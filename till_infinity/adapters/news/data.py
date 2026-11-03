"""The custom data types the news client publishes.

**The release shape is where the lookahead lives, and it is the whole reason
these are two states rather than one record.**

An economic calendar entry exists long before its number does. `Event.actual`
is empty until the release and filled afterwards, so a naive replay that emits
the stored row at its scheduled time hands a strategy the outcome *before* it
happened. That is not a subtle leak: it is the number everybody is waiting for.

`open-gap-filters-are-lookahead` is the same mistake already made here once -
`drawing.gaps` emitted only *unfilled* gaps, so reading it as of a time before
the fill was known said which gaps would survive, and used as a bias it read
+0.50R a trade. A stored calendar row is lookahead in exactly that way, and for
the same reason: it was written after the fact.

So an entry is published twice:

  SCHEDULED  at the moment it became known - forecast and previous, no actual
  RELEASED   at its release time - with the actual, and the surprise

A backtest that subscribes to both sees what a trader saw, in the order they
saw it.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from nautilus_trader.core.data import Data


class Stage(StrEnum):
    """Which of an entry's two lives this is."""

    #: Announced, not yet released. Forecast and previous only.
    SCHEDULED = "scheduled"
    #: Released. The actual is present and the surprise is computable.
    RELEASED = "released"


class Importance(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

    @classmethod
    def of(cls, value: Any) -> Importance:
        try:
            return (cls.LOW, cls.MEDIUM, cls.HIGH)[int(value)]
        except (TypeError, ValueError, IndexError):
            return cls.LOW


class CalendarEvent(Data):
    """One economic calendar entry, at one of its two stages.

    A `Data` subclass, so it travels on the engine's own bus, is cacheable and
    can be written to and replayed from the catalogue - which is the property
    that makes a point-in-time backtest possible at all.
    """

    def __init__(
        self,
        *,
        event_id: str,
        title: str,
        country: str,
        stage: Stage,
        importance: Importance,
        ts_event: int,
        ts_init: int,
        forecast: float | None = None,
        previous: float | None = None,
        actual: float | None = None,
        unit: str = "",
        period: str = "",
        source: str = "",
    ) -> None:
        self._ts_event = ts_event
        self._ts_init = ts_init
        self.event_id = event_id
        self.title = title
        self.country = country
        self.stage = stage
        self.importance = importance
        self.forecast = forecast
        self.previous = previous
        # **Refused rather than dropped.** A scheduled entry carrying an
        # actual is the lookahead bug itself, and silently blanking it would
        # hide a broken producer - which is how a leak survives a review.
        if stage is Stage.SCHEDULED and actual is not None:
            raise ValueError(
                f"{event_id} is SCHEDULED and carries an actual of {actual!r}. "
                f"A scheduled entry is published before its number exists; "
                f"emitting one with an actual is lookahead."
            )
        self.actual = actual
        self.unit = unit
        self.period = period
        self.source = source

    @property
    def ts_event(self) -> int:
        return self._ts_event

    @property
    def ts_init(self) -> int:
        return self._ts_init

    @property
    def surprise(self) -> float | None:
        """Actual minus forecast, once both are numbers. The tradable part."""
        if self.actual is None or self.forecast is None:
            return None
        return self.actual - self.forecast

    @property
    def embargoed(self) -> bool:
        """Should a strategy stand aside for this one?

        High importance only. A low-importance release moves nothing and
        standing aside for every calendar entry is standing aside always -
        which is a strategy, just not the one anybody chose.
        """
        return self.importance is Importance.HIGH

    def __repr__(self) -> str:
        shown = self.actual if self.stage is Stage.RELEASED else self.forecast
        return (
            f"CalendarEvent({self.country} {self.title!r} {self.stage.value} "
            f"{self.importance.value} value={shown!r})"
        )


class MacroObservation(Data):
    """One value of a macro series - FRED, IMF, COT.

    Separate from `CalendarEvent` because the shape differs where it matters:
    an observation has a *period* it describes and a *date it was published*,
    and those are weeks apart. The publication date is `ts_event`, because
    that is when it could have been acted on; the period is carried as a
    field.

    **`difference-before-aligning` is the trap next door.** Aligning two
    series on common timestamps and differencing afterwards makes every gap a
    fake one-period change, and macro series are mostly gaps.
    """

    def __init__(
        self,
        *,
        series: str,
        value: float,
        period: str,
        ts_event: int,
        ts_init: int,
        unit: str = "",
        source: str = "",
    ) -> None:
        self._ts_event = ts_event
        self._ts_init = ts_init
        self.series = series
        self.value = value
        self.period = period
        self.unit = unit
        self.source = source

    @property
    def ts_event(self) -> int:
        return self._ts_event

    @property
    def ts_init(self) -> int:
        return self._ts_init

    def __repr__(self) -> str:
        return f"MacroObservation({self.series} {self.period} = {self.value}{self.unit})"
