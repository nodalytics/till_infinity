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

## The shape, chased down

The residual above was the shape, at one bar, after sigma is tracked. Three
hypotheses were tested in order, and the third is the answer.

### Discreteness: refuted

The first guess was that a one-bar return lives on a tick grid and carries the
bid-ask bounce, so no continuous density can fit a distribution with mass
points in it. `tick_grid.py` measures it, and it is not that. Only **0.06% to
2.4%** of one-bar changes land on exactly zero, and a typical move spans **27
to 413 ticks**, so the grid is far too fine relative to the move to matter.

Discreteness predicts a negative correlation of flatness with ticks per move
and a **positive** one with the share of exact zeros. The first is there at
-0.375, the second is **-0.022** - absent, and the wrong sign. With zero shares
that small there is no mass point to fit around.

### A faster tracker: a trap, and worth naming

`sigma_sweep.py` sweeps the half-life, which `one-bar-band.md` never did. The
misfit falls monotonically as the tracker speeds up - at 1h from 0.0782 at
half-life 40 to **0.0212 at half-life 2**, with no bottom reached - and adding
a second, slower timescale always lands between its two members rather than
beating either.

That looks like a fix and is not one. **A noisy variance estimate is itself a
mixture, and a mixture of Gaussians has fatter tails than a Gaussian**, so a
fast tracker can flatten the PIT for a reason that has nothing to do with
knowing more about the next bar's scale. Scoring CRPS beside flatness separates
them, because CRPS is proper: at 4h and 1d a half-life of 1 **costs** CRPS
(1.033 and 1.030) while barely flattening. That calibration was bought with
estimation noise and paid for in sharpness.

This is the same shape as the lesson already on record that the noise argument
is a variance. It is worth keeping because the flatness statistic alone would
have accepted it.

### The family: the fix

A **Student-t over the slow sigma** is both the flattest arm and the cheapest
on CRPS, simultaneously, which rules out the noise explanation - a proper score
does not fall for a worse forecast. At 1h a t with dof 4 reads 0.0057 against
the Gaussian's 0.0782, at a CRPS of 0.987.

`sigma_holdout.py` then fits dof on a training half and scores only the
held-out half, per feed, two ways: by **maximum likelihood on the standardised
residuals**, which never sees CRPS or the PIT, and by CRPS on the training
half, the greedy version. The verdict is a count of feeds, not a median.

| frame | gaussian flatness | t flatness | x calibrated, gauss to t | CRPS | mle dof | crps dof |
|---|---|---|---|---|---|---|
| 15m | 0.054 to 0.096 | 0.0014 to 0.017 | ~140x to **3-9x** | 0.985 to 0.990 | 3.72 | 4.00 |
| 1h | 0.062 to 0.102 | 0.0021 to 0.021 | ~180x to **5-20x** | 0.983 to 0.990 | 3.22 | 3.50 |
| 4h | 0.050 to 0.114 | 0.0034 to 0.050 | ~170x to **7-40x** | 0.983 to 0.993 | 3.23 | 4.00 |
| 1d | 0.038 to 0.078 | 0.0121 to 0.040 | ~60x to **15-50x** | 0.993 to 0.997 | 5.13 | 5.00 |

**Flatter on 8 of 8 and cheaper on 8 of 8, at every frame, under both dof
choices** - 64 of 64 out-of-sample wins. The CRPS margin is small, 0.3% to
1.7%, but it is unanimous, which is what the per-feed count was added to show.

Three things make this a found effect rather than a fitted one:

- **The two dof estimates agree.** Maximum likelihood on the residuals and the
  CRPS-greedy choice land in the same place at every frame, and they are
  computed from quantities that do not share a formula.
- **The tail index rises with the frame**, about 3.5 intraday to about 5 daily.
  That is aggregational Gaussianity - returns get closer to Gaussian as they
  are summed - recovered here without being looked for.
- **It is unanimous per feed**, so no median is hiding a split.

One honest exception: on gold the MLE is too fat. At 1h and 4h it picks dof
2.89 and 2.65 and reads flatness 0.0207 and 0.0502, against 0.0040 and 0.0151
at the CRPS choice of 3.5 and 3.0. The likelihood is pulled by a few extreme
bars. Both still beat the Gaussian on both scores, but **the tail index wants a
floor near 3**.

## What this says about `robust.py`

It settles the open question, and in the opposite direction to the lever on
record. The problem was never the **scale** estimator, which is what a robust
sigma addresses, and which is why no amount of work on `robust.py` could reach
it. The problem was the **family**. The residuals after a well-tracked sigma
are t-distributed with about 3 to 5 degrees of freedom, and fitting them a
Gaussian misses by 60 to 180 times the calibrated misfit at every frame and on
every feed tested.

A robust scale and a fat-tailed family are easy to confuse because both are
responses to outliers. They are not interchangeable: one changes what the band
is centred and sized by, the other changes its shape, and only the second was
ever the defect here.

## What is left

The t closes 95% or more of the gap but does not close it: the best arms still
sit at 3 to 50 times the calibrated misfit, lowest at 15m and highest at 1d
where the samples are smallest. Whether that remainder is skew - the t is
symmetric and returns are not - or simply the dof being held fixed where it
drifts, is the next measurement, and it is a much smaller one than this was.

The production change this implies is a separate piece of work: the band used
for stops is currently calibrated against the walk, and swapping its family is
a live change to be measured on its own.
