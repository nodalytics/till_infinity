"""Does ML raise the TA battery's winners? A meta-model choosing which indicator trades to take.

ta_battery.py's rules lose small and often and win 1.3-2.0R on average; the crypto trend rules
survived. Meta-labelling on the old strategies learned nothing (lopez-de-prado.md: AUC 0.541 on
markets and on walks). This asks it again of the battery, whose survivors have an edge to sharpen.

Pre-registered (2026-10-02), before any run.

  trades    every trade of the 21 rules (ta_battery.signals + EMA crosses) on every family and
            15m-1d, with the battery's exits, plus the same on 4 GARCH walks per timeframe
  features  known at the signal bar: ATR percentile (500 bars), the expansion alert's compression
            percentile (1,500 bars), trend efficiency (16 bars), distance from the 50-bar mean in
            ATR, RSI(14), the 16-bar return in ATR, range and tick-volume z (100 bars), hour and
            weekday, the side, and the rule, family and timeframe as categories
  model     one gradient-boosted regressor of R across everything, trained on each instrument's
            first half of trades by time, applied to the second half
  select    the top 30% of second-half trades by predicted R
  judged    on the second half: expectancy, win rate, average winner and loser, share >= 2R - for
            the selection, all trades, and 1,000 random 30% picks; per family and pooled. The same
            pipeline on the walks' trades is the control.
  counts if the selection lifts expectancy by >= 0.05R over all trades and beats >= 95% of random
            picks, pooled and in at least two families, and the walks show no such lift
"""
from __future__ import annotations

import json
import os
import sys
import zlib
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research" / "harness"))
sys.path.insert(0, str(ROOT / "research"))
sys.path.insert(0, str(ROOT))

import ta_battery as tb  # noqa: E402

OUT = Path(os.environ.get("OUT", ".data/ta_meta"))
SEQLAB = os.environ.get("SEQLAB", ".data/seqlab")
FEATS = ["atr_pct", "comp_pct", "efficiency", "dist50", "rsi14", "ret16", "range_z", "vol_z",
         "hour", "weekday", "side"]
CATS = ["rule", "family", "interval"]


def features(df: pd.DataFrame) -> pd.DataFrame:
    c, h, l = df["close"], df["high"], df["low"]
    a = tb.atr(df)
    lc = np.log(c)
    tr = np.log(h / l).replace([np.inf, -np.inf], np.nan)
    slow = tr.ewm(alpha=1 / 14, adjust=False).mean()
    path = lc.diff().abs().rolling(16).sum()
    t = pd.to_datetime(df["ts"], unit="s", utc=True)
    lv = np.log(df["volume"].clip(lower=1))
    return pd.DataFrame({
        "atr_pct": a.rolling(500, min_periods=100).rank(pct=True),
        "comp_pct": slow.rolling(1500, min_periods=300).rank(pct=True),
        "efficiency": (lc.diff(16).abs() / path.replace(0, np.nan)),
        "dist50": (c - c.rolling(50).mean()) / a,
        "rsi14": tb.rsi(c, 14),
        "ret16": (c - c.shift(16)) / a,
        "range_z": (tr - tr.rolling(100).mean()) / tr.rolling(100).std(),
        "vol_z": (lv - lv.rolling(100).mean()) / lv.rolling(100).std(),
        "hour": t.dt.hour, "weekday": t.dt.weekday,
    })


def one(job: tuple) -> pd.DataFrame | None:
    from mt5bt import Book, Costs, load_bars, load_specs, run
    from mt5bt.data import EXAMPLE_SPECS
    from mt5bt.nulls import garch_walk
    import energy as en

    kind, sym, fam, iv = job
    if kind == "walk":
        bars = garch_walk(20_000, interval=iv, spread_points=8.0, seed=int(sym))
        spec, name = EXAMPLE_SPECS["EURUSD"], f"walk{sym}"
    else:
        try:
            bars = load_bars(sym, iv, "seqlab", SEQLAB)
        except (OSError, ValueError):
            return None
        spec = en.spec_for(load_specs(os.environ.get("MT5BT_DB")), sym)
        if spec is None or len(bars) < 600:
            return None
        name = sym
    book = Book(name, bars, spec, iv, feed=sym.replace("_", " ").lower() if kind != "walk" else "eurusd")
    F = features(book.bars)
    parts = []
    for rule, sg in tb.signals(book.bars).items():
        od = tb.orders(book.bars, sg, False, zlib.crc32(f"{name}{iv}{rule}".encode()))
        if od.empty:
            continue
        t, _ = run(book, None, Costs(), equity=1e7, risk=0.001, one_per_symbol=True, signals={name: od})
        if t.empty:
            continue
        x = F.iloc[t["signal_bar"].to_numpy()].reset_index(drop=True)
        x["side"] = t["side"].to_numpy()
        x["R"], x["entry_ts"] = t["R"].to_numpy(), t["entry_ts"].to_numpy()
        x["rule"], x["family"], x["interval"], x["sym"], x["kind"] = rule, fam, iv, name, kind
        parts.append(x)
    print(f"  {kind} {name} {iv}", flush=True)
    return pd.concat(parts, ignore_index=True) if parts else None


def evaluate(d: pd.DataFrame, rng) -> dict:
    """Train on each instrument's first half, select the top 30% of its second half."""
    from sklearn.ensemble import HistGradientBoostingRegressor

    d = d.copy()
    d["half2"] = d["entry_ts"] >= d.groupby("sym")["entry_ts"].transform("median")
    X = d[FEATS].copy()
    for c in CATS:
        X[c] = d[c].astype("category").cat.codes
    tr, te = ~d["half2"].to_numpy(), d["half2"].to_numpy()
    for col in X.columns:  # a feature with no values (walks have no tick volume) breaks the binning
        if X.loc[tr, col].isna().all():
            X[col] = 0.0
    m = HistGradientBoostingRegressor(max_depth=4, max_iter=300, learning_rate=0.05, min_samples_leaf=200,
                                      categorical_features=[X.columns.get_loc(c) for c in CATS])
    m.fit(X[tr], d["R"].to_numpy()[tr])
    test = d[te].assign(pred=m.predict(X[te]))
    cut = test["pred"].quantile(0.7)
    sel = test[test["pred"] >= cut]

    def prof(x):
        R = x["R"].to_numpy()
        return dict(n=len(R), exp=round(float(R.mean()), 4), win=round(float((R > 0).mean()), 3),
                    avg_win=round(float(R[R > 0].mean()), 3) if (R > 0).any() else 0.0,
                    avg_loss=round(float(R[R <= 0].mean()), 3) if (R <= 0).any() else 0.0,
                    ge2=round(float((R >= 2).mean()), 3))

    rand = np.array([test["R"].to_numpy()[rng.choice(len(test), len(sel), replace=False)].mean()
                     for _ in range(1000)])
    out = dict(all=prof(test), selected=prof(sel),
               lift=round(float(sel["R"].mean() - test["R"].mean()), 4),
               beats_random=round(float((sel["R"].mean() > rand).mean()), 3),
               rank_corr=round(float(pd.Series(test["pred"]).corr(test["R"], method="spearman")), 4))
    out["by_family"] = {}
    for f, g in test.groupby("family"):
        s = g[g["pred"] >= cut]
        if len(s) > 30:
            out["by_family"][f] = dict(all_exp=round(float(g["R"].mean()), 4), sel_exp=round(float(s["R"].mean()), 4),
                                       sel_avg_win=round(float(s.loc[s["R"] > 0, "R"].mean()), 3),
                                       all_avg_win=round(float(g.loc[g["R"] > 0, "R"].mean()), 3), n_sel=len(s))
    return out


def main() -> None:
    import expansion_build as eb

    OUT.mkdir(parents=True, exist_ok=True)
    jobs = [("market", s, f, iv) for s, f in eb.FAMILY.items() for iv in tb.INTERVALS]
    jobs += [("walk", str(900 + k), "walk", iv) for k in range(4) for iv in tb.INTERVALS]
    saved = OUT / "trades.pkl.gz"
    if saved.exists() and os.environ.get("PART") == "report":
        d = pd.read_pickle(saved)  # our own output from the trade pass
    else:
        with ProcessPoolExecutor(int(os.environ.get("WORKERS", "48"))) as pool:
            parts = [p for p in pool.map(one, jobs) if p is not None]
        d = pd.concat(parts, ignore_index=True)
        d.to_pickle(saved)  # our own output
    rng = np.random.default_rng(113)
    res = {"trades_market": int((d["kind"] == "market").sum()), "trades_walk": int((d["kind"] == "walk").sum()),
           "market": evaluate(d[d["kind"] == "market"], rng), "walks": evaluate(d[d["kind"] == "walk"], rng)}
    mk = res["market"]
    fam_ok = sum(1 for v in mk["by_family"].values() if v["sel_exp"] - v["all_exp"] >= 0.05)
    res["counts"] = bool(mk["lift"] >= 0.05 and mk["beats_random"] >= 0.95 and fam_ok >= 2
                         and not (res["walks"]["lift"] >= 0.05 and res["walks"]["beats_random"] >= 0.95))
    print(json.dumps(res, indent=1), flush=True)
    (OUT / "ta_meta.json").write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
