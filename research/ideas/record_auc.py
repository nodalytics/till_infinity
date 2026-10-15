"""Why does a level's own record read AUC 0.648 in one study and 0.5056 in another?

Two measurements of nominally the same claim - *does a level's prior same-side
hold record order its next interaction* - disagree by 0.14 of AUC:

* `strength.md` reports the same-side record at **0.648** against
  `Level.strength`'s 0.548, and `reactions.py` cites that figure in the
  docstring of `Inference.record_hold`, which it publishes so that something
  downstream can rank on it.
* `statespace-conditional-holds.md` reports **0.5056 to 0.5058** with every
  Brier arm worse than predicting the pooled base rate, and concludes the hold
  rate carries nothing.

Both cannot be right, and the field is live: `record_hold` is published for
ranking on the strength of the larger number.

Three differences could produce the gap, and they are separable:

1. **Ties.** A prior hold rate over `k` touches takes `k + 1` distinct values,
   so tied comparisons are everywhere. `conditional_holds.py` documents its own
   AUC as ranking by sorted position with no tie handling, which read **1.0000**
   for a constant arm. An implementation that breaks ties by list order can be
   wrong in either direction by up to half the tie share.
2. **Stratification.** A pooled AUC rewards knowing the **feed** rather than the
   level: if hold rates differ by instrument and interval, a level's record and
   its next outcome are both shifted by the same instrument, and the ordering
   that produces has no level content. `level-shrinkage.md` caught exactly this
   artefact worth +0.112 of MSE on push.
3. **Overlap.** If consecutive interactions are not disjoint, the record and
   the outcome share bars. `prod-probability-up-needs-halving` found a 0.6365
   that became 0.5092 de-overlapped, which is the right order of magnitude for
   this gap on its own.

So: the same quantity, scored as a 2 x 3 x 2 - disjoint or overlapping races,
pooled or stratified by `(feed, interval)` or by feed, real levels or
distance-matched placebos - with the tie share reported beside every figure.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CACHE = Path.home() / "till_infinity/data/seqlab"
FRAMES = ("1h", "4h")
LIMIT = 40000
LOOKBACK = 100
PER_FEED = 60
PATIENCE = 24
LEAST = 12
#: Interactions used as history before an outcome is scored, as `conditional_holds`.
WARM = 5
JITTER = 0.15
SEED = 20261015
TRADED = ("EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "AUDUSD", "USDCAD")
#: `levels.SideStats` shrinks its own record toward 0.5 with this many pseudo
#: observations, so the score is the shrunk rate rather than the raw ratio.
PRIOR = 2.0


def load(name: str, frame: str):
    import numpy as np

    path = CACHE / f"{name}.{frame}.npz"
    if not path.exists():
        return None
    with np.load(path) as bundle:
        need = {"time", "high", "low", "close"}
        if not need <= set(bundle.keys()):
            return None
        order = np.argsort(bundle["time"])
        got = {k: np.asarray(bundle[k], dtype=float)[order] for k in need}
    keep = (got["high"] >= got["low"]) & (got["low"] > 0)
    got = {k: v[keep] for k, v in got.items()}
    if len(got["close"]) < 8000:
        return None
    if len(got["close"]) > LIMIT:
        got = {k: v[-LIMIT:] for k, v in got.items()}
    return got


def interactions(bars, level: float, start: int, move: float, disjoint: bool) -> list[bool]:
    """Resolved interactions with `level`, oldest first.

    `disjoint` is the whole experiment. With it on, the scan resumes **after**
    the race that just settled, so one visit is one interaction and no two
    outcomes share a bar - what `conditional_holds.py` does. With it off, the
    scan resumes one bar after the touch, so a level visited for six
    consecutive bars yields six races over largely the same bars, which is the
    shape that inflates a record-versus-outcome score without any of it being
    about the level.
    """
    highs, lows, closes = bars["high"], bars["low"], bars["close"]
    out: list[bool] = []
    i, end = start, len(highs)
    while i < end:
        if not (lows[i] <= level <= highs[i]):
            i += 1
            continue
        before = closes[i - 1] if i > 0 else closes[i]
        from_below = before < level
        back = level - move if from_below else level + move
        through = level + move if from_below else level - move
        settled: bool | None = None
        j = i + 1
        while j < min(i + 1 + PATIENCE, end):
            if (highs[j] >= through) if from_below else (lows[j] <= through):
                settled = False
                break
            if (lows[j] <= back) if from_below else (highs[j] >= back):
                settled = True
                break
            j += 1
        if settled is not None:
            out.append(settled)
        i = (j + 1) if disjoint else (i + 1)
    return out


def auc(scores: list[float], truths: list[bool]) -> tuple[float, float]:
    """`(tie-aware AUC, share of comparisons that are ties)`.

    `P(score | hold > score | break) + 0.5 * P(equal)`, by `searchsorted` on
    both sides. The tie share is reported because it bounds how wrong an
    implementation that ignores ties can be: half of it, in either direction.
    """
    import numpy as np

    held = np.sort(np.asarray([s for s, t in zip(scores, truths, strict=True) if t], dtype=float))
    broke = np.sort(
        np.asarray([s for s, t in zip(scores, truths, strict=True) if not t], dtype=float)
    )
    if not len(held) or not len(broke):
        return float("nan"), float("nan")
    left = np.searchsorted(broke, held, side="left")
    right = np.searchsorted(broke, held, side="right")
    pairs = float(len(held)) * float(len(broke))
    ties = float((right - left).sum())
    return (float(left.sum()) + 0.5 * ties) / pairs, ties / pairs


def blind(scores: list[float], truths: list[bool]) -> float:
    """AUC by sorted position with **no** tie handling, for the comparison.

    Mann-Whitney on ranks from a stable sort, which gives tied scores distinct
    ranks in list order. Not a correct estimator; included because it is what
    produces a figure like 0.648 out of a quantity that ties constantly, and the
    gap between this and `auc` is the size of that mistake on this data.
    """
    order = sorted(range(len(scores)), key=lambda i: scores[i])
    ranks = [0.0] * len(scores)
    for position, index in enumerate(order, start=1):
        ranks[index] = float(position)
    positives = sum(1 for t in truths if t)
    negatives = len(truths) - positives
    if not positives or not negatives:
        return float("nan")
    total = sum(r for r, t in zip(ranks, truths, strict=True) if t)
    return (total - positives * (positives + 1) / 2.0) / (positives * negatives)


def stratified(rows: list[tuple[str, float, bool]], by: str) -> tuple[float, float, int]:
    """`(AUC, tie share, strata)` with comparisons confined inside each stratum.

    The pooled figure compares a level on one instrument against a level on
    another, so any difference in their base rates reads as ordering power. This
    confines every comparison to one stratum and weights the strata by their
    pair counts, which is the version that can only be about levels.
    """
    groups: dict[str, list[tuple[float, bool]]] = {}
    for key, score, truth in rows:
        groups.setdefault("all" if by == "pooled" else key, []).append((score, truth))
    top, ties, weight, strata = 0.0, 0.0, 0.0, 0
    for found in groups.values():
        scores = [s for s, _ in found]
        truths = [t for _, t in found]
        got, tied = auc(scores, truths)
        if got != got:  # nan
            continue
        held = sum(1 for t in truths if t)
        pairs = float(held) * float(len(truths) - held)
        top += got * pairs
        ties += tied * pairs
        weight += pairs
        strata += 1
    if weight <= 0.0:
        return float("nan"), float("nan"), strata
    return top / weight, ties / weight, strata


def gather(frame: str, disjoint: bool):
    """Scored interactions for real levels and distance-matched placebos."""
    import numpy as np

    rng = np.random.default_rng(SEED)
    out: dict[str, list[tuple[str, float, bool]]] = {"real": [], "fake": []}
    rates: dict[str, dict[str, list[float]]] = {"real": {}, "fake": {}}
    for name in TRADED:
        bars = load(name, frame)
        if bars is None:
            continue
        closes, highs, lows = bars["close"], bars["high"], bars["low"]
        starts = np.linspace(LOOKBACK, len(closes) - 500, PER_FEED, dtype=int)
        for k, at in enumerate(starts):
            window = slice(max(at - LOOKBACK, 0), at)
            move = float(np.median(highs[window] - lows[window]))
            if not (move > 0):
                continue
            level = float(highs[window].max() if k % 2 == 0 else lows[window].min())
            here = float(closes[at])
            gap = level - here
            if abs(gap) < 0.25 * move:
                continue
            scale = 1.0 + float(rng.uniform(-JITTER, JITTER))
            for which, price in (("real", level), ("fake", here + gap * scale)):
                got = interactions(bars, price, int(at), move, disjoint)
                if len(got) < LEAST:
                    continue
                rates[which].setdefault(name, []).append(
                    sum(1 for g in got if g) / len(got)
                )
                for i in range(WARM, len(got)):
                    # The shrunk prior record, as `SideStats.hold_rate` would
                    # have it at that moment: holds so far over touches so far.
                    holds = sum(1 for g in got[:i] if g)
                    score = (holds + PRIOR * 0.5) / (i + PRIOR)
                    out[which].append((f"{name}.{frame}", score, got[i]))
    return out, rates


def main() -> None:
    print(
        "Does a level's prior same-side hold record order its next interaction?\n"
        f"{LOOKBACK}-bar extremes, {LEAST}+ interactions, scored from touch {WARM}.\n"
    )
    for frame in FRAMES:
        for disjoint in (True, False):
            shape = "disjoint races" if disjoint else "OVERLAPPING races"
            rows, rates = gather(frame, disjoint)
            if not rows["real"]:
                continue
            print("=" * 92)
            print(f"{frame}  {shape}")
            print("=" * 92)
            head = f"  {'arm':<6}{'scored':>9}{'tie-aware':>11}{'ties':>8}"
            print(head + f"{'no-tie AUC':>12}{'stratified':>12}{'ties':>8}{'strata':>8}")
            for which in ("real", "fake"):
                found = rows[which]
                scores = [s for _, s, _ in found]
                truths = [t for _, _, t in found]
                pooled, tied = auc(scores, truths)
                naive = blind(scores, truths)
                inside, inside_tied, strata = stratified(found, "feed")
                print(
                    f"  {which:<6}{len(found):>9,}{pooled:>11.4f}{tied:>8.3f}"
                    f"{naive:>12.4f}{inside:>12.4f}{inside_tied:>8.3f}{strata:>8}"
                )
            spread = {
                which: (
                    min(sum(v) / len(v) for v in by.values()),
                    max(sum(v) / len(v) for v in by.values()),
                )
                for which, by in rates.items()
                if by
            }
            if "real" in spread:
                low, high = spread["real"]
                print(
                    f"  per-feed mean hold rate spans {low:.3f} to {high:.3f}, which is what\n"
                    "  a pooled AUC can order on without knowing anything about a level."
                )
            print(
                "  `tie-aware` is P(hold > break) + 0.5 P(equal); `no-tie AUC` ranks by\n"
                "  sorted position and is wrong by up to half the tie share;\n"
                "  `stratified` confines every comparison to one feed and frame.\n"
            )


if __name__ == "__main__":
    main()
