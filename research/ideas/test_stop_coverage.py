"""Does the stop-coverage harness measure what it claims to measure?

Run with `uv run pytest research/ideas/test_stop_coverage.py`; `testpaths` is
`tests`, so these do not run in the suite and are not meant to.

Three of these are the ones that would catch a wrong answer rather than a
crash, and they are the reason the file exists:

* **the scale control must read exactly nothing.** The excursion is divided by
  a sigma estimated from the same returns, so multiplying every price change
  by ten cannot move a coverage. If it does, the unit has a lookahead or a
  price-level dependence - the class
  `a-synthetic-at-price-one-hides-scale-bugs` records, where relative sd and
  price offset coincide at price 1.0 and the bug is invisible.
* **the reflection prediction must hold on a walk.** A driftless walk has
  `P(min <= -a) = 2 Phi(-a / sigma)`, which is identically `P(|X| >= a)`, so
  `student_stop` is the one-bar excursion quantile and not only the one-bar
  band. That is the reproduction arm, and if it fails the panel's `H` = 1
  column means nothing.
* **the plants must move what they claim and nothing else**, with the zero
  cell empty, because a plant whose zero control reads an effect makes its
  question *untested* rather than null.
"""

import math
import random

import numpy as np
import pytest

import research.ideas.level_shield as L
import research.ideas.stop_coverage as S
from till_infinity.risk.quantiles import TAU, student_stop


def walk(n: int = 6_000, *, seed: int = 7, sigma: float = 0.004, mu: float = 0.0,
         price: float = 1.2, sub: int = 1) -> L.Series:
    """A Gaussian walk with bars, as a `Series`.

    `sub` is the number of sub-bar increments each bar is built from, so a bar
    has a **real** high and low rather than the two closes. It matters for
    exactly one reason and the reason is a measured bias, not tidiness: at
    `sub` 1 a bar's extremes *are* its closes, so the one-bar adverse excursion
    is the negative part of the return and reads `Phi(-a)`, while a finely
    sampled path reads the reflection answer `2 Phi(-a)` - **a factor of two in
    the one-bar coverage**. Real bars sit between, closer to the second, and the
    panel's `H` = 1 column has to be read knowing which end it is near.
    """
    rng = random.Random(seed)
    step = sigma / math.sqrt(max(1, sub))
    drift = mu * sigma / max(1, sub)
    here = math.log(price)
    opens, highs, lows, closes = [], [], [], []
    for _ in range(n):
        opens.append(here)
        hi = lo = here
        for _ in range(max(1, sub)):
            here += rng.gauss(drift, step)
            hi = max(hi, here)
            lo = min(lo, here)
        highs.append(hi)
        lows.append(lo)
        closes.append(here)
    return L.Series(
        feed="walk",
        venue="TEST",
        interval="1d",
        ts=np.arange(n, dtype=float) * 86_400.0,
        open=np.exp(np.asarray(opens)),
        high=np.exp(np.asarray(highs)),
        low=np.exp(np.asarray(lows)),
        close=np.exp(np.asarray(closes)),
    )


# ────────────────────────────── the unit ──────────────────────────────


def test_the_unit_is_the_one_production_divides_by():
    """`deciding.py` computes `unit = vol_bps / 1e4 * entry` with `vol_bps` a
    per-bar return sigma, so the incumbent's 3.0 is three of *this*. A walk at
    a known sigma has to read that sigma back, or the stop and the excursion
    are in two units and both readings look fine."""
    series = walk(sigma=0.004)
    got = S.sigma_close(series)[S.WARMUP:]

    assert float(np.median(got)) == pytest.approx(0.004, rel=0.10)


def test_both_unit_estimators_measure_the_same_quantity():
    """Parkinson's constant is what makes `log(high/low)` an estimator of the
    return sigma rather than of the range. On real bars the two differ by
    1.015x on eurusd and **0.755x on gold**, which is why the panel carries
    both; on a walk whose bars are drawn from that sigma they must agree, or
    one of them is measuring something else."""
    series = walk(sigma=0.004, sub=20)
    close = float(np.median(S.sigma_close(series)[S.WARMUP:]))
    ranged = float(np.median(S.sigma_range(series)[S.WARMUP:]))

    assert ranged == pytest.approx(close, rel=0.25), f"close {close:.5f} range {ranged:.5f}"


def test_the_unit_is_causal():
    """The whole study is a one-step-ahead claim. A sigma that has seen bar
    `i` makes the coverage at bar `i` unreadable, and the failure is silent:
    an in-sample sigma reads *better* calibrated, which is the direction that
    looks like a result."""
    series = walk()
    base = S.sigma_close(series)
    moved = list(series.close)
    moved[3_000] *= 1.5
    bumped = S.sigma_close(
        L.Series(
            feed=series.feed,
            venue=series.venue,
            interval=series.interval,
            ts=series.ts,
            open=series.open,
            high=series.high,
            low=series.low,
            close=np.asarray(moved),
        )
    )

    assert bumped[3_000] == pytest.approx(base[3_000]), "bar 3000 moved its own sigma"
    assert bumped[3_001] != pytest.approx(base[3_001]), "and must move the next one"


# ───────────────────────────── the excursion ─────────────────────────────


def test_the_excursion_is_the_distance_against_the_trade_on_each_side():
    """`dn` is adverse for a long and `up` for a short. A single pooled
    excursion would be a stop for both sides at once, which is the thing
    `fear-greed.md`'s measured asymmetry says cannot be right."""
    series = walk(n=600, sub=20)
    sigma = S.sigma_close(series)
    exc = S.excursions(series, sigma, 20)

    assert len(exc.anchors) > 0
    assert (exc.dn >= 0.0).all() and (exc.up >= 0.0).all()
    assert exc.side(1) is exc.dn
    assert exc.side(-1) is exc.up


def test_the_anchors_do_not_overlap_by_default():
    """At step 1 the window at `t+1` shares `H - 1` of its bars with the
    window at `t`, so an online estimator updated on `t` before setting
    `t+1`'s stop has already seen most of the outcome it is about to be scored
    on. The default is the non-overlapping stream for that reason."""
    series = walk(n=1_200)
    sigma = S.sigma_close(series)

    spaced = S.excursions(series, sigma, 20)
    dense = S.excursions(series, sigma, 20, step=1)

    assert int(np.diff(spaced.anchors).min()) == 20
    assert int(np.diff(dense.anchors).min()) == 1
    assert len(dense.anchors) > 15 * len(spaced.anchors)


def test_a_gap_away_from_the_entry_is_counted_rather_than_dropped():
    """Price never trading back through the entry is a real outcome and goes
    in as a zero, which is what `Quantile.observe` accepts and why it refuses
    a negative one. The count is reported because a cell where it is common is
    a cell where the entry is not where this study thinks it is."""
    series = walk(n=600)
    high = series.close * 1.0
    low = series.close * 1.0
    gapped = L.Series(
        feed=series.feed,
        venue=series.venue,
        interval=series.interval,
        ts=series.ts,
        open=series.open,
        high=high * 1.01,
        low=low * 1.005,
        close=series.close,
    )
    exc = S.excursions(gapped, S.sigma_close(series), 5)

    assert exc.clamped_dn > 0, "every window is above the entry, so every long gapped"
    assert exc.dn.min() == 0.0


# ─────────────────────── the reproduction arm ───────────────────────


def test_the_reflection_principle_sets_the_one_bar_stop_on_a_walk():
    """**The reproduction arm, and the panel's `H` = 1 column rests on it.**
    For Brownian motion `P(min <= -a) = 2 Phi(-a / sigma)`, which is
    identically `P(|X| >= a)` - so the `tau` quantile of the one-sided running
    minimum over one bar *equals* the `tau` quantile of the two-sided
    endpoint, which is exactly what `student_stop` returns. A Gaussian walk's
    0.90 quantile of `|X|` is 1.645 sigma, so a stop there must be reached
    about one bar in ten on a finely sampled path.
    """
    series = walk(n=20_000, sub=100)
    exc = S.excursions(series, S.sigma_close(series), 1, step=1)
    gaussian = 1.6449

    for side in (1, -1):
        rate = float((exc.side(side) >= gaussian).mean())
        assert rate == pytest.approx(0.10, abs=0.02), f"side {side} reached {rate:.3f}"


def test_a_bar_sampled_too_coarsely_halves_its_own_excursion():
    """**The measured bias in the `H` = 1 column, and it is a factor of two.**
    Where a bar's extremes are its own two closes the adverse excursion is the
    negative part of the return and reads `Phi(-a)`; where the path inside the
    bar is sampled it reads the reflection answer `2 Phi(-a)`. A recorded bar
    is between, so a one-bar coverage can be read as a statement about the
    tail only once it is known which end it is near. This is the discreteness
    the panel reports rather than assumes away."""
    coarse = walk(n=20_000, sub=1)
    fine = walk(n=20_000, sub=100)
    gaussian = 1.6449

    low = float((S.excursions(coarse, S.sigma_close(coarse), 1, step=1).dn >= gaussian).mean())
    high = float((S.excursions(fine, S.sigma_close(fine), 1, step=1).dn >= gaussian).mean())

    assert low == pytest.approx(0.05, abs=0.01), f"closes only read {low:.3f}"
    assert high == pytest.approx(0.10, abs=0.02), f"sampled path read {high:.3f}"
    assert high / low == pytest.approx(2.0, abs=0.3)


def test_the_t_stop_is_tighter_than_the_gaussian_one_and_so_reads_tighter():
    """`student_stop` at dof 4 is 1.51 against a Gaussian 1.645 - the t is
    *tighter* at unit variance, because scaling to unit variance shrinks the
    body to pay for the tails. On Gaussian excursions it therefore reads too
    tight, and the panel's `t-fixed` column has to be read against that rather
    than against 0.100 alone: a t stop on a market with thinner tails than
    dof 4 is expected to overshoot its target."""
    assert student_stop(TAU, 4.0) < 1.6449

    series = walk(n=20_000, sub=100)
    exc = S.excursions(series, S.sigma_close(series), 1, step=1)
    rate = float((exc.dn >= student_stop(TAU, 4.0)).mean())

    assert rate > 0.10, f"a tighter stop must be reached more often, got {rate:.3f}"


def test_the_sqrt_h_correction_is_the_right_shape_on_a_walk():
    """`student_stop` carries no horizon, so at `H` bars it is a one-bar
    quantity answering an `H`-bar question - and the correction a diffusive
    baseline is entitled to is `sqrt(H)`, by the same reflection argument. On
    a walk the empirical quantile must track `sqrt(H)`, so the fixed arm's
    coverage error at `H` = 20 is a missing square root and not a market
    fact."""
    series = walk(n=20_000)
    sigma = S.sigma_close(series)
    ratios = []
    for horizon in (4, 16, 64):
        exc = S.excursions(series, sigma, horizon, step=1)
        ratios.append(float(np.quantile(exc.dn, TAU)) / math.sqrt(horizon))

    assert max(ratios) / min(ratios) < 1.15, f"q90 / sqrt(H) drifted: {ratios}"


# ─────────────────────────── causality ───────────────────────────


def test_the_online_stop_is_fixed_before_its_excursion_is_seen():
    """**The causality claim, asserted through the production object.** The
    harness reads `stop(side)`, scores, then calls `observe` - so a stop can
    never have been moved by the excursion it is scored against. The check is
    that the first scored stop is exactly the starting distance, whatever
    happens afterwards."""
    series = walk(n=2_000)
    exc = S.excursions(series, S.sigma_close(series), 20)
    reading = S.online_arm(exc, 20, side=1, name="quantile", seated=False, gain=0.2,
                           spread_vol=None)

    assert reading.stop_first == pytest.approx(student_stop(TAU), abs=1e-9)
    assert reading.stop_last != pytest.approx(reading.stop_first), "and then it moved"


def test_the_online_estimator_calibrates_a_walk_when_it_is_given_the_room():
    """**The arm where a null passing is the good outcome**, which is the
    opposite of every other study here: this is an estimator, not a signal, so
    one that cannot calibrate a random walk is broken. Given a gain large
    enough to converge inside the stream, it must deliver its target."""
    series = walk(n=40_000)
    exc = S.excursions(series, S.sigma_close(series), 20)
    reading = S.online_arm(exc, 20, side=1, name="quantile-seated", seated=True,
                           gain=0.2, spread_vol=None)

    assert reading.n > 1_000
    assert reading.rate_late == pytest.approx(0.10, abs=0.03), (
        f"delivered {reading.rate_late:.3f} against 0.100"
    )


def test_the_shipped_gain_cannot_reach_a_twenty_bar_quantile_in_time():
    """**The measured reason the online arm may lose for a reason that is not
    about markets.** `GAIN` is an absolute step, so reaching a quantile of
    size `q` from 1.51 takes about `(q - 1.51) / (gain * tau)` exceedances -
    at `H` = 20, where the quantile is 6 to 9 units, that is 250 to 420 and
    the non-overlapping daily stream has 250. Seating the estimator at
    `t-sqrt-h` is the fix, and this test is why it is in the panel."""
    series = walk(n=6_000)
    exc = S.excursions(series, S.sigma_close(series), 20)
    cold = S.online_arm(exc, 20, side=1, name="quantile", seated=False, gain=0.02,
                        spread_vol=None)
    seated = S.online_arm(exc, 20, side=1, name="quantile-seated", seated=True,
                          gain=0.02, spread_vol=None)

    assert cold.n < 350, "the point is that the stream is short"
    assert cold.rate > 0.20, f"the cold start is still too tight at {cold.rate:.3f}"
    assert abs(seated.excess) < abs(cold.excess), "seating it must help"


# ──────────────────────────── the plants ────────────────────────────


def test_a_pure_scale_change_reads_exactly_nothing():
    """**The control that must come back empty, not smaller.** The excursion is
    divided by a sigma estimated from the same returns, so the whole
    measurement is scale-equivariant and multiplying every price change by ten
    cannot move a coverage. A reading here means a lookahead in the unit or a
    price-level dependence - the class
    `a-synthetic-at-price-one-hides-scale-bugs` names, where relative sd and
    price offset coincide at price 1.0 and the bug is invisible."""
    series = walk(n=4_000, price=1.2, sub=20)
    base = S.excursions(series, S.sigma_close(series), 20)
    for factor in (2.0, 10.0):
        grown = S.plant_scale(series, factor)
        got = S.excursions(grown, S.sigma_close(grown), 20)
        assert got.dn == pytest.approx(base.dn, rel=1e-6), f"scale {factor} moved the dn"
        assert got.up == pytest.approx(base.up, rel=1e-6), f"scale {factor} moved the up"


def test_the_scale_control_still_reads_nothing_at_gold_scale():
    """Same control at a price nowhere near 1.0. `a-synthetic-at-price-one-
    hides-scale-bugs` is that relative sd and price offset coincide at price
    1.0, so a harness tested only there has not been tested."""
    series = walk(n=4_000, price=4_000.0, sub=20)
    base = S.excursions(series, S.sigma_close(series), 20)
    grown = S.plant_scale(series, 3.0)
    got = S.excursions(grown, S.sigma_close(grown), 20)

    assert got.dn == pytest.approx(base.dn, rel=1e-6)


def test_the_drift_plant_moves_the_two_sides_apart_and_its_zero_cell_does_not():
    """A drift makes the adverse excursion deeper on one side and shallower on
    the other with no asymmetry in the volatility at all, which is the
    hypothesis for gold's 1.19x at `H` = 20 growing to 1.64x at 96. The zero
    cell is the control: a plant whose zero reads an effect makes its question
    *untested* rather than null, which is how `level-bounce.md`'s pure-order
    plant was discarded at z -4.76 with nothing planted."""
    series = walk(n=12_000, sub=20)

    flat = S.excursions(S.plant_drift(series, 0.0), S.sigma_close(series), 20)
    zero_gap = float(np.quantile(flat.up, TAU)) / float(np.quantile(flat.dn, TAU))
    assert zero_gap == pytest.approx(1.0, abs=0.06), f"zero control read {zero_gap:.3f}"

    pushed = S.plant_drift(series, 0.20)
    got = S.excursions(pushed, S.sigma_close(pushed), 20)
    gap = float(np.quantile(got.up, TAU)) / float(np.quantile(got.dn, TAU))
    assert gap > zero_gap + 0.10, f"an up drift must deepen the up side, read {gap:.3f}"


def test_the_asymmetry_plant_deepens_one_side_only_and_its_zero_cell_does_not():
    """The case the module's own `test_the_empirical_wins_where_the_scale_
    differs` builds by hand at 1.3x, planted into bars so the detector runs on
    planted data and the unit moves with the plant. The whole bar is scaled,
    not just the close step: a stop is reached by the extreme, so a plant that
    leaves the wicks alone is a plant a stop cannot see."""
    series = walk(n=12_000, sub=20)

    flat = S.plant_asym(series, 1.0)
    base = S.excursions(flat, S.sigma_close(flat), 20)
    zero_gap = float(np.quantile(base.dn, TAU)) / float(np.quantile(base.up, TAU))
    assert zero_gap == pytest.approx(1.0, abs=0.06), f"zero control read {zero_gap:.3f}"

    deeper = S.plant_asym(series, 1.5)
    got = S.excursions(deeper, S.sigma_close(deeper), 20)
    gap = float(np.quantile(got.dn, TAU)) / float(np.quantile(got.up, TAU))
    assert gap > zero_gap + 0.15, f"down bars 1.5x deep must show, read {gap:.3f}"


def test_the_plants_keep_the_bar_a_bar():
    """A plant that rebuilds a path can emit a high below its own low, and the
    excursion would then read a negative distance on one side and look like a
    gap. Asserted on every plant rather than on the one that was tried."""
    series = walk(n=2_000, sub=20)
    for name, (make, strengths) in S.PLANTS.items():
        for strength in strengths:
            got = make(series, strength)
            assert (got.high >= got.low).all(), f"{name} at {strength} inverted a bar"
            assert (got.high >= got.close).all(), f"{name} at {strength} closed above high"
            assert (got.low <= got.close).all(), f"{name} at {strength} closed below low"


# ──────────────────────── the arms and the gates ────────────────────────


def test_every_arm_reports_a_coverage_on_both_sides():
    """A pooled stop is a sixth arm and not one of these. `pooled-medians-
    invert-subgroups` is the recorded reason: a pooled median once agreed with
    a claim that every subgroup refuted."""
    series = walk(n=4_000, sub=20)
    exc = S.excursions(series, S.sigma_close(series), 20)
    readings = S.all_arms(exc, 20, spread_vol=None)

    names = {(r.arm, r.side) for r in readings}
    for arm in ("vol-3", "t-fixed", "t-sqrt-h", "quantile", "quantile-seated"):
        assert (arm, 1) in names and (arm, -1) in names, f"{arm} is missing a side"
    assert ("vol-3-N20", 1) not in names, "no spread, so no floored arm rather than a guess"


def test_the_n20_floor_is_only_computed_where_a_spread_is_measured():
    """**Do not invent a spread.** A result priced off a guessed one is the one
    result that looks like a measurement and is not, and the floored incumbent
    is 7.78 units on eurusd 15m against 3.0 - a different stop, so a guess
    here would not be a small error."""
    series = walk(n=4_000)
    sigma = S.sigma_close(series)
    exc = S.excursions(series, sigma, 20)
    spread_vol = np.full(len(sigma), 0.30)
    readings = S.fixed_arms(exc, 20, side=1, spread_vol=spread_vol)

    floored = next(r for r in readings if r.arm == "vol-3-N20")
    assert floored.stop_median == pytest.approx(S.N20 * 0.30)
    assert floored.binds == 1.0, "20 x 0.30 is 6.0, above the 3.0 incumbent"


def test_a_stop_too_tight_to_carry_its_spread_is_named_on_the_arm_that_is():
    """Cost is a gate on the conclusion, not a footnote. The measured 15m
    spread on eurusd is 0.389 volatility units, so the 1.51-unit `t-fixed`
    stop pays **26% of its risk** against the desk's 0.16 limit while the
    3.0-unit incumbent pays 13% - the cost gate lands on the parametric
    baseline, not on the wide arms, and the panel has to say so."""
    series = walk(n=4_000)
    sigma = S.sigma_close(series)
    exc = S.excursions(series, sigma, 20)
    spread_vol = np.full(len(sigma), 0.389)
    readings = S.fixed_arms(exc, 20, side=1, spread_vol=spread_vol)

    tight = next(r for r in readings if r.arm == "t-fixed")
    wide = next(r for r in readings if r.arm == "vol-3")
    assert "26% of its risk" in tight.afford
    assert wide.afford == "", "the incumbent clears the limit at 13%"


def test_the_pass_rule_is_the_binomial_interval_and_not_a_fixed_tolerance():
    """At n = 250 and a 0.100 target the 95% interval is +-0.037, and at
    n = 4,000 it is +-0.009. A fixed tolerance would call the same reading
    calibrated on one panel and not on another, which is a pass rule that
    depends on the panel size rather than on the claim."""
    assert S.calibrated(0.13, 250) is True
    assert S.calibrated(0.13, 4_000) is False
    assert S.calibrated(0.10, 30) is True
    assert S.calibrated(0.30, 4_000) is False


def test_the_side_ratio_is_the_statistic_that_decides_the_adaptive_estimator():
    """The module's own tests show the fixed t only loses where a side's scale
    differs, at 1.3x. This is the measurement of that factor on real data, and
    it has to be read against the null arms rather than against 1.0 - a
    one-sided drift produces it with no volatility asymmetry at all."""
    series = walk(n=12_000, mu=0.15, sub=20)
    exc = S.excursions(series, S.sigma_close(series), 20)
    readings = S.all_arms(exc, 20, spread_vol=None)

    ratio = S.side_ratio(readings, "quantile-seated")
    assert ratio is not None
    assert ratio > 1.0, f"an up drift must widen the short side's stop, read {ratio:.3f}"


def test_a_seed_is_stable_across_processes():
    """`hash()` of a tuple holding a string is salted by `PYTHONHASHSEED`, and
    `fear-greed.md` measured the consequence: a panel's `bar-shuffle` arm read
    -0.266 where a local run on the same code and data read -0.172, while
    every real value matched to the digit. A surrogate range that moves
    between runs cannot be what a verdict is scored against."""
    assert S.seed_for("eurusd.FOREXCOM.1d", "garch-bars", 3) == S.seed_for(
        "eurusd.FOREXCOM.1d", "garch-bars", 3
    )
    assert S.seed_for("a", 1) != S.seed_for("a", 2)
    assert S.seed_for("eurusd.FOREXCOM.1d", "garch-bars", 3) == 17049339896415672


# ──────────────────────────── the mean-R secondary ────────────────────────────


def test_mean_r_divides_by_the_width_and_the_common_unit_does_not():
    """**The confound that decides how to read the secondary.**
    `widestop.md` measured mean R at `m` times the stop to be the 1x mean over
    `m` in every row, with price P&L in units of the base risk not moving
    (+0.180 at 1x against +0.177 at 3x). The arms here span 1.51 to about 8
    units, so a mean-R ranking is a ranking of 1/width - and `per_sigma` is
    the number that can be compared."""
    series = walk(n=6_000, mu=0.05, sub=20)
    sigma = S.sigma_close(series)
    exc = S.excursions(series, sigma, 20)
    spread_vol = np.full(len(sigma), 0.01)

    narrow = S.race(series, sigma, exc, np.full(len(exc.anchors), 2.0), arm="a", side=1,
                    horizon=20, spread_vol=spread_vol)
    wide = S.race(series, sigma, exc, np.full(len(exc.anchors), 6.0), arm="b", side=1,
                  horizon=20, spread_vol=spread_vol)

    assert narrow is not None and wide is not None
    assert abs(wide.mean_r) < abs(narrow.mean_r), "three times the width, a third the R"
    assert wide.stopped < narrow.stopped, "a wider stop is reached less often"


def test_a_tie_inside_one_bar_goes_to_the_stop():
    """Bar-level first passage cannot say which barrier a bar touched first, so
    the conservative rule is the only honest one - and it is a bias against
    the target that is biggest where the stop is tight, which is exactly the
    arm comparison here. Stated in the test because it changes the ranking."""
    series = walk(n=3_000)
    sigma = S.sigma_close(series)
    exc = S.excursions(series, sigma, 20)
    reach = L.Series(
        feed=series.feed,
        venue=series.venue,
        interval=series.interval,
        ts=series.ts,
        open=series.open,
        high=series.close * 1.5,
        low=series.close * 0.5,
        close=series.close,
    )
    got = S.race(reach, sigma, exc, np.full(len(exc.anchors), 1.0), arm="tie", side=1,
                 horizon=20, spread_vol=np.full(len(sigma), 0.01))

    assert got is not None
    assert got.stopped == 1.0, "every bar reaches both barriers, so every one is a stop"


# ──────────────────────── the interval on overlapping rows ────────────────────────


def test_the_block_interval_is_wider_where_the_windows_overlap():
    """**The gate this exists for, with the control beside it.** A binomial
    interval assumes independent rows. On the dense stream the window at `t+1`
    shares `H - 1` of its `H` bars with `t`'s, so the rows are nearly the same
    observation repeated and the binomial interval describes a sample this
    study does not have - `overlapping-windows-inflate-permutation-nulls` is
    the recorded failure, where a level finding at p 0.015 was anchor overlap.

    The control is the non-overlapping stream, where the two intervals must
    agree: a correction that widens everything is indistinguishable from a
    correction that widens nothing."""
    series = walk(n=6_000, sub=20)
    sigma = S.sigma_close(series)

    dense = S.excursions(series, sigma, 48, step=1)
    hit = dense.dn >= 1.51
    binomial = math.sqrt(0.10 * 0.90 / len(hit))
    blocked = S.block_sd(hit, dense.block)
    assert dense.block == 48, "the block is the overlap length in anchors"
    assert blocked > 3.0 * binomial, f"block {blocked:.4f} vs binomial {binomial:.4f}"

    spaced = S.excursions(series, sigma, 48)
    hit = spaced.dn >= 1.51
    binomial = math.sqrt(0.10 * 0.90 / len(hit))
    blocked = S.block_sd(hit, spaced.block)
    assert spaced.block == 1, "disjoint windows need no block"
    assert blocked < 2.0 * binomial, "on disjoint windows the two must agree"


def test_a_calendar_day_block_cannot_see_overlap_in_daily_bars():
    """**The measured reason the block is the overlap length and not a day.**
    A day-block bootstrap is the habit in this folder and it is right at 15m,
    where a day holds 96 bars. On daily bars a calendar day holds exactly one
    anchor, so every block is a single row and the bootstrap becomes an
    ordinary one over rows that are not independent - it read 1.35x the
    binomial sd where the overlap block reads several times it."""
    series = walk(n=6_000, sub=20)
    dense = S.excursions(series, S.sigma_close(series), 48, step=1)
    hit = dense.dn >= 1.51

    by_day = S.block_sd(hit, 1)
    by_overlap = S.block_sd(hit, dense.block)

    assert by_overlap > 2.0 * by_day, f"day {by_day:.4f} against overlap {by_overlap:.4f}"


def test_the_pass_rule_widens_only_when_the_rows_are_dependent():
    """The rule is the wider of the two intervals, so a dependent sample cannot
    be called miscalibrated on an interval it does not support - and an
    independent one is judged exactly as pre-registered."""
    assert S.calibrated(0.13, 4_000) is False
    assert S.calibrated(0.13, 4_000, sd_block=0.05) is True
    assert S.calibrated(0.40, 4_000, sd_block=0.05) is False, "it must still refuse"
