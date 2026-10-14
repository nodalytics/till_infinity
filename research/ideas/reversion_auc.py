"""Does a stretch signal work for mean reversion, and what is its AUC?

Three runs have now established that a **trailing-mean** z-score manufactures
the reversion it measures: the window's mean is backward-looking, so a walk
that has drifted away from it has no tendency to come back - the statistic comes
back as the window catches up. On FX crosses the block-shuffled twin took +0.111
of a +0.137 effect at `z` 4.23.

That diagnosis names its own fix, and it is the reason for this harness. **The
centre is the variable.** A trailing mean lags a drifting series by
construction; a least-squares line fitted over the same window does not, because
it removes the drift. So the question is not whether a stretch signal works, it
is **which centre's signal survives its own surrogate** - and the twin's AUC,
not 0.5, is the baseline that answers it.

## What varies

- **centre**: `mean`, a trailing simple average; `ema`, exponential with the
  same effective span; `regress`, a rolling least-squares line evaluated at the
  current bar, with the deviation measured about the **line** rather than about
  the mean.
- **quantity**: `hlc3` - the typical price - and the **tick volume**, scored
  the same way, and the two **combined**. Volume carries no direction, so it
  cannot be a signal by itself; it enters as a conditioner, which is what
  "combine" has to mean here.
- **lookback**: 50, 70, 100, 200 and 500 bars.
- **frame**: 3m and 15m - the cache's two lowest - and 1h for continuity.
  **There is no 1m data in the cache**, so the floor is 3m.
- **instrument**: the Deriv synthetics as first-class subjects rather than only
  as controls, beside FX majors, crosses and metals. The synthetics are real
  markets with known generators, which makes a reversion result on them
  interpretable in a way an FX result is not.

## The metric, and why the twin sets the baseline

AUC of the reversion signal against whether the forward return went the
signal's way, tie-aware. A reversion signal says a stretched-down price will
rise, so the score is the **negative** of the deviation and an AUC above 0.5
means reversion pays.

Every cell is run again on a **block-shuffled surrogate** of the same feeds, and
the number that matters is `edge` - live AUC minus twin AUC. A trailing-mean
score will read well above 0.5 on the surrogate, because that is the artefact
already measured, and anything whose edge is zero is reading its own
construction. Bars are spaced by the full horizon so no two forward windows
overlap.
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
from screen import load  # noqa: E402

FRAMES = tuple(os.environ.get("FRAMES", "3m,15m,1h").split(","))
BACKS = tuple(int(k) for k in os.environ.get("BACKS", "50,70,100,200,500").split(","))
MAIN_BACK = int(os.environ.get("MAIN_BACK", "100"))
HORIZON = int(os.environ.get("HORIZON", "3"))
CENTRES = ("mean", "ema", "regress")
STRATA = int(os.environ.get("STRATA", "3"))

CLASSES = (
    ("fx majors", ("EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD")),
    ("fx crosses", ("EURJPY", "GBPJPY", "AUDJPY", "CHFJPY", "EURGBP", "EURAUD", "EURCHF")),
    ("metals", ("XAUUSD", "XAGUSD")),
    ("synth volatility", ("Volatility_25_Index", "Volatility_75_Index", "Volatility_100_Index")),
    ("synth step", ("Step_Index",)),
    ("synth boom/crash", ("Boom_500_Index", "Crash_500_Index")),
)


def rolling_sum(got: np.ndarray, back: int) -> np.ndarray:
    """Trailing sum ending at each index, NaN until the window is full."""
    out = np.full(len(got), np.nan)
    running = np.concatenate(([0.0], np.cumsum(got)))
    out[back - 1 :] = running[back:] - running[: len(got) - back + 1]
    return out


def centred(price: np.ndarray, back: int, centre: str) -> tuple[np.ndarray, np.ndarray]:
    """`(deviation, sd)` of the price from the chosen centre, both trailing.

    The window **ends on the current bar**, which is what a live signal can see.
    """
    if centre == "mean":
        total = rolling_sum(price, back)
        squares = rolling_sum(price**2, back)
        mean = total / back
        var = np.maximum(squares / back - mean**2, 0.0)
        return price - mean, np.sqrt(var)
    if centre == "ema":
        # Same effective span, so the two centres are comparable.
        alpha = 2.0 / (back + 1.0)
        level = lfilter([alpha], [1.0, -(1.0 - alpha)], price, zi=[(1.0 - alpha) * price[0]])[0]
        gap = price - level
        var = lfilter([alpha], [1.0, -(1.0 - alpha)], gap**2, zi=[(1.0 - alpha) * gap[0] ** 2])[0]
        out = np.full(len(price), np.nan)
        out[back - 1 :] = gap[back - 1 :]
        return out, np.sqrt(np.maximum(var, 0.0))
    # A least-squares line over the window, evaluated at its last point, with
    # the deviation measured about the line. Closed form from rolling sums, so
    # it costs one pass rather than one fit per bar.
    at = np.arange(len(price), dtype=float)
    sum_y = rolling_sum(price, back)
    sum_yy = rolling_sum(price**2, back)
    sum_iy = rolling_sum(at * price, back)
    start = at - (back - 1)
    sum_x = back * (back - 1) / 2.0
    sum_xx = (back - 1) * back * (2 * back - 1) / 6.0
    sum_xy = sum_iy - start * sum_y
    denom = back * sum_xx - sum_x**2
    slope = (back * sum_xy - sum_x * sum_y) / denom
    intercept = (sum_y - slope * sum_x) / back
    fitted = intercept + slope * (back - 1)
    sse = np.maximum(sum_yy - intercept * sum_y - slope * sum_xy, 0.0)
    return price - fitted, np.sqrt(sse / back)


def signals(bars: dict, back: int, centre: str):
    """`(reversion score, volume stretch, forward return)`, aligned."""
    price = np.log(np.maximum((bars["high"] + bars["low"] + bars["close"]) / 3.0, 1e-12))
    gap, sd = centred(price, back, centre)
    with np.errstate(invalid="ignore", divide="ignore"):
        z = np.where(sd > 0, gap / sd, np.nan)
    vol = bars["volume"].astype(float)
    vgap, vsd = centred(vol, back, centre)
    with np.errstate(invalid="ignore", divide="ignore"):
        vz = np.where(vsd > 0, vgap / vsd, np.nan)
    logged = np.log(np.maximum(bars["close"], 1e-12))
    ahead = np.full(len(logged), np.nan)
    ahead[:-HORIZON] = logged[HORIZON:] - logged[:-HORIZON]
    # Reversion: a price stretched down should rise, so the score is -z.
    return -z, vz, ahead


def gather(names, frame, back, centre, shuffled=False):
    rng = np.random.default_rng(13)
    scores, vols, aheads = [], [], []
    for name in names:
        bars = load(name, frame)
        if bars is None:
            continue
        if shuffled:
            bars = shuffle_blocks(bars, rng)
        score, vz, ahead = signals(bars, back, centre)
        keep = np.isfinite(score) & np.isfinite(ahead) & np.isfinite(vz)
        at = np.flatnonzero(keep)[::HORIZON]  # spaced, so windows never overlap
        if len(at) < 200:
            continue
        scores.append(score[at])
        vols.append(vz[at])
        aheads.append(ahead[at])
    if not scores:
        return None
    return np.concatenate(scores), np.concatenate(vols), np.concatenate(aheads)


def scored(score: np.ndarray, ahead: np.ndarray) -> float:
    """AUC of the signal against the forward return going the signal's way."""
    up = ahead > 0
    if up.sum() < 50 or (~up).sum() < 50:
        return float("nan")
    return auc(score[up], score[~up])


def main() -> None:
    print(
        f"AUC of the reversion signal against the forward {HORIZON}-bar return,\n"
        "tie-aware, bars spaced by the horizon. Above 0.5 means reversion pays.\n"
        "`twin` is the same cell on block-shuffled bars and is the real baseline,\n"
        "because a trailing-mean score reads well above 0.5 on a surrogate.\n"
        f"There is no 1m data in the cache, so {FRAMES[0]} is the floor.\n"
    )
    best: dict[str, float] = {}
    for frame in FRAMES:
        print(f"--- {frame}, lookback {MAIN_BACK}")
        print(f"  {'class':<18}{'centre':<9}{'n':>8}{'auc':>8}{'twin':>8}{'edge':>8}")
        for label, names in CLASSES:
            for centre in CENTRES:
                got = gather(names, frame, MAIN_BACK, centre)
                if got is None:
                    continue
                score, _, ahead = got
                live = scored(score, ahead)
                twin_got = gather(names, frame, MAIN_BACK, centre, shuffled=True)
                twin = scored(*(twin_got[0], twin_got[2])) if twin_got else float("nan")
                edge = live - twin
                best[f"{frame}|{label}|{centre}"] = edge
                print(
                    f"  {label:<18}{centre:<9}{len(score):>8}{live:>8.4f}{twin:>8.4f}{edge:>+8.4f}"
                )
        print()

    print("the lookback, 15m, edge (live AUC minus twin AUC):")
    print(f"  {'class':<18}{'centre':<9}" + "".join(f"{b:>9d}" for b in BACKS))
    for label, names in CLASSES:
        for centre in CENTRES:
            cells = []
            for back in BACKS:
                got = gather(names, "15m", back, centre)
                twin_got = gather(names, "15m", back, centre, shuffled=True)
                if got is None or twin_got is None:
                    cells.append("        .")
                    continue
                live = scored(got[0], got[2])
                twin = scored(twin_got[0], twin_got[2])
                cells.append(f"{live - twin:>+9.4f}")
            print(f"  {label:<18}{centre:<9}" + "".join(cells))
    print()

    # Volume as a conditioner, which is what combining them has to mean.
    print(f"volume stretch as a conditioner, 15m, lookback {MAIN_BACK}, {STRATA} strata:")
    print(f"  {'class':<18}{'centre':<9}" + "".join(f"{f'v{k}':>9}" for k in range(STRATA)))
    for label, names in CLASSES:
        for centre in CENTRES:
            got = gather(names, "15m", MAIN_BACK, centre)
            twin_got = gather(names, "15m", MAIN_BACK, centre, shuffled=True)
            if got is None or twin_got is None:
                continue
            score, vz, ahead = got
            tscore, tvz, tahead = twin_got
            edges = np.quantile(vz, np.linspace(0.0, 1.0, STRATA + 1))
            cells = []
            for k in range(STRATA):
                lo, hi = edges[k], edges[k + 1]
                pick = (vz >= lo) & (vz <= hi if k == STRATA - 1 else vz < hi)
                tpick = (tvz >= lo) & (tvz <= hi if k == STRATA - 1 else tvz < hi)
                live = scored(score[pick], ahead[pick])
                twin = scored(tscore[tpick], tahead[tpick])
                cells.append(
                    f"{live - twin:>+9.4f}"
                    if np.isfinite(live) and np.isfinite(twin)
                    else "        ."
                )
            print(f"  {label:<18}{centre:<9}" + "".join(cells))
    print(
        "\n  v0 is the lowest volume stretch and the last is the highest, so a\n"
        "  climax story predicts the edge rising across the row. An edge that is\n"
        "  flat across strata means volume adds nothing to the price signal, and\n"
        "  combining them is not worth the second parameter."
    )


if __name__ == "__main__":
    main()
