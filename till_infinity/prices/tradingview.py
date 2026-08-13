"""TradingView chart socket — per-broker OHLCV, no API key.

Wire format is socket.io 0.9 style: ``~m~<len>~m~<payload>`` frames, several per
websocket message. A payload is either JSON ``{"m": method, "p": params}``, the
opening session handshake, or a ``~h~<n>`` heartbeat that must be echoed back
verbatim or the server hangs up.

What this does differently from the throwaway script it grew out of:

* one socket per *symbol* instead of one per (symbol, interval) — a chart
  session is cheap, a TCP+TLS handshake is not;
* symbols run concurrently under a semaphore rather than serially;
* ``request_more_data`` pagination, so deep history is actually reachable
  instead of capped at whatever one ``create_series`` returns;
* frames are parsed by length, not by regex-splitting the whole message;
* symbol errors are separated from transport errors so retries only fire where
  they can help.
"""

from __future__ import annotations

import asyncio
import random
import re
import string
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager, suppress
from typing import Any, Self

import httpx
import orjson
from httpx_ws import AsyncWebSocketSession, aconnect_ws

from ..logging import get_logger
from .config import Settings
from .models import Bar, Interval, WriteResult
from .source import BarSink, Job, PermanentError, Source, TransientError, first_cause

log = get_logger(__name__)

#: TradingView refuses much more than this in a single series request.
MAX_BARS_PER_REQUEST = 5_000
#: A 5k-bar timescale_update is far bigger than httpx-ws's default cap.
MAX_MESSAGE_BYTES = 32 * 1024 * 1024

INTERVAL_CODES: dict[str, str] = {
    "1m": "1",
    "5m": "5",
    "15m": "15",
    "1h": "60",
    "2h": "120",
    "4h": "240",
    "1d": "1D",
    "1w": "1W",
}

_FRAME = re.compile(r"~m~(\d+)~m~")
_SYMBOL_ERRORS = frozenset({"symbol_error", "series_error", "study_error"})
_FATAL_ERRORS = frozenset({"critical_error", "protocol_error"})


# ---------------------------------------------------------------- wire format


def encode(payload: str) -> str:
    """Wrap a payload in a ``~m~<len>~m~`` frame."""
    return f"~m~{len(payload)}~m~{payload}"


def decode(raw: str) -> list[str]:
    """Split a websocket message into its payloads, honouring the length prefix."""
    payloads: list[str] = []
    pos = 0
    while pos < len(raw):
        match = _FRAME.match(raw, pos)
        if match is None:
            break
        start = match.end()
        length = int(match.group(1))
        payloads.append(raw[start : start + length])
        pos = start + length
    return payloads


def message(method: str, params: Sequence[Any]) -> str:
    """Encode a ``{"m": ..., "p": ...}`` call as a frame."""
    body = orjson.dumps({"m": method, "p": list(params)}).decode()
    return encode(body)


def session_id(prefix: str) -> str:
    return prefix + "".join(random.choices(string.ascii_lowercase, k=12))


def symbol_spec(venue: str, ticker: str) -> str:
    spec = orjson.dumps({"symbol": f"{venue}:{ticker}", "adjustment": "splits"}).decode()
    return f"={spec}"


def extract_bars(params: Sequence[Any]) -> list[Bar]:
    """Pull candles out of a ``timescale_update`` / ``du`` payload."""
    bars: list[Bar] = []
    for element in params[1:]:
        if not isinstance(element, dict):
            continue
        for value in element.values():
            if not isinstance(value, dict):
                continue
            entries = value.get("s")
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                bar = Bar.from_series(entry.get("v"))
                if bar is not None:
                    bars.append(bar)
    return bars


# ------------------------------------------------------------------ connection


class Connection:
    """A live chart socket. Reused across every interval of one symbol."""

    def __init__(self, ws: AsyncWebSocketSession, settings: Settings) -> None:
        self._ws = ws
        self._settings = settings

    async def handshake(self) -> None:
        await self._send("set_auth_token", [self._settings.tv_auth_token])

    async def _send(self, method: str, params: Sequence[Any]) -> None:
        await self._ws.send_text(message(method, params))

    async def _receive(self, timeout: float) -> list[tuple[str, list[Any]]]:
        """One websocket message, decoded; heartbeats answered in place."""
        try:
            raw = await self._ws.receive_text(timeout=timeout)
        except TimeoutError as exc:
            raise TransientError("timed out waiting for data") from exc
        except Exception as exc:  # disconnect, protocol failure
            raise TransientError(f"socket error: {exc}") from exc

        out: list[tuple[str, list[Any]]] = []
        for payload in decode(raw):
            if payload.startswith("~h~"):
                await self._ws.send_text(encode(payload))
                continue
            try:
                obj = orjson.loads(payload)
            except orjson.JSONDecodeError:
                continue
            if isinstance(obj, dict) and "m" in obj:
                params = obj.get("p")
                out.append((str(obj["m"]), list(params) if isinstance(params, list) else []))
        return out

    async def series(self, venue: str, ticker: str, interval: Interval, want: int) -> list[Bar]:
        """Fetch up to `want` bars, paginating with ``request_more_data``."""
        code = INTERVAL_CODES.get(interval.name)
        if code is None:
            raise PermanentError(f"TradingView has no resolution for {interval.name}")

        chart = session_id("cs_")
        sym_id, series_id = "sym_1", "s1"
        await self._send("chart_create_session", [chart, ""])
        await self._send("resolve_symbol", [chart, sym_id, symbol_spec(venue, ticker)])
        await self._send(
            "create_series",
            [chart, series_id, series_id, sym_id, code, min(want, MAX_BARS_PER_REQUEST), ""],
        )

        collected: dict[int, Bar] = {}
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._settings.tv_fetch_timeout
        pages = 0
        try:
            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    if collected:
                        break
                    raise TransientError(f"no data for {venue}:{ticker} {interval.name}")

                completed = False
                for method, params in await self._receive(
                    min(self._settings.tv_recv_timeout, remaining)
                ):
                    if params and params[0] != chart:
                        continue  # a stale session's tail end
                    if method in ("timescale_update", "du"):
                        for bar in extract_bars(params):
                            collected[bar.time] = bar
                    elif method == "series_completed":
                        completed = True
                    elif method in _SYMBOL_ERRORS:
                        raise PermanentError(f"{venue}:{ticker} {interval.name}: {method}")
                    elif method in _FATAL_ERRORS:
                        raise TransientError(f"{method}: {params}")

                if not completed:
                    continue
                if len(collected) >= want or pages >= self._settings.tv_max_pages:
                    break
                before = len(collected)
                await self._send(
                    "request_more_data",
                    [chart, series_id, min(want - before, MAX_BARS_PER_REQUEST)],
                )
                pages += 1
                # Server answers with more timescale_update frames; if the next
                # completion adds nothing, history is exhausted.
                if not await self._drain_page(chart, collected, deadline):
                    break
        finally:
            with suppress(Exception):  # teardown is best effort
                await self._send("chart_delete_session", [chart])

        return [collected[t] for t in sorted(collected)][-want:]

    async def _drain_page(self, chart: str, collected: dict[int, Bar], deadline: float) -> bool:
        """Consume one ``request_more_data`` page; True if it added bars."""
        loop = asyncio.get_running_loop()
        added = 0
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                return False
            done = False
            for method, params in await self._receive(
                min(self._settings.tv_recv_timeout, remaining)
            ):
                if params and params[0] != chart:
                    continue
                if method in ("timescale_update", "du"):
                    for bar in extract_bars(params):
                        if bar.time not in collected:
                            added += 1
                        collected[bar.time] = bar
                elif method == "series_completed":
                    done = True
                elif method in _SYMBOL_ERRORS:
                    raise PermanentError(f"{method}: {params}")
                elif method in _FATAL_ERRORS:
                    raise TransientError(f"{method}: {params}")
            if done:
                return added > 0


# ---------------------------------------------------------------------- source


class TradingViewSource(Source):
    """Candles from TradingView's chart feed, one socket per symbol."""

    name = "tradingview"

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self._client: httpx.AsyncClient | None = None

    @property
    def concurrency(self) -> int:
        return self.settings.tv_concurrency

    def supported(self, intervals: Sequence[Interval]) -> tuple[Interval, ...]:
        return tuple(i for i in intervals if i.name in INTERVAL_CODES)

    async def __aenter__(self) -> Self:
        self._client = httpx.AsyncClient(
            headers={
                "Origin": self.settings.tv_origin,
                "User-Agent": self.settings.user_agent,
            },
            timeout=httpx.Timeout(self.settings.tv_connect_timeout),
        )
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        client, self._client = self._client, None
        if client is not None:
            await client.aclose()

    @asynccontextmanager
    async def _connect(self) -> AsyncIterator[Connection]:
        if self._client is None:
            raise RuntimeError("source is not open")
        try:
            async with aconnect_ws(
                self.settings.tv_ws_url,
                self._client,
                max_message_size_bytes=MAX_MESSAGE_BYTES,
                # TradingView drives its own ~h~ heartbeat and ignores WS pings.
                keepalive_ping_interval_seconds=None,
            ) as ws:
                conn = Connection(ws, self.settings)
                await conn.handshake()
                yield conn
        except (PermanentError, TransientError):
            raise
        except Exception as exc:
            # anyio wraps a failed connect in an ExceptionGroup, which is
            # neither HTTPError nor OSError — left unclassified it would skip
            # the retry entirely, so anything unrecognised here is transient.
            raise TransientError(f"connect failed: {first_cause(exc)}") from exc

    async def fetch(self, job: Job, bars: int, sink: BarSink) -> WriteResult:
        total = WriteResult()
        async with self._connect() as conn:
            for interval in job.intervals:
                try:
                    candles = await conn.series(job.symbol.venue, job.symbol.ticker, interval, bars)
                except PermanentError as exc:
                    log.warning("skipping %s %s: %s", job.symbol.full, interval.name, exc)
                    continue
                total += await sink(job.key(interval), self.keep(candles, interval))
                await asyncio.sleep(self.settings.tv_request_gap)
        return total
