# The 82% return rate holds on every asset class, and it is geometry

**Measured 2026-10-15.** Code: [`origin_returns.py`](../ideas/origin_returns.py).
557 instruments, eight traded classes, eleven generated families, three frames.

`fade-to-value` records **82%** of displacement origins being returned to, and
the desk already treats that as a target hit rate rather than an entry signal.
Asked: does it hold across families and asset classes?

**Yes, and it means nothing.** The rate is extraordinarily stable - a median of
**0.797** at a hundred bars across 35 class-frames, from 0.711 to 0.827 - and a
distance-matched price that is **not** an origin returns at the same rate, with
a median difference of **+0.001** and a range of −0.008 to +0.013. A driftless
walk returns slightly *more* often, median −0.033.

## The origin, by the desk's own definition

Not a new one. From `drawing/displacement.py` and `drawing/origins.py`: a push
of `PUSH_N = 2` bars whose bodies are each at least `PUSH_BODY = 0.65` of their
range and all the same direction; the leg spanning at least `MIN_LEG_VOL = 1.5`
volatility units; the origin bar before it having a body between **0.10 and
0.60** of its range; and the zone being `zone_of` - the bar's range, or its body
when the range reaches `WIDE_BAR = 2.0` units.

## The result

Return rate at a hundred bars, with a distance-matched placebo band of the same
width on the same bars, and a matched driftless walk.

| frame | class | origins | real | placebo | walk | vs placebo |
|---|---|---:|---:|---:|---:|---:|
| 1h | fx majors | 2,800 | 0.783 | 0.783 | 0.824 | **+0.000** |
| 1h | fx crosses | 6,073 | 0.782 | 0.779 | 0.818 | +0.003 |
| 1h | metals | 1,466 | 0.767 | 0.763 | 0.816 | +0.004 |
| 1h | indices | 2,472 | 0.787 | 0.785 | 0.817 | +0.002 |
| 1h | equities | 624 | 0.774 | 0.777 | 0.796 | −0.003 |
| 1h | energy | 660 | 0.783 | 0.777 | 0.806 | +0.006 |
| 1h | baskets | 1,116 | 0.804 | 0.800 | 0.808 | +0.004 |
| 1h | softs | 476 | 0.790 | 0.790 | 0.800 | +0.000 |
| 4h | fx majors | 2,601 | 0.766 | 0.769 | 0.820 | −0.003 |
| 1d | fx majors | 851 | 0.786 | 0.783 | 0.822 | +0.003 |
| 1h | volatility | 6,152 | 0.797 | 0.793 | 0.838 | +0.004 |
| 1h | boom | 2,452 | 0.821 | 0.819 | 0.807 | +0.002 |
| 1h | jump | 2,000 | 0.797 | 0.797 | 0.818 | +0.000 |
| 1h | range break | 800 | 0.759 | 0.757 | 0.799 | +0.002 |

Across all 35 class-frames with 300 or more origins:

| | min | median | max |
|---|---:|---:|---:|
| return rate at h=100 | 0.711 | **0.797** | 0.827 |
| real − placebo | −0.008 | **+0.001** | +0.013 |
| real − walk | −0.140 | −0.033 | +0.014 |

**The placebo column is the finding.** It is the same band width at a matched
distance on the same bars, differing from the origin only in not being one, and
it is returned to just as often everywhere. The rate is set by how wide the zone
is relative to how far price travelled, and both of those are properties of the
construction rather than of the market.

A walk makes the same point from the other side: with no structure at all, the
geometry returns 0.825 of the time at a hundred bars. The number the question
was about is what a random walk produces.

## The horizon is half the claim

| horizon | fx majors, 1h | walk |
|---|---:|---:|
| 20 bars | 0.542 | 0.612 |
| 50 bars | 0.703 | 0.753 |
| 100 bars | 0.783 | 0.824 |
| 500 bars | 0.894 | 0.920 |

"82% of origins are returned to" is not a fact about origins until the horizon
is attached, and at 500 bars every class exceeds 0.87. Quoting the level without
the horizon and the placebo is quoting the geometry.

## The engulfed-candle zone is the same story, more so

A published method draws its entry zone on the candle that got **engulfed**
rather than the one that did the engulfing. Measured identically:

* return rate at h=100: **0.931 to 0.989**, median 0.975 over 42 class-frames;
* real − placebo: median **+0.001**, range −0.004 to +0.010;
* **median bars to return: zero.**

That last row is the whole of it. The engulfed candle's range sits immediately
behind current price, so price is usually inside the zone already and "returns"
on the first bar. A 97% hit rate on a target you are standing on is not a target.

## And an engulf is not a displacement origin

They select opposite candle shapes, which is worth stating because the two are
easy to conflate - both mark "where the big move started".

| | all bars | engulfing bars |
|---|---:|---:|
| range, in median bar ranges | 1.00 | **1.42** |
| body as a share of range | 0.499 | **0.408** |
| share clearing the 0.65 body test | 0.314 | **0.151** |

An engulf selects a **wide, wick-heavy** bar; the desk's push test selects a
**body-dominant** one. Among engulfing bars the displacement test passes so
rarely that the combined arm is a tenth the size of either. Conflating them
would import a measurement from one construction into another that selects the
opposite shape.

## What this does and does not change

**It does not stop `fade-to-value` targeting the origin.** If you target a price
a known distance away and give it a hundred bars, you reach it about 80% of the
time; that is operationally true and the doc already frames the figure as a
target hit rate.

**It does remove any claim that the origin is selected for returning.** A price
at the same distance that is not an origin is reached just as often, so the
origin contributes nothing to *choosing* the target. Anything built on "origins
are special because 82% of them get revisited" is built on the distance and the
horizon.

The honest version of the statistic carries three things with it: the horizon,
the zone width in volatility units, and the placebo rate. Without them, 82% is a
restatement of how the zone was drawn.
