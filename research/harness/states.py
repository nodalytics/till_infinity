"""Does a level's behaviour change over its life, or is it one coin all along?

Run from the repository root:  python research/harness/states.py

`Inference.probability_up` pools every touch a level has ever had, equally. A
support that held six times and then broke is **averaged with itself**: the
level's behaviour changed and the statistic cannot say so. The proposal is a
per-level state model — {respected, breaking, flipped} with transitions — so
that "it has flipped" becomes a discrete, reportable event with a probability
on it.

The sample size objection is the right one. Levels here carry 4-20 touches, and
estimating even a two-state transition matrix from six observations is fitting
noise confidently. The honest form is hierarchical: one transition model pooled
across every level, per-level state inferred. That is a real modelling project.

**So this measures the premise first, because the premise is cheap and the
project is not.** If a level's next outcome is no better predicted by its
*recent* touches than by all of them pooled, there is no state to infer and the
hierarchical model would be machinery around nothing.

    pooled     the up-rate over every prior same-side touch
    recent     the up-rate over the last few
    last       what happened the single most recent time

Three questions, in the order that decides whether to build anything:

1. **Is behaviour stationary?** Split each level's touches in half by time and
   compare the two halves. If the up-rate is the same, pooling is fine.
2. **Does recency beat pooling** at predicting the next outcome?
3. **Do runs exist?** A level that alternates hold/fail/hold/fail has no state;
   one that holds five times then fails five times does.
"""

from __future__ import annotations

import collections
import itertools
import math
import pickle
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from edge_gate import INTERVALS, bars

from till_infinity.structures.engine import Engine

CACHE = Path(__file__).with_name("states.pkl")

#: Prior same-side touches a level needs before it is asked anything. Four is
#: the bottom of the range levels actually reach.
MIN_HISTORY = 4


def collect():
    """Every touch, in order, tagged with the level it happened at."""
    if CACHE.exists():
        return pickle.loads(CACHE.read_bytes())
    engine = Engine(intervals=INTERVALS)
    rows: list[dict] = []
    for bar in bars(INTERVALS):
        engine.observe_bar(bar)
        for level, touch in engine.drain_resolved():
            if not touch.push_vol:
                continue
            above = touch.features.side.name == "ABOVE"
            rows.append(
                {
                    # The level object, not its price: a level is a Kalman
                    # filter whose mean moves on every touch it absorbs, so a
                    # price key would make each touch a different level.
                    "level": id(level),
                    "feed": touch.feed,
                    "interval": touch.interval,
                    "above": above,
                    "when": float(touch.started),
                    "outcome": str(touch.outcome).split(".")[-1].lower(),
                    "up": touch.push_vol > 0,
                    # The trivial rule's trade: did the level do its job.
                    "held": (touch.push_vol > 0) == above,
                }
            )
    CACHE.write_bytes(pickle.dumps(rows))
    return rows


def sequences(rows, per_side: bool = True):
    """Each level's touches in order, optionally split by the side they came from."""
    found: dict[tuple, list[dict]] = collections.defaultdict(list)
    for row in sorted(rows, key=lambda r: r["when"]):
        key = (row["level"], row["above"]) if per_side else (row["level"],)
        found[key].append(row)
    return {k: v for k, v in found.items() if len(v) >= MIN_HISTORY}


def wilson(hits: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if not n:
        return 0.0, 1.0
    p = hits / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(centre - half, 0.0), min(centre + half, 1.0)


def main() -> None:
    rows = collect()
    runs = sequences(rows)
    touches = sum(len(v) for v in runs.values())
    print(f"{len(rows):,} resolved touches")
    print(f"{len(runs):,} level-sides with at least {MIN_HISTORY} touches, {touches:,} touches\n")

    lengths = sorted(len(v) for v in runs.values())
    print("=== 0. how much history a level actually has")
    for q in (50, 75, 90, 99, 100):
        print(f"    p{q:<4} {lengths[min(int(len(lengths) * q / 100), len(lengths) - 1)]:>4} touches")
    print(f"    a two-state transition matrix needs four counts; the median level has {lengths[len(lengths) // 2]}")

    print("\n=== 1. is behaviour stationary — first half against second")
    firsts = seconds = first_held = second_held = 0
    moved = []
    for group in runs.values():
        half = len(group) // 2
        early, late = group[:half], group[half:]
        if not early or not late:
            continue
        firsts += len(early)
        seconds += len(late)
        first_held += sum(1 for r in early if r["held"])
        second_held += sum(1 for r in late if r["held"])
        moved.append(
            sum(1 for r in late if r["held"]) / len(late)
            - sum(1 for r in early if r["held"]) / len(early)
        )
    print(f"    first half  held {first_held / firsts:.1%} of {firsts:,}")
    print(f"    second half held {second_held / seconds:.1%} of {seconds:,}")
    print(f"    mean within-level change {statistics.fmean(moved):+.3f}")
    print(f"    median |change| {statistics.median(abs(m) for m in moved):.3f}")

    print("\n=== 2. does recency beat pooling at predicting the next touch")
    print(f"    {'predictor':<22} {'n':>7} {'right':>8}")
    print("    " + "-" * 40)
    scores: dict[str, list[bool]] = collections.defaultdict(list)
    for group in runs.values():
        for i in range(MIN_HISTORY, len(group)):
            past, now = group[:i], group[i]
            pooled = sum(1 for r in past if r["held"]) / len(past)
            recent = sum(1 for r in past[-3:] if r["held"]) / len(past[-3:])
            scores["pooled (what we do)"].append((pooled > 0.5) == now["held"])
            scores["last three"].append((recent > 0.5) == now["held"])
            scores["the last one only"].append(past[-1]["held"] == now["held"])
            scores["always 'it holds'"].append(now["held"])
    for name, hits in scores.items():
        print(f"    {name:<22} {len(hits):>7} {sum(hits) / len(hits):>7.1%}")

    print("\n=== 3. do runs exist, or does it alternate")
    swaps = total = 0
    for group in runs.values():
        held = [r["held"] for r in group]
        swaps += sum(1 for a, b in itertools.pairwise(held) if a != b)
        total += len(held) - 1
    rate = sum(1 for r in rows if r["held"]) / len(rows)
    chance = 2 * rate * (1 - rate)
    print(f"    consecutive touches that differ: {swaps / total:.1%} of {total:,}")
    print(f"    expected from independent coins: {chance:.1%}")
    print(f"    {'runs are longer than chance' if swaps / total < chance else 'NO run structure'}")

    print("\n=== 4. the flip — does a level that fails twice keep failing")
    after: dict[str, list[bool]] = collections.defaultdict(list)
    for group in runs.values():
        held = [r["held"] for r in group]
        for i in range(2, len(held)):
            if not held[i - 1] and not held[i - 2]:
                after["after two failures"].append(held[i])
            elif held[i - 1] and held[i - 2]:
                after["after two holds"].append(held[i])
    print(f"    {'state':<22} {'n':>7} {'next one holds':>16} {'95%':>18}")
    print("    " + "-" * 66)
    for name, seen in after.items():
        hits = sum(seen)
        lo, hi = wilson(hits, len(seen))
        print(f"    {name:<22} {len(seen):>7} {hits / len(seen):>15.1%} {f'{lo:.1%} - {hi:.1%}':>18}")
    print(f"    {'pooled':<22} {len(rows):>7} {rate:>15.1%}")


if __name__ == "__main__":
    main()
