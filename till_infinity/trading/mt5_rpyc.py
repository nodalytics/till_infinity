"""MT5 over RPyC: the Windows terminal, called as if it were local.

The third way to reach a terminal from Linux, and the closest of the three to
the real thing. A Windows Python runs inside a Wine prefix beside the terminal
and serves the `MetaTrader5` module over RPyC; this process connects and gets a
**proxy of that module back**. `conn.modules.MetaTrader5` answers
`symbol_info`, `order_send` and the rest with the same names, the same
arguments and the same namedtuples.

Which is why this class is thirty lines of connection handling on top of
`NativeBroker` and no trading logic of its own. Everything that backend does it
does through `self._mt5`, and it does not care whether that name refers to an
imported module or a network proxy of one. A second copy of the order-building
code would be a second place for the filling-mode logic to drift.

    # in the Wine prefix, once
    wine python -m rpyc.utils.server --port 18812 ThreadedServer

The usual arrangement is the `mt5linux` package, which packages exactly this.

## What it costs, and what is done about it

**Every attribute access is a round trip.** RPyC returns *netrefs* - handles to
objects that still live on the other side - so reading `position.ticket`,
`.symbol`, `.volume` off a returned namedtuple is three calls over a socket,
not three memory reads. `NativeBroker._position_from` touches eleven fields,
and `spec` touches a dozen more.

So results are **materialised** as they arrive: `_call` pulls each one across
in full, once, and hands local data to the code above. On a list of positions
that turns dozens of round trips into one. Where materialising is not possible
the netref is passed through unchanged rather than failing - it still works,
just slowly, which is the right way round for a fallback.

The module proxy itself is deliberately *not* materialised. It is the live
handle to the terminal, and copying it locally is neither possible nor wanted.

**Compared with the HTTP bridge**, this is the lower-latency option and the
more complete one: the whole MT5 API surface is available rather than the
subset somebody wrapped in FastAPI, and there is no JSON round trip. What it
gives up is the bridge's isolation - an RPyC server with `allow_all_attrs` is a
remote-code-execution service, so it must never listen on a public interface.
Bind it to localhost, or to a private network, and reach it over SSH or a
tunnel if the terminal is on another host.
"""

from __future__ import annotations

from typing import Any, ClassVar

from ..logging import get_logger
from .broker import NotConnectedError
from .config import Settings
from .models import Account
from .mt5_native import NativeBroker

log = get_logger(__name__)

#: What `rpyc.utils.server` listens on by default, and what mt5linux uses.
DEFAULT_PORT = 18812


class RpycBroker(NativeBroker):
    """The native backend, with the terminal at the other end of a socket."""

    name: ClassVar[str] = "mt5-rpyc"

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self._conn: Any = None

    async def connect(self) -> Account:
        try:
            import rpyc
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise NotConnectedError("rpyc is not installed (uv sync --extra rpyc)") from exc

        host, port = self.settings.rpyc_host, self.settings.rpyc_port or DEFAULT_PORT
        if not host:
            raise NotConnectedError("TRADING_RPYC_HOST is not set")

        try:
            self._conn = rpyc.connect(
                host,
                port,
                # The proxy has to be able to read namedtuple fields and call
                # module functions; without this every attribute is refused.
                config={
                    "allow_all_attrs": True,
                    "allow_public_attrs": True,
                    "sync_request_timeout": self.settings.timeout,
                },
            )
            self._mt5 = self._conn.modules.MetaTrader5
        except Exception as exc:
            self._conn = None
            raise NotConnectedError(
                f"could not reach the RPyC server at {host}:{port}: {exc}"
            ) from exc

        # The remote terminal still has to be initialised, exactly as a local
        # one does - the proxy is a way of calling it, not a way of starting it.
        kwargs: dict[str, Any] = {}
        if self.settings.terminal:
            kwargs["path"] = self.settings.terminal
        if self.settings.login:
            kwargs.update(
                login=self.settings.login,
                password=self.settings.password,
                server=self.settings.server,
            )
        if not await self._to_thread(lambda: self._mt5.initialize(**kwargs)):
            code, message = self._local(self._mt5.last_error())
            await self.close()
            raise NotConnectedError(f"MT5 initialize failed on {host}: {message} ({code})")

        account = await self.account()
        log.info("trading: attached to MT5 at %s:%d over rpyc - %s", host, port, account)
        return account

    async def close(self) -> None:
        self._mt5 = None
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception as exc:  # a closing socket must not raise here
                log.debug("trading: closing the rpyc connection failed: %s", exc)
            self._conn = None

    async def _call(self, name: str, *args: Any, **kwargs: Any) -> Any:
        """Call the remote module and bring the answer across whole.

        The materialisation is the point - see the module docstring. Without it
        every field read by the code above is its own socket round trip.
        """
        return self._local(await super()._call(name, *args, **kwargs))

    async def _to_thread(self, call) -> Any:
        import asyncio

        return await asyncio.to_thread(call)

    @staticmethod
    def _local(value: Any) -> Any:
        """A local copy of a netref, or the netref if it cannot be copied.

        Falling back rather than raising: a value that will not pickle still
        works through the proxy, just with a round trip per field, and a
        backend that refused it would be trading nothing over a performance
        detail.
        """
        try:
            import rpyc

            return rpyc.utils.classic.obtain(value)
        except Exception:
            return value
