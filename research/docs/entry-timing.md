# Does waiting k bars before entry add selection, or only buy hit rate?

**measured 2026-11-10.** Harness:
[`research/harness/entry_timing.py`](../harness/entry_timing.py). Lab runs
`logs/et_{leak,calib,main,imp,power}.log`, cells in
`out/entry_timing/cells-*.csv`. Pre-registration frozen before the first cell
and reproduced verbatim at the bottom, with every later addition listed and the
measurement that forced it.

## The answer, first

**A confirmation delay of 1 to 5 bars buys hit rate at the fair rate and
nothing more.** On `smc-bos-causal` at 15m, waiting one bar for a close in the
trade's direction raises the 1R hit rate from **0.504 to 0.653** - fifteen
points - and the fair rate for the reward:risk that buys, `risk / (risk +
reward)` recomputed at the later entry, goes from **0.500 to 0.644**. At a 2R
target the same arm goes 0.333 to 0.472 against a fair rate of 0.333 to 0.462.
Across the nine lags and three targets in the table below the realised hit
rate sits on the fair rate to within **0.025**, on 7,128 trades, and it sits
*below* it in 16 of those 22 cells. That is `CLAUDE.md`'s fade-to-value
finding - 31% to 48% hit for 1.88 to 0.94 reward - reproduced on a different
rule with a hundred times the sample.

The expectation per signal goes the other way. Paired against the same signals
entered at market, the delay is worth **-0.017R at k=1 falling to -0.047R at
k=4** on `smc-bos-causal`, with a day-block interval excluding zero at **every
one of the five lags**, against a matched random-anchor placebo whose own
delay difference is **+0.0013R [-0.0081, +0.0101]**. It still loses with
reward:risk held constant, so the exchange is not where the loss hides. And it
is indistinguishable from waiting at random for the same mean length: the
random-delay twin reads **-0.034 to -0.048R** against the real confirmation's
-0.020 to -0.030R.

**No k beats the fair-rate null on either rule.** Four of five lags beat *no
delay* on hit rate, exactly as arithmetic requires, and none of them beats what
the arithmetic gives for free. The only nominal positives in the study are two
marginal cells on `vol-impulse`'s stopless exit; both are negative net of the
venue's own spread, both are matched by the random twin, and **0 of 125**
per-instrument cells on that rule survive Benjamini-Hochberg.

## Verdict

| question | answer | kind |
|---|---|---|
| does a 1-5 bar lag raise the hit rate? | **yes, and at the fair rate.** 0.504 to 0.653 at 1R, 0.333 to 0.472 at 2R; within 0.025 of `risk/(risk+reward)` at every k and target, and below it in 16 of 22 cells | reading, n 7,128 |
| does it add **selection** beyond that exchange? | **no.** Every lag's paired difference from k=0 is zero or negative, and all five fixed lags have an interval excluding zero - -0.017, -0.037, -0.045, -0.047 and -0.041R at k=1 to k=5 | **null** |
| does the exchange explain all of it? | **no - it is worse than that.** With reward:risk held constant and no refusals at all (`shifted`) the lag still loses, -0.021 to -0.080R | null |
| is the confirmation distinguishable from waiting at random? | **no.** The random twin at the same mean delay and the same refusal rate reads -0.034 to -0.048R against -0.020 to -0.030R, and **survives BH on 11 per-instrument cells against the real confirmation's 3** | null |
| does production's `ArrivalEntry` candle witness help? | **it fires almost never at a break price.** 1.7% of signals within one bar, 11.5% within five, and the refusal costs the rule its whole reading: -0.073 to -0.078R a signal | mechanic |
| is `ArrivalEntry.candle_tolerance_vol` in volatility units? | **no, a fraction of price.** Documented as volatility units, implemented as `abs(level) * tol / 100` | **defect** |
| does `smc-bos-causal` exit on a 16-bar clock? | **no, 96.** 16 is `vol-impulse`'s. A 5-bar lag eats 5.2% of one hold and 31.3% of the other | mechanic |
| what does the delay cost to execute? | **nothing measurable.** `N20` pins cost in R to 1/20 by construction, and the measured 0.049 is flat across k to three decimals - a later entry moves the entry, not the stop distance it is divided by | reading |
| can `walk_with_bar_geometry` null a barrier race? | **no.** Random anchors on it read **-0.2055R** where optional stopping requires zero; the same anchors on real bars read **-0.0004R** | **defect** |
| where does the test go blind? | it detects a planted conditional continuation at 2.0 volatility units over a 96-bar hold and not at 1.0; the measured interval excludes anything above **0.24 to 0.41 units**, depending on which arm's zero is the baseline | power |
| readable at 1d? | **no.** 128 trades, mean +1.44R, interval [+0.28, +2.83], median -1.000 | unmeasurable |

## What was run

**Populations.** Two of the five deployed rules, each driven through its own
production fold rather than a re-implementation, so the arm and the rule are
the same detector:

- **`smc-bos-causal`** - `strategies.structure.Fold(reach=50)`, BOS only
  (CHoCH is not traded), stop the wider of one ATR(14) at the signal close and
  20 spreads, hold **96** bars (`HOLD_MINUTES // 15`), no target.
- **`vol-impulse`** - `strategies.volimpulse.Fold` with the squeeze leg on as
  deployed, impulse 3.0x the frozen HAR, risk `3 x sigma x price`, hold **16**
  bars. **No protective stop**: `decide` sets `stop` as a sizing distance,
  `protective_stop` is False, and `_clock` closes the position - so its own
  exit is the `mark` outcome below and its first reading here, which imposed a
  stop the rule does not have, was wrong. 15m only, and only the five feeds
  with a frozen HAR, because that HAR forecasts a fifteen-minute mean absolute
  return and at 1h it would fire on ordinary bars.

Not measured, and why: `statespace-surprise` needs the statespace engine, whose
scope defaults to 1m and 5m; `identity-arb` needs a live partner leg; `zones`
needs the structures service's level book. Each is a different harness and none
of them changes the arithmetic the headline rests on.

**Data**, with each series' bar count and date range printed beside its signal
count so `n` can be read as a claim about the world.

| | series | bars each | span |
|---|---|---|---|
| 15m, long | 8 real + 4 Deriv indices | 198k-295k | 2015-01 to 2026-11 |
| 15m, short | 23 FX crosses | 20,000 | 2026-01 to 2026-11 |
| 1h | 28 FX pairs | 20,000 | 2023-08 to 2026-11 |
| 1d | 14 feeds | 1,000-6,008 | 2006-09 to 2026-08 |

`spx500` and `us100` hold **two rows per timestamp** at 1d - 6,005 and 6,008
rows over 3,006 stamps, which is 503 bars a year on a daily series - and the
defect is not fixed upstream. `db_series` de-duplicates by timestamp and prints
what it dropped. Left in, a fold confirms every bar twice, a 96-bar hold is 48
real days and an ATR spans half the time it claims.

**Arms.** `k1..k5` a pure wait; `c1..c5` the first bar in `1..k` that closes in
the trade's direction; `w1..w5` and `v1..v5` production's own
`indicators.candles.confirms` at the signal price, at the tolerance as
implemented and as documented; `r1..r5` the random-delay twin, drawn from
`c*`'s own realised delay distribution on the same series **including its
refusals**, so trading less and waiting are not one column.

**Geometries.** `anchored` keeps the stop and targets at the prices the signal
named, so a delay walks the entry toward the target and raises the risk - this
is production's geometry, since `structure.py` anchors the ATR leg at the
signal close. `shifted` re-anchors the distances to the delayed entry, so
reward:risk is constant and **nothing is ever refused**.

**Outcomes.** `clock` - stop, else the mark at the hold. `mark` - no stop, no
target, marked at the hold, which is `vol-impulse`'s own exit. `tgt1/2/3` - a
target at 1, 2 or 3x the k=0 risk as a **fixed price** every arm races to. All
of them are bounded, so a walk pays exactly zero on each.

**De-overlapping.** One position at a time at `hold + 5` bars' spacing, which
is both what a one-position desk does - `volimpulse._clock` runs before the
fold's own event for exactly that reason - and what removes the outcome-window
overlap a short skip rule against a long forward window creates. It is read off
**bar indices only**, so it cannot select on an outcome, and it costs little
here: BOS fires 726-819 times in 294,000 bars.

**Standard errors** are a day-block bootstrap, 2,000 draws, resampling whole
days: a 96-bar hold at 15m overlaps by construction.

## The statistic is the paired difference, and here is why

Under the null, price is a martingale and every arm's exit is a bounded
stopping time, so moving an entry k bars later has expected P&L **exactly
zero** in units of the k=0 risk with a refused signal scored zero - whatever
the delay does to the hit rate, the reward or the refusal rate. So `mean R0 =
0` *is* the fair-rate null and it needs no simulation.

It does need a calibration, and the calibration is why the **level** is never
quoted as a result here. (The table below is the `main` run's 31 15-minute
series; the sub-step sweep two sections down is `MODE=calib`, which runs only
the eight eleven-year series, so the two universes are not the same and their
levels are not comparable with each other either.) A 1-ATR stop against a
96-bar mark has a median of exactly **-1.000** and a positive mean: a short
string of very large winners against a wall of stop-outs, so the sample mean
is badly conditioned and any settlement bias rides on top of it. Measured with
**random anchors**, where the answer must be zero:

| bars the race ran on | k=0 mean R0 | stop rate | paired k=3 vs k=0 |
|---|---|---|---|
| **real** | **-0.0004** [-0.0245, +0.0241] | 0.65 | **+0.0013** [-0.0081, +0.0101] |
| Brownian-bridge walk (`walk_path`) | +0.0899 | 0.74 | -0.0050 [-0.0145, +0.0042] |
| `node/surrogates.walk_with_bar_geometry` | -0.2055 | 0.80 | +0.0340 [+0.0229, +0.0457] |
| `level_shield.bar_shuffle` | -0.2078 | 0.80 | +0.0309 [+0.0203, +0.0411] |
| `level_shield.garch_bars` | -0.6552 | 0.86 | +0.0421 [+0.0336, +0.0509] |

**Only the real-bars arm is calibrated, and it is calibrated on both the level
and the paired difference.** The paired difference is not *exactly* zero on
every null either, and the bound matters: on a Brownian bridge with a stop
three times as wide the same random anchors read **-0.0040 at k=1, -0.0077 at
k=3, -0.0092 at k=5 and -0.0119 at `c3`**, each with an interval excluding
zero. So delaying has a small mechanical cost that depends on the bars and the
stop width, and on the bars and stop width this study uses it is within
**[-0.0081, +0.0101]**. The real arm's -0.0448 at k=3 survives the widest of
those allowances with -0.035 to spare, so the verdict does not turn on it -
but it is a reason the verdict is stated as "zero or negative" rather than as
a precise negative number. So the study reads the paired difference from k=0
on real bars, and the surrogate arms are kept for what they can still say -
whether a delay difference appears where there is nothing to select, which on
three of the four it does.

## Two leaks found in this harness, both worth more than one of its tables

**A gap-aware stop fill is unusable with these surrogates.** Filling a stop at
the worse of the stop and the bar's open is the honest reading of a gap on a
real series. `walk_with_bar_geometry` and `bar_shuffle` draw each bar's open
*inside that bar's own range*, independently of the previous close, so every
synthetic bar opens with a fabricated gap. Measured on EURUSD 15m against its
own twins, `|open - previous close|` as a share of the bar range, at the
median: **0.0000 real, 0.6481 walk-geometry, 0.6721 bar-shuffle** - the means
are not quoted because zero-range bars put them in the thousands. The first run
of this harness duly read **-0.6378R at k=0 on walk-geometry** against a
required zero, which `MODE=leak ET_GAPFILL=1 ET_SUBSTEPS=15 ET_DEMEAN=0`
reproduces. The headline
fills at the stop price, which is symmetric across arms; `ET_GAPFILL=1`
restores the gap reading for a real-bars sensitivity. Underfilling is also the
safer direction: `smc-bos-reconcile.md` measured the catalogue's own stop fills
as **pessimistic** by +0.081 to +0.363R, not optimistic.

**A surrogate's wicks are not on its own path, so a barrier race on it is not a
martingale race.** The deeper version of the same thing, and it survives the
fill fix. All three of `level_shield`'s arms build a bar by drawing a close from
a walk and then a *shape* resampled independently of that walk, so a stop read
off such a low fires without the price path ever having gone there, while the
mark at the clock is read off the close path as though nothing had happened.
The decomposition that located it is the table above: **random anchors**, which
cannot be the detector's fault, read -0.2055 on walk-geometry bars and -0.0004
on real bars. `walk_path` is the replacement - each bar a Brownian bridge of
120 sub-steps pinned to a step drawn from the real series' own steps, so the
open is the previous close exactly and the high and low are the path's own
extremes. It is not a general improvement: a bridge's range is the range
Brownian motion gives and markets are wickier, so `walk-geometry` remains the
right arm for a claim that needs wickiness and this one for a claim about a
race.

Two smaller things fell out on the way, and both are recorded because each one
looked like the cause and was not:

- **"Driftless" was not.** Every one of these arms resamples or permutes real
  steps and none removes the mean, so a surrogate of an eleven-year gold
  series carries eleven years of gold's drift - about +0.01 price units a bar
  against a 15-minute ATR of a few, a fifth of an R inside one 96-bar hold.
  `ET_DEMEAN` removes it and is on by default. It moved the bridge arm from
  +0.1219 to +0.1144, so it was **not** the cause of that arm's bias.
- **Refining the path does not fix the level either, and the residual's cause
  is not identified.** On the eight eleven-year series (`MODE=calib
  ET_SUBGRID=15,30,60,120,240`) the bridge's k=0 reading across 15, 30, 60,
  120 and 240 sub-steps a bar is +0.1734, +0.1686, +0.1222, +0.1164, +0.1144 -
  it falls and then stops, so about 0.06R of it was the stop's overshoot and
  the remaining +0.11R is something else. Three candidates were ruled out by
  measurement rather than argument: drift (`ET_DEMEAN`, worth 0.0075), path
  discreteness (the sweep above) and the detector (random anchors read the
  same as BOS signals read +0.0899 and +0.1253 on the same 31 series). What is
  left is a mean over a payoff whose median is exactly -1.000, whose winners
  are a short heavy tail, and whose stop sits closer in units of a bar's own
  step on a bridge than on a real series - 0.74 of trades stopped against
  0.65. `ET_STOPMULT` is the handle that varies that while holding the signal
  fixed, and it carries **part of it and not all**: `MODE=calib ET_SUBGRID=240
  ET_STOPMULT=3` takes the same arm's k=0 reading from +0.1144 to **+0.0803**
  and its stop rate from 0.86 to 0.60. **No level in this study is read as a
  result**, which is the whole argument for the paired statistic.

## `smc-bos-causal` at 15m: 7,128 trades, 31 real markets, 2015 to 2026

The rule's own exit, production's geometry. `vs k0` is the paired difference
with its day-block interval.

| arm | fill | mean wait | mean R0 | **vs k0** | 95% interval | stop rate |
|---|---|---|---|---|---|---|
| `k0` | 1.000 | 0.00 | +0.0736 | - | - | 0.65 |
| `k1` | 0.969 | 1.00 | +0.0566 | -0.0170 | [-0.0322, -0.0025] | 0.64 |
| `k2` | 0.937 | 2.00 | +0.0365 | **-0.0371** | [-0.0592, -0.0144] | 0.63 |
| `k3` | 0.915 | 3.00 | +0.0288 | **-0.0448** | [-0.0700, -0.0185] | 0.62 |
| `k4` | 0.898 | 4.00 | +0.0269 | **-0.0467** | [-0.0747, -0.0158] | 0.61 |
| `k5` | 0.880 | 5.00 | +0.0328 | **-0.0408** | [-0.0736, -0.0059] | 0.60 |
| `c1` | 0.484 | 1.00 | +0.0508 | -0.0228 | [-0.0571, +0.0088] | 0.57 |
| `c2` | 0.735 | 1.34 | +0.0535 | -0.0201 | [-0.0439, +0.0022] | 0.61 |
| `c3` | 0.852 | 1.57 | +0.0470 | **-0.0266** | [-0.0481, -0.0045] | 0.62 |
| `c4` | 0.903 | 1.71 | +0.0442 | **-0.0294** | [-0.0498, -0.0078] | 0.62 |
| `c5` | 0.923 | 1.78 | +0.0438 | **-0.0297** | [-0.0503, -0.0082] | 0.62 |
| `r3` (random twin of `c3`) | 0.831 | 1.57 | +0.0304 | **-0.0432** | [-0.0689, -0.0189] | 0.64 |
| `r5` (random twin of `c5`) | 0.922 | 1.86 | +0.0369 | **-0.0367** | [-0.0590, -0.0126] | 0.63 |
| `w1` (production's candle) | 0.017 | 1.00 | +0.0006 | **-0.0730** | [-0.1329, -0.0179] | 0.66 |
| `w5` | 0.115 | 2.95 | -0.0042 | **-0.0778** | [-0.1334, -0.0271] | 0.60 |
| `v5` (same, documented unit) | 0.092 | 2.74 | -0.0043 | **-0.0779** | [-0.1350, -0.0269] | 0.62 |
| **matched placebo, `k1`** | 0.986 | 1.00 | +0.0000 | +0.0004 | [-0.0050, +0.0058] | 0.64 |
| **matched placebo, `k3`** | 0.950 | 3.00 | +0.0008 | +0.0013 | [-0.0081, +0.0101] | 0.63 |
| **matched placebo, `k5`** | 0.923 | 5.00 | +0.0047 | +0.0052 | [-0.0070, +0.0167] | 0.62 |

The placebo rows are the control that decides it: the same mechanics at random
anchors, five draws a signal, 35,640 trades, and **no delay effect at all**. So
the -0.017 to -0.047 on real signals is not the mechanics of waiting; it is
what waiting does to this rule's signals.

**The random twin is the second control and says the same.** `c3` and `r3` wait
the same 1.57 bars on average and refuse the same share of signals, and `r3`
reads -0.043 against `c3`'s -0.027. A confirmation that cannot beat a coin flip
at the same duty cycle is not a confirmation.

### The fair-rate column

The target is a **fixed price** at 1, 2 or 3x the k=0 risk, so every arm races
to the same pair of prices; `fair` is `risk_k / (risk_k + reward_k)` averaged
over the trades that entered, which is the hit rate a driftless walk owes that
geometry.

| arm | hit at 1R | fair | hit at 2R | fair | hit at 3R | fair |
|---|---|---|---|---|---|---|
| `k0` | 0.504 | 0.500 | 0.333 | 0.333 | 0.231 | 0.250 |
| `k1` | 0.496 | 0.494 | 0.347 | 0.348 | 0.244 | 0.263 |
| `k2` | - | - | 0.358 | 0.364 | - | - |
| `k3` | 0.486 | 0.497 | 0.364 | 0.373 | 0.267 | 0.292 |
| `k4` | - | - | 0.373 | 0.379 | - | - |
| `k5` | 0.486 | 0.493 | 0.379 | 0.384 | 0.281 | 0.306 |
| **`c1`** | **0.653** | **0.644** | **0.472** | **0.462** | **0.348** | **0.354** |
| `c3` | - | - | 0.396 | 0.399 | - | - |
| `c5` | 0.535 | 0.542 | 0.378 | 0.383 | 0.269 | 0.291 |
| `w5` | - | - | 0.461 | 0.454 | - | - |

Read any row's pair of columns together. Waiting one bar for a confirming close
lifts the 1R hit rate by **fifteen points, 0.504 to 0.653** - and the fair rate
for the reward:risk that buys lifts by fourteen, 0.500 to 0.644. The excess
over the fair rate is **+0.010 at its best and negative in 16 of the 22 cells**,
and the expectation per signal does not move: +0.0051 at `k0` against
+0.0054 at `c1`, on a per-trade standard deviation above 1R.

That is the same exchange `CLAUDE.md` records on fade-to-value, arriving at the
same place from a different rule, and it is why "improve the entry" was never
the answer.

### With reward:risk held constant, the lag still loses

The `shifted` geometry moves the stop and target with the entry, so reward:risk
is identical at every k and **no signal is ever refused** - the exchange is
switched off and only selection is left.

| arm | fill | mean R0 | vs k0 | 95% interval |
|---|---|---|---|---|
| `k1` | 1.000 | +0.0524 | -0.0212 | [-0.0527, +0.0113] |
| `k2` | 1.000 | +0.0223 | **-0.0513** | [-0.0882, -0.0153] |
| `k3` | 1.000 | +0.0290 | -0.0446 | [-0.0856, +0.0008] |
| `k4` | 1.000 | -0.0059 | **-0.0795** | [-0.1227, -0.0355] |
| `k5` | 1.000 | +0.0048 | **-0.0688** | [-0.1150, -0.0216] |
| `c5` | 0.971 | +0.0489 | -0.0247 | [-0.0590, +0.0112] |
| `r5` | 0.970 | +0.0203 | **-0.0533** | [-0.0883, -0.0167] |

So the refusal is not where the loss comes from. Entering the same trade k bars
later at the same reward:risk is simply a worse trade, by about 0.08R at k=4.

### Per instrument, and the multiplicity

Eight 15m instruments carry 100 trades or more. At `k3`, **one of eight** has a
positive paired difference and none has a positive interval excluding zero,
while one has a negative one; at `c5`, one of eight positive and **three**
negative intervals; at `r3`, none of eight positive.

**Benjamini-Hochberg over all 1,600 real per-instrument delay cells** at the
headline outcome, on the paired difference: 50 survive q<0.05, **49 of them
positive**, and that is the duty-cycle failure mode rather than a finding.

- **36 of the 50 are arms that refuse 80% to 98% of signals** - `w*` and `v*`,
  production's candle witness - on 44-53-trade cells with a negative baseline.
- The duty-cycle expectation, `-(1 - fill) x mean R0 at k=0`, accounts for them:
  CADCHF `v1` reads +0.8298 against an expectation of +0.8423, excess -0.0125.
  Across all 50 the median excess over that expectation is +0.1189 on cells of
  44 to 53 trades chosen as the best of 1,600.
- By arm family the survivors are **18 `v`, 18 `w`, 11 `r`, 3 `c`, 0 `k`**. The
  **random-delay twin survives more often than the real confirmation does**,
  which is the whole argument in one line.
- The one negative survivor is BTCUSD `c5`: 660 trades, fill 0.923, **-0.0902R
  [-0.1435, -0.0370]** - a well-sampled cell where the confirmation loses.

## The other intervals

**1h, 28 FX pairs, 1,332 trades.** Here the lags read *positive*: `k5` +0.1013
[-0.0064, +0.2245] and `c1` +0.1071 [+0.0325, +0.1760] at p 0.005. **And the
placebo does the same**: random anchors on the same bars give `k5` +0.0603
[+0.0189, +0.1023] at p 0.004 and `c1` +0.0374 at p 0.049. A delay effect that
appears at random anchors on a feed whose baseline is -0.2661R a trade is the
mechanics of trading less on a losing book, not selection, and the placebo
tracking the real arm is exactly the tell. Nothing here survives.

**1d, 14 feeds, 128 trades.** Mean R0 +1.4404 with an interval of [+0.2845,
+2.8254] and a median of -1.000. Under 100 trades the prior is noise and this
is barely above it; the lag differences are +0.02 to +0.15 with intervals three
to four times their own width, and the **placebo's** `k3` reads +0.1866
[+0.0343, +0.3781]. **Unmeasurable**, and reported as such.

## `vol-impulse`: the cleanest arm, and the study's only nominal positives

6,139 trades on five 15m feeds over eleven years. This rule is the better test
of the question because its own exit has **no stop and no target** - so there
is no hit-rate-for-reward exchange for a delay to collect and the only thing
left for it to do is select.

On the rule's own `mark` exit:

| arm | fill | mean R0 | vs k0 | 95% interval | d p | net R0 |
|---|---|---|---|---|---|---|
| `k0` | 1.000 | -0.0245 | - | - | - | -0.1183 |
| `k1` | 0.930 | -0.0117 | +0.0127 | [-0.0214, +0.0466] | 0.467 | -0.0981 |
| `k2` | 0.863 | +0.0213 | **+0.0458** | [+0.0012, +0.0936] | 0.052 | -0.0583 |
| `k3` | 0.824 | +0.0061 | +0.0305 | [-0.0212, +0.0840] | 0.245 | -0.0703 |
| `k5` | 0.766 | +0.0097 | +0.0342 | [-0.0296, +0.1029] | 0.323 | -0.0612 |
| `c1` | 0.445 | +0.0303 | **+0.0548** | [+0.0013, +0.1164] | 0.058 | -0.0107 |
| `c3` | 0.806 | +0.0132 | +0.0377 | [-0.0041, +0.0817] | 0.086 | -0.0616 |
| `c5` | 0.860 | +0.0123 | +0.0368 | [-0.0046, +0.0783] | 0.083 | -0.0676 |
| `r5` (random twin of `c5`) | 0.847 | +0.0101 | +0.0346 | [-0.0097, +0.0837] | 0.134 | -0.0680 |
| **matched placebo, `k2`** | 0.921 | -0.0035 | -0.0007 | [-0.0174, +0.0172] | - | -0.0967 |
| **matched placebo, `c1`** | 0.488 | -0.0112 | -0.0084 | [-0.0313, +0.0149] | - | -0.0611 |

These two cells are the only nominally positive readings in the study and they
fail the pre-registered bar on three counts:

1. **Cost.** Every arm is negative net of the terminal's own quoted round trip,
   which is 9.2% to 9.4% of risk on this rule - `k2` -0.0583, `c1` -0.0107.
2. **The random twin.** `r5` reads +0.0346 against `c5`'s +0.0368. The
   confirmation is not distinguishable from waiting at random.
3. **Multiplicity.** **0 of 125** per-instrument delay cells on this rule
   survive Benjamini-Hochberg at q<0.05, and two marginal cells (p 0.052 and
   0.058) out of twenty arms across five outcomes is below the chance yield.

The fair-rate story repeats on this rule too. At a 2R target the hit rate goes
**0.306 at `k0` to 0.397 at `k5` and 0.529 at `c1`**, against fair rates of
0.333, 0.405 and 0.513 - tracking within 0.016 on this rule - while the paired
difference is +0.0150 [-0.0185, +0.0490] and +0.0302 [+0.0044, +0.0581] and
the net is -0.0593 and -0.0215.

## The controls that must read nothing, and do

**Deriv's Volatility 25 and 75 Index**, 1,367 trades. These are real markets
with a published constant sigma and independent increments, so there is no
information in the bars after a signal and a delay can add nothing *by
construction* - which is the one named property they control for, and they are
offered as a control for nothing else. Every lag's paired difference spans
zero: `k1` +0.0294 [-0.0105, +0.0749], `k3` +0.0006 [-0.0696, +0.0694], `k5`
+0.0696 [-0.0224, +0.1656], `c1` +0.0745 [-0.0052, +0.1513], `c5` +0.0510
[-0.0151, +0.1263]. On 1,367 trades this arm's own resolution is about 0.09R,
so it excludes an effect the size of the one the real arm would need and no
smaller - it is a sanity check, not a tight bound.

## Where the test goes blind

Continuation planted on Brownian-bridge walks of 31 real 15m series, 6,947
trades, and planted **signed**: with the trade where the first two bars moved
with it and against the trade where they did not, so the market gains nothing
on average and a confirmation carries real information about which signals
continue. `strength` is how much further the market travels, in volatility
units, over the whole 96-bar hold.

| planted | `k2` vs k0 | `c2` vs k0 | 95% interval | d p | `c5` vs k0 |
|---|---|---|---|---|---|
| 0 | -0.0148 | -0.0051 | [-0.0376, +0.0265] | 0.755 | +0.0011 |
| 0.10 | -0.0162 | -0.0035 | [-0.0363, +0.0277] | 0.835 | -0.0001 |
| 0.25 | -0.0170 | -0.0003 | [-0.0320, +0.0313] | 0.988 | -0.0032 |
| 0.50 | -0.0160 | +0.0079 | [-0.0242, +0.0389] | 0.634 | -0.0049 |
| 1.00 | -0.0161 | +0.0164 | [-0.0143, +0.0466] | 0.292 | -0.0069 |
| 2.00 | -0.0189 | **+0.0302** | [+0.0008, +0.0591] | 0.043 | -0.0177 |

- **The `c2` arm's response is linear at about +0.017R per planted volatility
  unit**, and the test's own 5% detection threshold on this sample is a plant of
  roughly **2.0 units**. It does not see 1.0.
- The measured `c2` on real `smc-bos-causal` is -0.0201 with an upper bound of
  **+0.0022R**. The fitted line is `diff = -0.0051 + 0.0177 g`, so that upper
  bound sits at **g = 0.41**; measured instead as an excess over the real-bars
  placebo's own `c3` difference of -0.0020, it sits at **g = 0.24**. So the
  *exclusion* is four to eight times tighter than the detection threshold,
  because the real reading is negative and its interval narrow: the data rules
  out a confirmation worth more than **a quarter to two fifths of a bar's
  range** of extra travel over a day's hold, and the two figures differ only in
  which arm's zero is taken as the baseline.
- **A pure wait cannot select and the sweep shows it**: `k2` is flat at -0.015
  to -0.019 across the whole grid. So is `c5`, which fills 90% of signals and
  therefore barely refuses anything. Only an arm that *refuses* can read a
  selection effect, which is a property of the arms rather than of the market.

The first version of this sweep planted continuation only on the confirmers and
read +0.003 to +0.010 at every strength. It was measuring nothing, because the
k=0 arm is in the trade for all 96 bars and collects the planted drift in full.
**A planted effect the baseline captures is not a planted selection effect**,
and that correction is recorded in `plant`'s docstring.

## What the delay costs to execute

Cost in R is `round trip / risk` and is set by the **stop, not the target**.
The round trip is the terminal's own live bid-ask through
`research/harness/venue.py`; 18 of 31 instruments are quoted and the rest are
geometry only, because the per-bar `spread` column is in points and reading a
cost off it is how a pair once screened at a 476% round trip.

**The delay itself is not the expensive part of this idea.** On
`smc-bos-causal` the `N20` floor binds on every tight-spread instrument, so
cost in R is **1/20 = 0.0500 by construction** and the measured figure is 0.049
at every k to three decimals - a later entry moves the entry price but not the
stop distance the cost is divided by. On the 18 priced instruments (6,541
trades) the net readings are `k0` +0.0529, `k1` +0.0415, `k2` +0.0237, `k3`
+0.0121, `k4` +0.0176, `k5` +0.0208, `c3` +0.0334, `c5` +0.0279, `w5` -0.0024:
the lag loses net about what it loses gross.

What *is* expensive is the clock. The same spread is 19 to 21 times dearer at
15m than at 1d; `vol-impulse` pays 9.2-9.4% of risk against `smc-bos-causal`'s
4.9% because its risk is a volatility distance rather than a spread floor; and
the one interval where a lag read nominally positive is 1h, where the placebo
read positive too.

## What this refutes, and what it does not

**Refuted.** That a 1-5 bar confirmation delay adds selection to
`smc-bos-causal` or `vol-impulse` at 15m. The hit rate rises at the fair rate
to within 0.025 at every lag and target, and below it more often than above;
the per-signal expectation falls or does not move; the fall survives turning
the exchange off; the confirmation is indistinguishable from waiting at random
for the same mean length; the matched placebo shows no delay effect at all;
and no per-instrument cell survives multiplicity as an improvement.

**Refuted separately.** That `ArrivalEntry`'s candle witness is a usable
confirmation **at a break price**. It fires on 1.7% of signals within one bar
and 11.5% within five, and the 88.5% it refuses carry the whole of the rule's
reading. That is not a statement about the witness at a *level*, which is what
it was built for and where `confirm.md` already measured production's candle
rule as one of seven narrow survivors.

**Not refuted, and not measurable here.** Any of this at 1d (128 trades); on
`statespace-surprise`, `identity-arb` or `zones` (different harnesses); or for
a lag whose *trigger* is a reading this harness does not have. `ArrivalEntry`
ships two witnesses and the second is `pressure_vol`, a structures feature only
the live service computes. A delay gated on a reading rather than on a bar
count is a different claim and this study does not touch it.

**Not a finding.** `smc-bos-causal`'s own +0.0736R at `k0`. It is the baseline
the differences are taken from, nothing else; its level sits on a badly
conditioned mean (see the calibration above) and it is **not reconcilable**
with [smc-bos-reconcile.md](smc-bos-reconcile.md)'s -0.533R. That figure is 75
trades over 76 days of a different venue with a stop filled from the *next
bar's close*, which the same document measured as pessimistic by +0.081 to
+0.363R. Two settlements on two samples are two numbers and neither corrects
the other.

## What would settle what is left

- **The live `ArrivalEntry` record.** The desk already has the mechanism and
  `follow_untaken` is on by default, so the one thing this study could not
  reach - a confirmation gated on `pressure_vol` at a real level - is already
  being recorded. Read it rather than simulate it.
- **A reading, not a bar count.** Every lag here is a *time* gate, and time is
  the one thing the fair-rate exchange prices exactly. For a delay to pay it
  has to be gated on something whose value at `i + k` is not a function of the
  price path alone, which on this desk means the structures or statespace
  features and not the candles.
- **Nothing more at 1d.** 128 trades needs an order of magnitude more history
  than the store holds.

## For production

**Nothing ships.** No lag survived, so there is no `k` to recommend, no
parameter to add to `ArrivalEntry` and no gate to add to `risk/`. Two
maintenance items came out of reading the code, neither of them this study's
question:

1. **`ArrivalEntry.candle_tolerance_vol` is documented in volatility units and
   implemented as a fraction of price.** `_candle_at` computes `abs(level) *
   candle_tolerance_vol / 100.0`, so the shipped 0.1 is **10 basis points of
   price** - roughly 1.5 to 2 M15 ATRs on EURUSD and about 0.3 of one on gold.
   One field, two units, varying by nothing but the instrument's price level.
   The `v*` arms here run the documented reading and the `w*` arms the
   implemented one; they differ (0.092 against 0.115 fill at k=5) and neither
   is useful, so **fixing it changes no result in this study** - but `one
   column, one unit` is the standing rule and this is a live config field.
2. **`level_shield`'s surrogate arms are not barrier nulls.** `walk-geometry`,
   `bar-shuffle` and `garch-bars` read -0.2055, -0.2078 and -0.6552R with
   random anchors where zero is required, and their *paired* delay differences
   read +0.031 to +0.042 where real bars read +0.001. They remain correct for
   the rate and topology claims they were built for. Any study here that
   settles a stop-and-target race against them is reading its own surrogate's
   wicks, and `research/ideas/price_action.py` uses exactly these arms with a
   bar-level `settle` and a stop-order fill off the bar's open - worth a look,
   with the sign of the bias in mind.

## Pre-registration, as frozen

Written before any cell was run, kept verbatim.

> **The question.** Not "does waiting improve the hit rate" - it will, and the
> repo already measured by how much and why that is free. The question is
> whether a confirmation delay of k bars (k = 1..5) adds **selection**: does it
> refuse trades that would have lost at a higher rate than it refuses trades
> that would have won, **beyond** the hit-rate-for-reward exchange that
> `1/(1+k)` gives for nothing?
>
> **The null is a delay that buys hit rate at the fair rate**, which is
> arithmetic rather than a simulation: price is a martingale under the null and
> every arm's exit is a bounded stopping time, so the expected P&L of any entry
> delay, in units of the k=0 risk and with a refused signal scored zero, is
> exactly 0.000 gross. A second null that costs little and catches a lot: a
> **random delay** of the same mean length, so "waiting helped" is
> distinguishable from "this particular confirmation helped".
>
> **Pass bar.** A lag survives only if its mean has a day-block interval
> excluding zero and positive, net of the venue's own quoted round trip, above
> its random-delay twin, above the matched placebo at the same trade count,
> with the surrogate arms reading zero on the same detector and the Deriv
> constant-sigma indices reading zero, surviving Benjamini-Hochberg across
> every real-market cell, and holding per instrument rather than only pooled.
>
> **Any arm that reads positive on a driftless walk stops the study.** Moving
> an entry forward in time is exactly the operation that can read the bar it
> enters on.

The first run's walk arm read **-0.6378R** where the pre-registration said a
positive reading stops the study. A negative one that large is the same defect
in the other direction and was treated as one.

| added after the first run | the measurement that forced it |
|---|---|
| the **paired** difference from k=0 as the headline statistic | the level is badly conditioned (median -1.000, positive mean) and its null calibration spans 0.75R across surrogate families; the paired difference's calibration is +0.0013 [-0.0081, +0.0101] |
| `walk_path`, a Brownian-bridge arm | the three existing surrogate arms are not barrier nulls: -0.2055, -0.2078, -0.6552R at random anchors |
| a **placebo on every surrogate's own bars** | it is the arm that proved the bias was in the bars and not in the detector, so it is kept rather than discarded as a diagnostic |
| `MODE=calib` and the sub-step sweep | a null is worth reporting with the size of its own measurement error attached |
| `ET_DEMEAN` | "driftless" was not; it moved the bridge arm 0.0075 and was not the cause |
| `ET_STOPMULT` | the one handle that varies the settlement bias while holding the signal fixed |
| the stop filling **at** the stop, not at the worse of the stop and the open | the gap reading is a -0.64R leak in the control; `ET_GAPFILL=1` keeps it available |
| the `mark` outcome | `vol-impulse` has no protective stop and the first reading of it imposed one |
| the **signed** plant | planting continuation only on the confirmers measured nothing, because the k=0 arm collects it in full |
