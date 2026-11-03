"""How long a departure from a level lasts: survival, the time exponent, the hazard.

The third quantity, independent of the shape and the distance the committed
study measured. `a-magnet-is-a-shared-reference` ends with the instruction this
answers - *use the time exponent, not the return rate* - and the committed run
used distance, so this is the reading the memory actually asked for.

## Why the exponent is the quantity and the mean is not

**The null is exact, parameter-free and distribution-free.** By Sparre
Andersen's theorem the first-passage time of a symmetric random walk back to a
level satisfies `P(T > t) ~ t^(-1/2)` **whatever the step distribution** - the
same 1/2 for a Gaussian walk, for a fat-tailed one and for this market's own
resampled steps. So:

* the asymptotic null exponent is **0.5**, with nothing to fit;
* a reading at the walk's means duration is geometry -
  `a-return-rate-is-geometry` in the time domain, which is the same trap the
  distance readings fell into;
* **a power-law survival has no characteristic length.** If the exponent sits
  at the walk's then "how long does a bounce last" has no answer: the
  distribution is scale-free, the mean is dominated by the censoring window and
  a time exit set to any particular number of bars is arbitrary. That is a
  result about the SMC rule's 1,440-M1-bar clock, not an absence of one.

## The 0.5 is an anchor, not the comparison, and that is measured

**This estimator does not read 0.5 on a walk at these horizons.** Simulated
symmetric Gaussian walks, 30,000 paths, the estimator exactly as it runs here:

| horizon | fit to 0.5 | fit to 0.75 | fit to 1.0 | censored |
|---|---|---|---|---|
| 20 (the 1d setting) | **0.397** | 0.414 | 0.424 | 0.275 |
| 48 (1h and 15m) | **0.429** | 0.439 | 0.445 | 0.181 |
| 100 | 0.446 | 0.457 | 0.463 | 0.127 |
| 200 | 0.460 | 0.465 | 0.467 | 0.092 |

The bias is finite-horizon censoring and it **shrinks monotonically toward 0.5
as the horizon grows**, which is what confirms the estimator is right rather
than broken. But it moves with the window, so by the standard this desk already
set - the roughness exponent that drifted by a factor of three across windows
and had no value quoted because of it - **no absolute exponent is quotable
here**. The comparison is real against the **same estimator on the matched null
arms at the same horizon**, which is the discipline every other reading in this
study already follows. `z_vs_theory` is printed as a sanity anchor and is not a
test; a cell that beats its hardest arm is the only thing that counts.

So the hazard shape is tested rather than assumed. A **flat** hazard is an
exponential survival and *does* have a characteristic length, `1 / h`; a
**decaying** hazard is the power law and does not. Both fits are reported with
the same block bootstrap and the comparison is by residual, not by eye.

## Censoring is the main hazard and it points the wrong way

A departure still running at the horizon has no measured length. A mean over
the uncensored episodes alone is biased **short**, and short is exactly what a
"bounces are brief" finding would look like - so the bias manufactures the
result. Everything here is Kaplan-Meier, the censored share travels with every
cell, and **no bare mean duration is reported anywhere**. Where the censored
share is large the honest answer is "longer than the horizon", and that is
written down rather than estimated through.

## What this does not do

It does not fold duration into the existing grade. Two bounces with identical
hit rates and identical R at a fixed target can have very different lengths,
so `correlations` reports whether duration moves with the shape bits and with
R at all, and the answer is reported rather than assumed either way.
"""

from __future__ import annotations

import math
import statistics as st
from dataclasses import dataclass

import numpy as np

from research.ideas.level_bounce import DURATION_CENSORED, AGE_EDGES, Rows, TARGETS
from research.ideas.level_bounce_agg import DRAWS, FLOOR, LEAST, _cell_median_split, age_bin

#: The walk's exponent, exactly, for any symmetric step distribution. Not a
#: fitted null and not an arm: Sparre Andersen's theorem supplies it.
WALK_EXPONENT = 0.5

#: The bar range the exponent is fitted over, as a fraction of the horizon.
#: Pre-registered, and both ends are there for a reason:
#:
#: * **from 2 bars**, because `t = 1` is a discreteness artefact - a bar whose
#:   range straddles the level ends the departure on the first bar, and that
#:   share is set by the bar's width against the unit rather than by any
#:   exponent;
#: * **to half the horizon**, because the Kaplan-Meier curve's last points sit
#:   where almost everything left is censored and their variance swamps the
#:   fit. Fitting into the censoring region is how a censored sample produces a
#:   confident exponent.
FIT_FROM, FIT_TO = 2, 0.5


@dataclass(frozen=True, slots=True)
class Survival:
    """A Kaplan-Meier curve and the two shapes fitted to it.

    `exponent` is the power-law slope of `log S(t)` against `log t`, to be read
    against `WALK_EXPONENT` 0.5 and against the same number on every null arm.
    `rate` is the exponential hazard fitted to the same points. `power_better`
    says which fit left the smaller residual - the test of whether a
    characteristic length exists at all.
    """

    n: int
    censored: float
    #: Median from the curve, or `None` when the curve never reaches 0.5 -
    #: which is itself the answer "longer than the horizon".
    median: float | None
    exponent: float
    exponent_se: float
    rate: float
    power_resid: float
    exp_resid: float
    #: Survival at the horizon: the share still away from the level at the end.
    tail: float
    #: `S(t)` at 1, 2, 4, 8 and 16 bars.
    #:
    #: Carried because **the median is pinned at 1 bar** and so says almost
    #: nothing: measured on eurusd 1d, half of departures end on the very next
    #: bar, because a bar's range is wide against the level and price prints
    #: back through it immediately. That is a property of the bar, not of the
    #: bounce, and it is why `FIT_FROM` is 2. The curve read at fixed times is
    #: what shows the shape a single quantile hides.
    at: dict[int, float]

    @property
    def power_better(self) -> bool:
        return self.power_resid < self.exp_resid

    @property
    def z_vs_theory(self) -> float:
        """Distance from the asymptotic 0.5, in its own se. **An anchor, not a test.**

        This estimator reads 0.397 on a true walk at a 20-bar horizon and 0.429
        at 48 - see the module docstring's measured table - so a large value
        here is mostly finite-horizon censoring and not a finding. The test is
        real against the same estimator on the matched arms at the same
        horizon, which the report computes.
        """
        return (self.exponent - WALK_EXPONENT) / self.exponent_se if self.exponent_se > 0 else 0.0


def kaplan_meier(duration: np.ndarray, censored: np.ndarray, horizon: int):
    """`(times, survival)` by the product-limit estimator.

    Right-censored episodes leave the risk set at their censoring time without
    counting as an event, which is the whole point: a departure still running
    at the horizon is evidence *for* long durations and a naive estimator that
    dropped it would delete that evidence.
    """
    keep = duration != DURATION_CENSORED
    dur, cen = duration[keep], censored[keep]
    if len(dur) == 0:
        return np.empty(0), np.empty(0)
    times = np.arange(1, horizon + 1)
    at_risk = np.array([(dur >= t).sum() for t in times], dtype=float)
    events = np.array([((dur == t) & ~cen).sum() for t in times], dtype=float)
    factor = np.divide(
        at_risk - events, at_risk, out=np.ones_like(at_risk), where=at_risk > 0
    )
    return times, np.cumprod(factor)


def _fit(times: np.ndarray, surv: np.ndarray, horizon: int):
    """`(exponent, rate, power residual, exponential residual)` on one curve.

    Both fits use the same points, so the residual comparison is fair. The
    power law is a line in `log S` against `log t` and the exponential is a
    line in `log S` against `t`; the exponent is the negated slope of the
    first, so a steeper decay reads as a larger exponent.
    """
    hi = max(FIT_FROM + 2, int(horizon * FIT_TO))
    sel = (times >= FIT_FROM) & (times <= hi) & (surv > 0)
    if sel.sum() < 3:
        return float("nan"), float("nan"), float("inf"), float("inf")
    t, s = times[sel].astype(float), surv[sel]
    log_s = np.log(s)
    slope, intercept = np.polyfit(np.log(t), log_s, 1)
    power_resid = float(np.mean((log_s - (slope * np.log(t) + intercept)) ** 2))
    e_slope, e_intercept = np.polyfit(t, log_s, 1)
    exp_resid = float(np.mean((log_s - (e_slope * t + e_intercept)) ** 2))
    return -float(slope), -float(e_slope), power_resid, exp_resid


def survival_for(
    rows: Rows,
    mask: np.ndarray,
    horizon: int,
    *,
    draws: int = DRAWS,
    seed: int = 0,
) -> Survival | None:
    """The curve, the exponent and the hazard shape, with a block bootstrap.

    Blocks and not rows: nearby episodes share outcome bars, so an ordinary
    standard error on the exponent is far too narrow - the same reason
    `level_bounce_agg` resamples blocks for every other statistic here.
    """
    use = mask & (rows.duration != DURATION_CENSORED)
    if int(use.sum()) < LEAST:
        return None
    dur, cen, block = rows.duration[use], rows.censored[use], rows.block[use]
    times, surv = kaplan_meier(dur, cen, horizon)
    if len(times) == 0:
        return None
    exponent, rate, p_res, e_res = _fit(times, surv, horizon)
    if math.isnan(exponent):
        return None
    below = np.flatnonzero(surv <= 0.5)
    at = {t: float(surv[t - 1]) for t in (1, 2, 4, 8, 16) if t <= len(surv)}
    keys = np.unique(block)
    rng = np.random.default_rng(seed)
    spread = []
    for _ in range(draws):
        pick = rng.choice(keys, len(keys))
        counts = np.bincount(
            np.searchsorted(keys, pick), minlength=len(keys)
        )[np.searchsorted(keys, block)]
        take = counts > 0
        if take.sum() < FLOOR:
            continue
        t2, s2 = kaplan_meier(dur[take], cen[take], horizon)
        got, _, _, _ = _fit(t2, s2, horizon)
        if not math.isnan(got):
            spread.append(got)
    return Survival(
        n=int(use.sum()),
        censored=float(cen.mean()),
        median=float(times[below[0]]) if len(below) else None,
        exponent=exponent,
        exponent_se=float(st.pstdev(spread)) if len(spread) > 5 else 0.0,
        rate=rate,
        power_resid=p_res,
        exp_resid=e_res,
        tail=float(surv[-1]),
        at=at,
    )


@dataclass(frozen=True, slots=True)
class Split:
    """High-grade against low-grade survival, for the causal grading question."""

    n_high: int
    n_low: int
    median_high: float | None
    median_low: float | None
    exponent_high: float
    exponent_low: float
    #: High minus low, with a paired block-bootstrap standard error.
    diff: float
    se: float

    @property
    def t(self) -> float:
        return self.diff / self.se if self.se > 0 else 0.0


def grade_survival_for(
    rows: Rows,
    mask: np.ndarray,
    grade: str,
    horizon: int,
    *,
    draws: int = DRAWS,
    seed: int = 0,
) -> Split | None:
    """Does a level's **previous** durations predict its next one?

    Split at each compression-by-age cell's own median grade, exactly as the
    committed study splits for shape and R, so the three questions are asked
    the same way and the answers are comparable. The statistic is the
    difference in fitted exponent, paired on the same blocks in each draw so
    the common regime cancels.
    """
    use = mask & (rows.duration != DURATION_CENSORED) & (rows.n_prev >= 1)
    if int(use.sum()) < 2 * LEAST:
        return None
    cell = rows.stratum[use] * (len(AGE_EDGES) + 1) + age_bin(rows.n_prev[use])
    bucket = _cell_median_split(getattr(rows, grade)[use], cell)
    dur, cen, block = rows.duration[use], rows.censored[use], rows.block[use]
    hi_m, lo_m = bucket == 1, bucket == 0
    if int(hi_m.sum()) < LEAST or int(lo_m.sum()) < LEAST:
        return None

    def one(sel):
        t, s = kaplan_meier(dur[sel], cen[sel], horizon)
        if len(t) == 0:
            return None, None
        got, _, _, _ = _fit(t, s, horizon)
        below = np.flatnonzero(s <= 0.5)
        return (None if math.isnan(got) else got), (float(t[below[0]]) if len(below) else None)

    e_hi, m_hi = one(hi_m)
    e_lo, m_lo = one(lo_m)
    if e_hi is None or e_lo is None:
        return None
    keys = np.unique(block)
    rng = np.random.default_rng(seed)
    spread = []
    for _ in range(draws):
        pick = rng.choice(keys, len(keys))
        counts = np.bincount(
            np.searchsorted(keys, pick), minlength=len(keys)
        )[np.searchsorted(keys, block)]
        take = counts > 0
        a, _ = one(hi_m & take)
        b, _ = one(lo_m & take)
        if a is not None and b is not None:
            spread.append(a - b)
    return Split(
        n_high=int(hi_m.sum()),
        n_low=int(lo_m.sum()),
        median_high=m_hi,
        median_low=m_lo,
        exponent_high=e_hi,
        exponent_low=e_lo,
        diff=e_hi - e_lo,
        se=float(st.pstdev(spread)) if len(spread) > 5 else 0.0,
    )


def correlations(rows: Rows, mask: np.ndarray) -> dict[str, float]:
    """Does duration restate the shape or the R the committed study measured?

    The coordinator's third requirement, and it is a real question rather than
    a formality: if duration correlates near 1 with `r_mtm` it is a third name
    for the same reading and the arm buys nothing. Spearman, because duration
    is a censored count and a Pearson correlation on it would be a statement
    about the censoring window.

    Censored episodes are **kept** with their lower-bound duration. They are
    the long ones, and a correlation computed without them is a correlation
    over short bounces only.
    """
    use = mask & (rows.duration != DURATION_CENSORED)
    if int(use.sum()) < LEAST:
        return {}
    dur = rows.duration[use].astype(float)
    out: dict[str, float] = {"n": float(use.sum()), "censored": float(rows.censored[use].mean())}
    against: dict[str, np.ndarray] = {
        "r_mtm": rows.r_mtm[use],
        "peak_at": rows.peak_at[use].astype(float),
        "held": rows.held[use].astype(float),
        "excursion": rows.excursion[use],
    }
    for target in TARGETS:
        against[f"r{target:g}"] = rows.r[target][use]
    from research.ideas.level_bounce import RUN, SHARP, SHARP_BAR

    for name, bit in (("sharp", SHARP), ("run", RUN), ("sharp_bar", SHARP_BAR)):
        against[name] = (rows.shape[use] & bit > 0).astype(float)
    for name, other in against.items():
        out[name] = _spearman(dur, other)
    return out


def _spearman(a: np.ndarray, b: np.ndarray) -> float:
    """Rank correlation, tie-aware by mid-ranks."""
    if len(a) < 3:
        return 0.0
    ra, rb = _ranks(a), _ranks(b)
    sa, sb = ra.std(), rb.std()
    if sa == 0 or sb == 0:
        return 0.0
    return float(((ra - ra.mean()) * (rb - rb.mean())).mean() / (sa * sb))


def _ranks(x: np.ndarray) -> np.ndarray:
    order = np.argsort(x, kind="mergesort")
    sorted_x = x[order]
    starts = np.ones(len(x), dtype=bool)
    starts[1:] = sorted_x[1:] != sorted_x[:-1]
    group = np.cumsum(starts) - 1
    first = np.flatnonzero(starts)
    last = np.append(first[1:], len(x)) - 1
    out = np.empty(len(x), dtype=float)
    out[order] = 0.5 * (first[group] + last[group])
    return out


def as_json(got: Survival | None) -> dict | None:
    if got is None:
        return None
    return {
        "n": got.n,
        "censored": got.censored,
        "median": got.median,
        "exponent": got.exponent,
        "exponent_se": got.exponent_se,
        "z_vs_theory": got.z_vs_theory,
        "rate": got.rate,
        "power_resid": got.power_resid,
        "exp_resid": got.exp_resid,
        "power_better": got.power_better,
        "tail": got.tail,
        "at": {str(k): v for k, v in got.at.items()},
    }


def split_as_json(got: Split | None) -> dict | None:
    if got is None:
        return None
    return {
        "n_high": got.n_high,
        "n_low": got.n_low,
        "median_high": got.median_high,
        "median_low": got.median_low,
        "exponent_high": got.exponent_high,
        "exponent_low": got.exponent_low,
        "diff": got.diff,
        "se": got.se,
        "t": got.t,
    }
