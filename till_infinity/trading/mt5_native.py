"""MT5 in-process, through the `MetaTrader5` package.

The fastest path and the narrowest: the package is a binding onto a running
Windows terminal, so this backend exists on Windows, and inside a Wine prefix
that has a Windows Python in it. Everywhere else `broker.choose` never reaches
this module — which is also why the import sits inside `connect` rather than at
the top of the file, so a Linux host can import the package for its types
without the import failing.

**Every call runs in a thread.** The package is synchronous and each call
crosses into a DLL that may block for as long as the terminal takes to answer.
Awaiting `to_thread` rather than calling directly is what keeps one slow
`order_send` from stopping the quote stream that the rest of the system is
reading.

**A symbol has to be selected before it can be seen.** `symbol_info` returns
None for anything not in Market Watch, which is indistinguishable from the
broker not offering it. `symbol_select(name, True)` is therefore part of asking
whether a symbol exists, not a separate setup step — without it, availability
detection reports every instrument as missing on a fresh terminal.
"""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar

from ..logging import get_logger
from .broker import Broker, NotConnectedError, RejectedError
from .config import Settings
from .models import Account, Order, OrderResult, Position, Side, SymbolSpec, Tick

log = get_logger(__name__)

TRADE_DONE = 10009
#: Also a success: the request was placed but the terminal is in "no execution
#: confirmation" mode. Treating it as a failure would leave a live position
#: that this system does not believe it has, which is the worst of both.
TRADE_PLACED = 10008


class NativeBroker(Broker):
    """One terminal, in this process."""

    name: ClassVar[str] = "mt5"

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self._mt5: Any = None

    # ------------------------------------------------------------- lifecycle

    async def connect(self) -> Account:
        try:
            import MetaTrader5 as mt5
        except ImportError as exc:  # pragma: no cover - platform-dependent
            raise NotConnectedError(
                "the MetaTrader5 package is not installed (uv sync --extra mt5, Windows only)"
            ) from exc

        kwargs: dict[str, Any] = {}
        if self.settings.terminal:
            kwargs["path"] = self.settings.terminal
        if self.settings.login:
            kwargs.update(
                login=self.settings.login,
                password=self.settings.password,
                server=self.settings.server,
            )
        if not await asyncio.to_thread(lambda: mt5.initialize(**kwargs)):
            code, message = mt5.last_error()
            raise NotConnectedError(f"MT5 initialize failed: {message} ({code})")

        self._mt5 = mt5
        account = await self.account()
        log.info("trading: attached to MT5 %s", account)
        return account

    async def close(self) -> None:
        if self._mt5 is not None:
            await asyncio.to_thread(self._mt5.shutdown)
            self._mt5 = None

    async def healthy(self) -> bool:
        if self._mt5 is None:
            return False
        try:
            return bool(await asyncio.to_thread(self._mt5.terminal_info))
        except Exception as exc:
            log.warning("trading: terminal health check failed: %s", exc)
            return False

    # ----------------------------------------------------------------- reads

    async def account(self) -> Account:
        info = await self._call("account_info")
        if info is None:
            raise NotConnectedError("MT5 returned no account info")
        return Account(
            login=int(info.login),
            currency=str(info.currency),
            balance=float(info.balance),
            equity=float(info.equity),
            margin_free=float(info.margin_free),
            leverage=int(info.leverage),
        )

    async def spec(self, symbol: str) -> SymbolSpec | None:
        info = await self._select(symbol)
        if info is None:
            return None
        return SymbolSpec(
            symbol=info.name,
            digits=int(info.digits),
            point=float(info.point),
            tick_size=float(info.trade_tick_size or info.point),
            tick_value=float(info.trade_tick_value or 0.0),
            volume_min=float(info.volume_min),
            volume_max=float(info.volume_max),
            volume_step=float(info.volume_step),
            contract_size=float(info.trade_contract_size or 0.0),
            stops_level=float(getattr(info, "trade_stops_level", 0.0) or 0.0),
            tradable=int(info.trade_mode) == self._mt5.SYMBOL_TRADE_MODE_FULL,
        )

    async def catalogue(self) -> list[str] | None:
        """Every symbol on the account, so resolution can scan rather than guess.

        `symbols_get()` with no argument returns the broker's whole tree,
        including instruments not in Market Watch — which is the point, since a
        symbol has to be found before it can be selected.
        """
        try:
            found = await self._call("symbols_get")
        except Exception as exc:
            log.warning("trading: could not list symbols: %s", exc)
            return None
        names = [str(row.name) for row in (found or ())]
        return names or None

    async def quote(self, symbol: str) -> Tick | None:
        tick = await self._call("symbol_info_tick", symbol)
        if tick is None or not tick.bid or not tick.ask:
            return None
        return Tick(symbol=symbol, bid=float(tick.bid), ask=float(tick.ask), time=float(tick.time))

    async def positions(self) -> list[Position]:
        found = await self._call("positions_get")
        rows = list(found or ())
        return [
            _position_from(row, self._mt5)
            for row in rows
            if int(getattr(row, "magic", 0)) == self.settings.magic
        ]

    # ---------------------------------------------------------------- writes

    async def send(self, order: Order) -> OrderResult:
        mt5 = self._require()
        tick = await self.quote(order.symbol)
        if tick is None:
            raise RejectedError(f"no quote for {order.symbol}")
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": order.symbol,
            "volume": order.volume,
            "type": mt5.ORDER_TYPE_BUY if order.side is Side.BUY else mt5.ORDER_TYPE_SELL,
            "price": tick.entry(order.side),
            "sl": order.stop,
            "tp": order.target,
            "deviation": order.deviation,
            "magic": order.magic,
            # MT5 truncates a comment at 31 characters and rejects some
            # punctuation; the reasoning lives in the journal, not here.
            "comment": order.comment[:31],
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": await self._filling(order.symbol),
        }
        return _result_from(await self._call("order_send", request))

    async def close_position(self, ticket: int, volume: float = 0.0) -> OrderResult:
        mt5 = self._require()
        found = await self._call("positions_get", ticket=ticket)
        rows = list(found or ())
        if not rows:
            raise RejectedError(f"no position {ticket}")
        position = rows[0]
        side = Side.SELL if int(position.type) == mt5.POSITION_TYPE_SELL else Side.BUY
        tick = await self.quote(position.symbol)
        if tick is None:
            raise RejectedError(f"no quote for {position.symbol}")
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": position.symbol,
            "volume": volume or float(position.volume),
            # Closing is an opposite deal against the same position ticket.
            "type": mt5.ORDER_TYPE_SELL if side is Side.BUY else mt5.ORDER_TYPE_BUY,
            "position": ticket,
            "price": tick.exit(side),
            "deviation": self.settings.deviation,
            "magic": self.settings.magic,
            "comment": "till: close",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": await self._filling(position.symbol),
        }
        return _result_from(await self._call("order_send", request))

    async def modify(self, ticket: int, stop: float, target: float = 0.0) -> OrderResult:
        mt5 = self._require()
        found = await self._call("positions_get", ticket=ticket)
        rows = list(found or ())
        if not rows:
            raise RejectedError(f"no position {ticket}")
        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": rows[0].symbol,
            "position": ticket,
            "sl": stop,
            "tp": target or float(rows[0].tp),
        }
        return _result_from(await self._call("order_send", request))

    # ---------------------------------------------------------------- inside

    def _require(self) -> Any:
        if self._mt5 is None:
            raise NotConnectedError("not attached to a terminal")
        return self._mt5

    async def _call(self, name: str, *args: Any, **kwargs: Any) -> Any:
        mt5 = self._require()
        return await asyncio.to_thread(lambda: getattr(mt5, name)(*args, **kwargs))

    async def _select(self, symbol: str) -> Any:
        """Add the symbol to Market Watch, then read it. None if there is no such symbol."""
        mt5 = self._require()
        if not await asyncio.to_thread(lambda: mt5.symbol_select(symbol, True)):
            return None
        return await self._call("symbol_info", symbol)

    async def _filling(self, symbol: str) -> int:
        """The fill policy this symbol accepts, preferring the configured one.

        Brokers differ, and a policy the symbol does not allow is rejected with
        "Unsupported filling mode" — a failure that looks like a bad order and
        is really a bad constant. The symbol's own `filling_mode` mask is the
        authority; the setting only chooses between what it permits.

        Async because the lookup is a call into the terminal, and over RPyC
        that is a socket round trip. Building it into the request dict
        synchronously blocked the event loop on the network for every order.
        """
        mt5 = self._require()
        wanted = {
            "IOC": mt5.ORDER_FILLING_IOC,
            "FOK": mt5.ORDER_FILLING_FOK,
            "RETURN": mt5.ORDER_FILLING_RETURN,
        }.get(self.settings.filling, mt5.ORDER_FILLING_IOC)

        info = await self._call("symbol_info", symbol)
        mask = int(getattr(info, "filling_mode", 0) or 0)
        if not mask:
            return wanted
        # The mask is a bitfield of SYMBOL_FILLING_* flags, which are 1 and 2
        # for FOK and IOC respectively — one off from the ORDER_FILLING_*
        # constants, so they are checked rather than reused.
        allows_fok, allows_ioc = bool(mask & 1), bool(mask & 2)
        if wanted == mt5.ORDER_FILLING_IOC and allows_ioc:
            return mt5.ORDER_FILLING_IOC
        if wanted == mt5.ORDER_FILLING_FOK and allows_fok:
            return mt5.ORDER_FILLING_FOK
        if allows_ioc:
            return mt5.ORDER_FILLING_IOC
        if allows_fok:
            return mt5.ORDER_FILLING_FOK
        return mt5.ORDER_FILLING_RETURN


def _result_from(raw: Any) -> OrderResult:
    if raw is None:
        raise RejectedError("MT5 returned nothing for the order")
    retcode = int(getattr(raw, "retcode", 0))
    return OrderResult(
        ok=retcode in (TRADE_DONE, TRADE_PLACED),
        ticket=int(getattr(raw, "order", 0) or 0),
        price=float(getattr(raw, "price", 0.0) or 0.0),
        volume=float(getattr(raw, "volume", 0.0) or 0.0),
        retcode=retcode,
        comment=str(getattr(raw, "comment", "") or ""),
    )


def _position_from(row: Any, mt5: Any) -> Position:
    return Position(
        ticket=int(row.ticket),
        symbol=str(row.symbol),
        side=Side.SELL if int(row.type) == mt5.POSITION_TYPE_SELL else Side.BUY,
        volume=float(row.volume),
        price_open=float(row.price_open),
        stop=float(row.sl or 0.0),
        target=float(row.tp or 0.0),
        price_current=float(row.price_current or 0.0),
        profit=float(row.profit or 0.0),
        opened=float(row.time or 0.0),
        comment=str(row.comment or ""),
        magic=int(row.magic or 0),
    )
