"""The whole thing, running together.

Every part of this project is a service that talks over the bus, which is the
right shape for deploying them separately and an awkward one for answering
"does it work". This module starts all of them in one process against one bus,
so an end-to-end run is a single command.

    prices ──┬─▶ structures ─┬─▶ structures.signals ─┐
             │               └───────────────────────┼─▶ alerts ─▶ notifications
    news  ───┴───────────────────▶ agents ───────────┘
                                      │
                  structures, agents ─┴─▶ journal ─▶ journal.db

## What is optional, and why

**Agents are off unless asked for.** They are the only part that needs a paid
credential, and a stack that refuses to start without one would make the free
path — collect, detect levels, alert on a dead feed — hostage to the expensive
one. `AGENTS_ENABLED=1` turns them on; without a key they stay off however the
flag is set, with a warning rather than a crash.

**Notifications are off unless configured.** Same reasoning: no Telegram token
is a reason to skip delivery, not to stop collecting.

Everything else runs. If a service fails to start, the others carry on and the
run reports which one is missing — a stack that dies because one collector
cannot reach a venue would be less useful than the collector it replaced.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from . import agents as ag
from . import journal as jr
from . import news as nw
from . import notifications as nt
from . import prices as px
from . import structures as sx
from .bus import Bus
from .logging import get_logger

log = get_logger(__name__)

#: Services in start order. Consumers first, so nothing published during
#: start-up is dropped for want of a subscriber — an in-memory bus only
#: delivers to groups that already exist when publish is called.
ORDER: tuple[str, ...] = (
    "journal",
    "notifications",
    "agents",
    "structures",
    "prices",
    "news",
)


def first_cause(exc: BaseException, depth: int = 0) -> str:
    """The innermost real error, not the group that wrapped it.

    TaskGroups raise `ExceptionGroup`, whose message is "unhandled errors in a
    TaskGroup (1 sub-exception)" — which names neither the error nor where it
    came from. A supervisor that reports that has told nobody anything, so this
    walks down to the exception that actually happened.
    """
    inner = getattr(exc, "exceptions", None)
    if inner and depth < 6:
        return first_cause(inner[0], depth + 1)
    return f"{type(exc).__name__}: {exc}"


def truthy(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() not in ("", "0", "false", "no", "off")


@dataclass(slots=True)
class Plan:
    """Which services to run, and where their data lives."""

    redis_url: str | None = None
    #: Off by default: the only part needing a paid credential.
    agents: bool = False
    notifications: bool = True
    structures: bool = True
    prices: bool = True
    news: bool = True
    journal: bool = True

    symbols: tuple[str, ...] = ()
    intervals: tuple[str, ...] = ()
    #: Stop after this long. None runs until interrupted.
    duration: float | None = None
    once: bool = False

    @classmethod
    def from_env(cls) -> Plan:
        symbols = os.environ.get("SYMBOLS", "")
        intervals = os.environ.get("INTERVALS", "")
        return cls(
            redis_url=os.environ.get("TILL_REDIS_URL") or None,
            agents=truthy("AGENTS_ENABLED"),
            notifications=truthy("NOTIFICATIONS_ENABLED", "1"),
            structures=truthy("STRUCTURES_ENABLED", "1"),
            prices=truthy("PRICES_ENABLED", "1"),
            news=truthy("NEWS_ENABLED", "1"),
            journal=truthy("JOURNAL", "1"),
            symbols=tuple(s.strip() for s in symbols.split(",") if s.strip()),
            intervals=tuple(i.strip() for i in intervals.split(",") if i.strip()),
        )

    def wanted(self) -> list[str]:
        return [name for name in ORDER if getattr(self, name)]


@dataclass(slots=True)
class Status:
    """What actually started, and why anything did not."""

    running: list[str] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)
    failed: dict[str, str] = field(default_factory=dict)
    started: float = field(default_factory=time.time)

    @property
    def elapsed(self) -> float:
        return time.time() - self.started

    def __str__(self) -> str:
        parts = [f"{len(self.running)} running: {', '.join(self.running)}"]
        if self.skipped:
            parts.append(f"skipped {', '.join(sorted(self.skipped))}")
        if self.failed:
            parts.append(f"failed {', '.join(sorted(self.failed))}")
        return " · ".join(parts)


def check(plan: Plan) -> dict[str, str]:
    """Reasons a wanted service cannot run. Empty means everything can.

    Checked up front so a stack reports "no ANTHROPIC_API_KEY" at second zero
    rather than after a collector has been running for a minute.
    """
    reasons: dict[str, str] = {}
    if plan.agents:
        settings = ag.Settings.from_env()
        if not settings.ready:
            reasons["agents"] = ag.providers.missing(settings.model)
    if plan.notifications:
        settings = nt.Settings.from_env()
        if not nt.build_notifiers(None, settings):
            reasons["notifications"] = "no Telegram or Discord channel configured"
    return reasons


class Stack:
    """Every service, one bus, one process."""

    def __init__(self, plan: Plan | None = None) -> None:
        self.plan = plan or Plan.from_env()
        self.bus = Bus(redis_url=self.plan.redis_url)
        self.status = Status()
        self._stack = contextlib.AsyncExitStack()

    async def run(
        self,
        *,
        on_event: Callable[[str, str], None] | None = None,
    ) -> Status:
        """Start everything wanted and available, then wait.

        Returns once `duration` has elapsed, `once` has completed a pass, or the
        caller cancels. A service that raises takes itself down and is recorded;
        the rest keep running.
        """
        blocked = check(self.plan)
        wanted = self.plan.wanted()
        for name in wanted:
            if name in blocked:
                self.status.skipped[name] = blocked[name]
                log.warning("stack: %s skipped — %s", name, blocked[name])

        runnable = [name for name in wanted if name not in blocked]
        say = on_event or (lambda name, note: log.info("stack: %s %s", name, note))

        async with self._stack:
            book = None
            if self.plan.journal:
                book = await self._stack.enter_async_context(jr.Journal(_journal_db()))

            async with asyncio.TaskGroup() as group:
                for name in runnable:
                    started = self._start(group, name, book, say)
                    if started:
                        self.status.running.append(name)
                        say(name, "started")

                if self.plan.duration is not None:
                    await asyncio.sleep(self.plan.duration)
                    group._abort()
        return self.status

    def _start(self, group: asyncio.TaskGroup, name: str, book, say) -> bool:
        """Launch one service as a supervised task."""
        runner = getattr(self, f"_run_{name}", None)
        if runner is None:  # pragma: no cover - ORDER and methods are written together
            self.status.failed[name] = "no runner"
            return False

        async def supervised() -> None:
            try:
                await runner(book)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # One service failing is a service failing, not a stack failing.
                reason = first_cause(exc)
                self.status.failed[name] = reason
                log.error("stack: %s stopped: %s", name, reason, exc_info=True)
                say(name, f"stopped: {reason}")

        group.create_task(supervised(), name=f"stack:{name}")
        return True

    # ----------------------------------------------------------- the services

    async def _run_journal(self, book) -> None:
        if book is None:
            return
        await jr.listen(self.bus, book)

    async def _run_notifications(self, _book) -> None:
        await nt.listen(self.bus)

    async def _run_agents(self, book) -> None:
        await ag.watch(self.bus, journal=book)

    async def _run_structures(self, book) -> None:
        watcher = sx.Watcher(self.bus, journal=book)
        watcher.load()
        await watcher.run()

    async def _run_prices(self, _book) -> None:
        settings = px.Settings.from_env()
        feeds = px.resolve_symbols(self.plan.symbols or None)
        intervals = px.resolve_intervals(self.plan.intervals or None)
        store = px.open_store("sqlite", database=settings.database, data_dir=settings.data_dir)
        async with store, asyncio.TaskGroup() as group:
            group.create_task(
                px.collect(
                    settings=settings,
                    store=store,
                    feeds=feeds,
                    intervals=intervals,
                    cycles=1 if self.plan.once else None,
                    bus=self.bus,
                )
            )
            group.create_task(
                px.stream(
                    settings=settings,
                    feeds=feeds,
                    sink=store.write_quote,
                    ticks=1 if self.plan.once else None,
                    bus=self.bus,
                )
            )

    async def _run_news(self, _book) -> None:
        settings = nw.Settings.from_env()
        store = nw.open_store("sqlite", database=settings.database, data_dir=settings.data_dir)
        async with store:
            await nw.collect(
                settings=settings,
                store=store,
                cycles=1 if self.plan.once else None,
                bus=self.bus,
            )

    async def close(self) -> None:
        await self.bus.close()


def _journal_db() -> Path:
    return Path(os.environ.get("JOURNAL_DB") or jr.DEFAULT_DB)


async def run(plan: Plan | None = None, **kwargs) -> Status:
    """Start the stack, run it, and shut it down cleanly."""
    stack = Stack(plan)
    try:
        return await stack.run(**kwargs)
    finally:
        await stack.close()
