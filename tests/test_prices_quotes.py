import asyncio

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
