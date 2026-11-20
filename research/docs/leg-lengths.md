# How far a leg stretches before it comes back, across five timeframes

**Measured 2026-11-20.** Four index CFDs, M5 to D1, 2.5 years of M15 and 10
months of M5. Harness: [`leg_lengths.py`](../ideas/leg_lengths.py). The
question was whether leg lengths are **fractal** - the same distribution at
every scale - and whether an unusually long leg is a tradeable bet on the
return.

| question | answer |
|---|---|
| are leg lengths self-similar across timeframes? | **yes, and exactly** - median stretch is **2.73 to 3.33 ATR** on five frames spanning 288x in clock time, and the tail exponent is **0.68 to 0.71** on all five |
| is that self-similarity a property of the market? | **no.** The day-shuffled twin reproduces every quantile to two decimals, including the tail exponent and the 0.90-0.93 return rate |
| does price come back? | **90 to 93% of the time** within 500 bars - and the shuffle says the same |
| can I bet on the return after an impulse? | **no.** 12 of 12 cells net-negative; at 3 hours and a 1 ATR stop the return arrives **23.4%** of the time against a fair **32.7%** |

## The definitions

A **turn** is a bar whose extreme is the most extreme of the 5 bars before and
the 3 bars after it. **The walk starts 4 bars after the pivot**, not at the
pivot, because a 3-right pivot is not knowable until its third right-hand bar
closes - a detector that measures from the pivot itself reads three bars of the
future on every row.

The **stretch** is how far price travelled away from the turn, in ATR of the
turn's own bar, before it came back to the turn's price. Normalising by the
turn's own ATR is what makes the comparison across frames meaningful at all:
an M5 leg and a D1 leg are both counted in units of their own bar's range.

The **shuffled** arm resamples whole days. That keeps each day's internal bar
shapes and its intraday volatility pattern and destroys the order of days.
`rehung-bar-shapes-break-bar-derived-nulls` is why the shuffle is by day rather
than by bar: re-hanging individual bars invalidates exactly the geometry a
stretch measures.

## The ladder

Median stretch, tail exponent and return rate, real against shuffled:

| frame | n | **p50 stretch** | p75 | p90 | p99 | **tail** | **returned** |
|---|---:|---:|---:|---:|---:|---:|---:|
| M5 | 35,518 | **2.78** | 6.10 | 15.01 | 48.70 | 0.71 | 0.926 |
| *M5 shuffled* | 35,487 | *2.78* | *6.12* | *15.09* | *48.26* | *0.71* | *0.921* |
| M15 | 35,720 | **2.73** | 6.16 | 15.27 | 45.86 | 0.71 | 0.928 |
| *M15 shuffled* | 35,755 | *2.71* | *6.17* | *15.33* | *50.96* | *0.70* | *0.928* |
| H1 | 10,011 | **3.02** | 6.83 | 15.86 | 44.18 | 0.68 | 0.921 |
| *H1 shuffled* | 10,078 | *2.93* | *6.77* | *16.83* | *49.56* | *0.68* | *0.916* |
| H4 | 2,950 | **2.98** | 6.22 | 17.32 | 38.28 | 0.71 | 0.915 |
| *H4 shuffled* | 2,858 | *3.10* | *6.49* | *17.46* | *46.87* | *0.68* | *0.925* |
| D1 | 505 | **3.33** | 6.67 | 14.88 | 52.35 | 0.69 | 0.903 |
| *D1 shuffled* | 550 | *3.03* | *6.51* | *11.48* | *31.41* | *0.73* | *0.911* |

**The self-similarity is genuine and it is strong.** Five minutes to one day is
a factor of 288 in clock time, and the median stretch moves from 2.73 to 3.33
ATR - about 20% - while p75 sits at 6.1 to 6.8 on every frame and the Hill tail
exponent sits in 0.68 to 0.71 on every frame. If you were handed the stretch
distribution with the frame label removed you could not recover the frame.

**And so does the shuffle.** Every line's italic twin matches it: 2.78 against
2.78, 2.71 against 2.73, 0.71 against 0.71, 0.928 against 0.928. The only
column where real and shuffled separate is D1, where `n` is 505 and the
separation goes the *other* way at H1 and H4 (shuffled mean 6.64 against real
6.33, 6.37 against 6.08) - that is sampling noise, not structure.

**The honest reading is that the fractal is in the detector.** A 5/3 pivot
rule, ATR normalisation and a 500-bar patience limit applied to anything with
this bar geometry produce these quantiles. That is the same finding as
[`fractal-twins.md`](fractal-twins.md) and
[`excursion-scaling.md`](excursion-scaling.md) reached by other routes, and
`let-shuffled-twin-name-the-mechanical-observables` is the standing rule it
illustrates: overshoot past an extreme is **definitional**, so its distribution
is not evidence of anything.

## Time to return, which is the part that kills the trade

| frame | p10 | p25 | **p50** | p75 | p90 | p99 | mean |
|---|---:|---:|---:|---:|---:|---:|---:|
| M15 bars | 4 | 6 | **12** | 35 | 99.6 | 399 | 39.9 |
| M15 hours | 1.0 | 1.5 | **3.0** | 8.75 | 24.9 | 99.75 | 9.98 |
| *M15 shuffled, bars* | *4* | *6* | ***12*** | *36* | *102* | *386* | *39.9* |
| H1 bars | 4 | 6 | **12** | 34 | 110 | 407 | 40.6 |
| H4 bars | 4 | 6 | **11** | 31 | 92 | 375 | 36.1 |
| D1 bars | 4 | 6 | **12** | 32 | 94 | 290 | 32.9 |

**Twelve bars is the median on every frame**, which is the strongest statement
of self-similarity on this page and, again, matched bar-for-bar by the shuffle.

The 90-93% return rate is measured with **no stop and 500 bars of patience**.
At M15 that is **125 hours**. p90 of time-to-return is **24.9 hours**; p99 is
**99.75 hours**. So "price comes back 93% of the time" and "price comes back
within three hours" are different claims by a factor of forty in patience.

## Betting the return: 12 of 12 cells lose

Enter when the stretch clears **2 ATR**, target the turn's own price, stop *n*
ATR beyond the entry, 0.02R charged (US Tech 100's measured round trip, from
[`index-pullback.md`](index-pullback.md)). `fair` is `1/(1+RR)` computed from
the geometry **each trade actually had**, so it is the break-even rate for a
driftless process facing that same target and stop:

| clock | stop | n | **hit** | **fair** | hit - fair | R:R | **net R** |
|---|---|---:|---:|---:|---:|---:|---:|
| 1h | 0.5 | 17,168 | 0.098 | 0.201 | -0.103 | 4.88 | -0.0449 |
| 1h | 1.0 | 17,168 | 0.145 | 0.327 | -0.182 | 2.44 | -0.0395 |
| 1h | 2.0 | 17,168 | 0.182 | 0.483 | -0.301 | 1.22 | -0.0198 |
| **3h** | 0.5 | 17,168 | 0.151 | 0.201 | -0.050 | 4.88 | -0.0435 |
| **3h** | **1.0** | 17,168 | **0.234** | **0.327** | **-0.093** | 2.44 | **-0.0535** |
| **3h** | 2.0 | 17,168 | 0.318 | 0.483 | -0.165 | 1.22 | -0.0292 |
| 8h | 0.5 | 17,168 | 0.180 | 0.201 | -0.021 | 4.88 | -0.0256 |
| 8h | 1.0 | 17,168 | 0.291 | 0.327 | -0.036 | 2.44 | -0.0428 |
| 8h | 2.0 | 17,168 | 0.423 | 0.483 | -0.060 | 1.22 | -0.0234 |
| 24h | 0.5 | 17,168 | 0.189 | 0.201 | -0.013 | 4.88 | -0.0202 |
| 24h | 1.0 | 17,168 | 0.312 | 0.327 | -0.015 | 2.44 | -0.0362 |
| **24h** | **2.0** | 17,168 | **0.474** | **0.483** | **-0.009** | 1.22 | -0.0210 |

**At three hours and a 1 ATR stop the return arrives 23.4% of the time.** The
90%+ figure from the ladder has become 23% because the ladder gave the walk 500
bars and no stop, and this gives it 12 bars and a stop. Three hours at M15 is
*exactly* p50 of time-to-return, so a 3-hour clock is the point where the bet
is a coin flip, not the point where it is near-certain.

**`hit - fair` goes to zero as you extend the clock and widen the stop, and
never goes above it.** 24h and 2 ATR reads 0.474 against a fair 0.483. That is
the signature of a driftless process: with enough patience and a stop far
enough away, you collect exactly the geometric rate and not one basis point
more. The impulse buys the **distance** to the target; it does not buy the
**probability** of reaching it.

**Every cell is net-negative at 0.02R**, which is the *cheapest* feed in the
index book. At Germany 40's 0.1087R, or an FX cross's 0.2R, these are not close.

## Why this was already the answer

`fade-to-value` died of exactly this, and it is on record twice:
`a-return-rate-is-geometry` ("the origin's 82% is matched by a distance-matched
placebo on every class; a walk reads 0.825") and
`fade-to-value-loses-on-the-entry-not-the-target` ("62% stop out in 7 minutes
at -10.81; targets pay +28.16"). This page is the same mechanism measured on a
different instrument class with the stop made explicit as a swept parameter
rather than a fixed one. The stretch distribution above - p75 at 6 ATR, p90 at
15 - is *why* 89-91% of those fades were stopped before the target arrived.

`the-origin-picks-a-distance-not-a-probability` is the one-line form, and this
is its quantitative confirmation: the impulse is information about **where**,
never about **whether**.

## What a leg is good for, then

Nothing on this page refutes the leg as a **target-placement** device, which is
what the desk actually uses it for and what the 82% target-hit rate was always
measuring. What is closed is:

- the leg length as a **signal** (shuffle-identical at five scales)
- the long leg as a **reversal bet** (12 of 12 cells negative)
- cross-timeframe fractality as **evidence of structure** (it is a detector
  property)

The open thread from this work is the opposite trade - following the stretch
rather than fading it - which the penetration ladder in
[`turn-points.md`](turn-points.md) touches and which has not been costed in R.
