"""The hour of the week, as a volatility multiplier: FX on New York's clock, crypto on UTC.

`research/docs/calendar-returns.md` bucketed every family's 1h bars by weekday x hour. Volatility
runs on the clock in FX, metals and crypto, and the profile repeats out of sample:
- FX: profile correlation +0.96; the London/New York overlap is about 1.6x the average hour, and
  19-23 UTC about 0.6x;
- crypto: US hours about 1.8x, Saturday about 0.6x.

Multiplying the production volatility unit by the profile cut the error of the next hour's |r|
to 0.937/0.948 of sigma alone on FX (New York clock) and 0.957/0.958 on crypto, in both halves.
Metals failed its second half, so its profile is kept for the card's description only. Deriv
has no calendar and is left out entirely.

## What is learned

Per family and interval, the mean of y = |log(close / previous close)| / sigma, where sigma is
the previous bar's EWMA true range, the production unit. It is kept for each of the 168 weekday x
hour cells and overall. The multiplier is a cell's mean over the overall mean, as the study
measured it. Means run exactly until `SLOW` observations, then as an EWMA with that memory, so
the profile is stable but can follow a market that changes its hours. It is neutral (1.0) until a
cell and the whole profile are warm.

## Where it is used

`multiplier` scales the envelope's unit for the next N bars by the root mean square of the cells
those bars fall in. The unit is how big the coming moves should be, which is the question the
profile answers. It is not applied where the boosted envelope already reads the hour (FX 15m) or
where a published law quotes (Deriv). `now` gives the current cell's multiple for the card.

`STRUCTURES_VOL_CLOCK=0` turns it off.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from ..state import Restorable

ENABLED = os.environ.get("STRUCTURES_VOL_CLOCK", "1") not in ("0", "false", "no")

NEW_YORK = ZoneInfo("America/New_York")
CELLS = 168
#: Memory of each mean, in observations: exact until then, an EWMA with this memory after.
SLOW = 500
#: Observations a cell needs, and the profile overall, before a multiple is read from it.
MIN_CELL, MIN_TOTAL = 20, 4_000
#: Families whose profile forecasts (calendar-returns.md passed both halves); metals is described
#: on the card but not forecast.
FORECAST = frozenset({"fx", "crypto"})
#: A multiple worth a card line: clearly louder or quieter than the average hour.
NOTABLE_HIGH, NOTABLE_LOW = 1.3, 0.75

_CRYPTO = ("btc", "eth", "sol", "xrp", "ltc", "ada", "doge", "bnb", "dot", "link")
_METALS = ("xau", "xag", "xpt", "xpd", "gold", "silver")


def family(feed: str) -> str | None:
    """The clock family of a feed, or None for a market with no calendar (Deriv, indices)."""
    from .. import rollover

    if rollover.is_fx(feed):
        return "fx"
    low = feed.lower()
    if low.startswith(_CRYPTO):
        return "crypto"
    if low.startswith(_METALS):
        return "metals"
    return None


def cell(fam: str, when: float) -> int:
    """weekday x 24 + hour, on New York's clock for FX and UTC for the rest."""
    t = datetime.fromtimestamp(when, UTC)
    if fam == "fx":
        t = t.astimezone(NEW_YORK)
    return t.weekday() * 24 + t.hour


def _step(mean: float, count: float, y: float) -> float:
    return mean + (y - mean) / (count + 1) if count < SLOW else mean + (y - mean) / SLOW


@dataclass(slots=True)
class Profile(Restorable):
    """One family and interval: the mean normalised |move| per weekday x hour cell."""

    means: list[float] = field(default_factory=lambda: [0.0] * CELLS)
    counts: list[float] = field(default_factory=lambda: [0.0] * CELLS)
    mean: float = 0.0
    count: float = 0.0

    def observe(self, at: int, y: float) -> None:
        self.means[at] = _step(self.means[at], self.counts[at], y)
        self.counts[at] += 1
        self.mean = _step(self.mean, self.count, y)
        self.count += 1

    def ratio(self, at: int) -> float | None:
        """The cell's multiple of the average hour, or None while it or the profile is cold."""
        if self.count < MIN_TOTAL or self.counts[at] < MIN_CELL or self.mean <= 0:
            return None
        return self.means[at] / self.mean


@dataclass(slots=True)
class Clock(Restorable):
    """Every family and interval's profile, and each series' last close and unit."""

    profiles: dict[str, Profile] = field(default_factory=dict)
    #: "feed|interval" -> (last close, last sigma): what the next bar's y is measured against.
    last: dict[str, tuple[float, float]] = field(default_factory=dict)

    def observe(self, feed: str, interval: str, opened: float, close: float, sigma: float) -> None:
        """One closed bar: fold its normalised move into its family's cell. `opened` is the
        bar's open time, the hour the move belongs to; `sigma` is this bar's unit, kept for the
        next bar's measurement."""
        fam = family(feed)
        if fam is None or close <= 0 or not (sigma > 0):
            return
        key = f"{feed}|{interval}"
        before = self.last.get(key)
        self.last[key] = (close, sigma)
        if before is None:
            return
        prev_close, prev_sigma = before
        if prev_close <= 0 or prev_sigma <= 0:
            return
        y = abs(math.log(close / prev_close)) / prev_sigma
        if not math.isfinite(y) or y > 50:  # a bad print, not a market move
            return
        profile = self.profiles.get(f"{fam}|{interval}")
        if profile is None:
            profile = self.profiles[f"{fam}|{interval}"] = Profile()
        profile.observe(cell(fam, opened), y)

    def _profile(self, feed: str, interval: str) -> tuple[str, Profile] | None:
        fam = family(feed)
        if fam is None:
            return None
        found = self.profiles.get(f"{fam}|{interval}")
        return None if found is None else (fam, found)

    def multiplier(
        self, feed: str, interval: str, start: float, bars: int, seconds: float
    ) -> float:
        """The unit's multiplier for the next `bars` bars from `start`: the root mean square of
        their cells' multiples. 1.0 where the family does not forecast, or while cold."""
        got = self._profile(feed, interval) if ENABLED else None
        if got is None or got[0] not in FORECAST or bars <= 0 or seconds <= 0:
            return 1.0
        fam, profile = got
        total = 0.0
        for k in range(bars):
            r = profile.ratio(cell(fam, start + k * seconds))
            total += (1.0 if r is None else r) ** 2
        return math.sqrt(total / bars)

    def now(self, feed: str, interval: str, when: float) -> float | None:
        """The multiple of the cell `when` falls in, for the card; None while cold or off-clock."""
        got = self._profile(feed, interval) if ENABLED else None
        if got is None:
            return None
        return got[1].ratio(cell(got[0], when))

    def forget(self, keep: set[str]) -> int:
        gone = [k for k in self.last if k.split("|", 1)[0] not in keep]
        for k in gone:
            del self.last[k]
        return len(gone)


def card_line(got: dict) -> list[str]:
    """A line when this hour is clearly louder or quieter than the average hour; else nothing."""
    m = got.get("vol_clock")
    if not isinstance(m, int | float) or not math.isfinite(m):
        return []
    if m >= NOTABLE_HIGH or m <= NOTABLE_LOW:
        return [f"🕐 this hour is historically {m:.1f}x average volatility"]
    return []
