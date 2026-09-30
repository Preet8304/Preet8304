"""Robustness: run EVERY swept parameter combo on held-out data (no selection) - does the family hold up?"""
import itertools, warnings
import numpy as np
from multiprocessing import Pool
from common import metrics
from engine import run, Market
from improved import TrendBreakout
from validate import times, arr, oos_i, sol_i
warnings.filterwarnings("ignore")

def job(args):
    sym, start, p = args
    ch, outer, tl, sa, ta, am = p
    d = arr[sym]
    s = TrendBreakout(np.nan_to_num(d), ch, outer, tl, stop_atr=sa, trail_atr=ta, adx_min=am)
    eq, tr = run(times, [Market(sym, *d, [s])], start_i=start)
    m, _ = metrics(times, eq, tr, start_i=start, capital=10_000)
    return sym, p, m["total_return_pct"], m["mar"], m["profit_factor"]

grid = list(itertools.product([50, 100, 200], [1.0, 1.4, 1.8], [200, 400, 800], [2.0, 3.0], [3.0, 5.0], [0, 20]))
with Pool() as pool:
    res = pool.map(job, [("ETHUSD", oos_i, p) for p in grid] + [("SOLUSD", sol_i, p) for p in grid])
for sym in ["ETHUSD", "SOLUSD"]:
    r = [x for x in res if x[0] == sym]
    print(sym, "combos profitable:", f"{np.mean([x[2] > 0 for x in r]):.0%}", " median return:", round(np.median([x[2] for x in r]), 1),
          " median PF:", round(np.median([x[4] for x in r]), 2))
    for k, nm in enumerate(["ch", "outer", "trend", "stop", "trail", "adx"]):
        vals = sorted(set(x[1][k] for x in r))
        print("   ", nm, {v: round(np.median([x[2] for x in r if x[1][k] == v]), 1) for v in vals})
