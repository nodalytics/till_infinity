"""Orders, positions and reconciliation against the terminal.

**Reconciliation is the part that matters here and the part most likely to be
got wrong.** `judge-the-desk-on-the-broker-not-the-journal` is the rule: the
broker's view is authoritative and ours is a record. `DEFAULT_MAGIC` is
777_701, and being off by one relabels every strategy as its neighbour - so
the magic is how this client decides which positions are the desk's at all.
"""

from __future__ import annotations

import asyncio
from typing import Any

from nautilus_trader.core.uuid import UUID4
from nautilus_trader.execution.messages import (
    GenerateFillReports,
    GenerateOrderStatusReport,
    GenerateOrderStatusReports,
    GeneratePositionStatusReports,
)
from nautilus_trader.execution.reports import FillReport, OrderStatusReport, PositionStatusReport
from nautilus_trader.live.execution_client import LiveExecutionClient
from nautilus_trader.model.enums import (
    AccountType,
    LiquiditySide,
    OmsType,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSide,
    TimeInForce,
)
from nautilus_trader.model.identifiers import (
    AccountId,
    ClientId,
    ClientOrderId,
    InstrumentId,
    PositionId,
    Symbol,
    TradeId,
    Venue,
    VenueOrderId,
)
from nautilus_trader.model.objects import Money, Price, Quantity

from .config import MT5ExecClientConfig
from .providers import MT5InstrumentProvider
from .transport import connect

#: MT5 position types. 0 buy, 1 sell - and nothing else is a position.
_SIDES = {0: OrderSide.BUY, 1: OrderSide.SELL}

#: The same two codes as a position's side. **Spelled out rather than derived**:
#: `OrderSide` has no `to_position_side`, the method the first version called,
#: and a position report built on it raised `AttributeError` on the first real
#: position.
_POSITION_SIDES = {0: PositionSide.LONG, 1: PositionSide.SHORT}

#: `retcode`s that mean the terminal took the request: 0 is "no code sent",
#: 10008 "placed", 10009 "done".
_OK_RETCODES = (0, 10008, 10009)


class MT5ExecutionClient(LiveExecutionClient):
    """The order side of the venue.

    **Net, not hedging.** MT5 accounts can be either and the distinction is
    not cosmetic: on a netting account a second buy adds to one position and on
    a hedging account it opens a second. `OmsType.NETTING` is declared here
    because that is what the Deriv account is; a hedging account would need
    `HEDGING` and would change what `generate_position_status_reports` means.
    """

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        client_id: ClientId,
        venue: Venue,
        msgbus: Any,
        cache: Any,
        clock: Any,
        instrument_provider: MT5InstrumentProvider,
        config: MT5ExecClientConfig,
    ) -> None:
        super().__init__(
            loop=loop,
            client_id=client_id,
            venue=venue,
            oms_type=OmsType.NETTING,
            account_type=AccountType.MARGIN,
            base_currency=None,
            instrument_provider=instrument_provider,
            msgbus=msgbus,
            cache=cache,
            clock=clock,
            config=config,
        )
        self._cfg = config
        self._bridge = connect(config)
        self._venue = venue

    # ──── lifecycle ────
    async def _connect(self) -> None:
        await self._bridge.open()
        account = await self._bridge.account()
        if not account:
            raise ConnectionError("the bridge returned no account - is the terminal logged in?")
        # **The venue answering is what "connected" means.** Three deploys on
        # 2026-10-09 were built, tagged, health-checked and reported up while
        # running none of the code they claimed, because every check read our
        # own side. An account query is the broker's answer.
        login = account.get("login") or account.get("account")
        self._set_account_id(AccountId(f"{self._venue.value}-{login}"))
        self._log.info(f"account {login}, equity {account.get('equity')}")

    async def _disconnect(self) -> None:
        await self._bridge.close()

    # ──── instruments ────
    async def _instrument(self, instrument_id: InstrumentId) -> Any:
        """The instrument, loaded from the terminal the first time it is asked for.

        **The provider starts empty and nothing else fills it.** The data
        client loads every symbol on connect, but this client has its own
        provider, and the first version never loaded it: `find` returned
        `None`, `_submit_order` raised `AttributeError` on the first order and
        every reconciliation row was skipped as an unknown instrument - a
        silent empty report.

        Loaded on demand rather than all at once because `load_all_async` is
        one round trip per symbol, seven hundred on this account, and an
        execution client only ever needs the few it trades. A loaded
        instrument is also added to the cache, because the execution engine
        sizes fills against the cache and not against this provider.
        """
        found = self._instrument_provider.find(instrument_id)
        if found is None:
            await self._instrument_provider.load_async(instrument_id)
            found = self._instrument_provider.find(instrument_id)
        if found is not None and self._cache.instrument(instrument_id) is None:
            self._cache.add_instrument(found)
        return found

    def _ours(self, row: dict) -> bool:
        return int(row.get("magic") or 0) == self._cfg.magic

    # ──── reconciliation ────
    #
    # **These are the names Nautilus awaits** - `generate_*`, no underscore.
    # The first version defined `_generate_*`, which nothing calls, so on a
    # live node the framework's own versions ran and raised
    # `NotImplementedError`: the desk's open positions were never reconciled.
    async def generate_position_status_reports(
        self, command: GeneratePositionStatusReports | None = None
    ) -> list[PositionStatusReport]:
        wanted = getattr(command, "instrument_id", None)
        reports = []
        for row in await self._bridge.positions():
            if not self._ours(row):
                continue  # not ours; another strategy or a human
            side = _POSITION_SIDES.get(int(row.get("type") if row.get("type") is not None else -1))
            if side is None:
                continue
            instrument_id = InstrumentId(Symbol(str(row.get("symbol"))), self._venue)
            if wanted is not None and instrument_id != wanted:
                continue
            instrument = await self._instrument(instrument_id)
            if instrument is None:
                self._log.warning(f"position {row.get('ticket')}: unknown symbol {instrument_id}")
                continue
            now = self._clock.timestamp_ns()
            reports.append(
                PositionStatusReport(
                    account_id=self.account_id,
                    instrument_id=instrument_id,
                    position_side=side,
                    quantity=Quantity(float(row.get("volume") or 0.0), instrument.size_precision),
                    report_id=UUID4(),
                    ts_last=now,
                    ts_init=now,
                    venue_position_id=PositionId(str(row.get("ticket"))),
                )
            )
        return reports

    async def _order_report(self, row: dict) -> OrderStatusReport | None:
        instrument_id = InstrumentId(Symbol(str(row.get("symbol"))), self._venue)
        instrument = await self._instrument(instrument_id)
        if instrument is None:
            self._log.warning(f"order {row.get('ticket')}: unknown symbol {instrument_id}")
            return None
        now = self._clock.timestamp_ns()
        return OrderStatusReport(
            account_id=self.account_id,
            instrument_id=instrument_id,
            venue_order_id=VenueOrderId(str(row.get("ticket"))),
            order_side=_SIDES.get(int(row.get("type") or 0) % 2, OrderSide.BUY),
            order_type=OrderType.LIMIT,
            time_in_force=TimeInForce.GTC,
            order_status=OrderStatus.ACCEPTED,
            quantity=Quantity(
                float(row.get("volume_current") or row.get("volume") or 0.0),
                instrument.size_precision,
            ),
            filled_qty=Quantity(0, instrument.size_precision),
            report_id=UUID4(),
            ts_accepted=now,
            ts_last=now,
            ts_init=now,
            price=Price(float(row.get("price_open") or 0.0), instrument.price_precision),
        )

    async def generate_order_status_reports(
        self, command: GenerateOrderStatusReports | None = None
    ) -> list[OrderStatusReport]:
        """Resting orders only. A filled order is a position, reported above."""
        wanted = getattr(command, "instrument_id", None)
        reports = []
        for row in await self._bridge.pending():
            if not self._ours(row):
                continue
            if wanted is not None and str(row.get("symbol")) != wanted.symbol.value:
                continue
            report = await self._order_report(row)
            if report is not None:
                reports.append(report)
        return reports

    async def generate_order_status_report(
        self, command: GenerateOrderStatusReport
    ) -> OrderStatusReport | None:
        """One resting order, by venue id (or by the id the cache remembers).

        `None` when it is not resting: filled, cancelled or never ours. The
        base `_query_order` turns that into a warning rather than a state.
        """
        venue_order_id = command.venue_order_id
        if venue_order_id is None and command.client_order_id is not None:
            venue_order_id = self._cache.venue_order_id(command.client_order_id)
        if venue_order_id is None:
            return None
        for row in await self._bridge.pending():
            if self._ours(row) and str(row.get("ticket")) == str(venue_order_id):
                return await self._order_report(row)
        return None

    async def generate_fill_reports(
        self, command: GenerateFillReports | None = None
    ) -> list[FillReport]:
        """From `/history/deals`, filtered to this desk's magic.

        The window is the command's `start`/`end` when it names them, and the
        last day otherwise.
        """
        now_s = int(self._clock.timestamp_ns() / 1e9)
        start = getattr(command, "start", None)
        end = getattr(command, "end", None)
        begin = int(start.timestamp()) if start is not None else now_s - 86_400
        finish = int(end.timestamp()) if end is not None else now_s + 60
        wanted = getattr(command, "instrument_id", None)
        order = getattr(command, "venue_order_id", None)
        reports = []
        for row in await self._bridge.deals(begin, finish):
            if not self._ours(row):
                continue
            instrument_id = InstrumentId(Symbol(str(row.get("symbol"))), self._venue)
            if wanted is not None and instrument_id != wanted:
                continue
            venue_order_id = VenueOrderId(str(row.get("order") or row.get("ticket")))
            if order is not None and venue_order_id != order:
                continue
            instrument = await self._instrument(instrument_id)
            if instrument is None:
                self._log.warning(f"deal {row.get('ticket')}: unknown symbol {instrument_id}")
                continue
            now = self._clock.timestamp_ns()
            reports.append(
                FillReport(
                    account_id=self.account_id,
                    instrument_id=instrument_id,
                    venue_order_id=venue_order_id,
                    trade_id=TradeId(str(row.get("ticket"))),
                    order_side=_SIDES.get(int(row.get("type") or 0), OrderSide.BUY),
                    last_qty=Quantity(float(row.get("volume") or 0.0), instrument.size_precision),
                    last_px=Price(float(row.get("price") or 0.0), instrument.price_precision),
                    commission=Money(
                        float(row.get("commission") or 0.0), instrument.quote_currency
                    ),
                    liquidity_side=LiquiditySide.TAKER,
                    report_id=UUID4(),
                    ts_event=now,
                    ts_init=now,
                )
            )
        return reports

    # ──── commands ────
    #
    # `_query_order` is not overridden: the base class builds a
    # `GenerateOrderStatusReport`, awaits `generate_order_status_report` above
    # and sends what comes back. Overriding it here called the wrong name.
    async def _submit_order(self, command: Any) -> None:
        order = command.order
        instrument = await self._instrument(order.instrument_id)
        if instrument is None:
            self.generate_order_rejected(
                strategy_id=order.strategy_id,
                instrument_id=order.instrument_id,
                client_order_id=order.client_order_id,
                reason=f"{order.instrument_id.symbol.value} is not a symbol this terminal lists",
                ts_event=self._clock.timestamp_ns(),
            )
            return
        body = {
            "symbol": order.instrument_id.symbol.value,
            "order_type": "BUY" if order.side == OrderSide.BUY else "SELL",
            "volume": float(order.quantity),
            "deviation": self._cfg.deviation,
            "magic": self._cfg.magic,
            "comment": str(order.client_order_id)[:31],
            "type_filling": self._cfg.filling,
        }
        if order.has_price:
            body["price"] = float(order.price)
        self.generate_order_submitted(
            strategy_id=order.strategy_id,
            instrument_id=order.instrument_id,
            client_order_id=order.client_order_id,
            ts_event=self._clock.timestamp_ns(),
        )
        raw = await self._bridge.order(body)
        result = raw.get("result") or {}
        trade = raw.get("trade") or {}
        retcode = int(result.get("retcode") or 0)
        # The bridge raises on a bad retcode, so a 2xx already means filled -
        # but reading the code when it is there means a future build that stops
        # raising cannot silently look like a fill.
        if not raw.get("success") or retcode not in _OK_RETCODES:
            self.generate_order_rejected(
                strategy_id=order.strategy_id,
                instrument_id=order.instrument_id,
                client_order_id=order.client_order_id,
                reason=str(result.get("comment") or f"retcode {retcode}"),
                ts_event=self._clock.timestamp_ns(),
            )
            return
        ticket = result.get("order") or trade.get("transaction_broker_id") or 0
        deal = result.get("deal") or ticket
        filled = float(result.get("volume") or trade.get("order_volume") or order.quantity)
        price = float(result.get("price") or trade.get("entry_price") or 0.0)
        now = self._clock.timestamp_ns()
        self.generate_order_accepted(
            strategy_id=order.strategy_id,
            instrument_id=order.instrument_id,
            client_order_id=order.client_order_id,
            venue_order_id=VenueOrderId(str(ticket)),
            ts_event=now,
        )
        # **By keyword, on purpose.** The positional call left out `trade_id`,
        # which sits between `venue_position_id` and `order_side`, so every
        # later argument landed one slot early and every successful fill
        # raised `TypeError`. A keyword call turns the next signature change
        # into a named error instead of a silent reassignment.
        self.generate_order_filled(
            strategy_id=order.strategy_id,
            instrument_id=order.instrument_id,
            client_order_id=order.client_order_id,
            venue_order_id=VenueOrderId(str(ticket)),
            venue_position_id=PositionId(str(ticket)),
            trade_id=TradeId(str(deal)),
            order_side=order.side,
            order_type=order.order_type,
            last_qty=Quantity(filled, instrument.size_precision),
            last_px=Price(price, instrument.price_precision),
            quote_currency=instrument.quote_currency,
            commission=Money(0.0, instrument.quote_currency),
            liquidity_side=LiquiditySide.TAKER,
            ts_event=now,
        )

    @staticmethod
    def _ticket(venue_order_id: Any) -> int:
        try:
            return int(str(venue_order_id)) if venue_order_id else 0
        except ValueError:
            return 0

    async def _modify_order(self, command: Any) -> None:
        """Move a stop and target, and say what happened.

        Every path ends in an event. An order left in `PENDING_UPDATE` is not
        a quiet failure: the engine will not accept another modify or cancel
        for it until something resolves it, and nothing would.
        """
        ticket = self._ticket(command.venue_order_id)
        order = self._cache.order(command.client_order_id)

        def refuse(reason: str) -> None:
            self._log.error(f"modify {command.client_order_id}: {reason}")
            self.generate_order_modify_rejected(
                strategy_id=command.strategy_id,
                instrument_id=command.instrument_id,
                client_order_id=command.client_order_id,
                venue_order_id=command.venue_order_id,
                reason=reason,
                ts_event=self._clock.timestamp_ns(),
            )

        if not ticket:
            refuse("cannot modify an order with no venue id")
            return
        quantity = command.quantity or (order.quantity if order is not None else None)
        if quantity is None:
            refuse("the order is not in the cache, so its quantity is unknown")
            return
        try:
            raw = await self._bridge.modify(
                ticket,
                float(command.trigger_price or 0.0),
                float(command.price or 0.0),
            )
        except Exception as exc:
            refuse(f"bridge: {exc}")
            return
        # Absent keys read as accepted: the bridge raises on a refusal, so a
        # plain 2xx is the success case. A body that *says* otherwise wins.
        retcode = int((raw.get("result") or {}).get("retcode") or 0)
        if raw.get("success") is False or retcode not in _OK_RETCODES:
            refuse(str((raw.get("result") or {}).get("comment") or f"retcode {retcode}"))
            return
        self.generate_order_updated(
            strategy_id=command.strategy_id,
            instrument_id=command.instrument_id,
            client_order_id=command.client_order_id,
            venue_order_id=command.venue_order_id,
            quantity=quantity,
            price=command.price or (order.price if order is not None and order.has_price else None),
            trigger_price=command.trigger_price,
            ts_event=self._clock.timestamp_ns(),
        )

    async def _withdraw(
        self, strategy_id: Any, instrument_id: Any, client_order_id: Any, venue_order_id: Any
    ) -> None:
        """Cancel one ticket and settle the order either way.

        **The broker is asked afterwards, not trusted.** A cancel answers
        `{}` both when it worked and when the ticket was already gone (the
        bridge reads a 404 as "nothing there"), so the response cannot tell a
        cancelled order from one that filled a moment earlier. A resting order
        that is still listed is the one answer that is unambiguous.
        """
        ticket = self._ticket(venue_order_id)

        def refuse(reason: str) -> None:
            self._log.error(f"cancel {client_order_id}: {reason}")
            self.generate_order_cancel_rejected(
                strategy_id=strategy_id,
                instrument_id=instrument_id,
                client_order_id=client_order_id,
                venue_order_id=venue_order_id,
                reason=reason,
                ts_event=self._clock.timestamp_ns(),
            )

        if not ticket:
            refuse("cannot cancel an order with no venue id")
            return
        try:
            await self._bridge.cancel(ticket)
            resting = {int(r.get("ticket") or 0) for r in await self._bridge.pending()}
        except Exception as exc:
            refuse(f"bridge: {exc}")
            return
        if ticket in resting:
            refuse(f"order {ticket} is still resting after the cancel")
            return
        self.generate_order_canceled(
            strategy_id=strategy_id,
            instrument_id=instrument_id,
            client_order_id=client_order_id,
            venue_order_id=venue_order_id,
            ts_event=self._clock.timestamp_ns(),
        )

    async def _cancel_order(self, command: Any) -> None:
        await self._withdraw(
            command.strategy_id,
            command.instrument_id,
            command.client_order_id,
            command.venue_order_id,
        )

    async def _cancel_all_orders(self, command: Any) -> None:
        """Cancel this desk's resting orders, for the instrument and side asked.

        Only orders the cache knows get an event: an engine cannot be told
        about an order it never held. A resting order of ours that the cache
        does not know is cancelled at the terminal and logged.
        """
        wanted = getattr(command, "instrument_id", None)
        side = getattr(command, "order_side", OrderSide.NO_ORDER_SIDE)
        for row in await self._bridge.pending():
            if not self._ours(row):
                continue
            if wanted is not None and str(row.get("symbol")) != wanted.symbol.value:
                continue
            if (
                side != OrderSide.NO_ORDER_SIDE
                and _SIDES.get(int(row.get("type") or 0) % 2) != side
            ):
                continue
            venue_order_id = VenueOrderId(str(row.get("ticket")))
            client_order_id = self._cache.client_order_id(venue_order_id)
            order = self._cache.order(client_order_id) if client_order_id is not None else None
            if order is None:
                self._log.warning(f"cancelling {venue_order_id}, which the cache does not know")
                await self._bridge.cancel(int(row.get("ticket") or 0))
                continue
            await self._withdraw(
                order.strategy_id, order.instrument_id, client_order_id, venue_order_id
            )


__all__ = ["ClientOrderId", "MT5ExecutionClient"]
