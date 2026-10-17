"""Does a panel-denoised volatility move the clock and the ladder, in nats.

`panel_volatility.py` measured a cross-sectional volatility factor removing
**4.3%** of out-of-sample log-volatility forecast error on equities at a pooled
`t` of `+4.85`, and **3.1%** on the FX crosses with few currency neighbours. It
then said plainly that whether this moves the clock, the ladder or sizing was
not measured. This measures two of the three.

The question is not whether the estimator is better - that is settled - but
whether the two places the desk already earns from volatility can **spend** it.
Those are:

* **the clock**, `Driven(build, lever, clock=factor)` from
  `research/ideas/clock_levers.py`, which multiplies a member's process noise
  by a time-varying factor and is scored by the member's own log-likelihood on
  the second half;
* **the log-volatility ladder**, `ladder_against_one` from
  `research/ideas/rough_volatility.py`, a `Fractional(modes=5)` ladder against
  a single OU, scored the same way.

Both are reused rather than reimplemented. A result on a fresh scorer would not
be a result about the clock.

## The blend is nested, so a null result is exactly zero

The denoised series is
`blend(w) = (1 - w) * own + w * (a + b * factor)`, with `a` and `b` from a
training-half regression of own log-volatility on the factor, and **`w` swept on
the training half** exactly as both harnesses already sweep their process noise.

`w = 0` *is* the own-only arm. So if the factor carries nothing the sweep picks
zero and the measured gain is zero rather than a small negative number that
needs interpreting. The arms are nested and the comparison cannot be won by the
extra freedom.

## Two traps this has to avoid, both already recorded

**A lever's multiplier must have mean 1.** `statespace-clock-levers.md` records a
clock whose factor averaged 1.04 to 1.36, which scored the arms at different
average `Q` and turned a `+1192` into a `-24`. Every factor here is normalised
to mean 1 before use, and the base is still swept on the matched null so the
null cannot be handicapped.

**The ladder's measurement variance is declared, not fitted.** It is
`1/(2 * WINDOW)`, which the harness knows analytically. A denoised series has
*less* measurement noise, so declaring a smaller variance for the panel arm
would raise its likelihood mechanically. **Both arms therefore declare the
identical variance.** That understates the panel's benefit - it is not allowed
to claim the tighter variance it has earned - which is the conservative
direction.

## Controls

* **rotation** - the other instruments rotated in time, so the factor is noise
  with every marginal preserved. The sweep should then pick `w = 0`;
* **the synthetics** - measured mutually uncorrelated in volatility at
  `-0.0133`, so there is nothing to borrow and the gain must be zero.

Runs on the lab.
"""

from __future__ import annotations

import math
import os
import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import panel_volatility as panel  # noqa: E402
import relationship_screen as screen  # noqa: E402

HOUR = 3600.0
#: Bars per volatility observation. **6, not 24** - `rough_volatility.WINDOW`
#: is 6, so the published ladder result is measured on six-bar realised
#: volatility and its declared measurement variance is `1/12` rather than
#: `1/48`. A first run at 24 improved a ladder that was *losing* to a single OU
#: by -27.6 nats, which is not the ladder this is supposed to be about.
SPAN = int(os.environ.get("SPAN", "6"))
#: Blend weights swept on the training half. 0.0 is the own-only arm.
WEIGHTS = tuple(
    float(w) for w in os.environ.get("WEIGHTS", "0.0,0.1,0.2,0.3,0.4,0.5").split(",")
)
#: Process-noise grid, in powers of ten, for both harnesses' own sweep.
POWERS = range(-12, 3)
#: Instruments carried, and null repetitions.
EQUITIES = int(os.environ.get("EQUITIES", "21"))
REPS = int(os.environ.get("REPS", "4"))
SEED = 20261013


def blended(matrix, index: int, half: int, weight: float, picked):
    """`(1-w)*own + w*(a + b*factor)`, with `a` and `b` fitted on the first half."""
    import numpy as np

    own = matrix[index]
    if weight <= 0 or not picked:
        return own
    others = matrix[picked]
    centre = others[:, : half + 1].mean(axis=1, keepdims=True)
    spread = others[:, : half + 1].std(axis=1, keepdims=True)
    spread[spread == 0] = 1.0
    factor = ((others - centre) / spread).mean(axis=0)
    design = np.column_stack([factor[: half + 1], np.ones(half + 1)])
    try:
        fit, *_ = np.linalg.lstsq(design, own[: half + 1], rcond=None)
    except np.linalg.LinAlgError:
        return own
    implied = factor * fit[0] + fit[1]
    return (1.0 - weight) * own + weight * implied


def ladder_nats(series, half: int):
    """`ladder_against_one`'s two members, on a given log-volatility series."""
    from till_infinity.statespace.fractional import Fractional
    from till_infinity.statespace.reverting import Reverting

    # The declared measurement variance is the same for every arm, so a
    # denoised series is not allowed to claim the tighter variance it earns.
    variance = 1.0 / (2.0 * SPAN)
    stamps = [float(i) * SPAN * HOUR for i in range(len(series))]

    def score(build, noise: float, *, upto: int | None = None) -> float:
        member = build(noise)
        stop = upto if upto is not None else len(series)
        for i in range(stop):
            member.predict(stamps[i])
            member.update(float(series[i]), variance, stamps[i])
            if upto is None and i == half:
                member.loglike = 0.0
        return member.loglike

    out = {}
    for tag, build in (
        ("ladder", lambda q: Fractional(modes=5, wander=q)),
        ("one_ou", lambda q: Reverting(sigma2=q)),
    ):
        best, chosen = float("-inf"), 0.0
        for power in POWERS:
            noise = 10.0**power
            got = score(build, noise, upto=half)
            if math.isfinite(got) and got > best:
                best, chosen = got, noise
        if chosen <= 0:
            continue
        out[tag] = score(build, chosen)
    return out


def clock_nats(times, values, factor_at, half_index: int, *, profile=None):
    """`Driven`'s log-likelihood with a given clock, base swept on the null.

    **The lever is `level_wander`, and the choice is not cosmetic.** A level's
    variance grows like `q * dt`, so a volatility clock belongs there; a jerk's
    grows like `q * dt^5`. Checked against a planted clock on a series whose
    volatility quadruples half way through, with the base swept on the null in
    every case:

    | lever | null | the true clock | the same clock reversed |
    |-------|-----:|---------------:|------------------------:|
    | level       | +3830.45 | **+33.06** | **-1298.40** |
    | reverting   | +3713.40 |     -93.13 |       -28.96 |
    | jerk        | +3313.00 |     -31.19 |       -15.44 |

    Only `level` rewards a correct clock, and the first version of this used
    `jerk` - which would have reported a null for the clock arm from the lever
    alone. Note also how asymmetric the detector is: a correct clock is worth
    `+33` and a reversed one costs `-1298`, so a small positive is a real
    reading and a large negative means the clock is actively misleading.
    """
    from till_infinity.statespace.driven import Driven
    from till_infinity.statespace.seasonal import Seasonal

    steps = [abs(values[i] - values[i - 1]) for i in range(1, len(values))]
    noise = statistics.pstdev(steps) or 1e-9
    dt = (times[-1] - times[0]) / max(len(times) - 1, 1) / HOUR
    natural = noise * noise / dt if dt > 0 else noise * noise

    def run(base: float, clock) -> float:
        member = Driven(
            build=lambda: Seasonal(seasonal_on=False, level_wander=base),
            lever="level_wander",
            clock=clock,
        )
        for when, value in zip(times, values, strict=True):
            member.predict(when)
            member.update(value, noise * noise, when)
            if member.seen == half_index:
                member.loglike = 0.0
        return member.loglike

    # The base is swept on the matched null, so no clock wins a rescaling.
    best, base = float("-inf"), natural
    for power in range(-6, 7):
        here = natural * 10.0**power
        got = run(here, None)
        if math.isfinite(got) and got > best:
            best, base = got, here
    out = {name: run(base, call) for name, call in factor_at.items()}
    if profile is not None:
        # **The established clock is the time-of-day profile, not realised
        # volatility.** The +1055 result drives the lever with `Profile.factor`,
        # which returns the profile squared - the right multiplier for a
        # variance. A realised-volatility clock is a different object, and the
        # first run measured the panel against *it* rather than against the
        # clock the desk actually earns from, which read -245 against no clock.
        out["profile"] = run(base, profile.factor)
        for name, call in factor_at.items():
            out[f"profile x {name}"] = run(
                base, lambda when, call=call: profile.factor(when) * call(when)
            )
    return base, best, out


def normalised(values):
    """A clock factor with mean exactly 1, which is the recorded failure mode."""
    import numpy as np

    out = np.exp(np.asarray(values, dtype=float))
    middle = float(out.mean())
    return out / middle if middle > 0 else out


def run_universe(label: str, names, series, *, rotate_with=None) -> None:
    import numpy as np

    pool = {n: series[n] for n in names if series.get(n) is not None}
    if rotate_with is not None:
        for n in list(pool)[1:]:
            pool[n] = panel.rotated(pool[n], rotate_with)
    kept, matrix = panel.aligned(list(pool), pool)
    if kept is None:
        print(f"{label:<30}  not enough common spans")
        return
    half = matrix.shape[1] // 2

    ladder_rows, clock_rows = [], []
    for index, name in enumerate(kept):
        picked = panel.nearest_neighbours(matrix, index, half)
        if len(picked) < 2:
            continue
        # One weight, chosen on the training half by the ladder's own score,
        # and reused for the clock so the two arms are the same estimator.
        best_w, best_train = 0.0, float("-inf")
        for weight in WEIGHTS:
            made = blended(matrix, index, half, weight, picked)
            got = ladder_nats(made[: half + 1], max(half // 2, 20))
            value = got.get("ladder", float("-inf"))
            if math.isfinite(value) and value > best_train:
                best_train, best_w = value, weight

        own = ladder_nats(matrix[index], half)
        made = blended(matrix, index, half, best_w, picked)
        panelled = ladder_nats(made, half)
        if own.get("ladder") is not None and panelled.get("ladder") is not None:
            ladder_rows.append(
                {
                    "name": name,
                    "weight": best_w,
                    "own_ladder": own["ladder"],
                    "panel_ladder": panelled["ladder"],
                    "own_margin": own["ladder"] - own.get("one_ou", 0.0),
                    "panel_margin": panelled["ladder"] - panelled.get("one_ou", 0.0),
                }
            )

        # The clock arm: the same blend, exponentiated and normalised to mean 1.
        bars = series[name]
        spans = np.arange(len(matrix[index]))
        own_clock = normalised(matrix[index])
        panel_clock = normalised(made)

        def at(table):
            def call(when: float) -> float:
                i = int((when - bars[0][0]) / (SPAN * HOUR))
                return float(table[min(max(i, 0), len(table) - 1)])

            return call

        times = list(bars[0][: len(spans) * SPAN])
        values = list(bars[1][: len(spans) * SPAN])
        if len(times) < 400:
            continue
        from till_infinity.statespace.seasonal import Profile

        middle = len(times) // 2
        profile = Profile.fit(times[:middle], values[:middle])
        base, null, got = clock_nats(
            times,
            values,
            {"own": at(own_clock), "panel": at(panel_clock)},
            middle,
            profile=profile,
        )
        clock_rows.append(
            {
                "name": name,
                "weight": best_w,
                "null": null,
                "own": got["own"] - null,
                "panel": got["panel"] - null,
                "profile": got.get("profile", float("nan")) - null,
                "profile_panel": got.get("profile x panel", float("nan")) - null,
            }
        )

    if ladder_rows:
        gains = [r["panel_ladder"] - r["own_ladder"] for r in ladder_rows]
        margins = [r["panel_margin"] - r["own_margin"] for r in ladder_rows]
        chose = sum(1 for r in ladder_rows if r["weight"] > 0)
        print(
            f"{label + ', ladder':<30}{len(ladder_rows):>6}"
            f"{statistics.median(gains):>+13.1f}{max(gains):>+11.1f}"
            f"{sum(1 for g in gains if g > 0):>8}"
            f"{statistics.median(margins):>+13.1f}{chose:>8}"
        )
    if clock_rows:
        # Against the established profile clock, which is the one that earns.
        usable = [r for r in clock_rows if math.isfinite(r["profile"])]
        if usable:
            gains = [r["profile_panel"] - r["profile"] for r in usable]
            print(
                f"{label + ', clock vs profile':<30}{len(usable):>6}"
                f"{statistics.median(gains):>+13.1f}{max(gains):>+11.1f}"
                f"{sum(1 for g in gains if g > 0):>8}"
                f"{statistics.median(r['profile'] for r in usable):>+13.1f}"
                f"{sum(1 for r in usable if r['weight'] > 0):>8}"
            )
        gains = [r["panel"] - r["own"] for r in clock_rows]
        print(
            f"{label + ', clock vs own vol':<30}{len(clock_rows):>6}"
            f"{statistics.median(gains):>+13.1f}{max(gains):>+11.1f}"
            f"{sum(1 for g in gains if g > 0):>8}"
            f"{statistics.median(r['own'] for r in clock_rows):>+13.1f}"
            f"{sum(1 for r in clock_rows if r['weight'] > 0):>8}"
        )


def main() -> None:
    print(
        f"spans of {SPAN} bars, blend weights {WEIGHTS} swept on the training\n"
        "half, both harnesses reused rather than reimplemented\n"
    )
    traded = [n for n in screen.TRADED if screen.load(n) is not None]
    synthetic = [
        n for n in screen.universe(screen.FRAME, cap=40) if screen.load(n) is not None
    ]
    covered = []
    for path in screen.CACHE.glob(f"*.{screen.FRAME}.npz"):
        if path.name.count(".") == 3:
            name = ".".join(path.name.split(".")[:2])
            got = screen.load(name)
            if got is not None:
                covered.append((len(got[0]), name))
    covered.sort(reverse=True)
    equities = [n for _, n in covered[:EQUITIES]]
    series = {n: screen.load(n) for n in traded + synthetic + equities}

    print("=" * 112)
    print("ARM 1  the two scorers, own volatility against the panel blend")
    print("=" * 112)
    print(
        f"{'':<30}{'rows':>6}{'median nats':>13}{'best':>11}{'helped':>8}"
        f"{'own margin':>13}{'w>0':>8}"
    )
    for label, names in (
        ("traded", traded),
        ("equities", equities),
        ("generated", synthetic),
    ):
        run_universe(label, names, series)
    print(
        "\n`median nats` is the panel arm less the own arm, so zero means the\n"
        "weight sweep chose 0 and the blend added nothing. `own margin` is the\n"
        "existing ladder result for comparison - the ladder's own margin over a\n"
        "single OU - so a gain can be read against the size of what it improves.\n"
        "`w>0` counts the instruments where the training half preferred a blend."
    )

    print("\n" + "=" * 112)
    print("ARM 2  the rotation null, where the factor is noise")
    print("=" * 112)
    print(
        f"{'':<30}{'rows':>6}{'median nats':>13}{'best':>11}{'helped':>8}"
        f"{'own margin':>13}{'w>0':>8}"
    )
    spinner = random.Random(SEED)
    for _ in range(max(REPS // 2, 1)):
        run_universe("traded, rotated", traded, series, rotate_with=spinner)
    run_universe("equities, rotated", equities, series, rotate_with=spinner)
    print(
        "\nWith the factor destroyed the sweep should pick `w = 0` and the\n"
        "median should be exactly zero. A positive median here would mean the\n"
        "blend is being paid for its extra freedom rather than its information."
    )


if __name__ == "__main__":
    main()
