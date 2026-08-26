"""IMF reserves - International Reserves and Foreign Currency Liquidity (IRFCL).

Central bank reserve assets per country, monthly. Slow-moving data, but it is
the balance-sheet side of the same story the calendar covers: who has the
firepower to defend a currency, and how that stock is changing.

Three things about this API cost time to discover, so they are pinned here:

* the legacy host ``dataservices.imf.org`` is **gone** - not deprecated, absent
  from DNS. The live service is ``api.imf.org/external/sdmx/2.1``;
* the series key is ``COUNTRY.INDICATOR.SECTOR.FREQUENCY`` and country codes
  are **ISO-3**. ``US...M`` returns a valid, empty document; ``USA...M`` returns
  the data. An empty result and a wrong key look identical, which is what makes
  this worth writing down;
* series carry ``SCALE="6"``, which looks like "values are in millions" and is
  not: the numbers are already plain USD. US reserves for 2026-07 arrive as
  252,708,091,800 - the $252.7bn actually held. Applying the exponent would
  overstate every figure by a million.

Responses are SDMX StructureSpecificData: dimensions live in the attributes of
each ``<Series>`` element, observations in the ``<Obs>`` children below it.
"""

from __future__ import annotations

import asyncio
import xml.etree.ElementTree as ET
from datetime import UTC, datetime

from ..logging import get_logger
from .config import (
    IMF_BASE_URL,
    IMF_FLOW,
    IMF_FREQUENCY,
    IMF_MONTHS_BACK,
    Settings,
)
from .models import Batch, Observation, parse_period
from .source import PermanentError, Source, TransientError

log = get_logger(__name__)

#: An empty SDMX document still parses, so "no series" is the real signal.
EMPTY_HINT = "no series matched"


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_dataset(payload: bytes, *, source: str = "imf") -> list[Observation]:
    """Pull observations out of an SDMX StructureSpecificData body."""
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise PermanentError(f"imf: malformed SDMX ({exc})") from exc

    out: list[Observation] = []
    for element in root.iter():
        if _local(element.tag) != "Series":
            continue
        dims = element.attrib
        country = dims.get("COUNTRY", "")
        indicator = dims.get("INDICATOR", "")
        frequency = dims.get("FREQUENCY", "")
        try:
            scale = int(dims.get("SCALE") or 0)
        except ValueError:
            scale = 0
        series = ".".join((country, indicator, dims.get("SECTOR", ""), frequency))

        for obs in element:
            if _local(obs.tag) != "Obs":
                continue
            period = obs.get("TIME_PERIOD") or ""
            when = parse_period(period)
            raw = obs.get("OBS_VALUE")
            if when is None or raw in (None, ""):
                continue
            try:
                value = float(raw)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                continue
            out.append(
                Observation(
                    source=source,
                    series=series,
                    time=when,
                    value=value,
                    country=country,
                    indicator=indicator,
                    frequency=frequency,
                    scale=scale,
                    period=period,
                )
            )
    return out


def start_period(months_back: int, *, now: datetime | None = None) -> str:
    """The ``startPeriod`` query value, as ``YYYY-MM``."""
    now = now or datetime.now(UTC)
    month_index = now.year * 12 + (now.month - 1) - months_back
    return f"{month_index // 12:04d}-{month_index % 12 + 1:02d}"


class ImfSource(Source):
    """Reserve assets per country, one request each."""

    name = "imf"
    #: Monthly data - there is nothing to gain from the fast clock.
    slow = True

    def __init__(self, settings: Settings, countries: tuple[str, ...] | None = None) -> None:
        super().__init__(settings)
        self.countries = tuple(countries if countries is not None else settings.imf_countries)

    def key(self, country: str) -> str:
        """``COUNTRY.INDICATOR.SECTOR.FREQUENCY``, with the middle two open."""
        return f"{country}...{IMF_FREQUENCY}"

    async def poll(self) -> Batch:
        limit = asyncio.Semaphore(max(1, min(self.settings.concurrency, 3)))
        batch = Batch()
        since = start_period(IMF_MONTHS_BACK)

        async def one(country: str) -> None:
            async with limit:
                try:
                    response = await self.get(
                        f"{IMF_BASE_URL}/data/{IMF_FLOW}/{self.key(country)}",
                        params={"startPeriod": since},
                    )
                    found = parse_dataset(response.content)
                except (PermanentError, TransientError) as exc:
                    log.warning("imf %s: %s", country, exc)
                    return
                if not found:
                    # Valid document, no rows: usually a country code that is
                    # not ISO-3 rather than a genuinely empty period.
                    log.warning("imf %s: %s for key %s", country, EMPTY_HINT, self.key(country))
                    return
                batch.observations.extend(found)

        async with asyncio.TaskGroup() as group:
            for country in self.countries:
                group.create_task(one(country))
        return batch
