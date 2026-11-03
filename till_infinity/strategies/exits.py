"""Managing a position after the trade is on: stops, partials, and giving up.

Two things, and the split between them is the point.

`Exits` is a **component a strategy owns**, not an Actor. Three reasons, in the
order they matter:

1. **An exit rule that could close another strategy's position is the magic
   number bug wearing a new hat.** Nautilus puts a `strategy_id` on every
   position; management belongs to whoever opened it, and a component held by
   that strategy cannot reach anyone else's.
2. A component lets each entry choose which exits it runs. A scalp wants
   staleness; a swing whose thesis *is* duration must not have it.
3. It is a plain object over a position and a clock, so the policy is testable
   without an engine, an execution client or a venue.

`ExitMechanism` and its two leaves are what **hold** that component: a mixin
with no base, composed in front of an entry, exactly the way a decision mixin
is composed in front of one. That is the half that was missing. The component
was written, tested, correct and **reachable from nothing** - `Exits` had no
constructor call anywhere in `till_infinity/`, `manage.advance` and
`manage.partial` had no caller, `Profile.protection` had no caller, and
`BasketExit`'s close request had no subscriber. So the exit a trade got was
whichever bracket its entry happened to submit, identical for every decision,
and a decision could not state an exit at all.

The policy itself is `manage.py` and is not re-implemented here: `advance`,
`partial`, `Move`, `Take` and `better` are already pure functions over a
position and an intent. This is the part that was tangled up in `Trader` - the
tracking, the ordering, and the translation into orders.

## Both stop rules are off by default, and that is a finding

Break-even and trailing each cut the loss tail **and** cut winners. Which
dominates is an empirical question about this strategy on these instruments,
and nothing in this repository answers it. Shipping them on by default would be
asserting the answer. `manage.py` says this at more length and the four
combinations are meant to be compared on the journal.

## The stop only ever moves toward profit

Every path returns the existing stop unless the new one is strictly better. A
rule that can widen a stop is not risk management - it is the trade quietly
asking for more room after it has started going wrong, which is the single most
expensive habit in discretionary trading and does not become cheaper for being
automated.

## Exactly one thing may move a stop, and there are three candidates

This is a live hazard rather than a theoretical one.

* The **MT5 bridge** runs its own trailing-stop handler on a twenty-second
  timer. `manage.py` already refuses to use it, because two things moving the
  same stop on different clocks is incoherent rather than redundant.
* **Nautilus** has native `trailing_stop_market` orders, which is the third.
* **`advance`** is ours, and is the one with measurements behind it.

"Nautilus first" would say delegate to the framework, and here it cannot:
Nautilus's trailing stop does a plain offset trail and has no way to express
break-even-then-trail with a spread cushion and rung awareness, which is what
`advance` actually does. So `advance` stays, and **neither of the other two may
be enabled**. `Exits.conflicts` is the assertion of that, not a comment about
it.

## `best` comes from the quote stream, not from a snapshot

`advance` takes the most favourable price the trade has seen - the high for a
long, the low for a short. `Trader` tracked it from polls, and said why: a
broker's `price_current` is a snapshot, and a trailing stop anchored to
snapshots trails whatever the last poll happened to catch. Nautilus delivers
every quote to `on_quote_tick`, so this is strictly better than the version it
replaces rather than a translation of it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Any, ClassVar

from nautilus_trader.model.data import QuoteTick
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.position import Position as NautilusPosition

from ..domain.models import Intent, Position, Refusal, Side
from . import manage, turning
from .config import Settings


@dataclass(slots=True)
class Held:
    """What this component remembers about one open position.

    The intent is kept because `advance` needs the numbers the trade was
    *sized* for - its entry, its stop, its risk - and a position carries the
    fill rather than the plan. The two differ by the slippage, which is exactly
    the amount a stop placed from the fill would be wrong by.
    """

    intent: Intent
    #: The most favourable price seen since the position opened.
    best: float
    #: Unix seconds the position opened, for the age the hold rules read.
    opened: float
    #: Whether part of it has already been banked. A scaled position is
    #: exempt from staleness: it has already proved something.
    scaled: bool = False
    #: Quotes seen since it opened. `Trader` distinguished three causes of an
    #: untracked position and this is the one that needed a count - a busy
    #: morning proves nothing about now.
    quotes: int = 0
    #: The turn model's exit, ridden alongside the real one and scored
    #: against it. Not acted on: `delivering.md` measured it at +0.19 skill
    #: against the running mean, which is worth recording and not yet worth
    #: trading.
    ride: Any = None
    #: Why this position has already been asked to close, or "".
    #:
    #: A latch, and not decoration. A close is an *order*, and the
    #: `PositionClosed` event that clears this book arrives later - so without
    #: it the next quote asks the same question, gets the same answer and sends
    #: a second closing order. In a backtest the fill lands before the next
    #: quote and the bug is invisible; on a live feed it is one order per quote
    #: until the venue answers.
    closing: str = ""
    #: The stop the **venue** is holding, which stops being `intent.stop` the
    #: first time anything moves it.
    #:
    #: Tracked rather than re-derived because `manage.advance` compares a
    #: proposal against two different stops - the current one, to refuse a
    #: move backwards, and the original one, to refuse a trail tighter than
    #: the trade was sized for. An intent's stop never changes, so reading
    #: both off it would make every improvement look new and re-send the same
    #: modify on every quote.
    stop: float = 0.0


@dataclass(frozen=True, slots=True)
class Protection:
    """One side's exit geometry, in the units the `Intent` already carries.

    The same five fields the intent declares, so a side-specific entry is
    *folded onto the intent* and everything downstream keeps reading one
    place. Zero on any of them means the configured default, which is the
    convention the `Intent` fields already state.
    """

    break_even_at: float = 0.0
    trail_vol: float = 0.0
    trail_levels: bool = False
    hold: float = 0.0
    stale_exempt: bool = False


def protection_for(
    book: Sequence[tuple[str, Protection]], feed: str, side: Side | None = None
) -> Protection | None:
    """This feed's exit geometry, preferring a side-specific entry.

    `boom_500_index.sell` beats `boom_500_index`, in the same spelling
    `config.DEFAULT_STOP_OVERSHOOT` already uses, so the two tables can be
    read against one another. `risk.scaling.overshoot_for` is this function
    over those keys, and the reason is the same one: **on a jump instrument
    the two sides are not the same trade**, because a stop on the spike side
    can only be gapped over. A rule that exits a long and a short identically
    on an instrument with asymmetric tails is wrong by a measurable amount.

    **Nothing is shipped in the table, and that is the honest state.** No
    long/short difference in *exit* behaviour has been measured on this desk.
    The measured asymmetry next door is in the *gapping* - 2.0 on a boom's
    sell and a crash's buy - and turning an overshoot multiple into a trail
    distance is arithmetic nobody has done. So this resolves a table, the
    table is empty, and the first measured difference is one row.

    `None` means *nothing names this feed*, which is not the same as a
    `Protection` of zeros: the first leaves the intent alone, and the second
    is a side deliberately asking for the configured defaults.
    """
    held = dict(book)
    name = feed.strip().lower()
    word = str(getattr(side, "value", side) or "").strip().lower()
    if word and f"{name}.{word}" in held:
        return held[f"{name}.{word}"]
    return held.get(name)


@dataclass(frozen=True, slots=True)
class Plan:
    """What should happen to one position now, and nothing about how.

    Three outcomes rather than a list, because they are exclusive in practice
    and saying so in the type is cheaper than saying it in a comment: a
    position being closed is not also being banked.
    """

    move: manage.Move | None = None
    take: manage.Take | None = None
    #: Why the whole position should come off now, or "" to keep it.
    close: str = ""

    def __bool__(self) -> bool:
        """Whether anything should happen, so a caller can skip the rest."""
        return bool(self.move or self.take or self.close)


@dataclass(slots=True)
class Exits:
    """The exit policies for one strategy's positions.

    Held by the strategy, so it can only ever reach positions that strategy
    opened. `observe` folds in a quote; `apply` returns what should happen and
    the strategy sends it - split that way so the decision is testable without
    an execution client.
    """

    settings: Settings
    #: Close a trade that has gone nowhere. Off for a strategy whose thesis is
    #: duration - see `stale_after`.
    stale: bool = True
    #: Ride the turn model's exit and score it, without acting on it.
    score_turn: bool = True
    _held: dict[Any, Held] = field(default_factory=dict)

    # ------------------------------------------------------------- the tracking

    def opened(self, position_id: Any, intent: Intent, when: float) -> None:
        """A position this strategy opened."""
        self._held[position_id] = Held(
            intent=intent, best=intent.entry, opened=when, stop=intent.stop
        )
        if self.score_turn:
            self._ride(position_id, intent)

    def closed(self, position_id: Any) -> Held | None:
        """Forget a position, returning what was known about it."""
        return self._held.pop(position_id, None)

    def observe(self, position_id: Any, tick: QuoteTick) -> None:
        """Fold one quote into the best price this position has seen.

        The **entry side** of the quote, which is the side the position would
        be closed at: a long is closed at the bid, so the best a long has seen
        is the highest bid and not the highest ask. Using the wrong side
        flatters every trailing stop by one spread.
        """
        held = self._held.get(position_id)
        if held is None:
            return
        held.quotes += 1
        price = float(tick.bid_price) if held.intent.side is Side.BUY else float(tick.ask_price)
        if held.intent.side is Side.BUY:
            held.best = max(held.best, price)
        else:
            held.best = min(held.best, price)

    def _ride(self, position_id: Any, intent: Intent) -> None:
        """Start the turn model's exit alongside the real one."""
        try:
            suggested = turning.suggestion_from(intent.features, intent.side)
        except Exception:
            return
        if not suggested:
            return
        held = self._held.get(position_id)
        if held is not None:
            held.ride = suggested

    # -------------------------------------------------------------- the policy

    def stop_for(
        self,
        position_id: Any,
        position: Position,
        spec: Any,
        *,
        vol_bps: float = 0.0,
        rungs: tuple[float, ...] = (),
    ) -> manage.Move | None:
        """Where this position's stop should be now, or None to leave it."""
        held = self._held.get(position_id)
        if held is None:
            return None
        return manage.advance(
            position,
            held.intent,
            spec,
            self.settings,
            best=held.best,
            vol_bps=vol_bps,
            rungs=rungs,
        )

    def bank_for(
        self,
        position_id: Any,
        position: Position,
        spec: Any,
        *,
        best: float | None = None,
    ) -> tuple[manage.Take | None, str]:
        """What part of this position should come off, and why not if none.

        Returns the reason as well, because `partial` declined from five places
        without saying which and `scale_out_at` sat at 1.0 for the life of the
        desk without a single scale-out firing. That is the shape
        `research/inert.md` catalogues: a feature configured, correct and
        inert.
        """
        held = self._held.get(position_id)
        if held is None or held.scaled:
            return None, "already scaled"
        take = manage.partial(
            position,
            held.intent,
            spec,
            self.settings,
            best=held.best if best is None else best,
        )
        return take, "" if take else manage.why_no_bank()

    def banked(self, position_id: Any) -> None:
        """Record that part of it came off, which exempts it from staleness."""
        held = self._held.get(position_id)
        if held is not None:
            held.scaled = True

    def stale_after(self, position_id: Any) -> float:
        """How long this position gets before it counts as going nowhere.

        **Zero, meaning off entirely, for a strategy whose thesis is
        duration.** The rule exists because a level touch resolves in eighteen
        seconds at the median and 84% inside five minutes - a premise true of a
        scalp and false of a swing, at any length of clock. Scaling it to the
        declared hold was the first attempt and it was a half-measure: it made a
        rule proportional when the rule does not apply.
        """
        held = self._held.get(position_id)
        if held is None or not self.stale:
            return 0.0
        if getattr(held.intent, "stale_exempt", False):
            return 0.0
        after = float(self.settings.stale_after or 0.0)
        # The floor applies here too, or it is defeated: an expiry rule would
        # keep a young trade and this would close it anyway. Both early
        # closures have to respect the band the edge was measured in.
        floor = float(self.settings.min_hold or 0.0)
        return max(after, floor) if after > 0.0 else 0.0

    def is_stale(self, position_id: Any, now: float) -> bool:
        """Has this position gone nowhere for longer than it is allowed to?"""
        held = self._held.get(position_id)
        if held is None or held.scaled:
            return False
        after = self.stale_after(position_id)
        return after > 0.0 and (now - held.opened) >= after

    def held(self, position_id: Any) -> Held | None:
        return self._held.get(position_id)

    @property
    def tracking(self) -> int:
        return len(self._held)

    @property
    def positions(self) -> tuple[Any, ...]:
        """The positions this component is tracking, oldest first.

        A tuple and not the dict, because a caller iterates this while `apply`
        may close one - and mutating a dict under its own iterator fails only
        on the quote that closes a position, which is the one quote a test is
        least likely to send.
        """
        return tuple(self._held)

    def apply(
        self,
        position_id: Any,
        position: Position,
        spec: Any,
        *,
        now: float,
        vol_bps: float = 0.0,
        rungs: tuple[float, ...] = (),
    ) -> Plan:
        """Everything this position's exits ask for now, as one answer.

        **The split this class promised and did not have.** `observe` folded in
        a quote and the three policy methods each answered separately, so a
        caller had to know the order to ask them in - and there was no caller,
        so nothing did. A policy that returns orders cannot be tested without
        an execution client; this returns a `Plan` and the strategy sends it.

        The order is the design, the same way the gate sequence is. A position
        that should come off whole is not also partially banked, and a stop
        moved on a position about to be closed is a modify nobody needed.
        """
        held = self._held.get(position_id)
        if held is None:
            return Plan()
        if why := self._expired(held, now):
            return Plan(close=why)
        if self.is_stale(position_id, now):
            return Plan(close=f"went nowhere for {self.stale_after(position_id):.0f}s")
        take, _ = self.bank_for(position_id, position, spec)
        if take is not None:
            return Plan(take=take)
        return Plan(move=self.stop_for(position_id, position, spec, vol_bps=vol_bps, rungs=rungs))

    @staticmethod
    def _expired(held: Held, now: float) -> str:
        """Why this position is out of time, or "" while it still has some.

        **Only the clock a rule set.** `Intent.hold` is the strategy's own and
        is enforced here; `Settings.max_hold` is deliberately *not* folded in,
        and the number is the reason: it is 1800s by default, so folding it in
        would put a thirty-minute timeout on every trade this desk takes, on
        the quiet authority of a default. `research/spending.md` measured the
        holds already running short - **50 of 133** closes exited at 5% of
        their planned target because the clock ran out before the geometry
        could resolve, the largest exit category on the book and the one
        nobody could see was a timeout rather than an outcome. A global hold is
        a policy change, and this is not the change that measures it.
        """
        hold = float(held.intent.hold or 0.0)
        if hold <= 0.0:
            return ""
        age = now - held.opened
        return f"held {age:.0f}s and its rule allows {hold:.0f}s" if age >= hold else ""

    # ------------------------------------------------------------ the conflict

    @staticmethod
    def conflicts(orders: list[Any]) -> list[str]:
        """Any order type that would move a stop behind `advance`'s back.

        An assertion rather than a comment. Three things can trail a stop on
        this desk - the bridge's twenty-second handler, Nautilus's native
        trailing order, and `advance` - and exactly one may. If a trailing
        order reaches the venue while `advance` is also running, both move the
        same stop on different clocks and the resulting stop is whichever wrote
        last, which is not a policy.
        """
        return [
            str(order.client_order_id)
            for order in orders
            if "TRAILING" in getattr(order, "order_type", type("x", (), {"name": ""})()).name
        ]


def closing_side(side: Side) -> OrderSide:
    """The side that closes a position opened on `side`."""
    return OrderSide.SELL if side is Side.BUY else OrderSide.BUY


def as_domain(position: NautilusPosition, intent: Intent, *, stop: float = 0.0) -> Position:
    """A Nautilus position in the shape `manage` reads.

    **A bridge, and it is meant to go away.** `manage.advance` and
    `manage.partial` take this desk's own `Position` and read `price_open`,
    `side`, `stop` and `ticket` off it; the spec's step on data structures
    replaces that shape with Nautilus's and deletes this function. Until then a
    translation in one place is better than two position types threaded
    through the policy.

    `stop` is the one the **venue** is holding, defaulting to the intent's:
    Nautilus keeps a stop as a separate order, so a position has no stop field
    to read. The default is only right until something moves it, which is why
    `Held.stop` tracks it and `ManagedExit` passes it - `advance` compares a
    proposal against the current stop *and* against the original, and an
    intent's stop never changes. `ticket` is the position id as a string hash,
    because `Move` and `Take` carry it only to name themselves in a log line.
    """
    return Position(
        ticket=abs(hash(str(position.id))) % 1_000_000_000,
        symbol=position.instrument_id.symbol.value,
        side=intent.side,
        volume=float(position.quantity),
        price_open=float(position.avg_px_open),
        stop=stop or intent.stop,
        target=intent.target,
        price_current=float(position.avg_px_open),
        profit=float(position.realized_pnl or 0.0),
        opened=position.ts_opened / 1_000_000_000,
    )


# --------------------------------------------------------- the exit mechanisms


class ExitMechanism:
    """The exit half of a strategy, as a mixin with no base of its own.

    The entries in `entries.py` differ in `place`; these differ in what happens
    **after** the fill, and they compose the same way a decision does:

        class SurpriseEdge(Surprise, VenueExit, EdgeEntry): ...
        class SurpriseResting(Surprise, ManagedExit, RestingEntry): ...

    Until this existed the exit was not composable at all. `EdgeEntry` and
    `ArrivalEntry` submitted a bracket inside `place` and `RestingEntry`
    submitted none, so the exit was whatever the entry happened to do - which
    means every decision got the same exit whatever its thesis, and no decision
    could state one. `Exits`, `manage.advance`, `manage.partial` and
    `Profile.protection` were all written, tested and reachable from nothing.

    ## Before the entry in the bases, and the ordering is load-bearing

    Two of the three entries override `on_quote_tick` and two override
    `on_order_filled`, and neither of the latter calls `super()`. An exit
    placed *after* the entry in the bases would therefore never see a fill. In
    front of it this runs first and hands the event on, which is also what lets
    it read the entry's own `_waiting` before the entry clears it - so a
    resting order that fills is matched to the intent it was left for rather
    than to whichever intent was accepted most recently.

    ## Protection is here, not in the entry

    Whether a position is protected is a question about the cache, not about
    which entry ran. `RestingEntry` submits a bare limit and attaches nothing
    on the fill, so a rest that filled was an unprotected position for as long
    as resting entries have existed; `EdgeEntry` and `ArrivalEntry` bracket, so
    for them `_attach` finds a stop and does nothing. One rule covers all three
    and none of them has to remember it.

    ## And the basket close, because an Actor cannot close a position

    `BasketExit` publishes a request and the owning strategy acts on it: an
    Actor has no order factory and submitting under its own identity would lose
    the `strategy_id` the whole carve-up is for. Nothing subscribed, so the
    basket stop logged "closing all N positions", counted them closed and
    **closed nothing**. A rule that reports an action it did not take is worse
    than one switched off, because the record says it fired.
    """

    #: Per-(feed, side) exit geometry, folded onto the intent when a position
    #: opens. **Empty, deliberately** - see `protection_for` for what is
    #: measured and what is not.
    sided: ClassVar[tuple[tuple[str, Protection], ...]] = ()
    #: Close a trade that has gone nowhere. A leaf whose thesis *is* duration
    #: sets this False, which is the per-rule half of the same asymmetry
    #: `Intent.stale_exempt` expresses per trade.
    stale: ClassVar[bool] = True
    #: Ride the turn model's exit and score it, without acting on it.
    score_turn: ClassVar[bool] = True

    @property
    def exits(self) -> Exits:
        """This strategy's own exit book, built on first use.

        A property rather than an `__init__`, because a mixin with one would
        have to know the entry's config type to pass it along - and that
        coupling is the thing being composed away. Built from `self.settings`,
        which `Desk` has already read.
        """
        book = getattr(self, "_exits", None)
        if book is None:
            book = Exits(settings=self.settings, stale=self.stale, score_turn=self.score_turn)
            self._exits = book
        return book

    # ----------------------------------------------------------- the lifecycle

    def on_start(self) -> None:
        """Subscribe to the basket's close request, then start the entry."""
        super().on_start()
        from ..utils.topics import ALERTS, subscribe

        # A bound method, which is what makes a stop/start cycle safe:
        # `msgbus.subscribe` deduplicates on `(topic, handler, priority)`, and
        # two bound methods of one instance compare equal where two fresh
        # `partial`s never do - the bug `notifications/actor.py` paid for by
        # delivering every later alert twice.
        subscribe(self, ALERTS, self.on_alert)
        self.log.info(f"{type(self).__name__} exits, listening for the basket close")

    def on_alert(self, payload: Any) -> None:
        """Close this strategy's own position when the whole book says so.

        Filtered on `strategy_id`, because an exit rule that could close
        another strategy's position is the magic-number bug wearing a new hat -
        and the request names the owner precisely so this does not have to
        guess.
        """
        if not isinstance(payload, dict) or payload.get("shape") != "basket.close":
            return
        if str(payload.get("strategy_id") or "") != str(self.id):
            return
        from nautilus_trader.model.identifiers import PositionId

        named = str(payload.get("position_id") or "")
        if not named:
            return
        if self._close(PositionId(named), "the book was over its limit"):
            self._count("(exit):basket")
            return
        # Counted rather than silent: the gap between what the basket asked
        # for and what came off is the number that says whether the book was
        # actually flattened.
        self._count("(exit):basket-gone")

    def _close(self, position_id: Any, why: str) -> bool:
        """Flatten a position **once**, however many rules ask for it.

        The single place a close is sent, so the latch cannot be forgotten by
        one of them - see `Held.closing`. False means nothing was sent, either
        because the position is already closing or because it is already gone.
        """
        held = self.exits.held(position_id)
        if held is not None and held.closing:
            return False
        position = self.cache.position(position_id)
        if position is None or position.is_closed:
            return False
        if held is not None:
            held.closing = why
        self.close_position(position)
        self.log.info(f"closing {position.id}: {why}")
        return True

    def consider(self, payload: dict[str, Any]) -> Intent | Refusal | None:
        """The gates, then remember what they accepted.

        **The only funnel every entry shares.** `place` is not one:
        `ArrivalEntry.place` parks a payload and the intent that eventually
        fills is built later, from `on_quote_tick`, so an exit that captured
        `place` would manage an arrival with the geometry it had *before* the
        wait. `consider` is called on both paths and returns the intent on
        both.
        """
        verdict = super().consider(payload)
        if isinstance(verdict, Intent):
            self._intended = verdict
        return verdict

    def on_order_filled(self, event: Any) -> None:
        """Pin the fill to its intent, **before the entry forgets it**.

        `RestingEntry` can have more than one limit out at once and pops
        `_waiting` on the fill, so the intent has to be read here, in front of
        it. Where an entry keeps no map - an arrival, or a bracketed edge -
        the last accepted intent is the right answer, because `Desk` refuses a
        proposal on an instrument anything already holds.
        """
        found = None
        order_id = getattr(event, "client_order_id", None)
        for book in (getattr(self, "_waiting", None), getattr(self, "_pending", None)):
            if isinstance(book, dict) and order_id in book:
                found = book[order_id]
                break
        self._filled = found or getattr(self, "_intended", None)
        super().on_order_filled(event)

    def on_position_opened(self, event: Any) -> None:
        """Track it, fold in the side's own numbers, and see that it is held."""
        intent = getattr(self, "_filled", None) or getattr(self, "_intended", None)
        self._filled = None
        if intent is None:
            self._orphan(event.position_id, "nothing here remembers the intent it was opened on")
            return
        if intent.stop <= 0.0:
            self._orphan(event.position_id, f"its intent on {intent.feed} names no stop price")
            return
        self.exits.opened(event.position_id, self._sided(intent), self.clock.timestamp())
        self._attach(event.position_id)

    def _orphan(self, position_id: Any, why: str) -> None:
        """Close a position whose stop price cannot be reconstructed.

        **The price is the one number that must never be invented.** A quantity
        has a correct answer whatever this process remembers - whatever is open
        - but a stop does not: a distance, a volatility multiple or the
        configured default all put a price nobody chose on the venue, and that
        price then reads as protection in every report. Falling back is the
        worse failure of the two, because an unprotected position at least
        looks like one.

        So this is treated as an orphan rather than patched: said out loud,
        recorded, and flattened. A position whose stop cannot be named is a
        position nobody decided to hold, and the desk's standing instruction is
        to judge it on the broker rather than on what this process remembers.
        """
        self._count("(exit):orphan")
        self.log.error(f"closing {position_id} as an orphan: {why}")
        self._journal(Refusal(gate="orphan", detail=why, feed=self._feed_name()), {})
        self._close(position_id, f"orphan: {why}")

    def on_position_closed(self, event: Any) -> None:
        """Forget it, and say what the turn model would have done instead.

        Scored and not acted on: `delivering.md` measured the turn exit at
        +0.19 skill against the running mean, which is worth recording and not
        yet worth trading.
        """
        held = self.exits.closed(event.position_id)
        if held is not None and held.ride is not None:
            self.log.info(f"{held.intent.feed} closed; the turn model wanted {held.ride}")

    def on_quote_tick(self, tick: QuoteTick) -> None:
        """Fold the quote into every position this strategy holds.

        `super()` first, for the reason `Desk.on_quote_tick` gives: an override
        that forgets it leaves the counterfactual's `following` climbing
        forever and the trial count wrong, which nothing else would show.
        """
        super().on_quote_tick(tick)
        for position_id in self.exits.positions:
            self.exits.observe(position_id, tick)

    # ------------------------------------------------------------ the stop

    def _sided(self, intent: Intent) -> Intent:
        """`intent` with this `(feed, side)`'s own exit numbers folded in.

        Folded onto the intent rather than read later, because every rule
        downstream already reads the intent - the field comments say why: by
        the time a stop is being moved, the strategy that wanted the trade is a
        name in a log line.
        """
        found = protection_for(self.sided, intent.feed, intent.side)
        if found is None:
            return intent
        return replace(
            intent,
            break_even_at=found.break_even_at or intent.break_even_at,
            trail_vol=found.trail_vol or intent.trail_vol,
            trail_levels=found.trail_levels or intent.trail_levels,
            hold=found.hold or intent.hold,
            stale_exempt=found.stale_exempt or intent.stale_exempt,
        )

    def _attach(self, position_id: Any) -> None:
        """A stop at the venue, where nothing is already holding one.

        **The quantity is the position's and not the intent's.** A partial
        fill, a venue that rounds, or a second fill into one position all leave
        `intent.volume` and `position.quantity` disagreeing, and a stop sized
        from the intent would then leave part of a live position uncovered -
        which is the exact failure a bracket exists to make impossible. What is
        open is the only answer that cannot be wrong.

        The *price* is the intent's, and only ever the intent's - see
        `_orphan` for what happens when there is not one.
        """
        held = self.exits.held(position_id)
        if held is None:
            return
        if self._guards():
            return  # the entry bracketed it, and two stops is not two policies
        instrument = self.cache.instrument(self._cfg.instrument_id)
        position = self.cache.position(position_id)
        if instrument is None or position is None:
            return
        self.submit_order(
            self.order_factory.stop_market(
                instrument_id=instrument.id,
                order_side=closing_side(held.intent.side),
                quantity=position.quantity,
                trigger_price=instrument.make_price(held.intent.stop),
                time_in_force=TimeInForce.GTC,
                reduce_only=True,
            )
        )
        self._count("(exit):protected")
        self.log.info(f"{held.intent.feed} stop attached at {held.intent.stop} after the fill")

    def _guards(self) -> list[Any]:
        """The stop orders this strategy has live on this instrument.

        A trigger price and not an order type, so a stop-limit and a trailing
        stop are both found - the second is what `Exits.conflicts` is for. Not
        `orders_open`, because an order submitted and not yet accepted is still
        a stop on its way to the venue, and treating it as absent would send a
        second one.
        """
        return [
            order
            for order in self.cache.orders(
                instrument_id=self._cfg.instrument_id, strategy_id=self.id
            )
            if getattr(order, "trigger_price", None) is not None and not order.is_closed
        ]


def _trail_vol_bps(intent: Any) -> float:
    """The relative volatility `advance` needs, in basis points.

    **`advance` stands down entirely when this is zero**, because
    `price_distance` multiplies by it, so a rule that publishes no volatility
    gets no trail - silently, since a trail that never moves a stop looks
    exactly like a trail that was never switched on.

    Measured: `TRADING_TRAIL_VOL` at 0.25, 0.5, 1.0 and 3.0, with
    `TRADING_TRAIL_SIGMAS` at 0.5 and 0.0, moved `smc-bos-causal` by **0.00 on
    all eight combinations** while the same settings moved
    `statespace-surprise` from -93.58 to -56.12 and `statespace-long` from
    -145.89 to -58.90. One rule in four had an inert trail.

    The reason is a units decision that was right: `structure.py` publishes its
    volatility as `bos_atr` and says in place why it is **not** called
    `vol_bps` - that column is a folded log variance elsewhere on this desk,
    and an ATR written into it would put one journal column in two estimators.
    So the conversion belongs here, at the one caller that needs a distance,
    rather than in the feature the journal scores.

    An ATR is a price distance and `vol_bps` is relative, so the conversion is
    `atr / price * 10_000` - the inverse of `price_distance`, same dimension
    and same unit. `bos_close` is the anchor because `bos_atr` is measured at
    the signal bar's close, and dividing a distance by a price from a different
    moment is the error that reads as calibrated near 1.0 and is wrong by a
    factor of the price everywhere else.
    """
    features = getattr(intent, "features", None) or {}
    folded = float(features.get("vol_bps") or 0.0)
    if folded > 0.0:
        return folded
    # **Any `<prefix>_atr` with its own `<prefix>_close` anchor**, which is a
    # convention and not a list: `structure.py` publishes `bos_atr`/`bos_close`
    # and `bands.py` publishes `ma_atr`/`ma_close`, and a hard-coded pair would
    # have left the second rule with the silent inert trail the first one had.
    # The anchor must share the prefix, because dividing a distance by a price
    # from a different moment reads calibrated near 1.0 and is wrong by a
    # factor of the price everywhere else.
    for key, value in features.items():
        if not str(key).endswith("_atr"):
            continue
        atr = float(value or 0.0)
        price = float(features.get(f"{str(key)[: -len('_atr')]}_close") or 0.0)
        if atr > 0.0 and price > 0.0:
            return atr / price * 10_000.0
    return 0.0


class VenueExit(ExitMechanism):
    """The venue holds the whole exit and nothing of ours moves it.

    The stop and the target sit with the broker from the fill onward, and the
    only thing this adds to them is the basket close and the protection of a
    fill that arrived without a bracket.

    **It is the configuration to run when something else is trailing.**
    `manage.py` records the hazard as live rather than theoretical: three
    things can move a stop on this desk - the MT5 bridge's own twenty-second
    trailing handler, Nautilus's native trailing order, and `advance` - and
    exactly one may, because two moving the same stop on different clocks
    gives whichever wrote last and that is not a policy. Where the bridge's
    handler is on, this is the honest pairing.
    """


class ManagedExit(ExitMechanism):
    """The stop is ours after the fill: break-even, the trail, banking, clocks.

    `manage.advance` and `manage.partial` are the policy, and both are **off by
    default** - which is a finding rather than an omission. Break-even and
    trailing each cut the loss tail and each cut winners; which dominates is an
    empirical question about this strategy on these instruments and nothing in
    this repository answers it, so shipping them on would be asserting the
    answer. `TRADING_BREAK_EVEN_AT` and `TRADING_TRAIL_VOL` turn each on
    independently, and an `Intent` overrides both **per rule and per side**.

    So what this changes today is not the policy but whether the policy can
    run at all. Before it, `advance` and `partial` had no caller anywhere in
    `till_infinity/`: configured, correct and inert, which is the exact shape
    `research/inert.md` catalogues and `scale_out_at` sat in for the life of
    the desk.

    Driven from the quote stream rather than a timer, for the reason `partial`
    gives: the trigger used to need the position to be at its threshold *when
    a loop happened to look*, and 19.6% of closes reached 1.0R by their
    high-water mark while not one scale-out ever fired, because the peak and
    the poll are different moments.
    """

    def on_quote_tick(self, tick: QuoteTick) -> None:
        super().on_quote_tick(tick)
        now = self.clock.timestamp()
        for position_id in self.exits.positions:
            self._act(position_id, now)

    def _act(self, position_id: Any, now: float) -> None:
        """One position, one answer, acted on."""
        held = self.exits.held(position_id)
        if held is None or not self._manages(held):
            return
        position = self.cache.position(position_id)
        spec = self._spec()
        if position is None or position.is_closed or spec is None:
            return
        if stray := Exits.conflicts(self._guards()):
            # The assertion `manage.py` promised rather than a comment about
            # it. `advance` is the one that stands down, because the trailing
            # order is already live at the venue and cancelling it from here
            # would be a second policy racing the first rather than replacing
            # it. Counted, so a deploy that leaves the bridge's handler on is
            # visible in the tally instead of in the fills.
            self._count("(exit):trailing-conflict")
            self.log.error(f"a trailing order is live, so advance stands down: {stray}")
            return
        plan = self.exits.apply(
            position_id,
            as_domain(position, held.intent, stop=held.stop),
            spec,
            now=now,
            vol_bps=_trail_vol_bps(held.intent),
            # No rungs: the `Book` of levels is not threaded to a strategy, so
            # a level trail has nothing to step behind. `Intent.trail_levels`
            # is off by default and this is the reason - a feature switched on
            # with an empty input is the inert shape again.
            rungs=(),
        )
        if not plan:
            return
        if plan.close:
            if self._close(position_id, plan.close):
                self._count("(exit):closed")
            return
        if plan.take is not None:
            self._bank(position_id, held, plan.take)
        if plan.move is not None:
            self._move(held, plan.move)

    def _manages(self, held: Held) -> bool:
        """Whether any rule could act on this position at all.

        Asked before the position, the spec and the cross-rate are looked up,
        because this runs on **every quote** and every rule here is off by
        default: break-even and trailing are zero unless a deploy or an intent
        asks, a rule's own hold is zero unless it sets one, and `stale_after`
        and `scale_out_at` are zero. With all of them off there is nothing for
        the rest of this to compute, and an account plus cross-rate lookup per
        quote per position on two cores is how a node comes to have late
        quotes - which is the one input every gate on this desk trusts.
        """
        settings = self.settings
        intent = held.intent
        return bool(
            intent.break_even_at
            or intent.trail_vol
            or intent.hold
            or settings.break_even_at
            or settings.trail_vol
            or settings.scale_out_at
            or (self.stale and settings.stale_after)
        )

    def _bank(self, position_id: Any, held: Held, take: manage.Take) -> None:
        """Take part of it off at market, reduce-only."""
        instrument = self.cache.instrument(self._cfg.instrument_id)
        if instrument is None:
            return
        quantity = instrument.make_qty(take.volume)
        if quantity.as_double() <= 0.0:
            # Refused rather than nudged up, as a zero entry size is: a slice
            # the venue cannot take is not a slice.
            self._count("(exit):bank-rounds-to-zero")
            return
        self.submit_order(
            self.order_factory.market(
                instrument_id=instrument.id,
                order_side=closing_side(held.intent.side),
                quantity=quantity,
                reduce_only=True,
            )
        )
        self.exits.banked(position_id)
        self._count("(exit):banked")
        self.log.info(f"{held.intent.feed} {take}")

    def _move(self, held: Held, move: manage.Move) -> None:
        """Modify the stop the venue is holding, once.

        One modify per improvement and not one per quote: `advance` only
        returns a `Move` when the new stop beats the one the venue holds, which
        is what `Held.stop` is for. A modify already in flight is left to land
        - the next quote asks again - because two modifies racing on one order
        is the same incoherence as two things trailing it.
        """
        instrument = self.cache.instrument(self._cfg.instrument_id)
        if instrument is None:
            return
        for order in self._guards():
            if order.is_pending_update:
                return
            self.modify_order(order, trigger_price=instrument.make_price(move.stop))
            held.stop = move.stop
            self._count("(exit):advanced")
            self.log.info(str(move))
            return
