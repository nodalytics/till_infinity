"""How far does price stretch before it comes back to the displacement origin?

The return rate to a displacement origin is **82% within 300 bars**, and
`fade-to-value-targets-the-displacement-origin` records exactly what that
figure is: a target hit rate, never an entry signal. The origin says *where*
price is going. It says nothing about *when*, or about how far price gets first.

That second question has a direct answer and this measures it. **At the turn -
the bar of maximum distance from the origin before price comes back - what is
the z-score?** If excursions reliably turn at z near some value, that value is
an entry threshold **derived from the data** rather than picked, which is how
every z-threshold in this repo has been chosen until now.

## The duration confound, which decides whether this means anything

A running maximum only grows, so an excursion that returns in five bars has had
five bars to reach a high z and one that takes two hundred has had two hundred.
Comparing them raw would find that slow returns reach higher z-scores and that
would be arithmetic, not a finding. Two things handle it:

- the headline is the z **at the turn**, which is a single well-defined bar per
  excursion rather than a running maximum over a window of varying length;
- every table is also split by **time to return**, so a reading is only ever
  compared against excursions of the same duration.

## Returners against non-returners

The 18% that never come back are the control that matters most. If they reach
the same z-scores as the returners, then the z-score says nothing about
*whether* price returns - it can still say when, but the distinction has to be
made rather than assumed. Both arms are capped at the same window so the
comparison is fair.

## The windows

Both kinds, because the z-score's own window is a free parameter and the right
one is not obvious: **bar counts** of 50, 100, 200 and 300, and **spans** of 1
day, 1 week and 2 weeks converted per frame, where a day is 24 trading hours
and a week is five of them. The return window itself is held at the established
300 bars and swept separately.
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
from reversion_clock import HOURS, deviation  # noqa: E402
from screen import load  # noqa: E402

PUSH_BODY, PUSH_N = 0.65, 2
ORIGIN_BODY_MIN, ORIGIN_BODY_MAX = 0.10, 0.60

FRAMES = tuple(os.environ.get("FRAMES", "15m,1h,4h").split(","))
RETURN_BARS = int(os.environ.get("RETURN_BARS", "300"))
RETURNS = tuple(int(k) for k in os.environ.get("RETURNS", "50,100,300,500").split(","))
BAR_WINDOWS = tuple(int(k) for k in os.environ.get("BAR_WINDOWS", "50,100,200,300").split(","))
TIME_WINDOWS = (("1d", 24.0), ("1w", 120.0), ("2w", 240.0))
MAIN_WINDOW = int(os.environ.get("MAIN_WINDOW", "100"))
BUCKETS = ((1, 10), (11, 30), (31, 100), (101, 300))

CLASSES = (
    ("fx majors", ("EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD")),
    ("fx crosses", ("EURJPY", "GBPJPY", "AUDJPY", "CHFJPY", "EURGBP", "EURAUD", "EURCHF")),
    ("metals", ("XAUUSD", "XAGUSD")),
    ("synth volatility", ("Volatility_75_Index", "Volatility_100_Index")),
)


def origins(bars: dict):
    """`(start, line, band_low, band_high, up)` - production's definition."""
    o, h, l_, c = bars["open"], bars["high"], bars["low"], bars["close"]
    out = []
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
        out.append((at + PUSH_N - 1, float(l_[oi]), float(h[oi]), up))
    return out


def excursions(bars: dict, back: int, cap: int):
    """One row per displacement: how far it stretched, and whether it came back."""
    h, l_, c = bars["high"], bars["low"], bars["close"]
    price = np.log(np.maximum((h + l_ + c) / 3.0, 1e-12))
    if len(price) < back + cap + 50:
        return []
    at = np.arange(back - 1, len(price))
    z = deviation(price, back, "mean", "sd", at)
    lookup = np.full(len(price), np.nan)
    lookup[at] = z
    span = np.median(h - l_)
    if not span > 0:
        return []
    rows = []
    for start, band_low, band_high, up in origins(bars):
        if start < back or start + cap >= len(c):
            continue
        # The excursion runs until price re-enters the origin's own band.
        back_in = None
        reach, turn = 0.0, start
        for i in range(start + 1, start + cap + 1):
            if up:
                gone = (float(h[i]) - band_high) / span
                if float(l_[i]) <= band_high:
                    back_in = i - start
                    break
            else:
                gone = (band_low - float(l_[i])) / span
                if float(h[i]) >= band_low:
                    back_in = i - start
                    break
            if gone > reach:
                reach, turn = gone, i
        here = lookup[turn]
        if not np.isfinite(here):
            continue
        rows.append(
            {
                "returned": back_in is not None,
                "bars": back_in if back_in is not None else cap,
                # Signed away from the origin, so a bigger number is a further
                # stretch regardless of the displacement's direction.
                "z_turn": float(here if up else -here),
                "reach": float(reach),
            }
        )
    return rows


def collect(names, frame, back, cap, shuffled=False):
    rng = np.random.default_rng(13)
    rows = []
    for name in names:
        bars = load(name, frame)
        if bars is None:
            continue
        if shuffled:
            bars = shuffle_blocks(bars, rng)
        rows.extend(excursions(bars, back, cap))
    return rows


def quantiles(got: list[float]) -> str:
    if len(got) < 30:
        return "        too few"
    arr = np.asarray(got)
    return (
        f"{np.quantile(arr, 0.25):>8.2f}{np.median(arr):>8.2f}"
        f"{np.quantile(arr, 0.75):>8.2f}{np.quantile(arr, 0.90):>8.2f}"
    )


def main() -> None:
    print(
        f"The z-score at the **turn** - the bar of furthest distance from the origin\n"
        f"before price comes back into its band - within {RETURN_BARS} bars, which is\n"
        "the established window. Signed away from the origin, so bigger is a further\n"
        "stretch whichever way the displacement went.\n"
    )
    for frame in FRAMES:
        print(f"--- {frame}, z window {MAIN_WINDOW} bars, return window {RETURN_BARS}")
        print(
            f"  {'class':<18}{'arm':<14}{'n':>6}{'rate':>7}{'q25':>8}{'med':>8}{'q75':>8}{'q90':>8}"
        )
        for label, names in CLASSES:
            rows = collect(names, frame, MAIN_WINDOW, RETURN_BARS)
            if len(rows) < 60:
                continue
            came = [r for r in rows if r["returned"]]
            never = [r for r in rows if not r["returned"]]
            rate = len(came) / len(rows)
            print(
                f"  {label:<18}{'returned':<14}{len(came):>6}{rate:>7.3f}"
                + quantiles([r["z_turn"] for r in came])
            )
            if len(never) >= 30:
                print(
                    f"  {'':<18}{'never returned':<14}{len(never):>6}{'':>7}"
                    + quantiles([r["z_turn"] for r in never])
                )
            # Would a z threshold have caught them at all?
            for cut in (2.0, 2.5, 3.0):
                share = float(np.mean([r["z_turn"] >= cut for r in came]))
                print(f"  {'':<18}{f'reached z {cut:g}':<14}{'':>6}{share:>7.3f}", end="")
                print()
        print()

    print(f"by time to return, 1h, z window {MAIN_WINDOW}. median z at the turn:")
    print(f"  {'class':<18}" + "".join(f"{f'{a}-{b}':>10}" for a, b in BUCKETS))
    for label, names in CLASSES:
        rows = collect(names, "1h", MAIN_WINDOW, RETURN_BARS)
        came = [r for r in rows if r["returned"]]
        if len(came) < 60:
            continue
        cells = []
        for lo, hi in BUCKETS:
            picked = [r["z_turn"] for r in came if lo <= r["bars"] <= hi]
            cells.append(f"{np.median(picked):>10.2f}" if len(picked) >= 20 else "         .")
        print(f"  {label:<18}" + "".join(cells))
    print()

    print("the z window, 1h. median z at the turn for returners:")
    labels = [str(b) for b in BAR_WINDOWS] + [s for s, _ in TIME_WINDOWS]
    print(f"  {'class':<18}" + "".join(f"{v:>9}" for v in labels))
    for label, names in CLASSES:
        cells = []
        for back in BAR_WINDOWS:
            came = [r for r in collect(names, "1h", back, RETURN_BARS) if r["returned"]]
            cells.append(
                f"{np.median([r['z_turn'] for r in came]):>9.2f}"
                if len(came) >= 30
                else "        ."
            )
        for _, hours in TIME_WINDOWS:
            back = int(hours / HOURS["1h"])
            came = [r for r in collect(names, "1h", back, RETURN_BARS) if r["returned"]]
            cells.append(
                f"{np.median([r['z_turn'] for r in came]):>9.2f}"
                if len(came) >= 30
                else "        ."
            )
        print(f"  {label:<18}" + "".join(cells))
    print()

    print("does the stretch predict whether it returns? AUC of z at the turn:")
    print(f"  {'class':<18}" + "".join(f"{r:>9}" for r in RETURNS) + f"{'twin':>9}")
    for label, names in CLASSES:
        cells = []
        for cap in RETURNS:
            rows = collect(names, "1h", MAIN_WINDOW, cap)
            came = np.array([r["z_turn"] for r in rows if r["returned"]])
            never = np.array([r["z_turn"] for r in rows if not r["returned"]])
            cells.append(
                f"{auc(came, never):>9.4f}" if len(came) >= 30 and len(never) >= 30 else "        ."
            )
        rows = collect(names, "1h", MAIN_WINDOW, RETURN_BARS, shuffled=True)
        came = np.array([r["z_turn"] for r in rows if r["returned"]])
        never = np.array([r["z_turn"] for r in rows if not r["returned"]])
        cells.append(
            f"{auc(came, never):>9.4f}" if len(came) >= 30 and len(never) >= 30 else "        ."
        )
        print(f"  {label:<18}" + "".join(cells))
    print(
        "\n  A median z at the turn near some value is an entry threshold the data\n"
        "  chose. The share reaching 2.0, 2.5 and 3.0 says what a threshold that\n"
        "  high would miss. And if returners and non-returners reach the same z,\n"
        "  the stretch says when and not whether."
    )


if __name__ == "__main__":
    main()
