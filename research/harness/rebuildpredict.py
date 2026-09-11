"""Can the next tick be predicted before it prints?

Not its distribution - that is settled - but the value. This is the last route by
which the generated 72% of this book could ever pay, and the prior is strongly
that it closes negative: Deriv is regulated, audits its generator, and a
cryptographic source is unpredictable from its outputs by construction. So the
job here is to write that null *well*, with the sample size named, and to be
explicit about which attacks the data had the power to run and which it did not.
"We found nothing" and "we could not have found anything" are different
sentences and this page separates them.

Five rungs, in increasing ambition.

1. **Structure in k-tuples.** The empirical spectral test from
   `rebuildjudge.py`, pushed to k = 2, 3, 4 with a wider integer search. A sound
   generator shows nothing; a linear congruential source puts its k-tuples on a
   small family of hyperplanes and the projection finds them. The controls are
   already calibrated - RANDU reads 2,616x where numpy's PCG64 reads 2.11.
2. **Mersenne Twister state recovery.** MT19937 is not cryptographically secure:
   624 consecutive 32-bit outputs determine the state exactly, by untempering.
   **This requires whole words.** Section one computes how many bits a tick
   actually carries, and if that is under 32 the attack is impossible rather
   than merely unsuccessful - which is the honest thing to report.
3. **Truncated LCG recovery.** The realistic case: each tick shows only the top
   few bits of whatever was drawn, because the quote is quantised. Truncated
   LCGs fall to lattice reduction on consecutive outputs, and the number of
   outputs needed is about `modulus bits / observed bits`. Rung 1 is the
   detector for exactly this hypothesis: an LCG small enough to be attackable
   leaves a lattice, so a clean rung 1 excludes the family rung 3 would attack.
4. **The joint stream, which is the angle specific to this venue.**
   `twins.md` found **all sixteen synthetics publish on one clock to within
   9ms**. If one stream feeds all sixteen then consecutive draws from it appear
   as *different feeds at the same tick index*, so a cross-feed tuple is a
   k-tuple of the underlying generator and the spectral test applies directly.
   Sixteen feeds is sixteen times the bits per unit time, and the cross-feed
   structure is itself the signature.
5. **A held-out forward prediction**, which is the only claim that counts. Fit on
   a prefix, predict the sign of the next tick on a held-out suffix, and report
   the AUC with its interval against the 0.5 null - both from a feed's own past
   and from all sixteen feeds at the same instant.

## What would count as failure, written before any number was looked at

1. **The null dies** if any k-tuple lattice ratio on a real feed exceeds **3x**
   what numpy's PCG64 produces on the same sample size, at k = 2, 3 or 4.
2. **The null dies** if the cross-feed test finds structure: a pairwise
   correlation of uniformised increments outside `+-4/sqrt(n)` on more pairs
   than chance allows, a two-dimensional grid chi-square below `0.001/pairs`
   after Bonferroni, or a cross-feed lattice ratio past the same 3x bar.
3. **The null dies** if the held-out classifier's AUC interval excludes 0.5 on
   the sign of the next tick, from either feature set.
4. **The run is void** if the positive control is missed: a feed synthesised from
   a truncated LCG, quantised exactly as the real feed is, must be caught by
   rung 1 and must be predicted above 0.5 by rung 5. A battery that cannot see a
   generator known to be broken says nothing about one that might be sound.
5. **The run is void** if an AUC lands on exactly 0.5000 or a lattice ratio on
   exactly its control's value - both are dead columns rather than nulls.
6. **Any rung the data cannot support is reported as untested**, with the
   arithmetic that says so, and is not counted as a pass.

## One thing this page will not do

If a rung bites, it is a finding about the product and about counterparty risk,
not a trading rule. Every set of terms permits voiding trades made against a
defective generator, so a position built on one is not bankable, and a venue
whose generator is predictable will discover it. The write-up is the deliverable
and the decision is the desk's.
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

OUT = os.environ.get("OUT", os.path.expanduser("~/till_infinity/logs/rebuildpredict.json"))
SEED = int(os.environ.get("SEED", "20260912"))
KLAGS = int(os.environ.get("KLAGS", "8"))
TREES = int(os.environ.get("TREES", "150"))
MAXROW = int(os.environ.get("MAXROW", "80000"))

SYNTH = list(V.NOMINAL) + list(V.JUMP_NOMINAL) + [
    "boom_300_index", "boom_500_index", "boom_1000_index",
    "crash_300_index", "crash_500_index", "crash_1000_index",
    "step_index", "range_break_100_index", "range_break_200_index",
]


def bits_per_tick(mid: np.ndarray, grid: float) -> dict:
    """How much of the underlying draw a single quote reveals.

    A discretised variate of standard deviation `s` lattice units carries about
    `log2(s * sqrt(2*pi*e))` bits. That number decides rungs 2 and 3 before
    either is run: untempering MT19937 needs whole 32-bit words, and a truncated
    LCG of an `n`-bit modulus needs roughly `n / bits` consecutive outputs.
    """
    d = np.diff(mid)
    if grid > 0:
        d = d / grid
    s = float(np.std(d))
    nz = float((d != 0).mean())
    bits = math.log2(s * math.sqrt(2 * math.pi * math.e)) if s > 0 else 0.0
    return {"sd_lattice": s, "bits": bits, "nonzero_frac": nz,
            "mt_words_needed": 624, "mt_ticks_needed": float("inf") if bits < 32
            else 624.0, "lcg48_ticks": 48.0 / bits if bits > 0 else float("inf")}


def trunc_lcg(n: int, bits_out: int, mod_bits: int = 48, a: int = 25214903917,
              c: int = 11, seed: int = 1) -> np.ndarray:
    """java.util.Random's LCG, truncated to `bits_out` observable bits.

    The positive control for rungs 1, 3 and 5: a generator that is known to be
    breakable, quantised the way a real quote is.
    """
    m = 1 << mod_bits
    x = seed
    out = np.empty(n, dtype=np.float64)
    shift = mod_bits - bits_out
    for i in range(n):
        x = (a * x + c) % m
        out[i] = (x >> shift) / (1 << bits_out)
    return out


def align(feeds: list[str], slot_ms: int) -> tuple[list[str], np.ndarray]:
    """Line the feeds up by publication slot.

    `twins.md` measured all sixteen synthetics publishing on one clock to within
    9ms, so flooring the timestamp to the slot is enough to put the same draw
    index beside itself across feeds. Only slots where every feed printed are
    kept, which is what makes a cross-feed tuple a tuple of one stream if there
    is one stream.
    """
    per = {}
    for f in feeds:
        t = G.real_ticks(f)
        if not t.get("n"):
            continue
        slot = t["ts"] // slot_ms
        uniq, first = np.unique(slot, return_index=True)
        per[f] = (uniq, t["mid"][first])
    if len(per) < 2:
        return [], np.empty((0, 0))
    common = None
    for f, (u, _m) in per.items():
        common = u if common is None else np.intersect1d(common, u, assume_unique=True)
    rows = []
    names = []
    for f, (u, m) in per.items():
        idx = np.searchsorted(u, common)
        rows.append(m[idx])
        names.append(f)
    return names, np.array(rows)


def sign_features(u: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Rows of `k` past increments, label = the sign of the next one."""
    d = np.diff(u)
    n = d.size - k
    if n < 500:
        return np.empty((0, 0)), np.empty(0), []
    x = np.lib.stride_tricks.sliding_window_view(d[:-1], k)[:n]
    y = (d[k:k + n] > 0).astype(float)
    return np.ascontiguousarray(x), y, [f"lag{i}" for i in range(k, 0, -1)]


def main() -> None:
    rng = np.random.default_rng(SEED)
    ledger: list[dict] = []
    payload: dict = {}
    print("=" * 120)
    print("CAN THE NEXT TICK BE PREDICTED BEFORE IT PRINTS?")
    print(f"  seed {SEED}   {G.machine()}")
    print("=" * 120)

    # ------------------------------------------------- how many bits a tick is --
    print("\n[1] HOW MUCH OF THE DRAW A TICK SHOWS - this decides which rungs are possible")
    print("    A discretised variate of sd `s` lattice units carries log2(s*sqrt(2*pi*e))")
    print("    bits. MT19937 untempering needs whole 32-bit words; a truncated LCG of an")
    print("    n-bit modulus needs about n/bits consecutive outputs.")
    print(f"{'feed':26s} {'grid':>10s} {'sd (lattice)':>13s} {'bits/tick':>10s} "
          f"{'ticks for a 48-bit LCG':>23s} {'MT possible':>12s}")
    bits = {}
    for feed in SYNTH:
        t = G.real_ticks(feed)
        if not t.get("n"):
            continue
        grid = G.quote_grid(t["mid"])
        b = bits_per_tick(t["mid"], grid)
        bits[feed] = b
        print(f"{feed:26s} {grid:10.6g} {b['sd_lattice']:13.2f} {b['bits']:10.2f} "
              f"{b['lcg48_ticks']:23.1f} {'no' if b['bits'] < 32 else 'yes':>12s}")
    payload["bits"] = bits
    best = max(bits.values(), key=lambda b: b["bits"]) if bits else {"bits": 0}
    print(f"\n    the richest feed carries {best['bits']:.2f} bits a tick, against the 32 a")
    print("    Mersenne Twister untempering needs. **Rung 2 is impossible on this data**")
    print("    and is reported as untested rather than as a pass.")
    print(f"    A 48-bit truncated LCG would need about {48 / max(best['bits'], 1e-9):.0f} "
          "consecutive ticks, which the sample has many times over - so rung 3's")
    print("    hypothesis is testable, and rung 1 is its detector.")
    ledger.append({"test": "rung 2 (MT untempering) is possible on this data",
                   "feed": "all", "value": best["bits"], "fired": False,
                   "note": "untested - needs 32 bits a tick"})

    # ------------------------------------------------------- rung 1: lattices --
    print("\n[2] RUNG 1 - k-TUPLE LATTICE STRUCTURE IN EACH FEED'S OWN INCREMENTS")
    print("    Ratio is the largest empty band in a projected k-tuple grid, in units of")
    print("    the ln(n)/n a genuine uniform stream gives. Controls first.")
    ctl_u = rng.random(200_000)
    ctl_randu = J.randu(200_000)
    ctl_lcg = trunc_lcg(200_000, 10)
    rows = []
    for name, u in (("CONTROL numpy PCG64", ctl_u),
                    ("CONTROL RANDU", ctl_randu),
                    ("CONTROL 48-bit LCG, top 10 bits", ctl_lcg)):
        rows.append({"name": name, "n": u.size,
                     "lat": {k: J.lattice_gap(u, k, 12 if k == 2 else 10 if k == 3 else 6)
                             for k in (2, 3, 4)}})
    for feed in SYNTH:
        t = G.real_ticks(feed)
        if not t.get("n"):
            continue
        inc = np.diff(t["mid"]).astype(float)
        u = J.to_uniform(inc, rng)
        rows.append({"name": feed, "n": u.size,
                     "lat": {k: J.lattice_gap(u, k, 12 if k == 2 else 10 if k == 3 else 6)
                             for k in (2, 3, 4)}})
    pcg = rows[0]
    print(f"{'stream':32s} {'n':>8s} {'k=2':>9s} {'k=3':>9s} {'k=4':>9s} {'verdict':>10s}")
    for r in rows:
        vals = [r["lat"][k].get("ratio", float("nan")) for k in (2, 3, 4)]
        base = [pcg["lat"][k].get("ratio", 1.0) for k in (2, 3, 4)]
        hit = any(v > 3 * b for v, b in zip(vals, base, strict=False) if v == v)
        print(f"{r['name']:32s} {r['n']:8d} " + " ".join(f"{v:9.2f}" for v in vals)
              + f" {'STRUCTURE' if hit else '-':>10s}")
        if not r["name"].startswith("CONTROL"):
            ledger.append({"test": "no k-tuple lattice past 3x the PCG64 control",
                           "feed": r["name"], "value": max(v for v in vals if v == v),
                           "fired": hit})
    randu_hit = any(rows[1]["lat"][k].get("ratio", 0) > 3 * pcg["lat"][k].get("ratio", 1)
                    for k in (2, 3, 4))
    lcg_hit = any(rows[2]["lat"][k].get("ratio", 0) > 3 * pcg["lat"][k].get("ratio", 1)
                  for k in (2, 3, 4))
    ledger.append({"test": "VOID unless RANDU is caught", "feed": "control",
                   "value": rows[1]["lat"][3].get("ratio", 0), "fired": not randu_hit})
    ledger.append({"test": "VOID unless the truncated LCG is caught", "feed": "control",
                   "value": rows[2]["lat"][2].get("ratio", 0), "fired": not lcg_hit})
    payload["lattice"] = json.loads(json.dumps(rows, default=float))

    # --------------------------------------------------- rung 4: joint stream --
    print("\n[3] RUNG 4 - THE JOINT STREAM, WHICH IS THE ANGLE SPECIFIC TO THIS VENUE")
    print("    twins.md: all sixteen synthetics publish on one clock to within 9ms. If one")
    print("    stream feeds them all, consecutive draws appear as different feeds at the")
    print("    same slot, and a cross-feed tuple is a k-tuple of that stream.")
    one_sec = [f for f in SYNTH if "_1s_" in f or f in
               ("step_index", "range_break_100_index", "range_break_200_index")
               or f.startswith("jump_")]
    names, mat = align(one_sec, 1000)
    if mat.size:
        inc = np.diff(mat, axis=1)
        n = inc.shape[1]
        uu = np.array([J.to_uniform(inc[i], rng) for i in range(inc.shape[0])])
        print(f"    {len(names)} feeds aligned on {n:,} common one-second slots")
        c = np.corrcoef(uu)
        iu = np.triu_indices(len(names), 1)
        band = 4.0 / math.sqrt(n)
        npast = int((np.abs(c[iu]) > band).sum())
        print(f"    pairwise correlation of uniformised increments at the same slot:")
        print(f"      largest |r| {np.abs(c[iu]).max():.5f}, mean {np.abs(c[iu]).mean():.5f}, "
              f"{npast} of {len(iu[0])} past +-4/sqrt(n) = {band:.5f} "
              f"(expected {0.0000633 * len(iu[0]):.2f})")
        worst_p, worst_pair = 1.0, None
        nb = max(2, int(len(iu[0])))
        for a, b in zip(*iu, strict=False):
            g = J.grid_chi2(np.column_stack([uu[a], uu[b]]).ravel(), 2, 8)
            if g.get("p", 1.0) < worst_p:
                worst_p, worst_pair = g["p"], (names[a], names[b])
        print(f"      worst 2-D grid chi-square over {nb} pairs: p = {worst_p:.3g} on "
              f"{worst_pair}, Bonferroni bar {0.001 / nb:.3g}")
        # the cross-feed tuple: feeds in order at one slot, as a k-tuple
        flat = uu.T.ravel()
        cross = {k: J.lattice_gap(flat, k, 12 if k == 2 else 10 if k == 3 else 6)
                 for k in (2, 3, 4)}
        pcgr = [pcg["lat"][k].get("ratio", 1.0) for k in (2, 3, 4)]
        cv = [cross[k].get("ratio", float("nan")) for k in (2, 3, 4)]
        print(f"      cross-feed tuples read as one stream, lattice ratio: "
              + " ".join(f"k={k}:{v:.2f}" for k, v in zip((2, 3, 4), cv, strict=False))
              + f"  (PCG64 {pcgr[0]:.2f}/{pcgr[1]:.2f}/{pcgr[2]:.2f})")
        hit = any(v > 3 * b for v, b in zip(cv, pcgr, strict=False) if v == v)
        ledger.append({"test": "no cross-feed correlation past the band",
                       "feed": "joint", "value": float(np.abs(c[iu]).max()),
                       "fired": npast > 3})
        ledger.append({"test": "no cross-feed 2-D dependence after Bonferroni",
                       "feed": "joint", "value": worst_p,
                       "fired": worst_p < 0.001 / nb})
        ledger.append({"test": "no lattice in the cross-feed tuple", "feed": "joint",
                       "value": max(v for v in cv if v == v), "fired": hit})
        payload["joint"] = {"feeds": names, "n": int(n),
                            "max_abs_corr": float(np.abs(c[iu]).max()),
                            "n_past_band": npast, "worst_chi2_p": worst_p,
                            "cross_lattice": json.loads(json.dumps(cross, default=float))}
    else:
        print("    could not align the feeds - skipped")

    # ---------------------------------------- rung 5: held-out forward prediction --
    print("\n[4] RUNG 5 - A HELD-OUT FORWARD PREDICTION, WHICH IS THE ONLY CLAIM THAT COUNTS")
    print("    Predict the sign of the next tick. Two feature sets: a feed's own last")
    print(f"    {KLAGS} increments, and all aligned feeds at the current slot.")
    print(f"{'target':28s} {'features':28s} {'n':>8s} {'AUC':>8s} {'95% CI':>17s} "
          f"{'verdict':>10s}")
    for feed in ("volatility_75_1s_index", "step_index", "range_break_100_index",
                 "boom_500_index"):
        t = G.real_ticks(feed)
        if not t.get("n"):
            continue
        x, y, nm = sign_features(t["mid"].astype(float), KLAGS)
        if not x.size:
            continue
        r = G.discriminate(x[y == 0][:MAXROW], x[y == 1][:MAXROW], nm, seed=SEED,
                           n_trees=TREES)
        ok = r["lo"] <= 0.5 <= r["hi"]
        print(f"{feed:28s} {'own last ' + str(KLAGS):28s} {r['n']:8d} {r['auc']:8.4f} "
              f"[{r['lo']:.4f},{r['hi']:.4f}] {'-' if ok else 'PREDICTS':>10s}")
        ledger.append({"test": "next-tick sign AUC interval contains 0.5", "feed": feed,
                       "value": r["auc"] - 0.5, "fired": not ok})
        payload.setdefault("predict", {})[feed] = {"own": r}
    if mat.size and mat.shape[0] > 2:
        tgt = 0
        d = np.diff(mat, axis=1)
        y = (d[tgt, 1:] > 0).astype(float)
        x = np.ascontiguousarray(d[:, :-1].T)
        nm = [f"f{i}" for i in range(x.shape[1])]
        r = G.discriminate(x[y == 0][:MAXROW], x[y == 1][:MAXROW], nm, seed=SEED,
                           n_trees=TREES)
        ok = r["lo"] <= 0.5 <= r["hi"]
        print(f"{names[tgt]:28s} {'all ' + str(len(names)) + ' feeds, same slot':28s} "
              f"{r['n']:8d} {r['auc']:8.4f} [{r['lo']:.4f},{r['hi']:.4f}] "
              f"{'-' if ok else 'PREDICTS':>10s}")
        ledger.append({"test": "next-tick sign AUC interval contains 0.5",
                       "feed": names[tgt] + " from all feeds",
                       "value": r["auc"] - 0.5, "fired": not ok})
        payload.setdefault("predict", {})["joint"] = r
    # the positive control: a feed whose source is a breakable LCG
    lu = trunc_lcg(300_000, 10, seed=7)
    lmid = np.cumsum(np.round((lu - 0.5) * 200)) + 10000.0
    x, y, nm = sign_features(lmid, KLAGS)
    r = G.discriminate(x[y == 0][:MAXROW], x[y == 1][:MAXROW], nm, seed=SEED,
                       n_trees=TREES)
    seen = not (r["lo"] <= 0.5 <= r["hi"])
    print(f"{'CONTROL truncated LCG':28s} {'own last ' + str(KLAGS):28s} {r['n']:8d} "
          f"{r['auc']:8.4f} [{r['lo']:.4f},{r['hi']:.4f}] "
          f"{'PREDICTS' if seen else 'missed':>10s}")
    ledger.append({"test": "VOID unless the LCG control is predicted", "feed": "control",
                   "value": r["auc"] - 0.5, "fired": not seen})
    payload.setdefault("predict", {})["control_lcg"] = r

    print("\n[5] THE FAILURE LEDGER")
    by: dict[str, list] = {}
    for e in ledger:
        by.setdefault(e["test"], []).append(e)
    print(f"{'condition':58s} {'cells':>6s} {'fired':>6s} {'worst cell':>32s}")
    nf = 0
    for name, es in sorted(by.items()):
        f2 = [e for e in es if e["fired"]]
        nf += len(f2)
        worst = max(es, key=lambda e: abs(e.get("value") or 0))
        print(f"{name:58s} {len(es):6d} {len(f2):6d} "
              f"{str(worst['feed'])[:24] + ' ' + format(worst['value'], '.4g'):>32s}")
    print(f"\n    {len(ledger)} pre-registered comparisons, {nf} fired.")
    payload["ledger"] = ledger

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(json.loads(json.dumps(payload, default=float)), fh, indent=1)
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
