# How good is the volatility estimate

Run: `python research/harness/vol.py`

Every threshold in this project is denominated in volatility units.
`resolve_vol` is 1.5 of them, `MIN_ZONE_VOL` is 0.35, `KEEP_VOL` is 8,
`GRID_ZONE_VOL` is 0.75. If the denominator is wrong the whole scale is wrong —
and it had never been checked.

`Volatility` is an exponentially weighted **mean absolute return**, so its claim
is precise and testable: the next bar's absolute return should be about `bps`,
on average. Walk-forward throughout — the estimate is read *before* the bar it
is judged on.

## It is well calibrated, and mistuned

| interval | forecast | n | ratio | correlation |
|---|---|---|---|---|
| 1m | model | 96,345 | 1.00 | 0.587 |
| 1m | flat 20 | 96,345 | 1.00 | **0.588** |
| 5m | model | 34,354 | 0.96 | 0.481 |
| 5m | flat 20 | 34,354 | 1.00 | **0.527** |
| 15m | model | 18,954 | 0.95 | 0.474 |
| 15m | flat 20 | 18,954 | 0.99 | **0.481** |
| 1h | model | 50,647 | 0.98 | 0.381 |
| 1h | flat 20 | 50,647 | 1.00 | **0.397** |
| 1d | model | 155,506 | 0.99 | 0.513 |
| 1d | flat 20 | 155,506 | 1.00 | **0.534** |

**The level is right**: a ratio of 0.95–1.00 means the estimate really is the
size of a typical move, which is what it claims. Both beat naive persistence —
using the last bar's move scores 0.27–0.35.

**But a flat twenty-bar mean beats it at every interval.** An exponentially
weighted estimator that cannot beat an unweighted window is not earning its
form, and the reason is the half-life.

## `HALF_LIFE = 60` is well past the optimum

| interval | h=2 | h=5 | **h=7** | **h=10** | h=20 | h=60 |
|---|---|---|---|---|---|---|
| 5m | 0.487 | 0.525 | **0.529** | 0.528 | 0.517 | 0.481 |
| 1h | 0.378 | 0.406 | 0.412 | **0.415** | 0.411 | 0.381 |
| 1d | 0.516 | 0.546 | **0.548** | 0.547 | 0.538 | 0.513 |

A genuine interior optimum at **7 to 10 bars**, the same at every interval,
worth +0.034 to +0.047 of correlation over the current 60. Calibration improves
too: the ratio goes from 0.96–0.99 to 1.00.

The first sweep stopped at h=10 and reported it as best, which was the edge of
the grid rather than a maximum. Extending below it found the turn.

### What it costs

| half_life | correlation (5m) | bar-to-bar movement in the estimate |
|---|---|---|
| 60 | 0.481 | 0.9% |
| 10 | 0.528 | 5.6% |
| 7 | 0.529 | 8.0% |
| 2 | 0.487 | 31.2% |

A shorter half-life tracks change better and jerks around more, and everything
in volatility units rides on it. **h=10 is the defensible choice**: peak or
within 0.001 of peak everywhere, ratio 1.00, and a fifth of the jumpiness of
h=7 for the same accuracy.

## What it does downstream, which is the part that matters

Correlation is the metric that improved. Levels and touches are what the
estimate is *for*, so the replay was run at each half-life:

| half_life | touches | levels | reject | chop | break | trap |
|---|---|---|---|---|---|---|
| 60 | 1,912 | 204 | 876 | 533 | 242 | 179 |
| 20 | 1,914 | 190 | 866 | 553 | 244 | 180 |
| 10 | 1,976 | 184 | 858 | 576 | 250 | 190 |
| 7 | 1,959 | 175 | 838 | 598 | 243 | 190 |

Modest: 3% more touches, 14% fewer levels, and a shift from reject toward chop.
Instant resolutions stay at zero throughout, so nothing regressed.

**Whether that is better is not answerable from counts**, and this document
does not claim it is. Fewer levels could be tighter clustering or lost
structure; more chop could be honesty about nothing happening or touches
failing to resolve. The measurement that would settle it is direction and
realised push per call, as in [edge.md](../docs/edge.md).

An earlier version of this table showed *identical* numbers at every half-life,
because `half_life` is a dataclass field default captured at class definition
and setting the module global afterwards does nothing. It is set through
`Book(half_life=…)` now, with an assertion that it took.

## The calls do not improve, and that is the answer

Run: `python research/harness/halflife.py`

The forecast is not what the estimate is for, so the edge machinery was run at
each half-life — every call paired with the outcome of the touch it opened,
scored on the things a gate consumes.

| half_life | calls | direction | holds | push | separation |
|---|---|---|---|---|---|
| **60** *(current)* | 1,899 | 69.2% | 76.3% | 0.58 | 27.1pp |
| 20 | 1,900 | **70.2%** | 74.8% | **0.69** | 28.7pp |
| 10 | 1,966 | 68.5% | 74.9% | 0.59 | 27.2pp |
| 7 | 1,945 | 67.1% | 74.2% | 0.65 | **29.7pp** |

**The forecasting optimum does not carry over.** h=7 and h=10 won the forecast
clearly and monotonically; on direction they are *worse* than the current 60,
and the ordering across the four is not monotone at all — which is what noise
looks like rather than signal.

The spread across all four is **3.1 points on about 1,900 calls, against a
standard error of 1.1**. The confidence intervals overlap heavily:

    h=20   68.1% to 72.3%
    h=60   67.1% to 71.3%
    h=7    65.0% to 69.2%

So **no half-life is measurably better for calls**, and the honest reading is
that the volatility estimate is not the bottleneck. `holds` — the trivial rule
from [features.md](features.md) — beats the model at every half-life, by 4 to 7
points, which is the same result that section reached and is untouched by any
of this.

### Why this was worth running anyway

It is the loop the previous section deliberately left open, and it closed the
other way. Had `HALF_LIFE` been changed to 10 on the forecast evidence — which
was strong, consistent across five intervals, and improved calibration as well
— the result would have been a better forecast and slightly worse calls, with
nothing in the system to say so.

**Optimising a component against its own metric is not optimising the system.**
That is the general lesson, and it applies directly to the adaptive scheme in
[todo.md](../docs/todo.md) 6b: an expert aggregation over half-lives would
weight them by *forecast* loss, which this measurement says is the wrong
objective. Whatever adapts has to be scored on outcomes, not on the quantity it
happens to predict.

## What to do

1. **Leave `HALF_LIFE` at 60.** Not because it is right — the forecast says it
   is not — but because nothing that depends on it gets better when it changes,
   and a change with no measured benefit is churn.
2. **Score the adaptive scheme on outcomes, not forecast loss.** See above; this
   is the correction to todo.md 6b that this measurement produced.
3. **Revisit if the bottleneck moves.** The estimate being adequate is a
   statement about the current model, which loses to "assume the level holds".
   If that gap ever closes, the denominator may start to matter.
