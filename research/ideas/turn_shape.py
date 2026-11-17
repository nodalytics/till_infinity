"""Volatility around a turn, and whether turns fall into kinds.

Three operator questions from 2026-11-17, in the order they were asked:

* *"did we also check the volatility around legs and turn points"* - an event
  study. For every turn point, the true range of each bar from 24 before to 24
  after, in units of the ATR **24 bars before** the turn, so the profile is not
  normalised by the thing it is measuring. `seasonality-belongs-on-q` and
  [`impulse-vol.md`](../docs/impulse-vol.md) both say the risk channel is where
  this desk's signal lives, and `reactive-zones.md` already found ATR *rises*
  into a level sequence and separates winners from losers by 0.02 - so the
  shape of the profile is a description worth having whether or not it pays.
* *"apply clustering to turn points too and compare with the graph approach,
  also apply PCA"* - k-means and principal components over a turn point's own
  description, scored the only way a cluster can be: does the clearance rate
  differ between clusters by more than the **distance** between clusters
  already implies, and by more than clustering a day-shuffled series gives.
  `definitions-cannot-be-states` is the trap - a mixture centre that is a free
  state collapses onto the data - and `auc-is-free-on-volatility-targets` is
  the second one.
* The graph comparison: degree, meaning how many later turns land within
  `--tol` ATR of this one, against a placebo node 1 to 3 ATR away.
  [`level-graph.md`](../docs/level-graph.md) closed *centrality* on a level
  graph (real below its hardest null in 226 of 231 cells) and
  [`topology.md`](../docs/topology.md) closed persistent homology, so degree
  over turn points is the one statistic in the family still open.

Run as:

    uv run python research/ideas/turn_shape.py --kinds pivot,zigzag --clusters 4
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from leg_sequence import Turns, alternating, extremes, penetrate, turns_of  # noqa: E402
from persistence import SYMBOLS, trailing_rank, true_range  # noqa: E402
from reactive_zones import (  # noqa: E402
    CATALOGUE,
    Candles,
    atr,
    fold,
    load,
    load_csv,
    shuffled,
    window,
)

#: What a turn point is described by. Everything is backward-looking except
#: `post_vol`, which is in the matrix because the question "do turns fall into
#: kinds" is about the object and not about a tradable signal - and it is
#: labelled so that nothing downstream mistakes it for one.
DESCRIBE = (
    "bar_size",
    "body_share",
    "reject_wick",
    "opposite_wick",
    "approach_atr",
    "approach_bars",
    "approach_efficiency",
    "pre_vol",
    "regime",
    "hour_sin",
    "hour_cos",
    "reach_atr",
)


def profile(bars: Candles, band: np.ndarray, turns: Turns, span: int = 24) -> np.ndarray | None:
    """Mean true range from `span` before a turn to `span` after, in early ATR.

    **Normalised by the ATR `span` bars before the turn, not at it.** Dividing
    by the ATR at the turn is what makes every event study of volatility read
    as a spike followed by decay: the denominator is itself inflated by the
    event. Here the scale is fixed before the window opens, so a rise into the
    turn and a fall out of it are both visible and both mean something.
    """
    tr = true_range(bars)
    rows = []
    for k in range(turns.at.size):
        i = int(turns.at[k])
        if i - span - 1 < 0 or i + span >= len(bars):
            continue
        unit = band[i - span]
        if not np.isfinite(unit) or unit <= 0:
            continue
        rows.append(tr[i - span : i + span + 1] / unit)
    if len(rows) < 100:
        return None
    return np.asarray(rows)


def describe(bars: Candles, band: np.ndarray, turns: Turns, source: str, span: int = 24) -> dict:
    """One row per turn point: what it looked like, and what it did next."""
    tops, bottoms = extremes(bars, source)
    tr = true_range(bars)
    state = trailing_rank(band)
    hour = ((bars.ts // 3_600_000_000_000) % 24).astype(float)
    rows: dict[str, list[float]] = {name: [] for name in DESCRIBE}
    rows["post_vol"] = []
    index: list[int] = []
    for k in range(turns.at.size):
        i = int(turns.at[k])
        if i - span - 1 < 0 or i + span >= len(bars):
            continue
        unit = band[i - span]
        if not np.isfinite(unit) or unit <= 0 or not np.isfinite(state[i]):
            continue
        up = turns.side[k] == 1
        here = float(turns.price[k])
        extreme = float(tops[i - span : i].max()) if up else float(bottoms[i - span : i].min())
        net = (extreme - here) if up else (here - extreme)
        walked = float(np.nansum(tr[i - span : i + 1]))
        at = int(np.argmax(tops[i - span : i]) if up else np.argmin(bottoms[i - span : i]))
        full = max(float(bars.span[i]), 1e-12)
        rows["bar_size"].append(float(bars.span[i]) / unit)
        rows["body_share"].append(float(bars.body[i]) / full)
        rows["reject_wick"].append(float(bars.lower_wick[i] if up else bars.upper_wick[i]) / full)
        rows["opposite_wick"].append(float(bars.upper_wick[i] if up else bars.lower_wick[i]) / full)
        rows["approach_atr"].append(net / unit)
        rows["approach_bars"].append(float(span - at))
        rows["approach_efficiency"].append(net / walked if walked > 0 else np.nan)
        rows["pre_vol"].append(float(np.nanmean(tr[i - span : i])) / unit)
        rows["regime"].append(float(state[i]))
        rows["hour_sin"].append(float(np.sin(2 * np.pi * hour[i] / 24.0)))
        rows["hour_cos"].append(float(np.cos(2 * np.pi * hour[i] / 24.0)))
        rows["reach_atr"].append(np.nan)
        rows["post_vol"].append(float(np.nanmean(tr[i + 1 : i + span + 1])) / unit)
        index.append(k)
    out = {name: np.asarray(values) for name, values in rows.items()}
    out["_turn"] = np.asarray(index, dtype=np.int64)
    return out


def histograms(found, bars: Candles) -> None:
    """The distributions themselves: how big a leg is, how long, how far it falls short.

    Asked for directly, and worth having on its own: the desk has never written
    down the size distribution of a leg. Printed as deciles rather than as a
    fitted family, because a fitted family is a claim and these are the data.
    """
    hours = float(np.median(np.diff(bars.ts[:1000]))) / 3_600_000_000_000 if len(bars) > 1000 else 0.0
    for name, values, unit in (
        ("leg extent, ATR", found.extent, ""),
        ("leg duration, bars", found.took, f" ({hours:.1f}h each)"),
        ("reach to the prior turn, ATR", found.reach_atr, ""),
        ("overshoot of it, ATR", found.overshoot, ""),
    ):
        ok = np.isfinite(values)
        if ok.sum() < 200:
            continue
        v = values[ok]
        edges = np.percentile(v, [1, 10, 25, 50, 75, 90, 99])
        print(
            f"      {name:<30}{unit} n {ok.sum():>7,}  mean {v.mean():7.2f}  "
            + "  ".join(f"p{q} {e:.2f}" for q, e in zip((1, 10, 25, 50, 75, 90, 99), edges, strict=False))
        )


def binned(
    matrix: np.ndarray,
    cleared: np.ndarray,
    reach: np.ndarray,
    names: tuple[str, ...],
    picks: tuple[str, ...] = ("reach_atr", "regime", "approach_efficiency"),
    cells: int = 4,
    draws: int = 20,
    seed: int = 11,
) -> float:
    """Plain joint bins - a histogram over three features - and its own floor.

    The simplest alternative to clustering, and the one that makes the others
    comparable: every method here is ultimately asking "is there a region of
    turn-point space where the clearance rate is not what the distance
    implies", so each is scored by **the largest such gap it finds** and by
    **the largest a permuted label gives it**.

    The permutation shuffles the outcome **inside each distance decile**,
    which keeps the one relationship that is not in question - clearance falls
    from 0.89 at 1.5 ATR to 0.05 past 3.8 - and destroys every other. Picking
    the best of 64 cells finds a winner every time, and this says how big that
    winner is when there is nothing there.
    """
    good = np.isfinite(matrix).all(axis=1) & np.isfinite(cleared) & np.isfinite(reach)
    if good.sum() < 400:
        print(f"      bins: {good.sum()} rows, too few")
        return float("nan")
    kept, done, far = matrix[good], cleared[good], reach[good]
    columns = [names.index(name) for name in picks if name in names]
    ids = np.zeros(kept.shape[0], dtype=np.int64)
    for column in columns:
        edges = np.percentile(kept[:, column], np.linspace(0, 100, cells + 1))
        here = np.clip(np.searchsorted(edges[1:-1], kept[:, column], side="right"), 0, cells - 1)
        ids = ids * cells + here
    decile = np.clip(
        np.searchsorted(np.percentile(far, np.linspace(0, 100, 11))[1:-1], far, side="right"), 0, 9
    )
    expected = np.zeros(far.size)
    for d in range(10):
        pick = decile == d
        if pick.any():
            expected[pick] = done[pick].mean()

    def best(outcome: np.ndarray) -> tuple[float, int]:
        top, where = 0.0, -1
        for cell in np.unique(ids):
            pick = ids == cell
            if pick.sum() < 50:
                continue
            gap = float(outcome[pick].mean() - expected[pick].mean())
            if abs(gap) > abs(top):
                top, where = gap, int(cell)
        return top, where

    found, cell = best(done)
    rng = np.random.default_rng(seed)
    floor = []
    for _ in range(draws):
        spun = done.copy()
        for d in range(10):
            pick = np.flatnonzero(decile == d)
            spun[pick] = done[rng.permutation(pick)]
        floor.append(abs(best(spun)[0]))
    print(
        f"      bins {' x '.join(picks)} at {cells} each: {len(np.unique(ids))} cells, "
        f"{good.sum():,} legs"
    )
    print(
        f"        best gap over the distance-matched rate {found:+.4f} (cell {cell}), "
        f"against a within-decile permuted best of {np.mean(floor):.4f} +/- {np.std(floor):.4f}"
    )
    return abs(found) - float(np.mean(floor))


def principal(matrix: np.ndarray, names: tuple[str, ...], show: int = 4) -> np.ndarray:
    """PCA on standardised columns: variance share, and the top loadings.

    Reported beside the same decomposition on a day-shuffled series. A PCA on
    any correlated matrix produces a dominant component; the question is
    whether the real one is more concentrated than a market with its order
    removed, and `topology.md` is the precedent for what the answer usually is
    - what those tools saw was volatility clustering.
    """
    good = np.isfinite(matrix).all(axis=1)
    kept = matrix[good]
    if kept.shape[0] < 500:
        print("      PCA: too few rows")
        return np.zeros((0, 0))
    centred = (kept - kept.mean(axis=0)) / (kept.std(axis=0) + 1e-12)
    _, singular, loadings = np.linalg.svd(centred, full_matrices=False)
    share = singular**2 / np.sum(singular**2)
    print(f"      PCA on {kept.shape[0]:,} turns, {kept.shape[1]} columns")
    for c in range(min(show, share.size)):
        order = np.argsort(-np.abs(loadings[c]))[:4]
        terms = "  ".join(f"{names[j]} {loadings[c][j]:+.2f}" for j in order)
        print(f"        PC{c + 1} {share[c]:.3f} of variance   {terms}")
    print(f"        first four together {share[:4].sum():.3f}")
    return centred @ loadings[:show].T


def cluster(
    matrix: np.ndarray,
    cleared: np.ndarray,
    reach: np.ndarray,
    names: tuple[str, ...],
    count: int,
    seed: int = 7,
) -> None:
    """k-means over the description, scored against a distance-matched rate.

    **A cluster's clearance rate is not evidence on its own.** Clearance is a
    near-deterministic function of how far the prior turn point is - 0.89 at
    1.5 ATR and 0.05 past 3.8 - so a clustering that sorts on distance sorts on
    the outcome for free. Each cluster is therefore reported beside the rate the
    whole sample gives *at that cluster's own distances*, and the column to read
    is the difference.
    """
    from sklearn.cluster import KMeans

    good = np.isfinite(matrix).all(axis=1) & np.isfinite(cleared) & np.isfinite(reach)
    if good.sum() < 400:
        print(f"      clusters: {good.sum()} rows, too few")
        return
    kept = matrix[good]
    centred = (kept - kept.mean(axis=0)) / (kept.std(axis=0) + 1e-12)
    labels = KMeans(n_clusters=count, n_init=10, random_state=seed).fit_predict(centred)
    done, far = cleared[good], reach[good]
    edges = np.percentile(far, np.linspace(0, 100, 11))
    # The sample's own rate in each distance decile, which is the expectation a
    # cluster has to beat by being something other than a distance.
    expected = np.zeros(far.size)
    for d in range(10):
        lo, hi = edges[d], edges[d + 1]
        pick = (far >= lo) & (far < hi) if d < 9 else (far >= lo)
        if pick.sum() > 0:
            expected[pick] = done[pick].mean()
    # The same within-decile permuted floor the binned arm gets, so the two
    # methods are scored on one scale rather than on their own.
    rng = np.random.default_rng(seed + 1)
    decile = np.clip(np.searchsorted(edges[1:-1], far, side="right"), 0, 9)

    def spread(outcome: np.ndarray) -> float:
        top = 0.0
        for c in range(count):
            pick = labels == c
            if pick.sum() < 50:
                continue
            gap = float(outcome[pick].mean() - expected[pick].mean())
            top = gap if abs(gap) > abs(top) else top
        return abs(top)

    floor = []
    for _ in range(20):
        spun = done.copy()
        for d in range(10):
            pick = np.flatnonzero(decile == d)
            spun[pick] = done[rng.permutation(pick)]
        floor.append(spread(spun))
    print(
        f"      k-means k={count} on {kept.shape[0]:,} turns, best gap {spread(done):.4f} "
        f"against a permuted {np.mean(floor):.4f} +/- {np.std(floor):.4f}"
    )
    for c in range(count):
        pick = labels == c
        if pick.sum() < 50:
            continue
        loud = np.argsort(-np.abs(centred[pick].mean(axis=0)))[:3]
        traits = "  ".join(f"{names[j]} {centred[pick].mean(axis=0)[j]:+.2f}" for j in loud)
        print(
            f"        c{c} n {pick.sum():>6,}  cleared {done[pick].mean():.4f}  "
            f"distance-matched {expected[pick].mean():.4f}  "
            f"difference {done[pick].mean() - expected[pick].mean():+.4f}   {traits}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalogue", default=str(CATALOGUE))
    parser.add_argument("--symbols", default=",".join(SYMBOLS))
    parser.add_argument("--csv", default="")
    parser.add_argument("--unit", default="5m")
    parser.add_argument("--frame", default="1h")
    parser.add_argument("--years", type=float, default=0.0)
    parser.add_argument("--kinds", default="pivot,zigzag,fractal")
    parser.add_argument("--arms", default="real,shuffled")
    parser.add_argument("--source", default="wick", choices=("wick", "body", "close"))
    parser.add_argument("--span", type=int, default=24)
    parser.add_argument("--clusters", default="3,5")
    parser.add_argument("--left", type=int, default=15)
    parser.add_argument("--right", type=int, default=5)
    parser.add_argument("--reversal", type=float, default=1.5)
    parser.add_argument("--approach", type=float, default=1.5)
    parser.add_argument("--reach", type=float, default=3.0)
    parser.add_argument("--ahead", type=int, default=24)
    parser.add_argument("--behind", type=int, default=24)
    parser.add_argument("--share", type=float, default=0.5)
    parser.add_argument("--displacement", type=float, default=1.0)
    parser.add_argument("--pad", type=float, default=0.25)
    parser.add_argument("--tol", type=float, default=0.25)
    args = parser.parse_args()

    sources: list[tuple[str, Candles]] = []
    if args.csv:
        for pair in args.csv.split(","):
            name, _, path = pair.partition("=")
            sources.append((name, load_csv(Path(path), name, args.unit)))
    else:
        for symbol in (s for s in args.symbols.split(",") if s):
            sources.append((symbol, load(Path(args.catalogue), symbol)))

    print(f"frame {args.frame}  source {args.source}  span {args.span}")
    for kind in (k.strip() for k in args.kinds.split(",") if k.strip()):
        print(f"\n{'=' * 70}\n### {kind}\n{'=' * 70}")
        for arm in (a.strip() for a in args.arms.split(",") if a.strip()):
            print(f"\n  --- {arm}")
            shapes: list[np.ndarray] = []
            stacks: list[np.ndarray] = []
            outcomes: list[np.ndarray] = []
            reaches: list[np.ndarray] = []
            for name, base in sources:
                series = shuffled(base, seed=19) if arm == "shuffled" else base
                if args.years > 0:
                    series = window(series, args.years)
                bars = fold(series, args.frame, unit=args.unit)
                band = atr(bars)
                turns = alternating(turns_of(bars, band, kind, args))
                shape = profile(bars, band, turns, args.span)
                if shape is not None:
                    shapes.append(shape)
                    histograms(penetrate(bars, band, turns, args.source), bars)
                    middle = shape.shape[1] // 2
                    before = shape[:, :middle].mean()
                    at = shape[:, middle].mean()
                    after = shape[:, middle + 1 :].mean()
                    print(
                        f"    {name}: {shape.shape[0]:,} turns  mean TR before {before:.3f}  "
                        f"at the turn {at:.3f}  after {after:.3f}  (ATR {args.span} bars earlier = 1)"
                    )
                table = describe(bars, band, turns, args.source, args.span)
                found = penetrate(bars, band, turns, args.source)
                # `penetrate` drops legs with nothing to clear, so the two row
                # sets are joined on the turn index rather than assumed equal.
                # Joined on the turn index `penetrate` carries, never on a
                # counter walked beside its loop: the first version of this
                # reproduced one of that loop's four `continue`s and attached
                # outcomes to the wrong turns.
                wanted = {int(v): j for j, v in enumerate(table["_turn"])}
                pick, cleared, reach = [], [], []
                for position, k in enumerate(found.turn):
                    row = wanted.get(int(k))
                    if row is None:
                        continue
                    pick.append(row)
                    cleared.append(float(found.cleared[position]))
                    reach.append(float(found.reach_atr[position]))
                if len(pick) < 200:
                    continue
                rows = np.asarray(pick, dtype=np.int64)
                stacks.append(np.column_stack([table[c][rows] for c in DESCRIBE[:-1]]))
                outcomes.append(np.asarray(cleared))
                reaches.append(np.asarray(reach))
            if not stacks:
                continue
            matrix = np.concatenate(stacks)
            done = np.concatenate(outcomes)
            far = np.concatenate(reaches)
            matrix = np.column_stack([matrix, far])
            if shapes:
                every = np.concatenate(shapes)
                middle = every.shape[1] // 2
                path = every.mean(axis=0)
                print(f"\n    pooled profile over {every.shape[0]:,} turns, bar -{args.span} to +{args.span}")
                for start in range(0, every.shape[1], 7):
                    chunk = path[start : start + 7]
                    offsets = range(start - middle, start - middle + chunk.size)
                    print(
                        "      "
                        + "  ".join(f"{o:+3d} {v:.2f}" for o, v in zip(offsets, chunk, strict=False))
                    )
            print()
            scores = principal(matrix, DESCRIBE)
            if scores.size:
                from persistence import strata_auc

                good = np.isfinite(matrix).all(axis=1)
                for c in range(scores.shape[1]):
                    print(
                        f"        PC{c + 1} on clearance: AUC within distance strata "
                        f"{strata_auc(scores[:, c], done[good], far[good]):.4f}"
                    )
            binned(matrix, done, far, DESCRIBE)
            binned(matrix, done, far, DESCRIBE, picks=("bar_size", "reject_wick", "body_share"))
            for count in (int(c) for c in args.clusters.split(",") if c.strip()):
                cluster(matrix, done, far, DESCRIBE, count)


if __name__ == "__main__":
    main()
