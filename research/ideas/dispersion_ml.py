"""Can anything predict dispersion better than HAR-Parkinson, and can ML?

Asked on 2026-10-17: "point the other guys at dispersion", then "also test if
ml can predict dispersion". The architecture rule set in the same breath is
that every member and component forecasts **dispersion** and only the Monte
Carlo emits a price, so this is the measurement that rule stands on: if nothing
here beats a three-term linear regression at forecasting variance, the
reframing buys nothing and should be said so.

## Why dispersion and not price

The README's item 6 is the argument and it is strong. Price is a
near-martingale: it diffuses at 1.00 to 1.07 times `sqrt(h)`, direction is a
coin in every test on this desk, and a random walk wins the point forecast at
every horizon on 17 to 21 of 39 series. Log-variance is not: it is persistent,
it is forecastable, and HAR's win says it has structure at **several time
scales at once** - which is a description of the quantity a multi-component
state space is built for.

## The null is named, cheap, and already works

**HAR-Parkinson**, a linear regression of next log-variance on the last bar's,
the last five's mean and the last twenty-two's mean. `one-bar-band.md`'s
companion result puts it at 79% of achievable. A state space on log-variance
has a high bar and a working incumbent to beat, which is the right shape for
this package: a named null that is not a straw man.

So the arms are ordered by how much they assume, and the question for each one
is only whether it beats the regression:

* `constant` - the unconditional mean. The floor, and what R2 is measured
  against.
* `last` - the previous bar's log-variance. A random walk in log-variance, and
  the arm that says whether anything beyond persistence is needed.
* `ou` - AR(1) in log-variance, a discretised Ornstein-Uhlenbeck. **It is here
  because the family has no member that does this.** README item 6 argues that
  "`reverting`'s mean reversion" should work on log-variance because volatility
  mean-reverts, but `reverting` reverts the **rate** to zero and leaves the
  value integrated - so it models a random walk in log-variance, not a
  reversion to a level. `ou` is the two-parameter reference that claim should
  have been measured against, and because it is a one-timescale HAR, `har`
  beating it is the multi-scale claim and nothing else.
* `har` - **the null.** Three realised variances, one OLS fit.
* `s4d` - `diagonal.Diagonal`, the multi-timescale basis promoted the same day.
  Its reason to work here is exactly HAR's: several decay rates in one state.
* `pool` - the production pool through `Desk.read`, reading log-variance as its
  subject. This is "point the other guys at dispersion" as a number.
* `lin48` - ridge on the last 48 raw lags. **The control that says what any
  ESN win means**, because a reservoir brings three things at once -
  nonlinearity, capacity, and a memory much longer than HAR's 22 bars - and
  only this arm separates the last two from the first.
* `esn` - an echo state network. Fixed random reservoir, one ridge readout, and
  its **effective degrees of freedom computed rather than hoped**, which is the
  only honest way to run a nonlinear model on a few thousand rows.

## Two controls, and both are already measured elsewhere

**`shuffled`** destroys the target's time order, so every arm must read about
zero. An arm that scores on a shuffled target is reading its own construction.

**A constant-sigma synthetic** is the stronger control, and it is a
*replication*: `reservoirs.md` ran an ESN across the Deriv Volatility grid,
where the generator fixes sigma and there is nothing to learn, and measured
`logvol` R2 of **-0.0107 to +0.0015** against **+0.0558 to +0.1140** on real
markets. If this harness does not reproduce that split it is not measuring what
that one measured.

Everything is fitted on the first half of each series and scored only on the
second, per instrument - the shape `sigma_holdout.py` used, because an in-sample
R2 on a nonlinear model is a statement about its capacity.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
for q in (HERE, HERE.parent, HERE.parents[1]):
    sys.path.insert(0, str(q))

from pattern_fingerprint import CACHE, classify, load  # noqa: E402

from till_infinity.structures.statespace.diagonal import Diagonal  # noqa: E402
from till_infinity.structures.statespace.facade import Desk  # noqa: E402

FRAMES = ("1h", "4h")
#: Real classes, then the generated one that fixes its own sigma - the control
#: `reservoirs.md` ran. `classify` names the Deriv volatility family.
TRADED = ("fx_major", "fx_cross", "metal")
CONTROLS = ("volatility",)
PER_CLASS = 8
LIMIT = 12000
#: HAR's three windows, in bars. The names are daily in the literature; here
#: they are whatever the frame is, which is the point of a multi-scale basis.
LAGS = (1, 5, 22)
#: Forecast horizons, in bars. **One bar is the hardest and the least useful.**
#: A single bar's range-based variance is a noisy estimate of that bar's true
#: variance, so an R2 against it is capped by the estimator's own noise - which
#: is why HAR's literature figure is 79% of *achievable* rather than 79% of
#: total. Averaging the target over a horizon beats that noise down, and a
#: horizon is also what a caller actually needs: the Monte Carlo prices a path
#: 40 bars out, not one bar out.
HORIZONS = (1, 5, 20)
#: Reservoir size. Small on purpose: the readout is `SIZE + len(LAGS) + 1` wide
#: against thousands of rows, so the effective dof stays far below the sample
#: and the fit is a statement about the data rather than the capacity.
SIZE = 48
SPECTRAL = 0.9
LEAK = 0.3
RIDGES = (1e-6, 1e-4, 1e-2, 1.0, 100.0)
SEED = 20261017


def onescale(n: int, rng) -> dict[str, np.ndarray]:
    """One timescale in log-variance, read through the same noisy estimator.

    **The baseline for `har / ou`.** HAR's five- and twenty-two-bar averages do
    two things at once: they carry multi-scale persistence *and* they average
    down the **estimator noise** in the target, because a single bar's
    range-based variance is a noisy reading of that bar's true variance. This
    series has exactly one AR(1) timescale and no multi-scale structure at all,
    so whatever ratio HAR wins by here is what the noise-averaging alone buys -
    and only a ratio clearly above it on real bars is evidence of several
    timescales. A smoke test on this generator put HAR about threefold above
    AR(1) with nothing multi-scale present, which is why the ratio cannot be
    read without this row.
    """
    phi, level, kick = 0.95, -18.0, 0.2
    logvar = np.empty(n)
    logvar[0] = level
    for i in range(1, n):
        logvar[i] = level + phi * (logvar[i - 1] - level) + rng.normal(0.0, kick)
    sigma = np.exp(0.5 * logvar)
    close = 100.0 * np.exp(np.cumsum(rng.normal(0.0, 1.0, n) * sigma))
    return {
        "time": np.arange(n, dtype=float) * 3600.0,
        "open": close,
        "high": close * np.exp(np.abs(rng.normal(0.0, 1.0, n)) * sigma),
        "low": close * np.exp(-np.abs(rng.normal(0.0, 1.0, n)) * sigma),
        "close": close,
    }


def parkinson(high: np.ndarray, low: np.ndarray) -> np.ndarray:
    """Log of the bar's range-based variance, the subject's measurement.

    `(ln(H/L))**2 / (4 ln 2)` is Parkinson's estimator - unbiased for the
    variance of a driftless diffusion observed continuously - and the log is
    taken because a variance is positive and a state should not be.
    """
    span = np.log(np.maximum(high, 1e-300) / np.maximum(low, 1e-300))
    var = span * span / (4.0 * math.log(2.0))
    return np.log(np.maximum(var, 1e-300))


def _design(logvar: np.ndarray, horizon: int) -> tuple[np.ndarray, np.ndarray, int]:
    """HAR's three backward averages, and the forward average over `horizon`.

    The target is the **mean** log-variance over the next `horizon` bars, so it
    is a statement about dispersion over a span rather than about one bar's
    noisy estimate. Nothing in a row at `i` uses a bar past `i`.
    """
    start = max(LAGS)
    rows, target = [], []
    for i in range(start, len(logvar) - horizon):
        rows.append([float(np.mean(logvar[i - lag + 1 : i + 1])) for lag in LAGS])
        target.append(float(np.mean(logvar[i + 1 : i + 1 + horizon])))
    return np.asarray(rows, dtype=float), np.asarray(target, dtype=float), start


def _ridge(x: np.ndarray, y: np.ndarray, lam: float) -> tuple[np.ndarray, float]:
    """Ridge coefficients with an intercept, and the fit's effective dof.

    `dof = sum_j e_j / (e_j + lam)` over the eigenvalues of `X'X` on the
    centred design - the quantity `reservoirs.md` insists on printing, because
    a nonlinear model whose effective dof approaches its sample size has not
    learnt anything, it has memorised.
    """
    mean = x.mean(axis=0)
    centred = x - mean
    gram = centred.T @ centred
    width = gram.shape[0]
    coef = np.linalg.solve(gram + lam * np.eye(width), centred.T @ (y - y.mean()))
    eigen = np.linalg.eigvalsh(gram)
    dof = float(np.sum(eigen / (eigen + lam))) + 1.0
    intercept = float(y.mean() - mean @ coef)
    return np.concatenate([[intercept], coef]), dof


def _apply(coef: np.ndarray, x: np.ndarray) -> np.ndarray:
    return coef[0] + x @ coef[1:]


def _reservoir(series: np.ndarray, rng: np.random.Generator, known: int) -> np.ndarray:
    """Drive a fixed random reservoir with the series; return its states.

    The nonlinearity is entirely in here and entirely untrained - that is what
    buys LSTM-class expressiveness without a gradient, and it is why the only
    fitted object is the linear readout above.

    **`known` is the leak this function had and no longer has.** The drive is
    standardised so the reservoir sees a comparable input on every instrument,
    and the first version computed that mean and standard deviation over the
    **whole** series - including the half the arm is scored on. Since R2 here
    is measured against the *training* half's mean, an arm that knows the test
    half's average volatility level is handed most of the answer wherever the
    level drifts between halves, which on volatility it does. The statistics
    now come from `series[:known]` only, and nothing past it is touched.
    """
    win = rng.normal(0.0, 1.0, size=SIZE)
    w = rng.normal(0.0, 1.0, size=(SIZE, SIZE))
    radius = float(np.max(np.abs(np.linalg.eigvals(w))))
    w *= SPECTRAL / max(radius, 1e-12)
    seen = series[: max(known, 2)]
    drive = (series - seen.mean()) / max(seen.std(), 1e-12)
    state = np.zeros(SIZE)
    out = np.empty((len(series), SIZE))
    for i, u in enumerate(drive):
        state = (1.0 - LEAK) * state + LEAK * np.tanh(w @ state + win * u)
        out[i] = state
    return out


def _r2(truth: np.ndarray, guess: np.ndarray, base: float) -> float:
    """R2 against the unconditional mean of the **training** half.

    Against the training mean and not the test mean, because using the test
    half's own mean would hand every arm information it does not have.
    """
    err = float(np.sum((truth - guess) ** 2))
    floor = float(np.sum((truth - base) ** 2))
    return 1.0 - err / floor if floor > 0 else float("nan")


def _statespace(
    logvar: np.ndarray, start: int, rows: int, feed: str, frame: str, member
) -> np.ndarray:
    """One-step predictive means from a member reading log-variance.

    `Desk.read` and the members take a scalar, so pointing them at dispersion
    is a matter of what the number **means** rather than of new machinery -
    which is the whole content of `subjects.py`. The prediction scored is the
    state *before* the bar is folded in, so it is predictive and not fitted.
    """
    out = []
    noise = 0.30  # the dispersion subject's `noise`, a placeholder that says so
    desk = _DESKS.get((feed, frame))
    for i in range(start, start + rows):
        # The guess for bar i+1 is the state **before** bar i+1 is folded in,
        # which is what makes this predictive rather than fitted.
        if member is None:
            got = desk.read(feed, frame, float(i) * 3600.0, float(logvar[i]), noise)
            out.append(float(got.value))
        else:
            out.append(float(member.value) if member.seen else float(logvar[i]))
            member.update(float(logvar[i]), noise, float(i) * 3600.0)
    return np.asarray(out, dtype=float)


_DESKS: dict[tuple[str, str], Desk] = {}


def score(
    bars: dict[str, np.ndarray],
    frame: str,
    feed: str,
    rng,
    horizon: int = 1,
    shuffle: bool = False,
) -> dict:
    """Every arm on one series, fitted on the first half and scored on the second."""
    logvar = parkinson(bars["high"], bars["low"])
    good = np.isfinite(logvar)
    if good.sum() < 2000:
        return {}
    logvar = logvar[good]
    if shuffle:
        order = rng.permutation(len(logvar))
        logvar = logvar[order]

    x, y, start = _design(logvar, horizon)
    if len(y) < 1000:
        return {}
    cut = len(y) // 2
    base = float(y[:cut].mean())

    out: dict[str, tuple[float, float]] = {}
    out["constant"] = (_r2(y[cut:], np.full(len(y) - cut, base), base), 1.0)
    out["last"] = (_r2(y[cut:], x[cut:, 0], base), 0.0)

    coef, dof = _ridge(x[:cut], y[:cut], 1e-8)
    out["har"] = (_r2(y[cut:], _apply(coef, x[cut:]), base), dof)

    # AR(1) in log-variance, which is a discretised Ornstein-Uhlenbeck and is
    # the model this quantity actually wants: a **value** reverting to a level.
    # It is here because the family has no such member - `reverting` reverts
    # the *rate* to zero, which makes the value integrated - so this is the
    # reference README item 6 should have been compared against. It is also a
    # one-timescale HAR, so `har` beating it is the multi-scale claim and
    # nothing else.
    last = x[:cut, 0]
    centre = float(last.mean())
    spread = float(((last - centre) ** 2).sum())
    phi = float(((last - centre) * (y[:cut] - centre)).sum() / spread) if spread > 0 else 0.0
    out["ou"] = (_r2(y[cut:], centre + phi * (x[cut:, 0] - centre), base), 2.0)

    # `start + cut` is the last index the training half can see, so the
    # reservoir's standardisation is fitted on exactly that much history.
    # **The control that decides what the reservoir's win means.** An ESN beats
    # HAR with 48 extra features and a memory far longer than 22 bars, so a
    # gain could be nonlinearity, capacity, or simply seeing further back.
    # `lin48` is the linear arm with the same reach: ridge on the last `SIZE`
    # raw lags, no nonlinearity at all. If it matches the ESN the win is
    # memory; if the ESN beats it, the win is the nonlinearity.
    deep = np.asarray(
        [[float(logvar[i - k]) for k in range(SIZE)] for i in range(start, start + len(y))],
        dtype=float,
    )
    best, pick = -math.inf, RIDGES[0]
    inner = max(cut // 2, 1)
    for lam in RIDGES:
        coef, _ = _ridge(deep[:inner], y[:inner], lam)
        got = _r2(y[inner:cut], _apply(coef, deep[inner:cut]), float(y[:inner].mean()))
        if got > best:
            best, pick = got, lam
    coef, dof = _ridge(deep[:cut], y[:cut], pick)
    out["lin48"] = (_r2(y[cut:], _apply(coef, deep[cut:]), base), dof)

    states = _reservoir(logvar, rng, start + cut)[start : start + len(y)]
    wide = np.hstack([x, states])
    best, bestlam = -math.inf, RIDGES[0]
    for lam in RIDGES:
        coef, _ = _ridge(wide[:cut], y[:cut], lam)
        # Chosen on a slice of the **training** half, never on the test half.
        inner = max(cut // 2, 1)
        got = _r2(y[inner:cut], _apply(coef, wide[inner:cut]), float(y[:inner].mean()))
        if got > best:
            best, bestlam = got, lam
    coef, dof = _ridge(wide[:cut], y[:cut], bestlam)
    out["esn"] = (_r2(y[cut:], _apply(coef, wide[cut:]), base), dof)

    _DESKS[(feed, frame)] = Desk()
    pooled = _statespace(logvar, start, len(y), feed, frame, None)
    out["pool"] = (_r2(y[cut:], pooled[cut:], base), 0.0)
    alone = _statespace(logvar, start, len(y), feed, frame, Diagonal())
    out["s4d"] = (_r2(y[cut:], alone[cut:], base), 0.0)
    return out


def main() -> None:
    print(
        "Can anything forecast dispersion better than HAR-Parkinson?\n"
        "Target: log Parkinson variance one bar ahead. Fitted on each series'\n"
        "first half, scored only on the second. R2 is against the training\n"
        "half's unconditional mean, so 0.00 means 'no better than a constant'.\n"
        "`dof` is the fit's effective degrees of freedom where it has one.\n"
        "The shuffled rows and the constant-sigma synthetics must read ~0.00.\n"
    )
    rng = np.random.default_rng(SEED)
    groups: dict[str, list[str]] = {}
    for path in sorted(CACHE.glob("*.1h.npz")):
        name = path.name[: -len(".1h.npz")]
        groups.setdefault(classify(name), []).append(name)
    print("classes in the cache:", ", ".join(sorted(groups)))

    arms = ("constant", "last", "ou", "har", "lin48", "s4d", "pool", "esn")
    for frame in FRAMES:
        for label in ("onescale", *TRADED, *CONTROLS):
            if label != "onescale" and label not in groups:
                continue
            for horizon in HORIZONS:
                for shuffle in (False, True):
                    pooled: dict[str, list[float]] = {}
                    dofs: dict[str, list[float]] = {}
                    names = (
                        [f"onescale{k}" for k in range(PER_CLASS)]
                        if label == "onescale"
                        else sorted(groups[label])[:PER_CLASS]
                    )
                    for name in names:
                        bars = onescale(LIMIT, rng) if label == "onescale" else load(name, frame)
                        if bars is None:
                            continue
                        cut = {k: v[-LIMIT:] for k, v in bars.items()}
                        got = score(cut, frame, name, rng, horizon=horizon, shuffle=shuffle)
                        for arm, (r2, dof) in got.items():
                            if math.isfinite(r2):
                                pooled.setdefault(arm, []).append(r2)
                            if dof:
                                dofs.setdefault(arm, []).append(dof)
                    if not pooled:
                        continue
                    tag = f"{label}, {frame}, h={horizon}" + (
                        "  [SHUFFLED CONTROL]" if shuffle else ""
                    )
                    print(f"\n=== {tag}   n={len(next(iter(pooled.values())))} instruments")
                    print(
                        f"  {'arm':<10}{'median R2':>11}{'min':>9}{'max':>9}{'beats har':>11}{'dof':>8}"
                    )
                    har = pooled.get("har", [])
                    ou = pooled.get("ou", [])
                    if har and ou:
                        top, bot = float(np.median(har)), float(np.median(ou))
                        ratio = top / bot if abs(bot) > 1e-9 else float("nan")
                        print(
                            f"  har/ou = {ratio:.2f}  (the onescale row is this ratio's baseline)"
                        )
                    for arm in arms:
                        rows = pooled.get(arm)
                        if not rows:
                            continue
                        wins = (
                            sum(a > b for a, b in zip(rows, har))
                            if har and len(rows) == len(har)
                            else 0
                        )
                        dof = float(np.median(dofs[arm])) if dofs.get(arm) else float("nan")
                        print(
                            f"  {arm:<10}{float(np.median(rows)):>11.4f}{min(rows):>9.4f}"
                            f"{max(rows):>9.4f}{wins:>8}/{len(rows):<3}{dof:>8.1f}"
                        )


if __name__ == "__main__":
    main()
