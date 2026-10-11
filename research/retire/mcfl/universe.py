"""The alt coins the market mirror listens to, and how their bars are fetched.

## Why a universe of its own

Production's price feeds carry three coins - BTC, ETH and SOL - beside FX,
metals, indices and energy. The market mirror's signal is *any alt* printing
DISPLACE_C at a 12-bar low on the daily, and it was validated on the 12
original Binance coins and on 274 perpetuals no study had used, with the
DISPLACE_C trade itself confirmed on 58 fresh coins. On three coins it would
almost never fire. So the coins it was validated on are fetched here, by this
service, and **kept off `prices.bars`**: nothing the prices service stores or
the structures service reads changes because the mirror is on.

## Gently

One request per coin per timeframe per closed bar, and only on 4h and 1d - the
two timeframes the trade was tested on. 15m and 1h run only on coins the
prices service already carries. With the default universe of 344 coins that
is 6 x 344 + 344 = 2,408 kline requests a day, plus one market listing per
venue at start-up; see `requests_per_day`.

## Where from

Through production's own ccxt source (`prices.crypto.CcxtSource`), with the
venue order the lab's paper logger uses (`research/ideas/paper_displace.py`):
**Binance spot**, through its public market-data host by default because that
host answers where the main API is geo-blocked, **then OKX perpetuals** for
coins Binance spot does not list. Spot tracks the perpetual within a fraction
of a percent and R is scale-free, which is the paper logger's reasoning too.

A series whose newest closed bar is older than `STALE_BARS` bar lengths is
treated as delisted on that venue - the paper logger's stale-series guard - and
the coin moves to the next venue, or is dropped with one log line.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from ..logging import get_logger
from ..prices.crypto import CcxtSource
from ..prices.models import INTERVALS, Bar, SeriesKey, Symbol, WriteResult
from ..prices.source import Job, SourceError

log = get_logger(__name__)


def _words(text: str) -> tuple[str, ...]:
    return tuple(text.split())


#: The 12 Binance perpetuals the turn studies were built on (`turn_trade.COINS`).
ORIGINAL: tuple[str, ...] = _words("BTC ETH SOL BNB XRP DOGE ADA AVAX LINK LTC DOT TRX")

#: The 58 fresh coins `turn_confirm_rule.json` passed on (SET_A + SET_B minus the 12).
FRESH: tuple[str, ...] = _words(
    "AAVE ALGO APE APT BAT BCH COMP DASH ETC FIL IMX IOTA NEO NEAR SAND 1000SHIB TRU UNI "
    "XLM XMR XTZ ZEC ATOM EOS RUNE KAVA AXS MANA GALA CRV SNX MKR LDO GRT EGLD HBAR ICP "
    "THETA VET KSM ZIL CHZ ENJ 1INCH SUSHI YFI OP ARB INJ FTM MATIC QTUM ONT OMG WAVES ICX "
    "ZRX COTI"
)

#: The 274 unseen perpetuals of the mirror's second check (`market_mirror_rule.json`, SET_D).
SET_D: tuple[str, ...] = _words(
    "1000000MOG 1000BONK 1000CAT 1000CHEEMS 1000FLOKI 1000PEPE 1000RATS 1000SATS 1000WHY "
    "1000X 1MBABYDOGE ACE ACH ACT ACX AERO AEVO AGIX AGLD AI16Z AI AIXBT AKT ALCH ALPACA "
    "ALT AMB ANIME ARC ARKM ARK ASTR AUCTION AVAAI AVA AXL B3 BADGER BANANAS31 BANANA BAN "
    "BB BEAMX BERA BICO BID BIGTIME BIO BLUR BMT BNT BOME BOND BRETT BROCCOLI714 "
    "BROCCOLIF3B BR BSV BSW CAKE CATI CETUS CFX CGPT CHESS CHILLGUY CKB COMBO COOKIE COS "
    "COW CYBER DEGEN DEGO DEXE DF DIA DODOX DOGS DRIFT D DYM EDU EIGEN ENA EPIC ETHFI ETHW "
    "FARTCOIN FET FIDA FIO FLUX FORM FUN FXS GAS GHST GLMR GLM GMX GOAT GPS GRASS GRIFFAIN "
    "GUN G HEI HFT HIFI HIGH HIPPO HIVE HMSTR HOOK IDEX ID ILV IO IP JELLYJELLY JOE JTO JUP "
    "KAIA KAITO KAS KDA KEY KMNO KOMA LAYER LEVER LISTA LOKA LOOM LQTY LSK LUMIA MAGIC "
    "MANTA MAVIA MAV MBOX MDT MELANIA MEME METIS ME MEW MINA MLN MOCA MOODENG MORPHO MOVE "
    "MOVR MUBARAK MYRO NEIROETH NEIRO NFP NIL NMR NOT NTRN NULS OMNI OM ONDO ONG ORBS ORCA "
    "ORDI OXT PARTI PAXG PENDLE PENGU PERP PHA PHB PIPPIN PIXEL PLUME PNUT POL POLYX PONKE "
    "POPCAT PORTAL POWR PROM PYTH QUICK RAD RARE RAYSOL RDNT RED REI RENDER REZ RIF RONIN "
    "RPL SAFE SAGA SANTOS SCRT SCR SEI SHELL SIREN SLERF SLP SNT SOLV SONIC SPX SSV STEEM "
    "STPT STRAX STRK STX SUI SUN SUPER S SWARMS SWELL SYN SYS TAO THE TIA TNSR TOKEN TON "
    "TROY TRUMP TST TURBO T TUT TWT UMA USTC USUAL UXLINK VANA VANRY VELODROME VIC VIDT "
    "VINE VIRTUAL VOXEL VTHO VVV WAL WAXP WIF WLD W XAI XVG XVS YGG ZEREBRO ZETA ZK ZRO"
)

#: Every coin the rules were validated on, in that order, de-duplicated.
DEFAULT_COINS: tuple[str, ...] = tuple(dict.fromkeys((*ORIGINAL, *FRESH, *SET_D)))

#: The market the mirror buys. Fetched for its reference price; never a signal source.
TARGET = "BTC"

#: Perpetual names whose spot market drops the multiplier (`paper_displace.SPOT_NAME`,
#: extended to the 1000x coins of SET_D).
SPOT_NAME: dict[str, str] = {
    "1000LUNC": "LUNC",
    "1000XEC": "XEC",
    "1000SHIB": "SHIB",
    "LUNA2": "LUNA",
    "1000BONK": "BONK",
    "1000FLOKI": "FLOKI",
    "1000PEPE": "PEPE",
    "1000RATS": "RATS",
    "1000X": "X",
    "1000CAT": "CAT",
    "1000CHEEMS": "CHEEMS",
    "1000WHY": "WHY",
}

#: The timeframes the alt universe is fetched on. 15m and 1h are not: the
#: trade was never tested there, and 344 coins at 15m is 33,000 requests a day.
ALT_TIMEFRAMES: tuple[str, ...] = ("4h", "1d")

#: Binance's public market-data host - the same data as the main API, reachable
#: where the main API is not. The paper logger's price source.
BINANCE_MIRROR = "https://data-api.binance.vision/api/v3"

#: A series this many bar lengths behind is stale - delisted on that venue.
STALE_BARS = 2


def requests_per_day(coins: int, timeframes: Sequence[str]) -> int:
    """Kline requests a day: one per coin per closed bar of each timeframe."""
    return sum(coins * (86_400 // INTERVALS[tf].seconds) for tf in timeframes)


@dataclass(slots=True)
class Venue:
    """One ccxt exchange, opened through production's CcxtSource."""

    name: str
    market_type: str
    url: str = ""
    source: CcxtSource | None = None
    listed: set[str] = field(default_factory=set)

    def settings(self) -> SimpleNamespace:
        overrides: dict[str, Any] = {}
        if self.name == "binance":
            # Spot only: the default market load also asks the futures hosts,
            # which is three requests and two blocked hosts for nothing.
            overrides["options"] = {"fetchMarkets": {"types": ["spot"]}}
            if self.url:
                overrides["urls"] = {"api": {"public": self.url}}
        return SimpleNamespace(
            ccxt_exchanges=(self.name,),
            ccxt_market_type=self.market_type,
            ccxt_overrides={self.name: overrides} if overrides else {},
            include_partial=False,
        )

    def symbol(self, coin: str) -> str | None:
        """The pair this venue lists for a coin, or None."""
        name = SPOT_NAME.get(coin, coin)
        if self.market_type == "swap":
            candidates = (f"{coin}/USDT:USDT", f"{name}/USDT:USDT")
        else:
            candidates = (f"{coin}/USDT", f"{name}/USDT")
        return next((c for c in candidates if c in self.listed), None)


class Fetcher:
    """Closed bars for the alt universe, one coin and timeframe at a time.

    `open` lists each venue's markets once; `bars` asks the coin's venue for
    its last `limit` closed bars and moves the coin down the venue list when a
    venue does not list it or serves a stale series.
    """

    def __init__(self, venues: Sequence[Venue]) -> None:
        self.venues = list(venues)
        #: coin -> index into `venues` currently used for it.
        self._where: dict[str, int] = {}
        self._said: set[str] = set()
        self.requests = 0

    async def open(self) -> None:
        for venue in self.venues:
            venue.source = CcxtSource(venue.settings())  # type: ignore[arg-type]
            try:
                await venue.source.__aenter__()
                venue.listed = await venue.source.listed(venue.name)
                self.requests += 1
                log.info("mcfl: %s lists %d pairs", venue.name, len(venue.listed))
            except Exception as exc:  # one venue down is not all of them
                log.warning("mcfl: %s unavailable: %s", venue.name, exc)
                venue.listed = set()

    async def close(self) -> None:
        for venue in self.venues:
            if venue.source is not None:
                await venue.source.__aexit__(None, None, None)
                venue.source = None

    async def bars(self, coin: str, timeframe: str, limit: int) -> tuple[str, list[Bar]] | None:
        """(venue:pair, closed bars oldest first), or None if no venue serves it fresh."""
        interval = INTERVALS[timeframe]
        start = self._where.get(coin, 0)
        for i in range(start, len(self.venues)):
            venue = self.venues[i]
            pair = venue.symbol(coin)
            if pair is None or venue.source is None:
                continue
            got: list[Bar] = []

            async def sink(_key: SeriesKey, bars: Sequence[Bar], into=got) -> WriteResult:
                into.extend(bars)
                return WriteResult(inserted=len(bars))

            job = Job("ccxt", coin, Symbol(venue.name.upper(), pair), (interval,))
            self.requests += 1
            try:
                await venue.source.fetch(job, limit, sink)
            except SourceError as exc:
                log.debug("mcfl: %s %s on %s failed: %s", coin, timeframe, venue.name, exc)
                continue
            got.sort(key=lambda b: b.time)
            if not got or got[-1].time + STALE_BARS * interval.seconds < time.time():
                continue  # nothing, or stale: delisted here, try the next venue
            self._where[coin] = i
            return f"{venue.name}:{pair}", got
        if coin not in self._said:
            self._said.add(coin)
            log.info("mcfl: %s has no fresh %s series on %s", coin, timeframe, self.names)
        return None

    @property
    def names(self) -> str:
        return "/".join(v.name for v in self.venues)


def default_venues(binance_url: str = BINANCE_MIRROR) -> list[Venue]:
    """Binance spot, then OKX perpetuals - the paper logger's order."""
    return [Venue("binance", "spot", binance_url), Venue("okx", "swap")]
