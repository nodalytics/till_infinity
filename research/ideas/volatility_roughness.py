"""Is volatility rough here? Measure the Hurst exponent of realised variance.

Muhle-Karbe, Ouazzani Chahdi, Rosenbaum and Szymanski (2026) pin four empirical
facts to one statistic `H0`, the persistence of core order flow, and with
`H0 ~ 3/4` the predictions are: volume rough at `H0 - 1/2 = 1/4`, **volatility
rough at `2*H0 - 3/2 ~ 0`**, and market impact a power law with exponent
`2 - 2*H0 = 1/2` - the square-root law.

The volatility half is testable from bars alone and this is that test. It
matters to `statespace/` because **every member there is smooth**: `linear`
integrates a jerk, `reverting` is an Ornstein-Uhlenbeck, `selective` sums
exponential averages, `swarm` anchors a random walk, and all four pending
members are smooth too. A rough process has negatively correlated increments
and is nothing like any of them, so a confirmed `H ~ 0` says the family is the
wrong shape for the one quantity measured as forecastable.

## The estimator

The standard one, from the rough-volatility literature. For realised volatility
`sigma`, the `q`-th absolute moment of its log increments at lag `L` scales as

    m(q, L) = mean(|log sigma(t+L) - log sigma(t)|^q) ~ L^(q*H)

so `log m` against `log L` has slope `q*H`. Doing it for several `q` and
checking the slopes are linear in `q` is the self-similarity test; `H` is then
the common slope divided by `q`.

## And the criticism of it, built in

**A low `H` can be measurement noise rather than roughness.** Realised variance
is an estimate, and noise in it inflates the short-lag increments, which pushes
the estimated `H` toward zero - Cont and Das make this case against the rough
volatility literature directly. An artefact and a fact look identical at one
scale.

They separate across scales. If the low `H` is noise in `sigma`, then
estimating `sigma` **more precisely** - more bars per realised-variance window -
must raise it. If it is roughness, `H` stays put. So this sweeps the number of
bars per window and reports `H` for each, and **the shape of that sweep is the
answer** rather than any single number.

That doubles as the paper's own diagnostic: it warns that Hurst estimates for
order flow are "strongly scale dependent... close to 0.5 at high frequencies and
increase steadily as the sampling frequency decreases", which is the same
problem and the reason a single number here would be worthless.

**Both variance proxies are run**, because the range beat the close at every
short horizon in `statespace-volatility.md`: squared log returns, and Parkinson
from the high and low. A better `sigma` has less measurement noise, so if the
low `H` is an artefact, Parkinson should read higher.

## Time

Windows are in **hours**, per `statespace/__init__.py`. The lags are multiples
of the realised-variance window rather than bar counts, so the same lag means
the same horizon on every series.

Runs on the lab. Production has two cores and a 2.6GB container limit, and
research on it OOM-killed the live desk three times - see `research/starving.md`.
"""

from __future__ import annotations

import math
import os
import statistics
from pathlib import Path

from till_infinity.structures.statespace.inputs import bar_hours, coverage, parkinson

SYMBOLS = (
    ("eurusd", "EURUSD"),
    ("xauusd", "XAUUSD"),
    ("gbpusd", "GBPUSD"),
    ("usdjpy", "USDJPY"),
    ("v75", "Volatility_75_Index"),
    ("v25", "Volatility_25_Index"),
)
FRAMES = ("15m", "1h")

#: Hours of bars aggregated into one realised-variance observation. **The
#: sweep is the measurement**: if a low `H` is noise in the variance estimate
#: rather than roughness, estimating it over more bars must raise `H`.
WINDOWS = (1.0, 2.0, 4.0, 8.0, 24.0)

#: Lags at which the moments are taken, as multiples of the window. Five points
#: on a log-log line is thin; these are the usable range before the series runs
#: out at the long end.
LAGS = (1, 2, 3, 4, 6, 8, 12, 16, 24, 32)

#: Moment orders. Linearity of the slopes in `q` is the self-similarity test -
#: if they are not linear, a single `H` does not describe the series and the
#: number should not be quoted.
ORDERS = (0.5, 1.0, 1.5, 2.0)

LIMIT = int(os.environ.get("LIMIT", "40000"))


def load(stem: str, frame: str):
    import numpy as np

    path = Path(f"data/seqlab/{stem}.{frame}.npz")
    if not path.exists():
        return None
    with np.load(path) as bundle:
        if not {"time", "high", "low", "close"} <= set(bundle.keys()):
            return None
        order = np.argsort(bundle["time"])
        got = {k: bundle[k][order].tolist() for k in ("time", "high", "low", "close")}
    if len(got["close"]) > LIMIT:
        got = {k: v[-LIMIT:] for k, v in got.items()}
    return got


def slope(xs: list[float], ys: list[float]) -> float:
    """Least-squares slope of `ys` on `xs`."""
    n = len(xs)
    if n < 3:
        return float("nan")
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 0:
        return float("nan")
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / sxx


def hurst(log_sigma: list[float]) -> tuple[float, dict[float, float], float]:
    """`(H, slope per order, linearity error)` from log realised volatility.

    `H` is the mean of `slope(q)/q` over the orders. The linearity error is the
    largest deviation of `slope(q)/q` from that mean, which is the
    self-similarity check: a series that is not self-similar gives orders that
    disagree, and then no single `H` describes it.
    """
    per_order: dict[float, float] = {}
    for q in ORDERS:
        xs, ys = [], []
        for lag in LAGS:
            if lag >= len(log_sigma) // 4:
                continue
            moments = [
                abs(log_sigma[i + lag] - log_sigma[i]) ** q for i in range(len(log_sigma) - lag)
            ]
            mean = statistics.fmean(moments)
            if mean <= 0:
                continue
            xs.append(math.log(lag))
            ys.append(math.log(mean))
        if len(xs) >= 3:
            per_order[q] = slope(xs, ys)
    if not per_order:
        return float("nan"), {}, float("nan")
    estimates = [per_order[q] / q for q in per_order]
    got = statistics.fmean(estimates)
    return got, per_order, max(abs(e - got) for e in estimates)


def noise_floor(squares: list[float], span: int) -> tuple[float, float]:
    """Measure the estimator's own noise, `(floor, density exponent)`.

    **A bar count cannot give this and the first two attempts both tried.**
    `4/n` from `Var(log RV) ~ 2/n` is bar-counting, which this package forbids
    for the usual reason: the same four hours of the same market is three bars
    at 1h and sixteen at 15m, and that formula claims the 1h estimate is five
    times noisier than the 15m one *for the same four hours*. The noise is a
    property of the window in time and the data density inside it, so it has to
    be measured.

    The half-split is the other failure, and a more interesting one. Comparing
    the first half of a window to the second gives

        Var(d) = Var(log sigma_A - log sigma_B) + 2 Var(e)

    which is **the lag-1 moment itself** - adjacent non-overlapping windows are
    exactly what the lag-1 moment is taken over. Subtracting it leaves nothing
    by construction, which is why every cell came back `nan` with "noise 100%".
    A floor derived from consecutive windows cannot be below the shortest lag.

    So the handle has to hold the volatility fixed and vary only the data:
    **interleave**. Take every other bar in the window, then every other one
    starting at the offset. Both subsamples cover the *same span of the same
    time*, so the true volatility over them is the same number and the spread
    between their estimates is pure estimation error, with no contribution from
    the volatility's own movement.

    `k`-way interleaving at `k = 2` and `k = 4` gives the error at two data
    densities, so how the error scales with density is measured rather than
    assumed:

        Var(e_k) = c * k^p,  p = log2(Var(e_4) / Var(e_2))

    and the full-window error follows at `k = 1`. Sampling theory says `p = 1`;
    reporting it means a reader can see whether that held rather than trusting
    it. The floor on the increment of the error across two windows is twice
    that, since the two are independent.

    Returns `(nan, nan)` when the window holds too few bars to interleave four
    ways. That is the honest answer, and it is the point restated: a window is a
    duration, and whether its noise is *measurable* depends on how densely the
    feed samples that duration - a property of the feed, not of the window.
    """

    def spread(parts: int) -> float:
        """Mean within-window variance across `parts` interleaved estimates."""
        seen: list[float] = []
        for start in range(0, len(squares) - span + 1, span):
            block = squares[start : start + span]
            logs: list[float] = []
            for offset in range(parts):
                total = sum(block[offset::parts])
                if total <= 0:
                    break
                # The `parts` factor rescales to the whole window, and is a
                # constant shift in logs, so it cannot affect the variance.
                logs.append(0.5 * math.log(total * parts))
            if len(logs) == parts:
                seen.append(statistics.variance(logs))
        return statistics.fmean(seen) if len(seen) >= 30 else float("nan")

    if span < 8:
        return float("nan"), float("nan")
    two, four = spread(2), spread(4)
    if not (two > 0 and four > 0):
        return float("nan"), float("nan")
    density = math.log(four / two) / math.log(2.0)
    # Var(e) at the full window, then doubled for the increment across two.
    return 2.0 * two * 2.0**-density, density


def mixed_hurst(log_sigma: list[float], floor: float) -> tuple[float, float, float]:
    """`(H, noise share at the shortest lag, fit scatter)` above a given floor.

    The decomposition is the paper's: what is observed is the truth plus an
    estimation error, and because the error is independent across
    non-overlapping windows the second moment of the increments separates

        m(2, L) = Var(d log sigma) + Var(d e) = a * L^(2H) + b

    with `b` constant in the lag. Fitting `a`, `b` and `H` together does not
    identify them - measured, that returned the grid boundaries, 0.001 or 0.500
    with "noise 100%", which is worse than a wrong number because it looks like
    a right one. So `b` comes from `noise_floor`, measured independently by
    holding the window fixed and thinning the data, and what is left is a pure
    power law that is well determined.

    That also makes `b` a prediction rather than a knob: if the corrected
    moments go negative, the floor is larger than the signal and the answer is
    that this series has no measurable roughness at this window, not a fit.

    The criterion is **stability**. A scale-aware estimator gives the same `H`
    at every realised-variance window, because the roughness of volatility is
    not a function of how finely it was measured. The number is worth reading
    only once that holds.
    """
    xs: list[float] = []
    ys: list[float] = []
    first = float("nan")
    for lag in LAGS:
        if lag >= len(log_sigma) // 4:
            continue
        moments = [(log_sigma[i + lag] - log_sigma[i]) ** 2 for i in range(len(log_sigma) - lag)]
        if not moments:
            continue
        raw = statistics.fmean(moments)
        if math.isnan(first):
            first = raw
        corrected = raw - floor
        if corrected <= 0:
            continue
        xs.append(math.log(lag))
        ys.append(math.log(corrected))

    share = min(floor / first, 1.0) if not math.isnan(first) and first > 0 else float("nan")
    if len(xs) < 4:
        return float("nan"), share, float("nan")

    two_h = slope(xs, ys)
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    intercept = my - two_h * mx
    resid = [y - two_h * x - intercept for x, y in zip(xs, ys, strict=True)]
    return two_h / 2.0, share, math.sqrt(statistics.fmean([r * r for r in resid]))


def realised(values: list[float], span: int) -> list[float]:
    """Non-overlapping realised volatility: the root of summed variance proxies.

    **Non-overlapping on purpose.** Overlapping windows share observations, and
    `slope_fade.py` has already shown what that does to a statistic - an
    apparent `t` of -10.8 that was entirely the overlap.
    """
    out = []
    for start in range(0, len(values) - span + 1, span):
        total = sum(values[start : start + span])
        if total > 0:
            out.append(math.sqrt(total))
    return out


def legend() -> None:
    """How to read the table, printed under it."""
    print("Reading it:")
    print("  'H naive' fits a pure power law, which has no intercept to absorb")
    print("  estimation noise, so it bends toward zero at short lags - the")
    print("  Cont and Das objection, visible as H rising with the window.")
    print("  'H mixed' subtracts a **measured** noise floor and fits a power")
    print("  law to what is left. The floor comes from interleaving: two")
    print("  estimates of the SAME window built from alternate bars differ")
    print("  only by estimation error, because the volatility over them is the")
    print("  same number. Deriving the floor from a bar count (4/n) was")
    print("  bar-counting, and taking it from a half-split was circular - the")
    print("  half-split IS the lag-1 moment, so nothing could survive it.")
    print("  'noise' is the floor as a share of the shortest-lag moment: how")
    print("  much of what the naive estimator read was estimation error.")
    print("  'p' is how the error scales with data density, measured at 2-way")
    print("  and 4-way thinning. Sampling theory says 1; printing it means a")
    print("  reader can check rather than trust.")
    print()
    print("  **The criterion is stability, not the number.** A scale-aware")
    print("  estimator gives the same H at every window; if 'H mixed' still")
    print("  drifts, the decomposition is missing a component too.")


def main() -> None:
    print("Is volatility rough? The Hurst exponent of realised variance.")
    print("The theory predicts H ~ 0 (from H0 ~ 3/4 and H = 2*H0 - 3/2).")
    print("Brownian volatility would give H = 0.5; the rough literature finds ~0.1.\n")
    print("**The sweep is the measurement.** If a low H is measurement noise in")
    print("the variance estimate rather than roughness, estimating it over more")
    print("bars must raise H. If it is roughness, H stays put.\n")

    for label, stem in SYMBOLS:
        for frame in FRAMES:
            bars = load(stem, frame)
            if bars is None or len(bars["close"]) < 4000:
                continue
            close, high, low, times = (
                bars["close"],
                bars["high"],
                bars["low"],
                bars["time"],
            )
            bar = bar_hours(times)
            cover = coverage(times, bar)
            if bar <= 0:
                continue

            squares = [0.0] + [
                math.log(close[k] / close[k - 1]) ** 2 if close[k] > 0 and close[k - 1] > 0 else 0.0
                for k in range(1, len(close))
            ]
            park = parkinson(high, low)

            print(f"=== {label} {frame}: {len(close)} bars, bar={bar:g}h ===")
            print(
                f"  {'window':>8}{'bars':>6}{'n':>7}"
                f"{'H naive':>10}{'H mixed':>10}{'noise':>8}{'p':>6}"
                f"{'fit':>7}{'H mix park':>12}{'noise':>8}"
            )
            for hours in WINDOWS:
                span = max(round(hours * cover / bar), 1)
                if span < 2:
                    continue
                closes_log = [math.log(v) for v in realised(squares, span) if v > 0]
                park_log = [math.log(v) for v in realised(park, span) if v > 0]
                if len(closes_log) < 200 or len(park_log) < 200:
                    continue
                naive, _per, _lin = hurst(closes_log)
                floor, density = noise_floor(squares, span)
                floor_p, _dp = noise_floor(park, span)
                mixed, share, fit = mixed_hurst(closes_log, floor)
                mixed_p, share_p, _fit_p = mixed_hurst(park_log, floor_p)
                print(
                    f"  {hours:>6g}h{span:>6}{len(closes_log):>7}"
                    f"{naive:>10.3f}{mixed:>10.3f}{share:>8.1%}"
                    f"{density:>6.2f}{fit:>7.3f}{mixed_p:>12.3f}{share_p:>8.1%}"
                )
            print()

    legend()


if __name__ == "__main__":
    main()
