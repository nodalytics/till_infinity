"""Validate a journalled per-level direction posterior, with the touches spaced.

Asked on 2026-10-14: *check probability_up on the journalled touches.*

## Two separate contaminations, and only one of them is arithmetic

**The recorded number is post-hoc.** An outcome entry is written after its touch
resolves and carries the **updated** posterior beside the realised push, so the
AUC read straight off it is 0.9280 - and exactly **1.0000** on daily. The
journalled `up_rate` is pinned at exactly 1.0 on 47.5% of up pushes and 0.0 on
48.3% of down ones. Both numbers contain the event they are being scored
against.

**And the history is not a sequence of independent touches.** Removing one
touch arithmetically does not help, because removing one from an all-up history
leaves an all-up history. The reason it is all-up is spacing: **49% of
consecutive 1m touches of the same level land within five bars, and 98.7% of
daily ones**, so eight "touches" are eight samples of one move and every one
records its direction.

So the sequence has to be rebuilt from the touch rows, with a minimum spacing,
and the posterior walked forward over earlier spaced touches only. That is what
this does, and the spacing is a sweep rather than a setting because the decay
across it is the result:

    none      149,582 scored   AUC 0.6566
    1 bar      78,068          AUC 0.5848
    5 bars     54,615          AUC 0.5453
    20 bars    30,759          AUC 0.5167
    40 bars    21,501          AUC 0.5092

The unspaced figure is the one this desk had been quoting. At 21,501 scored
touches an AUC of 0.6566 would be about thirty sigma, so the decay is not a loss
of power.

The input is a CSV of journalled touch outcomes - time, feed, interval, level,
push_vol - extracted from the production journal at idle priority and kept
outside this repository, which is public. `JOURNAL_CSV` points at it.
"""

from __future__ import annotations

import bisect
import collections
import csv
import gzip
import os
import statistics
import sys

#: Seconds a bar covers, per journalled interval name.
BARS = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "daily": 86400,
    "weekly": 604800,
}
#: Production's own prior and weight, from `levels.SideStats.probability_up`.
PRIOR, WEIGHT = 0.5, 4.0
#: Touches a level needs before its posterior is allowed to speak, matching
#: production's warmup.
WARM = int(os.environ.get("WARM", "3"))
SPACINGS = tuple(int(k) for k in os.environ.get("SPACINGS", "0,1,5,20,40").split(","))
PATH = os.environ.get("JOURNAL_CSV", "")


def number(value: str) -> float | None:
    try:
        return float(value)
    except Exception:
        return None


def auc(positive: list[float], negative: list[float]) -> float:
    """Tie-aware, because a posterior over small counts is highly tied."""
    if not positive or not negative:
        return float("nan")
    order = sorted(negative)
    total = 0.0
    for value in positive:
        low = bisect.bisect_left(order, value)
        high = bisect.bisect_right(order, value)
        total += low + 0.5 * (high - low)
    return total / (len(positive) * len(order))


def read(path: str) -> dict[tuple[str, str, float], list[tuple[float, float]]]:
    opener = gzip.open if path.endswith(".gz") else open
    groups: dict[tuple[str, str, float], list[tuple[float, float]]] = collections.defaultdict(list)
    with opener(path, "rt") as handle:
        for row in csv.DictReader(handle):
            push = number(row.get("push_vol", ""))
            when = number(row.get("time", ""))
            level = number(row.get("level", ""))
            if push is None or when is None or level is None or push == 0:
                continue
            # A level's price moves as its filter learns, so rounding is the
            # identity available here - the journal carries no level name.
            groups[(row["feed"], row["interval"], round(level, 4))].append(
                (when, 1.0 if push > 0 else 0.0)
            )
    return groups


def main() -> None:
    if not PATH:
        print("set JOURNAL_CSV to an extract of journalled touch outcomes")
        sys.exit(2)
    groups = read(PATH)
    touches = sum(len(v) for v in groups.values())
    print(f"{len(groups):,} level groups, {touches:,} touches\n")
    print(f"  {'spacing':<16}{'scored':>9}{'levels':>9}{'up rate':>9}{'AUC':>9}")
    for bars in SPACINGS:
        guesses: list[float] = []
        truths: list[float] = []
        used = 0
        for (_feed, interval, _level), history in groups.items():
            gap = BARS.get(interval, 60) * bars
            history.sort()
            spaced: list[float] = []
            last = -1e18
            for when, up in history:
                if when - last >= gap:
                    spaced.append(up)
                    last = when
            if len(spaced) < WARM + 1:
                continue
            used += 1
            ups = 0.0
            for i, up in enumerate(spaced):
                if i >= WARM:
                    guesses.append((PRIOR * WEIGHT + ups) / (WEIGHT + i))
                    truths.append(up)
                ups += up
        if len(truths) < 200:
            print(f"  {f'>= {bars} bars':<16}{len(truths):>9,}   too few")
            continue
        positive = [g for g, t in zip(guesses, truths, strict=True) if t > 0.5]
        negative = [g for g, t in zip(guesses, truths, strict=True) if t < 0.5]
        print(
            f"  {f'>= {bars} bars':<16}{len(truths):>9,}{used:>9,}"
            f"{statistics.fmean(truths):>9.3f}{auc(positive, negative):>9.4f}"
        )
    print(
        "\n  Zero spacing is what the journal implies. Each row down is the same\n"
        "  estimator on touches that cannot be re-samples of one move."
    )


if __name__ == "__main__":
    main()
