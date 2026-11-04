"""Every bridge route the desk uses, against a real terminal, through the real client.

**Excluded from the default suite.** `pyproject.toml` carries
`addopts = "-ra -m 'not venue'"`, so these run only when selected:

    uv run pytest -m venue tests/test_mt5_live.py

## Why this drives `Bridge` and not `httpx`

The first version of this file posted hand-written JSON with a bare client. It
passed, and it could not have caught **any of the four route faults** that were
in `bridge.py` at the time, because it never called `bridge.py`:

* `POST /orders/` for a market order - a GET-only listing route, **405**;
* a market order with no `sl` - `MarketOrderRequest` declares it required, so
  every market order this adapter sent was a **422**;
* a limit sent to `/trading/order`, whose handler calls `send_market_order` and
  has no price parameter - accepted, and **filled at the market**;
* `GET /orders/pending`, which does not exist - a **404** that the old
  404-means-empty rule turned into "no resting orders".

Each lived in a body builder or a route string inside `Bridge`. A test that
writes its own body tests its own body. So every call below goes through the
method production calls, and the assertions are about what the **venue** did.

## What is covered, and what each one protects

| route | method | what breaks without it |
|---|---|---|
| `/terminal/ping` | `ping` | nothing reachable |
| `/terminal/account/info` | `account` | the demo guard itself |
| `/terminal/info` | `terminal_info` | **AutoTrading, which no other route reports** |
| `/symbols/` | `symbols` | instrument discovery |
| `/symbols/info/{s}` | `symbol_info` | sizing, digits, stop distance |
| `/symbols/rates/pos` | `bars` | **every bar poll raised on ISO timestamps** |
| `/symbols/ticks/{s}/range` | `ticks` | the bare route returns one quote repeatedly |
| `/trading/order` | `order` | market entries |
| `/orders/pending` | `order` with a price | **resting entries**, which place almost nothing |
| `GET /orders/` | `pending` | cancel verification, reconciliation |
| `PUT /orders/{t}` | `modify_order` | moving a resting order |
| `DELETE /orders/{t}` | `cancel` | an order left resting forever |
| `/positions/` | `positions` | reconciliation |
| `/positions/modify` | `modify` | break-even and trailing |
| `/positions/close` | `close_position` | **every exit**, and partial exits |
| `/history/deals` | `deals` | the record |

`/positions/close_all` is deliberately **not** here: production never calls it.
The previous version of this file closed with it, which meant the route the desk
actually exits through had never been exercised.

## Why this is behind a marker and not just slow

It places real orders on the terminal the **live desk trades through**.
`lab-hosts-the-mt5-terminal` records that an outage there takes the desk down.
So the guards are not politeness:

1. **No bridge configured, no test.** Skipped, not failed.
2. **Demo accounts only, and it fails closed.** If the bridge will not say
   whether the account is a demo, the test refuses. A `trade_mode` this file
   does not recognise is not a demo.
3. **The smallest order the symbol allows**, closed before the test returns.
4. **Only tickets this test opened are ever touched.** Every test snapshots the
   open tickets first and cleans up the difference, so a position belonging to
   the desk or to a person cannot be closed by a test run.
5. **Resting orders are placed 10% away from the market** so they cannot fill,
   and are cancelled in a `finally`.
"""

from __future__ import annotations

import asyncio
import os
import time

import pytest

pytestmark = pytest.mark.venue

#: `ACCOUNT_TRADE_MODE_*`: **0 demo, 1 contest, 2 real.** Neither 0 nor 1 can
#: lose real money.
#:
#: **It has to be `trade_mode` and not `margin_mode`.** The first version of
#: this file read `margin_mode` as a fallback, and the live terminal reports
#: `trade_mode: 0` beside `margin_mode: 2` - so the guard would have refused a
#: genuine demo, which is the safe direction but for the wrong reason, and the
#: same confusion inverted would pass a real one. `server` reads `Deriv-Demo`
#: and corroborates, but a server *name* is a string a broker chooses and is
#: not a guard.
DEMO_TRADE_MODES = frozenset({0, 1})

#: How far a resting order is placed from the market, as a fraction of price.
#: Far enough that no instrument here can reach it inside a test, and on the
#: side that makes it a **limit** - a BUY_LIMIT above the market is a stop
#: order and MT5 refuses it as an invalid price.
RESTING_AWAY = 0.10

#: A tag on everything this file places, so a human reading the terminal's
#: history can tell a test fill from a desk fill. `Bridge.order` truncates a
#: comment to 31 characters, which is MT5's own limit.
TAG = "till e2e"


def _env(name: str) -> str | None:
    found = os.environ.get(name)
    return found.strip() or None if found else None


@pytest.fixture
async def live():
    """An opened production `Bridge` on a demo account, or a skip.

    Function-scoped on purpose: the demo guard then runs for **every** test
    rather than once per module, so a session that reconnects to a different
    account mid-run cannot inherit a pass.
    """
    pytest.importorskip("httpx")
    url = _env("TRADING_MT5_URL")
    if not url:
        pytest.skip("TRADING_MT5_URL is not set: no bridge to talk to")

    from till_infinity.adapters.mt5.bridge import Bridge

    bridge = Bridge(url, _env("TRADING_MT5_API_KEY"), timeout=30.0)
    await bridge.open()
    try:
        try:
            awake = await bridge.ping()
        except Exception as exc:
            pytest.skip(f"the bridge at {url} did not answer: {type(exc).__name__}")
        if not awake:
            pytest.skip("/terminal/ping answered falsey")

        try:
            account = await bridge.account()
        except Exception as exc:
            pytest.skip(f"the account is unreadable ({type(exc).__name__}) - refusing to trade")
        mode = account.get("trade_mode")
        if mode is None:
            pytest.skip("the account reply carries no trade_mode - refusing to trade on it")
        if int(mode) not in DEMO_TRADE_MODES:
            pytest.skip(
                f"trade_mode {mode} is not a demo or contest account. Refusing "
                f"rather than placing an order with real money."
            )
        yield bridge
    finally:
        await bridge.close()


@pytest.fixture
async def tradeable(live):
    """Skip, rather than fail, when the terminal's AutoTrading is off.

    Without this, one toggle fails **five** tests with five tracebacks about
    five different routes, and a reader has to notice that `10027` is the same
    word in all of them. `test_the_terminal_will_accept_an_order` fails loudly
    and alone; everything that needs a fill then skips with the cause named.

    It also stops a **vacuous pass**:
    `test_the_venue_refuses_an_impossible_order` catches `BridgeError` and
    treats it as the venue refusing a million lots. With AutoTrading off every
    order raises `BridgeError`, so that test would have passed while proving
    nothing about volume at all - which is the shape `CLAUDE.md` calls worse
    than no test.
    """
    if not await live.can_trade():
        pytest.skip(
            "terminal_info().trade_allowed is false: AutoTrading is off on the "
            "terminal, so every order returns 10027. See "
            "test_the_terminal_will_accept_an_order."
        )
    return live


@pytest.fixture
async def spec(live):
    """The test symbol's contract, skipped if it is not tradeable right now.

    A closed market is a skip and not a failure: the route is fine and the
    session is shut, and a red suite on a Sunday teaches a reader to ignore it.
    """
    symbol = os.environ.get("TRADING_MT5_TEST_SYMBOL", "EURUSD")
    found = await live.symbol_info(symbol)
    if not found:
        pytest.skip(
            f"{symbol} returned nothing. Symbol names are the broker's own "
            f"spelling and are case-sensitive: `EURUSD` works where `eurusd` "
            f"404s, which is the fault that left the desk with quotes and no trades."
        )
    found["symbol"] = symbol
    volume = float(found.get("volume_min") or 0.0)
    if volume <= 0.0:
        pytest.skip(f"{symbol} reports no minimum volume: {found.get('volume_min')!r}")
    return found


async def _price(live, spec) -> float:
    """A current price for `spec`'s symbol: the quote, else the last bar's close."""
    for key in ("ask", "bid", "last"):
        value = spec.get(key)
        if value and float(value) > 0.0:
            return float(value)
    bars = await live.bars(spec["symbol"], "M1", 2, start=1)
    if bars and float(bars[-1].get("close") or 0.0) > 0.0:
        return float(bars[-1]["close"])
    pytest.skip(f"no price available for {spec['symbol']}: the session may be closed")


async def _tickets(live) -> set[int]:
    return {int(p["ticket"]) for p in await live.positions() if p.get("ticket") is not None}


async def _resting(live) -> set[int]:
    return {int(o["ticket"]) for o in await live.pending() if o.get("ticket") is not None}


async def _mine(live, before: set[int], *, what: str = "position") -> list[dict]:
    """The rows this test opened, waited for briefly.

    A fill is acknowledged before it is in the book on some servers, so a
    single read can race it. This is why the assertion is not "a position
    exists" but "a position **this test opened** exists".
    """
    rows = await live.positions() if what == "position" else await live.pending()
    for _ in range(10):
        mine = [r for r in rows if r.get("ticket") is not None and int(r["ticket"]) not in before]
        if mine:
            return mine
        await asyncio.sleep(0.3)
        rows = await live.positions() if what == "position" else await live.pending()
    return []


async def _flatten(live, before: set[int]) -> None:
    """Close every position this test opened, and nothing else.

    Fails loudly: a position left open by a test is worse than a red build.
    """
    stuck = []
    for row in await live.positions():
        ticket = row.get("ticket")
        if ticket is None or int(ticket) in before:
            continue
        try:
            await live.close_position(int(ticket))
        except Exception as exc:
            stuck.append(f"{ticket}: {type(exc).__name__} {exc}")
    assert not stuck, (
        f"FAILED TO CLOSE {len(stuck)} position(s) this test opened: {stuck}. Close them by hand."
    )


async def _withdraw(live, before: set[int]) -> None:
    """Cancel every resting order this test placed, and nothing else."""
    stuck = []
    for row in await live.pending():
        ticket = row.get("ticket")
        if ticket is None or int(ticket) in before:
            continue
        try:
            await live.cancel(int(ticket))
        except Exception as exc:
            stuck.append(f"{ticket}: {type(exc).__name__} {exc}")
    assert not stuck, f"FAILED TO CANCEL {len(stuck)} order(s) this test placed: {stuck}."


# ──────────────────────────── the guard ────────────────────────────


async def test_the_account_this_runs_against_is_a_demo(live):
    """The guard, asserted rather than assumed.

    The fixture already refuses a non-demo account, so reaching this test means
    the check passed - and this states the number, so a reader knows what was
    checked rather than trusting a skip they did not see.
    """
    found = await live.account()

    assert int(found["trade_mode"]) in DEMO_TRADE_MODES
    # **This is the account's flag, not the terminal's**, and they are
    # different facts with the same name. This one says the broker permits
    # trading on the account; it was `true` on 2026-11-04 while the terminal
    # refused every order. Asserting it is therefore **not** a check that
    # trading works - that is the next test.
    assert found.get("trade_allowed") is True, (
        "the broker has disabled trading on this account, which is a different "
        "thing from AutoTrading being off"
    )


async def test_the_terminal_will_accept_an_order(live):
    """**The check that was missing, and the reason the desk looked healthy.**

    MT5 has two flags spelled `trade_allowed`. `account_info().trade_allowed`
    is the broker's permission; `terminal_info().trade_allowed` is the
    AutoTrading button, and an order is checked against the **second**. With it
    off every submission comes back `10027, Autotrading disabled by client
    terminal` - and nothing in this repo read that route before this test.

    Measured on 2026-11-04, with the desk unable to place a single order:

        GET /terminal/info          trade_allowed  false   <- the truth
        GET /terminal/account/info  trade_allowed  true
        GET /account/health         {"status": "healthy", "mt5": "connected"}
        GET /terminal/ping          200

    Four signals, three of them green, and `trade_allowed` appears **zero
    times in the bridge's OpenAPI schema** - both routes return undeclared
    dicts, so the field cannot be found from the spec, only by calling it.

    This fails rather than skips. A terminal that will not trade is an
    ordinary weekend state, and that is exactly why it must be loud: a desk
    that cannot tell a weekend from a toggle someone left off is a desk that
    discovers it from a missing week of fills.
    """
    found = await live.terminal_info()

    assert found, "/terminal/info returned nothing: the route the AutoTrading flag lives on"
    assert found.get("connected") is True, (
        f"the terminal is not connected to the broker: {found.get('connected')!r}"
    )
    assert found.get("trade_allowed") is True, (
        f"AutoTrading is OFF on the terminal (build {found.get('build')}), so "
        f"every order the desk sends returns 10027 and nothing it trades can "
        f"fill. `/account/health` and `/terminal/ping` both read healthy "
        f"anyway. This is fixed on the terminal, not in this repo: the "
        f"AutoTrading button, which is what the VNC interface on 6901 is for."
    )


# ──────────────────────────── the data paths ────────────────────────────


async def test_the_symbol_list_comes_back_populated(live):
    """`/symbols/`, which is how an instrument is discovered at all.

    Asserted as a count rather than for a specific name, because the universe
    is the broker's and a missing single name is a configuration question.
    """
    found = await live.symbols()

    assert len(found) > 1, f"the terminal offers {len(found)} symbols, which is not a universe"
    assert all(isinstance(s, str) and s for s in found)


async def test_bars_parse_through_the_production_parser(live, spec):
    """**The fault that raised on every bar poll**, asserted live.

    `test_mt5_contract.py` parses a reply *recorded* from this terminal, which
    proves the parser handles the shape seen once. This proves the terminal is
    still sending that shape - the bridge runs MT5's rows through
    `pandas.to_datetime`, so `time` arrives as an ISO string, and the bar path
    used to call `int()` on it directly and raise on every poll.

    `_bar_seconds` is the production function. A plausible epoch is the
    assertion that distinguishes a parse from a silent zero: a wrong parse
    lands in 1970 and a bar at 1970 is not an exception anywhere.
    """
    from till_infinity.adapters.mt5.data import _bar_seconds

    rows = await live.bars(spec["symbol"], "M1", 5, start=1)
    if not rows:
        pytest.skip(f"no M1 bars for {spec['symbol']}: the session may be closed")

    now = time.time()
    seconds = [_bar_seconds(row) for row in rows]
    for row, opened in zip(rows, seconds, strict=True):
        assert 1_000_000_000 < opened < now + 86_400, (
            f"bar open time parsed to {opened}, which is not a plausible epoch. The row was {row!r}"
        )
        assert float(row.get("open") or 0.0) > 0.0, f"a bar with no open: {row!r}"
        assert float(row["high"]) >= float(row["low"]), f"high below low: {row!r}"
        assert row.get("tick_volume") is not None or row.get("real_volume") is not None, (
            f"neither tick_volume nor real_volume - and it is **not** `volume`, "
            f"which is the name the first adapter looked for: {row!r}"
        )

    assert seconds == sorted(seconds), f"bars came back out of order: {seconds}"
    assert len(set(seconds)) == len(seconds), f"a repeated bar timestamp: {seconds}"


async def test_a_tick_range_returns_distinct_ticks(live, spec):
    """**`/range`, not the bare tick route**, which is a different fault shape.

    `/symbols/ticks/{s}` is `get_symbol_info_tick` - the latest single tick -
    and it ignores `date_from` and `date_to`, so a backfill built on it
    returned the current quote over and over: a market that never moved, wrong
    in a way no exception reports. The assertion is therefore **distinct
    timestamps**, which is the thing that was wrong, not "some ticks came back".
    """
    from till_infinity.adapters.mt5.data import _milliseconds

    end = int(time.time())
    rows = await live.ticks(spec["symbol"], end - 3600, end)
    if len(rows) < 2:
        pytest.skip(f"{len(rows)} ticks in the last hour for {spec['symbol']}: market closed?")

    stamps = [_milliseconds(row) for row in rows]
    assert all(s is not None for s in stamps), (
        f"a tick whose time did not parse. The bridge sends ISO strings through "
        f"`pandas.to_datetime`: {rows[:2]!r}"
    )
    assert len(set(stamps)) > 1, (
        f"{len(rows)} ticks and {len(set(stamps))} distinct timestamp - this is "
        f"the bare-route fault: one quote repeated over the whole range"
    )
    assert min(stamps) >= (end - 3600 - 120) * 1000, (
        f"a tick older than the range asked for: {min(stamps)} vs {(end - 3600) * 1000}"
    )
    assert any(float(r.get("bid") or 0.0) > 0.0 for r in rows), "no bid on any tick"


async def test_the_deal_history_route_accepts_what_the_adapter_sends(live):
    """`/history/deals`, which is the only record of what actually filled.

    **The parameters are sent as bare ints** while the tick route had to send
    ISO strings, because that route types both as `datetime`. If this route
    does the same, the call is a 422 and the desk's record is empty - so what
    is asserted is that the call *succeeds*, not that it returns rows. An
    account with no deals in the window is a legitimate empty.
    """
    from till_infinity.adapters.mt5.bridge import _seconds

    end = int(time.time())
    day = await live.deals(end - 86_400, end)
    month = await live.deals(end - 30 * 86_400, end)

    assert isinstance(day, list), f"the deal history is not a list: {day!r}"
    assert isinstance(month, list)

    # **The route ignores both parameters.** Measured 2026-11-04: an hour, 7
    # days and 30 days all returned the same 4,014 rows spanning 30 days, as
    # bare ints and as ISO strings alike. `Bridge.deals` therefore applies the
    # window itself, and this is what proves it still does - without it,
    # `generate_fill_reports` asks for a day and is handed a month.
    for row in day:
        when = _seconds(row.get("time"))
        if when is None:
            continue
        assert end - 86_400 <= when <= end, (
            f"a deal at {when} came back for a window of "
            f"[{end - 86_400}, {end}] - the route's range is ignored and the "
            f"filter in `Bridge.deals` is what keeps the window true"
        )
    assert len(day) <= len(month), (
        f"a day holds {len(day)} deals and a month {len(month)}: the window is "
        f"not being applied in the direction it should be"
    )


# ──────────────────────────── the order paths ────────────────────────────


@pytest.mark.parametrize("side", ["BUY", "SELL"])
async def test_a_market_order_fills_and_closes_through_the_position_route(
    live, spec, tradeable, side
):
    """**Both sides**, closed through `/positions/close`.

    Only BUY was ever tested, and the close went through `/positions/close_all`
    - a route production does not call. So the route every exit on this desk
    actually uses had never been exercised against a venue, and a short entry
    had never been placed at all.
    """
    before = await _tickets(live)
    volume = float(spec["volume_min"])

    await live.order(
        {
            "symbol": spec["symbol"],
            "order_type": side,
            "volume": volume,
            "sl": 0.0,
            "comment": f"{TAG} {side.lower()}",
        }
    )
    try:
        mine = await _mine(live, before)
        assert mine, (
            f"the venue accepted a market {side} and reported no new position. "
            f"That is the shape of every fault found on 2026-11-03: a reply "
            f"that looks like success over nothing having happened."
        )
        position = mine[-1]
        assert str(position.get("symbol")) == spec["symbol"]
        assert float(position.get("volume") or 0.0) == pytest.approx(volume, rel=1e-6)
        assert float(position.get("price_open") or 0.0) > 0.0, (
            "filled at a price of zero, which is a parse fault rather than a fill"
        )
        # MT5 position types: 0 is a long, 1 is a short. A SELL that opens a
        # long is the whole reason both sides are tested.
        kind = position.get("type")
        if kind is not None:
            assert int(kind) == (0 if side == "BUY" else 1), (
                f"a market {side} opened a position of type {kind}"
            )
    finally:
        await _flatten(live, before)

    assert await _tickets(live) == before, "the close did not remove the position"


async def test_a_partial_close_leaves_the_remainder_open(live, spec, tradeable):
    """`/positions/close` with a volume - the path `manage.partial` needs.

    `scale_out_at` has had **no caller for the life of the desk**, so this is
    the first time a partial exit has been sent anywhere. It is a different
    request from a full close: a volume short of the position's own closes
    part of it, and a venue that ignores the field would close the lot and
    look like a success.
    """
    volume_min = float(spec["volume_min"])
    step = float(spec.get("volume_step") or volume_min)
    whole = volume_min * 2.0
    if whole > float(spec.get("volume_max") or whole):
        pytest.skip(f"{spec['symbol']} cannot take {whole}: volume_max is {spec.get('volume_max')}")
    if step > volume_min + 1e-12:
        pytest.skip(f"volume_step {step} is coarser than volume_min {volume_min}: no partial")

    before = await _tickets(live)
    await live.order(
        {
            "symbol": spec["symbol"],
            "order_type": "BUY",
            "volume": whole,
            "sl": 0.0,
            "comment": f"{TAG} partial",
        }
    )
    try:
        mine = await _mine(live, before)
        assert mine, "no position to close part of"
        ticket = int(mine[-1]["ticket"])
        assert float(mine[-1]["volume"]) == pytest.approx(whole, rel=1e-6)

        await live.close_position(ticket, volume_min)

        left = None
        for _ in range(10):
            rows = {int(p["ticket"]): p for p in await live.positions() if p.get("ticket")}
            # A partial close keeps the ticket on MT5. A venue that issues a
            # new one is handled by falling back to whatever this test owns.
            if ticket in rows:
                left = rows[ticket]
            else:
                owned = [p for p in rows.values() if int(p["ticket"]) not in before]
                left = owned[-1] if owned else None
            if left is not None and float(left["volume"]) < whole - 1e-9:
                break
            await asyncio.sleep(0.3)

        assert left is not None, (
            f"the partial close removed the position entirely. A volume of "
            f"{volume_min} against a position of {whole} must leave "
            f"{volume_min} open, and a venue that ignores the volume field "
            f"closes the lot and reports success."
        )
        assert float(left["volume"]) == pytest.approx(volume_min, rel=1e-6), (
            f"closed {volume_min} of {whole} and {left['volume']} is left"
        )
    finally:
        await _flatten(live, before)


async def test_a_stop_and_target_can_be_set_on_an_open_position(live, spec, tradeable):
    """`/positions/modify` - what break-even and trailing both call.

    `advance` moves a stop on a live position every bar it is armed. If this
    route silently does nothing, a break-even that "fired" never moved
    anything, and the journal would say it did: the desk reads its own intent
    and not the venue's state. So the assertion is read back **from the
    venue**.

    The stop is placed 10% away so no `trade_stops_level` can refuse it for
    being too close, which is a rejection about distance and not about the route.
    """
    before = await _tickets(live)
    digits = int(spec.get("digits") or 5)

    await live.order(
        {
            "symbol": spec["symbol"],
            "order_type": "BUY",
            "volume": float(spec["volume_min"]),
            "sl": 0.0,
            "comment": f"{TAG} modify",
        }
    )
    try:
        mine = await _mine(live, before)
        assert mine, "no position to modify"
        position = mine[-1]
        ticket = int(position["ticket"])
        opened = float(position["price_open"])
        stop = round(opened * (1.0 - RESTING_AWAY), digits)
        target = round(opened * (1.0 + RESTING_AWAY), digits)

        await live.modify(ticket, stop, target)

        landed = None
        for _ in range(10):
            rows = {int(p["ticket"]): p for p in await live.positions() if p.get("ticket")}
            found = rows.get(ticket)
            if found and float(found.get("sl") or 0.0) > 0.0:
                landed = found
                break
            await asyncio.sleep(0.3)

        assert landed is not None, (
            f"the modify was accepted and the position still reports no stop. "
            f"Asked for sl {stop} tp {target} on ticket {ticket}."
        )
        assert float(landed["sl"]) == pytest.approx(stop, abs=10.0 ** -(digits - 1)), (
            f"asked for a stop at {stop}, the venue holds {landed.get('sl')}"
        )
        assert float(landed.get("tp") or 0.0) == pytest.approx(target, abs=10.0 ** -(digits - 1)), (
            f"asked for a target at {target}, the venue holds {landed.get('tp')}"
        )
    finally:
        await _flatten(live, before)


async def test_a_resting_limit_rests_and_can_be_moved_and_cancelled(live, spec, tradeable):
    """**The whole resting path**, which the leaf sweep says places almost nothing.

    `arrival` placed **nothing** and `resting` placed **2 positions** over a
    whole sweep. A rule that never fires and a route that never works look
    identical from a backtest, and this is the test that tells them apart -
    against a venue, through `Bridge.order`, which picks `/orders/pending`
    purely from the presence of a `price`.

    Three routes in one test because they are one lifecycle and each needs the
    previous: placed (`POST /orders/pending`), listed (`GET /orders/`, which
    used to 404 into an empty list), moved (`PUT /orders/{t}`, not
    `/positions/modify` - an order is not a position) and cancelled
    (`DELETE /orders/{t}`).

    **It cannot fill:** a BUY_LIMIT 10% below the market is unreachable inside
    a test, and that is also the side that makes it a limit rather than a stop.
    """
    before = await _resting(live)
    held = await _tickets(live)
    digits = int(spec.get("digits") or 5)
    market = await _price(live, spec)
    price = round(market * (1.0 - RESTING_AWAY), digits)

    await live.order(
        {
            "symbol": spec["symbol"],
            "order_type": "BUY",
            "volume": float(spec["volume_min"]),
            "sl": 0.0,
            "price": price,
            "comment": f"{TAG} resting",
        }
    )
    try:
        mine = await _mine(live, before, what="pending")
        assert mine, (
            f"a limit at {price} was accepted and nothing is resting. Either "
            f"`/orders/pending` did not place it, or `GET /orders/` cannot see "
            f"it - and the second is the fault that made cancel verification "
            f"and reconciliation both read an empty list as fact."
        )
        order = mine[-1]
        ticket = int(order["ticket"])
        assert str(order.get("symbol")) == spec["symbol"]
        resting_at = float(order.get("price_open") or order.get("price") or 0.0)
        assert resting_at == pytest.approx(price, abs=10.0 ** -(digits - 1)), (
            f"placed a limit at {price} and the venue holds it at {resting_at}. A "
            f"limit that arrives at the market price is the "
            f"`/trading/order` fault: accepted, and filled at the market."
        )
        # MT5 pending types: 2 BUY_LIMIT, 3 SELL_LIMIT, 4 BUY_STOP, 5 SELL_STOP.
        kind = order.get("type")
        if kind is not None:
            assert int(kind) == 2, (
                f"a BUY below the market should rest as a BUY_LIMIT (2), the venue calls it {kind}"
            )

        moved = round(market * (1.0 - RESTING_AWAY * 1.5), digits)
        await live.modify_order(ticket, moved)

        after = None
        for _ in range(10):
            rows = {int(o["ticket"]): o for o in await live.pending() if o.get("ticket")}
            found = rows.get(ticket)
            if found:
                at = float(found.get("price_open") or found.get("price") or 0.0)
                if abs(at - moved) < abs(at - price):
                    after = found
                    break
            await asyncio.sleep(0.3)
        assert after is not None, (
            f"`PUT /orders/{ticket}` was accepted and the order did not move "
            f"to {moved}. `/positions/modify` posts a limit price as a target "
            f"and leaves the order where it was, which is why this is a "
            f"separate call."
        )

        await live.cancel(ticket)
        for _ in range(10):
            if ticket not in await _resting(live):
                break
            await asyncio.sleep(0.3)
        assert ticket not in await _resting(live), (
            f"`DELETE /orders/{ticket}` was accepted and the order is still "
            f"resting. An uncancellable order is a position the desk does not "
            f"know it has."
        )
    finally:
        await _withdraw(live, before)
        # A limit 10% away cannot fill, but if the venue ever treated it as a
        # market order - the `/trading/order` fault - that is a live position.
        await _flatten(live, held)


async def test_the_venue_refuses_an_impossible_order(live, spec, tradeable):
    """The **rejection** path, which nothing here has ever asserted.

    Every other test says what happens when the venue agrees. This says a
    refusal is visible, because the failure mode on this bridge is a refusal
    that reads as success: a 404 used to become `{}`, which read as retcode 0,
    which read as success. A volume of a million lots cannot be filled and
    cannot be mistaken for anything else.

    Either an exception or a non-10009 retcode is a pass. Which one it is
    depends on whether the bridge maps the refusal to an HTTP status, and that
    is the bridge's choice rather than this test's requirement.
    """
    from till_infinity.adapters.mt5.bridge import BridgeError

    before = await _tickets(live)
    try:
        reply: dict | None = None
        refusal = ""
        try:
            reply = await live.order(
                {
                    "symbol": spec["symbol"],
                    "order_type": "BUY",
                    "volume": 1_000_000.0,
                    "sl": 0.0,
                    "comment": f"{TAG} refuse",
                }
            )
        except BridgeError as exc:
            refusal = str(exc)

        if refusal:
            # **Refused for the right reason.** `10027` is AutoTrading, which
            # refuses *everything* and would make this test pass while saying
            # nothing about volume. The `tradeable` fixture should have skipped
            # this test already; this is the assertion that says so, and it is
            # outside the `except` because a bare `pytest.raises` cannot
            # express "an exception **or** a retcode".
            for wrong, why in (
                ("10027", "AutoTrading is off"),
                # **10030 made this test pass for the wrong reason once.** With
                # `type_filling` hardcoded to a mode the symbol does not
                # accept, every order was refused `Unsupported filling mode` -
                # so this test went green while proving nothing about volume,
                # which is exactly the vacuous pass `CLAUDE.md` forbids.
                ("10030", "the filling mode is unsupported"),
            ):
                assert wrong not in refusal, (
                    f"the venue refused this order because {why}, not because a "
                    f"million lots is impossible: {refusal}"
                )
            return
        assert reply is not None

        retcode = reply.get("retcode")
        assert retcode is not None, (
            f"a million-lot order was neither refused nor given a retcode. The "
            f"reply was {reply!r} - and a reply with no retcode is the shape "
            f"that read as success."
        )
        assert int(retcode) != 10009, (
            f"the venue reports DONE (10009) on a million lots of "
            f"{spec['symbol']}, which means the retcode is not the fill's"
        )
    finally:
        await _flatten(live, before)
