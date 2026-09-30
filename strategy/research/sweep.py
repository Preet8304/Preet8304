"""In-sample parameter sweep on ETHUSD 2021-11 .. 2024-12 ONLY (2025+ and all SOL data are held out)."""
import itertools, sys, json
import numpy as np
from multiprocessing import Pool
from common import load, metrics
from engine import run, Market
from improved import TrendBreakout, TrendPullback

IS_END = 1735689600  # 2025-01-01 UTC
df = load("ETHUSD")
t = df.time.values
d = tuple(df[k].values for k in ["open", "high", "low", "close"])
end_i = int(np.searchsorted(t, IS_END))
KIND = sys.argv[1]

def job(p):
    ch, outer, tl, sa, ta, am = p
    cls = TrendBreakout if KIND == "TB" else TrendPullback
    s = cls(d, ch, outer, tl, stop_atr=sa, trail_atr=ta, adx_min=am)
    eq, tr = run(t, [Market("ETHUSD", *d, [s])], sizing=("risk", 0.01, 3.0), end_i=end_i)
    m, _ = metrics(t, eq, tr, end_i=end_i, capital=10_000)
    return dict(p=p, **{k: round(float(v), 2) for k, v in m.items()})

grid = list(itertools.product([50, 100, 200], [1.0, 1.4, 1.8], [200, 400, 800], [2.0, 3.0], [3.0, 5.0], [0, 20]))
with Pool() as pool:
    res = pool.map(job, grid)
json.dump(res, open(f"sweep_{KIND}.json", "w"))
res.sort(key=lambda r: -r["mar"])
for r in res[:15]:
    print(r["p"], "CAGR", r["cagr_pct"], "DD", r["max_dd_pct"], "MAR", r["mar"], "Sh", r["sharpe"], "+mo", r["pos_months_pct"], "n", r["trades"], "PF", r["profit_factor"])
print("share of combos profitable:", np.mean([r["total_return_pct"] > 0 for r in res]))
print("median MAR:", np.median([r["mar"] for r in res]))
