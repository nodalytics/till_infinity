import asyncio

import pytest

from till_infinity.prices import INTERVALS, Bar, JsonlStore, SeriesKey, SqliteStore, Symbol
from till_infinity.prices.store import iter_bars

MINUTE = INTERVALS["1m"]
KEY = SeriesKey("tradingview", "gold", Symbol("OANDA", "XAUUSD"), "1m")


def bars(*times: int, close: float = 100.0) -> list[Bar]:
    return [Bar(t, close, close + 1, close - 1, close, 10.0) for t in times]


@pytest.mark.asyncio
async def test_sqlite_upserts_only_unclosed_bars(tmp_path):
    async with SqliteStore(tmp_path / "p.db") as store:
        first = await store.write(KEY, bars(60, 120), MINUTE)
        assert (first.inserted, first.updated) == (2, 0)

        # Same timestamps again: both bars are closed, so history stands.
        again = await store.write(KEY, bars(60, 120, close=999.0), MINUTE)
        assert (again.inserted, again.updated) == (0, 0)
        assert [b.close for b in await store.bars(KEY)] == [100.0, 100.0]


@pytest.mark.asyncio
async def test_sqlite_corrects_a_bar_that_was_still_forming(tmp_path):
    forming = int(asyncio.get_running_loop().time())  # unused, keeps intent explicit
    del forming
    now = 10_000_000_000  # far future -> the bar is not closed yet
    async with SqliteStore(tmp_path / "p.db") as store:
        await store.write(KEY, [Bar(now, 1, 1, 1, 1, 0)], MINUTE)
        result = await store.write(KEY, [Bar(now, 1, 5, 1, 4, 7)], MINUTE)
        assert (result.inserted, result.updated) == (0, 1)
        assert (await store.bars(KEY))[-1].close == 4.0


@pytest.mark.asyncio
async def test_sqlite_series_summary(tmp_path):
    async with SqliteStore(tmp_path / "p.db") as store:
        await store.write(KEY, bars(60, 120, 180), MINUTE)
        (info,) = await store.series()
    assert info.key == KEY
    assert (info.bars, info.first_time, info.last_time) == (3, 60, 180)


@pytest.mark.asyncio
async def test_jsonl_appends_forward_only(tmp_path):
    async with JsonlStore(tmp_path) as store:
        assert (await store.write(KEY, bars(60, 120), MINUTE)).inserted == 2
        # 120 is already on disk; only 180 is new.
        assert (await store.write(KEY, bars(120, 180), MINUTE)).inserted == 1
        path = store.path(KEY)
    assert [b.time for b in iter_bars(path)] == [60, 120, 180]
    assert path.name == "gold_OANDA_XAUUSD_1m.jsonl"


@pytest.mark.asyncio
async def test_jsonl_dedup_survives_a_restart(tmp_path):
    async with JsonlStore(tmp_path) as store:
        await store.write(KEY, bars(60, 120), MINUTE)
    async with JsonlStore(tmp_path) as reopened:  # cold cache, reads the tail
        assert (await reopened.write(KEY, bars(120, 180), MINUTE)).inserted == 1
    assert [b.time for b in iter_bars(tmp_path / "tradingview" / f"{KEY.slug}.jsonl")] == [
        60,
        120,
        180,
    ]


@pytest.mark.asyncio
async def test_jsonl_series_recovers_venue_with_underscores(tmp_path):
    key = SeriesKey("tradingview", "eurusd", Symbol("FX_IDC", "EURUSD"), "1h")
    async with JsonlStore(tmp_path) as store:
        await store.write(key, bars(3600, 7200), INTERVALS["1h"])
        (info,) = await store.series()
    assert info.key.symbol == Symbol("FX_IDC", "EURUSD")
    assert info.bars == 2
