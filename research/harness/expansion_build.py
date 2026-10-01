"""Re-validate the compression-to-expansion alert on production's compact features, then ship it.

research/docs/fractal-twins.md found expansion from compression predictable (GB AUC 0.728 / 0.738)
on 288 raw window values, with Deriv's indices as the control. Deriv is a market, not a control,
and production cannot keep those windows, so this re-runs the question through the production
class (`structures/learning/expansion.py`) on the lab's broker bars, against walks we generate.

Pre-registered (2026-10-01), before any run (4h and 1d added the same day, judged by the same
gates per interval: an interval is read in production only if its real-market AUC is >= 0.68 in
both halves):
  1. real-market held-out AUC >= 0.68, in both halves of the held-out period
  2. real-market AUC beats our iid t walks by >= 0.10 (some walk skill is mechanical: a deep
     compression takes longer to climb back)
  3. top-decile calibration (realised over predicted) within 0.7-1.4
  GARCH walks are reported, not gated: the share of the skill that is plain volatility clustering.

Walk-forward: every series' first 60% by time trains, its last 40% scores. Writes
  $OUT/report.json          the scores
  $OUT/test_predictions.csv the held-out probabilities, for the B1/F2 backtests
  $OUT/expansion_wf.json    the walk-forward model (trained on the 60%)
  $OUT/expansion.json       the model to ship: everything but the last 14 days, as the contest does

  ./.secrets/lab.sh run research/harness/expansion_build.py SEQLAB=$HOME/till_infinity/data/seqlab
"""
from __future__ import annotations

import glob
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from till_infinity.models import expansion_train as et  # noqa: E402
from till_infinity.prices.models import Bar  # noqa: E402
from till_infinity.shared import frozen  # noqa: E402

SEQLAB = Path(os.environ.get("SEQLAB", ".data/seqlab"))
OUT = Path(os.environ.get("OUT", ".data/expansion"))
FAMILIES = {
    "fx": ["EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDCAD", "USDCHF", "USDJPY", "EURJPY", "GBPJPY",
           "EURGBP", "AUDJPY", "EURAUD", "CHFJPY", "EURCHF", "USDCNH"],
    "metal": ["XAUUSD", "XAGUSD"],
    "crypto": ["BTCUSD", "ETHUSD", "SOLUSD"],
    "stock": ["AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA", "JPM", "XOM", "AMD", "NFLX",
              "AVGO", "COST", "LLY", "UNH", "V", "MA", "BAC", "WMT", "ORCL"],
    "deriv": ["Volatility_25_Index", "Volatility_75_Index", "Jump_50_Index", "Step_Index",
              "Boom_1000_Index", "Crash_1000_Index", "Range_Break_100_Index",
              "Drift_Switch_Index_10"],
}
FAMILY = {s: f for f, ss in FAMILIES.items() for s in ss}


def find(sym: str, iv: str) -> Path | None:
    exact = SEQLAB / f"{sym}.{iv}.npz"
    if exact.exists():
        return exact
    got = sorted(glob.glob(str(SEQLAB / f"{sym}.*.{iv}.npz")))
    return Path(got[0]) if got else None


def load(sym: str, iv: str) -> list[Bar]:
    path = find(sym, iv)
    if path is None:
        return []
    z = np.load(path)
    df = pd.DataFrame({k: z[k] for k in ("time", "open", "high", "low", "close", "volume")})
    df = df.drop_duplicates("time").sort_values("time")
    df["high"] = df[["open", "high", "close"]].max(axis=1)
    df["low"] = df[["open", "low", "close"]].min(axis=1)
    return [Bar(int(r.time), float(r.open), float(r.high), float(r.low), float(r.close),
                float(r.volume) if r.volume > 0 else None) for r in df.itertuples(index=False)]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    started = time.time()
    series = {}
    for sym in FAMILY:
        for iv in ("15m", "1h", "4h", "1d"):
            bars = load(sym, iv)
            if len(bars) > 2_000:
                series[(sym, iv)] = bars
    print(f"{len(series)} series loaded ({time.time() - started:.0f}s)", flush=True)
    scored_ivs = tuple((os.environ.get("SCORED") or "15m,1h").split(","))
    rows = et.dataset(series, intervals=scored_ivs)
    wbars = int(os.environ.get("WALK_BARS", "20000"))  # 1d needs long walks to warm
    walks = et.walks(8, wbars) | et.walks(8, wbars, garch=True)
    wrows = et.dataset(walks, intervals=scored_ivs)
    when, kinds, x, y = rows.arrays()
    keys = np.array(rows.key)
    fam = np.array([FAMILY.get(k.split("|")[0], "?") for k in keys])
    iv = np.array([k.split("|")[1] for k in keys])
    print(f"{len(y):,} compressed rows, base rate {y.mean():.3f} ({time.time() - started:.0f}s)",
          flush=True)

    # walk-forward: each series' first 60% of compressed rows by time trains
    train = np.zeros(len(y), bool)
    second = np.zeros(len(y), bool)
    for k in np.unique(keys):
        m = np.flatnonzero(keys == k)
        cut = np.quantile(when[m], 0.6)
        train[m] = when[m] < cut
        test_m = m[when[m] >= cut]
        if len(test_m):
            second[test_m] = when[test_m] >= np.median(when[test_m])
    test = ~train
    spec = et.train(x[train], y[train])
    model = spec.pop("_sklearn")
    trees = frozen.Trees(spec)
    sample = x[test][:5000]
    exact = float(np.max(np.abs(np.array([trees.predict(list(r)) for r in sample])
                                - model.predict_proba(sample)[:, 1])))
    p = model.predict_proba(np.where(np.isnan(x), np.nan, x))[:, 1]
    _, wk, wx, wy = wrows.arrays()
    wp = model.predict_proba(wx)[:, 1]

    def a(mask, pp=p, yy=y):
        return round(et.auc(yy[mask], pp[mask]), 4) if mask.sum() > 50 and 0 < yy[mask].mean() < 1 else None

    real = test & (kinds == "real")
    report = {
        "rows": int(len(y)), "train_rows": int(train.sum()), "test_rows": int(test.sum()),
        "base_rate_train": round(float(y[train].mean()), 4),
        "evaluator_max_diff": exact,
        "auc": {
            "real": a(real), "real_first_half": a(real & ~second), "real_second_half": a(real & second),
            "deriv": a(test & (kinds == "deriv")),
            "control_iid": a(wk == "control", wp, wy), "garch": a(wk == "garch", wp, wy),
        },
        "by_family": {f: a(test & (fam == f)) for f in FAMILIES},
        "by_interval": {i: a(real & (iv == i)) for i in ("15m", "1h", "4h", "1d")},
        "by_interval_halves": {i: [a(real & (iv == i) & ~second), a(real & (iv == i) & second)]
                               for i in ("15m", "1h", "4h", "1d")},
        "by_interval_deriv": {i: a(test & (kinds == "deriv") & (iv == i)) for i in ("15m", "1h", "4h", "1d")},
        "by_family_interval": {f"{f}|{i}": a(test & (fam == f) & (iv == i))
                               for f in FAMILIES for i in ("15m", "1h", "4h", "1d")},
        "baselines_real": {
            "pct_only": round(et.auc(y[real], -x[real, 0]), 4),
            "depth_only": round(et.auc(y[real], -x[real, 1]), 4),
        },
    }
    top = real & (p >= np.quantile(p[real], 0.9))
    report["top_decile_real"] = {
        "realised": round(float(y[top].mean()), 4), "predicted": round(float(p[top].mean()), 4),
        "calibration": round(float(y[top].mean() / p[top].mean()), 3),
        "lift": round(float(y[top].mean() / y[real].mean()), 3),
        "base_rate": round(float(y[real].mean()), 4),
    }
    ar, ai = report["auc"]["real"] or 0, report["auc"]["control_iid"] or 1
    report["gates"] = {
        "1_real_both_halves_ge_0.68": bool(min(report["auc"]["real_first_half"] or 0,
                                               report["auc"]["real_second_half"] or 0) >= 0.68),
        "2_real_minus_iid_ge_0.10": bool(ar - ai >= 0.10),
        "3_calibration_0.7_1.4": bool(0.7 <= report["top_decile_real"]["calibration"] <= 1.4),
    }
    spec["test"] = report["auc"]
    (OUT / "expansion_wf.json").write_text(json.dumps(spec, separators=(",", ":")))
    pd.DataFrame({"key": keys, "when": when, "kind": kinds, "family": fam, "test": test,
                  "p": p, "y": y}).to_csv(OUT / "test_predictions.csv", index=False)

    # the model to ship: everything but the last 14 days, as the retrain contest trains
    cut = when.max() - 14 * 86_400
    ship = et.train(x[when < cut], y[when < cut])
    ship.pop("_sklearn")
    ship["test"] = report["auc"]
    ship["holdout_from"] = pd.Timestamp(cut, unit="s", tz="UTC").isoformat()
    (OUT / "expansion.json").write_text(json.dumps(ship, separators=(",", ":")))
    (OUT / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    print(f"done in {time.time() - started:.0f}s")


if __name__ == "__main__":
    main()
