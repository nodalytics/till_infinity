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
message on any bus - the position is simply gone next time it is asked for. So
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
from ..structures.levels import SECONDS
from . import manage, plans, strategy
from . import symbols as sym
from .broker import Broker, BrokerError, build
from .config import Settings, magic_for, strategy_for
from .context import Context
from .manage import Move
from .models import Intent, Order, Position, Refusal, Side, SymbolSpec, Tick
from .models import money as money  # noqa: PLC0414
from .paper import PaperBroker
from .risk import Guard
from .sizing import price_distance

log = get_logger(__name__)

#: Everything the trader listens to, and why each one is needed.
#:
#: `signals` is the trade. `quotes` price the entry on the paper book and feed
#: the venue consensus our own broker is judged against. `events` is the
#: economic calendar, for standing aside around a release. `resolutions` is
#: ground truth - what the levels we traded actually did - which is consumed
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
    #: The strategy that asked for it. Empty when the position was adopted and
    #: its magic names no strategy we know - an older trade, or one opened by a
    #: plugin whose hashed offset has no inverse. Read from the position rather
    #: than remembered, so it survives a restart.
    by: str = ""


@dataclass(slots=True)
class Waiting:
    """A signal parked until price comes back to where the trade is worth taking.

    Entry is a market order, so a call arriving after price has already left
    the level is filled at whatever is on offer - which spends part of the move
    before the trade starts and leaves the stop, anchored to the level, sitting
    close underneath the fill. Parking it turns "buy here because a level is
    over there" into "buy when price comes back to the level".

    What is stored is the **signal**, not the intent. When price arrives the
    strategy is asked again against the current tick, so entry, stop, target
    and size are all re-derived through every gate rather than a stale intent
    being resurrected. A setup that stopped being worth taking while it waited
    is refused on arrival like any other.
    """

    payload: dict[str, Any]
    feed: str
    #: The price that wakes it, and which side of it counts.
    trigger: float
    side: Side
    #: After this it is dropped. A resting order with no deadline is a trade
    #: taken on information that has gone stale.
    until: float


@dataclass(slots=True)
class Shadow:
    """A trade that was stopped, watched to see whether it was right anyway.

    The single question the journal could not answer. A stop hit at full size
    looks identical whether the level failed or the stop was simply inside the
    noise, and the account cannot tell them apart - so the argument about stop
    width has had nothing to settle it but reasoning.

    This settles it. When a trade closes at a loss the target it was aiming at
    is kept, and price is watched for as long as the trade would have been
    held. If the target arrives, the thesis was right and the stop was too
    tight. If it does not, the stop was not the problem and widening it would
    only have made the same loss larger.

    Costs nothing to run: the quotes are already on the bus and being consumed.
    """

    feed: str
    side: Side
    entry: float
    stop: float
    target: float
    ref: str
    by: str
    #: When the watch gives up, which is the hold the trade would have had.
    until: float
    #: Furthest price reached in the trade's favour since it was stopped.
    best: float = 0.0
    stopped_at: float = 0.0


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
        #: The account's currency, for anything that prints an amount. A bare
        #: "+12.56" does not say what it is 12.56 of, and the answer is not
        #: guessable from the instrument - a gold trade on a euro-denominated
        #: account pays euros.
        self.currency = ""
        self.taken = 0
        self.refused = 0
        self._symbol_of: dict[str, str] = {}
        self._feed_of: dict[str, str] = {}
        #: The order just sent, waiting to be matched to the position it
        #: became. Held for exactly one reconcile - see `_reconcile`.
        self._pending: tuple[int, Intent, str] | None = None
        #: Best price each open trade has seen, for the trailing stop. Tracked
        #: from the quote stream rather than read from the broker, because
        #: `price_current` is a snapshot and a trail anchored to snapshots
        #: follows whatever the last poll happened to catch.
        self._best: dict[int, float] = {}
        #: feed -> a signal parked until price comes back. One per instrument,
        #: because the per-instrument position limit would refuse the second
        #: anyway and holding several would only decide which to drop later.
        self._waiting: dict[str, Waiting] = {}
        #: Stopped trades still being watched. See `Shadow`.
        self._shadows: dict[int, Shadow] = {}
        #: feed -> the spread when it was last quoted, for the record.
        self._spread_of: dict[str, float] = {}
        #: feed -> this fill was waited for. Consumed when the trade is taken.
        self._was_parked: dict[str, bool] = {}
        #: Why signals did not become trades, counted per gate. Strategy-level
        #: refusals are far too many to journal - hundreds a day, and mostly
        #: the filter working - but counting them is what separates "the market
        #: is quiet" from "the trader has been discarding everything".
        self.passed_over: dict[str, int] = {}
        self._last_summary = time.monotonic()
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
        against the real bid/ask - it simply cannot place anything.

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
        self.currency = account.currency or ""
        self.guard.currency = self.currency
        log.info(
            "trading: %s via %s - %s",
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
                "trading: TRADING_LIVE is not set - orders go to the paper book, "
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
        self._check_order()
        self._check_magics()
        self.guard.roll(self.equity)
        log.info(
            "trading: %s on %s",
            " + ".join(s.name for s in self.strategies),
            ", ".join(sorted(self.specs)),
        )

    def _check_order(self) -> None:
        """Warn when a strategy is listed where it can never trade.

        `TRADING_STRATEGIES` is a priority list - the first taker wins - so a
        strategy that is another plus extra refusals only ever sees what the
        permissive one declined, and it declined those for reasons the stricter
        one would decline too. It books nothing, forever, and every other
        signal says it is running: it loaded, it is enabled, it just never
        fires. That is the failure this catches, because it is the kind nobody
        finds by looking.
        """
        order = [engine.name for engine in self.strategies]
        for position, engine in enumerate(self.strategies):
            parent = engine.refines
            if not parent or parent not in order:
                continue
            if order.index(parent) < position:
                log.warning(
                    "trading: %s is %s plus extra refusals and is listed after "
                    "it, so it can only see calls %s already declined and will "
                    "never trade - put it first",
                    engine.name,
                    parent,
                    parent,
                )

    def _check_magics(self) -> None:
        """Print the strategy-to-magic map, and refuse a silent collision.

        Two strategies sharing a magic is not a cosmetic problem: their trades
        become one indistinguishable book, a report merges their results, and
        the merged number is the one somebody decides on. Only the hashed tail
        can collide - names in `MAGIC_ORDER` have fixed slots - so this is rare
        and worth saying out loud when it happens rather than discovering it in
        a scorecard that looks fine.
        """
        seen: dict[int, str] = {}
        for engine in self.strategies:
            magic = magic_for(self.settings.magic, engine.name)
            if magic in seen:
                log.warning(
                    "trading: %s and %s both stamp magic %d, so their trades "
                    "cannot be told apart - rename one",
                    seen[magic],
                    engine.name,
                    magic,
                )
                continue
            seen[magic] = engine.name
        log.info(
            "trading: magics %s",
            ", ".join(f"{name}={magic}" for magic, name in sorted(seen.items())),
        )

    def _check_gates(self) -> None:
        """Warn about a gate that cannot fire.

        `structures` will not publish a call below `reactions.MIN_EDGE`, so an
        edge floor at or under it is configuration that looks like a limit and
        is not one. This module shipped with exactly that - 0.08 against an
        upstream 0.10 - and nothing would have said so.
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
            feed = str(message.payload.get("feed") or "")
            symbol = self._symbol_of.get(feed)
            if symbol and (feed in self._waiting or self._shadows):
                got = await self._tick(symbol)
                if got is not None:
                    await self._watch_shadows(feed, got)
                    if feed in self._waiting:
                        return await self._arrived(feed, got)
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
        gained so that something *can* act on it - an accuracy-targeting gate,
        a back-check strategy, a Kelly fraction - and none of those exist yet.
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

        Every venue's quote goes to the consensus - that is the whole point of
        having six of them - but only our own broker's fills anything else.
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
        self._spread_of[feed] = tick.spread
        # The paper book holds its own stops, so it has to see the market. When
        # the execution venue *is* the broker they are the same object and this
        # runs once.
        for venue in {id(self.broker): self.broker, id(self.paper): self.paper}.values():
            observed = getattr(venue, "observe", None)
            if observed is not None:
                observed(tick)
        self._mark_best(symbol, float(bid), float(ask))

    async def on_signal(
        self, payload: dict[str, Any], *, observe: bool = True, park: bool = True
    ) -> Intent | Refusal | None:
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
        if observe:
            # Skipped when a parked signal is re-considered: the level is
            # already in each strategy's book, and folding it in twice would
            # count one publication as two observations.
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
            verdict = await engine.consider_async(payload, spec=spec, tick=tick, equity=self.equity)
            if isinstance(verdict, Refusal):
                self.refused += 1
                key = f"{engine.name}:{verdict.gate}"
                self.passed_over[key] = self.passed_over.get(key, 0) + 1
                # Deliberately not journalled. A strategy refusing on
                # probability or interval is the normal case - hundreds a day -
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

            if park:
                parked = self._park(payload, verdict, engine.name, tick)
                if parked is not None:
                    return parked
            return await self.take(verdict, engine.name)
        return None

    # --------------------------------------------------------------- trading

    def _park(self, payload: dict[str, Any], intent: Intent, by: str, tick: Tick) -> Refusal | None:
        """Hold this signal back if a better fill is worth waiting for.

        The target is where the stop would otherwise have sat - the far edge of
        the level's sweep zone - approached by `pullback_fraction` of the way
        from the current price. At 1.0 the trade waits for the price the stop
        was going to defend, which is the best fill the setup can offer and the
        one it fills least often; at 0.5 it meets it halfway.

        The trade that gets stopped out today is the trade that gets *filled*
        tomorrow, and the reward-to-risk improves because the target has not
        moved. What it costs is the setups that never come back, and that cost
        is real - a strategy that only fills on retracements is a different
        strategy, not a cheaper version of this one. Which is why this is off
        unless asked for, and why the journal records what it refused.
        """
        fraction = self.settings.pullback_fraction
        if fraction <= 0:
            return None
        features = intent.features or {}
        edge = features.get("sweep_low" if intent.side is Side.BUY else "sweep_high") or 0.0
        if not edge:
            return None

        # How far to wait is the **level's** business, not a constant.
        #
        # A fixed fraction asks every level for the same retracement, and levels
        # do not retrace the same amount: the wick this one has actually been
        # pushed to, on the side price is arriving from, is recorded on the
        # signal and is the measured answer to exactly this question. A level
        # that gets swept deeply is worth waiting deeper for; a level that
        # barely gets touched is not, and asking it to retrace as far as the
        # deep one just means never filling.
        #
        # `pullback_fraction` becomes the **ceiling** on that wait rather than
        # the wait itself, so a level with no wick history yet still parks
        # somewhere sensible instead of not parking at all.
        level = float(features.get("level") or 0.0)
        wick = features.get("wick_below_vol" if intent.side is Side.BUY else "wick_above_vol")
        spread = (
            features.get("wick_below_sd" if intent.side is Side.BUY else "wick_above_sd") or 0.0
        )
        seen = features.get("wick_n") or 0.0

        # Nothing to wait for on a level nobody has pushed.
        #
        # Parking asks price to come back somewhere it has been before. A level
        # with no wick history has no such place, so waiting is a bet with
        # nothing behind it - and the trade that expires unfilled is not a
        # trade avoided, it is a trade the strategy wanted and did not get.
        if seen < self.settings.pullback_min_wicks:
            return None

        unit = abs(intent.entry - intent.stop) / intent.stop_vol if intent.stop_vol else 0.0
        deep = float(edge)
        if wick and unit > 0 and level > 0:
            # From the level, not from the fill: the wick is measured from the
            # level and adding it to a fill that has already drifted would ask
            # for a retracement nobody has ever observed here.
            # Mean plus a share of the spread, rather than the mean alone.
            # Half of all wicks are deeper than the mean by definition, so
            # waiting at it is waiting at a depth that gets exceeded as often
            # as not - which for a retracement is the difference between being
            # met and being missed.
            depth = float(wick) + float(spread) * self.settings.pullback_sigmas
            # Bounded in volatility units rather than at the sweep edge.
            #
            # It used to clamp at the edge, twice over - once here and again
            # through a fraction whose ceiling *was* the edge - so a level
            # whose wicks run deeper than its own zone had the extra depth
            # discarded and was met shallow. That threw away the best fill the
            # setup offers: a deep pullback is the sweep, and buying the sweep
            # is the whole idea.
            #
            # The edge is not a safe stopping point either, which was the
            # stated reason and was wrong. The stop sits *beyond* the edge with
            # clearance, and `_floored_stop` guarantees it clears the **fill**
            # by `min_stop_vol` - so a deeper entry gets a proportionally
            # further stop on its own. An entry that really has gone too far is
            # refused by the `through` gate when the signal is reconsidered,
            # which is a check that already exists and is better placed.
            depth = min(depth, self.settings.pullback_max_vol)
            deep = level - intent.side.sign * depth * unit

        ceiling = intent.entry + (float(edge) - intent.entry) * fraction
        # Whichever asks for more depth, now that neither is clamped at the
        # edge. The fraction is still a floor on the wait for a level with no
        # wick history, where `deep` is the edge itself.
        want = min(deep, ceiling) if intent.side is Side.BUY else max(deep, ceiling)

        # Already there, or better: nothing to wait for.
        if (intent.entry - want) * intent.side.sign <= 0:
            return None

        # Is the better price worth the risk of not getting it?
        #
        # Parking trades a fill in hand for a fill that may not arrive, and the
        # trade that expires unfilled is a trade the strategy wanted. When the
        # fill on offer is already close to the level there is little left to
        # win and the whole spread of outcomes is downside - so the improvement
        # has to be worth something before the trade is put at risk for it.
        unit_now = price_distance(intent.entry, _vol_of(payload), 1.0)
        if unit_now > 0:
            better_by = abs(intent.entry - want) / unit_now
            if better_by < self.settings.pullback_min_gain:
                return None

        # Will price come back at all?
        #
        # `sweep_rate` is how often this level has been run through and
        # recovered - the level's own record of doing the thing being waited
        # for. A level that has never been swept is not one to wait for a sweep
        # on, and waiting anyway is how a signal becomes an expiry. Absent or
        # unmeasured passes, because an unknown rate is not a low one.
        swept = features.get("sweep_rate")
        seen_sweeps = features.get("sweep_n") or 0.0
        if (
            swept is not None
            and seen_sweeps >= self.settings.pullback_min_wicks
            and float(swept) < self.settings.pullback_min_sweep_rate
        ):
            return None

        # How long to wait, in bars of the timeframe that produced the call.
        #
        # A fraction of the hold makes the wait a property of the strategy
        # rather than of the market, so a 1m call and a 1h call wait the same
        # wall-clock time for retracements that happen on completely different
        # clocks. Bars of the entry interval is the same correction the hold
        # itself got, applied to the other end.
        # Bars of the interval that produced the call, falling back to the hold
        # itself when the interval is unknown - which is a real bound rather
        # than a second setting nobody would ever tune. There was one, and it
        # became unreachable the moment bars were preferred: the interval is
        # always known in practice, so the fraction it scaled was dead config
        # that still looked live.
        bars = SECONDS.get(intent.interval, 0.0)
        window = (
            bars * self.settings.pullback_bars if bars else (intent.hold or self.settings.max_hold)
        )
        self._waiting[intent.feed] = Waiting(
            payload=payload,
            feed=intent.feed,
            trigger=want,
            side=intent.side,
            until=tick.time + window,
        )
        self._was_parked[intent.feed] = True
        log.info(
            "trading: %s %s parked - waiting for %.5g rather than filling at %.5g [%s]",
            intent.side,
            intent.feed,
            want,
            intent.entry,
            by,
        )
        return Refusal("waiting", f"holding out for {want:.5g}", intent.feed)

    async def _arrived(self, feed: str, tick: Tick) -> Intent | Refusal | None:
        """Wake a parked signal if price has come to it, or drop it if stale."""
        held = self._waiting.get(feed)
        if held is None:
            return None
        if tick.time >= held.until:
            self._waiting.pop(feed, None)
            log.info("trading: %s expired waiting for %.5g", feed, held.trigger)
            return None
        price = tick.entry(held.side)
        if (price - held.trigger) * held.side.sign > 0:
            return None  # not there yet
        self._waiting.pop(feed, None)
        log.info("trading: %s reached %.5g - reconsidering", feed, held.trigger)
        # Asked again rather than resurrected: a setup that stopped being worth
        # taking while it waited is refused on arrival like any other.
        return await self.on_signal(held.payload, observe=False, park=False)

    async def take(self, intent: Intent, by: str = "") -> Intent | Refusal:
        """Send an order, or say why it was not sent."""
        ref = await self._record_intent(intent, by)

        if not self.settings.live:
            log.info("trading: [paper] %s - %s", intent.title, intent.reason)

        order = Order(
            symbol=intent.symbol,
            side=intent.side,
            volume=intent.volume,
            stop=intent.stop,
            target=intent.target,
            comment=f"till {by or 'scalp'}"[:31],
            # The comment says the same thing, but comments are advisory: MT5
            # caps them at 31 characters and brokers rewrite them. This is the
            # field that still names the strategy after a restart, and the one
            # a report can group by.
            magic=magic_for(self.settings.magic, by),
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
        log.info(
            "trading: %s %s [%s] - %s",
            self.settings.mode,
            result,
            by or "scalp",
            intent.reason,
        )
        await self._announce_fill(intent, result.price, result.ticket, by)
        # Tracked from the broker's own position list rather than from the
        # result, because the ticket a fill reports is the order's and the one
        # that has to be closed is the position's. Reconciling picks it up.
        await self._reconcile(ref_for=(result.ticket, intent, ref))
        return intent

    def _say_what_it_is_doing(self) -> None:
        """Report the shape of the silence, periodically.

        A trader that has taken nothing looks identical whether the market is
        quiet, the signals are being discarded by a gate, or the subscription
        is broken. handoff.md calls this out as a class of bug: correct silence
        and broken silence are indistinguishable, and every such place needs a
        positive signal saying which it is.

        It cost a day here. Level calls were arriving and being delivered to
        Telegram while the trader discarded every one of them on a timeframe
        filter, and the only trace was a DEBUG line nobody was reading.
        """
        every = max(300.0, self.settings.heartbeat * 5)
        if time.monotonic() - self._last_summary < every:
            return
        self._last_summary = time.monotonic()
        if not self.passed_over and not self.taken:
            log.info(
                "trading: nothing seen yet - %s on %s, %s",
                " + ".join(s.name for s in self.strategies),
                ", ".join(sorted(self.specs)),
                ", ".join(self.settings.intervals),
            )
            return
        top = sorted(self.passed_over.items(), key=lambda kv: -kv[1])[:4]
        log.info(
            "trading: %d taken, %d passed over (%s) · %s",
            self.taken,
            self.refused,
            ", ".join(f"{gate} x{count}" for gate, count in top) or "none",
            self.guard.summary(),
        )

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
        self._say_what_it_is_doing()

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
                await self._announce_move(live, move)
        return moved

    async def _announce_move(self, live: Live, move: Move) -> None:
        """Say when a stop moves, because it changes what the trade can lose.

        Fills and closes were announced and this was not, so the channel showed
        a trade opening at one risk and closing at another with nothing in
        between to explain it - and the moment a trade stops being able to lose
        is the most reassuring thing that happens to it.
        """
        if not (self.settings.notify and self.settings.notify_fills):
            return
        risk = abs(live.intent.entry - live.intent.stop)
        gained = (move.stop - live.position.price_open) * live.intent.side.sign
        await self.bus.publish(
            ALERTS,
            {
                "title": (
                    f"{self.settings.mode}: {live.intent.feed} stop to {move.stop:.5g}"
                    + (f" · {live.by}" if live.by else "")
                ),
                "body": (
                    f"{move.reason}\n\n"
                    f"{live.position.side} {live.position.volume:g} @ "
                    f"{live.position.price_open:.5g}\n"
                    + (
                        f"locked in {self.money(gained / risk * live.intent.risk_money)}"
                        if risk
                        else ""
                    )
                ),
                "level": "info",
                "fields": {
                    "instrument": live.intent.feed,
                    "shape": "trade",
                    # Its own event, so it neither suppresses nor is suppressed
                    # by the fill and the close it sits between.
                    "event": "protect",
                    "strategy": live.by,
                    "venue": self.broker.name,
                },
                "source": "trading",
            },
            source="trading",
        )

    async def _expire(self) -> None:
        """Close anything that has outstayed the hold its strategy asked for.

        Unless it is working. The hold exists to release capital from a thesis
        that is not playing out, and it was closing trades that were - a
        position a point in front at the thirty minute mark went out at market
        and the rest of the move happened without us. Observed on gold: out at
        4623 on a fall that carried to 4592.

        So a trade far enough in front is protected and kept instead. See
        `_worth_keeping`, which moves the stop to break even first, so an
        extension can scratch but cannot turn a winner into a loser.
        """
        now = time.time()
        closed = False
        for ticket, live in list(self.open.items()):
            limit = live.intent.hold or self.settings.max_hold
            if limit <= 0:
                continue
            age = now - live.seen
            if age < limit:
                continue
            if await self._worth_keeping(live, age, limit):
                continue
            log.info("trading: closing #%d after %.0fs, past its %.0fs hold", ticket, age, limit)
            with contextlib.suppress(BrokerError):
                await self.execution.close_position(ticket)
            closed = True
        if closed:
            await self._reconcile()

    def _reach(self, live: Live) -> float:
        """Furthest this trade got in front, in units of its own risk."""
        best = self._best.get(live.position.ticket)
        risk = abs(live.intent.entry - live.intent.stop)
        if best is None or risk <= 0:
            return 0.0
        gained = (best - live.position.price_open) * live.intent.side.sign
        return max(gained / risk, 0.0)

    def money(self, amount: float, *, signed: bool = True) -> str:
        """An amount with the account's currency attached. See `models.money`."""
        return money(amount, self.currency, signed=signed)

    async def _watch_shadows(self, feed: str, tick: Tick) -> None:
        """Follow stopped trades to see whether the target arrived anyway.

        Recorded, never traded. The point is to answer the one question the
        account cannot: a stop hit at full size looks the same whether the
        level failed or the stop sat inside the noise, and until this existed
        the argument about stop width had nothing but reasoning to settle it.
        """
        for ticket, shade in list(self._shadows.items()):
            if shade.feed != feed:
                continue
            price = tick.bid if shade.side is Side.BUY else tick.ask
            sign = shade.side.sign
            if (price - shade.best) * sign > 0:
                shade.best = price

            hit = (price - shade.target) * sign >= 0
            done = hit or tick.time >= shade.until
            if not done:
                continue
            self._shadows.pop(ticket, None)

            risk = abs(shade.entry - shade.stop)
            reach = abs(shade.best - shade.entry) / risk if risk else 0.0
            went = (shade.best - shade.entry) * sign
            log.info(
                "trading: stopped #%d [%s] would have %s - best %.5g against a "
                "target of %.5g (%.2fR of the way)",
                ticket,
                shade.by or "unattributed",
                "WON" if hit else "still lost",
                shade.best,
                shade.target,
                reach if went > 0 else 0.0,
            )
            await observe(
                self.journal,
                f"stopped {shade.feed} {'reached' if hit else 'never reached'} its target",
                rationale=(
                    f"best {shade.best:.5g} against target {shade.target:.5g} "
                    f"in the {self.settings.shadow_window:.1f}x hold after the stop"
                ),
                actor="trading",
                context={
                    "shape": "shadow",
                    "feed": shade.feed,
                    "strategy": shade.by,
                    "ticket": ticket,
                    "reached_target": hit,
                    # How far the trade got, in units of the risk it was
                    # stopped for. Above 1 means the stop cost a winner.
                    "best_r": round(reach if went > 0 else 0.0, 3),
                    "stopped_at": round(shade.stopped_at, 8),
                    "best": round(shade.best, 8),
                    "target": round(shade.target, 8),
                },
                tags=(shade.feed, "shadow", shade.by or "unattributed"),
            )

    async def _worth_keeping(self, live: Live, age: float, limit: float) -> bool:
        """Whether a trade past its hold is working well enough to keep.

        Three conditions, and all of them have to hold.

        **It has to be in front**, by `hold_extends_at` times the risk it was
        sized for. Measured from the current price rather than from the best
        seen: the question is whether to keep the position now, and the best
        price is history the trade may already have given back.

        **It has to be protectable.** The stop is moved to break even plus the
        spread cushion before the extension is granted, so the worst outcome
        after this point is a scratch. That is what makes the rule safe to run
        without the trailing rules in `manage.py` being switched on, and if the
        move is refused the trade is closed on the clock as before rather than
        held unprotected.

        **It has to end.** `max_hold_multiple` caps total age, because a
        position kept indefinitely accrues swap, crosses sessions it was never
        measured in, and eventually sits over a weekend.
        """
        at = self.settings.hold_extends_at
        if at <= 0:
            return False
        if age >= limit * max(1.0, self.settings.max_hold_multiple):
            return False

        position, intent = live.position, live.intent
        risk = abs(intent.entry - intent.stop)
        if risk <= 0:
            return False
        tick = await self._tick(position.symbol)
        if tick is None:
            return False
        # The price this position would be closed at, not the mid: a long exits
        # on the bid, and crediting it the mid would extend trades that are not
        # actually in front once the spread is paid.
        out = tick.bid if position.side is Side.BUY else tick.ask
        gained = (out - position.price_open) * position.side.sign
        if gained < risk * at:
            return False

        spec = self.specs.get(intent.feed)
        if spec is None:
            return False
        cushion = spec.tick_size * max(0, self.settings.break_even_ticks)
        safe = spec.round_price(position.price_open + position.side.sign * cushion)
        # Never backwards: if the stop is already better than break even - the
        # trailing rules are on and have moved it - leave it where it is.
        if not manage.better(safe, position.stop, position.side):
            safe = position.stop
        elif not await self._protect(position.ticket, safe, position.target):
            return False

        log.info(
            "trading: keeping #%d past its %.0fs hold - %.1fR in front, stop at %.5g",
            position.ticket,
            limit,
            gained / risk,
            safe,
        )
        return True

    async def _protect(self, ticket: int, stop: float, target: float) -> bool:
        """Move a stop, saying whether it actually moved."""
        try:
            result = await self.execution.modify(ticket, stop, target)
        except BrokerError as exc:
            log.warning("trading: could not protect #%d: %s", ticket, exc)
            return False
        return bool(result.ok)

    async def _reconcile(
        self, ref_for: tuple[int, Intent, str] | None = None
    ) -> list[tuple[Live, float, str]]:
        """Match the broker's open set against ours, and settle the difference."""
        if ref_for is not None:
            ticket, intent, ref = ref_for
            self._pending = (ticket, intent, ref)

        current = {p.ticket: p for p in await self._positions(fresh=True)}

        # Anything the broker has that we do not is ours as of this moment -
        # it is filtered to our magic - so adopt it with whatever intent is
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
            self.open[ticket] = Live(
                position=position,
                intent=intent,
                ref=ref,
                by=strategy_for(self.settings.magic, position.magic),
            )
            pending = None
        self._pending = None

        exact = {p.ticket: (price, why) for p, price, why in self.execution.drain_closed()}
        settled: list[tuple[Live, float, str]] = []
        for ticket, live in list(self.open.items()):
            if ticket in current:
                continue
            price, why = exact.get(ticket, (live.position.price_current, "gone"))
            profit = live.position.profit
            if why == "gone":
                # Ask the terminal what it actually paid, rather than settling
                # at the last snapshot we happened to hold. See
                # `Broker.closed_deal`.
                try:
                    told = await self.execution.closed_deal(ticket)
                except BrokerError as exc:
                    log.debug("trading: could not confirm #%d: %s", ticket, exc)
                    told = None
                if told is not None and told[0]:
                    price, profit, why = told[0], told[1], "closed"
            del self.open[ticket]
            self._best.pop(ticket, None)
            settled.append((live, price, why))
            await self._settle(live, price, why, profit)
        return settled

    async def _settle(
        self, live: Live, price: float, why: str, profit: float | None = None
    ) -> None:
        """Record a closed position, and tell the day about it."""
        position = live.position
        profit = position.profit if profit is None else profit
        self.guard.record(live.intent.feed, profit, self.equity)
        log.info(
            "trading: closed #%d %s [%s] @ %.5g for %+.2f (%s) · %s",
            position.ticket,
            position.symbol,
            live.by or "unattributed",
            price,
            profit,
            why,
            self.guard.summary(),
        )
        if profit < 0 and self.settings.shadow_window > 0 and live.intent.target:
            hold = live.intent.hold or self.settings.max_hold
            self._shadows[position.ticket] = Shadow(
                feed=live.intent.feed,
                side=live.intent.side,
                entry=live.intent.entry,
                stop=live.intent.stop,
                target=live.intent.target,
                ref=live.ref,
                by=live.by,
                until=time.time() + hold * self.settings.shadow_window,
                best=price,
                stopped_at=price,
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
                    # "closed" is the terminal's own deal record, "gone" the
                    # last snapshot we held because it could not be read.
                    "exit_source": "last seen" if why == "gone" else "broker",
                    "seconds": round(position.age),
                    "strategy": live.by,
                    "magic": position.magic,
                    # Which of the three ways it ended. `reason` says how the
                    # position left the book - closed, or gone between polls -
                    # and not what took it, so stop and target were
                    # indistinguishable except by the sign of the profit, which
                    # is a guess dressed as a fact.
                    "exit_kind": _exit_kind(live, price),
                    # How far in front the trade ever got, in units of the risk
                    # it was sized for. The service has tracked the best price
                    # all along - the trailing rules need it - and never wrote
                    # it down, so "we were up and gave it back" was something
                    # you could watch happen and not something you could
                    # measure afterwards. Above 1 means a trade that was a
                    # winner by its own risk and did not end as one.
                    "best_r": round(self._reach(live), 3),
                    # What was asked for against what the terminal actually
                    # filled at. `position.price_open` is the broker's own
                    # record, so this survives a restart and does not depend on
                    # having kept the order result around.
                    #
                    # Until this was written down slippage was not recoverable
                    # from the journal at all: the decision held the requested
                    # price, the outcome held the exit, and the fill in between
                    # reached only an alert. It is signed against the trade -
                    # positive is a worse fill than asked for, on either side -
                    # so the sign means the same thing for a buy and a sell.
                    #
                    # Zero on an adopted position, whose synthetic intent is
                    # built from the fill itself.
                    "entry_wanted": round(live.intent.entry, 8),
                    "entry_filled": round(position.price_open, 8),
                    "slippage": round(
                        (position.price_open - live.intent.entry) * live.intent.side.sign, 8
                    ),
                    **live.intent.to_context(),
                },
                tags=(live.intent.feed, str(live.intent.side), why, live.by or "unattributed"),
            )

    # ---------------------------------------------------------------- record

    async def _record_intent(self, intent: Intent, by: str) -> str:
        return await decide(
            self.journal,
            f"{self.settings.mode}: {intent.title}",
            rationale=intent.reason or f"{by} took a level call",
            actor="trading",
            context={
                "strategy": by,
                # What the spread actually was when this was sent. Three gates
                # judge spread and none of them wrote down the number they
                # judged, so "what did execution cost" could be argued about
                # but not answered.
                "spread_at_entry": round(self._spread_of.get(intent.feed, 0.0), 8),
                # Whether this fill was waited for rather than taken. Without
                # it the pullback cannot be evaluated at all: parked and
                # unparked trades are indistinguishable once filled.
                "waited": bool(self._was_parked.pop(intent.feed, False)),
                # The stop in the units the rules are written in, and the
                # multiplier the hold scaling applied. Both were recoverable
                # from entry, stop and vol_bps by arithmetic - which is another
                # way of saying every future question about them started with
                # a derivation that could be got wrong.
                "stop_vol": round(intent.stop_vol, 4),
                "stop_scale": round(intent.stop_scale, 4),
                "hold_seconds": round(intent.hold or self.settings.max_hold, 1),
                # Recorded so a position found at the broker can be matched
                # back to this entry by number alone, with nothing in memory.
                "magic": magic_for(self.settings.magic, by),
                "mode": self.settings.mode,
                **intent.to_context(),
            },
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

    async def _announce_fill(self, intent: Intent, price: float, ticket: int, by: str = "") -> None:
        if not (self.settings.notify and self.settings.notify_fills):
            return
        body = [
            f"{intent.side} {intent.volume:g} lots @ {price:.5g}",
            "",
            f"stop {intent.stop:.5g} · target {intent.target:.5g} · {intent.reward_to_risk:.1f}R",
            f"risking {self.money(intent.risk_money, signed=False)} "
            f"({intent.risk_money / self.equity:.2%})"
            if self.equity
            else "",
            intent.reason,
        ]
        await self.bus.publish(
            ALERTS,
            {
                "title": (
                    f"{self.settings.mode}: {intent.side} {intent.feed} #{ticket}"
                    + (f" · {by}" if by else "")
                ),
                "body": "\n".join(line for line in body if line),
                "level": "info",
                "fields": {
                    "instrument": intent.feed,
                    "shape": "trade",
                    # Part of the repeat key. Without it a fill and its own
                    # close read as the same finding, and a trade that closed
                    # inside the cooldown lost its close alert entirely.
                    "event": "open",
                    "strategy": by,
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
                "title": (
                    f"{self.settings.mode}: {live.intent.feed} closed "
                    f"{self.money(profit)} ({why})" + (f" · {live.by}" if live.by else "")
                ),
                "body": (
                    f"{live.position.side} {live.position.volume:g} @ "
                    f"{live.position.price_open:.5g} → {price:.5g}\n\n{self.guard.summary()}"
                ),
                "level": "info" if profit >= 0 else "warning",
                "fields": {
                    "instrument": live.intent.feed,
                    "shape": "trade",
                    "event": "close",
                    "strategy": live.by,
                    "venue": self.broker.name,
                },
                "source": "trading",
            },
            source="trading",
        )

    async def _announce_decline(self, intent: Intent, refusal: Refusal) -> None:
        """A trade the strategy wanted and the account refused.

        Off unless asked for. It is the most interesting message here and the
        easiest to drown in - every gate that does its job produces one, and a
        halted day produces one per signal until the clock rolls over.
        """
        if not (self.settings.notify and self.settings.notify_declines):
            return
        await self.bus.publish(
            ALERTS,
            {
                "title": f"declined {intent.side} {intent.feed} - {refusal.gate}",
                "body": f"{refusal.detail}\n\n{intent.title}\n{self.guard.summary()}",
                "level": "info",
                "fields": {
                    "instrument": intent.feed,
                    "shape": "trade",
                    "event": "declined",
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
        gates = ", ".join(
            f"{gate} x{count}"
            for gate, count in sorted(self.passed_over.items(), key=lambda kv: -kv[1])[:4]
        )
        return (
            f"{self.settings.mode} via {self.broker.name}: {self.taken} taken, "
            f"{self.refused} declined, {len(self.open)} open, "
            f"{self.resolutions} resolutions seen · {self.guard.summary()}"
            + (f" · passed over: {gates}" if gates else "")
        )


def _vol_of(payload: dict[str, Any]) -> float:
    """The volatility unit a signal was measured in, or 0."""
    features = payload.get("features")
    if not isinstance(features, dict):
        return 0.0
    value = features.get("vol_bps")
    return float(value) if isinstance(value, int | float) and value > 0 else 0.0


def _exit_kind(live: Live, price: float) -> str:
    """Which of the three ways a trade ended, decided by where it ended.

    `reason` records how the position left the book - closed by us, or gone
    between polls - not what took it. Stop and target were therefore
    distinguishable only by the sign of the profit, which is a guess dressed as
    a fact: a trade closed on the hold clock while slightly ahead looks like a
    target, and one closed slightly behind looks like a stop.
    """
    intent = live.intent
    sign = intent.side.sign
    if intent.stop and (price - intent.stop) * sign <= 0:
        return "stop"
    if intent.target and (price - intent.target) * sign >= 0:
        return "target"
    return "hold"


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
