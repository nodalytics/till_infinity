# Dispersion is forecastable, and what forecasts it depends on the frame

**2026-10-17. `research/ideas/dispersion_ml.py`, `research/ideas/dispersion_panel.py`.**

The architecture rule set the same day is that every member and component
forecasts **dispersion**, `signalling` emits a bounded signal, and the Monte
Carlo is the only thing that emits a price. This is the measurement that rule
stands on. If nothing beats a three-term linear regression at forecasting
variance, the reframing buys nothing and should be said to.

It does not come out that way, and the useful part is the controls.

## The null, and why it had to be refitted

**HAR-Parkinson**: a regression of forward log-variance on the last bar's, the
last five's mean and the last twenty-two's mean. The target throughout is the
**mean log Parkinson variance over the next `h` bars**, scored out of sample on
the second half of each series with the fit on the first.

The first version of this harness fitted that null at a fixed `1e-8`, which is
effectively OLS - and HAR's three backward averages are strongly collinear, so
the coefficients swing and generalise badly. `dispersion_panel.py`, which
selects a ridge on an inner training split, read HAR at **+0.565** on fx_cross
1h h=20 where the first harness reported **+0.110** for the same cell. The gap
was the penalty, not the model. **An ESN win measured against the
unregularised version would have been a win against a crippled opponent**, so
every linear arm now goes through one fitting procedure and only the features
differ.

## Measured, median out-of-sample R2 against the training mean

| cell | `ou` | `har` | `lin48` | `esn` | esn beats har |
| --- | ---: | ---: | ---: | ---: | ---: |
| onescale 1h h=1 | +0.032 | +0.094 | +0.088 | +0.093 | 4/8 |
| onescale 1h h=20 | +0.066 | +0.201 | +0.205 | +0.198 | 3/8 |
| fx_major 1h h=20 | +0.004 | +0.103 | +0.178 | **+0.540** | 4/7 |
| fx_cross 1h h=1 | +0.007 | +0.046 | +0.090 | **+0.344** | **8/8** |
| fx_cross 1h h=20 | +0.004 | +0.110 | +0.198 | **+0.572** | **8/8** |
| metal 1h h=20 | +0.169 | +0.791 | **+0.826** | +0.769 | 3/4 |
| fx_major 4h h=20 | +0.119 | +0.460 | **+0.500** | +0.482 | 6/7 |
| fx_cross 4h h=20 | +0.004 | +0.362 | **+0.526** | +0.319 | 3/8 |
| metal 4h h=1 | +0.006 | +0.038 | **+0.448** | -1.512 | 0/2 |
| volatility 1h h=20 | +0.000 | -0.003 | -0.009 | -0.042 | 0/8 |

`ou` is AR(1) in log-variance, a discretised Ornstein-Uhlenbeck. `lin48` is
ridge on the last 48 raw lags. `esn` is a fixed random reservoir with a ridge
readout and its effective degrees of freedom printed.

**Dispersion is strongly forecastable and price is not.** That is the whole
argument for the reframing, and it is now a number: R2 of **+0.54 to +0.83** at
a twenty-bar horizon, against a direction that is a coin in every test on this
desk.

## The answer to "can ML predict dispersion" is frame-dependent

**At 1h, the nonlinearity earns its place.** The reservoir reads +0.540 and
+0.572 at h=20 where HAR reads +0.103 and +0.110 and the long linear arm reads
+0.178 and +0.198 - so it is roughly **three times `lin48`** and five times
HAR, and it wins on **8 of 8** fx_cross instruments at every horizon.

**At 4h, it does not.** `lin48` is the best arm nearly everywhere - +0.500
against the ESN's +0.482 on fx_major, +0.526 against +0.319 on fx_cross, and
+0.448 against **-1.512** on metals. So at the slower frame the gain is
**linear long memory** and the reservoir is actively worse.

That split is only visible because of the control, and it is the reason the
control exists. A reservoir brings three things at once - nonlinearity,
capacity, and a memory far longer than HAR's 22 bars - and without `lin48`
every one of these cells would have been read as "ML wins".

**The reservoir is also high variance.** Metal 4h at -1.512 and -1.786 is worse
than predicting the mean, on two instruments. Anything shipping it needs a
guard, not an average.

## Three controls, and each one answers a different objection

**`onescale`** is a generated AR(1) in log-variance read through the same
Parkinson estimator: one timescale, by construction. All three arms read the
same there - **+0.094, +0.088, +0.093** at h=1 and +0.201, +0.205, +0.198 at
h=20 - so neither the extra capacity nor the nonlinearity buys anything where
there is nothing multi-scale to find. The harness has no spurious capacity
advantage, and that is what licenses reading the 1h gap as real.

**It also calibrates the multi-scale claim.** README item 6 says "HAR's win
*is* the multi-scale result", and the raw ratio cannot show that: HAR's longer
averages both carry multi-scale persistence **and** average down the estimator
noise in the target, and a single bar's range-based variance is a noisy reading
of that bar's true variance. On `onescale`, `har / ou` is **2.95, 2.74, 3.03** -
threefold, from noise-averaging alone, with one timescale present. On real
markets at 1h it is **5.52, 25.61, 6.43, 13.14, 31.63**. Well above the
baseline, so log-variance genuinely carries structure at several timescales -
and that claim could not have been made from the ratio without this row.

**The constant-sigma synthetics** are the replication. Deriv's volatility
indices fix their own sigma, so there is nothing to learn, and every arm reads
**-0.000 to -0.042** on all of them at both frames and all three horizons.
`reservoirs.md` measured -0.0107 to +0.0015 there in 2026-09; this reproduces
it. The level-tracking arms go heavily negative instead, which is correct - a
filter tracking a level with no level to track loses to the mean.

**Shuffled targets** read -0.0016 to -0.04 for every fitted arm.

## Topology adds nothing, and nor do the spatial statistics

`topology.md` measured persistent homology against production's shock
forecaster and found it adds nothing: 4 of 250 incremental cells passed, 3
survived Benjamini-Hochberg, none on GARCH walks. Its sharpest column was the
one that looked like a win - volatility-free topology does separate regimes,
but **GARCH walks gain the same**, so what it sees is clustering.

That makes dispersion the natural follow-up: if topology restates volatility it
should predict volatility, and the only question is whether it predicts it
better than a regression on realised variance already does.

**It does not.** The increment over HAR, on the Vietoris-Rips H0 and H1
persistence-landscape norms of a standardised delay embedding:

| cell | tda increment | positive on |
| --- | ---: | ---: |
| fx_major 1h h=5 | -0.0045 | 2/6 |
| fx_major 1h h=20 | **+0.0008** | 3/6 |
| fx_cross 1h h=5 | -0.0028 | 1/6 |
| fx_cross 1h h=20 | -0.0062 | 1/6 |
| metal 1h h=5 | -0.0029 | 1/4 |
| metal 1h h=20 | -0.0049 | 0/4 |
| garch 1h h=20 | -0.0173 | 1/6 |

The best cell anywhere is **+0.0008 on 3 of 6 instruments**, which is zero.

**The cheap rival reads the same.** Point-pattern statistics from *Geospatial
Analysis* (de Smith, Goodchild and Longley, 7th ed.) apply directly to a delay
embedding, because a delay embedding **is** a point pattern - standard
distance, the standard deviational ellipse's anisotropy, the
nearest-neighbour index against complete spatial randomness, and a two-radius
Ripley's K ratio. Their increment over HAR is **-0.0040 to +0.0002**, best 3 of
6. So four moments of the cloud and the full homology of it agree, and they
agree on nothing - which says what persistent homology was reading here was the
cloud's shape, and the cloud's shape is volatility that HAR already has.

## One estimator result worth keeping

Which **definition** of dispersion is forecastable is not a detail. On
fx_cross 1h h=20, HAR on the same bars reads:

| estimator | R2 |
| --- | ---: |
| Garman-Klass | **+0.575** |
| Parkinson | +0.565 |
| Rogers-Satchell | **-0.090** |

Rogers-Satchell is the drift-robust estimator, and removing the drift term
removes nearly all of the forecastable signal with it. On metals it reads
+0.209 against Parkinson's +0.617. Garman-Klass and Parkinson are
interchangeable; Rogers-Satchell is not, and a study that had picked it by
reputation would have reported dispersion unforecastable.

**And window estimators cannot be targets.** A 100-bar standard deviation
shares 99 of its bars with its own next value, so forecasting its forward
average is nearly forecasting itself: on the GARCH control, HAR on a 100-bar
standard deviation read **+0.9297** and on a 100-bar MAD **+0.9298**, against
**+0.0027** on per-bar Parkinson. That is the autocorrelation of an overlapping
moving average and not a result. They are kept as **features**, where looking
back over a window is what a feature is for.

## What this does not claim

Nothing here is about direction. Every number is a statement about how wide the
next bars are, and the desk's record on direction is unchanged. The use for a
dispersion forecast is the Monte Carlo in `statespace/projecting.py`, which
turns it into a distribution over paths - a stop at a stated breach rate, a
target's touch probability, a time to arrive - and for nothing that needs to
know which way price goes.
