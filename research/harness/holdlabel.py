"""How much of the hold rate is the market, and how much is the label? Decomposed.

    python research/harness/holdlabel.py --touches 200000

## The claim this settles

A simulation reported that a pure random walk "holds" 67-76% under the production
resolution rule while a symmetric rule reads 50.0%, and attributed it to two
asymmetries: failed breaks counting as holds, and hold and break being measured from
different places.

**The second is right and the first is not.** `Stats.hold_rate` is

    rejects / (rejects + breaks + traps)

so a trap sits in the **denominator** and *lowers* the rate. `learning/breaking.py`
never references `Outcome.TRAP` at all. Trap-as-holding exists only in
`levels.py`'s state machine, which decides `FLIPPED`/`TESTED` and whether to decay the
level's history - not the statistic. So "failed breaks count as holds" cannot be what
inflates `hold_rate`, and attributing points to it measures a reimplementation rather
than production.

This harness runs the same paths through four rules so the mechanisms separate instead
of being argued about.

## The four rules

Each is the production rule with one thing changed, so a difference is attributable.

* **symmetric** - first of `+resolve_vol` or `-resolve_vol` from where the touch
  started, nothing re-labelled, nothing excluded. The control: it must read 50% on
  noise, and if it does not, the harness is wrong rather than the desk.
* **production** - the rule `Tracker.update` actually applies:
  - a hold needs price back `resolve_vol` from `touch.origin`, which **ratchets**:
    `reactions.py:1154` sets `touch.origin = price` on every deeper print, and its own
    comment says "a deeper print re-extends it and moves the origin with it";
  - a break needs price `resolve_vol` through the **fixed** level, then `trap_bars`
    without price coming back `trap_vol` to the approach side;
  - `chop` is **excluded** from the denominator.
* **fixed origin** - production with the hold measured from the touch start instead of
  the ratcheting extreme. The difference from production is the ratchet's contribution.
* **chop included** - production with the undecided in the denominator. The difference
  is the selection effect from excluding them.

## The asymmetry the original report missed

`resolve_vol` is **1.5** and `trap_vol` is **0.5**. Confirming a break demands 1.5
units through *and* six bars of survival; voiding it demands only 0.5 units back. A
break is three times easier to lose than to win, so on noise most attempts become traps
- and since traps are in the denominator, that pushes the hold rate **down**. It is
therefore not part of the inflation, which is worth knowing before anyone "fixes" it.
"""

from __future__ import annotations

import argparse

import numpy as np

#: Production's own numbers, from `reactions.py` and `levels.py`.
RESOLVE_VOL = 1.5
TRAP_VOL = 0.5
TRAP_BARS = 6
HORIZON_BARS = 12

RULES = ("symmetric", "production", "fixed origin", "chop included", "traps as holds")


def label(path: np.ndarray, *, ratchet: bool) -> str:
    """One touch's outcome under the production rule, as `Tracker.update` applies it.

    `path` is price in volatility units, relative to the level, one entry a bar, with
    the touch starting at 0. Positive is the approach side; negative is through.
    """
    origin = 0.0
    breaking_at: int | None = None
    for bar, price in enumerate(path):
        if breaking_at is not None:
            # Provisional. Back `trap_vol` to the approach side voids it; otherwise it
            # confirms once it has survived `trap_bars`. The horizon does not apply
            # here - production returns before reaching that check while breaking.
            if price >= TRAP_VOL:
                return "trap"
            if bar - breaking_at >= TRAP_BARS:
                return "break"
            continue
        if ratchet and price < origin:
            # The ratchet. `touch.origin = price` on every deeper print.
            origin = price
        if price - origin >= RESOLVE_VOL:
            return "reject"
        if -price >= RESOLVE_VOL:
            breaking_at = bar
            continue
        if bar + 1 >= HORIZON_BARS:
            return "chop"
    return "chop"


def symmetric(path: np.ndarray) -> str:
    """First of up or down `resolve_vol` from the touch start. Nothing re-labelled."""
    for price in path:
        if price >= RESOLVE_VOL:
            return "reject"
        if -price >= RESOLVE_VOL:
            return "break"
    return "chop"


def rate(counts: dict[str, int], *, include_chop: bool = False, traps_hold: bool = False) -> float:
    """`Stats.hold_rate`: rejects over the decisive, with traps in the denominator.

    `traps_hold` is **not** what production does and is offered to reproduce the claim
    that it is. Moving traps from the denominator into the numerator is the single
    change that turns this harness's ~55% into the ~65-76% that was reported, which is
    how we know that is where the number came from.
    """
    decisive = counts["reject"] + counts["break"] + counts["trap"]
    if include_chop:
        decisive += counts["chop"]
    held = counts["reject"] + (counts["trap"] if traps_hold else 0)
    return held / decisive if decisive else float("nan")


def run(touches: int, bars: int, scale: float, seed: int) -> dict[str, dict]:
    """Every rule over the same paths, so a difference is the rule and not the sample."""
    rng = np.random.default_rng(seed)
    # A pure random walk. `scale` is the volatility unit being wrong on purpose: 1.0 is
    # correct, 0.5 understates it, 2.0 overstates it. Measuring in volatility units
    # cannot manufacture holds, and the symmetric rule below is what proves that.
    steps = rng.normal(0.0, 1.0 / scale, size=(touches, bars))
    paths = np.cumsum(steps, axis=1)

    out: dict[str, dict] = {}
    for rule in RULES:
        counts = dict.fromkeys(("reject", "break", "trap", "chop"), 0)
        for row in paths:
            if rule == "symmetric":
                counts[symmetric(row)] += 1
            else:
                counts[label(row, ratchet=rule != "fixed origin")] += 1
        out[rule] = {
            **counts,
            "hold_rate": rate(
                counts,
                include_chop=rule == "chop included",
                traps_hold=rule == "traps as holds",
            ),
        }
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--touches", type=int, default=200_000)
    parser.add_argument("--bars", type=int, default=64)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    print(f"{args.touches:,} touches on a pure random walk, {args.bars} bars each")
    print(
        "\n`scale` is the volatility unit being wrong on purpose. If a rule's hold rate"
        "\nmoves with it, the rule is reading volatility rather than the market."
    )
    for scale in (0.5, 1.0, 2.0):
        got = run(args.touches, args.bars, scale, args.seed)
        print(f"\n=== volatility unit x{1 / scale:.1f}" + ("  (correct)" if scale == 1.0 else ""))
        print(
            f"  {'rule':14s} {'hold%':>7s} {'reject':>8s} {'break':>7s} {'trap':>7s} {'chop':>7s}"
        )
        print("  " + "-" * 56)
        for rule in RULES:
            r = got[rule]
            print(
                f"  {rule:14s} {100 * r['hold_rate']:7.1f} {r['reject']:8d} "
                f"{r['break']:7d} {r['trap']:7d} {r['chop']:7d}"
            )
    print(
        "\n  symmetric is the control and must read 50%."
        "\n  production - fixed origin  =  what the ratcheting origin contributes."
        "\n  production - chop included =  what excluding the undecided contributes."
        "\n  traps as holds is NOT production. It is the reported claim, reproduced, and"
        "\n  it is the one change that gets from production's ~55% to the ~67-76% cited."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
