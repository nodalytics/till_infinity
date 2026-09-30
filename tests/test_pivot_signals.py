"""Pivot-level calls are published under their session's name, which the shadow gate reads.

`research/docs/confirm.md`'s `deriv_pivot_mfi` gate found nothing to record in the journal
snapshot, because until 869031d (2026-09-11) pivot levels were never checked. These pin the path
from a pivot touch to a published signal the gate matches - and that no strategy trades one.
"""

from __future__ import annotations

import math
import random

import pytest

from till_infinity.bus import Bus
from till_infinity.structures import reactions
from till_infinity.structures.config import Settings
from till_infinity.structures.drawing import pivots
from till_infinity.structures.service import Watcher
from till_infinity.trading import shadow as sh
from till_infinity.trading.strategies import strategy as ts

FEED = "boom_1000_index"


def _pivot_calls(watcher: Watcher, days: int = 3) -> list:
    engine = watcher.engine
    engine.consensus.single_source = frozenset({FEED})
    rng = random.Random(1)
    price, t = 10_000.0, 1_780_000_000 - (1_780_000_000 % 86_400)
    found = []
    for _ in range(60 * 24 * days):
        opened = price
        price *= math.exp(rng.gauss(0, 0.0008))
        high, low = max(opened, price) * 1.0003, min(opened, price) * 0.9997
        bar = {
            "feed": FEED,
            "venue": "DERIV",
            "interval": "1m",
            "time": t,
            "open": opened,
            "high": high,
            "low": low,
            "close": price,
        }
        found += [c for c in engine.observe_bar(bar) if c.interval in pivots.PERIODS]
        engine.drain_resolved()
        t += 60
    return found


def test_pivot_levels_are_touched_and_called_under_their_session():
    calls = _pivot_calls(Watcher(Bus(), settings=Settings()))
    assert calls
    assert {c.interval for c in calls} <= set(pivots.PERIODS)


def test_an_actionable_pivot_call_is_published_as_a_level_signal_the_gate_matches(monkeypatch):
    watcher = Watcher(Bus(), settings=Settings())
    call = _pivot_calls(watcher)[0]
    monkeypatch.setattr(reactions.Inference, "actionable", property(lambda self: True))
    signals = watcher._level_calls([call])
    assert signals
    payload = signals[0].to_dict()
    assert payload["interval"] in pivots.PERIODS
    assert payload["shape"] == "level"
    assert "arrived_above" in payload["features"]

    async def fetch(symbol, interval, count):
        return []

    async def record(title, context, tags):
        pass

    plans = sh.ShadowGates(fetch=fetch, record=record).consider(payload, "BOOM1000")
    assert [p.gate.name for p in plans] == ["deriv_pivot_mfi"]


def test_no_strategy_trades_a_pivot_interval():
    """Publishing pivot signals must not start trading them: strategies select by interval."""
    import till_infinity.trading.service  # noqa: F401  (registers every strategy)

    assert len(ts.STRATEGIES) >= 10
    for name, cls in ts.STRATEGIES.items():
        entries = getattr(cls, "entries", ()) or ()
        assert not set(entries) & set(pivots.PERIODS), name


@pytest.mark.parametrize("period", pivots.PERIODS)
def test_the_session_names_are_the_ones_the_gate_reads(period):
    assert period in sh.PIVOTS
