"""Let the data name the patterns, then ask whether any of them predicts anything.

Run from the repository root:

    .venv-research/bin/python research/harness/motifs.py

`patterns.py` tested the shapes the books name. This inverts it: cluster the candle
geometry the instruments actually produce, and check whether any recurring shape - a
*motif* - is followed by something other than the base rate.

The appeal over a named pattern is that there is no tolerance to choose. A double top
needs somebody to decide what "roughly the same price" means; a motif is whatever the
clustering finds, and the only choice is how many clusters to look for.

## Why the base rate is already the right control

Every row carries the **same** symmetric barrier - one true range either side - so the
geometry is identical across the whole panel. That makes the overall hit rate exactly
the "same geometry entered at an arbitrary bar" placebo that `patterns.py` had to
construct by hand, and a motif has to beat it rather than beat 50%.

It also means this file cannot repeat the mistake `patterns.py` caught: a cluster
cannot win by quietly having a different reward-to-risk, because it does not have one.

## The three controls, because unsupervised search is the easiest way to fool yourself

**Clusters are fitted on the past and scored on the future.** The centroids come from
the first `--fit` share of the panel by time, and every number reported is from the
remainder. A clustering fitted on everything would be choosing its shapes with the
test period's geometry in hand.

**Leave one instrument out.** Centroids are fitted on the other instruments and the
held-out one's windows are assigned to them. A motif that only exists on one
instrument shows up here and nowhere else, which is the control that caught the
daily-to-monthly momentum result when four weaker ones had passed.

**K clusters is K chances.** With 24 clusters and a two-standard-error bar, about one
cluster is expected to clear it by luck; with 48, about two. The expected count is
printed next to the observed count, because "three clusters were significant" means
nothing until it is compared with how many should have been.

## What it cannot say

A motif is a shape in normalised space, and two windows in the same cluster can look
different to an operator. This says whether the *clustering* separates outcomes, not
whether any human-nameable pattern does. And it says nothing about a motif's own best
exit - every row is scored on one fixed barrier, deliberately, so that the comparison
across motifs is clean.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "training"))

import candles  # noqa: E402

#: Clusters to look for. Not swept: every extra value multiplies the best-of-K
#: problem, and the expected-by-chance count below is what keeps it honest.
CLUSTERS = 24

#: Share of the panel, by time, used to fit the centroids.
FIT_SHARE = 0.6

#: Smallest cluster worth reporting in the test period.
FLOOR = 200


def fit_centroids(windows: np.ndarray, clusters: int, seed: int = 0):
    """K-means on flattened scale-free windows.

    `MiniBatchKMeans` because the panel runs to hundreds of thousands of windows and
    the exact algorithm buys nothing here - the question is whether *any* reasonable
    partition separates outcomes, not whether this is the optimal partition.
    """
    from sklearn.cluster import MiniBatchKMeans

    flat = windows.reshape(len(windows), -1)
    model = MiniBatchKMeans(n_clusters=clusters, random_state=seed, n_init=10, batch_size=4096)
    model.fit(flat)
    return model


def score(labels: np.ndarray, y: np.ndarray, classes: list[str]) -> list[tuple]:
    """Per cluster: how often the favourable barrier came first, against the base.

    Timeouts are dropped rather than counted as failures - the desk exits on
    barriers, and a window that resolved neither way is a different question. The
    base rate is computed on the same filtered rows so the comparison is like for
    like.
    """
    top, bottom = len(classes) - 1, 0
    resolved = (y == top) | (y == bottom)
    base_hits = int((y[resolved] == top).sum())
    base_total = int(resolved.sum())
    base = base_hits / max(base_total, 1)

    out = []
    for k in sorted(set(labels.tolist())):
        mine = resolved & (labels == k)
        total = int(mine.sum())
        if total < FLOOR:
            continue
        hits = int((y[mine] == top).sum())
        rate = hits / total
        # Two-proportion error against the base rate computed on everything else,
        # so a large cluster is not being compared against itself.
        others = resolved & (labels != k)
        o_total = int(others.sum())
        o_rate = int((y[others] == top).sum()) / max(o_total, 1)
        se = (rate * (1 - rate) / total + o_rate * (1 - o_rate) / max(o_total, 1)) ** 0.5
        out.append((k, total, rate, o_rate, rate - o_rate, 2 * se))
    return out, base, base_total


def block_gap(
    labels: np.ndarray,
    y: np.ndarray,
    classes: list[str],
    k: int,
    draws: int,
    block: int,
    rng: np.random.Generator,
) -> tuple[float, float]:
    """A motif's gap over the rest, and a block-bootstrap band for it.

    The overlap is the whole problem: neighbouring rows share nearly all of their
    window and their forward windows intersect, so treating rows as independent
    understates the error. Resampling **contiguous blocks** of rows, with the block
    longer than the window and the horizon together, keeps that dependence inside the
    resample instead of averaging it away.
    """
    top = len(classes) - 1
    resolved = (y == top) | (y == 0)
    hit = (y == top).astype(float)
    n = len(y)
    starts = np.arange(0, max(n - block, 1))
    gaps = []
    for _ in range(draws):
        pick = rng.choice(starts, size=max(n // block, 1), replace=True)
        idx = np.concatenate([np.arange(s, min(s + block, n)) for s in pick])
        ok = resolved[idx]
        if not ok.any():
            continue
        mine = ok & (labels[idx] == k)
        rest = ok & (labels[idx] != k)
        if mine.sum() < 30 or rest.sum() < 30:
            continue
        gaps.append(hit[idx][mine].mean() - hit[idx][rest].mean())
    if len(gaps) < 20:
        return float("nan"), float("nan")
    lo, hi = np.percentile(gaps, [2.5, 97.5])
    return float(np.mean(gaps)), float((hi - lo) / 2.0)


def report(title: str, rows: list[tuple], base: float, base_total: int) -> int:
    print(f"\n{title}")
    print(f"  base rate {base:.1%} on {base_total:,} resolved rows")
    print(f"  {'motif':>6}{'n':>9}{'hit':>8}{'rest':>8}{'gap':>8}{'+/-':>7}")
    beat = 0
    for k, total, rate, o_rate, gap, band in sorted(rows, key=lambda r: -r[4]):
        mark = ""
        if abs(gap) > band:
            beat += 1
            mark = "  <-"
        print(f"  {k:>6}{total:>9,}{rate:>8.1%}{o_rate:>8.1%}{gap:>+8.1%}{band:>7.1%}{mark}")
    # With this many independent looks at a two-sided 2-SE bar, about 4.6% clear it
    # by chance. Printing the expectation is the difference between a result and a
    # count of coin flips.
    expected = 0.046 * len(rows)
    print(
        f"  {beat} of {len(rows)} motifs clear two standard errors; "
        f"about {expected:.1f} expected by chance"
    )
    print(
        "  **those bars are optimistic.** Consecutive rows share all but one bar of\n"
        "  their window and their horizons overlap, so a two-proportion error assuming\n"
        "  independent observations is too small. `--bootstrap` replaces it with a\n"
        "  block resample that keeps the overlap, and is the number to believe."
    )
    return beat


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("symbols", nargs="*", default=["xauusd", "eurusd", "gbpusd", "usdjpy"])
    ap.add_argument("--where", default=".secrets/broker-deep")
    ap.add_argument("--interval", default="1h")
    ap.add_argument("--clusters", type=int, default=CLUSTERS)
    ap.add_argument("--horizon", type=int, default=24)
    ap.add_argument("--band", type=float, default=1.0)
    ap.add_argument("--fit", type=float, default=FIT_SHARE)
    ap.add_argument(
        "--bootstrap",
        type=int,
        default=0,
        help="block-bootstrap draws for the top and bottom motif; 0 is off, 400 is real",
    )
    args = ap.parse_args()

    paths = []
    for symbol in args.symbols:
        found = sorted(Path(args.where).glob(f"{symbol}_{args.interval}_*.csv.gz"))
        if found:
            paths.append(found[0])
        else:
            print(f"{symbol}: no {args.interval} file")
    if not paths:
        return 1

    print(
        f"{len(paths)} instruments, {args.clusters} clusters, window "
        f"{candles.WINDOW} bars, barrier +/-{args.band} TR, horizon {args.horizon}\n"
    )
    windows, panel = candles.sequences(paths, family="triple", horizon=args.horizon, band=args.band)
    if not len(panel):
        print("no usable rows")
        return 1
    print(f"{len(panel):,} windows over {len(set(panel.groups.tolist()))} instruments")

    order = np.argsort(panel.when, kind="stable")
    cut = int(len(order) * args.fit)
    train, test = order[:cut], order[cut:]

    model = fit_centroids(windows[train], args.clusters)
    labels = model.predict(windows[test].reshape(len(test), -1))
    rows, base, base_total = score(labels, panel.y[test], panel.classes)
    report(
        f"fitted on the first {args.fit:.0%} by time, scored on the rest", rows, base, base_total
    )

    if args.bootstrap and rows:
        bootstrap(rows, labels, panel, test, args)

    held_out(windows, panel, args)
    return 0


def bootstrap(rows, labels, panel, test, args) -> None:
    """Re-band the best and worst motif with a resample that keeps the overlap."""
    block = candles.WINDOW + args.horizon
    rng = np.random.default_rng(0)
    print(f"\nblock bootstrap, {args.bootstrap} draws, blocks of {block} rows")
    ranked = sorted(rows, key=lambda r: -r[4])
    for label, row in (("best", ranked[0]), ("worst", ranked[-1])):
        mean, band = block_gap(
            labels, panel.y[test], panel.classes, row[0], args.bootstrap, block, rng
        )
        print(
            f"  {label} motif {row[0]:>3}: gap {mean:+.1%} +/- {band:.1%} "
            f"(naive band was +/-{row[5]:.1%})"
        )


def held_out(windows, panel, args) -> None:
    """Centroids from the other instruments, scored on the one held back."""
    print("\nleave one instrument out - centroids from the others, scored on the held-out one")
    for name in sorted(set(panel.groups.tolist())):
        held = panel.groups == name
        rest = np.flatnonzero(~held)
        mine = np.flatnonzero(held)
        if len(rest) < 5000 or len(mine) < FLOOR * 2:
            continue
        # The time cut is kept: centroids from the others' earlier period only, so a
        # motif cannot be defined using the held-out instrument's own future.
        rest = rest[np.argsort(panel.when[rest], kind="stable")]
        rest = rest[: int(len(rest) * args.fit)]
        boundary = panel.when[rest].max()
        mine = mine[panel.when[mine] > boundary]
        if len(mine) < FLOOR * 2:
            continue
        other = fit_centroids(windows[rest], args.clusters)
        got = other.predict(windows[mine].reshape(len(mine), -1))
        rows, base, base_total = score(got, panel.y[mine], panel.classes)
        report(f"  held out: {name}", rows, base, base_total)


if __name__ == "__main__":
    raise SystemExit(main())
