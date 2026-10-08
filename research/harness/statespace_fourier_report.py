"""Tables and the frozen verdict for `statespace_fourier.py`.

  uv run python research/harness/statespace_fourier_report.py path/to/statespace_fourier.json
"""

from __future__ import annotations

import json
import sys

import numpy as np

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from statespace_report import bh

TFS = ["15m", "1h", "4h", "1d"]
SHORT = {"Volatility_75_Index": "V75", "Volatility_10_Index": "V10", "Volatility_10_1s_Index": "V10 (1s)",
         "Volatility_25_Index": "V25", "Volatility_25_1s_Index": "V25 (1s)", "Volatility_15_Index": "V15",
         "Volatility_15_1s_Index": "V15 (1s)", "Jump_25_Index": "Jump 25"}


def f(x, p=3, sign=False):
    if x is None:
        return "-"
    return f"{x:+.{p}f}" if sign else f"{x:.{p}f}"


def main(path):
    rows = [r for r in json.load(open(path)) if "skipped" not in r]
    real = {(r["sym"], r["tf"]): r for r in rows if r["kind"] == "real"}
    W = {}
    for r in rows:
        if r["kind"] != "real":
            W.setdefault((r["sym"], r["tf"]), []).append(r)
    syms = list(dict.fromkeys(r["sym"] for r in rows))

    def wmean(key, getter):
        v = [getter(w) for w in W.get(key, [])]
        v = [x for x in v if x is not None]
        return float(np.mean(v)) if v else None

    def dget(r, tag, part):
        return r["direction"].get(tag, {}).get(part, {}).get("auc") if isinstance(r["direction"].get(tag, {}).get(part), dict) else None

    cells = []
    print("## 1. Direction, N = 128, K = 5: real AUC [CI] (walks) | cycle part | trend part | bands | N64 N256 K3 K10\n")
    print("| instrument | tf | test bars | full | cycle (walks) | trend (walks) | band power (walks) | N64 / N256 / K3 / K10 |")
    print("|---|---|---:|---|---|---|---|---|")
    for s in syms:
        for tf in TFS:
            r = real.get((s, tf))
            if not r:
                continue
            m = r["direction"]["main"]["full"]
            w = wmean((s, tf), lambda x: dget(x, "main", "full"))
            cells.append((s, tf, m.get("p"), m["auc"], w))
            wc = wmean((s, tf), lambda x: dget(x, "main", "cycle"))
            wt = wmean((s, tf), lambda x: dget(x, "main", "trend"))
            wb = wmean((s, tf), lambda x: x["direction"]["main"].get("bands"))
            sens = " / ".join(f(dget(r, t, "full")) for t in ("N64", "N256", "K3", "K10"))
            print(f"| {SHORT.get(s, s)} | {tf} | {r['n_test']:,} | {f(m['auc'])} [{f(m.get('lo'))}-{f(m.get('hi'))}] ({f(w)}) | "
                  f"{f(dget(r, 'main', 'cycle'))} ({f(wc)}) | {f(dget(r, 'main', 'trend'))} ({f(wt)}) | "
                  f"{f(r['direction']['main'].get('bands'))} ({f(wb)}) | {sens} |")
    ok = bh([c[2] if c[2] is not None else 1.0 for c in cells])
    passes = [(c[0], c[1], c[3], c[4]) for c, k in zip(cells, ok)
              if k and c[3] > 0.5 and c[4] is not None and c[3] - c[4] >= 0.005]
    below = [(c[0], c[1], c[3], c[4]) for c in cells if c[4] is not None and c[3] < 0.5 and c[4] - c[3] >= 0.01]

    print("\n## 2. Volatility: next bar a top-10% |r|, AUC real (GARCH walk)\n")
    print("| instrument | tf | EWMA | + Fourier vol | + hour-of-week profile | + profile + Fourier | + band power |")
    print("|---|---|---|---|---|---|---|")
    vol_pass = []
    for s in syms:
        for tf in TFS:
            r = real.get((s, tf))
            if not r:
                continue
            v = r["vol"]
            g = [w for w in W.get((s, tf), []) if w["kind"] == "garch"]
            gv = g[0]["vol"] if g else {}
            cells_v = []
            for key in ("ewma", "ewma_fourier", "ewma_profile", "ewma_profile_fourier", "ewma_bands"):
                cells_v.append(f"{f(v.get(key))} ({f(gv.get(key))})")
            print(f"| {SHORT.get(s, s)} | {tf} | " + " | ".join(cells_v) + " |")
            if v.get("ewma") and v.get("ewma_fourier") and gv.get("ewma") and gv.get("ewma_fourier"):
                gain, ggain = v["ewma_fourier"] - v["ewma"], gv["ewma_fourier"] - gv["ewma"]
                if gain >= 0.005 and gain > ggain:
                    vol_pass.append((s, tf, round(gain, 4), round(ggain, 4),
                                     round((v.get("ewma_profile_fourier") or 0) - (v.get("ewma_profile") or 0), 4)))

    print("\n## 3. Trade on the confident decile (held one bar) and the tail\n")
    print("| instrument | tf | cost bps | n | gross bps (t) | net bps | P(>=4R) / P(>=10R) real | flip walks |")
    print("|---|---|---|---:|---|---|---|---|")
    for s in syms:
        for tf in TFS:
            r = real.get((s, tf))
            if not r or "trade" not in r:
                continue
            tr = r["trade"]
            tl = r.get("tail")
            wt = [w.get("tail") for w in W.get((s, tf), []) if w["kind"] == "flip" and w.get("tail")]
            wtxt = "; ".join(f"{f(x['p4'])} / {f(x['p10'])}" for x in wt) or "-"
            print(f"| {SHORT.get(s, s)} | {tf} | {r['cost_bps']:.2f} | {tr['n']} | {f(tr['gross_bps'], 2, True)} ({f(tr['t'], 1, True)}) | "
                  f"{f(tr['net_bps'], 2, True)} | {('-' if not tl else f(tl['p4']) + ' / ' + f(tl['p10']) + ' (' + str(tl['n']) + ')')} | {wtxt} |")

    print("\n## Verdict (frozen rules)\n")
    print(f"- direction cells: {len(cells)}; passing BH, above 0.5 and walks by >= 0.005: {len(passes)}")
    for p in passes:
        print(f"    {p}")
    print(f"- cells at least 0.01 BELOW their walks: {len(below)}")
    for p in below:
        print(f"    {p}")
    print(f"- volatility cells where the Fourier forecast adds >= 0.005 over EWMA and more than on GARCH: {len(vol_pass)}")
    for p in vol_pass:
        print(f"    {p}  (gain real, gain garch, gain over the hour-of-week profile)")


if __name__ == "__main__":
    main(sys.argv[1])
