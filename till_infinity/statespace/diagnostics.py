"""Is the filter right, and what should its parameters be - both from the residuals.

Two things this package was missing, and both come from the same place. They are
lifted from how statsmodels' state-space machinery works (Chad Fulton's
`MLEModel`), because the idea is standard and the version here is only standard
arithmetic written without the dependency.

## 1. The parameters are fitted, not chosen

**The likelihood comes as a byproduct of the Kalman filter.** Every step already
computes an innovation and its variance, so the log-likelihood of the data under
a given `jerk` costs nothing beyond running the filter. Maximise it and the
parameter is measured.

That matters here more than it would elsewhere, because this desk's record on
chosen constants is poor and documented: `DRIFT_VOL_PER_HOUR = 0.02` was picked
per hour, applied at every timeframe, and never fitted once. `fit_jerk` is the
procedure that would have settled it, and it needs no new data - only the
measurements the filter is already being given.

`TOUCH_NOISE_VOL` was measured a different way, by two independent estimates of
the touch dispersion. That is a better answer where it is available, because it
does not assume the model. MLE assumes the model and then asks which parameter
fits best within it, which is exactly the right question for `jerk` - a process
variance has no meaning outside the process - and the wrong one for `R`, which
can be observed directly.

## 2. Whether the model is right at all

Under a correctly specified filter the standardised innovations
`y_t / sqrt(S_t)` are **independent standard normals**. That is a testable claim
and it is the one worth testing, because it fails in informative directions:

* **autocorrelated** - the state equation is wrong. Something the filter treats
  as noise is predictable, which on a level usually means the drift is real and
  `jerk` is too small.
* **fat-tailed but uncorrelated** - the measurement model is wrong, not the
  dynamics. This is the case `robust.py` exists for, and `jarque_bera` is a
  better test of it than counting how often a gate fired.
* **variance drifting with time** - `R` is not constant, which on this desk is
  expected rather than surprising: a touch in a calm hour and one in a violent
  hour are not equally precise, which is why everything is in volatility units
  in the first place.

A filter whose residuals pass all three is not necessarily useful. One whose
residuals fail is definitely misspecified, and that is the cheaper question.

## Why pure Python

`scipy` is installed here only as a transitive dependency of `river` and
`yfinance` - it is not declared, so production code may not import it. The
arithmetic below is a few lines either way, and `tests/test_statespace.py`
checks it against `scipy` where `scipy` happens to be present.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass

HOUR = 3600.0

#: Lags for the Ljung-Box statistic. **Even on purpose**: the chi-squared
#: survival function has an exact closed form for even degrees of freedom, so an
#: even `h` gives a real p-value in pure Python instead of a table lookup.
LAGS = 10


def _chi2_sf(x: float, df: int) -> float:
    """P(chi^2_df > x), exact for even `df`.

    For even degrees of freedom the survival function is a finite sum, so there
    is no incomplete gamma to approximate:

        P = exp(-x/2) * sum_{k=0}^{df/2 - 1} (x/2)^k / k!
    """
    if x <= 0.0:
        return 1.0
    if df % 2 or df <= 0:
        raise ValueError(f"exact only for positive even df, got {df}")
    half = x / 2.0
    total, term = 1.0, 1.0
    for k in range(1, df // 2):
        term *= half / k
        total += term
    return math.exp(-half) * total


@dataclass(frozen=True, slots=True)
class Residuals:
    """What the standardised innovations say about the filter that produced them."""

    n: int
    mean: float
    sd: float
    skew: float
    kurtosis: float
    #: Ljung-Box statistic over `LAGS` lags, and its p-value. Small p means the
    #: residuals are autocorrelated, which means the state equation is wrong.
    ljung_box: float
    ljung_box_p: float
    #: Jarque-Bera statistic and p-value. Small p means non-normal residuals -
    #: the case `robust.py` is the cheap arm for.
    jarque_bera: float
    jarque_bera_p: float

    @property
    def overconfident(self) -> float:
        """How far the residual spread is from an honest 1.0.

        Above one, the filter's stated uncertainty is too tight - it is
        surprised more often than it says it will be. The shipped volatility
        EWMA measured 1.199 to 1.291 this way, which is 18-29% over-confident,
        and that number is what a particle filter was then able to improve on.
        """
        return self.sd

    @property
    def autocorrelated(self) -> bool:
        return self.ljung_box_p < 0.05

    @property
    def non_normal(self) -> bool:
        return self.jarque_bera_p < 0.05


def blocked_error(values, overlap: int, draws: int = 400, seed: int = 0) -> float:
    """Standard error of a mean when the observations **overlap**.

    `sd / sqrt(n)` assumes independent draws, and a study of overlapping
    windows or barrier trades has nothing of the kind: neighbours share most of
    the same price path. A moving-block bootstrap with blocks longer than
    `overlap` measures the dependence instead of assuming it.

    **This is the number a `must read zero` check needs, and not having it once
    cost a line of work.** `statespace-volatility-convexity.md` carried a
    residual of `-0.0706` that looked like an unexplained defect for as long as
    it took to compute one standard error; it is `0.0231`, so the residual is
    `z = -3.06` and real.

    It is also worth recording what the **naive** correction gets wrong there.
    Barrier trades entered 24 bars apart with 500 bars of patience look 21-fold
    overlapped, which gives `se = 0.085` and a reassuring `z = -0.83` - but
    about three quarters stop at the near barrier within a few dozen bars, so
    the mean duration is nowhere near the patience window and the true overlap
    is slight. Pass the **horizon** as `overlap` and let the bootstrap find the
    dependence; do not divide the sample by it.
    """
    import numpy as np

    got = np.asarray(values, dtype=float)
    got = got[np.isfinite(got)]
    if len(got) < 50:
        return float("nan")
    size = max(3 * int(overlap), 10)
    if size >= len(got) // 4:
        size = max(len(got) // 8, 2)
    starts = len(got) - size
    if starts < 2:
        return float("nan")
    rng = np.random.default_rng(seed)
    count = max(len(got) // size, 1)
    means = []
    for _ in range(draws):
        picks = rng.integers(0, starts, size=count)
        means.append(float(np.concatenate([got[i : i + size] for i in picks]).mean()))
    return float(np.std(means))


def crps(quantiles: Sequence[tuple[float, float]], outcome: float) -> float:
    """Continuous ranked probability score from a set of quantiles.

    **The score the whole forecast line is judged on, and it was not in the
    library.** `statespace-path-ensembles.md` and `statespace-tail-shape.md`
    both conclude on CRPS - "nothing beats the walk at any horizon" - and both
    computed it in a research harness.

    Scored through the quantile-loss identity

        CRPS = 2 * integral over tau of the pinball loss at level tau

    which needs **only quantiles and never a density**. That is the property
    worth having: a Gaussian band, a Student-t band and a shape-free empirical
    band are then scored by one instrument instead of three. The tail-shape
    work needed a closed form *and* a quadrature and had to check them against
    each other - they agreed to `1e-4` on twenty thousand normals, which was
    reassuring and is work this avoids.

    `quantiles` is `(level, value)` in ascending level, as
    `[(0.02, -2.05), (0.04, -1.75), ...]`. The integral is a left Riemann sum
    over the levels supplied, so a denser grid is a more accurate score and the
    caller chooses the trade.
    """
    total, last = 0.0, 0.0
    for tau, value in quantiles:
        if not (math.isfinite(tau) and math.isfinite(value)):
            continue
        loss = (outcome - value) * tau if outcome >= value else (value - outcome) * (1.0 - tau)
        total += loss * (tau - last)
        last = tau
    return 2.0 * total


def pit_flatness(values: Sequence[float], bins: int = 20) -> float:
    """Chi-square of a PIT histogram against uniform, per degree of freedom.

    1.0 is calibrated. The measured context is what makes it worth carrying:
    **no Gaussian forecast in this package is calibrated on real data**, with
    flatness running 18 to 461, the walk included.

    A caution that belongs with the number rather than beside it: an
    **empirical** predictive CDF scores near 1.0 almost by construction, since
    its PIT is the rank of a new residual among past ones and a rank among
    exchangeable draws is uniform by definition. So this measures whether a
    *parametric* shape fits, and it cannot be used to prefer a shape-free band -
    for that, score `crps`.
    """
    usable = [v for v in values if math.isfinite(v)]
    if len(usable) < 200 or bins < 2:
        return float("nan")
    counts = [0] * bins
    for v in usable:
        at = min(int(max(min(v, 1.0 - 1e-12), 0.0) * bins), bins - 1)
        counts[at] += 1
    want = len(usable) / bins
    return sum((c - want) ** 2 / want for c in counts) / (bins - 1)


def residuals(standardised: Sequence[float], lags: int = LAGS) -> Residuals | None:
    """Diagnose a run of standardised innovations. None if there are too few.

    `lags` must be even - see `_chi2_sf`. Thirty points is the floor, below which
    the moments are noise and a p-value would be theatre.
    """
    z = [float(v) for v in standardised if math.isfinite(v)]
    n = len(z)
    if n < 30 or lags <= 0 or lags % 2:
        return None

    mean = sum(z) / n
    centred = [v - mean for v in z]
    var = sum(v * v for v in centred) / n
    sd = math.sqrt(var)
    if sd <= 0:
        return None
    m3 = sum(v**3 for v in centred) / n
    m4 = sum(v**4 for v in centred) / n
    skew = m3 / sd**3
    kurt = m4 / var**2

    # Ljung-Box over `lags`, which asks whether anything the filter called noise
    # was predictable.
    used = min(lags, n - 2)
    used -= used % 2
    if used <= 0:
        return None
    q = 0.0
    for k in range(1, used + 1):
        num = sum(centred[i] * centred[i - k] for i in range(k, n))
        rho = num / (var * n)
        q += rho * rho / (n - k)
    q *= n * (n + 2)

    # Jarque-Bera: skew and excess kurtosis against normal, chi-squared with 2
    # degrees of freedom, whose survival function is exactly exp(-x/2).
    jb = n / 6.0 * (skew**2 + 0.25 * (kurt - 3.0) ** 2)

    return Residuals(
        n=n,
        mean=mean,
        sd=sd,
        skew=skew,
        kurtosis=kurt,
        ljung_box=q,
        ljung_box_p=_chi2_sf(q, used),
        jarque_bera=jb,
        jarque_bera_p=_chi2_sf(jb, 2),
    )


#: Bracket the search over `log10(jerk)`. Wide, because the right order of
#: magnitude is the thing being discovered and a bracket that excludes it returns
#: its own edge without complaining.
LOG_JERK_LOW = -12.0
LOG_JERK_HIGH = 2.0


def fit_em(
    build: Callable[[float, float], object],
    times: Sequence[float],
    measured: Sequence[float],
    *,
    jerk: float = 1e-4,
    noise: float = 0.25,
    rounds: int = 25,
    tolerance: float = 1e-4,
) -> tuple[float, float, float, int]:
    """Expectation-maximisation for `jerk` and `R`. `(jerk, noise, loglike, rounds)`.

    **Item 3 on `README.md`'s priority list, finally.** It asked for EM and got
    coordinate ascent, because the M-step for `Q` needs the smoothed lag-one
    cross-covariances and `smoothing.Smoothed` did not carry them. It does now,
    so this is the thing that was asked for.

    ## The two steps

    The **E-step** is the smoother: it returns `x(t|T)`, `P(t|T)` and
    `P(t, t-1|T)` under the current parameters, which are exactly the
    sufficient statistics the complete-data likelihood needs.

    The **M-step** is closed form. With `H = [1, 0, 0]`,

        R = (1/T) sum[ (y - H x)^2 + H P H' ]

    and, because this family's process noise is a **scalar spectral density
    times a fixed shape**, `Q(dt) = jerk * G(dt)`, the maximiser for `jerk`
    involves `M = S11 - S10 F' - F S10' + F S00 F'` with
    `S11 = P(t) + x x'`, `S10 = P(t,t-1) + x(t) x(t-1)'` and
    `S00 = P(t-1) + x(t-1) x(t-1)'`. Both are averages of quantities the
    E-step produced; neither is a search.

    ## The scalar step is a projection, not `tr(G^-1 M)`, and that is measured

    The exact maximiser is `(1/(T d)) sum tr( G(dt)^-1 M )`. **It does not
    work here**, and the failure is not subtle: `G` for an integrated-jerk
    model is badly conditioned - its entries at `dt = 1` run from 0.05 to 1.0
    with a near-degenerate structure - and `M` under a too-small `jerk` is of
    order `1e-5`, so the trace cancels into *negative* territory. Measured,
    the first M-step drove `jerk` to its floor of `1e-12`, which froze the
    state, which sent the next round's likelihood to **-2.5e9** and `R` to
    174,252.

    So the scalar comes from the **Frobenius projection** of `M` onto `G`:

        jerk = sum <M, G> / sum <G, G>

    which is the least-squares scalar `c` solving `M ~ c G`, needs no inverse,
    and is non-negative whenever `M` is - which it is, being an expected outer
    product. It is not the exact ML step and this says so; it is the stable
    one, and the likelihood it reaches is the number to judge it by.

    ## `G(dt)` is read from the member, not re-derived

    A second copy of the integrated-jerk `Q` would be two definitions of one
    thing - shape #5 in the `finding-bugs` skill, and the one that has bitten
    this package hardest. Instead a probe member is built with `jerk = 1`, its
    covariance zeroed, and advanced by `dt`: what grows is `G(dt)` by
    definition. It costs one `predict` per distinct step and it cannot drift
    from the member's own arithmetic, because it *is* the member's arithmetic.

    ## What EM buys over `fit_both`, measured - and it is not the rate

    I expected a better rate: coordinate ascent crawls along the diagonal
    ridge `jerk` and `R` trade off along, and EM is supposed to move along it
    directly. **Measured on a 1,500-point path generated at `jerk = 1e-3`,
    `R = 0.25`:**

    | | jerk | noise | loglike | time |
    |---|---|---|---|---|
    | EM | 1.157e-3 | 0.2355 | -1666.7 | **4.9s**, 22 rounds |
    | `fit_both` | 1.263e-3 | 0.2350 | -1666.3 | **0.4s** |

    Same optimum - the likelihoods differ by 0.4 nats over 1,500 points - and
    EM is **twelve times slower**. The textbook rate advantage does not
    survive the cost per iteration here: an EM round is a full forward-backward
    smoother pass, where a golden-section step is a filter pass, and the
    smoother is several times the work.

    What EM does buy is a **closer parameter**: 1.157e-3 against 1.263e-3 for
    a truth of 1e-3. If the parameter is the answer, use this; if the
    likelihood is, `fit_both` reaches the same place sooner.

    The honest summary is that the item on the list asked for EM, EM is now
    here, and it is not obviously the better tool - which is worth more than
    an implementation that was never compared.

    EM maximises a lower bound rather than the likelihood itself, so the
    monotonicity guarantee is on that bound. The likelihood reported here is
    the filter's own, recomputed at the final parameters, which is the honest
    number to compare with anything else in this package.
    """
    import math as _math

    from .smoothing import smooth

    size = 0
    current_jerk, current_noise = float(jerk), float(noise)
    best = -_math.inf
    used = 0

    for round_number in range(1, rounds + 1):
        used = round_number
        got = smooth(
            lambda j=current_jerk, n=current_noise: build(j, n),
            times,
            measured,
            noise=current_noise,
        )
        if got is None or not got.covariances:
            break
        size = len(got.states[0])
        probe_member = build(1.0, current_noise)
        if not callable(getattr(probe_member, "transition", None)):
            break

        total_noise = 0.0
        total_jerk = 0.0
        total_shape = 0.0
        steps = 0
        for i in range(len(got.states)):
            residual = float(measured[i]) - got.states[i][0]
            total_noise += residual * residual + got.covariances[i][0][0]
            if i == 0 or not got.cross[i]:
                continue
            dt = (float(times[i]) - float(times[i - 1])) / HOUR
            if dt <= 0.0:
                continue
            shape = _shape(build, dt, current_noise)
            if shape is None:
                continue
            transition = [list(r) for r in probe_member.transition(dt)]
            bracket = _bracket(got, i, transition)
            # <M, G> and <G, G>, accumulated separately: the estimator is the
            # ratio of the sums, not the average of the ratios.
            total_jerk += sum(bracket[a][b] * shape[a][b] for a in range(size) for b in range(size))
            total_shape += sum(shape[a][b] * shape[a][b] for a in range(size) for b in range(size))
            steps += 1

        if steps == 0 or total_shape <= 0.0:
            break
        current_noise = max(total_noise / len(got.states), 1e-12)
        current_jerk = max(total_jerk / total_shape, 1e-12)
        if got.loglike - best < tolerance * abs(best + 1.0):
            best = max(best, got.loglike)
            break
        best = got.loglike

    final = smooth(
        lambda: build(current_jerk, current_noise),
        times,
        measured,
        noise=current_noise,
    )
    return (
        current_jerk,
        current_noise,
        float(final.loglike) if final else best,
        used,
    )


def _shape(build, dt: float, noise: float) -> list[list[float]] | None:
    """`G(dt)`: the process noise a unit spectral density grows over `dt`.

    Read from the member by zeroing a probe's covariance and advancing it,
    rather than re-deriving the integrator's `Q`. Two definitions of one
    matrix is the error this avoids.
    """
    probe = build(1.0, noise)
    if not callable(getattr(probe, "covariance", None)):
        return None
    width = len(probe.state())
    for a in range(width):
        for b in range(width):
            name = f"p{min(a, b)}{max(a, b)}"
            if hasattr(probe, name):
                setattr(probe, name, 0.0)
    probe.at = 0.0
    probe.predict(dt * HOUR)
    grown = [list(r) for r in probe.covariance()]
    return grown if any(any(r) for r in grown) else None


def _bracket(got, i: int, transition: list[list[float]]) -> list[list[float]]:
    """`S11 - S10 F' - F S10' + F S00 F'`, the M-step's numerator."""
    size = len(got.states[i])
    now = list(got.states[i])
    before = list(got.states[i - 1])
    s11 = [[got.covariances[i][a][b] + now[a] * now[b] for b in range(size)] for a in range(size)]
    s10 = [[got.cross[i][a][b] + now[a] * before[b] for b in range(size)] for a in range(size)]
    s00 = [
        [got.covariances[i - 1][a][b] + before[a] * before[b] for b in range(size)]
        for a in range(size)
    ]
    ft = [[transition[b][a] for b in range(size)] for a in range(size)]
    s10ft = _product(s10, ft)
    fs01 = [[s10ft[b][a] for b in range(size)] for a in range(size)]
    fs00ft = _product(_product(transition, s00), ft)
    return [
        [s11[a][b] - s10ft[a][b] - fs01[a][b] + fs00ft[a][b] for b in range(size)]
        for a in range(size)
    ]


def _product(left: list[list[float]], right: list[list[float]]) -> list[list[float]]:
    size = len(left)
    return [
        [sum(left[a][k] * right[k][b] for k in range(size)) for b in range(size)]
        for a in range(size)
    ]


def _invert(matrix: list[list[float]]) -> list[list[float]] | None:
    """Gauss-Jordan inverse. `None` when singular, which a caller must skip."""
    size = len(matrix)
    work = [list(matrix[i]) + [1.0 if i == j else 0.0 for j in range(size)] for i in range(size)]
    for col in range(size):
        pivot = max(range(col, size), key=lambda r: abs(work[r][col]))
        if abs(work[pivot][col]) < 1e-18:
            return None
        work[col], work[pivot] = work[pivot], work[col]
        scale = work[col][col]
        work[col] = [v / scale for v in work[col]]
        for row in range(size):
            if row == col:
                continue
            factor = work[row][col]
            if factor:
                work[row] = [a - factor * b for a, b in zip(work[row], work[col], strict=True)]
    return [row[size:] for row in work]


def fit_both(
    run: Callable[[float, float], float],
    *,
    noise_low: float = -4.0,
    noise_high: float = 2.0,
    rounds: int = 8,
    tolerance: float = 0.01,
) -> tuple[float, float, float]:
    """Fit `jerk` and the measurement noise together. `(jerk, noise, loglike)`.

    Item 3 on `README.md`'s priority list, which asks for *"the route to `jerk`
    **and** `R` together rather than measuring one and searching the other"*.

    ## Why this is coordinate ascent and not EM, which the list asked for

    The list says EM, and EM is the right answer in principle: the E-step is
    the smoothed posterior and the M-step for the noise covariances is closed
    form. **It is not available here yet**, and the reason is concrete rather
    than a preference. The M-step for `Q` needs the smoothed **lag-one
    cross-covariances** `P(t, t-1 | T)`, and `smoothing.Smoothed` returns the
    smoothed states and the standard deviation of the observed component -
    not the full covariance, and not the cross terms. Extending the smoother
    to carry them is the prerequisite, and it is written down rather than done
    because doing it badly would be worse than the alternative below.

    What this does instead is alternate a one-dimensional search on each
    parameter until neither moves. It has one property EM does not: it
    maximises the **exact marginal likelihood** rather than a lower bound on
    it, so there is no gap between what is being maximised and what is being
    reported. It has one EM does: each round cannot decrease the likelihood,
    because each half is a maximisation of the same objective with the other
    held fixed.

    What it lacks is EM's rate - a 2-D coordinate ascent crawls along a
    diagonal ridge, and `jerk` and `R` trade off against each other almost
    exactly, which is a diagonal ridge. `rounds` is capped for that reason and
    the returned likelihood says how far it got.

    `run(jerk, noise)` must drive a **fresh** filter each time, for the same
    reason `fit_jerk` says so: reusing one makes the answer depend on the order
    candidates were tried in.
    """
    jerk = 10.0 ** ((LOG_JERK_LOW + LOG_JERK_HIGH) / 2.0)
    noise = 10.0 ** ((noise_low + noise_high) / 2.0)
    best = run(jerk, noise)
    for _ in range(rounds):
        jerk, got = fit_jerk(lambda j, n=noise: run(j, n), tolerance=tolerance)
        noise, got = fit_jerk(
            lambda n, j=jerk: run(j, n),
            low=noise_low,
            high=noise_high,
            tolerance=tolerance,
        )
        if got - best < tolerance:
            best = max(best, got)
            break
        best = got
    return jerk, noise, best


def fit_jerk(
    run: Callable[[float], float],
    *,
    low: float = LOG_JERK_LOW,
    high: float = LOG_JERK_HIGH,
    tolerance: float = 0.01,
) -> tuple[float, float]:
    """Maximise `run(jerk)` over `jerk`. Returns `(jerk, log-likelihood)`.

    `run` takes a candidate `jerk`, drives a fresh filter over the measurements,
    and returns its accumulated `loglike`. One parameter, so golden-section on
    `log10(jerk)` rather than a dependency on an optimiser: the likelihood of a
    state-space model in one variance is smooth and unimodal in practice, and
    searching in logs is what makes a bracket spanning fourteen orders of
    magnitude tractable.

    **The caller is responsible for the filter being fresh each time.** Reusing
    one would make the likelihood depend on the order candidates were tried in,
    which is the kind of bug that produces a confident wrong answer.

    Returning the edge of the bracket is a real outcome and the caller should
    check for it: it means the best `jerk` is outside the range offered, not that
    the range was right.
    """
    phi = (math.sqrt(5.0) - 1.0) / 2.0
    a, b = float(low), float(high)
    c, d = b - phi * (b - a), a + phi * (b - a)
    fc, fd = run(10.0**c), run(10.0**d)
    while b - a > tolerance:
        if fc > fd:
            b, d, fd = d, c, fc
            c = b - phi * (b - a)
            fc = run(10.0**c)
        else:
            a, c, fc = c, d, fd
            d = a + phi * (b - a)
            fd = run(10.0**d)
    best = c if fc > fd else d
    return 10.0**best, max(fc, fd)


def shape_cost(
    build: Callable[[float, float], object],
    times: Sequence[float],
    measured: Sequence[float],
    *,
    jerk: float = 1e-4,
    noise: float = 0.25,
) -> dict[str, float] | None:
    """What the fixed `Q` shape costs, which is what a matrix M-step would buy.

    `family.MISSING["em"]` says the matrix M-step is the half still missing:
    `fit_em` fits a scalar multiplier on `Q(dt) = jerk * G(dt)` by Frobenius
    projection, where a full M-step would fit the covariance's **entries**.

    ## Why a free matrix `Q` is not simply the better estimator

    The textbook M-step for a linear-Gaussian state space is
    `Q = (1/T) sum M(t)` with `M` exactly what `_bracket` returns - no inverse,
    no conditioning problem, simpler than the projection. The reason this
    package does not do it is **not** numerical.

    It is that `Q` here is a function of `dt`. A continuous-time model
    sampled at irregular times has a different `Q` at every step, and
    `Q(dt) = jerk * G(dt)` is what ties them together with one parameter. A
    free matrix `Q` is a statement that every step is the same length, which
    is the per-bar assumption `I6` exists to reject - and averaging `M(t)`
    across steps of different `dt` estimates nothing in particular.

    So the question a matrix M-step would answer is not "what is `Q`" but
    **"is the shape right"**, and that is answerable without one.

    ## The measurement

    For each step the scalar M-step solves `M ~ c G` in the least-squares
    sense. The **relative residual** of that fit,

        ||M - c G||_F / ||M||_F

    is what the one-parameter family cannot represent. Zero means the shape is
    exactly right and a free `Q` would buy nothing; near one means `M` and `G`
    are nearly orthogonal and the scalar is discarding almost everything.

    Returned with the cosine between `M` and `G`, which is the same fact read
    the other way and is bounded, so it can be compared across series.
    """
    import math as _math
    import statistics

    from .smoothing import smooth

    got = smooth(
        lambda j=float(jerk), n=float(noise): build(j, n),
        times,
        measured,
        noise=float(noise),
    )
    if got is None or not got.covariances or not got.cross:
        return None
    probe = build(1.0, float(noise))
    if not callable(getattr(probe, "transition", None)):
        return None
    size = len(got.states[0])

    residuals: list[float] = []
    cosines: list[float] = []
    scalars: list[float] = []
    for i in range(1, len(got.states)):
        if not got.cross[i]:
            continue
        dt = (float(times[i]) - float(times[i - 1])) / HOUR
        if dt <= 0.0:
            continue
        shape = _shape(build, dt, float(noise))
        if shape is None:
            continue
        bracket = _bracket(got, i, [list(r) for r in probe.transition(dt)])

        mg = sum(bracket[a][b] * shape[a][b] for a in range(size) for b in range(size))
        gg = sum(shape[a][b] * shape[a][b] for a in range(size) for b in range(size))
        mm = sum(bracket[a][b] * bracket[a][b] for a in range(size) for b in range(size))
        if gg <= 0.0 or mm <= 0.0:
            continue
        scalar = mg / gg
        left = mm - 2.0 * scalar * mg + scalar * scalar * gg
        residuals.append(_math.sqrt(max(left, 0.0) / mm))
        cosines.append(mg / _math.sqrt(mm * gg))
        scalars.append(scalar)

    if len(residuals) < 10:
        return None
    return {
        "steps": float(len(residuals)),
        "residual": statistics.median(residuals),
        "cosine": statistics.median(cosines),
        "scalar": statistics.median(scalars),
        # How much the fitted scalar moves from step to step. A shape that is
        # right gives one scalar; a shape that is wrong gives a different
        # best-fit multiple at every step, and that spread is a second
        # symptom of the same thing.
        "scalar_spread": (
            statistics.pstdev(scalars) / abs(statistics.fmean(scalars))
            if statistics.fmean(scalars) != 0.0
            else float("nan")
        ),
    }
