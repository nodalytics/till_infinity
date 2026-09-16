import asyncio
import contextlib
import time
from dataclasses import replace
from unittest.mock import patch

import pytest

from till_infinity.prices import Quote, QuoteKey, Settings, SqliteStore, Symbol, poll_once
from till_infinity.prices.config import FEEDS
from till_infinity.prices.quotes import QuoteSource, QuoteTick, build_quote_sources, parse_quote

KEY = QuoteKey("tradingview", "gold", Symbol("OANDA", "XAUUSD"))


def test_parse_quote_reads_a_live_body():
    quote = parse_quote(
        {"ask": 4401.2, "bid": 4400.46, "ch": None, "chp": None, "lp": None, "volume": 626511},
        now=1000.0,
    )
    assert (quote.bid, quote.ask) == (4400.46, 4401.2)
    assert quote.mid == pytest.approx(4400.83)
    assert quote.spread == pytest.approx(0.74)
    assert quote.spread_bps == pytest.approx(1.6815, rel=1e-3)
    assert quote.volume == 626511.0


def test_parse_quote_rejects_an_error_body():
    assert parse_quote({"code": "symbol_not_exists", "errmsg": "empty"}, now=1.0) is None
    assert parse_quote({"bid": None, "ask": None, "lp": None}, now=1.0) is None
    assert parse_quote("not json", now=1.0) is None


def test_mid_falls_back_to_last_when_there_is_no_book():
    quote = Quote(time=1.0, last=4400.0)
    assert quote.mid == 4400.0
    assert quote.spread is None
    assert quote.spread_bps is None


def test_a_zero_spread_sorts_ahead_of_a_wide_one():
    tick = QuoteTick(
        quotes={
            QuoteKey("tv", "eurusd", Symbol("OANDA", "EURUSD")): Quote(1.0, 1.15278, 1.15293),
            QuoteKey("tv", "eurusd", Symbol("FOREXCOM", "EURUSD")): Quote(1.0, 1.15306, 1.15306),
            QuoteKey("tv", "eurusd", Symbol("TVC", "EURUSD")): Quote(1.0, last=1.15),
        }
    )
    assert [key.symbol.venue for key, _ in tick.by_feed("eurusd")] == [
        "FOREXCOM",  # zero spread is the tightest, not the loosest
        "OANDA",
        "TVC",  # no book at all sorts last
    ]


class FakeQuotes(QuoteSource):
    name = "tradingview"
    feed_key = "tradingview"

    def __init__(self, settings, delay=0.0):
        super().__init__(settings)
        self.delay = delay
        self.seen: list[str] = []

    async def quote(self, symbol):
        if self.delay:
            await asyncio.sleep(self.delay)
        self.seen.append(symbol.full)
        if symbol.venue == "DERIV":  # the scanner does not carry these
            return None
        return Quote(time=1000.0, bid=1.0, ask=1.5)


@pytest.mark.asyncio
async def test_poll_once_covers_every_broker_and_counts_the_gaps(tmp_path):
    settings = Settings(data_dir=tmp_path)
    source = FakeQuotes(settings)
    feeds = [FEEDS["gold"]]
    tick = await poll_once([source], feeds, concurrency=4)

    expected = len(FEEDS["gold"].for_source("tradingview"))
    assert len(source.seen) == expected
    assert len(tick.quotes) == expected - 1  # DERIV has no scanner quote
    assert tick.missing == 1


@pytest.mark.asyncio
async def test_written_counts_survive_concurrency(tmp_path):
    """`x += await f()` would lose updates here - every write must be counted."""
    settings = Settings(data_dir=tmp_path)
    source = FakeQuotes(settings, delay=0.01)
    feeds = [FEEDS["gold"], FEEDS["eurusd"], FEEDS["gbpusd"]]

    async with SqliteStore(tmp_path / "p.db") as store:
        tick = await poll_once([source], feeds, concurrency=16, sink=store.write_quote)
        rows = 0
        for key in tick.quotes:
            rows += len(await store.quotes(key))
    assert tick.written.inserted == len(tick.quotes) == rows


@pytest.mark.asyncio
async def test_unchanged_quotes_are_not_rewritten(tmp_path):
    async with SqliteStore(tmp_path / "p.db") as store:
        assert (await store.write_quote(KEY, Quote(1000.0, 1.0, 2.0))).inserted == 1
        # Same top of book one poll later: nothing moved, nothing to store.
        assert (await store.write_quote(KEY, Quote(1015.0, 1.0, 2.0))).inserted == 0
        assert (await store.write_quote(KEY, Quote(1030.0, 1.0, 2.5))).inserted == 1
        assert [q.ask for q in await store.quotes(KEY)] == [2.0, 2.5]


@pytest.mark.asyncio
async def test_all_ticks_mode_keeps_every_poll(tmp_path):
    async with SqliteStore(tmp_path / "p.db", dedupe_quotes=False) as store:
        await store.write_quote(KEY, Quote(1000.0, 1.0, 2.0))
        await store.write_quote(KEY, Quote(1015.0, 1.0, 2.0))
        assert len(await store.quotes(KEY)) == 2


@pytest.mark.asyncio
async def test_quotes_round_trip_through_sqlite(tmp_path):
    async with SqliteStore(tmp_path / "p.db") as store:
        await store.write_quote(KEY, Quote(1000.5, 4400.46, 4401.2, 4400.8, 12.0, 1.5, 0.03))
        (stored,) = await store.quotes(KEY)
    assert stored.time == pytest.approx(1000.5)
    assert (stored.bid, stored.ask, stored.last) == (4400.46, 4401.2, 4400.8)
    assert stored.change_pct == 0.03


def test_parse_quote_keeps_the_venues_own_clock():
    """`lp_time` was requested and discarded for two years.

    Every venue on the record therefore carried our *receive* time, which makes
    cross-venue lead-lag unmeasurable from stored data at any horizon - the
    single limit that capped `research/lagging.md` and `research/crossing.md`.
    """
    quote = parse_quote({"bid": 1.1, "ask": 1.2, "lp_time": 1789000000}, now=1789000000.4)
    assert quote is not None
    assert quote.venue_time == 1789000000.0
    assert quote.time == 1789000000.4  # ours, and different: that gap is the point


def test_a_quote_without_a_venue_clock_is_still_a_quote():
    quote = parse_quote({"bid": 1.1, "ask": 1.2}, now=1.0)
    assert quote is not None
    assert quote.venue_time is None


@pytest.mark.asyncio
async def test_the_venue_clock_survives_sqlite_at_sub_second_resolution(tmp_path):
    async with SqliteStore(tmp_path / "p.db") as store:
        await store.write_quote(KEY, Quote(2000.0, 1.0, 2.5, venue_time=1999.25))
        (stored,) = await store.quotes(KEY)
    # Milliseconds, because a lead-lag measured in seconds measures nothing.
    assert stored.venue_time == pytest.approx(1999.25)
    assert stored.time - stored.venue_time == pytest.approx(0.75)


@pytest.mark.asyncio
async def test_a_live_database_grows_the_venue_column(tmp_path):
    """`CREATE TABLE IF NOT EXISTS` does nothing to a table that already exists.

    Without the migration the column would reach new databases and silently miss
    every running one - which is the only kind we have.
    """
    import sqlite3

    path = tmp_path / "p.db"
    old = sqlite3.connect(path)
    old.executescript(
        "CREATE TABLE quotes (source TEXT NOT NULL, feed TEXT NOT NULL,"
        " venue TEXT NOT NULL, ticker TEXT NOT NULL, ts INTEGER NOT NULL,"
        " bid REAL, ask REAL, last REAL, mid REAL, spread REAL, spread_bps REAL,"
        " volume REAL, change REAL, change_pct REAL,"
        " PRIMARY KEY (source, feed, venue, ticker, ts)) WITHOUT ROWID;"
    )
    old.execute(
        "INSERT INTO quotes (source, feed, venue, ticker, ts, bid, ask)"
        " VALUES (?, ?, ?, ?, 1000, 1.0, 2.0)",
        (KEY.source, KEY.feed, KEY.symbol.venue, KEY.symbol.ticker),
    )
    old.commit()
    old.close()

    async with SqliteStore(path) as store:
        await store.write_quote(KEY, Quote(2000.0, 1.0, 2.5, venue_time=1999.0))
        rows = await store.quotes(KEY)
    # The row written before the column existed reads back as unknown, not lost.
    assert [q.venue_time for q in rows] == [None, 1999.0]

    async with SqliteStore(path) as store:  # opening twice must not re-add it
        assert len(await store.quotes(KEY)) == 2


@pytest.mark.asyncio
async def test_jsonl_quotes_land_under_a_quotes_directory(tmp_path):
    from till_infinity.prices import JsonlStore

    async with JsonlStore(tmp_path) as store:
        await store.write_quote(KEY, Quote(1000.0, 1.0, 2.0))
        path = store.quote_path(KEY)
    assert path == tmp_path / "quotes" / "tradingview" / "gold_OANDA_XAUUSD.jsonl"
    assert path.exists()


def test_quote_sources_default_to_tradingview(tmp_path):
    settings = Settings(data_dir=tmp_path)
    assert [s.name for s in build_quote_sources(None, settings)] == ["tradingview"]
    assert [s.name for s in build_quote_sources(("yahoo",), settings)] == ["yahoo"]
    with pytest.raises(ValueError, match="unknown quote source"):
        build_quote_sources(("reuters",), settings)


class Recorder:
    """A sink that remembers what it was handed."""

    def __init__(self):
        self.calls: list[tuple[QuoteKey, Quote]] = []

    async def __call__(self, key, quote):
        self.calls.append((key, quote))
        from till_infinity.prices import WriteResult

        return WriteResult(inserted=1)


def socket_source(tmp_path):
    from till_infinity.prices.quotes import TradingViewQuotes

    return TradingViewQuotes(Settings(data_dir=tmp_path))


@pytest.mark.asyncio
async def test_socket_pushes_each_update_to_the_sink(tmp_path):
    source = socket_source(tmp_path)
    sink = Recorder()
    source._sink = sink
    source._keys[KEY.symbol.full] = KEY
    source._ready[KEY.symbol.full] = asyncio.Event()

    await source._on_update(
        ["qs_1", {"n": KEY.symbol.full, "s": "ok", "v": {"bid": 1.0, "ask": 2.0}}]
    )

    assert len(sink.calls) == 1
    assert sink.calls[0][1].bid == 1.0
    assert source.drain_pushed().inserted == 1
    assert source.drain_pushed().inserted == 0  # drained


@pytest.mark.asyncio
async def test_socket_merges_partial_updates(tmp_path):
    """A tick carries only the fields that moved - the rest must survive."""
    source = socket_source(tmp_path)
    sink = Recorder()
    source._sink = sink
    source._keys[KEY.symbol.full] = KEY
    source._ready[KEY.symbol.full] = asyncio.Event()

    await source._on_update(
        ["qs", {"n": KEY.symbol.full, "v": {"bid": 1.0, "ask": 2.0, "lp": 1.5}}]
    )
    await source._on_update(["qs", {"n": KEY.symbol.full, "v": {"ask": 2.5}}])

    latest = sink.calls[-1][1]
    assert (latest.bid, latest.ask, latest.last) == (1.0, 2.5, 1.5)


@pytest.mark.asyncio
async def test_socket_ignores_a_volume_only_update(tmp_path):
    source = socket_source(tmp_path)
    sink = Recorder()
    source._sink = sink
    source._keys[KEY.symbol.full] = KEY
    source._ready[KEY.symbol.full] = asyncio.Event()

    await source._on_update(["qs", {"n": KEY.symbol.full, "v": {"volume": 10.0}}])
    assert sink.calls == []  # nothing tradable moved


@pytest.mark.asyncio
async def test_socket_marks_an_error_symbol_unavailable(tmp_path):
    source = socket_source(tmp_path)
    name = KEY.symbol.full
    source._keys[name] = KEY
    source._ready[name] = asyncio.Event()

    await source._on_update(["qs", {"n": name, "s": "error"}])
    assert name in source._failed
    assert source._ready[name].is_set()  # waiters released rather than hung
    assert await source.quote(KEY.symbol) is None


@pytest.mark.asyncio
async def test_a_dead_reader_is_noticed_on_a_prepared_symbol(tmp_path):
    """**The reconnect was unreachable for every symbol the desk follows.**

    `quote()` only checked the socket for a symbol nobody had prepared, and
    every symbol on the desk is prepared at start-up. So a dropped reader was
    permanent: the task ended, no poll looked at it again, and the cache went
    on answering. Twice on 2026-09-16 the desk wrote no quote for hours - once
    for 2h34m - with nothing logged, every other actor healthy, and bars still
    arriving. That is the failure this test exists for, and the symbol being
    already known is the whole point of it.
    """
    source = socket_source(tmp_path)
    name = KEY.symbol.full
    source._keys[name] = KEY
    source._fields[name] = {"bid": 1.0, "ask": 2.0}

    async def died():
        raise RuntimeError("socket closed")

    source._reader = asyncio.create_task(died())
    await asyncio.sleep(0)

    tried = []

    async def reconnect():
        tried.append(True)

    source._ensure_live = reconnect
    assert await source.quote(KEY.symbol) is not None, "and answers from the cache meanwhile"
    assert source._repair is not None, "a prepared symbol must still ask for the socket back"
    await source._repair
    assert tried, "and the repair must actually run"


@pytest.mark.asyncio
async def test_a_poll_that_never_finishes_says_so_and_names_the_tasks(tmp_path, caplog):
    """**The desk has to be able to say where it is stuck.**

    Four times on 2026-09-16 quotes stopped while bars kept arriving, nothing
    raised, nothing logged, and every actor read as running. Three fixes were
    aimed at whichever await seemed likeliest, and all three were wrong,
    because there was no way to ask. A stalled poll now dumps every task and
    where it is standing.
    """
    import logging

    from till_infinity.prices import quotes as q

    clock = [0.0]
    ticking = type("Clock", (), {"monotonic": staticmethod(lambda: clock[0])})

    started = asyncio.Event()

    async def never(*a, **k):
        started.set()
        await asyncio.Event().wait()

    real_sleep = asyncio.sleep

    async def jump(delay, *a, **k):
        clock[0] += delay
        await real_sleep(0)

    settings = Settings(data_dir=tmp_path)
    with (
        patch.object(q, "poll_once", never),
        patch.object(q, "build_quote_sources", lambda *a, **k: []),
        patch.object(q, "time", ticking),
        patch.object(q.asyncio, "sleep", jump),
        caplog.at_level(logging.WARNING, logger=q.log.name),
    ):
        runner = asyncio.create_task(q.stream(settings=settings, feeds=[], sink=None))
        await asyncio.wait_for(started.wait(), timeout=2)
        for _ in range(200):
            await real_sleep(0)
            if any("no quote poll has finished" in r.getMessage() for r in caplog.records):
                break
        runner.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await runner

    said = [r.getMessage() for r in caplog.records]
    assert any("no quote poll has finished" in m for m in said), said[-3:]
    assert any("stuck task" in m for m in said), "and it must name the tasks, not only complain"


@pytest.mark.asyncio
async def test_polls_that_finish_but_write_nothing_are_reported_too(tmp_path, caplog):
    """**The stall that actually happens, and the one the first watchdog
    missed.**

    At 11:03 on 2026-09-16 both transports stopped writing and the watchdog
    said nothing for nine minutes - because the poll loop was turning perfectly
    well. A hung await and a source that has gone quiet look identical from
    outside and need opposite fixes, so they have to be told apart here.
    """
    import logging

    from till_infinity.prices import quotes as q

    clock = [0.0]
    ticking = type("Clock", (), {"monotonic": staticmethod(lambda: clock[0])})

    class Mute(QuoteSource):
        name = "mute"
        feed_key = "mute"

        def diagnose(self):
            return "mute says why it is quiet"

    real_sleep = asyncio.sleep

    async def jump(delay, *a, **k):
        clock[0] += delay
        await real_sleep(0)

    async def empty(*a, **k):
        return QuoteTick()  # finished, wrote nothing

    settings = Settings(data_dir=tmp_path)
    with (
        patch.object(q, "poll_once", empty),
        patch.object(q, "build_quote_sources", lambda *a, **k: [Mute(settings)]),
        patch.object(q, "time", ticking),
        patch.object(q.asyncio, "sleep", jump),
        caplog.at_level(logging.WARNING, logger=q.log.name),
    ):
        runner = asyncio.create_task(q.stream(settings=settings, feeds=[], sink=None))
        for _ in range(300):
            await real_sleep(0)
            if any("nothing has been written" in r.getMessage() for r in caplog.records):
                break
        runner.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await runner

    said = [r.getMessage() for r in caplog.records]
    assert any("written nothing for" in m for m in said), said[-3:]
    assert any("mute" in m and "written nothing" in m for m in said), (
        "and it must name the source that went quiet, not the poll as a whole - a book where "
        "one source still produces makes every poll look productive"
    )
    assert any("mute says why it is quiet" in m for m in said), "and each source explains itself"
    assert not any("stuck task" in m for m in said), "a turning loop is not a hung one"


@pytest.mark.asyncio
async def test_one_busy_source_does_not_hide_a_dark_one(tmp_path, caplog):
    """**Why the totals cannot answer this.**

    `tick.written` sums every source, so one transport still producing makes
    every poll look productive while the rest of the book is dark. That is not
    hypothetical: on 2026-09-16 the watchdog stayed silent through a
    thirteen-minute outage in which both named transports wrote nothing.
    """
    import logging

    from till_infinity.prices import quotes as q

    clock = [0.0]
    ticking = type("Clock", (), {"monotonic": staticmethod(lambda: clock[0])})

    class Busy(QuoteSource):
        name = "busy"
        feed_key = "busy"

    class Dark(QuoteSource):
        name = "dark"
        feed_key = "dark"

        def diagnose(self):
            return "dark explains itself"

    real_sleep = asyncio.sleep

    async def jump(delay, *a, **k):
        clock[0] += delay
        await real_sleep(0)

    from till_infinity.prices import WriteResult

    async def busy_only(*a, **k):
        tick = QuoteTick()
        tick.by_source["busy"] = WriteResult(inserted=1)
        tick.by_source["dark"] = WriteResult()
        tick.written = WriteResult(inserted=1)
        return tick

    settings = Settings(data_dir=tmp_path)
    with (
        patch.object(q, "poll_once", busy_only),
        patch.object(q, "build_quote_sources", lambda *a, **k: [Busy(settings), Dark(settings)]),
        patch.object(q, "time", ticking),
        patch.object(q.asyncio, "sleep", jump),
        caplog.at_level(logging.WARNING, logger=q.log.name),
    ):
        runner = asyncio.create_task(q.stream(settings=settings, feeds=[], sink=None))
        for _ in range(300):
            await real_sleep(0)
            if any("written nothing" in r.getMessage() for r in caplog.records):
                break
        runner.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await runner

    said = [r.getMessage() for r in caplog.records]
    assert any("dark" in m and "written nothing" in m for m in said), said[-3:]
    assert not any("busy has written nothing" in m for m in said), "the busy one is fine"


@pytest.mark.asyncio
async def test_the_poll_path_awaits_nothing_that_can_hang(tmp_path):
    """**The strongest form of the rule, because the weaker ones both failed.**

    Bounding the reconnect was not enough (the bound could not bind), and not
    queueing on the lock was not enough either. `poll_once` runs one task group
    across every source and waits for all of it, so a single task that does not
    return stops the broker half of the book as well - which is exactly what
    both 2026-09-16 outages looked like: quotes from both transports ending on
    the same minute as a tradingview socket drop, with `collect` still writing
    bars beside them.

    So for a symbol already prepared, `quote()` must reach no network at all.
    Here the reconnect never returns and the repair task never completes, and
    the poll still finishes immediately.
    """
    source = socket_source(tmp_path)
    name = KEY.symbol.full
    source._keys[name] = KEY
    source._fields[name] = {"bid": 1.0, "ask": 2.0}
    source._touched[name] = time.time()

    async def died():
        raise RuntimeError("socket closed")

    source._reader = asyncio.create_task(died())
    await asyncio.sleep(0)

    async def never():
        await asyncio.sleep(3600)

    source._ensure_live = never
    try:
        started = time.monotonic()
        got = await asyncio.wait_for(source.quote(KEY.symbol), timeout=1)
        assert time.monotonic() - started < 0.2, "the poll waited on the network"
        assert got is not None
        assert got.bid == 1.0
        assert source._repair is not None
        assert not source._repair.done(), "the repair is still running; the poll did not wait"
    finally:
        if source._repair is not None:
            source._repair.cancel()


@pytest.mark.asyncio
async def test_one_repair_at_a_time(tmp_path):
    """Every symbol in the book notices the same dead socket in the same poll.
    One reconnect, not fifty."""
    source = socket_source(tmp_path)
    book = [Symbol("OANDA", t) for t in ("XAUUSD", "EURUSD", "GBPUSD")]
    for sym in book:
        source._keys[sym.full] = QuoteKey("tradingview", "x", sym)
        source._fields[sym.full] = {"bid": 1.0, "ask": 2.0}

    async def died():
        raise RuntimeError("socket closed")

    source._reader = asyncio.create_task(died())
    await asyncio.sleep(0)

    runs = []

    async def slow():
        runs.append(True)
        await asyncio.sleep(3600)

    source._ensure_live = slow
    try:
        for sym in book:
            await source.quote(sym)
        await asyncio.sleep(0)
        assert len(runs) <= 1, f"{len(runs)} reconnects for one dropped socket"
    finally:
        if source._repair is not None:
            source._repair.cancel()


@pytest.mark.asyncio
async def test_a_failed_reconnect_is_still_dead(tmp_path):
    """A reconnect that fails leaves no reader at all. Written as "not None and
    done", the check stops asking after the first failure and the source never
    comes back - the outage becomes permanent on the first thing that goes
    wrong with fixing it."""
    source = socket_source(tmp_path)
    source._reader = None
    assert source._dead()


@pytest.mark.asyncio
async def test_a_hanging_reconnect_does_not_stop_the_poll(tmp_path):
    """**A reconnect on the polling path must not be able to stop polling.**

    `poll_once` runs one task group over every source, so an unbounded connect
    here does not merely delay tradingview - it holds the group open and the
    broker half of the book stops quoting too. That happened at 08:58 on
    2026-09-16, fifteen minutes after the liveness check first shipped: the
    socket dropped, the reconnect hung, both transports went dark, and
    `collect` carried on writing bars as if nothing were wrong.
    """
    source = socket_source(tmp_path)
    source.settings = replace(source.settings, tv_connect_timeout=0.05)
    name = KEY.symbol.full
    source._keys[name] = KEY
    source._fields[name] = {"bid": 1.0, "ask": 2.0}
    source._touched[name] = time.time()

    async def died():
        raise RuntimeError("socket closed")

    source._reader = asyncio.create_task(died())
    await asyncio.sleep(0)

    async def never():
        await asyncio.sleep(3600)

    source._ensure_live = never

    started = time.monotonic()
    got = await asyncio.wait_for(source.quote(KEY.symbol), timeout=2)
    assert time.monotonic() - started < 1, "the poll waited on a connect that never returns"
    assert got is not None, "and it answers from the cache rather than blocking or raising"


@pytest.mark.asyncio
async def test_a_second_symbol_does_not_queue_behind_the_first_reconnect(tmp_path):
    """One poll asks this of every symbol at once and waits for all of them
    together. Queueing on the lock puts the whole book behind one connect."""
    source = socket_source(tmp_path)
    name = KEY.symbol.full
    source._keys[name] = KEY
    source._fields[name] = {"bid": 1.0, "ask": 2.0}
    source._touched[name] = time.time()

    async def died():
        raise RuntimeError("socket closed")

    source._reader = asyncio.create_task(died())
    await asyncio.sleep(0)

    await source._lock.acquire()  # somebody else is already reconnecting
    try:
        got = await asyncio.wait_for(source.quote(KEY.symbol), timeout=2)
        assert got is not None
        assert got.bid == 1.0
    finally:
        source._lock.release()


@pytest.mark.asyncio
async def test_a_live_reader_is_not_reconnected_for_every_poll(tmp_path):
    """The check is on the hot path - every symbol, every tick - so it has to
    be exactly the reader's state and nothing more expensive."""
    source = socket_source(tmp_path)
    name = KEY.symbol.full
    source._keys[name] = KEY
    source._fields[name] = {"bid": 1.0, "ask": 2.0}
    source._reader = asyncio.create_task(asyncio.sleep(5))

    tried = []
    source._ensure_live = lambda: tried.append(True)
    try:
        assert await source.quote(KEY.symbol) is not None
        assert not tried
    finally:
        source._reader.cancel()


@pytest.mark.asyncio
async def test_a_cached_quote_is_dated_when_it_moved_not_when_it_was_read(tmp_path):
    """**A stale price must not be able to look like a live one.** The cache
    answers polls, so dating it to the present makes a dead socket produce
    prices that every consumer - the store, liveness checks, anything deciding
    on them - reads as current."""
    source = socket_source(tmp_path)
    name = KEY.symbol.full
    source._keys[name] = KEY
    source._ready[name] = asyncio.Event()
    source._reader = asyncio.create_task(asyncio.sleep(5))

    try:
        await source._on_update(["qs", {"n": name, "v": {"bid": 1.0, "ask": 2.0}}])
        moved = source._touched[name]
        await asyncio.sleep(0.05)

        got = await source.quote(KEY.symbol)
        assert got is not None
        assert got.time == moved, "read time is not quote time"
    finally:
        source._reader.cancel()


class FakeStreaming(QuoteSource):
    name = "tradingview"
    feed_key = "tradingview"
    streaming = True

    def __init__(self, settings):
        super().__init__(settings)
        from till_infinity.prices import WriteResult

        self._pushed = WriteResult(inserted=3)

    async def quote(self, symbol):
        return Quote(time=1.0, bid=1.0, ask=2.0)

    def drain_pushed(self):
        from till_infinity.prices import WriteResult

        out, self._pushed = self._pushed, WriteResult()
        return out


@pytest.mark.asyncio
async def test_a_streaming_source_is_not_written_twice(tmp_path):
    """It already wrote on push; the snapshot must not write the same quote again."""
    settings = Settings(data_dir=tmp_path)
    sink = Recorder()
    tick = await poll_once([FakeStreaming(settings)], [FEEDS["gold"]], concurrency=4, sink=sink)
    assert sink.calls == []
    assert tick.written.inserted == 0
    assert tick.pushed.inserted == 3
    assert tick.stored == 3


def test_the_scanner_transport_stores_under_the_venue_source(tmp_path):
    """Whichever transport fetched it, a quote belongs to the same series."""
    from till_infinity.prices.quotes import TradingViewScannerQuotes

    scanner = TradingViewScannerQuotes(Settings(data_dir=tmp_path))
    assert scanner.name == "scanner"
    keys = scanner.keys([FEEDS["gold"]])
    assert keys
    assert all(key.source == "tradingview" for key in keys)
    assert not scanner.streaming


def test_deriv_is_tracked_and_fxcm_is_not():
    venues = {s.venue for feed in FEEDS.values() for s in feed.for_source("tradingview")}
    assert "DERIV" in venues  # served by the socket, though the scanner 404s
    assert "FXCM" not in venues  # delisted from TradingView entirely


@pytest.mark.asyncio
async def test_a_healthy_file_reports_no_complaints_and_rebuilds_nothing(tmp_path):
    async with SqliteStore(tmp_path / "p.db") as store:
        for i in range(50):
            await store.write_quote(KEY, Quote(1000.0 + i, 1.0, 2.0 + i * 0.01))
        got = await store.reindex()
    assert got.checked
    assert got.complaints == ()
    assert got.rebuilt == ()


@pytest.mark.asyncio
async def test_one_index_can_be_named(tmp_path):
    async with SqliteStore(tmp_path / "p.db") as store:
        await store.write_quote(KEY, Quote(1000.0, 1.0, 2.0))
        assert (await store.reindex("quotes_feed_ts")).checked == ("quotes_feed_ts",)
        with pytest.raises(ValueError, match="no index named"):
            await store.reindex("not_an_index")


@pytest.mark.asyncio
async def test_a_corrupt_index_is_reported_rather_than_raised(tmp_path):
    """The caller reached for a repair; an exception is not one.

    Corruption bad enough to defeat both rebuild routes is still the useful
    answer - it says restore rather than repair - and the rows stay readable
    throughout, which is the distinction the whole method exists to make.
    """
    import sqlite3

    path = tmp_path / "p.db"
    async with SqliteStore(path) as store:
        for i in range(400):
            await store.write_quote(KEY, Quote(1000.0 + i, 1.0, 2.0 + i * 0.01))

    conn = sqlite3.connect(path)
    root = conn.execute(
        "SELECT rootpage FROM sqlite_master WHERE name='quotes_feed_ts'"
    ).fetchone()[0]
    size = conn.execute("PRAGMA page_size").fetchone()[0]
    conn.close()
    raw = bytearray(path.read_bytes())
    at = (root - 1) * size
    raw[at + 8 : at + 60] = b"\xff" * 52
    path.write_bytes(bytes(raw))

    async with SqliteStore(path) as store:
        got = await store.reindex("quotes_feed_ts")
        assert got.complaints
        # The rows were never the problem and are still all there.
        assert len(await store.quotes(KEY)) == 400


@pytest.mark.asyncio
async def test_the_index_is_recreated_when_reindex_itself_cannot_run(tmp_path):
    """`REINDEX` walks the tree it is replacing, so a bad enough one defeats it.

    Dropping the definition and replaying `sqlite_master.sql` does not, and the
    two halves are one operation - a DROP that lands with a CREATE that does not
    leaves the table with no index, which is slower than a corrupt one and much
    harder to notice.
    """
    import sqlite3

    class NoReindex:
        def __init__(self, inner):
            self._inner = inner

        def execute(self, sql, *args, **kwargs):
            if sql.strip().upper().startswith("REINDEX"):
                raise sqlite3.DatabaseError("database disk image is malformed")
            return self._inner.execute(sql, *args, **kwargs)

        def __getattr__(self, name):
            return getattr(self._inner, name)

    async with SqliteStore(tmp_path / "p.db") as store:
        for i in range(200):
            await store.write_quote(KEY, Quote(1000.0 + i, 1.0, 2.0 + i * 0.01))
        conn = store._require()
        assert SqliteStore._rebuild(conn, "quotes_feed_ts") == "reindex"
        assert SqliteStore._rebuild(NoReindex(conn), "quotes_feed_ts") == "recreate"
        plan = str(
            conn.execute(
                "EXPLAIN QUERY PLAN SELECT ts FROM quotes WHERE feed=? ORDER BY ts DESC",
                (KEY.feed,),
            ).fetchall()
        )
        assert "quotes_feed_ts" in plan
        assert len(await store.quotes(KEY)) == 200
