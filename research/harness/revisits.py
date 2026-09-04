"""Do origins hold when price comes back to them, and for how many visits?

The question that decides whether origins are worth trading. An origin is where
volatility turned and the impulse that followed broke structure, so the claim is
that unfilled interest was left behind. If that claim is true, price returning
to the zone should be turned away - and the claim should weaken each time the
zone is revisited, because each visit is interest being filled.

This is the direct test. Earlier work found never-revisited origins returned
1.136R against 0.822R for twice-revisited, which is the same shape read through
trade outcomes; this reads it off price directly, and separates the visits.

## What counts as a bounce

Price is *in* the zone when it trades between its low and high. From the first
bar inside, the origin held if price left in the direction the impulse went,
by `BOUNCE_VOL` volatility units, **before** running through the far side of
the zone by `BREAK_VOL`. Whichever happens first decides it, so a zone that is
sliced through and recovers is not counted as holding.

The far side matters: a demand origin is broken by trading below its low, not
by failing to rally. A zone that price sits inside indefinitely is neither -
it is unresolved, and is counted separately rather than as a win.
"""

from __future__ import annotations

import sqlite3
import statistics as st
from collections import defaultdict

from till_infinity.structures.drawing.origins import Origins
from till_infinity.structures.vol.volatility import Volatility

PRICES = "file:/app/.data/prices/prices.db?mode=ro"
FEEDS = ["gold", "eurusd", "us100", "btc", "spx500", "ger40"]

#: How far price must travel away from the zone to have bounced.
BOUNCE_VOL = 1.0

#: How far through the far side it must go to have broken.
BREAK_VOL = 0.5

#: Bars to read per feed, and the interval.
BARS = 20_000
INTERVAL = "5m"

#: Visits past this are pooled - there are few of them and each is thin.
MAX_VISIT = 4


def closes(feed: str) -> list[float]:
    c = sqlite3.connect(PRICES, uri=True)
    rows = c.execute(
        "select close from bars where feed=? and interval=? and venue='OANDA' "
        "order by ts desc limit ?",
        (feed, INTERVAL, BARS),
    ).fetchall()
    if len(rows) < 1_000:
        rows = c.execute(
            "select close from bars where feed=? and interval=? order by ts desc limit ?",
            (feed, INTERVAL, BARS),
        ).fetchall()
    return [float(p) for (p,) in reversed(rows)]


def visits(prices: list[float], origin, unit: float, start: int) -> list[str]:
    """Outcome of each *return* to this origin's zone, in order.

    **The impulse has to leave before anything counts.** The zone is the bar at
    the turn, so price is still inside it for the first bars after - and
    counting from there measures the launching impulse itself, which by
    construction goes the right way. That read 92.6% on the first visit; it was
    the move that defined the origin being scored as a reaction to it.
    """
    up = origin.launched == "up"
    out: list[str] = []
    i = start
    # Leave the zone first.
    while i < len(prices) and origin.low <= prices[i] <= origin.high:
        i += 1
    if i >= len(prices):
        return out
    while i < len(prices):
        # Wait until price is inside the zone.
        while i < len(prices) and not (origin.low <= prices[i] <= origin.high):
            i += 1
        if i >= len(prices):
            break
        entered = i
        verdict = "open"
        while i < len(prices):
            price = prices[i]
            if up:
                if price >= origin.high + BOUNCE_VOL * unit:
                    verdict = "held"
                    break
                if price <= origin.low - BREAK_VOL * unit:
                    verdict = "broke"
                    break
            else:
                if price <= origin.low - BOUNCE_VOL * unit:
                    verdict = "held"
                    break
                if price >= origin.high + BREAK_VOL * unit:
                    verdict = "broke"
                    break
            i += 1
        out.append(verdict)
        if verdict in ("broke", "open"):
            # A broken origin is finished; an unresolved one ran out of series.
            break
        # Held: wait for price to leave before counting another visit.
        while i < len(prices) and origin.low <= prices[i] <= origin.high:
            i += 1
        del entered
    return out


def run(feed: str) -> dict[int, list[str]]:
    prices = closes(feed)
    if len(prices) < 2_000:
        print(f"{feed}: only {len(prices)} bars, skipped")
        return {}
    vol = Volatility()
    for p in prices[:400]:
        vol.update(p)
    if not vol.warm:
        print(f"{feed}: volatility never warmed")
        return {}
    unit = abs(st.median(prices) * vol.bps / 10_000)
    times = [float(i) for i in range(len(prices))]

    found = Origins().observe(times, prices, unit)
    by_visit: dict[int, list[str]] = defaultdict(list)
    for origin in found:
        # `times` is the bar index here, so `when` is where the origin sits -
        # `prices.index(origin.price)` would find the first bar that happens to
        # share that price, which is usually but not always the same bar.
        start = int(origin.when) + 1
        if start >= len(prices):
            continue
        for n, verdict in enumerate(visits(prices, origin, unit, start), start=1):
            by_visit[min(n, MAX_VISIT)].append(verdict)
    print(f"{feed}: {len(found)} origins with a break of structure")
    return by_visit


def show(title: str, by_visit: dict[int, list[str]]) -> None:
    print(f"\n{title}")
    print(f"   {'visit':>7s} {'n':>6s} {'held':>7s} {'broke':>7s} {'unresolved':>11s}")
    for n in sorted(by_visit):
        rows = by_visit[n]
        if not rows:
            continue
        held = sum(1 for r in rows if r == "held") / len(rows)
        broke = sum(1 for r in rows if r == "broke") / len(rows)
        open_ = sum(1 for r in rows if r == "open") / len(rows)
        label = f"{n}" if n < MAX_VISIT else f"{MAX_VISIT}+"
        print(f"   {label:>7s} {len(rows):6d} {held:6.1%} {broke:6.1%} {open_:10.1%}")


def main() -> None:
    pooled: dict[int, list[str]] = defaultdict(list)
    for feed in FEEDS:
        got = run(feed)
        for n, rows in got.items():
            pooled[n].extend(rows)
        if got:
            show(f"  {feed}", got)
    show("ALL FEEDS", pooled)


if __name__ == "__main__":
    main()
