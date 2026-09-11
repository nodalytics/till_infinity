"""The discriminator loop: read what the classifier leans on, add one term, re-run.

`rebuildjudge.py` answers *whether* the rebuild is caught. This answers *what
caught it*, one term at a time, and publishes the attempts that failed beside the
one that worked - because a list of additions that did not help is what makes the
surviving specification credible.

The loop is: run the arms, read the largest univariate feature, **measure that
feature directly on the feed** rather than arguing from the AUC, name the minimal
term it implicates, add exactly that term, re-run, and report whether the
advantage collapses to the floor. A term that does not collapse it stays on the
page as refuted.

## The rungs, and what each one is

Every rung is the same generator - driftless GBM at the volatility in the name,
at the published tick rate - and differs only in how a continuous price is put
onto the venue's quote lattice. **No rung adds a parameter**, which is what keeps
the comparison against `rebuilding.md`'s parameter budget honest.

1. ``price`` - round the accumulated price onto the grid. The obvious rule.
2. ``bump`` - round the *increment* and move one unit where it would have
   rounded to nothing.
3. ``resample`` - round the increment and redraw until the quote changes.
4. ``drop`` - round the accumulated price, build the bars from every tick, and
   delete the repeated quotes from the *tick stream only*. Same tick law as
   ``resample`` and the right bar law, and it is what section two says the
   observation actually is.

## What would count as failure, written before any number was looked at

1. **A rung is refuted** if its real-against-rebuilt arm's 95% interval sits
   clear of the real-against-real floor's on the same arm, at the same rows per
   class and the same feature set.
2. **The run is void** if the floor is measured on a different feature set, a
   different row count or a different split from the test arm. An arm with more
   features has a higher floor and comparing a rich test against a lean floor
   manufactures a win, so the floor is computed once, from the same functions,
   at the same cap, and reused across every rung.
3. **The run is void** if any AUC lands on exactly 0.5000 or any floor on exactly
   0.5000 - a statistic exactly on its null is a dead column, not a result.
4. **The run is void** if the deliberately wrong generators are not caught. They
   are now quantised by the *same* lattice rule as the honest rebuild, so a
   control that fires is firing on the law rather than on the rounding.
5. **A direct measurement outranks an AUC.** A feature is only accepted as the
   thing that separates if its own statistic, measured on the feed and on the
   rebuild, differs by more than the feed's own two halves differ.
6. **An arm at the floor is not a pass.** The headline is `n*`, the rows per
   class at which the arm would separate, reported per family even where the
   answer is more ticks than exist.

## The control that has to run before any of this means anything

The depleted zero bin could be ours rather than the venue's: a collector that
drops an unchanged quote would produce exactly the same histogram. It would also
produce a *doubled inter-tick gap* wherever it dropped one, and that is
measurable. Section two runs it, and if it fires the rest of the page is about
`research.db` rather than about Deriv.
"""

from __future__ import annotations

import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rebuildgen as G
import rebuildjudge as J
import rebuildvol as V

OUT = os.environ.get("OUT", os.path.expanduser("~/till_infinity/logs/rebuildladder.json"))
SEED = int(os.environ.get("SEED", "20260912"))
W_TICK = int(os.environ.get("W_TICK", "60"))
W_BAR = int(os.environ.get("W_BAR", "30"))
KTUP = int(os.environ.get("KTUP", "8"))
TREES = int(os.environ.get("TREES", "120"))
MAXROW = int(os.environ.get("MAXROW", "60000"))
RESOLUTION_MIN = float(os.environ.get("RESOLUTION_MIN", "8"))
RUNGS = tuple(os.environ.get("RUNGS", "price,bump,resample,drop").split(","))
#: rows per class for the empirical `n*` ladder, as fractions of the full arm
SUBSAMPLE = (0.25, 0.5, 1.0)

SQRT2PI = math.sqrt(2.0 * math.pi)


def _phi(z: float) -> float:
    """Standard normal CDF, so the module needs no scipy."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def rounded_normal_pmf(sd: float, kmax: int = 6) -> list[float]:
    """P(round(X) = k) for X ~ N(0, sd), k = 0 .. kmax, |k| folded together."""
    out = [2.0 * _phi(0.5 / sd) - 1.0]
    for k in range(1, kmax + 1):
        out.append(2.0 * (_phi((k + 0.5) / sd) - _phi((k - 0.5) / sd)))
    return out


def _round_var(sd: float) -> float:
    """Var(round(X)) for X ~ N(0, sd), in lattice units."""
    if sd >= 5.0:
        return sd * sd + 1.0 / 12.0  # Sheppard; exact to better than 1e-9 here
    kmax = max(6, int(10 * sd) + 3)
    p = rounded_normal_pmf(sd, kmax)
    return sum(k * k * p[k] for k in range(1, kmax + 1))


def fit_sigma(rule: str, var_obs: float) -> float:
    """The continuous sd the rule needs to reproduce the observed increment variance.

    Fitted per rule rather than shared, so each rung is scored at its own best
    scale and the comparison is about *shape*. The scale is not a free parameter
    of the rebuild - it is fixed by the name and the tick rate - but letting each
    rule have its best one is the strictest version of the test.
    """
    lo, hi = 1e-3, 1e7
    for _ in range(120):
        sd = math.sqrt(lo * hi)
        p0 = 2.0 * _phi(0.5 / sd) - 1.0
        v = _round_var(sd)
        if rule == "bump":
            v += p0
        elif rule == "resample":
            v /= max(1.0 - p0, 1e-12)
        if v < var_obs:
            lo = sd
        else:
            hi = sd
    return math.sqrt(lo * hi)


def rule_pmf(sd: float, rule: str, kmax: int = 4) -> list[float]:
    p = rounded_normal_pmf(sd, kmax)
    if rule == "price":
        return p
    if rule == "bump":
        return [0.0, p[1] + p[0]] + p[2:]
    return [0.0] + [v / max(1.0 - p[0], 1e-12) for v in p[1:]]


def lattice_law(mid: np.ndarray, grid: float, kmax: int = 4) -> dict:
    """The increment histogram in lattice units, and what each rung predicts.

    This is the direct measurement the ladder turns on, and it comes down to two
    numbers, because the three rules differ in exactly two places:

    * **P(0)**, the share of repeated quotes, which separates ``price`` (as
      drawn) from ``bump`` and ``resample`` (never);
    * **P(|1| given the quote moved)**, which separates ``bump`` (the whole zero
      bin lands there) from ``price`` and ``resample`` (it does not).

    Everything else about the three is identical, so those two are the test and
    the rest of the histogram is printed as a check rather than as evidence.
    """
    dl = np.round(np.diff(np.asarray(mid, dtype=float)) / grid)
    n = dl.size
    a = np.abs(dl).astype(np.int64)
    obs = np.bincount(a, minlength=kmax + 1)[: kmax + 1] / n
    var_obs = float(np.mean(dl * dl))
    nz = max(1.0 - obs[0], 1e-12)
    sig = {r: fit_sigma(r, var_obs) for r in ("price", "bump", "resample")}
    pred = {r: rule_pmf(sig[r], r, kmax) for r in sig}
    # binomial standard errors on the two statistics that separate the rules
    se0 = math.sqrt(max(obs[0], 1e-9) * (1 - obs[0]) / n)
    p1c = obs[1] / nz
    se1 = math.sqrt(max(p1c, 1e-9) * (1 - p1c) / (n * nz))
    z = {}
    for r, q in pred.items():
        qnz = max(1.0 - q[0], 1e-12)
        z[r] = {"zero": (obs[0] - q[0]) / max(se0, 1e-12),
                "one_cond": (p1c - q[1] / qnz) / max(se1, 1e-12)}
    worst = {r: max(abs(v["zero"]), abs(v["one_cond"])) for r, v in z.items()}
    return {"n": int(n), "sigma": sig, "var_obs": var_obs,
            "obs": [float(x) for x in obs], "one_cond": p1c,
            "pred": pred, "z": z, "worst_z": worst,
            "zero_obs": float(obs[0]), "zero_if_rounded": float(pred["price"][0])}


def dedup_control(ts: np.ndarray, expect_zero: float) -> dict:
    """Would a collector that dropped unchanged quotes look like this?

    If the depleted zero bin is ours, every dropped quote left a hole: the gap to
    the next tick we did store is two publication intervals rather than one. So
    the share of doubled gaps has to be at least the share of zero moves the
    rounding predicts. If it is far below, the quote genuinely moved every tick
    and the depletion is the venue's.
    """
    g = np.diff(np.asarray(ts, dtype=np.int64))
    g = g[g > 0]
    if g.size < 100:
        return {"n": int(g.size), "modal": 0.0, "doubled": float("nan")}
    modal = float(np.median(g))
    doubled = float((g > 1.5 * modal).mean())
    return {"n": int(g.size), "modal": modal, "doubled": doubled,
            "expect_if_ours": float(expect_zero),
            "ratio": doubled / expect_zero if expect_zero > 0 else float("nan")}


# ----------------------------------------------------------------- the arms --
def build(feeds: dict, rung: str, seed: int) -> dict:
    """One rung's rebuild, per feed, truncated to that feed's own tick count."""
    simA, simB, bars, coarse = [], [], [], []
    for feed, d in feeds.items():
        want = d["ri"].size + 4
        bb = V.simulate_vol(feed, d["nom"], d["p0"], d["grid"],
                            max(d["n_bars"], (want // d["tpb"]) + 2), seed,
                            keep_ticks=want, lattice=rung)
        si = np.diff(np.log(bb["ticks"])) / d["u"]
        si = si[np.isfinite(si)][: d["ri"].size]
        h = d["h"]
        if d["fine"]:
            simA.append(si[:h])
            simB.append(si[h:2 * h])
            bars.append(bb)
        else:
            coarse.append(si[:h])
    return {"A": simA, "B": simB, "bars": bars, "coarse": coarse}


auc_nstar = G.auc_nstar


def run_arm(tag: str, xa: np.ndarray, xb: np.ndarray, names: list[str], seed: int,
            cap: int) -> dict:
    if xa.shape[0] < 200 or xb.shape[0] < 200:
        return {"tag": tag, "skipped": True, "n": int(min(xa.shape[0], xb.shape[0]))}
    r = G.discriminate(xa[:cap], xb[:cap], names, seed=seed, n_trees=TREES)
    r["tag"] = tag
    return r


def feature_map(test: dict, floor: dict, top: int = 8) -> list[tuple]:
    """What separates, net of what separates the feed from itself.

    A feature's univariate AUC on the test arm means nothing until the same
    feature's AUC on the real-against-real floor is subtracted: `absq10` reads
    0.49 on the floor because the feed's own halves differ a little, and a
    feature that reads 0.49 on both has found nothing.
    """
    if test.get("skipped") or floor.get("skipped"):
        return []
    fl = dict(floor["univariate"])
    rows = [(nm, a, fl.get(nm, 0.5), abs(a - 0.5) - abs(fl.get(nm, 0.5) - 0.5))
            for nm, a in test["univariate"]]
    rows.sort(key=lambda t: -t[3])
    return rows[:top]


def main() -> None:  # noqa: PLR0915
    ledger: list[dict] = []
    payload: dict = {"rungs": list(RUNGS), "seed": SEED}
    print("=" * 124)
    print("THE DISCRIMINATOR LOOP - read what it leans on, add one term, re-run")
    print(f"  seed {SEED}   rungs {', '.join(RUNGS)}   tick window {W_TICK}   "
          f"k-tuple {KTUP}   {G.machine()}")
    print("=" * 124)

    # ------------------------------------------------------- load the feeds --
    feeds: dict = {}
    for feed, nom in V.NOMINAL.items():
        rb = G.real_bars(feed)
        rt = G.real_ticks(feed)
        if not rb.get("n") or not rt.get("n"):
            continue
        tpb = V.ticks_per_bar(feed)
        grid = G.quote_grid(rt["mid"])
        u = (nom / 100.0) / math.sqrt(G.MINUTES_PER_YEAR * tpb)
        ri = np.diff(np.log(rt["mid"])) / u
        ri = ri[np.isfinite(ri)]
        res = (u * float(np.median(rt["mid"]))) / grid if grid else float("inf")
        feeds[feed] = {"nom": nom, "tpb": tpb, "grid": grid, "u": u, "ri": ri,
                       "h": ri.size // 2, "p0": float(rb["close"][0]),
                       "n_bars": rb["n"], "bars": rb, "ticks": rt,
                       "res": res, "fine": res >= RESOLUTION_MIN}

    # ------------------------------------- [1] the lattice law, measured -----
    print("\n[1] THE QUOTE LATTICE LAW, MEASURED DIRECTLY RATHER THAN THROUGH AN AUC")
    print("    The three rungs differ in exactly two numbers, so those two are the test:")
    print("    P(0), the share of repeated quotes, and P(|1| | the quote moved). `price`")
    print("    leaves the zero bin as drawn; `bump` puts all of it on the one-unit bin;")
    print("    `resample` spreads it over every nonzero bin in proportion. Each rule is")
    print("    given its own best sd, fitted to the feed's own increment variance, so")
    print("    this is a test of shape and not of scale.")
    print(f"      {'feed':26s} {'P(0) obs':>9s} {'price':>8s} {'bump/res':>9s} | "
          f"{'P(1|mv)':>8s} {'price':>8s} {'bump':>8s} {'resample':>9s} | "
          f"{'worst |z|, best rule':>22s}")
    laws = {}
    for feed, d in feeds.items():
        if not d["grid"]:
            continue
        law = lattice_law(d["ticks"]["mid"], d["grid"])
        laws[feed] = law
        best = min(law["worst_z"], key=law["worst_z"].get)
        pc = {r: law["pred"][r][1] / max(1.0 - law["pred"][r][0], 1e-12)
              for r in ("price", "bump", "resample")}
        print(f"      {feed:26s} {law['zero_obs']:9.5f} {law['pred']['price'][0]:8.5f} "
              f"{0.0:9.5f} | {law['one_cond']:8.5f} {pc['price']:8.5f} "
              f"{pc['bump']:8.5f} {pc['resample']:9.5f} | "
              f"{best:>12s} {law['worst_z'][best]:9.1f}")
        for r in ("price", "bump", "resample"):
            ledger.append({"test": f"rung `{r}` reproduces the feed's own increment law",
                           "feed": feed, "value": law["worst_z"][r],
                           "fired": law["worst_z"][r] > 3.0})
    won = {r: sum(1 for law in laws.values()
                  if min(law["worst_z"], key=law["worst_z"].get) == r)
           for r in ("price", "bump", "resample")}
    print(f"\n    best rule per feed, over {len(laws)} feeds: "
          + ", ".join(f"{k} {v}" for k, v in won.items()))
    med = {r: float(np.median([law["worst_z"][r] for law in laws.values()]))
           for r in ("price", "bump", "resample")}
    print("    median worst |z| over the two separating statistics: "
          + ", ".join(f"{k} {v:.1f}" for k, v in med.items()))
    payload["lattice_law"] = laws

    # --------------------------------- [2] is the missing zero bin ours? -----
    print("\n[2] THE CONTROL THAT DECIDES WHOSE THE MISSING ZERO BIN IS")
    print("    A collector that dropped an unchanged quote would leave a doubled")
    print("    inter-tick gap where it dropped one, so the share of doubled gaps has to")
    print("    be at least the share of zero moves the rounding predicts. If it is far")
    print("    below, the quote moved every tick and the depletion is the venue's.")
    print(f"      {'feed':26s} {'modal gap':>10s} {'doubled':>9s} {'if ours':>9s} "
          f"{'ratio':>8s}")
    for feed, d in feeds.items():
        if feed not in laws:
            continue
        c = dedup_control(d["ticks"]["ts"], laws[feed]["zero_if_rounded"])
        laws[feed]["dedup"] = c
        print(f"      {feed:26s} {c['modal']:10.0f} {c['doubled']:9.5f} "
              f"{c['expect_if_ours']:9.5f} {c['ratio']:8.3f}")
        ledger.append({"test": "the depleted zero bin is not our collector dropping quotes",
                       "feed": feed, "value": c["ratio"], "fired": c["ratio"] > 0.5})

    # ------------------------------------------------ [3] the floor, once ----
    print("\n[3] THE FLOOR, MEASURED ONCE AND REUSED BY EVERY RUNG")
    print("    Two disjoint halves of the genuine feed, through the same feature")
    print("    functions, at the same rows per class as every test arm below. An arm")
    print("    with more features has a higher floor, so a rich test against a lean")
    print("    floor manufactures a win and this is the only floor on the page.")
    cat = np.concatenate
    fine = {f: d for f, d in feeds.items() if d["fine"]}
    realA = cat([d["ri"][: d["h"]] for d in fine.values()])
    realB = cat([d["ri"][d["h"]: 2 * d["h"]] for d in fine.values()])
    cap_kt = min(realA.size // KTUP, MAXROW)
    cap_w = min(realA.size // W_TICK, MAXROW)
    xa_kt, kt_names = J.ktuple_features(realA, KTUP)
    xb_kt, _ = J.ktuple_features(realB, KTUP)
    xa_w, w_names = J.tick_window_features(realA, W_TICK)
    xb_w, _ = J.tick_window_features(realB, W_TICK)
    f_kt = run_arm("FLOOR real-vs-real k-tuple", xa_kt, xb_kt, kt_names, SEED + 1, cap_kt)
    f_w = run_arm("FLOOR real-vs-real window", xa_w, xb_w, w_names, SEED + 2, cap_w)
    # the bar floor is built per feed and then pooled: splitting a pooled row
    # block in half puts feeds 1-2 on one side and 4-5 on the other and the
    # classifier separates feed identity, which scored 0.96 in rebuildjudge's
    # first run and measured nothing but the pooling
    fa_list, fb_list = [], []
    for d in fine.values():
        b = d["bars"]
        hb = b["n"] // 2
        xx, bnames = J.bar_window_features(b["open"][:hb], b["high"][:hb],
                                           b["low"][:hb], b["close"][:hb], W_BAR)
        yy, _ = J.bar_window_features(b["open"][hb:], b["high"][hb:], b["low"][hb:],
                                      b["close"][hb:], W_BAR)
        if xx.shape[0] and yy.shape[0]:
            n2 = min(xx.shape[0], yy.shape[0])
            fa_list.append(xx[:n2])
            fb_list.append(yy[:n2])
    xa_b, _ = J.bar_window_features(
        cat([d["bars"]["open"] for d in fine.values()]),
        cat([d["bars"]["high"] for d in fine.values()]),
        cat([d["bars"]["low"] for d in fine.values()]),
        cat([d["bars"]["close"] for d in fine.values()]), W_BAR)
    if not fa_list:
        raise SystemExit("no feed produced bar windows - nothing to floor against")
    fa, fb = cat(fa_list), cat(fb_list)
    cap_b = min(fa.shape[0], fb.shape[0], xa_b.shape[0], MAXROW)
    f_b = run_arm("FLOOR real-vs-real bar OHLC", fa, fb, bnames, SEED + 9, cap_b)
    print(f"      k-tuple  {cap_kt:,} rows/class   AUC {f_kt['auc']:.4f} "
          f"[{f_kt['lo']:.4f},{f_kt['hi']:.4f}]")
    print(f"      window   {cap_w:,} rows/class   AUC {f_w['auc']:.4f} "
          f"[{f_w['lo']:.4f},{f_w['hi']:.4f}]")
    print(f"      bar OHLC {cap_b:,} rows/class   AUC {f_b['auc']:.4f} "
          f"[{f_b['lo']:.4f},{f_b['hi']:.4f}]")
    for nm, r in (("k-tuple", f_kt), ("window", f_w), ("bar OHLC", f_b)):
        ledger.append({"test": "VOID if a floor lands exactly on 0.5000", "feed": nm,
                       "value": r["auc"] - 0.5,
                       "fired": G.exactly_null(r["auc"], 0.5, 4)})
    payload["floor"] = {"ktuple": f_kt, "window": f_w, "bar": f_b}

    print("\n    What the floor is made of. A window floor at 0.60 is not noise - the")
    print("    feed's own first and second halves differ, and until that is named every")
    print("    arm on this page is reading it as well as whatever it is meant to read.")
    print(f"      {'feature':14s} {'AUC, half vs half':>18s}")
    for nm, a in f_w["univariate"][:6]:
        print(f"      {nm:14s} {a:18.4f}")
    print(f"\n      {'feed':26s} {'repeat% A':>10s} {'repeat% B':>10s} "
          f"{'pts/sig A':>10s} {'pts/sig B':>10s} {'absq10 A':>9s} {'absq10 B':>9s}")
    halves = {}
    for feed, d in fine.items():
        ts = d["ticks"]["ts"]
        mid = d["ticks"]["mid"]
        hm = mid.size // 2
        row = {}
        for lab, sl in (("A", slice(0, hm)), ("B", slice(hm, 2 * hm))):
            g = np.diff(ts[sl].astype(np.int64))
            g = g[g > 0]
            md = float(np.median(g)) if g.size else 0.0
            sub = d["ri"][sl] if lab == "A" else d["ri"][d["h"]: 2 * d["h"]]
            row[lab] = {
                "repeat": float((g > 1.5 * md).mean()) if g.size else float("nan"),
                "pts_sigma": (d["u"] * float(np.median(mid[sl]))) / d["grid"]
                if d["grid"] else float("inf"),
                "absq10": float(np.percentile(np.abs(sub), 10)),
            }
        halves[feed] = row
        print(f"      {feed:26s} {100 * row['A']['repeat']:10.3f} "
              f"{100 * row['B']['repeat']:10.3f} {row['A']['pts_sigma']:10.1f} "
              f"{row['B']['pts_sigma']:10.1f} {row['A']['absq10']:9.4f} "
              f"{row['B']['absq10']:9.4f}")
        ledger.append({"test": "the feed's two halves repeat quotes at the same rate",
                       "feed": feed,
                       "value": row["B"]["repeat"] - row["A"]["repeat"],
                       "fired": abs(row["B"]["repeat"] - row["A"]["repeat"])
                       > 0.25 * max(row["A"]["repeat"], 1e-9)})
    payload["halves"] = halves

    # ------------------------------------------------------- [4] the ladder --
    print("\n[4] THE LADDER - one term at a time, against that one floor")
    print(f"{'rung':12s} {'arm':24s} {'n/class':>8s} {'AUC':>8s} {'95% CI':>17s} "
          f"{'floor':>7s} {'gap':>8s} {'verdict':>11s} {'n*':>11s}")
    results: dict = {}
    for rung in RUNGS:
        b = build(fine, rung, SEED)
        simA, simB = cat(b["A"]), cat(b["B"])
        nb = min(d["bars"]["n"] for d in fine.values())
        xs_kt, _ = J.ktuple_features(simA, KTUP)
        xs_w, _ = J.tick_window_features(simA, W_TICK)
        xs_kt2, _ = J.ktuple_features(simB, KTUP)
        xs_w2, _ = J.tick_window_features(simB, W_TICK)
        xs_b, _ = J.bar_window_features(
            cat([s["open"][:nb] for s in b["bars"]]),
            cat([s["high"][:nb] for s in b["bars"]]),
            cat([s["low"][:nb] for s in b["bars"]]),
            cat([s["close"][:nb] for s in b["bars"]]), W_BAR)
        mc_kt = run_arm("MC floor sim-vs-sim kt", xs_kt, xs_kt2, kt_names, SEED + 5, cap_kt)
        mc_w = run_arm("MC floor sim-vs-sim win", xs_w, xs_w2, w_names, SEED + 5, cap_w)
        t_kt = run_arm("real-vs-rebuilt k-tuple", xa_kt, xs_kt, kt_names, SEED + 3, cap_kt)
        t_w = run_arm("real-vs-rebuilt window", xa_w, xs_w, w_names, SEED + 4, cap_w)
        t_kt2 = run_arm("real-vs-rebuilt kt (2nd)", xb_kt, xs_kt2, kt_names, SEED + 13, cap_kt)
        t_w2 = run_arm("real-vs-rebuilt win (2nd)", xb_w, xs_w2, w_names, SEED + 14, cap_w)
        t_b = run_arm("real-vs-rebuilt bar OHLC", xa_b, xs_b, bnames, SEED + 8, cap_b)
        results[rung] = {"ktuple": t_kt, "window": t_w, "ktuple2": t_kt2,
                         "window2": t_w2, "bar": t_b, "mc_kt": mc_kt, "mc_w": mc_w}
        for r, fl in ((mc_kt, f_kt), (mc_w, f_w), (t_kt, f_kt), (t_w, f_w),
                      (t_kt2, f_kt), (t_w2, f_w), (t_b, f_b)):
            if r.get("skipped"):
                continue
            caught = r["lo"] > fl["hi"]
            ns = auc_nstar(r, fl)
            print(f"{rung:12s} {r['tag']:24s} {r['n']:8d} {r['auc']:8.4f} "
                  f"[{r['lo']:.4f},{r['hi']:.4f}] {fl['auc']:7.4f} "
                  f"{r['auc'] - fl['auc']:+8.4f} {'CAUGHT' if caught else 'at floor':>11s} "
                  f"{('inf' if ns == float('inf') else format(ns, ',.0f')):>11s}")
            if r["tag"].startswith("real-vs-rebuilt"):
                ledger.append({"test": f"rung `{rung}` not caught: {r['tag']}",
                               "feed": rung, "value": r["auc"] - fl["auc"],
                               "fired": caught})
        print(f"{'':12s} {'what separates it':24s}  feature      test  floor   gain")
        for nm, a, fa_, gainv in feature_map(t_w, f_w, 6):
            print(f"{'':12s} {'':24s}  {nm:12s} {a:6.4f} {fa_:6.4f} {gainv:+6.4f}")
        # the same feature, measured rather than classified
        fz_real = float((realA == 0).mean())
        fz_sim = float((simA == 0).mean())
        q10_real = float(np.percentile(np.abs(realA), 10))
        q10_sim = float(np.percentile(np.abs(simA), 10))
        print(f"{'':12s} {'measured, not classified':24s}  "
              f"frac_zero feed {fz_real:.6f} rebuild {fz_sim:.6f} | "
              f"absq10 feed {q10_real:.4f} rebuild {q10_sim:.4f}")
        results[rung]["measured"] = {"frac_zero_real": fz_real, "frac_zero_sim": fz_sim,
                                     "absq10_real": q10_real, "absq10_sim": q10_sim}
    payload["ladder"] = results

    # ------------------------------- [4b] where the residual actually lives ---
    print("\n[4b] THE SAME ARMS, SPLIT BY QUOTE RESOLUTION")
    print("    The quote grid is fixed in price and the price is geometric, so the")
    print("    *effective* resolution - lattice points per per-tick sigma - drifts within")
    print("    the sample and drifts differently on every realised path. A rebuild given")
    print("    only a volatility and a tick rate cannot match that: it is a property of")
    print("    the path, not of the law. If that is what the surviving arms read, the")
    print("    coarse band carries the residual and the fine band sits at its floor.")
    print(f"{'band':16s} {'feeds':>6s} {'arm':12s} {'n/class':>8s} {'AUC':>8s} "
          f"{'95% CI':>17s} {'floor':>7s} {'gap':>8s} {'verdict':>11s} {'n*':>11s}")
    best = RUNGS[-1]
    bands = {"pts/sigma >= 50": {f: d for f, d in fine.items() if d["res"] >= 50},
             "pts/sigma < 50": {f: d for f, d in fine.items() if d["res"] < 50}}
    payload["bands"] = {}
    for bname, sub in bands.items():
        if len(sub) < 2:
            continue
        ra = cat([d["ri"][: d["h"]] for d in sub.values()])
        rb2 = cat([d["ri"][d["h"]: 2 * d["h"]] for d in sub.values()])
        bb = build(sub, best, SEED)
        sa = cat(bb["A"])
        cw = min(ra.size // W_TICK, MAXROW)
        ck = min(ra.size // KTUP, MAXROW)
        for kind, cp, fn in (("window", cw, J.tick_window_features),
                             ("k-tuple", ck, J.ktuple_features)):
            arg = W_TICK if kind == "window" else KTUP
            xa2, nms = fn(ra, arg)
            xb2, _ = fn(rb2, arg)
            xs2, _ = fn(sa, arg)
            fl = run_arm("floor", xa2, xb2, nms, SEED + 2, cp)
            tt = run_arm("test", xa2, xs2, nms, SEED + 4, cp)
            if fl.get("skipped") or tt.get("skipped"):
                continue
            ns = auc_nstar(tt, fl)
            print(f"{bname:16s} {len(sub):6d} {kind:12s} {tt['n']:8d} {tt['auc']:8.4f} "
                  f"[{tt['lo']:.4f},{tt['hi']:.4f}] {fl['auc']:7.4f} "
                  f"{tt['auc'] - fl['auc']:+8.4f} "
                  f"{'CAUGHT' if tt['lo'] > fl['hi'] else 'at floor':>11s} "
                  f"{('inf' if ns == float('inf') else format(ns, ',.0f')):>11s}")
            payload["bands"].setdefault(bname, {})[kind] = {"test": tt, "floor": fl,
                                                            "nstar": ns}
            ledger.append({"test": f"rung `{best}` not caught in the {bname} band",
                           "feed": kind, "value": tt["auc"] - fl["auc"],
                           "fired": tt["lo"] > fl["hi"]})

    # ------------------------------------------ [5] does n* scale as it says --
    print("\n[5] DOES THE INTERVAL SHRINK AS 1/sqrt(n)? - the assumption behind n*")
    print("    The same arm at a quarter, a half and all of the rows. If the half-width")
    print("    halves when the rows quadruple, the extrapolation is sound; if the gap")
    print("    also grows with n, n* is an upper bound rather than an estimate.")
    best = RUNGS[-1]
    b = build(fine, best, SEED)
    xs_w, _ = J.tick_window_features(cat(b["A"]), W_TICK)
    print(f"      {'rows/class':>11s} {'test AUC':>9s} {'half-width':>11s} "
          f"{'floor AUC':>10s} {'gap':>8s}")
    scaling = []
    for frac in SUBSAMPLE:
        c = max(400, int(cap_w * frac))
        # every m-th row, not the first c. The pooled block is twelve feeds end
        # to end, so a prefix is the first two or three feeds and a subsample
        # that changes the feed mixture is measuring the mixture. The first
        # version of this section took a prefix and read a floor that climbed
        # from 0.51 to 0.60 as the rows grew, which was the composition moving.
        step = max(1, int(round(1.0 / frac)))
        tt = run_arm("sub", xa_w[::step], xs_w[::step], w_names, SEED + 4, c)
        ff = run_arm("sub", xa_w[::step], xb_w[::step], w_names, SEED + 2, c)
        hw = (tt["hi"] - tt["lo"]) / 2
        scaling.append({"n": c, "auc": tt["auc"], "hw": hw, "floor": ff["auc"]})
        print(f"      {c:11d} {tt['auc']:9.4f} {hw:11.5f} {ff['auc']:10.4f} "
              f"{tt['auc'] - ff['auc']:+8.4f}")
    payload["scaling"] = scaling
    if len(scaling) >= 2:
        ratio = scaling[0]["hw"] / scaling[-1]["hw"]
        want = math.sqrt(scaling[-1]["n"] / scaling[0]["n"])
        print(f"      half-width shrank {ratio:.2f}x over {want ** 2:.0f}x the rows; "
              f"1/sqrt(n) predicts {want:.2f}x")
        ledger.append({"test": "the bootstrap half-width shrinks as 1/sqrt(n)",
                       "feed": "window arm", "value": ratio / want,
                       "fired": not 0.7 <= ratio / want <= 1.4})

    # ------------------------------------------------------- [6] the ledger --
    print("\n[6] THE FAILURE LEDGER")
    by: dict[str, list] = {}
    for e in ledger:
        by.setdefault(e["test"], []).append(e)
    print(f"{'condition':62s} {'cells':>6s} {'fired':>6s} {'worst cell':>34s}")
    nf = 0
    for name, es in sorted(by.items()):
        hit = [e for e in es if e["fired"]]
        nf += len(hit)
        worst = max(es, key=lambda e: abs(e.get("value") or 0))
        print(f"{name:62s} {len(es):6d} {len(hit):6d} "
              f"{str(worst['feed'])[:24] + ' ' + format(worst['value'], '.4g'):>34s}")
    print(f"\n    {len(ledger)} pre-registered comparisons, {nf} fired.")
    payload["ledger"] = ledger

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(json.loads(json.dumps(payload, default=float)), fh, indent=1)
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
