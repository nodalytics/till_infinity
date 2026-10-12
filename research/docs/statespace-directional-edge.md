# Direction is closed: the machinery works, the planted drift does not pay

Seven directional claims have been measured on this desk and all seven are
null against a matched control - the direction chain, the Landau cubic, Point
Z on both sides, the Hawkes cascade, five regime gates, the displacement
family. **Every one of them used a point estimate of direction.**

A state-space member carries something none of them had: a **calibrated
uncertainty on the drift**. `rate_confident` is `|rate| > 2 * sd_rate` and had
existed on every member since the package began without once being used as a
gate. If the drift is mostly noise but *occasionally* identified, the edge
lives in the subset where the filter says it knows - and nothing tested so far
could have found it.

That is now measured. The harness is `research/ideas/directional_edge.py`.

## The result, in three rows

`in sprd` is the edge net of a matched control, in spread units. Break-even
needs **1.0** and a round trip **2.0**. `share pays` is the fraction of cells
whose most-confident bucket clears one spread.

| arm | horizon | lowest confidence | highest confidence | top `z` | share `z>2` | **share pays** |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| **planted** - drift genuinely switches | 1 | -0.006 | **+0.019** | **+2.90** | **0.67** | **0.00** |
| **flat** - drift zero by construction | all | +0.00 to +0.10 | -0.04 to +0.05 | -1.58 to +0.54 | **0.00** | **0.00** |
| **traded** - 8 instruments | all | **±0.000** | **±0.000** | -0.63 to +0.05 | **0.00** | **0.00** |

Read in order, they say three different things.

**1. The machinery works.** On `Drift_Switch_Index_10/20/30` - a real market
whose drift genuinely switches between discrete values - the confidence gate
finds it at `z = +2.90` for `reverting` and `+2.86` for `kalman`, with two of
three cells past `|z| > 2`, and the gradient runs the right way: the
least-confident bucket is negative and the most-confident positive. So the
filter's uncertainty **is** informative about when its drift estimate can be
trusted, and the gate reads it correctly.

**2. Real markets have no drift to find.** Sixty-four traded cells - eight
instruments, two members, four horizons - at `±0.000` spreads, with the
most-confident bucket's `z` between `-0.63` and `+0.05` and **not one cell**
past `|z| > 2`. The gate that works on the planted feed finds nothing here.

**3. And even the planted drift does not pay.** This is the new part. The best
edge anywhere in the table is `+0.019` spreads, on the feed where the drift is
*engineered to exist*, against the `1.0` that break-even needs - **fifty times
short**, before a round trip.

So direction is not merely absent from real markets. **It would not pay even
if it were present at the magnitude Deriv builds into a drift-switching
index.** That is a ceiling rather than another null, and it is why this closes
rather than adding an eighth entry to the list.

## The flat feeds are the method check

`Volatility_*` and `Step_Index` have **zero drift by construction**, so
anything they report is artefact. Their most-confident buckets read `z` of
`+0.54`, `+0.07`, `+0.13`, `-0.01` and `-1.58` across members and horizons,
with `share z>2` of **0.00** everywhere. Nothing where there is nothing - so
the `+2.90` on the planted feed is the gate working, not the gate's own noise.

## The long-horizon idea fails for a different reason

The standing record said sub-three-minute directional nulls mean *cannot pay*
- a cost threshold of 0.188 against a detection of 0.08 - rather than *cannot
find*, which suggested the edge might live at horizons where a spread is
amortised. At 1h a spread is paid some 24 times a day; over a month, once in
700 bars.

Measured out to 720 bars - a month - that does not rescue it, and the reason
is the **sample** rather than the cost. The standard errors here use the
**non-overlapping** count, `len / horizon`, so 12,602 overlapping rows at a
720-bar horizon are **17 independent observations**, not 12,602. Quoting the
raw count would have inflated every long-horizon t-statistic by a factor of
27. At 17 observations nothing is establishable, and every 720-bar `z` in the
table sits between `-0.01` and `+0.05`.

So the long horizon makes the cost gate passable in principle and removes the
data needed to clear it. That trade is not favourable at any point on the
range tested.

## One bug, caught by a `nan`

The first version scored the planted arm by comparing the **whole** row set
against random draws of the whole row set. Every draw of `len(rows)` from
`rows` is the same set, so the control's spread was zero and every `z` came
back `nan`.

The right null for a whole set is **sign randomisation** - keep the forward
moves and flip the drift's sign at random - which asks whether the drift's
*direction* carries information rather than whether a subset differs from its
parent. The subset null still applies to the confidence buckets, where it is
the duty-cycle control it was always meant to be.

Two different questions needed two different nulls, and the `nan` is what said
so.

## What this closes, and what it leaves

**Closed:** directional edge from a single-series state-space member. The
confidence gate was the last untested idea that was specific to the
state-space approach rather than borrowed from an indicator, the machinery
demonstrably works, and the ceiling is 2% of a spread on a planted drift.

**Not tested here, and not worth testing after this:** the panel factor's
direction and cross-member sign agreement. Both were in the design and both
are refinements of a quantity whose *best case* has now been measured at
fifty times too small. A factor estimated from N series has `sqrt(N)` less
noise, which moves `+0.019` to perhaps `+0.06` - still an order of magnitude
short.

**What is left is magnitude**, which is where every surviving result on this
desk already lives: the `Q` clock at +1055, the clock and the loop composing
at +1567, the log-volatility ladder at +191 to +547, and the walk's band as
the best-calibrated forecast there is.
