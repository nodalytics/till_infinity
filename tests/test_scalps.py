"""What the scalping harness must get right before any of its numbers mean anything.

`research/harness/scalps.py` reimplements four textbook indicators, a barrier
race and a higher-timeframe context lookup. Every one of those is a place where
an off-by-one produces a plausible number rather than an error, so each is
pinned here against either `nautilus_trader`'s own indicator or a fixture whose
answer is known by construction.

The look-ahead test is the one that earns its place: the first version of
`context()` searched the M15 bars' *opens*, which attaches a bar closing at
10:15 to an execution bar at 10:03 and hands the filter twelve minutes of the
future. It read as a working trend filter.
"""

from __future__ import annotations

import numpy as np
import pytest

from research.harness import scalps


@pytest.fixture
def walk() -> dict[str, np.ndarray]:
    """A 600-bar random walk with wicks, long enough for Wilder recursions to converge."""
    rng = np.random.default_rng(7)
    close = 100.0 + np.cumsum(rng.normal(0.0, 0.3, 600))
    wick = np.abs(rng.normal(0.0, 0.2, 600))
    return {
        "close": close,
        "high": close + wick,
        "low": close - wick,
        "open": np.concatenate(([100.0], close[:-1])),
        "time": np.arange(600, dtype=float) * 60.0,
    }


def test_ema_matches_nautilus(walk):
    """The desk's framework ships this one; ours exists only to run vectorised."""
    from nautilus_trader.indicators.averages import ExponentialMovingAverage

    theirs = ExponentialMovingAverage(9)
    ours = scalps.ema(walk["close"], 9)
    for i, value in enumerate(walk["close"]):
        theirs.update_raw(float(value))
        assert ours[i] == pytest.approx(theirs.value, rel=1e-12)


def test_atr_is_wilders_and_matches_nautilus(walk):
    """Agreement after warmup, not at the seed.

    Wilder's recursion is seeded differently by every implementation and the
    difference decays geometrically, so the claim is that the *recursion* is the
    same. Asserting from bar 0 would pin a seed convention and fail on an
    upstream change that is not a defect.
    """
    from nautilus_trader.indicators.averages import MovingAverageType
    from nautilus_trader.indicators.volatility import AverageTrueRange

    theirs = AverageTrueRange(14, ma_type=MovingAverageType.WILDER)
    ours = scalps.atr(walk["high"], walk["low"], walk["close"])
    for i in range(len(walk["close"])):
        theirs.update_raw(float(walk["high"][i]), float(walk["low"][i]), float(walk["close"][i]))
        if i >= 300:
            assert ours[i] == pytest.approx(theirs.value, rel=1e-6)
    assert np.all(np.isnan(ours[: scalps.ATR_N])), "a stop must not exist before ATR is warm"


def test_rsi_is_wilders_and_matches_nautilus(walk):
    """Ours is Wilder's, and `ma_type` has to be said out loud.

    `RelativeStrengthIndex(4)` defaults to an ordinary exponential average and
    reads **32.1 where Wilder reads 47.4** on the same 600 bars. Both are
    called RSI(4), both look like an RSI, and a rule thresholded at 25 fires at
    a different rate under each - so the default is not a near-enough
    substitute for the indicator the brief names.
    """
    from nautilus_trader.indicators.averages import MovingAverageType
    from nautilus_trader.indicators.momentum import RelativeStrengthIndex

    theirs = RelativeStrengthIndex(4, ma_type=MovingAverageType.WILDER)
    ours = scalps.rsi(walk["close"], 4)
    for i, value in enumerate(walk["close"]):
        theirs.update_raw(float(value))
        if i >= 50:
            assert ours[i] == pytest.approx(theirs.value * 100.0, rel=1e-6)
    assert np.all(np.isnan(ours[: scalps.RSI_N])), "no reading before it is warm"


def test_bollinger_matches_nautilus(walk):
    """Nautilus's bands are fed typical price; ours are fed the close.

    So this pins ours against a close-fed instance of theirs - passing the same
    series to both. A test that fed theirs the typical price and ours the close
    would fail for a reason that is a choice, not a defect.
    """
    from nautilus_trader.indicators.volatility import BollingerBands

    theirs = BollingerBands(20, 2.0)
    mid, lower, upper = scalps.bands(walk["close"])
    for i, value in enumerate(walk["close"]):
        theirs.update_raw(float(value), float(value), float(value))
        if i >= 25:
            assert mid[i] == pytest.approx(theirs.middle, rel=1e-9)
            assert lower[i] == pytest.approx(theirs.lower, rel=1e-9)
            assert upper[i] == pytest.approx(theirs.upper, rel=1e-9)


def test_the_stop_wins_a_bar_that_spans_both_barriers():
    """A bar touching both barriers must lose.

    Resolving the tie the other way is how a 1:2 backtest manufactures an edge,
    and at this geometry the barriers are two ATR apart so the tie is common.
    """
    f = {
        "open": np.array([100.0, 100.0]),
        "high": np.array([100.0, 103.0]),
        "low": np.array([100.0, 98.0]),
        "close": np.array([100.0, 102.0]),
    }
    r, exit_i = scalps.race(f, 1, 1, 1.0, 2.0)
    assert r == -1.0
    assert exit_i == 1


def test_a_clocked_out_trade_is_marked_to_the_close_not_to_zero():
    """A trade that reaches neither barrier is worth where it ended.

    Scoring it zero would quietly delete the drift the hold earned, in either
    direction, and `clocked` in the report exists so a cell that is mostly
    clock-outs cannot be read as a barrier result.
    """
    f = {
        "open": np.array([100.0, 100.0, 100.0]),
        "high": np.array([100.0, 100.2, 100.5]),
        "low": np.array([100.0, 99.8, 99.9]),
        "close": np.array([100.0, 100.1, 100.4]),
    }
    r, exit_i = scalps.race(f, 1, 1, 1.0, 2.0, hold=1)
    assert r == pytest.approx(0.4)
    assert exit_i == 2


def test_book_holds_one_position_at_a_time():
    """A signal inside an open trade is refused, not queued.

    Without this a 1-minute book takes overlapping positions on the same move
    and reports the same information several times, which inflates n and
    narrows every interval.
    """
    n = 60
    f = {
        "open": np.full(n, 100.0),
        "high": np.full(n, 100.05),
        "low": np.full(n, 99.95),
        "close": np.full(n, 100.0),
        "atr": np.full(n, 1.0),
        "time": np.arange(n, dtype=float) * 60.0,
        "mid": np.full(n, 100.0),
    }
    taken = scalps.book(f, np.arange(0, 50), np.ones(50, dtype=int), 0.0)
    assert len(taken) == 2, "flat bars clock out after HOLD, so only two fit in fifty"
    assert taken[1]["i"] > taken[0]["exit"]


def test_context_cannot_see_an_m15_bar_that_has_not_closed():
    """The filter at 10:03 is the 09:45-10:00 reading, never the 10:00-10:15 one."""
    m1 = {
        "time": np.arange(0, 3600, 60, dtype=float),
        "open": np.zeros(60),
        "high": np.zeros(60),
        "low": np.zeros(60),
        "close": np.zeros(60),
    }
    bars = scalps.clock_bars(m1, 3)
    m15 = scalps.clock_bars(m1, 15)
    seen = np.searchsorted(m15["time"] + 900.0, bars["time"], side="right") - 1
    at_1003 = int(np.flatnonzero(bars["time"] == 180.0)[0])
    assert seen[at_1003] == -1, "nothing has closed three minutes into the first M15 bar"
    at_1800 = int(np.flatnonzero(bars["time"] == 1800.0)[0])
    assert m15["time"][seen[at_1800]] == 900.0, "the 15-30 bar is the last one closed at 30"


def test_a_continuously_quoted_series_is_flagged_as_having_no_session():
    """An opening range on a synthetic is a control, and must be labelled one.

    A Deriv synthetic never gaps, so any session boundary imposed on it is a
    midnight this venue does not observe. Reading its ORB as a strategy result
    is the mistake this flag exists to prevent.
    """
    straight = np.arange(0, 86400 * 5, 60, dtype=float)
    _, real = scalps.sessions(straight, straight)
    assert real is False

    gapped = np.concatenate(
        [np.arange(d * 86400, d * 86400 + 8 * 3600, 60, dtype=float) for d in range(5)]
    )
    _, real = scalps.sessions(gapped, gapped)
    assert real is True


def test_both_sides_firing_on_one_bar_is_dropped():
    """A rule that is long and short at once has no direction.

    Picking one would be a choice the rule did not make, and picking the
    profitable one is look-ahead wearing a tie-break's clothes.
    """
    f = {"atr": np.array([1.0, 1.0, 1.0, 1.0, 1.0]), "close": np.zeros(5)}
    up = np.array([True, True, False, False, False])
    down = np.array([True, False, True, False, False])
    index, side = scalps._pair(up, down, f)
    assert index.tolist() == [1, 2]
    assert side.tolist() == [1, -1]


def test_the_planted_windows_cannot_overlap():
    """No bar may receive two plants.

    A plant that compounds across overlapping windows makes every cell
    significant including the unplanted one, which is a defect this repository
    has already published once. Asserted on the series rather than on a mean:
    the largest drift any bar carries is one window's worth.
    """
    n = 200
    f = {
        "open": np.full(n, 100.0),
        "high": np.full(n, 100.0),
        "low": np.full(n, 100.0),
        "close": np.full(n, 100.0),
        "atr": np.full(n, 1.0),
        "time": np.arange(n, dtype=float) * 60.0,
        "mid": np.full(n, 100.0),
    }
    trades = [
        {"entry": 1, "exit": 5, "side": 1, "risk": 1.0, "target_r": 2.0},
        {"entry": 6, "exit": 10, "side": 1, "risk": 1.0, "target_r": 2.0},
        {"entry": 11, "exit": 60, "side": 1, "risk": 1.0, "target_r": 2.0},
    ]
    planted = scalps.plant(f, trades, 0.05)
    drift = planted["close"] - 100.0
    assert drift[5] == pytest.approx(0.05 * 4), "clipped at the next entry, four bars in"
    assert drift[6] == pytest.approx(0.0), "the next window restarts its ramp at zero"
    assert drift.max() == pytest.approx(0.05 * scalps.HOLD, abs=1e-9), "one window, not two"


def test_a_plant_the_harness_can_see_moves_the_mean(walk):
    """Power is only reportable if the plant lands, so the plant is tested too.

    Without this, "the test went blind" and "the plant was never applied" are
    the same output.
    """
    f = dict(walk)
    f["atr"] = scalps.atr(walk["high"], walk["low"], walk["close"])
    f["mid"] = walk["close"]
    index = np.arange(20, 560, 45)
    trades = scalps.book(f, index, np.ones(len(index), dtype=int), 0.0)
    rng = np.random.default_rng(1)
    flat = scalps.summarise(trades, rng)["mean"]
    loud = scalps.planted(f, trades, 0.20, rng)["mean"]
    assert loud > flat + 0.5, "a 0.2R-a-bar drift must show up in the mean R"


def test_the_paired_bootstrap_reads_zero_on_an_arm_against_itself():
    """A difference estimator that cannot read zero cannot read anything.

    `compare` is what decides whether the M15 context filter earns its place,
    so the control is the arm against a copy of itself: the difference must be
    exactly zero and the interval must contain it.
    """
    rng = np.random.default_rng(3)
    trades = [
        {
            "day": d,
            "net": float(v),
            "gross": float(v),
            "target_r": 2.0,
            "cost_r": 0.0,
            "entry": i,
            "exit": i + 1,
        }
        for i, (d, v) in enumerate((d, rng.normal()) for d in range(60) for _ in range(5))
    ]
    same = scalps.compare(trades, list(trades), rng)
    assert same["diff"] == pytest.approx(0.0, abs=1e-12)
    assert same["lo"] <= 0.0 <= same["hi"]
    assert same["p"] == pytest.approx(1.0), "an arm against itself is the least significant result"

    better = [{**t, "net": t["net"] + 0.5} for t in trades]
    moved = scalps.compare(better, trades, rng)
    assert moved["diff"] == pytest.approx(0.5, abs=1e-9)
    assert moved["lo"] > 0.0, "a half-R shift over 300 trades must be visible"


def test_the_difference_is_taken_over_the_union_of_days_not_the_intersection():
    """A filter whose whole effect is skipping days must still be measurable.

    At 15 minutes an opening-range book takes about one trade a day, so on a
    day where both the filtered and the unfiltered arm traded it is the *same*
    trade. An intersection comparison therefore reported `+0.0000` with a
    zero-width interval while the two arms' means differed - the filter's
    entire effect living on the days it refused.
    """
    rng = np.random.default_rng(11)
    full = [
        {
            "day": d,
            "net": -1.0 if d % 2 else 1.0,
            "gross": 0.0,
            "target_r": 2.0,
            "cost_r": 0.0,
            "entry": d,
            "exit": d,
        }
        for d in range(80)
    ]
    kept = [t for t in full if t["day"] % 2 == 0]
    got = scalps.compare(kept, full, rng)
    assert got["days"] == 80, "every day either arm traded"
    assert got["both"] == 40, "and they overlap on only half of them"
    assert got["diff"] == pytest.approx(1.0), "skipping every loser is worth exactly 1R"
    assert got["lo"] > 0.0


def test_a_cell_too_short_for_day_blocks_returns_nothing_rather_than_a_number():
    """Under twenty shared days there is no block bootstrap worth printing.

    Returning `{}` makes the caller skip the line. Returning a number computed
    from four days would print with an interval and read as a measurement.
    """
    trades = [
        {
            "day": d,
            "net": 1.0,
            "gross": 1.0,
            "target_r": 2.0,
            "cost_r": 0.0,
            "entry": d,
            "exit": d + 1,
        }
        for d in range(5)
    ]
    assert scalps.compare(trades, trades, np.random.default_rng(0)) == {}
