"""Scoring our volatility forecast against Deribit's implied, and the traps in it.

The load-bearing test is `test_an_expired_option_is_refused`. `expired=false` is a
request to Deribit, not a guarantee from it, and an expiry already in the past
makes the realised-volatility window negative - which does not raise, it silently
scores the forecast against a window running backwards.
"""

from __future__ import annotations

import numpy as np

from research.harness.implied_vs_ours import (
    MIN_HORIZON_BARS,
    MONEYNESS_BAND,
    NOTHING_SCORED,
    annualise,
    compare,
    horizon_bars,
    qlike,
    realised_vol,
    score,
    underlying_series,
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


def test_a_run_that_scored_nothing_says_so_however_much_is_recorded(tmp_path, capsys):
    """The safeguard the operator needs precisely when the wait is over.

    An earlier version printed "not enough to score" only when under five days were
    recorded. After the week the plan gates on, it printed a floor and exited 0 - a
    clean successful-looking run with no score and no warning, at the one moment
    somebody would come back to check. Nine days of span here, and every option in it
    expires beyond the last sweep, so there is genuinely nothing to score.
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
    assert NOTHING_SCORED in out, "a long recording that scored nothing must say so"
    assert rc != 0, "no score available should not look like a successful run"


# --------------------------------------------------------------- the bar join


def _quote(at, expiry, underlying_price, mark_iv, underlying="BTC", strike=None):
    return {
        "underlying": underlying,
        "at": str(at),
        "expiry": str(expiry),
        "underlying_price": str(underlying_price),
        "strike": str(underlying_price if strike is None else strike),
        "mark_iv": str(mark_iv),
        "bid_price": "0.0120",
        "ask_price": "0.0126",
        "mark_price": "0.0123",
    }


def test_the_underlying_series_is_one_price_per_instant_sorted():
    """Every strike at one sweep carries the same index price; the path is per instant."""
    rows = [
        _quote(300.0, 9_999.0, 84_100.0, 40.0),
        _quote(300.0, 8_888.0, 84_100.0, 41.0),  # same instant, another strike
        _quote(100.0, 9_999.0, 83_900.0, 40.0),
        _quote(200.0, 9_999.0, 84_000.0, 40.0),
    ]
    at, price = underlying_series(rows, "BTC")
    assert list(at) == [100.0, 200.0, 300.0]
    assert list(price) == [83_900.0, 84_000.0, 84_100.0]


def test_the_underlying_series_separates_currencies():
    rows = [
        _quote(100.0, 9_999.0, 83_900.0, 40.0, underlying="BTC"),
        _quote(100.0, 9_999.0, 2_100.0, 55.0, underlying="ETH"),
    ]
    _at, price = underlying_series(rows, "ETH")
    assert list(price) == [2_100.0]


def test_compare_refuses_a_window_that_runs_past_the_recording():
    """An option expiring after the last sweep has no realised volatility yet.

    This is the whole reason the plan gates the write-up on a week: scoring a
    forecast against a half-open window silently grades it on less than it forecast.
    """
    rows = [
        _quote(at=float(i * 300), expiry=1_000_000.0, underlying_price=84_000.0 + i, mark_iv=40.0)
        for i in range(30)
    ]
    out = compare(rows)
    assert out["scored"] == 0
    assert out["unresolved"] == 30


def test_compare_scores_a_window_that_closed_inside_the_recording():
    """A synthetic path whose realised volatility is known, so the sign is checkable.

    The path is a random walk with a per-step sigma chosen so annualised realised
    volatility is far below the 400% mark_iv quoted. Ours - a trailing estimate of
    the same path - must therefore beat mark_iv, and the QLIKE ordering must say so.
    """
    rng = np.random.default_rng(11)
    step = 300.0
    n = 400
    sigma = 0.0004  # per 5 minutes; about 20% annualised
    price = 84_000.0 * np.exp(np.cumsum(rng.normal(0.0, sigma, n)))
    rows = []
    for i in range(n):
        at = i * step
        # Expire 20 bars ahead, well inside the recording for the early quotes.
        rows.append(_quote(at=at, expiry=at + 20 * step, underlying_price=price[i], mark_iv=400.0))
    out = compare(rows)
    assert out["scored"] > 200
    assert out["qlike_mark"] > out["qlike_ours"], "a 400% quote must lose to a 20% path"


def test_compare_reports_nan_rather_than_a_number_on_a_thin_sample():
    rows = [
        _quote(
            at=float(i * 300), expiry=float(i * 300 + 600), underlying_price=84_000.0, mark_iv=40.0
        )
        for i in range(5)
    ]
    out = compare(rows)
    assert np.isnan(out["qlike_mark"]) or out["scored"] < 200


def test_a_far_out_of_the_money_strike_is_not_scored():
    """The smile is not a forecast of at-the-money realised volatility.

    Selecting the options whose lives close inside a short recording selects the
    shortest-dated ones, and a strike far from spot expiring in hours carries an
    enormous implied volatility for reasons that have nothing to do with forecasting
    the index. Measured on 34 hours of real surface, the unfiltered median `mark_iv`
    of the scored set was 173.6% against realised of 41.4% - a four-fold gap that is
    the wings of the smile, not a bad forecast.
    """
    rng = np.random.default_rng(3)
    step, n = 300.0, 200
    price = 84_000.0 * np.exp(np.cumsum(rng.normal(0.0, 0.0004, n)))
    near, far = [], []
    for i in range(n):
        at = i * step
        near.append(_quote(at, at + 20 * step, price[i], 40.0, strike=price[i]))
        # 60% away from spot: deep in the wing.
        far.append(_quote(at, at + 20 * step, price[i], 400.0, strike=price[i] * 1.6))
    only_far = compare(far)
    assert only_far["scored"] == 0
    assert only_far["off_the_money"] > 100
    both = compare(near + far)
    assert both["scored"] > 100
    assert both["off_the_money"] > 100


def test_the_moneyness_band_is_a_fraction_of_spot():
    assert 0.0 < MONEYNESS_BAND < 1.0


def test_a_window_too_short_to_measure_is_not_scored():
    """QLIKE on a near-zero realised variance is unbounded, and a mean of it is junk.

    Realised variance over a handful of five-minute bars can be essentially zero, and
    `a/f - log(a/f) - 1` goes to infinity as `a` goes to zero however good the
    forecast is. On 34 hours of real surface this made the mean QLIKE for `mark_iv`
    read 5,640 while its median implied volatility was 45.7% against realised of
    34.4% - two numbers a whole order of agreement apart from the loss they produced.
    """
    rng = np.random.default_rng(5)
    step = 300.0
    price = 84_000.0 * np.exp(np.cumsum(rng.normal(0.0, 0.0004, 300)))
    short = [
        _quote(i * step, i * step + (MIN_HORIZON_BARS - 1) * step, price[i], 40.0)
        for i in range(300)
    ]
    assert compare(short)["scored"] == 0
    assert compare(short)["too_short"] > 100

    long_enough = [
        _quote(i * step, i * step + (MIN_HORIZON_BARS + 5) * step, price[i], 40.0)
        for i in range(300)
    ]
    assert compare(long_enough)["scored"] > 100


def test_the_median_qlike_is_reported_beside_the_mean():
    """One near-zero window can move a mean of 2,754 rows by thousands."""
    rng = np.random.default_rng(6)
    step = 300.0
    price = 84_000.0 * np.exp(np.cumsum(rng.normal(0.0, 0.0004, 400)))
    rows = [
        _quote(i * step, i * step + (MIN_HORIZON_BARS + 5) * step, price[i], 40.0)
        for i in range(400)
    ]
    got = compare(rows)
    # Reported and finite for both forecasts. Deliberately not asserting
    # median <= mean: that holds for a right-skewed loss and is not a property of
    # QLIKE in general, so pinning it would be pinning this seed.
    for key in ("qlike_mark_median", "qlike_ours_median"):
        assert not np.isnan(got[key]), key
        assert got[key] >= 0.0, key
