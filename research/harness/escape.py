"""Does compression change the distribution of post-breakout paths? Clean escape against whipsaw.

energy.py found the expansion alert raises displacement (P(Y > 4 sigma) 0.25 -> 0.60) *and* the
whipsaw (both box edges touched, 0.10 -> 0.30). This asks the sharper question: once price leaves
the box, does it commit?

Pre-registered (2026-10-01), before any run. Held-out rows only.

  box        [L, H] = the 16 bars ending at the arming bar, W = H - L. Arming: one per 16 bars.
  breakout   the first bar within the next 16 whose high > H (up) or low < L (down); a bar
             through both is "both" and counted apart
  follow     48 bars from the breakout bar's close c_b, side s
  outcomes   clean     reaches the edge + 1 W (H + W up) before the opposite edge (L up)
             whipsaw   reaches the opposite edge first
             stall     neither within 48 bars
  the null   for a martingale, P(clean) = (distance from c_b to the opposite edge) / (distance to
             +1W plus distance to the opposite edge), event by event. **Excess = realised clean
             rate minus that.** Zero on a martingale whatever the state; positive means breakouts
             commit more than chance, negative means they whipsaw more than chance.
  measures   BQ = max favourable excursion past the edge / W; WD = MAE / MFE from c_b; T_commit
             = bars to +1W (clean only); RS = W / bars to the opposite edge (whipsaw only)
  groups     A = alert (lift >= 2.5), Q = compressed, alert quiet (< 1), all compressed
  refractory after a whipsaw, the opposite-edge crossing is a second breakout: its excess against
             first breakouts'
  precursors at the breakout bar, direction-free: its range / sigma, whether it closed outside
             the box, its tick-volume z, bars from arming to breakout, W / sigma, alert lift.
             AUC of each for clean against whipsaw; and gradient boosting, first half of the
             held-out period trains, second half scores
  controls   the same on 12 GARCH walks (excess and precursor AUCs should be ~0 and ~0.5)
  judged     excess with a day-cluster bootstrap CI, both halves, by family
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "research"))

from mt5bt import load_bars  # noqa: E402
from mt5bt.nulls import garch_walk  # noqa: E402
from till_infinity.models.shocks_train import auc  # noqa: E402

OUT = Path(os.environ.get("OUT", ".data/expansion"))
SEQLAB = os.environ.get("SEQLAB", ".data/seqlab")
SECONDS = {"15m": 900, "1h": 3600}
BOX, WAIT, FOLLOW = 16, 16, 48
RNG = np.random.default_rng(23)


def sigma(bars: pd.DataFrame) -> np.ndarray:
    h, l, c = (np.log(bars[k].to_numpy()) for k in ("high", "low", "close"))
    prev = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(abs(h - prev), abs(l - prev)))
    return pd.Series(tr).ewm(alpha=1 / 14, adjust=False).mean().to_numpy()


def follow(h, l, c, b: int, s: int, edge: float, other: float, W: float) -> dict | None:
    """From bar b's close, side s: the first of +1W past `edge` and the `other` edge."""
    n = len(c)
    if b + 1 >= n:
        return None
    goal = edge + s * W
    cb = c[b]
    d_goal, d_other = s * (goal - cb), s * (cb - other)
    if d_goal <= 0 or d_other <= 0:  # already past +1W, or back inside past the other edge
        return None
    out = dict(p_null=d_other / (d_goal + d_other), outcome="stall", t=FOLLOW)
    mfe = mae = 0.0
    for k in range(b + 1, min(n, b + 1 + FOLLOW)):
        fav = (h[k] - cb) if s > 0 else (cb - l[k])
        adv = (cb - l[k]) if s > 0 else (h[k] - cb)
        mfe, mae = max(mfe, fav), max(mae, adv)
        hit_goal = (h[k] >= goal) if s > 0 else (l[k] <= goal)
        hit_other = (l[k] <= other) if s > 0 else (h[k] >= other)
        if hit_goal and hit_other:  # one bar through both: the bar cannot say; the worse case
            out.update(outcome="whipsaw", t=k - b)
            break
        if hit_other:
            out.update(outcome="whipsaw", t=k - b)
            break
        if hit_goal:
            out.update(outcome="clean", t=k - b)
            break
    excur = max(h[b:min(n, b + 1 + FOLLOW)].max() - edge, 0) if s > 0 else max(edge - l[b:min(n, b + 1 + FOLLOW)].min(), 0)
    out.update(BQ=excur / W, WD=mae / mfe if mfe > 0 else np.inf)
    return out


def events(bars: pd.DataFrame, arms: np.ndarray, extra: dict | None = None) -> list[dict]:
    o, h, l, c = (bars[k].to_numpy() for k in ("open", "high", "low", "close"))
    vol = bars["volume"].to_numpy() if "volume" in bars else np.zeros(len(c))
    sig = sigma(bars) * c
    hi = pd.Series(h).rolling(BOX).max().to_numpy()
    lo = pd.Series(l).rolling(BOX).min().to_numpy()
    lv = np.log(np.maximum(vol, 1))
    vmean = pd.Series(lv).rolling(50, min_periods=20).mean().to_numpy()
    vsd = pd.Series(lv).rolling(50, min_periods=20).std().to_numpy()
    out, last = [], -BOX
    for i in np.sort(arms):
        if i - last < BOX or np.isnan(hi[i]) or i + 2 >= len(c):
            continue
        last = i
        H, L = hi[i], lo[i]
        W = H - L
        if W <= 0:
            continue
        for b in range(i + 1, min(len(c), i + 1 + WAIT)):
            up, dn = h[b] > H, l[b] < L
            if not (up or dn):
                continue
            base = dict(arm=i, b=b, W_sig=W / sig[i], wait=b - i,
                        bar_range=(h[b] - l[b]) / sig[i],
                        closed_out=float(c[b] > H or c[b] < L),
                        vol_z=(lv[b] - vmean[b]) / vsd[b] if vsd[b] > 0 else np.nan,
                        **(extra or {}).get(i, {}))
            if up and dn:
                out.append(base | dict(side=0, outcome="both", second=False))
                break
            s = 1 if up else -1
            edge, other = (H, L) if s > 0 else (L, H)
            got = follow(h, l, c, b, s, edge, other, W)
            if got is None:
                break
            ev = base | dict(side=s, second=False) | got
            out.append(ev)
            if got["outcome"] == "whipsaw":  # the refractory question: the second breakout
                b2 = b + got["t"]
                again = follow(h, l, c, b2, -s, other, edge, W)
                if again is not None:
                    out.append(base | dict(side=-s, second=True, b=b2) | again)
            break
    return out


def summarise(ev: pd.DataFrame, by: str | None = None) -> dict:
    ev = ev[ev["outcome"] != "both"]
    if ev.empty:
        return {}
    clean = (ev["outcome"] == "clean").to_numpy(float)
    excess = clean - ev["p_null"].to_numpy()
    day = ev["day"].to_numpy()
    days = np.unique(day)
    groups = [np.flatnonzero(day == d) for d in days]
    boots = []
    for _ in range(500):
        pick = np.concatenate([groups[k] for k in RNG.integers(0, len(groups), len(groups))])
        boots.append(excess[pick].mean())
    half = ev["half"].to_numpy()
    return dict(n=len(ev), clean=round(clean.mean(), 4),
                whipsaw=round(float((ev["outcome"] == "whipsaw").mean()), 4),
                stall=round(float((ev["outcome"] == "stall").mean()), 4),
                p_null=round(float(ev["p_null"].mean()), 4),
                excess=round(float(excess.mean()), 4),
                ci=[round(float(np.percentile(boots, 2.5)), 4), round(float(np.percentile(boots, 97.5)), 4)],
                halves=[round(float(excess[half == 0].mean()), 4), round(float(excess[half == 1].mean()), 4)],
                BQ_median=round(float(ev["BQ"].median()), 3),
                WD_median=round(float(ev["WD"].replace(np.inf, np.nan).median()), 3),
                T_commit_median=float(ev.loc[ev["outcome"] == "clean", "t"].median()),
                both_in_bar=None)


FEATURES = ["bar_range", "closed_out", "vol_z", "wait", "W_sig", "lift"]


def precursors(ev: pd.DataFrame) -> dict:
    ev = ev[ev["outcome"].isin(["clean", "whipsaw"]) & ~ev["second"]]
    y = (ev["outcome"] == "clean").to_numpy(float)
    out = {}
    for f in FEATURES:
        if f in ev and ev[f].notna().sum() > 100:
            m = ev[f].notna().to_numpy()
            a = auc(y[m], ev[f].to_numpy()[m])
            out[f] = round(a, 4)
    # the martingale's own geometry predicts the outcome; what matters is excess, so also the
    # AUC of p_null alone
    out["p_null_geometry"] = round(auc(y, ev["p_null"].to_numpy()), 4)
    try:
        from sklearn.ensemble import HistGradientBoostingClassifier
        cols = [f for f in FEATURES if f in ev and ev[f].notna().any()] + ["p_null"]
        X = ev[cols].to_numpy(float)
        tr = ev["half"].to_numpy() == 0
        if tr.sum() > 500 and (~tr).sum() > 200:
            gb = HistGradientBoostingClassifier(max_depth=3, max_iter=150, learning_rate=0.05,
                                                min_samples_leaf=200).fit(X[tr], y[tr])
            out["gb_all_second_half"] = round(auc(y[~tr], gb.predict_proba(X[~tr])[:, 1]), 4)
            geo = HistGradientBoostingClassifier(max_depth=3, max_iter=150, learning_rate=0.05,
                                                 min_samples_leaf=200).fit(X[tr][:, [-1]], y[tr])
            out["gb_geometry_only_second_half"] = round(auc(y[~tr], geo.predict_proba(X[~tr][:, [-1]])[:, 1]), 4)
    except (ImportError, ValueError) as exc:
        out["gb_error"] = str(exc)[:80]
    return out


def main() -> None:
    pred = pd.read_csv(OUT / "test_predictions.csv")
    pred = pred[pred["test"] & (pred["kind"] == "real")]
    wf = json.loads((OUT / "expansion_wf.json").read_text())
    pred["lift"] = pred["p"] / wf["base_rate"]
    rows = []
    for key, g in pred.groupby("key"):
        sym, iv = key.split("|")
        try:
            bars = load_bars(sym, iv, "seqlab", SEQLAB)
        except (OSError, ValueError):
            continue
        ts = bars["ts"].to_numpy()
        idx = np.searchsorted(ts, (g["when"].to_numpy() - SECONDS[iv]).astype(np.int64))
        ok = (idx < len(ts)) & (ts[np.minimum(idx, len(ts) - 1)] == g["when"].to_numpy() - SECONDS[iv])
        g, idx = g[ok], idx[ok]
        lift = g["lift"].to_numpy()
        mid = np.median(idx)
        extra = {int(i): {"lift": float(x)} for i, x in zip(idx, lift, strict=True)}
        for group, arms in (("A", idx[lift >= 2.5]), ("Q", idx[lift < 1.0]), ("all", idx)):
            for e in events(bars, arms, extra):
                e.update(group=group, key=key, family=g["family"].iloc[0],
                         day=int(ts[e["arm"]] // 86400), half=int(e["arm"] >= mid))
                rows.append(e)
    ev = pd.DataFrame(rows)
    ev["second"] = ev["second"].fillna(False).astype(bool)
    res = {"events": len(ev)}
    for group in ("A", "Q", "all"):
        e = ev[ev["group"] == group]
        res[f"{group}/first"] = summarise(e[~e["second"].astype(bool)])
        res[f"{group}/first"]["both_in_bar"] = round(float((e["outcome"] == "both").mean()), 4)
        res[f"{group}/second_after_whipsaw"] = summarise(e[e["second"].astype(bool)])
        res[f"{group}/by_family"] = {f: summarise(x[~x["second"].astype(bool)]).get("excess")
                                     for f, x in e.groupby("family")}
    res["precursors_all"] = precursors(ev[ev["group"] == "all"])
    print(json.dumps(res, indent=1), flush=True)

    walk_rows = []
    for w in range(12):
        bars = garch_walk(30_000, interval="15m", spread_points=8.0, seed=1300 + w)
        s = sigma(bars)
        pct = pd.Series(s).rolling(1500, min_periods=300).rank(pct=True).to_numpy()
        arms = np.flatnonzero((pct <= 0.2) & (np.arange(len(s)) > 18_000))
        for e in events(bars, arms):
            e.update(group="walk", key=f"walk{w}", family="walk", day=int(bars["ts"].iat[e["arm"]] // 86400),
                     half=int(e["arm"] >= 24_000), lift=np.nan)
            walk_rows.append(e)
    wv = pd.DataFrame(walk_rows)
    wv["second"] = wv["second"].fillna(False).astype(bool)
    res["walks/first"] = summarise(wv[~wv["second"].astype(bool)])
    res["walks/second_after_whipsaw"] = summarise(wv[wv["second"].astype(bool)])
    res["walks/precursors"] = precursors(wv.assign(lift=0.0))
    print(json.dumps({k: v for k, v in res.items() if k.startswith("walks")}, indent=1), flush=True)
    (OUT / "escape.json").write_text(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    main()
