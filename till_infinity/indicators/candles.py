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
function here takes already-closed bars, and `Candles` is what drops the live
one: with `confirm` set it refuses a bar Nautilus marks `is_revision`, which is
what a forming bar's updates are, so `Candles.bars` only ever holds closed
bars.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from nautilus_trader.indicators.base import Indicator
from nautilus_trader.model.data import Bar as NautilusBar

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
    #: Tick volume where the venue gives one; 0 means unknown. Read by the shadowed MFI gate only.
    volume: float = 0.0

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

    See `trading-candles.md` in research/docs.
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


def rejection_wick(bars: list[Bar], want_up: bool) -> float:
    """How much of the last bar was the wick that rejected the level, in [0, 1].

    See `trading-candles.md` in research/docs.
    """
    if not bars:
        return 0.0
    bar = bars[-1]
    if bar.range <= 0:
        return 0.0
    return (bar.lower if want_up else bar.upper) / bar.range


def confirms(bars: list[Bar], level: float, want_up: bool, tolerance: float = 0.0) -> str:
    """The pattern confirming a trade at `level`, or "" if none does.

    See `trading-candles.md` in research/docs.
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


# ==========================================================================
# the engine's view
# ==========================================================================


class Candles(Indicator):
    """Candle patterns on **confirmed** bars, with the shapes this module knows.

    Registered with `Actor.register_indicator_for_bars` or the identical method
    on `Strategy`.

    ## Waiting for the confirmed bar, which is the whole point of the gate

    The Bjorgum script carries this as an input - *"Wait For Confirmed Bar"*,
    `repaint`, defaulting to **true**, with the tooltip "False will show
    potential patterns forming before they are confirmed". That is the honest
    description: a hammer half way through its bar is not a hammer, it is a bar
    that currently looks like one, and by the close it may be a marubozu. A
    pattern read off a forming bar is read off a measurement that has not
    finished.

    Nautilus marks that case itself: `Bar.is_revision` is true for a bar that
    revises one already emitted, which is what a forming bar's updates are. So
    `confirm=True` drops revisions and `confirm=False` admits them, and the
    second is for watching a shape build rather than for deciding on one.

    Two further layers already protect this and neither replaces the gate. The
    MT5 adapter drops forming bars at the source, by comparing the bar's open
    time against the clock - but that is one venue, and a crypto feed
    aggregating internally will revise. An EXTERNAL bar type delivers closed
    bars only - but an INTERNAL one aggregating from ticks need not. The gate
    costs one boolean and covers both.

    ## Nautilus has the graded primitives

    `indicators.fuzzy_candlesticks` grades body, size and wicks into categories
    against a rolling window, which is a better size judgement than this
    module's fixed fractions - `TAIL_SHARE`, `STUB_SHARE`, `BODY_THIRD`. What
    it has no notion of is a **level**, and `confirms(bars, level, want_up)` is
    the question this desk asks. Use both: theirs for how big, this for where.
    """

    def __init__(self, *, confirm: bool = True, kept: int = 3) -> None:
        if kept < 2:
            raise ValueError(
                f"kept={kept} cannot see a two-bar pattern: engulfing and the "
                f"tweezers each need the bar before."
            )
        super().__init__([confirm, kept])
        #: Drop revisions. The script's `repaint`, and its default.
        self.confirm = bool(confirm)
        self.kept = int(kept)
        self._bars: deque[Bar] = deque(maxlen=self.kept)
        self.skipped = 0

    # ------------------------------------------------------------- the engine

    def handle_bar(self, bar: NautilusBar) -> None:
        """Nautilus's entry point. A revision is counted and dropped."""
        if self.confirm and bar.is_revision:
            self.skipped += 1
            return
        self._bars.append(_of(bar))
        self._set_has_inputs(True)
        if not self.initialized and len(self._bars) >= 2:
            self._set_initialized(True)

    def reset(self) -> None:
        """Nautilus's reset: as if this had never seen a bar."""
        self._bars.clear()
        self.skipped = 0
        self._set_has_inputs(False)
        self._set_initialized(False)

    # ------------------------------------------------------------ the reading

    @property
    def bars(self) -> list[Bar]:
        """The confirmed bars held, oldest first."""
        return list(self._bars)

    @property
    def last(self) -> Bar | None:
        return self._bars[-1] if self._bars else None

    @property
    def hammer(self) -> bool:
        """A long lower tail with the body at the top. None of these is a
        signal: they are shapes, and a shape at a level is the question."""
        return bool(self._bars) and hammer(self._bars[-1])

    @property
    def shooting_star(self) -> bool:
        return bool(self._bars) and shooting_star(self._bars[-1])

    @property
    def engulfing(self) -> str:
        """ "up", "down" or "" - the two-bar shape, or nothing."""
        if len(self._bars) < 2:
            return ""
        return engulfing(self._bars[-2], self._bars[-1])

    def confirms(self, level: float, want_up: bool, tolerance: float = 0.0) -> str:
        """Did the auction reach `level`, get rejected, and close away from it?

        The level-relative question, which is the one worth asking of a shape.
        """
        if len(self._bars) < 2:
            return ""
        return confirms(list(self._bars), level, want_up, tolerance)

    def rejection_wick(self, want_up: bool) -> float:
        """The wick that rejected, as a share of the bar's range."""
        if not self._bars:
            return 0.0
        return rejection_wick(list(self._bars), want_up)


def _of(bar: NautilusBar) -> Bar:
    """This module's lightweight bar from the engine's.

    Nautilus's `Price` is fixed-precision, so `float()` here is already the
    truncated number: an instrument declared at two decimals has had its wicks
    rounded before any shape test sees them.
    """
    return Bar(
        open=float(bar.open),
        high=float(bar.high),
        low=float(bar.low),
        close=float(bar.close),
    )
