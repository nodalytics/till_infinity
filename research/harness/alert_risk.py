"""The expansion alert as a risk overlay on the trades the desk's strategies take.

The alert forecasts a range expansion (AUC 0.80 at 15m/1h, 3.9x the base rate in its top decile)
and nothing about direction. The use it was built for is risk: when a position's market fires the
alert, a fast move is coming, so take less of it. This asks whether that would have helped, on
every intent the strategies asked for (triage.py's settled rows), using only held-out predictions.

Pre-registered (2026-10-02), before any run.

  trades    triage.py's rows: universe "market", the `ships` exit, net R (and gross)
  flag      the trade's market fired the alert (lift >= 2.5) on 15m or 1h within the 16 bars before
            its entry, from expansion_build.py's held-out predictions; trades on markets or times
            the predictions do not cover are reported apart, not guessed
  overlays  none; half size on flagged trades (their R x 0.5); half size on the same number of
            trades chosen at random (500 draws)
  measures  mean R, ES5 (mean of the worst 5% of per-trade R), the worst day, max drawdown of the
            cumulative R in time order, and mean / sd (risk-adjusted)
  counts if the alert cut beats >= 95% of random cuts on ES5 and on mean / sd, in both halves
            of the period; and first, are flagged trades different at all (their mean, sd and ES5)?
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research" / "harness"))

OUT = Path(os.environ.get("OUT", ".data/alert_risk"))
TRIAGE = Path(os.environ.get("TRIAGE", os.path.expanduser("~/till_infinity/data/triage/triage.pkl.gz")))
PRED = Path(os.environ.get("PRED", ".data/expansion_all"))
SEQLAB = Path(os.environ.get("SEQLAB", ".data/seqlab"))
RNG = np.random.default_rng(61)
SECONDS = {"15m": 900, "1h": 3600}


def slug_map(symbols) -> dict[str, str]:
    """Journal feed slug -> the prediction file's symbol (EURUSD -> eurusd, XAUUSD -> gold, ...)."""
    sys.path.insert(0, str(ROOT / "research" / "harness"))
    from mt5fill import REAL
    out = {}
    for sym in symbols:
        base = sym.split(".")[0]
        if base in REAL:
            out[REAL[base]] = sym
        out[sym.lower()] = sym
    return out


def measures(r: np.ndarray, when: np.ndarray) -> dict:
    order = np.argsort(when)
    cum = np.cumsum(r[order])
    dd = float(np.min(cum - np.maximum.accumulate(np.r_[0.0, cum])[1:]))
    worst = np.sort(r)[: max(1, int(0.05 * len(r)))]
    day = pd.Series(r).groupby(pd.to_datetime(when, unit="s").floor("D")).sum()
    return dict(mean=float(r.mean()), sd=float(r.std()), es5=float(worst.mean()),
                worst_day=float(day.min()), max_dd=dd, ratio=float(r.mean() / r.std()) if r.std() > 0 else 0.0)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    # triage.py's own output on the lab (it wrote this file), not outside data
    tri = pd.read_pickle(TRIAGE)
    print(tri["universe"].value_counts().to_dict(), tri["source"].value_counts().to_dict(), flush=True)
    t = tri[(tri["universe"] == "market") & (tri["exit"] == "ships")]
    t = t.pivot_table(index=["source", "strategy", "feed", "family", "interval", "when"], columns="cost",
                      values="r", aggfunc="first").reset_index()
    pred = pd.read_csv(PRED / "test_predictions.csv")
    pred = pred[pred["key"].str.endswith(("|15m", "|1h"))]
    pred["sym"] = pred["key"].str.split("|").str[0]
    pred["iv"] = pred["key"].str.split("|").str[1]
    smap = slug_map(pred["sym"].unique())
    t["sym"] = t["feed"].map(smap)
    covered_from = pred.groupby("sym")["when"].min()
    hot = pred[pred["lift"] >= 2.5]
    hot_by = {s: (g["when"].to_numpy(), g["iv"].to_numpy()) for s, g in hot.groupby("sym")}
    flag = np.zeros(len(t), bool)
    known = np.zeros(len(t), bool)
    for k, (s, w) in enumerate(zip(t["sym"], t["when"], strict=True)):
        if not isinstance(s, str) or s not in covered_from.index or w < covered_from[s]:
            continue
        known[k] = True
        hw = hot_by.get(s)
        if hw is None:
            continue
        ww, iv = hw
        span = np.where(iv == "15m", 16 * 900, 16 * 3600)
        flag[k] = bool(np.any((ww <= w) & (ww > w - span)))
    t["flag"], t["known"] = flag, known
    res = {"trades": len(t), "covered": int(known.sum()), "flagged": int(flag.sum()),
           "flag_share": round(float(flag[known].mean()), 4) if known.any() else None,
           "by_family_covered": t[known].groupby("family").size().to_dict()}
    k = t[t["known"] & t["net"].notna()].copy()
    res["flagged_vs_not"] = {
        name: {c: round(float(v), 4) for c, v in measures(g["net"].to_numpy(), g["when"].to_numpy()).items()}
        | {"n": len(g), "gross_mean": round(float(g["gross"].mean()), 4)}
        for name, g in (("flagged", k[k["flag"]]), ("not_flagged", k[~k["flag"]]))}
    mid = np.median(k["when"])
    over = {}
    for half, h in (("all", k), ("first", k[k["when"] < mid]), ("second", k[k["when"] >= mid])):
        r, w, f = h["net"].to_numpy(), h["when"].to_numpy(), h["flag"].to_numpy()
        base = measures(r, w)
        cut = measures(np.where(f, 0.5 * r, r), w)
        rand = []
        for _ in range(500):
            pick = np.zeros(len(r), bool)
            pick[RNG.choice(len(r), int(f.sum()), replace=False)] = True
            rand.append(measures(np.where(pick, 0.5 * r, r), w))
        rd = pd.DataFrame(rand)
        over[half] = dict(n=len(r), flagged=int(f.sum()),
                          none={c: round(v, 4) for c, v in base.items()},
                          alert_cut={c: round(v, 4) for c, v in cut.items()},
                          random_cut_median={c: round(float(rd[c].median()), 4) for c in rd},
                          beats_random_es5=round(float((cut["es5"] > rd["es5"]).mean()), 3),
                          beats_random_ratio=round(float((cut["ratio"] > rd["ratio"]).mean()), 3))
    res["overlay"] = over
    res["counts"] = bool(all(over[h]["beats_random_es5"] >= 0.95 and over[h]["beats_random_ratio"] >= 0.95
                             for h in ("first", "second")))
    res["by_family"] = {f: dict(n=len(g), flagged=int(g["flag"].sum()),
                                mean_flagged=round(float(g.loc[g["flag"], "net"].mean()), 4) if g["flag"].any() else None,
                                mean_not=round(float(g.loc[~g["flag"], "net"].mean()), 4))
                        for f, g in k.groupby("family")}
    print(json.dumps(res, indent=1, default=str), flush=True)
    (OUT / "alert_risk.json").write_text(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    main()
