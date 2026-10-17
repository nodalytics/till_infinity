"""`probability_up` and `probability_down` as separate estimators, not complements.

Asked on 2026-10-14: *we should do probability_up and probability_down
separately* - after *markets are not random and they have directions*, *it is
even more pronounced when the directions have tails, up or down tails*, and *at
any point the direction decision is either up or down*.

**Today they are the same number.** `reactions.py` returns
`1.0 - probability_up` for `probability_down`, and `levels.SideStats` keeps one
counter, `ups` over `touches`. One number cannot say "both" or "neither", so a
level that runs twenty sigma in each direction and a level that never moves are
written down identically at 0.5.

## Separate means estimated on different events

The two probabilities are only independent if their events are:

    p_up   = P(the path reaches +k sigma within the horizon)
    p_down = P(the path reaches -k sigma within the horizon)

These are **not** complementary. Both happen when the path runs up and then
down; neither happens when it sits still. So the pair carries two things at
once:

    p_up - p_down   is direction
    p_up + p_down   is volatility

which is the separation this desk has been unable to make with one counter -
and it is the up-or-down-tails framing exactly, because `k` is the tail.

## What that buys, and what it has to survive

A single `probability_up` of 0.5 is ambiguous between "no view" and "violent
both ways". The difference lets the desk abstain: direction is called only where
`|p_up - p_down|` is large, which is a **selective** prediction, and the AUC on
that subset is the number a book would actually trade. It is reported beside the
AUC over everything so the coverage it costs is visible.

Every arm carries matched placebo prices, a block-shuffled copy of the same
feed, and the range-break processes whose generator has a boundary. A posterior
built from a level's own prior touches is scored only on touches after them.
"""

from __future__ import annotations

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
    JITTER,
    LOOKBACK,
    SEED,
    TRADED,
    auc,
    load,
    shuffle_blocks,
)
from till_infinity.statespace.dispersion import differ  # noqa: E402

HORIZON = int(os.environ.get("HORIZON", "400"))
PER_FEED = int(os.environ.get("PER_FEED", "250"))
#: Bars after a touch in which a tail may be reached.
REACH = int(os.environ.get("REACH", "20"))
WARM = int(os.environ.get("WARM", "3"))
#: Bars enforced between consecutive touches of the same price, so that their
#: outcome windows cannot overlap. Set to `REACH` it makes them disjoint; set
#: to 1 it reproduces the leaking version, which is why it is a knob.
SEPARATE = int(os.environ.get("SEPARATE", str(REACH)))
#: Production's prior and weight, so these are production's estimator twice.
PRIOR = 0.5
WEIGHT = 4.0
#: The tail, in typical bars. `k` is what makes these two events separate
#: rather than complementary: at a large `k` a path can reach neither.
KS = tuple(float(k) for k in os.environ.get("KS", "1.0,2.0,3.0,4.0").split(","))
#: Coverage kept by the selective read, where the two posteriors disagree most.
#: Coverage kept by the selective reads, where the two posteriors disagree
#: most. Swept, because conviction and coverage trade off and the trade is the
#: result: at k=2 the top fifth read 0.6579 against 0.5938 over everything, so
#: the question is how far that goes and what it costs in events.
PICKS = tuple(float(k) for k in os.environ.get("PICKS", "1.0,0.2,0.1,0.05").split(","))


def posterior(hits: float, touches: float) -> float:
    alpha = PRIOR * WEIGHT + hits
    beta = (1.0 - PRIOR) * WEIGHT + (touches - hits)
    return alpha / (alpha + beta)


def touches_at(bars, price: float, start: int, move: float, k: float) -> list[tuple[int, int, int]]:
    """Per touch: did the path reach the up tail, the down tail, and which first.

    `first` is 1 for up, 0 for down, -1 when neither tail was reached - which is
    the case one counter cannot represent and is why these are two estimators.
    """
    highs, lows, closes = bars["high"], bars["low"], bars["close"]
    out: list[tuple[int, int, int]] = []
    end = min(start + HORIZON, len(closes) - REACH - 1)
    i = max(start, 1)
    reach = k * move
    while i < end:
        if not (lows[i] <= price <= highs[i]):
            i += 1
            continue
        here = float(closes[i])
        ahead = slice(i + 1, i + 1 + REACH)
        up_at = np.flatnonzero(highs[ahead] >= here + reach)
        down_at = np.flatnonzero(lows[ahead] <= here - reach)
        up, down = int(len(up_at) > 0), int(len(down_at) > 0)
        if up and down:
            first = int(up_at[0] < down_at[0])
        elif up:
            first = 1
        elif down:
            first = 0
        else:
            first = -1
        out.append((up, down, first))
        j = i + 1
        while j < end and (lows[j] <= price <= highs[j] or abs(closes[j] - price) < 0.5 * move):
            j += 1
        # **Disjoint outcome windows, which the first version did not have.**
        # The skip rule above only asks price to move half a typical bar away,
        # which can take five bars - while the outcome runs `REACH` bars. So
        # touch i's outcome was most of touch i+1's outcome, the posterior that
        # had seen the first was reading the second, and the AUC climbed to
        # 0.79 at three sigma. It climbed just as high on block-shuffled bars
        # and on matched placebo prices, which is what an overlap artefact does
        # and what a level-specific signal cannot do.
        i = max(j, i + SEPARATE)
    return out


def collect(bars, rng, k: float) -> list[dict]:
    closes, highs, lows = bars["close"], bars["high"], bars["low"]
    last = len(closes) - HORIZON - REACH - 2
    span = last - LOOKBACK
    if span <= 0:
        return []
    step = max(HORIZON, span // max(PER_FEED, 1))
    out: list[dict] = []
    for n, at in enumerate(range(LOOKBACK, last, step)):
        window = slice(at - LOOKBACK, at)
        move = float(np.median(highs[window] - lows[window]))
        if not (move > 0):
            continue
        level = float(highs[window].max() if n % 2 == 0 else lows[window].min())
        here = float(closes[at])
        gap = level - here
        if abs(gap) < 0.25 * move:
            continue
        placebo = here + gap * (1.0 + float(rng.uniform(-JITTER, JITTER)))
        real = touches_at(bars, level, at, move, k)
        fake = touches_at(bars, placebo, at, move, k)
        if len(real) >= WARM + 1 and len(fake) >= WARM + 1:
            out.append({"real": real, "fake": fake})
    return out


def walk_forward(records, key: str) -> dict[str, np.ndarray]:
    """Posteriors from prior touches only, and what actually happened."""
    rows: dict[str, list[float]] = {
        "p_up": [],
        "p_down": [],
        "up": [],
        "down": [],
        "first": [],
    }
    for r in records:
        ups = downs = 0.0
        for i, (up, down, first) in enumerate(r[key]):
            if i >= WARM:
                rows["p_up"].append(posterior(ups, float(i)))
                rows["p_down"].append(posterior(downs, float(i)))
                rows["up"].append(float(up))
                rows["down"].append(float(down))
                rows["first"].append(float(first))
            ups += up
            downs += down
    return {k: np.asarray(v) for k, v in rows.items()}


def read(got: dict[str, np.ndarray], label: str) -> None:
    if len(got["up"]) < 50:
        print(f"    {label:<10} {len(got['up'])} touches, too few")
        return
    lines = []
    for name, guess, truth in (
        ("up", got["p_up"], got["up"]),
        ("down", got["p_down"], got["down"]),
    ):
        if 0 < truth.sum() < len(truth):
            lines.append(f"{name} {auc(guess[truth > 0.5], guess[truth < 0.5]):.4f}")
        else:
            lines.append(f"{name} -")
    # Direction: the difference, scored on which tail came first, and only
    # where one did - the abstention `-1` is dropped rather than counted.
    decided = got["first"] >= 0
    lean = got["p_up"][decided] - got["p_down"][decided]
    truth = got["first"][decided]
    if len(truth) > 50 and 0 < truth.sum() < len(truth):
        for pick in PICKS:
            # Selective prediction: keep only the touches where the two
            # posteriors disagree most, which is what a book trades. The
            # permutation null is drawn **inside the kept subset**, so a high
            # AUC on few events cannot borrow its significance from the rest.
            edge = float(np.quantile(np.abs(lean), 1.0 - pick)) if pick < 1.0 else -1.0
            keep = np.abs(lean) >= edge
            if keep.sum() < 40 or not (0 < truth[keep].sum() < keep.sum()):
                lines.append(f"top {pick:.0%} -")
                continue
            here = auc(lean[keep & (truth > 0.5)], lean[keep & (truth < 0.5)])
            inner_lean, inner_truth = lean[keep], truth[keep]
            local = np.random.default_rng(SEED + 9)
            wider = sum(
                1
                for _ in range(DRAWS)
                if abs(
                    auc(
                        inner_lean[(d := local.permutation(inner_truth)) > 0.5],
                        inner_lean[d < 0.5],
                    )
                    - 0.5
                )
                >= abs(here - 0.5)
            )
            tag = "all" if pick >= 1.0 else f"top {pick:.0%}"
            lines.append(f"{tag} {here:.4f} p {(wider + 1) / (DRAWS + 1):.3f} n {int(keep.sum())}")
    print(f"    {label:<10} n {len(got['up']):>5}  " + "  ".join(lines[:2]))
    for line in lines[2:]:
        print(f"                  {line}")


def arm(group: str, names: tuple[str, ...], rng) -> None:
    print("=" * 84)
    print(group)
    print("=" * 84)
    for k in KS:
        records: list[dict] = []
        mixed: list[dict] = []
        for name in names:
            bars = load(name)
            if bars is None:
                continue
            records += collect(bars, rng, k)
            mixed += collect(shuffle_blocks(bars, rng), rng, k)
        if len(records) < 30:
            print(f"  k={k}: {len(records)} levels, too few\n")
            continue
        real = walk_forward(records, "real")
        both = (real["up"] > 0.5) & (real["down"] > 0.5)
        neither = (real["up"] < 0.5) & (real["down"] < 0.5)
        print(
            f"  k={k:g} sigma, {len(records)} levels: "
            f"up {real['up'].mean():.3f}, down {real['down'].mean():.3f}, "
            f"both {both.mean():.3f}, neither {neither.mean():.3f}"
        )
        print(
            "    `both` and `neither` are the states one counter cannot hold; "
            f"they are {both.mean() + neither.mean():.1%} of touches here."
        )
        # Does the per-level rate differ, for each side on its own?
        for name, which in (("up", 0), ("down", 1)):
            counts = [
                (float(len(r["real"])), float(sum(t[which] for t in r["real"])))
                for r in records
                if len(r["real"]) >= WARM + 1
            ]
            pooled = sum(h for _, h in counts) / max(sum(n for n, _ in counts), 1.0)
            tau, null, p = differ(counts, pooled)
            fakes = [
                (float(len(r["fake"])), float(sum(t[which] for t in r["fake"])))
                for r in records
                if len(r["fake"]) >= WARM + 1
            ]
            pooled_f = sum(h for _, h in fakes) / max(sum(n for n, _ in fakes), 1.0)
            tau_f, _, p_f = differ(fakes, pooled_f)
            print(
                f"    levels differ on {name:<5}: tau {tau:.4f} vs null {null:.4f}, "
                f"p {p:.3f}   (placebo tau {tau_f:.4f}, p {p_f:.3f})"
            )
        read(real, "real")
        read(walk_forward(records, "fake"), "placebo")
        read(walk_forward(mixed, "real"), "shuffled")
        print()


def main() -> None:
    rng = np.random.default_rng(SEED)
    print(
        f"{LOOKBACK}-bar extremes, {HORIZON} watched, tail reached within {REACH} bars,\n"
        f"posterior prior {PRIOR} weight {WEIGHT} after {WARM} touches, "
        f"{DRAWS} permutations\n"
    )
    for group, names in (("traded", TRADED), ("control", CONTROL), ("generated", GENERATED)):
        arm(group, names, rng)


if __name__ == "__main__":
    main()
