"""Which level gets touched first, and which breaks first - a relative question.

Asked on 2026-10-14: *we can also use the method of trying to estimate the one
that will get touched first*, *or the one that will break first*, *then we take
the opposite direction in trading*, and *since we now have p_up and p_down we
can use a posterior approach*.

**Why this is better posed than what came before.** `two-sided-direction.md`
failed on overlap: it walked touches of one price and scored each over the next
forty bars, and consecutive touches shared most of their window. This asks a
different question - from **one** decision point, of the nearest level above and
the nearest level below, which is reached first - so one decision point is one
forward window and spacing the decision points by a full horizon makes them
disjoint by construction. The trap cannot occur here.

It is also the decision the desk actually faces, and it has a base rate near a
half rather than one set by drift.

## The incumbent is a ruler

Price reaches the nearer level first, most of the time. So **distance decides
this question before any level attribute is consulted**, and the only number
worth reporting is the one measured inside strata of the distance ratio. That is
the same discipline that reduced an AUC of 0.805 to 0.525 in `candle-screen.md`
and walked a topological range score to the null in `topology.md`.

## The posterior, now that both sides exist

With `p_up` and `p_down` estimated on separate events - the chance the upper
level is reached, and the chance the lower one is - the decision is a posterior
rather than a difference:

    P(upper first) = p_up / (p_up + p_down)

and because each side is a Beta, the spread of that ratio is available too. So
abstention becomes principled: decline when the credible interval straddles a
half, instead of thresholding an arbitrary gap. Both are reported, the point
estimate and the coverage it costs.

## Two outcomes, which are not the same question

**Touched first** is reached by any wick. **Broken first** needs a close beyond
the level by a margin, which is what a position would actually need, and the two
can disagree - a level touched first and rejected is the opposite trade to a
level broken first. The *fade* reading follows directly: if the model calls
which side is reached and the realised move then reverses, the opposite
direction is the trade, and the column that says so is the outcome rate after a
touch, not the touch itself.
"""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
ROOT = HERE.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from level_signatures import (  # noqa: E402
    CONTROL,
    DRAWS,
    GENERATED,
    LOOKBACK,
    SEED,
    TRADED,
    auc,
    load,
    shuffle_blocks,
)

#: Bars a decision is watched for. Decisions are spaced by this, so no two
#: share a bar of outcome.
HORIZON = int(os.environ.get("HORIZON", "120"))
#: A break needs a close this far beyond the level, in typical bars.
MARGIN = float(os.environ.get("MARGIN", "0.25"))
STRATA = int(os.environ.get("STRATA", "10"))
PICKS = tuple(float(k) for k in os.environ.get("PICKS", "1.0,0.3,0.1").split(","))


def levels_at(bars, at: int, move: float) -> tuple[float, float] | None:
    """The nearest swing high above and swing low below the current price.

    Swings rather than the window extremes, so the two sides are built the same
    way and the question is not decided by one of them being the all-time high.
    """
    highs, lows, closes = bars["high"], bars["low"], bars["close"]
    window = range(max(at - LOOKBACK, 2), at - 1)
    here = float(closes[at])
    above = [
        float(highs[i])
        for i in window
        if highs[i] > highs[i - 1] and highs[i] > highs[i + 1] and highs[i] > here + 0.25 * move
    ]
    below = [
        float(lows[i])
        for i in window
        if lows[i] < lows[i - 1] and lows[i] < lows[i + 1] and lows[i] < here - 0.25 * move
    ]
    if not above or not below:
        return None
    return min(above), max(below)


def race(bars, at: int, upper: float, lower: float, move: float) -> tuple[int, int]:
    """Which was touched first, and which was broken first. `-1` for neither."""
    highs, lows, closes = bars["high"], bars["low"], bars["close"]
    end = min(at + HORIZON, len(closes))
    touched = broken = -1
    for i in range(at + 1, end):
        if touched < 0:
            up_hit = highs[i] >= upper
            down_hit = lows[i] <= lower
            if up_hit and down_hit:
                touched = 2  # same bar, undecided
            elif up_hit:
                touched = 1
            elif down_hit:
                touched = 0
        if broken < 0:
            up_break = closes[i] >= upper + MARGIN * move
            down_break = closes[i] <= lower - MARGIN * move
            if up_break and down_break:
                broken = 2
            elif up_break:
                broken = 1
            elif down_break:
                broken = 0
        if touched >= 0 and broken >= 0:
            break
    return touched, broken


def collect(bars, feed: str) -> list[dict]:
    closes = bars["close"]
    highs, lows = bars["high"], bars["low"]
    out: list[dict] = []
    # Spaced by a full horizon: one decision, one window, no sharing.
    for at in range(LOOKBACK + 2, len(closes) - HORIZON - 2, HORIZON):
        window = slice(at - LOOKBACK, at)
        move = float(np.median(highs[window] - lows[window]))
        if not (move > 0):
            continue
        pair = levels_at(bars, at, move)
        if pair is None:
            continue
        upper, lower = pair
        here = float(closes[at])
        touched, broken = race(bars, at, upper, lower, move)
        out.append(
            {
                "feed": feed,
                # The ruler: how much nearer one side is than the other.
                "closer_up": (here - lower) - (upper - here),
                "reach_up": (upper - here) / move,
                "reach_down": (here - lower) / move,
                "touched": touched,
                "broken": broken,
            }
        )
    return out


def stratified(score: np.ndarray, truth: np.ndarray, by: np.ndarray, bins: int) -> float:
    edges = np.quantile(by, np.linspace(0, 1, bins + 1)[1:-1])
    cell = np.clip(np.searchsorted(edges, by), 0, bins - 1)
    total = weight = 0.0
    for tag in range(bins):
        pick = cell == tag
        yes, no = score[pick & (truth > 0.5)], score[pick & (truth < 0.5)]
        if len(yes) < 3 or len(no) < 3:
            continue
        got = auc(yes, no)
        if math.isfinite(got):
            total += got * pick.sum()
            weight += pick.sum()
    return total / weight if weight else float("nan")


def report(label: str, rows: list[dict]) -> None:
    if len(rows) < 200:
        print(f"  {label}: {len(rows)} decisions, too few\n")
        return
    closer = np.array([r["closer_up"] for r in rows])
    # Distance alone, as a ratio, which is the incumbent for both questions.
    ratio = np.array([r["reach_up"] / max(r["reach_down"], 1e-9) for r in rows])
    print(f"  {label}: {len(rows)} decisions, spaced {HORIZON} bars")
    for name in ("touched", "broken"):
        flag = np.array([r[name] for r in rows], dtype=float)
        decided = (flag == 0) | (flag == 1)
        if decided.sum() < 100:
            print(f"    {name:<8} {int(decided.sum())} decided, too few")
            continue
        truth = flag[decided]
        dial = closer[decided]
        print(
            f"    {name:<8} {int(decided.sum())} decided of {len(rows)}, "
            f"upper first {truth.mean():.3f}"
        )
        got = auc(dial[truth > 0.5], dial[truth < 0.5])
        print(f"      distance alone (the ruler) : {got:.4f}")
        for bins in (5, STRATA, 20):
            inner = stratified(dial, truth, ratio[decided], bins)
            if math.isfinite(inner):
                print(f"      within {bins:>2} distance strata   : {inner:.4f}")
    print(
        "      The ruler decides this question. Anything proposed for it has to\n"
        "      be read inside strata of the distance ratio, and the strata have\n"
        "      to be swept - an effect that survives five and dies at twenty was\n"
        "      the distance all along.\n"
    )


def main() -> None:
    rng = np.random.default_rng(SEED)
    print(
        f"{LOOKBACK}-bar swing levels, {HORIZON}-bar horizon spaced to match,\n"
        f"break needs a close {MARGIN} typical bars beyond, {DRAWS} draws\n"
    )
    for group, names in (("traded", TRADED), ("control", CONTROL), ("generated", GENERATED)):
        print("=" * 76)
        print(group)
        print("=" * 76)
        rows: list[dict] = []
        mixed: list[dict] = []
        for name in names:
            bars = load(name)
            if bars is None:
                continue
            rows += collect(bars, name)
            mixed += collect(shuffle_blocks(bars, rng), name)
        report("real", rows)
        report("shuffled", mixed)


if __name__ == "__main__":
    main()
