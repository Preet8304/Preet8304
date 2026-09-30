"""Data loading and performance metrics."""
import os
import sqlite3
import numpy as np
import pandas as pd

DB = os.path.join(os.path.dirname(__file__), "..", "data", "trading.db")


def load(symbol, resolution="1h"):
    con = sqlite3.connect(DB)
    df = pd.read_sql("select time,open,high,low,close,volume from candles where symbol=? and resolution=? order by time",
                     con, params=(symbol, resolution))
    con.close()
    return df


def aligned(symbols, resolution="1h"):
    """Return common hourly timeline (union) and per-symbol OHLC arrays (NaN where a symbol has no data)."""
    frames = {s: load(s, resolution).set_index("time") for s in symbols}
    idx = sorted(set().union(*[f.index for f in frames.values()]))
    out = {s: f.reindex(idx) for s, f in frames.items()}
    return np.array(idx), out


def metrics(times, eq, trades, start_i=0, end_i=None, capital=None):
    end_i = len(eq) if end_i is None else end_i
    t = pd.to_datetime(times[start_i:end_i], unit="s", utc=True)
    e = pd.Series(eq[start_i:end_i], index=t).ffill().dropna()
    if capital is None:
        capital = e.iloc[0]
    e0 = pd.concat([pd.Series([capital], index=[e.index[0] - pd.Timedelta(hours=1)]), e])
    peak = e0.cummax()
    dd = (e0 / peak - 1).min()
    years = (e0.index[-1] - e0.index[0]).total_seconds() / (365.25 * 86400)
    total = e0.iloc[-1] / capital - 1
    cagr = (e0.iloc[-1] / capital) ** (1 / years) - 1 if years > 0 and e0.iloc[-1] > 0 else -1
    me = e0.resample("ME").last()
    monthly = me.pct_change()
    monthly.iloc[0] = me.iloc[0] / capital - 1
    daily = e0.resample("D").last().pct_change().dropna()
    sharpe = daily.mean() / daily.std() * np.sqrt(365) if daily.std() > 0 else 0
    tr = [x for x in trades if start_i <= x["entry_i"] < end_i]
    wins = [x["net"] for x in tr if x["net"] > 0]
    losses = [x["net"] for x in tr if x["net"] <= 0]
    return dict(
        total_return_pct=100 * total, cagr_pct=100 * cagr, max_dd_pct=100 * dd,
        avg_month_pct=100 * monthly.mean(), median_month_pct=100 * monthly.median(),
        pos_months_pct=100 * (monthly > 0).mean(), worst_month_pct=100 * monthly.min(),
        best_month_pct=100 * monthly.max(), sharpe=sharpe,
        mar=(cagr / -dd) if dd < 0 else np.nan,
        trades=len(tr), win_rate_pct=100 * len(wins) / max(len(tr), 1),
        profit_factor=sum(wins) / -sum(losses) if losses and sum(losses) < 0 else np.inf,
        avg_r=np.mean([x["r"] for x in tr]) if tr else 0,
    ), monthly


def fmt(m):
    return (f"ret {m['total_return_pct']:8.1f}%  CAGR {m['cagr_pct']:6.1f}%  maxDD {m['max_dd_pct']:6.1f}%  "
            f"avgMo {m['avg_month_pct']:5.2f}%  +mo {m['pos_months_pct']:4.0f}%  worstMo {m['worst_month_pct']:6.1f}%  "
            f"Sharpe {m['sharpe']:4.2f}  MAR {m['mar']:5.2f}  n {m['trades']:4d}  win {m['win_rate_pct']:4.1f}%  "
            f"PF {m['profit_factor']:4.2f}  avgR {m['avg_r']:5.2f}")


def monthly_table(monthly):
    df = pd.DataFrame({"y": monthly.index.year, "m": monthly.index.month, "r": 100 * monthly.values})
    tab = df.pivot(index="y", columns="m", values="r")
    tab.columns = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][:len(tab.columns)] \
        if len(tab.columns) == 12 else [pd.Timestamp(2000, c, 1).strftime("%b") for c in tab.columns]
    yearly = df.groupby("y")["r"].apply(lambda r: 100 * (np.prod(1 + r / 100) - 1))
    tab["Year"] = yearly
    return tab.round(1)
