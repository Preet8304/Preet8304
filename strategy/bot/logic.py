"""Live decision logic. Uses the SAME TrendBreakout class as the backtest so signals are identical.

All functions are stateless given candles + the position's entry bar/price, so a restart never loses the
trailing-stop state: the stop is recomputed from history exactly as the backtest engine does it.
"""
import os
import sys
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "research"))
from improved import TrendBreakout  # noqa: E402

FINAL_PARAMS = dict(ch_len=100, outer=1.4, trend_len=400, stop_atr=2.0, trail_atr=3.0, adx_min=20)
WINDOW = 3000  # closed 1h bars fed to the indicators (EMA-400 / IIR filters fully warmed up)


def build(candles, params=FINAL_PARAMS):
    """candles: list of dicts (time, open, high, low, close) sorted ascending, CLOSED bars only."""
    t = np.array([c["time"] for c in candles], dtype=np.int64)
    d = tuple(np.array([float(c[k]) for c in candles]) for k in ("open", "high", "low", "close"))
    return t, TrendBreakout(d, **params)


def entry_signal(strat):
    """Signal on the last closed bar -> (side, stop) or None. side: +1 long / -1 short."""
    i = len(strat.c) - 1
    s = strat.signal(i)
    return None if s is None else (s[0], float(s[1]))


def trailing_stop(strat, t, side, entry_time, entry_price, initial_stop):
    """Recompute the ratcheted chandelier stop through the last closed bar (same as engine + manage())."""
    e = int(np.searchsorted(t, entry_time))
    stop, ext = initial_stop, entry_price
    for k in range(e, len(t)):
        if side > 0:
            ext = max(ext, strat.h[k])
            stop = max(stop, ext - strat.trail_atr * strat.atr[k])
        else:
            ext = min(ext, strat.l[k])
            stop = min(stop, ext + strat.trail_atr * strat.atr[k])
    return float(stop)


def regime_exit(strat, side):
    i = len(strat.c) - 1
    return (side > 0 and strat.c[i] < strat.trend[i]) or (side < 0 and strat.c[i] > strat.trend[i])


def contracts_for(equity, entry, stop, contract_value, risk_pct, max_lev):
    """Risk-based size in whole contracts, capped by max notional leverage."""
    dist = abs(entry - stop)
    if dist <= 0 or equity <= 0:
        return 0
    by_risk = equity * risk_pct / (dist * contract_value)
    by_lev = equity * max_lev / (entry * contract_value)
    return int(max(0, min(by_risk, by_lev)))
