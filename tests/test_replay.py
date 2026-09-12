"""The forward walk, and the two look-aheads it exists to make impossible.

Every test here pins a specific failure that actually happened on 2026-09-11
rather than a behaviour in general. The reason they live in `tests/` and not
beside the harness is the whole point of the module: `pyproject.toml` excludes
`research` from ruff and pytest's `testpaths` is `tests` alone, so the code that
produced this project's conclusions was the only code in the repo with no lint
gate and no test gate. A forward walk is not a scratch script - it is the
function that decides what ships.
"""

import inspect

import pytest

from till_infinity.shared.replay import walk

#: `(ts, open, high, low, close)` - the open is load-bearing, see `test_a_bar_...`
FLAT = [(float(i), 100.0, 100.0, 100.0, 100.0) for i in range(50)]


def trade(**over):
    """A long at 100 with a 1.0v stop, one volatility unit being 1.0 of price."""
    got = {
        "up": True,
        "level": 100.0,
        "unit": 1.0,
        "risk_vol": 1.0,
        "push_vol": 1.0,
        "context": {},
    }
    got.update(over)
    return got


def bars(*rows):
    """`(open, high, low, close)` tuples, stamped in order."""
    return [(float(i), *row) for i, row in enumerate(rows)]


def test_a_peak_during_a_suspended_stop_cannot_be_booked_after_it():
    """**This is the +1.335R result as an assertion.**

    A policy that suspends the stop for a grace window must suspend the stop's
    *movement* too. Letting the trail tighten while forbidding it to fire means
    the exit at the end of the window books a price the market has already
    passed through and left - it reads as a profit taken at the high-water mark
    rather than at what was actually on offer.

    Price runs to 110 during the window and is back at 100 when the window
    ends. A trail that tightened through the window sits near 109.5; the honest
    answer is that nothing above 100 was available once the stop could fire.
    """
    rows = bars(
        (100.0, 110.0, 100.0, 110.0),  # bar 0: runs to 110 - stop suspended
        (110.0, 110.0, 100.0, 100.0),  # bar 1: back to 100 - stop suspended
        (100.0, 100.0, 100.0, 100.0),  # bar 2: the stop may fire from here
        *[(100.0, 100.0, 100.0, 100.0)] * 10,
    )
    got = walk(rows, 0, trade(), cost=0.0, hold=len(rows), policy={"grace": 2})

    assert got is not None
    r, _kind = got
    assert r < 5.0, "a 9.5R exit here is the trail booking a price it never saw"
    assert r == pytest.approx(0.0, abs=0.01), "price was at entry when the stop armed"


def test_a_bar_that_opens_through_the_stop_fills_at_the_open():
    """Filling at the stop pays the trade a price the market never offered.

    Invisible when the stop trails just behind price, and enormous when a bar
    gaps. Built so the two answers differ by a wide margin - a fixture where
    they nearly agree would pass while broken.
    """
    rows = bars(
        (100.0, 100.0, 100.0, 100.0),
        (90.0, 90.0, 89.0, 89.0),  # opens at 90, ten units through a stop at 99
        *[(89.0, 89.0, 89.0, 89.0)] * 5,
    )
    got = walk(rows, 0, trade(), cost=0.0, hold=len(rows), policy={"trail_vol": 0.0})

    assert got is not None
    r, kind = got
    assert kind == "stop"
    # Stop sits at 99 (entry 100, risk 1.0). The open is 90, so the fill is -10R.
    assert r == pytest.approx(-10.0, abs=0.01), "filled at the stop, not the open"


def test_the_trail_does_not_move_on_a_bar_it_is_allowed_to_fill_on():
    """The order of prices within a bar is not knowable from OHLC.

    So the only honest sequence is to test the levels that were resting when the
    bar opened, and only then let that bar's extreme move them for the next one.
    Raising the trail on a bar's own high and filling on the same bar protects
    the trade with information it did not have.

    One bar reaches 105 and returns to 100. A trail computed from that bar's own
    high would sit at 104.5 and fill on the same bar's low.
    """
    rows = bars(
        (100.0, 105.0, 100.0, 100.0),  # high 105 and low 100, in unknown order
        *[(100.0, 100.0, 100.0, 100.0)] * 8,
    )
    got = walk(rows, 0, trade(), cost=0.0, hold=len(rows), policy={"trail_vol": 0.5})

    assert got is not None
    r, _kind = got
    assert r < 4.0, "a 4.5R exit is the trail filling on the bar that set it"


def test_cost_and_hold_have_no_defaults():
    """Both are modelling choices, and a default is how a modelling choice stops
    being a decision.

    Four of 103 harnesses charged a spread; charging zero moved a replayed
    population from -0.015R to +0.348R. And one harness held trades for 1,440
    bars while the live desk holds for 30 - a 48x error that was invisible
    because it sat in a module constant.

    Asserted on the signature rather than by catching `TypeError`, because the
    guarantee is that nobody can add `cost: float = 0.0` later without this
    failing and saying so.
    """
    signature = inspect.signature(walk)
    for name in ("cost", "hold"):
        assert signature.parameters[name].default is inspect.Parameter.empty
        assert signature.parameters[name].kind is inspect.Parameter.KEYWORD_ONLY


def test_the_spread_changes_the_answer():
    """The behavioural half of the rule above."""
    rows = bars(*[(100.0, 101.0, 99.5, 100.0)] * 20)
    free = walk(rows, 0, trade(), cost=0.0, hold=len(rows), policy={})
    charged = walk(rows, 0, trade(), cost=0.2, hold=len(rows), policy={})

    assert free is not None
    assert charged is not None
    assert charged[0] < free[0], "a round trip has to pay one spread"


def test_a_stop_and_a_target_in_one_bar_resolve_as_the_stop():
    """The worse order within the bar, which is what `exits.py` already assumed
    and what a replay has no way to know."""
    rows = bars(
        (100.0, 130.0, 90.0, 100.0),  # reaches the target and the stop
        *[(100.0, 100.0, 100.0, 100.0)] * 5,
    )
    got = walk(rows, 0, trade(), cost=0.0, hold=len(rows), policy={"trail_vol": 0.0})

    assert got is not None
    assert got[1] == "stop"


def test_a_walk_with_no_room_left_returns_nothing():
    """A trade that starts past the end of the bars is not a zero, it is an
    absence - and scoring it as a zero is how a replay quietly gains a
    population of flat trades it never made."""
    assert walk(FLAT, len(FLAT), trade(), cost=0.0, hold=30, policy={}) is None


def test_an_unpriceable_trade_returns_nothing():
    """No volatility unit means no R, because R is denominated in it."""
    assert walk(FLAT, 0, trade(unit=0.0), cost=0.0, hold=30, policy={}) is None
    assert walk(FLAT, 0, trade(push_vol=0.0), cost=0.0, hold=30, policy={}) is None


def test_the_characterisation_fixture_still_says_what_it_said():
    """A fixed fixture with the answer recorded, so a later edit that changes
    the arithmetic has to change this test and say so. Correctness is not what
    this pins - agreement with the version that was reasoned about is."""
    rows = bars(
        (100.0, 102.0, 99.8, 101.5),
        (101.5, 103.0, 101.0, 102.5),
        (102.5, 103.5, 101.8, 102.0),
        (102.0, 102.5, 100.5, 100.8),
        (100.8, 101.0, 99.0, 99.2),
        *[(99.2, 99.5, 98.8, 99.0)] * 6,
    )
    got = walk(rows, 0, trade(), cost=0.05, hold=len(rows), policy={})

    assert got is not None
    r, kind = got
    assert kind == "stop"

    # Traced by hand rather than recorded from a run, so this argues back when
    # the arithmetic changes instead of agreeing with whatever it now does:
    #
    #   half  = 0.05 / 2 = 0.025      entry = 100.025      risk = 1.0
    #   stop  = 99.025               target = 106.025
    #
    #   bar 0  no exit. best -> 102.0, gained 1.975R
    #          protect at 1R moves the stop to break even, 100.025
    #          the 0.5v trail then pulls it to 102.0 - 0.5 = 101.5
    #   bar 1  opens 101.5, low 101.0. The stop at 101.5 is touched, and the
    #          bar opened exactly on it, so rules 2 and 1 agree: fill at 101.5
    #
    #   exit 101.5 - 0.025 = 101.475, and (101.475 - 100.025) / 1.0 = 1.45
    assert r == pytest.approx(1.45, abs=0.001)


# ---------------------------------------------------- rule 3, and declining it


#: A bar that touches both barriers. The trade is a long at 100 with a 1.0 stop,
#: so the stop rests at 99; `target_mult` 1.0 on a 1.0v push puts the target at
#: 101. This bar opens at 100 and reaches both.
BOTH = (100.0, 101.5, 98.5, 100.0)
TIGHT = {"target_mult": 1.0}


def test_rule_three_still_says_stop_by_default():
    """The convention is kept as the default so an existing result reproduces.

    Changing it silently would restate every conclusion this kernel has already
    produced without saying which moved.
    """
    got = walk(bars(BOTH), 0, trade(), cost=0.0, hold=5, policy=TIGHT)
    assert got is not None
    assert got[1] == "stop"
    assert got[0] == pytest.approx(-1.0)


def test_an_ambiguous_bar_can_return_the_expected_r_instead_of_a_guess():
    """`always stop` is 0.47-0.68 accurate and 0.415 on btc - worse than a coin.

    Because it always says the same thing its error is a one-sided bias rather
    than noise, worth -9 to -44 points of risk per resolved trade, against a
    largest strategy-table claim of 34 points. The weighted value is not a
    better guess at which barrier came first; it is a refusal to guess, and over
    many trades it is unbiased where a guess is not.
    """
    got = walk(bars(BOTH), 0, trade(), cost=0.0, hold=5, policy=TIGHT, ambiguous="expected")
    assert got is not None
    assert got[1] == "both", "the exit kind says the bar was ambiguous"
    # Strictly between the two outcomes it is refusing to choose between.
    assert -1.0 < got[0] < 1.0


def test_a_bar_opening_midway_between_the_barriers_is_a_coin():
    """The property that makes this a refusal rather than a different guess: it
    cannot manufacture a direction the bar does not contain."""
    from till_infinity.shared.replay import _first_target

    assert _first_target(100.0, 99.0, 101.0, 101.5, 98.5) == pytest.approx(0.5)
    # And an open sitting on one barrier leans towards it.
    assert _first_target(99.1, 99.0, 101.0, 101.5, 98.5) < 0.5
    assert _first_target(100.9, 99.0, 101.0, 101.5, 98.5) > 0.5


def test_the_weighting_leans_towards_the_nearer_barrier():
    """An open next to the stop should resolve mostly as a stop, and the
    expected R should sit near -1 rather than in the middle."""
    near_stop = walk(
        bars((99.1, 101.5, 98.5, 99.1)),
        0,
        trade(),
        cost=0.0,
        hold=5,
        policy=TIGHT,
        ambiguous="expected",
    )
    near_target = walk(
        bars((100.9, 101.5, 98.5, 100.9)),
        0,
        trade(),
        cost=0.0,
        hold=5,
        policy=TIGHT,
        ambiguous="expected",
    )
    assert near_stop is not None
    assert near_target is not None
    assert near_stop[0] < near_target[0]


def test_a_fresh_entry_is_never_ambiguous_at_the_default_target():
    """Rule 3 costs a fresh entry nothing - measured at 0.00% of bars on every
    feed at `target_mult` 6.0, which is this module's own default. It binds once
    the stop has trailed up near price, which is where every winner ends up."""
    rows = bars((100.0, 101.5, 98.5, 100.0), *[(100.0, 100.0, 100.0, 100.0)] * 5)
    default = walk(rows, 0, trade(), cost=0.0, hold=6, policy={})
    weighted = walk(rows, 0, trade(), cost=0.0, hold=6, policy={}, ambiguous="expected")
    assert default == weighted, "no bar is ambiguous, so the setting cannot matter"


def test_the_shift_here_is_the_one_trading_derives():
    """`shared` sits under `trading` and must not import upwards, so the constant
    is duplicated. This is what stops the copies drifting apart."""
    from till_infinity.shared import replay as shared_replay
    from till_infinity.trading import barriers

    assert shared_replay.SHIFT == barriers.SHIFT


def test_close_only_replays_are_never_ambiguous():
    """A close-only walk sees one price a bar, so no bar can touch both."""
    got = walk(
        bars(BOTH),
        0,
        trade(),
        cost=0.0,
        hold=5,
        policy={**TIGHT, "close_only": True},
        ambiguous="expected",
    )
    assert got is not None
    assert got[1] != "both"
