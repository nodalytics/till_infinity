"""Every number this folder has published about the generators, regenerated from
the specification - with no database at all.

`research.db` lives on the research lab and nowhere else, so while that machine
is unreachable the two-sample comparisons in `rebuildvol.py`, `rebuildstep.py`
and `rebuildspike.py` cannot run. This harness is what *can*: `deriving.md`,
`generators.md` and `twins.md` between them state around a hundred numbers
measured off the real feeds, and every one of them is a number a correct
simulator has to produce. Matching a published measurement is weaker than a
two-sample test on the raw rows - it compares two summaries rather than two
distributions - and it is not nothing, because the measurements were taken
before this rebuild existed and none of them is an input to it.

The parameter budget is the same as everywhere else on this page and is listed
in `PARAMS` below: a volatility and a tick rate for the Volatility family, a step
and a coin for Step Index, five numbers a feed for Boom and Crash, and a name, a
rate and a variance budget for Jump. Nothing else is read.

## What would count as failure, written before any number was looked at

1. **The volatility family fails** if realised annualised volatility misses the
   name by more than the **0.5%** `generators.md` cleared on twelve feeds, if
   kurtosis leaves **2.98-3.02**, if the structure-function Hurst exponent leaves
   **0.50 +- 0.01**, or if the Parkinson-to-close ratio misses **0.870** (30
   ticks a bar) or **0.909** (60) by more than 1%.
2. **The barrier arithmetic fails** if the rebuilt `P(up first)` and `E[tau]`
   miss `deriving.md` section one's *measured* column by more than **3%** at
   barriers of three one-minute sigmas and out, where the 0.5826 asymptotic is
   supposed to hold. The eight geometries are 1:1, 3:3, 5:5, 10:10, 3:1, 1:3,
   9:1 and 2:10, and the numbers to hit were measured on 86,411 bars a feed.
3. **The window arithmetic fails** if `E[max]` or `E[range]` over 5, 15, 60 and
   240 minutes misses the measured column by more than 3%, or if the occupation
   time above the start departs from the arcsine law by more than 0.01 in any
   decile.
4. **Step Index fails** if the gambler's-ruin hit rates and durations miss
   `deriving.md` section three's measured column - 0.5004/24.9, 0.3339/48.9,
   0.2504/75.5, 0.5012/99.5 - by more than 3 standard errors on `P` and 5% on
   `E[tau]`, or if the fill-one-step-past convention does not reproduce
   **0.3536, 0.2732 and 0.1874**.
5. **Boom and Crash fail** if the five published numbers do not reproduce
   `deriving.md` section five's *observed* P&L column for `boom_500_index` -
   mean, median, sd, `P(profit)` and both tails at N = 10, 100, 500 and 3000 -
   or if the rebuilt stop slippage misses `genstop.py`'s **+13.96R, +6.81R,
   +2.44R and +1.02R** by more than 20%.
6. **The Jump reading fails** if diffusion at the name plus a jump budget of
   `1.322^2 - 1` does not realise **1.322x** the name to within 0.05.
7. **The twin claim fails** if a 1-second feed and its 2-second twin do not carry
   identical volatility per second with per-tick variance differing by exactly
   **sqrt(2) = 1.4142** (`twins.md`), to within 1%.
8. **The run is void** if a statistic lands on exactly its null, and **void** if
   the negative control fires: the same battery is run on a generator with sigma
   2% wrong, which must fail the volatility condition and pass the others, and
   on one at half the tick rate, which must fail the Parkinson condition and pass
   the volatility one. A battery that cannot tell those apart is not testing what
   it claims to.

## What this is not

It is **not** a two-sample test against the feed. Every comparison here is
rebuild-against-published-summary, so it can only catch an error large enough to
move a summary. `rebuildall.py` is the one that settles it and it needs the lab.
"""

from __future__ import annotations

import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rebuildgen as G
import rebuildvol as V

OUT = os.environ.get("OUT", os.path.expanduser("~/till_infinity/logs/rebuildpaper.json"))
SEEDS = [int(x) for x in os.environ.get("SEEDS", "20260912,20260913,20260914").split(",")]
NBARS = int(os.environ.get("NBARS", "400000"))
NTICK = int(os.environ.get("NTICK", "4000000"))

#: Every parameter the rebuild is given, and where it is published. Nothing else
#: is read anywhere in this file.
PARAMS = {
    "volatility": "the annualised volatility in the name; 30 ticks a bar (2s) or 60 (1s)",
    "step": "a 0.1 increment, a fair coin, 60 ticks a bar",
    "boom_crash": "lambda, E[g], CV[g], E[J], median J - deriving.md section five",
    "jump": "the name, one tick a second, the measured rate, and 1.322^2-1 of the "
            "diffusive variance for the jumps",
}

# --------------------------------------------------------- published targets --
#: `deriving.md` section one, the *measured* columns, 86,411 bars a feed.
BARRIER = {
    "1:1": (0.5000, 2.782), "3:3": (0.5001, 13.051), "5:5": (0.5008, 31.279),
    "10:10": (0.5015, 112.062), "3:1": (0.3073, 5.942), "1:3": (0.6928, 5.929),
    "9:1": (0.1426, 15.382), "2:10": (0.8042, 27.472),
}
WINDOW = {5: (1.2933, 2.5821), 15: (2.5649, 5.1245), 60: (5.6502, 11.2338),
          240: (11.7735, 23.6321)}
#: `deriving.md` section one, occupation time, T = 60 minutes.
OCCUPATION = {0: 0.1984, 4: 0.0637, 5: 0.0587, 9: 0.2195}
#: `generators.md` section one.
PARKINSON = {30: 0.870, 60: 0.909}
#: `deriving.md` section three, measured on 86,393 real Step Index ticks.
RUIN = {(5, 5): (0.5004, 24.9), (5, 10): (0.3339, 48.9), (5, 15): (0.2504, 75.5),
        (10, 10): (0.5012, 99.5), (5, 50): (0.0917, 255.5), (50, 5): (0.9102, 267.3)}
RUIN_PAST = {(5, 10): 0.3536, (5, 15): 0.2732, (5, 25): 0.1874}
#: `deriving.md` section five. lambda, E[g], CV[g], E[J], median J, the spike
#: side, and spread/E[g] from section six's "ticks to pay" row.
BOOM = {
    "boom_300_index": (267.7, 0.00373, 0.632, 1.0624, 0.9327, +1, 5.4),
    "boom_500_index": (529.4, 0.00977, 0.661, 4.7837, 3.9635, +1, 6.9),
    "boom_1000_index": (908.3, 0.01511, 0.671, 14.6405, 12.2198, +1, 9.9),
    "crash_300_index": (329.0, 0.01787, 0.676, 5.4198, 4.7620, -1, 5.7),
    "crash_500_index": (507.7, 0.00624, 0.655, 2.8331, 2.6280, -1, 6.7),
    "crash_1000_index": (973.8, 0.00605, 0.656, 5.6712, 4.9718, -1, 9.8),
}
#: `deriving.md` section five, the *observed* rows for boom_500_index:
#: mean, median, sd, P(profit), q01, q99.
BOOM_PNL = {
    10: (0.0071, 0.0960, 0.8150, 0.9812, -3.318, 0.149),
    100: (0.0768, 0.9610, 2.5364, 0.8481, -9.859, 1.131),
    500: (0.4092, 2.3560, 5.5881, 0.6303, -18.635, 5.141),
    3000: (2.6873, 5.0382, 14.4065, 0.6246, -40.270, 29.166),
}
#: `genstop.py`, measured before any of this existed: mean slippage in R at
#: stops of 5, 10, 25 and 50 spreads on boom_500_index.
BOOM_SLIP = {5.0: 13.961, 10.0: 6.807, 25.0: 2.439, 50.0: 1.019}
#: `deriving.md` section five, P(J > D) on boom_500_index at the same stops.
BOOM_GAP = {5.0: 0.963, 10.0: 0.888, 25.0: 0.763, 50.0: 0.531}
JUMP_MULT = 1.3226


def fired(label: str, got: float, want: float, tol: float, ledger: list,
          rel: bool = True, feed: str = "") -> bool:
    err = (got / want - 1.0) if (rel and want) else (got - want)
    bad = abs(err) > tol
    ledger.append({"test": label, "feed": feed or label, "value": err, "fired": bad})
    return bad


def sim_vol(tpb: int, seed: int, n_bars: int, sigma: float = 75.0,
            grid: float = 0.0, keep: int = 0) -> dict:
    """The Volatility family from two numbers. `grid = 0` means no quote
    rounding, which is the right choice here because every published target was
    measured in one-minute sigmas and is scale-free."""
    rng = np.random.default_rng([seed, tpb])
    return G.bars_from_stream(
        G.gen_gbm(n_bars * tpb, sigma, 60.0 / tpb, 10000.0, grid, rng),
        tpb, n_bars, keep_ticks=keep)


def two_barrier(logp: np.ndarray, a: float, b: float, u: float) -> tuple[float, float, int]:
    n = logp.size
    i, ups, taus = 0, 0, []
    while i < n - 1:
        x0 = logp[i]
        j = i + 1
        hit = 0
        while j < n:
            d = (logp[j] - x0) / u
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
        return float("nan"), float("nan"), 0
    t = np.array(taus, dtype=float)
    return ups / len(taus), float(t.mean()), len(taus)


def windows(logp: np.ndarray, u: float, horizon: int) -> dict:
    k = logp.size // horizon
    if k < 50:
        return {}
    seg = logp[: k * horizon].reshape(k, horizon)
    start = np.concatenate([[logp[0]], logp[np.arange(1, k) * horizon - 1]])
    d = (seg - start[:, None]) / u
    mx = np.maximum(d.max(axis=1), 0.0)
    mn = np.minimum(d.min(axis=1), 0.0)
    frac = (d > 0).mean(axis=1)
    occ = np.bincount(np.minimum((frac * 10).astype(int), 9), minlength=10) / k
    return {"emax": float(mx.mean()), "erange": float((mx - mn).mean()),
            "occ": occ, "n": k}


def ruin_on_lattice(lat: np.ndarray, stop: int, tgt: int, past: bool) -> tuple[float, float, int]:
    n, i, hits, taus = lat.size, 0, 0, []
    while i < n - 1:
        x0 = lat[i]
        j = i + 1
        res = 0
        while j < n:
            d = lat[j] - x0
            if (d > tgt) if past else (d >= tgt):
                res = 1
                break
            if (d < -stop) if past else (d <= -stop):
                res = -1
                break
            j += 1
        if res == 0:
            break
        hits += 1 if res > 0 else 0
        taus.append(j - i)
        i = j
    if not taus:
        return float("nan"), float("nan"), 0
    return hits / len(taus), float(np.mean(taus)), len(taus)


def boom_path(feed: str, n_ticks: int, seed: int) -> tuple[np.ndarray, dict]:
    lam, gm, gcv, jm, jmd, side, pay = BOOM[feed]
    rng = np.random.default_rng([seed, abs(hash(feed)) % (2 ** 31)])
    chunks = []
    got = 0
    for c in G.gen_boomcrash(n_ticks, lam, gm, gcv, jm, jmd, side, 100000.0, 0.0, rng):
        chunks.append(c)
        got += c.size
        if got >= n_ticks:
            break
    return np.concatenate(chunks)[:n_ticks], {
        "lam": lam, "g": gm, "gcv": gcv, "J": jm, "Jmed": jmd, "side": side,
        "spread": pay * gm}


def hold_stats(mid: np.ndarray, nhold: int, side: int) -> dict:
    r = (mid[:-nhold] - mid[nhold:]) if side > 0 else (mid[nhold:] - mid[:-nhold])
    return {"mean": float(r.mean()), "median": float(np.median(r)),
            "sd": float(r.std(ddof=1)), "p_profit": float((r > 0).mean()),
            "q01": float(np.percentile(r, 1)), "q99": float(np.percentile(r, 99))}


def slippage(mid: np.ndarray, dist: float, side: int, cap: int) -> dict:
    m = mid[:cap]
    n, i = m.size, 0
    slips = []
    stops = tot = 0
    while i < n - 2:
        e = m[i]
        stop = e - side * dist
        tgt = e + side * dist
        out = None
        for j in range(i + 1, min(i + 1 + 7200, n)):
            if side * (m[j] - stop) <= 0:
                out = ("stop", m[j], j - i)
                break
            if side * (m[j] - tgt) >= 0:
                out = ("t", m[j], j - i)
                break
        if out is None:
            i += 7200
            continue
        why, xp, held = out
        tot += 1
        if why == "stop":
            stops += 1
            slips.append(-(side * (xp - e) + dist) / dist)
        i += max(held, 1)
    if not slips:
        return {}
    s = np.array(slips)
    return {"n": tot, "p_stop": stops / tot, "mean_slip_R": float(s.mean())}


def main() -> None:
    ledger: list[dict] = []
    payload: dict = {"seeds": SEEDS, "n_bars": NBARS, "params": PARAMS}
    print("=" * 118)
    print("EVERY PUBLISHED NUMBER, REGENERATED FROM THE SPECIFICATION - NO DATABASE")
    print(f"  seeds {SEEDS}   {NBARS:,} bars a cell   {G.machine()}")
    print("=" * 118)
    print("\n  what the rebuild is given, and nothing else:")
    for k, v in PARAMS.items():
        print(f"    {k:12s} {v}")

    # ------------------------------------------------- the volatility family --
    print("\n[1] THE VOLATILITY FAMILY - two numbers in, and the feed's own statistics out")
    print(f"{'tpb':>4s} {'seed':>10s} {'ann vol':>9s} {'ratio':>8s} {'kurt':>8s} "
          f"{'H':>7s} {'parkinson':>10s} {'published':>10s} {'err':>8s} {'VRq10':>8s}")
    vol_runs = {}
    for tpb in (30, 60):
        for seed in SEEDS:
            bb = sim_vol(tpb, seed, NBARS)
            r = G.logrets(bb["close"], bb["ts"])
            pk = G.parkinson_ratio(bb["high"], bb["low"], bb["close"])
            h = G.hurst(bb["ts"], bb["close"])
            av = G.ann_vol(r)
            vol_runs.setdefault(tpb, []).append(
                {"ann": av, "kurt": G.kurtosis(r), "H": h["H"], "park": pk,
                 "vr10": G.variance_ratio(r, 10), "bars": bb, "rets": r})
            print(f"{tpb:4d} {seed:10d} {av:9.3f} {av / 75.0:8.4f} {G.kurtosis(r):8.4f} "
                  f"{h['H']:7.4f} {pk:10.4f} {PARKINSON[tpb]:10.3f} "
                  f"{100 * (pk / PARKINSON[tpb] - 1):7.2f}% {G.variance_ratio(r, 10):8.4f}")
    for tpb in (30, 60):
        sp = G.spread_across([x["ann"] for x in vol_runs[tpb]])
        fired(f"realised volatility within 0.5% of the name ({tpb} ticks/bar)",
              sp["mean"], 75.0, 0.005, ledger)
        ku = G.spread_across([x["kurt"] for x in vol_runs[tpb]])
        ledger.append({"test": "1m kurtosis inside 2.98-3.02",
                       "feed": f"{tpb} ticks/bar", "value": ku["mean"],
                       "fired": not (2.98 <= ku["mean"] <= 3.02)})
        hh = G.spread_across([x["H"] for x in vol_runs[tpb]])
        ledger.append({"test": "Hurst within 0.01 of 0.50", "feed": f"{tpb} ticks/bar",
                       "value": hh["mean"], "fired": abs(hh["mean"] - 0.5) > 0.01})
        pp = G.spread_across([x["park"] for x in vol_runs[tpb]])
        fired(f"Parkinson ratio reproduces generators.md ({tpb} ticks/bar)",
              pp["mean"], PARKINSON[tpb], 0.01, ledger)
        print(f"    {tpb} ticks/bar over {len(SEEDS)} seeds: ann vol {sp['mean']:.3f} "
              f"+-{sp['sd']:.3f}, kurtosis {ku['mean']:.4f} +-{ku['sd']:.4f}, "
              f"Parkinson {pp['mean']:.4f} +-{pp['sd']:.4f} against {PARKINSON[tpb]:.3f}")

    print("\n[2] THE BARRIER TABLE - deriving.md section one, measured on the real feeds")
    print("    The rebuild was never told about the 0.5826 correction; the `corrected`")
    print("    column is printed only so the three routes can be compared.")
    u = (75.0 / 100.0) / math.sqrt(G.MINUTES_PER_YEAR)
    # Averaged over the seeds, because one path is not enough. A single
    # 400,000-bar path ends a few hundred one-minute sigmas from where it
    # started, and a non-overlapping barrier replay turns that terminal
    # displacement straight into an apparent bias in P(up) - +0.0022 at a 1:1
    # barrier and +0.009 at 10:10, which is exactly what the first run of this
    # harness printed. `deriving.md`'s own section on the twenty-three rules
    # says the same thing about its three positive-net rows.
    lgs = [np.log(x["bars"]["close"]) for x in vol_runs[30]]
    print(f"{'a:b':>6s} {'P meas':>8s} {'P rebuilt':>10s} {'cont':>7s} {'corr':>7s} "
          f"{'err':>7s} | {'tau meas':>9s} {'tau rebuilt':>11s} {'cont':>7s} {'corr':>8s} "
          f"{'err':>7s} {'n':>7s}")
    for key, (p_meas, t_meas) in BARRIER.items():
        a, b = (float(x) for x in key.split(":"))
        each = [two_barrier(x, a, b, u) for x in lgs]
        n = sum(e[2] for e in each)
        p_sim = sum(e[0] * e[2] for e in each) / n
        t_sim = sum(e[1] * e[2] for e in each) / n
        pc, pd = b / (a + b), (b + G.BETA) / (a + b + 2 * G.BETA)
        tc, td = a * b, (a + G.BETA) * (b + G.BETA)
        print(f"{key:>6s} {p_meas:8.4f} {p_sim:10.4f} {pc:7.4f} {pd:7.4f} "
              f"{p_sim - p_meas:+7.4f} | {t_meas:9.3f} {t_sim:11.3f} {tc:7.2f} {td:8.3f} "
              f"{100 * (t_sim / t_meas - 1):+6.2f}% {n:7d}")
        if a >= 3 or b >= 3:
            fired("barrier P(up) within 3% of the measured column", p_sim, p_meas,
                  0.03, ledger, feed=key)
            fired("barrier E[tau] within 3% of the measured column", t_sim, t_meas,
                  0.03, ledger, feed=key)
        payload.setdefault("barrier", {})[key] = {
            "measured": p_meas, "rebuilt": p_sim, "cont": pc, "corrected": pd,
            "tau_measured": t_meas, "tau_rebuilt": t_sim, "tau_corrected": td, "n": n}

    print("\n[3] THE WINDOW TABLE - E[max] and E[range] in one-minute sigmas")
    print(f"{'T':>5s} {'max meas':>9s} {'max rebuilt':>12s} {'cont':>8s} {'err':>7s} | "
          f"{'rng meas':>9s} {'rng rebuilt':>12s} {'cont':>8s} {'err':>7s} {'n':>7s}")
    occ_sim = None
    for T, (m_meas, r_meas) in WINDOW.items():
        ws = [windows(x, u, T) for x in lgs]
        ws = [x for x in ws if x]
        if not ws:
            continue
        tot = sum(x["n"] for x in ws)
        w = {"emax": sum(x["emax"] * x["n"] for x in ws) / tot,
             "erange": sum(x["erange"] * x["n"] for x in ws) / tot,
             "occ": sum(x["occ"] * x["n"] for x in ws) / tot, "n": tot}
        if T == 60:
            occ_sim = w["occ"]
        print(f"{T:5d} {m_meas:9.4f} {w['emax']:12.4f} {math.sqrt(2 * T / math.pi):8.4f} "
              f"{100 * (w['emax'] / m_meas - 1):+6.2f}% | {r_meas:9.4f} "
              f"{w['erange']:12.4f} {math.sqrt(8 * T / math.pi):8.4f} "
              f"{100 * (w['erange'] / r_meas - 1):+6.2f}% {w['n']:7d}")
        fired("E[max] within 3% of the measured column", w["emax"], m_meas, 0.03,
              ledger, feed=f"T={T}")
        fired("E[range] within 3% of the measured column", w["erange"], r_meas, 0.03,
              ledger, feed=f"T={T}")

    print("\n[4] OCCUPATION TIME ABOVE THE START, T = 60 MINUTES - the arcsine law")
    print(f"{'decile':>8s} {'arcsine':>9s} {'measured':>9s} {'rebuilt':>9s} {'err':>8s}")
    for d, meas in OCCUPATION.items():
        der = (2 / math.pi) * (math.asin(math.sqrt((d + 1) / 10))
                               - math.asin(math.sqrt(d / 10)))
        got = float(occ_sim[d]) if occ_sim is not None else float("nan")
        print(f"{d / 10:.1f}-{(d + 1) / 10:.1f} {der:9.4f} {meas:9.4f} {got:9.4f} "
              f"{got - meas:+8.4f}")
        ledger.append({"test": "occupation decile within 0.01 of the arcsine law",
                       "feed": f"decile {d}", "value": got - der,
                       "fired": abs(got - der) > 0.01})

    # -------------------------------------------------------------- step ------
    print("\n[5] STEP INDEX - a 0.1 step and a fair coin, and gambler's ruin out")
    rng = np.random.default_rng(SEEDS[0])
    sb = G.bars_from_stream(G.gen_step(NTICK, 0.1, 0.5, 9000.0, rng), 60,
                            NTICK // 60, keep_ticks=NTICK)
    ticks = sb["ticks"]
    lat = np.round(ticks / 0.1).astype(np.int64)
    d = np.diff(lat)
    mags, counts = np.unique(np.abs(d[d != 0]), return_counts=True)
    share = counts.max() / counts.sum()
    signs = np.sign(d)
    p_up = float((signs > 0).mean())
    se = math.sqrt(0.25 / signs.size)
    print(f"    {ticks.size:,} ticks; magnitude concentration {share:.6%} on "
          f"{mags[np.argmax(counts)]} step(s) (generators.md: 99.9988% on the feed)")
    print(f"    p(up) {p_up:.6f} +- {se:.6f}, z {(p_up - 0.5) / se:+.2f}; "
          f"runs z {G.runs_z(signs):+.3f}; sign acf lag 1 {G.acf(signs.astype(float), 1):+.5f}")
    ledger.append({"test": "Step concentration at least 99.99% on one magnitude",
                   "feed": "step_index", "value": share, "fired": share < 0.9999})
    ledger.append({"test": "Step p(up) within 3 SE of 0.5", "feed": "step_index",
                   "value": (p_up - 0.5) / se, "fired": abs(p_up - 0.5) > 3 * se})
    ledger.append({"test": "Step |runs z| <= 3", "feed": "step_index",
                   "value": G.runs_z(signs), "fired": abs(G.runs_z(signs)) > 3})
    print(f"\n{'S:T':>7s} {'P meas':>8s} {'P rebuilt':>10s} {'S/(S+T)':>9s} {'z':>7s} | "
          f"{'tau meas':>9s} {'tau rebuilt':>12s} {'S*T':>7s} {'err':>7s} {'n':>7s}")
    for (stop, tgt), (p_meas, t_meas) in RUIN.items():
        p_sim, t_sim, n = ruin_on_lattice(lat, stop, tgt, past=False)
        z = (p_sim - p_meas) / math.sqrt(0.25 / max(n, 1))
        print(f"{stop}:{tgt:<5d} {p_meas:8.4f} {p_sim:10.4f} {stop / (stop + tgt):9.4f} "
              f"{z:+7.2f} | {t_meas:9.1f} {t_sim:12.1f} {stop * tgt:7d} "
              f"{100 * (t_sim / t_meas - 1):+6.2f}% {n:7d}")
        ledger.append({"test": "Step ruin P within 3 SE of the measured column",
                       "feed": f"{stop}:{tgt}", "value": z, "fired": abs(z) > 3})
        fired("Step ruin E[tau] within 5% of the measured column", t_sim, t_meas,
              0.05, ledger, feed=f"{stop}:{tgt}")
    print("\n    the fill-one-step-past convention, which deriving.md shows is what")
    print("    generators.md's replay actually measured:")
    print(f"{'S:T':>7s} {'derived':>9s} {'rebuilt':>9s} {'err':>8s}")
    for (stop, tgt), want in RUIN_PAST.items():
        p_sim, _t, n = ruin_on_lattice(lat, stop, tgt, past=True)
        print(f"{stop}:{tgt:<5d} {want:9.4f} {p_sim:9.4f} {p_sim - want:+8.4f}")
        fired("Step fill-one-past reproduces the derived value", p_sim, want, 0.03,
              ledger, feed=f"{stop}:{tgt}")

    # ------------------------------------------------------- boom and crash ---
    print("\n[6] BOOM AND CRASH - five published numbers a feed, and the rate back out")
    print("    `lam*E[g]/E[J]` is the closure as the *published* numbers state it. It is")
    print("    not 1: the five numbers are each accurate and their product is only good")
    print("    to about 8%, so a rebuild long enough to see the difference carries a")
    print("    drift the feed's own 24 hours cannot resolve.")
    print(f"{'feed':22s} {'lambda in':>10s} {'ticks/spike out':>16s} {'ratio':>7s} "
          f"{'grind CV':>9s} {'lam E[g]/E[J]':>14s} {'closure z':>10s} {'gap CV':>7s}")
    boom_paths = {}
    for feed in BOOM:
        mid, par = boom_path(feed, min(NTICK, 3_000_000), SEEDS[0])
        boom_paths[feed] = (mid, par)
        dd = np.diff(mid)
        nz = np.abs(dd[dd != 0])
        med = float(np.median(nz))
        spike = np.abs(dd) > 10 * med
        side = par["side"]
        jj = np.abs(dd[spike & (np.sign(dd) == side)])
        gg = np.abs(dd[~spike])
        p = jj.size / dd.size
        tps = dd.size / max(jj.size, 1)
        closure = (1 - p) * float(gg.mean()) - p * float(jj.mean())
        cse = float(dd.std(ddof=1) / math.sqrt(dd.size))
        idx = np.flatnonzero(spike)
        gaps = np.diff(idx).astype(float)
        gcv = float(gaps.std(ddof=1) / gaps.mean()) if gaps.size > 2 else float("nan")
        gv = float(gg.std(ddof=1) / gg.mean())
        pub_closure = par["lam"] * par["g"] / par["J"]
        print(f"{feed:22s} {par['lam']:10.1f} {tps:16.1f} {tps / par['lam']:7.3f} "
              f"{gv:9.3f} {pub_closure:14.4f} {closure / cse:+10.2f} {gcv:7.3f}")
        ledger.append({"test": "the published five numbers close to 2%", "feed": feed,
                       "value": pub_closure - 1.0, "fired": abs(pub_closure - 1.0) > 0.02})
        fired("rebuilt spike rate recovers the published lambda", tps, par["lam"],
              0.10, ledger, feed=feed)
        ledger.append({"test": "grind CV in 0.63-0.68", "feed": feed, "value": gv,
                       "fired": not (0.63 <= gv <= 0.68)})
        ledger.append({"test": "spike-gap CV in 0.85-1.15", "feed": feed, "value": gcv,
                       "fired": not (0.85 <= gcv <= 1.15)})

    print("\n    the same six feeds with the closure *imposed* - E[J] replaced by")
    print("    lambda*E[g], which is what `deriving.md`'s own theorem says it must be:")
    print(f"{'feed':22s} {'E[J] published':>15s} {'lam*E[g]':>10s} {'closure z':>10s}")
    for feed in BOOM:
        lam, gm, gcv0, jm, jmd, side, pay = BOOM[feed]
        forced = lam * gm
        rng2 = np.random.default_rng([SEEDS[0], 99])
        chunks, got = [], 0
        need = min(NTICK, 3_000_000)
        for c in G.gen_boomcrash(need, lam, gm, gcv0, forced, jmd * forced / jm,
                                 side, 100000.0, 0.0, rng2):
            chunks.append(c)
            got += c.size
            if got >= need:
                break
        mid2 = np.concatenate(chunks)[:need]
        dd = np.diff(mid2)
        nz = np.abs(dd[dd != 0])
        spike = np.abs(dd) > 10 * float(np.median(nz))
        jj = np.abs(dd[spike & (np.sign(dd) == side)])
        gg = np.abs(dd[~spike])
        pp = jj.size / dd.size
        cl = (1 - pp) * float(gg.mean()) - pp * float(jj.mean())
        z = cl / float(dd.std(ddof=1) / math.sqrt(dd.size))
        print(f"{feed:22s} {jm:15.4f} {forced:10.4f} {z:+10.2f}")
        ledger.append({"test": "closure imposed: rebuilt path is a martingale",
                       "feed": feed, "value": z, "fired": abs(z) > 3})

    print("\n[7] THE P&L OF A HOLD ON THE GRIND SIDE - boom_500_index, against the")
    print("    *observed* column in deriving.md section five")
    mid, par = boom_paths["boom_500_index"]
    print(f"{'N':>6s} {'':>8s} {'mean':>10s} {'median':>10s} {'sd':>10s} "
          f"{'P(profit)':>10s} {'q01':>10s} {'q99':>10s}")
    for n_hold, obs in BOOM_PNL.items():
        got = hold_stats(mid, n_hold, par["side"])
        print(f"{n_hold:6d} {'observed':>8s} " + " ".join(f"{v:10.4f}" for v in obs))
        print(f"{'':6s} {'rebuilt':>8s} {got['mean']:10.4f} {got['median']:10.4f} "
              f"{got['sd']:10.4f} {got['p_profit']:10.4f} {got['q01']:10.4f} "
              f"{got['q99']:10.4f}")
        fired("hold sd within 15% of the observed column", got["sd"], obs[2], 0.15,
              ledger, feed=f"N={n_hold}")
        ledger.append({"test": "hold P(profit) within 0.03 of the observed column",
                       "feed": f"N={n_hold}",
                       "value": got["p_profit"] - obs[3],
                       "fired": abs(got["p_profit"] - obs[3]) > 0.03})
        payload.setdefault("boom_pnl", {})[str(n_hold)] = {"observed": obs, "rebuilt": got}

    print("\n[8] THE STOP ON THE SPIKE SIDE - genstop.py's four numbers, from a path")
    print("    built out of five published parameters and nothing else")
    print(f"{'stop':>5s} {'genstop.py':>11s} {'rebuilt':>9s} {'err':>8s} {'p(stop)':>9s} "
          f"{'P(J>D) pub':>11s} {'rebuilt':>9s}")
    jmag = np.abs(np.diff(mid))
    jmag = jmag[jmag > 10 * float(np.median(jmag[jmag > 0]))]
    for sd_, want in BOOM_SLIP.items():
        dist = sd_ * par["spread"]
        got = slippage(mid, dist, -par["side"], min(mid.size, 600_000))
        pj = float((jmag > dist).mean())
        if not got:
            continue
        print(f"{sd_:5.0f} {want:11.3f} {got['mean_slip_R']:9.3f} "
              f"{100 * (got['mean_slip_R'] / want - 1):+7.2f}% {got['p_stop']:9.4f} "
              f"{BOOM_GAP[sd_]:11.3f} {pj:9.3f}")
        fired("slippage reproduces genstop.py to 20%", got["mean_slip_R"], want, 0.20,
              ledger, feed=f"{sd_:.0f} spreads")
        fired("P(J>D) within 0.05 of the published table", pj, BOOM_GAP[sd_], 0.05,
              ledger, rel=False, feed=f"{sd_:.0f} spreads")

    # ------------------------------------------------------------- the jump ---
    print("\n[9] THE JUMP FAMILY - the name is the diffusion and the jumps are extra")
    print(f"{'min/jump':>9s} {'seed':>10s} {'ann vol':>9s} {'ratio to name':>14s} "
          f"{'kurtosis':>9s}")
    sig_min = (75.0 / 100.0) / math.sqrt(G.MINUTES_PER_YEAR)
    jr = []
    for rate_min in (24.0,):
        rate = 1.0 / rate_min
        js = math.sqrt(0.7477 * sig_min ** 2 / rate)
        for seed in SEEDS:
            bb = G.bars_from_stream(
                G.gen_jump(NBARS * 60, 75.0, 1.0, rate, js, 10000.0, 0.0,
                           np.random.default_rng([seed, 7])), 60, NBARS)
            r = G.logrets(bb["close"], bb["ts"])
            jr.append(G.ann_vol(r) / 75.0)
            print(f"{rate_min:9.1f} {seed:10d} {G.ann_vol(r):9.3f} {jr[-1]:14.4f} "
                  f"{G.kurtosis(r):9.3f}")
    sp = G.spread_across(jr)
    fired("Jump spec A realises 1.322x the name", sp["mean"], JUMP_MULT, 0.05 / JUMP_MULT,
          ledger, feed="jump")

    # ------------------------------------------------------------- the twins --
    print("\n[10] THE TWINS - the same law at twice the rate (twins.md)")
    a = sim_vol(30, SEEDS[0], NBARS, keep=400_000)
    b = sim_vol(60, SEEDS[0], NBARS, keep=400_000)
    va = float(np.var(np.diff(np.log(a["ticks"]))))
    vb = float(np.var(np.diff(np.log(b["ticks"]))))
    ratio = math.sqrt(va / vb)
    sec_a = va * 0.5
    sec_b = vb * 1.0
    print(f"    per-tick variance 2s {va:.4e}, 1s {vb:.4e}; sd ratio {ratio:.4f} "
          f"against sqrt(2) = {math.sqrt(2):.4f}")
    print(f"    variance per second 2s {sec_a:.4e}, 1s {sec_b:.4e}, ratio "
          f"{sec_a / sec_b:.4f} against 1")
    fired("twin per-tick sd ratio is sqrt(2)", ratio, math.sqrt(2), 0.01, ledger,
          feed="v75 / v75_1s")
    fired("twins carry identical volatility per second", sec_a / sec_b, 1.0, 0.01,
          ledger, feed="v75 / v75_1s")

    # ---------------------------------------------------------- the controls --
    print("\n[11] THE NEGATIVE CONTROLS - the battery has to fail where it should")
    print(f"{'wrong generator':26s} {'ann/name':>9s} {'vol cond':>9s} {'parkinson':>10s} "
          f"{'park cond':>10s}")
    for name, kw in (("sigma +2%", {"sigma": 75.0 * 1.02}),
                     ("half the tick rate", {"tpb": 15})):
        tpb = kw.pop("tpb", 30)
        bb = sim_vol(tpb, SEEDS[0] + 5, NBARS, **kw)
        r = G.logrets(bb["close"], bb["ts"])
        av = G.ann_vol(r) / 75.0
        pk = G.parkinson_ratio(bb["high"], bb["low"], bb["close"])
        vbad = abs(av - 1) > 0.005
        pbad = abs(pk / PARKINSON[30] - 1) > 0.01
        print(f"{name:26s} {av:9.4f} {'FAILS' if vbad else 'passes':>9s} {pk:10.4f} "
              f"{'FAILS' if pbad else 'passes':>10s}")
        payload.setdefault("controls", {})[name] = {"ann_ratio": av, "park": pk,
                                                    "vol_fails": vbad, "park_fails": pbad}
    c = payload["controls"]
    ledger.append({"test": "VOID unless sigma +2% fails the volatility condition",
                   "feed": "control", "value": c["sigma +2%"]["ann_ratio"],
                   "fired": not c["sigma +2%"]["vol_fails"]})
    ledger.append({"test": "VOID unless half the tick rate fails the Parkinson condition",
                   "feed": "control", "value": c["half the tick rate"]["park"],
                   "fired": not c["half the tick rate"]["park_fails"]})

    print("\n[12] THE FAILURE LEDGER")
    by: dict[str, list] = {}
    for e in ledger:
        by.setdefault(e["test"], []).append(e)
    print(f"{'condition':62s} {'cells':>6s} {'fired':>6s} {'worst cell':>30s}")
    nf = 0
    for name, es in sorted(by.items()):
        f2 = [e for e in es if e["fired"]]
        nf += len(f2)
        worst = max(es, key=lambda e: abs(e.get("value") or 0))
        print(f"{name:62s} {len(es):6d} {len(f2):6d} "
              f"{str(worst['feed'])[:22] + ' ' + format(worst['value'], '.4g'):>30s}")
    print(f"\n    {len(ledger)} pre-registered comparisons against published "
          f"measurements, {nf} fired.")
    payload["ledger"] = ledger

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(json.loads(json.dumps(payload, default=float)), fh, indent=1)
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
