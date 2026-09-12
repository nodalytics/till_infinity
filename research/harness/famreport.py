"""Turn the two result files into the tables `research/families.md` is written from.

Kept separate from the harnesses so a table can be re-cut without re-running an
hour of compute, and so the page's numbers and the run's numbers are the same
numbers rather than two transcriptions of one log.
"""

from __future__ import annotations

import contextlib
import io
import json
import math
import os
from pathlib import Path

import numpy as np

from research.harness import seqlab

OUT = Path.home() / "till_infinity" / "data" / "families"
FAM_ORDER = ("drift_switch", "boom", "crash", "dex", "jump", "step", "range_break")


def load(name):
    p = OUT / name
    return json.loads(p.read_text()) if p.exists() else []


def g(d, *keys, default=float("nan")):
    for k in keys:
        if not isinstance(d, dict):
            return default
        d = d.get(k, {} if k != keys[-1] else default)
    return d if d not in ({}, None) else default


def f(v, d=4, w=0):
    try:
        if v is None or not np.isfinite(float(v)):
            return "n/a".rjust(w)
        return f"{float(v):{w}.{d}f}"
    except Exception:
        return str(v).rjust(w)


def main() -> None:
    rows = load("characterise.json")
    models = load("models.json")
    by = lambda k: [r for r in rows if r.get("kind") == k]  # noqa: E731

    # ---------------- 1. hazard ----------------
    haz = [r for r in by("hazard") if "obs" in r]
    print("=" * 128)
    print("ONE: THE SPIKE HAZARD  (spike = |tick bid move| > 10x median, genspike.py's detector)")
    print("=" * 128)
    print(f"{'symbol':24s} {'ticks':>8s} {'spikes':>7s} {'per':>7s} {'nom':>6s} {'rat':>5s} "
          f"{'mspr':>5s} | {'CV':>6s} {'z':>5s} | {'KS':>6s} {'z':>5s} | {'Fano':>6s} {'z':>5s} | "
          f"{'acf1':>6s} {'z':>5s} | {'slope':>6s} {'z':>5s} | {'min':>4s}")
    zmax = {}
    for r in sorted(haz, key=lambda r: (FAM_ORDER.index(r["family"]), r["per_spike"])):
        o, n = r["obs"], r["null"]
        print(f"{r['symbol']:24s} {r['n_ticks']:8,} {r['n_spikes']:7,} {r['per_spike']:7.1f} "
              f"{r['nominal']:6.0f} {r['rate_ratio']:5.2f} {r['mult_spread']:5.2f} | "
              f"{f(o['cv'],3,6)} {f(g(n,'cv','z'),1,5)} | {f(o['ks'],4,6)} {f(g(n,'ks','z'),1,5)} | "
              f"{f(o['fano'],3,6)} {f(g(n,'fano','z'),1,5)} | {f(o['acf1'],3,6)} {f(g(n,'acf1','z'),1,5)} | "
              f"{f(o.get('hz_slope'),3,6)} {f(g(n,'hz_slope','z'),1,5)} | {o['min_gap']:4.0f} "
              f"| s/g {r['spike_over_grind']:7.1f} up {r['spike_up_frac']:.3f} "
              f"grind_up {r['grind_up_frac']:.4f}")
        zs = [abs(g(n, k, "z")) for k in ("cv", "ks", "fano", "acf1", "hz_slope")]
        zs = [z for z in zs if np.isfinite(z)]
        zmax[r["symbol"]] = max(zs) if zs else float("nan")
    if zmax:
        v = np.array([z for z in zmax.values() if np.isfinite(z)])
        worst = max(zmax, key=lambda k: zmax[k] if np.isfinite(zmax[k]) else -1)
        print(f"\n  max |z| over {len(v)} symbols x 5 statistics = {len(v)*5} tests: "
              f"{v.max():.2f} on {worst}")
        print(f"  |z| > 2: {(v > 2).sum()} of {len(v)} symbols   "
              f"|z| > 3: {(v > 3).sum()}   mean max|z| {v.mean():.2f}")
        ntest = len(v) * 5
        crit = float(np.sqrt(2.0) * 1.0) * 0.0 + abs(np.sqrt(2) * 0.0) + (
            2.0 * math.log(2.0 * ntest / 0.05)) ** 0.5
        print(f"  Bonferroni two-sided |z| for 5% over {ntest} tests: {crit:.2f}")
        byf = {}
        for r in haz:
            byf.setdefault(r["family"], []).append(r)
        print("\n  by family:")
        for fam in FAM_ORDER:
            fr = byf.get(fam, [])
            if not fr:
                continue
            cv = np.array([r["obs"]["cv"] for r in fr])
            rr = np.array([r["rate_ratio"] for r in fr])
            nz = np.array([zmax[r["symbol"]] for r in fr])
            print(f"    {fam:12s} n={len(fr):2d}  CV {cv.mean():.3f} [{cv.min():.3f},{cv.max():.3f}]  "
                  f"rate/nominal {rr.mean():.3f} [{rr.min():.3f},{rr.max():.3f}]  max|z| {np.nanmax(nz):.2f}")

    # ---------------- 2. step ----------------
    st = [r for r in by("step") if "p_up" in r]
    print("\n" + "=" * 128)
    print("TWO: THE STEP LATTICE AND THE SKEW STEP NAME TEST")
    print("=" * 128)
    print(f"{'symbol':24s} {'moves':>9s} {'mags99':>6s} {'top':>6s} {'p_up':>9s} {'se':>7s} "
          f"{'halves':>17s} {'E[up]':>8s} {'E[dn]':>8s} {'ratio':>7s} {'clos_z':>7s} "
          f"{'acf1':>7s} {'out':>4s} {'runs_z':>7s}")
    for r in sorted(st, key=lambda r: r["symbol"]):
        h = r["p_up_halves"]
        print(f"{r['symbol']:24s} {r['n_moves']:9,} {r['mags_to_99']:6d} {r['top1_share']:6.3f} "
              f"{r['p_up']:9.6f} {r['se_p_up']:7.5f} [{h[0]:7.5f},{h[1]:7.5f}] "
              f"{r['e_up']:8.5f} {r['e_down']:8.5f} {r['size_ratio']:7.4f} {r['closure_z']:7.2f} "
              f"{r['acf1']:7.4f} {r['acf_out']:2d}/30 {r['runs_z']:7.2f}")
    print("\n  the name test - 'Skew Step Index k Up' pre-registered as p_up = 1/(1+k), up:down = k:1")
    print(f"  {'symbol':24s} {'k':>3s} {'p_up pred':>10s} {'p_up obs':>10s} {'z':>8s} "
          f"{'ratio pred':>11s} {'ratio obs':>10s}")
    for r in sorted(st, key=lambda r: r["symbol"]):
        nt = r.get("name_test") or {}
        if not nt.get("predicts"):
            continue
        print(f"  {r['symbol']:24s} {nt['k']:3.0f} {nt['p_up']:10.4f} {r['p_up']:10.6f} "
              f"{f(nt.get('p_up_z'),1,8)} {nt['size_ratio']:11.3f} {f(nt.get('ratio_obs'),4,10)}")
    print("\n  the magnitude ladder of every Step-family member - the name test that did hold")
    for r in sorted(st, key=lambda r: r["symbol"]):
        print(f"  {r['symbol']:24s} magnitudes covering 99%: {r['mags_to_99']}   "
              f"distinct: {r['n_distinct_mag']}   top: "
              + ", ".join(f"{a:g}@{c:.4f}" for a, _, c in r["top_mag"][:5]))

    # ---------------- 3. drift ----------------
    dr = [r for r in by("drift") if "vr" in r]
    print("\n" + "=" * 128)
    print("THREE: DRIFT SWITCH")
    print("=" * 128)
    for r in sorted(dr, key=lambda r: r["symbol"]):
        print(f"\n{r['symbol']}  {r['interval']}  {r['n_bars']:,} bars  acf1 {r['acf1_ret']:+.5f}")
        for tag, key in (("real", "vr"), ("shuffle", "vr_shuffle"), ("surrogate", "vr_surrogate")):
            print(f"   VR {tag:9s} " + "  ".join(f"k{k}:{v:.3f}" for k, v in sorted(
                ((int(a), b) for a, b in r[key].items()))))
        for k in (2, 3):
            h = r.get(f"hmm{k}")
            if not h:
                continue
            print(f"   hmm{k} real      persist {[round(v,2) for v in h['persist']]} "
                  f"dwell {[round(v,1) for v in h['dwell']]} sep {h['sep']:.2f} "
                  f"mu {[round(v,6) for v in h['mu']]} sigma {[round(v,6) for v in h['sigma']]}")
            for tag in ("shuffle", "surrogate"):
                q = r.get(f"hmm{k}_{tag}")
                if q:
                    print(f"   hmm{k} {tag:9s} persist {[round(v,2) for v in q['persist']]} "
                          f"dwell {[round(v,1) for v in q['dwell']]} sep {q['sep']:.2f}")
            rc = r.get(f"hmm{k}_recovery")
            if rc:
                print(f"   hmm{k} recovery  persist {[round(v,2) for v in rc['persist']]} "
                      f"corr_with_true_drift {rc['corr_with_truth']:.3f} "
                      f"auc_next_sign {rc['auc_next_sign']:.4f}")

    # ---------------- 4. range break ----------------
    rb = [r for r in by("range") if "ticks_per_break" in r]
    if rb:
        print("\n" + "=" * 128)
        print("FOUR: RANGE BREAK - replication of a settled number, not a re-measurement")
        print("=" * 128)
        for r in rb:
            o = r.get("obs", {})
            print(f"{r['symbol']:24s} {r['n_ticks']:,} ticks / {r['hours']:.0f}h  "
                  f"{r['n_breaks_10x']} breaks  {r['ticks_per_break']:.0f} ticks "
                  f"= {r['minutes_per_break']:.1f} min/break   CV {f(o.get('cv'),3)} "
                  f"Fano {f(o.get('fano'),3)} unit-move frac {r['unit_move_frac']:.4f}")

    # ---------------- 5. acf ----------------
    ac = [r for r in by("acf") if "acf1" in r]
    print("\n" + "=" * 128)
    print("FIVE: LAG-ONE RETURN AUTOCORRELATION, BY FAMILY AND TIMEFRAME  (t = acf1 * sqrt(n))")
    print("=" * 128)
    fams = list(FAM_ORDER) + ["control"]
    print(f"{'family':14s} " + " ".join(f"{tf:>14s}" for tf in seqlab.GRID))
    for fam in fams:
        cells = []
        for tf in seqlab.GRID:
            v = [r for r in ac if r["family"] == fam and r["interval"] == tf]
            if not v:
                cells.append("            --")
                continue
            a = np.array([r["acf1"] for r in v])
            t = np.array([r["t"] for r in v])
            j = int(np.argmax(np.abs(t)))
            cells.append(f"{a.mean():+.4f}/{t[j]:+5.1f}")
        print(f"{fam:14s} " + " ".join(f"{c:>14s}" for c in cells))
    print("\n  mean acf1 over the family's symbols / the largest |t| in the cell.")
    print("  controls, per symbol (these decide whether the synthetic numbers mean anything):")
    for s in ("Step Index", "Volatility 75 Index", "Volatility 100 Index", "XAUUSD", "EURUSD", "BTCUSD"):
        v = sorted([r for r in ac if r["symbol"] == s], key=lambda r: seqlab.GRID.index(r["interval"]))
        if v:
            print(f"    {s:22s} " + "  ".join(f"{r['interval']}:{r['acf1']:+.4f}(t{r['t']:+.1f})" for r in v))

    print("\n  every symbol with |t| > 6 at any timeframe, and what it costs to trade:")
    print(f"  {'symbol':24s} {'tf':>4s} {'n':>7s} {'acf1':>8s} {'t':>7s} {'halves':>18s} "
          f"{'shuf':>8s} {'surr':>8s} {'LB p':>10s} | {'hit':>6s} {'gross':>10s} {'turn':>6s} "
          f"{'cost':>9s} {'net':>10s} {'be/cost':>8s} {'thr be/c':>9s}")
    big = sorted([r for r in ac if abs(r.get("t", 0)) > 6],
                 key=lambda r: -abs(r["t"]))
    for r in big[:40]:
        a = r.get("ar1", {})
        th = a.get("thr", {})
        h = r["acf1_halves"]
        print(f"  {r['symbol']:24s} {r['interval']:>4s} {r['n']:7,} {r['acf1']:+8.4f} {r['t']:+7.1f} "
              f"[{h[0]:+7.4f},{h[1]:+7.4f}] {r['acf1_shuffle']:+8.4f} {r['acf1_surrogate']:+8.4f} "
              f"{r['lb_p']:10.2e} | {f(a.get('hit'),4,6)} {f(a.get('gross'),2,10) if not np.isfinite(a.get('gross',np.nan)) else '%+.3e'%a['gross']} "
              f"{f(a.get('turnover'),3,6)} {'%.3e'%r['rel_spread'] if np.isfinite(r['rel_spread']) else 'n/a':>9s} "
              f"{'%+.3e'%a['net'] if 'net' in a else 'n/a':>10s} {f(a.get('breakeven_over_cost'),3,8)} "
              f"{f(th.get('breakeven_over_cost'),3,9)}")

    # the full cost sweep for the one family it matters on
    print("\n  the cost sweep across the whole grid, for the family that has an autocorrelation:")
    print(f"  {'symbol':24s} {'tf':>4s} {'n':>7s} {'acf1':>8s} {'t':>7s} {'sigma_bar':>10s} "
          f"{'cost':>10s} {'cost/sig':>9s} {'hit':>6s} {'gross':>11s} {'turn':>6s} {'net':>11s} "
          f"{'be/cost':>8s} {'thr be/c':>9s} {'thr net':>11s}")
    for r in sorted([r for r in ac if r["family"] == "drift_switch"],
                    key=lambda r: (r["symbol"], seqlab.GRID.index(r["interval"]))):
        a = r.get("ar1", {})
        th = a.get("thr", {})
        cs = r["rel_spread"] / r["sigma_bar"] if r.get("sigma_bar") else float("nan")
        print(f"  {r['symbol']:24s} {r['interval']:>4s} {r['n']:7,} {r['acf1']:+8.4f} {r['t']:+7.1f} "
              f"{r['sigma_bar']:10.3e} {r['rel_spread']:10.3e} {f(cs,3,9)} {f(a.get('hit'),4,6)} "
              f"{'%+.4e'%a['gross'] if 'gross' in a else 'n/a':>11s} {f(a.get('turnover'),3,6)} "
              f"{'%+.4e'%a['net'] if 'net' in a else 'n/a':>11s} {f(a.get('breakeven_over_cost'),3,8)} "
              f"{f(th.get('breakeven_over_cost'),3,9)} "
              f"{'%+.4e'%th['net'] if 'net' in th else 'n/a':>11s}")

    # ---------------- 6. tick vs bar ----------------
    tk = [r for r in by("tickacf") if "acf1_bid" in r]
    if tk:
        print("\n" + "=" * 128)
        print("SIX: THE SAME STATISTIC AT TICK RESOLUTION - the artefact discriminator")
        print("=" * 128)
        print(f"{'family':14s} {'n':>3s} {'tick acf1 (bid)':>18s} {'se':>8s} {'max |t|':>8s}")
        byf = {}
        for r in tk:
            byf.setdefault(r["family"], []).append(r)
        for fam in FAM_ORDER:
            v = byf.get(fam, [])
            if not v:
                continue
            a = np.array([r["acf1_bid"] for r in v])
            t = np.array([r["acf1_bid"] / r["se_bid"] for r in v])
            print(f"{fam:14s} {len(v):3d} {a.mean():+18.5f} {np.mean([r['se_bid'] for r in v]):8.5f} "
                  f"{np.abs(t).max():8.2f}")
        print("\n  per drift-switch symbol, lags one to five on the bid:")
        for r in sorted([r for r in tk if r["family"] == "drift_switch"], key=lambda r: r["symbol"]):
            print(f"    {r['symbol']:24s} n={r['n_ticks']:,} se={r['se_bid']:.5f} "
                  f"bid {[round(v,5) for v in r['acf_bid']]}")

    # ---------------- 7. models ----------------
    if models:
        sp = [r for r in models if r.get("kind") == "spike" and "real" in r and "logistic" in r["real"]]
        print("\n" + "=" * 128)
        print("SEVEN: THE MODEL ARM")
        print("=" * 128)
        print("spike_next on tick bars.  Analytic floor is exactly 0.500 if the hazard is memoryless.")
        print(f"{'symbol':24s} {'per':>5s} {'rows':>6s} {'base':>6s} {'logit':>7s} {'null':>15s} {'z':>6s} "
              f"{'pmaxk':>6s} | {'nohaz':>7s} {'gru':>7s} {'gru null':>15s} | {'shuf':>7s} {'surr':>7s}")
        for r in sorted(sp, key=lambda r: (FAM_ORDER.index(r["family"]), r["per_spike"])):
            rl, nl = r["real"], r.get("null", {})
            nn, ng = nl.get("logistic", {}), nl.get("gru", {})
            print(f"{r['symbol']:24s} {r['ticks_per_bar']:5d} {rl['rows']:6,} {rl['base_rate']:6.3f} "
                  f"{f(rl['logistic'],4,7)} {f(nn.get('mean'),4,6)}+-{f(nn.get('sd'),4,6)} "
                  f"{f(nn.get('z'),2,6)} {f(nn.get('p_max_of_k'),3,6)} | {f(rl['logistic_nohaz'],4,7)} "
                  f"{f(rl['gru'],4,7)} {f(ng.get('mean'),4,6)}+-{f(ng.get('sd'),4,6)} | "
                  f"{f(g(r,'shuffle','logistic'),4,7)} {f(g(r,'surrogate','logistic'),4,7)}")
        allz = [g(r, "null", "logistic", "z") for r in sp]
        allz = [z for z in allz if np.isfinite(z)]
        if allz:
            print(f"\n  max |z| over {len(allz)} spike cells: {max(abs(np.array(allz))):.2f}   "
                  f"|z|>2: {(np.abs(allz) > 2).sum()}")
        print("\n  the census - expected spikes per bar on the wall clock. "
              "Outside [0.05, 1.0] the target is destroyed.")
        print(f"  {'symbol':24s} " + " ".join(f"{tf:>8s}" for tf in seqlab.GRID))
        for r in sorted(sp, key=lambda r: (FAM_ORDER.index(r["family"]), r["per_spike"]))[:12]:
            c = r["census"]
            print(f"  {r['symbol']:24s} " + " ".join(f"{c[tf]:8.2f}" for tf in seqlab.GRID))

        ba = [r for r in models if r.get("kind") == "bar" and "dir" in r]
        print("\ndirection and volatility on wall-clock bars, pooled by family")
        print(f"{'family':14s} {'tf':>4s} {'n':>3s} {'base':>6s} {'logit':>7s} {'shuf':>7s} {'surr':>7s} "
              f"{'mom':>7s} {'hmm':>7s} | {'naive':>7s} {'mean':>7s} {'gap':>8s} {'har':>7s} {'ridge':>7s}")
        for fam in FAM_ORDER:
            for tf in ("15m", "1h", "4h", "1d"):
                v = [r for r in ba if r["family"] == fam and r["interval"] == tf]
                if not v:
                    continue
                def m(*k):
                    q = [g(r, *k) for r in v]
                    q = [x for x in q if np.isfinite(x)]
                    return float(np.mean(q)) if q else float("nan")
                print(f"{fam:14s} {tf:>4s} {len(v):3d} {f(m('dir','base_rate'),4,6)} "
                      f"{f(m('dir','logistic'),4,7)} {f(m('dir','shuffle'),4,7)} {f(m('dir','surrogate'),4,7)} "
                      f"{f(m('dir','momentum'),4,7)} {f(m('dir','hmm'),4,7)} | "
                      f"{f(m('vol','naive_srel'),4,7)} {f(m('vol','mean_srel'),4,7)} "
                      f"{f(m('vol','naive_minus_mean'),4,8)} {f(m('vol','har_srel'),4,7)} "
                      f"{f(m('vol','ridge_srel'),4,7)}")

        dm = [r for r in models if r.get("kind") == "drift" and "real" in r]
        if dm:
            print("\ndrift switch, full model arm - every control on identical rows")
            print(f"{'symbol':24s} {'tf':>4s} {'rows':>7s} " +
                  " ".join(f"{a:>26s}" for a in ("real", "shuffle", "surrogate", "null_switch", "null_volonly")))
            print(f"{'':24s} {'':>4s} {'':>7s} " +
                  " ".join(f"{'hmm/gru/mom':>26s}" for _ in range(5)))
            for r in sorted(dm, key=lambda r: (r["symbol"], r["interval"])):
                cells = []
                for tag in ("real", "shuffle", "surrogate", "null_switch", "null_volonly"):
                    a = r.get(tag, {})
                    cells.append(f"{f(a.get('hmm'),4)}/{f(a.get('gru'),4)}/{f(a.get('mom22'),4)}")
                print(f"{r['symbol']:24s} {r['interval']:>4s} {r['rows']:7,} " +
                      " ".join(f"{c:>26s}" for c in cells))


if __name__ == "__main__":
    # `lab.sh log` tails sixty lines, and these tables are two hundred. `PART=n`
    # prints the n-th 55-line slice so a full report can be read through that
    # window without a second transport.
    part = int(os.environ.get("PART", "0"))
    if not part:
        main()
    else:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            main()
        lines = buf.getvalue().splitlines()
        chunk = 55
        print(f"[part {part} of {(len(lines) + chunk - 1) // chunk}, {len(lines)} lines]")
        print("\n".join(lines[(part - 1) * chunk : part * chunk]))
