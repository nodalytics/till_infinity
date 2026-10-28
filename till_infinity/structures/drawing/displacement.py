"""Levels where a one-sided move began, judged by candle character.

`origins` answers almost this question and answers it a different way, and the
difference is the whole reason this exists. There, a move is violent because it
is **large** - `MOVE_VOL` units in `MOVE_BARS` bars, clearing a prior extremum.
Here it is violent because it is **one-sided**: `PUSH_N` consecutive bars whose
bodies are at least `PUSH_BODY` of their own range, all the same colour. A bar
that opens at its low and closes at its high spent the whole period going one
way, and that is a statement about how the move happened rather than how far it
went.

The two disagree often enough to be worth keeping apart. A slow grind of four
units over six bars is an `origin` and is not a displacement; two decisive bars
that travel two units are a displacement and are not an `origin`.

## The rule is the desk's, stated by the desk

Specified over an afternoon and implemented here as given:

- **the push** - `PUSH_N` bars, each with a body at least `PUSH_BODY` of its
  range, all in one direction
- **the origin** - the bar immediately before them, whatever colour it is.
  Colour was tested and the desk's answer was that it does not matter, which is
  why nothing here looks at it. Its body must fall between `ORIGIN_BODY_MIN`
  and `ORIGIN_BODY_MAX` - "normally a small candle", with the desk's own
  correction that this is normally and not necessarily, a tenth to three
  fifths. The upper end keeps this from drawing a level at every step of a
  trend; the lower end rejects the doji, which is not a small candle but an
  undecided one
- **the band** - that bar's whole range, high to low
- **the line** - its *body* edge on the side price would return to: the bottom
  of the body for a demand zone, the top for a supply one. For a green candle
  that is the open and for a red one the close, which is how the desk put it
  and is the same thing said twice

`PUSH_BODY` and `PUSH_N` are the numbers already in
`structures/learning/touches.py`, imported rather than restated so the two
cannot drift apart.

## What is known about it, which is not nothing and is not good

`research/docs/fade-to-origin.md` measured this structure three ways and found
no tradable edge in any of them: traded from the zone, traded toward it, and
used to filter the origins `fade-to-value` already trades. Price returns to
these levels **77-81%** of the time and does not survive a stop in any
configuration tried.

That is a reason to draw them carefully and a reason not to believe them. The
return rate is real and the trade is not, so what a pass like this is for is
letting the outcome machinery say whether the *level* is respected - which is a
different question from whether a particular entry made money, and one none of
that work asked.

**Freshness is deliberately not applied here.** The desk's rule says a zone
should not have been tested before it is traded, and that is a property of the
moment of trading rather than of the level. `origins` made the same call for
the same reason - it keeps `revisits` rather than expiring on them, because how
fast they wear out is a measurement nobody here has made.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ...shared.state import Restorable
from ..learning.touches import PUSH_BODY, PUSH_N
from ..vol.volatility import Volatility
from .pips import Point, Swing

#: How far the push must travel, in volatility units, measured from the
#: origin's body edge to the end of the run.
#:
#: Body share says the bars were one-sided and says nothing about size, and two
#: one-sided bars inside a quiet range are a common and meaningless shape. This
#: is the floor that makes the pattern mean "a move started here" rather than
#: "two bars agreed". It is the one constant in this module the desk did not
#: specify, so it is stated here to be argued with rather than buried.
MIN_LEG_VOL = 1.5

#: The band an origin bar's body must fall in, as a share of its own range.
#:
#: **"Normally a small candle", and the desk's correction: normally, not
#: necessarily - a body anywhere from a tenth to three fifths.** Both ends do
#: work and they do different work.
#:
#: The **upper** end is what keeps this from drawing a level at every step of a
#: trend. Without it the pass emitted 40 levels on a 1,500-bar walk where `pip`
#: emitted 12 and `gap` 9 - three to four times every other formation, which is
#: not a formation but a flood. Every bar in a run is "the bar before two
#: one-sided bars", so a trending stretch qualifies almost everywhere, and what
#: separates the ones the desk means is that the origin itself did not travel.
#:
#: The **lower** end rejects the doji. A bar with no body is not a small candle,
#: it is an undecided one: open and close in the same place means the period
#: resolved nowhere, and the body edge - which is the level this pass emits -
#: is then an arbitrary point inside a range nobody defended.
ORIGIN_BODY_MIN = 0.10
ORIGIN_BODY_MAX = 0.60

#: How many origins one window may contribute, newest kept. A run of trending
#: bars produces an origin at almost every step, and without a cap a strong
#: session would crowd out every other formation in the merge.
KEEP = 40


@dataclass(slots=True)
class Displacement(Restorable):
    """An origin bar and the one-sided move that left it."""

    #: The origin bar - the one *before* the push.
    index: int
    #: Its whole range, ordered.
    low: float
    high: float
    #: The body edge price would return to: the body's bottom for a demand
    #: zone, its top for a supply one.
    line: float
    #: How far the push carried, in volatility units.
    leg_vol: float
    #: True where the push went up, so the origin sits below price and reads as
    #: demand.
    up: bool
    #: The bar the push finished on. Nothing here is knowable before it.
    confirmed_at: int


def _body(open_: float, close: float) -> tuple[float, float]:
    """A bar's body, ordered low to high."""
    return (close, open_) if open_ > close else (open_, close)


def pushed(
    opens: Sequence[float],
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    start: int,
    run: int,
    body: float,
) -> int:
    """`+1`, `-1` or `0`: the direction of a push of `run` bars from `start`.

    The same predicate as `left_by_displacement` in
    `research/ideas/origin_displacement.py`, which is where it was measured.
    """
    if start + run > len(closes):
        return 0
    first = closes[start] - opens[start]
    side = 1 if first > 0 else -1 if first < 0 else 0
    if side == 0:
        return 0
    for i in range(start, start + run):
        span = highs[i] - lows[i]
        if span <= 0:
            return 0
        if side * (closes[i] - opens[i]) < body * span:
            return 0
    return side


def displacements(
    opens: Sequence[float],
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    vol: Volatility,
    *,
    body: float = PUSH_BODY,
    run: int = PUSH_N,
    minimum_vol: float = MIN_LEG_VOL,
    origin_body: tuple[float, float] = (ORIGIN_BODY_MIN, ORIGIN_BODY_MAX),
    keep: int = KEEP,
) -> list[Displacement]:
    """Every origin a one-sided push left, oldest first.

    See `structures-drawing-displacement.md` in research/docs.
    """
    n = len(closes)
    if n < run + 1 or len({len(opens), len(highs), len(lows), n}) != 1:
        return []
    out: list[Displacement] = []
    for i in range(n - run):
        side = pushed(opens, highs, lows, closes, i + 1, run, body)
        if side == 0:
            continue
        span = highs[i] - lows[i]
        if span <= 0:
            continue
        bottom, top = _body(opens[i], closes[i])
        # The origin is the bar that did *not* travel, and is not a doji
        # either. See `ORIGIN_BODY_MIN` / `ORIGIN_BODY_MAX`.
        share = (top - bottom) / span
        if not origin_body[0] <= share <= origin_body[1]:
            continue
        line = bottom if side > 0 else top
        end = i + run
        reach = highs[end] if side > 0 else lows[end]
        if line <= 0:
            continue
        leg = vol.units(abs(reach - line) / line * 10_000)
        if leg < minimum_vol:
            continue
        out.append(
            Displacement(
                index=i,
                low=float(lows[i]),
                high=float(highs[i]),
                line=float(line),
                leg_vol=leg,
                up=side > 0,
                confirmed_at=end,
            )
        )
    return out[-keep:]


def points(
    times: Sequence[float],
    opens: Sequence[float],
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    vol: Volatility,
) -> list[Point]:
    """Displacement origins as turning points, so levels can form at them.

    The price emitted is the **body edge**, not the middle of the band. That is
    the desk's rule taken at its word - the support is the open of a green
    candle or the close of a red one - and it is also the one choice here that
    `gaps` makes differently, which is worth keeping so the two can be compared
    rather than quietly harmonised.

    See `structures-drawing-displacement.md` in research/docs.
    """
    if not closes or len(times) != len(closes) or len(opens) != len(closes):
        return []
    spot = closes[-1]
    last = len(times) - 1
    return [
        Point(
            index=found.index,
            time=int(times[found.index]),
            price=found.line,
            swing=Swing.HIGH if found.line > spot else Swing.LOW,
            # The leg, in basis points of volatility unit, so it ranks the way
            # prominence does for the other formations.
            prominence_bps=found.leg_vol * 10_000,
            # Not knowable until the push has printed, which is the whole
            # look-ahead question for this formation.
            confirmed=float(times[min(found.confirmed_at, last)]),
        )
        for found in displacements(opens, highs, lows, closes, vol)
    ]
