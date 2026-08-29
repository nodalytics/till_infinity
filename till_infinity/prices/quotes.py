"""Realtime top-of-book: the same instrument priced by many brokers at once.

Two transports, because they are not equivalent:

* **socket** (default) - TradingView's quote websocket. One connection carries
  every symbol and the server *pushes* each change, so a write happens the
  moment a broker moves, not on a timer. It also covers venues the HTTP
  endpoint does not (DERIV 404s there) and fills in the last price, which the
  scanner returns as null for FX.
* **scanner** - the keyless ``scanner.tradingview.com/symbol`` endpoint. Purely
  request/response, so it has to be polled. Stateless and simple; use it when a
  long-lived socket is inconvenient.

Yahoo has no real book for FX or futures, so its quote is the last trade. It is
here so a Yahoo-only run still produces something.

FXCM is not in the feed list: TradingView delisted it, and symbol search returns
nothing for that exchange on any transport.
"""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Awaitable, Callable, Sequence
from contextlib import AsyncExitStack, suppress
from dataclasses import dataclass, field
from typing import Any, Self

import httpx
import orjson
from httpx_ws import aconnect_ws

from ..bus import QUOTES, Bus
from ..logging import get_logger
from .config import BROKER, TRADINGVIEW, YAHOO, Feed, Settings
from .models import Quote, QuoteKey, Symbol, WriteResult
from .tradingview import MAX_MESSAGE_BYTES, decode, encode, message, session_id

log = get_logger(__name__)

SCANNER_URL = "https://scanner.tradingview.com/symbol"

#: Fields to ask for. Both transports name them the same way.
QUOTE_FIELDS: tuple[str, ...] = ("lp", "bid", "ask", "volume", "ch", "chp", "lp_time")
SCANNER_FIELDS = ",".join(f for f in QUOTE_FIELDS if f != "lp_time")

QuoteSink = Callable[[QuoteKey, Quote], Awaitable[WriteResult]]


def announce_quote(key: QuoteKey, quote: Quote) -> dict[str, object]:
    """Top of book as it goes on the wire. Time in epoch seconds, like the model."""
    return {
        "source": key.source,
        "feed": key.feed,
        "venue": key.symbol.venue,
        "ticker": key.symbol.ticker,
        "bid": quote.bid,
        "ask": quote.ask,
        "mid": quote.mid,
        "spread_bps": quote.spread_bps,
        "time": quote.time,
    }


def publishing(sink: QuoteSink | None, bus: Bus) -> QuoteSink:
    """Wrap a sink so every stored quote is also announced.

    Wrapping rather than publishing at the call sites is what makes pushed and
    polled quotes behave the same: a streaming source is handed this sink in
    `prepare()` and writes through it on push, so nothing has to know which
    transport a venue happens to use.
    """

    async def announcing(key: QuoteKey, quote: Quote) -> WriteResult:
        result = await sink(key, quote) if sink is not None else WriteResult()
        await bus.publish(QUOTES, announce_quote(key, quote), source="prices")
        return result

    return announcing


@dataclass(slots=True)
class QuoteTick:
    """A snapshot of every symbol, taken at one instant."""

    quotes: dict[QuoteKey, Quote] = field(default_factory=dict)
    written: WriteResult = field(default_factory=WriteResult)
    pushed: WriteResult = field(default_factory=WriteResult)
    missing: int = 0
    elapsed: float = 0.0

    @property
    def stored(self) -> int:
        return self.written.inserted + self.pushed.inserted

    def __str__(self) -> str:
        return (
            f"{len(self.quotes)} quotes, {self.stored} stored"
            + (f" ({self.pushed.inserted} pushed)" if self.pushed.inserted else "")
            + (f", {self.missing} unavailable" if self.missing else "")
            + f" in {self.elapsed:.2f}s"
        )

    def by_feed(self, feed: str) -> list[tuple[QuoteKey, Quote]]:
        """This feed's brokers, tightest spread first. A zero spread is the
        tightest there is, so sort on ``is None`` rather than truthiness."""
        rows = [(k, q) for k, q in self.quotes.items() if k.feed == feed]
        return sorted(
            rows,
            key=lambda row: (row[1].spread_bps is None, row[1].spread_bps or 0.0),
        )


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) else number


def parse_quote(payload: Any, *, now: float) -> Quote | None:
    """Build a Quote from a field dict - the shape both transports return."""
    if not isinstance(payload, dict) or "code" in payload:
        return None
    quote = Quote(
        time=now,
        bid=_number(payload.get("bid")),
        ask=_number(payload.get("ask")),
        last=_number(payload.get("lp")),
        volume=_number(payload.get("volume")),
        change=_number(payload.get("ch")),
        change_pct=_number(payload.get("chp")),
    )
    return None if quote.is_empty else quote


class QuoteSource:
    """Provides top-of-book for one provider."""

    #: How the caller selects this source.
    name: str
    #: Which entry of ``Feed.symbols`` it reads, and the source recorded in
    #: storage - so the same venue lands in the same series whichever
    #: transport fetched it.
    feed_key: str
    #: True when the provider pushes updates instead of answering polls.
    streaming: bool = False

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._unavailable: set[str] = set()

    def keys(self, feeds: Sequence[Feed]) -> list[QuoteKey]:
        return [
            QuoteKey(self.feed_key, feed.name, symbol)
            for feed in feeds
            for symbol in feed.for_source(self.feed_key)
        ]

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None

    async def prepare(self, keys: Sequence[QuoteKey], sink: QuoteSink | None = None) -> None:
        """Called once with every symbol before the first read."""

    async def quote(self, symbol: Symbol) -> Quote | None:
        raise NotImplementedError

    def drain_pushed(self) -> WriteResult:
        """Writes this source made on its own since the last call."""
        return WriteResult()

    def _note_unavailable(self, symbol: Symbol, reason: str) -> None:
        """Log a symbol the provider does not carry - once, not every tick."""
        if symbol.full not in self._unavailable:
            self._unavailable.add(symbol.full)
            log.warning("%s has no quote for %s (%s)", self.name, symbol.full, reason)


class TradingViewQuotes(QuoteSource):
    """Streaming bid/ask over TradingView's quote websocket.

    One connection serves every symbol. The reader task merges each ``qsd``
    update into a per-symbol field map and hands it straight to the sink, so
    storage tracks the market rather than the polling clock. Sampling the cache
    (``quote()``) is then free - no network involved.
    """

    name = "tradingview"
    feed_key = TRADINGVIEW
    streaming = True

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self._stack: AsyncExitStack | None = None
        self._ws: Any = None
        self._session = ""
        self._reader: asyncio.Task[None] | None = None
        self._sink: QuoteSink | None = None
        self._keys: dict[str, QuoteKey] = {}
        self._fields: dict[str, dict[str, Any]] = {}
        self._ready: dict[str, asyncio.Event] = {}
        self._failed: set[str] = set()
        self._pushed = WriteResult()
        self._lock = asyncio.Lock()

    # -- connection ---------------------------------------------------------

    async def __aenter__(self) -> Self:
        await self._connect()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self._disconnect()

    async def _connect(self) -> None:
        stack = AsyncExitStack()
        try:
            client = await stack.enter_async_context(
                httpx.AsyncClient(
                    headers={
                        "Origin": self.settings.tv_origin,
                        "User-Agent": self.settings.user_agent,
                    },
                    timeout=httpx.Timeout(self.settings.tv_connect_timeout),
                )
            )
            ws = await stack.enter_async_context(
                aconnect_ws(
                    self.settings.tv_ws_url,
                    client,
                    max_message_size_bytes=MAX_MESSAGE_BYTES,
                    # TradingView drives its own ~h~ heartbeat.
                    keepalive_ping_interval_seconds=None,
                )
            )
        except Exception:
            await stack.aclose()
            raise

        self._stack, self._ws = stack, ws
        self._session = session_id("qs_")
        await ws.send_text(message("set_auth_token", [self.settings.tv_auth_token]))
        await ws.send_text(message("quote_create_session", [self._session]))
        await ws.send_text(message("quote_set_fields", [self._session, *QUOTE_FIELDS]))
        self._reader = asyncio.create_task(self._read(), name="tv-quotes-reader")

    async def _disconnect(self) -> None:
        reader, self._reader = self._reader, None
        if reader is not None:
            reader.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await reader
        stack, self._stack = self._stack, None
        self._ws = None
        if stack is not None:
            with suppress(Exception):
                await stack.aclose()

    async def _ensure_live(self) -> None:
        """Reconnect and resubscribe if the reader died."""
        if self._reader is not None and not self._reader.done():
            return
        log.warning("tradingview quote socket dropped; reconnecting")
        await self._disconnect()
        self._ready.clear()
        await self._connect()
        if self._keys:
            await self._subscribe(list(self._keys))

    # -- subscription -------------------------------------------------------

    async def prepare(self, keys: Sequence[QuoteKey], sink: QuoteSink | None = None) -> None:
        self._sink = sink
        async with self._lock:
            await self._ensure_live()
            fresh = [key.symbol.full for key in keys if key.symbol.full not in self._keys]
            for key in keys:
                self._keys[key.symbol.full] = key
            if fresh:
                await self._subscribe(fresh)
        await self._await_first([k.symbol.full for k in keys], timeout=self.settings.quote_timeout)

    async def _subscribe(self, names: Sequence[str]) -> None:
        for name in names:
            self._ready.setdefault(name, asyncio.Event())
        # One frame for the whole watchlist rather than one per symbol.
        await self._ws.send_text(message("quote_add_symbols", [self._session, *names]))

    async def _await_first(self, names: Sequence[str], timeout: float) -> None:
        waits = [self._ready[n].wait() for n in names if n in self._ready]
        if not waits:
            return
        with suppress(TimeoutError):
            await asyncio.wait_for(asyncio.gather(*waits), timeout)

    # -- reading ------------------------------------------------------------

    async def _read(self) -> None:
        while True:
            raw = await self._ws.receive_text()
            for payload in decode(raw):
                if payload.startswith("~h~"):
                    await self._ws.send_text(encode(payload))
                    continue
                try:
                    obj = orjson.loads(payload)
                except orjson.JSONDecodeError:
                    continue
                if isinstance(obj, dict) and obj.get("m") == "qsd":
                    await self._on_update(obj.get("p"))

    async def _on_update(self, params: Any) -> None:
        if not isinstance(params, list) or len(params) < 2:
            return
        data = params[1]
        if not isinstance(data, dict):
            return
        name = data.get("n")
        if not isinstance(name, str):
            return

        if data.get("s") == "error":
            self._failed.add(name)
            self._wake(name)
            return

        values = data.get("v")
        if not isinstance(values, dict):
            return
        # Updates are partial - a tick may carry only the fields that moved.
        merged = self._fields.setdefault(name, {})
        merged.update(values)
        if not any(field in values for field in ("bid", "ask", "lp")):
            return
        self._wake(name)

        quote = parse_quote(merged, now=time.time())
        key = self._keys.get(name)
        if quote is None or key is None or self._sink is None:
            return
        # The store drops repeats, so this writes only genuine moves.
        self._pushed += await self._sink(key, quote)

    def _wake(self, name: str) -> None:
        event = self._ready.get(name)
        if event is not None:
            event.set()

    # -- reading the cache --------------------------------------------------

    async def quote(self, symbol: Symbol) -> Quote | None:
        name = symbol.full
        if name not in self._keys:
            # A symbol nobody prepared - subscribe now and wait for the first tick.
            async with self._lock:
                await self._ensure_live()
                if name not in self._keys:
                    self._keys[name] = QuoteKey(self.feed_key, "", symbol)
                    await self._subscribe([name])
            await self._await_first([name], timeout=self.settings.quote_timeout)

        if name in self._failed:
            self._note_unavailable(symbol, "quote_error")
            return None
        fields = self._fields.get(name)
        if not fields:
            return None
        return parse_quote(fields, now=time.time())

    def drain_pushed(self) -> WriteResult:
        out, self._pushed = self._pushed, WriteResult()
        return out


class TradingViewScannerQuotes(QuoteSource):
    """Bid/ask from the keyless scanner endpoint. Request/response, so polled."""

    name = "scanner"
    feed_key = TRADINGVIEW

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> Self:
        self._client = httpx.AsyncClient(
            headers={"User-Agent": self.settings.user_agent},
            timeout=httpx.Timeout(self.settings.quote_timeout),
            limits=httpx.Limits(max_connections=self.settings.quote_concurrency * 2),
        )
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        client, self._client = self._client, None
        if client is not None:
            await client.aclose()

    async def quote(self, symbol: Symbol) -> Quote | None:
        if self._client is None:
            raise RuntimeError("quote source is not open")
        try:
            response = await self._client.get(
                SCANNER_URL, params={"symbol": symbol.full, "fields": SCANNER_FIELDS}
            )
        except httpx.HTTPError as exc:
            log.debug("scanner request failed for %s: %s", symbol.full, exc)
            return None

        if response.status_code == httpx.codes.NOT_FOUND:
            # The scanner does not carry every venue TradingView charts.
            self._note_unavailable(symbol, "symbol_not_exists - try --source tradingview")
            return None
        if response.status_code != httpx.codes.OK:
            log.debug("scanner returned %s for %s", response.status_code, symbol.full)
            return None
        try:
            return parse_quote(response.json(), now=time.time())
        except ValueError:
            return None


class YahooQuotes(QuoteSource):
    """Last trade and previous close from Yahoo. No real book for FX or futures."""

    name = YAHOO
    feed_key = YAHOO

    async def __aenter__(self) -> Self:
        import yfinance  # noqa: F401

        return self

    async def quote(self, symbol: Symbol) -> Quote | None:
        return await asyncio.to_thread(self._quote, symbol)

    def _quote(self, symbol: Symbol) -> Quote | None:
        import yfinance as yf

        try:
            info = yf.Ticker(symbol.ticker).fast_info
            last = _number(info.get("lastPrice"))
            previous = _number(info.get("previousClose"))
        except Exception as exc:  # yfinance raises a grab bag of types
            self._note_unavailable(symbol, str(exc)[:60])
            return None

        if last is None:
            return None
        change = None if previous is None else last - previous
        return Quote(
            time=time.time(),
            bid=_number(info.get("bid")),
            ask=_number(info.get("ask")),
            last=last,
            volume=_number(info.get("lastVolume")),
            change=change,
            change_pct=None if not previous or change is None else change / previous * 100,
        )


class BrokerQuotes(QuoteSource):
    """Top of book straight from the trading terminal, over the MT5 bridge.

    Every other source here is somebody else's opinion of the price. This one
    is the book we actually deal on, and that difference is worth having for
    two separate reasons.

    **Coverage.** The consensus venues carry the majors and nothing else. A
    broker offers hundreds of instruments no venue on TradingView quotes -
    synthetics above all, which have no underlying and therefore no other
    source by construction. Without this they cannot be traded here at all,
    because `structures` builds levels from quotes and there were none to
    build from.

    **Agreement with what we trade.** A level built from six venues' consensus
    and an order filled on one broker's book are answers to slightly different
    questions, and the gap between them is what `dislocation` exists to police.
    A level built from the broker's own quotes has no gap to police.

    **It polls; there is no stream.** The bridge publishes no websocket and no
    SSE - forty-seven routes, and the only `subscribe` is
    `/symbols/book/{symbol}/subscribe`, which is MT5 market *depth* and is
    still read by polling `/symbols/book/{symbol}`. So this is a poller, and
    `streaming` stays False. Worth stating plainly because "stream prices from
    the terminal" is the obvious way to describe the goal and is not what the
    transport does.

    **Off unless asked for.** Not in `DEFAULT_QUOTE_SOURCES`: it needs a bridge
    that only exists where a terminal is reachable, and a deployment without
    one should not be trying and failing on every symbol.
    """

    name = BROKER
    feed_key = BROKER
    streaming = False

    #: Read from the same variables the trading service uses, so one bridge is
    #: configured once. A deployment that can trade can quote.
    URL_VAR = "TRADING_MT5_URL"
    KEY_VAR = "TRADING_MT5_API_KEY"

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self._client: Any = None

    async def __aenter__(self) -> Self:
        import os

        import httpx

        url = os.environ.get(self.URL_VAR, "")
        if not url:
            raise RuntimeError(
                f"{self.name} quotes need {self.URL_VAR} - there is no bridge to read"
            )
        headers = {"Accept": "application/json"}
        key = os.environ.get(self.KEY_VAR, "")
        if key:
            headers["X-API-Key"] = key
        self._client = httpx.AsyncClient(base_url=url, headers=headers, timeout=10.0)
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def prepare(self, keys: Sequence[QuoteKey], sink: QuoteSink | None = None) -> None:
        """Select every symbol in the terminal before reading any of them.

        **Not optional, and silent when skipped.** MT5 only streams ticks for
        symbols in Market Watch, and an unselected one answers the tick
        endpoint with `bid 0.0, ask 0.0, time 0` - HTTP 200, well-formed, and
        empty. Measured: `Volatility 75 Index` read zero, and 51418.35/51436.01
        one second after a select. Without this the source would poll happily
        and publish nothing, which is the failure that looks like working code.

        Selection sticks for the session, so this runs once per start rather
        than per poll.
        """
        # This source has nothing to push: it writes through the caller's poll
        # like every other request/response source here.
        del sink
        if self._client is None:
            return
        picked = 0
        for key in keys:
            try:
                response = await self._client.post(f"/api/v1/symbols/select/{key.symbol.ticker}")
            except Exception as exc:  # httpx raises a family of transport errors
                self._note_unavailable(key.symbol, str(exc)[:60])
                continue
            if response.status_code != 200:
                self._note_unavailable(key.symbol, f"select: HTTP {response.status_code}")
                continue
            picked += 1
        log.info("%s selected %d of %d symbols in the terminal", self.name, picked, len(keys))

    async def quote(self, symbol: Symbol) -> Quote | None:
        if self._client is None:
            return None
        try:
            response = await self._client.get(f"/api/v1/symbols/ticks/{symbol.ticker}")
        except Exception as exc:  # httpx raises a family of transport errors
            self._note_unavailable(symbol, str(exc)[:60])
            return None
        if response.status_code != 200:
            self._note_unavailable(symbol, f"HTTP {response.status_code}")
            return None
        try:
            row = response.json()
        except ValueError:
            self._note_unavailable(symbol, "not JSON")
            return None
        if not isinstance(row, dict):
            return None

        bid, ask = _number(row.get("bid")), _number(row.get("ask"))
        if not bid or not ask:
            return None
        # The bridge's own tick time, in epoch seconds and on our clock - the
        # rates endpoint sends ISO strings but this one does not. Kept rather
        # than stamped with `time.time()` because a frozen tick time is how a
        # shut market is recognised, and overwriting it would erase exactly
        # that evidence.
        when = _number(row.get("time")) or time.time()
        return Quote(time=when, bid=bid, ask=ask, last=(bid + ask) / 2.0)


QUOTE_SOURCES: dict[str, type[QuoteSource]] = {
    TradingViewQuotes.name: TradingViewQuotes,
    TradingViewScannerQuotes.name: TradingViewScannerQuotes,
    YahooQuotes.name: YahooQuotes,
    BrokerQuotes.name: BrokerQuotes,
}

DEFAULT_QUOTE_SOURCES: tuple[str, ...] = (TradingViewQuotes.name,)


def build_quote_sources(names: Sequence[str] | None, settings: Settings) -> list[QuoteSource]:
    chosen = tuple(names) if names else DEFAULT_QUOTE_SOURCES
    unknown = [n for n in chosen if n not in QUOTE_SOURCES]
    if unknown:
        raise ValueError(
            f"unknown quote source(s): {', '.join(unknown)} (have: {', '.join(QUOTE_SOURCES)})"
        )
    return [QUOTE_SOURCES[name](settings) for name in chosen]


async def poll_once(
    sources: Sequence[QuoteSource],
    feeds: Sequence[Feed],
    *,
    concurrency: int,
    sink: QuoteSink | None = None,
) -> QuoteTick:
    """Take one snapshot across every broker.

    Streaming sources answer from their live cache and have already written
    what they saw; only request/response sources go to the network here.
    """
    started = time.monotonic()
    tick = QuoteTick()
    limit = asyncio.Semaphore(max(1, concurrency))

    async def one(source: QuoteSource, key: QuoteKey) -> None:
        async with limit:
            quote = await source.quote(key.symbol)
        if quote is None:
            tick.missing += 1
            return
        tick.quotes[key] = quote
        if sink is None or source.streaming:
            return
        # Bind the result before accumulating: `x += await f()` loads x
        # *before* suspending, so concurrent tasks lose each other's writes.
        written = await sink(key, quote)
        tick.written += written

    async with asyncio.TaskGroup() as group:
        for source in sources:
            for key in source.keys(feeds):
                group.create_task(one(source, key))

    for source in sources:
        tick.pushed += source.drain_pushed()

    tick.elapsed = time.monotonic() - started
    return tick


async def stream(
    *,
    settings: Settings,
    feeds: Sequence[Feed],
    sink: QuoteSink | None = None,
    sources: Sequence[str] | None = None,
    ticks: int | None = None,
    on_tick: Callable[[int, QuoteTick], None] | None = None,
    bus: Bus | None = None,
) -> None:
    """Keep quotes flowing until `ticks` snapshots have been taken (or forever).

    With a streaming source, writes happen on push between snapshots;
    ``quote_poll_seconds`` only sets how often the caller gets a summary and
    how often request/response sources are re-polled.
    """
    if bus is not None:
        sink = publishing(sink, bus)
    count = 0
    async with AsyncExitStack() as stack:
        live: list[QuoteSource] = []
        for source in build_quote_sources(sources, settings):
            try:
                live.append(await stack.enter_async_context(source))
            except Exception as exc:
                log.error("quote source %s unavailable: %s", source.name, exc)

        for source in live:
            await source.prepare(source.keys(feeds), sink)

        while ticks is None or count < ticks:
            started = time.monotonic()
            tick = await poll_once(live, feeds, concurrency=settings.quote_concurrency, sink=sink)
            count += 1
            if on_tick is not None:
                on_tick(count, tick)
            if ticks is not None and count >= ticks:
                return
            await asyncio.sleep(
                max(0.0, settings.quote_poll_seconds - (time.monotonic() - started))
            )
