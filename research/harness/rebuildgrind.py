"""Boom and Crash are the one family the rebuild does not reproduce. Why?

Every other family came back indistinguishable - the seven fine-resolution
Volatility feeds have `n*` infinite on both discriminator arms. Boom and Crash
separate at **59 to 960 ticks**, which is not a near miss. `rebuildjudge.py`'s
map says where: the largest univariate feature is `n_distinct`, the count of
distinct increment magnitudes in a sixty-tick window, and it fires in *both*
directions across the six feeds - AUC 0.601 on `boom_500_index` and 0.308 on
`crash_500_index`. A feature that separates in both directions is not one defect.

This harness does for the grind what `rebuildladder.py` did for the quote
lattice: measure the thing the discriminator leans on, ask what an *observation*
artefact would look like before blaming the venue, name the minimal term, and
re-run the arm.

## The two measurements this turns on

1. **What the grind's distribution actually is**, against the gamma that
   `deriving.md`'s `E[g]` and `CV[g]` imply. Two moments pin a gamma's shape at
   `1/CV^2`, and a gamma of shape above one has its mode away from zero.
2. **Which series the grind lives on.** `research.db` stores a bid and an ask and
   every rebuild here has compared the *mid*, which is their average and
   therefore moves on half the quote grid whenever the spread changes. If the
   odd half-grid moves are the spread rather than the price, the discriminator
   has been reading a second process the generator was never given.

## What would count as failure, written before any number was looked at

1. **The mid is the wrong series** if `P(odd half-grid move | the spread did not
   change)` is under 0.01 on every feed. The odd moves are then the spread, the
   grind lives on a grid twice as coarse as `quote_grid(mid)` reports, and the
   arm has to be re-run on the bid before anything is concluded about the
   generator.
2. **The published two moments do not pin the grind** if the gamma they imply
   misses the smallest occupied bin by more than a factor of two.
3. **The rung is refuted** if its real-against-rebuilt arm's interval sits clear
   of the real-against-real floor on the same series, the same rows per class and
   the same feature set. The floor is measured per series - a bid floor for a bid
   arm - because a floor from a different series is not a floor.
4. **The run is void** if the `pool` build, which is handed the feed's own
   empirical marginals, does not beat the `spec` build. If matching the marginal
   exactly does not help, the defect is not in the marginal and this harness is
   looking in the wrong place.
5. **The run is void** if a floor lands exactly on 0.5000.
6. **`n*` is the verdict, not the AUC.** Each arm reports the rows per class at
   which it would clear its own floor, and the headline is whether that moves off
   the 59 ticks `rebuildjudge.py` reports.
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
import rebuildspike as K

OUT = os.environ.get("OUT", os.path.expanduser("~/till_infinity/logs/rebuildgrind.json"))
SEED = int(os.environ.get("SEED", "20260912"))
W_TICK = int(os.environ.get("W_TICK", "60"))
KTUP = int(os.environ.get("KTUP", "8"))
TREES = int(os.environ.get("TREES", "120"))
MAXROW = int(os.environ.get("MAXROW", "60000"))
FEEDS = K.FEEDS


def series(feed: str) -> dict | None:
    """The feed as a mid and as a bid, each with its own grid and its own fit."""
    t = G.real_ticks(feed)
    b = G.real_bars(feed)
    if not t.get("n") or not b.get("n"):
        return None
    mid, sp = t["mid"], t["spread"]
    bid = mid - sp / 2.0
    out = {"feed": feed, "n_bars": b["n"], "spread": sp,
           "mid": {"px": mid, "grid": G.quote_grid(mid), "p0": float(mid[0])},
           "bid": {"px": bid, "grid": G.quote_grid(bid), "p0": float(bid[0])}}
    for k in ("mid", "bid"):
        out[k]["fit"] = K.detect(out[k]["px"])
        out[k]["fit"]["tag"] = f"{feed}/{k}"
    return out


def grind_hist(px: np.ndarray, grid: float) -> dict:
    d = G.lattice_increments(px, grid)
    nz = np.abs(d[d != 0])
    if not nz.size:
        return {}
    med = float(np.median(nz))
    spike = np.abs(d) > K.SPIKE_MULT * med
    gl = np.round(np.abs(d[~spike]) / grid).astype(np.int64)
    cnt = np.bincount(gl)
    n = gl.size
    mean = float(gl.mean())
    cv = float(gl.std(ddof=1) / mean) if mean else float("nan")
    return {"n": int(n), "distinct": int(np.unique(gl).size), "mean": mean, "cv": cv,
            "max": int(gl.max()), "odd": float((gl % 2 == 1).mean()),
            "share": [float(c) / n for c in cnt[: min(cnt.size, 40)]]}


def gamma_bins(mean: float, cv: float, upto: int = 10) -> list[float]:
    """What a gamma matched to the published mean and CV puts in the small bins."""
    from scipy.stats import gamma as _g
    k = 1.0 / cv ** 2
    th = mean / k
    return [float(_g.cdf(j + 0.5, k, scale=th) - _g.cdf(max(j - 0.5, 0.0), k, scale=th))
            for j in range(upto)]


def arm(tag: str, a: np.ndarray, b: np.ndarray, kind: str, seed: int,
        cap: int) -> dict:
    fn = J.ktuple_features if kind == "ktuple" else J.tick_window_features
    w = KTUP if kind == "ktuple" else W_TICK
    xa, names = fn(a, w)
    xb, _ = fn(b, w)
    if xa.shape[0] < 200 or xb.shape[0] < 200:
        return {"tag": tag, "skipped": True}
    r = G.discriminate(xa[:cap], xb[:cap], names, seed=seed, n_trees=TREES)
    r["tag"] = tag
    return r


def main() -> None:  # noqa: PLR0915
    ledger: list[dict] = []
    payload: dict = {"seed": SEED}
    print("=" * 120)
    print("BOOM AND CRASH - THE ONE FAMILY THE REBUILD DOES NOT REPRODUCE")
    print(f"  seed {SEED}   tick window {W_TICK}   k-tuple {KTUP}   {G.machine()}")
    print("=" * 120)

    data = {f: series(f) for f in FEEDS}
    data = {f: d for f, d in data.items() if d}

    # ------------------------------------- [1] which series the grind lives on --
    print("\n[1] WHICH SERIES THE GRIND LIVES ON - the control, run before the blame")
    print("    `research.db` stores a bid and an ask; every rebuild here has compared")
    print("    the mid, which is their average and moves on half the quote grid")
    print("    whenever the spread changes. If the odd half-grid moves are the spread")
    print("    then the discriminator has been reading a second process the generator")
    print("    was never given, and the grid it was handed is twice too fine.")
    print(f"      {'feed':20s} {'grid(mid)':>10s} {'grid(bid)':>10s} {'spread vals':>11s} "
          f"{'spread chg':>10s} {'odd |d|':>8s} {'P(odd|no chg)':>13s}")
    for f, d in data.items():
        sp = d["spread"]
        gl = np.round(np.abs(np.diff(d["mid"]["px"])) / d["mid"]["grid"]).astype(np.int64)
        chg = np.diff(sp) != 0
        odd = gl % 2 == 1
        p_same = float(odd[~chg].mean()) if (~chg).any() else float("nan")
        print(f"      {f:20s} {d['mid']['grid']:10.6g} {d['bid']['grid']:10.6g} "
              f"{np.unique(sp).size:11d} {100 * float(chg.mean()):9.1f}% "
              f"{100 * float(odd.mean()):7.1f}% {p_same:13.4f}")
        ledger.append({"test": "an odd half-grid move happens without a spread change",
                       "feed": f, "value": p_same, "fired": p_same > 0.01})
        payload.setdefault("series", {})[f] = {
            "grid_mid": d["mid"]["grid"], "grid_bid": d["bid"]["grid"],
            "spread_values": int(np.unique(sp).size),
            "spread_change": float(chg.mean()), "odd": float(odd.mean()),
            "p_odd_no_change": p_same}

    # ------------------------------------------- [2] what the grind actually is --
    print("\n[2] WHAT THE GRIND ACTUALLY IS, ON THE BID, AGAINST THE PUBLISHED GAMMA")
    print("    `deriving.md` publishes `E[g]` and `CV[g]`, which pin a gamma of shape")
    print("    `1/CV^2`. A gamma of shape above one has its mode away from zero.")
    print(f"      {'feed':20s} {'mean':>7s} {'cv':>6s} {'shape':>6s} {'distinct':>8s} "
          f"{'bin 1 feed':>11s} {'bin 1 gamma':>12s} {'ratio':>7s}")
    for f, d in data.items():
        h = grind_hist(d["bid"]["px"], d["bid"]["grid"])
        payload.setdefault("grind", {})[f] = h
        gb = gamma_bins(h["mean"], h["cv"])
        r = h["share"][1] / max(gb[1], 1e-12)
        print(f"      {f:20s} {h['mean']:7.2f} {h['cv']:6.3f} {1 / h['cv'] ** 2:6.2f} "
              f"{h['distinct']:8d} {100 * h['share'][1]:10.2f}% {100 * gb[1]:11.2f}% "
              f"{r:7.2f}")
        ledger.append({"test": "the published two moments pin the grind's smallest bin",
                       "feed": f, "value": r, "fired": r > 2.0 or r < 0.5})
    print("\n    the shape, feed against gamma, in units of the bid's own grid:")
    for f, d in data.items():
        h = payload["grind"][f]
        gb = gamma_bins(h["mean"], h["cv"], 10)
        print(f"      {f:20s} feed  " + " ".join(f"{100 * v:5.2f}" for v in h["share"][:10]))
        print(f"      {'':20s} gamma " + " ".join(f"{100 * v:5.2f}" for v in gb))

    # ------------------------------------------------------------- [3] the arms --
    print("\n[3] THE ARMS - the same discriminator, on the mid and on the bid")
    print("    Four builds a feed. `spec` is the five published numbers - a gamma for")
    print("    the grind and a lognormal for the jump; `pool` resamples the feed's own")
    print("    empirical marginals, so if matching the marginal exactly does not help,")
    print("    the defect is not in the marginal. Each arm carries its own floor on its")
    print("    own series, at the same rows per class and the same feature set.")
    print(f"{'feed':20s} {'series':6s} {'build':5s} {'arm':8s} {'n/class':>8s} {'AUC':>7s} "
          f"{'95% CI':>17s} {'floor':>7s} {'gap':>8s} {'verdict':>10s} {'n* ticks':>11s}")
    res: dict = {}
    for f, d in data.items():
        for sname in ("mid", "bid"):
            s = d[sname]
            fit = s["fit"]
            if not fit.get("n_ticks"):
                continue
            sc = fit["g_mean"]
            ri = G.lattice_increments(s["px"], s["grid"], sc)
            h = ri.size // 2
            caps = {"ktuple": min(h // KTUP, MAXROW), "tick": min(h // W_TICK, MAXROW)}
            floors = {k: arm(f"{f}/{sname} FLOOR {k}", ri[:h], ri[h: 2 * h], k,
                             SEED + 1, caps[k]) for k in ("ktuple", "tick")}
            for k, fl in floors.items():
                if not fl.get("skipped"):
                    ledger.append({"test": "VOID if a floor lands exactly on 0.5000",
                                   "feed": f"{f}/{sname}/{k}", "value": fl["auc"] - 0.5,
                                   "fired": G.exactly_null(fl["auc"], 0.5, 4)})
            for build, pool in (("spec", False), ("pool", True)):
                sim = K.build(fit, s["grid"], s["p0"],
                              max(d["n_bars"], ri.size // K.TPB + 10), SEED, pool)
                si = G.lattice_increments(sim["ticks"], s["grid"], sc)
                for k in ("ktuple", "tick"):
                    fl = floors[k]
                    r = arm(f"{f}/{sname}/{build} {k}", ri[:h], si[:h], k, SEED + 2,
                            caps[k])
                    if r.get("skipped") or fl.get("skipped"):
                        continue
                    ns = G.auc_nstar(r, fl)
                    per = KTUP if k == "ktuple" else W_TICK
                    caught = r["lo"] > fl["hi"]
                    print(f"{f:20s} {sname:6s} {build:5s} {k:8s} {r['n']:8d} "
                          f"{r['auc']:7.4f} [{r['lo']:.4f},{r['hi']:.4f}] "
                          f"{fl['auc']:7.4f} {r['auc'] - fl['auc']:+8.4f} "
                          f"{'CAUGHT' if caught else 'at floor':>10s} "
                          f"{('inf' if ns == float('inf') else format(ns * per, ',.0f')):>11s}")
                    res.setdefault(f, {})[f"{sname}/{build}/{k}"] = {
                        "auc": r["auc"], "floor": fl["auc"], "lo": r["lo"],
                        "hi": r["hi"], "nstar_ticks": ns * per, "n": r["n"],
                        "top": r["univariate"][:5]}
                    ledger.append({"test": f"{sname}/{build} rebuild not caught ({k})",
                                   "feed": f, "value": r["auc"] - fl["auc"],
                                   "fired": caught})
            if sname == "bid":
                best = res.get(f, {}).get("bid/pool/tick", {})
                if best.get("top"):
                    print(f"{'':20s} {'':6s} {'':5s} what separates the bid/pool arm: "
                          + ", ".join(f"{n2}={a2:.3f}" for n2, a2 in best["top"]))
    payload["arms"] = res

    # ------------------------------------------------- [4] did n* move at all? --
    print("\n[4] DID n* MOVE? - the number this harness exists to change")
    print(f"      {'feed':20s} {'mid/pool k-tuple':>18s} {'bid/pool k-tuple':>18s} "
          f"{'mid/pool window':>17s} {'bid/pool window':>17s}")
    for f in data:
        r = res.get(f, {})
        def g(key):
            v = r.get(key, {}).get("nstar_ticks")
            if v is None:
                return "-"
            return "inf" if v == float("inf") else format(v, ",.0f")
        print(f"      {f:20s} {g('mid/pool/ktuple'):>18s} {g('bid/pool/ktuple'):>18s} "
              f"{g('mid/pool/tick'):>17s} {g('bid/pool/tick'):>17s}")

    print("\n[5] THE FAILURE LEDGER")
    by: dict[str, list] = {}
    for e in ledger:
        by.setdefault(e["test"], []).append(e)
    print(f"{'condition':56s} {'cells':>6s} {'fired':>6s} {'worst cell':>30s}")
    nf = 0
    for name, es in sorted(by.items()):
        hit = [e for e in es if e["fired"]]
        nf += len(hit)
        worst = max(es, key=lambda e: abs(e.get("value") or 0))
        print(f"{name:56s} {len(es):6d} {len(hit):6d} "
              f"{str(worst['feed'])[:20] + ' ' + format(worst['value'], '.4g'):>30s}")
    print(f"\n    {len(ledger)} pre-registered comparisons, {nf} fired.")
    payload["ledger"] = ledger

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(json.loads(json.dumps(payload, default=float)), fh, indent=1)
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
