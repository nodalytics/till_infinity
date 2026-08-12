"""Feeds, calendar coverage and runtime settings.

Env vars are read with a ``NEWS_`` prefix.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

#: RSS feeds. Macro/FX first, then crypto — the mix the gold/BTC/FX book needs.
RSS_FEEDS: dict[str, str] = {
    "forexlive": "https://www.forexlive.com/feed/",
    "fxstreet": "https://www.fxstreet.com/rss/news",
    "investing": "https://www.investing.com/rss/news.rss",
    "coindesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "cointelegraph": "https://cointelegraph.com/rss",
}

#: Countries worth watching for instruments priced in USD, EUR and GBP.
#: TradingView wants ISO-2; ForexFactory reports currency codes instead.
CALENDAR_COUNTRIES: tuple[str, ...] = ("US", "EU", "GB", "DE", "JP", "CH", "CA", "AU", "CN")

#: ForexFactory tags events with the currency, so filtering happens on these.
CALENDAR_CURRENCIES: tuple[str, ...] = ("USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "CNY")

#: Symbols to pull TradingView headlines for. Same instruments as prices.
HEADLINE_SYMBOLS: tuple[str, ...] = (
    "OANDA:XAUUSD",
    "OANDA:EURUSD",
    "OANDA:GBPUSD",
    "BINANCE:BTCUSDT",
)

#: Broad feeds, fetched without a symbol.
HEADLINE_CATEGORIES: tuple[str, ...] = ("forex", "crypto")

#: Only the current week is published any more — ff_calendar_nextweek.json and
#: ff_calendar_lastweek.json both 404. TradingView covers the forward window.
FOREXFACTORY_URLS: tuple[str, ...] = ("https://nfs.faireconomy.media/ff_calendar_thisweek.json",)

TRADINGVIEW_CALENDAR_URL = "https://economic-calendar.tradingview.com/events"
TRADINGVIEW_HEADLINES_URL = "https://news-headlines.tradingview.com/v2/headlines"

DEFAULT_DATA_DIR = ".data/news"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
#: TradingView's calendar and headline services check the browser origin.
TRADINGVIEW_ORIGIN = "https://www.tradingview.com"

#: IMF SDMX. Country codes are ISO-3 — "US" matches nothing, "USA" does.
IMF_BASE_URL = "https://api.imf.org/external/sdmx/2.1"
#: International Reserves and Foreign Currency Liquidity. The "+" resolves to
#: the latest version, which moves (12.0.0 at time of writing).
IMF_FLOW = "IMF.STA,IRFCL,+"
IMF_COUNTRIES: tuple[str, ...] = ("USA", "GBR", "JPN", "CHN", "DEU", "CHE")
IMF_FREQUENCY = "M"
#: Reserves are monthly and revised slowly, so only a short window is re-pulled.
IMF_MONTHS_BACK = 18

DEFAULT_SOURCES: tuple[str, ...] = ("rss", "forexfactory", "tradingview", "headlines", "imf")


def _env(name: str) -> str | None:
    return os.environ.get(name) or None


def _env_int(default: int, name: str) -> int:
    raw = _env(name)
    return int(raw) if raw else default


def _env_float(default: float, name: str) -> float:
    raw = _env(name)
    return float(raw) if raw else default


@dataclass(slots=True)
class Settings:
    """Everything tunable, resolved once and threaded through the service."""

    data_dir: Path = field(default_factory=lambda: Path(DEFAULT_DATA_DIR))
    database: Path | None = None

    #: Headlines move fast; the calendar barely moves until a print lands.
    news_poll_seconds: float = 300.0
    calendar_poll_seconds: float = 900.0

    #: How far the calendar window reaches, in days either side of now.
    calendar_back_days: int = 3
    calendar_forward_days: int = 14

    concurrency: int = 6
    timeout: float = 20.0
    retries: int = 3
    headline_limit: int = 30
    imf_countries: tuple[str, ...] = IMF_COUNTRIES
    user_agent: str = DEFAULT_USER_AGENT

    def __post_init__(self) -> None:
        self.data_dir = Path(self.data_dir)
        if self.database is None:
            self.database = self.data_dir / "news.db"
        else:
            self.database = Path(self.database)

    @classmethod
    def from_env(cls) -> Settings:
        db = _env("NEWS_DB")
        return cls(
            data_dir=Path(_env("NEWS_DIR") or DEFAULT_DATA_DIR),
            database=Path(db) if db else None,
            news_poll_seconds=_env_float(300.0, "NEWS_POLL"),
            calendar_poll_seconds=_env_float(900.0, "NEWS_CAL_POLL"),
            calendar_back_days=_env_int(3, "NEWS_CAL_BACK_DAYS"),
            calendar_forward_days=_env_int(14, "NEWS_CAL_FORWARD_DAYS"),
            concurrency=_env_int(6, "NEWS_CONCURRENCY"),
            retries=_env_int(3, "NEWS_RETRIES"),
            user_agent=_env("NEWS_USER_AGENT") or DEFAULT_USER_AGENT,
        )
