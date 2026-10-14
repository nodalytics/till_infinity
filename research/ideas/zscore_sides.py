"""The one live thread from the price z-scores: the up/down asymmetry.

`zscore_prices.py` found the pooled readings mechanical - every cell matched by
its block-shuffled twin - but it printed the twin **only for the pooled side**,
and the up/down split was strongly asymmetric. On FX crosses at 1h, a close
stretched 2.5 sigma up read +0.074 and one stretched down read -0.137, in a
convention where the forward return is signed by the stretch's own direction.

A down-stretch reading of -0.137 means price **rose** 0.137 bar-ranges after an
oversold stretch, so the reversion bet is long and earns that gross. Against a
round trip near 0.056 it would net positive. That is the only cell in the run
pointing anywhere, and the harness could not say whether it was mechanical
because the twin was never split the same way.

So that gap is the whole purpose here: **every arm gets its own twin, on its own
side**, plus cost, plus the per-instrument split that a pooled reading over
seven crosses cannot substitute for - a pooled median has already agreed in
this repo with a claim every subgroup refuted.

The bet is stated as the **reversion** bet throughout, because that is the one
the asymmetry suggests: short an up-stretch, long a down-stretch. So a positive
mean here means reversion pays, and it is the negative of the convention used
in `zscore_prices.py`.
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

from zscore_bursts import zed  # noqa: E402
from zscore_prices import pooled  # noqa: E402

CUTS = tuple(float(k) for k in os.environ.get("CUTS", "2.0,2.5,3.0,4.0").split(","))
HORIZONS = tuple(int(k) for k in os.environ.get("HORIZONS", "1,3,6,12").split(","))
MAIN = float(os.environ.get("MAIN", "2.5"))
MAIN_H = int(os.environ.get("MAIN_H", "3"))
MAIN_BACK = int(os.environ.get("MAIN_BACK", "50"))

CROSSES = ("EURJPY", "GBPJPY", "AUDJPY", "CHFJPY", "EURGBP", "EURAUD", "EURCHF")
MAJORS = ("EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD")
PLACEBO = ("Volatility_75_Index", "Volatility_100_Index", "Step_Index")
GROUPS = (("fx crosses", CROSSES), ("fx majors", MAJORS), ("placebo synth", PLACEBO))
KINDS = ("close", "open", "low")


def arm(names, kind, side, cut=MAIN, horizon=MAIN_H, back=MAIN_BACK, shuffled=False):
    """The reversion bet, so the sign is flipped from `zscore_prices`."""
    got, cost = pooled(names, "1h", kind, cut, horizon, back, "crossing", side, shuffled)
    return -got, cost


def main() -> None:
    print(
        f"The REVERSION bet - short an up-stretch, long a down-stretch - at z over\n"
        f"{MAIN} on a {MAIN_BACK}-bar window, held {MAIN_H} bars, in median-bar-range\n"
        "units. Positive means reversion pays. Every arm carries its own twin on\n"
        "its own side, which the previous run did not.\n"
    )
    print(
        f"  {'group':<15}{'kind':<7}{'side':<6}{'n':>6}{'gross':>8}{'cost':>7}"
        f"{'net':>8}{'z':>7}{'hit':>7}{'twin':>8}{'edge':>8}"
    )
    live: list[tuple[str, str, str]] = []
    for label, names in GROUPS:
        for kind in KINDS:
            for side in ("up", "down"):
                got, cost = arm(names, kind, side)
                if len(got) < 30:
                    continue
                twin, _ = arm(names, kind, side, shuffled=True)
                mean = float(np.mean(got))
                twin_mean = float(np.mean(twin)) if len(twin) > 20 else float("nan")
                net = mean - float(np.mean(cost))
                print(
                    f"  {label:<15}{kind:<7}{side:<6}{len(got):>6}{mean:>8.3f}"
                    f"{float(np.mean(cost)):>7.3f}{net:>8.3f}{zed(got):>7.2f}"
                    f"{float(np.mean(got > 0)):>7.3f}{twin_mean:>8.3f}"
                    f"{mean - twin_mean:>8.3f}"
                )
                if label == "fx crosses" and net > 0:
                    live.append((label, kind, side))
    print(
        "\n  `edge` is gross minus the twin: what is left after the surrogate has\n"
        "  taken its share. A cell whose edge is near zero is bar geometry however\n"
        "  large its gross, and the twin is the only column that can say so.\n"
    )
    if not live:
        print("  nothing on the crosses nets positive, so there is nothing to break down.")
        return

    # Per instrument, because seven pooled crosses can hide six flat ones.
    for label, kind, side in live:
        print(f"  {label}, {kind}, {side}-stretch, per instrument:")
        print(f"    {'pair':<9}{'n':>6}{'gross':>8}{'net':>8}{'z':>7}{'twin':>8}")
        for name in CROSSES:
            got, cost = arm((name,), kind, side)
            if len(got) < 25:
                print(f"    {name:<9}{len(got):>6}   too few")
                continue
            twin, _ = arm((name,), kind, side, shuffled=True)
            print(
                f"    {name:<9}{len(got):>6}{float(np.mean(got)):>8.3f}"
                f"{float(np.mean(got) - np.mean(cost)):>8.3f}{zed(got):>7.2f}"
                f"{(float(np.mean(twin)) if len(twin) > 20 else float('nan')):>8.3f}"
            )
        print()

    # And the sweeps, on the mean, with the twin beside it at every step.
    for title, values, which in (
        ("threshold", CUTS, "cut"),
        ("horizon", HORIZONS, "horizon"),
    ):
        print(f"  the {title}, gross then twin then n:")
        print(f"    {'group':<15}{'kind':<7}{'side':<6}" + "".join(f"{v:>9}" for v in values))
        for label, kind, side in live:
            rows: dict[str, list[str]] = {"gross": [], "twin": [], "(n)": []}
            for value in values:
                kwargs = {"cut": value} if which == "cut" else {"horizon": value}
                got, _ = arm(dict(GROUPS)[label], kind, side, **kwargs)
                twin, _ = arm(dict(GROUPS)[label], kind, side, shuffled=True, **kwargs)
                if len(got) >= 30:
                    rows["gross"].append(f"{float(np.mean(got)):>9.3f}")
                    rows["twin"].append(
                        f"{float(np.mean(twin)):>9.3f}" if len(twin) > 20 else "        ."
                    )
                    rows["(n)"].append(f"{len(got):>9d}")
                else:
                    for key in rows:
                        rows[key].append("        .")
            head = f"    {label:<15}{kind:<7}{side:<6}"
            print(head + "".join(rows["gross"]))
            print(f"    {'':<15}{'twin':<7}{'':<6}" + "".join(rows["twin"]))
            print(f"    {'':<15}{'(n)':<7}{'':<6}" + "".join(rows["(n)"]))
        print()


if __name__ == "__main__":
    main()
