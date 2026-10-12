# The members on real markets: the walk is the best-calibrated of them

Asked on 2026-10-12: test and backtest the state-space members against real
markets. Seven traded instruments at 1h, each member's process noise fitted on
the first half and everything scored on the second, run in the lab.

Two things already existed and are not repeated. `statespace_fx.py` ran the
**directional** question - a Kalman AR(1) drift, 13 of 96 cells past
Benjamini-Hochberg at AUC 0.510 to 0.523 against walks at 0.49 to 0.51. And
`statespace-measured.md` has a coverage table on **one cell**, with `linear`
at 68.6% against a nominal 95% - which turns out to have been a verdict on a
default rather than on the model.

## Calibration, which is the reading the desk would actually use

A stop is a band. So the question is whether the band asked for at the next
reading's time contains the next value at the rate the member claims.

| member | cover 1 sigma | cover 2 sigma | error at 2 sigma | width | lag-1 of `z` |
| --- | --- | --- | --- | --- | --- |
| **walk** | 0.823 | **0.953** | **0.001** | 2.00 | **-0.013** |
| switching | 0.773 | 0.933 | 0.022 | 2.06 | +0.151 |
| reverting | 0.675 | 0.888 | 0.067 | **1.54** | -0.369 |
| kalman | 0.626 | 0.860 | 0.095 | 2.39 | -0.447 |
| kalman + clock | 0.625 | 0.861 | 0.093 | 2.44 | -0.458 |

Nominal is 0.683 and 0.954. Medians over seven instruments.

**The random walk's two-sigma band is right to one part in a thousand** -
0.953 against 0.954 - and its residuals are the whitest of the five. Nothing
in the package beats a flat forecast with a `sqrt` band at the job of saying
how wide the next move might be.

`reverting` has the narrowest band at 1.54 and covers only 0.888, which is why
width is reported as a ranking **among the calibrated only**. A narrow band
that does not cover is not sharp, it is wrong, and ranking on width alone
rewards exactly that.

### Two diagnostics worth reading off this

**`kalman`'s residuals are negatively autocorrelated at -0.45.** That is not
imprecision, it is the state equation being wrong in a specific direction: the
member extrapolates a trend which then reverses, so one residual predicts the
next with the opposite sign. `reverting` has the same defect at -0.37.
`switching` errs the other way at +0.15, and the walk is flat.

**The walk over-covers at one sigma while being exact at two.** 0.823 where
0.683 is nominal, and 0.953 where 0.954 is. That pattern is the leptokurtic
signature: more mass in the centre *and* in the far tails than a Gaussian,
with less in between. It means the coverage being right at two sigma is partly
a coincidence of where the crossover sits, and a three-sigma band would
under-cover. **A member calibrated at two sigma should not be assumed
calibrated at three.**

## The P&L arm

The member's own one-step view as the signal - long when it expects the next
reading above the current price - held 24 hours, one position at a time, cost
1.5 spreads round trip, against the same number of random entries at the same
holding time.

| member | trades | total | random entries | beat random |
| --- | --- | --- | --- | --- |
| switching | 624 | **-885.7** | -937.6 | 4 of 7 |
| reverting | 624 | -1030.2 | -939.6 | 2 of 7 |
| kalman | 624 | -1035.3 | -940.3 | 0 of 7 |
| kalman + clock | 624 | -1051.6 | -932.6 | 0 of 7 |

In one-bar volatility units, median over seven instruments. **0 of 28 cells are
profitable after cost.**

The arithmetic is worth doing explicitly, because it is the whole result: 624
trades at 1.5 spreads is **936 volatility units of cost**, and the totals run
from -886 to -1052. **The entire loss is the cost.** Random entries lose 940,
which is the same number. The signal contributes approximately nothing in
either direction - it neither pays for the spread nor digs a hole beyond it.

`switching` is the only member that beats random entries more often than not,
4 of 7, and the only one whose total is better than cost alone. That is
consistent with it being the one member whose fitted parameters stayed
interior in `statespace-new-members-measured.md`, and it is far too small to
act on.

`walk` does not appear: its forecast is flat by construction, so it has no
view to trade. That is the point of it.

## A caveat that matters for reading any of these numbers

**The ranking between members depends on the assumed measurement variance.**
Here `R` is a quarter of a typical bar move squared, shared across every
member so the comparison is of dynamics rather than of calibration. At that
`R` the walk leads `kalman` by about 33,000 nats on EURUSD. At the larger `R`
`statespace-clock-levers.md` happened to use, the same members sit within a
couple of thousand of each other.

The reason is mechanical: a small `R` forces the filter to explain the
movement with its dynamics, which penalises bad dynamics heavily, while a
large `R` lets measurement noise absorb the error and the models converge. So
**an absolute likelihood gap between two members is only meaningful with the
`R` quoted beside it**, and the clock-levers note's "within two thousand nats"
should be read as specific to its `R` rather than as a general claim.

What does not depend on `R` is the coverage table, because a band is checked
against outcomes rather than scored against a density, and the ordering there
is unambiguous.

## What this changes

* **Use the walk's band for stops**, not a member's. It is the only one
  honest at two sigma, and the one to beat - **with the correction
  `statespace-touches.md` measured.** Everything in this note is on closes,
  and a stop is hit on a touch: on ticks the two-sigma band holds a *quoted*
  path 0.944 of the time where it contains the next close 0.969, so the real
  breach rate is 0.056 per interval rather than 0.047. At one sigma the gap
  is 0.115 and a close-based reading is not usable at all. The correction
  scales with the spread in units of the interval's volatility.
* **Do not trade a member's direction.** Zero of twenty-eight cells clear
  cost, the loss equals the spread paid, and this agrees with every previous
  attempt: at most 6 of 45 bin pairs orderable in
  `statespace-informatory-pairs.md`, AUC 0.51 in `statespace_fx.py`, and the
  up/down edge at -98% with good fills.
* **`kalman` needs its state equation looked at, not its noise.** A -0.45
  residual autocorrelation is a misspecification rather than a
  mis-calibration, and no amount of fitting the jerk will fix a model that
  extrapolates what reverses.
* **Quote the `R`** with any likelihood comparison between members.

The harness is `research/ideas/backtest_members.py`.
