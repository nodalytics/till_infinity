"""The N-bar volatility envelope: P10 / P50 / P90 that are hit at the rate they claim."""

from __future__ import annotations

import math
import random

from till_infinity.structures import codec as scodec
from till_infinity.structures.vol import envelope as ev


def _walk(n: int, sigma: float = 0.001, seed: int = 3):
    rng = random.Random(seed)
    price = 100.0
    for _ in range(n):
        price *= math.exp(rng.gauss(0.0, sigma))
        yield price


def test_cold_publishes_nothing():
    book = ev.Book()
    for price in _walk(50):
        book.observe("g", "15m", price, 0.001)
    assert book.reading("g", "15m", 100.0) == {}


def test_warm_publishes_ordered_quantiles_for_each_horizon():
    book = ev.Book()
    for price in _walk(400):
        book.observe("g", "15m", price, 0.001)
    got = book.reading("g", "15m", 100.0)
    for n in ev.HORIZONS:
        assert got[f"env{n}_p10"] < got[f"env{n}_p50"] < got[f"env{n}_p90"]
        assert got[f"env{n}_width_bps"] > 0
        assert 0.0 <= got[f"env{n}_cover_p90"] <= 1.0


def test_on_a_random_walk_the_percentiles_are_hit_at_their_stated_rates():
    env = ev.Envelope(horizon=5)
    for price in _walk(8000, seed=11):
        env.observe(price, 0.001)
    p10, p50, p90 = env.coverage()
    assert abs(p10 - 0.10) < 0.025
    assert abs(p50 - 0.50) < 0.03
    assert abs(p90 - 0.90) < 0.025


def test_a_p90_that_is_being_hit_too_rarely_is_read_from_further_up_the_tail():
    env = ev.Envelope(horizon=1)
    for price in _walk(300, seed=5):
        env.observe(price, 0.001)
    before = env.levels[2]
    # A regime three times as volatile as the unit says: outcomes clear P90 far too often.
    for price in _walk(400, sigma=0.003, seed=6):
        env.observe(price * 1.0, 0.001)
    assert env.levels[2] > before


def test_bad_inputs_are_ignored():
    env = ev.Envelope(horizon=5)
    env.observe(0.0, 0.001)
    env.observe(100.0, 0.0)
    env.observe(100.0, float("nan"))
    assert env.resolved == 0
    assert len(env.pending) == 0


def test_history_and_pending_stay_bounded():
    env = ev.Envelope(horizon=5)
    for price in _walk(ev.WINDOW + 500):
        env.observe(price, 0.001)
    assert len(env.history) == ev.WINDOW
    assert len(env.pending) == 5


def test_forget_drops_only_the_feeds_not_kept():
    book = ev.Book()
    for price in _walk(10):
        book.observe("a", "15m", price, 0.001)
        book.observe("b", "1h", price, 0.001)
    assert book.forget({"a"}) == len(ev.HORIZONS)
    assert all(k.startswith("a|") for k in book.envelopes)


def test_an_envelope_survives_the_state_file_with_its_bounds():
    book = ev.Book()
    for price in _walk(400):
        book.observe("g", "15m", price, 0.001)
    back = scodec.unpack(scodec.pack({"book": book}))["book"]
    env = back.envelopes["g|15m|5"]
    assert env.history.maxlen == ev.WINDOW
    assert env.pending.maxlen is not None
    assert back.reading("g", "15m", 100.0) == book.reading("g", "15m", 100.0)
    env.observe(101.0, 0.001)  # and it keeps working after the round trip


def test_the_engine_publishes_the_envelope_once_warm():
    from till_infinity.structures import engine

    eng = engine.Engine(intervals=("15m",))
    assert eng._envelope_at("g", "15m", 100.0) == {}
    for price in _walk(400):
        eng._envelopes().observe("g", "15m", price, 0.001)
    got = eng._envelope_at("g", "15m", 100.0)
    assert got["env5_p10"] < got["env5_p50"] < got["env5_p90"]
    assert got["env20_p90"] - got["env20_p10"] > got["env5_p90"] - got["env5_p10"]


def test_card_lines_are_silent_while_cold():
    assert ev.card_lines({"tr_percentile": 0.1}, str) == []


def test_card_lines_show_the_envelope_its_cover_and_the_volatility_state():
    got = {
        "env_ref": 100.0,
        "env5_p10": 99.5,
        "env5_p50": 100.1,
        "env5_p90": 100.6,
        "env5_cover_p90": 0.9,
        "tr_percentile": 0.15,
    }
    lines = ev.card_lines(got, lambda v: f"${v:,.2f}")
    assert "ceiling P90 $100.60 (+0.60%)" in lines[0]
    assert "floor P10 $99.50 (-0.50%)" in lines[0]
    assert "P90 held 90%" in lines[0]
    assert "compression" in lines[1]
    assert len(ev.card_lines({**got, "tr_percentile": 0.5}, str)) == 1
