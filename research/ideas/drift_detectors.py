"""River's drift detectors against this desk's, with the answer planted first.

`river.drift` offers ADWIN, Page-Hinkley and KSWIN. This package has two
detectors of its own - `changepoint.Changepoint`, a Bayesian online changepoint
detector whose `changepoint` property is the posterior mass on a run length of
zero, and `accruing.OneSided`, a CUSUM. None of them has ever been scored
against another.

## The comparison has to be calibrated or it is a threshold contest

Every detector here has a sensitivity dial - ADWIN's `delta`, Page-Hinkley's
`threshold`, KSWIN's `alpha`, the hazard rate, the CUSUM's threshold - and a
detector set looser will always find a change sooner. Comparing raw detection
delays at whatever defaults each library shipped measures the defaults.

So each detector is **calibrated to the same false-alarm rate on driftless
data** first, by sweeping its own dial until it fires about once per
`FALSE_ALARM_BARS`, and only then is its detection delay measured. That makes
the comparison one of power at equal size, which is the only version of it that
means anything.

## And the answer is planted, because that is the standard here

`show-power-before-reporting-a-null` is explicit: plant the effect, sweep its
strength, and report where the test goes blind. So the series is generated with
drift switches at **known** bars, and the sweep is over the drift magnitude in
sigma per bar. Detection delay is bars from the true switch to the first alarm;
a detector that never fires inside `PATIENCE` is blind at that strength.

The real `Drift_Switch_Index` is run too, but it is the weaker arm: Deriv does
not publish its switch times, so it can only be scored on how often each
detector fires, not on whether it fired at the right moment. That is why the
planted series is the measurement and the real feed is the sanity check.

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

CACHE = Path(os.environ.get("SEQLAB_CACHE", str(Path.home() / "till_infinity/data/seqlab")))
BARS = int(os.environ.get("BARS", "40000"))
#: Bars between planted switches.
EVERY = int(os.environ.get("EVERY", "400"))
#: Bars after a switch within which a detection counts.
PATIENCE = int(os.environ.get("PATIENCE", "200"))
#: Target false-alarm spacing on driftless data, in bars.
FALSE_ALARM_BARS = float(os.environ.get("FALSE_ALARM_BARS", "2000"))
#: Drift strengths swept, in sigma per bar.
STRENGTHS = tuple(float(x) for x in os.environ.get("STRENGTHS", "0.02,0.05,0.1,0.2,0.4").split(","))
SEED = 20261014
HOUR = 3600.0


def planted(strength: float, rng):
    """A unit-sigma series whose drift flips sign every `EVERY` bars.

    Returns `(values, switch bars)`. The drift is the only thing that changes,
    so a detector that fires is responding to a mean shift and not to a
    variance change - which matters, because a detector that only sees variance
    would otherwise look competent on a series where both move.
    """
    import numpy as np

    sign = 1.0
    out, switches = [], []
    for i in range(BARS):
        if i and i % EVERY == 0:
            sign = -sign
            switches.append(i)
        out.append(float(rng.normal(sign * strength, 1.0)))
    return np.asarray(out), switches


def river_detector(name: str, dial: float):
    """One detector, built alone.

    Built one at a time because the three take their dials on different
    scales: building all of them and selecting afterwards passed
    Page-Hinkley's threshold of 1.0 to `KSWIN(alpha=...)`, which refuses
    anything outside `(0, 1)` and raised during calibration.
    """
    from river import drift

    if name == "ADWIN":
        return drift.ADWIN(delta=dial)
    if name == "PageHinkley":
        return drift.PageHinkley(threshold=dial)
    return drift.KSWIN(alpha=dial, seed=SEED)


class Bocpd:
    """`changepoint.Changepoint`, alarming when its run-length mass at zero is high."""

    def __init__(self, dial: float) -> None:
        from till_infinity.statespace.changepoint import Changepoint

        self.inner = Changepoint()
        self.dial = dial
        self.when = 0.0
        self.drift_detected = False

    def update(self, value: float) -> None:
        self.when += HOUR
        self.inner.predict(self.when)
        self.inner.update(float(value), 1.0, self.when)
        self.drift_detected = float(self.inner.changepoint) > self.dial


class Cusum:
    """`accruing.OneSided`, which returns its own alarm from `update`."""

    def __init__(self, dial: float) -> None:
        from till_infinity.statespace.accruing import OneSided

        self.inner = OneSided(threshold=dial)
        self.drift_detected = False

    def update(self, value: float) -> None:
        self.drift_detected = bool(self.inner.update(float(value), 1.0))
        if self.drift_detected:
            self.inner.reset()


#: Each detector, with the dial values to sweep for calibration. Wide enough
#: that the target false-alarm rate is bracketed rather than clipped.
DIALS = {
    # Up to 0.9: at its conventional 0.002 and even at 0.1 ADWIN fires far
    # below the target rate on this data, so the bracket has to reach the
    # loose end or it is calibrated at a clip rather than at the target.
    "ADWIN": [0.9, 0.7, 0.5, 0.3, 0.1, 0.01, 1e-3, 1e-5, 1e-7],
    "PageHinkley": [1.0, 2.0, 5.0, 10.0, 20.0, 50.0, 100.0, 200.0],
    "KSWIN": [0.5, 0.2, 0.1, 0.01, 1e-3, 1e-4, 1e-5],
    "BOCPD": [0.02, 0.05, 0.1, 0.2, 0.4, 0.6, 0.8],
    "CUSUM": [2.0, 4.0, 6.0, 9.0, 12.0, 18.0, 25.0, 40.0],
}


def build(name: str, dial: float):
    if name in ("ADWIN", "PageHinkley", "KSWIN"):
        return river_detector(name, dial)
    return Bocpd(dial) if name == "BOCPD" else Cusum(dial)


def alarms(name: str, dial: float, values) -> list[int]:
    one = build(name, dial)
    out = []
    for i, v in enumerate(values):
        one.update(float(v))
        if getattr(one, "drift_detected", False):
            out.append(i)
    return out


def calibrate(name: str, quiet) -> tuple[float, float]:
    """The dial whose false-alarm spacing is closest to the target. `(dial, per 1k)`."""
    target = 1000.0 / FALSE_ALARM_BARS
    best, got = None, None
    for dial in DIALS[name]:
        fired = alarms(name, dial, quiet)
        rate = 1000.0 * len(fired) / len(quiet)
        if best is None or abs(rate - target) < abs(best - target):
            best, got = rate, dial
    return got, best


def delay(fired, switches) -> tuple[float, int]:
    """Median bars from a true switch to the next alarm, and how many were caught."""
    caught = []
    for at in switches:
        after = [f for f in fired if at <= f < at + PATIENCE]
        if after:
            caught.append(after[0] - at)
    if not caught:
        return float("nan"), 0
    return statistics.median(caught), len(caught)


def main() -> None:
    import numpy as np

    rng = np.random.default_rng(SEED)
    print(
        f"{BARS:,} bars, a switch every {EVERY}, detection counted inside "
        f"{PATIENCE} bars\ncalibrated to one false alarm per "
        f"{FALSE_ALARM_BARS:,.0f} bars on driftless data\n"
    )
    quiet = rng.normal(0.0, 1.0, size=BARS)
    print(f"{'detector':<14}{'dial':>10}{'false alarms / 1k':>19}")
    settings = {}
    for name in DIALS:
        dial, rate = calibrate(name, quiet)
        settings[name] = dial
        print(f"{name:<14}{dial:>10.2e}{rate:>19.3f}")
    print(
        "\n**Read the second column before the table below.** A detector whose\n"
        "false-alarm rate could not be brought near the target is not being\n"
        "compared at equal size, and its delays mean less than the others'.\n"
    )
    print("=" * 76)
    print("detection delay in bars, at the calibrated dial")
    print("=" * 76)
    header = f"{'detector':<14}"
    for s in STRENGTHS:
        header += f"{s:>12.2f}"
    print(header + "   (drift, sigma/bar)")
    for name in DIALS:
        row = f"{name:<14}"
        for strength in STRENGTHS:
            values, switches = planted(strength, np.random.default_rng(SEED + 1))
            fired = alarms(name, settings[name], values)
            med, caught = delay(fired, switches)
            share = caught / len(switches) if switches else 0.0
            row += f"{(f'{med:.0f}' if math.isfinite(med) else '-') + f'/{share:.0%}':>12}"
        print(row)
    print(
        "\nEach cell is the median delay and the share of switches caught. A dash\n"
        "is blind at that strength - nothing fired inside the window.\n"
    )

    print("=" * 76)
    print("the real feed, which can only be a sanity check")
    print("=" * 76)
    print(
        "Deriv does not publish `Drift_Switch`'s switch times, so there is no\n"
        "delay to measure. All this can say is how often each detector fires on\n"
        "a feed designed to switch drift against one specified not to.\n"
    )
    print(f"{'detector':<14}{'Drift_Switch_10':>18}{'Volatility_75':>16}{'ratio':>9}")
    series = {}
    for feed in ("Drift_Switch_Index_10", "Volatility_75_Index"):
        path = CACHE / f"{feed}.1h.npz"
        if not path.exists():
            continue
        with np.load(path) as bundle:
            closes = np.asarray(bundle["close"], dtype=float)
        closes = closes[closes > 0][-BARS:]
        steps = np.diff(np.log(closes))
        sd = steps.std() or 1e-12
        series[feed] = steps / sd
    if len(series) == 2:
        for name in DIALS:
            rates = []
            for feed in ("Drift_Switch_Index_10", "Volatility_75_Index"):
                fired = alarms(name, settings[name], series[feed])
                rates.append(1000.0 * len(fired) / len(series[feed]))
            ratio = rates[0] / rates[1] if rates[1] > 0 else float("inf")
            print(f"{name:<14}{rates[0]:>18.3f}{rates[1]:>16.3f}{ratio:>9.2f}")
        print(
            "\nA ratio above one means the detector fires more on the feed that\n"
            "switches drift than on the one that does not, which is the weakest\n"
            "form of the right answer."
        )


if __name__ == "__main__":
    main()
