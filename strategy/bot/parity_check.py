"""Compare the bot's replay trades (bot.py --mode replay) with the research backtest over the same period."""
import json, os, sys, warnings
warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "research"))
import numpy as np
from engine import run
from validate import times, oos_i, mk

cfg = json.load(open(os.path.join(HERE, "config.json")))
rep = json.load(open(os.path.join(HERE, "replay_result.json")))
eq, tr = run(times, [mk(s) for s in cfg["symbols"]], sizing=("risk", cfg["risk_per_trade"], cfg["max_notional_leverage"]),
             start_i=oos_i)
bt = {(x["symbol"], x["entry_time"], x["side"]) for x in tr}
bot = {(x["symbol"], x["entry_time"], x["side"]) for x in rep["trades"]}
print(f"backtest trades {len(bt)}  bot trades {len(bot)}  identical entries {len(bt & bot)}")
print("only in backtest:", sorted(bt - bot)[:5], " only in bot:", sorted(bot - bt)[:5])
bt_exit = {(x["symbol"], x["entry_time"]): x["exit_time"] for x in tr}
# backtest stamps the exit with the stop bar's open time; the bot sees it one bar later (+1h, +5s)
same_exit = sum(abs(bt_exit.get((x["symbol"], x["entry_time"]), 0) - x["exit_time"]) <= 3605 for x in rep["trades"])
print(f"exits within the same hour: {same_exit}/{len(rep['trades'])}")
print(f"final equity  backtest {eq[-1]:.2f}   bot replay {rep['paper']['cash']:.2f}  "
      "(difference = whole-contract rounding in the bot)")
