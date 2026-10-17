"""Does sampling in volume time make the Q clock unnecessary?

The `seasonal.Profile` clock on `Q` is worth **+1055 nats** median on traded
instruments at 1h, by modelling how the variance of an hourly increment varies
with the hour of the day. The subordination literature - Clark 1973,
Ane-Geman 2000 - says that pattern is not about *time* at all: returns are
closer to i.i.d. Gaussian when sampled in equal increments of **activity**, and
a calendar hour at 14:00 UTC simply contains more activity than one at 02:00.

If that is right here, the clock is a **calendar artefact** and the fix is a
sampling change rather than a member. If it is wrong, the pattern is in time
and not in activity, which is a stronger claim than the clock currently makes.

## The variable is the right one, not a proxy

MT5's `volume` on an FX feed is **tick volume** - the number of price changes
in the bar - which is exactly the trade-count variable the subordination
literature uses, rather than a notional stand-in for it.

## The control validates the method, not only the result

The Deriv generated feeds have **exactly constant** volume: `Volatility_75`
posts 90 ticks every 3m bar and 1800 every hour, with an interquartile range of
**zero**. So for those feeds volume time *is* calendar time by construction,
and the two clocks must agree to rounding. A difference there is a bug in the
resampling, not a finding - which makes them a test of this harness before they
are a control on its answer.

It is also prior support for the hypothesis: constant activity, constant
volatility, which is what those feeds show.

## Likelihoods are not comparable across clocks, and that is the trap

Resampling changes the observation set, so a density over volume bars and a
density over calendar bars are **different quantities** and their log-
likelihoods cannot be subtracted. Every comparison here is therefore either

* **scale-free** - `Profile.extent()` is peak over trough, kurtosis is a
  ratio of moments, the squared-return autocorrelation is a correlation; or
* **internal to one clock** - the clock's gain over a flat arm, both fitted on
  the same observation set, reported **per bar** so the two clocks' figures
  are at least on the same footing.

The headline is `extent`, because it measures the thing directly: how much the
variance of an increment depends on the hour it fell in. One means no profile.

Runs on the lab.
"""

from __future__ import annotations

import math
import os
import statistics
from pathlib import Path

from till_infinity.statespace.driven import Driven
from till_infinity.statespace.linear import Gaussian
from till_infinity.statespace.seasonal import Profile

HOUR = 3600.0
SEED = 20261012

TRADED = ("EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "XAUUSD", "XAGUSD", "BTCUSD")
#: Constant tick volume by construction - volume time is calendar time here.
GENERATED = ("Volatility_75_Index", "Volatility_25_Index", "Step_Index", "Jump_100_Index")
#: The finest frame carrying volume, which sets how precisely a volume bar can
#: be closed. At 3m a volume bar's boundary is accurate to three minutes.
FINE = os.environ.get("FINE", "3m")
COARSE = os.environ.get("COARSE", "1h")
JERKS = tuple(10.0**k for k in range(-9, 2))
SINCE = float(os.environ.get("SINCE", "99792000"))
LIMIT = int(os.environ.get("LIMIT", "120000"))
CACHE = Path.home() / "till_infinity" / "data" / "seqlab"


def load(name: str, frame: str):
    import numpy as np

    path = CACHE / f"{name}.{frame}.npz"
    if not path.exists():
        return None
    with np.load(path) as bundle:
        if not {"time", "close", "volume"} <= set(bundle.keys()):
            return None
        order = np.argsort(bundle["time"])
        got = {k: np.asarray(bundle[k], dtype=float)[order] for k in ("time", "close", "volume")}
    keep = (got["close"] > 0) & (got["time"] >= SINCE)
    got = {k: v[keep] for k, v in got.items()}
    if len(got["time"]) > LIMIT:
        got = {k: v[-LIMIT:] for k, v in got.items()}
    return got if len(got["time"]) > 8000 else None


def calendar_bars(fine, span_hours: float = 1.0):
    """Aggregate the **same** fine series into fixed calendar bars.

    **Not read from the coarse file, and that is the whole point.** The first
    run took the calendar arm from the `1h` file and the volume arm from the
    `3m` file, both capped at the same row count - so one covered thirteen
    years and the other about eight months, and the two clocks were measured
    on different data.

    The controls caught it: their volume is exactly constant, so their two
    clocks must agree, and `extent` came back 1.06 against 1.37. That gap was
    the span, not the clock.

    Building both arms from one fine series removes it by construction.
    """
    import numpy as np

    times, closes = fine["time"], fine["close"]
    width = span_hours * HOUR
    edges = np.floor(times / width)
    last = np.flatnonzero(np.diff(edges) != 0)
    if len(last) < 2000:
        return None
    return {"time": times[last], "close": closes[last]}


def volume_bars(fine, threshold: float):
    """Close a bar each time cumulative volume crosses `threshold`.

    The bar's timestamp is its **closing** time, which is the one a desk would
    have, and is what the time-of-day profile is read from. Carrying the excess
    volume forward rather than resetting keeps the long-run bar count right -
    truncating it would quietly make every bar slightly light.
    """
    import numpy as np

    times, closes, volumes = fine["time"], fine["close"], fine["volume"]
    out_t, out_c = [], []
    carried = 0.0
    for i in range(len(times)):
        carried += float(volumes[i])
        if carried >= threshold:
            out_t.append(float(times[i]))
            out_c.append(float(closes[i]))
            carried -= threshold
    if len(out_t) < 2000:
        return None
    return {"time": np.asarray(out_t), "close": np.asarray(out_c)}


def shape(series):
    """Scale-free readings of one clock's increments."""
    import numpy as np

    levels = np.log(series["close"])
    moves = np.diff(levels)
    if len(moves) < 2000:
        return None
    spread = float(np.std(moves))
    if spread <= 0:
        return None
    standard = moves / spread
    squared = standard * standard
    middle = float(np.mean(squared))
    den = float(np.sum((squared - middle) ** 2))
    clustering = (
        float(np.sum((squared[:-1] - middle) * (squared[1:] - middle))) / den if den > 0 else 0.0
    )
    return {
        "n": len(moves),
        "kurtosis": float(np.mean(standard**4)),
        # Lag-1 autocorrelation of squared standardised returns: the clustering
        # that a volume clock is supposed to absorb.
        "clustering": clustering,
    }


def clock_gain(series):
    """The clock's gain over a flat arm, per bar, inside one clock.

    Both arms get their own best base jerk from the same grid, because the
    clock multiplies that parameter and a multiplier whose mean is not one
    changes the average as well as the shape - which reversed this comparison
    once already.
    """
    import numpy as np

    times = series["time"].tolist()
    levels = np.log(series["close"]).tolist()
    half = len(levels) // 2
    profile = Profile.fit(times[:half], levels[:half], period=24.0)
    if profile is None:
        return None
    noise = (
        0.25
        * float(
            statistics.pstdev([levels[i] - levels[i - 1] for i in range(1, min(len(levels), 3000))])
        )
        ** 2
    )

    def best(clock):
        top = None
        for jerk in JERKS:
            member = Driven(
                build=lambda j=jerk: Gaussian(jerk=j, p00=1.0),
                lever="jerk",
                gain=0.0,
                clock=clock,
            )
            for i in range(half):
                member.predict(times[i])
                member.update(levels[i], noise)
            member.loglike = 0.0
            member._member.burn = 0
            counted = 0
            for i in range(half, len(levels)):
                before = member.loglike
                member.predict(times[i])
                member.update(levels[i], noise)
                if not math.isfinite(member.value) or not math.isfinite(member.sd):
                    return None
                if member.loglike != before:
                    counted += 1
            if not math.isfinite(member.loglike) or not counted:
                continue
            if top is None or member.loglike > top[0]:
                top = (member.loglike, counted, jerk)
        return top

    flat = best(None)
    driven = best(profile.factor)
    if flat is None or driven is None or flat[1] != driven[1]:
        return None
    return {
        "per_bar": (driven[0] - flat[0]) / driven[1],
        "total": driven[0] - flat[0],
        "bars": driven[1],
        "extent": profile.extent(),
    }


def main() -> None:
    print(
        f"fine {FINE}, coarse {COARSE}\n"
        "**Both clocks are built from the same fine series**, so they cover the\n"
        "same span bar for bar. Volume bars close when cumulative tick volume\n"
        "crosses the median volume of one coarse bar; calendar bars close on\n"
        "the hour. Reading the calendar arm from the coarse file instead gave\n"
        "the two arms different spans, which the controls caught.\n\n"
        "**extent is the headline**: peak over trough of the fitted time-of-day\n"
        "variance profile. One means no profile. FX at 1h calendar reads 2.7 to\n"
        "3.7, and if volume time absorbs the seasonality it should read near 1.\n"
    )

    print("=" * 112)
    print("ARM 1  the method check: the controls' two clocks must agree")
    print("=" * 112)
    print(
        f"{'instrument':<22}{'cal bars':>10}{'vol bars':>10}{'cal extent':>12}"
        f"{'vol extent':>12}{'cal kurt':>10}{'vol kurt':>10}"
    )
    rows: dict[str, list] = {}
    for group, names in (("generated", GENERATED), ("traded", TRADED)):
        if group == "traded":
            print("\n" + "=" * 112)
            print("ARM 2  the question: does volume time absorb the clock?")
            print("=" * 112)
            print(
                f"{'instrument':<22}{'cal bars':>10}{'vol bars':>10}{'cal extent':>12}"
                f"{'vol extent':>12}{'cal kurt':>10}{'vol kurt':>10}"
            )
        for name in names:
            fine = load(name, FINE)
            coarse = load(name, COARSE)
            if fine is None or coarse is None:
                continue
            import numpy as np

            calendar = calendar_bars(fine)
            if calendar is None:
                continue
            # **The threshold comes from this window, not from the coarse
            # file.** Taking the median of the `1h` file gave XAGUSD 2,511
            # calendar bars against 14,813 volume ones - a 5.9x mismatch,
            # because that file spans years in which the tick rate was
            # different. Total volume over the window divided by the number of
            # calendar bars in it makes the two counts agree by construction,
            # which is what the per-bar figures need.
            threshold = float(np.sum(fine["volume"])) / len(calendar["time"])
            if threshold <= 0:
                continue
            bars = volume_bars(fine, threshold)
            if bars is None:
                continue
            cal_shape, vol_shape = shape(calendar), shape(bars)
            cal_gain, vol_gain = clock_gain(calendar), clock_gain(bars)
            if not all((cal_shape, vol_shape, cal_gain, vol_gain)):
                continue
            rows.setdefault(group, []).append(
                {
                    "cal_extent": cal_gain["extent"],
                    "vol_extent": vol_gain["extent"],
                    "cal_per_bar": cal_gain["per_bar"],
                    "vol_per_bar": vol_gain["per_bar"],
                    "cal_kurt": cal_shape["kurtosis"],
                    "vol_kurt": vol_shape["kurtosis"],
                    "cal_clust": cal_shape["clustering"],
                    "vol_clust": vol_shape["clustering"],
                }
            )
            print(
                f"{name:<22}{cal_shape['n']:>10}{vol_shape['n']:>10}"
                f"{cal_gain['extent']:>12.2f}{vol_gain['extent']:>12.2f}"
                f"{cal_shape['kurtosis']:>10.1f}{vol_shape['kurtosis']:>10.1f}"
            )

    print("\n" + "=" * 112)
    print("ARM 3  the verdict")
    print("=" * 112)
    print(
        f"{'group':<12}{'cells':>7}{'extent cal':>12}{'extent vol':>12}"
        f"{'clock/bar cal':>15}{'clock/bar vol':>15}{'kurt cal':>10}{'kurt vol':>10}"
        f"{'clust cal':>11}{'clust vol':>11}"
    )
    for group in ("traded", "generated"):
        cells = rows.get(group, [])
        if not cells:
            continue

        def med(key):
            return statistics.median(c[key] for c in cells)

        print(
            f"{group:<12}{len(cells):>7}{med('cal_extent'):>12.2f}{med('vol_extent'):>12.2f}"
            f"{med('cal_per_bar'):>+15.4f}{med('vol_per_bar'):>+15.4f}"
            f"{med('cal_kurt'):>10.1f}{med('vol_kurt'):>10.1f}"
            f"{med('cal_clust'):>11.3f}{med('vol_clust'):>11.3f}"
        )
    print(
        "\nIf the generated rows differ between clocks, the resampling is wrong.\n"
        "If traded `extent vol` is near 1 and `clock/bar vol` near 0, the clock\n"
        "was a calendar artefact. If they are unchanged, the pattern is in time."
    )
    print("\nDONE")


if __name__ == "__main__":
    main()
