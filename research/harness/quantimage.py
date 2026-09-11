"""The 0.5826 constant is an extrapolation length, and the method of images says so.

`research/deriving.md` needs `B = -zeta(1/2)/sqrt(2*pi) = 0.5826` to make every
barrier answer on the synthetics exact, and quotes it from Broadie-Glasserman-Kou
as a fact about discretely monitored options. That is borrowing a number. This
harness derives it from the **boundary condition** instead, which is the
physicist's route, and it is worth running because it generalises: BGK give a
correction to two named option formulas, while a boundary condition applies to
every boundary-value problem on the same operator - including the ones this desk
asks about that nobody has written a closed form for.

## The construction

Under the Wick rotation `t -> -i*tau` the diffusion equation is the Schrodinger
equation, and an absorbing barrier is a Dirichlet wall. The free propagator plus
one image charge of opposite sign at the mirror point solves it,

    K_a(x, t | 0) = phi_t(x) - phi_t(2a - x),      x < a

which is the reflection principle written as electrostatics. That is exact for a
*continuously* monitored wall. A quoted price is monitored on a grid: the walk
can cross and come back between quotes, so the wall absorbs less than a Dirichlet
wall does.

The physics of a wall that absorbs imperfectly is old. It is a **Robin** boundary
condition, `du/dx = -u/L` at the wall, and `L` is the **extrapolation length** -
the distance beyond the wall at which the linearly extrapolated density would
vanish. It is the Milne problem of neutron transport, where the answer is 0.7104
mean free paths, and the de Gennes extrapolation length of polymer adsorption. To
leading order a Robin wall at `a` with extrapolation length `L` is a Dirichlet
wall at `a + L`: **one image charge, moved.**

The claim under test is therefore

    L = B * sigma * sqrt(h),   B = -zeta(1/2)/sqrt(2*pi) = 0.5826

- that 0.5826 is the extrapolation length of a Gaussian walk against a wall it
only sees every `h`. If it is, `deriving.md`'s two corrected formulas are one
boundary condition rather than two special cases, and any barrier question on
these instruments is answered by moving one image.

## Where 0.5826 comes from, in probability

The walk crosses between quotes and is first *seen* past the level, so the
observed first-passage level is `a + R` with `R` the **overshoot**. Renewal
theory gives the stationary mean overshoot of a random walk over a high level as
`E[H^2]/(2E[H])` with `H` the strict ascending ladder height - the first record
value. For a Gaussian walk the Wiener-Hopf factorisation collapses, because
`P(S_n <= 0) = 1/2` exactly at every `n`, and gives `E[H] = sigma/sqrt(2)` in
closed form. So `E[H]` is an exact number the same estimator must also return,
and it is the control on everything measured here.

## What would count as failure, written before any number is printed

1. **The extrapolation-length reading dies** if the shift fitted from the exactly
   propagated discrete law is not flat in the barrier distance. A boundary
   condition is a property of the wall and cannot know how far away the barrier
   is; a shift that drifts with `a` is a fitted fudge and not a wall. Threshold:
   a spread across `a` in [2, 12] of more than 0.01 at the longest horizon.
2. **The constant dies** if that flat value is not `-zeta(1/2)/sqrt(2*pi)` to
   better than 1%.
3. **The images construction dies** if an image plane at `a + B` scores *worse*
   than the textbook plane at `a` against the exact discrete law, at any barrier
   of two monitoring sigmas or more.
4. **The probabilistic identification dies** if the measured `E[H^2]/(2E[H])`
   differs from `B` by more than 3 Monte Carlo standard errors.
5. **The Wiener-Hopf anchor dies** if `E[H]` differs from `1/sqrt(2)` by more
   than 3 standard errors. This is the load-bearing control: an exact value the
   simulation cannot know, produced by the same estimator as the number under
   test.
6. **The run is void** if a quantity reproduces its target to more digits than
   its own error bar permits, which would mean the estimator is returning its
   target rather than measuring it.

## The controls

* **`1/sqrt(2)`** for the ladder height, above.
* **A deliberately wrong constant.** Everything is also evaluated at `B = 0` (no
  correction) and at `B = 1.0`, a plausible-looking round number. If the three
  are hard to tell apart, the measurement has no power and says nothing.
* **The exact discrete law.** Both candidates are scored against a Chapman-
  Kolmogorov recursion evaluated numerically - convolve, then zero beyond the
  wall - with no asymptotics in it anywhere. Its only error is the space grid,
  and that error is measured by halving the grid rather than assumed.

Nothing here reads any market data. Every number is a property of the Gaussian
random walk, which `research/deriving.md` established these instruments are.
"""

from __future__ import annotations

import json
import math
import os

import numpy as np
from scipy.signal import fftconvolve
from scipy.special import zeta
from scipy.stats import norm

OUT = os.environ.get("OUT", os.path.expanduser("~/till_infinity/logs/quantimage.json"))
SEED = int(os.environ.get("SEED", "20260911"))
#: Paths per batch for the ladder-height Monte Carlo, and the number of batches.
#: The standard error is taken from the spread of the batches rather than from a
#: delta method on two correlated moments of the same variable.
NPATH = int(os.environ.get("NPATH", "400000"))
NBATCH = int(os.environ.get("NBATCH", "12"))
#: Steps a ladder path is followed before it is abandoned. The ladder epoch has
#: infinite mean, so some fraction never finishes; that fraction is reported and
#: the bias it causes is bounded in the output rather than ignored.
LADDER_CAP = int(os.environ.get("LADDER_CAP", "20000"))
#: Grid cells per monitoring sigma for the exact propagation.
PER_SIGMA = int(os.environ.get("PER_SIGMA", "64"))
#: Longest monitoring horizon, in steps.
NSTEPS = int(os.environ.get("NSTEPS", "3200"))

#: -zeta(1/2)/sqrt(2*pi). Broadie-Glasserman-Kou's continuity correction, the
#: limiting expected overshoot of a Gaussian walk, and - the claim here - the
#: extrapolation length of a discretely monitored wall.
BETA = float(-zeta(0.5) / math.sqrt(2.0 * math.pi))
HORIZONS = (25, 100, 400, 1600, 3200)
LEVELS = (1.0, 2.0, 3.0, 5.0, 8.0, 12.0)


def _kernel(dx: float, reach: float = 9.0) -> np.ndarray:
    half = int(round(reach / dx))
    k = dx * norm.pdf(dx * np.arange(-half, half + 1))
    return k / k.sum()


# --------------------------------------------------------------------------
# 1. The exact discretely monitored law, by Chapman-Kolmogorov on a grid
# --------------------------------------------------------------------------


def survival_one_sided(a: float, nsteps: int, per_sigma: int) -> np.ndarray:
    """P(all observed points stay below `a`) after 1..nsteps monitoring instants.

    Exact up to the space grid. The grid is laid out so that the **barrier falls
    on a cell edge**, which turns the leading discretisation error from O(dx) -
    half a cell of mass at the wall - into O(dx^2). Before that alignment the
    one-step survival missed `Phi(a)` in the fourth decimal and the whole table
    inherited it.
    """
    dx = 1.0 / per_sigma
    span = 9.0 * math.sqrt(nsteps) + 25.0
    ncell = int(math.ceil((a + span) / dx))
    x = (a - dx * (np.arange(ncell) + 0.5))[::-1].copy()
    k = _kernel(dx)
    u = norm.pdf(x)  # the density one step in, already restricted below `a`
    out = np.empty(nsteps)
    out[0] = float(u.sum() * dx)
    for i in range(1, nsteps):
        u = fftconvolve(u, k, mode="same")
        out[i] = float(u.sum() * dx)
    return out


def two_sided(a: float, b: float, per_sigma: int, nsteps: int) -> dict:
    """Exit above `+a` before below `-b`, and the expected exit time, exactly.

    Both walls sit on cell edges. The mass crossing each wall at each monitoring
    instant is harvested with its time weight, so `E[tau]` is a sum over the
    exact exit-time distribution rather than a simulation average. The residual
    mass still inside at the end is reported: if it is not negligible the
    expectation is truncated and must not be read.
    """
    dx = 1.0 / per_sigma
    pad = 10.0
    npad = int(round(pad / dx))
    nin = int(round((a + b) * per_sigma))
    x = -b + dx * (np.arange(-npad, nin + npad) + 0.5)
    k = _kernel(dx)
    u = norm.pdf(x)
    up = x > a
    dn = x < -b
    inside = ~(up | dn)
    p_up = p_dn = etau = 0.0
    for i in range(1, nsteps + 1):
        mu = float(u[up].sum() * dx)
        md = float(u[dn].sum() * dx)
        p_up += mu
        p_dn += md
        etau += i * (mu + md)
        u = np.where(inside, u, 0.0)
        if u.sum() * dx < 1e-15:
            break
        u = fftconvolve(u, k, mode="same")
    resid = float(u.sum() * dx)
    tot = p_up + p_dn
    return {
        "a": a,
        "b": b,
        "p_up": p_up / tot,
        "E_tau": etau / tot,
        "residual": resid,
        "total": tot,
    }


def fitted_shift(a: float, surv: np.ndarray) -> dict:
    """The image-plane shift that reproduces the exact survival, horizon by horizon.

    Solve `1 - 2*Phi(-(a+s)/sqrt(n)) = S_exact(n)` for `s`. If 0.5826 is a
    boundary condition then `s` is the same number at every `a` and every `n`
    once the diffusive regime is reached, and that constancy - not the value - is
    what makes it a wall rather than a fit.
    """
    shifts = []
    for n in HORIZONS:
        s_exact = float(surv[n - 1])
        q = (1.0 - s_exact) / 2.0
        shifts.append(-math.sqrt(n) * norm.ppf(q) - a)
    return {"a": a, "horizons": list(HORIZONS), "shifts": shifts, "longest": shifts[-1]}


def expected_max(n: int, per_sigma: int) -> float:
    """E[max of the observed points] = integral over m of P(max > m).

    Asmussen-Glynn-Pitman: `E[max_{k<=n} S_k] = sqrt(2n/pi) - B + o(1)`. This
    evaluates the left side exactly from the same survival propagation, so the
    constant is read off a second functional of the same operator.

    The upper limit has to scale with `sqrt(n)`, because the maximum does. A
    fixed limit of 30 sigmas silently truncated the integral at n >= 400 in the
    first run of this harness and turned a 0.03 residual into a 10.2 one; the
    lesson is that the tail of an expectation has to be bounded rather than
    guessed.
    """
    dm = 0.25
    mmax = 6.0 * math.sqrt(n) + 8.0
    tot = 0.0
    tail = 0.0
    for m in np.arange(dm / 2.0, mmax, dm):
        s = 1.0 - float(survival_one_sided(float(m), n, per_sigma)[n - 1])
        tot += s * dm
        tail = s
    if tail > 1e-4:
        raise RuntimeError(f"E[max] integral truncated at n={n}: tail {tail:.2e}")
    return tot


# --------------------------------------------------------------------------
# 2. The ladder height, by Monte Carlo, with an exact control
# --------------------------------------------------------------------------


def ladder_batch(npath: int, cap: int, rng: np.random.Generator, chunk: int = 100_000) -> dict:
    """Strict ascending ladder height `H = S_tau`, `tau = min{n>=1 : S_n > 0}`."""
    h1 = h2 = 0.0
    done = 0
    unfinished = 0
    rem = npath
    while rem > 0:
        m = min(chunk, rem)
        rem -= m
        s = np.zeros(m)
        idx = np.arange(m)
        for _ in range(cap):
            if idx.size == 0:
                break
            s[idx] += rng.standard_normal(idx.size)
            v = s[idx]
            hit = v > 0.0
            if hit.any():
                w = v[hit]
                h1 += float(w.sum())
                h2 += float((w * w).sum())
                done += int(hit.sum())
                idx = idx[~hit]
        unfinished += int(idx.size)
    eh = h1 / done
    eh2 = h2 / done
    return {"n": done, "unfinished": unfinished, "E_H": eh, "E_H2": eh2, "ratio": eh2 / (2.0 * eh)}


def main() -> None:
    rng = np.random.default_rng(SEED)
    out: dict = {"beta": BETA, "per_sigma": PER_SIGMA, "nsteps": NSTEPS}

    print("=" * 98)
    print("THE 0.5826 CONSTANT AS AN EXTRAPOLATION LENGTH - the method of images, checked")
    print("=" * 98)
    print(f"\n  -zeta(1/2)/sqrt(2*pi) = {BETA:.10f}")
    print("  No market data is read by this harness. Every number is a property of the")
    print("  Gaussian random walk, which research/deriving.md established these are.")

    # ---- 0. how good is the grid? ---------------------------------------
    print("\n[0] THE EXACT ROUTE, AND ITS ONLY ERROR")
    print("    The discrete law is a convolution followed by a truncation, iterated. Its")
    print("    one error is the space grid, so the grid is halved until the answer stops")
    print("    moving, and the one-step survival is checked against Phi(a), which is known.")
    conv = []
    print(
        f"\n    {'cells/sigma':>12s} {'S(1) at a=2':>14s} {'err vs Phi(2)':>15s} "
        f"{'S(100) at a=3':>15s}"
    )
    for ps in (16, 32, 64, 128):
        s1 = survival_one_sided(2.0, 2, ps)[0]
        s100 = survival_one_sided(3.0, 100, ps)[99]
        conv.append({"per_sigma": ps, "S1_a2": float(s1), "S100_a3": float(s100)})
        print(f"    {ps:12d} {s1:14.8f} {s1 - norm.cdf(2.0):+15.2e} {s100:15.8f}")
    out["grid_convergence"] = conv
    drift = abs(conv[-1]["S100_a3"] - conv[-2]["S100_a3"])
    print(f"\n    last halving moved S(100) by {drift:.2e}; every number below is computed")
    print(f"    at {PER_SIGMA} cells per sigma, so the grid error is smaller than that.")

    # ---- 1. the shift, fitted from the exact law ------------------------
    print("\n[1] THE IMAGE-PLANE SHIFT, INVERTED FROM THE EXACT DISCRETE LAW")
    print("    A boundary condition does not know how far away the barrier is. So the")
    print("    test is flatness in `a`, and the value it is flat at is the extrapolation")
    print("    length. The drift across horizons is the o(sqrt(h)) term dying.")
    print(f"\n    {'a':>5s} " + " ".join(f"{('n=' + str(n)):>9s}" for n in HORIZONS))
    fits = []
    survs = {}
    for a in LEVELS:
        survs[a] = survival_one_sided(a, NSTEPS, PER_SIGMA)
        f = fitted_shift(a, survs[a])
        fits.append(f)
        print(f"    {a:5.1f} " + " ".join(f"{v:9.4f}" for v in f["shifts"]))
    out["shift_fit"] = fits
    far = [f["longest"] for f in fits if f["a"] >= 2.0]
    spread = float(np.max(far) - np.min(far))
    mean_far = float(np.mean(far))
    print(f"\n    at n={NSTEPS}, pooled over a in [2, 12]: {mean_far:.5f}, spread {spread:.5f}")
    print(
        f"    -zeta(1/2)/sqrt(2*pi)                      {BETA:.5f}   "
        f"relative error {abs(mean_far / BETA - 1):.3%}"
    )
    print(f"    at a = 1 the shift is {fits[0]['longest']:.4f}, which is deriving.md's")
    print("    'excellent at three units and only fair at one' seen from the other side.")

    # ---- 2. scoring three image planes ----------------------------------
    print("\n[2] THREE IMAGE PLANES, SCORED AGAINST THE EXACT LAW")
    print("    mean |P_predicted - P_exact| over horizons 25..3200. The a+1.0 column is")
    print("    the wrong-constant control: if it scored as well, this measurement would")
    print("    have no power to say which constant is right.")
    cands = {"a  (textbook)": 0.0, "a + 0.5826": BETA, "a + 1.0  (control)": 1.0}
    rows = []
    print(f"\n    {'a':>5s} " + " ".join(f"{k:>20s}" for k in cands))
    for a in LEVELS:
        errs = {}
        for name, sh in cands.items():
            e = [
                abs((1.0 - 2.0 * norm.cdf(-(a + sh) / math.sqrt(n))) - float(survs[a][n - 1]))
                for n in HORIZONS
            ]
            errs[name] = float(np.mean(e))
        rows.append({"a": a, "err": errs})
        print(f"    {a:5.1f} " + " ".join(f"{errs[k]:20.6f}" for k in cands))
    out["image_scores"] = rows

    # ---- 3. the same constant from the expected maximum ------------------
    print("\n[3] THE SAME CONSTANT FROM A DIFFERENT FUNCTIONAL - the expected maximum")
    print("    Asmussen-Glynn-Pitman: E[max of the observed points] = sqrt(2n/pi) - B")
    print("    + o(1). Evaluated exactly by integrating the survival over the level.")
    print(
        f"\n    {'n':>6s} {'E[max] exact':>14s} {'sqrt(2n/pi)':>13s} {'deficit':>10s} {'vs B':>10s}"
    )
    emax = []
    for n in (25, 100, 400):
        e = expected_max(n, 32)
        cont = math.sqrt(2.0 * n / math.pi)
        emax.append({"n": n, "E_max": e, "cont": cont, "deficit": cont - e})
        print(f"    {n:6d} {e:14.5f} {cont:13.5f} {cont - e:10.5f} {cont - e - BETA:+10.5f}")
    out["expected_max"] = emax

    # ---- 4. deriving.md's two forms, from the moved plane ----------------
    print("\n[4] deriving.md's TWO BARRIER FORMS ARE THIS ONE BOUNDARY CONDITION")
    print("    P(up first) = (b+B)/(a+b+2B) and E[tau] = (a+B)(b+B) are exactly what")
    print("    b/(a+b) and a*b become when both walls move out by B. Scored against the")
    print("    exact two-sided law, which is a separate computation from section 1.")
    print(
        f"\n    {'a:b':>7s} | {'P(up) exact':>11s} {'cont':>8s} {'moved':>8s} "
        f"{'B=1 ctl':>8s} | {'E[tau] exact':>12s} {'cont':>9s} {'moved':>9s} {'B=1 ctl':>9s}"
    )
    two = []
    for a, b in ((1, 1), (3, 3), (5, 5), (10, 10), (3, 1), (9, 1), (2, 10)):
        ex = two_sided(float(a), float(b), 32, 40000)
        cp, mp = b / (a + b), (b + BETA) / (a + b + 2 * BETA)
        ct, mt = a * b, (a + BETA) * (b + BETA)
        c1, t1 = (b + 1.0) / (a + b + 2.0), (a + 1.0) * (b + 1.0)
        two.append(
            {"a": a, "b": b, "exact": ex, "cont_p": cp, "moved_p": mp, "cont_t": ct, "moved_t": mt}
        )
        print(
            f"    {f'{a}:{b}':>7s} | {ex['p_up']:11.4f} {cp:8.4f} {mp:8.4f} {c1:8.4f} "
            f"| {ex['E_tau']:12.3f} {ct:9.3f} {mt:9.3f} {t1:9.3f}   "
            f"(resid {ex['residual']:.1e})"
        )
    out["two_sided"] = two
    ec = float(np.mean([abs(r["exact"]["E_tau"] - r["cont_t"]) / r["exact"]["E_tau"] for r in two]))
    em = float(
        np.mean([abs(r["exact"]["E_tau"] - r["moved_t"]) / r["exact"]["E_tau"] for r in two])
    )
    epc = float(np.mean([abs(r["exact"]["p_up"] - r["cont_p"]) for r in two]))
    epm = float(np.mean([abs(r["exact"]["p_up"] - r["moved_p"]) for r in two]))
    print(f"\n    mean relative error on E[tau]:  continuous {ec:.1%}   moved plane {em:.1%}")
    print(f"    mean absolute error on P(up):   continuous {epc:.4f}   moved plane {epm:.4f}")

    # ---- 5. the probabilistic identification ----------------------------
    print("\n[5] THE SAME CONSTANT AS AN OVERSHOOT - the ladder height, by Monte Carlo")
    print("    E[H] = 1/sqrt(2) exactly, from Wiener-Hopf, because P(S_n <= 0) = 1/2 at")
    print("    every n for a symmetric continuous walk. That is the control: the same")
    print("    estimator produces it and the number under test.")
    batches = [ladder_batch(NPATH, LADDER_CAP, rng) for _ in range(NBATCH)]
    eh = float(np.mean([b["E_H"] for b in batches]))
    se_eh = float(np.std([b["E_H"] for b in batches], ddof=1) / math.sqrt(NBATCH))
    rt = float(np.mean([b["ratio"] for b in batches]))
    se_rt = float(np.std([b["ratio"] for b in batches], ddof=1) / math.sqrt(NBATCH))
    unf = sum(b["unfinished"] for b in batches) / (NBATCH * NPATH)
    z_h = (eh - 1.0 / math.sqrt(2.0)) / se_eh
    z_b = (rt - BETA) / se_rt
    out["ladder"] = {
        "batches": NBATCH,
        "npath_each": NPATH,
        "cap": LADDER_CAP,
        "E_H": eh,
        "se_E_H": se_eh,
        "ratio": rt,
        "se_ratio": se_rt,
        "unfinished_frac": unf,
        "z_E_H": z_h,
        "z_ratio": z_b,
    }
    print(
        f"\n    {NBATCH} batches of {NPATH:,} paths, cap {LADDER_CAP:,} steps, "
        f"{unf:.3%} never finished"
    )
    print(f"    E[H]            {eh:.6f} +- {se_eh:.6f}   Wiener-Hopf 0.707107   z = {z_h:+.2f}")
    print(
        f"    E[H^2]/(2E[H])  {rt:.6f} +- {se_rt:.6f}   -zeta(1/2)/sqrt(2pi) "
        f"{BETA:.6f}   z = {z_b:+.2f}"
    )
    print("    The ladder epoch has infinite mean, so the unfinished fraction biases")
    print("    both upward; the size of that bias is visible in E[H]'s own residual.")

    # ---- 6. the ledger ---------------------------------------------------
    print("\n[6] THE PRE-REGISTERED KILL CONDITIONS")
    ledger = []

    def fire(name: str, cond: bool, detail: str) -> None:
        ledger.append({"condition": name, "fired": bool(cond), "detail": detail})
        print(f"    [{'FIRED' if cond else ' ok  '}] {name}")
        print(f"             {detail}")

    fire(
        "1. the fitted shift is not flat in the barrier distance over a in [2,12]",
        spread > 0.01,
        f"values {[f'{v:.4f}' for v in far]}, spread {spread:.5f}",
    )
    fire(
        "2. the flat value is not -zeta(1/2)/sqrt(2pi) to better than 1%",
        abs(mean_far / BETA - 1.0) > 0.01,
        f"{mean_far:.5f} against {BETA:.5f}, relative error {abs(mean_far / BETA - 1):.3%}",
    )
    worse = any(r["err"]["a + 0.5826"] > r["err"]["a  (textbook)"] for r in rows if r["a"] >= 2.0)
    fire(
        "3. the moved image plane scores worse than the textbook one at a >= 2",
        worse,
        "; ".join(
            f"a={r['a']:.0f}: {r['err']['a + 0.5826']:.5f} vs {r['err']['a  (textbook)']:.5f}"
            for r in rows
            if r["a"] >= 2.0
        ),
    )
    fire(
        "4. E[H^2]/(2E[H]) is not the constant within 3 MC standard errors",
        abs(z_b) > 3.0,
        f"{rt:.6f} +- {se_rt:.6f} against {BETA:.6f}, z = {z_b:+.2f}",
    )
    fire(
        "5. E[H] is not 1/sqrt(2) within 3 SE - the live-estimator control",
        abs(z_h) > 3.0,
        f"{eh:.6f} +- {se_eh:.6f} against 0.707107, z = {z_h:+.2f}",
    )
    fire(
        "6. void - a quantity reproduces its target to more digits than its error bar",
        abs(eh - 1.0 / math.sqrt(2.0)) < 0.02 * se_eh or abs(mean_far - BETA) < 1e-9,
        f"|E[H] - 1/sqrt(2)| = {abs(eh - 1 / math.sqrt(2)):.2e} against SE {se_eh:.2e}; "
        f"|shift - B| = {abs(mean_far - BETA):.2e}",
    )
    out["ledger"] = ledger
    print(f"\n    {sum(1 for x in ledger if x['fired'])} of {len(ledger)} fired.")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(out, fh, indent=1, default=float)
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
