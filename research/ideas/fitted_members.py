"""Fit the members, then judge them. The comparison that was missing.

`research/docs/statespace-new-members-measured.md` scored every member on real
instruments and the walk won nearly everywhere - but **none of them was
fitted**. `fractional` carries five modes at a `wander` of 1e-3 chosen to make
a synthetic fixture behave; `switching` asserts regime durations of 24h and 4h;
`panel` asserts a reversion rate. A member with five states and an unfitted
noise is not a model class being tested, it is a member shown unusable as
shipped, which is a different and much smaller claim.

So: fit each member's own parameters on the **training** period by maximum
likelihood, then score the back of the series. Same split, same readings, same
null.

## Coordinate ascent, and why not something cleverer

`diagnostics.fit_jerk` is a golden-section search on one parameter in log
space, and `fit_both` alternates two of them. This generalises that to a named
dictionary: search each parameter in turn with the others held, repeat until
nothing moves. It maximises the **exact** likelihood rather than a bound, each
round cannot decrease it, and it crawls along diagonal ridges - which is the
known cost and the reason `rounds` is capped.

Everything is searched in `log10`, because these parameters span orders of
magnitude and a linear bracket would spend its whole budget in the wrong
decade.

## The three comparisons

* **fitted against default** - how much of each member's showing was the
  parameters rather than the model.
* **fitted against the walk** - the null that has beaten everything.
* **fitted against `linear` fitted** - a member with more states has to earn
  them against the simplest one that was given the same treatment.

Runs on the lab.
"""

from __future__ import annotations

import math
import os
from pathlib import Path

from till_infinity.statespace.diagnostics import fit_jerk
from till_infinity.statespace.fractional import Fractional
from till_infinity.statespace.inputs import bar_hours
from till_infinity.statespace.linear import Gaussian
from till_infinity.statespace.nulls import Walk
from till_infinity.statespace.oscillator import Oscillator
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
LIMIT = int(os.environ.get("LIMIT", "8000"))

#: Rounds of coordinate ascent. Capped because the ridge is diagonal.
ROUNDS = 3

#: Each member, and the parameters to fit with their `log10` brackets.
#: **Durations are in hours** and noises are spectral densities, so the
#: brackets differ in kind as well as in range.
#: **The null is fitted too, and the first run of this did not do that.**
#: Scoring fitted members against a walk whose `noise` was asserted at 0.4 is
#: not a comparison - it hands every member a parameter search and the null
#: none. The walk has exactly one parameter and it gets the same treatment.
WALK_GRID = {"noise": (-2.0, 1.5)}

#: Brackets widened after the first run **pinned three of them**: `jerk` at
#: the top (0.987 against a ceiling of 1.0), `theta` at the bottom (0.0101
#: against a floor of 0.01) and `slowest` near the top (986 of 1000). A
#: parameter at the edge of its grid is not a fit, it is a grid - and this
#: package has the scar: every `selective` and `swarm` fit pinned `drift` at
#: the top of its grid, and the limit of that family turned out to be the
#: random walk.
GRIDS: dict[str, tuple] = {
    "linear": (Gaussian, {"jerk": (-8.0, 3.0)}),
    "reverting": (Reverting, {"theta": (-4.0, 1.0)}),
    "fractional": (Fractional, {"wander": (-6.0, 3.0), "slowest": (1.0, 4.0)}),
    # The damped harmonic oscillator. **Two parameters and they are not
    # independent**: `zeta = gamma / (2 omega)` is the thing that matters, so
    # fitting both separately searches a ridge. Fitted anyway, because the
    # alternative is asserting one of them.
    "oscillator": (
        Oscillator,
        {"omega": (-3.0, 1.0), "gamma": (-3.0, 1.0), "forcing": (-6.0, 2.0)},
    ),
    "switching": (
        Switching,
        {
            "balance_hours": (0.0, 2.5),
            "imbalance_hours": (-0.5, 2.0),
            "theta": (-4.0, 1.0),
        },
    ),
}


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


def score(build, times, values, first, last) -> float:
    """Log-likelihood over `[first, last)`, zeroed at the boundary."""
    engine = build()
    for i in range(last):
        engine.predict(times[i])
        engine.update(values[i], NOISE, times[i])
        if i == first - 1:
            engine.loglike = 0.0
    return float(engine.loglike)


def fit(make, grid: dict, times, values, cut) -> dict:
    """Coordinate ascent on the training period. Returns the parameters."""
    chosen = {name: 10.0 ** ((lo + hi) / 2.0) for name, (lo, hi) in grid.items()}
    best = -math.inf
    for _ in range(ROUNDS):
        moved = False
        for name, (lo, hi) in grid.items():

            def run(value: float, _name=name) -> float:
                trial = dict(chosen)
                trial[_name] = value
                try:
                    return score(lambda: make(**trial), times, values, 0, cut)
                except (ValueError, ZeroDivisionError, OverflowError):
                    return -math.inf

            got, like = fit_jerk(run, low=lo, high=hi, tolerance=0.02)
            if like > best + 0.5:
                best = like
                chosen[name] = got
                moved = True
            else:
                chosen[name] = got
        if not moved:
            break
    return chosen


def main() -> None:
    print("Fit the members, then judge them.")
    print(f"{FRAME} bars, fitted on the front {SHARE:.0%}, scored on the back.")
    print("'default' is the member as shipped; 'fitted' is the same member")
    print("with its own parameters chosen by likelihood on the training")
    print("period only. The walk is the null that has beaten everything.\n")

    for label, stem in SYMBOLS:
        got = load(stem, FRAME)
        if got is None or len(got[1]) < 3000:
            continue
        times, closes = got
        if bar_hours(times) <= 0:
            continue
        values = normalise(closes)
        cut = int(len(values) * SHARE)

        chosen_walk = fit(Walk, WALK_GRID, times, values, cut)
        walk = score(lambda _p=chosen_walk: Walk(**_p), times, values, cut, len(values))
        plain = score(lambda: Walk(noise=0.4), times, values, cut, len(values))
        print(
            f"=== {label}: walk {walk:,.0f} fitted "
            f"(noise={chosen_walk['noise']:.3g}), {plain:,.0f} at 0.4 ==="
        )
        print(f"  {'member':<12}{'default':>13}{'fitted':>13}{'gain':>12}  parameters")
        for name, (make, grid) in GRIDS.items():
            base = score(lambda _m=make: _m(), times, values, cut, len(values))
            chosen = fit(make, grid, times, values, cut)
            after = score(lambda _m=make, _p=chosen: _m(**_p), times, values, cut, len(values))
            # **Flag a pinned parameter.** One at the edge of its bracket is
            # a grid rather than a fit, and silently printing it as a fitted
            # value is how a widened bracket never gets asked for.
            marks = []
            for key, value in chosen.items():
                lo, hi = grid[key]
                edge = math.log10(max(value, 1e-300))
                pinned = edge <= lo + 0.05 or edge >= hi - 0.05
                marks.append(f"{key}={value:.3g}" + ("!" if pinned else ""))
            shown = " ".join(marks)
            print(f"  {name:<12}{base:>13,.0f}{after:>13,.0f}{after - base:>12,.0f}  {shown}")
        print()

    print("Reading it: 'gain' is what fitting was worth. A member whose gain")
    print("is large was being judged on its defaults rather than its model;")
    print("one whose gain is small was not.")
    print("A `!` marks a parameter at the edge of its bracket - a grid")
    print("rather than a fit, and the bracket needs widening before the")
    print("number beside it means anything.")


if __name__ == "__main__":
    main()
