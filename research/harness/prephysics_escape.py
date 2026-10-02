"""Part K, question 2: do fatigue, rheology or foreshocks separate clean escapes from whipsaws?

prephysics.py's docstring promised this test and its first version did not run it; this is it.
Pre-registered (2026-10-02), before any run, as written there: at each breakout from a compression
box (escape.py's events: arm at a compressed bar, the first bar within 16 to leave the 16-bar box),
read the K4 fatigue, K1 rheology and K3 foreshock features at the breakout bar; label clean (+1W
before the opposite edge) against whipsaw (the opposite edge first), stalls dropped. Gradient
boosting on the martingale geometry (p_null) alone, against geometry plus each group; each series'
first half of events trains, the second half scores (AUC, both halves of it). Real markets 15m and
1h, against the same on GARCH walks. Counts if a group adds >= 0.01 AUC in both halves and not on
the walks.
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
sys.path.insert(0, str(ROOT))

import escape as es  # noqa: E402
import expansion_build as eb  # noqa: E402
import prephysics as pp  # noqa: E402
from till_infinity.models import expansion_train as et  # noqa: E402
from till_infinity.models.shocks_train import auc  # noqa: E402

OUT = Path(os.environ.get("OUT", ".data/prephysics"))


def collect(name: str, bars) -> pd.DataFrame | None:
    df = pp.frame(bars).rename(columns={"time": "time"})
    if len(df) < 3000:
        return None
    f = pp.physics(df)
    s = es.sigma(df.assign(open=df["open"]))
    pct = pd.Series(s).rolling(1500, min_periods=300).rank(pct=True).to_numpy()
    arms = np.flatnonzero(pct <= 0.2)
    ev = pd.DataFrame(es.events(df, arms))
    if ev.empty:
        return None
    ev = ev[(ev["outcome"].isin(["clean", "whipsaw"])) & ~ev["second"].astype(bool)].copy()
    cols = [c for g in pp.GROUPS.values() for c in g]
    ev[cols] = f[cols].to_numpy()[ev["b"].astype(int)]
    ev["y"] = (ev["outcome"] == "clean").astype(float)
    ev["key"] = name
    ev["late"] = ev["arm"] >= np.median(ev["arm"])
    return ev


def judge(d: pd.DataFrame) -> dict:
    from sklearn.ensemble import HistGradientBoostingClassifier

    tr, te = ~d["late"].to_numpy(), d["late"].to_numpy()
    third = d.loc[te, "arm"].to_numpy() >= np.median(d.loc[te, "arm"])
    y = d["y"].to_numpy()

    def score(cols):
        X = d[cols].to_numpy(float)
        X[:, np.all(np.isnan(X[tr]), axis=0)] = 0.0
        m = HistGradientBoostingClassifier(max_depth=3, max_iter=150, learning_rate=0.05,
                                           min_samples_leaf=200).fit(X[tr], y[tr])
        p = m.predict_proba(X[te])[:, 1]
        yt = y[te]
        return dict(auc=round(auc(yt, p), 4), halves=[round(auc(yt[~third], p[~third]), 4),
                                                      round(auc(yt[third], p[third]), 4)])

    out = {"events": len(d), "clean_share": round(float(y.mean()), 4), "geometry": score(["p_null"])}
    g0 = out["geometry"]
    for g, gc in pp.GROUPS.items():
        v = score(["p_null"] + gc)
        v["counts"] = bool(min(v["halves"][i] - g0["halves"][i] for i in (0, 1)) >= 0.01)
        out[g] = v
    out["all"] = score(["p_null"] + [c for g in pp.GROUPS.values() for c in g])
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    res = {}
    parts = []
    for sym, fam in eb.FAMILY.items():
        if fam == "deriv":
            continue
        for iv in ("15m", "1h"):
            bars = eb.load(sym, iv)
            if len(bars) > 3000:
                e = collect(f"{sym}|{iv}", bars)
                if e is not None:
                    parts.append(e)
    res["market"] = judge(pd.concat(parts, ignore_index=True))
    print("market", json.dumps(res["market"]), flush=True)
    walks = et.walks(8, 20_000, garch=True)
    wparts = [collect(f"{s}|{iv}", b) for (s, iv), b in walks.items() if iv in ("15m", "1h")]
    res["walks"] = judge(pd.concat([w for w in wparts if w is not None], ignore_index=True))
    print("walks", json.dumps(res["walks"]), flush=True)
    (OUT / "prephysics_escape.json").write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
