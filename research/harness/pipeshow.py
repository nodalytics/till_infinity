"""Read `pipeline.json` back in slices that fit a 60-line log tail.

`lab.sh log` shows the last sixty lines, and the pipeline run's own log is
several hundred. Rather than re-run anything to see a table that has already
been computed, this prints one section at a time from the JSON the run wrote.

    ./.secrets/lab.sh run research/harness/pipeshow.py SHOW=lattice
"""

from __future__ import annotations

import json
import math
import os

PATH = os.environ.get("PIPE_JSON", os.path.expanduser("~/till_infinity/logs/pipeline.json"))
SHOW = os.environ.get("SHOW", "lattice")


def f(x, w=10, p=4):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return f"{'-':>{w}}"
    return f"{v:{w}.{p}g}" if math.isfinite(v) else f"{'-':>{w}}"


def main() -> None:
    r = json.load(open(PATH))
    print(f"== {SHOW} ==  keys: {sorted(r)}", flush=True)

    if SHOW == "lattice":
        for k, v in r["lattice"].items():
            print(f"{k:32s} n={v['n']:>7} dec={v['decimals']} g={f(v['grid'],9,4)} "
                  f"px={f(v['price'],11,7)} sd={f(v['sd_rel'],10,4)} sY={f(v['sigma_lat'],9,4)} "
                  f"b={f(v['bits'],6,3)} sp/g={f(v['spread_units'],7,3)} "
                  f"fz={f(v['frac_zero'],7,3)} keep={f(v['kept_frac'],6,4)} "
                  f"h={f(v['hours'],6,4)} D={int(v['diffusion'])}")

    elif SHOW == "clock":
        for k, v in r["clock"].items():
            print(f"{k:30s} gap={v['gap_mean_ms']:9.3f} mode={v['gap_mode_ms']:5d} "
                  f"off={v['offset_mean_ms']:7.2f}+-{v['offset_sd_ms']:5.2f} "
                  f"p01={v['offset_p01_ms']:6.0f} p99={v['offset_p99_ms']:6.0f} "
                  f"empty={100*v['empty_frac']:7.4f}% dbl={v['slots_doubled']:5d} "
                  f"per={v['period_from_slots_ms']:10.5f}")

    elif SHOW == "clock2":
        for k, v in r["variance_vs_gap"].items():
            print(f"{k:30s} n={v['n']:>8} slope={f(v['slope'],9,3)} se={f(v['se'],8,3)} "
                  f"z={f(v['z'],7,3)} gapsd={f(v.get('gap_sd_rel'),8,3)}")
        print("-- control --", r.get("variance_vs_gap_control"))
        print("-- shared jitter --")
        for k, v in r.get("shared_jitter", {}).items():
            print(f"  {k}: {v}")

    elif SHOW.startswith("atoms"):
        for feed, a in r["atoms"].items():
            print(f"--- {feed} ---")
            real, bar = a["real"], a["bar"]
            print(f"  n={real['n']:,} keep={real['kept_frac']:.5f} sY={real['sigma_lat']:.5g} "
                  f"eps={real['eps']:.4g} bits={real['bits']:.4f} price={real['price']:.6g} "
                  f"sd_rel={real['sd_rel']:.6g}")
            print(f"  ecf real={real['ecf']['max']:.6f} bar={bar['ecf']:.6f} "
                  f"at_w={real['ecf'].get('at_w', float('nan')):.1f} "
                  f"spacing={real['ecf'].get('spacing', float('nan')):.4g} "
                  f"w_lo={real['ecf']['w_lo']:.0f} w_hi={real['ecf']['w_hi']:.0f} "
                  f"floor={real['ecf']['floor']:.5f} qlat={real['quote_lattice_peak']:.5f}")
            print(f"  cap max|z|={real['cap']['max_abs_z']:.5f} exp={real['cap']['expected_max']:.5f} "
                  f"ratio={real['cap']['ratio']:.6f} bar={bar['cap_lo']:.6f} "
                  f"excl_upto={real['cap']['bits_excluded_upto']} reach={real['cap']['reach']:.2f}")
            print(f"  u_T={a['u_T']:.5f} bar={bar['u_T']:.5f} at_k={a['u_T_at_k']} "
                  f"tail={real['u']['n_tail']:,} ident={a.get('identified_k')}")
            print(f"  fired={a['fired']}  false_pos={a['false_positive']} "
                  f"(calib {a['n_calib']}, valid {a['n_valid']})")
            if SHOW == "atoms2":
                print("  per-k z:", {k: round(v, 2) for k, v in a["u_z"].items()})
                print("  recovery:")
                for name, v in a["recovery"].items():
                    print(f"    {name:22s} ecf {v['ecf']}/{v['reps']} u {v['u']}/{v['reps']} "
                          f"cap {v['cap']}/{v['reps']} caught {v['caught']}/{v['reps']} "
                          f"k={v.get('identified_k')}")

    elif SHOW == "drift":
        for row in r["drift"]["rows"]:
            print(f"{row['feed']:32s} {row['interval']:>3s} n={row['bars']:>6} "
                  f"y={row['years']:7.3f} sig={row['sigma']:8.5f} "
                  f"named={f(row['named'],6,3)} x={row['x']:+9.5f} "
                  f"worst={row['worst_z']:6.2f} s2T={row['sigma']**2*row['years']:9.5f} "
                  f"{row['first']:.6g}->{row['last']:.6g}")
        print("POOLED:", json.dumps(r["drift"]["pooled"], indent=None))

    elif SHOW == "rounding":
        ident = r["rounding"]["identifiability"]
        print("feed", r["rounding"]["feed"], "spec", r["rounding"]["spec"])
        print("n", ident["n"], "reps", ident["reps"])
        for m, st in ident["means"].items():
            print(f"  {m:11s} " + " ".join(f"{k}={v:.7g}" for k, v in st.items()))
        for m, row in ident["paired_vs_half_even"].items():
            print(f"  z {m:11s} " + " ".join(
                f"{k}={row[k]['z']:+.2f}{'*' if row[k].get('bit_identical') else ''}"
                for k in row))
        print("identifiable:", ident["identifiable"])
        print("-- bid/ask --")
        for k, v in r["bid_ask"].items():
            print(f"  {k:30s} gb={f(v['grid_bid'],9,4)} ga={f(v['grid_ask'],9,4)} "
                  f"sp/g={f(v['spread_units'],8,4)} spsd={f(v['spread_sd'],9,4)} "
                  f"half={f(v['mid_half_grid'],7,4)}")

    elif SHOW == "accum":
        for k, v in r["accumulation"].items():
            vr = v["vr"]
            print(f"{k:30s} sY={f(v['sigma_lat'],9,4)} n={v['n']:>8} "
                  f"rho1={f(v['rho1'],9,4)}+-{f(v['rho1_se'],7,3)} "
                  f"pred={f(v['pred_rho1_display'],9,4)} "
                  f"VR8={f(vr.get('8'),8,5)} VR64={f(vr.get('64'),8,5)} "
                  f"predVR={f(v['pred_vr_inf_display'],8,5)}")
        print("-- controls --")
        for k, v in r["accumulation_controls"].items():
            print(f"  {k}: verdict={v['verdict_rho1']}")
            for state, c in v["control"].items():
                print(f"    {state:11s} rho1={c['rho1']:+.6f} [{c['rho1_lo']:+.6f},"
                      f"{c['rho1_hi']:+.6f}] vr64={f(c['vr64'],9,5)} "
                      f"[{f(c['vr64_lo'],8,5)},{f(c['vr64_hi'],8,5)}] "
                      f"sig={c.get('sigma_internal', float('nan')):.5g}")


if __name__ == "__main__":
    main()
