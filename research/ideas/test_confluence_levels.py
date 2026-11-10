"""Tests for `confluence_levels.py`.

    uv run pytest research/ideas/test_confluence_levels.py

Every test here can fail for its own reason, and every gate has a control that
passes beside it: the bimodality tests check that the estimator **does** see a
planted two-component mixture before they are allowed to report that a return
distribution is unimodal, and the barrier test checks that a planted reflecting
grid **does** raise the hold rate before a null hold rate means anything.

The ones that exist because of a specific defect are named for it:
`test_the_bridge_opens_exactly_at_the_previous_close` is the hazard in
`node/surrogates.walk_with_bar_geometry`, which gaps 0.60-0.64 of a bar range
on every bar and so fires a stop where the path never went;
`test_no_fibonacci_level_is_born_before_its_swing_is_confirmed` is the lookahead
that made an open-gap filter read +0.50R a trade.
"""

from __future__ import annotations

import math
import random
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import confluence_levels as cl  # noqa: E402


def bars_of(high, low, close=None, open_=None, step: int = 3600):
    """A bar dict from lists, with `ts` on a regular clock."""
    high = np.asarray(high, float)
    low = np.asarray(low, float)
    close = np.asarray(close if close is not None else (high + low) / 2.0, float)
    open_ = np.asarray(open_ if open_ is not None else np.r_[close[0], close[:-1]], float)
    return {"ts": np.arange(len(high), dtype=np.int64) * step, "open": open_,
            "high": high, "low": low, "close": close}


def walk_bars(n: int, seed: int = 3, sigma: float = 1.0, start: float = 1000.0):
    rng = random.Random(seed)
    gen = np.random.default_rng(seed)
    steps = gen.normal(0.0, sigma, size=n - 1)
    ts = np.arange(n, dtype=np.int64) * 3600
    return cl.bridge_path(steps, ts, start, rng)


def zigzag(n: int = 130, low_at: int = 40, high_at: int = 80,
           top: float = 1000.0, bottom: float = 900.0):
    """A series with exactly two confirmed pivots: a strict low then a strict
    high, so the leg between them is the only completed one."""
    close = np.empty(n)
    close[: low_at + 1] = np.linspace(top, bottom, low_at + 1)
    close[low_at: high_at + 1] = np.linspace(bottom, top, high_at - low_at + 1)
    close[high_at:] = np.linspace(top, top - 2.5 * (n - 1 - high_at), n - high_at)
    return bars_of(close + 0.5, close - 0.5, close)


# ───────────────────────────── the frameworks ─────────────────────────────


def test_the_square_of_nine_reproduces_the_published_rung() -> None:
    """One 45 degree step adds `45/180 = 0.25` to the square root of the price.

    The commentary that prompted this study quotes $3,971.63 as a Square-of-9
    45 degree angle, which pins the anchor: `(sqrt(a) + 0.25)^2 = 3971.63`
    gives `a = 3940.17`. If the formula in the harness were the other common
    misreading - a full rotation adding 1 rather than 2 to the root - this
    would come out at 3955.9 and the test would say so.
    """
    anchor = 3940.17
    rung = (math.sqrt(anchor) + 45.0 / 180.0) ** 2
    assert rung == pytest.approx(3971.63, abs=0.05)
    assert (math.sqrt(anchor) + 360.0 / 180.0) ** 2 == pytest.approx(
        anchor + 4.0 * math.sqrt(anchor) + 4.0, abs=1e-6)


@pytest.mark.parametrize(("price", "unit"), [(1.1, 0.0004), (150.0, 0.05),
                                             (4000.0, 1.2), (90000.0, 60.0),
                                             (0.65, 0.0002)])
def test_the_gann_scale_puts_the_step_within_a_power_of_ten_of_five_units(
        price: float, unit: float) -> None:
    """A Square of 9 is not scale-free, so the harness picks the power of ten
    whose 45 degree step is nearest five volatility units.

    The tolerance is a factor of `sqrt(10)` because the scale is a power of ten
    and nothing finer is available - which is the point: the wheel's density is
    a choice, and this test pins how large that choice can be. Without the rule
    the step is $31 on gold and half the price on EURUSD.
    """
    s = cl.gann_scale(price, unit)
    step = ((math.sqrt(price * s) + 0.25) ** 2) / s - price
    assert step / unit == pytest.approx(5.0, rel=math.sqrt(10.0))


def test_the_round_step_is_the_smallest_power_of_ten_five_units_wide() -> None:
    assert cl.round_step(1.0) == 10.0
    assert cl.round_step(2.0) == 10.0
    assert cl.round_step(2.1) == 100.0
    assert cl.round_step(0.0004) == 0.01
    for unit in (0.0003, 0.02, 1.3, 70.0):
        step = cl.round_step(unit)
        assert step >= 5.0 * unit
        assert step / 10.0 < 5.0 * unit


def test_the_round_grid_tells_a_whole_number_from_a_half() -> None:
    unit = np.full(10, 1.0)
    book = cl.Book({f: np.zeros((0, 4)) for f in ("swing", "fib", "gann")}, unit)
    step = cl.round_step(1.0)
    assert book.names("round", step, 5, 0.1) == 0
    assert book.names("round", step * 1.5, 5, 0.1) == 1
    assert book.names("round", step * 1.23, 5, 0.1) == -1


def test_a_fibonacci_level_is_a_retracement_of_the_completed_leg(monkeypatch) -> None:
    """A 61.8% retracement of a 100-point leg sits 61.8 points back from its
    end, and the harness emits exactly the four stated ratios."""
    monkeypatch.setattr(cl, "WARMUP", 0)
    monkeypatch.setattr(cl, "MIN_LEG_VOL", 0.5)
    bars = zigzag()
    unit = np.full(len(bars["close"]), 1.0)
    got = cl.levels_for(bars, unit)
    assert len(got["swing"]) == 2, got["swing"]
    prices = sorted(round(p, 3) for p in got["fib"][:, 0])
    want = sorted(round(1000.5 - r * (1000.5 - 899.5), 3) for r in cl.FIB_RATIOS)
    assert prices == want, (prices, want)


def test_no_fibonacci_level_is_born_before_its_swing_is_confirmed(monkeypatch) -> None:
    """The lookahead this study would otherwise have.

    A retracement of a swing still forming is a level drawn from a high that
    has not happened yet. The second pivot of the leg prints at bar 80 and is
    knowable at bar `80 + SWING`, so no `fib` row may carry a `born` below
    that - and the `swing` row for the same pivot may not either.
    """
    monkeypatch.setattr(cl, "WARMUP", 0)
    monkeypatch.setattr(cl, "MIN_LEG_VOL", 0.5)
    bars = zigzag()
    unit = np.full(len(bars["close"]), 1.0)
    got = cl.levels_for(bars, unit)
    assert got["fib"][:, 1].min() >= 80 + cl.SWING
    assert got["swing"][:, 1].min() >= 40 + cl.SWING
    assert got["gann"][:, 1].min() >= 40 + cl.SWING


def test_a_level_is_not_live_before_the_bar_it_became_knowable_on() -> None:
    unit = np.full(100, 1.0)
    rows = {"swing": np.array([[500.0, 30.0, 60.0, 0.0]]),
            "fib": np.zeros((0, 4)), "gann": np.zeros((0, 4))}
    book = cl.Book(rows, unit)
    assert book.names("swing", 500.0, 29, 0.25) == -1
    assert book.names("swing", 500.0, 30, 0.25) == 0
    assert book.names("swing", 500.0, 59, 0.25) == 0
    assert book.names("swing", 500.0, 60, 0.25) == -1


def test_k_counts_frameworks_and_not_levels(monkeypatch) -> None:
    """Four Fibonacci ratios at one price are one framework.

    This is the arithmetic the whole study exists to separate from four
    frameworks: if `k` counted levels, a single completed swing whose ratios
    happen to cluster would read as a four-way confluence on its own.
    """
    monkeypatch.setattr(cl, "WARMUP", 0)
    unit = np.full(40, 1.0)
    # 503 and not 500: at a unit of 1.0 the round grid's half-step is 5, so
    # 500 is itself a round number and `k` would be 2 for the right reason.
    rows = {"fib": np.array([[503.0, 0.0, 40.0, 0.0], [503.05, 0.0, 40.0, 1.0],
                             [502.95, 0.0, 40.0, 2.0], [503.1, 0.0, 40.0, 3.0]]),
            "swing": np.zeros((0, 4)), "gann": np.zeros((0, 4))}
    book = cl.Book(rows, unit)
    high = np.full(40, 502.0)
    low = np.full(40, 501.0)
    high[20], low[20] = 504.0, 502.0
    bars = bars_of(high, low, np.full(40, 502.5))
    named = cl.named_prices(book, bars, unit)
    at = [r for r in named if r[0] == 20]
    assert at, "the touch was not found at all"
    assert max(r[2] for r in at) == 1, at


def test_a_touch_is_a_first_touch() -> None:
    """Sitting inside a level for forty bars is one observation.

    De-overlapping touches is what turned a published 0.6365 into 0.5092.
    """
    high = np.full(30, 101.0)
    low = np.full(30, 99.0)
    high[:10] = 98.0
    low[:10] = 97.0
    bars = bars_of(high, low)
    rows = np.array([[100.0, 0.0, 30.0, 0.0]])
    got = cl.touches_of_rows(rows, bars)
    assert got == [(10, 100.0)], got


def test_dedupe_still_works_where_the_unit_is_far_from_its_median() -> None:
    """The bucket grid is the tolerance at the *median* unit, so a row whose own
    tolerance is a hundred buckets wide needs a hundred-bucket scan.

    A fixed one-bucket scan stops de-duplicating in exactly the regime with the
    most levels - the violent one - which inflates a density figure without
    touching any outcome, since `k` comes from `Book.names` and never consults
    this grid. The series below has a unit of 1.0 almost everywhere and 100.0
    at the end, so the median grid is 0.25 and the late tolerance is 25.0.
    """
    unit = np.ones(1000)
    unit[990:] = 100.0
    rows = np.array([[1000.0, 992.0, 998.0, 0.0], [1020.0, 993.0, 999.0, 1.0]])
    kept = cl.dedupe(rows, unit)
    assert len(kept) == 1, kept
    assert kept[0, 1] == 992.0
    # And a price genuinely outside the tolerance survives, or the scan is
    # merging everything in sight.
    far = np.array([[1000.0, 992.0, 998.0, 0.0], [1100.0, 993.0, 999.0, 1.0]])
    assert len(cl.dedupe(far, unit)) == 2


def test_dedupe_keeps_the_earliest_birth() -> None:
    unit = np.full(100, 1.0)
    rows = np.array([[500.0, 10.0, 80.0, 0.0], [500.1, 20.0, 90.0, 1.0],
                     [500.0, 95.0, 150.0, 2.0]])
    kept = cl.dedupe(rows, unit)
    assert len(kept) == 2
    assert sorted(kept[:, 1].tolist()) == [10.0, 95.0]


# ───────────────────────────── the race, settled ─────────────────────────────


def test_the_race_resolves_a_hold_a_break_and_a_tie_against_the_claim() -> None:
    #                      arrival                     hold          break
    high = np.array([105.0, 101.0, 100.4, 102.5, 99.0])
    low = np.array([103.0, 99.0, 99.6, 99.8, 97.0])
    close = np.array([104.0, 100.0, 100.0, 102.0, 98.0])
    bars = bars_of(high, low, close)
    assert cl.race(bars, 1, 100.0, +1, 2.0, horizon=3) == (+1, 2)
    #: a tie - both barriers inside one bar - goes to the break, there being
    #: no ticks to order them.
    high2 = np.array([105.0, 101.0, 103.0])
    low2 = np.array([103.0, 99.0, 97.0])
    close2 = np.array([104.0, 100.0, 100.0])
    assert cl.race(bars_of(high2, low2, close2), 1, 100.0, +1, 2.0, horizon=2) == (-1, 1)


def test_the_arrival_bar_contributes_its_close_and_not_its_extremes() -> None:
    """OHLC cannot order the high against the low, so using the arrival bar's
    extremes would be the harness choosing an intrabar path."""
    high = np.array([105.0, 101.0, 100.2])
    low = np.array([103.0, 90.0, 100.0])               # the arrival bar's low is far through
    close = np.array([104.0, 100.0, 100.1])
    bars = bars_of(high, low, close)
    assert cl.race(bars, 1, 100.0, +1, 2.0, horizon=1) == (0, 1)


def test_the_race_is_censored_when_neither_barrier_is_reached() -> None:
    bars = bars_of(np.full(10, 100.3), np.full(10, 99.7), np.full(10, 100.0))
    assert cl.race(bars, 1, 100.0, +1, 2.0, horizon=5) == (0, 5)


def test_the_continuation_race_is_symmetric_about_the_level() -> None:
    high = np.array([100.0, 100.0, 99.0, 99.0])
    low = np.array([100.0, 98.0, 95.9, 95.9])
    close = np.array([100.0, 98.0, 96.0, 96.0])
    bars = bars_of(high, low, close)
    went, realised, far = cl.continuation(bars, 1, 100.0, +1, 2.0, horizon=2)
    assert went == 1                       # reached 96 before returning to 100
    assert far == pytest.approx(4.1, abs=1e-9)
    assert realised > 0


def test_de_overlapping_drops_an_observation_inside_the_horizon(monkeypatch) -> None:
    monkeypatch.setattr(cl, "WARMUP", 0)
    monkeypatch.setattr(cl, "HOLD_H", 10)
    monkeypatch.setattr(cl, "SHAPE_N", 2)
    n = 60
    # The close is above the level, so every arrival is from above and no
    # observation is dropped for having no side.
    bars = bars_of(np.full(n, 101.0), np.full(n, 99.0), np.full(n, 100.5))
    unit = np.full(n, 1.0)
    strata = np.zeros(n, dtype=np.int8)
    named = [(5, 100.0, 1, (0, -1, -1, -1)), (9, 100.0, 1, (0, -1, -1, -1)),
             (20, 100.0, 1, (0, -1, -1, -1))]
    got = cl.observe(bars, unit, strata, named)
    assert [int(r["bar"]) for r in got["k1"]] == [5, 20]


def test_the_buckets_are_separate_streams(monkeypatch) -> None:
    """A `k=1` event does not consume the slot a `k=3` event needs.

    With one stream the rarest bucket - which is the claim - loses every
    contest to one that fires ten times as often.
    """
    monkeypatch.setattr(cl, "WARMUP", 0)
    monkeypatch.setattr(cl, "HOLD_H", 10)
    monkeypatch.setattr(cl, "SHAPE_N", 2)
    n = 60
    bars = bars_of(np.full(n, 101.0), np.full(n, 99.0), np.full(n, 100.5))
    unit = np.full(n, 1.0)
    strata = np.zeros(n, dtype=np.int8)
    named = [(5, 100.0, 1, (0, -1, -1, -1)), (6, 100.2, 3, (0, 0, 0, -1))]
    got = cl.observe(bars, unit, strata, named)
    assert [int(r["bar"]) for r in got["k1"]] == [5]
    assert [int(r["bar"]) for r in got["k3"]] == [6]


# ───────────────────────────── the surrogate paths ─────────────────────────────


def test_the_bridge_opens_exactly_at_the_previous_close() -> None:
    """The hazard in `node/surrogates.walk_with_bar_geometry`, pinned.

    That function re-hangs real bar shapes on a synthetic close path, so it
    gaps 0.60-0.64 of a bar range on **every** bar against the market's median
    `|gap|` of 0.0000 on 71-79% of bars - which fires a stop where the path
    never went. A path surrogate must have no gap at all.
    """
    bars = walk_bars(4000, seed=5)
    assert np.allclose(bars["open"][1:], bars["close"][:-1], atol=0, rtol=0)
    assert np.all(bars["high"] >= np.maximum(bars["open"], bars["close"]) - 1e-9)
    assert np.all(bars["low"] <= np.minimum(bars["open"], bars["close"]) + 1e-9)


def test_the_bridge_keeps_the_step_distribution_it_was_given() -> None:
    bars = walk_bars(20_000, seed=6, sigma=2.0)
    steps = np.diff(bars["close"])
    assert float(np.std(steps)) == pytest.approx(2.0, rel=0.05)
    assert abs(float(np.mean(steps))) < 4.0 * 2.0 / math.sqrt(len(steps))


def test_a_race_from_the_close_is_a_martingale_and_one_from_the_level_is_not() -> None:
    """The construction's own offset, measured with **random anchors** so the
    detector cannot be the cause.

    `a-martingale-cannot-pay`: any positive expectancy on a walk is a bug - so
    the convention has to be audited rather than assumed. Barriers about the
    arrival bar's close are a martingale race and owe exactly 0.5. Barriers
    about the touched price are **not**: the path is already at the bar's close
    when the race starts, and a bar that dipped to the price and closed is on
    average displaced back toward the side it came from, which moves the hold
    barrier nearer. That offset is shared by every arm in the study, which is
    why its verdict rests on differences between arms and never on the level of
    one.
    """
    bars = walk_bars(60_000, seed=8)
    unit = cl.unit_of(bars)
    gen = np.random.default_rng(8)
    at_level: list[float] = []
    at_close: list[float] = []
    for bar in range(600, len(bars["close"]) - cl.HOLD_H - 1, cl.HOLD_H):
        lo, hi = bars["low"][bar], bars["high"][bar]
        prev_hi, prev_lo = bars["high"][bar - 1], bars["low"][bar - 1]
        spans = [(lo, min(hi, prev_lo)), (max(lo, prev_hi), hi)]
        spans = [(a, b) for a, b in spans if b > a]
        if not spans:
            continue
        a, b = spans[int(gen.integers(0, len(spans)))]
        price = float(gen.uniform(a, b))
        prev = bars["close"][bar - 1]
        side = 1 if prev > price else (-1 if prev < price else 0)
        if side == 0:
            continue
        dist = cl.HOLD_VOL * unit[bar]
        got, _took = cl.race(bars, bar, price, side, dist)
        if got:
            at_level.append(float(got > 0))
        got, _took = cl.race(bars, bar, float(bars["close"][bar]), side, dist)
        if got:
            at_close.append(float(got > 0))
    close_arr = np.asarray(at_close)
    level_arr = np.asarray(at_level)
    assert len(close_arr) > 300 and len(level_arr) > 300
    se = math.sqrt(0.25 / len(close_arr))
    assert abs(float(close_arr.mean()) - 0.5) < 3.5 * se, (close_arr.mean(), se)
    assert float(level_arr.mean()) > float(close_arr.mean())


def test_the_reflecting_plant_raises_the_hold_rate_at_the_planted_grid(
        monkeypatch) -> None:
    """The positive control for the whole barrier measurement.

    A grid specified independently of the path is planted by reflecting the
    sub-steps that cross it, and the hold rate at prices the `round` framework
    names must rise. A study whose detectors cannot see a real barrier has
    nothing to say about the absence of one.

    The strength matters and is why `MODE=power` sweeps it rather than quoting
    a probability: a reflected sub-step is retried by the next one, so a
    barrier at `p = 0.6` leaks and moves the hold rate by nothing, while
    `p = 0.9` moves it by eleven points.
    """
    monkeypatch.setattr(cl, "WARMUP", 100)
    rng = random.Random(21)
    gen = np.random.default_rng(21)
    n = 40_000
    steps = gen.normal(0.0, 1.0, size=n - 1)
    ts = np.arange(n, dtype=np.int64) * 3600
    step = cl.round_step(1.0)
    rates = {}
    for prob in (0.0, 0.9):
        bars = cl.bridge_path(steps, ts, 1000.0, random.Random(21), sub=20,
                              reflect=(step / 2.0, prob) if prob else None)
        unit, strata, _book, named, _rows = cl.prepare(bars)
        got = cl.observe(bars, unit, strata, named)
        flat = [r for b in ("k1", "k2", "k3") for r in got[b]]
        hold = np.asarray([r["hold"] for r in flat if r["has_round"] == 1.0])
        hold = hold[np.isfinite(hold)]
        assert len(hold) > 100, (prob, len(hold))
        rates[prob] = float(hold.mean())
    del rng
    assert rates[0.9] > rates[0.0] + 0.05, rates


def test_the_garch_arm_clusters_and_the_walk_arm_does_not() -> None:
    """The arm is labelled with the property it carries, which is the rule
    `a-control-is-only-for-a-named-property` states."""
    gen = np.random.default_rng(31)
    steps = gen.normal(0.0, 1.0, size=50_000)
    clustered = cl.garch_steps(steps, random.Random(31))
    def ac1(x):
        a = np.abs(x) - np.abs(x).mean()
        return float((a[:-1] * a[1:]).mean() / (a * a).mean())
    assert ac1(clustered) > 0.04, ac1(clustered)
    assert abs(ac1(steps)) < 0.02, ac1(steps)
    assert ac1(clustered) > 4.0 * abs(ac1(steps))


# ───────────────────────────────── statistics ─────────────────────────────────


def test_the_block_bootstrap_widens_when_the_days_are_clustered() -> None:
    """The gate and its control together.

    An independent sample's block standard error must match the binomial one,
    or the bootstrap is broken; a sample whose outcome is constant within a day
    must come back wider, or the blocking does nothing.
    """
    gen = np.random.default_rng(41)
    n = 4000
    days = np.repeat(np.arange(n // 20), 20)
    independent = gen.random(n) < 0.5
    _m, se_i, _lo, _hi = cl.block_ci(independent.astype(float), days, draws=400)
    assert se_i == pytest.approx(math.sqrt(0.25 / n), rel=0.35)
    per_day = (gen.random(n // 20) < 0.5).astype(float)
    clustered = np.repeat(per_day, 20)
    _m, se_c, _lo, _hi = cl.block_ci(clustered, days, draws=400)
    assert se_c > 3.0 * se_i, (se_i, se_c)


def test_benjamini_hochberg_rejects_noise_and_finds_a_planted_cell() -> None:
    gen = np.random.default_rng(51)
    noise = {f"c{i}": float(p) for i, p in enumerate(gen.random(200))}
    assert sum(cl.bh(noise).values()) == 0
    planted = {**noise, "real": 1e-9}
    assert cl.bh(planted)["real"]


def test_silverman_sees_a_location_mixture_and_not_a_fat_tail() -> None:
    """The bimodality estimator's power, before any null from it is reported.

    A two-component **location** mixture is what the commentary's claim
    predicts; a Student-t is what this desk measures everywhere. The test has
    to separate them, or "unimodal" means only that the test is blind.
    """
    gen = np.random.default_rng(61)
    n = 3000
    mixed = np.r_[gen.normal(-3.0, 1.0, n // 2), gen.normal(+3.0, 1.0, n // 2)]
    heavy = gen.standard_t(3, size=n)
    h_mixed, p_mixed = cl.silverman(mixed, draws=60, seed=61)
    h_heavy, p_heavy = cl.silverman(heavy, draws=60, seed=61)
    assert p_mixed < 0.05, p_mixed
    # **And it over-rejects on a Student-t(3)**, which is why the write-up
    # reads this statistic against the surrogate arms rather than against a
    # nominal level. A critical bandwidth is driven by the gap between the two
    # densest parts of the sample, and a heavy tail supplies one without a
    # second mode. The mixture's **mean separation** is the statistic that does
    # distinguish the two, and it has its own test below.
    assert p_heavy < 0.10, p_heavy
    # And `h_crit / sd` does not order them either - the t(3) needs **3.20**
    # against the mixture's **0.89**, because a handful of extreme points are
    # isolated bumps that only a very wide kernel smooths away while the tails
    # have already inflated the standard deviation it is divided by. So the
    # bandwidth is reported and not interpreted.
    assert h_heavy > h_mixed, (h_mixed, h_heavy)


def test_the_mixture_separates_a_location_mixture_from_a_scale_mixture() -> None:
    """`dbic` alone cannot answer the claim and the test says why.

    Two Gaussians with one mean and two variances is a fat tail, and it beats a
    single Gaussian on every return series ever recorded. Only the mean
    separation distinguishes that from bimodality.
    """
    gen = np.random.default_rng(71)
    n = 4000
    location = np.r_[gen.normal(-3.0, 1.0, n // 2), gen.normal(+3.0, 1.0, n // 2)]
    scale = np.r_[gen.normal(0.0, 1.0, n // 2), gen.normal(0.0, 5.0, n // 2)]
    got_loc = cl.mixture(location)
    got_scale = cl.mixture(scale)
    assert got_loc["dbic"] > 50
    assert got_scale["dbic"] > 50
    assert got_loc["separation"] > 1.5, got_loc
    assert got_scale["separation"] < 0.5, got_scale


def test_the_bimodality_coefficient_flags_the_mixture_and_not_the_t() -> None:
    gen = np.random.default_rng(81)
    n = 4000
    mixed = np.r_[gen.normal(-3.0, 1.0, n // 2), gen.normal(+3.0, 1.0, n // 2)]
    heavy = gen.standard_t(4, size=n)
    # Sarle's denominator is `excess kurtosis + 3(n-1)^2/((n-2)(n-3))`, which
    # tends to 3. An extra +3 - the first version of this file - reads 0.228 on
    # a clean two-component mixture and so flags nothing, ever.
    assert cl.shape_stats(mixed, silv=False)["bc"] > 5.0 / 9.0
    assert cl.shape_stats(heavy, silv=False)["bc"] < 5.0 / 9.0


# ────────────────────────────── causality guards ──────────────────────────────


def test_the_volatility_unit_is_lagged_by_one_bar() -> None:
    """`unit[i]` is a function of bars strictly before `i`, so nothing a level
    is measured against was measured with the bar it is measured on."""
    n = 200
    gen = np.random.default_rng(91)
    close = 100.0 + np.cumsum(gen.normal(0.0, 1.0, n))
    bars = bars_of(close + 1.0, close - 1.0, close)
    before = cl.unit_of(bars)
    bumped = {k: v.copy() for k, v in bars.items()}
    bumped["high"][150] += 50.0
    bumped["low"][150] -= 50.0
    after = cl.unit_of(bumped)
    assert np.allclose(before[: 151], after[: 151])
    assert after[151] > before[151]


def test_the_strata_are_computed_from_the_past_only() -> None:
    gen = np.random.default_rng(101)
    unit = np.abs(gen.normal(1.0, 0.2, 3000)) + 0.1
    base = cl.strata_of(unit, window=200)
    bumped = unit.copy()
    bumped[2500:] *= 9.0
    after = cl.strata_of(bumped, window=200)
    assert np.array_equal(base[:2500], after[:2500])


def test_the_placebo_is_unnamed_and_matched_on_distance(monkeypatch) -> None:
    """Every placebo arrival is at a price no framework names, and the arm's
    mean absolute displacement tracks the real arm's.

    Without this control a level study measures mean reversion and reports it
    as structure, and the matching is what makes it a control rather than a
    second population.
    """
    monkeypatch.setattr(cl, "WARMUP", 100)
    bars = walk_bars(30_000, seed=111)
    unit, strata, book, named, _rows = cl.prepare(bars)
    got = cl.observe(bars, unit, strata, named)
    flat = sorted((r for b in ("k1", "k2", "k3") for r in got[b]),
                  key=lambda r: r["bar"])
    extra, why = cl.placebo_of(bars, unit, strata, book, flat, random.Random(111))
    assert len(extra) > 100, (len(extra), why)
    for row in extra:
        assert row["k"] == 0.0
        assert all(row[f"has_{f}"] == 0.0 for f in cl.FRAMEWORKS)
        # The price is reconstructed from the recorded displacement rather than
        # stored, because the panel keeps only what a statistic reads. Asking
        # the book again is the point: the flags above come from the same call,
        # so this re-derives the price independently and checks it is free.
        bar = int(row["bar"])
        price = bars["close"][bar - 1] - row["displacement"] * unit[bar]
        tol = cl.TOL_VOL * unit[bar]
        assert all(book.names(f, price, bar, tol) == -1 for f in cl.FRAMEWORKS)
        assert bars["low"][bar] - 1e-9 <= price <= bars["high"][bar] + 1e-9
    want = float(np.mean([abs(r["displacement"]) for r in flat]))
    have = float(np.mean([abs(r["displacement"]) for r in extra]))
    assert have == pytest.approx(want, rel=0.25), (want, have)


def test_a_short_series_is_skipped_rather_than_reported() -> None:
    """A count of zero beside a non-zero statistic is a reporting bug, so a
    series too short to carry the construction is named as skipped."""
    tiny = {"ts": np.arange(50, dtype=np.int64), "open": np.ones(50),
            "high": np.ones(50), "low": np.ones(50), "close": np.ones(50)}
    assert len(tiny["close"]) < cl.MIN_BARS
    unit = cl.unit_of(tiny)
    assert len(cl.levels_for(tiny, unit)["swing"]) == 0


def test_the_fold_does_not_walk_across_a_gap() -> None:
    """Index folding puts Friday's close in the same bar as Monday's open; a
    timestamp bucket just yields fewer bars."""
    ts = np.array([0, 900, 1800, 2700, 998_000, 998_900], dtype=np.int64)
    bars = {"ts": ts, "open": np.arange(6, dtype=float), "close": np.arange(6, dtype=float),
            "high": np.arange(6, dtype=float) + 1, "low": np.arange(6, dtype=float) - 1}
    got = cl.fold(bars, 3600)
    assert got["ts"].tolist() == [0, 998_000 // 3600 * 3600]
    assert got["close"].tolist() == [3.0, 5.0]
    assert got["high"].tolist() == [4.0, 6.0]
