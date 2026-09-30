"""Bar spreads are counts of the broker's points, and the point must be the broker's.

`research/docs/vetoes.md` excluded crypto from its spread tests: the point inferred from the
closes (BTCUSD prints whole) was 1,000 times the broker's 0.001, so a spread read through it was
1,000 times too wide. The research data layer now takes the point from the broker's symbol info.
Production is not affected: its spreads are ask minus bid (`Tick.spread`).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research" / "harness"))
import seqlab

from till_infinity.trading.models import Tick

#: What the broker's symbol info said on 2026-09-30.
BROKER = {
    "BTCUSD": 0.001,
    "ETHUSD": 1e-5,
    "EURUSD": 1e-5,
    "USDJPY": 0.001,
    "XAUUSD": 0.01,
    "Volatility 75 Index": 0.01,
    "Step Index": 0.1,
}


@pytest.fixture(autouse=True)
def _points(tmp_path, monkeypatch):
    path = tmp_path / "points.json"
    path.write_text(json.dumps(BROKER))
    monkeypatch.setattr(seqlab, "POINTS", path)


@pytest.mark.parametrize(
    ("symbol", "price", "points", "bps"),
    [
        ("BTCUSD", 65_000.0, 18_424, 2.834),  # crypto: closes print whole
        ("ETHUSD", 2_500.0, 158_000, 6.32),
        ("EURUSD", 1.10, 11, 1.0),
        ("USDJPY", 147.0, 14, 0.952),
        ("XAUUSD", 4_400.0, 18, 0.409),
        ("Volatility 75 Index", 3_000.0, 150, 5.0),
        ("Step Index", 8_000.0, 1, 0.125),
    ],
)
def test_the_broker_point_gives_the_spread_in_price(symbol, price, points, bps):
    closes = np.full(3000, price)
    bars = {"close": closes, "spread": np.full(3000, float(points))}
    got = seqlab.rel_spread(bars, symbol)[0] * 10_000
    assert got == pytest.approx(points * BROKER[symbol] / closes[0] * 10_000)
    assert got == pytest.approx(bps, rel=0.01)


def test_the_closes_alone_overstate_crypto_a_thousandfold():
    bars = {
        "close": np.tile([65_000.0, 65_010.0, 64_990.0], 1000),
        "spread": np.full(3000, 18_424.0),
    }
    assert seqlab.tick_size(bars) == 1.0
    assert seqlab.tick_size(bars, "BTCUSD") == 0.001


def test_production_reads_spread_from_the_quote():
    assert Tick(symbol="BTCUSD", bid=65_000.0, ask=65_018.424).spread_bps == pytest.approx(
        2.834, rel=1e-3
    )
