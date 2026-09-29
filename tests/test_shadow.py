"""The shadowed confirmation gates: they match the measured rules, record, and never act."""

from __future__ import annotations

import math
import random
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from till_infinity.bus import QUOTES, SIGNALS, Bus, Message
from till_infinity.trading import candles
from till_infinity.trading import shadow as sh
from till_infinity.trading.service import Trader

T0 = 1_700_000_000.0


def _bars(closes, minutes=15, t0=T0, volume=None, wick=0.0002):
    out, prev = [], closes[0]
    for i, c in enumerate(closes):
        o = prev
        hi, lo = max(o, c) * (1 + wick), min(o, c) * (1 - wick)
        out.append(
            candles.Bar(
                o,
                hi,
                lo,
                c,
                time=t0 + i * minutes * 60,
                volume=(volume[i] if volume else 100.0 + (i % 7)),
            )
        )
        prev = c
    return out


def _walk(n, seed=1, step=0.0015, start=100.0):
    rng = random.Random(seed)
    out, p = [], start
    for _ in range(n):
        p *= math.exp(rng.gauss(0, step))
        out.append(p)
    return out


def _gate(name):
    return next(g for g in sh.GATES if g.name == name)


def _plan(name, bars, k0, level, side=1, feed="eurusd"):
    """A plan whose window opens at bar k0 of `bars`."""
    gate = _gate(name)
    closes_at = bars[k0].time + sh.MINUTES[gate.ltf] * 60
    return sh.Plan(
        gate=gate,
        feed=feed,
        symbol="X",
        level=level,
        side=side,
        interval=gate.signals[0],
        signal_time=closes_at - sh.WINDOW_OFFSET_S,
        level_id="L",
    )


# ------------------------------------------------------------------ the port matches the harness


@pytest.fixture(scope="module")
def harness():
    pytest.importorskip("sklearn")
    sys.path.insert(0, str(Path(__file__).parents[1] / "research" / "harness"))
    import confirm

    return confirm


def _same(a, b):
    assert len(a) == len(b)
    for x, y in zip(a, b, strict=True):
        if math.isnan(x) or math.isnan(y):
            assert math.isnan(x)
            assert math.isnan(y)
        else:
            assert x == pytest.approx(y, rel=1e-9, abs=1e-12)


def test_the_indicators_are_the_harness_indicators(harness):
    import pandas as pd

    bars = _bars(_walk(400, seed=3), wick=0.001)
    df = pd.DataFrame(
        {
            "ts": [b.time for b in bars],
            "open": [b.open for b in bars],
            "high": [b.high for b in bars],
            "low": [b.low for b in bars],
            "close": [b.close for b in bars],
            "volume": [b.volume for b in bars],
        }
    )
    x = harness.features(df, 15)
    closes = [b.close for b in bars]
    _same(sh.vol(closes), list(x["vol"]))
    _same(sh.trix(closes), list(x["trix"]))
    _same(sh.mfi(bars), list(x["mfi"]))
    _same(sh.chop(bars), list(x["chop"]))
    trig = harness.trigger_arrays(x)
    t, m = sh.trix(closes), sh.mfi(bars)
    for j in range(len(bars)):
        assert sh._turn(t, j, True) == bool(trig["trix"][0][j])
        assert sh._turn(t, j, False) == bool(trig["trix"][1][j])
        assert sh._through(m, j, 20.0, True) == bool(trig["mfi"][0][j])
        assert sh._through(m, j, 80.0, False) == bool(trig["mfi"][1][j])


def test_the_gates_are_the_passing_cells():
    got = {
        g.name: (g.family, g.level_tf, g.ltf, g.rule, g.stop, g.target_r, g.window, g.limit)
        for g in sh.GATES
    }
    assert got == {
        "fx_1h_candle": ("fx", "1h", "15m", "candle", "htf", 2, 4, 40),
        "deriv_1h_sweep": ("deriv", "1h", "15m", "sweep", "htf", 1, 4, 40),
        "deriv_pivot_mfi": ("deriv", "piv", "1h", "mfi", "htf", 2, 24, 240),
        "fx_4h_chop": ("fx", "4h", "1h", "chop", "ltf", 1, 4, 40),
        "crypto_1h_trix": ("crypto", "1h", "1h", "trix", "htf", 1, 8, 10),
    }


# ------------------------------------------------------------------ which signals get a plan


def _signal(feed, interval, above=1.0, level=100.0, **features):
    payload = {
        "shape": "level",
        "feed": feed,
        "interval": interval,
        "time": T0,
        "level_id": "L1",
        "direction": "up",
        "features": {"level": level, **features},
    }
    if above is not None:
        payload["features"]["arrived_above"] = above
    return payload


def _gates(**over):
    async def fetch(symbol, interval, count):
        return []

    async def record(title, context, tags):
        pass

    return sh.ShadowGates(fetch=fetch, record=record, **over)


@pytest.mark.parametrize(
    ("feed", "interval", "gate"),
    [
        ("eurusd", "1h", "fx_1h_candle"),
        ("eurusd", "4h", "fx_4h_chop"),
        ("volatility_75_index", "1h", "deriv_1h_sweep"),
        ("boom_1000_index", "daily", "deriv_pivot_mfi"),
        ("crash_1000_index", "weekly", "deriv_pivot_mfi"),
        ("btcusd", "1h", "crypto_1h_trix"),
    ],
)
def test_a_matching_signal_gets_a_plan(feed, interval, gate):
    gates = _gates()
    made = gates.consider(_signal(feed, interval), "SYM")
    assert [p.gate.name for p in made] == [gate]
    assert made[0].side == 1
    assert made[0].closes_at == T0 + sh.WINDOW_OFFSET_S


@pytest.mark.parametrize(
    ("feed", "interval"),
    [
        ("eurusd", "15m"),
        ("eurusd", "daily"),
        ("xauusd", "1h"),
        ("range_break_100_index", "1h"),
        ("btcusd", "4h"),
        ("volatility_75_index", "4h"),
    ],
)
def test_a_signal_no_gate_was_measured_on_gets_none(feed, interval):
    gates = _gates()
    assert gates.consider(_signal(feed, interval), "SYM") == []
    assert not gates.pending


def test_a_signal_without_its_arrival_side_is_counted_not_guessed():
    gates = _gates()
    assert gates.consider(_signal("eurusd", "1h", above=None), "SYM") == []
    assert gates.no_side == 1
    below = gates.consider(_signal("eurusd", "1h", above=0.0), "SYM")
    assert below[0].side == -1


def test_no_symbol_or_switched_off_records_nothing():
    assert _gates().consider(_signal("eurusd", "1h"), None) == []
    assert _gates(enabled=False).consider(_signal("eurusd", "1h"), "SYM") == []


def test_the_queue_stays_bounded():
    gates = _gates(cap=3)
    for _ in range(5):
        gates.consider(_signal("eurusd", "1h"), "SYM")
    assert len(gates.pending) == 3
    assert gates.dropped == 2


# ------------------------------------------------------------------ the verdicts


def _history(n=260, seed=2):
    return _walk(n, seed=seed, step=0.0008)


def _htf_for(ltf_bars, minutes=60):
    """Hourly bars ending at the last LTF bar, enough for the HTF stop."""
    closes = _walk(120, seed=9, step=0.002, start=ltf_bars[-1].close)
    end = ltf_bars[-1].time
    t0 = end - len(closes) * minutes * 60
    return _bars(closes, minutes=minutes, t0=t0)


def test_chop_passes_in_a_range_and_fails_in_a_trend():
    k0 = 250
    ranging = [100 + (0.3 if i % 2 else -0.3) for i in range(k0 + 10)]
    trending = [100 * (1.002**i) for i in range(k0 + 10)]
    for closes, want in ((ranging, "pass"), (trending, "fail")):
        bars = _bars(closes, minutes=60)
        plan = _plan("fx_4h_chop", bars, k0, level=closes[k0] - 0.5)
        assert sh.evaluate(plan, bars, ())["verdict"] == want


def test_the_sweep_needs_a_trip_through_the_level_and_a_close_back():
    k0 = 250
    base = _history(k0 + 1)
    level = base[-1] * 0.999
    dip = [level * 0.9995, level * 1.0006, level * 1.0008, level * 1.001, level * 1.001]
    stays = [level * 1.002] * 5
    for tail, want in ((dip, "pass"), (stays, "fail")):
        bars = _bars(base + tail, wick=0.0)
        bars = [replace(b, low=min(b.open, b.close), high=max(b.open, b.close)) for b in bars]
        plan = _plan("deriv_1h_sweep", bars, k0, level=level, feed="volatility_75_index")
        got = sh.evaluate(plan, bars, _htf_for(bars))
        assert got["verdict"] == want, got


def test_the_candle_gate_is_production_s_rule():
    k0 = 250
    base = _history(k0 + 1)
    level = base[-1]
    # A long lower wick through the level and a small body at the top, closing above it.
    hammer = candles.Bar(level * 1.0004, level * 1.0010, level * 0.9990, level * 1.0009, time=0.0)
    assert candles.confirms(
        [candles.Bar(level, level, level, level), hammer], level, True, level * 0.0002
    )
    bars = _bars(base + [level * 1.0003] * 4)
    shaped = [*bars[: k0 + 2], replace(hammer, time=bars[k0 + 2].time), *bars[k0 + 3 :]]
    plan = _plan("fx_1h_candle", shaped, k0, level=level)
    assert sh.evaluate(plan, shaped, _htf_for(shaped))["verdict"] == "pass"
    flat = _bars(base + [level * 1.01] * 4)
    assert (
        sh.evaluate(_plan("fx_1h_candle", flat, k0, level=level), flat, _htf_for(flat))["verdict"]
        == "fail"
    )


def test_mfi_passes_on_a_turn_up_from_oversold():
    k0 = 250
    falling = [100 * (0.998**i) for i in range(k0 + 1)]
    turn = [falling[-1] * 1.004 * (1.002**i) for i in range(24)]
    for closes, want in (
        (falling + turn, "pass"),
        (falling + [falling[-1] * 0.998**i for i in range(1, 25)], "fail"),
    ):
        bars = _bars(closes, minutes=60)
        daily = _bars(
            _walk(120, seed=4, step=0.01, start=closes[-1]),
            minutes=1440,
            t0=bars[-1].time - 120 * 86_400,
        )
        plan = _plan("deriv_pivot_mfi", bars, k0, level=closes[k0] * 0.999, feed="boom_1000_index")
        assert sh.evaluate(plan, bars, daily)["verdict"] == want


def test_trix_passes_on_a_turn_and_fails_on_a_steady_fall():
    k0 = 250
    falling = [100 * (0.999**i) for i in range(k0 + 1)]
    for tail, want in (
        ([falling[-1] * 1.003 * 1.002**i for i in range(8)], "pass"),
        ([falling[-1] * 0.999**i for i in range(1, 9)], "fail"),
    ):
        bars = _bars(falling + tail, minutes=60)
        plan = _plan("crypto_1h_trix", bars, k0, level=falling[-1] * 0.999, feed="btcusd")
        assert sh.evaluate(plan, bars, bars)["verdict"] == want


def test_short_history_is_unavailable_not_a_fail():
    bars = _bars(_history(50))
    got = sh.evaluate(_plan("fx_1h_candle", bars, 45, level=bars[45].close), bars, bars)
    assert got["verdict"] == "unavailable"


# ------------------------------------------------------------------ recording


async def test_a_due_plan_is_fetched_evaluated_and_journalled():
    k0 = 250
    ranging = [100 + (0.3 if i % 2 else -0.3) for i in range(k0 + 10)]
    bars = _bars(ranging, minutes=60)
    asked, recorded = [], []

    async def fetch(symbol, interval, count):
        asked.append((symbol, interval))
        return bars

    async def record(title, context, tags):
        recorded.append((title, context, tags))

    plan_time = bars[k0].time + 3600 - sh.WINDOW_OFFSET_S
    gates = sh.ShadowGates(fetch=fetch, record=record, now=lambda: bars[-1].time + 7200)
    gates.consider(
        _signal("eurusd", "4h", above=1.0, level=ranging[k0] - 0.5) | {"time": plan_time}, "EURUSD"
    )
    assert await gates.due() == 1
    assert asked == [("EURUSD", "1h")]  # the LTF stop needs no second fetch
    title, context, tags = recorded[0]
    assert "fx_4h_chop pass" in title
    assert tags == ("eurusd", sh.TAG, "fx_4h_chop")
    for key in (
        "gate",
        "cell",
        "verdict",
        "side",
        "level",
        "stop",
        "entry",
        "risk",
        "targets",
        "cost_r",
        "limit_bars",
        "target_r",
        "plain",
        "signal_time",
        "window_offset_s",
    ):
        assert key in context
    assert context["plain"]["entry"] == ranging[k0]
    assert not gates.pending


async def test_a_fetch_failure_records_unavailable():
    recorded = []

    async def fetch(symbol, interval, count):
        raise RuntimeError("bridge down")

    async def record(title, context, tags):
        recorded.append(context)

    gates = sh.ShadowGates(fetch=fetch, record=record, now=lambda: T0 + 10 * 86_400)
    gates.consider(_signal("eurusd", "1h"), "EURUSD")
    await gates.due()
    assert recorded[0]["verdict"] == "unavailable"


async def test_a_fault_inside_a_gate_never_escapes(monkeypatch):
    def boom(*args, **kwargs):
        raise ZeroDivisionError

    async def fetch(symbol, interval, count):
        return _bars(_history(300))

    async def record(title, context, tags):
        pass

    monkeypatch.setattr(sh, "evaluate", boom)
    gates = sh.ShadowGates(fetch=fetch, record=record, now=lambda: T0 + 10 * 86_400)
    gates.consider(_signal("eurusd", "1h"), "EURUSD")
    assert await gates.due() == 1
    assert gates.evaluated == 1


# ------------------------------------------------------------------ the service


def _settings(**over):
    from tests.test_trading import settings

    return settings(**over)


async def test_the_switch_is_read_from_settings():
    assert Trader(Bus(), settings=_settings()).gates.enabled is True
    assert Trader(Bus(), settings=_settings(shadow_gates=False)).gates.enabled is False


def _snapshot(got):
    if got is None:
        return None
    fields = (
        "feed",
        "symbol",
        "side",
        "volume",
        "entry",
        "stop",
        "target",
        "reason",
        "code",
        "detail",
    )
    return (type(got).__name__, tuple(getattr(got, f, None) for f in fields))


async def test_the_shadow_changes_nothing_trading_decides(monkeypatch):
    from tests.test_trading import signal

    monkeypatch.setattr(sh, "family", lambda feed: "fx")  # so gold's 1h signal gets a plan
    results = []
    for on in (True, False):
        trader = Trader(Bus(), settings=_settings(shadow_gates=on))
        await trader.start()
        await trader.handle(
            Message(topic=QUOTES, payload={"feed": "gold", "bid": 4399.5, "ask": 4400.5})
        )
        payload = signal(interval="1h", features={"arrived_above": 1.0})
        got = await trader.handle(Message(topic=SIGNALS, payload=payload))
        results.append((_snapshot(got), len(trader.open), trader.taken, len(trader.gates.pending)))
    (on_got, on_open, on_taken, on_pending), (off_got, off_open, off_taken, off_pending) = results
    assert (on_got, on_open, on_taken) == (off_got, off_open, off_taken)
    assert on_pending == 1
    assert off_pending == 0
