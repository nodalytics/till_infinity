"""Does taker flow call the side of an expansion - beyond momentum, beyond chance, after costs?

buffer.py found, among compressed crypto bars that went on to expand, net taker flow over the
previous 16 bars calls the side of the next 16-bar move at AUC 0.558 (n = 5,153, held out). Flow is
information MT5 bars do not carry, and the program's verdict is that only new information carries
direction - so this is checked properly.

Pre-registered (2026-10-01), before any run. Binance USD-M perps (binance_archive.py), 12 symbols,
15m and 1h, 2023-03 on, each series' last 40% by time held out, both halves.

  rows       compressed bars (the production alert's definition), all of them and the alert's top
             (lift >= 2.5, from the walk-forward model trained on each series' first 60%)
  target     sign of the 16-bar return after the bar (all compressed rows, and those that expanded)
  signals    imb16 (net taker quote volume / total, 16 bars); ret16 (the 16-bar return: momentum,
             the baseline flow must beat); imb_resid (imb16 minus its fit on ret16, training rows);
             depth_asym; oi16
  tests      AUC of each sign; logistic on [ret16] against [ret16, imb16] on the held-out rows; the
             30-day placebo (each signal shifted 30 days within its series)
  counts if  imb_resid's AUC > 0.53 in both halves, and [ret16, imb16] beats [ret16] by >= 0.01,
             and the placebo is within 0.5 +- 0.01
  trades     only if it counts. I5: enter in the sign of imb_resid at the next open when compressed
             and the alert fires; stop 2 sigma, trail 2 sigma, 64 bars at most, no take-profit;
             B1-flow: the bracket's leg that agrees with flow only. Costs 0.05% a side (taker) and
             funding from the archive's 8-hourly rates. Against the same entries with a coin side.
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

import buffer as bf  # noqa: E402
from till_infinity.models import expansion_train as et  # noqa: E402
from till_infinity.models.shocks_train import auc  # noqa: E402

OUT = Path(os.environ.get("OUT", ".data/flowsign"))
H = 16


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    series, sens, closes = {}, {}, {}
    for sym in bf.SYMBOLS:
        for iv in ("15m", "1h", "4h", "1d"):
            k = bf.klines(sym, iv)
            if k is None or len(k) < 2000:
                continue
            series[(sym, iv)] = bf.bars_of(k)
            if iv in ("15m", "1h"):
                key = f"{sym}|{iv}"
                sens[key] = bf.sensors(sym, iv, k)
                closes[key] = k
    rows = et.dataset(series, intervals=("15m", "1h"))
    when, _, x, y = rows.arrays()
    keys = np.array(rows.key)
    keep = when >= bf.FROM
    when, x, y, keys = when[keep], x[keep], y[keep], keys[keep]
    cols = ["imb16", "ret16_sig", "depth_asym", "oi16"]
    S = np.full((len(y), len(cols)), np.nan)
    fwd = np.full(len(y), np.nan)
    train = np.zeros(len(y), bool)
    second = np.zeros(len(y), bool)
    for key in np.unique(keys):
        m = np.flatnonzero(keys == key)
        S[m] = sens[key].reindex(when[m]).reindex(columns=cols).to_numpy()
        k = closes[key]
        lc = pd.Series(np.log(k["close"].to_numpy()), index=k["time"].astype(np.int64).to_numpy() + bf.SECONDS[key.split("|")[1]])
        fwd[m] = (lc.shift(-H) - lc).reindex(when[m]).to_numpy()
        cut = np.quantile(when[m], 0.6)
        train[m] = when[m] < cut
        te_m = m[when[m] >= cut]
        second[te_m] = when[te_m] >= np.median(when[te_m])
    df = pd.DataFrame(S, columns=cols)
    df["key"], df["when"], df["y"], df["fwd"] = keys, when, y, fwd
    df["train"], df["second"] = train, second
    ok = train & df["imb16"].notna() & df["ret16_sig"].notna()
    beta = np.polyfit(df.loc[ok, "ret16_sig"], df.loc[ok, "imb16"], 1)
    df["imb_resid"] = df["imb16"] - np.polyval(beta, df["ret16_sig"])
    # the alert: the walk-forward model, trained on each series' first 60%
    from sklearn.ensemble import HistGradientBoostingClassifier
    gb = HistGradientBoostingClassifier(max_depth=4, max_iter=200, learning_rate=0.05,
                                        min_samples_leaf=200).fit(x[train], y[train])
    p = gb.predict_proba(x)[:, 1]
    df["lift"] = p / y[train].mean()

    def placebo(col):
        out = df[col].copy()
        for key in np.unique(keys):
            m = np.flatnonzero(keys == key)
            order = m[np.argsort(when[m])]
            shift = int(30 * 86400 / bf.SECONDS[key.split("|")[1]])
            out.iloc[order] = df[col].iloc[np.roll(order, shift)].to_numpy()
        return out

    res = {"rows": int(len(df)), "beta": [round(float(b), 4) for b in beta]}
    for subset, mask in (("compressed", ~df["train"]), ("expanded", ~df["train"] & (df["y"] > 0.5)),
                         ("alert", ~df["train"] & (df["lift"] >= 2.5))):
        d = df[mask & df["fwd"].notna()]
        up = (d["fwd"] > 0).to_numpy(float)
        cell = {"n": len(d)}
        for col in ("imb16", "imb_resid", "ret16_sig", "depth_asym", "oi16"):
            v = d[col].to_numpy()
            okv = ~np.isnan(v)
            pl = placebo(col)[d.index].to_numpy()
            okp = ~np.isnan(pl)
            s2 = d["second"].to_numpy()
            cell[col] = dict(auc=round(auc(up[okv], v[okv]), 4),
                             halves=[round(auc(up[okv & ~s2], v[okv & ~s2]), 4),
                                     round(auc(up[okv & s2], v[okv & s2]), 4)],
                             placebo=round(auc(up[okp], pl[okp]), 4))
        # does flow add to momentum? logistic fit on the held-out first half, scored on the second
        from sklearn.linear_model import LogisticRegression
        z = d[["ret16_sig", "imb16"]].dropna()
        uz = (d.loc[z.index, "fwd"] > 0).to_numpy(int)
        s2z = d.loc[z.index, "second"].to_numpy()
        if (~s2z).sum() > 100 and s2z.sum() > 100:
            m1 = LogisticRegression().fit(z[["ret16_sig"]][~s2z], uz[~s2z])
            m2 = LogisticRegression().fit(z[~s2z], uz[~s2z])
            cell["momentum_only"] = round(auc(uz[s2z], m1.predict_proba(z[["ret16_sig"]][s2z])[:, 1]), 4)
            cell["momentum_plus_flow"] = round(auc(uz[s2z], m2.predict_proba(z[s2z])[:, 1]), 4)
        res[subset] = cell
        print(subset, json.dumps(cell), flush=True)
    c = res["compressed"]["imb_resid"]
    res["counts"] = bool(min(c["halves"]) > 0.53
                         and res["compressed"].get("momentum_plus_flow", 0) - res["compressed"].get("momentum_only", 0) >= 0.01
                         and abs(c["placebo"] - 0.5) <= 0.01)
    print("counts:", res["counts"], flush=True)
    df.to_csv(OUT / "rows.csv", index=False)
    (OUT / "flowsign.json").write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
