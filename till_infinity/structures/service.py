"""Watching the bus, learning continuously, saying something when it matters.

This is the always-on layer. It consumes `prices.quotes` and `prices.bars`,
updates its models on every message, and publishes what it finds:

    prices ──▶ structures ──┬──▶ structures.signals ──▶ agents
                            └──▶ alerts (unambiguous only)

Two outputs because two kinds of finding. Most signals are *evidence*: a venue
looks odd, and whether that matters depends on the calendar, which this layer
cannot see. Those go to `structures.signals` for an agent to weigh against the
fundamentals.

A few are unambiguous. A venue that has not moved in five minutes while five
others have does not need a language model to interpret it and does not need a
release to explain it, so it goes straight to `alerts`. Making everything wait
for an agent would put an LLM in the path of the one message that most needs to
arrive during an outage.

Nothing here needs an API key.
"""

from __future__ import annotations

import asyncio
import contextlib
import statistics
import time
from collections import OrderedDict
from collections.abc import Callable, Sequence

from ..bus import ALERTS, BARS, QUOTES, SIGNALS, Bus, Message
from ..journal import Journal, decide
from ..logging import get_logger
from . import store
from .anomaly import Detector
from .config import INTERVALS, Settings
from .drift import Drift
from .models import Shape, Signal

log = get_logger(__name__)

TOPICS: tuple[str, ...] = (QUOTES, BARS)

#: Shapes that never need a model or a calendar to be worth sending.
UNAMBIGUOUS: frozenset[Shape] = frozenset({Shape.STALE})

#: Venues needed before a median close means anything, matching the quote side.
MIN_VENUES = 3


class BarConsensus:
    """Median close per (instrument, interval), for the drift detector.

    Bars arrive one venue at a time. Feeding drift a single venue's series
    would mix market moves with that venue's own quirks, which is the thing
    having six venues exists to cancel.
    """

    def __init__(self) -> None:
        self._closes: dict[tuple[str, str], dict[str, tuple[int, float]]] = {}

    def observe(self, payload: dict) -> tuple[str, float] | None:
        feed = str(payload.get("feed") or "")
        venue = str(payload.get("venue") or "")
        interval = str(payload.get("interval") or "")
        close = payload.get("close")
        when = payload.get("time")
        if interval not in INTERVALS or not feed or not venue:
            return None
        if not isinstance(close, int | float) or not close:
            return None

        group = self._closes.setdefault((feed, interval), {})
        group[venue] = (int(when or 0), float(close))
        # Only the venues that reported this same bar, so the median is a
        # snapshot rather than a blend of different minutes.
        latest = max(ts for ts, _ in group.values())
        aligned = [price for ts, price in group.values() if ts == latest]
        if len(aligned) < MIN_VENUES:
            return None
        return feed, statistics.median(aligned)


class Watcher:
    """The online layer as a running service."""

    def __init__(
        self,
        bus: Bus,
        *,
        settings: Settings | None = None,
        group: str = "structures",
        journal: Journal | None = None,
        memory: int = 500,
    ) -> None:
        self.bus = bus
        self.settings = settings or Settings.from_env()
        self.group = group
        self.journal = journal
        self.memory = memory
        self.detector = Detector(
            warmup=self.settings.warmup,
            quantile=self.settings.quantile,
            sigma=self.settings.sigma,
        )
        self.drift = Drift()
        self.bars = BarConsensus()
        self._sent: OrderedDict[tuple[str, str, str], float] = OrderedDict()
        self._saved = 0.0
        self.published = 0
        self.alerted = 0

    # ---------------------------------------------------------- persistence

    def load(self) -> bool:
        """Restore what was learned last run. False means starting cold."""
        state = store.load(self.settings.state_dir)
        if not state:
            return False
        self.detector = state.get("detector", self.detector)
        self.drift = state.get("drift", self.drift)
        log.info("structures: restored models (%s)", self.detector.seen())
        return True

    def save(self) -> None:
        try:
            store.save({"detector": self.detector, "drift": self.drift}, self.settings.state_dir)
        except Exception as exc:  # losing a save must not stop the watch
            log.warning("structures: could not save state: %s", exc)
        self._saved = time.monotonic()

    # -------------------------------------------------------------- sending

    def fresh(self, signal: Signal) -> bool:
        """True unless this exact finding was sent inside the cooldown."""
        now = time.time()
        last = self._sent.get(signal.key)
        if last is not None and now - last < self.settings.cooldown:
            return False
        self._sent[signal.key] = now
        self._sent.move_to_end(signal.key)
        while len(self._sent) > self.memory:
            self._sent.popitem(last=False)
        return True

    def direct(self, signal: Signal) -> bool:
        """Whether this goes to a human without an agent in between.

        Deliberately *not* keyed on score. Score measures statistical rarity,
        and rarity is not unambiguity — an unusually wide spread is rare and is
        exactly the case that needs the calendar before anyone is woken. What
        qualifies is a reading that no fundamental could explain: a feed that
        has stopped, or a price so far from every other venue that it is a
        broken quote rather than a market opinion.
        """
        if not self.settings.alert_direct:
            return False
        if signal.shape in UNAMBIGUOUS:
            return True
        return (
            signal.shape is Shape.DISLOCATION
            and signal.features.get("abs_dev_bps", 0.0) >= self.settings.direct_dev_bps
        )

    async def emit(self, signals: Sequence[Signal]) -> int:
        """Publish signals, alerting directly on the unambiguous ones."""
        sent = 0
        for signal in signals:
            if not self.fresh(signal):
                continue
            await self.bus.publish(SIGNALS, signal.to_dict(), source="structures")
            self.published += 1
            sent += 1

            if self.direct(signal):
                await self.bus.publish(
                    ALERTS,
                    {
                        "title": signal.title,
                        "body": signal.detail,
                        "level": "warning",
                        "fields": {
                            "instrument": signal.feed,
                            "venue": signal.venue,
                            "shape": str(signal.shape),
                            "score": f"{signal.score:.3f}",
                        },
                        "source": "structures",
                    },
                    source="structures",
                )
                self.alerted += 1

            # Journalled with the features it was found from, because those are
            # the inputs a later model would need and they cannot be recovered
            # from the stores — the consensus at that instant is not written
            # down anywhere else.
            await decide(
                self.journal,
                signal.title,
                rationale=signal.detail,
                actor="structures",
                context={"shape": str(signal.shape), "score": signal.score, **signal.features},
                tags=(signal.feed, signal.venue, str(signal.shape)),
                confidence=min(1.0, signal.score),
            )
        return sent

    # -------------------------------------------------------------- running

    async def handle(self, message: Message) -> list[Signal]:
        """One bus message in, zero or more findings out."""
        if message.topic == QUOTES:
            return self.detector.observe(message.payload)
        if message.topic == BARS:
            seen = self.bars.observe(message.payload)
            if seen is None:
                return []
            feed, mid = seen
            found = self.drift.observe(feed, mid, message.time)
            return [found] if found else []
        return []

    async def run(
        self,
        *,
        messages: int | None = None,
        on_signal: Callable[[Signal], None] | None = None,
    ) -> int:
        """Consume until the bus closes, or for `messages` messages."""
        seen = 0
        queue: asyncio.Queue[Message] = asyncio.Queue(maxsize=10_000)

        async def read(topic: str) -> None:
            with contextlib.suppress(asyncio.CancelledError):
                async for message in self.bus.subscribe(topic, group=self.group):
                    with contextlib.suppress(asyncio.QueueFull):
                        queue.put_nowait(message)

        async with asyncio.TaskGroup() as tasks:
            readers = [tasks.create_task(read(topic)) for topic in TOPICS]
            try:
                while messages is None or seen < messages:
                    message = await queue.get()
                    seen += 1
                    signals = await self.handle(message)
                    if signals:
                        await self.emit(signals)
                        for signal in signals:
                            log.info("structures: %s", signal)
                            if on_signal is not None:
                                on_signal(signal)
                    if time.monotonic() - self._saved >= self.settings.save_seconds:
                        self.save()
            finally:
                self.save()
                for reader in readers:
                    reader.cancel()
        return seen


async def watch(
    bus: Bus,
    *,
    settings: Settings | None = None,
    group: str = "structures",
    journal: Journal | None = None,
    messages: int | None = None,
    on_signal: Callable[[Signal], None] | None = None,
) -> int:
    """Run the online layer over the bus. The everyday entry point."""
    watcher = Watcher(bus, settings=settings, group=group, journal=journal)
    watcher.load()
    return await watcher.run(messages=messages, on_signal=on_signal)
