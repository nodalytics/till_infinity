"""Pivots: the levels everyone else is already looking at.

Swing levels are discovered from what price did. Pivots are the opposite —
arithmetic on the previous session's high, low and close, published before the
session opens, and watched by enough people that they matter whether or not the
formula means anything. A level's power here is partly self-fulfilling, and
that is a reason to include them rather than to dismiss them.

Two properties make them worth having alongside PIP levels:

**No look-ahead, at all.** A pivot for today is fully determined by yesterday,
so unlike a swing there is no question of when it became knowable. That makes
them a clean control: if PIP levels do not outperform pivots, the swing
detection is not earning its complexity.

**They exist before the first touch.** A swing level needs price to have turned
there already. A pivot is there on the open, which is exactly when a level is
most useful and a swing level knows least.

They flow into the same machinery — same zones, same touch tracking, same
per-side statistics — and carry `origin="pivot"` so kNN can learn that they
behave differently from swing levels without being cut off from them.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from .levels import Kalman, Level
from .state import Restorable
from .volatility import Volatility

#: Sessions a pivot set is computed for. Daily is what most desks watch;
#: weekly survives longer and is worth keeping separately rather than merged.
PERIODS: tuple[str, ...] = ("daily", "weekly")

#: Pivot levels, strongest first. R3/S3 are included for completeness and are
#: rarely reached — which the touch statistics will discover on their own
#: rather than being told.
NAMES: tuple[str, ...] = ("PP", "R1", "S1", "R2", "S2", "R3", "S3", "PH", "PL", "PC")


@dataclass(frozen=True, slots=True)
class Session(Restorable):
    """One completed period's range. The whole input to a pivot set."""

    start: int
    end: int
    high: float
    low: float
    close: float
    period: str = "daily"

    @property
    def range(self) -> float:
        return max(0.0, self.high - self.low)


def levels_from(session: Session) -> dict[str, float]:
    """The classic floor-trader set, plus the prior range itself.

    `PH`, `PL` and `PC` — yesterday's high, low and close — are included
    because they are observed more often than the computed pivots, and it costs
    nothing to let the statistics decide which of them actually matter.
    """
    high, low, close = session.high, session.low, session.close
    pivot = (high + low + close) / 3.0
    width = session.range
    return {
        "PP": pivot,
        "R1": 2 * pivot - low,
        "S1": 2 * pivot - high,
        "R2": pivot + width,
        "S2": pivot - width,
        "R3": high + 2 * (pivot - low),
        "S3": low - 2 * (high - pivot),
        "PH": high,
        "PL": low,
        "PC": close,
    }


def build(feed: str, session: Session, vol: Volatility) -> list[Level]:
    """Turn one completed session into levels ready for the same machinery.

    Initial uncertainty is a fixed fraction of a volatility unit rather than
    derived from scattered touches: a pivot's price is known exactly, so the
    only uncertainty is how precisely the market respects it, and that is a
    volatility question.
    """
    built: list[Level] = []
    for name, price in levels_from(session).items():
        if price <= 0:
            continue
        variance = vol.price_units(price, 0.4) ** 2
        built.append(
            Level(
                feed=feed,
                interval=session.period,
                filter=Kalman(mean=price, variance=variance, updated=session.end),
                origin=f"pivot:{name}",
                created=session.end,
                swings=1,
            )
        )
    return built


def is_pivot(level: Level) -> bool:
    return level.origin.startswith("pivot")


def label(level: Level) -> str:
    """`R1`, `PH`, … or "" for a swing level."""
    return level.origin.partition(":")[2] if is_pivot(level) else ""


# ------------------------------------------------------------------ sessions


def day_of(when: float) -> int:
    """UTC midnight for the day containing `when`. Sessions are UTC like
    everything else here — a pivot set that shifts with the observer's clock
    is not the same level two people are looking at."""
    moment = datetime.fromtimestamp(when, UTC)
    return int(datetime(moment.year, moment.month, moment.day, tzinfo=UTC).timestamp())


def week_of(when: float) -> int:
    """UTC midnight of the Monday of the containing week."""
    start = day_of(when)
    weekday = datetime.fromtimestamp(start, UTC).weekday()
    return start - weekday * 86_400


class Sessions:
    """Accumulates bars into completed sessions, one per period.

    A session is only emitted once a bar from the *next* one arrives, which is
    the same discipline the swing detection follows: a period's high is not
    known until the period is over.
    """

    def __init__(self, periods: Sequence[str] = PERIODS) -> None:
        self.periods = tuple(periods)
        self._current: dict[tuple[str, str], Session] = {}

    def observe(
        self, feed: str, when: float, high: float, low: float, close: float
    ) -> list[Session]:
        """Fold one bar in. Returns any sessions that just completed."""
        completed: list[Session] = []
        for period in self.periods:
            start = day_of(when) if period == "daily" else week_of(when)
            key = (feed, period)
            current = self._current.get(key)
            if current is None or current.start != start:
                if current is not None and current.start < start:
                    completed.append(current)
                self._current[key] = Session(
                    start=start, end=int(when), high=high, low=low, close=close, period=period
                )
                continue
            self._current[key] = Session(
                start=current.start,
                end=int(when),
                high=max(current.high, high),
                low=min(current.low, low),
                close=close,
                period=period,
            )
        return completed

    def current(self, feed: str, period: str = "daily") -> Session | None:
        """The session still in progress. Not usable for pivots — that is the point."""
        return self._current.get((feed, period))
