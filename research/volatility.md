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

## What to do

1. **Do not change `HALF_LIFE` on this evidence alone.** The forecast improves
   and the downstream effect is unmeasured in the only terms that matter. Run
   the edge machinery at h=10 against h=60 first.
2. **Then consider not choosing at all** — see todo.md on self-adjustment. A
   constant that is measurably wrong five years after being set is an argument
   about the *form*, not about the number.
