"""Shared machinery for `research/grounding.md`.

A library rather than an experiment: no kill conditions here, because nothing
here is a claim. The claims are in `groundstate.py`, `groundslow.py`,
`groundbarrier.py` and `groundborn.py`, and each of those states its own before
any number.

What is here is the four objects those pages share.

**The transfer operator, by Ulam's method.** Bin the state, count transitions,
take the eigenvalues of the row-normalised matrix. `research/quantising.md`
already uses this for the Range Break ladder; it is repeated here rather than
imported so that the two pages cannot silently drift into each other, and
because this version is deliberately run on a *uniform* grid where that one uses
equiprobable bins. The reason is in `static_rates` below.

**The static spectrum**, which is the object this page is built on and which
does not exist anywhere else in the repository. For a reversible one-dimensional
diffusion with constant diffusivity `D` and stationary density `p`, the
generator's Dirichlet form is

    <f, -L f>_p  =  D * Integral p(x) f'(x)^2 dx

so the relaxation rates are the minima of `D * Int p f'^2 / Int p f^2` over
functions orthogonal to the constants. That is the Rayleigh-Ritz principle of
quantum mechanics written for a Fokker-Planck generator, and the thing worth
noticing is what is *not* in it: **no transition data**. The whole spectrum of a
reversible one-dimensional diffusion is a functional of its marginal density and
one scalar. `static_rates` evaluates it with piecewise-linear finite elements,
which turns it into a `p`-weighted graph Laplacian.

**Why a uniform grid and not equiprobable bins.** With equiprobable bins the
outermost cells are the widest, their conductance `m_i/h_i^2` collapses, and the
generalised eigenproblem grows a spurious slow mode localised on the tail: at
N=100 on a standard Gaussian the tail cell returns about `0.45 D` against a true
`lambda_1 = D`, so the estimator reports a mode that is not there and reports it
*below* the real one. On a uniform grid both `A_ii` and `M_ii` are proportional
to the local mass, the mass cancels, and a thin tail cell carries the same
stencil as a fat central one. Empty cells disconnect the graph and are handled
by keeping the largest contiguous run.

**The Kramers-Moyal generator**, which is the classical control for the static
spectrum: estimate the drift and the diffusivity as conditional moments of the
increment, assemble the generator, take its eigenvalues. It uses the
transitions, so if it agrees with the static route the static route has bought
nothing but cheapness, and if it agrees with Ulam and the static route does not,
the disagreement is about reversibility rather than about numerics.

**Analytic checks that need no data.** `sim_box` and `sim_ou` have exactly known
spectra - `(k pi / W)^2 D` and `k theta` - and their stationary densities are
uniform and Gaussian, so `static_rates` on a uniform density must return the
box ladder 1:4:9 and on a Gaussian the spring ladder 1:2:3. That is the whole
`research/quantising.md` dictionary - "a reflecting band is the particle in a
box, an Ornstein-Uhlenbeck generator is the harmonic oscillator" - **recovered
as two evaluations of one formula rather than as two separate facts**, and
`check_analytic` runs it on the exact densities with no simulation anywhere.
"""

from __future__ import annotations

import math
import os
import sqlite3

import numpy as np

DATA = os.environ.get("DATA", os.path.expanduser("~/till_infinity/data"))
DB = os.environ.get("DB", os.path.join(DATA, "research.db"))
LOGS = os.environ.get("LOGS", os.path.expanduser("~/till_infinity/logs"))

#: The Broadie-Glasserman-Kou continuity correction, and by
#: `research/quantising.md` section one the *extrapolation length* of a Robin
#: wall: a barrier monitored every `h` behaves like a Dirichlet wall moved out by
#: `B * sigma * sqrt(h)`. Duplicated from `till_infinity/trading/barriers.py`
#: rather than imported, because a research harness that imports the production
#: module it is auditing cannot report a disagreement with it.
SHIFT = -1.0 / math.sqrt(2.0 * math.pi) * -1.4603545088095868  # -zeta(1/2)/sqrt(2pi)

#: The Deriv synthetic families, and what `research/deriving.md` proved each is.
#: Kept here because three harnesses need the same split into "the theorem covers
#: this" and "it does not".
BROWNIAN = (
    "volatility_10_index",
    "volatility_25_index",
    "volatility_50_index",
    "volatility_75_index",
    "volatility_100_index",
    "volatility_10_1s_index",
    "volatility_25_1s_index",
    "volatility_50_1s_index",
    "volatility_75_1s_index",
    "volatility_100_1s_index",
    "volatility_250_1s_index",
)
LATTICE = ("step_index",)
CONFINED = ("range_break_100_index", "range_break_200_index")
JUMPY = (
    "boom_300_index",
    "boom_500_index",
    "boom_1000_index",
    "crash_300_index",
    "crash_500_index",
    "crash_1000_index",
)
REAL = (
    "btc",
    "eth",
    "gold",
    "silver",
    "eurusd",
    "gbpusd",
    "usdjpy",
    "usdcad",
    "audusd",
    "eurjpy",
    "gbpjpy",
    "us30",
    "us100",
    "ger40",
    "uk100",
    "jp225",
    "hk50",
    "aus200",
    "fra40",
)


# --------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------


def have_db(db: str = DB) -> bool:
    return os.path.exists(db)


def load_bars(feed: str, interval: str = "1m", db: str = DB) -> dict | None:
    """One feed's bars, as float arrays. `None` when the store is not reachable."""
    if not os.path.exists(db):
        return None
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = conn.execute(
        "SELECT ts, open, high, low, close FROM bars WHERE feed=? AND interval=? ORDER BY ts",
        (feed, interval),
    ).fetchall()
    conn.close()
    if len(rows) < 2000:
        return None
    a = np.asarray(rows, dtype=float)
    return {
        "feed": feed,
        "interval": interval,
        "ts": a[:, 0],
        "open": a[:, 1],
        "high": a[:, 2],
        "low": a[:, 3],
        "close": a[:, 4],
        "n": len(rows),
    }


def load_ticks(feed: str, db: str = DB) -> dict | None:
    """One feed's stored tick mids. The store holds a fixed 24-hour snapshot."""
    if not os.path.exists(db):
        return None
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = conn.execute(
        "SELECT ts, bid, ask FROM ticks WHERE feed=? ORDER BY ts ASC", (feed,)
    ).fetchall()
    conn.close()
    if len(rows) < 20000:
        return None
    a = np.asarray(rows, dtype=float)
    return {"feed": feed, "ts": a[:, 0], "mid": 0.5 * (a[:, 1] + a[:, 2]), "n": len(rows)}


def rb_tick_episodes(mid: np.ndarray, min_len: int = 240) -> tuple[np.ndarray, np.ndarray]:
    """Range Break ticks cut at the break and de-meaned within each episode.

    `research/generators.md` establishes the series moves exactly one unit a tick
    between breaks and `research/rebuilding.md` fits the break jump at 130 and
    210 units, so a move of more than five steps is a break and nothing else is.

    De-meaning is not optional and it is not free: the level of a range moves
    when it breaks, so pooling raw levels would put the between-range wander into
    the same histogram as the within-range structure - and because it biases
    every rate, the only readable comparison is against simulated truths pushed
    through the identical function. `research/quantising.md` learned that the
    expensive way and this harness inherits the lesson rather than re-learning it.
    """
    d = np.diff(mid)
    nz = d[d != 0]
    step = float(np.median(np.abs(nz))) if nz.size else 1.0
    isbrk = np.abs(d) > 5.0 * step
    ep = np.concatenate([[0], np.cumsum(isbrk)])
    keep = np.concatenate([[True], ~isbrk])
    x, e = mid[keep], ep[keep]
    _, inv, cnt = np.unique(e, return_inverse=True, return_counts=True)
    ok = cnt[inv] >= min_len
    x, inv = x[ok], inv[ok]
    if x.size < 5000:
        return np.empty(0), np.empty(0, dtype=int)
    _, inv = np.unique(inv, return_inverse=True)
    mu = np.bincount(inv, weights=x) / np.bincount(inv)
    return (x - mu[inv]) / step, inv


# --------------------------------------------------------------------------
# Simulated truths with exactly known spectra
# --------------------------------------------------------------------------


def episode_lengths(n: int, mean_len: float, rng, min_len: int = 8) -> np.ndarray:
    """Geometric episode lengths summing to about `n`.

    `research/deriving.md` measured the Range Break arrival memoryless on both
    feeds (CV 1.003 and 1.076), so geometric and nothing else. The same `min_len`
    the real data gets is applied here, because the de-meaning bias is a function
    of the episode-length distribution and cutting one side only would compare a
    truncated geometric against an untruncated one.
    """
    guess = int(n / max(1.0, min(mean_len, n)) * 1.5) + 32
    lens = np.minimum(rng.geometric(1.0 / mean_len, guess), n)
    cum = np.cumsum(lens)
    hit = np.flatnonzero(cum >= n)
    if hit.size:
        lens = lens[: hit[0] + 1].copy()
        lens[-1] -= int(lens.sum() - n)
    return lens[lens >= min_len]


def _pack(lens: np.ndarray, rng, draw):
    mask = np.arange(int(lens.max()))[None, :] < lens[:, None]
    mat = draw(len(lens), int(lens.max()))
    mu = (mat * mask).sum(axis=1) / mask.sum(axis=1)
    ids = np.repeat(np.arange(len(lens)), lens)
    return (mat - mu[:, None])[mask], ids


def sim_box(n, width, dvar, mean_len, rng, min_len=8):
    """Reflecting Brownian motion in [0, W]: spectrum `(k pi / W)^2 * dvar/2`.

    Folding a free path through a triangle wave of period 2W **is** reflecting
    Brownian motion in law - the method of images - so the discrete skeleton's
    eigenvalues are exact rather than approximated.
    """
    lens = episode_lengths(n, mean_len, rng, min_len)

    def draw(r, m):
        inc = rng.normal(0.0, math.sqrt(dvar), (r, m))
        inc[:, 0] = 0.0
        y = rng.random(r)[:, None] * width + np.cumsum(inc, axis=1)
        t = np.mod(y, 2.0 * width)
        return np.where(t <= width, t, 2.0 * width - t)

    return _pack(lens, rng, draw)


def sim_ou(n, theta, svar, mean_len, rng, min_len=8):
    """Ornstein-Uhlenbeck with the *exact* transition: spectrum `k * theta`."""
    lens = episode_lengths(n, mean_len, rng, min_len)
    a = math.exp(-theta)
    s = math.sqrt(svar * (1.0 - a * a))

    def draw(r, m):
        out = np.empty((r, m))
        out[:, 0] = rng.standard_normal(r) * math.sqrt(svar)
        z = rng.standard_normal((r, m)) * s
        for j in range(1, m):
            out[:, j] = a * out[:, j - 1] + z[:, j]
        return out

    return _pack(lens, rng, draw)


def sim_free(n, dvar, mean_len, rng, min_len=8):
    """A driftless walk cut at the same hazard. No discrete spectrum at all.

    The false-positive control, and the one `research/quantising.md` found
    reproduces the particle-in-a-box ladder because binning a diffusion by its
    own observed support makes that support the box.
    """
    lens = episode_lengths(n, mean_len, rng, min_len)

    def draw(r, m):
        inc = rng.normal(0.0, math.sqrt(dvar), (r, m))
        inc[:, 0] = 0.0
        return np.cumsum(inc, axis=1)

    return _pack(lens, rng, draw)


def sim_two_scale(n, theta, svar, mean_len, rng, min_len=8, ratio=12.0, share=0.45):
    """A sum of a fast and a slow Ornstein-Uhlenbeck: the **memory** positive control.

    The observed coordinate is not Markov - it is the projection of a
    two-dimensional Markov process onto one axis - so its transfer-operator
    eigenvalue is not exponential in the lag and the implied timescale drifts
    upward: a short lag sees mostly the fast mode, a long lag only the slow one.

    It exists because the *other* positive control, `sim_hidden_vol`, turned out
    in the dry run to be caught by the specification ratio and not by the
    timescale scan, which is what two instruments detecting different failures
    looks like. One control that only one instrument can see is not a
    calibration; two, each designed for one, is.
    """
    lens = episode_lengths(n, mean_len, rng, min_len)
    # Match the plain OU's lag-1 autocorrelation exactly, by bisecting a common
    # scale on the two rates. Without this the control is merely *slower* than the
    # OU and an AR(1) half-life separates the two with no error at all - which it
    # did in the dry run, at 0.000. That would have been a control for "is this
    # slow", not for "is this Markov". Matched, the only thing left to see is that
    # the decay is a sum of two exponentials rather than one.
    rho = math.exp(-theta)
    lo, hi = 1e-6, 1e6
    for _ in range(200):
        s = math.sqrt(lo * hi)
        r = (1.0 - share) * math.exp(-s * theta * math.sqrt(ratio)) + share * math.exp(
            -s * theta / math.sqrt(ratio)
        )
        lo, hi = (s, hi) if r > rho else (lo, s)
    s = math.sqrt(lo * hi)
    tf, ts = s * theta * math.sqrt(ratio), s * theta / math.sqrt(ratio)
    af, as_ = math.exp(-tf), math.exp(-ts)
    vf, vs = svar * (1.0 - share), svar * share

    def draw(r, m):
        out = np.empty((r, m))
        f = rng.standard_normal(r) * math.sqrt(vf)
        s = rng.standard_normal(r) * math.sqrt(vs)
        sf = math.sqrt(vf * (1.0 - af * af))
        ss = math.sqrt(vs * (1.0 - as_ * as_))
        out[:, 0] = f + s
        for j in range(1, m):
            f = af * f + rng.standard_normal(r) * sf
            s = as_ * s + rng.standard_normal(r) * ss
            out[:, j] = f + s
        return out

    return _pack(lens, rng, draw)


def single_cut_error(a, b) -> float:
    """The best single-threshold misclassification rate between two samples.

    `research/quantising.md`'s power metric, so the two pages can be read against
    each other. 0.0 means the estimator separates the two truths with no overlap.
    """
    a = np.asarray([v for v in a if np.isfinite(v)], dtype=float)
    b = np.asarray([v for v in b if np.isfinite(v)], dtype=float)
    if a.size < 3 or b.size < 3:
        return float("nan")
    cuts = np.unique(np.concatenate([a, b]))
    best = 1.0
    for c in cuts:
        e = (np.mean(a <= c) + np.mean(b > c)) / 2.0
        best = min(best, e, 1.0 - e)
    return float(best)


def sim_hidden_vol(n, theta, svar, mean_len, rng, min_len=8, vol_theta=0.02, vol_sd=0.7):
    """An OU whose diffusivity is itself a slow hidden process.

    The **positive control for the specification test**. Its marginal is a scale
    mixture of Gaussians - fatter than Gaussian - so the static route, which sees
    only the marginal, reads a potential that is not the one generating the
    dynamics. A test that cannot separate this from a plain OU cannot detect
    hidden state anywhere, and saying so before looking at a market is what makes
    the market reading mean anything.
    """
    lens = episode_lengths(n, mean_len, rng, min_len)
    a = math.exp(-theta)

    def draw(r, m):
        out = np.empty((r, m))
        lv = rng.standard_normal(r) * vol_sd
        out[:, 0] = rng.standard_normal(r) * math.sqrt(svar)
        av = math.exp(-vol_theta)
        sv = vol_sd * math.sqrt(1.0 - av * av)
        for j in range(1, m):
            lv = av * lv + rng.standard_normal(r) * sv
            sd = math.sqrt(svar * (1.0 - a * a)) * np.exp(lv - 0.5 * vol_sd**2)
            out[:, j] = a * out[:, j - 1] + rng.standard_normal(r) * sd
        return out

    return _pack(lens, rng, draw)


# --------------------------------------------------------------------------
# Estimators
# --------------------------------------------------------------------------


def _lagged(x: np.ndarray, ep: np.ndarray, lag: int):
    """Lagged pairs that do not straddle an episode boundary."""
    if ep is None:
        return x[:-lag], x[lag:]
    same = ep[lag:] == ep[:-lag]
    return x[:-lag][same], x[lag:][same]


def uniform_grid(x: np.ndarray, nbin: int, trim: float = 0.0) -> np.ndarray:
    """A uniform grid spanning the observed support.

    **`trim` defaults to zero and should stay there**, which is a measurement
    rather than a preference. Trimming moves the reflecting boundary inward, and
    an inward wall is a harder wall: on 400,000 exact Gaussian samples, whose
    true ladder is 1:2:3, the recovered `lambda_2/lambda_1` runs

        trim 0      1.994      (true 2.000)
        trim 0.02%  2.032
        trim 0.1%   2.102
        trim 0.5%   2.269
        trim 2%     2.567

    so **trimming a spring's tails turns it into something that reads as a box**,
    monotonically, and at 2% it is a third of the way to 4.00. A parameter that
    walks an answer toward the more interesting hypothesis is exactly the knob
    this field hides in, so it is exposed, defaulted off, and scanned wherever it
    is used.
    """
    lo, hi = (
        (float(x.min()), float(x.max()))
        if trim <= 0
        else (float(np.quantile(x, trim)), float(np.quantile(x, 1.0 - trim)))
    )
    pad = 1e-9 * max(1.0, hi - lo)
    return np.linspace(lo - pad, hi + pad, nbin + 1)


def _largest_run(nonempty: np.ndarray) -> slice:
    """The longest contiguous run of occupied cells.

    An empty cell disconnects the weighted graph and hands the eigensolver an
    extra exact zero, which would be read as a second slow mode. Keeping the
    largest run is the cheapest honest repair and the number of cells dropped is
    reported by every caller.
    """
    best = cur = 0
    best_end = 0
    for i, ok in enumerate(nonempty):
        cur = cur + 1 if ok else 0
        if cur > best:
            best, best_end = cur, i + 1
    return slice(best_end - best, best_end)


def static_rates(
    x: np.ndarray,
    dvar: float,
    nbin: int = 96,
    nmode: int = 3,
    trim: float = 0.0,
) -> tuple[list[float], dict]:
    """Relaxation rates from the marginal density alone, plus one diffusivity.

    The derivation, in full, because the whole page rests on it. A reversible
    diffusion `dX = b dt + sqrt(2D) dW` with stationary density `p` has
    `b = D (log p)'`, and its generator `L f = D f'' + b f'` is self-adjoint in
    `L^2(p)` with Dirichlet form `<f, -L f>_p = D Int p f'^2`. Rayleigh-Ritz on
    piecewise-linear hat functions over a grid `x_0 < ... < x_N` gives the
    generalised symmetric eigenproblem `A v = (lambda/D) M v` with

        A[i,i]   = m[i-1]/h[i-1]^2 + m[i]/h[i]^2
        A[i,i+1] = -m[i]/h[i]^2
        M[i,i]   = (m[i-1] + m[i]) / 2          (lumped)

    where `m[i]` is the probability mass of cell `i` and `h[i]` its width: a
    `p`-weighted graph Laplacian against a `p`-weighted mass. On a uniform grid
    `h` is constant and `m` cancels between `A` and `M` for a thin cell, which is
    why the grid is uniform - see the module docstring for what equiprobable bins
    do to the tail.

    `dvar` is the one-step increment variance, so `D = dvar/2` per sampling
    interval. **The ratios `lambda_k / lambda_1` do not depend on it at all**, so
    the ladder that `research/quantising.md` measures from the dynamics is
    predicted here by the density with nothing else in it.

    Returns the first `nmode` non-zero rates and a diagnostics dict.
    """
    edges = uniform_grid(x, nbin, trim)
    cnt = np.histogram(x, bins=edges)[0].astype(float)
    keep = _largest_run(cnt > 0)
    cnt = cnt[keep]
    edges = edges[keep.start : keep.stop + 1]
    if cnt.size < 8:
        return [float("nan")] * nmode, {"cells": int(cnt.size), "dropped": nbin - int(cnt.size)}
    return rates_from_mass(edges, cnt / cnt.sum(), dvar, nmode) + (
        {"cells": int(cnt.size), "dropped": int(nbin - cnt.size), "nbin": nbin},
    )


def rates_from_mass(
    edges: np.ndarray, m: np.ndarray, dvar: float, nmode: int = 3
) -> tuple[list[float]]:
    """The static spectrum from an exact cell-mass vector rather than a sample.

    Split out so `check_analytic` can hand the estimator a density it knows
    exactly. That matters: the first version of the check built its "Gaussian" by
    flooring `exp(-x^2/2s^2) * 20000` to an integer count, which leaves a long
    plateau of count-1 cells in each tail - a *uniform* stretch bolted onto a
    Gaussian body through a narrow neck - and the estimator correctly reported
    the slow mode that plateau really has. It read 1 : 1.00 : 1.38 against a true
    1:2:3 and the fault was entirely in the check.
    """
    # A cell of exactly zero mass disconnects the weighted graph and hands the
    # solver an extra exact zero, which reads as a second slow mode. It happens
    # on exact densities at fine grids, where the tail masses underflow: the
    # analytic Gaussian check returned lambda_1 = 0.00000 at 1024 cells before
    # this filter and 0.99967 of truth at 512.
    keep = _largest_run(m > 0)
    m = m[keep]
    edges = edges[keep.start : keep.stop + 1]
    if m.size < 8:
        return ([float("nan")] * nmode,)
    h = np.diff(edges)
    cond = m / h**2
    nn = m.size + 1
    a = np.zeros((nn, nn))
    idx = np.arange(m.size)
    a[idx, idx] += cond
    a[idx + 1, idx + 1] += cond
    a[idx, idx + 1] -= cond
    a[idx + 1, idx] -= cond
    mass = np.zeros(nn)
    mass[:-1] += 0.5 * m
    mass[1:] += 0.5 * m
    r = mass > 0
    a, mass = a[r][:, r], mass[r]
    s = 1.0 / np.sqrt(mass)
    ev = np.linalg.eigvalsh(a * s[:, None] * s[None, :])
    ev = np.sort(np.maximum(ev, 0.0)) * (0.5 * dvar)
    return ([float(v) for v in ev[1 : nmode + 1]],)


def ulam_rates(
    x: np.ndarray,
    ep: np.ndarray | None,
    lag: int,
    nbin: int = 96,
    nmode: int = 3,
    trim: float = 0.0,
    edges: np.ndarray | None = None,
) -> tuple[list[float], dict]:
    """Rates from the eigenvalues of the binned lag-`lag` transition matrix.

    Ulam's method. `rates = -log(mu_j)/lag`. The grid is the **same uniform grid**
    `static_rates` uses, deliberately: the two estimators then share every
    numerical artefact of the binning, so a disagreement between them cannot be
    the bins. One reads the joint law of `(x_t, x_{t+lag})` and the other reads
    only its marginal.
    """
    if edges is None:
        edges = uniform_grid(x, nbin, trim)
    a, b = _lagged(x, ep, lag)
    if a.size < 500:
        return [float("nan")] * nmode, {"pairs": int(a.size)}
    ia = np.clip(np.searchsorted(edges, a, side="right") - 1, 0, len(edges) - 2)
    ib = np.clip(np.searchsorted(edges, b, side="right") - 1, 0, len(edges) - 2)
    n = len(edges) - 1
    mat = np.zeros((n, n))
    np.add.at(mat, (ia, ib), 1.0)
    row = mat.sum(axis=1)
    keep = row > 0
    mat, row = mat[keep][:, keep], row[keep]
    ev = np.linalg.eigvals(mat / row[:, None])
    ev = ev[np.argsort(-np.abs(ev))]
    out = []
    for j in range(1, nmode + 1):
        if j >= len(ev):
            out.append(float("nan"))
            continue
        mu = abs(complex(ev[j]))
        out.append(-math.log(mu) / lag if 0 < mu < 1 else float("nan"))
    return out, {"pairs": int(a.size), "cells": int(keep.sum()), "lag": lag}


def km_rates(
    x: np.ndarray,
    ep: np.ndarray | None,
    nbin: int = 96,
    nmode: int = 3,
    trim: float = 0.0,
    lag: int = 1,
) -> tuple[list[float], dict]:
    """The classical control: a generator assembled from conditional moments.

    Kramers-Moyal. Bin the state; in each bin estimate `b = E[dX|x]/dt` and
    `D = Var(dX|x)/(2 dt)`; assemble `L f = D f'' + b f'` by central differences;
    take the eigenvalues. This uses the transitions the static route throws away
    and assumes nothing about reversibility, so it is the right thing to beat: if
    it lands where `static_rates` lands, the derivation has bought only cheapness.
    """
    edges = uniform_grid(x, nbin, trim)
    a, b = _lagged(x, ep, lag)
    d = (b - a) / lag
    ia = np.clip(np.searchsorted(edges, a, side="right") - 1, 0, len(edges) - 2)
    n = len(edges) - 1
    cnt = np.bincount(ia, minlength=n).astype(float)
    keep = _largest_run(cnt >= 20)
    s1 = np.bincount(ia, weights=d, minlength=n)
    s2 = np.bincount(ia, weights=d * d, minlength=n)
    with np.errstate(invalid="ignore", divide="ignore"):
        mu = s1 / cnt
        var = s2 / cnt - mu * mu
    mu, var, cnt = mu[keep], var[keep], cnt[keep]
    if mu.size < 8:
        return [float("nan")] * nmode, {"cells": int(mu.size)}
    h = float(np.diff(edges).mean())
    dd = np.maximum(var, 1e-12) / 2.0
    k = mu.size
    gen = np.zeros((k, k))
    i = np.arange(1, k - 1)
    gen[i, i - 1] = dd[i] / h**2 - mu[i] / (2 * h)
    gen[i, i + 1] = dd[i] / h**2 + mu[i] / (2 * h)
    gen[i, i] = -2 * dd[i] / h**2
    gen[0, 0], gen[0, 1] = -dd[0] / h**2, dd[0] / h**2
    gen[-1, -1], gen[-1, -2] = -dd[-1] / h**2, dd[-1] / h**2
    ev = np.linalg.eigvals(gen).real
    ev = -np.sort(-ev)
    out = [float(max(0.0, -v)) for v in ev[1 : nmode + 1]]
    return out, {"cells": int(mu.size), "min_count": int(cnt.min())}


def ladder(rates: list[float]) -> list[float]:
    if not rates or not np.isfinite(rates[0]) or rates[0] <= 0:
        return [float("nan")] * len(rates)
    return [r / rates[0] for r in rates]


def ar1_halflife(x: np.ndarray, ep: np.ndarray | None = None) -> float:
    """The one number this desk would reach for instead of any of the above."""
    a, b = _lagged(x, ep, 1)
    if a.size < 100:
        return float("nan")
    a = a - a.mean()
    b = b - b.mean()
    den = float(np.dot(a, a))
    rho = float(np.dot(a, b) / den) if den > 0 else 0.0
    return -math.log(2.0) / math.log(abs(rho)) if 0 < abs(rho) < 1 else float("inf")


def mean_sd(v) -> tuple[float, float]:
    v = np.asarray([x for x in v if np.isfinite(x)], dtype=float)
    if v.size == 0:
        return float("nan"), float("nan")
    return float(v.mean()), float(v.std(ddof=1)) if v.size > 1 else 0.0


def check_analytic(nbin: int = 200) -> dict:
    """`static_rates` against two densities whose spectra are known exactly.

    No simulation and no data: the uniform density on [0, W] is fed in as an
    exact histogram and must return the box ladder 1:4:9, and a Gaussian must
    return the spring's 1:2:3. This is `research/quantising.md`'s dictionary
    recovered as one formula evaluated twice.
    """
    out = {}
    w, dvar = 10.0, 1.0
    edges = np.linspace(0.0, w, nbin + 1)
    (r,) = rates_from_mass(edges, np.full(nbin, 1.0 / nbin), dvar)
    out["uniform"] = {
        "rates": r,
        "ladder": ladder(r),
        "true_l1": (math.pi / w) ** 2 * dvar / 2.0,
        "true_ladder": [1.0, 4.0, 9.0],
    }
    s = 3.0
    edges = np.linspace(-8 * s, 8 * s, nbin + 1)
    cdf = 0.5 * (1.0 + np.vectorize(math.erf)(edges / (s * math.sqrt(2.0))))
    m = np.diff(cdf)
    (r,) = rates_from_mass(edges, m / m.sum(), dvar)
    out["gaussian"] = {
        "rates": r,
        "ladder": ladder(r),
        "true_l1": dvar / 2.0 / s**2,
        "true_ladder": [1.0, 2.0, 3.0],
    }
    return out


if __name__ == "__main__":
    import json

    print(json.dumps(check_analytic(), indent=2, default=float))
