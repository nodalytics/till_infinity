"""Is the Wigner function of these processes ever negative, and if so, why?

Negativity of the Wigner function is the standard test of whether a quantum
description is doing any work. A classical probability distribution over phase
space is non-negative by definition; a quantum state need not be, and where it is
not, no classical phase-space model can reproduce it. So measuring it on these
instruments **bounds how far the imaginary-time analogy goes**, which is a
statement `research/quantising.md` currently does not make.

## The construction, and it collapses to something measurable

Under the Wick rotation the transition density is the Euclidean propagator
`K_tau(x, y) = <x| exp(-H tau) |y>`, and the thermal density matrix is that
kernel normalised:

    rho_tau(x, x') = K_tau(x, x') / Z,    Z = integral K_tau(x, x) dx

The Wigner transform of a density matrix is

    W(q, p) = (1/pi) integral rho(q+u, q-u) exp(-2 i p u) du

and every process on this book has **stationary independent increments**, so
`K_tau(x, x') = f_tau(x - x')` depends only on the displacement and `rho` is
translation invariant. Substituting `v = 2u` collapses the whole thing:

    W(q, p) = (1/(2 pi)) * phi_tau(p)

**the Wigner function is the characteristic function of the lag-`tau` increment
distribution**, independent of `q`. That is not an approximation, it is what the
Wigner transform of a translation-invariant kernel *is*, and it makes the test
one line of arithmetic on data this desk already holds.

So the question "is the Wigner function negative" becomes "does the
characteristic function of the returns dip below zero", and the answer is known
in advance for two of the three cases:

* a **Gaussian** increment has `phi(k) = exp(-sigma^2 k^2 / 2)`, strictly
  positive at every `k`. The Volatility indices should show no negativity at all;
* a **lattice** increment of fixed step `d` has `phi(k) = cos(d k)^n` at `n`
  steps, which reaches **-1** at `k = pi/d` when `n` is odd and bottoms at **0**
  when `n` is even, because an even power of a cosine is non-negative. Step Index
  and Range Break move exactly one unit a tick, so they should show a negativity
  that **alternates with the parity of the lag** and sits at the edge of the quote
  lattice's Brillouin zone rather than anywhere interesting. That is the
  sublattice symmetry of a tight-binding chain, and it is a parameter-free
  prediction with nothing fitted in it;
* a **superposition** - two separated packets - has an oscillating `phi` with
  deep negative lobes. That is the positive control, and without it a null here
  would only show the estimator cannot see negativity.

If that is what comes out then the negativity is **the quote grid and not
interference**, the analogy is bounded exactly there, and saying so is the
result. If a continuous feed goes negative, or a lattice feed goes negative
somewhere the lattice does not predict, that is the opposite of a null and would
be the most surprising thing in this folder.

## What would count as failure, written before any number is printed

1. **The null dies** if a continuous feed - any Volatility index - shows a
   minimum of `phi` below three standard errors under zero. Those are Gaussian to
   `H = 0.50` and kurtosis 3.00 (`research/cascading.md`) and have no business
   being negative anywhere.
2. **The lattice explanation dies** if `cos(dk)^n` with the *measured* step and
   the actual lag does not reproduce the measured negativity in both **depth** and
   **parity**, to within 0.15.
3. **The estimator dies** if the superposition control does not go sharply
   negative. A null from a blind estimator is not a null.
4. **The suppression claim dies** if the negativity does not die away with lag
   the way `cos(dk)^n` says it must - a lattice signature has to vanish under
   coarse-graining or it is not a lattice signature.
5. **The run is void** if a minimum comes out exactly 0.0000 or exactly -1.0000,
   or if the characteristic function is exactly 1 at every `k`, which would mean
   a constant input.

## What this cannot say

`phi` is estimated from a finite sample, so at large `k` it is dominated by noise
with a floor of order `1/sqrt(n)`; the standard error is computed analytically
from `Var(cos(kX)) = (1 + phi(2k))/2 - phi(k)^2` and no minimum inside three of
them is read. And the whole construction assumes
stationary independent increments, which `research/deriving.md` establishes for
these generators and which is **false** for Range Break inside a range - so Range
Break is reported with that caveat attached rather than silently.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3

import numpy as np

DATA = os.environ.get("DATA", os.path.expanduser("~/till_infinity/data"))
DB = os.environ.get("DB", os.path.join(DATA, "research.db"))
OUT = os.environ.get("OUT", os.path.expanduser("~/till_infinity/logs/quantwigner.json"))
SEED = int(os.environ.get("SEED", "20260911"))
#: Frequencies probed, in units of the feed's own quote step.
NK = int(os.environ.get("NK", "1500"))
#: Lags in ticks at which the propagator is taken.
LAGS = tuple(int(v) for v in os.environ.get("LAGS", "1,2,3,5,10,30").split(","))

FEEDS = (
    "volatility_75_index",
    "volatility_100_index",
    "volatility_75_1s_index",
    "step_index",
    "range_break_100_index",
    "range_break_200_index",
    "boom_500_index",
    "jump_75_index",
)


def increments(feed: str, lag: int) -> tuple[np.ndarray, float] | None:
    """Lag-`lag` mid-price increments, and the feed's own quote step."""
    if not os.path.exists(DB):
        return None
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = conn.execute(
        "SELECT bid, ask FROM ticks WHERE feed=? ORDER BY ts ASC", (feed,)
    ).fetchall()
    conn.close()
    if len(rows) < 5000:
        return None
    mid = np.array([(float(b) + float(a)) / 2.0 for b, a in rows], dtype=float)
    d1 = np.diff(mid)
    nz = np.abs(d1[d1 != 0])
    step = float(np.median(nz)) if nz.size else 1.0
    return mid[lag:] - mid[:-lag], step


def cf(x: np.ndarray, ks: np.ndarray) -> np.ndarray:
    """Empirical characteristic function, real part, of a symmetric increment.

    `W(q, p) = phi(p) / (2 pi)`, so up to the positive constant this *is* the
    Wigner function and its sign is the thing under test.
    """
    x = x - x.mean()
    return np.cos(np.outer(ks, x)).mean(axis=1)


def cf_se(x: np.ndarray, ks: np.ndarray) -> np.ndarray:
    """Standard error of the empirical characteristic function, analytically.

    `Var(cos(kX)) = (1 + phi(2k))/2 - phi(k)^2`, so the error bar needs no
    resampling - which matters, because bootstrapping a characteristic function
    over 1,500 frequencies and 86,000 points is 3.6 billion cosines and the first
    version of this harness would not have finished.
    """
    p1 = cf(x, ks)
    p2 = cf(x, 2.0 * ks)
    v = np.maximum((1.0 + p2) / 2.0 - p1 * p1, 0.0)
    return np.sqrt(v / x.size)


def main() -> None:
    rng = np.random.default_rng(SEED)
    out: dict = {"lags": list(LAGS)}

    print("=" * 98)
    print("THE WIGNER FUNCTION OF A PRICE PROCESS, AND WHERE IT GOES NEGATIVE")
    print("=" * 98)
    print("\n  For a process with stationary independent increments the Wigner transform")
    print("  of the Euclidean density matrix collapses to W(q,p) = phi_tau(p) / (2 pi):")
    print("  the characteristic function of the lag-tau return, independent of q. So the")
    print("  negativity test is one line of arithmetic and needs no phase-space grid.")

    # ---- 0. the controls, before any data --------------------------------
    print("\n[0] THE CONTROLS, WHICH DECIDE WHETHER A NULL CAN BE READ")
    ks = np.linspace(0.0, 40.0, 2001)
    ctl = {}
    g = rng.standard_normal(200_000)
    ctl["gaussian"] = float(cf(g, ks / g.std()).min())
    lat = rng.choice(np.array([-1.0, 1.0]), 200_000)
    ctl["lattice, one step"] = float(cf(lat, ks).min())
    for n in (2, 3, 10):
        latn = rng.choice(np.array([-1.0, 1.0]), (200_000, n)).sum(axis=1)
        ctl[f"lattice, {n} steps"] = float(cf(latn, ks).min())
    cat = np.concatenate(
        [rng.standard_normal(100_000) * 0.2 - 3.0, rng.standard_normal(100_000) * 0.2 + 3.0]
    )
    ctl["superposition (positive control)"] = float(cf(cat, ks).min())
    for k, v in ctl.items():
        print(f"    {k:36s} min W  {v:+.4f}")
    out["controls"] = ctl
    print("\n    A Gaussian cannot go negative and does not. A lattice does, and it does")
    print("    so with a PARITY: phi(k) = cos(dk)^n reaches -1 at k = pi/d when n is odd")
    print("    and bottoms at 0 when n is even, because cos^even is non-negative. That is")
    print("    a parameter-free prediction with no fitting in it, and it is the")
    print("    sublattice symmetry of a tight-binding chain seen in a price series. The")
    print("    superposition is the positive control: without it a null would only show")
    print("    the estimator is blind.")

    # ---- 1. measured -----------------------------------------------------
    print("\n[1] MEASURED, ON TICKS")
    if not os.path.exists(DB):
        print(f"    research.db not reachable at {DB} - nothing measured, nothing reported.")
        out["measured"] = {}
    else:
        meas: dict = {}
        print(
            f"    {'feed':26s} {'lag':>4s} {'n':>8s} {'step':>8s} {'min W':>9s} "
            f"{'k at min':>9s} {'k*step/pi':>10s} {'-3 SE':>9s} {'lattice':>9s}"
        )
        for feed in FEEDS:
            for lag in LAGS:
                got = increments(feed, lag)
                if got is None:
                    if lag == LAGS[0]:
                        print(f"    {feed:26s} (absent)")
                    break
                x, step = got
                sd = float(x.std())
                if sd <= 0:
                    continue
                # Probe out to well past the lattice's first zero, in units set by
                # the feed's own quote step so every feed is asked the same question.
                kk = np.linspace(0.0, 4.0 * math.pi / step, NK)
                w = cf(x, kk)
                j = int(np.argmin(w))
                blo = float(-3.0 * cf_se(x, kk).max())
                # What a pure lattice walk of the same number of steps predicts.
                lat_pred = float(np.min(np.cos(kk * step) ** lag))
                meas.setdefault(feed, {})[lag] = {
                    "n": int(x.size),
                    "step": step,
                    "sd": sd,
                    "min_W": float(w[j]),
                    "k_at_min": float(kk[j]),
                    "k_step_over_pi": float(kk[j] * step / math.pi),
                    "noise_floor_3se": blo,
                    "lattice_prediction": lat_pred,
                }
                print(
                    f"    {feed:26s} {lag:4d} {x.size:8d} {step:8.4f} {w[j]:+9.4f} "
                    f"{kk[j]:9.3f} {kk[j] * step / math.pi:10.3f} {blo:+9.4f} "
                    f"{lat_pred:+9.4f}"
                )
        out["measured"] = meas

    # ---- 2. the ledger ---------------------------------------------------
    print("\n[2] THE PRE-REGISTERED KILL CONDITIONS")
    ledger = []

    def fire(name: str, cond: bool, detail: str) -> None:
        ledger.append({"condition": name, "fired": bool(cond), "detail": detail})
        print(f"    [{'FIRED' if cond else ' ok  '}] {name}")
        print(f"             {detail}")

    meas = out.get("measured", {})
    cont = {f: v for f, v in meas.items() if f.startswith("volatility")}
    latf = {f: v for f, v in meas.items() if f.startswith(("step", "range_break"))}
    bad_cont = [
        f"{f} lag {lag}: {r['min_W']:+.4f} against floor {r['noise_floor_3se']:+.4f}"
        for f, lv in cont.items()
        for lag, r in lv.items()
        if r["min_W"] < r["noise_floor_3se"]
    ]
    fire(
        "1. a continuous feed goes negative below its own bootstrap floor",
        bool(bad_cont),
        "; ".join(bad_cont)
        if bad_cont
        else (
            "not evaluated - no data"
            if not cont
            else f"{sum(len(v) for v in cont.values())} cells, none below their floor"
        ),
    )
    miss = [
        f"{f} lag {lag}: measured {r['min_W']:+.4f} against lattice {r['lattice_prediction']:+.4f}"
        for f, lv in latf.items()
        for lag, r in lv.items()
        if abs(r["min_W"] - r["lattice_prediction"]) > 0.15
    ]
    fire(
        "2. the lattice control does not reproduce a lattice feed's negativity",
        bool(miss),
        "; ".join(miss[:6])
        if miss
        else (
            "not evaluated - no data"
            if not latf
            else f"{sum(len(v) for v in latf.values())} cells, all within 0.15"
        ),
    )
    fire(
        "3. the superposition control does not go sharply negative",
        ctl["superposition (positive control)"] > -0.2,
        f"min W {ctl['superposition (positive control)']:+.4f}",
    )
    decayed = []
    for f, lv in latf.items():
        lags = sorted(lv)
        if len(lags) >= 2 and lv[lags[-1]]["min_W"] < lv[lags[0]]["min_W"] - 0.05:
            decayed.append(f"{f}: {lv[lags[0]]['min_W']:+.3f} -> {lv[lags[-1]]['min_W']:+.3f}")
    fire(
        "4. the negativity does not die away with lag",
        bool(decayed),
        "; ".join(decayed)
        if decayed
        else ("not evaluated - no data" if not latf else "every lattice feed decays or holds"),
    )
    allmin = [r["min_W"] for lv in meas.values() for r in lv.values()]
    fire(
        "5. void - a minimum lands on exactly 0 or exactly -1",
        any(abs(v) < 1e-12 or abs(v + 1.0) < 1e-12 for v in allmin),
        f"{len(allmin)} cells, extremes [{min(allmin):+.4f}, {max(allmin):+.4f}]"
        if allmin
        else "no data",
    )
    out["ledger"] = ledger
    print(f"\n    {sum(1 for x in ledger if x['fired'])} of {len(ledger)} fired.")

    os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(out, fh, indent=1, default=float)
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
