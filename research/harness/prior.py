"""What is `edge` actually measuring, and does the kNN prior earn its place?

Run from the repository root:  python research/harness/prior.py

`infer` builds its probability from two things and compares the result to a
third:

    own     = level.stats(side)                 # this level's own same-side record
    prior   = memory.prior(features)            # 12 nearest by Features.distance
    p       = w * own + (1 - w) * prior
    edge    = p - memory.base_rate_for(feed, interval)

Three measurements say something is wrong with that.

- [similarity.md](../similarity.md): `Features.distance` orders neighbours no
  better than random. Agreement runs 57.8% to 61.6% across every distance band
  over 13.5M pairs, and the 2.00-3.00 band beats the nearest one.
- [features.md](../features.md) §4: the level's own record is worth **+0.004
  AUC** once `side` is known.
- [features.md](../features.md) §3: "assume the level holds" beats the
  published direction at every gate but the highest, and the two agree **89.7%**
  of the time.

## The asymmetry this script was written to test

`neighbours()` filters `touch.features.side is features.side`, so the prior is
**side-conditioned**. `base_rate_for(feed, interval)` is not — it is the
unconditional up-rate for the series.

So `edge` subtracts a side-blind baseline from a side-aware estimate, and most
of what is left is *which side price arrived from*. That would explain the 89.7%
agreement with the trivial rule exactly: `edge` is a noisy re-encoding of
`side`, and the trivial rule is the clean version of the same thing.

If that is right, the fix is not a better model. It is comparing like with like.

## The variants

| | probability | baseline |
|---|---|---|
| `current` | own + kNN prior | unconditional |
| `side base` | own + kNN prior | **side-conditioned** |
| `no knn` | own + side base rate | side-conditioned |
| `base only` | side-conditioned base rate | side-conditioned |
| `holds` | the trivial rule | — |

Every baseline is accumulated **causally** — a call is scored against the rates
as they stood when it was made, never against rates its own outcome helped set.
"""

from __future__ import annotations

import collections
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import numpy
from edge_gate import INTERVALS, bars, key

from till_infinity.structures import reactions
from till_infinity.structures.engine import Engine
from till_infinity.structures.levels import Side

#: How many of a cell's own observations before its side-conditioned rate
#: mostly speaks for itself. Mirrors `reactions.BASE_WEIGHT`.
BASE_WEIGHT = reactions.BASE_WEIGHT

#: Captured by the wrapper below, one row per call.
CAPTURED: list[dict] = []


def watching(original):
    """Record what `infer` combined, without changing what it returns.

    A wrapper rather than a reimplementation: the point is to measure the live
    path, and a second copy of this arithmetic would drift from it.
    """

    def wrapped(level, side, features, memory, vol, price=0.0, cost_vol=0.0):
        own = level.stats(side)
        prior_up, _push, count = memory.prior(features)
        CAPTURED.append(
            {
                "feed": level.feed,
                "interval": level.interval,
                "above": side is Side.ABOVE,
                "own_touches": own.touches,
                # The raw counts, not the shrunk probability. `probability_up`
                # shrinks the level's own record **toward the kNN prior**, so a
                # variant without the kNN has to re-shrink toward whatever
                # replaces it — reusing the shrunk value would smuggle the kNN
                # back in through the component that was meant to be free of it.
                "own_ups": own.ups,
                "prior_up": prior_up,
                "prior_n": count,
                "base_blind": memory.base_rate_for(level.feed, level.interval),
                "level_price": level.price,
            }
        )
        return original(level, side, features, memory, vol, price, cost_vol)

    return wrapped


class SideRates:
    """Up-rate per (feed, interval, side), accumulated causally.

    Shrunk toward the pooled rate the same way `base_rate_for` is, so the
    comparison is like for like and any difference is the side conditioning
    rather than a different smoothing.
    """

    def __init__(self) -> None:
        self._cells: dict[tuple, list[float]] = collections.defaultdict(lambda: [0.0, 0.0])
        self._pooled = [0.0, 0.0]

    def rate(self, feed: str, interval: str, above: bool) -> float:
        pooled = (self._pooled[0] + 0.5) / (self._pooled[1] + 1.0) if self._pooled[1] else 0.5
        ups, seen = self._cells.get((feed, interval, above), (0.0, 0.0))
        if not seen:
            return pooled
        return (ups + BASE_WEIGHT * pooled) / (seen + BASE_WEIGHT)

    def observe(self, feed: str, interval: str, above: bool, went_up: bool) -> None:
        cell = self._cells[(feed, interval, above)]
        cell[0] += 1.0 if went_up else 0.0
        cell[1] += 1.0
        self._pooled[0] += 1.0 if went_up else 0.0
        self._pooled[1] += 1.0


def collect():
    """Replay, pairing every call with the outcome of the touch it opened."""
    original = reactions.infer
    reactions.infer = watching(original)
    try:
        engine = Engine(intervals=INTERVALS)
        rates = SideRates()
        pending: dict[tuple, dict] = {}
        paired: list[dict] = []

        for bar in bars(INTERVALS):
            before = len(CAPTURED)
            calls = engine.observe_bar(bar)
            made = CAPTURED[before:]
            for call in calls:
                touch = engine.tracker.open_touch(call.level)
                if touch is None or touch.started != call.time:
                    continue
                # Match the capture to the call by level price, since one bar
                # can open several touches.
                found = next(
                    (
                        row
                        for row in made
                        if math.isclose(row["level_price"], touch.level_price, rel_tol=1e-12)
                    ),
                    None,
                )
                if found is None:
                    continue
                row = dict(found)
                row["base_side"] = rates.rate(call.feed, call.interval, row["above"])
                row["when"] = touch.started
                pending[key(call.feed, call.interval, touch.level_price, touch.started)] = row

            for _level, touch in engine.drain_resolved():
                row = pending.pop(
                    key(touch.feed, touch.interval, touch.level_price, touch.started), None
                )
                # Every resolution updates the causal rates, whether or not it
                # was paired to a call.
                rates.observe(
                    touch.feed,
                    touch.interval,
                    touch.features.side is Side.ABOVE,
                    touch.push_vol > 0,
                )
                if row is None or not touch.push_vol:
                    continue
                row["push_vol"] = float(touch.push_vol)
                row["up"] = touch.push_vol > 0
                paired.append(row)
        return paired
    finally:
        reactions.infer = original


def probability(row, knn: bool) -> float:
    """Recombine the components the way `infer` does, with or without the kNN.

    The prior appears **twice** in the live path and both have to move together:
    once as the thing the level's own record is shrunk toward
    (`Stats.probability_up`), and once as the other half of the outer
    shrinkage. Replacing only the outer one would leave the kNN doing most of
    its work through the back door.
    """
    prior = row["prior_up"] if knn else row["base_side"]
    touches, ups = row["own_touches"], row["own_ups"]
    alpha = prior * reactions.PRIOR_WEIGHT + ups
    beta = (1.0 - prior) * reactions.PRIOR_WEIGHT + (touches - ups)
    own = alpha / (alpha + beta) if (alpha + beta) else prior
    weight = touches / (touches + reactions.PRIOR_WEIGHT) if touches else 0.0
    return weight * own + (1.0 - weight) * prior


VARIANTS = {
    "current (own + kNN, blind base)": lambda r: probability(r, True) - r["base_blind"],
    "side-conditioned base": lambda r: probability(r, True) - r["base_side"],
    "no kNN (own + side base)": lambda r: probability(r, False) - r["base_side"],
    "side base rate only": lambda r: r["base_side"] - 0.5,
}


def auc(scored) -> float:
    values = numpy.array([s for s, _ in scored], dtype=float)
    labels = numpy.array([y for _, y in scored], dtype=bool)
    positives = int(labels.sum())
    negatives = labels.size - positives
    if not positives or not negatives:
        return 0.5
    order = numpy.argsort(values, kind="stable")
    ordered = values[order]
    ranks = numpy.empty(ordered.size, dtype=float)
    starts = numpy.flatnonzero(numpy.concatenate(([True], ordered[1:] != ordered[:-1])))
    ends = numpy.append(starts[1:], ordered.size)
    for start, end in zip(starts, ends, strict=True):
        ranks[start:end] = (start + end - 1) / 2 + 1
    return float(
        (ranks[labels[order]].sum() - positives * (positives + 1) / 2) / (positives * negatives)
    )


def score(rows, edge_of):
    """Direction, AUC and what a gate would consume, for one variant."""
    decided = [(edge_of(r), r) for r in rows]
    hits = sum(1 for e, r in decided if e and (e > 0) == r["up"])
    called = sum(1 for e, _ in decided if e)
    return {
        "n": called,
        "direction": hits / called if called else 0.0,
        "auc": auc([(e, r["up"]) for e, r in decided]),
        "median_abs": sorted(abs(e) for e, _ in decided)[len(decided) // 2] if decided else 0.0,
    }


def main() -> None:
    rows = collect()
    print(f"{len(rows):,} calls paired with the outcome of the touch they opened\n")

    holds = sum(1 for r in rows if r["above"] == r["up"]) / len(rows)
    print(f"{'variant':<34} {'n':>7} {'direction':>10} {'AUC':>8} {'median |edge|':>14}")
    print("-" * 78)
    print(f"{'assume the level holds':<34} {len(rows):>7} {holds:>9.1%} {'-':>8} {'-':>14}")
    for label, edge_of in VARIANTS.items():
        got = score(rows, edge_of)
        print(
            f"{label:<34} {got['n']:>7} {got['direction']:>9.1%}"
            f" {got['auc']:>8.3f} {got['median_abs']:>14.4f}"
        )

    print("\nhow often each variant agrees with the trivial rule")
    for label, edge_of in VARIANTS.items():
        agree = sum(1 for r in rows if (edge_of(r) > 0) == r["above"]) / len(rows)
        print(f"  {label:<34} {agree:>6.1%}")

    print("\nat the live gate, MIN_EDGE = 0.10")
    print(f"{'variant':<34} {'passed':>8} {'share':>7} {'direction':>10} {'vs holds':>10}")
    print("-" * 74)
    for label, edge_of in VARIANTS.items():
        kept = [r for r in rows if abs(edge_of(r)) >= reactions.MIN_EDGE]
        if not kept:
            print(f"{label:<34} {0:>8} {'0.0%':>7}")
            continue
        hits = sum(1 for r in kept if (edge_of(r) > 0) == r["up"]) / len(kept)
        trivial = sum(1 for r in kept if r["above"] == r["up"]) / len(kept)
        print(
            f"{label:<34} {len(kept):>8} {len(kept) / len(rows):>6.1%}"
            f" {hits:>9.1%} {100 * (hits - trivial):>+9.1f}pp"
        )


if __name__ == "__main__":
    main()
