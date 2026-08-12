import pytest

from till_infinity.prices import (
    INTERVALS,
    Bar,
    Settings,
    Source,
    SqliteStore,
    TransientError,
    resolve_feeds,
    resolve_intervals,
    sweep,
)
from till_infinity.prices.service import build_sources


class FakeSource(Source):
    """Returns two bars per interval and can be told to fail the first n calls."""

    name = "tradingview"  # borrow a real name so its feed symbols resolve

    def __init__(self, settings, failures=0):
        super().__init__(settings)
        self.failures = failures
        self.calls = 0

    async def fetch(self, job, bars, sink):
        from till_infinity.prices.models import WriteResult

        self.calls += 1
        if self.calls <= self.failures:
            raise TransientError("boom")
        total = WriteResult()
        for interval in job.intervals:
            candles = [Bar(60, 1, 2, 0, 1, 5), Bar(60 + interval.seconds, 1, 2, 0, 1, 5)]
            total += await sink(job.key(interval), self.keep(candles, interval))
        return total


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path)


@pytest.mark.asyncio
async def test_sweep_writes_every_symbol_and_interval(settings, monkeypatch):
    monkeypatch.setitem(
        __import__("till_infinity.prices.service", fromlist=["SOURCES"]).SOURCES,
        "tradingview",
        FakeSource,
    )
    feeds = resolve_feeds(("gold",))
    intervals = resolve_intervals(("1h", "1d"))
    async with SqliteStore(settings.database) as store:
        summary = await sweep(
            settings=settings,
            store=store,
            feeds=feeds,
            intervals=intervals,
            bars=10,
            sources=("tradingview",),
        )
        series = await store.series()

    symbols = len(feeds[0].for_source("tradingview"))
    assert summary.jobs == symbols
    assert summary.failed == 0
    assert len(series) == symbols * len(intervals)
    assert summary.total.inserted == symbols * len(intervals) * 2


@pytest.mark.asyncio
async def test_a_failing_symbol_does_not_sink_the_sweep(settings, monkeypatch):
    service = __import__("till_infinity.prices.service", fromlist=["SOURCES"])
    settings.retries = 1

    def always_fails(s):
        return FakeSource(s, failures=99)

    monkeypatch.setitem(service.SOURCES, "tradingview", always_fails)
    async with SqliteStore(settings.database) as store:
        summary = await sweep(
            settings=settings,
            store=store,
            feeds=resolve_feeds(("gold",)),
            intervals=resolve_intervals(("1h",)),
            bars=10,
            sources=("tradingview",),
        )
    assert summary.failed == summary.jobs > 0
    assert summary.total.inserted == 0


@pytest.mark.asyncio
async def test_transient_failures_are_retried(settings, monkeypatch):
    service = __import__("till_infinity.prices.service", fromlist=["SOURCES"])
    settings.retries = 3
    made: list[FakeSource] = []

    def flaky(s):
        source = FakeSource(s, failures=1)
        made.append(source)
        return source

    monkeypatch.setitem(service.SOURCES, "tradingview", flaky)
    async with SqliteStore(settings.database) as store:
        summary = await sweep(
            settings=settings,
            store=store,
            feeds=resolve_feeds(("btc",)),
            intervals=resolve_intervals(("1d",)),
            bars=5,
            sources=("tradingview",),
        )
    assert summary.failed == 0
    assert made[0].calls > 1  # the first attempt failed and was retried


def test_build_sources_rejects_an_unknown_provider(settings):
    with pytest.raises(ValueError, match="unknown source"):
        build_sources(("bloomberg",), settings)


def test_resolvers_reject_unknown_names():
    with pytest.raises(ValueError, match="unknown feed"):
        resolve_feeds(("platinum",))
    with pytest.raises(ValueError, match="unknown interval"):
        resolve_intervals(("3m",))
    assert set(resolve_intervals(None)) == set(INTERVALS.values())
