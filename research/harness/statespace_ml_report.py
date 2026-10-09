"""Tables and the frozen verdict for `statespace_ml.py`.

  uv run python research/harness/statespace_ml_report.py path/to/statespace_ml.json
"""

from __future__ import annotations

import json
import sys

import numpy as np

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from statespace_fourier_report import SHORT, TFS, f
from statespace_report import bh


def main(path):
    rows = [r for r in json.load(open(path)) if "skipped" not in r]
    real = {(r["sym"], r["tf"]): r for r in rows if r["kind"] == "real"}
    walks = {}
    for r in rows:
        if r["kind"] != "real":
            walks.setdefault((r["sym"], r["tf"]), []).append(r)
    syms = list(dict.fromkeys(r["sym"] for r in rows))

    def w(key, target, model, kinds=("flip", "garch")):
        v = [x["targets"][target].get(model) for x in walks.get(key, []) if x["kind"] in kinds]
        v = [a for a in v if a is not None]
        return float(np.mean(v)) if v else None

    cells, filt, risk = [], [], []
    print("## Next-bar direction, test AUC: gradient boosting real (mean of walks)\n")
    print("| instrument | tf | test bars | all blocks [CI] | bars | bars + filters | filters alone | logistic, all | filter gain real / walks |")
    print("|---|---|---:|---|---|---|---|---|---|")
    for s in syms:
        for tf in TFS:
            r = real.get((s, tf))
            if not r:
                continue
            T = r["targets"]["up1"]
            k = (s, tf)
            ci = r.get("main_ci", {})
            gain = (T["bars+filters|gbm"] or 0) - (T["bars|gbm"] or 0)
            wg = [(x["targets"]["up1"]["bars+filters|gbm"] or 0) - (x["targets"]["up1"]["bars|gbm"] or 0)
                  for x in walks.get(k, [])]
            wgain = float(np.mean(wg)) if wg else None
            cells.append((s, tf, ci.get("p", 1.0), T["all|gbm"], w(k, "up1", "all|gbm"), gain, wgain))
            print(f"| {SHORT.get(s, s)} | {tf} | {r['n_test']:,} | {f(T['all|gbm'])} [{f(ci.get('lo'))}-{f(ci.get('hi'))}] ({f(w(k, 'up1', 'all|gbm'))}) | "
                  f"{f(T['bars|gbm'])} ({f(w(k, 'up1', 'bars|gbm'))}) | {f(T['bars+filters|gbm'])} ({f(w(k, 'up1', 'bars+filters|gbm'))}) | "
                  f"{f(T['filters|gbm'])} ({f(w(k, 'up1', 'filters|gbm'))}) | {f(T['all|logit'])} ({f(w(k, 'up1', 'all|logit'))}) | "
                  f"{f(gain, 3, True)} / {f(wgain, 3, True)} |")
    ok = bh([c[2] if c[2] is not None else 1.0 for c in cells])
    passes = [c for c, k in zip(cells, ok) if k and c[3] > 0.5 and c[4] is not None and c[3] - c[4] >= 0.005]
    for c in passes:
        if c[5] >= 0.003 and c[6] is not None and c[5] > c[6]:
            filt.append(c)

    print("\n## Five-bar direction, test AUC: gradient boosting, all blocks real (walks) | bars only real\n")
    print("| instrument | " + " | ".join(TFS) + " |")
    print("|---|" + "---|" * len(TFS))
    for s in syms:
        cs = []
        for tf in TFS:
            r = real.get((s, tf))
            cs.append("-" if not r else f"{f(r['targets']['up5']['all|gbm'])} ({f(w((s, tf), 'up5', 'all|gbm'))}) | {f(r['targets']['up5']['bars|gbm'])}")
        print(f"| {SHORT.get(s, s)} | " + " | ".join(cs) + " |")

    print("\n## Next bar a top-10% move, test AUC: gradient boosting real (GARCH walk)\n")
    print("| instrument | tf | bars | bars + filters | filters alone | + liquidity | all | filter gain real / GARCH |")
    print("|---|---|---|---|---|---|---|---|")
    for s in syms:
        for tf in TFS:
            r = real.get((s, tf))
            if not r:
                continue
            T = r["targets"]["shock"]
            k = (s, tf)
            g = lambda m: w(k, "shock", m, ("garch",))
            gain = (T["bars+filters|gbm"] or 0) - (T["bars|gbm"] or 0)
            ggain = (g("bars+filters|gbm") or 0) - (g("bars|gbm") or 0)
            if gain >= 0.003 and gain > ggain:
                risk.append((s, tf, round(gain, 4), round(ggain, 4)))
            print(f"| {SHORT.get(s, s)} | {tf} | {f(T['bars|gbm'])} ({f(g('bars|gbm'))}) | {f(T['bars+filters|gbm'])} ({f(g('bars+filters|gbm'))}) | "
                  f"{f(T['filters|gbm'])} ({f(g('filters|gbm'))}) | {f(T['bars+filters+liq|gbm'])} | {f(T['all|gbm'])} ({f(g('all|gbm'))}) | "
                  f"{f(gain, 3, True)} / {f(ggain, 3, True)} |")

    print("\n## Trade on the confident decile of the all-blocks model, held one bar; tail before a one-sigma stop\n")
    print("| instrument | tf | cost bps | n | gross bps (t) | net bps | P(>=4R) / P(>=10R) real | walks |")
    print("|---|---|---|---:|---|---|---|---|")
    for s in syms:
        for tf in TFS:
            r = real.get((s, tf))
            if not r or "trade" not in r:
                continue
            t = r["trade"]
            tl = r.get("tail")
            wt = [x.get("tail") for x in walks.get((s, tf), []) if x.get("tail")]
            wtxt = "; ".join(f"{f(x['p4'])} / {f(x['p10'])}" for x in wt) or "-"
            print(f"| {SHORT.get(s, s)} | {tf} | {r['cost_bps']:.2f} | {t['n']} | {f(t['gross_bps'], 2, True)} ({f(t['t'], 1, True)}) | "
                  f"{f(t['net_bps'], 2, True)} | {('-' if not tl else f(tl['p4']) + ' / ' + f(tl['p10']) + ' (' + str(tl['n']) + ')')} | {wtxt} |")

    print("\n## Logistic weights on the standardised filter features, next-bar direction, real bars (mean over cells)\n")
    ws = {}
    for r in real.values():
        for k, v in r.get("filter_weights_up1", {}).items():
            ws.setdefault(k, []).append(v)
    for k, v in sorted(ws.items(), key=lambda kv: -abs(np.mean(kv[1]))):
        print(f"  {k:<12} mean {np.mean(v):+.4f}  mean |w| {np.mean(np.abs(v)):.4f}  n {len(v)}")

    print("\n## Verdict (frozen rules)\n")
    print(f"- direction cells {len(cells)}; passing BH, above 0.5 and walks by >= 0.005: {len(passes)}")
    for c in passes:
        print(f"    {c[0]} {c[1]}: AUC {c[3]:.4f} walks {c[4]:.4f}  filter gain {c[5]:+.4f} (walks {c[6]:+.4f})")
    print(f"- passing cells where the filters add >= 0.003 over bars alone and more than on walks: {len(filt)}")
    for c in filt:
        print(f"    {c[0]} {c[1]}")
    print(f"- shock cells where the filters add >= 0.003 over bars and more than on the GARCH walk: {len(risk)}")
    for c in risk:
        print(f"    {c}")


if __name__ == "__main__":
    main(sys.argv[1])
