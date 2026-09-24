"""Scoring our volatility forecast against Deribit's implied, and the traps in it.

The load-bearing test is `test_an_expired_option_is_refused`. `expired=false` is a
request to Deribit, not a guarantee from it, and an expiry already in the past
makes the realised-volatility window negative - which does not raise, it silently
scores the forecast against a window running backwards.
"""

from __future__ import annotations

import numpy as np

from research.harness.implied_vs_ours import (
    JOIN_IS_UNWRITTEN,
    annualise,
    horizon_bars,
    qlike,
    realised_vol,
    score,
)

HOUR = 3600.0


def test_an_expired_option_is_refused():
    assert horizon_bars(expiry=1_000.0, at=2_000.0, bar_seconds=60.0) is None


def test_an_option_expiring_this_instant_is_refused():
    """A zero-length window is not a forecast horizon."""
    assert horizon_bars(expiry=2_000.0, at=2_000.0, bar_seconds=60.0) is None


def test_an_expiry_shorter_than_one_bar_is_refused():
    """Half a bar rounds to zero bars, and a zero-bar window scores nothing."""
    assert horizon_bars(expiry=2_030.0, at=2_000.0, bar_seconds=60.0) is None


def test_the_horizon_is_in_bars():
    assert horizon_bars(expiry=2_000.0 + 2 * HOUR, at=2_000.0, bar_seconds=HOUR) == 2


def test_a_nonsense_bar_length_is_refused():
    assert horizon_bars(expiry=2_000.0 + HOUR, at=2_000.0, bar_seconds=0.0) is None


def test_annualising_scales_with_the_square_root_of_time():
    a = annualise(0.01, 60.0)
    b = annualise(0.01, 240.0)
    # Four times the bar length is half the annualised sigma for the same per-bar value.
    assert np.isclose(a / b, 2.0, rtol=1e-9)


def test_annualising_a_non_positive_sigma_is_nan():
    assert np.isnan(annualise(0.0, 60.0))
    assert np.isnan(annualise(0.01, 0.0))


def test_realised_vol_of_a_flat_series_is_zero():
    out = realised_vol(np.ones(100), bars=10)
    assert np.nanmax(out) == 0.0


def test_realised_vol_recovers_a_known_sigma():
    rng = np.random.default_rng(7)
    sigma = 0.01
    closes = 100.0 * np.exp(np.cumsum(rng.normal(0.0, sigma, 20_000)))
    out = realised_vol(closes, bars=200)
    assert np.isclose(np.nanmedian(out), sigma, rtol=0.15)


def test_realised_vol_is_nan_when_the_window_exceeds_the_data():
    out = realised_vol(np.ones(5), bars=50)
    assert np.isnan(out).all()


def test_realised_vol_is_aligned_to_the_windows_start():
    """The value at index i must describe the window that begins at i, not ends there.

    Getting this backwards is a look-ahead: the forecast would be scored against
    volatility that had already happened when the quote was taken.
    """
    # Flat, then violent. A window starting in the flat stretch and reaching into
    # the violent one should be non-zero; one entirely inside the flat stretch zero.
    closes = np.concatenate([np.ones(50), np.exp(np.cumsum(np.full(50, 0.05)))])
    out = realised_vol(closes, bars=10)
    assert out[0] == 0.0
    assert out[45] > 0.0


def test_qlike_is_zero_for_a_perfect_forecast():
    a = np.full(500, 0.01)
    assert np.isclose(qlike(a, a), 0.0)


def test_qlike_punishes_a_forecast_in_either_direction():
    """Variance loss is asymmetric but never rewards being wrong."""
    actual = np.full(500, 0.01)
    assert qlike(actual, np.full(500, 0.005)) > 0.0
    assert qlike(actual, np.full(500, 0.020)) > 0.0


def test_qlike_is_nan_on_a_thin_sample():
    """A thin cell must read as thin, not as a result."""
    a = np.full(10, 0.01)
    assert np.isnan(qlike(a, a))


def test_score_squares_its_inputs_because_the_folder_scores_variances():
    """The convention, made impossible to get wrong at the call site.

    `similarity_grid.py`, `regimes.py` and `susceptibility.py` all pass **variances**
    to `qlike` - `susceptibility.py:197` is `base = x_trail**2 * horizon`, and the
    `np.sqrt` on line 176 is an intermediate that line squares back. An earlier
    version of this module claimed the opposite and passed standard deviations.

    `realised_vol` returns a sigma, so the natural composition lands on the wrong
    side. `score` exists so the join cannot.
    """
    actual = np.full(500, 0.010)
    forecast = np.full(500, 0.015)
    assert np.isclose(score(actual, forecast), qlike(actual**2, forecast**2))


def test_the_convention_is_load_bearing_not_cosmetic():
    """Why the one above is worth a function: the two conventions rank differently.

    Actual sigma 0.010, one forecast 50% high and one 30% low. On sigmas the low
    forecast wins; on variances the high one does. If those are `mark_iv` and ours,
    the phase-0 verdict depends on the convention alone.
    """
    actual = np.full(500, 0.010)
    high = np.full(500, 0.015)
    low = np.full(500, 0.007)
    on_sigma = (qlike(actual, high), qlike(actual, low))
    on_variance = (score(actual, high), score(actual, low))
    assert on_sigma[0] > on_sigma[1]  # sigmas prefer the low forecast
    assert on_variance[0] < on_variance[1]  # variances prefer the high one


def test_the_unwritten_join_is_announced_however_much_is_recorded(tmp_path, capsys):
    """The safeguard the operator needs precisely when the wait is over.

    An earlier version printed "not enough to score" only when under five days were
    recorded. After the week the plan gates on, it printed a floor and exited 0 - a
    clean successful-looking run with no score and no warning, at the one moment
    somebody would come back to check.
    """
    import gzip

    # FIELDS comes from the real schema, so this fixture cannot drift from what the
    # recorder actually writes.
    from research.harness.deribit import FIELDS
    from research.harness.implied_vs_ours import main

    header = ",".join(FIELDS)
    # Nine days of span: past the five-day gate the old version used.
    rows = [
        f"BTC-X-{i}-C,BTC,call,71000,{2_000_000 + i * 90_000},40.6,0.0123,"
        f"0.0120,0.0126,84000,12,958,{1_000_000 + i * 86_400}"
        for i in range(10)
    ]
    with gzip.open(tmp_path / "deribit_2026-09-24.csv.gz", "wt") as handle:
        handle.write(header + "\n" + "\n".join(rows) + "\n")

    rc = main(["--surface", str(tmp_path)])
    out = capsys.readouterr().out
    assert JOIN_IS_UNWRITTEN in out, "a long recording must still say the join is missing"
    assert rc != 0, "no score available should not look like a successful run"
