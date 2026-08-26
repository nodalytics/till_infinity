# How good is the volatility estimate

Run: `python research/harness/vol.py`

Every threshold in this project is denominated in volatility units.
`resolve_vol` is 1.5 of them, `MIN_ZONE_VOL` is 0.35, `KEEP_VOL` is 8,
`GRID_ZONE_VOL` is 0.75. If the denominator is wrong the whole scale is wrong -
and it had never been checked.

`Volatility` is an exponentially weighted **mean absolute return**, so its claim
is precise and testable: the next bar's absolute return should be about `bps`,
on average. Walk-forward throughout - the estimate is read *before* the bar it
is judged on.

## It is well calibrated, and mistuned

> **Re-measured on 2026-08-16** on 1.46M forecasts across 14 instruments, up
> from 355k across six. The finding held and one detail flipped.

| interval | forecast | n | ratio | correlation |
|---|---|---|---|---|
| 1m | model | 99,571 | 1.00 | 0.586 |
| 1m | flat 20 | 99,571 | 1.00 | **0.587** |
| 5m | model | 35,002 | 0.96 | 0.480 |
| 5m | flat 20 | 35,002 | 1.00 | **0.525** |
| 15m | model | 474,273 | 0.98 | 0.489 |
| 15m | flat 20 | 474,273 | 1.00 | **0.492** |
| 1h | model | 487,705 | 1.00 | 0.475 |
| 1h | flat 20 | 487,705 | 1.00 | 0.475 |
| 1d | **model** | 363,390 | 0.98 | **0.446** |
| 1d | flat 20 | 363,390 | 1.00 | 0.443 |

**The level is right**: a ratio of 0.96-1.00 means the estimate really is the
size of a typical move, which is what it claims. Both beat naive persistence by
a wide margin - using the last bar's move scores 0.199 to 0.340, and the gap
*widened* on more data.

**A flat twenty-bar mean still matches or beats it at every interval except
one.** The margins narrowed almost to nothing at 1m (0.587 vs 0.586) and 15m
(0.492 vs 0.489), they tie exactly at 1h, and at **1d the model now wins**
(0.446 vs 0.443) where it lost before.

That is a weaker version of the original finding rather than a reversal. An
exponentially weighted estimator that merely *ties* an unweighted window is
still not earning its form - but "beaten everywhere" has become "beaten at 5m,
level elsewhere", and the honest summary is that the two are hard to tell
apart outside 5m, where the flat window is clearly better by 0.045.

## `HALF_LIFE = 60` is well past the optimum

| interval | h=2 | h=5 | **h=7** | **h=10** | h=20 | h=60 |
|---|---|---|---|---|---|---|
| 5m | 0.487 | 0.525 | **0.529** | 0.528 | 0.517 | 0.481 |
| 1h | 0.378 | 0.406 | 0.412 | **0.415** | 0.411 | 0.381 |
| 1d | 0.516 | 0.546 | **0.548** | 0.547 | 0.538 | 0.513 |

A genuine interior optimum at **7 to 10 bars**, the same at every interval,
worth +0.034 to +0.047 of correlation over the current 60. Calibration improves
too: the ratio goes from 0.96-0.99 to 1.00.

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

**Measured on the 2026-08-15 dataset and not re-run**, unlike the rest of this
document - the counts below are from six instruments over days. They are kept
because the conclusion drawn from them is "counts cannot answer this", which
does not depend on the counts.

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
each half-life - every call paired with the outcome of the touch it opened,
scored on the things a gate consumes.

| half_life | calls | direction | holds | push | separation |
|---|---|---|---|---|---|
| **60** *(current)* | 10,509 | 68.8% | 73.1% | 0.50 | **16.5pp** |
| 20 | 10,708 | 69.5% | 73.3% | 0.51 | 13.7pp |
| 10 | 11,052 | **69.6%** | 73.5% | 0.51 | 14.5pp |
| 7 | 11,012 | **69.6%** | 73.5% | **0.52** | 16.2pp |

**The forecasting optimum still does not carry over, and on more data the
picture is cleaner rather than different.** The first reading found h=7 and
h=10 *worse* than 60 on direction, in a non-monotone ordering that looked like
noise. It was noise: on 10,509 calls the four are within **0.8 points** of each
other, with h=7 and h=10 now fractionally ahead rather than behind.

The spread across all four was 3.1 points on 1,900 calls; it is 0.8 points on
10,500. An effect that shrinks by four as the sample grows by five is an effect
that was never there.

`separation` - what a gate actually consumes - still favours the current 60
(16.5pp against 13.7 to 16.2), which is the one column that has not flattened.

So **no half-life is measurably better for calls**, more firmly than before,
and the honest reading is that the volatility estimate is not the bottleneck.
`holds` - the trivial rule from [features.md](features.md) - beats the model at
every half-life, by 3.8 to 4.3 points, which is the same result that section
reached and is untouched by any of this.

### Why this was worth running anyway

It is the loop the previous section deliberately left open, and it closed the
other way. Had `HALF_LIFE` been changed to 10 on the forecast evidence - which
was strong, consistent across five intervals, and improved calibration as well
- the result would have been a better forecast and slightly worse calls, with
nothing in the system to say so.

**Optimising a component against its own metric is not optimising the system.**
That is the general lesson, and it applies directly to the adaptive scheme in
[todo.md](../docs/todo.md) 6b: an expert aggregation over half-lives would
weight them by *forecast* loss, which this measurement says is the wrong
objective. Whatever adapts has to be scored on outcomes, not on the quantity it
happens to predict.

## What to do

1. **Leave `HALF_LIFE` at 60.** Not because it is right - the forecast says it
   is not - but because nothing that depends on it gets better when it changes,
   and a change with no measured benefit is churn. Re-measured on five times
   the calls, the four half-lives are within 0.8 points on direction and 60
   still leads on separation. This is now a well-tested "leave it alone".
2. **Score the adaptive scheme on outcomes, not forecast loss.** See above; this
   is the correction to todo.md 6b that this measurement produced.
3. **Revisit if the bottleneck moves.** The estimate being adequate is a
   statement about the current model, which loses to "assume the level holds".
   If that gap ever closes, the denominator may start to matter.
