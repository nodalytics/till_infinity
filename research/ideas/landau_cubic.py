"""Does the trend sit in a double well? The renormalisation-group cubic, measured.

Schmidhuber's lattice-gas model gives the trend a Landau free energy whose
derivative is the drift on returns, and therefore the regression

    R(t+T) = a + b phi(t) + c phi(t)^3 + eps

**It is the only claim in the reading pile quoted with error bars** - daily
`b = 1.29% +/- 0.43%`, `c = -0.62% +/- 0.23%`; intraday (>= 1h)
`b = +0.132% +/- 0.046%`, `c = -0.039% +/- 0.014%` - so it can be replicated
rather than merely re-found, which is why it is worth the harness.

## What is predicted, written down before running

1. **Signs.** `b > 0` and `c < 0`: the origin repels, the cubic stabilises.
2. **A scale ladder.** The paper's own table says `c -> 0` below ~30 minutes
   and `c < 0` from ~1 hour out. That is a *dose-response* across scales, and
   this harness has 3m, 15m, 1h, 4h and 1d to test it on. A claim that only
   holds at one scale is a claim that was fitted at one scale.
3. **A bimodal trend.** `b > 0 > c` puts stable drifts at `+/- sqrt(b/-c)` and
   makes zero unstable, so the trend's own distribution should have a **trough
   at zero** - checkable with no filter and no likelihood at all. From the
   daily coefficients the modes sit at `+/- 1.44` standardised units.
4. **A tradeable size.** At `phi = 2` the daily fit predicts
   `1.29*2 - 0.62*8 = -2.38%` the next day. If that survives, it clears any
   spread; if it does not, the coefficients are not what they appear to be.

## The cubic is read off an orthogonalised basis, not fought for

`phi` and `phi^3` correlate about 0.77, so their coefficients are strongly
anti-correlated and each absorbs the other's noise. Regressing instead on
`phi` and `psi = phi^3 - gamma phi`, with `gamma` from the empirical
regression of `phi^3` on `phi`, is the same model reparametrised: the
coefficient on `psi` **is** `c`, with no collinearity left in it, and
`b = beta_phi - gamma c` recovers the published parametrisation.

That reparametrisation also reframes the published numbers. With
`gamma = 3` (the Gaussian value), daily `b = 1.29, c = -0.62` becomes
`beta_phi = b + 3c = -0.57`: in the orthogonal basis **the linear term is
negative**, and the whole of the reported "trending" comes from the cubic's
projection onto `phi`. Intraday it becomes `+0.015` against `c = -0.039` -
very nearly pure cubic.

## Nulls, and a planted case that is not simulated

* **Shuffled returns** keep each series' marginal exactly and destroy the
  order. Any `c` that survives there is a property of the distribution.
* **`Volatility_*_Index`** - Deriv synthetics with a known generator and no
  drift structure whatsoever. `b` and `c` must both be null.
* **`Drift_Switch_Index_10/20/30`** is the sharp one. It is a real market
  whose drift genuinely **switches between discrete values** - exactly the
  discrete alternative that a continuous double well is competing with. If a
  double well fits there it is finding real structure, and three members of
  the family give a dose-response rather than one fit.
* **`Crash_*` / `Boom_*`** carry an engineered asymmetry, so a member that
  reports a symmetric double well on them is reporting the wrong shape.

The filter arm is the test that matters: `Landau` against `Reverting` is the
same model with `kappa = 0`, held out, so it is a one-parameter nested
comparison rather than two collinear regressors arguing.

Runs on the lab.
"""

from __future__ import annotations

import math
import os
import random
from pathlib import Path

from till_infinity.structures.statespace.landau import Landau
from till_infinity.structures.statespace.reverting import Reverting

HOUR = 3600.0
SEED = 20261012

MAJORS = ("EURUSD", "USDJPY", "GBPUSD", "USDCHF", "USDCAD", "EURJPY", "GBPJPY", "NZDUSD")
METALS = ("XAUUSD", "XAGUSD")
CRYPTO = ("BTCUSD", "ETHUSD")
#: Known generator, no drift structure. Both coefficients must be null here.
FLAT = ("Volatility_75_Index", "Volatility_25_Index", "Volatility_100_Index", "Step_Index")
#: Known *discrete* drift switching - the alternative hypothesis as a market.
SWITCHED = ("Drift_Switch_Index_10", "Drift_Switch_Index_20", "Drift_Switch_Index_30")
#: Known engineered asymmetry. A symmetric well here is the wrong shape.
SKEWED = ("Crash_500_Index", "Boom_500_Index", "Jump_100_Index")

REAL = MAJORS + METALS + CRYPTO
GENERATED = FLAT + SWITCHED + SKEWED

FRAMES = tuple(os.environ.get("FRAMES", "3m,15m,1h,4h,1d").split(","))
BARS = {
    "3m": 0.05,
    "15m": 0.25,
    "1h": 1.0,
    "4h": 4.0,
    "6h": 6.0,
    "8h": 8.0,
    "12h": 12.0,
    "1d": 24.0,
}
#: Lookbacks for `phi`, in bars, which also set the forward horizon `T`. **The
#: paper pins neither**, and that matters more than it looks: `b = 1.29%` is
#: implausible as one day's return off a one-sigma trend and entirely plausible
#: as a quarter's, so the horizon is swept to 250 bars - a trading year at 1d -
#: and the whole surface reported rather than the best cell.
LOOKBACKS = tuple(int(k) for k in os.environ.get("LOOKBACKS", "1,5,20,60,250").split(","))
LIMIT = int(os.environ.get("LIMIT", "200000"))
#: 1973-03-01, when the Bretton Woods pegs were finally abandoned and the
#: majors began to float. **This is not a convenience cut.** The cache carries
#: EURUSD, USDJPY and USDCHF daily back to 1971, and in that era the price was
#: *administered*: 11.6% of USDJPY's 1970s daily returns are exactly zero. The
#: first run of this harness reported a trend density at zero 49 times its
#: density at one sigma for USDJPY, and standard errors of 0.000 - both of
#: which are the peg, not the market. A series that spans a change in how the
#: price is set is two series.
SINCE = float(os.environ.get("SINCE", "99792000"))
CACHE = Path.home() / "till_infinity" / "data" / "seqlab"


def load(name: str, frame: str):
    import numpy as np

    path = CACHE / f"{name}.{frame}.npz"
    if not path.exists():
        path = Path(f"data/seqlab/{name}.{frame}.npz")
        if not path.exists():
            return None
    with np.load(path) as bundle:
        if not {"time", "close"} <= set(bundle.keys()):
            return None
        order = np.argsort(bundle["time"])
        times = np.asarray(bundle["time"], dtype=float)[order]
        closes = np.asarray(bundle["close"], dtype=float)[order]
        spread = np.asarray(bundle["spread"], dtype=float)[order] if "spread" in bundle else None
    keep = (closes > 0) & (times >= SINCE)
    times, closes = times[keep], closes[keep]
    if spread is not None:
        spread = spread[keep]
    if len(times) > LIMIT:
        times, closes = times[-LIMIT:], closes[-LIMIT:]
        if spread is not None:
            spread = spread[-LIMIT:]
    return (times, closes, spread) if len(times) > 400 else None


# --------------------------------------------------------------------- the fit


def _ols(design, y, lag: int = 0):
    """Least squares with White or Newey-West standard errors.

    Written out rather than imported: the standard errors *are* the result
    here - the published claim is `+/- 0.43` - so the covariance has to be
    visible rather than taken on trust from a library call.

    `lag > 0` gives the Bartlett-weighted Newey-West meat, which is what
    overlapping windows require. With `lag = 0` it is White's estimator, which
    is correct for non-overlapping windows and is the headline.
    """
    import numpy as np

    xtx = design.T @ design
    try:
        inverse = np.linalg.inv(xtx)
    except np.linalg.LinAlgError:
        return None
    beta = inverse @ (design.T @ y)
    residual = y - design @ beta
    scored = design * residual[:, None]
    meat = scored.T @ scored
    for shift in range(1, lag + 1):
        weight = 1.0 - shift / (lag + 1.0)
        cross = scored[shift:].T @ scored[:-shift]
        meat = meat + weight * (cross + cross.T)
    cov = inverse @ meat @ inverse
    return beta, np.sqrt(np.maximum(np.diag(cov), 0.0)), len(y)


def regress(
    times, closes, bar_hours: float, lookback: int, shuffle: str = "", overlap: bool = False
):
    """The published regression, in percent per standardised unit of the trend.

    `phi` is the trailing return over `lookback` bars divided by a **strictly
    trailing** standard deviation, so nothing after `t` enters the regressor -
    which is the one way this measurement could manufacture its own answer.
    `R` is the next `lookback` bars' return in percent.

    Windows step by `lookback` unless `overlap`, so no two observations share a
    bar. The overlapping variant steps by one and pays for it with Newey-West
    standard errors at `lookback - 1` lags; both are reported, because the
    difference between them is how much of a published t-statistic was real.
    """
    import numpy as np

    moves = np.diff(np.log(closes))
    if shuffle == "flat":
        # Keeps the marginal exactly and destroys all ordering. A coefficient
        # that survives here is a property of the distribution.
        moves = np.asarray(random.Random(SEED).sample(list(moves), len(moves)))
    elif shuffle == "blocks":
        # **The null the claim actually needs.** A flat shuffle also destroys
        # volatility clustering, and a fat-tailed clustered series is not a
        # fair comparison against an i.i.d. one. Reordering 20-bar blocks
        # keeps the clustering and destroys the long-range trend structure,
        # which is the only thing the cubic can be reading.
        size = 20
        blocks = [moves[i : i + size] for i in range(0, len(moves), size)]
        random.Random(SEED).shuffle(blocks)
        moves = np.concatenate(blocks)
    n = len(moves)
    span = max(lookback, 1)
    history = 20 * span
    if n < history + 3 * span:
        return None

    step = 1 if overlap else span
    phi_list, forward = [], []
    start = history
    while start + 2 * span <= n:
        window = moves[start - history : start - span]
        scale = float(np.std(window))
        if scale > 0.0:
            phi_list.append(float(np.sum(moves[start - span : start])) / (scale * math.sqrt(span)))
            forward.append(100.0 * float(np.sum(moves[start : start + span])))
        start += step
    if len(phi_list) < 60:
        return None

    phi = np.asarray(phi_list)
    y = np.asarray(forward)
    spread = float(np.std(phi))
    if spread <= 0.0:
        return None
    # Standardise phi, so `b` and `c` are per standardised unit. That is what
    # "rescaled trend size" has to mean for the published coefficients to be
    # comparable across markets at all, and it is stated rather than assumed.
    phi = (phi - float(np.mean(phi))) / spread

    cube = phi**3
    gamma = float((phi @ cube) / (phi @ phi))
    psi = cube - gamma * phi

    design = np.column_stack([np.ones_like(phi), phi, psi])
    fitted = _ols(design, y, lag=(span - 1 if overlap else 0))
    if fitted is None:
        return None
    beta, se, count = fitted
    c, c_se = float(beta[2]), float(se[2])
    b = float(beta[1]) - gamma * c
    # beta1 and the psi coefficient are orthogonal by construction, so the
    # cross term in var(b) is zero to rounding and this is not an approximation.
    b_se = math.sqrt(se[1] ** 2 + (gamma * c_se) ** 2)
    well = math.sqrt(b / -c) if b > 0.0 > c else float("nan")
    return {
        "n": count,
        "b": b,
        "b_se": b_se,
        "c": c,
        "c_se": c_se,
        "gamma": gamma,
        "well": well,
        "sd_y": float(np.std(y)),
        "sd_cube": float(np.std(cube)),
        "kurtosis": float(np.mean(phi**4)),
        "trough": trough_at_zero(phi),
        # The whole fitted drift at two standardised units, which is the only
        # number a desk could act on and the one a cost gate applies to.
        "at_two": b * 2.0 + c * 8.0,
        "at_two_se": 2.0 * math.sqrt(se[1] ** 2 + ((8.0 - 2.0 * gamma) * c_se / 2.0) ** 2),
    }


def trough_at_zero(phi) -> float:
    """Is the trend's own density lower at zero than at `+/- 1`? No model.

    Prediction 3, read straight off the sample: a double well makes the origin
    unstable, so the trend should spend *less* time near zero than a unimodal
    distribution would. Reported as the ratio of the density at zero to the
    mean density at `+/- 1`, by histogram - **below one means a trough**, and
    a Gaussian gives about 1.65.
    """
    import numpy as np

    counts, edges = np.histogram(phi, bins=41, range=(-3.0, 3.0))
    width = edges[1] - edges[0]
    density = counts / (len(phi) * width)
    centres = 0.5 * (edges[:-1] + edges[1:])
    middle = float(density[np.argmin(np.abs(centres))])
    flank = 0.5 * (
        float(density[np.argmin(np.abs(centres - 1.0))])
        + float(density[np.argmin(np.abs(centres + 1.0))])
    )
    return middle / flank if flank > 0 else float("nan")


# ----------------------------------------------------------------- the members

THETAS = (-1.2, -0.6, -0.25, -0.1, 0.0, 0.1, 0.25, 0.5, 1.0, 2.0, 4.0)
KAPPAS = (0.0, 0.02, 0.1, 0.5, 2.0, 10.0, 50.0)
SIGMAS = (1e-4, 1e-3, 1e-2, 1e-1, 1.0, 10.0)


def score(member_kind, times, values, noise: float, theta: float, kappa: float, sigma2: float):
    """Held-out log-likelihood over the second half, fitted on the first.

    **Returns the count as well as the likelihood, and the caller checks it.**
    The first version of this did not, and `theta = -1.2, kappa = 0` - an
    explosive model whose covariance reaches infinity within a few hundred
    bars - came back with a likelihood of exactly `0.0` and therefore *won* on
    every instrument by three thousand nats. It had scored nothing.

    That is the identical defect `reverting.py`'s docstring records from its
    own first comparison: *a likelihood over fewer observations is not a
    smaller number, it is a different quantity*. Having the warning written
    down in the package did not stop me rewriting the bug, so the guard is now
    in the code rather than in the prose.
    """
    half = len(values) // 2
    if member_kind is Landau:
        member = Landau(theta=theta, kappa=kappa, sigma2=sigma2)
    else:
        member = Reverting(theta=theta, sigma2=sigma2)
    for i in range(half):
        member.update(values[i], noise, times[i])
        if not math.isfinite(member.value) or not math.isfinite(member.p00):
            return -math.inf, 0
    member.loglike = 0.0
    member.burn = 0
    counted = 0
    for i in range(half, len(values)):
        before = member.loglike
        member.update(values[i], noise, times[i])
        if not math.isfinite(member.value) or not math.isfinite(member.p00):
            return -math.inf, counted
        if member.loglike != before:
            counted += 1
    if not math.isfinite(member.loglike):
        return -math.inf, counted
    return member.loglike, counted


def best(member_kind, times, values, noise: float):
    """Grid fit over the first half, scored on the second.

    Cells that scored fewer observations than the best cell are **discarded
    rather than compared**, which is the guard `score` exists for.
    """
    kappas = KAPPAS if member_kind is Landau else (0.0,)
    wanted = len(values) - len(values) // 2
    top = None
    skipped = 0
    for theta in THETAS:
        for kappa in kappas:
            for sigma2 in SIGMAS:
                got, counted = score(member_kind, times, values, noise, theta, kappa, sigma2)
                if not math.isfinite(got):
                    continue
                if counted < wanted:
                    skipped += 1
                    continue
                if top is None or got > top[0]:
                    top = (got, theta, kappa, sigma2, counted)
    if top is None:
        return None
    got, theta, kappa, sigma2, counted = top
    member = (
        Landau(theta=theta, kappa=kappa, sigma2=sigma2)
        if member_kind is Landau
        else Reverting(theta=theta, sigma2=sigma2)
    )
    edges = []
    if theta in (THETAS[0], THETAS[-1]):
        edges.append("theta")
    if member_kind is Landau and kappa in (KAPPAS[0], KAPPAS[-1]):
        edges.append("kappa")
    if sigma2 in (SIGMAS[0], SIGMAS[-1]):
        edges.append("sigma2")
    return {
        "loglike": got,
        "scored": counted,
        "incomplete": skipped,
        "theta": theta,
        "kappa": kappa,
        "sigma2": sigma2,
        "wells": getattr(member, "wells", None),
        "edges": ",".join(edges) or "-",
    }


def planted(n: int = 4000):
    """Can the member find a double well that is really there?

    Simulates the member's own process with `theta = -0.6, kappa = 0.4` -
    wells at `+/- 1.22` - and refits. Without this arm a null on real data is
    unreadable, which is the lesson the direction chain's planted arm taught.
    """
    rng = random.Random(SEED)
    # sigma^2 = 0.1225, which the first grid could not reach - it stopped at
    # 0.1, so the planted arm recovered the well position and missed the
    # parameters. A planted arm that cannot be recovered is not a control.
    theta, kappa, sigma = -0.6, 0.4, 0.35
    dt = 1.0
    rate, value = 0.1, 0.0
    times, values = [], []
    from till_infinity.structures.statespace.landau import _flow, _travel

    for i in range(n):
        value += _travel(rate, dt, theta, kappa)
        rate = _flow(rate, dt, theta, kappa) + rng.gauss(0.0, sigma * math.sqrt(dt))
        times.append(i * HOUR * dt)
        values.append(value + rng.gauss(0.0, 0.05))
    return times, values, 0.05**2, (theta, kappa)


def equities(frame: str = "1d", wanted: int = 500):
    """Every equity in the cache, as `(name, times, closes)`.

    439 names at 1d, about 270 bars each. Too short for a per-name cubic -
    `phi` and `phi^3` need more than 270 points to separate - but exactly
    right for the thing the published estimate must have been: a broad market.
    """
    import numpy as np

    found = []
    for path in sorted(CACHE.glob(f"*.{frame}.npz")):
        name = path.name[: -len(f".{frame}.npz")]
        if "." not in name:  # the synthetics and FX have no venue suffix
            continue
        with np.load(path) as bundle:
            if not {"time", "close"} <= set(bundle.keys()):
                continue
            order = np.argsort(bundle["time"])
            times = np.asarray(bundle["time"], dtype=float)[order]
            closes = np.asarray(bundle["close"], dtype=float)[order]
        keep = closes > 0
        if keep.sum() < 150:
            continue
        found.append((name, times[keep], closes[keep]))
        if len(found) >= wanted:
            break
    return found


def aggregate(names):
    """An equal-weighted index of the cross-section, on the common dates.

    **This is the closest thing here to "aggregate net order flow".** The
    published `phi` is a market-level quantity, so a market-level series is
    what the regression wants; running it on one name at a time tests a
    different claim and would answer a question nobody asked.
    """
    import numpy as np

    by_date: dict[float, list[float]] = {}
    for _name, times, closes in names:
        moves = np.diff(np.log(closes))
        for when, move in zip(times[1:], moves, strict=True):
            by_date.setdefault(float(when), []).append(float(move))
    dates = sorted(d for d, rows in by_date.items() if len(rows) >= 20)
    if len(dates) < 150:
        return None
    level, times, closes = 0.0, [], []
    for when in dates:
        level += sum(by_date[when]) / len(by_date[when])
        times.append(when)
        closes.append(math.exp(level))
    import numpy as np

    return np.asarray(times), np.asarray(closes)


def macbeth(names, lookback: int):
    """Fama-MacBeth: one regression per name, then the spread across names.

    The alternative - pooling every name and date into one regression - gets
    the standard errors badly wrong, because equities share a market factor
    and the residuals are correlated across names on the same date. Averaging
    per-name coefficients and taking the standard error from their **spread**
    sidesteps that: the cross-sectional correlation shows up as a correlation
    between the estimates, which widens the spread rather than hiding in it.

    Reported with the count, because 270 daily bars per name is thin and many
    names will return nothing at long lookbacks.
    """
    import statistics

    bs, cs, troughs = [], [], []
    for _name, times, closes in names:
        got = regress(times, closes, 24.0, lookback)
        if got is None:
            continue
        bs.append(got["b"])
        cs.append(got["c"])
        troughs.append(got["trough"])
    if len(bs) < 20:
        return None
    return {
        "names": len(bs),
        "b": statistics.fmean(bs),
        "b_se": statistics.stdev(bs) / math.sqrt(len(bs)),
        "c": statistics.fmean(cs),
        "c_se": statistics.stdev(cs) / math.sqrt(len(cs)),
        "c_negative": sum(1 for v in cs if v < 0) / len(cs),
        "trough": statistics.median(troughs),
    }


def main() -> None:
    print(
        "LANDAU CUBIC: R(t+T) = a + b phi + c phi^3\n"
        "Target, as published: daily b=+1.29+/-0.43 c=-0.62+/-0.23;\n"
        "                   intraday b=+0.132+/-0.046 c=-0.039+/-0.014.\n"
        "b and c are percent per standardised unit of the trend. c is read off\n"
        "an orthogonalised cubic, so its standard error is not inflated by\n"
        "collinearity with phi. 'well' is sqrt(b/-c), the predicted mode;\n"
        "'trough' is the density at zero over the density at +/-1 - below 1.0\n"
        "means the trend really does avoid zero, and a Gaussian gives 1.65.\n"
        "'at 2' is the predicted next-window return after a 2-sigma trend.\n"
    )

    print("=" * 112)
    print("ARM 1  the regression, non-overlapping windows, every scale")
    print("=" * 112)
    header = (
        f"{'instrument':<24}{'frame':<6}{'back':>5}{'n':>7}"
        f"{'b':>9}{'+/-':>7}{'c':>9}{'+/-':>7}{'well':>7}{'trough':>8}{'at 2':>8}"
    )
    summary: dict[tuple[str, str], list] = {}
    for group, names in (("real", REAL), ("generated", GENERATED)):
        print(f"\n--- {group} ---")
        print(header)
        for name in names:
            for frame in FRAMES:
                found = load(name, frame)
                if found is None:
                    continue
                times, closes, _spread = found
                for back in LOOKBACKS:
                    got = regress(times, closes, BARS.get(frame, 1.0), back)
                    if got is None:
                        continue
                    summary.setdefault((group, frame), []).append(got)
                    print(
                        f"{name:<24}{frame:<6}{back:>5}{got['n']:>7}"
                        f"{got['b']:>+9.3f}{got['b_se']:>7.3f}"
                        f"{got['c']:>+9.3f}{got['c_se']:>7.3f}"
                        f"{got['well']:>7.2f}{got['trough']:>8.2f}{got['at_two']:>+8.2f}"
                    )

    print("\n" + "=" * 112)
    print("ARM 1b  medians by scale, and the shuffled control")
    print("=" * 112)
    print(
        f"{'group':<12}{'frame':<6}{'cells':>7}{'med b':>9}{'med c':>9}{'c<0 share':>11}{'med trough':>12}"
    )
    for (group, frame), rows in sorted(summary.items()):
        import statistics

        print(
            f"{group:<12}{frame:<6}{len(rows):>7}"
            f"{statistics.median(r['b'] for r in rows):>+9.3f}"
            f"{statistics.median(r['c'] for r in rows):>+9.3f}"
            f"{sum(1 for r in rows if r['c'] < 0) / len(rows):>11.2f}"
            f"{statistics.median(r['trough'] for r in rows):>12.2f}"
        )

    print("\nthe two nulls, on every instrument - not only the ones that were null")
    print("flat keeps the marginal and destroys all order; blocks keeps 20-bar")
    print("clustering and destroys the long-range trend. t is c over its own error.\n")
    print(
        f"{'instrument':<24}{'back':>5}{'real c':>10}{'t':>7}"
        f"{'flat c':>10}{'t':>7}{'blocks c':>10}{'t':>7}"
    )

    def ratio(got):
        return got["c"] / got["c_se"] if got["c_se"] > 0 else float("nan")

    for name in REAL + FLAT[:2]:
        found = load(name, "1d")
        if found is None:
            continue
        times, closes, _ = found
        for back in (5, 20, 60):
            live = regress(times, closes, 24.0, back)
            flat = regress(times, closes, 24.0, back, shuffle="flat")
            blocks = regress(times, closes, 24.0, back, shuffle="blocks")
            if live is None or flat is None or blocks is None:
                continue
            print(
                f"{name:<24}{back:>5}{live['c']:>+10.3f}{ratio(live):>+7.2f}"
                f"{flat['c']:>+10.3f}{ratio(flat):>+7.2f}"
                f"{blocks['c']:>+10.3f}{ratio(blocks):>+7.2f}"
            )

    print("\noverlapping windows against Newey-West: how much of a t-statistic is real")
    print(
        f"{'instrument':<24}{'back':>5}{'t(c) non-overlap':>18}{'t(c) overlap':>14}{'n ratio':>9}"
    )
    for name in REAL[:6]:
        found = load(name, "1d")
        if found is None:
            continue
        times, closes, _ = found
        for back in (20, 60):
            flat = regress(times, closes, 24.0, back)
            thick = regress(times, closes, 24.0, back, overlap=True)
            if flat is None or thick is None:
                continue
            t_flat = flat["c"] / flat["c_se"] if flat["c_se"] > 0 else float("nan")
            t_thick = thick["c"] / thick["c_se"] if thick["c_se"] > 0 else float("nan")
            print(
                f"{name:<24}{back:>5}{t_flat:>18.2f}{t_thick:>14.2f}{thick['n'] / flat['n']:>9.1f}"
            )

    print("\n" + "=" * 112)
    print("ARM 1c  the equity cross-section, which is what an aggregate claim needs")
    print("=" * 112)
    names = equities()
    print(f"{len(names)} names at 1d\n")
    index = aggregate(names)
    if index is not None:
        times, closes = index
        print("the equal-weighted index itself:")
        print(
            f"{'back':>5}{'n':>7}{'b':>9}{'+/-':>7}{'c':>9}{'+/-':>7}{'well':>7}"
            f"{'trough':>8}{'at 2':>8}{'+/-':>7}"
        )
        for back in (1, 5, 20, 60):
            got = regress(times, closes, 24.0, back)
            if got is None:
                continue
            print(
                f"{back:>5}{got['n']:>7}{got['b']:>+9.3f}{got['b_se']:>7.3f}"
                f"{got['c']:>+9.3f}{got['c_se']:>7.3f}{got['well']:>7.2f}"
                f"{got['trough']:>8.2f}{got['at_two']:>+8.2f}{got['at_two_se']:>7.2f}"
            )

    print("\nFama-MacBeth across names - the mean coefficient and the spread of it:")
    print(
        f"{'back':>5}{'names':>7}{'b':>9}{'+/-':>7}{'c':>9}{'+/-':>7}"
        f"{'c<0 share':>11}{'med trough':>12}"
    )
    for back in (1, 5, 20):
        got = macbeth(names, back)
        if got is None:
            continue
        print(
            f"{back:>5}{got['names']:>7}{got['b']:>+9.3f}{got['b_se']:>7.3f}"
            f"{got['c']:>+9.3f}{got['c_se']:>7.3f}{got['c_negative']:>11.2f}"
            f"{got['trough']:>12.2f}"
        )

    print("\n" + "=" * 112)
    print("ARM 2  the nested filter test: Landau (kappa free) against Reverting (kappa=0)")
    print("=" * 112)
    times, values, noise, truth = planted()
    land = best(Landau, times, values, noise)
    rev = best(Reverting, times, values, noise)
    print(
        f"planted theta={truth[0]} kappa={truth[1]} wells=+/-{math.sqrt(-truth[0] / truth[1]):.3f}"
    )
    if land and rev:
        print(
            f"  recovered theta={land['theta']} kappa={land['kappa']} "
            f"wells={land['wells']} edges={land['edges']}"
        )
        print(
            f"  Landau {land['loglike']:+.1f} vs Reverting {rev['loglike']:+.1f} "
            f"-> gain {land['loglike'] - rev['loglike']:+.1f}"
        )

    print(
        f"\n{'instrument':<24}{'frame':<6}{'n':>7}{'theta':>8}{'kappa':>8}"
        f"{'wells':>16}{'Landau':>11}{'Reverting':>11}{'gain':>9}{'edges':>14}"
    )
    for name in REAL + SWITCHED + FLAT[:2]:
        for frame in ("4h", "1d"):
            found = load(name, frame)
            if found is None:
                continue
            times, closes, _ = found
            import numpy as np

            series = np.asarray(closes, dtype=float)
            moves = np.diff(np.log(series))
            scale = float(np.std(moves))
            if scale <= 0:
                continue
            # The filter measures a *level* whose rate is the trend, in units
            # where one bar's move is one. Noise is a touch-sized fraction.
            level = np.cumsum(moves) / scale
            stamps = np.asarray(times[1:], dtype=float)
            if len(level) > 6000:
                level, stamps = level[-6000:], stamps[-6000:]
            noise = 0.25**2
            land = best(Landau, stamps.tolist(), level.tolist(), noise)
            rev = best(Reverting, stamps.tolist(), level.tolist(), noise)
            if not land or not rev:
                continue
            wells = f"{land['wells'][0]:+.2f}/{land['wells'][1]:+.2f}" if land["wells"] else "none"
            print(
                f"{name:<24}{frame:<6}{len(level):>7}{land['theta']:>8.2f}{land['kappa']:>8.2f}"
                f"{wells:>16}{land['loglike']:>11.1f}{rev['loglike']:>11.1f}"
                f"{land['loglike'] - rev['loglike']:>+9.1f}{land['edges']:>14}"
            )
    print("\nDONE")


if __name__ == "__main__":
    main()
