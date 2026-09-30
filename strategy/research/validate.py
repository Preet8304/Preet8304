"""Out-of-sample validation of the FINAL parameters (chosen on ETH 2021-11..2024-12 only)."""
import numpy as np
from common import aligned, metrics, fmt, monthly_table
from engine import run, Market
from improved import TrendBreakout
from original import MeanReversion, Breakout

FINAL = dict(ch_len=100, outer=1.4, trend_len=400, stop_atr=2.0, trail_atr=3.0, adx_min=20)
IS_END = 1735689600

times, data = aligned(["ETHUSD", "SOLUSD"])
arr = {s: tuple(data[s][k].values for k in ["open", "high", "low", "close"]) for s in data}
oos_i = int(np.searchsorted(times, IS_END))
sol_i = int(np.argmax(~np.isnan(arr["SOLUSD"][3])))

def mk(sym, kind="final", **kw):
    d = arr[sym]
    if kind == "final":
        return Market(sym, *d, [TrendBreakout(np.nan_to_num(d), **{**FINAL, **kw})])
    return Market(sym, *d, [MeanReversion(np.nan_to_num(d)), Breakout(np.nan_to_num(d))], no_opposite=True)

def report(label, markets, start, sizing=("risk", 0.01, 3.0), show_table=False):
    eq, tr = run(times, markets, sizing=sizing, start_i=start)
    m, mo = metrics(times, eq, tr, start_i=start, capital=10_000)
    print(f"{label:48s} {fmt(m)}")
    if show_table:
        print(monthly_table(mo).to_string())
    return m, mo, eq, tr

if __name__ == "__main__":
    print("== ETH in-sample (2021-11..2024-12), used for tuning ==")
    eq, tr = run(times, [mk("ETHUSD")], end_i=oos_i)
    m, _ = metrics(times, eq, tr, end_i=oos_i, capital=10_000); print(f"{'ETH final IS':48s} {fmt(m)}")
    print("== OUT-OF-SAMPLE ==")
    report("ETH final 2025-01..2026-09", [mk("ETHUSD")], oos_i)
    report("SOL final 2024-04..2026-09 (never tuned)", [mk("SOLUSD")], sol_i)
    report("ETH+SOL final 2025-01..2026-09", [mk("ETHUSD"), mk("SOLUSD")], oos_i)
    report("ETH long-only 2025-01..", [mk("ETHUSD", allow_short=False)], oos_i)
    print("== original strategy, same period, realistic costs, same 1% risk sizing ==")
    report("ETH+SOL ORIGINAL 2025-01..2026-09", [mk("ETHUSD", "orig"), mk("SOLUSD", "orig")], oos_i)
