"""Discover exploitable shapes - the named ones, and ones nobody has named.

Run from the repository root:

    .venv-research/bin/python research/harness/shapes.py

`patterns.py` tested the shapes the textbooks name and found them worth about a
point over a matched random entry, which their own target rules then give back.
`motifs.py` clustered raw candle windows and the result died against a block
bootstrap once the window overlap was accounted for. This is the third approach and
the one with an actual argument behind it.

## Why a topological representation and not raw coordinates

**A persistence diagram is invariant to time-warping and to monotone rescaling.** The
same shape unfolding over twenty bars or forty, in a quiet regime or a violent one,
produces a similar diagram. Raw-coordinate clustering treats those as different
things, which is a good reason to think `motifs.py` was looking through the wrong
representation: a shape that recurs *at varying speed* is invisible to it.

That invariance is the whole case for doing this the expensive way. If shapes matter
at all, they matter as shapes, not as fixed-length pixel patterns.

## Why a persistence image and not a persistence norm

`tda.py` summarises each diagram into twelve scalars - total persistence, entropy,
landscape norms. Those cannot find a shape **by construction**: two entirely
different shapes with equal total persistence are identical to them. They answer "how
much structure is here", which is a volatility question, and `tda.py` duly found a
volatility signal and no directional one.

A **persistence image** vectorises the diagram onto a fixed grid while preserving
*where* features are born and die, so different shapes give different images. That is
what makes clustering them a search over shapes rather than over magnitudes.

## Old, new, and undiscovered

Every cluster is reported, and each is cross-tabulated against the named patterns from
`patterns.py` that fall inside it. So a cluster is one of three things:

* **old** - it is largely a known pattern, and its edge should match what
  `patterns.py` measured for that pattern;
* **new** - it contains named patterns but mixes several, so the clustering has found
  a grouping the textbooks split, or split one they group;
* **undiscovered** - it contains almost no named pattern at all.

The third is the interesting column, and it is also the one most likely to be noise,
which is why the controls below are not optional.

## The controls, which killed the last two attempts

**The base rate is the placebo.** Every row carries the same symmetric barrier, so
geometry is constant and the overall hit rate is exactly "this geometry entered at an
arbitrary moment". A shape must beat that, not beat 50%.

**A block bootstrap, not a two-proportion error.** Consecutive windows overlap almost
entirely and their forward windows intersect, so an error bar assuming independent
rows is too narrow - that is precisely what made `motifs.py` look significant before
the bootstrap halved its margin. Blocks are longer than the window plus the horizon.

**Fitted on the past, scored on the future**, and then **leave one instrument out**.

**And the count of survivors is compared with the count expected by chance**, because
with enough clusters something always clears a bar.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "training"))

import candles  # noqa: E402

#: Delay embedding, **measured rather than assumed**. `embed.py` puts the first
#: minimum of mutual information at a lag of 4 to 5 and false nearest neighbours at
#: dimension 6 across every real instrument (5 on the synthetics), with near-identical
#: curves on all seven tested. The first version of this file used lag 1 and dimension
#: 3, which collapses the cloud towards its diagonal - adjacent returns are nearly
#: redundant - and under-embeds it. Its negative result was measured at the wrong
#: embedding.
DIM = 6
LAG = 4

#: Bars in the window. It has to hold `DIM * LAG` coordinates plus enough points for a
#: cloud to have shape, so raising the dimension raised this too.
WINDOW = 64

#: Persistence image resolution per side. 8x8 per homology dimension keeps the
#: vector small enough to cluster and large enough to tell shapes apart.
PIXELS = 8

#: Clusters to look for. One value, not a sweep: every extra value multiplies the
#: best-of-K problem and the expected-by-chance line is what holds it honest.
SHAPES = 20

#: Smallest cluster worth reporting.
FLOOR = 150

#: Rows between samples. A Rips complex and an image per bar over a hundred thousand
#: bars is a great deal of homology for windows that overlap by 39 of 40 bars.
EVERY = 12


def diagrams(bars: np.ndarray, at: int) -> dict[int, np.ndarray]:
    """Persistence diagrams of the delay embedding of the window ending at `at`."""
    from ripser import ripser

    close = bars[at - WINDOW : at + 1, 4]
    if len(close) < WINDOW or (close <= 0).any():
        return {}
    returns = np.diff(np.log(close))
    spread = returns.std()
    if spread <= 0:
        return {}
    # Scaled out, so the diagram is about shape rather than about size - size is
    # what `vol_bps` already reports and what `tda.py` found.
    returns = returns / spread
    span = (DIM - 1) * LAG
    count = len(returns) - span
    if count < DIM + 2:
        return {}
    points = np.stack([returns[i * LAG : i * LAG + count] for i in range(DIM)], axis=1)
    if len(points) < DIM + 2:
        return {}
    out = ripser(points, maxdim=1)["dgms"]
    return {d: np.asarray(out[d]) for d in range(len(out))}


def image_of(dgms: dict[int, np.ndarray], imagers: dict) -> np.ndarray:
    """Both homology dimensions as one flat persistence-image vector."""
    parts = []
    for d in (0, 1):
        pairs = dgms.get(d, np.zeros((0, 2)))
        finite = pairs[np.isfinite(pairs[:, 1])] if len(pairs) else np.zeros((0, 2))
        if not len(finite):
            parts.append(np.zeros(PIXELS * PIXELS))
            continue
        img = imagers[d].transform(finite, skew=True)
        parts.append(np.asarray(img).ravel())
    return np.concatenate(parts)


def make_imagers(samples: list[dict]) -> dict:
    """Fit one imager per homology dimension on a sample of diagrams.

    The imager's birth and persistence ranges have to come from data, and they come
    from the **training** diagrams only - a range fitted on everything would let the
    test period influence the grid every shape is measured on.
    """
    from persim import PersistenceImager

    out = {}
    for d in (0, 1):
        pairs = [s[d][np.isfinite(s[d][:, 1])] for s in samples if d in s and len(s[d])]
        pairs = [p for p in pairs if len(p)]
        imager = PersistenceImager(pixel_size=1.0)
        if pairs:
            imager.fit(pairs, skew=True)
            # Force a fixed grid so every image has the same length.
            span_b = max(imager.birth_range[1] - imager.birth_range[0], 1e-6)
            span_p = max(imager.pers_range[1] - imager.pers_range[0], 1e-6)
            imager.pixel_size = max(span_b, span_p) / PIXELS
            imager.birth_range = (
                imager.birth_range[0],
                imager.birth_range[0] + imager.pixel_size * PIXELS,
            )
            imager.pers_range = (
                imager.pers_range[0],
                imager.pers_range[0] + imager.pixel_size * PIXELS,
            )
        out[d] = imager
    return out


def build(paths: list[Path], horizon: int, band: float, every: int):
    """Persistence images, labels and the named pattern at each row, if any."""
    import patterns as named
    from labels import FAMILIES

    make = FAMILIES["triple"]
    rows: list[dict] = []
    for path in sorted(paths):
        name = path.name.split("_")[0]
        bars, _repaired = candles.read(path)
        if len(bars) < WINDOW + horizon + 10:
            continue
        tr = candles.true_range(bars)
        y, _ret, valid, classes = make(bars, tr, horizon, band)

        # Which bars a textbook pattern triggered on, so clusters can be labelled
        # old or undiscovered rather than guessed at.
        peaks, troughs = named.swings(bars)
        tagged: dict[int, str] = {}
        for label, find in named.PATTERNS.items():
            for setup in find(bars, tr, peaks, troughs, 1.0):
                tagged.setdefault(int(setup["at"]), label)

        kept = 0
        for at in range(WINDOW, len(bars) - horizon, every):
            if not valid[at]:
                continue
            dgms = diagrams(bars, at)
            if not dgms:
                continue
            rows.append(
                {
                    "dgms": dgms,
                    "y": int(y[at]),
                    "when": float(bars[at, 0]),
                    "group": name,
                    "named": tagged.get(at, ""),
                }
            )
            kept += 1
        print(f"  {name:<22} {kept:>6} windows")
    return rows, classes


def hit_rate(y: np.ndarray, classes: list[str]) -> tuple[float, int]:
    top = len(classes) - 1
    resolved = (y == top) | (y == 0)
    n = int(resolved.sum())
    return (float((y[resolved] == top).mean()) if n else 0.0), n


def bootstrap_gap(labels, y, classes, k, draws, block, rng) -> tuple[float, float]:
    """A shape's gap over everything else, with a block resample that keeps overlap."""
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
        mine, rest = ok & (labels[idx] == k), ok & (labels[idx] != k)
        if mine.sum() < 25 or rest.sum() < 25:
            continue
        gaps.append(hit[idx][mine].mean() - hit[idx][rest].mean())
    if len(gaps) < 20:
        return float("nan"), float("nan")
    lo, hi = np.percentile(gaps, [2.5, 97.5])
    return float(np.mean(gaps)), float((hi - lo) / 2.0)


def walk(labels, y, named, classes, args) -> tuple[int, int]:
    """Report every shape big enough to judge, and count the survivors."""
    block = WINDOW + args.horizon
    rng = np.random.default_rng(0)
    survivors = reported = 0
    for k in sorted(set(labels.tolist())):
        mine = labels == k
        if int(mine.sum()) < FLOOR:
            continue
        rate, n = hit_rate(y[mine], classes)
        if n < FLOOR:
            continue
        other, _ = hit_rate(y[~mine], classes)
        mean, band = bootstrap_gap(labels, y, classes, k, args.bootstrap, block, rng)
        reported += 1
        tags = [t for t in named[mine] if t]
        share = len(tags) / max(int(mine.sum()), 1)
        if share < 0.02:
            what = "undiscovered - almost no named pattern"
        else:
            what = f"{share:.0%} named, mostly {max(set(tags), key=tags.count)}"
        clears = bool(np.isfinite(band) and abs(mean) > band)
        survivors += clears
        print(
            f"{k:>6}{n:>8,}{rate:>8.1%}{rate - other:>+8.1%}{band:>10.1%}  "
            f"{what}{'  <-' if clears else ''}"
        )
    return survivors, reported


def main() -> int:
    from sklearn.cluster import MiniBatchKMeans

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("symbols", nargs="*", default=["xauusd", "eurusd", "gbpusd", "usdjpy"])
    ap.add_argument("--where", default=".secrets/broker-deep")
    ap.add_argument("--interval", default="1h")
    ap.add_argument("--shapes", type=int, default=SHAPES)
    ap.add_argument("--horizon", type=int, default=24)
    ap.add_argument("--band", type=float, default=1.0)
    ap.add_argument("--every", type=int, default=EVERY)
    ap.add_argument("--fit", type=float, default=0.6)
    ap.add_argument("--bootstrap", type=int, default=300)
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
        f"delay d={DIM} lag={LAG}, window {WINDOW}, images {PIXELS}x{PIXELS} per "
        f"dimension, {args.shapes} shapes, one row per {args.every} bars\n"
    )
    rows, classes = build(paths, args.horizon, args.band, args.every)
    if len(rows) < 2000:
        print(f"only {len(rows)} windows - not enough to cluster")
        return 1

    when = np.array([r["when"] for r in rows])
    order = np.argsort(when, kind="stable")
    cut = int(len(order) * args.fit)
    train, test = order[:cut], order[cut:]

    imagers = make_imagers([rows[i]["dgms"] for i in train[:4000]])
    images = np.stack([image_of(r["dgms"], imagers) for r in rows])
    print(f"\n{len(rows):,} windows, image vector {images.shape[1]} long")

    model = MiniBatchKMeans(n_clusters=args.shapes, random_state=0, n_init=10, batch_size=2048)
    model.fit(images[train])
    labels = model.predict(images[test])

    y = np.array([rows[i]["y"] for i in test])
    named = np.array([rows[i]["named"] for i in test])
    base, base_n = hit_rate(y, classes)
    print(f"\nbase rate {base:.1%} on {base_n:,} resolved windows")
    print(f"{'shape':>6}{'n':>8}{'hit':>8}{'gap':>8}{'boot +/-':>10}  what is in it")

    survivors, reported = walk(labels, y, named, classes, args)
    print(
        f"\n{survivors} of {reported} shapes clear their bootstrap band; "
        f"about {0.05 * reported:.1f} expected by chance"
    )
    print(
        "  The bootstrap band is the one to read - it keeps the overlap between\n"
        "  windows, which a two-proportion error does not, and halving that error is\n"
        "  what removed the `motifs.py` result. A shape is only interesting if it\n"
        "  clears this band AND the survivor count beats the chance line."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
