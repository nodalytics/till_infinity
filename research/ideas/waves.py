"""Elliott's leg ratios and Wyckoff's effort-versus-result, as falsifiable pieces.

Asked on 2026-10-14 alongside the pivot formulas: *wycoff, elliot waves*.

Neither is arithmetic on a prior session, so neither can be reviewed the way
`pivot-families.md` reviews pivots. Both are **models**, and each has one claim
that can be tested without adopting the apparatus around it.

## Elliott, without a wave counter

Elliott's problem is identifiability rather than plausibility: the rule set has
enough freedom to label almost any path, so "does the count work" is not a
question with an answer. One component is falsifiable on its own, though -
**the Fibonacci relationships between consecutive legs**. If a corrective leg
really retraces 0.618 of its impulse, and an extension really runs 1.618, then
the distribution of consecutive leg ratios should be **denser at those values
than chance allows**.

That needs no labelling. Segment price into alternating legs with a zigzag at a
volatility-scaled threshold, take consecutive ratios, and compare the density
near 0.618 and 1.618 against the same series block-shuffled - which keeps bar
geometry and volatility clustering and destroys the ordering that a wave would
live in.

The threshold is swept, because a zigzag's output is a function of it and a
ratio clustering that only appears at one threshold is the threshold.

## Wyckoff, as effort against result

Wyckoff's mechanic is that **effort** (volume) and **result** (price travelled)
normally agree, and that a divergence - heavy volume, little progress - marks
absorption and precedes a turn. That is a two-channel observation model, which
is what `hmm.py` and `switching.py` are for, and it is directly testable as a
conditional direction claim: at the end of a leg, does the effort-to-result
ratio predict whether the **next** leg continues or reverses?

Direction has been closed here six ways, so the prior is poor - but this is a
specific conditional that none of those tests asked, and it costs one harness.

Both arms carry the block-shuffled control, a per-feed split because a pooled
answer here has agreed with a claim every subgroup refuted, and legs are
non-overlapping by construction - a zigzag cannot emit two legs over one bar.
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
    shuffle_blocks,
)
from screen import load  # noqa: E402

#: Zigzag thresholds, in typical bars. Swept because the segmentation is a
#: function of this and a result at one value only is this value.
THRESHOLDS = tuple(float(k) for k in os.environ.get("THRESHOLDS", "1.0,2.0,4.0").split(","))
#: The ratios Elliott names, and the window counted as "near" one.
TARGETS = (0.382, 0.500, 0.618, 1.000, 1.618, 2.618)
NEAR = float(os.environ.get("NEAR", "0.05"))


def legs(bars, threshold: float) -> list[dict]:
    """Alternating swings, each with its size, duration, volume and effort.

    A leg ends when price retraces `threshold` typical bars from its extreme,
    which is the zigzag rule. Legs cannot overlap, so consecutive legs never
    share a bar - the defect that invalidated the per-level direction work
    cannot arise here.
    """
    closes, highs, lows = bars["close"], bars["high"], bars["low"]
    volume = bars["volume"]
    if len(closes) < 4 * LOOKBACK:
        return []
    span = np.median(highs[:LOOKBACK] - lows[:LOOKBACK])
    if not (span > 0):
        return []
    out: list[dict] = []
    start = LOOKBACK
    # **Direction is never zero.** A first version initialised it to zero so
    # that both tracking branches were live, which set `extreme` to `price` on
    # every bar they differed - so `extreme == price` always and no turn
    # condition could fire. It segmented nothing on 40,000 bars at every
    # threshold, which is the useful kind of failure: silent zero rather than
    # a plausible number.
    direction = 1
    extreme = float(closes[start])
    extreme_at = start
    leg_from = start
    for i in range(start + 1, len(closes)):
        # Re-scale the threshold to recent range so one setting means the same
        # thing in a quiet stretch and a violent one.
        if i % LOOKBACK == 0:
            window = slice(max(i - LOOKBACK, 0), i)
            got = float(np.median(highs[window] - lows[window]))
            if got > 0:
                span = got
        reach = threshold * span
        price = float(closes[i])
        if direction > 0:
            if price > extreme:
                extreme, extreme_at = price, i
                continue
            if price > extreme - reach:
                continue
        else:
            if price < extreme:
                extreme, extreme_at = price, i
                continue
            if price < extreme + reach:
                continue
        # A leg ended at `extreme_at`, running from `leg_from`.
        size = abs(extreme - float(closes[leg_from]))
        bars_in = max(extreme_at - leg_from, 1)
        travelled = float(np.abs(np.diff(np.log(closes[leg_from : extreme_at + 1]))).sum())
        out.append(
            {
                "up": 1.0 if direction > 0 else 0.0,
                "size": size / span,
                "bars": float(bars_in),
                "to_at": extreme_at,
                # Effort against result: volume per unit of distance covered.
                "effort": float(volume[leg_from : extreme_at + 1].sum()) / max(travelled, 1e-12),
                "travelled": travelled,
            }
        )
        leg_from = extreme_at
        direction = -direction
        extreme, extreme_at = price, i
    return out


def ratio_density(found: list[dict]) -> dict[float, float]:
    """Share of consecutive leg ratios landing near each named value."""
    ratios = [
        found[i + 1]["size"] / found[i]["size"]
        for i in range(len(found) - 1)
        if found[i]["size"] > 0
    ]
    if len(ratios) < 30:
        return {}
    out = {}
    for target in TARGETS:
        lo, hi = target * (1 - NEAR), target * (1 + NEAR)
        out[target] = sum(1 for r in ratios if lo <= r <= hi) / len(ratios)
    out[-1.0] = float(len(ratios))
    return out


def effort_call(found: list[dict]) -> tuple[list[float], list[float]]:
    """Does effort-to-result at a leg's end say the next leg reverses?

    Every leg alternates by construction, so "reverses" cannot be the target -
    the question is whether the **next leg is larger or smaller** than this
    one, which is what a Wyckoff absorption claim implies: heavy effort with
    little result should be followed by a bigger move the other way.
    """
    scores: list[float] = []
    truths: list[float] = []
    for i in range(len(found) - 1):
        here, nxt = found[i], found[i + 1]
        if here["size"] <= 0 or here["effort"] <= 0:
            continue
        scores.append(math.log(here["effort"]))
        truths.append(1.0 if nxt["size"] > here["size"] else 0.0)
    return scores, truths


def arm(group: str, names: tuple[str, ...], rng) -> None:
    print("=" * 84)
    print(group)
    print("=" * 84)
    for threshold in THRESHOLDS:
        real: list[list[dict]] = []
        mixed: list[list[dict]] = []
        for name in names:
            bars = load(name)
            if bars is None:
                continue
            got = legs(bars, threshold)
            if len(got) >= 40:
                real.append(got)
            got = legs(shuffle_blocks(bars, rng), threshold)
            if len(got) >= 40:
                mixed.append(got)
        if not real:
            print(f"  threshold {threshold}: nothing segmented\n")
            continue
        print(
            f"  threshold {threshold:g} typical bars: {len(real)} feeds, "
            f"{sum(len(f) for f in real):,} legs"
        )
        print(f"    {'ratio':>7}{'real':>9}{'shuffled':>10}{'lift':>8}   per-feed agreement")
        for target in TARGETS:
            here = [d[target] for f in real if (d := ratio_density(f))]
            there = [d[target] for f in mixed if (d := ratio_density(f))]
            if not here or not there:
                continue
            a, b = float(np.mean(here)), float(np.mean(there))
            agree = sum(1 for x in here if x > b) / len(here)
            print(
                f"    {target:>7.3f}{a:>9.4f}{b:>10.4f}{a - b:>+8.4f}   {agree:>5.0%} of {len(here)}"
            )
        print(
            "      A Fibonacci ratio has to be denser than the same bars shuffled.\n"
            f"      Near means within {NEAR:.0%} of the value."
        )
        # Wyckoff.
        for label, pool in (("real", real), ("shuffled", mixed)):
            per_feed = []
            for found in pool:
                scores, truths = effort_call(found)
                if len(truths) < 30 or not (0 < sum(truths) < len(truths)):
                    continue
                s = np.asarray(scores)
                t = np.asarray(truths)
                one = auc(s[t > 0.5], s[t < 0.5])
                if math.isfinite(one):
                    per_feed.append(one)
            if per_feed:
                mean = float(np.mean(per_feed))
                same = sum(1 for x in per_feed if (x > 0.5) == (mean > 0.5)) / len(per_feed)
                print(
                    f"    effort -> next leg bigger, {label:<9} AUC {mean:.4f}  "
                    f"sign {same:.0%} of {len(per_feed)}"
                )
        print()


def main() -> None:
    rng = np.random.default_rng(SEED)
    print(
        f"zigzag legs, thresholds {THRESHOLDS} typical bars, "
        f"ratios within {NEAR:.0%}\n{DRAWS} draws reserved for the nulls\n"
    )
    for group, names in (("traded", TRADED), ("control", CONTROL), ("generated", GENERATED)):
        arm(group, names, rng)


if __name__ == "__main__":
    main()
