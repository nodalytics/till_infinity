"""MT5 over HTTP, via a FastAPI bridge running the terminal under Wine.

This is the backend that makes Linux work. The bridge runs the Windows
terminal under Wine in a container and puts FastAPI in front of it, so the only
Windows-only thing in the system is the container, and this process talks to it
over a socket like anything else.

## Two bridges, one client

There are two of these in the wild and they are not the same API:

* **`metatrader-terminal`** - the published one, and the more complete;
* **`mt5-api`** - an earlier variant, which may only exist locally.

They share the `/api/v1` prefix, the `X-API-Key` header, `POST /trading/order`
and `POST /positions/close`, and they differ in exactly the places that matter
here. Rather than pick one and be broken against the other, this client
**probes what it is talking to** at connect and adapts. Three differences:

| | `metatrader-terminal` | `mt5-api` |
|---|---|---|
| account | `GET /terminal/account/info` | none - falls back to `TRADING_ACCOUNT_EQUITY` |
| symbol list | `GET /symbols/` returns every name | none - suffixes have to be probed |
| symbol spec | `GET /symbols/info/{symbol}` | `GET /symbols/{symbol}` |

That last one is not cosmetic. `metatrader-terminal` has **no** bare
`/symbols/{symbol}` route, so a client hard-wired to it 404s on every symbol
and concludes the broker carries none of them - which is a total failure that
looks exactly like a broker naming problem. And on `mt5-api` the `info` route
is the one that cannot be used, because its response model narrows the payload
to name, path, volume limits and `price_digits`, dropping `trade_tick_value`
and `trade_tick_size` - precisely what position sizing needs. Each project's
working route is the other's broken one, so both are tried and the answer is
judged by whether it actually carries a tick value.

Where the symbol list exists it is used, and that is the better path by a
distance: the account's suffix is *found* rather than guessed from a list of
twenty-odd that cannot be complete. See `symbols.resolve`.

**The magic filter is applied here, and only here.** The bridge passes magic
to `positions_get`, which does not take that keyword - it filters by symbol,
group or ticket. Rather than depend on that being fixed, every position is
checked locally. The cost is a few dictionaries; the failure it prevents is
this system closing somebody's hand-placed trade.

The request no longer *sends* a magic either. Each strategy now stamps its
own - see `config.MAGIC_BAND` - so asking the bridge for one exact number
would hide every position except the unattributed ones, and the trader would
stop managing trades it had just opened. Ownership is a band, and a band is
not something the query parameter can express.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, ClassVar

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from ..logging import get_logger
from .broker import Broker, BrokerError, NotConnectedError, RejectedError, TransientError
from .candles import Bar
from .config import Settings, ours
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
        value - `mt5-api`'s `info` route returns a 200 with a narrowed payload
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
                continue  # 404 - this route, or this symbol. The next one says which.
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
        raw = await self._get("/positions/")
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
        # The terminal's own answer where the bridge returns it, and the stored
        # row otherwise. Older builds returned only the row - and serialised it
        # to `{}` - so every field here has to survive both being absent.
        result = raw.get("result") or {}
        ticket = result.get("order") or trade.get("transaction_broker_id") or 0
        price = result.get("price") or trade.get("entry_price") or 0.0
        retcode = int(result.get("retcode") or 0)
        return OrderResult(
            # A retcode when there is one, `success` when there is not. The
            # bridge raises on a bad retcode, so a 2xx already means filled -
            # but reading the code when it is there means a future build that
            # stops raising does not silently look like a fill.
            ok=bool(raw.get("success")) and retcode in (0, TRADE_DONE, 10008),
            ticket=int(ticket) if str(ticket).isdigit() else 0,
            price=float(price),
            volume=float(result.get("volume") or trade.get("order_volume") or order.volume),
            retcode=retcode,
            comment=str(result.get("comment") or ""),
        )

    async def modify(self, ticket: int, stop: float, target: float = 0.0) -> OrderResult:
        """Move a stop or target, by ticket.

        `POST /positions/modify` takes the MT5 ticket. The older
        `/trading/modify-sl-tp` takes a `trade_id` from the bridge's own
        database and so cannot touch a position it did not record - which is
        every position after the bridge restarts. Without the ticket route this
        backend could not trail a stop at all.
        """
        body: dict[str, Any] = {"ticket": ticket, "sl": stop}
        if target:
            body["tp"] = target
        raw = await self._post("/positions/modify", json=body)
        result = raw.get("result") or {}
        retcode = int(result.get("retcode") or 0)
        return OrderResult(
            ok=bool(raw.get("success")) and retcode in (0, TRADE_DONE, 10008),
            ticket=ticket,
            price=float(result.get("price") or 0.0),
            retcode=retcode,
            comment=str(result.get("comment") or ""),
        )

    async def closed_deal(self, ticket: int) -> tuple[float, float] | None:
        """The closing deal for a position, from the bridge's history.

        Deals are linked to their position by `position_id`, and the one that
        closed it is the one with `entry == 1` (DEAL_ENTRY_OUT). A partial
        close leaves several, so the profits are summed and the last price is
        the one the position finally left at.
        """
        try:
            raw = await self._get("/history/deals", params={"days": 1})
        except Exception as exc:
            log.debug("trading: could not read deal history: %s", exc)
            return None
        rows = raw if isinstance(raw, list) else raw.get("deals", [])
        closing = [
            row
            for row in rows
            if isinstance(row, dict)
            and int(row.get("position_id") or 0) == ticket
            and int(row.get("entry") or 0) == 1
        ]
        if not closing:
            return None
        closing.sort(key=lambda row: row.get("time_msc") or row.get("time") or 0)
        profit = sum(
            float(row.get("profit") or 0.0)
            + float(row.get("swap") or 0.0)
            + float(row.get("commission") or 0.0)
            + float(row.get("fee") or 0.0)
            for row in closing
        )
        return float(closing[-1].get("price") or 0.0), profit

    async def close_position(self, ticket: int, volume: float = 0.0) -> OrderResult:
        """Close a position, or `volume` of it when a part is asked for.

        **The volume has to be sent.** This method took the argument and threw
        it away, posting only the ticket - so every partial close was a full
        close that reported success, and the scale-out rule silently shut whole
        positions while logging that it had taken half off. Caught on the first
        live scale-out, by the broker's own deal history showing one close of
        3.0 lots where the log claimed 1.5.

        Zero means all of it, which is what the bridge does with the parameter
        absent, so the full-close path is unchanged.
        """
        params: dict[str, Any] = {"ticket": ticket}
        if volume > 0:
            params["volume"] = volume
        raw = await self._post("/positions/close", params=params)
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

    #: Our interval names against MT5's. Anything absent simply has no bars,
    #: which reads downstream as an unconfirmed trade rather than an error.
    TIMEFRAMES: ClassVar[dict[str, str]] = {
        "1m": "M1",
        "3m": "M3",
        "5m": "M5",
        "15m": "M15",
        "30m": "M30",
        "1h": "H1",
        "4h": "H4",
        "1d": "D1",
        "1w": "W1",
    }

    async def bars(self, symbol: str, interval: str, count: int = 3) -> list[Bar]:
        """Recent closed candles, oldest first.

        **The forming bar is dropped**, and that is the whole reason this is
        not a thin wrapper. The bridge returns the current, incomplete bar as
        the last element - its close is simply the current price - so a pattern
        read from it is a statement about this instant that the next tick can
        withdraw. One extra bar is requested and the last is discarded.
        """
        timeframe = self.TIMEFRAMES.get(interval)
        if not timeframe:
            return []
        try:
            raw = await self._get(
                "/symbols/rates/pos",
                params={"symbol": symbol, "timeframe": timeframe, "num_bars": count + 1},
            )
        except BrokerError as exc:
            log.debug("trading: no bars for %s %s: %s", symbol, interval, exc)
            return []
        if not isinstance(raw, list) or len(raw) < 2:
            return []
        out = []
        for row in raw[:-1]:  # drop the forming bar
            try:
                out.append(
                    Bar(
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                        time=_bar_time(row.get("time")),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return out

    async def _get(self, path: str, **kwargs: Any) -> Any:
        return await self._request("GET", path, **kwargs)

    async def _post(self, path: str, **kwargs: Any) -> Any:
        return await self._request("POST", path, **kwargs)


def _bar_time(raw: Any) -> float:
    """A bar's open time as epoch seconds.

    The bridge is not consistent with itself: `/symbols/ticks/` sends epoch
    seconds and `/symbols/rates/` sends an ISO string like
    `2026-08-07T15:00:00`. The string carries no zone and is the broker's
    server time, which is UTC here - Wall Street 30's last Friday bar opens at
    20:45 and its last tick was 20:44:58 UTC, so the two agree.

    `Bar.time` defaulted to 0.0 for every bar the bridge returned until this
    existed, because `float("2026-08-07T15:00:00")` raises and the whole row
    was skipped.
    """
    if isinstance(raw, int | float):
        return float(raw)
    if not isinstance(raw, str) or not raw:
        return 0.0
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).replace(tzinfo=UTC).timestamp()
    except ValueError:
        return 0.0


def _body(response: httpx.Response, method: str, path: str) -> Any:
    """Turn a response into data, or into the right kind of error.

    A 5xx is transient and a 4xx is not: the bridge answering 400 "Invalid
    volume" to the same order body a second time is certain, and retrying it
    only delays the log line that says so.
    """
    if response.status_code >= 500:
        raise TransientError(f"{method} {path}: {response.status_code}")
    if response.status_code >= 400:
        # Every key, not just `detail`. This looked for one field, the bridge
        # does not use it, and so a refusal arrived as a bare "400" carrying
        # nothing. That single omission hid three separate causes in one day -
        # a stops-level miss on eurgbp, an impossible target on brent, and a
        # market closed for its daily break - each needing its own
        # investigation to identify, and one of them never identified at all
        # because the container had recycled by the time anyone looked.
        detail = ""
        try:
            body = response.json()
        except Exception:  # an error page that is not JSON is still an error
            detail = response.text[:300]
        else:
            if isinstance(body, dict):
                # The usual suspects first, so the common case reads cleanly,
                # then the whole body rather than nothing.
                for key in ("detail", "message", "error", "comment", "retcode"):
                    found = body.get(key)
                    if found:
                        detail = f"{key}={found}"
                        break
                else:
                    detail = str(body)[:300]
            else:
                detail = str(body)[:300]
        raise RejectedError(f"{method} {path}: {response.status_code} {detail}")
    try:
        return response.json()
    except Exception as exc:
        raise TransientError(f"{method} {path}: response was not JSON") from exc


def _ours(row: dict[str, Any], base: int) -> bool:
    return ours(base, int(row.get("magic") or 0))


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
