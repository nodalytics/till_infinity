# Particle filters do not improve levels, and the control says why

**Measured 2026-10-08.** Asked: "research how we can use particle filters to
improve levels, we can run it as an alternative to kalman or even run both
together". Code: [`level_filters.py`](../ideas/level_filters.py).

**Answer: no, and not for a subtle reason.** On 856,638 predictions over 22,402
levels a particle filter ties the Kalman on median error, loses on mean and
tail error, and needs a wider band for less coverage.

## The control is what makes the answer mean anything

A particle filter differs from the Kalman in **two** ways at once: it carries a
sample instead of a Gaussian, and it can use any likelihood. Run only those two
arms and a win is unattributable - it could be the particles or it could be the
heavier tail, and those have very different costs.

So there are three:

| arm | what it is |
|---|---|
| `kalman` | the production shape - Gaussian innovation, exact update |
| `robust` | **the same filter, innovation Huberised** - heavier-tailed likelihood, no particles |
| `particle` | a sample over `(price, slope)`, Student-t likelihood, systematic resampling |

`robust` is the arm that decides. If `particle` only matches it, the answer is
"use a heavier-tailed likelihood" and the particles are machinery for nothing.

## The arms can separate - on synthetic touches they do

Worth establishing before the null, or the null means only that the test was
blunt. 400 synthetic levels, 12 touches each, every arm given the same process
and observation noise:

| touches | kalman | robust | particle |
|---|---:|---:|---:|
| Gaussian, median error | 0.4011 | 0.4037 | 0.4021 |
| **heavy-tailed** (10% at 6x), median error | 0.4853 | 0.4632 | **0.4375** |
| heavy-tailed, coverage | 0.801 | 0.803 | **0.864** |

Where the Gaussian assumption holds, all three are the same and the particle
filter costs nothing and gains nothing - which is correct. Where it does not,
the ordering is exactly as theory says: `particle` beats `robust` beats
`kalman`, on error *and* on coverage.

## On real touches they do not

22,402 levels of 5+ touches, from three-bar pivots clustered within 0.75
volatility units, across 1h, 4h and 1d:

| iv | arm | median err | mean err | p90 err | coverage | width |
|---|---|---:|---:|---:|---:|---:|
| 1d | kalman | 0.3430 | **0.3702** | **0.7083** | 0.9831 | **2.045** |
| 1d | robust | 0.3433 | 0.3706 | 0.7090 | 0.9823 | 2.045 |
| 1d | particle | **0.3424** | 0.3799 | 0.7473 | 0.9794 | 2.135 |
| 1h | kalman | 0.3595 | **0.3765** | **0.6964** | 0.9858 | **1.868** |
| 1h | robust | 0.3594 | 0.3767 | 0.6973 | 0.9851 | 1.868 |
| 1h | particle | **0.3572** | 0.3877 | 0.7441 | 0.9764 | 1.962 |
| 4h | kalman | 0.3569 | **0.3783** | **0.7062** | 0.9834 | **1.954** |
| 4h | robust | 0.3571 | 0.3786 | 0.7072 | 0.9827 | 1.954 |
| 4h | particle | **0.3566** | 0.3893 | 0.7511 | 0.9774 | 2.049 |

The particle filter's advantage over `robust` on median error is **-0.0009 to
-0.0022 units** against errors of 0.34 to 0.36. That is a tie reported to four
decimals, not a win. On every other column it is behind: higher mean error,
higher p90, and a **wider** band for **lower** coverage, which is the filter
paying for coverage rather than earning it.

## Why - and this is the useful part

**`robust` is identical to `kalman` to four decimal places.** Their widths
agree exactly. That means the Huberised update essentially never fires, which
means real touch residuals almost never exceed `HUBER_C` of the filter's own
spread.

So the heavy-tailed observation problem that a particle filter exists to solve
**is not present in this data at this level**. There is nothing for either a
heavier likelihood or a sample representation to fix, and both correctly do
nothing while costing compute.

That also lands on an open question from
[`structures-roadmap.md`](structures-roadmap.md), which lists Student-t
observation noise as worth doing and notes the repo already dodges the problem
upstream by taking `done.origin` over `done.extreme` - "the extreme is a wick".
**This is evidence that the dodge works**: having removed the wick from the
observation, what is left is not heavy-tailed enough to matter. The robust
filter is a fix for a problem already fixed somewhere cheaper.

## The incidental finding, which is larger than the one asked for

**Every arm covers 97.6-98.6% with a band asked to cover 90%.**

That is not a filter being cautious, it is a predicted spread that is too wide
by a lot, and all three inherit it because all three were given the same
process and observation noise. A Gaussian multiple on an overstated spread
gives 98% where 90% was asked, and a zone that wide calls every passing wick a
touch.

Independent support for the conformal calibrator, from a direction it was not
designed to be tested from: the band needs calibrating against what touches
actually do, and that is exactly what it now does. It also suggests the error
in production is in the **wide** direction, which is the one that costs
opportunity rather than accuracy and so is the harder one to notice.

## What this does not say

The touch clusters are a **proxy** for `levels.form` - three-bar pivots grouped
by proximity, not the production former with its prominence ranking, merging
and per-side statistics. If production levels have different touch statistics
the answer could differ, though the mechanism found here - residuals that are
not heavy relative to the filter's own uncertainty - is not delicate.

And it says nothing about the multimodality argument, which is the other reason
particle filters were raised. That one is already parked on the grounds that
two candidate prices for a level is **two levels**, not one level with two
modes, and the repo's answer to that is `form` and `merge`.

## Running both together

The question asked whether both could run. They can - and on this evidence
there is no reason to. The arms agree to three decimal places on real data, so
a hybrid would spend twice the compute to arbitrate between two filters that
are saying the same thing.

If the regime ever changes - if a feed starts producing genuinely heavy-tailed
touches - the synthetic row above says the particle filter would pull ahead and
by how much. The cheap way to watch for that is not to run both: it is to watch
whether the Huberised update ever starts firing, which is one counter on a
filter already running.

## Adaptive observation noise: also nothing (2026-10-09)

The fourth arm, and the one idea from the levels critique I thought worth
building. `observe_touch` gives every touch the same observation noise,
`(0.5v)**2`, whether it was a decisive rejection or a chaotic probe. `adaptive`
scales that by how much of the turning bar was wick:

    R = (NOISE * unit * (1 + WICK_PENALTY * wick_share)) ** 2

**Why it is a different claim from `robust`**, and the reason both are run:
`robust` discounts an observation for landing far from the prediction, which is
a function of the observation itself - it can only say "that disagreed, so
trust it less", which flatters the filter. This discounts it for **looking**
unreliable, from the shape of the bar, before anything is known about whether
it agrees. Only the second could be computed live without peeking at the
residual.

### The mechanism works

Established first, on synthetic pools, or the null below would only mean the
test was blunt:

| | kalman | robust | particle | **adaptive** |
|---|---:|---:|---:|---:|
| wick share predicts noise, median err | 1.1144 | 1.1556 | 1.0909 | **1.0661** |
| wick share unrelated, median err | 0.7008 | 0.7080 | 0.7021 | **0.6957** |

It gains where the quality signal is real and costs nothing where it is noise,
which is exactly the property wanted.

### On real touches it finds nothing

604,825 predictions at 1h:

| arm | median err | mean err | p90 err | coverage | width |
|---|---:|---:|---:|---:|---:|
| adaptive | 0.3600 | 0.3764 | **0.6945** | 0.9904 | 1.9222 |
| kalman | **0.3595** | **0.3765** | 0.6964 | 0.9858 | **1.8676** |

Worse on the median, identical on the mean, **0.3% better in the tail**, and it
needs a wider band for the extra coverage. The same holds at 4h and 1d.

**So wick share does not predict how informative a touch is.** The mechanism is
sound and the signal is absent, which is a different and more useful negative
than "it did not work".

### And it is the same reason the particle filter found nothing

`robust` is identical to `kalman` to four decimal places, which says real touch
residuals almost never exceed its threshold relative to the filter's own
spread. There is no heavy tail to down-weight - so neither a heavier likelihood
(`robust`), nor a sample representation (`particle`), nor a prior on
measurement quality (`adaptive`) has anything to work with.

Three different attacks on the same assumed weakness, all finding it is not
there. The observation noise being **too wide by about 25%**
([`level-dispersion.md`](level-dispersion.md)) is a real defect in the same
constant; its *conditioning* is not.
