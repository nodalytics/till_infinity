"""Does the time-of-day profile belong on every member's lever, or only the level's?

`statespace-seasonal.md` measured the clock profile driving `level_wander` on a
level-only member and found +197 nats at the median. It left one question
open: the other members carry different process noises, and whether the clock
belongs on those was untested.

## Why the dimensions already work

Three levers, three different units, all of them **variance rates**:

| member | lever | units |
| --- | --- | --- |
| `Seasonal` level-only | `level_wander` | (value)^2 / hour |
| `linear.Gaussian` | `jerk` | (value)^2 / hour^5 |
| `reverting.Reverting` | `sigma2` | (value)^2 / hour^3 |

`Profile.factor` returns the profile **squared**, which is the right multiplier
for a variance whatever the integration order: a threefold profile in size is a
ninefold one in variance, and the integration from jerk to position is linear
in the jerk's spectral density, so the factor passes through unchanged. The
dimensions are therefore not the question. The question is whether a member
whose dynamics are smoother - `kalman` integrates jerk three times to reach
the level - can use an hourly signal at all, or whether its own smoothing
averages the profile away.

## The base has to be fitted first, or the clock wins for the wrong reason

**This is the trap this harness exists to avoid.** If a member's process noise
is set badly, multiplying it by a profile that averages above or below one
would improve the fit by accident - the gain would be a rescaling, not a
clock. `driven.Driven` floors on the product but does not normalise it, and
`Profile.at` averages one over the *cycle* rather than over the sample's
actual hours, so a sample that is not a whole number of days is slightly
off-centre.

So each lever's base is swept over a grid and **chosen on the matched null**,
`clock=None`, before the clock is applied. The clock then has to beat the
member at its own best setting, which is the only comparison worth making.

## Nulls

* **matched** - the same member, same fitted base, `clock=None`;
* **clock broken** - the observations slid half a day against the stamps, with
  its own matched null, because sliding also shortens the sample;
* **generated markets** - no session, so no profile to find.
"""

from __future__ import annotations

import math
import os
import statistics
from pathlib import Path

from till_infinity.structures.statespace.driven import Driven
from till_infinity.structures.statespace.linear import Gaussian
from till_infinity.structures.statespace.reverting import Reverting
from till_infinity.structures.statespace.seasonal import Profile, Seasonal

HOUR = 3600.0

TRADED = ("EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "XAGUSD", "BTCUSD", "ETHUSD")
GENERATED = ("Volatility_75_Index", "Step_Index")
FRAMES = tuple(os.environ.get("FRAMES", "1h").split(","))

#: Multiples of the dimensionally natural base to sweep, over fourteen
#: decades. It needs to be this wide because `jerk` kept pinning at the
#: bottom edge, and a parameter at a grid edge is not a fitted parameter -
#: the defect `statespace-fitting.md` records three of.
#:
#: Pinning at the **floor** turned out to be the finding rather than an
#: obstacle, which is why `null loglike` is printed beside the gain: a lever
#: driven to zero cannot carry a profile, because zero times any factor is
#: still zero.
GRID = (1e-12, 1e-10, 1e-8, 1e-6, 1e-4, 0.01, 1.0, 100.0)

SINCE = float(os.environ.get("SINCE", "1420070400"))
LIMIT = int(os.environ.get("LIMIT", "30000"))
CACHE = Path.home() / "till_infinity" / "data" / "seqlab"


def load(name: str, frame: str):
    import numpy as np

    for path in (CACHE / f"{name}.{frame}.npz", Path(f"data/seqlab/{name}.{frame}.npz")):
        if not path.exists():
            continue
        with np.load(path) as bundle:
            if not {"time", "close"} <= set(bundle.keys()):
                continue
            order = np.argsort(bundle["time"])
            times = bundle["time"][order].tolist()
            closes = bundle["close"][order].tolist()
        first = 0
        while first < len(times) and times[first] < SINCE:
            first += 1
        times, closes = times[first:], closes[first:]
        if len(times) > LIMIT:
            times, closes = times[-LIMIT:], closes[-LIMIT:]
        return (times, closes) if len(times) > 5000 else None
    return None


#: Each lever: how to build the member, the attribute name, and the
#: dimensionally natural base from a one-step spread `s` over `dt` hours.
#:
#: The exponents come straight from the integration order. A level's variance
#: grows like `q * dt`, a reverting rate's contribution to the level like
#: `q * dt^3`, and an integrated jerk's like `q * dt^5`, so matching a
#: one-step variance of `s^2` means `q = s^2 / dt^k` for `k` of 1, 3 and 5.
LEVERS = (
    (
        "level",
        lambda base: Seasonal(seasonal_on=False, level_wander=base),
        "level_wander",
        lambda s, dt: s * s / dt,
    ),
    (
        "jerk",
        lambda base: Gaussian(jerk=base),
        "jerk",
        lambda s, dt: s * s / dt**5,
    ),
    (
        "reverting",
        lambda base: Reverting(sigma2=base),
        "sigma2",
        lambda s, dt: s * s / dt**3,
    ),
)


def score(times, values, *, build, lever, base, profile, slide: int = 0) -> float:
    """One pass, scored on the second half only."""
    if slide:
        times = times[: len(times) - slide]
        values = values[slide:]
    steps = [abs(values[i] - values[i - 1]) for i in range(1, len(values))]
    noise = statistics.pstdev(steps) or 1e-9
    start = len(times) // 2

    member = Driven(
        build=lambda: build(base),
        lever=lever,
        clock=profile.factor if profile is not None else None,
    )
    for when, value in zip(times, values, strict=True):
        member.predict(when)
        member.update(value, noise, when)
        if member.seen == start:
            member.loglike = 0.0
    return member.loglike


def best_base(times, values, *, build, lever, natural) -> tuple[float, float]:
    """Sweep the grid on the **matched null**, so the clock cannot win a rescaling."""
    found = []
    for multiple in GRID:
        base = natural * multiple
        if base <= 0:
            continue
        got = score(times, values, build=build, lever=lever, base=base, profile=None)
        if math.isfinite(got):
            found.append((got, base, multiple))
    if not found:
        return 0.0, float("nan")
    got, base, multiple = max(found)
    if multiple in (GRID[0], GRID[-1]):
        # Pinned at an edge: the grid did not bracket the best value, so the
        # comparison below is against a member that is still mis-set.
        print(f"    (base pinned at grid edge {multiple}x - widen GRID)")
    return base, got


def main() -> None:
    print(f"frames {FRAMES}  grid {GRID}\n")
    print(
        f"{'instrument':<22}{'lever':<11}{'base x':>10}{'null loglike':>12}"
        f"{'clock':>10}{'slid':>10}{'hi/lo':>7}"
    )
    rows: list[tuple[str, str, float, float]] = []
    for name in TRADED + GENERATED:
        for frame in FRAMES:
            found = load(name, frame)
            if found is None:
                continue
            times, closes = found
            logs = [math.log(c) for c in closes if c > 0]
            if len(logs) != len(times):
                continue

            gaps = [times[i] - times[i - 1] for i in range(1, min(len(times), 500))]
            dt = statistics.median(gaps) / HOUR if gaps else 1.0
            half = max(round(12.0 / dt), 1)
            spread = statistics.pstdev([logs[i] - logs[i - 1] for i in range(1, len(logs))]) or 1e-9

            middle = len(times) // 2
            profile = Profile.fit(times[:middle], logs[:middle])
            if profile is None:
                continue

            label = f"*{name}" if name in GENERATED else name
            for tag, build, lever, natural in LEVERS:
                base, flat = best_base(
                    times, logs, build=build, lever=lever, natural=natural(spread, dt)
                )
                if base <= 0:
                    continue
                driven = score(times, logs, build=build, lever=lever, base=base, profile=profile)
                slid = score(
                    times,
                    logs,
                    build=build,
                    lever=lever,
                    base=base,
                    profile=profile,
                    slide=half,
                )
                slid_flat = score(
                    times,
                    logs,
                    build=build,
                    lever=lever,
                    base=base,
                    profile=None,
                    slide=half,
                )
                print(
                    f"{label:<22}{tag:<11}{base / natural(spread, dt):>10.1e}"
                    f"{flat:>12.1f}{driven - flat:>10.1f}{slid - slid_flat:>10.1f}"
                    f"{profile.extent():>7.2f}"
                )
                rows.append((label, tag, driven - flat, slid - slid_flat))

    print()
    for tag, _b, _l, _n in LEVERS:
        traded = [(a, b) for label, t, a, b in rows if t == tag and not label.startswith("*")]
        made = [(a, b) for label, t, a, b in rows if t == tag and label.startswith("*")]
        if not traded:
            continue
        line = (
            f"{tag:<11} traded median {statistics.median([a for a, _ in traded]):>9.1f}"
            f"   clock broken {statistics.median([b for _, b in traded]):>9.1f}"
        )
        if made:
            line += f"   generated {statistics.median([a for a, _ in made]):>8.1f}"
        print(line)


if __name__ == "__main__":
    main()
