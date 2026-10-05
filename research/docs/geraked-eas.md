# The geraked MetaTrader 5 Expert Advisors, backtested

**Measured, pre-registered, 2026-10-04.** The 13 EAs of the public MIT repo
[github.com/geraked/metatrader5](https://github.com/geraked/metatrader5) were ported to Python
(`research/ideas/geraked_ind.py`, `geraked_eas.py`, `geraked_sim.py`, `geraked_report.py`, tests in
`test_geraked.py`). They were tested three ways, all frozen in `geraked_rule.json` before the run:

- **Mode S** is each entry signal with its own coded stop, target and trail.
- **Mode G** is the author's defaults: a grid with no stop, run as an account in money.
- **Mode R** is the repo's risk layer, swapped one factor at a time.

Every test runs on the broker's bars for every asset class and against walks matched to each series.

**Verdict: no EA's signal has an edge, and the grid's "profit" is the grid's shape.**

- **Mode S (primary):** none of the 13 EAs passes. Twelve lose 0.02-0.09R a trade after costs, with
  intervals below zero. The exception is CEZLSMA at +0.012R [-0.016, +0.046], p = 0.30, and all of
  that comes from before 2024 (+0.136 before, -0.018 after). Every EA's P(+N R before the stop)
  sits on 1/(N+1), and on its walks, at every N from 0.5 to 10. Matching the walks means zero edge
  before costs; it does not mean the patterns are fake ([walks-and-edge.md](walks-and-edge.md)).
- **Secondary cells:** of 441 EA x class x timeframe cells, 13 pass every rule and 7 survive
  Benjamini-Hochberg. Four of the seven are on Deriv (Range Break 100, or the jumpy indices), where
  the price comes from a published generator. The other three are crypto at 4h, all trend-following:
  2MAAOS on crypto CFDs (+0.084R) and on Binance (+0.095R), and DHLAOS on Binance (+0.083R). The two
  venues share their largest coins, so this is one result, not two. It is a candidate for a frozen
  test on unseen coins, not a finding.
- **Mode G** (the author's grid, no stop, 1% risk, 1:100): the typical account loses. Across MT5
  non-Deriv, the median CAGR runs from -38% to +1% by EA. 37-70% of accounts hit a stop-out and
  28-57% are ruined (down 90%). The median max drawdown is 87-95% for every gridded EA except BBRSI,
  which rarely fires. No grid ever reached its level cap: margin always ran out first. The walks show
  the same picture, with ruin rates of 45-75%. Real data is somewhat kinder than walks for some EAs.
  On FX, real-data accounts are ruined 32% of the time against 49-55% on walks, which suggests
  short-run mean reversion helps a grid a little. Even so, the median FX account loses about 10% a
  year. Profitable equity curves like the author's appear on random walks just as often (see the
  author cells).
- **Mode R:** no stop type, trail, sizing mode, martingale, equity limit, spread limit or
  multiple-position setting moves mean R on real data by more than it moves on the walks (all within
  0.007R; the one exception, the 60-point fixed stop, is noted below). They change drawdown and ruin
  and nothing else, as `deriving.md` predicts. The martingale raises Monte Carlo ruin (P of touching
  -50% within 1,000 trades) from 0.41 to 0.69 on real data, and from 0.61 to 0.82 on walks.

## Design (frozen in `geraked_rule.json`, commit 2a52007)

- **Ports.** Each EA's signal, coded SL/TP, trail, close rule and default inputs come from
  `Experts/*.mq5`. The indicators come from `Indicators/*.mq5` and the MT5 built-ins, with MQL warm-ups
  (EMA seeded with the first price, ATR as a simple mean). The order, trail, grid and volume logic
  come from `EAUtils.mqh`. All are re-expressed in Python, with 37 tests: hand-worked indicator bars,
  engine cases, and each EA firing both ways on a walk.
- **Timing and fills.** The signal is taken on the bar close and filled at the next open. Inside a
  bar, price runs open, low, high, close on an up bar and open, high, low, close on a down bar. Stops
  fill at the stop, plus 0.05 ATR of slippage; a gap fills at the open.
- **Data.** The broker's bars at 15m, 1h, 4h and 1d for every `run.FAMILY` symbol: FX 12, metals 5,
  indices 7, energy 2, crypto CFDs 35 and Deriv 15. Also Binance perpetuals (12 coins) and 50 of the
  broker's stock CFDs. Stocks are 1h only: their 1d history (about 250 bars) is too short for the
  EAs' warm-ups.
- **Costs.** The broker's spread floor; where that floor is zero, the median bar spread. Binance pays
  0.07% and stocks 0.05% of price. 15 series cost over 0.5 ATR and were dropped
  (`.data/geraked/dropped.csv`, mostly small crypto CFDs at 15m, plus XPT/XPD 15m and USDCNH 15m).
- **Controls.** iid and GARCH walks in log price, matched to each series: 256 sub-steps a bar, the
  real timestamps, the real first price, and the real cost in ATR units. Also a coin twin (same
  entries, random side) and the reversed signal. Mode G and Mode R run on the same walks.
- **COT1** reads CFTC TFF futures-only (Dealer and Leveraged Funds, fetched from cftc.gov) in the
  EA's own window: last week's Tuesday report, traded Monday and Tuesday. It is managed on the FX
  pairs' 15m bars, which start in 2024, so it has no "before" half and cannot pass.
- **Amendment after the first run.** A stop inside the broker's stops level is refused, as the broker
  refuses it (`amended_after_first_run` in the rule). In the first run a stop a point or two from the
  fill made a few hundred trades' R explode, down to -10^8 on one Deriv cell. Everything was re-run
  with the refusal. The primary verdicts did not change.

## Mode S: the signal (primary: MT5 non-Deriv, 15m-1d pooled)

| EA | n | R | 90% CI | before / after 2024 | iid | GARCH | coin | reversed | P(4R) real / iid | P(10R) real / iid |
|---|---|---|---|---|---|---|---|---|---|---|
| 2MAAOS | 49,512 | -0.019 | [-0.030, -0.008] | +0.018 / -0.027 | -0.045 | -0.050 | -0.036 | -0.054 | 0.204 / 0.200 | 0.088 / 0.085 |
| 2MACDSTO | 100,618 | -0.078 | [-0.084, -0.072] | -0.041 / -0.086 | -0.105 | -0.109 | -0.081 | -0.087 | 0.201 / 0.203 | 0.093 / 0.093 |
| 2MOMEMA | 96,319 | -0.085 | [-0.095, -0.075] | -0.067 / -0.089 | -0.082 | -0.083 | -0.075 | -0.065 | 0.199 / 0.200 | 0.090 / 0.089 |
| 3MACD | 95,775 | -0.027 | [-0.033, -0.021] | -0.029 / -0.026 | -0.032 | -0.030 | -0.029 | -0.046 | 0.196 / 0.194 | 0.084 / 0.081 |
| 3MAF | 63,533 | -0.044 | [-0.053, -0.035] | -0.030 / -0.048 | -0.056 | -0.062 | -0.041 | -0.037 | 0.203 / 0.198 | 0.092 / 0.087 |
| AFAOSMD | 38,654 | -0.067 | [-0.079, -0.056] | -0.083 / -0.064 | -0.058 | -0.053 | -0.048 | -0.031 | 0.196 / 0.199 | 0.087 / 0.087 |
| BBRSI | 6,630 | -0.049 | [-0.072, -0.026] | -0.037 / -0.051 | -0.017 | -0.025 | -0.010 | +0.017 | 0.187 / 0.181 | 0.077 / 0.064 |
| CEZLSMA | 82,519 | +0.012 | [-0.016, +0.046] | +0.136 / -0.018 | -0.043 | -0.042 | +0.008 | +0.005 | 0.198 / 0.196 | 0.083 / 0.083 |
| COT1 | 221 | +0.007 | [-0.082, +0.094] | - / +0.007 | +0.055 | -0.147 | +0.029 | -0.069 | 0.235 / 0.225 | 0.086 / 0.113 |
| DHLAOS | 41,218 | -0.033 | [-0.043, -0.023] | -0.014 / -0.038 | -0.051 | -0.052 | -0.046 | -0.039 | 0.207 / 0.198 | 0.090 / 0.086 |
| LRCMACD | 99,099 | -0.063 | [-0.070, -0.056] | -0.036 / -0.069 | -0.069 | -0.072 | -0.065 | -0.065 | 0.199 / 0.201 | 0.091 / 0.089 |
| LRCUTB | 137,279 | -0.046 | [-0.052, -0.041] | -0.035 / -0.049 | -0.048 | -0.048 | -0.045 | -0.043 | 0.199 / 0.199 | 0.089 / 0.087 |
| NWERSIASF | 89,158 | -0.074 | [-0.083, -0.064] | -0.065 / -0.075 | -0.090 | -0.090 | -0.061 | -0.034 | 0.200 / 0.204 | 0.092 / 0.091 |

1/(N+1) is 0.200 at 4R and 0.091 at 10R. **No EA passes**, before or after Benjamini-Hochberg.

- **The walks lose a little more than real data** (by 0.01-0.04R) on most cells. The walks match
  close-to-close sigma, not each bar's range, so swing stops sit a little differently against ATR. The
  tails do not move.
- **Reversing the signal (the author's own trick for 3MACD and AFAOSMD) does not help.** It is no
  better than the coin twin.
- **Plots:** `pnr_<EA>.png` (real, iid, GARCH, coin, reversed and 1/(N+1), per timeframe and pooled),
  and `heatmap_edge.png` (EA x timeframe x asset class, real R minus the walks, * where a cell passes).

**Cells that survive BH (7 of 441 tried):**

| EA | class | TF | n | R [lo] | before / after | walks (iid / GARCH) | coin | P(4R) vs iid |
|---|---|---|---|---|---|---|---|---|
| 2MAAOS | crypto CFD | 4h | 3,907 | +0.084 [+0.052] | +0.087 / +0.082 | -0.019 / -0.036 | -0.009 | 0.223 / 0.205 |
| 2MAAOS | Binance | 4h | 1,828 | +0.095 [+0.055] | +0.094 / +0.096 | -0.025 / -0.026 | -0.006 | 0.231 / 0.191 |
| DHLAOS | Binance | 4h | 2,228 | +0.083 [+0.045] | +0.086 / +0.081 | -0.020 / -0.018 | -0.018 | 0.231 / 0.187 |
| CEZLSMA | Deriv jumpy | 1h | 4,441 | +0.051 [+0.029] | +0.063 / +0.037 | -0.012 / -0.030 | +0.025 | 0.214 / 0.199 |
| 3MAF, LRCUTB, NWERSIASF | Range Break 100 | 1h | 743 / 2,561 / 600 | +0.098 / +0.051 / +0.164 | all positive | about 0 | +0.04 to +0.10 | - |

- **Range Break** rewards anything that trades back into its range; its coin twins also make money.
  It is reported but not pooled.
- **Crypto 4h** is the one place an EA's signal beats walks, coins and 1/(N+1) on two venues. It is
  trend-following, it agrees with [imported-ideas.md](imported-ideas.md) and
  [battery.md](battery.md) (crypto trend survives, thinly), and it was found by searching 441 cells.
  Next step: freeze 2MAAOS and DHLAOS at 4h on `binance_fresh` coins.

## Mode G: the author's defaults (grid, no stop), risk 1%, 10,000 at 1:100, stop-out 50%

MT5 non-Deriv, medians across series (about 220 per EA). Each column shows real / iid / GARCH.

| EA | median CAGR | median max DD | stopped out | ruined | profitable accounts |
|---|---|---|---|---|---|
| 2MAAOS | -12% / -34% / -28% | 90% / 94% / 92% | 56% / 60% / 58% | 40% / 50% / 47% | 45% / 39% / 40% |
| 2MACDSTO | -38% / -39% / -40% | 95% / 95% / 96% | 70% / 72% / 74% | 56% / 61% / 66% | 29% / 29% / 24% |
| 2MOMEMA (no grid by default) | -3% / -3% / -3% | 23% / 24% / 25% | 1% / 2% / 2% | 1% / 3% / 6% | 25% / 32% / 27% |
| 3MACD | -23% / -30% / -24% | 94% / 95% / 93% | 56% / 58% / 56% | 48% / 48% / 47% | 42% / 36% / 41% |
| 3MAF | -10% / -26% / -32% | 87% / 92% / 92% | 57% / 62% / 62% | 39% / 46% / 46% | 46% / 36% / 35% |
| AFAOSMD | -0% / -30% / -26% | 77% / 94% / 94% | 51% / 58% / 59% | 37% / 48% / 48% | 50% / 39% / 39% |
| BBRSI | +1% / +1% / +1% | 15% / 23% / 26% | 18% / 18% / 17% | 15% / 15% / 13% | 76% / 66% / 66% |
| CEZLSMA | -26% / -35% / -34% | 92% / 94% / 94% | 61% / 66% / 65% | 48% / 54% / 52% | 41% / 35% / 34% |
| DHLAOS | 0% / 0% / 0% | 66% / 82% / 74% | 44% / 48% / 45% | 28% / 36% / 33% | 46% / 29% / 33% |
| LRCMACD | -36% / -42% / -39% | 93% / 95% / 95% | 68% / 71% / 72% | 53% / 62% / 61% | 35% / 28% / 30% |
| LRCUTB | -38% / -50% / -47% | 95% / 97% / 97% | 70% / 82% / 76% | 52% / 75% / 67% | 28% / 17% / 23% |
| NWERSIASF | -37% / -29% / -31% | 95% / 92% / 93% | 69% / 57% / 60% | 57% / 49% / 47% | 26% / 36% / 35% |
| COT1 (one FX account) | +68% / -86% / -39% | - | no / yes / yes | no / yes / no | - |

- **No grid cycle reached GridMaxLvl in any series.** At 1% risk and 1:100, margin binds after about
  4-8 levels, so the broker's stop-out is the real stop. The mean depth is 1.6-2.2 levels.
- **By class** (median over EAs, real / iid / GARCH ruin share):
  - FX: 32% / 55% / 49%.
  - Metals: 50% / 35% / 38%.
  - Indices: 27% / 27% / 29%.
  - Crypto CFDs: 52% / 53% / 53%.
  - Binance: 64% / 48% / 54%.
  - Deriv diffusive: 51% / 59% / 53%.
  - Stocks: 8% / 6% / 8%. The stock histories are only a year long, so few grids had time to blow up;
    their median CAGR is +8% real against +7% on walks.
- **Plots:** `mode_g_equity_author.png` (the author's cells, real against both walks, at 1% and the
  author's own risk) and `mode_g_equity_others.png`.

**The author's own cells** (the broker's history; Mode G CAGR at 1% / at the author's risk; walks at 1%):

| cell | Mode S R | real G 1% | real G author risk | iid G 1% | GARCH G 1% |
|---|---|---|---|---|---|
| 2MAAOS EURUSD 4h | +0.006 | -14%, DD 88% | +2% (5.5%), DD 96% | -33%, ruined | -15% |
| 2MAAOS USDCAD 4h | +0.023 | +9%, DD 34% | +13% (5.5%), DD 87% | +13% | -12% |
| 2MACDSTO NZDUSD 3h | -0.109 | -36%, ruined | -35% (2.25%), ruined | -41%, ruined | -40% |
| 3MACD AUDUSD 5m (6 months) | -0.020 | -69% | -91% (0.5%) | -99%, ruined | **+417%** |
| 3MAF USDCAD 15m | -0.022 | -75%, ruined day 393 | - | -59% | -71%, ruined |
| BBRSI XAUUSD 5m (6 months) | -0.013 | **+75%**, DD 70% | - | **+82%**, DD 20% | +54% |
| CEZLSMA AUDUSD 15m | -0.033 | +27%, DD 54% | -75% (3%), ruined day 256 | +34% | -79%, ruined |
| DHLAOS AUDUSD 5m (6 months) | -0.158 | -100%, ruined day 105 | -46% (0.5%) | +55% | +163% |
| NWERSIASF AUDUSD 2h | -0.089 | -40%, ruined | -33% (1.2%) | +19% | -9% |
| NWERSIASF USDCAD 2h | -0.146 | -14% | -6% (1.2%) | -3% | -23% |

The author's best-looking curve (BBRSI on gold 5m) has a random-walk twin that looks better. 3MACD's
best curve is on a GARCH walk.

## Against the author's reports

The author's MT5 reports (`Test/<EA>/report.xlsx`, 2019-2023, Alpari and 360Capital, 1:100-1:500,
the author's risk) show net profits of 3.7x to 333x the 10,000 deposit, profit factors of 1.9-4.4 and
win rates of 64-84%. Their **relative equity drawdowns are 56-94%** (CEZLSMA 94%, AFAOSMD 84%, 3MAF
75%, BBRSI 70%). The author notes on every EA but COT1 that "the pure implementation ... was not
profitable over the long term" and that the grid "made it profitable". This study agrees with the
first half. The signals have no edge, and a grid on a 70-94% drawdown path is the shape of a
martingale, which ends in a stop-out sooner or later. On our broker and dates, about half of all
gridded accounts did, and walks do the same. Two further differences:

- The author's tester runs had a 1:200-1:500 margin and an earlier period.
- Several of the author's symbols (EURCAD, EURCHF, NZDCAD, AUDCAD) are not at this broker.

## Mode R: the risk layer, one factor at a time (MT5 non-Deriv, all EAs pooled)

Each column shows real / iid / GARCH. Ruin is Monte Carlo: 2,000 resampled 1,000-trade sequences at
1% risk, counting P(touching -50%).

| config | mean R | median max DD | P(ruin -50%) | P(end below start) |
|---|---|---|---|---|
| base (Mode S, 1%) | -0.050 / -0.062 / -0.063 | 14% / 17% / 18% | 0.41 / 0.61 / 0.69 | 0.81 / 0.85 / 0.83 |
| trail off | -0.066 / -0.076 / -0.079 | 15% / 20% / 20% | 0.56 / 0.73 / 0.80 | 0.82 / 0.86 / 0.86 |
| trail 25% | -0.009 / -0.026 / -0.025 | 9% / 11% / 11% | 0.18 / 0.35 / 0.42 | 0.46 / 0.63 / 0.63 |
| trail 75% | -0.059 / -0.072 / -0.074 | 15% / 19% / 20% | 0.49 / 0.70 / 0.76 | 0.81 / 0.86 / 0.85 |
| SL_AR / SL_MR / SL_SWING | -0.060 / -0.050 / -0.050 (real) | 15-16% | 0.40-0.49 | 0.78-0.83 |
| fixed lots | same R | 16% / 20% / 22% | 0.79 / 0.86 / 0.90 | 0.79 / 0.87 / 0.88 |
| min amount | same R | 17% / 21% / 22% | 0.75 / 0.80 / 0.83 | 0.78 / 0.85 / 0.85 |
| martingale (4% cap) | same R | 21% / 26% / 27% | 0.69 / 0.82 / 0.85 | 0.87 / 0.91 / 0.90 |
| equity limit 5% | same R | 14% / 16% / 17% | 0.12 / 0.21 / 0.17 | 0.69 / 0.68 / 0.54 |
| spread limit | -0.051 / -0.064 / -0.065 | 12% / 15% / 16% | 0.43 / 0.66 / 0.68 | 0.81 / 0.87 / 0.82 |
| multiple positions | -0.044 / -0.054 / -0.055 | 21% / 26% / 26% | 0.75 / 0.90 / 0.93 | 0.77 / 0.88 / 0.91 |
| grid (= Mode G) | - | 84% / 91% / 91% | - | - |
| grid + equity limit 20% | - | 42% / 47% / 48% | - | - |

**No factor interacts with anything real.**

- **The change against the base is the same on real data and on walks.** Every factor's shift in R
  matches the walks' to within 0.007R, in every class. Trail 25% adds +0.040R on real data and
  +0.036/+0.039R on the walks.
- **Why trail 25% gains on walks at all:** it is mostly the close-inside-30-points rule exiting
  without stop slippage, plus the bar-path convention. It is not edge.
- **The 60-point fixed stop** is the exception. It sits at a spread or two from the fill on most
  non-FX symbols, so its R is cost/stop; the walks scale cost through ATR, and that comparison is
  meaningless.
- **Sizing, martingale and equity limit leave R per trade untouched** and move only drawdown and
  ruin:
  - The martingale raises ruin.
  - The equity limit cuts the Monte Carlo ruin, because it caps the rare gap losses.
  - The grid's 20% equity limit halves the grid's drawdown but keeps its negative CAGR.
- **Base ruin is high (0.41) even at 1% risk** because the base loses 0.05R a trade. Over 1,000
  trades that is a 40% drag. The risk layer cannot turn a negative expectancy into a positive one.
- **Not tested:**
  - The news filter: the lab has no economic calendar.
  - Knn.mqh: no EA uses it.
  - RISK_BALANCE / RISK_MARGIN_FREE: these equal RISK_EQUITY with one position open.
- **Plots:** `mode_r_factors.png`, `mode_r_ruin.png`, `mode_r_fans.png`.

## Caveats

- **Bars, not ticks.** The fixed open-low-high-close path is a convention, and the walks share it.
- **Timer-polled EAs approximated.** 2MAAOS and NWERSIASF poll on a timer within the bar; here they
  are checked at the open only.
- **3MAF's fractal.** The EA reads buffer 2 on the new bar's first tick, before MT5 has computed it.
  It is modelled as a fractal confirmed by the last bar and the new open.
- **DHLAOS.** On its rare "no cross found" branch, the forming bar's indicator values are taken from
  the last closed bar.
- **Mode G simplifications.** One leverage (1:100) on every instrument, margin at the fill, no swap
  or commission, constant tick values. Gaps fill at the open.
- **Short histories.** The 5m history is six months; the FX 15m history starts in 2024 (so COT1 and
  the 15m FX cells have no "before" half); stocks are 1h only and one year long.
- **Mode R summaries.** Mode R's per-series account numbers are medians over series, so they do not
  add up.

## Files

- Code: `research/ideas/geraked_ind.py`, `geraked_eas.py`, `geraked_sim.py`, `geraked_report.py`,
  `test_geraked.py`.
- Rule: `research/ideas/geraked_rule.json`.
- Tables and plots: `.data/geraked/` (`mode_s_primary.csv`, `mode_s_cells.csv`, `mode_g_*.csv`,
  `mode_r*.csv`, `author_cells.csv`, `plots/`).
- Lab output: `out/geraked2/` (the re-run; `out/geraked/` is the first run).

## The EAs in plain words

Every EA reads the last closed bar on the first tick of a new bar and fills at that bar's open. A
"swing" stop is the lowest low (highest high) of N bars, minus (plus) a few points. Points are the
symbol's own (1 point = 0.00001 on EURUSD, 0.01 on gold). TP is a multiple of the stop distance.
The defaults columns are what the author ships; Mode S overrides them with stops and TP on and the
grid off.

| EA | Entry (buy; sells mirror it) | Coded stop / TP | Author's defaults |
|---|---|---|---|
| 2MAAOS | Andean Oscillator bull line crosses its signal, bull > bear, SMA50 > SMA200, price above SMA50 - half the MA gap; at least 6 bars between entries | swing 10 bars - 100 pt / 1R | risk 5.5%, TP ignored, trail 50%, grid x1.3 to 20 |
| 2MACDSTO | MACD(34,144) > 0 and MACD(13,21) < 0 (a pullback in an uptrend); Stochastic(7,3,3) below 20 crosses up | swing 7 - 60 pt / 1R | risk 2.25%, SL and TP ignored, grid x1.0 to 50 |
| 2MOMEMA | Momentum(10) crosses above 100 with Momentum(34) > 100 and EMA10 > EMA34 for the last 9 bars | swing 10 - 60 pt / 1R | risk 1%, stops on, no trail, no grid |
| 3MACD | a triple-MACD (5/8, 13/21, 34/144) pullback: slow MACD positive, medium MACD troughs after the fast one re-crossed zero | swing 7 - 60 pt / 2R | **Reverse on**, risk 0.5%, SL and TP ignored, grid x1.0 to 50 |
| 3MAF | EMA60 > EMA350 > EMA600, the bar's low between EMA600 and EMA60, a Williams fractal low | at EMA350 (EMA600 if below it), at least 100 pt / 1.5R | SL and TP ignored, grid x1.5 to 20, grid trail 40% |
| AFAOSMD | Average Force crosses up through 0 while Andean bull > bear and MACD(100,200) positive and rising | swing 7 - 60 pt / 1R | **Reverse on**, TP ignored, grid x1.1 to 20 |
| BBRSI | a close back inside Bollinger(500, 2) after one below it, RSI(7) back above 30 but under 50, below the middle band | lower band - 0.9 x band half-width / 1R | SL and TP ignored, grid x1.1 to 20 |
| CEZLSMA | Chandelier Exit (ATR 1 x 0.75 on Heikin-Ashi) flips to buy while the HA close is above ZLSMA(50) of HA closes; closes when HA crosses back if in profit | chandelier stop - 650 pt / none | risk 3%, SL ignored, grid x1.5 to 50 |
| COT1 | weekly, from last week's CFTC TFF report (Dealer, then Leveraged Funds): buy the pairs of the two currencies that added net longs with the highest long share against the two that added net shorts with the highest short share; Monday/Tuesday; one position at a time | mean daily range of 6 days + 30 pt / 2R | risk 3.5%, TP ignored, grid x1.2 to 20 |
| DHLAOS | Andean bull crosses its signal; the last bull-over-bear cross came first, and within 50 bars after it price traded wholly below the previous day's low | swing 7 - 60 pt / 1.5R | risk 0.5%, SL and TP ignored, grid x1.1 to 50, grid trail 20% |
| LRCMACD | Linear Regression Candles(11, signal 5): an up candle closing above the signal after 1-4 down candles, MACD(34,144) positive throughout | lowest low of 10 - 60 pt / 1R | TP ignored, grid x1.5 to 20 |
| LRCUTB | an up LRC(11, 7) candle above its signal and a UT Bot (ATR 1 x 2 trailing line) buy within 3 bars | swing 10 - 100 pt / 1R | risk 0.6%, TP ignored, grid x1.2 to 50 |
| NWERSIASF | Nadaraya-Watson envelope (bandwidth 8, x3 mean deviation, 500 bars): the bar before last pierced the lower band with RSI(5) < 30, the last bar closed up, price in the lower half of the envelope; 4 bars between entries | ATR SL Finder lower line (low - 0.75 ATR14) / 1.5R | TP ignored, grid x1.1 to 20 |

Where the defaults turn the trail on, it moves the stop to entry plus the move, minus 50% of the coded
stop distance, once the trade is half a stop in profit. The grid (`checkForGrid`) adds a position
every coded-stop distance against the first one. Each new lot is the previous lot times the
multiplier. All positions share one take-profit, set where the whole book earns back the first
order's risk. Up to the level cap there is no stop, so only the broker's stop-out ends a losing grid.
