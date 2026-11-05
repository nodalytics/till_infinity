# Lowering the surprise trigger multiplies the events and not the edge: an impulse is followed by reversion, and a random walk reads the same

**Measured 2026-11-05** on the lab with
[`research/harness/trigger_expectancy.py`](../harness/trigger_expectancy.py):
seven traded markets and two Deriv synthetics at a 15-minute base, about
1.75 million readouts, signed continuation over 12 bars in units of the
volatility forecast made before the event, day-block bootstrap.

| question | verdict |
|---|---|
| Does expectancy per proposal hold up as the trigger falls? | **No.** It is negative at every threshold - **-0.066 at 1.5 sigma, -0.070 at 2.0, -0.069 at 2.5, -0.062 at 3.0** - while the event rate rises from 1.9% to 21.4% |
| Should the live trigger move from 3.0 to 1.5-2.5? | **No.** Events multiply about **5x** from 3.0 to 1.5 and per-event expectancy does not improve, so cost scales and edge does not. **0 of 6 instruments** clear the quoted round trip at any threshold |
| Which way does an impulse actually resolve? | **Reversion, not continuation.** The sign is negative throughout, so the textbook breakout reading is backwards - and the size, 0.04 to 0.07, is a fifth to a third of the 0.22 round trip |
| Is the reversion real? | **No.** The constant-volatility synthetics read **-0.033 and -0.044** at 1.5 and 2.0 with intervals excluding zero - the same sign and nearly the same size with no market structure present |
| Is anything here worth building? | **No.** The volatility reading in [`impulse-vol.md`](impulse-vol.md) stands; this is the direction side and it is dead at every threshold measured |

## Why this was measured

[`surprise-rate.md`](surprise-rate.md) measured what the threshold costs in
*events*: 15.2-17.4% of readouts at 1.5 sigma, 6.2-7.9% at 2.0, 0.9-1.9% at
3.0, against a Gaussian 0.27%. A fat tail is not an edge, and the reading
invites exactly the wrong inference - that a trigger firing more often than a
Gaussian predicts is finding something.

**Cost scales linearly with the event count. Edge does not.** So the only
thing that justifies a lower threshold is expectancy per proposal holding up
as it falls, and that is a measurement rather than an argument.

## The reading

Signed by the impulse, so positive means it continued:

| trigger | events | rate | continuation | 90% interval | net of 0.22 | instruments clearing cost |
|---|---|---|---|---|---|---|
| 1.5 | 374,938 | 21.4% | **-0.0656** | [-0.1056, -0.0241] | -0.286 | **0 of 6** |
| 2.0 | 216,615 | 12.4% | **-0.0703** | [-0.1263, -0.0109] | -0.290 | **0 of 6** |
| 2.5 | 127,978 | 7.3% | -0.0686 | [-0.1426, +0.0127] | -0.289 | 0 of 6 |
| 3.0 | 78,130 | 4.5% | -0.0620 | [-0.1649, +0.0422] | -0.282 | 0 of 6 |
| 4.0 | 32,501 | 1.9% | -0.0408 | [-0.2179, +0.1413] | -0.261 | 0 of 6 |

The cost line is **0.22 forecast units**, the quoted round trip. It is not
taken from the per-bar `spread` column, which `impulse-vol.md` and
`chart-patterns.md` both found unusable - 3.3 to 8.3 times below the quote on
FX and 6.5 times *above* it on `Volatility 75 Index`.

**The only thresholds whose intervals exclude zero are 1.5 and 2.0** - the
ones a lower trigger would use. What they show cleanly is a loss.

## The walk reads the same, which is the result

| trigger | traded | synthetic | synthetic 90% interval |
|---|---|---|---|
| 1.5 | -0.0656 | **-0.0327** | [-0.0638, -0.0040] |
| 2.0 | -0.0703 | **-0.0440** | [-0.0837, -0.0051] |
| 2.5 | -0.0686 | -0.0360 | [-0.1050, +0.0294] |
| 3.0 | -0.0620 | +0.0014 | [-0.1074, +0.1118] |

The Deriv synthetics are real markets with a known, constant-volatility
generator. They carry the same negative sign at 1.5 and 2.0, with intervals
that also exclude zero, at roughly half the size.

So the reversion is **mechanical, not structural**: selecting a bar on
`|r| / vol` picks moments where the denominator is small relative to what
follows, and the next measurement regresses. A market effect would not appear
in a generator that has none. The sign-flip surrogate agrees from the other
direction, reading **+0.009 to +0.023** across every trigger - it holds the
volatility path and destroys direction, and finds nothing.

## What this does not settle

**It is a conditional mean, not a trade.** There is no stop, no target and no
fill model, so the desk's `P(>= N R)` against `1/(1+N)` is not computed and
the cost comparison is the weaker mean-against-round-trip one. A favourable
reading here would have been a reason to build the barrier test; an
unfavourable one at every threshold is a reason not to.

**One horizon.** 12 bars at 15m. The decay in `impulse-vol.md` -
excess volatility 0.534 at 1 bar falling to 0.109 at 48 - says the interesting
window is short, and 1 and 4 bars are not measured here.

**Seven traded markets, two synthetics.** The synthetic arm is the one doing
the work and two is thin; the four-synthetic panel in `impulse-vol.md` read
the same direction.

## What is worth doing next

Nothing on this question. The direction side of the surprise statistic is now
closed at five thresholds, on 1.75 million readouts, with the walk reproducing
the effect. The live trigger should stay at 3.0 - not because 3.0 is right,
but because moving it changes how often the desk acts on a reading that does
not pay in either direction.

The constant's **name** is still wrong, which `surprise-rate.md` records: it
fires at 0.9-1.9%, not the "genuinely rare" its comment claims.
