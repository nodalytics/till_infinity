"""MT5 over HTTP, via the `nodalytics/mt5-api` bridge.

This is the backend that makes Linux work. The bridge runs the Windows
terminal under Wine in a container and puts FastAPI in front of it, so the only
Windows-only thing in the system is the container, and this process talks to it
over a socket like anything else.

The routes below are the bridge's as it stands, not an idealised version of
them, and two of its quirks are worth knowing because they shape the code:

**Symbol specs come from `/symbols/{symbol}`, not `/symbols/info/{symbol}`.**
The `info` route declares a narrow response model — name, path, volume limits,
`price_digits` — which drops `trade_tick_value` and `trade_tick_size`. Those
two are exactly what position sizing needs, and the bare route returns the
terminal's whole symbol dict unfiltered.

**The magic filter is applied here as well as there.** The bridge passes magic
to `positions_get`, which does not take that keyword — it filters by symbol,
group or ticket. Rather than depend on that being fixed, every position is
checked against our magic locally. The cost is a few dictionaries; the failure
it prevents is this system closing somebody's hand-placed trade.

**There is no account endpoint.** The bridge exposes health, last error and
retcodes, but nothing carrying balance or equity, so `account()` asks for
`/account/info` in case a later version grew one and otherwise falls back to
`TRADING_ACCOUNT_EQUITY`. Risk sizing needs a number; guessing one silently
would size every trade off a fiction, so the fallback is logged the first time
it is used and the setting is documented as required for this backend.
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
        try:
            body = await self._get("/account/health")
        except Exception as exc:
            log.warning("trading: bridge health check failed: %s", exc)
            return False
        return str(body.get("status", "")).lower() == "healthy"

    # ----------------------------------------------------------------- reads

    async def account(self) -> Account:
        try:
            raw = await self._get("/account/info")
        except Exception:
            raw = {}
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

    async def spec(self, symbol: str) -> SymbolSpec | None:
        try:
            raw = await self._get(f"/symbols/{symbol}")
        except RejectedError:
            return None  # 404 — the broker has no such symbol. An answer, not a fault.
        if not raw or not raw.get("name"):
            return None
        return _spec_from(raw, symbol)

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
