"""Feed definitions and runtime settings.

Env vars are read with a ``PRICES_`` prefix.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from ..logging import get_logger
from .models import Symbol, slugify

log = get_logger(__name__)

TRADINGVIEW = "tradingview"
YAHOO = "yahoo"
#: The trading terminal's own book, over the MT5 bridge. Off unless asked for -
#: see `BrokerQuotes` and `broker_feeds`.
BROKER = "broker"


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


def broker_feeds(names: Sequence[str]) -> dict[str, Feed]:
    """Feeds for instruments only the broker carries, keyed by a slug.

    The point of these is the instruments no consensus venue quotes -
    synthetics above all, which have no underlying and so no other source by
    construction. Without a feed they cannot be traded here at all, because
    `structures` builds levels out of quotes and there are none.

    The broker's own name is the symbol, verbatim: `Volatility 75 Index`, not a
    guess at what it might be called elsewhere. The feed name is a slug of it,
    because feed names travel through journal keys and log lines where spaces
    are a nuisance. Nothing is resolved or probed here - a name the broker does
    not carry simply never quotes, and `_note_unavailable` says so once.
    """
    made: dict[str, Feed] = {}
    for raw in names:
        symbol = raw.strip()
        if not symbol:
            continue
        slug = slugify(symbol).lower()
        if not slug or slug in made:
            continue
        made[slug] = Feed(
            name=slug,
            symbols={BROKER: (Symbol(BROKER.upper(), symbol),)},
        )
    return made


FEEDS: dict[str, Feed] = {
    f.name: f
    for f in (
        _feed(
            "gold",
            # Spot gold is quoted per broker; TVC:GOLD is TradingView's own index.
            # Yahoo has no spot XAUUSD - GC=F (COMEX continuous) is the free stand-in.
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
            "silver",
            # Spot silver, quoted per broker exactly as gold is. Yahoo has no
            # spot XAGUSD either, so SI=F (COMEX continuous) is the same
            # free stand-in GC=F is for gold.
            tradingview=(
                "OANDA:XAGUSD",
                "PEPPERSTONE:XAGUSD",
                "FOREXCOM:XAGUSD",
                "SAXO:XAGUSD",
                "TVC:SILVER",
                "DERIV:XAGUSD",
            ),
            yahoo=("SI=F",),
        ),
        _feed(
            "btc",
            # Bybit is quoted on the USDT pair for all three of BTC, ETH and
            # SOL. It carries BYBIT:BTCUSD and BYBIT:ETHUSD as well, but not
            # BYBIT:SOLUSD - checked, it returns symbol_error - so the USDT
            # form is the one that is uniform across the crypto feeds.
            tradingview=(
                "BINANCE:BTCUSDT",
                "BYBIT:BTCUSDT",
                "COINBASE:BTCUSD",
                "BITSTAMP:BTCUSD",
                "KRAKEN:BTCUSD",
                "DERIV:BTCUSD",
            ),
            yahoo=("BTC-USD",),
        ),
        # ETH and SOL take the same venue list as BTC, and every one of the ten
        # was checked against the live socket before being added rather than
        # assumed from the BTC set - the cost of guessing wrong here is a
        # symbol_error every sweep, forever, exactly as noted under us100.
        # DERIV was the doubtful one and does carry both.
        _feed(
            "eth",
            tradingview=(
                "BINANCE:ETHUSDT",
                "BYBIT:ETHUSDT",
                "COINBASE:ETHUSD",
                "BITSTAMP:ETHUSD",
                "KRAKEN:ETHUSD",
                "DERIV:ETHUSD",
            ),
            yahoo=("ETH-USD",),
        ),
        _feed(
            "sol",
            tradingview=(
                "BINANCE:SOLUSDT",
                "BYBIT:SOLUSDT",
                "COINBASE:SOLUSD",
                "BITSTAMP:SOLUSD",
                "KRAKEN:SOLUSD",
                "DERIV:SOLUSD",
            ),
            yahoo=("SOL-USD",),
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
        # The rest of the majors. One venue list, because every one of these is
        # quoted by all six brokers - checked, not assumed.
        _feed(
            "usdjpy",
            tradingview=(
                "OANDA:USDJPY",
                "PEPPERSTONE:USDJPY",
                "FOREXCOM:USDJPY",
                "SAXO:USDJPY",
                "FX_IDC:USDJPY",
                "DERIV:USDJPY",
            ),
            yahoo=("JPY=X",),
        ),
        _feed(
            "audusd",
            tradingview=(
                "OANDA:AUDUSD",
                "PEPPERSTONE:AUDUSD",
                "FOREXCOM:AUDUSD",
                "SAXO:AUDUSD",
                "FX_IDC:AUDUSD",
                "DERIV:AUDUSD",
            ),
            yahoo=("AUDUSD=X",),
        ),
        _feed(
            "usdcad",
            tradingview=(
                "OANDA:USDCAD",
                "PEPPERSTONE:USDCAD",
                "FOREXCOM:USDCAD",
                "SAXO:USDCAD",
                "FX_IDC:USDCAD",
                "DERIV:USDCAD",
            ),
            yahoo=("CAD=X",),
        ),
        _feed(
            "usdchf",
            tradingview=(
                "OANDA:USDCHF",
                "PEPPERSTONE:USDCHF",
                "FOREXCOM:USDCHF",
                "SAXO:USDCHF",
                "FX_IDC:USDCHF",
                "DERIV:USDCHF",
            ),
            yahoo=("CHF=X",),
        ),
        _feed(
            "nzdusd",
            tradingview=(
                "OANDA:NZDUSD",
                "PEPPERSTONE:NZDUSD",
                "FOREXCOM:NZDUSD",
                "SAXO:NZDUSD",
                "FX_IDC:NZDUSD",
                "DERIV:NZDUSD",
            ),
            yahoo=("NZDUSD=X",),
        ),
        _feed(
            "usdcnh",
            # The **offshore** yuan, and that is deliberate. Onshore USDCNY is
            # carried by exactly one of our venues (FX_IDC) - OANDA, SAXO,
            # FOREXCOM and DERIV all return symbol_error for it - which is
            # below the three-venue quorum a consensus bar needs, so a `usdcny`
            # feed would form no levels at all and do it silently. CNH is the
            # rate that trades outside the mainland's daily band, all six
            # venues quote it, and `usdcny` is an alias onto it.
            tradingview=(
                "OANDA:USDCNH",
                "PEPPERSTONE:USDCNH",
                "FOREXCOM:USDCNH",
                "SAXO:USDCNH",
                "FX_IDC:USDCNH",
                "DERIV:USDCNH",
            ),
            yahoo=("CNH=X",),
        ),
        _feed(
            "us100",
            # The Nasdaq 100. Brokers quote a CFD on it under half a dozen
            # names - NAS100USD, NAS100, NSXUSD, US100 - so the venue list is
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
        _feed(
            "ger40",
            # The DAX. Every venue here was checked and quoting before it was
            # added - a dead symbol logs a skip on every sweep, forever, and
            # the list is otherwise indistinguishable from a working one.
            #
            # Quoted in euros, not dollars, which is the point of carrying it:
            # it is the first index here whose second leg is not USD.
            tradingview=(
                "OANDA:DE30EUR",
                "PEPPERSTONE:GER40",
                "FOREXCOM:GRXEUR",
                "CAPITALCOM:DE40",
                "BLACKBULL:GER40",
                "TVC:DAX",
            ),
            # ^GDAXI is the index itself. There is no free DAX future on
            # Yahoo - FDAX=F does not resolve - so unlike us100 and spx500
            # this one has no out-of-hours companion series.
            yahoo=("^GDAXI",),
        ),
        _feed(
            "uk100",
            # The FTSE 100, quoted in sterling. Same reasoning as ger40.
            tradingview=(
                "OANDA:UK100GBP",
                "PEPPERSTONE:UK100",
                "FOREXCOM:UKXGBP",
                "CAPITALCOM:UK100",
                "BLACKBULL:UK100",
                "TVC:UKX",
            ),
            yahoo=("^FTSE",),
        ),
        _feed(
            "us30",
            # The Dow. Quoted tighter than gold on the account this was
            # measured against - 0.28bps - which makes it the most liquid
            # instrument here, not a diversifier.
            tradingview=(
                "OANDA:US30USD",
                "PEPPERSTONE:US30",
                "FOREXCOM:DJI",
                "CAPITALCOM:US30",
                "BLACKBULL:US30",
                "TVC:DJI",
            ),
            yahoo=("^DJI", "YM=F"),
        ),
        _feed(
            "us2000",
            # The Russell 2000. Small caps, so it diverges from the other US
            # indices more often than they diverge from each other.
            tradingview=(
                "OANDA:US2000USD",
                "PEPPERSTONE:US2000",
                "CAPITALCOM:RTY",
                "TVC:RUT",
            ),
            yahoo=("^RUT", "RTY=F"),
        ),
        _feed(
            "jp225",
            # The Nikkei, quoted in yen. One of the few indices whose second
            # leg is neither the dollar nor the euro.
            tradingview=(
                "OANDA:JP225USD",
                "PEPPERSTONE:JPN225",
                "FOREXCOM:JPXJPY",
                "CAPITALCOM:J225",
                "TVC:NI225",
            ),
            yahoo=("^N225", "NIY=F"),
        ),
        _feed(
            "fra40",
            tradingview=(
                "OANDA:FR40EUR",
                "PEPPERSTONE:FRA40",
                "CAPITALCOM:FR40",
                "FOREXCOM:FRXEUR",
                "TVC:CAC40",
            ),
            yahoo=("^FCHI",),
        ),
        _feed(
            "eu50",
            tradingview=(
                "OANDA:EU50EUR",
                "PEPPERSTONE:EUSTX50",
                "CAPITALCOM:EU50",
                "TVC:SX5E",
            ),
            yahoo=("^STOXX50E",),
        ),
        _feed(
            "aus200",
            # Three venues, which is exactly the consensus quorum. One of them
            # going quiet leaves this instrument with no cross-venue check at
            # all - the fail-open that `trading.spreads` now covers.
            tradingview=(
                "OANDA:AU200AUD",
                "PEPPERSTONE:AUS200",
                "CAPITALCOM:AU200",
            ),
            yahoo=("^AXJO",),
        ),
        _feed(
            "hk50",
            tradingview=(
                "OANDA:HK33HKD",
                "PEPPERSTONE:HK50",
                "CAPITALCOM:HK50",
                "FOREXCOM:HKXHKD",
                "TVC:HSI",
            ),
            yahoo=("^HSI",),
        ),
        _feed(
            "wti",
            # Energy, which is the one driver nothing else here carries.
            #
            # **FOREXCOM quotes oil in cents.** `FOREXCOM:USOIL` ran 8047-8397
            # against 80-85 everywhere else, and `FOREXCOM:UKOIL` 8516-8891
            # against 85-92 - a clean factor of 100, in 70,402 stored wti
            # quotes and 61,924 brent ones. A venue on a different unit is not
            # a venue with a different opinion: it drags the consensus mid,
            # makes every spread comparison meaningless and reads as a
            # permanent dislocation. Dropped rather than rescaled, because a
            # rescale is a silent lie the day they fix it.
            tradingview=(
                "OANDA:WTICOUSD",
                "CAPITALCOM:OIL_CRUDE",
                "TVC:USOIL",
            ),
            yahoo=("CL=F",),
        ),
        _feed(
            "brent",
            # `FOREXCOM:UKOIL` dropped for the reason `wti` gives above.
            tradingview=(
                "OANDA:BCOUSD",
                "CAPITALCOM:OIL_BRENT",
                "TVC:UKOIL",
            ),
            yahoo=("BZ=F",),
        ),
        # The crosses. Every one of these has **no dollar leg**, which is the
        # reason to carry them: everything else here is long or short the
        # dollar by construction, so a book of majors and metals is one trade
        # wearing several tickets. See `trading.exposure`.
        _feed(
            "eurgbp",
            tradingview=(
                "OANDA:EURGBP",
                "PEPPERSTONE:EURGBP",
                "FOREXCOM:EURGBP",
                "CAPITALCOM:EURGBP",
                "FX_IDC:EURGBP",
                "SAXO:EURGBP",
            ),
            yahoo=("EURGBP=X",),
        ),
        _feed(
            "eurjpy",
            tradingview=(
                "OANDA:EURJPY",
                "PEPPERSTONE:EURJPY",
                "FOREXCOM:EURJPY",
                "CAPITALCOM:EURJPY",
                "FX_IDC:EURJPY",
                "SAXO:EURJPY",
            ),
            yahoo=("EURJPY=X",),
        ),
        _feed(
            "gbpjpy",
            tradingview=(
                "OANDA:GBPJPY",
                "PEPPERSTONE:GBPJPY",
                "FOREXCOM:GBPJPY",
                "CAPITALCOM:GBPJPY",
                "FX_IDC:GBPJPY",
                "SAXO:GBPJPY",
            ),
            yahoo=("GBPJPY=X",),
        ),
        _feed(
            "eurchf",
            tradingview=(
                "OANDA:EURCHF",
                "PEPPERSTONE:EURCHF",
                "FOREXCOM:EURCHF",
                "CAPITALCOM:EURCHF",
                "FX_IDC:EURCHF",
                "SAXO:EURCHF",
            ),
            yahoo=("EURCHF=X",),
        ),
        _feed(
            "audjpy",
            tradingview=(
                "OANDA:AUDJPY",
                "PEPPERSTONE:AUDJPY",
                "FOREXCOM:AUDJPY",
                "CAPITALCOM:AUDJPY",
                "FX_IDC:AUDJPY",
                "SAXO:AUDJPY",
            ),
            yahoo=("AUDJPY=X",),
        ),
        _feed(
            "chfjpy",
            tradingview=(
                "OANDA:CHFJPY",
                "PEPPERSTONE:CHFJPY",
                "FOREXCOM:CHFJPY",
                "CAPITALCOM:CHFJPY",
                "FX_IDC:CHFJPY",
                "SAXO:CHFJPY",
            ),
            yahoo=("CHFJPY=X",),
        ),
        _feed(
            "euraud",
            tradingview=(
                "OANDA:EURAUD",
                "PEPPERSTONE:EURAUD",
                "FOREXCOM:EURAUD",
                "CAPITALCOM:EURAUD",
                "FX_IDC:EURAUD",
                "SAXO:EURAUD",
            ),
            yahoo=("EURAUD=X",),
        ),
    )
}

DEFAULT_SOURCES: tuple[str, ...] = (TRADINGVIEW, YAHOO)

#: Bars kept per series when retention runs.
#:
#: **Sized against the data rather than against a formula**, which the first
#: version was not: it took four times the level engine's 500-bar window and
#: landed on 2,000, comfortably above every series that actually exists. The
#: largest on production held 1,733 bars and the average 602, so retention as
#: first shipped would have deleted precisely nothing while reporting success.
#:
#: 1,000 is what the seed needs with room to spare. `Engine.seed` reads
#: `bars * 8` rows per `(feed, interval)` - 4,000 - and those are shared across
#: the dozen venue-and-source series that make up one instrument's timeframe,
#: so each needs on the order of 333. Three times that is margin enough for a
#: feed whose venues report unevenly, and it removes about a fifth of the table
#: today, rising as history accumulates.
#:
#: The coupling to `structures` is written down rather than imported: prices
#: knows nothing about the models that read it, and should not start now for a
#: constant. If that window changes, this is the other number to look at.
#:
#: A count rather than a duration, and the same count for every interval - the
#: models consume a window of *bars*, and one number self-scales into roughly
#: the horizon each timeframe's evidence survives anyway: 1,000 bars is about
#: seventeen hours of 1m and about nineteen years of 1w.
DEFAULT_RETAIN_BARS = 1_000

#: Tracked unless the caller names something else.
DEFAULT_SYMBOLS: tuple[str, ...] = (
    "eurusd",
    "gbpusd",
    "usdjpy",
    "audusd",
    "usdcad",
    "usdchf",
    "nzdusd",
    "usdcnh",
    "gold",
    "silver",
    "btc",
    "eth",
    "sol",
    "us100",
    "spx500",
    "ger40",
    "uk100",
    "us30",
    "us2000",
    "jp225",
    "fra40",
    "eu50",
    "aus200",
    "hk50",
    "wti",
    "brent",
    "eurgbp",
    "eurjpy",
    "gbpjpy",
    "eurchf",
    "audjpy",
    "chfjpy",
    "euraud",
)

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
    "ger40": "ger40",
    "germany40": "ger40",
    "germany": "ger40",
    "dax": "ger40",
    "dax40": "ger40",
    "de40": "ger40",
    "de30": "ger40",
    "gdaxi": "ger40",
    "uk100": "uk100",
    "uk": "uk100",
    "ftse": "uk100",
    "ftse100": "uk100",
    "ukx": "uk100",
    "footsie": "uk100",
    "us30": "us30",
    "dow": "us30",
    "dowjones": "us30",
    "dji": "us30",
    "wallstreet": "us30",
    "ym": "us30",
    "us2000": "us2000",
    "russell": "us2000",
    "rut": "us2000",
    "jp225": "jp225",
    "nikkei": "jp225",
    "japan225": "jp225",
    "n225": "jp225",
    "fra40": "fra40",
    "cac": "fra40",
    "cac40": "fra40",
    "france40": "fra40",
    "eu50": "eu50",
    "stoxx": "eu50",
    "stoxx50": "eu50",
    "europe50": "eu50",
    "aus200": "aus200",
    "asx": "aus200",
    "asx200": "aus200",
    "australia200": "aus200",
    "hk50": "hk50",
    "hsi": "hk50",
    "hangseng": "hk50",
    "hongkong50": "hk50",
    "wti": "wti",
    "usoil": "wti",
    "crude": "wti",
    "oil": "wti",
    "cl": "wti",
    "brent": "brent",
    "ukoil": "brent",
    "bco": "brent",
    "xauusd": "gold",
    "xau": "gold",
    "gold": "gold",
    "xagusd": "silver",
    "xag": "silver",
    "silver": "silver",
    "btc": "btc",
    "btcusd": "btc",
    "btcusdt": "btc",
    "bitcoin": "btc",
    "eth": "eth",
    "ethusd": "eth",
    "ethusdt": "eth",
    "ether": "eth",
    "ethereum": "eth",
    "sol": "sol",
    "solusd": "sol",
    "solusdt": "sol",
    "solana": "sol",
    "eur": "eurusd",
    "eurusd": "eurusd",
    "gbp": "gbpusd",
    "gbpusd": "gbpusd",
    # The rest of the majors, under the desk names as well as the tickers -
    # nobody asks for USDJPY out loud.
    "jpy": "usdjpy",
    "usdjpy": "usdjpy",
    "yen": "usdjpy",
    "aud": "audusd",
    "audusd": "audusd",
    "aussie": "audusd",
    "cad": "usdcad",
    "usdcad": "usdcad",
    "loonie": "usdcad",
    "chf": "usdchf",
    "usdchf": "usdchf",
    "swissy": "usdchf",
    "franc": "usdchf",
    "nzd": "nzdusd",
    "nzdusd": "nzdusd",
    "kiwi": "nzdusd",
    # Onshore and offshore both land on CNH, which is the one our venues
    # actually quote. See the feed for why.
    "cnh": "usdcnh",
    "usdcnh": "usdcnh",
    "cny": "usdcnh",
    "usdcny": "usdcnh",
    "yuan": "usdcnh",
    "renminbi": "usdcnh",
}


def register_broker_feeds(names: Sequence[str]) -> tuple[str, ...]:
    """Add broker-only instruments to the catalogue. Returns the slugs added.

    Called at start-up from `PRICES_BROKER_SYMBOLS`, so a synthetic named there
    becomes an ordinary feed that everything downstream - quotes, storage,
    levels, signals - handles without knowing it came from anywhere unusual.

    Mutating the module catalogue is deliberate. `FEEDS` is what `resolve_feeds`
    and every alias lookup read, and a parallel registry would be a second
    place for a feed to exist and a second place to forget to look.
    """
    made = broker_feeds(names)
    added = tuple(slug for slug in made if slug not in FEEDS)
    for slug in added:
        FEEDS[slug] = made[slug]
    return added


def quote_source_names() -> tuple[str, ...]:
    """Which quote transports to run, from the environment.

    `PRICES_QUOTE_SOURCES` if set, otherwise the default - plus `broker`
    whenever broker-only feeds have been registered, because those have no
    other transport that can reach them. Registering a synthetic and then not
    polling it would leave a feed that exists, is asked for, and never quotes:
    present in the catalogue, absent from every level.
    """
    from .quotes import DEFAULT_QUOTE_SOURCES

    raw = _env("PRICES_QUOTE_SOURCES") or ""
    chosen = tuple(n.strip() for n in raw.split(",") if n.strip()) or DEFAULT_QUOTE_SOURCES
    if BROKER in chosen:
        return chosen
    if any(BROKER in feed.symbols for feed in FEEDS.values()):
        return (*chosen, BROKER)
    return chosen


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

    * a tracked instrument - ``gold``, ``xauusd``, ``btc``, ``eurusd`` - which
      brings along every broker configured for it;
    * ``VENUE:TICKER`` (``OANDA:XAUUSD``, ``YAHOO:GC=F``) for one exact series;
    * a bare ticker (``AAPL``, ``BTC-USD``), which goes to Yahoo - TradingView
      needs the venue to resolve a symbol.

    With nothing passed, every feed in `DEFAULT_SYMBOLS` is tracked.
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
        # Broker-only instruments become ordinary feeds before anything reads
        # the catalogue. Empty by default: this needs a bridge, and a
        # deployment without one should not be polling for symbols it cannot
        # reach. See `register_broker_feeds`.
        raw = _env("PRICES_BROKER_SYMBOLS") or ""
        wanted = [n.strip() for n in raw.split(",") if n.strip()]
        if wanted:
            added = register_broker_feeds(wanted)
            log.info(
                "prices: %d broker-only feed(s) registered - %s",
                len(added),
                ", ".join(added) or "none new",
            )
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
