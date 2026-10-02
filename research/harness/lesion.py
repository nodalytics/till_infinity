"""F9 (research/docs/ideas.md): do abnormal bars before a level touch ("lesions") foretell a break?

The trade idea: take level breaks only where the market's morphology was abnormal before the touch.
Its first test, as the backlog wrote it: break rate and push with and without the lesion, against
what the engine already knows at the touch. Trades only if the lesion adds information.

Pre-registered (2026-10-02), before any run.

  rows      the structures engine's resolved touches in the lab's journal snapshot (`outcome` by
            `structures`), at 15m and 1h, on instruments the lab holds bars for; label: break
            (outcome == "break") against everything else
  baseline  the engine's own features known at the touch: approach_vol, slope, prior_slope,
            slowing, strength, experience, confluence_n, base_rate_up, probability_up, up_rate,
            interval_log, side
  lesion    from the 8 bars before the touch on its own interval, the largest robust z (against the
            100 bars before: (x - median) / 1.4826 MAD) of bar range, tick volume and spread, and
            the count of bars with any |z| > 3
  timing    the outcome entry is stamped when the touch resolved; the touch began `seconds` earlier,
            and only bars closed by then are read (a first run read up to the resolution, which
            includes the breakout itself, and showed a spurious +0.11)
  judged    gradient boosting, each instrument's first 60% by time trains; AUC of baseline against
            baseline + lesion, both halves of the rest; counts if it adds >= 0.005 in both halves
            and the placebo (lesion values shuffled within the instrument) does not
  also      break rate and median push (push_vol) among breaks, with a lesion (any |z| > 3) and
            without; per family
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research" / "harness"))
sys.path.insert(0, str(ROOT))

from till_infinity.models.shocks_train import auc  # noqa: E402

OUT = Path(os.environ.get("OUT", ".data/lesion"))
JOURNAL = os.path.expanduser(os.environ.get("JOURNAL", "~/till_infinity/data/journal.db"))
SEQLAB = Path(os.environ.get("SEQLAB", ".data/seqlab"))
SECONDS = {"15m": 900, "1h": 3600}
BASE = ["approach_vol", "slope", "prior_slope", "slowing", "strength", "experience", "confluence_n",
        "base_rate_up", "probability_up", "up_rate", "interval_log", "side_up"]
LESION = ["range_z", "volume_z", "spread_z", "abnormal_bars"]


def symbol_files() -> dict[str, str]:
    """Journal feed slug -> lab bar-file symbol."""
    from mt5fill import REAL
    out = {}
    for f in SEQLAB.glob("*.15m.npz"):
        sym = f.name[: -len(".15m.npz")]
        base = sym.split(".")[0]
        out[REAL.get(base, sym.lower())] = sym
        out[sym.lower()] = sym
    return out


def robust_z(x: pd.Series, n: int = 100) -> pd.Series:
    med = x.rolling(n, min_periods=30).median().shift(1)
    mad = (x - med).abs().rolling(n, min_periods=30).median().shift(1) * 1.4826
    return (x - med) / mad.replace(0, np.nan)


def lesions(sym: str, iv: str) -> pd.DataFrame | None:
    f = SEQLAB / f"{sym}.{iv}.npz"
    if not f.exists():
        return None
    z = np.load(f)
    df = pd.DataFrame({k: z[k] for k in z.files if k in ("time", "high", "low", "close", "volume", "spread")})
    df = df.drop_duplicates("time").sort_values("time").reset_index(drop=True)
    rng = np.log(df["high"] / df["low"]).replace([np.inf, -np.inf], np.nan)
    zs = {"range": robust_z(rng).abs(), "volume": robust_z(np.log(df["volume"].clip(lower=1))).abs()}
    if "spread" in df:
        zs["spread"] = robust_z(df["spread"].astype(float)).abs()
    out = pd.DataFrame({"time": df["time"].astype(np.int64) + SECONDS[iv]})  # keyed by bar close
    for k, v in zs.items():
        out[f"{k}_z"] = v.rolling(8, min_periods=4).max().to_numpy()
    any3 = pd.concat([v > 3 for v in zs.values()], axis=1).any(axis=1).astype(float)
    out["abnormal_bars"] = any3.rolling(8, min_periods=4).sum().to_numpy()
    for k in LESION:
        if k not in out:
            out[k] = np.nan
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    smap = symbol_files()
    c = sqlite3.connect(f"file:{JOURNAL}?mode=ro", uri=True)
    rows = []
    for t, ctx in c.execute("select time, context from entries where kind='outcome' and actor='structures'"):
        d = json.loads(ctx)
        if d.get("interval") not in SECONDS or d.get("feed") not in smap:
            continue
        d["time"] = t
        rows.append(d)
    df = pd.DataFrame(rows)
    df["side_up"] = (df["side"].astype(str).str.lower().str.contains("up|above|resist")).astype(float)
    df["y"] = (df["outcome"].astype(str).str.lower() == "break").astype(float)
    print(f"{len(df):,} touches at 15m/1h on {df['feed'].nunique()} instruments; break rate {df['y'].mean():.3f}", flush=True)
    parts = []
    for (feed, iv), g in df.groupby(["feed", "interval"]):
        les = lesions(smap[feed], iv)
        if les is None:
            continue
        # the outcome's time is when the touch *resolved*; it began `seconds` earlier. The lesion is
        # read only from bars that had closed by then - never from the move that resolved it.
        g = g.assign(touch=(g["time"] - pd.to_numeric(g["seconds"], errors="coerce").fillna(0)).astype(np.int64))
        g = g.sort_values("touch")
        m = pd.merge_asof(g, les.rename(columns={"time": "bar_close"}).sort_values("bar_close"),
                          left_on="touch", right_on="bar_close", direction="backward")
        cut = m["time"].quantile(0.6)
        m["train"] = m["time"] < cut
        te = ~m["train"]
        m["second"] = te & (m["time"] >= m.loc[te, "time"].median())
        # placebo: the lesion values shuffled within the instrument and interval
        perm = np.random.default_rng(7).permutation(len(m))
        for k in LESION:
            m[f"{k}_placebo"] = m[k].to_numpy()[perm]
        parts.append(m)
    d = pd.concat(parts, ignore_index=True)
    for k in BASE:
        d[k] = pd.to_numeric(d.get(k), errors="coerce")
    from sklearn.ensemble import HistGradientBoostingClassifier
    tr, te = d["train"].to_numpy(), ~d["train"].to_numpy()
    s2 = d["second"].to_numpy()[te]
    y = d["y"].to_numpy()

    def score(cols):
        X = d[cols].to_numpy(float)
        X[:, np.all(np.isnan(X[tr]), axis=0)] = 0.0  # an empty column breaks the binning
        m = HistGradientBoostingClassifier(max_depth=4, max_iter=200, learning_rate=0.05,
                                           min_samples_leaf=200).fit(X[tr], y[tr])
        p = m.predict_proba(X[te])[:, 1]
        yt = y[te]
        return dict(auc=round(auc(yt, p), 4), halves=[round(auc(yt[~s2], p[~s2]), 4), round(auc(yt[s2], p[s2]), 4)])

    res = {"touches": len(d), "train": int(tr.sum()), "break_rate": round(float(y.mean()), 4),
           "coverage": {k: round(float(d[k].notna().mean()), 3) for k in LESION}}
    res["baseline"] = score(BASE)
    res["baseline_plus_lesion"] = score(BASE + LESION)
    res["baseline_plus_placebo"] = score(BASE + [f"{k}_placebo" for k in LESION])
    b, l, p = res["baseline"], res["baseline_plus_lesion"], res["baseline_plus_placebo"]
    res["counts"] = bool(min(l["halves"][i] - b["halves"][i] for i in (0, 1)) >= 0.005
                         and not min(p["halves"][i] - b["halves"][i] for i in (0, 1)) >= 0.005)
    lesioned = d["abnormal_bars"] > 0
    res["break_rate"] = {"with_lesion": round(float(d.loc[lesioned, "y"].mean()), 4),
                         "without": round(float(d.loc[~lesioned, "y"].mean()), 4),
                         "share_lesioned": round(float(lesioned.mean()), 3)}
    pv = pd.to_numeric(d.get("push_vol"), errors="coerce")
    res["push_among_breaks"] = {"with_lesion": round(float(pv[lesioned & (d["y"] > 0)].median()), 3),
                                "without": round(float(pv[~lesioned & (d["y"] > 0)].median()), 3)}
    res["single_auc_test"] = {k: round(auc(y[te & d[k].notna().to_numpy()],
                                             d.loc[te & d[k].notna().to_numpy(), k].to_numpy()), 4) for k in LESION}
    print(json.dumps(res, indent=1), flush=True)
    (OUT / "lesion.json").write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
