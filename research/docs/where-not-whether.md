# Does a level change the barrier race when it sits at the barrier?

**Measured 2026-11-16.** Five majors, 15m execution against 4h levels, eight
years, 30,676 races per geometry.

[`reactive-zones.md`](reactive-zones.md) closed levels as a **signal** - six
kinds, every control matching the real arm. This asks the one question none of
those did, because a rule makes two decisions and only one had been tested:

* **whether** to act, which is the signal. Closed.
* **where** to act - the entry, the stop, the target.

**Nominating a price is not predicting one.** A level could be worthless as a
signal and still be the right place to put a stop, and if it were, that would
be worth more than a directional edge: the same stop distance surviving more
often costs nothing, and it is immune to direction being closed.

## The design

The obvious comparison is incoherent. "A stop at a level" and "a stop at the
same distance with no level" are the **same price**. So the split is
conditional instead: entries every 32 bars, the **side from a seeded coin**,
barriers at fixed ATR distances, and each race labelled by whether a level
happens to sit within 0.25 ATR of the stop - and separately, of the target.

The coin does real work. No directional claim can be smuggled in, and every
arm has the same expectation on a driftless walk - `1/(1+N)` - so a departure
is about placement alone. A bar spanning both barriers counts as a **loss**,
which is the conservative reading and why every cell sits a little under the
walk.

## The result

Pooled over five instruments, with the mirrored **placebo** - the same
distance with no pivot behind it - beside each split:

| geometry | walk | level at stop | no level | placebo at stop | no placebo |
|---|---:|---:|---:|---:|---:|
| 1.0 / 1.0 | 0.500 | 0.495 | 0.488 | 0.492 | 0.495 |
| 1.0 / 2.0 | 0.333 | 0.324 | 0.322 | 0.322 | 0.327 |
| 2.0 / 2.0 | 0.500 | **0.491** | **0.497** | **0.491** | **0.497** |
| 2.0 / 4.0 | 0.333 | 0.319 | 0.340 | 0.323 | 0.336 |

| geometry | level at target | no level | placebo at target | no placebo |
|---|---:|---:|---:|---:|
| 1.0 / 1.0 | 0.493 | 0.493 | 0.490 | 0.502 |
| 1.0 / 2.0 | 0.323 | 0.324 | 0.322 | 0.326 |
| 2.0 / 2.0 | 0.493 | 0.491 | 0.494 | 0.488 |
| 2.0 / 4.0 | 0.325 | 0.328 | 0.327 | 0.324 |

Standard errors are 0.003 on the larger group and 0.005 to 0.006 on the
smaller, so the difference between two groups carries about 0.006.

**The real split and the placebo split move together in every cell.** The
2.0/2.0 row is the clearest: 0.491 against 0.497 for a real level, and 0.491
against 0.497 for a mirrored price with no pivot behind it - identical to
three decimals. The largest movement anywhere is **-0.021** at 2.0/4.0, which
is a level at the stop making things *worse*, and its placebo reproduces
-0.013 of it.

**On the target side it is flatter still**: 0.493 against 0.493 at 1.0/1.0,
and nothing beyond 0.003 at any geometry.

## So placement is closed too

A level does not change the barrier race, on either side, at any of four
geometries, with the placebo reproducing what little movement exists. Taken
with the six-kind watchedness ladder, a level on this data does not predict
**and** does not place.

What remains untested is narrower than it was and worth stating precisely:

* **entry placement** - a resting limit *at* a level against one at the same
  distance, which trades fill rate against price and is a different
  measurement from a barrier race;
* **sizing** - a level as the thing that sets the stop *distance* rather than
  its price, which is the one use `levels.py` actually makes of it and which
  no study here has touched;
* **a level as a place to stop looking** - the exits, not the entries.

The first two are measurable with this harness. The third is a different
question about holding, and `fade-to-value` is the warning: it was killed by
its stop while its targets paid +28.16.
