"""Builds ../REPORT_DATA.md: final-strategy results, risk levels, monthly % tables, bootstrap risk estimates."""
import warnings
import numpy as np
import pandas as pd
from common import metrics, fmt, monthly_table
from engine import run, Market
from validate import times, arr, oos_i, sol_i, mk
warnings.filterwarnings("ignore")
out = []
P = out.append

def row(label, m):
    return (f"| {label} | {m['total_return_pct']:.1f}% | {m['cagr_pct']:.1f}% | {m['max_dd_pct']:.1f}% | {m['avg_month_pct']:.2f}% | "
            f"{m['median_month_pct']:.2f}% | {m['pos_months_pct']:.0f}% | {m['worst_month_pct']:.1f}% | {m['sharpe']:.2f} | "
            f"{m['trades']} | {m['win_rate_pct']:.0f}% | {m['profit_factor']:.2f} |")
HDR = ("| Run | Total | CAGR | Max DD | Avg month | Median month | Positive months | Worst month | Sharpe | Trades | Win | PF |\n"
       "|---|---|---|---|---|---|---|---|---|---|---|---|")

def bootstrap(monthly, n=20000, seed=1):
    rng = np.random.default_rng(seed)
    r = monthly.values
    sims = rng.choice(r, size=(n, 12), replace=True)
    yr = np.prod(1 + sims, axis=1) - 1
    paths = np.cumprod(1 + sims, axis=1)
    peak = np.maximum.accumulate(np.concatenate([np.ones((n, 1)), paths], axis=1), axis=1)[:, 1:]
    dd = (paths / peak - 1).min(axis=1)
    return np.mean(yr < 0), np.percentile(yr, [5, 50, 95]), np.percentile(dd, 5)

P("## Risk level vs return (ETH + SOL portfolio, Apr 2024 - Sep 2026, realistic costs)\n")
P(HDR)
monthly_by_risk = {}
for risk in [0.005, 0.0075, 0.01, 0.015, 0.02]:
    eq, tr = run(times, [mk("ETHUSD"), mk("SOLUSD")], sizing=("risk", risk, 3.0), start_i=sol_i)
    m, mo = metrics(times, eq, tr, start_i=sol_i, capital=10_000)
    monthly_by_risk[risk] = mo
    P(row(f"{risk*100:.2g}% risk/trade", m))

P("\n## Final strategy vs original (same period, same costs)\n")
P(HDR)
for label, mks, st, sz in [
        ("FINAL ETH only, Nov 2021-Sep 2026 (to 2024 = tuning)", [mk("ETHUSD")], 0, ("risk", 0.01, 3.0)),
        ("FINAL ETH only, 2025-2026 held-out", [mk("ETHUSD")], oos_i, ("risk", 0.01, 3.0)),
        ("FINAL SOL only, held-out", [mk("SOLUSD")], sol_i, ("risk", 0.01, 3.0)),
        ("FINAL ETH+SOL, 0.75% risk, Apr 2024-Sep 2026", [mk("ETHUSD"), mk("SOLUSD")], sol_i, ("risk", 0.0075, 3.0)),
        ("ORIGINAL ETH only, Pine sizing 10% equity", [mk("ETHUSD", "orig")], 0, ("fraction", 0.10)),
        ("ORIGINAL ETH only, repo sizing (10x = 100% equity)", [mk("ETHUSD", "orig")], 0, ("fraction", 1.0)),
        ("ORIGINAL ETH+SOL, 0.75% risk, Apr 2024-Sep 2026", [mk("ETHUSD", "orig"), mk("SOLUSD", "orig")], sol_i, ("risk", 0.0075, 3.0)),
]:
    eq, tr = run(times, mks, sizing=sz, start_i=st)
    m, mo = metrics(times, eq, tr, start_i=st, capital=10_000)
    P(row(label, m))
    if label.startswith("FINAL ETH only, Nov"):
        eth_mo, eth_tr = mo, tr
    if label.startswith("FINAL ETH+SOL"):
        port_mo, port_tr = mo, tr

def md(tab):
    return tab.to_markdown() if hasattr(tab, "to_markdown") else tab.to_string()

P("\n## Monthly % returns - FINAL, ETH only, 1% risk/trade (2021-11..2024-12 tuning, 2025+ held-out)\n")
P(md(monthly_table(eth_mo)))
P("\n## Monthly % returns - FINAL, ETH + SOL portfolio, 0.75% risk/trade\n")
P(md(monthly_table(port_mo)))

P("\n## Bootstrap of monthly returns (20,000 simulated years)\n")
P("| Series | P(losing year) | 5th pct year | Median year | 95th pct year | 5th pct worst 12-mo drawdown |\n|---|---|---|---|---|---|")
for label, mo in [("ETH only 1%", eth_mo), ("ETH+SOL 0.75%", port_mo)]:
    pl, pct, dd = bootstrap(mo.dropna())
    P(f"| {label} | {pl:.0%} | {pct[0]*100:.1f}% | {pct[1]*100:.1f}% | {pct[2]*100:.1f}% | {dd*100:.1f}% |")

P("\n## Trade breakdown - FINAL ETH+SOL portfolio\n")
df = pd.DataFrame(port_tr)
df = df[df.entry_i >= sol_i]
g = df.groupby(["symbol", "side"]).agg(trades=("net", "size"), win=("net", lambda x: f"{(x > 0).mean():.0%}"),
                                        net_usd=("net", "sum"), avg_R=("r", "mean")).round(2)
P(md(g))
g2 = df.groupby("reason").agg(trades=("net", "size"), net_usd=("net", "sum"), avg_R=("r", "mean")).round(2)
P("\n" + md(g2))
df.assign(entry_time=pd.to_datetime(df.entry_time, unit="s"), exit_time=pd.to_datetime(df.exit_time, unit="s")) \
  .to_csv("../final_trades.csv", index=False)
open("../REPORT_DATA.md", "w").write("\n".join(out) + "\n")
print("\n".join(out))
