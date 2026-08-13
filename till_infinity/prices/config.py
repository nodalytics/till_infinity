"""Feed definitions and runtime settings.

Env vars are read with a ``PRICES_`` prefix.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .models import Symbol, slugify

TRADINGVIEW = "tradingview"
YAHOO = "yahoo"


@dataclass(frozen=True, slots=True)
class Feed:
    """One instrument, tracked across several venues per source."""

    name: str
    symbols: Mapping[str, tuple[Symbol, ...]]

    def for_source(self, source: str) -> tuple[Symbol, ...]:
        return self.symbols.get(source, ())


def _feed(name: str, *, tradingview: tuple[str, ...], yahoo: tuple[str, ...]) -> Feed:
    return Feed(
        name=name,
        symbols={
            TRADINGVIEW: tuple(Symbol.parse(s) for s in tradingview),
            YAHOO: tuple(Symbol("YAHOO", s) for s in yahoo),
        },
    )


FEEDS: dict[str, Feed] = {
    f.name: f
    for f in (
        _feed(
            "gold",
            # Spot gold is quoted per broker; TVC:GOLD is TradingView's own index.
            # Yahoo has no spot XAUUSD — GC=F (COMEX continuous) is the free stand-in.
            tradingview=(
                "OANDA:XAUUSD",
                "PEPPERSTONE:XAUUSD",
                "FOREXCOM:XAUUSD",
                "SAXO:XAUUSD",
                "TVC:GOLD",
                "DERIV:XAUUSD",
            ),
            yahoo=("GC=F",),
        ),
        _feed(
            "btc",
            tradingview=(
                "BINANCE:BTCUSDT",
                "COINBASE:BTCUSD",
                "BITSTAMP:BTCUSD",
                "KRAKEN:BTCUSD",
                "DERIV:BTCUSD",
            ),
            yahoo=("BTC-USD",),
        ),
        _feed(
            "eurusd",
            tradingview=(
                "OANDA:EURUSD",
                "PEPPERSTONE:EURUSD",
                "FOREXCOM:EURUSD",
                "SAXO:EURUSD",
                "FX_IDC:EURUSD",
                "DERIV:EURUSD",
            ),
            yahoo=("EURUSD=X",),
        ),
        _feed(
            "gbpusd",
            tradingview=(
                "OANDA:GBPUSD",
                "PEPPERSTONE:GBPUSD",
                "FOREXCOM:GBPUSD",
                "SAXO:GBPUSD",
                "FX_IDC:GBPUSD",
                "DERIV:GBPUSD",
            ),
            yahoo=("GBPUSD=X",),
        ),
        _feed(
            "us100",
            # The Nasdaq 100. Brokers quote a CFD on it under half a dozen
            # names — NAS100USD, NAS100, NSXUSD, US100 — so the venue list is
            # less uniform than for FX. SAXO, DERIV and BLACKBULL were checked
            # and do not carry it; asking anyway would log a symbol_error every
            # sweep, forever, for a symbol nobody expects to appear.
            tradingview=(
                "OANDA:NAS100USD",
                "PEPPERSTONE:NAS100",
                "FOREXCOM:NSXUSD",
                "CAPITALCOM:US100",
                "TVC:NDX",
            ),
            # ^NDX is the index itself; NQ=F is the CME continuous future, kept
            # because it trades when the cash index does not.
            yahoo=("^NDX", "NQ=F"),
        ),
        _feed(
            "spx500",
            tradingview=(
                "OANDA:SPX500USD",
                "PEPPERSTONE:US500",
                "FOREXCOM:SPXUSD",
                "CAPITALCOM:US500",
                "BLACKBULL:US500",
                "TVC:SPX",
            ),
            yahoo=("^GSPC", "ES=F"),
        ),
    )
}

DEFAULT_SOURCES: tuple[str, ...] = (TRADINGVIEW, YAHOO)

#: Tracked unless the caller names something else.
DEFAULT_SYMBOLS: tuple[str, ...] = ("eurusd", "gbpusd", "gold", "btc", "us100", "spx500")

#: What people actually type, mapped to the feed it means.
SYMBOL_ALIASES: dict[str, str] = {
    # Indices go by more names than anything else here, and every one of them
    # is what somebody calls it first.
    "us100": "us100",
    "nas100": "us100",
    "nasdaq": "us100",
    "nasdaq100": "us100",
    "ndx": "us100",
    "nq": "us100",
    "spx500": "spx500",
    "spx": "spx500",
    "us500": "spx500",
    "sp500": "spx500",
    "s&p500": "spx500",
    "sandp": "spx500",
    "gspc": "spx500",
    "es": "spx500",
    "xauusd": "gold",
    "xau": "gold",
    "gold": "gold",
    "btc": "btc",
    "btcusd": "btc",
    "btcusdt": "btc",
    "bitcoin": "btc",
    "eur": "eurusd",
    "eurusd": "eurusd",
    "gbp": "gbpusd",
    "gbpusd": "gbpusd",
}


def resolve_feeds(names: Sequence[str] | None) -> tuple[Feed, ...]:
    """Look feeds up by their configured name."""
    if not names:
        return tuple(FEEDS[n] for n in DEFAULT_SYMBOLS)
    unknown = [n for n in names if n not in FEEDS]
    if unknown:
        raise ValueError(f"unknown feed(s): {', '.join(unknown)} (have: {', '.join(FEEDS)})")
    return tuple(FEEDS[n] for n in names)


def resolve_symbols(values: Sequence[str] | None) -> tuple[Feed, ...]:
    """Turn whatever the caller typed into feeds.

    Three forms are accepted, and they mix freely:

    * a tracked instrument — ``gold``, ``xauusd``, ``btc``, ``eurusd`` — which
      brings along every broker configured for it;
    * ``VENUE:TICKER`` (``OANDA:XAUUSD``, ``YAHOO:GC=F``) for one exact series;
    * a bare ticker (``AAPL``, ``BTC-USD``), which goes to Yahoo — TradingView
      needs the venue to resolve a symbol.

    With nothing passed, the defaults are EURUSD, GBPUSD, gold and BTC.
    """
    if not values:
        return resolve_feeds(None)

    merged: dict[str, Feed] = {}
    for raw in values:
        feed = _as_feed(raw.strip())
        existing = merged.get(feed.name)
        merged[feed.name] = _merge(existing, feed) if existing else feed
    return tuple(merged.values())


def _as_feed(raw: str) -> Feed:
    if not raw:
        raise ValueError("empty symbol")

    known = FEEDS.get(raw.lower()) or FEEDS.get(SYMBOL_ALIASES.get(raw.lower(), ""))
    if known is not None:
        return known

    venue, sep, ticker = raw.partition(":")
    if sep and ticker:
        if venue.upper() == "YAHOO":
            symbol, source = Symbol("YAHOO", ticker), YAHOO
        else:
            symbol, source = Symbol(venue.upper(), ticker.upper()), TRADINGVIEW
    else:
        # No venue to resolve against, so Yahoo is the only source that can serve it.
        symbol, source = Symbol("YAHOO", raw), YAHOO

    return Feed(name=slugify(symbol.ticker).lower(), symbols={source: (symbol,)})


def _merge(left: Feed, right: Feed) -> Feed:
    symbols = {source: tuple(syms) for source, syms in left.symbols.items()}
    for source, syms in right.symbols.items():
        combined = list(symbols.get(source, ()))
        combined.extend(s for s in syms if s not in combined)
        symbols[source] = tuple(combined)
    return Feed(name=left.name, symbols=symbols)


def _env(name: str) -> str | None:
    return os.environ.get(name) or None


def _env_int(default: int, name: str) -> int:
    raw = _env(name)
    return int(raw) if raw else default


def _env_float(default: float, name: str) -> float:
    raw = _env(name)
    return float(raw) if raw else default


DEFAULT_DATA_DIR = ".data/prices"
DEFAULT_TV_WS_URL = "wss://data.tradingview.com/socket.io/websocket"
DEFAULT_TV_ORIGIN = "https://data.tradingview.com"
DEFAULT_TV_TOKEN = "unauthorized_user_token"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


@dataclass(slots=True)
class Settings:
    """Everything tunable, resolved once and threaded through the service.

    Defaults live in the module constants above, not as class attributes:
    ``slots=True`` turns every class attribute into a slot descriptor, so
    ``Settings.tv_origin`` is a descriptor rather than the string.
    """

    data_dir: Path = field(default_factory=lambda: Path(DEFAULT_DATA_DIR))
    database: Path | None = None

    backfill_bars: int = 5_000
    live_bars: int = 300
    cycle_seconds: float = 60.0
    include_partial: bool = False

    # TradingView socket
    tv_concurrency: int = 6
    tv_ws_url: str = DEFAULT_TV_WS_URL
    tv_origin: str = DEFAULT_TV_ORIGIN
    tv_auth_token: str = DEFAULT_TV_TOKEN
    tv_connect_timeout: float = 20.0
    tv_recv_timeout: float = 15.0
    tv_fetch_timeout: float = 60.0
    tv_max_pages: int = 8
    tv_request_gap: float = 0.25

    # Yahoo (yfinance is blocking; it runs in a thread pool)
    yahoo_concurrency: int = 4
    yahoo_request_gap: float = 0.2

    # Realtime bid/ask polling
    quote_poll_seconds: float = 15.0
    quote_concurrency: int = 8
    quote_timeout: float = 10.0
    quote_dedupe: bool = True

    retries: int = 3
    user_agent: str = DEFAULT_USER_AGENT

    def __post_init__(self) -> None:
        self.data_dir = Path(self.data_dir)
        if self.database is None:
            self.database = self.data_dir / "prices.db"
        else:
            self.database = Path(self.database)

    @classmethod
    def from_env(cls) -> Settings:
        data_dir = Path(_env("PRICES_DIR") or DEFAULT_DATA_DIR)
        db = _env("PRICES_DB")
        return cls(
            data_dir=data_dir,
            database=Path(db) if db else None,
            backfill_bars=_env_int(5_000, "PRICES_BACKFILL_BARS"),
            live_bars=_env_int(300, "PRICES_LIVE_BARS"),
            cycle_seconds=_env_float(60.0, "PRICES_CYCLE_S"),
            tv_concurrency=_env_int(6, "PRICES_TV_CONCURRENCY"),
            tv_ws_url=_env("PRICES_TV_WS_URL") or DEFAULT_TV_WS_URL,
            tv_origin=_env("PRICES_TV_ORIGIN") or DEFAULT_TV_ORIGIN,
            tv_auth_token=_env("PRICES_TV_TOKEN") or DEFAULT_TV_TOKEN,
            yahoo_concurrency=_env_int(4, "PRICES_YAHOO_CONCURRENCY"),
            quote_poll_seconds=_env_float(15.0, "PRICES_QUOTE_POLL"),
            quote_concurrency=_env_int(8, "PRICES_QUOTE_CONCURRENCY"),
            retries=_env_int(3, "PRICES_RETRIES"),
            user_agent=_env("PRICES_USER_AGENT") or DEFAULT_USER_AGENT,
        )
