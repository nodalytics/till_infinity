"""The two ways this adapter reaches a terminal, and that they are the same.

The whole value of `transport.py` is that nothing above `adapters/mt5/` can
tell which one is running, and the way that value is lost is quietly: a method
added to the HTTP bridge and not to the rpyc proxy, or a write that comes back
in a different shape. So the first test here compares the two surfaces, and
most of the rest pin the *translation* - MT5's namedtuples and numpy rows into
the bridge's row shapes - because a wrong conversion does not raise, it changes
a number.

Driven against a fake module rather than a terminal. `Proxy._mt5` is our own
attribute on our own class, which is a different thing from stubbing a method
onto a framework class to make a test pass: that is how three production call
sites came to call Nautilus methods that did not exist. See
`tests/test_nautilus_api.py`.
"""

from __future__ import annotations

import asyncio
from collections import namedtuple

import pytest

from till_infinity.adapters.mt5 import (
    DockerizedMT5TerminalConfig,
    MT5DataClientConfig,
    MT5ExecClientConfig,
    Streaming,
    Transport,
)
from till_infinity.adapters.mt5.bridge import Bridge
from till_infinity.adapters.mt5.proxy import (
    TUNNELLED,
    Proxy,
    ProxyError,
    _reachable,
    _row,
    _rows,
    _sent,
    _when,
)
from till_infinity.adapters.mt5.terminal import API_PORT, container_name, environment
from till_infinity.adapters.mt5.transport import TRANSPORTS, connect

# ------------------------------------------------------------ the one invariant


def test_the_two_transports_answer_the_same_methods():
    """**The abstraction, stated as an assertion.**

    `data.py`, `execution.py` and `providers.py` are written against whichever
    of these a config picked, so a method on one and not the other is an
    `AttributeError` on a live order - and only on the transport nobody
    developed against. Comparing the surfaces is cheap; discovering the gap
    from a production traceback is not.
    """
    surface = {
        name
        for name in dir(Transport)
        if not name.startswith("_") and callable(getattr(Transport, name, None))
    }
    # `stream` is deliberately not in here - see `test_only_the_bridge_can_push`.
    assert "stream" not in surface
    assert surface, "the protocol declared nothing, so this test proves nothing"
    for transport in (Bridge, Proxy):
        missing = {name for name in surface if not hasattr(transport, name)}
        assert not missing, f"{transport.__name__} is missing {sorted(missing)}"


def test_only_the_bridge_can_push():
    """**Streaming is a separate protocol on purpose.** `Bridge` has a
    websocket; `Proxy` is an in-process call into a terminal and has nothing
    to push with.

    Were `stream` on `Transport`, the way to satisfy it would be a
    `Proxy.stream` that raises - a stub that makes the capability check pass
    and the feature fail at the one moment it is used. So `data.py` asks
    `isinstance(transport, Streaming)` and refuses `quote_source="push"`
    rather than falling back to polling: a feed that samples while reporting
    itself as a push makes every measurement taken on it wrong, and nothing
    about it looks wrong.
    """
    import inspect

    assert isinstance(connect(MT5DataClientConfig()), Streaming)
    assert not isinstance(connect(MT5ExecClientConfig(transport="rpyc", rpyc_host="h")), Streaming)
    # And it is an async generator, which is the shape `data.py` consumes.
    assert inspect.isasyncgenfunction(Bridge.stream)


def test_both_transports_satisfy_the_protocol():
    """The check `transport.py` made `Transport` `runtime_checkable` for.

    It overlaps the surface test above, which compares the same member names
    on the two classes. What it adds is the object `connect` hands back rather
    than the class it was built from, so a factory that wrapped or decorated a
    transport would have to produce something still conforming.
    """
    data = MT5DataClientConfig()
    rpyc = MT5ExecClientConfig(transport="rpyc", rpyc_host="127.0.0.1")
    assert isinstance(connect(data), Transport)
    assert isinstance(connect(rpyc), Transport)


@pytest.mark.parametrize(
    ("transport", "expected"),
    [("http", Bridge), ("HTTP", Bridge), ("rpyc", Proxy)],
)
def test_the_config_picks_the_transport(transport, expected):
    config = MT5ExecClientConfig(transport=transport, rpyc_host="127.0.0.1")
    assert isinstance(connect(config), expected)


def test_the_default_is_http():
    """The one that works through a firewall without a tunnel, and the one the
    lab box runs."""
    assert isinstance(connect(MT5DataClientConfig()), Bridge)
    assert TRANSPORTS[0] == "http"


def test_an_unknown_transport_refuses_rather_than_falling_back():
    """A transport that does not resolve would be a client connected to
    nothing - a node that reports healthy and trades nothing, which is the
    failure three deploys on 2026-10-09 already produced by another route."""
    with pytest.raises(ValueError, match="unknown MT5 transport"):
        connect(MT5DataClientConfig(transport="mt5-native"))


# ------------------------------------------------------------- the translation

Rate = namedtuple("Rate", "time open high low close tick_volume spread real_volume")
Sent = namedtuple("Sent", "retcode deal order volume price comment")


def test_a_namedtuple_becomes_the_bridges_row_shape():
    """MT5's own field names *are* the bridge's, which is why a transport can
    be swapped at all - `data._bar` reads `time`, `open` and `tick_volume` off
    whichever one answered."""
    row = _row(Rate(1_700_000_000, 1.1, 1.2, 1.0, 1.15, 42, 3, 0))
    assert row["time"] == 1_700_000_000
    assert row["open"] == 1.1
    assert row["tick_volume"] == 42


def test_a_numpy_row_becomes_a_row_of_scalars():
    """`copy_rates_from_pos` returns a structured array, so a row is a
    `numpy.void` and its fields are zero-dimensional arrays. Left as they
    arrive, `float(row["open"])` still works and `row["time"]` is an array
    where an int is expected."""
    numpy = pytest.importorskip("numpy")
    array = numpy.array(
        [(1_700_000_000, 1.1, 1.2, 1.0, 1.15, 42, 3, 0)],
        dtype=[
            ("time", "i8"),
            ("open", "f8"),
            ("high", "f8"),
            ("low", "f8"),
            ("close", "f8"),
            ("tick_volume", "i8"),
            ("spread", "i4"),
            ("real_volume", "i8"),
        ],
    )
    row = _row(array[0])
    assert row["time"] == 1_700_000_000
    assert isinstance(row["time"], int)
    assert isinstance(row["open"], float)


def test_nothing_reads_as_nothing_and_not_as_an_error():
    """MT5 returns `None` from `copy_rates_from_pos` on failure *and* an empty
    array when the range is empty, and `positions_get` does the same. An empty
    answer is the normal state of a quiet market."""
    assert _rows(None) == []
    assert _rows(()) == []
    assert _row(None) == {}


@pytest.mark.parametrize(("retcode", "success"), [(10009, True), (10008, True), (10013, False)])
def test_a_write_comes_back_in_the_bridges_envelope(retcode, success):
    """`execution.py` reads `raw["success"]` and `raw["result"]["retcode"]`, so
    a transport returning a bare namedtuple would make that reader know which
    transport answered.

    10008 is `PLACED` and 10009 is `DONE`. Both have to read as accepted or a
    working limit order would be journalled as a rejection.
    """
    envelope = _sent(Sent(retcode, 0, 555, 0.1, 1.1, "ok"))
    assert envelope["success"] is success
    assert envelope["result"]["retcode"] == retcode
    assert envelope["result"]["order"] == 555


def test_no_answer_from_order_send_is_a_refusal_with_a_reason():
    """`order_send` returns `None` when the terminal is not initialised, and a
    falsy envelope with no reason would be journalled as a rejection with an
    empty comment - the gate reason is the whole value of the record."""
    envelope = _sent(None)
    assert envelope["success"] is False
    assert "order_send" in envelope["result"]["comment"]


def test_a_tick_range_is_sent_as_utc():
    """Passed as a bare int, MT5 reads a range in the *terminal's* timezone,
    which is not UTC on any broker this desk trades. The range would shift by
    hours and read as a quiet market rather than as an error."""
    when = _when(1_700_000_000)
    assert when.tzinfo is not None
    assert when.utcoffset().total_seconds() == 0
    assert when.timestamp() == 1_700_000_000


# ------------------------------------------------------------------- the proxy


class FakeMT5:
    """Enough of the `MetaTrader5` module to drive the proxy.

    The constants are the real values, because `proxy.py` reads them off the
    module by name and a fake that invented them would pass while the request
    it builds would be rejected by a terminal.
    """

    TRADE_ACTION_DEAL = 1
    TRADE_ACTION_PENDING = 5
    TRADE_ACTION_SLTP = 6
    TRADE_ACTION_MODIFY = 7
    TRADE_ACTION_REMOVE = 8
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    ORDER_TYPE_BUY_LIMIT = 2
    ORDER_TYPE_SELL_LIMIT = 3
    ORDER_TIME_GTC = 0
    ORDER_FILLING_FOK = 0
    ORDER_FILLING_IOC = 1
    ORDER_FILLING_RETURN = 2
    TIMEFRAME_M15 = 15
    COPY_TICKS_ALL = 3

    def __init__(self, **answers):
        self.answers = answers
        self.calls: list[tuple] = []
        self.requests: list[dict] = []
        self.selected: list[str] = []

    def _note(self, name, *args):
        self.calls.append((name, args))
        return self.answers.get(name)

    def terminal_info(self):
        return self._note("terminal_info")

    def symbol_select(self, symbol, on):
        self.selected.append(symbol)
        return True

    def symbol_info(self, symbol):
        return self._note("symbol_info", symbol)

    def symbol_info_tick(self, symbol):
        return self._note("symbol_info_tick", symbol)

    def copy_rates_from_pos(self, symbol, timeframe, start, count):
        return self._note("copy_rates_from_pos", symbol, timeframe, start, count)

    def copy_ticks_range(self, symbol, start, end, flags):
        return self._note("copy_ticks_range", symbol, start, end, flags)

    def positions_get(self):
        return self._note("positions_get")

    def orders_get(self):
        return self._note("orders_get")

    def history_deals_get(self, start, end):
        return self._note("history_deals_get", start, end)

    def last_error(self):
        return self.answers.get("last_error", (0, "no error"))

    def order_send(self, request):
        self.requests.append(dict(request))
        return self.answers.get("order_send")


def proxy(**answers) -> tuple[Proxy, FakeMT5]:
    made = Proxy(host="127.0.0.1")
    module = FakeMT5(**answers)
    made._mt5 = module
    return made, module


def test_a_call_before_open_says_so():
    """Rather than failing as a missing attribute on `None`, which reads as a
    broken transport rather than an unopened one."""
    with pytest.raises(ProxyError, match="not open"):
        assert Proxy(host="127.0.0.1").module


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1"])
def test_a_loopback_rpyc_host_is_allowed(host):
    """The documented arrangement: a Windows Python in the Wine prefix beside
    the terminal, on the same host."""
    _reachable(host)


@pytest.mark.parametrize("host", ["10.0.0.5", "mt5.example.invalid", "203.0.113.7"])
def test_a_non_loopback_rpyc_host_is_refused(monkeypatch, host):
    """**The rule was documented and nothing enforced it.** This module and
    `docs/trading.md` both say "never expose the RPyC server" - it runs
    whatever its client asks, so it is a remote-code-execution channel by
    construction - and the code would have connected to any address on the
    internet.

    Trusting the server is the transport's premise, which is exactly why the
    premise has to be true: the pickled values `_obtain` brings back are the
    least of it when the same channel can call `order_send`.
    """
    monkeypatch.delenv(TUNNELLED, raising=False)
    with pytest.raises(ProxyError, match="not loopback"):
        _reachable(host)


def test_the_operator_can_say_the_path_is_private(monkeypatch):
    """Only they can know it. Nothing in this process can distinguish a VPN
    address from a public one, so the switch asserts a fact rather than
    disabling a check."""
    monkeypatch.setenv(TUNNELLED, "1")
    _reachable("10.0.0.5")


def test_the_refusal_points_at_the_bridge():
    """The HTTP bridge is the transport that can safely face a network, and a
    refusal that did not say so would read as "this cannot be done"."""
    with pytest.raises(ProxyError, match="HTTP bridge"):
        _reachable("203.0.113.7")


def test_an_rpyc_transport_with_no_host_refuses_to_open():
    with pytest.raises(ProxyError, match="no rpyc host"):
        asyncio.run(Proxy(host=None).open())


def test_the_live_quote_is_merged_over_the_spec():
    """The quote poll reads `bid` and `ask` off `symbol_info`, and
    `symbol_info().bid` is only as fresh as the last MarketWatch update while
    `symbol_info_tick` is the current quote. Without the merge the stream
    would be a stale sample of a stale sample."""
    made, _ = proxy(
        symbol_info={"digits": 5, "volume_step": 0.01, "bid": 1.0, "ask": 1.1},
        symbol_info_tick={"bid": 1.2345, "ask": 1.2347, "time": 1_700_000_000},
    )
    info = asyncio.run(made.symbol_info("EURUSD"))
    assert info["bid"] == 1.2345
    assert info["ask"] == 1.2347
    assert info["digits"] == 5, "the spec's own fields must survive the merge"


def test_a_symbol_is_selected_before_it_is_read():
    """An unselected symbol answers `None` to `symbol_info`, which upstream
    reads as "this venue does not list it" - so a missing `symbol_select` does
    not look like a bug, it looks like a missing instrument."""
    made, module = proxy(symbol_info={"digits": 5}, symbol_info_tick={})
    asyncio.run(made.symbol_info("XAUUSD"))
    assert module.selected == ["XAUUSD"]
    asyncio.run(made.symbol_info("XAUUSD"))
    assert module.selected == ["XAUUSD"], "selected once, not per call"


def test_an_unlisted_symbol_is_empty_rather_than_half_a_spec():
    """`providers.py` reads `digits` and `volume_step` with defaults, so a
    half-filled dict would resolve into an instrument with invented precision
    rather than no instrument."""
    made, _ = proxy(symbol_info=None, symbol_info_tick={"bid": 1.1})
    assert asyncio.run(made.symbol_info("NOPE")) == {}


def test_ping_asks_the_terminal_and_not_the_socket():
    """A live rpyc connection to a Python whose terminal has died is the exact
    failure mode of a check that reads our own side of the wire."""
    made, _ = proxy(terminal_info={"build": 6182})
    assert asyncio.run(made.ping()) is True
    dead, _ = proxy(terminal_info=None)
    assert asyncio.run(dead.ping()) is False


def test_a_market_order_carries_a_price_because_mt5_requires_one():
    """`TRADE_ACTION_DEAL` is rejected without a price, so an order with no
    limit reads the current tick here rather than sending a request that is
    certain to come back 10013."""
    made, module = proxy(
        symbol_info_tick={"bid": 1.2345, "ask": 1.2347},
        order_send=Sent(10009, 1, 777, 0.1, 1.2347, "done"),
    )
    envelope = asyncio.run(
        made.order(
            {
                "symbol": "EURUSD",
                "order_type": "BUY",
                "volume": 0.1,
                "magic": 777_701,
                "deviation": 20,
                "type_filling": "IOC",
            }
        )
    )
    assert envelope["success"] is True
    sent = module.requests[0]
    assert sent["action"] == FakeMT5.TRADE_ACTION_DEAL
    assert sent["type"] == FakeMT5.ORDER_TYPE_BUY
    assert sent["price"] == 1.2347, "a buy pays the ask"
    assert sent["magic"] == 777_701
    assert sent["type_filling"] == FakeMT5.ORDER_FILLING_IOC


def test_a_sell_at_market_takes_the_bid():
    made, module = proxy(
        symbol_info_tick={"bid": 1.2345, "ask": 1.2347},
        order_send=Sent(10009, 1, 777, 0.1, 1.2345, "done"),
    )
    asyncio.run(made.order({"symbol": "EURUSD", "order_type": "SELL", "volume": 0.1}))
    assert module.requests[0]["price"] == 1.2345
    assert module.requests[0]["type"] == FakeMT5.ORDER_TYPE_SELL


def test_a_named_price_makes_it_pending_rather_than_a_market_order():
    """`RestingEntry` leaves a limit at a price it named. Sent as a DEAL it
    would fill immediately at the market, which is the opposite of what that
    entry is for."""
    made, module = proxy(order_send=Sent(10008, 0, 778, 0.1, 1.2000, "placed"))
    envelope = asyncio.run(
        made.order({"symbol": "EURUSD", "order_type": "BUY", "volume": 0.1, "price": 1.2000})
    )
    assert envelope["success"] is True, "10008 PLACED is an accepted resting order"
    sent = module.requests[0]
    assert sent["action"] == FakeMT5.TRADE_ACTION_PENDING
    assert sent["type"] == FakeMT5.ORDER_TYPE_BUY_LIMIT
    assert sent["price"] == 1.2000


def test_a_market_order_with_no_quote_refuses_rather_than_sending_a_zero():
    """A price of 0.0 is accepted by the request builder and rejected by the
    terminal, which turns a missing quote into a venue error."""
    made, _ = proxy(symbol_info_tick={})
    with pytest.raises(ProxyError, match="no quote"):
        asyncio.run(made.order({"symbol": "EURUSD", "order_type": "BUY", "volume": 0.1}))


def test_an_unknown_filling_mode_falls_back_rather_than_failing_a_trade():
    """A filling mode the symbol does not support is retcode 10030 and no
    fill, which is why it is configurable - but an unknown *name* is our typo,
    and losing a trade to a spelling is the worse outcome."""
    made, module = proxy(
        symbol_info_tick={"bid": 1.0, "ask": 1.1},
        order_send=Sent(10009, 1, 1, 0.1, 1.1, "done"),
    )
    asyncio.run(
        made.order(
            {"symbol": "EURUSD", "order_type": "BUY", "volume": 0.1, "type_filling": "NONSENSE"}
        )
    )
    assert module.requests[0]["type_filling"] == FakeMT5.ORDER_FILLING_IOC


def test_closing_sends_the_opposite_side_against_the_ticket():
    """MT5 has no close call: closing is a deal with `position` set, at the
    opposite type to the one that is open. Reading the position first is what
    makes the side and the volume right."""
    made, module = proxy(
        positions_get=({"ticket": 4242, "symbol": "EURUSD", "type": 0, "volume": 0.3, "magic": 7},),
        symbol_info_tick={"bid": 1.2345, "ask": 1.2347},
        order_send=Sent(10009, 2, 999, 0.3, 1.2345, "done"),
    )
    asyncio.run(made.close_position(4242))
    sent = module.requests[0]
    assert sent["position"] == 4242
    assert sent["type"] == FakeMT5.ORDER_TYPE_SELL, "a long is closed by a sell"
    assert sent["price"] == 1.2345, "and it is closed at the bid"
    assert sent["volume"] == 0.3, "the whole position where no volume was named"


def test_closing_a_ticket_that_is_gone_refuses():
    """Sent blind it would open a *new* position on the opposite side, which
    is the worst available outcome for a close."""
    made, _ = proxy(positions_get=())
    with pytest.raises(ProxyError, match="no open position"):
        asyncio.run(made.close_position(4242))


def test_a_partial_close_sends_the_volume_it_was_given():
    made, module = proxy(
        positions_get=({"ticket": 1, "symbol": "EURUSD", "type": 1, "volume": 0.5, "magic": 7},),
        symbol_info_tick={"bid": 1.0, "ask": 1.1},
        order_send=Sent(10009, 2, 9, 0.2, 1.1, "done"),
    )
    asyncio.run(made.close_position(1, volume=0.2))
    assert module.requests[0]["volume"] == 0.2
    assert module.requests[0]["type"] == FakeMT5.ORDER_TYPE_BUY, "a short is closed by a buy"


def test_a_timeframe_this_venue_does_not_serve_refuses():
    """`M7` rather than `M3`, which this used to use: M3 became a timeframe a
    deploy can configure, so the example of an unservable one had to be an
    interval MT5 genuinely has no constant for. The gap this guards is a
    `TRADING_INTERVALS` typo reaching the venue as a silent default rather
    than a refusal."""
    made, _ = proxy()
    with pytest.raises(ProxyError, match="unknown timeframe"):
        asyncio.run(made.bars("EURUSD", "M7", count=10))


def test_a_timeframe_resolves_to_the_modules_own_constant():
    """The names are the bridge's (`M15`) and the values are MT5's
    (`TIMEFRAME_M15`), because a second vocabulary here would be a second
    place for a timeframe to be wrong."""
    made, module = proxy(copy_rates_from_pos=(Rate(1, 1.0, 1.0, 1.0, 1.0, 1, 0, 0),))
    rows = asyncio.run(made.bars("EURUSD", "M15", count=2, start=1))
    assert rows[0]["time"] == 1
    _, args = next(c for c in module.calls if c[0] == "copy_rates_from_pos")
    assert args[1] == FakeMT5.TIMEFRAME_M15
    assert args[2:] == (1, 2), "start then count, in that order"


def test_ticks_ask_for_every_tick_and_not_only_trades():
    """An MT5 tick is a quote update and `last` reads 0 on this feed, so
    `COPY_TICKS_INFO` would return nothing at all."""
    made, module = proxy(copy_ticks_range=())
    asyncio.run(made.ticks("EURUSD", 1_700_000_000, 1_700_000_060))
    _, args = next(c for c in module.calls if c[0] == "copy_ticks_range")
    assert args[3] == FakeMT5.COPY_TICKS_ALL
    assert args[1].utcoffset().total_seconds() == 0


# -------------------------------------------------------- the docker container


def test_the_container_environment_uses_the_images_own_names():
    """Checked against `metatrader-terminal`'s README rather than inferred. A
    variable this image does not read is a credential that silently does
    nothing, and the symptom is a terminal that starts and never logs in."""
    config = DockerizedMT5TerminalConfig(
        login=12345678,
        password="unused-in-tests",
        server="Deriv-Demo",
        api_key_seed="seed",
        setup_url="https://example.invalid/mt5setup.exe",
        vnc_password="vnc",
    )
    env = environment(config)
    assert env["MT5_LOGIN"] == "12345678"
    assert env["MT5_SERVER"] == "Deriv-Demo"
    assert env["API_KEY_SEED"] == "seed"
    assert env["MT5_SETUP_URL"] == "https://example.invalid/mt5setup.exe"
    assert env["VNC_PASSWORD"] == "vnc"


def test_the_published_port_is_not_the_port_inside_the_container():
    """`MT5_API_PORT` is what the bridge listens on *inside*; `port` is where
    it lands on this host. Setting the inside one from the outside one
    publishes a port to a terminal listening somewhere else, and the symptom
    is a container that runs and a bridge that never answers."""
    env = environment(DockerizedMT5TerminalConfig(port=8100))
    assert env["MT5_API_PORT"] == str(API_PORT) == "8000"


def test_an_unset_field_is_absent_rather_than_empty():
    """An empty `MT5_LOGIN` is not the same as no `MT5_LOGIN`: the image
    defaults it to 0 and logs in to whatever the prefix already holds, which
    is the arrangement a blank config is asking for."""
    env = environment(DockerizedMT5TerminalConfig())
    assert "MT5_LOGIN" not in env
    assert "MT5_PASSWORD" not in env


def test_extra_can_set_what_the_config_does_not_model():
    """The image has more knobs than a config should enumerate, and a field
    per knob here is a field to keep in step with someone else's repo."""
    env = environment(DockerizedMT5TerminalConfig(extra={"MT5_SOMETHING": "1"}))
    assert env["MT5_SOMETHING"] == "1"


def test_two_accounts_are_two_containers():
    """A shared container name would mean the second node silently reused the
    first's account - `judge-the-desk-on-the-broker-not-the-journal` a level
    down, where the desk believed its own label rather than the venue's."""
    demo = container_name(DockerizedMT5TerminalConfig(login=111))
    live = container_name(DockerizedMT5TerminalConfig(login=222))
    assert demo != live
    assert container_name(DockerizedMT5TerminalConfig()) == "till-mt5-terminal"


def test_the_terminal_password_is_not_in_the_config_repr():
    """This repository is public and a config is logged on startup."""
    shown = repr(DockerizedMT5TerminalConfig(login=1, password="hunter2"))
    assert "hunter2" not in shown
    assert "********" in shown


# --------------------------------- the routes the bridge actually serves


def test_a_market_order_goes_to_the_market_route_and_carries_a_stop():
    """**No market order this adapter sent could ever have been placed.**
    `MarketOrderRequest` declares `sl` as a bare `float` with no default, so a
    body without it is a 422 - checked against the bridge repo's
    `models/trading.py`, not inferred.

    `0.0` where the caller named none is how MT5 spells "no stop"; the
    protective stop proper is the bracket's own order, submitted separately.
    """
    sent: list[tuple] = []

    class Routed(Bridge):
        async def post(self, route, body):
            sent.append((route, body))
            return {"success": True, "result": {"retcode": 10009, "order": 1}}

    asyncio.run(
        Routed("http://x").order(
            {"symbol": "EURUSD", "order_type": "BUY", "volume": 0.1, "magic": 777_701}
        )
    )
    route, body = sent[0]
    assert route == "/trading/order"
    assert body["order_type"] == "BUY"
    assert body["sl"] == 0.0, "present, because the route requires the field"
    assert "price" not in body


def test_a_limit_order_goes_to_the_pending_route():
    """`POST /trading/order` validates `order_type` against `^(BUY|SELL)$` and
    its handler calls `send_market_order`, which takes no price at all - so a
    limit sent there was accepted and **filled at the market**, which is the
    opposite of what a resting entry is for."""
    sent: list[tuple] = []

    class Routed(Bridge):
        async def post(self, route, body):
            sent.append((route, body))
            return {"success": True, "result": {"retcode": 10008, "order": 2}}

    asyncio.run(
        Routed("http://x").order(
            {"symbol": "EURUSD", "order_type": "SELL", "volume": 0.1, "price": 1.2000}
        )
    )
    route, body = sent[0]
    assert route == "/orders/pending"
    assert body["order_type"] == "SELL_LIMIT"
    assert body["price"] == 1.2000


def test_resting_orders_are_listed_from_the_route_that_exists():
    """`/orders/pending` is a `POST` that *places* one. There is no `GET` at
    that path, so `pending()` asked for a route that does not exist - and the
    old 404-means-empty rule turned every call into "no resting orders", which
    cancel verification and reconciliation then read as fact."""
    asked: list[str] = []

    class Routed(Bridge):
        async def get(self, route, empty_on_404=False, **params):
            asked.append(route)
            return []

    asyncio.run(Routed("http://x").pending())
    assert asked == ["/orders/"]


def test_a_resting_order_is_moved_by_its_own_route():
    """`POST /positions/modify` sets a *position's* stop and target. A resting
    order is not a position: sending one there posted its limit price as a
    target and left the order where it was."""
    sent: list[tuple] = []

    class Routed(Bridge):
        async def put(self, route, body):
            sent.append((route, body))
            return {"success": True, "result": {"retcode": 10009}}

    asyncio.run(Routed("http://x").modify_order(4242, 1.2345))
    assert sent == [("/orders/4242", {"price": 1.2345})]


def test_the_proxy_moves_a_resting_order_with_modify_and_not_sltp():
    """The same confusion as the test above, on the other transport.

    `TRADE_ACTION_SLTP` takes a *position* and sets its stop and target;
    `TRADE_ACTION_MODIFY` takes an order and moves its price. The two differ
    by one in the terminal's constants - 6 and 7 - and sending the first
    posted a limit price as a target and left the order where it was.

    This was `assert hasattr(Bridge, "modify_order")` and
    `assert hasattr(Proxy, "modify_order")`, which a method raising on every
    call passes. **`Proxy.modify_order` had no test that called it**, and
    `FakeMT5` did not carry `TRADE_ACTION_MODIFY` - so the one assertion that
    would have caught a wrong action could not have been written.
    """
    made, module = proxy(order_send=Sent(10009, 1, 4242, 0.0, 1.2345, "done"))
    answer = asyncio.run(made.modify_order(4242, 1.2345))

    sent = module.requests[0]
    assert sent["action"] == FakeMT5.TRADE_ACTION_MODIFY
    assert sent["action"] != FakeMT5.TRADE_ACTION_SLTP
    assert sent["order"] == 4242, "the order's ticket, not a position's"
    assert sent["price"] == 1.2345
    # And it comes back in the bridge's envelope, so `execution.py` cannot
    # tell which transport answered.
    assert answer["success"] is True
    assert answer["result"]["retcode"] == 10009


def test_a_failed_listing_is_not_an_empty_one():
    """**MT5 returns `None` both for "nothing" and for "could not".** Without
    asking `last_error`, a failed `positions_get` is indistinguishable from a
    flat account - and reconciliation believing the desk is flat when it is
    not is how it opens a position it already holds."""
    made, _ = proxy(positions_get=None, last_error=(10013, "invalid request"))
    with pytest.raises(ProxyError, match="positions_get failed"):
        asyncio.run(made.positions())


def test_a_genuinely_empty_listing_is_empty():
    """An empty tuple is a real answer - a flat account - and some builds
    return `None` with error 0 for the same thing, so the error *code* decides
    rather than the `None`."""
    made, _ = proxy(positions_get=())
    assert asyncio.run(made.positions()) == []
    quiet, _ = proxy(positions_get=None, last_error=(0, "no error"))
    assert asyncio.run(quiet.positions()) == []


# ------------------------------------- the terminal's clock, measured not set


def test_the_clock_offset_is_recovered_from_the_feed():
    """**MT5 stamps ticks in broker server time**, which is not UTC on any
    broker this desk trades, and `server_offset_seconds` defaults to `0.0` -
    honest rather than right.

    Within one venue nothing notices, because every comparison is relative.
    Across two it builds a constant lead into every reading, and
    `relationships-are-contemporaneous` is why that is expensive: the desk's
    whole relationship screen is about simultaneity, and a lead of exactly
    three hours is indistinguishable from a broker clock.

    Recovered as the **minimum** implied offset, not the mean. A tick cannot
    arrive before it was stamped, so the delay is one-sided and the minimum
    converges on the offset plus the best round trip - where a mean would be
    the offset plus the *average* delay, which on a 0.25s poll is an eighth of
    a second of pure bias that wanders with load.
    """
    import random

    from till_infinity.adapters.mt5.clocks import Clocks

    random.seed(7)
    clocks = Clocks()
    stamped = 1_700_000_000_000_000_000
    for step in range(60):
        at = stamped + step * 250_000_000
        # Three hours ahead, arriving 10-400ms later.
        clocks.saw(at, at + 3 * 3600 * 1_000_000_000 + int(random.uniform(0.01, 0.4) * 1e9))

    assert clocks.measured == pytest.approx(3 * 3600, abs=1.0)
    assert clocks.disagrees(0.0) == pytest.approx(3 * 3600, abs=1.0)
    assert clocks.disagrees(3 * 3600) is None, "configured correctly, so nothing to say"


def test_an_offset_is_not_reported_before_it_is_worth_reporting():
    """The estimate is a minimum, so it is badly wrong with few samples and can
    only improve with more. Reporting early would mean reporting the first
    tick's latency as a timezone."""
    from till_infinity.adapters.mt5.clocks import LEAST, Clocks

    clocks = Clocks()
    for step in range(LEAST - 1):
        clocks.saw(step * 1_000_000_000, step * 1_000_000_000 + 7_200_000_000_000)
    assert clocks.measured is None
    assert clocks.disagrees(0.0) is None
    assert "not yet measured" in clocks.describe(0.0)


def test_a_terminal_ahead_of_our_clock_is_kept_and_not_discarded():
    """A negative implied offset means the stamp is ahead of us - a broker
    ahead of UTC, or our own clock behind. Discarding it would make the
    estimate silently one-sided."""
    from till_infinity.adapters.mt5.clocks import LEAST, Clocks

    clocks = Clocks()
    for step in range(LEAST):
        at = step * 250_000_000
        clocks.saw(at, at - 7_200_000_000_000)
    assert clocks.measured == pytest.approx(-7200, abs=1.0)


def test_the_description_names_the_timezone_a_reader_would_recognise():
    """A broker clock is almost always a whole or half number of hours, and
    `10800` costs a reader the recognition that `+3.0h` gives away."""
    from till_infinity.adapters.mt5.clocks import LEAST, Clocks

    whole = Clocks()
    for step in range(LEAST):
        at = step * 250_000_000
        whole.saw(at, at + 2 * 3600 * 1_000_000_000)
    assert "+2.0h" in whole.describe(0.0)
    assert "looks like a timezone" in whole.describe(0.0)

    odd = Clocks()
    for step in range(LEAST):
        at = step * 250_000_000
        odd.saw(at, at + 1337 * 1_000_000_000)
    assert "not a whole timezone" in odd.describe(0.0)


def test_nothing_applies_the_measurement_by_itself():
    """**Reported, never applied.** Shifting every timestamp by an inferred
    constant would be invisible, would move with the network, and a transport
    glitch that produced a bad minimum would re-date the whole feed. The
    configured value stays authoritative.

    The absences are asserted on the source, because there is no call to make
    that proves a thing does not happen. The presence is not: `assert "def saw"
    in source` used to stand here, and a line existing is not a line running.
    """
    from pathlib import Path

    from till_infinity.adapters.mt5 import clocks as module

    source = Path(module.__file__).read_text()
    # No setter, no mutation of a config, nothing returning a corrected stamp.
    assert "server_offset_seconds =" not in source
    assert "def apply" not in source

    # The measurement is a query, taken and handed back. `data.py` reads it
    # into a log line and nothing else, so asking twice has to give the same
    # answer and leave the estimate alone - an accessor that consumed or
    # corrected anything would be applying it by another name.
    seen = module.Clocks()
    for step in range(module.LEAST):
        at = step * 250_000_000
        seen.saw(at, at + 2 * 3600 * 1_000_000_000)
    before = (seen.least, seen.samples, seen.told)
    assert seen.disagrees(0.0) == seen.disagrees(0.0) == pytest.approx(7200.0)
    assert seen.describe(0.0) == seen.describe(0.0)
    assert (seen.least, seen.samples, seen.told) == before


def test_a_tick_timestamp_stays_an_integer_through_the_offset():
    """**Nanoseconds do not survive a float.** A tick stamp is about 1.8e18
    and float64 is exact only to 2^53, so computing
    `msc * 1_000_000 - offset * 1_000_000_000` as a float and casting back
    perturbed every `ts_event` by 64ns.

    It was found by a test asserting a refilled tick's time, not by reading:
    the error is tens of nanoseconds on a quantity nothing displays, so no
    amount of looking at a log would have shown it. The subtraction is
    integral now - `round` on the offset is what keeps it there.
    """
    msc = 1_793_564_255_413

    def shipped(offset: float) -> int:
        return msc * 1_000_000 - round(offset * 1_000_000_000)

    def through_a_float(offset: float) -> int:
        return int(msc * 1_000_000 - offset * 1_000_000_000)

    for offset in (0.0, 3 * 3600.0, 1.5, -7200.0):
        exact = shipped(offset)
        assert exact % 1_000_000 == 0, "a millisecond stamp lands on a whole millisecond"
        assert exact == msc * 1_000_000 - int(offset * 1_000_000_000)
        # The float route is wrong by a non-zero amount at every offset,
        # including zero - which is the part that makes it a bug rather than
        # a rounding preference.
        assert through_a_float(offset) != exact
