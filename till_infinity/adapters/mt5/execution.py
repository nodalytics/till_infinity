"""Orders, positions and reconciliation against the terminal.

**Reconciliation is the part that matters here and the part most likely to be
got wrong.** `judge-the-desk-on-the-broker-not-the-journal` is the rule: the
broker's view is authoritative and ours is a record. `DEFAULT_MAGIC` is
777_701, and being off by one relabels every strategy as its neighbour - so
the magic is how this client decides which positions are the desk's at all.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
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
from nautilus_trader.model.objects import AccountBalance, Currency, Money, Price, Quantity

from ...utils.topics import VENUE_TRADING
from .bridge import COMMENT_MAX
from .config import MT5ExecClientConfig
from .providers import MT5InstrumentProvider
from .redact import redact
from .transport import connect

#: MT5 position types. 0 buy, 1 sell - and nothing else is a position.
_SIDES = {0: OrderSide.BUY, 1: OrderSide.SELL}

#: The same two codes as a position's side. **Spelled out rather than derived**:
#: `OrderSide` has no `to_position_side`, the method the first version called,
#: and a position report built on it raised `AttributeError` on the first real
#: position.
_POSITION_SIDES = {0: PositionSide.LONG, 1: PositionSide.SHORT}

#: MT5 trade server return codes this client acts on.
#:
#: **0 is not one of them.** The first version accepted it as "no code sent",
#: and `Bridge._send` then read a 404 as `None` on every route, which every
#: write method turned into `{}` - so an empty body parsed to retcode 0, 0 was
#: OK, and "the bridge did not answer" was indistinguishable from "done". A
#: real `order_send` never returns 0. A request is confirmed by a *positive*
#: code, never by the absence of a failure.
#:
#: Both halves were fixed. `_send` now takes `empty_on_404` and only the tick
#: and bar history routes pass it, so a 404 on a write raises; and 0 is refused
#: here whatever the transport does.
DONE = 10009
PLACED = 10008
#: `TRADE_RETCODE_CLIENT_DISABLES_AT`: **AutoTrading is off in the terminal.**
#:
#: Not a property of the order. Every submission gets it until a human turns
#: the button back on, so it is reported as a venue-level fault rather than as
#: one order's rejection reason - which is how it stayed invisible: a desk
#: reading per-order rejections sees twelve unrelated refusals, not one cause.
AUTOTRADING_OFF = 10027

#: How long a rejection reason may be. Applied in `_reject`, **after**
#: `_scrub`, so no caller can shorten a string before the key has been taken
#: out of it - see that docstring.
REASON_MAX = 200
#: `SYMBOL_FILLING_*` bits mapped to the bridge's own spelling, in the order to
#: prefer when a symbol accepts more than one.
#:
#: **This is per symbol and is not a preference.** Measured on the live
#: terminal on 2026-11-04: EURUSD, GBPUSD, USDJPY and XAUUSD all report
#: `filling_mode=1` - **FOK only** - and this client sent `IOC`, which came
#: back `10030, Unsupported filling mode` on **every market order**. FOK
#: filled at retcode 10009 on the same symbol a second later.
#:
#: It was invisible because nothing went through this body builder against a
#: real venue: a `FakeBridge` accepts whatever it is handed, and the one live
#: test posted its own JSON without the field at all, so the bridge's default
#: was used and a market order filled.
#:
#: FOK is first because it is the mode this account has and the most widely
#: offered; a broker that is IOC-only reports bit 2 and gets IOC.
FILLING_BITS: tuple[tuple[int, str], ...] = ((1, "FOK"), (2, "IOC"), (4, "RETURN"))

#: How often to re-read the account and the AutoTrading flag, in seconds.
#:
#: **A one-shot publish on connect is not enough, and the ordering is why.**
#: Nautilus connects its clients *before* it starts actors, so the heartbeat
#: subscribed to `VENUE_TRADING` after the execution client had already
#: published - it read `can_trade: None` on a node whose log said "the terminal
#: will accept orders". A repeating read also means AutoTrading going off
#: mid-session is noticed within a minute rather than at the next order.
ACCOUNT_REFRESH_S = 60.0

#: Seconds between sweeps for a position the broker is holding without a stop.
#:
#: **The desk's own view cannot answer this**, which is the whole reason the
#: sweep exists. On 2026-11-10 two live positions ran with `sl 0.0 tp 0.0`
#: while `ManagedExit._protects()` passed and `_guards()` reported that the
#: entry had already bracketed them: Nautilus held the legs, MT5 did not. The
#: container's log carried **zero** `closing` lines, so nothing had failed
#: loudly - the two sides simply disagreed, and `judge-the-desk-on-the-broker-
#: not-the-journal` is the standing rule for which one to believe.
#:
#: 60 seconds, matching `position_check_interval_secs`: a sweep slower than
#: Nautilus's own reconciliation would let a naked position outlive a
#: divergence the engine had already noticed.
UNPROTECTED_SWEEP_S = 60.0

#: Where the legs the broker confirmed are written down, so a restart can still
#: repair them. Beside the status file, which is on the image's volume.
#:
#: **The sweep could not repair a position that went naked across a restart.**
#: It copies the cache's own stop order, and reconciliation rebuilds positions
#: without the bracket legs that protected them - so on 2026-11-10 a live
#: XAUUSD short reported "no stop at the broker and no stop order in the cache
#: to copy" every sixty seconds and had to be given a stop by hand. The cache
#: is still the first source; this is the fallback that outlives the process.
PROTECTION_PATH = Path(os.environ.get("TILL_PROTECTION_PATH") or "/app/.data/protection.json")
#: Placed or done: the terminal has the request.
_TAKEN = (PLACED, DONE)


def _comment(client_order_id: Any) -> str:
    """The client order id as MT5 will store it, tail first.

    **The length is `bridge.COMMENT_MAX` and not a number repeated here**, for
    the reason this function exists at all: 31 was wrong, every order carried
    it, and every order was refused. One owner for the limit, on the wire.

    The discriminating part of a
    Nautilus client order id is its tail - `...-001-EURUSD_E270-3` names the
    trader, the desk and the counter, while the head is a timestamp the
    terminal already records against the deal. Taking the first 31 was
    harmless only while the tag was four characters: once it carries the
    symbol, `O-20261105-230145-001-EURUSD_E270-3` truncates to
    `O-20261105-230145-001-EURUSD_E2`, which is the same string for every
    order that desk sends and for its neighbours on other symbols too.

    Informational either way - this desk finds its own orders by `magic` and
    correlates fills by ticket, never by comment - but a comment that cannot
    tell two desks apart is no use to the person reading the terminal, which
    is the only reason it is sent.
    """
    return str(client_order_id)[-COMMENT_MAX:]


class _Refusal(Exception):  # noqa: N818 - a control-flow signal, not an error to catch widely
    """A modify that must be answered with a rejection, carrying the reason."""


class ReconciliationError(RuntimeError):
    """The broker's book could not be established, so none is reported.

    Raised instead of returning a shorter list. A report generator that skips
    what it cannot read tells the engine the account is smaller than it is,
    and a desk that believes it is flat re-opens the position it already
    holds.
    """


def _retcode(raw: dict) -> int:
    return int(((raw or {}).get("result") or {}).get("retcode") or 0)


def _confirmed(raw: dict, codes: tuple[int, ...] = (DONE,)) -> bool:
    """A positive signal: the envelope says success *and* carries a real code."""
    return bool(raw) and raw.get("success") is True and _retcode(raw) in codes


def _field(leg: Any) -> str:
    """Which field of the position this leg *is* - `sl`, `tp`, or neither.

    Read from the order type and not from `tags`, for the same reason
    `_submit_order_list` reads the shape that way: tags are this desk's
    convention and another strategy may not set them.
    """
    kind = getattr(leg, "order_type", None)
    if kind == OrderType.STOP_MARKET:
        return "sl"
    if kind == OrderType.LIMIT:
        return "tp"
    return ""


def _leg_id(ticket: Any, order: Any, entry: Any) -> str:
    """The venue id for one leg of a bracket.

    The entry keeps the bare ticket, because it *is* the order the terminal
    acknowledged. A stop or a target is a field on the position that ticket
    opened, so it gets the ticket and a side - enough for a modify to find the
    position and for a cancel to know which side to clear.
    """
    if order is entry:
        return str(ticket)
    return f"{ticket}-SL" if order.order_type == OrderType.STOP_MARKET else f"{ticket}-TP"


class MT5ExecutionClient(LiveExecutionClient):
    """The order side of the venue.

    **The account is hedging and this declares `NETTING`, knowingly.** The
    live terminal answers `margin_mode: 2` - `ACCOUNT_MARGIN_MODE_RETAIL_
    HEDGING` - recorded in `tests/test_mt5_live.py` beside the `trade_mode`
    the demo guard reads. The distinction is not cosmetic: on a netting
    account a second buy adds to one position, and on a hedging account it
    opens a second, so the engine can carry one aggregate where the broker
    holds a stack.

    The expensive half of that was the *exit*, and it is fixed: a market order
    on the opposite side does not close a hedged position, it opens one facing
    the other way, which is why `_close_out` routes every reduce-only market
    order through `Bridge.close_position` and its ticket. See that method for
    what it cost.

    What is left is the bookkeeping. Declaring `HEDGING` would give each
    broker ticket its own Nautilus position and change what
    `generate_position_status_reports` means, what `cache.positions_open()`
    hands a rule, and what `exits.Held` is keyed on - so it is a deliberate
    piece of work and not a one-line flip, and it is not done here.
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
        #: Per symbol, because `filling_mode` is a property of the symbol and
        #: not of the account. Asked once each: it does not change inside a
        #: session, and an extra round trip on every order is latency on the
        #: money path.
        self._filling: dict[str, str] = {}
        #: Deals dropped from a fill report because their instrument would not
        #: resolve. Non-zero means a fill report was incomplete.
        self.skipped_deals = 0

    # ──── lifecycle ────
    def _scrub(self, value: Any) -> str:
        """Text safe to log or to put in an event: the API key removed."""
        return redact(value, (getattr(self._cfg, "api_key", None),))

    async def _connect(self) -> None:
        try:
            await self._bridge.open()
            account = await self._bridge.account()
        except Exception as exc:
            raise ConnectionError(self._scrub(exc)) from None
        if not account:
            raise ConnectionError("the bridge returned no account - is the terminal logged in?")
        # **The venue answering is what "connected" means.** Three deploys on
        # 2026-10-09 were built, tagged, health-checked and reported up while
        # running none of the code they claimed, because every check read our
        # own side. An account query is the broker's answer.
        login = account.get("login") or account.get("account")
        self._set_account_id(AccountId(f"{self._venue.value}-{login}"))
        self._log.info(f"account {login}, equity {account.get('equity')}")
        self._publish_account(account)
        await self._check_trading()
        self._refresh = self.create_task(self._refresh_account())
        self._sweeper = self.create_task(self._sweep_unprotected())

    async def _check_trading(self) -> None:
        """Read the terminal's AutoTrading flag and say so, loudly if it is off.

        **`account()` cannot answer this.** MT5 spells `trade_allowed` twice:
        on the account it is the broker's permission, and on the terminal it is
        the AutoTrading button. An order is checked against the second. On
        2026-11-04 the terminal held `trade_allowed: false` while the account
        held `true`, `/account/health` said healthy and `/terminal/ping`
        answered 200 - four signals, three green, over a desk that could not
        place a single order.

        **Not fatal.** A terminal that will not trade is an ordinary weekend,
        and `terminal.py` makes the same argument about launch: refusing to
        start then would make a Sunday deploy impossible. Unreadable is also
        not false - a failed read publishes nothing rather than claiming the
        venue is shut.
        """
        try:
            allowed = await self._bridge.can_trade()
        except Exception as exc:
            self._log.warning(f"could not read the terminal's AutoTrading flag: {self._scrub(exc)}")
            return
        self._publish_trading(allowed, "terminal_info on connect")

    def _publish_trading(self, allowed: bool, cause: str) -> None:
        """Put the flag on the bus, and log what it means rather than the number."""
        if allowed:
            self._log.info(f"the terminal will accept orders ({cause})")
        else:
            self._log.error(
                f"AUTOTRADING IS OFF on the terminal ({cause}): every order returns "
                f"{AUTOTRADING_OFF} and nothing this desk trades can fill. The "
                f"account's own trade_allowed and /account/health both read healthy "
                f"regardless. Fixed on the terminal, not here."
            )
        try:
            self._msgbus.publish(VENUE_TRADING, {"can_trade": bool(allowed), "cause": cause})
        except Exception as exc:  # pragma: no cover - the bus is the framework's
            self._log.warning(f"could not publish the venue trading flag: {exc}")

    async def _disconnect(self) -> None:
        # Both loops, because a sweeper left running against a closed bridge
        # logs a failed read every minute for the life of the process - and a
        # sweep that is only failing is indistinguishable from one that is
        # finding nothing, which is the state this whole mechanism exists to
        # make visible.
        for name in ("_refresh", "_sweeper"):
            task = getattr(self, name, None)
            if task is not None:
                task.cancel()
                setattr(self, name, None)
        await self._bridge.close()

    async def _refresh_account(self) -> None:
        """Re-read the account and the AutoTrading flag, forever.

        Two things need repeating rather than doing once. The **account state**
        is what puts the account in the cache, and the portfolio prices margin
        against it, so a figure from connect-time goes stale. The **AutoTrading
        flag** has to be re-published because actors start after clients
        connect: the heartbeat subscribes too late to hear the connect-time
        publish and read `can_trade: None` on a node whose own log said the
        terminal would accept orders.

        Failures are logged and the loop continues. A dropped read is not a
        reason to stop reporting, and `_check_trading` already refuses to claim
        anything from a read that failed.
        """
        while True:
            try:
                await asyncio.sleep(ACCOUNT_REFRESH_S)
                found = await self._bridge.account()
                if found:
                    self._publish_account(found)
                await self._check_trading()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - the transport's shapes
                self._log.warning(f"account refresh failed: {self._scrub(exc)}")

    async def _sweep_unprotected(self) -> None:
        """Attach the stop the cache intended to any position the broker holds bare.

        **Judged on the broker, never on our own view.** Two live positions ran
        with `sl 0.0 tp 0.0` on 2026-11-10 while every desk-side check passed:
        `ManagedExit._protects()` was True and `_guards()` reported the entry
        had already bracketed them. Nautilus held the legs; MT5 did not. The
        log carried **zero** `closing` lines, so nothing failed loudly - the
        two sides disagreed silently, which is the one failure a desk-side
        check cannot see by construction.

        The stop is **the cache's own**, never a number invented here. An open
        stop order on the instrument is what the rule asked for, and copying it
        to the venue is a repair; choosing a distance would be this adapter
        taking a trading decision, which is not its job. A position with no
        cached stop to copy is **reported and left alone** - there is nothing
        to repair and inventing one would be worse than saying so.

        `_protect` reads before it writes, so a position already carrying the
        right prices is skipped rather than sent a no-op modify that MT5
        refuses and this bridge answers 400 - the mistake that once read as a
        protected position's legs being rejected.

        Failures are logged and the loop continues. A dropped read is not a
        reason to stop sweeping, and a sweep that stopped silently would
        restore exactly the blindness it exists to remove.
        """
        while True:
            try:
                await asyncio.sleep(UNPROTECTED_SWEEP_S)
                await self._repair_unprotected()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - the transport's shapes
                self._log.warning(f"unprotected sweep failed: {self._scrub(exc)}")

    async def _repair_unprotected(self) -> int:
        """One pass over both legs. Returns how many positions were repaired.

        **Each leg is the broker's own price where it holds one.** A modify
        carries the pair, so attaching a missing stop with `tp 0.0` would take
        the target off a position that had one - and the target is swept for
        the same reason as the stop, because a position whose target leg was
        dropped runs to its stop or to a manual close with nothing in front of
        it.
        """
        repaired = 0
        rows = await self._bridge.positions()
        self._forget({int(row.get("ticket") or 0) for row in rows})
        for row in rows:
            if not self._ours(row):
                continue  # another strategy's, or a human's
            at_stop = float(row.get("sl") or 0.0)
            at_target = float(row.get("tp") or 0.0)
            if at_stop and at_target:
                continue
            ticket = int(row.get("ticket") or 0)
            symbol = str(row.get("symbol") or "")
            if not ticket or not symbol:
                continue
            instrument_id = InstrumentId(Symbol(symbol), self._venue)
            # **The legs sit on the closing side, and an entry order does
            # not.** A resting limit order on the instrument is a target when
            # it would close this position and an unfilled entry when it would
            # add to it; copying the second onto the position as a target
            # would hand it a "target" at the price it was trying to get in at.
            closing = OrderSide.SELL if int(row.get("type") or 0) % 2 == 0 else OrderSide.BUY
            wanted = at_stop or self._cached_stop(instrument_id, closing=closing)
            target = at_target or self._cached_target(instrument_id, closing=closing)
            if wanted is None or target is None:
                # **The cache first, this second.** The cache is live truth and
                # a trailing stop moves in it; this file is what outlives the
                # process. Reconciliation rebuilds a position without the
                # bracket legs that protected it, so after a restart the cache
                # has nothing to copy and only the record does.
                recorded = self._protections().get(str(ticket)) or {}
                if wanted is None:
                    wanted = float(recorded.get("sl") or 0.0) or None
                if target is None:
                    target = float(recorded.get("tp") or 0.0) or None
            if not at_stop and wanted is None:
                # **Said, not guessed.** A naked position with nothing in the
                # cache to copy is a different fault from a dropped leg, and
                # naming it is what lets an operator tell them apart.
                self._log.error(
                    f"position {ticket} on {symbol} has no stop at the broker and "
                    f"no stop order in the cache and none on record to copy - "
                    f"it is running unprotected and this sweep has nothing to "
                    f"repair it with"
                )
            if wanted is None and target is None:
                continue
            instrument = await self._instrument(instrument_id)
            if instrument is None:
                continue
            missing, why = await self._protect(ticket, sl=wanted, tp=target, instrument=instrument)
            if missing:
                self._log.error(
                    f"position {ticket} on {symbol} is unprotected and the repair "
                    f"did not land: {why}"
                )
                continue
            given = ", ".join(
                f"{name} {price}"
                for name, price, held in (("sl", wanted, at_stop), ("tp", target, at_target))
                if price is not None and not held
            )
            if not given:
                continue
            repaired += 1
            self._log.warning(
                f"position {ticket} on {symbol} was running without {given} at the "
                f"broker and has been given the cache's own - the broker and the "
                f"engine had diverged"
            )
        return repaired

    def _cached_stop(self, instrument_id: Any, *, closing: Any) -> Any:
        """The stop price the engine believes this instrument's position has.

        An open `STOP_MARKET` order on the instrument, which is the leg a
        bracket leaves behind. `None` when there is not exactly one.

        **Exactly one, and it refuses to choose between several.** Two stop
        orders on one instrument is the state `manage.py` says must never
        exist - three things on this desk can move a stop and exactly one may -
        so it is a fault in its own right, and picking one of them here would
        repair a position by guessing which rule owns it. Selecting the
        "tightest" needs the position's side to even be defined, which this
        would have to read and could get wrong; saying so costs nothing and a
        wrong stop is worse than a reported one.
        """
        # **`order_type` is an int enum, not a name.** `str(order.order_type)`
        # is `"3"`, so matching the word `STOP_MARKET` in it never fires and
        # this returned None for every position - the same shape as
        # `BarSpecification.aggregation` reading `"12"` against `"MINUTE"`,
        # found in this repo the same day. Compared against the enum.
        prices = [
            price
            for order in self._cache.orders_open(instrument_id=instrument_id)
            if order.order_type == OrderType.STOP_MARKET
            and order.side == closing
            and (price := getattr(order, "trigger_price", None)) is not None
        ]
        if len(prices) == 1:
            return prices[0]
        if len(prices) > 1:
            self._log.error(
                f"{instrument_id.symbol} has {len(prices)} open stop orders in the "
                f"cache, which `manage.py` says cannot happen - refusing to guess "
                f"which one protects the position"
            )
        return None

    def _cached_target(self, instrument_id: Any, *, closing: Any) -> Any:
        """The target price the engine believes this instrument's position has.

        The `LIMIT` half of `_cached_stop`: `_place` reads a bracket's target
        off `child.price` of a `LIMIT` child, so that is the leg to copy.
        `None` when there is not exactly one, and `None` is also the honest
        answer for a rule that set no target - there is nothing to repair, and
        a distance invented here would be this adapter taking a trading
        decision.

        `closing` is what keeps an unfilled limit **entry** out of this. A
        desk that enters on a limit leaves a resting order on the same side as
        the position it is building, and its price is where the rule wanted
        in - the one price that must never be installed as a target.
        """
        prices = [
            price
            for order in self._cache.orders_open(instrument_id=instrument_id)
            if order.order_type == OrderType.LIMIT
            and order.side == closing
            and (price := getattr(order, "price", None)) is not None
        ]
        if len(prices) == 1:
            return prices[0]
        if len(prices) > 1:
            self._log.error(
                f"{instrument_id.symbol} has {len(prices)} open limit orders in the "
                f"cache - refusing to guess which one targets the position"
            )
        return None

    def _remember(self, ticket: int, stop: float, target: float, confirmed: bool = True) -> None:
        """Write down a position's legs, keyed by the broker's own ticket.

        Usually called from `_protect` after it has re-read the position, so
        what is recorded is what the venue holds and not what was asked for -
        the distinction that `_report_legs` exists to make, since a retcode of
        10009 over a naked position has happened here.

        **`confirmed=False` is the one case where what was asked for is worth
        recording anyway**, and it is the hole that left two positions naked
        for six hours. `_protect` has a third path: the modify was not refused
        and the position cannot be read back. It returns "nothing missing"
        there on purpose - a missing row is not evidence a position is naked,
        and rejecting on one rejected the legs of positions the broker was
        protecting - but it then wrote nothing, so the claim had nothing behind
        it.

        That matters because the record is the *only* durable source.
        `_sweep_unprotected` prefers the live cache, and reconciliation rebuilds
        a position without the bracket legs that protected it, so after any
        restart the cache has nothing to copy. With no record either, the sweep
        reports "none on record to copy" and repairs nothing, every minute,
        forever. On 2026-11-11 EURUSD and Germany 40 sat stopless from 13:52
        and 18:29 on exactly that path.

        The flag is stored so a reader can tell a leg the broker confirmed from
        one this process only asked for. The sweep treats them alike, which is
        correct: it only copies a leg onto a position the broker is showing
        with **no** stop, where the stop that was asked for is the right one to
        put back.

        Atomic, because a crash between truncate and write would leave the
        fallback empty exactly when it is needed. Never raises: a desk that
        cannot write this file still trades, and a lost record degrades the
        sweep to what it did before this existed.
        """
        if not ticket or stop <= 0.0:
            return  # nothing worth remembering, and a zero is not a stop
        try:
            held = self._protections()
            held[str(int(ticket))] = {
                "sl": float(stop),
                "tp": float(target or 0.0),
                "confirmed": bool(confirmed),
            }
            PROTECTION_PATH.parent.mkdir(parents=True, exist_ok=True)
            temp = PROTECTION_PATH.with_suffix(".tmp")
            temp.write_text(json.dumps(held))
            temp.replace(PROTECTION_PATH)
        except Exception as exc:  # pragma: no cover - a full or read-only disk
            self._log.warning(f"could not record protection for {ticket}: {self._scrub(exc)}")

    def _protections(self) -> dict[str, dict]:
        """The recorded legs. An unreadable or absent file is an empty one."""
        try:
            found = json.loads(PROTECTION_PATH.read_text())
        except Exception:
            return {}
        return found if isinstance(found, dict) else {}

    def _forget(self, live: set[int]) -> None:
        """Drop records for tickets the broker no longer holds.

        **Pruned against the open positions rather than on a timer**, so the
        file cannot grow without bound and cannot carry a closed ticket's stop
        into anything. Called from the sweep, which has just read the
        positions anyway.
        """
        held = self._protections()
        keep = {name: row for name, row in held.items() if int(name) in live}
        if len(keep) == len(held):
            return
        try:
            PROTECTION_PATH.parent.mkdir(parents=True, exist_ok=True)
            temp = PROTECTION_PATH.with_suffix(".tmp")
            temp.write_text(json.dumps(keep))
            temp.replace(PROTECTION_PATH)
        except Exception as exc:  # pragma: no cover
            self._log.warning(f"could not prune the protection record: {self._scrub(exc)}")

    def _publish_account(self, account: dict) -> None:
        """Put the broker's balances in the cache, which nothing else did.

        **The healthcheck was failing on a connected desk because of this.**
        `node/status.py` reads `venue_connected` from
        `cache.accounts()` having a `balance_total`, on the argument that an
        account in the cache is the venue's own word. Nothing ever generated an
        `AccountState`, so the cache held no account, `venue_connected` was
        **permanently false**, and the container reported `unhealthy` with
        "the venue has not answered" while the log said `Connected` and
        reconciliation had succeeded.

        That is the third spelling of one bug: the check first read
        `cache.exec_clients()`, which does not exist, then `cache.accounts()`,
        which was empty for this reason. A check that cannot pass is worse than
        no check, because it trains a reader to ignore the one signal that is
        meant to be trusted.

        **`total` must equal `locked + free`** or Nautilus refuses the balance,
        and MT5 defines `margin_free = equity - margin`, so `free` is computed
        from the identity rather than read. `margin_free` is logged when it
        disagrees, because a broker that breaks the identity is worth knowing
        about and is not worth failing over.
        """
        try:
            currency = Currency.from_str(str(account.get("currency") or "USD"))
            equity = float(account.get("equity") or 0.0)
            margin = float(account.get("margin") or 0.0)
            free = equity - margin
            reported_free = account.get("margin_free")
            if reported_free is not None and abs(float(reported_free) - free) > 0.01:
                self._log.warning(
                    f"margin_free {reported_free} is not equity - margin ({free:.2f}); "
                    f"using the identity, since a balance whose parts do not sum is refused"
                )
            self.generate_account_state(
                balances=[
                    AccountBalance(
                        Money(equity, currency),
                        Money(max(margin, 0.0), currency),
                        Money(max(free, 0.0), currency),
                    )
                ],
                margins=[],
                reported=True,
                ts_event=self._clock.timestamp_ns(),
            )
        except Exception as exc:
            self._log.error(
                f"could not publish the account state ({self._scrub(exc)}): the "
                f"healthcheck reads the cache for this and will report the venue "
                f"as unanswered"
            )

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

    async def _filling_for(self, symbol: str) -> str:
        """The filling mode this symbol will actually accept.

        `TRADING_MT5_FILLING` names a preference and the symbol has the final
        say: a configured mode the symbol does not support is replaced by one
        it does, loudly, because the alternative is `10030` on every order.

        An unreadable `filling_mode` falls back to the configured value rather
        than guessing - the field is absent on some bridge versions, and
        refusing to trade over a missing hint would be worse than sending the
        mode that was asked for.
        """
        found = self._filling.get(symbol)
        if found is not None:
            return found
        wanted = str(self._cfg.filling or "FOK").upper()
        try:
            mask = int((await self._bridge.symbol_info(symbol)).get("filling_mode") or 0)
        except Exception as exc:
            self._log.warning(
                f"{symbol}: could not read filling_mode ({self._scrub(exc)}), "
                f"sending the configured {wanted}"
            )
            self._filling[symbol] = wanted
            return wanted
        supported = [name for bit, name in FILLING_BITS if mask & bit]
        if not supported:
            self._log.warning(
                f"{symbol}: filling_mode={mask} names no mode this client knows, "
                f"sending the configured {wanted}"
            )
            chosen = wanted
        elif wanted in supported:
            chosen = wanted
        else:
            chosen = supported[0]
            self._log.warning(
                f"{symbol}: does not accept {wanted} (filling_mode={mask} is "
                f"{'/'.join(supported)}), sending {chosen}. Sending an "
                f"unsupported mode returns 10030 on every order and fills nothing."
            )
        self._filling[symbol] = chosen
        return chosen

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
            instrument_id = InstrumentId(Symbol(str(row.get("symbol"))), self._venue)
            if wanted is not None and instrument_id != wanted:
                continue
            side = _POSITION_SIDES.get(int(row.get("type") if row.get("type") is not None else -1))
            if side is None:
                raise ReconciliationError(
                    f"position {row.get('ticket')} has type {row.get('type')!r}, which is "
                    f"neither a buy nor a sell - the book cannot be reported"
                )
            instrument = await self._instrument(instrument_id)
            if instrument is None:
                raise ReconciliationError(
                    f"position {row.get('ticket')} is in {instrument_id.symbol}, which the "
                    f"terminal will not describe - reporting the book without it would say "
                    f"the account is smaller than it is"
                )
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

    async def _order_report(self, row: dict) -> OrderStatusReport:
        instrument_id = InstrumentId(Symbol(str(row.get("symbol"))), self._venue)
        instrument = await self._instrument(instrument_id)
        if instrument is None:
            raise ReconciliationError(
                f"resting order {row.get('ticket')} is in {instrument_id.symbol}, which the "
                f"terminal will not describe"
            )
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
            reports.append(await self._order_report(row))
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
                # **Loud, not fatal.** Positions and resting orders are state
                # the desk acts on, so an unreadable one raises. A deal is
                # history: the position report carries the same fact, and a
                # node that cannot start over a day-old fill is its own
                # outage. It is counted and logged at error so it is seen.
                self.skipped_deals += 1
                self._log.error(
                    f"deal {row.get('ticket')} skipped: {instrument_id.symbol} unknown "
                    f"({self.skipped_deals} skipped since start)"
                )
                continue
            now = self._clock.timestamp_ns()
            # **The deal's own second, not the clock.** `ts_event` is what
            # orders fills and what a lookback window is measured against, so
            # stamping a day-old deal "now" tells the engine a fill has just
            # happened - and on a reconciliation that decides the state the
            # desk is reported to be in. A deal that cannot be dated is still a
            # deal and keeps the clock, the same argument `Bridge.deals` makes
            # about a row whose time will not parse.
            try:
                stamped = int(float(row.get("time") or 0.0) * 1e9) or now
            except (TypeError, ValueError):
                stamped = now
            # **The position this deal belongs to, where the broker names it.**
            # Without it `position_check_interval_secs` cannot do its job: it
            # spots a position the cache holds and the venue does not, queries
            # for the lost fills, and then cannot attribute them on a hedging
            # account where one symbol carries several.
            #
            # That is the phantom. On 2026-11-11 ETHUSD, US Oil, XAUUSD and UK
            # Brent Oil all closed on their own stops before 11:00 and the desk
            # was still refusing entries on them as "already held by EXTERNAL"
            # at 19:30 - five instruments out of the book for a session,
            # because the engine never learned the broker had closed them.
            position = row.get("position_id") or row.get("position") or 0
            reports.append(
                FillReport(
                    account_id=self.account_id,
                    instrument_id=instrument_id,
                    venue_order_id=venue_order_id,
                    venue_position_id=PositionId(str(int(position))) if position else None,
                    trade_id=TradeId(str(row.get("ticket"))),
                    order_side=_SIDES.get(int(row.get("type") or 0), OrderSide.BUY),
                    last_qty=Quantity(float(row.get("volume") or 0.0), instrument.size_precision),
                    last_px=Price(float(row.get("price") or 0.0), instrument.price_precision),
                    commission=Money(
                        float(row.get("commission") or 0.0), instrument.quote_currency
                    ),
                    liquidity_side=LiquiditySide.TAKER,
                    report_id=UUID4(),
                    ts_event=stamped,
                    ts_init=max(now, stamped),
                )
            )
        return reports

    # ──── commands ────
    #
    # `_query_order` is not overridden: the base class builds a
    # `GenerateOrderStatusReport`, awaits `generate_order_status_report` above
    # and sends what comes back. Overriding it here called the wrong name.
    def _reject(self, order: Any, reason: str) -> None:
        """Reject with a bounded reason, **redacted before it is shortened**.

        The order of those two matters and the callers must not have to
        remember it. `_scrub` removes the API key by matching it, so cutting
        the text first can split the key across the boundary, leave the
        pattern unmatchable and put the first half of a credential into an
        event that is logged and published. Shortening after redaction can
        only ever remove characters from an already-safe string.
        """
        self.generate_order_rejected(
            strategy_id=order.strategy_id,
            instrument_id=order.instrument_id,
            client_order_id=order.client_order_id,
            reason=self._scrub(reason)[:REASON_MAX],
            ts_event=self._clock.timestamp_ns(),
        )

    def _reject_all(self, orders: tuple, reason: str) -> None:
        """Reject every order of a bracket for the one reason.

        A bracket is submitted as a single MT5 order, so its parts share one
        fate. Rejecting only the entry would leave the stop and the target
        `INITIALIZED` forever - orders the engine believes are on their way to
        a venue that was never told about them.
        """
        for order in orders:
            self._reject(order, reason)

    def _fill(
        self,
        order: Any,
        instrument: Any,
        *,
        ticket: Any,
        trade_id: Any,
        qty: float,
        px: float,
        commission: float = 0.0,
    ) -> None:
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
            trade_id=TradeId(str(trade_id)),
            order_side=order.side,
            order_type=order.order_type,
            last_qty=Quantity(qty, instrument.size_precision),
            last_px=Price(px, instrument.price_precision),
            quote_currency=instrument.quote_currency,
            commission=Money(commission, instrument.quote_currency),
            liquidity_side=LiquiditySide.TAKER,
            ts_event=self._clock.timestamp_ns(),
        )

    async def _deal_for(self, ticket: int) -> dict | None:
        """This desk's newest deal for an order ticket in the last day, if any.

        Raises when the history cannot be read: "no deal" and "could not ask"
        are different answers and only the first one is a fact.
        """
        now_s = int(self._clock.timestamp_ns() / 1e9)
        found = [
            row
            for row in await self._bridge.deals(now_s - 86_400, now_s + 60)
            if self._ours(row) and int(row.get("order") or 0) == ticket
        ]
        return found[-1] if found else None

    def _fault(self, orders: tuple, exc: BaseException) -> None:
        """Reject what is still open, naming the exception. **The last resort.**

        Nothing below this may reach Nautilus's `create_task` wrapper, because
        that wrapper logs the *command* and not the exception: the whole trace
        of a failed submit was `Error on 'submit_order: SubmitOrder(...)'`, the
        engine then polled five times for an `OrderStatusReport` that was never
        coming, and resolved the order itself as
        `OrderRejected(reason='UNKNOWN')`.

        `UNKNOWN` is the engine's word for "this client said nothing", so it is
        only ever correct when nothing *can* be said. An exception can always
        say its type and its message, so this names those instead.

        Only orders that are still open are rejected: `_place` rejects on the
        paths it knows about, and rejecting an order twice is an invalid state
        transition that would raise from inside the handler for the error.
        """
        self._log.error(f"submit failed: {type(exc).__name__}: {exc}")
        self._reject_all(
            tuple(o for o in orders if not getattr(o, "is_closed", False)),
            f"{type(exc).__name__}: {exc}",
        )

    async def _submit_order(self, command: Any) -> None:
        """One order, with any stop or target the command carries."""
        params = getattr(command, "params", None) or {}
        try:
            await self._place(command.order, sl=params.get("sl"), tp=params.get("tp"))
        except Exception as exc:
            self._fault((command.order,), exc)

    async def _submit_order_list(self, command: Any) -> None:
        """A bracket, as the one MT5 order a bracket is here.

        **Nothing could trade without this.** The base class raises
        `NotImplementedError`, every strategy on this desk submits an entry
        with a stop and a target as an OTO list, and so every order died in
        the adapter with the engine reporting nothing worse than an error on a
        command. Quotes flowed, the terminal said it would accept orders, the
        healthcheck was green, and no trade had ever been placed through
        Nautilus.

        **MT5 has no separate orders for a stop and a target.** They are
        properties of the position, set by `sl` and `tp` on the entry and
        changed afterwards through `/positions/modify`, which is addressed by
        the position's own ticket - which is why `_modify_order` already works
        that way. So the three Nautilus orders become one request, and the
        children are accepted against the entry's ticket: there is no second
        ticket for them to carry, and leaving them `INITIALIZED` would be the
        engine waiting forever for a venue that has nothing to say.

        The shape is read from the order *types*, not the `tags`. Tags are
        this desk's convention and a different strategy may not set them;
        `STOP_MARKET` and `LIMIT` are what the orders are.
        """
        orders = tuple(command.order_list.orders)
        try:
            await self._place_bracket(orders)
        except Exception as exc:
            self._fault(orders, exc)

    async def _place_bracket(self, orders: tuple) -> None:
        """The bracket proper. Separate so `_submit_order_list` can guard it.

        **Not named `_submit_*`.** Every `_submit_...` on this class is a
        Nautilus hook, and `test_every_hook_shaped_method_exists_on_the_
        framework_base` refuses a private method shaped like one that the base
        does not declare - which is how an override that the framework never
        calls gets noticed instead of silently never running.
        """
        entry = next((o for o in orders if o.parent_order_id is None), None)
        if entry is None:
            self._reject_all(orders, "no entry in the list: every order names a parent")
            return
        children = tuple(o for o in orders if o is not entry)

        sl: float | None = None
        tp: float | None = None
        for child in children:
            if child.order_type == OrderType.STOP_MARKET:
                sl = float(child.trigger_price)
            elif child.order_type == OrderType.LIMIT:
                tp = float(child.price)
            else:
                # Refusing the bracket rather than the one leg. A bracket with
                # a leg silently dropped is a position whose risk is not what
                # the strategy sized it for.
                self._reject_all(
                    orders,
                    f"{child.order_type.name} cannot be a bracket leg on MT5: a stop is "
                    f"STOP_MARKET and a target is LIMIT",
                )
                return
        await self._place(entry, sl=sl, tp=tp, also=children)

    async def _place(
        self,
        order: Any,
        *,
        sl: Any = None,
        tp: Any = None,
        also: tuple = (),
    ) -> None:
        """Send one order to the terminal and report what came back.

        `also` are orders that share this one's fate - the stop and target of
        a bracket, which MT5 carries on the entry rather than as orders of
        their own. They are submitted, rejected and accepted with it.
        """
        together = (order, *also)
        # Only the two shapes this client can express. A stop order has no
        # `price`, so `has_price` was False and it went out as a market order.
        if await self._unsendable(order, together):
            return
        instrument = await self._instrument(order.instrument_id)
        if instrument is None:
            self._reject_all(
                together, f"{order.instrument_id.symbol.value} is not a symbol this terminal lists"
            )
            return
        body = {
            "symbol": order.instrument_id.symbol.value,
            "order_type": "BUY" if order.side == OrderSide.BUY else "SELL",
            "volume": float(order.quantity),
            "deviation": self._cfg.deviation,
            "magic": self._cfg.magic,
            "comment": _comment(order.client_order_id),
            "type_filling": await self._filling_for(order.instrument_id.symbol.value),
        }
        if order.has_price:
            body["price"] = float(order.price)
        # A stop or target the strategy attached, passed through as given. The
        # HTTP bridge's market-order route *requires* `sl`; this client never
        # invents one.
        for key, value in (("sl", sl), ("tp", tp)):
            if value is not None:
                body[key] = float(value)
        for leg in together:
            self.generate_order_submitted(
                strategy_id=leg.strategy_id,
                instrument_id=leg.instrument_id,
                client_order_id=leg.client_order_id,
                ts_event=self._clock.timestamp_ns(),
            )
        try:
            raw = await self._bridge.order(body)
        except Exception as exc:
            # **An exception here is a rejection, and it has to be said out
            # loud.** `_send` raises `BridgeError` carrying the status code
            # and the first 200 characters of the body - the one piece of
            # evidence that distinguishes a 422 on the body's shape from a 500
            # in the terminal from a lost connection. Letting it propagate
            # gave Nautilus's own wrapper, which logs the *command* and not
            # the exception, so the whole trace was
            # `Error on 'submit_order: SubmitOrder(...)'` with no cause.
            #
            # The engine then polled for an `OrderStatusReport` five times,
            # got nothing, and resolved the order itself as
            # `OrderRejected(reason='UNKNOWN')`. On 2026-11-08/09 that is what
            # all 13 of this desk's first orders looked like: 13 submitted, 0
            # accepted, 0 filled, every reason `UNKNOWN`, across three rule
            # classes and nine instruments - a single adapter fault wearing
            # the costume of thirteen unrelated venue refusals.
            self._log.error(f"{order.client_order_id}: the bridge refused the order: {exc}")
            self._reject_all(together, f"bridge: {exc}")
            return
        result = raw.get("result") or {}
        trade = raw.get("trade") or {}
        retcode = _retcode(raw)
        if raw.get("success") is not True or retcode not in _TAKEN:
            # Includes `{}`: an empty answer is not an acceptance. It may mean
            # the order was never placed (a 404 is "no such route") or that it
            # was and the reply was lost; rejecting is the safe reading and
            # the next position report corrects it if it was placed.
            if retcode == AUTOTRADING_OFF:
                # **The cause is the terminal, not this order.** Published so
                # the heartbeat reports a desk that cannot trade; without it
                # the only trace was one rejection reason per order, which
                # reads as twelve unrelated refusals.
                self._publish_trading(False, f"retcode {AUTOTRADING_OFF} on an order")
            self._reject_all(
                together,
                str(result.get("comment") or f"retcode {retcode or 'missing'}: not confirmed"),
            )
            return
        ticket = result.get("order") or trade.get("transaction_broker_id") or 0
        if not ticket:
            self._log.error(f"{order.client_order_id}: confirmed with no ticket - reconcile")
            self._reject_all(together, "confirmed by the terminal but no ticket came back")
            return
        # **The legs are the entry's ticket with a suffix, not the ticket
        # itself.** MT5 answers a bracket with one order ticket; the stop and
        # the target are fields on the position it opens, not orders with
        # tickets of their own.
        #
        # Giving all three the bare ticket looked right - `_modify_order`
        # resolves it to the position and sets `sl`/`tp`, which is correct -
        # and was dangerous on cancel. Cancelling the target would call
        # `/orders/<entry ticket>`, which is not a resting order, so the
        # cancel is unconfirmed; the ticket is not in the pending listing; and
        # `_withdraw` then falls through to its deal fallback, finds **the
        # entry's own opening deal**, and reports the *target* as filled at
        # the entry's price. A fabricated fill, after which the engine's
        # position differs from the broker's.
        #
        # The suffix keeps `_ticket` resolving to the position for a modify
        # while letting a cancel see which side it was asked to withdraw.
        await self._report_legs(
            order, ticket=ticket, also=also, sl=sl, tp=tp, instrument=instrument, retcode=retcode
        )
        # **A fill is only a market order that came back DONE.** 10008 is
        # PLACED - a working order - and a pending order's DONE means placed,
        # not filled. Reporting either as a fill gave the desk a position it
        # did not have. Those fills arrive through the broker's deals.
        if order.order_type != OrderType.MARKET or retcode != DONE:
            return
        price = float(result.get("price") or trade.get("entry_price") or 0.0)
        qty = float(result.get("volume") or trade.get("order_volume") or 0.0)
        deal = result.get("deal") or 0
        if price <= 0 or qty <= 0:
            # Done at the broker but unpriced. Rejecting would tell the engine
            # there is no position when there is one, so ask the deals; failing
            # that, leave the order accepted and let reconciliation find it.
            try:
                row = await self._deal_for(int(ticket))
            except Exception as exc:
                row = None
                self._log.error(
                    f"{order.client_order_id}: no fill price, deals: {self._scrub(exc)}"
                )
            if row is None:
                self._log.error(f"{order.client_order_id}: done with no fill price - reconcile")
                return
            price, qty = float(row.get("price") or 0.0), float(row.get("volume") or 0.0)
            deal = row.get("ticket") or deal
            if price <= 0 or qty <= 0:
                return
        self._fill(order, instrument, ticket=ticket, trade_id=deal or ticket, qty=qty, px=price)

    async def _close_out(self, order: Any, together: tuple) -> bool:
        """A reduce-only market order is **a close by ticket**, not a new order.

        Returns whether it was handled, in the same shape as `_attach_stop`.

        **This account is a hedging account.** `tests/test_mt5_live.py` records
        the live terminal answering `margin_mode: 2`, which is
        `ACCOUNT_MARGIN_MODE_RETAIL_HEDGING`, and on a hedging account a market
        order on the opposite side does **not** close anything - it opens a
        second position facing the other way. So every exit this desk sent went
        out as a bare `SELL` and the terminal did what it was asked: on
        2026-11-11 a `ZonesEdge-BTCUSD` long reported closed at -3.01 while the
        broker was left holding a short.

        The divergence is the expensive half. The adapter reports the fill,
        the engine nets it against the long because this client declares
        `OmsType.NETTING`, and from then on Nautilus believes it is flat while
        the broker is not: a position with no stop, no target and no rule
        watching it. Every "closed" alert this desk has sent had that shape.

        `Bridge.close_position` is the route that does close - it sends the
        opposite deal **with `position` set to the ticket**, which is the one
        thing that makes MT5 reduce rather than open. It has existed, and
        tested, the whole time and nothing in this client had ever called it:
        the dead-route failure `venue-faults-hide-below-the-strategy` is about,
        where a rule that never fires and a route that never works read alike.

        **Several positions, not one.** Under hedging, a rule that adds to a
        winner holds a *stack* of tickets on one symbol while Nautilus carries
        one aggregate position, so a close for the aggregate quantity cannot
        be one ticket's close. The stack is walked oldest first until the
        requested volume is met, which is what a reader means by closing a
        position and what the engine's single fill then describes.
        """
        if order.order_type != OrderType.MARKET or not bool(
            getattr(order, "is_reduce_only", False)
        ):
            return False
        symbol = order.instrument_id.symbol.value
        instrument = await self._instrument(order.instrument_id)
        if instrument is None:
            self._reject_all(together, f"{symbol} is not a symbol this terminal lists")
            return True
        try:
            stack = await self._closable(order, symbol)
        except Exception as exc:
            # Refused rather than sent as a plain order. Falling back to a bare
            # market order is precisely the behaviour being fixed, and a desk
            # that cannot read its own book must not act on it.
            self._reject(order, f"cannot read the terminal's book to close {symbol}: {exc}")
            return True
        if not stack:
            # The same argument `_attach_stop` makes about a stop with nothing
            # to protect: believing this process holds what the broker does not
            # is the state to surface, not to paper over with a new position.
            self._reject(order, f"no open {symbol} position of this desk's to close")
            return True

        self.generate_order_submitted(
            strategy_id=order.strategy_id,
            instrument_id=order.instrument_id,
            client_order_id=order.client_order_id,
            ts_event=self._clock.timestamp_ns(),
        )
        wanted = float(order.quantity)
        done = 0.0
        last: dict[str, Any] = {}
        for ticket, held in stack:
            if done >= wanted - 1e-12:
                break
            part = min(float(held.get("volume") or 0.0), wanted - done)
            if part <= 0.0:
                continue
            try:
                raw = await self._bridge.close_position(ticket, part)
            except Exception as exc:
                self._log.error(f"{order.client_order_id}: closing {ticket} failed: {exc}")
                break
            if raw.get("success") is not True or _retcode(raw) not in _TAKEN:
                detail = str((raw.get("result") or {}).get("comment") or "not confirmed")
                self._log.error(f"{order.client_order_id}: closing {ticket}: {detail}")
                break
            last = raw
            done += part

        if done <= 0.0:
            self._reject(order, f"the terminal confirmed no close of {symbol}")
            return True
        self.generate_order_accepted(
            strategy_id=order.strategy_id,
            instrument_id=order.instrument_id,
            client_order_id=order.client_order_id,
            venue_order_id=VenueOrderId(str(stack[0][0])),
            ts_event=self._clock.timestamp_ns(),
        )
        result = last.get("result") or {}
        price = float(result.get("price") or 0.0)
        if price <= 0.0:
            # Closed at the broker but unpriced. The position is gone either
            # way, so the fill is reported at the last quote rather than left
            # for reconciliation to find - an engine that still believes it
            # holds this is the state that produced the bug above.
            price = self._last_price(order)
        if price <= 0.0:
            self._log.error(f"{order.client_order_id}: closed with no price - reconcile")
            return True
        self._fill(
            order,
            instrument,
            ticket=result.get("order") or stack[0][0],
            trade_id=result.get("deal") or result.get("order") or stack[0][0],
            qty=done,
            px=price,
        )
        if done < wanted - 1e-12:
            # Said out loud rather than inferred from two numbers in a journal.
            # A partial close leaves the remainder unmanaged by any rule, which
            # is the same exposure the whole method exists to stop.
            self._log.error(
                f"{order.client_order_id}: closed {done:g} of {wanted:g} on {symbol} - "
                f"the remainder is still open at the broker"
            )
        return True

    async def _closable(self, order: Any, symbol: str) -> list[tuple[int, dict]]:
        """This desk's open positions a reduce-only order would close.

        **Opposite side only.** A `SELL` closes a long, and a row on the same
        side as the order is not something this order may touch - that is the
        check whose absence let a close open a position.

        Ordered with the ticket Nautilus named first, then oldest first. The
        named one is the position the engine is actually talking about;
        `venue_position_id` is this client's own `PositionId(str(ticket))`, so
        it resolves straight back to a ticket when the cache has it.
        """
        want = 0 if order.side == OrderSide.SELL else 1
        rows = [
            row
            for row in await self._bridge.positions()
            if self._ours(row)
            and str(row.get("symbol")) == symbol
            and int(row.get("type") or 0) % 2 == want
            and float(row.get("volume") or 0.0) > 0.0
            and int(row.get("ticket") or 0)
        ]
        rows.sort(key=lambda row: int(row.get("time") or row.get("ticket") or 0))
        named = self._named_ticket(order)
        if named:
            rows.sort(key=lambda row: int(row.get("ticket") or 0) != named)
        return [(int(row.get("ticket") or 0), row) for row in rows]

    def _named_ticket(self, order: Any) -> int:
        """The broker ticket the engine's own position carries, or 0.

        Never raises and never guesses: an unresolvable id simply leaves the
        stack in time order, which is what a reader means by closing first
        what was opened first.

        **The order may not carry it yet.** `Strategy.close_position` builds
        the market order and submits it with `position_id=position.id` as a
        *command* field; the order's own `position_id` is assigned by the
        execution engine. So the cache is asked by client order id as well,
        which is the join that holds at submit time.
        """
        try:
            position_id = getattr(order, "position_id", None) or self._cache.position_id(
                order.client_order_id
            )
            if position_id is None:
                return 0
            position = self._cache.position(position_id)
            found = getattr(position, "venue_position_id", None)
            return int(str(found)) if found is not None else 0
        except Exception:
            return 0

    def _last_price(self, order: Any) -> float:
        """The side a close prints against, from the cache. 0.0 when unknown."""
        try:
            quote = self._cache.quote_tick(order.instrument_id)
            if quote is None:
                return 0.0
            return float(quote.bid_price if order.side == OrderSide.SELL else quote.ask_price)
        except Exception:
            return 0.0

    async def _unsendable(self, order: Any, together: tuple) -> bool:
        """Whether this order cannot go to the terminal as an order of its own.

        Split out for the reason `_report_legs` was: `_place` sits on the
        branch and return limits, and this is a decision worth finding on its
        own rather than a line inside a longer function.

        Only the two shapes this client can express go to the terminal. A
        reduce-only stop is handled instead of refused - see `_attach_stop`,
        and a reduce-only *market* order is a close rather than an order at
        all - see `_close_out`, which is the one that cost money.
        """
        if await self._close_out(order, together):
            return True
        if order.order_type in (OrderType.MARKET, OrderType.LIMIT):
            return False
        if await self._attach_stop(order):
            return True
        self._reject_all(together, f"{order.order_type.name} orders are not supported on MT5 here")
        return True

    async def _attach_stop(self, order: Any) -> bool:
        """A standalone reduce-only stop is **this position's stop**, not an order.

        Returns whether it was handled, so `_place` can go on refusing every
        other order type.

        **The bug this closes left a live position naked.** `EdgeEntry` sends a
        bracket where it can and otherwise a bare market order, attaching the
        stop on the fill as a reduce-only `STOP_MARKET` - the fallback whose
        own docstring says a poll "has a window in which a filled position has
        no stop, and that window is exactly when a fast move would find it".
        This client refused that order outright as an unsupported type, so the
        fallback could never land and `SurpriseProfile.protective_stop = True`
        was a claim the venue path could not honour.

        Measured on 2026-11-09: BTCUSD short 0.1 opened at 19:20:27 from a bare
        entry and sat at `sl 0.0 tp 0.0` with this desk's magic. The same shape
        is already recorded against ticket 5828118661, open 90 minutes naked,
        whose cause `_report_legs` records as still open - this is a cause.

        MT5 has no separate stop order: a stop is a field on the position, set
        by `/positions/modify`, which is exactly the translation `_place`
        already performs for a bracket's legs. So the stop is put on the
        position and the order is accepted against `<ticket>-SL` - the same id
        a bracket leg gets, so `_modify_order` can trail it afterwards and
        `_ticket` resolves it to the position.

        A `reduce_only` stop with no position to reduce is **rejected, not
        ignored**: it means this process believes it holds something the broker
        does not, and the one thing worse than an unprotected position is an
        unprotected position reported as protected.
        """
        if order.order_type != OrderType.STOP_MARKET or not bool(
            getattr(order, "is_reduce_only", False)
        ):
            return False
        trigger = float(getattr(order, "trigger_price", 0.0) or 0.0)
        if trigger <= 0.0:
            return False
        instrument = await self._instrument(order.instrument_id)
        if instrument is None:
            return False

        self.generate_order_submitted(
            strategy_id=order.strategy_id,
            instrument_id=order.instrument_id,
            client_order_id=order.client_order_id,
            ts_event=self._clock.timestamp_ns(),
        )
        symbol = order.instrument_id.symbol.value
        try:
            held = self._protectable(order, symbol, await self._bridge.positions())
        except Exception as exc:
            self._reject(order, f"cannot read the terminal's book: {exc}")
            return True
        if held is None:
            self._reject(order, f"no open {symbol} position of this desk's to put a stop on")
            return True

        ticket = int(held.get("ticket") or 0)
        if not ticket:
            self._reject(order, f"the open {symbol} position carries no ticket")
            return True
        # The target is carried through unchanged. `/positions/modify` sets
        # both fields at once, so passing 0 would clear a target the position
        # is already holding.
        target = float(held.get("tp") or 0.0)
        naked, why = await self._protect(
            ticket, sl=trigger, tp=target or None, instrument=instrument
        )
        if "sl" in naked:
            self._log.error(f"{order.client_order_id}: {why}")
            self._reject(order, why)
            return True
        self.generate_order_accepted(
            strategy_id=order.strategy_id,
            instrument_id=order.instrument_id,
            client_order_id=order.client_order_id,
            venue_order_id=VenueOrderId(f"{ticket}-SL"),
            ts_event=self._clock.timestamp_ns(),
        )
        self._log.info(f"{order.client_order_id}: stop {trigger} set on position {ticket}")
        return True

    def _protectable(self, order: Any, symbol: str, rows: Any) -> dict | None:
        """The position an attached stop is for, or `None`.

        **`next()` over the symbol was wrong on a hedging account**, and this
        account is one. A reduce-only `SELL` stop protects a *long*; with a
        short open on the same symbol - normal here, and exactly what the close
        bug used to leave behind - the first matching row can be the short, so
        the stop landed on a position it would not close while the one it was
        sized for stayed bare.

        Two orderings, both of which matter:

        * **The closing side only.** A stop that cannot close the position it
          is put on is not that position's stop.
        * **Bare first, then newest.** Among several on that side, the one
          without a stop is the one that needs this; overwriting a stop the
          desk is trailing would move a live stop *and* leave the new position
          naked. Newest breaks the remaining tie, because this arrives on the
          fill of the entry that just opened.
        """
        want = 0 if order.side == OrderSide.SELL else 1
        found = [
            row
            for row in rows or ()
            if self._ours(row)
            and str(row.get("symbol")) == symbol
            and int(row.get("type") or 0) % 2 == want
            and int(row.get("ticket") or 0)
        ]
        if not found:
            return None
        found.sort(
            key=lambda row: (
                float(row.get("sl") or 0.0) > 0.0,
                -int(row.get("time") or row.get("ticket") or 0),
            )
        )
        return found[0]

    async def _report_legs(
        self,
        order: Any,
        *,
        ticket: Any,
        also: tuple,
        sl: Any,
        tp: Any,
        instrument: Any,
        retcode: Any,
    ) -> None:
        """Accept the legs the venue is actually holding, and reject the rest.

        Split out of `_place` to keep it under the complexity limits, but it
        is also the one place that decides what this desk *claims* about a
        position, which is worth being able to find.
        """
        # **A retcode does not say whether the protection exists.** Ticket
        # 5828118661 was open 90 minutes at `sl 0.0 tp 0.0` with our magic
        # while this client reported both legs accepted, because the only
        # thing read was `retcode 10009`. So the position is read, and what it
        # holds decides what is claimed.
        #
        # It is read *before* anything is written, because the deal usually
        # does carry the stop: EURUSD 0.01 at ask 1.11382 sent with `sl
        # 1.10882 tp 1.11882` read back holding both on 2026-11-06.
        # `trade_exemode: 2` says nothing either way - all 17 non-FX
        # instruments here report mode 2. Asking `/positions/modify` for
        # prices already held gives MT5 nothing to change, so it refuses and
        # this bridge answers `400`; a first cut at this rejected the legs of
        # every protected position for it. Why 5828118661 was naked is still
        # open - the stop may have sat inside `trade_stops_level`.
        #
        # Accepted **after** this, not before: an accepted order cannot then
        # be rejected, and a leg the venue is not holding must not be
        # reported as live.
        naked: frozenset[str] = frozenset()
        why = ""
        # `retcode == DONE` as well as MARKET, and for the same reason the
        # fill below needs it: 10008 is PLACED, a working order, and a
        # position only exists once the deal is done. `/positions/modify`
        # addresses a position, and sending a resting order there posted its
        # limit price as a target once already.
        if (
            (sl is not None or tp is not None)
            and order.order_type == OrderType.MARKET
            and retcode == DONE
        ):
            naked, why = await self._protect(int(ticket), sl=sl, tp=tp, instrument=instrument)
        refused = tuple(leg for leg in also if _field(leg) in naked)
        if refused:
            self._log.error(f"{order.client_order_id}: {why}")
            self._reject_all(refused, why)
        for leg in (order, *also):
            if leg in refused:
                continue
            self.generate_order_accepted(
                strategy_id=leg.strategy_id,
                instrument_id=leg.instrument_id,
                client_order_id=leg.client_order_id,
                venue_order_id=VenueOrderId(_leg_id(ticket, leg, order)),
                ts_event=self._clock.timestamp_ns(),
            )

    async def _protect(
        self, ticket: int, *, sl: Any, tp: Any, instrument: Any
    ) -> tuple[frozenset[str], str]:
        """Put the stop and target on the position; say which did not land.

        Returns the fields the venue is **not** holding and why. Empty means
        the position carries what was asked.

        **Read before writing.** A deal on this broker *does* carry the `sl`
        and `tp` sent with it - EURUSD 0.01 at ask 1.11382 with `sl 1.10882
        tp 1.11882` in the deal body read back holding both on 2026-11-06, and
        `trade_exemode: 2` implies nothing either way, since all 17 non-FX
        instruments on this book report mode 2. A modify asking for prices the
        position already holds therefore has nothing to change: MT5 refuses
        it, this bridge answers `400`, and reading that as a failed stop
        rejected the legs of a position the broker was protecting. So a
        position that is already right is left alone.

        **Then judge on the position, not on the answer.** Whatever the modify
        said, the verdict comes from reading the position afterwards. A
        refusal over a position that holds the stop is noise; a confirmation
        over one that does not is a lie.

        **A missing row is not evidence.** A position can be a moment behind
        the deal that opened it, so a position that cannot be seen is not a
        naked one: a confirmed modify stands on its own, and only a refusal
        with nothing to look at is reported as unprotected.
        """
        stop = float(sl) if sl is not None else 0.0
        target = float(tp) if tp is not None else 0.0
        both = frozenset(f for f, v in (("sl", stop), ("tp", target)) if v)
        if not both:
            return frozenset(), ""
        digits = int(getattr(instrument, "price_precision", 5) or 5)

        held = await self._held(ticket)
        if held is not None and not self._shortfall(held, stop, target, digits):
            self._remember(ticket, stop, target)
            return frozenset(), ""

        refused = ""
        try:
            raw = await self._bridge.modify(ticket, stop, target)
        except Exception as exc:
            refused = self._scrub(exc)
        else:
            if not _confirmed(raw):
                comment = (raw.get("result") or {}).get("comment")
                refused = comment or f"retcode {_retcode(raw) or 'missing'}: not confirmed"

        held = await self._held(ticket)
        if held is None:
            if refused:
                # A refusal with nothing to look at is the one case that is
                # reported as unprotected, and it records nothing: the terminal
                # has said it will not take this stop, so a record of it would
                # only have the sweep ask again for a leg already declined.
                return both, f"the terminal would not put the stop on {ticket}: {refused}"
            # **Optimistic verdict, pessimistic record.** The modify was taken
            # and the position cannot be read, so this is still reported as
            # landed - see `_remember`, where the whole argument is - but the
            # stop is written down unconfirmed so the next sweep has something
            # to repair with if it did not in fact land.
            self._remember(ticket, stop, target, confirmed=False)
            return frozenset(), ""
        missing = self._shortfall(held, stop, target, digits)
        if not missing:
            self._remember(ticket, stop, target)
            return frozenset(), ""
        asked = ", ".join(f"{f} {a}" for f, a in (("sl", stop), ("tp", target)) if a)
        holds = ", ".join(f"{f} {held.get(f) or 0.0}" for f in ("sl", "tp"))
        return missing, (
            f"{ticket} is open and unprotected: asked {asked}, "
            f"the venue holds {holds}" + (f": {refused}" if refused else "")
        )

    async def _held(self, ticket: int) -> dict | None:
        """The position, or `None` where it cannot be seen.

        Unreadable and absent are the same answer here on purpose: neither is
        evidence that the position is unprotected, and the caller treats both
        as "look at the modify instead".
        """
        try:
            rows = await self._bridge.positions()
        except Exception as exc:
            self._log.warning(f"{ticket}: could not read the position: {self._scrub(exc)}")
            return None
        return next((r for r in rows if int(r.get("ticket") or 0) == ticket), None)

    def _shortfall(self, held: dict, stop: float, target: float, digits: int) -> frozenset[str]:
        """Which of the asked-for fields the position is not holding."""
        return frozenset(
            field
            for field, asked in (("sl", stop), ("tp", target))
            if asked and not self._near(float(held.get(field) or 0.0), asked, digits)
        )

    @staticmethod
    def _ticket(venue_order_id: Any) -> int:
        """The position or order ticket, with any bracket-leg suffix dropped.

        A bracket's stop and target are `<ticket>-SL` and `<ticket>-TP`; they
        name a side of the position that `<ticket>` opened, so everything that
        addresses the terminal by ticket wants the number in front.
        """
        raw = str(venue_order_id or "").split("-", 1)[0]
        try:
            return int(raw) if raw else 0
        except ValueError:
            return 0

    @staticmethod
    def _leg(venue_order_id: Any) -> str:
        """`SL`, `TP`, or empty for an order that is one in its own right."""
        parts = str(venue_order_id or "").split("-", 1)
        return parts[1].upper() if len(parts) == 2 else ""

    @staticmethod
    def _near(a: float, b: float, digits: int) -> bool:
        return abs(float(a) - float(b)) <= 0.5 * 10.0**-digits

    async def _locate(self, ticket: int) -> tuple[dict | None, dict | None]:
        """The resting order and the open position with this ticket, if either.

        Raises `_Refusal` when the book cannot be read or the ticket is not
        this desk's: neither is a reason to guess.
        """
        try:
            resting = next(
                (r for r in await self._bridge.pending() if int(r.get("ticket") or 0) == ticket),
                None,
            )
            held = next(
                (r for r in await self._bridge.positions() if int(r.get("ticket") or 0) == ticket),
                None,
            )
        except Exception as exc:
            raise _Refusal(f"cannot read the terminal's book: {exc}") from None
        for row in (resting, held):
            if row is not None and not self._ours(row):
                raise _Refusal(f"{ticket} is not this desk's")
        return resting, held

    async def _send_modify(
        self, command: Any, ticket: int, resting: dict | None, held: dict | None
    ) -> tuple[float, ...]:
        """Send the right modify for what the ticket is; return what was sent."""
        if resting is not None:
            # A resting order is not a position: `/positions/modify` addresses
            # a position ticket. It has its own route and its own transport
            # method, and a transport without one cannot do this at all.
            move = getattr(self._bridge, "modify_order", None)
            if move is None:
                raise _Refusal(f"{type(self._bridge).__name__} cannot modify a resting order")
            price = float(command.price or 0.0)
            if price <= 0:
                raise _Refusal("a resting order is moved by price, and the command carries none")
            sent: tuple[float, ...] = (price,)
            call = move(ticket, price)
        elif held is not None:
            if not (command.trigger_price or command.price):
                raise _Refusal("the modify carries neither a stop nor a target to change")
            sent = (
                float(command.trigger_price or 0.0) or float(held.get("sl") or 0.0),
                float(command.price or 0.0) or float(held.get("tp") or 0.0),
            )
            call = self._bridge.modify(ticket, *sent)
        else:
            raise _Refusal(f"{ticket} is neither a resting order nor an open position")
        try:
            raw = await call
        except Exception as exc:
            raise _Refusal(f"bridge: {exc}") from None
        if not _confirmed(raw):
            comment = (raw.get("result") or {}).get("comment")
            raise _Refusal(str(comment or f"retcode {_retcode(raw) or 'missing'}: not confirmed"))
        return sent

    async def _verify_modify(
        self, ticket: int, resting: bool, sent: tuple[float, ...], digits: int
    ) -> None:
        """Read the book back; raise unless it shows what was sent."""
        try:
            if resting:
                rows = await self._bridge.pending()
                keys = ("price_open",)
            else:
                rows = await self._bridge.positions()
                keys = ("sl", "tp")
        except Exception as exc:
            raise _Refusal(
                f"unconfirmed: acknowledged, but the book could not be read: {exc}"
            ) from None
        row = next((r for r in rows if int(r.get("ticket") or 0) == ticket), None)
        if row is None or not all(
            self._near(row.get(k) or 0.0, v, digits) for k, v in zip(keys, sent, strict=True)
        ):
            raise _Refusal("unconfirmed: the terminal's listing does not show the new value")

    async def _modify_order(self, command: Any) -> None:
        """Move a resting order's price, or an open position's stop and target.

        **Never sends a stop of zero, because zero removes it.** The first
        version sent `float(command.trigger_price or 0.0)`, so a modify that
        only moved the target came back with no stop at all. An omitted side
        is filled from what the terminal currently holds, and a modify that
        supplies nothing to change is refused.

        Every path ends in an event, and `OrderUpdated` is emitted only after
        a DONE reply *and* the terminal's own listing showing the new value.
        """
        ticket = self._ticket(command.venue_order_id)
        order = self._cache.order(command.client_order_id)
        try:
            if not ticket:
                raise _Refusal("cannot modify an order with no venue id")
            quantity = command.quantity or (order.quantity if order is not None else None)
            if quantity is None:
                raise _Refusal("the order is not in the cache, so its quantity is unknown")
            instrument = await self._instrument(command.instrument_id)
            resting, held = await self._locate(ticket)
            sent = await self._send_modify(command, ticket, resting, held)
            digits = instrument.price_precision if instrument is not None else 5
            await self._verify_modify(ticket, resting is not None, sent, digits)
        except _Refusal as refusal:
            reason = self._scrub(refusal)
            self._log.error(f"modify {command.client_order_id}: {reason}")
            self.generate_order_modify_rejected(
                strategy_id=command.strategy_id,
                instrument_id=command.instrument_id,
                client_order_id=command.client_order_id,
                venue_order_id=command.venue_order_id,
                reason=reason,
                ts_event=self._clock.timestamp_ns(),
            )
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

    async def _clear_leg(
        self,
        strategy_id: Any,
        instrument_id: Any,
        client_order_id: Any,
        venue_order_id: Any,
        ticket: int,
        leg: str,
        refuse: Any,
    ) -> None:
        """Withdraw one side of a bracket, which on MT5 means zeroing a field.

        **Never through the cancel route.** A bracket leg's ticket is the
        position's, not a resting order's, so `/orders/<ticket>` cannot
        cancel it - and an unconfirmed cancel sends `_withdraw` to its deal
        fallback, which would find the entry's own opening deal and report
        *this* leg as filled at the entry's price.

        A position that is already gone means the leg is gone with it: the
        other side filled, or the desk closed it. That is a cancellation, not
        a failure, and reporting it as one would leave the engine holding an
        order the broker has no record of.
        """
        try:
            _, held = await self._locate(ticket)
        except _Refusal as exc:
            refuse(str(exc))
            return
        if held is None:
            self._log.info(
                f"cancel {client_order_id}: position {ticket} is closed, and the leg with it"
            )
            self.generate_order_canceled(
                strategy_id=strategy_id,
                instrument_id=instrument_id,
                client_order_id=client_order_id,
                venue_order_id=venue_order_id,
                ts_event=self._clock.timestamp_ns(),
            )
            return
        # Zero the side being withdrawn and send the other one back unchanged:
        # `/positions/modify` sets both, so omitting one would clear it too.
        sl = 0.0 if leg == "SL" else float(held.get("sl") or 0.0)
        tp = 0.0 if leg == "TP" else float(held.get("tp") or 0.0)
        try:
            raw = await self._bridge.modify(ticket, sl, tp)
        except Exception as exc:
            refuse(f"bridge: {exc}")
            return
        if not _confirmed(raw):
            comment = (raw.get("result") or {}).get("comment")
            refuse(str(comment or f"retcode {_retcode(raw) or 'missing'}: not confirmed"))
            return
        self.generate_order_canceled(
            strategy_id=strategy_id,
            instrument_id=instrument_id,
            client_order_id=client_order_id,
            venue_order_id=venue_order_id,
            ts_event=self._clock.timestamp_ns(),
        )

    async def _withdraw(
        self, strategy_id: Any, instrument_id: Any, client_order_id: Any, venue_order_id: Any
    ) -> None:
        """Cancel one ticket and settle the order only on evidence.

        **The unknown case is treated as still working.** The bridge answers
        `{}` for a cancel that did nothing as well as for one that worked, and
        an empty pending listing is also what a failed one looks like. So a
        cancel is announced only when the envelope carries DONE; when it does
        not, the order is reported as *not* cancelled unless the broker shows
        a deal for it, in which case it filled and the fill is reported.
        """
        ticket = self._ticket(venue_order_id)
        leg = self._leg(venue_order_id)

        def refuse(reason: str) -> None:
            reason = self._scrub(reason)
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
        if leg:
            await self._clear_leg(
                strategy_id, instrument_id, client_order_id, venue_order_id, ticket, leg, refuse
            )
            return
        try:
            raw = await self._bridge.cancel(ticket)
        except Exception as exc:
            refuse(f"bridge: {exc}")
            return
        confirmed = _confirmed(raw)

        try:
            resting = {int(r.get("ticket") or 0) for r in await self._bridge.pending()}
        except Exception as exc:
            if confirmed:
                resting = set()  # the terminal's own DONE outweighs an unreadable listing
            else:
                refuse(f"unconfirmed: no cancel confirmation and the listing failed: {exc}")
                return
        if ticket in resting:
            refuse(f"order {ticket} is still resting after the cancel")
            return
        if confirmed:
            self.generate_order_canceled(
                strategy_id=strategy_id,
                instrument_id=instrument_id,
                client_order_id=client_order_id,
                venue_order_id=venue_order_id,
                ts_event=self._clock.timestamp_ns(),
            )
            return

        # Not confirmed and no longer resting: it filled, expired, or the reply
        # was lost. Only a deal is evidence of which.
        try:
            deal = await self._deal_for(ticket)
        except Exception as exc:
            refuse(f"unconfirmed: no cancel confirmation and the deals failed: {exc}")
            return
        order = self._cache.order(client_order_id)
        instrument = await self._instrument(instrument_id)
        if deal is None or order is None or instrument is None:
            refuse("unconfirmed: not confirmed cancelled, not resting, and no deal to explain it")
            return
        self._fill(
            order,
            instrument,
            ticket=ticket,
            trade_id=deal.get("ticket") or ticket,
            qty=float(deal.get("volume") or 0.0),
            px=float(deal.get("price") or 0.0),
            commission=float(deal.get("commission") or 0.0),
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
        does not know is cancelled at the terminal and logged. A listing that
        cannot be read raises, leaving every order exactly as it was.
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


__all__ = ["ClientOrderId", "MT5ExecutionClient", "ReconciliationError"]
