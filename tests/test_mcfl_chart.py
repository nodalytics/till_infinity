"""Chart images on the cards: every pattern type renders, fast, at the size phones want.

Snapshot-style rather than pixel-exact: a pixel comparison would fail on every
matplotlib or font update without saying anything about whether the chart is
right. What is checked is that each pattern type draws from real bars without
error, as a 1200x675 PNG, inside the time budget - and, with
`MCFL_WRITE_EXAMPLES=1`, the examples under `docs/img/mcfl/` are rewritten from
the same fixtures so the desk can see them.
"""

from __future__ import annotations

import os
import struct
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from till_infinity.mcfl import cards
from till_infinity.mcfl import chart as ch
from till_infinity.mcfl.config import Settings
from till_infinity.mcfl.desk import Desk, Series
from till_infinity.mcfl.detect import detect
from till_infinity.mcfl.tokens import Bars

FIXTURES = Path(__file__).parent / "fixtures" / "mcfl"
EXAMPLES = Path(__file__).resolve().parents[1] / "docs" / "img" / "mcfl"


def load(name: str) -> Bars:
    d = pd.read_csv(FIXTURES / f"{name}.csv")
    return Bars(
        d["ts"].to_numpy(np.int64),
        *(d[k].to_numpy(float) for k in ("open", "high", "low", "close")),
    )


def first_card(bars: Bars, symbol: str, tf: str, pattern: str, kind: str) -> cards.Card:
    """The first card of a kind found walking the series bar by bar."""
    for last in range(80, len(bars)):
        window = bars.upto(last).tail(300)
        for f in detect(window, tf, "crypto", (pattern,)):
            if f.kind == kind:
                return cards.finding(f, symbol, tf, "crypto", window, venue="binance")
    raise AssertionError(f"no {kind} in the fixture")


def exit_card(tmp_path: Path) -> cards.Card:
    desk = Desk(Settings(state_dir=tmp_path, charts=False))
    bars = load("ARBUSDT.1d")
    series = Series("alt:ARB:1d", "ARB", "1d", "crypto")
    for i in range(60, len(bars)):
        for c in desk.observe(series, bars.upto(i), float(bars.ts[i]) + 86_460):
            if c.key.startswith("DISPLACE_C_LOW12:exit"):
                return c
    raise AssertionError("no exit")


CASES = {
    "displace_c_low12": lambda tmp: first_card(
        load("ARBUSDT.1d"), "ARB", "1d", "DISPLACE_C_LOW12", "DISPLACE_C_LOW12"
    ),
    "bos_4h": lambda tmp: first_card(load("BTCUSDT.4h"), "BTC", "4h", "BOS", "STRUCTURE_SHIFT"),
    "bos_major_15m": lambda tmp: first_card(load("BTCUSDT.15m"), "BTC", "15m", "BOS", "MAJOR_BOS"),
    "breach_revert": lambda tmp: first_card(
        load("BTCUSDT.4h"), "BTC", "4h", "BREACH_REVERT", "BREACH_REVERT"
    ),
    "exit": exit_card,
}


def size(png: bytes) -> tuple[int, int]:
    return struct.unpack(">II", png[16:24])


@pytest.mark.parametrize("name", sorted(CASES))
def test_every_pattern_type_renders(name, tmp_path):
    pytest.importorskip("matplotlib")
    card = CASES[name](tmp_path)
    assert card.chart is not None
    ch.render(ch.Spec(card.chart.bars, "warm"))  # the font cache is built once per process
    started = time.process_time()
    png = ch.render(card.chart)
    took = time.process_time() - started
    assert png is not None
    assert png.startswith(b"\x89PNG")
    assert size(png) == (1200, 675)
    # CPU time, not wall time: a busy runner stretches the wall clock. The aim
    # is about a second; this ceiling catches a render gone pathological, with
    # room for a shared, contended core (1.6s was measured at load 30 on 8).
    assert took < 3.0, f"{name} took {took:.2f}s of CPU"
    if os.environ.get("MCFL_WRITE_EXAMPLES"):
        EXAMPLES.mkdir(parents=True, exist_ok=True)
        (EXAMPLES / f"{name}.png").write_bytes(png)
        (EXAMPLES / f"{name}.txt").write_text(_text(card))


def _text(card: cards.Card) -> str:
    from till_infinity.notifications import from_message

    return from_message(card.payload).as_text() + "\n"


def test_no_matplotlib_means_no_picture_and_no_error(monkeypatch):
    """The card goes out as text, and the reason is said once."""
    import builtins

    real = builtins.__import__

    def refuse(name, *args, **kwargs):
        if name.startswith("matplotlib"):
            raise ImportError("not installed")
        return real(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", refuse)
    monkeypatch.setattr(ch, "_said", set())
    spec = ch.Spec(load("ARBUSDT.1d"), "x")
    assert ch.render(spec) is None
    assert ch.render(spec) is None
    assert ch._said == {"import"}
