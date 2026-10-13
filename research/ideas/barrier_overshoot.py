"""Which part of the barrier arithmetic skew actually breaks.

`bounding.py` derives the win probability and the expected duration of a two
barrier trade from a **symmetric driftless walk**:

    P = d / (u + d)        T = u * d        u = up + B,  d = down + B

with `B = 0.5826`, the Broadie-Glasserman-Kou discrete-monitoring shift. The
`Volatility_*` family is exactly that process - verified to spec, Gaussian,
kurtosis 3.12 - but Boom, Crash and DEX are not: 11 of 11 skew the advertised
way, with `|skew|` from 0.28 to 1.16.

**The obvious conclusion, that `P` is therefore wrong, is itself wrong**, and
getting this the right way round decides how much of the module has to change.

## `P` and `T` do not depend on the shape

`P = d/(u+d)` is optional stopping applied to a mean-zero martingale: at the
stopping time `E[X] = 0`, so `P*u - (1-P)*d = 0`. `T = u*d` is Wald's second
identity: `E[tau] * sigma^2 = E[X^2] = P*u^2 + (1-P)*d^2 = u*d`.

**Neither derivation mentions symmetry, Gaussianity or any higher moment.** They
need the martingale property and a finite variance and nothing else, so a skewed
martingale has the same `P` and the same `T` as a Gaussian one with the same
variance. The drift measurements support the premise: 0 of 11 spiking
instruments carry a drift past `|t| = 2`.

## What skew breaks is the overshoot, and it breaks it asymmetrically

`B` exists because a barrier watched once a bar can be crossed and recrossed
inside the bar, so the effective barrier sits further away than the stated one.
That is an **overshoot** correction, and the overshoot is exactly where a
one-sided process differs: a Boom index reaches its upper barrier **in a spike**
and overshoots it badly, and reaches its lower barrier by small drifting steps
and barely overshoots at all.

So the defect is not the formulas. It is that `B` is a single symmetric
constant, and for these instruments it has to be **two numbers**.

## What is measured

The mean excess beyond a barrier at first crossing, in units of one bar's
standard deviation, **separately by direction**. For a Gaussian walk both
directions must recover `0.5826`, which is the control: an estimator that
cannot reproduce the constant it is replacing has no business replacing it.

Reported at several barrier distances, because `B` is an asymptotic result and
the distance at which it settles is worth knowing.

Runs on the lab.
"""

from __future__ import annotations

import math
import os
import statistics

import relationship_screen as screen

#: Barrier distances in units of one bar's standard deviation.
#:
#: **16 was dropped.** First passage of `+/-16` sigma takes about 256 bars and
#: needs a window of four times that, so on 20,000 bars there are 19
#: non-overlapping samples - and with overlapping ones the first version read a
#: share-up of 0.4816 on a **driftless Gaussian walk** at an apparent `z` of
#: -3.2. The bias was 98% window overlap against a standard error that assumed
#: independence, so the reach the data cannot support is not measured.
REACHES = tuple(float(r) for r in os.environ.get("REACHES", "2,4,8").split(","))
#: The constant being replaced, for comparison.
SHIFT = 0.5826


#: Families reported apart. **DEX_UP and DEX_DOWN must not be pooled**: they
#: are mirror constructions, so averaging them averages opposite asymmetries
#: and reports a symmetric process. The first version pooled them.
FAMILIES = (
    "Volatility",
    "Boom",
    "Crash",
    "DEX_UP",
    "DEX_DOWN",
    "Step",
    "Multi_Step",
    "Skew_Step",
)


def in_family(name: str, family: str) -> bool:
    if family == "DEX_UP":
        return name.startswith("DEX_") and name.endswith("UP_Index")
    if family == "DEX_DOWN":
        return name.startswith("DEX_") and name.endswith("DOWN_Index")
    if family == "Step":
        # `Step_Index` only, not `Multi_Step_*` or `Skew_Step_*`.
        return name.startswith("Step")
    return name.startswith(family)


def raw_closes(name: str):
    """The unlogged closes, which is where a price lattice is visible.

    **The first version of this measured log returns and found no lattice
    anywhere**, including on `Step_Index`. That was the measurement, not the
    data: a step index moves in fixed *price* increments, and the logarithm of a
    price grid is not a grid. Modal share read 0.0004 on every instrument, which
    looked like an answer and was an artefact of the space it was measured in.
    """
    import numpy as np

    path = screen.CACHE / f"{name}.{screen.FRAME}.npz"
    if not path.exists():
        return None
    with np.load(path) as bundle:
        if "close" not in bundle:
            return None
        order = np.argsort(bundle["time"])
        times = np.asarray(bundle["time"], dtype=float)[order]
        closes = np.asarray(bundle["close"], dtype=float)[order]
    keep = (closes > 0) & (times >= screen.SINCE)
    closes = closes[keep]
    return closes[-screen.LIMIT :] if len(closes) > screen.LIMIT else closes


def lattice(steps):
    """How concentrated the absolute step is, which decides if there is a grid.

    `Step_Index` is advertised as a **fixed-size step with 50/50 direction**,
    which is a lattice rather than a diffusion. That matters more than any
    asymmetry: **on a lattice a barrier placed at an exact multiple of the step
    has no overshoot at all** - the walk lands on it rather than through it - so
    the discrete-monitoring correction is not merely asymmetric there, it is
    *removable*.

    Returned as the share of steps taking the modal absolute size, so a true
    lattice reads near 1.0 and a diffusion reads near 0.
    """
    import numpy as np

    sizes = np.abs(np.asarray(steps, dtype=float))
    sizes = sizes[sizes > 0]
    if len(sizes) < 100:
        return None
    # Round to a relative tolerance so float noise does not split one grid
    # value into thousands of distinct ones.
    scale = float(np.median(sizes))
    if scale <= 0:
        return None
    rounded = np.round(sizes / scale, 4)
    values, counts = np.unique(rounded, return_counts=True)
    best = int(counts.argmax())
    return {
        "share": float(counts[best] / len(sizes)),
        "modal": float(values[best] * scale),
        "distinct": int(len(values)),
        "up_share": float((np.asarray(steps) > 0).mean()),
    }


def overshoots(steps, reach: float, stride: int | None = None):
    """Mean excess beyond the barrier at first crossing, by direction.

    Walks forward from each entry until the cumulative move passes `reach`
    standard deviations either way, and records how far past it went.

    **Entries are non-overlapping by default**, because the share that crossed
    upward is a proportion and its standard error assumes independent draws.
    Overlapping windows inflate the sample without adding information and turn
    a driftless walk into an apparent downward bias.
    """
    import numpy as np

    steps = np.asarray(steps, dtype=float)
    sd = float(steps.std())
    if sd <= 0:
        return None
    level = reach * sd
    # A generous cap: first passage of +/- reach takes about reach^2 bars.
    span = int(max(4.0 * reach * reach, 64))
    step_by = span if stride is None else stride
    up, down = [], []
    for start in range(0, len(steps) - span, step_by):
        path = np.cumsum(steps[start : start + span])
        hit = np.flatnonzero(np.abs(path) >= level)
        if not len(hit):
            continue
        where = hit[0]
        excess = (abs(path[where]) - level) / sd
        (up if path[where] > 0 else down).append(excess)
    if len(up) < 12 or len(down) < 12:
        return None
    return {
        "up": statistics.mean(up),
        "down": statistics.mean(down),
        "up_count": len(up),
        "down_count": len(down),
        "share_up": len(up) / (len(up) + len(down)),
    }


def planted() -> None:
    """A Gaussian walk, which must recover 0.5826, and a skewed martingale."""
    import numpy as np

    print("=" * 104)
    print("ARM 0  the control: a Gaussian walk must return the constant it replaces")
    print("=" * 104)
    rng = np.random.default_rng(11)
    n = 120_000
    gauss = rng.standard_normal(n)

    # A skewed *martingale*: rare large up-jumps paid for by a constant down
    # drift, so the mean is exactly zero by construction.
    rate = 0.01
    size = 8.0
    jumps = (rng.random(n) < rate).astype(float) * size
    skewed = jumps - rate * size + rng.standard_normal(n) * 0.5
    skewed = skewed - skewed.mean()

    print(f"{'process':<26}{'skew':>8}{'reach':>7}{'B up':>9}{'B down':>9}{'share up':>10}")
    for label, steps in (("gaussian", gauss), ("skewed martingale", skewed)):
        sd = steps.std()
        skew = float((((steps - steps.mean()) / sd) ** 3).mean())
        for reach in REACHES:
            got = overshoots(steps, reach, stride=16)
            if got is None:
                continue
            print(
                f"{label:<26}{skew:>+8.3f}{reach:>7.0f}"
                f"{got['up']:>9.4f}{got['down']:>9.4f}{got['share_up']:>10.4f}"
            )
    print(
        f"\nThe gaussian rows must sit near {SHIFT} in both directions, and the\n"
        "skewed rows must differ between them. `share up` is the empirical `P`\n"
        "at equal barriers: optional stopping says it stays near 0.5 whatever\n"
        "the skew, because a martingale is a martingale."
    )


def main() -> None:
    print(
        f"barrier distances {REACHES} sd, non-overlapping entries,\n"
        f"replacing a single symmetric shift of {SHIFT}\n"
    )
    planted()

    import numpy as np

    print("\n" + "=" * 104)
    print("ARM 1  the spiking families, where the two directions should part")
    print("=" * 104)
    names = [
        n
        for n in screen.universe(screen.FRAME, cap=80)
        if screen.load(n) is not None
        and n.startswith(
            ("Boom_", "Crash_", "DEX_", "Volatility_", "Step", "Multi_Step", "Skew_Step")
        )
    ]
    print(
        f"{'instrument':<26}{'skew':>8}{'reach':>7}{'B up':>9}{'B down':>9}"
        f"{'ratio':>8}{'share up':>10}"
    )
    rows = []
    for name in names:
        series = screen.load(name)
        steps = np.diff(series[1])
        sd = float(steps.std())
        if sd <= 0:
            continue
        skew = float((((steps - steps.mean()) / sd) ** 3).mean())
        for reach in REACHES:
            got = overshoots(steps, reach)
            if got is None:
                continue
            ratio = got["up"] / got["down"] if got["down"] > 0 else float("nan")
            rows.append((name, skew, reach, got, ratio))
            print(
                f"{name:<26}{skew:>+8.3f}{reach:>7.0f}{got['up']:>9.4f}"
                f"{got['down']:>9.4f}{ratio:>8.3f}{got['share_up']:>10.4f}"
            )
    if not rows:
        print("  nothing measurable")
        return

    print("\n" + "=" * 104)
    print("ARM 2  by family, which is what a table in the library would carry")
    print("=" * 104)
    print(f"{'family':<16}{'reach':>7}{'B up':>9}{'B down':>9}{'ratio':>8}{'rows':>7}")
    for family in FAMILIES:
        for reach in REACHES:
            here = [r for r in rows if in_family(r[0], family) and r[2] == reach]
            if not here:
                continue
            ups = statistics.median(r[3]["up"] for r in here)
            downs = statistics.median(r[3]["down"] for r in here)
            print(
                f"{family:<16}{reach:>7.0f}{ups:>9.4f}{downs:>9.4f}"
                f"{ups / downs if downs else float('nan'):>8.3f}{len(here):>7}"
            )
    print(
        f"\nVolatility is the control and must land near {SHIFT} both ways. A\n"
        "family whose ratio departs from 1 needs two shifts rather than one,\n"
        "and the number in the `B up` and `B down` columns is the one to carry."
    )

    print("\n" + "=" * 104)
    print("ARM 4  is any of them a lattice, where the shift can be removed instead")
    print("=" * 104)
    print(
        "A fixed step size is not a smaller correction, it is **no correction**:\n"
        "a barrier at an exact multiple of the step is landed on rather than\n"
        "crossed. `modal share` near 1.0 is a grid; near 0 is a diffusion.\n"
    )
    print(
        f"{'instrument':<26}{'modal share':>13}{'distinct':>10}"
        f"{'modal step':>12}{'up share':>10}"
    )
    for name in names:
        closes = raw_closes(name)
        if closes is None or len(closes) < 200:
            continue
        # In price, not log: a step index steps in price.
        got = lattice(np.diff(closes))
        if got is None:
            continue
        print(
            f"{name:<26}{got['share']:>13.4f}{got['distinct']:>10}"
            f"{got['modal']:>12.6f}{got['up_share']:>10.4f}"
        )
    print(
        "\n`up share` is the advertised 50/50 for the step families, and a\n"
        "lattice with a modal share near 1 is the one case where `bounding.py`\n"
        "can be exact rather than corrected."
    )

    print("\n" + "=" * 104)
    print("ARM 3  does the probability move, which the algebra says it must not")
    print("=" * 104)
    print(
        "At equal barriers optional stopping gives P = 0.5 for any mean-zero\n"
        "martingale, skewed or not. If `share up` departs from 0.5 beyond its\n"
        "own standard error then either the process is not a martingale or the\n"
        "formulas do need a skew term after all.\n"
    )
    print(f"{'family':<16}{'reach':>7}{'share up':>11}{'se':>9}{'z':>8}")
    for family in FAMILIES:
        for reach in REACHES:
            here = [r for r in rows if in_family(r[0], family) and r[2] == reach]
            if not here:
                continue
            total = sum(r[3]["up_count"] + r[3]["down_count"] for r in here)
            share = sum(r[3]["up_count"] for r in here) / total
            se = math.sqrt(0.25 / total)
            print(
                f"{family:<16}{reach:>7.0f}{share:>11.4f}{se:>9.4f}"
                f"{(share - 0.5) / se:>+8.2f}"
            )


if __name__ == "__main__":
    main()
