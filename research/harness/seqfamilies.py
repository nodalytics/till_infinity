"""What the rest of the Deriv book is made of, measured before anything is modelled.

The sequence-model study is six arms on one floor. Five of them cover the
Volatility family, where `research/deriving.md`'s theorem and
`research/rebuilding.md`'s `n*` have closed the question: a Volatility index is
geometric Brownian motion at a published constant sigma, its increments are
independent by construction, and a direction arm there is a null calibration
rather than a hunt. **This arm covers everything else, and everything else is
not one process.**

That distinction is the whole reason this file exists rather than a `for family
in SYNTHETIC` loop inside one of the other five. Boom is a compound Poisson.
Step is a lattice walk. Drift Switch is - by its own name - a Markov-modulated
drift. These have genuinely different internal structure, a sequence model has
genuinely different things to find in each, and pooling them produces a mean of
six answers to six questions.

## The distinction this page is built on, because it is the one this folder keeps flattening

`deriving.md` proves `E[net] = -(c/2) x turnover` for **any predictable position
on a martingale**. Its own limits section says what that does not cover:

> **The theorem is about expectancy, not about outcomes.** `E[net] = -c` says a
> strategy loses on average. It says nothing about the variance.

A **predictable conditional variance is not a violation of it.** Neither is a
predictable spike hazard, a predictable dwell time or a predictable step size.
`deriving.md` demonstrates this on Range Break itself: the break arrival is
memoryless at 86.5 minutes, `P(break inside four hours) = 0.938` on RB100, the
process between breaks is sub-diffusive by a factor of 3.6 - and "**That is a
variance statement. The mean is still zero.**" So "structure exists" and
"structure is tradeable after costs" are two claims, the theorem bears on the
second and not the first, and every section below reports them separately.

`research/spending.md` is why the first one is worth having anyway: the desk's
measured failure is not its direction calls, it is that it "realise[s] **half**
the payoff the entries were sized for - 0.70 against 1.36 - and that halving is
the entire loss". A conditional estimate is what fixes a payoff. A direction
call is not.

## What is already known, and is therefore not re-run here

Re-measuring a settled number on a worse sample is the most common way a page in
this folder has been wrong, so the inventory comes before the plan:

* **Step Index** is tier 1. `research/generators.md`: 86,391 of 86,393 tick
  moves are exactly 0.1, and `p(up) = 0.499734 +- 0.000220` over 5.18M implied
  flips. **Not re-run.** The other eight members of the family have never been
  measured at all, and that is section two.
* **Range Break** is measured twice over. `deriving.md` has the break rate at
  86.6 and 178.9 minutes with CV 1.003 and 1.075 over sixty days and 998/483
  breaks, and the sub-diffusion at 3.6x and 8.9x; `research/quantising.md` has
  the relaxation ladder at `l2/l1` 2.076 and 1.976, which refutes its own
  pre-registered band of 2 to 4 from below. **Not re-run**, and section four
  says what is left open and why this sample cannot close it.
* **Boom and Crash at 300, 500 and 1000** have a rate, a grind, a jump size and
  a closure from `generators.md`. Those are not re-run either. **What is re-run
  is the waiting-time test**, and section one is why.
* **Boom/Crash at 50, 100, 150, 200, 600 and 900; every Step variant but the
  base; Jump's waiting time; all three Drift Switch; all six DEX** have never
  been measured anywhere in this folder. That is most of this page.

## The kill conditions, written before any number was read

1. **The detector is a detector artefact** if the spike rate moves with the
   threshold. `generators.md` found identical counts at 5x, 10x and 20x on six
   feeds; if that fails on the twelve feeds it never covered, the rate is not a
   property of the generator and section one reports nothing.
2. **The hazard result is void** if the simulated compound Poisson - built from
   the feed's own grind and spike pools at the feed's own rate, and passed
   through the identical detector - does not return CV 1.00, Fano 1.00 and
   acf1 0.00 within its own replicate band. A null that does not know it is a
   null cannot say anything about the feed.
3. **The Skew Step reading is wrong** if `p_up * E[up] + (1 - p_up) * E[down]`
   does not close to zero within three standard errors. An asymmetric generator
   that is not a martingale would contradict `generators.md`'s four-way
   verification on all 26 synthetics, and the first suspect would be this
   file's arithmetic.
4. **The Drift Switch claim is void** if the variance ratio on the *shuffled*
   returns is not 1.00 within its band. Shuffling destroys the switching and
   nothing else, so a shuffle that is still super-diffusive means the estimator
   is reading its own overlap.
5. **A hidden-state model has found nothing** if the dwell time it reports on a
   phase surrogate is within a factor of two of the dwell time it reports on
   the feed. An EM fit always returns states; the question is never whether it
   found them.
6. **The wall clock is the wrong clock** and any next-bar spike number taken
   from it is withdrawn, if the mean spike count per bar is not inside roughly
   [0.05, 1.0]. Above 1 the answer to "will a spike happen next bar" is yes and
   the classifier is scoring a constant; below 0.05 there are no positives left
   to score.

    ./.secrets/lab.sh run research/harness/seqfamilies.py
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("MKL_NUM_THREADS", "2")

import numpy as np  # noqa: E402

from research.harness import seqlab  # noqa: E402

#: Four processes at two threads each. Five sibling arms share this box and the
#: cap in the brief is eight.
WORKERS = 4

#: Replicates of the family null per symbol. Two hundred puts the 2.5th and
#: 97.5th percentile of the null band on five draws each, which is coarse for a
#: tail and adequate for the two-sided z this page actually reports.
REPLICATES = 200

#: Where the tables land, for `fammodels.py` and for the page.
OUT = Path.home() / "till_infinity" / "data" / "families"

#: Ticks between spikes, as the instrument name claims it. Boom and Crash put
#: the rate in the name. **Jump does not** - the number in `Jump 75 Index` is
#: the annualised volatility, and the published jump rate is one every twenty
#: minutes, which is 1,200 ticks on a one-second feed, for all five. DEX's
#: number is a guess from the naming pattern and is tested rather than assumed.
def nominal(symbol: str) -> float:
    fam = seqlab.FAMILY_OF.get(symbol, "")
    if fam in ("boom", "crash"):
        return float(symbol.split()[1])
    if fam == "jump":
        return 1200.0
    if fam == "dex":
        return float(symbol.split()[1])
    return float("nan")


#: What `famticks.py` actually pulled, per family. `seqlab.tick_cache` re-pulls
#: when the file on disk holds less than 85% of what it is asked for, so asking
#: for the default 250,000 against a Step cache of 200,000 silently re-pulls
#: every Step symbol and the two Range Break ones. Same numbers, one place.
WANT = {"boom": 300_000, "crash": 300_000, "dex": 300_000, "jump": 300_000,
        "step": 200_000, "drift_switch": 200_000, "range_break": 120_000}


def want_for(symbol: str) -> int:
    return WANT.get(seqlab.FAMILY_OF.get(symbol, ""), 200_000)


def _bid(t: dict[str, np.ndarray]) -> np.ndarray:
    """The bid, not the mid.

    `research/rebuilding.md` established that the mid takes a half-grid step
    every time the spread changes - on 33% to 64% of Boom/Crash ticks - so the
    mid's apparent lattice is 0.0005 where the real one is 0.001, and raw float
    differences of the mid separate `crash_500` from its own rebuild at AUC
    0.0242 on an artefact. Every increment on this page is a bid increment.
    """
    b = t["bid"]
    return b if np.isfinite(b).all() and b.max() > 0 else t["mid"]


# --------------------------------------------------------------------------
# Section one: the spike hazard
# --------------------------------------------------------------------------


def hazard_arm(symbol: str, replicates: int = REPLICATES, seed: int = 11) -> dict:
    """Is the waiting time between spikes memoryless, at a sample that can tell?

    `generators.md` answered this with a coefficient of variation on 86 to 306
    spikes and got 0.844 to 1.103 against a Poisson's 1.000. The standard error
    of a CV on 94 draws is 0.073, so that range is two standard errors wide and
    the conclusion "memoryless across the whole family" is a failure to reject
    at a power that could not have rejected a gamma renewal at shape 1.2.

    So: the same detector, three times the ticks on the slowest member, twelve
    feeds that were never covered, and five statistics instead of one - each
    against a simulated compound Poisson built from this feed's own pools and
    put through the identical detector, so the null band is a finite-sample
    band and not a textbook one.
    """
    rng = np.random.default_rng(seed)
    ticks = seqlab.tick_cache(symbol, want_for(symbol))
    if len(ticks.get("time", ())) < 5_000:
        return {"symbol": symbol, "skip": f"{len(ticks.get('time', ()))} ticks"}

    price = _bid(ticks)
    moves = np.diff(price)
    row: dict = {
        "symbol": symbol, "family": seqlab.FAMILY_OF.get(symbol, "?"),
        "n_ticks": len(price), "nominal": nominal(symbol),
        "hours": float((ticks["time"][-1] - ticks["time"][0]) / 3600.0),
        "median_gap_ms": float(np.median(np.diff(ticks["time"])) * 1000.0),
    }

    # Kill condition 1: the rate must not move with the threshold.
    by_mult = {}
    for m in seqlab.SPIKE_MULTS:
        s = seqlab.spikes(moves, m)
        by_mult[m] = {"n": s["n_spikes"], "per": s["per_spike"]}
    row["by_mult"] = by_mult
    rates = [v["per"] for v in by_mult.values() if np.isfinite(v["per"])]
    row["mult_spread"] = (float(max(rates) / min(rates)) if len(rates) == 3 and min(rates) > 0
                          else float("nan"))

    det = seqlab.spikes(moves, 10.0)
    if det["n_spikes"] < 25:
        row["skip"] = f"{det['n_spikes']} spikes at 10x"
        return row

    grind, jump = det["grind"], det["spike"]
    p_hat = det["n_spikes"] / det["n_moves"]
    row.update({
        "n_spikes": det["n_spikes"], "per_spike": det["per_spike"],
        "rate_ratio": float(det["per_spike"] / nominal(symbol)) if np.isfinite(nominal(symbol)) else float("nan"),
        "median_abs_move": det["median_abs"],
        "grind_mean": float(grind.mean()), "grind_cv": float(np.std(np.abs(grind)) / max(np.mean(np.abs(grind)), 1e-12)),
        "spike_median": float(np.median(np.abs(jump))), "spike_mean": float(jump.mean()),
        "spike_over_grind": float(np.median(np.abs(jump)) / max(np.median(np.abs(grind)), 1e-12)),
        "spike_up_frac": float((jump > 0).mean()), "grind_up_frac": float((grind > 0).mean()),
    })

    # Martingale closure, the arithmetic `generators.md` used: does the spike
    # pay for the grind? A z past 2 would put the feed, not the model, in doubt.
    drift = float(moves.mean())
    se = float(moves.std(ddof=1) / math.sqrt(len(moves)))
    row["closure_z"] = float(drift / max(se, 1e-18))
    row["drift_per_tick"] = drift

    gaps = np.diff(det["idx"]).astype(float)
    obs = seqlab.hazard(gaps)
    row["obs"] = {k: v for k, v in obs.items() if k not in ("hz", "hz_edges")}
    row["hz"], row["hz_edges"] = obs["hz"], obs["hz_edges"]

    # The family null, through the identical detector.
    keys = ("cv", "ks", "fano", "acf1", "hz_ratio", "hz_slope", "min_gap", "mean")
    draws = {k: [] for k in keys}
    n_sim = min(len(moves), 400_000)
    for _ in range(replicates):
        path = seqlab.compound_poisson_ticks(grind, jump, p_hat, n_sim, rng)
        sm = np.diff(path)
        sd = seqlab.spikes(sm, 10.0)
        if sd["n_spikes"] < 25:
            continue
        h = seqlab.hazard(np.diff(sd["idx"]).astype(float))
        for k in keys:
            draws[k].append(h[k])
    row["null"] = {}
    for k in keys:
        d = np.asarray(draws[k], float)
        d = d[np.isfinite(d)]
        if len(d) < 20:
            row["null"][k] = {"mean": float("nan"), "sd": float("nan"), "z": float("nan"), "p": float("nan")}
            continue
        mu, sd_ = float(d.mean()), float(d.std(ddof=1))
        z = (obs[k] - mu) / max(sd_, 1e-18) if np.isfinite(obs[k]) else float("nan")
        # Two-sided simulated p: how often the null is at least this far out.
        p = float((np.abs(d - mu) >= abs(obs[k] - mu)).mean()) if np.isfinite(obs[k]) else float("nan")
        row["null"][k] = {"mean": mu, "sd": sd_, "z": float(z), "p": p, "draws": len(d)}
    row["null_replicates"] = replicates
    return row


# --------------------------------------------------------------------------
# Section two: the Step lattice, and whether Skew Step's name is true
# --------------------------------------------------------------------------


def skew_prediction(symbol: str) -> dict:
    """The name, read as a falsifiable claim, before the data is opened.

    `Skew Step Index 4 Up` names an asymmetry and a number. The reading taken
    here - pre-registered, so that being wrong is a result rather than a
    revision - is that the number is the **size ratio**, and that the generator
    is a martingale, which forces the probability:

        up move = k units, down move = 1 unit, and a martingale needs
        p_up * k = (1 - p_up) * 1, so p_up = 1 / (1 + k).

    So `4 Up` predicts `p_up = 0.2000` with up moves four times the size of down
    moves, and `5 Up` predicts `p_up = 0.1667` at five times. The `Down`
    variants mirror it. This is one of three readings that the name permits -
    the others being skew in probability alone (sizes equal, `p_up != 0.5`) and
    skew in size alone (which cannot be a martingale) - and section two reports
    which of the three the feed actually is.
    """
    parts = symbol.split()
    k = float(parts[-2]) if parts[-1] in ("Up", "Down") else float("nan")
    up = parts[-1] == "Up"
    if not np.isfinite(k):
        return {"predicts": False}
    p_up = 1.0 / (1.0 + k) if up else k / (1.0 + k)
    return {"predicts": True, "k": k, "side": "up" if up else "down",
            "p_up": p_up, "size_ratio": k if up else 1.0 / k}


def step_arm(symbol: str, replicates: int = REPLICATES, seed: int = 13) -> dict:
    """The increment law of a Step-family feed, on ticks, where the increment lives.

    A three-minute bar has summed a hundred and eighty increments and the
    lattice is gone. Everything here is a tick-to-tick bid move.
    """
    rng = np.random.default_rng(seed)
    ticks = seqlab.tick_cache(symbol, want_for(symbol))
    if len(ticks.get("time", ())) < 5_000:
        return {"symbol": symbol, "skip": f"{len(ticks.get('time', ()))} ticks"}
    price = _bid(ticks)
    moves = np.diff(price)
    nz = moves[moves != 0.0]
    n = len(moves)
    row: dict = {
        "symbol": symbol, "family": "step", "n_ticks": len(price), "n_moves": n,
        "hours": float((ticks["time"][-1] - ticks["time"][0]) / 3600.0),
        "frac_zero": float((moves == 0.0).mean()),
    }

    # The lattice: how many distinct magnitudes, and how concentrated.
    mag = np.round(np.abs(nz), 8)
    vals, counts = np.unique(mag, return_counts=True)
    order = np.argsort(-counts)
    row["n_distinct_mag"] = int(len(vals))
    row["top_mag"] = [(float(vals[i]), int(counts[i]), float(counts[i] / len(mag)))
                      for i in order[:6]]
    row["top1_share"] = float(counts[order[0]] / len(mag)) if len(mag) else float("nan")
    # How many magnitudes are needed to cover 99% of moves - the honest answer
    # to "is Multi Step 3 a three-valued step" when a feed has float dust.
    share = np.sort(counts / len(mag))[::-1]
    row["mags_to_99"] = int(np.searchsorted(np.cumsum(share), 0.99) + 1)

    up, down = nz[nz > 0], nz[nz < 0]
    p_up = float(len(up) / len(nz))
    se_p = math.sqrt(p_up * (1 - p_up) / len(nz))
    row.update({
        "p_up": p_up, "se_p_up": se_p,
        "z_vs_fair": float((p_up - 0.5) / max(se_p, 1e-18)),
        "e_up": float(up.mean()) if len(up) else float("nan"),
        "e_down": float(down.mean()) if len(down) else float("nan"),
        "size_ratio": float(up.mean() / abs(down.mean())) if len(down) and down.mean() != 0 else float("nan"),
        "n_up": len(up), "n_down": len(down),
    })
    # Halves, because `generators.md`'s documented trap on this family was a
    # tick-sample bias that the bar sample refuted - a statistic that does not
    # hold in both halves of its own sample is not a statistic.
    half = len(nz) // 2
    row["p_up_halves"] = [float((nz[:half] > 0).mean()), float((nz[half:] > 0).mean())]

    drift = float(moves.mean())
    se_d = float(moves.std(ddof=1) / math.sqrt(n))
    row["closure_z"] = float(drift / max(se_d, 1e-18))
    row["drift_per_tick"] = drift

    row["name_test"] = skew_prediction(symbol)
    if row["name_test"].get("predicts"):
        pred = row["name_test"]
        row["name_test"]["p_up_z"] = float((p_up - pred["p_up"]) / max(se_p, 1e-18))
        row["name_test"]["ratio_obs"] = row["size_ratio"]

    # Independence: sign acf at lags 1..30 against the +-3/sqrt(n) band that
    # `genstep.py` uses, and a Wald-Wolfowitz runs z.
    s = np.sign(nz)
    band = 3.0 / math.sqrt(len(s))
    acf = []
    for lag in range(1, 31):
        a, b = s[:-lag] - s.mean(), s[lag:] - s.mean()
        d = math.sqrt(float((a * a).sum()) * float((b * b).sum()))
        acf.append(float((a * b).sum() / d) if d > 0 else 0.0)
    row["acf_band"] = band
    row["acf_out"] = int(sum(abs(v) > band for v in acf))
    row["acf1"] = acf[0]
    row["acf_max"] = float(max(acf, key=abs))
    runs = 1 + int((s[1:] != s[:-1]).sum())
    n1, n2 = len(up), len(down)
    mu_r = 2 * n1 * n2 / len(s) + 1
    var_r = (mu_r - 1) * (mu_r - 2) / max(len(s) - 1, 1)
    row["runs_z"] = float((runs - mu_r) / math.sqrt(max(var_r, 1e-18)))

    # The family null: the same lattice, the same skew, independent by
    # construction. `gbm_bars` would be the wrong null here and the difference
    # is not cosmetic - a Gaussian null has no lattice at all, so every lattice
    # statistic would separate it and none of them would mean anything.
    u = float(up.mean()) if len(up) else 1.0
    d = float(abs(down.mean())) if len(down) else 1.0
    draws = {"acf1": [], "runs_z": [], "p_up": []}
    for _ in range(min(replicates, 60)):
        sim = seqlab.step_ticks(u, d, p_up, min(n, 200_000), rng)
        sm = np.diff(sim)
        ss = np.sign(sm[sm != 0])
        a, b = ss[:-1] - ss.mean(), ss[1:] - ss.mean()
        dd = math.sqrt(float((a * a).sum()) * float((b * b).sum()))
        draws["acf1"].append(float((a * b).sum() / dd) if dd > 0 else 0.0)
        r = 1 + int((ss[1:] != ss[:-1]).sum())
        m1, m2 = int((ss > 0).sum()), int((ss < 0).sum())
        mr = 2 * m1 * m2 / len(ss) + 1
        vr = (mr - 1) * (mr - 2) / max(len(ss) - 1, 1)
        draws["runs_z"].append(float((r - mr) / math.sqrt(max(vr, 1e-18))))
        draws["p_up"].append(float((ss > 0).mean()))
    row["null"] = {k: {"mean": float(np.mean(v)), "sd": float(np.std(v, ddof=1))}
                   for k, v in draws.items() if len(v) > 3}
    return row


# --------------------------------------------------------------------------
# Section three: Drift Switch, the one family where a recurrent net has a job
# --------------------------------------------------------------------------


def variance_ratio(r: np.ndarray, ks: tuple[int, ...]) -> dict[int, float]:
    """`Var(sum of k returns) / (k * Var(r))`. One for a martingale, at every k.

    **This is the cheap statistic that decides whether Drift Switch needs a
    model at all.** A drift that persists for a few hundred bars and then flips
    makes the sum of returns over that horizon more variable than k independent
    draws - super-diffusion - and the horizon where the ratio peaks *is* the
    dwell time, read off without fitting anything. `deriving.md` used the same
    estimator in the other direction on Range Break, where reflection makes it
    sub-diffusive by 3.6x.
    """
    r = np.asarray(r, float)
    r = r[np.isfinite(r)]
    v1 = float(r.var(ddof=1))
    out = {}
    for k in ks:
        if len(r) < 20 * k or k < 1:
            continue
        m = len(r) // k
        agg = r[: m * k].reshape(m, k).sum(axis=1)
        out[k] = float(agg.var(ddof=1) / max(k * v1, 1e-30))
    return out


#: Longest series an EM fit is given. The forward recursion is a Python loop
#: over bars - it has to be, the recursion is sequential - so a 50,000-bar 3m
#: series at 120 iterations is six million small numpy calls and the fit becomes
#: the run. Twenty thousand bars is 833 days at 1h and is far more than a dwell
#: time of tens of bars needs; the cap is stated rather than hidden because a
#: fit on a truncated series is a fit on a truncated series.
HMM_MAX = 20_000


def fit_hmm(r: np.ndarray, k: int = 2, *, iters: int = 80, seed: int = 3) -> dict:
    """A Gaussian HMM by EM, written here because the lab has no `hmmlearn`.

    Returns the fitted means, sigmas and transition matrix, and - the part that
    matters for a walk-forward study - a **causal filter**, `P(state at t |
    returns up to t)`, which is what a real-time user would have. The smoothed
    posterior from forward-backward reads the whole series and is a look-ahead
    if it is used as a feature, which is the standard way this class of study
    leaks.
    """
    r = np.asarray(r, float)
    r = r[np.isfinite(r)]
    n_all = len(r)
    r = r[-HMM_MAX:]
    n = len(r)
    if n < 200:
        return {"ok": False, "n": n}
    rng = np.random.default_rng(seed)
    qs = np.quantile(r, np.linspace(0.15, 0.85, k))
    mu = qs + 1e-9 * rng.standard_normal(k)
    sig = np.full(k, float(r.std(ddof=1)))
    trans = np.full((k, k), 0.05 / max(k - 1, 1))
    np.fill_diagonal(trans, 0.95)
    pi = np.full(k, 1.0 / k)
    ll_last = -np.inf

    for _ in range(iters):
        # Emission likelihoods, scaled forward-backward (no logs needed with scaling).
        e = np.exp(-0.5 * ((r[:, None] - mu) / sig) ** 2) / (sig * math.sqrt(2 * math.pi))
        e = np.maximum(e, 1e-300)
        a = np.empty((n, k)); c = np.empty(n)
        a[0] = pi * e[0]; c[0] = a[0].sum(); a[0] /= max(c[0], 1e-300)
        for t in range(1, n):
            a[t] = (a[t - 1] @ trans) * e[t]
            c[t] = a[t].sum()
            a[t] /= max(c[t], 1e-300)
        b = np.empty((n, k)); b[-1] = 1.0
        for t in range(n - 2, -1, -1):
            b[t] = (trans @ (e[t + 1] * b[t + 1])) / max(c[t + 1], 1e-300)
        g = a * b
        g /= np.maximum(g.sum(axis=1, keepdims=True), 1e-300)
        # Vectorised expected transition counts. The obvious loop over `t` here
        # is six million iterations at 20,000 bars and 80 sweeps, and it was the
        # whole run time before this line replaced it.
        beta_e = e[1:] * b[1:] / np.maximum(c[1:, None], 1e-300)
        xi = trans * (a[:-1].T @ beta_e)
        pi = g[0] / g[0].sum()
        trans = xi / np.maximum(xi.sum(axis=1, keepdims=True), 1e-300)
        w = np.maximum(g.sum(axis=0), 1e-9)
        mu = (g * r[:, None]).sum(axis=0) / w
        sig = np.sqrt(np.maximum((g * (r[:, None] - mu) ** 2).sum(axis=0) / w, 1e-24))
        ll = float(np.log(np.maximum(c, 1e-300)).sum())
        if abs(ll - ll_last) < 1e-7 * max(abs(ll), 1.0):
            break
        ll_last = ll

    order = np.argsort(mu)
    mu, sig = mu[order], sig[order]
    trans = trans[np.ix_(order, order)]
    dwell = 1.0 / np.maximum(1.0 - np.diag(trans), 1e-12)

    # **`dwell` alone is not a persistence statistic, and the smoke run is why
    # this is here.** An EM fit on *shuffled* returns - i.i.d. by construction,
    # no regime left at all - came back with a three-state dwell of [1.6, 7.5,
    # 1.9]. That is not a bug in the shuffle. On i.i.d. data the likelihood is
    # maximised by transition rows equal to the stationary weights, so a state
    # holding 87% of the mass has `p_ii = 0.87` and `1/(1-p_ii) = 7.7` with
    # precisely zero persistence. Reading that 7.5 as a dwell time would have
    # been this page's headline and it would have been an artefact of the state
    # weight.
    #
    # `persist[i] = p_ii / pi_i` is the ratio to that i.i.d. baseline: 1.00 is a
    # mixture with no memory, above 1 is a chain that actually stays put. It is
    # the number every Drift Switch claim on this page is made on.
    evals, evecs = np.linalg.eig(trans.T)
    j = int(np.argmin(np.abs(evals - 1.0)))
    stat = np.real(evecs[:, j])
    stat = np.abs(stat) / max(np.abs(stat).sum(), 1e-18)
    persist = np.diag(trans) / np.maximum(stat, 1e-12)
    return {"ok": True, "n": n, "n_available": n_all, "k": k,
            "mu": mu.tolist(), "sigma": sig.tolist(),
            "trans": trans.tolist(), "dwell": dwell.tolist(), "loglik": ll_last,
            "filtered": (a * 1.0), "pi": pi.tolist(),
            "stationary": stat.tolist(), "persist": persist.tolist(),
            "persist_max": float(persist.max()),
            "sep": float((mu.max() - mu.min()) / max(sig.mean(), 1e-18))}


def hmm_filter(r: np.ndarray, fit: dict) -> np.ndarray:
    """`E[mu | returns up to and including t]` - the causal drift estimate.

    Row `t` uses nothing after `t`, so it is a legal feature for predicting bar
    `t+1`. That is the only version of a hidden-state model this study is
    allowed to score.
    """
    mu = np.asarray(fit["mu"], float); sig = np.asarray(fit["sigma"], float)
    trans = np.asarray(fit["trans"], float); pi = np.asarray(fit["pi"], float)
    r = np.asarray(r, float)
    out = np.full(len(r), np.nan)
    a = pi.copy()
    for t in range(len(r)):
        if not np.isfinite(r[t]):
            out[t] = float(a @ mu)
            continue
        e = np.exp(-0.5 * ((r[t] - mu) / sig) ** 2) / (sig * math.sqrt(2 * math.pi))
        a = (a @ trans) * np.maximum(e, 1e-300)
        s = a.sum()
        a = a / s if s > 0 else np.full(len(mu), 1.0 / len(mu))
        out[t] = float(a @ mu)
    return out


def drift_arm(symbol: str, interval: str = "1h", seed: int = 17) -> dict:
    """Does the drift actually switch, and is the switch visible in real time?

    Two questions and they have different answers. The first is a property of
    the generator and a variance ratio answers it without fitting anything. The
    second is a property of the *filtration* and needs an out-of-sample score.
    """
    rng = np.random.default_rng(seed)
    try:
        bars = seqlab.load(symbol, interval)
    except Exception as exc:  # noqa: BLE001
        return {"symbol": symbol, "interval": interval, "skip": str(exc)[:80]}
    c = bars["close"]
    r = np.diff(np.log(c))
    row: dict = {"symbol": symbol, "family": "drift_switch", "interval": interval,
                 "n_bars": len(c), "n_ret": len(r)}

    ks = tuple(k for k in (2, 5, 10, 20, 50, 100, 200, 400) if len(r) >= 20 * k)
    row["vr"] = variance_ratio(r, ks)
    # Kill condition 4: the shuffle must sit at 1.00. It destroys the switching
    # and nothing else, so it is the control that makes the VR readable.
    sh = r.copy(); rng.shuffle(sh)
    row["vr_shuffle"] = variance_ratio(sh, ks)
    row["vr_surrogate"] = variance_ratio(seqlab.phase_surrogate(r, rng), ks)
    if row["vr"]:
        peak = max(row["vr"], key=lambda k: row["vr"][k])
        row["vr_peak_k"] = int(peak)
        row["vr_peak"] = float(row["vr"][peak])
        row["vr_peak_shuffle"] = float(row["vr_shuffle"].get(peak, float("nan")))

    row["acf1_ret"] = float(np.corrcoef(r[:-1], r[1:])[0, 1]) if len(r) > 10 else float("nan")

    for k in (2, 3):
        fit = fit_hmm(r, k, seed=seed)
        if not fit["ok"]:
            continue
        keep = ("mu", "sigma", "trans", "dwell", "persist", "persist_max",
                "stationary", "loglik", "sep")
        row[f"hmm{k}"] = {q: fit[q] for q in keep}
        # Kill condition 5: the same fit on a surrogate and on a shuffle. An EM
        # fit always returns states; only the comparison says whether they exist.
        for tag, series in (("shuffle", sh), ("surrogate", seqlab.phase_surrogate(r, rng))):
            f2 = fit_hmm(series, k, seed=seed)
            if f2["ok"]:
                row[f"hmm{k}_{tag}"] = {"dwell": f2["dwell"], "sep": f2["sep"],
                                        "persist": f2["persist"],
                                        "persist_max": f2["persist_max"],
                                        "mu": f2["mu"], "sigma": f2["sigma"]}
        # The positive control: refit on a simulation at the fitted parameters,
        # where the state path is known, and check the filter against the truth.
        sim = seqlab.switch_bars(np.asarray(fit["mu"]), np.asarray(fit["sigma"]),
                                 np.asarray(fit["trans"]), min(len(r), 20_000), rng)
        f3 = fit_hmm(sim["ret"], k, seed=seed)
        if f3["ok"]:
            filt = hmm_filter(sim["ret"], f3)
            truth = np.asarray(fit["mu"])[sim["state"]]
            good = np.isfinite(filt) & np.isfinite(truth)
            row[f"hmm{k}_recovery"] = {
                "dwell": f3["dwell"], "sep": f3["sep"],
                "persist": f3["persist"], "persist_max": f3["persist_max"],
                "corr_with_truth": float(np.corrcoef(filt[good], truth[good])[0, 1]),
                "auc_next_sign": float(seqlab.auc(
                    filt[good][:-1], (sim["ret"][good][1:] > 0).astype(float))),
            }
    return row


# --------------------------------------------------------------------------
# Section four: Range Break - the replication, not the study
# --------------------------------------------------------------------------


def range_break_arm(symbol: str, seed: int = 19) -> dict:
    """One cheap check against two settled numbers, and nothing more.

    `deriving.md` has RB100's break arrival at 86.6 minutes with CV 1.003 over
    998 breaks and sixty days, RB200's at 178.9 with CV 1.075 over 483; and
    `quantising.md` has the relaxation ladder at `l2/l1` = 2.076 and 1.976 with
    its pre-registered band of 2 to 4 refuted from below. Three days of ticks
    cannot improve on sixty days of bars and re-running the ladder here would
    produce a worse number with the same name, which is how a folder acquires
    two values for one quantity. This arm exists to confirm the detector in this
    file lands on the published rate, so that section one's detector can be
    trusted on the families that have no published rate to check against.
    """
    ticks = seqlab.tick_cache(symbol, want_for(symbol))
    if len(ticks.get("time", ())) < 5_000:
        return {"symbol": symbol, "skip": f"{len(ticks.get('time', ()))} ticks"}
    price = _bid(ticks)
    moves = np.diff(price)
    row = {"symbol": symbol, "family": "range_break", "n_ticks": len(price),
           "hours": float((ticks["time"][-1] - ticks["time"][0]) / 3600.0)}
    det = seqlab.spikes(moves, 10.0)
    row["n_breaks_10x"] = det["n_spikes"]
    row["ticks_per_break"] = det["per_spike"]
    row["minutes_per_break"] = float(det["per_spike"] * np.median(np.diff(ticks["time"])) / 60.0)
    row["unit_move_frac"] = float((np.abs(np.round(moves, 8)) ==
                                   np.median(np.abs(moves[moves != 0]))).mean())
    if det["n_spikes"] >= 25:
        h = seqlab.hazard(np.diff(det["idx"]).astype(float))
        row["obs"] = {k: v for k, v in h.items() if k not in ("hz", "hz_edges")}
    return row


# --------------------------------------------------------------------------
# Section five: the lag-one autocorrelation, and whether it survives the spread
#
# **This section was not in the plan.** It was added after the smoke run, which
# is recorded here rather than tidied away: `Drift Switch Index 30` came back
# with a lag-one return autocorrelation of **+0.132 on 50,000 15m bars**, which
# is twenty-nine standard errors from zero, and with a variance ratio of 1.50
# against a shuffle at 0.93. A positive return autocorrelation is not a
# volatility statement and it is not a hazard statement. It says
# `E[r_{t+1} | r_t] != 0`, which is the negation of the martingale property -
# **the first assumption of `research/deriving.md`'s theorem, which that page is
# careful to call measured and not assumed**, and which `research/generators.md`
# verified four ways on twenty-six synthetics that did not include this one.
#
# So the theorem may simply not cover this family, and if it does not then the
# question it closes everywhere else is open here. That is a large claim and it
# gets the treatment a large claim needs: the same statistic on every family, on
# a tier-1 fair coin where the answer is known to be zero, on a real market where
# it is known to be negative, at tick resolution as well as bar, in both halves -
# and then the only question that matters, which is whether the predictable part
# is bigger than the spread.
# --------------------------------------------------------------------------


def ljung_box(r: np.ndarray, lags: int = 10) -> dict:
    """Q over the first `lags` autocorrelations, against chi-square on `lags` df.

    One autocorrelation at sixteen standard errors could be one lucky lag out of
    the eight timeframes and eighty-four symbols this study covers. Q pools them,
    and `seqlab.max_of_k` handles the rest of the multiplicity.
    """
    r = np.asarray(r, float)
    r = r[np.isfinite(r)]
    n = len(r)
    if n < 50 * lags:
        return {"q": float("nan"), "p": float("nan"), "n": n, "acf": []}
    x = r - r.mean()
    denom = float((x * x).sum())
    acf = []
    q = 0.0
    for k in range(1, lags + 1):
        c = float((x[:-k] * x[k:]).sum()) / max(denom, 1e-300)
        acf.append(c)
        q += c * c / (n - k)
    q *= n * (n + 2)
    try:
        from scipy import stats
        p = float(stats.chi2.sf(q, lags))
    except Exception:  # noqa: BLE001 - the Q is still readable without a p
        p = float("nan")
    return {"q": float(q), "p": p, "n": n, "acf": [float(v) for v in acf]}


def ar1_after_costs(r: np.ndarray, cost: float, *, folds: int = 5) -> dict:
    """Walk-forward AR(1), position by the sign of the forecast, spread charged.

    **The only question that matters once an autocorrelation is established.**
    `research/deriving.md`'s theorem does not apply to a process that is not a
    martingale, so the arithmetic has to be done rather than cited: fit `beta`
    on the training block, take `w = sign(beta * r_t)` on the test block, and
    report gross, turnover, and

        net = gross - (cost / 2) * turnover

    with `cost` the measured relative spread. `breakeven` is the spread at which
    net reaches zero, `2 * gross / turnover`, and putting it beside the spread
    the broker actually quotes is the whole result. A breakeven under the quoted
    spread is structure that exists and is not tradeable, which is the
    distinction this page is built to keep.
    """
    r = np.asarray(r, float)
    r = r[np.isfinite(r)]
    n = len(r) - 1
    if n < 500:
        return {"n": n}
    x, y = r[:-1], r[1:]
    gross, turn, hits, rows = [], [], [], 0
    for tr, te in seqlab.walk_forward(n, folds=folds, horizon=1):
        if len(tr) < 200 or len(te) < 50:
            continue
        v = float((x[tr] * x[tr]).sum())
        beta = float((x[tr] * y[tr]).sum() / v) if v > 0 else 0.0
        w = np.sign(beta * x[te])
        g = float(np.mean(w * y[te]))
        t = float(np.mean(np.abs(np.diff(np.concatenate([[0.0], w])))))
        gross.append(g)
        turn.append(t)
        hits.append(float(np.mean((w * y[te]) > 0)))
        rows += len(te)
    if not gross:
        return {"n": n}
    g, t = float(np.mean(gross)), float(np.mean(turn))
    out = {"n": n, "rows": rows, "gross": g, "turnover": t,
           "net": g - cost / 2.0 * t, "cost": cost,
           "breakeven": float(2.0 * g / t) if t > 0 else float("nan"),
           "breakeven_over_cost": float(2.0 * g / t / cost) if t > 0 and cost > 0 else float("nan"),
           "hit": float(np.mean(hits)), "folds": len(gross)}

    # **Turnover is the only free variable the theorem leaves**, and on a process
    # that is not a martingale it is the only lever left when gross is real and
    # smaller than the spread. So: stand aside unless the forecast is large, with
    # the threshold picked on the *training* block by net-after-cost and applied
    # unchanged to test. Picking it on test would be the whole finding and it
    # would be a look-ahead.
    best_g, best_t, best_thr, best_rows = [], [], [], 0
    grid = (0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0)
    for tr, te in seqlab.walk_forward(n, folds=folds, horizon=1):
        if len(tr) < 200 or len(te) < 50:
            continue
        v = float((x[tr] * x[tr]).sum())
        beta = float((x[tr] * y[tr]).sum() / v) if v > 0 else 0.0
        scale = float(np.std(beta * x[tr])) or 1e-18
        pick, pick_net = 0.0, -np.inf
        for thr in grid:
            f = beta * x[tr]
            w = np.where(np.abs(f) > thr * scale, np.sign(f), 0.0)
            gg = float(np.mean(w * y[tr]))
            tt = float(np.mean(np.abs(np.diff(np.concatenate([[0.0], w])))))
            nn = gg - cost / 2.0 * tt
            if nn > pick_net:
                pick, pick_net = thr, nn
        f = beta * x[te]
        w = np.where(np.abs(f) > pick * scale, np.sign(f), 0.0)
        best_g.append(float(np.mean(w * y[te])))
        best_t.append(float(np.mean(np.abs(np.diff(np.concatenate([[0.0], w]))))))
        best_thr.append(pick)
        best_rows += len(te)
    if best_g:
        gg, tt = float(np.mean(best_g)), float(np.mean(best_t))
        out["thr"] = {
            "gross": gg, "turnover": tt, "net": gg - cost / 2.0 * tt,
            "breakeven": float(2.0 * gg / tt) if tt > 0 else float("nan"),
            "breakeven_over_cost": float(2.0 * gg / tt / cost) if tt > 0 and cost > 0 else float("nan"),
            "chosen": best_thr, "rows": best_rows,
        }
    return out


def rel_spread(symbol: str) -> float:
    """The quoted spread as a fraction of price, from ticks.

    The bar table's `spread` column is in integer points and the point size is
    not on the wire, so it cannot be turned into a fraction without a lookup
    this harness does not have. The tick route carries bid and ask, so the
    spread is a measurement here rather than a unit conversion.
    """
    try:
        tk = seqlab.tick_cache(symbol, want_for(symbol))
    except Exception:  # noqa: BLE001
        return float("nan")
    if len(tk.get("bid", ())) < 100:
        return float("nan")
    mid = np.maximum(tk["mid"], 1e-12)
    return float(np.median((tk["ask"] - tk["bid"]) / mid))


def acf_arm(symbol: str, interval: str, seed: int = 37) -> dict:
    """Lag-one autocorrelation on bars, with both halves, Q, and the cost test."""
    rng = np.random.default_rng(seed)
    try:
        bars = seqlab.load(symbol, interval)
    except Exception as exc:  # noqa: BLE001
        return {"symbol": symbol, "interval": interval, "skip": str(exc)[:70]}
    r = np.diff(np.log(np.maximum(bars["close"], 1e-12)))
    r = r[np.isfinite(r)]
    n = len(r)
    if n < 400:
        return {"symbol": symbol, "interval": interval, "skip": f"{n} returns"}
    se = 1.0 / math.sqrt(n)

    def a1(v):
        v = np.asarray(v, float)
        v = v[np.isfinite(v)]
        if len(v) < 50 or v.std() == 0:
            return float("nan")
        x = v - v.mean()
        return float((x[:-1] * x[1:]).sum() / max((x * x).sum(), 1e-300))

    half = n // 2
    sh = r.copy(); rng.shuffle(sh)
    lb = ljung_box(r, 10)
    cost = rel_spread(symbol)
    row = {
        "symbol": symbol, "family": seqlab.FAMILY_OF.get(symbol, "control"),
        "interval": interval, "n": n, "se": se,
        "acf1": a1(r), "t": a1(r) / se,
        "acf1_halves": [a1(r[:half]), a1(r[half:])],
        "acf1_shuffle": a1(sh),
        "acf1_surrogate": a1(seqlab.phase_surrogate(r, rng)),
        "lb_q": lb["q"], "lb_p": lb["p"], "acf": lb["acf"],
        "rel_spread": cost,
        "sigma_bar": float(r.std(ddof=1)),
    }
    if np.isfinite(cost) and cost > 0:
        row["ar1"] = ar1_after_costs(r, cost)
    return row


def tick_acf_arm(symbol: str) -> dict:
    """The same statistic at tick resolution, which is where an artefact shows.

    If a bar-scale autocorrelation is an artefact of how bars are cut it will
    not be in the ticks; if it is in the generator it will be in both. That is
    the single cheapest discriminator available and it costs one cached read.
    """
    try:
        tk = seqlab.tick_cache(symbol, want_for(symbol))
    except Exception as exc:  # noqa: BLE001
        return {"symbol": symbol, "skip": str(exc)[:70]}
    if len(tk.get("time", ())) < 5_000:
        return {"symbol": symbol, "skip": "thin"}
    for field in ("bid", "mid"):
        pass
    out = {"symbol": symbol, "family": seqlab.FAMILY_OF.get(symbol, "control"),
           "n_ticks": len(tk["time"])}
    for field in ("bid", "mid"):
        d = np.diff(tk[field])
        d = d[np.isfinite(d)]
        if len(d) < 1000 or d.std() == 0:
            continue
        x = d - d.mean()
        out[f"acf1_{field}"] = float((x[:-1] * x[1:]).sum() / max((x * x).sum(), 1e-300))
        out[f"se_{field}"] = float(1.0 / math.sqrt(len(d)))
        # Lags two to five, because a one-tick echo and a persistent drift look
        # the same at lag one and different immediately after it.
        out[f"acf_{field}"] = [
            float((x[:-k] * x[k:]).sum() / max((x * x).sum(), 1e-300)) for k in range(1, 6)
        ]
    return out


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------


def _job(spec: tuple[str, str, str]) -> dict:
    kind, symbol, extra = spec
    began = time.time()
    try:
        if kind == "hazard":
            out = hazard_arm(symbol)
        elif kind == "step":
            out = step_arm(symbol)
        elif kind == "drift":
            out = drift_arm(symbol)
        elif kind == "acf":
            out = acf_arm(symbol, extra)
        elif kind == "tickacf":
            out = tick_acf_arm(symbol)
        else:
            out = range_break_arm(symbol)
    except Exception as exc:  # noqa: BLE001 - one symbol must not stop the arm
        out = {"symbol": symbol, "kind": kind, "error": f"{type(exc).__name__}: {exc}"[:200]}
    out["kind"] = kind
    out["secs"] = round(time.time() - began, 1)
    return out


def _clean(o):
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, np.ndarray):
        return _clean(o.tolist())
    if isinstance(o, (np.floating, float)):
        v = float(o)
        return v if math.isfinite(v) else None
    if isinstance(o, (np.integer, int)):
        return int(o)
    if isinstance(o, (np.bool_, bool)):
        return bool(o)
    return o


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    jobs: list[tuple[str, str, str]] = []
    for fam in ("boom", "crash", "dex", "jump"):
        jobs += [("hazard", s, "") for s in seqlab.SYNTHETIC[fam]]
    jobs += [("step", s, "") for s in seqlab.SYNTHETIC["step"]]
    jobs += [("drift", s, "") for s in seqlab.SYNTHETIC["drift_switch"]]
    jobs += [("range", s, "") for s in seqlab.SYNTHETIC["range_break"]]
    # Section five, on everything - including the two control groups, because a
    # +0.13 on a synthetic means nothing without a 0.00 on a verified fair coin
    # and a negative number on a real market in the same table.
    every = [s for syms in seqlab.SYNTHETIC.values() for s in syms]
    controls = ["Step Index", "Volatility 75 Index", "Volatility 100 Index",
                "XAUUSD", "EURUSD", "BTCUSD"]
    for s in every + [c for c in controls if c not in every]:
        jobs += [("acf", s, tf) for tf in seqlab.GRID]
    jobs += [("tickacf", s, "") for s in every]

    print(f"seqfamilies - characterising {len(jobs)} symbols before any model")
    print(f"{REPLICATES} null replicates per hazard symbol, {WORKERS} workers\n", flush=True)

    began = time.time()
    rows: list[dict] = []
    with ProcessPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(_job, j): j for j in jobs}
        for i, future in enumerate(as_completed(futures), 1):
            row = future.result()
            rows.append(row)
            tag = row.get("error") or row.get("skip") or ""
            extra = ""
            if row["kind"] == "hazard" and "obs" in row:
                o, nl = row["obs"], row.get("null", {})
                extra = (f"per_spike {row['per_spike']:.0f} (nominal {row['nominal']:.0f}) "
                         f"n={row['n_spikes']:,}  CV {o['cv']:.3f} z{nl.get('cv',{}).get('z',float('nan')):+.1f}  "
                         f"KS {o['ks']:.4f} z{nl.get('ks',{}).get('z',float('nan')):+.1f}  "
                         f"Fano {o['fano']:.3f} z{nl.get('fano',{}).get('z',float('nan')):+.1f}  "
                         f"hz {o['hz_ratio']:.2f} z{nl.get('hz_ratio',{}).get('z',float('nan')):+.1f}  "
                         f"slope {o['hz_slope']:+.3f} z{nl.get('hz_slope',{}).get('z',float('nan')):+.1f}  "
                         f"min {o['min_gap']:.0f}")
            elif row["kind"] == "step" and "p_up" in row:
                extra = (f"p_up {row['p_up']:.5f}+-{row['se_p_up']:.5f}  mags {row['mags_to_99']} "
                         f"(top {row['top1_share']:.3f})  ratio {row['size_ratio']:.3f}  "
                         f"closure z{row['closure_z']:+.2f}")
            elif row["kind"] == "drift" and "vr_peak" in row:
                extra = (f"VR peak {row['vr_peak']:.3f} at k={row['vr_peak_k']} "
                         f"(shuffle {row['vr_peak_shuffle']:.3f})  "
                         f"hmm2 dwell {['%.0f'%d for d in row.get('hmm2',{}).get('dwell',[])]}")
            elif row["kind"] == "acf" and "acf1" in row:
                ar = row.get("ar1", {})
                extra = (f"{row['interval']:>3s} n={row['n']:6,} acf1 {row['acf1']:+.4f} "
                         f"t{row['t']:+6.1f} halves [{row['acf1_halves'][0]:+.4f},"
                         f"{row['acf1_halves'][1]:+.4f}] shuf {row['acf1_shuffle']:+.4f} "
                         f"| net {ar.get('net', float('nan')):+.2e} "
                         f"be/cost {ar.get('breakeven_over_cost', float('nan')):.3f}")
            elif row["kind"] == "tickacf" and "acf1_bid" in row:
                extra = (f"tick acf1 bid {row['acf1_bid']:+.5f} mid {row.get('acf1_mid', float('nan')):+.5f} "
                         f"se {row['se_bid']:.5f}  lags {[round(v,4) for v in row['acf_bid']]}")
            elif row["kind"] == "range" and "ticks_per_break" in row:
                extra = (f"{row['n_breaks_10x']} breaks, {row['minutes_per_break']:.1f} min/break")
            print(f"  {i:3d}/{len(jobs)}  {row['symbol']:26s} {extra} {tag}", flush=True)

    path = OUT / "characterise.json"
    path.write_text(json.dumps(_clean(rows), indent=1))
    print(f"\ndone in {(time.time() - began)/60:.1f}m -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
