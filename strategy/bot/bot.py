"""Trend-Breakout trading bot for Delta Exchange perpetual futures (1h candles).

Modes
  paper  : live Delta candles, simulated fills (no API key needed)        python bot.py --mode paper
  live   : real orders on Delta Exchange (API key + secret in env vars)   python bot.py --mode live --env india-testnet
  replay : runs the bot hour-by-hour over the local candle DB (offline test of the full loop)
           python bot.py --mode replay --from 2025-01-01

Every hour, just after the candle closes:
  1. sync fills (paper) / reconcile the exchange position (live)
  2. in a position -> ratchet the trailing stop (edit the reduce-only stop order), exit on regime flip
  3. flat          -> check entry signal on the closed bar, size by risk, market entry + protective stop
  4. account guards: monthly loss limit (no new entries), max-drawdown kill switch (flatten + halt)
"""
import argparse
import json
import logging
import math
import os
import sqlite3
import time
from datetime import datetime, timezone

import logic
from delta_client import DeltaClient

HERE = os.path.dirname(os.path.abspath(__file__))
H = 3600
log = logging.getLogger("bot")


# ---------------------------------------------------------------- data sources
class LiveData:
    def __init__(self, client):
        self.client = client

    def closed(self, symbol, now):
        end = (int(now) // H) * H          # open time of the still-forming bar
        out, cursor = [], end
        while len(out) < logic.WINDOW:
            chunk = self.client.candles(symbol, "1h", cursor - 2000 * H, cursor - 1) or []
            if not chunk:
                break
            out = sorted(chunk, key=lambda c: c["time"]) + out
            cursor = min(c["time"] for c in chunk)
        bars = {c["time"]: c for c in out if c["time"] + H <= now}
        return [bars[k] for k in sorted(bars)][-logic.WINDOW:]


class ReplayData:
    def __init__(self, db):
        self.cache = {}
        self.db = db

    def _all(self, symbol):
        if symbol not in self.cache:
            con = sqlite3.connect(self.db)
            rows = con.execute("select time,open,high,low,close from candles where symbol=? and resolution='1h' "
                               "order by time", (symbol,)).fetchall()
            con.close()
            self.cache[symbol] = [dict(time=r[0], open=r[1], high=r[2], low=r[3], close=r[4]) for r in rows]
            self.cache[symbol + "_t"] = [r[0] for r in rows]
        return self.cache[symbol]

    def closed(self, symbol, now):
        import bisect
        rows = self._all(symbol)
        j = bisect.bisect_right(self.cache[symbol + "_t"], now - H)
        return rows[max(0, j - logic.WINDOW):j]


# ---------------------------------------------------------------- brokers
class PaperBroker:
    """Simulated fills with the SAME cost model and fill rules as research/engine.py."""
    FEE, SLIP, FUND = 0.0005 * 1.18, 0.0002, 0.0001 / 8

    def __init__(self, state, capital, contract_values):
        self.s = state.setdefault("paper", {"cash": capital, "pos": {}, "stops": {}, "seen": {}})
        self.cv = contract_values

    def equity(self):
        return self.s["cash"]

    def contract_value(self, sym):
        return self.cv[sym]

    def position(self, sym):
        p = self.s["pos"].get(sym)
        return (p["size"], p["entry"]) if p else (0, 0.0)

    def _fill(self, sym, side, size, px):
        """side 'buy'/'sell', size contracts (positive). Returns fill price."""
        sgn = 1 if side == "buy" else -1
        px = px * (1 + self.SLIP * sgn)
        qty = size * self.cv[sym]
        self.s["cash"] -= qty * px * self.FEE
        p = self.s["pos"].get(sym)
        if p is None:
            self.s["pos"][sym] = {"size": sgn * size, "entry": px}
        else:
            self.s["cash"] += (px - p["entry"]) * p["size"] * self.cv[sym]
            del self.s["pos"][sym]
            self.s["stops"].pop(sym, None)
        return px

    def market(self, sym, side, size, ref_px):
        return self._fill(sym, side, size, ref_px)

    def place_stop(self, sym, side, size, price):
        self.s["stops"][sym] = {"side": side, "size": size, "price": price}
        return f"paper-{sym}"

    def edit_stop(self, sym, oid, price, size):
        self.s["stops"][sym]["price"] = price

    def cancel(self, sym, oid):
        self.s["stops"].pop(sym, None)

    def stop_exists(self, sym, oid):
        return sym in self.s["stops"]

    def sync(self, sym, candles):
        """Process bars closed since last sync: funding, then stop triggers (gap-aware)."""
        last = self.s["seen"].get(sym, 0)
        for c in candles:
            if c["time"] <= last:
                continue
            p, st = self.s["pos"].get(sym), self.s["stops"].get(sym)
            if p:
                self.s["cash"] -= abs(p["size"]) * self.cv[sym] * c["close"] * self.FUND
            if p and st:
                if p["size"] > 0 and c["low"] <= st["price"]:
                    self._fill(sym, "sell", abs(p["size"]), min(c["open"], st["price"]))
                elif p["size"] < 0 and c["high"] >= st["price"]:
                    self._fill(sym, "buy", abs(p["size"]), max(c["open"], st["price"]))
        if candles:
            self.s["seen"][sym] = candles[-1]["time"]


class LiveBroker:
    def __init__(self, client, symbols, settle_asset, leverage):
        self.c = client
        self.products = {s: client.product(s) for s in symbols}
        self.settle = settle_asset
        for s, p in self.products.items():
            try:
                client.set_leverage(p["id"], leverage)
            except Exception as e:  # leverage may already be set / position open
                log.warning("set_leverage %s: %s", s, e)

    def pid(self, sym):
        return self.products[sym]["id"]

    def contract_value(self, sym):
        return float(self.products[sym]["contract_value"])

    def tick(self, sym):
        return float(self.products[sym]["tick_size"])

    def equity(self):
        for b in self.c.balances():
            if b.get("asset_symbol") == self.settle:
                return float(b.get("balance", 0))
        raise RuntimeError(f"settle asset {self.settle} not in wallet")

    def position(self, sym):
        p = self.c.position(self.pid(sym)) or {}
        return int(p.get("size") or 0), float(p.get("entry_price") or 0)

    def market(self, sym, side, size, ref_px):
        o = self.c.market_order(self.pid(sym), side, size)
        px = o.get("average_fill_price")
        if not px:  # fall back to the position's entry price
            time.sleep(1)
            px = self.position(sym)[1]
        return float(px)

    def _round(self, sym, price):
        t = self.tick(sym)
        return round(round(price / t) * t, 8)

    def place_stop(self, sym, side, size, price):
        return self.c.stop_order(self.pid(sym), side, size, self._round(sym, price))["id"]

    def edit_stop(self, sym, oid, price, size):
        self.c.edit_stop(self.pid(sym), oid, self._round(sym, price), size)

    def cancel(self, sym, oid):
        self.c.cancel(self.pid(sym), oid)

    def stop_exists(self, sym, oid):
        return any(o["id"] == oid for o in (self.c.open_orders(self.pid(sym)) or []))

    def sync(self, sym, candles):
        pass


# ---------------------------------------------------------------- bot
class Bot:
    def __init__(self, cfg, data, broker, state, state_path, simulated_fills=False):
        self.cfg, self.data, self.broker, self.state_path = cfg, data, broker, state_path
        self.state = state
        self.simulated = simulated_fills   # replay: fill market orders at the next bar's open
        self.state.setdefault("positions", {})
        self.state.setdefault("trades", [])

    def save(self):
        if self.state_path:
            tmp = self.state_path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self.state, f, indent=1)
            os.replace(tmp, self.state_path)

    def _guards(self, now):
        eq = self.broker.equity()
        st = self.state
        st["peak"] = max(st.get("peak", eq), eq)
        month = datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m")
        if st.get("month") != month:
            st["month"], st["month_start_eq"] = month, eq
        if eq < st["peak"] * (1 - self.cfg["kill_drawdown"]):
            if not st.get("halted"):
                log.error("KILL SWITCH: equity %.2f < %.0f%% below peak %.2f -> flatten + halt",
                          eq, 100 * self.cfg["kill_drawdown"], st["peak"])
            st["halted"] = True
        month_ret = eq / st["month_start_eq"] - 1
        return eq, month_ret <= -self.cfg["monthly_loss_limit"]

    def _close(self, sym, pos, px, reason, now):
        side = "sell" if pos["side"] > 0 else "buy"
        size = abs(self.broker.position(sym)[0])
        if pos.get("stop_id"):
            try:
                self.broker.cancel(sym, pos["stop_id"])
            except Exception as e:
                log.warning("cancel stop %s: %s", sym, e)
        fill = self.broker.market(sym, side, size, px) if size else px
        self._record(sym, pos, fill, reason, now)

    def _record(self, sym, pos, exit_px, reason, now):
        self.state["positions"].pop(sym, None)
        self.state["trades"].append(dict(symbol=sym, side=pos["side"], entry_time=pos["entry_time"],
                                         entry=pos["entry_price"], exit_time=int(now), exit=exit_px,
                                         reason=reason, equity=self.broker.equity()))
        log.info("EXIT %s %s @ %.4f (%s) equity=%.2f", sym, "LONG" if pos["side"] > 0 else "SHORT",
                 exit_px, reason, self.broker.equity())

    def step(self, now):
        eq, month_locked = self._guards(now)
        for sym in self.cfg["symbols"]:
            candles = self.data.closed(sym, now)
            if len(candles) < 1000:
                log.warning("%s: only %d candles, skipping", sym, len(candles))
                continue
            last_t = candles[-1]["time"]
            if self.state.get("last_bar", {}).get(sym) == last_t:
                continue                       # this bar already processed
            self.broker.sync(sym, candles)
            t, strat = logic.build(candles, self.cfg.get("params", logic.FINAL_PARAMS))
            px = candles[-1]["close"]
            pos = self.state["positions"].get(sym)
            size, _ = self.broker.position(sym)

            # -- reconcile: position closed by the exchange stop?
            if pos and size == 0:
                self._record(sym, pos, pos["stop"], "stop", now)
                pos = None
            elif not pos and size != 0:
                log.error("%s: exchange position %s not opened by this bot - not touching it", sym, size)
                self.state.setdefault("last_bar", {})[sym] = last_t
                continue

            if pos and self.state.get("halted"):
                self._close(sym, pos, px, "kill-switch", now)
                pos = None
            elif pos:
                if logic.regime_exit(strat, pos["side"]):
                    self._close(sym, pos, self._ref(sym, now, px), "regime", now)
                    pos = None
                else:
                    new_stop = logic.trailing_stop(strat, t, pos["side"], pos["entry_time"],
                                                   pos["entry_price"], pos["initial_stop"])
                    moved = (new_stop - pos["stop"]) * pos["side"] > 0
                    if moved:
                        pos["stop"] = new_stop
                        log.info("%s trail stop -> %.4f", sym, new_stop)
                    if not (pos.get("stop_id") and self.broker.stop_exists(sym, pos["stop_id"])):
                        # protective stop missing (placement failed / cancelled manually) -> always re-place it
                        pos["stop_id"] = self.broker.place_stop(
                            sym, "sell" if pos["side"] > 0 else "buy", abs(size), pos["stop"])
                    elif moved:
                        self.broker.edit_stop(sym, pos["stop_id"], pos["stop"], abs(size))
            elif not self.state.get("halted") and not month_locked:
                sig = logic.entry_signal(strat)
                if sig:
                    side, stop = sig
                    n = logic.contracts_for(self.broker.equity(), px, stop, self.broker.contract_value(sym),
                                            self.cfg["risk_per_trade"], self.cfg["max_notional_leverage"])
                    if n >= 1:
                        fill = self.broker.market(sym, "buy" if side > 0 else "sell", n, self._ref(sym, now, px))
                        pos = dict(side=side, entry_time=last_t + H, entry_price=fill, initial_stop=stop, stop=stop)
                        self.state["positions"][sym] = pos
                        log.info("ENTRY %s %s %d @ %.4f stop %.4f", sym, "LONG" if side > 0 else "SHORT", n, fill, stop)
                        if (fill - stop) * side <= 0:          # filled beyond the stop -> get out
                            self._close(sym, pos, fill, "filled-beyond-stop", now)
                        else:
                            try:
                                pos["stop_id"] = self.broker.place_stop(sym, "sell" if side > 0 else "buy", n, stop)
                            except Exception:
                                log.exception("%s: protective stop rejected -> closing position", sym)
                                self._close(sym, pos, fill, "no-stop", now)
            self.state.setdefault("last_bar", {})[sym] = last_t
        self.save()

    def _ref(self, sym, now, last_close):
        """Reference price for a market order. Replay: open of the bar that just started (as the backtest).
        Paper on live data: last close (~ next open). Live: ignored, the exchange fills it."""
        if not self.simulated:
            return last_close
        nxt = self.data.closed(sym, now + H)
        return nxt[-1]["open"] if nxt and nxt[-1]["time"] == (int(now) // H) * H else last_close


# ---------------------------------------------------------------- main
def load_cfg(path):
    with open(path) as f:
        return json.load(f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["paper", "live", "replay"], default="paper")
    ap.add_argument("--config", default=os.path.join(HERE, "config.json"))
    ap.add_argument("--env", default=None, help="india | india-testnet | global | global-testnet")
    ap.add_argument("--once", action="store_true", help="run one cycle and exit (for cron)")
    ap.add_argument("--from", dest="start", default="2025-01-01", help="replay start date")
    ap.add_argument("--to", dest="end", default=None, help="replay end date")
    a = ap.parse_args()
    cfg = load_cfg(a.config)
    env = a.env or cfg.get("env", "india-testnet")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(os.path.join(HERE, f"bot_{a.mode}.log"))])
    state_path = os.path.join(HERE, f"state_{a.mode}.json")
    state = json.load(open(state_path)) if (os.path.exists(state_path) and a.mode != "replay") else {}

    if a.mode == "replay":
        db = os.path.join(HERE, "..", "data", "trading.db")
        data = ReplayData(db)
        broker = PaperBroker(state, cfg["paper_capital"], cfg["paper_contract_values"])
        bot = Bot(cfg, data, broker, state, None, simulated_fills=True)
        logging.getLogger().setLevel(logging.WARNING)
        t0 = int(datetime.fromisoformat(a.start).replace(tzinfo=timezone.utc).timestamp())
        t1 = int(datetime.fromisoformat(a.end).replace(tzinfo=timezone.utc).timestamp()) if a.end else \
            max(data._all(s)[-1]["time"] for s in cfg["symbols"]) + H
        for now in range(t0, t1 + 1, H):
            bot.step(now + 5)
        json.dump(state, open(os.path.join(HERE, "replay_result.json"), "w"), indent=1)
        print(f"replay done: equity {broker.equity():.2f}, trades {len(state['trades'])}")
        return

    client = DeltaClient(os.environ.get("DELTA_API_KEY", ""), os.environ.get("DELTA_API_SECRET", ""), env)
    data = LiveData(client)
    if a.mode == "live":
        if not client.key or not client.secret:
            raise SystemExit("set DELTA_API_KEY and DELTA_API_SECRET")
        broker = LiveBroker(client, cfg["symbols"], cfg["settle_asset"], cfg["exchange_leverage"])
    else:
        cv = {s: float(client.product(s)["contract_value"]) for s in cfg["symbols"]}
        broker = PaperBroker(state, cfg["paper_capital"], cv)
    bot = Bot(cfg, data, broker, state, state_path)
    log.info("started mode=%s env=%s symbols=%s", a.mode, env, cfg["symbols"])
    while True:
        try:
            bot.step(time.time())
        except Exception:
            log.exception("cycle failed; will retry next cycle")
        if a.once:
            break
        nxt = (int(time.time()) // H + 1) * H + cfg.get("delay_after_close_s", 10)
        time.sleep(max(5, nxt - time.time()))


if __name__ == "__main__":
    main()
