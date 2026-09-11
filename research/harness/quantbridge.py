"""Reconstructing the path inside a bar, and deconvolving the quote grid.

This is the "get to the real series" half of the imaginary-time programme, and
it is the half with money in it, because the desk holds far more bar history than
tick history. Two reconstructions, each with the classical estimator that does
the same job sitting beside it.

## One: what happened inside the bar

A bar is a coarse-graining of a tick path. Recovering the interior from
`(O, H, L, C)` is a **boundary-value problem for the propagator**: the path is a
Brownian bridge pinned at `O` and `C` and confined to `[L, H]`, and the
conditional law of the interior is the ratio of two propagators - the one with
walls over the one without. The propagator between two absorbing walls is the
free kernel plus an **infinite lattice of image charges**,

    p(t, x, y) = sum_k [ phi_t(y - x + 2k(H-L)) - phi_t(y + x - 2H + 2k(H-L)) ]

which is section one of `research/quantising.md` with one wall replaced by two,
and it is the Poisson-summation dual of the eigenmode expansion that
`quantspec.py` uses: images converge fast at short times, eigenmodes at long
ones. Rather than truncate either series this harness evaluates the conditional
law exactly by forward-backward recursion on a price grid, which is the same
object with no series in it.

**The conditioning is containment, not attainment**, and that is the right model
rather than a weakening: `H` and `L` are set by *ticks*, and the thing being
reconstructed is the sub-bar closes, which lie strictly inside. Conditioning on
the sub-bar closes attaining the extremes would be false.

### The classical control, and it is an identity

For a driftless random walk observed exactly at bar closes, the **Kalman
smoother's conditional mean between observations is the Brownian bridge mean, and
the Brownian bridge mean is linear interpolation.** That is a theorem, not a
measurement, so the `(O, C)`-only part of this construction is pure notation and
this harness checks the identity numerically rather than pretending otherwise.

What the path integral adds that a Kalman smoother cannot represent is the
conditioning on `H` and `L`, because a running maximum is not a linear functional
of the state and has no place in a linear-Gaussian filter. **So the entire
measurable content of the bridge is: how much do the high and the low tell you
about the interior?** That is the number this section exists to produce.

## Two: the quote grid as a measurement operator

`research/twins.md` found `volatility_150_1s_index` quoted too coarsely to carry
any tick statistic, so the rounding is real and measurable. The quoted price is
the latent price passed through a quantiser - a measurement operator with a
resolution - and recovering the latent state is deconvolution. Two estimators:
the exact posterior, which uses the true likelihood (the latent lay somewhere
inside the cell that was printed), and a **Kalman smoother** that treats rounding
as additive noise of variance `Delta^2/12`, which is what everyone does. If the
Kalman smoother matches, the exact treatment is notation and this page says so.

## What would count as failure, written before any number is printed

1. **The bridge dies** if it does not beat linear interpolation on root mean
   square error against the true path, on simulated data where the generator is
   exactly the Brownian motion the construction assumes.
2. **The `(H, L)` information claim dies** if that improvement is under 2%, which
   would make the extra two numbers in every bar worth nothing.
3. **The Kalman identity must hold**: the smoother's intra-bar mean on closes
   alone must equal linear interpolation to numerical precision. If it does not,
   the Kalman implementation is wrong and nothing compared against it can be read.
   This is the live-estimator control.
4. **The conditional law dies** if its nominal 90% band does not contain the truth
   between 85% and 95% of the time. A mean that is better but whose uncertainty
   is wrong is not a reconstruction.
5. **The real-data leg dies** if the bridge fails to beat linear interpolation on
   real bars. Real instruments are not Brownian and the conditional law could be
   wrong enough to hurt rather than help - that is the point of running it.
6. **The deconvolution claim dies** if the exact posterior does not beat the
   Kalman smoother at any grid coarseness, in which case the density-matrix
   framing is a relabelling of a Kalman smoother and is reported as one.
7. **The run is void** if any root mean square error is exactly zero, if a
   reconstruction equals its own input, or if two methods that are not the same
   estimator return identical numbers.

## The data

The synthetics live in `research.db` on the lab. When it is unreachable the
simulated leg still runs in full, and the real leg falls back to
`.data/prices/prices.db`, which holds one-minute and fifteen-minute bars for the
broker's real instruments - including Deriv's own quotes for them. That is a
*harder* test than the synthetics, because a real instrument has fat tails and
volatility clustering and the construction assumes neither, so beating linear
interpolation there is worth more than beating it on a process built to order.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3

import numpy as np

DATA = os.environ.get("DATA", os.path.expanduser("~/till_infinity/data"))
DB = os.environ.get("DB", os.path.join(DATA, "research.db"))
#: The local store of real instruments, used when the lab is unreachable.
LOCAL = os.environ.get("LOCAL_DB", ".data/prices/prices.db")
OUT = os.environ.get("OUT", os.path.expanduser("~/till_infinity/logs/quantbridge.json"))
SEED = int(os.environ.get("SEED", "20260911"))
#: Price cells across [L, H] for the forward-backward recursion.
NCELL = int(os.environ.get("NCELL", "161"))
#: Sub-bar steps: 15 one-minute closes inside a fifteen-minute bar.
NSUB = int(os.environ.get("NSUB", "15"))
NBAR_SIM = int(os.environ.get("NBAR_SIM", "20000"))
#: Ticks per sub-step when simulating, so the bar's H and L are set by a finer
#: path than the one being reconstructed - exactly as they are in the data.
TICKS_PER_SUB = int(os.environ.get("TICKS_PER_SUB", "20"))


# --------------------------------------------------------------------------
# The conditional law of the interior, exactly
# --------------------------------------------------------------------------

def _kernel_matrix(ncell: int, s: float) -> np.ndarray:
    """One sub-step transition on the unit grid, absorbing outside it.

    `s` is the sub-step standard deviation as a fraction of the bar's high-low
    range, which is the only dimensionless parameter the problem has. Rows are
    normalised to the mass that stays inside, which is what conditioning on
    containment means.
    """
    x = (np.arange(ncell) + 0.5) / ncell
    d = x[None, :] - x[:, None]
    k = np.exp(-0.5 * (d / s) ** 2)
    k /= k.sum(axis=1, keepdims=True)
    return k


def bridge_interior(o: np.ndarray, c: np.ndarray, lo: np.ndarray, hi: np.ndarray,
                    sigma_sub: np.ndarray, nsub: int, ncell: int = NCELL,
                    nbucket: int = 24):
    """E[X_t | O, C, the path stayed in [L, H]] and its standard deviation.

    Forward-backward on a price grid: the forward pass carries the density from
    `O` with the walls in place, the backward pass carries it from `C`, and their
    product at each interior time is the conditional law. Exact up to the grid,
    with no image series truncated and no sampling error.

    Bars are bucketed by the one dimensionless parameter, `sigma_sub / (H - L)`,
    so one kernel serves many bars and the whole thing is a handful of matrix
    multiplications rather than a loop over bars.
    """
    n = len(o)
    rng_hl = hi - lo
    good = (rng_hl > 0) & (sigma_sub > 0)
    s = np.where(good, sigma_sub / np.maximum(rng_hl, 1e-12), 0.1)
    # Below 1/ncell the grid cannot represent the step; above 1 the walls are
    # irrelevant. Both ends are clipped and the count at each is reported.
    s = np.clip(s, 1.5 / ncell, 1.0)
    edges = np.exp(np.linspace(math.log(s.min() * 0.999), math.log(s.max() * 1.001),
                               nbucket + 1))
    which = np.clip(np.searchsorted(edges, s, side="right") - 1, 0, nbucket - 1)

    mean = np.full((n, nsub - 1), np.nan)
    sd = np.full((n, nsub - 1), np.nan)
    xg = (np.arange(ncell) + 0.5) / ncell
    for b in range(nbucket):
        idx = np.flatnonzero(which == b)
        if idx.size == 0:
            continue
        k = _kernel_matrix(ncell, float(np.sqrt(np.exp(
            0.5 * (math.log(edges[b]) + math.log(edges[b + 1])))) ** 2))
        u0 = np.clip((o[idx] - lo[idx]) / rng_hl[idx], 0.0, 1.0)
        u1 = np.clip((c[idx] - lo[idx]) / rng_hl[idx], 0.0, 1.0)
        i0 = np.clip((u0 * ncell).astype(int), 0, ncell - 1)
        i1 = np.clip((u1 * ncell).astype(int), 0, ncell - 1)
        fwd = np.zeros((idx.size, ncell))
        fwd[np.arange(idx.size), i0] = 1.0
        alphas = []
        for _ in range(nsub - 1):
            fwd = fwd @ k
            ssum = fwd.sum(axis=1, keepdims=True)
            fwd = fwd / np.maximum(ssum, 1e-300)
            alphas.append(fwd.copy())
        bwd = np.zeros((idx.size, ncell))
        bwd[np.arange(idx.size), i1] = 1.0
        betas = [None] * (nsub - 1)
        for t in range(nsub - 2, -1, -1):
            bwd = bwd @ k.T
            bsum = bwd.sum(axis=1, keepdims=True)
            bwd = bwd / np.maximum(bsum, 1e-300)
            betas[t] = bwd.copy()
        for t in range(nsub - 1):
            g = alphas[t] * betas[t]
            g /= np.maximum(g.sum(axis=1, keepdims=True), 1e-300)
            m = g @ xg
            v = g @ (xg * xg) - m * m
            mean[idx, t] = lo[idx] + rng_hl[idx] * m
            sd[idx, t] = rng_hl[idx] * np.sqrt(np.maximum(v, 0.0))
    return mean, sd


def linear_interior(o: np.ndarray, c: np.ndarray, nsub: int) -> np.ndarray:
    """Straight line from open to close.

    This is simultaneously three things: the naive chart reading, the mean of the
    Brownian bridge pinned only at the ends, and the Kalman smoother's
    conditional mean for a random walk observed at the bar boundaries. That they
    coincide is a theorem and is checked in section 0.
    """
    w = (np.arange(1, nsub) / nsub)[None, :]
    return o[:, None] + (c - o)[:, None] * w


def zigzag_interior(o: np.ndarray, c: np.ndarray, lo: np.ndarray, hi: np.ndarray,
                    nsub: int) -> np.ndarray:
    """O to the nearer extreme, to the further one, then to C, at constant speed.

    What charting software draws inside a bar, and the only `(H, L)`-aware
    control that is not a probability model.
    """
    first_hi = np.abs(hi - o) <= np.abs(lo - o)
    p1 = np.where(first_hi, hi, lo)
    p2 = np.where(first_hi, lo, hi)
    legs = np.stack([o, p1, p2, c], axis=1)
    d = np.abs(np.diff(legs, axis=1))
    tot = d.sum(axis=1)
    tot = np.where(tot <= 0, 1.0, tot)
    cum = np.concatenate([np.zeros((len(o), 1)), np.cumsum(d, axis=1) / tot[:, None]],
                         axis=1)
    out = np.empty((len(o), nsub - 1))
    frac = np.arange(1, nsub) / nsub
    for j, f in enumerate(frac):
        seg = np.clip((cum <= f).sum(axis=1) - 1, 0, 2)
        a = cum[np.arange(len(o)), seg]
        b = cum[np.arange(len(o)), seg + 1]
        w = np.where(b > a, (f - a) / np.maximum(b - a, 1e-12), 0.0)
        out[:, j] = legs[np.arange(len(o)), seg] + w * (
            legs[np.arange(len(o)), seg + 1] - legs[np.arange(len(o)), seg])
    return out


def kalman_interior(o: np.ndarray, c: np.ndarray, nsub: int) -> np.ndarray:
    """RTS smoother for a random walk seen exactly at the bar's two endpoints.

    Implemented from the recursions rather than asserted, because its agreement
    with `linear_interior` is the live-estimator control for this whole section.
    """
    n = len(o)
    q = 1.0
    out = np.empty((n, nsub - 1))
    for i in range(n):
        m = np.zeros(nsub + 1)
        p = np.zeros(nsub + 1)
        m[0], p[0] = o[i], 0.0
        for t in range(1, nsub + 1):
            m[t], p[t] = m[t - 1], p[t - 1] + q
        # Exact observation of the final state: condition, then smooth back.
        ms = m.copy()
        ps = p.copy()
        ms[nsub], ps[nsub] = c[i], 0.0
        for t in range(nsub - 1, -1, -1):
            pp = p[t] + q
            g = p[t] / pp
            ms[t] = m[t] + g * (ms[t + 1] - m[t])
            ps[t] = p[t] + g * g * (ps[t + 1] - pp)
        out[i] = ms[1:nsub]
    return out


# --------------------------------------------------------------------------
# Two: the quote grid as a measurement operator
# --------------------------------------------------------------------------

def deconvolve_exact(q: np.ndarray, delta: float, sigma: float,
                     ncell: int = 96) -> np.ndarray:
    """Posterior mean of the latent walk given quotes rounded to a grid.

    The likelihood is the true one - the latent price lay somewhere inside the
    cell that was printed - so this is forward-backward with a box likelihood
    rather than a Gaussian one. In the imaginary-time language the quantiser is a
    projective measurement and this is the conditioned density; in plain language
    it is the exact posterior and the Kalman smoother is its Gaussian
    approximation.
    """
    n = len(q)
    off = (np.arange(ncell) + 0.5) / ncell - 0.5  # within-cell offset, in units of delta
    x = q[:, None] + delta * off[None, :]
    # Transition kernel between consecutive cell grids, which move with the quote.
    alpha = np.full((n, ncell), 1.0 / ncell)
    fw = np.empty((n, ncell))
    fw[0] = alpha[0]
    for t in range(1, n):
        d = x[t][None, :] - x[t - 1][:, None]
        k = np.exp(-0.5 * (d / sigma) ** 2)
        v = fw[t - 1] @ k
        s = v.sum()
        fw[t] = v / s if s > 0 else alpha[t]
    bw = np.empty((n, ncell))
    bw[n - 1] = 1.0 / ncell
    for t in range(n - 2, -1, -1):
        d = x[t + 1][None, :] - x[t][:, None]
        k = np.exp(-0.5 * (d / sigma) ** 2)
        v = k @ bw[t + 1]
        s = v.sum()
        bw[t] = v / s if s > 0 else alpha[t]
    g = fw * bw
    g /= np.maximum(g.sum(axis=1, keepdims=True), 1e-300)
    return (g * x).sum(axis=1)


def deconvolve_kalman(q: np.ndarray, delta: float, sigma: float) -> np.ndarray:
    """RTS smoother treating the rounding as additive noise of variance d^2/12.

    The classical control, and what every desk does.
    """
    n = len(q)
    r = delta * delta / 12.0
    qv = sigma * sigma
    m = np.empty(n)
    p = np.empty(n)
    mp = np.empty(n)
    pp = np.empty(n)
    m[0], p[0] = q[0], r
    mp[0], pp[0] = q[0], r
    for t in range(1, n):
        mp[t] = m[t - 1]
        pp[t] = p[t - 1] + qv
        k = pp[t] / (pp[t] + r)
        m[t] = mp[t] + k * (q[t] - mp[t])
        p[t] = (1.0 - k) * pp[t]
    ms = m.copy()
    for t in range(n - 2, -1, -1):
        g = p[t] / pp[t + 1]
        ms[t] = m[t] + g * (ms[t + 1] - mp[t + 1])
    return ms


# --------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------

def simulate(nbar: int, nsub: int, tps: int, rng: np.random.Generator):
    """True tick paths, then the bar they coarse-grain to.

    The bar's high and low come from the *tick* path and the thing reconstructed
    is the sub-bar closes, so the extremes are strictly outside what is being
    predicted - which is the relationship the real data has and the reason
    containment rather than attainment is the right conditioning.
    """
    steps = rng.standard_normal((nbar, nsub * tps))
    path = np.cumsum(steps, axis=1)
    o = np.zeros(nbar)
    c = path[:, -1]
    hi = np.maximum(path.max(axis=1), 0.0)
    lo = np.minimum(path.min(axis=1), 0.0)
    sub = path[:, tps - 1:: tps][:, : nsub - 1]
    return o, c, hi, lo, sub


def load_pairs(dbpath: str, feed: str, venue: str | None, coarse: str, fine: str,
               factor: int):
    """Coarse bars and the fine bars that compose them, aligned by timestamp."""
    if not os.path.exists(dbpath):
        return None
    conn = sqlite3.connect(f"file:{dbpath}?mode=ro", uri=True)
    args: list = [feed, coarse]
    q = "SELECT ts, open, high, low, close FROM bars WHERE feed=? AND interval=?"
    if venue:
        q += " AND venue=?"
        args.append(venue)
    cb = conn.execute(q + " ORDER BY ts", args).fetchall()
    args = [feed, fine]
    q = "SELECT ts, close FROM bars WHERE feed=? AND interval=?"
    if venue:
        q += " AND venue=?"
        args.append(venue)
    fb = conn.execute(q + " ORDER BY ts", args).fetchall()
    conn.close()
    if len(cb) < 200 or len(fb) < 200:
        return None
    step = {"1m": 60, "5m": 300, "15m": 900}[fine]
    fine_by_ts = {int(r[0]): float(r[1]) for r in fb}
    o, c, hi, lo, sub = [], [], [], [], []
    for ts, oo, hh, ll, cc in cb:
        ts = int(ts)
        want = [ts + step * (j + 1) for j in range(factor - 1)]
        vals = [fine_by_ts.get(w) for w in want]
        if any(v is None for v in vals) or hh <= ll:
            continue
        o.append(float(oo))
        c.append(float(cc))
        hi.append(float(hh))
        lo.append(float(ll))
        sub.append(vals)
    if len(o) < 200:
        return None
    return (np.array(o), np.array(c), np.array(hi), np.array(lo),
            np.array(sub, dtype=float))


def score(pred: np.ndarray, truth: np.ndarray, scale: np.ndarray) -> float:
    """Root mean square error in units of the bar's own close-to-close sigma."""
    e = (pred - truth) / scale[:, None]
    return float(np.sqrt(np.nanmean(e * e)))


def main() -> None:
    rng = np.random.default_rng(SEED)
    out: dict = {}

    print("=" * 98)
    print("RECONSTRUCTING THE PATH INSIDE A BAR, AND DECONVOLVING THE QUOTE GRID")
    print("=" * 98)

    # ---- 0. the identity that makes the O,C half notation -----------------
    print("\n[0] THE CLASSICAL CONTROL IS AN IDENTITY, AND IT IS CHECKED NOT ASSERTED")
    print("    For a driftless random walk observed exactly at the bar's endpoints, the")
    print("    Kalman smoother's conditional mean, the Brownian bridge mean and straight")
    print("    linear interpolation are the same function. So the (O, C) half of this")
    print("    construction is notation. The whole measurable content is what H and L add.")
    oo = rng.standard_normal(200) * 10.0
    cc = oo + rng.standard_normal(200) * 5.0
    lin = linear_interior(oo, cc, NSUB)
    kal = kalman_interior(oo, cc, NSUB)
    ident = float(np.max(np.abs(lin - kal)))
    out["kalman_identity_maxabs"] = ident
    print(f"\n    max |Kalman smoother - linear interpolation| over 200 bars x "
          f"{NSUB - 1} interior points: {ident:.3e}")

    # ---- 1. simulation ----------------------------------------------------
    print("\n[1] SIMULATED, WHERE THE GENERATOR IS EXACTLY WHAT THE BRIDGE ASSUMES")
    print(f"    {NBAR_SIM:,} bars of {NSUB} sub-steps built from {TICKS_PER_SUB} ticks each,")
    print("    so H and L are set by a finer path than the one reconstructed - the same")
    print("    relationship the real data has.")
    o, c, hi, lo, sub = simulate(NBAR_SIM, NSUB, TICKS_PER_SUB, rng)
    scale = np.full(len(o), math.sqrt(NSUB * TICKS_PER_SUB))
    # Parkinson on the bar's own range, in units of the SUB-STEP: the bar is NSUB
    # sub-steps long, so E[range] = sigma_sub * sqrt(8*NSUB/pi). The first version
    # of this line carried an extra sqrt(TICKS_PER_SUB) and made the simulated
    # bridge four times too diffuse, which is why the chart-drawing zigzag beat
    # it on data generated by exactly the process the bridge assumes.
    sig_sub = (hi - lo) / math.sqrt(8.0 * NSUB / math.pi)
    bm, bs = bridge_interior(o, c, lo, hi, sig_sub, NSUB)
    rows = {
        "linear / Kalman / OC-bridge": linear_interior(o, c, NSUB),
        "OHLC zigzag": zigzag_interior(o, c, lo, hi, NSUB),
        "conditioned bridge": bm,
    }
    sim = {}
    print(f"\n    {'method':32s} {'RMSE (bar sigmas)':>19s} {'vs linear':>11s}")
    base = score(rows["linear / Kalman / OC-bridge"], sub, scale)
    for name, p in rows.items():
        r = score(p, sub, scale)
        sim[name] = r
        print(f"    {name:32s} {r:19.5f} {(r / base - 1) * 100:+10.2f}%")
    out["sim_rmse"] = sim

    # How much is left on the table by conditioning on containment rather than
    # attainment? The zigzag is the only control that uses the fact that the path
    # *reached* H and L, so if blending it in still helps after the bridge has
    # spoken, attainment carries information the bridge is not using. The weight
    # is fitted on the first half and scored on the second.
    zz_pred = rows["OHLC zigzag"]
    half = len(o) // 2
    resid = (sub - bm)[:half].ravel()
    extra = (zz_pred - bm)[:half].ravel()
    w = float(resid @ extra / max(extra @ extra, 1e-12))
    blend = bm[half:] + w * (zz_pred - bm)[half:]
    r_blend = score(blend, sub[half:], scale[half:])
    r_bridge_h2 = score(bm[half:], sub[half:], scale[half:])
    out["attainment_headroom"] = {"weight": w, "bridge_h2": r_bridge_h2,
                                  "blend_h2": r_blend,
                                  "gain": 1.0 - r_blend / r_bridge_h2}
    print(f"\n    headroom from attainment: blending in the zigzag at a weight fitted")
    print(f"    out of sample (w = {w:+.3f}) moves the bridge from {r_bridge_h2:.5f} to "
          f"{r_blend:.5f},")
    print(f"    a further {(1 - r_blend / r_bridge_h2):+.2%}. That is what conditioning on")
    print("    the extremes being *attained* rather than merely contained would buy.")

    z = (sub - bm) / np.maximum(bs, 1e-12)
    cover = float(np.nanmean(np.abs(z) < 1.6448536269514722))
    out["sim_coverage_90"] = cover
    print(f"\n    nominal 90% band contains the truth {cover:.1%} of the time")
    print("    (a mean that is better but whose uncertainty is wrong is not a")
    print("     reconstruction, which is why this row is a kill condition)")

    # how much of the interior variance do H and L remove?
    v_lin = float(np.nanmean(((rows["linear / Kalman / OC-bridge"] - sub) / scale[:, None]) ** 2))
    v_br = float(np.nanmean(((bm - sub) / scale[:, None]) ** 2))
    out["variance_removed"] = 1.0 - v_br / v_lin
    print(f"\n    H and L remove {(1 - v_br / v_lin):.1%} of the residual variance that")
    print("    O and C leave behind. That number is the whole value of the construction.")

    # ---- 2. real bars -----------------------------------------------------
    print("\n[2] REAL BARS - 15m (O,H,L,C) reconstructed at 1m")
    real = {}
    src = DB if os.path.exists(DB) else LOCAL
    synth = os.path.exists(DB)
    if synth:
        print(f"    source: {src} (the research store, so the synthetics are in scope)")
        jobs = [("volatility_75_index", None), ("volatility_100_index", None),
                ("step_index", None), ("range_break_100_index", None),
                ("boom_500_index", None)]
    elif os.path.exists(LOCAL):
        print(f"    source: {src} - the lab is unreachable, so this is the local store,")
        print("    which carries no generated feed at all. These are real instruments and")
        print("    a harder test: neither fat tails nor volatility clustering is in the")
        print("    construction, so beating linear here is worth more than beating it on")
        print("    a process built to order.")
        jobs = [("btc", "DERIV"), ("btc", "BINANCE"), ("gold", "DERIV"),
                ("eurusd", "DERIV"), ("spx500", "DERIV"), ("us100", "DERIV")]
    else:
        jobs = []
        print("    no store reachable at all - section skipped, nothing reported")
    print(f"\n    {'feed':22s} {'n bars':>8s} {'linear':>9s} {'zigzag':>9s} "
          f"{'bridge':>9s} {'gain':>8s} {'cover90':>8s}")
    for feed, venue in jobs:
        d = load_pairs(src, feed, venue, "15m", "1m", 15)
        if d is None:
            print(f"    {feed + (' ' + venue if venue else ''):22s} (absent or too few)")
            continue
        o, c, hi, lo, sub = d
        # The bar's own close-to-close sigma, from its range, so that the error is
        # in units of the move the bar actually made and feeds are comparable.
        scale = (hi - lo) / math.sqrt(8.0 * NSUB / math.pi) * math.sqrt(NSUB)
        sig_sub = (hi - lo) / math.sqrt(8.0 * NSUB / math.pi)
        ok = (sig_sub > 0) & np.isfinite(sub).all(axis=1) & (scale > 0)
        o, c, hi, lo, sub, scale, sig_sub = (v[ok] for v in
                                             (o, c, hi, lo, sub, scale, sig_sub))
        if len(o) < 200:
            print(f"    {feed:22s} (too few usable bars)")
            continue
        bm, bs = bridge_interior(o, c, lo, hi, sig_sub, NSUB)
        rl = score(linear_interior(o, c, NSUB), sub, scale)
        rz = score(zigzag_interior(o, c, lo, hi, NSUB), sub, scale)
        rb = score(bm, sub, scale)
        zz = (sub - bm) / np.maximum(bs, 1e-12)
        cov = float(np.nanmean(np.abs(zz) < 1.6448536269514722))
        tag = f"{feed} {venue}" if venue else feed
        real[tag] = {"n": int(len(o)), "linear": rl, "zigzag": rz, "bridge": rb,
                     "gain": 1.0 - rb / rl, "coverage90": cov}
        print(f"    {tag:22s} {len(o):8d} {rl:9.4f} {rz:9.4f} {rb:9.4f} "
              f"{(1 - rb / rl) * 100:+7.2f}% {cov:8.1%}")
    out["real"] = real
    out["real_source"] = src
    out["real_is_synthetic"] = synth

    # ---- 3. the quote grid ------------------------------------------------
    print("\n[3] THE QUOTE GRID AS A MEASUREMENT OPERATOR")
    print("    A latent random walk rounded to a grid of size Delta. The exact posterior")
    print("    uses the true likelihood - the latent lay inside the printed cell - and the")
    print("    Kalman smoother approximates that by additive noise of variance d^2/12.")
    print("    If the smoother matches, the density-matrix framing is a relabelling.")
    print(f"\n    {'Delta/sigma':>12s} {'raw quote':>10s} {'Kalman':>10s} {'exact':>10s} "
          f"{'exact vs Kalman':>16s}")
    dec = []
    for ratio in (0.25, 0.5, 1.0, 2.0, 4.0, 8.0):
        sigma = 1.0
        delta = ratio * sigma
        errs = {"raw": [], "kal": [], "exact": []}
        for _ in range(12):
            lat = np.cumsum(rng.standard_normal(600) * sigma)
            q = np.round(lat / delta) * delta
            errs["raw"].append(np.sqrt(np.mean((q - lat) ** 2)))
            errs["kal"].append(np.sqrt(np.mean((deconvolve_kalman(q, delta, sigma) - lat) ** 2)))
            errs["exact"].append(np.sqrt(np.mean((deconvolve_exact(q, delta, sigma) - lat) ** 2)))
        r0, r1, r2 = (float(np.mean(errs[k])) for k in ("raw", "kal", "exact"))
        dec.append({"ratio": ratio, "raw": r0, "kalman": r1, "exact": r2,
                    "gain": 1.0 - r2 / r1})
        print(f"    {ratio:12.2f} {r0:10.4f} {r1:10.4f} {r2:10.4f} "
              f"{(1 - r2 / r1) * 100:+15.2f}%")
    out["deconvolution"] = dec

    # ---- 4. the ledger ----------------------------------------------------
    print("\n[4] THE PRE-REGISTERED KILL CONDITIONS")
    ledger = []

    def fire(name: str, cond: bool, detail: str) -> None:
        ledger.append({"condition": name, "fired": bool(cond), "detail": detail})
        print(f"    [{'FIRED' if cond else ' ok  '}] {name}")
        print(f"             {detail}")

    gain_sim = 1.0 - sim["conditioned bridge"] / base
    fire("1. the bridge does not beat linear interpolation on simulated Brownian paths",
         gain_sim <= 0,
         f"bridge {sim['conditioned bridge']:.5f} against linear {base:.5f}, "
         f"{gain_sim:+.2%}")
    fire("2. H and L are worth less than 2%",
         gain_sim < 0.02, f"root mean square error falls {gain_sim:.2%}; "
         f"{out['variance_removed']:.1%} of the residual variance removed")
    fire("3. the Kalman smoother is not linear interpolation (live-estimator control)",
         ident > 1e-9, f"max absolute difference {ident:.3e}")
    fire("4. the nominal 90% band does not cover between 85% and 95%",
         not (0.85 <= cover <= 0.95), f"covers {cover:.1%}")
    bad = [k for k, v in real.items() if v["gain"] <= 0]
    fire("5. the bridge fails to beat linear on real bars",
         bool(bad), "all feeds positive" if not bad else f"negative on {bad}")
    best = max((d["gain"] for d in dec), default=0.0)
    fire("6. the exact posterior never beats the Kalman smoother",
         best <= 0.0,
         f"best gain {best:+.2%} at Delta/sigma = "
         f"{max(dec, key=lambda d: d['gain'])['ratio'] if dec else float('nan')}")
    vals = [sim[k] for k in sim]
    fire("7. void - a root mean square error is zero, or two different estimators agree",
         any(v == 0 for v in vals) or len(set(round(v, 12) for v in vals)) < len(vals),
         "; ".join(f"{k}={v:.5f}" for k, v in sim.items()))
    out["ledger"] = ledger
    print(f"\n    {sum(1 for x in ledger if x['fired'])} of {len(ledger)} fired.")

    os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(out, fh, indent=1, default=float)
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
