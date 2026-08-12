import time

import pytest

from till_infinity.news import (
    HIGH,
    LOW,
    Article,
    Batch,
    Event,
    JsonlStore,
    Settings,
    SqliteStore,
    build_sources,
    open_store,
    poll_once,
)
from till_infinity.news.source import Source, TransientError


def article(ident: str, source: str = "forexlive", **kw) -> Article:
    return Article(source=source, id=ident, title=f"headline {ident}", **kw)


def event(ident: str, **kw) -> Event:
    return Event(source="forexfactory", id=ident, title="CPI m/m", country="USD", **kw)


@pytest.mark.asyncio
async def test_a_headline_is_stored_once(tmp_path):
    async with SqliteStore(tmp_path / "n.db") as store:
        assert (await store.write_articles([article("a"), article("b")])).inserted == 2
        # The same feed re-polled five minutes later carries the same stories.
        assert (await store.write_articles([article("b"), article("c")])).inserted == 1
        assert len(await store.latest_articles()) == 3


@pytest.mark.asyncio
async def test_the_same_id_from_two_publishers_is_two_rows(tmp_path):
    async with SqliteStore(tmp_path / "n.db") as store:
        result = await store.write_articles(
            [article("1", source="forexlive"), article("1", source="fxstreet")]
        )
    assert result.inserted == 2


@pytest.mark.asyncio
async def test_an_event_is_rewritten_when_the_print_lands(tmp_path):
    """The whole reason the calendar is re-polled: actual arrives late."""
    async with SqliteStore(tmp_path / "n.db") as store:
        scheduled = event("cpi", time=2_000_000_000.0, forecast="0.2%", importance=HIGH)
        assert (await store.write_events([scheduled])).inserted == 1

        # Polled again before release: nothing changed, so nothing is written.
        again = await store.write_events([scheduled])
        assert (again.inserted, again.updated) == (0, 0)

        released = event(
            "cpi", time=2_000_000_000.0, forecast="0.2%", actual="0.3%", importance=HIGH
        )
        result = await store.write_events([released])
        assert (result.inserted, result.updated) == (0, 1)

        (stored,) = await store.upcoming()
        assert stored.actual == "0.3%"
        assert stored.released


@pytest.mark.asyncio
async def test_upcoming_filters_by_time_and_importance(tmp_path):
    now = time.time()
    async with SqliteStore(tmp_path / "n.db") as store:
        await store.write_events(
            [
                event("past", time=now - 3600, importance=HIGH),
                event("soon-low", time=now + 3600, importance=LOW),
                event("soon-high", time=now + 7200, importance=HIGH),
            ]
        )
        assert [e.id for e in await store.upcoming()] == ["soon-low", "soon-high"]
        assert [e.id for e in await store.upcoming(min_importance=HIGH)] == ["soon-high"]


@pytest.mark.asyncio
async def test_latest_articles_are_newest_first(tmp_path):
    async with SqliteStore(tmp_path / "n.db") as store:
        await store.write_articles(
            [article("old", published=1000.0), article("new", published=2000.0)]
        )
        assert [a.id for a in await store.latest_articles()] == ["new", "old"]
        assert [a.id for a in await store.latest_articles(source="nobody")] == []


@pytest.mark.asyncio
async def test_symbols_survive_the_round_trip(tmp_path):
    async with SqliteStore(tmp_path / "n.db") as store:
        await store.write_articles(
            [article("s", source="tradingview", symbols=("OANDA:XAUUSD", "TVC:GOLD"))]
        )
        (stored,) = await store.latest_articles()
    assert stored.symbols == ("OANDA:XAUUSD", "TVC:GOLD")


@pytest.mark.asyncio
async def test_feeds_summary_counts_both_kinds(tmp_path):
    async with SqliteStore(tmp_path / "n.db") as store:
        await store.write_articles([article("a", published=500.0)])
        await store.write_events([event("e", time=900.0)])
        rows = {(f.kind, f.source): f for f in await store.feeds()}
    assert rows[("news", "forexlive")].rows == 1
    assert rows[("calendar", "forexfactory")].last_time == 900.0


@pytest.mark.asyncio
async def test_jsonl_writes_one_file_per_source(tmp_path):
    async with JsonlStore(tmp_path) as store:
        await store.write_articles([article("a"), article("b", source="fxstreet")])
        await store.write_events([event("e")])
        # Re-polling the same headline appends nothing.
        assert (await store.write_articles([article("a")])).inserted == 0
    assert (tmp_path / "news" / "forexlive.jsonl").exists()
    assert (tmp_path / "news" / "fxstreet.jsonl").exists()
    assert (tmp_path / "calendar" / "forexfactory.jsonl").exists()
    assert len((tmp_path / "news" / "forexlive.jsonl").read_bytes().splitlines()) == 1


@pytest.mark.asyncio
async def test_jsonl_appends_a_second_copy_when_the_actual_lands(tmp_path):
    """Append-only cannot rewrite, so a release is a new line, not an edit."""
    async with JsonlStore(tmp_path) as store:
        await store.write_events([event("cpi", forecast="0.2%")])
        await store.write_events([event("cpi", forecast="0.2%", actual="0.3%")])
    lines = (tmp_path / "calendar" / "forexfactory.jsonl").read_bytes().splitlines()
    assert len(lines) == 2


class FakeSource(Source):
    name = "rss"

    def __init__(self, settings, batch=None, fail=False):
        super().__init__(settings)
        self.batch = batch or Batch()
        self.fail = fail
        self.polls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def poll(self):
        self.polls += 1
        if self.fail:
            raise TransientError("boom")
        return self.batch


@pytest.mark.asyncio
async def test_poll_once_persists_every_source(tmp_path):
    settings = Settings(data_dir=tmp_path)
    sources = [
        FakeSource(settings, Batch(articles=[article("a")])),
        FakeSource(settings, Batch(events=[event("e")])),
    ]
    async with SqliteStore(tmp_path / "n.db") as store:
        summary = await poll_once(settings=settings, store=store, sources=sources)
    assert summary.articles.inserted == 1
    assert summary.events.inserted == 1
    assert summary.failed == 0


@pytest.mark.asyncio
async def test_a_failing_source_is_retried_then_counted(tmp_path):
    settings = Settings(data_dir=tmp_path, retries=2)
    bad = FakeSource(settings, fail=True)
    good = FakeSource(settings, Batch(articles=[article("a")]))
    async with SqliteStore(tmp_path / "n.db") as store:
        summary = await poll_once(settings=settings, store=store, sources=[bad, good])
    assert bad.polls == 2  # retried
    assert summary.failed == 1
    assert summary.articles.inserted == 1  # the healthy source still landed


def test_build_sources_rejects_an_unknown_name(tmp_path):
    settings = Settings(data_dir=tmp_path)
    assert {s.name for s in build_sources(None, settings)} == {
        "rss",
        "forexfactory",
        "tradingview",
        "headlines",
    }
    with pytest.raises(ValueError, match="unknown source"):
        build_sources(("bloomberg",), settings)


def test_open_store_rejects_an_unknown_kind(tmp_path):
    assert open_store("both", database=tmp_path / "n.db", data_dir=tmp_path).name == "multi"
    with pytest.raises(ValueError, match="unknown store"):
        open_store("parquet", database=tmp_path / "n.db", data_dir=tmp_path)


def test_calendars_are_polled_on_the_slow_clock(tmp_path):
    settings = Settings(data_dir=tmp_path)
    slow = {s.name for s in build_sources(None, settings) if s.slow}
    assert slow == {"forexfactory", "tradingview"}
