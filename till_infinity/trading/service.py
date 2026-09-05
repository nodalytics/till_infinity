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
import json
import time
from collections import Counter
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, ClassVar

from ..bus import ALERTS, EVENTS, QUOTES, RESOLUTIONS, SIGNALS, Bus, Message
from ..journal import Journal, decide, observe, outcome
from ..logging import get_logger
from ..structures.context.cusum import Cusum, Ensemble, adaptive_threshold
from ..structures.context.holds import Book as HoldBook
from ..structures.context.reach import Reaches
from ..structures.context.trend import Trend
from ..structures.levels import SECONDS
from . import manage, plans
from .candles import confirms
from .config import Settings, magic_for, strategy_for
from .context import Context
from .manage import Move, Take
from .models import Intent, Order, Position, Refusal, Side, SymbolSpec, Tick
from .models import money as money  # noqa: PLC0414
from .risk import Guard
from .sessions import Sessions
from .sizing import lots, price_distance
from .strategies import strategy
from .strategies.opportunity import PRESETS
from .strategies.policy import Policy
from .strategies.strategy import Strategy
from .venues import replicate
from .venues import symbols as sym
from .venues.broker import Broker, BrokerError, build
from .venues.paper import PaperBroker

log = get_logger(__name__)

#: The bar size session hours are learned at. Fifteen minutes resolves the
#: daily break and the Friday close, which is what the gate needs, without
#: fetching a minute of history for every instrument at start-up.
#: How fast the per-feed push estimate follows new calls. Slow, because this
#: is a property of the instrument rather than of the moment.
PUSH_DECAY = 0.05

#: The share of a typical push that counts as a turn, and the most one may ask
#: for. The share matches the momentum filter's, because they are reading the
#: same event by different means; the ceiling stops an instrument with a huge
#: modelled push from asking for a turn no pullback ever produces.
#: How many of a series' own expected holds a trade gets before it counts as
#: going nowhere. Two, because one is the time it usually takes and stopping
#: there would close every trade that is merely slower than the median.
STALE_HOLDS = 2.0

#: How much of the sub-hour ensemble must be behind a motionless trade for it
#: to be given more time. A majority, because half the timeframes pointing one
#: way is what a coin flip looks like.
STALE_AGREE = 0.5

TURN_SHARE = 0.35
TURN_CEILING = 2.0

SESSION_INTERVAL = "15m"
SESSION_INTERVAL_S = 15 * 60

#: How many symbols to fetch bars for at once. Sequentially this is 0.72s each
#: and adds 24s to start-up, during which the service is not trading and the
#: closing gate is not yet armed. Six at a time brings it under five seconds
#: without asking the bridge to serve thirty-three at once.
SESSION_FETCHES = 6

#: Where a re-armed signal carries its attempt count. Kept on the payload
#: rather than in a table keyed by feed, so it survives the round trip through
#: `_park` and back into `on_signal` without anything having to remember it,
#: and so a signal that never comes back never leaves a counter behind.
ATTEMPT = "_attempt"

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
    #: True once part of this position has been banked, so the scale-out
    #: happens once rather than on every pass of the manage loop.
    scaled: bool = False
    #: The signal that produced this trade, kept so a stopped-out setup can be
    #: put back through the strategies rather than resurrected as a stale
    #: intent. Empty for adopted positions, which therefore never re-arm -
    #: correctly, since nothing here knows what they were.
    signal: dict[str, Any] = field(default_factory=dict)
    #: How many times this setup has already been taken. Zero on a first
    #: entry, and the guard that stops `reentry_max` compounding.
    attempt: int = 0
    #: Which of our own rules closed this, when one of them did. The price
    #: cannot say: a stale close and a hold-clock close both land wherever the
    #: market happens to be, and both used to read as "hold".
    closed_by: str = ""


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
    #: The broker's order, when the price was also left there as a limit - see
    #: `Settings.entry_pending`. Held so it can be withdrawn: this system keeps
    #: the judgement and the broker keeps the reflexes, and the half that can
    #: change its mind has to be able to reach the half that cannot.
    ticket: int = 0
    #: What was left there, kept only so the withdrawal can describe it. The
    #: **decision** is still re-made from `payload` on arrival - this is not a
    #: stale intent waiting to be resurrected, it is a label.
    resting: Intent | None = None
    by: str = ""


@dataclass(slots=True)
class Untaken:
    """A trade a strategy wanted and did not get, followed to its own barriers.

    `_also_wanted` already asks every strategy what it would have done with a
    signal another one took, and journals the answer with the prices it would
    have used. Until this existed nothing resolved those intents, so the record
    said what each strategy *wanted* and never what it would have *got* - and
    the ranking that settles which strategy should own a signal had to be
    computed by hand, off stored bars, after the fact.

    This closes that loop on the live quote stream. Two stages, because an
    intent is not a trade until it fills:

    1. **Fill.** The named entry has to trade. Several strategies rest their
       entry away from the market, and crediting them with a fill they never
       got would hand them a better price than they would have had.
    2. **Barriers.** From the fill, whichever of target or stop arrives first
       inside the hold. Neither arriving is a timeout, marked to the last
       price, exactly as the live trade would have been.

    Costs one comparison per open intent per quote, on quotes already on the
    bus. It is the feedback channel for arms nobody pulled, which is the thing
    a bandit assumes it cannot have.
    """

    feed: str
    by: str
    side: Side
    entry: float
    stop: float
    target: float
    interval: str
    #: When to give up waiting for the fill.
    fill_by: float
    #: How long the trade may run once filled.
    hold: float
    placed_at: float = 0.0
    #: Zero until it fills, then the time it did.
    filled_at: float = 0.0
    #: When the barrier race ends. Set at fill.
    until: float = 0.0
    #: Last price seen since the fill, for a timeout's mark to market.
    last: float = 0.0


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


def _closed_body(
    live: Live, price: float, profit: float, why: str, money: str, standing: str
) -> str:
    """A close, laid out like the fill it answers.

    The R multiple leads, because it is the only figure that compares one trade
    against another - the money says what this one did and the R says whether
    the rule is working.
    """
    rule = "━" * 22
    won = profit >= 0
    risk = abs(live.intent.entry - live.intent.stop)
    got = ((price - live.position.price_open) * live.position.side.sign / risk) if risk else 0.0
    lines = [
        rule,
        f"{'✅' if won else '❌'} {live.intent.feed.upper().replace('_', ' ')} · "
        f"CLOSED · {why.upper()}",
        rule,
        f"📊 {live.by or 'trading'} · #{live.position.ticket}",
        "",
        f"📍 {live.position.side} {live.position.volume:g} @ "
        f"{live.position.price_open:.5g} → {price:.5g}",
        f"{'💚' if won else '💔'} {money} · {got:+.2f}R",
    ]
    if standing:
        lines.append(f"📅 {standing}")
    lines.append(rule)
    return "\n".join(lines)


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
        #: What this style is running, and what it stood down. Both are set
        #: here and nowhere else - an initialiser placed after this line once
        #: quietly emptied the second of them.
        self.strategies, self.stood_down = strategy.by_style(
            strategy.build(self.settings.strategies, self.settings), self.settings.style
        )
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
        #: The highest equity this process has seen. Drawdown is measured from
        #: it, so a book that has given back a third of its month trades
        #: smaller *before* the daily halt fires rather than at full size until
        #: it does. Not persisted: a restart starts the peak at the current
        #: equity, which under-reports an existing drawdown rather than
        #: inventing one, and understating is the safe direction for a number
        #: that only ever reduces size.
        self.peak_equity = 0.0
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
        #: The signal behind each feed's most recent trade, so a stopped-out
        #: setup can be put back through the strategies rather than rebuilt
        #: from an intent that has already been proved wrong once.
        self._last_signal: dict[str, dict[str, Any]] = {}
        #: Signals waiting to be re-armed after a stop. Drained by the loop
        #: rather than re-entered from inside `_settle`, which runs during
        #: reconciliation - taking a trade there would mutate the position set
        #: being reconciled, from inside the walk over it.
        self._rearm: list[dict[str, Any]] = []
        #: Accumulated directional pressure per feed, fed from the quote
        #: stream. One per feed rather than one shared, because the
        #: accumulation is the state and mixing instruments into it would
        #: measure nothing.
        self._push: dict[str, Cusum] = {}
        #: The same momentum question asked at several sub-hour resolutions.
        #: The single filter above answers "is there momentum" at whatever
        #: speed quotes happen to arrive; this one can also say whether the
        #: timeframes agree, which is what a swing entry at an origin turns on.
        self._ensemble: dict[str, Ensemble] = {}
        #: A slow read on how far each instrument pushes, which is what the
        #: momentum threshold is sized against. See `_note_push`.
        self._push_vol: dict[str, float] = {}
        #: Trend context per feed and interval. Keyed on both because the
        #: efficiency of 1m levels and of 15m levels on one instrument are
        #: different markets, and pooling them measures neither.
        self._trend: dict[tuple[str, str], Trend] = {}
        #: How long a touch on each feed and interval takes to resolve. Fed
        #: from the resolution stream, which the trader already subscribes to.
        self._holds = HoldBook()
        #: How far price reaches into a level, and against a trade once in it.
        #: The two distances behind an entry and a stop. See
        #: `structures/reach.py`.
        self._reaches = Reaches()
        #: When each feed last quoted. A market in its daily break keeps its
        #: last quote and refuses every order, which is a different thing from
        #: an order being wrong and wants the opposite handling: wait, rather
        #: than retry and shout. `spec.tradable` reports whether an instrument
        #: is enabled, not whether it is trading, so it says True throughout.
        self._quoted_at: dict[str, float] = {}
        self._sessions = Sessions()
        self.replicator = replicate.from_settings(self.settings)
        #: symbol -> (when we looked, the broker's own tick time). Two numbers
        #: because a cached tick time goes on ageing whether or not we are
        #: still asking, and a stale observation must not be read as a shut
        #: market. See `_shut_for`.
        self._broker_quoted_at: dict[str, tuple[float, float]] = {}
        #: Best price each open trade has seen, for the trailing stop. Tracked
        #: from the quote stream rather than read from the broker, because
        #: `price_current` is a snapshot and a trail anchored to snapshots
        #: follows whatever the last poll happened to catch.
        #: Where the extremes are kept between restarts.
        #:
        #: **They were kept nowhere, and that is a measured leak.** `_best` and
        #: `_worst` are the only things this service needs across a restart,
        #: and it persisted nothing at all - so every deploy reset the
        #: high-water mark of every open position. A trade that had run to 2R
        #: came back looking like a trade at its entry, break-even never fired
        #: on a move it had already earned, and it gave the lot back. There
        #: were ten deploys on 2026-09-04 alone.
        #:
        #: It also understated the damage: `best_r` on the close is read from
        #: this dict, so a give-back measured after a restart records the peak
        #: it reached *since* the restart, not the one that mattered.
        self._marks = Path(self.settings.state_dir) / "extremes.json"
        self._recalled = False
        self._best: dict[int, float] = {}
        #: feed -> how many quotes `_quote` has resolved a symbol for. Only
        #: read by the `_manage` skip diagnostic, which cannot otherwise
        #: distinguish "no quote ever arrived for this feed" from "quotes
        #: arrived and `_mark_best` did not match them to the position".
        self._quotes_seen: Counter[str] = Counter()
        #: The worst price each open trade has seen. The mirror of `_best`, and
        #: it was missing: the trailing rules need the favourable extreme so
        #: that one was tracked, and nothing needed the adverse one so nobody
        #: wrote it down. That made "how much heat does a winner take" - the
        #: number that sizes a stop - unanswerable from our own record.
        self._worst: dict[int, float] = {}
        #: feed -> a signal parked until price comes back. One per instrument,
        #: because the per-instrument position limit would refuse the second
        #: anyway and holding several would only decide which to drop later.
        self._waiting: dict[str, Waiting] = {}
        #: Stopped trades still being watched. See `Shadow`.
        self._shadows: dict[int, Shadow] = {}
        #: Intents other strategies wanted, keyed by feed, followed to their
        #: own barriers. See `Untaken`. Bounded per feed because this grows
        #: with strategies times signals and nothing else evicts it.
        self._untaken: dict[str, list[Untaken]] = {}
        #: What each shape has been worth, and the chooser that reads it. Fed
        #: from `_record_untaken` - which is full information, every arm on
        #: every signal - and from real closes.
        self.policy = Policy()
        # Attached to whichever strategies read one. A strategy without a
        # policy keeps its class defaults, which are the measured ones - so
        # nothing is ever shaped by a guess, only by a default or by evidence.
        for engine in self.strategies:
            if hasattr(engine, "policy"):
                engine.policy = self.policy
        #: Unresolved intents dropped for want of room. Counted because a
        #: silent eviction is a silent bias - see `MAX_UNTAKEN`.
        self._spilled: int = 0
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
        self._warm_trend()
        self._warm_reach()
        account = await self.broker.connect()
        self.equity = account.equity or account.balance
        self.peak_equity = max(self.peak_equity, self.equity)
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

        await self.replicator.start(sorted(self.specs))
        await self._warm_sessions()
        self._announce_style()
        self._check_gates()
        self._check_order()
        self._check_magics()
        self.guard.roll(self.equity)
        log.info(
            "trading: %s on %s",
            " + ".join(s.name for s in self.strategies),
            ", ".join(sorted(self.specs)),
        )

    def _announce_style(self) -> None:
        """Say which kind of trading is running, and what that turned off.

        Loud because it is the difference between a quiet service and a broken
        one. `TRADING_STYLE=none` produces a process that connects, warms every
        estimator, publishes signals and takes nothing, which looks identical
        to a fault unless it says so.
        """
        if self.stood_down:
            log.info(
                "trading: style=%s - %s stood down (%s)",
                self.settings.style,
                len(self.stood_down),
                ", ".join(sorted(e.name for e in self.stood_down)),
            )
        if not self.strategies:
            log.warning(
                "trading: style=%s leaves no strategies - the service will run and take nothing",
                self.settings.style,
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

        **Zero is exempt, and the distinction is the point.** A floor of zero
        is a gate deliberately switched off, which is what the measurement in
        `research/harness/gates.py` argued for; a floor of 0.08 is a gate
        somebody believes in that does nothing. Warning about both taught the
        reader to ignore the warning, which is worse than not having it - and
        it started doing exactly that the day the edge floor was turned off on
        purpose.
        """
        from ..structures.reactions import MIN_EDGE

        if 0 < self.settings.min_edge <= MIN_EDGE:
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
            if symbol and (feed in self._waiting or self._shadows or self._untaken.get(feed)):
                got = await self._tick(symbol)
                if got is not None:
                    await self._watch_shadows(feed, got)
                    await self._resolve_untaken(feed, got)
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
        # The one thing acted on: how long this took. See
        # `structures.holds` - hold time varies 163x and persists at +0.269,
        # which is the pair of properties that justifies an estimator, and it
        # is multiplied into every stop `stop_hold_scaling` widens.
        interval = str(payload.get("interval") or "")
        seconds = payload.get("seconds")
        if isinstance(seconds, int | float) and seconds > 0:
            self._holds.observe(feed, interval, float(seconds))
        # How far price went into the level, and how far against the trade.
        # The pullback and the stop are questions about these two distances,
        # and both were being answered by constants.
        # Passed only when present. A zero is a real observation - price
        # reached the level and did not go through it, or never went against
        # the trade - and substituting zero for a *missing* field would put
        # those two things in the same sample.
        depth = payload.get("depth_vol")
        excursion = payload.get("excursion_vol")
        if isinstance(depth, int | float) or isinstance(excursion, int | float):
            self._reaches.observe(
                feed,
                interval,
                float(depth) if isinstance(depth, int | float) else None,
                float(excursion) if isinstance(excursion, int | float) else None,
            )
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
        self._quoted_at[feed] = time.time()
        # Accumulate directional pressure. Fed from the quote stream rather
        # than from signals, because signals arrive when a level is touched
        # and the run that matters is the one that happened on the way there.
        #
        # The unit comes from the last signal for this feed, so a feed that has
        # never published one accumulates nothing and the filter reads zero -
        # no refusal. That is the right failure direction, but it is a real
        # blind window and worth naming: the filter is inert on a feed until
        # its first signal arrives. Signals are frequent enough that the window
        # is short, and the alternative is inventing a second volatility
        # estimate here that would disagree with the one everything else uses.
        unit = price_distance(tick.mid, self._vol_bps.get(feed, 0.0), 1.0)
        if unit > 0:
            self._push.setdefault(feed, Cusum()).push(tick.mid, unit, when=when)
            self._ensemble.setdefault(feed, Ensemble()).push(tick.mid, unit, when=when)
        # The paper book holds its own stops, so it has to see the market. When
        # the execution venue *is* the broker they are the same object and this
        # runs once.
        for venue in {id(self.broker): self.broker, id(self.paper): self.paper}.values():
            observed = getattr(venue, "observe", None)
            if observed is not None:
                observed(tick)
        self._quotes_seen[feed] += 1
        self._mark_best(symbol, float(bid), float(ask))

    def _undealable(self, feed: str, spec: SymbolSpec, tick: Tick | None) -> Refusal | None:
        """Whether we can actually deal in this instrument right now.

        Two ways we cannot. No quote at all is the obvious one. The other is a
        shut market, which is not obvious: it keeps its last quote, and the
        broker will still accept an order against it. What it will not do is
        let the position out. A us30 position could not be closed for twenty
        minutes through the index's daily break, and a weekend is that same
        failure for two days.

        `spec.tradable` is no help - it reports whether an instrument is
        enabled, not whether it is trading, and said True throughout.

        This catches a market already shut. A market *about* to shut is the
        harder half and is not covered: the spread gate refuses some of it,
        since spreads widen into a close, and the rest needs session hours we
        do not have.

        **Which clock decides.** The broker's, not ours. `_quoted_at` is fed
        from the quotes bus, which is a consensus of other venues, and they
        keep quoting an instrument our broker has closed - so a us30 order was
        refused with "Market closed" while the consensus feed looked perfectly
        live. The broker's own tick time is the only clock that answers the
        question actually being asked, which is whether *this* broker will let
        a position out. Measured against it on a Friday evening: BTCUSD -2s,
        Australia 200 696s, Wall Street 30 1597s - the same epoch as ours, and
        a clean separation between trading and shut.

        The consensus check stays underneath it as a fallback, for a bridge
        that does not report a tick time. A tick with no usable time is not
        called shut: absence of evidence is not evidence of a closed market,
        the same reason a feed that has never quoted is not called shut.
        """
        if tick is None:
            return Refusal("quote", f"no quote for {spec.symbol}", feed)
        quiet = self._shut_for(feed, tick)
        if quiet is not None:
            return Refusal(
                "shut",
                f"{spec.symbol} last traded {quiet:.0f}s ago - the market is closed, "
                "and a position opened here could not be closed",
                feed,
            )
        return None

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
        feed_name = str(payload.get("feed") or "")
        if vol_bps > 0:
            self._vol_bps[feed_name] = vol_bps
        self._note_push(feed_name, payload)
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
        # Kept whether or not this becomes a trade, because what re-arms after
        # a stop is the signal put back through every gate - not the intent,
        # which has already been proved wrong once at this price.
        self._last_signal[feed] = payload
        # Hand the strategies the accumulated run. Injected here rather than
        # computed in a strategy because it is an accumulation over the whole
        # quote stream and a strategy sees one signal at a time.
        self._hand_over_pressure(feed, payload)
        self._hand_over_trend(feed, payload)
        self._hand_over_hold(feed, payload)
        self._hand_over_reach(feed, payload)

        tick = await self._tick(spec.symbol)
        if refusal := self._undealable(feed, spec, tick):
            return refusal

        positions = await self._positions()
        for engine in self.strategies:
            if not engine.wants(payload):
                continue
            verdict = await engine.consider_async(
                payload,
                spec=spec,
                tick=tick,
                equity=self.equity,
                # What the book already holds, so a trade sharing a currency
                # leg with three open ones is sized for that rather than
                # merely refused at the cap. See `scaling.crowding`.
                positions=positions,
                peak=self.peak_equity,
            )
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
                unconfirmed = await self._rejected_at(verdict, engine)
                if unconfirmed is not None:
                    await self._record_refusal(verdict, unconfirmed, engine.name)
                    return unconfirmed
                parked = await self._park(payload, verdict, engine.name, tick, engine)
                if parked is not None:
                    # Journalled like every other refusal. It was not, so a
                    # resting entry left no record at all: the log said it
                    # happened and the journal showed zero, which makes the one
                    # number that matters - how often a rested entry is
                    # actually filled - impossible to compute.
                    await self._record_refusal(verdict, parked, engine.name)
                    await self._also_wanted(payload, spec, tick, engine.name)
                    return parked
            others = await self._also_wanted(payload, spec, tick, engine.name)
            verdict, agreed = self._agree(verdict, others)
            if agreed:
                sized = lots(
                    spec,
                    equity=self.equity,
                    risk_fraction=self.settings.risk_fraction,
                    stop_distance=abs(verdict.entry - verdict.stop),
                    max_risk_money=self.settings.max_risk_money,
                )
                if not sized.ok:
                    return Refusal("size", sized.reason, feed)
                verdict = replace(verdict, volume=sized.volume, risk_money=sized.risk_money)
                log.info(
                    "trading: %s %s agreed by %s - stop %.5g target %.5g, %g lots",
                    verdict.side,
                    verdict.feed,
                    " + ".join([engine.name, *agreed]),
                    verdict.stop,
                    verdict.target,
                    verdict.volume,
                )
            return await self.take(verdict, engine.name)
        return None

    def _agree(self, taken: Intent, others: list[tuple[str, Intent]]) -> tuple[Intent, list[str]]:
        """Rebuild a trade from what the strategies that agreed with it wanted.

        Agreement is worth something, and the useful thing to do with it is
        **not** to bet more. Two strategies on one signal is one idea found
        twice, so sizing up on agreement doubles a position on a single
        thesis - which is what the per-instrument limit exists to prevent.

        What agreement can buy is a better-built trade. Among the strategies
        that wanted the same side:

        * the **furthest** stop, because being stopped before the move arrived
          is the failure this session measured most - six of twelve stopped
          trades later reached their target;
        * the **nearest** target, because the same measurement said unreached
          targets are what a wide stop costs.

        That is the combination most likely to resolve as a win, and it is
        deliberately the *worst* reward-to-risk of the ones on offer - which
        `min_reward_to_risk` then judges on its merits. If the safest version
        of a trade cannot clear the floor, that is worth knowing rather than
        trading the flattering version instead.

        Money at risk is unchanged: a wider stop is re-sized into fewer lots by
        `lots`, so the account never notices the difference.
        """
        least = self.settings.consensus_min
        # `< 2` and not `<= 0`: a consensus of one is the trade itself, and a
        # threshold of zero read as "off" in the setting's own description
        # while the arithmetic made it "always on" - `len(agreed) + 1 < 0` is
        # never true. It shipped that way and fired in production within
        # minutes of being deployed disabled.
        if least < 2:
            return taken, []
        agreed = [(n, i) for n, i in others if i.side is taken.side]
        if len(agreed) + 1 < least:
            return taken, []

        sign = taken.side.sign
        stop = min((i.stop for _, i in agreed), default=taken.stop, key=lambda p: p * sign)
        stop = taken.stop if (taken.stop - stop) * sign < 0 else stop
        target = min((i.target for _, i in agreed), default=taken.target, key=lambda p: p * sign)
        target = taken.target if (target - taken.target) * sign > 0 else target
        return replace(taken, stop=stop, target=target), [n for n, _ in agreed]

    async def _also_wanted(
        self, payload: dict[str, Any], spec: SymbolSpec, tick: Tick, taken_by: str
    ) -> list[tuple[str, Intent]]:
        """Ask every other strategy what it would have done with this signal.

        The running order decides who trades, and it also decides **who is ever
        asked** - so the strategies never see the same signals and their
        records are not comparable. `level-scalp` scored +1.01R over two
        trades and `fade-to-value` -0.75R over ten, on two different streams,
        which is not a comparison however it is printed.

        Trading them in parallel would fix the comparison and multiply the risk
        - two strategies on one signal is one idea found twice, which is what
        the per-instrument limit exists to prevent. So they are *evaluated* in
        parallel and one of them trades: every other strategy is asked, and
        what it wanted is written down beside what actually happened.

        Nothing here places an order. It costs one arithmetic pass per
        strategy per signal, and it buys the only honest way to rank them.
        """
        wanted_by: list[tuple[str, Intent]] = []
        if not self.settings.evaluate_all:
            return wanted_by
        for engine in self.strategies:
            if engine.name == taken_by or not engine.wants(payload):
                continue
            try:
                # No `positions` here, deliberately. This is the shadow
                # evaluation - what each *other* strategy would have done with
                # the same signal - and crowding is a fact about the book
                # rather than about the strategy. Applying it would make the
                # comparison depend on what happened to be open, which is the
                # opposite of what a comparison is for.
                verdict = await engine.consider_async(
                    payload, spec=spec, tick=tick, equity=self.equity, peak=self.peak_equity
                )
            except Exception as exc:
                # A shadow evaluation must never break a real trade.
                log.debug("trading: %s could not be evaluated: %s", engine.name, exc)
                continue
            wanted = isinstance(verdict, Intent)
            if wanted:
                wanted_by.append((engine.name, verdict))
                # Followed forward from here, so the record says what this
                # strategy would have *got* and not only what it wanted. See
                # `Untaken`: without this the ranking has to be recomputed by
                # hand off stored bars, which is how it was done the first time.
                self._remember_untaken(
                    str(payload.get("feed") or ""),
                    engine.name,
                    verdict,
                    str(payload.get("interval") or ""),
                    engine.hold_for(str(payload.get("interval") or "")),
                    tick.time,
                )
            await observe(
                self.journal,
                f"{engine.name} would have {'taken' if wanted else 'passed'} {payload.get('feed')}",
                rationale=(verdict.reason if wanted else f"{verdict.gate}: {verdict.detail}"),
                actor="trading",
                context={
                    "shape": "considered",
                    "strategy": engine.name,
                    "taken_by": taken_by,
                    "wanted": wanted,
                    "gate": "" if wanted else verdict.gate,
                    # The prices it would have used, so the same scoring that
                    # runs over real trades can run over these.
                    "entry": round(verdict.entry, 8) if wanted else 0.0,
                    "stop": round(verdict.stop, 8) if wanted else 0.0,
                    "target": round(verdict.target, 8) if wanted else 0.0,
                    "feed": str(payload.get("feed") or ""),
                    "interval": str(payload.get("interval") or ""),
                },
                tags=(str(payload.get("feed") or ""), engine.name, "considered"),
            )
        return wanted_by

    # --------------------------------------------------------------- trading

    def _ref_for(self, position: Position) -> str:
        """The journal entry for the decision that opened this position.

        **Why this is needed at all.** `_settle` writes an outcome against
        `live.ref`, and `journal.outcome` refuses a record with no parent -
        correctly, since an outcome that cannot be paired with its decision
        teaches nothing. But `ref` is handed over through `_pending`, which is
        only set for a position opened in *this* run. Anything adopted after a
        restart therefore carried an empty ref and vanished from the record on
        close.

        **The bias that made it worth fixing rather than noting.** What went
        missing was precisely the trades that lived long enough to span a
        deploy - so every figure taken from the journal was computed on a set
        that over-represented short trades, including the per-strategy table
        and the stop cost this repository has been reasoning from.

        Matched on symbol and side, newest first, and only against decisions
        that are not already the parent of an outcome - so a position cannot
        adopt the record of an earlier, settled trade on the same instrument.
        Returns "" when nothing matches, which restores the old behaviour for
        that position rather than guessing.
        """
        path = getattr(self.journal, "path", None)
        if path is None:
            return ""
        try:
            from ..journal import read as read_journal

            decisions = read_journal(path, kind="decision", actor="trading", limit=400)
            outcomes = read_journal(path, kind="outcome", actor="trading", limit=400)
        except Exception as exc:
            log.debug("trading: could not look up a ref for #%d: %s", position.ticket, exc)
            return ""

        settled = {entry.parent for entry in outcomes if entry.parent}
        want = str(position.side)
        for entry in decisions:  # newest first
            context = entry.context or {}
            if context.get("symbol") != position.symbol:
                continue
            if str(context.get("side") or "") != want:
                continue
            if entry.id in settled:
                continue
            log.info(
                "trading: adopted #%d and recovered its decision from the journal",
                position.ticket,
            )
            return entry.id
        return ""

    async def _warm_sessions(self) -> None:
        """Learn each instrument's trading week from where its bars are.

        The broker does not publish its hours - see `sessions.py` - so they are
        read off fifteen-minute bars, which is enough resolution for the daily
        break and the Friday close and cheap enough to fetch for every symbol
        at start-up.

        Failure is not fatal, here as in `_warm_trend` and `_warm_reach`. An
        instrument whose bars cannot be read simply has no session opinion, and
        the gate stands aside for it rather than refusing everything.
        """
        want = self.settings.session_bars
        if want <= 0:
            return
        span = float(SESSION_INTERVAL_S)
        gate = asyncio.Semaphore(SESSION_FETCHES)

        async def learn(symbol: str) -> None:
            async with gate:
                try:
                    bars = await self.broker.bars(symbol, SESSION_INTERVAL, want)
                except BrokerError as exc:
                    log.debug("trading: no session bars for %s: %s", symbol, exc)
                    return
            times = [bar.time for bar in bars if bar.time > 0]
            if not times:
                log.debug("trading: no bar times for %s", symbol)
                return
            self._sessions.learn(symbol, times, span)

        started = time.time()
        await asyncio.gather(
            *(learn(spec.symbol) for spec in self.specs.values()), return_exceptions=True
        )
        took = time.time() - started
        known = self._sessions.learned
        if known:
            always = sum(1 for sch in self._sessions.by_symbol.values() if sch.always)
            log.info(
                "trading: session hours learned for %d of %d instruments in %.1fs - %d never close",
                known,
                len(self.specs),
                took,
                always,
            )
        else:
            log.info("trading: no session hours learned - the closing gate stands aside")

    def _warm_reach(self) -> None:
        """Rebuild the hold and reach estimates from the journal before trading.

        The same problem `_warm_trend` was written for, and the same shape.
        These need a sample **per feed and interval** - twenty resolutions for
        a reach quantile - while production publishes on the order of
        twenty-seven signals in fifteen minutes across every series there is.
        A given pair may see one an hour, so a cold estimator is not merely
        cold: it is unavailable for most of a day, and every deploy resets it.

        Verified the way `_warm_trend` was not: the first check after shipping
        the reach estimators found `reach_depth_vol` and `reach_stop_vol`
        absent from every decision, on a container minutes old.

        Failure is not fatal. Starting cold is what happened before this
        existed, and a trading service that will not boot because it could not
        read history is worse than one that starts without an opinion.
        """
        path = getattr(self.journal, "path", None)
        if path is None:
            return
        try:
            from ..journal import read as read_journal

            rows = read_journal(path, kind="outcome", actor="structures", limit=8000)
        except Exception as exc:
            log.debug("trading: could not warm the reach estimates: %s", exc)
            return

        warmed = 0
        # Oldest first, so a bounded window keeps what is recent rather than
        # the stalest rows of the batch - the trap `_warm_trend` documents.
        for entry in reversed(rows):
            context = getattr(entry, "context", None) or {}
            feed, interval = context.get("feed"), context.get("interval")
            if not feed or not interval:
                continue
            seconds = context.get("seconds")
            if isinstance(seconds, int | float) and seconds > 0:
                self._holds.observe(str(feed), str(interval), float(seconds))
            depth, excursion = context.get("depth_vol"), context.get("excursion_vol")
            if isinstance(depth, int | float) or isinstance(excursion, int | float):
                self._reaches.observe(
                    str(feed),
                    str(interval),
                    float(depth) if isinstance(depth, int | float) else None,
                    float(excursion) if isinstance(excursion, int | float) else None,
                )
                warmed += 1
        if warmed:
            log.info(
                "trading: reach warmed from %d resolutions - %d series ready, %d hold estimates",
                warmed,
                self._reaches.ready(),
                sum(1 for h in self._holds.by_key.values() if h.expected is not None),
            )

    def _warm_trend(self) -> None:
        """Rebuild the trend windows from the journal before trading starts.

        Without this the measure is not merely cold, it is effectively
        unavailable. A reading needs three prior levels on the **same feed and
        interval** and the window wants twelve, while production publishes on
        the order of twenty-seven signals in fifteen minutes across every feed
        and interval there is - so a given pair may see one an hour. Every
        deploy would reset that to nothing, and on a day of frequent deploys
        the context would never once be available to size a trade.

        The replay that measured this effect ran over resolutions accumulated
        across days, which hid the problem completely: there, twelve prior
        levels per pair is ordinary.

        Failure here is not fatal. A cold start is what happened before this
        existed, and a trading service that will not boot because it could not
        read history is worse than one that starts without an opinion.
        """
        path = getattr(self.journal, "path", None)
        if path is None:
            return
        try:
            from ..journal import read as read_journal

            rows = read_journal(path, kind="outcome", actor="structures", limit=6000)
        except Exception as exc:
            log.debug("trading: could not warm the trend context: %s", exc)
            return

        warmed = 0
        # Oldest first, because the window is a bounded deque and keeps what
        # was appended *last*. Fed newest-first it would retain the twelve
        # oldest levels of the batch and discard everything recent, which is
        # the exact opposite of the intent and would still produce a
        # confident-looking number.
        #
        # Not for the reason it first appears: efficiency is order-invariant.
        # Reversing a sequence flips the sign of the net displacement but not
        # its magnitude, and leaves the distance travelled untouched, so the
        # ratio is identical either way. Only which levels survive the deque
        # depends on the order.
        for entry in reversed(rows):
            context = getattr(entry, "context", None) or {}
            feed, interval = context.get("feed"), context.get("interval")
            level = context.get("level")
            if not feed or not interval or not isinstance(level, int | float):
                continue
            self._trend.setdefault((str(feed), str(interval)), Trend()).observe(float(level))
            warmed += 1
        if warmed:
            ready = sum(1 for t in self._trend.values() if t.efficiency is not None)
            log.info(
                "trading: trend context warmed from %d levels - %d of %d pairs ready",
                warmed,
                ready,
                len(self._trend),
            )

    def _hand_over_reach(self, feed: str, payload: dict[str, Any]) -> None:
        """Attach how far price reaches here, into the level and against a trade.

        Recorded rather than acted on, like the hold estimate beside it.
        `pullback_fraction` and `min_stop_vol` still decide; these say what the
        instrument has actually done, so the journal can show whether the
        constants were in the right place before anything is moved.
        """
        interval = str(payload.get("interval") or "")
        entry = self._reaches.entry_at(feed, interval)
        features = payload.get("features")
        if not isinstance(features, dict):
            return
        if entry is not None:
            features["reach_depth_vol"] = entry
        risk = features.get("risk_vol")
        stop = self._reaches.stop_at(
            feed, interval, risk_vol=float(risk) if isinstance(risk, int | float) else 0.0
        )
        if stop is not None:
            features["reach_stop_vol"] = stop

    def _hand_over_hold(self, feed: str, payload: dict[str, Any]) -> None:
        """Attach how long a touch here usually takes, when that is known.

        Recorded on the decision rather than acted on. The estimator is worth
        having - hold time varies 163x and persists - but it has never sized a
        stop, and a quantity that moves money should be visible in the journal
        for a while before it does. `stop_hold_scaling` still scales by the
        strategy's configured hold.
        """
        expected = self._holds.expected(feed, str(payload.get("interval") or ""))
        if expected is None:
            return
        features = payload.get("features")
        if isinstance(features, dict):
            features["expected_hold_s"] = expected

    def _hand_over_trend(self, feed: str, payload: dict[str, Any]) -> None:
        """Attach the trend context, then fold this level into it.

        **Read before observe, and the order is the whole correctness of it.**
        The level being decided must not be inside the window it is judged
        against, or the measure describes the decision instead of predicting
        it - which is the trap `push_vol` fell into, where a quantity signed by
        the outcome was scored against the outcome.
        """
        # Out of `features`, which is where every strategy reads it from and
        # therefore where it actually is. Read from the top of the payload
        # this returned early on every signal, so no reading was ever injected
        # *and* the window never grew - the measure was inert twice over while
        # the warm start reported 121 of 140 pairs ready.
        #
        # The third time today a value has been read from or written to the
        # wrong level of this payload. `features` is the contract; the top
        # level carries routing.
        features = payload.get("features")
        level = features.get("level") if isinstance(features, dict) else None
        if not isinstance(level, int | float):
            return
        interval = str(payload.get("interval") or "")
        context = self._trend.setdefault((feed, interval), Trend())

        ratio = context.efficiency
        if ratio is not None:
            features["efficiency"] = ratio
        context.observe(float(level))

    def _note_push(self, feed: str, payload: dict[str, Any]) -> None:
        """Keep a running estimate of how far this instrument moves, and size
        the momentum filter to it.

        Volatility units already normalise for how much an instrument moves per
        bar, and that is not enough: the *push* it makes once it starts moving
        varies on top of that, 1.66v on eurusd against 2.75v on brent. A single
        threshold is late for one and noisy for the other.

        Measured over 59,982 resolutions, the fixed 2.0v was silent through
        **47.5% of all moves** and confirmed after 2.0v of a 2.07v median push
        - the end of the move, which is no use for timing an entry.

        A slow EWMA, because this is a property of the instrument rather than
        of the moment; the threshold should not lurch because one call carried
        a big forecast.
        """
        if not feed:
            return
        push = abs(float(payload.get("features", {}).get("expected_push_vol") or 0.0))
        if push <= 0 or push > self.settings.max_push_vol:
            return
        seen = self._push_vol.get(feed)
        self._push_vol[feed] = push if seen is None else seen * (1 - PUSH_DECAY) + push * PUSH_DECAY
        group = self._ensemble.get(feed)
        if group is not None:
            group.threshold = adaptive_threshold(self._push_vol[feed])

    def _hand_over_pressure(self, feed: str, payload: dict[str, Any]) -> None:
        """Put the accumulated run where the strategies will actually see it.

        Into `features`, not the top level. `_features` reads
        `payload["features"]` and nothing else, so a top-level key is invisible
        to every strategy - the gate reads zero and refuses nothing while
        looking configured. That is what the first version of this did, and
        the test written to catch exactly that asserted the wrong dictionary
        and passed alongside it.
        """
        running = self._push.get(feed)
        if running is None:
            return
        features = payload.setdefault("features", {})
        if not isinstance(features, dict):
            return
        features["pressure_vol"] = running.pressure
        # The ensemble's own reading, alongside rather than instead of the
        # single filter: `require_turn_vol` is calibrated against that one, and
        # swapping the number underneath a threshold silently recalibrates it.
        group = self._ensemble.get(feed)
        if group is not None and group.ready:
            features["momentum_vol"] = group.pressure
            features["momentum_agree"] = group.agreement
            features["momentum_ready"] = float(group.ready)

    async def _rejected_at(self, intent: Intent, engine: Strategy | None = None) -> Refusal | None:
        """Refuse a trade nothing has confirmed yet. Either witness will do.

        A level says where a trade is worth taking and is silent about when.
        The gap between those is where this book loses money: an `inverse` buy
        on gold took its stop at 4591 and then ran to its target at 4604, and
        23 of the first 32 trades were stopped, several later reaching the
        price they were aiming at. Entering because price is *near* a level,
        while the level is still being tested, is a bet that the test is over.

        Two ways to see that it is, and **either is enough**:

        **The move turned.** After price has come back to the level, momentum
        crossing back in the trade's favour says the run against it has ended.
        Only meaningful after a pullback - momentum at a level is adverse by
        construction, because price arriving at support is falling, which is
        what arriving means.

        **A candle rejected the level.** The last closed bar reached the level
        and closed away from it - a hammer, a shooting star, an engulfing
        reversal.

        These are the same claim measured differently. A hammer *is* a momentum
        reversal compressed into one bar; the accumulator reads the same event
        tick by tick. The candle is stronger evidence and has to wait for a
        close, which on a 4h chart is a long time to hold an opinion. Requiring
        both would refuse a fast turn for not yet having a bar to show for
        itself, and refuse a clean rejection for happening inside one bar
        rather than across several. So it is a disjunction, and the trade is
        confirmed by whichever arrives.
        """
        wants_turn = self.settings.require_turn_vol > 0
        wants_candle = self.settings.require_candle
        if not (wants_turn or wants_candle):
            return None

        # A swing may insist on both. The disjunction is right for a scalp,
        # which cannot wait four hours for a bar to close and would otherwise
        # refuse a clean fast turn for having no candle yet. A swing has the
        # time, and an origin price merely touched is not one that rejected it.
        both = bool(engine and engine.needs_both_witnesses)
        # Momentum leads, and its absence is a refusal rather than a pass. See
        # `Strategy.momentum_leads` for the leak this closes: the turn is read
        # only after a pullback, so on any other entry the candle was the only
        # witness asked and carried the trade alone.
        leads = bool(engine and engine.momentum_leads and wants_turn)
        both = both or leads

        asked: list[str] = []
        held: list[str] = []
        # The turn. Skipped entirely before a pullback, where the reading means
        # the opposite thing - so on a straight-to-market entry this witness is
        # not merely unsatisfied, it is not applicable.
        if wants_turn and (intent.features.get("after_pullback") or leads):
            asked.append("turn")
            pressure = float(intent.features.get("pressure_vol") or 0.0)
            turned = pressure if intent.side is Side.BUY else -pressure
            wanted = self._turn_wanted(intent.feed)
            if turned >= wanted:
                log.info(
                    "trading: %s %s confirmed - turned %.2fv after the pullback",
                    intent.side,
                    intent.feed,
                    turned,
                )
                if not both:
                    return None
                held.append("turn")
            elif leads:
                # Refused here rather than folded into the "wants both" message
                # below, because the reason is different and the operator
                # should be able to tell them apart: this is not "one of two
                # witnesses is missing", it is "the thing that has to come
                # first did not happen".
                return Refusal(
                    "momentum",
                    f"momentum leads here and has not turned: {turned:+.2f}v "
                    f"against the {wanted:.2f}v it needs",
                    intent.feed,
                )

        if wants_candle:
            asked.append("candle")
            found = await self._candle_at(intent, engine)
            if found:
                log.info("trading: %s %s confirmed by a %s", intent.side, intent.feed, found)
                if not both:
                    return None
                held.append("candle")

        if not asked:
            return None
        if both:
            missing = [w for w in asked if w not in held]
            if not missing:
                return None
            return Refusal(
                "unconfirmed",
                f"{'/'.join(held) or 'nothing'} confirmed the level but "
                f"{'/'.join(missing)} did not, and this strategy wants both",
                intent.feed,
            )
        witnesses = "/".join(asked)
        return Refusal("unconfirmed", f"nothing confirmed the level ({witnesses})", intent.feed)

    async def _candle_at(self, intent: Intent, engine: Strategy | None = None) -> str:
        """The pattern rejecting this level on the last closed bar, or "".

        An unavailable answer is an empty one, not an exception: if the broker
        serves no bars the trade is unconfirmed, which is exactly what the gate
        is for. Treating missing data as a pass would make this silently
        inactive on every instrument whose bars fail, which is the failure mode
        that looks like working code.
        """
        # A swing enters on 1h and wants the 4h rejection: the entry can be
        # fast while the evidence is slow. A scalp names nothing and is judged
        # on the bar it is entering on.
        interval = (engine.candle_interval if engine else "") or intent.interval
        bars = await self.execution.bars(intent.symbol, interval, count=3)
        if len(bars) < 2:
            return ""
        level = float(intent.features.get("level") or intent.entry)
        vol_bps = self._vol_bps.get(intent.feed, 0.0)
        tolerance = price_distance(level, vol_bps, self.settings.candle_tolerance_vol)
        return confirms(bars, level, intent.side is Side.BUY, tolerance)

    async def _park(
        self,
        payload: dict[str, Any],
        intent: Intent,
        by: str,
        tick: Tick,
        engine: Strategy | None = None,
    ) -> Refusal | None:
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
        # A strategy that insists on a resting entry says so itself. Depending
        # on the deployment's setting would make "does this wait for its price"
        # a property of how the box is tuned rather than of the strategy, and a
        # swing entry that quietly became a market order because a global was
        # zeroed is not the same trade.
        own = getattr(engine, "pullback_fraction", 0.0) if engine is not None else 0.0
        fraction = own or self.settings.pullback_fraction

        # The small, ordinary improvement, tried before the deep one. Resting a
        # fraction of a unit nearer the level is a different bet from waiting
        # for the sweep edge: 189 signals of 813 reached that wait and none of
        # them parked, because by then the fill was already past it.
        edge = await self._edge_entry(payload, intent, tick, by)
        if edge is not None:
            return edge

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
            await self._withdraw(held, "the window expired")
            log.info("trading: %s expired waiting for %.5g", feed, held.trigger)
            return None
        # The judgement half, exercised while the reflex half waits. A broker
        # order cannot change its mind, so anything that would refuse the trade
        # now has to reach in and take it back - otherwise the one arrangement
        # this was meant to avoid is the one it creates: a fill on a setup that
        # had already stopped being worth taking.
        turned = self._turned_against(held, tick)
        if turned:
            self._waiting.pop(feed, None)
            await self._withdraw(held, turned)
            log.info("trading: %s dropped while waiting - %s", feed, turned)
            return None

        price = tick.entry(held.side)
        if (price - held.trigger) * held.side.sign > 0:
            return None  # not there yet
        self._waiting.pop(feed, None)
        # Taken back before the signal is re-asked: if the gates still pass we
        # fill at market here, and if they do not the order must already be
        # gone. Leaving it would fill a setup this system just refused.
        await self._withdraw(held, "price arrived, deciding here")
        log.info("trading: %s reached %.5g - reconsidering", feed, held.trigger)
        # Asked again rather than resurrected: a setup that stopped being worth
        # taking while it waited is refused on arrival like any other.
        #
        # Marked as post-pullback, which is what lets `require_turn_vol` apply
        # here and only here. The same momentum reading means "arriving at the
        # level" before the wait and "the fall has not finished" after it.
        woken = held.payload.setdefault("features", {})
        if isinstance(woken, dict):
            woken["after_pullback"] = 1.0
        return await self.on_signal(held.payload, observe=False, park=False)

    async def _copy_to_followers(self, intent: Intent, by: str) -> None:
        """Replicate a filled decision onto every other terminal.

        **Risk travels, volume does not.** Each follower re-sizes against its
        own equity, so the same decision is the same *fraction* of each account
        rather than the same number of lots - which on a smaller account would
        be several times the risk the plan authorised. See `replicate.py`.

        Never raises and never blocks the primary. The trade that matters is
        already on; a follower that cannot take it is a fact to record, not a
        reason to unwind an account that did nothing wrong.
        """
        if not self.replicator.live:
            return
        made = await self.replicator.copy(
            intent,
            risk_fraction=self.settings.risk_fraction,
            magic=magic_for(self.settings.magic, by),
            by=by,
            max_risk_money=self.settings.max_risk_money,
            slippage=self.settings.stop_slippage,
        )
        for copied in made.results:
            await self.journal.write(
                observe(
                    "trading",
                    f"copied {intent.title} to {copied.account}",
                    context={
                        "account": copied.account,
                        "ok": copied.ok,
                        "detail": copied.detail,
                        "volume": copied.volume,
                        "ticket": copied.ticket,
                        "feed": intent.feed,
                        "by": by,
                    },
                )
            )

    async def _edge_entry(
        self, payload: dict[str, Any], intent: Intent, tick: Tick, by: str = ""
    ) -> Refusal | None:
        """Hold the order a fraction of a unit better than the quote.

        The trade is worth taking at the level; it is worth more a fraction
        nearer it. This waits at that price rather than paying the spread to
        cross now, and the wait is short by construction - a quarter of a unit
        is inside the noise of any instrument that is moving at all.

        **Held here, not sent to the broker.** The bridge has
        `POST /orders/pending`, and using it would put the stop and target on
        the terminal between placement and fill, where nothing here can adjust
        them - and where a market that gapped through would fill at a price
        this never agreed to. The same book that already re-arms parked signals
        watches this one.

        Skipped when the fill is already better than the price being waited
        for, which is the common case on a fast move: there is nothing to
        improve and waiting would only risk the trade.
        """
        want = self.settings.entry_edge_vol
        if want <= 0:
            return None
        unit = price_distance(intent.entry, _vol_of(payload), 1.0)
        if unit <= 0:
            return None
        better = intent.entry - intent.side.sign * want * unit
        # Already there or better: nothing to wait for.
        if (intent.entry - better) * intent.side.sign <= 0:
            return None
        if (tick.entry(intent.side) - better) * intent.side.sign <= 0:
            return None
        bars = SECONDS.get(intent.interval, 0.0)
        window = (
            bars * self.settings.pullback_bars if bars else (intent.hold or self.settings.max_hold)
        )
        self._waiting[intent.feed] = Waiting(
            payload=payload,
            feed=intent.feed,
            trigger=better,
            side=intent.side,
            until=tick.time + window,
        )
        self._was_parked[intent.feed] = True
        log.info(
            "trading: %s %s resting at %.5g - %.2fv better than the %.5g on offer",
            intent.side,
            intent.feed,
            better,
            want,
            intent.entry,
        )
        await self._leave_with_broker(intent, by, better, tick.time + window)
        return Refusal("waiting", f"holding out for {better:.5g}", intent.feed)

    def _turned_against(self, held: Waiting, tick: Tick) -> str:
        """Why this wait should be abandoned now, or "" to keep waiting.

        Only conditions that would refuse the trade outright. A signal that has
        merely aged is handled by `until`, and one whose numbers moved is
        handled by asking the strategy again on arrival - this is for the cases
        where there is no point arriving at all.
        """
        shut = self._shut_for(held.feed, symbol=self._symbol_of.get(held.feed, ""))
        if shut is not None:
            return f"the market shut {shut:.0f}s ago"
        if self.context.drifting(held.feed):
            return "the regime changed under it"
        # `widened` is already zero below its own threshold, so this reads
        # "several venues at once" rather than "any venue".
        if self.context.widened(held.feed):
            return "the venues went wide together"
        # Against the **target**, which is what `risk.py` measures it against
        # when the same setting refuses an entry. This used to divide by the
        # distance price still had to travel to reach `trigger`, under a local
        # named `risk` that made it read as the trade's risk. It was not: that
        # gap shrinks to nothing as price arrives - which is the event the
        # order is waiting for - so the threshold shrank with it and any spread
        # at all cleared the bar. This check runs before the arrival check
        # below, so every resting order was withdrawn on the tick it would
        # have filled. Measured 2026-09-01: nine rests, no fills, no
        # expiries, every resolution a spread withdrawal.
        #
        # Silent with no resting order, and that is not a gap. The point of
        # this method is to reach in and take back the **broker's** order,
        # which cannot change its mind; when there is none, arrival re-asks
        # every gate through `on_signal` and a wide spread is refused there.
        spread = tick.spread
        resting = held.resting
        if spread > 0 and self.settings.max_spread_fraction > 0 and resting is not None:
            reward = resting.reward
            if reward > 0 and spread > reward * self.settings.max_spread_fraction:
                return (
                    f"the spread reached {spread / reward:.0%} of the target, "
                    f"limit is {self.settings.max_spread_fraction:.0%}"
                )
        return ""

    async def _leave_with_broker(self, intent: Intent, by: str, at: float, until: float) -> None:
        """Also leave the price with the broker, as a limit order.

        The other half of the hybrid. A poller sees price at its own cadence
        and a deep wick is brief by construction, so the fills most worth
        having are the ones most likely to fall between two reads. The broker
        fills on its own tick.

        Failure here is not fatal and not silent: the local watch is already
        registered, so a rejected order leaves the entry exactly as it was
        before this existed rather than losing it.
        """
        if not self.settings.entry_pending or not self.settings.live:
            return
        held = self._waiting.get(intent.feed)
        if held is None:
            return
        order = Order(
            symbol=intent.symbol,
            side=intent.side,
            volume=intent.volume,
            stop=intent.stop,
            target=intent.target,
            comment=f"till {by or 'scalp'}"[:31],
            magic=magic_for(self.settings.magic, by),
            deviation=self.settings.deviation,
        )
        try:
            result = await self.execution.rest(order, at, until)
        except BrokerError as exc:
            log.warning("trading: could not rest %s with the broker: %s", intent.feed, exc)
            return
        if not result.ok or not result.ticket:
            log.warning("trading: broker refused the resting %s: %s", intent.feed, result)
            return
        held.ticket = result.ticket
        held.resting = intent
        held.by = by
        log.info(
            "trading: %s also left with the broker at %.5g as #%d",
            intent.feed,
            at,
            result.ticket,
        )
        await self._announce_rest(intent, at, by, result.ticket)

    async def _withdraw(self, held: Waiting, why: str) -> None:
        """Take a resting order back off the broker.

        Every path that drops a wait comes through here, because an order left
        behind is one that fills on a setup this system has already refused -
        the exact failure a broker-side limit invites and the reason it is only
        half of the arrangement.
        """
        if not held.ticket:
            return
        ticket = held.ticket
        try:
            await self.execution.withdraw(ticket)
            log.info("trading: withdrew #%d on %s - %s", ticket, held.feed, why)
        except BrokerError as exc:
            log.warning("trading: could not withdraw #%d on %s: %s", ticket, held.feed, exc)
        held.ticket = 0
        if held.resting is not None:
            await self._announce_rest(held.resting, held.trigger, held.by, ticket, gone=why)

    def _still_building(self, live: Live) -> bool:
        """Whether momentum is gathering behind this trade despite the silence.

        A trade that has not moved is two different situations. One is dead:
        nothing is happening and the capital should go elsewhere, which is what
        the stale clock is for. The other is coiling - price has not travelled
        yet and the sub-hour timeframes are lining up behind it - and closing
        that one is closing the setup immediately before it works.

        The clock alone cannot tell them apart, because it only reads distance
        travelled. The momentum ensemble can: `agreement` is the share of
        timeframes pointing the trade's way, and it turns before the move
        rather than after it.

        Only a **majority behind the trade** buys more time, and only until the
        hold clock ends it anyway. A silent instrument with no reading is not
        given the benefit - unknown is not the same as building.
        """
        group = self._ensemble.get(live.intent.feed)
        if group is None or not group.ready:
            return False
        facing = group.agreement * live.intent.side.sign
        if facing < STALE_AGREE:
            return False
        log.info(
            "trading: #%d has not moved but %.0f%% of the fast timeframes are behind it",
            live.position.ticket,
            facing * 100,
        )
        return True

    def _stale_after(self, live: Live) -> float:
        """How long this instrument gets before a trade counts as going nowhere.

        Adaptive above a fixed floor, for the reason the momentum threshold is:
        the setting is one number and hold time is not. Measured across this
        book it varies **163-fold** between series and it persists, which is
        exactly the shape that makes an average useless - a fixed 300s is most
        of a fast series' whole life and a fraction of a slow one's.

        `STALE_HOLDS` times the series' own expected hold. A trade that has not
        moved after twice as long as this instrument usually takes to resolve
        is genuinely going nowhere; the same silence after 300 seconds may be
        an instrument that has not started.

        The estimator is the one already published on every decision as
        `expected_hold_s`, so this is the first thing to act on a number that
        has been visible in the journal for a while - which is the order this
        repository does it in.

        `stale_after` stays the floor: it still means "never sooner than this",
        and a series with no estimate yet behaves exactly as before.
        """
        floor = self.settings.stale_after
        if floor <= 0:
            return 0.0
        expected = self._holds.expected(live.intent.feed, live.intent.interval)
        if not expected or expected <= 0:
            return floor
        return max(floor, STALE_HOLDS * float(expected))

    def _turn_wanted(self, feed: str) -> float:
        """How much of a turn this instrument has to show, in volatility units.

        Adaptive above a fixed floor, for the reason the CUSUM threshold is:
        volatility units normalise how far an instrument moves per bar, and the
        push it makes once moving varies on top of that - 1.66v on eurusd
        against 2.75v on brent. A turn worth 0.5v is most of a eurusd move and
        a fifth of a brent one, so one number asks two different questions.

        `require_turn_vol` is the **floor**, not the value: the setting still
        says "never accept less than this", and the instrument raises it when
        its own moves are larger. A feed with no push estimate yet gets the
        floor, which is the setting behaving exactly as it did before.
        """
        floor = self.settings.require_turn_vol
        push = self._push_vol.get(feed, 0.0)
        if push <= 0:
            return floor
        return adaptive_threshold(push, share=TURN_SHARE, floor=floor, ceiling=TURN_CEILING)

    def _closing_soon(self, intent: Intent) -> Refusal | None:
        """Refuse a trade whose hold does not fit before its market closes.

        The other half of a shut market. `_shut_for` catches one that has
        already closed, by noticing the broker has stopped quoting; nothing
        caught one about to close, and that is the case that costs money. A
        position opened at 20:52 on a Friday cannot be closed until Sunday
        night: the hold clock keeps running while the market does not, and
        `max_hold_multiple` does not save it because the shut branch of the
        deferral has no cap.

        Judged against **this trade's own hold**, not a fixed cutoff, because
        that is the thing that has to fit. A thirty-minute hold needs thirty
        minutes of session; a scalp with a two-minute hold is perfectly fine at
        the same moment, and a blanket "no trading after 20:30" would refuse
        both.

        Stands aside when the hours were not learned, and for instruments that
        never close. See `sessions.py` for how little this claims.
        """
        margin = self.settings.session_margin
        if margin <= 0:
            return None
        left = self._sessions.closes_in(intent.symbol)
        if left is None:
            return None
        hold = intent.hold or self.settings.max_hold
        if left >= hold + margin:
            return None
        return Refusal(
            "closing",
            f"{intent.symbol} closes in {left:.0f}s and this trade wants "
            f"{hold:.0f}s - it could not be closed before the session ends",
            intent.feed,
        )

    async def take(self, intent: Intent, by: str = "") -> Intent | Refusal:
        """Send an order, or say why it was not sent."""
        if refusal := self._closing_soon(intent):
            log.info("trading: %s - %s", intent.title, refusal.detail)
            return refusal
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
        # Only after the primary has actually filled. Copying a decision the
        # account it was made for refused would put the position everywhere
        # except where it was decided.
        await self._copy_to_followers(intent, by)
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

    def _remember_marks(self) -> None:
        """Write the extremes for whatever is still open.

        Once a heartbeat, not once a quote: the cost of a restart is then
        bounded to a minute of high-water rather than the whole trade, and the
        file stays a few hundred bytes.

        Never raises. A desk that cannot write a convenience file must keep
        trading - `structures` takes the same line on its own state, and for
        the same reason.
        """
        try:
            self._marks.parent.mkdir(parents=True, exist_ok=True)
            live = set(self.open)
            payload = {
                "best": {str(k): v for k, v in self._best.items() if k in live},
                "worst": {str(k): v for k, v in self._worst.items() if k in live},
            }
            self._marks.write_text(json.dumps(payload))
        except Exception as exc:  # pragma: no cover - a full disk, a bad path
            log.debug("trading: could not write %s: %s", self._marks, exc)

    def _recall_marks(self) -> None:
        """Read them back, keeping only tickets the broker still reports.

        A ticket that has closed since the file was written is dropped rather
        than carried: `_settle` reads these to record `best_r`, and a stale
        entry would attach one trade's excursion to another's ticket if the
        broker ever reused a number.
        """
        try:
            payload = json.loads(self._marks.read_text())
        except Exception:
            return
        live = set(self.open)
        kept = 0
        for name, into in (("best", self._best), ("worst", self._worst)):
            for raw, value in (payload.get(name) or {}).items():
                try:
                    ticket = int(raw)
                except (TypeError, ValueError):
                    continue
                if ticket in live and isinstance(value, int | float):
                    into.setdefault(ticket, float(value))
                    kept += 1
        if kept:
            log.info("trading: recovered %d high-water mark(s) across the restart", kept)

    async def sweep(self) -> None:
        """The heartbeat: roll the day, reconcile, and time out stale scalps."""
        if not await self.broker.healthy():
            log.warning("trading: the terminal is not answering; nothing will be sent")
            return

        account = await self.broker.account()
        self.equity = account.equity or self.equity
        self.guard.roll(self.equity)
        await self._reconcile()
        # After reconcile, so `self.open` is what the broker actually reports -
        # and before `_manage`, so a position adopted this pass is judged on
        # the excursion it really made rather than on the price it happens to
        # be at now.
        if not self._recalled:
            self._recalled = True
            self._recall_marks()
        await self._orphans()
        await self._manage()
        self._remember_marks()
        await self._expire()
        await self._rearm_stopped()
        self._say_what_it_is_doing()

    async def _orphans(self) -> None:
        """Withdraw resting orders this process is not tracking.

        `_waiting` is in-process memory and the broker's order book is not.
        Every path that drops a wait goes through `_withdraw`, which is the
        right design and covers nothing across a restart: the container
        recycles, `_waiting` comes back empty, and the orders it was holding
        sit at the broker with nobody watching them.

        Found live on 2026-09-01 - seven resting orders, the oldest 6.9 hours
        old and placed before a restart the evening before. A stale limit is
        worse than a missed trade: it fills on a setup this system stopped
        believing in hours ago, at a price the market has since left, and the
        first anybody knows is a position nobody opened.

        Deliberately **not** adopting them instead. Reconstructing what a
        `Waiting` believed - which gate it watched, what would have withdrawn
        it - is guesswork, and a wrong guess leaves a live order governed by a
        fiction. Withdrawing is the honest recovery: the signal is gone, and if
        it is still good it will be published again.
        """
        if not self.settings.entry_pending or not self.settings.live:
            return
        try:
            resting = await self.execution.resting()
        except BrokerError as exc:
            log.debug("trading: could not list resting orders: %s", exc)
            return
        mine = {held.ticket for held in self._waiting.values() if held.ticket}
        for ticket in resting:
            if ticket in mine:
                continue
            try:
                await self.execution.withdraw(ticket)
            except BrokerError as exc:
                log.warning("trading: could not withdraw orphan #%d: %s", ticket, exc)
                continue
            log.info(
                "trading: withdrew orphan #%d - resting at the broker with "
                "nothing here tracking it",
                ticket,
            )

    def _mark_best(self, symbol: str, bid: float, ask: float) -> None:
        """Track the extremes each open trade has seen, both ways.

        The favourable one is what the trailing rules read. The adverse one is
        what sizes a stop, and it was not tracked at all: 38 stopped trades cost
        -897.84 and how far price went against the ones that *won* - the number
        that says whether a 4v stop is protecting anything - could not be got
        out of our own record. See research/stops.md.
        """
        for ticket, live in self.open.items():
            if live.position.symbol != symbol:
                continue
            # The exit side, because that is the price a stop is measured
            # against: a long is closed on the bid.
            price = bid if live.position.side is Side.BUY else ask
            buying = live.position.side is Side.BUY
            seen = self._best.get(ticket)
            if seen is None:
                self._best[ticket] = price
            else:
                self._best[ticket] = max(seen, price) if buying else min(seen, price)
            hurt = self._worst.get(ticket)
            if hurt is None:
                self._worst[ticket] = price
            else:
                self._worst[ticket] = min(hurt, price) if buying else max(hurt, price)

    async def _manage(self) -> int:
        """Move stops on open trades, and bank part of the ones in front."""
        rules = (
            self.settings.break_even_at > 0
            or self.settings.trail_vol > 0
            or self.settings.scale_out_at > 0
        )
        if not rules:
            return 0
        moved = 0
        looked = 0
        skipped: Counter[str] = Counter()
        for ticket, live in list(self.open.items()):
            looked += 1
            spec = self.specs.get(live.intent.feed)
            best = self._best.get(ticket)
            # Said out loud rather than skipped in silence.
            #
            # Four trades on 2026-09-04 reached 2.75R to 4.32R in front and
            # closed at their **original** stop for -68.71 between them, with
            # `break_even_at` 1.0, `trail_vol` 2.0 and `scale_out_at` 1.0 all
            # configured. This loop had produced two stop moves in 181,039 log
            # lines and no scale-outs at all, with no errors anywhere: every
            # position was falling through one of these two guards and nothing
            # recorded which. That is the shape of every inert feature in
            # research/inert.md - a legal-looking silence.
            if spec is None:
                skipped[f"no spec for {live.intent.feed!r}"] += 1
                continue
            if best is None:
                # Not just *that* it is untracked, but which half failed:
                # a feed with no quotes never reached `_mark_best`, and a
                # feed with quotes reached it and did not match the symbol.
                skipped[
                    f"no best for {live.intent.feed}: position "
                    f"{live.position.symbol!r} vs mapped "
                    f"{self._symbol_of.get(live.intent.feed)!r}, "
                    f"{self._quotes_seen.get(live.intent.feed, 0)} quotes"
                ] += 1
                continue
            banked = False
            if not live.scaled:
                banked = await self._bank(live, spec, best)
                if not banked:
                    # Said out loud for the same reason the guards above are.
                    # `scale_out_at` has been 1.0 for the life of this desk and
                    # not one scale-out has fired, and `partial` declined from
                    # five places without saying which.
                    why = manage.why_no_bank()
                    if why:
                        skipped[f"no bank: {why}"] += 1
            if banked:
                moved += 1
                # The position is a different size now, and the stop rules
                # below read `live.position.volume`. Left to the next pass
                # rather than moving a stop against a stale volume.
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
        if looked and not moved:
            # Only when nothing moved, and only with open positions to move -
            # a quiet book is not a fault and should not be logged as one.
            log.info(
                "trading: managed nothing across %d open position(s)%s%s",
                looked,
                f" - {dict(skipped)}" if skipped else "",
                "" if skipped else " - every one reached `advance` and it proposed no better stop",
            )
        return moved

    async def _bank(self, live: Live, spec: SymbolSpec, best: float) -> bool:
        """Take part of a winner off, once. True if any came off.

        The failure this guards against is not the broker refusing - it is the
        broker *partially* succeeding and this not noticing, leaving `scaled`
        false and the loop taking another slice off on the next pass until the
        position is gone. So the flag is set on a confirmed close and the
        position is re-read from the broker rather than adjusted by arithmetic
        here, because what came off is the broker's answer, not ours.
        """
        # The exit price a market order would get right now: a long leaves on
        # the bid. Passed alongside `best` because banking wants the price that
        # exists and the trailing rules want the one that did.
        tick = await self._tick(live.position.symbol)
        now = tick.exit(live.position.side) if tick is not None else 0.0
        take = manage.partial(
            live.position, live.intent, spec, self.settings, best=best, current=now
        )
        if take is None:
            return False
        try:
            result = await self.execution.close_position(take.ticket, take.volume)
        except BrokerError as exc:
            log.warning("trading: could not bank part of #%d: %s", take.ticket, exc)
            return False
        if not result.ok:
            log.warning("trading: banking part of #%d refused: %s", take.ticket, result.comment)
            return False
        live.scaled = True
        log.info("trading: %s", take)
        for position in await self._positions(fresh=True):
            if position.ticket == take.ticket:
                live.position = position
                break
        await self._announce_bank(live, take)
        return True

    async def _announce_bank(self, live: Live, take: Take) -> None:
        """Say when part of a position is banked - it changes size and risk."""
        if not (self.settings.notify and self.settings.notify_fills):
            return
        await self.bus.publish(
            ALERTS,
            {
                "title": (
                    f"{self.settings.mode}: {live.intent.feed} part banked"
                    + (f" · {live.by}" if live.by else "")
                ),
                "body": (
                    f"{take.reason}\n\n"
                    f"took {take.volume:g} off, {live.position.volume:g} still running"
                ),
                "level": "info",
                "fields": {
                    "instrument": live.intent.feed,
                    "shape": "trade",
                    # Its own event for the same reason `protect` is: it sits
                    # between the fill and the close without replacing either.
                    "event": "bank",
                    "strategy": live.by,
                    "venue": self.broker.name,
                },
                "source": "trading",
            },
            source="trading",
        )

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
            # Floored, because the ceiling was never the problem. The measured
            # edge lives at 300-1,800s and the desk was holding for a median of
            # 99 seconds - closing trades before the horizon their edge was
            # measured over had elapsed. `snap` asks for 120s outright. See
            # research/horizon.md and `Settings.min_hold`.
            floor = self.settings.min_hold
            if floor > 0:
                limit = max(limit, floor)
            if limit <= 0:
                continue
            age = now - live.seen
            if age < limit:
                if await self._stale(live, age):
                    closed = True
                continue
            if await self._worth_keeping(live, age, limit):
                continue
            # Refreshes the broker's clock for this symbol. Without it the
            # cached tick time ages past its own freshness guard and the shut
            # test silently falls back to the consensus feed, which carries on
            # quoting an instrument the broker has closed - #5759753523 retried
            # its close every minute for eight hours of a shut US Tech 100.
            # Only positions already past their hold pay for the call.
            await self._tick(live.position.symbol)
            if self._too_wide_to_leave(live, age, limit):
                continue
            log.info("trading: closing #%d after %.0fs, past its %.0fs hold", ticket, age, limit)
            try:
                await self.execution.close_position(ticket)
            except BrokerError as exc:
                if _market_closed(exc):
                    log.info(
                        "trading: holding #%d past its %.0fs hold - the broker says "
                        "%s is closed, so this is a shut market rather than a fault",
                        ticket,
                        limit,
                        live.position.symbol,
                    )
                else:
                    log.warning("trading: could not close #%d on its clock: %s", ticket, exc)
                continue
            live.closed_by = "hold"
            closed = True
        if closed:
            await self._reconcile()

    def _shut_for(self, feed: str, tick: Tick | None = None, *, symbol: str = "") -> float | None:
        """How long this market has been shut, or None if it is trading.

        **The broker's clock first.** `_quoted_at` is fed from the quotes bus,
        which is a consensus of other venues, and they carry on quoting an
        instrument our broker has closed: a us30 order was refused with
        "Market closed" while the consensus feed looked perfectly live. Only
        the broker's own tick time answers the question being asked, which is
        whether *this* broker will let a position out.

        Measured on a Friday evening, our epoch and theirs agree and the two
        states separate cleanly: BTCUSD -2s against Australia 200 696s and
        Wall Street 30 1597s.

        **The observation has to be fresh too.** A cached tick time goes on
        ageing whether or not we are still asking, so an instrument we simply
        stopped quoting would drift into looking shut. If we have not looked
        recently the broker's clock is not used at all, and the consensus one
        answers instead - which is also what happens for a bridge that reports
        no tick time. Neither missing evidence nor our own silence is evidence
        of a closed market.
        """
        limit = self.settings.stale_quote_after
        now = time.time()
        if tick is not None and tick.time > 0.0:
            quiet = now - tick.time
            return quiet if quiet > limit else None
        # A caller holding the position knows its symbol outright. Worth taking
        # over the feed mapping, because a position adopted after a restart is
        # given `feed = position.symbol.lower()` - "us tech 100", which is not
        # a feed key, so both lookups miss and a shut market reads as trading.
        symbol = symbol or self._symbol_of.get(feed) or ""
        seen = self._broker_quoted_at.get(symbol)
        if seen and now - seen[0] <= limit:
            quiet = now - seen[1]
            return quiet if quiet > limit else None
        last = self._quoted_at.get(feed)
        if not last:
            return None
        quiet = now - last
        return quiet if quiet > limit else None

    def _quote_is_stale(self, feed: str) -> bool:
        """Whether this feed has stopped quoting, which means the market is shut.

        A us30 position could not be closed for twenty minutes through the
        index's daily break. The error was a bare 400 with no retcode; what
        actually identified the cause was the quote not having moved in thirty
        minutes - bid, ask and timestamp identical to half an hour earlier.

        Worth separating from a refusal because they want opposite handling. A
        shut market means wait, and retrying fills the log with warnings that
        read as a fault. A refused order means something about that order is
        wrong and should be loud.

        One definition, shared with the gate that refuses an entry. Two would
        let a position be opened into a market this path already considers
        shut, which is the exact failure the gate exists to prevent.
        """
        if self.settings.stale_quote_after <= 0:
            return False
        return self._shut_for(feed) is not None

    def _too_wide_to_leave(self, live: Live, age: float, limit: float) -> bool:
        """Whether the spread makes closing on the clock worse than waiting.

        The hold clock exists to release capital from a thesis that is not
        playing out. It assumes the exit costs about what the entry did, and
        out of hours that assumption fails completely: an aus200 position was
        quoted `bid 8998 / ask 9051` after the ASX closed - 53 points against a
        normal 1 or 2, and against the trade's own 8.89-point risk. Closing
        there would have paid six times the trade's entire risk budget in
        spread alone, to exit a position whose true mid had not reached its
        stop.

        `max_spread_fraction` already refuses to *enter* on a wide spread, and
        that is the easy half - an entry can always wait. This is the other
        half.

        **Bounded, like every extension here.** `max_hold_multiple` still caps
        total age, so an instrument that is permanently wide cannot hold a
        position open indefinitely; past that the trade goes out at whatever
        the market is offering, which is the honest outcome when the
        alternative is never leaving.
        """
        shut = self._shut_for(live.intent.feed, symbol=live.position.symbol)
        if shut is not None:
            log.info(
                "trading: holding #%d past its %.0fs hold - %s has not quoted in "
                "%.0fs, so the market is shut rather than the order refused",
                live.position.ticket,
                limit,
                live.position.symbol,
                shut,
            )
            return True
        want = self.settings.hold_max_spread
        if want <= 0:
            return False
        if age >= limit * max(1.0, self.settings.max_hold_multiple):
            return False
        risk = abs(live.intent.entry - live.intent.stop)
        spread = self._spread_of.get(live.intent.feed, 0.0)
        if risk <= 0 or spread <= 0 or spread < risk * want:
            return False
        log.info(
            "trading: holding #%d past its %.0fs hold - spread %.5g is %.1fx its "
            "%.5g risk, closing now would pay that to leave",
            live.position.ticket,
            limit,
            spread,
            spread / risk,
            risk,
        )
        return True

    async def _stale(self, live: Live, age: float) -> bool:
        """Close a trade that has gone nowhere long past when it should have.

        The median touch resolves in eighteen seconds and 84% of them inside
        five minutes, against holds here measured in half hours. A position
        still sitting at its entry well past that is not the event it was
        opened for - and what it is doing while it waits is not waiting for the
        thesis, it is giving noise time to reach the stop. That is a losing
        trade arrived at slowly, and closing it flat costs the spread instead.

        **Measured from the best price, not the current one**, and that is the
        conservative direction: a trade that reached 0.4R and came back has
        started, so it is left alone. Only a trade that never went anywhere at
        all qualifies. The rule is meant to catch the dead ones, and a rule
        that also caught the retracing ones would be closing winners on the way
        through their pullback.

        Not applied once a position has been scaled or protected - if part is
        banked or the stop is at break even, the thing this protects against
        has already been dealt with by something better.
        """
        after = self._stale_after(live)
        # The floor applies here too, or it is defeated: `_expire` would keep a
        # young trade and this would close it anyway. Stale is the other early
        # closure and both have to respect the band the edge was measured in.
        floor = self.settings.min_hold
        if floor > 0:
            after = max(after, floor)
        if after <= 0 or age < after or live.scaled:
            return False
        if self._still_building(live):
            return False
        risk = abs(live.intent.entry - live.intent.stop)
        if risk <= 0:
            return False
        best = self._best.get(live.position.ticket)
        if best is None:
            return False
        gained = (best - live.position.price_open) * live.intent.side.sign
        if gained >= risk * self.settings.stale_move:
            return False
        log.info(
            "trading: closing #%d flat - %.0fs old and never left the entry (%.2fR)",
            live.position.ticket,
            age,
            gained / risk,
        )
        try:
            await self.execution.close_position(live.position.ticket)
        except BrokerError as exc:
            log.warning("trading: could not close stale #%d: %s", live.position.ticket, exc)
            return False
        # Only once the broker has taken it. Naming the exit before the close
        # succeeds means a refused close still stamps the reason, and whatever
        # ends the trade later - a stop, a target - is then recorded as this.
        # A us30 position found it: its close was refused through the index's
        # daily break and the label was already on.
        live.closed_by = "stale"
        return True

    def _maybe_rearm(self, live: Live, price: float) -> None:
        """Queue a stopped-out setup for one more attempt, if it has one left.

        Only a stop qualifies. A trade closed on its target got what it asked
        for, and one closed on the clock was not refuted by anything - taking
        either again would be trading the same idea twice rather than
        re-taking one that a sweep interrupted.

        Queued rather than re-entered here: `_settle` runs inside
        reconciliation, and opening a position from within the walk over the
        position set is how that walk starts disagreeing with the broker.
        """
        if self.settings.reentry_max <= 0 or not live.signal:
            return
        if live.attempt >= self.settings.reentry_max:
            return
        if _exit_kind(live, price) != "stop":
            return
        again = dict(live.signal)
        again[ATTEMPT] = live.attempt + 1
        self._rearm.append(again)

    async def _rearm_stopped(self) -> None:
        """Put stopped-out setups back through the strategies, once each.

        Six of twelve stopped trades in the sample later reached the target
        they were aiming at, by between 3.7R and 25.7R. The level survived
        being crossed - which is what a sweep looks like from the outside - and
        the stop settled only that *that fill* was too early, not that the idea
        was wrong.

        **It re-runs the signal, not the trade.** The payload goes back through
        `on_signal` and therefore through every gate, so a setup whose
        probability has since decayed, whose instrument has gone wide, or whose
        level has stopped being a level is refused exactly like a new one. The
        alternative - resurrecting the intent - would re-enter on the strength
        of reasoning that the stop already contradicted.

        **It requires the pullback to be switched on**, and that is the guard
        that makes the rule safe rather than a way to lose twice quickly. At
        the moment a stop fills, price is by definition at the worst point the
        trade has seen; re-entering at market there buys the extreme. With
        `pullback_fraction` above zero the re-armed signal parks and waits for
        price to come back to the level, which is the entry the thesis wanted
        in the first place. Without it, this does nothing.
        """
        queued, self._rearm = self._rearm, []
        if not queued or self.settings.pullback_fraction <= 0:
            return
        for payload in queued:
            feed = str(payload.get("feed") or "")
            log.info("trading: re-arming %s after a stop (attempt %d)", feed, payload.get(ATTEMPT))
            with contextlib.suppress(Exception):
                await self.on_signal(payload, observe=False)

    def _reach(self, live: Live) -> float:
        """Furthest this trade got in front, in units of its own risk."""
        best = self._best.get(live.position.ticket)
        risk = abs(live.intent.entry - live.intent.stop)
        if best is None or risk <= 0:
            return 0.0
        gained = (best - live.position.price_open) * live.intent.side.sign
        return max(gained / risk, 0.0)

    def _heat(self, live: Live) -> float:
        """Furthest this trade ever went **against** itself, in units of risk.

        The mirror of `_reach`, and the number research/stops.md wanted and did
        not have. On a trade that won it says how much of the stop was actually
        used: if winners rarely spend more than a third of their risk, a stop
        four volatility units wide is protection nobody reaches, bought by
        sizing every position at a quarter of what the same money would allow.

        Zero rather than negative when the trade never went against itself at
        all, which is a real case on a fast fill and is not "no reading".
        """
        hurt = self._worst.get(live.position.ticket)
        risk = abs(live.intent.entry - live.intent.stop)
        if hurt is None or risk <= 0:
            return 0.0
        lost = (live.position.price_open - hurt) * live.intent.side.sign
        return max(lost / risk, 0.0)

    def _heat_vol(self, live: Live) -> float:
        """The same excursion in volatility units, so it compares across the book.

        `adverse_r` is in units of *this trade's* risk, which is the right
        denominator for "was the stop used" and the wrong one for comparing
        instruments - a 4v stop and a 1v stop both read 1.0 when fully used.
        """
        stop_vol = live.intent.stop_vol
        return round(self._heat(live) * stop_vol, 4) if stop_vol > 0 else 0.0

    def money(self, amount: float, *, signed: bool = True) -> str:
        """An amount with the account's currency attached. See `models.money`."""
        return money(amount, self.currency, signed=signed)

    #: Intents kept per feed.
    #:
    #: Sized against what actually accumulates rather than guessed. Measured on
    #: the live box within half an hour of shipping: twelve wanted intents in
    #: thirty minutes across two feeds, and `opportunity` holds for the 24h
    #: ceiling. At roughly sixteen an hour a single feed can carry several
    #: hundred open at once, so the first cap of 60 would have evicted most of
    #: them - and evicted the *slow* ones, biasing every mean towards intents
    #: that resolved quickly. An `Untaken` is a slotted dataclass; four hundred
    #: of them across forty feeds is nothing.
    MAX_UNTAKEN: ClassVar[int] = 400

    def _remember_untaken(
        self, feed: str, by: str, intent: Intent, interval: str, hold: float, now: float
    ) -> None:
        """Keep an intent a strategy wanted but did not get, to score later."""
        if intent.entry <= 0 or intent.stop <= 0 or intent.target <= 0:
            return
        kept = self._untaken.setdefault(feed, [])
        kept.append(
            Untaken(
                feed=feed,
                by=by,
                side=intent.side,
                entry=intent.entry,
                stop=intent.stop,
                target=intent.target,
                interval=interval,
                fill_by=now + self._fill_window(interval, hold),
                hold=hold,
                placed_at=now,
            )
        )
        if len(kept) > self.MAX_UNTAKEN:
            spilled, kept[:] = (
                kept[: len(kept) - self.MAX_UNTAKEN],
                kept[len(kept) - self.MAX_UNTAKEN :],
            )
            # Said out loud rather than dropped silently. An evicted intent is
            # a missing observation, and missing observations that correlate
            # with *how long a trade takes* are the ones that quietly rewrite a
            # mean - which is the whole reason this record exists.
            for lost in spilled:
                self._spilled += 1
                log.debug(
                    "trading: dropped an unresolved %s intent on %s after %.0fs",
                    lost.by,
                    lost.feed,
                    now - lost.placed_at,
                )

    def _fill_window(self, interval: str, hold: float) -> float:
        """How long an unfilled intent may wait, matching what `_park` allows.

        **Corrected on 2026-09-02, hours after shipping the wrong version.**
        The first cut gave every intent `max(hold, 60)` to fill, which is up to
        twenty-four hours for `opportunity`. A real resting entry gets
        `pullback_bars` bars of its own interval - fifty minutes on a 5m call -
        and is withdrawn after that.

        So the resolver was crediting fills the live system would never have
        seen, and crediting them to exactly the strategies that rest their
        entry furthest out of reach. `Untaken`'s own docstring says a fill must
        not be assumed because it would rank those strategies above the ones
        that paid the spread to be certain; the fill *window* is the same
        argument and the first version got it wrong.

        Same expression as `_park`, deliberately, so the two cannot drift.
        """
        bars = SECONDS.get(interval, 0.0)
        return bars * self.settings.pullback_bars if bars else (hold or self.settings.max_hold)

    async def _resolve_untaken(self, feed: str, tick: Tick) -> None:
        """Walk every unresolved intent on this feed one quote forward.

        Fill first, then the barrier race. See `Untaken` for why the fill is
        not assumed: crediting a rested entry with a price it never traded at
        would rank it above strategies that paid the spread to be certain.
        """
        kept = self._untaken.get(feed)
        if not kept:
            return
        alive: list[Untaken] = []
        for shade in kept:
            done = await self._step_untaken(shade, tick)
            if not done:
                alive.append(shade)
        if alive:
            self._untaken[feed] = alive
        else:
            self._untaken.pop(feed, None)

    async def _step_untaken(self, shade: Untaken, tick: Tick) -> bool:
        """One quote against one intent. True when it is finished with."""
        sign = shade.side.sign
        # Entry and exit sides, as a real trade would pay them.
        coming = tick.entry(shade.side)
        going = tick.bid if shade.side is Side.BUY else tick.ask

        if not shade.filled_at:
            reached = (coming - shade.entry) * sign <= 0
            if reached:
                shade.filled_at = tick.time
                shade.until = tick.time + shade.hold
                shade.last = going
                return False
            if tick.time >= shade.fill_by:
                await self._record_untaken(shade, "never filled", 0.0, tick.time)
                return True
            return False

        shade.last = going
        risk = abs(shade.entry - shade.stop)
        if risk <= 0:
            return True
        if (going - shade.target) * sign >= 0:
            await self._record_untaken(
                shade, "target", abs(shade.target - shade.entry) / risk, tick.time
            )
            return True
        if (going - shade.stop) * sign <= 0:
            await self._record_untaken(shade, "stop", -1.0, tick.time)
            return True
        if tick.time >= shade.until:
            await self._record_untaken(
                shade, "timeout", ((going - shade.entry) * sign) / risk, tick.time
            )
            return True
        return False

    async def _record_untaken(self, shade: Untaken, how: str, reward: float, when: float) -> None:
        """Journal what an intent nobody took would have been worth.

        `reward` is in units of the intent's own risk, which is the only
        denominator that compares a strategy trading gold against one trading a
        synthetic. A fill that never happened scores nothing and says so - it
        is not a zero-reward trade, it is an absent one, and averaging it in
        would flatter strategies that rest their entry out of reach.
        """
        await observe(
            self.journal,
            f"{shade.by} would have {how} on {shade.feed}",
            rationale=(
                f"entry {shade.entry:.5g} stop {shade.stop:.5g} target {shade.target:.5g}"
                f" - {how} at {reward:+.2f}R"
                if how != "never filled"
                else f"price never traded {shade.entry:.5g} within the hold"
            ),
            actor="trading",
            context={
                "shape": "untaken",
                "strategy": shade.by,
                "feed": shade.feed,
                "interval": shade.interval,
                "side": shade.side.value if hasattr(shade.side, "value") else str(shade.side),
                "resolved": how,
                "filled": bool(shade.filled_at),
                # Absent rather than zero when there was no fill, so a mean over
                # this field is a mean over trades that happened.
                "reward_r": round(reward, 4) if how != "never filled" else None,
                "entry": round(shade.entry, 8),
                "stop": round(shade.stop, 8),
                "target": round(shade.target, 8),
                "seconds": round(when - shade.placed_at, 1),
            },
            tags=(shade.feed, shade.by, "untaken"),
        )
        if how != "never filled":
            self._credit(shade.by, shade.feed, shade.interval, reward)

    def _arm_of(self, by: str) -> str:
        """The shape the named strategy last chose, or "" if it chooses none.

        Read off the engine rather than remembered here: `Opportunity.consider`
        sets it as it decides, and `consider` is synchronous, so the value is
        the one this decision was made with.
        """
        engine = next((e for e in self.strategies if e.name == by), None)
        return str(getattr(engine, "arm", "") or "")

    def _credit(self, by: str, feed: str, interval: str, reward: float) -> None:
        """Tell the policy what a strategy's shape was worth here.

        Keyed by the **shape** rather than the strategy name, because the names
        are not the thing being chosen between - `level-scalp` and
        `sweep-aware` are the same point, and crediting them separately would
        split one arm's evidence in half.
        """
        shape = PRESETS.get(by)
        arm = shape.named() if shape is not None else ""
        if not arm:
            engine = next((e for e in self.strategies if e.name == by), None)
            arm = str(getattr(engine, "arm", "") or "")
        if arm:
            self.policy.observe(feed, interval, arm, reward)

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
                intent = _intent_from(position, self._feed_of)
                ref = ""
            signal = self._last_signal.get(intent.feed, {})
            # From the fill, not from now. `seen` is stamped at adoption, so a
            # restart handed every open position a fresh clock - and max_hold,
            # hold_seconds and stale_after all measure from it. On a day with
            # fifteen deploys a position can outlive its hold indefinitely, and
            # `seconds` on its outcome measures from the last adoption rather
            # than the fill, so hold statistics read shorter than they were.
            # The broker already reports when it opened; nothing had asked.
            opened = getattr(position, "opened", 0.0) or 0.0
            # A position adopted after a restart arrives with no ref, and
            # `_settle` will not journal a close without one - so the trade
            # would be logged, announced, and never written down. Recover it
            # from the decision that opened it.
            if not ref:
                ref = self._ref_for(position)
            self.open[ticket] = Live(
                position=position,
                intent=intent,
                ref=ref,
                by=strategy_for(self.settings.magic, position.magic),
                signal=signal,
                attempt=int(signal.get(ATTEMPT, 0) or 0),
                seen=float(opened) if opened > 0 else time.time(),
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
            settled.append((live, price, why))
            # Discarded *after* the outcome is written, not before.
            #
            # These two lines used to sit above `_settle`, which is what reads
            # them - `_reach` and `_heat` both return 0.0 for a ticket they
            # cannot find. So `best_r` and `adverse_r` were written as exactly
            # 0.000 on every close the book ever made: 188 and 85 of them, min
            # and max both zero, and not one stopped trade recorded as ever
            # having been in profit. The tracking was correct, the recording
            # was correct, and the state was thrown away in between.
            #
            # `finally`, so a raising `_settle` still cleans up rather than
            # leaking a ticket's extremes for the life of the process.
            try:
                await self._settle(live, price, why, profit)
            finally:
                self._best.pop(ticket, None)
                self._worst.pop(ticket, None)
        return settled

    async def _settle(
        self, live: Live, price: float, why: str, profit: float | None = None
    ) -> None:
        """Record a closed position, and tell the day about it."""
        position = live.position
        profit = position.profit if profit is None else profit
        self.guard.record(live.intent.feed, profit, self.equity)
        self._maybe_rearm(live, price)
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
        if not live.ref:
            # A close with no decision behind it, which after a restart is most
            # of them: `self.open` is rebuilt from the broker by `_reconcile`
            # and the ref lives in memory, so every position that outlived a
            # restart closed without reaching the journal. Measured on
            # 2026-09-01: twenty distinct tickets closed in fourteen hours and
            # six outcomes recorded.
            #
            # Recorded as an **observation**, not an outcome. `journal.outcome`
            # refuses a parentless entry on purpose - an outcome is a label on
            # a decision and a label with nothing to label is not one - so
            # forcing it through there would break that invariant to fix this.
            # An observation is what this is: something that happened, with no
            # decision of ours attached.
            await observe(
                self.journal,
                f"{position.symbol} closed {profit:+.2f} at {price:.5g}, unattributed",
                rationale=(
                    f"{why} after {position.age:.0f}s. No decision is on record for this "
                    "position - it was adopted from the broker rather than opened here, "
                    "which is what happens to anything that outlives a restart."
                ),
                actor="trading",
                context={
                    "feed": live.intent.feed,
                    "symbol": position.symbol,
                    "ticket": position.ticket,
                    "exit": price,
                    "profit": round(profit, 2),
                    "seconds": round(position.age),
                    "reason": why,
                    "exit_kind": _exit_kind(live, price),
                    "strategy": live.by,
                    "unattributed": 1.0,
                },
                tags=(live.intent.feed, "close", "unattributed"),
            )
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
                    # What it made in the unit everything else here is judged
                    # in. Money is not comparable across instruments or across
                    # account sizes; R is, and it was never recorded - so every
                    # question about how a strategy actually did began with a
                    # derivation from entry, stop and exit that a reader had to
                    # do themselves and could get wrong.
                    #
                    # Signed against the side, so a profitable short is
                    # positive. Zero risk means a placeholder intent adopted
                    # after a restart, where the stop is the broker's and the
                    # entry is the fill - not a trade that risked nothing.
                    "r_multiple": _r_multiple(live.intent, price),
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
                    # The broker's own name for this trade. Absent until now,
                    # which meant a ticket from the terminal or an alert could
                    # not be traced to its record at all - the one identifier
                    # tying our books to theirs was the one thing not written
                    # down.
                    "ticket": position.ticket,
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
                    # And the other side of the same question, which was never
                    # recorded: how far it went against itself before it got
                    # there. On a winner this is how much of the stop was
                    # actually used, and a book whose winners never spend more
                    # than a third of their risk is a book sized at a quarter
                    # of what it could be. See research/stops.md.
                    "adverse_r": round(self._heat(live), 3),
                    "adverse_vol": self._heat_vol(live),
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
                # **Which shape the policy chose**, for the strategies that
                # choose one. `opportunity` is a parameter vector rather than a
                # fixed set of numbers, so "opportunity lost 15.90" says
                # nothing without it - the arm is the thing being judged, and
                # its first five trades were recorded with the arm absent.
                #
                # Empty for a strategy that has no policy, which is every
                # other one today.
                "arm": self._arm_of(by),
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
        # Same layout as a level alert, so a phone full of both can be read
        # without switching gear - one rule per line, each opening with the
        # thing it answers.
        rule = "━" * 22
        up = intent.side.sign > 0
        body = [
            rule,
            f"{'🟢' if up else '🔴'} {intent.feed.upper().replace('_', ' ')} · "
            f"FILLED · {str(intent.side).upper()}",
            rule,
            f"📊 {self.broker.name} · {by or 'trading'} · #{ticket}",
            "",
            f"📍 {intent.volume:g} lots @ {price:.5g}",
            # Stop and target with the ratio between them - and this one **is**
            # a reward-to-risk, unlike the level alert's push line, because
            # both ends are prices this trade will actually exit at.
            f"🛑 stop {intent.stop:.5g} · 🎯 target {intent.target:.5g} "
            f"· {intent.reward_to_risk:.1f} to 1",
            f"💰 risking {self.money(intent.risk_money, signed=False)} "
            f"({intent.risk_money / self.equity:.2%} of the book)"
            if self.equity
            else f"💰 risking {self.money(intent.risk_money, signed=False)}",
            f"📝 {intent.reason}" if intent.reason else "",
            rule,
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

    async def _announce_rest(
        self, intent: Intent, at: float, by: str, ticket: int, gone: str = ""
    ) -> None:
        """Say that an order is resting with the broker, or no longer is.

        An order left there is money committed while nobody is looking - it can
        fill on the terminal's own tick with this process asleep - so the two
        things worth telling a person are that it is out there and that it is
        not any more. `gone` carries why it was taken back, and is empty when
        it has just been placed.
        """
        if not (self.settings.notify and self.settings.notify_rests):
            return
        away = abs(intent.entry - at)
        body = [
            f"{intent.side} {intent.volume:g} lots resting @ {at:.5g}"
            if not gone
            else f"withdrawn - {gone}",
            "",
            f"{away:.5g} better than the {intent.entry:.5g} on offer" if not gone else "",
            f"stop {intent.stop:.5g} · target {intent.target:.5g}" if not gone else "",
            intent.reason if not gone else "",
        ]
        await self.bus.publish(
            ALERTS,
            {
                "title": (
                    f"{self.settings.mode}: {'withdrew' if gone else 'resting'} "
                    f"{intent.side} {intent.feed}"
                    + (f" #{ticket}" if ticket else "")
                    + (f" · {by}" if by else "")
                ),
                "body": "\n".join(line for line in body if line),
                "level": "info",
                "fields": {
                    "instrument": intent.feed,
                    "shape": "trade",
                    # Its own event, or a placement and its withdrawal would
                    # collapse into one finding under the repeat key - and the
                    # withdrawal is the half that says the money came back.
                    "event": "withdrawn" if gone else "resting",
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
                "body": _closed_body(
                    live, price, profit, why, self.money(profit), self.guard.summary()
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
        if tick is not None and tick.time > 0.0:
            self._broker_quoted_at[tick.symbol] = (time.time(), tick.time)
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
    """How a trade ended: what closed it, or where it ended if nothing did.

    `reason` records how the position left the book - closed by us, or gone
    between polls - not what took it. Stop and target were therefore
    distinguishable only by the sign of the profit, which is a guess dressed as
    a fact: a trade closed on the hold clock while slightly ahead looks like a
    target, and one closed slightly behind looks like a stop.

    **What we closed ourselves, we know**, and it is asked first. The price
    cannot distinguish a stale close from a hold-clock close - both land
    wherever the market happens to be - so both used to read as "hold" and the
    question "is the stale exit helping" had no answer in the record. Every
    rule that closes a position names itself on the way out.

    **Falling through to "hold" is a claim, and it needs the evidence for one.**
    An adopted position carries a placeholder intent with no stop and no
    target, so every comparison below is skipped and the trade would be filed
    as having run its clock - which is not something we know. It reads
    "unknown" instead. Scoring can exclude what is unknown; it cannot exclude
    what is confidently mislabelled.
    """
    if live.closed_by:
        return live.closed_by
    intent = live.intent
    sign = intent.side.sign
    if intent.stop and (price - intent.stop) * sign <= 0:
        return "stop"
    if intent.target and (price - intent.target) * sign >= 0:
        return "target"
    if not intent.stop and not intent.target:
        return "unknown"
    return "hold"


def _market_closed(exc: BrokerError) -> bool:
    """Whether the broker refused because its market is shut.

    The last authority on the question, and the only one that cannot be wrong:
    every clock here is an inference about the broker's state, and this is the
    broker stating it. `400 Order failed: Market closed` is what a close
    against a shut US Tech 100 actually returns.

    Kept as a string match because the bridge sends no retcode to match on -
    the same reason the original us30 diagnosis had to go by the quote not
    moving. Worth having anyway: a shut market means wait, and logging it as a
    warning every minute for eight hours reads as a fault that needs fixing.
    """
    return "market closed" in str(exc).lower()


def message_time(payload: dict[str, Any]) -> float:
    when = payload.get("time")
    return float(when) if isinstance(when, int | float) and when else time.time()


def _r_multiple(intent: Intent, exit_price: float) -> float:
    """What the trade made, in multiples of what it risked.

    `None` when there is no risk to divide by, rather than zero: a trade that
    made nothing and a trade whose risk is unknown are different facts, and
    zero would pool them.
    """
    risk = abs(intent.entry - intent.stop)
    if risk <= 0 or not exit_price or not intent.entry:
        return 0.0
    return round((exit_price - intent.entry) * intent.side.sign / risk, 4)


def _intent_from(position: Position, feed_of: dict[str, str] | None = None) -> Intent:
    """A placeholder intent for a position we did not open in this run.

    A restart leaves positions on the account carrying our magic and no record
    in memory of why they were opened. Adopting them means they are managed and
    closed properly; the reasoning is gone, and the journal entry says so
    rather than inventing one.

    **The feed name has to be the real one.** It was `symbol.lower()`, which
    for a broker whose symbols have spaces gives `volatility 25 index` beside
    the `volatility_25_index` everything else writes - two names for one
    instrument, so its history splits and neither half accumulates. Three
    trades went into the journal under the spaced name. The resolved map is
    passed in rather than guessed at, and the lowered symbol survives only as
    the fallback for a position on an instrument we do not track.
    """
    return Intent(
        feed=(feed_of or {}).get(position.symbol) or position.symbol.lower(),
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
