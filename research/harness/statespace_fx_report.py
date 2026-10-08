"""Tables and the frozen verdict for `statespace_fx.py`.

  uv run python research/harness/statespace_fx_report.py path/to/statespace_fx.json
"""

from __future__ import annotations

import json
import sys

import numpy as np

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from statespace_report import bh

PAIRS = ["GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD"]
TFS = ["15m", "1h", "4h", "1d"]
MODELS = ["kalman_close", "kalman_ohlc", "hmm_ohlc"]


def main(path):
    rows = json.load(open(path))
    real = {(r["pair"], r["tf"]): r for r in rows if r["kind"] == "real"}
    walks = {}
    for r in rows:
        if r["kind"] != "real":
            walks.setdefault((r["pair"], r["tf"]), []).append(r)

    def walk_auc(pair, tf, m):
        v = [w["models"][m]["masked"]["auc"] for w in walks.get((pair, tf), [])]
        v = [x for x in v if x is not None]
        return float(np.mean(v)) if v else None

    cells = []
    for pair in PAIRS:
        for tf in TFS:
            for m in MODELS:
                x = real[(pair, tf)]["models"][m]["masked"]
                cells.append((pair, tf, m, x["p"], x["auc"], walk_auc(pair, tf, m)))
    passed_bh = bh([c[3] for c in cells])
    passes = {(c[0], c[1], c[2]): bool(ok and c[5] is not None and c[4] - c[5] >= 0.005)
              for c, ok in zip(cells, passed_bh)}

    print("## AUC, rollover masked: real [95% CI] (mean of 3 walks) | unmasked real | phi; * = passes the frozen rule\n")
    print("| pair | tf | test from | n | " + " | ".join(MODELS) + " | unmasked (k_close, k_ohlc, hmm) | kalman phi |")
    print("|---|---|---|---|" + "---|" * len(MODELS) + "---|---|")
    for pair in PAIRS + ["EURUSD"]:
        for tf in TFS:
            r = real.get((pair, tf))
            if not r:
                continue
            cs = []
            for m in MODELS:
                x = r["models"][m]["masked"]
                w = walk_auc(pair, tf, m)
                star = "*" if passes.get((pair, tf, m)) else ""
                cs.append(f"{x['auc']:.3f}{star} [{x['lo']:.3f}-{x['hi']:.3f}] ({w:.3f})")
            um = ", ".join(f"{r['models'][m]['unmasked']['auc']:.3f}" for m in MODELS)
            phi = r["models"]["kalman_close"]["info"]["phi"]
            print(f"| {pair} | {tf} | {r['test_from']} | {r['n_test']:,} | " + " | ".join(cs) + f" | {um} | {phi:+.3f} |")

    print("\n## The confident decile, held one bar: n, gross bps, net at quoted spread, net at 1 pip (t of gross)\n")
    print("| pair | tf | quoted / 1 pip cost bps | " + " | ".join(MODELS) + " |")
    print("|---|---|---|" + "---|" * len(MODELS))
    for pair in PAIRS + ["EURUSD"]:
        for tf in TFS:
            r = real.get((pair, tf))
            if not r:
                continue
            cs = []
            for m in MODELS:
                t = r["models"][m]["trade"]
                cs.append(f"{t['conf_n']}, {t['conf_gross_bps']:+.2f}, {t['conf_net_quoted_bps']:+.2f}, "
                          f"{t['conf_net_retail_bps']:+.2f} (t {t['conf_t']:+.1f})")
            c = r["cost_bps"]
            print(f"| {pair} | {tf} | {c['quoted']:.2f} / {c['retail']:.2f} | " + " | ".join(cs) + " |")

    n_pass = sum(passes.values())
    pairs_fast = sorted({p for (p, tf, m), ok in passes.items() if ok and tf in ("15m", "1h")})
    paying = [(p, tf, m) for (p, tf, m), ok in passes.items() if ok
              and real[(p, tf)]["models"][m]["trade"]["conf_net_quoted_bps"] > 0]
    print(f"\n## Verdict (frozen rules)\n")
    print(f"- cells passing BH (q 0.05 over {len(cells)}) and beating walks by >= 0.005: {n_pass}")
    print(f"- pairs with a passing 15m or 1h cell: {len(pairs_fast)} {pairs_fast} (needs >= 4)")
    print(f"- CONFIRMED: {len(pairs_fast) >= 4}")
    print(f"- passing cells net positive at the quoted spread: {len(paying)} {paying}")
    paying_retail = [c for c in paying if real[c[:2]]["models"][c[2]]["trade"]["conf_net_retail_bps"] > 0]
    print(f"- ... and at 1 pip: {len(paying_retail)} {paying_retail}")


if __name__ == "__main__":
    main(sys.argv[1])
