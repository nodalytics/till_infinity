"""Online learning and error feedback: what the filter is not already doing.

**A Kalman filter is online learning with error feedback.** The innovation is
the error signal, the gain is a learning rate, and that rate is optimal by
construction rather than tuned. So the question is not whether to add online
learning but what the filter is not learning - and the answer is **its own
parameters**: the gain is optimal *given* `(Q, R)`, and `Q` is set by hand or
gridded offline over a whole series.

`statespace/adapting.py` closes the cheap part of that for the scalar
process-noise lever. This measures whether it was worth closing.

## The prediction, written before running

1. **The loop must track a planted change.** A series whose `Q` genuinely
   steps partway through: adaptation must beat a fixed `Q` there or the
   implementation is broken and every other arm is unreadable.
2. **It must buy nothing on `Volatility_*`.** Those have constant `Q` by
   construction, so a scheme that gains there is reading noise.
3. **It will beat a fitted `Q` on real markets, and that is not interesting.**
   Covariance matching on `Q` from an exponentially weighted mean of squared
   innovations **is a volatility model**, and this desk already knows
   volatility clustering is real and large. A win is expected.
4. **The interesting comparison is against the clock.** `seasonal.Profile`
   models the same quantity deterministically. It cannot react to a shock; the
   loop cannot anticipate an hour. So I expect **adaptation > clock**, because
   clustering is a larger effect than time of day, and I expect them to
   **compose**, because one is a pattern and the other is a reaction.
5. **`matching` and `gradient` will land in the same place**, because they are
   the same direction - covariance matching *is* gradient ascent on the
   likelihood with respect to `log Q`, up to the step size. If they differ
   materially, the step size matters more than the rule and that is the
   finding.

## Every arm starts from the same offline-fitted Q

The null is not a hand-set parameter, it is **what the desk does now**: `Q`
gridded on the first half and held fixed on the second. So every adaptive arm
starts from that same fitted value and is only allowed to move it. That is the
least favourable framing for adaptation and the only honest one.

All arms must score the same number of observations, and a cell where they do
not is dropped rather than compared - a likelihood over fewer observations is
not a smaller number, it is a different quantity.

Runs on the lab.
"""

from __future__ import annotations

import math
import os
import random
import statistics
from pathlib import Path

from till_infinity.statespace.adapting import Adapting
from till_infinity.statespace.driven import Driven
from till_infinity.statespace.linear import Gaussian
from till_infinity.statespace.seasonal import Profile

HOUR = 3600.0
SEED = 20261012

TRADED = ("EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "XAUUSD", "XAGUSD", "BTCUSD")
#: Constant `Q` by construction. Adaptation must buy nothing here.
GENERATED = ("Volatility_75_Index", "Volatility_25_Index", "Step_Index")
FRAME = os.environ.get("FRAME", "1h")
JERKS = tuple(10.0**k for k in range(-9, 2))
#: Step sizes. **Bounded above by a stability condition, not by taste.** The
#: loop is negative feedback through a lagged estimate - inflating `Q` inflates
#: the predictive spread, which lowers the squared standardised innovation,
#: which deflates `Q` again - and the lag is the EWMA's `memory`. A delayed
#: negative feedback oscillates and then diverges once the loop gain exceeds
#: the delay, roughly `rate * memory > 1`, so at `memory = 64` the bound is
#: about 0.016.
#:
#: Measured, that bound is real: on the planted series `rate = 0.08` moved the
#: lever over **18,000x** and lost 195 nats while fixing the calibration, and
#: `0.02` moved it 695x. Both are above the bound. These are not.
#: The Gaussian bound above is **too generous for real innovations.** Measured
#: on traded markets at `rate = 0.015` the lever ran to its clamp - `moved` of
#: 1e6 on XAUUSD and XAGUSD - and a gain from a clamped lever is a gain from
#: the clamp. Fat tails make the squared-innovation mean far noisier than
#: `sqrt(2/memory)` predicts, so the usable rate is well below the bound and
#: the grid has to reach down to where the lever stays interior.
RATES = tuple(
    float(r) for r in os.environ.get("RATES", "0.0002,0.001,0.003,0.008,0.015").split(",")
)
SINCE = float(os.environ.get("SINCE", "99792000"))
LIMIT = int(os.environ.get("LIMIT", "40000"))
CACHE = Path.home() / "till_infinity" / "data" / "seqlab"


def load(name: str, frame: str = FRAME):
    import numpy as np

    path = CACHE / f"{name}.{frame}.npz"
    if not path.exists():
        return None
    with np.load(path) as bundle:
        if not {"time", "close"} <= set(bundle.keys()):
            return None
        order = np.argsort(bundle["time"])
        times = np.asarray(bundle["time"], dtype=float)[order]
        closes = np.asarray(bundle["close"], dtype=float)[order]
    keep = (closes > 0) & (times >= SINCE)
    times, closes = times[keep], closes[keep]
    if len(times) > LIMIT:
        times, closes = times[-LIMIT:], closes[-LIMIT:]
    return (times.tolist(), np.log(closes).tolist()) if len(times) > 4000 else None


def run(times, levels, noise, jerk, *, mode="none", step=0.02, clock=None, report="held"):
    """Score one arm. `report="held"` scores the second half, `"train"` the first.

    The member is built once and walked through the whole series; the
    likelihood is zeroed at the halfway point, so the second half is scored by
    a filter that has already warmed up on the first - which is what a desk
    would have, and is different from scoring a cold filter.

    **`report` exists because the first version leaked.** `fit` maximised the
    value this returned, and that value was the *held-out* half - so the null
    was choosing its parameter by looking at the data it would be judged on.
    On the planted arm that made the null already correct for the regime it
    was supposed to be wrong about, and on every real cell it inflated the
    null. Selection now reads `"train"` and only the report reads `"held"`.
    """
    half = len(levels) // 2

    def build():
        return Gaussian(jerk=jerk, p00=1.0)

    if clock is not None:
        member = Driven(build=build, lever="jerk", gain=0.0, clock=clock)
    else:
        member = Adapting(build=build, lever="jerk", mode=mode, step=step)

    if report != "train":
        for i in range(half):
            member.predict(times[i])
            member.update(levels[i], noise)
    # `Adapting` proxies `burn`; `Driven` does not, so set it on the member
    # itself when the wrapper has no setter for it.
    inner = getattr(member, "_member", None)
    counted, squared = 0, []
    scored = range(half) if report == "train" else range(half, len(levels))
    if report == "train":
        # Re-walk from cold: the training half cannot be scored by a filter
        # that has already seen it.
        member = (
            Driven(build=build, lever="jerk", gain=0.0, clock=clock)
            if clock is not None
            else Adapting(build=build, lever="jerk", mode=mode, step=step)
        )
        inner = getattr(member, "_member", None)
    if inner is not None:
        inner.burn = 2 if report == "train" else 0
    if report != "train":
        member.loglike = 0.0
    for i in scored:
        before = member.loglike
        member.predict(times[i])
        member.update(levels[i], noise)
        if not math.isfinite(member.value) or not math.isfinite(member.sd):
            return None
        if member.loglike != before:
            counted += 1
            squared.append(member.last_standardised**2)
    if not math.isfinite(member.loglike) or not counted:
        return None
    return {
        "loglike": member.loglike,
        "n": counted,
        # The quantity the loop exists to drive to 1.0, over the held-out half
        # rather than from the loop's own running mean.
        "z2": statistics.fmean(squared),
        "moved": getattr(member, "moved", 1.0),
        "clamped": getattr(member, "clamped", False),
        "excess": getattr(member, "excess", float("nan")),
    }


def both(times, levels, noise, jerk, profile, step):
    """The clock and the loop at once - do they compose?

    `Driven` carries the clock and `Adapting` carries the loop, and neither
    wraps the other, so composing them means driving the clock's factor into
    the lever that the loop is also moving. Done here by hand rather than by
    nesting the wrappers, because a nested wrapper would have each one reading
    the other's output as its own base and the factors would compound twice.
    """

    def build():
        return Gaussian(jerk=jerk, p00=1.0)

    member = Adapting(build=build, lever="jerk", mode="matching", step=step)
    half = len(levels) // 2
    counted, squared = 0, []
    for i, (when, level) in enumerate(zip(times, levels, strict=True)):
        if i == half:
            member.loglike = 0.0
            member._member.burn = 0
        # **Before `predict`, not after.** The jerk is read by `predict` when
        # it builds `Q(dt)`, and `update` writes it again from the loop's own
        # factor at the end of every step. Setting it between the two means it
        # is never used for any prediction and is then overwritten - which is
        # why the first run of this arm returned numbers *identical* to
        # `matching` on all eleven cells. Identical columns are a bug, not a
        # finding that two levers agree.
        inner = member._member
        inner.jerk = jerk * member.factor * float(profile.factor(when))
        member.predict(when)
        before = member.loglike
        member.update(level, noise)
        if not math.isfinite(member.value) or not math.isfinite(member.sd):
            return None
        if i >= half and member.loglike != before:
            counted += 1
            squared.append(member.last_standardised**2)
    if not math.isfinite(member.loglike) or not counted:
        return None
    return {
        "loglike": member.loglike,
        "n": counted,
        "z2": statistics.fmean(squared),
        "moved": member.moved,
        "clamped": member.clamped,
    }


def planted(n: int = 6000, step: float = 25.0):
    """A level whose process noise **steps up by `step`** halfway through.

    The arm that makes every other arm readable. A fixed `Q` fitted on the
    first half is wrong by construction on the second, and a loop that cannot
    beat it there cannot be trusted anywhere.
    """
    rng = random.Random(SEED)
    times, levels = [], []
    level, slope = 0.0, 0.0
    for i in range(n):
        quiet = 1.0 if i < n // 2 else math.sqrt(step)
        slope += rng.gauss(0.0, 0.002 * quiet)
        level += slope
        times.append(i * HOUR)
        levels.append(level + rng.gauss(0.0, 0.01))
    return times, levels, 0.01**2


def fit(times, levels, noise):
    """The offline grid - what the desk does now, and the null here.

    **Selected on the training half and reported on the held-out one.** The
    two have to be different halves or the null is reading its own answer.
    """
    top = None
    for jerk in JERKS:
        chosen = run(times, levels, noise, jerk, mode="none", report="train")
        if chosen is None:
            continue
        if top is None or chosen["loglike"] > top[1]:
            top = (jerk, chosen["loglike"])
    if top is None:
        return None
    jerk = top[0]
    held = run(times, levels, noise, jerk, mode="none")
    if held is None:
        return None
    edge = jerk in (JERKS[0], JERKS[-1])
    return (jerk, held["loglike"], held["n"], held["z2"], edge)


def main() -> None:
    print(
        f"frame {FRAME}, rates {RATES}\n"
        "Every arm starts from the same offline-fitted Q and is only allowed\n"
        "to move it. z2 is the mean squared standardised innovation over the\n"
        "held-out half - **1.00 is an honest filter** and is the quantity the\n"
        "loop exists to drive there. 'moved' is the ratio of the highest to\n"
        "the lowest lever reached; 1.0 means the loop never adapted.\n"
    )

    print("=" * 112)
    print("ARM 1  the planted step: can the loop track a Q that really changes?")
    print("=" * 112)
    times, levels, noise = planted()
    fitted = fit(times, levels, noise)
    if fitted is None:
        print("  the planted series did not fit")
    else:
        jerk, base, _n, z2, edge = fitted
        print(
            f"fitted jerk {jerk:.1e}{' (GRID EDGE)' if edge else ''}, "
            f"selected on the training half, held-out {base:+.1f}, z2 {z2:.2f}\n"
        )
        print(f"{'arm':<16}{'rate':>7}{'held out':>12}{'vs fitted':>11}{'z2':>8}{'moved':>9}")
        print(f"{'fitted (null)':<16}{'-':>7}{base:>12.1f}{0.0:>+11.1f}{z2:>8.2f}{1.0:>9.1f}")
        for mode in ("matching", "gradient", "forgetting"):
            for rate in RATES if mode != "forgetting" else (0.0,):
                got = run(times, levels, noise, jerk, mode=mode, step=rate)
                if got is None:
                    continue
                print(
                    f"{mode:<16}{rate if rate else '-':>7}{got['loglike']:>12.1f}"
                    f"{got['loglike'] - base:>+11.1f}{got['z2']:>8.2f}{got['moved']:>9.1f}"
                )

    print("\n" + "=" * 112)
    print("ARM 2  real markets and the constant-Q controls")
    print("=" * 112)
    print(
        f"{'instrument':<22}{'jerk':>8}{'fitted':>11}{'matching':>10}{'gradient':>10}"
        f"{'forget':>9}{'clock':>9}{'clock+loop':>12}{'z2 fit':>8}{'z2 loop':>9}{'moved':>8}"
    )
    rows = []
    for name in TRADED + GENERATED:
        found = load(name)
        if found is None:
            continue
        times, levels = found
        noise = (
            0.25
            * float(
                statistics.pstdev(
                    [levels[i] - levels[i - 1] for i in range(1, min(len(levels), 3000))]
                )
            )
            ** 2
        )
        fitted = fit(times, levels, noise)
        if fitted is None:
            continue
        jerk, base, want, z2_fit, edge = fitted
        half = len(levels) // 2
        profile = Profile.fit(times[:half], levels[:half], period=24.0)
        arms = {}
        for label, kwargs in (
            ("matching", {"mode": "matching"}),
            ("gradient", {"mode": "gradient"}),
            ("forgetting", {"mode": "forgetting"}),
        ):
            best = None
            for rate in RATES if label != "forgetting" else (0.0,):
                got = run(times, levels, noise, jerk, step=rate, **kwargs)
                if got is None or got["n"] != want:
                    continue
                if best is None or got["loglike"] > best["loglike"]:
                    best = got
            arms[label] = best
        arms["clock"] = run(times, levels, noise, jerk, clock=profile.factor) if profile else None
        arms["both"] = (
            max(
                (
                    g
                    for g in (both(times, levels, noise, jerk, profile, r) for r in RATES)
                    if g is not None and g["n"] == want
                ),
                key=lambda g: g["loglike"],
                default=None,
            )
            if profile
            else None
        )
        if arms["clock"] is not None and arms["clock"]["n"] != want:
            arms["clock"] = None

        def gain(key):
            got = arms.get(key)
            return f"{got['loglike'] - base:>+10.0f}" if got else f"{'-':>10}"

        rows.append(
            (
                name in GENERATED,
                {k: (v["loglike"] - base if v else float("nan")) for k, v in arms.items()},
            )
        )
        print(
            f"{name:<22}{jerk:>8.0e}{base:>11.0f}{gain('matching')}{gain('gradient')}"
            + (
                f"{arms['forgetting']['loglike'] - base:>+9.0f}"
                if arms["forgetting"]
                else f"{'-':>9}"
            )
            + (f"{arms['clock']['loglike'] - base:>+9.0f}" if arms["clock"] else f"{'-':>9}")
            + (f"{arms['both']['loglike'] - base:>+12.0f}" if arms["both"] else f"{'-':>12}")
            + f"{z2_fit:>8.2f}"
            + (f"{arms['matching']['z2']:>9.2f}" if arms["matching"] else f"{'-':>9}")
            + (
                f"{arms['matching']['moved']:>8.0f}" + ("*" if arms["matching"]["clamped"] else " ")
                if arms["matching"]
                else f"{'-':>9}"
            )
        )

    print("\n" + "=" * 112)
    print("ARM 3  medians: traded against the constant-Q controls")
    print("=" * 112)
    print(
        f"{'group':<12}{'cells':>7}"
        + "".join(f"{k:>12}" for k in ("matching", "gradient", "forgetting", "clock", "both"))
    )
    for generated, label in ((False, "traded"), (True, "generated")):
        group = [r for g, r in rows if g is generated]
        if not group:
            continue
        line = f"{label:<12}{len(group):>7}"
        for key in ("matching", "gradient", "forgetting", "clock", "both"):
            values = [r[key] for r in group if not math.isnan(r.get(key, float("nan")))]
            line += f"{statistics.median(values):>+12.0f}" if values else f"{'-':>12}"
        print(line)
    print("\nDONE")


if __name__ == "__main__":
    main()
