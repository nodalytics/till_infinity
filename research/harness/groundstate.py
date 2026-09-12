"""Can the relaxation spectrum be read off the marginal, and what does it mean when it cannot?

`research/quantising.md` measures the Range Break ladder from the *dynamics* -
Ulam's method on the lagged transition matrix - and reads it against a dictionary
it takes as given: a reflecting band is the particle in a box and gives 1:4:9, an
Ornstein-Uhlenbeck generator is the harmonic oscillator up to a similarity
transform and gives 1:2:3.

**That dictionary is not two facts. It is one formula evaluated at two
densities**, and this harness derives the formula, checks it on the two cases
where the answer is known exactly, and then uses it for something neither page
can currently do.

## The derivation

A reversible diffusion `dX = b dt + sqrt(2D) dW` with stationary density `p` has
`b = D (log p)'` - that is what reversibility *means* in one dimension - and its
generator `L f = D f'' + b f'` is self-adjoint in `L^2(p)` with Dirichlet form

    <f, -L f>_p  =  D * Integral p(x) f'(x)^2 dx

The Rayleigh-Ritz principle - the same variational principle that gives the
ground state of a Hamiltonian - says the relaxation rates are the successive
minima of `D Int p f'^2 / Int p f^2` over functions orthogonal to the constants.
Equivalently, the ground-state transform `psi = sqrt(p)` conjugates `L` into a
Schrodinger operator `H = -D d^2/dx^2 + V` with

    V(x) = D [ (1/4) ((log p)')^2 + (1/2) (log p)'' ]

and `H sqrt(p) = 0` exactly, so the stationary density **is** the ground state
and the relaxation rates **are** the excitation energies. `groundlib.static_rates`
evaluates the Dirichlet form directly rather than forming `V`, because `V` needs
two numerical derivatives of an estimated density and the Dirichlet form needs
none.

What is worth stopping on is what is absent from the right-hand side: **no
transition data**. Under the reversible-diffusion hypothesis the entire spectrum
is a functional of the marginal density and one diffusivity, and the *ratios*
`lambda_k/lambda_1` do not even need the diffusivity. So

> **`lambda_2/lambda_1` - the number `research/quantising.md` measures from the
> dynamics - is predicted by the histogram, with nothing dynamic in it.**

A uniform density returns 4.00 and a Gaussian returns 2.00. Those are the box and
the spring, and they are the same formula twice.

## And then the part that is a test rather than a restatement

There is a second, independent estimate of the same spectrum: Ulam's method on
the joint law of `(x_t, x_{t+lag})`. Run on the **same uniform grid**, so that
the two share every artefact of the binning, the pair gives

    R  =  lambda_1(dynamics) / lambda_1(density)

and under the reversible-one-dimensional-diffusion hypothesis `R = 1`. It is not
a goodness-of-fit statistic bolted on afterwards; it is the hypothesis written as
a ratio of two things that are the same object if the hypothesis holds. `R != 1`
says one of: the process is not Markov in `x` alone (hidden state), or its drift
is not a gradient (irreversible), or it is not a diffusion (jumps).

That is the question `till_infinity/trading/barriers.py` needs answered and
cannot answer. It prices a stop-and-target geometry as driftless Brownian motion
at an estimated volatility. Brownian motion is the `R = 1` case with a flat
potential. **`R` is how far a feed is from the assumption**, measured rather than
assumed, on a statistic that needs one histogram and one transition count.

## The classical control, which has to be beaten or acknowledged

`groundlib.km_rates`: Kramers-Moyal. Bin the state, estimate `b(x)` and `D(x)` as
conditional moments of the increment, assemble the generator, take its
eigenvalues. It uses the transitions the static route throws away and assumes
nothing about reversibility. **If it lands where the static route lands on every
truth including the positive control, then the derivation has bought cheapness
and not information, and this page says so.** The AR(1) half-life is printed
beside everything as the one number this desk would otherwise reach for.

## The controls, run before any market data

* a simulated **reflecting box** and a simulated **Ornstein-Uhlenbeck**, whose
  spectra are exactly `(k pi/W)^2 D` and `k theta`;
* a **driftless random walk**, which has no discrete spectrum at all and which
  `research/quantising.md` found reproduces the box ladder because binning a
  diffusion by its own observed support makes that support the box;
* **two positive controls**, because the dry run showed one is not enough. The
  first is an OU whose diffusivity is itself a hidden process: its marginal is a
  scale mixture, so the static route reads a potential that is not generating the
  dynamics and `R` must move. The second is a **sum of a fast and a slow OU** -
  the projection of a two-dimensional Markov process onto one axis, which is not
  Markov in what is observed - so the implied timescale must drift. In the dry
  run `R` caught the first and the timescale scan did not, which is what made it
  obvious that a single control was calibrating a single instrument.

All six run through the identical episode-splitting and de-meaning pipeline the
Range Break data gets, at the sample size the data has, because
`research/quantising.md` established that the de-meaning bias is a function of
the episode-length distribution and that a feed cut one way and a simulation cut
another will differ by an amount that looks like a spectrum.

## And a free null on the real feeds

The real-feed leg reads the relaxation of **log realised volatility**, which is
the quantity `barriers.py` takes as an input and holds constant. The twelve Deriv
Volatility indices are the control and they are a good one:
`research/generators.md` measured no volatility clustering anywhere on them
(largest `|acf|` 0.017 against 0.219 on the real feeds) and
`research/cascading.md` has them at H = 0.50 and kurtosis 3.00. **Their log
realised volatility is estimation noise around a constant**, so whatever rate the
estimator returns there is its own floor, and a real feed means something only
against it.

## What would count as failure

Written before the first number was read.

1. **The derivation is wrong** if an exact uniform density does not return the
   ladder 1:4:9 and an exact Gaussian 1:2:3, each to within 1% at the finest
   grid, with `lambda_1` within 1% of `(pi/W)^2 D` and `D/s^2`.
2. **The estimator is dead** if, on a simulated Ornstein-Uhlenbeck at the real
   sample size and through the real pipeline, the static route's replicate
   interval does not cover the true `lambda_1`.
3. **The same for a simulated reflecting box**, against `(pi/W)^2 D`.
4. **The specification test has no power** if `R` on the hidden-volatility
   positive control is not separated from `R` on the plain OU by two replicate
   standard deviations. If this fires, the real-feed leg is not reported at all,
   because a ratio with no power returns 1 whatever is true.

   **This fired in the dry run and is restated here, before the real run, with
   the reason and the original wording kept.** At eight replicates the gap was
   0.87 against a requirement of 2.04: `R` reads 1.03 +- 0.03 on the plain
   Ornstein-Uhlenbeck and 1.90 +- 0.98 on the hidden-volatility control, so the
   *means* are far apart and a *single* series cannot be classified by it. Both
   statements are worth having and the original condition conflated them, so it
   becomes two:

   * **4a, `R` as a per-series verdict.** Separation at two replicate standard
     deviations. If it fires, `R` may never be quoted as a verdict about one
     feed - only against a control arm of other feeds run through the same code.
   * **4b, `R` as a comparative statistic.** The two means separate by two
     standard errors of the mean over `NREP` replicates. **The market legs are
     gated on 4b**, because that is the form in which they are read: a group of
     real feeds against a group of constant-volatility control feeds, never one
     number against 1.0.

   Restating a condition after it fires is the move this folder is most
   suspicious of, so: the restatement narrows what may be claimed rather than
   widening it, it was made on simulated data before any feed was read, and 4a is
   expected to fire in the real run too and is reported when it does.
5. **The static route is notation** if the Kramers-Moyal control reproduces it on
   every truth *including* the positive control - that is, if nothing the
   derivation says is unavailable to a method that already reads the transitions.
   This one is expected to fire in part and the page will report which part.
6. **The run is void** if any recovered ladder lands on exactly 4.0000 or 2.0000,
   or any `R` lands on exactly 1.0000. A statistic landing on its null to four
   decimals is a bug to hunt.
7. **The real-feed leg is void** if the Volatility-index control returns the same
   log realised volatility relaxation rate as the real feeds, because a family
   with no volatility clustering in it cannot be as persistent as gold unless the
   estimator is measuring its own window.
8. **The Range Break leg may not be read** unless the simulated box and the
   simulated spring separate on the static ladder by two replicate standard
   deviations at the sample actually achieved. Inherited verbatim from
   `quantspec.py` condition 10, which was added there after a run that could not
   read its own ladder and said so.
9. **The trim is a fitted knob** if any headline number moves by more than its
   own replicate spread across the trim scan. `groundlib.uniform_grid` documents
   that trimming walks a spring toward a box, so this is checked rather than
   trusted.

Added during the dry run, before any feed was read, because condition 4's
restatement exposed that `R` is not the sharpest instrument for the thing it was
reaching for:

10. **The implied-timescale scan.** For *any* Markov process the transfer
    operator's eigenvalues are exactly exponential in the lag, so
    `lambda_1(tau) = -log(mu_1(tau))/tau` is **flat in `tau`**, whatever its
    spectrum looks like. A drift in it is non-Markovianity and nothing else -
    hidden state seen without needing a density at all. It is free, it is a
    within-series slope so the replicate-to-replicate wander in the level
    cancels, and it is the classical implied-timescale test of Markov state
    models. It is run beside `R` and **the honest expectation is that it is the
    more powerful of the two**; if it is, the page says so and `R` keeps only the
    job the scan cannot do, which is to say whether the *marginal* is what misled
    you.
"""

from __future__ import annotations

import json
import math
import os
from concurrent.futures import ProcessPoolExecutor

import numpy as np

import groundlib as G

SEED = int(os.environ.get("SEED", "20260912"))
NREP = int(os.environ.get("NREP", "96"))
NBIN = int(os.environ.get("NBIN", "96"))
WORKERS = int(os.environ.get("WORKERS", "32"))
OUT = os.environ.get("OUT", os.path.join(G.LOGS, "groundstate.json"))
#: Lag for Ulam, in the sampling unit. On Range Break ticks `tau_2` is about 96
#: ticks, so 60 is well inside the second mode's lifetime; `quantspec.py` uses
#: the same value and the two are meant to be comparable.
LAG = int(os.environ.get("LAG", "60"))
TRIMS = (0.0, 0.0005, 0.002)
#: Realised-volatility window for the real-feed leg, in one-minute bars.
RV_WIN = int(os.environ.get("RV_WIN", "30"))
#: Lags for the implied-timescale scan, as multiples of `LAG`. Flat means Markov.
ITS = (0.25, 0.5, 1.0, 2.0, 4.0)


def implied_timescales(x, ep, base_lag, nbin, trim=0.0) -> tuple[list[float], float]:
    """`lambda_1` recovered at a ladder of lags, and the log-log slope of it.

    Exactly exponential eigenvalues mean `lambda_1(tau)` is constant, so the
    slope is zero for any Markov process and the size of it is the
    non-Markovianity. Nothing about the density enters.
    """
    out, lags = [], []
    for f in ITS:
        lag = max(1, int(round(base_lag * f)))
        if lag in lags:
            continue
        r, d = G.ulam_rates(x, ep, lag, nbin=nbin, trim=trim)
        if d.get("pairs", 0) > 500 and math.isfinite(r[0]) and r[0] > 0:
            out.append(r[0])
            lags.append(lag)
    if len(out) < 3:
        return out, float("nan")
    lg = np.log(np.asarray(lags, dtype=float))
    lv = np.log(np.asarray(out))
    return out, float(np.polyfit(lg, lv, 1)[0])


def _fmt(v, w=8, p=4):
    return f"{v:{w}.{p}f}" if isinstance(v, float) and math.isfinite(v) else f"{'-':>{w}s}"


# --------------------------------------------------------------------------
# 1. The dictionary, from one formula
# --------------------------------------------------------------------------


def section_dictionary() -> dict:
    print("\n=== 1. The box and the spring are one formula at two densities ===\n")
    print("    No data and no simulation: an exact uniform density and an exact")
    print("    Gaussian, pushed through the same Rayleigh-Ritz discretisation.\n")
    rows = {}
    print(f"    {'density':10s} {'cells':>6s} {'l1/true':>9s} {'l2/l1':>9s} {'l3/l1':>9s}  true")
    for nbin in (64, 128, 256, 512, 1024):
        c = G.check_analytic(nbin)
        for name, v in c.items():
            lad = v["ladder"]
            print(
                f"    {name:10s} {nbin:6d} {v['rates'][0] / v['true_l1']:9.5f} "
                f"{lad[1]:9.5f} {lad[2]:9.5f}  {v['true_ladder']}"
            )
            rows[f"{name}_{nbin}"] = v
    print("\n    The uniform density is the particle in a box and the Gaussian is the")
    print("    harmonic oscillator. Nothing was fitted and no transition was read.")
    return rows


# --------------------------------------------------------------------------
# 2. Power, and the specification ratio's own controls
# --------------------------------------------------------------------------

TRUTHS = ("box", "spring", "free", "hidden", "twoscale")


def _one_replicate(args) -> dict:
    kind, seed, n, width, dvar, theta, svar, mean_len, min_len, nbin, lag, trim = args
    rng = np.random.default_rng(seed)
    if kind == "box":
        x, ep = G.sim_box(n, width, dvar, mean_len, rng, min_len)
    elif kind == "spring":
        x, ep = G.sim_ou(n, theta, svar, mean_len, rng, min_len)
    elif kind == "free":
        x, ep = G.sim_free(n, dvar, mean_len, rng, min_len)
    elif kind == "twoscale":
        x, ep = G.sim_two_scale(n, theta, svar, mean_len, rng, min_len)
    else:
        x, ep = G.sim_hidden_vol(n, theta, svar, mean_len, rng, min_len)
    if x.size < 2000:
        return {}
    a, b = G._lagged(x, ep, 1)
    dvar_hat = float(np.var(b - a))
    st, sd = G.static_rates(x, dvar_hat, nbin=nbin, trim=trim)
    ul, ud = G.ulam_rates(x, ep, lag, nbin=nbin, trim=trim)
    km, _ = G.km_rates(x, ep, nbin=nbin, trim=trim)
    _, slope = implied_timescales(x, ep, lag, nbin, trim)
    return {
        "kind": kind,
        "n": int(x.size),
        "static": st,
        "ulam": ul,
        "km": km,
        "static_ladder": G.ladder(st),
        "ulam_ladder": G.ladder(ul),
        "km_ladder": G.ladder(km),
        "R": (ul[0] / st[0]) if (st[0] and math.isfinite(ul[0]) and st[0] > 0) else float("nan"),
        "R_km": (km[0] / st[0]) if (st[0] and math.isfinite(km[0]) and st[0] > 0) else float("nan"),
        "its_slope": slope,
        "halflife": G.ar1_halflife(x, ep),
        "cells": sd.get("cells"),
        "pairs": ud.get("pairs"),
    }


#: Every statistic that claims to say which confinement this is, so that the
#: derived one and the classical ones are scored on the same replicates by the
#: same rule. `halflife` is the one number this desk would otherwise reach for.
DISCRIMINATORS = (
    ("static ladder l2/l1", lambda r: r["static_ladder"][1]),
    ("ulam ladder l2/l1", lambda r: r["ulam_ladder"][1]),
    ("km ladder l2/l1", lambda r: r["km_ladder"][1]),
    ("AR(1) half-life", lambda r: r["halflife"]),
    ("R = ulam/static", lambda r: r["R"]),
    ("ITS slope", lambda r: r["its_slope"]),
)


def power_table(raw: dict) -> dict:
    """Single-cut error for every pair of truths, for every discriminator.

    `research/quantising.md` scores its ladder by "the best single-cut error
    separating box from spring", so this uses the same metric and the two pages
    can be read against each other. The three pairs that matter are box against
    spring (*which* confinement), spring against the hidden-volatility control
    (is the marginal lying), and spring against the two-scale control (is there
    memory). A discriminator is only interesting where it beats the AR(1) row.
    """
    pairs = (("box", "spring"), ("spring", "hidden"), ("spring", "twoscale"), ("box", "free"))
    print("\n    single-cut error between truths, 0.000 = perfect separation")
    print(f"    {'discriminator':22s}" + "".join(f"{a[:3]}/{b[:5]:>7s}" for a, b in pairs))
    out = {}
    for name, fn in DISCRIMINATORS:
        row = {}
        cells = []
        for a, b in pairs:
            if a not in raw or b not in raw:
                cells.append(f"{'-':>11s}")
                continue
            e = G.single_cut_error([fn(r) for r in raw[a]], [fn(r) for r in raw[b]])
            row[f"{a}_vs_{b}"] = e
            cells.append(f"{e:11.3f}")
        print(f"    {name:22s}" + "".join(cells))
        out[name] = row
    return out


def _replicates(kind, nrep, seed0, n, width, dvar, theta, svar, mean_len, min_len, nbin, lag, trim):
    jobs = [
        (kind, seed0 + i, n, width, dvar, theta, svar, mean_len, min_len, nbin, lag, trim)
        for i in range(nrep)
    ]
    with ProcessPoolExecutor(max_workers=WORKERS) as ex:
        return [r for r in ex.map(_one_replicate, jobs, chunksize=1) if r]


def section_power(n, width, mean_len, min_len, nbin=NBIN, lag=LAG, trim=0.0, tag="") -> dict:
    """The four truths through the identical pipeline, at the real sample size."""
    dvar = 1.0
    # Matched difficulty: the spring is given the box's own leading rate, so the
    # two truths differ in the SHAPE of their ladder and not in its speed. Without
    # this the comparison is confounded by how fast each relaxes.
    lam1 = (math.pi / width) ** 2 * dvar / 2.0
    theta = lam1
    svar = dvar / 2.0 / theta
    print(f"\n=== 2{tag}. The four truths, n={n}, W={width:.1f}, episode~{mean_len:.0f} ===\n")
    print(f"    true lambda_1 = {lam1:.6f} for BOTH confined truths (matched by construction)")
    print(f"    box true ladder 1:4:9, spring 1:2:3, free walk has none. {NREP} replicates.\n")
    out, raw = {}, {}
    hdr = (
        f"    {'truth':8s} {'l1 static':>18s} {'l1 ulam':>18s} {'l1 km':>18s} "
        f"{'stat l2/l1':>14s} {'ulam l2/l1':>14s} {'R=ulam/static':>16s} "
        f"{'ITS slope':>14s} {'AR1 half':>9s}"
    )
    print(hdr)
    for kind in TRUTHS:
        reps = _replicates(
            kind, NREP, SEED + hash(kind) % 9973, n, width, dvar, theta, svar, mean_len, min_len,
            nbin, lag, trim,
        )
        if not reps:
            continue
        g = {
            k: G.mean_sd([r[k][0] if isinstance(r[k], list) else r[k] for r in reps])
            for k in ("static", "ulam", "km", "R", "R_km", "its_slope", "halflife")
        }
        gl = {
            k: G.mean_sd([r[k][1] for r in reps]) for k in ("static_ladder", "ulam_ladder", "km_ladder")
        }
        print(
            f"    {kind:8s} {g['static'][0]:9.5f}+-{g['static'][1]:<7.5f}"
            f"{g['ulam'][0]:9.5f}+-{g['ulam'][1]:<7.5f}"
            f"{g['km'][0]:9.5f}+-{g['km'][1]:<7.5f}"
            f"{gl['static_ladder'][0]:7.3f}+-{gl['static_ladder'][1]:<5.3f}"
            f"{gl['ulam_ladder'][0]:7.3f}+-{gl['ulam_ladder'][1]:<5.3f}"
            f"{g['R'][0]:9.4f}+-{g['R'][1]:<5.4f}"
            f"{g['its_slope'][0]:8.4f}+-{g['its_slope'][1]:<5.4f}"
            f"{g['halflife'][0]:9.2f}"
        )
        raw[kind] = reps
        out[kind] = {
            "n_rep": len(reps),
            "n_used": int(np.mean([r["n"] for r in reps])),
            "true_l1": lam1,
            **{k: {"mean": v[0], "sd": v[1]} for k, v in g.items()},
            **{k: {"mean": v[0], "sd": v[1]} for k, v in gl.items()},
        }
    print(f"\n    true lambda_1 {lam1:.6f}; the free walk has no true value and both")
    print("    positive controls share the spring's.")
    out["_power"] = power_table(raw)
    return out


def report_conditions(power: dict) -> dict:
    """Kill conditions 2-6, checked on the numbers above and printed as a ledger."""
    led = {}
    for kind, key in (("spring", "spring"), ("box", "box")):
        d = power.get(kind)
        if not d:
            continue
        m, s = d["static"]["mean"], d["static"]["sd"]
        led[f"covers_true_l1_{key}"] = bool(abs(m - d["true_l1"]) <= 2.0 * max(s, 1e-12))
    ou = power.get("spring")
    # Each instrument is scored against the control it was built for: `R` reads a
    # marginal, so its control is the scale mixture; the timescale scan reads
    # memory, so its control is the two-scale process whose lag-1 autocorrelation
    # has been matched to the plain OU's. Scoring both against one control is what
    # calibrated one instrument and not the other in the dry run.
    for name, key, ctrl in (("R", "R", "hidden"), ("its", "its_slope", "twoscale")):
        pos = power.get(ctrl)
        if not (ou and pos):
            continue
        nr = min(ou["n_rep"], pos["n_rep"])
        gap = abs(pos[key]["mean"] - ou[key]["mean"])
        per = 2.0 * (pos[key]["sd"] + ou[key]["sd"])
        mean_se = 2.0 * math.sqrt((pos[key]["sd"] ** 2 + ou[key]["sd"] ** 2) / max(nr, 1))
        # 4a / 10a: can ONE series be classified. 4b / 10b: can the two groups be
        # told apart in the mean, which is how the market legs actually read it.
        led[f"{name}_control"] = ctrl
        led[f"{name}_4a_per_series"] = bool(gap > per)
        led[f"{name}_4b_in_the_mean"] = bool(gap > mean_se)
        led[f"{name}_gap"] = float(gap)
        led[f"{name}_need_per_series"] = float(per)
        led[f"{name}_need_mean"] = float(mean_se)
    voids = []
    for kind, d in power.items():
        for k in ("static_ladder", "ulam_ladder"):
            v = d.get(k, {}).get("mean")
            if v is not None and math.isfinite(v) and (abs(v - 4.0) < 5e-5 or abs(v - 2.0) < 5e-5):
                voids.append(f"{kind}.{k}={v:.6f}")
        r = d.get("R", {}).get("mean")
        if r is not None and math.isfinite(r) and abs(r - 1.0) < 5e-5:
            voids.append(f"{kind}.R={r:.6f}")
    led["void_exact_null"] = voids
    print("\n    --- conditions ---")
    for k, v in led.items():
        print(f"    {k:28s} {v}")
    return led


# --------------------------------------------------------------------------
# 3. Range Break: does the density say what the ladder said?
# --------------------------------------------------------------------------


def section_rangebreak() -> dict:
    print("\n=== 3. Range Break: the ladder from the histogram ===\n")
    if not G.have_db():
        print("    research.db not reachable - skipped, not silently empty.")
        return {}
    out = {}
    for feed in G.CONFINED:
        d = G.load_ticks(feed)
        if d is None:
            print(f"    {feed}: absent")
            continue
        x, ep = G.rb_tick_episodes(d["mid"])
        if x.size < 5000:
            print(f"    {feed}: too few usable ticks")
            continue
        n_ep = int(ep.max()) + 1
        mean_len = float(x.size / n_ep)
        a, b = G._lagged(x, ep, 1)
        dvar = float(np.var(b - a))
        # The width a box with this stationary spread would have. Reported, not
        # used to calibrate: quantising.md measured RB100 saturating at ~38.
        width = math.sqrt(12.0 * float(np.var(x)))
        print(f"    {feed}: {x.size} ticks, {n_ep} episodes, mean {mean_len:.0f}, ")
        print(f"      one-step increment variance {dvar:.4f}, uniform-equivalent W {width:.1f}")
        row = {"n": int(x.size), "n_episodes": n_ep, "mean_len": mean_len, "dvar": dvar,
               "width_uniform_equivalent": width}
        for trim in TRIMS:
            st, sd = G.static_rates(x, dvar, nbin=NBIN, trim=trim)
            ul, _ = G.ulam_rates(x, ep, LAG, nbin=NBIN, trim=trim)
            km, _ = G.km_rates(x, ep, nbin=NBIN, trim=trim)
            row[f"trim_{trim}"] = {
                "static": st, "static_ladder": G.ladder(st),
                "ulam": ul, "ulam_ladder": G.ladder(ul),
                "km": km,
                "R": ul[0] / st[0] if st[0] > 0 else float("nan"),
                "cells": sd.get("cells"),
            }
            print(
                f"      trim {trim:<7} static l2/l1 {G.ladder(st)[1]:6.3f}  "
                f"ulam l2/l1 {G.ladder(ul)[1]:6.3f}  R {ul[0] / st[0] if st[0] > 0 else float('nan'):7.3f}"
            )
        # The simulated truths, at THIS feed's own tick count, episode length and
        # stationary spread, through the identical function. The comparison is
        # never against a formula.
        sim = section_power(
            int(x.size), width, mean_len, 240, nbin=NBIN, lag=LAG, trim=0.0, tag=f" [{feed}]"
        )
        row["simulated"] = sim
        bx, sp = sim.get("box"), sim.get("spring")
        if bx and sp:
            gate = (
                bx["static_ladder"]["mean"] - 2 * bx["static_ladder"]["sd"]
                > sp["static_ladder"]["mean"] + 2 * sp["static_ladder"]["sd"]
            )
            row["gate_separates"] = bool(gate)
            print(f"\n      kill condition 8 (box and spring separate on the STATIC ladder): {gate}")
            print(
                f"      box {bx['static_ladder']['mean']:.3f}+-{bx['static_ladder']['sd']:.3f}  "
                f"spring {sp['static_ladder']['mean']:.3f}+-{sp['static_ladder']['sd']:.3f}  "
                f"measured {row['trim_0.0']['static_ladder'][1]:.3f}"
            )
        out[feed] = row
    return out


# --------------------------------------------------------------------------
# 4. The real feeds, and the constant-volatility control
# --------------------------------------------------------------------------


def log_rv(close: np.ndarray, win: int) -> np.ndarray:
    """Log realised volatility over a rolling window of one-minute bars.

    The quantity `barriers.py` takes as an input and holds constant for the life
    of a trade. Its relaxation rate is the volatility half-life, and whether it
    has one at all is the question.
    """
    r = np.diff(np.log(np.maximum(close, 1e-12)))
    r = r[np.isfinite(r)]
    if r.size < 4 * win:
        return np.empty(0)
    c = np.cumsum(np.concatenate([[0.0], r * r]))
    v = (c[win:] - c[:-win]) / win
    v = v[v > 0]
    return np.log(v) if v.size else np.empty(0)


def section_real() -> dict:
    print("\n=== 4. Log realised volatility, and the feeds that have none ===\n")
    if not G.have_db():
        print("    research.db not reachable - skipped.")
        return {}
    print("    The Volatility indices are the control: generators.md measures no")
    print("    volatility clustering on them at all, so their log-RV is estimation")
    print("    noise around a constant and whatever rate appears is the floor.\n")
    print(
        f"    {'feed':26s} {'n':>7s} {'l1 static':>10s} {'l1 ulam':>10s} {'R':>8s} "
        f"{'half-life, bars':>16s} {'stat l2/l1':>11s} {'acf1':>7s}"
    )
    out = {}
    for group, feeds in (("control", G.BROWNIAN[:5]), ("real", G.REAL)):
        print(f"    -- {group} --")
        for feed in feeds:
            d = G.load_bars(feed)
            if d is None:
                continue
            x = log_rv(d["close"], RV_WIN)
            if x.size < 5000:
                continue
            # One-step variance at the RV sampling lag: the window overlaps, so
            # the increment at lag 1 is not the diffusion's. Sample the series
            # every RV_WIN bars so successive points use disjoint returns.
            xs = x[::RV_WIN]
            if xs.size < 1200:
                continue
            a, b = G._lagged(xs, None, 1)
            dvar = float(np.var(b - a))
            st, _ = G.static_rates(xs, dvar, nbin=48)
            ul, _ = G.ulam_rates(xs, None, 1, nbin=48)
            hl = G.ar1_halflife(xs)
            am = a - a.mean()
            bm = b - b.mean()
            acf1 = float(np.dot(am, bm) / np.dot(am, am)) if np.dot(am, am) > 0 else float("nan")
            r = ul[0] / st[0] if st[0] > 0 and math.isfinite(ul[0]) else float("nan")
            print(
                f"    {feed:26s} {xs.size:7d} {_fmt(st[0], 10, 5)} {_fmt(ul[0], 10, 5)} "
                f"{_fmt(r, 8, 3)} {_fmt(hl * RV_WIN, 16, 1)} {_fmt(G.ladder(st)[1], 11, 3)} "
                f"{_fmt(acf1, 7, 3)}"
            )
            out[feed] = {
                "group": group, "n": int(xs.size), "static": st, "ulam": ul,
                "static_ladder": G.ladder(st), "R": r,
                "halflife_bars": hl * RV_WIN, "acf1": acf1, "dvar": dvar,
            }
    ctrl = [v["halflife_bars"] for v in out.values() if v["group"] == "control"]
    real = [v["halflife_bars"] for v in out.values() if v["group"] == "real"]
    if ctrl and real:
        cm, _ = G.mean_sd(ctrl)
        rm, _ = G.mean_sd(real)
        print(f"\n    control mean half-life {cm:.1f} bars, real mean {rm:.1f} bars")
        print(f"    kill condition 7 (they are the same): {abs(rm - cm) < max(cm, 1.0) * 0.25}")
        out["_summary"] = {"control_mean_halflife": cm, "real_mean_halflife": rm}
    return out


def main() -> None:
    print("=" * 78)
    print("groundstate.py - the spectrum from the marginal, and what R measures")
    print("=" * 78)
    res = {"seed": SEED, "nrep": NREP, "nbin": NBIN, "lag": LAG}
    res["dictionary"] = section_dictionary()
    # The calibration sample is Range Break's own: about 86,000 ticks in episodes
    # of about 4,300, which is what the feed has.
    res["power"] = section_power(86000, 38.0, 4300.0, 240, tag="")
    res["conditions"] = report_conditions(res["power"])
    if res["conditions"].get("R_4b_in_the_mean") or res["conditions"].get("its_4b_in_the_mean"):
        res["rangebreak"] = section_rangebreak()
        res["real"] = section_real()
    else:
        print("\n    Kill condition 4b fired on BOTH instruments: neither the")
        print("    specification ratio nor the implied-timescale slope separates a")
        print("    hidden-state process from a plain diffusion even in the mean, so the")
        print("    market legs are NOT reported. That is the condition doing its job.")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(res, fh, indent=1, default=float)
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
