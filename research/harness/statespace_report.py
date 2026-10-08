"""Tables for `research/docs/state-space-filters.md` from `statespace.py`'s results.json.

  uv run python research/harness/statespace_report.py path/to/results.json
"""

from __future__ import annotations

import json
import sys

import numpy as np

MODELS = ["kalman", "hmm", "particle", "qdecoh", "qbasis", "quantum"]
TFS = ["15m", "1h", "4h", "1d"]


def f(x, p=3, sign=False):
    if x is None:
        return "-"
    return f"{x:+.{p}f}" if sign else f"{x:.{p}f}"


def bh(pvals, q=0.05):
    p = np.asarray(pvals)
    order = np.argsort(p)
    m = len(p)
    passed = np.zeros(m, bool)
    thr = q * np.arange(1, m + 1) / m
    ok = p[order] <= thr
    if ok.any():
        passed[order[: np.max(np.where(ok)[0]) + 1]] = True
    return passed


def main(path):
    d = json.load(open(path))
    S = {(s["sym"], s["tf"], s["kind"]): s for s in d["series"]}

    print("## Synthetic controls (test AUC / log score mnats per bar over a t walk / regime accuracy)\n")
    print("| model | S1 classical regimes | S2 quantum-generated |")
    print("|---|---|---|")
    for m in ["oracle"] + MODELS:
        cells = []
        for w in ("S1", "S2"):
            x = d["synth"].get(w, {}).get(m)
            cells.append("-" if x is None else f"{f(x['auc'])} / {f(x['logscore_mnats'], 1, True)} / {f(x['regime'])}")
        print(f"| {m} | " + " | ".join(cells) + " |")
    for w in ("S1", "S2"):
        g = {k: round(v["gamma"], 3) for k, v in d["synth"].get(w, {}).get("info", {}).items()}
        print(f"\n{w} fitted dephasing gamma: {g}")

    for obs in ("close", "ohlc"):
        print(f"\n## Direction, {obs}: test AUC [95% block CI] real | flip walk | GARCH walk; log score real\n")
        print("| series | model | real AUC | CI | flip | garch | real - walks | log score | net bps/bar | confident net bps (n) |")
        print("|---|---|---|---|---|---|---|---|---|---|")
        for sym in ("EURUSD", "V75"):
            for tf in TFS:
                r = S.get((sym, tf, "real"))
                if not r:
                    continue
                for m in MODELS:
                    x = r[obs]["models"][m]
                    fw = S.get((sym, tf, "flip"), {}).get(obs, {}).get("models", {}).get(m, {})
                    gw = S.get((sym, tf, "garch"), {}).get(obs, {}).get("models", {}).get(m, {})
                    walk = np.nanmean([v for v in (fw.get("auc"), gw.get("auc")) if v is not None]) if (fw or gw) else None
                    gap = x["auc"] - walk if (walk is not None and x["auc"] is not None) else None
                    conf = f"{f(x.get('conf_net_bps'), 1, True)} ({x.get('conf_n', 0)})"
                    print(f"| {sym} {tf} | {m} | {f(x['auc'])} | {f(x['lo'])}-{f(x['hi'])} | {f(fw.get('auc'))} | "
                          f"{f(gw.get('auc'))} | {f(gap, 3, True)} | {f(x['logscore_mnats'], 1, True)} | "
                          f"{f(x['net_bps'], 2, True)} | {conf} |")

    print("\n## Coherence ablation: fitted gamma (1 = classical) and train log-lik per bar, real series\n")
    print("| series | obs | qdecoh ll | qbasis ll (gamma) | quantum ll (gamma) |")
    print("|---|---|---|---|---|")
    for sym in ("EURUSD", "V75"):
        for tf in TFS:
            r = S.get((sym, tf, "real"))
            if not r:
                continue
            for obs in ("close", "ohlc"):
                i = r[obs]["info"]
                print(f"| {sym} {tf} | {obs} | {f(i['qdecoh']['train_ll'], 4)} | {f(i['qbasis']['train_ll'], 4)} "
                      f"({f(i['qbasis']['gamma'], 2)}) | {f(i['quantum']['train_ll'], 4)} ({f(i['quantum']['gamma'], 2)}) |")

    print("\n## Tail: confident calls, stop 1 bar-sigma, no target: P(>=4R) / P(>=10R) (n); walk 1/(N+1) = 0.200 / 0.091\n")
    print("| series | model | obs | real | flip | garch |")
    print("|---|---|---|---|---|---|")
    for sym in ("EURUSD", "V75"):
        for tf in TFS:
            for m in ("hmm", "quantum"):
                for obs in ("close", "ohlc"):
                    cells = []
                    for k in ("real", "flip", "garch"):
                        t = S.get((sym, tf, k), {}).get(obs, {}).get("models", {}).get(m, {}).get("tail")
                        cells.append("-" if not t else f"{f(t['p4'])} / {f(t['p10'])} ({t['n']})")
                    print(f"| {sym} {tf} | {m} | {obs} | " + " | ".join(cells) + " |")

    print("\n## Multi-timeframe: lower-frame AUC alone, with the closed higher-frame reading, higher alone; agreement\n")
    print("| pair | obs | model | kind | LTF | LTF+HTF | HTF alone | agree share | hit agree | hit disagree | agree net bps |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for sym in ("EURUSD", "V75"):
        for tf in TFS:
            for obs in ("close", "ohlc"):
                for kind in ("real", "flip", "garch"):
                    r = S.get((sym, tf, kind))
                    if not r:
                        continue
                    for ht, row in r[obs]["mtf"].items():
                        for m in ("hmm", "quantum", "kalman"):
                            c = row["combined"].get(m)
                            if not c:
                                continue
                            a = row["agree"][m]
                            print(f"| {sym} {tf}->{ht} | {obs} | {m} | {kind} | {f(c['ltf'])} | {f(c['both'])} | "
                                  f"{f(row['htf_auc_alone'][m])} | {f(a['share'], 2)} | {f(a['hit'])} | "
                                  f"{f(a['hit_disagree'])} | {f(a['net_bps'], 2, True)} |")

    print("\n## The zone method: fill AUC (physics no-fit | method | + candle | + HTF state), walks, calibration, trade\n")
    print("| series | kind | fill | physics | method | +candle | +HTF hmm | P>=0.95 pred/real (n) | P>=0.99 pred/real (n) |"
          " net R all | net R p>=0.95 | net R p>=0.99 | tail P4/P10 (n) |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for sym in ("EURUSD", "V75"):
        for tf in TFS:
            for kind in ("real", "flip", "garch"):
                r = S.get((sym, tf, kind))
                if not r:
                    continue
                z = r["zone"]
                htf = [row.get("zone_htf", {}).get("auc_method_htf") for row in r["ohlc"]["mtf"].values()]
                htf = [h for h in htf if h is not None]
                c95, c99 = z["calibration"]["0.95"], z["calibration"]["0.99"]
                t = z["trades"]
                tl = z.get("tail")
                print(f"| {sym} {tf} | {kind} | {f(z['fill_rate'])} | {f(z['auc_physics'])} | {f(z['auc_method'])} | "
                      f"{f(z['auc_method_candle'])} | {f(htf[0]) if htf else '-'} | "
                      f"{f(c95[1])}/{f(c95[2])} ({c95[0]}) | {f(c99[1])}/{f(c99[2])} ({c99[0]}) | "
                      f"{f(t['all']['net_R1'], 3, True)} | {f(t['p>=0.95']['net_R1'], 3, True)} ({t['p>=0.95']['n']}) | "
                      f"{f(t['p>=0.99']['net_R1'], 3, True)} ({t['p>=0.99']['n']}) | "
                      f"{('-' if not tl else f(tl['p4']) + '/' + f(tl['p10']) + ' (' + str(tl['n']) + ')')} |")

    # multiplicity over the real direction cells: AUC > 0.5, block-bootstrap p
    cells = []
    for (sym, tf, kind), r in S.items():
        if kind != "real":
            continue
        for obs in ("close", "ohlc"):
            for m in MODELS:
                x = r[obs]["models"][m]
                if x.get("p") is not None:
                    cells.append((f"{sym} {tf} {obs} {m}", x["p"], x["auc"]))
    passed = bh([c[1] for c in cells])
    print(f"\n## Benjamini-Hochberg over {len(cells)} real direction cells (AUC > 0.5): {passed.sum()} pass")
    for c, ok in zip(cells, passed):
        if ok or c[1] < 0.05:
            print(f"  {c[0]}: AUC {c[2]:.4f}, p {c[1]:.3f}, {'PASSES BH' if ok else 'nominal only'}")


if __name__ == "__main__":
    main(sys.argv[1])
