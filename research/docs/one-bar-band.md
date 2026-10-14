# The one-bar band is a sigma problem and a shape problem, and the range estimator fixes neither

`statespace-tail-shape.md` leaves exactly one horizon genuinely miscalibrated.
The often-quoted PIT flatness range of 18 to 461 was mostly an **overlap
artefact** - the forward window stepped one bar at a time, so at h=20
consecutive residuals shared 19 of their 20 bars, and stepped by the horizon
h=20 reads **1.6**. Only **h=1** stands, because a one-bar horizon has no
overlap to remove.

That document also closes both candidate levers, and corrects an earlier claim
of mine in the process. **`robust.py` is not the tail lever**: it inflates
measurement variance when an innovation is surprising, which changes the
**gain** and leaves the predictive density Gaussian, so it cannot move a PIT -
a PIT is a statement about the *shape* of the forecast density. A **Student-t**
is not the answer either, and `nu` depends on the horizon.

## The hypothesis was that it is not a tail at all

A flatness far above one at a single bar does not need a fat-tailed density to
explain it. **A Gaussian with the wrong sigma, bar to bar, is already
leptokurtic in aggregate**: residuals standardised by a sigma that does not
track are a mixture of normals at different scales, and that mixture is
fat-tailed even though no component is. Volatility clusters, so a constant
sigma guarantees exactly that.

If so, the fix is not a shape - it is a better one-bar sigma. And
`candle-screen.md` had just measured one: the range-based estimator, 0.6484
within strata on twenty FX feeds and 0.6671 on 371 of 392 equities, wired as
`spanning.Span` in #231 with its own gate stated as *it has to beat `Q(dt)`,
not a six-bin dial*. This is that comparison, on the metric the band problem is
written in.

## Measured, four arms, one bar ahead

| frame | arm | flatness | per-feed median | CRPS |
| --- | --- | ---: | ---: | ---: |
| 15m | constant | 5,479 | 690 | 3.0022 |
| | **ewma close** | **2,055** | 253 | 2.8894 |
| | ewma range | 2,071 | 252 | **2.8822** |
| | garman-klass | 2,101 | 251 | 2.8828 |
| 1h | constant | 5,667 | 729 | 6.0381 |
| | **ewma close** | **2,589** | 346 | 5.8620 |
| | ewma range | 2,893 | 386 | 5.8592 |
| | garman-klass | 2,986 | 397 | 5.8625 |
| 4h | constant | 5,692 | 758 | 12.9654 |
| | **ewma close** | **2,539** | 338 | **12.5597** |
| | ewma range | 3,162 | 409 | 12.5858 |
| | garman-klass | 3,421 | 437 | 12.6068 |

**The sigma is a large part of the problem.** Tracking it at all cuts flatness
by 55 to 64% - 5,479 to 2,055 at 15m, 5,692 to 2,539 at 4h. That part of the
hypothesis holds.

**The range estimator does not fix it, and makes it worse at 1h and 4h.** 2,589
to 2,893 and 2,539 to 3,162. On CRPS it is marginally better at 15m and 1h and
worse at 4h, so it is not rescued there either.

That is a real result about #231 and the two things come apart. A range-based
estimator is better at predicting **where volatility goes next** and worse as
the **scale for the next close-to-close residual** - because a bar's range
systematically exceeds its close-to-close move, so standardising by it produces
bands that are too wide. `Span` should drive `Q` for forecasting and should
**not** set the one-bar predictive scale. Those are different jobs and the same
number does not do both.

**And a large residual survives the sigma fix**, so there is a genuine shape
problem left once conditional variance is handled - which `robust.py` still
cannot touch, for the structural reason above.

## One defect in the metric, which matters for reading it

**Chi-square per degree of freedom is not sample-size invariant.** For a fixed
relative misfit in each bin, chi-square grows linearly with `n`, so a flatness
of 2,055 on 318,392 observations is **not** comparable to the 73.3 on record
from a smaller sample. The arms here are comparable to each other - identical
`n` by construction - and not to that figure.

Anything comparing calibration across samples needs a size-free statistic: the
largest absolute deviation of a bin's frequency from `1/BINS`, or chi-square
divided by `n` rather than by degrees of freedom. The per-feed median column is
closer to size-free, and it tells the same story - 690 to 253 at 15m with the
range arms at 252 and 251, and 758 to 338 at 4h with the range arms at 409 and
437.

## What is left

The shape, at one bar, after sigma is tracked. Neither lever on record can move
it, and the honest next hypothesis is not a fatter continuous density but a
**discrete** one: a one-bar return lives on a tick grid and carries the
bid-ask bounce, and no continuous density fits a distribution with mass points
in it. That is measurable - the share of one-bar changes landing on zero, one
and two ticks - and it has not been measured here.
