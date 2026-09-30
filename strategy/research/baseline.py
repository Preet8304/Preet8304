"""Backtest of the ORIGINAL Pine strategy under Pine-like and realistic assumptions."""
import numpy as np
from common import load, metrics, fmt, monthly_table
from engine import run, Market, Costs
from original import MeanReversion, Breakout

PINE_COSTS = Costs(fee=0.0001, slippage=0.0, funding_per_bar=0.0)   # script: 0.01% commission, no slippage
REAL = Costs()

for sym in ["ETHUSD", "SOLUSD"]:
    df = load(sym)
    d = tuple(df[k].values for k in ["open", "high", "low", "close"])
    t = df.time.values
    for label, sl in [("MR+BO", lambda: [MeanReversion(d), Breakout(d)]),
                      ("MR only", lambda: [MeanReversion(d)]), ("BO only", lambda: [Breakout(d)])]:
        for cname, costs, sizing in [("Pine 10%eq 0.01%fee", PINE_COSTS, ("fraction", 0.10)),
                                     ("Real 10%eq", REAL, ("fraction", 0.10)),
                                     ("Real 100%eq (repo 10x lev)", REAL, ("fraction", 1.0))]:
            eq, tr = run(t, [Market(sym, *d, sl(), no_opposite=True)], sizing=sizing, costs=costs)
            m, mo = metrics(t, eq, tr, capital=10_000)
            print(f"{sym:7s} {label:8s} {cname:28s} {fmt(m)}")
