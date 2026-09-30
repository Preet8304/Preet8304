"""Event-driven bar backtester with realistic fills for Delta Exchange perpetual futures.

Fill rules (no look-ahead):
  * A signal computed on bar i's close is filled at bar i+1's open (TradingView default).
  * Stop-loss is a resting stop: filled at the stop price, or at the open if the bar gaps through it.
  * Take-profit is a resting limit: filled at the TP price, or at the open if it gaps through.
  * If stop and TP are both inside one bar, the stop is assumed to fill first (worst case).
  * Every fill pays taker fee + slippage; open positions pay a funding cost each bar.
"""
from dataclasses import dataclass, field
import numpy as np


@dataclass
class Costs:
    fee: float = 0.0005 * 1.18   # Delta Exchange taker 0.05% + 18% GST on fees
    slippage: float = 0.0002     # 0.02% adverse per fill
    funding_per_bar: float = 0.0001 / 8  # ~0.01% per 8h, charged to every position (conservative)


@dataclass
class Position:
    sleeve: str
    side: int              # +1 long, -1 short
    entry: float
    qty: float
    stop: float
    tp: float = None
    entry_i: int = 0
    risk: float = 0.0      # initial |entry - stop|
    fees: float = 0.0
    extra: dict = field(default_factory=dict)


class Sleeve:
    """One independent strategy component on one market. Subclasses implement signal()/manage()."""
    name = "sleeve"

    def signal(self, i):
        """Called on bar i close while flat. Return (side, stop, tp) or None."""
        return None

    def manage(self, i, pos):
        """Called on bar i close while in a position. May move pos.stop/pos.tp.
        Return True to exit at the next bar's open."""
        return False


@dataclass
class Market:
    symbol: str
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    sleeves: list
    no_opposite: bool = False   # block entries opposite to another open sleeve on this market


def run(times, markets, capital=10_000.0, sizing=("risk", 0.01, 3.0), costs=Costs(), start_i=0, end_i=None):
    """sizing: ("fraction", f)        -> notional = f * equity
               ("risk", r, max_lev)   -> qty = r * equity / stop_distance, notional capped at max_lev * equity
    """
    n = len(times) if end_i is None else end_i
    cash = capital
    eq_curve = np.full(n, np.nan)
    trades = []
    open_pos = {}      # (sym, sleeve) -> Position
    pending = {}       # (sym, sleeve) -> ("enter", side, stop, tp, signal_i) | ("exit",)

    def fill_px(px, side_of_trade):
        return px * (1 + costs.slippage * side_of_trade)

    def close(key, pos, px, i, reason):
        nonlocal cash
        px = fill_px(px, -pos.side)
        fee = abs(pos.qty * px) * costs.fee
        pnl = pos.side * (px - pos.entry) * pos.qty - fee
        cash += pnl
        # net trade result including entry fee, exit fee and funding paid while open
        net = pos.side * (px - pos.entry) * pos.qty - pos.fees - fee - pos.extra.get("funding", 0.0)
        trades.append(dict(symbol=key[0], sleeve=pos.sleeve, side=pos.side, entry_i=pos.entry_i, exit_i=i,
                           entry_time=int(times[pos.entry_i]), exit_time=int(times[i]),
                           entry=pos.entry, exit=px, qty=pos.qty, reason=reason,
                           net=net, r=net / max(pos.risk * pos.qty, 1e-12)))
        del open_pos[key]

    for i in range(start_i, n):
        # ---- 1. fills at the open ----
        for m in markets:
            o = m.o[i]
            if np.isnan(o):
                continue
            for s in m.sleeves:
                key = (m.symbol, s.name)
                p = pending.pop(key, None)
                if p is None:
                    continue
                if p[0] == "exit" and key in open_pos:
                    close(key, open_pos[key], o, i, "signal")
                elif p[0] == "enter" and key not in open_pos:
                    _, side, stop, tp, _si = p
                    entry = fill_px(o, side)
                    dist = side * (entry - stop)
                    if dist <= 0:           # opened beyond the stop: skip trade
                        continue
                    equity = max(cash, 0.0)
                    if sizing[0] == "fraction":
                        qty = equity * sizing[1] / entry
                    else:
                        qty = min(equity * sizing[1] / dist, equity * sizing[2] / entry)
                    if qty <= 0:
                        continue
                    fee = qty * entry * costs.fee
                    cash -= fee
                    open_pos[key] = Position(s.name, side, entry, qty, stop, tp, i, dist, fee)

        # ---- 2. intrabar stops / targets ----
        for m in markets:
            if np.isnan(m.o[i]):
                continue
            o, h, l = m.o[i], m.h[i], m.l[i]
            for s in m.sleeves:
                key = (m.symbol, s.name)
                pos = open_pos.get(key)
                if pos is None:
                    continue
                f = pos.qty * m.c[i] * costs.funding_per_bar
                cash -= f
                pos.extra["funding"] = pos.extra.get("funding", 0.0) + f
                if pos.side > 0:
                    if l <= pos.stop:
                        close(key, pos, min(o, pos.stop), i, "stop")
                    elif pos.tp is not None and h >= pos.tp:
                        close(key, pos, max(o, pos.tp), i, "target")
                else:
                    if h >= pos.stop:
                        close(key, pos, max(o, pos.stop), i, "stop")
                    elif pos.tp is not None and l <= pos.tp:
                        close(key, pos, min(o, pos.tp), i, "target")

        # ---- 3. bar close: mark-to-market, manage, new signals ----
        mtm = cash
        for (sym, _), pos in open_pos.items():
            m = next(mm for mm in markets if mm.symbol == sym)
            px = m.c[i] if not np.isnan(m.c[i]) else pos.entry
            mtm += pos.side * (px - pos.entry) * pos.qty
        eq_curve[i] = mtm
        if i == n - 1:
            break
        for m in markets:
            if np.isnan(m.c[i]):
                continue
            for s in m.sleeves:
                key = (m.symbol, s.name)
                if key in open_pos:
                    if s.manage(i, open_pos[key]):
                        pending[key] = ("exit",)
                elif key not in pending:
                    sig = s.signal(i)
                    if sig is None:
                        continue
                    side = sig[0]
                    if m.no_opposite and any(k[0] == m.symbol and p.side == -side for k, p in open_pos.items()):
                        continue
                    pending[key] = ("enter", side, sig[1], sig[2] if len(sig) > 2 else None, i)

    # close anything still open at the last bar's close
    for key, pos in list(open_pos.items()):
        m = next(mm for mm in markets if mm.symbol == key[0])
        close(key, pos, m.c[n - 1], n - 1, "end")
    eq_curve[n - 1] = cash
    return eq_curve, trades
