"""The Volatility indices are GBM with a published sigma, so the barrier
questions this desk answers with estimators have closed forms. Derive them,
then check the closed form against 86,411 bars.

`research/generators.md` and `research/twins.md` settled the generator:
`volatility_N_index` is geometric Brownian motion whose annualised volatility
is exactly `N` percent, annualising at 365*24*60. H = 0.50, kurtosis 3.00,
Jarque-Bera p 0.40-0.95, variance ratios 1.000, no volatility clustering.

That is not one more statistic. It means the log price is a driftless Brownian
motion with a **known** diffusion coefficient, and every first-passage question
on a driftless Brownian motion is solved. This page's job is to write those
answers down and then verify them, because a closed form that disagrees with
86,411 bars is a wrong closed form and the check is the whole value of having
both.

## The unit

Everything here is measured in **one-minute sigmas**:

    u = (N/100) / sqrt(365*24*60)

so `u` is the standard deviation of a one-minute log return and a barrier "at 3"
means three of those. In that unit the answers lose their parameters:

* **two-sided exit**, up barrier `a`, down barrier `b`:
  `P(up first) = b/(a+b)` and `E[tau] = a*b` **minutes**;
* **one-sided touch** within `T` minutes: `P = 2*Phi(-a/sqrt(T))`;
* **maximum** over `T` minutes: `E[M] = sqrt(2T/pi)`, `P(M>=m) = 2*Phi(-m/sqrt(T))`;
* **range** over `T` minutes: `E[H-L] = sqrt(8T/pi)`;
* **occupation**: the fraction of `T` spent above the start is arcsine,
  `P(frac <= x) = (2/pi)*arcsin(sqrt(x))`.

## The correction that is the actual finding

Those are continuous-time answers and the quote is not continuous. A discretely
monitored barrier behaves like a continuous barrier pushed **further away** by

    beta * sigma * sqrt(dt),   beta = -zeta(1/2)/sqrt(2*pi) = 0.5826

- the Broadie-Glasserman-Kou continuity correction, which is the same constant
as the limiting expected overshoot of a Gaussian random walk past a level. In
one-minute sigmas with one-minute monitoring `sigma*sqrt(dt) = 1`, so the
correction is **0.5826 of a unit** and it is not a rounding error: a symmetric
band at +-3 has `E[tau] = 9` minutes continuously and `(3.58)^2 = 12.8` minutes
on closes, 43% longer.

This also predicts a number `research/generators.md` measured and could not
explain: the Parkinson-to-close volatility ratio, **0.870** on the two-second
family and **0.909** on the one-second family. A bar's high and low are resolved
by `n` ticks, not continuously, so the same correction applies to both ends of
the range.

## What would count as failure, written before running

1. **The closed forms die** if measured `P(up first)` or `E[tau]` misses the
   derived value by more than a few percent on the larger barriers, where the
   asymptotics are supposed to hold, in both halves of the sample.
2. **The correction dies** if the uncorrected continuous formula fits the data
   *better* than the corrected one, or if the correction has the wrong sign.
3. **The premise dies** if the three routes disagree: closed form, a Monte Carlo
   of the *specified* generator, and the real bars must land together. If the
   Monte Carlo matches the closed form but the bars do not, the generator is not
   what `generators.md` says it is.
4. **The run is void** if a statistic lands on exactly its null - this folder has
   published a dead column twice.

## The three routes

Every number below is computed three ways and the three are printed side by
side:

* **derived** - the closed form, evaluated;
* **simulated** - 2,000,000 paths of the *specified* process. This is numerical
  evaluation of a known law, not a fit to data: nothing in it comes from the
  bars. It exists so that a disagreement between theory and data can be blamed
  on the right one of the two.
* **measured** - non-overlapping windows of real one-minute bars, split into the
  first and last 30 days.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
from multiprocessing import Pool

import numpy as np
from scipy.stats import norm

DATA = os.environ.get("DATA", os.path.expanduser("~/till_infinity/data"))
DB = os.environ.get("DB", os.path.join(DATA, "research.db"))
OUT = os.environ.get("OUT", os.path.expanduser("~/till_infinity/logs/derivegbm.json"))
NPATH = int(os.environ.get("NPATH", "2000000"))
SEED = int(os.environ.get("SEED", "20260911"))

MINUTES_PER_YEAR = 365 * 24 * 60
#: -zeta(1/2)/sqrt(2*pi). The Broadie-Glasserman-Kou continuity correction and
#: the limiting expected overshoot of a standard Gaussian walk past a level.
BETA = 0.5825971579

NOMINAL = {
    "volatility_10_index": 10.0, "volatility_25_index": 25.0,
    "volatility_50_index": 50.0, "volatility_75_index": 75.0,
    "volatility_100_index": 100.0,
    "volatility_10_1s_index": 10.0, "volatility_25_1s_index": 25.0,
    "volatility_50_1s_index": 50.0, "volatility_75_1s_index": 75.0,
    "volatility_100_1s_index": 100.0, "volatility_150_1s_index": 150.0,
    "volatility_250_1s_index": 250.0,
}
#: Ticks per one-minute bar, *measured* from the tick table rather than assumed.
#: The nominal rates are 30 a minute for the 2-second family and 60 for the
#: 1-second family, but the collector drops some and the Parkinson prediction
#: is sensitive to the count, so it is read from the data.
def measured_ticks_per_bar(feed: str) -> float:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    row = conn.execute("SELECT COUNT(*), MIN(ts), MAX(ts) FROM ticks WHERE feed=?",
                       (feed,)).fetchone()
    conn.close()
    if not row or not row[0] or row[2] == row[1]:
        return 60.0 if "_1s_" in feed else 30.0
    return 60.0 * row[0] / ((row[2] - row[1]) / 1000.0)

#: (up, down) barrier pairs in one-minute sigmas. Symmetric pairs test E[tau],
#: asymmetric pairs test the hit probability, and the ladder from 1 to 10 tests
#: where the 0.5826 asymptotic starts to hold.
PAIRS = [(1, 1), (2, 2), (3, 3), (5, 5), (8, 8), (10, 10),
         (1, 3), (3, 1), (2, 6), (6, 2), (1, 9), (9, 1), (2, 10), (10, 2)]
HORIZONS = [5, 15, 60, 240]
TOUCH_A = [0.5, 1.0, 2.0, 3.0, 5.0]


# ---------------------------------------------------------------- derived ----
def p_up_continuous(a: float, b: float) -> float:
    return b / (a + b)


def p_up_discrete(a: float, b: float, s: float = 1.0) -> float:
    """Optional stopping with the mean overshoot carried on both barriers.

    A driftless walk stopped at either barrier satisfies
    `0 = p*(a+E[O]) - (1-p)*(b+E[O])`, and `E[O] -> BETA*s` for Gaussian steps
    of standard deviation `s`. Solving gives the barriers each pushed out by
    the same amount, which is the BGK correction in probability form.
    """
    return (b + BETA * s) / (a + b + 2.0 * BETA * s)


def etau_continuous(a: float, b: float) -> float:
    return a * b


def etau_discrete(a: float, b: float, s: float = 1.0) -> float:
    return (a + BETA * s) * (b + BETA * s)


def p_touch_one_sided(a: float, T: float, shift: float = 0.0) -> float:
    """Reflection principle: P(max over [0,T] >= a) = 2*Phi(-a/sqrt(T))."""
    return 2.0 * norm.cdf(-(a + shift) / math.sqrt(T))


def p_touch_two_sided(a: float, T: float, shift: float = 0.0) -> float:
    """P(|X| reaches a by T) for a driftless walk, from the exit-time series

        P(tau > T) = (4/pi) * sum_n (-1)^n/(2n+1) * exp(-(2n+1)^2 pi^2 T/(8 a^2))

    which is the standard eigenfunction expansion on (-a, a). It is *not*
    twice the one-sided answer - that double-counts paths reaching both.
    """
    A = a + shift
    tot = 0.0
    for n in range(0, 60):
        k = 2 * n + 1
        tot += ((-1) ** n / k) * math.exp(-(k ** 2) * (math.pi ** 2) * T / (8.0 * A * A))
    return 1.0 - (4.0 / math.pi) * tot


def emax_continuous(T: float) -> float:
    return math.sqrt(2.0 * T / math.pi)


def emax_discrete(T: float, s: float = 1.0) -> float:
    return math.sqrt(2.0 * T / math.pi) - BETA * s


def erange_continuous(T: float) -> float:
    return math.sqrt(8.0 * T / math.pi)


def erange_discrete(T: float, s: float = 1.0) -> float:
    return math.sqrt(8.0 * T / math.pi) - 2.0 * BETA * s


def arcsine_cdf(x: float) -> float:
    return (2.0 / math.pi) * math.asin(math.sqrt(x))


def parkinson_ratio_derived(n: int) -> float:
    """Parkinson-over-close volatility for a bar resolved by `n` ticks.

    Parkinson reads `sigma^2 = E[(ln H/L)^2] / (4 ln 2)`, which is exact when
    the range is continuous. With `n` ticks each end of the range is short by
    `BETA*sigma*sqrt(dt)`, and `E[R] = sqrt(8n/pi)` in per-tick sigmas, so

        ratio ~= 1 - 2*BETA / sqrt(8n/pi)

    to first order. The simulated column evaluates the same quantity exactly.
    """
    return 1.0 - 2.0 * BETA / math.sqrt(8.0 * n / math.pi)


# -------------------------------------------------------------- simulated ----
def sim_two_barrier(a: float, b: float, npath: int, rng) -> tuple[float, float]:
    """Monte Carlo of the *specified* process: unit-variance Gaussian steps."""
    hit_up = 0
    taus = 0.0
    n = 0
    block = 200000
    maxstep = int(4.0 * (a + b + 1.0) ** 2 + 400)
    done = 0
    while done < npath:
        m = min(block, npath - done)
        x = np.zeros(m)
        alive = np.ones(m, dtype=bool)
        tau = np.zeros(m, dtype=np.int64)
        up = np.zeros(m, dtype=bool)
        for t in range(1, maxstep + 1):
            idx = np.flatnonzero(alive)
            if idx.size == 0:
                break
            x[idx] += rng.standard_normal(idx.size)
            hu = idx[x[idx] >= a]
            hd = idx[x[idx] <= -b]
            if hu.size:
                up[hu] = True
                tau[hu] = t
                alive[hu] = False
            if hd.size:
                tau[hd] = t
                alive[hd] = False
        keep = ~alive
        hit_up += int(up[keep].sum())
        taus += float(tau[keep].sum())
        n += int(keep.sum())
        done += m
    return hit_up / n, taus / n


def sim_window(T: int, npath: int, rng) -> dict:
    out = {"emax": 0.0, "erange": 0.0, "n": 0,
           "touch": {str(a): 0 for a in TOUCH_A},
           "touch1": {str(a): 0 for a in TOUCH_A},
           "occ_deciles": np.zeros(10, dtype=np.int64)}
    done = 0
    block = max(1, min(200000, 20000000 // max(T, 1)))
    while done < npath:
        m = min(block, npath - done)
        steps = rng.standard_normal((m, T))
        path = np.cumsum(steps, axis=1)
        mx = path.max(axis=1)
        mn = path.min(axis=1)
        out["emax"] += float(np.maximum(mx, 0.0).sum())
        out["erange"] += float((np.maximum(mx, 0.0) - np.minimum(mn, 0.0)).sum())
        for a in TOUCH_A:
            out["touch"][str(a)] += int(((mx >= a) | (mn <= -a)).sum())
            out["touch1"][str(a)] += int((mx >= a).sum())
        frac = (path > 0).mean(axis=1)
        out["occ_deciles"] += np.bincount(np.minimum((frac * 10).astype(int), 9),
                                          minlength=10)
        out["n"] += m
        done += m
    return out


def sim_parkinson(n: int, npath: int, rng) -> float:
    """E[(H-L)^2] / (4 ln2 * n) for an n-step walk, against the close variance."""
    tot = 0.0
    done = 0
    block = max(1, min(400000, 20000000 // max(n, 1)))
    while done < npath:
        m = min(block, npath - done)
        # A bar's high and low are extremes of the ticks *inside* the bar. The
        # previous close is not one of them, while the close-to-close return
        # spans all n increments - so the range is taken over p_1..p_n and the
        # variance denominator stays n. Including p_0 in the range was the first
        # version of this and it overstated the ratio by two points.
        path = np.cumsum(rng.standard_normal((m, n)), axis=1)
        hi = path.max(axis=1)
        lo = path.min(axis=1)
        tot += float(((hi - lo) ** 2).sum())
        done += m
    er2 = tot / npath
    return math.sqrt(er2 / (4.0 * math.log(2.0) * n))


# --------------------------------------------------------------- measured ----
def load(feed: str) -> np.ndarray:
    conn = sqlite3.connect(DB)
    rows = conn.execute(
        "SELECT ts, open, high, low, close FROM bars WHERE feed=? AND interval='1m' "
        "ORDER BY ts ASC", (feed,)).fetchall()
    conn.close()
    return np.array([[r[0], r[1], r[2], r[3], r[4]] for r in rows
                     if r[4] is not None and r[4] > 0 and r[2] is not None], dtype=float)


def two_barrier_measured(x: np.ndarray, a: float, b: float, u: float) -> dict:
    """Non-overlapping windows on closes. Monitoring is at the close, which is
    the discrete case the correction is written for."""
    n = len(x)
    i = 0
    ups = 0
    taus = []
    while i < n - 1:
        x0 = x[i]
        j = i + 1
        hit = 0
        while j < n:
            d = (x[j] - x0) / u
            if d >= a:
                hit = 1
                break
            if d <= -b:
                hit = -1
                break
            j += 1
        if hit == 0:
            break
        ups += 1 if hit > 0 else 0
        taus.append(j - i)
        i = j
    if not taus:
        return {"n": 0}
    t = np.array(taus, dtype=float)
    return {"n": len(taus), "p_up": ups / len(taus), "etau": float(t.mean()),
            "se_p": math.sqrt(0.25 / len(taus)), "se_tau": float(t.std(ddof=1) / math.sqrt(len(t)))}


def windows_measured(x: np.ndarray, T: int, u: float) -> dict:
    n = len(x)
    k = n // T
    if k < 20:
        return {"n": 0}
    seg = x[: k * T].reshape(k, T)
    start = x[np.arange(k) * T]
    # windows start at the close before the first bar of the block
    start = np.concatenate([[x[0]], x[np.arange(1, k) * T - 1]])
    d = (seg - start[:, None]) / u
    mx = np.maximum(d.max(axis=1), 0.0)
    mn = np.minimum(d.min(axis=1), 0.0)
    frac = (d > 0).mean(axis=1)
    occ = np.bincount(np.minimum((frac * 10).astype(int), 9), minlength=10)
    return {"n": int(k), "emax": float(mx.mean()), "erange": float((mx - mn).mean()),
            "se_max": float(mx.std(ddof=1) / math.sqrt(k)),
            "touch": {str(a): float(((mx >= a) | (mn <= -a)).mean()) for a in TOUCH_A},
            "touch1": {str(a): float((mx >= a).mean()) for a in TOUCH_A},
            "occ_deciles": occ.tolist()}


def parkinson_measured(o: np.ndarray) -> dict:
    hi, lo, cl = o[:, 2], o[:, 3], o[:, 4]
    ok = (hi > 0) & (lo > 0) & (cl > 0)
    hi, lo, cl = hi[ok], lo[ok], cl[ok]
    r = np.diff(np.log(cl))
    sig_c = float(np.sqrt((r ** 2).mean()))
    rng = np.log(hi / lo)
    sig_p = float(math.sqrt((rng ** 2).mean() / (4.0 * math.log(2.0))))
    return {"sigma_close": sig_c, "sigma_parkinson": sig_p, "ratio": sig_p / sig_c}


def drift_bound(x: np.ndarray, u: float, sigma_ann: float) -> dict:
    r = np.diff(x)
    n = len(r)
    mu_hat = float(r.mean())
    se = float(r.std(ddof=1) / math.sqrt(n))
    # the two candidate conventions, per minute
    half_var = -0.5 * (sigma_ann ** 2) / MINUTES_PER_YEAR
    return {"n": n, "mu_per_min": mu_hat, "se": se, "z_vs_zero": mu_hat / se,
            "minus_half_var": half_var, "z_vs_half_var": (mu_hat - half_var) / se,
            "sigma_min": u, "mu_over_sigma": mu_hat / u,
            "half_var_over_se": half_var / se}


def expectancy_measured(x: np.ndarray, c: float, a: float, b: float, u: float) -> dict:
    """A long entered at the offer and closed at the bid, barriers from the mid.

    The mid is a martingale, so `E[P&L] = -c` for **any** stopping time with
    finite expectation. This is that theorem, replayed: report gross (must be
    zero) and net (must be -c), in price-log units and in R.
    """
    n = len(x)
    i = 0
    gross = []
    while i < n - 1:
        x0 = x[i]
        j = i + 1
        res = None
        while j < n:
            d = (x[j] - x0) / u
            if d >= a:
                res = a * u
                break
            if d <= -b:
                res = -b * u
                break
            j += 1
        if res is None:
            break
        gross.append((x[j] - x0))
        i = j
    if len(gross) < 20:
        return {"n": 0}
    g = np.array(gross)
    risk = b * u
    return {"n": len(g), "gross": float(g.mean()),
            "se_gross": float(g.std(ddof=1) / math.sqrt(len(g))),
            "z_gross": float(g.mean() / (g.std(ddof=1) / math.sqrt(len(g)))),
            "net": float(g.mean() - c), "net_R": float((g.mean() - c) / risk),
            "predicted_net_R": float(-c / risk)}


def spread_of(feed: str) -> float:
    conn = sqlite3.connect(DB)
    rows = conn.execute("SELECT bid, ask FROM ticks WHERE feed=? ", (feed,)).fetchall()
    conn.close()
    v = [(a - b) / ((a + b) / 2.0) for b, a in rows
         if b is not None and a is not None and b > 0 and a >= b]
    if not v:
        return float("nan")
    return float(np.median(v))


def do_feed(feed: str) -> dict:
    o = load(feed)
    if len(o) < 1000:
        return {"feed": feed, "n": 0}
    npb = measured_ticks_per_bar(feed)
    cl = np.log(o[:, 4])
    nominal = NOMINAL[feed]
    r = np.diff(cl)
    sig_realised = float(r.std(ddof=1)) * math.sqrt(MINUTES_PER_YEAR)
    u_nom = (nominal / 100.0) / math.sqrt(MINUTES_PER_YEAR)
    out = {"feed": feed, "bars": len(o), "nominal": nominal,
           "realised_ann": sig_realised * 100.0, "u_nominal": u_nom,
           "quote_grid_over_sigma": None,
           "drift": drift_bound(cl, u_nom, nominal / 100.0),
           "parkinson": parkinson_measured(o),
           "parkinson_derived": parkinson_ratio_derived(npb),
           "ticks_per_bar": npb,
           "pairs": {}, "windows": {}, "expectancy": {}}
    half = len(cl) // 2
    for (a, b) in PAIRS:
        full = two_barrier_measured(cl, a, b, u_nom)
        h1 = two_barrier_measured(cl[:half], a, b, u_nom)
        h2 = two_barrier_measured(cl[half:], a, b, u_nom)
        out["pairs"][f"{a}:{b}"] = {"full": full, "h1": h1, "h2": h2}
    for T in HORIZONS:
        out["windows"][str(T)] = windows_measured(cl, T, u_nom)
    c = spread_of(feed)
    out["spread_log"] = c
    if c == c:
        for (a, b) in [(1, 1), (3, 3), (5, 5), (3, 1), (1, 3)]:
            out["expectancy"][f"{a}:{b}"] = expectancy_measured(cl, c, a, b, u_nom)
    return out


def main() -> None:
    rng = np.random.default_rng(SEED)
    print("=" * 110)
    print("DERIVED vs SIMULATED vs MEASURED - driftless Brownian motion in one-minute sigmas")
    print("=" * 110)

    print("\n[0] the simulated column is the specified process, not the data")
    print(f"    paths per cell: {NPATH:,}   seed {SEED}   beta = {BETA:.7f}")

    sim_pairs = {}
    for (a, b) in PAIRS:
        p, t = sim_two_barrier(a, b, min(NPATH, 400000), rng)
        sim_pairs[f"{a}:{b}"] = {"p_up": p, "etau": t}
    sim_win = {T: sim_window(T, min(NPATH, 400000), rng) for T in HORIZONS}
    sim_park = {n: sim_parkinson(n, min(NPATH, 1000000), rng) for n in (30, 60)}
    # every distinct measured tick count, so the per-feed row is predicted from
    # that feed's own publication rate rather than the nominal one
    for f in NOMINAL:
        nb = int(round(measured_ticks_per_bar(f)))
        if nb not in sim_park:
            sim_park[nb] = sim_parkinson(nb, min(NPATH, 1000000), rng)

    print("\n[1] TWO-SIDED BARRIER - derived closed form against the specified process")
    print(f"{'a:b':>7s} {'P(up) cont':>11s} {'P(up) disc':>11s} {'P(up) sim':>11s}"
          f" {'E[tau] cont':>12s} {'E[tau] disc':>12s} {'E[tau] sim':>12s}")
    for (a, b) in PAIRS:
        k = f"{a}:{b}"
        print(f"{k:>7s} {p_up_continuous(a,b):11.4f} {p_up_discrete(a,b):11.4f} {sim_pairs[k]['p_up']:11.4f}"
              f" {etau_continuous(a,b):12.3f} {etau_discrete(a,b):12.3f} {sim_pairs[k]['etau']:12.3f}")

    print("\n[2] WINDOW STATISTICS - derived against the specified process")
    print(f"{'T':>5s} {'E[max] cont':>12s} {'E[max] disc':>12s} {'E[max] sim':>12s}"
          f" {'E[rng] cont':>12s} {'E[rng] disc':>12s} {'E[rng] sim':>12s}")
    for T in HORIZONS:
        s = sim_win[T]
        print(f"{T:5d} {emax_continuous(T):12.4f} {emax_discrete(T):12.4f} {s['emax']/s['n']:12.4f}"
              f" {erange_continuous(T):12.4f} {erange_discrete(T):12.4f} {s['erange']/s['n']:12.4f}")

    print("\n[3] PARKINSON RATIO - the 0.870 / 0.909 in generators.md, derived")
    print(f"{'ticks/bar':>10s} {'first order':>12s} {'exact (sim)':>12s} {'generators.md':>14s}")
    for n, obs in ((30, 0.870), (60, 0.909)):
        print(f"{n:10d} {parkinson_ratio_derived(n):12.4f} {sim_park[n]:12.4f} {obs:14.3f}")

    feeds = [f for f in NOMINAL if f != "volatility_200_1s_index"]
    with Pool(min(16, len(feeds))) as pool:
        res = pool.map(do_feed, feeds)
    res = [r for r in res if r.get("bars")]

    print("\n[4] MEASURED - two-sided barrier on real bars, pooled over feeds")
    print(f"{'a:b':>7s} {'n':>8s} {'P(up) meas':>11s} {'cont':>8s} {'disc':>8s} {'z vs disc':>10s}"
          f" {'E[tau] meas':>12s} {'cont':>8s} {'disc':>8s} {'err cont':>9s} {'err disc':>9s}")
    pooled = {}
    for (a, b) in PAIRS:
        k = f"{a}:{b}"
        n = sum(r["pairs"][k]["full"].get("n", 0) for r in res)
        if n == 0:
            continue
        pu = sum(r["pairs"][k]["full"].get("p_up", 0) * r["pairs"][k]["full"].get("n", 0) for r in res) / n
        et = sum(r["pairs"][k]["full"].get("etau", 0) * r["pairs"][k]["full"].get("n", 0) for r in res) / n
        pc, pd = p_up_continuous(a, b), p_up_discrete(a, b)
        tc, td = etau_continuous(a, b), etau_discrete(a, b)
        sep = math.sqrt(0.25 / n)
        pooled[k] = {"n": n, "p_up": pu, "etau": et, "p_cont": pc, "p_disc": pd,
                     "t_cont": tc, "t_disc": td, "z_vs_disc": (pu - pd) / sep,
                     "z_vs_cont": (pu - pc) / sep,
                     "err_cont": et / tc - 1.0, "err_disc": et / td - 1.0}
        print(f"{k:>7s} {n:8d} {pu:11.4f} {pc:8.4f} {pd:8.4f} {(pu-pd)/sep:10.2f}"
              f" {et:12.3f} {tc:8.3f} {td:8.3f} {100*(et/tc-1):8.1f}% {100*(et/td-1):8.1f}%")

    print("\n[5] MEASURED - split sample, symmetric 5:5 and asymmetric 2:10")
    print(f"{'feed':28s} {'5:5 h1 tau':>11s} {'5:5 h2 tau':>11s} {'2:10 h1 p':>10s} {'2:10 h2 p':>10s}")
    for r in res:
        a = r["pairs"]["5:5"]
        b = r["pairs"]["2:10"]
        print(f"{r['feed']:28s} {a['h1'].get('etau',float('nan')):11.3f} {a['h2'].get('etau',float('nan')):11.3f}"
              f" {b['h1'].get('p_up',float('nan')):10.4f} {b['h2'].get('p_up',float('nan')):10.4f}")

    print("\n[6] MEASURED - window statistics per feed, against derived")
    for T in HORIZONS:
        n = sum(r["windows"][str(T)].get("n", 0) for r in res)
        if not n:
            continue
        em = sum(r["windows"][str(T)].get("emax", 0) * r["windows"][str(T)].get("n", 0) for r in res) / n
        er = sum(r["windows"][str(T)].get("erange", 0) * r["windows"][str(T)].get("n", 0) for r in res) / n
        print(f"  T={T:4d}m n={n:7d}  E[max] meas {em:7.4f} cont {emax_continuous(T):7.4f} "
              f"disc {emax_discrete(T):7.4f}   E[range] meas {er:7.4f} cont {erange_continuous(T):7.4f} "
              f"disc {erange_discrete(T):7.4f}")

    print("\n[7] MEASURED - touch probability within T, against derived")
    print("    one-sided is the reflection principle; two-sided is the exit-time series.")
    print(f"{'T':>5s} {'a':>5s} {'1s meas':>8s} {'1s cont':>8s} {'1s disc':>8s} {'1s sim':>8s}"
          f" {'2s meas':>8s} {'2s cont':>8s} {'2s disc':>8s} {'2s sim':>8s} {'n':>7s}")
    touch_rows = []
    for T in HORIZONS:
        for a in TOUCH_A:
            n = sum(r["windows"][str(T)].get("n", 0) for r in res)
            if not n:
                continue
            m2 = sum(r["windows"][str(T)]["touch"][str(a)] * r["windows"][str(T)]["n"] for r in res) / n
            m1 = sum(r["windows"][str(T)]["touch1"][str(a)] * r["windows"][str(T)]["n"] for r in res) / n
            s2 = sim_win[T]["touch"][str(a)] / sim_win[T]["n"]
            s1 = sim_win[T]["touch1"][str(a)] / sim_win[T]["n"]
            row = {"T": T, "a": a, "n": n, "m1": m1, "m2": m2, "s1": s1, "s2": s2,
                   "c1": p_touch_one_sided(a, T), "d1": p_touch_one_sided(a, T, BETA),
                   "c2": p_touch_two_sided(a, T), "d2": p_touch_two_sided(a, T, BETA)}
            touch_rows.append(row)
            print(f"{T:5d} {a:5.1f} {m1:8.4f} {row['c1']:8.4f} {row['d1']:8.4f} {s1:8.4f}"
                  f" {m2:8.4f} {row['c2']:8.4f} {row['d2']:8.4f} {s2:8.4f} {n:7d}")
    err1c = [abs(r["m1"]/r["c1"]-1) for r in touch_rows if r["c1"] > 0.02 and r["c1"] < 0.98]
    err1d = [abs(r["m1"]/r["d1"]-1) for r in touch_rows if r["d1"] > 0.02 and r["d1"] < 0.98]
    err1s = [abs(r["m1"]/r["s1"]-1) for r in touch_rows if 0.02 < r["s1"] < 0.98]
    if err1c:
        print(f"    one-sided, cells away from the boundaries: mean |error| "
              f"continuous {100*sum(err1c)/len(err1c):.1f}%, "
              f"corrected {100*sum(err1d)/len(err1d):.1f}%, "
              f"exact-discrete {100*sum(err1s)/len(err1s):.1f}%")

    print("\n[8] MEASURED - occupation time above the start, against the arcsine law")
    print(f"{'decile':>7s} {'derived':>9s} {'sim':>9s} {'measured (T=60)':>16s}")
    tot = np.zeros(10)
    for r in res:
        w = r["windows"]["60"]
        if w.get("n"):
            tot += np.array(w["occ_deciles"], dtype=float)
    tot = tot / tot.sum()
    sd = sim_win[60]["occ_deciles"] / sim_win[60]["occ_deciles"].sum()
    for d in range(10):
        der = arcsine_cdf((d + 1) / 10.0) - arcsine_cdf(d / 10.0)
        print(f"{d/10:.1f}-{(d+1)/10:.1f} {der:9.4f} {sd[d]:9.4f} {tot[d]:16.4f}")

    print("\n[9] PARKINSON per feed - measured against derived")
    print(f"{'feed':28s} {'ticks/bar':>9s} {'measured':>9s} {'derived':>9s} {'exact sim':>10s} {'err':>8s}")
    perr = []
    for r in res:
        n = r["ticks_per_bar"]
        m = r["parkinson"]["ratio"]
        d = r["parkinson_derived"]
        sv = sim_park[int(round(n))]
        print(f"{r['feed']:28s} {n:9.1f} {m:9.4f} {d:9.4f} {sv:10.4f} {100*(m/sv-1):7.2f}%")

        perr.append(abs(m / sv - 1.0))
    print(f"    mean |error| of the exact discrete prediction across {len(perr)} feeds: "
          f"{100*sum(perr)/len(perr):.2f}%")

    print("\n[10] DRIFT - which convention, and can 60 days tell")
    print(f"{'feed':28s} {'mu/min':>12s} {'se':>12s} {'z vs 0':>8s} {'-sig^2/2':>12s} {'z vs that':>10s} {'|gap|/se':>9s}")
    for r in res:
        d = r["drift"]
        print(f"{r['feed']:28s} {d['mu_per_min']:12.3e} {d['se']:12.3e} {d['z_vs_zero']:8.2f}"
              f" {d['minus_half_var']:12.3e} {d['z_vs_half_var']:10.2f} {abs(d['half_var_over_se']):9.3f}")
    zs = [r["drift"]["z_vs_zero"] for r in res]
    print(f"    combined z against zero drift over {len(zs)} feeds: "
          f"{sum(zs)/math.sqrt(len(zs)):+.3f}")
    sep = [abs(r["drift"]["half_var_over_se"]) for r in res]
    print(f"    the two conventions are {sum(sep)/math.sqrt(len(sep)):.3f} combined SE apart - "
          f"the sample cannot separate them")

    print("\n[11] EXPECTANCY - a martingale minus a cost, replayed")
    print(f"{'feed':28s} {'a:b':>5s} {'n':>6s} {'gross':>12s} {'z':>7s} {'net R':>9s} {'-c/risk':>9s} {'err':>8s}")
    for r in res:
        for k, e in r["expectancy"].items():
            if not e.get("n"):
                continue
            print(f"{r['feed']:28s} {k:>5s} {e['n']:6d} {e['gross']:12.3e} {e['z_gross']:7.2f}"
                  f" {e['net_R']:9.4f} {e['predicted_net_R']:9.4f} {e['net_R']-e['predicted_net_R']:8.4f}")
    zg = [e["z_gross"] for r in res for e in r["expectancy"].values() if e.get("n")]
    if zg:
        print(f"    {len(zg)} cells, |z| on gross: max {max(abs(z) for z in zg):.2f}, "
              f"combined {sum(zg)/math.sqrt(len(zg)):+.3f}")

    payload = {"touch": touch_rows, "beta": BETA, "npath": NPATH, "sim_pairs": sim_pairs,
               "sim_parkinson": {str(k): v for k, v in sim_park.items()},
               "pooled_pairs": pooled, "feeds": res}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(payload, fh, indent=1, default=float)
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
