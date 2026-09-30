"""FX-only vetoes in New York's clock: the close-and-rollover hours and the Sunday open.

`research/docs/vetoes.md`: FX entries at 16:00-18:59 New York did -0.43 / -0.45 vol worse, and the
Sunday open's first hour -1.2 / -1.5, while Deriv did better in the same hours - so FX only, and
in New York time so daylight saving cannot move the window.
"""

from __future__ import annotations

import datetime as dt

from till_infinity.trading import Settings
from till_infinity.trading.config import _ny_span
from till_infinity.trading.models import Intent, Side
from till_infinity.trading.risk import Guard, fx_window


def utc(text: str) -> float:
    return dt.datetime.fromisoformat(text).replace(tzinfo=dt.UTC).timestamp()


def desk(**over) -> Guard:
    made = Settings()
    for k, v in over.items():
        setattr(made, k, v)
    guard = Guard(made, currency="USD")
    guard.roll(10_000.0, now=utc("2026-07-15 09:00"))
    return guard


def intent(feed: str = "eurusd", symbol: str = "EURUSD") -> Intent:
    return Intent(
        feed=feed,
        symbol=symbol,
        side=Side.BUY,
        volume=0.1,
        entry=1.1000,
        stop=1.0990,
        target=1.1020,
        interval="15m",
        risk_money=10.0,
    )


def gate(guard: Guard, when: float, **kw) -> str | None:
    got = guard.allows(intent(**kw), positions=[], now=when)
    return None if got is None else got.gate


def test_fx_quiet_hours_follow_new_york_through_daylight_saving():
    s = Settings()
    # July: New York is UTC-4, so 16:00-18:59 New York is 20:00-22:59 UTC
    assert fx_window(s, "eurusd", utc("2026-07-15 20:05"))[0] == "fx_quiet_hour"
    assert fx_window(s, "eurusd", utc("2026-07-15 22:55"))[0] == "fx_quiet_hour"
    assert fx_window(s, "eurusd", utc("2026-07-15 23:05")) is None
    assert fx_window(s, "eurusd", utc("2026-07-15 19:55")) is None
    # January: UTC-5, so the window is 21:00-23:59 UTC
    assert fx_window(s, "eurusd", utc("2026-01-14 21:05"))[0] == "fx_quiet_hour"
    assert fx_window(s, "eurusd", utc("2026-01-14 20:05")) is None


def test_other_markets_are_left_alone():
    s = Settings()
    for feed in ("xauusd", "volatility_75_index", "boom_1000_index", "btcusd"):
        assert fx_window(s, feed, utc("2026-07-15 21:00")) is None, feed


def test_the_sunday_open_is_vetoed_when_quiet_hours_are_off():
    s = Settings()
    s.fx_quiet_ny = ()
    # Sunday 2026-07-19: the open is 17:00 New York, 21:00 UTC
    assert fx_window(s, "eurusd", utc("2026-07-19 21:10"))[0] == "fx_sunday_open"
    assert fx_window(s, "eurusd", utc("2026-07-19 21:59"))[0] == "fx_sunday_open"
    assert fx_window(s, "eurusd", utc("2026-07-19 22:01")) is None
    assert fx_window(s, "eurusd", utc("2026-07-15 21:10")) is None  # a Wednesday
    s.fx_sunday_open_min = 0
    assert fx_window(s, "eurusd", utc("2026-07-19 21:10")) is None


def test_the_guard_refuses_fx_in_the_window_and_nothing_else():
    guard = desk()
    assert gate(guard, utc("2026-07-15 21:00")) == "fx_quiet_hour"
    assert gate(guard, utc("2026-07-15 14:00")) != "fx_quiet_hour"
    assert gate(guard, utc("2026-07-15 21:00"), feed="xauusd", symbol="XAUUSD") != "fx_quiet_hour"


def test_both_switch_off():
    guard = desk(fx_quiet_ny=(), fx_sunday_open_min=0.0)
    assert gate(guard, utc("2026-07-15 21:00")) not in ("fx_quiet_hour", "fx_sunday_open")
    assert gate(guard, utc("2026-07-19 21:10")) not in ("fx_quiet_hour", "fx_sunday_open")


def test_the_window_is_read_from_the_environment():
    assert _ny_span("16-19") == (16, 19)
    assert _ny_span("") == ()
    assert _ny_span("19-16") == ()
    assert _ny_span("x") == ()


def test_the_fast_bands_size_brake_applies_when_the_setting_is_unset(monkeypatch):
    """docs/environment.md: `from_env` used to read an unset TRADING_INTERVAL_WEIGHT as no weights,
    silently dropping the brake the dataclass sets."""
    from till_infinity.trading.config import INTERVAL_WEIGHT

    monkeypatch.delenv("TRADING_INTERVAL_WEIGHT", raising=False)
    assert Settings.from_env().interval_weight == INTERVAL_WEIGHT == Settings().interval_weight
    monkeypatch.setenv("TRADING_INTERVAL_WEIGHT", "1m=0.5")
    assert Settings.from_env().interval_weight == (("1m", 0.5),)
