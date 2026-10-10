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
