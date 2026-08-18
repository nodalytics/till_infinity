"""Structure beyond the touch: confluence, the shape of the level set, and volatility.

Run from the repository root:  python research/harness/structure.py

[topology.py](topology.py) asks whether a level's place in the *transit graph*
says anything. This asks the two neighbouring questions, and one more that only
makes sense alongside them:

    confluence   how many timeframes agree on this price, and how tightly
    shape        what the whole level set looks like at this moment — how many,
                 how dense, how dispersed, how fast it is turning over
    volatility   whether any of it says something different in a quiet market
                 from a violent one

The last is the reason to do all three together. Every threshold in this
project is denominated in volatility units already, so structure measured in
those units is comparable across instruments — and if structure carries
anything, the most likely shape is *conditional*: a dense band of levels means
one thing when volatility is low and another when a single bar crosses the
whole band.

## The discipline this needs more than the others

This is exploratory, and exploratory is where false positives are manufactured.
Fourteen properties across three volatility regimes is forty-two chances for
one to look significant at 95%, which is roughly two by construction.

So: the family-wise correction is applied **from the start**, the count of
tests is reported beside the results, and the headline test remains the one
[cycles.md](../cycles.md) settled on — does it add AUC over what the model
already has, by more than the interval on the difference when resampled by
instrument.
"""

from __future__ import annotations

import math
import pickle
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import numpy
from edge_gate import INTERVALS, bars
from topology import BASE, auc, walk

from till_infinity.structures.engine import Engine

CACHE = Path(__file__).with_name("structure.pkl")

#: How far either side of price counts as "near" when measuring density, in
#: volatility units. Three is the same neighbourhood `confluence.at` uses.
NEAR_VOL = 3.0

#: The properties being tested, by family.
CONFLUENCE = ("agree", "agree_intervals", "cluster_vol", "zone_rank")
SHAPE = ("count", "density", "dispersion", "gap_up", "gap_down", "gap_ratio")
REGIME = ("vol_bps", "vol_pctile", "vol_ratio")
EVERYTHING = (*CONFLUENCE, *SHAPE, *REGIME)


def describe(engine: Engine, feed: str, interval: str, price: float, level_price: float) -> dict:
    """What the level set around this touch looks like, right now.

    Everything in volatility units, so a band on gold and a band on btc are the
    same measurement rather than two numbers that cannot be compared.
    """
    vol = engine.vol.of(feed, interval)
    unit = vol.price_units(price, 1.0) if price else 0.0
    mine = engine.levels(feed, interval)
    everything = engine.levels(feed)
    if not unit:
        return dict.fromkeys(EVERYTHING, 0.0)

    def units(other: float) -> float:
        return abs(other - price) / unit

    near = [lvl for lvl in everything if units(lvl.price) <= NEAR_VOL]
    agreeing = [lvl for lvl in everything if abs(lvl.price - level_price) / unit <= 0.5]
    above = [lvl.price for lvl in mine if lvl.price > price]
    below = [lvl.price for lvl in mine if lvl.price < price]
    spread = [units(lvl.price) for lvl in mine]

    gap_up = (min(above) - price) / unit if above else 0.0
    gap_down = (price - max(below)) / unit if below else 0.0
    return {
        # Confluence: how many timeframes call this the same price.
        "agree": float(len(agreeing)),
        "agree_intervals": float(len({lvl.interval for lvl in agreeing})),
        "cluster_vol": (
            (max(lvl.price for lvl in agreeing) - min(lvl.price for lvl in agreeing)) / unit
            if len(agreeing) > 1
            else 0.0
        ),
        "zone_rank": float(sum(1 for lvl in everything if lvl.price < level_price)),
        # Shape: what the whole set looks like.
        "count": float(len(mine)),
        "density": float(len(near)),
        "dispersion": statistics.pstdev(spread) if len(spread) > 1 else 0.0,
        "gap_up": gap_up,
        "gap_down": gap_down,
        # Asymmetry of the room either side, which headroom alone cannot see.
        "gap_ratio": (gap_up / gap_down) if gap_down else 0.0,
        # Volatility, as the thing structure is to be paired with.
        "vol_bps": float(vol.bps),
        "vol_pctile": float(getattr(vol, "percentile", lambda: 0.5)())
        if callable(getattr(vol, "percentile", None))
        else 0.0,
        "vol_ratio": 0.0,
    }


def collect():
    if CACHE.exists():
        return pickle.loads(CACHE.read_bytes())
    from touches import FIELDS

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
                    **{f: float(getattr(touch.features, f)) for f in FIELDS},
                    **describe(engine, touch.feed, touch.interval, touch.entry, level.price),
                    "above": 1.0 if above else 0.0,
                    "feed": touch.feed,
                    "interval": touch.interval,
                    "up": touch.push_vol > 0,
                    "held": float(touch.push_vol) if above else -float(touch.push_vol),
                }
            )
    CACHE.write_bytes(pickle.dumps(rows))
    return rows


def wilson(hits: int, n: int, z: float) -> tuple[float, float]:
    if not n:
        return 0.0, 1.0
    p = hits / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(centre - half, 0.0), min(centre + half, 1.0)


def main() -> None:
    rows = collect()
    print(f"{len(rows):,} resolved touches described by the level set around them\n")

    print("=== 0. what the level set looks like")
    for name in EVERYTHING:
        values = sorted(r[name] for r in rows)
        if not any(values):
            continue
        print(
            f"    {name:<16} median {values[len(values) // 2]:>8.2f}"
            f"  p90 {values[int(len(values) * 0.9)]:>9.2f}  max {values[-1]:>10.2f}"
        )

    print("\n=== 1. each property alone, against direction")
    print(f"    {'property':<16} {'AUC':>7}")
    print("    " + "-" * 26)
    solo = []
    for name in EVERYTHING:
        if not any(r[name] for r in rows):
            continue
        got = auc([r[name] for r in rows], [r["up"] for r in rows])
        solo.append((abs(got - 0.5), name, got))
    for _, name, got in sorted(solo, reverse=True):
        print(f"    {name:<16} {got:>7.3f}")

    live = [name for _, name, _ in solo]
    print("\n=== 2. does any of it add to what the model already has")
    print(f"    {'features':<28} {'accuracy':>10} {'AUC':>8}")
    print("    " + "-" * 50)
    base_hits, base_auc, base_scored, feeds = walk(rows, BASE)
    print(f"    {'side + the eight':<28} {base_hits:>9.1%} {base_auc:>8.3f}")
    for label, keys in (
        ("plus confluence", tuple(k for k in CONFLUENCE if k in live)),
        ("plus the shape", tuple(k for k in SHAPE if k in live)),
        ("plus volatility", tuple(k for k in REGIME if k in live)),
        ("plus everything", tuple(live)),
    ):
        if not keys:
            continue
        hits, area, _scored, _ = walk(rows, (*BASE, *keys))
        print(f"    {label:<28} {hits:>9.1%} {area:>8.3f}   {area - base_auc:+.4f}")

    honest(rows, live, base_scored, feeds, base_auc)
    regimes(rows, live)


def honest(rows, live, base_scored, feeds, base_auc) -> None:
    """The test cycles.md settled on: does the gain survive by instrument."""
    print("\n=== 3. the honest test: resampled by instrument")
    _hits, area, scored, _ = walk(rows, (*BASE, *live))
    base = numpy.array([s for s, _ in base_scored])
    plus = numpy.array([s for s, _ in scored])
    labels = numpy.array([y for _, y in base_scored], dtype=bool)
    names = numpy.array(feeds)
    unique = sorted(set(feeds))
    index = {f: numpy.flatnonzero(names == f) for f in unique}
    rng = numpy.random.default_rng(11)
    gains = []
    for _ in range(2000):
        picked = rng.integers(0, len(unique), len(unique))
        drawn = numpy.concatenate([index[unique[i]] for i in picked])
        if labels[drawn].sum() in (0, drawn.size):
            continue
        gains.append(auc(plus[drawn], labels[drawn]) - auc(base[drawn], labels[drawn]))
    gains.sort()
    low, high = gains[int(0.025 * len(gains))], gains[int(0.975 * len(gains))]
    print(f"    gain {area - base_auc:+.4f}, 95% by instrument {low:+.4f} to {high:+.4f}")
    print(f"    {'REAL' if low > 0 else 'not distinguishable from zero'}")


def regimes(rows, live) -> None:
    """Whether any of it says something different in a quiet market."""
    print("\n=== 4. paired with volatility — does any of it work in one regime only")
    thirds = sorted(rows, key=lambda r: r["vol_bps"])
    size = len(thirds) // 3
    bands = (
        ("quiet", thirds[:size]),
        ("middle", thirds[size : 2 * size]),
        ("violent", thirds[2 * size :]),
    )
    tests = len(live) * 3
    alpha = 1 - 0.95 ** (1 / tests)
    from statistics import NormalDist

    z = NormalDist().inv_cdf(1 - alpha / 2)
    print(f"    {len(live)} properties x 3 regimes = {tests} tests, so each needs")
    print(f"    {100 * (1 - alpha):.2f}% rather than 95% (Sidak): z = {z:.3f}\n")
    print(f"    {'property':<16} {'quiet':>9} {'middle':>9} {'violent':>9} {'separates':>11}")
    print("    " + "-" * 60)
    for name in live:
        cells, separated = [], []
        for label, group in bands:
            got = auc([r[name] for r in group], [r["up"] for r in group])
            cells.append(got)
            # An AUC interval by instrument-block bootstrap is expensive here;
            # the Wilson interval on the equivalent win-rate is the cheap
            # stand-in, and it is deliberately the conservative direction.
            middle = statistics.median(r[name] for r in group)
            side = [r for r in group if r[name] > middle]
            if len(side) > 30:
                hits = sum(1 for r in side if r["up"])
                lo, hi = wilson(hits, len(side), z)
                pooled = sum(1 for r in group if r["up"]) / len(group)
                if not (lo <= pooled <= hi):
                    separated.append(label)
        mark = ", ".join(separated) if separated else "none"
        print(f"    {name:<16} {cells[0]:>9.3f} {cells[1]:>9.3f} {cells[2]:>9.3f} {mark:>11}")


if __name__ == "__main__":
    main()
