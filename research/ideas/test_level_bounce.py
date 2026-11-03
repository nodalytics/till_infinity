"""What the level-bounce harness must get right, and what breaks if it does not.

Run explicitly - `research/` is outside `testpaths`:

    uv run pytest research/ideas/test_level_bounce.py -q

The tests are ordered by what they cost if they fail. The grade's causality
comes first, because a grade that can see its own episode makes the whole study
a lookahead and every number in it would read as a finding.
"""

from __future__ import annotations

import numpy as np
import pytest

import research.ideas.level_bounce as B
import research.ideas.level_bounce_agg as A


def series_of(bars, *, feed="test", interval="1d", start=0.0, step=86_400.0):
    """A `Series` from `(open, high, low, close)` tuples, one bar a day."""
    arr = np.asarray(bars, dtype=float)
    return B.Series(
        feed=feed,
        venue="TEST",
        interval=interval,
        ts=start + step * np.arange(len(arr)),
        open=arr[:, 0],
        high=arr[:, 1],
        low=arr[:, 2],
        close=arr[:, 3],
    )


# ───────────────────────── the grade cannot see itself ─────────────────────────


def test_a_levels_first_episode_is_graded_on_the_prior_and_not_on_itself():
    """The whole study is a lookahead if a grade reads its own episode.

    A level's first episode has no history, so every grade on it must be the
    pooled prior - 0.5 for the very first episode in the series, since there is
    nothing earlier to pool either. If `episodes` ever folded a row's own shape
    in before grading it, this reads something other than 0.5 and the positive
    results in the write-up would be the shape predicting itself.
    """
    rows = _rows_with_two_touches()
    first = int(np.argmin(rows.bar))
    assert rows.n_prev[first] == 0
    for grade in ("sharp_share", "run_share", "bar_share", "hold_share"):
        assert getattr(rows, grade)[first] == pytest.approx(0.5), grade


def test_a_grade_moves_only_after_the_episode_it_describes():
    """A second episode is graded on the first, which is the usable claim.

    `n_prev` is 1 on the second episode and its `sharp_share` has to differ
    from the first's 0.5 in the direction of what the first episode did. If
    both episodes carried the same grade, the history was never being read and
    part 2 would be measuring nothing at all.
    """
    rows = _rows_with_two_touches()
    order = np.argsort(rows.bar)
    assert rows.n_prev[order[1]] == 1
    assert rows.sharp_share[order[1]] != pytest.approx(0.5)


def _rows_with_two_touches():
    """A level at 100.0 touched twice, far enough apart to both be scored."""
    bars = []
    for _ in range(3):
        bars.extend(
            [
                (99.0, 99.4, 98.6, 99.2),
                (99.2, 99.6, 98.9, 99.4),
                (99.4, 100.2, 99.3, 99.6),
                (99.6, 99.9, 99.1, 99.3),
                (99.3, 99.5, 98.4, 98.6),
                (98.6, 99.1, 98.2, 98.9),
                (98.9, 99.3, 98.5, 99.1),
                (99.1, 99.8, 98.9, 99.5),
            ]
        )
    series = series_of(bars)
    books = [[(7, 100.0)] for _ in bars]
    unit = np.full(len(bars), 0.5)
    return B.episodes(
        series,
        books,
        unit,
        np.zeros(len(bars), dtype=np.int64),
        interval="1d",
        horizon=4,
        gap_bars=4,
    )


# ───────────────────────────── the shape definitions ─────────────────────────────

#: A resistance level price and the unit every shape fixture is built in. One
#: unit is 1.0 in price, so `SPIKE_RANGE` 1.5 means a bar range of 1.5.
LEVEL, UNIT = 100.0, 1.0


def _shape(departure, *, away=-1, level=LEVEL, unit=UNIT):
    """`shape_at` on a one-bar lead-in plus `departure`, touching at bar 1.

    `departure` is padded to `SHAPE_BARS` by repeating its last bar, because
    `shape_at` reads a window of exactly that length from the touch and returns
    0 - no opinion - when the series is too short to hold one. A fixture one bar
    short reads as "no shape" for every class at once, which is what the first
    version of these tests did.
    """
    padded = list(departure) + [departure[-1]] * max(0, B.SHAPE_BARS - len(departure))
    series = series_of([(99.0, 99.2, 98.8, 99.1), *padded])
    assert series.high[1] + B.TOUCH_VOL * unit >= level >= series.low[1] - B.TOUCH_VOL * unit
    return B.shape_at(series, 1, level, away, unit)


def test_a_wide_impulsive_bar_closing_away_from_the_level_is_a_spike():
    """The spike class, and what each of its three conditions is for.

    A bar that spikes through 100.0, is 1.6 units wide, has a body 0.8 of its
    range and closes below the level is the shape the question is about. All
    three conditions come from production code - `Candle.impulsive` is the
    desk's `PUSH_BODY` 0.70 - so this test also pins that the harness is
    reading them and not a local copy.
    """
    got = _shape(
        [(100.1, 100.4, 98.8, 98.9), (98.9, 99.1, 98.5, 98.7), (98.7, 99.0, 98.3, 98.5)]
    )
    assert got & B.SPIKE


def test_a_narrow_bar_with_the_same_shape_is_not_a_spike():
    """The width gate is what separates a spike from an ordinary down bar.

    Identical body-to-range proportion and identical direction, a tenth of the
    range. Without this control "spike" would fire on any bar that closed the
    right way and the class would be a direction label, not a shape - which is
    the version of this harness that read a 0.2% firing rate and was fixed.
    """
    got = _shape(
        [(100.02, 100.04, 99.88, 99.89), (99.89, 99.91, 99.85, 99.87), (99.87, 99.9, 99.83, 99.85)]
    )
    assert not got & B.SPIKE


def test_a_bar_that_pierces_the_level_and_closes_beyond_it_is_not_a_rejection():
    """A hammer whose close is on the wrong side is the level breaking.

    `candles.confirms` makes this check and it is the one most easily left out.
    A long lower wick below support, closing *below* support, is support
    failing; counting it as a rejection would grade a level well for the
    episodes on which it broke.
    """
    through = _shape(
        [(99.9, 100.1, 97.0, 97.2), (97.2, 97.5, 96.8, 97.0), (97.0, 97.3, 96.6, 96.8)],
        away=1,
    )
    assert not through & B.REJECT


def test_four_bars_marching_away_with_one_small_hiccup_is_a_trend_run():
    """The user's trend run, and `trend.ratio` is why it tolerates the hiccup.

    Three down steps of about 1.0 with one 0.2 step back gives net travel over
    gross travel well above `RUN_EFF`, so the run survives a counter-bar. A
    rule asking for monotone bars would refuse this, which is exactly the shape
    the desk described as a run.
    """
    got = _shape(
        [
            (100.1, 100.3, 99.0, 99.1),
            (99.1, 99.3, 98.1, 98.2),
            (98.2, 98.5, 98.1, 98.4),
            (98.4, 98.5, 97.2, 97.3),
        ]
    )
    assert got & B.RUN


def test_a_zigzag_covering_the_same_ground_is_not_a_trend_run():
    """The control: same net move, inefficient path, no run.

    Without it, `RUN` would be "price ended up `RUN_MOVE` away", which is the
    departure condition on its own - and the study would be comparing a
    departure against a departure and calling the difference bounce shape.
    """
    got = _shape(
        [
            (100.1, 100.3, 99.0, 99.1),
            (99.1, 100.4, 99.0, 100.2),
            (100.2, 100.4, 98.9, 99.0),
            (99.0, 100.3, 98.5, 99.4),
        ]
    )
    assert not got & B.RUN


def test_a_touch_that_never_leaves_is_neither_a_bounce_nor_a_drift():
    """Two thirds of 1d episodes land here, so the class has to exist.

    A harness that emitted only its interesting classes would report shape
    shares over a third of its own touches while reading as though it covered
    them all.
    """
    got = _shape(
        [(100.0, 100.1, 99.9, 100.0), (100.0, 100.1, 99.9, 100.0), (100.0, 100.1, 99.9, 100.0)]
    )
    assert not got & B.SHARP
    assert got & (B.THROUGH | B.STALL)


# ──────────────────────────── de-overlapping and R ────────────────────────────


def test_two_touches_inside_the_forward_window_score_once():
    """Overlapping outcome windows are how this study would fake a result.

    `overlapping-windows-inflate-permutation-nulls` is a level finding at
    p 0.015 that was anchor overlap, and `overlapping-outcome-windows-leak` is
    a direction AUC of 0.79 that collapsed to 0.51. Two touches of one level
    three bars apart share almost all of their outcome bars, so only the first
    may be scored at a gap of 8.
    """
    bars = [(99.5, 100.1, 99.0, 99.2)] + [(99.2, 99.6, 98.8, 99.4)] * 2
    bars += [(99.4, 100.2, 99.1, 99.3)] + [(99.3, 99.7, 98.9, 99.5)] * 10
    series = series_of(bars)
    rows = B.episodes(
        series,
        [[(1, 100.0)] for _ in bars],
        np.full(len(bars), 0.5),
        np.zeros(len(bars), dtype=np.int64),
        interval="1d",
        horizon=8,
        gap_bars=8,
    )
    assert len(rows) == 1


def test_r_is_minus_one_when_the_stop_goes_first_and_the_ratio_when_the_target_does():
    """The R arithmetic, which is what the study is now decided on.

    Entry is the touch bar's close and the stop sits one unit through the
    level, so the risk is measurable by hand: a touch closing at 99.5 against a
    level at 100.0 with a one-unit stop at 101.0 risks 1.5, and the 2R target
    is at 99.5 - 3.0 = 96.5. A path reaching 96.5 before 101.0 pays +2; the
    reverse pays -1. If this drifts, every mean R in the write-up is on a
    different scale than it claims.
    """
    unit = np.full(40, 1.0)
    strata = np.zeros(40, dtype=np.int64)

    down = [(99.0, 99.3, 98.8, 99.1), (99.1, 100.2, 99.0, 99.5)]
    down += [(99.0, 99.2, 96.0, 96.2)] + [(96.2, 96.4, 95.8, 96.0)] * 10
    rows = B.episodes(
        series_of(down),
        [[(1, 100.0)] for _ in down],
        unit,
        strata[: len(down)],
        interval="1d",
        horizon=8,
        gap_bars=8,
    )
    assert rows.r[2.0][0] == pytest.approx(2.0)

    up = [(99.0, 99.3, 98.8, 99.1), (99.1, 100.2, 99.0, 99.5)]
    up += [(99.5, 101.5, 99.4, 101.4)] + [(101.4, 101.8, 101.2, 101.6)] * 10
    rows = B.episodes(
        series_of(up),
        [[(1, 100.0)] for _ in up],
        unit,
        strata[: len(up)],
        interval="1d",
        horizon=8,
        gap_bars=8,
    )
    assert rows.r[2.0][0] == pytest.approx(-1.0)


def test_a_tighter_target_can_pay_while_a_wider_one_on_the_same_touch_stops_out():
    """Each reward-to-risk is its own trade, and one shared stop flag broke that.

    The 1R target fills on the way down and the 3R target is still live when
    price turns and stops out. A single "stopped" flag would have charged the
    banked 1R trade for the later loss, which is a silent loss of about one R
    on every episode that turns after a partial move.
    """
    bars = [(99.0, 99.3, 98.8, 99.1), (99.1, 100.2, 99.0, 99.5)]
    bars += [(99.5, 99.6, 97.9, 98.0), (98.0, 101.5, 97.9, 101.4)]
    bars += [(101.4, 101.8, 101.2, 101.6)] * 10
    rows = B.episodes(
        series_of(bars),
        [[(1, 100.0)] for _ in bars],
        np.full(len(bars), 1.0),
        np.zeros(len(bars), dtype=np.int64),
        interval="1d",
        horizon=8,
        gap_bars=8,
    )
    assert rows.r[1.0][0] == pytest.approx(1.0)
    assert rows.r[3.0][0] == pytest.approx(-1.0)


# ───────────────────────────── the placebo and the tags ─────────────────────────


def test_a_placebo_level_keeps_one_offset_so_it_has_a_history_too():
    """A placebo redrawn per bar has no record, and part 2 loses its control.

    The offset is drawn once per tag. If it were redrawn each bar the placebo
    book would be a different book every bar, every placebo episode would be a
    first episode, and the grade comparison would have a real arm and no
    matched arm to read it against.
    """
    books = [[(1, 100.0)] for _ in range(50)]
    unit = np.full(50, 1.0)
    made = B.placebo_books(books, unit, np.random.default_rng(0))
    prices = {round(p, 9) for book in made for _, p in book}
    assert len(prices) == 1
    assert abs(next(iter(prices)) - 100.0) >= B.SHIFT_LO


def test_a_placebo_does_not_wander_when_volatility_changes():
    """A placebo stored in units re-multiplies each bar and moves with volatility.

    A wandering level is reached more often in a volatile stretch, which is the
    confound the compression strata exist to remove - re-introduced inside the
    control, where it would read as the real arm being no better than the
    placebo for the wrong reason. The offset is fixed in price at first sight,
    so doubling the unit must not move the placebo.
    """
    books = [[(1, 100.0)] for _ in range(20)]
    unit = np.concatenate([np.full(10, 1.0), np.full(10, 4.0)])
    made = B.placebo_books(books, unit, np.random.default_rng(1))
    prices = {round(p, 9) for book in made for _, p in book}
    assert len(prices) == 1


def test_a_placebo_landing_on_a_real_level_is_dropped_rather_than_kept():
    """A placebo that is a level is not a placebo.

    With two real levels `SHIFT_LO` apart, some offsets land one placebo on the
    other real level. Those are refused, so the placebo arm never scores a
    touch of a genuine level and reports it as a control.
    """
    books = [[(1, 100.0), (2, 100.0 + B.SHIFT_LO)] for _ in range(20)]
    made = B.placebo_books(books, np.full(20, 1.0), np.random.default_rng(3))
    for book in made:
        for _, price in book:
            assert all(abs(price - real) >= B.CLEAR_VOL for real in (100.0, 100.0 + B.SHIFT_LO))


def test_two_levels_never_share_a_tag_even_when_one_is_dropped():
    """Splicing two levels' histories would invent the record under test.

    `_tagger` holds a reference to every object it has tagged, so a dropped
    level's address cannot be reused for a new one. Without the reference,
    CPython hands the same `id()` out again and the new level inherits the old
    one's episodes - which is a fabricated history, in the one variable this
    study grades on.
    """
    tag = B._tagger()
    first = tag(object())
    for _ in range(200):
        tag(object())
    assert tag(object()) != first


# ───────────────────────────── the estimators ─────────────────────────────


def test_the_auc_reads_a_half_on_a_constant_score_and_not_a_one():
    """The recorded defect in `conditional_holds.py`, pinned here.

    That file documents its own AUC reading **1.0000** for a constant arm. A
    cell where the grade has collapsed to one value carries no information, so
    the only correct answer is 0.5; 1.0 would make every degenerate cell in
    this study's grid read as a perfect predictor.
    """
    label = np.array([True, False, True, False, True, False])
    assert A._auc(np.ones(6), label) == pytest.approx(0.5)
    assert A._auc(np.array([2.0, 1.0, 2.0, 1.0, 2.0, 1.0]), label) == pytest.approx(1.0)


def test_a_cell_thinner_than_the_floor_reports_nothing_rather_than_a_gap():
    """The guard that a bjorgum gap of -0.0769 on 26 episodes got past.

    `grade_gap_for` first checked only the row count, so 209 rows spread over
    25 cells left almost every cell under `FLOOR`, and it returned a number
    computed from 26 episodes as though it were a measurement. The guard is on
    the mass that survived flooring, not on the rows that went in.
    """
    n = 150
    rows = B.Rows(
        tag=np.arange(n),
        bar=np.arange(n),
        block=np.arange(n),
        away=np.ones(n, dtype=np.int64),
        stratum=np.arange(n) % 25,
        shape=np.zeros(n, dtype=np.int64),
        held=np.tile([True, False], n // 2),
        decided=np.ones(n, dtype=bool),
        tie=np.zeros(n, dtype=bool),
        excursion=np.zeros(n),
        r=dict.fromkeys(B.TARGETS, np.zeros(n)),
        r_mtm=np.zeros(n),
        n_prev=np.ones(n, dtype=np.int64),
        sharp_share=np.linspace(0.0, 1.0, n),
        run_share=np.zeros(n),
        bar_share=np.zeros(n),
        hold_share=np.zeros(n),
        hold_dev=np.zeros(n),
    )
    assert A.grade_gap_for(rows, np.ones(n, dtype=bool), "sharp_share") is None


def test_the_implied_sample_grows_with_the_variance_at_a_fixed_mean():
    """Why every mean in the write-up carries its sd and its implied sample.

    Two arms with the same mean R and different per-trade sd do not rest on
    the same evidence. A score that selects sharper bounces selects larger
    moves, so it buys variance; `needed` is what makes that visible instead of
    letting two means be compared as equals.
    """
    rng = np.random.default_rng(0)
    block = np.arange(400)
    calm = A._money(0.1 + rng.normal(0, 1.0, 400), block, draws=50, seed=0)
    wild = A._money(0.1 + rng.normal(0, 3.0, 400), block, draws=50, seed=0)
    assert wild.sd > calm.sd
    assert wild.needed > 4 * calm.needed
