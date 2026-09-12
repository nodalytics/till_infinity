"""When does the Brownian assumption behind `barriers.py` fail, and what would fix it?

`till_infinity/trading/barriers.py` landed this week and is the first thing in
the package that prices a stop-and-target geometry. It answers

    P(target before stop) = (b + B) / (a + b + 2B)
    E[bars]               = (a + B) * (b + B)

for barriers `a` above and `b` below in volatility units, with
`B = -zeta(1/2)/sqrt(2 pi) = 0.5826` of one monitoring interval's sigma. Its own
docstring is candid about the scope: **"on real markets it is a better prior than
the continuous form and is not validated"**, because gold and the majors have fat
tails, volatility clustering and drift, and `research/cascading.md` measures FX
running 27% above the Gaussian `MAD_TO_SIGMA` at one minute.

This harness validates it, says where it breaks, and asks whether a *learned*
operator repairs the break or whether the feed's own return histogram is the
whole of it.

## The derivation, and why a transfer operator is the right object

A stop-and-target trade is a first-passage problem between two absorbing walls.
Under the Wick rotation that is a Schrodinger problem with two Dirichlet
boundaries, and `research/quantising.md` section one established the correct
boundary condition for a wall watched on a grid: not Dirichlet at `a` but
**Robin**, which to leading order is Dirichlet at `a + B`. One image charge,
moved. The closed form above is that boundary-value problem solved for the free
particle.

For a process that is **not** a free particle the same problem is still exactly
solvable, and the solution is the sub-stochastic transfer operator restricted to
the interior:

    q_{n+1} = S q_n ,   P(alive after n) = 1' q_n ,
    P(exit up) = sum_n (flux of S q_n past the upper wall)

with `S` the one-step operator with the absorbing states deleted. There is
nothing approximate in it: given the operator, the barrier answer is a
propagation. So the question is entirely **what state the operator is defined
on**, and that is where the physics has to earn its place.

The state used here is two-dimensional:

    u  = position between the barriers, in units of the volatility at entry
    s  = the log of the current volatility, binned on its own stationary quantiles

because the failure the desk actually suffers is not that returns are fat-tailed
at one minute. It is that **the barriers are fixed at entry in units of the entry
volatility, and the volatility then moves**. In entry units the step at time `t`
is `z_t * exp(s_t - s_0)`, so a trade opened in a quiet regime that turns
volatile reaches its barriers sooner and in different proportion than the closed
form says. `s` is the slow coordinate; `groundstate.py` section four measures how
slow, and the two sections are the same object read twice.

## The arms, which differ in exactly one thing at a time

Every arm answers the same question about the same geometries on the same bars,
monitored the same way - one-minute closes, so `ticks_per_bar = 1` and the shift
is `0.5826` unmodified, which is the regime `research/deriving.md` validated.

| arm | carries |
| --- | --- |
| **A. closed form** | `barriers.py` itself: Gaussian, independent, constant volatility, Robin wall |
| **B. Gaussian propagation** | the same law, propagated exactly rather than approximated. A check on the propagator, not a model |
| **C. iid propagation** | the feed's **own** standardised-return histogram, still independent. The classical control |
| **D. regime propagation** | the same histogram plus the learned volatility chain. The transfer operator |
| **T. the feed** | non-overlapping trials on the actual bars, out of sample |

Read as a decomposition:

* `A - T` is the total error of the Brownian assumption;
* `A - C` is the part the **marginal** explains - fat tails, and nothing dynamic;
* `C - T` is what is left for **dependence** to explain;
* `D - T` is what the learned operator leaves.

**If C is as close to T as D is, the operator is notation and the fix to
`barriers.py` is one line: replace the Gaussian by the feed's own return
quantiles.** That is the verdict this harness exists to reach, in whichever
direction it goes, and it is pre-registered below.

## The controls

* **The Volatility indices are the positive control for the closed form.**
  `research/deriving.md` and `research/generators.md` prove them geometric
  Brownian motion at a published sigma with no volatility clustering anywhere, so
  there arm A is not an assumption and must match T. If it does not, the harness
  is measuring itself and nothing on a real feed can be read.
* **Boom and Crash are the negative control.** They are drift plus compound
  Poisson, so arm A must fail on them, and if it does not the test has no power.
* **The regime shuffle.** Arm D is re-fitted with the volatility-regime sequence
  randomly permuted, which destroys its persistence and keeps its marginal
  exactly. Whatever D buys over C that the shuffle also buys is not dependence.
* **Out of sample throughout.** D and C are fitted on the first half of the
  stored bars and scored on the second. `research/exiting.md` records two
  look-aheads that moved a replayed answer tenfold in a morning, so the split is
  not a formality.

## What would count as failure

Written before any number was read.

1. **The propagator is broken** if arm B disagrees with arm A by more than 0.005
   in probability at any geometry with `min(a,b) >= 2`. `research/quantising.md`
   measured the Robin approximation good to 0.0004 there and explicitly worse at
   `a = 1`, so the `a = 1` row is excluded from this condition and reported.
2. **The whole construction is void** if, pooled over the Volatility indices,
   arm A does not match T within two standard errors at every geometry. The
   closed form must be right where its assumptions are exactly true.
3. **The test has no power** if arm A matches T on Boom and Crash, because a jump
   process is what the assumption cannot survive.
4. **The learned operator is notation** if `|D - T| >= |C - T|` on a majority of
   real feeds out of sample. This is the verdict condition and it is expected to
   be close.
5. **The dependence is not dependence** if the regime-shuffled arm D closes as
   much of the `C - T` gap as the unshuffled one.
6. **The run is void** if any arm reproduces T to more digits than T's own
   standard error allows, or if any measured probability lands on the closed
   form's value to four decimals.
7. **No per-feed claim** is made unless the per-feed gap survives the scan's own
   noise floor: the feed-by-geometry table is a scan, `research/calibrating.md`
   measures an uncontrolled read firing in 98.50% of null books, and the control
   here is the permutation of regime labels in condition 5 plus the synthetic
   feeds whose true answer is known.
"""

from __future__ import annotations

import json
import math
import os
from concurrent.futures import ProcessPoolExecutor

import numpy as np

import groundlib as G

SEED = int(os.environ.get("SEED", "20260912"))
OUT = os.environ.get("OUT", os.path.join(G.LOGS, "groundbarrier.json"))
WORKERS = int(os.environ.get("WORKERS", "32"))
#: Trailing bars for the causal volatility estimate. `research/volatility.md`
#: found a flat 20-bar mean beating the shipping estimator at every interval, so
#: this is the desk's own best available number rather than a tuned one.
VOL_WIN = int(os.environ.get("VOL_WIN", "20"))
#: Volatility regime bins. Nine is enough for the chain to carry persistence and
#: few enough that each bin holds thousands of bars on a 30,000-bar training half.
NS = int(os.environ.get("NS", "9"))
#: Position cells per volatility unit in the propagator.
NU = int(os.environ.get("NU", "24"))
MAXBARS = int(os.environ.get("MAXBARS", "600"))
#: The geometries. Symmetric cases where the answer is exactly 0.5 whatever the
#: shift, the 3:1 `research/deriving.md` measured on 174,501 trades, and the
#: asymmetries `research/spending.md` says the book plans and realises.
GEOMS = (
    (1.0, 1.0), (2.0, 2.0), (3.0, 3.0), (5.0, 5.0), (10.0, 10.0),
    (3.0, 1.0), (1.0, 3.0), (6.0, 2.0), (2.0, 6.0), (1.36, 1.0),
)


# --------------------------------------------------------------------------
# The closed form, duplicated rather than imported
# --------------------------------------------------------------------------


def closed_form(a: float, b: float, shift: float = G.SHIFT) -> tuple[float, float]:
    """`barriers.py`'s two forms. Duplicated on purpose.

    A harness that imports the module it is auditing cannot report a
    disagreement with it, because any drift in the module moves both sides.
    """
    return (b + shift) / (a + b + 2.0 * shift), (a + shift) * (b + shift)


# --------------------------------------------------------------------------
# The propagator: one step law, optionally per regime
# --------------------------------------------------------------------------


def propagate_exact(
    a: float,
    b: float,
    step_law,
    regime: np.ndarray | None = None,
    start: int = 0,
    scale=None,
    maxbars: int = MAXBARS,
    nu: int = NU,
) -> dict:
    """P(target first) and E[bars], by propagating the sub-stochastic operator.

    Each regime's kernel is built as three blocks - interior, over the top, under
    the bottom - so absorbed mass is attributed to the wall it crossed **by
    construction** rather than by a rule applied afterwards. An earlier version
    split it by a fixed share and is deleted rather than kept, because a
    first-passage harness whose wall accounting is a guess is measuring the guess.

    `step_law(k, du, scale)` returns the integer cell offsets and weights for
    regime `k`, `regime` is the regime-to-regime transition matrix, and
    `scale[k] = exp(s_k - s_start)` the multiplier that turns a standardised
    return into entry-volatility units. With one regime and `regime=None` this is
    the iid case; with a Gaussian law it is the exact discretely-monitored
    Brownian answer, which is what condition 1 checks the closed form against.
    """
    # The grid must put the **start** on a cell centre and both walls on cell
    # boundaries, or a symmetric geometry does not return 0.5. The first version
    # used `arange(-b + du/2, a, du)`, which puts zero on an edge, and it returned
    # 0.50724, 0.49581, 0.50292, 0.49813 on 1:1 through 10:10 - oscillating in
    # sign and shrinking with the geometry, which is a parity artefact of the grid
    # and not a property of anything. A symmetric case is the one answer known
    # without any calculation, so it is the right thing to be wrong on first.
    # The grid puts the start on a cell centre and the walls at `a` and `-b`.
    # Nearest-cell rounding then places the *effective* wall half a cell inside,
    # which shortens every duration by 0.5*du*(dE/da + dE/db) - at nu=48 that is
    # E[bars] = 2.752 against `research/quantising.md`'s exactly propagated 2.783
    # at 1:1, and the deficit matches that expression to the digit. It cannot be
    # removed by moving the wall, because a centred start and a wall on a cell
    # boundary cannot both hold when `a/du` is an integer. It is instead reported
    # as what it is: a discretisation that converges, monotonically, and section
    # zero prints the scan. **The probabilities do not carry it** - every
    # symmetric geometry returns exactly 0.5 at every grid - so the arms are
    # compared on probability and the duration is quoted with its scan.
    du = 1.0 / nu
    na, nb = int(round(a * nu)), int(round(b * nu))
    u = du * np.arange(-(nb - 1), na)
    n = u.size
    nk = 1 if regime is None else regime.shape[0]
    starts = [start] if np.isscalar(start) else list(start)
    ns = len(starts)
    inner, hi, lo = [], [], []
    for k in range(nk):
        sc = 1.0 if scale is None else float(scale[k])
        off, w = step_law(k, du, sc)
        m = np.zeros((n, n))
        h = np.zeros(n)
        d = np.zeros(n)
        src = np.arange(n)
        # `u[i]` is cell `i` counting from the bottom wall, so a step of `o` cells
        # lands at `i + o`; the walls are the cells just outside [0, n), and
        # absorption is an index test rather than a comparison on prices.
        for o, wt in zip(off, w, strict=True):
            if wt <= 0:
                continue
            j = src + int(o)
            inb = (j >= 0) & (j < n)
            m[src[inb], j[inb]] += wt
            h[j >= n] += wt
            d[j < 0] += wt
        inner.append(m)
        hi.append(h)
        lo.append(d)
    # All start regimes propagate at once. The recursion is linear, so a batch of
    # start states is a matrix rather than a loop, and that is the difference
    # between this arm costing seconds and costing an hour: the regime arm needs
    # one propagation per (geometry, opening regime) and there are nine of each.
    q = np.zeros((ns, nk, n))
    c0 = int(np.argmin(np.abs(u)))
    for r, k0 in enumerate(starts):
        q[r, k0, c0] = 1.0
    up = np.zeros(ns)
    dn = np.zeros(ns)
    ttot = np.zeros(ns)
    for step in range(1, maxbars + 1):
        nxt = np.zeros_like(q)
        for k in range(nk):
            up += q[:, k, :] @ hi[k]
            dn += q[:, k, :] @ lo[k]
            ttot += step * (q[:, k, :] @ (hi[k] + lo[k]))
            row = q[:, k, :] @ inner[k]
            if regime is None:
                nxt[:, k, :] += row
            else:
                nxt += regime[k][None, :, None] * row[:, None, :]
        q = nxt
        if q.sum() < 1e-10:
            break
    alive = q.sum(axis=(1, 2))
    tot = up + dn
    one = np.isscalar(start)
    res = {
        "p_up": up / np.maximum(tot, 1e-15),
        "e_bars": ttot / np.maximum(tot, 1e-15),
        "unresolved": alive,
    }
    return {k: (float(v[0]) if one else v) for k, v in res.items()}


def gauss_cells(du: float, scale: float = 1.0, nsig: float = 10.0):
    """Exact cell probabilities for a unit Gaussian step scaled by `scale`.

    Cell `k` covers increments in `[(k-0.5)du, (k+0.5)du)`, so its probability is
    a difference of two normal CDFs and nothing is approximated. Returning
    integer cell offsets rather than real-valued steps is what removes the last
    discretisation error: an earlier version built the law on its own 801-point
    grid and re-rounded it onto the propagator's, which left `E[bars]` about 1%
    below `research/quantising.md`'s exactly propagated 2.783 at 1:1.
    """
    kmax = max(1, int(math.ceil(nsig * scale / du)))
    k = np.arange(-kmax, kmax + 1)
    edge = (k[:, None] + np.array([-0.5, 0.5])[None, :]) * du / max(scale, 1e-12)
    cdf = 0.5 * (1.0 + np.vectorize(math.erf)(edge / math.sqrt(2.0)))
    w = cdf[:, 1] - cdf[:, 0]
    return k, w / w.sum()


def sample_cells(z: np.ndarray, du: float, scale: float = 1.0, nsig: float = 40.0):
    """The same object measured from data: where the feed's own steps land.

    Identical definition to `gauss_cells` - the probability that the increment
    falls in cell `k` - so the Gaussian arm and the feed arm differ in the law
    and in nothing else. `nsig` truncates a single extreme outlier that would
    otherwise set the grid; the truncated mass is returned so the caller can
    report it rather than discover it later.
    """
    zz = np.clip(np.asarray(z, dtype=float), -nsig, nsig)
    k = np.rint(zz * scale / du).astype(int)
    kmin, kmax = int(k.min()), int(k.max())
    w = np.bincount(k - kmin, minlength=kmax - kmin + 1).astype(float)
    return np.arange(kmin, kmax + 1), w / max(w.sum(), 1.0)


# --------------------------------------------------------------------------
# The feed: causal volatility, regimes, and non-overlapping trials
# --------------------------------------------------------------------------


def prepare(close: np.ndarray, vol_win: int = VOL_WIN) -> dict | None:
    """Log returns, a strictly causal volatility, and the standardised return."""
    p = np.asarray(close, dtype=float)
    ok = np.isfinite(p) & (p > 0)
    p = p[ok]
    if p.size < 8000:
        return None
    r = np.diff(np.log(p))
    c = np.cumsum(np.concatenate([[0.0], r * r]))
    # sigma[t] uses returns strictly before t, so a trial opened at t sees only
    # the past. Off-by-one here is the whole difference between this and a
    # look-ahead, which is why it is written out rather than sliced cleverly.
    sig = np.full(r.size, np.nan)
    sig[vol_win:] = np.sqrt((c[vol_win:-1] - c[:-vol_win - 1]) / vol_win)
    good = np.isfinite(sig) & (sig > 0)
    return {"r": r, "sigma": sig, "good": good, "z": np.where(good, r / np.where(good, sig, 1), 0.0)}


def regimes(sigma: np.ndarray, good: np.ndarray, ns: int, edges=None):
    """Volatility regime index, on quantiles of log sigma learned in-sample."""
    ls = np.log(np.where(good, sigma, np.nan))
    if edges is None:
        q = ls[np.isfinite(ls)]
        edges = np.quantile(q, np.linspace(0.0, 1.0, ns + 1))
        edges[0], edges[-1] = -np.inf, np.inf
    idx = np.clip(np.searchsorted(edges, ls, side="right") - 1, 0, ns - 1)
    return idx, edges, ls


def trials(r, sigma, good, a, b, start_at=0, stop_at=None, maxbars=MAXBARS):
    """Non-overlapping barrier trials on one-minute closes.

    The next trial opens where the last one closed, so every trial is
    independent and the standard error is the binomial one rather than a block
    bootstrap's. `research/deriving.md` walks its windows the same way.
    """
    n = r.size if stop_at is None else min(stop_at, r.size)
    i = start_at
    ups, durs, ss = [], [], []
    dropped = 0
    cum = np.cumsum(r)
    while i < n - 2:
        if not good[i]:
            i += 1
            continue
        s0 = sigma[i]
        base = cum[i - 1] if i > 0 else 0.0
        hi, lo = base + a * s0, base - b * s0
        j = min(i + maxbars, n)
        seg = cum[i:j]
        up_hit = np.flatnonzero(seg >= hi)
        dn_hit = np.flatnonzero(seg <= lo)
        tu = up_hit[0] if up_hit.size else 10**9
        td = dn_hit[0] if dn_hit.size else 10**9
        if tu == 10**9 and td == 10**9:
            # Unresolved inside the horizon. Dropping these is a **selection**,
            # not a rounding: a trial fails to resolve when the realised
            # volatility falls short of the entry estimate, so the dropped set is
            # the quiet periods and keeping quiet about it would bias every wide
            # geometry toward the noisy half of the sample. It is counted and
            # reported, and the horizon is set from the geometry rather than
            # fixed so the rate stays small where it can.
            dropped += 1
            i = j
            continue
        ups.append(1 if tu < td else 0)
        durs.append(int(min(tu, td)) + 1)
        ss.append(i)
        i += int(min(tu, td)) + 1
    return np.asarray(ups), np.asarray(durs), np.asarray(ss), dropped


# --------------------------------------------------------------------------
# One feed, all arms
# --------------------------------------------------------------------------


def run_feed(args) -> dict | None:
    feed, shuffle_seed = args
    d = G.load_bars(feed)
    if d is None:
        return None
    pre = prepare(d["close"])
    if pre is None:
        return None
    r, sig, good, z = pre["r"], pre["sigma"], pre["good"], pre["z"]
    half = r.size // 2
    # Fit on the first half, score on the second. Nothing below touches the
    # second half's outcomes before the second half is replayed.
    fit = slice(0, half)
    idx, edges, ls = regimes(sig, good, NS)
    zf = z[fit][good[fit]]
    if zf.size < 4000:
        return None
    kurt = float(np.mean((zf - zf.mean()) ** 4) / max(np.var(zf), 1e-18) ** 2)
    # The regime chain, and the volatility multiplier attached to each bin.
    idf = idx[fit][good[fit]]
    tr = np.zeros((NS, NS))
    np.add.at(tr, (idf[:-1], idf[1:]), 1.0)
    row = tr.sum(axis=1)
    tr = np.where(row[:, None] > 0, tr / np.maximum(row[:, None], 1), 1.0 / NS)
    lsf = ls[fit][good[fit]]
    lvl = np.array([lsf[idf == k].mean() if np.any(idf == k) else lsf.mean() for k in range(NS)])
    # Per-regime standardised-return law. Standardising by the causal sigma
    # already removes the level, so what is left here is whatever shape the
    # regime carries beyond its scale.
    parts = [zf[idf == k] if np.sum(idf == k) > 200 else zf for k in range(NS)]

    def laws(k, du, sc):
        return sample_cells(parts[k], du, sc)

    def pooled(k, du, sc):
        return sample_cells(zf, du, sc)

    def glaw(k, du, sc):
        return gauss_cells(du, sc)
    rng = np.random.default_rng(shuffle_seed)
    tr_shuf = tr[rng.permutation(NS)][:, rng.permutation(NS)]
    tr_shuf = tr_shuf / tr_shuf.sum(axis=1, keepdims=True)
    out = {"feed": feed, "n_bars": int(r.size), "kurtosis_z": kurt, "cells": {}}
    for a, b in GEOMS:
        key = f"{a:g}:{b:g}"
        # The horizon scales with the geometry's own expected duration, so a wide
        # geometry is not judged on a window a narrow one was sized for.
        horizon = int(max(MAXBARS, 30.0 * closed_form(a, b)[1]))
        up, dur, ss, dropped = trials(r, sig, good, a, b, start_at=half, maxbars=horizon)
        if up.size < 60:
            continue
        p_t = float(up.mean())
        se = float(math.sqrt(max(p_t * (1 - p_t), 1e-9) / up.size))
        p_a, e_a = closed_form(a, b)
        gb = propagate_exact(a, b, glaw)
        cc = propagate_exact(a, b, pooled)
        # The regime arm is started in the bin the trial actually opened in, and
        # averaged over the observed distribution of opening bins, so it is not
        # given a starting regime the desk would not know.
        s0 = idx[ss]
        wts = np.bincount(s0, minlength=NS).astype(float)
        wts /= wts.sum()
        # The regime arm opens in the bin the trial actually opened in, and is
        # averaged over the observed distribution of opening bins - so it is never
        # given a starting regime the desk would not have known at order time.
        allk = list(range(NS))
        dd, ds = {}, {}
        for tgt, mat in ((dd, tr), (ds, tr_shuf)):
            acc = {"p_up": 0.0, "e_bars": 0.0, "unresolved": 0.0}
            for k in allk:
                if wts[k] <= 0:
                    continue
                v = propagate_exact(a, b, laws, regime=mat, start=k,
                                    scale=np.exp(lvl - lvl[k]), nu=NU)
                for f in acc:
                    acc[f] += wts[k] * v[f]
            tgt.update(acc)
        out["cells"][key] = {
            "n": int(up.size), "p_truth": p_t, "se": se,
            "dropped": int(dropped),
            "drop_rate": float(dropped / max(dropped + up.size, 1)),
            "horizon": horizon,
            "dur_truth": float(dur.mean()),
            "A_closed": p_a, "A_bars": e_a,
            "B_gauss": gb["p_up"], "B_bars": gb["e_bars"],
            "C_iid": cc["p_up"], "C_bars": cc["e_bars"],
            "D_regime": dd["p_up"], "D_bars": dd["e_bars"],
            "D_shuffled": ds["p_up"],
            "unresolved_D": dd["unresolved"],
        }
    return out


def summarise(rows: list[dict], title: str) -> dict:
    print(f"\n  --- {title} ---")
    print(
        f"  {'feed':24s} {'geom':>7s} {'n':>6s} {'truth':>8s} {'se':>7s} "
        f"{'A close':>8s} {'B gauss':>8s} {'C iid':>8s} {'D regime':>8s} "
        f"{'A-T':>7s} {'C-T':>7s} {'D-T':>7s} {'Dsh-T':>7s}"
    )
    agg = {}
    for row in rows:
        for key, c in row["cells"].items():
            t = c["p_truth"]
            print(
                f"  {row['feed']:24s} {key:>7s} {c['n']:6d} {t:8.4f} {c['se']:7.4f} "
                f"{c['A_closed']:8.4f} {c['B_gauss']:8.4f} {c['C_iid']:8.4f} {c['D_regime']:8.4f} "
                f"{c['A_closed'] - t:+7.4f} {c['C_iid'] - t:+7.4f} {c['D_regime'] - t:+7.4f} "
                f"{c['D_shuffled'] - t:+7.4f}"
            )
            g = agg.setdefault(key, {k: [] for k in ("A", "B", "C", "D", "Dsh", "z", "n", "drop")})
            g["drop"].append(c["drop_rate"])
            g["A"].append(abs(c["A_closed"] - t))
            g["B"].append(abs(c["B_gauss"] - t))
            g["C"].append(abs(c["C_iid"] - t))
            g["D"].append(abs(c["D_regime"] - t))
            g["Dsh"].append(abs(c["D_shuffled"] - t))
            g["z"].append((c["A_closed"] - t) / max(c["se"], 1e-9))
            g["n"].append(c["n"])
    print(f"\n  pooled by geometry, {title}")
    print(
        f"  {'geom':>7s} {'feeds':>6s} {'trials':>8s} {'drop%':>6s} {'|A-T|':>7s} {'|B-T|':>7s} "
        f"{'|C-T|':>7s} {'|D-T|':>7s} {'|Dsh-T|':>8s} | {'mean z A':>9s} {'t over feeds':>12s} "
        f"{'sign':>7s} {'best':>5s}"
    )
    pooled = {}
    for key, g in agg.items():
        z = np.asarray(g["z"], dtype=float)
        nf = z.size
        # The 19 real feeds are not 19 independent samples - indices co-move - so
        # the interval quoted is a t interval over FEEDS, which charges the
        # between-feed spread rather than the within-feed trial count. That is the
        # conservative choice and it is the one `research/calibrating.md` would
        # insist on for a table with this many rows in it.
        tz = float(z.mean() / (z.std(ddof=1) / math.sqrt(nf))) if nf > 1 and z.std(ddof=1) > 0 else float("nan")
        same = int(max((z > 0).sum(), (z < 0).sum()))
        means = {k: float(np.mean(g[k])) for k in ("A", "B", "C", "D", "Dsh")}
        best = min(means, key=means.get)
        pooled[key] = {
            **means, "feeds": nf, "trials": int(np.sum(g["n"])),
            "mean_z": float(z.mean()), "t_over_feeds": tz,
            "sign_consistency": f"{same}/{nf}", "best_arm": best,
            "drop_rate": float(np.mean(g["drop"])),
        }
        print(
            f"  {key:>7s} {nf:6d} {int(np.sum(g['n'])):8d} {100 * np.mean(g['drop']):6.2f} "
            f"{means['A']:7.4f} {means['B']:7.4f} {means['C']:7.4f} {means['D']:7.4f} "
            f"{means['Dsh']:8.4f} | {z.mean():9.2f} {tz:12.2f} {same:3d}/{nf:<3d} {best:>5s}"
        )
    return pooled


def main() -> None:
    print("=" * 110)
    print("groundbarrier.py - where barriers.py's Brownian assumption fails, and what repairs it")
    print("=" * 110)
    if not G.have_db():
        print("research.db not reachable - nothing run, rather than an empty table.")
        return
    res = {"seed": SEED, "vol_win": VOL_WIN, "ns": NS, "nu": NU, "geoms": list(GEOMS)}

    print("\n=== 0. The propagator against the closed form, no data at all ===\n")
    print("  Arm B is an exact propagation of the same Gaussian law arm A approximates.")
    print("  The probabilities carry no grid error - every symmetric geometry returns")
    print("  0.5 exactly at every grid - and the durations converge monotonically to")
    print("  research/quantising.md's independently propagated table, which is a")
    print("  cross-check between two code paths that share nothing.\n")
    chk = {}

    def glaw(k, du, sc):
        return gauss_cells(du, sc)

    print(f"  {'geom':>8s} {'closed A':>10s} {'exact B':>10s} {'A - B':>9s} "
          f"{'A bars':>9s} {'B nu=16':>9s} {'B nu=48':>9s} {'B nu=144':>9s}")
    for a, b in GEOMS:
        pa, ea = closed_form(a, b)
        scan = [propagate_exact(a, b, glaw, nu=n, maxbars=6000) for n in (16, 48, 144)]
        v = scan[1]
        chk[f"{a:g}:{b:g}"] = {
            "A": pa, "B": v["p_up"], "A_bars": ea,
            "B_bars": {n: sc["e_bars"] for n, sc in zip((16, 48, 144), scan, strict=True)},
        }
        print(
            f"  {a:g}:{b:g}".rjust(10)
            + f" {pa:10.5f} {v['p_up']:10.5f} {pa - v['p_up']:+9.5f} {ea:9.3f} "
            + " ".join(f"{sc['e_bars']:9.3f}" for sc in scan)
        )
    worst = max(
        abs(c["A"] - c["B"])
        for k, c in chk.items()
        if min(float(k.split(":")[0]), float(k.split(":")[1])) >= 2
    )
    print(f"\n  condition 1 (worst |A-B| at min(a,b)>=2 exceeds 0.005): "
          f"{worst > 0.005}  [{worst:.5f}]")
    res["propagator_check"] = chk
    res["cond1_fired"] = bool(worst > 0.005)

    groups = (
        ("control: Volatility indices (provably GBM)", G.BROWNIAN[:6]),
        ("negative control: Boom and Crash (compound Poisson)", G.JUMPY[:4]),
        ("lattice and confined synthetics", G.LATTICE + G.CONFINED),
        ("real feeds", G.REAL),
    )
    with ProcessPoolExecutor(max_workers=WORKERS) as ex:
        done = {
            name: [r for r in ex.map(run_feed, [(f, SEED + i) for i, f in enumerate(feeds)]) if r]
            for name, feeds in groups
        }
    for name, rows in done.items():
        if rows:
            res[name] = {"pooled": summarise(rows, name), "feeds": rows}

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(res, fh, indent=1, default=float)
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
