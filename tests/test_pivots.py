"""Session pivots: the arithmetic, the cut, and the look-ahead that is not there.

Three things can go wrong with a pivot set and only one of them is the
formula. The formula is checked against a hand computation because a variant
is easy to half-remember. The **cut** is checked because a boundary shift
moves every level and the FX day a broker rolls is not UTC midnight. And the
**look-ahead** is checked because a set published on the last bar of its own
period is computed from a range that had not finished - which is the same
mistake as reading a swing before its confirmation, and it would not show up
as an error anywhere.

The last group is about what these are *for*. They are the control the swing
book has never had: no parameters, no detector, no fitting. If the Kalman book
does not beat this, the swing detection is not earning its complexity.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from till_infinity.indicators.levels import Sided
from till_infinity.indicators.pivots import (
    NAMES,
    SIDES,
    Pivots,
    Session,
    Sessions,
    day_of,
    levels_from,
    month_of,
    week_of,
)

#: 21:00 UTC, the hour a broker rolls the FX day, and the hour a random walk
#: held across reads +0.61R by survivorship.
BROKER = 21 * 3600.0


def moment(year=2026, month=6, day=10, hour=0, minute=0) -> float:
    return datetime(year, month, day, hour, minute, tzinfo=UTC).timestamp()


def session(high=110.0, low=90.0, close=105.0, period="daily") -> Session:
    return Session(start=0, end=0, high=high, low=low, close=close, period=period)


# -------------------------------------------------------------- the arithmetic


def test_the_classic_set_matches_the_hand_computation():
    """Checked against the arithmetic rather than against a stored table, so
    a transcription error in the expectation cannot agree with one in the
    code. PP is the typical price; R1 and S1 reflect the extremes through it;
    R2 and S2 are a prior range either side."""
    got = levels_from(session())
    pivot = (110.0 + 90.0 + 105.0) / 3.0

    assert got["PP"] == pytest.approx(pivot)
    assert got["R1"] == pytest.approx(2.0 * pivot - 90.0)
    assert got["S1"] == pytest.approx(2.0 * pivot - 110.0)
    assert got["R2"] == pytest.approx(pivot + 20.0)
    assert got["S2"] == pytest.approx(pivot - 20.0)
    assert got["R3"] == pytest.approx(110.0 + 2.0 * (pivot - 90.0))
    assert got["S3"] == pytest.approx(90.0 - 2.0 * (110.0 - pivot))


def test_the_prior_extremes_are_carried_as_levels_of_their_own():
    """Watched more often than the computed pivots and free to carry, so the
    touch statistics can decide which actually matter."""
    got = levels_from(session())
    assert (got["PH"], got["PL"], got["PC"]) == (110.0, 90.0, 105.0)


def test_every_name_is_published():
    assert set(levels_from(session())) == set(NAMES)


def test_the_levels_are_ordered_as_their_names_claim():
    """S3 below S2 below S1 below PP below R1 below R2 below R3. An ordering
    that broke would make "the nearest level above" return something below."""
    got = levels_from(session())
    ladder = [got[n] for n in ("S3", "S2", "S1", "PP", "R1", "R2", "R3")]
    assert ladder == sorted(ladder)


def test_a_flat_period_collapses_r2_and_s2_onto_the_pivot():
    """The degenerate case: a period with no range is a real thing on an
    illiquid feed, and R2 = PP + range has to become PP rather than raise."""
    got = levels_from(session(high=100.0, low=100.0, close=100.0))
    assert got["R2"] == got["S2"] == got["PP"] == pytest.approx(100.0)


def test_the_range_is_never_negative():
    """It is a scale and never a signal, so a reversed high and low must not
    put R2 below the pivot."""
    assert session(high=90.0, low=110.0).width == 0.0


# ---------------------------------------------------------------------- the cut


def test_the_default_cut_is_utc_midnight():
    """A pivot set that shifts with the observer's clock is not the same level
    two people are looking at."""
    assert day_of(moment(hour=12)) == moment(hour=0)
    assert day_of(moment(hour=23, minute=59)) == moment(hour=0)


def test_the_broker_cut_puts_the_late_evening_in_the_next_day():
    """**And this is the one that matters.** The FX day a broker rolls is
    21:00-22:00 UTC, and 21:00 is where a survivorship confound lives - a
    random walk held across it reads +0.61R. The two cuts give different
    sets, so the boundary is a choice to be measured rather than assumed."""
    assert day_of(moment(hour=12), boundary=BROKER) == moment(day=9, hour=21)
    assert day_of(moment(hour=22), boundary=BROKER) == moment(day=10, hour=21)


def test_a_week_starts_on_its_monday():
    """2026-06-10 is a Wednesday."""
    assert datetime.fromtimestamp(moment(), UTC).weekday() == 2
    assert week_of(moment()) == moment(day=8)


def test_a_week_under_the_broker_cut_starts_on_the_sunday_evening():
    """Which is when the FX week actually opens, and is the same instant the
    reconciliation found three trades exiting into."""
    assert week_of(moment(hour=12), boundary=BROKER) == moment(day=7, hour=21)


def test_a_month_starts_on_its_first():
    assert month_of(moment(day=23)) == moment(day=1)


def test_an_unknown_period_is_refused_with_what_it_knows():
    with pytest.raises(ValueError, match="daily, weekly, monthly"):
        Sessions(("fortnightly",))


# -------------------------------------------------------------- the look-ahead


def test_a_period_is_published_only_once_the_next_one_starts():
    """**The look-ahead that is not there.** A period's high is not known
    until the period is over, so a set published on the last bar of its own
    period is computed from an unfinished range - the same mistake as reading
    a swing before its confirmation, and it would show up as an error
    nowhere."""
    found = Pivots(periods=("daily",))
    start = moment()
    for hour in range(0, 24, 6):
        found.update_raw(100.0 + hour, 95.0, 99.0 + hour, start + hour * 3600)

    assert found.published == 0
    assert found.set_for() == {}
    assert found.initialized is False

    found.update_raw(101.0, 99.0, 100.0, start + 86_400 + 60)
    assert found.published == 1
    assert found.initialized is True


def test_the_published_set_uses_the_whole_completed_period():
    """Not only the last bar of it, which is what folding without an
    accumulator would give."""
    found = Pivots(periods=("daily",))
    start = moment()
    for hour, high in enumerate((100.0, 118.0, 104.0)):
        found.update_raw(high, 95.0, high - 1.0, start + hour * 3600)
    found.update_raw(101.0, 99.0, 100.0, start + 86_400 + 60)

    source = found.sources["daily"]
    assert (source.high, source.low) == (118.0, 95.0)
    assert found.price("PH") == 118.0


def test_a_bar_from_before_the_open_period_is_ignored():
    """Out-of-order input would otherwise reopen a period already published
    and silently move a set that had been acted on."""
    found = Pivots(periods=("daily",))
    start = moment()
    found.update_raw(110.0, 90.0, 105.0, start)
    found.update_raw(101.0, 99.0, 100.0, start + 86_400 + 60)
    before = found.set_for()

    found.update_raw(500.0, 1.0, 400.0, start - 86_400)
    assert found.set_for() == before


def test_two_periods_are_kept_apart():
    """A weekly R1 and a daily R1 at the same price are two different claims,
    so merging them would lose which one was being tested."""
    found = Pivots(periods=("daily", "weekly"))
    start = moment(day=8)  # a Monday
    for day in range(9):
        found.update_raw(100.0 + day, 95.0, 99.0 + day, start + day * 86_400)

    assert set(found.sets) == {"daily", "weekly"}
    # The weekly set is computed from seven days and the daily from one, which
    # is the property; the two published periods end at different times, so
    # comparing their highs says nothing.
    weekly, daily = found.sources["weekly"], found.sources["daily"]
    assert weekly.end - weekly.start > daily.end - daily.start
    assert found.set_for("weekly") != found.set_for("daily")


def test_the_period_in_progress_is_reachable_and_not_published():
    """Exposed only so a caller can say how far through a period it is. Using
    it for a pivot is the look-ahead this class exists to prevent."""
    found = Pivots(periods=("daily",))
    found.update_raw(110.0, 90.0, 105.0, moment())
    forming = found.sessions.forming("daily")

    assert forming is not None
    assert forming.high == 110.0
    assert found.set_for() == {}, "nothing published from an unfinished period"


# ----------------------------------------------------------------- the queries


def built() -> Pivots:
    found = Pivots(periods=("daily",))
    start = moment()
    found.update_raw(110.0, 90.0, 105.0, start)
    found.update_raw(101.0, 99.0, 100.0, start + 86_400 + 60)
    return found


def test_the_nearest_level_each_way_carries_its_name():
    """A distance without the name cannot be reviewed later - "price stopped
    at a level" and "price stopped at R2" are different statements."""
    found = built()
    above, below = found.above(102.0), found.below(102.0)

    assert above is not None
    assert below is not None
    assert above[0] == "PC"
    assert above[1] == pytest.approx(105.0)
    assert below[0] == "PP"
    assert below[1] == pytest.approx(101.6667, abs=1e-3)


def test_a_level_exactly_at_the_price_is_neither_above_nor_below():
    """Strictly above and strictly below, so a price sitting on a level does
    not get that level returned as the room to it - which would read as zero
    distance and divide badly downstream."""
    found = built()
    assert found.above(105.0)[0] != "PC"
    assert found.below(105.0)[0] != "PC"


def test_the_room_is_the_reading_these_are_sound_for():
    """A distance rather than a probability, which is the one thing levels
    survived as on this desk."""
    found = built()
    down, up = found.room(102.0)
    assert down == pytest.approx(102.0 - 101.6667, abs=1e-3)
    assert up == pytest.approx(3.0)


def test_the_room_is_none_when_a_wall_is_missing():
    """A room measured against one wall is not the quantity."""
    found = built()
    assert found.room(1_000.0) is None
    assert Pivots().room(100.0) is None


def test_an_unpublished_level_reads_none_rather_than_zero():
    """Zero is a price, and a caller comparing against it would place an
    order at the bottom of the book."""
    assert Pivots().price("R1") is None


def test_a_reset_forgets_the_sets_and_the_open_period():
    """Nautilus resets an indicator on a reconnect, and a book that kept
    yesterday's set through it would publish a level from a period it could no
    longer account for."""
    found = built()
    assert found.published == 1
    found.reset()

    assert found.published == 0
    assert found.set_for() == {}
    assert found.sessions.forming("daily") is None
    assert found.has_inputs is False


def test_registering_it_for_quotes_says_why_not():
    """A quote carries no period high or low, so registering it there would
    leave a book that never published and no indication why."""
    with pytest.raises(NotImplementedError, match="register_indicator_for_bars"):
        Pivots().handle_quote_tick(object())


def test_two_boundaries_are_told_apart_by_the_indicator_identity():
    """Two books cut differently are two different indicators, and this desk
    has already had two modules resolve to one persistence key."""
    assert repr(Pivots()) != repr(Pivots(boundary=BROKER))


# --------------------------------------------------------------- the asymmetry


def test_every_name_has_a_side():
    """A downstream `Sided` parameter has to be applied to something, and a
    name with no side would silently take the neutral branch."""
    assert set(SIDES) == set(NAMES)


def test_the_resistances_and_supports_are_labelled_as_such():
    assert [n for n, s in SIDES.items() if s > 0] == ["R1", "R2", "R3", "PH"]
    assert [n for n, s in SIDES.items() if s < 0] == ["S1", "S2", "S3", "PL"]


def test_the_pivot_and_the_prior_close_have_no_side():
    """The pivot is a midpoint price approaches from either side and the prior
    close is a reference, not a barrier. Handing either a side would make
    `Sided.for_side` return a tilted value for a level that has none."""
    assert SIDES["PP"] == 0
    assert SIDES["PC"] == 0


def test_a_stop_goes_beyond_the_level_on_the_trade_s_own_side():
    """Long, so below the nearest support; short, so above the nearest
    resistance. The level has to break before the stop is reached."""
    found = built()
    name, stop = found.beyond(100.0, +1, unit=1.0, buffer=0.25)
    assert name == "S1"
    assert stop < found.price("S1")

    name, stop = found.beyond(112.0, -1, unit=1.0, buffer=0.25)
    assert name == "R1"
    assert stop > found.price("R1")


def test_the_buffer_may_be_tilted_per_side():
    """Where the asymmetry enters. A tilt of 4 makes the resistance buffer
    twice `shared` and the support buffer half of it, and `Sided` keeps the
    geometric mean at `shared` so switching it on cannot move the average."""
    found = built()
    tilt = Sided(0.25, 4.0)

    _, support = found.beyond(100.0, +1, unit=1.0, buffer=tilt)
    _, resistance = found.beyond(112.0, -1, unit=1.0, buffer=tilt)

    assert found.price("S1") - support == pytest.approx(0.125)
    assert resistance - found.price("R1") == pytest.approx(0.5)


def test_a_tilt_of_one_is_exactly_the_scalar():
    """An asymmetry capability whose neutral setting is not neutral silently
    reparameterises every existing deployment."""
    found = built()
    for price, side in ((100.0, 1), (112.0, -1)):
        assert found.beyond(price, side, unit=1.0, buffer=Sided(0.25, 1.0)) == found.beyond(
            price, side, unit=1.0, buffer=0.25
        )


def test_a_sideless_level_gets_the_neutral_buffer():
    """`PP` has no side, so a tilt must not reach it - otherwise the default
    becomes quietly asymmetric for every level that has no side."""
    found = built()
    flat = found.beyond(102.0, +1, unit=1.0, buffer=Sided(0.25, 1.0))
    tilted = found.beyond(102.0, +1, unit=1.0, buffer=Sided(0.25, 9.0))
    assert flat[0] == "PP"
    assert flat == tilted


def test_a_stop_needs_a_published_level_and_a_unit():
    """`None` rather than a price computed from nothing, because a caller
    would otherwise place an order at it."""
    assert Pivots().beyond(100.0, 1, unit=1.0) is None
    assert built().beyond(100.0, 1, unit=0.0) is None
