# A level's weight orders its return rate on swings, and nowhere else

**Measured 2026-10-15.** Code: [`weight_return.py`](../ideas/weight_return.py).
Eight level types, 1h and 4h, ~12,400 scored decision points per cell.

Asked: *the weight of a level is directly or inversely proportional to its
return rate - research and test, and not only for displacement origins, for
other types of levels too.*

`levels.Level.strength` is the desk's weight and its most-read number, with
seventeen consumers:

    0.4 * evidence + 0.25 * agreement + 0.2 * recency + 0.15 * breadth

Until now it had no outcome to be fitted against. The hold rate is closed
([`statespace-conditional-holds.md`](statespace-conditional-holds.md)), and
sweep depth and push are closed ([`level-shrinkage.md`](level-shrinkage.md)).
The **return rate** is the one that is not - `fade-to-value` measures 82% of
displacement origins being returned to, and a target hit rate is exactly what a
weight should order if a weight means anything.

**Answer: directly proportional, on swing levels only, and it is the `recency`
term doing all of it.**

## The confound, which is most of the measurement

Return rate is overwhelmingly a function of **distance**, and three of the four
weight terms move with distance through the same mechanism - a level price was
at recently is both recent and near. A second channel is **volatility**: at a
fixed distance, a level touched recently means price covered that distance
faster, and a faster market traverses it again more readily.

So every figure is scored inside a (distance, volatility) cell - quarter-sigma
distance bins in **current** sigmas, crossed with four short-to-long volatility
ratio bins, about 74 cells. What that does to the headline number:

| | swing, 1h, h=96 |
|---|---:|
| pooled, ignoring distance | **0.7470** |
| one-sigma distance bins | 0.5974 |
| quarter-sigma bins | 0.5721 |
| quarter-sigma x volatility | **0.5721** |
| distance-matched placebo | 0.5084 |

Two thirds of the apparent effect was distance. The volatility conditioning was
expected to take the rest and **did not** - the figure is unchanged - so that
hypothesis is refuted and the surviving effect is not a volatility proxy.

## What survives

`gap` is the conditioned AUC minus the same weight on a distance-matched price
that is not a level; `z` is that difference over its own bootstrap standard
error.

| type | 1h h=24 | 1h h=96 | 4h h=24 | 4h h=96 |
|---|---:|---:|---:|---:|
| **swing** | **+0.062 (z 2.53)** | **+0.064 (z 4.44)** | **+0.053 (z 2.04)** | **+0.067 (z 4.50)** |
| prev_week | +0.025 (1.06) | +0.029 (2.18) | +0.007 (0.49) | +0.003 (0.28) |
| origin | +0.023 (1.20) | +0.019 (1.62) | −0.015 (−0.79) | −0.006 (−0.46) |
| round | −0.003 (−0.16) | +0.002 (0.09) | −0.005 (−0.43) | −0.005 (−0.42) |
| prev_day | −0.008 (−0.62) | +0.001 (0.10) | −0.008 (−0.57) | −0.001 (−0.06) |
| dopen | −0.013 (−1.11) | −0.005 (−0.38) | −0.004 (−0.35) | −0.003 (−0.18) |
| turn | −0.002 (−0.16) | +0.001 (0.09) | −0.006 (−0.58) | −0.002 (−0.24) |
| poc | −0.016 (−1.00) | −0.012 (−1.07) | −0.018 (−1.31) | −0.010 (−0.99) |

**Swing is the only type that replicates**, on both frames and both horizons.
And the positive control agrees the right way round: on `Range_Break_*`, where a
range exists by construction, the same measurement reads **+0.2547 at z 4.07** -
four times the traded effect on the feed where levels are real by design.

**Displacement origins are the null case**, which is the opposite of what the
question expected. The sign reverses between frames, +0.019 at 1h against
−0.006 at 4h, and neither clears its own error. The 82% return rate is real and
a *weight* does not order it: being an origin is the whole of the information,
and how heavy the origin is adds nothing.

Power, from a planted weight-to-return tilt of known strength: a share of 0.20
is found at z 2.91 to 3.20, a share of 0.10 at z 2.08 on 1h and missed on 4h,
and the unplanted redraw reads 0.5118 and 0.4993 as it must. So the nulls above
are nulls against an effect about a third the size of the one found on swings,
and smaller effects are not excluded.

## The composite dilutes the one term that works

Per-term, conditioned the same way:

| type | frame | composite | evidence | agreement | **recency** | breadth |
|---|---|---:|---:|---:|---:|---:|
| swing | 1h h=96 | 0.5721 | 0.5014 | 0.4991 | **0.5702** | 0.5014 |
| swing | 4h h=96 | 0.5618 | 0.4978 | 0.5012 | **0.5636** | 0.4978 |
| origin | 4h h=96 | 0.5594 | 0.5471 | 0.5027 | **0.5750** | 0.5329 |
| poc | 1h h=96 | 0.5297 | 0.5080 | 0.4840 | **0.5574** | 0.4998 |
| turn | 1h h=96 | 0.4950 | 0.4904 | 0.5057 | **0.5253** | 0.4969 |

`evidence`, `agreement` and `breadth` read **0.49 to 0.55, mostly 0.50, on every
type** - they do not order this outcome at all. `recency` matches or beats the
four-term composite everywhere, and on five of eight types the composite scores
**below** its own recency term because the dead terms drag it toward 0.5.

`strength` weights them `0.4` evidence and `0.2` recency. For this outcome that
is backwards, and the fix is not a reweighting: it is to use recency alone.

Worth noting that `levels.md` §10 argues age is deliberately not rewarded -
"an old level with two touches is not stale, it is stale" - and that is about
*age as authority*. Recency is the opposite quantity and the measurement says
it is the only one of the four that carries anything here.

## What this does not say

The outcome is "did price trade at this price within N bars", which is a target
hit rate. It is not a direction, not an entry, and not profitable by itself -
`fade-to-value` already records that distinction for the 82%. A weight that
orders return rates on swings by +0.06 of AUC is a sizing and target input, not
a signal.

And `strength`'s seventeen consumers are not all ranking return rates. This
closes the question for one outcome; the terms may still earn their weights
against something else.
