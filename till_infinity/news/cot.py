"""Who is actually holding the position - the CFTC's Commitments of Traders.

Everything else this system knows about supply and demand is **inferred from
price**. An origin is where a violent move started, a profile node is where a
lot of time was spent, a gap is where trade did not happen - all of them read
off the tape, because the tape is all there is. There is no order book on this
feed: the broker gives a spread and nothing behind it.

This is the one exception available. Every Friday the CFTC publishes, for every
US futures market, how many contracts each category of trader was holding on
the previous Tuesday. It is not inferred, it is **reported** - and it is free.

## What is taken from it, and what is ignored

The report splits reportable positions four ways: dealers, asset managers,
leveraged funds and other reportables. What this takes is the **leveraged
funds' net** - long minus short - because that is the speculative money, the
category whose positioning is a bet rather than a hedge. A dealer's book is the
other side of somebody's hedge and says more about flow than about opinion.

Normalised by open interest, so a net of -72,092 contracts on the Canadian
dollar becomes -21.9% of the market. Raw contract counts are not comparable
between a market with 2m contracts outstanding and one with 22,000, and are not
comparable with themselves a year later either.

## The sign, which is the one thing that must not be wrong

**CME currency futures are quoted as the foreign currency in dollars.** A long
JAPANESE YEN future is long yen, which is *short* USDJPY. So the mapping to our
feeds inverts for every pair that has the dollar first:

* `eurusd`, `gbpusd`, `audusd`, `nzdusd` - futures long is our feed up;
* `usdjpy`, `usdcad`, `usdchf` - futures long is our feed **down**.

Getting this backwards would not fail, it would produce a signal of exactly the
right size pointing exactly the wrong way, on the instruments that matter most.
`INVERTED` names them and a test asserts the direction rather than the table.

## Weekly, and three days stale on arrival

Tuesday's positions, published Friday afternoon. That is the data, and no
amount of polling improves it - so this is a `slow` source and the freshest
reading is always at least three days old.

Whether a three-day-old weekly number is worth anything is exactly the sort of
question this repository answers by measuring rather than arguing. See
research/positioning.md. What is not in doubt is that it is the only
*observed* rather than inferred supply-and-demand data reachable from here.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime
from typing import Any, ClassVar

from ..logging import get_logger
from .models import Batch, Observation
from .source import Source, TransientError

log = get_logger(__name__)

#: The weekly financial-futures file, short format.
#:
#: There is a Socrata JSON API for the same data
#: (`publicreporting.cftc.gov/resource/gpe5-46if.json`) and it is better in
#: every respect except one: it answers **403 from some networks and 200 from
#: others**. It serves the production host and refuses the development machine,
#: which is the worst shape a dependency can have - it works until somebody
#: tries to reproduce a result.
#:
#: What it would buy, recorded because it is the right answer if this data ever
#: earns its keep: **named fields**. This parser reads `row[14]`, and a column
#: reshuffle in a fixed-layout government text dump would not fail, it would
#: read a different category of trader - a silent wrong answer of exactly the
#: kind the sign mapping below is written to avoid. Also server-side filtering
#: to the twelve markets that matter, incremental fetching by report date, and
#: the whole history behind one endpoint rather than a zip per year.
#:
#: Not adopted, because the lead correlations in research/positioning.md are
#: all inside the noise band: this data has no measured predictive content, and
#: hardening the pipeline of something nothing consumes is work spent on the
#: wrong end.
COT_URL = "https://www.cftc.gov/dea/newcot/FinFutWk.txt"

#: Column positions in the short-format file, zero-based. Verified against the
#: live file rather than the spec: the four category longs plus the four
#: spreads reconcile exactly to the total reportable long, which is the check
#: that says the layout is what it appears to be.
NAME, DATE, OPEN_INTEREST = 0, 2, 7
LEV_LONG, LEV_SHORT = 14, 15
ASSET_LONG, ASSET_SHORT = 11, 12

#: Which CFTC market maps onto which of our feeds. Matched on the market name
#: starting with the key, because the exchange suffix varies and the
#: consolidated and micro contracts of the same market would otherwise collide.
MARKETS: dict[str, str] = {
    "EURO FX - ": "eurusd",
    "BRITISH POUND - ": "gbpusd",
    "JAPANESE YEN - ": "usdjpy",
    "AUSTRALIAN DOLLAR - ": "audusd",
    "CANADIAN DOLLAR - ": "usdcad",
    "SWISS FRANC - ": "usdchf",
    "NZ DOLLAR - ": "nzdusd",
    "USD INDEX - ": "dxy",
    "E-MINI S&P 500 - ": "spx500",
    "NASDAQ MINI - ": "us100",
    "DJIA Consolidated - ": "us30",
    "BITCOIN - ": "btc",
}

#: Feeds where a long future means our price goes **down**, because the future
#: is quoted in the foreign currency and our feed has the dollar first.
INVERTED: frozenset[str] = frozenset({"usdjpy", "usdcad", "usdchf"})


def direction(feed: str) -> int:
    """+1 when a long future means our feed rises, -1 when it means it falls."""
    return -1 if feed in INVERTED else 1


def _number(text: str) -> float | None:
    try:
        return float(text.strip())
    except (AttributeError, TypeError, ValueError):
        return None


def parse(text: str) -> list[Observation]:
    """Observations from the weekly file.

    Two per market: the leveraged funds' net as a share of open interest, and
    the asset managers'. Both signed so that positive always means *long our
    feed*, which is the only convention a consumer can use without knowing
    which side of the pair the dollar is on.
    """
    out: list[Observation] = []
    for row in csv.reader(io.StringIO(text)):
        if len(row) <= LEV_SHORT:
            continue
        name = row[NAME].strip()
        feed = next((f for key, f in MARKETS.items() if name.startswith(key)), "")
        if not feed:
            continue
        try:
            when = datetime.strptime(row[DATE].strip(), "%Y-%m-%d").replace(tzinfo=UTC)
        except ValueError:
            continue
        interest = _number(row[OPEN_INTEREST])
        if not interest or interest <= 0:
            continue

        sign = direction(feed)
        for series, long_at, short_at in (
            ("leveraged_net", LEV_LONG, LEV_SHORT),
            ("asset_manager_net", ASSET_LONG, ASSET_SHORT),
        ):
            long_side, short_side = _number(row[long_at]), _number(row[short_at])
            if long_side is None or short_side is None:
                continue
            out.append(
                Observation(
                    source=CotSource.name,
                    series=f"{feed}.{series}",
                    time=when.timestamp(),
                    # Share of open interest, signed so positive is long *our*
                    # feed. See `INVERTED`.
                    value=sign * (long_side - short_side) / interest,
                    country=feed,
                    indicator=f"{series.replace('_', ' ')} share of open interest",
                    frequency="weekly",
                )
            )
        out.append(
            Observation(
                source=CotSource.name,
                series=f"{feed}.open_interest",
                time=when.timestamp(),
                value=interest,
                country=feed,
                indicator="open interest, contracts",
                frequency="weekly",
            )
        )
    return out


class CotSource(Source):
    """Positioning from the CFTC, weekly.

    No key and no account. The one piece of *observed* supply and demand
    reachable from here - everything else this system knows about it is
    inferred from price, because the broker feed has no order book behind its
    spread.
    """

    name: ClassVar[str] = "cot"
    #: Tuesday's positions published on Friday. Polling faster cannot make the
    #: data fresher, and the file is the same bytes all week.
    slow: ClassVar[bool] = True

    async def poll(self) -> Batch:
        batch = Batch()
        try:
            response = await self.get(COT_URL)
        except TransientError as exc:
            log.warning("cot: %s", exc)
            return batch
        found = parse(response.text)
        if not found:
            # Loud, because the file is a fixed-layout text dump with no
            # version marker: a silent reshuffle of its columns would otherwise
            # look like a market nobody trades.
            log.warning("cot: %d bytes and no rows matched a known market", len(response.text))
            return batch
        batch.observations.extend(found)
        return batch

    def describe(self) -> dict[str, Any]:
        return {"source": self.name, "url": COT_URL, "markets": len(MARKETS)}
