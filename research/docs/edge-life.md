# How fast to forget: deriving the decay factor

**Measured 2026-11-20.** Five FX and metal feeds, 4 years of 5-minute bars,
a 144-cell RSI and moving-average grid, **12,828,065 trades**. Harness:
[`edge_life.py`](../ideas/edge_life.py).

**The premise is the operator's and it is not under test here.** *"We are not
using statespace to trade these signals long term, that is why it is
adapting"*, and *"our system adapts to the markets"* - rules whose edge has a
short life, continuously re-selected, is the **design**. Nothing on this page
screens for a rule that lasts. The half-life is a **tuning** quantity: how fast
the picker should forget, and how far ahead a forecast is worth making. The
operator also set the constraint that it be *"automatically computed and
derived, not fixed"*.

So the question is not *whether* edges decay. It is **which measurable quantity
the decay factor should be derived from**, and this page answers that.

| question | answer |
|---|---|
| can we derive the decay factor from the edge's own autocorrelation? | **no.** The estimator is **blind**: planted half-lives of 10, 50, 200, 1000 and **infinity** all come back as **3.5 to 4.6 trades** |
| so what are the 0.1-trade readings on real data? | the estimator's floor, not a measurement. 144 of 144 combinations read the same thing |
| which quantity *is* estimable? | **log volatility**, by two orders of magnitude - rho **0.9963 to 0.9995** at 1h, half-life **185 to 1253 hours** |
| what does the adaptation cost? | **0.013 to 0.311 R a trade**, a **23-fold** range set by the stop far more than by the clock |

## 1. The power check, which decides everything else

`show-power-before-reporting-a-null` is the standing rule: plant the effect,
sweep its strength, and report where the test goes blind. Done here with
+/-1 trade of noise and 4,000 trades a draw, 40 draws each:

| planted half-life | **recovered median** | 10th-90th | Q/R planted | finite : static |
|---|---:|---|---:|---|
| 10 | **4.6** | 2.7-9.0 | 4.81e-03 | 18/40 : 22 |
| 50 | **4.3** | 2.5-7.7 | 1.92e-04 | 19/40 : 21 |
| 200 | **3.6** | 2.4-8.0 | 1.20e-05 | 25/40 : 15 |
| 1000 | **4.1** | 2.7-6.3 | 4.80e-07 | 22/40 : 18 |
| **infinity** | **3.5** | 2.4-11.1 | 0.00e+00 | 20/40 : 20 |

**A hundred-fold change in the truth moves the answer by one trade.** A series
with *no decay at all* is reported as a half-life of 3.5 trades, and one that
halves every 10 trades is reported as 4.6. Half the draws come back "static"
regardless. The estimator does not measure what it is pointed at.

That makes the real-data run uninterpretable **before** reading it. Which is the
right order: the power check was run because the real numbers looked too tidy,
and it says they were.

## 2. The real-data run, read in that light

| | |
|---|---|
| combinations | 144, all finite, 0 static |
| trades | 12,828,065 |
| half-life in trades | **p10 0, median 0, p90 1** |
| mean R, every one of the 144 | **negative**, -0.033 to -0.078 |

| half-life | trades | mean R | Q | R | combination |
|---:|---:|---:|---:|---:|---|
| 0.1 | 245,236 | -0.0640 | 2.53e-01 | 1.76e-03 | trend_pullback/R1/vol0/sess0 |
| 0.1 | 194,326 | -0.0607 | 2.47e-01 | 1.42e-03 | trend_pullback/R1/vol1/sess1 |
| 0.1 | 154,692 | -0.0699 | 4.79e-01 | 2.90e-03 | trend_pullback/R2/vol1/sess1 |
| 0.1 | 147,456 | -0.0783 | 2.48e-01 | 1.60e-03 | trend_pullback/R1/vol0/sess1 |
| 0.1 | 119,336 | -0.0345 | 2.27e-01 | 1.34e-03 | oversold_falling/R1/vol1/sess1 |

Two separate things to say, and only one of them is a limitation of the
estimator.

**The 0.1 readings are the floor.** They are *below* the 3.5-to-4.6 the power
check recovers from a series with infinite memory, so they carry no information
about decay speed.

**The real series and the planted ones are in different regimes, four to five
orders of magnitude apart in `Q/R`.** The plants ran at `Q/R` of 4.8e-03 and
below - a persistent mean seen through heavy noise. The real combinations read
`Q/R` near **170** (`Q` 2.5e-01, `R` 1.4e-03), and pooled, **7.8**. So the
power check establishes blindness for noise-dominated series and the real data
is drift-dominated. The honest statement is not "the estimator is blind here" -
it is **the estimator is unvalidated in the regime it is being used in**, and
its answer should not be used either way.

**And the mean R being negative on 144 of 144 is a separate finding that needs
no estimator.** Net of one spread each way, at 15m on a 1 ATR stop, the whole
grid loses 0.033 to 0.078 R a trade - which is approximately the **cost** at
that frame and stop (0.0283 to 0.0443 below). Gross is about zero. That is the
same result as [`rsi-ma-momentum.md`](rsi-ma-momentum.md) on a sample 3,000
times larger.

**This is a statement about a grid held still, not about the adapting system.**
A fixed 144-cell grid traded unchanged for four years is exactly the thing the
design says will not work. What it does establish is that **the edge is not
sitting in the cells waiting to be found** - the adaptation has to earn its
return from *re-selection*, and the amount it has to earn is in section 4.

## 3. Where the memory actually is: volatility

`derived_memory`'s local-level model is **refuted on log-ATR by its own
moments**. The model requires `Cov(dr_t, dr_{t-1}) = -R < 0`; on log volatility
that covariance comes out **positive**, which drove `R` onto its 1e-12 floor
and returned a half-life of **0.0 bars**. Log volatility is long-memory, not a
random walk observed through noise, so the moments the model needs do not exist
in it. Both numbers are printed side by side so the refutation is visible
rather than quietly replaced.

An AR(1) on the level is the well-conditioned alternative, `ln2 / -ln(rho)`:

| frame | feed | bars | **rho** | half-life, bars | **half-life, hours** | local-level |
|---|---|---:|---:|---:|---:|---|
| 1h | EURUSD | 24,810 | 0.9969 | 222.6 | **222.6** | 0.0, refuted |
| 1h | GBPUSD | 24,809 | 0.9963 | 184.7 | **184.7** | 0.0, refuted |
| 1h | **GOLD** | 23,515 | **0.9994** | 1253.0 | **1253.0** | 0.0, refuted |
| 1h | USDJPY | 24,807 | 0.9978 | 311.6 | **311.6** | 0.0, refuted |
| 1h | AUDUSD | 24,809 | 0.9970 | 229.2 | **229.2** | 0.0, refuted |
| 15m | EURUSD | 99,330 | 0.9979 | 330.0 | **82.5** | 0.0, refuted |
| 15m | GBPUSD | 99,329 | 0.9976 | 283.3 | **70.8** | 0.0, refuted |
| 15m | GOLD | 94,152 | 0.9995 | 1499.9 | **375.0** | 0.0, refuted |
| 15m | USDJPY | 99,318 | 0.9983 | 408.4 | **102.1** | 0.0, refuted |
| 15m | AUDUSD | 99,328 | 0.9975 | 278.3 | **69.6** | 0.0, refuted |

**Volatility's memory is 7.7 to 52 days at 1h and 2.9 to 15.6 days at 15m**,
and gold's is the longest on both frames by a factor of four. This is the
quantity a derived decay factor should be driven by, for three reasons:

* **It is estimable.** `rho` of 0.9963 to 0.9995 against
  [`reactive-zones.md`](reactive-zones.md)'s shuffled -0.03 to +0.12. There is
  no power problem.
* **It is where the structure already is.** `seasonality-belongs-on-q` puts
  the intraday pattern in volatility rather than in return;
  `relationships-are-contemporaneous` puts the cross-feed structure there too;
  `drive-q-from-the-range` is the same conclusion reached from the estimator
  side.
* **The half-lives differ per feed by 7x**, so a factor derived this way is
  automatically per-feed - which is what "computed, not fixed" has to mean in
  practice.

**The two frames disagree in bars and agree in hours**, which is the check that
this is a property of the market rather than of the sampling: 222.6 bars at 1h
against 330.0 bars at 15m on EURUSD is 222.6h against 82.5h, so the agreement
is partial - the 15m estimate is systematically shorter. That is expected for a
long-memory series fitted with a one-lag model and is the reason to read this
table as an **ordering of feeds**, not as a point estimate of a horizon.

### What a combination *does*, rather than what it earns

| quantity | series | steps | pooled half-life | Q | R | per-series p10-p90 |
|---|---:|---:|---:|---:|---:|---|
| firing rate an hour | 144 | 569,736 | **0.7h** | 2.178e+02 | 2.340e+02 | 0.7-1.8 |

`Q/R` here is **0.93** - the one quantity on this page the estimator is in the
right regime for, since `Q` and `R` are comparable. A firing rate's memory is
**0.7 to 1.8 hours**. That is short, and it is real, and it is about activity
rather than profit.

### Pooled by family, for completeness

| family | series | steps | pooled half-life | Q | R |
|---|---:|---:|---:|---:|---:|
| every combination | 144 | 12,827,921 | 0.3 | 3.490e-01 | 4.461e-02 |
| oversold_turning | 18 | 54,893 | 0.6 | 6.556e-01 | 4.540e-01 |
| ma_pullback | 18 | 675,508 | 0.5 | 7.569e-01 | 3.043e-01 |
| ma_trend | 18 | 1,452,451 | 0.4 | 5.157e-01 | 1.196e-01 |
| ma_stretch | 18 | 970,783 | 0.4 | 4.027e-01 | 7.655e-02 |
| ma_cross | 18 | 285,469 | 0.3 | 8.650e-01 | 1.437e-01 |
| oversold_falling | 18 | 1,476,592 | 0.2 | 3.242e-01 | 3.909e-03 |
| trend_confirmed | 18 | 5,455,673 | 0.2 | 2.183e-01 | 7.243e-03 |
| trend_pullback | 18 | 2,456,552 | 0.1 | 3.555e-01 | 3.073e-03 |

**Read these as `Q/R`, not as half-lives.** The ordering is a ranking of how
drift-dominated each family's trade series is - `oversold_turning` at `Q/R` 1.4
against `trend_pullback` at 116 - and the half-life column is the floor
discussed above. The families whose `Q/R` is near 1 are the only ones where the
estimator has any claim to be in range, and they are also the smallest samples.

## 4. The budget: what the adaptation has to beat

Cost in R is `spread / stop distance`, so it scales with the clock **and**
inversely with the stop. Median recorded spread over median ATR, 4 years:

| frame | stop | EURUSD | GBPUSD | GOLD | USDJPY | AUDUSD |
|---|---|---:|---:|---:|---:|---:|
| 1h | 1.00 | **0.0159** | 0.0186 | 0.0218 | **0.0133** | 0.0180 |
| 1h | 0.50 | 0.0319 | 0.0373 | 0.0437 | 0.0266 | 0.0361 |
| 1h | 0.25 | 0.0637 | 0.0745 | 0.0874 | 0.0532 | 0.0722 |
| 15m | 1.00 | 0.0338 | 0.0392 | 0.0443 | 0.0283 | 0.0380 |
| 15m | 0.50 | 0.0675 | 0.0784 | 0.0887 | 0.0566 | 0.0759 |
| 15m | 0.25 | 0.1350 | 0.1569 | 0.1773 | 0.1132 | 0.1519 |
| 5m | 1.00 | 0.0627 | 0.0725 | 0.0778 | 0.0527 | 0.0698 |
| 5m | 0.50 | 0.1254 | 0.1450 | 0.1556 | 0.1054 | 0.1396 |
| 5m | 0.25 | **0.2509** | 0.2900 | **0.3111** | 0.2108 | 0.2791 |

**Read the stop axis, not the clock axis.** A 1 ATR stop at 5m (0.0627) is
cheaper than a 0.25 ATR stop at 1h (0.0637). The range across the whole table
is **23-fold**, and the stop accounts for 4x of it on every row while the clock
accounts for 4x on every column - so a design that shortens the clock *and*
tightens the stop pays both.

**This settles a disagreement on record.**
[`rsi-ma-momentum.md`](rsi-ma-momentum.md) measured 0.033 to 0.043 R at 15m and
0.067 to 0.091 at 5m on a 1 ATR stop; the operator's note put 1-minute FX at
0.3 to 0.5 R. Both are right about different things: the operator's figure is a
**tight-stop** number and the shelf's is a 1 ATR one. The gap was the stop, not
the clock, and the ladder shows it arithmetically.

**The consequence for an adapting system is a budget.** Short-lived rules
require fast re-selection; fast re-selection is only worth doing on a clock
short enough for the selection to still be current; and that clock costs. So
whatever the re-selection earns must clear **0.013 R at the cheap corner and
0.311 R at the dear one**. `a-shorter-clock-multiplies-cost-in-r` is the
standing form of this - the same spread is 19x dearer at 15m than at 1d - and
this table is it swept on both axes at once.

## What this says to do

1. **Derive the decay factor from log volatility's AR(1), per feed.** It is
   estimable at `rho` 0.996+, it is where `seasonality-belongs-on-q` and
   `drive-q-from-the-range` already put the structure, and it varies 7x across
   five feeds so the derivation is doing real work.
2. **Do not derive it from edge autocorrelation.** The estimator cannot tell 10
   trades from infinity, and the regime the real data sits in is one the power
   check never covered.
3. **Price the clock before choosing it.** A design that re-selects hourly and
   trades 5m with a tight stop starts 0.25 R behind on every trade.
4. **Judge the adapting process forward, never a cell's carry-over.**
   `rules-change-judge-the-adaptation` is the standing instruction, and
   [`rsi-ma-momentum.md`](rsi-ma-momentum.md) has already run it at 7-day
   re-selection: **-0.021 to -0.046 R** a trade. The untested cadence is
   **minutes to hours**, which is the gap this file was built to point at and
   has not yet closed.

## 5. The decay curve, and the confound it leaves open

Period means correlated with themselves at lags 1 to 10, periods swept from one
hour to five days, 414 combinations at 15m over 4 years, minimum 3 trades a
period. Pooled mean **-0.0552 R** in every arm. **Lag 1 is contaminated and
reported separately**: a race entered near a period edge resolves in the next
period, which manufactures a positive correlation there and nowhere else
(`overlapping-outcome-windows-leak`), so the half-life is fitted from lag 2.

| arm | window | pairs at lag 2 | lag 1 | **lag 2** | lag 3 | lag 4 | lag 5 | lag 6 | half-life |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **real** | 1h | 262,850 | +0.155 | **+0.053** | +0.022 | +0.010 | +0.013 | +0.016 | **1.0h** |
| *shuffled-scenarios* | 1h | *1,053,675* | *+0.028* | ***+0.005*** | *+0.001* | *-0.001* | *-0.003* | *+0.001* | *4.5h* |
| *within-volatility* | 1h | *262,850* | *+0.144* | ***+0.047*** | *+0.019* | *+0.007* | *+0.013* | *+0.014* | *1.9h* |
| **real** | 4h | **0** | +0.081 | -- | -- | -- | +0.021 | +0.010 | 6.3h |
| *shuffled-scenarios* | 4h | *584,503* | *+0.002* | *-0.002* | *+0.002* | *-0.002* | *+0.002* | *-0.002* | *none* |
| *within-volatility* | 4h | **0** | *+0.077* | -- | -- | -- | *+0.019* | *+0.008* | *9.7h* |
| **real** | 24h | 65,190 | +0.012 | **+0.045** | +0.028 | +0.013 | +0.033 | +0.019 | 821.4h |
| *shuffled-scenarios* | 24h | *118,772* | *-0.003* | ***+0.007*** | *+0.001* | *-0.002* | *+0.003* | *+0.006* | *248.4h* |
| *within-volatility* | 24h | *65,190* | *+0.014* | ***+0.044*** | *+0.028* | *+0.011* | *+0.031* | *+0.017* | *1715.7h* |
| **real** | 120h | 38,472 | +0.049 | +0.016 | +0.041 | +0.028 | +0.044 | +0.036 | none |
| *shuffled-scenarios* | 120h | *41,483* | *-0.014* | *-0.003* | *-0.001* | *-0.013* | *-0.008* | *-0.007* | *none* |
| *within-volatility* | 120h | *38,472* | *+0.048* | *+0.015* | *+0.042* | *+0.028* | *+0.043* | *+0.037* | *none* |

**There is a combination-specific autocorrelation at one-hour windows, and it
is not volatility.** At lag 2, real reads **+0.053**, permuting which
combination owns each trade takes it to **+0.005**, and removing each period's
volatility band mean leaves it at **+0.047**. Those two arms answer two
different questions and both answers point the same way: the persistence
belongs to the *combination* (the permutation destroys it) and not to the
*regime* (the volatility adjustment does not). `auc-is-free-on-volatility-targets`
is the standing warning that makes the second arm necessary, and this is the
rarer outcome where a finding survives it.

**The decay is fast.** +0.053, +0.022, +0.010 across lags 2 to 4 is a half-life
of about **one hour**, two hours after the volatility adjustment. That is the
scale the operator's design is pitched at, and it is the first measurement on
this desk to put a number on it.

**And at 24 hours and beyond it stops being a decay.** The 24h row is +0.045,
+0.028, +0.013, +0.033, +0.019 - positive throughout, with no ordering, which
is why the fitted 821h is meaningless rather than long. At 120h there is a
small persistent positive correlation with no shape at all, against a slightly
*negative* shuffled arm. So the hour scale carries a decaying signal and the
day scale carries a flat offset; only the first is something a forgetting rate
can be derived from.

### Two things that are wrong with this measurement

**The arms are not sample-matched, by a factor of four.** Real has 262,850
pairs at 1h against the permuted arm's 1,053,675. The `--least 3` gate admits a
period only when that combination fired at least three times in it, and
permuting ownership spreads trades evenly so far more periods qualify. More data
makes the control's estimate *tighter* rather than smaller, so the +0.053
against +0.005 gap is not a precision artefact - but the real arm's correlation
is computed on a **selected subset: the hours in which a combination was
unusually busy.**

**Which is a live confound, at exactly the same half-life.** Section 3 measures
the firing rate's own memory at **0.7 to 1.8 hours**. The edge correlation here
decays with a half-life of **1.0 to 1.9 hours**. Consecutive busy hours for a
combination are correlated in *activity*, and if outcome depends on activity -
through stop geometry, through which part of the session fires, through the
spread at the moment of firing - then this correlation is the firing rate's and
not the edge's. The two numbers matching to within the fit's resolution is not
evidence that they are the same thing, but it is exactly the coincidence that
should be ruled out before anything is built on this.

**Neither existing arm controls for it.** `shuffled-scenarios` changes the
sample as well as the ownership; `within-volatility` removes the regime but not
the activity. The control this needs is a **firing-rate-matched** arm: permute
ownership *within* periods of equal activity, so the comparison holds the busy
subset fixed. `a-control-is-only-for-a-named-property` is the standing rule and
the property to name here is activity, not volatility.

**The 4h row is broken and should not be read.** Real and within-volatility both
report **0 pairs at lag 2** while the permuted arm reports 584,503, and lags 3
and 4 are missing too. A window that admits no qualifying consecutive pairs for
the real arm but half a million for its control is a gate interacting with the
window length, not a measurement. The 6.3h and 9.7h half-lives in those rows are
fitted from lags 1, 5 and 6 and mean nothing.

## What is still open

* **The firing-rate-matched arm**, which decides whether section 5's finding is
  an edge or an activity artefact. Until it runs, the one-hour half-life is a
  candidate, not a result.
* **The 4h gate defect**, which needs the minimum-trades rule to scale with the
  window rather than sit at 3.
* **The forward test of the adapting process at hour scale.** The 7-day cadence
  is measured at -0.021 to -0.046 R a trade; the minutes-to-hours cadence that
  section 5 points at has never been run end to end, and section 4 says it
  starts between 0.013 and 0.311 R behind.
