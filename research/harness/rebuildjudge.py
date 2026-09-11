"""Can anything tell the rebuild from the feed, and is the venue's randomness sound?

This is the strong form of the question `rebuildvol.py`, `rebuildstep.py` and
`rebuildspike.py` ask weakly. Those pages check whether a list of statistics
agrees. Many wrong processes agree on a list of statistics. The operational
definition of replication is that **nobody can tell which feed is which**, so the
primary criterion here is adversarial: train the best classifier this environment
can carry to separate real Deriv ticks from rebuilt ones, and read its held-out
AUC.

An AUC means nothing on its own. It is read against **the same pipeline run on
real against real** - two disjoint halves of the genuine feed - which is the
score "indistinguishable" actually earns on this data rather than the 0.5 one
might assume. A discriminator that cannot beat that floor is the strongest
statement available that the rebuild is the process. A discriminator that beats
it is more useful still, because the features it leans on are a map of exactly
what the specification is missing.

The second half of the page is a different question with the same apparatus.
These feeds come out of a seeded random number generator and the venue makes
audit claims about it. So the increment stream is uniformised and put through the
standard batteries - serial correlation at many lags, k-tuple lattice structure
and the spectral idea behind it, chi-square on 2-, 3- and 4-dimensional tuple
grids, the gap test, overlapping permutations, monobit and runs on the bit
stream. A sound generator passes all of
them and that is a clean closed question worth having on the record. A generator
whose k-tuples lie on a small number of hyperplanes is a linear congruential
source, which would be a finding about the product and about counterparty risk
rather than about a trading rule, and is reported as such either way.

## What would count as failure, written before any number was looked at

1. **The rebuild is caught** if the discriminator's held-out AUC on
   real-against-rebuilt is above the real-against-real floor by more than the
   floor's own 95% bootstrap interval, on any family and any arm. This is the
   headline and it is the condition the whole page turns on.
2. **The study is void** if the discriminator has no power: it is run against
   four deliberately wrong generators (sigma +2%, Student-t(6) tick
   innovations, half the publication rate, and a two-state volatility) and must
   separate at least three of the four. A classifier that cannot see a
   generator known to be wrong says nothing about one that might be right.
3. **The study is void** if an AUC lands on *exactly* 0.5000, or if the floor
   arm returns exactly the same number as the test arm. Both are the signature
   of a constant column, which this folder has published twice.
4. **The timing arm is expected to be caught and is not a failure.** Tick
   inter-arrival times in `research.db` are our own collector's receive clock
   (`lagging.md`), not the venue's publication clock, so a discriminator handed
   durations is reading our network. It is run, reported separately, and
   excluded from the headline.
5. **The randomness claim fails** if the uniformised increment stream fails any
   battery that `numpy`'s PCG64 passes on the same sample size - serial
   correlation outside the band at more than the expected count of lags, a
   k-tuple grid chi-square below p = 0.001 in any of 2, 3 or 4 dimensions, or a
   lattice gap more than 3x what the same number of genuine uniforms produces.
6. **The randomness battery is void** if the positive control passes: RANDU
   (`x <- 65539 x mod 2^31`), the textbook bad generator whose 3-tuples lie on
   fifteen planes, must fail the lattice test on this sample size. If it does
   not, the test has no resolution and the Deriv result is not evidence.

## What the sample can and cannot support, said in advance

Twenty-four hours of ticks is 43,000 to 86,400 draws a feed and about a million
pooled across the Volatility family. That is four orders of magnitude short of
what TestU01's SmallCrush wants. So a *pass* here excludes a grossly broken
source - a short period, a visible lattice, a stuck bit - and does not certify a
cryptographic one. The quote grid quantises every draw as well, and the number of
distinct increment values a feed carries is printed beside each result as the
resolution bound.
"""

from __future__ import annotations

import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rebuildgen as G
import rebuildspike as K
import rebuildstep as S
import rebuildvol as V

OUT = os.environ.get("OUT", os.path.expanduser("~/till_infinity/logs/rebuildjudge.json"))
SEED = int(os.environ.get("SEED", "20260912"))
#: Window length in ticks for the summary arm, and the tuple length for the raw
#: arm. The tuple arm tests the joint law of consecutive increments directly;
#: the window arm tests everything a summary statistic could see.
W_TICK = int(os.environ.get("W_TICK", "60"))
W_BAR = int(os.environ.get("W_BAR", "30"))
KTUP = int(os.environ.get("KTUP", "8"))
TREES = int(os.environ.get("TREES", "120"))
MAXROW = int(os.environ.get("MAXROW", "60000"))
#: Lattice points per per-tick sigma. A feed quoted coarser than its own tick
#: sigma has almost all its information in the rounding, and pooling it with the
#: rest hands the discriminator a quantisation artefact instead of a law -
#: `twins.md` section 6 already quarantined two feeds for exactly this. Feeds
#: below the threshold are run in their own arm and reported separately.
RESOLUTION_MIN = float(os.environ.get("RESOLUTION_MIN", "8"))

VOL = {f: v for f, v in V.NOMINAL.items()}


# --------------------------------------------------------------- features ----
def _acf(x: np.ndarray, lag: int) -> np.ndarray:
    a = x - x.mean(axis=1, keepdims=True)
    num = (a[:, :-lag] * a[:, lag:]).sum(axis=1)
    den = (a * a).sum(axis=1)
    return np.where(den > 0, num / np.maximum(den, 1e-300), 0.0)


def tick_window_features(inc: np.ndarray, w: int) -> tuple[np.ndarray, list[str]]:
    """Everything a summary statistic could see in `w` consecutive increments."""
    k = inc.size // w
    if k < 50:
        return np.empty((0, 0)), []
    m = inc[: k * w].reshape(k, w)
    a = np.abs(m)
    mu = m.mean(axis=1)
    sd = m.std(axis=1) + 1e-12
    z = np.clip((m - mu[:, None]) / sd[:, None], -50.0, 50.0)
    cs = np.cumsum(m, axis=1)
    med = np.median(a, axis=1) + 1e-12
    srt = np.sort(a, axis=1)
    sgn = np.sign(m)
    flips = (sgn[:, 1:] != sgn[:, :-1]).sum(axis=1)
    cols = {
        "mean": mu, "sd": sd, "skew": (z ** 3).mean(axis=1), "kurt": (z ** 4).mean(axis=1),
        "sum": m.sum(axis=1), "min": m.min(axis=1), "max": m.max(axis=1),
        "path_range": cs.max(axis=1) - cs.min(axis=1),
        "rs": (cs.max(axis=1) - cs.min(axis=1)) / (sd * math.sqrt(w)),
        "frac_up": (m > 0).mean(axis=1), "frac_zero": (m == 0).mean(axis=1),
        "sign_flips": flips / (w - 1),
        "mad_over_sd": a.mean(axis=1) / sd,
        "sd_over_1": sd,
        "n_distinct": (1 + (np.diff(np.sort(np.round(a, 12), axis=1),
                                    axis=1) != 0).sum(axis=1)) / w,
        "max_over_med": srt[:, -1] / med,
        "top3_share": srt[:, -3:].sum(axis=1) / (a.sum(axis=1) + 1e-300),
        "n_gt3": (a > 3 * med[:, None]).sum(axis=1),
        "n_gt10": (a > 10 * med[:, None]).sum(axis=1),
        "acf1": _acf(m, 1), "acf2": _acf(m, 2), "acf5": _acf(m, 5),
        "absacf1": _acf(a, 1), "absacf2": _acf(a, 2), "absacf5": _acf(a, 5),
        "signacf1": _acf(sgn, 1),
    }
    for q in (10, 25, 50, 75, 90, 99):
        cols[f"absq{q}"] = np.percentile(a, q, axis=1)
    names = list(cols)
    return np.column_stack([cols[n] for n in names]), names


def ktuple_features(inc: np.ndarray, k: int) -> tuple[np.ndarray, list[str]]:
    """Rows of `k` consecutive increments, raw. The joint law, undigested."""
    n = inc.size // k
    if n < 200:
        return np.empty((0, 0)), []
    m = inc[: n * k].reshape(n, k)
    extra = np.column_stack([np.abs(m).max(axis=1), m.sum(axis=1),
                             (m > 0).sum(axis=1)])
    names = [f"x{i}" for i in range(k)] + ["absmax", "sum", "nup"]
    return np.hstack([m, extra]), names


def bar_window_features(o, h, lo_, c, w: int) -> tuple[np.ndarray, list[str]]:
    k = c.size // w
    if k < 50:
        return np.empty((0, 0)), []
    cut = k * w
    o, h, lo_, c = o[:cut].reshape(k, w), h[:cut].reshape(k, w), \
        lo_[:cut].reshape(k, w), c[:cut].reshape(k, w)
    rng_ = h - lo_
    body = np.abs(c - o)
    r = np.diff(np.log(np.maximum(c, 1e-300)), axis=1)
    if r.shape[1] % 2:
        r = r[:, :-1]
    sd = r.std(axis=1) + 1e-12
    zr = np.clip((r - r.mean(axis=1, keepdims=True)) / sd[:, None], -50.0, 50.0)
    park = np.sqrt((np.log(np.maximum(h, 1e-300) / np.maximum(lo_, 1e-300)) ** 2).mean(axis=1)
                   / (4 * math.log(2)))
    park = np.nan_to_num(park)
    pos = np.where(rng_ > 0, (c - lo_) / np.maximum(rng_, 1e-300), 0.5)
    cols = {
        "bar_sd": sd, "bar_kurt": (zr ** 4).mean(axis=1),
        "park_over_close": park / sd,
        "range_over_body": (rng_ / np.maximum(body, 1e-300)).mean(axis=1),
        "close_pos": pos.mean(axis=1), "close_pos_sd": pos.std(axis=1),
        "upper_share": ((h - np.maximum(o, c)) / np.maximum(rng_, 1e-300)).mean(axis=1),
        "range_mean": rng_.mean(axis=1) / np.maximum(
            sd * np.maximum(c.mean(axis=1), 1e-300), 1e-300),
        "range_max_over_med": rng_.max(axis=1) / np.maximum(np.median(rng_, axis=1), 1e-300),
        "bar_acf1": _acf(r, 1), "bar_absacf1": _acf(np.abs(r), 1),
        "bar_vr2": ((r[:, ::2] + r[:, 1::2]).var(axis=1)
                    / np.maximum(2 * r.var(axis=1), 1e-300)),
    }
    names = list(cols)
    return np.column_stack([cols[n] for n in names]), names


# ------------------------------------------------------------ RNG batteries --
def to_uniform(inc: np.ndarray, rng) -> np.ndarray:
    """Rank-transform the increments to uniforms, ties broken at random.

    The alternative - pushing the increments through an assumed Gaussian CDF -
    conflates two questions. A Jump index's marginal is a mixture, so `Phi(x/s)`
    is not uniform and every uniformity test fails for a reason that is about the
    marginal rather than about the source; and a quantised quote puts an atom on
    every lattice point. The rank transform makes the marginal exactly uniform by
    construction and leaves only the **dependence** structure, which is what an
    RNG battery is actually asking about. The marginal is tested to death
    elsewhere on this page.
    """
    n = inc.size
    jitter = inc.astype(float) + rng.random(n) * 1e-12 * (np.abs(inc).max() + 1.0)
    order = np.argsort(jitter, kind="mergesort")
    u = np.empty(n)
    u[order] = (np.arange(n) + 0.5) / n
    return u


def serial_battery(u: np.ndarray, lags: int = 50) -> dict:
    n = u.size
    band = 2.0 / math.sqrt(n)
    vals = [G.acf(u, lag) for lag in range(1, lags + 1)]
    out = [v for v in vals if abs(v) > band]
    return {"n": n, "band": band, "n_outside": len(out), "expected": 0.0455 * lags,
            "max_abs": float(max(abs(v) for v in vals)),
            "worst_lag": int(np.argmax(np.abs(vals)) + 1)}


def grid_chi2(u: np.ndarray, k: int, m: int) -> dict:
    """Chi-square on an m^k grid of non-overlapping k-tuples of uniforms."""
    from scipy.stats import chi2 as chi2d
    n = u.size // k
    if n < 5 * (m ** k):
        return {"k": k, "m": m, "n": n, "p": float("nan"), "skipped": "too few tuples"}
    t = np.minimum((u[: n * k].reshape(n, k) * m).astype(np.int64), m - 1)
    idx = np.zeros(n, dtype=np.int64)
    for j in range(k):
        idx = idx * m + t[:, j]
    cnt = np.bincount(idx, minlength=m ** k).astype(float)
    exp = n / (m ** k)
    stat = float(((cnt - exp) ** 2 / exp).sum())
    df = m ** k - 1
    return {"k": k, "m": m, "n": n, "chi2": stat, "df": df,
            "p": float(chi2d.sf(stat, df)), "empty_cells": int((cnt == 0).sum())}


def lattice_gap(u: np.ndarray, k: int, amax: int = 6, cap: int = 30_000) -> dict:
    """The spectral idea, done empirically: project k-tuples onto integer
    directions and look for an empty band.

    A linear congruential generator's k-tuples lie on a family of parallel
    hyperplanes, so for the right integer vector the projected values collapse
    onto a few points and the largest gap between consecutive projections is
    enormous. For genuine uniforms the largest of `n` gaps is about
    `ln(n)/n`, so the statistic reported is the observed maximum gap in those
    units - around 1 for a sound source, and orders of magnitude larger for a
    lattice.
    """
    n = u.size // k
    if n < 2000:
        return {"k": k, "skipped": "too few tuples"}
    t = u[: n * k].reshape(n, k)
    if n > cap:
        t = t[:cap]
        n = cap
    best = (0.0, None)
    exp_gap = math.log(n) / n
    for v in _int_vectors(k, amax):
        proj = np.mod(t @ np.array(v, dtype=float), 1.0)
        proj.sort()
        gaps = np.diff(proj)
        g = float(max(gaps.max(), proj[0] + 1.0 - proj[-1]))
        if g > best[0]:
            best = (g, v)
    return {"k": k, "n": n, "max_gap": best[0], "vector": best[1],
            "expected_gap": exp_gap, "ratio": best[0] / exp_gap}


def _int_vectors(k: int, amax: int):
    """Integer directions to project k-tuples onto.

    `amax` has to reach the coefficients of the generator's own recurrence or
    the lattice is invisible: RANDU satisfies `x_{n+2} = 6 x_{n+1} - 9 x_n`, so
    the vector that collapses its 3-tuples is (9, -6, 1) and a search over
    +-4 never sees it. The first version of this test searched +-4 and cleared
    RANDU, which is how the bound below was chosen.
    """
    from itertools import product
    from math import gcd
    for v in product(range(-amax, amax + 1), repeat=k):
        first = next((c for c in v if c != 0), 0)
        if first <= 0:
            continue
        g = 0
        for c in v:
            g = gcd(g, abs(c))
        if g != 1:
            continue
        yield v


#: **What is deliberately not in this battery.** Diehard's birthday spacings and
#: Knuth's collision test both read the *spacing* of the values rather than their
#: dependence, and neither can be calibrated here. The published quote is
#: quantised, so an increment stream of 80,000 draws carries at most that many
#: distinct values; birthday spacings needs a day count far larger than the cube
#: of the birthday count, and the collision test needs many more distinct values
#: than cells. Run anyway on the dry run they reported z = -334 and z = +120 on
#: *every* stream including numpy's own PCG64 - a test with no resolution rather
#: than a finding. The two functions below are kept because the calibration is
#: the useful part of the record, and neither appears in the results table.
def to_uniform_oos(x: np.ndarray) -> np.ndarray:
    """Uniformise the second half of a stream through the *first* half's
    empirical CDF.

    The within-sample rank transform is right for dependence tests and useless
    for anything that reads the spacing of the values: it forces the order
    statistics onto an exact lattice, which makes a collision test report a z of
    -334 on every stream including numpy's own. Fitting the transform on one half
    and applying it to the other leaves the spacing random, so the collision test
    means something again.
    """
    h = x.size // 2
    ref = np.sort(x[:h])
    return (np.searchsorted(ref, x[h:], side="left") + 0.5) / (h + 1.0)


def collision_test(u: np.ndarray) -> dict:
    """Knuth's collision test: drop `n` values into `n` cells and count the
    coincidences.

    This replaces Diehard's birthday spacings, which cannot be run on this data
    at all. The published quote is quantised, so the increment stream carries
    only tens of thousands of distinct values, and birthday spacings needs a day
    count far larger than the cube of the birthday count; run anyway on the dry
    run it reported a z of several hundred on *every* stream including numpy's
    own, which is a test with no resolution rather than a finding. The collision
    count is the same idea - short-range coincidences - at the resolution the
    data actually has.
    """
    n = u.size
    m = n
    cells = np.minimum((u * m).astype(np.int64), m - 1)
    occupied = int(np.unique(cells).size)
    collisions = n - occupied
    # E[occupied] = m(1 - (1 - 1/m)^n); for m = n this is m(1 - e^-1)
    exp_occ = m * (1.0 - (1.0 - 1.0 / m) ** n)
    exp_col = n - exp_occ
    # variance of the occupancy count, standard occupancy-problem result
    p1 = (1.0 - 1.0 / m) ** n
    p2 = (1.0 - 2.0 / m) ** n
    var = m * p1 * (1 - p1) + m * (m - 1) * (p2 - p1 * p1)
    sd = math.sqrt(max(var, 1e-9))
    return {"n": n, "cells": m, "collisions": collisions, "expected": exp_col,
            "sd": sd, "z": (collisions - exp_col) / sd}


def gap_test(u: np.ndarray, a: float = 0.3, b: float = 0.7, nbin: int = 12) -> dict:
    """Gaps between successive values falling in (a, b) are geometric."""
    from scipy.stats import chi2 as chi2d
    inside = (u > a) & (u < b)
    idx = np.flatnonzero(inside)
    if idx.size < 500:
        return {"skipped": "too few hits"}
    gaps = np.diff(idx) - 1
    p = b - a
    obs = np.bincount(np.minimum(gaps, nbin), minlength=nbin + 1).astype(float)
    n = obs.sum()
    exp = np.array([n * p * (1 - p) ** r for r in range(nbin)] + [n * (1 - p) ** nbin])
    ok = exp > 5
    stat = float((((obs - exp) ** 2 / exp)[ok]).sum())
    df = int(ok.sum()) - 1
    return {"n_gaps": int(n), "chi2": stat, "df": df, "p": float(chi2d.sf(stat, df))}


def permutation_test(u: np.ndarray, k: int = 5) -> dict:
    """Non-overlapping k-tuples: all k! orderings must be equally likely."""
    from math import factorial

    from scipy.stats import chi2 as chi2d
    n = u.size // k
    if n < 20 * factorial(k):
        return {"skipped": "too few tuples", "n": n}
    t = u[: n * k].reshape(n, k)
    order = np.argsort(t, axis=1)
    code = np.zeros(n, dtype=np.int64)
    for j in range(k):
        code = code * k + order[:, j]
    cnt = np.bincount(code)
    cnt = cnt[cnt > 0]
    nperm = factorial(k)
    exp = n / nperm
    full = np.zeros(nperm)
    full[: cnt.size] = np.sort(cnt)[::-1]
    stat = float(((full - exp) ** 2 / exp).sum())
    return {"n": n, "chi2": stat, "df": nperm - 1,
            "p": float(chi2d.sf(stat, nperm - 1)), "distinct": int((full > 0).sum())}


def bitstream_battery(bits: np.ndarray) -> dict:
    """Monobit, runs and serial correlation on a one-bit-per-tick stream, which
    is all Step Index and Range Break expose of their source."""
    n = bits.size
    ones = int(bits.sum())
    z_mono = (ones - n / 2.0) / math.sqrt(n / 4.0)
    s = np.where(bits > 0, 1, -1)
    band = 2.0 / math.sqrt(n)
    acfs = [G.acf(s.astype(float), lag) for lag in range(1, 51)]
    # blocks of 20 bits read as an integer, then the uniform batteries
    nb = n // 20
    blocks = bits[: nb * 20].reshape(nb, 20)
    ints = (blocks * (1 << np.arange(20))).sum(axis=1)
    u = (ints + 0.5) / (1 << 20)
    return {"n_bits": n, "p_one": ones / n, "z_monobit": z_mono,
            "runs_z": G.runs_z(s), "acf_band": band,
            "acf_outside": int(sum(1 for v in acfs if abs(v) > band)),
            "acf_max": float(max(abs(v) for v in acfs)),
            "block_grid_chi2": grid_chi2(u, 2, 16) if nb > 2000 else {"skipped": "short"},
            "block_serial": serial_battery(u) if nb > 2000 else {"skipped": "short"}}


def randu(n: int) -> np.ndarray:
    """RANDU: `x <- 65539 x mod 2^31`. The textbook bad generator, whose 3-tuples
    lie on fifteen planes. The positive control for the lattice test."""
    x = 1
    out = np.empty(n, dtype=np.float64)
    m = 1 << 31
    for i in range(n):
        x = (65539 * x) % m
        out[i] = x / m
    return out


def rng_report(name: str, u: np.ndarray, do_lattice3: bool = True) -> dict:
    got = {"name": name, "n": int(u.size),
           "distinct": int(np.unique(np.round(u, 9)).size),
           "serial": serial_battery(u),
           "grid2": grid_chi2(u, 2, 16), "grid3": grid_chi2(u, 3, 8),
           "gap": gap_test(u), "perm": permutation_test(u),
           "grid4": grid_chi2(u, 4, 5),
           "lattice2": lattice_gap(u, 2, 12)}
    if do_lattice3:
        got["lattice3"] = lattice_gap(u, 3, 10)
    return got


# ------------------------------------------------------------------- study ----
def arm(tag: str, real_inc, sim_inc, rng_seed: int, out: list, kind="tick",
        cap: int | None = None) -> dict:
    """One discriminator arm.

    `cap` is the number of rows per class and is passed identically to every arm
    on a family. An AUC is a property of the classifier as well as of the data,
    and a learner handed twice the rows finds more - so comparing an arm at
    12,000 rows against a floor at 6,000 measures the split, not the law. The
    first version of this harness did exactly that and read a rebuilt-against-
    rebuilt floor *above* the real-against-real one.
    """
    if kind == "ktuple":
        xa, names = ktuple_features(real_inc, KTUP)
        xb, _ = ktuple_features(sim_inc, KTUP)
    else:
        xa, names = tick_window_features(real_inc, W_TICK)
        xb, _ = tick_window_features(sim_inc, W_TICK)
    if xa.shape[0] < 200 or xb.shape[0] < 200:
        return {"tag": tag, "skipped": True, "n": int(min(xa.shape[0], xb.shape[0]))}
    lim = min(cap or MAXROW, MAXROW)
    xa, xb = xa[:lim], xb[:lim]
    r = G.discriminate(xa, xb, names, seed=rng_seed, n_trees=TREES)
    r["tag"] = tag
    out.append(r)
    return r


def main() -> None:
    payload: dict = {}
    ledger: list[dict] = []
    print("=" * 122)
    print("THE ADVERSARIAL TEST - can any classifier tell the rebuild from the feed?")
    print(f"  seed {SEED}   tick window {W_TICK}   k-tuple {KTUP}   bar window {W_BAR}   "
          f"{G.machine()}")
    print("=" * 122)

    # ------------------------------------------------------ volatility family --
    print("\n[1] THE VOLATILITY FAMILY - increments pooled over the feeds, each divided")
    print("    by its own nominal per-tick sigma so the twelve are on one scale and a")
    print("    volatility error stays visible.")
    real_t, sim_t, real_b, sim_b = [], [], [], []
    realA, realB, simA, simB = [], [], [], []
    coarseA, coarseB, coarse_simA = [], [], []
    resolution = []
    ctl_names = ("sigma+2%", "student-t(6)", "half tick rate", "clustering")
    ctlA: dict[str, list] = {c: [] for c in ctl_names}
    ctl_bars: dict[str, list] = {}
    n_feeds = 0
    for feed, nom in VOL.items():
        rb = G.real_bars(feed)
        rt = G.real_ticks(feed)
        if not rb.get("n") or not rt.get("n"):
            continue
        n_feeds += 1
        tpb = V.ticks_per_bar(feed)
        grid = G.quote_grid(rt["mid"])
        u = (nom / 100.0) / math.sqrt(G.MINUTES_PER_YEAR * tpb)
        ri = np.diff(np.log(rt["mid"])) / u
        ri = ri[np.isfinite(ri)]
        h = ri.size // 2
        sigma_price = u * float(np.median(rt["mid"]))
        res = sigma_price / grid if grid else float("inf")
        resolution.append((feed, grid, sigma_price, res))
        fine = res >= RESOLUTION_MIN
        real_t.append(ri)
        (realA if fine else coarseA).append(ri[:h])
        (realB if fine else coarseB).append(ri[h:2 * h])
        # Every build is truncated to the feed's own real tick count, so the
        # pooled classes carry the *same mixture of feeds*. Pooling twelve feeds
        # of unequal length into two classes of unequal composition hands the
        # classifier feed identity, which is shared between the classes and has
        # nothing to do with the law - and it was worth an apparent AUC of 0.58
        # in the first run of this harness.
        for tag, kw in (("main", {}),
                        ("sigma+2%", {"sigma_mult": 1.02}),
                        ("student-t(6)", {"student_df": 6}),
                        ("half tick rate", {"tpb_override": max(tpb // 2, 2)}),
                        ("clustering", {"cluster": True})):
            sd = SEED + (0 if tag == "main" else 33)
            want = ri.size + 4
            bb = V.simulate_vol(feed, nom, float(rb["close"][0]), grid,
                                max(rb["n"], (want // tpb) + 2), sd,
                                keep_ticks=want, **kw)
            scale = u * (math.sqrt(2.0) if tag == "half tick rate" else 1.0)
            si = np.diff(np.log(bb["ticks"])) / scale
            si = si[np.isfinite(si)][: ri.size]
            if tag == "main":
                sim_t.append(si)
                if fine:
                    simA.append(si[:h])
                    simB.append(si[h:2 * h])
                    real_b.append(rb)
                    sim_b.append(bb)
                else:
                    coarse_simA.append(si[:h])
            elif fine:
                ctlA[tag].append(si[:h])
                ctl_bars.setdefault(tag, []).append(
                    {k2: bb[k2][:rb["n"]] for k2 in ("open", "high", "low", "close")})
    print(f"    {n_feeds} feeds; pooled real tick increments "
          f"{sum(x.size for x in real_t):,}, each rebuild truncated to the same length")
    print(f"\n    quote resolution - lattice points per per-tick sigma. Below "
          f"{RESOLUTION_MIN:.0f} the")
    print("    feed's increments are mostly rounding and it is pooled separately:")
    print(f"      {'feed':26s} {'grid':>10s} {'sigma (price)':>14s} {'points/sigma':>13s}")
    for feed, grid, sp, res in resolution:
        mark = "" if res >= RESOLUTION_MIN else "   <- coarse, quarantined"
        print(f"      {feed:26s} {grid:10.6g} {sp:14.6g} {res:13.1f}{mark}")

    cat = np.concatenate
    arms: list[dict] = []
    ctl: dict[str, list] = {}
    # one row cap for every arm on this family, set by the half-length pool
    cap_kt = cat(realA).size // KTUP
    cap_w = cat(realA).size // W_TICK
    print(f"    every arm below carries {min(cap_kt, MAXROW):,} k-tuple rows and "
          f"{min(cap_w, MAXROW):,} window rows per class")
    print(f"\n{'arm':34s} {'n/class':>9s} {'AUC':>8s} {'95% CI':>17s} {'linear':>8s} "
          f"{'verdict':>12s}")

    def show(r, floor=None):
        if r.get("skipped"):
            print(f"{r['tag']:34s}  skipped ({r.get('n', 0)} rows)")
            return
        v = ""
        if floor is not None and not floor.get("skipped"):
            v = "CAUGHT" if r["lo"] > floor["hi"] else "indistinct"
        print(f"{r['tag']:34s} {r['n']:9d} {r['auc']:8.4f} "
              f"[{r['lo']:.4f},{r['hi']:.4f}] {r['auc_linear']:8.4f} {v:>12s}")

    f_kt = arm("vol FLOOR real-vs-real k-tuple", cat(realA), cat(realB), SEED + 1, arms,
               "ktuple", cap_kt)
    f_w = arm("vol FLOOR real-vs-real window", cat(realA), cat(realB), SEED + 2, arms,
              "tick", cap_w)
    mc_kt = arm("vol MC floor rebuilt-vs-rebuilt", cat(simA), cat(simB), SEED + 5, arms,
                "ktuple", cap_kt)
    mc_w = arm("vol MC floor rebuilt-vs-rebuilt w", cat(simA), cat(simB), SEED + 5, arms,
               "tick", cap_w)
    m_kt = arm("vol real-vs-rebuilt k-tuple", cat(realA), cat(simA), SEED + 3, arms,
               "ktuple", cap_kt)
    m_w = arm("vol real-vs-rebuilt window", cat(realA), cat(simA), SEED + 4, arms,
              "tick", cap_w)
    m_kt2 = arm("vol real-vs-rebuilt k-tuple (2nd)", cat(realB), cat(simB), SEED + 13,
                arms, "ktuple", cap_kt)
    m_w2 = arm("vol real-vs-rebuilt window (2nd)", cat(realB), cat(simB), SEED + 14,
               arms, "tick", cap_w)
    show(f_kt)
    show(f_w)
    show(mc_kt, f_kt)
    show(mc_w, f_w)
    show(m_kt, f_kt)
    show(m_w, f_w)
    show(m_kt2, f_kt)
    show(m_w2, f_w)
    for nm in ctl_names:
        r = arm(f"vol CONTROL {nm} window", cat(realA), cat(ctlA[nm]), SEED + 6, arms,
                "tick", cap_w)
        show(r, f_w)
        r2 = arm(f"vol CONTROL {nm} k-tuple", cat(realA), cat(ctlA[nm]), SEED + 7, arms,
                 "ktuple", cap_kt)
        show(r2, f_kt)
        ctl[nm] = [r, r2]
    if coarseA and coarse_simA:
        rc = arm("vol COARSE FLOOR real-vs-real", cat(coarseA), cat(coarseB), SEED + 15,
                 arms, "ktuple", cap_kt)
        show(rc)
        rq = arm("vol COARSE real-vs-rebuilt", cat(coarseA), cat(coarse_simA), SEED + 16,
                 arms, "ktuple", cap_kt)
        show(rq, rc)
        if not rq.get("skipped") and not rc.get("skipped"):
            ledger.append({"test": "coarse-quoted feeds: rebuild not caught",
                           "feed": "coarse pool", "value": rq["auc"] - rc["auc"],
                           "fired": rq["lo"] > rc["hi"]})

    # bar arm
    xa, bnames = bar_window_features(
        cat([b["open"] for b in real_b]), cat([b["high"] for b in real_b]),
        cat([b["low"] for b in real_b]), cat([b["close"] for b in real_b]), W_BAR)
    nb_real = min(b["n"] for b in real_b) if real_b else 0
    xb, _ = bar_window_features(
        cat([b["open"][:nb_real] for b in sim_b]), cat([b["high"][:nb_real] for b in sim_b]),
        cat([b["low"][:nb_real] for b in sim_b]), cat([b["close"][:nb_real] for b in sim_b]),
        W_BAR)
    # The floor has to pool the *same feeds* on both sides. Splitting the pooled
    # row block in half puts feeds 1-2 on one side and 4-5 on the other, and the
    # classifier then separates feed identity: that arm read AUC 0.96 in the
    # first run of this harness and was measuring nothing but the pooling.
    fa_list, fb_list = [], []
    for b in real_b:
        hb = b["n"] // 2
        xx, _ = bar_window_features(b["open"][:hb], b["high"][:hb], b["low"][:hb],
                                    b["close"][:hb], W_BAR)
        yy, _ = bar_window_features(b["open"][hb:], b["high"][hb:], b["low"][hb:],
                                    b["close"][hb:], W_BAR)
        if xx.shape[0] and yy.shape[0]:
            n2 = min(xx.shape[0], yy.shape[0])
            fa_list.append(xx[:n2])
            fb_list.append(yy[:n2])
    if xa.shape[0] > 400 and xb.shape[0] > 400 and fa_list:
        fa, fb = cat(fa_list), cat(fb_list)
        cap_b = min(fa.shape[0], fb.shape[0], xa.shape[0], xb.shape[0], MAXROW)
        fbar = G.discriminate(fa[:cap_b], fb[:cap_b], bnames,
                              seed=SEED + 9, n_trees=TREES)
        fbar["tag"] = "vol FLOOR real-vs-real bar OHLC"
        arms.append(fbar)
        rbar = G.discriminate(xa[:cap_b], xb[:cap_b], bnames, seed=SEED + 8,
                              n_trees=TREES)
        rbar["tag"] = "vol real-vs-rebuilt bar OHLC"
        arms.append(rbar)
        show(fbar)
        show(rbar, fbar)
        # the controls through the bar arm as well. `half the tick rate` changes
        # nothing a tick increment can see once it is rescaled - the whole of it
        # lives in how many ticks resolve a bar's high and low, so this is the
        # only arm with any power over it.
        for nm, blist in ctl_bars.items():
            xc, _ = bar_window_features(
                cat([b["open"] for b in blist]), cat([b["high"] for b in blist]),
                cat([b["low"] for b in blist]), cat([b["close"] for b in blist]), W_BAR)
            if xc.shape[0] < 400:
                continue
            rc2 = G.discriminate(xa[:cap_b], xc[:cap_b], bnames, seed=SEED + 10,
                                 n_trees=TREES)
            rc2["tag"] = f"vol CONTROL {nm} bar OHLC"
            arms.append(rc2)
            show(rc2, fbar)
            ctl.setdefault(nm, []).append(rc2)
    else:
        rbar = fbar = {"skipped": True}

    vol_ticks = sum(x.size for x in realA)
    vol_bars = sum(b["n"] // 2 for b in real_b)
    nstar_rows = [("Volatility (12 feeds)", "k-tuple", m_kt, f_kt, KTUP, "ticks", vol_ticks),
                  ("Volatility (12 feeds)", "window", m_w, f_w, W_TICK, "ticks", vol_ticks),
                  ("Volatility (12 feeds)", "bar OHLC", rbar, fbar, W_BAR, "bars", vol_bars)]
    for nm, (r, floor) in (("k-tuple", (m_kt, f_kt)), ("window", (m_w, f_w)),
                           ("k-tuple 2nd", (m_kt2, f_kt)), ("window 2nd", (m_w2, f_w)),
                           ("bar OHLC", (rbar, fbar))):
        if r.get("skipped") or floor.get("skipped"):
            continue
        ledger.append({"test": f"volatility rebuild not caught, {nm} arm", "feed": "pooled",
                       "value": r["auc"] - floor["auc"], "fired": r["lo"] > floor["hi"]})
    for nm, (r, floor) in (("k-tuple", (mc_kt, f_kt)), ("window", (mc_w, f_w))):
        if not r.get("skipped") and not floor.get("skipped"):
            ledger.append({"test": f"MC floor no higher than the real floor, {nm}",
                           "feed": "pooled", "value": r["auc"] - floor["auc"],
                           "fired": r["lo"] > floor["hi"]})
    def _floor_for(tag: str) -> dict:
        if "bar OHLC" in tag:
            return fbar
        return f_kt if "k-tuple" in tag else f_w

    n_caught_gen = 0
    for nm in ctl:
        hit = False
        for r in ctl[nm]:
            fl2 = _floor_for(r.get("tag", ""))
            if not r.get("skipped") and not fl2.get("skipped") and r["lo"] > fl2["hi"]:
                hit = True
        n_caught_gen += int(hit)
    ledger.append({"test": "VOID unless 3 of the 4 wrong generators are caught",
                   "feed": "controls", "value": float(n_caught_gen),
                   "fired": n_caught_gen < 3})
    for r in (m_w, m_kt, f_w, f_kt):
        if not r.get("skipped") and G.exactly_null(r["auc"], 0.5, 4):
            ledger.append({"test": "VOID: AUC exactly 0.5000", "feed": r["tag"],
                           "value": 0.5, "fired": True})

    print("\n    the feature the discriminator leans on hardest, measured directly:")
    print("    a zero tick move is a repeated quote, and it is the one thing rounding a")
    print("    continuous process to a lattice gets wrong if the venue does not round.")
    print(f"      {'feed':26s} {'points/sigma':>12s} {'zero moves, feed':>17s} "
          f"{'rebuilt':>10s} {'ratio':>8s}")
    for feed, nom in VOL.items():
        rt = G.real_ticks(feed)
        rb = G.real_bars(feed)
        if not rt.get("n") or not rb.get("n"):
            continue
        tpb = V.ticks_per_bar(feed)
        grid = G.quote_grid(rt["mid"])
        res = next((r[3] for r in resolution if r[0] == feed), float("nan"))
        zr = float((np.diff(rt["mid"]) == 0).mean())
        bb = V.simulate_vol(feed, nom, float(rb["close"][0]), grid,
                            max(rb["n"], rt["n"] // tpb + 2), SEED,
                            keep_ticks=rt["n"] + 2)
        zs = float((np.diff(bb["ticks"]) == 0).mean())
        print(f"      {feed:26s} {res:12.1f} {zr:17.6f} {zs:10.6f} "
              f"{(zs / zr if zr else float('inf')):8.3f}")
        payload.setdefault("zero_moves", {})[feed] = {"real": zr, "sim": zs,
                                                      "points_per_sigma": res}

    print("\n    what the discriminator leans on - the ten features with the largest")
    print("    univariate AUC on the real-against-rebuilt window arm, each beside the")
    print("    same feature's AUC on the real-against-real floor:")
    if not m_w.get("skipped"):
        fl = dict(f_w.get("univariate", []))
        print(f"      {'feature':20s} {'AUC vs rebuilt':>15s} {'AUC floor':>11s} {'gain':>12s}")
        for nm, a in m_w["univariate"][:10]:
            print(f"      {nm:20s} {a:15.4f} {fl.get(nm, float('nan')):11.4f} "
                  f"{m_w['gain'].get(nm, 0.0):12.1f}")

    # ------------------------------------------------------------- the others --
    print("\n[2] THE OTHER FAMILIES - same two arms, same floors")
    print(f"\n{'arm':34s} {'n/class':>9s} {'AUC':>8s} {'95% CI':>17s} {'linear':>8s} "
          f"{'verdict':>12s}")
    others = []

    # Step Index
    sb, st = G.real_bars("step_index"), G.real_ticks("step_index")
    if sb.get("n") and st.get("n"):
        step = 0.1
        ri = np.diff(st["mid"]) / step
        bb = S.sim_step(max(sb["n"], ri.size // 60 + 10), 0.5, SEED,
                        float(sb["close"][0]))
        si = np.diff(bb["ticks"]) / step
        others.append(("step_index", ri, si))

    # Range Break, both feeds, at the edge rule
    for feed in ("range_break_100_index", "range_break_200_index"):
        rb, rt = G.real_bars(feed), G.real_ticks(feed)
        if not rb.get("n") or not rt.get("n"):
            continue
        d = np.diff(rt["mid"])
        stp = float(np.median(np.abs(d[d != 0])))
        brk = S.break_stats(rb, stp)
        vis = S.visited_ranges(rb, stp)
        mbt = brk["minutes_per_break"] * S.TPB
        band, _med, _dk = S.fit_band(vis, mbt, brk["_jump"], float(rb["close"][0]), stp,
                                     SEED)
        sim = S.sim_rb(max(rb["n"], rt["n"] // 60 + 10), band, mbt, brk["_jump"], SEED,
                       float(rb["close"][0]), stp, "edge")
        others.append((feed, d / stp, np.diff(sim["ticks"]) / stp))

    # Boom / Crash, the pool build
    for feed in ("boom_500_index", "crash_500_index", "boom_300_index"):
        rb, rt = G.real_bars(feed), G.real_ticks(feed)
        if not rb.get("n") or not rt.get("n"):
            continue
        f = K.detect(rt["mid"])
        if not f.get("n_ticks"):
            continue
        f["tag"] = feed + "/judge"
        grid = G.quote_grid(rt["mid"])
        sim = K.build(f, grid, float(rb["close"][0]),
                      max(rb["n"], rt["n"] // 60 + 10), SEED, True)
        sc = f["g_mean"]
        others.append((feed, np.diff(rt["mid"]) / sc, np.diff(sim["ticks"]) / sc))

    # Jump
    jb, jt = G.real_bars("jump_75_index"), G.real_ticks("jump_75_index")
    if jb.get("n") and jt.get("n"):
        jd = np.diff(jt["mid"])
        jmed = float(np.median(np.abs(jd[jd != 0])))
        idx = np.flatnonzero(np.abs(jd) > 10 * jmed)
        span = (jt["ts"][-1] - jt["ts"][0]) / 60000.0
        rate = idx.size / span
        sig = (75.0 / 100.0) / math.sqrt(G.MINUTES_PER_YEAR)
        js = math.sqrt(0.7477 * sig ** 2 / rate)
        sim = G.bars_from_stream(
            G.gen_jump(max(jb["n"], jt["n"] + 10) * 60, 75.0, 1.0, rate, js,
                       float(jb["close"][0]), G.quote_grid(jt["mid"]),
                       np.random.default_rng(SEED)), 60,
            max(jb["n"], jt["n"] // 60 + 10), keep_ticks=jt["n"] * 3)
        u = sig / math.sqrt(60.0)
        others.append(("jump_75_index", np.diff(np.log(jt["mid"])) / u,
                       np.diff(np.log(sim["ticks"])) / u))

    per_family = {}
    for feed, ri, si in others:
        h = ri.size // 2
        caps = {"ktuple": h // KTUP, "tick": h // W_TICK}
        for kind in ("ktuple", "tick"):
            fl = arm(f"{feed} FLOOR real-vs-real {kind}", ri[:h], ri[h:2 * h], SEED + 1,
                     arms, kind, caps[kind])
            show(fl)
            r = arm(f"{feed} real-vs-rebuilt {kind}", ri[:h], si[:h], SEED + 2, arms,
                    kind, caps[kind])
            show(r, fl)
            per_family.setdefault(feed, {})[kind] = r
            nstar_rows.append((feed, "k-tuple" if kind == "ktuple" else "window", r, fl,
                               KTUP if kind == "ktuple" else W_TICK, "ticks", h))
            if not r.get("skipped") and not fl.get("skipped"):
                ledger.append({"test": f"{feed} rebuild not caught ({kind})", "feed": feed,
                               "value": r["auc"] - fl["auc"],
                               "fired": r["lo"] > fl["hi"]})
        if feed in per_family and not per_family[feed]["tick"].get("skipped"):
            print("      top features: " + ", ".join(
                f"{n}={a:.3f}" for n, a in per_family[feed]["tick"]["univariate"][:5]))

    # ------------------------------------------------------------- the timing --
    print("\n[3] THE TIMING ARM - reported and excluded from the headline")
    print("    `research.db`'s tick timestamps are our own collector's receive clock, not")
    print("    the venue's publication clock (`lagging.md`), so a discriminator handed")
    print("    inter-arrival times is reading our network rather than Deriv's generator.")
    vt = G.real_ticks("volatility_75_index")
    gaps = np.diff(vt["ts"]).astype(float)
    print(f"    real gaps: median {np.median(gaps):.0f}ms, "
          f"p01 {np.percentile(gaps, 1):.0f}ms, p99 {np.percentile(gaps, 99):.0f}ms, "
          f"sd {gaps.std():.0f}ms")
    print("    a rebuild publishes on an exact grid, so this arm is separable at AUC 1.0")
    print("    by construction and says nothing about the law.")
    payload["timing"] = {"median_ms": float(np.median(gaps)), "sd_ms": float(gaps.std()),
                         "p01": float(np.percentile(gaps, 1)),
                         "p99": float(np.percentile(gaps, 99))}

    # --------------------------------------------------------- the randomness --
    print("\n[4] IS THE VENUE'S RANDOMNESS SOUND? - the increment stream, uniformised")
    print("    Controls first: numpy's PCG64 must pass everything and RANDU must fail the")
    print("    3-tuple lattice test, or these columns have no resolution.")
    rows = []
    rng = np.random.default_rng(SEED)
    # the pool excludes the coarsely quoted feeds: 0.8 lattice points per sigma
    # makes every uniformity test fail on the rounding rather than on the source
    npool = min(1_000_000, sum(x.size for x in realA) + sum(x.size for x in realB))
    g_u = rng.random(npool)
    rows.append(rng_report("CONTROL numpy PCG64", g_u))
    r_u = randu(min(npool, 300_000))
    rows.append(rng_report("CONTROL RANDU (must fail)", r_u))
    pooled = cat(realA + realB)[:npool]
    rows.append(rng_report("volatility, pooled, real", to_uniform(pooled, rng)))
    simpool = cat(simA + simB)[:npool]
    rows.append(rng_report("volatility, pooled, rebuilt", to_uniform(simpool, rng)))
    for feed in ("volatility_75_index", "volatility_75_1s_index", "jump_75_index"):
        rt = G.real_ticks(feed)
        if not rt.get("n"):
            continue
        inc = np.diff(np.log(rt["mid"]))
        inc = inc[np.isfinite(inc)]
        rows.append(rng_report(feed, to_uniform(inc, rng)))
    print(f"{'stream':32s} {'n':>9s} {'distinct':>9s} {'acf out/50':>11s} {'acfmax':>8s} "
          f"{'grid2 p':>9s} {'grid3 p':>9s} {'gap p':>8s} {'perm p':>8s} "
          f"{'grid4 p':>9s} {'lat2':>7s} {'lat3':>7s}")
    for r in rows:
        print(f"{r['name']:32s} {r['n']:9d} {r['distinct']:9d} "
              f"{r['serial']['n_outside']:4d}/{50:<6d} {r['serial']['max_abs']:8.5f} "
              f"{r['grid2'].get('p', float('nan')):9.4f} "
              f"{r['grid3'].get('p', float('nan')):9.4f} "
              f"{r['gap'].get('p', float('nan')):8.4f} "
              f"{r['perm'].get('p', float('nan')):8.4f} "
              f"{r['grid4'].get('p', float('nan')):9.4f} "
              f"{r['lattice2'].get('ratio', float('nan')):7.2f} "
              f"{r.get('lattice3', {}).get('ratio', float('nan')):7.2f}")
    print("    lat2 / lat3 are the largest empty band in a projected 2- or 3-tuple grid,")
    print("    in units of the ln(n)/n a genuine uniform stream produces. Around 1 is")
    print("    sound; a linear congruential source reads orders of magnitude higher.")

    randu_row = next(r for r in rows if "RANDU" in r["name"])
    pcg_row = next(r for r in rows if "PCG64" in r["name"])
    ledger.append({"test": "VOID unless RANDU fails the 3-tuple lattice test",
                   "feed": "control", "value": randu_row.get("lattice3", {}).get("ratio", 0),
                   "fired": randu_row.get("lattice3", {}).get("ratio", 0)
                   < 3 * pcg_row.get("lattice3", {}).get("ratio", 1)})
    for r in rows:
        if r["name"].startswith("CONTROL"):
            continue
        bad = []
        if r["serial"]["n_outside"] > 3 * r["serial"]["expected"]:
            bad.append("serial")
        for key in ("grid2", "grid3", "grid4", "gap", "perm"):
            p = r[key].get("p")
            if p is not None and p == p and p < 0.001:
                bad.append(key)
        if r.get("lattice3", {}).get("ratio", 0) > 3 * pcg_row.get("lattice3", {}).get("ratio", 1):
            bad.append("lattice3")
        ledger.append({"test": "randomness battery passes where PCG64 passes",
                       "feed": r["name"], "value": float(len(bad)), "fired": bool(bad)})
        if bad:
            print(f"    {r['name']}: failed {bad}")

    print("\n[5] THE BIT STREAM - all Step Index and Range Break expose of their source")
    print(f"{'feed':26s} {'bits':>9s} {'p(1)':>9s} {'monobit z':>10s} {'runs z':>9s} "
          f"{'acf out/50':>11s} {'block grid2 p':>14s}")
    for feed in ("step_index", "range_break_100_index", "range_break_200_index"):
        rt = G.real_ticks(feed)
        if not rt.get("n"):
            continue
        d = np.diff(rt["mid"])
        bits = (d[d != 0] > 0).astype(np.int64)
        r = bitstream_battery(bits)
        r["feed"] = feed
        payload.setdefault("bits", []).append(r)
        print(f"{feed:26s} {r['n_bits']:9d} {r['p_one']:9.6f} {r['z_monobit']:+10.2f} "
              f"{r['runs_z']:+9.3f} {r['acf_outside']:4d}/{50:<6d} "
              f"{r['block_grid_chi2'].get('p', float('nan')):14.4f}")
        ledger.append({"test": "bit stream: |monobit z| <= 3", "feed": feed,
                       "value": r["z_monobit"], "fired": abs(r["z_monobit"]) > 3})
        ledger.append({"test": "bit stream: |runs z| <= 3", "feed": feed,
                       "value": r["runs_z"], "fired": abs(r["runs_z"]) > 3})
    bb = S.sim_step(200_000, 0.5, SEED, 9000.0)
    d = np.diff(bb["ticks"])
    r = bitstream_battery((d[d != 0] > 0).astype(np.int64))
    print(f"{'CONTROL rebuilt step':26s} {r['n_bits']:9d} {r['p_one']:9.6f} "
          f"{r['z_monobit']:+10.2f} {r['runs_z']:+9.3f} {r['acf_outside']:4d}/{50:<6d} "
          f"{r['block_grid_chi2'].get('p', float('nan')):14.4f}")

    print("\n[6] n* - THE SAMPLE AT WHICH EACH ARM WOULD SEPARATE REBUILD FROM FEED")
    print("    An AUC at the floor is not proof of identity, it is failure to reject at")
    print("    the power available - so the headline this page owes is the sample size")
    print("    at which each arm *would* reject. `inf` means the arm sits at or below")
    print("    its own real-against-real floor, so no sample separates it by this")
    print("    battery. The gap is held fixed as n grows and in practice it widens, so")
    print("    every finite figure is an upper bound rather than an estimate.")
    print("    `have` is what one class of the arm is drawn from - half the feed, since")
    print("    the other half is the floor - so an arm separates exactly when n* x the")
    print("    window is below it.")
    print(f"{'family':26s} {'arm':10s} {'rows now':>9s} {'gap':>8s} {'n* rows':>12s} "
          f"{'n* in units':>18s} {'have':>12s} {'x over':>8s}")
    for fam, nm, r, fl, per, unit, have in nstar_rows:
        if not r or r.get("skipped") or not fl or fl.get("skipped"):
            continue
        ns = G.auc_nstar(r, fl)
        units = ns * per
        over = units / max(have, 1)
        print(f"{fam:26s} {nm:10s} {r['n']:9d} {r['auc'] - fl['auc']:+8.4f} "
              f"{('inf' if ns == float('inf') else format(ns, ',.0f')):>12s} "
              f"{(('inf' if ns == float('inf') else format(units, ',.0f')) + ' ' + unit):>18s} "
              f"{format(int(have), ',d'):>12s} "
              f"{('inf' if ns == float('inf') else format(over, ',.2f')):>8s}")
        payload.setdefault("nstar", []).append(
            {"family": fam, "arm": nm, "n": r["n"], "gap": r["auc"] - fl["auc"],
             "nstar_rows": ns, "nstar_units": units, "unit": unit, "have": int(have)})

    print("\n[7] THE FAILURE LEDGER")
    by: dict[str, list] = {}
    for e in ledger:
        by.setdefault(e["test"], []).append(e)
    print(f"{'condition':58s} {'cells':>6s} {'fired':>6s} {'worst cell':>36s}")
    nf = 0
    for name, es in sorted(by.items()):
        f2 = [e for e in es if e["fired"]]
        nf += len(f2)
        worst = max(es, key=lambda e: abs(e.get("value") or 0))
        print(f"{name:58s} {len(es):6d} {len(f2):6d} "
              f"{worst['feed'][:28] + ' ' + format(worst['value'], '.4g'):>36s}")
    print(f"\n    {len(ledger)} pre-registered comparisons, {nf} fired.")

    payload.update({"arms": [{k: v for k, v in a.items() if k != "gain"} for a in arms],
                    "rng": rows, "ledger": ledger})
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(json.loads(json.dumps(payload, default=float)), fh, indent=1)
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
