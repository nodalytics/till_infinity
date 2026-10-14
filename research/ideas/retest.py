"""Does lower volume on the retest predict the second impulse?

The one idea from the MT5 list worth running. `outcome-prediction.md` found the
retest is already the **most predictable** event in the production journal -
`backcheck` is 7 to 10% of touches and `confluence_n` calls it at 0.6140 - so
the event exists and is detectable. What nobody here has measured is the
condition the idea puts on it:

> if price retraces back to the broken swing high, and the tick volume on the
> retest is at least 30% lower than the volume on the initial breakout bar, it
> confirms a lack of selling pressure

That is a claim about a **ratio of two tick volumes** predicting continuation,
and it is falsifiable as stated.

## How it is scored

A break is a close beyond the rolling structural extreme by a margin. A retest
is price returning to the broken level within `WAIT` bars. Continuation is a new
extreme beyond the break within `AHEAD` bars of the retest.

Three things this has to survive, each bought with a false positive earlier:

**Non-overlapping decisions.** Each retest's forward window is skipped before
the next break is looked for, so no two decisions share an outcome bar - the
defect that produced an AUC of 0.79 in `two-sided-direction.md`.

**A block-shuffled arm.** Bar geometry and the volume marginal survive, the
ordering does not. A volume-ratio effect that needs the real sequence must beat
its shuffled twin.

**An incumbent.** Continuation has obvious predictors that need no volume at
all - how far the break travelled, and how long the retest took. The volume
ratio is reported beside them and inside strata of them, because a ratio that
only works where the break was large is the break size.
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

from level_signatures import SEED, auc, shuffle_blocks  # noqa: E402
from screen import load  # noqa: E402

FRAME = os.environ.get("RETEST_FRAME", "4h")
#: Bars the structural extreme is taken over. Twenty days on 4h is 120 bars.
LOOK = int(os.environ.get("LOOK", "120"))
#: A break needs a close this far beyond, in typical bars.
MARGIN = float(os.environ.get("MARGIN", "0.25"))
#: Bars the retest is allowed to arrive within.
WAIT = int(os.environ.get("WAIT", "60"))
#: Bars the continuation is judged over, and the gap enforced after each call.
AHEAD = int(os.environ.get("AHEAD", "30"))
#: The idea's own threshold: retest volume at most this share of the break bar's.
QUIET = float(os.environ.get("QUIET", "0.70"))
STRATA = int(os.environ.get("STRATA", "5"))
#: Which outcome. `continued` is the idea's own - a new extreme beyond the
#: break - and is **confounded**: the further the break ran before the retest,
#: the harder it is to exceed, so `travel` and `patience` predict it by
#: construction. `forward` is the signed move from the retest and contains
#: neither.
TARGET = os.environ.get("TARGET", "forward")


def events(bars) -> list[dict]:
    """Break, retest, volume ratio, and whether the second impulse came."""
    o, h, l_, c = bars["open"], bars["high"], bars["low"], bars["close"]
    v = bars["volume"]
    out: list[dict] = []
    i = LOOK + 1
    end = len(c) - WAIT - AHEAD - 2
    while i < end:
        window = slice(i - LOOK, i)
        move = float(np.median(h[window] - l_[window]))
        if not (move > 0):
            i += 1
            continue
        top = float(h[window].max())
        bottom = float(l_[window].min())
        up = c[i] > top + MARGIN * move
        down = c[i] < bottom - MARGIN * move
        if not (up or down):
            i += 1
            continue
        level = top if up else bottom
        break_volume = float(v[i])
        extreme = float(h[i]) if up else float(l_[i])
        # The retest: price back to the broken level within WAIT bars.
        retest = -1
        for j in range(i + 1, min(i + 1 + WAIT, len(c))):
            if up and l_[j] <= level:
                retest = j
                break
            if down and h[j] >= level:
                retest = j
                break
            extreme = max(extreme, float(h[j])) if up else min(extreme, float(l_[j]))
        if retest < 0 or break_volume <= 0:
            i += 1
            continue
        after = slice(retest + 1, retest + 1 + AHEAD)
        if retest + 1 + AHEAD >= len(c):
            break
        went = float(h[after].max()) > extreme if up else float(l_[after].min()) < extreme
        # **A second target, because the first one is definitional.**
        # "Exceeded the pre-retest extreme" is harder the further the break
        # already ran and the longer the retest took - so `travel` reads an AUC
        # of 0.2401 against it and `patience` 0.2629, which are not predictions
        # but restatements of the target. A signed forward move from the retest
        # has neither quantity inside it.
        step = math.log(float(c[retest + AHEAD]) / float(c[retest]))
        forward = step if up else -step
        out.append(
            {
                "up": 1.0 if up else 0.0,
                "ratio": float(v[retest]) / break_volume,
                "continued": 1.0 if went else 0.0,
                "forward": 1.0 if forward > 0 else 0.0,
                # The incumbents: how far the break ran, and how long the
                # retest took. Both predict continuation with no volume in them.
                "travel": abs(extreme - level) / move,
                "patience": float(retest - i),
            }
        )
        # No two decisions share an outcome bar.
        i = retest + AHEAD + 1
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


def report(label: str, pool: list[list[dict]]) -> None:
    flat = [e for feed in pool for e in feed]
    if len(flat) < 100:
        print(f"    {label:<10} {len(flat)} events, too few")
        return
    ratio = np.array([e["ratio"] for e in flat])
    truth = np.array([e[TARGET] for e in flat])
    travel = np.array([e["travel"] for e in flat])
    patience = np.array([e["patience"] for e in flat])
    quiet = ratio <= QUIET
    got = auc(ratio[truth > 0.5], ratio[truth < 0.5])
    per_feed = []
    for feed in pool:
        if len(feed) < 30:
            continue
        r = np.array([e["ratio"] for e in feed])
        t = np.array([e[TARGET] for e in feed])
        if not (0 < t.sum() < len(t)):
            continue
        one = auc(r[t > 0.5], r[t < 0.5])
        if math.isfinite(one):
            per_feed.append(one)
    same = sum(1 for x in per_feed if (x > 0.5) == (got > 0.5)) / len(per_feed) if per_feed else 0.0
    print(
        f"    {label:<10}{len(flat):>7,}{float(truth.mean()):>9.3f}"
        f"{float(truth[quiet].mean()) if quiet.sum() > 20 else float('nan'):>11.3f}"
        f"{float(truth[~quiet].mean()) if (~quiet).sum() > 20 else float('nan'):>11.3f}"
        f"{got:>9.4f}{same:>8.0%} of {len(per_feed)}"
    )
    if label == "real":
        for name, dial in (("travel", travel), ("patience", patience)):
            inner = [f"{bins}: {stratified(ratio, truth, dial, bins):.4f}" for bins in (3, STRATA)]
            print(f"      within {name:<9} strata  " + " | ".join(inner))
        for name, dial in (("travel", travel), ("patience", patience)):
            one = auc(dial[truth > 0.5], dial[truth < 0.5])
            print(f"      incumbent {name:<9} alone  AUC {one:.4f}")


def main() -> None:
    rng = np.random.default_rng(SEED)
    names = tuple(
        os.environ.get(
            "RETEST_PAIRS",
            "EURUSD,GBPUSD,USDJPY,XAUUSD,AUDUSD,USDCAD,EURJPY,GBPJPY,EURGBP,XAGUSD,USDCHF,NZDUSD",
        ).split(",")
    )
    print(
        f"frame {FRAME}, {LOOK}-bar structural extreme, break margin {MARGIN},\n"
        f"retest within {WAIT} bars, continuation over {AHEAD}, quiet at {QUIET:.0%}\n"
        "Decisions are spaced so no two share an outcome bar.\n"
    )
    print(f"    target: {TARGET}")
    print(
        f"    {'arm':<10}{'events':>7}{'base':>9}{'quiet':>11}{'loud':>11}"
        f"{'AUC':>9}  sign agreement"
    )
    real: list[list[dict]] = []
    mixed: list[list[dict]] = []
    for name in names:
        bars = load(name, FRAME)
        if bars is None:
            continue
        got = events(bars)
        if got:
            real.append(got)
        got = events(shuffle_blocks(bars, rng))
        if got:
            mixed.append(got)
    report("real", real)
    report("shuffled", mixed)
    print(
        "\n      `quiet` is the continuation rate where the retest bar carried at\n"
        f"      most {QUIET:.0%} of the break bar's volume, `loud` where it carried more.\n"
        "      The idea predicts quiet above loud. An AUC below 0.5 says the same\n"
        "      thing, since a lower ratio would then mean continuation."
    )


if __name__ == "__main__":
    main()
