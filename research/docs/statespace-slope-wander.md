# How fast a slope actually wanders, and the constant that says 0.02

Three modules point at one unmeasured number.

`rates.py`:

> `Kalman.var_slope` says *how fast the true slope is believed to wander*,
> which is a property of the world and is currently set by
> `DRIFT_VOL_PER_HOUR = 0.02`, a number chosen rather than measured.

`levels.py` carries it as "process noise per hour, in volatility units... what
stops a filter with many observations from freezing solid". `linear.py` calls it
"the parameter nobody has measured - chosen per hour and applied at every
timeframe and has never been fitted."

The harness is `research/ideas/slope_wander.py`.

## The identity does the work, and the subtraction is the point

`linear.py` states it: for two readings separated by `dt`,
`var(second - first) = q * dt + 2R`. With the slope *estimated* in consecutive
non-overlapping windows, `R` is not a guess either - it is `Slope.variance`,
which `rates.py` returns for exactly this comparison. So

    q = (var(slope change) - 2 * mean estimator variance) / dt

A slope series wanders partly because the world moved and partly because the
estimator is noisy, and a measurement that skips the second term attributes all
of it to the first.

## The first version had no null and was therefore unreadable

The cross-frame test looked decisive. A rate **per hour** applied at 3m through
1d predicts the fitted value is the same at every frame, and it was not - 3m
read **10,050 times** the 1h value.

**That is not evidence about markets.** A walk has no slope. Its apparent slope
over an `n`-bar window of `h`-hour bars is a window artefact of size
`sqrt(n)/(n*h)`, so the apparent wander scales as `q ~ 1/(n*h^3)` and predicts a
3m-to-1h ratio of `1/0.05^3 = 8000` against the 10,050 observed. **A walk fails
the cross-frame test in the same direction and by roughly the same amount.**

So the readable question is not whether `q` is constant across frames. It is
whether the market's `q` exceeds **a walk's at the same frame**, run through the
identical pipeline with each series' own per-bar scale.

## The answer is that there is no slope to track

| frame | median `q` | median walk | **ratio** | above walk | vs 0.02 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 3m | 30.34083 | 35.20944 | **0.86** | 0/10 | 1517.0 |
| 15m | 0.20668 | 0.25299 | **0.82** | 0/10 | 10.3 |
| 1h | 0.00302 | 0.00337 | **0.90** | 3/10 | 0.2 |
| 4h | 0.00002 | 0.00003 | 0.98 | 5/10 | 0.0 |
| 1d | 0.00000 | 0.00000 | 0.96 | 7/10 | 0.0 |

**A market's slope wanders no more than a walk's at any frame.** The ratio runs
0.82 to 0.98 and not one of ten instruments exceeds the walk at 3m or 15m. The
apparent wander is the window artefact in full, and the market produces slightly
*less* of it than a walk does.

That is consistent with the rest of this line of work rather than new: direction
is closed, and the walk is the best-calibrated band there is.

## What it says about the constant

`DRIFT_VOL_PER_HOUR = 0.02` is **1517 times** the measured value at 3m, **0.2
times** it at 1h, and four orders of magnitude above it at 1d. So one per-hour
constant is right at no more than one frame, which confirms `I6`'s concern -
but **not** for the reason `I6` would suggest. The quantity it is meant to
represent is a window artefact, so there is no frame at which it is measuring a
real slope wander.

Its actual job is the one `levels.py` states: stopping a filter with many
observations from freezing solid. That is a floor on uncertainty, not an
estimate of the world, and it should be documented as a floor rather than as a
drift volatility - a floor has no cross-frame prediction to fail.

## What to use

* **Do not fit `q` for a slope and expect a number.** Run the walk through the
  same pipeline first; its apparent slope wander is most of what any fit will
  find.
* **Subtract the estimator's own variance.** `rates.Slope.variance` is there for
  it, and skipping it inflates `q`.
* **Read `DRIFT_VOL_PER_HOUR` as a floor on uncertainty**, which is what it
  does, and not as a measured drift volatility, which is what its name implies.

## Related

* [Directional recurrence](statespace-directional-recurrence.md) - the other
  random-walk property tested here, where the market *does* differ
* [Clock levers](statespace-clock-levers.md) - the process-noise sweeps this
  reuses the discipline of
