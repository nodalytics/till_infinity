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
    assert got["env50_p90"] - got["env50_p10"] > got["env20_p90"] - got["env20_p10"]


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
    assert not any("50 bars" in line for line in lines)  # absent until the long horizon is warm
    assert "compression" in lines[1]
    assert len(ev.card_lines({**got, "tr_percentile": 0.5}, str)) == 1


def test_card_lines_show_the_long_horizon_once_it_is_warm():
    got = {
        "env_ref": 100.0,
        "env5_p10": 99.5,
        "env5_p50": 100.1,
        "env5_p90": 100.6,
        "env50_p10": 98.0,
        "env50_p90": 102.1,
        "env50_cover_p90": 0.89,
    }
    lines = ev.card_lines(got, lambda v: f"${v:,.2f}")
    assert "next 50 bars · ceiling P90 $102.10 (+2.10%) · floor P10 $98.00 (-2.00%)" in lines[1]
    assert "P90 held 89%" in lines[1]


# ------------------------------------------------------ AgACI (research/docs/conformal.md)


def _bars(n: int, sigma: float = 0.001, seed: int = 4):
    """(open, high, low, close), oldest first."""
    rng = random.Random(seed)
    price, out = 100.0, []
    for _ in range(n):
        close = price * math.exp(rng.gauss(0.0, sigma))
        wick = abs(rng.gauss(0.0, sigma / 2))
        out.append(
            (price, max(price, close) * math.exp(wick), min(price, close) * math.exp(-wick), close)
        )
        price = close
    return out


def test_the_single_corrector_quotes_until_agaci_has_learned_enough():
    env = ev.Envelope(horizon=5)
    for price in _walk(ev.WARM, seed=21):
        env.observe(price, 0.001)
    assert not env.aggregated
    for price in _walk(50, seed=22):
        env.observe(price, 0.001)
    assert env.aggregated
    assert env.learned >= ev.WARM


def test_agaci_levels_settle_on_their_targets():
    env = ev.Envelope(horizon=5)
    for price in _walk(8000, seed=23):
        env.observe(price, 0.001)
    p10, p50, p90 = env.agaci_levels
    assert abs(p10 - 0.10) < 0.05
    assert abs(p50 - 0.50) < 0.08
    assert abs(p90 - 0.90) < 0.05


def test_stored_history_teaches_agaci_without_waiting_live():
    book = ev.Book()
    assert book.teach("g", "15m", _bars(3000)) == len(ev.HORIZONS)
    for n in ev.HORIZONS:
        env = book.envelopes[f"g|15m|{n}"]
        assert env.learned >= ev.WARM
        assert env.history == ev.Envelope(horizon=n).history  # history is the engine's to fill
    for price in _walk(400):
        book.observe("g", "15m", price, 0.001)
    assert all(env.aggregated for env in book.envelopes.values())
    assert book.reading("g", "15m", 100.0)["env5_p90"] > 100.0


def test_teaching_leaves_an_envelope_that_already_learned_alone():
    book = ev.Book()
    book.teach("g", "15m", _bars(3000))
    before = [list(r) for r in book.envelopes["g|15m|5"].experts]
    assert book.teach("g", "15m", _bars(3000, seed=9)) == 0
    assert book.envelopes["g|15m|5"].experts == before


def test_adopting_replaces_the_state_and_learns_nothing_from_old_quotes():
    live = ev.Envelope(horizon=5)
    for price in _walk(300):
        live.observe(price, 0.001)
    taught = ev.Book()
    taught.teach("g", "15m", _bars(3000))
    live.adopt(taught.envelopes["g|15m|5"])
    assert live.learned == taught.envelopes["g|15m|5"].learned
    assert all(len(q) == 3 for q in live.pending)
    live.observe(100.0, 0.001)  # the stripped quotes still settle


def test_a_state_saved_before_agaci_restores_and_keeps_its_corrector():
    env = ev.Envelope(horizon=5)
    for price in _walk(400):
        env.observe(price, 0.001)
    # What an envelope saved before AgACI looked like: no correctors, three-part quotes.
    old = {k: getattr(env, k) for k in ("horizon", "history", "hits", "resolved", "quote", "sigma")}
    old["levels"] = [0.12, 0.5, 0.88]
    old["pending"] = [(q[0], q[1], q[2]) for q in env.pending]
    back = ev.Envelope.__new__(ev.Envelope)
    back.__setstate__(old)
    assert back.levels == [0.12, 0.5, 0.88]
    assert back.learned == 0
    for price in _walk(10, seed=8):
        back.observe(price, 0.001)
    assert back.resolved > env.resolved


def test_the_service_teaches_envelopes_from_the_price_store(tmp_path):
    import sqlite3

    from till_infinity.bus import Bus
    from till_infinity.prices import store as pstore
    from till_infinity.structures.config import Settings
    from till_infinity.structures.service import Watcher

    db = tmp_path / "prices.db"
    with sqlite3.connect(db) as conn:
        conn.executescript(pstore.SCHEMA)
        conn.executemany(
            "INSERT INTO bars (source, feed, venue, ticker, interval, ts, open, high, low, close,"
            " closed, updated) VALUES ('broker', 'EURUSD', 'BROKER', 'EURUSD', '15m', ?, ?, ?, ?,"
            " ?, 1, 0)",
            [(900 * k, *bar) for k, bar in enumerate(_bars(3000))],
        )
    watcher = Watcher(Bus(), settings=Settings(prices_db=db, state_dir=tmp_path, feeds=("EURUSD",)))
    assert watcher.warm_envelopes() == len(ev.HORIZONS)
    env = watcher.engine._envelopes().envelopes["EURUSD|15m|5"]
    assert env.learned >= ev.WARM
