"""The economic calendar as an expected volatility multiple.

See `news-volatility.md` in research/docs.

The news service has collected a calendar since August and nothing read it for volatility. This
reads it, and it is the one thing in this folder whose input carries **no estimation at all**: a
scheduled release time is published days in advance, so "a high-importance print lands in twenty
minutes" is a fact, not a forecast.

## Why volatility and not direction

Every directional candidate in this repository has died. Volatility has not, because it clusters -
`a-theory-from-ohlc.md` records the signed series as near-unpredictable past a few minutes while
absolute returns carry long memory. So a calendar is pointed at the quantity it can actually move.

## What was measured, and what the numbers are net of

Over **191 instrument-events** on eurusd, gbpusd and xauusd at 15m resolution, against a control of
**the same instrument, the same hour of the day, the same weekday, within 120 days, with no event
of any importance inside two hours.**

That control is the whole study. **61 of the high-importance events land in the 12:30 UTC hour** -
the US 08:30 Eastern slot - which is also the London/New York overlap, so comparing against an
all-hours average would measure the session and report a large, confident, spurious number.
`context/sessions.py` already learns that the hour carries a volatility share, which is the same
fact from the other side.

Every figure in `PROFILE` is therefore net of the diurnal and weekly pattern **and** of the
instrument's own recent volatility level.

## The shape, which is more useful than the peak

    -2h to -30m   0.79x     the market stops trading while it waits
    the print     2.42x
    +30m          1.76x
    +1h           1.35x
    +2h           1.12x
    +4h           0.92x     below normal - it overshoots, then undershoots

**The lull is the part worth having.** It is knowable furthest ahead, it is the least obvious, and
a 0.79 multiple on a volatility-scaled stop is a 21% change in a sizing input. Every window's 95%
interval excludes 1.0.

## It decides nothing

Published as features on level calls and consumed by nothing, like `Macro` before it and
`character.py` beside it. The reason is `paying.md`'s arithmetic: a volatility multiple is not an
edge, it is an input to sizing, and whether re-sizing on it pays has not been measured. What is
measured is the multiple.

**One instrument is deliberately excluded from the profile.** usdjpy showed 5.0x on the print and
**1.90x before it** - a market getting busier while it waits, which the others do not do. The
obvious explanation was tested and rejected: dropping every event with no fixed release minute
(rate decisions, statements, press conferences) left it at 1.902x unchanged. So it is unexplained,
and a number that is unexplained on one of four instruments does not go into a shared table. See
the research document.
"""

from __future__ import annotations

import bisect
import math
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

from ...logging import get_logger
from ..state import Restorable
from .macro import currencies

log = get_logger(__name__)

#: Importance at or above which a release is worth carrying. The store grades 0, 1 and 2, and the
#: measurement was made on 2 - so this is the number that was measured rather than a preference.
IMPORTANT = 2

#: Measured cumulative realised-volatility multiples, as `(minutes from the release, multiple)`.
#:
#: Each entry is the realised volatility from the release to that offset, over the matched control
#: median - so they are cumulative windows and not per-slice rates. Read "at +60 minutes the hour
#: since the print carried 1.35 times normal volatility", which is what was measured; inventing a
#: per-minute rate from it would be modelling past the data.
#:
#: The negative entry is the pre-release lull and is the one knowable furthest ahead.
#:
#: **Each entry labels the interval that begins at its offset**, so a caller 45 minutes past a
#: print reads the `30.0` row. That makes the final entry a boundary rather than a usable step:
#: `0.920` is the realised volatility over the *whole* four hours after a release, which is a
#: statement about a window and not about a moment, so it marks where reach ends. The undershoot
#: is a real measured finding - volatility overshoots and then comes back *below* normal - and it
#: is recorded here and in the research rather than published as an instantaneous multiple it is
#: not.
PROFILE: tuple[tuple[float, float], ...] = (
    (-120.0, 0.789),
    (0.0, 2.424),
    (30.0, 1.762),
    (60.0, 1.349),
    (120.0, 1.120),
    (240.0, 0.920),
)

#: Beyond this many minutes either side, a release says nothing and no feature is published.
#: `None` rather than 1.0, because "no opinion" and "expect normal volatility" are different
#: claims and the journal should be able to tell them apart.
REACH = 240.0

#: Events held at most, newest kept. A cap because this is restored from a save and an unbounded
#: field grows forever; a plain tuple because a capped `deque` restored from an older save comes
#: back **uncapped** - that happened in this codebase and was found on the live heap.
KEEP = 4_000


@dataclass(slots=True)
class Releases(Restorable):
    """Scheduled releases, and the volatility multiple they imply for one feed right now."""

    #: `(when, currency)` for important releases, sorted by time. Only floats and strings.
    events: list[tuple[float, str]] = field(default_factory=list)

    def note(self, rows: object) -> int:
        """Take calendar rows from the news store. Returns how many were kept.

        Accepts anything with `time`, `importance` and `country` - a mapping or an object - so
        this does not have to import the news models and the two services stay uncoupled.
        """
        held = {(when, code) for when, code in self.events}
        for row in rows or ():
            get = row.get if hasattr(row, "get") else lambda name, _r=row: getattr(_r, name, None)
            try:
                when = float(get("time") or 0.0)
                rank = int(get("importance") or 0)
            except (TypeError, ValueError):
                continue
            code = str(get("country") or "").strip().upper()
            if when <= 0.0 or rank < IMPORTANT or not code:
                continue
            held.add((when, code))
        self.events = sorted(held)[-KEEP:]
        return len(self.events)

    def _codes(self, feed: str) -> tuple[str, ...]:
        """The currency codes a feed answers to, as the calendar spells them.

        The two providers label the same print differently - one by ISO country, one by currency -
        so both are matched. `EUR` also answers to its large members, because a German inflation
        print moves the euro and the calendar files it under `DE`.
        """
        base, quote = currencies(feed)
        out: set[str] = set()
        for code in (base, quote):
            if not code:
                continue
            out.add(code)
            out.update(_ALSO.get(code, ()))
        return tuple(sorted(out))

    def nearest(self, feed: str, now: float) -> float | None:
        """Minutes between now and the closest important release touching this feed.

        **Negative before the print, positive after it**, since it is `now - when`. Getting that
        sign backwards would read the post-release spike as the pre-release lull and size up into
        exactly the wrong window, so it is stated here and pinned by a test.
        """
        if not self.events:
            return None
        codes = self._codes(feed)
        if not codes:
            return None
        # The list is sorted by time, so start at the insertion point and walk outward only as
        # far as `REACH` allows rather than scanning thousands of rows on every level call.
        span = REACH * 60.0
        at = bisect.bisect_left(self.events, (now - span, ""))
        best: float | None = None
        for when, code in self.events[at:]:
            if when > now + span:
                break
            if code not in codes:
                continue
            minutes = (now - when) / 60.0
            if best is None or abs(minutes) < abs(best):
                best = minutes
        return best

    def expect(self, feed: str, now: float) -> float | None:
        """The measured volatility multiple for where this feed sits relative to a release.

        `None` when no important release is within reach, which is most of the time.
        """
        minutes = self.nearest(feed, now)
        if minutes is None or abs(minutes) > REACH:
            return None
        if minutes < PROFILE[0][0]:
            return None
        # Step through the measured windows rather than interpolating between them. The entries
        # are cumulative realised volatility over distinct windows, so a straight line between
        # two of them is not a quantity anything measured.
        answer = PROFILE[0][1]
        for offset, multiple in PROFILE[:-1]:
            if minutes >= offset:
                answer = multiple
        return answer

    def features(self, feed: str, now: float) -> dict[str, float]:
        """Release proximity as floats, for a signal's feature dictionary.

        Empty when nothing is near, so this is a no-op on a deployment with no news service
        rather than a missing key downstream - the same contract `Macro.features` keeps.
        """
        minutes = self.nearest(feed, now)
        if minutes is None or abs(minutes) > REACH:
            return {}
        multiple = self.expect(feed, now)
        out = {"release_minutes": round(minutes, 2)}
        if multiple is not None:
            out["release_vol_multiple"] = multiple
            # Log, so a doubling and a halving are the same distance from normal - the form
            # every other volatility ratio in this codebase is compared in.
            out["release_vol_log"] = round(math.log(multiple), 4)
        return out


#: Codes that also move a currency. The euro is the only one that needs it: the calendar files a
#: German or French print under the country, and it moves the euro.
_ALSO: dict[str, tuple[str, ...]] = {
    "EUR": ("EU", "DE", "FR", "IT", "ES"),
    "USD": ("US",),
    "GBP": ("GB", "UK"),
    "JPY": ("JP",),
    "CAD": ("CA",),
    "AUD": ("AU",),
    "NZD": ("NZ",),
    "CHF": ("CH",),
}


def upcoming(path: str | Path, *, window_days: float = 30.0) -> list[dict]:
    """Important calendar events out of the news store, read-only.

    Shaped like `macro.stored`: the same read-only URI, the same tolerance for a missing file,
    and the same habit of logging rather than raising - a structures service must not fall over
    because a sibling service has not written anything yet.

    A window either side of now rather than the whole table, because only nearby events can
    affect a `Releases` reading and the store holds months of history plus weeks of forecasts.
    """
    edge = time.time()
    span = window_days * 86_400.0
    uri = f"file:{Path(path)}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=5.0)
    except sqlite3.Error as exc:
        log.warning("releases: no calendar at %s: %s", path, exc)
        return []
    try:
        rows = conn.execute(
            "SELECT time, country, importance FROM events"
            " WHERE importance >= ? AND time BETWEEN ? AND ?",
            (IMPORTANT, edge - span, edge + span),
        ).fetchall()
    except sqlite3.Error as exc:
        log.warning("releases: could not read %s: %s", path, exc)
        return []
    finally:
        conn.close()
    return [{"time": when, "country": code, "importance": rank} for when, code, rank in rows]
