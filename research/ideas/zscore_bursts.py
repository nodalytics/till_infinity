"""z above 2.5: the trigger two of the published ideas read in opposite directions.

A z-score past 2.5 is the single most reused trigger in the idea batches, and
two of them disagree about what it means:

- **tick velocity** says a burst past +2.5 is institutional size arriving, so
  take the move's direction and hold 3 to 5 bars - **momentum**;
- **volume climax** says a reading past 2.5 standard deviations at the end of a
  run is retail capitulation into institutional supply, so take the other side
  and hold 3 to 5 days - **exhaustion**.

Same trigger, opposite bets. A measurement settles it, and the **sign** is the
whole answer: the forward return is measured in the burst's own direction, so
positive is momentum and negative is exhaustion.

## Four quantities, because "z-score" was never specified

Tick-arrival timestamps are not in a bar cache, so tick velocity's literal form
is out of reach. What bar data can carry a z-score of is the **signed return**,
the **absolute return**, the **tick volume** and the **bar range** - which are
the four quantities the ideas name between them. Each gets its own row.

The window is trailing and causal: mean and sd come from the bars strictly
before the one being scored. It is swept over **50, 70, 100 and 200**, because
a burst threshold means nothing without the window it is measured against - a
z of 2.5 against 50 bars and against 200 bars are different events.

For the unsigned quantities the bet needs a direction, and the ideas supply it:
"the net directional displacement", so the sign of that bar's close against its
open.

## Reported by instrument class, never pooled across them

A pooled median has already agreed here with a claim every subgroup refuted, so
FX majors, crosses, metals and the Deriv synthetics stay apart.

The synthetics are not decoration. **Boom and Crash indices have engineered
one-way spikes** - Boom jumps up, Crash down - so they are a known-answer
positive control: a burst detector that cannot see them is broken.
`Step_Index` and the volatility indices are the honest placebos, real markets
with a known generator and no institutions in them at all.

## What the sweeps print, and what they do not

**The mean and `n`, never `z`.** `z` carries the root of the sample size and `n`
falls fast as a threshold rises, so a `z` grid manufactures a peak wherever the
two balance - a mistake made here one run ago that reversed a reading.

The sweeps cover only the rows the main table flags at `|z|` over 2, plus every
synthetic row at the same kinds as controls. Sweeping rows that are flat at the
headline setting spends output on nothing, and the controls have to be there or
a surviving row has nothing to be compared against.
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

FRAMES = tuple(os.environ.get("FRAMES", "1h,4h").split(","))
BACKS = tuple(int(k) for k in os.environ.get("BACKS", "50,70,100,200").split(","))
MAIN_BACK = int(os.environ.get("MAIN_BACK", "50"))
CUTS = tuple(float(k) for k in os.environ.get("CUTS", "2.0,2.5,3.0,4.0").split(","))
HORIZONS = tuple(int(k) for k in os.environ.get("HORIZONS", "1,3,6,12").split(","))
MAIN = float(os.environ.get("MAIN", "2.5"))
MAIN_H = int(os.environ.get("MAIN_H", "3"))
NOTE = float(os.environ.get("NOTE", "2.0"))

CLASSES = (
    ("fx majors", ("EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD")),
    ("fx crosses", ("EURJPY", "GBPJPY", "AUDJPY", "CHFJPY", "EURGBP", "EURAUD", "EURCHF")),
    ("metals", ("XAUUSD", "XAGUSD")),
    ("placebo synth", ("Volatility_75_Index", "Volatility_100_Index", "Step_Index")),
    ("spike synth", ("Boom_500_Index", "Crash_500_Index")),
)
CONTROLS = ("placebo synth", "spike synth")
KINDS = ("signed return", "absolute return", "volume", "range")


def quantity(bars: dict, kind: str) -> tuple[np.ndarray, np.ndarray]:
    """`(scored, sign)` - the series to z-score and the direction to bet."""
    close, open_ = bars["close"], bars["open"]
    moved = np.diff(np.log(close), prepend=np.log(close[0]))
    body = np.sign(close - open_)
    body[body == 0] = 1.0
    if kind == "signed return":
        return moved, np.sign(moved)
    if kind == "absolute return":
        return np.abs(moved), body
    if kind == "volume":
        return bars["volume"].astype(float), body
    span = np.log(np.maximum(bars["high"], 1e-12)) - np.log(np.maximum(bars["low"], 1e-12))
    return span, body


def zscores(got: np.ndarray, back: int) -> np.ndarray:
    """Trailing and causal: the window ends on the bar before the one scored."""
    out = np.full(len(got), np.nan)
    if len(got) <= back + 1:
        return out
    rolling = np.lib.stride_tricks.sliding_window_view(got, back)[:-1]
    mean = rolling.mean(axis=1)
    sd = rolling.std(axis=1)
    live = sd > 0
    at = np.arange(back, len(got))
    out[at[live]] = (got[at[live]] - mean[live]) / sd[live]
    return out


def harvest(bars, kind, cut, horizon, back):
    """Signed forward return and round-trip cost, in median-bar-range units."""
    scored, sign = quantity(bars, kind)
    z = zscores(scored, back)
    close = bars["close"]
    span = np.log(np.maximum(bars["high"], 1e-12)) - np.log(np.maximum(bars["low"], 1e-12))
    scale = float(np.median(span[span > 0])) if (span > 0).any() else 0.0
    tick = tick_of(close)
    if scale <= 0 or tick <= 0:
        return np.empty(0), np.empty(0)
    logged = np.log(np.maximum(close, 1e-12))
    cost = 2.0 * bars["spread"].astype(float) * tick / close / scale
    moves, paid = [], []
    last = -(10**9)
    for i in np.flatnonzero(np.isfinite(z) & (z > cut)):
        i = int(i)
        if i - last < horizon or i + horizon >= len(close):
            continue
        last = i
        moves.append(sign[i] * (logged[i + horizon] - logged[i]) / scale)
        paid.append(float(cost[i]))
    return np.asarray(moves), np.asarray(paid)


def pooled(names, frame, kind, cut, horizon, back, shuffled=False):
    rng = np.random.default_rng(7)
    moves, paid = [], []
    for name in names:
        bars = load(name, frame)
        if bars is None:
            continue
        if shuffled:
            bars = shuffle_blocks(bars, rng)
        got, cost = harvest(bars, kind, cut, horizon, back)
        if len(got):
            moves.append(got)
            paid.append(cost)
    if not moves:
        return np.empty(0), np.empty(0)
    return np.concatenate(moves), np.concatenate(paid)


def zed(got: np.ndarray) -> float:
    """Closed-form sign-flip null: the standard error is sqrt(mean(x^2)/n)."""
    if len(got) < 20:
        return float("nan")
    spread = float(np.sqrt(np.mean(got**2) / len(got)))
    return float(np.mean(got)) / spread if spread else float("nan")


def main() -> None:
    print(
        f"z over {MAIN} on a trailing {MAIN_BACK}-bar window, bet in the burst's own\n"
        f"direction, held {MAIN_H} bars, in median-bar-range units. POSITIVE is\n"
        "momentum (tick velocity's claim), NEGATIVE is exhaustion (volume climax's).\n"
        "`net` pays the measured spread; `twin` is the block-shuffled surrogate.\n"
    )
    flagged: set[tuple[str, str]] = set()
    for frame in FRAMES:
        print(f"--- {frame}")
        print(
            f"  {'class':<16}{'kind':<17}{'n':>6}{'mean':>8}{'net':>8}{'z':>7}{'hit':>7}{'twin':>8}"
        )
        for label, names in CLASSES:
            for kind in KINDS:
                got, cost = pooled(names, frame, kind, MAIN, MAIN_H, MAIN_BACK)
                if len(got) < 30:
                    continue
                twin, _ = pooled(names, frame, kind, MAIN, MAIN_H, MAIN_BACK, shuffled=True)
                score = zed(got)
                if abs(score) >= NOTE and label not in CONTROLS:
                    flagged.add((label, kind))
                print(
                    f"  {label:<16}{kind:<17}{len(got):>6}{float(np.mean(got)):>8.3f}"
                    f"{float(np.mean(cost) * -1 + np.mean(got)):>8.3f}{score:>7.2f}"
                    f"{float(np.mean(got > 0)):>7.3f}"
                    f"{(float(np.mean(twin)) if len(twin) > 20 else float('nan')):>8.3f}"
                )
        print()

    rows = sorted(flagged) + [
        (label, kind)
        for label, _ in CLASSES
        if label in CONTROLS
        for kind in sorted({k for _, k in flagged})
    ]
    if not rows:
        print("nothing reached |z| 2 at the headline setting, so there is nothing to sweep.")
        return
    lookup = dict(CLASSES)

    print(f"the lookback, 1h, z over {MAIN}, h={MAIN_H}. mean then n:")
    print(f"  {'class':<16}{'kind':<17}" + "".join(f"{b:>8d}" for b in BACKS))
    for label, kind in rows:
        means, counts = [], []
        for back in BACKS:
            got, _ = pooled(lookup[label], "1h", kind, MAIN, MAIN_H, back)
            means.append(f"{float(np.mean(got)):>8.3f}" if len(got) >= 30 else "       .")
            counts.append(f"{len(got):>8d}" if len(got) >= 30 else "       .")
        print(f"  {label:<16}{kind:<17}" + "".join(means))
        print(f"  {'':<16}{'(n)':<17}" + "".join(counts))
    print()

    print(f"the threshold, 1h, lookback {MAIN_BACK}, h={MAIN_H}. mean then n:")
    print(f"  {'class':<16}{'kind':<17}" + "".join(f"{c:>8.1f}" for c in CUTS))
    for label, kind in rows:
        means, counts = [], []
        for cut in CUTS:
            got, _ = pooled(lookup[label], "1h", kind, cut, MAIN_H, MAIN_BACK)
            means.append(f"{float(np.mean(got)):>8.3f}" if len(got) >= 30 else "       .")
            counts.append(f"{len(got):>8d}" if len(got) >= 30 else "       .")
        print(f"  {label:<16}{kind:<17}" + "".join(means))
        print(f"  {'':<16}{'(n)':<17}" + "".join(counts))
    print()

    print(f"the horizon, 1h, lookback {MAIN_BACK}, z over {MAIN}. mean:")
    print(f"  {'class':<16}{'kind':<17}" + "".join(f"{f'h={h}':>8}" for h in HORIZONS))
    for label, kind in rows:
        cells = []
        for horizon in HORIZONS:
            got, _ = pooled(lookup[label], "1h", kind, MAIN, horizon, MAIN_BACK)
            cells.append(f"{float(np.mean(got)):>8.3f}" if len(got) >= 30 else "       .")
        print(f"  {label:<16}{kind:<17}" + "".join(cells))
    print(
        "\n  The spike synthetics are the positive control - a burst detector that\n"
        "  cannot see Boom and Crash is broken. The placebo synthetics are real\n"
        "  markets with no institutions in them, so anything paying there is not\n"
        "  the institutional story either idea tells. A reading matched by its\n"
        "  shuffled twin is bar geometry rather than a burst."
    )


if __name__ == "__main__":
    main()
