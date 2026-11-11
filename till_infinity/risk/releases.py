"""Scheduled releases, and the volatility multiple each one implies.

**The calendar is one of two things this desk has measured forecastable**, and
it is the one that needs no model of the future: release times are published
days ahead. `research/docs/news-volatility.md`, over three instruments against
a matched control median:

| window | x normal | 95% interval |
| --- | ---: | --- |
| pre -2h to -30m | **0.789** | [0.757, 0.872] |
| the print's own bar | **2.424** | [2.075, 2.612] |
| +30m | 1.762 | [1.569, 2.432] |
| +1h | 1.349 | [1.309, 1.440] |
| +2h | 1.120 | [1.032, 1.185] |
| +4h | **0.920** | [0.883, 0.972] |

**Every interval excludes 1.0** and both halves of the sample agree in sign at
every horizon. The spike is large and short, and it overshoots then undershoots
- by four hours realised volatility is *below* normal.

## This is a volatility statement and never a direction one

`seasonality-belongs-on-q` is the standing rule and this obeys it: the multiple
drives **Q**, never R. A release moves how far price goes, not which way, and
`break-features.md` measured exactly that - the calendar moves volatility and
does **not** move the probability that a level breaks.

## Ported rather than rewritten

This shipped as `structures/context/releases.py` on the service that retired on
2026-10-29, publishing three features and **deciding nothing**. The profile,
the reach, the importance threshold and the sign convention are that file's,
because they are what was measured; what changed is the currency map, which now
comes from `risk/exposure.legs` - the live one, fixed on 2026-11-10 after it
had gone stale at the migration and returned `("", "")` for 22 of the 30
deployed symbols.
"""

from __future__ import annotations

import bisect
import math
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .exposure import declared, legs

#: Importance at or above which a release is carried. The store grades 0, 1 and
#: 2, and **the measurement was made on 2** - so this is the number that was
#: measured rather than a preference. The live store holds 398 rows at this
#: grade against 3,004 at grade 0.
IMPORTANT = 2

#: Measured cumulative realised-volatility multiples, as `(minutes from the
#: release, multiple)`.
#:
#: Each entry is the realised volatility from the release to that offset over
#: the matched control median - **cumulative windows, not per-slice rates**.
#: Read "at +60 minutes the hour since the print carried 1.35 times normal
#: volatility", which is what was measured; inventing a per-minute rate from it
#: would be modelling past the data.
#:
#: The negative entry is the pre-release lull, and it is the one knowable
#: furthest ahead.
#:
#: **Each entry labels the interval that begins at its offset**, so a caller 45
#: minutes past a print reads the `30.0` row. That makes the final entry a
#: boundary rather than a usable step: `0.920` is the realised volatility over
#: the *whole* four hours after a release, a statement about a window and not
#: about a moment, so it marks where reach ends.
PROFILE: tuple[tuple[float, float], ...] = (
    (-120.0, 0.789),
    (0.0, 2.424),
    (30.0, 1.762),
    (60.0, 1.349),
    (120.0, 1.120),
    (240.0, 0.920),
)

#: Beyond this many minutes either side a release says nothing and no multiple
#: is returned. `None` rather than 1.0, because **"no opinion" and "expect
#: normal volatility" are different claims** and a journal has to tell them
#: apart.
REACH = 240.0

#: Codes that also move a currency. The euro is the one that needs it: a German
#: or French print is filed under the country and moves the euro.
ALSO: dict[str, tuple[str, ...]] = {
    "EUR": ("EU", "DE", "FR", "IT", "ES"),
    "USD": ("US",),
    "GBP": ("GB", "UK"),
    "JPY": ("JP",),
    "CAD": ("CA",),
    "AUD": ("AU",),
    "NZD": ("NZ",),
    "CHF": ("CH",),
}


@dataclass(slots=True)
class Releases:
    """Scheduled releases, and what they imply for one feed right now."""

    #: `(when, code)` for important releases, sorted by time. Floats and
    #: strings only, so this survives being published on a bus.
    events: list[tuple[float, str]] = field(default_factory=list)

    def note(self, rows: Any) -> int:
        """Take calendar rows. Returns how many are now held.

        Accepts anything with `time`, `importance` and `country` - a mapping or
        an object - so this does not import the news models and the two stay
        uncoupled.
        """
        held = set(self.events)
        for row in rows or ():
            get = row.get if hasattr(row, "get") else lambda name, _r=row: getattr(_r, name, None)
            try:
                when = float(get("time") or 0.0)
                rank = int(get("importance") or 0)
            except (TypeError, ValueError):
                continue
            code = str(get("country") or "").strip().upper()
            if when > 0.0 and rank >= IMPORTANT and code:
                held.add((when, code))
        self.events = sorted(held)
        return len(self.events)

    def codes(self, feed: str) -> tuple[str, ...]:
        """The codes a feed answers to, as the calendar spells them.

        Providers label the same print differently - one by ISO country, one by
        currency - so both are matched.

        **A feed nobody mapped answers to nothing.** `register_broker_legs`
        gives every unknown broker symbol a `USD` quote leg, which is right for
        netting exposure and wrong here: it would make a US print widen the
        stop on `Volatility 75 Index`, whose generator is a broker's RNG and is
        independent of the world by construction. That is a cheap error in the
        band - a floor only ever widens - and an expensive one in the features,
        where it would pool a known generator with the measured FX sample under
        a "near a print" label. `news-volatility.md` says the same thing about
        its own reach: three instruments measured against thirty-two traded.
        """
        if not declared(feed):
            return ()
        base, quote = legs(feed)
        out: set[str] = set()
        for code in (base, quote):
            if not code:
                continue
            out.add(code)
            out.update(ALSO.get(code, ()))
        return tuple(sorted(out))

    def nearest(self, feed: str, now: float) -> float | None:
        """Minutes to the closest important release touching this feed.

        **Negative before the print and positive after it**, since it is
        `now - when`. Getting that backwards would read the post-release spike
        as the pre-release lull and size *up* into the quietest window of the
        day, so it is stated here and pinned by a test.
        """
        if not self.events:
            return None
        codes = self.codes(feed)
        if not codes:
            return None
        span = REACH * 60.0
        # Sorted by time, so start at the insertion point and walk outward only
        # as far as `REACH` allows rather than scanning every row per bar.
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
        """The measured multiple for where this feed sits against a release.

        `None` when nothing important is within reach, which is most of the
        time. **Stepped, not interpolated**: the entries are cumulative
        realised volatility over distinct windows, so a straight line between
        two of them is not a quantity anything measured.
        """
        minutes = self.nearest(feed, now)
        if minutes is None or abs(minutes) > REACH or minutes < PROFILE[0][0]:
            return None
        answer = PROFILE[0][1]
        for offset, multiple in PROFILE[:-1]:
            if minutes >= offset:
                answer = multiple
        return answer

    def features(self, feed: str, now: float) -> dict[str, float]:
        """Release proximity as floats, for an intent's features.

        Empty when nothing is near, so a deployment with no calendar records
        nothing rather than a missing key downstream.
        """
        minutes = self.nearest(feed, now)
        if minutes is None or abs(minutes) > REACH:
            return {}
        out = {"release_minutes": round(minutes, 2)}
        multiple = self.expect(feed, now)
        if multiple is not None:
            out["release_vol_multiple"] = multiple
            # Log, so a doubling and a halving sit the same distance from
            # normal - the form every other volatility ratio here is compared in.
            out["release_vol_log"] = round(math.log(multiple), 4)
        return out


def upcoming(path: str | Path, *, window_days: float = 30.0, now: float = 0.0) -> list[dict]:
    """Important calendar rows within `window_days` either side, read-only.

    A missing or unreadable store returns nothing rather than raising: the
    calendar is a feature and a desk without one must size as it did before.
    """
    import time as _time

    at = now or _time.time()
    span = window_days * 86_400.0
    try:
        link = sqlite3.connect(f"file:{Path(path)}?mode=ro", uri=True)
    except sqlite3.Error:
        return []
    try:
        rows = link.execute(
            "select time, importance, country from events "
            "where importance >= ? and time between ? and ?",
            (IMPORTANT, at - span, at + span),
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        link.close()
    return [{"time": r[0], "importance": r[1], "country": r[2]} for r in rows]


__all__ = ["ALSO", "IMPORTANT", "PROFILE", "REACH", "Releases", "upcoming"]
