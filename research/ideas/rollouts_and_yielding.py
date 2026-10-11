"""Two measurements the library gained today, on real bars.

**One.** Every member here has been scored on held-out likelihood and never on
whether *simulating it forward* produces a series that looks like a market.
TradeFM judges a generative model on exactly that, and `statespace/facts.py`
now does it for any member through the `Filter` protocol: ask for its
predictive distribution, draw from it, feed the draw back.

**Two.** Two fluid-dynamics papers independently say to handle a discontinuity
by *widening* rather than by cutting - shock-aware collocation gates the
physics where it does not hold, and the phase-field branch exists because a
diffuse interface behaves better than a sharp one. `statespace/yielding.py`
widens a member's process noise in proportion to `Changepoint.changepoint`,
which was computed and consumed by nothing. Its null is two-sided: it must beat
the member alone, **and** it must beat `Paired`, which resets.

Runs on the lab.
"""

from __future__ import annotations

import math
import os
from pathlib import Path

from till_infinity.structures.statespace import members
from till_infinity.structures.statespace.facts import measure, rollout, verdict
from till_infinity.structures.statespace.inputs import bar_hours
from till_infinity.structures.statespace.nulls import Walk
from till_infinity.structures.statespace.paired import Paired
from till_infinity.structures.statespace.yielding import Yielding

SYMBOLS = (
    ("eurusd", "EURUSD"),
    ("xauusd", "XAUUSD"),
    ("gbpusd", "GBPUSD"),
    ("usdjpy", "USDJPY"),
    ("v75", "Volatility_75_Index"),
)
FRAMES = ("15m", "1h")

#: Measurement variance in the normalised units, by the `Filter` contract.
NOISE = float(os.environ.get("NOISE", "0.16"))

#: How far `Yielding` may inflate the process noise. Swept rather than trusted.
REACHES = (1.0, 3.0, 10.0, 30.0)

SINCE = float(os.environ.get("SINCE", "1262304000"))  # 2010-01-01
LIMIT = int(os.environ.get("LIMIT", "8000"))


def load(stem: str, frame: str):
    import numpy as np

    path = Path(f"data/seqlab/{stem}.{frame}.npz")
    if not path.exists():
        return None
    with np.load(path) as bundle:
        if not {"time", "close"} <= set(bundle.keys()):
            return None
        order = np.argsort(bundle["time"])
        times = bundle["time"][order].tolist()
        closes = bundle["close"][order].tolist()
    first = 0
    while first < len(times) and times[first] < SINCE:
        first += 1
    times, closes = times[first:], closes[first:]
    if len(closes) > LIMIT:
        times, closes = times[-LIMIT:], closes[-LIMIT:]
    return times, closes


def normalise(prices: list[float]) -> list[float]:
    """Cumulative log return over the series' own bar move. Scale-free."""
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


def rollouts(label: str, frame: str, times: list[float], values: list[float]) -> None:
    """Does each member, run forward, generate something market-shaped?"""
    real = measure(values)
    print(f"  === {label} {frame}: {len(values)} bars ===")
    print(f"    {'real':<12}{real}")

    half = len(values) // 2
    warmup = list(zip(times[:half], values[:half], strict=True))
    ahead = times[half:]
    family = dict(members())
    family["walk"] = Walk
    for name, build in family.items():
        try:
            made = rollout(build, ahead, noise=NOISE, seed=11, warmup=warmup)
        except Exception as exc:
            print(f"    {name:<12}declined: {type(exc).__name__}")
            continue
        got = measure(made)
        print(f"    {name:<12}{got}")
        print(f"    {'':<12}{verdict(real, got)}")
    print()


def softening(label: str, frame: str, times: list[float], values: list[float]) -> None:
    """`Yielding` against the member alone and against `Paired`, which resets."""
    rows = list(zip(times, values, strict=True))
    family = members()
    print(f"  === {label} {frame}: softening against reset ===")
    print(
        f"    {'member':<12}{'alone':>11}{'paired':>11}"
        + "".join(f"{f'reach={r:g}':>12}" for r in REACHES)
    )
    for name, build in family.items():
        if not hasattr(build(), "jerk"):
            continue

        def run(engine):
            for when, value in rows:
                engine.predict(when)
                engine.update(value, NOISE, when)
            return engine

        alone = run(build()).loglike
        pair = run(Paired(build)).loglike
        cells = []
        for reach in REACHES:
            soft = run(Yielding(build, reach=reach))
            cells.append(f"{soft.loglike:>12.1f}")
        print(f"    {name:<12}{alone:>11.1f}{pair:>11.1f}" + "".join(cells))
    print()


def main() -> None:
    print("Rollouts: does a member, simulated forward, look like a market?")
    print("Softening: widening the process noise against resetting the state.")
    print(f"noise={NOISE:g} (variance), reaches {REACHES}.\n")

    print("## 1. Stylized facts of each member's own rollout\n")
    for label, stem in SYMBOLS:
        for frame in FRAMES:
            got = load(stem, frame)
            if got is None or len(got[1]) < 2000:
                continue
            times, closes = got
            if bar_hours(times) <= 0:
                continue
            rollouts(label, frame, times, normalise(closes))

    print("## 2. Softening against resetting, on held-out likelihood\n")
    for label, stem in SYMBOLS:
        for frame in FRAMES:
            got = load(stem, frame)
            if got is None or len(got[1]) < 2000:
                continue
            times, closes = got
            softening(label, frame, times, normalise(closes))

    print("Reading it:")
    print("  A member whose rollout has NO clustering is a good local density")
    print("  and a false description - this desk's own measurements say")
    print("  volatility is the one forecastable quantity here.")
    print("  reach=1 is the member exactly, so it is the control for the")
    print("  wrapper rather than for the softening.")


if __name__ == "__main__":
    main()
