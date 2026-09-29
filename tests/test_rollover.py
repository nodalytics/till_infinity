"""The FX rollover mask: nothing opens or resolves on the 17:00 New York spread spike."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from till_infinity.structures import engine as eng
from till_infinity.structures import rollover as ro
from till_infinity.structures.levels import Kalman, Level


def at(text: str) -> float:
    return datetime.fromisoformat(text).replace(tzinfo=UTC).timestamp()


SUMMER = "2026-07-15"  # New York on EDT: the roll is 21:00 UTC
WINTER = "2026-01-15"  # on EST: 22:00 UTC


@pytest.mark.parametrize(
    ("feed", "fx"),
    [
        ("EURUSD", True),
        ("eurusd", True),
        ("EUR/USD", True),
        ("usd_jpy", True),
        ("XAUUSD", False),
        ("BTCUSD", False),
        ("Volatility 75 Index", False),
        ("spx500", False),
    ],
)
def test_only_currency_pairs_are_fx(feed, fx):
    assert ro.is_fx(feed) is fx


def test_the_window_follows_new_york_through_daylight_saving():
    assert ro.masked("EURUSD", at(f"{SUMMER} 20:57"))
    assert ro.masked("EURUSD", at(f"{SUMMER} 21:09"))
    assert not ro.masked("EURUSD", at(f"{SUMMER} 20:54"))
    assert not ro.masked("EURUSD", at(f"{SUMMER} 21:11"))
    assert not ro.masked("EURUSD", at(f"{SUMMER} 22:00"))
    assert ro.masked("EURUSD", at(f"{WINTER} 22:00"))
    assert not ro.masked("EURUSD", at(f"{WINTER} 21:00"))


def test_a_bar_is_masked_if_it_reaches_the_window():
    assert ro.masked("EURUSD", at(f"{SUMMER} 20:45"), at(f"{SUMMER} 21:00"))
    assert ro.masked("EURUSD", at(f"{SUMMER} 21:00"), at(f"{SUMMER} 21:15"))
    assert not ro.masked("EURUSD", at(f"{SUMMER} 20:30"), at(f"{SUMMER} 20:45"))
    assert not ro.masked("EURUSD", at(f"{SUMMER} 21:15"), at(f"{SUMMER} 21:30"))


def test_long_bars_and_other_markets_are_never_masked():
    # A 4h bar always spans 17:00; masking it would stop the feed from ever touching.
    assert not ro.masked("EURUSD", at(f"{SUMMER} 20:00"), at(f"{SUMMER} 23:59"))
    assert not ro.masked("XAUUSD", at(f"{SUMMER} 21:00"))
    assert not ro.masked("Volatility 75 Index", at(f"{SUMMER} 21:00"))


def test_the_mask_can_be_switched_off(monkeypatch):
    monkeypatch.setattr(ro, "ENABLED", False)
    assert not ro.masked("EURUSD", at(f"{SUMMER} 21:00"))


# ------------------------------------------------------------------ the engine


def _machine(feed: str) -> tuple[eng.Engine, Level]:
    machine = eng.Engine(intervals=("1m",))
    volatility = machine.vol.of(feed, "1m")
    for i in range(200):
        volatility.update(100.0 + (i % 5) * 0.1)
    level = Level(feed=feed, interval="1m", filter=Kalman(mean=100.0, variance=0.01))
    machine._levels[(feed, "1m")] = [level]
    return machine, level


def test_no_fx_touch_opens_on_the_spike():
    machine, level = _machine("eurusd")
    machine.check("eurusd", "1m", 100.0, at(f"{SUMMER} 21:01"))
    assert machine.tracker.open_touch(level) is None
    machine.check("eurusd", "1m", 100.0, at(f"{SUMMER} 21:30"))
    assert machine.tracker.open_touch(level) is not None


def test_other_markets_still_touch_at_the_same_minute():
    machine, level = _machine("xauusd")
    machine.check("xauusd", "1m", 100.0, at(f"{SUMMER} 21:01"))
    assert machine.tracker.open_touch(level) is not None


def test_an_open_fx_touch_is_carried_through_the_spike_untouched():
    handed: list[float] = []

    class Touching:
        started = at(f"{SUMMER} 20:30")

        def carry(self, level, price, vol, when):
            pass

        def open_touch(self, level):
            return self

        def update(self, level, price, vol, when, low=None, high=None):
            handed.append(when)

        def expire(self, when):
            return []

    machine, _ = _machine("eurusd")
    machine.tracker = Touching()
    inside = at(f"{SUMMER} 21:02")
    machine.check("eurusd", "1m", 100.0, inside, low=95.0, high=105.0, since=inside - 60)
    after = at(f"{SUMMER} 21:20")
    machine.check("eurusd", "1m", 100.0, after, low=99.9, high=100.1, since=after - 60)
    assert handed == [after]
