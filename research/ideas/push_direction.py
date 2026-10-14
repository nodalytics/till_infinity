"""Which way the push went - the per-level statistic that was never tested.

Asked on 2026-10-14: *markets are not random and they have directions*, *we
have started it and it is very good, you can see the results now*, *it is even
more pronounced when the directions have tails, up or down tails*, *at any point
the direction decision is either up or down*.

**The thing I conflated.** `statespace-conditional-holds.md` closed the per-level
**hold** rate: `tau` over 279 levels came back at 0.0109 against a null of
0.0085, so whether a level holds is not a property of the level. Production's
`probability_up` is a different statistic on the same object - a Beta-binomial
posterior over `ups / touches`, **which way the push went**, prior 0.5 and
weight 4, with kNN supplying the prior where a level's own history cannot
(`levels.SideStats.probability_up`). Its AUC is measured at 0.6365 in
production, roughly twice over-confident.

Hold and direction are not the same question. A level can turn price back half
the time, unpredictably, while the pushes it does produce lean one way. Nothing
in this repository has asked whether `ups` disperses across levels, and the
`tau` that closed the hold rate says nothing about it.

## What is tested, in the order the claims were made

1. **Does the per-level up rate differ at all?** `dispersion.differ` against a
   simulated null, and the same question asked of distance-matched placebo
   prices on the same feed. That is the gate `sym_hold_rate` failed.
2. **Does the posterior predict the next push?** Built from a level's prior
   touches only, scored on the next one, pooled, against the base rate.
3. **Is it stronger in the tails?** The same AUC restricted to touches whose
   push reached one, two or three sigma - "up or down tails" - which is the
   claim that the signal concentrates where the move is large.

Every arm carries a block-shuffled copy of the same feed, where bar geometry
and volatility clustering survive and level structure does not, and the
range-break processes whose generator has a boundary by construction.
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
from till_infinity.structures.statespace.dispersion import differ  # noqa: E402

HORIZON = int(os.environ.get("HORIZON", "400"))
PER_FEED = int(os.environ.get("PER_FEED", "250"))
#: Bars after a touch over which the push is measured.
PUSH = int(os.environ.get("PUSH", "10"))
#: Touches a level needs before its posterior is allowed to speak.
WARM = int(os.environ.get("WARM", "3"))
#: Production's prior and weight, so this is the same estimator.
PRIOR = 0.5
WEIGHT = 4.0
TAILS = (0.0, 1.0, 2.0, 3.0)


def posterior(ups: float, touches: float) -> float:
    """`levels.SideStats.probability_up`, exactly."""
    alpha = PRIOR * WEIGHT + ups
    beta = (1.0 - PRIOR) * WEIGHT + (touches - ups)
    return alpha / (alpha + beta)


def pushes(bars, price: float, start: int, move: float) -> list[tuple[float, float]]:
    """Every touch of `price`, as `(up, size in sigma)`.

    `up` is the sign of the move over the `PUSH` bars after the touch - the
    binary decision the question is about - and `size` is how far it went, which
    is what the tail conditioning selects on.
    """
    highs, lows, closes = bars["high"], bars["low"], bars["close"]
    out: list[tuple[float, float]] = []
    end = min(start + HORIZON, len(closes) - PUSH - 1)
    i = max(start, 1)
    while i < end:
        if not (lows[i] <= price <= highs[i]):
            i += 1
            continue
        after = float(closes[i + PUSH] - closes[i])
        out.append((float(after > 0), abs(after) / move if move > 0 else 0.0))
        j = i + 1
        while j < end and (lows[j] <= price <= highs[j] or abs(closes[j] - price) < 0.5 * move):
            j += 1
        # **Disjoint push windows.** The skip above only asks price to move half
        # a typical bar away, which can take three bars, while the push runs
        # `PUSH` bars - so touch i's push was most of touch i+1's push and the
        # posterior was reading its own answer. With this line the AUC falls
        # from 0.5682 to chance; see `two_sided.py`, where the same defect
        # reached 0.79 and collapsed to 0.51.
        i = max(j, i + PUSH)
    return out


def collect(bars, rng, feed: str) -> list[dict]:
    """One record per level: its touch sequence, and a matched placebo's."""
    closes, highs, lows = bars["close"], bars["high"], bars["low"]
    last = len(closes) - HORIZON - PUSH - 2
    span = last - LOOKBACK
    if span <= 0:
        return []
    step = max(HORIZON, span // max(PER_FEED, 1))
    out: list[dict] = []
    for k, at in enumerate(range(LOOKBACK, last, step)):
        window = slice(at - LOOKBACK, at)
        move = float(np.median(highs[window] - lows[window]))
        if not (move > 0):
            continue
        level = float(highs[window].max() if k % 2 == 0 else lows[window].min())
        here = float(closes[at])
        gap = level - here
        if abs(gap) < 0.25 * move:
            continue
        placebo = here + gap * (1.0 + float(rng.uniform(-JITTER, JITTER)))
        real = pushes(bars, level, at, move)
        fake = pushes(bars, placebo, at, move)
        if len(real) >= WARM + 1 and len(fake) >= WARM + 1:
            out.append({"feed": feed, "real": real, "fake": fake})
    return out


def rate_counts(records, key: str) -> list[tuple[float, float]]:
    return [
        (float(len(r[key])), float(sum(u for u, _ in r[key])))
        for r in records
        if len(r[key]) >= WARM + 1
    ]


def score(records, key: str, least: float) -> tuple[list[float], list[float]]:
    """The posterior from prior touches only, and the truth, for tail >= `least`."""
    guesses: list[float] = []
    truths: list[float] = []
    for r in records:
        seen = r[key]
        ups = 0.0
        for i, (up, size) in enumerate(seen):
            if i >= WARM and size >= least:
                guesses.append(posterior(ups, float(i)))
                truths.append(up)
            ups += up
    return guesses, truths


def arm(group: str, names: tuple[str, ...], rng) -> None:
    records: list[dict] = []
    mixed: list[dict] = []
    for name in names:
        bars = load(name)
        if bars is None:
            continue
        records += collect(bars, rng, name)
        mixed += collect(shuffle_blocks(bars, rng), rng, name)
    if len(records) < 30:
        print(f"  {group}: {len(records)} levels, too few\n")
        return
    print(f"  {group}: {len(records)} levels, {len(mixed)} shuffled")

    # 1. Does the per-level up rate differ at all?
    real_counts = rate_counts(records, "real")
    fake_counts = rate_counts(records, "fake")
    pooled = sum(h for _, h in real_counts) / sum(n for n, _ in real_counts)
    pooled_fake = sum(h for _, h in fake_counts) / max(sum(n for n, _ in fake_counts), 1.0)
    tau, null, p = differ(real_counts, pooled)
    tau_f, null_f, p_f = differ(fake_counts, pooled_fake)
    print(f"    pooled up rate        : {pooled:.4f}  (placebo {pooled_fake:.4f})")
    print(f"    do levels differ      : tau {tau:.4f} vs null {null:.4f}, p {p:.3f}")
    print(f"    do placebos differ    : tau {tau_f:.4f} vs null {null_f:.4f}, p {p_f:.3f}")
    print(
        "      This is the gate `sym_hold_rate` failed, asked of `ups` instead.\n"
        "      The placebo line decides the first: dispersion means something\n"
        "      only if matched prices on the same feed do not show it too."
    )

    # 2 and 3. Does the posterior predict, and is it stronger in the tails?
    print(f"    {'tail':>6}{'n':>8}{'base':>8}{'AUC':>9}{'p':>8}{'placebo':>9}{'shuffled':>10}")
    for least in TAILS:
        guesses, truths = score(records, "real", least)
        if len(truths) < 50 or not (0 < sum(truths) < len(truths)):
            print(f"    {least:>6.0f}{len(truths):>8}  too few")
            continue
        truth = np.asarray(truths)
        guess = np.asarray(guesses)
        got = auc(guess[truth > 0.5], guess[truth < 0.5])
        # Permute the truth, which is the null for "the posterior orders them".
        local = np.random.default_rng(SEED + 5)
        wider = sum(
            1
            for _ in range(DRAWS)
            if abs(auc(guess[(drawn := local.permutation(truth)) > 0.5], guess[drawn < 0.5]) - 0.5)
            >= abs(got - 0.5)
        )
        placebo_guess, placebo_truth = score(records, "fake", least)
        shuffled_guess, shuffled_truth = score(mixed, "real", least)
        here = (
            auc(
                np.asarray(placebo_guess)[np.asarray(placebo_truth) > 0.5],
                np.asarray(placebo_guess)[np.asarray(placebo_truth) < 0.5],
            )
            if len(placebo_truth) > 50 and 0 < sum(placebo_truth) < len(placebo_truth)
            else float("nan")
        )
        there = (
            auc(
                np.asarray(shuffled_guess)[np.asarray(shuffled_truth) > 0.5],
                np.asarray(shuffled_guess)[np.asarray(shuffled_truth) < 0.5],
            )
            if len(shuffled_truth) > 50 and 0 < sum(shuffled_truth) < len(shuffled_truth)
            else float("nan")
        )
        print(
            f"    {least:>6.0f}{len(truth):>8}{float(truth.mean()):>8.3f}{got:>9.4f}"
            f"{(wider + 1) / (DRAWS + 1):>8.3f}{here:>9.4f}{there:>10.4f}"
        )
    print(
        "      `tail` is the smallest push kept, in typical bars, so the last\n"
        "      rows are the up-or-down tails. A rising AUC down the column is\n"
        "      the claim; the placebo and shuffled columns have to stay at 0.5.\n"
    )


def main() -> None:
    rng = np.random.default_rng(SEED)
    print(
        f"{LOOKBACK}-bar extremes, {HORIZON} bars watched, push over {PUSH} bars,\n"
        f"posterior prior {PRIOR} weight {WEIGHT} - production's own - after "
        f"{WARM} touches\n{DRAWS} permutations\n"
    )
    for group, names in (("traded", TRADED), ("control", CONTROL), ("generated", GENERATED)):
        print("=" * 80)
        print(group)
        print("=" * 80)
        arm(group, names, rng)


if __name__ == "__main__":
    main()
