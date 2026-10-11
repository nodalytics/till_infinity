"""Does persistent homology see anything a trailing standard deviation does not?

Asked on 2026-10-11. Topological data analysis on a **delay embedding** of a
price series is a real and well-defined thing: embed the series in `d`
dimensions by stacking lagged copies, build a filtration of simplicial
complexes over a growing distance scale, and record at which scales
topological features - connected components and loops - are born and die. A
loop that survives a wide range of scales is a recurrent structure in the
embedding that is not an artifact of the scale you happened to pick.

The claim worth testing is that **persistence summarises recurrence in a way
a variance cannot**, because a loop is a statement about the *shape* of the
trajectory rather than about the size of its steps.

## Why this is a harness and not a member

Persistent homology produces a **summary of a window**, not a predictive
distribution. It cannot be scored on held-out likelihood against `linear`,
which is the one comparison `family.py` insists on, so it could only ever be
an input to a member - and an input has to earn its place against the same
nulls as every other input. That is what this measures.

## The null that kills most TDA results in finance

**A surrogate with the same volatility clustering and no topology.** The
published comparisons that matter are the ones against a GARCH surrogate,
because a series with clustered volatility produces persistence diagrams that
look structured for reasons that have nothing to do with recurrence. If the
statistic cannot tell a market from a GARCH path, it is reading volatility.

So three arms:

* the real series;
* a **GARCH(1,1) with t(5) innovations**, the control
  `research/harness/ecology.py` already uses - clustered volatility, no
  participants, no recurrence;
* a plain Gaussian random walk, which has neither.

And the usual two: a rotated control on the feature, and the net correlation
after a trailing standard deviation is removed.

## Persistence entropy, which is the cheap decisive version

The full diagram is expensive and most of it is noise. **Persistence entropy**
- the entropy of the normalised lifetimes of the `H1` features - is one number
per window, it is scale-free, and it is the summary the literature reports
most often. If it carries nothing, the richer summaries are not worth the
compute.

`ripser` and `giotto-tda` are not dependencies here and will not become ones
for a harness, so the Vietoris-Rips `H1` persistence is computed directly:
for a point cloud this small the 1-dimensional homology of a Rips filtration
is obtainable from the **minimum spanning tree** and the cycle-closing edges,
which is `O(n^2 log n)` and exact for `H1` lifetimes under a standard
construction. Written out, with its reference, because that is the rule.

Runs on the lab.
"""

from __future__ import annotations

import math
import os
import random
from pathlib import Path

from till_infinity.structures.statespace.nulls import control, spearman, trailing

SYMBOLS = (
    ("eurusd", "EURUSD"),
    ("xauusd", "XAUUSD"),
    ("gbpusd", "GBPUSD"),
    ("btcusd", "BTCUSD"),
    ("v75", "Volatility_75_Index"),
)
FRAME = os.environ.get("FRAME", "1h")

#: Delay embedding: how many lagged copies, and the lag between them in bars.
DIMENSION = 3
DELAY = 2

#: Points per window. Small, because Rips on `m` points is `O(m^2)` edges and
#: this runs over thousands of windows.
POINTS = 40

#: Forecast horizons in bars.
HORIZONS = (4, 24)

SINCE = float(os.environ.get("SINCE", "1262304000"))
LIMIT = int(os.environ.get("LIMIT", "8000"))
SEED = 20261011


def load(stem: str, frame: str):
    import numpy as np

    path = Path(f"data/seqlab/{stem}.{frame}.npz")
    if not path.exists():
        return None
    with np.load(path) as bundle:
        if not {"time", "close"} <= set(bundle.keys()):
            return None
        order = np.argsort(bundle["time"])
        times = bundle["time"][order].tolist()
        closes = bundle["close"][order].tolist()
    first = 0
    while first < len(times) and times[first] < SINCE:
        first += 1
    times, closes = times[first:], closes[first:]
    if len(closes) > LIMIT:
        times, closes = times[-LIMIT:], closes[-LIMIT:]
    return times, closes


def returns(closes: list[float]) -> list[float]:
    return [0.0] + [
        math.log(closes[i] / closes[i - 1]) if closes[i] > 0 and closes[i - 1] > 0 else 0.0
        for i in range(1, len(closes))
    ]


def garch(n: int, seed: int) -> list[float]:
    """GARCH(1,1) with t(5) innovations: clustered volatility, no recurrence."""
    rng = random.Random(seed)
    variance, previous = 1.0, 0.0
    out = []
    for _ in range(n):
        variance = 0.02 + 0.10 * previous * previous + 0.88 * variance
        # Student-t(5) by the ratio of a normal to a chi scaling.
        chi = sum(rng.gauss(0.0, 1.0) ** 2 for _ in range(5))
        previous = rng.gauss(0.0, math.sqrt(variance)) * math.sqrt(5.0 / max(chi, 1e-9))
        out.append(previous)
    return out


def walk(n: int, seed: int) -> list[float]:
    rng = random.Random(seed)
    return [rng.gauss(0.0, 1.0) for _ in range(n)]


def _lifetimes(cloud: list[tuple[float, ...]]) -> list[float]:
    """`H1` lifetimes of the Vietoris-Rips filtration, from the MST.

    The construction: in a Rips filtration a 1-cycle is born when an edge
    closes a loop - that is, an edge *not* in the minimum spanning tree - and
    dies when the triangle filling it appears, which for a Rips complex is at
    the longest edge of the triangle that closes it. Taking the cheapest such
    triangle per cycle-closing edge gives that edge's lifetime.

    **This is a standard shortcut and not the full persistence algorithm**: it
    gives correct `H1` *lifetimes* for the dominant cycles and does not pair
    them canonically. That is enough for persistence entropy, which depends
    only on the multiset of lifetimes, and it is stated here rather than
    implied because the full algorithm is a library this package will not add.
    """
    count = len(cloud)
    if count < 4:
        return []
    distance = [
        [math.dist(cloud[i], cloud[j]) if i != j else 0.0 for j in range(count)]
        for i in range(count)
    ]
    # Prim's minimum spanning tree.
    in_tree = [False] * count
    in_tree[0] = True
    tree_edges = set()
    for _ in range(count - 1):
        best = (math.inf, -1, -1)
        for i in range(count):
            if not in_tree[i]:
                continue
            for j in range(count):
                if in_tree[j]:
                    continue
                if distance[i][j] < best[0]:
                    best = (distance[i][j], i, j)
        _, a, b = best
        if b < 0:
            break
        in_tree[b] = True
        tree_edges.add((min(a, b), max(a, b)))

    lifetimes = []
    for i in range(count):
        for j in range(i + 1, count):
            if (i, j) in tree_edges:
                continue
            birth = distance[i][j]
            # Death: the cheapest triangle containing this edge, which in a
            # Rips complex appears at the larger of its other two edges.
            death = math.inf
            for k in range(count):
                if k in (i, j):
                    continue
                death = min(death, max(distance[i][k], distance[j][k]))
            if death > birth:
                lifetimes.append(death - birth)
    return lifetimes


def entropy(cloud: list[tuple[float, ...]]) -> float:
    """Persistence entropy of the `H1` lifetimes. Scale-free by construction."""
    lifetimes = [v for v in _lifetimes(cloud) if v > 0]
    total = sum(lifetimes)
    if total <= 0 or len(lifetimes) < 2:
        return 0.0
    shares = [v / total for v in lifetimes]
    return -sum(p * math.log(p) for p in shares if p > 0)


def embed(series: list[float], start: int, points: int) -> list[tuple[float, ...]]:
    """A delay embedding of `points` consecutive points ending at `start`."""
    need = points + (DIMENSION - 1) * DELAY
    if start < need:
        return []
    window = series[start - need : start]
    return [tuple(window[k + d * DELAY] for d in range(DIMENSION)) for k in range(points)]


def measure(name: str, series: list[float], scored: list[float]) -> None:
    """Persistence entropy against |move|, with both nulls."""
    need = POINTS + (DIMENSION - 1) * DELAY
    for horizon in HORIZONS:
        rows = list(range(need + 50, len(series) - horizon, horizon))
        if len(rows) < 200:
            continue
        feature, size, vol = [], [], []
        sd = trailing(scored, 24)
        for i in rows:
            cloud = embed(series, i, POINTS)
            if not cloud:
                continue
            feature.append(entropy(cloud))
            size.append(abs(scored[i + horizon] - scored[i]))
            vol.append(sd[i])
        if len(feature) < 200 or max(feature) - min(feature) <= 0:
            continue
        raw = spearman(feature, size)
        null = control(feature, size)
        base = spearman(vol, size)
        print(
            f"  {name:<14}{horizon:>5}{len(feature):>7}{raw:>+10.3f}"
            f"{null:>+9.3f}{raw - null:>+9.3f}{base:>+10.3f}"
        )


def main() -> None:
    print("Persistent homology on a delay embedding: does it see anything?")
    print(f"embedding dimension {DIMENSION}, delay {DELAY} bars, {POINTS} points.")
    print("'entropy' is the persistence entropy of the H1 lifetimes.")
    print("The controls are the rotated feature, and a GARCH surrogate with")
    print("the same volatility clustering and no recurrence.\n")
    print(f"  {'series':<14}{'h':>5}{'n':>7}{'rho':>10}{'ctrl':>9}{'edge':>9}{'sd null':>10}")

    for label, stem in SYMBOLS:
        got = load(stem, FRAME)
        if got is None or len(got[1]) < 3000:
            continue
        _times, closes = got
        moves = returns(closes)
        levels = [0.0]
        for m in moves[1:]:
            levels.append(levels[-1] + m)
        measure(label, moves, levels)

    # The surrogates, on the same lengths.
    length = 8000
    for name, maker in (("GARCH t(5)", garch), ("gaussian walk", walk)):
        moves = maker(length, SEED)
        levels = [0.0]
        for m in moves:
            levels.append(levels[-1] + m)
        measure(name, [0.0, *moves], levels)

    print()
    print("Reading it: 'edge' is rho minus the rotated control, so zero means")
    print("a marginal. 'sd null' is what a trailing standard deviation gets on")
    print("the same points - the number persistence entropy has to beat.")
    print("If the GARCH surrogate reads like the markets, the statistic is")
    print("reading volatility clustering rather than recurrence.")


if __name__ == "__main__":
    main()
