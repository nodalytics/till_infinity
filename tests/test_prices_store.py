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
async def test_prune_keeps_the_newest_bars_of_every_series(tmp_path):
    """Retention is per series, and it keeps the recent end.

    Both halves matter and only one is obvious. Dropping the newest bars would
    also satisfy "no series exceeds the cap".
    """
    other = SeriesKey("tradingview", "btc", Symbol("BINANCE", "BTCUSDT"), "1m")
    async with SqliteStore(tmp_path / "p.db") as store:
        await store.write(KEY, bars(*range(60, 60 * 21, 60)), MINUTE)  # 20 bars
        await store.write(other, bars(*range(60, 60 * 6, 60)), MINUTE)  # 5 bars

        result = await store.prune(keep=5)

        assert result.deleted == 15  # only the long series loses anything
        assert result.kept == 10
        # The recent end survived, oldest first.
        assert [b.time for b in await store.bars(KEY)] == [960, 1020, 1080, 1140, 1200]
        # A series already under the cap is untouched.
        assert len(await store.bars(other)) == 5


@pytest.mark.asyncio
async def test_prune_counts_series_separately_rather_than_the_table(tmp_path):
    """A per-table cap would empty a quiet series to make room for a busy one."""
    quiet = SeriesKey("tradingview", "gold", Symbol("SAXO", "XAUUSD"), "1w")
    async with SqliteStore(tmp_path / "p.db") as store:
        await store.write(KEY, bars(*range(60, 60 * 51, 60)), MINUTE)  # 50
        await store.write(quiet, bars(60, 120), MINUTE)  # 2

        await store.prune(keep=10)

        assert len(await store.bars(KEY)) == 10
        assert len(await store.bars(quiet)) == 2, "a quiet series was pruned to feed a busy one"


@pytest.mark.asyncio
async def test_prune_refuses_to_empty_the_table(tmp_path):
    async with SqliteStore(tmp_path / "p.db") as store:
        await store.write(KEY, bars(60, 120), MINUTE)
        with pytest.raises(ValueError, match="at least 1"):
            await store.prune(keep=0)
        assert len(await store.bars(KEY)) == 2


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


# --------------------------------------------------------------- quote retention


def _write_quotes(store, *ages_in_days: float) -> None:
    """One quote per age, written straight to the table - `ts` is epoch **milliseconds**."""
    import time

    now = time.time()
    conn = store._require()
    with conn:
        conn.executemany(
            "INSERT OR REPLACE INTO quotes (source, feed, venue, ticker, ts, bid, ask)"
            " VALUES ('tradingview','gold','OANDA','XAUUSD',?,1.0,2.0)",
            [(int((now - age * 86_400.0) * 1000.0),) for age in ages_in_days],
        )


@pytest.mark.asyncio
async def test_quotes_are_left_alone_unless_a_window_is_asked_for(tmp_path):
    """**This is how a production file reached 29.5 GB.** `prune` applied its retention to `bars`
    and touched `quotes` not at all, so the default has to stay "leave them" for any caller that
    has not opted in - and the opt-in has to exist."""
    async with SqliteStore(tmp_path / "p.db") as store:
        await store.write(KEY, bars(60, 120), MINUTE)
        _write_quotes(store, 400.0, 0.1)
        result = await store.prune(1)
        assert result.quotes_deleted == 0
        assert store._require().execute("SELECT COUNT(*) FROM quotes").fetchone()[0] == 2


@pytest.mark.asyncio
async def test_quotes_older_than_the_window_go_and_newer_ones_stay(tmp_path):
    async with SqliteStore(tmp_path / "p.db") as store:
        await store.write(KEY, bars(60, 120), MINUTE)
        _write_quotes(store, 40.0, 20.0, 13.9, 1.0, 0.0)
        result = await store.prune(1, quote_days=14.0)
        assert result.quotes_deleted == 2, "the 40-day and 20-day quotes"
        assert result.quotes_kept == 3
        assert "quotes" in str(result)


@pytest.mark.asyncio
async def test_the_cutoff_is_in_milliseconds_not_seconds(tmp_path):
    """`quotes.ts` is epoch **milliseconds** where `bars.ts` is seconds. A cutoff computed in
    seconds is a thousand times too small, so every quote looks newer than it and **nothing** is
    deleted - a prune that reports success and reclaims nothing, which is the failure mode this
    whole exercise was chasing."""
    async with SqliteStore(tmp_path / "p.db") as store:
        await store.write(KEY, bars(60), MINUTE)
        _write_quotes(store, 365.0)
        result = await store.prune(1, quote_days=1.0)
        assert result.quotes_deleted == 1, "a year-old quote must not survive a one-day window"


@pytest.mark.asyncio
async def test_pruning_quotes_never_empties_the_bars_policy(tmp_path):
    """The two tables are cut by different policies and neither may stand in for the other."""
    async with SqliteStore(tmp_path / "p.db") as store:
        await store.write(KEY, bars(60, 120, 180), MINUTE)
        _write_quotes(store, 99.0)
        result = await store.prune(2, quote_days=14.0)
        assert (result.deleted, result.kept) == (1, 2)
        assert (result.quotes_deleted, result.quotes_kept) == (1, 0)


@pytest.mark.asyncio
async def test_a_backend_with_no_quotes_says_nothing_rather_than_raising(tmp_path):
    """The collector calls this on a timer, and an `AttributeError` in a loop that must not stop
    collecting is worse than a backend admitting it has nothing to trim."""
    async with JsonlStore(tmp_path) as store:
        assert store.prune_quotes_sync(14.0) == 0


@pytest.mark.asyncio
async def test_the_live_trim_touches_quotes_and_leaves_bars(tmp_path):
    """What the collector runs every hour: quotes only, no VACUUM, nothing held for a rebuild."""
    async with SqliteStore(tmp_path / "p.db") as store:
        await store.write(KEY, bars(60, 120, 180), MINUTE)
        _write_quotes(store, 90.0, 30.0, 0.5)
        went = store.prune_quotes_sync(14.0)
        assert went == 2
        assert len(await store.bars(KEY)) == 3, "bars are the CLI's job, not the loop's"
        assert store.prune_quotes_sync(0) == 0, "zero days is off, not empty-the-table"


@pytest.mark.asyncio
async def test_the_trim_is_batched_and_respects_its_cap(tmp_path):
    """**The version before this shipped unbatched and would have knocked the desk over.**

    `DELETE FROM quotes WHERE ts < ?` is one transaction, so against years of backlog it tries to
    delete everything at once and the write-ahead log grows to hold it - which is the exact failure
    this retention exists to prevent. The cap is what makes a first run against a large backlog
    safe: a bounded bite now, the rest on the next hourly pass.
    """
    from till_infinity.prices.store import QUOTE_BATCH

    async with SqliteStore(tmp_path / "p.db") as store:
        await store.write(KEY, bars(60), MINUTE)
        _write_quotes(store, *[100.0 + i / 1000.0 for i in range(500)])
        total = store._require().execute("SELECT COUNT(*) FROM quotes").fetchone()[0]
        assert total == 500

        # A cap below the backlog takes a bite and leaves the rest.
        went = store.prune_quotes_sync(14.0, limit=200)
        assert went == 200
        assert store._require().execute("SELECT COUNT(*) FROM quotes").fetchone()[0] == 300

        # And a later pass finishes the job rather than needing the cap raised.
        assert store.prune_quotes_sync(14.0, limit=10_000) == 300
        assert store._require().execute("SELECT COUNT(*) FROM quotes").fetchone()[0] == 0
        # The batch size is what bounds a transaction, so it must stay well under the run cap.
        assert QUOTE_BATCH < 10_000_000


@pytest.mark.asyncio
async def test_the_trim_stops_early_rather_than_spinning_on_an_empty_table(tmp_path):
    """The loop exits when a batch comes back short, so a cap of two million does not mean two
    million pointless round trips against a table with nothing old in it."""
    async with SqliteStore(tmp_path / "p.db") as store:
        await store.write(KEY, bars(60), MINUTE)
        _write_quotes(store, 0.1, 0.2)  # both inside any sane window
        assert store.prune_quotes_sync(14.0) == 0
        assert store._require().execute("SELECT COUNT(*) FROM quotes").fetchone()[0] == 2


@pytest.mark.asyncio
async def test_vacuum_actually_runs_after_a_prune(tmp_path):
    """A 50-minute maintenance window ended here on 2026-09-23: the deletes committed, the log
    checkpointed down from 10.5 GB, and then `conn.execute("VACUUM")` raised `OperationalError:
    database is locked` and reclaimed nothing - a 29.8 GB file left 29.8 GB with 21.5 GB free
    *inside* it.

    **This test does not reproduce that failure and is not claimed to.** `lsof` showed the cause
    was the service container holding the file after a deploy restarted it mid-window, which no
    unit test can stage and no change in this method could have prevented.

    What it does guard is narrower and still worth having: that the prune's own code path reaches
    VACUUM and returns, with the connection usable afterwards. Both were true before the defensive
    commit was added, which is precisely why the comment there says it is not the fix.
    """
    async with SqliteStore(tmp_path / "p.db") as store:
        await store.write(KEY, bars(60, 120, 180, 240), MINUTE)
        _write_quotes(store, 90.0, 0.5)
        result = await store.prune(1, vacuum=True, quote_days=14.0)
        assert result.vacuumed is True
        assert result.deleted == 3
        assert result.quotes_deleted == 1
        # And the connection is still usable afterwards, with its isolation level restored.
        assert len(await store.bars(KEY)) == 1


@pytest.mark.asyncio
async def test_vacuum_survives_the_quote_prune_being_skipped(tmp_path):
    """The same path with no quote window, since the two branches reach VACUUM differently."""
    async with SqliteStore(tmp_path / "p.db") as store:
        await store.write(KEY, bars(60, 120), MINUTE)
        result = await store.prune(1, vacuum=True)
        assert result.vacuumed is True
        assert result.deleted == 1
