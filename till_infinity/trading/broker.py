"""The contract a terminal implements, and how the right one gets picked.

## Why there is more than one backend

MetaTrader 5 is a Windows program, and the `MetaTrader5` Python package is a
thin binding onto the terminal's Win32 DLL. There is no Linux wheel and there
will not be one - it is not a pure-Python package that upstream has neglected
to build, it is an in-process call into a running Windows executable.

That leaves three ways to reach a terminal from this codebase, and the project
needs all three for the same reason it keeps six price venues: the environment
is not ours to choose.

| backend | where it runs | how it talks to MT5 |
|---|---|---|
| `mt5` | Windows, or a Wine prefix with a Windows Python | `import MetaTrader5`, in-process |
| `mt5-rpyc` | anywhere | a proxy of the module itself, over RPyC |
| `mt5-http` | anywhere | HTTP to a bridge running MT5 under Wine |
| `paper` | anywhere, no terminal at all | nothing; fills are simulated against the live quote |

The middle two both put the terminal on another host and differ in what
crosses the wire. RPyC carries the module: the same functions, arguments and
namedtuples, so the native backend drives it unchanged. HTTP carries JSON
through whatever subset somebody wrapped in FastAPI. RPyC is faster and more
complete; the bridge is the one that can safely face a network, because an
RPyC server with `allow_all_attrs` will run anything it is asked to.

The HTTP bridge is `nodalytics/metatrader-terminal` - MT5 under Wine in a
container, behind FastAPI. `mt5_http.py` speaks its routes, and those of the
earlier `mt5-api` variant, which are not the same; see that module.

## Why selection is automatic, and why it is still announced

The same repository is developed on Linux and may be deployed beside a Windows
terminal, and a config file that has to change between the two is a config file
that will be wrong on one of them. So `choose` resolves the backend from what
is actually available on the host, in a fixed order.

What it does **not** do is stay quiet about it. Falling back from a terminal to
the paper book is the difference between trading and pretending to, and a
silent fallback is how a strategy runs for a week against nothing. Every path
through `choose` logs which backend it picked and why the earlier ones were
skipped.
"""

from __future__ import annotations

import platform
import sys
from abc import ABC, abstractmethod
from collections.abc import Sequence
from importlib.util import find_spec
from typing import ClassVar, Self

from ..logging import get_logger
from .config import BACKENDS, HTTP, NATIVE, PAPER, RPYC, Settings
from .models import Account, Order, OrderResult, Position, SymbolSpec, Tick

log = get_logger(__name__)


class BrokerError(Exception):
    """Base for anything a terminal refuses or fails to do."""


class NotConnectedError(BrokerError):
    """No terminal. Every other call is meaningless until this is fixed."""


class RejectedError(BrokerError):
    """The order reached the terminal and came back refused.

    Distinct from `TransientError` because a rejection is an *answer*: the
    volume was wrong, the market is closed, the stop was too close. Retrying it
    unchanged asks the same question and gets the same answer.
    """

    def __init__(self, message: str, retcode: int = 0) -> None:
        super().__init__(message)
        self.retcode = retcode


class TransientError(BrokerError):
    """Timeout, disconnect, requote. Worth another attempt."""


class Broker(ABC):
    """One trading account, however it is reached.

    Async throughout even where a backend is synchronous. The native package
    blocks - every call into it is a call into a Windows DLL - so `mt5_native`
    runs its calls in a thread rather than pretending they are cheap. Making
    the *interface* async is what lets one scalper drive either backend
    without knowing which it has.
    """

    name: ClassVar[str]

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def __aenter__(self) -> Self:
        await self.connect()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    # ------------------------------------------------------------- lifecycle

    @abstractmethod
    async def connect(self) -> Account:
        """Open the connection and return the account behind it."""

    async def close(self) -> None:
        """Release whatever `connect` acquired. Safe to call twice."""

    @abstractmethod
    async def healthy(self) -> bool:
        """Whether the terminal is still answering. Never raises."""

    # ----------------------------------------------------------------- reads

    @abstractmethod
    async def account(self) -> Account: ...

    @abstractmethod
    async def spec(self, symbol: str) -> SymbolSpec | None:
        """The instrument's trading rules, or None if the broker has no such
        symbol. None is an answer, not a failure - it is how availability is
        discovered."""

    @abstractmethod
    async def quote(self, symbol: str) -> Tick | None: ...

    @abstractmethod
    async def positions(self) -> list[Position]:
        """Open positions **belonging to this system**, filtered by magic."""

    # ---------------------------------------------------------------- writes

    @abstractmethod
    async def send(self, order: Order) -> OrderResult: ...

    @abstractmethod
    async def close_position(self, ticket: int, volume: float = 0.0) -> OrderResult: ...

    async def modify(self, ticket: int, stop: float, target: float = 0.0) -> OrderResult:
        """Move a stop or target. Optional: the paper book overrides it, and a
        backend that cannot do it says so rather than reporting a silent
        success."""
        raise BrokerError(f"{self.name}: modifying a position is not supported")

    async def catalogue(self) -> list[str] | None:
        """Every symbol this account carries, or None if it cannot be listed.

        None is not a failure - it means "ask me one at a time", which is the
        honest answer for the HTTP bridge, whose only symbol route takes a
        name. The native terminal can enumerate, and when it can, resolution
        scans the list instead of guessing suffixes.

        That distinction matters more than it looks. A broker's account-type
        suffix is not a standard: `.raw`, `.r`, `.s`, `m`, `+`, `_SB` and a
        dozen others are all in use, and no list of them can be complete. A
        scan finds whatever this broker actually calls gold without anybody
        having guessed it first.
        """
        return None

    async def closed_deal(self, ticket: int) -> tuple[float, float] | None:
        """(exit price, realised profit) for a position that has closed.

        The terminal's own record, rather than the last snapshot we happened to
        hold. A position closed server-side vanishes between polls, and
        settling it at its last observed `price_current` is a guess that is
        always a little stale and always in the direction of the move that
        closed it: the first live trade recorded +52.20 where the broker had
        paid +59.40, a 12% error on the one number every strategy will later be
        scored by.

        None when the backend cannot answer, in which case the caller keeps the
        stale estimate and says so.
        """
        return None

    def drain_closed(self) -> list[tuple[Position, float, str]]:
        """Positions this backend closed itself since the last call.

        Only the paper book can answer, because only it holds the stops. A real
        terminal keeps them server-side, and a position it closed is noticed by
        the position having disappeared - which `service` reconciles for every
        backend anyway, so this is an accuracy improvement rather than the
        mechanism.
        """
        return []


def available() -> dict[str, str]:
    """Why each backend can or cannot run here, keyed by backend name.

    An empty string means it can. Returned rather than logged so `trading
    doctor` can print the whole table - the question "why is it on paper" has
    one answer per backend and showing one of them is how the other gets
    missed.
    """
    reasons: dict[str, str] = {}

    if find_spec("MetaTrader5") is not None:
        reasons[NATIVE] = ""
    elif sys.platform.startswith("win"):
        reasons[NATIVE] = "MetaTrader5 is not installed (uv sync --extra mt5)"
    else:
        reasons[NATIVE] = (
            f"the MetaTrader5 package is Windows-only and this is {platform.system()} "
            f"- reach a terminal over rpyc or the http bridge"
        )

    reasons[RPYC] = (
        "" if find_spec("rpyc") is not None else "rpyc is not installed (uv sync --extra rpyc)"
    )
    reasons[HTTP] = "" if find_spec("httpx") is not None else "httpx is not installed"
    reasons[PAPER] = ""
    return reasons


def choose(settings: Settings) -> str:
    """Which backend to use, given the host and the configuration.

    Order: an explicit `TRADING_BACKEND` wins outright, then the native package
    if it imports, then RPyC if a host is set, then the HTTP bridge if a URL
    is, then paper. Each step is preferred over the next because it is closer
    to the terminal: in-process beats a module proxy beats a JSON wrapper, in
    latency and in how much of the API survives the trip.
    """
    reasons = available()
    wanted = (settings.backend or "auto").lower()

    if wanted and wanted != "auto":
        if wanted not in BACKENDS:
            raise ValueError(f"unknown backend {wanted!r} (have: {', '.join(BACKENDS)})")
        blocked = reasons.get(wanted, "")
        if blocked:
            # Asked for explicitly and unavailable: that is an error, not a
            # fallback. Someone who wrote TRADING_BACKEND=mt5 wants MT5.
            raise BrokerError(f"backend {wanted!r} cannot run here: {blocked}")
        if wanted == HTTP and not settings.url:
            raise BrokerError("backend 'mt5-http' needs TRADING_MT5_URL")
        if wanted == RPYC and not settings.rpyc_host:
            raise BrokerError("backend 'mt5-rpyc' needs TRADING_RPYC_HOST")
        return wanted

    if not reasons[NATIVE]:
        log.info("trading: using the native MetaTrader5 package")
        return NATIVE
    if settings.rpyc_host and not reasons[RPYC]:
        log.info(
            "trading: %s - using the module over rpyc at %s",
            reasons[NATIVE],
            settings.rpyc_host,
        )
        return RPYC
    if settings.url and not reasons[HTTP]:
        log.info("trading: %s - using the bridge at %s", reasons[NATIVE], settings.url)
        return HTTP
    log.warning(
        "trading: no terminal available (%s%s), running on paper",
        reasons[NATIVE],
        ""
        if (settings.url or settings.rpyc_host)
        else "; neither TRADING_RPYC_HOST nor TRADING_MT5_URL is set",
    )
    return PAPER


def build(settings: Settings, backend: str | None = None) -> Broker:
    """The broker for this host. Imports the backend lazily.

    Lazily because importing `MetaTrader5` on a machine that has it will try to
    attach to a terminal, and importing `mt5_http` drags in httpx - neither
    should happen because someone ran `trading symbols` on a laptop.
    """
    chosen = backend or choose(settings)
    if chosen == NATIVE:
        from .mt5_native import NativeBroker

        return NativeBroker(settings)
    if chosen == RPYC:
        from .mt5_rpyc import RpycBroker

        return RpycBroker(settings)
    if chosen == HTTP:
        from .mt5_http import HttpBroker

        return HttpBroker(settings)
    from .paper import PaperBroker

    return PaperBroker(settings)


def describe(specs: Sequence[SymbolSpec]) -> str:
    return ", ".join(s.symbol for s in specs) if specs else "nothing"
