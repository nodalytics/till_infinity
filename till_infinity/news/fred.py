"""Monetary policy as data: balance sheets, the curve, and inflation expectations.

The calendar says *when* a central bank will speak. This says what its policy
actually is between those dates - how much money there is, what it costs, and
what the market thinks inflation will be. Those are the inputs a rate
differential is built from, and a rate differential is most of why one currency
moves against another.

## Why daily, when CPI is monthly

Official inflation cannot be daily: a CPI is a multi-week survey of physical and
digital prices, so the BLS and Eurostat publish monthly or quarterly and no
amount of wanting will change it.

Markets do not wait for it. A **breakeven rate** is the yield on a nominal bond
minus the yield on an inflation-protected one of the same maturity, which is
what inflation the market is pricing *right now*, and it trades every day. That
is a sentiment reading rather than a measurement - it is what people believe,
which is exactly what moves a currency before the print confirms or refutes it.

So the series here are of three kinds and should not be read as one:

* **Policy stock** - `WALCL`, `M2SL`, `RRPONTSYD`, `WRESBAL`, `TOTBKCR`,
  `ECBASSETSW`, `JPNASSETS`. Slow, revised, and the ground truth of how much
  money exists.
* **Market expectation** - `DGS2`, `DGS10`, `T5YIE`, `T10YIE`, `T5YIFR`,
  `DFII10`. Daily, never revised, and an opinion rather than a fact.
* **Rates, one definition per family** - the daily policy rates `DFF`,
  `ECBDFR` and `IUDSOIA`, and the two OECD families `IRSTCI01xx` (overnight)
  and `IRLTLT01xx` (ten-year) for eight currencies.

## Why a family rather than the best series per country

A rate differential is most of why one currency moves against another, and a
differential is only meaningful when both legs are the **same measurement**.
Quoting an overnight policy rate for one currency against a ten-year yield for
another gives a number that moves with the shape of one curve rather than with
the gap between two countries - and it will look like signal, because it moves.

So the cross-country rates are taken from two OECD families, which are one
definition with the country code swapped. They are monthly and about two months
behind, checked against the live API rather than assumed: on 2026-08-30 the
newest observation was 2026-06-01. That is slow, and it is what a comparable
cross-country rate costs. The three daily policy rates are the fast read where
one exists.

Germany stands in for the euro area. The euro-area aggregates exist
(`IRSTCI01EZM156N`, `IRLTLT01EZM156N`) and stop in January 2026, which is worse
than a proxy that is current.

## What this deliberately does not do

It does not forecast. Nothing here says a widening breakeven means buy dollars;
this package collects and the models decide, which is the same division every
other source in `news` keeps. `structures/macro.py` is the model.

`FRED_API_KEY` is required and there is no keyless fallback: the keyless
endpoint returns 400, and a source that silently collects nothing is worse than
one that refuses to start.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from typing import Any, ClassVar

from ..logging import get_logger
from .config import Settings
from .models import Batch, Observation
from .source import PermanentError, Source, TransientError

log = get_logger(__name__)

FRED_BASE_URL = "https://api.stlouisfed.org/fred"

#: What each series is, so a reader does not have to look every code up. The
#: label is stored on the observation as its indicator.
SERIES: dict[str, str] = {
    # The Federal Reserve's own balance sheet and the money it has created.
    "WALCL": "Fed total assets",
    "M2SL": "M2 money stock",
    "RRPONTSYD": "overnight reverse repo",
    "WRESBAL": "reserve balances",
    "TOTBKCR": "bank credit",
    # The curve. Two and ten are what a rate differential is usually quoted on,
    # and their spread is the recession signal every desk watches.
    "DGS2": "2-year Treasury",
    "DGS10": "10-year Treasury",
    "DFII10": "10-year TIPS (real yield)",
    # Inflation the market is pricing, daily. See the module docstring.
    "T5YIE": "5-year breakeven inflation",
    "T10YIE": "10-year breakeven inflation",
    "T5YIFR": "5y5y forward inflation expectation",
    # The other two balance sheets that matter to a major pair.
    "ECBASSETSW": "ECB total assets",
    "JPNASSETS": "Bank of Japan total assets",
    # Policy rates that move daily, for the three currencies that publish one.
    # These are the fast half of a rate differential and there is no comparable
    # daily series for the yen, the Swiss franc or the commodity currencies.
    "DFF": "Fed funds effective rate",
    "ECBDFR": "ECB deposit facility rate",
    "IUDSOIA": "SONIA (sterling overnight)",
    # The two OECD families, and the reason for preferring them to a hand-picked
    # series per country. A differential is only meaningful when both legs are
    # the *same measurement*: quoting an overnight policy rate against a ten-year
    # yield produces a number that moves with the shape of one curve rather than
    # with the gap between two countries. Every code below is the same
    # definition with the country swapped, so subtracting one from another means
    # what it looks like it means.
    #
    # Monthly and about two months behind - checked, not assumed: the newest
    # observation on 2026-08-30 was 2026-06-01. That is slow, and it is what a
    # comparable cross-country rate costs. The daily policy rates above are the
    # fast read where one exists.
    #
    # Germany stands in for the euro area. The euro-area aggregates
    # (`IRSTCI01EZM156N`, `IRLTLT01EZM156N`) exist and stop in January 2026,
    # which is worse than a proxy that is current.
    "IRSTCI01USM156N": "US overnight rate",
    "IRSTCI01DEM156N": "euro-area overnight rate",
    "IRSTCI01GBM156N": "UK overnight rate",
    "IRSTCI01JPM156N": "Japan overnight rate",
    "IRSTCI01CAM156N": "Canada overnight rate",
    "IRSTCI01AUM156N": "Australia overnight rate",
    "IRLTLT01USM156N": "US 10-year rate",
    "IRLTLT01DEM156N": "euro-area 10-year rate",
    "IRLTLT01GBM156N": "UK 10-year rate",
    "IRLTLT01JPM156N": "Japan 10-year rate",
    "IRLTLT01CAM156N": "Canada 10-year rate",
    "IRLTLT01AUM156N": "Australia 10-year rate",
    "IRLTLT01CHM156N": "Switzerland 10-year rate",
    "IRLTLT01NZM156N": "New Zealand 10-year rate",
    # Inflation as measured rather than as priced. The breakevens above are what
    # the market *thinks*; these are what was counted, monthly and revised, and
    # the gap between the two is the surprise a print delivers.
    "CPIAUCSL": "US CPI",
    "CPILFESL": "US core CPI",
    "PCEPILFE": "US core PCE",
    "CP0000EZ19M086NEST": "euro-area HICP",
    # The dollar against everything, which is the other side of every
    # instrument in the book by construction. Daily.
    "DTWEXBGS": "broad dollar index",
    "DTWEXAFEGS": "dollar against advanced economies",
    # One activity series, because a rate differential is a story about
    # policy and policy is a story about this.
    "UNRATE": "US unemployment rate",
}

#: Which currency each series speaks about, so a consumer can line it up with a
#: pair without knowing what the code means.
CURRENCY: dict[str, str] = {
    "ECBASSETSW": "EUR",
    "JPNASSETS": "JPY",
    "ECBDFR": "EUR",
    "IUDSOIA": "GBP",
    "IRSTCI01DEM156N": "EUR",
    "IRSTCI01GBM156N": "GBP",
    "IRSTCI01JPM156N": "JPY",
    "IRSTCI01CAM156N": "CAD",
    "IRSTCI01AUM156N": "AUD",
    "IRLTLT01DEM156N": "EUR",
    "IRLTLT01GBM156N": "GBP",
    "IRLTLT01JPM156N": "JPY",
    "IRLTLT01CAM156N": "CAD",
    "IRLTLT01AUM156N": "AUD",
    "IRLTLT01CHM156N": "CHF",
    "IRLTLT01NZM156N": "NZD",
    "CP0000EZ19M086NEST": "EUR",
}

#: Days of history to ask for. Enough to see the level and the trend it is on,
#: without re-fetching a decade on every poll.
DAYS_BACK = 400


def _since(days: int = DAYS_BACK) -> str:
    return datetime.fromtimestamp(time.time() - days * 86_400, UTC).strftime("%Y-%m-%d")


def parse(payload: Any, series: str) -> list[Observation]:
    """Observations from one `series/observations` response.

    FRED writes a missing value as the string `"."` - not null, not zero. Read
    naively that becomes a float conversion error on a document that is
    otherwise fine, and skipping the whole response would drop a series for one
    absent day. They are dropped individually.
    """
    if not isinstance(payload, dict):
        return []
    rows = payload.get("observations")
    if not isinstance(rows, list):
        return []

    out: list[Observation] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw = row.get("value")
        when = row.get("date")
        if raw in (None, ".", "") or not when:
            continue
        try:
            value = float(raw)
            at = datetime.strptime(str(when), "%Y-%m-%d").replace(tzinfo=UTC).timestamp()
        except ValueError:
            continue
        out.append(
            Observation(
                source=FredSource.name,
                series=series,
                time=at,
                value=value,
                country=CURRENCY.get(series, "USD"),
                indicator=SERIES.get(series, series),
            )
        )
    return out


class FredSource(Source):
    """Monetary policy series from the St. Louis Fed, one request each."""

    name: ClassVar[str] = "fred"
    #: Daily at fastest, and most of it weekly or monthly. Nothing to gain from
    #: the fast clock, and a rate limit to lose.
    slow: ClassVar[bool] = True

    def __init__(self, settings: Settings, series: tuple[str, ...] | None = None) -> None:
        super().__init__(settings)
        chosen = series if series is not None else settings.fred_series
        self.series = tuple(chosen) or tuple(SERIES)

    async def poll(self) -> Batch:
        batch = Batch()
        if not self.settings.fred_api_key:
            # Loud rather than empty. The keyless endpoint answers 400, so a
            # source that carried on would collect nothing and look healthy.
            raise PermanentError("fred needs FRED_API_KEY - the keyless endpoint returns 400")

        limit = asyncio.Semaphore(max(1, min(self.settings.concurrency, 3)))
        since = _since()

        async def one(series: str) -> None:
            async with limit:
                try:
                    response = await self.get(
                        f"{FRED_BASE_URL}/series/observations",
                        params={
                            "series_id": series,
                            "api_key": self.settings.fred_api_key,
                            "file_type": "json",
                            "observation_start": since,
                        },
                    )
                    found = parse(response.json(), series)
                except (PermanentError, TransientError) as exc:
                    log.warning("fred %s: %s", series, exc)
                    return
                except ValueError as exc:
                    log.warning("fred %s: response was not JSON: %s", series, exc)
                    return
                if not found:
                    log.warning("fred %s: no observations since %s", series, since)
                    return
                batch.observations.extend(found)

        async with asyncio.TaskGroup() as group:
            for series in self.series:
                group.create_task(one(series))
        return batch
