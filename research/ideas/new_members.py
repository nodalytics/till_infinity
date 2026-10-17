"""The members added today, on the real instruments, with volume.

`fractional`, `switching` and `panel` were built against synthetic fixtures
that each isolated the thing the member was for. That is the right way to
build them and no evidence at all about markets, so this is the part that
decides whether any of them is worth keeping.

Four comparisons, each against a null the package already insists on:

1. **Every member on held-out likelihood**, per instrument, against `linear`
   and against `nulls.Walk`. A member with more states has to earn them.
2. **Volume through `Q`**, which is the door the evidence points at.
   `driven.Driven` scales a member's process noise by an exogenous input;
   the input is log volume against its own trailing mean. Its null is the
   **same member with `gain = 0`**, which is the member exactly - so the
   comparison measures the input rather than the wrapper.
3. **`panel` against independent members.** A factor model has to beat `n`
   separate filters on the same readings, or the factor is decoration.
4. **`switching`'s balance reading on the synthetics**, which are generated
   and have no auction. A reading that is the same there is a reading of the
   model rather than of the market.

Held out by **time**: fit nothing, score the back 40% of every series, with
the likelihood zeroed at the boundary so the warm-up does not count.

Runs on the lab.
"""

from __future__ import annotations

import math
import os
import statistics
from pathlib import Path

from till_infinity.statespace.driven import Driven
from till_infinity.statespace.fractional import Fractional
from till_infinity.statespace.inputs import bar_hours, coverage
from till_infinity.statespace.linear import Gaussian
from till_infinity.statespace.nulls import Walk, trailing
from till_infinity.statespace.panel import Panel
from till_infinity.statespace.reverting import Reverting
from till_infinity.statespace.switching import Switching

SYMBOLS = (
    ("eurusd", "EURUSD"),
    ("xauusd", "XAUUSD"),
    ("gbpusd", "GBPUSD"),
    ("usdjpy", "USDJPY"),
    ("btcusd", "BTCUSD"),
    ("v75", "Volatility_75_Index"),
)
FRAME = os.environ.get("FRAME", "1h")

NOISE = float(os.environ.get("NOISE", "0.16"))
SHARE = 0.6
SINCE = float(os.environ.get("SINCE", "1262304000"))
LIMIT = int(os.environ.get("LIMIT", "12000"))

#: How hard the volume input is allowed to drive the process noise. Swept,
#: with zero as the control arm - which reproduces the member exactly.
GAINS = (0.0, 0.5, 2.0)


def load(stem: str, frame: str):
    import numpy as np

    path = Path(f"data/seqlab/{stem}.{frame}.npz")
    if not path.exists():
        return None
    with np.load(path) as bundle:
        keys = set(bundle.keys())
        if not {"time", "close"} <= keys:
            return None
        order = np.argsort(bundle["time"])
        times = bundle["time"][order].tolist()
        closes = bundle["close"][order].tolist()
        volumes = bundle["volume"][order].tolist() if "volume" in keys else [0.0] * len(order)
    first = 0
    while first < len(times) and times[first] < SINCE:
        first += 1
    times, closes, volumes = times[first:], closes[first:], volumes[first:]
    if len(closes) > LIMIT:
        times, closes, volumes = times[-LIMIT:], closes[-LIMIT:], volumes[-LIMIT:]
    return times, closes, volumes


def normalise(prices: list[float]) -> list[float]:
    alpha = 1.0 - 0.5 ** (1.0 / 60.0)
    average = 0.0
    steps = [0.0]
    for i in range(1, len(prices)):
        step = (
            math.log(prices[i] / prices[i - 1]) * 10_000
            if prices[i] > 0 and prices[i - 1] > 0
            else 0.0
        )
        steps.append(step)
        average = abs(step) if i == 1 else average + alpha * (abs(step) - average)
    unit = max(average, 0.25)
    out, running = [], 0.0
    for step in steps:
        running += step / unit
        out.append(running)
    return out


def held_out(build, times, values, cut, control=None) -> float:
    """Log-likelihood over the back of the series only."""
    engine = build()
    for i, (when, value) in enumerate(zip(times, values, strict=True)):
        if control is None:
            engine.predict(when)
        else:
            engine.predict(when, control=control[i])
        engine.update(value, NOISE, when)
        if i == cut - 1:
            engine.loglike = 0.0
    return float(engine.loglike)


def volume_input(volumes: list[float], span: int) -> list[float] | None:
    """Log volume against its own trailing mean. `None` without real volume."""
    if sum(1 for v in volumes if v > 0) < 0.9 * len(volumes):
        return None
    logv = [math.log(v) if v > 0 else 0.0 for v in volumes]
    spread = trailing(logv, span)
    out, run = [], 0.0
    for k, value in enumerate(logv):
        run += value
        if k >= span:
            run -= logv[k - span]
        mean = run / min(k + 1, span)
        out.append((value - mean) / max(spread[k], 1e-9) if spread[k] > 0 else 0.0)
    return out


def members_table(loaded: dict) -> None:
    """Section one: every member on held-out likelihood."""
    print("## 1. Every member, held-out log-likelihood\n")
    print(
        f"  {'instrument':<10}{'walk':>10}{'linear':>10}{'reverting':>11}"
        f"{'fractional':>12}{'switching':>11}"
    )
    for label, (times, values, _vol, _bar, _cov) in loaded.items():
        cut = int(len(values) * SHARE)
        row = [
            held_out(lambda: Walk(noise=0.4), times, values, cut),
            held_out(lambda: Gaussian(jerk=1e-4), times, values, cut),
            held_out(Reverting, times, values, cut),
            held_out(Fractional, times, values, cut),
            held_out(Switching, times, values, cut),
        ]
        widths = (10, 10, 11, 12, 11)
        cells = "".join(f"{v:>{w}.0f}" for v, w in zip(row, widths, strict=True))
        print(f"  {label:<10}{cells}")


def volume_table(loaded: dict) -> None:
    """Section two: volume through `Q`, against gain zero."""
    print("\n## 2. Volume through `Q`: `Driven`, against gain zero\n")
    print(f"  {'instrument':<10}" + "".join(f"{f'gain={g:g}':>12}" for g in GAINS))
    for label, (times, values, volumes, bar, cover) in loaded.items():
        span = max(round(24.0 * cover / bar), 2)
        driver = volume_input(volumes, span)
        if driver is None:
            print(f"  {label:<10}{'no real volume':>36}")
            continue
        cut = int(len(values) * SHARE)
        cells = [
            held_out(
                lambda g=g: Driven(lambda: Gaussian(jerk=1e-4), gain=g),
                times,
                values,
                cut,
                control=driver,
            )
            for g in GAINS
        ]
        print(f"  {label:<10}" + "".join(f"{v:>12.0f}" for v in cells))


def panel_table(loaded: dict) -> None:
    """Section three: the panel against independent members."""
    print("\n## 3. `panel` against independent members, same readings\n")
    names = sorted(loaded)
    stamps = sorted(set.intersection(*(set(loaded[n][0]) for n in names)))
    if len(stamps) > 4000:
        stamps = stamps[-4000:]
    if len(stamps) <= 500:
        print("  not enough overlapping history")
        return
    table = {n: dict(zip(loaded[n][0], loaded[n][1], strict=True)) for n in names}
    rows = [[table[n][t] for n in names] for t in stamps]
    cut = int(len(stamps) * SHARE)
    panel = Panel(size=len(names), wander=1e-2, idio_wander=1e-3, theta=0.05)
    for i, (when, reading) in enumerate(zip(stamps, rows, strict=True)):
        panel.predict(when)
        panel.update(reading, NOISE, when)
        if i == cut - 1:
            panel.loglike = 0.0
    separate = sum(
        held_out(lambda: Gaussian(jerk=1e-4), stamps, [r[k] for r in rows], cut)
        for k in range(len(names))
    )
    print(f"  instruments {len(names)}, bars {len(stamps)}")
    print(f"  panel (one factor)      {panel.loglike:>12.0f}")
    print(f"  {len(names)} independent linear    {separate:>12.0f}")
    print(f"  half-life of a dislocation: {panel.half_life():.1f}h")


def balance_table(loaded: dict) -> None:
    """Section four: is the balance reading a market or a model?"""
    print("\n## 4. `switching`: is the balance reading a market or a model?\n")
    print(f"  {'instrument':<12}{'share of time in balance':>26}")
    for label, (times, values, _vol, _bar, _cov) in loaded.items():
        engine = Switching()
        seen = []
        for when, value in zip(times, values, strict=True):
            engine.predict(when)
            engine.update(value, NOISE, when)
            seen.append(engine.balance)
        tail = seen[len(seen) // 2 :]
        print(f"  {label:<12}{statistics.fmean(tail):>26.3f}")
    print("\n  v75 is generated and has no auction. A reading that matches")
    print("  it is a reading of the model rather than of the market.")


def main() -> None:
    print("The members added today, on real instruments, with volume.")
    print(f"{FRAME} bars, held out by time: the back {1 - SHARE:.0%} is scored.")
    print("Higher is better; every number is a log-likelihood on the same")
    print("readings, so they are comparable down a column.\n")

    loaded = {}
    for label, stem in SYMBOLS:
        got = load(stem, FRAME)
        if got is None or len(got[1]) < 3000:
            continue
        times, closes, volumes = got
        bar = bar_hours(times)
        if bar <= 0:
            continue
        loaded[label] = (times, normalise(closes), volumes, bar, coverage(times, bar))

    members_table(loaded)
    volume_table(loaded)
    panel_table(loaded)
    balance_table(loaded)


if __name__ == "__main__":
    main()
