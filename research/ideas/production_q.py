"""Does activity drive the **production** filter's process noise, as it does ours?

`statespace-activity-on-q.md` measured activity on `Q` at **+2197 nats** median
against the clock's +675, on 8 of 8 traded instruments - and said the next step
was a shadow arm rather than a swap. Looking for somewhere to put one turned up
two facts worth recording.

**Nothing in production runs a `statespace` member.** The package is imported
only by `shared/codec.py`, and only so that `CODEC_UNPERSISTED` can be
discovered. There is no member in the live desk to shadow, which is by design -
the package is deliberately standalone and deletable.

**But production has its own Kalman, and its process noise is already a
per-call argument.** `levels.Kalman.predict(when, drift_per_hour)` adds
`drift_per_hour ** 2 * elapsed` to the variance, and exactly one call site
supplies it, at `levels.py:1244`:

    self.filter.predict(when, vol.price_units(self.price, DRIFT_VOL_PER_HOUR))

So the wiring would be a one-line multiply at a single call site, with no
change to the filter at all. **That is not a reason to do it**, because the
measurement that motivates it was taken on a different object: `level_wander`
on a log-price member tracking the price itself, not a filter tracking a
**level** that price visits and leaves.

Three things differ enough that the result cannot be assumed to carry:

* the production filter is `(price, slope)` - constant velocity, not a random
  walk - so its process noise enters through a different transition;
* its observations are **touches**, which arrive irregularly and only when
  price is near, rather than every bar;
* `DRIFT_VOL_PER_HOUR` is 0.02 volatility units per hour, orders of magnitude
  smaller than a price member's, and a multiplier on a nearly-frozen filter
  does something different from a multiplier on a lively one.

So this harness asks the question on the production filter directly, before
anything is wired. The arms and the guard are the same as the original study -
base refit on the undriven arm, every exponent normalised to average one, and
generated feeds whose fixed tick count makes the mechanism inert.

Runs on the lab. **Touches nothing in production.**
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

from till_infinity.structures.levels import Kalman  # noqa: E402
from till_infinity.structures.statespace.pacing import Pace  # noqa: E402

CACHE = Path(os.environ.get("SEQLAB_CACHE", str(Path.home() / "till_infinity/data/seqlab")))
FRAME = os.environ.get("FRAME", "1h")
LIMIT = int(os.environ.get("LIMIT", "20000"))
GRID = tuple(
    float(x)
    for x in os.environ.get("GRID", "1,4,16,64,256,1024,4096,16384").split(",")
)
EXPONENTS = tuple(float(x) for x in os.environ.get("EXPONENTS", "1,2,3").split(","))
#: The production constant, in volatility units per hour.
DRIFT_VOL_PER_HOUR = 0.02
TRADED = tuple(
    os.environ.get("TRADED", "EURUSD,GBPUSD,USDJPY,USDCAD,AUDUSD,XAUUSD,XAGUSD,US_Oil").split(",")
)
GENERATED = tuple(
    os.environ.get("GENERATED", "Boom_500_Index,Step_Index_200,Volatility_75_Index").split(",")
)


def load(name: str):
    import numpy as np

    path = CACHE / f"{name}.{FRAME}.npz"
    if not path.exists():
        return None
    with np.load(path) as bundle:
        if not {"time", "close", "volume"} <= set(bundle.keys()):
            return None
        order = np.argsort(bundle["time"])
        times, closes, volumes = (
            bundle["time"][order],
            bundle["close"][order],
            bundle["volume"][order],
        )
    keep = (closes > 0) & (volumes > 0)
    times, closes, volumes = times[keep], closes[keep], volumes[keep]
    if len(times) < 6000:
        return None
    if len(times) > LIMIT:
        times, closes, volumes = times[-LIMIT:], closes[-LIMIT:], volumes[-LIMIT:]
    return times.tolist(), np.log(closes).tolist(), volumes.tolist()


def score(times, values, volumes, *, drift: float, exponent: float | None):
    """Held-out loglike per observation on the production filter.

    `drift` is `drift_per_hour` in the series' own units, which is what the
    production call site passes after converting from volatility units.
    """
    steps = [abs(values[i] - values[i - 1]) for i in range(1, len(values))]
    noise = statistics.pstdev(steps) or 1e-9
    one = Kalman(mean=float(values[0]), variance=noise * noise, updated=float(times[0]))
    pace = Pace(exponent=exponent) if exponent is not None else None
    start = len(times) // 2
    total, counted, factors = 0.0, 0, []
    for i, (when, value, volume) in enumerate(zip(times, values, volumes, strict=True)):
        scale = 1.0
        if pace is not None:
            pace.update(volume)
            scale = pace.factor(volume)
            factors.append(scale)
        # The multiplier is on a **variance** and `drift_per_hour` is a spread,
        # so it enters as a square root - the same exponent trap `Profile`
        # documents, in the other direction.
        one.predict(float(when), drift * math.sqrt(scale))
        # **`update` returns the Kalman gain, not a log density.** Accumulating
        # what it returns and calling it a likelihood would have scored a
        # quantity that rises mechanically with the process noise - a larger
        # variance gives a larger gain - so the drift sweep would have picked
        # the top of the grid and the activity arm would have "won" for the
        # same reason. The density is formed here, from the predictive state
        # before the observation is folded in.
        var = float(one.variance) + noise * noise
        if i >= start and var > 0:
            residual = float(value) - float(one.mean)
            total += -0.5 * (residual * residual / var + math.log(2.0 * math.pi * var))
            counted += 1
        one.update(float(value), noise * noise, float(when))
    if not counted:
        return None
    return total / counted, (statistics.fmean(factors) if factors else 1.0)


def best_drift(times, values, volumes, natural: float):
    found = []
    for multiple in GRID:
        drift = natural * multiple
        if drift <= 0:
            continue
        got = score(times, values, volumes, drift=drift, exponent=None)
        if got and math.isfinite(got[0]):
            found.append((got[0], drift, multiple))
    if not found:
        return 0.0, float("nan")
    got, drift, multiple = max(found)
    if multiple in (GRID[0], GRID[-1]):
        print(f"    (drift pinned at grid edge {multiple}x)")
    return drift, got


def main() -> None:
    print(f"frame {FRAME}  exponents {EXPONENTS}  production DRIFT_VOL_PER_HOUR {DRIFT_VOL_PER_HOUR}\n")
    print(
        "`levels.Kalman` is the production filter and its process noise is\n"
        "already a per-call argument, so this needs no change to it. The\n"
        "multiplier enters as a **square root**, because `drift_per_hour` is a\n"
        "spread and the activity factor is a variance ratio.\n"
    )
    print(
        f"{'instrument':<20}{'flat/obs':>11}" + "".join(f"{f'pace {e:g}':>11}" for e in EXPONENTS)
        + f"{'mean factor':>13}"
    )
    rows = []
    for name in TRADED + GENERATED:
        got = load(name)
        if got is None:
            print(f"{name:<20}  no cached bars with volume")
            continue
        times, logs, volumes = got
        spread = statistics.pstdev([logs[i] - logs[i - 1] for i in range(1, len(logs))]) or 1e-9
        # Production converts volatility units to price units at the call site;
        # the series is in logs, so its own one-step spread is that unit.
        natural = spread * DRIFT_VOL_PER_HOUR
        drift, flat = best_drift(times, logs, volumes, natural)
        if drift <= 0:
            continue
        gains, factor = {}, 1.0
        for exponent in EXPONENTS:
            out = score(times, logs, volumes, drift=drift, exponent=exponent)
            if out:
                gains[exponent] = out[0] - flat
                factor = out[1]
        made = name in GENERATED
        print(
            f"{('*' + name if made else name):<20}{flat:>11.4f}"
            + "".join(f"{gains.get(e, float('nan')):>+11.4f}" for e in EXPONENTS)
            + f"{factor:>13.3f}"
        )
        rows.append({"name": name, "made": made, "gains": gains})

    if not rows:
        return
    print("\n" + "=" * 92)
    print("medians, per observation")
    print("=" * 92)
    print(f"{'group':<12}{'cells':>7}" + "".join(f"{f'pace {e:g}':>11}" for e in EXPONENTS))
    for group, made in (("traded", False), ("generated", True)):
        here = [r for r in rows if r["made"] == made]
        if not here:
            continue
        print(
            f"{group:<12}{len(here):>7}"
            + "".join(
                f"{statistics.median([r['gains'][e] for r in here if e in r['gains']]):>+11.4f}"
                for e in EXPONENTS
                if any(e in r["gains"] for r in here)
            )
        )
    traded = [r for r in rows if not r["made"]]
    if traded:
        best = max(
            EXPONENTS,
            key=lambda e: statistics.median([r["gains"][e] for r in traded if e in r["gains"]]),
        )
        wins = sum(1 for r in traded if r["gains"].get(best, 0) > 0)
        print(
            f"\nbest exponent {best:g}, positive on {wins} of {len(traded)} traded cells."
        )
        print(
            "**This is per observation, not a total**, so it is not comparable\n"
            "with the +2197 the price member earned over a whole series. What is\n"
            "comparable is the sign and the count: a mechanism worth wiring into\n"
            "a single production call site should help on nearly every\n"
            "instrument, and be inert on the generated feeds whose tick count\n"
            "their generator fixes."
        )


if __name__ == "__main__":
    main()
