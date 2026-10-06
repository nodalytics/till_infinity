"""Diagnostics added after the frozen run (not registered): where the direction skill sits in the day.

The registered P2 / behavioural AUCs pool every hour. This splits them into the bars whose label spans
the daily FX rollover (17:00 New York, 21:00 / 22:00 UTC, where bid quotes widen and dip) and the rest,
and does the same for the conformal-set trades. Reads OUT/pred and OUT/report/trades.pkl (our own
pickles), writes OUT/report/diag_*.csv.

  OUT=... python research/ideas/fxml_diag.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fxml_data as D  # noqa: E402
import fxml_report as R  # noqa: E402

# bars whose own close or whose label's close sits in or next to the rollover window
ROLL_HOURS = {"15m": set(range(19, 24)), "1h": {19, 20, 21, 22}, "4h": {16, 20}, "1d": set()}


def roll_mask(m, tf):
    h = m["hour"].to_numpy().astype(int)
    return np.isin(h, sorted(ROLL_HOURS[tf]))


def main():
    rows = []
    for tf in D.TFS:
        m_ts = R.meta(tf, "real")["ts"].to_numpy(np.int64)
        B = R.Boot(m_ts[m_ts >= D.SPLIT], R.B_SEC)
        for tgt in ("sign1", "signk", "nr2L", "nr2S", "first", "tup05", "tdn05", "tup10", "tdn10"):
            prs = {s: R.load_pred(tf, s, tgt) for s in D.SOURCES}
            if any(v is None for v in prs.values()):
                continue
            for c in ("POOL", "FX", "METAL", "HOLD", "INDEX"):
                for part in ("ex_rollover", "rollover"):
                    a = {}
                    for s in D.SOURCES:
                        pr, m = prs[s], R.meta(tf, s)
                        rm = roll_mask(m, tf)
                        sel = R.scored(pr, m, c) & (~rm if part == "ex_rollover" else rm)
                        if sel.sum() < 200:
                            continue
                        ts = m["ts"].to_numpy(np.int64)[sel]
                        nm = pr.get("best", "hgb") if tgt == "sign1" and tf == "4h" else "hgb"
                        a[s] = B.auc(ts, pr["y"][sel].astype(float), pr["pred"][nm][sel].astype(float))
                    if "real" not in a:
                        continue
                    r = dict(tf=tf, target=tgt, cls=c, part=part, auc_real=a["real"][0],
                             auc_real_lo=R.ci(a["real"][1], 0)[0], auc_real_hi=R.ci(a["real"][1], 0)[1])
                    for w in R.WALKS:
                        if w in a:
                            d = a["real"][1] - a[w][1]
                            r[f"auc_{w}"] = a[w][0]
                            r[f"diff_{w}"] = a["real"][0] - a[w][0]
                            r[f"diff_{w}_lo"], r[f"diff_{w}_hi"] = R.ci(d, 0)[:2]
                    rows.append(r)
    pd.DataFrame(rows).to_csv(R.REP / "diag_rollover_auc.csv", index=False)
    # trades by the signal bar's hour
    p = R.REP / "trades.pkl"
    if p.exists():
        T = pd.read_pickle(p)  # our own pickle
        T["hour"] = (T["ts"] // 3600) % 24
        out = []
        for tf in D.TFS:
            m_ts = R.meta(tf, "real")["ts"].to_numpy(np.int64)
            B = R.Boot(m_ts[m_ts >= D.SPLIT], R.B_SEC)
            for s in D.SOURCES:
                for part in ("all", "ex_rollover", "rollover"):
                    x = T[(T.tf == tf) & (T.source == s) & (T.cls != "HOLD")]
                    if part != "all":
                        rm = x["hour"].isin(sorted(ROLL_HOURS[tf]))
                        x = x[~rm] if part == "ex_rollover" else x[rm]
                    if len(x) < 30:
                        continue
                    r = dict(tf=tf, source=s, part=part, n=len(x))
                    for ex in ("net1", "net2", "net4", "net10", "nettrail", "g1", "gtrail"):
                        pt, dr = B.mean(x.ts.to_numpy(np.int64), x[ex].to_numpy(float))
                        r[ex], r[f"{ex}_lo"], r[f"{ex}_hi"] = pt, *R.ci(dr, pt)[:2]
                    for n_ in R.NS:
                        r[f"P{n_}"] = float((x.mfe >= n_).mean())
                    out.append(r)
        pd.DataFrame(out).to_csv(R.REP / "diag_rollover_trades.csv", index=False)
    print("diag done", flush=True)


if __name__ == "__main__":
    main()
