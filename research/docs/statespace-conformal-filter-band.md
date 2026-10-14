# Step three is not needed: the band is calibrated where it is read

`statespace-estimator-on-touches.md` measured `levels.Kalman` at **18 times**
the sharpness of anything statespace has on touch-spaced observations and at a
**PIT flatness of 89**, and concluded that the incumbent should be kept and its
uncertainty fixed. It promoted the band from step three of the migration to
step one.

That recommendation was wrong, and this is the measurement that says so.

## Production already owns the machinery, and it is not the problem

`vol/envelope.py` runs AgACI over the volatility envelope at **89.1-89.6%**
coverage against one-step ACI's 87.8-88.1% while **2-9% narrower**, and
`structures/conformal.py` is that machinery pointed at the **zone** - its own
docstring says *"the same machinery pointed at a different interval"*. Nothing
points it at the filter's own predictive band: `levels.py` reads
`filter.sigma_at(when)` at 1088 and 1246 and publishes `filter.sigma` raw at
1320.

So the obvious third pointing was tested, with `conformal.Pool` fed the
filter's standardised residuals and `reach()` setting the band.

| group | arm | coverage | vs nominal | width, sigmas | misses above |
| --- | --- | ---: | ---: | ---: | ---: |
| **traded**, 150 levels | gaussian | **95.7%** | +0.7% | **3.920** | 50.0% |
| | conformal | 96.8% | +1.8% | 4.085 | 50.0% |
| | empirical | 94.4% | -0.6% | 3.756 | 50.0% |
| **generated**, 49 levels | gaussian | **95.5%** | +0.5% | **3.920** | 50.0% |
| | conformal | 97.5% | +2.5% | 4.155 | 50.0% |
| | empirical | 94.7% | -0.3% | 4.025 | 50.0% |

**The Gaussian band already holds its nominal coverage** - 95.7% against 95.0% -
and conformalising it makes it **worse**: it over-covers by 1.8 points and is
4% wider. `misses above` is exactly 50.0% for every arm, so the band is in the
right place as well as of the right size.

A calibrator cannot improve an interval that is already at nominal. Pointed at
the envelope it was worth 1.3 points of coverage and 2-9% of width; pointed
here it costs 1.8 points of over-coverage and 4% of width, because there was
nothing left to correct.

## And the PIT of 89 is the observation process, not the band

Both figures are right, and they answer different questions: coverage is **one
point** on the predictive curve and the PIT is the **whole curve**. Ten bins of
the Gaussian arm's PIT, where a calibrated band puts 10% in each:

| bin | share | vs 10% |
| --- | ---: | ---: |
| 0.0-0.1 | 13.8% | +3.8% |
| 0.1-0.2 | 1.2% | -8.8% |
| 0.2-0.3 | 0.8% | -9.2% |
| 0.3-0.4 | 0.9% | -9.1% |
| **0.4-0.5** | **32.0%** | **+22.0%** |
| **0.5-0.6** | **33.3%** | **+23.3%** |
| 0.6-0.7 | 1.0% | -9.0% |
| 0.7-0.8 | 0.7% | -9.3% |
| 0.8-0.9 | 1.0% | -9.0% |
| 0.9-1.0 | 15.2% | +5.2% |

**Sixty-five per cent of the mass is in the two central bins**, with the four
bins either side holding under 1.2% each.

A PIT of 0.5 is a residual of zero - the filter's mean *is* the observation -
and that is what touch clustering produces. Consecutive bars both contain the
level, so the filter updates at a price and the next touch arrives at almost the
same one. A third of the observations are near-duplicates of the update that
preceded them.

**So the flatness of 89 is measuring the burstiness of the observation process,
not the size of the band.** The two tail bins hold 29% against the 20% a
calibrated band would put there, which is the only genuine over-confidence in
the figure and is modest - and it is the part the 95.7% coverage number already
summarises.

## Which corrects the previous study as well

`statespace-estimator-on-touches.md` reported `Pooled(adapt=True)` as **13 times
better calibrated** than the Kalman - PIT 6.66 against 89.15 - and offered that
as the half of its result that was actionable. On this evidence that reading is
wrong: the pool scores better on a statistic dominated by duplicate
observations, and it does so by being **wider**, which smooths the central
spike away rather than describing it better.

The sound half of that study stands unchanged, and it is the one that used
CRPS: **the Kalman is 18 times sharper and should be kept.** CRPS penalises
width and miscalibration together, which is why it survived a diagnostic that
PIT did not.

## What this does to the migration

**Step three is closed, not merely deferred.** There is no calibration defect in
the filter's band at the level any consumer reads it, so there is nothing for
the conformal machinery to fix and wiring it would make the published band
wider and over-covered.

The remaining steps are unaffected and move up by one:

* **activity on `Q`** at `levels.py:1244`, measured at +0.0513 per observation
  on 7 of 8 instruments at exponent 1;
* **`bounding`** against `learning/touches.py` and `learning/breaking.py`;
* the **retirements** that need no replacement - `learning/baseline.py` first;
* and **anchored level discovery**, still the only item blocked on design.

## The general lesson, which has now cost two recommendations

PIT flatness and interval coverage are not the same claim, and a bursty
observation process separates them completely. A flatness of 89 read as "the
band is wrong" produced a recommendation to re-calibrate a band that was
already at nominal; the histogram took one run to produce and would have
prevented it.

`statespace-conformal-band.md` already recorded half of this - that a conformal
PIT is near-tautological and **CRPS is the evidence**. The other half is now
measured: a PIT can also be *badly wrong for a reason that has nothing to do
with the forecast*, and the fix is to look at which bins carry it before
believing the number.
