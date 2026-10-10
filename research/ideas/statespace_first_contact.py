"""The state-space package's first contact with real bars, and what it says.

Everything in `structures/statespace/` has so far only seen paths from
`paths.simulate`, which are drawn from the model's own assumption about the
world. Recovering a parameter from your own generator proves the estimator works
and nothing else. This is the first run against real prices.

## The question, and why it is the right first one

Not "does the filter track" - it will, a Kalman tracks anything. The question is
**whether the model is correctly specified for this data**, because every other
claim depends on it:

* if the standardised innovations are **autocorrelated**, the state equation is
  wrong and `jerk` is the thing that is wrong;
* if they are **fat-tailed but uncorrelated**, the measurement model is wrong,
  and `robust.py` is the cheap arm for exactly that;
* if they are **honest**, `robust.py` cannot earn anything on this series and
  that is worth knowing before anything else is built on it.

## The setup, and the one judgement in it

The latent state is a fair value and each bar's close is a **noisy measurement**
of it. That is a choice and it is the honest one available: a close is not the
fair value, it is where the last trade of the bar happened to land.

`R` is the one parameter on this desk that has been measured -
`TOUCH_NOISE_VOL = 0.40`, from two independent estimates on 2026-10-09 - and a
close is as good a reading of fair value as a touch is, so `R = 0.40^2`.
Everything is in volatility units of the series' own bar, which is what lets the
number mean the same thing on eurusd and on gold.

`jerk` is fitted here rather than assumed, which is the whole point of
`diagnostics.fit_jerk` existing.

## What it said, 2026-10-10, eurusd 4h, 1,073 bars from FOREXCOM

    fitted jerk  1.831e-03 vol units^2 / hour^5   (log-likelihood -2975.2)

                 n     sd    skew  kurt    LB p       JB p
    linear    1070  1.444   +0.03  6.12  2.25e-47  8.78e-95
    robust    1070  1.358   +0.16  4.67  3.93e-45  1.52e-28

**The model is wrong on this series in all three ways at once**: autocorrelated,
non-normal, and over-confident by 44%. None of those is marginal - the
Ljung-Box p-value is 2e-47.

**The tails are real, and `robust.py` is the first thing here with evidence
either way.** Its gate fired on **7.55%** of measurements against the ~1.2% a
true Gaussian would produce, the worst innovation was 6.1 sigma, and it took
kurtosis from 6.12 to 4.67 and over-confidence from 44% to 36%. So the
measurement model *is* non-Gaussian and the cheap arm for it earns something
measurable. It does not earn much: the autocorrelation barely moves
(2.25e-47 to 3.93e-45), which says the **state equation is the dominant error**
and the tails are the smaller one. That is the right order to attack them in and
the opposite of where a reading of the kurtosis alone would send you.

The smoother works on real data: mean standard deviation 0.2916 against the
filter's 0.3908, tighter at 1,072 of 1,073 points.

## What this cannot conclude

**A fitted `jerk` of 1.8e-03 implies 27.0 volatility units of drift a day, where
`DRIFT_VOL_PER_HOUR = 0.02` implies 0.48.** A factor of 56. That is *not*
evidence that the production constant is 56 times too small, and reading it that
way would be the same error as #136 - a number validated without checking what
it is a number about.

A bar close is not a touch. The close moves because price moved; a level is not
supposed to. Fitting a latent value to closes therefore attributes all of price's
motion to the state, which is why the fitted jerk is enormous and why the
innovations are autocorrelated - the thing being tracked is not slowly drifting,
it is the market. The run says the **machinery** is sound, and says nothing about
what `jerk` is for a level.

Levels are observed when price returns to them, which is a sparser and
differently-biased sample, and the raw touch price is not in the outcomes
journal. Until that field exists this harness cannot be pointed at the right
measurement.



"""

from __future__ import annotations

import csv
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from till_infinity.structures.statespace import (
    Gaussian,
    Robust,
    fit_jerk,
    residuals,
    smooth,
)

#: Measurement variance, in volatility units squared. `TOUCH_NOISE_VOL = 0.40`.
NOISE = 0.40**2


def load(path: Path, venue: str = "FOREXCOM") -> tuple[list[float], list[float], float]:
    """One venue's closes, as `(times, volatility units, bps per bar)`.

    Volatility units rather than price, because that is the scale everything in
    `structures` is expressed in and the only one that travels between
    instruments. The unit itself is the EWMA of the absolute close-to-close move
    that `vol/volatility.py` publishes - recomputed here rather than imported so
    this harness needs no engine.
    """
    rows: list[tuple[int, float]] = []
    with path.open() as fh:
        for row in csv.DictReader(fh):
            if row["venue"] != venue or not row["close"]:
                continue
            rows.append((int(row["ts"]), float(row["close"])))
    rows.sort()
    closes = [c for _t, c in rows]

    # The shipped unit: EWMA of |return| in bps, 60-bar half-life, floored.
    alpha = 1.0 - 0.5 ** (1.0 / 60.0)
    mean_abs = 0.0
    for i in range(1, len(closes)):
        move = abs(closes[i] - closes[i - 1]) / closes[i - 1] * 10_000
        mean_abs = move if i == 1 else mean_abs + alpha * (move - mean_abs)
    bps = max(mean_abs, 0.25)

    base = closes[0]
    units = [(c / base - 1.0) * 10_000 / bps for c in closes]
    return [float(t) for t, _c in rows], units, bps


def report(label: str, got) -> None:
    if got is None:
        print(f"  {label:<10} too few residuals to read")
        return
    print(
        f"  {label:<10} n={got.n:<5} sd={got.sd:6.3f}  skew={got.skew:+6.2f}  "
        f"kurt={got.kurtosis:6.2f}  LB p={got.ljung_box_p:8.2e}  JB p={got.jarque_bera_p:8.2e}"
    )
    verdict = []
    if got.autocorrelated:
        verdict.append("AUTOCORRELATED (state equation wrong)")
    if got.non_normal:
        verdict.append("NON-NORMAL (measurement model wrong)")
    if got.sd > 1.1:
        verdict.append(f"OVER-CONFIDENT by {(got.sd - 1) * 100:.0f}%")
    elif got.sd < 0.9:
        verdict.append(f"UNDER-CONFIDENT by {(1 - got.sd) * 100:.0f}%")
    print(f"  {'':<10} {' | '.join(verdict) or 'honest on all three'}")


def main() -> None:
    path = Path(sys.argv[1])
    times, units, bps = load(path)
    print(f"{len(units)} bars, volatility unit {bps:.2f} bps per 4h bar")
    print(f"range {min(units):.1f} to {max(units):.1f} volatility units from the first close")
    print(f"measurement noise R = {NOISE:.4f} (TOUCH_NOISE_VOL = 0.40, measured)\n")

    # --- what jerk does this series actually want?
    def run(jerk: float) -> float:
        g = Gaussian(jerk=jerk)
        for t, z in zip(times, units, strict=True):
            g.update(z, noise=NOISE, when=t)
        return g.loglike

    jerk, best = fit_jerk(run)
    print(f"fitted jerk = {jerk:.3e} vol units^2 / hour^5   (log-likelihood {best:.1f})")
    edge = "AT THE BRACKET EDGE - the answer is outside the range searched"
    if jerk < 1e-11 or jerk > 1e1:
        print(f"  !! {edge}")

    # The production counterpart, for scale. `DRIFT_VOL_PER_HOUR` is a standard
    # deviation per hour on the *value*, so its jerk-equivalent is not directly
    # comparable - what is comparable is how far each says a level drifts in a day.
    drift_day_fitted = math.sqrt(jerk * (24.0**5) / 20.0)
    print(f"  a day of that is {drift_day_fitted:.3f} volatility units of drift")
    print(f"  DRIFT_VOL_PER_HOUR = 0.02 says {0.02 * 24:.3f} over the same day\n")

    # --- is the model right?
    print("standardised innovations:")
    for label, make in (("linear", Gaussian), ("robust", Robust)):
        f = make(jerk=jerk)
        z = []
        for t, m in zip(times, units, strict=True):
            f.update(m, noise=NOISE, when=t)
            if f.seen > f.burn:
                z.append(f.last_standardised)
        report(label, residuals(z))
        if isinstance(f, Robust):
            print(
                f"  {'':<10} gate fired on {f.gated_share:.2%} of measurements "
                f"(about 1.2% under a true Gaussian), worst {f.worst_sigma:.1f} sigma"
            )

    # --- and what does using the whole series buy?
    got = smooth(times, units, jerk=jerk, noise=NOISE)
    if got is not None:
        tighter = sum(1 for s, fl in zip(got.sd, got.filtered_sd, strict=True) if s < fl - 1e-12)
        print(
            f"\nsmoother: mean sd {sum(got.sd) / len(got):.4f} against the filter's "
            f"{sum(got.filtered_sd) / len(got):.4f}, tighter at {tighter}/{len(got)} points"
        )


if __name__ == "__main__":
    main()
