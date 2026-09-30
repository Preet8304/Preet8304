# Strategy review and Delta Exchange bot

Source analysed: [Devangnne123/react_tradingchart](https://github.com/Devangnne123/react_tradingchart). The strategy under
test is `user_pinescript.txt`, "Dual-Engine: Mean Reversion + Breakout", run on the repo's own Delta Exchange
1h candles (`data/trading.db`):

- **ETHUSD:** 43,036 bars, Nov 2021 to Sep 2026.
- **SOLUSD:** 21,723 bars, Apr 2024 to Sep 2026.

There are no gaps in either series.

> Numbers below are backtests. They are not a promise of future returns. Crypto regimes change, and 2026 so far has been
> close to flat for this strategy. Run the bot on testnet or in paper mode first.

## 1. What the original strategy does

| Leg | Entry | Exit | Stop |
|---|---|---|---|
| Mean Reversion (MRC 200, ×1.8) | Wick touches S2/R2 within 3 bars, then closes back inside and reverses | Same band touched again | 10-bar swing, moved to breakeven at 1R |
| Breakout (MRC 100, ×1.8) | Close crosses R2 / S2 | Wick touches the band again (usually 1 to 3 bars later) | 10-bar swing, moved to breakeven at 1R |

## 2. Results of the original

The repo's engine reports **+1049% on ETH**. That figure comes from three optimistic assumptions:

1. **Fees:** commission is 0.01% per side. Delta's taker fee is 0.05%, plus 18% GST, so 0.059%. The strategy makes about
   1,000 trades on ETH, so fees decide whether it wins or loses.
2. **Leverage:** the default is 10x on 10% of equity, so the full account is in every trade. That compounds a small
   edge into a large number, along with a 48–62% drawdown.
3. **Fill timing:** entries fill at the signal bar's close, and band exits fill at the close even when the band was
   touched intrabar.

The repo engine with only the fee and leverage changed:

| ETH, repo engine | 10x leverage | 1x |
|---|---|---|
| 0.01% fee (script) | +1049%, DD 48% | +34% |
| 0.059% fee (real) | +177%, DD 55% | +15% |

SOL at 10x with real fees: **-12%, 65% drawdown.**

I then re-ran it in an independent engine (`research/engine.py`). It fills at the next bar's open and handles stops that
gap through, and it includes fees, 0.02% slippage and funding:

| Original, realistic costs | Total | Max DD | Win | Profit factor |
|---|---|---|---|---|
| ETH, 10% equity (Pine sizing), Nov 2021 to Sep 2026 | +8.5% | -9.3% | 24% | 1.11 |
| ETH, 100% equity (repo 10x) | +42% | **-62%** | 24% | 1.06 |
| ETH mean-reversion leg only | +1.9% | -11% | 12% | 1.04 |
| ETH breakout leg only | 0.0% | -3.9% | 38% | 1.00 |
| SOL, both legs, 10% equity | **-7.7%** | -13% | 19% | 0.84 |

**Conclusion:** after real costs the original has no meaningful edge.

- The mean-reversion leg wins only 12% of trades.
- The breakout leg exits on the first retouch of the band, so its winners are too small to pay the fees.

## 3. What changed

`final_strategy.pine` and `research/improved.py` contain the final strategy. The changes:

1. **Mean-reversion leg removed.** I also tested a "buy dips only with the trend" version. Only 34% of parameter
   combinations were profitable, so it was dropped.
2. **Breakout only in the trend's direction.** Longs need close > EMA(400) with the EMA rising over 24 bars; shorts need
   the opposite. ADX(14) must be ≥ 20.
3. **ATR stop:** the initial stop is 2×ATR(14) from entry, so each loss is a known, fixed size.
4. **Trailing stop instead of the band-retouch exit:** the stop follows 3×ATR from the best price reached since entry.
   Winners can run, which is where the profit comes from (avg win ≈ 2.1× avg loss).
5. **Size by risk, not by % of equity:** 0.75% of equity is lost if the stop hits, with notional capped at 3x.

Final parameters: channel 100, outer ×1.4, trend EMA 400, ADX ≥ 20, stop 2 ATR, trail 3 ATR.

### How the parameters were chosen

- **Tuning window:** parameters were picked only on **ETH, Nov 2021 to Dec 2024**, from 216 combinations.
- **In-sample check:** 99% of the combinations were profitable in that window. I took the centre of a robust region
  rather than the single best result.
- **Held-out data, never used for tuning:** ETH Jan 2025 to Sep 2026, and all SOL data.
- **ETH held-out:** all 216 combinations were profitable (median profit factor 1.57).
- **SOL held-out:** 74% of combinations were profitable (median +8.6%).

The chosen setting is about average on ETH and below average on SOL.

## 4. Final results (realistic costs)

| Run | Total | CAGR | Max DD | Avg month | Median month | Positive months | Worst month | PF |
|---|---|---|---|---|---|---|---|---|
| ETH, 1% risk, Nov 2021 to Sep 2026 | +194% | 24.6% | -17.0% | 1.96% | 1.69% | 66% | -7.7% | 1.69 |
| ETH, 1% risk, **2025–26 held-out** | +34% | 18.4% | -17.0% | 1.43% | 0.43% | 64% | -7.7% | 1.49 |
| SOL, 1% risk, **held-out** | +5% | 2.1% | -14.2% | 0.24% | -0.50% | 43% | -4.8% | 1.06 |
| **ETH+SOL, 0.75% risk, Apr 2024 to Sep 2026** | **+63%** | **21.7%** | **-20.3%** | **1.77%** | 1.07% | 63% | -9.0% | 1.38 |
| Original ETH+SOL, 0.75% risk, same period | +5% | 2.0% | -42.3% | 0.67% | 0.48% | 50% | -16.2% | 1.03 |

Against the original over the same period with the same risk, the final version makes about 12 times more profit and
has about half the maximum drawdown.

### Monthly % returns by risk level (ETH+SOL portfolio)

Choose your risk level; returns and drawdowns scale together:

| Risk per trade | Avg month | Median month | Worst month | Max DD | CAGR |
|---|---|---|---|---|---|
| 0.5% | 1.18% | 0.73% | -6.1% | -14.0% | 14.4% |
| **0.75% (default)** | **1.77%** | **1.07%** | **-9.0%** | **-20.3%** | **21.7%** |
| 1% | 2.35% | 1.40% | -11.8% | -26.1% | 28.9% |
| 1.5% | 3.51% | 1.99% | -17.3% | -36.5% | 43.2% |
| 2% | 4.66% | 2.51% | -22.4% | -45.5% | 57.0% |

### Month by month: ETH+SOL, 0.75% risk

| Year | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec | Year |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2024 | | | | 0.4 | -1.4 | 1.2 | 9.0 | 4.9 | 0.5 | 1.3 | 1.9 | -3.5 | **14.6** |
| 2025 | -0.1 | 16.7 | -0.7 | 8.4 | 8.9 | -4.1 | -0.5 | 6.1 | 2.6 | -1.2 | 1.4 | -1.3 | **40.3** |
| 2026 | 5.7 | 2.5 | 0.1 | -5.6 | -9.0 | -4.1 | 1.6 | 10.4 | 0.9 | | | | **1.1** |

### Month by month: ETH only, 1% risk (2025 onward is held-out)

| Year | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec | Year |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2021 | | | | | | | | | | | -4.5 | 0.8 | -3.8 |
| 2022 | 2.5 | 2.3 | 2.5 | -1.6 | -1.4 | 10.0 | 3.4 | -0.3 | 1.2 | -3.5 | 3.1 | -5.7 | **12.2** |
| 2023 | 3.9 | -4.3 | 5.6 | 2.2 | 0.1 | -2.3 | -3.4 | 10.7 | 1.7 | 5.2 | -3.3 | -3.8 | **11.7** |
| 2024 | 5.3 | 20.2 | 6.2 | -0.2 | 3.1 | 4.5 | 13.3 | 4.7 | 3.1 | 0.0 | 3.6 | -0.8 | **81.6** |
| 2025 | 0.0 | 9.1 | 0.3 | 5.8 | 7.0 | -2.9 | 3.8 | 6.0 | 4.4 | -2.6 | 1.1 | 0.5 | **36.9** |
| 2026 | 4.3 | -2.2 | -0.5 | -3.6 | -7.7 | -2.6 | 3.3 | 7.6 | 0.4 | | | | -1.9 |

**What to realistically expect:**

- **Typical month:** about +1% (median) at 0.75% risk. The average of +1.8% is pulled up by a few big trend months.
- **Losing months:** about 1 month in 3 loses.
- **Losing years:** a bootstrap of the monthly returns gives roughly a **13% chance of a losing 12-month period**. In 5%
  of simulated years the 12-month drawdown is worse than -17.6%.
- **Weak markets:** this is a trend-following system, so it earns in trending markets and gives back in choppy ones.
  April to June 2026 is an example.

Requirements: `pip install numpy pandas tabulate`. Copy the repo's `data/trading.db` into `strategy/data/`; it is
not committed because it is 17 MB. Then run the scripts in `research/`.

## 5. Automation: `bot/`

The bot is written for the Delta Exchange REST v2 API: Python standard library only, HMAC-signed requests.

```bash
cd strategy/bot
# 1) offline replay of the full bot loop over the local candle DB (no network needed)
python3 bot.py --mode replay --from 2025-01-01 && python3 parity_check.py
# 2) paper trading on live Delta candles, simulated fills (no API key)
python3 bot.py --mode paper
# 3) testnet, then live (create API keys at delta.exchange with trading permission, whitelist your server IP)
export DELTA_API_KEY=... DELTA_API_SECRET=...
python3 bot.py --mode live --env india-testnet
python3 bot.py --mode live --env india
```

**What it does every hour,** 10 seconds after the candle closes, for ETHUSD and SOLUSD:

1. Loads the last 3,000 closed 1h candles.
2. Runs the **same `TrendBreakout` class used in the backtest.**
3. Sizes the trade by risk and sends a market entry plus a **reduce-only stop-market order**.
4. Each hour after that, it moves the stop up (or down, for shorts) to follow the trailing level.

The trailing stop is recalculated from candle history each hour, so a restart never loses it.

**Safety guards** (in `config.json`):

- `risk_per_trade` is 0.75% and `max_notional_leverage` is 3x.
- `exchange_leverage` is 10x. That only sets the margin; exposure is still governed by the risk setting.
- `monthly_loss_limit` 10%: no new entries for the rest of the month.
- `kill_drawdown` 25% below the equity peak: flatten everything and halt.
- A missing stop order is re-placed every hour. If the first stop is rejected, the position is closed immediately.
- Positions the bot didn't open are never touched.

**Verification:**

- **Replay vs backtest:** replaying Jan 2025 to Sep 2026 through the full bot loop gave the **same 223 entries (time,
  side, stop)** as the backtest. All exits land within the same hour, and final equity differs by 0.5% (whole-contract
  rounding).
- **Unit tests:** `bot/test_bot.py` checks request signing, position sizing and the trailing-stop logic.

**Not verified:**

- The Delta API was not reachable from the environment this was built in. The live order endpoints (`/v2/orders`
  create, edit and cancel, `/v2/positions`, `/v2/wallet/balances`) follow Delta's documentation but have not been run
  against the exchange.
- **Run on `india-testnet` first** and check that stop orders appear and move each hour.
- `final_strategy.pine` has not been compiled in TradingView.

## 6. Files

| Path | What |
|---|---|
| `research/engine.py` | Independent backtest engine (next-open fills, gap-aware stops, fees, slippage, funding) |
| `research/original.py` | Port of the original Pine strategy |
| `research/improved.py` | Final `TrendBreakout` (and the rejected `TrendPullback`) |
| `research/baseline.py`, `sweep.py`, `validate.py`, `oos_family.py`, `final_report.py` | Reproduce every number above |
| `REPORT_DATA.md`, `final_trades.csv` | Generated tables and the trade list |
| `final_strategy.pine` | Final strategy for TradingView / the chart app |
| `bot/` | Delta Exchange bot, config, tests, parity check |

**Costs assumed throughout:** 0.059% taker fee per fill, 0.02% slippage per fill, and 0.01% funding per 8h charged on
every open position. Using limit (maker) orders for entries would lower costs further but is not modelled.
