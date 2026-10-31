"""Managing a position after the trade is on: stops, partials, and giving up.

A **component a strategy owns**, not a mixin and not an Actor. Three reasons,
in the order they matter:

1. **An exit rule that could close another strategy's position is the magic
   number bug wearing a new hat.** Nautilus puts a `strategy_id` on every
   position; management belongs to whoever opened it, and a component held by
   that strategy cannot reach anyone else's.
2. A component lets each entry choose which exits it runs. A scalp wants
   staleness; a swing whose thesis *is* duration must not have it.
3. It avoids multiple inheritance over a Cython base, which works but makes
   every later question about method order harder than it needs to be.

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

from dataclasses import dataclass, field
from typing import Any

from nautilus_trader.model.data import QuoteTick
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.position import Position as NautilusPosition

from ..domain.models import Intent, Position, Side
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
        self._held[position_id] = Held(intent=intent, best=intent.entry, opened=when)
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


def as_domain(position: NautilusPosition, intent: Intent) -> Position:
    """A Nautilus position in the shape `manage` reads.

    **A bridge, and it is meant to go away.** `manage.advance` and
    `manage.partial` take this desk's own `Position` and read `price_open`,
    `side`, `stop` and `ticket` off it; the spec's step on data structures
    replaces that shape with Nautilus's and deletes this function. Until then a
    translation in one place is better than two position types threaded
    through the policy.

    `stop` comes from the **intent**, not from the position: Nautilus holds a
    stop as a separate order, so a position has no stop field to read, and the
    plan's stop is what `advance` is comparing against anyway. `ticket` is the
    position id as a string hash, because `Move` and `Take` carry it only to
    name themselves in a log line.
    """
    return Position(
        ticket=abs(hash(str(position.id))) % 1_000_000_000,
        symbol=position.instrument_id.symbol.value,
        side=intent.side,
        volume=float(position.quantity),
        price_open=float(position.avg_px_open),
        stop=intent.stop,
        target=intent.target,
        price_current=float(position.avg_px_open),
        profit=float(position.realized_pnl or 0.0),
        opened=position.ts_opened / 1_000_000_000,
    )
