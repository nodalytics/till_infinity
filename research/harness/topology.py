"""Does a level's place in the graph of levels say anything?

Run from the repository root:  python research/harness/topology.py

Every feature the model carries describes the level or the approach:
`approach_vol`, `depth_vol`, `run_vol`, `pivot`, `backcheck`, `strength`,
`experience`, `regime`. [features.md](../features.md) established that none of
them predicts direction beyond `side`, and that the missing class is probably
not another function of price at the touch.

[cycles.md](../cycles.md) tried one non-local class - where the instrument sits
in a larger move - and found a marginal effect that did not survive being
resampled by instrument. This is a different non-local class: not where price
is in a *trend*, but where this level sits in the **network of levels** the
instrument has actually been trading between.

## The graph

    node   a level, as (feed, interval, price)
    edge   A -> B, once for every time a touch at A resolved and the next
           touch on that instrument was at B

So an edge is an **observed transit**: price left this level and arrived at
that one. Nothing is inferred from geometry - two levels a hair apart with no
transit between them are not connected, and two far apart that price shuttles
between are.

## What is asked of it

Six properties, all accumulated causally - a touch is described by the graph as
it stood *before* that touch resolved, never after:

    out_degree      distinct levels price has departed to from here
    in_degree       distinct levels price has arrived from
    self_rate       how often the next touch is this level again
    pull            share of departures that went to the single commonest
                    next level - how concentrated this level's traffic is
    through         how often this level sits in the middle of an A->L->B chain
    reach           median distance, in volatility units, of a departure

## The falsification

`side` carries essentially all the directional signal, so the question is not
whether these predict on their own. It is whether they **add** to `side`:

> Does AUC over `side` plus the graph beat AUC over `side` alone, by more than
> the interval on the difference when it is resampled by instrument?

That last clause is the one that killed [cycles.md](../cycles.md) - a gain of
+0.0041 there had an interval of -0.0008 to +0.0085 - and it is applied here
from the start rather than after the fact.
"""

from __future__ import annotations

import collections
import pickle
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import numpy
from edge_gate import INTERVALS, bars

from till_infinity.structures.engine import Engine

CACHE = Path(__file__).with_name("topology.pkl")

#: Touches before the graph is asked anything. A degree of one on a node seen
#: twice is not a property of the market.
WARM = 200

#: What the model already has, from `touches.FIELDS` plus the side.
BASE = (
    "approach_vol",
    "depth_vol",
    "strength",
    "run_vol",
    "experience",
    "pivot",
    "backcheck",
    "regime",
    "above",
)

GRAPH = ("out_degree", "in_degree", "self_rate", "pull", "through", "reach")


class Levels:
    """The transit graph, built as touches resolve.

    Every lookup answers with the graph as it stood before the touch being
    described, because the edge that touch is about to create is exactly the
    thing that would make its own description circular.
    """

    def __init__(self) -> None:
        self.out: dict[tuple, collections.Counter] = collections.defaultdict(collections.Counter)
        self.into: dict[tuple, collections.Counter] = collections.defaultdict(collections.Counter)
        self.middle: collections.Counter = collections.Counter()
        self.hops: dict[tuple, list[float]] = collections.defaultdict(list)
        self._last: dict[str, tuple] = {}
        self._before: dict[str, tuple] = {}

    def describe(self, node: tuple) -> dict[str, float]:
        out, into = self.out.get(node), self.into.get(node)
        departures = sum(out.values()) if out else 0
        commonest = out.most_common(1)[0][1] if out else 0
        hops = self.hops.get(node)
        return {
            "out_degree": float(len(out)) if out else 0.0,
            "in_degree": float(len(into)) if into else 0.0,
            "self_rate": (out[node] / departures) if departures and out else 0.0,
            "pull": (commonest / departures) if departures else 0.0,
            "through": float(self.middle.get(node, 0)),
            "reach": statistics.median(hops) if hops else 0.0,
        }

    def observe(self, feed: str, node: tuple, distance: float) -> None:
        """Record that price has now arrived here, after wherever it was."""
        previous = self._last.get(feed)
        if previous is not None:
            self.out[previous][node] += 1
            self.into[node][previous] += 1
            self.hops[previous].append(abs(distance))
            older = self._before.get(feed)
            if older is not None and older != previous:
                self.middle[previous] += 1
        self._before[feed] = previous if previous is not None else node
        self._last[feed] = node


def collect():
    """Replay, describing each touch by the graph as it stood beforehand."""
    if CACHE.exists():
        return pickle.loads(CACHE.read_bytes())

    from touches import FIELDS

    engine = Engine(intervals=INTERVALS)
    graph = Levels()
    rows: list[dict] = []
    for bar in bars(INTERVALS):
        engine.observe_bar(bar)
        for level, touch in engine.drain_resolved():
            if not touch.push_vol:
                continue
            # **The level object itself**, not its price. Rounding the price
            # was the first attempt and it measured nothing: a level is a
            # Kalman filter whose mean moves on every touch it absorbs, so a
            # price-keyed node is a *new* node each time and the graph never
            # accumulates. It showed 94 of 11,094 touches at a node it had seen
            # before, an `out_degree` maxing at 2, and a `pull` of 1.00 at the
            # median - the signature of a graph with no edges rather than a
            # market with no structure.
            #
            # Identity is replay-local, which is all this needs: the question
            # is whether transit structure exists at all, not how to persist it.
            node = (touch.feed, touch.interval, id(level))
            described = graph.describe(node)
            above = touch.features.side.name == "ABOVE"
            rows.append(
                {
                    **{f: float(getattr(touch.features, f)) for f in FIELDS},
                    **described,
                    "above": 1.0 if above else 0.0,
                    "feed": touch.feed,
                    "interval": touch.interval,
                    "up": touch.push_vol > 0,
                    "push_vol": float(touch.push_vol),
                    "held": float(touch.push_vol) if above else -float(touch.push_vol),
                    "seen": sum(graph.out.get(node, {}).values()),
                }
            )
            graph.observe(touch.feed, node, float(touch.push_vol))
    CACHE.write_bytes(pickle.dumps(rows))
    return rows


def auc(values, labels) -> float:
    values = numpy.asarray(values, dtype=float)
    labels = numpy.asarray(labels, dtype=bool)
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
    total = ranks[labels[order]].sum() - positives * (positives + 1) / 2
    return float(total / (positives * negatives))


def walk(rows, keys):
    """Walk-forward, every touch predicted before it is learned."""
    from river import linear_model, preprocessing

    model = preprocessing.StandardScaler() | linear_model.LogisticRegression()
    scored, feeds = [], []
    hits = seen = 0
    for i, row in enumerate(rows):
        x = {k: row[k] for k in keys}
        probability = model.predict_proba_one(x).get(True, 0.5)
        if i >= WARM:
            seen += 1
            hits += (probability > 0.5) == row["up"]
            scored.append((probability, row["up"]))
            feeds.append(row["feed"])
        model.learn_one(x, row["up"])
    return (
        hits / seen if seen else 0.0,
        auc([s for s, _ in scored], [y for _, y in scored]),
        scored,
        feeds,
    )


def main() -> None:
    rows = collect()
    described = [r for r in rows if r["seen"] > 0]
    print(f"{len(rows):,} resolved touches, {len(described):,} at a level the graph had seen\n")

    print("=== 0. what the graph looks like")
    nodes = {(r["feed"], r["interval"]) for r in rows}
    print(f"    instruments x timeframes: {len(nodes)}")
    for name in GRAPH:
        values = sorted(r[name] for r in described)
        if not values:
            continue
        print(
            f"    {name:<11} median {values[len(values) // 2]:>7.2f}"
            f"  p90 {values[int(len(values) * 0.9)]:>8.2f}  max {values[-1]:>9.2f}"
        )

    print("\n=== 1. each property alone, against direction")
    print(f"    {'property':<12} {'AUC':>7}")
    print("    " + "-" * 22)
    for name in GRAPH:
        alone = auc([r[name] for r in described], [r["up"] for r in described])
        print(f"    {name:<12} {alone:>7.3f}")

    print("\n=== 2. does it add to what the model already has")
    print(f"    {'features':<26} {'accuracy':>10} {'AUC':>8}")
    print("    " + "-" * 48)
    base_hits, base_auc, base_scored, feeds = walk(rows, BASE)
    print(f"    {'side + the eight':<26} {base_hits:>9.1%} {base_auc:>8.3f}")
    with_hits, with_auc, with_scored, _ = walk(rows, (*BASE, *GRAPH))
    print(f"    {'plus the graph':<26} {with_hits:>9.1%} {with_auc:>8.3f}")
    only_hits, only_auc, _, _ = walk(rows, ("above", *GRAPH))
    print(f"    {'side + the graph only':<26} {only_hits:>9.1%} {only_auc:>8.3f}")
    print(f"\n    gain {with_auc - base_auc:+.4f}")

    print("\n=== 3. and does the gain survive being resampled by instrument")
    base = numpy.array([s for s, _ in base_scored])
    plus = numpy.array([s for s, _ in with_scored])
    labels = numpy.array([y for _, y in base_scored], dtype=bool)
    names = numpy.array(feeds)
    unique = sorted(set(feeds))
    index = {f: numpy.flatnonzero(names == f) for f in unique}
    rng = numpy.random.default_rng(5)
    gains = []
    for _ in range(2000):
        drawn = numpy.concatenate(
            [index[unique[i]] for i in rng.integers(0, len(unique), len(unique))]
        )
        if labels[drawn].sum() in (0, drawn.size):
            continue
        gains.append(auc(plus[drawn], labels[drawn]) - auc(base[drawn], labels[drawn]))
    gains.sort()
    low, high = gains[int(0.025 * len(gains))], gains[int(0.975 * len(gains))]
    print(f"    95% by instrument: {low:+.4f} to {high:+.4f}")
    print(f"    {'REAL' if low > 0 else 'not distinguishable from zero'}")


if __name__ == "__main__":
    main()
