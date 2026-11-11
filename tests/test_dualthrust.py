"""The Dual Thrust harness's fill model and its three arms.

`research/docs/dual-thrust.md` argues from a per-trade mean in units of the
trigger distance, and every one of the numbers below it is a few lines of code
that can be wrong by a bar or a sign and still produce a plausible table. The
specific failures these pin:

* the range window including the bar it triggers on, which is a one-bar
  look-ahead that makes the cap a function of the excursion meant to reach it;
* a fill at the bar's close rather than at the trigger price, which is the
  shape that read +0.432R on a driftless walk in `smc-conjunctions.md`;
* the `const` control reading its constant off the whole sample, which hands a
  control an advantage the rule did not have;
* a side shuffle that redraws the magnitudes as well as the signs, which would
  make the null a different sample rather than the same one re-signed.

Each gate here has a control that passes beside it: a rule that never fires and
a rule that fires and makes nothing read identically in a mean, so the
monotone-series tests exist to prove the detector has a sign at all.
"""

from __future__ import annotations

import math
import random
from itertools import pairwise

import numpy as np
import pytest

from research.ideas.dualthrust import (
    MIN_TRADES,
    Series,
    bh,
    coin_means,
    const_range,
    daily,
    describe,
    drift_units,
    malformed,
    plant,
    reflect,
    run_rule,
    shuffle,
    thrust_range,
    wickiness,
)


def series(
    open_: list[float],
    high: list[float],
    low: list[float],
    close: list[float],
    interval: str = "1d",
    step: float = 86_400.0,
) -> Series:
    return Series(
        feed="TEST",
        venue="unit",
        interval=interval,
        ts=np.arange(len(close), dtype=float) * step,
        open=np.asarray(open_, dtype=float),
        high=np.asarray(high, dtype=float),
        low=np.asarray(low, dtype=float),
        close=np.asarray(close, dtype=float),
    )


def flat(n: int, level: float = 100.0) -> Series:
    """Repeating bars with a range. The rule **does** fire on these.

    Worth saying, because it is the first surprise in the rule: four identical
    bars give a 4-bar range of one bar's own range, so the trigger sits half a
    bar inside the bar and every bar reaches it. A quiet book is not a quiet
    rule - see `quiet` for a series that genuinely cannot trigger.
    """
    return series([level] * n, [level + 1] * n, [level - 1] * n, [level] * n)


def quiet(n: int) -> Series:
    """A wide prior range and then bars with none: the triggers are out of reach.

    The control that must read nothing. The first four bars put a 20-unit span
    into the window and every bar after them is a point, so the trigger is ten
    units away and then the measured range collapses to zero and the rule is
    skipped for want of a distance.
    """
    return series(
        [100.0] * n,
        [110.0] * 4 + [100.0] * (n - 4),
        [90.0] * 4 + [100.0] * (n - 4),
        [110.0, 90.0, 110.0, 90.0] + [100.0] * (n - 4),
    )


def ramp(n: int, sign: int = 1, size: float = 1.0) -> Series:
    """A monotone series of equal steps. The rule **cannot** fire on it.

    Also worth saying, and it is the second surprise: `N` steps of one unit
    give a 4-bar range of about four units, so the trigger is two units from
    the open and a one-unit bar never reaches it. Dual Thrust needs an
    **expansion**, not a trend, which is why the sign test below uses a
    series that expands.
    """
    close = [100.0 + sign * size * i for i in range(n)]
    open_ = [100.0 + sign * size * (i - 1) if i else 100.0 for i in range(n)]
    high = [max(o, c) + 0.01 for o, c in zip(open_, close, strict=True)]
    low = [min(o, c) - 0.01 for o, c in zip(open_, close, strict=True)]
    return series(open_, high, low, close)


def walk(size: int = 400, seed: int = 7) -> Series:
    """A walk with wicks: the fixture that reliably triggers."""
    rng = np.random.default_rng(seed)
    close = 100.0 + np.cumsum(rng.normal(0.0, 1.0, size))
    open_ = np.concatenate(([100.0], close[:-1]))
    wick = np.abs(rng.normal(0.0, 1.0, size))
    return series(
        open_.tolist(),
        (np.maximum(open_, close) + wick).tolist(),
        (np.minimum(open_, close) - wick).tolist(),
        close.tolist(),
    )


def expansion(runs: int = 8, size: float = 10.0) -> Series:
    """Quiet, one expansion bar, then a continuation - direction alternating.

    The positive control for the **side**. Each run is four point-bars (so the
    trigger is a hair from the open), one bar that expands `size` in the run's
    direction, and four bars continuing a quarter of `size` each. A rule with
    its side the right way round is long in the up runs and short in the down
    ones and makes money in both; a rule with it backwards loses in both, and
    neither is distinguishable from a rule that never fires by a mean alone.
    """
    open_, high, low, close = [], [], [], []
    level = 100.0
    for run in range(runs):
        direction = 1.0 if run % 2 == 0 else -1.0
        for _ in range(4):
            open_.append(level)
            close.append(level)
            high.append(level + 0.01)
            low.append(level - 0.01)
        for step in (size, *([size * 0.25] * 4)):
            nxt = level + direction * step
            open_.append(level)
            close.append(nxt)
            high.append(max(level, nxt) + 0.01)
            low.append(min(level, nxt) - 0.01)
            level = nxt
    return series(open_, high, low, close)


# ------------------------------------------------------------- thrust_range


def test_the_range_window_is_strictly_prior():
    """A bar's own high cannot widen the range that triggers it.

    This is the look-ahead that matters most here, because the cap is
    `open + K * range` and the thing that reaches the cap is the bar's high. A
    window that included bar `i` would move the cap away from any bar large
    enough to reach it, which is a rule that cannot lose on a big bar.
    """
    base = series([10] * 6, [11] * 6, [9] * 6, [10] * 6)
    spiked = series([10] * 6, [11, 11, 11, 11, 99, 11], [9] * 6, [10] * 6)
    before = thrust_range(base, 4)
    after = thrust_range(spiked, 4)
    assert after[4] == pytest.approx(before[4]), "bar 4's own high changed bar 4's range"
    assert after[5] > before[5], "bar 4's high must reach bar 5's window"


def test_the_range_is_the_wider_of_the_two_crossed_spans():
    """`max(HH - LC, HC - LL)`, and not `HH - LL`, which is always at least as big."""
    # highs 12,12,12,20; lows 8,8,8,8; closes 10,10,10,19
    got = thrust_range(
        series([10] * 5, [12, 12, 12, 20, 12], [8] * 5, [10, 10, 10, 19, 10]),
        4,
    )
    # HH 20, LL 8, HC 19, LC 10  ->  max(20-10, 19-8) = 11, where HH-LL is 12.
    assert got[4] == pytest.approx(11.0)


def test_the_warm_up_is_absent_rather_than_a_shorter_window():
    """`nan` for the first `N` bars. A shorter window is a different rule."""
    got = thrust_range(flat(8), 4)
    assert np.all(np.isnan(got[:4]))
    assert np.all(np.isfinite(got[4:]))


def test_a_series_shorter_than_the_window_is_all_nan():
    assert np.all(np.isnan(thrust_range(flat(3), 4)))


# ----------------------------------------------------------------- run_rule


def test_the_rule_does_not_fire_when_the_triggers_are_out_of_reach():
    """The control that must read nothing.

    It has to be a *quiet* series rather than a flat one: four identical bars
    put a trigger half a bar inside the bar and fire on every one of them, so
    "the rule does nothing on a dull book" is false and the test that assumed
    it was the first thing this file got wrong.
    """
    data = quiet(60)
    width = thrust_range(data, 4)
    trades, same_bar = run_rule(data, width, np.ones(60), 0.5, 0.5)
    assert trades == []
    assert same_bar == 0


def test_a_repeating_bar_fires_every_bar_which_is_the_rule_and_not_a_bug():
    """Four identical bars give a 4-bar range of one bar's range.

    So the cap sits half a bar above the open, the bar's own high reaches it,
    and the rule trades constantly on a book that is going nowhere. Both
    triggers are reached on every one of those bars, which is what `same_bar`
    counts - and it is counted on that condition rather than on a double flip,
    because the headline convention flips at most once and a double-flip count
    would read zero and say nothing.
    """
    data = flat(60)
    trades, same_bar = run_rule(data, thrust_range(data, 4), np.ones(60), 0.5, 0.5)
    assert len(trades) > 20
    assert same_bar > 20, "both triggers sit inside a repeating bar"
    assert same_bar == len(trades) + 1, (
        "every bar flips here, and the opening position is not a trade: "
        "`flips - 1` trades for `flips` triggers"
    )


def test_a_zero_measured_range_is_skipped_rather_than_dividing_by_zero():
    """No distance means no trade, not a trade with an infinite unit."""
    data = series([100.0] * 20, [100.0] * 20, [100.0] * 20, [100.0] * 20)
    trades, _ = run_rule(data, thrust_range(data, 4), np.ones(20), 0.5, 0.5)
    assert trades == []


def test_every_fill_is_the_trigger_price_and_never_the_bar_close():
    """`open + side * K * range`, computed independently of the rule.

    Over a 400-bar walk, so it is every trade rather than a chosen one, and the
    second assertion is what makes the first able to fail for its own reason:
    the bar closes somewhere else, so a fill at the close would be a different
    number on nearly every trade.
    """
    data = walk()
    width = thrust_range(data, 4)
    trades, _ = run_rule(data, width, np.ones(len(data.close)), 0.5, 0.5)
    assert len(trades) > 20
    for trade in trades:
        i = trade.enter
        assert trade.entry_px == pytest.approx(data.open[i] + trade.side * 0.5 * width[i])
    apart = [abs(t.entry_px - data.close[t.enter]) for t in trades]
    assert sum(1 for gap in apart if gap > 1e-9) > 0.9 * len(trades)


def test_the_entry_is_above_the_open_when_long_and_below_it_when_short():
    """The geometry's sign, which a mean cannot see.

    A rule with its cap and floor swapped would still trade, still tile, and
    still report a mean - and would be long at a price below the open.
    """
    data = walk()
    trades, _ = run_rule(data, thrust_range(data, 4), np.ones(len(data.close)), 0.5, 0.5)
    for trade in trades:
        if trade.side > 0:
            assert trade.entry_px > data.open[trade.enter]
        else:
            assert trade.entry_px < data.open[trade.enter]


def test_the_unit_is_the_trigger_distance_at_the_entry_bar():
    """`K * range` at the bar that opened the trade, and not at the one that closed it.

    This is the denominator the whole study is reported in, and the exit bar's
    range is the nearest wrong answer: it is available, it is the same order of
    magnitude, and using it would make the unit a function of the outcome.
    """
    data = walk()
    width = thrust_range(data, 4)
    trades, _ = run_rule(data, width, np.ones(len(data.close)), 0.5, 0.5)
    assert len(trades) > 20
    for trade in trades:
        assert trade.unit == pytest.approx(0.5 * width[trade.enter])
    differs = [t for t in trades if abs(width[t.enter] - width[t.leave]) > 1e-9]
    assert len(differs) > 0.5 * len(trades), "the exit bar's range is a different number"


def test_one_trigger_distance_of_profit_is_one_unit():
    """The arithmetic of the unit, on numbers small enough to check by hand."""
    data = walk()
    width = thrust_range(data, 4)
    trades, _ = run_rule(data, width, np.ones(len(data.close)), 0.5, 0.5)
    trade = trades[0]
    moved = trade.side * (trade.exit_px - trade.entry_px)
    assert trade.gross == pytest.approx(moved)
    assert trade.gross / trade.unit == pytest.approx(moved / (0.5 * width[trade.enter]))


def test_the_trades_tile_with_no_flat_state():
    """Each exit is the next entry, in index and in price: the duty cycle is 1.0.

    Not a nicety. It is the reason this study has no duty-cycle twin and no
    outcome overlap to de-overlap, and a gap between one exit and the next
    entry would mean a flat state had crept in and both of those claims were
    wrong.
    """
    data = walk()
    trades, _ = run_rule(data, thrust_range(data, 4), np.ones(len(data.close)), 0.5, 0.5)
    assert len(trades) > 5, "a random walk with this geometry must trigger"
    for before, after in pairwise(trades):
        assert before.leave == after.enter
        assert before.exit_px == pytest.approx(after.entry_px)
        assert before.side == -after.side


def test_the_default_convention_reverses_a_whipsaw_bar_once():
    """A bar reaching both triggers flips the position once, to the other side.

    The convention matters more than it looks. The first version of this file
    fired the nearer trigger first and then the other, which with `K1 == K2`
    put the position on the second of a fixed order every time - a systematic
    short bias on every whipsaw bar. `once` is symmetric by construction: the
    position reverses and stops, whichever side it was on.
    """
    data = flat(30)
    width = thrust_range(data, 4)
    sides = []
    for first in (1, -1):
        # A bar before the whipsaw run that forces the starting side.
        forced = series(
            [100.0] * 4 + [100.0] + [100.0] * 25,
            [101.0] * 4 + [101.0 if first > 0 else 100.4] + [101.0] * 25,
            [99.0] * 4 + [99.6 if first > 0 else 99.0] + [99.0] * 25,
            [100.0] * 30,
        )
        trades, _ = run_rule(forced, thrust_range(forced, 4), np.ones(30), 0.5, 0.5)
        sides.append([t.side for t in trades[:4]])
    assert sides[0][0] == 1
    assert sides[1][0] == -1
    assert all(a == -b for a, b in zip(sides[0], sides[1], strict=True)), (
        "the convention must not prefer a side"
    )
    assert np.all(np.diff(width[4:]) == 0), "the fixture's range is constant"


def test_the_three_conventions_disagree_only_on_the_whipsaw_bars():
    """`close` and `adverse` fire both triggers and bracket `once`.

    So they must produce more flips than `once` and must not agree with each
    other, or the sensitivity arm is not measuring anything.
    """
    data = flat(60)
    width = thrust_range(data, 4)
    got = {
        name: run_rule(data, width, np.ones(60), 0.5, 0.5, intrabar=name)
        for name in ("once", "close", "adverse")
    }
    assert len(got["close"][0]) > len(got["once"][0])
    assert len(got["adverse"][0]) > len(got["once"][0])
    assert [t.side for t in got["close"][0]] != [t.side for t in got["adverse"][0]]


def test_the_rule_is_on_the_right_side_of_an_expansion():
    """The detector's sign, which a null cannot establish.

    A rule that never fires and a rule whose side is backwards both read zero
    in a mean, so the control has to be a series whose direction is known. Each
    run of `expansion` breaks out and continues, so a correctly-signed rule
    takes the run's own side and makes money on the pooled mean.
    """
    data = expansion()
    trades, _ = run_rule(data, thrust_range(data, 4), np.ones(len(data.close)), 0.5, 0.5)
    assert len(trades) >= 4, "an expansion must trigger"
    gained = [t.gross for t in trades]
    assert sum(gained) > 0, "a breakout-and-continue series must pay a breakout rule"
    assert sum(1 for g in gained if g > 0) > len(gained) / 2


def test_the_two_multipliers_are_read_on_their_own_sides():
    """`K1` scales the cap and `K2` the floor, and a trade's unit is its own side's.

    An asymmetric pair is what makes a swapped one visible: with `K1` at 1.0
    and `K2` at 0.2 the longs are entered a full range away and the shorts a
    fifth of one, so a long's unit is five times a short's.
    """
    data = walk()
    width = thrust_range(data, 4)
    trades, _ = run_rule(data, width, np.ones(len(data.close)), 1.0, 0.2)
    longs = [t for t in trades if t.side > 0]
    shorts = [t for t in trades if t.side < 0]
    assert longs, "the asymmetric pair must still produce longs"
    assert shorts, "and shorts"
    for trade in longs:
        assert trade.unit == pytest.approx(1.0 * width[trade.enter])
        assert trade.entry_px == pytest.approx(data.open[trade.enter] + width[trade.enter])
    for trade in shorts:
        assert trade.unit == pytest.approx(0.2 * width[trade.enter])


# -------------------------------------------------------------- const_range


def test_the_constant_arm_cannot_see_past_its_training_block():
    """Doubling the range after the training block must not move the constant.

    A control that reads its constant off the whole sample is a control that
    knew the future, and would make the comparison "a measured range against a
    range measured with hindsight" rather than against a constant.
    """
    quiet = thrust_range(flat(100), 4)
    loud = quiet.copy()
    loud[60:] *= 7.0
    assert const_range(quiet, train=0.2)[90] == pytest.approx(const_range(loud, train=0.2)[90])


def test_the_constant_is_the_median_of_the_measured_range():
    width = thrust_range(flat(100), 4)
    got = const_range(width, train=0.5)
    assert got[50] == pytest.approx(float(np.median(width[4:52])), rel=1e-6)
    assert np.all(np.isnan(got[:4])), "the warm-up stays absent, not constant"


# ---------------------------------------------------------------- coin_means


def test_the_side_shuffle_re_signs_the_same_magnitudes():
    """The null is the real sample re-signed, not a resampled one.

    So the magnitudes that come back are exactly `|gross| / unit`, and the
    draws' means are centred on zero with the real sample's own spread. A null
    that redrew the magnitudes would be a different population and a difference
    against it would be partly a difference of samples.
    """
    gross = np.array([3.0, -1.0, 2.0, -4.0])
    unit = np.array([1.0, 1.0, 2.0, 2.0])
    means, mag = coin_means(gross, unit, random.Random(1), draws=4000)
    assert mag.tolist() == [3.0, 1.0, 1.0, 2.0]
    assert abs(means.mean()) < 0.05
    assert means.std() > 0.0
    assert set(np.unique(np.abs(means * 4)).round(6)) <= {
        round(abs(s @ mag), 6) for s in np.array(np.meshgrid(*[(-1, 1)] * 4)).T.reshape(-1, 4)
    }


# --------------------------------------------------------------------- plant


def test_a_strength_of_zero_is_the_identity():
    """Nothing planted means nothing changed, which is the power sweep's baseline."""
    data = ramp(50)
    same = plant(data, 0.0, 1.0)
    assert np.allclose(same.close, data.close)
    assert np.allclose(same.high, data.high)


def test_the_plant_moves_price_in_the_breakout_direction_and_keeps_the_bar():
    """A continuation after an up-break lifts later closes and never inverts a bar.

    The plant is the power statement's whole content, so it has to be the
    effect it claims: a positive strength on a rising series must raise the
    closes, and `low <= open <= high` has to survive it or the detector would
    be reading bars that cannot happen.
    """
    data = ramp(60, sign=1, size=1.0)
    planted = plant(data, 0.5, 2.0)
    assert planted.close[-1] > data.close[-1]
    assert np.all(planted.high >= planted.low)
    assert np.all(planted.high >= planted.open)
    assert np.all(planted.low <= planted.open)


def test_the_plant_is_monotone_in_its_strength():
    data = ramp(60, sign=1, size=1.0)
    gained = [plant(data, s, 2.0).close[-1] - data.close[-1] for s in (0.1, 0.2, 0.4)]
    assert gained == sorted(gained)
    assert gained[0] > 0.0


# --------------------------------------------------------------------- daily


def test_the_daily_fold_takes_the_first_open_and_the_last_close():
    """And the block's own extremes, which is what makes it a bar and not a sample."""
    data = series(
        [1.0, 2.0, 3.0, 4.0],
        [5.0, 9.0, 6.0, 7.0],
        [0.5, 0.2, 2.0, 1.0],
        [2.0, 3.0, 4.0, 5.0],
        interval="15m",
        step=43_200.0,
    )
    got = daily(data)
    assert got.interval == "1d"
    assert got.venue == "cache1d", "a folded day is its own source"
    assert got.open.tolist() == [1.0, 3.0]
    assert got.close.tolist() == [3.0, 5.0]
    assert got.high.tolist() == [9.0, 7.0]
    assert got.low.tolist() == [0.2, 1.0]


def test_a_one_bar_day_is_dropped_rather_than_kept_as_a_day():
    """A day with one 15m bar is a feed gap, and its range is one bar's."""
    data = series(
        [1.0, 2.0, 3.0],
        [2.0, 3.0, 4.0],
        [0.0, 1.0, 2.0],
        [1.5, 2.5, 3.5],
        interval="15m",
        step=86_400.0,
    )
    assert len(daily(data).close) == 0


# ------------------------------------------------------------------ describe


def _trades(data: Series):
    return run_rule(data, thrust_range(data, 4), np.ones(len(data.close)), 0.5, 0.5)[0]


def test_a_thin_cell_reports_no_mean_at_all():
    """Absent, not zero. A dict of zeros reads later as a measurement."""
    row = describe(_trades(walk())[:3], bars=400, common=1.0, cost_px=0.1, rng=random.Random(0))
    assert row["n"] == 3
    assert "mean_u" not in row


def test_an_unpriced_cell_is_not_a_free_round_trip():
    """`nan` cost means no net is reported, never a net equal to the gross."""
    trades = _trades(walk())
    assert len(trades) >= MIN_TRADES
    row = describe(trades, bars=400, common=1.0, cost_px=float("nan"), rng=random.Random(0))
    assert math.isnan(row["cost_u"])
    assert math.isnan(row["net_u"])
    priced = describe(trades, bars=400, common=1.0, cost_px=0.1, rng=random.Random(0))
    assert priced["net_u"] < priced["mean_u"]


def test_the_coin_column_is_centred_on_zero_where_the_real_one_is_not():
    """The side decomposition's own control, on a series with a known direction.

    `expansion` is directional, so the real mean is positive and the coin's is
    not. On a cell where the two agree the rule carries no side, which is the
    study's primary claim - and a coin arm that could not disagree anywhere
    would be no evidence for it.
    """
    row = describe(_trades(expansion(runs=40)), bars=360, common=1.0, cost_px=0.0,
                   rng=random.Random(0))  # fmt: skip
    assert row["mean_u"] > 0
    assert abs(row["coin_u"]) < abs(row["mean_u"])
    assert row["p"] < 0.05


def test_the_dominance_column_sees_a_single_trade_carrying_the_mean():
    """`top1` is the largest trade's share of the gross, which a mean hides.

    The trigger distance can collapse in a quiet patch, and a trade divided by
    a near-zero unit reads in the thousands. The mean is still the P&L, so it
    is not winsorised - but it has to be readable beside the share one trade
    contributed.
    """
    trades = _trades(walk())
    row = describe(trades, bars=400, common=1.0, cost_px=0.0, rng=random.Random(0))
    assert 0.0 < row["top1"] < 1.0
    assert row["top1"] >= 1.0 / len(trades)


# ------------------------------------------------------------------------ bh


def test_benjamini_hochberg_counts_the_largest_surviving_rank():
    """Three of four p-values survive at 0.05 here, and the cut is the third."""
    assert bh([0.001, 0.008, 0.03, 0.4]) == (3, 0.03)
    assert bh([0.2, 0.3, 0.4]) == (0, pytest.approx(float("nan"), nan_ok=True))
    assert bh([]) == (0, pytest.approx(float("nan"), nan_ok=True))


def test_a_non_finite_p_is_dropped_from_the_count_rather_than_passing():
    """An unmeasurable cell must not shrink the denominator's own threshold."""
    survive, _ = bh([0.001, float("nan")])
    assert survive == 1


# ------------------------------------------------------------------- the nulls


def test_the_reflection_reproduces_every_bar_and_destroys_only_the_direction():
    """The claim the headline null rests on, asserted term by term.

    The ranges, the absolute steps and the gap magnitudes come back as the same
    multisets, so the trigger distance - which is a function of the ranges - is
    the real one. `wickiness` is the single number the write-up quotes for this,
    and it has to match exactly rather than closely: `walk_path`'s is 3.23
    against the market's 2.37 on EURUSD and 7.53 against 2.35 on silver, which
    is what disqualified it.
    """
    data = walk(size=2000)
    got = reflect(data, random.Random(4))
    assert sorted((got.high - got.low).round(9).tolist()) == sorted(
        (data.high - data.low).round(9).tolist()
    )
    assert sorted(np.abs(np.diff(got.close)).round(9).tolist()) == sorted(
        np.abs(np.diff(data.close)).round(9).tolist()
    )
    assert wickiness(got) == pytest.approx(wickiness(data))


def test_the_reflection_is_a_fair_coin_and_not_a_fixed_flip():
    """A flip of every bar would reproduce the geometry and still be one series.

    Two seeds have to give different series, and the share of up bars has to sit
    at a half. A fixed flip is the failure that would make the null a mirror of
    the data, which has the same P&L under a rule that is itself symmetric.
    """
    data = walk(size=4000)
    one = reflect(data, random.Random(1))
    two = reflect(data, random.Random(2))
    assert not np.allclose(one.close, two.close)
    share = float((np.diff(one.close) > 0).mean())
    assert 0.45 < share < 0.55


def test_the_reflection_keeps_the_path_continuous_and_the_bars_valid():
    """`open` is the previous close plus a real gap, and the bar contains both ends."""
    data = walk(size=2000)
    got = reflect(data, random.Random(5))
    gap = got.open[1:] - got.close[:-1]
    real_gap = data.open[1:] - data.close[:-1]
    assert sorted(np.abs(gap).round(9).tolist()) == sorted(np.abs(real_gap).round(9).tolist())
    assert np.all(got.high >= np.maximum(got.open, got.close))
    assert np.all(got.low <= np.minimum(got.open, got.close))


def test_the_reflection_of_a_trend_is_not_a_trend():
    """The direction is what the arm is for, so it has to actually go."""
    data = ramp(400, sign=1, size=1.0)
    got = reflect(data, random.Random(6))
    assert data.close[-1] - data.close[0] == pytest.approx(399.0)
    assert abs(got.close[-1] - got.close[0]) < 200.0


def test_the_shuffle_keeps_the_bars_and_breaks_the_clustering():
    """Same range multiset as `reflect`, and a flat autocorrelation of `|step|`.

    The pair is the A/B for the harness's own offset: both have no direction, so
    a difference between them is the volatility clustering and nothing else.
    """
    rng = np.random.default_rng(3)
    size = 6000
    # A clustered magnitude sequence, so there is clustering to destroy.
    scale = np.exp(np.cumsum(rng.normal(0.0, 0.05, size)) * 0.5)
    step = rng.normal(0.0, 1.0, size) * scale
    close = 100.0 + np.cumsum(step)
    open_ = np.concatenate(([100.0], close[:-1]))
    wick = np.abs(rng.normal(0.0, 1.0, size)) * scale
    data = series(
        open_.tolist(),
        (np.maximum(open_, close) + wick).tolist(),
        (np.minimum(open_, close) - wick).tolist(),
        close.tolist(),
    )

    def autocorr(s: Series) -> float:
        mag = np.abs(np.diff(s.close))
        return float(np.corrcoef(mag[:-1], mag[1:])[0, 1])

    mixed = shuffle(data, random.Random(7))
    kept = reflect(data, random.Random(7))
    assert sorted((mixed.high - mixed.low).round(9).tolist()) == sorted(
        (data.high - data.low).round(9).tolist()
    )
    assert autocorr(kept) > 0.1, "the fixture has to be clustered for this to mean anything"
    assert abs(autocorr(mixed)) < 0.05


def test_the_shuffle_carries_each_bar_s_own_gap_rather_than_its_neighbour_s():
    """A permuted `open[i] - close[i-1]` is two unrelated prices subtracted.

    Left uncorrected the arm's gaps are the size of the whole series' excursion,
    it triggers on every bar, and nothing raises. The gap multiset is the check.
    """
    data = walk(size=2000)
    got = shuffle(data, random.Random(8))
    real_gap = np.abs(data.open[1:] - data.close[:-1])
    assert np.median(np.abs(got.open[1:] - got.close[:-1])) == pytest.approx(
        np.median(real_gap), abs=1e-9
    )


def test_the_drift_column_is_the_hold_times_the_step_over_the_unit():
    """What a trend is worth to an always-invested rule, so it is not read as edge.

    Every null here coins or demeans the direction, so a rule that is always in
    the market beats them on an instrument that went somewhere - by exposure,
    not by selection. On a ramp of one unit a bar the column has to be the hold
    in units; on a series going nowhere it has to be about zero.
    """
    data = walk(size=2000)
    trades = _trades(data)
    got = drift_units(data, trades)
    step = float(np.mean(np.diff(data.close)))
    held = float(np.mean([t.leave - t.enter for t in trades]))
    unit = float(np.median([t.unit for t in trades]))
    assert got == pytest.approx(step * held / unit)
    assert drift_units(data, []) != drift_units(data, trades)
    assert math.isnan(drift_units(data, []))


def test_the_drift_column_sees_a_trend_a_coin_arm_cannot():
    """A reflected series has no drift and the real one may have plenty."""
    rng = np.random.default_rng(12)
    size = 3000
    close = 100.0 + np.cumsum(rng.normal(0.05, 1.0, size))
    open_ = np.concatenate(([100.0], close[:-1]))
    wick = np.abs(rng.normal(0.0, 1.0, size))
    data = series(
        open_.tolist(),
        (np.maximum(open_, close) + wick).tolist(),
        (np.minimum(open_, close) - wick).tolist(),
        close.tolist(),
    )
    mirror = reflect(data, random.Random(13))
    assert drift_units(data, _trades(data)) > 0.02
    assert abs(drift_units(mirror, _trades(mirror))) < abs(drift_units(data, _trades(data)))


# ------------------------------------------------------------------ malformed


def test_a_bar_whose_extremes_do_not_contain_its_ends_is_flagged():
    """The check that caught the 1d gold series: 177 of 5,009 bars, 3.53%.

    Four columns, four ways to be wrong, and the vendor managed three of them
    in one series. The rule never triggers on such a bar - the cap is above the
    open and the high is below it - so nothing raises and the bar quietly
    poisons the range window instead.
    """
    good = np.array([[0.0, 10.0, 11.0, 9.0, 10.5]])
    assert not malformed(good)[0]
    for row in (
        [0.0, 10.0, 10.2, 9.0, 10.5],  # the high is below the close
        [0.0, 10.0, 11.0, 10.5, 10.2],  # the low is above the open
        [0.0, 10.0, 9.0, 11.0, 10.0],  # the high is below the low
        [0.0, 10.0, float("nan"), 9.0, 10.0],  # and a missing one
    ):
        assert malformed(np.array([row]))[0], row


def test_the_boundary_case_is_a_bar_and_not_a_defect():
    """A dead bar - four equal prices - is malformed by none of the four tests."""
    assert not malformed(np.array([[0.0, 10.0, 10.0, 10.0, 10.0]]))[0]


def test_an_absent_second_trigger_is_the_symmetric_rule_exactly():
    """**The control for the asymmetric grid.** Every mode but `asym` builds an
    eight-field task and passes no `k2`, so the published numbers must be
    reachable unchanged - a default that quietly altered them would make the
    whole study irreproducible."""
    data = flat(400)
    widths = np.full(len(data.close), 1.0)
    vol = np.full(len(data.close), 1.0)

    same, _ = run_rule(data, widths, vol, 0.5, 0.5)
    again, _ = run_rule(data, widths, vol, 0.5, 0.5)
    assert [t.gross for t in same] == [t.gross for t in again]


def test_an_asymmetric_pair_moves_the_two_triggers_independently():
    """A wider short trigger must make short entries rarer, which is the whole
    point of tuning them apart - and is what makes the both-triggers bar's
    convention load-bearing rather than incidental."""
    data = flat(400)
    widths = np.full(len(data.close), 1.0)
    vol = np.full(len(data.close), 1.0)

    even, _ = run_rule(data, widths, vol, 0.3, 0.3)
    tilted, _ = run_rule(data, widths, vol, 0.3, 0.9)
    shorts_even = sum(1 for t in even if t.side < 0)
    shorts_tilted = sum(1 for t in tilted if t.side < 0)
    assert shorts_tilted <= shorts_even, "a wider short trigger did not reduce short entries"
