"""The regression channel, and the ways a slope can lie."""

from __future__ import annotations

import math

from till_infinity.trading.candles import Bar
from till_infinity.trading.regression import (
    FALLING,
    FALLING_FAST,
    FLAT,
    RISING,
    RISING_FAST,
    agrees,
    arrow,
    atr,
    card_line,
    features,
    fit,
    slope_vol,
    true_ranges,
)


def bars(closes, *, spread=1.0):
    """Closes with a symmetric range around each, so true range is predictable."""
    return [
        Bar(open=c, high=c + spread / 2, low=c - spread / 2, close=c, time=float(i))
        for i, c in enumerate(closes)
    ]


# ------------------------------------------------------------------ the fit


def test_a_straight_line_is_fitted_exactly():
    got = fit(bars([10 + 2 * i for i in range(20)]))
    assert got is not None
    assert math.isclose(got.slope, 2.0)
    assert math.isclose(got.intercept, 10.0)
    assert math.isclose(got.r2, 1.0)
    assert got.stderr == 0.0
    assert math.isclose(got.last, 48.0)


def test_a_falling_line_has_a_negative_slope():
    got = fit(bars([100 - 0.5 * i for i in range(20)]))
    assert got is not None
    assert math.isclose(got.slope, -0.5)
    assert math.isclose(got.r2, 1.0)


def test_the_fit_uses_only_the_last_span_bars():
    """A regime before the window must not tilt the line inside it."""
    noise = [0.0, 500.0, -500.0, 0.0]
    got = fit(bars(noise + [10 + 2 * i for i in range(20)]), span=20)
    assert got is not None
    assert math.isclose(got.slope, 2.0)


def test_a_flat_series_explains_nothing_rather_than_everything():
    """r2 is 1 - residual/variance and both are zero here. Calling that a
    perfect fit would certify a line through twenty identical closes."""
    got = fit(bars([42.0] * 20))
    assert got is not None
    assert got.slope == 0.0
    assert got.r2 == 0.0


def test_too_few_bars_has_no_fit():
    assert fit(bars([1.0, 2.0])) is None
    assert fit(bars([1.0, 2.0, 3.0]), span=20) is None


def test_two_bars_are_refused_even_when_asked_for():
    """stderr divides by span - 2, so a two-bar channel has no width to report."""
    assert fit(bars([1.0, 2.0]), span=2) is None


def test_noise_around_a_line_keeps_the_slope_and_loses_the_r2():
    straight = [10 + 2 * i for i in range(20)]
    wobbled = [c + (3.0 if i % 2 else -3.0) for i, c in enumerate(straight)]
    clean = fit(bars(straight))
    dirty = fit(bars(wobbled))
    assert clean is not None
    assert dirty is not None
    # The offsets are balanced in count but not against x - the last bar is a
    # high one - so the slope tilts by 0.045 rather than not at all. Near enough
    # that the direction is unharmed, which is what the slope is read for.
    assert abs(dirty.slope - clean.slope) < 0.1
    # ...and the fit is visibly worse, which is the number a gate should read.
    # The line still explains most of the variance - 2660 of 2840 - because a
    # slope of 2 over twenty bars is a far bigger movement than +/-3 of noise.
    # That is the point of quoting r2 rather than asserting a slope is "clean".
    assert dirty.r2 < 0.95
    assert dirty.stderr > 3.0


def test_the_channel_is_symmetric_about_the_line():
    got = fit(bars([10 + 2 * i + (1.0 if i % 2 else -1.0) for i in range(20)]))
    assert got is not None
    low, high = got.band(2.0)
    assert math.isclose((low + high) / 2, got.last)
    assert math.isclose(high - low, 4 * got.stderr)


def test_place_is_in_residual_sigmas_and_nan_without_a_channel():
    got = fit(bars([10 + 2 * i + (1.0 if i % 2 else -1.0) for i in range(20)]))
    assert got is not None
    assert math.isclose(got.place(got.last), 0.0, abs_tol=1e-9)
    assert math.isclose(got.place(got.last + got.stderr), 1.0)
    straight = fit(bars([10 + 2 * i for i in range(20)]))
    assert straight is not None
    assert math.isnan(straight.place(straight.last))


# ------------------------------------------------------------ normalisation


def test_true_range_reaches_across_the_gap_to_the_previous_close():
    got = true_ranges(
        [Bar(open=10, high=11, low=9, close=10), Bar(open=20, high=21, low=19, close=20)]
    )
    assert got[0] == 2.0
    # 21 - 10 is the real range of the second bar, not 21 - 19.
    assert got[1] == 11.0


def test_atr_needs_a_full_window():
    assert math.isnan(atr(bars([1.0] * 5), n=14))
    assert math.isclose(atr(bars([1.0] * 14, spread=2.0), n=14), 2.0)


def test_the_slope_is_scaled_into_volatility_units():
    """The whole point: the same shape on two instruments reads the same."""
    index = fit(bars([122_000 + 40 * i for i in range(20)]))
    rate = fit(bars([0.65 + 0.0002 * i for i in range(20)]))
    assert index is not None
    assert rate is not None
    assert math.isclose(slope_vol(index, 200.0), 0.2)
    assert math.isclose(slope_vol(rate, 0.001), 0.2)


def test_an_absent_scale_is_nan_not_zero():
    """Zero would read as flat, which is a claim rather than an absence."""
    got = fit(bars([10 + 2 * i for i in range(20)]))
    assert math.isnan(slope_vol(got, 0.0))
    assert math.isnan(slope_vol(None, 1.0))


# ---------------------------------------------------------------- the arrow


def test_the_arrow_follows_the_slope():
    assert arrow(0.5) == RISING_FAST
    assert arrow(0.1) == RISING
    assert arrow(0.0) == FLAT
    assert arrow(-0.1) == FALLING
    assert arrow(-0.5) == FALLING_FAST


def test_a_steep_slope_through_a_cloud_reads_flat():
    """The slope of a cloud is not a direction."""
    assert arrow(0.5, r2=0.05) == FLAT


def test_an_absent_reading_reads_flat():
    assert arrow(float("nan")) == FLAT
    assert arrow(0.5, r2=float("nan")) == FLAT


def test_agreement_distinguishes_against_from_unknown():
    assert agrees(0.5, 1.0, buying=True) is True
    assert agrees(0.5, 1.0, buying=False) is False
    # No fit, no trend, and a flat line are all "no reading" rather than "no".
    assert agrees(float("nan"), 1.0, buying=True) is None
    assert agrees(0.5, 0.05, buying=True) is None
    assert agrees(0.0, 1.0, buying=True) is None


# -------------------------------------------------------------- the journal


def test_features_name_everything_a_later_score_needs():
    got = features(bars([10 + 2 * i for i in range(30)]), unit=10.0, span=20)
    assert math.isclose(got["regression_slope_vol"], 0.2)
    assert math.isclose(got["regression_r2"], 1.0)
    assert got["regression_span"] == 20.0
    assert got["regression_width_vol"] == 0.0
    # A straight line has no channel, so there is no place in it to report.
    assert math.isnan(got["regression_place"])
    # Slope is constant on a straight line, so it is neither steepening nor easing.
    assert math.isclose(got["regression_accel_vol"], 0.0)


def test_features_fall_back_to_atr_when_no_unit_is_given():
    got = features(bars([10 + 2 * i for i in range(30)], spread=4.0), span=20)
    # Each bar spans its close +/-2 and the step up is 2, so the previous close
    # sits exactly on this bar's low: the true range is the 4.0 spread.
    assert math.isclose(got["regression_slope_vol"], 2.0 / 4.0)


def test_features_are_empty_rather_than_nan_when_there_is_no_fit():
    """A dict of NaNs lands in the journal on every decision and is read, later,
    as a measurement."""
    assert features(bars([1.0, 2.0, 3.0]), unit=1.0, span=20) == {}


def test_features_are_empty_when_there_is_no_scale_to_divide_by():
    """A series that never moves has no volatility unit, and `unit=0` falls back
    to an ATR that is also zero. Neither is a reason to publish a slope."""
    assert features(bars([42.0] * 30, spread=0.0), unit=0.0, span=20) == {}


def test_acceleration_is_signed_so_easing_and_steepening_differ():
    # A slope that grows: quadratic up.
    got = features(bars([0.01 * i * i for i in range(40)]), unit=1.0, span=20)
    assert got["regression_accel_vol"] > 0
    # The mirror image falls ever faster, so its slope change is negative.
    mirror = features(bars([-0.01 * i * i for i in range(40)]), unit=1.0, span=20)
    assert mirror["regression_accel_vol"] < 0


def test_acceleration_is_absent_without_the_earlier_window():
    got = features(bars([10 + 2 * i for i in range(20)]), unit=1.0, span=20)
    assert "regression_accel_vol" not in got


# ----------------------------------------------------------------- the card


def test_the_card_renders_one_line_with_the_arrow():
    got = card_line(features(bars([10 + 2 * i for i in range(30)]), unit=10.0, span=20))
    assert len(got) == 1
    assert RISING_FAST in got[0]
    assert "+0.20v/bar" in got[0]
    assert "+4.0v over 20" in got[0]
    assert "r² 1.00" in got[0]


def test_the_card_is_empty_without_a_fit():
    assert card_line({}) == []
    assert card_line({"regression_slope_vol": float("nan"), "regression_r2": 1.0}) == []


def test_the_card_says_steepening_only_when_the_slope_is_growing_in_its_own_direction():
    rising = card_line(features(bars([0.01 * i * i for i in range(40)]), unit=1.0, span=20))
    assert "steepening" in rising[0]
    # Falling ever faster is also steepening: accel is negative and so is the slope.
    falling = card_line(features(bars([-0.01 * i * i for i in range(40)]), unit=1.0, span=20))
    assert "steepening" in falling[0]
