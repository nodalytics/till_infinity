"""Three small open questions, all about a periodic profile or a second leg.

The remaining items on the inventory that fit in one harness.

## 1. Does a weekly period add anything over a daily one?

`seasonal.PERIODS` defaults to `(24.0, 168.0)` and `Profile.period` says a
week "is the other one worth trying, and the weekend gap makes it harder" -
so the week is **written and never measured against a day alone**. That is the
gap, and it is a cheap one to close: fit the profile at 24, at 168, and at
both, and score each on held-out data.

Measured on **Q**, not on the level. Intraday pattern on this desk lives in
volatility, not in direction - the profile drives the process noise squared
and never the measurement noise - so a weekly profile has to earn its place in
the same currency as the daily one did.

## 2. Does the session profile drift over the years?

If the 14-15 UTC peak is a fixture, one profile fitted once is enough and the
constant can be written down. If it drifts, the profile has to be refitted and
a hardcoded shape goes stale. Two readings:

* the **correlation between successive years' hourly shapes**, which says
  whether the pattern is the same pattern;
* whether **last year's profile beats a pooled one** on the next year, which
  is the only version of the question that changes what the code should do. A
  drifting profile that is still better fitted on everything is a profile that
  should be fitted on everything.

## 3. Is a third leg worth it?

`Relating` already takes `legs`, so a third instrument costs nothing to try.
The pair work found a USDJPY/XAGUSD relationship; this asks whether a second
independent leg improves it, held out, against `legs = 1`.

**With the control that caught two leaks before**: an independent placebo pair
of Deriv volatility indices as the third leg. A third leg that helps as much
when it is a volatility index as when it is a related market is a third leg
that is adding degrees of freedom, not information.

Runs on the lab.
"""

from __future__ import annotations

import math
import os
import statistics
from pathlib import Path

from till_infinity.structures.statespace.driven import Driven
from till_infinity.structures.statespace.linear import Gaussian
from till_infinity.structures.statespace.relating import Relating
from till_infinity.structures.statespace.seasonal import Profile

HOUR = 3600.0
SEED = 20261012

TRADED = ("EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "XAUUSD", "XAGUSD", "BTCUSD")
PLACEBO = ("Volatility_75_Index", "Volatility_25_Index")
FRAME = os.environ.get("FRAME", "1h")
SINCE = float(os.environ.get("SINCE", "99792000"))
LIMIT = int(os.environ.get("LIMIT", "60000"))
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
    return (times, np.log(closes)) if len(times) > 4000 else None


def score(times, levels, profiles, noise: float, jerk: float = 1e-3):
    """Held-out log-likelihood of a `Driven` member whose Q follows the profiles.

    `profiles` is a tuple, and the clock multiplies their factors together -
    which is what "a daily *and* a weekly profile" means: one shape per period
    and the product is the softness at that moment. An empty tuple is the flat
    arm, the null every profile has to beat.
    """

    def clock(when: float) -> float:
        total = 1.0
        for profile in profiles:
            total *= profile.factor(when)
        return total

    member = Driven(
        build=lambda: Gaussian(jerk=jerk),
        lever="jerk",
        gain=0.0,  # no exogenous control here; the clock is the whole point
        clock=clock if profiles else None,
    )
    half = len(levels) // 2
    # **`predict` is where the clock lands, not `update`.** `Driven.update`
    # forwards straight to the wrapped member, so passing `when` to it makes
    # the member predict internally and the softness is never applied. The
    # first run of this arm did exactly that and reported all four arms
    # identical to 0.1 nats - a clock with no effect, which looked like a
    # null result and was a wiring bug.
    for i in range(half):
        member.predict(times[i])
        member.update(levels[i], noise)
    member.loglike = 0.0
    # `Driven` proxies `loglike` to the wrapped member but has no `burn`, so
    # the burn-in is set on the member itself.
    inner = member._member
    if inner is not None:
        inner.burn = 0
    counted = 0
    for i in range(half, len(levels)):
        before = member.loglike
        member.predict(times[i])
        member.update(levels[i], noise)
        if not math.isfinite(member.value) or not math.isfinite(member.sd):
            return -math.inf, counted
        if member.loglike != before:
            counted += 1
    return (member.loglike if math.isfinite(member.loglike) else -math.inf), counted


#: Wide on purpose. The first gridded run had the best jerk on an edge in 9
#: of 10 cells, and an edge on the *flat* arm would understate it and inflate
#: the clock's margin - so the grid has to be wide enough that the winner is
#: interior, and the `edge` column says when it is not.
JERKS = tuple(10.0**k for k in range(-9, 2))

#: The period ladder, in hours, each with the mechanism that would make it
#: real. **Both ends extended** past the `(24, 168)` the package shipped with:
#: shorter, because the session rotation is an eight-hour cycle and the day is
#: not the finest clock a market has; longer, because month-end rebalancing and
#: the quarterly cycle are documented effects that a weekly period cannot see.
#:
#: `48` and `100` are deliberate **controls with no mechanism** - two days and
#: a non-round 100 hours. A ladder in which every rung gains is a ladder
#: measuring flexibility, and these two rungs say which it is.
PERIODS_LADDER = (
    (4.0, "4h, the bar boundary"),
    (8.0, "8h, session rotation"),
    (12.0, "12h, half a day"),
    (24.0, "24h, the day"),
    (48.0, "48h, no mechanism (control)"),
    (100.0, "100h, no mechanism (control)"),
    (168.0, "168h, the week"),
    (336.0, "336h, the fortnight"),
    (672.0, "672h, four weeks, month end"),
    (2190.0, "2190h, the quarter"),
    (8766.0, "8766h, the year"),
)
#: A harmonic fit needs several samples per cycle to be a shape rather than an
#: interpolation, and several cycles in the sample to be a *season* rather than
#: a trend. Below either, the period is reported as unresolvable instead of
#: being silently fitted - which is the same discipline `inputs.resolvable`
#: applies to windows.
LEAST_SAMPLES_PER_CYCLE = 4.0
LEAST_CYCLES = 8.0


def mean_factor(times, profiles) -> float:
    """The clock's average multiplier over the sample.

    **The confound this arm nearly reported as a result.** `Profile.factor`
    is a multiplier whose mean over a sample need not be one, so switching the
    clock on changes the *average* process noise as well as its shape. With a
    fixed base jerk the clocked arm is then being scored on a different
    average Q, and a profile with real amplitude loses for a reason that has
    nothing to do with seasonality.

    The first run of this arm did exactly that: the daily profile lost 24 to
    213 nats on traded instruments and **1 nat on the placebos** - whose
    profiles have no amplitude, so they move Q by nothing and cost nothing.
    That pattern is the confound's fingerprint, not a null.

    The fix is to grid the base jerk for every arm, so each is scored at its
    own best average and only the shape differs. This number is printed so the
    confound stays visible rather than being silently corrected away.
    """
    if not profiles:
        return 1.0
    step = max(len(times) // 2000, 1)
    total, count = 0.0, 0
    for when in times[::step]:
        value = 1.0
        for profile in profiles:
            value *= profile.factor(float(when))
        total += value
        count += 1
    return total / count if count else 1.0


def best(times, levels, profiles, noise: float):
    """The best held-out likelihood over the jerk grid, and where it landed."""
    top = None
    for jerk in JERKS:
        got, counted = score(times, levels, profiles, noise, jerk=jerk)
        if not math.isfinite(got):
            continue
        if top is None or got > top[0]:
            top = (got, jerk, counted)
    return top


def arm_one() -> None:
    print("=" * 104)
    print("ARM 1  does a weekly profile add over a daily one? Held out, on Q.")
    print("=" * 104)
    print(
        f"{'instrument':<22}{'n':>7}{'flat':>11}{'day':>11}{'week':>11}{'both':>11}"
        f"{'day gain':>10}{'week adds':>11}{'mean f':>8}{'edge':>2}"
    )
    print("every arm gets its own best base jerk, so only the shape differs.\n")
    rows = []
    for name in TRADED + PLACEBO:
        found = load(name)
        if found is None:
            continue
        times, levels = found
        half = len(levels) // 2
        day = Profile.fit(times[:half], levels[:half], period=24.0)
        week = Profile.fit(times[:half], levels[:half], period=168.0)
        if day is None or week is None:
            continue
        noise = (
            0.25
            * float(
                statistics.pstdev(
                    [levels[i] - levels[i - 1] for i in range(1, min(len(levels), 3000))]
                )
            )
            ** 2
        )
        arms = {}
        for label, profiles in (
            ("flat", ()),
            ("day", (day,)),
            ("week", (week,)),
            ("both", (day, week)),
        ):
            top = best(times, levels, profiles, noise)
            if top is None:
                break
            arms[label] = top
        if len(arms) != 4:
            continue
        if len({c for _g, _j, c in arms.values()}) != 1:
            print(f"{name:<22}  arms scored different counts, skipped")
            continue
        flat, dayly, weekly, both = (arms[k][0] for k in ("flat", "day", "week", "both"))
        edge = "*" if arms["day"][1] in (JERKS[0], JERKS[-1]) else " "
        print(
            f"{name:<22}{arms['flat'][2]:>7}{flat:>11.1f}{dayly:>11.1f}"
            f"{weekly:>11.1f}{both:>11.1f}{dayly - flat:>+10.1f}{both - dayly:>+11.1f}"
            f"{mean_factor(times, (day,)):>8.2f}{edge:>2}"
        )
        rows.append((name in PLACEBO, dayly - flat, both - dayly, weekly - flat))
    if rows:
        for placebo, label in ((False, "traded"), (True, "placebo")):
            group = [r for r in rows if r[0] is placebo]
            if not group:
                continue
            print(
                f"\n{label} median: day over flat {statistics.median(r[1] for r in group):+.1f}, "
                f"week over flat {statistics.median(r[3] for r in group):+.1f}, "
                f"week on top of day {statistics.median(r[2] for r in group):+.1f}"
            )


def arm_one_b() -> None:
    print("\n" + "=" * 104)
    print("ARM 1b  the period ladder, both ends: what else is worth a harmonic?")
    print("=" * 104)
    print(
        "Each period is scored **on top of the daily profile**, so the column\n"
        "is what it adds to what already works. The day's own gain is shown\n"
        "for scale. Unresolvable rungs are marked rather than fitted: a\n"
        "harmonic needs >= 4 samples per cycle and >= 8 cycles in the sample.\n"
        "48h and 100h have no mechanism and are there to show what a rung\n"
        "gains from flexibility alone.\n"
    )
    for frame, names in (("1h", TRADED[:5] + PLACEBO), ("1d", ("EURUSD", "USDJPY", "XAUUSD"))):
        bar = 1.0 if frame == "1h" else 24.0
        print(f"--- {frame} bars ---")
        print(
            f"{'period':<30}{'cycles':>8}{'per cyc':>9}"
            + "".join(f"{n[:7]:>9}" for n in names)
            + f"{'median':>9}"
        )
        loaded = {}
        for name in names:
            found = load(name, frame)
            if found is None:
                continue
            times, levels = found
            half = len(levels) // 2
            day = Profile.fit(times[:half], levels[:half], period=24.0)
            if day is None:
                continue
            noise = (
                0.25
                * float(
                    statistics.pstdev(
                        [levels[i] - levels[i - 1] for i in range(1, min(len(levels), 3000))]
                    )
                )
                ** 2
            )
            base = best(times, levels, (day,), noise)
            flat = best(times, levels, (), noise)
            if base is None or flat is None:
                continue
            loaded[name] = (times, levels, day, noise, base[0], flat[0])
        if not loaded:
            continue
        shown = [n for n in names if n in loaded]
        spans = {n: (loaded[n][0][-1] - loaded[n][0][0]) / HOUR for n in shown}
        print(
            f"{'(the day over flat)':<30}{'-':>8}{'-':>9}"
            + "".join(f"{loaded[n][4] - loaded[n][5]:>+9.0f}" for n in shown)
            + f"{statistics.median(loaded[n][4] - loaded[n][5] for n in shown):>+9.0f}"
        )
        for period, label in PERIODS_LADDER:
            cycles = statistics.median(spans[n] / period for n in shown)
            per_cycle = period / bar
            if per_cycle < LEAST_SAMPLES_PER_CYCLE or cycles < LEAST_CYCLES:
                why = "too few samples" if per_cycle < LEAST_SAMPLES_PER_CYCLE else "too few cycles"
                print(f"{label:<30}{cycles:>8.1f}{per_cycle:>9.1f}   unresolvable: {why}")
                continue
            gains = []
            line = ""
            for name in shown:
                times, levels, day, noise, with_day, _flat = loaded[name]
                half = len(levels) // 2
                extra = Profile.fit(times[:half], levels[:half], period=period)
                if extra is None:
                    line += f"{'-':>9}"
                    continue
                top = best(times, levels, (day, extra), noise)
                if top is None:
                    line += f"{'-':>9}"
                    continue
                gains.append(top[0] - with_day)
                line += f"{top[0] - with_day:>+9.0f}"
            print(
                f"{label:<30}{cycles:>8.1f}{per_cycle:>9.1f}{line}"
                + (f"{statistics.median(gains):>+9.0f}" if gains else f"{'-':>9}")
            )
        print()


def arm_one_c() -> None:
    """The question the ladder's own controls asked instead.

    The ladder put two rungs in with no mechanism, to show what a period gains
    from flexibility alone - and they answered a different question. **A second
    profile at 24 hours gained +324 and one at 48 hours gained +399**, more
    than any genuinely new period in the ladder, while 100 hours gained -3.

    The reason is that harmonic `j` of a 48-hour period sits at `48/j` hours,
    so `j = 2` *is* the day: a 48h profile re-fits the daily shape with more
    harmonics. 100 hours has no harmonic near 24 and gains nothing. So the two
    controls are not a pair - **100h is the honest one**, and against it no new
    period in the ladder earns its place.

    What they point at is that the day's shape is under-described rather than
    the clock being incomplete. So: sweep the harmonic count on the 24-hour
    period and find where it stops paying.
    """
    print("\n" + "=" * 104)
    print("ARM 1c  more harmonics on the day, which is what the controls pointed at")
    print("=" * 104)
    print(
        "Held out, each count against the flat arm, own best base jerk. The\n"
        "placebo columns are the check: a volatility index has no session, so\n"
        "every count there is fitting noise and should pay nothing.\n"
    )
    names = TRADED[:5] + PLACEBO
    print(f"{'harmonics':<12}" + "".join(f"{n[:9]:>10}" for n in names) + f"{'median':>10}")
    loaded = {}
    for name in names:
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
        flat = best(times, levels, (), noise)
        if flat is None:
            continue
        loaded[name] = (times, levels, noise, flat[0])
    shown = [n for n in names if n in loaded]
    for count in (1, 2, 3, 4, 6, 8, 12):
        line, gains = "", []
        for name in shown:
            times, levels, noise, flat = loaded[name]
            half = len(levels) // 2
            profile = Profile.fit(times[:half], levels[:half], harmonics=count, period=24.0)
            if profile is None:
                line += f"{'-':>10}"
                continue
            top = best(times, levels, (profile,), noise)
            if top is None:
                line += f"{'-':>10}"
                continue
            gains.append(top[0] - flat)
            line += f"{top[0] - flat:>+10.0f}"
        star = " *" if count == 3 else ""
        print(
            f"{str(count) + star:<12}{line}"
            + (f"{statistics.median(gains):>+10.0f}" if gains else f"{'-':>10}")
        )
    print("\n* 3 is the shipped PROFILE_HARMONICS.")


def arm_two() -> None:
    print("\n" + "=" * 104)
    print("ARM 2  does the session profile drift? Per-year shapes, and refit against pooled.")
    print("=" * 104)
    import datetime as dt

    import numpy as np

    print(
        f"{'instrument':<22}{'years':>7}{'median year-to-year r':>24}"
        f"{'worst':>8}{'peak hour: mode':>18}{'spread':>8}"
    )
    for name in TRADED + PLACEBO:
        found = load(name)
        if found is None:
            continue
        times, levels = found
        buckets: dict[int, list[int]] = {}
        for i, when in enumerate(times):
            buckets.setdefault(dt.datetime.utcfromtimestamp(float(when)).year, []).append(i)
        shapes, peaks = {}, []
        for year, index in sorted(buckets.items()):
            if len(index) < 2000:
                continue
            got = Profile.fit([times[i] for i in index], [levels[i] for i in index], period=24.0)
            if got is None:
                continue
            shape = got.shape()
            shapes[year] = shape
            peaks.append(int(max(range(len(shape)), key=lambda h: shape[h])))
        if len(shapes) < 3:
            continue
        years = sorted(shapes)
        agreements = []
        for a, b in zip(years[:-1], years[1:], strict=True):
            left, right = np.asarray(shapes[a]), np.asarray(shapes[b])
            if left.std() > 0 and right.std() > 0:
                agreements.append(float(np.corrcoef(left, right)[0, 1]))
        if not agreements:
            continue
        mode = max(set(peaks), key=peaks.count)
        print(
            f"{name:<22}{len(shapes):>7}{statistics.median(agreements):>24.3f}"
            f"{min(agreements):>8.3f}{mode:>14}:00  "
            f"{sum(1 for p in peaks if p == mode) / len(peaks):>6.2f}"
        )


def _slope_t(series):
    """Dickey-Fuller slope and its t, on `d(x) = a + b x`. Reverting is `b < 0`."""
    if len(series) < 200:
        return 0.0, 0.0
    left = series[:-1]
    steps = [b - a for a, b in zip(series[:-1], series[1:], strict=True)]
    mx = statistics.fmean(left)
    my = statistics.fmean(steps)
    den = sum((x - mx) ** 2 for x in left)
    if den <= 0:
        return 0.0, 0.0
    slope = sum((x - mx) * (y - my) for x, y in zip(left, steps, strict=True)) / den
    residual = [y - (my + slope * (x - mx)) for x, y in zip(left, steps, strict=True)]
    spread = sum(r * r for r in residual) / max(len(residual) - 2, 1)
    error = math.sqrt(spread / den) if spread > 0 else 0.0
    return slope, (slope / error if error > 0 else 0.0)


def spread_from(times, dependent, legs, count: int):
    """The residual after hedging `dependent` against `count` legs, lagged.

    **The hedge ratio is the one as of the previous reading**, so the spread
    could have been formed at the time rather than with hindsight. That is the
    `lagged` arm the pair work established, and it is the only version a desk
    could trade.

    `centre=True`, which is `Relating`'s default and matters here: an
    uncentred basket carries the *level*, and USDJPY against XAGUSD is not
    cointegrated in levels, so the residual is non-stationary and swamps
    everything. The first version of this arm compared leg counts on
    `Relating`'s own likelihood with an uncentred fit and a fixed noise, and
    reported the **placebo gaining the most** - 3.1e8 nats for a volatility
    index, more than any real market. That is what "which third series best
    absorbs a non-stationary residual" looks like, and it is not the question.
    """
    unit = (
        statistics.pstdev(
            [dependent[i] - dependent[i - 1] for i in range(1, min(len(dependent), 5000))]
        )
        or 1e-6
    )
    hedge = Relating(legs=count, centre=True)
    carried = []
    for i, when in enumerate(times):
        carried.append(hedge.ratios if len(hedge.ratios) == count else None)
        hedge.predict(when)
        hedge.update(dependent[i], unit, when, against=[leg[i] for leg in legs[:count]])
    out = []
    for i, ratios in enumerate(carried):
        if ratios is None or len(ratios) != count:
            continue
        out.append(dependent[i] - sum(r * leg[i] for r, leg in zip(ratios, legs, strict=False)))
    return out


def arm_three() -> None:
    print("\n" + "=" * 104)
    print("ARM 3  is a third leg worth it? Judged on the spread, not on Relating's likelihood.")
    print("=" * 104)
    print(
        "A reverting spread has a negative Dickey-Fuller slope and a t below the\n"
        "critical value. The question is whether a second independent leg makes\n"
        "the spread revert harder than one leg does - and whether a volatility\n"
        "index does the same, which would mean the leg is buying freedom.\n"
    )
    print(
        f"{'dependent':<10}{'leg 1':<10}{'leg 2':<24}{'n':>7}"
        f"{'one leg t':>11}{'two legs t':>12}{'better by':>11}"
    )
    base = load("USDJPY")
    partner = load("XAGUSD")
    if base is None or partner is None:
        print("  missing the pair")
        return
    for third in ("XAUUSD", "EURUSD", "BTCUSD") + PLACEBO:
        other = load(third)
        if other is None:
            continue
        n = min(len(base[0]), len(partner[0]), len(other[0]))
        times = base[0][-n:]
        dependent = base[1][-n:]
        legs = [partner[1][-n:], other[1][-n:]]
        one = spread_from(times, dependent, legs, 1)
        two = spread_from(times, dependent, legs, 2)
        if len(one) < 500 or len(two) < 500:
            continue
        _s1, t1 = _slope_t(one)
        _s2, t2 = _slope_t(two)
        tag = "  (placebo)" if third in PLACEBO else ""
        print(
            f"{'USDJPY':<10}{'XAGUSD':<10}{third + tag:<24}{n:>7}"
            f"{t1:>11.2f}{t2:>12.2f}{t1 - t2:>+11.2f}"
        )


def main() -> None:
    print(f"frame {FRAME}\n")
    arm_one()
    arm_one_b()
    arm_one_c()
    arm_two()
    arm_three()
    print("\nDONE")


if __name__ == "__main__":
    main()
