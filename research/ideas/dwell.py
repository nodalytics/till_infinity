"""Are regime durations memoryless, or patterned? - Benner's logic, made testable.

Asked on 2026-10-14: *on benner i think we can derive the formula and logic
behind it and use it.* That is the right objection to the previous answer, which
treated Benner as a single pinned frequency and concluded - correctly but
uselessly - that fifty-five years of data gives six repetitions of a nine-year
cycle and so no test.

## The derivation

Benner's 1875 structure is not a sinusoid. It is a **repeating sequence of
intervals**:

    pig iron lows   : 11, 9, 7, 11, 9, 7, ...   (summing to 27)
    pig iron peaks  : 8, 9, 10, 8, 9, 10, ...   (summing to 27)
    corn peaks      : 5, 6, 5, 6, ...           (summing to 11)

A deterministic renewal process whose inter-arrival times cycle through a fixed
list. The general object that contains it is already in this package's
vocabulary: a standard hidden Markov model has **geometric** dwell times -
memoryless, a constant hazard of leaving a state each step - while Benner's
durations are **patterned**, the extreme opposite. The model spanning both is a
hidden **semi**-Markov model, with an explicit duration distribution per state,
and Benner is the degenerate case where that distribution is a point mass
cycling through 11, 9 and 7.

## Why that is testable and the original claim was not

A nine-year cycle needs decades. **Duration dependence needs transitions**, and
intraday data has thousands of them. So the question becomes:

- Is the hazard of leaving a regime **flat** in how long the regime has lasted?
  Flat means memoryless, which means every fixed-interval cycle theory has no
  mechanism to stand on.
- Is the coefficient of variation of dwell times near **one**? A geometric
  distribution has CV about one. Patterned durations give CV well below one -
  that is the signature Benner's logic predicts. Clustered durations give CV
  above one.

Both are read against the same series **block-shuffled**, which preserves bar
geometry and the marginal distribution and destroys the ordering a regime would
live in - so a shuffled series should land on the geometric answer.

Regimes here are deliberately crude - volatility above or below its own rolling
median - because the claim is about **durations**, not about a clever state
definition. A sophisticated regime detector would put its own structure into
the dwell times, which is the mistake `null-pivot-ideas-against-a-walk-first`
records.
"""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
ROOT = HERE.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from level_signatures import CONTROL, GENERATED, SEED, TRADED, shuffle_blocks  # noqa: E402
from screen import load  # noqa: E402

#: Bars the volatility estimate and its median are taken over.
WINDOW = int(os.environ.get("WINDOW", "20"))
MEDIAN = int(os.environ.get("MEDIAN", "500"))
#: Durations the hazard is reported at.
STEPS = (1, 2, 3, 5, 8, 13, 21, 34)


def runs(bars, window: int = 0, median: int = 0) -> list[int]:
    """Lengths of consecutive stretches on one side of rolling median volatility."""
    closes = bars["close"]
    window = window or WINDOW
    median = median or MEDIAN
    if len(closes) < median + 4 * window:
        return []
    rets = np.diff(np.log(closes))
    if not np.isfinite(rets).all():
        return []
    # Rolling standard deviation, then its own rolling median as the split.
    cumulative = np.cumsum(rets**2)
    vol = np.sqrt((cumulative[window:] - cumulative[:-window]) / window)
    if len(vol) < median + 10:
        return []
    high = np.empty(len(vol) - median, dtype=bool)
    for i in range(len(high)):
        high[i] = vol[median + i] > np.median(vol[i : median + i])
    out: list[int] = []
    length = 1
    for i in range(1, len(high)):
        if high[i] == high[i - 1]:
            length += 1
        else:
            out.append(length)
            length = 1
    return out


def hazard(lengths: list[int], at: int) -> float:
    """`P(the run ends at exactly `at` | it reached `at`)`."""
    reached = sum(1 for n in lengths if n >= at)
    ended = sum(1 for n in lengths if n == at)
    return ended / reached if reached >= 20 else float("nan")


def describe(pool: list[list[int]], label: str) -> None:
    if not pool:
        print(f"    {label:<10} nothing")
        return
    flat = [n for lengths in pool for n in lengths]
    mean = float(np.mean(flat))
    cv = float(np.std(flat)) / mean if mean > 0 else float("nan")
    # Per feed, because a pooled dwell distribution mixes instruments with
    # different activity and this desk has been caught by pooling before.
    cvs = []
    for lengths in pool:
        if len(lengths) < 50:
            continue
        m = float(np.mean(lengths))
        if m > 0:
            cvs.append(float(np.std(lengths)) / m)
    cells = []
    for at in STEPS:
        got = hazard(flat, at)
        cells.append("-" if not math.isfinite(got) else f"{got:.3f}")
    print(
        f"    {label:<10}{len(flat):>8,}{mean:>8.1f}{cv:>7.3f}"
        f"{float(np.median(cvs)) if cvs else float('nan'):>8.3f}  "
        + " ".join(f"{c:>5}" for c in cells)
    )


#: Minutes a bar covers, per frame name - so a scale in bars can be read in
#: minutes, hours and days and compared across frames.
MINUTES = {"3m": 3, "15m": 15, "1h": 60, "4h": 240, "12h": 720, "1d": 1440}


def fits(lengths: list[int]) -> dict[str, tuple[float, float]]:
    """Fit four duration families by maximum likelihood, as `{name: (aic, scale)}`.

    **A CV puts no number on the regime, and the number is the question.** Over
    dispersion is consistent with "rare long regimes" but does not say how long.
    These four answer different questions:

    - **geometric**: constant hazard, scale `1/p`. If it wins, durations are
      memoryless and no cycle theory has a mechanism to stand on.
    - **lognormal**: a characteristic scale - the median - with a long right
      tail. If it wins there **is** a period and it is `exp(mu)`.
    - **Weibull**: shape below one is a stretched exponential, a decaying
      hazard whose scale still exists.
    - **Pareto**: scale-free. If it wins there is **no** period at any scale,
      which is a definite answer rather than an absence of one.
    """
    data = [float(n) for n in lengths if n >= 1]
    if len(data) < 200:
        return {}
    n = float(len(data))
    total = sum(data)
    logs = [math.log(x) for x in data]
    log_total = sum(logs)
    out: dict[str, tuple[float, float]] = {}

    p_hat = min(max(n / total, 1e-9), 1 - 1e-9)
    loglike = sum((x - 1.0) * math.log1p(-p_hat) + math.log(p_hat) for x in data)
    out["geometric"] = (2.0 - 2.0 * loglike, 1.0 / p_hat)

    mu = log_total / n
    sigma = math.sqrt(max(sum((x - mu) ** 2 for x in logs) / n, 1e-12))
    loglike = sum(
        -math.log(x * sigma * math.sqrt(2 * math.pi)) - (lx - mu) ** 2 / (2 * sigma * sigma)
        for x, lx in zip(data, logs, strict=True)
    )
    out["lognormal"] = (4.0 - 2.0 * loglike, math.exp(mu))

    shape = 1.0
    for _ in range(80):
        powered = [x**shape for x in data]
        s_p = sum(powered)
        s_pl = sum(pw * lx for pw, lx in zip(powered, logs, strict=True))
        s_pll = sum(pw * lx * lx for pw, lx in zip(powered, logs, strict=True))
        if s_p <= 0:
            break
        g = 1.0 / shape + log_total / n - s_pl / s_p
        dg = -1.0 / (shape * shape) - (s_pll * s_p - s_pl * s_pl) / (s_p * s_p)
        if abs(dg) < 1e-18:
            break
        step = g / dg
        shape = max(min(shape - step, 20.0), 0.05)
        if abs(step) < 1e-10:
            break
    scale = (sum(x**shape for x in data) / n) ** (1.0 / shape)
    loglike = sum(
        math.log(shape / scale) + (shape - 1) * math.log(x / scale) - (x / scale) ** shape
        for x in data
    )
    out["weibull"] = (4.0 - 2.0 * loglike, scale)
    out["_weibull_shape"] = (out["weibull"][0], shape)

    floor = min(data)
    denom = sum(math.log(x / floor) for x in data)
    alpha = n / denom if denom > 0 else float("inf")
    if math.isfinite(alpha) and alpha > 0:
        loglike = sum(math.log(alpha) + alpha * math.log(floor) - (alpha + 1) * lx for lx in logs)
        out["pareto"] = (2.0 - 2.0 * loglike, alpha)
    return out


def period(pool: list[list[int]], label: str, frame: str) -> None:
    """Which duration family wins, and the period it implies in real time."""
    flat = [n for lengths in pool for n in lengths]
    got = fits(flat)
    if not got:
        print(f"      {label:<9} {len(flat):>7,} runs - too few")
        return
    ranked = sorted(
        ((v[0], k, v[1]) for k, v in got.items() if not k.startswith("_")),
        key=lambda r: r[0],
    )
    best_aic, best_name, best_fitted = ranked[0]
    shape = got.get("_weibull_shape", (0.0, float("nan")))[1]
    deltas = " ".join(f"{k} {a - best_aic:+.0f}" for a, k, _ in ranked[1:])
    # **Pareto's parameter is a tail exponent, not a duration.** Converting it
    # to minutes would print a number with no meaning - and an alpha below one
    # is the opposite of a period: the mean itself does not converge, so there
    # is no characteristic length to report in any unit.
    if best_name == "pareto":
        verdict = (
            f"alpha {best_fitted:.3f} - scale-free, "
            + ("infinite mean" if best_fitted <= 1.0 else "heavy tailed")
            + ", no period in any unit"
        )
    else:
        minutes = best_fitted * MINUTES.get(frame, 60)
        verdict = (
            f"scale {best_fitted:>6.1f} bars = {minutes:>7.0f} min "
            f"= {minutes / 60.0:>6.1f} h = {minutes / 1440.0:>5.2f} d"
        )
    print(f"      {label:<9} {len(flat):>7,} runs  best {best_name:<10} {verdict}")
    print(f"      {'':<9} {'':>7}  weibull shape {shape:.3f}   AIC behind: {deltas}")


def arm(group: str, names: tuple[str, ...], rng) -> None:
    real: list[list[int]] = []
    mixed: list[list[int]] = []
    for name in names:
        bars = load(name)
        if bars is None:
            continue
        got = runs(bars)
        if len(got) >= 50:
            real.append(got)
        got = runs(shuffle_blocks(bars, rng))
        if len(got) >= 50:
            mixed.append(got)
    print(f"  {group}: {len(real)} feeds")
    print(
        f"    {'arm':<10}{'runs':>8}{'mean':>8}{'CV':>7}{'CV/feed':>8}  "
        + " ".join(f"{f'h({d})':>5}" for d in STEPS)
    )
    describe(real, "real")
    describe(mixed, "shuffled")
    print()


#: Real-time windows for the frame sweep, in minutes. The bar-count version
#: measures a **different object** at every frame - a 20-bar window is five
#: hours at 15m and twenty at 1h - so a period drifting across frames may be
#: this parameter drifting rather than the market.
WINDOW_MINUTES = int(os.environ.get("WINDOW_MINUTES", "1200"))
MEDIAN_MINUTES = int(os.environ.get("MEDIAN_MINUTES", "30000"))


def in_bars(minutes: int, frame: str) -> int:
    return max(int(round(minutes / MINUTES.get(frame, 60))), 3)


def stress(rng) -> None:
    """Each period claim against its own flaw."""
    print("=" * 96)
    print("STRESS TESTS on the period claims")
    print("=" * 96)
    print(
        f"\n  ONE  the same regime at every frame: {WINDOW_MINUTES} min of volatility"
        f" against {MEDIAN_MINUTES} min of median"
    )
    print("       if the period is real it is constant in minutes now, not in bars")
    for frame in ("15m", "1h", "4h"):
        window = in_bars(WINDOW_MINUTES, frame)
        median = in_bars(MEDIAN_MINUTES, frame)
        pool: list[list[int]] = []
        for name in TRADED:
            bars = load(name, frame)
            if bars is None:
                continue
            got = runs(bars, window, median)
            if len(got) >= 50:
                pool.append(got)
        if pool:
            print(f"    {frame} (window {window} bars, median {median} bars)")
            period(pool, "real", frame)

    print("\n  TWO  does Pareto survive dropping the short runs it feeds on?")
    print("       a continuous Pareto MLE on discrete lengths floored at one bar")
    print("       is driven by the mass at one and two bars")
    for frame in ("4h", "1d"):
        for least in (1, 3, 5, 10):
            pool = []
            for name in TRADED:
                bars = load(name, frame)
                if bars is None:
                    continue
                got = [n for n in runs(bars) if n >= least]
                if len(got) >= 50:
                    pool.append(got)
            if pool:
                period(pool, f"{frame} >={least}", frame)

    print("\n  THREE  real against shuffled at a matched run count")
    print("       the arms had 24,387 and 19,985 runs, so the winner could have")
    print("       changed from sample composition alone")
    for frame in ("4h", "1d"):
        real: list[list[int]] = []
        mixed: list[list[int]] = []
        for name in TRADED:
            bars = load(name, frame)
            if bars is None:
                continue
            a = runs(bars)
            b = runs(shuffle_blocks(bars, rng))
            if len(a) >= 50 and len(b) >= 50:
                keep = min(len(a), len(b))
                real.append([int(x) for x in rng.permutation(a)[:keep]])
                mixed.append([int(x) for x in rng.permutation(b)[:keep]])
        if real:
            print(f"    {frame}, matched to {sum(len(x) for x in real):,} runs each")
            period(real, "real", frame)
            period(mixed, "shuffled", frame)
    print()


def main() -> None:
    rng = np.random.default_rng(SEED)
    # **Across frames, because that is what decides whether a period exists.**
    # If the fitted scale is constant in *bars* at every frame, the process is
    # scale-free and the number is just the bar size. If it is constant in
    # *minutes*, there is a genuine characteristic timescale.
    print(
        "SCALE ACROSS FRAMES - constant in bars means scale-free, constant in minutes means a period\n"
    )
    for frame in ("15m", "1h", "4h", "1d"):
        real: list[list[int]] = []
        mixed: list[list[int]] = []
        for name in TRADED:
            bars = load(name, frame)
            if bars is None:
                continue
            got = runs(bars)
            if len(got) >= 50:
                real.append(got)
            got = runs(shuffle_blocks(bars, rng))
            if len(got) >= 50:
                mixed.append(got)
        print(f"    {frame}: {len(real)} feeds")
        period(real, "real", frame)
        period(mixed, "shuffled", frame)
    print()
    print(
        f"regimes = {WINDOW}-bar volatility against its own {MEDIAN}-bar median\n"
        "CV near 1 is memoryless (geometric). Patterned durations - Benner's\n"
        "logic - give CV well below 1. A flat hazard across h(1)..h(34) is\n"
        "memoryless; a rising one is duration dependence.\n"
    )
    for group, names in (("traded", TRADED), ("control", CONTROL), ("generated", GENERATED)):
        print("=" * 88)
        print(group)
        print("=" * 88)
        arm(group, names, rng)
    stress(rng)


if __name__ == "__main__":
    main()
