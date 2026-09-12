"""Time one GRU cell and one drift cell under the budget, before committing the run."""
import time
import numpy as np
from research.harness import seqlab, seqfamilies as sf, fammodels as fm

t0 = time.time(); r = fm.spike_arm("Boom 500 Index", replicates=3)
rl, nl = r.get("real", {}), r.get("null", {})
print(f"spike_arm Boom 500: {time.time()-t0:.0f}s  per_bar {r.get('ticks_per_bar')} "
      f"rows {rl.get('rows')} base {rl.get('base_rate')}")
for k in ("logistic", "logistic_nohaz", "gru"):
    n = nl.get(k, {})
    print(f"   {k:15s} real {rl.get(k)}  null {n.get('mean')} +- {n.get('sd')} n={n.get('n')} z={n.get('z')}")
print("   shuffle", r.get("shuffle", {}).get("logistic"), " surrogate", r.get("surrogate", {}).get("logistic"))
print("   census", {k: round(v, 2) for k, v in r.get("census", {}).items()}, flush=True)

t0 = time.time(); r = fm.drift_model_arm("Drift Switch Index 30", "1h")
print(f"\ndrift_model_arm 1h: {time.time()-t0:.0f}s rows {r.get('rows')}")
for tag in ("real", "shuffle", "surrogate", "null_switch", "null_volonly"):
    a = r.get(tag)
    if a:
        print(f"   {tag:13s} hmm {a.get('hmm')} gru {a.get('gru')} mom22 {a.get('mom22')} "
              f"(n {a.get('hmm_n')}/{a.get('gru_n')}/{a.get('mom22_n')})")

t0 = time.time(); r = sf.acf_arm("Drift Switch Index 30", "15m")
print(f"\nacf_arm drift 15m: {time.time()-t0:.0f}s")
for k in ("n", "acf1", "t", "acf1_halves", "acf1_shuffle", "acf1_surrogate", "lb_q", "lb_p",
          "rel_spread", "sigma_bar", "acf"):
    print(f"   {k:16s} {r.get(k)}")
print("   ar1", r.get("ar1"), flush=True)

t0 = time.time(); r = sf.tick_acf_arm("Drift Switch Index 30")
print(f"\ntick_acf drift: {time.time()-t0:.0f}s {r}")
for s in ("Step Index", "Volatility 75 Index", "XAUUSD"):
    q = sf.acf_arm(s, "15m")
    print(f"   CONTROL {s:20s} n {q.get('n')} acf1 {q.get('acf1')} t {q.get('t')} "
          f"shuf {q.get('acf1_shuffle')} spread {q.get('rel_spread')}")
print("TIME OK", flush=True)
