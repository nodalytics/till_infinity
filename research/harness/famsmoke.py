"""Smoke: every code path once, on cached ticks, printed terse enough to read in one log."""
import time
import numpy as np
from research.harness import seqlab, seqfamilies as sf, fammodels as fm

def ready(want, floor=50_000):
    out = []
    for s in want:
        p = seqlab.TICK_CACHE / f"{seqlab._slug(s, 'tick')}.npz"
        if p.exists() and len(np.load(p)["time"]) > floor:
            out.append(s)
    return out

def f(v, d=4):
    try:
        return "  n/a" if v is None or not np.isfinite(v) else f"{v:.{d}f}"
    except Exception:
        return str(v)

boom = ready(seqlab.SYNTHETIC["boom"] + seqlab.SYNTHETIC["crash"])
step = ready(seqlab.SYNTHETIC["step"])
print(f"cached ticks: boom/crash {len(boom)} step {len(step)}", flush=True)

if boom:
    t0 = time.time(); r = sf.hazard_arm(boom[0], replicates=25)
    o, n = r["obs"], r["null"]
    print(f"\nHAZARD {boom[0]} {time.time()-t0:.0f}s  ticks {r['n_ticks']:,} spikes {r['n_spikes']} "
          f"per {r['per_spike']:.1f} nominal {r['nominal']:.0f} mult_spread {f(r['mult_spread'],3)}")
    for k in ("cv","ks","fano","acf1","hz_ratio","hz_slope","min_gap"):
        print(f"   {k:9s} obs {f(o[k],4)}  null {f(n[k]['mean'],4)}+-{f(n[k]['sd'],4)}  "
              f"z {f(n[k]['z'],2)}  p {f(n[k]['p'],2)}")
    print("   hz", [round(v,6) for v in r["hz"]], "edges", r["hz_edges"], flush=True)

if step:
    for s in step[:3]:
        t0 = time.time(); r = sf.step_arm(s, replicates=8)
        if "p_up" not in r: print("STEP", s, r.get("skip") or r.get("error")); continue
        nt = r["name_test"]
        print(f"\nSTEP {s} {time.time()-t0:.0f}s n={r['n_moves']:,} zero {f(r['frac_zero'],5)} "
              f"mags {r['n_distinct_mag']} (99%: {r['mags_to_99']}) top {f(r['top1_share'],4)}")
        print(f"   p_up {f(r['p_up'],6)}+-{f(r['se_p_up'],6)} halves {[round(v,5) for v in r['p_up_halves']]} "
              f"z_fair {f(r['z_vs_fair'],1)}  E[up] {f(r['e_up'],5)} E[dn] {f(r['e_down'],5)} "
              f"ratio {f(r['size_ratio'],4)}  closure z {f(r['closure_z'],2)}")
        print(f"   top_mag {[(round(a,5),round(c,4)) for a,_,c in r['top_mag'][:4]]}")
        print(f"   acf1 {f(r['acf1'],5)} band {f(r['acf_band'],5)} out {r['acf_out']}/30 runs_z {f(r['runs_z'],2)}")
        if nt.get("predicts"):
            print(f"   NAME predicts p_up {f(nt['p_up'],4)} ratio {f(nt['size_ratio'],2)} -> "
                  f"p_up z {f(nt.get('p_up_z'),1)} ratio obs {f(nt.get('ratio_obs'),3)}", flush=True)

for tf in ("1h", "15m"):
    t0 = time.time(); r = sf.drift_arm("Drift Switch Index 30", tf)
    if "vr" not in r: print("DRIFT", r.get("skip")); continue
    print(f"\nDRIFT 30 {tf} {time.time()-t0:.0f}s bars {r['n_bars']:,} acf1 {f(r['acf1_ret'],5)}")
    print("   VR   real", {k: round(v,3) for k,v in r["vr"].items()})
    print("   VR   shuf", {k: round(v,3) for k,v in r["vr_shuffle"].items()})
    print("   VR   surr", {k: round(v,3) for k,v in r["vr_surrogate"].items()})
    for k in (2,3):
        h = r.get(f"hmm{k}")
        if not h: continue
        print(f"   hmm{k} real  dwell {[round(d,1) for d in h['dwell']]} persist "
              f"{[round(d,2) for d in h['persist']]} sep {f(h['sep'],2)} mu {[round(m,6) for m in h['mu']]}")
        for tag in ("shuffle","surrogate"):
            g = r.get(f"hmm{k}_{tag}")
            if g: print(f"   hmm{k} {tag:9s} dwell {[round(d,1) for d in g['dwell']]} persist "
                        f"{[round(d,2) for d in g['persist']]} sep {f(g['sep'],2)}")
        rc = r.get(f"hmm{k}_recovery")
        if rc: print(f"   hmm{k} recovery dwell {[round(d,1) for d in rc['dwell']]} persist "
                     f"{[round(d,2) for d in rc['persist']]} corr {f(rc['corr_with_truth'],3)} "
                     f"auc {f(rc['auc_next_sign'],4)}", flush=True)

if boom:
    t0 = time.time(); r = fm.spike_arm(boom[0], replicates=4)
    rl, nl = r.get("real",{}), r.get("null",{})
    print(f"\nSPIKE-MODEL {boom[0]} {time.time()-t0:.0f}s per_bar {r.get('ticks_per_bar')} "
          f"rows {rl.get('rows')} base {f(rl.get('base_rate'),4)}")
    for k in ("logistic","logistic_nohaz","gru"):
        print(f"   {k:15s} real {f(rl.get(k))}  null {f(nl.get(k,{}).get('mean'))}"
              f"+-{f(nl.get(k,{}).get('sd'))} z {f(nl.get(k,{}).get('z'),2)} "
              f"pmax {f(nl.get(k,{}).get('p_max_of_k'),3)}")
    print(f"   shuffle {f(r.get('shuffle',{}).get('logistic'))} surrogate {f(r.get('surrogate',{}).get('logistic'))}")
    print("   census", {k: round(v,2) for k,v in r.get("census",{}).items()}, flush=True)

t0 = time.time(); r = fm.bar_arm("Drift Switch Index 30", "1h")
d, v = r.get("dir",{}), r.get("vol",{})
print(f"\nBAR drift 1h {time.time()-t0:.0f}s  dir logit {f(d.get('logistic'))} mom {f(d.get('momentum'))} "
      f"hmm {f(d.get('hmm'))} | shuf {f(d.get('shuffle'))} surr {f(d.get('surrogate'))} base {f(d.get('base_rate'))}")
print(f"   vol naive {f(v.get('naive_srel'))} mean {f(v.get('mean_srel'))} gap {f(v.get('naive_minus_mean'))} "
      f"har {f(v.get('har_srel'))} ridge {f(v.get('ridge_srel'))}", flush=True)

t0 = time.time(); r = fm.drift_model_arm("Drift Switch Index 30", "1h")
print(f"\nDRIFT-MODEL 1h {time.time()-t0:.0f}s rows {r.get('rows')} base {f(r.get('base_rate'))}")
for tag in ("real","shuffle","surrogate","null_switch","null_volonly"):
    a = r.get(tag)
    if a: print(f"   {tag:13s} hmm {f(a.get('hmm'))} gru {f(a.get('gru'))} mom22 {f(a.get('mom22'))}")
print("\nSMOKE OK", flush=True)
