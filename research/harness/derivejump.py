"""Boom and Crash are drift plus compound Poisson, so the P&L of a hold is a
distribution with a formula. Write it down, then check it against the ticks.

`research/generators.md` fixed every parameter of this family. The spike rate
is the published one on all six (268-974 ticks against a stated 300-1000) and
its arrival is **memoryless** (waiting-time CV 0.84-1.10). The grind is a random
step with CV 0.63-0.68 per tick. The arithmetic closes: `(1-p)*grind + p*spike`
is within 1.3 standard errors of zero on all six. And on `boom_500_index`,
**84,506 of 84,701 tick moves are down** - the price is monotone decreasing
except where it jumps.

That is a complete specification:

    dP = -g_t dt  with probability 1-p per tick,   +J_t  with probability p

with `p = 1/lambda`, `E[J] = E[g]*(1-p)/p` forced by the closure. Everything
this desk asks about Boom is then a question about a compound Poisson process,
and the answers are formulas rather than backtests.

## What is derived

For a position of one unit held `N` ticks on the grind side (short Boom):

* `P&L(N) = N*g - sum_{k=1..K} J_k` with `K ~ Binomial(N, p)`;
* `E[P&L] = 0` exactly, by the closure;
* `Var[P&L] = N*[(1-p)Var(g) + p*Var(J) + p(1-p)(E[g]+E[J])^2]`;
* `P(no spike at all) = (1-p)^N`, which is `P(the grind is kept whole)`;
* the **median** crosses zero at `N = lambda * ln 2` - hold longer than that on
  the grind side and the typical outcome is a loss, while the mean stays zero.

For a stop `D` above a short, which is the side price cannot walk to:

* the stop fires at the first spike with `J > D + g*t`;
* the fill is at `entry - g*t + J`, so the realised loss is `J - g*t`, **not** `D`;
* `E[slippage in R] = E[(J - g*t - D)/D | J > D + g*t]`, which is a number the
  jump distribution already contains and which `genstop.py` measured at
  **+13.96R, +6.81R, +2.44R and +1.02R** on `boom_500` at stops of 5, 10, 25 and
  50 spreads. Those four numbers are the prediction this page has to reproduce
  without touching them.

## What would count as failure, written before running

1. **The model is wrong** if the derived P&L distribution misses the empirical
   one - mean, median, standard deviation, `P(profit)` and the 1st/99th
   percentiles - by more than sampling error at any holding period.
2. **The slippage derivation is wrong** if the predicted multiples miss
   `genstop.py`'s four measured numbers by more than about 20%. They were
   measured independently, before this page existed, and are not refitted here.
3. **The closure is wrong**, and the whole martingale claim with it, if the
   measured `(1-p)*E[g] - p*E[J]` is more than 2 SE from zero in both halves of
   the day on more than one of the six feeds.
4. **The run is void** if the control fails: `volatility_75_index` through the
   same spike detector must produce no spikes, and its replayed stops must fill
   at their level.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3

import numpy as np

DATA = os.environ.get("DATA", os.path.expanduser("~/till_infinity/data"))
DB = os.environ.get("DB", os.path.join(DATA, "research.db"))
OUT = os.environ.get("OUT", os.path.expanduser("~/till_infinity/logs/derivejump.json"))
NSIM = int(os.environ.get("NSIM", "400000"))
SEED = int(os.environ.get("SEED", "20260911"))

FEEDS = ["boom_300_index", "boom_500_index", "boom_1000_index",
         "crash_300_index", "crash_500_index", "crash_1000_index"]
CONTROL = ["volatility_75_index", "step_index"]
SPIKE_MULT = 10.0
HOLDS = [10, 50, 100, 300, 500, 1000, 3000]
STOPS = [5.0, 10.0, 25.0, 50.0]
QUANTILES = [1, 5, 25, 50, 75, 95, 99]


def ticks(feed: str):
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = conn.execute("SELECT ts, bid, ask FROM ticks WHERE feed=? ORDER BY ts ASC",
                        (feed,)).fetchall()
    conn.close()
    mid, spr = [], []
    for _, b, a in rows:
        if b is None or a is None or b <= 0:
            continue
        mid.append((b + a) / 2.0)
        spr.append(a - b)
    return np.array(mid), float(np.median(spr)) if spr else float("nan")


def fit(mid: np.ndarray) -> dict:
    """Estimate (p, g, J) and the side the spike points. Nothing is assumed:
    the spike direction is read off the sign imbalance of the moves."""
    d = np.diff(mid)
    nz = np.abs(d[d != 0])
    if not len(nz):
        return {}
    med = float(np.median(nz))
    spike = np.abs(d) > SPIKE_MULT * med
    # the spike side is the rarer sign
    up = int((d > 0).sum())
    dn = int((d < 0).sum())
    side = +1 if up < dn else -1          # +1: spikes up (Boom), -1: spikes down
    J = np.abs(d[spike & (np.sign(d) == side)])
    g = np.abs(d[~spike])
    if len(J) < 20 or len(g) < 1000:
        return {"n_spikes": int(len(J))}
    n = len(d)
    p = len(J) / n
    closure = (1.0 - p) * float(g.mean()) - p * float(J.mean())
    se = float(d.std(ddof=1) / math.sqrt(n))
    h = n // 2
    d1, d2 = d[:h], d[h:]
    return {"n_ticks": n, "side": side, "p": p, "lam": 1.0 / p,
            "n_spikes": int(len(J)),
            "g_mean": float(g.mean()), "g_sd": float(g.std(ddof=1)),
            "g_cv": float(g.std(ddof=1) / g.mean()),
            "J_mean": float(J.mean()), "J_sd": float(J.std(ddof=1)),
            "J_med": float(np.median(J)),
            "J_q": {str(q): float(np.percentile(J, q)) for q in QUANTILES},
            "spike_over_grind": float(np.median(J) / g.mean()),
            "closure": closure, "closure_se": se, "closure_z": closure / se,
            "drift_z_h1": float(d1.mean() / (d1.std(ddof=1) / math.sqrt(len(d1)))),
            "drift_z_h2": float(d2.mean() / (d2.std(ddof=1) / math.sqrt(len(d2)))),
            "_g": g, "_J": J}


def derived_hold_fast(f: dict, N: int, rng, nsim: int) -> dict:
    """Monte Carlo of the *derived* law: K ~ Binomial(N,p), K jumps, N-K grinds.

    Nothing here walks the real path. The grind and jump marginals come from the
    fit, but the dependence structure - Bernoulli thinning, independent draws -
    is the model, and that is exactly what the comparison tests. The grind sum
    is drawn as a normal, which is exact to well inside the sampling error at
    every N tested here because the smallest is forty independent draws.
    """
    g, J, p = f["_g"], f["_J"], f["p"]
    K = rng.binomial(N, p, size=nsim)
    gm, gv = float(g.mean()), float(g.var(ddof=1))
    m = N - K
    gsum = rng.normal(m * gm, np.sqrt(np.maximum(m, 0) * gv))
    kmax = int(K.max())
    jsum = np.zeros(nsim)
    if kmax:
        draws = rng.choice(J, size=(nsim, kmax))
        mask = np.arange(kmax)[None, :] < K[:, None]
        jsum = (draws * mask).sum(axis=1)
    tot = gsum - jsum
    return {"mean": float(tot.mean()), "median": float(np.median(tot)),
            "sd": float(tot.std(ddof=1)),
            "var_closed": float(N * ((1 - p) * gv + p * float(J.var(ddof=1))
                                     + p * (1 - p) * (gm + float(J.mean())) ** 2)),
            "p_profit": float((tot > 0).mean()),
            "p_nospike": float((1.0 - p) ** N),
            "q": {str(q): float(np.percentile(tot, q)) for q in QUANTILES}}


def empirical_hold(mid: np.ndarray, N: int, side: int) -> dict:
    """The grind side of an N-tick hold, measured on the real path."""
    if len(mid) <= N + 10:
        return {}
    r = (mid[:-N] - mid[N:]) if side > 0 else (mid[N:] - mid[:-N])
    nb = r[::N]                       # non-overlapping, for the standard error
    return {"mean": float(r.mean()), "median": float(np.median(r)),
            "sd": float(r.std(ddof=1)), "p_profit": float((r > 0).mean()),
            "n_nonoverlap": int(len(nb)),
            "se_mean": float(nb.std(ddof=1) / math.sqrt(len(nb))) if len(nb) > 2 else float("nan"),
            "q": {str(q): float(np.percentile(r, q)) for q in QUANTILES}}


def derived_slippage(f: dict, D: float, T: float, rng, nsim: int) -> dict:
    """A short on the spike side: derive where the stop actually fills.

    Price grinds away from the stop at `g` per tick, so the barrier the spike
    must clear grows with time held. Fires at the first `J_t > D + sum(g)`.
    """
    g, J, p = f["_g"], f["_J"], f["p"]
    gm = float(g.mean())
    maxt = int(T / gm * 3 + 50)
    stopped = np.zeros(nsim, dtype=bool)
    loss = np.zeros(nsim)
    won = np.zeros(nsim, dtype=bool)
    travel = np.zeros(nsim)
    alive = np.ones(nsim, dtype=bool)
    for t in range(maxt):
        idx = np.flatnonzero(alive)
        if not idx.size:
            break
        isjump = rng.random(idx.size) < p
        jj = idx[isjump]
        gg = idx[~isjump]
        travel[gg] += rng.choice(g, size=gg.size)
        if jj.size:
            amp = rng.choice(J, size=jj.size)
            newpos = -travel[jj] + amp       # signed distance from entry, + is against
            hit = newpos > D
            h = jj[hit]
            loss[h] = newpos[hit]
            stopped[h] = True
            alive[h] = False
            travel[jj[~hit]] -= amp[~hit]    # the spike pushes price back up
        tgt = idx[travel[idx] >= T]
        if tgt.size:
            won[tgt] = True
            alive[tgt] = False
    done = stopped | won
    slip = (loss[stopped] - D) / D
    return {"n": int(done.sum()), "p_stop": float(stopped.sum() / max(done.sum(), 1)),
            "mean_slip_R": float(slip.mean()) if slip.size else float("nan"),
            "p90_slip_R": float(np.percentile(slip, 90)) if slip.size else float("nan"),
            "max_slip_R": float(slip.max()) if slip.size else float("nan"),
            "frac_over_half_R": float((slip > 0.5).mean()) if slip.size else float("nan"),
            "mean_loss_R": float(-(loss[stopped] / D).mean()) if slip.size else float("nan"),
            "expectancy_R": float((won.sum() * (T / D) - loss[stopped].sum() / D)
                                  / max(done.sum(), 1))}


def measured_slippage(mid: np.ndarray, spread: float, D: float, T: float, side: int) -> dict:
    """`genstop.py`'s replay, reproduced here so the derivation has something on
    the same sample to be checked against."""
    n = len(mid)
    i = 0
    slips, losses = [], []
    stops = wins = tot = 0
    while i < n - 2:
        e = mid[i]
        stop = e - side * D
        tgt = e + side * T
        out = None
        for j in range(i + 1, min(i + 1 + 7200, n)):
            p = mid[j]
            if side * (p - stop) <= 0:
                out = ("stop", p, j - i)
                break
            if side * (p - tgt) >= 0:
                out = ("target", p, j - i)
                break
        if out is None:
            i += 7200
            continue
        why, xp, held = out
        gross = side * (xp - e)
        tot += 1
        if why == "stop":
            stops += 1
            slips.append(-(gross + D) / D)
            losses.append(gross / D)
        else:
            wins += 1
        i += max(held, 1)
    if tot < 20 or not slips:
        return {}
    s = np.array(slips)
    return {"n": tot, "p_stop": stops / tot, "mean_slip_R": float(s.mean()),
            "p90_slip_R": float(np.percentile(s, 90)), "max_slip_R": float(s.max()),
            "frac_over_half_R": float((s > 0.5).mean()),
            "mean_loss_R": float(np.mean(losses))}


def main() -> None:
    rng = np.random.default_rng(SEED)
    out = {}
    print("=" * 118)
    print("BOOM AND CRASH AS COMPOUND POISSON - the P&L of a hold, derived")
    print("=" * 118)

    fits = {}
    print("\n[1] THE FITTED GENERATOR - every parameter, from 24h of ticks")
    print(f"{'feed':22s} {'spikes':>7s} {'lambda':>8s} {'E[g]':>10s} {'CV[g]':>6s} {'E[J]':>10s}"
          f" {'med J':>9s} {'J/g':>7s} {'closure':>11s} {'z':>6s} {'z h1':>6s} {'z h2':>6s} {'spread':>9s}")
    for feed in FEEDS:
        mid, spread = ticks(feed)
        f = fit(mid)
        if not f.get("n_ticks"):
            print(f"{feed:22s}  no fit")
            continue
        f["spread"] = spread
        f["_mid"] = mid
        fits[feed] = f
        print(f"{feed:22s} {f['n_spikes']:7d} {f['lam']:8.1f} {f['g_mean']:10.5f} {f['g_cv']:6.3f}"
              f" {f['J_mean']:10.4f} {f['J_med']:9.4f} {f['spike_over_grind']:7.0f}"
              f" {f['closure']:11.3e} {f['closure_z']:6.2f} {f['drift_z_h1']:6.2f}"
              f" {f['drift_z_h2']:6.2f} {spread:9.4f}")
    print("\n    control: the same detector on feeds with no spike mechanism")
    for feed in CONTROL:
        mid, spread = ticks(feed)
        f = fit(mid)
        print(f"    {feed:24s} spikes found: {f.get('n_spikes', 0)}   (must be 0)")

    print("\n[2] DERIVED - the cost of the crossing, exactly")
    print(f"{'feed':22s} {'spread':>9s} {'E[g]/tick':>11s} {'ticks to pay':>13s} {'seconds':>9s}"
          f" {'ticks/spike':>12s}")
    for feed, f in fits.items():
        nt = f["spread"] / f["g_mean"]
        print(f"{feed:22s} {f['spread']:9.4f} {f['g_mean']:11.5f} {nt:13.2f} {nt:9.2f}"
              f" {f['lam']:12.1f}")
        f["ticks_to_pay"] = nt

    print("\n[3] DERIVED vs MEASURED - the P&L distribution of an N-tick hold on the grind side")
    for feed, f in fits.items():
        print(f"\n  {feed}  (lambda={f['lam']:.0f}, ln2*lambda={f['lam']*math.log(2):.0f})")
        print(f"{'N':>6s} {'':>4s} {'mean':>11s} {'median':>11s} {'sd':>11s} {'P(profit)':>10s}"
              f" {'P(no spike)':>12s} {'q01':>11s} {'q50':>11s} {'q99':>11s}")
        for N in HOLDS:
            d = derived_hold_fast(f, N, rng, NSIM)
            e = empirical_hold(f["_mid"], N, f["side"])
            if not e:
                continue
            print(f"{N:6d} {'der':>4s} {d['mean']:11.4f} {d['median']:11.4f} {d['sd']:11.4f}"
                  f" {d['p_profit']:10.4f} {d['p_nospike']:12.4f} {d['q']['1']:11.4f}"
                  f" {d['q']['50']:11.4f} {d['q']['99']:11.4f}")
            print(f"{'':6s} {'obs':>4s} {e['mean']:11.4f} {e['median']:11.4f} {e['sd']:11.4f}"
                  f" {e['p_profit']:10.4f} {'':>12s} {e['q']['1']:11.4f}"
                  f" {e['q']['50']:11.4f} {e['q']['99']:11.4f}")
            out.setdefault("holds", {}).setdefault(feed, {})[str(N)] = {"derived": d, "measured": e}
        # The closure forces E[J] = lambda * E[g] exactly, so one spike costs
        # exactly lambda ticks of grind and the hold is profitable **iff fewer
        # than N/lambda spikes arrive** - iff a Poisson variable lands below its
        # own mean. That is above 1/2 at every N and tends to 1/2 from above,
        # which is why the grind side wins more often than it loses at every
        # horizon while its mean stays at zero.
        from scipy.stats import poisson
        print(f"       derived: E[J]/E[g] = {f['J_mean']/f['g_mean']:.1f} against "
              f"lambda = {f['lam']:.1f} - one spike costs "
              f"{f['J_mean']/f['g_mean']/f['lam']:.3f} lambdas of grind")
        print(f"{'':7s}{'N':>8s} {'P(K < N/lam)':>13s} {'P(profit) der':>14s} {'P(profit) obs':>14s}")
        prow = []
        for N in HOLDS:
            mu = N / f["lam"]
            pk = float(poisson.cdf(math.ceil(mu) - 1, mu))
            d = derived_hold_fast(f, N, rng, min(NSIM, 120000))
            e = empirical_hold(f["_mid"], N, f["side"])
            if not e:
                continue
            print(f"{'':7s}{N:8d} {pk:13.4f} {d['p_profit']:14.4f} {e['p_profit']:14.4f}")
            prow.append({"N": N, "poisson": pk, "derived": d["p_profit"], "measured": e["p_profit"]})
        out.setdefault("p_profit", {})[feed] = prow

    print("\n[4] DERIVED vs MEASURED - the stop on the spike side, and what it fills at")
    print("    the four boom_500 numbers below were measured by genstop.py before this")
    print("    page existed and are not refitted here.")
    print(f"{'feed':22s} {'stop':>5s} {'':>4s} {'p(stop)':>8s} {'mean slip R':>12s} {'p90':>8s}"
          f" {'max':>9s} {'>0.5R':>7s} {'mean loss R':>12s} {'n':>7s}")
    for feed, f in fits.items():
        for sd in STOPS:
            D = sd * f["spread"]
            der = derived_slippage(f, D, D, rng, min(NSIM, 60000))
            mea = measured_slippage(f["_mid"], f["spread"], D, D, -f["side"])
            print(f"{feed:22s} {sd:5.0f} {'der':>4s} {der['p_stop']:8.4f} {der['mean_slip_R']:12.3f}"
                  f" {der['p90_slip_R']:8.2f} {der['max_slip_R']:9.2f} {der['frac_over_half_R']:7.3f}"
                  f" {der['mean_loss_R']:12.3f} {der['n']:7d}")
            if mea:
                print(f"{'':22s} {'':5s} {'obs':>4s} {mea['p_stop']:8.4f} {mea['mean_slip_R']:12.3f}"
                      f" {mea['p90_slip_R']:8.2f} {mea['max_slip_R']:9.2f} {mea['frac_over_half_R']:7.3f}"
                      f" {mea['mean_loss_R']:12.3f} {mea['n']:7d}")
            out.setdefault("slippage", {}).setdefault(feed, {})[str(sd)] = {"derived": der, "measured": mea}

    print("\n[5] DERIVED - the stop does not bound the risk until it clears the jump")
    print("    P(J > D) at each stop width: the fraction of stop-outs that gap through.")
    print(f"{'feed':22s} " + " ".join(f"{int(s):>9d}" for s in STOPS) + f" {'D at J q95':>11s} {'in spreads':>11s}")
    for feed, f in fits.items():
        J = f["_J"]
        row = [float((J > s * f["spread"]).mean()) for s in STOPS]
        q95 = float(np.percentile(J, 95))
        print(f"{feed:22s} " + " ".join(f"{v:9.4f}" for v in row)
              + f" {q95:11.3f} {q95/f['spread']:11.0f}")
        out.setdefault("gapthrough", {})[feed] = {"p": row, "q95": q95,
                                                  "q95_spreads": q95 / f["spread"]}

    print("\n[6] DERIVED - the size that survives, given the jump distribution")
    print("    max units per unit of account so that one stop-out costs at most eps.")
    print(f"{'feed':22s} {'J q50':>9s} {'J q95':>9s} {'J q99':>9s} {'J max':>9s}"
          f" {'units @1%':>10s} {'units @2% of q99':>17s}")
    for feed, f in fits.items():
        J = f["_J"]
        q = {k: float(np.percentile(J, int(k))) for k in ("50", "95", "99")}
        mx = float(J.max())
        print(f"{feed:22s} {q['50']:9.3f} {q['95']:9.3f} {q['99']:9.3f} {mx:9.3f}"
              f" {0.01/mx:10.6f} {0.02/q['99']:17.6f}")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    clean = json.loads(json.dumps(out, default=float))
    with open(OUT, "w") as fh:
        json.dump(clean, fh, indent=1)
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
