# Fuzzy-logic trading: the rules do no better than a walk, and fuzziness adds nothing

**Measured 2026-10-04, pre-registered. The primary fails.** The expert fuzzy rule base (FIS-1) loses
**-0.110R** a trade on 210,048 MT5 trades, with a 90% interval of [-0.130, -0.089]. That is above its coin
twin (-0.144), the iid walk (-0.150) and the GARCH walk (-0.122), but below the same rules with hard
thresholds (-0.100). When the near-zero-risk trades are set aside (a diagnostic, not part of the
registration), the edge over walks disappears: -0.087R against -0.093 for the iid walk and -0.088 for GARCH.

The learned rule base (FIS-2, Wang-Mendel) ranks direction slightly better than the desk's logistic on
held-out bars: AUC **0.508 against 0.504** on MT5 and 0.514 against 0.509 on Binance, with walks at 0.499.
Neither turns that into a profitable trade. Of 255 secondary cells, six survive Benjamini-Hochberg. All six
are Deriv, and the gain comes from one instrument, Range Break 100, which is about +1R a trade for every
system *and for its coin twin*. That is a property of the instrument, not of fuzzy logic.

Script: [`ideas/fuzzy_trade.py`](../ideas/fuzzy_trade.py). Frozen rule base, memberships, thresholds and
pass conditions: [`ideas/fuzzy_rule.json`](../ideas/fuzzy_rule.json), committed (83b889f) before any
real-data run. Before the freeze, one smoke run on a generated iid walk checked that the rules fire and
that trades are built. Lab outputs are in `out/fuzzy/`, and the plots are listed at the end.

## The question

Can a fuzzy inference system pick a side that beats chance and walks? It takes graded memberships
("the trend is *fairly* up, the close is *near* support, the candle is a *strong* bull") instead of hard
cut-offs. Earlier pages give the priors:

- direction is close to a coin flip ([ladder.md](ladder.md));
- textbook TA rules survive only as thin crypto trend-following ([battery.md](battery.md));
- a small logistic regression is the model to beat ([models.md](models.md)).

The question is asked two ways. FIS-1 uses rules written down from practice. FIS-2 uses rules learned from
data. The crisp twin of FIS-1 asks whether *fuzziness* adds anything.

## What was frozen

**Inputs.** All are known at bar t's close. Breakpoints are percentiles of the pre-2024 MT5 non-Deriv
real bars: 764,487 bars from 44 symbols, 1h, 4h and 1d pooled.

| input | definition | fitted breakpoints |
|---|---|---|
| TR | (close - EMA50) / ATR14 | b = q67(\|x\|) = 2.11, c = q90 = 3.56 |
| SLOPE | EMA50 change over 5 bars / (5 ATR) | b = 0.084, c = 0.140 |
| MOM | RSI(14) - 50 | b = 12.2, c = 20.5 |
| VOL | log ATR(5) / ATR(50) | q10 -0.36, q50 -0.055, q90 0.28 |
| RPOS | close in the 20-bar range | fixed 0.2 / 0.5 / 0.8 |
| candle (MCFL) | signed body share, close location, body force (z of body/ATR in the 10-bar window, as `force_g`) | the MCFL class edges sit at membership 0.5 |
| DSL / DSH | distance to the last confirmed swing low / high (3 bars either side), in ATR | NEAR: full to q25 = 0.99, zero at q50 = 1.77 |

**FIS-1: nine long rules, mirrored for shorts on the flipped chart.** AND is min and NOT is 1 - mu.
Consequents are singletons on the long strength. Defuzzification is a weighted average with a background
"otherwise WEAK" weight of 0.25. The score is L - S, in [-1, 1].

| rule | if | then long is |
|---|---|---|
| L1 pullback in uptrend | UPTREND (SLOPE POS and not TR NEG) and RPOS LOW and not MOM NEG | STRONG (1) |
| L2 trend momentum | UPTREND and MOM POS and not MOM EXTENDED | MEDIUM (0.5) |
| L3 bull candle at support | not SLOPE NEG and NEAR support and STRONG_BULL | STRONG |
| L4 compression breakout | VOL COMPRESSED and RPOS HIGH and STRONG_BULL | STRONG |
| L5 oversold reversal | MOM EXTENDED down and STRONG_BULL | MEDIUM |
| L6 exhaustion | TR POS and TR EXTENDED and STRONG_BEAR | WEAK (0) |
| L7 downtrend | SLOPE NEG and TR NEG | WEAK |
| L8 overbought at resistance | MOM EXTENDED and NEAR resistance | WEAK |
| L9 expanding sell-off | VOL EXPANDED and STRONG_BEAR | WEAK |

STRONG_BULL = min(BULL, FORCE_STRONG, CLOSE_HIGH). A trade fires when |score| crosses **0.5** (the grid
was 0.3-0.7). The **crisp** version applies the same rules after replacing every membership with
1[mu >= 0.5].

**FIS-2** learns a Wang-Mendel rule base on 8 inputs (TR, SLOPE, MOM, VOL, RPOS, CDIR, CFORCE, SWING), each
with 3 Ruspini triangles:

- Each training bar votes for its max-membership cell with its degree. A cell's consequent is the
  degree-weighted mean of the target, and a cell needs a total degree of at least 20 to hold a rule.
- The target is +1 or -1 for the side that moves 1.5 ATR first within 24 bars.
- It was fit on the same pre-2024 MT5 bars: **712 rules** out of 3,008 cells seen (6,561 possible).
- The baseline is a logistic regression on the same 8 crisp inputs.
- Both trade when |score| crosses the 90th percentile of their training |score| (grid 80/90/95).

**Trade.**

- Entry is the next open.
- The stop is the last 3 bars' extreme plus 0.1 ATR.
- Exits: E1, a 2-ATR trail (primary), and X2, a fixed 2R. The hold is 10 days at most.
- Stop fills pay 0.05 ATR of slippage.
- Costs are the broker spread floor on MT5, 0.07% on Binance.

**Controls.**

- iid and GARCH walks matched to each series: 256 sub-steps, real timestamps, the real cost in ATR. The
  FIS runs on them unchanged.
- A coin twin: the same entry bars with a random side.
- The crisp rules.

**Data.**

- MT5: every symbol in `run.FAMILY` at 1h, 4h and 1d: 62 non-Deriv symbols, with the 15 Deriv synthetics
  reported apart.
- Binance: the 12 `turn_trade.COINS` perpetuals at 1h, 4h and 1d.
- 789 series per source.

## The primary

FIS-1, |score| >= 0.5, MT5 non-Deriv pooled, all timeframes, E1:

| | n | R | 90% CI | before 2024 | after | P(0.5R) | P(1R) | P(2R) | P(4R) | P(10R) |
|---|---|---|---|---|---|---|---|---|---|---|
| **real** | 210,048 | **-0.110** | [-0.130, -0.089] | -0.153 | -0.089 | 0.600 | 0.450 | 0.271 | 0.116 | 0.021 |
| coin twin | 209,990 | -0.144 | [-0.161, -0.126] | -0.244 | -0.097 | 0.549 | 0.419 | 0.265 | 0.130 | 0.034 |
| iid walk | 146,473 | -0.150 | [-0.163, -0.137] | -0.226 | -0.113 | 0.548 | 0.426 | 0.270 | 0.127 | 0.031 |
| GARCH walk | 184,692 | -0.122 | [-0.133, -0.112] | -0.190 | -0.089 | 0.575 | 0.435 | 0.260 | 0.113 | 0.024 |
| crisp rules | 131,308 | -0.100 | [-0.121, -0.078] | -0.156 | -0.075 | 0.596 | 0.443 | 0.261 | 0.107 | 0.020 |
| 1/(N+1) | | | | | | 0.667 | 0.500 | 0.333 | 0.200 | 0.091 |

**Fails on four of the six conditions.** R is negative, its interval is below zero, both halves are
negative, and the crisp rules do better. It beats the coin twin and both walks, but:

- **It reaches nothing.** Every P(N R) is below 1/(N+1). P(>=4R) is 0.116 against 0.20, and P(>=10R) is
  0.021 against 0.091, *below* the coin twin and the iid walk at 4R and 10R. The rules buy a slightly
  higher chance of a small move (P(0.5R) 0.60 against 0.55) and give back the tail. Mostly this is
  geometry: a trade that fires after a pullback or a strong candle has a different stop distance.
- **The margin over walks lives in the tiny-risk trades.** The registered rule takes a trade whenever the
  open is beyond the stop at all, so some trades risk 0.001 ATR, where cost / risk is huge. Without trades
  under 0.25 ATR of risk (5.7% of the real ones), real is -0.087, iid walk -0.093 and GARCH -0.088. That
  is a walk. Median R is -1.03.
- **The threshold grid shows the same thing.** For FIS-1 at 0.3 / 0.4 / 0.5 / 0.6 / 0.7, real is -0.127
  / -0.116 / -0.110 / -0.098 / -0.091, against GARCH at -0.124 / -0.120 / -0.122 / -0.121 / -0.113.
- **Rule by rule.** Trades where L1 (buy the pullback in an uptrend) fires lose the most, -0.205R. Trades
  with L3 or L4 (a strong bull candle at support, or a breakout from compression) lose -0.04R. None are
  positive. L5 (oversold reversal) never fired at 0.2 or above on an entry: an RSI 20 points beyond 50 and
  a strong opposite candle rarely meet.

Per family (FIS-1 0.5, E1; real / coin / iid / GARCH / crisp):

- fx: -0.210 / -0.278 / -0.266 / -0.206 / -0.206
- metal: -0.153 / -0.199 / -0.234 / -0.155 / -0.155
- index: -0.125 / -0.155 / -0.156 / -0.177 / -0.098
- energy: -0.206 / -0.173 / -0.249 / -0.123 / -0.174
- crypto CFD: -0.054 / -0.072 / -0.071 / -0.066 / -0.045
- Deriv: -0.007 / -0.012 / -0.078 / -0.103 / -0.015
- Binance: -0.106 / -0.176 / -0.197 / -0.175 / -0.108

## FIS-2 against the logistic: does fuzziness add anything?

AUC for the side that moves 1.5 ATR first within 24 bars. The pre-2024 MT5 rows are the training set, and
everything else is out of sample.

| pool | half | FIS-1 | crisp | **FIS-2** | **logistic** |
|---|---|---|---|---|---|
| MT5 real | train (pre-2024) | 0.500 | 0.501 | 0.520 | 0.509 |
| MT5 real | **held out (2024+)** | 0.499 | 0.501 | **0.508** | **0.504** |
| MT5 iid walk | 2024+ | 0.501 | 0.501 | 0.499 | 0.499 |
| MT5 GARCH | 2024+ | 0.500 | 0.501 | 0.500 | 0.499 |
| MT5 crypto CFDs | 2024+ | 0.501 | 0.503 | 0.510 | 0.506 |
| Binance real (never trained on) | 2024+ | 0.503 | 0.506 | 0.514 | 0.509 |
| Deriv real (never trained on) | 2024+ | 0.499 | 0.498 | 0.500 | 0.497 |

- **The expert rules carry no ranking information.** FIS-1 and its crisp twin are at 0.50 everywhere,
  and the hit rate by score decile is flat (`fuzzy_scores.png`).
- **The learned fuzzy rules beat the logistic, narrowly and out of sample**: +0.004 AUC on MT5 held out
  and +0.005 on Binance. Walks sit at 0.499-0.500, so the signal is real and not an artefact of the
  machinery. FIS-2 also loses about half its training AUC out of sample (0.520 to 0.508), where the
  logistic loses less (0.509 to 0.504). This is the non-linearity a cell grid can hold (the logistic's
  largest weight is on SLOPE, at -0.05: a faint mean reversion). An AUC of 0.508 is about a 0.5-point
  shift in a coin flip.
- **Traded at its frozen threshold**, FIS-2 does not pay. On MT5 pooled it makes -0.406R, but that figure
  is dominated by a handful of zero-risk FX entries (an open at the 3-bar low; one AUDJPY trade at
  -52,000R on X2). Its crypto CFD cell is +0.001R [-0.036, +0.037]. The logistic makes -0.091R on MT5
  pooled and +0.014R [-0.033, +0.060] on crypto CFDs. Both beat their coin twins and walks on crypto and
  neither is distinguishable from zero.

## Secondary cells and multiple testing

255 real cells:

- 4 systems: FIS-1 (79, the primary excluded), crisp (80), FIS-2 (48), logistic (48);
- × thresholds;
- × 2 exits;
- × 8 pools: MT5 pooled, fx, metal, index, energy, crypto, Deriv, Binance.

The p-value is the one-sided day-bootstrap share of resampled means at or below 0. **Benjamini-Hochberg at
q = 0.10 keeps 6 cells, all Deriv** (E1):

| cell | n | R | 90% CI | coin twin | iid walk | GARCH |
|---|---|---|---|---|---|---|
| Deriv FIS-2 q95 | 16,270 | +0.198 | [+0.137, +0.260] | +0.178 | -0.120 | -0.124 |
| Deriv FIS-2 q90 | 33,591 | +0.106 | [+0.068, +0.144] | +0.089 | -0.120 | -0.114 |
| Deriv FIS-2 q80 | 78,244 | +0.047 | [+0.025, +0.071] | +0.038 | -0.122 | -0.108 |
| Deriv logistic q95 | 11,120 | +0.245 | [+0.185, +0.306] | +0.340 | -0.091 | -0.082 |
| Deriv logistic q90 | 27,519 | +0.146 | [+0.112, +0.182] | +0.184 | -0.068 | -0.077 |
| Deriv logistic q80 | 65,390 | +0.076 | [+0.053, +0.098] | +0.083 | -0.075 | -0.082 |

Three of the six beat their coin twin, by +0.01 to +0.02R. The coin twins are themselves positive because
of **Range Break 100 Index**: there, every system and every coin twin makes about +0.9 to +1.3R a trade
(FIS-2 +1.285, its coin +1.158). On the other Deriv symbols FIS-2 runs from -0.47 to +0.02 (Crash 1000 is the only one above zero). A
range-confined generator rewards a 2-ATR trail and a tight stop whichever side is taken. It says nothing
about fuzzy rules, and [battery.md](battery.md) found Deriv's TA survivors were fill artefacts too.
Outside Deriv, **4 of 223 cells have R > 0** (all MT5 crypto CFDs, FIS-2 and the logistic, p 0.33-0.48),
and none survives BH. The best Binance cell is FIS-1 0.7 E1 at -0.074R, which beats its coin (-0.202) and
walks (-0.159 / -0.186) but loses money.

**What beat walks:** FIS-1 on the MT5 pool, Binance and most families, by 0.01-0.09R, always at a loss,
and only before the tiny-risk trades are removed. FIS-2 and the logistic on MT5 crypto CFDs come in at
about 0R against walks at -0.06 to -0.09R. Out-of-sample AUC beats walks for FIS-2 and the logistic on MT5
and Binance. Nothing beats walks *and* makes money outside the Range Break artefact.

## Verdicts

1. **Primary, FIS-1 expert rules: fails.** -0.110R, below zero in both halves and below the crisp rules.
   Its edge over walks and the coin twin is cost geometry, not side.
2. **Fuzziness against crisp thresholds: adds nothing to the expert rules.** The crisp twin trades as well
   or better (-0.100 against -0.110), and both have an AUC of 0.50.
3. **Learned fuzzy rules against the logistic: FIS-2 ranks a little better out of sample** (0.508 against
   0.504 on MT5, 0.514 against 0.509 on Binance; walks 0.499), and still nothing trades. This matches
   [ladder.md](ladder.md): the information is a fraction of a point of AUC, below what a tight-stop trade
   needs.
4. **Deriv positives are Range Break 100**, where coin twins earn as much. Report it; never trade it as
   a fuzzy edge.

## Caveats

- **Near-zero-risk entries.** The frozen stop rule ("skip only if the open is beyond the stop") lets
  through trades whose risk is a pip or less after a gap to the 3-bar extreme. They dominate FIS-2's MT5
  and FX means. A minimum risk (for example 0.25 ATR) belongs in any rerun and should be frozen up front.
- **Overlap.** Every crossing is taken, so trades overlap within a series. The day bootstrap absorbs part
  of the dependence, but the intervals are optimistic.
- **The pre-2024 half is thin and old for most of the book.** Indices, energy and the fresh crypto CFDs
  start in 2024 on this broker, so "before" is FX, metals, BTC/ETH/SOL and older 4h/1d bars. Those are
  the bars FIS-2, the logistic and the breakpoints were fit on.
- **The decile plot pools both halves.** `fuzzy_scores.png` mixes training and held-out bars for FIS-2 and
  the logistic, so their real curves are partly in-sample. The AUC table separates them.
- **Signal-free walks still show "skill" against their coin twins** (FIS-1 walk -0.150 against coin
  -0.152; GARCH -0.122 against -0.154). The entry choice changes stop distance and cost / risk, which is
  why the coin twin alone is not enough of a control.
- **The rule base is one reasonable reading of the literature** (trend-plus-pullback, momentum,
  candle-at-support, compression breakout, oversold reversal, and four inhibitors), not the only one. The
  learned rule base is the hedge against a poor choice of expert rules, and it does not trade either.

## Plots (`out/fuzzy/`, copied to `.data/fuzzy/`)

- `fuzzy_pnr.png`: P(N R) for real, iid, GARCH, coin twin and crisp, per family. Every curve sits under
  1/(N+1), and the lines are nearly indistinguishable.
- `fuzzy_scores.png`: the score distributions (real against walks) and P(up first) by score decile. FIS-1
  and crisp are flat. FIS-2 and the logistic are monotone on real data (partly in-sample) and flat on walks.
- `fuzzy_auc.png`: FIS-1, crisp, FIS-2 and logistic AUC by pool and source, pre-2024 and held out.
- `fuzzy_winners.png`, `fuzzy_losers.png`: six MT5 trades each, annotated with the score, the rules
  firing for and against, the entry, the structural stop and the trail's exit.
