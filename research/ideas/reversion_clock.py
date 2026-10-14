"""Reversion signals on **time** lookbacks, with a robust scale, across frames.

`reversion_auc.py` measured the stretch signal on bar-count lookbacks and found
the answer: AUC tops out at **0.518** raw, the block-shuffled twin accounts for
about two thirds of the excess over 0.5, and the best edge over that surrogate
is **+0.008**. The one coherent structure was the volume conditioner running
**backwards** to the published climax story - reversion strongest where the
volume stretch is lowest.

This run changes three things that were all arbitrary before.

## The lookback is a duration, not a bar count

A 100-bar window means six hours at 3m and four days at 1h, so comparing frames
at matched bar counts compares different questions. Here the window is a
**span** - 24 hours, 2 days, 3 days, 2 weeks, 3 weeks - converted to a bar count
per frame, which is the matched comparison. A day is 24 **trading** hours and a
week is five of those, because FX closes at the weekend; stated explicitly
because "2 weeks" could as easily mean 336 calendar hours and the two differ by
40%.

The bar count each span becomes is printed, since that is what actually drives
the estimator.

## The scale can be robust

A standard deviation is dragged by the same news spikes a reversion signal is
supposed to be measuring, so a single outlier inside the window inflates the
denominator and hides the next one. The **modified z-score** uses the median and
the median absolute deviation, scaled by 1.4826 so it estimates the same sigma
on Gaussian data, and is immune to that by construction. Both are run.

Being immune to spikes is not the same as being right, so the twin still
decides: a robust scale will also happily manufacture reversion if the centre
lags, and the whole point of the previous run was that the centre is what lags.

## The subjects

Deriv synthetic families are discovered from the cache by prefix rather than
named by hand, and run as **first-class subjects**. They are real markets with
known generators: a volatility index has no reversion designed into it, so an
edge near zero there is the measurement proving itself calibrated rather than a
disappointing result.
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

from level_signatures import CACHE, auc, shuffle_blocks  # noqa: E402
from screen import load  # noqa: E402

#: Hours per bar, which is what turns a span into a window.
HOURS = {"3m": 0.05, "15m": 0.25, "1h": 1.0, "4h": 4.0}
#: A day is 24 trading hours and a week is five of them, because FX closes.
SPANS = (("24h", 24.0), ("2d", 48.0), ("3d", 72.0), ("2w", 240.0), ("3w", 360.0))
FRAMES = tuple(os.environ.get("FRAMES", "3m,15m,1h").split(","))
MAIN_SPAN = os.environ.get("MAIN_SPAN", "2d")
HORIZON = int(os.environ.get("HORIZON", "3"))
CENTRES = ("mean", "ema", "regress")
SCALES = ("sd", "mad")
STRATA = int(os.environ.get("STRATA", "3"))
LEAST = int(os.environ.get("LEAST", "400"))


def family(prefix: str, frame: str, most: int = 4) -> tuple[str, ...]:
    """Synthetic names discovered from the cache, not guessed."""
    found = sorted({p.stem.partition(".")[0] for p in CACHE.glob(f"{prefix}*.{frame}.npz")})
    return tuple(found[:most])


def classes(frame: str):
    return (
        ("fx majors", ("EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD")),
        ("fx crosses", ("EURJPY", "GBPJPY", "AUDJPY", "CHFJPY", "EURGBP", "EURAUD", "EURCHF")),
        ("metals", ("XAUUSD", "XAGUSD")),
        ("synth volatility", family("Volatility", frame)),
        ("synth step", family("Step", frame) + family("Skew_Step", frame, 2)),
        ("synth boom/crash", family("Boom", frame, 2) + family("Crash", frame, 2)),
        ("synth jump", family("Jump", frame)),
        ("synth dex", family("DEX", frame)),
    )


def rolling_sum(got: np.ndarray, back: int) -> np.ndarray:
    out = np.full(len(got), np.nan)
    running = np.concatenate(([0.0], np.cumsum(got)))
    out[back - 1 :] = running[back:] - running[: len(got) - back + 1]
    return out


def deviation(price: np.ndarray, back: int, centre: str, scale: str, at: np.ndarray):
    """`z` at the evaluation points only, which is what makes a robust scale affordable.

    A rolling median over a 7,200-bar window on every bar would allocate
    gigabytes. Only the spaced evaluation points are ever scored, so only those
    are computed.
    """
    if centre == "mean":
        mid = rolling_sum(price, back) / back
    elif centre == "ema":
        alpha = 2.0 / (back + 1.0)
        mid = lfilter([alpha], [1.0, -(1.0 - alpha)], price, zi=[(1.0 - alpha) * price[0]])[0]
        mid[: back - 1] = np.nan
    else:
        spot = np.arange(len(price), dtype=float)
        sum_y = rolling_sum(price, back)
        sum_iy = rolling_sum(spot * price, back)
        start = spot - (back - 1)
        sum_x = back * (back - 1) / 2.0
        sum_xx = (back - 1) * back * (2 * back - 1) / 6.0
        sum_xy = sum_iy - start * sum_y
        slope = (back * sum_xy - sum_x * sum_y) / (back * sum_xx - sum_x**2)
        mid = (sum_y - slope * sum_x) / back + slope * (back - 1)

    if scale == "sd":
        if centre == "mean":
            squares = rolling_sum(price**2, back)
            spread = np.sqrt(np.maximum(squares / back - mid**2, 0.0))
        else:
            gap = price - mid
            spread = np.sqrt(rolling_sum(np.nan_to_num(gap) ** 2, back) / back)
        return (price[at] - mid[at]) / np.where(spread[at] > 0, spread[at], np.nan)

    # Robust: the median absolute deviation about this centre, scaled to sigma.
    out = np.full(len(at), np.nan)
    for k, i in enumerate(at):
        window = price[i - back + 1 : i + 1]
        if not np.isfinite(mid[i]):
            continue
        spread = 1.4826 * float(np.median(np.abs(window - mid[i])))
        if spread > 0:
            out[k] = (price[i] - mid[i]) / spread
    return out


def gather(names, frame, back, centre, scale, shuffled=False):
    rng = np.random.default_rng(13)
    scores, vols, aheads = [], [], []
    for name in names:
        bars = load(name, frame)
        if bars is None:
            continue
        if shuffled:
            bars = shuffle_blocks(bars, rng)
        price = np.log(np.maximum((bars["high"] + bars["low"] + bars["close"]) / 3.0, 1e-12))
        if len(price) < back + 10 * HORIZON + LEAST:
            continue
        at = np.arange(back - 1, len(price) - HORIZON, HORIZON)
        if len(at) < LEAST:
            continue
        z = deviation(price, back, centre, scale, at)
        vz = deviation(bars["volume"].astype(float), back, centre, scale, at)
        logged = np.log(np.maximum(bars["close"], 1e-12))
        ahead = logged[at + HORIZON] - logged[at]
        keep = np.isfinite(z) & np.isfinite(ahead) & np.isfinite(vz)
        if keep.sum() < LEAST:
            continue
        scores.append(-z[keep])  # reversion: a stretch down should rise
        vols.append(vz[keep])
        aheads.append(ahead[keep])
    if not scores:
        return None
    return np.concatenate(scores), np.concatenate(vols), np.concatenate(aheads)


def scored(score: np.ndarray, ahead: np.ndarray) -> float:
    up = ahead > 0
    if up.sum() < 50 or (~up).sum() < 50:
        return float("nan")
    return auc(score[up], score[~up])


def edge_of(names, frame, back, centre, scale):
    live = gather(names, frame, back, centre, scale)
    twin = gather(names, frame, back, centre, scale, shuffled=True)
    if live is None or twin is None:
        return None
    a, b = scored(live[0], live[2]), scored(twin[0], twin[2])
    if not (np.isfinite(a) and np.isfinite(b)):
        return None
    return a, b, len(live[0]), live


def main() -> None:
    print(
        f"AUC of the reversion signal against the forward {HORIZON}-bar return,\n"
        "tie-aware, spaced by the horizon. `twin` is the block-shuffled surrogate\n"
        "and is the baseline, not 0.5. A day is 24 trading hours, a week five of\n"
        "them. There is no 1m data in the cache.\n"
    )
    print("  span to bars:")
    for frame in FRAMES:
        counts = ", ".join(f"{label} {int(hours / HOURS[frame])}" for label, hours in SPANS)
        print(f"    {frame:<4} {counts}")
    print()

    for frame in FRAMES:
        back = int(dict(SPANS)[MAIN_SPAN] / HOURS[frame])
        print(f"--- {frame}, span {MAIN_SPAN} = {back} bars")
        print(f"  {'class':<18}{'centre':<9}{'scale':<6}{'n':>8}{'auc':>8}{'twin':>8}{'edge':>8}")
        for label, names in classes(frame):
            if not names:
                continue
            for centre in CENTRES:
                for scale in SCALES:
                    got = edge_of(names, frame, back, centre, scale)
                    if got is None:
                        continue
                    live, twin, count, _ = got
                    print(
                        f"  {label:<18}{centre:<9}{scale:<6}{count:>8}"
                        f"{live:>8.4f}{twin:>8.4f}{live - twin:>+8.4f}"
                    )
        print()

    print("the span, 15m, edge (live AUC minus twin AUC):")
    print(f"  {'class':<18}{'centre':<9}{'scale':<6}" + "".join(f"{s:>9}" for s, _ in SPANS))
    for label, names in classes("15m"):
        if not names:
            continue
        for centre in CENTRES:
            for scale in SCALES:
                cells = []
                for _, hours in SPANS:
                    got = edge_of(names, "15m", int(hours / HOURS["15m"]), centre, scale)
                    cells.append(f"{got[0] - got[1]:>+9.4f}" if got else "        .")
                if all(c.strip() == "." for c in cells):
                    continue
                print(f"  {label:<18}{centre:<9}{scale:<6}" + "".join(cells))
    print()

    print(f"volume stretch as a conditioner, 15m, span {MAIN_SPAN}, {STRATA} strata:")
    print(
        f"  {'class':<18}{'centre':<9}{'scale':<6}"
        + "".join(f"{f'v{k}':>9}" for k in range(STRATA))
    )
    back = int(dict(SPANS)[MAIN_SPAN] / HOURS["15m"])
    for label, names in classes("15m"):
        if not names:
            continue
        for centre in CENTRES:
            for scale in SCALES:
                live = gather(names, "15m", back, centre, scale)
                twin = gather(names, "15m", back, centre, scale, shuffled=True)
                if live is None or twin is None:
                    continue
                score, vz, ahead = live
                tscore, tvz, tahead = twin
                bounds = np.quantile(vz, np.linspace(0.0, 1.0, STRATA + 1))
                cells = []
                for k in range(STRATA):
                    lo, hi = bounds[k], bounds[k + 1]
                    last = k == STRATA - 1
                    pick = (vz >= lo) & (vz <= hi if last else vz < hi)
                    tpick = (tvz >= lo) & (tvz <= hi if last else tvz < hi)
                    a, b = scored(score[pick], ahead[pick]), scored(tscore[tpick], tahead[tpick])
                    cells.append(
                        f"{a - b:>+9.4f}" if np.isfinite(a) and np.isfinite(b) else "        ."
                    )
                print(f"  {label:<18}{centre:<9}{scale:<6}" + "".join(cells))
    print(
        "\n  v0 is the lowest volume stretch, so the published climax story predicts\n"
        "  the edge rising across each row. The previous run found it falling."
    )


if __name__ == "__main__":
    main()
