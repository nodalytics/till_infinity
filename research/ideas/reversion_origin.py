"""The stretch signal against a **level** target: the displacement origin.

Every reversion measurement so far has used a fixed-horizon return as the
target, and the answer was AUC 0.518 raw with two thirds of the excess
reproduced by a block-shuffled surrogate. A fixed-horizon return is a demanding
target for a reversion signal, though, because it asks where price will be at
an arbitrary bar rather than whether it gets somewhere.

So the target changes to a **price**, and the price is the one this repo has
already measured: the **displacement origin**. `order-block-zones.md` recorded
an 82% arrival rate within 300 bars, and `fade-to-value-targets-the-displacement-
origin` records what that figure is and is not - a target hit rate, never an
entry signal. That is exactly the gap this fills: the origin says *where*, and
the question here is whether a stretch signal says *when*.

## The target

A zone is built on production's own definition, with its constants asserted
against the source: `PUSH_BODY` 0.65 over `PUSH_N` 2 one-sided bars of one
colour, an origin bar whose body is between 10% and 60% of its range, and the
line at that body's far edge. A zone stays live until price touches it or it
ages out.

The target is **arrival at the live line within the horizon**, which is binary,
and the base rate is printed because an 82% target over 300 bars would make any
AUC meaningless - at a short horizon it has to be moderate to be measurable.

## The signal has to be pointed at the line

A reversion signal says price returns toward its centre. That only predicts
arrival at the origin if the origin lies on the centre's side, so the score is
the stretch **signed toward the line**: `-z * sign(line - price)`. Stretched
below the centre with the line above scores high; stretched below with the line
below scores low. Without that the signal and the target are describing
different directions half the time.

## Controls

The block-shuffled twin, which recomputes its zones on the shuffled bars so
both the signal and the target are surrogate - a twin that kept the real zones
would be testing something else. Deriv synthetics as subjects. And the two
conditioners asked for beside the volume stretch: **price velocity against
ATR**, which asks whether a fast approach behaves differently from a slow one.
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

from level_signatures import auc, shuffle_blocks  # noqa: E402
from reversion_clock import HOURS, SPANS, classes, deviation, rolling_sum  # noqa: E402
from screen import load  # noqa: E402

# Production's constants, asserted against the source in `origin_placebo.py`.
PUSH_BODY, PUSH_N = 0.65, 2
ORIGIN_BODY_MIN, ORIGIN_BODY_MAX = 0.10, 0.60

FRAMES = tuple(os.environ.get("FRAMES", "15m,1h").split(","))
SPAN = os.environ.get("SPAN", "2d")
HORIZONS = tuple(int(k) for k in os.environ.get("HORIZONS", "12,24,48").split(","))
MAIN_H = int(os.environ.get("MAIN_H", "24"))
AGE = int(os.environ.get("AGE", "300"))
CENTRES = ("mean", "regress")
SCALES = ("sd", "mad")
STRATA = int(os.environ.get("STRATA", "3"))
STEP = int(os.environ.get("STEP", "8"))


def origins(bars: dict) -> list[tuple[int, float, bool]]:
    """`(bar, line, up)` for every displacement origin, production's definition."""
    o, h, l_, c = bars["open"], bars["high"], bars["low"], bars["close"]
    out: list[tuple[int, float, bool]] = []
    for at in range(1, len(c) - PUSH_N - 1):
        bodies = []
        for k in range(PUSH_N):
            i = at + k
            span = float(h[i] - l_[i])
            if span <= 0:
                break
            bodies.append((float(c[i]) - float(o[i])) / span)
        if len(bodies) < PUSH_N or not all(abs(b) >= PUSH_BODY for b in bodies):
            continue
        if len({b > 0 for b in bodies}) != 1:
            continue
        up = bodies[0] > 0
        oi = at - 1
        span = float(h[oi] - l_[oi])
        if span <= 0:
            continue
        share = abs(float(c[oi]) - float(o[oi])) / span
        if not (ORIGIN_BODY_MIN <= share <= ORIGIN_BODY_MAX):
            continue
        body_low = min(float(o[oi]), float(c[oi]))
        body_high = max(float(o[oi]), float(c[oi]))
        out.append((at + PUSH_N - 1, body_low if up else body_high, up))
    return out


def live_line(found, at: int, used: set[int]) -> tuple[float, bool] | None:
    """The newest zone born before `at`, still unused and not aged out."""
    best = None
    for k, (born, line, up) in enumerate(found):
        if born >= at or k in used or at - born > AGE:
            continue
        if best is None or born > found[best][0]:
            best = k
    if best is None:
        return None
    return found[best][1], found[best][2]


def panel(bars: dict, back: int, centre: str, scale: str, horizon: int):
    """`(score, arrived, volume stretch, velocity)` at spaced bars."""
    price = np.log(np.maximum((bars["high"] + bars["low"] + bars["close"]) / 3.0, 1e-12))
    if len(price) < back + horizon + 500:
        return None
    at = np.arange(back - 1, len(price) - horizon, STEP)
    if len(at) < 300:
        return None
    z = deviation(price, back, centre, scale, at)
    vz = deviation(bars["volume"].astype(float), back, centre, scale, at)
    # Velocity against ATR: how fast the last few bars moved, in range units.
    span = bars["high"] - bars["low"]
    atr = rolling_sum(span, back) / back
    moved = np.abs(np.concatenate((np.zeros(5), bars["close"][5:] - bars["close"][:-5])))
    with np.errstate(invalid="ignore", divide="ignore"):
        pace = np.where(atr > 0, moved / atr, np.nan)

    found = origins(bars)
    if len(found) < 40:
        return None
    high, low, close = bars["high"], bars["low"], bars["close"]
    used: set[int] = set()
    scores, flags, vols, paces = [], [], [], []
    for k, i in enumerate(at):
        i = int(i)
        got = live_line(found, i, used)
        if got is None or not np.isfinite(z[k]):
            continue
        line, _ = got
        here = float(close[i])
        toward = 1.0 if line > here else -1.0
        window = slice(i + 1, i + 1 + horizon)
        arrived = bool((high[window] >= line).any() if toward > 0 else (low[window] <= line).any())
        scores.append(-z[k] * toward)
        flags.append(arrived)
        vols.append(vz[k] if np.isfinite(vz[k]) else 0.0)
        paces.append(pace[i] if np.isfinite(pace[i]) else 0.0)
    if len(scores) < 300:
        return None
    return (
        np.asarray(scores),
        np.asarray(flags),
        np.asarray(vols),
        np.asarray(paces),
    )


def gather(names, frame, back, centre, scale, horizon, shuffled=False):
    rng = np.random.default_rng(13)
    parts = [[], [], [], []]
    for name in names:
        bars = load(name, frame)
        if bars is None:
            continue
        if shuffled:
            bars = shuffle_blocks(bars, rng)
        got = panel(bars, back, centre, scale, horizon)
        if got is None:
            continue
        for slot, piece in zip(parts, got):
            slot.append(piece)
    if not parts[0]:
        return None
    return tuple(np.concatenate(slot) for slot in parts)


def scored(score: np.ndarray, flags: np.ndarray) -> float:
    if flags.sum() < 50 or (~flags).sum() < 50:
        return float("nan")
    return auc(score[flags], score[~flags])


def main() -> None:
    print(
        "AUC of the stretch signal, pointed at the line, against arrival at a live\n"
        f"displacement origin within the horizon. Span {SPAN}, bars stepped {STEP}.\n"
        "`base` is the arrival rate - an AUC means nothing beside a base rate of\n"
        "0.02 or 0.98. `twin` recomputes its zones on shuffled bars, so both the\n"
        "signal and the target are surrogate there.\n"
    )
    for frame in FRAMES:
        back = int(dict(SPANS)[SPAN] / HOURS[frame])
        print(f"--- {frame}, span {SPAN} = {back} bars, horizon {MAIN_H}")
        print(
            f"  {'class':<18}{'centre':<9}{'scale':<6}{'n':>7}"
            f"{'base':>7}{'auc':>8}{'twin':>8}{'edge':>8}"
        )
        for label, names in classes(frame):
            if not names:
                continue
            for centre in CENTRES:
                for scale in SCALES:
                    live = gather(names, frame, back, centre, scale, MAIN_H)
                    twin = gather(names, frame, back, centre, scale, MAIN_H, shuffled=True)
                    if live is None or twin is None:
                        continue
                    a = scored(live[0], live[1])
                    b = scored(twin[0], twin[1])
                    if not (np.isfinite(a) and np.isfinite(b)):
                        continue
                    print(
                        f"  {label:<18}{centre:<9}{scale:<6}{len(live[0]):>7}"
                        f"{float(np.mean(live[1])):>7.3f}{a:>8.4f}{b:>8.4f}{a - b:>+8.4f}"
                    )
        print()

    print(f"the horizon, 15m, span {SPAN}. base then edge:")
    back = int(dict(SPANS)[SPAN] / HOURS["15m"])
    print(f"  {'class':<18}{'centre':<9}{'scale':<6}" + "".join(f"{f'h={h}':>9}" for h in HORIZONS))
    for label, names in classes("15m"):
        if not names:
            continue
        for centre in CENTRES:
            for scale in SCALES:
                bases, edges = [], []
                for horizon in HORIZONS:
                    live = gather(names, "15m", back, centre, scale, horizon)
                    twin = gather(names, "15m", back, centre, scale, horizon, shuffled=True)
                    if live is None or twin is None:
                        bases.append("        .")
                        edges.append("        .")
                        continue
                    a, b = scored(live[0], live[1]), scored(twin[0], twin[1])
                    bases.append(f"{float(np.mean(live[1])):>9.3f}")
                    edges.append(
                        f"{a - b:>+9.4f}" if np.isfinite(a) and np.isfinite(b) else "        ."
                    )
                if all(e.strip() == "." for e in edges):
                    continue
                print(f"  {label:<18}{centre:<9}{scale:<6}" + "".join(edges))
                print(f"  {'':<18}{'(base)':<9}{'':<6}" + "".join(bases))
    print()

    print(f"conditioners, 15m, span {SPAN}, horizon {MAIN_H}, {STRATA} strata, edge:")
    for which, slot in (("volume stretch", 2), ("velocity / ATR", 3)):
        print(f"  {which}:")
        print(
            f"    {'class':<18}{'centre':<9}{'scale':<6}"
            + "".join(f"{f'q{k}':>9}" for k in range(STRATA))
        )
        for label, names in classes("15m"):
            if not names:
                continue
            for centre in CENTRES:
                for scale in SCALES:
                    live = gather(names, "15m", back, centre, scale, MAIN_H)
                    twin = gather(names, "15m", back, centre, scale, MAIN_H, shuffled=True)
                    if live is None or twin is None:
                        continue
                    bounds = np.quantile(live[slot], np.linspace(0.0, 1.0, STRATA + 1))
                    cells = []
                    for k in range(STRATA):
                        lo, hi = bounds[k], bounds[k + 1]
                        last = k == STRATA - 1
                        pick = (live[slot] >= lo) & (live[slot] <= hi if last else live[slot] < hi)
                        tpick = (twin[slot] >= lo) & (twin[slot] <= hi if last else twin[slot] < hi)
                        a = scored(live[0][pick], live[1][pick])
                        b = scored(twin[0][tpick], twin[1][tpick])
                        cells.append(
                            f"{a - b:>+9.4f}" if np.isfinite(a) and np.isfinite(b) else "        ."
                        )
                    print(f"    {label:<18}{centre:<9}{scale:<6}" + "".join(cells))
    print(
        "\n  q0 is the lowest stratum. The origin says where price is going; the\n"
        "  question here is whether a stretch says when, and the twin is what\n"
        "  separates that from the fact that a stretched price is nearer the line."
    )


if __name__ == "__main__":
    main()
