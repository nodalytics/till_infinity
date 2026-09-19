"""Bars in one end, a position out the other, over one bus.

**Every failure that has cost this desk a day was a wiring failure.** The quote
collector that died and took the feed with it; `_carry` correct and tested and
never called by the engine; signals published on traded instruments while
`passed over` sat frozen at 39,643 for two days. In each case both sides had
tests, both sides passed, and nothing asked whether they were joined up.

Unit tests cannot see this by construction: a test that drives a component
directly agrees with the component. Only a test that refuses to touch the
seam - publishing on the bus and waiting on the other side - can tell whether
anybody is listening.

What makes this awkward to write, and is therefore worth writing down: a
single venue produces *nothing at all*. `Consensus` holds a bar back until
`MIN_VENUES` have reported it, so a feed from one venue never forms a level,
never warms the volatility estimate and never publishes a call - silently, and
identically to a broken engine.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest

from till_infinity import trading as td
from till_infinity.bus import BARS, QUOTES, SIGNALS, Bus, Message
from till_infinity.structures import service as sx

#: Three, because `MIN_VENUES` is three. Two is one venue's opinion wearing a
#: median's clothes, and one is silence.
VENUES = ("ALPHA", "BETA", "GAMMA")

FEED = "gold"


def trading_settings(**over):
    made = td.Settings(symbols=(FEED,), account_equity=10_000.0, paper_equity=10_000.0)
    made.live = False
    made.strategies = ("level-scalp",)
    # The spread-against-risk gate is calibrated from production and this
    # fixture's synthetic quotes do not resemble it; every other test file
    # turns it off for the same reason.
    made.max_spread_risk_fraction = 0.0
    made.state_dir = Path(tempfile.mkdtemp(prefix="till-e2e-"))
    for key, value in over.items():
        setattr(made, key, value)
    return made


def walk() -> list[float]:
    """Up to 110 and back to 100, repeatedly.

    Price has to *revisit* a price for a level to form there and be touched;
    a random walk wanders off and produces nothing.
    """
    path: list[float] = []
    for _ in range(10):
        path += [100.0 + step * 0.5 for step in range(21)]
        path += [110.0 - step * 0.5 for step in range(21)]
    return path


def bars_and_quotes(prices: list[float]):
    """The messages `prices` would publish for this path."""
    for i, price in enumerate(prices):
        when = i * 60
        for venue in VENUES:
            yield Message(
                topic=BARS,
                payload={
                    "feed": FEED,
                    "venue": venue,
                    "source": "test",
                    "interval": "1m",
                    "ts": when,
                    "time": when,
                    "open": price,
                    "high": price + 0.2,
                    "low": price - 0.2,
                    "close": price,
                    "volume": 100,
                    "closed": True,
                },
            )
        yield Message(
            topic=QUOTES,
            payload={
                "feed": FEED,
                "venue": VENUES[0],
                "source": "test",
                "time": when,
                "bid": price - 0.01,
                "ask": price + 0.01,
                "mid": price,
                "spread_bps": 2.0,
            },
        )


async def drive(watcher: sx.Watcher, *, emit: bool = True, stop_after: int = 0) -> int:
    """Feed the path through the watcher, publishing what it finds.

    `emit` is the production publish path - `Watcher.run` calls exactly this
    with exactly these signals - so what reaches the bus here is what reaches
    it on the desk.

    `stop_after` stops once that many have been published. A subscriber that
    is slower than this loop turns `emit` into a wait, and the tests below
    only need to know that *a* call crossed the bus, not all sixty.
    """
    published = 0
    for message in bars_and_quotes(walk()):
        found = await watcher.handle(message)
        if found and emit:
            published += await watcher.emit(found)
            if stop_after and published >= stop_after:
                return published
    return published


class TestTheEngineNeedsAQuorumBeforeItSaysAnything:
    """Stated first, because everything below is silent without it."""

    @pytest.mark.asyncio
    async def test_one_venue_produces_nothing_at_all(self):
        watcher = sx.Watcher(Bus(), settings=sx.Settings())
        watcher.arm()
        for i, price in enumerate(walk()):
            when = i * 60
            await watcher.handle(
                Message(
                    topic=BARS,
                    payload={
                        "feed": FEED,
                        "venue": "ONLY",
                        "source": "test",
                        "interval": "1m",
                        "ts": when,
                        "time": when,
                        "open": price,
                        "high": price + 0.2,
                        "low": price - 0.2,
                        "close": price,
                        "volume": 100,
                        "closed": True,
                    },
                )
            )
        levels = sum(len(v) for v in watcher.engine._levels.values())
        assert levels == 0, "a lone venue should reach no quorum"
        assert not watcher.engine.vol.of(FEED, "1m").warm

    @pytest.mark.asyncio
    async def test_a_quorum_forms_levels_and_publishes_calls(self):
        watcher = sx.Watcher(Bus(), settings=sx.Settings())
        watcher.arm()
        await drive(watcher, emit=False)
        levels = sum(len(v) for v in watcher.engine._levels.values())
        assert watcher.engine.vol.of(FEED, "1m").warm, "the estimate never warmed"
        assert levels > 0, "no level formed from a price that was revisited ten times"
        assert watcher.engine.calls > 0, "levels formed but nothing was ever called"


class TestASignalCrossesTheBus:
    """The seam. Nothing here touches both sides of it directly."""

    @pytest.mark.asyncio
    async def test_a_published_call_reaches_a_subscriber(self):
        bus = Bus()
        seen: list[dict] = []

        stream = bus.subscribe(SIGNALS, group="listener")

        async def read() -> None:
            # Not a comprehension: that one drains the whole stream before it
            # assigns anything, so `seen` stays empty until the bus closes -
            # which is exactly what this test is waiting on. PERF401 is wrong
            # for a subscription that is meant to be observed while it runs.
            async for message in stream:
                seen.append(message.payload)  # noqa: PERF401

        reader = asyncio.create_task(read())
        await asyncio.sleep(0)

        watcher = sx.Watcher(bus, settings=sx.Settings())
        watcher.arm()
        published = await asyncio.wait_for(drive(watcher, stop_after=1), timeout=60)
        for _ in range(10):
            await asyncio.sleep(0)

        reader.cancel()
        await asyncio.gather(reader, return_exceptions=True)

        assert published > 0, "the watcher published nothing to publish"
        assert seen, "signals were published and nobody received them"

    @pytest.mark.asyncio
    async def test_the_trader_is_asked_about_what_structures_publishes(self):
        """**The test today's two-day outage would have failed.**

        Structures published level calls on instruments the desk trades and
        `passed over` never moved, because both silent returns in `on_signal`
        left no trace. What has to hold is not that a trade is taken - a
        strategy may honestly refuse - but that the trader *considered* it.
        """
        bus = Bus()
        settings = trading_settings()
        trading = asyncio.create_task(td.listen(bus, settings=settings, limit=1))

        # **Wait for the subscription, do not assume it.** `listen` attaches a
        # broker before it subscribes, so a signal published in the meantime
        # reaches nobody and is gone - `Bus.publish` only serves groups that
        # already exist. The first run of this test failed exactly that way,
        # with "published to structures.signals with nobody subscribed" in the
        # log, which is the same silent-drop shape the desk keeps producing.
        for _ in range(2_000):
            if (SIGNALS, "trading") in bus._channels:
                break
            await asyncio.sleep(0.01)
        else:  # pragma: no cover - only on a real regression
            trading.cancel()
            pytest.fail("trading never subscribed to structures.signals")

        watcher = sx.Watcher(bus, settings=sx.Settings())
        watcher.arm()
        published = await asyncio.wait_for(drive(watcher, stop_after=1), timeout=60)
        assert published > 0, "nothing was published, so nothing could be delivered"

        trader = await asyncio.wait_for(trading, timeout=60)
        looked = trader.taken + trader.refused + sum(trader.passed_over.values())
        assert looked > 0, (
            "structures published a level call on a traded instrument and the "
            "trader recorded nothing at all - the state the desk was in for two "
            f"days (counters: taken={trader.taken} refused={trader.refused} "
            f"passed_over={dict(trader.passed_over)})"
        )


class TestTradingListensBeforeItConnects:
    """A level call published while the broker is still attaching must land.

    `_attach` connects to the terminal and scans its symbols - about two
    minutes on the instance - and `Bus.publish` only reaches groups that
    already exist. Trading used to subscribe after that, so anything published
    in the window was delivered to nobody. The first run of the test above
    lost its call exactly that way.
    """

    @pytest.mark.asyncio
    async def test_signals_are_subscribed_while_the_broker_is_still_attaching(self, monkeypatch):
        from till_infinity.trading import service as svc

        attaching = asyncio.Event()
        release = asyncio.Event()

        async def slow_attach(trader):
            attaching.set()
            await release.wait()

        monkeypatch.setattr(svc, "_attach", slow_attach)
        bus = Bus()
        task = asyncio.create_task(td.listen(bus, settings=trading_settings(), limit=1))
        await asyncio.wait_for(attaching.wait(), timeout=10)

        try:
            assert (SIGNALS, "trading") in bus._channels, (
                "trading is still connecting to its broker and is not yet listening "
                "for signals, so a call published now is delivered to nobody"
            )
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    @pytest.mark.asyncio
    async def test_quotes_are_not_subscribed_early(self, monkeypatch):
        """Deliberately: they would queue a thousand stale quotes per restart."""
        from till_infinity.trading import service as svc

        attaching = asyncio.Event()
        release = asyncio.Event()

        async def slow_attach(trader):
            attaching.set()
            await release.wait()

        monkeypatch.setattr(svc, "_attach", slow_attach)
        bus = Bus()
        task = asyncio.create_task(td.listen(bus, settings=trading_settings(), limit=1))
        await asyncio.wait_for(attaching.wait(), timeout=10)
        try:
            assert (QUOTES, "trading") not in bus._channels
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
