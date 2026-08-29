"""Sessions, learned from where bars are.

Written against real observed shapes rather than invented ones: the windows
here are what Wall Street 30, EURUSD and BTCUSD actually reported.
"""

import calendar

from till_infinity.trading.sessions import WEEK, Schedule, Sessions, week_minute

M15 = 15 * 60


def at(day: str, hh: int, mm: int = 0) -> float:
    """A UTC timestamp on a known weekday. 2026-08-24 was a Monday."""
    dates = {
        "Mon": 24,
        "Tue": 25,
        "Wed": 26,
        "Thu": 27,
        "Fri": 28,
        "Sat": 29,
        "Sun": 30,
    }
    return calendar.timegm((2026, 8, dates[day], hh, mm, 0, 0, 0, 0))


def bars(spans: list[tuple[str, int, int]]) -> list[float]:
    """Bar open times covering each (day, from_hour, to_hour) window."""
    out: list[float] = []
    for day, start, end in spans:
        midnight = at(day, 0, 0)
        out.extend(midnight + m * 60 for m in range(start * 60, end * 60, 15))
    return out


def test_the_week_wraps_at_sunday_midnight():
    assert week_minute(at("Mon", 0, 0)) == 0
    assert week_minute(at("Mon", 0, 1)) == 1
    assert week_minute(at("Tue", 0, 0)) == 24 * 60
    assert week_minute(at("Sun", 23, 59)) == WEEK - 1


def test_a_bar_is_evidence_for_every_minute_it_covers():
    """A 15-minute bar says all fifteen minutes traded, not just the first."""
    s = Schedule()
    s.add(at("Mon", 9, 0), M15)
    assert s.trading_at(at("Mon", 9, 0))
    assert s.trading_at(at("Mon", 9, 14))
    assert not s.trading_at(at("Mon", 9, 15))


def test_too_little_evidence_judges_nothing():
    """A handful of bars would otherwise describe a market that trades for an
    hour on Tuesdays and refuse the rest of the week."""
    s = Schedule()
    s.add(at("Tue", 9, 0), M15)
    assert s.known is False
    assert s.closes_in(at("Tue", 9, 0)) is None


def test_the_friday_close_is_found():
    """Wall Street 30's observed shape: Mon-Thu 00:00-21:00 and 22:00-24:00,
    Friday out at 21:00, nothing on Saturday."""
    sessions = Sessions()
    spans = []
    for day in ("Mon", "Tue", "Wed", "Thu"):
        spans += [(day, 0, 21), (day, 22, 24)]
    spans += [("Fri", 0, 21)]
    sessions.learn("Wall Street 30", bars(spans), M15)

    # Thursday afternoon: the daily break is what closes next.
    assert sessions.closes_in("Wall Street 30", at("Thu", 20, 0)) == 60 * 60
    # Friday afternoon: the weekend.
    assert sessions.closes_in("Wall Street 30", at("Fri", 20, 0)) == 60 * 60
    # Friday at five to close.
    assert sessions.closes_in("Wall Street 30", at("Fri", 20, 55)) == 5 * 60


def test_a_shut_market_has_no_time_left():
    sessions = Sessions()
    spans = [(day, 0, 21) for day in ("Mon", "Tue", "Wed", "Thu", "Fri")]
    sessions.learn("Wall Street 30", bars(spans), M15)
    assert sessions.closes_in("Wall Street 30", at("Sat", 12, 0)) == 0.0
    assert sessions.closes_in("Wall Street 30", at("Fri", 21, 30)) == 0.0


def test_an_instrument_that_never_closes_never_closes():
    """BTCUSD trades every day, all day; there is no close to wait for."""
    sessions = Sessions()
    spans = [(d, 0, 24) for d in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")]
    sessions.learn("BTCUSD", bars(spans), M15)
    assert sessions.closes_in("BTCUSD", at("Sat", 3, 0)) is None
    assert sessions.trading_at("BTCUSD", at("Sat", 3, 0)) is True


def test_an_unknown_symbol_is_not_guessed_at():
    """Refusing on absent evidence would stop trading on anything unlearned."""
    sessions = Sessions()
    assert sessions.closes_in("Nothing 500") is None
    assert sessions.trading_at("Nothing 500") is None


def test_a_holiday_does_not_carve_a_hole_in_the_week():
    """The union across weeks, not the intersection. One missing Wednesday
    must not make every Wednesday look shut."""
    sessions = Sessions()
    full = [(d, 0, 21) for d in ("Mon", "Tue", "Wed", "Thu", "Fri")]
    sessions.learn("Wall Street 30", bars(full), M15)
    # A second week that skipped Wednesday entirely.
    missing = [(d, 0, 21) for d in ("Mon", "Tue", "Thu", "Fri")]
    sessions.learn("Wall Street 30", bars(missing), M15)
    assert sessions.trading_at("Wall Street 30", at("Wed", 12, 0)) is True


def test_the_answer_is_never_more_optimistic_than_the_truth():
    """Counted from the start of the current minute, so a trade is never told
    it has longer than it does."""
    sessions = Sessions()
    spans = [(d, 0, 21) for d in ("Mon", "Tue", "Wed", "Thu", "Fri")]
    sessions.learn("Wall Street 30", bars(spans), M15)
    exact = sessions.closes_in("Wall Street 30", at("Fri", 20, 30))
    late = sessions.closes_in("Wall Street 30", at("Fri", 20, 30) + 59)
    assert exact == 30 * 60
    assert late == exact


def test_learned_counts_only_what_can_be_judged():
    sessions = Sessions()
    sessions.learn("Thin", [at("Mon", 9, 0)], M15)
    spans = [(d, 0, 21) for d in ("Mon", "Tue", "Wed", "Thu", "Fri")]
    sessions.learn("Wall Street 30", bars(spans), M15)
    assert sessions.learned == 1
