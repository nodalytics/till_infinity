"""The z-score reaches the journal and the gate, and cannot quietly reach a trade.

Three joins, each of which was broken or absent when this was written:

* **`to_signal` is handed the reading.** It is a method on `Call`, which has no
  engine and therefore no book to ask - the first attempt reached for
  `self.zma.of(feed, interval)` from a scope with none of the three, and did not
  compile. The reading is a parameter now, the way `vol` already is.
* **What it publishes is numeric.** `Signal.features` is `dict[str, float]` and
  `to_dict` rounds every value, so the obvious `"zma_state": "oversold"` raises
  at publication time rather than at the call site.
* **The gate can only remove trades, and only when asked.** The measured record
  is a coin on this desk's instruments and worse than one on Boom and Crash, so
  agreement buys nothing; `TRADING_ZMA_GATE` decides whether even the veto runs.
"""

from __future__ import annotations

import pytest

from till_infinity.structures import zma as zm
from till_infinity.structures.engine import _zma_context
from till_infinity.trading.config import Settings
from till_infinity.trading.strategies.scalper import CycleScalp, zma_gate


def wound(z: zm.Zma, *, agrees: int) -> zm.Zma:
    """A reading holding a stated agreement, without simulating bars to get one.

    The agreement condition is deliberately strict - the percentile thresholds
    mean a series makes a call every forty-odd bars - so driving one out of
    synthetic prices tests the generator rather than the wiring.
    """
    z.seen = 50
    z.strong = 1.0
    z.z_score = -2.0 if agrees > 0 else 2.0
    z.slope = 1.0 if agrees > 0 else -1.0
    assert z.agrees == agrees
    return z


class TestContext:
    def test_cold_publishes_nothing(self):
        """Absent, not zero: a zero here reads downstream as a measurement."""
        assert _zma_context(zm.Zma()) == {}

    def test_absent_reading_publishes_nothing(self):
        assert _zma_context(None) == {}

    def test_every_published_value_is_a_number(self):
        """`Signal.to_dict` rounds the whole features dict."""
        published = _zma_context(wound(zm.Zma(), agrees=1))
        assert published
        for name, value in published.items():
            assert isinstance(value, float), f"{name} is {type(value).__name__}"
            assert round(value, 6) == pytest.approx(value)

    def test_the_state_is_recoverable_from_what_is_published(self):
        """The word was dropped; the two numbers that define it were not."""
        published = _zma_context(wound(zm.Zma(), agrees=-1))
        assert published["zma_z"] > published["zma_strong"]

    def test_a_broken_reading_is_silent(self):
        class Angry:
            seen = 50

            def __getattr__(self, name):
                raise RuntimeError("no reading")

        assert _zma_context(Angry()) == {}

    def test_disabled_publishes_nothing(self, monkeypatch):
        monkeypatch.setattr(zm, "ENABLED", False)
        assert _zma_context(wound(zm.Zma(), agrees=1)) == {}


class TestGate:
    @pytest.fixture
    def strategy(self):
        settings = Settings()
        settings.zma_gate = True
        found = CycleScalp(settings=settings)
        assert found.settings.zma_gate
        return found

    def test_off_by_default(self):
        """The flag, not the reading, is what decides whether this runs at all."""
        assert Settings().zma_gate is False
        plain = CycleScalp(settings=Settings())
        against = {"zma_agrees": -1.0, "zma_z": 2.0, "zma_strong": 1.0}
        assert zma_gate(plain, {"direction": "up", "feed": "v75"}, against) is None

    def test_refuses_a_call_the_z_score_leans_against(self, strategy):
        refusal = zma_gate(
            strategy,
            {"direction": "up", "feed": "v75"},
            {"zma_agrees": -1.0, "zma_z": 2.0, "zma_strong": 1.0},
        )
        assert refusal is not None
        assert refusal.gate == "zma_against"
        assert "overbought" in refusal.detail

    def test_agreement_does_not_add_a_trade(self, strategy):
        """It returns None either way - the difference is only ever a refusal."""
        agreeing = zma_gate(
            strategy,
            {"direction": "up", "feed": "v75"},
            {"zma_agrees": 1.0, "zma_z": -2.0, "zma_strong": 1.0},
        )
        silent = zma_gate(
            strategy,
            {"direction": "up", "feed": "v75"},
            {"zma_agrees": 0.0, "zma_z": -2.0, "zma_strong": 1.0},
        )
        assert agreeing is None
        assert silent is None

    def test_both_sides(self, strategy):
        down = {"direction": "down", "feed": "v75"}
        assert zma_gate(strategy, down, {"zma_agrees": 1.0, "zma_z": -2.0}) is not None
        assert zma_gate(strategy, down, {"zma_agrees": -1.0, "zma_z": 2.0}) is None

    def test_a_call_with_no_direction_is_not_this_gate_s_refusal(self, strategy):
        """`direction` is refused upstream, and two refusals for one fault is worse."""
        assert zma_gate(strategy, {"feed": "v75"}, {"zma_agrees": -1.0}) is None

    def test_a_cold_call_carries_no_agreement_and_passes(self, strategy):
        assert zma_gate(strategy, {"direction": "up", "feed": "v75"}, {}) is None


class TestBook:
    def test_forgetting_a_feed_drops_every_timeframe_of_it(self):
        book = zm.Book()
        for interval in ("1m", "5m", "1h"):
            book.of("v75", interval)
            book.of("v25", interval)
        assert book.forget({"v75"}) == 3
        assert {feed for feed, _ in book._by_key} == {"v75"}

    def test_standings_are_worst_first(self):
        book = zm.Book()
        for name, right in (("good", 180), ("bad", 40)):
            z = book.of(name, "1m")
            z.calls, z.right = 200, right
        assert [name for name, _, _ in book.standings()] == ["bad 1m", "good 1m"]

    def test_a_series_that_has_not_called_enough_is_not_ranked(self):
        book = zm.Book()
        z = book.of("young", "1m")
        z.calls, z.right = zm.WARM - 1, 0
        assert book.standings() == []
