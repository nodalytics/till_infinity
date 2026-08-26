"""MT5 over HTTP, via a FastAPI bridge running the terminal under Wine.

This is the backend that makes Linux work. The bridge runs the Windows
terminal under Wine in a container and puts FastAPI in front of it, so the only
Windows-only thing in the system is the container, and this process talks to it
over a socket like anything else.

## Two bridges, one client

There are two of these in the wild and they are not the same API:

* **`metatrader-terminal`** — the published one, and the more complete;
* **`mt5-api`** — an earlier variant, which may only exist locally.

They share the `/api/v1` prefix, the `X-API-Key` header, `POST /trading/order`
and `POST /positions/close`, and they differ in exactly the places that matter
here. Rather than pick one and be broken against the other, this client
**probes what it is talking to** at connect and adapts. Three differences:

| | `metatrader-terminal` | `mt5-api` |
|---|---|---|
| account | `GET /terminal/account/info` | none — falls back to `TRADING_ACCOUNT_EQUITY` |
| symbol list | `GET /symbols/` returns every name | none — suffixes have to be probed |
| symbol spec | `GET /symbols/info/{symbol}` | `GET /symbols/{symbol}` |

That last one is not cosmetic. `metatrader-terminal` has **no** bare
`/symbols/{symbol}` route, so a client hard-wired to it 404s on every symbol
and concludes the broker carries none of them — which is a total failure that
looks exactly like a broker naming problem. And on `mt5-api` the `info` route
is the one that cannot be used, because its response model narrows the payload
to name, path, volume limits and `price_digits`, dropping `trade_tick_value`
and `trade_tick_size` — precisely what position sizing needs. Each project's
working route is the other's broken one, so both are tried and the answer is
judged by whether it actually carries a tick value.

Where the symbol list exists it is used, and that is the better path by a
distance: the account's suffix is *found* rather than guessed from a list of
twenty-odd that cannot be complete. See `symbols.resolve`.

**The magic filter is applied here as well as there.** The bridge passes magic
to `positions_get`, which does not take that keyword — it filters by symbol,
group or ticket. Rather than depend on that being fixed, every position is
checked against our magic locally. The cost is a few dictionaries; the failure
it prevents is this system closing somebody's hand-placed trade.
"""

from __future__ import annotations

from typing import Any, ClassVar

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from ..logging import get_logger
from .broker import Broker, NotConnectedError, RejectedError, TransientError
from .config import Settings
from .models import Account, Order, OrderResult, Position, Side, SymbolSpec, Tick

log = get_logger(__name__)

#: The terminal's "request completed" code. Everything else is a rejection.
TRADE_DONE = 10009


class HttpBroker(Broker):
    """One account, reached through the bridge."""

    name: ClassVar[str] = "mt5-http"

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self._client: httpx.AsyncClient | None = None
        self._warned_equity = False
        #: The spec route this bridge answers on, learned on the first symbol
        #: asked for and reused. Both are tried until one works.
        self._spec_route = ""
        #: Whether this bridge can list its symbols. None until asked.
        self._can_list: bool | None = None

    # ------------------------------------------------------------- lifecycle

    async def connect(self) -> Account:
        if not self.settings.url:
            raise NotConnectedError("TRADING_MT5_URL is not set")
        headers = {"Accept": "application/json"}
        if self.settings.api_key:
            headers["X-API-Key"] = self.settings.api_key
        self._client = httpx.AsyncClient(
            base_url=self.settings.base_url(),
            headers=headers,
            timeout=self.settings.timeout,
        )
        if not await self.healthy():
            await self.close()
            raise NotConnectedError(f"the bridge at {self.settings.url} has no terminal attached")
        return await self.account()

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def healthy(self) -> bool:
        """Whichever health route this bridge has. Never raises.

        `mt5-api` answers `/account/health` with a status field;
        `metatrader-terminal` answers `/terminal/ping`. A client that knew only
        one would report a healthy bridge as down and refuse to start.
        """
        for path in ("/account/health", "/terminal/ping"):
            try:
                body = await self._get(path)
            except Exception:
                continue
            if not isinstance(body, dict):
                continue
            status = str(body.get("status", "")).lower()
            # A ping with no status field is itself the answer.
            if status in ("healthy", "ok", "") or body.get("ping"):
                return status not in ("unhealthy", "disconnected")
        log.warning("trading: no health route answered on %s", self.settings.url)
        return False

    # ----------------------------------------------------------------- reads

    async def account(self) -> Account:
        raw: dict[str, Any] = {}
        for path in ("/terminal/account/info", "/account/info"):
            try:
                found = await self._get(path)
            except Exception:
                continue
            if isinstance(found, dict) and found.get("equity") is not None:
                raw = found
                break
        if raw.get("equity") is None:
            if not self._warned_equity:
                log.warning(
                    "trading: the bridge exposes no account endpoint; sizing off "
                    "TRADING_ACCOUNT_EQUITY=%.2f",
                    self.settings.account_equity,
                )
                self._warned_equity = True
            equity = self.settings.account_equity
            return Account(currency="USD", balance=equity, equity=equity, margin_free=equity)
        return Account(
            login=int(raw.get("login") or 0),
            currency=str(raw.get("currency") or "USD"),
            balance=float(raw.get("balance") or 0.0),
            equity=float(raw.get("equity") or 0.0),
            margin_free=float(raw.get("margin_free") or 0.0),
            leverage=int(raw.get("leverage") or 0),
        )

    async def catalogue(self) -> list[str] | None:
        """Every symbol the bridge will list, or None if it does not list them.

        `metatrader-terminal` answers `GET /symbols/` with the whole set, which
        lets resolution scan instead of guessing suffixes. `mt5-api` has no
        such route, and None is the honest answer there.
        """
        if self._can_list is False:
            return None
        try:
            found = await self._get("/symbols/")
        except Exception:
            self._can_list = False
            return None
        names = (
            [str(item) for item in found if isinstance(item, str)]
            if isinstance(found, list)
            else []
        )
        self._can_list = bool(names)
        return names or None

    async def spec(self, symbol: str) -> SymbolSpec | None:
        """The instrument's trading rules, from whichever route this bridge has.

        Both are tried, and the answer is accepted only when it carries a tick
        value — `mt5-api`'s `info` route returns a 200 with a narrowed payload
        rather than an error, so status alone cannot tell a usable spec from an
        unusable one. Sizing off a spec with no tick value is refused later
        anyway; discovering it here means the *other* route still gets a turn.
        """
        routes = (
            [self._spec_route]
            if self._spec_route
            else [
                f"/symbols/{symbol}",
                f"/symbols/info/{symbol}",
            ]
        )
        narrowed: dict[str, Any] | None = None
        for route in routes:
            path = route.format(symbol=symbol) if "{symbol}" in route else route
            try:
                raw = await self._get(path)
            except RejectedError:
                continue  # 404 — this route, or this symbol. The next one says which.
            except Exception:
                continue
            if not isinstance(raw, dict) or not raw.get("name"):
                continue
            if raw.get("trade_tick_value") is None:
                narrowed = raw  # usable only if nothing better answers
                continue
            self._spec_route = route.replace(symbol, "{symbol}")
            return _spec_from(raw, symbol)
        if narrowed is not None:
            log.warning(
                "trading: %s came back without a tick value, so it cannot be sized",
                symbol,
            )
            return _spec_from(narrowed, symbol)
        return None

    async def quote(self, symbol: str) -> Tick | None:
        try:
            raw = await self._get(f"/symbols/ticks/{symbol}")
        except RejectedError:
            return None
        bid, ask = float(raw.get("bid") or 0.0), float(raw.get("ask") or 0.0)
        if not bid or not ask:
            return None
        return Tick(symbol=symbol, bid=bid, ask=ask, time=float(raw.get("time") or 0.0))

    async def positions(self) -> list[Position]:
        raw = await self._get("/positions/", params={"magic": self.settings.magic})
        rows = raw if isinstance(raw, list) else raw.get("positions", [])
        return [_position_from(row) for row in rows if _ours(row, self.settings.magic)]

    # ---------------------------------------------------------------- writes

    async def send(self, order: Order) -> OrderResult:
        body = {
            "symbol": order.symbol,
            "volume": order.volume,
            "order_type": "BUY" if order.side is Side.BUY else "SELL",
            # Required by the bridge's request model, and rightly so: a scalp
            # without a stop is not a scalp.
            "sl": order.stop,
            "tp": order.target or None,
            "deviation": order.deviation,
            "comment": order.comment[:31],
            "magic": order.magic,
            "type_filling": self.settings.filling,
        }
        raw = await self._post("/trading/order", json=body)
        trade = raw.get("trade") or {}
        ticket = trade.get("transaction_broker_id") or 0
        return OrderResult(
            ok=bool(raw.get("success")),
            # The bridge stores the *order* ticket as a string. For a market
            # fill it is the position ticket too, and the service reconciles
            # against `positions()` regardless rather than trusting this.
            ticket=int(ticket) if str(ticket).isdigit() else 0,
            price=float(trade.get("entry_price") or 0.0),
            volume=float(trade.get("order_volume") or order.volume),
            comment=str(trade.get("closing_reason") or ""),
        )

    async def close_position(self, ticket: int, volume: float = 0.0) -> OrderResult:
        raw = await self._post("/positions/close", params={"ticket": ticket})
        result = raw.get("result") or {}
        return OrderResult(
            ok=bool(raw.get("success")),
            ticket=ticket,
            price=float(result.get("price") or 0.0),
            volume=float(result.get("volume") or volume),
            retcode=int(result.get("retcode") or 0),
            comment=str(result.get("comment") or ""),
        )

    # ---------------------------------------------------------------- inside

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        if self._client is None:
            raise NotConnectedError("the bridge client is not open")
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(max(1, self.settings.retries)),
            wait=wait_exponential_jitter(initial=0.5, max=8.0),
            retry=retry_if_exception_type(TransientError),
            reraise=True,
        ):
            with attempt:
                try:
                    response = await self._client.request(method, path, **kwargs)
                except httpx.TimeoutException as exc:
                    raise TransientError(f"{method} {path} timed out") from exc
                except httpx.HTTPError as exc:
                    raise TransientError(f"{method} {path}: {exc}") from exc
                return _body(response, method, path)
        raise AssertionError("unreachable")

    async def _get(self, path: str, **kwargs: Any) -> Any:
        return await self._request("GET", path, **kwargs)

    async def _post(self, path: str, **kwargs: Any) -> Any:
        return await self._request("POST", path, **kwargs)


def _body(response: httpx.Response, method: str, path: str) -> Any:
    """Turn a response into data, or into the right kind of error.

    A 5xx is transient and a 4xx is not: the bridge answering 400 "Invalid
    volume" to the same order body a second time is certain, and retrying it
    only delays the log line that says so.
    """
    if response.status_code >= 500:
        raise TransientError(f"{method} {path}: {response.status_code}")
    if response.status_code >= 400:
        detail = ""
        try:
            detail = str(response.json().get("detail", ""))
        except Exception:  # an error page that is not JSON is still an error
            detail = response.text[:200]
        raise RejectedError(f"{method} {path}: {response.status_code} {detail}")
    try:
        return response.json()
    except Exception as exc:
        raise TransientError(f"{method} {path}: response was not JSON") from exc


def _ours(row: dict[str, Any], magic: int) -> bool:
    return int(row.get("magic") or 0) == magic


def _spec_from(raw: dict[str, Any], symbol: str) -> SymbolSpec:
    digits = int(raw.get("digits") or 5)
    point = float(raw.get("point") or 10.0**-digits)
    tick_size = float(raw.get("trade_tick_size") or point)
    return SymbolSpec(
        symbol=str(raw.get("name") or symbol),
        digits=digits,
        point=point,
        tick_size=tick_size,
        tick_value=float(raw.get("trade_tick_value") or 0.0),
        volume_min=float(raw.get("volume_min") or 0.01),
        volume_max=float(raw.get("volume_max") or 100.0),
        volume_step=float(raw.get("volume_step") or 0.01),
        contract_size=float(raw.get("trade_contract_size") or 0.0),
        stops_level=float(raw.get("trade_stops_level") or 0.0),
        # 4 is SYMBOL_TRADE_MODE_FULL. Anything less is close-only, quotes-only
        # or disabled, none of which can open a scalp.
        tradable=int(raw.get("trade_mode", 4)) == 4,
    )


def _position_from(row: dict[str, Any]) -> Position:
    return Position(
        ticket=int(row.get("ticket") or 0),
        symbol=str(row.get("symbol") or ""),
        # MT5 position types: 0 is buy, 1 is sell.
        side=Side.SELL if int(row.get("type") or 0) == 1 else Side.BUY,
        volume=float(row.get("volume") or 0.0),
        price_open=float(row.get("price_open") or 0.0),
        stop=float(row.get("sl") or 0.0),
        target=float(row.get("tp") or 0.0),
        price_current=float(row.get("price_current") or 0.0),
        profit=float(row.get("profit") or 0.0),
        opened=float(row.get("time") or 0.0),
        comment=str(row.get("comment") or ""),
        magic=int(row.get("magic") or 0),
    )
