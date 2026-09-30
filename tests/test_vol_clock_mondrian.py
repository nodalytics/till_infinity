"""The hour-of-week volatility clock, the Mondrian envelope by ZMA state, and the hour card line."""

from __future__ import annotations

import datetime as dt
import math
import random

import pytest

from till_infinity.structures import codec as scodec
from till_infinity.structures.vol import clock as ck
from till_infinity.structures.vol import envelope as ev


def utc(text: str) -> float:
    return dt.datetime.fromisoformat(text).replace(tzinfo=dt.UTC).timestamp()


# ------------------------------------------------------------------ the clock


@pytest.mark.parametrize(
    ("feed", "fam"),
    [
        ("eurusd", "fx"),
        ("btcusd", "crypto"),
        ("xauusd", "metals"),
        ("volatility_75_index", None),
        ("boom_1000_index", None),
        ("spx500", None),
    ],
)
def test_families(feed, fam):
    assert ck.family(feed) == fam


def test_fx_cells_are_on_new_yorks_clock_through_daylight_saving():
    # 21:00 UTC is 17:00 New York in July (EDT) and 16:00 in January (EST); both Wednesdays
    assert ck.cell("fx", utc("2026-07-15 21:00")) == 2 * 24 + 17
    assert ck.cell("fx", utc("2026-01-14 21:00")) == 2 * 24 + 16
    assert ck.cell("crypto", utc("2026-07-15 21:00")) == 2 * 24 + 21


def _feed_hours(book: ck.Clock, feed: str, loud_hour: int, weeks: int = 30, seed: int = 3):
    """1h bars whose moves are twice as big in one UTC hour of every day."""
    rng = random.Random(seed)
    price, t = 100.0, utc("2026-01-05 00:00")
    for _ in range(weeks * 7 * 24):
        hour = dt.datetime.fromtimestamp(t, dt.UTC).hour
        sd = 0.002 if hour == loud_hour else 0.001
        price *= math.exp(rng.gauss(0.0, sd))
        book.observe(feed, "1h", t, price, 0.001)
        t += 3600


def test_it_is_neutral_until_warm():
    book = ck.Clock()
    assert book.multiplier("btcusd", "1h", utc("2026-01-05 00:00"), 5, 3600) == 1.0
    assert book.now("btcusd", "1h", utc("2026-01-05 00:00")) is None


def test_it_learns_the_loud_hour_and_scales_the_unit_for_it():
    book = ck.Clock()
    _feed_hours(book, "btcusd", loud_hour=14)
    loud = book.now("btcusd", "1h", utc("2026-09-02 14:30"))
    quiet = [book.now("btcusd", "1h", utc(f"2026-09-02 {h:02d}:30")) for h in range(24) if h != 14]
    assert loud == pytest.approx(2.0 / (23 / 24 + 2 / 24), rel=0.15)
    # one cell holds ~30 observations, so judge the quiet hours together
    assert sum(quiet) / len(quiet) == pytest.approx(1.0 / (23 / 24 + 2 / 24), rel=0.05)
    # the next bar alone is the loud hour: the unit is scaled up by about its multiple
    one = book.multiplier("btcusd", "1h", utc("2026-09-02 14:00"), 1, 3600)
    assert one == pytest.approx(loud, rel=1e-6)


def test_metals_are_described_but_never_scaled_and_deriv_has_no_clock():
    book = ck.Clock()
    _feed_hours(book, "xauusd", loud_hour=14)
    assert book.now("xauusd", "1h", utc("2026-09-02 14:30")) > 1.3  # the card may say so
    assert book.multiplier("xauusd", "1h", utc("2026-09-02 14:00"), 5, 3600) == 1.0
    _feed_hours(book, "volatility_75_index", loud_hour=14)
    assert book.now("volatility_75_index", "1h", utc("2026-09-02 14:30")) is None
    assert book.multiplier("volatility_75_index", "1h", utc("2026-09-02 14:00"), 5, 3600) == 1.0


def test_the_switch_turns_it_off(monkeypatch):
    book = ck.Clock()
    _feed_hours(book, "btcusd", loud_hour=14)
    monkeypatch.setattr(ck, "ENABLED", False)
    assert book.multiplier("btcusd", "1h", utc("2026-09-02 14:00"), 1, 3600) == 1.0
    assert book.now("btcusd", "1h", utc("2026-09-02 14:30")) is None


def test_the_clock_survives_the_state_file():
    book = ck.Clock()
    _feed_hours(book, "btcusd", loud_hour=14, weeks=26)
    back = scodec.unpack(scodec.pack({"c": book}))["c"]
    when = utc("2026-09-02 14:30")
    assert back.now("btcusd", "1h", when) == book.now("btcusd", "1h", when)
    assert back.forget({"eurusd"}) == 1


def test_the_card_line_shows_only_a_notable_hour():
    assert ck.card_line({"vol_clock": 1.62}) == [
        "🕐 this hour is historically 1.6x average volatility"
    ]
    assert ck.card_line({"vol_clock": 0.6}) == [
        "🕐 this hour is historically 0.6x average volatility"
    ]
    assert ck.card_line({"vol_clock": 1.1}) == []
    assert ck.card_line({}) == []


def test_the_envelope_card_carries_the_hour_line():
    got = {
        "env_ref": 100.0,
        "env5_p10": 99.5,
        "env5_p50": 100.0,
        "env5_p90": 100.5,
        "vol_clock": 1.8,
    }
    assert any(line.startswith("🕐") for line in ev.card_lines(got, str))


def test_the_scale_widens_the_empirical_band_but_not_a_law_or_a_model():
    walk = [100.0 * math.exp(0.001 * math.sin(i) + 0.0003 * i % 0.01) for i in range(400)]
    plain, scaled = ev.Book(), ev.Book()
    for price in walk:
        plain.observe("btcusd", "1h", price, 0.001)
        scaled.observe("btcusd", "1h", price, 0.001, scale=dict.fromkeys(ev.HORIZONS, 2.0))
    a = plain.envelopes["btcusd|1h|5"]
    b = scaled.envelopes["btcusd|1h|5"]
    assert b.sigma == pytest.approx(2 * a.sigma)
    law = ev.Book()
    law.observe("volatility_75_index", "1h", 1000.0, 0.001, scale=dict.fromkeys(ev.HORIZONS, 2.0))
    assert law.envelopes["volatility_75_index|1h|5"].sigma == pytest.approx(0.001)


# ------------------------------------------------------------------ Mondrian by ZMA state


def _walk(n: int, seed: int = 5):
    rng = random.Random(seed)
    price = 100.0
    for _ in range(n):
        price *= math.exp(rng.gauss(0.0, 0.001))
        yield price


def test_each_bucket_learns_only_from_its_own_quotes(monkeypatch):
    monkeypatch.setattr(ev, "MONDRIAN", True)  # off by default; these test it on
    book = ev.Book()
    for i, price in enumerate(_walk(1200)):
        book.observe("btcusd", "15m", price, 0.001, bucket=1 if i % 3 == 0 else 0)
    up = book.mondrian["btcusd|15m|5|1"]
    inside = book.mondrian["btcusd|15m|5|0"]
    down = book.mondrian["btcusd|15m|5|-1"]
    assert up.resolved == pytest.approx(1200 / 3, abs=10)
    assert inside.resolved == pytest.approx(2 * 1200 / 3, abs=10)
    assert down.resolved == 0


def test_a_bucket_is_published_only_once_it_has_its_own_history(monkeypatch):
    monkeypatch.setattr(ev, "MONDRIAN", True)  # off by default; these test it on
    book = ev.Book()
    for price in _walk(100):
        book.observe("btcusd", "15m", price, 0.001, bucket=1)
    assert "btcusd|15m|5" not in book.chosen  # 95 outcomes: the pooled envelope speaks
    for price in _walk(400, seed=6):
        book.observe("btcusd", "15m", price, 0.001, bucket=1)
    assert book.chosen["btcusd|15m|5"] == 1
    got = book.reading("btcusd", "15m", 100.0)
    assert got["env5_zma"] == 1.0
    assert 0.0 <= got["env5_cover_p90"] <= 1.0  # the published quotes' own record


def test_no_mondrian_without_a_bucket_or_for_a_published_law():
    book = ev.Book()
    for price in _walk(300):
        book.observe("btcusd", "15m", price, 0.001)
        book.observe("volatility_75_index", "15m", price, 0.001, bucket=1)
    assert not book.mondrian
    assert "volatility_75_index|15m|5" not in book.chosen


def test_the_switch_turns_mondrian_off(monkeypatch):
    monkeypatch.setattr(ev, "MONDRIAN", False)
    book = ev.Book()
    for price in _walk(300):
        book.observe("btcusd", "15m", price, 0.001, bucket=1)
    assert not book.mondrian


def test_a_boosted_base_stays_the_base_in_every_bucket(monkeypatch):
    monkeypatch.setattr(ev, "MONDRIAN", True)  # off by default; these test it on
    fixed = [-2.0, -1.2, 0.0, 1.2, 2.0]
    monkeypatch.setattr(ev, "_safe_quantiles", lambda n, features: list(fixed))
    book = ev.Book()
    for price in _walk(50):
        book.observe("eurusd", "15m", price, 0.001, {"lvol": 0.0}, bucket=0)
    assert book.envelopes["eurusd|15m|5"].base == ev.MODEL_RECIPE
    assert book.mondrian["eurusd|15m|5|0"].base == ev.MODEL_RECIPE


def test_mondrian_state_survives_the_state_file_and_forget():
    book = ev.Book()
    for i, price in enumerate(_walk(600)):
        book.observe("btcusd", "15m", price, 0.001, bucket=1 if i % 2 else -1)
    back = scodec.unpack(scodec.pack({"b": book}))["b"]
    assert back.reading("btcusd", "15m", 100.0) == book.reading("btcusd", "15m", 100.0)
    back.observe("btcusd", "15m", 100.1, 0.001, bucket=0)  # and it keeps working
    assert back.forget({"eurusd"}) == len(ev.HORIZONS)
    assert not back.mondrian
    assert not back.published


# ------------------------------------------------------------------ the engine's hooks


def test_the_engine_reads_the_zma_bucket_after_the_close_and_publishes_the_hour():
    from till_infinity.structures import engine

    eng = engine.Engine(intervals=("1h",))
    assert eng._zma_bucket("btcusd", "1h") is None  # the z-score has not seen the series
    for price in _walk(300):
        eng.zma.observe("btcusd", "1h", price)
    assert eng._zma_bucket("btcusd", "1h") in (-1, 0, 1)
    assert eng._clock_at("btcusd", "1h", utc("2026-09-02 14:30")) == {}  # cold
    _feed_hours(eng._vol_clock(), "btcusd", loud_hour=14)
    got = eng._clock_at("btcusd", "1h", utc("2026-09-02 14:30"))
    assert got["vol_clock"] > 1.3
    scale = eng._clock_scale("btcusd", "1h", utc("2026-09-02 13:00"), 100.0, 0.001)
    assert set(scale) == set(ev.HORIZONS)
    assert eng._clock_scale("xauusd", "1h", utc("2026-09-02 13:00"), 100.0, 0.001) is None
