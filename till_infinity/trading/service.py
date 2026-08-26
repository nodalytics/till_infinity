"""The trader: signals in, orders out, outcomes written down.

    structures ──▶ structures.signals ──▶ trading ──┬──▶ broker (mt5 | bridge | paper)
    prices     ──▶ prices.quotes     ──┘            ├──▶ alerts
                                                    └──▶ journal

This is the only part of the project that can lose money, so it is written to
fail closed. Nothing here starts without a terminal it has checked, an account
it has read, and a symbol map it has resolved; a service that cannot do those
does not trade, rather than trading on assumptions about them.

**Paper unless armed.** `TRADING_LIVE=1` is the only thing that reaches a real
account, and the mode is logged at start-up and again on every fill.

**Quotes are consumed as well as signals.** Two reasons. The paper book holds
its own stops and has to see the market to know when one is hit; and the live
path prices its entry off the broker's own quote rather than the consensus,
because the consensus is six venues' opinion and the fill is one broker's.

**Positions are reconciled, not assumed.** A stop hit server-side leaves no
message on any bus — the position is simply gone next time it is asked for. So
the open set is compared on every heartbeat and a ticket that has vanished is
recorded as closed at its last known price. That is a slightly stale exit for
a real broker and an exact one on paper, and it is honest about which: the
journal entry says where the number came from.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import dataclass, field
from typing import Any

from ..bus import ALERTS, EVENTS, QUOTES, RESOLUTIONS, SIGNALS, Bus, Message
from ..journal import Journal, decide, observe, outcome
from ..logging import get_logger
from . import manage, plans, strategy
from . import symbols as sym
from .broker import Broker, BrokerError, build
from .config import Settings
from .context import Context
from .models import Intent, Order, Position, Refusal, Side, SymbolSpec, Tick
from .paper import PaperBroker
from .risk import Guard

log = get_logger(__name__)

#: Everything the trader listens to, and why each one is needed.
#:
#: `signals` is the trade. `quotes` price the entry on the paper book and feed
#: the venue consensus our own broker is judged against. `events` is the
#: economic calendar, for standing aside around a release. `resolutions` is
#: ground truth — what the levels we traded actually did — which is consumed
#: for the record rather than for a decision, and is the seam anything that
#: learns from outcomes will attach to.
TOPICS: tuple[str, ...] = (SIGNALS, QUOTES, EVENTS, RESOLUTIONS)


@dataclass(slots=True)
class Live:
    """One position we opened, and the journal entry that predicted it."""

    position: Position
    intent: Intent
    ref: str = ""
    seen: float = field(default_factory=time.time)


class Trader:
    """Watches the bus, trades what it likes, records everything."""

    def __init__(
        self,
        bus: Bus,
        *,
        settings: Settings | None = None,
        journal: Journal | None = None,
        broker: Broker | None = None,
    ) -> None:
        self.bus = bus
        self.settings = settings or Settings.from_env()
        self.journal = journal
        self.plan = plans.apply(self.settings)
        self.broker = broker or build(self.settings)
        #: Where orders go. **Not** the same object as `self.broker` unless
        #: armed: see `execution`.
        self.paper: PaperBroker | None = None
        self.strategies = strategy.build(self.settings.strategies, self.settings)
        self.context = Context(
            before=self.settings.news_before,
            after=self.settings.news_after,
            max_dislocation_bps=self.settings.max_dislocation_bps,
            max_spread_ratio=self.settings.max_spread_ratio,
            drift_pause=self.settings.drift_pause,
        )
        self.guard = Guard(self.settings, context=self.context)
        self.specs: dict[str, SymbolSpec] = {}
        self.open: dict[int, Live] = {}
        self.equity = 0.0
        self.taken = 0
        self.refused = 0
        self._symbol_of: dict[str, str] = {}
        self._feed_of: dict[str, str] = {}
        #: The order just sent, waiting to be matched to the position it
        #: became. Held for exactly one reconcile — see `_reconcile`.
        self._pending: tuple[int, Intent, str] | None = None
        #: Best price each open trade has seen, for the trailing stop. Tracked
        #: from the quote stream rather than read from the broker, because
        #: `price_current` is a snapshot and a trail anchored to snapshots
        #: follows whatever the last poll happened to catch.
        self._best: dict[int, float] = {}
        #: The volatility unit last published per instrument, so a trail can be
        #: measured in the same units the stop was placed in.
        self._vol_bps: dict[str, float] = {}
        self.resolutions = 0

    @property
    def execution(self) -> Broker:
        """The venue orders are sent to.

        The real terminal only when `TRADING_LIVE` is set; the paper book
        otherwise. Market data always comes from `self.broker`, so an unarmed
        run still resolves real symbols, reads the real account and prices
        against the real bid/ask — it simply cannot place anything.

        This exists because the flag used not to do anything. `take` called
        `self.broker.send` unconditionally and `TRADING_LIVE` changed only a log
        line, so a run in "paper" mode against a live bridge placed real orders
        on the account. Caught by doing exactly that: a paper run opened 0.03
        BTCUSD on the demo, and the next run refused to trade because the
        instrument it had never really traded was already open.

        A safety switch that is checked in one place and ignored in another is
        worse than no switch, because it is believed.
        """
        return self.paper or self.broker

    # ------------------------------------------------------------- lifecycle

    async def start(self) -> None:
        """Attach, resolve what can be traded, and open the day."""
        account = await self.broker.connect()
        self.equity = account.equity or account.balance
        log.info(
            "trading: %s via %s — %s",
            self.settings.mode.upper(),
            self.broker.name,
            account,
        )
        if not self.settings.live:
            # One paper book, not two. When there is no terminal at all
            # `build` has already returned a PaperBroker, and making a second
            # one here would split the state: bus quotes would drive the stops
            # on one book while the positions lived on the other, so nothing
            # would ever resolve.
            if isinstance(self.broker, PaperBroker):
                self.paper = self.broker
            else:
                self.paper = PaperBroker(self.settings)
                await self.paper.connect()
            log.info(
                "trading: TRADING_LIVE is not set — orders go to the paper book, "
                "priced against %s's quotes",
                self.broker.name,
            )

        resolution = await sym.resolve(self.broker, self.settings.symbols, self.settings)
        self.specs = dict(resolution.found)
        self._symbol_of = resolution.symbols
        self._feed_of = {symbol: feed for feed, symbol in self._symbol_of.items()}
        if not self.specs:
            raise BrokerError(
                f"none of {', '.join(self.settings.symbols)} can be traded on this account"
            )

        self._check_gates()
        self.guard.roll(self.equity)
        log.info(
            "trading: %s on %s",
            " + ".join(s.name for s in self.strategies),
            ", ".join(sorted(self.specs)),
        )

    def _check_gates(self) -> None:
        """Warn about a gate that cannot fire.

        `structures` will not publish a call below `reactions.MIN_EDGE`, so an
        edge floor at or under it is configuration that looks like a limit and
        is not one. This module shipped with exactly that — 0.08 against an
        upstream 0.10 — and nothing would have said so.
        """
        from ..structures.reactions import MIN_EDGE

        if self.settings.min_edge <= MIN_EDGE:
            log.warning(
                "trading: min_edge %.3f is at or below the %.3f structures already "
                "requires, so it can never refuse anything",
                self.settings.min_edge,
                MIN_EDGE,
            )

    async def close(self) -> None:
        await self.broker.close()

    # ---------------------------------------------------------------- inputs

    async def handle(self, message: Message) -> Intent | Refusal | None:
        """One bus message in. Returns what it did, for the tests and the log."""
        if message.topic == QUOTES:
            self._quote(message.payload)
            return None
        if message.topic == EVENTS:
            self.context.observe_event(message.payload)
            return None
        if message.topic == RESOLUTIONS:
            self._resolution(message.payload)
            return None
        if message.topic == SIGNALS:
            return await self.on_signal(message.payload)
        return None

    def _resolution(self, payload: dict[str, Any]) -> None:
        """Note what a level actually did.

        Counted and logged, not acted on. This is the ground truth the bus
        gained so that something *can* act on it — an accuracy-targeting gate,
        a back-check strategy, a Kelly fraction — and none of those exist yet.
        Consuming it now means the topic has a subscriber from the day it
        shipped, so the first thing built on it is not also debugging whether
        the messages arrive.
        """
        self.resolutions += 1
        feed = str(payload.get("feed") or "")
        if feed in self.specs:
            log.debug(
                "trading: %s %s at %s after %ss",
                feed,
                payload.get("outcome"),
                payload.get("level"),
                payload.get("seconds"),
            )

    def _quote(self, payload: dict[str, Any]) -> None:
        """Feed the consensus, the paper book, and the trailing high-water mark.

        Every venue's quote goes to the consensus — that is the whole point of
        having six of them — but only our own broker's fills anything else.
        """
        self.context.observe_quote(payload)
        feed = str(payload.get("feed") or "")
        symbol = self._symbol_of.get(feed)
        bid, ask = payload.get("bid"), payload.get("ask")
        if not symbol or not isinstance(bid, int | float) or not isinstance(ask, int | float):
            return
        if not bid or not ask:
            return
        when = message_time(payload)
        tick = Tick(symbol=symbol, bid=float(bid), ask=float(ask), time=when)
        # The paper book holds its own stops, so it has to see the market. When
        # the execution venue *is* the broker they are the same object and this
        # runs once.
        for venue in {id(self.broker): self.broker, id(self.paper): self.paper}.values():
            observed = getattr(venue, "observe", None)
            if observed is not None:
                observed(tick)
        self._mark_best(symbol, float(bid), float(ask))

    async def on_signal(self, payload: dict[str, Any]) -> Intent | Refusal | None:
        """Consider one signal against every strategy. The first taker wins.

        First rather than best: two strategies wanting the same instrument is
        one idea found twice, and the per-instrument limit would refuse the
        second anyway. Ordering is the order they were configured in, which
        makes it something the operator chose rather than an accident of a
        dictionary.
        """
        self.context.observe_signal(payload)
        vol_bps = _vol_of(payload)
        if vol_bps > 0:
            self._vol_bps[str(payload.get("feed") or "")] = vol_bps
        for engine in self.strategies:
            engine.observe(payload)

        feed = str(payload.get("feed") or "")
        spec = self.specs.get(feed)
        if spec is None:
            return None  # not traded here; not worth a refusal record

        tick = await self._tick(spec.symbol)
        if tick is None:
            return Refusal("quote", f"no quote for {spec.symbol}", feed)

        positions = await self._positions()
        for engine in self.strategies:
            if not engine.wants(payload):
                continue
            verdict = engine.consider(payload, spec=spec, tick=tick, equity=self.equity)
            if isinstance(verdict, Refusal):
                self.refused += 1
                # Deliberately not journalled. A strategy refusing on
                # probability or interval is the normal case — hundreds a day —
                # and writing all of it down would bury the refusals that
                # matter under the ones that are simply the filter working.
                log.debug("trading: %s declined %s: %s", engine.name, feed, verdict.detail)
                continue

            stopped = self.guard.allows(
                verdict,
                positions=positions,
                tick=tick,
                risk_of={t: live.intent.risk_money for t, live in self.open.items()},
                feed_of=self._feed_of,
            )
            if stopped is not None:
                self.refused += 1
                # These *are* journalled: the strategy wanted this trade and
                # the account said no. That is the half of the record that says
                # what the limits actually cost.
                await self._record_refusal(verdict, stopped, engine.name)
                await self._announce_decline(verdict, stopped)
                return stopped

            return await self.take(verdict, engine.name)
        return None

    # --------------------------------------------------------------- trading

    async def take(self, intent: Intent, by: str = "") -> Intent | Refusal:
        """Send an order, or say why it was not sent."""
        ref = await self._record_intent(intent, by)

        if not self.settings.live:
            log.info("trading: [paper] %s — %s", intent.title, intent.reason)

        order = Order(
            symbol=intent.symbol,
            side=intent.side,
            volume=intent.volume,
            stop=intent.stop,
            target=intent.target,
            comment=f"till {by or 'scalp'}"[:31],
            magic=self.settings.magic,
            deviation=self.settings.deviation,
        )
        try:
            result = await self.execution.send(order)
        except BrokerError as exc:
            log.warning("trading: %s rejected: %s", intent.title, exc)
            return Refusal("rejected", str(exc), intent.feed)

        if not result.ok:
            log.warning("trading: %s not filled: %s", intent.title, result)
            return Refusal("rejected", str(result), intent.feed)

        self.taken += 1
        log.info("trading: %s %s — %s", self.settings.mode, result, intent.reason)
        await self._announce_fill(intent, result.price, result.ticket)
        # Tracked from the broker's own position list rather than from the
        # result, because the ticket a fill reports is the order's and the one
        # that has to be closed is the position's. Reconciling picks it up.
        await self._reconcile(ref_for=(result.ticket, intent, ref))
        return intent

    async def sweep(self) -> None:
        """The heartbeat: roll the day, reconcile, and time out stale scalps."""
        if not await self.broker.healthy():
            log.warning("trading: the terminal is not answering; nothing will be sent")
            return

        account = await self.broker.account()
        self.equity = account.equity or self.equity
        self.guard.roll(self.equity)
        await self._reconcile()
        await self._manage()
        await self._expire()

    def _mark_best(self, symbol: str, bid: float, ask: float) -> None:
        """Track the best price each open trade has seen, for the trail."""
        for ticket, live in self.open.items():
            if live.position.symbol != symbol:
                continue
            # The exit side, because that is the price a stop is measured
            # against: a long is closed on the bid.
            price = bid if live.position.side is Side.BUY else ask
            seen = self._best.get(ticket)
            if seen is None:
                self._best[ticket] = price
            elif live.position.side is Side.BUY:
                self._best[ticket] = max(seen, price)
            else:
                self._best[ticket] = min(seen, price)

    async def _manage(self) -> int:
        """Move stops on open trades, if either rule is switched on."""
        if not (self.settings.break_even_at > 0 or self.settings.trail_vol > 0):
            return 0
        moved = 0
        for ticket, live in list(self.open.items()):
            spec = self.specs.get(live.intent.feed)
            best = self._best.get(ticket)
            if spec is None or best is None:
                continue
            move = manage.advance(
                live.position,
                live.intent,
                spec,
                self.settings,
                best=best,
                vol_bps=self._vol_bps.get(live.intent.feed, 0.0),
            )
            if move is None:
                continue
            try:
                result = await self.execution.modify(ticket, move.stop, live.position.target)
            except BrokerError as exc:
                log.warning("trading: could not move #%d: %s", ticket, exc)
                continue
            if result.ok:
                moved += 1
                log.info("trading: %s", move)
        return moved

    async def _expire(self) -> None:
        """Close anything that has outstayed the hold its strategy asked for."""
        now = time.time()
        closed = False
        for ticket, live in list(self.open.items()):
            limit = live.intent.hold or self.settings.max_hold
            if limit <= 0:
                continue
            age = now - live.seen
            if age < limit:
                continue
            log.info("trading: closing #%d after %.0fs, past its %.0fs hold", ticket, age, limit)
            with contextlib.suppress(BrokerError):
                await self.execution.close_position(ticket)
            closed = True
        if closed:
            await self._reconcile()

    async def _reconcile(
        self, ref_for: tuple[int, Intent, str] | None = None
    ) -> list[tuple[Live, float, str]]:
        """Match the broker's open set against ours, and settle the difference."""
        if ref_for is not None:
            ticket, intent, ref = ref_for
            self._pending = (ticket, intent, ref)

        current = {p.ticket: p for p in await self._positions(fresh=True)}

        # Anything the broker has that we do not is ours as of this moment —
        # it is filtered to our magic — so adopt it with whatever intent is
        # waiting. An unadopted position would never be journalled on close.
        pending = self._pending
        for ticket, position in current.items():
            if ticket in self.open:
                self.open[ticket].position = position
                continue
            intent, ref = (pending[1], pending[2]) if pending else (None, "")
            if intent is None or intent.symbol != position.symbol:
                intent = _intent_from(position)
                ref = ""
            self.open[ticket] = Live(position=position, intent=intent, ref=ref)
            pending = None
        self._pending = None

        exact = {p.ticket: (price, why) for p, price, why in self.execution.drain_closed()}
        settled: list[tuple[Live, float, str]] = []
        for ticket, live in list(self.open.items()):
            if ticket in current:
                continue
            price, why = exact.get(ticket, (live.position.price_current, "gone"))
            del self.open[ticket]
            self._best.pop(ticket, None)
            settled.append((live, price, why))
            await self._settle(live, price, why)
        return settled

    async def _settle(self, live: Live, price: float, why: str) -> None:
        """Record a closed position, and tell the day about it."""
        position = live.position
        profit = position.profit
        self.guard.record(live.intent.feed, profit, self.equity)
        log.info(
            "trading: closed #%d %s @ %.5g for %+.2f (%s) · %s",
            position.ticket,
            position.symbol,
            price,
            profit,
            why,
            self.guard.summary(),
        )
        await self._announce_close(live, price, profit, why)
        if live.ref:
            await outcome(
                self.journal,
                live.ref,
                f"{position.symbol} closed {profit:+.2f} at {price:.5g}",
                rationale=(
                    f"{why} after {position.age:.0f}s, "
                    f"{'target' if profit > 0 else 'stop'} side of the trade"
                ),
                actor="trading",
                context={
                    "exit": price,
                    "profit": round(profit, 2),
                    "reason": why,
                    # Said plainly because it is not always a fill price: a
                    # position that vanished between polls is settled at the
                    # last quote we saw for it.
                    "exit_source": "broker" if why != "gone" else "last seen",
                    "seconds": round(position.age),
                    **live.intent.to_context(),
                },
                tags=(live.intent.feed, str(live.intent.side), why),
            )

    # ---------------------------------------------------------------- record

    async def _record_intent(self, intent: Intent, by: str) -> str:
        return await decide(
            self.journal,
            f"{self.settings.mode}: {intent.title}",
            rationale=intent.reason or f"{by} took a level call",
            actor="trading",
            context={"strategy": by, "mode": self.settings.mode, **intent.to_context()},
            tags=(intent.feed, str(intent.side), by or "scalp", self.settings.mode),
            confidence=intent.features.get("probability"),
        )

    async def _record_refusal(self, intent: Intent, refusal: Refusal, by: str) -> None:
        await observe(
            self.journal,
            f"declined {intent.title}",
            rationale=f"{refusal.gate}: {refusal.detail}",
            actor="trading",
            context={"strategy": by, "gate": refusal.gate, **intent.to_context()},
            tags=(intent.feed, "declined", refusal.gate),
        )

    async def _announce_fill(self, intent: Intent, price: float, ticket: int) -> None:
        if not (self.settings.notify and self.settings.notify_fills):
            return
        body = [
            f"{intent.side} {intent.volume:g} lots @ {price:.5g}",
            "",
            f"stop {intent.stop:.5g} · target {intent.target:.5g} · {intent.reward_to_risk:.1f}R",
            f"risking {intent.risk_money:.2f} ({intent.risk_money / self.equity:.2%})"
            if self.equity
            else "",
            intent.reason,
        ]
        await self.bus.publish(
            ALERTS,
            {
                "title": f"{self.settings.mode}: {intent.side} {intent.feed} #{ticket}",
                "body": "\n".join(line for line in body if line),
                "level": "info",
                "fields": {
                    "instrument": intent.feed,
                    "shape": "trade",
                    "direction": "up" if intent.side.sign > 0 else "down",
                    "venue": self.broker.name,
                },
                "source": "trading",
            },
            source="trading",
        )

    async def _announce_close(self, live: Live, price: float, profit: float, why: str) -> None:
        if not (self.settings.notify and self.settings.notify_closes):
            return
        await self.bus.publish(
            ALERTS,
            {
                "title": (f"{self.settings.mode}: {live.intent.feed} closed {profit:+.2f} ({why})"),
                "body": (
                    f"{live.position.side} {live.position.volume:g} @ "
                    f"{live.position.price_open:.5g} → {price:.5g}\n\n{self.guard.summary()}"
                ),
                "level": "info" if profit >= 0 else "warning",
                "fields": {
                    "instrument": live.intent.feed,
                    "shape": "trade",
                    "venue": self.broker.name,
                },
                "source": "trading",
            },
            source="trading",
        )

    async def _announce_decline(self, intent: Intent, refusal: Refusal) -> None:
        """A trade the strategy wanted and the account refused.

        Off unless asked for. It is the most interesting message here and the
        easiest to drown in — every gate that does its job produces one, and a
        halted day produces one per signal until the clock rolls over.
        """
        if not (self.settings.notify and self.settings.notify_declines):
            return
        await self.bus.publish(
            ALERTS,
            {
                "title": f"declined {intent.side} {intent.feed} — {refusal.gate}",
                "body": f"{refusal.detail}\n\n{intent.title}\n{self.guard.summary()}",
                "level": "info",
                "fields": {
                    "instrument": intent.feed,
                    "shape": "trade",
                    "venue": self.broker.name,
                },
                "source": "trading",
            },
            source="trading",
        )

    # ---------------------------------------------------------------- inside

    async def _tick(self, symbol: str) -> Tick | None:
        """The live quote, and the one the paper book fills against.

        Feeding it here rather than only from the bus is what makes an unarmed
        run against a real bridge honest: the simulated fill pays the broker's
        actual spread at that instant, not a consensus of other venues.
        """
        try:
            tick = await self.broker.quote(symbol)
        except BrokerError as exc:
            log.warning("trading: could not quote %s: %s", symbol, exc)
            return None
        if tick is not None and self.paper is not None:
            self.paper.observe(tick)
        return tick

    async def _positions(self, fresh: bool = False) -> list[Position]:
        if not fresh and self.open:
            return [live.position for live in self.open.values()]
        try:
            return await self.execution.positions()
        except BrokerError as exc:
            log.warning("trading: could not read positions: %s", exc)
            return [live.position for live in self.open.values()]

    def summary(self) -> str:
        return (
            f"{self.settings.mode} via {self.broker.name}: {self.taken} taken, "
            f"{self.refused} declined, {len(self.open)} open, "
            f"{self.resolutions} resolutions seen · {self.guard.summary()}"
        )


def _vol_of(payload: dict[str, Any]) -> float:
    """The volatility unit a signal was measured in, or 0."""
    features = payload.get("features")
    if not isinstance(features, dict):
        return 0.0
    value = features.get("vol_bps")
    return float(value) if isinstance(value, int | float) and value > 0 else 0.0


def message_time(payload: dict[str, Any]) -> float:
    when = payload.get("time")
    return float(when) if isinstance(when, int | float) and when else time.time()


def _intent_from(position: Position) -> Intent:
    """A placeholder intent for a position we did not open in this run.

    A restart leaves positions on the account carrying our magic and no record
    in memory of why they were opened. Adopting them means they are managed and
    closed properly; the reasoning is gone, and the journal entry says so
    rather than inventing one.
    """
    return Intent(
        feed=position.symbol.lower(),
        symbol=position.symbol,
        side=position.side,
        volume=position.volume,
        entry=position.price_open,
        stop=position.stop,
        target=position.target,
        reason="adopted on start-up; opened before this process was running",
    )


async def listen(
    bus: Bus,
    *,
    settings: Settings | None = None,
    journal: Journal | None = None,
    broker: Broker | None = None,
    limit: int | None = None,
) -> Trader:
    """Run the trader until the bus closes. Returns it, for its counters.

    The heartbeat runs alongside the message loop rather than inside it,
    because the two are unrelated: a stop can be hit during an hour in which no
    signal is published, and reconciling only when a message arrives would
    leave that trade recorded as open for as long as the market is quiet.

    Both topics are subscribed *before* either pump starts. `Bus.publish` only
    reaches groups that already exist, so subscribing inside the tasks would
    drop whatever was published between the first task starting and the second.
    """
    trader = Trader(bus, settings=settings, journal=journal, broker=broker)
    await trader.start()

    streams = {topic: bus.subscribe(topic, group="trading") for topic in TOPICS}
    queue: asyncio.Queue[Message | None] = asyncio.Queue()

    async def pump(topic: str) -> None:
        try:
            async for message in streams[topic]:
                await queue.put(message)
        finally:
            # A sentinel per topic, so the loop below knows the difference
            # between "quiet" and "closed" without polling either.
            await queue.put(None)

    tasks = [asyncio.create_task(pump(topic), name=f"trading:{topic}") for topic in TOPICS]
    tasks.append(asyncio.create_task(_heartbeat(trader), name="trading:heartbeat"))

    handled, closed = 0, 0
    try:
        while closed < len(TOPICS):
            message = await queue.get()
            if message is None:
                closed += 1
                continue
            await trader.handle(message)
            handled += 1
            if limit is not None and handled >= limit:
                break
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await trader.close()
    return trader


async def _heartbeat(trader: Trader) -> None:
    every = max(5.0, trader.settings.heartbeat)
    while True:
        await asyncio.sleep(every)
        try:
            await trader.sweep()
        except Exception as exc:  # a failed sweep must not end the service
            log.warning("trading: heartbeat failed: %s", exc)
