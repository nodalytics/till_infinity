"""Step Index is a pure Gambler's Ruin, so its expectancy is a theorem. Try to
escape it.

`research/generators.md` measured the two facts that specify the process
completely: **99.9988% of 86,392 tick moves are exactly 0.1** and
**p(up) = 0.499734 +- 0.000220** over 5.18M implied flips, with no sign
autocorrelation to lag 30 and a Wald-Wolfowitz runs z of -1.354. The quoted
spread is **0.1 - exactly one step**. Range Break 100 and 200 are the same
shape: 99.98% of ticks move exactly one unit, spread one unit, plus a
memoryless break every 86.6 and 178.9 minutes.

That makes the instrument the most solved problem in probability, and it makes
the question a different one. Not "does this edge hold up" but "is there
*anything* - any order type, holding rule, entry filter or sizing scheme - that
has positive expectancy against a fair lattice walk charged one step to cross".

## What is derived

Let the step be `d`, the stop `S` steps below entry, the target `T` steps above,
and the round-trip cost `c` in price units.

* **hit probability** `P(target) = S/(S+T)`;
* **expected duration** `E[tau] = S*T` steps, with `Var[tau] = S*T*(S^2+T^2-2)/3`;
* **gross expectancy** `= 0` - this is optional stopping, not a measurement;
* **net expectancy** `= -c` per trade, or `-c/(S*d)` in R, at every geometry.

That last line is the whole of `generators.md`'s stop table derived rather than
replayed: -0.200, -0.100, -0.040, -0.020 at stops of 5, 10, 25 and 50 spreads
are `-0.1/0.5`, `-0.1/1.0`, `-0.1/2.5`, `-0.1/5.0`.

**And the theorem is much stronger than the barrier case.** Write the position
held over `[t, t+1)` as `w_t`, any function of the path up to `t`. Then

    E[ sum_t w_t * (P_{t+1} - P_t) ] = 0

for every such `w` with finite expected turnover - the martingale transform. The
cost is `(c/2) * sum_t |w_t - w_{t-1}|`, which is strictly positive whenever
anything is traded. So

    E[net] = -(c/2) * E[turnover] < 0

**for every strategy expressible as a position process.** Stops, targets,
trailing stops, break-even moves, scale-outs, pyramids, grids, martingale
doubling, entry filters and position sizing are all position processes. None of
them can change the sign. The only lever is turnover, and driving turnover to
its floor - one entry, one exit, held forever - gives exactly `-c`, never more.

## What would count as failure, written before running

1. **The theorem is wrong** if any rule in the battery returns a gross
   expectancy more than 3 standard errors from zero on both the real path and
   the simulated one. One rule out of twenty at 2 SE is arithmetic.
2. **The harness is dead** if the **look-ahead control** does not print a large
   positive number. A battery in which everything is zero is indistinguishable
   from a battery that computes zero, and this repository has published a
   statistic sitting on exactly its null twice. `cheat_next` is given tomorrow's
   step and must win enormously; if it does not, nothing else on the page reads.
3. **The closed forms are wrong** if measured hit rates and durations miss the
   derived values by more than their standard errors on the larger barriers.
4. **The premise is wrong** if the simulated fair walk and the real tick path
   disagree with each other.

## The three routes, again

**derived** (closed form), **simulated** (a fair lattice walk of the specified
step, which is numerical evaluation of the law and contains nothing from the
data), and **measured** (the real tick path). All three are printed together.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3

import numpy as np

DATA = os.environ.get("DATA", os.path.expanduser("~/till_infinity/data"))
DB = os.environ.get("DB", os.path.join(DATA, "research.db"))
OUT = os.environ.get("OUT", os.path.expanduser("~/till_infinity/logs/deriveruin.json"))
SIM_STEPS = int(os.environ.get("SIM_STEPS", "20000000"))
SEED = int(os.environ.get("SEED", "20260911"))

#: (feed, step size, quoted spread in price units)
LATTICE = [("step_index", 0.1, 0.1),
           ("range_break_100_index", 1.0, 1.0),
           ("range_break_200_index", 1.0, 1.0)]


# ---------------------------------------------------------------- derived ----
def p_target(S: float, T: float) -> float:
    return S / (S + T)


def p_target_overshoot(S: float, T: float, d: float) -> float:
    """Hit rate when the fill is recorded one step *past* the level.

    A lattice walk crosses a level by at most one step. A comparison that
    triggers strictly beyond the level therefore places the effective stop at
    `S+d` and the effective target at `T+d`, and the ruin formula applies to
    those. This is the lattice form of the continuity correction in
    `derivegbm.py`, and it is a property of the *fill rule* rather than of the
    instrument.
    """
    return (S + d) / (S + T + 2.0 * d)


def etau(S_steps: float, T_steps: float) -> float:
    return S_steps * T_steps


def vartau(S: float, T: float) -> float:
    return S * T * (S * S + T * T - 2.0) / 3.0


def net_expectancy_R(c: float, S_price: float) -> float:
    return -c / S_price


# -------------------------------------------------------- position process ----
# Every rule returns `w`, the position held over [t, t+1), decided from p[0..t]
# only. Gross P&L is then sum w_t * (p_{t+1} - p_t) and the cost is
# (c/2) * sum |w_t - w_{t-1}|, which is the theorem stated as code.
def _pnl(p: np.ndarray, w: np.ndarray, c: float) -> dict:
    dp = np.diff(p)
    m = min(len(w), len(dp))
    w = w[:m]
    inc = w * dp[:m]
    turn = float(np.abs(np.diff(np.concatenate([[0.0], w, [0.0]]))).sum())
    gross = float(inc.sum())
    # block the increments to get an honest standard error on a serially
    # structured path: 200 blocks, not 86,000 correlated ticks.
    nb = 200
    bs = max(1, m // nb)
    blocks = np.array([inc[i:i + bs].sum() for i in range(0, bs * (m // bs), bs)])
    se = float(blocks.std(ddof=1) * math.sqrt(len(blocks))) if len(blocks) > 2 else float("nan")
    return {"gross": gross, "turnover": turn, "cost": 0.5 * c * turn,
            "net": gross - 0.5 * c * turn, "se_gross": se,
            "z_gross": gross / se if se and se == se and se > 0 else float("nan"),
            "n": m}


def w_barrier(p, S, T):
    n = len(p)
    w = np.zeros(n)
    i = 0
    while i < n - 1:
        e = p[i]
        j = i + 1
        while j < n and e - S < p[j] < e + T:
            j += 1
        w[i:j] = 1.0
        # One flat tick between trades. Without it a rule that re-enters at the
        # exit price is *indistinguishable from holding* and pays one spread for
        # the whole sample, which is not what a broker charges. The flat tick is
        # what makes `turnover` count round trips.
        i = j + 1
    return w


def w_time_stop(p, K):
    n = len(p)
    w = np.zeros(n)
    i = 0
    while i < n - 1:
        j = min(i + K, n - 1)
        w[i:j] = 1.0
        i = j + 1
    return w


def w_trail(p, D):
    n = len(p)
    w = np.zeros(n)
    i = 0
    while i < n - 1:
        hw = p[i]
        j = i + 1
        while j < n:
            hw = max(hw, p[j])
            if p[j] <= hw - D:
                break
            j += 1
        w[i:j] = 1.0
        i = j + 1
    return w


def w_breakeven(p, S, T, trig):
    n = len(p)
    w = np.zeros(n)
    i = 0
    while i < n - 1:
        e = p[i]
        stop = e - S
        j = i + 1
        while j < n:
            if p[j] >= e + trig:
                stop = max(stop, e)
            if p[j] <= stop or p[j] >= e + T:
                break
            j += 1
        w[i:j] = 1.0
        i = j + 1
    return w


def w_scaleout(p, S):
    n = len(p)
    w = np.zeros(n)
    i = 0
    while i < n - 1:
        e = p[i]
        size = 2.0
        j = i + 1
        while j < n:
            if size == 2.0 and p[j] >= e + S:
                size = 1.0
            if p[j] <= e - S or p[j] >= e + 3.0 * S:
                break
            w[j] = size
            j += 1
        w[i] = 2.0
        i = j + 1
    return w


def w_pyramid(p, S):
    n = len(p)
    w = np.zeros(n)
    i = 0
    while i < n - 1:
        e = p[i]
        size = 1.0
        hw = e
        j = i + 1
        while j < n:
            hw = max(hw, p[j])
            if size < 3.0 and p[j] >= e + size * S:
                size += 1.0
            if p[j] <= hw - S:
                break
            w[j] = size
            j += 1
        w[i] = 1.0
        i = j + 1
    return w


def w_double(p, S, cap, after_loss=True):
    n = len(p)
    w = np.zeros(n)
    i = 0
    size = 1.0
    while i < n - 1:
        e = p[i]
        j = i + 1
        won = False
        while j < n:
            if p[j] >= e + S:
                won = True
                break
            if p[j] <= e - S:
                break
            j += 1
        w[i:j] = size
        j += 1
        if after_loss:
            size = 1.0 if won else min(size * 2.0, cap)
        else:
            size = min(size * 2.0, cap) if won else 1.0
        i = j
    return w


def w_grid(p, S, maxadds, target):
    n = len(p)
    w = np.zeros(n)
    i = 0
    while i < n - 1:
        e = p[i]
        size = 1.0
        basis = e
        j = i + 1
        while j < n:
            if size < maxadds and p[j] <= e - size * S:
                basis = (basis * size + p[j]) / (size + 1.0)
                size += 1.0
            if p[j] >= basis + target:
                break
            w[j] = size
            j += 1
        w[i] = 1.0
        i = j + 1
    return w


def w_always_in(p, S):
    n = len(p)
    w = np.zeros(n)
    side = 1.0
    e = p[0]
    for t in range(n):
        if side * (p[t] - e) <= -S:
            side = -side
            e = p[t]
        w[t] = side
    return w


def w_hold(p):
    return np.ones(len(p))


def w_entry_filter(p, S, k, want_up):
    """Enter only after `k` consecutive steps in one direction, then a barrier.

    This is the strong Markov property as a trade. Increments are independent,
    so conditioning the entry on any function of the past cannot change the
    conditional law of what follows.
    """
    n = len(p)
    w = np.zeros(n)
    s = np.sign(np.diff(p))
    want = 1.0 if want_up else -1.0
    run = 0
    i = 1
    while i < n - 1:
        run = run + 1 if s[i - 1] == want else 0
        if run >= k:
            e = p[i]
            j = i + 1
            while j < n and e - S < p[j] < e + S:
                j += 1
            w[i:j] = 1.0
            i = j + 1
            run = 0
        else:
            i += 1
    return w


def w_streak_size(p, S, maxsize):
    n = len(p)
    w = np.zeros(n)
    s = np.sign(np.diff(p))
    i = 1
    while i < n - 1:
        run = 0
        k = i - 1
        while k >= 0 and s[k] == s[i - 1] and s[k] != 0:
            run += 1
            k -= 1
            if run >= maxsize:
                break
        size = float(max(1, run))
        e = p[i]
        j = i + 1
        while j < n and e - S < p[j] < e + S:
            j += 1
        w[i:j] = size
        i = j + 1
    return w


def w_lookback_sign(p, L, sign):
    n = len(p)
    w = np.zeros(n)
    w[L:] = sign * np.sign(p[L:] - p[:-L])[: n - L]
    return w


def w_random(p, rng, S):
    """Independent of the path: sizes drawn from a coin that never sees prices.

    A control for the sizing theorem - a *random* predictable size must also
    give zero gross, because independence is enough.
    """
    n = len(p)
    w = np.zeros(n)
    i = 0
    while i < n - 1:
        size = float(rng.integers(1, 5))
        e = p[i]
        j = i + 1
        while j < n and e - S < p[j] < e + S:
            j += 1
        w[i:j] = size
        i = j + 1
    return w


def w_cheat_next(p):
    """LOOK-AHEAD POSITIVE CONTROL. Holds the sign of the next step.

    This is not a strategy. It exists so that a table of zeros can be told apart
    from a harness that computes zero. It must print an enormous number.
    """
    n = len(p)
    w = np.zeros(n)
    w[: n - 1] = np.sign(np.diff(p))
    return w


def battery(p: np.ndarray, d: float, c: float, rng) -> dict:
    S5, S25 = 5 * d, 25 * d
    rules = {
        "barrier 5:5": w_barrier(p, S5, S5),
        "barrier 5:10": w_barrier(p, S5, 10 * d),
        "barrier 5:15": w_barrier(p, S5, 15 * d),
        "barrier 25:25": w_barrier(p, S25, S25),
        "time stop 50": w_time_stop(p, 50),
        "time stop 500": w_time_stop(p, 500),
        "trailing 5": w_trail(p, S5),
        "trailing 25": w_trail(p, S25),
        "breakeven 5/3/10": w_breakeven(p, S5, 10 * d, 3 * d),
        "scale-out 5": w_scaleout(p, S5),
        "pyramid 5": w_pyramid(p, S5),
        "double after loss": w_double(p, S5, 8.0, True),
        "double after win": w_double(p, S5, 8.0, False),
        "grid 5 x4": w_grid(p, S5, 4, 2 * d),
        "always-in 5": w_always_in(p, S5),
        "hold, no exit": w_hold(p),
        "entry: 3 up then 5:5": w_entry_filter(p, S5, 3, True),
        "entry: 5 down then 5:5": w_entry_filter(p, S5, 5, False),
        "size = streak, 5:5": w_streak_size(p, S5, 6),
        "momentum 100": w_lookback_sign(p, 100, +1),
        "reversion 100": w_lookback_sign(p, 100, -1),
        "random size 5:5": w_random(p, rng, S5),
        "CONTROL cheat_next": w_cheat_next(p),
    }
    return {k: _pnl(p, w, c) for k, w in rules.items()}


# --------------------------------------------------------------- measured ----
def barrier_stats(p: np.ndarray, S: float, T: float, strict_past: bool) -> dict:
    """Non-overlapping barrier trades. `strict_past` records the fill one step
    beyond the level, which is what `genstop.py` does."""
    n = len(p)
    i = 0
    wins = 0
    taus = []
    res = []
    while i < n - 1:
        e = p[i]
        j = i + 1
        hit = 0
        while j < n:
            if (p[j] < e - S) if strict_past else (p[j] <= e - S):
                hit = -1
                break
            if (p[j] > e + T) if strict_past else (p[j] >= e + T):
                hit = 1
                break
            j += 1
        if hit == 0:
            break
        wins += 1 if hit > 0 else 0
        taus.append(j - i)
        res.append(p[j] - e)
        i = j
    if len(taus) < 10:
        return {"n": 0}
    t = np.array(taus, dtype=float)
    r = np.array(res)
    return {"n": len(taus), "p_target": wins / len(taus), "etau": float(t.mean()),
            "se_p": math.sqrt(0.25 / len(taus)),
            "se_tau": float(t.std(ddof=1) / math.sqrt(len(t))),
            "sd_tau": float(t.std(ddof=1)),
            "gross": float(r.mean()), "se_gross": float(r.std(ddof=1) / math.sqrt(len(r)))}


def lattice_path(feed: str, d: float) -> np.ndarray:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = conn.execute("SELECT ts, bid, ask FROM ticks WHERE feed=? ORDER BY ts ASC",
                        (feed,)).fetchall()
    conn.close()
    mid = np.array([(b + a) / 2.0 for _, b, a in rows
                    if b is not None and a is not None and b > 0], dtype=float)
    return mid


def break_stats(feed: str) -> dict:
    """Range Break: the break rate, memorylessness, and the value of knowing it."""
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = conn.execute(
        "SELECT ts, high, low, close FROM bars WHERE feed=? AND interval='1m' ORDER BY ts",
        (feed,)).fetchall()
    conn.close()
    hi = np.array([r[1] for r in rows], dtype=float)
    lo = np.array([r[2] for r in rows], dtype=float)
    rng = hi - lo
    brk = np.flatnonzero(rng > 66)
    if len(brk) < 10:
        return {"n_breaks": int(len(brk))}
    gaps = np.diff(brk).astype(float)
    lam = float(gaps.mean())
    return {"bars": len(rows), "n_breaks": int(len(brk)), "mean_gap_min": lam,
            "cv_gap": float(gaps.std(ddof=1) / lam),
            "p_break_in_60m": 1.0 - math.exp(-60.0 / lam),
            "p_break_in_240m": 1.0 - math.exp(-240.0 / lam),
            "mean_break_size": float(rng[brk].mean()),
            "median_range_nonbreak": float(np.median(rng[rng <= 66]))}


def main() -> None:
    rng = np.random.default_rng(SEED)
    out = {"derived": {}, "sim": {}, "measured": {}}

    print("=" * 108)
    print("GAMBLER'S RUIN, DERIVED - and twenty-three attempts to escape it")
    print("=" * 108)

    print("\n[1] DERIVED - exact, for a fair lattice walk of step d, cost c")
    print(f"{'S:T (steps)':>12s} {'P(target)':>10s} {'P w/ overshoot':>15s} {'E[tau]':>10s} {'sd[tau]':>10s}")
    GEOM = [(5, 5), (5, 10), (5, 15), (10, 10), (25, 25), (50, 50), (5, 50), (50, 5)]
    for (S, T) in GEOM:
        print(f"{S:5d}:{T:<6d} {p_target(S,T):10.4f} {p_target_overshoot(S,T,1.0):15.4f}"
              f" {etau(S,T):10.1f} {math.sqrt(vartau(S,T)):10.1f}")
        out["derived"][f"{S}:{T}"] = {"p": p_target(S, T), "p_over": p_target_overshoot(S, T, 1.0),
                                      "etau": etau(S, T), "sdtau": math.sqrt(vartau(S, T))}

    print("\n    generators.md's stop table, derived rather than replayed:")
    print(f"    {'stop (spreads)':>15s} {'net R = -c/(S*d)':>18s} {'generators.md':>15s}")
    for sp, meas in ((5, -0.200), (10, -0.100), (25, -0.040), (50, -0.020)):
        print(f"    {sp:15d} {net_expectancy_R(0.1, sp*0.1):18.4f} {meas:15.3f}")

    print("\n    and its hit rates, which sit above S/(S+T) by exactly one step of fill:")
    print(f"    {'target':>8s} {'S/(S+T)':>10s} {'(S+d)/(S+T+2d)':>16s} {'generators.md':>15s}")
    for T, meas in ((5, 0.4998), (10, 0.3525), (15, 0.2722)):
        print(f"    {T/5:7.0f}R {p_target(5,T):10.4f} {p_target_overshoot(5,T,1.0):16.4f} {meas:15.4f}")

    print(f"\n[2] SIMULATED - a fair +-1 lattice walk, {SIM_STEPS:,} steps")
    sim = np.concatenate([[0.0], np.cumsum(rng.choice([-1.0, 1.0], size=SIM_STEPS))])
    print(f"{'S:T':>10s} {'P(target)':>10s} {'derived':>9s} {'z':>7s} {'E[tau]':>10s} {'derived':>9s} {'err':>8s} {'n':>8s}")
    for (S, T) in GEOM:
        st = barrier_stats(sim, S, T, strict_past=False)
        if not st["n"]:
            continue
        z = (st["p_target"] - p_target(S, T)) / st["se_p"]
        print(f"{S:4d}:{T:<5d} {st['p_target']:10.4f} {p_target(S,T):9.4f} {z:7.2f}"
              f" {st['etau']:10.1f} {etau(S,T):9.1f} {100*(st['etau']/etau(S,T)-1):7.2f}% {st['n']:8d}")
        out["sim"][f"{S}:{T}"] = st

    print("\n[3] MEASURED - the real tick paths")
    for feed, d, c in LATTICE:
        p = lattice_path(feed, d)
        if len(p) < 10000:
            print(f"  {feed}: {len(p)} ticks, skipped")
            continue
        steps = np.diff(p) / d
        frac1 = float((np.abs(np.abs(steps) - 1.0) < 1e-6).mean())
        print(f"\n  {feed}: {len(p):,} ticks, {100*frac1:.4f}% are exactly one step, "
              f"p(up) = {float((steps>0).mean()):.6f}")
        print(f"{'  S:T':>10s} {'P(target)':>10s} {'derived':>9s} {'z':>7s} {'E[tau]':>10s} {'derived':>9s} {'err':>8s} {'n':>7s}")
        out["measured"].setdefault(feed, {})
        for (S, T) in GEOM:
            st = barrier_stats(p, S * d, T * d, strict_past=False)
            if not st["n"]:
                continue
            z = (st["p_target"] - p_target(S, T)) / st["se_p"]
            print(f"{S:4d}:{T:<5d} {st['p_target']:10.4f} {p_target(S,T):9.4f} {z:7.2f}"
                  f" {st['etau']:10.1f} {etau(S,T):9.1f} {100*(st['etau']/etau(S,T)-1):7.2f}% {st['n']:7d}")
            out["measured"][feed][f"{S}:{T}"] = st

    print("\n[4] THE FILL RULE, isolated - same path, barrier recorded one step past the level")
    p = lattice_path("step_index", 0.1)
    print(f"{'S:T':>10s} {'at the level':>13s} {'derived':>9s} {'one step past':>14s} {'derived':>9s}")
    for (S, T) in [(5, 10), (5, 15), (5, 25)]:
        a = barrier_stats(p, S * 0.1, T * 0.1, strict_past=False)
        b = barrier_stats(p, S * 0.1, T * 0.1, strict_past=True)
        print(f"{S:4d}:{T:<5d} {a.get('p_target',float('nan')):13.4f} {p_target(S,T):9.4f}"
              f" {b.get('p_target',float('nan')):14.4f} {p_target_overshoot(S,T,1.0):9.4f}")

    print("\n[5] THE ESCAPE BATTERY - every rule is a position process, so every")
    print("    rule must return gross zero. Cost is (c/2) * turnover, by construction.")
    for label, path, d, c in (("SIMULATED fair walk", sim[: min(len(sim), 4000000)], 1.0, 1.0),
                              ("MEASURED step_index", lattice_path("step_index", 0.1), 0.1, 0.1)):
        print(f"\n  --- {label} ({len(path):,} steps, d={d:g}, c={c:g}) ---")
        print(f"{'rule':24s} {'gross':>12s} {'se':>11s} {'z':>7s} {'turnover':>11s} "
              f"{'cost':>12s} {'net':>12s} {'net/turn':>9s}")
        res = battery(path, d, c, rng)
        for k, v in res.items():
            print(f"{k:24s} {v['gross']:12.2f} {v['se_gross']:11.2f} {v['z_gross']:7.2f}"
                  f" {v['turnover']:11.0f} {v['cost']:12.2f} {v['net']:12.2f}"
                  f" {v['net']/max(v['turnover'],1e-9):9.4f}")
        zs = [v["z_gross"] for k, v in res.items()
              if not k.startswith("CONTROL") and v["z_gross"] == v["z_gross"]]
        nt = [v["net"] / max(v["turnover"], 1e-9) for k, v in res.items()
              if not k.startswith("CONTROL") and v["turnover"] > 10]
        print(f"    {len(zs)} non-control rules: max |z| on gross = {max(abs(z) for z in zs):.2f}, "
              f"{sum(1 for z in zs if abs(z) > 2)} past |z|=2. They share one path, so these "
              f"are not independent tests and no combined z is quoted.")
        print(f"    net per unit of turnover: range [{min(nt):+.4f}, {max(nt):+.4f}] "
              f"against the derived -c/2 = {-0.5*c:+.4f}")
        ctl = res["CONTROL cheat_next"]
        print(f"    LOOK-AHEAD CONTROL: gross {ctl['gross']:,.1f} on turnover "
              f"{ctl['turnover']:,.0f}, net per unit turnover {ctl['net']/ctl['turnover']:+.4f} "
              f"against every real rule's {-0.5*c:+.4f}. The harness can see an edge.")
        out.setdefault("battery", {})[label] = res

    print("\n[5b] IS IT ACTUALLY A FREE WALK? the diffusion curve, on 60 days of bars")
    print("     Var(C_{t+n} - C_t) / (n * ticks_per_bar * d^2) must be 1.0 at every n for")
    print("     iid steps. step_index is the positive control. `ex-break` drops the bars")
    print("     containing a break, whose single-tick variance swamps everything else.")
    LAGS = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000]
    print(f"{'feed':34s} " + " ".join(f"{n:>7d}" for n in LAGS))
    diff = {}
    for feed, d, c in LATTICE:
        conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        rows = conn.execute("SELECT high, low, close FROM bars WHERE feed=? AND "
                            "interval='1m' ORDER BY ts", (feed,)).fetchall()
        conn.close()
        cl = np.array([r[2] for r in rows], dtype=float)
        hl = np.array([r[0] - r[1] for r in rows], dtype=float)
        tpb = 60.0
        isbrk = hl > 66.0 * d
        for tag, series in ((" (all bars)", cl),
                            (" (ex-break)", None),
                            (" (shuffled)", None)):
            if tag == " (ex-break)":
                inc = np.diff(cl)
                keep = ~(isbrk[1:] | isbrk[:-1])
                inc = inc[keep]
                series = np.concatenate([[0.0], np.cumsum(inc)])
            elif tag == " (shuffled)":
                inc = np.diff(cl).copy()
                rng.shuffle(inc)
                series = np.concatenate([[0.0], np.cumsum(inc)])
            row = []
            for n in LAGS:
                if len(series) <= n + 100:
                    row.append(float("nan"))
                    continue
                dd = series[n:] - series[:-n]
                row.append(float(dd.var(ddof=1) / (n * tpb * d * d)))
            diff[feed + tag] = row
            print(f"{feed+tag:34s} " + " ".join(f"{v:7.3f}" for v in row))
    out["diffusion"] = {"lags": LAGS, "curves": diff}

    print("\n[5c] WHAT ANY CONFINEMENT IS WORTH - fade an m-bar move, hold n bars")
    print("     gross per trade in price units against the spread, on 60 days of bars,")
    print("     non-overlapping, with each series' own return shuffle as the null and")
    print("     the day split in half.")
    print(f"{'feed':24s} {'m':>4s} {'n':>4s} {'thr':>5s} {'gross':>9s} {'se':>8s} {'z':>6s}"
          f" {'shuffled':>9s} {'h1':>9s} {'h2':>9s} {'spread':>7s} {'trades':>7s}")
    fade = []
    for feed, d, c in LATTICE:
        conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        cl = np.array([r[0] for r in conn.execute(
            "SELECT close FROM bars WHERE feed=? AND interval='1m' ORDER BY ts", (feed,))],
            dtype=float)
        conn.close()
        inc = np.diff(cl)
        sh = inc.copy()
        rng.shuffle(sh)
        qs = np.concatenate([[cl[0]], cl[0] + np.cumsum(sh)])
        for m in (5, 15, 60, 240):
            for n in (5, 15, 60, 240):
                for thr in (0.0, 1.0, 2.0):
                    rows = []
                    for series in (cl, qs):
                        L = len(series)
                        past = series[m:L - n] - series[:L - n - m]
                        fut = series[m + n:] - series[m:L - n]
                        sd = past.std(ddof=1)
                        keep = np.flatnonzero(np.abs(past) >= thr * sd)
                        pick, last = [], -10 ** 9
                        for ix in keep:
                            if ix - last >= m + n:
                                pick.append(ix)
                                last = ix
                        if len(pick) < 60:
                            rows.append(None)
                            continue
                        gg = -np.sign(past[pick]) * fut[pick]
                        h = len(gg) // 2
                        rows.append((float(gg.mean()),
                                     float(gg.std(ddof=1) / math.sqrt(len(gg))),
                                     float(gg[:h].mean()), float(gg[h:].mean()), len(gg)))
                    if rows[0] is None:
                        continue
                    r, sv = rows[0], rows[1]
                    z = r[0] / r[1] if r[1] else float("nan")
                    print(f"{feed:24s} {m:4d} {n:4d} {thr:5.1f} {r[0]:9.4f} {r[1]:8.4f} {z:6.2f}"
                          f" {(sv[0] if sv else float('nan')):9.4f} {r[2]:9.4f} {r[3]:9.4f}"
                          f" {c:7.2f} {r[4]:7d}")
                    fade.append({"feed": feed, "m": m, "n": n, "thr": thr, "gross": r[0],
                                 "se": r[1], "z": z, "shuffled": sv[0] if sv else None,
                                 "h1": r[2], "h2": r[3], "spread": c, "trades": r[4]})
    out["fade"] = fade
    for feed, d, c in LATTICE:
        sub = [f for f in fade if f["feed"] == feed]
        if not sub:
            continue
        best = max(sub, key=lambda f: f["gross"])
        surv = [f for f in sub if f["gross"] > f["spread"] and f["h1"] > 0 and f["h2"] > 0
                and f["shuffled"] is not None and f["gross"] > f["shuffled"] and f["z"] > 2]
        print(f"     {feed}: {len(sub)} cells, largest gross {best['gross']:.4f} "
              f"(m={best['m']} n={best['n']} thr={best['thr']}, z={best['z']:.2f}) = "
              f"{100*best['gross']/best['spread']:.1f}% of the spread; "
              f"{len(surv)} cells clear the spread, their own shuffle, both halves and z=2.")

    print("\n[6] RANGE BREAK - a lattice walk plus a memoryless break")
    for feed in ("range_break_100_index", "range_break_200_index"):
        b = break_stats(feed)
        out.setdefault("breaks", {})[feed] = b
        if not b.get("n_breaks"):
            continue
        print(f"  {feed}: {b['n_breaks']} breaks in {b['bars']} bars, one every "
              f"{b['mean_gap_min']:.1f} min, CV {b['cv_gap']:.3f}")
        print(f"     derived P(a break inside a 60m hold)  = 1 - exp(-60/{b['mean_gap_min']:.1f})"
              f"  = {b['p_break_in_60m']:.4f}")
        print(f"     derived P(a break inside a 240m hold) = {b['p_break_in_240m']:.4f}")
        print(f"     mean break size {b['mean_break_size']:.1f} units against a "
              f"median non-break range of {b['median_range_nonbreak']:.1f}")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(out, fh, indent=1, default=float)
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
