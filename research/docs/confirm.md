# A TA confirmation layer for structures signals: which indicators, on which timeframe?

Harness: [`research/harness/confirm.py`](../harness/confirm.py). Lab run 2026-09-29, bars from
2024-01-01. Results table on the lab: `data/confirm/results.csv`, 10,058 cells.

## The question

The desk wants a confirmation layer in the trading service. A structures signal arrives from any
timeframe, and one or more TA indicators confirm or reject it before a trading model takes over.
Some models' own entry plans would then be dropped. The problem it must solve is being stopped out
before the market goes our way. [`indicators.md`](indicators.md) found no lagging indicator times
the touch on its own timeframe, so this widens the search to 45 gates and makes **timeframe
alignment** the main design: the level is on a higher timeframe (HTF) and the indicator confirms on
a lower one (LTF).

## Method

**Signals.** 38,816 real-market, 28,637 Deriv and 20,963 walk touches opened by the production
`Engine` on 1h, 4h and 1d levels and on daily and weekly pivots, replayed from 2024-01-01. Each
trade fades the arrival. The FX rollover mask (`structures/rollover.py`) was already in the replay.
FX with the few remaining 21:00 UTC touches removed reads within 0.01R of FX with them, so FX below
is the masked view.

**Pairs (HTF → LTF):** 1d→1h, 1d→30m, 4h→1h, 4h→30m, 4h→15m, 1h→15m, pivot→1h and pivot→15m, plus
1h→1h (same timeframe, an 8-bar window). A gate may fire on the LTF bars from the close of the
touching bar through one HTF bar's worth of them, capped at 32.
- **Entry:** the confirming LTF close.
- **Stop:** anchored to the level at 1 × the HTF bar's volatility (`htf`), and also 1 × the LTF
  bar's (`ltf`).
- **Targets:** 1R and 2R from the actual entry's risk.
- **Time limit:** 10 HTF bars.
- **Costs:** `indicators.COST_V`, in R.

**Gates, 45 of them.** Triggers enter where they fire. States are read at the window's first bar.
- **Oscillators and turns:** RSI, stochastic, stoch-RSI, Bollinger, EMA and SMA reclaims, MACD,
  Williams %R, CCI, Fisher, TRIX, ROC, Connors RSI, the Ultimate Oscillator.
- **Trend and regime:** Heikin-Ashi, Supertrend and PSAR (flips and states), Vortex (cross and
  state), ADX in range or with the trade, Choppiness, Kaufman efficiency, a variance-ratio Hurst
  proxy, Aroon, Ichimoku, the LTF EMA(200) slope, the HTF EMA(50) slope.
- **Volatility:** Keltner re-entry, the Bollinger-in-Keltner squeeze (on, and firing), ATR calm,
  Chandelier.
- **Volume** (FX is tick volume): OBV, MFI (turn and extreme), VWAP discount.
- **Structure:** RSI and MACD divergence at the level, change of character, displacement, the
  sweep-and-reclaim, and production's `candles.confirms`.

Sources for the additions:
[StockCharts ChartSchool](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays),
[TradingView: Vortex](https://www.tradingview.com/scripts/vortex/),
[TradingView: Connors RSI](https://www.tradingview.com/support/solutions/43000502017-connors-rsi-crsi/),
[LuxAlgo: Connors RSI](https://www.luxalgo.com/blog/connors-rsi-guide-enhanced-rsi-for-short-term-signals/),
[LuxAlgo: indicators for confirming support and resistance](https://www.luxalgo.com/blog/5-indicators-for-confirming-support-and-resistance/).

**Baselines and controls.**
- `htf_close`: no gate, entered at the touching bar's close.
- `ltf_touch`: no gate, entered at the first LTF bar back at the level.
- A random gate of the same pass rate.
- A random wait drawn from the gate's own delays.
- Walks we generate (iid t(3) 15m, aggregated upward), and both halves.
- Benjamini-Hochberg across all 8,366 market cells.
- A learned confirmer: boosting on every indicator's state.

**Pre-registered bar.** A gate must beat `htf_close` by 0.05R net with t ≥ 3 and q < 0.05, beat
its random gate, be positive in both halves, and beat the same cell on walks by 0.05R. After the
first run it had to beat walks **gross of costs** too, by 0.05R with gross t ≥ 3. The first run
passed 180 cells, all losing money and nearly all FX. The cause was mechanical: a later entry
risks more against a level-anchored stop, so a fixed cost is fewer R, and the walks (charged 0.15)
understate that about fivefold for FX (charged 0.8).

**Two harness bugs were caught and fixed before these results:**
- a gate's pass rate could exceed 1;
- **a touch's interval is its level's timeframe, not its bar's.** Matching 4h and 1d touches to
  their own bars had silently dropped 77% and 97% of them.

## Results

**The plain entry loses everywhere but Deriv's slow levels.** Net R at 1R, `htf_close`, HTF stop
(`ltf_touch` in brackets):

| | 1h→15m | 1h→1h | 4h→1h | 1d→1h | pivot→1h |
|---|---|---|---|---|---|
| FX | -0.268 [-0.344] | -0.266 [-0.313] | -0.127 [-0.192] | -0.092 [-0.130] | -0.050 [-0.068] |
| crypto | -0.087 [-0.371] | -0.193 [-0.253] | -0.083 [-0.217] | -0.057 [-0.084] | -0.059 [-0.066] |
| metals | -0.126 [-0.120] | -0.101 [-0.122] | -0.105 [-0.060] | -0.052 [-0.010] | -0.017 [-0.015] |
| Deriv | -0.066 [-0.036] | -0.087 [-0.115] | -0.035 [-0.058] | -0.001 [+0.012] | -0.018 [-0.023] |
| walks | -0.068 [-0.142] | -0.103 [-0.114] | -0.046 [-0.039] | +0.034 [+0.029] | -0.010 [-0.002] |

**The desk's complaint is real, and waiting for the retest makes it worse.**
- **Plain entry:** 10-25% of trades are stopped and then reach 1R anyway (FX 4h→1h 18.8%, pivots
  25%).
- **Waiting for the LTF bar that comes back to the level:** that rises to 25-34%, and the stop
  rate goes up. For example FX 4h→15m: stopped 50.3% vs 47.2%, stopped-then-right 30.2% vs 18.4%,
  net -0.229 vs -0.138.
- The walks show the same rise, so a retest entry is a tighter risk measured from a worse place,
  not a better entry.

**17 of 8,366 market cells pass**, which is 7 findings once stop variants and FX with and without
rollover are merged:

| family | pair | gate | trades (pass rate) | net R | vs plain entry | vs walks, gross | stopped | stopped then right | halves |
|---|---|---|---|---|---|---|---|---|---|
| FX | 1h→15m | production candle, 2R | 223 (5.7%) | **+0.114** | +0.370 (t 4.0) | +0.297 | 48.9% | 8.5% | +0.38 / +0.34 |
| FX | 1h→15m | production candle, 1R | 223 (5.7%) | +0.015 | +0.283 (t 4.3) | +0.202 | 39.0% | 13.0% | +0.31 / +0.21 |
| FX | 4h→1h | Choppiness > 61.8 (LTF stop), 1R | 251 (4.7%) | +0.041 | +0.233 (t 3.8) | +0.156 | 38.6% | 17.1% | +0.24 / +0.23 |
| Deriv | 1h→15m | sweep-and-reclaim, 1R | 832 (33%) | **+0.082** | +0.148 (t 3.6) | +0.136 | 42.8% | 12.0% | +0.09 / +0.17 |
| Deriv | pivot→1h | MFI back above 20, 2R | 1,043 (10%) | **+0.174** | +0.195 (t 3.2) | +0.149 | 58.8% | 30.6% | +0.24 / +0.09 |
| crypto | 1h→1h | TRIX turn, 1R | 570 (30%) | +0.033 | +0.226 (t 5.4) | +0.115 | 23.9% | 3.3% | +0.27 / +0.12 |
| crypto | 1h→1h | change of character / MACD / PSAR / Vortex, 1R | 636-842 (34-45%) | -0.010 to +0.018 | +0.18 to +0.21 | +0.066 to +0.092 | 23-29% | 2-6% | second half +0.03 to +0.16 |

**Timeframe alignment, by pair.** Cells with t ≥ 3 / q < 0.05 / passing:

| 1d→1h | 1d→30m | 4h→1h | 4h→30m | 4h→15m | 1h→15m | 1h→1h | pivot→1h | pivot→15m |
|---|---|---|---|---|---|---|---|---|
| 0 / 0 / 0 | 0 / 1 / 0 | 13 / 12 / 1 | 2 / 7 / 0 | 1 / 8 / 0 | 23 / 31 / 3 | 92 / 88 / 10 | 28 / 39 / 1 | 14 / 19 / 0 |

- Confirming a **daily** level on a lower timeframe finds nothing.
- Confirming a **4h** level finds one narrow cell: FX, the 1h range state.
- The survivors cluster on **1h levels** (confirmed on 15m or on 1h) and **Deriv pivots**.

**The learned confirmer knows nothing the walks don't.** Held-out AUC for "reaches 1R before the
stop" is 0.537 on real markets, 0.534 on Deriv and **0.537 on our walks**, so what it learned is
the geometry of the stop, not the market. Its top 10% nets -0.036R on real markets, +0.062 better
than all signals (t 2.0) but still losing.

## What this means

- **There is no general confirmation layer.**
  - No indicator or combination confirms structures signals across families and timeframes.
  - The learned combination is at the walks' level.
  - On FX, crypto and metals every no-gate entry loses, so the best any gate can do is lose less.
- **The desk's complaint is real, but waiting to "get a better price" is the wrong fix.** About
  1 trade in 6 is stopped and then reaches 1R. Entering on the LTF retest of the level adds to
  that. The walks do the same, so it's geometry, not the market.
- **A few narrow gates survive every control,** each on a few hundred trades:
  - **FX 1h levels confirmed by production's candle rule on 15m:** +0.114R at 2R, 223 trades in
    2.7 years across 7 pairs.
  - **Deriv 1h levels confirmed by a 15m sweep-and-reclaim:** +0.082R at 1R, 832 trades.
  - **Deriv pivots confirmed by MFI on 1h:** +0.174R at 2R, but stopped 59%.
  - **FX 4h levels in a choppy 1h range:** +0.041R at 1R, 251 trades.
  - **Crypto 1h momentum turns** (TRIX, change of character, MACD, PSAR, Vortex) turn a -0.19R
    entry into roughly breakeven, and cut stopped-then-right from 18% to 2-6%. That is the
    complaint fixed, but not a profit, and the second half is weaker.
- **These are small samples chosen from 8,366 tests.** They passed BH and every control, but each
  rests on 223-1,043 trades, so they are candidates, not a layer to hand trading decisions to.

## For production

1. **Don't relegate any model's entry plan yet.** Nothing here beats the plain entry broadly.
2. **Shadow the survivors in the trading service.** Record each gate's verdict on every structures
   signal, but don't act on it, and judge after about 200 live signals per gate:
   - production's candle confirmation on 15m, for FX 1h-level signals;
   - the 15m sweep-and-reclaim, for Deriv 1h-level signals;
   - MFI on 1h, for Deriv pivot signals;
   - the 1h Choppiness range state, for FX 4h-level signals;
   - a 1h momentum turn (TRIX), for crypto 1h-level signals.

   Their pass rates would cut those signals' trades to 6%, 33%, 10%, 5% and 30% respectively.
3. **If any of them holds live,** the first thing it would replace is the plain at-the-touch entry
   of the level-fade strategies on that family and timeframe. For FX 1h that is the same rule as
   `TRADING_REQUIRE_CANDLE`, scoped to FX 1h levels and read on 15m.
4. **Don't add a "wait for the retest" entry.** It raises stopped-then-right everywhere.
