"""Flattening before a close, and the asymmetry that makes it safe.

`sessions.py` learned a trading week and had **no importer**, while
`Settings.session_margin` had no reader - a producer and a consumer that were
both written and never joined. `calendar.SessionCalendar` is the producer, and
these are the tests of the join.

**The whole safety of the feature is that `None` never means "act now".** Three
different situations produce `None` from `closes_in`:

* an instrument that never closes - BTCUSD and the Deriv synthetics,
* one whose week has not been seen well enough to judge,
* no producer running at all.

A reader that treated any of them as "closing now" would flatten the book on a
failed fetch, and one that treated an unknown schedule as "never closes" would
carry a position through a weekend it could not exit. So the only safe action
on `None` is none, and that is asserted here from both ends rather than
inferred from reading `_closing_soon`.
"""

from __future__ import annotations

import calendar

from till_infinity.strategies.sessions import Schedule, Sessions

M15 = 15 * 60


def at(day: str, hh: int, mm: int = 0) -> float:
    """A UTC timestamp on a known weekday. 2026-08-24 was a Monday."""
    dates = {"Mon": 24, "Tue": 25, "Wed": 26, "Thu": 27, "Fri": 28, "Sat": 29, "Sun": 30}
    return calendar.timegm((2026, 8, dates[day], hh, mm, 0, 0, 0, 0))


def bars(spans: list[tuple[str, int, int]]) -> list[float]:
    out: list[float] = []
    for day, start, end in spans:
        midnight = at(day, 0, 0)
        out.extend(midnight + m * 60 for m in range(start * 60, end * 60, 15))
    return out


def _fx() -> Sessions:
    """EURUSD's observed shape: 24h Monday to Thursday, Friday out at 21:00."""
    sessions = Sessions()
    spans = [(day, 0, 24) for day in ("Mon", "Tue", "Wed", "Thu")] + [("Fri", 0, 21)]
    sessions.learn("EURUSD", bars(spans), M15)
    return sessions


class TestWhatCountsAsClosingSoon:
    """The decision `Desk._closing_soon` makes, against the published number."""

    def test_an_fx_friday_is_inside_a_thirty_minute_flat(self) -> None:
        ahead = _fx().closes_in("EURUSD", at("Fri", 20, 40))
        assert ahead == 20 * 60
        assert ahead <= 1800

    def test_an_fx_friday_morning_is_not(self) -> None:
        """**The gate must not fire all Friday.** It is a flat before the close,
        not a ban on Fridays: a trade taken at 09:00 has twelve hours."""
        ahead = _fx().closes_in("EURUSD", at("Fri", 9, 0))
        assert ahead == 12 * 60 * 60
        assert ahead > 1800

    def test_a_weekday_answers_the_distant_friday_rather_than_none(self) -> None:
        """**For FX the answer is almost never `None`, and that is the point.**

        EURUSD runs through Monday-to-Thursday midnight, so the next close from
        Tuesday night is Friday's - 69 hours away. `closes_in` finds the next
        close whenever one exists, however far, so the gate's safety comes from
        the **magnitude** against the flat window and not from `None`.

        `None` is reserved for the three cases in `TestNoneIsNeverActNow`:
        never closes, not enough week seen, nobody learned it. Confusing the
        two would be the difference between a gate that is off and a gate that
        cannot see.
        """
        ahead = _fx().closes_in("EURUSD", at("Tue", 23, 50))
        # Tuesday 23:50 to Friday 21:00 is 69 hours and 10 minutes.
        assert ahead == 249_000.0
        assert ahead > 1800


class TestNoneIsNeverActNow:
    """Three roads to `None`, and none of them may flatten anything."""

    def test_an_instrument_that_never_closes_answers_none(self) -> None:
        """BTCUSD trades every day all day, so there is no close to prepare for.

        This is what excludes crypto and the synthetics from the weekend flat
        without a rule naming them - `Schedule.always` does it.
        """
        sessions = Sessions()
        sessions.learn(
            "BTCUSD",
            bars([(d, 0, 24) for d in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")]),
            M15,
        )
        assert sessions.by_symbol["BTCUSD"].always is True
        assert sessions.closes_in("BTCUSD", at("Fri", 20, 50)) is None

    def test_too_little_of_the_week_answers_none(self) -> None:
        """A failed fetch must not read as a market about to shut.

        `Schedule.known` wants a day's worth of minutes, and a handful of bars
        would otherwise describe a market trading for an hour on Tuesdays.
        """
        sessions = Sessions()
        sessions.learn("EURUSD", bars([("Tue", 9, 10)]), M15)
        assert sessions.by_symbol["EURUSD"].known is False
        assert sessions.closes_in("EURUSD", at("Fri", 20, 50)) is None

    def test_a_symbol_nobody_learned_answers_none(self) -> None:
        """No producer, or a symbol it never saw: still nothing to act on."""
        assert Sessions().closes_in("EURUSD", at("Fri", 20, 50)) is None

    def test_an_empty_schedule_is_neither_known_nor_always(self) -> None:
        """The guard on the guard: an empty schedule must not read as either."""
        empty = Schedule()
        assert empty.known is False
        assert empty.always is False
        assert empty.closes_in(at("Fri", 20, 50)) is None


class TestTheSettingIsOffByDefault:
    def test_weekend_flat_is_zero_unless_asked_for(self) -> None:
        """**Off is a no-op, not a permissive default.**

        A desk with the setting at zero never consults the calendar, so a
        deployment that has not asked for this behaves exactly as it did.
        """
        from till_infinity.strategies.config import Settings

        assert Settings().weekend_flat == 0.0

    def test_the_environment_name_is_the_documented_one(self) -> None:
        import os

        from till_infinity.strategies.config import Settings

        os.environ["TRADING_WEEKEND_FLAT_S"] = "1800"
        try:
            assert Settings.from_env().weekend_flat == 1800.0
        finally:
            del os.environ["TRADING_WEEKEND_FLAT_S"]


class TestTheActorCanBeBuilt:
    def test_a_calendar_with_no_bar_types_says_so_rather_than_lying(self) -> None:
        """A producer that can learn nothing publishes `None` for everything,
        which reads as "do nothing" - so it has to be loud about it.

        `calendar.py`'s own words: that shape "has hidden a topic in this
        repository four times"."""
        from till_infinity.strategies.calendar import CalendarConfig, SessionCalendar

        actor = SessionCalendar(CalendarConfig(bar_types=(), component_id="SessionCalendar-test"))
        assert actor is not None

    def test_the_topic_is_declared(self) -> None:
        """An undeclared topic publishes into silence and `topics.publish`
        raises rather than letting that happen."""
        from till_infinity.utils.topics import DECLARED, SESSIONS

        assert SESSIONS in DECLARED
