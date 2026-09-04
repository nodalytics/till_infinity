"""How late is the momentum reading, as a share of the move it is reading?

The concern is concrete. Confirm halfway through a swing and the entry is
halfway worse while the stop, anchored on structure, has not moved - the same
idea taken at worse reward for identical risk. Measured rather than assumed.

## The unit has to be production's

The first version of this harness invented its own volatility unit - the median
absolute 1m step - and the numbers it produced were unusable: gold came out
with a "typical push" of 17.27 units, which pinned its threshold to the ceiling
and made the filter look hopelessly late on that feed alone. The unit was
wrong, so everything denominated in it was wrong.

Both numbers now come from the journal, which is production's own measurement:

* the volatility unit from `structures.volatility.Volatility`, fed the same
  series - production's own estimator rather than a stand-in for it, converted
  to a price distance the way `sizing` does: `price * vol_bps / 10_000`. It is
  warmed before any measuring starts, because a cold estimator returns its
  floor and every distance read against that floor is nonsense.
* `push_vol` per feed from the journal, the **realised** push on resolved level
  touches, which is what `adaptive_threshold` is a fraction of. There is no
  `vol_bps` on those rows, which is why the unit is recomputed rather than
  read.

## What is measured

For every move of `MOVE` units or more, how far into it each reading first
speaks, and - the number that matters economically - how much of the move is
still ahead when it does.

Two readings, because they have different latencies and the swing gate uses the
earlier one:

* `agreement` - the sign of each member's accumulator, which turns on any net
  progress
* the first `event` - which needs the whole threshold
"""

from __future__ import annotations

import json
import sqlite3
import statistics as st
from collections import defaultdict

from till_infinity.structures.context.cusum import Ensemble, adaptive_threshold
from till_infinity.structures.vol.volatility import Volatility

PRICES = "file:/app/.data/prices/prices.db?mode=ro"
JOURNAL = "file:/app/.data/journal/journal.db?mode=ro"

FEEDS = ["gold", "eurusd", "us100", "btc", "wti", "audjpy"]

#: A move worth catching, in volatility units. Below the median realised push,
#: so this is not only measuring the largest moves.
MOVE = 1.5

#: Bars to replay per feed.
BARS = 40_000


def realised_push() -> dict[str, float]:
    """Per-feed median realised `push_vol`, from the journal."""
    c = sqlite3.connect(JOURNAL, uri=True)
    push: dict[str, list[float]] = defaultdict(list)
    rows = c.execute(
        "select context from entries where actor='structures' and kind='outcome' "
        "order by time desc limit 120000"
    )
    for (blob,) in rows:
        d = json.loads(blob or "{}")
        feed = str(d.get("feed") or "")
        if not feed:
            continue
        p = d.get("push_vol")
        if isinstance(p, int | float) and p:
            push[feed].append(abs(float(p)))
    return {f: st.median(p) for f, p in push.items() if len(p) >= 30}


def closes(feed: str, limit: int = BARS) -> list[float]:
    c = sqlite3.connect(PRICES, uri=True)
    rows = c.execute(
        "select close from bars where feed=? and interval='1m' order by ts desc limit ?",
        (feed, limit),
    ).fetchall()
    return [float(p) for (p,) in reversed(rows)]


def quantiles(vals: list[float]) -> str:
    vals = sorted(vals)

    def q(p: float) -> float:
        return vals[min(len(vals) - 1, int(p * len(vals)))]

    return f"p25 {q(0.25):4.0%}  median {q(0.5):4.0%}  p75 {q(0.75):4.0%}"


def run(feed: str, typical_push: float) -> None:
    prices = closes(feed)
    if len(prices) < 2_000:
        print(f"{feed}: only {len(prices)} bars, skipped")
        return

    # Production's estimator, warmed before anything is measured against it.
    vol = Volatility()
    warm = min(500, len(prices) // 4)
    for price in prices[:warm]:
        vol.update(price)
    if not vol.warm:
        print(f"{feed}: volatility never warmed, skipped")
        return
    prices = prices[warm:]

    threshold = adaptive_threshold(typical_push)
    agree_at: list[float] = []
    event_at: list[float] = []
    moves = 0

    i = 0
    while i < len(prices) - 120:
        start = prices[i]
        # The unit at this price, exactly as `sizing.price_distance` computes it,
        # off the estimator that has been reading this series all along.
        unit = abs(start * vol.bps / 10_000)
        if unit <= 0:
            break
        end = None
        for j in range(i + 1, min(i + 120, len(prices))):
            if abs(prices[j] - start) / unit >= MOVE:
                end = j
                break
        if end is None:
            i += 30
            continue

        moves += 1
        want_up = prices[end] > start
        span = abs(prices[end] - start)

        group = Ensemble(intervals=("1m", "3m", "5m", "15m"), threshold=threshold)
        first_agree = first_event = None
        for k in range(i, end + 1):
            vol.update(prices[k])
            group.push(prices[k], unit, when=k * 60.0)
            done = abs(prices[k] - start) / span if span else 0.0
            if first_agree is None and group.ready:
                facing = group.agreement if want_up else -group.agreement
                if facing >= 0.5:
                    first_agree = done
            if first_event is None and any(m.events for m in group.members.values()):
                first_event = done
        if first_agree is not None:
            agree_at.append(first_agree)
        if first_event is not None:
            event_at.append(first_event)
        i = end + 1

    print(
        f"\n{feed}: {moves} moves of {MOVE}v+  ·  push {typical_push:.2f}v  ·  "
        f"threshold {threshold:.2f}v  ·  vol {vol.bps:.1f}bps"
    )
    for name, vals in (("agreement >= 0.5", agree_at), ("first CUSUM event", event_at)):
        if not vals:
            print(f"   {name:20s} never spoke")
            continue
        spoke = len(vals) / moves if moves else 0.0
        left = 1.0 - st.median(vals)
        print(f"   {name:20s} {quantiles(vals)}   spoke in {spoke:5.1%} of moves")
        print(f"   {'':20s} {left:.0%} of the move still ahead at the median")


def main() -> None:
    push = realised_push()
    print("units from structures.Volatility; typical push from the journal")
    for feed in FEEDS:
        if feed not in push:
            print(f"\n{feed}: no realised push in the journal, skipped")
            continue
        run(feed, push[feed])


if __name__ == "__main__":
    main()
