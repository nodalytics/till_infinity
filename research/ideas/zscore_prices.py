"""z over the OHLC prices themselves, which is a state and not an event.

`zscore_bursts.py` scored returns, volume and range - quantities that spike and
subside, where "z over 2.5" names a single bar. A z-score of the **price level**
against a trailing window is a different object: price does not return to its
mean between bars, so a stretched reading **persists**, and a run of forty bars
can sit above 2.5 the whole way.

That makes the event definition the crux rather than a detail, and it is tested
both ways:

- **crossing** - the first bar where z goes from at-or-below the threshold to
  above it. One event per excursion.
- **level** - every bar above the threshold, which is what a naive reading of
  "z over 2.5" does. Its events overlap by construction and it is here to show
  what that costs.

Overlapping windows have produced a direction AUC of 0.79 in this repo that
collapsed to 0.51 once separated, so this is not a hypothetical.

## The direction question is the opposite one

For a burst the claim was momentum against exhaustion. For a stretched price it
is **breakout against mean reversion**, and the same convention answers it: the
forward return is measured in the stretch's own direction, so **positive is
continuation** and **negative is reversion**.

Up-stretches and down-stretches are reported separately as well as pooled,
because an asymmetry between them is a different finding from either.

## The four prices are not four independent tests

The open, high, low and close of one bar sit within a fraction of a bar's range
of each other, so their z-scores against a 50-bar window are nearly the same
number and these rows are **one test seen four times**, not four. They are kept
apart because the high and the low can disagree - a stretched high with an
unstretched close is a rejected push - and not because the family-wise count
should treat them as independent.

Controls are as before: a block-shuffled twin at the same sample size, Deriv
placebos that are real markets with no institutions in them, the Boom and Crash
indices as a known-answer positive control, spacing by the full horizon, and
the measured spread.
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

from level_signatures import shuffle_blocks  # noqa: E402
from screen import load  # noqa: E402
from swap_squeeze import tick_of  # noqa: E402
from zscore_bursts import CLASSES, CONTROLS, zed, zscores  # noqa: E402

FRAMES = tuple(os.environ.get("FRAMES", "1h,4h").split(","))
BACKS = tuple(int(k) for k in os.environ.get("BACKS", "50,70,100,200").split(","))
MAIN_BACK = int(os.environ.get("MAIN_BACK", "50"))
CUTS = tuple(float(k) for k in os.environ.get("CUTS", "2.0,2.5,3.0,4.0").split(","))
HORIZONS = tuple(int(k) for k in os.environ.get("HORIZONS", "1,3,6,12").split(","))
MAIN = float(os.environ.get("MAIN", "2.5"))
MAIN_H = int(os.environ.get("MAIN_H", "3"))
NOTE = float(os.environ.get("NOTE", "2.0"))

KINDS = ("close", "high", "low", "open", "typical")
MODES = ("crossing", "level")


def priced(bars: dict, kind: str) -> np.ndarray:
    if kind == "typical":
        return (bars["high"] + bars["low"] + bars["close"]) / 3.0
    return bars[kind].astype(float)


def harvest(bars, kind, cut, horizon, back, mode, side):
    """Signed forward return and cost, in median-bar-range units."""
    z = zscores(np.log(np.maximum(priced(bars, kind), 1e-12)), back)
    close = bars["close"]
    span = np.log(np.maximum(bars["high"], 1e-12)) - np.log(np.maximum(bars["low"], 1e-12))
    scale = float(np.median(span[span > 0])) if (span > 0).any() else 0.0
    tick = tick_of(close)
    if scale <= 0 or tick <= 0:
        return np.empty(0), np.empty(0)
    logged = np.log(np.maximum(close, 1e-12))
    cost = 2.0 * bars["spread"].astype(float) * tick / close / scale
    live = np.isfinite(z)
    up, down = live & (z > cut), live & (z < -cut)
    if mode == "crossing":
        # The first bar of an excursion: above now, not above on the bar before.
        up &= ~np.concatenate(([False], up[:-1]))
        down &= ~np.concatenate(([False], down[:-1]))
    picked = {"up": up, "down": down, "both": up | down}[side]
    signs = np.where(up, 1.0, -1.0)
    moves, paid = [], []
    last = -(10**9)
    for i in np.flatnonzero(picked):
        i = int(i)
        if i - last < horizon or i + horizon >= len(close):
            continue
        last = i
        moves.append(signs[i] * (logged[i + horizon] - logged[i]) / scale)
        paid.append(float(cost[i]))
    return np.asarray(moves), np.asarray(paid)


def pooled(names, frame, kind, cut, horizon, back, mode="crossing", side="both", shuffled=False):
    rng = np.random.default_rng(7)
    moves, paid = [], []
    for name in names:
        bars = load(name, frame)
        if bars is None:
            continue
        if shuffled:
            bars = shuffle_blocks(bars, rng)
        got, cost = harvest(bars, kind, cut, horizon, back, mode, side)
        if len(got):
            moves.append(got)
            paid.append(cost)
    if not moves:
        return np.empty(0), np.empty(0)
    return np.concatenate(moves), np.concatenate(paid)


def main() -> None:
    print(
        f"z of the log price over a trailing {MAIN_BACK}-bar window, past {MAIN},\n"
        f"held {MAIN_H} bars, measured in the stretch's own direction and in\n"
        "median-bar-range units. POSITIVE is continuation (breakout), NEGATIVE is\n"
        "reversion. `net` pays the measured spread; `twin` is block-shuffled.\n"
    )
    flagged: set[tuple[str, str]] = set()
    for frame in FRAMES:
        for mode in MODES:
            print(f"--- {frame}, {mode}")
            print(
                f"  {'class':<16}{'kind':<10}{'n':>7}{'mean':>8}{'net':>8}"
                f"{'z':>7}{'hit':>7}{'twin':>8}{'up':>8}{'down':>8}"
            )
            for label, names in CLASSES:
                for kind in KINDS:
                    got, cost = pooled(names, frame, kind, MAIN, MAIN_H, MAIN_BACK, mode)
                    if len(got) < 30:
                        continue
                    twin, _ = pooled(
                        names, frame, kind, MAIN, MAIN_H, MAIN_BACK, mode, shuffled=True
                    )
                    up, _ = pooled(names, frame, kind, MAIN, MAIN_H, MAIN_BACK, mode, "up")
                    down, _ = pooled(names, frame, kind, MAIN, MAIN_H, MAIN_BACK, mode, "down")
                    score = zed(got)
                    if abs(score) >= NOTE and label not in CONTROLS and mode == "crossing":
                        flagged.add((label, kind))
                    print(
                        f"  {label:<16}{kind:<10}{len(got):>7}{float(np.mean(got)):>8.3f}"
                        f"{float(np.mean(got) - np.mean(cost)):>8.3f}{score:>7.2f}"
                        f"{float(np.mean(got > 0)):>7.3f}"
                        f"{(float(np.mean(twin)) if len(twin) > 20 else float('nan')):>8.3f}"
                        f"{(float(np.mean(up)) if len(up) > 20 else float('nan')):>8.3f}"
                        f"{(float(np.mean(down)) if len(down) > 20 else float('nan')):>8.3f}"
                    )
            print()

    rows = sorted(flagged) + [
        (label, kind)
        for label, _ in CLASSES
        if label in CONTROLS
        for kind in sorted({k for _, k in flagged})
    ]
    if not rows:
        print("nothing reached |z| 2 on crossings, so there is nothing to sweep.")
        return
    lookup = dict(CLASSES)

    for title, values, call in (
        (f"the lookback, 1h crossings, z over {MAIN}, h={MAIN_H}", BACKS, "back"),
        (f"the threshold, 1h crossings, lookback {MAIN_BACK}, h={MAIN_H}", CUTS, "cut"),
        (f"the horizon, 1h crossings, lookback {MAIN_BACK}, z over {MAIN}", HORIZONS, "horizon"),
    ):
        print(f"{title}. mean then n:")
        print(f"  {'class':<16}{'kind':<10}" + "".join(f"{v:>9}" for v in values))
        for label, kind in rows:
            means, counts = [], []
            for value in values:
                if call == "back":
                    got, _ = pooled(lookup[label], "1h", kind, MAIN, MAIN_H, value)
                elif call == "cut":
                    got, _ = pooled(lookup[label], "1h", kind, value, MAIN_H, MAIN_BACK)
                else:
                    got, _ = pooled(lookup[label], "1h", kind, MAIN, value, MAIN_BACK)
                means.append(f"{float(np.mean(got)):>9.3f}" if len(got) >= 30 else "        .")
                counts.append(f"{len(got):>9d}" if len(got) >= 30 else "        .")
            print(f"  {label:<16}{kind:<10}" + "".join(means))
            print(f"  {'':<16}{'(n)':<10}" + "".join(counts))
        print()
    print(
        "  `crossing` against `level` is the measurement that matters most here: a\n"
        "  price z-score is a state, so `level` re-samples one excursion many times\n"
        "  and any gap between the two rows is that overlap, not a market effect."
    )


if __name__ == "__main__":
    main()
