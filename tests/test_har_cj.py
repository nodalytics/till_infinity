"""What the forecaster gained, and the one horizon it is still weakest at.

Four changes, each with a measurement behind it:

* **It defers to the published constant** on the feeds that state one. Those
  have no clustering to track - largest `|acf|` of the absolute 1m return is
  0.017 against 0.219-0.453 on real controls - so three horizons are three
  windows onto one number, and a fitted forecast measured *negative*
  out-of-sample R-squared there while the name is right to a median 1.0020.
* **It fits in logs.** A right-skewed strictly-positive target fitted in levels
  produced a ratio whose median was 1.12 and whose p99 was 629.
* **It splits the jump from the continuous part.** They do not persist alike,
  and pooling them teaches one memory for two processes.
* **`predict_over` exists**, because `research/forecasting.md` measured naive
  beating HAR in 11 of 12 cells at one bar while HAR wins at 5, 10 and 20 - and
  `predict` is the one-bar number.

The input needed no change: `Volatility.observe_bar` already feeds this
`rogers_satchell_bps`, a drift-robust range estimator, not a close-to-close one.
"""

from __future__ import annotations

import math

import pytest

from till_infinity.structures.vol import har as har_mod
from till_infinity.structures.vol.har import BIPOWER, Har


@pytest.fixture
def stated_on(monkeypatch):
    monkeypatch.setattr(har_mod.stated, "ENABLED", True)


def feed_bars(model: Har, values: list[float]) -> None:
    for v in values:
        model.observe(v)


# -------------------------------------------------------- published deferral


def test_a_named_feed_uses_its_own_published_volatility(stated_on):
    model = Har(feed="volatility_75_index", interval_seconds=3600.0)
    got = model.published()
    # 75% annual over one hour of a 365-day year, in bps.
    want = 0.75 * math.sqrt(3600.0 / (365 * 24 * 3600)) * 10_000.0
    assert got == pytest.approx(want, rel=1e-9)
    assert model.predict() == pytest.approx(want, rel=1e-9)


def test_jump_carries_the_measured_multiple_not_its_name(stated_on):
    """Jump indices realise 1.322x their name in both halves of the record."""
    model = Har(feed="jump_25_index", interval_seconds=3600.0)
    plain = Har(feed="volatility_25_index", interval_seconds=3600.0)
    assert model.published() == pytest.approx(plain.published() * 1.322, rel=1e-9)


def test_an_unnamed_feed_still_fits(stated_on):
    """Real markets and the Boom, Crash, Step and Range Break families publish
    nothing, and inventing a number for them is the failure `stated.py` exists
    to avoid."""
    for feed in ("gold", "boom_500_index", "step_index", "XAUUSD"):
        assert Har(feed=feed, interval_seconds=3600.0).published() is None


def test_the_deferral_is_off_when_the_flag_is(monkeypatch):
    monkeypatch.setattr(har_mod.stated, "ENABLED", False)
    assert Har(feed="volatility_75_index", interval_seconds=3600.0).published() is None


def test_a_forecaster_with_no_interval_does_not_guess(stated_on):
    """`bps_for` needs a bar length; zero means the caller did not say."""
    assert Har(feed="volatility_75_index", interval_seconds=0.0).published() is None


# --------------------------------------------------------------- the CJ split


def test_a_smooth_series_has_no_jump():
    """Bipower multiplies adjacent bars, so a series with no outlier leaves
    nothing above the continuous level."""
    _, jump = Har._split([10.0] * 12)
    # `pi/2 * sqrt(10*10)` exceeds 10, so every excess is clipped to zero.
    assert all(j == 0.0 for j in jump)


def test_a_single_spike_lands_in_the_jump_column():
    values = [10.0] * 6 + [400.0] + [10.0] * 6
    cont, jump = Har._split(values)
    spike = jump[6]
    assert spike > 0.0, "a 40x bar must register as a jump"
    # Bipower sees only one large factor, so it stays near the quiet level.
    assert cont[6] == pytest.approx(BIPOWER * math.sqrt(400.0 * 10.0), rel=1e-9)
    assert max(jump[:6] + jump[7:]) == 0.0, "the quiet bars carry no jump"


def test_the_two_parts_reconstruct_the_bar():
    values = [3.0, 11.0, 2.0, 90.0, 4.0, 5.0, 60.0, 1.0]
    cont, jump = Har._split(values)
    for x, c, j in zip(values, cont, jump, strict=True):
        assert c + j == pytest.approx(x, rel=1e-9)


def test_a_jump_is_never_negative():
    """A bar quieter than its neighbour is a quiet bar, not a negative jump."""
    _, jump = Har._split([100.0, 1.0, 100.0, 1.0, 100.0])
    assert min(jump) >= 0.0


def test_the_feature_vector_carries_both_components():
    model = Har()
    feed_bars(model, [float(10 + i % 4) for i in range(30)])
    got = model._features()
    assert got is not None
    for name in ("short", "medium", "long", "cont_short", "cont_long", "jump_short", "jump_long"):
        assert name in got, f"{name} missing from the HAR-CJ features"


# ---------------------------------------------------------------- log target


def test_the_forecast_is_never_negative_however_wild_the_input():
    """A squared-error fit in levels can predict a negative volatility; in logs
    it is impossible by construction."""
    model = Har(warmup=5)
    feed_bars(model, [1.0, 900.0, 2.0, 1500.0, 3.0, 2000.0, 1.0] * 6)
    assert model.predict() > 0.0


def test_the_ratio_stays_inside_its_cap_on_a_violent_series():
    """The p99 of 629 that forced `RATIO_CAP` was the level-space fit; this is
    the behaviour that replaces it."""
    model = Har(warmup=5)
    feed_bars(model, [5.0, 1200.0, 6.0, 1400.0, 4.0] * 10)
    assert 0.0 < model.ratio <= har_mod.RATIO_CAP


# --------------------------------------------------------------- the horizon


def test_one_bar_and_below_is_the_plain_forecast():
    model = Har(warmup=5)
    feed_bars(model, [float(8 + i % 5) for i in range(40)])
    assert model.predict_over(1) == model.predict()
    assert model.predict_over(0) == model.predict()


def test_a_longer_horizon_pulls_toward_the_long_window():
    """The three-horizon form exists to express mean reversion; over more bars
    the expectation should move toward the long-run term."""
    model = Har(warmup=5)
    feed_bars(model, [float(8 + i % 5) for i in range(40)])
    near, far = model.predict(), model.predict_over(model.long * 4)
    long_mean = model._last_features["long"]
    assert abs(far - long_mean) <= abs(near - long_mean) + 1e-9


def test_a_published_feed_ignores_the_horizon(stated_on):
    """Constant sigma is constant over any horizon, and saying otherwise would
    be the model inventing a term the generator does not have."""
    model = Har(feed="volatility_75_index", interval_seconds=3600.0)
    assert model.predict_over(50) == pytest.approx(model.predict(), rel=1e-12)
