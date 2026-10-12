"""Scoring the forecast distribution, not the forecast - and why the walk wins.

Asked whether the members can **simulate** what comes next well enough to be
useful: draw an ensemble of continuations, see which one the market took,
recalibrate on the answer.

Three things have to be said before any of that is measurable.

## There is no bug in `paths.simulate`, and that is the finding

The standing note on this work called `simulate`'s increments broken: lag-1
autocorrelation of **+0.999** where every real series reads 0.00. They are not
broken. `simulate` draws from a **triple integrator driven by white jerk**,
which is `linear.Gaussian`'s own model, and the increments of a thrice-
integrated process *must* be nearly perfectly autocorrelated - a step is
dominated by `rate * dt`, and the rate barely moves between steps.

So the +0.999 is the model's assumption showing through a faithful generator,
and `paths.py`'s own docstring already says it is "not a market simulator".

**And it derives the wall everything else on this desk keeps hitting**, more
sharply than expected. Measured, the generator reads `+0.999` for *every*
positive jerk down to `1e-10`, and `-0.488` at exactly zero - the latter being
differenced white noise, whose lag-1 is `-0.5` by construction. Real series sit
at `0.00`, **between the two and reachable by neither.**

The reason is the `t^5`: a triple integrator's value variance grows as
`jerk * t^5 / 20`, so over a long series the smooth latent motion dominates the
measurement noise however small the jerk is made. **A random walk is not in
`linear.Gaussian`'s family at any parameter setting.** That is stronger than
the fitted jerk landing on its grid floor - the floor is the fit reaching
toward the `-0.5` corner, which is still wrong, only less wrong than `+1`.

## "Which path did it take" is the wrong question

The maximum over `N` draws grows without limit in `N`, so "the highest path"
is a statement about the sample size. And the realised path is one draw from a
distribution - asking which ensemble member it matched scores the ensemble on
a coin flip.

**The answerable question is whether the forecast distribution is
calibrated**: does the realised value land uniformly across the predicted
quantiles? That is the probability integral transform, and it is what decides
whether a band can be trusted for a stop.

## The ensemble is analytic here, so there is no Monte Carlo error

Every member in this package carries a **Gaussian** predictive marginal -
`predict` advances the mean and the covariance together - so the quantiles can
be read exactly instead of sampled. Drawing paths would add estimation noise
for nothing. The continuous ranked probability score has a closed form for a
Gaussian,

    CRPS(N(mu, sigma), y) = sigma * [ z (2 Phi(z) - 1) + 2 phi(z) - 1/sqrt(pi) ]

with `z = (y - mu)/sigma`, so the whole comparison is exact.

Paths would be needed for a path-dependent functional - a first-passage
probability - and `statespace-triple-barrier.md` already shows the barrier
*label* is invariant to volatility and the closed form exists, so that is not
where the open question is.

## The nulls

The walk - a random walk with the series' own volatility - is the baseline,
because it is already the best-calibrated band on this desk. The Deriv
constant-volatility feeds go first because a walk **is** their generator, so a
member that cannot match the walk there cannot match it anywhere.

Runs on the lab.
"""

from __future__ import annotations

import copy
import math
import os
import statistics
from pathlib import Path

from till_infinity.structures.statespace.landau import Landau
from till_infinity.structures.statespace.linear import Gaussian
from till_infinity.structures.statespace.paths import hourly, simulate
from till_infinity.structures.statespace.reverting import Reverting

HOUR = 3600.0
SEED = 20261012

TRADED = ("EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "XAGUSD", "BTCUSD")
#: A walk **is** their generator, so the walk arm must win here by construction.
GENERATED = ("Volatility_75_Index", "Volatility_25_Index", "Step_Index")
FRAME = os.environ.get("FRAME", "1h")
HORIZONS = tuple(int(h) for h in os.environ.get("HORIZONS", "1,5,20,60").split(","))
JERKS = tuple(10.0**k for k in range(-9, 2))
THETAS = (0.1, 0.5, 2.0)
BINS = 10
SINCE = float(os.environ.get("SINCE", "99792000"))
LIMIT = int(os.environ.get("LIMIT", "20000"))
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


# --------------------------------------------------------------------- arm one


def increment_memory(jerk: float, noise: float, n: int = 4000) -> float:
    """Lag-1 autocorrelation of `simulate`'s **measured** increments.

    The quantity the standing note called a bug. It is a function of the
    jerk-to-noise ratio and nothing else: all jerk gives a smooth thrice-
    integrated path whose steps repeat, all noise gives independent steps.
    """
    path = simulate(hourly(n), jerk=jerk, noise=noise, seed=SEED)
    moves = [path.measured[i] - path.measured[i - 1] for i in range(1, len(path.measured))]
    middle = statistics.fmean(moves)
    den = sum((m - middle) ** 2 for m in moves)
    if den <= 0:
        return float("nan")
    return sum((moves[i] - middle) * (moves[i + 1] - middle) for i in range(len(moves) - 1)) / den


def real_memory(levels) -> float:
    moves = [levels[i] - levels[i - 1] for i in range(1, len(levels))]
    middle = statistics.fmean(moves)
    den = sum((m - middle) ** 2 for m in moves)
    if den <= 0:
        return float("nan")
    return sum((moves[i] - middle) * (moves[i + 1] - middle) for i in range(len(moves) - 1)) / den


# ------------------------------------------------------- the predictive scores


def _normal_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _normal_pdf(z: float) -> float:
    return math.exp(-0.5 * z * z) / math.sqrt(2.0 * math.pi)


def crps(middle: float, spread: float, seen: float) -> float:
    """Continuous ranked probability score of `N(middle, spread)` at `seen`.

    Closed form, so the ensemble needs no sampling and carries no Monte Carlo
    error. Lower is better, and it is in the units of the observation - which
    makes it comparable across members on one series and **not** across series.
    """
    if spread <= 0:
        return float("nan")
    z = (seen - middle) / spread
    return spread * (
        z * (2.0 * _normal_cdf(z) - 1.0) + 2.0 * _normal_pdf(z) - 1.0 / math.sqrt(math.pi)
    )


def build(kind: str, jerk: float, theta: float):
    if kind == "kalman":
        return Gaussian(jerk=jerk, p00=1.0)
    if kind == "reverting":
        return Reverting(sigma2=jerk, theta=theta)
    if kind == "landau":
        return Landau(sigma2=jerk, theta=theta, kappa=0.5)
    raise ValueError(kind)


def walk_forecast(levels, at: int, horizon: int, span: int = 240):
    """The baseline: a random walk at the series' own trailing volatility.

    No state, no parameters beyond a volatility window - which is why it is the
    thing to beat rather than a straw man. `sd` grows as `sqrt(horizon)`.
    """
    if at < span:
        return None
    window = [levels[i] - levels[i - 1] for i in range(at - span + 1, at + 1)]
    spread = statistics.pstdev(window)
    if spread <= 0:
        return None
    return levels[at], spread * math.sqrt(horizon)


def assess(times, levels, member, horizons=HORIZONS, train_share: float = 0.5):
    """Walk the member forward and score its predictive marginal at each horizon.

    The member is advanced on the **whole** series one reading at a time, and
    at each step after the training half a *copy* is pushed forward to each
    horizon to read its mean and spread. Copying is what keeps the forecast
    from contaminating the filter: predicting ahead on the live member would
    advance its own clock and the next update would be applied at the wrong
    time.
    """
    noise = (
        0.25
        * statistics.pstdev([levels[i] - levels[i - 1] for i in range(1, min(len(levels), 3000))])
        ** 2
    )
    start = int(len(levels) * train_share)
    scores: dict[int, list[float]] = {h: [] for h in horizons}
    ranks: dict[int, list[float]] = {h: [] for h in horizons}
    for i, (when, level) in enumerate(zip(times, levels, strict=True)):
        member.update(level, noise, when)
        if i < start or i + max(horizons) >= len(levels):
            continue
        for h in horizons:
            ahead = copy.deepcopy(member)
            ahead.predict(times[i + h])
            spread = ahead.sd
            if not (math.isfinite(spread) and spread > 0 and math.isfinite(ahead.value)):
                continue
            seen = levels[i + h]
            scores[h].append(crps(ahead.value, spread, seen))
            # The probability integral transform: where the realised value fell
            # in the predicted distribution. Uniform is calibrated.
            ranks[h].append(_normal_cdf((seen - ahead.value) / spread))
    return scores, ranks


def assess_walk(times, levels, horizons=HORIZONS, train_share: float = 0.5):
    start = int(len(levels) * train_share)
    scores: dict[int, list[float]] = {h: [] for h in horizons}
    ranks: dict[int, list[float]] = {h: [] for h in horizons}
    for i in range(start, len(levels) - max(horizons)):
        for h in horizons:
            got = walk_forecast(levels, i, h)
            if got is None:
                continue
            middle, spread = got
            seen = levels[i + h]
            scores[h].append(crps(middle, spread, seen))
            ranks[h].append(_normal_cdf((seen - middle) / spread))
    return scores, ranks


def flatness(values, bins: int = BINS) -> float:
    """Chi-square of the PIT histogram against uniform, per degree of freedom.

    **1.0 is calibrated.** Reported per degree of freedom so it does not grow
    with the sample, and so a member on ten thousand points is comparable with
    one on two thousand.
    """
    if len(values) < 200:
        return float("nan")
    counts = [0] * bins
    for v in values:
        counts[min(int(v * bins), bins - 1)] += 1
    want = len(values) / bins
    return sum((c - want) ** 2 / want for c in counts) / (bins - 1)


def coverage(values, share: float) -> float:
    """Share of realised values inside the central `share` interval."""
    if not values:
        return float("nan")
    low, high = (1.0 - share) / 2.0, 1.0 - (1.0 - share) / 2.0
    return sum(1 for v in values if low <= v <= high) / len(values)


def main() -> None:
    print(
        f"frame {FRAME}, horizons {HORIZONS}\n"
        "The predictive marginal is Gaussian for every member here, so CRPS and\n"
        "the probability integral transform are read in closed form - no\n"
        "sampling and no Monte Carlo error. PIT flatness is a chi-square per\n"
        "degree of freedom against uniform: **1.0 is calibrated.** Coverage is\n"
        "the share of realised values inside the stated interval.\n"
    )

    print("=" * 108)
    print("ARM 1  `simulate` is not broken: the +0.999 is the model, and it derives the wall")
    print("=" * 108)
    print(
        "Lag-1 autocorrelation of the generator's own measured increments, by\n"
        "jerk against a fixed measurement noise of 1e-4. A triple integrator's\n"
        "steps repeat because the rate barely moves; independent steps need the\n"
        "noise to dominate.\n"
    )
    print(f"{'jerk':>10}{'noise':>10}{'lag-1 of increments':>22}")
    for jerk in (1e-2, 1e-4, 1e-6, 1e-8, 1e-10, 0.0):
        print(f"{jerk:>10.0e}{1e-4:>10.0e}{increment_memory(jerk, 1e-4):>22.4f}")
    print(f"\n{'instrument':<22}{'real lag-1 of increments':>26}")
    for name in GENERATED + TRADED:
        found = load(name)
        if found is None:
            continue
        print(f"{name:<22}{real_memory(found[1]):>26.4f}")
    print(
        "\n**There is no jerk at which this looks like a market.** It reads\n"
        "+0.999 for every positive jerk down to 1e-10 and -0.488 at exactly\n"
        "zero - the latter being differenced white noise, whose lag-1 is -0.5\n"
        "by construction. Real series sit at 0.00, between the two and\n"
        "reachable by neither.\n\n"
        "The reason is the t^5: a triple integrator's value variance grows as\n"
        "`jerk * t^5 / 20`, so over a long series the smooth latent motion\n"
        "dominates the measurement noise however small the jerk is made. A\n"
        "random walk is **not in this model's family at any parameter**, which\n"
        "is a stronger statement than the fitted jerk merely landing on its\n"
        "floor - the floor is the fit reaching for the -0.5 corner, which is\n"
        "still wrong, only less wrong than +1."
    )

    print("\n" + "=" * 108)
    print("ARM 2  is any member's forecast distribution calibrated? Against the walk.")
    print("=" * 108)
    rows: dict[str, list] = {}
    for group, names in (("generated", GENERATED), ("traded", TRADED)):
        print(f"\n--- {group} ---")
        print(
            f"{'instrument':<22}{'arm':<12}{'h':>4}{'n':>7}"
            f"{'PIT flat':>10}{'cover 50':>10}{'cover 90':>10}{'CRPS':>12}{'vs walk':>10}"
        )
        for name in names:
            found = load(name)
            if found is None:
                continue
            times, levels = found
            walk_scores, walk_ranks = assess_walk(times, levels)
            arms = {"walk": (walk_scores, walk_ranks)}
            for kind in ("kalman", "reverting"):
                best = None
                for jerk in JERKS:
                    for theta in THETAS if kind != "kalman" else (0.5,):
                        member = build(kind, jerk, theta)
                        scores, ranks = assess(times, levels, member)
                        total = [s for s in scores[HORIZONS[0]] if math.isfinite(s)]
                        if len(total) < 200:
                            continue
                        mean = statistics.fmean(total)
                        if best is None or mean < best[0]:
                            best = (mean, scores, ranks)
                if best is not None:
                    arms[kind] = (best[1], best[2])
            for arm, (scores, ranks) in arms.items():
                for h in HORIZONS:
                    good = [s for s in scores[h] if math.isfinite(s)]
                    pit = [r for r in ranks[h] if math.isfinite(r)]
                    if len(good) < 200:
                        continue
                    mine = statistics.fmean(good)
                    base = [s for s in arms["walk"][0][h] if math.isfinite(s)]
                    against = mine / statistics.fmean(base) if base else float("nan")
                    rows.setdefault(f"{group}:{arm}:{h}", []).append(
                        {
                            "flat": flatness(pit),
                            "c50": coverage(pit, 0.5),
                            "c90": coverage(pit, 0.9),
                            "ratio": against,
                        }
                    )
                    print(
                        f"{name:<22}{arm:<12}{h:>4}{len(good):>7}"
                        f"{flatness(pit):>10.1f}{coverage(pit, 0.5):>10.3f}"
                        f"{coverage(pit, 0.9):>10.3f}{mine:>12.6f}{against:>10.3f}"
                    )

    print("\n" + "=" * 108)
    print("ARM 3  the verdict: medians by arm and horizon")
    print("=" * 108)
    print(
        f"{'group:arm:horizon':<30}{'cells':>7}{'PIT flat':>10}"
        f"{'cover 50':>10}{'cover 90':>10}{'CRPS vs walk':>14}"
    )
    for key in sorted(rows):
        cells = rows[key]
        flats = [c["flat"] for c in cells if math.isfinite(c["flat"])]
        print(
            f"{key:<30}{len(cells):>7}"
            + (f"{statistics.median(flats):>10.1f}" if flats else f"{'-':>10}")
            + f"{statistics.median(c['c50'] for c in cells):>10.3f}"
            f"{statistics.median(c['c90'] for c in cells):>10.3f}"
            f"{statistics.median(c['ratio'] for c in cells):>14.3f}"
        )
    print(
        "\nPIT flatness 1.0 is calibrated; coverage should read 0.500 and 0.900.\n"
        "CRPS vs walk below 1.0 beats the walk. The generated feeds are the\n"
        "calibration: a walk **is** their generator, so nothing can beat it there."
    )
    print("\nDONE")


if __name__ == "__main__":
    main()
