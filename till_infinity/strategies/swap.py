"""The overnight swap a position pays for being held across the rollover.

`research/docs/carry.md` measured what the broker charges to hold: about the interbank
differential plus a markup on FX, and on the 24/7 synthetics an annual rate on **both** sides -
Boom 1000 36% a year, about 10 bps a night, Crash 1000 about 5. A trade planned to hold across the
17:00 New York rollover pays it, and neither spread gate sees it. `expected` prices it for the
risk check, over the strategy's planned hold, from the broker's own symbol info:

  swap_mode 1  points: a night costs `-swap * point` in price (EURUSD long -11.42, Range Break 100
               -30 on both sides)
  swap_mode 5  annual interest % of the current price: a night costs `-price * swap / 100 / 365`
               (every Deriv index and crypto on this broker)

Nights are the 17:00 New York rollovers the hold crosses. The one on the broker's triple day
(`swap_rollover3days`, Wednesday for FX) is charged three times, and FX does not roll on Saturday
or Sunday; a 24/7 symbol (`swap_rollover3days` 7) rolls every night once. Where the broker's symbol
info carries no swap, the Deriv table below - measured from this broker on 2026-09-30 - stands in.
A negative swap is a cost; a positive one, a credit, is not counted as a reason to trade.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from .models import Side, SymbolSpec

NEW_YORK = ZoneInfo("America/New_York")
ROLLOVER = time(17, 0)
POINTS, INTEREST = 1, 5
DAYS_A_YEAR = 365.0
NO_TRIPLE = 7

#: `(long, short, mode)` for Deriv indices when the broker's symbol info carries no swap. Read from
#: the broker's symbol info on 2026-09-30; all roll every night (no triple day).
DERIV_FALLBACK: dict[str, tuple[float, float, int]] = {
    "boom_1000_index": (-36.0, -36.0, INTEREST),
    "crash_1000_index": (-18.0, -18.0, INTEREST),
    "volatility_75_index": (-7.5, -7.5, INTEREST),
    "volatility_10_index": (-1.0, -1.0, INTEREST),
    "jump_50_index": (-7.0, -7.0, INTEREST),
    "step_index": (-1.0, -1.0, INTEREST),
    "range_break_100_index": (-30.0, -30.0, POINTS),
}


def _mt5_weekday(day: datetime) -> int:
    """MetaTrader numbers weekdays from Sunday = 0; Python from Monday = 0."""
    return (day.weekday() + 1) % 7


def nights(start: float, hold_s: float, triple_day: int) -> float:
    """Swap nights charged over `[start, start + hold_s]`, counting the triple day three times."""
    if hold_s <= 0:
        return 0.0
    end = start + hold_s
    local = datetime.fromtimestamp(start, UTC).astimezone(NEW_YORK)
    day = local.date()
    total = 0.0
    while True:
        at = datetime.combine(day, ROLLOVER, NEW_YORK)
        stamp = at.timestamp()
        if stamp > end:
            return total
        if stamp > start:
            weekday = _mt5_weekday(at)
            if triple_day == NO_TRIPLE:
                total += 1.0
            elif weekday not in (6, 0):  # no rollover on Saturday; Sunday 17:00 is the open
                total += 3.0 if weekday == triple_day else 1.0
        day += timedelta(days=1)


def _terms(spec: SymbolSpec | None, feed: str) -> tuple[float, float, int, int] | None:
    if spec is not None and spec.swap_mode in (POINTS, INTEREST):
        return spec.swap_long, spec.swap_short, spec.swap_mode, spec.swap_triple_day
    got = DERIV_FALLBACK.get(feed)
    if got is not None:
        return got[0], got[1], got[2], NO_TRIPLE
    return None


def expected(
    spec: SymbolSpec | None, feed: str, side: Side, price: float, start: float, hold_s: float
) -> float:
    """The swap cost, in price units, of holding one unit from `start` for `hold_s` seconds.

    Positive is a cost. Zero when the hold crosses no rollover, when nothing is known about the
    symbol's swap, or when the side is credited rather than charged.
    """
    terms = _terms(spec, feed)
    if terms is None or price <= 0:
        return 0.0
    long_, short, mode, triple = terms
    count = nights(start, hold_s, triple)
    if count <= 0:
        return 0.0
    rate = long_ if side is Side.BUY else short
    if mode == POINTS:
        point = spec.point if spec is not None else 0.1
        per_night = -rate * point
    else:
        per_night = -price * rate / 100.0 / DAYS_A_YEAR
    return max(0.0, per_night * count)
