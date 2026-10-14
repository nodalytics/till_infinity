# What `SWEEP_SIGMAS = 1.0` actually buys

`engine.SWEEP_SIGMAS` sets the band a stop has to clear beyond a level, through
`levels.Level.sweep_zone` and `SideStats.wick_deep_vol`, which returns
`centre + sigmas * reach` - a mean-plus-k-sigma rule. Its own docstring asked
for this measurement:

> One would be roughly the depth 84% of sweeps stay inside **if the depths were
> normal, which they are not** - they are bounded below at zero with a long
> right tail, so real coverage at one sigma is higher than that. [...] This is
> the setting most worth **measuring against outcomes** rather than reasoning
> about.

Both halves of that are right, and the size of the gap is worth having.

## The construction

A sweep depth needs a level and a touch. The level here is the simplest thing
that produces real sweeps - a rolling 100-bar extreme - rather than
production's own proposers, because importing those would make this a test of
`drawing` instead of of the depth distribution. When a bar breaches the prior
extreme, the depth is how far past it the bar reached, in the instrument's own
volatility units. That is the quantity `wick_deep_vol` models.

Twelve instruments, kept separate as well as pooled, since the coverage of a
mean-plus-k-sigma rule is a property of the shape and pooling different shapes
measures the mixture.

## The coverage

| frame | k=0 | k=0.5 | **k=1, live** | k=1.5 | k=2 | k=3 |
|---|---|---|---|---|---|---|
| 15m | 0.674 | 0.842 | **0.918** | 0.951 | 0.969 | 0.984 |
| 1h | 0.663 | 0.830 | **0.907** | 0.945 | 0.967 | 0.985 |
| 4h | 0.657 | 0.836 | **0.915** | 0.952 | 0.972 | 0.988 |

**Production's stop band contains about 91% of sweeps, not 84%.** The docstring
expected the figure to be higher than 84% and it is, by seven points.

Read the other way, the multiplier each target coverage needs:

| frame | 80% | 84% | 90% | 95% |
|---|---|---|---|---|
| 15m | 0.33 | ~0.5 | 0.84 | 1.46 |
| 1h | 0.39 | ~0.5 | 0.94 | 1.59 |
| 4h | 0.36 | ~0.5 | 0.87 | 1.46 |

**If 84% was the intent, the setting is 0.5 rather than 1.0.** That matters
beyond tidiness, because the same docstring records the pressure in the other
direction - "two produces stops wide enough that the size the risk budget then
allows is uninteresting on the tighter instruments". A stop at 0.5 is tighter
*and* hits the coverage that was being aimed at, so this is not a trade-off
between the two, it is a correction.

Also worth noting: `k=0` already contains **two thirds** of sweeps, so the mean
depth alone is a far from negligible band.

## Which family the depths are

By maximum likelihood with AIC over exponential, lognormal, Weibull and Pareto,
on each instrument and pooled:

| frame | pooled winner | margin over second | skew |
|---|---|---|---|
| 15m | lognormal | 213 | 6.9 |
| 1h | weibull | 467 | 7.1 |
| 4h | weibull | 237 | 18.5 |

Per instrument it splits between Weibull and lognormal with margins from 2 to
225, and skew runs from **2.5 to 40**. Nothing here is close to normal, which
is the premise the mean-plus-k-sigma rule rests on.

So the better rule is a **fitted quantile** rather than any multiplier: a
Weibull or lognormal quantile is exact at the coverage asked for, where
mean-plus-k-sigma only approximates it and the approximation drifts with the
skew - which is why `k=1` buys 0.907 on one frame and 0.918 on another.

## Where the Student-t work does not reach

`statespace/tails.py` corrects a **symmetric** predictive band, and
`one-bar-band.md` measured its tail index on close-to-close residuals. A sweep
depth is one-sided and bounded at zero, so a t is the wrong family for it by
construction, and reaching for it here would be using a result outside the
place it was measured. The two corrections are not substitutes:

* `tails.py` answers "how wide for this coverage, on a symmetric residual";
* this answers "how deep for this coverage, on a one-sided depth", and its
  answer is a Weibull or lognormal quantile.

## What this does and does not change

The docstring is corrected, because it stated a coverage that the data
contradicts and that is the kind of claim that gets reasoned from later.

`SWEEP_SIGMAS` is **left at 1.0**. Changing it narrows every live stop and
re-sizes every position the risk budget allows, which is a trading decision
rather than a measurement one - the measurement's job is to say what each
choice costs, and it now does.
