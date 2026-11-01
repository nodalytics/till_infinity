"""FX-only vetoes in New York's clock: the close-and-rollover hours and the Sunday open.

`research/docs/vetoes.md`: FX entries at 16:00-18:59 New York did -0.43 / -0.45 vol worse, and the
Sunday open's first hour -1.2 / -1.5, while Deriv did better in the same hours - so FX only, and
in New York time so daylight saving cannot move the window.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import replace

from till_infinity.domain.models import Intent, Side
from till_infinity.risk.envelope import Envelope
from till_infinity.risk.guard import Guard, fx_window
from till_infinity.strategies import Settings
from till_infinity.strategies.config import _ny_span


def utc(text: str) -> float:
    return dt.datetime.fromisoformat(text).replace(tzinfo=dt.UTC).timestamp()


def limits(**over) -> Envelope:
    """The shipped limits, tuned, and projected the way production projects them."""
    made = Settings()
    for k, v in over.items():
        setattr(made, k, v)
    return made.envelope()


def desk(**over) -> Guard:
    guard = Guard(limits(**over), currency="USD")
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
    """**The window was measured in New York time, so it has to be applied in
    it.** Held as UTC it would be right for half the year and an hour wrong
    for the other half - and wrong in the direction that matters, because
    20:00 UTC in January is 15:00 New York, which is an hour of normal
    trading being refused while the hour that actually lost is let through.
    """
    s = limits()
    # July: New York is UTC-4, so 16:00-18:59 New York is 20:00-22:59 UTC
    assert fx_window(s, "eurusd", utc("2026-07-15 20:05"))[0] == "fx_quiet_hour"
    assert fx_window(s, "eurusd", utc("2026-07-15 22:55"))[0] == "fx_quiet_hour"
    assert fx_window(s, "eurusd", utc("2026-07-15 23:05")) is None
    assert fx_window(s, "eurusd", utc("2026-07-15 19:55")) is None
    # January: UTC-5, so the window is 21:00-23:59 UTC
    assert fx_window(s, "eurusd", utc("2026-01-14 21:05"))[0] == "fx_quiet_hour"
    assert fx_window(s, "eurusd", utc("2026-01-14 20:05")) is None


def test_other_markets_are_left_alone():
    """Deriv did *better* in the same hours, so a veto applied to everything
    would be paying for the FX finding out of the synthetics' returns. The
    four feeds below are one from each family the desk trades."""
    s = limits()
    for feed in ("xauusd", "volatility_75_index", "boom_1000_index", "btcusd"):
        assert fx_window(s, feed, utc("2026-07-15 21:00")) is None, feed


def test_the_sunday_open_is_vetoed_when_quiet_hours_are_off():
    """Two vetoes that overlap in the clock, separated so each can be measured.

    The Sunday open is 17:00 New York, which falls inside the 16:00-18:59
    quiet window - so with quiet hours on, nothing here would reach the Sunday
    rule and it could be broken without a test noticing.
    """
    s = limits(fx_quiet_ny=())
    # Sunday 2026-07-19: the open is 17:00 New York, 21:00 UTC
    assert fx_window(s, "eurusd", utc("2026-07-19 21:10"))[0] == "fx_sunday_open"
    assert fx_window(s, "eurusd", utc("2026-07-19 21:59"))[0] == "fx_sunday_open"
    assert fx_window(s, "eurusd", utc("2026-07-19 22:01")) is None
    assert fx_window(s, "eurusd", utc("2026-07-15 21:10")) is None  # a Wednesday
    # `replace` rather than assignment: the limits a gate reads are frozen, so
    # that the refusal in the journal can be recomputed from them later.
    assert fx_window(replace(s, fx_sunday_open_min=0.0), "eurusd", utc("2026-07-19 21:10")) is None


def test_the_guard_refuses_fx_in_the_window_and_nothing_else():
    """`fx_window` answering correctly is not the same as the gate being
    wired to it, and a veto that is computed and not consulted is the shape of
    dead path this suite has already paid for twice."""
    guard = desk()
    assert gate(guard, utc("2026-07-15 21:00")) == "fx_quiet_hour"
    assert gate(guard, utc("2026-07-15 14:00")) != "fx_quiet_hour"
    assert gate(guard, utc("2026-07-15 21:00"), feed="xauusd", symbol="XAUUSD") != "fx_quiet_hour"


def test_either_veto_can_be_switched_off_without_the_other():
    """Both are measured findings, not rules, and `vetoes.md` is a document
    that can be revised. A veto with no off switch is one that outlives the
    measurement behind it."""
    guard = desk(fx_quiet_ny=(), fx_sunday_open_min=0.0)
    assert gate(guard, utc("2026-07-15 21:00")) not in ("fx_quiet_hour", "fx_sunday_open")
    assert gate(guard, utc("2026-07-19 21:10")) not in ("fx_quiet_hour", "fx_sunday_open")


def test_a_malformed_window_is_no_window_rather_than_a_guess():
    """Every form below is something a hand-edited env file produces. **An
    unparseable span switches the veto off rather than inventing one**, which
    is the safe direction here: a window nobody asked for refuses trades for
    three hours a day and reads as a quiet market.

    `19-16` is the instructive case - a reversed span is a typo, not a wrap
    around midnight, because the measurement that produced the window is a
    single evening block.
    """
    assert _ny_span("16-19") == (16, 19)
    assert _ny_span("") == ()
    assert _ny_span("19-16") == ()
    assert _ny_span("x") == ()


def test_the_fast_bands_size_brake_applies_when_the_setting_is_unset(monkeypatch):
    """docs/environment.md: `from_env` used to read an unset TRADING_INTERVAL_WEIGHT as no weights,
    silently dropping the brake the dataclass sets."""
    from till_infinity.strategies.config import INTERVAL_WEIGHT

    monkeypatch.delenv("TRADING_INTERVAL_WEIGHT", raising=False)
    assert Settings.from_env().interval_weight == INTERVAL_WEIGHT == Settings().interval_weight
    monkeypatch.setenv("TRADING_INTERVAL_WEIGHT", "1m=0.5")
    assert Settings.from_env().interval_weight == (("1m", 0.5),)
