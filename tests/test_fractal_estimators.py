"""The fractal estimators separate the shapes they are supposed to separate.

`research/docs/fractal-rules.md` reports a null from these functions, and a null
is only worth reading if the estimator could have found something. Each test
below pins one thing the estimator must be able to tell apart - a line from
noise, a persistent series from an anti-persistent one, a monofractal from a
multifractal - so a future change that quietly flattens an estimator shows up
here rather than as a better-looking null.

The tolerances are wide on purpose. A 256-point window gives five or six scales,
so a log-log slope carries a standard error of order 0.05 and these estimators
are known to be biased at that length; asserting a textbook value to two
decimals would be asserting the bias.
"""

from __future__ import annotations

import numpy as np
import pytest

from research.harness import fractalest


@pytest.fixture
def rng() -> np.random.Generator:
    return np.random.default_rng(20261109)


def test_windows_last_column_is_the_bar_the_reading_is_for():
    """A reading must be usable at the close of its own bar and see nothing after it.

    `overlapping-outcome-windows-leak` records a direction AUC of 0.79 that
    collapsed to 0.51 once the windows stopped overlapping. An estimator whose
    window is centred, or ends one bar late, produces that same shape of result
    and nothing in a summary statistic reveals it.
    """
    series = np.arange(10.0)
    got = fractalest.windows(series, width=4, stride=2)

    assert got.shape == (4, 4)
    assert got[0].tolist() == [0.0, 1.0, 2.0, 3.0]
    assert got[1].tolist() == [2.0, 3.0, 4.0, 5.0]
    # Row i ends at bar i * stride + width - 1, so the newest bar is the last column.
    assert [row[-1] for row in got] == [3.0, 5.0, 7.0, 9.0]


def test_windows_refuses_a_series_shorter_than_one_window():
    """An empty result rather than a short one. A window padded to length would
    read the pad, and the reading would look like every other reading."""
    assert fractalest.windows(np.arange(3.0), width=8).shape == (0, 8)


def test_higuchi_ranks_a_line_below_a_walk_below_noise(rng):
    """Higuchi's dimension is the one shape statistic with textbook anchors: 1 for
    a smooth curve, about 1.5 for a walk, about 2 for white noise. If the
    ordering is lost the estimator cannot see roughness at all."""
    width = 256
    line = np.linspace(0.0, 1.0, width)[None, :]
    noise = rng.standard_normal((64, width))
    walk = np.cumsum(rng.standard_normal((64, width)), axis=1)

    assert fractalest.higuchi(line)[0] == pytest.approx(1.0, abs=0.1)
    assert float(np.median(fractalest.higuchi(walk))) == pytest.approx(1.5, abs=0.2)
    assert float(np.median(fractalest.higuchi(noise))) == pytest.approx(2.0, abs=0.15)


def test_higuchi_ignores_amplitude(rng):
    """`L(k)` is homogeneous of degree one in the series, so scaling a window
    cannot move the log-log slope. This is what makes the dimension a shape
    statistic rather than a volatility reading, and `topology.md` is the record
    of what happens when a "shape" is secretly an amplitude."""
    win = np.cumsum(rng.standard_normal((32, 256)), axis=1)

    plain = fractalest.higuchi(win)
    scaled = fractalest.higuchi(win * 1_000.0)

    np.testing.assert_allclose(plain, scaled, rtol=1e-9)


def test_box_dimension_separates_a_monotone_line_from_a_filled_square(rng):
    """A monotone curve touches about `m` boxes and a space-filling one about
    `m**2`, so the dimension runs 1 to 2. Without the per-window normalisation
    the count would rise with amplitude instead and both would read the same."""
    width = 256
    line = np.linspace(0.0, 1.0, width)[None, :]
    noise = rng.standard_normal((64, width))

    assert fractalest.box_dimension(line)[0] == pytest.approx(1.0, abs=0.15)
    assert float(np.median(fractalest.box_dimension(noise))) > 1.5


def test_box_dimension_returns_nan_for_a_flat_window():
    """A window whose closes are identical has no range to normalise by. `Step
    Index` and a dead FX hour both produce one, and a fabricated 1.0 there would
    enter a mean as a reading rather than as a gap."""
    assert np.isnan(fractalest.box_dimension(np.full((1, 256), 7.0))[0])


def test_dfa_reads_one_half_on_white_noise(rng):
    """The anchor the exponent is interpreted against. DFA on independent
    increments is 0.5 by construction, so a drift away from it at this window
    length would mean every market reading carried an unknown offset."""
    win = rng.standard_normal((256, 256))

    assert float(np.median(fractalest.dfa(win))) == pytest.approx(0.5, abs=0.05)


@pytest.mark.parametrize("hurst", [0.3, 0.5, 0.7])
def test_dfa_and_rescaled_range_track_a_planted_exponent(rng, hurst):
    """Both estimators must move with the truth, because the power curve in
    `fractal-rules.md` is built by planting a known exponent and reading it
    back. An estimator that is merely biased is usable; one that is flat is not.

    Asserted as a rank against the neighbouring plants rather than as a level:
    R/S is biased upward at 256 points - Anis-Lloyd exists for that reason - so
    pinning its value would pin the bias.
    """
    steps = 1 << 14
    win_a = fractalest.windows(fractalest.fbm(steps, hurst, rng), 256, stride=256)
    win_b = fractalest.windows(fractalest.fbm(steps, hurst + 0.2, rng), 256, stride=256)

    assert float(np.median(fractalest.dfa(win_a))) < float(np.median(fractalest.dfa(win_b)))
    assert float(np.median(fractalest.rescaled_range(win_a))) < float(
        np.median(fractalest.rescaled_range(win_b))
    )


def test_dfa_reads_one_higher_on_the_integral_of_its_input(rng):
    """`dfa` integrates internally, so it takes **increments**. Passing a price
    integrates twice and reads about one higher - a reading of 1.5 that looks
    like extreme persistence and is a unit error. Pinned so the convention
    cannot be changed silently."""
    returns = rng.standard_normal(1 << 14)
    on_returns = fractalest.dfa(fractalest.windows(returns, 256, stride=256))
    on_prices = fractalest.dfa(fractalest.windows(np.cumsum(returns), 256, stride=256))

    assert float(np.median(on_prices)) - float(np.median(on_returns)) == pytest.approx(1.0, abs=0.2)


def test_structure_scaling_reads_no_curvature_on_a_monofractal(rng):
    """`zeta(q)` is linear in `q` for fractional Brownian motion, so the fitted
    curvature - the `lambda**2` of the multifractal random walk - must sit on
    zero. It is the reference the market's reading is judged against, and
    `statespace-fractals.md` records a sign error on exactly this quantity that
    inverted its first answer."""
    win = fractalest.windows(np.cumsum(fractalest.fbm(1 << 16, 0.5, rng)), 512, stride=512)

    hurst, curvature = fractalest.structure_scaling(win)

    assert float(np.median(hurst)) == pytest.approx(0.5, abs=0.1)
    # Not zero: a 512-bar window leaves a measured upward bias of about +0.013,
    # which is why the market's rolling reading is judged against its own
    # shuffled twin at the same width and never against zero.
    assert abs(float(np.median(curvature))) < 0.03


def test_structure_scaling_sees_a_planted_volatility_cascade(rng):
    """A series whose volatility is itself a long-memory process is multifractal,
    and the curvature is the only statistic here that distinguishes it from a
    walk of the same variance. If this reads zero the estimator cannot find
    multifractality and a null from it would mean nothing."""
    steps = 1 << 16
    # Fractional Gaussian **noise**, not its integral: the increments are
    # stationary with slowly decaying correlations, which is the cascade. Using
    # the integral instead makes log-volatility wander to +-40 and `exp` of it
    # overflows to `inf`, and the curvature then comes back `nan` rather than
    # large - a broken fixture that reads as a failed estimator.
    log_volatility = fractalest.fbm(steps, 0.9, rng) * 0.5
    cascade = np.cumsum(rng.standard_normal(steps) * np.exp(log_volatility))
    plain = np.cumsum(rng.standard_normal(steps))

    _, cascade_curvature = fractalest.structure_scaling(
        fractalest.windows(cascade, 512, stride=512)
    )
    _, plain_curvature = fractalest.structure_scaling(fractalest.windows(plain, 512, stride=512))

    assert float(np.median(cascade_curvature)) > float(np.median(plain_curvature)) + 0.02


def test_fbm_increments_aggregate_at_the_planted_exponent(rng):
    """The plant has to be right before the power curve means anything: the
    standard deviation of a sum of `L` consecutive increments must scale as
    `L**H`. An approximate generator makes a blind estimator look sensitive."""
    for hurst in (0.3, 0.7):
        steps = fractalest.fbm(1 << 17, hurst, rng)
        lags = np.array([4, 16, 64, 256], dtype=float)
        spread = [
            float(np.std(steps[: (len(steps) // int(k)) * int(k)].reshape(-1, int(k)).sum(1)))
            for k in lags
        ]
        fitted = np.polyfit(np.log(lags), np.log(spread), 1)[0]

        assert fitted == pytest.approx(hurst, abs=0.03)


def test_bars_from_path_takes_its_extremes_from_the_path(rng):
    """A bar's high and low must be the path's own, not the close plus a draw.
    `excursion-scaling.md` burned three control runs on a generator that added
    an independent wick: it inflates a one-bar range far more than a
    ninety-six-bar one and returned a scaling exponent of 0.42 where the truth
    was 0.5."""
    per_bar = 20
    path = rng.standard_normal(per_bar * 500)
    bars = fractalest.bars_from_path(path, per_bar)

    level = np.cumsum(path).reshape(-1, per_bar)
    np.testing.assert_allclose(bars["close"], level[:, -1])
    assert np.all(bars["high"] >= np.maximum(bars["open"], bars["close"]))
    assert np.all(bars["low"] <= np.minimum(bars["open"], bars["close"]))
    # The extremes are the path's, so they are attained by it rather than drawn
    # beyond it: every high equals some step of its own bar.
    np.testing.assert_allclose(bars["high"], np.maximum(level.max(axis=1), bars["open"]))


@pytest.mark.parametrize("scale", [1e-4, 1e4])
def test_every_estimator_is_blind_to_the_amplitude_of_its_input(rng, scale):
    """A fractal exponent is a property of the dependence, not of the units, so
    multiplying the input must not move any reading.

    **This is the test that catches a floored moment.** `structure_scaling`
    takes `mean |increment|**q`; at `q = 4` on a log-price series whose
    15-minute increments are 4e-4 that moment is 2.6e-14, under an absolute
    floor of 1e-12, and the floor then sets the answer. The same planted series
    read a curvature of 0.019 at a wide amplitude and 0.188 at a realistic one -
    and real FX sits on the clamped side, so every market reading would have
    been the floor rather than the market.
    """
    base = np.cumsum(rng.standard_normal((48, 512)), axis=1)

    for name in ("dfa", "rescaled_range", "higuchi", "box_dimension"):
        fn = getattr(fractalest, name)
        np.testing.assert_allclose(fn(base), fn(base * scale), rtol=1e-6, err_msg=name)

    plain = fractalest.structure_scaling(base)
    scaled = fractalest.structure_scaling(base * scale)
    np.testing.assert_allclose(plain[0], scaled[0], rtol=1e-6)
    np.testing.assert_allclose(plain[1], scaled[1], rtol=1e-6)


def test_structure_scaling_returns_nan_for_a_window_that_never_moved():
    """A window with no increment has no scale to normalise by. Returning a
    fitted 0.0 would put "the quote did not move" into a mean of exponents as
    though it were a measurement of a flat scaling law."""
    hurst, curvature = fractalest.structure_scaling(np.full((1, 512), 3.0))

    assert np.isnan(hurst[0])
    assert np.isnan(curvature[0])


def test_rescaled_range_returns_a_number_at_the_shortest_window(rng):
    """R/S must not be all-NaN at the shortest reach in the sweep. At
    `width // 4` a 64-bar window afforded only the scales {8, 16} - two points
    fit a line exactly - and the function returned NaN for every window, which
    printed a whole `nan` column in a power table and raised nothing."""
    win = fractalest.windows(rng.standard_normal(1 << 13), 64, stride=64)

    got = fractalest.rescaled_range(win)

    assert np.isfinite(got).mean() > 0.9


def test_readings_align_with_their_window_ends_across_chunk_boundaries(rng):
    """One reading per window end, on a series long enough to be chunked.

    The chunked loop returned **one extra reading per chunk**: a 294,499-bar
    feed gave 36,809 readings against 36,805 window ends. On a short series it
    fits in one chunk and the count is right, so this only fails above the
    chunk size - which is why the bug reached the lab and surfaced as an
    IndexError rather than a wrong number.
    """
    from research.harness import fractal_rules

    width, chunk = 64, 64
    close = 100.0 * np.exp(np.cumsum(rng.standard_normal(5_000)) * 1e-4)
    bars = fractal_rules.Bars(
        symbol="t", open=close, high=close, low=close, close=close, vol=np.ones(len(close))
    )

    got = fractal_rules.readings(bars, width, chunk=chunk)
    at = fractal_rules.ends(bars, width)

    assert len(at) > 3 * chunk, "the fixture must span several chunks or this cannot fail"
    for name, values in got.items():
        assert len(values) == len(at), f"{name}: {len(values)} readings for {len(at)} window ends"


def test_fbm_refuses_an_exponent_outside_the_unit_interval():
    """`hurst = 0` or `1` has no stationary fractional Gaussian noise, and the
    circulant embedding returns a path with no error at all - a silent wrong
    plant, which is the worst kind in a power curve."""
    with pytest.raises(ValueError, match="strictly inside"):
        fractalest.fbm(1024, 1.0, np.random.default_rng(0))
