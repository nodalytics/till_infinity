"""The FX daily rollover, masked out of what the levels learn.

At 17:00 New York the FX broker rolls positions to the next value date, and for a few minutes the
spread widens several-fold. On bid-based bars that prints a wick through nearby levels and back,
which the touch tracker reads as a real interaction, most often a trap.
`research/docs/rollover.md` measured it on the journal:

- 14.7% of weekday FX call outcomes resolved at 21:00 UTC, against 2.5-6.7% in any other hour;
- traps rose to 19% (9-16% elsewhere) and breaks fell to 1%;
- on FX 15m and 30m, 41-46% of outcomes resolved in 21-22 UTC, where an even spread is 8.3%.

Deriv, metals and crypto were flat, because they have no FX rollover.

So, for FX feeds only, a price update that falls in the window neither opens a touch nor resolves
one, and does not advance the symmetric races. The window is set in New York time, so it follows
daylight saving: 21:00 UTC in the northern summer, 22:00 in winter. Levels still form from these
bars, and touches opened outside the window are carried through it untouched and judged on the
prices after it.

`STRUCTURES_ROLLOVER_MASK=0` turns it off.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, time, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

ENABLED = os.environ.get("STRUCTURES_ROLLOVER_MASK", "1") not in ("0", "false", "no")

NEW_YORK = ZoneInfo("America/New_York")
ROLLOVER = time(17, 0)
#: Minutes masked either side of 17:00 New York. The spread starts widening a few minutes before
#: the roll and takes longer to settle after it.
BEFORE, AFTER = 5, 10

#: A price update spanning more than this is not masked. Every bar of 4h or longer spans 17:00, and
#: masking them would stop a feed whose finest bars are that long from ever touching; the spike is
#: a small part of such a bar's range.
LONGEST = 2 * 3600

#: ISO codes of the currencies a six-letter FX feed is made of. A metal (XAUUSD) or a crypto pair
#: (BTCUSD) also has six letters, which is why the halves are checked, not the length.
CURRENCIES = frozenset(
    [
        "usd",
        "eur",
        "gbp",
        "jpy",
        "chf",
        "aud",
        "nzd",
        "cad",
        "sek",
        "nok",
        "dkk",
        "sgd",
        "hkd",
        "zar",
        "mxn",
        "try",
        "pln",
        "huf",
        "czk",
        "cnh",
    ]
)


@lru_cache(maxsize=4096)
def is_fx(feed: str) -> bool:
    """Whether a feed is a currency pair, from its name: EURUSD, eurusd, EUR/USD, EUR_USD."""
    name = "".join(ch for ch in feed.lower() if ch.isalpha())
    return len(name) == 6 and name[:3] in CURRENCIES and name[3:] in CURRENCIES


@lru_cache(maxsize=1024)
def _window(day: str) -> tuple[float, float]:
    """The masked span around the rollover on one New York calendar day, as epoch seconds."""
    at = datetime.combine(datetime.fromisoformat(day).date(), ROLLOVER, NEW_YORK)
    return (
        (at - timedelta(minutes=BEFORE)).timestamp(),
        (at + timedelta(minutes=AFTER)).timestamp(),
    )


def masked(feed: str, start: float, end: float | None = None) -> bool:
    """Whether a price update spanning `[start, end]` (a quote when `end` is None) touches the
    rollover window on an FX feed."""
    if not ENABLED or not is_fx(feed):
        return False
    end = start if end is None else end
    if end < start:
        start, end = end, start
    if end - start > LONGEST:
        return False
    # Every New York day the span can reach: a bar is at most a day long, so the days of its two
    # ends cover it.
    first = datetime.fromtimestamp(start, UTC).astimezone(NEW_YORK).date()
    last = datetime.fromtimestamp(end, UTC).astimezone(NEW_YORK).date()
    day = first
    while day <= last:
        lo, hi = _window(day.isoformat())
        if start <= hi and end >= lo:
            return True
        day += timedelta(days=1)
    return False
