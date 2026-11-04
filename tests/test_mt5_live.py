"""The round trip nothing else here covers: an order, a fill, and a close.

**Excluded from the default suite.** `pyproject.toml` carries
`addopts = "-ra -m 'not venue'"`, so these run only when selected:

    uv run pytest -m venue tests/test_mt5_live.py

Every other test in this repo stops at the adapter boundary.
`test_first_trade.py` drives a proposal to an order against `Venue("SIM")` in a
`BacktestEngine`; `test_mt5_clients.py` asserts route bodies against a
`FakeBridge`; `test_mt5_contract.py` parses replies recorded from a real
terminal. None of them sends anything to a venue, and on 2026-11-03 that gap
cost the desk a day:

* sixteen retired rule names put the node in a 27-restart loop,
* lowercase symbols returned `404 Symbol not found` on **2,605 of 2,609** log
  lines in ninety seconds,
* bar timestamps arrived as ISO strings and every bar poll raised,
* and a 5-minute subscription under M15 rules had six desks refusing.

**Not one of those stopped the node reporting itself healthy**, and no test in
the suite could have caught any of them, because a fake bridge returns the
shapes the code expects and a simulated venue accepts whatever it is sent.

## Why this is behind a marker and not just slow

It places a real order on the terminal the **live desk trades through**.
`lab-hosts-the-mt5-terminal` records that an outage there takes the desk down,
and `research/starving.md`'s rule is that research which degrades production is
not research that got a result faster. So the guards below are not politeness:

1. **No bridge configured, no test.** Skipped, not failed - a developer
   without the environment should get a pass, not a red suite.
2. **Demo accounts only, and it fails closed.** If the bridge will not say
   whether the account is a demo, the test refuses rather than assuming. A
   `trade_mode` this file does not recognise is not a demo.
3. **The smallest order the symbol allows**, and it is closed in the same
   test.

The order is a market order rather than a resting one on purpose: a pending
order that is never filled proves the route accepted a request, which the
`FakeBridge` tests already prove. A fill is the thing that has never been
asserted.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.venue

#: `ACCOUNT_TRADE_MODE_*`: **0 demo, 1 contest, 2 real.** Neither 0 nor 1 can
#: lose real money.
#:
#: **It has to be `trade_mode` and not `margin_mode`.** The first version of
#: this file read `margin_mode` as a fallback, and the live terminal reports
#: `trade_mode: 0` beside `margin_mode: 2` - so the guard would have refused a
#: genuine demo account, which is the safe direction but for the wrong reason,
#: and the same confusion inverted would pass a real one. `server` reads
#: `Deriv-Demo` and corroborates, but a server *name* is a string a broker
#: chooses and is not a guard.
DEMO_TRADE_MODES = frozenset({0, 1})

#: Where the account lives. **Not `/account/info`**, which does not exist: the
#: bridge publishes `/account/health`, `/account/last_error` and
#: `/account/retcodes` only, and the account is under `/terminal/`. The first
#: version of this file probed the wrong path, found nothing, and **skipped the
#: demo guard while still going on to place an order** - a fail-open guard in a
#: test that spends money.
ACCOUNT_ROUTE = "/terminal/account/info"


def bridge_url() -> str | None:
    url = os.environ.get("TRADING_MT5_URL")
    return url.rstrip("/") if url else None


def api_key() -> str | None:
    return os.environ.get("TRADING_MT5_API_KEY")


@pytest.fixture(scope="module")
def live():
    """A reachable bridge on a demo account, or a skip.

    The health probe comes first because every later assertion would otherwise
    fail for the same reason and say so four times.
    """
    httpx = pytest.importorskip("httpx")
    url = bridge_url()
    if not url:
        pytest.skip("TRADING_MT5_URL is not set: no bridge to talk to")

    headers = {"X-API-Key": api_key()} if api_key() else {}
    client = httpx.Client(base_url=f"{url}/api/v1", headers=headers, timeout=20.0)

    try:
        health = client.get("/terminal/ping")
    except Exception as exc:
        pytest.skip(f"the bridge at {url} did not answer: {type(exc).__name__}")
    if health.status_code != 200:
        pytest.skip(f"the bridge answered {health.status_code} on /terminal/ping")

    # **The demo check is in the fixture, so every test in this file inherits
    # it.** Putting it in one test left the order test free to run when the
    # check had merely been skipped, which is the opposite of failing closed.
    account = client.get(ACCOUNT_ROUTE)
    if account.status_code != 200:
        pytest.skip(
            f"{ACCOUNT_ROUTE} answered {account.status_code}, so whether this "
            f"account is a demo is unknown - refusing to trade on it"
        )
    mode = account.json().get("trade_mode")
    if mode is None:
        pytest.skip("the account reply carries no trade_mode - refusing to trade on it")
    if int(mode) not in DEMO_TRADE_MODES:
        pytest.skip(
            f"trade_mode {mode} is not a demo or contest account. Refusing "
            f"rather than placing an order with real money."
        )

    yield client
    client.close()


def test_the_account_this_runs_against_is_a_demo(live):
    """The guard, asserted rather than assumed.

    The fixture already refuses a non-demo account, so reaching this test means
    the check passed - and this states the number so a reader knows what was
    checked rather than trusting a skip they did not see.
    """
    found = live.get(ACCOUNT_ROUTE).json()

    assert int(found["trade_mode"]) in DEMO_TRADE_MODES
    assert found.get("trade_allowed") is True, (
        "the account is a demo and the terminal still will not trade: "
        "AutoTrading is off, or the broker has disabled it"
    )


def test_a_market_order_fills_and_can_be_closed(live):
    """**The assertion no other test in this repo makes.**

    Strategy code is not involved: `test_first_trade.py` already proves a
    proposal becomes an order, through an engine, with nothing stubbed. What is
    unproven is that the *venue* accepts what this adapter sends and reports a
    fill - and four faults on 2026-11-03 lived in exactly that gap while every
    test passed.

    The smallest volume the symbol allows, and it is closed before the test
    returns. If the close fails the test fails loudly, because a position left
    open by a test is worse than a red build.
    """
    symbol = os.environ.get("TRADING_MT5_TEST_SYMBOL", "EURUSD")

    info = live.get(f"/symbols/info/{symbol}")
    assert info.status_code == 200, (
        f"{symbol} returned {info.status_code}. Symbol names are the broker's "
        f"own spelling and are case-sensitive: `EURUSD` works where `eurusd` "
        f"returns 404, which is the fault that left the desk with quotes and "
        f"no trades."
    )
    spec = info.json()
    volume = float(spec.get("volume_min") or 0.0)
    assert volume > 0.0, f"{symbol} reports no minimum volume: {spec.get('volume_min')!r}"

    before = live.get("/positions/")
    assert before.status_code == 200, "cannot count positions, so cannot clean up after"
    opened_before = len(before.json() or [])

    # **`POST /trading/order`, not `/orders/`.** The first version of this
    # file posted to `/orders/`, which is a GET-only listing route and answered
    # **405 Method Not Allowed** against the live bridge - a third wrong route
    # in this file, found by running it rather than by reading it.
    #
    # And `sl` is mandatory: `bridge.order` records that
    # `MarketOrderRequest` declares it required, so a market order without one
    # is a 422. Zero is accepted and means "no stop at the venue", which is
    # what `EdgeEntry` sends before it attaches one from `on_order_filled`.
    placed = live.post(
        "/trading/order",
        json={
            "symbol": symbol,
            "order_type": "BUY",
            "volume": volume,
            "sl": 0.0,
            "comment": "till e2e",
        },
    )
    assert placed.status_code in (200, 201), (
        f"the venue refused the order: {placed.status_code} {placed.text[:200]}"
    )

    try:
        after = live.get("/positions/")
        assert after.status_code == 200
        positions = after.json() or []
        assert len(positions) > opened_before, (
            "the venue accepted the order and reported no new position. That is "
            "the shape of every fault found on 2026-11-03: a reply that looks "
            "like success over nothing having happened."
        )
        mine = [p for p in positions if str(p.get("symbol")) == symbol]
        assert mine, f"a position was opened and none of them is {symbol}"
        assert float(mine[-1].get("volume") or 0.0) > 0.0, "a position with no volume"
        assert float(mine[-1].get("price_open") or 0.0) > 0.0, (
            "filled at a price of zero, which is a parse fault rather than a fill"
        )
    finally:
        closed = live.post("/positions/close_all", json={"symbol": symbol})
        assert closed.status_code in (200, 201), (
            f"FAILED TO CLOSE: {closed.status_code} {closed.text[:200]}. A test "
            f"has left a position open on a real account - close it by hand."
        )
