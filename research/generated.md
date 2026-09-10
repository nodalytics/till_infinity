# The generated series are independently generated, and the changepoint detector does not find their origins

Two questions about Deriv's synthetics, both answered on 2026-09-10, both
answered *no*. They are on one page because they were run on the same data and
because the second is only trustworthy because of how the first was controlled.

The book is 72% generated instruments, so what they are and are not is not a
curiosity - it is most of what the desk trades.

## One: nothing shares a driver with anything

`Volatility 75` and `Volatility 75 (1s)` carry the same headline parameter and
differ in tick rate. `Boom 500` spikes up where `Crash 500` spikes down. If
either pair were one process quoted twice, that would be close to arbitrage;
if either merely shared a driver, a lead between them would be worth finding.

**26 series, 325 pairs, 86,385 one-minute bars each over 60 days**
(`research/harness/twins.py`), every pair measured at seven lags:

| kind | pairs | mean \|corr\| | max | worst offender |
| --- | --- | --- | --- | --- |
| mirror | 3 | 0.0067 | 0.0089 | boom_500 / crash_500 = -0.0089 |
| twin | 5 | 0.0062 | 0.0085 | volatility_100_1s / volatility_100 |
| sibling | 48 | 0.0058 | 0.0096 | |
| mirror-ish | 6 | 0.0061 | 0.0086 | |
| sibling-1s | 30 | 0.0059 | 0.0109 | |
| **stranger** | 233 | 0.0059 | **0.0129** | boom_500 / volatility_10_1s |

Nothing exceeds five standard deviations of the stranger distribution (mean
0.0027, sd 0.0021). Every category sits on the noise floor.

**The control earned its place, and this is the part worth keeping.** The single
largest correlation in the whole study - 0.0129 - is on a *stranger* pair, two
instruments with no relationship at all. Had the twins been tested alone, 0.0085
between V100 and V100(1s) was there to be written up as a faint shared driver.
It is smaller than what unrelated instruments produce.

So: independently generated. The mirror hypothesis, which would have been worth
the most, is dead. That is worth having - it closes a line of speculation rather
than leaving it open.

## Two: FOCuS detections and origins are independent events

`focus.THRESHOLD` is 12.0 nats and `_note_change` *adds* to it on faster rungs,
so only the slowest rung in the ladder keeps 12. The TradingView indicator
rendering the same idea defaults to 1.0. Both cannot be right, and the standing
suspicion was that 12 was hiding higher-timeframe origins.

Bars replayed through `Focus` at five thresholds, matched against the origins
the engine actually recorded, within one bar
(`research/harness/htforigins.py`), on 15 series at 1h:

| nats | fires | origins | matched | hit% | fires/origin | chance | lift |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1.0 | 7,986 | 309 | 212 | 68.6% | 25.84 | 75.0% | **0.92** |
| 3.0 | 2,934 | 309 | 95 | 30.7% | 9.50 | 35.5% | **0.87** |
| 6.0 | 941 | 309 | 33 | 10.7% | 3.05 | 12.5% | **0.85** |
| 12.0 | 150 | 309 | 6 | 1.9% | 0.49 | 2.1% | **0.94** |
| 20.0 | 26 | 309 | 1 | 0.3% | 0.08 | 0.4% | **0.90** |

At the production threshold FOCuS matches **1.9%** of 1h origins, so the
suspicion that 12 nats finds almost nothing is correct. What is not correct is
the inference from it.

`chance` is what a detector firing at the same rate but knowing nothing would
score - a fire lands on a given bar with probability `fires/bars`, and the match
window is the bar either side. **Lift is below 1.0 at every threshold.** A blind
detector firing as often would do slightly better.

So lowering the threshold does not capture origins. At 1 nat it fires on 37% of
all bars - **25.84 times per origin** - and hits 68.6% of them, where firing
blindly at that rate gives 75%. The hit rate is the firing rate and nothing
else.

Reading `hit%` alone, 1.9% climbing to 68.6% looks like a transformation. It is
the same detector making more noise.

## What limits the second result

**Synthetics only, and one rung.** `research.db` was filled from the broker's
generated list, so the FX, crypto and index feeds that carry most origins had no
bars in it - and **2h and 4h had none at all**, which is where the
higher-timeframe question actually lives. 15 series at 1h is what this rests on.

**Synthetics may not be representative**, and result one is the reason to think
so: these are independently generated processes with no shared structure. A
changepoint detector may behave quite differently on a market with genuine
regime shifts. The honest scope is *no signal on generated series at 1h*, not
*no signal*.

Extending it needs the non-generated book in `research.db`, which
`research/harness/mt5fill.py --real` collects.

## What both runs relied on

Neither would be trustworthy without a null to read against, and in both cases
the null was computed from the same data rather than assumed:

* the **stranger** pairs, for correlation
* the **chance** column, for detection

Both were written into the harness before the numbers were seen. On this project
that is not caution, it is the minimum: `research/forecasting.md` records two
clean tables that were defects, and the first version of `aligning.md` was
Simpson's paradox.
