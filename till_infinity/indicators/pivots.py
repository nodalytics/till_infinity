"""Session pivots: the levels everyone else is already looking at.

A swing level is discovered from what price did. A pivot is arithmetic on the
previous period's high, low and close, published before the period opens, and
watched by enough people that it matters whether or not the formula means
anything. A level's power here is partly self-fulfilling, which is a reason to
carry them rather than to dismiss them.

## Why they are worth having, and the reason is not edge

**They are the control the swing book has never had.** A pivot costs nothing
to compute, has no parameters to fit and no detector to tune. If the Kalman
book over `trend.pivots` does not beat this, the swing detection is not
earning its complexity - and nothing on this desk has ever checked. That is
the main use.

**No look-ahead, at all.** Today's set is fully determined by yesterday, so
unlike a swing there is no question of when it became knowable. A `Session` is
emitted only once a bar from the *next* one arrives, which is the same
discipline `trend.pivots` follows for a confirmed turn.

**They exist before the first touch.** A swing level needs price to have
turned there already; a pivot is there on the open, which is when a level is
most useful and a swing level knows least.

## The prior, attached because this is range-derived

`topology-restates-volatility` is measured here: levels, ranges and shapes all
read null once volatility is stratified. R2 and S2 are the pivot plus and minus
the prior range, so their distance from PP *is* a volatility estimate, and
"price reached R2" is close to "price moved one prior range" - tautological in
the way `a-return-rate-is-geometry` describes.

So these are sound as a **distance** - which is the one thing levels survived
as, per `the-origin-picks-a-distance-not-a-probability` - and refuted as a
**probability**. Build on them for placement and for control, not for entry.
`level-shield.md` is the recent instance: a level in the path does not suppress
the move, over 210 cells on 14 feeds.

## The session boundary is a choice, and it is not a neutral one

`day_of` cuts at UTC midnight because a pivot set that shifts with the
observer's clock is not the same level two people are looking at. But the FX
day a broker rolls is 21:00-22:00 UTC, not midnight, and **21:00 is exactly
where a survivorship confound lives** - a random walk held across it reads
+0.61R, and the BOS reconciliation found three trades exiting at the Sunday
reopen for the same reason. `boundary` shifts the cut in seconds so the two can
be compared rather than assumed; the default is the one that is reproducible
across observers, not the one a broker uses.

One more uncertainty worth stating: the recorded store's `ts` is probably the
bar's **open** rather than its close, so a bar near a boundary may fall in the
wrong session by one bar. It affects the last and first bar of each period and
nothing else.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from nautilus_trader.indicators.base import Indicator
from nautilus_trader.model.data import Bar

from till_infinity.utils.state import Restorable

from .levels import Sided

NANOS = 1_000_000_000

#: Periods a set is computed for. Daily is what most desks watch; weekly and
#: monthly survive longer and are kept separately rather than merged, because
#: a weekly R1 and a daily R1 at the same price are two different claims.
PERIODS: tuple[str, ...] = ("daily", "weekly")

#: Every period this module can cut. `monthly` is available and off by
#: default: 19 years of daily bars support it, and a 76-day window does not.
KNOWN: tuple[str, ...] = ("daily", "weekly", "monthly")

#: The set, strongest first. R3 and S3 are rarely reached, which the touch
#: statistics discover on their own rather than being told.
#:
#: `PH`, `PL` and `PC` - the prior period's high, low and close - are included
#: because they are watched more often than the computed pivots and cost
#: nothing to carry.
NAMES: tuple[str, ...] = ("PP", "R1", "S1", "R2", "S2", "R3", "S3", "PH", "PL", "PC")

#: Which side each name is: +1 resistance, -1 support, 0 neither.
#:
#: **This is where a pivot set carries asymmetry, and the price is not.**
#: `Sided` tilts a parameter; it must never tilt a pivot's own price, because
#: the only property a pivot has is that other people are watching that exact
#: number - a tilted R1 is not the R1 anybody else is looking at, and the
#: self-fulfilling part, which is the whole argument for carrying these, is
#: gone. So the set is published exactly and the side is published with it,
#: and a per-side *parameter* is applied by whatever places against it.
#:
#: `PP` and `PC` are 0 rather than guessed. The pivot is a midpoint that price
#: approaches from either side and the prior close is a reference, not a
#: barrier, so handing either a side would make `Sided.for_side` return a
#: tilted value for a level that has no side.
SIDES: dict[str, int] = {
    "R1": 1,
    "R2": 1,
    "R3": 1,
    "PH": 1,
    "S1": -1,
    "S2": -1,
    "S3": -1,
    "PL": -1,
    "PP": 0,
    "PC": 0,
}


@dataclass(frozen=True, slots=True)
class Session(Restorable):
    """One period's range. The whole input to a pivot set."""

    start: int
    end: int
    high: float
    low: float
    close: float
    period: str = "daily"

    @property
    def width(self) -> float:
        """The range, never negative - it is a scale and never a signal."""
        return max(0.0, self.high - self.low)


def levels_from(session: Session) -> dict[str, float]:
    """The classic floor-trader set, plus the prior period's own extremes.

    One variant of several in circulation and the one most widely watched,
    which is the only property that matters for a level whose power is partly
    that other people are looking at it. Camarilla and Woodie's differ and are
    not better; they are watched less.
    """
    high, low, close = session.high, session.low, session.close
    pivot = (high + low + close) / 3.0
    width = session.width
    return {
        "PP": pivot,
        "R1": 2.0 * pivot - low,
        "S1": 2.0 * pivot - high,
        "R2": pivot + width,
        "S2": pivot - width,
        "R3": high + 2.0 * (pivot - low),
        "S3": low - 2.0 * (high - pivot),
        "PH": high,
        "PL": low,
        "PC": close,
    }


# ------------------------------------------------------------------- the cuts


def day_of(when: float, *, boundary: float = 0.0) -> int:
    """The start of the day containing `when`, in UTC seconds.

    `boundary` shifts the cut - 21 * 3600 for the broker's FX day. A positive
    shift means a moment before it belongs to the previous day, which is what
    "the day starts at 21:00" has to mean.
    """
    moment = datetime.fromtimestamp(when - boundary, UTC)
    midnight = datetime(moment.year, moment.month, moment.day, tzinfo=UTC).timestamp()
    return int(midnight + boundary)


def _labelled(start: int, boundary: float) -> datetime:
    """The calendar day a session beginning at `start` is named for.

    **A shifted session is named for the day it ends in, not the one it
    starts in**, which is the whole content of "Sunday 21:00 is Monday's
    session". Getting this from the start date instead put the FX week's first
    boundary on Monday evening - a day late - and the same error would have
    put a month boundary in the wrong month whenever the 1st opened the
    evening before.
    """
    shift = 86_400.0 if boundary > 0.0 else 0.0
    return datetime.fromtimestamp(start - boundary + shift, UTC)


def week_of(when: float, *, boundary: float = 0.0) -> int:
    """The start of the containing week: the session named for the Monday."""
    start = day_of(when, boundary=boundary)
    return int(start - _labelled(start, boundary).weekday() * 86_400)


def month_of(when: float, *, boundary: float = 0.0) -> int:
    """The start of the containing month, under the same cut."""
    start = day_of(when, boundary=boundary)
    return int(start - (_labelled(start, boundary).day - 1) * 86_400)


CUTS = {"daily": day_of, "weekly": week_of, "monthly": month_of}


class Sessions:
    """Folds bars into periods, emitting each one only when it is complete.

    Kept as a plain object rather than inside the indicator so the
    period arithmetic is testable without a bar, which is the same argument
    `ladder.Episodes` and `strategies/sizes` make.
    """

    def __init__(self, periods: Sequence[str] = PERIODS, *, boundary: float = 0.0) -> None:
        unknown = [p for p in periods if p not in CUTS]
        if unknown:
            raise ValueError(
                f"{', '.join(unknown)} is not a period this cuts. Known: {', '.join(KNOWN)}."
            )
        self.periods = tuple(periods)
        self.boundary = float(boundary)
        self.open: dict[str, Session] = {}

    def observe(self, when: float, high: float, low: float, close: float) -> list[Session]:
        """Fold one bar in, and return whatever just completed.

        **A period is emitted when a bar from the next one arrives, never on
        the last bar of its own.** A period's high is not known until the
        period is over, so emitting early would publish a set computed from a
        range that had not finished - the same look-ahead a swing has before
        its confirmation.

        A bar from *before* the open period is ignored rather than folded: out
        of order input would otherwise reopen a period already published.
        """
        done: list[Session] = []
        for period in self.periods:
            start = CUTS[period](when, boundary=self.boundary)
            current = self.open.get(period)
            if current is not None and start < current.start:
                continue
            if current is None or current.start != start:
                if current is not None:
                    done.append(current)
                self.open[period] = Session(
                    start=start,
                    end=int(when),
                    high=high,
                    low=low,
                    close=close,
                    period=period,
                )
                continue
            self.open[period] = Session(
                start=current.start,
                end=int(when),
                high=max(current.high, high),
                low=min(current.low, low),
                close=close,
                period=period,
            )
        return done

    def forming(self, period: str = "daily") -> Session | None:
        """The period still in progress. **Not usable for pivots** - that is
        the point of the class, and it is exposed only so a caller can report
        how far through a period it is."""
        return self.open.get(period)


class Pivots(Indicator):
    """The pivot sets for each period, from completed periods only.

    Registered with `Actor.register_indicator_for_bars` or the identical
    method on `Strategy`. Holds no state about touches: this says where the
    levels are, and `Levels` is the book that learns what happens at them.
    """

    def __init__(
        self,
        *,
        periods: Sequence[str] = PERIODS,
        boundary: float = 0.0,
    ) -> None:
        super().__init__([",".join(periods), f"{boundary:.0f}s"])
        self.sessions = Sessions(periods, boundary=boundary)
        self.periods = self.sessions.periods
        self.boundary = float(boundary)
        #: The published set per period, and the period it was computed from.
        self.sets: dict[str, dict[str, float]] = {}
        self.sources: dict[str, Session] = {}
        self.published = 0

    def handle_bar(self, bar: Bar) -> None:
        """Nautilus's entry point. `ts_event` is the bar's close."""
        self.update_raw(
            float(bar.high),
            float(bar.low),
            float(bar.close),
            bar.ts_event / NANOS,
        )

    def update_raw(self, high: float, low: float, close: float, when: float) -> None:
        """Fold one bar in and republish any period that completed."""
        self._set_has_inputs(True)
        for session in self.sessions.observe(when, high, low, close):
            self.sets[session.period] = levels_from(session)
            self.sources[session.period] = session
            self.published += 1
        if self.sets:
            self._set_initialized(True)

    # ----------------------------------------------------------- the queries

    def set_for(self, period: str = "daily") -> dict[str, float]:
        """This period's set, or empty until one has completed."""
        return dict(self.sets.get(period, {}))

    def price(self, name: str, period: str = "daily") -> float | None:
        """One named level, or `None` where no period has completed yet.

        `None` rather than zero, because zero is a price and a caller
        comparing against it would place an order at the bottom of the book.
        """
        return self.sets.get(period, {}).get(name)

    def above(self, price: float, period: str = "daily") -> tuple[str, float] | None:
        """The nearest published level strictly above `price`, with its name."""
        found = [(n, p) for n, p in self.sets.get(period, {}).items() if p > price]
        return min(found, key=lambda pair: (pair[1] - price, pair[0])) if found else None

    def below(self, price: float, period: str = "daily") -> tuple[str, float] | None:
        """The nearest published level strictly below `price`, with its name."""
        found = [(n, p) for n, p in self.sets.get(period, {}).items() if p < price]
        return max(found, key=lambda pair: (pair[1] - price, pair[0])) if found else None

    def room(self, price: float, period: str = "daily") -> tuple[float, float] | None:
        """Distance down to the nearest level and up to the next, in price.

        The reading these are actually sound for - a distance rather than a
        probability. `None` where either side is unpublished, because a room
        measured against only one wall is not the quantity.
        """
        under, over = self.below(price, period), self.above(price, period)
        if under is None or over is None:
            return None
        return price - under[1], over[1] - price

    def beyond(
        self,
        price: float,
        side: int,
        *,
        unit: float,
        buffer: Sided | float = 0.25,
        period: str = "daily",
    ) -> tuple[str, float] | None:
        """A stop price just past the nearest level on `side`, with its name.

        `side` is the trade's own: +1 long, so the stop goes **below** the
        nearest support and the level has to break before it is reached; -1
        short, so it goes above the nearest resistance. `buffer` is in
        volatility units and may be a `Sided`, which is where the per-side
        asymmetry enters - the price does not carry one and must not.

        The buffer's tilt is read on **the level's own side**, not the trade's,
        so one number means the same thing whichever way the trade is facing.

        `None` where no level is published on that side yet. This places
        against a level; whether that beats a fixed volatility distance is a
        measurement and not an assumption - `level-shield.md` found a level in
        the path does not suppress the move.
        """
        found = self.below(price, period) if side > 0 else self.above(price, period)
        if found is None or unit <= 0.0:
            return None
        name, level = found
        room = Sided.of(buffer).for_side(SIDES.get(name, 0)) * unit
        return name, level - room if side > 0 else level + room

    def _reset(self) -> None:
        self.sessions = Sessions(self.periods, boundary=self.boundary)
        self.sets = {}
        self.sources = {}
        self.published = 0
        self._set_has_inputs(False)
        self._set_initialized(False)

    def handle_quote_tick(self, tick: Any) -> None:
        """Refused rather than ignored: a pivot needs a period's high and low,
        and a quote carries neither. Registering this for quotes would leave a
        book that never published and no indication why."""
        raise NotImplementedError(
            "Pivots needs bars - a period's high, low and close - so register "
            "it with register_indicator_for_bars, not for quote ticks."
        )
