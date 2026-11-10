"""Setting a stop from a volatility forecast, and the bound on doing it.

Three measured facts compose here, and the **third is a limit rather than a
licence**: `no-gaussian-band-is-calibrated` found only the *one-bar* band
miscalibrated and the Student-t fixing it, 64 of 64 out of sample. Scaling that
band over a hold by `sqrt(n)` is unmeasured, and the arithmetic is why it
matters: on a steady 20-pip 15m bar the one-bar band is **30 pips** against a
rule's own 3.0-unit stop of 60, so it binds only on a genuinely tight stop -
while the same band over `smc-bos-causal`'s 96-bar hold is **295 pips**, five
times the rule's own, which would make a "floor" a silent rewrite of every stop
on the desk.
"""

from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from till_infinity.risk import forecast
from till_infinity.risk.quantiles import DOF, TAU, student_stop

OWN = "EURUSD.SIM-15-MINUTE-LAST-EXTERNAL"
FOREIGN = "AUDUSD.SIM-15-MINUTE-LAST-EXTERNAL"


def _bar(spelling: str, at: int, span: float = 0.0020, close: float = 1.1000):
    """One bar of `spelling`, as `on_historical_data` is delivered them - one
    per call rather than as a batch, which is what Nautilus actually does.

    `at` is required rather than defaulted because the mixin's duplicate guard
    keys on `(bar_type, ts_event)`: bars sharing a stamp are one bar seen
    several times, so a fixture that reused a default would feed the forecast
    exactly once and the test would read as a broken feed.
    """
    from nautilus_trader.model.data import Bar, BarType
    from nautilus_trader.model.objects import Price, Quantity

    return Bar(
        bar_type=BarType.from_str(spelling),
        open=Price(close, 5),
        high=Price(close + span / 2, 5),
        low=Price(close - span / 2, 5),
        close=Price(close, 5),
        volume=Quantity(1, 0),
        ts_event=at,
        ts_init=at,
    )


def steady(bars: int = 20, span: float = 0.0020, close: float = 1.1000) -> forecast.RangeForecast:
    """A forecast fed `bars` identical ranges, so its value is exactly `span`."""
    found = forecast.RangeForecast()
    for _ in range(bars):
        found.update(close + span / 2, close - span / 2, close)
    return found


# -------------------------------------------------------------- the forecast


def test_a_steady_range_forecasts_itself():
    """An exponential average of a constant is that constant. Asserted because
    a decay seeded from zero would converge toward it from below for the whole
    warm-up and read a stop too tight the entire time."""
    assert steady().value == pytest.approx(0.0020)


def test_a_gap_counts_as_movement():
    """**True range, not the bar's own high-low.** A gap is movement the
    position lives through, and a high-low that ignores the previous close
    reports a quiet bar on a day that opened well away from it."""
    quiet = forecast.RangeForecast()
    quiet.update(1.1010, 1.0990, 1.1000)  # 20 pips, no previous close
    before = quiet.value
    # A 200-pip gap up, then a 20-pip bar. The range is the gap, not the bar.
    quiet.update(1.1210, 1.1190, 1.1200)
    assert quiet.value > before * 2, "a gap was read as a quiet bar"


def test_it_is_not_read_before_it_is_warm():
    """A stop set from two bars is a stop set from two bars."""
    assert steady(bars=forecast.WARM - 1).ready is False
    assert steady(bars=forecast.WARM).ready is True


def test_a_flat_series_has_no_opinion():
    """Zero range is not zero volatility, it is no reading - and a band of zero
    would be a stop on the entry."""
    flat = forecast.RangeForecast()
    for _ in range(30):
        flat.update(1.1000, 1.1000, 1.1000)
    assert flat.ready is False
    assert forecast.band(flat.value) == 0.0


# ------------------------------------------------------------------ the band


def test_the_band_is_the_student_quantile_and_not_a_gaussian_one():
    """`student_stop` is called rather than a quantile computed here, because
    the two-sided version of this put the baseline at 1.08 units where it
    belongs at 1.51 - and a stop that tight read a realised coverage well
    under its nominal."""
    assert forecast.band(0.0020) == pytest.approx(0.0020 * student_stop(TAU, DOF))
    assert student_stop(TAU, DOF) == pytest.approx(1.5074, abs=5e-4)


def test_one_bar_is_the_default_because_one_bar_is_what_was_measured():
    """The calibration result is a one-bar result. Anything else is an
    extrapolation and the signature says so by defaulting here."""
    assert forecast.band(0.0020) == forecast.band(0.0020, 1.0)


def test_a_multi_bar_band_scales_with_the_square_root_and_is_flagged_unmeasured():
    """Asserted so the extrapolation is pinned rather than accidental: a reader
    who widens `bars` gets `sqrt(n)` and the module docstring tells them that
    is not a measured coverage claim. A stop is a barrier, not a terminal
    distribution, so this understates the excursion a hold sees."""
    assert forecast.band(0.0020, 96) == pytest.approx(forecast.band(0.0020) * math.sqrt(96))


def test_a_hold_shorter_than_a_bar_still_lives_through_one():
    assert forecast.band(0.0020, 0.25) == forecast.band(0.0020, 1.0)


# ----------------------------------------------------------------- the floor


def test_it_widens_a_tight_stop_and_leaves_a_wide_one_alone():
    """**The property that makes it a floor.** A band that could tighten a stop
    would make a rule trade at a distance it was never measured at."""
    value = steady().value
    tight = 1.0 * value
    wide = 3.0 * value

    assert forecast.floored(tight, value) > tight, "a tight stop was not widened"
    assert forecast.floored(tight, value) == pytest.approx(forecast.band(value))
    assert forecast.floored(wide, value) == wide, "a measured stop was moved"


def test_the_binding_point_is_about_one_and_a_half_units():
    """The number a deploy is choosing. On a steady 20-pip 15m bar the band is
    30 pips, so a rule's own 3.0-unit stop of 60 is untouched and anything
    under about 1.5 units is widened."""
    value = steady().value
    assert forecast.floored(1.4 * value, value) > 1.4 * value
    assert forecast.floored(1.6 * value, value) == pytest.approx(1.6 * value)


def test_no_forecast_is_no_change():
    """An unwarmed desk must behave exactly as it did before, which is what
    makes switching this on safe to do and to undo."""
    assert forecast.floored(0.0005, 0.0) == 0.0005
    assert forecast.floored(0.0005, -1.0) == 0.0005


# ------------------------------------------------------------- the desk's use


def test_the_desk_floors_the_stop_before_it_floors_the_target():
    """**The two must share a basis.** A target in units of a stop the desk
    then widened is a reward-to-risk ratio describing no trade that happened,
    so the stop floor runs first and `target_r` measures R against the result.
    """
    from till_infinity.domain.models import Intent, Side
    from till_infinity.strategies.desk import Desk

    value = steady().value
    intent = Intent(
        feed="eurusd",
        symbol="EURUSD",
        volume=0.1,
        side=Side.BUY,
        entry=1.1000,
        stop=1.1000 - 1.0 * value,  # one unit: tighter than the band
        target=0.0,
        reason="a test",
        interval="15m",
        features={},
        hold=0.0,
    )
    stub = SimpleNamespace(
        settings=SimpleNamespace(forecast_band=True, target_r=2.0),
        _forecast=steady(),
    )
    widened = Desk._floor_stop(stub, intent)
    assert widened.risk == pytest.approx(forecast.band(value)), "the stop was not floored"
    assert widened.features["stop_floored_from"] == pytest.approx(1.0 * value)

    targeted = Desk._floor_target(stub, widened)
    assert targeted.reward == pytest.approx(2.0 * widened.risk), "R is on the floored stop"


def test_the_desk_does_nothing_with_the_flag_off():
    """Off is a no-op and a test says so, because a gate that silently changes
    nothing reads the same as one that is working."""
    from till_infinity.domain.models import Intent, Side
    from till_infinity.strategies.desk import Desk

    value = steady().value
    intent = Intent(
        feed="eurusd",
        symbol="EURUSD",
        volume=0.1,
        side=Side.BUY,
        entry=1.1000,
        stop=1.1000 - 0.5 * value,
        target=0.0,
        reason="a test",
        interval="15m",
        features={},
        hold=0.0,
    )
    off = SimpleNamespace(
        settings=SimpleNamespace(forecast_band=False, target_r=0.0), _forecast=steady()
    )
    assert Desk._floor_stop(off, intent) is intent

    cold = SimpleNamespace(
        settings=SimpleNamespace(forecast_band=True, target_r=0.0),
        _forecast=steady(bars=3),
    )
    assert Desk._floor_stop(cold, intent) is intent, "an unwarmed forecast moved a stop"


def test_the_setting_is_off_by_default():
    from till_infinity.strategies.config import Settings

    assert Settings().forecast_band is False


def test_the_replay_warms_the_forecast_so_the_floor_is_live_on_the_first_bar():
    """**Fourteen live bars is three and a half hours on a 15m clock.** A floor
    that only arrives after that is absent for exactly the trades it exists
    for - the ones a desk takes in the minutes after a deploy - so the warm
    replay feeds it through the same `observe_forecast` a live bar uses.

    Asserted on the mixin's own loop rather than on a desk, because the loop is
    where a foreign bar type is rejected and a desk's forecast must inherit
    that rejection rather than reimplement it.
    """
    from till_infinity.strategies.warming import WarmFromHistory

    class Replayed(WarmFromHistory):
        """Enough of a desk to drive the loop: the mixin reads these four."""

        def __init__(self) -> None:
            self.warmed: dict[str, int] = {}
            self.seen: list[object] = []
            self.forecast = forecast.RangeForecast()

        def warm_bar_types(self):
            return (OWN,)

        def warm_bar(self, bar):
            self.seen.append(bar)

        def observe_forecast(self, bar):
            if str(bar.bar_type) == str(OWN):
                self.forecast.update(float(bar.high), float(bar.low), float(bar.close))

    desk = Replayed()
    minute = 60_000_000_000
    for i in range(forecast.WARM):
        desk.on_historical_data(_bar(OWN, at=i * minute))
    assert desk.forecast.ready, "a desk warmed by replay still had no forecast"
    assert desk.forecast.value == pytest.approx(0.0020)

    # And a foreign bar type is not folded, which is the half that matters:
    # `identity-arb` requests its partner legs' history on its own clock.
    before = desk.forecast.value
    for i in range(10):
        desk.on_historical_data(_bar(FOREIGN, at=i * minute, span=0.0200))
    assert desk.forecast.value == pytest.approx(before), "a partner leg reached the forecast"
    assert desk.warmed["foreign"] == 10
