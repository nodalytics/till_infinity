"""EMAs and slopes as signals in their own right, scored by AUC.

`reversion_clock.py` used a rolling least-squares line as a **centre** - the
thing a stretch is measured from - and never scored the **slope** itself. That
is a different signal and a different claim: a centre asks "how far from fair",
a slope asks "which way is it going". The second was never measured here, and
it is what a linear-regression-channel or EMA-crossover idea actually trades.

Tick data would be the natural resolution for this and is **not reachable**:
the HTTP bridge exposes only the current tick, and the RPyC proxy that would
hand over `copy_ticks_range` is not running. So this runs at 3m, the finest
bars in the cache, and 15m.

## The signals

- **slope t** - the regression slope divided by its own standard error, which
  is the scale-free form. A raw slope is in price units a bar and cannot be
  compared across instruments or windows; its t-statistic can.
- **ema gap** - distance from an EMA in deviation units, the reversion reading,
  kept for contrast.
- **ema cross** - a fast EMA minus a slow one, in deviation units. The
  crossover, as a continuous score rather than a binary event.
- **ema slope** - the EMA's own change over a few bars, in deviation units.

Every one is scored for **momentum**: positive means the signal's direction is
the direction price then goes. A reversion reading is the same number with the
sign flipped, so one table answers both.

## Why the power line is not optional

`direction-is-closed-not-just-null` records that a direction gate here finds a
planted drift at z +2.90 and still earns 2% of a spread. A null on a direction
signal is the expected result, so the only thing that makes this measurement
worth anything is showing what it **could** have seen: a drift of known size is
planted in the forward returns and the AUC it produces is printed beside the
real one.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
from scipy.signal import lfilter  # type: ignore[import-untyped]

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
ROOT = HERE.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from level_signatures import auc, shuffle_blocks  # noqa: E402
from reversion_clock import HOURS, classes, rolling_sum  # noqa: E402
from screen import load  # noqa: E402

FRAMES = tuple(os.environ.get("FRAMES", "3m,15m").split(","))
SPANS = (("24h", 24.0), ("2d", 48.0), ("1w", 120.0))
MAIN_SPAN = os.environ.get("MAIN_SPAN", "24h")
HORIZONS = tuple(int(k) for k in os.environ.get("HORIZONS", "1,3,12").split(","))
MAIN_H = int(os.environ.get("MAIN_H", "3"))
PLANT = tuple(float(k) for k in os.environ.get("PLANT", "0.02,0.05,0.1").split(","))
KINDS = ("slope t", "ema gap", "ema cross", "ema slope")


def ema(got: np.ndarray, span: float) -> np.ndarray:
    alpha = 2.0 / (span + 1.0)
    return lfilter([alpha], [1.0, -(1.0 - alpha)], got, zi=[(1.0 - alpha) * got[0]])[0]


def features(price: np.ndarray, back: int) -> dict[str, np.ndarray]:
    """Each signal, causal, on a trailing `back`-bar window."""
    spot = np.arange(len(price), dtype=float)
    sum_y = rolling_sum(price, back)
    sum_yy = rolling_sum(price**2, back)
    sum_iy = rolling_sum(spot * price, back)
    start = spot - (back - 1)
    sum_x = back * (back - 1) / 2.0
    sum_xx = (back - 1) * back * (2 * back - 1) / 6.0
    sum_xy = sum_iy - start * sum_y
    spread_x = back * sum_xx - sum_x**2
    slope = (back * sum_xy - sum_x * sum_y) / spread_x
    intercept = (sum_y - slope * sum_x) / back
    sse = np.maximum(sum_yy - intercept * sum_y - slope * sum_xy, 0.0)
    # The slope's own standard error, which is what makes it comparable at all.
    centred_x = sum_xx - sum_x**2 / back
    with np.errstate(invalid="ignore", divide="ignore"):
        se = np.sqrt(sse / max(back - 2, 1) / centred_x)
        slope_t = np.where(se > 0, slope / se, np.nan)

    quick, slow = ema(price, back / 4.0), ema(price, float(back))
    gap = price - slow
    unit = np.sqrt(rolling_sum(np.nan_to_num(gap) ** 2, back) / back)
    step = max(int(back / 10), 2)
    moved = np.concatenate((np.full(step, np.nan), slow[step:] - slow[:-step]))
    with np.errstate(invalid="ignore", divide="ignore"):
        return {
            "slope t": slope_t,
            "ema gap": np.where(unit > 0, gap / unit, np.nan),
            "ema cross": np.where(unit > 0, (quick - slow) / unit, np.nan),
            "ema slope": np.where(unit > 0, moved / unit, np.nan),
        }


def gather(names, frame, back, horizon, shuffled=False):
    rng = np.random.default_rng(13)
    out: dict[str, list[np.ndarray]] = {k: [] for k in KINDS}
    aheads: list[np.ndarray] = []
    for name in names:
        bars = load(name, frame)
        if bars is None:
            continue
        if shuffled:
            bars = shuffle_blocks(bars, rng)
        price = np.log(np.maximum((bars["high"] + bars["low"] + bars["close"]) / 3.0, 1e-12))
        if len(price) < back + horizon + 600:
            continue
        got = features(price, back)
        at = np.arange(back - 1, len(price) - horizon, horizon)
        if len(at) < 400:
            continue
        logged = np.log(np.maximum(bars["close"], 1e-12))
        ahead = logged[at + horizon] - logged[at]
        keep = np.isfinite(ahead)
        for kind in KINDS:
            keep &= np.isfinite(got[kind][at])
        if keep.sum() < 400:
            continue
        for kind in KINDS:
            out[kind].append(got[kind][at][keep])
        aheads.append(ahead[keep])
    if not aheads:
        return None
    return (
        {kind: np.concatenate(out[kind]) for kind in KINDS},
        np.concatenate(aheads),
    )


def scored(score: np.ndarray, ahead: np.ndarray) -> float:
    up = ahead > 0
    if up.sum() < 50 or (~up).sum() < 50:
        return float("nan")
    return auc(score[up], score[~up])


def main() -> None:
    print(
        "AUC of each signal against the forward return, tie-aware, spaced by the\n"
        "horizon. Above 0.5 is momentum, below is reversion. `twin` is the\n"
        "block-shuffled surrogate and is the baseline. `planted` is the AUC the\n"
        "same test gives when a drift of that size is added, which is the power\n"
        "statement a direction null needs to mean anything.\n"
        "Tick data is not reachable - no RPyC proxy running, no bridge route - so\n"
        f"{FRAMES[0]} is the finest resolution available.\n"
    )
    for frame in FRAMES:
        back = int(dict(SPANS)[MAIN_SPAN] / HOURS[frame])
        print(f"--- {frame}, span {MAIN_SPAN} = {back} bars, horizon {MAIN_H}")
        head = "".join(f"{f'+{p:g}':>9}" for p in PLANT)
        print(f"  {'class':<18}{'kind':<11}{'n':>8}{'auc':>8}{'twin':>8}{'edge':>8}  |{head}")
        for label, names in classes(frame):
            if not names:
                continue
            live = gather(names, frame, back, MAIN_H)
            twin = gather(names, frame, back, MAIN_H, shuffled=True)
            if live is None or twin is None:
                continue
            feats, ahead = live
            tfeats, tahead = twin
            for kind in KINDS:
                a = scored(feats[kind], ahead)
                b = scored(tfeats[kind], tahead)
                if not (np.isfinite(a) and np.isfinite(b)):
                    continue
                # Power: a drift proportional to the signal's own sign.
                unit = float(np.std(ahead)) or 1.0
                cells = []
                for size in PLANT:
                    lifted = ahead + size * unit * np.sign(feats[kind])
                    cells.append(f"{scored(feats[kind], lifted):>9.4f}")
                print(
                    f"  {label:<18}{kind:<11}{len(ahead):>8}{a:>8.4f}{b:>8.4f}"
                    f"{a - b:>+8.4f}  |" + "".join(cells)
                )
        print()

    print(f"the horizon, 15m, span {MAIN_SPAN}. edge:")
    back = int(dict(SPANS)[MAIN_SPAN] / HOURS["15m"])
    print(f"  {'class':<18}{'kind':<11}" + "".join(f"{f'h={h}':>9}" for h in HORIZONS))
    for label, names in classes("15m"):
        if not names:
            continue
        rows: dict[str, list[str]] = {k: [] for k in KINDS}
        for horizon in HORIZONS:
            live = gather(names, "15m", back, horizon)
            twin = gather(names, "15m", back, horizon, shuffled=True)
            for kind in KINDS:
                if live is None or twin is None:
                    rows[kind].append("        .")
                    continue
                a = scored(live[0][kind], live[1])
                b = scored(twin[0][kind], twin[1])
                rows[kind].append(
                    f"{a - b:>+9.4f}" if np.isfinite(a) and np.isfinite(b) else "        ."
                )
        for kind in KINDS:
            if all(c.strip() == "." for c in rows[kind]):
                continue
            print(f"  {label:<18}{kind:<11}" + "".join(rows[kind]))
    print()

    print(f"the span, 15m, horizon {MAIN_H}. edge:")
    print(f"  {'class':<18}{'kind':<11}" + "".join(f"{s:>9}" for s, _ in SPANS))
    for label, names in classes("15m"):
        if not names:
            continue
        rows = {k: [] for k in KINDS}
        for _, hours in SPANS:
            back = int(hours / HOURS["15m"])
            live = gather(names, "15m", back, MAIN_H)
            twin = gather(names, "15m", back, MAIN_H, shuffled=True)
            for kind in KINDS:
                if live is None or twin is None:
                    rows[kind].append("        .")
                    continue
                a = scored(live[0][kind], live[1])
                b = scored(twin[0][kind], twin[1])
                rows[kind].append(
                    f"{a - b:>+9.4f}" if np.isfinite(a) and np.isfinite(b) else "        ."
                )
        for kind in KINDS:
            if all(c.strip() == "." for c in rows[kind]):
                continue
            print(f"  {label:<18}{kind:<11}" + "".join(rows[kind]))
    print(
        "\n  A planted drift of 0.02 standard deviations already moving the AUC well\n"
        "  clear of the real reading is the statement that this test had the power\n"
        "  to see an effect and did not."
    )


if __name__ == "__main__":
    main()
