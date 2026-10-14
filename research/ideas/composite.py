"""Signal = w1*Trend + w2*Momentum + w3*Volatility + w_regime*Regime, hand tuned.

Proposed on 2026-10-14: *we can also test this out first with handtuned weights,
signal should say something before the move either up or down move, we can even
add posteriors and prob distributions, but it all feeds into this.*

## What today's failures dictate about how this is tested

Three rules, each bought with a false positive earlier in the day:

1. **Decision points are spaced a full horizon apart.** A per-level direction
   study read AUC 0.79 because consecutive touches shared 35 of their 40
   outcome bars (`two-sided-direction.md`). One decision, one window, no
   sharing.
2. **Every component uses bars strictly before the decision.** No component may
   touch the bar at `t` or after.
3. **Each component is reported beside the composite.** A composite that beats
   its own best component has earned something; one that does not is that
   component wearing three extra terms.

And the volatility term is reported twice. Added, as written, it makes a
volatile market look **bullish** - the term has no sign, so `w3 * Volatility`
pushes the score up either way. The variant divides by it instead, which is what
a signal-to-noise reading does. Both are run; the data can choose.

## The components, all scale-free

**Trend** is the slow signed one: where price sits against its own mean, in
units of a walk's spread over the window. **Momentum** is the fast signed one:
the recent leg, standardised the same way. **Volatility** is the unsigned ratio
of this window's spread to the one before it. **Regime** is signed persistence -
the net move times the share of bars that agreed with it - which separates a
trend that is grinding from one that is whipping.

`dir` and `first_up` are both carried, because "says something before the move"
can mean the endpoint or which barrier arrives, and `vol_up` is carried as the
check that a directional score is not secretly a volatility score.
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
    SEED,
    TRADED,
    auc,
    shuffle_blocks,
)
from screen import load  # noqa: E402

WINDOW = int(os.environ.get("WINDOW", "100"))
#: Bars ahead that the decision is judged on, and the spacing between
#: decisions, which are the same number on purpose.
HORIZON = int(os.environ.get("HORIZON", "40"))
FAST = int(os.environ.get("FAST", "10"))
#: The barrier for `first_up`, in window sigma.
BARRIER = float(os.environ.get("BARRIER", "1.0"))
PARTS = ("trend", "momentum", "volatility", "regime")
TARGETS = ("dir", "first_up", "vol_up")

#: Hand-tuned weight sets. The first is the proposal with every term equal; the
#: rest isolate the terms so a win can be attributed to one.
WEIGHTS: dict[str, tuple[float, float, float, float]] = {
    "equal 1,1,1,1": (1.0, 1.0, 1.0, 1.0),
    "trend only": (1.0, 0.0, 0.0, 0.0),
    "momentum only": (0.0, 1.0, 0.0, 0.0),
    "regime only": (0.0, 0.0, 0.0, 1.0),
    "no volatility": (1.0, 1.0, 0.0, 1.0),
    "trend+momentum": (1.0, 1.0, 0.0, 0.0),
    "momentum-led": (0.5, 1.0, 0.0, 0.5),
}


def read(bars, at: int) -> tuple[dict[str, float], dict[str, float]] | None:
    """Components from bars before `at`, and what happened from `at` onward."""
    closes, highs, lows = bars["close"], bars["high"], bars["low"]
    if at < 2 * WINDOW + 2 or at + HORIZON + 1 >= len(closes):
        return None
    # Strictly before the decision: the window ends at `at`, exclusive.
    rets = np.diff(np.log(closes[at - WINDOW : at + 1]))
    prior = np.diff(np.log(closes[at - 2 * WINDOW : at - WINDOW + 1]))
    sd = float(rets.std())
    if not (sd > 0 and prior.std() > 0) or not np.isfinite(rets).all():
        return None
    path = np.cumsum(rets)
    spread = sd * math.sqrt(WINDOW)
    net = float(rets.sum())
    agreed = float((np.sign(rets) == np.sign(net)).mean()) if net != 0 else 0.5
    parts = {
        "trend": (float(path[-1]) - float(path.mean())) / spread,
        "momentum": float(rets[-FAST:].sum()) / (sd * math.sqrt(FAST)),
        "volatility": sd / float(prior.std()),
        "regime": (net / spread) * (2.0 * agreed - 1.0),
    }
    ahead = np.diff(np.log(closes[at : at + HORIZON + 1]))
    run = np.cumsum(ahead)
    forward_sd = float(ahead.std())
    reach = BARRIER * spread
    up_at = np.flatnonzero(run >= reach)
    down_at = np.flatnonzero(run <= -reach)
    if len(up_at) and len(down_at):
        first = float(up_at[0] < down_at[0])
    elif len(up_at):
        first = 1.0
    elif len(down_at):
        first = 0.0
    else:
        first = 0.5  # neither barrier reached; dropped by the caller
    got = {
        "dir": float(run[-1] > 0),
        "first_up": first,
        "vol_up": float(forward_sd > sd),
    }
    if not all(math.isfinite(v) for v in parts.values()):
        return None
    return parts, got


def walk(bars) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray]]:
    rows = []
    # Spaced by HORIZON, so no two decisions share an outcome bar.
    for at in range(2 * WINDOW + 2, len(bars["close"]) - HORIZON - 2, HORIZON):
        got = read(bars, at)
        if got is not None:
            rows.append(got)
    if len(rows) < 60:
        return {}, {}
    parts = {p: np.array([r[0][p] for r in rows]) for p in PARTS}
    got = {t: np.array([r[1][t] for r in rows]) for t in TARGETS}
    return parts, got


def standardise(parts: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Per feed, so the weights mean the same thing on gold and on EURGBP."""
    out = {}
    for name, values in parts.items():
        spread = float(values.std())
        out[name] = (values - float(values.mean())) / (spread if spread > 0 else 1.0)
    return out


def score(feeds: list[tuple[dict, dict]], label: str) -> None:
    print(f"  {label}: {len(feeds)} feeds, {sum(len(f[1]['dir']) for f in feeds):,} decisions")
    print(f"    {'weights':<16}" + "".join(f"{t:>12}" for t in TARGETS) + "   sign agreement")
    for name, weight in WEIGHTS.items():
        line = []
        agree = []
        for target in TARGETS:
            per_feed = []
            for parts, got in feeds:
                signal = sum(w * parts[p] for w, p in zip(weight, PARTS, strict=True))
                truth = got[target]
                keep = truth != 0.5
                if keep.sum() < 40 or not (0 < truth[keep].sum() < keep.sum()):
                    continue
                one = auc(signal[keep][truth[keep] > 0.5], signal[keep][truth[keep] < 0.5])
                if math.isfinite(one):
                    per_feed.append(one)
            if not per_feed:
                line.append("-")
                agree.append("-")
                continue
            mean = float(np.mean(per_feed))
            same = sum(1 for a in per_feed if (a > 0.5) == (mean > 0.5)) / len(per_feed)
            line.append(f"{mean:.4f}")
            agree.append(f"{same:.0%}")
        print(f"    {name:<16}" + "".join(f"{v:>12}" for v in line) + "   " + " ".join(agree))
    # The variant: volatility divides rather than adds.
    line = []
    for target in TARGETS:
        per_feed = []
        for parts, got in feeds:
            scale = np.maximum(parts["volatility"] - parts["volatility"].min() + 1.0, 0.5)
            signal = (parts["trend"] + parts["momentum"] + parts["regime"]) / scale
            truth = got[target]
            keep = truth != 0.5
            if keep.sum() < 40 or not (0 < truth[keep].sum() < keep.sum()):
                continue
            one = auc(signal[keep][truth[keep] > 0.5], signal[keep][truth[keep] < 0.5])
            if math.isfinite(one):
                per_feed.append(one)
        line.append(f"{float(np.mean(per_feed)):.4f}" if per_feed else "-")
    print(f"    {'vol as divisor':<16}" + "".join(f"{v:>12}" for v in line))
    print()


def main() -> None:
    rng = np.random.default_rng(SEED)
    print(
        f"{WINDOW}-bar window, {HORIZON}-bar horizon and spacing, fast leg {FAST},\n"
        f"barrier {BARRIER} window sigma, {DRAWS} draws\n"
        "Every component is computed from bars strictly before the decision,\n"
        "and decisions are spaced so no two share an outcome bar.\n"
    )
    for group, names in (("traded", TRADED), ("control", CONTROL), ("generated", GENERATED)):
        print("=" * 76)
        print(group)
        print("=" * 76)
        real: list[tuple[dict, dict]] = []
        mixed: list[tuple[dict, dict]] = []
        for name in names:
            bars = load(name)
            if bars is None:
                continue
            parts, got = walk(bars)
            if parts:
                real.append((standardise(parts), got))
            parts, got = walk(shuffle_blocks(bars, rng))
            if parts:
                mixed.append((standardise(parts), got))
        if real:
            score(real, "real")
        if mixed:
            score(mixed, "shuffled")


if __name__ == "__main__":
    main()
