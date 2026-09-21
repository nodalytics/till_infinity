"""Persistent homology of price, tested on direction and on volatility.

Run from the repository root:

    .venv-research/bin/python research/harness/tda.py

Real topological data analysis, not the shape clustering in `motifs.py`. The pipeline
is the standard one for a scalar time series:

1. **Delay embedding.** A window of log returns becomes a point cloud in R^d by
   sliding a d-length lag vector over it. This is the step that gives a 1-D series a
   shape at all - a list of numbers has no topology worth the name.
2. **Vietoris-Rips.** Grow a ball of radius `e` around every point and record the
   complex of mutual intersections as `e` increases.
3. **Persistent homology.** Track when features are born and die: `H0` components,
   which merge as `e` grows, and `H1` loops, which appear and then fill in.
4. **Summarise the diagram** into numbers a model can read - total persistence, max
   persistence, persistence entropy, and the `L1`/`L2` norms of the persistence
   landscape, which is what the finance literature on this actually uses.

`ripser` computes the homology. It is in `.venv-research` and nothing at runtime
imports it.

## The prediction, written down before the run

Gidea and Katz, *Topological data analysis of financial time series: landscapes of
crashes* (Physica A 491, 2018), and Aguilar and Ensor, *Topology data analysis using
mean persistence landscapes in financial crashes* (J. Math. Finance 10(4), 2020), both
report that **persistence landscape norms rise sharply before crashes**.

Read carefully, that is an instability and volatility result. It is not a claim about
which way price goes. And it lines up with two things already established here:
`clustering.md` opens with "direction is noise; volatility is the part that repeats",
and the `triple` run in `supervised-candles.md` had `vol_log_gap` as its single most
important feature by permutation, ahead of every return feature.

So the prediction, recorded before any number came back:

> the persistence features will **fail on direction** and **may work on forward
> volatility**.

Both are tested, in that order, with identical machinery. Writing it down first is the
point - it is what makes the volatility result meaningful if it arrives, and what stops
a directional result being quietly reinterpreted as the thing that was expected.

## What is deliberately not done

Gidea and Katz build their point cloud from **several** series at once, one dimension
per index, so their topology is of the cross-section. This uses a delay embedding of one
instrument, which is the per-instrument question and the one this desk can act on. The
cross-sectional version is a different study and would need the instruments aligned on a
common clock first.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "training"))

import candles  # noqa: E402
import splits  # noqa: E402

#: Embedding dimension for the delay map. 3 is the smallest that admits a loop in
#: `H1` at all, so it is the cheapest setting where the topology is not trivial.
DIM = 3

#: Bars in the window the cloud is built from. Long enough for the cloud to have
#: shape, short enough that the reading is about now rather than about last month.
WINDOW = 40

#: Landscape resolution for the `Lp` norms.
GRID = 32

#: Cost in fractional return terms, for the breakeven line.
COST = 0.0002


def cloud(returns: np.ndarray, dim: int = DIM) -> np.ndarray:
    """A delay embedding: row `i` is `(r[i], r[i+1], ..., r[i+dim-1])`."""
    n = len(returns) - dim + 1
    if n <= dim:
        return np.zeros((0, dim))
    return np.stack([returns[i : i + dim] for i in range(n)])


def diagram(points: np.ndarray) -> dict[int, np.ndarray]:
    """Persistence diagrams by homology dimension, from a Vietoris-Rips filtration."""
    from ripser import ripser

    if len(points) < DIM + 2:
        return {0: np.zeros((0, 2)), 1: np.zeros((0, 2))}
    out = ripser(points, maxdim=1)["dgms"]
    return {d: np.asarray(out[d]) for d in range(len(out))}


def landscape_norms(pairs: np.ndarray, grid: int = GRID) -> tuple[float, float]:
    """`L1` and `L2` norms of the first persistence landscape.

    The landscape is the upper envelope of the tent functions of each birth-death
    pair. Its norms are the summary the crash literature reports, which is the reason
    they are here rather than some other functional of the diagram.
    """
    if not len(pairs):
        return 0.0, 0.0
    finite = pairs[np.isfinite(pairs[:, 1])]
    if not len(finite):
        return 0.0, 0.0
    lo, hi = float(finite.min()), float(finite.max())
    if hi <= lo:
        return 0.0, 0.0
    xs = np.linspace(lo, hi, grid)
    # Tent for each pair: rises from birth, peaks at the midpoint, falls to death.
    births, deaths = finite[:, 0][:, None], finite[:, 1][:, None]
    tents = np.minimum(xs[None, :] - births, deaths - xs[None, :])
    envelope = np.clip(tents, 0.0, None).max(axis=0)
    step = (hi - lo) / max(grid - 1, 1)
    return float(envelope.sum() * step), float(np.sqrt((envelope**2).sum() * step))


def summarise(dgms: dict[int, np.ndarray]) -> list[float]:
    """Numbers a model can read, per homology dimension.

    Total and max persistence say how much structure there is and how strong its
    strongest feature is. Persistence entropy says whether the structure is one big
    feature or many small ones - two diagrams can share a total and differ entirely in
    how it is distributed.
    """
    out: list[float] = []
    for d in (0, 1):
        pairs = dgms.get(d, np.zeros((0, 2)))
        finite = pairs[np.isfinite(pairs[:, 1])] if len(pairs) else pairs
        lives = (finite[:, 1] - finite[:, 0]) if len(finite) else np.zeros(0)
        lives = lives[lives > 0]
        total = float(lives.sum())
        out.append(total)
        out.append(float(lives.max()) if len(lives) else 0.0)
        out.append(float(len(lives)))
        if len(lives) and total > 0:
            share = lives / total
            out.append(float(-(share * np.log(share + 1e-12)).sum()))
        else:
            out.append(0.0)
        one, two = landscape_norms(finite)
        out.append(one)
        out.append(two)
    return out


FEATURE_NAMES = [
    f"h{d}_{name}"
    for d in (0, 1)
    for name in ("total", "max", "count", "entropy", "landscape_l1", "landscape_l2")
]


def features_for(bars: np.ndarray, at: int) -> list[float]:
    """The topology of the window ending at bar `at`, and nothing after it."""
    close = bars[at - WINDOW : at + 1, 4]
    if len(close) < WINDOW or (close <= 0).any():
        return [0.0] * len(FEATURE_NAMES)
    returns = np.diff(np.log(close))
    # Scale out volatility, or the diagram measures how big the moves were, which
    # `vol_bps` already says. The question is whether the *shape* adds anything.
    spread = returns.std()
    if spread > 0:
        returns = returns / spread
    return summarise(diagram(cloud(returns)))


BASELINE_NAMES = [
    "rv_5_over_40",
    "rv_10_over_40",
    "rv_20_over_40",
    "rv_last_over_40",
    "tr_ewma_over_rv",
    "abs_ret_mean",
]


def baseline_for(bars: np.ndarray, at: int) -> list[float]:
    """Trailing volatility, the way anyone would compute it without topology.

    **This is the comparison that decides whether topology is worth anything.**
    Beating block-shuffled labels at forward volatility is nearly free, because
    volatility clusters - that is the most replicated fact in finance and
    `clustering.md` opens with it. A trailing realised-volatility ratio will clear a
    shuffled null easily, so the honest question is not whether persistence beats
    noise but whether it beats *this*.

    All ratios, so nothing carries a price unit, and all from bars `<= at`.
    """
    close = bars[at - WINDOW : at + 1, 4]
    if len(close) < WINDOW or (close <= 0).any():
        return [0.0] * len(BASELINE_NAMES)
    returns = np.diff(np.log(close))
    long = returns.std()
    if long <= 0:
        return [0.0] * len(BASELINE_NAMES)
    out = [
        float(returns[-5:].std() / long),
        float(returns[-10:].std() / long),
        float(returns[-20:].std() / long),
        float(abs(returns[-1]) / long),
    ]
    tr = candles.true_range(bars[at - WINDOW : at + 1])
    out.append(float(tr[-1] / long) if long > 0 else 0.0)
    out.append(float(np.abs(returns).mean() / long))
    return out


def build(paths: list[Path], family: str, horizon: int, band: float, every: int):
    """A panel of topological features against one label family.

    `every` subsamples bars, because a Rips complex per bar over a hundred thousand
    bars is a great deal of homology for windows that overlap by 39 of 40 bars. The
    subsample loses little and is stated rather than hidden.
    """
    from labels import FAMILIES

    make = FAMILIES[family]
    xs, ys, rets, groups, whens = [], [], [], [], []
    for path in sorted(paths):
        name = path.name.split("_")[0]
        bars, _repaired = candles.read(path)
        if len(bars) < WINDOW + horizon + 10:
            continue
        tr = candles.true_range(bars)
        y, ret, valid, classes = make(bars, tr, horizon, band)
        for at in range(WINDOW, len(bars) - horizon, every):
            if not valid[at]:
                continue
            row = features_for(bars, at) + baseline_for(bars, at)
            if not all(np.isfinite(row)):
                continue
            xs.append(row)
            ys.append(int(y[at]))
            rets.append(float(ret[at]))
            groups.append(name)
            whens.append(bars[at, 0])
        print(f"  {name:<22} {len(xs):>7} rows so far")
    return (
        np.array(xs, dtype=np.float32),
        np.array(ys, dtype=np.int64),
        np.array(rets),
        np.array(groups),
        np.array(whens, dtype=float),
        classes,
    )


def evaluate(x, y, when, classes, folds: int, *, shuffled: bool = False) -> dict:
    """Purged walk-forward, exactly as `sk_batch` does it, so results compare."""
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import balanced_accuracy_score

    labels = splits.block_shuffle(y, when, 1) if shuffled else y
    scores, majority = [], []
    for train, test in splits.walk_forward(when, 1, folds=folds):
        if len(np.unique(labels[train])) < 2:
            continue
        model = HistGradientBoostingClassifier(
            max_iter=250, learning_rate=0.06, l2_regularization=1.0, random_state=0
        )
        model.fit(x[train], labels[train])
        said = model.predict(x[test])
        scores.append(balanced_accuracy_score(labels[test], said))
        counts = np.bincount(labels[test], minlength=len(classes))
        majority.append(counts.max() / max(counts.sum(), 1))
    if not scores:
        return {}
    return {
        "balanced": float(np.mean(scores)),
        "chance": 1.0 / len(classes),
        "majority": float(np.mean(majority)),
        "folds": len(scores),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("symbols", nargs="*", default=["xauusd", "eurusd", "gbpusd", "usdjpy"])
    ap.add_argument("--where", default=".secrets/broker-deep")
    ap.add_argument("--interval", default="1h")
    ap.add_argument("--every", type=int, default=8, help="subsample: one row per N bars")
    ap.add_argument("--folds", type=int, default=4)
    args = ap.parse_args()

    paths = []
    for symbol in args.symbols:
        found = sorted(Path(args.where).glob(f"{symbol}_{args.interval}_*.csv.gz"))
        if found:
            paths.append(found[0])
    if not paths:
        print("no candle files found")
        return 1

    print(
        f"delay embedding d={DIM}, window {WINDOW} bars, Rips H0+H1, "
        f"{len(FEATURE_NAMES)} features, one row per {args.every} bars\n"
    )

    # The order is the prediction's order: direction first, volatility second.
    for family, horizon, band in (("banded", 12, 1.0), ("expansion", 12, 1.0)):
        print(f"=== {family}")
        x, y, _ret, groups, when, classes = build(paths, family, horizon, band, args.every)
        if not len(y):
            print("  no rows\n")
            continue
        # Three models on identical rows. The only comparison that matters is the
        # third against the second: topology has earned its place only if adding it
        # to ordinary trailing volatility improves on trailing volatility alone.
        blocks = {
            "topology only": np.arange(len(FEATURE_NAMES)),
            "trailing volatility only": np.arange(len(FEATURE_NAMES), x.shape[1]),
            "both together": np.arange(x.shape[1]),
        }
        null = evaluate(x, y, when, classes, args.folds, shuffled=True)
        print(f"  {len(y):,} rows over {len(set(groups.tolist()))} instruments")
        if null:
            print(f"  {'block-shuffled labels':<26}{null['balanced']:.4f}   <- noise")
        for label, cols in blocks.items():
            got = evaluate(x[:, cols], y, when, classes, args.folds)
            if not got:
                continue
            base = null["balanced"] if null else got["chance"]
            print(
                f"  {label:<26}{got['balanced']:.4f}   lift {got['balanced'] - base:+.4f}"
                f"   ({len(cols)} features)"
            )
        print()

    print(
        "The prediction recorded in the docstring before this ran: direction fails,\n"
        "volatility may work.\n\n"
        "The row that decides it is `both together` against `trailing volatility\n"
        "only`. Topology has earned its place only if adding it to ordinary trailing\n"
        "volatility improves on trailing volatility alone. If `topology only` beats\n"
        "the shuffled null but `both together` does not beat the baseline, then\n"
        "persistence is re-deriving volatility clustering the expensive way."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
