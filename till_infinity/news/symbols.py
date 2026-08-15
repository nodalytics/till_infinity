"""Which instrument a headline is about.

A headline is only actionable if it can be attached to something we price.
TradingView tags articles with `VENUE:TICKER` strings — 641 distinct ones
across 3,058 articles — and none of them are the feed names the rest of this
project uses.

**The map comes from `prices`, not from a table written here.** `prices.config`
already knows that `BTCUSD` on Bitstamp and `BTC-USD` on Yahoo are both `btc`,
because it had to in order to collect them. A second list would be a second
thing to keep current, and it would go stale the first time a venue was added.

## The venue half is noise

`BITSTAMP:BTCUSD`, `FX:EURUSD`, `FX_IDC:USDJPY`, `TVC:GOLD`, `ICEUS:DXY`,
`RUS:EURUSD_TOD`, `FTMO_OANDA:EURUSD.SIM` — the prefix is whichever venue the
provider happened to cite, and matching on it would need every venue any
publisher might name. The ticker carries the instrument; the venue does not.

## What "not mapped" means

Roughly 40% of tagged articles map to nothing, and that is the correct answer
rather than a gap: `XRPUSD`, `DXY`, `POLYMARKET`, `HYPEUSD`, `USDINR`, `COIN`,
`BNBUSD`, `USDKRW`. They are instruments this project does not price, and a
headline about one of them cannot be joined to anything. Mapping them to a
neighbour — `USDINR` to `usdjpy` because both are dollar pairs — would be
inventing a relationship.
"""

from __future__ import annotations

import re
from functools import lru_cache

from ..prices.config import FEEDS

#: The shortest ticker a prefix match may use. Six is the length of a currency
#: pair, and below it the match stops being evidence: `SPX` would claim
#: `SPXANYTHING`, and a three-letter prefix collides with far too much.
MIN_PREFIX = 6

#: Decorations venues add to an otherwise ordinary ticker — a settlement suffix
#: (`EURUSD_TOD`, `EURUSDTDTM`), a simulated feed (`EURUSD.SIM`), a continuous
#: future (`BRN1!`). Stripped to bare alphanumerics before matching.
_BARE = re.compile(r"[^A-Z0-9]")


@lru_cache(maxsize=1)
def _by_ticker() -> dict[str, str]:
    """Ticker to feed, built from the symbols `prices` already collects."""
    found: dict[str, str] = {}
    for name, feed in FEEDS.items():
        for group in feed.symbols.values():
            for symbol in group:
                found[symbol.ticker.upper()] = name
    return found


def feed_for(symbol: str) -> str:
    """The feed this `VENUE:TICKER` names, or an empty string for one we do not price.

    Three passes, narrowing: the ticker as given, the ticker stripped of venue
    decoration, then the longest known ticker it starts with — which is what
    turns `EURUSD_TOD` and `EURUSDTDTM` into `eurusd` while leaving `EURJPY`
    alone, since no known ticker is a prefix of it.
    """
    if not symbol:
        return ""
    known = _by_ticker()
    ticker = symbol.rsplit(":", maxsplit=1)[-1].upper()
    if ticker in known:
        return known[ticker]

    bare = _BARE.sub("", ticker)
    if bare in known:
        return known[bare]

    # Longest first, so a specific ticker wins over a shorter one it contains.
    for candidate in sorted(known, key=len, reverse=True):
        if len(candidate) >= MIN_PREFIX and bare.startswith(candidate):
            return known[candidate]
    return ""


def feeds_for(symbols: list[str] | tuple[str, ...] | None) -> list[str]:
    """Every tracked feed a headline's symbols name, in a stable order.

    Deduplicated, because a provider often tags the same instrument twice
    through different venues — `FX:EURUSD` and `BITSTAMP:EURUSD` on one story
    is one instrument, not two.
    """
    if not symbols:
        return []
    found = {feed for feed in (feed_for(symbol) for symbol in symbols) if feed}
    return sorted(found)
