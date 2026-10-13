# Order flow read off bars: real markets absorb, generators run

A bar is a summary of the order flow inside it, so the question is how much of
that flow the summary keeps. The answer here is: enough to tell a real order
book from a generated one by the **sign** of a single statistic, and enough for
a directional signal that is consistent on 8 of 8 traded instruments and absent
on 13 of 15 generated ones.

The harness is `research/ideas/orderflow_from_bars.py`.

## Why this was worth asking rather than taking a proxy on faith

**Most OHLC flow proxies read the same on a random walk.** `(C - O) / (H - L)`,
wick ratios and range-per-tick all take ordinary values on a driftless path,
because they are functions of path geometry. So every statistic here is
computed three ways: on the instrument, on a **matched walk** built from that
instrument's own per-bar tick counts and volatility, and on the generated
feeds. Nothing is reported that the walk also produces.

The matched walk is built by sampling the within-bar path rather than from a
closed form, because the high and low of a discrete walk are not the continuous
expressions. It lands on a `range ~ ticks` slope of **0.47 to 0.51** against the
0.5 that independence predicts, which is the harness checking itself.

**And the Deriv synthetics are not a zero-flow control.** Deriv generates their
tick process as well as their prices, so they have flow - a *specified* one,
posted at a near-fixed rate with no participants, no queue and no inventory
behind it. At 1h their activity extent is 1.001 to 1.016 against 2.7 to 9.4
traded, so their tick count is nearly constant by construction. The contrast is
**informative flow against uninformative flow**, which is sharper than present
against absent.

## The finding: the sign separates a book from a generator

| statistic | traded, vs its walk | generated, vs its walk |
| --- | :---: | :---: |
| `\|imbalance\|`, how far from mid-range it closed | **8 of 8 below** | **5 of 5 above** |
| `\|wick\|`, which side was rejected | **8 of 8 below** | **5 of 5 above** |
| run share, bars closing past half their range | **8 of 8 below** | **5 of 5 above** |
| absorption cv, spread of ticks per unit range | 8 of 8 above | 5 of 5 above |

**Opposite signs, unanimous on both sides.** Real markets close **nearer the
middle of their range** than a matched random walk does - they travel their
range and come back. That is intra-bar absorption, which is what passive
liquidity does and what a generator has no mechanism to produce. Deriv's
spiking families do the reverse: Boom, Crash and DEX close *further* from mid
than a walk, because a bar containing a jump closes at its extreme.

The departures are small - about 5% on the traded side - which is why the
**sign count** is the evidence and not the median. A 5% departure on 8 of 8 is
a different claim from a 40% departure on 4 of 8.

`absorption cv` is the one statistic that moves the same way on both, so it is
the weakest discriminator despite having the largest departure. It is reading
activity variation, which both have.

### The slope arm is weaker than the filter said, and that is expected

`statespace-activity-on-q.md` found the exponent relating a bar's variance to
its activity is **2**, which means the move grows linearly in tick count rather
than as its square root - a directional run. The cross-sectional `range ~
ticks` slope here gives **0.577 against the walk's 0.512**, above it on only
**5 of 8**.

These are not the same quantity and the filter is the better measurement. The
exponent related variance to the activity **share** - volume against its own
recent mean - inside a filter tracking the level. This slope is a plain
regression carrying every long-run change in volatility that had nothing to do
with activity, and volatility clustering attenuates it toward 0.5.

The generated feeds are **absent from this arm by design**: their tick count is
fixed, so `var(log ticks)` is near zero and `cov / var` explodes. The first run
reported slopes of 9.2, 13.5 and 21.8 for Boom, Crash and DEX, which are not
steep relationships but a division by almost nothing. `slope` now refuses a
regressor whose spread is below 0.05.

## The directional arm, which is the first consistent one here

Does absorption continue across the bar boundary? Feature on bar `t`, target
the sign of bar `t+1`, AUC against a **block shuffle** of the feature that
keeps its own serial structure and breaks only its alignment to the target.

**21 of 24 traded cells beat their null. 2 of 15 generated cells do** - and
both of those are `Drift_Switch_Index_10`, the one synthetic with a planted
drift regime.

| feature | median AUC | direction | traded cells beating null |
| --- | ---: | --- | :---: |
| imbalance | **0.4843** | closing near the high predicts **down** | 8 of 8 |
| wick | **0.5181** | the rejected side predicts **reversal** | 8 of 8 |
| absorption | 0.4931 | weak | 5 of 8 |

The two strong features **agree on the mechanism**: single-bar reversal, same
sign on every instrument, which is intra-bar absorption persisting one bar
rather than two unrelated findings. Best single cell is silver's imbalance at
**0.4678**.

### And it does not pay, which is the same answer in a new place

| instrument | edge, bp | room, bp | round-trip cost, bp | net |
| --- | ---: | ---: | ---: | ---: |
| XAUUSD | 1.10 | 22.95 | 0.41 | **+0.69** |
| XAGUSD | 2.83 | 45.58 | 5.60 | **-2.76** |
| US_Oil | 1.73 | 48.73 | 5.02 | **-3.30** |
| AUDUSD | 0.42 | 15.64 | 0.59 | **-0.17** |
| EURUSD | 0.47 | 9.97 | **0.00** | +0.47 |

An AUC of 0.52 is a 4% edge on the direction of a move, and a 1h bar has only
9 to 49 basis points of room, so the edge is **0.3 to 2.9 basis points per
bar**. Costs where they are measurable are 0.15 to 5.6.

**The `0.00` costs are a cache artefact and must not be read as free.** The
`spread` column is zero for the majors on this demo feed; a one-pip EURUSD
spread is about 0.93 bp, so the round trip is near 1.9 bp against an edge of
0.47. Taking that figure, EURUSD is **negative**, and so is every major.

So the honest statement is the desk's existing one arriving somewhere new:
`statespace` has already measured that a directional gate can be real at
`z + 2.90` and earn two per cent of a spread. This is real at 8 of 8 with a
mechanism and a control, and it earns roughly **a quarter of a spread**. Better,
and still not a trade.

## What would change that, and what would not

**Not** a better classifier. The edge is 4% of a move and the move is 10 bp;
doubling the AUC's distance from 0.5 still leaves it near the spread.

**The horizon is the lever.** Edge scales with the room available, and room
grows with horizon while the spread does not. The arm to run next is the same
features against the sign of the return over 2, 4, 8 and 24 bars, looking for
where `edge x room` clears twice the spread - and watching the AUC decay, since
absorption is a one-bar mechanism and may not survive aggregation.

**And the venue matters more than the signal.** This measures spot FX at a
retail spread. The same statistic on an instrument with a tighter spread, or
expressed as a barrier payoff where the cost structure is different rather than
as a spot round trip, is a different arithmetic problem with the same edge.

## What this says for the library

Two things are directly usable, and neither is a directional bet.

**The absorption sign is a market-class fingerprint.** It separates a real book
from a generator unanimously, which makes it a candidate for the same treatment
`bounding.SHIFTS` gives the barrier walls: a measured per-family constant the
library looks up rather than a thing each caller rediscovers.

**And it is a specification test for the generated feeds.** Boom, Crash and DEX
run *more* directional than a walk within the bar, by a margin that is 5 of 5
consistent. That is the jump in their generator, seen from a statistic nobody
designed to find jumps - which makes it a cheap standing check that a synthetic
family still behaves the way its name says.
