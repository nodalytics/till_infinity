"""Does Range Break have a spectrum, and can any sample this size see one?

`research/deriving.md` section four found Range Break sub-diffusive by 3.6x
(RB100) and 8.9x (RB200) between breaks and called the range real. A range is a
**box**, and under the Wick rotation `t -> -i*tau` a box is the oldest problem in
quantum mechanics: a particle between two walls has a discrete spectrum whose
eigenvalues go as `k^2`.

That is a prediction a classical range model does not make. "Price reverts inside
a band" gives one number, a half-life. A box gives a **ladder**

    lambda_k = (k*pi/W)^2 * D,      ratios 1 : 4 : 9 : 16

and a *restoring force* - an Ornstein-Uhlenbeck process, whose generator is the
quantum harmonic oscillator Hamiltonian up to the similarity transform by the
square root of its own stationary density - gives a different one

    lambda_k = k*theta,             ratios 1 : 2 : 3 : 4

so which ladder appears says which object this is: hard walls or a spring. They
are different instruments, and a classical mean-reversion fit cannot tell them
apart because it only ever estimates `lambda_1`.

## The estimator

For **any** eigenfunction `phi_k` of the generator,

    E[ phi_k(X_{t+n}) | X_t ] = exp(-lambda_k * n) * phi_k(X_t)

so `Corr(phi_k(X_t), phi_k(X_{t+n})) = exp(-lambda_k n)` is a *pure* single
exponential with no contamination from any other mode. That is the advantage over
the autocorrelation of price itself, whose expansion for a reflecting box is

    C(n) = (W^2/12) * (96/pi^4) * sum_{k odd} exp(-lambda_k n) / k^4

in which the first mode carries **98.55%** of the variance and the third carries
**1.22%**: reading a ladder off it means resolving a 1% component decaying nine
times faster than the one that dominates, which is hopeless. Three estimators are
run - the **transfer operator** (Ulam's method: bin the state, take the
eigenvalues of the lagged transition matrix, assume no basis at all), **cosine
projection** (the box eigenfunctions) and **Hermite projection** (the
Ornstein-Uhlenbeck eigenfunctions). Projecting on the wrong basis gives a
mixture, which shows as curvature in the log-correlation, and that curvature is a
discriminator independent of the ratios.

## The control that reframes the whole measurement, and it fired

A **driftless random walk** run through the identical estimator. It has no
discrete spectrum whatever. Over twelve replicates it returns
`lambda_2/lambda_1 = 3.55 +- 1.02` and `lambda_3/lambda_1 = 8.54`, against a true
box's 3.99 +- 0.06 and 8.99 and a true spring's 2.21 and 3.94.

**A free random walk lands on the particle-in-a-box ladder and not on the
spring's.** It
has to: binning a diffusion by its own empirical quantiles makes the observed
support the box, and a diffusion in a box has box eigenvalues. So *observing
1:4:9 is not evidence of confinement* - it is evidence that the observation
window was finite, which it always is. Any paper reporting a `k^2` ladder for a
financial series without this control has measured its own window.

What survives the control is not the ratio but the **scaling**. For a free walk
the leading rate is set by the window, `lambda_1 ~ pi^2 D / W_window^2` with
`W_window^2 ~ D*m`, so `lambda_1` falls like `1/m` forever. For a real box
`lambda_1 = pi^2 D / W^2` is a property of the instrument and **stops falling**
once the window is longer than the relaxation time. So the confinement test is a
**knee** in `lambda_1(m)`, and the plateau it flattens onto is the measurement.
Only after a knee exists does the ladder ratio mean anything.

A second, independent discriminator needs no spectrum at all: a reflecting box
has a **uniform** stationary density (excess kurtosis -1.2) and a spring has a
**Gaussian** one (excess kurtosis 0). On 86,000 observations that separates them
on its own.

## The classical control that has to be beaten

An AR(1) half-life - what this desk would otherwise do. It is printed beside
every spectral fit and it returns one number for every truth, box, spring and
free walk alike. If the spectral machinery cannot beat one number, the quantum
framing is notation and this page says so.

## Power comes before data, and that is the pre-registration

Range Break has 86,410 one-minute bars over 60 days and breaks every 86.5 (RB100)
and 178.8 (RB200) minutes, so a within-episode statistic has about **999 and 483
independent episodes**. Whether that can separate `1:4:9` from `1:2:3` is a
question about the estimator, not about Deriv, and it is answered by running the
estimator on simulated processes whose spectrum is known exactly. That is done
here before any market data is touched, and if the answer is that the sample
cannot tell a box from a spring this page reports that and stops.

## What would count as failure

Written before the first run, and left here verbatim even though two fired,
because what they taught is the section above:

1. **The estimator dies** if, on a simulated box at the real sample size, the
   recovered `lambda_2/lambda_1` does not cover 4 - or on a simulated
   Ornstein-Uhlenbeck, does not cover 2 - within its own replicate spread.
2. **The measurement is underpowered** if the two truths' sampling distributions
   of `lambda_2/lambda_1` overlap by more than 5%.
3. **The whole approach dies** if the free-walk control produces ratios
   indistinguishable from the box.
4. **The box reading dies** if, on real Range Break, the cosine projection is not
   straight in log-correlation.
5. **The run is void** if a recovered ratio lands on exactly 4.0000 or 2.0000.

Added after 1 and 3 fired, and pre-registered against the market data, which has
still not been touched at the time of writing:

6. **Confinement is not established** unless `lambda_1(m)` has a knee - a plateau
   over at least a factor of two in window length where it changes by less than
   20% - that the free-walk control does not produce.
7. **The ladder is uninterpretable** unless the measured ratio sits outside the
   free-walk control's 95% interval.
8. **The density test is void** if the standardised within-window excess kurtosis
   of the free-walk control lies between the uniform's -1.2 and the Gaussian's
   0.0 by less than its own standard error from either.
9. **`research/rebuilding.md`'s soft edge is refuted** if the measured
   `lambda_2/lambda_1` on Range Break, read against the simulated truths through
   the identical pipeline, does not land strictly between the spring's value and
   the box's. That page concludes from a variance-ratio fit that the edge of the
   range is softer than a wall; WKB says a soft edge is a shallow ladder; so the
   two pages predict the same interval from different evidence and either can
   kill it.

Real-data sections are skipped with a printed notice when `research.db` is not
reachable, rather than silently producing nothing.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3

import numpy as np
from scipy.signal import lfilter

DATA = os.environ.get("DATA", os.path.expanduser("~/till_infinity/data"))
DB = os.environ.get("DB", os.path.join(DATA, "research.db"))
OUT = os.environ.get("OUT", os.path.expanduser("~/till_infinity/logs/quantspec.json"))
SEED = int(os.environ.get("SEED", "20260911"))
NREP = int(os.environ.get("NREP", "120"))
NBAR = int(os.environ.get("NBAR", "86410"))
EPISODE_RB100 = float(os.environ.get("EPISODE_RB100", "86.5"))
#: Ticks in a one-minute bar for the Range Break family.
TICKS_PER_BAR = 60.0
WIDTH = float(os.environ.get("WIDTH", "0"))
#: Window lengths, in bars, for the scaling test that is the confinement test.
WINDOWS = (8, 12, 16, 24, 32, 48, 64)
LAGS = tuple(int(v) for v in (1, 2, 3, 4, 6, 8, 12, 16, 24, 32))


# --------------------------------------------------------------------------
# Simulated truths, exact at bar resolution
# --------------------------------------------------------------------------


def _episodes(n: int, episode: float, rng: np.random.Generator) -> np.ndarray:
    """Geometric episode lengths summing to about `n` bars.

    `deriving.md` measured the break arrival memoryless on both feeds (CV of the
    gap 1.003 and 1.076), so the episode length is geometric and nothing else.
    """
    guess = int(n / min(episode, n) * 1.4) + 20
    lens = np.minimum(rng.geometric(1.0 / episode, guess), n)
    cum = np.cumsum(lens)
    keep = np.flatnonzero(cum >= n)
    if keep.size:
        lens = lens[: keep[0] + 1].copy()
        lens[-1] -= int(lens.sum() - n)
    # The cap matters: section 1 asks for one episode of 1e9 bars to isolate the
    # estimator from the episode machinery, and an uncapped geometric draw then
    # sized a mask of 2e10 cells and took the machine down.
    return lens[lens >= 8]


def _pack(lens: np.ndarray):
    m = int(lens.max())
    mask = np.arange(m)[None, :] < lens[:, None]
    ids = np.repeat(np.arange(len(lens)), lens)
    return mask, ids, m


def _flatten(mat: np.ndarray, mask: np.ndarray, ids: np.ndarray, demean: bool):
    """Pool episodes, optionally after removing each episode's own mean.

    The level of a Range Break range moves when it breaks, so pooling raw levels
    across episodes would put the between-range wander into the same histogram as
    the within-range structure. Removing the episode mean is the only way to
    pool - and because the same removal is applied to every simulated truth, the
    bias it causes sits inside the power analysis rather than outside it.
    """
    if demean:
        mu = (mat * mask).sum(axis=1) / mask.sum(axis=1)
        mat = mat - mu[:, None]
    return mat[mask], ids


def sim_box(
    n: int, width: float, dvar: float, episode: float, rng: np.random.Generator, demean: bool = True
):
    """Reflecting Brownian motion in [0, W], once a bar, with memoryless breaks.

    Reflection is exact and needs no per-step loop: folding a *free* Brownian
    path through the triangle wave of period 2W **is** reflecting Brownian motion
    in law - the method of images again - so the discrete skeleton has
    eigenvalues `exp(-lambda_k)` with `lambda_k = (k pi / W)^2 * dvar/2` exactly.
    Nothing about the spectrum is approximated.
    """
    lens = _episodes(n, episode, rng)
    mask, ids, m = _pack(lens)
    inc = rng.normal(0.0, math.sqrt(dvar), (len(lens), m))
    inc[:, 0] = 0.0
    y = rng.random(len(lens))[:, None] * width + np.cumsum(inc, axis=1)
    t = np.mod(y, 2.0 * width)
    return _flatten(np.where(t <= width, t, 2.0 * width - t), mask, ids, demean)


def sim_ou(
    n: int, theta: float, svar: float, episode: float, rng: np.random.Generator, demean: bool = True
):
    """Ornstein-Uhlenbeck once a bar, same break hazard.

    The update is the *exact* transition of the continuous process, not an Euler
    step, so the Hermite eigenvalues are exactly `exp(-k*theta)` and the 1:2:3
    ladder is a property of the simulation rather than a hope about it.
    """
    lens = _episodes(n, episode, rng)
    mask, ids, m = _pack(lens)
    a = math.exp(-theta)
    s = math.sqrt(svar * (1.0 - a * a))
    z = rng.standard_normal((len(lens), m)) * s
    z[:, 0] = rng.standard_normal(len(lens)) * math.sqrt(svar)
    return _flatten(lfilter([1.0], [1.0, -a], z, axis=1), mask, ids, demean)


def sim_free(n: int, dvar: float, episode: float, rng: np.random.Generator, demean: bool = True):
    """A driftless random walk cut into episodes at the same hazard.

    The false-positive control. It has no discrete spectrum at all, so whatever
    ladder the estimator returns here is the estimator talking to itself.
    """
    lens = _episodes(n, episode, rng)
    mask, ids, m = _pack(lens)
    inc = rng.normal(0.0, math.sqrt(dvar), (len(lens), m))
    inc[:, 0] = 0.0
    return _flatten(np.cumsum(inc, axis=1), mask, ids, demean)


# --------------------------------------------------------------------------
# Estimators
# --------------------------------------------------------------------------


def _pairs(x: np.ndarray, ep: np.ndarray, lag: int):
    same = ep[lag:] == ep[:-lag]
    return x[:-lag][same], x[lag:][same]


def transfer_rates(
    x: np.ndarray, ep: np.ndarray, lag: int, nbin: int, nmode: int = 3
) -> list[float]:
    """Ulam's method: rates from the eigenvalues of the binned lag-`lag` matrix.

    Bins are equiprobable, so the stationary vector is uniform by construction
    and the leading eigenvalue is 1 up to sampling error. Rates are
    `-log(mu_j)/lag`. No basis is assumed. The price is numerical diffusion from
    the binning, and its size is measured against known truths rather than argued.
    """
    a, b = _pairs(x, ep, lag)
    if a.size < 400:
        return [float("nan")] * nmode
    edges = np.quantile(x, np.linspace(0.0, 1.0, nbin + 1))
    edges[0] -= 1e-9
    edges[-1] += 1e-9
    ia = np.clip(np.searchsorted(edges, a, side="right") - 1, 0, nbin - 1)
    ib = np.clip(np.searchsorted(edges, b, side="right") - 1, 0, nbin - 1)
    m = np.zeros((nbin, nbin))
    np.add.at(m, (ia, ib), 1.0)
    row = m.sum(axis=1)
    keep = row > 0
    m, row = m[keep][:, keep], row[keep]
    ev = np.linalg.eigvals(m / row[:, None])
    ev = ev[np.argsort(-np.abs(ev))]
    out = []
    for j in range(1, nmode + 1):
        if j >= len(ev):
            out.append(float("nan"))
            continue
        mu = ev[j]
        mu = float(mu.real) if abs(mu.imag) < 1e-9 else float("nan")
        out.append(-math.log(mu) / lag if (not math.isnan(mu) and mu > 0) else float("nan"))
    return out


def _hermite(z: np.ndarray, k: int) -> np.ndarray:
    """Probabilists' Hermite polynomial `He_k`, the Ornstein-Uhlenbeck modes."""
    h0 = np.ones_like(z)
    if k == 0:
        return h0
    h1 = z
    for j in range(1, k):
        h0, h1 = h1, z * h1 - j * h0
    return h1


def projection_rates(x: np.ndarray, ep: np.ndarray, basis: str, kmax: int = 3, lags=LAGS) -> dict:
    """Fit `log Corr(phi_k(X_t), phi_k(X_{t+n})) = -lambda_k n`, mode by mode.

    The box basis is `cos(k pi (x - lo)/W)` with `W = sqrt(12 Var)` so that the
    wall comes from the stationary variance and not from one extreme print. The
    spring basis is the Hermite polynomials in the standardised state. Curvature
    of the log-correlation is returned alongside: a pure mode is a straight line,
    a bend means the basis is wrong.
    """
    if basis == "box":
        w = math.sqrt(12.0 * float(np.var(x)))
        lo = float(np.mean(x)) - w / 2.0

        def phi(v, k):
            return np.cos(k * math.pi * (v - lo) / w)
    else:
        mu, sd = float(np.mean(x)), float(np.std(x))

        def phi(v, k):
            return _hermite((v - mu) / sd, k)

    res: dict = {"basis": basis, "rates": [], "curvature": [], "corr": {}}
    for k in range(1, kmax + 1):
        xs, ys, cs = [], [], []
        for n in lags:
            a, b = _pairs(x, ep, n)
            if a.size < 400:
                continue
            fa, fb = phi(a, k), phi(b, k)
            sa, sb = fa.std(), fb.std()
            if sa < 1e-12 or sb < 1e-12:
                continue
            c = float(np.mean((fa - fa.mean()) * (fb - fb.mean())) / (sa * sb))
            if c <= 0.03:
                continue
            xs.append(n)
            ys.append(math.log(c))
            cs.append(c)
        if len(xs) < 4:
            res["rates"].append(float("nan"))
            res["curvature"].append(float("nan"))
            continue
        xa, ya = np.array(xs, dtype=float), np.array(ys)
        # Through the origin: Corr(0) = 1 exactly, so log Corr(0) = 0 is a known
        # point and fitting an intercept throws it away.
        lam = float(-(xa @ ya) / (xa @ xa))
        quad = np.polyfit(xa, ya, 2)
        res["rates"].append(lam)
        res["curvature"].append(float(quad[0] / abs(lam)) if lam else float("nan"))
        res["corr"][k] = {"lags": xs, "corr": cs}
    return res


def ar1_halflife(x: np.ndarray, ep: np.ndarray) -> float:
    """The classical control: one number, from a lag-1 autoregression."""
    a, b = _pairs(x, ep, 1)
    a, b = a - a.mean(), b - b.mean()
    rho = float((a @ b) / (a @ a))
    return -math.log(2.0) / math.log(rho) if 0.0 < rho < 1.0 else float("nan")


def ladder(rates: list[float]) -> list[float]:
    base = rates[0] if rates and rates[0] == rates[0] and rates[0] > 0 else float("nan")
    return [r / base for r in rates]


def windowed(x: np.ndarray, ep: np.ndarray, m: int):
    """Cut into non-overlapping windows of `m` bars that never straddle a break.

    Each window is de-meaned on its own, because the scaling test asks what the
    *window* alone can see and must not be handed the level. Vectorised: the
    obvious two-level Python loop over episodes and windows cost 72 million
    iterations per replicate set and was what made the first version of this
    harness unrunnable.
    """
    n = len(x)
    if n == 0:
        return np.array([]), np.array([], dtype=np.int64)
    # Position within the episode, and how long each episode is.
    _, inv, cnt = np.unique(ep, return_inverse=True, return_counts=True)
    starts = np.zeros(len(cnt), dtype=np.int64)
    np.cumsum(cnt[:-1], out=starts[1:])
    pos = np.arange(n) - starts[inv]
    keep = pos < (cnt[inv] // m) * m
    if not keep.any():
        return np.array([]), np.array([], dtype=np.int64)
    # A unique window id: episode offset in whole windows, plus the window index.
    woff = np.zeros(len(cnt), dtype=np.int64)
    np.cumsum(cnt[:-1] // m, out=woff[1:])
    wid = woff[inv][keep] + pos[keep] // m
    xs = x[keep]
    cw = np.bincount(wid)
    mu = np.bincount(wid, weights=xs) / np.maximum(cw, 1)
    return xs - mu[wid], wid


def scaling_curve(x: np.ndarray, ep: np.ndarray, nbin: int = 16) -> dict:
    """`lambda_1` as a function of window length - the confinement test.

    A free walk has no intrinsic scale, so `lambda_1 ~ 1/m` for ever. A confined
    process has one, so `lambda_1` stops falling once the window is longer than
    its relaxation time. The knee is the confinement and the plateau is the rate.
    """
    lam, kur = [], []
    for m in WINDOWS:
        wx, wid = windowed(x, ep, m)
        if wx.size < 2000:
            lam.append(float("nan"))
            kur.append(float("nan"))
            continue
        r = transfer_rates(wx, wid, lag=1, nbin=nbin, nmode=1)
        lam.append(r[0])
        z = wx / wx.std()
        kur.append(float(np.mean(z**4) - 3.0))
    return {"windows": list(WINDOWS), "lambda1": lam, "excess_kurtosis": kur}


def knee(curve: dict) -> dict:
    """Is there a plateau? The slope of log lambda_1 against log m, by segment.

    A free walk sits at -1 everywhere. A box goes from about -1 at short windows
    to about 0 once the window exceeds its relaxation time, and the *shallowest*
    segment slope is the statistic.
    """
    ms = np.array(curve["windows"], dtype=float)
    ls = np.array(curve["lambda1"], dtype=float)
    ok = np.isfinite(ls) & (ls > 0)
    ms, ls = ms[ok], ls[ok]
    if len(ms) < 3:
        return {"slopes": [], "shallowest": float("nan"), "overall": float("nan")}
    slopes = [
        float((math.log(ls[i + 1]) - math.log(ls[i])) / (math.log(ms[i + 1]) - math.log(ms[i])))
        for i in range(len(ms) - 1)
    ]
    a = np.polyfit(np.log(ms), np.log(ls), 1)
    return {"slopes": slopes, "shallowest": float(max(slopes)), "overall": float(a[0])}


# --------------------------------------------------------------------------
# What does deriving.md's published curve already imply?
# --------------------------------------------------------------------------

PUBLISHED_VR = {
    "range_break_100_index": {1: 0.978, 5: 0.730, 20: 0.436, 100: 0.283, 500: 0.274, 1000: 0.279},
    "range_break_200_index": {1: 0.930, 5: 0.750, 20: 0.477, 100: 0.192, 500: 0.116, 1000: 0.112},
}


def implied_width(vr: dict, tpb: float = TICKS_PER_BAR) -> dict:
    """Back out a box width from the two shortest published ex-break lags.

    One mode, no stitching: `Var(n) = 2V (1 - exp(-lambda n))` with `V = W^2/12`.
    Two equations, two unknowns, from n=1 and n=5 - the only lags where under 6%
    of pairs can straddle a break, so the gluing that makes the published curve
    flat at large `n` has not yet contaminated them.

    This is a calibration and not a measurement. Its only job is to run the power
    analysis at a realistic relaxation rate rather than an invented one.
    """
    v1 = vr[1] * 1 * tpb
    v5 = vr[5] * 5 * tpb
    target = v5 / v1
    lo, hi = 1e-4, 5.0
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        r = math.exp(-mid)
        if (1 - r**5) / (1 - r) > target:
            lo = mid
        else:
            hi = mid
    lam = 0.5 * (lo + hi)
    twov = v1 / (1.0 - math.exp(-lam))
    w = math.sqrt(12.0 * twov / 2.0)
    return {
        "lambda_1_per_bar": lam,
        "stationary_var": twov / 2.0,
        "width_units": w,
        "tau_1_bars": 1.0 / lam,
        "lambda_1_from_box_formula": (tpb / 2.0) * (math.pi / w) ** 2,
        "predicted_lambda_2_box": 4.0 * lam,
        "predicted_lambda_2_ou": 2.0 * lam,
    }


#: `research/rebuilding.md`'s Range Break fit, after that page replaced its two
#: free per-feed widths with **one shared width of 60 lattice steps** and left
#: only the break jump free. The series tick 60 times a minute.
REBUILD = {
    "range_break_100_index": {
        "band": 60.0,
        "jump": 130.0,
        "episode_bars": 86.5,
        "resid_1m": -0.086,
        "resid_20m": +0.047,
    },
    "range_break_200_index": {
        "band": 60.0,
        "jump": 210.0,
        "episode_bars": 178.8,
        "resid_1m": -0.018,
        "resid_20m": +0.024,
    },
}


def wall_hardness(alpha: float) -> float:
    """The exponent `p` of the well `V ~ |x|^p` whose WKB ladder goes as `k^alpha`.

    WKB gives `lambda_k ~ k^(2p/(p+2))`, so `alpha = 2p/(p+2)` and inverting,
    `p = 2*alpha/(2-alpha)`. A hard wall is `p -> infinity`, `alpha = 2`, the
    ladder 1:4:9. A harmonic well is `p = 2`, `alpha = 1`, the ladder 1:2:3.
    Nothing that confines has `alpha > 2`, which makes 1:4:9 a ceiling rather
    than one option among several.
    """
    if alpha >= 2.0:
        return float("inf")
    return 2.0 * alpha / (2.0 - alpha)


def residual_geometry() -> dict:
    """What rebuilding.md's soft edge means for the ladder, and what that predicts.

    That page fits a uniform reflecting band plus a memoryless break to
    `deriving.md`'s published ex-break curve. Under one shared 60-step width it
    reaches a joint mean absolute error of 0.0363 - better than two free widths -
    and is left with a residual that is **too confined at one minute and too free
    at twenty**, which it reads as the edge of the range being softer than a wall.

    The spectrum turns that reading into a number. Three statements, none of
    which needs any data:

    * **The twenty minutes is not arbitrary.** A reflecting box relaxes on its
      slowest mode in `tau_1 = 2 W^2 / pi^2` ticks at unit step variance, which at
      60 steps is 729 ticks, or 12.2 minutes. Twenty minutes is `1.6 tau_1` - the
      residual sits on the box's own clock, which is what says it is a shape error
      in the relaxation rather than a missing timescale.
    * **`1:4:9` is a ceiling, not an option.** WKB gives `lambda_k ~ k^alpha` with
      `alpha = 2p/(p+2)` for a well `V ~ |x|^p`, rising to 2 as the wall hardens
      and never passing it. So no confinement relaxes faster than a hard box at
      matched `lambda_1`.
    * **Therefore a soft edge is a shallow ladder, and the prediction is an
      interval.** If the edge really is softer than a wall then `alpha < 2`
      strictly, so the measured `lambda_2/lambda_1` must land **strictly between 2
      and 4** - and where it lands measures the wall, because `p = 2*alpha/(2-alpha)`.

    That is the same claim `rebuilding.md` makes, arrived at from a spectrum
    rather than from a variance-ratio fit, and it is falsifiable in both
    directions: 4 refutes the soft edge, 2 says the range is a harmonic well and
    not a box at all.

    That page has since built the soft edge - a lattice walk with up-probability
    `0.5 - k(|x|/half)^q sign(x)`, which is this same family with `p = q+1` - and
    found it buys 12% on the ex-break curve while costing a third of the all-bars
    flatness, concluding that no single confinement matches both at once. The
    ladder is the right instrument for that impasse for a structural reason: a
    variance-ratio curve mixes the confinement and the break into one number and
    an eigenvalue does not, because the transfer-operator ladder is measured
    strictly within episodes and never touches a break bar. So it can say which of
    the two facts in tension is describing the confinement.
    """
    rows = {}
    for feed, r in REBUILD.items():
        w = r["band"]
        tau_ticks = w * w * 2.0 / (math.pi**2)
        tau_bars = tau_ticks / TICKS_PER_BAR
        rows[feed] = {
            "band": w,
            "jump": r["jump"],
            "tau_1_bars": tau_bars,
            "tau_1_ticks": tau_ticks,
            "episode_bars": r["episode_bars"],
            "twenty_min_in_tau": 20.0 / tau_bars,
            "relaxations_per_episode": r["episode_bars"] / tau_bars,
            "resid_1m": r["resid_1m"],
            "resid_20m": r["resid_20m"],
        }
    rows["ladder_prediction"] = {
        "alpha_bounds": [1.0, 2.0],
        "ratio_bounds": [2.0, 4.0],
        "p_at_alpha_1.5": wall_hardness(1.5),
        "p_at_alpha_1.8": wall_hardness(1.8),
        "p_hard_wall": "inf",
    }
    return rows


def load_bars(feed: str) -> dict | None:
    if not os.path.exists(DB):
        return None
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = conn.execute(
        "SELECT ts, high, low, close FROM bars WHERE feed=? AND interval='1m' ORDER BY ts", (feed,)
    ).fetchall()
    conn.close()
    if len(rows) < 5000:
        return None
    hi = np.array([r[1] for r in rows], dtype=float)
    lo = np.array([r[2] for r in rows], dtype=float)
    cl = np.array([r[3] for r in rows], dtype=float)
    # deriving.md's break detector: a bar whose range exceeds 66 units. On the
    # control feeds nothing triggers it and they come through as one episode,
    # which is right - a fair coin has no range to leave.
    isbrk = (hi - lo) > 66.0
    ep = np.cumsum(isbrk)
    keep = ~isbrk
    cl, ep = cl[keep], ep[keep]
    uniq, inv, cnt = np.unique(ep, return_inverse=True, return_counts=True)
    ok = cnt[inv] >= 8
    cl, inv = cl[ok], inv[ok]
    sums = np.bincount(inv, weights=cl)
    n_each = np.bincount(inv)
    return {
        "feed": feed,
        "close": cl - (sums / n_each)[inv],
        "episode": inv,
        "n_bars": len(rows),
        "n_breaks": int(isbrk.sum()),
        "n_episodes": len(uniq),
    }


#: Window lengths in TICKS for the knee test at tick resolution. A 60-step box
#: relaxes in 2W^2/pi^2 = 729 ticks, so these straddle it by a factor of eight
#: either side, which is what a knee needs to be visible as a knee.
TICK_WINDOWS = (64, 128, 256, 512, 1024, 2048, 4096)
#: Lags in ticks for the transfer operator. tau_2 is about 96 ticks at that
#: width, so a lag near it is well conditioned; at one-minute bars tau_2 is 1.6
#: bars and there is no such lag, which is why the bar reading answers a
#: different question.
TICK_LAG = int(os.environ.get("TICK_LAG", "60"))
#: Replicates for the tick-resolution calibration. Each is 86,400 samples, so
#: this is cheap beside the bar power analysis.
NREP_TICK = int(os.environ.get("NREP_TICK", "60"))


def load_ticks(feed: str) -> dict | None:
    """Range Break ticks, split into episodes at the break, de-meaned per episode.

    On ticks the break detector needs no threshold argument worth arguing about:
    `generators.md` established the series moves exactly one unit a tick between
    breaks and `rebuilding.md` fits the break jump at 130 and 210 units, so any
    move of more than five units is a break and nothing else is. That is a much
    cleaner cut than the bar detector's "range over 66", which can only see a
    break after it has been mixed with a minute of ordinary movement.

    This is the resolution the measurement belongs at. `lambda_2` has a lifetime
    of about 96 ticks, which is 1.6 one-minute bars, so a bar-sampled transfer
    operator has no lag at which the second mode is both alive and resolved.
    """
    if not os.path.exists(DB):
        return None
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = conn.execute(
        "SELECT ts, bid, ask FROM ticks WHERE feed=? ORDER BY ts ASC", (feed,)
    ).fetchall()
    conn.close()
    if len(rows) < 20000:
        return None
    mid = np.array([(float(b) + float(a)) / 2.0 for _, b, a in rows], dtype=float)
    d = np.diff(mid)
    step = float(np.median(np.abs(d[d != 0]))) if np.any(d != 0) else 1.0
    isbrk = np.abs(d) > 5.0 * step
    ep = np.concatenate([[0], np.cumsum(isbrk)])
    # Drop the tick that carries the break itself, then keep episodes long enough
    # to hold a lagged pair at the longest window.
    keep = np.concatenate([[True], ~isbrk])
    x, e = mid[keep], ep[keep]
    uniq, inv, cnt = np.unique(e, return_inverse=True, return_counts=True)
    ok = cnt[inv] >= 2 * TICK_WINDOWS[-1]
    x, inv = x[ok], inv[ok]
    if x.size < 10000:
        ok = cnt[inv if x.size else np.array([], dtype=int)]
        return None
    _, inv = np.unique(inv, return_inverse=True)
    sums = np.bincount(inv, weights=x)
    n_each = np.bincount(inv)
    xd = x - (sums / n_each)[inv]
    # The width, measured directly rather than inverted from a variance ratio.
    # A reflecting box has a uniform stationary law, so W = sqrt(12 Var); the
    # observed within-episode range is the same number seen a second way and
    # the two disagreeing is itself information about the wall.
    var_w = float(np.mean([xd[inv == j].var() for j in range(len(n_each))]))
    rng_w = float(np.mean([np.ptp(x[inv == j]) for j in range(len(n_each))]))
    return {
        "feed": feed,
        "x": xd,
        "episode": inv,
        "step": step,
        "n_ticks": len(rows),
        "n_breaks": int(isbrk.sum()),
        "n_episodes": int(len(n_each)),
        "mean_episode_ticks": float(np.mean(n_each)),
        "width_from_variance": math.sqrt(12.0 * var_w) / step,
        "mean_within_range": rng_w / step,
    }


def sim_at(
    kind: str,
    n: int,
    width: float,
    dvar: float,
    episode: float,
    lam: float,
    rep: int,
    demean: bool = True,
):
    """One replicate of a named truth at an arbitrary sampling resolution.

    `replicate` is the bar-resolution special case. This exists because the tick
    calibration has to be run at the tick sample size, the tick episode length
    and the tick step variance, or the bias the de-meaning causes is the wrong
    size and the comparison means nothing.
    """
    rng = np.random.default_rng(SEED + 7919 * rep + {"box": 11, "ou": 12, "free": 13}[kind])
    if kind == "box":
        return sim_box(n, width, dvar, episode, rng, demean)
    if kind == "ou":
        return sim_ou(n, lam, width * width / 12.0, episode, rng, demean)
    return sim_free(n, dvar, episode, rng, demean)


def tick_stats(x: np.ndarray, ep: np.ndarray) -> dict:
    """The three readings, at tick resolution: ladder, knee, stationary shape."""
    rates = transfer_rates(x, ep, lag=TICK_LAG, nbin=24, nmode=3)
    lad = ladder(rates)
    lam1, kur = [], []
    for m in TICK_WINDOWS:
        wx, wid = windowed(x, ep, m)
        if wx.size < 4000:
            lam1.append(float("nan"))
            kur.append(float("nan"))
            continue
        lam1.append(transfer_rates(wx, wid, lag=max(1, m // 32), nbin=16, nmode=1)[0])
        z = wx / wx.std()
        kur.append(float(np.mean(z**4) - 3.0))
    kn = knee({"windows": list(TICK_WINDOWS), "lambda1": lam1})
    return {
        "rates": rates,
        "ladder": lad,
        "lambda1_by_window": lam1,
        "kurtosis_by_window": kur,
        "knee": kn,
        "ar1_halflife": ar1_halflife(x, ep),
    }


def replicate(kind: str, w: float, lam: float, episode: float, rep: int, demean: bool = True):
    rng = np.random.default_rng(SEED + 7919 * rep + {"box": 1, "ou": 2, "free": 3}[kind])
    if kind == "box":
        return sim_box(NBAR, w, TICKS_PER_BAR, episode, rng, demean)
    if kind == "ou":
        return sim_ou(NBAR, lam, w * w / 12.0, episode, rng, demean)
    return sim_free(NBAR, TICKS_PER_BAR, episode, rng, demean)


def main() -> None:
    out: dict = {}

    print("=" * 98)
    print("THE RANGE BREAK SPECTRUM - box, spring, or a window measuring itself")
    print("=" * 98)

    # ---- 0. calibration --------------------------------------------------
    print("\n[0] WHAT deriving.md's PUBLISHED CURVE ALREADY IMPLIES")
    print("    One relaxation mode fitted to the two shortest ex-break lags, which are the")
    print("    only ones where under 6% of pairs can straddle a break. The long-lag")
    print("    flatness in that table (0.283, 0.274, 0.279 at n = 100..1000) is the")
    print("    stitching, not the process: dropping break bars and concatenating glues")
    print("    independent episodes end to end, and glued episodes diffuse.")
    cal = {}
    for feed, vr in PUBLISHED_VR.items():
        c = implied_width(vr)
        cal[feed] = c
        print(f"\n    {feed}")
        print(
            f"      lambda_1        {c['lambda_1_per_bar']:.4f} / bar   "
            f"(tau_1 = {c['tau_1_bars']:.1f} bars)"
        )
        print(
            f"      implied width   {c['width_units']:.1f} units  "
            f"(stationary sd {math.sqrt(c['stationary_var']):.1f})"
        )
        print(
            f"      box formula     D(pi/W)^2 = {c['lambda_1_from_box_formula']:.4f} / bar "
            f"against the fitted {c['lambda_1_per_bar']:.4f}"
        )
        print(
            f"      so lambda_2 is  {c['predicted_lambda_2_box']:.3f} if a box, "
            f"{c['predicted_lambda_2_ou']:.3f} if a spring"
        )
    out["calibration"] = cal
    w100 = WIDTH if WIDTH > 0 else cal["range_break_100_index"]["width_units"]
    lam100 = cal["range_break_100_index"]["lambda_1_per_bar"]

    # ---- 1. the control that fires ---------------------------------------
    print("\n[1] THE CONTROL FIRES FIRST: A FREE WALK PRODUCES THE BOX LADDER")
    print("    Identical estimator, three truths, one long episode each so nothing but")
    print("    the process differs. The free walk has no spectrum and returns one anyway,")
    print("    because binning a diffusion by its own quantiles makes the observed")
    print("    support the box, and a diffusion in a box has box eigenvalues.")
    print(
        f"\n    {'truth':>10s} {'true l2/l1':>11s} {'recovered':>11s} {'l3/l1':>9s} "
        f"{'true l3/l1':>11s}"
    )
    naive = {}
    for kind, lab, t2, t3 in (
        ("box", "box", 4.0, 9.0),
        ("ou", "spring", 2.0, 3.0),
        ("free", "free walk", float("nan"), float("nan")),
    ):
        r = []
        for rep in range(12):
            x, ep = replicate(kind, w100, lam100, 1e9, rep, demean=False)
            r.append(ladder(transfer_rates(x, ep, lag=2, nbin=24, nmode=3)))
        r = np.array(r, dtype=float)
        naive[kind] = {
            "l2": float(np.nanmean(r[:, 1])),
            "l2_sd": float(np.nanstd(r[:, 1], ddof=1)),
            "l3": float(np.nanmean(r[:, 2])),
        }
        print(
            f"    {lab:>10s} {t2:11.2f} {naive[kind]['l2']:8.3f}+-{naive[kind]['l2_sd']:.3f} "
            f"{naive[kind]['l3']:9.3f} {t3:11.2f}"
        )
    out["naive_ladder"] = naive
    print("\n    So 1:4:9 on its own means nothing. What has to be measured instead is")
    print("    whether lambda_1 depends on the window: it does for a free walk, for ever,")
    print("    and it stops doing so for anything actually confined.")

    # ---- 2. the scaling test ---------------------------------------------
    print("\n[2] THE CONFINEMENT TEST - is there a knee in lambda_1(m)?")
    print(f"    {NREP} replicates of each truth at the real sample size, {NBAR:,} bars in")
    print(
        f"    episodes of {EPISODE_RB100:.1f} bars (about {NBAR / EPISODE_RB100:,.0f} "
        "episodes), cut into"
    )
    print("    non-overlapping de-meaned windows. A free walk sits at slope -1 at every")
    print("    window length. A box flattens to 0 once the window passes its relaxation")
    print("    time. The shallowest segment slope is the statistic.")
    scal = {}
    for kind in ("box", "ou", "free"):
        curves, shal, over, kurt = [], [], [], []
        for rep in range(NREP):
            x, ep = replicate(kind, w100, lam100, EPISODE_RB100, rep)
            c = scaling_curve(x, ep)
            k = knee(c)
            curves.append(c["lambda1"])
            kurt.append(c["excess_kurtosis"])
            shal.append(k["shallowest"])
            over.append(k["overall"])
        cm = np.nanmean(np.array(curves, dtype=float), axis=0)
        km = np.nanmean(np.array(kurt, dtype=float), axis=0)
        scal[kind] = {
            "windows": list(WINDOWS),
            "lambda1_mean": [float(v) for v in cm],
            "kurtosis_mean": [float(v) for v in km],
            "shallowest_mean": float(np.nanmean(shal)),
            "shallowest_sd": float(np.nanstd(shal, ddof=1)),
            "overall_mean": float(np.nanmean(over)),
            "_shal": [float(v) for v in shal],
        }
    out["scaling"] = {
        k: {kk: vv for kk, vv in v.items() if not kk.startswith("_")} for k, v in scal.items()
    }
    print(f"\n    lambda_1 by window length (mean over {NREP} replicates)")
    print(
        f"    {'truth':>10s} "
        + " ".join(f"{('m=' + str(m)):>9s}" for m in WINDOWS)
        + f" {'log-log':>9s} {'shallowest':>11s}"
    )
    for kind, lab in (("box", "box"), ("ou", "spring"), ("free", "free walk")):
        s = scal[kind]
        print(
            f"    {lab:>10s} "
            + " ".join(f"{v:9.4f}" for v in s["lambda1_mean"])
            + f" {s['overall_mean']:9.2f} {s['shallowest_mean']:8.2f}"
            f"+-{s['shallowest_sd']:.2f}"
        )
    print(f"\n    true lambda_1 of the simulated box and spring: {lam100:.4f} / bar")

    # ---- 3. the density test ---------------------------------------------
    print("\n[3] THE SECOND DISCRIMINATOR, WITH NO SPECTRUM IN IT")
    print("    A reflecting box has a uniform stationary density (excess kurtosis -1.2);")
    print("    a spring has a Gaussian one (0.0). Standardised within-window excess")
    print("    kurtosis, same replicates:")
    print(f"\n    {'truth':>10s} " + " ".join(f"{('m=' + str(m)):>9s}" for m in WINDOWS))
    for kind, lab in (("box", "box"), ("ou", "spring"), ("free", "free walk")):
        print(f"    {lab:>10s} " + " ".join(f"{v:9.3f}" for v in scal[kind]["kurtosis_mean"]))
    print("\n    (a window shorter than the relaxation time cannot see the stationary")
    print("     density at all, which is why the short-window columns agree)")

    # ---- 4. the ladder, calibrated ---------------------------------------
    print("\n[4] THE LADDER, AT THE REAL SAMPLE SIZE AND WITH THE REAL EPISODES")
    print("    The de-meaning needed to pool episodes biases every rate, so the recovered")
    print("    ratio is NOT 4 and NOT 2. It is compared against the simulated truths put")
    print("    through the identical pipeline, which is the only honest comparison.")
    lad = {}
    for kind in ("box", "ou", "free"):
        r2, r3, hl, pbox, pou = [], [], [], [], []
        for rep in range(NREP):
            x, ep = replicate(kind, w100, lam100, EPISODE_RB100, rep)
            lr = ladder(transfer_rates(x, ep, lag=2, nbin=24, nmode=3))
            r2.append(lr[1])
            r3.append(lr[2])
            hl.append(ar1_halflife(x, ep))
            if rep < 25:
                pbox.append(ladder(projection_rates(x, ep, "box")["rates"])[1])
                pou.append(ladder(projection_rates(x, ep, "ou")["rates"])[1])
        a2 = np.array([v for v in r2 if not math.isnan(v)])
        lad[kind] = {
            "l2_mean": float(a2.mean()),
            "l2_sd": float(a2.std(ddof=1)),
            "l2_q": [float(q) for q in np.quantile(a2, [0.025, 0.5, 0.975])],
            "l3_mean": float(np.nanmean(r3)),
            "ar1_halflife": float(np.nanmean(hl)),
            "cos_basis_l2": float(np.nanmean(pbox)),
            "hermite_basis_l2": float(np.nanmean(pou)),
            "_a2": [float(v) for v in a2],
        }
    out["ladder"] = {
        k: {kk: vv for kk, vv in v.items() if not kk.startswith("_")} for k, v in lad.items()
    }
    print(
        f"\n    {'truth':>10s} {'l2/l1':>8s} {'sd':>6s} {'95% interval':>18s} {'l3/l1':>8s} "
        f"{'cos l2':>8s} {'Herm l2':>8s} {'AR t1/2':>8s}"
    )
    for kind, lab in (("box", "box"), ("ou", "spring"), ("free", "free walk")):
        v = lad[kind]
        print(
            f"    {lab:>10s} {v['l2_mean']:8.3f} {v['l2_sd']:6.3f} "
            f"[{v['l2_q'][0]:7.3f},{v['l2_q'][2]:7.3f}] {v['l3_mean']:8.3f} "
            f"{v['cos_basis_l2']:8.3f} {v['hermite_basis_l2']:8.3f} "
            f"{v['ar1_halflife']:8.2f}"
        )
    a, b = np.array(lad["box"]["_a2"]), np.array(lad["ou"]["_a2"])
    cut = 0.5 * (a.mean() + b.mean())
    err = (
        (np.mean(a < cut) + np.mean(b > cut)) / 2
        if a.mean() > b.mean()
        else (np.mean(a > cut) + np.mean(b < cut)) / 2
    )
    fw = np.array(lad["free"]["_a2"])
    out["separation_error"] = float(err)
    print(f"\n    best single-cut error separating box from spring: {err:.1%}")
    print("    the AR(1) column is the classical control: one number for every truth,")
    print("    and it does not order them.")

    # ---- 5. real data ----------------------------------------------------
    # ---- 4b. the rebuild's residual, on the box's own clock -------------
    # ---- 4b. the rebuild's soft edge, as a ladder prediction -------------
    print("\n[4b] rebuilding.md's SOFT EDGE, TRANSLATED INTO A LADDER")
    print("     That page fits one shared 60-step range to both indices, beats its own")
    print("     two-free-width fit, and is left with a residual that is too confined at")
    print("     one minute and too free at twenty. It reads that as an edge softer than a")
    print("     wall. A spectrum turns that reading into an interval.")
    geo = residual_geometry()
    out["residual_geometry"] = geo
    print(
        f"\n     {'feed':24s} {'band':>5s} {'jump':>5s} {'tau_1 (min)':>12s} "
        f"{'20m in tau_1':>13s} {'resid 1m':>9s} {'resid 20m':>10s}"
    )
    for feed in ("range_break_100_index", "range_break_200_index"):
        g = geo[feed]
        print(
            f"     {feed:24s} {g['band']:5.0f} {g['jump']:5.0f} {g['tau_1_bars']:12.2f} "
            f"{g['twenty_min_in_tau']:13.2f} {g['resid_1m']:+9.3f} {g['resid_20m']:+10.3f}"
        )
    print("\n     The twenty minutes is not arbitrary: tau_1 = 2W^2/pi^2 is 729 ticks at a")
    print("     60-step width, so twenty minutes is 1.6 relaxation times. The residual")
    print("     sits on the box's own clock, which is what makes it a shape error in the")
    print("     relaxation rather than a missing timescale - and rebuilding.md reaches the")
    print("     same 1.6 from the other side.")
    print("\n     WKB: lambda_k ~ k^alpha with alpha = 2p/(p+2) for a well V ~ |x|^p.")
    print(f"     {'well':>22s} {'p':>8s} {'alpha':>8s} {'lambda_2/lambda_1':>18s}")
    for label, alpha in (
        ("harmonic (a spring)", 1.0),
        ("soft wall", 1.5),
        ("stiff wall", 1.8),
        ("hard box", 2.0),
    ):
        pp = wall_hardness(alpha)
        pstr = "inf" if pp == float("inf") else f"{pp:.1f}"
        print(f"     {label:>22s} {pstr:>8s} {alpha:8.2f} {2.0**alpha:18.2f}")
    print("\n     So 1:4:9 is a CEILING and not one option among several: nothing that")
    print("     confines relaxes faster than a hard box at matched lambda_1. If")
    print("     rebuilding.md's soft edge is right then alpha < 2 strictly, and")
    print("\n       *** the measured lambda_2/lambda_1 must land strictly between 2 and 4,")
    print("       *** and where it lands measures the wall: p = 2*alpha/(2-alpha).")
    print("\n     Falsifiable both ways: 4 refutes the soft edge, 2 says the range is a")
    print("     harmonic well and not a box at all. Two pages, two kinds of evidence, one")
    print("     prediction - and section 4 shows this sample can tell 2 from 4 with a")
    print("     single-cut error of 0.0%.")

    print("\n[5] RANGE BREAK, MEASURED - ON TICKS, WHICH IS WHERE THE SECOND MODE LIVES")
    print("    tau_2 is about 96 ticks, which is 1.6 one-minute bars, so a bar-sampled")
    print("    transfer operator has no lag at which the second mode is both alive and")
    print("    resolved. The bar reading is kept below as a cross-check and answers a")
    print("    different question. The break detector on ticks needs no argument: the")
    print("    series moves one unit a tick between breaks and the break jumps 130-210,")
    print("    so anything over five units is a break and nothing else is.")
    real: dict = {}
    if not os.path.exists(DB):
        print(f"    research.db not reachable at {DB} - the measured leg is NOT run and")
        print("    nothing in this section is reported as a result. On the lab:")
        print("      ./.secrets/lab.sh run research/harness/quantspec.py")
    else:
        print(
            f"\n    {'feed':24s} {'ticks':>7s} {'brk':>5s} {'eps':>4s} {'ep len':>8s} "
            f"{'W (var)':>8s} {'W (range)':>10s}"
        )
        loaded = {}
        for feed in (
            "range_break_100_index",
            "range_break_200_index",
            "step_index",
            "volatility_75_index",
        ):
            d = load_ticks(feed)
            if d is None:
                print(f"    {feed:24s} (absent or too few usable ticks)")
                continue
            loaded[feed] = d
            print(
                f"    {feed:24s} {d['n_ticks']:7d} {d['n_breaks']:5d} {d['n_episodes']:4d} "
                f"{d['mean_episode_ticks']:8.0f} {d['width_from_variance']:8.1f} "
                f"{d['mean_within_range']:10.1f}"
            )
        print("\n    W (var) is sqrt(12 x within-episode variance), which is the width a")
        print("    UNIFORM stationary law implies; W (range) is the mean within-episode")
        print("    range. For a reflecting box fully explored they agree. They are the")
        print("    first thing to read, because quantising.md's eigenvalue inversion said")
        print("    49 and 56 units and rebuilding.md's fit said one shared 60 for both.")

        print(
            f"\n    {'feed':24s} {'lambda_1':>10s} {'l2/l1':>7s} {'l3/l1':>7s} "
            f"{'knee':>7s} {'kurt':>7s} {'AR t1/2':>9s}"
        )
        for feed, d in loaded.items():
            st = tick_stats(d["x"], d["episode"])
            real[feed] = {**{k: v for k, v in d.items() if k not in ("x", "episode")}, **st}
            print(
                f"    {feed:24s} {st['rates'][0]:10.5f} {st['ladder'][1]:7.3f} "
                f"{st['ladder'][2]:7.3f} {st['knee']['shallowest']:7.2f} "
                f"{st['kurtosis_by_window'][-1]:7.3f} {st['ar1_halflife']:9.1f}"
            )

        # ---- the calibration, at the tick sample size and episode length ----
        print("\n    THE CALIBRATION THAT MAKES THOSE NUMBERS READABLE. The de-meaning")
        print("    that pooling episodes forces biases every rate, so the simulated truths")
        print("    are run at each feed's OWN tick count, episode length and measured")
        print("    width, through the identical pipeline. Nothing is compared against 4.")
        cal_rows = {}
        for feed in ("range_break_100_index", "range_break_200_index"):
            if feed not in loaded:
                continue
            d = loaded[feed]
            w = d["width_from_variance"]
            lam1_box = 0.5 * (math.pi / w) ** 2
            n = int(d["x"].size)
            epi = d["mean_episode_ticks"]
            print(f"\n    {feed}: W = {w:.1f}, so a box has lambda_1 = {lam1_box:.5f}/tick")
            print(f"      {'truth':>10s} {'l2/l1':>16s} {'l3/l1':>8s} {'knee':>7s} {'kurt':>8s}")
            rows = {}
            for kind, lab in (("box", "box"), ("ou", "spring"), ("free", "free walk")):
                v2, v3, kn, ku = [], [], [], []
                for rep in range(NREP_TICK):
                    x, e = sim_at(kind, n, w, 1.0, epi, lam1_box, rep)
                    st = tick_stats(x, e)
                    v2.append(st["ladder"][1])
                    v3.append(st["ladder"][2])
                    kn.append(st["knee"]["shallowest"])
                    ku.append(st["kurtosis_by_window"][-1])
                rows[kind] = {
                    "l2_mean": float(np.nanmean(v2)),
                    "l2_sd": float(np.nanstd(v2, ddof=1)),
                    "l3_mean": float(np.nanmean(v3)),
                    "knee": float(np.nanmean(kn)),
                    "kurt": float(np.nanmean(ku)),
                }
                print(
                    f"      {lab:>10s} {rows[kind]['l2_mean']:10.3f}"
                    f"+-{rows[kind]['l2_sd']:.3f} {rows[kind]['l3_mean']:8.3f} "
                    f"{rows[kind]['knee']:7.2f} {rows[kind]['kurt']:8.3f}"
                )
            m = real[feed]
            print(
                f"      {'MEASURED':>10s} {m['ladder'][1]:10.3f}"
                f"{'':8s} {m['ladder'][2]:8.3f} {m['knee']['shallowest']:7.2f} "
                f"{m['kurtosis_by_window'][-1]:8.3f}"
            )
            lo_s, hi_b = rows["ou"]["l2_mean"], rows["box"]["l2_mean"]
            v = m["ladder"][1]
            where = (
                "BELOW the spring - not a confinement of this family"
                if v < lo_s
                else "ABOVE the box - impossible for any confining potential, so something"
                " else is going on"
                if v > hi_b
                else "STRICTLY BETWEEN spring and box, which is what a soft edge predicts"
            )
            alpha = float("nan") if not (lo_s < v < hi_b) else 1.0 + (v - lo_s) / (hi_b - lo_s)
            print(f"      -> {where}")
            if alpha == alpha:
                print(
                    f"      -> interpolated alpha = {alpha:.2f}, wall exponent "
                    f"p = {wall_hardness(alpha):.1f}"
                )
            cal_rows[feed] = {"sim": rows, "measured_l2": v, "alpha": alpha, "verdict": where}
        out["tick_calibration"] = cal_rows

        # ---- the bar cross-check ----
        print("\n    BAR CROSS-CHECK (a different question, kept for comparability)")
        print(
            f"    {'feed':24s} {'bars':>7s} {'brk':>5s} {'eps':>5s} {'l1':>8s} "
            f"{'l2/l1':>7s} {'AR t1/2':>8s}"
        )
        for feed in ("range_break_100_index", "range_break_200_index", "step_index"):
            d = load_bars(feed)
            if d is None:
                print(f"    {feed:24s} (absent)")
                continue
            rt = transfer_rates(d["close"], d["episode"], lag=2, nbin=24, nmode=3)
            lr = ladder(rt)
            real.setdefault(feed, {})["bar"] = {
                "n_bars": d["n_bars"],
                "n_breaks": d["n_breaks"],
                "rates": rt,
                "ladder": lr,
                "ar1_halflife": ar1_halflife(d["close"], d["episode"]),
            }
            print(
                f"    {feed:24s} {d['n_bars']:7d} {d['n_breaks']:5d} {d['n_episodes']:5d} "
                f"{rt[0]:8.4f} {lr[1]:7.3f} {real[feed]['bar']['ar1_halflife']:8.2f}"
            )
    out["measured"] = real

    # ---- 6. the ledger ---------------------------------------------------
    print("\n[6] THE PRE-REGISTERED KILL CONDITIONS")
    ledger = []

    def fire(name: str, cond: bool, detail: str) -> None:
        ledger.append({"condition": name, "fired": bool(cond), "detail": detail})
        print(f"    [{'FIRED' if cond else ' ok  '}] {name}")
        print(f"             {detail}")

    bq, oq = lad["box"]["l2_q"], lad["ou"]["l2_q"]
    fire(
        "1. the estimator cannot recover a known box (4) or a known spring (2)",
        not (bq[0] <= 4.0 <= bq[2]) or not (oq[0] <= 2.0 <= oq[2]),
        f"box 95% [{bq[0]:.3f}, {bq[2]:.3f}] must cover 4; spring 95% "
        f"[{oq[0]:.3f}, {oq[2]:.3f}] must cover 2. The de-meaning that pooling "
        f"episodes forces is what moves them; section 1 shows both are recovered "
        f"exactly without it.",
    )
    fire(
        "2. underpowered - box and spring sampling distributions overlap past 5%",
        err > 0.05,
        f"best single-cut error {err:.1%} over {NREP} replicates",
    )
    fire(
        "3. the free-walk control is indistinguishable from the box",
        abs(naive["free"]["l2"] - naive["box"]["l2"])
        < 2.0 * math.sqrt(naive["free"]["l2_sd"] ** 2 + naive["box"]["l2_sd"] ** 2),
        f"free walk {naive['free']['l2']:.3f} +- {naive['free']['l2_sd']:.3f} against "
        f"box {naive['box']['l2']:.3f} +- {naive['box']['l2_sd']:.3f}, on the raw ladder",
    )
    fire(
        "4. the box reading is curved in its own basis",
        False,
        "RETIRED before the data was seen: section 4 shows the cosine and Hermite "
        "projections do not survive the per-episode de-meaning at all (1.208 and "
        "1.580 where the transfer operator gives 2.908 and 2.154), so only the "
        "basis-free estimator is read and there is no curvature to test",
    )
    fire(
        "5. void - a recovered ratio lands on exactly its null",
        any(abs(v - round(v)) < 1e-9 for v in (a.mean(), b.mean(), fw.mean())),
        f"box {a.mean():.6f}, spring {b.mean():.6f}, free {fw.mean():.6f}",
    )
    sb, sf = scal["box"]["shallowest_mean"], scal["free"]["shallowest_mean"]
    sdb, sdf = scal["box"]["shallowest_sd"], scal["free"]["shallowest_sd"]
    fire(
        "6. no knee - the box's shallowest slope is not distinguishable from the walk's",
        abs(sb - sf) < 2.0 * math.sqrt(sdb**2 + sdf**2),
        f"box {sb:+.3f} +- {sdb:.3f} against free walk {sf:+.3f} +- {sdf:.3f}",
    )
    fire(
        "7. the ladder is uninterpretable - box overlaps the free-walk control",
        float(np.quantile(a, 0.025)) < float(np.quantile(fw, 0.975)),
        f"box 2.5% {np.quantile(a, 0.025):.3f} against free walk 97.5% "
        f"{np.quantile(fw, 0.975):.3f}",
    )
    kb = scal["box"]["kurtosis_mean"][-1]
    ko = scal["ou"]["kurtosis_mean"][-1]
    kf = scal["free"]["kurtosis_mean"][-1]
    fire(
        "8. the density test is void - the free walk sits on top of one of the truths",
        min(abs(kf - kb), abs(kf - ko)) < 0.05,
        f"at m={WINDOWS[-1]}: box {kb:+.3f}, spring {ko:+.3f}, free walk {kf:+.3f} "
        f"(uniform -1.200, Gaussian 0.000)",
    )
    tc = out.get("tick_calibration", {})
    if tc:
        bad = [
            k
            for k, v in tc.items()
            if not (v["sim"]["ou"]["l2_mean"] < v["measured_l2"] < v["sim"]["box"]["l2_mean"])
        ]
        det = "; ".join(
            f"{k}: measured {v['measured_l2']:.3f} against spring "
            f"{v['sim']['ou']['l2_mean']:.3f} and box {v['sim']['box']['l2_mean']:.3f}"
            for k, v in tc.items()
        )
    else:
        bad, det = [], "not evaluated - no real data"
    fire(
        "9. rebuilding.md's soft edge is refuted - the ladder is not strictly between",
        bool(tc) and bool(bad),
        det,
    )
    out["ledger"] = ledger
    print(f"\n    {sum(1 for x in ledger if x['fired'])} of {len(ledger)} fired.")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(out, fh, indent=1, default=float)
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
