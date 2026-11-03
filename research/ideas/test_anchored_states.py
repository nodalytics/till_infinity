"""What the anchored-states harness must get right, and what breaks if not.

Run explicitly - `research/` is outside `testpaths`:

    uv run pytest research/ideas/test_anchored_states.py -q

Ordered by what a failure costs. **Causality first**: a state that can see one
bar past its decision bar makes every number in this study a look-ahead, and a
dispersion study is exactly where that would not look implausible - it would
look like a state that calls the next move's size, which is the finding.
`open-gap-filters-are-lookahead` is the recorded version: `drawing.gaps` emits
only *unfilled* gaps, and as a bias it read +0.50R a trade.

Every gate here has a control that passes, per the repo's rule: "it refuses
40%" is indistinguishable from "it refuses everything" without one.
"""

from __future__ import annotations

import math
import random
import subprocess
import sys
from datetime import UTC, datetime

import numpy as np
import pytest

import research.ideas.anchored_states as A
import research.ideas.anchored_states_agg as G
import research.ideas.level_shield as L


def wiggle(n: int, *, seed: int = 11, drift: float = 0.0) -> L.Series:
    """A walk with ranges, so pivots form and a level book is not empty.

    A fixture with structure in it: a straight line has no pivots and no
    spread of readings, so every assertion about a state would pass on a
    series where no state exists.
    """
    rng = random.Random(seed)
    price = 1.2345
    ts, op, hi, lo, cl = [], [], [], [], []
    start = 1_000_000_000
    for i in range(n):
        step = rng.gauss(drift, 0.004) * price
        close = max(1e-6, price + step)
        width = abs(rng.gauss(0.0, 0.003)) * price + 1e-6
        bottom = close - rng.uniform(0.1, 0.9) * width
        ts.append(start + i * 86_400)
        op.append(bottom + rng.uniform(0.1, 0.9) * width)
        hi.append(bottom + width)
        lo.append(bottom)
        cl.append(close)
        price = close
    return L.Series(
        feed="eurusd",
        venue="TEST",
        interval="1d",
        ts=np.asarray(ts, dtype=float),
        open=np.asarray(op),
        high=np.asarray(hi),
        low=np.asarray(lo),
        close=np.asarray(cl),
    )


def hourly(n: int, *, seed: int = 5) -> L.Series:
    """The same walk on an hourly clock, for the stride and session tests."""
    daily = wiggle(n, seed=seed)
    return L.Series(
        feed="eurusd",
        venue="TEST",
        interval="1h",
        ts=np.asarray([1_000_000_000 + i * 3_600 for i in range(n)], dtype=float),
        open=daily.open,
        high=daily.high,
        low=daily.low,
        close=daily.close,
    )


def replaced(series: L.Series, where: int, scale: float) -> L.Series:
    """The same series with every bar from `where` on moved by `scale`."""
    op, hi, lo, cl = (arr.copy() for arr in (series.open, series.high, series.low, series.close))
    for arr in (op, hi, lo, cl):
        arr[where:] *= scale
    return L.Series(
        feed=series.feed,
        venue=series.venue,
        interval=series.interval,
        ts=series.ts,
        open=op,
        high=hi,
        low=lo,
        close=cl,
    )


# ───────────────────────────── causality ─────────────────────────────


def test_no_state_reading_moves_when_a_bar_past_the_decision_bar_changes():
    """The whole study rests on this: states see closed bars only.

    Every bar after the anchor's own outcome window is replaced with a very
    different one. If any level moves, something downstream of the anchor is
    being read, and every number in the study is a look-ahead.
    """
    series = wiggle(700)
    anchors = np.asarray([400], dtype=np.int64)
    before = A.measure(series, "1d", anchors)
    after = A.measure(replaced(series, 421, 1.7), "1d", anchors)
    for name in A.ANCHORS:
        assert before.levels[name][0] == after.levels[name][0], name
    assert before.stratum[0] == after.stratum[0]
    assert before.size[0] == pytest.approx(after.size[0])


def test_the_outcome_does_move_when_a_bar_inside_its_window_changes():
    """The control for the test above, which would otherwise be vacuous.

    A test that cannot fail for its own reason is worse than none: if
    `measure` ignored the forward bars entirely, the causality assertion would
    pass on a harness that measured nothing.
    """
    series = wiggle(700)
    anchors = np.asarray([400], dtype=np.int64)
    before = A.measure(series, "1d", anchors)
    after = A.measure(replaced(series, 415, 1.7), "1d", anchors)
    assert after.size[0] != pytest.approx(before.size[0])
    for name in A.ANCHORS:
        assert before.levels[name][0] == after.levels[name][0], name


def test_a_pivot_set_is_unreadable_until_the_period_that_made_it_has_closed():
    """`Frames.ready` is the guard, and it is wired rather than documented.

    The store's `ts` is probably the bar's open, so a set stamped at its
    source period's last `ts` is knowable one bar early. The stamp is pushed
    to that bar's close, and this asserts the guard refuses a read before it
    and allows one after - the second half being the control.
    """
    series = wiggle(10)
    frames = A.frames_for(series, "1d")
    context = frames.context[0]
    frames.observe(context, closed_at=1_000.0, value="weekly")
    assert frames.ready(999.0) == {}
    assert frames.ready(1_000.0) == {context: "weekly"}


def test_the_one_d_context_frame_is_weekly_because_a_daily_one_is_the_same_clock():
    """`Frames` refuses a context frame that is not strictly coarser.

    Which is why the pivot period is weekly at 1d, and the refusal is the
    reason rather than a preference - a daily set on daily bars is arithmetic
    on a one-bar "prior period" anyway.
    """
    assert "1-WEEK" in A.frames_for(wiggle(5), "1d").context[0]
    assert "1-DAY" in A.frames_for(hourly(5), "1h").context[0]


# ──────────────────────── de-overlapping and the stride ────────────────────────


def test_outcome_windows_never_share_a_bar():
    """De-overlapping is what makes a within-stratum permutation legitimate.

    `overlapping-outcome-windows-leak`: a short skip rule with a long forward
    window gave a direction AUC of 0.79 that collapsed to 0.51.
    """
    for interval, series in (("1d", wiggle(2_000)), ("1h", hourly(2_000))):
        anchors = A.anchors_for(series, interval)
        gaps = np.diff(anchors)
        assert gaps.min() >= A.SETTINGS[interval]["horizon"], interval


def test_the_jittered_stride_spreads_the_anchors_over_the_clock():
    """Without it, `session` and `through` are measured on one value.

    48 bars is exactly two days at 1h, so a fixed stride pins every anchor to
    one hour of the day. The fixed-stride arm below is the control that shows
    the jitter is doing the work rather than being decoration.
    """
    series = hourly(3_000)
    jittered = A.anchors_for(series, "1h")
    hours = {int(series.ts[t] // 3_600) % 24 for t in jittered}
    assert len(hours) >= 8

    fixed = np.arange(A.WARMUP, len(series.close) - 48, 48)
    pinned = {int(series.ts[t] // 3_600) % 24 for t in fixed}
    assert len(pinned) == 1


def test_session_is_refused_at_one_d_rather_than_measured_on_one_level():
    """A state that cannot vary is excluded, not approximated.

    Daily bars all carry the same stamp hour, so `session_of` returns one
    value and the cell has no contrast in it. The prereg's rule is that such
    a state is excluded from this study, and the guard is what excludes it.
    """
    series = wiggle(1_200)
    rows = A.measure(series, "1d")
    assert len(set(rows.levels["session"].tolist())) == 1
    assert (
        G.spread_for(
            rows.levels["session"],
            rows.stratum,
            rows.size,
            bins=A.ANCHORS["session"],
            block=1,
            draws=0,
        )
        is None
    )


# ─────────────────────────────── the seeds ───────────────────────────────


def test_seeds_reproduce_in_a_second_interpreter():
    """`hash()` is salted per process and three harnesses carried the bug.

    `stop-anchor.md` had gold.15m's hardest null move +0.0267 to +0.0239 and
    flip a cell from fail to pass with no real reading moving;
    `fear-greed.md` had audjpy's `bar-shuffle` read -0.172 locally and -0.266
    on the panel while every real value matched to the digit. A seed that
    does not survive a second interpreter is that bug.
    """
    here = A.seed_of("eurusd", "1d", "bar-shuffle", 3)
    code = (
        "import research.ideas.anchored_states as A;"
        "print(A.seed_of('eurusd', '1d', 'bar-shuffle', 3))"
    )
    got = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
        env={"PYTHONHASHSEED": "12345", "PATH": "/usr/bin:/bin"},
    )
    assert int(got.stdout.strip()) == here
    assert hash(("eurusd", "1d")) != A.seed_of("eurusd", "1d")


# ──────────────────────────────── the arms ────────────────────────────────


def test_a_log_arm_keeps_the_relative_range_where_an_absolute_arm_does_not():
    """The correction this module makes to `level_shield`'s arms.

    Over 19 years the price level moves up to 8.45x on gold, so an arm that
    permutes **absolute** steps and spans has the wrong relative volatility at
    one end of the sample. `fear-greed.md`'s fifth defect is the measured
    version: an absolute-step arm and its log twin disagreed by more than the
    effect, +0.142 against +0.236 on a real +0.213.
    """
    series = wiggle(1_500, seed=3, drift=0.0014)
    assert series.close[-1] / series.close[0] > 4.0
    real = float(np.std((series.high - series.low) / series.close))

    log_arm = A.bar_shuffle(series, random.Random(1))
    abs_arm = L.bar_shuffle(series, random.Random(1))
    log_rel = float(np.std((log_arm.high - log_arm.low) / log_arm.close))
    abs_rel = float(np.std((abs_arm.high - abs_arm.low) / abs_arm.close))
    assert abs(log_rel - real) < abs(abs_rel - real)


def test_bar_shuffle_keeps_the_log_step_multiset_and_loses_the_order():
    """The no-memory floor has to keep the marginal and nothing else."""
    series = wiggle(400)
    made = A.bar_shuffle(series, random.Random(7))
    real = np.sort(np.diff(np.log(series.close)))
    got = np.sort(np.diff(np.log(made.close)))
    assert np.allclose(real, got)
    assert not np.allclose(np.diff(np.log(series.close)), np.diff(np.log(made.close)))


@pytest.mark.parametrize("arm", ["garch-bars", "walk-geometry", "bar-shuffle"])
def test_every_arm_keeps_the_bar_count_the_calendar_and_a_valid_bar(arm):
    """An arm with a different calendar is a different experiment.

    `the-Q-clock-is-an-activity-clock` records that spans **and** bar counts
    both have to be matched before two clocks are comparable; an arm that
    silently drops a bar breaks the anchor set every other arm shares.
    """
    series = wiggle(500)
    make = A.SERIES_ARMS[arm]
    rng = random.Random(4)
    built = make(series, rng, L.fit_garch(np.diff(np.log(series.close)))) if arm == "garch-bars" else make(series, rng)
    assert len(built.close) == len(series.close)
    assert np.array_equal(built.ts, series.ts)
    assert (built.high >= built.low).all()
    assert (built.close > 0).all()


# ───────────────────────────── the statistic ─────────────────────────────


def planted(n: int, bins: int, gap: float, *, seed: int = 0, confound: float = 0.0):
    """Labels, strata and an outcome with a known level gap in it."""
    rng = np.random.default_rng(seed)
    level = rng.integers(0, bins, n)
    stratum = rng.integers(0, A.STRATA, n)
    value = rng.normal(0.0, 1.0, n) + gap * level + confound * stratum
    return level, stratum, value


def test_spread_tracks_a_planted_level_gap_and_reads_small_without_one():
    """The decision statistic has to move with the thing it measures.

    The zero arm is the control: a statistic that rises with the plant but is
    equally large with no plant is measuring its own estimation error.
    """
    with_gap = G.spread_for(*planted(2_000, 3, 0.50), bins=3, block=1, draws=50, seed=1)
    without = G.spread_for(*planted(2_000, 3, 0.0), bins=3, block=1, draws=50, seed=1)
    assert with_gap is not None and without is not None
    assert with_gap.spread > 4.0 * without.spread
    assert with_gap.spread == pytest.approx(0.41, abs=0.08)


def test_the_deciding_statistic_is_scale_free_where_the_raw_spread_is_not():
    """Why `effect` decides and `spread` is only reported.

    The arms do not match the real series on the outcome's own scale:
    measured on eurusd 1d, the real `size` has mean 2.300 and sd 1.904 while
    `level_shield.garch_bars` reads 1.257-1.410 and 1.054-1.195, because that
    arm scales a bar range by the simulated **sd** against a **median**
    absolute return. An unstandardised statistic reads that difference as
    structure. Multiplying the outcome by three is the same mismatch in
    miniature: the raw spread triples and the effect does not move.
    """
    level, stratum, value = planted(2_000, 3, 0.40, seed=15)
    small = G.spread_for(level, stratum, value, bins=3, block=1, draws=0)
    large = G.spread_for(level, stratum, 3.0 * value, bins=3, block=1, draws=0)
    assert small is not None and large is not None
    assert large.spread == pytest.approx(3.0 * small.spread, rel=1e-9)
    assert large.effect == pytest.approx(small.effect, rel=1e-9)


def test_stratifying_removes_a_pure_volatility_confound():
    """`AUC-is-free-on-volatility-targets`, as an assertion.

    A state that is the volatility stratum relabelled, over an outcome driven
    only by that stratum, is the exact shape of the 0.805 that fell to 0.525
    within strata. Within-stratum centring has to take it to nothing, and the
    pooled contrast is the control showing the confound was really there.
    """
    rng = np.random.default_rng(3)
    stratum = rng.integers(0, A.STRATA, 2_000)
    level = np.minimum(2, stratum // 2)
    value = rng.normal(0.0, 1.0, 2_000) + 2.0 * stratum

    pooled = [value[level == g].mean() for g in range(3)]
    assert max(pooled) - min(pooled) > 2.0

    got = G.spread_for(level, stratum, value, bins=3, block=1, draws=50, seed=2)
    assert got is not None
    assert got.spread < 0.15


def test_a_level_under_the_floor_is_dropped_and_the_kept_share_says_so():
    """`level-bounce.md` guarded on the rows going in and reported anyway.

    209 rows over 25 cells left almost every cell under the floor, and
    -0.0769 was still printed on the 26 that survived. The guard belongs on
    the surviving mass, and the share that survived has to be visible.
    """
    level, stratum, value = planted(600, 3, 0.0, seed=4)
    level[:3] = 2
    level[3:] = np.where(level[3:] == 2, 0, level[3:])
    got = G.spread_for(level, stratum, value, bins=3, block=1, draws=0, seed=5)
    assert got is not None
    assert got.used == 2
    assert got.kept < 1.0
    assert got.per_level_n[2] == 0


def test_spread_refuses_thin_mass_rather_than_reporting_on_it():
    """A refusal is a cell this study cannot answer, never a null."""
    level, stratum, value = planted(12, 3, 0.0, seed=6)
    assert G.spread_for(level, stratum, value, bins=3, block=1, draws=0) is None
    wide = planted(400, 3, 0.0, seed=6)
    assert G.spread_for(*wide, bins=3, block=1, draws=0) is not None


def test_the_duty_twin_keeps_the_firing_rate_and_kills_the_association():
    """Pass rule 4: otherwise the finding is the firing rate, not the state."""
    level, stratum, value = planted(1_200, 3, 0.60, seed=8)
    real = G.spread_for(level, stratum, value, bins=3, block=1, draws=0)
    draws = G.duty_draws(level, stratum, value, bins=3, block=1, draws=8, seed=9)
    assert real is not None
    assert len(draws) == 8
    assert max(draws) < real.effect
    #: The labels never move, so the twin's firing rate is identical by
    #: construction rather than by matching.
    assert [int((level == g).sum()) for g in range(3)] == list(real.per_level_n)


def test_the_sign_flip_arm_keeps_the_magnitudes_and_kills_the_direction():
    """The secondary claim's own null, which a Gaussian arm would not be.

    `fear-greed.md` found Gaussian GARCH reading -0.079 to +0.116 on all
    fourteen legs, so the mechanism there was skewness rather than
    clustering. Keeping `|signed|` keeps this market's tails.
    """
    level, stratum, _value = planted(1_200, 3, 0.0, seed=10)
    signed = np.where(level == 2, 1.0, -1.0) * np.abs(
        np.random.default_rng(11).normal(1.0, 0.3, 1_200)
    )
    real = G.spread_for(level, stratum, signed, bins=3, block=1, draws=0)
    draws = G.sign_flip_draws(level, stratum, signed, bins=3, block=1, draws=8, seed=12)
    assert real is not None and len(draws) == 8
    assert max(draws) < real.effect


def test_cramers_v_separates_a_relabelled_stratum_from_an_independent_state():
    """The first "uninteresting even if it passes" clause, as a number."""
    rng = np.random.default_rng(13)
    stratum = rng.integers(0, A.STRATA, 2_000)
    same = np.minimum(2, stratum // 2)
    free = rng.integers(0, 3, 2_000)
    assert G.cramers_v(same, stratum, bins=3) > 0.8
    assert G.cramers_v(free, stratum, bins=3) < 0.15


def test_the_pooled_auc_is_free_on_a_volatility_target_and_the_stratified_one_is_not():
    """Both numbers are reported because the gap is the measurement.

    The pooled AUC on a target driven only by the stratum reads well above
    0.5 with no state information at all, which is why the prereg says an
    unstratified AUC on `size` is not a result.
    """
    rng = np.random.default_rng(14)
    n = 3_000
    stratum = rng.integers(0, A.STRATA, n)
    level = np.minimum(2, stratum // 2)
    value = np.abs(rng.normal(0.0, 1.0, n)) * (1.0 + stratum)
    half = (np.arange(n) >= n // 2).astype(np.int64)
    got = G.auc_crossfit(level, stratum, value, bins=3, half=half)
    assert got.pooled is not None and got.strata is not None
    assert got.pooled > 0.60
    assert abs(got.strata - 0.5) < 0.06


def test_expected_passes_moves_with_the_draw_count():
    """`stop-anchor.md` printed a hardcoded bar whatever `--draws` was.

    It understated the bar fourfold and made 3 of 140 cells read as "far
    below chance". The expectation is a function of the draws, so the
    function has to be too.
    """
    low, low_sd = G.expected_passes(140, 12)
    high, _ = G.expected_passes(140, 48)
    assert low == pytest.approx(10.77, abs=0.05)
    assert high == pytest.approx(2.86, abs=0.05)
    assert low_sd == pytest.approx(math.sqrt(low), abs=1e-9)


def test_the_p_value_is_a_t_not_a_normal_so_sixteen_draws_are_not_taken_as_known():
    """A normal on a sd from 16 draws makes every p and BH q too small."""
    assert G._student_p(2.0, 15) == pytest.approx(0.0320, abs=0.002)
    assert G._student_p(2.0, 1_000_000) == pytest.approx(0.0228, abs=0.001)
    assert G._student_p(2.0, 15) > G._student_p(2.0, 1_000_000)


def test_judge_reads_the_hardest_arm_and_counts_every_draw():
    """The bar is the maximum over every draw of every deciding arm."""
    got = G.judge(1.0, 0.1, {"a": [0.1, 0.2, 0.3], "b": [0.8, 0.9, 1.1]})
    assert got is not None
    assert got.hardest_arm == "b"
    assert got.hardest == pytest.approx(1.1)
    assert got.draws == 6
    assert got.beats_hardest is False
    assert G.judge(1.5, 0.1, {"b": [0.8, 0.9, 1.1]}).beats_hardest is True


# ──────────────────────────────── the plant ────────────────────────────────


def test_the_zero_plant_returns_the_series_unchanged():
    """The zero control, asserted rather than assumed.

    `fear-greed.md`'s plant read -0.180 at z -4.76 with nothing planted and
    had to be rejected, with the question recorded as untested rather than
    null. A zero cell that is not exactly zero is a broken arm.
    """
    series = wiggle(600)
    anchors = A.anchors_for(series, "1d")
    picked = np.ones(len(anchors), dtype=bool)
    made = A.plant_magnitude(series, "1d", anchors, picked, 0.0)
    assert np.allclose(made.close, series.close)
    assert np.allclose(made.high, series.high)
    assert np.allclose(made.low, series.low)


def test_the_plant_widens_the_range_and_not_only_the_close():
    """A magnitude plant that moves closes alone validates the wrong half.

    `fear-greed.md`'s planted crash was a smooth drift that never widened a
    range: it validated the direction half and read 0 of 4 on the volatility
    half at depth 0.45.
    """
    series = wiggle(600)
    anchors = A.anchors_for(series, "1d")
    picked = np.ones(len(anchors), dtype=bool)
    made = A.plant_magnitude(series, "1d", anchors, picked, 0.5)
    inside = slice(int(anchors[0]) + 1, int(anchors[0]) + 20)
    real_rel = ((series.high - series.low) / series.close)[inside]
    made_rel = ((made.high - made.low) / made.close)[inside]
    assert made_rel.mean() == pytest.approx(1.5 * real_rel.mean(), rel=0.02)


def test_a_clock_plant_cannot_move_its_own_labels():
    """Why the power sweep plants on `session` and `through`.

    `fear-greed.md`'s sixth defect: a label-conditional plant changed the path,
    the labels recomputed on the planted series no longer marked the same
    bars, and **the act of planting destroyed the association being
    planted** - zero cell +0.1412, hard walls the wrong sign. A clock label
    is a function of the timestamp, so no price plant can reach it.
    """
    series = hourly(6_000)
    anchors = A.anchors_for(series, "1h")
    before = A.measure(series, "1h", anchors)
    picked = before.levels["session"] == A.SESSIONS.index("london")
    made = A.plant_magnitude(series, "1h", anchors, picked, 0.8)
    after = A.measure(made, "1h", anchors)
    assert np.array_equal(before.levels["session"], after.levels["session"])
    #: And the control: a price-derived label does move, which is the
    #: attenuation the sweep measures rather than assumes.
    assert not np.array_equal(before.levels["mood_vol"], after.levels["mood_vol"])


def test_the_plant_raises_the_picked_levels_outcome_and_leaves_the_others():
    """The plant has to be visible in the quantity the study judges."""
    series = hourly(6_000)
    anchors = A.anchors_for(series, "1h")
    before = A.measure(series, "1h", anchors)
    picked = before.levels["session"] == A.SESSIONS.index("london")
    assert picked.sum() > 10
    after = A.measure(A.plant_magnitude(series, "1h", anchors, picked, 0.8), "1h", anchors)
    assert after.size[picked].mean() > 1.3 * before.size[picked].mean()
    other = ~picked & np.isfinite(before.size)
    assert after.size[other].mean() == pytest.approx(before.size[other].mean(), rel=0.35)


# ───────────────────────────── the cuts are causal ─────────────────────────────


def test_a_causal_cut_uses_only_prior_readings_and_refuses_an_early_anchor():
    """A full-sample quantile edge is not computable at the decision bar.

    The prereg permitted one for the stratification variable; the causality
    rule is stronger and is what is implemented. An anchor with fewer than
    `RANK_FLOOR` prior readings is dropped rather than cut on forty of them.
    """
    raw = np.arange(1_000, dtype=float)
    anchors = np.asarray([50, 300, 999], dtype=np.int64)
    got = A.causal_levels(raw, anchors, 5)
    assert got[0] == -1
    #: A strictly rising reading is always at the top of its own prefix, so
    #: every admitted anchor lands in the last bin - which a full-sample cut
    #: would not do, and is the signature of a trailing one.
    assert got[1] == 4 and got[2] == 4


def test_the_period_thirds_are_fixed_and_not_estimated():
    """`through` is already 0..1, so early/middle/late is arithmetic.

    Nothing is estimated, so nothing can be fitted - which is the whole of
    `definitions-cannot-be-states`' requirement for this anchor.
    """
    raw = np.asarray([0.0, 0.2, 0.34, 0.5, 0.66, 0.9, 1.0, np.nan])
    got = A.thirds(raw, np.arange(8))
    assert got.tolist() == [0, 0, 1, 1, 1, 2, 2, -1]


# ──────────────────────── a production bug, worked around ────────────────────────


def test_a_dead_window_is_a_missing_mood_and_not_a_stale_one():
    """`FearGreed._expansion` raises on an all-dead last fifth of its window.

    It guards `middle <= 0.0` and not `now <= 0.0`, so
    `math.log2(now / middle)` raises `ValueError: math domain error`. **This is
    a production defect** - `handle_bar` would propagate it into the Nautilus
    bar handler on any feed that goes flat for twelve bars - and it is
    reported rather than fixed from a research file.

    The harness has to carry on, and what it must not do is record the
    previous bar's reading: `absent is not zero`, and a stale mood written on
    every dead bar reads later as a measurement.
    """
    series = wiggle(500)
    #: The window is 60 bars and `_expansion` reads its last fifth, so the
    #: crash needs a **mixture**: a positive median over the window and a dead
    #: last twelve. An all-dead series is caught by the `middle <= 0.0` guard
    #: and is not the case that breaks.
    op, hi, lo, cl = (arr.copy() for arr in (series.open, series.high, series.low, series.close))
    for arr in (op, hi, lo):
        arr[-15:] = cl[-15:]
    flat = L.Series(
        feed=series.feed,
        venue=series.venue,
        interval=series.interval,
        ts=series.ts,
        open=op,
        high=hi,
        low=lo,
        close=cl,
    )
    got = A.read(flat, "1d")
    assert got.dead > 0
    assert not np.isfinite(got.mood_vol[-1])
    assert not np.isfinite(got.mood_dir[-1])
    #: And the control: the same walk with live ranges produces a reading, so
    #: the assertion above is about dead bars and not about the harness never
    #: reading a mood at all.
    live = A.read(series, "1d")
    assert live.dead == 0
    assert np.isfinite(live.mood_vol[-1])


def test_thirds_of_a_week_are_not_three_states_on_daily_bars():
    """Why `through` reads the **monthly** period at 1d.

    A weekday bar stamped at midnight reaches at most 5/7 = 0.714 of its week,
    so the last third of a week is only ever the Sunday bar. Measured: gold,
    which has no Sunday bar, saw 2 of 3 levels, and eurusd's third level was
    made entirely of the FX Sunday open - the hour this desk already vetoes
    entries in. Thirds of a month are three buckets of about seven trading
    days each.
    """
    from till_infinity.indicators.pivots import Pivots

    pv = Pivots(periods=("weekly", "monthly"))
    #: Six weeks of weekday-only daily bars, stamped at midnight UTC.
    weekly, monthly = [], []
    when = 1_000_000_000 - 1_000_000_000 % 86_400
    for day in range(60):
        moment = when + day * 86_400
        if datetime.fromtimestamp(moment, UTC).weekday() >= 5:
            continue
        pv.update_raw(1.1, 0.9, 1.0, float(moment))
        weekly.append(pv.through("weekly"))
        monthly.append(pv.through("monthly"))
    assert max(weekly) < 2.0 / 3.0
    assert max(monthly) > 2.0 / 3.0
    assert A.SETTINGS["1d"]["through_period"] == "monthly"
    assert A.SETTINGS["15m"]["through_period"] == "daily"


# ──────────────────────────── the report, end to end ────────────────────────────


def panel_record(feed: str, anchor: str, outcome: str, *, placebo: bool, real: float) -> dict:
    """One `cell` record in the schema `anchored_states_run` writes.

    Hand-built on purpose: the report reads a file, so a change to what the
    run writes breaks it silently unless something asserts the two agree. That
    is the shape of this study's own history - a panel written before a later
    arm existed had no key for it and had to be re-run rather than appended to.
    """
    arms = {name: [0.05 * (i + 1) for i in range(16)] for name in A.DECIDING_ARMS}
    body = {
        "n": 200,
        "mass": 200,
        "kept": 1.0,
        "used": 3,
        "spread": real * 2.0,
        "sd": 0.04,
        "effect": real,
        "effect_sd": 0.04,
        "resid_sd": 2.0,
        "kw": 12.0 if real > 0.5 else 2.0,
        "level_n": [70, 70, 60],
        "level_mean": [-0.6, 0.0, 0.7],
        "level_sd": [1.9, 1.9, 1.9],
        "pooled_mean": 2.3,
        "row_sd": 1.9,
        "n_eff": 190.0,
    }
    return {
        "feed": feed,
        "venue": "TEST",
        "interval": "1d",
        "bars": 5000,
        "days": 7000.0,
        "placebo": placebo,
        "kind": "cell",
        "anchor": anchor,
        "outcome": outcome,
        "bins": 3,
        "v_comp": 0.2,
        "all": body,
        "a": body,
        "b": body,
        "arms_all": arms,
        "kw_arms_all": {name: [1.0] * 16 for name in A.DECIDING_ARMS},
        "arms_a": arms,
        "kw_arms_a": {name: [1.0] * 16 for name in A.DECIDING_ARMS},
        "arms_b": arms,
        "kw_arms_b": {name: [1.0] * 16 for name in A.DECIDING_ARMS},
        "auc_strata": 0.52,
        "auc_pooled": 0.61,
        "auc_n": 200,
    }


def test_the_report_prints_every_section_and_reaches_the_pass_rule(tmp_path, capsys):
    """Every section, on a panel built to make criterion 1 nearly reachable.

    The real arm is set above all 64 null draws on three non-placebo feeds and
    below them on the placebo pair, so the pass-rule block has to exercise
    both branches rather than printing the all-null path.
    """
    import json

    import research.ideas.anchored_states_report as R

    rows = [
        {
            "feed": feed,
            "venue": "TEST",
            "interval": "1d",
            "bars": 5000,
            "days": 7000.0,
            "placebo": feed in A.PLACEBO,
            "kind": "series",
            "anchors": 200,
            "stride": 20.0,
            "block_rows": 1,
            "refused": 0,
            "dead": 0,
            "levels_seen": dict.fromkeys(A.ANCHORS, 3),
            "arm_size": {"real": [2.3, 1.9], "garch-bars": [1.3, 1.1]},
        }
        for feed in ("eurusd", "gbpusd", "gold", *A.PLACEBO)
    ]
    for feed in ("eurusd", "gbpusd", "gold", *A.PLACEBO):
        for outcome in ("size", "signed"):
            rows.append(
                panel_record(
                    feed,
                    "mood_vol",
                    outcome,
                    placebo=feed in A.PLACEBO,
                    real=0.2 if feed in A.PLACEBO else 1.4,
                )
            )
    (tmp_path / "panel.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    (tmp_path / "meta.json").write_text(json.dumps({"draws": 16, "placebo": list(A.PLACEBO)}))

    R.main([str(tmp_path)])
    printed = capsys.readouterr().out
    for heading in (
        "coverage actually run",
        "marginal scale",
        "primary claim",
        "per instrument",
        "both halves",
        "duty-cycle twin",
        "is any effect reachable",
        "the pass rule, criterion by criterion",
        "secondary claim",
        "trial count",
    ):
        assert heading in printed, heading
    assert "3 non-placebo instruments (needs 3)" in printed
    assert "0 placebo cells beat their hardest null" in printed


def test_a_bad_store_fails_before_the_panel_is_spent(tmp_path):
    """`failed-sync-still-launches-the-run`, as a refusal with a flag in it.

    `lab.sh run` prints "launched" whether or not the sync carried the new
    code or the data, so the expensive thing has to refuse up front and name
    the flag that fixes it - not raise a traceback forty minutes in.
    """
    import research.ideas.anchored_states_run as R

    with pytest.raises(SystemExit) as refused:
        R.main(
            [
                "--out",
                str(tmp_path),
                "--store",
                "file:/nowhere/prices.db?mode=ro",
                "--feeds",
                "eurusd",
                "--intervals",
                "1d",
            ]
        )
    assert "--store" in str(refused.value)


def test_one_bad_job_becomes_a_record_and_does_not_kill_the_panel():
    """`pool.map` propagates an exception and takes the whole run with it.

    This study has already hit the case: `FearGreed` raises on gold's dead 1d
    bars, which killed a three-feed smoke run outright. Forty-one good jobs are
    not worth losing to one bad feed - and the record has to be loud, because a
    missing cell is not a null.
    """
    import research.ideas.anchored_states_run as R

    def boom(job):
        raise ValueError("math domain error")

    got = R.guarded(boom)(("gold", "1d", "store", 16))
    assert len(got) == 1
    assert got[0]["kind"] == "error"
    assert "math domain error" in got[0]["error"]
    assert got[0]["job"][:2] == ["gold", "1d"]
    #: And the control: a job that works is passed through untouched, so the
    #: guard cannot be hiding a silent failure on every job.
    assert R.guarded(lambda job: [{"kind": "cell"}])(("x",)) == [{"kind": "cell"}]
