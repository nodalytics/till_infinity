"""Can the boosted-quantile envelope be shipped, run the way production would run it?

`conformal.md` (Okita's section) found quantile boosting the best forecaster of the envelope: the
lowest pinball in all 18 family x horizon cells and regime-flat coverage. Boosting + AgACI fixed its
over-coverage at 50 bars but left weak worst slices in metals (78-82%). That was a single 60/40
fit. Production would instead freeze the models and retrain them every fortnight, so this
simulates exactly that and asks whether a shippable version beats production's envelope.

## What is compared, on the same rows

  prod     production's envelope: the last 1,000 resolved moves (the empirical quantiles),
           corrected by AgACI - `structures/vol/envelope.py`
  pooled   quantile boosting trained on every market family at once, read through AgACI
  fam      the same, one model set per family                                   (fix a)
  resid    per family, with the empirical quantiles q10/q50/q90 of the last 1,000 resolved moves
           as extra inputs, so the model adjusts the known-good base             (fix b)
  recent   per family, trained on the last 365 days only                         (fix c)
  fam5     per family, 5 quantile levels (0.05, 0.1, 0.5, 0.9, 0.95) instead of 9: the size test

Every model set is **retrained every 14 days on all resolved data before that day** (the retrain
pipeline's cadence) and quotes the next 14 days through AgACI, with AgACI reading between the
model's quantile levels. Quantile crossing is fixed by sorting, and the crossing rate before the
sort is reported (fix d). A **gated** stream (fix e) uses the selected variant in a 14-day window
only if, over the previous six windows (about 90 days), its worst window's P90 cover was at least
production's worst minus 1 point; otherwise it uses production's quotes.

The selected variant is the one with the lowest pinball relative to production over the **first
half** of the scored period, pooled across market families; its second half is the confirmation.

## Families, 15m, N = 5, 20, 50

FX, metals, crypto, and the Deriv families that are not quoted from a published law - Boom/Crash,
Range Break, DEX, Drift Switch - as markets. Volatility, Jump and Step quote their law in
production and are left out. Controls: iid t(3) walks and GARCH(1,1)-t walks, generated here.

## Pass bar, pre-registered

For a family and horizon it would ship for, the candidate must:
- beat production's pinball, with a day-bootstrap 95% interval of the difference below zero;
- have a worst slice (of 20, as conformal.py) no more than 1 point under production's;
- stay stable across retrains: no 14-day window's P90 cover more than 2 points under production's
  worst window;
- roughly tie on the iid walks, with the pinball difference within 1% of production's or its
  interval including zero.

Run on the lab:
  PART=run HORIZON=20 FAMILY=fx     SEQLAB=... python research/harness/gbmenvelope.py
  PART=run HORIZON=20 FAMILY=pooled ...
  PART=size ...      # export size and per-bar cost of the frozen models
  PART=report ...
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

sys.path.insert(0, str(Path(__file__).parent))
import conformal2 as c2
import envelope as env
import spikerisk

PART = os.environ.get("PART", "run")
H = int(os.environ.get("HORIZON", "20"))
FAMILY = os.environ.get("FAMILY", "fx")
OUT = Path(os.environ.get("OUT", ".data/gbmenvelope"))
INTERVAL = "15m"
BAR = 900
RETRAIN_DAYS = 14
LEVELS9 = (0.05, 0.1, 0.2, 0.3, 0.5, 0.7, 0.8, 0.9, 0.95)
LEVELS5 = (0.05, 0.1, 0.5, 0.9, 0.95)
FEATS = ["lvol", "r1", "r5", "r20", "rng", "hour"]
EQ = ["eq10", "eq50", "eq90"]
ROWS = int(os.environ.get("ROWS", "40000"))
ITER = int(os.environ.get("ITER", "120"))
PROD_WINDOW = 1000  # production's history depth (envelope.WINDOW)

FX = ["EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDCAD", "USDCHF", "USDJPY", "EURJPY", "GBPJPY",
      "EURGBP", "AUDJPY", "EURCHF", "CHFJPY", "EURAUD", "GBPCHF"]
FAMILIES = {
    "fx": FX,
    "metals": ["XAUUSD", "XAGUSD"],
    "crypto": ["BTCUSD", "ETHUSD", "SOLUSD"],
    "boomcrash": ["Boom_500_Index", "Boom_1000_Index", "Crash_500_Index", "Crash_1000_Index"],
    "rangebreak": ["Range_Break_100_Index", "Range_Break_200_Index"],
    "dex": ["DEX_600_UP_Index", "DEX_600_DOWN_Index", "DEX_900_UP_Index", "DEX_900_DOWN_Index",
            "DEX_1500_UP_Index", "DEX_1500_DOWN_Index"],
    "driftswitch": ["Drift_Switch_Index_10", "Drift_Switch_Index_20", "Drift_Switch_Index_30"],
    "walks_iid": [f"walkiid_{i}" for i in range(6)],
    "walks_garch": [f"walkgarch_{i}" for i in range(6)],
}
MARKETS = ["fx", "metals", "crypto", "boomcrash", "rangebreak", "dex", "driftswitch"]
VARIANTS = ["pooled", "fam", "resid", "recent", "fam5"]


# --------------------------------------------------------------------------------- the bars

def walk(sym: str, n: int | None = None) -> pd.DataFrame:
    """Walks we generate: iid t(3), or GARCH(1,1) with t(4) shocks. 15m, 24/7, from 2025-04-09."""
    n = n or int(os.environ.get("WALK_N", "50000"))
    kind, i = sym.split("_")
    rng = np.random.default_rng(1000 + int(i) + (500 if kind == "walkgarch" else 0))
    if kind == "walkiid":
        r = rng.standard_t(3, n) * 0.001
    else:
        r, s2, prev = np.empty(n), 1e-6, 0.0
        for t in range(n):
            s2 = 5e-8 + 0.08 * prev * prev + 0.87 * s2
            prev = r[t] = math.sqrt(s2) * rng.standard_t(4) / math.sqrt(2.0)
    close = 100 * np.exp(np.cumsum(r))
    open_ = np.r_[100.0, close[:-1]]
    scale = np.abs(r).mean()
    wick = np.abs(rng.standard_t(3, (n, 2))) * scale * 0.5
    t0 = int(pd.Timestamp("2025-04-09", tz="UTC").timestamp())
    return pd.DataFrame({"ts": t0 + BAR * np.arange(n), "open": open_, "close": close,
                         "high": np.maximum(open_, close) * np.exp(wick[:, 0]),
                         "low": np.minimum(open_, close) * np.exp(-wick[:, 1])})


def load(sym: str) -> pd.DataFrame:
    if sym.startswith("walk"):
        return walk(sym)
    return spikerisk.load(None, sym, "SEQLAB", INTERVAL)


def frame(sym: str) -> pd.DataFrame | None:
    """envelope.py's frame, with the time kept and the empirical quantiles added as features."""
    try:
        df = load(sym)
    except (ValueError, FileNotFoundError):
        return None
    o, h, lo, c = (np.log(df[k].to_numpy(dtype=float)) for k in ("open", "high", "low", "close"))
    prev = np.r_[np.nan, c[:-1]]
    tr = np.nanmax(np.column_stack([h - lo, np.abs(h - prev), np.abs(lo - prev)]), axis=1)
    sig = pd.Series(tr).ewm(alpha=1 / 14, adjust=False).mean().to_numpy()
    long = pd.Series(tr).rolling(500, min_periods=250).mean().to_numpy()
    r = np.diff(c, prepend=np.nan)
    d = pd.DataFrame({
        "ts": df["ts"].to_numpy(dtype=np.int64),
        "y": np.r_[c[H:] - c[:-H], np.full(H, np.nan)] / sig,
        "lvol": np.log(sig / long), "r1": r / sig,
        "r5": (c - np.r_[np.full(5, np.nan), c[:-5]]) / sig,
        "r20": (c - np.r_[np.full(20, np.nan), c[:-20]]) / sig,
        "rng": (h - lo) / sig,
        "hour": pd.to_datetime(df["ts"].to_numpy(), unit="s").hour, "sig": sig,
    })
    known = d["y"].shift(H)  # a move is known H bars after it starts
    for q, name in zip((0.1, 0.5, 0.9), EQ, strict=True):
        d[name] = known.rolling(PROD_WINDOW, min_periods=200).quantile(q)
    d["sym"] = sym
    return d.dropna(subset=["lvol", "r20"]).reset_index(drop=True)


def family_frames(fam: str) -> list[pd.DataFrame]:
    return [f for f in (frame(s) for s in FAMILIES[fam]) if f is not None and len(f) > 5_000]


def test_start(frames: list[pd.DataFrame]) -> int:
    """The last 40% of the family's time span is scored."""
    ts = np.concatenate([f["ts"].to_numpy() for f in frames])
    return int(np.quantile(ts, 0.6))


# --------------------------------------------------------------------------------- the models

def fit(x: pd.DataFrame, y: np.ndarray, levels, seed: int):
    if len(y) > ROWS:
        pick = np.random.default_rng(seed).choice(len(y), ROWS, replace=False)
        x, y = x.iloc[pick], y[pick]
    return [HistGradientBoostingRegressor(loss="quantile", quantile=q, max_depth=4, max_iter=ITER,
                                          learning_rate=0.05, min_samples_leaf=300).fit(x, y)
            for q in levels]


def walk_forward(train: pd.DataFrame, score: list[pd.DataFrame], feats, levels, start: int,
                 recent_days: float | None = None):
    """Per-row quantile predictions for every frame in `score`, each row from the model set
    trained on every row resolved before its 14-day window began. Returns (preds, crossing)."""
    preds = [np.full((len(f), len(levels)), np.nan) for f in score]
    crossed = total = 0
    end = max(int(f["ts"].max()) for f in score)
    t_w, k = start, 0
    resolved = train["ts"].to_numpy() + H * BAR
    while t_w <= end:
        ok = (resolved <= t_w) & train["y"].notna().to_numpy()
        if recent_days is not None:
            ok &= train["ts"].to_numpy() >= t_w - recent_days * 86_400
        models = fit(train.loc[ok, feats], train.loc[ok, "y"].to_numpy(), levels, seed=k)
        for f, p in zip(score, preds, strict=True):
            m = ((f["ts"] >= t_w) & (f["ts"] < t_w + RETRAIN_DAYS * 86_400)).to_numpy()
            if m.any():
                raw = np.column_stack([mod.predict(f.loc[m, feats]) for mod in models])
                crossed += int((np.diff(raw, axis=1) < 0).any(axis=1).sum())
                total += int(m.sum())
                p[m] = np.sort(raw, axis=1)
        t_w += RETRAIN_DAYS * 86_400
        k += 1
    return preds, crossed / max(total, 1)


def agaci(frames: list[pd.DataFrame], start: int, preds=None, levels=LEVELS9) -> dict:
    """AgACI's quotes on the scored rows, empirical (preds None) or reading the models."""
    c2.WINDOW = PROD_WINDOW
    keep = env.LEVELS
    env.LEVELS = levels
    out = {k: [] for k in ("y", "lvol", "ts", "q10", "q50", "q90")}
    try:
        for i, f in enumerate(frames):
            g = f.copy()
            g["test"] = g["ts"] >= start
            p = None if preds is None else preds[i]
            idx, q = c2.run(g, "agaci" if p is None else "gbm agaci", H, p)
            out["y"].append(g["y"].to_numpy()[idx])
            out["lvol"].append(g["lvol"].to_numpy()[idx])
            out["ts"].append(g["ts"].to_numpy()[idx])
            for t, name in zip((0.1, 0.5, 0.9), ("q10", "q50", "q90"), strict=True):
                out[name].append(q[t])
    finally:
        env.LEVELS = keep
    return {k: np.concatenate(v) for k, v in out.items()}


def save(fam: str, method: str, got: dict, start: int, crossing: float = float("nan")) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(OUT / f"{H}_{fam}_{method}.npz", start=start, crossing=crossing, **got)


def run_family(fam: str) -> None:
    frames = family_frames(fam)
    start = test_start(frames)
    allf = pd.concat(frames, ignore_index=True)
    print(f"{fam} H={H}: {len(frames)} series, {len(allf):,} rows, scored from "
          f"{pd.Timestamp(start, unit='s'):%Y-%m-%d}", flush=True)
    t0 = time.time()
    save(fam, "prod", agaci(frames, start), start)
    print(f"  prod done {time.time() - t0:.0f}s", flush=True)
    for method, feats, levels, recent in (("fam", FEATS, LEVELS9, None), ("resid", FEATS + EQ, LEVELS9, None),
                                          ("recent", FEATS, LEVELS9, 365.0), ("fam5", FEATS, LEVELS5, None)):
        preds, crossing = walk_forward(allf, frames, feats, levels, start, recent)
        save(fam, method, agaci(frames, start, preds, levels), start, crossing)
        print(f"  {method} done {time.time() - t0:.0f}s, crossing before sort {crossing:.2%}", flush=True)


def run_pooled() -> None:
    fams = {f: family_frames(f) for f in MARKETS}
    fams = {f: fr for f, fr in fams.items() if fr}
    starts = {f: test_start(fr) for f, fr in fams.items()}
    allf = pd.concat([x for fr in fams.values() for x in fr], ignore_index=True)
    score = [x for fr in fams.values() for x in fr]
    preds, crossing = walk_forward(allf, score, FEATS, LEVELS9, min(starts.values()))
    i = 0
    for f, fr in fams.items():
        mine = preds[i:i + len(fr)]
        i += len(fr)
        save(f, "pooled", agaci(fr, starts[f], mine, LEVELS9), starts[f], crossing)
        print(f"  pooled {f} done", flush=True)


# --------------------------------------------------------------------------------- scoring

def pin(y, q, t):
    d = y - q
    return np.maximum(t * d, (t - 1) * d)


def row_pinball(r):
    return (pin(r["y"], r["q10"], 0.1) + pin(r["y"], r["q50"], 0.5) + pin(r["y"], r["q90"], 0.9)) / 3


def windows(r) -> np.ndarray:
    return ((r["ts"] - int(r["start"])) // (RETRAIN_DAYS * 86_400)).astype(int)


def metrics(r) -> dict:
    y, lv = r["y"], r["lvol"]
    chunks = np.array_split(np.arange(len(y)), 20)
    c90 = [np.mean(y[c] <= r["q90"][c]) for c in chunks]
    terc = np.quantile(lv, [1 / 3, 2 / 3])
    thirds = [np.mean(y[m] <= r["q90"][m]) for m in (lv <= terc[0], (lv > terc[0]) & (lv <= terc[1]),
                                                     lv > terc[1])]
    w = windows(r)
    wc = [np.mean(y[w == k] <= r["q90"][w == k]) for k in np.unique(w) if (w == k).sum() > 200]
    half = r["ts"] < np.median(r["ts"])
    p = row_pinball(r)
    return {"c10": np.mean(y <= r["q10"]), "c50": np.mean(y <= r["q50"]), "c90": np.mean(y <= r["q90"]),
            "pin": p.mean(), "pin_h1": p[half].mean(), "pin_h2": p[~half].mean(),
            "width": np.mean(r["q90"] - r["q10"]), "worst": min(c90), "thirds": thirds,
            "win_min": min(wc) if wc else float("nan"), "wins": wc}


def diff_ci(a, b, n: int = 1000):
    """Mean of a - b (per-row pinball) and a day-bootstrap 95% interval."""
    d = row_pinball(a) - row_pinball(b)
    days = (a["ts"] // 86_400).astype(int)
    uniq, inv = np.unique(days, return_inverse=True)
    sums, counts = np.bincount(inv, d), np.bincount(inv)
    rng = np.random.default_rng(0)
    boots = []
    for _ in range(n):
        pick = rng.integers(0, len(uniq), len(uniq))
        boots.append(sums[pick].sum() / counts[pick].sum())
    return d.mean(), np.quantile(boots, [0.025, 0.975])


def gated(cand, prod) -> tuple[dict, float]:
    """Production's quotes in any 14-day window whose previous six windows' worst P90 cover was
    more than a point under production's; the candidate's otherwise."""
    w = windows(prod)
    ks = np.unique(w)
    cov = {name: {k: np.mean(r["y"][w == k] <= r["q90"][w == k]) for k in ks} for name, r in
           (("c", cand), ("p", prod))}
    use = {}
    for j, k in enumerate(ks):
        prior = ks[max(0, j - 6):j]
        use[k] = len(prior) >= 3 and min(cov["c"][x] for x in prior) >= min(cov["p"][x] for x in prior) - 0.01
    pick = np.array([use[k] for k in w])
    out = {k: (np.where(pick, cand[k], prod[k]) if k in ("q10", "q50", "q90") else prod[k]) for k in prod}
    return out, float(np.mean(list(use.values())))


def fmt(m) -> str:
    return (f"cover {m['c10']:.1%}/{m['c50']:.1%}/{m['c90']:.1%} | pinball {m['pin']:.4f} "
            f"(halves {m['pin_h1']:.4f}/{m['pin_h2']:.4f}) | width {m['width']:.2f} | worst slice "
            f"{m['worst']:.1%} | worst 14d {m['win_min']:.1%} | vol thirds "
            + "/".join(f"{x:.1%}" for x in m["thirds"]))


def load_run(h: int, fam: str, method: str):
    path = OUT / f"{h}_{fam}_{method}.npz"
    if not path.exists():
        return None
    z = np.load(path)
    return {k: z[k] for k in z.files}


def report() -> None:
    for h in (5, 20, 50):
        print(f"\n{'=' * 110}\nGBM ENVELOPE, 15m, next {h} bars - retrained every {RETRAIN_DAYS} days")
        runs = {f: {m: load_run(h, f, m) for m in ["prod", *VARIANTS]} for f in FAMILIES}
        # the selected variant: lowest pinball relative to prod over the first half, market families
        rel = {}
        for v in ["pooled", "fam", "resid", "recent"]:
            ratios = [metrics(runs[f][v])["pin_h1"] / metrics(runs[f]["prod"])["pin_h1"]
                      for f in MARKETS if runs[f][v] is not None and runs[f]["prod"] is not None]
            if ratios:
                rel[v] = float(np.mean(ratios))
        chosen = min(rel, key=rel.get) if rel else "fam"
        print("first-half pinball relative to prod, market families: "
              + ", ".join(f"{v} {x:.4f}" for v, x in rel.items()) + f"  -> selected {chosen}")
        for f in FAMILIES:
            prod = runs[f]["prod"]
            if prod is None:
                continue
            mp = metrics(prod)
            print(f"\n  {f}: {len(prod['y']):,} scored rows")
            print(f"    {'prod':9s} {fmt(mp)}")
            for v in VARIANTS:
                r = runs[f][v]
                if r is None:
                    continue
                m = metrics(r)
                d, ci = diff_ci(r, prod)
                print(f"    {v:9s} {fmt(m)} | vs prod {d:+.4f} [{ci[0]:+.4f}, {ci[1]:+.4f}]"
                      f" ({d / mp['pin']:+.1%}) | crossing {float(r['crossing']):.1%}")
            pick = chosen if runs[f][chosen] is not None else "fam"
            if runs[f][pick] is None:
                continue
            if f.startswith("walks"):
                d, ci = diff_ci(runs[f][pick], prod)
                tie = abs(d) / mp["pin"] < 0.01 or ci[0] <= 0 <= ci[1]
                print(f"    walks[{pick}]: {d / mp['pin']:+.2%} of prod's pinball, interval "
                      f"[{ci[0]:+.4f}, {ci[1]:+.4f}] -> {'ties' if tie else 'does not tie'}")
            g, share = gated(runs[f][pick], prod)
            mg = metrics(g)
            dg, cig = diff_ci(g, prod)
            print(f"    {'gated':9s} {fmt(mg)} | vs prod {dg:+.4f} [{cig[0]:+.4f}, {cig[1]:+.4f}]"
                  f" | {pick} used in {share:.0%} of windows")
            for label, r, m in ((pick, runs[f][pick], metrics(runs[f][pick])), ("gated", g, mg)):
                d, ci = diff_ci(r, prod)
                beats = ci[1] < 0
                slice_ok = m["worst"] >= mp["worst"] - 0.01
                stable = m["win_min"] >= mp["win_min"] - 0.02
                verdict = "PASS" if (beats and slice_ok and stable) else "fail"
                print(f"    bar[{label}]: beats pinball {beats} | worst slice ok {slice_ok} | "
                      f"stable {stable} -> {verdict}")


# --------------------------------------------------------------------------------- size

def export(model) -> dict:
    trees = [[[int(n["feature_idx"]), float(n["num_threshold"]), int(n["left"]), int(n["right"]),
               int(n["is_leaf"]), float(n["value"]), int(n["missing_go_to_left"])]
              for n in pr[0].nodes] for pr in model._predictors]
    return {"baseline": float(np.ravel(model._baseline_prediction)[0]), "trees": trees, "link": "identity"}


def raw(spec: dict, x: list[float]) -> float:
    total = spec["baseline"]
    for nodes in spec["trees"]:
        i = 0
        while not nodes[i][4]:
            f, thr, left, right, _, _, miss = nodes[i][:7]
            v = x[f]
            i = left if ((miss and math.isnan(v)) or (not math.isnan(v) and v <= thr)) else right
        total += nodes[i][5]
    return total


def size() -> None:
    frames = family_frames("fx")
    allf = pd.concat(frames, ignore_index=True).dropna(subset=["y"])
    x = allf[FEATS]
    for label, levels, iters in (("9 levels, 120 iterations", LEVELS9, ITER),
                                 ("5 levels, 120 iterations", LEVELS5, ITER),
                                 ("5 levels, 60 iterations", LEVELS5, 60)):
        models = [HistGradientBoostingRegressor(loss="quantile", quantile=q, max_depth=4, max_iter=iters,
                                                learning_rate=0.05, min_samples_leaf=300)
                  .fit(x.iloc[:ROWS], allf["y"].to_numpy()[:ROWS]) for q in levels]
        specs = [export(m) for m in models]
        nbytes = sum(len(json.dumps(s, separators=(",", ":"))) for s in specs)
        sample = x.iloc[-2000:].to_numpy()
        exact = max(abs(raw(s, list(r)) - m.predict(r.reshape(1, -1))[0])
                    for s, m in zip(specs[:1], models[:1], strict=True) for r in sample[:200])
        t0 = time.perf_counter()
        for r in sample:
            row = list(r)
            for s in specs:
                raw(s, row)
        per_bar = (time.perf_counter() - t0) / len(sample)
        print(f"  {label}: one horizon x one family = {nbytes / 1e6:.2f} MB JSON, "
              f"{per_bar * 1e6:.0f} us per bar in pure Python, exact to {exact:.1e}; "
              f"x 3 horizons x 7 families = {nbytes * 21 / 1e6:.1f} MB", flush=True)


if __name__ == "__main__":
    if PART == "report":
        report()
    elif PART == "size":
        size()
    elif FAMILY == "pooled":
        run_pooled()
    else:
        run_family(FAMILY)
