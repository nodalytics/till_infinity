"""Where the fair-odds line should break: jump processes, not diffusions.

Run from the repository root:  python research/harness/jump_odds.py

Every barrier result in this repository lands on `a / (a + b)` - the driftless
first-passage probability from `barrier_pde.py`. Patterns land on it, gap edges land on
it, and the premium/discount rule lands on it to within half a point across ten deciles
and 314,794 rows.

**That formula assumes continuous paths.** It is derived from a diffusion, where price
cannot reach a distant level without passing through every level in between. Two of this
broker's instruments are built to violate that.

## The prediction, recorded before the run

Boom indices are constructed with sudden upward spikes against a slow grind down; Crash
indices are the mirror. A single spike can clear a distant upside barrier without
touching a near downside one, which is precisely the event a diffusion says must be rare.

So:

* on **Boom**, a far upside target against a near stop should beat `a / (a + b)`, and
  the excess should *grow* with the reward-to-risk ratio;
* on **Crash**, the same geometry should be *worse* than fair odds by a similar amount,
  and a far **downside** target should beat it;
* on **FX and metals**, which are diffusion-like, the excess should stay near zero at
  every ratio - as it already does in four other harnesses.

This is the one place in this repository where the fair-odds line is expected to fail,
and it fails for a stated structural reason rather than because a pattern was found. If
the excess is flat on Boom too, then the jump structure is not reachable at hourly
resolution and the fair-odds result is more general than diffusion theory requires.

## What is measured

The stop is fixed at one true range and the target swept from a quarter of that to eight
times it, so the reward-to-risk ratio runs from 0.25 to 8 and the fair-odds rate from
80% down to 11%. Both directions are measured separately, because the whole point is the
asymmetry: `long` puts the far barrier above, `short` puts it below.

A bar touching both barriers counts as a stop, as everywhere else, which biases every
excess slightly negative - so the comparison across instruments and across directions,
which share that bias, is what carries the result.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "training"))

import candles  # noqa: E402

#: Stop distance, in true ranges. Held fixed so the ratio is the only thing varying.
RISK = 1.0

#: Target distances, in true ranges. The reward-to-risk ratio is this over `RISK`.
REWARDS = (0.25, 0.5, 1.0, 2.0, 4.0, 8.0)

#: Bars allowed to resolve. Long enough that an eight-to-one target is reachable.
HORIZON = 192


def resolve(bars: np.ndarray, tr: np.ndarray, at: int, side: int, reward: float, horizon: int):
    """1 if the target came first, -1 if the stop did, 0 if neither in `horizon`."""
    close, high, low = bars[:, 4], bars[:, 2], bars[:, 3]
    here = close[at]
    if here <= 0:
        return 0
    unit = tr[at] * here
    if unit <= 0:
        return 0
    if side > 0:
        target, stop = here + reward * unit, here - RISK * unit
    else:
        target, stop = here - reward * unit, here + RISK * unit
    for step in range(1, horizon + 1):
        i = at + step
        if i >= len(close):
            return 0
        if side > 0:
            hit_t, hit_s = high[i] >= target, low[i] <= stop
        else:
            hit_t, hit_s = low[i] <= target, high[i] >= stop
        if hit_t and hit_s:
            return -1  # adverse first, by convention
        if hit_t:
            return 1
        if hit_s:
            return -1
    return 0


def measure(bars: np.ndarray, tr: np.ndarray, horizon: int, every: int) -> dict:
    """Hit rate per (direction, reward), against the fair-odds rate for that geometry."""
    out: dict[tuple[int, float], tuple[int, int]] = {}
    for side in (1, -1):
        for reward in REWARDS:
            hits = total = 0
            for at in range(0, len(bars) - horizon, every):
                got = resolve(bars, tr, at, side, reward, horizon)
                if got == 0:
                    continue
                total += 1
                hits += got > 0
            out[(side, reward)] = (hits, total)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "symbols",
        nargs="*",
        default=[
            "boom_1000_index",
            "crash_1000_index",
            "xauusd",
            "eurusd",
            "gbpusd",
            "usdjpy",
        ],
    )
    ap.add_argument("--where", default=".secrets/broker-deep")
    ap.add_argument("--interval", default="1h")
    ap.add_argument("--horizon", type=int, default=HORIZON)
    ap.add_argument("--every", type=int, default=4)
    args = ap.parse_args()

    print(
        f"stop fixed at {RISK} true range, target swept {REWARDS[0]} to {REWARDS[-1]}, "
        f"horizon {args.horizon} bars, one row per {args.every}\n"
    )
    print(
        "prediction recorded before the run: Boom beats fair odds on far UP targets\n"
        "and the excess grows with the ratio; Crash mirrors it on far DOWN targets;\n"
        "FX and metals stay flat at zero.\n"
    )

    for symbol in args.symbols:
        found = sorted(Path(args.where).glob(f"{symbol}_{args.interval}_*.csv.gz"))
        if not found:
            print(f"{symbol:<22} no {args.interval} file")
            continue
        bars, _repaired = candles.read(found[0])
        if len(bars) < args.horizon + 500:
            continue
        tr = candles.true_range(bars)
        got = measure(bars, tr, args.horizon, args.every)

        print(f"{symbol}")
        print(
            f"  {'R:R':>5}{'fair':>8}"
            f"{'long hit':>10}{'excess':>9}{'short hit':>11}{'excess':>9}{'n':>9}"
        )
        for reward in REWARDS:
            fair = RISK / (RISK + reward)
            lh, lt = got[(1, reward)]
            sh, st = got[(-1, reward)]
            if lt < 200 or st < 200:
                continue
            long_rate, short_rate = lh / lt, sh / st
            print(
                f"  {reward / RISK:>5.2f}{fair:>8.1%}"
                f"{long_rate:>10.1%}{long_rate - fair:>+9.1%}"
                f"{short_rate:>11.1%}{short_rate - fair:>+9.1%}{lt:>9,}"
            )
        # The asymmetry is the headline: on a jump process the two directions should
        # not be mirror images, and on a diffusion they should.
        gaps = []
        for reward in REWARDS:
            fair = RISK / (RISK + reward)
            lh, lt = got[(1, reward)]
            sh, st = got[(-1, reward)]
            if lt >= 200 and st >= 200:
                gaps.append((lh / lt) - (sh / st))
        if gaps:
            print(f"  long minus short, averaged over ratios: {np.mean(gaps):+.2%}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
