"""How often do all of `origin-swing`'s conditions hold at once?

It has never appeared in the journal. That is either because the setup is rare
or because it cannot happen at all, and those need different responses: a rare
setup is worth waiting for, an impossible one is a strategy that will never
produce evidence either way and should be loosened or dropped.

Read as a funnel over the signals `trading` actually saw, in the order the
strategy applies them, so the first condition that empties the set is the one
that matters. Everything is read from journalled features rather than
recomputed, because what the strategy sees is the published signal and not
whatever a replay would derive.

The conditions, from `swing.py`:

* the call arrives on the **1h** entry interval
* at least one **compulsory context** timeframe agrees - 2h, 4h, 1d or 1w
* an origin exists **above and below**, price between them
* price has **reached** one, within `REACH_VOL`
* that origin is **fresh** - at most `max_revisits` returns
* the sub-hour momentum ensemble **agrees**, when it is warm
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter

JOURNAL = "file:/app/.data/journal/journal.db?mode=ro"
LIMIT = 200_000

REACH_VOL = 0.25
MAX_REVISITS = 1.0
MIN_AGREE = 0.5
CONTEXT = {"2h", "4h", "1d", "1w"}


def rows() -> list[dict]:
    c = sqlite3.connect(JOURNAL, uri=True)
    out = []
    for (blob,) in c.execute(
        "select context from entries where actor='trading' order by time desc limit ?",
        (LIMIT,),
    ):
        try:
            out.append(json.loads(blob or "{}"))
        except ValueError:
            continue
    return out


def main() -> None:
    seen = rows()
    print(f"{len(seen)} trading rows\n")

    steps: list[tuple[str, int]] = []
    at = seen
    steps.append(("every signal seen", len(at)))

    at = [d for d in at if str(d.get("interval") or "") == "1h"]
    steps.append(("on the 1h entry interval", len(at)))

    def agrees(d: dict) -> bool:
        conf = d.get("confluence")
        if isinstance(conf, str):
            conf = [t.strip() for t in conf.split(",")]
        return bool(CONTEXT & {str(t) for t in (conf or [])})

    at = [d for d in at if agrees(d)]
    steps.append(("a compulsory timeframe agrees", len(at)))

    at = [
        d
        for d in at
        if "origin_below_high" in d
        and "origin_above_low" in d
        and float(d["origin_below_high"]) < float(d["origin_above_low"])
    ]
    steps.append(("an origin above and below", len(at)))

    def reached(d: dict) -> bool:
        above = d.get("origin_above_vol")
        below = d.get("origin_below_vol")
        if above is None or below is None:
            return False
        return min(float(above), float(below)) <= REACH_VOL

    at = [d for d in at if reached(d)]
    steps.append(("price has reached one", len(at)))

    def fresh(d: dict) -> bool:
        above, below = d.get("origin_above_vol"), d.get("origin_below_vol")
        if above is None or below is None:
            return False
        key = "origin_below_revisits" if float(below) <= float(above) else "origin_above_revisits"
        n = d.get(key)
        return n is None or float(n) <= MAX_REVISITS

    at = [d for d in at if fresh(d)]
    steps.append(("the origin is fresh", len(at)))

    def momentum(d: dict) -> bool:
        if not d.get("momentum_ready"):
            return True  # silent while cold, by design
        above, below = d.get("origin_above_vol"), d.get("origin_below_vol")
        buy = float(below or 9e9) <= float(above or 9e9)
        agree = float(d.get("momentum_agree") or 0.0)
        return (agree if buy else -agree) >= MIN_AGREE

    at = [d for d in at if momentum(d)]
    steps.append(("the sub-hour timeframes agree", len(at)))

    widest = max(len(name) for name, _ in steps)
    start = steps[0][1] or 1
    previous = start
    for name, count in steps:
        share = count / start
        lost = previous - count
        note = f"   (-{lost})" if lost else ""
        print(f"   {name:<{widest}s} {count:7d}  {share:7.2%}{note}")
        previous = count

    print()
    if not at:
        empty = next((n for (n, c), (_, p) in zip(steps[1:], steps, strict=False) if c == 0 and p), None)
        print(f"nothing survives. the set empties at: {empty}")
    else:
        print(f"{len(at)} signals cleared every condition")
        by_feed = Counter(str(d.get("feed")) for d in at)
        for feed, n in by_feed.most_common(8):
            print(f"   {feed:12s} {n}")


if __name__ == "__main__":
    main()
