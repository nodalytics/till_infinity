"""The entry mechanisms, one Nautilus strategy each.

Three ways an accepted intent reaches the venue, carved out of
`service.Trader` where they were three code paths inside one object. They share
every gate - see [`desk.Desk`](desk.py) - and differ only in `place`.

**`EdgeEntry`** places at market, now. From `Trader._edge_entry`.

**`RestingEntry`** leaves a limit at a named price and withdraws it if price
turns against it first. From `_rest_at_named_price`, `_restable`,
`_leave_with_broker`, `_withdraw` and `_turned_against`.

**`ArrivalEntry`** waits for price to reach a level and for the bar to confirm
a rejection there. From `_arrived`, `_rejected_at`, `_candle_at` and `_park`.

Separate strategies rather than a mode flag, because Nautilus puts a
`strategy_id` on every order and position: *which mechanism took this trade* is
then a fact the framework carries rather than a field we have to remember to
set. That is the same argument as the magic number, one level down.

## The stop and the target go on the order

`Trader._protect` set them afterwards, in a second call, and had to handle the
window where a position existed with no stop. A bracket order has no such
window: Nautilus submits the entry and its two exits as one order list, and the
venue holds all three. Where a venue cannot bracket, the fallback is a stop
submitted from `on_order_filled` - still ours, but one event later rather than
one poll later.
"""

from __future__ import annotations

from nautilus_trader.model.data import QuoteTick
from nautilus_trader.model.enums import OrderSide, TimeInForce

from ..domain.models import Intent, Refusal, Side
from .desk import Desk, DeskConfig


def _side(side: Side) -> OrderSide:
    """This desk's side as Nautilus's.

    A function and not a dict, so a `Side` this does not know raises here
    rather than defaulting to buying.
    """
    if side is Side.BUY:
        return OrderSide.BUY
    if side is Side.SELL:
        return OrderSide.SELL
    raise ValueError(f"{side!r} is neither a buy nor a sell.")


class EdgeEntryConfig(DeskConfig, frozen=True):
    """At market, on an edge signal."""

    #: Submit the stop and target with the entry as one order list, where the
    #: venue supports it. False submits the entry alone and attaches the stop
    #: from `on_order_filled`, which is the fallback for a venue that cannot
    #: bracket - MT5 through the bridge among them.
    bracket: bool = True


class EdgeEntry(Desk):
    """Market order on an accepted intent. The simplest mechanism, and the one
    that proves the shape end to end.

    From `Trader._edge_entry`. What it loses in the port is everything around
    the order: no ticket bookkeeping, no `_reconcile`, no `_orphans`, no
    magic-number juggling. Nautilus's `ExecutionEngine` owns all of it, and
    `on_order_filled` arrives as an event rather than as a poll.
    """

    def __init__(self, config: EdgeEntryConfig) -> None:
        super().__init__(config)
        self._edge = config

    def place(self, intent: Intent) -> None:
        """Send it at market, with its stop and target.

        The quantity comes from the intent, which is where sizing already
        happened: `plans` bounded the loss and the rule turned that into a
        volume. This does not re-size, because two places computing a size is
        how they come to disagree.
        """
        instrument = self.cache.instrument(self._cfg.instrument_id)
        if instrument is None:
            self.log.error(f"no instrument for {self._cfg.instrument_id}")
            return
        quantity = instrument.make_qty(intent.volume)
        if quantity.as_double() <= 0.0:
            # Refused rather than rounded up. A size that rounds to zero is a
            # size the venue cannot take, and nudging it to the minimum would
            # place a trade nobody sized.
            self.log.warning(f"{intent.feed}: volume {intent.volume} rounds to zero")
            self._count("(desk):zero-volume")
            return

        side = _side(intent.side)
        if self._edge.bracket and intent.stop > 0.0 and intent.target > 0.0:
            order_list = self.order_factory.bracket(
                instrument_id=instrument.id,
                order_side=side,
                quantity=quantity,
                sl_trigger_price=instrument.make_price(intent.stop),
                tp_price=instrument.make_price(intent.target),
                time_in_force=TimeInForce.GTC,
            )
            self.submit_order_list(order_list)
            self.log.info(
                f"{intent.feed} {side.name} {quantity} bracketed "
                f"stop {intent.stop} target {intent.target}: {intent.reason}"
            )
            return

        order = self.order_factory.market(
            instrument_id=instrument.id,
            order_side=side,
            quantity=quantity,
        )
        self.submit_order(order)
        self._pending[order.client_order_id] = intent
        self.log.info(f"{intent.feed} {side.name} {quantity} at market: {intent.reason}")

    def on_start(self) -> None:
        super().on_start()
        #: Intents awaiting their fill, so the stop can be attached when a
        #: venue cannot bracket. Keyed by client order id, which is the only
        #: identifier that exists before the venue has answered.
        self._pending: dict[object, Intent] = {}

    def on_order_filled(self, event: object) -> None:
        """Attach the stop, where the entry could not carry it.

        Nautilus emits this; `Trader` polled for it. The difference matters
        beyond tidiness: a poll has a window in which a filled position has no
        stop, and that window is exactly when a fast move would find it.
        """
        pending = getattr(self, "_pending", {})
        intent = pending.pop(getattr(event, "client_order_id", None), None)
        if intent is None or intent.stop <= 0.0:
            return
        instrument = self.cache.instrument(self._cfg.instrument_id)
        if instrument is None:
            return
        quantity = instrument.make_qty(intent.volume)
        protect = self.order_factory.stop_market(
            instrument_id=instrument.id,
            # The stop closes, so it is the other side of the entry.
            order_side=OrderSide.SELL if intent.side is Side.BUY else OrderSide.BUY,
            quantity=quantity,
            trigger_price=instrument.make_price(intent.stop),
            time_in_force=TimeInForce.GTC,
            reduce_only=True,
        )
        self.submit_order(protect)
        self.log.info(f"{intent.feed} stop attached at {intent.stop}")


class RestingEntryConfig(DeskConfig, frozen=True):
    """A limit left at a named price, withdrawn if the setup stops being one."""

    #: How long a parked signal lives, in hours. **A resting order with no
    #: deadline is a trade taken on information that has gone stale.**
    window_hours: float = 4.0
    #: Give up the venue-side order rather than send one that will be refused,
    #: when the price cannot be pushed clear of the stop. The in-process wait
    #: is untouched either way - that is the fallback, and it was the whole
    #: mechanism before resting existed.
    give_up_when_crowded: bool = True


class RestingEntry(Desk):
    """Leave the price with the venue, keep the judgement here.

    From `Trader._rest_at_named_price`, `_restable`, `_leave_with_broker`,
    `_withdraw` and `_turned_against`.

    ## A venue-side limit is only half the arrangement

    **A resting order cannot change its mind.** So anything that would refuse
    the trade *now* has to reach in and take the order back - otherwise the one
    arrangement this was meant to avoid is the one it creates: a fill on a
    setup that had already stopped being worth taking. Every path that drops a
    wait goes through `_withdraw` for that reason, and an order left behind is
    the exact failure a venue-side limit invites.

    This system keeps the judgement and the venue keeps the reflexes, and the
    half that can change its mind has to be able to reach the half that cannot.

    ## The price has to clear the venue's minimum *and* its own stop

    A pending order must sit at least `stops_level` from the market, and the
    resting price is chosen from an edge in volatility units, which on an
    instrument with a wide minimum is inside it. Measured on the live desk:
    Volatility 100 Index reports **138 points at a point of 0.01**, so the
    venue wants 1.38 while a 0.50v edge asked for 0.23 - and four of six rests
    in an hour came back `Invalid price`, with the desk waiting in process for
    a price it had no order to catch.

    Pushing the price out costs nothing if it fills and makes filling less
    likely, which is the trade the edge was already making. What it must **not**
    do is walk the entry through its own stop: the stop does not move with it,
    and a limit on the far side of its stop opens a trade that is already
    beaten. So the pushed price is checked the way the entry itself was, and
    where there is no room the venue-side order is given up rather than sent to
    be refused.
    """

    def __init__(self, config: RestingEntryConfig) -> None:
        super().__init__(config)
        self._resting = config
        #: The order left with the venue, and the intent it was left for. The
        #: intent is a **label**: the decision is re-made on arrival, so this
        #: is not a stale intent waiting to be resurrected.
        self._waiting: dict[object, Intent] = {}
        self._until = 0.0

    def place(self, intent: Intent) -> None:
        """Leave a limit at the intent's entry, pushed clear if it has to be."""
        instrument = self.cache.instrument(self._cfg.instrument_id)
        if instrument is None:
            self.log.error(f"no instrument for {self._cfg.instrument_id}")
            return
        at = self._restable(instrument, intent)
        if at is None:
            self._count("(desk):crowded")
            return
        quantity = instrument.make_qty(intent.volume)
        if quantity.as_double() <= 0.0:
            self.log.warning(f"{intent.feed}: volume {intent.volume} rounds to zero")
            self._count("(desk):zero-volume")
            return

        order = self.order_factory.limit(
            instrument_id=instrument.id,
            order_side=_side(intent.side),
            quantity=quantity,
            price=instrument.make_price(at),
            time_in_force=TimeInForce.GTC,
        )
        self.submit_order(order)
        self._waiting[order.client_order_id] = intent
        self._until = self.clock.timestamp() + self._resting.window_hours * 3_600.0
        self.log.info(f"{intent.feed} resting at {at} until {self._until:.0f}: {intent.reason}")

    def _restable(self, instrument: object, intent: Intent) -> float | None:
        """`intent.entry` moved out to a price the venue will take, or None.

        None means *give up the venue-side order*, not *give up the trade*: the
        in-process wait still runs and still fills at market on arrival.
        """
        room = self._min_distance(instrument)
        at = intent.entry
        if room <= 0.0:
            return at
        reference = self._reference()
        if reference is None or abs(at - reference) >= room:
            return at
        pushed = at - intent.side.sign * room
        # **Never through its own stop.** The stop does not move with the
        # entry, so a limit on the far side of it opens a trade already beaten.
        if (pushed - intent.stop) * intent.side.sign <= 0:
            self.log.info(
                f"not resting {intent.feed} with the venue - it needs {room:.5g} "
                f"and {pushed:.5g} is through the stop at {intent.stop:.5g}"
            )
            return None if self._resting.give_up_when_crowded else at
        self.log.info(
            f"{intent.feed} rest moved out from {at:.5g} to {pushed:.5g} - "
            f"the venue needs {room:.5g}"
        )
        return pushed

    def _min_distance(self, instrument: object) -> float:
        """How far a pending order must sit from the market, in price.

        Nautilus does not model a venue's stops level, so this is read off the
        instrument's own info where the adapter put it and is zero otherwise.
        **Zero means no constraint, which is the right default**: inventing a
        distance would push every rest out on venues that do not ask for it.
        """
        info = getattr(instrument, "info", None) or {}
        points = float(info.get("stops_level") or 0.0)
        return points * float(getattr(instrument, "price_increment", 0.0) or 0.0)

    def _reference(self) -> float | None:
        """The price the venue measures its minimum from."""
        tick = self._tick()
        return None if tick is None else (tick.bid + tick.ask) / 2.0

    # ------------------------------------------------------------ the judgement

    def on_quote_tick(self, tick: QuoteTick) -> None:
        """The judgement half, exercised while the reflex half waits."""
        if not self._waiting:
            return
        if self.clock.timestamp() >= self._until:
            self._withdraw("the window expired")
            return
        if why := self._turned_against(tick):
            self._withdraw(why)

    def _turned_against(self, tick: QuoteTick) -> str:
        """Why this wait should be abandoned now, or "" to keep waiting.

        **Only conditions that would refuse the trade outright.** A signal that
        has merely aged is handled by the window, and one whose numbers moved is
        handled by asking the rule again on arrival - this is for the cases
        where there is no point arriving at all.
        """
        spread = float(tick.ask_price) - float(tick.bid_price)
        if spread <= 0.0:
            return ""
        intent = next(iter(self._waiting.values()), None)
        if intent is None:
            return ""
        # Against the **target**, which is what risk measures it against when
        # the same setting refuses an entry - not against the stop.
        reward = abs(intent.target - intent.entry)
        limit = self.settings.max_spread_fraction
        if reward > 0.0 and limit > 0.0 and spread > reward * limit:
            return f"the spread reached {spread / reward:.0%} of the target, limit is {limit:.0%}"
        return ""

    def _withdraw(self, why: str) -> None:
        """Take the resting order back off the venue.

        Every path that drops a wait comes through here, because an order left
        behind is one that fills on a setup this system has already refused.
        """
        for order_id in list(self._waiting):
            order = self.cache.order(order_id)
            if order is not None and order.is_open:
                self.cancel_order(order)
            intent = self._waiting.pop(order_id, None)
            feed = intent.feed if intent else "?"
            self.log.info(f"withdrew {feed}: {why}")
        self._count(f"(desk):withdrawn-{why.split(maxsplit=1)[0]}")

    def on_order_filled(self, event: object) -> None:
        """The rest filled, so the wait is over and nothing is left behind."""
        self._waiting.pop(getattr(event, "client_order_id", None), None)


class ArrivalEntryConfig(DeskConfig, frozen=True):
    """Parked until price reaches the level, then re-asked and confirmed."""

    #: How long a parked signal lives, in hours.
    window_hours: float = 4.0
    #: Volatility units of turn required to confirm. Zero asks no turn.
    require_turn_vol: float = 0.0
    #: Require a candle that rejected the level on the last closed bar.
    require_candle: bool = True
    #: Insist on **both** witnesses rather than either. A scalp cannot wait
    #: four hours for a bar to close and would otherwise refuse a clean fast
    #: turn for having no candle yet; a swing has the time, and an origin price
    #: merely touched is not one that rejected it.
    needs_both_witnesses: bool = False
    #: How close to the level a wick must come to count, in volatility units.
    candle_tolerance_vol: float = 0.1


class ArrivalEntry(Desk):
    """Hold the signal back until price comes to it, then decide again.

    From `Trader._arrived`, `_park`, `_rejected_at` and `_candle_at`.

    ## Re-asked, not resurrected

    A setup that stopped being worth taking while it waited is refused on
    arrival like any other. So what is parked is the **payload**, not the
    intent: the decision is re-made from it when price gets there. An intent
    held and then placed would be a decision made at a price that has since
    moved.

    ## The order of withdraw-then-ask is the design

    Where this also rests an order with the venue, the order is taken back
    **before** the rule is asked again: if the gates still pass it fills at
    market here, and if they do not the order must already be gone. Leaving it
    would fill a setup this system just refused.

    ## `after_pullback` is what makes the turn witness applicable

    On arrival the payload is marked, and that mark is what lets a turn
    requirement apply **here and only here**. The same momentum reading means
    *arriving at the level* before the wait and *the fall has not finished*
    after it, so before a pullback the turn witness is not merely unsatisfied -
    **it is not applicable**, and asking it there would refuse every
    straight-to-market entry for failing a test that does not apply.

    ## An unavailable witness is an unconfirmed one

    `Trader._candle_at` fetched bars from the broker and treated a failure as
    *unconfirmed*, because "treating missing data as a pass would make this
    silently inactive on every instrument whose bars fail, which is the failure
    mode that looks like working code". Here the bars arrive by subscription
    into a `Candles` indicator, so that failure mode is gone - but the
    semantics are kept: fewer than two closed bars confirms nothing.
    """

    def __init__(self, config: ArrivalEntryConfig) -> None:
        super().__init__(config)
        self._arrival = config
        #: The parked payload, its trigger price and side, and its deadline.
        self._payload: dict[str, object] | None = None
        self._trigger = 0.0
        self._side: Side | None = None
        self._until = 0.0
        self._candles: object | None = None

    def on_start(self) -> None:
        """Register a `Candles` on the entry's own bar type.

        Gated on confirmed bars by default, which is the point: a hammer half
        way through its bar is not a hammer, it is a bar that currently looks
        like one.
        """
        super().on_start()
        from ..indicators import Candles

        self._candles = Candles(confirm=True)
        self.register_indicator_for_bars(self._cfg.bar_type, self._candles)

    def place(self, intent: Intent) -> None:
        """Park it. The entry price is the trigger, not an order.

        Called when the gates have passed, which is why this is `place` and not
        a gate: the decision to *wait* is a decision to take the trade at a
        better price, and a signal that failed a gate is not parked at all.
        """
        self._payload = dict(intent.features) | {"feed": intent.feed}
        self._trigger = intent.entry
        self._side = intent.side
        self._until = self.clock.timestamp() + self._arrival.window_hours * 3_600.0
        self.log.info(f"{intent.feed} parked for {self._trigger:.5g}: {intent.reason}")

    # ------------------------------------------------------------- the arrival

    def on_quote_tick(self, tick: QuoteTick) -> None:
        """Wake the parked signal if price has come to it, or drop it if stale."""
        if self._payload is None or self._side is None:
            return
        if self.clock.timestamp() >= self._until:
            self.log.info(f"expired waiting for {self._trigger:.5g}")
            self._forget("the window expired")
            return
        price = float(tick.ask_price) if self._side is Side.BUY else float(tick.bid_price)
        if (price - self._trigger) * self._side.sign > 0:
            return  # not there yet
        payload = self._payload
        self._forget("price arrived, deciding here")
        self.log.info(f"reached {self._trigger:.5g} - reconsidering")
        # Marked before the rule is asked, which is what makes the turn witness
        # applicable. See the class docstring.
        features = payload.setdefault("features", {})
        if isinstance(features, dict):
            features["after_pullback"] = 1.0
        verdict = self.consider(payload)
        if isinstance(verdict, Intent):
            if refusal := self._unconfirmed(verdict):
                self._count(f"(desk):{refusal.gate}")
                self.log.info(f"{verdict.feed} arrived unconfirmed: {refusal.detail}")
                return
            self.taken += 1
            self._fill_at_market(verdict)

    def _forget(self, why: str) -> None:
        self._payload = None
        self._side = None
        self._trigger = 0.0
        self._count(f"(desk):unparked-{why.split(maxsplit=1)[0]}")

    def _unconfirmed(self, intent: Intent) -> Refusal | None:
        """Refuse a trade nothing has confirmed yet. Either witness will do.

        Unless `needs_both_witnesses`, in which case both are required - the
        disjunction is right for a scalp and the conjunction for a swing.
        """
        wants_turn = self._arrival.require_turn_vol > 0.0
        wants_candle = self._arrival.require_candle
        if not (wants_turn or wants_candle):
            return None
        both = self._arrival.needs_both_witnesses

        asked: list[str] = []
        held: list[str] = []
        if wants_turn:
            asked.append("turn")
            pressure = float(intent.features.get("pressure_vol") or 0.0)
            turned = pressure if intent.side is Side.BUY else -pressure
            if turned >= self._arrival.require_turn_vol:
                if not both:
                    return None
            else:
                held.append(f"turned {turned:.2f}v, wanted {self._arrival.require_turn_vol:.2f}v")
        if wants_candle:
            asked.append("candle")
            found = self._candle_at(intent)
            if found:
                if not both:
                    return None
            else:
                held.append("no candle rejected the level")
        if both and not held:
            return None
        return Refusal(
            gate="unconfirmed",
            detail=f"asked {'+'.join(asked)}: {'; '.join(held)}",
            feed=intent.feed,
        )

    def _candle_at(self, intent: Intent) -> str:
        """The pattern rejecting this level on the last closed bar, or "".

        An unavailable answer is an empty one, not an exception.
        """
        candles = self._candles
        if candles is None or len(getattr(candles, "bars", [])) < 2:
            return ""
        level = float(intent.features.get("level") or intent.entry)
        tolerance = abs(level) * self._arrival.candle_tolerance_vol / 100.0
        return candles.confirms(level, want_up=intent.side is Side.BUY, tolerance=tolerance)

    def _fill_at_market(self, intent: Intent) -> None:
        """Take it here, now that price has come and the witnesses agree."""
        instrument = self.cache.instrument(self._cfg.instrument_id)
        if instrument is None:
            return
        quantity = instrument.make_qty(intent.volume)
        if quantity.as_double() <= 0.0:
            self._count("(desk):zero-volume")
            return
        order_list = self.order_factory.bracket(
            instrument_id=instrument.id,
            order_side=_side(intent.side),
            quantity=quantity,
            sl_trigger_price=instrument.make_price(intent.stop),
            tp_price=instrument.make_price(intent.target),
            time_in_force=TimeInForce.GTC,
        )
        self.submit_order_list(order_list)
        self.log.info(f"{intent.feed} filled on arrival at {self._trigger:.5g}")
