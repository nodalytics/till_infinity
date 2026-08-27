"""Candlestick confirmation at a level: hammer, pin bar, engulfing.

A level says *where* a trade is worth taking. It does not say *when*, and the
gap between those has been the expensive part of this repo's record - trades
entered because price was near a level, stopped because it had not finished
going the other way first. A candlestick pattern is a claim about the second
question: that the auction reached a price, was rejected there, and closed
away from it inside one bar.

**The pattern is worthless away from the level.** A hammer in open space is a
bar with a long tail; a hammer whose tail reaches a level that has been
defended before is that level being defended again. So every check here takes
the level as an argument, and a pattern that did not touch it does not count.
That is the whole reason this module does not simply return "is this a
hammer".

## What the thresholds mean

The definitions below are the conventional ones, but conventional definitions
are stated in words and words do not run. The numbers are stated once, here,
so that they can be argued with rather than discovered inside a condition:

* a **rejection wick** is at least half the bar's range, and the opposing wick
  at most a seventh of it. Both are measured against the **range, not the
  body**, and that choice is the one worth explaining: the conventional
  phrasing is "the wick is twice the body", which inverts at exactly the shape
  it is meant to describe. A textbook hammer has a tiny body - that is what
  makes it a hammer - so a body-relative rule either passes everything once
  the body is small enough, or, if it guards against that by refusing small
  bodies, refuses the best examples of the pattern. Range-relative says what is
  actually meant: the tail dominates the bar.
* the **body sits in the far third** of the range from the wick. A bar with a
  long tail and its body in the middle is indecision, not rejection.
* an **engulfing** body strictly contains the previous body and closes the
  opposite way. Bodies, not ranges - a bar whose *range* covers the previous
  one but whose body does not is a wider bar, not a reversal. This one *is*
  body-relative, necessarily, so it keeps a **doji** guard: comparing against a
  body of almost nothing is a comparison with nothing.

## The bar that matters is the one that closed

The bridge returns the forming bar as the most recent element, and a forming
bar is not evidence: its close is the current price, so "closed away from the
level" is a statement about this instant that the next tick can withdraw. Every
function here takes already-closed bars, and `recent` is the thing responsible
for dropping the live one.
"""

from __future__ import annotations

from dataclasses import dataclass

#: The share of the bar's range the rejection wick must be. Half means the
#: tail is the larger part of everything that happened.
TAIL_SHARE = 0.5
#: The most of the range the *opposing* wick may be. Beyond this the bar was
#: rejected from both directions, which is indecision rather than a signal.
STUB_SHARE = 1.0 / 7.0
#: The share of the range the body must sit within, measured from the end
#: opposite the wick.
BODY_THIRD = 1.0 / 3.0
#: A body smaller than this share of the range is a doji, and is refused: the
#: wick ratios above are trivially satisfied when the body is near zero.
DOJI = 0.1


@dataclass(frozen=True, slots=True)
class Bar:
    """One closed candle."""

    open: float
    high: float
    low: float
    close: float
    time: float = 0.0

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def upper(self) -> float:
        return self.high - max(self.open, self.close)

    @property
    def lower(self) -> float:
        return min(self.open, self.close) - self.low

    @property
    def up(self) -> bool:
        return self.close > self.open

    @property
    def doji(self) -> bool:
        """Too little body for the wick ratios to mean anything."""
        return self.range <= 0 or self.body < self.range * DOJI


def hammer(bar: Bar) -> bool:
    """A long lower wick, a small body near the top. Rejection from below.

    Not required to be a bullish bar. A hammer's message is in the tail - the
    auction went down, found no takers and came back - and whether the close
    finished a tick above or below the open is a detail of where the bar
    happened to open, not of what happened inside it.

    A body of almost nothing is accepted rather than refused. That shape is a
    dragonfly doji, and at a level it is the *strongest* version of this
    pattern, not a degenerate one: price left and came all the way back.
    """
    if bar.range <= 0:
        return False
    if bar.lower < bar.range * TAIL_SHARE:
        return False
    if bar.upper > bar.range * STUB_SHARE:
        return False
    # Body in the top third, measured from the high.
    return (bar.high - min(bar.open, bar.close)) <= bar.range * BODY_THIRD


def shooting_star(bar: Bar) -> bool:
    """A long upper wick, a small body near the bottom. Rejection from above.

    The mirror of `hammer`, and the bearish half of what is loosely called a
    pin bar.
    """
    if bar.range <= 0:
        return False
    if bar.upper < bar.range * TAIL_SHARE:
        return False
    if bar.lower > bar.range * STUB_SHARE:
        return False
    return (max(bar.open, bar.close) - bar.low) <= bar.range * BODY_THIRD


def engulfing(previous: Bar, bar: Bar) -> str:
    """ "up", "down", or "" - whether this bar engulfs the previous body.

    Bodies rather than ranges, and strictly. A bar whose range covers the
    previous bar's range but whose body does not is simply a wider bar; the
    claim being made is that this session traded through everything the last
    one did *and closed beyond it*, which is a statement about opens and
    closes.
    """
    if bar.doji or previous.doji:
        return ""
    top, bottom = max(bar.open, bar.close), min(bar.open, bar.close)
    was_top, was_bottom = max(previous.open, previous.close), min(previous.open, previous.close)
    if not (bottom < was_bottom and top > was_top):
        return ""
    if bar.up and not previous.up:
        return "up"
    if not bar.up and previous.up:
        return "down"
    return ""


def touched(bar: Bar, level: float, tolerance: float = 0.0) -> bool:
    """Whether this bar's range actually reached the level."""
    return bar.low - tolerance <= level <= bar.high + tolerance


def confirms(bars: list[Bar], level: float, want_up: bool, tolerance: float = 0.0) -> str:
    """The pattern confirming a trade at `level`, or "" if none does.

    Three conditions, and a pattern satisfying two of them is not a weaker
    signal - it is a different event:

    1. the pattern is present on the **last closed bar**,
    2. that bar **reached the level**, and
    3. it **closed on the side the trade wants**, which is what separates a
       rejection from a breakout that has not finished yet.

    The third is the one most easily left out and the most important. A hammer
    whose tail pierces support and whose close is still below it is not support
    holding; it is support breaking, drawn in a shape that looks reassuring.
    """
    if len(bars) < 2:
        return ""
    previous, bar = bars[-2], bars[-1]
    if not touched(bar, level, tolerance):
        return ""
    # Closed on the side the trade wants. This is the check most easily left
    # out and the most important: a hammer whose tail pierces support and whose
    # close is still below it is not support holding, it is support breaking.
    if (bar.close < level) if want_up else (bar.close > level):
        return ""
    return _shape(previous, bar, want_up)


def _shape(previous: Bar, bar: Bar, want_up: bool) -> str:
    """Which pattern this pair makes, direction already settled."""
    if want_up:
        if hammer(bar):
            return "hammer"
        return "engulfing" if engulfing(previous, bar) == "up" else ""
    if shooting_star(bar):
        return "shooting-star"
    return "engulfing" if engulfing(previous, bar) == "down" else ""
