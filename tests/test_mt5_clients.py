"""The MT5 clients' behaviour, driven against a fake bridge.

`test_mt5_adapter.py` covers the conversions and says the clients need a
kernel. They do not need a whole node: a `MessageBus`, a `Cache` and a clock
from Nautilus's own test kit are enough to construct the real clients, and the
engines' endpoints can be registered on the bus to capture what a client sends
them. So these tests run the real `MT5DataClient` and `MT5ExecutionClient`,
with `Bridge` replaced by `FakeBridge`.

**Nothing here assigns a method onto a framework class.** The one thing
replaced is `client._bridge`, which is an attribute this adapter defines for
itself. `publish_data_dict` is the reason: assigning a name that Nautilus does
not have *creates* it, so the test passes against an API that does not exist.
Where a test is about a name the framework calls, it asserts the name against
the framework's own class.

Most of the cases below began as `xfail(strict=True)` tests for defects found
while writing the first version of this file: the reconciliation hooks were
named `_generate_*` (the framework awaits `generate_*`), a position report
called `OrderSide.to_position_side()`, `generate_order_filled` was called
without `trade_id`, the execution client's provider was never loaded, and
modify/cancel never told the engine what happened. They are ordinary tests now;
the docstrings say which bug put each one here.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import time
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from nautilus_trader.core.uuid import UUID4
from nautilus_trader.data.messages import (
    RequestBars,
    SubscribeBars,
    SubscribeQuoteTicks,
    UnsubscribeBars,
    UnsubscribeQuoteTicks,
)
from nautilus_trader.execution.messages import (
    CancelOrder,
    GenerateFillReports,
    GenerateOrderStatusReport,
    GenerateOrderStatusReports,
    GeneratePositionStatusReports,
    ModifyOrder,
    QueryOrder,
    SubmitOrder,
)
from nautilus_trader.live.data_client import LiveMarketDataClient
from nautilus_trader.live.execution_client import LiveExecutionClient
from nautilus_trader.model.data import Bar, BarType, QuoteTick
from nautilus_trader.model.enums import OrderSide, OrderStatus, PositionSide
from nautilus_trader.model.events import (
    OrderAccepted,
    OrderCanceled,
    OrderCancelRejected,
    OrderFilled,
    OrderModifyRejected,
    OrderRejected,
    OrderSubmitted,
    OrderUpdated,
)
from nautilus_trader.model.identifiers import (
    AccountId,
    ClientId,
    InstrumentId,
    PositionId,
    Venue,
    VenueOrderId,
)
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.test_kit.stubs.component import TestComponentStubs
from nautilus_trader.test_kit.stubs.identifiers import TestIdStubs

from till_infinity.adapters.mt5.bridge import Bridge, BridgeError
from till_infinity.adapters.mt5.config import MT5DataClientConfig, MT5ExecClientConfig
from till_infinity.adapters.mt5.data import QUOTE_SOURCES, MT5DataClient, _milliseconds
from till_infinity.adapters.mt5.execution import MT5ExecutionClient, ReconciliationError
from till_infinity.adapters.mt5.factories import MT5LiveDataClientFactory, MT5LiveExecClientFactory
from till_infinity.adapters.mt5.providers import MT5InstrumentProvider
from till_infinity.adapters.mt5.redact import redact

VENUE = Venue("MT5")
EURUSD_ID = InstrumentId.from_str("EURUSD.MT5")
MAGIC = 777_701

#: What the terminal says about EURUSD: `digits`, `volume_step` and the
#: currencies are what the provider builds an instrument from.
EURUSD_INFO: dict[str, Any] = {
    "digits": 5,
    "volume_step": 0.01,
    "volume_min": 0.01,
    "volume_max": 100.0,
    "currency_base": "EUR",
    "currency_profit": "USD",
    "bid": 1.08500,
    "ask": 1.08512,
}


# ──── the fake bridge ────


#: What the bridge returns when the terminal took a modify or a cancel.
DONE_ENVELOPE = {"success": True, "result": {"retcode": 10009}}


class FakeBridge:
    """The same async surface as `Bridge`, returning canned JSON.

    Every call is recorded as `(method, args, kwargs)` so a test can assert on
    the exact thing sent. A response may be a value, or an exception instance,
    which is raised instead - how a bridge that is down or refusing is made.
    """

    def __init__(self, **responses: Any) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []
        self.opened = False
        self.closed = False
        self.responses: dict[str, Any] = {
            "ping": True,
            "account": {"login": 5042, "equity": 10_000.0},
            "symbols": ["EURUSD"],
            "symbol_info": EURUSD_INFO,
            "bars": [],
            "ticks": [],
            "positions": [],
            "pending": [],
            "deals": [],
            "order": {"success": True, "result": {"retcode": 10009, "order": 55}},
            "modify": DONE_ENVELOPE,
            "modify_order": DONE_ENVELOPE,
            "close_position": {},
            "cancel": DONE_ENVELOPE,
            #: One entry per connection: frames to deliver, then either an
            #: exception (the connection drops) or the end of the list (it
            #: stays open and quiet, as a live socket does).
            "stream": [],
        }
        self.responses.update(responses)

    def _answer(self, name: str, args: tuple, kwargs: dict) -> Any:
        self.calls.append((name, args, kwargs))
        answer = self.responses[name]
        if callable(answer):
            answer = answer(*args, **kwargs)
        if isinstance(answer, BaseException):
            raise answer
        return answer

    def called(self, name: str) -> list[tuple[tuple, dict]]:
        return [(a, k) for n, a, k in self.calls if n == name]

    async def open(self) -> None:
        self.opened = True

    async def close(self) -> None:
        self.closed = True

    async def ping(self) -> bool:
        return self._answer("ping", (), {})

    async def account(self) -> dict:
        return self._answer("account", (), {})

    async def symbols(self) -> list[str]:
        return self._answer("symbols", (), {})

    async def symbol_info(self, symbol: str) -> dict:
        return self._answer("symbol_info", (symbol,), {})

    async def bars(self, symbol: str, timeframe: str, count: int, start: int = 0) -> list[dict]:
        return self._answer("bars", (symbol, timeframe), {"count": count, "start": start})

    async def ticks(self, symbol: str, start: int, end: int) -> list[dict]:
        return self._answer("ticks", (symbol, start, end), {})

    async def stream(self, symbols: list[str]):
        self.calls.append(("stream", (list(symbols),), {}))
        connections = self.responses["stream"]
        index = len(self.called("stream")) - 1
        frames = connections[index] if index < len(connections) else []
        for frame in frames:
            if isinstance(frame, BaseException):
                raise frame
            yield frame
        await asyncio.sleep(3600)

    async def positions(self) -> list[dict]:
        return self._answer("positions", (), {})

    async def pending(self) -> list[dict]:
        return self._answer("pending", (), {})

    async def deals(self, start: int, end: int) -> list[dict]:
        return self._answer("deals", (start, end), {})

    async def order(self, body: dict) -> dict:
        return self._answer("order", (body,), {})

    async def modify_order(self, ticket: int, price: float) -> dict:
        return self._answer("modify_order", (ticket, price), {})

    async def modify(self, ticket: int, stop: float, target: float = 0.0) -> dict:
        return self._answer("modify", (ticket, stop, target), {})

    async def close_position(self, ticket: int, volume: float | None = None) -> dict:
        return self._answer("close_position", (ticket, volume), {})

    async def cancel(self, ticket: int) -> dict:
        return self._answer("cancel", (ticket,), {})


#: The transport underneath; the fake replaces the verbs above it.
PLUMBING = {"get", "post", "delete"}

#: Defined on the fake ahead of the transports, for the push path. `stream` is
#: an async generator, which `iscoroutinefunction` does not see, so it is
#: checked by its own test below.
STREAMING = {"stream", "modify_order"}


def _public_coroutines(cls: type) -> dict[str, inspect.Signature]:
    return {
        name: inspect.signature(fn)
        for name, fn in inspect.getmembers(cls, inspect.iscoroutinefunction)
        if not name.startswith("_") and name not in PLUMBING
    }


def test_the_fake_bridge_has_the_surface_of_the_real_one():
    """A fake that drifts from `Bridge` passes tests for a client that cannot run.

    The `publish_data_dict` lesson, one level down: a stub proves nothing about
    a name or a signature unless something compares it to the thing it stands
    in for. Both directions, so a new `Bridge` method also fails here until the
    fake learns it.
    """
    # `get`/`post`/`put`/`delete` are the real client's HTTP plumbing, not the
    # transport surface a client calls - a fake answers the named methods
    # instead, so it has no reason to carry them.
    plumbing = {"get", "post", "put", "delete"}
    real, fake = _public_coroutines(Bridge), _public_coroutines(FakeBridge)
    assert set(fake) - STREAMING - plumbing == set(real) - STREAMING - plumbing
    for name, signature in real.items():
        if name in plumbing or name in STREAMING:
            continue
        assert list(fake[name].parameters) == list(signature.parameters), name


# ──── the rig ────


def test_a_transport_that_streams_does_so_with_the_signature_the_client_calls():
    """`stream(symbols)` is the contract between `data.py` and a transport.

    Every push test below runs against `FakeBridge.stream`, so the thing worth
    holding is that a real transport's `stream` takes what the fake takes. The
    emptiness check is the point of the first assertion: this test used to
    skip when no transport defined the method, which meant deleting
    `Bridge.stream` would have turned the whole push contract green by
    reporting itself as not applicable yet.

    Which transports have one is `test_mt5_transport.py`'s question - `Proxy`
    deliberately has none - so this asserts only that somebody does.
    """
    from till_infinity.adapters.mt5.proxy import Proxy

    expected = list(inspect.signature(FakeBridge.stream).parameters)
    present = [cls for cls in (Bridge, Proxy) if "stream" in vars(cls)]
    assert present, "no transport defines stream, so the signature check below is vacuous"
    for cls in present:
        assert list(inspect.signature(cls.stream).parameters) == expected, cls.__name__
        assert inspect.isasyncgenfunction(cls.stream), cls.__name__


def test_a_transport_that_moves_a_resting_order_does_so_with_the_signature_the_client_calls():
    """`modify_order(ticket, price)` is the contract `execution.py` calls.

    A resting order is moved by `PUT /orders/{ticket}`, not by the position
    route, and the two routes take different arguments - so a signature that
    drifts from the fake's is a modify that silently sends a stop where a
    price belongs.

    Asserted rather than skipped for the reason given above: a guard that
    tolerates nothing being present cannot fail when something is removed.
    """
    from till_infinity.adapters.mt5.proxy import Proxy

    expected = list(inspect.signature(FakeBridge.modify_order).parameters)
    present = [cls for cls in (Bridge, Proxy) if "modify_order" in vars(cls)]
    assert present, "no transport defines modify_order, so there is nothing to hold"
    for cls in present:
        assert list(inspect.signature(cls.modify_order).parameters) == expected, cls.__name__


class Rig:
    """A real client on a real bus, with the engines' endpoints captured."""

    def __init__(self, client: Any, bridge: FakeBridge, bus: Any, clock: Any) -> None:
        self.client, self.bridge, self.bus, self.clock = client, bridge, bus, clock
        self.processed: list[Any] = []
        self.reports: list[Any] = []
        self.responses: list[Any] = []

    def events(self, kind: type) -> list[Any]:
        return [e for e in self.processed if isinstance(e, kind)]

    def published(self, kind: type) -> list[Any]:
        return [e for e in self.processed if isinstance(e, kind)]


def _capture(bus: Any, rig: Rig) -> None:
    bus.register(endpoint="ExecEngine.process", handler=rig.processed.append)
    bus.register(endpoint="DataEngine.process", handler=rig.processed.append)
    bus.register(endpoint="DataEngine.response", handler=rig.responses.append)
    bus.register(endpoint="ExecEngine.reconcile_execution_report", handler=rig.reports.append)


def _eurusd() -> Any:
    """EURUSD as the provider builds it from the terminal's own numbers.

    Not `TestInstrumentProvider.default_fx_ccy`, whose size precision is 0: it
    would round every 0.5 lot to nothing and pass for the wrong reason.
    """
    return MT5InstrumentProvider(FakeBridge(), VENUE)._build(EURUSD_ID, EURUSD_INFO)


class StreamingDataConfig(MT5DataClientConfig, frozen=True):
    """The config the streaming options will live on.

    `config.py` is owned elsewhere, so the three fields `data.py` reads with a
    default are declared here by subclassing - a real pydantic field, not an
    attribute assigned onto a framework object.
    """

    quote_source: str = "poll"
    reconnect_seconds: float = 0.01
    server_offset_seconds: int = 0


def make_data(bridge: FakeBridge | None = None, **config: Any) -> Rig:
    bridge = bridge or FakeBridge()
    config.setdefault("poll_seconds", 0.01)
    clock, bus, cache = (
        TestComponentStubs.clock(),
        TestComponentStubs.msgbus(),
        TestComponentStubs.cache(),
    )
    provider = MT5InstrumentProvider(bridge, VENUE, symbols=("EURUSD",))
    client = MT5DataClient(
        asyncio.get_running_loop(),
        ClientId("MT5"),
        VENUE,
        bus,
        cache,
        clock,
        provider,
        StreamingDataConfig(**config),
    )
    client._bridge = bridge
    rig = Rig(client, bridge, bus, clock)
    _capture(bus, rig)
    return rig


def make_exec(bridge: FakeBridge | None = None, loaded: bool = True, **config: Any) -> Rig:
    bridge = bridge or FakeBridge()
    clock, bus, cache = (
        TestComponentStubs.clock(),
        TestComponentStubs.msgbus(),
        TestComponentStubs.cache(),
    )
    provider = MT5InstrumentProvider(bridge, VENUE)
    if loaded:
        provider.add(_eurusd())
    client = MT5ExecutionClient(
        asyncio.get_running_loop(),
        ClientId("MT5"),
        VENUE,
        bus,
        cache,
        clock,
        provider,
        MT5ExecClientConfig(**config),
    )
    client._bridge = bridge
    client._set_account_id(AccountId("MT5-5042"))
    rig = Rig(client, bridge, bus, clock)
    _capture(bus, rig)
    return rig


async def until(condition, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("timed out waiting for the condition")
        await asyncio.sleep(0.005)


async def stop(rig: Rig) -> None:
    """Cancel whatever the client left running, as a node's shutdown would."""
    client = rig.client
    for task in list(getattr(client, "_pollers", {}).values()):
        task.cancel()
    await client.cancel_pending_tasks()


def subscribe_quotes() -> SubscribeQuoteTicks:
    return SubscribeQuoteTicks(EURUSD_ID, ClientId("MT5"), VENUE, UUID4(), time.time_ns())


def unsubscribe_quotes() -> UnsubscribeQuoteTicks:
    return UnsubscribeQuoteTicks(EURUSD_ID, ClientId("MT5"), VENUE, UUID4(), time.time_ns())


def minute_bars() -> BarType:
    return BarType.from_str("EURUSD.MT5-1-MINUTE-LAST-EXTERNAL")


def subscribe_bars(bar_type: BarType) -> SubscribeBars:
    return SubscribeBars(bar_type, ClientId("MT5"), VENUE, UUID4(), time.time_ns())


def unsubscribe_bars(bar_type: BarType) -> UnsubscribeBars:
    return UnsubscribeBars(bar_type, ClientId("MT5"), VENUE, UUID4(), time.time_ns())


# ──── the names the framework calls ────


class TestTheAdapterOverridesNamesNautilusActuallyCalls:
    """A hook with a plausible name that nothing calls is dead code that passes.

    `test_nautilus_api.py` sweeps `self.x()` calls. This is the other
    direction: the methods the adapter *defines* in order to be called. The
    reconciliation reports are the case that put it here - the framework calls
    `generate_position_status_reports`, and the adapter defined
    `_generate_position_status_reports`, so on a live node the framework's
    version raised `NotImplementedError` and the desk's open positions were
    never reconciled.
    """

    HOOK_PREFIXES = (
        "_subscribe",
        "_unsubscribe",
        "_request",
        "_submit",
        "_modify",
        "_cancel",
        "_query",
        "_batch",
        "_connect",
        "_disconnect",
        "_generate",
    )

    @pytest.mark.parametrize(
        ("cls", "base"),
        [
            (MT5DataClient, LiveMarketDataClient),
            (MT5ExecutionClient, LiveExecutionClient),
        ],
    )
    def test_every_hook_shaped_method_exists_on_the_framework_base(self, cls, base):
        stray = [
            name
            for name, member in vars(cls).items()
            if name.startswith(self.HOOK_PREFIXES)
            and inspect.isfunction(member)
            and not hasattr(base, name)
        ]
        assert not stray, f"{cls.__name__} defines hooks {base.__name__} never calls: {stray}"

    @pytest.mark.parametrize(
        "name",
        [
            "generate_order_status_report",
            "generate_order_status_reports",
            "generate_fill_reports",
            "generate_position_status_reports",
        ],
    )
    def test_the_reconciliation_reports_are_overridden_under_the_name_nautilus_calls(self, name):
        """These are what `generate_mass_status` awaits, with no underscore."""
        assert hasattr(LiveExecutionClient, name)
        assert name in vars(MT5ExecutionClient), (
            f"{name} falls through to the framework's NotImplementedError"
        )

    # **`test_the_event_generators_the_client_calls_exist_on_the_framework`
    # went as a duplicate.** It was a hand-kept roster of twelve framework
    # names behind bare `hasattr`, and
    # `test_nautilus_api.test_nothing_calls_a_nautilus_method_that_does_not_exist`
    # already resolves `MT5ExecutionClient` and `MT5DataClient` against these
    # same two bases and checks every `self.x()` call in them - so eleven of
    # the twelve were covered automatically, by a check that cannot go stale.
    # The twelfth, `_send_order_status_report`, is called nowhere in the tree,
    # and a list entry for a method we do not use protects nothing. What the
    # roster could not do is check a *signature*, which is the mistake this
    # adapter actually made, and the test below does that.

    def test_generate_order_filled_is_called_by_keyword_with_every_required_argument(self):
        """The positional call left out `trade_id` and shifted the rest.

        The signature has `trade_id` between `venue_position_id` and
        `order_side`; the call skipped it, so every later argument landed one
        slot early and every successful fill raised `TypeError`. By keyword,
        the same mistake is a named error - and this binds the call's keywords
        against the real signature, so a renamed parameter fails here first.
        """
        import ast
        import textwrap

        source = textwrap.dedent(inspect.getsource(MT5ExecutionClient._fill))
        call = next(
            n
            for n in ast.walk(ast.parse(source))
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "generate_order_filled"
        )
        assert call.args == [], "positional arguments are how this shifted"
        signature = inspect.signature(LiveExecutionClient.generate_order_filled)
        signature.bind(None, **{k.arg: None for k in call.keywords})


# ──── refusals ────


class TestWhatThisVenueCannotDoStaysRefused:
    """MT5 has no order book, no trade ticks and no brackets here.

    A client that returns quietly from `subscribe_trade_ticks` is worse than one
    that refuses it, because the strategy believes it is subscribed and sees
    nothing. So each of these is asserted twice: the adapter has not overridden
    it, and the inherited hook still raises. If someone "implements" one as a
    no-op, the first assertion catches it.
    """

    DATA_REFUSALS = (
        "_subscribe_order_book_deltas",
        "_subscribe_order_book_depth",
        "_subscribe_trade_ticks",
        "_subscribe_mark_prices",
        "_subscribe_index_prices",
        "_subscribe_funding_rates",
        "_request_trade_ticks",
    )
    EXEC_REFUSALS = ("_submit_order_list", "_batch_cancel_orders")

    @pytest.mark.parametrize("name", DATA_REFUSALS)
    async def test_the_data_client_refuses(self, name):
        rig = make_data()
        assert name not in vars(MT5DataClient)
        with pytest.raises(NotImplementedError):
            await getattr(rig.client, name)(None)

    @pytest.mark.parametrize("name", EXEC_REFUSALS)
    async def test_the_exec_client_refuses(self, name):
        rig = make_exec()
        assert name not in vars(MT5ExecutionClient)
        with pytest.raises(NotImplementedError):
            await getattr(rig.client, name)(None)


# ──── data: lifecycle ────


class TestDataConnect:
    """`connected` has to mean the bridge answered.

    The deploys of 2026-10-09 were reported up while running none of the code
    they claimed, because every check read our own side. So connecting is
    asserted against the failure modes: bridge down, bridge refusing.
    """

    async def test_connecting_pings_and_loads_and_publishes_the_instruments(self):
        rig = make_data()
        await rig.client._connect()
        assert rig.bridge.opened
        assert rig.bridge.called("ping")
        published = [e for e in rig.processed if type(e).__name__ == "CurrencyPair"]
        assert [i.id for i in published] == [EURUSD_ID]
        assert published[0].price_precision == 5
        assert published[0].size_precision == 2

    async def test_a_bridge_that_answers_false_is_not_connected(self):
        rig = make_data(FakeBridge(ping=False))
        with pytest.raises(ConnectionError, match="did not answer"):
            await rig.client._connect()

    async def test_a_bridge_that_is_down_raises_rather_than_connecting(self):
        rig = make_data(FakeBridge(ping=httpx.ConnectError("refused")))
        with pytest.raises(ConnectionError, match="refused"):
            await rig.client._connect()

    async def test_a_failed_connect_leaves_the_client_disconnected(self):
        """Through the framework's `connect()`, which swallows and logs."""
        rig = make_data(FakeBridge(ping=False))
        rig.client.connect()
        await asyncio.sleep(0.1)
        assert not rig.client.is_connected
        await stop(rig)

    async def test_a_good_connect_marks_the_client_connected(self):
        rig = make_data()
        rig.client.connect()
        await until(lambda: rig.client.is_connected)
        await stop(rig)

    async def test_disconnect_stops_the_pollers_and_closes_the_session(self):
        rig = make_data()
        rig.client._instrument_provider.add(_eurusd())
        await rig.client._subscribe_quote_ticks(subscribe_quotes())
        poller = rig.client._pollers[f"quotes:{EURUSD_ID}"]
        await rig.client._disconnect()
        assert poller.cancelled() or poller.done()
        assert rig.client._pollers == {}
        assert rig.bridge.closed


# ──── data: quotes ────


class TestQuotePolling:
    """The stream is a sample at `poll_seconds`, not a push."""

    async def test_a_quote_is_published_at_the_instruments_precision(self):
        rig = make_data()
        rig.client._instrument_provider.add(_eurusd())
        await rig.client._subscribe_quote_ticks(subscribe_quotes())
        await until(lambda: rig.published(QuoteTick))
        tick = rig.published(QuoteTick)[0]
        assert tick.instrument_id == EURUSD_ID
        assert tick.bid_price == Price(1.08500, 5)
        assert tick.ask_price == Price(1.08512, 5)
        await stop(rig)

    async def test_an_unchanged_quote_is_not_published_again(self):
        """Polling a quiet market would otherwise publish the same tick forever."""
        rig = make_data()
        rig.client._instrument_provider.add(_eurusd())
        await rig.client._subscribe_quote_ticks(subscribe_quotes())
        await until(lambda: len(rig.bridge.called("symbol_info")) >= 5)
        assert len(rig.published(QuoteTick)) == 1
        await stop(rig)

    async def test_a_changed_quote_is_published(self):
        rig = make_data()
        rig.client._instrument_provider.add(_eurusd())
        await rig.client._subscribe_quote_ticks(subscribe_quotes())
        await until(lambda: len(rig.published(QuoteTick)) == 1)
        rig.bridge.responses["symbol_info"] = {**EURUSD_INFO, "bid": 1.0851, "ask": 1.08522}
        await until(lambda: len(rig.published(QuoteTick)) == 2)
        assert rig.published(QuoteTick)[1].bid_price == Price(1.0851, 5)
        await stop(rig)

    @pytest.mark.parametrize("bid", [0.0, None])
    async def test_a_quote_with_no_bid_is_not_published(self, bid):
        """A closed market reads zero, and a zero bid is not a price."""
        rig = make_data(FakeBridge(symbol_info={**EURUSD_INFO, "bid": bid}))
        rig.client._instrument_provider.add(_eurusd())
        await rig.client._subscribe_quote_ticks(subscribe_quotes())
        await until(lambda: len(rig.bridge.called("symbol_info")) >= 3)
        assert not rig.published(QuoteTick)
        await stop(rig)

    async def test_a_poll_that_fails_is_survived(self):
        """One dropped request must not end the subscription."""
        answers = iter([httpx.ReadTimeout("slow"), EURUSD_INFO])

        def flaky(*_):
            answer = next(answers, EURUSD_INFO)
            if isinstance(answer, BaseException):
                raise answer
            return answer

        rig = make_data(FakeBridge(symbol_info=flaky))
        rig.client._instrument_provider.add(_eurusd())
        await rig.client._subscribe_quote_ticks(subscribe_quotes())
        await until(lambda: rig.published(QuoteTick))
        await stop(rig)

    async def test_subscribing_twice_starts_one_poller(self):
        rig = make_data()
        rig.client._instrument_provider.add(_eurusd())
        await rig.client._subscribe_quote_ticks(subscribe_quotes())
        first = rig.client._pollers[f"quotes:{EURUSD_ID}"]
        await rig.client._subscribe_quote_ticks(subscribe_quotes())
        assert rig.client._pollers[f"quotes:{EURUSD_ID}"] is first
        assert len(rig.client._pollers) == 1
        await stop(rig)

    async def test_unsubscribing_stops_the_polling(self):
        rig = make_data()
        rig.client._instrument_provider.add(_eurusd())
        await rig.client._subscribe_quote_ticks(subscribe_quotes())
        await until(lambda: rig.bridge.called("symbol_info"))
        await rig.client._unsubscribe_quote_ticks(unsubscribe_quotes())
        assert rig.client._pollers == {}
        await asyncio.sleep(0.05)
        seen = len(rig.bridge.called("symbol_info"))
        await asyncio.sleep(0.1)
        assert len(rig.bridge.called("symbol_info")) == seen

    async def test_unsubscribing_something_never_subscribed_is_harmless(self):
        rig = make_data()
        await rig.client._unsubscribe_quote_ticks(unsubscribe_quotes())

    async def test_the_bridge_is_asked_for_the_raw_symbol(self):
        rig = make_data()
        rig.client._instrument_provider.add(_eurusd())
        await rig.client._subscribe_quote_ticks(subscribe_quotes())
        await until(lambda: rig.bridge.called("symbol_info"))
        assert rig.bridge.called("symbol_info")[0][0] == ("EURUSD",)
        await stop(rig)


# ──── data: bars ────


def _bar_row(opened: int, close: float = 1.1) -> dict:
    return {
        "time": opened,
        "open": 1.0,
        "high": 1.2,
        "low": 0.9,
        "close": close,
        "tick_volume": 120,
    }


class TestBarPolling:
    """A closed bar is published once, stamped at its close; a forming one never."""

    async def test_the_closed_bar_is_published_and_the_forming_one_is_not(self):
        now = int(time.time())
        forming = now - now % 60
        closed = forming - 60
        rig = make_data(FakeBridge(bars=[_bar_row(closed, 1.11), _bar_row(forming, 1.99)]))
        rig.client._instrument_provider.add(_eurusd())
        bar_type = minute_bars()
        await rig.client._subscribe_bars(subscribe_bars(bar_type))
        await until(lambda: rig.published(Bar))
        bars = rig.published(Bar)
        assert len(bars) == 1
        assert bars[0].close == Price(1.11, 5)
        assert bars[0].ts_event == (closed + 60) * 1_000_000_000
        await stop(rig)

    async def test_the_bridge_is_asked_for_two_bars_from_the_forming_position(self):
        rig = make_data()
        rig.client._instrument_provider.add(_eurusd())
        await rig.client._subscribe_bars(subscribe_bars(minute_bars()))
        await until(lambda: rig.bridge.called("bars"))
        args, kwargs = rig.bridge.called("bars")[0]
        assert args == ("EURUSD", "M1")
        assert kwargs == {"count": 2, "start": 0}
        await stop(rig)

    async def test_a_bar_at_or_before_the_last_published_is_not_published_again(self):
        """The reason `_last_bar` exists: a bar seen twice doubled the count.

        `prices` learned it first - a notice per *touched* bar meant the bar in
        progress arrived on every sweep. The guard is seeded rather than waited
        for, because a sweep sleeps `seconds / 10`, six seconds for a minute bar.
        """
        now = int(time.time())
        closed = now - now % 60 - 60
        rig = make_data(FakeBridge(bars=[_bar_row(closed - 60), _bar_row(closed)]))
        rig.client._instrument_provider.add(_eurusd())
        bar_type = minute_bars()
        rig.client._last_bar[str(bar_type)] = closed
        await rig.client._subscribe_bars(subscribe_bars(bar_type))
        await until(lambda: rig.bridge.called("bars"))
        await asyncio.sleep(0.05)
        assert not rig.published(Bar)
        await stop(rig)

    async def test_bars_are_remembered_per_bar_type(self):
        now = int(time.time())
        closed = now - now % 300 - 300
        rig = make_data(FakeBridge(bars=[_bar_row(closed)]))
        rig.client._instrument_provider.add(_eurusd())
        await rig.client._subscribe_bars(subscribe_bars(minute_bars()))
        await rig.client._subscribe_bars(
            subscribe_bars(BarType.from_str("EURUSD.MT5-5-MINUTE-LAST-EXTERNAL"))
        )
        await until(lambda: len(rig.published(Bar)) == 2)
        assert {str(b.bar_type) for b in rig.published(Bar)} == {
            "EURUSD.MT5-1-MINUTE-LAST-EXTERNAL",
            "EURUSD.MT5-5-MINUTE-LAST-EXTERNAL",
        }
        await stop(rig)

    async def test_unsubscribing_bars_stops_the_poller(self):
        rig = make_data()
        rig.client._instrument_provider.add(_eurusd())
        bar_type = minute_bars()
        await rig.client._subscribe_bars(subscribe_bars(bar_type))
        assert f"bars:{bar_type}" in rig.client._pollers
        await rig.client._unsubscribe_bars(unsubscribe_bars(bar_type))
        assert rig.client._pollers == {}

    async def test_a_bridge_error_on_a_sweep_publishes_nothing_and_does_not_raise(self):
        rig = make_data(FakeBridge(bars=BridgeError("GET /symbols/rates/pos -> 500")))
        rig.client._instrument_provider.add(_eurusd())
        await rig.client._subscribe_bars(subscribe_bars(minute_bars()))
        await until(lambda: rig.bridge.called("bars"))
        assert not rig.published(Bar)
        task = rig.client._pollers[f"bars:{minute_bars()}"]
        assert not task.done()
        await stop(rig)


class TestRequestBars:
    """History is the complete side, and was taken from position 1.

    Position 0 is the forming bar, so a history request starts one back.
    """

    def _request(self, limit: int = 3) -> RequestBars:
        return RequestBars(
            minute_bars(),
            None,
            None,
            limit,
            ClientId("MT5"),
            VENUE,
            None,
            UUID4(),
            time.time_ns(),
            None,
        )

    async def test_a_history_request_answers_with_bars_oldest_first(self):
        rows = [_bar_row(1_700_000_120), _bar_row(1_700_000_000), _bar_row(1_700_000_060)]
        rig = make_data(FakeBridge(bars=rows))
        rig.client._instrument_provider.add(_eurusd())
        request = self._request()
        await rig.client._request_bars(request)
        assert rig.bridge.called("bars")[0][1] == {"count": 3, "start": 1}
        assert len(rig.responses) == 1
        times = [b.ts_event for b in rig.responses[0].data]
        assert times == sorted(times)
        assert len(times) == 3


# ──── data: every tick ────


def _now_ms() -> int:
    return int(time.time() * 1000)


def _tick(msc: int, bid: float = 1.0850, ask: float = 1.0851, **extra: Any) -> dict:
    """A tick as the terminal records it: a quote update with dead trade fields."""
    return {
        "time": msc // 1000,
        "time_msc": msc,
        "bid": bid,
        "ask": ask,
        "last": 0.0,
        "volume": 0,
        "volume_real": 0.0,
        "flags": 134,
        **extra,
    }


class TestMillisecondsAcceptEveryShapeATransportSpellsATickIn:
    """The same tick arrives as an int over rpyc and an ISO string over HTTP.

    The HTTP bridge runs `copy_ticks_*` rows through `pandas.to_datetime`
    before serialising, so a watermark compared as a number would never match
    a tick compared as a string and every backfill would republish.
    """

    def test_an_integer_is_milliseconds(self):
        assert _milliseconds({"time_msc": 1_700_000_000_123}) == 1_700_000_000_123

    def test_an_iso_string_without_a_zone_is_utc(self):
        row = {"time_msc": "2023-11-14T22:13:20.123000"}
        assert _milliseconds(row) == 1_700_000_000_123

    def test_an_iso_string_with_a_zone_is_converted(self):
        assert _milliseconds({"time_msc": "2023-11-14T22:13:20.123+00:00"}) == 1_700_000_000_123

    def test_seconds_are_the_fallback_when_there_is_no_millisecond_field(self):
        assert _milliseconds({"time": 1_700_000_000}) == 1_700_000_000_000

    def test_no_time_at_all_is_none_rather_than_zero(self):
        assert _milliseconds({"bid": 1.0}) is None
        assert _milliseconds({"time_msc": "garbage"}) is None


class TestAQuoteSourceThisTransportCannotHonourIsRefused:
    """A `push` that quietly became a poll would report completeness it lacks."""

    def test_the_sources_are_exactly_these_three(self):
        assert QUOTE_SOURCES == ("poll", "ticks", "push")

    async def test_an_unknown_source_is_refused_at_connect(self):
        rig = make_data(quote_source="websocket")
        with pytest.raises(ValueError, match="unknown quote_source"):
            await rig.client._connect()

    async def test_push_on_a_transport_with_no_stream_is_refused_at_connect(self):
        class NoStream(FakeBridge):
            stream = None

        rig = make_data(NoStream(), quote_source="push")
        with pytest.raises(ConnectionError, match="needs a transport with a tick stream"):
            await rig.client._connect()

    async def test_poll_and_ticks_need_no_stream(self):
        """Power for the refusal above, which would otherwise be satisfied by a
        client that refused every stream-less transport outright.

        The rpyc proxy has no stream and is a perfectly good transport for the
        two sampling sources, so the refusal has to be specific to `push`.
        There is nothing to assert beyond the connect completing: the failure
        this is written against is an exception.
        """

        class NoStream(FakeBridge):
            stream = None

        for source in ("poll", "ticks"):
            rig = make_data(NoStream(), quote_source=source)
            await rig.client._connect()

    async def test_poll_is_the_default(self):
        assert make_data().client.quote_source == "poll"


class TestPullingEveryTick:
    """`quote_source='ticks'`: complete, and up to one interval late."""

    async def _run(self, rows: list[dict], **config: Any) -> Rig:
        rig = make_data(FakeBridge(ticks=rows), quote_source="ticks", **config)
        rig.client._instrument_provider.add(_eurusd())
        await rig.client._subscribe_quote_ticks(subscribe_quotes())
        await until(lambda: rig.bridge.called("ticks"))
        await asyncio.sleep(0.05)
        return rig

    async def test_every_tick_in_the_range_is_published_not_just_the_last(self):
        """The whole point: a poll would have shown only the final quote."""
        base = _now_ms() + 5_000
        rows = [_tick(base + i, bid=1.0850 + i * 1e-5, ask=1.0851 + i * 1e-5) for i in range(5)]
        rig = await self._run(rows)
        assert len(rig.published(QuoteTick)) == 5
        await stop(rig)

    async def test_ticks_are_published_in_time_order_even_if_returned_out_of_order(self):
        base = _now_ms() + 5_000
        rows = [_tick(base + 2, bid=1.0852), _tick(base, bid=1.0850), _tick(base + 1, bid=1.0851)]
        rig = await self._run(rows)
        assert [t.bid_price for t in rig.published(QuoteTick)] == [
            Price(1.0850, 5),
            Price(1.0851, 5),
            Price(1.0852, 5),
        ]
        await stop(rig)

    async def test_the_event_time_is_the_ticks_own_not_the_clocks(self):
        base = _now_ms() + 5_000
        rig = await self._run([_tick(base)])
        (tick,) = rig.published(QuoteTick)
        assert tick.ts_event == base * 1_000_000
        assert tick.ts_init >= tick.ts_event
        await stop(rig)

    async def test_the_server_offset_is_taken_off_the_event_time(self):
        """MT5 stamps server time as if it were UTC; the offset is the broker's."""
        base = _now_ms() + 5_000
        rig = await self._run([_tick(base)], server_offset_seconds=7200)
        assert rig.published(QuoteTick)[0].ts_event == base * 1_000_000 - 7200 * 1_000_000_000
        await stop(rig)

    async def test_re_reading_the_same_second_does_not_republish(self):
        """`copy_ticks_range` takes whole seconds, so every pull overlaps the last."""
        base = _now_ms() + 5_000
        rig = make_data(FakeBridge(ticks=[_tick(base)]), quote_source="ticks")
        rig.client._instrument_provider.add(_eurusd())
        await rig.client._subscribe_quote_ticks(subscribe_quotes())
        await until(lambda: len(rig.bridge.called("ticks")) >= 4)
        assert len(rig.published(QuoteTick)) == 1
        await stop(rig)

    async def test_two_different_quotes_in_one_millisecond_are_both_published(self):
        base = _now_ms() + 5_000
        rig = await self._run([_tick(base, bid=1.0850), _tick(base, bid=1.0851)])
        assert len(rig.published(QuoteTick)) == 2
        await stop(rig)

    async def test_the_same_quote_in_the_same_millisecond_is_one_tick(self):
        base = _now_ms() + 5_000
        rig = await self._run([_tick(base), _tick(base)])
        assert len(rig.published(QuoteTick)) == 1
        await stop(rig)

    async def test_a_tick_older_than_the_watermark_is_counted_not_published(self):
        """Before the subscription: history is `request_*`, not a subscription's job."""
        rig = await self._run([_tick(_now_ms() - 3_600_000)])
        assert not rig.published(QuoteTick)
        assert rig.client.stale_ticks >= 1
        await stop(rig)

    @pytest.mark.parametrize("flags", [2, 4, 6, 130, 134, 0])
    async def test_no_flag_value_filters_a_tick(self, flags):
        """`flags` has an undocumented bit 128; a one-sided revision is `(4, 130)`.

        Reading it as `(2, 4)` under-reports one-sidedness as 10.0% where the
        truth is 22.8%. The client has no business interpreting it: a quote
        carries both sides, so every flag value publishes.
        """
        rig = await self._run([_tick(_now_ms() + 5_000, flags=flags)])
        assert len(rig.published(QuoteTick)) == 1
        await stop(rig)

    async def test_the_trade_fields_are_ignored(self):
        """`last`, `volume` and `volume_real` read 0 or a constant 5000."""
        row = _tick(_now_ms() + 5_000, last=0.0, volume=5000, volume_real=5000.0)
        rig = await self._run([row])
        (tick,) = rig.published(QuoteTick)
        assert (tick.bid_size, tick.ask_size) == (Quantity(1, 0), Quantity(1, 0))
        await stop(rig)

    async def test_a_tick_with_no_bid_is_not_published(self):
        rig = await self._run([_tick(_now_ms() + 5_000, bid=0.0)])
        assert not rig.published(QuoteTick)
        await stop(rig)

    async def test_http_shaped_rows_with_iso_times_are_understood(self):
        stamp = datetime.fromtimestamp((_now_ms() + 5_000) / 1000, tz=UTC)
        row = _tick(0) | {"time": stamp.isoformat(), "time_msc": stamp.isoformat()}
        rig = await self._run([row])
        assert len(rig.published(QuoteTick)) == 1
        await stop(rig)

    async def test_the_range_is_asked_for_in_whole_seconds_ending_after_now(self):
        rig = await self._run([])
        (symbol, start, end), _ = rig.bridge.called("ticks")[0]
        assert symbol == "EURUSD"
        assert isinstance(start, int)
        assert end > start
        await stop(rig)

    async def test_a_failed_pull_is_survived(self):
        answers = iter([httpx.ReadTimeout("slow")])

        def flaky(*_):
            answer = next(answers, [_tick(_now_ms() + 5_000)])
            if isinstance(answer, BaseException):
                raise answer
            return answer

        rig = make_data(FakeBridge(ticks=flaky), quote_source="ticks")
        rig.client._instrument_provider.add(_eurusd())
        await rig.client._subscribe_quote_ticks(subscribe_quotes())
        await until(lambda: rig.published(QuoteTick))
        await stop(rig)

    async def test_it_never_asks_for_the_current_tick(self):
        rig = await self._run([])
        assert not rig.bridge.called("symbol_info")
        await stop(rig)


class TestPushedTicks:
    """`quote_source='push'`: what the transport's `stream` delivers."""

    def _frame(self, msc: int, seq: int | None = None, **extra: Any) -> dict:
        frame = {"type": "tick", "symbol": "EURUSD", **_tick(msc)} | extra
        if seq is not None:
            frame["seq"] = seq
        return frame

    async def _run(self, connections: list[list], tick_rows=(), wait=None, **config: Any) -> Rig:
        asked: list[int] = []

        def history(*_):
            """Nothing on the first ask, which is the catch-up before the stream
            opens; the missing ticks afterwards, which is the refill."""
            asked.append(1)
            return list(tick_rows) if len(asked) > 1 else []

        rig = make_data(
            FakeBridge(stream=connections, ticks=history), quote_source="push", **config
        )
        rig.client._instrument_provider.add(_eurusd())
        await rig.client._subscribe_quote_ticks(subscribe_quotes())
        await until(wait or (lambda: rig.published(QuoteTick)))
        return rig

    async def test_each_frame_is_one_quote(self):
        base = _now_ms() + 5_000
        frames = [self._frame(base + i, seq=i, bid=1.085 + i * 1e-4) for i in range(4)]
        rig = await self._run([frames], wait=lambda: True)
        await until(lambda: len(rig.published(QuoteTick)) == 4)
        await stop(rig)

    async def test_the_stream_is_asked_for_this_symbol_only(self):
        rig = await self._run([[self._frame(_now_ms() + 5_000)]])
        assert rig.bridge.called("stream")[0][0] == (["EURUSD"],)
        await stop(rig)

    async def test_it_never_falls_back_to_polling_the_current_tick(self):
        """The failure the option exists to end: claiming to push while sampling."""
        rig = await self._run([[self._frame(_now_ms() + 5_000)]])
        await asyncio.sleep(0.05)
        assert not rig.bridge.called("symbol_info")
        await stop(rig)

    async def test_frames_that_are_not_ticks_for_this_symbol_are_ignored(self):
        base = _now_ms() + 5_000
        frames = [
            {"type": "ready", "symbols": ["EURUSD"]},
            {"type": "positions", "positions": []},
            {"type": "error", "symbol": "EURUSD", "message": "no such symbol"},
            self._frame(base, symbol="GBPUSD"),
            self._frame(base + 1),
        ]
        rig = await self._run([frames])
        await asyncio.sleep(0.05)
        assert len(rig.published(QuoteTick)) == 1
        await stop(rig)

    @pytest.mark.parametrize("flags", [2, 4, 130, 134])
    async def test_flags_do_not_filter_a_pushed_tick(self, flags):
        """The four values are the observed ones, and the reason not to read
        them: 2 and 4 are a bid-only and an ask-only revision, 130 and 134 are
        the same two with the **undocumented bit 128** set.

        `adapters/mt5/__init__.py` records what that cost - a filter written
        as `flags in (2, 4)` under-reports, because the one-sided revision
        actually arrives as 130. A pushed frame already carries both sides, so
        the fix is to stop consulting the bitfield rather than to enumerate
        it, and this holds the client to that for every value seen in the wild.
        """
        rig = await self._run([[self._frame(_now_ms() + 5_000, flags=flags)]])
        assert len(rig.published(QuoteTick)) == 1
        await stop(rig)

    async def test_a_replayed_frame_is_published_once(self):
        base = _now_ms() + 5_000
        rig = await self._run([[self._frame(base), self._frame(base)]])
        await asyncio.sleep(0.05)
        assert len(rig.published(QuoteTick)) == 1
        await stop(rig)

    async def test_a_gap_in_seq_is_refilled_from_the_tick_history(self):
        """seq 1 then 4 means 2 and 3 were lost between the terminal and here."""
        base = _now_ms() + 5_000
        missing = [
            _tick(base + 1, bid=1.0861, ask=1.0862),
            _tick(base + 2, bid=1.0871, ask=1.0872),
        ]
        frames = [self._frame(base, seq=1), self._frame(base + 3, seq=4, bid=1.0881, ask=1.0882)]
        rig = await self._run([frames], tick_rows=missing, wait=lambda: True)
        await until(lambda: len(rig.published(QuoteTick)) == 4)
        times = sorted(t.ts_event for t in rig.published(QuoteTick))
        assert times == [(base + i) * 1_000_000 for i in range(4)]
        await stop(rig)

    async def test_a_dropped_stream_is_reopened_and_refilled(self):
        base = _now_ms() + 5_000
        first = [self._frame(base, seq=1), ConnectionError("socket closed")]
        second = [self._frame(base + 2, seq=3, bid=1.0891, ask=1.0892)]
        lost = [_tick(base + 1, bid=1.0871, ask=1.0872)]
        rig = await self._run([first, second], tick_rows=lost, wait=lambda: True)
        await until(lambda: len(rig.published(QuoteTick)) == 3)
        assert len(rig.bridge.called("stream")) == 2
        await stop(rig)

    async def test_unsubscribing_ends_the_stream(self):
        rig = await self._run([[self._frame(_now_ms() + 5_000)]])
        await rig.client._unsubscribe_quote_ticks(unsubscribe_quotes())
        assert rig.client._pollers == {}
        await stop(rig)

    async def test_disconnect_ends_the_stream(self):
        rig = await self._run([[self._frame(_now_ms() + 5_000)]])
        await rig.client._disconnect()
        assert rig.client._pollers == {}


# ──── exec: lifecycle ────


class TestExecConnect:
    """The account query is the broker's answer; nothing else is."""

    async def test_connecting_takes_the_account_id_from_the_login(self):
        rig = make_exec(FakeBridge(account={"login": 77, "equity": 1.0}))
        await rig.client._connect()
        assert rig.client.account_id == AccountId("MT5-77")

    async def test_the_account_key_is_accepted_when_login_is_absent(self):
        rig = make_exec(FakeBridge(account={"account": 88}))
        await rig.client._connect()
        assert rig.client.account_id == AccountId("MT5-88")

    async def test_an_empty_account_is_refused(self):
        rig = make_exec(FakeBridge(account={}))
        with pytest.raises(ConnectionError, match="no account"):
            await rig.client._connect()

    async def test_a_bridge_that_refuses_the_account_query_propagates(self):
        rig = make_exec(FakeBridge(account=BridgeError("GET -> 401: unauthorised")))
        with pytest.raises(ConnectionError, match="401"):
            await rig.client._connect()

    async def test_a_failed_connect_leaves_the_client_disconnected(self):
        rig = make_exec(FakeBridge(account={}))
        rig.client.connect()
        await asyncio.sleep(0.1)
        assert not rig.client.is_connected
        await stop(rig)

    async def test_disconnect_closes_the_session(self):
        rig = make_exec()
        await rig.client._disconnect()
        assert rig.bridge.closed

    async def test_an_instrument_is_loaded_from_the_terminal_the_first_time_it_is_needed(self):
        """The exec client's provider starts empty and nothing else fills it.

        `find` returned `None`, so the first order raised `AttributeError` and
        every reconciliation row was skipped as an unknown instrument - an
        empty report that looked like a flat account. Loaded on demand because
        `load_all_async` is one round trip per symbol, seven hundred here.
        """
        rig = make_exec(loaded=False)
        assert rig.client._instrument_provider.find(EURUSD_ID) is None
        instrument = await rig.client._instrument(EURUSD_ID)
        assert instrument is not None
        assert rig.bridge.called("symbol_info") == [(("EURUSD",), {})]
        assert rig.client._instrument_provider.find(EURUSD_ID) is instrument

    async def test_a_loaded_instrument_is_added_to_the_cache(self):
        """The execution engine sizes fills against the cache, not the provider."""
        rig = make_exec(loaded=False)
        assert rig.client._cache.instrument(EURUSD_ID) is None
        await rig.client._instrument(EURUSD_ID)
        assert rig.client._cache.instrument(EURUSD_ID) is not None

    async def test_an_instrument_is_loaded_once(self):
        rig = make_exec(loaded=False)
        await rig.client._instrument(EURUSD_ID)
        await rig.client._instrument(EURUSD_ID)
        assert len(rig.bridge.called("symbol_info")) == 1

    async def test_a_symbol_the_terminal_does_not_know_is_none(self):
        rig = make_exec(FakeBridge(symbol_info={}), loaded=False)
        assert await rig.client._instrument(EURUSD_ID) is None


# ──── exec: orders ────


def _submit(rig: Rig, order: Any) -> SubmitOrder:
    return SubmitOrder(
        TestIdStubs.trader_id(),
        TestIdStubs.strategy_id(),
        order,
        UUID4(),
        time.time_ns(),
        None,
        ClientId("MT5"),
    )


def _factory() -> Any:
    return TestComponentStubs.order_factory()


def _market(side: OrderSide = OrderSide.BUY, qty: str = "0.50") -> Any:
    return _factory().market(EURUSD_ID, side, Quantity.from_str(qty))


def _limit(side: OrderSide = OrderSide.BUY, price: str = "1.08000") -> Any:
    return _factory().limit(EURUSD_ID, side, Quantity.from_str("0.50"), Price.from_str(price))


REJECTION = {"success": False, "result": {"retcode": 10006, "comment": "Request rejected"}}


class TestSubmittingAnOrder:
    """The body sent to the bridge is the whole contract with the broker.

    `magic` is how the desk later tells its fills from anyone else's, and
    `DEFAULT_MAGIC` is 777_701: off by one relabels every strategy as its
    neighbour. So the payload is asserted whole, not by key.
    """

    async def test_a_market_buy_sends_exactly_this_body(self):
        rig = make_exec(FakeBridge(order=REJECTION))
        order = _market(OrderSide.BUY, "0.50")
        await rig.client._submit_order(_submit(rig, order))
        ((args, _),) = rig.bridge.called("order")
        assert args[0] == {
            "symbol": "EURUSD",
            "order_type": "BUY",
            "volume": 0.5,
            "deviation": 20,
            "magic": 777_701,
            "comment": str(order.client_order_id)[:31],
            "type_filling": "IOC",
        }

    async def test_a_market_sell_is_a_sell(self):
        rig = make_exec(FakeBridge(order=REJECTION))
        await rig.client._submit_order(_submit(rig, _market(OrderSide.SELL)))
        assert rig.bridge.called("order")[0][0][0]["order_type"] == "SELL"

    async def test_the_config_decides_magic_deviation_and_filling(self):
        rig = make_exec(FakeBridge(order=REJECTION), magic=424_242, deviation=7, filling="FOK")
        await rig.client._submit_order(_submit(rig, _market()))
        body = rig.bridge.called("order")[0][0][0]
        assert (body["magic"], body["deviation"], body["type_filling"]) == (424_242, 7, "FOK")

    def test_the_default_magic_is_the_one_the_desk_attributes_by(self):
        """**The magic is the only thing that says a fill was ours**, so the
        two places that spell it have to agree.

        `adapters/mt5/config.py` declares `magic: int = 777_701` as a literal
        and `strategies/config.py` declares `DEFAULT_MAGIC = 777_701`
        separately - the adapter's docstring names `DEFAULT_MAGIC` without
        importing it. Nothing else holds the copies together, and the recorded
        cost of them drifting is `judge-the-desk-on-the-broker-not-the-journal`:
        off by one relabels every strategy as its neighbour, so the fills come
        back attributed to a desk that did not place them.

        Asserted against the constant rather than only against the literal,
        because a test that repeats the number cannot notice the number moving.
        """
        from till_infinity.strategies.config import DEFAULT_MAGIC

        assert MT5ExecClientConfig().magic == MAGIC
        assert MT5ExecClientConfig().magic == DEFAULT_MAGIC, (
            "the adapter stamps orders with a magic the strategies no longer use"
        )

    async def test_the_comment_fits_the_mt5_limit(self):
        """MT5 truncates or rejects a comment past 31 characters."""
        rig = make_exec(FakeBridge(order=REJECTION))
        await rig.client._submit_order(_submit(rig, _market()))
        assert len(rig.bridge.called("order")[0][0][0]["comment"]) <= 31

    async def test_a_limit_order_carries_its_price(self):
        rig = make_exec(FakeBridge(order=REJECTION))
        await rig.client._submit_order(_submit(rig, _limit(price="1.08000")))
        body = rig.bridge.called("order")[0][0][0]
        assert body["price"] == 1.08

    async def test_a_market_order_carries_no_price(self):
        rig = make_exec(FakeBridge(order=REJECTION))
        await rig.client._submit_order(_submit(rig, _market()))
        assert "price" not in rig.bridge.called("order")[0][0][0]

    async def test_submitted_is_announced_before_the_bridge_is_asked(self):
        """The engine must see the order as in flight before it can be filled."""
        rig = make_exec(FakeBridge(order=lambda body: rig.processed.append("bridge") or REJECTION))
        await rig.client._submit_order(_submit(rig, _market()))
        assert [e if isinstance(e, str) else type(e).__name__ for e in rig.processed[:2]] == [
            "OrderSubmitted",
            "bridge",
        ]

    @pytest.mark.parametrize(
        "raw",
        [
            REJECTION,
            {"success": True, "result": {"retcode": 10013, "comment": "Invalid request"}},
            {},
        ],
    )
    async def test_a_refusal_is_a_rejection_with_the_brokers_reason(self, raw):
        rig = make_exec(FakeBridge(order=raw))
        await rig.client._submit_order(_submit(rig, _market()))
        rejected = rig.events(OrderRejected)
        assert len(rejected) == 1
        assert rejected[0].reason
        assert not rig.events(OrderFilled)
        assert not rig.events(OrderAccepted)

    async def test_the_rejection_names_the_brokers_comment(self):
        rig = make_exec(FakeBridge(order=REJECTION))
        await rig.client._submit_order(_submit(rig, _market()))
        assert rig.events(OrderRejected)[0].reason == "Request rejected"

    @pytest.mark.parametrize(
        "raw",
        [
            {"success": True, "result": {"order": 9, "volume": 0.5, "price": 1.1}},
            {"success": True, "result": {"retcode": 0, "order": 9}},
            {"success": True},
            {"result": {"retcode": 10009, "order": 9, "volume": 0.5, "price": 1.1}},
        ],
    )
    async def test_an_answer_without_a_positive_signal_is_a_rejection_not_a_fill(self, raw):
        """`retcode` 0 used to be OK, and a 404 reads as `{}`, so silence was 'done'.

        A real `order_send` never returns 0. The bridge not answering must not
        be distinguishable from the broker agreeing, so the absence of a
        failure is not a success: it needs `success: true` *and* 10008/10009.
        """
        rig = make_exec(FakeBridge(order=raw))
        await rig.client._submit_order(_submit(rig, _market()))
        assert len(rig.events(OrderRejected)) == 1
        assert not rig.events(OrderAccepted)
        assert not rig.events(OrderFilled)

    async def test_a_bridge_that_raises_propagates_to_the_framework(self):
        """The base `create_task` wrapper logs it; the order stays SUBMITTED.

        Asserted so nobody mistakes the silence for handling. See the report:
        nothing here ever generates a rejection for a transport failure.
        """
        rig = make_exec(FakeBridge(order=BridgeError("POST -> 500")))
        with pytest.raises(BridgeError):
            await rig.client._submit_order(_submit(rig, _market()))
        assert rig.events(OrderSubmitted)
        assert not rig.events(OrderRejected)

    async def test_a_filled_market_order_is_accepted_then_filled(self):
        raw = {
            "success": True,
            "result": {"retcode": 10009, "order": 55, "volume": 0.5, "price": 1.0851},
        }
        rig = make_exec(FakeBridge(order=raw))
        await rig.client._submit_order(_submit(rig, _market()))
        assert [type(e).__name__ for e in rig.processed] == [
            "OrderSubmitted",
            "OrderAccepted",
            "OrderFilled",
        ]
        fill = rig.events(OrderFilled)[0]
        assert fill.last_qty == Quantity(0.5, 2)
        assert fill.last_px == Price(1.0851, 5)
        assert fill.venue_order_id == VenueOrderId("55")
        assert fill.position_id == PositionId("55")

    async def test_placed_is_accepted_and_never_filled(self):
        """10008 is PLACED: a working order, not a position.

        The first version emitted `OrderAccepted` and `OrderFilled` for it, so
        a resting order gave the desk a position it did not have.
        """
        raw = {"success": True, "result": {"retcode": 10008, "order": 55, "price": 1.0851}}
        rig = make_exec(FakeBridge(order=raw))
        await rig.client._submit_order(_submit(rig, _market()))
        assert len(rig.events(OrderAccepted)) == 1
        assert not rig.events(OrderFilled)

    async def test_a_limit_order_is_accepted_when_placed_even_if_the_code_is_done(self):
        """For a pending order DONE means placed, not filled."""
        raw = {"success": True, "result": {"retcode": 10009, "order": 77, "price": 1.08}}
        rig = make_exec(FakeBridge(order=raw))
        await rig.client._submit_order(_submit(rig, _limit()))
        assert len(rig.events(OrderAccepted)) == 1
        assert not rig.events(OrderFilled)

    async def test_a_done_with_no_price_is_priced_from_the_deals(self):
        raw = {"success": True, "result": {"retcode": 10009, "order": 55}}
        deal = _deal(ticket=9001, order=55, volume=0.5, price=1.0853)
        rig = make_exec(FakeBridge(order=raw, deals=[deal]))
        await rig.client._submit_order(_submit(rig, _market()))
        (fill,) = rig.events(OrderFilled)
        assert fill.last_px == Price(1.0853, 5)
        assert str(fill.trade_id) == "9001"

    async def test_a_done_with_no_price_and_no_deal_is_never_a_fill_at_zero(self):
        """Not rejected either: the broker may hold the position.

        Rejecting would tell the engine there is no position when there is one,
        which is how a desk opens a second. It stays accepted and the next
        position report finds it.
        """
        raw = {"success": True, "result": {"retcode": 10009, "order": 55}}
        rig = make_exec(FakeBridge(order=raw, deals=[]))
        await rig.client._submit_order(_submit(rig, _market()))
        assert len(rig.events(OrderAccepted)) == 1
        assert not rig.events(OrderFilled)
        assert not rig.events(OrderRejected)

    async def test_a_done_with_no_ticket_is_rejected_not_tracked_as_order_zero(self):
        raw = {"success": True, "result": {"retcode": 10009, "volume": 0.5, "price": 1.1}}
        rig = make_exec(FakeBridge(order=raw))
        await rig.client._submit_order(_submit(rig, _market()))
        assert len(rig.events(OrderRejected)) == 1
        assert not rig.events(OrderAccepted)

    async def test_a_stop_order_is_refused_rather_than_sent_as_a_market_order(self):
        """A stop has no `price`, so `has_price` was False and it went out as a market order."""
        order = _factory().stop_market(
            EURUSD_ID, OrderSide.BUY, Quantity.from_str("0.50"), Price.from_str("1.09")
        )
        rig = make_exec()
        await rig.client._submit_order(_submit(rig, order))
        assert not rig.bridge.called("order")
        assert "not supported" in rig.events(OrderRejected)[0].reason

    async def test_a_stop_and_target_the_strategy_attached_are_passed_through(self):
        rig = make_exec(FakeBridge(order=REJECTION))
        command = SubmitOrder(
            TestIdStubs.trader_id(),
            TestIdStubs.strategy_id(),
            _market(),
            UUID4(),
            time.time_ns(),
            None,
            ClientId("MT5"),
            {"sl": 1.08, "tp": 1.09},
        )
        await rig.client._submit_order(command)
        body = rig.bridge.called("order")[0][0][0]
        assert (body["sl"], body["tp"]) == (1.08, 1.09)

    async def test_no_stop_is_invented_when_none_is_attached(self):
        rig = make_exec(FakeBridge(order=REJECTION))
        await rig.client._submit_order(_submit(rig, _market()))
        assert "sl" not in rig.bridge.called("order")[0][0][0]

    async def test_an_order_for_a_symbol_the_terminal_does_not_list_is_rejected(self):
        """It used to raise `AttributeError` on `None.size_precision`."""
        rig = make_exec(FakeBridge(symbol_info={}), loaded=False)
        await rig.client._submit_order(_submit(rig, _market()))
        (rejected,) = rig.events(OrderRejected)
        assert "not a symbol" in rejected.reason
        assert not rig.bridge.called("order")

    async def test_an_order_for_an_instrument_not_yet_loaded_loads_it_and_goes_through(self):
        """One of the defects this file was written for: the execution client's
        provider was never loaded.

        The data client loads instruments on connect and the execution client
        did not, so its provider was empty and the first order of a session
        looked exactly like the refusal above - a rejection reading "not a
        symbol" for a symbol the terminal lists perfectly well. The pair of
        tests has to stay a pair for that reason: either one alone passes for
        the wrong provider.
        """
        rig = make_exec(FakeBridge(order=REJECTION), loaded=False)
        await rig.client._submit_order(_submit(rig, _market()))
        assert rig.bridge.called("order")


def _held(**row: Any) -> dict:
    """An open position of this desk's, with a stop and a target."""
    return {
        "ticket": 55,
        "symbol": "EURUSD",
        "type": 0,
        "volume": 0.5,
        "magic": MAGIC,
        "sl": 1.0800,
        "tp": 1.0900,
        **row,
    }


class Terminal:
    """A bridge with a book: modifies change the rows the listings return.

    The fix for 'false success' needs a fake that can *disagree* with an
    envelope, so state lives here and the envelope is independent of it.
    """

    def __init__(self, positions=(), pending=(), deals=(), **responses: Any) -> None:
        self.positions = (
            [] if isinstance(positions, BaseException) else [dict(r) for r in positions]
        )
        self.pending = [] if isinstance(pending, BaseException) else [dict(r) for r in pending]
        self.applies = True
        wiring: dict[str, Any] = {
            "positions": positions
            if isinstance(positions, BaseException)
            else lambda: [dict(r) for r in self.positions],
            "pending": pending
            if isinstance(pending, BaseException)
            else lambda: [dict(r) for r in self.pending],
            "deals": deals if isinstance(deals, BaseException) else list(deals),
            "modify": self._modify,
            "modify_order": self._move,
            "cancel": self._cancel,
        }
        wiring.update(responses)
        self.bridge = FakeBridge(**wiring)

    def _modify(self, ticket, sl, tp):
        if self.applies:
            for row in self.positions:
                if row["ticket"] == ticket:
                    row["sl"], row["tp"] = sl, tp
        return DONE_ENVELOPE

    def _move(self, ticket, price):
        if self.applies:
            for row in self.pending:
                if row["ticket"] == ticket:
                    row["price_open"] = price
        return DONE_ENVELOPE

    def _cancel(self, ticket):
        self.pending = [r for r in self.pending if r["ticket"] != ticket]
        return DONE_ENVELOPE


class TestModifyAndCancel:
    """What the client sends to move or cancel, and that the engine hears the truth.

    The first version sent the request and returned, so an order stayed
    `PENDING_UPDATE` for good. The second announced success on the absence of
    a failure: an empty reply, a failed listing and a retcode of 0 all read as
    'done'. These tests give the fake a book that can disagree with the reply.
    """

    def _modify(self, rig, venue_order_id: VenueOrderId | None, price=None, trigger=None):
        order = _limit()
        rig.client._cache.add_order(order)
        return ModifyOrder(
            TestIdStubs.trader_id(),
            TestIdStubs.strategy_id(),
            EURUSD_ID,
            order.client_order_id,
            venue_order_id,
            None,
            price,
            trigger,
            UUID4(),
            time.time_ns(),
            ClientId("MT5"),
        )

    def _cancel(self, rig, venue_order_id: VenueOrderId | None) -> CancelOrder:
        order = _limit()
        rig.client._cache.add_order(order)
        return CancelOrder(
            TestIdStubs.trader_id(),
            TestIdStubs.strategy_id(),
            EURUSD_ID,
            order.client_order_id,
            venue_order_id,
            UUID4(),
            time.time_ns(),
            ClientId("MT5"),
        )

    # ── a position's stop and target ──

    async def test_a_target_only_modify_keeps_the_stop_the_position_has(self):
        """The worst of the fail-open paths: `sl=0` removes the stop in MT5.

        The first version sent `float(trigger_price or 0.0)`, so a modify that
        moved only the target came back with no stop at all.
        """
        terminal = Terminal(positions=[_held()])
        rig = make_exec(terminal.bridge)
        await rig.client._modify_order(
            self._modify(rig, VenueOrderId("55"), Price.from_str("1.095"))
        )
        assert rig.bridge.called("modify") == [((55, 1.08, 1.095), {})]
        assert rig.events(OrderUpdated)

    async def test_a_stop_only_modify_keeps_the_target(self):
        terminal = Terminal(positions=[_held()])
        rig = make_exec(terminal.bridge)
        command = self._modify(rig, VenueOrderId("55"), None, Price.from_str("1.0820"))
        await rig.client._modify_order(command)
        assert rig.bridge.called("modify") == [((55, 1.082, 1.09), {})]

    async def test_both_sides_are_sent_as_given(self):
        terminal = Terminal(positions=[_held()])
        rig = make_exec(terminal.bridge)
        command = self._modify(
            rig, VenueOrderId("55"), Price.from_str("1.09500"), Price.from_str("1.07")
        )
        await rig.client._modify_order(command)
        assert rig.bridge.called("modify") == [((55, 1.07, 1.095), {})]

    async def test_a_modify_that_changes_nothing_is_refused_before_the_bridge(self):
        terminal = Terminal(positions=[_held()])
        rig = make_exec(terminal.bridge)
        await rig.client._modify_order(self._modify(rig, VenueOrderId("55")))
        assert not rig.bridge.called("modify")
        assert "neither a stop nor a target" in rig.events(OrderModifyRejected)[0].reason

    async def test_no_modify_ever_sends_a_zero_stop_to_a_position_that_has_one(self):
        terminal = Terminal(positions=[_held()])
        rig = make_exec(terminal.bridge)
        await rig.client._modify_order(self._modify(rig, VenueOrderId("55"), Price.from_str("1.1")))
        assert all(args[1] != 0.0 for args, _ in rig.bridge.called("modify"))

    async def test_an_updated_event_carries_the_new_price_and_cached_quantity(self):
        terminal = Terminal(positions=[_held()])
        rig = make_exec(terminal.bridge)
        await rig.client._modify_order(
            self._modify(rig, VenueOrderId("55"), Price.from_str("1.095"))
        )
        (updated,) = rig.events(OrderUpdated)
        assert updated.price == Price.from_str("1.095")
        assert updated.quantity == Quantity.from_str("0.50")

    # ── a modify that must not read as a success ──

    @pytest.mark.parametrize(
        "reply",
        [
            {},
            {"success": True},
            {"success": True, "result": {"retcode": 0}},
            {"success": True, "result": {"retcode": 10013, "comment": "Invalid request"}},
            {"success": False, "result": {"retcode": 10009}},
        ],
    )
    async def test_a_reply_without_a_positive_signal_is_a_rejection(self, reply):
        """An empty body used to parse to retcode 0, and 0 was OK."""
        terminal = Terminal(positions=[_held()], modify=reply)
        rig = make_exec(terminal.bridge)
        await rig.client._modify_order(
            self._modify(rig, VenueOrderId("55"), Price.from_str("1.095"))
        )
        assert len(rig.events(OrderModifyRejected)) == 1
        assert not rig.events(OrderUpdated)

    async def test_the_brokers_comment_is_the_reason(self):
        reply = {"success": True, "result": {"retcode": 10016, "comment": "Invalid stops"}}
        terminal = Terminal(positions=[_held()], modify=reply)
        rig = make_exec(terminal.bridge)
        await rig.client._modify_order(
            self._modify(rig, VenueOrderId("55"), Price.from_str("1.095"))
        )
        assert rig.events(OrderModifyRejected)[0].reason == "Invalid stops"

    async def test_a_done_reply_the_book_does_not_bear_out_is_rejected(self):
        """DONE is the reply to the request; the listing is what the terminal holds."""
        terminal = Terminal(positions=[_held()])
        terminal.applies = False
        rig = make_exec(terminal.bridge)
        await rig.client._modify_order(
            self._modify(rig, VenueOrderId("55"), Price.from_str("1.095"))
        )
        assert "unconfirmed" in rig.events(OrderModifyRejected)[0].reason
        assert not rig.events(OrderUpdated)

    async def test_an_unreadable_book_after_a_done_reply_is_rejected_as_unconfirmed(self):
        terminal = Terminal(positions=[_held()])
        calls = {"n": 0}

        def positions():
            calls["n"] += 1
            if calls["n"] > 1:
                raise BridgeError("GET /positions/ -> 500")
            return [dict(r) for r in terminal.positions]

        terminal.bridge.responses["positions"] = positions
        rig = make_exec(terminal.bridge)
        await rig.client._modify_order(
            self._modify(rig, VenueOrderId("55"), Price.from_str("1.095"))
        )
        assert "unconfirmed" in rig.events(OrderModifyRejected)[0].reason

    async def test_an_unreadable_book_before_the_modify_sends_nothing(self):
        terminal = Terminal(positions=[_held()])
        terminal.bridge.responses["positions"] = BridgeError("GET /positions/ -> 500")
        rig = make_exec(terminal.bridge)
        await rig.client._modify_order(
            self._modify(rig, VenueOrderId("55"), Price.from_str("1.095"))
        )
        assert not rig.bridge.called("modify")
        assert len(rig.events(OrderModifyRejected)) == 1

    async def test_a_bridge_error_on_the_modify_is_a_rejection_not_a_raise(self):
        terminal = Terminal(positions=[_held()], modify=BridgeError("POST -> 500"))
        rig = make_exec(terminal.bridge)
        await rig.client._modify_order(
            self._modify(rig, VenueOrderId("55"), Price.from_str("1.095"))
        )
        assert "500" in rig.events(OrderModifyRejected)[0].reason

    async def test_a_modify_with_no_venue_id_is_rejected_rather_than_dropped(self):
        rig = make_exec()
        await rig.client._modify_order(self._modify(rig, None, Price.from_str("1.09000")))
        assert not rig.bridge.called("modify")
        assert "no venue id" in rig.events(OrderModifyRejected)[0].reason

    async def test_a_ticket_that_is_neither_resting_nor_open_is_rejected(self):
        rig = make_exec(Terminal().bridge)
        await rig.client._modify_order(
            self._modify(rig, VenueOrderId("55"), Price.from_str("1.09"))
        )
        assert "neither a resting order nor an open position" in (
            rig.events(OrderModifyRejected)[0].reason
        )

    async def test_another_desks_position_is_never_modified(self):
        terminal = Terminal(positions=[_held(magic=MAGIC + 1)])
        rig = make_exec(terminal.bridge)
        await rig.client._modify_order(
            self._modify(rig, VenueOrderId("55"), Price.from_str("1.09"))
        )
        assert not rig.bridge.called("modify")
        assert len(rig.events(OrderModifyRejected)) == 1

    async def test_a_modify_for_an_order_the_cache_lacks_is_rejected_before_the_bridge(self):
        """Its quantity is unknown, and `OrderUpdated` cannot be built without one."""
        rig = make_exec(Terminal(positions=[_held()]).bridge)
        command = self._modify(rig, VenueOrderId("55"), Price.from_str("1.09"))
        rig.client._cache.reset()
        await rig.client._modify_order(command)
        assert not rig.bridge.called("modify")
        assert len(rig.events(OrderModifyRejected)) == 1

    # ── a resting order ──

    async def test_a_resting_order_is_moved_through_the_pending_order_route(self):
        """It was posted to `/positions/modify` as a `tp`, which addresses a position."""
        terminal = Terminal(pending=[_pending(ticket=55)])
        rig = make_exec(terminal.bridge)
        await rig.client._modify_order(
            self._modify(rig, VenueOrderId("55"), Price.from_str("1.0790"))
        )
        assert rig.bridge.called("modify_order") == [((55, 1.079), {})]
        assert not rig.bridge.called("modify")
        assert rig.events(OrderUpdated)

    async def test_a_resting_order_move_the_book_does_not_bear_out_is_rejected(self):
        terminal = Terminal(pending=[_pending(ticket=55)])
        terminal.applies = False
        rig = make_exec(terminal.bridge)
        await rig.client._modify_order(
            self._modify(rig, VenueOrderId("55"), Price.from_str("1.0790"))
        )
        assert not rig.events(OrderUpdated)
        assert len(rig.events(OrderModifyRejected)) == 1

    async def test_a_resting_order_needs_a_price_to_move(self):
        terminal = Terminal(pending=[_pending(ticket=55)])
        rig = make_exec(terminal.bridge)
        command = self._modify(rig, VenueOrderId("55"), None, Price.from_str("1.07"))
        await rig.client._modify_order(command)
        assert not rig.bridge.called("modify_order")
        assert len(rig.events(OrderModifyRejected)) == 1

    async def test_a_transport_that_cannot_move_a_resting_order_says_so(self):
        class NoMove(FakeBridge):
            modify_order = None

        terminal = Terminal(pending=[_pending(ticket=55)])
        terminal.bridge.__class__ = NoMove
        rig = make_exec(terminal.bridge)
        await rig.client._modify_order(
            self._modify(rig, VenueOrderId("55"), Price.from_str("1.079"))
        )
        assert "cannot modify a resting order" in rig.events(OrderModifyRejected)[0].reason
        assert not rig.bridge.called("modify")

    # ── cancel ──

    async def test_a_confirmed_cancel_is_announced(self):
        terminal = Terminal(pending=[_pending(ticket=55)])
        rig = make_exec(terminal.bridge)
        await rig.client._cancel_order(self._cancel(rig, VenueOrderId("55")))
        assert rig.bridge.called("cancel") == [((55,), {})]
        (canceled,) = rig.events(OrderCanceled)
        assert canceled.venue_order_id == VenueOrderId("55")
        assert not rig.events(OrderCancelRejected)

    async def test_an_empty_reply_is_not_a_cancel(self):
        """`{}` is what the bridge returns for a 404, and for a transport that said nothing."""
        terminal = Terminal(pending=[], cancel={})
        rig = make_exec(terminal.bridge)
        await rig.client._cancel_order(self._cancel(rig, VenueOrderId("55")))
        assert not rig.events(OrderCanceled)
        assert "unconfirmed" in rig.events(OrderCancelRejected)[0].reason

    async def test_an_unreadable_listing_after_an_empty_reply_is_not_a_cancel(self):
        """The false confirmation: a failed listing read as 'the order is gone'."""
        terminal = Terminal(cancel={}, pending=BridgeError("GET /orders/pending -> 500"))
        rig = make_exec(terminal.bridge)
        await rig.client._cancel_order(self._cancel(rig, VenueOrderId("55")))
        assert not rig.events(OrderCanceled)
        assert "listing failed" in rig.events(OrderCancelRejected)[0].reason

    async def test_a_confirmed_cancel_stands_even_if_the_listing_cannot_be_read(self):
        """The terminal's own DONE outweighs an unreadable corroboration."""
        terminal = Terminal(pending=BridgeError("GET /orders/pending -> 500"))
        rig = make_exec(terminal.bridge)
        await rig.client._cancel_order(self._cancel(rig, VenueOrderId("55")))
        assert len(rig.events(OrderCanceled)) == 1

    async def test_a_cancel_after_which_the_order_still_rests_is_rejected(self):
        terminal = Terminal(pending=[_pending(ticket=55)])
        terminal.bridge.responses["cancel"] = DONE_ENVELOPE
        terminal.bridge.responses["cancel"] = lambda ticket: DONE_ENVELOPE  # leaves it resting
        rig = make_exec(terminal.bridge)
        await rig.client._cancel_order(self._cancel(rig, VenueOrderId("55")))
        assert "still resting" in rig.events(OrderCancelRejected)[0].reason
        assert not rig.events(OrderCanceled)

    async def test_an_unconfirmed_cancel_of_an_order_that_has_a_deal_is_a_fill(self):
        """If the order filled, say so; do not say it was cancelled."""
        terminal = Terminal(
            cancel={}, deals=[_deal(ticket=9001, order=55, volume=0.5, price=1.0852)]
        )
        rig = make_exec(terminal.bridge)
        await rig.client._cancel_order(self._cancel(rig, VenueOrderId("55")))
        (fill,) = rig.events(OrderFilled)
        assert fill.last_px == Price(1.0852, 5)
        assert not rig.events(OrderCanceled)

    async def test_an_unreadable_history_is_not_evidence_of_a_cancel(self):
        terminal = Terminal(cancel={}, deals=BridgeError("GET /history/deals -> 500"))
        rig = make_exec(terminal.bridge)
        await rig.client._cancel_order(self._cancel(rig, VenueOrderId("55")))
        assert not rig.events(OrderCanceled)
        assert "deals failed" in rig.events(OrderCancelRejected)[0].reason

    async def test_a_cancel_with_no_venue_id_is_rejected_rather_than_dropped(self):
        rig = make_exec()
        await rig.client._cancel_order(self._cancel(rig, None))
        assert not rig.bridge.called("cancel")
        assert "no venue id" in rig.events(OrderCancelRejected)[0].reason

    async def test_a_cancel_the_bridge_fails_is_rejected_not_raised(self):
        rig = make_exec(FakeBridge(cancel=BridgeError("DELETE -> 500")))
        await rig.client._cancel_order(self._cancel(rig, VenueOrderId("55")))
        assert len(rig.events(OrderCancelRejected)) == 1
        assert not rig.events(OrderCanceled)

    # ── cancel all ──

    def _resting(self, *rows: dict) -> FakeBridge:
        return Terminal(pending=rows).bridge

    async def test_cancel_all_cancels_only_this_desks_resting_orders(self):
        rig = make_exec(
            self._resting(
                {"ticket": 1, "magic": MAGIC, "symbol": "EURUSD", "type": 2},
                {"ticket": 2, "magic": MAGIC - 1, "symbol": "EURUSD", "type": 2},
                {"ticket": 3, "magic": 0, "symbol": "EURUSD", "type": 2},
                {"ticket": 4, "magic": MAGIC, "symbol": "EURUSD", "type": 3},
            )
        )
        await rig.client._cancel_all_orders(None)
        assert [args for args, _ in rig.bridge.called("cancel")] == [(1,), (4,)]

    async def test_cancel_all_announces_the_orders_the_cache_knows(self):
        order = _limit()
        rig = make_exec(self._resting({"ticket": 7, "magic": MAGIC, "symbol": "EURUSD", "type": 2}))
        rig.client._cache.add_order(order)
        rig.client._cache.add_venue_order_id(order.client_order_id, VenueOrderId("7"))
        await rig.client._cancel_all_orders(None)
        (canceled,) = rig.events(OrderCanceled)
        assert canceled.client_order_id == order.client_order_id

    async def test_cancel_all_cancels_an_unknown_order_at_the_terminal_and_stays_quiet(self):
        rig = make_exec(self._resting({"ticket": 8, "magic": MAGIC, "symbol": "EURUSD", "type": 2}))
        await rig.client._cancel_all_orders(None)
        assert rig.bridge.called("cancel") == [((8,), {})]
        assert not rig.events(OrderCanceled)

    async def test_cancel_all_with_an_unreadable_listing_raises_and_cancels_nothing(self):
        rig = make_exec(FakeBridge(pending=BridgeError("GET -> 500")))
        with pytest.raises(BridgeError):
            await rig.client._cancel_all_orders(None)
        assert not rig.bridge.called("cancel")

    async def test_cancel_all_respects_the_side_it_was_asked_for(self):
        from nautilus_trader.execution.messages import CancelAllOrders

        rig = make_exec(
            self._resting(
                {"ticket": 1, "magic": MAGIC, "symbol": "EURUSD", "type": 2},
                {"ticket": 2, "magic": MAGIC, "symbol": "EURUSD", "type": 3},
            )
        )
        command = CancelAllOrders(
            TestIdStubs.trader_id(),
            TestIdStubs.strategy_id(),
            EURUSD_ID,
            OrderSide.SELL,
            UUID4(),
            time.time_ns(),
            ClientId("MT5"),
        )
        await rig.client._cancel_all_orders(command)
        assert [args for args, _ in rig.bridge.called("cancel")] == [(2,)]


# ──── exec: reconciliation ────


def _position(**row: Any) -> dict:
    return {"ticket": 900, "symbol": "EURUSD", "type": 0, "volume": 0.5, "magic": MAGIC, **row}


def _pending(**row: Any) -> dict:
    return {
        "ticket": 71,
        "symbol": "EURUSD",
        "type": 2,
        "volume_current": 0.25,
        "price_open": 1.08,
        "magic": MAGIC,
        **row,
    }


def _deal(**row: Any) -> dict:
    return {
        "ticket": 5001,
        "order": 71,
        "symbol": "EURUSD",
        "type": 1,
        "volume": 0.5,
        "price": 1.0851,
        "commission": -0.35,
        "magic": MAGIC,
        **row,
    }


class TestPositionReports:
    """`judge-the-desk-on-the-broker-not-the-journal`: this is the broker's view."""

    async def test_a_buy_is_a_long_and_a_sell_is_a_short(self):
        rig = make_exec(
            FakeBridge(positions=[_position(type=0, ticket=1), _position(type=1, ticket=2)])
        )
        reports = await rig.client.generate_position_status_reports()
        assert [r.position_side for r in reports] == [PositionSide.LONG, PositionSide.SHORT]
        assert [str(r.venue_position_id) for r in reports] == ["1", "2"]

    async def test_the_quantity_is_at_the_instruments_precision(self):
        rig = make_exec(FakeBridge(positions=[_position(volume=0.5)]))
        (report,) = await rig.client.generate_position_status_reports()
        assert report.quantity == Quantity(0.5, 2)
        assert report.instrument_id == EURUSD_ID
        assert report.account_id == AccountId("MT5-5042")

    @pytest.mark.parametrize("magic", [MAGIC - 1, MAGIC + 1, 0, 123])
    async def test_a_position_with_another_magic_is_not_ours(self, magic):
        """Off by one is the neighbouring strategy; zero is a human's."""
        rig = make_exec(FakeBridge(positions=[_position(magic=magic)]))
        assert await rig.client.generate_position_status_reports() == []

    async def test_a_configured_magic_replaces_the_default(self):
        rig = make_exec(
            FakeBridge(positions=[_position(magic=MAGIC), _position(magic=5, ticket=2)]),
            magic=5,
        )
        reports = await rig.client.generate_position_status_reports()
        assert [str(r.venue_position_id) for r in reports] == ["2"]

    async def test_a_row_that_is_neither_a_buy_nor_a_sell_raises(self):
        """Skipping it would report a book smaller than the account's."""
        rig = make_exec(FakeBridge(positions=[_position(type=7)]))
        with pytest.raises(ReconciliationError, match="neither a buy nor a sell"):
            await rig.client.generate_position_status_reports()

    async def test_a_position_in_a_symbol_the_terminal_will_not_describe_raises(self):
        """A report that omits it says the account is flat in that name.

        A desk that believes it is flat re-opens the position it already holds,
        which is the failure `judge-the-desk-on-the-broker-not-the-journal`
        records. The row is this desk's (its magic), so it is not noise.
        """
        rig = make_exec(
            FakeBridge(
                positions=[_position(ticket=1), _position(ticket=2, symbol="NOSUCH")],
                symbol_info=lambda symbol: {} if symbol == "NOSUCH" else EURUSD_INFO,
            )
        )
        with pytest.raises(ReconciliationError, match="NOSUCH"):
            await rig.client.generate_position_status_reports()

    async def test_another_desks_unresolvable_position_does_not_stop_reconciliation(self):
        """Raising is for this desk's book; a stranger's position is none of its business."""
        rig = make_exec(
            FakeBridge(
                positions=[_position(ticket=1), _position(ticket=2, symbol="NOSUCH", magic=0)],
                symbol_info=lambda symbol: {} if symbol == "NOSUCH" else EURUSD_INFO,
            )
        )
        reports = await rig.client.generate_position_status_reports()
        assert [str(r.venue_position_id) for r in reports] == ["1"]

    async def test_a_position_in_an_instrument_not_yet_loaded_is_still_reported(self):
        """Before the on-demand load this read as flat, which is the dangerous answer."""
        rig = make_exec(FakeBridge(positions=[_position()]), loaded=False)
        (report,) = await rig.client.generate_position_status_reports()
        assert report.instrument_id == EURUSD_ID

    async def test_a_command_narrows_the_positions_to_its_instrument(self):
        rows = [_position(ticket=1), _position(ticket=2, symbol="GBPUSD")]
        rig = make_exec(FakeBridge(positions=rows))
        command = GeneratePositionStatusReports(EURUSD_ID, None, None, UUID4(), time.time_ns())
        reports = await rig.client.generate_position_status_reports(command)
        assert [str(r.venue_position_id) for r in reports] == ["1"]

    async def test_a_bridge_failure_propagates_rather_than_reading_as_flat(self):
        """An error must not be mistaken for 'no positions' - that would close them."""
        rig = make_exec(FakeBridge(positions=BridgeError("GET /positions/ -> 500")))
        with pytest.raises(BridgeError):
            await rig.client.generate_position_status_reports()

    async def test_no_positions_is_an_empty_report_list(self):
        rig = make_exec(FakeBridge(positions=[]))
        assert await rig.client.generate_position_status_reports() == []


class TestOrderStatusReports:
    """Resting orders only; a filled order is a position."""

    async def test_a_resting_order_is_reported_accepted_with_its_price_and_remainder(self):
        rig = make_exec(FakeBridge(pending=[_pending()]))
        (report,) = await rig.client.generate_order_status_reports()
        assert report.venue_order_id == VenueOrderId("71")
        assert report.order_status == OrderStatus.ACCEPTED
        assert report.quantity == Quantity(0.25, 2)
        assert report.price == Price(1.08, 5)
        assert report.filled_qty == Quantity(0, 2)

    @pytest.mark.parametrize(
        ("mt5_type", "side"),
        [
            (2, OrderSide.BUY),
            (3, OrderSide.SELL),
            (4, OrderSide.BUY),
            (5, OrderSide.SELL),
        ],
    )
    async def test_the_side_follows_the_mt5_pending_order_type(self, mt5_type, side):
        """2/4 are buy limit/stop and 3/5 are sell limit/stop; parity is the side."""
        rig = make_exec(FakeBridge(pending=[_pending(type=mt5_type)]))
        (report,) = await rig.client.generate_order_status_reports()
        assert report.order_side == side

    async def test_another_desks_orders_are_not_reported(self):
        rig = make_exec(FakeBridge(pending=[_pending(magic=MAGIC + 1), _pending(magic=0)]))
        assert await rig.client.generate_order_status_reports() == []

    async def test_query_order_sends_the_matching_report_only(self):
        rig = make_exec(FakeBridge(pending=[_pending(ticket=71), _pending(ticket=72)]))
        command = QueryOrder(
            TestIdStubs.trader_id(),
            TestIdStubs.strategy_id(),
            EURUSD_ID,
            _limit().client_order_id,
            VenueOrderId("72"),
            UUID4(),
            time.time_ns(),
            ClientId("MT5"),
        )
        await rig.client._query_order(command)
        assert [str(r.venue_order_id) for r in rig.reports] == ["72"]

    async def test_query_order_for_a_ticket_that_is_gone_sends_nothing(self):
        rig = make_exec(FakeBridge(pending=[_pending(ticket=71)]))
        command = QueryOrder(
            TestIdStubs.trader_id(),
            TestIdStubs.strategy_id(),
            EURUSD_ID,
            _limit().client_order_id,
            VenueOrderId("999"),
            UUID4(),
            time.time_ns(),
            ClientId("MT5"),
        )
        await rig.client._query_order(command)
        assert rig.reports == []


class TestAnUnreadableBookIsNotAnEmptyOne:
    """Reconciliation that skips what it cannot read reports a smaller account.

    The judgement call: raise for state the desk acts on (positions, resting
    orders), degrade loudly for history (deals). A fill report that is short
    by one day-old deal is repaired by the position report that carries the
    same fact; a position report that is short by one position tells the desk
    it is flat in a name it holds.
    """

    async def test_an_order_in_a_symbol_the_terminal_will_not_describe_raises(self):
        rig = make_exec(
            FakeBridge(
                pending=[_pending(symbol="NOSUCH")],
                symbol_info=lambda symbol: {} if symbol == "NOSUCH" else EURUSD_INFO,
            )
        )
        with pytest.raises(ReconciliationError, match="NOSUCH"):
            await rig.client.generate_order_status_reports()

    async def test_an_unreadable_order_listing_raises(self):
        rig = make_exec(FakeBridge(pending=BridgeError("GET -> 500")))
        with pytest.raises(BridgeError):
            await rig.client.generate_order_status_reports()

    async def test_an_unreadable_symbol_lookup_raises_rather_than_skipping(self):
        rig = make_exec(
            FakeBridge(positions=[_position()], symbol_info=BridgeError("GET -> 500")),
            loaded=False,
        )
        with pytest.raises(BridgeError):
            await rig.client.generate_position_status_reports()

    async def test_a_deal_in_an_unknown_symbol_is_skipped_counted_and_the_rest_reported(self):
        rig = make_exec(
            FakeBridge(
                deals=[_deal(ticket=1), _deal(ticket=2, symbol="NOSUCH")],
                symbol_info=lambda symbol: {} if symbol == "NOSUCH" else EURUSD_INFO,
            )
        )
        reports = await rig.client.generate_fill_reports()
        assert [str(r.trade_id) for r in reports] == ["1"]
        assert rig.client.skipped_deals == 1

    async def test_an_unreadable_history_raises(self):
        rig = make_exec(FakeBridge(deals=BridgeError("GET -> 500")))
        with pytest.raises(BridgeError):
            await rig.client.generate_fill_reports()


class TestCredentialsStayOutOfLoggedText:
    """The stream URL carried `api_key=` and exception text carries URLs.

    The repo is public and logs get pasted into issues. The transport is being
    changed to send the key as a header, but a URL can reach a log from more
    than one place, so the text is scrubbed where it is written.
    """

    KEY = "s3cr3t-key-123"

    @pytest.mark.parametrize(
        "text",
        [
            f"ws://bridge:8000/api/v1/stream?api_key={KEY}&symbols=EURUSD",
            f"GET https://bridge/x?API_KEY={KEY}",
            f"headers {{'X-API-Key': '{KEY}'}}",
            f"X-API-Key: {KEY}",
            f"connect to http://user:{KEY}@bridge:8000 failed",
            f"the key {KEY} was rejected",
        ],
    )
    def test_redact_removes_the_key_from_every_shape_it_arrives_in(self, text):
        assert self.KEY not in redact(text, (self.KEY,))

    def test_redact_keeps_the_rest_of_the_message_readable(self):
        out = redact(f"ws://bridge/stream?api_key={self.KEY}&symbols=EURUSD", (self.KEY,))
        assert out == "ws://bridge/stream?api_key=***&symbols=EURUSD"

    def test_a_short_secret_is_not_replaced_everywhere(self):
        """A 2-character 'secret' would mangle every word that contains it."""
        assert redact("a key", ("ke",)) == "a key"

    async def test_a_connect_failure_does_not_carry_the_key(self):
        """**Scrubbing the message is not enough if the original is chained.**

        `raise ConnectionError(scrubbed) from error` produces a clean message
        and a traceback that prints "The above exception was the direct cause"
        followed by the unscrubbed original - so the key reaches the log by the
        one route nobody thinks to check. The cause has to be dropped and the
        implicit context suppressed, which is what the last two assertions are
        for; the first alone passes on a chained raise.
        """
        error = httpx.ConnectError(f"All connection attempts failed: ?api_key={self.KEY}")
        rig = make_data(FakeBridge(ping=error), api_key=self.KEY)
        with pytest.raises(ConnectionError) as caught:
            await rig.client._connect()
        assert self.KEY not in str(caught.value)
        assert caught.value.__cause__ is None
        assert caught.value.__suppress_context__

    async def test_an_exec_connect_failure_does_not_carry_the_key(self):
        error = BridgeError(f"GET http://bridge?api_key={self.KEY} -> 401")
        rig = make_exec(FakeBridge(account=error), api_key=self.KEY)
        with pytest.raises(ConnectionError) as caught:
            await rig.client._connect()
        assert self.KEY not in str(caught.value)

    async def test_a_rejection_reason_does_not_carry_the_key(self):
        """Reasons are stored in events, and events go to the journal."""
        error = BridgeError(f"POST http://bridge?api_key={self.KEY} -> 500")
        terminal = Terminal(positions=[_held()], modify=error)
        rig = make_exec(terminal.bridge, api_key=self.KEY)
        command = TestModifyAndCancel()._modify(rig, VenueOrderId("55"), Price.from_str("1.095"))
        await rig.client._modify_order(command)
        assert self.KEY not in rig.events(OrderModifyRejected)[0].reason

    def test_the_clients_scrub_with_their_configured_key(self):
        async def build():
            return make_data(api_key=self.KEY), make_exec(api_key=self.KEY)

        data, execution = asyncio.run(build())
        for rig in (data, execution):
            assert self.KEY not in rig.client._scrub(f"boom {self.KEY}")


class TestASingleOrderStatusReport:
    """`generate_order_status_report` is what the base `_query_order` awaits."""

    def _command(self, venue_order_id=None, client_order_id=None):
        return GenerateOrderStatusReport(
            EURUSD_ID, client_order_id, venue_order_id, UUID4(), time.time_ns()
        )

    async def test_a_resting_order_is_found_by_its_venue_id(self):
        rig = make_exec(FakeBridge(pending=[_pending(ticket=71), _pending(ticket=72)]))
        report = await rig.client.generate_order_status_report(self._command(VenueOrderId("72")))
        assert report.venue_order_id == VenueOrderId("72")

    async def test_it_is_found_by_the_client_id_the_cache_remembers(self):
        order = _limit()
        rig = make_exec(FakeBridge(pending=[_pending(ticket=72)]))
        rig.client._cache.add_order(order)
        rig.client._cache.add_venue_order_id(order.client_order_id, VenueOrderId("72"))
        report = await rig.client.generate_order_status_report(
            self._command(client_order_id=order.client_order_id)
        )
        assert report.venue_order_id == VenueOrderId("72")

    async def test_an_order_that_is_not_resting_is_none(self):
        rig = make_exec(FakeBridge(pending=[_pending(ticket=71)]))
        assert (
            await rig.client.generate_order_status_report(self._command(VenueOrderId("9"))) is None
        )

    async def test_another_desks_order_is_none_even_with_its_ticket(self):
        rig = make_exec(FakeBridge(pending=[_pending(ticket=71, magic=MAGIC + 1)]))
        assert (
            await rig.client.generate_order_status_report(self._command(VenueOrderId("71"))) is None
        )

    async def test_no_id_at_all_is_none(self):
        rig = make_exec(FakeBridge(pending=[_pending()]))
        assert await rig.client.generate_order_status_report(self._command()) is None

    async def test_a_command_narrows_the_order_reports_to_its_instrument(self):
        rows = [_pending(ticket=1), _pending(ticket=2, symbol="GBPUSD")]
        rig = make_exec(FakeBridge(pending=rows))
        command = GenerateOrderStatusReports(EURUSD_ID, None, None, False, UUID4(), time.time_ns())
        reports = await rig.client.generate_order_status_reports(command)
        assert [str(r.venue_order_id) for r in reports] == ["1"]


class TestFillReports:
    """History deals, over the last day, for this desk's magic."""

    async def test_a_deal_becomes_a_fill_with_its_price_quantity_and_commission(self):
        rig = make_exec(FakeBridge(deals=[_deal()]))
        (report,) = await rig.client.generate_fill_reports()
        assert report.last_px == Price(1.0851, 5)
        assert report.last_qty == Quantity(0.5, 2)
        assert report.order_side == OrderSide.SELL
        assert str(report.trade_id) == "5001"
        assert str(report.venue_order_id) == "71"
        assert float(report.commission) == pytest.approx(-0.35)
        assert str(report.commission.currency) == "USD"

    async def test_the_window_is_the_last_day_plus_a_minute_of_slack(self):
        """The minute is on the *end* of the window, and it is for the
        terminal's clock rather than for the network.

        `clocks.py` measures the gap between a tick's stamp and its arrival
        and deliberately never applies it, so the broker's clock is free to
        sit ahead of ours - usually by a whole timezone. A window ending at
        `now` would then miss a deal the server stamped in our future, and a
        missed fill reconciles as an order that never filled.

        Both numbers are the shipped ones in `execution.py`; a day is the
        reconciliation horizon and the minute is slack, not a measurement.
        """
        rig = make_exec()
        before = int(rig.clock.timestamp_ns() / 1e9)
        await rig.client.generate_fill_reports()
        (start, end), _ = rig.bridge.called("deals")[0]
        assert end - start == 86_400 + 60
        assert abs(end - 60 - before) <= 2

    async def test_a_command_names_its_own_window_and_order(self):
        start = datetime(2026, 10, 1, tzinfo=UTC)
        end = datetime(2026, 10, 2, tzinfo=UTC)
        rig = make_exec(FakeBridge(deals=[_deal(order=71), _deal(ticket=2, order=72)]))
        command = GenerateFillReports(None, VenueOrderId("72"), start, end, UUID4(), time.time_ns())
        reports = await rig.client.generate_fill_reports(command)
        assert rig.bridge.called("deals") == [((int(start.timestamp()), int(end.timestamp())), {})]
        assert [str(r.trade_id) for r in reports] == ["2"]

    async def test_deals_with_other_magics_and_balance_rows_are_excluded(self):
        """A balance operation has magic 0, as does anything a human did."""
        deals = [_deal(), _deal(ticket=2, magic=MAGIC + 1), _deal(ticket=3, magic=0)]
        rig = make_exec(FakeBridge(deals=deals))
        reports = await rig.client.generate_fill_reports()
        assert [str(r.trade_id) for r in reports] == ["5001"]

    async def test_a_deal_without_an_order_falls_back_to_its_ticket(self):
        rig = make_exec(FakeBridge(deals=[_deal(order=None)]))
        (report,) = await rig.client.generate_fill_reports()
        assert str(report.venue_order_id) == "5001"

    async def test_a_bridge_failure_propagates(self):
        rig = make_exec(FakeBridge(deals=BridgeError("GET /history/deals -> 500")))
        with pytest.raises(BridgeError):
            await rig.client.generate_fill_reports()


# ──── the factories ────


class TestTheFactoriesWireTheClientsUp:
    """The factory builds the client before the loop is running; `_connect` does I/O."""

    async def _build(self, factory: Any, config: Any) -> Any:
        return factory.create(
            asyncio.get_running_loop(),
            "MT5",
            config,
            TestComponentStubs.msgbus(),
            TestComponentStubs.cache(),
            TestComponentStubs.clock(),
        )

    async def test_the_data_factory_builds_a_data_client(self):
        client = await self._build(MT5LiveDataClientFactory, MT5DataClientConfig())
        assert isinstance(client, MT5DataClient)
        assert client.id == ClientId("MT5")

    async def test_the_exec_factory_builds_a_netting_exec_client(self):
        """**MT5 nets**, and telling Nautilus otherwise would make its position
        book disagree with the terminal's.

        On a netting account a buy against an open short reduces that short;
        under `HEDGING` Nautilus would carry both as separate positions, so
        exposure would read as the sum of two legs the broker has already
        offset. The factory is where the choice is made, and it is not a
        setting - it is what this venue does.
        """
        from nautilus_trader.model.enums import OmsType

        client = await self._build(MT5LiveExecClientFactory, MT5ExecClientConfig())
        assert isinstance(client, MT5ExecutionClient)
        assert client.oms_type == OmsType.NETTING


# ──── the bridge on the wire ────


def _wired(handler) -> Bridge:
    bridge = Bridge("http://bridge:8000", "secret")
    bridge._client = httpx.AsyncClient(
        base_url="http://bridge:8000/api/v1",
        headers={"X-API-Key": "secret"},
        transport=httpx.MockTransport(handler),
    )
    return bridge


class TestTheBridgeSpeaksTheWireProtocol:
    """What actually crosses the network, for the writes that move money."""

    async def test_an_order_is_posted_as_json_to_the_trading_route(self):
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"success": True})

        await _wired(handler).order(
            {"symbol": "EURUSD", "order_type": "BUY", "volume": 0.1, "magic": MAGIC}
        )
        (request,) = seen
        assert (request.method, request.url.path) == ("POST", "/api/v1/trading/order")
        # **`sl` is present because the route requires it.**
        # `MarketOrderRequest` declares it as a bare `float` with no default,
        # so a body without it is a 422 - meaning no market order this adapter
        # sent could ever have been placed. Checked against the bridge repo's
        # `models/trading.py` rather than inferred.
        body = json.loads(request.read())
        assert body["sl"] == 0.0
        assert body["order_type"] == "BUY"
        assert body["magic"] == MAGIC
        assert "price" not in body, "a market order names no price"
        assert request.headers["X-API-Key"] == "secret"

    async def test_a_limit_order_is_posted_to_the_pending_route(self):
        """`/trading/order` validates `order_type` against `^(BUY|SELL)$` and
        calls `send_market_order`, which takes no price - so a limit sent
        there was accepted and **filled at the market**."""
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"success": True})

        await _wired(handler).order(
            {"symbol": "EURUSD", "order_type": "SELL", "volume": 0.1, "price": 1.2}
        )
        (request,) = seen
        assert request.url.path == "/api/v1/orders/pending"
        body = json.loads(request.read())
        assert body["order_type"] == "SELL_LIMIT"
        assert body["price"] == 1.2

    async def test_modify_sends_sl_and_only_sends_tp_when_there_is_one(self):
        bodies: list[bytes] = []

        def handler(request: httpx.Request) -> httpx.Response:
            bodies.append(request.read())
            return httpx.Response(200, json={})

        bridge = _wired(handler)
        await bridge.modify(55, 1.07, 1.09)
        await bridge.modify(55, 1.07)
        assert bodies == [b'{"ticket":55,"sl":1.07,"tp":1.09}', b'{"ticket":55,"sl":1.07}']

    async def test_cancel_is_a_delete_on_the_ticket(self):
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={})

        await _wired(handler).cancel(55)
        assert (seen[0].method, seen[0].url.path) == ("DELETE", "/api/v1/orders/55")

    async def test_close_sends_a_volume_only_when_partial(self):
        bodies: list[bytes] = []

        def handler(request: httpx.Request) -> httpx.Response:
            bodies.append(request.read())
            return httpx.Response(200, json={})

        bridge = _wired(handler)
        await bridge.close_position(9)
        await bridge.close_position(9, 0.25)
        assert bodies == [b'{"ticket":9}', b'{"ticket":9,"volume":0.25}']

    async def test_a_refusal_is_a_bridge_error_naming_the_route_and_status(self):
        bridge = _wired(lambda r: httpx.Response(400, text="invalid volume"))
        with pytest.raises(BridgeError, match=r"POST /trading/order -> 400: invalid volume"):
            await bridge.order({})

    async def test_a_404_reads_as_nothing_only_for_history(self):
        """**It used to mean "nothing" everywhere, and that was a fail-open on
        the money path.** A 404 from `/positions/` became an empty list, which
        is indistinguishable from a flat account - and reconciliation believing
        the desk is flat when it is not is how it opens a position it already
        holds.

        History keeps the old reading, because an empty range genuinely is the
        normal answer for a quiet market or a closed session.
        """
        bridge = _wired(lambda r: httpx.Response(404))
        assert await bridge.ticks("EURUSD", 0, 1) == []
        assert await bridge.bars("EURUSD", "M1", count=1) == []
        for call in (bridge.positions(), bridge.pending(), bridge.account()):
            with pytest.raises(BridgeError):
                await call

    async def test_bars_are_requested_by_position_with_the_documented_parameters(self):
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json=[{"time": 1}])

        rows = await _wired(handler).bars("EURUSD", "M1", count=2, start=1)
        assert rows == [{"time": 1}]
        assert seen[0].url.path == "/api/v1/symbols/rates/pos"
        assert dict(seen[0].url.params) == {
            "symbol": "EURUSD",
            "timeframe": "M1",
            "start_pos": "1",
            "count": "2",
        }

    async def test_close_releases_the_session_and_may_be_called_twice(self):
        bridge = _wired(lambda r: httpx.Response(200, json={}))
        await bridge.close()
        await bridge.close()
        with pytest.raises(BridgeError, match="not open"):
            _ = bridge.session

    # **`test_open_is_idempotent` went as a duplicate.** Session handling does
    # not cross the network, which is this class's subject, and
    # `test_mt5_adapter.TestTheSessionIsOpenedDeliberately` holds the same
    # property plus two things this copy did not: that the API key reaches the
    # session's headers, and that `session` raises again after a close. The
    # double-close case above is the one part that was only here, so it stays.
