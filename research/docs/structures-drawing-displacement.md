# Structures Drawing Displacement

Rationale for `till_infinity/structures/drawing/displacement.py`, added
2026-10-08. The code keeps what the function *is*; this keeps why it is that
way.

## Why this is not `origins`

Both modules answer "where did a violent move begin", and they disagree about
what makes a move violent.

| | `origins` | `displacement` |
|---|---|---|
| violent because it is | **large** - `MOVE_VOL` units in `MOVE_BARS` bars | **one-sided** - `PUSH_N` bars of `PUSH_BODY`+ body |
| also requires | clearing a prior extremum (`EXTREMUM_BARS`) | a leg of `MIN_LEG_VOL` |
| the band | the last opposing bar, body if it is huge | the origin bar's whole range |
| the price | the refined change point | the origin's **body edge** |

A slow grind of four units over six bars is an `origin` and is not a
displacement. Two decisive bars travelling two units are a displacement and are
not an `origin`. They are different claims about the same kind of event and
keeping them apart is the point: the outcome machinery can then say which, if
either, is respected.

## The rule is the desk's, stated by the desk

Specified over an afternoon in October 2026 and implemented as given.

- **the push** - `PUSH_N` bars, each with a body at least `PUSH_BODY` of its
  own range, all in one direction
- **the origin** - the bar immediately before them, *whatever colour it is*.
  Colour was raised and the desk's answer was that it does not matter, so
  nothing in the module looks at it, and a test asserts that flipping the
  origin's colour changes nothing
- **the band** - that bar's whole range, high to low
- **the line** - the body edge on the side price returns to: the bottom of the
  body for a demand zone, the top for a supply one. The desk put it as "the
  open if the candle was green, the close if it was red", which is the same
  thing said twice - both are the body's bottom

`PUSH_BODY` and `PUSH_N` are imported from `structures/learning/touches.py`
rather than restated, so the number lives in one place. **It moved from 0.70 to
0.65 on 2026-10-08**, on the desk's call. That was free: no model in the tree
reads `displaced` yet - the three shipped envelopes quote on their original six
features and the retrain that would pick up the thirteen has never run - so
nothing had been fitted to the old threshold.

## `MIN_LEG_VOL`, the one constant the desk did not give

Body share says the bars were one-sided and says nothing at all about size, and
two one-sided bars inside a quiet range are a common and meaningless shape. The
leg floor is what makes the pattern mean "a move started here" rather than "two
bars agreed". It is stated as a constant to be argued with rather than buried
in a condition, and a test pins that it is the thing doing that work.

## The price emitted is the body edge, not the midpoint

The one choice here that `gaps` makes differently, and it is kept different
deliberately. `gaps` emits the **middle** of its band, because a gap is a range
and picking an edge would be picking which end to believe. A displacement
origin is not symmetric: the desk's rule names one edge as the level and treats
the rest of the range as the zone around it. Harmonising the two would throw
away a difference worth measuring.

## Look-ahead

An origin is not knowable until the push has printed, so `confirmed` is the
time of the **last push bar**, not the origin's own. Every look-ahead bug this
formation could have lives in that one field, and a test asserts
`confirmed > time` for every point drawn.

## What is known about it, which is not nothing and is not good

[`fade-to-origin.md`](fade-to-origin.md) measured this structure three ways and
found no tradable edge in any of them - traded from the zone, traded toward it,
and used to filter the origins `fade-to-value` already trades. Price returns to
these levels **77-81%** of the time and does not survive a stop in any
configuration tried, including every entry rule and stop pad swept (0 of 105
cells with a positive lower bound).

That is a reason to draw them carefully and a reason not to believe them. The
return rate is real and the trade is not. What a pass like this is for is
letting the outcome machinery say whether the **level** is respected, which is
a different question from whether a particular entry made money and one none of
that work asked.

## Freshness is deliberately not applied

The desk's rule says a zone should not have been tested before it is traded.
That is a property of the moment of trading rather than of the level, and
`origins` made the same call for the same reason - it keeps `revisits` rather
than expiring on them, because how fast they wear out is a measurement nobody
here has made.

## Why it is in `DEFAULT_FORMATION`

Because the alternative guarantees it stays unproven. `config.py` is blunt
about this: a pass outside `STRUCTURES_FORMATION` never runs in production,
never publishes a level, never journals an outcome, and so can never be judged.
`round` and `vwap` were both broken in ways nobody could see for exactly that
reason.
