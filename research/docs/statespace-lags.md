# statespace: a panel of stale forecasts at one to twelve hours

Asked on 2026-10-11: run the same member at lags of one to twelve hours and test
whether the **agreement, overlap or disagreement** between those stale forecasts
is a signal. The harness is `research/ideas/lag_agreement.py`.

A member fitted up to `t - L` has an opinion about where the value is now. Run
that at seven lags and you have a panel of opinions about the same instant,
formed at different distances from it, and three readings come out of it that no
single forecast has:

* **agreement** - do the stale forecasts agree on which side of the current
  price the value sits?
* **overlap** - do their uncertainty bands intersect? Two forecasts can agree on
  a sign while being incompatible about the magnitude.
* **disagreement** - how far apart they are, in volatility units. Unlike a
  member's own `sd` this is not a model output, so it cannot be flattered by a
  member that reports a confident band.

Lags are **hours**, converted per series from its own spacing and trading
coverage, per the package rule. The panel is written **forward** - at bar `j` the
member projects to `time[j] + L` and the result is stored against the bar that
lands on - so every entry read at bar `i` was computed strictly before `i` by
construction rather than by an off-by-one that has to be argued about. Three
members (`kalman`, `reverting`, `swarm`), five series, two timeframes, three
horizons: 90 cells per feature.

## The answer: no, and the way it died is the useful part

| feature | mean rho | control | dominant sign | net of trailing sd |
|---|---|---|---|---|
| agreement -> direction | 50.7% | 50.1% | 57/90 | - |
| trailing sd -> \|move\| | **+0.158** | +0.000 | 87/90 | - |
| overlap -> \|move\| | -0.090 | +0.015 | 80/90 | -0.032 |
| disagreement -> \|move\| | +0.098 | -0.017 | 77/90 | +0.033 |

**Direction is a coin, again.** 50.7% against a 50.1% control over 90 cells. The
panel agreeing unanimously about which side of the price fair value sits says
nothing about which way it then goes.

**The magnitude readings are real and are a volatility proxy.** Disagreement
predicts the size of the next move and overlap predicts its smallness - the same
effect twice, with the signs the right way round. But a **trailing standard
deviation over the same window beats both**, +0.158 against +0.098, and net of
it the panel contributes +0.033. The sign of that residual is consistent
(65/90) and its size is at the level a partial correlation's unmodelled
curvature can produce, so it is not an edge: it is the panel being a slightly
different, worse estimator of the thing the simplest possible estimator already
gets.

That is the same verdict a three-state HMM, a fifty-neighbour analogue and an
Ising susceptibility have all received here against the same baseline.

## Two bugs, and both were caught by their own output

**The control was arithmetically void.** The matched null rotates the feature
circularly - same distribution, same autocorrelation, no alignment - and the
rotation was a *fixed count*, `SHIFT = 1013`. On 999 independent points that is
a shift of **14**, which destroys nothing, so every control landed on top of the
statistic it was meant to null and the first table read "no signal" for a reason
that had nothing to do with the data. Fractions of `n` cannot fail that way, and
three of them averaged removes the dependence on one arbitrary offset.

**The normalisation leaked the trend.** The series was put in volatility units
as cumulative *arithmetic* return from a fixed base, `(c / p0 - 1)`, whose
increments are proportional to the current price. On a series that has trended a
long way the later bars move more in those units than the early ones for the
same proportional move, so both "how far apart are the stale forecasts" and "how
big is the next move" scale with the price level and the correlation between them
is the trend.

It announced itself: the effect was strongest on exactly the two series that
trend hardest, v75 1h at rho +0.288 and xauusd 1h at +0.363, and the mean across
cells was +0.154. In log returns, which are additive and scale-free, the mean
falls to +0.098 and **v75 drops to +0.03** - which is the synthetic control
working, because v75's volatility barely autocorrelates and a trailing sd only
reaches +0.034 on it either. A reading that survives on a series whose
volatility is known to be unforecastable is a reading of something else.

Both are in the `finding-bugs` skill: a control that is not a control, and a
measurement whose units carry the effect.

## What it cost, and what to keep

The panel itself is cheap - one pass, projections written forward - and the
machinery is worth keeping for the diagnostic rather than the signal: a member
whose stale forecasts disagree *with each other* more than its own bands allow
is mis-specified, and that is `paired.Paired`'s question rather than a trade.

The honest summary of the lag family is the same as the rest of this work: the
magnitude is forecastable and the simplest estimator of it is hard to beat; the
direction is not forecastable by anything tried here.
