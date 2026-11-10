"""Graded candles: that the grades are relative, and that the level is checked.

**Written before anything trades on it.** `indicators/__init__` records that
two of Nautilus's indicators are arithmetically wrong and the rest sound - and
`fuzzy_candlesticks` had never been exercised in this repository, where it sat
in `FRAMEWORK` with exactly one reference, its own registration. An unverified
third wrong one would surface as a rule that fires at the wrong rate, which
looks exactly like a market.

The load-bearing test is `test_the_same_bar_grades_differently_in_two_windows`.
Everything this module claims over `candles.py`'s fixed fractions rests on the
grading being **window-relative**; if it were not, the claim is false and the
module is a slower way to spell `TAIL_SHARE`.
"""

from __future__ import annotations

from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.objects import Price, Quantity

from till_infinity.indicators.fuzzy import (
    BODY_MEDIUM,
    PERIOD,
    WICK_LARGE,
    WICK_SMALL,
    FuzzyCandles,
    Grade,
    grade_window,
    graded_at,
    pin,
)

BAR_TYPE = BarType.from_str("EURUSD.SIM-1-HOUR-LAST-EXTERNAL")


def bar(open_: float, high: float, low: float, close: float, ts: int = 0) -> Bar:
    return Bar(
        BAR_TYPE,
        Price(open_, 5),
        Price(high, 5),
        Price(low, 5),
        Price(close, 5),
        Quantity(100, 0),
        ts_event=ts,
        ts_init=ts,
    )


def feed(rows: list[tuple[float, float, float, float]]) -> FuzzyCandles:
    """A warmed indicator fed `rows` in order."""
    found = FuzzyCandles()
    for i, (o, h, low, c) in enumerate(rows):
        found.handle_bar(bar(o, h, low, c, ts=i))
    return found


#: A quiet bar: small range, body most of it, negligible wicks. Repeated, it is
#: the window against which a later bar is judged.
QUIET = (1.1000, 1.1010, 1.0990, 1.1008)

#: A hammer: long lower wick, small body at the top, almost no upper wick.
HAMMER = (1.1000, 1.1012, 1.0900, 1.1008)


# --------------------------------------------- the claim the module rests on


def test_the_same_bar_grades_differently_in_two_windows():
    """**The whole argument for this module over a fixed fraction.**

    A grade is "long for this market lately", so the identical bar must read
    differently against a quiet window and against a wild one. If it did not,
    the grading would be a fixed fraction wearing an ordinal's clothes, and
    `candles.TAIL_SHARE` would already do the job more cheaply.
    """
    quiet = feed([QUIET] * PERIOD + [HAMMER])
    # A window whose bars already have long lower wicks of their own, so the
    # same hammer is unremarkable in it.
    wild = feed([(1.1000, 1.1012, 1.0900, 1.1008)] * PERIOD + [HAMMER])

    assert quiet.grade is not None
    assert wild.grade is not None
    assert quiet.grade.lower > wild.grade.lower, (
        f"the hammer graded {quiet.grade.lower} against quiet bars and "
        f"{wild.grade.lower} against wicky ones - the grading is not relative "
        f"to its window, so this module's premise is wrong"
    )


def test_a_long_lower_wick_on_a_small_body_grades_as_one():
    """The direction of the reading, not only its relativity: a hammer must
    grade its *lower* wick large and its body small, or `pin` is reading the
    wrong field and would fire on shooting stars."""
    got = feed([QUIET] * PERIOD + [HAMMER]).grade
    assert got is not None
    assert got.lower >= WICK_LARGE, f"lower wick graded {got.lower}"
    assert got.upper <= WICK_SMALL, f"upper wick graded {got.upper}"
    assert got.body <= BODY_MEDIUM, f"body graded {got.body}"
    assert got.direction == 1, "closed above its open"


# ------------------------------------------------------------------ `pin`


def test_a_pin_bar_is_read_from_the_wick_that_would_have_rejected():
    """A trade wanting **up** is rejected from below, so its tail is the lower
    wick. Naming this for the trade rather than the wick is the inversion that
    reads identically at the call site and means the opposite."""
    hammer = Grade(direction=1, size=4, body=1, upper=0, lower=3)
    assert pin(hammer, want_up=True) is True
    assert pin(hammer, want_up=False) is False

    star = Grade(direction=-1, size=4, body=1, upper=3, lower=0)
    assert pin(star, want_up=False) is True
    assert pin(star, want_up=True) is False


def test_a_bar_rejected_from_both_sides_is_indecision_and_not_a_pin():
    """**The guard most easily left out.** A long tail *and* a long opposing
    wick is a bar the market pushed back on from both directions.
    `candles.STUB_SHARE` is the fixed-fraction form of the same check, and
    without it a wide indecisive bar counts as a signal in both directions."""
    both = Grade(direction=1, size=5, body=1, upper=3, lower=3)
    assert pin(both, want_up=True) is False
    assert pin(both, want_up=False) is False


def test_a_bar_that_is_itself_the_move_is_not_a_rejection():
    """`BODY_TREND` is the graded form of "this bar was the move", which is the
    opposite shape to a rejection - the same distinction `smc-conjunctions.md`
    measured between an engulf and a displacement origin."""
    trend = Grade(direction=1, size=5, body=4, upper=0, lower=3)
    assert pin(trend, want_up=True) is False


def test_a_doji_cannot_reject_in_a_direction_it_does_not_have():
    """With no direction there is no side for the rejection to be on, and every
    wick ratio is trivially satisfied when the body is near zero - which is why
    `candles.DOJI` exists as a floor there and a direction check here."""
    assert pin(Grade(direction=0, size=3, body=0, upper=0, lower=3), want_up=True) is False


def test_the_grades_a_pin_demands_can_be_swept_because_the_source_names_none():
    """The price-action sources state **no tail-to-body ratio**, so these are
    ordinals and the sweep is four values rather than a continuum. The control:
    loosening the tail grade admits a bar the default refuses, so the defaults
    are a choice this module made and not the only reading."""
    medium = Grade(direction=1, size=3, body=1, upper=0, lower=2)
    assert pin(medium, want_up=True) is False, "the default demands a large tail"
    assert pin(medium, want_up=True, tail=2) is True, "and a looser sweep admits it"


# ------------------------------------------------------- the level is ours


def test_a_wick_that_pierces_a_level_and_closes_through_it_is_not_a_rejection():
    """**The check most easily left out and the most important.** A hammer
    whose tail pierces support and whose close is still below it is support
    *breaking*, not support holding. `pin` never consults the level at all, so
    this has to be enforced where the two are joined."""
    # Closes below the level it pierced.
    through = feed([QUIET] * PERIOD + [(1.1000, 1.1012, 1.0900, 1.0950)])
    assert through.rejection(1.0980, want_up=True) == ""

    # Same pierce, closing back above it.
    held = feed([QUIET] * PERIOD + [(1.1000, 1.1012, 1.0900, 1.1008)])
    assert held.rejection(1.0980, want_up=True) == "pin"


def test_a_bar_that_never_reached_the_level_confirms_nothing():
    """The control for the test above: the rejection is refused for the right
    reason, not because this always returns empty."""
    got = feed([QUIET] * PERIOD + [HAMMER])
    assert got.rejection(1.0500, want_up=True) == "", "never traded there"
    assert got.rejection(1.0980, want_up=True) == "pin", "and does confirm where it did"


# ----------------------------------------------------- warm-up and research


def test_a_reading_needs_both_the_grader_and_a_pair_of_bars():
    """The grader initialises after `period` bars and `candles.confirms` needs
    the bar before. Reporting initialised on one of them would answer
    `rejection` with a grade and no pattern, or the reverse."""
    short = feed([QUIET] * (PERIOD - 1))
    assert short.initialized is False
    assert short.grade is None
    assert short.features() == {}
    assert short.rejection(1.1000, want_up=True) == ""

    warm = feed([QUIET] * PERIOD)
    assert warm.initialized is True
    assert warm.grade is not None


def test_the_research_path_grades_the_same_bar_the_live_one_does():
    """**A harness with its own copy of the grading would measure a different
    rule from the one that trades**, which is the single failure this
    repository's whole structure argues against. `grade_window` drives the
    framework's own `update_raw`, so the two cannot diverge - asserted rather
    than assumed."""
    rows = [QUIET] * PERIOD + [HAMMER]
    assert grade_window(rows) == feed(rows).grade


def test_the_research_path_refuses_a_window_shorter_than_its_period():
    """The grades are relative to the window, so a short window gives a reading
    whose scale is not the one a result would be quoted in. None, not a grade
    computed from fewer bars."""
    assert grade_window([QUIET] * (PERIOD - 1)) is None


def test_the_features_are_the_framework_s_own_enum_values_unrescaled():
    """A rescaled ordinal is a number whose provenance a result cannot state.
    `Intent.features` is `dict[str, float]`, so these are floats of the enum
    values and nothing else."""
    got = feed([QUIET] * PERIOD + [HAMMER])
    features = got.features()
    assert set(features) == {
        "fuzzy_direction",
        "fuzzy_size",
        "fuzzy_body",
        "fuzzy_upper_wick",
        "fuzzy_lower_wick",
    }
    grade = got.grade
    assert grade is not None
    assert features["fuzzy_lower_wick"] == float(grade.lower)
    assert features["fuzzy_direction"] == float(grade.direction)
    assert all(isinstance(v, float) for v in features.values())


def test_a_reset_leaves_it_as_if_it_had_seen_nothing():
    got = feed([QUIET] * PERIOD + [HAMMER])
    assert got.initialized
    got.reset()
    assert got.initialized is False
    assert got.has_inputs is False
    assert got.grade is None
    assert got.features() == {}


def test_it_is_registered_under_a_name_a_config_can_carry():
    """`FRAMEWORK`'s own `fuzzy` entry had one reference in the repository - its
    registration - so this one is asserted reachable the way a desk reaches it."""
    from till_infinity.indicators import BAR_DETECTORS, build_detector

    assert "fuzzy_candles" in BAR_DETECTORS
    assert isinstance(build_detector("fuzzy_candles"), FuzzyCandles)


# ------------------------------------- combined with the level nominators


def turning(n: int, *, seed: int = 5, start: float = 1.1000, step: float = 0.0004):
    """A seeded random walk, as OHLC rows. **Not a drift, and that matters.**

    `test_indicators.py` records the cost of getting this wrong: a drift large
    enough to be a trend has no bar that is the strict extreme of its own
    neighbourhood, so a pivot detector finds nothing and the test reads as a
    broken composition rather than as an unsuitable fixture. A walk has local
    extremes at every window length. Seeded, so a failure is reproducible.
    """
    import random

    rng = random.Random(seed)
    rows = []
    price = start
    for _ in range(n):
        price += rng.gauss(0.0, step)
        high = price + abs(rng.gauss(0.0, step / 2))
        low = price - abs(rng.gauss(0.0, step / 2))
        rows.append((price, high, low, price))
    return rows


def test_a_graded_rejection_can_be_asked_at_a_bjorgum_zone():
    """**Theirs for how big, a nominator for where.** `BjorgumLevels` says
    which prices are zones and carries no opinion about the candle that
    arrives; `FuzzyCandles` grades the candle and carries no opinion about the
    price. `graded_at` is the join, and it takes plain floats so the same
    grading serves every nominator in `delivering.md`'s table.
    """
    from till_infinity.indicators.levels import BjorgumLevels

    levels = BjorgumLevels.measured()
    fuzzy = FuzzyCandles()
    found: list[tuple[float, str]] = []
    for i, (o, h, low, c) in enumerate(turning(400)):
        candle = bar(o, h, low, c, ts=i)
        levels.handle_bar(candle)
        fuzzy.handle_bar(candle)
        if fuzzy.initialized and levels.zones:
            found += graded_at(fuzzy, [zone.level for zone in levels.zones], want_up=False)

    assert fuzzy.initialized, "the grader never warmed, so this pins nothing"
    assert levels.zones, "no zone was nominated, so the composition is untested here"
    # **Accumulated over the run, not read off the final bar.** Inspecting only
    # the last bar would let this pass with the loop body never executing,
    # which is the vacuous shape CLAUDE.md refuses - a test that cannot fail
    # for its own reason is worse than none.
    assert found, (
        "the join was never exercised: zones were nominated and the grader was "
        "warm, and not one bar produced a graded rejection at any of them"
    )
    for _level, shape in found:
        assert shape in {"pin", "hammer", "shooting-star", "engulfing"}, shape

    # **A rate on a walk is mechanical and is not evidence of anything.** This
    # pins that the composition is wired, not that it finds something real;
    # `null-structure-claims-on-the-same-detector` is why the two are not the
    # same test, and the measurement belongs in research/ with its own nulls.


def test_a_graded_rejection_can_be_asked_at_a_displacement_origin():
    """The same join against the other nominator, which is the point: an order
    block, a displacement origin and a Bjorgum level are one hypothesis with
    several detectors, so a result at one has to be comparable with a result at
    another. A `graded_at` that imported either type could not do that.

    **The return is constructed rather than waited for.** A walk that happened
    to come back to the origin and happened to print a graded rejection there
    would make this a test about the walk - and the first version of it did
    exactly that and failed, because `Displacement`'s window is `SPAN` bars and
    the chain scrolls out of it. What is under test is the composition, so the
    level comes from the real detector and the bar that visits it is placed.
    """
    from till_infinity.indicators.levels import Displacement

    displacement = Displacement()
    rows = [QUIET] * 12 + [
        (1.1000, 1.1060, 1.0998, 1.1055),
        (1.1055, 1.1115, 1.1053, 1.1110),
        (1.1110, 1.1170, 1.1108, 1.1165),
    ]
    for i, (o, h, low, c) in enumerate(rows):
        displacement.handle_bar(bar(o, h, low, c, ts=i))

    assert displacement.initialized
    assert displacement.origins, "no origin was nominated, so this pins nothing"
    line = displacement.origins[0].line

    # A quiet window around the nominated price, then a hammer that pierces it
    # and closes back above. The grades are window-relative, so the window has
    # to be quiet for the tail to grade large.
    tick = 0.0002
    window = [(line, line + tick, line - tick, line + tick / 2)] * PERIOD
    hammer = (line, line + 2 * tick, line - 20 * tick, line + tick)
    fuzzy = feed([*window, hammer])

    assert fuzzy.initialized
    got = graded_at(fuzzy, [line], want_up=True)
    assert got == [(line, "pin")], (
        f"the origin at {line} was nominated by the real detector and the bar "
        f"placed at it graded {fuzzy.card()}, yet the join reported {got}"
    )


def test_the_graded_pin_refuses_a_doji_that_the_fixed_fraction_hammer_accepts():
    """**The two readings genuinely differ, and here is where.**

    `candles.hammer` grades by fixed fractions of the range and has no
    direction requirement, so a bar that opens and closes at the same price
    with a long tail is a hammer to it. The graded `pin` refuses it: with no
    direction there is no side for a rejection to be on, and every wick ratio
    is trivially satisfied when the body is near zero - which is the problem
    `candles.DOJI` exists to patch there and the direction check handles here.

    Found by a fixture, not by reasoning: the first version of the test above
    placed a bar whose open equalled its close, and `rejection` returned
    `hammer` where it expected `pin`. Kept as a test because a divergence
    between two readings of the same bar is exactly what a result comparing
    them would turn on.
    """
    tick = 0.0002
    base = 1.1000
    window = [(base, base + tick, base - tick, base + tick / 2)] * PERIOD
    flat = (base + tick, base + 2 * tick, base - 20 * tick, base + tick)
    fuzzy = feed([*window, flat])

    assert fuzzy.grade is not None
    assert fuzzy.grade.direction == 0, "the fixture is not a doji, so this pins nothing"
    assert fuzzy.pin(want_up=True) is False, "a doji has no side to reject on"
    # And `candles` does accept it, which is the divergence rather than a bug
    # in either: a fixed fraction asks a different question.
    assert fuzzy.rejection(base - tick, want_up=True) == "hammer"


def test_the_join_reports_nothing_where_the_bar_never_reached_a_level():
    """**The control.** Without it "it found rejections at zones" is
    indistinguishable from "it reports a rejection at every price it is
    handed", which is the shape of the `0.706 by construction` finding in
    `smc-conjunctions.md` - a filter satisfied by the sampling frame."""
    fuzzy = feed([QUIET] * PERIOD + [HAMMER])
    far = [0.9000, 0.9500, 1.3000]
    assert graded_at(fuzzy, far, want_up=True) == []
    # And it does fire on a level the bar actually traded through, so the empty
    # result above is the level being wrong and not the join being broken.
    assert graded_at(fuzzy, [1.0980], want_up=True) == [(1.0980, "pin")]


def test_one_bar_can_reject_at_several_nominated_levels_and_all_are_reported():
    """Several zones at one price is not noise - `a-magnet-is-a-shared-reference`
    is that liquidity rests where many participants compute the same price - so
    the count is a reading worth keeping rather than a duplicate to collapse."""
    fuzzy = feed([QUIET] * PERIOD + [HAMMER])
    cluster = [1.0975, 1.0980, 1.0985]
    got = graded_at(fuzzy, cluster, want_up=True)
    assert [level for level, _ in got] == cluster
    assert {shape for _, shape in got} == {"pin"}
