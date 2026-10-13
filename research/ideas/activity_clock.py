"""Does activity on `Q` earn what the clock earns, and does it add to it?

`seasonal.Profile` on `Q` is worth a great deal on traded instruments, and
`statespace-volume-clock.md` then showed the clock is mostly a proxy for
**activity**: resampling into volume time absorbs about three-quarters of the
profile, which is the subordination result of Clark 1973. 14:00 UTC is not
special, it is busy.

That measurement could not be turned into a gain, because resampling changes
the observation set and a density over volume bars cannot be compared with one
over calendar bars. **This harness does not resample.** `statespace.pacing`
turns each bar's own tick volume into a variance multiplier on the same
calendar bars, so every arm here is a density over the **identical**
observations and the likelihoods subtract.

## The arms

Each on the same member, with the base process noise **refitted on the flat
arm** - the matched null - so no arm can win by rescaling a mis-set member.
That refit is not optional: a multiplier whose mean is not one changes the
average process noise as well as its variation, and on this desk that mistake
once turned a `+1192` into a `-24`.

* `flat` - the control. No clock, no activity;
* `clock` - `Profile.factor`, the measured positive;
* `pace 1` - activity with `exponent = 1`, which is what subordination says:
  variance tracks the number of price changes;
* `pace 2` - activity squared, which is what the quantity would need if it
  were standing in for a size the way the clock's profile does;
* `both` - the product, which is the question the volume-clock study left
  open: is the quarter of the clock that activity does **not** absorb worth
  carrying?

## The controls, and a correction to what was claimed about them

`statespace-volume-clock.md` says the generated feeds post **exactly constant**
tick volume. That was measured at **3m**, and it does not survive the move to
1h: a survey of all 553 cached feeds found **none** with an activity extent of
exactly 1.000. The synthetics come in at **1.003 to 1.016** with a coefficient
of variation of 0.005 to 0.022, against 2.7 to 9.4 for traded instruments.

So the control is a **bound rather than an identity**: a feed whose activity
varies by one part in a hundred has almost nothing for this mechanism to use,
and must earn almost nothing. Stated that way it is still the control the study
needs, and stating it as exact inertness - which the first version of this
harness did - fails on a feed that is behaving correctly.

Runs on the lab.
"""

from __future__ import annotations

import math
import os
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from till_infinity.structures.statespace.driven import Driven  # noqa: E402
from till_infinity.structures.statespace.linear import Gaussian  # noqa: E402
from till_infinity.structures.statespace.pacing import Both, Levelled, Pace  # noqa: E402
from till_infinity.structures.statespace.reverting import Reverting  # noqa: E402
from till_infinity.structures.statespace.seasonal import Profile, Seasonal  # noqa: E402

HOUR = 3600.0
CACHE = Path(os.environ.get("SEQLAB_CACHE", str(Path.home() / "till_infinity/data/seqlab")))
FRAMES = tuple(os.environ.get("FRAMES", "1h").split(","))
LIMIT = int(os.environ.get("LIMIT", "40000"))
SINCE = float(os.environ.get("SINCE", "0"))

#: Base-noise sweep, on the flat arm only. Widened after EURUSD pinned at the
#: low edge, which means the flat arm it is compared against was still mis-set.
GRID = tuple(
    float(x) for x in os.environ.get("GRID", "0.016,0.03,0.0625,0.125,0.25,0.5,1,2,4").split(",")
)

#: The exponents swept. Each is normalised to average one inside `Pace`, so
#: this compares the **shape** of the multiplier and not its level.
#: Swept past the apparent best so the preference has a **turn** in it. An
#: exponent that keeps improving as it rises is not a preferred shape, it is a
#: statistic being dominated by its largest few bars and the clamp that bounds
#: them.
EXPONENTS = tuple(float(x) for x in os.environ.get("EXPONENTS", "0.5,1,2,3,4").split(","))

TRADED = tuple(
    os.environ.get(
        "TRADED",
        "EURUSD,GBPUSD,USDJPY,USDCAD,AUDUSD,XAUUSD,XAGUSD,US_Oil",
    ).split(",")
)
#: Near-constant tick volume, so the activity arms have almost nothing to use.
#: These names are the ones the cache actually holds - the first run asked for
#: `Boom_500` and `Volatility_75` and silently got nothing for three of its
#: four controls, which is the failure mode a control group can least afford.
GENERATED = tuple(
    os.environ.get(
        "GENERATED",
        "Boom_500_Index,Crash_500_Index,DEX_900_UP_Index,Drift_Switch_Index_10,Step_Index_200",
    ).split(",")
)

#: `level_wander` and not `jerk`. The clock was measured on both and the
#: difference is the whole result: `jerk` reads `-31.19` for a true clock and
#: `level_wander` `+33.06`, because driving the fifth integral of a level is
#: not driving how far the level goes.
LEVERS = {
    "level": (
        lambda base: Seasonal(seasonal_on=False, level_wander=base),
        "level_wander",
        lambda s, dt: s * s / dt,
    ),
    "jerk": (lambda base: Gaussian(jerk=base), "jerk", lambda s, dt: s * s / dt**5),
    "reverting": (
        lambda base: Reverting(sigma2=base),
        "sigma2",
        lambda s, dt: s * s / dt**3,
    ),
}
WHICH = tuple(os.environ.get("LEVERS", "level").split(","))


def load(name: str, frame: str):
    """`(times, log closes, volumes)`, or `None`. Volume is required here."""
    import numpy as np

    for path in (CACHE / f"{name}.{frame}.npz", Path(f"data/seqlab/{name}.{frame}.npz")):
        if not path.exists():
            continue
        with np.load(path) as bundle:
            if not {"time", "close", "volume"} <= set(bundle.keys()):
                continue
            order = np.argsort(bundle["time"])
            times = bundle["time"][order].tolist()
            closes = bundle["close"][order].tolist()
            volumes = bundle["volume"][order].tolist()
        first = 0
        while first < len(times) and times[first] < SINCE:
            first += 1
        times, closes, volumes = times[first:], closes[first:], volumes[first:]
        if len(times) > LIMIT:
            times, closes, volumes = times[-LIMIT:], closes[-LIMIT:], volumes[-LIMIT:]
        if len(times) <= 5000 or min(closes) <= 0:
            return None
        return times, [math.log(c) for c in closes], volumes
    return None


class NoDriver:
    """The control arm: no exogenous input at all."""

    def control(self, when: float, volume: float) -> float:  # noqa: ARG002
        return 0.0


class PaceDriver:
    """Activity alone, through `Driven`'s exogenous door."""

    def __init__(self, exponent: float) -> None:
        self.pace = Pace(exponent=exponent)

    def control(self, when: float, volume: float) -> float:  # noqa: ARG002
        self.pace.update(volume)
        return self.pace.control(volume)


class BothDriver:
    """Clock times activity, with the **product** renormalised.

    Routed through the one door rather than giving the clock to `Driven` and
    the activity to `control`, because `Driven` multiplies its two channels
    without renormalising and the product of two mean-one factors is not
    mean-one when they are correlated - which these two are.
    """

    def __init__(self, exponent: float, clock) -> None:
        self.both = Both(pace=Pace(exponent=exponent), clock=clock)

    def control(self, when: float, volume: float) -> float:
        self.both.pace.update(volume)
        return self.both.factor(when, volume) - 1.0


def score(times, values, volumes, *, build, lever, base, clock, driver):
    """`(loglike on the second half, realised mean factor)`.

    The mean factor is returned because it is the one number that says whether
    an arm won by **shape** or by **level**. `Pace.factor` normalises to
    average one, but it normalises against a lagging exponential mean of a
    heavy-tailed quantity, so the realised average is near one rather than
    one - and an arm whose average has drifted to 1.5 has been handed half
    again as much process noise, which is not what is being tested.
    """
    steps = [abs(values[i] - values[i - 1]) for i in range(1, len(values))]
    noise = statistics.pstdev(steps) or 1e-9
    start = len(times) // 2

    member = Driven(build=lambda: build(base), lever=lever, clock=clock)
    for when, value, volume in zip(times, values, volumes, strict=True):
        # Folded in before it is read, so the bar is in its own mean and
        # nothing here looks forward.
        member.predict(when, driver.control(when, volume))
        member.update(value, noise * noise, when)
        if member.seen == start:
            member.loglike = 0.0
    return member.loglike, member.average


def best_base(times, values, volumes, *, build, lever, natural):
    """Sweep the base on the **flat** arm, so no driver can win a rescaling."""
    found = []
    for multiple in GRID:
        base = natural * multiple
        if base <= 0:
            continue
        got, _average = score(
            times,
            values,
            volumes,
            build=build,
            lever=lever,
            base=base,
            clock=None,
            driver=NoDriver(),
        )
        if math.isfinite(got):
            found.append((got, base, multiple))
    if not found:
        return 0.0, float("nan")
    got, base, multiple = max(found)
    if multiple in (GRID[0], GRID[-1]):
        print(f"    (base pinned at grid edge {multiple}x - widen GRID)")
    return base, got


def main() -> None:
    from till_infinity.structures.statespace.pacing import extent

    print(f"frames {FRAMES}  levers {WHICH}  exponents {EXPONENTS}")
    print(
        "every arm is a density over the same calendar bars, so these\n"
        "likelihoods subtract - which is what resampling into volume time\n"
        "could not do. `mean factor` is each arm's realised average\n"
        "multiplier: an arm whose average is not one won partly on level.\n"
    )
    labels = (
        ["clock", "clock norm"]
        + [f"pace {e:g}" for e in EXPONENTS]
        + [f"both {e:g}" for e in EXPONENTS]
    )
    print(
        f"{'instrument':<22}{'activity':>9}{'extent':>8}{'flat':>11}"
        + "".join(f"{one:>10}" for one in labels)
    )
    rows = []
    for name in TRADED + GENERATED:
        for frame in FRAMES:
            found = load(name, frame)
            if found is None:
                print(f"{name:<22}  no cached bars with volume at {frame}")
                continue
            times, logs, volumes = found
            gaps = [times[i] - times[i - 1] for i in range(1, min(len(times), 500))]
            dt = statistics.median(gaps) / HOUR if gaps else 1.0
            spread = (
                statistics.pstdev([logs[i] - logs[i - 1] for i in range(1, len(logs))]) or 1e-9
            )
            middle = len(times) // 2
            profile = Profile.fit(times[:middle], logs[:middle])
            if profile is None:
                print(f"{name:<22}  no profile fitted at {frame}")
                continue
            uneven = extent(volumes)

            for tag in WHICH:
                build, lever, natural = LEVERS[tag]
                base, flat = best_base(
                    times, logs, volumes, build=build, lever=lever, natural=natural(spread, dt)
                )
                if base <= 0:
                    continue
                arms, averages = {}, {}
                plan = [
                    ("clock", profile.factor, NoDriver),
                    ("clock norm", Levelled(inner=profile.factor).factor, NoDriver),
                ]
                plan += [
                    (f"pace {e:g}", None, (lambda e=e: PaceDriver(e))) for e in EXPONENTS
                ]
                plan += [
                    (f"both {e:g}", None, (lambda e=e: BothDriver(e, profile.factor)))
                    for e in EXPONENTS
                ]
                for label, which, make in plan:
                    got, average = score(
                        times,
                        logs,
                        volumes,
                        build=build,
                        lever=lever,
                        base=base,
                        clock=which,
                        driver=make(),
                    )
                    arms[label], averages[label] = got - flat, average
                made = name in GENERATED
                print(
                    f"{('*' + name if made else name):<22}{uneven:>9.2f}"
                    f"{profile.extent():>8.2f}{flat:>11.1f}"
                    + "".join(f"{arms[one]:>10.1f}" for one in labels)
                )
                rows.append((name, made, uneven, arms, averages))

    if not rows:
        print("\nnothing scored")
        return

    print("\n" + "=" * 104)
    print("did any arm win on level rather than shape")
    print("=" * 104)
    print(f"{'arm':<12}{'median mean factor':>20}{'worst':>10}")
    for one in labels:
        got = [r[4][one] for r in rows if math.isfinite(r[4][one])]
        if got:
            worst = max(got, key=lambda v: abs(v - 1.0))
            print(f"{one:<12}{statistics.median(got):>20.4f}{worst:>10.4f}")
    print(
        "\nOne is neutral. The first version of this study returned the raised\n"
        "share directly and the squared arm ran at a mean factor of 2.23,\n"
        "which handed it more process noise and nothing to do with shape."
    )

    print("\n" + "=" * 104)
    print("the control group: feeds whose activity barely varies")
    print("=" * 104)
    print(
        "Not an identity test. No cached feed has an activity extent of exactly\n"
        "1.000 at 1h - the claim of exact constancy was measured at 3m. These\n"
        "vary by one part in a hundred, so they bound what the mechanism can\n"
        "earn from nothing.\n"
    )
    for name, made, uneven, arms, _averages in rows:
        if not made:
            continue
        biggest = max((abs(arms[k]), k) for k in labels if "pace" in k)
        print(
            f"  {name:<24}activity extent {uneven:>7.4f}   "
            f"largest activity arm {biggest[0]:>8.1f} nats ({biggest[1]})"
        )

    print("\n" + "=" * 104)
    print("medians")
    print("=" * 104)
    print(f"{'group':<14}{'cells':>7}" + "".join(f"{one:>10}" for one in labels))
    for label, made in (("traded", False), ("generated", True)):
        here = [r for r in rows if r[1] == made]
        if not here:
            continue
        print(
            f"{label:<14}{len(here):>7}"
            + "".join(f"{statistics.median([r[3][one] for r in here]):>10.1f}" for one in labels)
        )

    traded = [r for r in rows if not r[1]]
    if not traded:
        return
    paces = [one for one in labels if one.startswith("pace")]
    middle = {k: statistics.median([r[3][k] for r in traded]) for k in labels}
    best = max(paces, key=lambda k: middle[k])
    print(
        f"\nthe exponent the data prefers is {best.split()[1]}. Subordination\n"
        "says 1. An exponent sweep with no turn in it would mean the statistic\n"
        "is being carried by its largest few bars rather than by a shape, so\n"
        f"the sweep runs to {max(EXPONENTS):g}: "
        + ", ".join(f"{k.split()[1]} -> {middle[k]:+.0f}" for k in paces)
    )
    beats = sum(1 for r in traded if r[3][best] > r[3]["clock"])
    print(
        f"\nactivity beats the clock on {beats} of {len(traded)} traded cells, "
        f"median {middle[best]:+.1f} against {middle['clock']:+.1f}."
    )
    print(
        f"the clock with its level subsidy removed earns "
        f"{middle['clock norm']:+.1f} against {middle['clock']:+.1f} with it, "
        f"so\n{'most of the clock was level, not shape' if middle['clock norm'] < 0.5 * middle['clock'] else 'the clock survives its own normalisation'}."
    )
    bothbest = max((k for k in labels if k.startswith("both")), key=lambda k: middle[k])
    adds = sum(1 for r in traded if r[3][bothbest] > max(r[3]["clock"], r[3][best]))
    print(
        f"\nthe best composed arm is {bothbest} at {middle[bothbest]:+.1f}, and it "
        f"beats the better\nof the two alone on {adds} of {len(traded)} cells. "
        "That is the question the volume-clock\nstudy left open: activity "
        "absorbs three-quarters of the clock, and this says\nwhether the rest "
        "is worth carrying."
    )


if __name__ == "__main__":
    main()
