"""Does bar range and tick volume improve the shock forecaster? Old model against new, same rows.

research/docs/infoflow.md found bar range and tick-volume z to be the only inputs carrying
information about the next bar's size beyond the production state; vpin.md found plain volume adds
+0.0145 AUC to the forecaster. `structures/learning/shocks.py` now adds `range_vol`, `volume_z`
and `volume_z_hour`. This decides whether the model trained on them ships, on identical rows:

  old        the shipped model (old recipe), fed the first 11 features
  fresh      a model retrained now on the old 11 features - separates the gain from freshness
  new        a model retrained now on all 14 features

Two splits, both on the same replay of the lab's bars through production code (`shocks_train`):
  holdout   the last 14 days, as the retrain contest judges, halves = its two weeks
  60/40     trained on the first 60% by time, scored on the last 40%, halves = its two 20%s

Families: FX, metals, crypto (real), Deriv's Boom/Crash, Jump and Volatility (a market, tick
volume only), and GARCH walks we generate (no volume, so the volume features are NaN and must not
help) and iid walks. AUC with day-bootstrap intervals, top-decile lift, top-decile calibration.

Pre-registered ship rule: `new` beats `old` on pooled real markets by at least the contest's slack
(max(0.01, 2 se)) on the 14-day holdout, positive in both of its halves, beats `fresh` in the
60/40 split in both halves, and passes the retrain gates (real AUC >= 0.65, control within 0.03 of
0.5 on our walks, calibration 0.7-1.4, exact export).

Run on the lab: SEQLAB=... python research/harness/shockvolume.py   (writes OUT/shocks.json)
"""
from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import spikerisk
from shockreplay import GROUPS

from till_infinity.models import shocks_train as st
from till_infinity.prices.models import Bar
from till_infinity.shared import frozen
from till_infinity.structures.learning import shocks as sh

OUT = Path(os.environ.get("OUT", ".data/shockvolume"))
PACKAGED = Path(__file__).resolve().parents[2] / "till_infinity" / "models" / "shocks.json"
OLD_N = 11
DAY = 86_400


def load(sym: str, iv: str) -> list[Bar]:
    df = spikerisk.load(None, sym, "SEQLAB", iv)
    vol = df["volume"].to_numpy() if "volume" in df else np.zeros(len(df))
    return [Bar(int(t), float(o), float(h), float(lo), float(c), float(v) if v > 0 else None)
            for t, o, h, lo, c, v in zip(df["ts"], df["open"], df["high"], df["low"], df["close"], vol,
                                         strict=True)]


def garch(walks: int = 6, bars: int = 30_000, seed: int = 3) -> dict:
    """GARCH(1,1) t(4) walks with no volume: clustering without the information volume carries."""
    rng = np.random.default_rng(seed)
    out = {}
    for w in range(walks):
        h, r, price, t, got = 1e-6, 0.0, 100.0, 1_700_000_000, []
        for _ in range(bars):
            h = 1e-8 + 0.08 * r * r + 0.9 * h
            r = math.sqrt(h) * rng.standard_t(4) / math.sqrt(2)
            close = price * math.exp(r)
            wick = abs(rng.standard_t(4)) * math.sqrt(h) * 0.5
            got.append(Bar(t, price, max(price, close) * math.exp(wick),
                           min(price, close) * math.exp(-wick), close, None))
            price, t = close, t + 900
        out[(f"~garch-{w}", "15m")] = got
    return out


def family_of(key: str) -> str:
    sym = key.split("|", 1)[0]
    if sym.startswith("~garch"):
        return "garch walks"
    if sym.startswith(st.CONTROL):
        return "iid walks"
    for fam, syms in GROUPS.items():
        if sym in syms:
            return fam
    return "other"


def auc(y, p) -> float:
    return st.auc(np.asarray(y), np.asarray(p))


def boot_auc(y, p, days, reps=200, seed=0):
    uniq = np.unique(days)
    by = {d: np.flatnonzero(days == d) for d in uniq}
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(reps):
        idx = np.concatenate([by[d] for d in rng.choice(uniq, len(uniq))])
        vals.append(auc(y[idx], p[idx]))
    return float(np.nanstd(vals))


def lift(y, p):
    top = p >= np.quantile(p, 0.9)
    base = y.mean()
    return (y[top].mean() / base if base > 0 else float("nan"),
            y[top].mean() / max(p[top].mean(), 1e-9))


def compare(label, x, y, when, fam, train, held, old_spec):
    fresh = st.train(x[train][:, :OLD_N], y[train])
    fresh_model = fresh.pop("_sklearn")
    new = st.train(x[train], y[train])
    new_model = new.pop("_sklearn")
    sample = x[held][:5000]
    exact = float(np.max(np.abs(np.array([frozen.Trees(new).predict(list(r)) for r in sample])
                                - new_model.predict_proba(sample)[:, 1]))) if len(sample) else 0.0
    preds = {
        "old": np.array([frozen.Trees(old_spec).predict(list(r[:OLD_N])) for r in x[held]]),
        "fresh": fresh_model.predict_proba(x[held][:, :OLD_N])[:, 1],
        "new": new_model.predict_proba(x[held])[:, 1],
    }
    yy, ww, ff = y[held], when[held], fam[held]
    days = (ww // DAY).astype(int)
    mid = np.quantile(ww, 0.5)
    print(f"\n== {label}: train {int(train.sum()):,} rows, scored {int(held.sum()):,} | export max diff {exact:.1e}",
          flush=True)
    real = np.isin(ff, ["fx", "metals", "crypto"])
    rows = {}
    for name in ["real (pooled)", "fx", "metals", "crypto", "boom/crash", "jump", "volatility",
                 "garch walks", "iid walks"]:
        m = real if name == "real (pooled)" else ff == name
        if m.sum() < 200 or yy[m].sum() < 10:
            continue
        cells = []
        for k in ("old", "fresh", "new"):
            p = preds[k]
            a = auc(yy[m], p[m])
            cells.append(f"{k} {a:.4f}")
        a_new, a_old, a_fresh = (auc(yy[m], preds[k][m]) for k in ("new", "old", "fresh"))
        diff = preds["new"][m], preds["old"][m], preds["fresh"][m]
        se = boot_auc(yy[m], diff[0], days[m])
        h1, h2 = ww[m] < mid, ww[m] >= mid
        half_old = [auc(yy[m][h], diff[0][h]) - auc(yy[m][h], diff[1][h]) for h in (h1, h2)]
        half_fresh = [auc(yy[m][h], diff[0][h]) - auc(yy[m][h], diff[2][h]) for h in (h1, h2)]
        lf, cal = lift(yy[m], diff[0])
        rows[name] = {"new_minus_old": a_new - a_old, "new_minus_fresh": a_new - a_fresh, "se": se,
                      "halves_old": half_old, "halves_fresh": half_fresh, "new": a_new, "old": a_old,
                      "fresh": a_fresh, "calibration": cal, "lift": lf, "n": int(m.sum())}
        print(f"  {name:14s} n={int(m.sum()):7,} rate {yy[m].mean():.3f} | " + " | ".join(cells)
              + f" | new-old {a_new - a_old:+.4f} (se {se:.4f}) halves {half_old[0]:+.4f}/{half_old[1]:+.4f}"
              + f" | new-fresh {a_new - a_fresh:+.4f} halves {half_fresh[0]:+.4f}/{half_fresh[1]:+.4f}"
              + f" | top-decile lift {lf:.2f} calib {cal:.2f}", flush=True)
    return rows, new, exact


def main():
    old_spec = json.loads(PACKAGED.read_text())
    assert len(old_spec["names"]) == OLD_N, "the packaged model must be the old recipe"
    series = {}
    for iv in ("15m", "1h"):
        for fam, syms in GROUPS.items():
            for sym in syms:
                try:
                    got = load(sym, iv)
                except (ValueError, FileNotFoundError):
                    continue
                if len(got) > 2 * sh.NORM:
                    series[(sym, iv)] = got
    series.update(st.controls())
    series.update(garch())
    have_volume = sum(1 for k, b in series.items() if any(bar.volume for bar in b[-100:]))
    print(f"{len(series)} series ({have_volume} with volume)", flush=True)
    rows = st.dataset(series)
    when, _, x, y = rows.arrays()
    fam = np.array([family_of(k) for k in rows.key])
    print(f"{len(y):,} rows, shock-within-{sh.AHEAD} rate {y.mean():.3f}; volume_z present "
          f"{np.mean(~np.isnan(x[:, OLD_N + 1])):.1%}", flush=True)
    cut = when.max() - 14 * DAY
    hold, hold_new, exact = compare("14-day holdout (the contest's)", x, y, when, fam, when < cut, when >= cut,
                                    old_spec)
    split = np.quantile(when, 0.6)
    wf, _, _ = compare("60/40 walk-forward", x, y, when, fam, when < split, when >= split, old_spec)
    real = hold.get("real (pooled)", {})
    slack = max(0.01, 2 * real.get("se", 1.0))
    ship = (
        real.get("new_minus_old", -1) >= slack
        and all(v > 0 for v in real.get("halves_old", [-1]))
        and all(v > 0 for v in wf.get("real (pooled)", {}).get("halves_fresh", [-1]))
        and real.get("new", 0) >= 0.65
        and 0.7 <= real.get("calibration", 0) <= 1.4
        and abs(hold.get("iid walks", {}).get("new", 0.5) - 0.5) <= 0.03
        and exact <= 1e-9
    )
    print(f"\nship rule: new-old {real.get('new_minus_old', float('nan')):+.4f} >= slack {slack:.4f}, "
          f"both holdout halves, beats fresh in both 60/40 halves, gates -> {'SHIP' if ship else 'KEEP OLD'}",
          flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "report.json").write_text(json.dumps({"holdout": hold, "walkforward": wf, "ship": ship,
                                                 "slack": slack, "exact": exact}, default=float))
    hold_new["test"] = {k: v for k, v in real.items() if not isinstance(v, list)}
    (OUT / "shocks.json").write_text(json.dumps(hold_new, separators=(",", ":")))
    print(f"wrote {OUT}/shocks.json and report.json", flush=True)




# ------------------------------------------------------------------ PART=control


def control_walks(template: list[Bar], kind: str, seed: int) -> list[Bar]:
    """A GARCH(1,1) t(4) walk on `template`'s own timestamps (so it lands in both training and
    hold-out), with a synthetic tick volume:
      indep  independent of the returns (lognormal)
      echo   volume that only echoes the same bar's size: exp(5 + |r|/sqrt(h) + noise)"""
    rng = np.random.default_rng(seed)
    h, r, price, got = 1e-6, 0.0, 100.0, []
    for bar in template:
        h = 2e-8 + 0.08 * r * r + 0.9 * h
        r = math.sqrt(h) * rng.standard_t(4) / math.sqrt(2)
        close = price * math.exp(r)
        wick = abs(rng.standard_t(4)) * math.sqrt(h) * 0.5
        if kind == "indep":
            volume = math.exp(rng.normal(5.0, 0.5))
        else:
            volume = math.exp(5.0 + 0.7 * abs(r) / math.sqrt(h) + rng.normal(0.0, 0.3))
        got.append(Bar(bar.time, price, max(price, close) * math.exp(wick),
                       min(price, close) * math.exp(-wick), close, volume))
        price = close
    return got


def control() -> None:
    """Old features against old + range against all 14, on walks with real timing."""
    templates = {}
    for sym in ("EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "BTCUSD", "ETHUSD"):
        for iv in ("15m", "1h"):
            try:
                got = load(sym, iv)
            except (ValueError, FileNotFoundError):
                continue
            if len(got) > 2 * sh.NORM:
                templates[(sym, iv)] = got
    print(f"control: {len(templates)} real-timed templates", flush=True)
    for kind in ("indep", "echo"):
        series = {(f"~{kind}-{s}", iv): control_walks(b, kind, seed=hash((s, iv, kind)) % 2**31)
                  for (s, iv), b in templates.items()}
        rows = st.dataset(series)
        when, _, x, y = rows.arrays()
        cut = when.max() - 14 * DAY
        split = np.quantile(when, 0.6)
        print(f"\n== {kind} volume: {len(y):,} rows, shock rate {y.mean():.3f}", flush=True)
        for label, train, held in (("14-day holdout", when < cut, when >= cut),
                                   ("60/40", when < split, when >= split)):
            yy, ww = y[held], when[held]
            days = (ww // DAY).astype(int)
            mid = np.quantile(ww, 0.5)
            preds = {}
            for name, cols in (("old", list(range(OLD_N))), ("old+range", list(range(OLD_N + 1))),
                               ("all 14", list(range(x.shape[1])))):
                spec = st.train(x[train][:, cols], y[train])
                model = spec.pop("_sklearn")
                preds[name] = model.predict_proba(x[held][:, cols])[:, 1]
            base = auc(yy, preds["old"])
            out = [f"old {base:.4f}"]
            for name in ("old+range", "all 14"):
                p = preds[name]
                gain = auc(yy, p) - base
                diff_se = boot_auc(yy, p, days)
                halves = [auc(yy[h], p[h]) - auc(yy[h], preds["old"][h]) for h in (ww < mid, ww >= mid)]
                out.append(f"{name} {gain:+.4f} (se~{diff_se:.4f}) halves {halves[0]:+.4f}/{halves[1]:+.4f}")
            vol_only = auc(yy, preds["all 14"]) - auc(yy, preds["old+range"])
            out.append(f"volume beyond range {vol_only:+.4f}")
            print(f"  {label:15s} n={int(held.sum()):9,} | " + " | ".join(out), flush=True)


if __name__ == "__main__" and os.environ.get("PART") == "control":
    control()
elif __name__ == "__main__":
    main()
