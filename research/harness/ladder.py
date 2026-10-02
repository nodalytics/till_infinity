"""Where does directional information enter? The ladder D0 -> D4, at level touches, against walks.

The proposal (ideas.md Part L): the level alone may carry no direction, but the way price arrives,
the state around it, the expansion state and the level's own sequence of tests might. So score
P(up wins) with progressively richer information and measure what each rung adds:

  D0  level        the engine's own reading: side, P(up), base rate, the level's record, strength
  D1  + approach   approach morphology: speed, run, depth, slowing, slopes, and from the last 16
                   bars velocity, acceleration, range contraction, persistence, efficiency, wick
                   asymmetry, distance to the level
  D2  + state      regime, the call's context (changing, learned, envelope, clock, touch), and the
                   higher-timeframe state (returns over 64 and 256 bars, position in the 256 range)
  D3  + expansion  the shock and expansion readings in the call's context
  D4  + history    the level's last four resolved touches on this side: push, adverse, outcome,
                   approach, and the trend across them; time since the last one

Pre-registered (2026-10-02), before any run.

  touches  the production structures.Engine replayed from 2025-01-01 at 15m and 1h, one call per
           touch (the first), exactly as skill.py does
  families real    EURUSD GBPUSD USDJPY AUDUSD USDCAD EURJPY XAUUSD BTCUSD ETHUSD
           deriv   Volatility 75, Jump 50, Drift Switch 10, Crash 500, Boom 500, Step (a market)
           walks   nine GARCH(1,1) walks with t(3) innovations from sub-steps, the control
  label    a symmetric race from the touch bar's close: +-1.5 ATR(14), 32 bars; up, down, or
           neither (a bar touching both is dropped). The direction label is up | decided. On a
           martingale P(up) = 0.5 whatever the state, so any skill on walks is geometry
  model    HistGB per rung, trained on the first 60% of touches by time, scored on the last 40%
  measures AUC, AUC within each arrival side, information in bits per touch over the train base
           rate, both halves of the test; and the trade: the top 20% most confident, in their
           side, scored +1/-1 on the race
  passes   a rung adds direction if its AUC gain over the rung below is >= 0.01 in both test halves,
           its day-bootstrap 95% interval excludes zero, and the same gain on walks is below half
           of it. The program needs D4 (or any rung) above 0.55 on real markets and not on walks
"""
from __future__ import annotations

import heapq
import json
import math
import os
import sys
from collections import defaultdict, deque
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(ROOT))

OUT = Path(os.environ.get("OUT", ".data/ladder"))
START = pd.Timestamp(os.environ.get("START", "2025-01-01"), tz="UTC").timestamp()
INTERVALS = ("15m", "1h")
SECONDS = {"15m": 900, "1h": 3600}
FAMILIES = {
    "real": ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "EURJPY", "XAUUSD", "BTCUSD", "ETHUSD"],
    "deriv": ["Volatility_75_Index", "Jump_50_Index", "Drift_Switch_Index_10", "Crash_500_Index",
              "Boom_500_Index", "Step_Index"],
    "walks": [f"WALK{k}" for k in range(int(os.environ.get("N_WALKS", 9)))],
}
BARRIER, HORIZON, ATR_N = 1.5, 32, 14
TOUCH = ("approach_vol", "depth_vol", "strength", "run_vol", "experience", "pivot", "backcheck", "regime",
         "up_rate", "slowing", "slope", "prior_slope", "interval_log")
CODE = {"reject": 1.0, "backcheck": 1.0, "break": -1.0, "trap": 0.5, "chop": 0.0}


# ------------------------------------------------------------------------------------------- bars

def walk_frame(k: int, iv: str, n15: int = int(os.environ.get("WALK_BARS", 45_000))) -> pd.DataFrame:
    """A GARCH(1,1) walk with t(3) innovations, built from 16 sub-steps a 15m bar, so the bar's
    high and low come from its own path rather than a bridge pinned to its return."""
    rng = np.random.default_rng(7_000 + k)
    sub = 16
    z = rng.standard_t(3, (n15, sub)) / math.sqrt(3.0) / math.sqrt(sub)
    zbar, var, sig = z.sum(axis=1), 0.001**2, np.empty(n15)
    for i in range(n15):
        sig[i] = math.sqrt(var)
        var = 0.001**2 * 0.02 + 0.06 * (sig[i] * zbar[i]) ** 2 + 0.92 * var
    path = 100.0 * np.exp(np.cumsum((z * sig[:, None]).ravel())).reshape(n15, sub)
    opens = np.r_[100.0, path[:-1, -1]]
    df = pd.DataFrame({"ts": START + 900 * np.arange(n15), "open": opens,
                       "high": np.maximum(path.max(axis=1), opens), "low": np.minimum(path.min(axis=1), opens),
                       "close": path[:, -1]})
    if iv == "15m":
        return df
    g = np.arange(n15) // 4
    return df.groupby(g).agg(ts=("ts", "first"), open=("open", "first"), high=("high", "max"),
                             low=("low", "min"), close=("close", "last")).reset_index(drop=True)


def frame(sym: str, iv: str) -> pd.DataFrame:
    if sym.startswith("WALK"):
        return walk_frame(int(sym[4:]), iv)
    import spikerisk
    df = spikerisk.load(None, sym, "SEQLAB", iv)
    return df[df["ts"] >= START].reset_index(drop=True)


def bars_of(sym, iv, df):
    for t, o, h, lo, c in zip(df["ts"].to_numpy(), df["open"].to_numpy(), df["high"].to_numpy(),
                              df["low"].to_numpy(), df["close"].to_numpy()):
        yield {"feed": sym.lower(), "venue": "SEQLAB", "interval": iv, "time": int(t),
               "open": float(o), "high": float(h), "low": float(lo), "close": float(c)}


# --------------------------------------------------------------------------------------- features

def morphology(h: deque, level: float) -> dict[str, float]:
    """The approach, from the bars up to and including the touch bar, in ATR units."""
    a = np.array(h)  # open, high, low, close
    o, hi, lo, c = a[:, 0], a[:, 1], a[:, 2], a[:, 3]
    tr = np.maximum(hi[1:], c[:-1]) - np.minimum(lo[1:], c[:-1])
    atr = tr[-ATR_N:].mean() or 1e-12
    rng = np.maximum(hi - lo, 1e-12)
    d = np.diff(c[-17:])
    v16 = (c[-1] - c[-17]) / atr
    v4 = (c[-1] - c[-5]) / atr
    out = {
        "m_v4": v4, "m_v16": v16, "m_accel": v4 - (c[-5] - c[-9]) / atr,
        "m_contract": rng[-4:].mean() / rng[-16:].mean(),
        "m_persist": float(np.mean(np.sign(d) == np.sign(v16))) if v16 else 0.5,
        "m_eff": abs(c[-1] - c[-17]) / (np.abs(d).sum() or 1e-12),
        "m_wick": float(np.mean(((hi - np.maximum(o, c)) - (np.minimum(o, c) - lo))[-8:] / rng[-8:])),
        "m_dist": (c[-1] - level) / atr,
        "h_r64": (c[-1] - c[-65]) / atr / 8.0 if len(c) > 65 else 0.0,
        "h_r256": (c[-1] - c[0]) / atr / 16.0,
        "h_pos": (c[-1] - lo.min()) / ((hi.max() - lo.min()) or 1e-12),
    }
    return out, atr


def history(seq: list[dict], now: float) -> dict[str, float]:
    out = {"q_n": float(len(seq)), "q_since": (now - seq[-1]["t"]) / 3600.0 if seq else -1.0}
    last = seq[-4:]
    for i in range(4):
        r = last[-1 - i] if i < len(last) else None
        out[f"q{i}_push"] = r["push"] if r else 0.0
        out[f"q{i}_adv"] = r["adverse"] if r else 0.0
        out[f"q{i}_out"] = r["code"] if r else 0.0
        out[f"q{i}_appr"] = r["appr"] if r else 0.0
        out[f"q{i}_dur"] = r["dur"] if r else 0.0
    out["q_trend"] = (last[-1]["push"] - last[0]["push"]) if len(last) > 1 else 0.0
    out["q_apprtrend"] = (last[-1]["appr"] - last[0]["appr"]) if len(last) > 1 else 0.0
    return out


# ----------------------------------------------------------------------------------------- replay

def replay(family: str) -> pd.DataFrame:
    from till_infinity.structures.engine import Engine
    syms = FAMILIES[family]
    series = []
    for sym in syms:
        for iv in INTERVALS:
            try:
                series.append(bars_of(sym, iv, frame(sym, iv)))
            except (ValueError, FileNotFoundError) as exc:
                print(f"  {family}: skip {sym} {iv}: {str(exc)[:60]}", flush=True)
    engine = Engine(intervals=INTERVALS)
    engine.consensus.single_source = frozenset(s.lower() for s in syms)
    hist: dict[tuple, deque] = defaultdict(lambda: deque(maxlen=257))
    races: dict[tuple, list] = defaultdict(list)
    seqs: dict[tuple, list] = defaultdict(list)
    pending: dict[tuple, dict] = {}
    rows = []
    stream = heapq.merge(*series, key=lambda b: (b["time"], b["interval"]))
    for n, bar in enumerate(stream):
        sk = (bar["feed"], bar["interval"])
        # resolve the races on this series with this bar, before anything new opens
        alive = []
        for r in races[sk]:
            up, dn = bar["high"] >= r["up_at"], bar["low"] <= r["dn_at"]
            r["age"] += 1
            if up and dn:
                r["row"]["race"] = "both"
            elif up or dn:
                r["row"]["race"] = "up" if up else "down"
            elif r["age"] >= HORIZON:
                r["row"]["race"] = "neither"
            else:
                alive.append(r)
        races[sk] = alive
        hist[sk].append((bar["open"], bar["high"], bar["low"], bar["close"]))
        for call in engine.observe_bar(bar):
            touch = engine.tracker.open_touch(call.level)
            if touch is None or touch.started != call.time or len(hist[sk]) < 257:
                continue
            inf = call.inference
            above = touch.features.side.name == "ABOVE"
            morph, atr = morphology(hist[sk], call.level.price)
            ctx = {f"c_{k}": float(v) for k, v in (call.context or {}).items()
                   if isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v)}
            row = dict(feed=call.feed, interval=call.interval, time=call.time, above=float(above),
                       level_id=call.level.id, p_up=inf.probability_up, base_up=inf.base_rate_up,
                       record_hold=inf.record_hold, record_n=inf.record_n, edge=inf.edge,
                       expected_push=inf.expected_push, push_sigma=inf.push_sigma, risk_vol=inf.risk_vol,
                       own=float(inf.own_touches), nb=float(inf.neighbours),
                       actionable=float(bool(getattr(inf, "actionable", False))),
                       **{f"x_{k}": float(getattr(touch.features, k, 0.0) or 0.0) for k in TOUCH},
                       **morph, **ctx,
                       **history(seqs[(call.level.id, above)], call.time))
            close = bar["close"]
            races[sk].append({"up_at": close + BARRIER * atr, "dn_at": close - BARRIER * atr, "age": 0, "row": row})
            pending[(call.feed, call.interval, call.level.id, touch.started)] = row
            rows.append(row)
        for level, touch in engine.drain_resolved():
            above = touch.features.side.name == "ABOVE"
            outcome = str(touch.outcome).split(".")[-1].lower()
            row = pending.pop((touch.feed, touch.interval, level.id, touch.started), None)
            if row is not None:
                row["outcome"], row["push"] = outcome, float(touch.push_vol)
            seqs[(level.id, above)].append(dict(
                t=touch.resolved or touch.started, push=float(touch.push_vol), adverse=float(touch.adverse_vol),
                code=CODE.get(outcome, 0.0), appr=float(touch.features.approach_vol or 0.0),
                dur=((touch.resolved or touch.started) - touch.started) / SECONDS.get(touch.interval, 900)))
        if n % 50_000 == 0:
            print(f"  {family}: {n:,} bars, {len(rows):,} touches", flush=True)
    d = pd.DataFrame(rows)
    d["family"] = family
    return d


# ---------------------------------------------------------------------------------------- scoring

def rungs(cols: list[str]) -> dict[str, list[str]]:
    d0 = ["above", "p_up", "base_up", "record_hold", "record_n", "edge", "expected_push", "push_sigma",
          "risk_vol", "own", "nb", "x_strength", "x_experience", "x_up_rate", "x_pivot", "x_backcheck",
          "x_interval_log"]
    d1 = d0 + ["x_approach_vol", "x_run_vol", "x_depth_vol", "x_slowing", "x_slope", "x_prior_slope",
               "m_v4", "m_v16", "m_accel", "m_contract", "m_persist", "m_eff", "m_wick", "m_dist"]
    hot = ("shock", "expansion", "coiled")
    ctx = [c for c in cols if c.startswith("c_")]
    d2 = d1 + ["x_regime", "h_r64", "h_r256", "h_pos"] + [c for c in ctx if not any(h in c for h in hot)]
    d3 = d2 + [c for c in ctx if any(h in c for h in hot)]
    d4 = d3 + [c for c in cols if c.startswith("q")]
    return {"D0": d0, "D1": d1, "D2": d2, "D3": d3, "D4": d4}


def auc(y, p):
    from sklearn.metrics import roc_auc_score
    return float(roc_auc_score(y, p)) if 0 < y.mean() < 1 else float("nan")


def bits(y, p, base):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    ll = -(y * np.log(p) + (1 - y) * np.log(1 - p)).mean()
    lb = -(y * np.log(base) + (1 - y) * np.log(1 - base)).mean()
    return float((lb - ll) / math.log(2))


def score(d: pd.DataFrame, label: str) -> dict:
    from sklearn.ensemble import HistGradientBoostingClassifier
    d = d.sort_values("time").reset_index(drop=True)
    cut = int(len(d) * 0.6)
    tr, te = d.iloc[:cut], d.iloc[cut:]
    y_tr, y_te = tr[label].to_numpy(float), te[label].to_numpy(float)
    mid = te["time"].median()
    halves = (te["time"] < mid).to_numpy()
    days = (te["time"] // 86400).to_numpy()
    above = te["above"].to_numpy() > 0.5
    base = float(y_tr.mean())
    out, preds = {"n_train": len(tr), "n_test": len(te), "base_up": round(base, 4)}, {}
    for name, cols in rungs(list(d.columns)).items():
        cols = [c for c in cols if c in d.columns]
        X_tr = tr[cols].to_numpy(float)
        X_te = te[cols].to_numpy(float)
        dead = ~np.isfinite(X_tr).any(axis=0) | (np.nanstd(X_tr, axis=0) == 0)
        X_tr[:, dead], X_te[:, dead] = 0.0, 0.0
        m = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, max_leaf_nodes=15,
                                           min_samples_leaf=100, l2_regularization=1.0, random_state=0)
        m.fit(X_tr, y_tr)
        p = m.predict_proba(X_te)[:, 1]
        preds[name] = p
        conf = np.abs(p - 0.5)
        top = conf >= np.quantile(conf, 0.8)
        side = np.where(p[top] > 0.5, 1.0, 0.0)
        out[name] = {"features": len(cols), "auc": round(auc(y_te, p), 4),
                     "halves": [round(auc(y_te[halves], p[halves]), 4), round(auc(y_te[~halves], p[~halves]), 4)],
                     "within_side": [round(auc(y_te[above], p[above]), 4), round(auc(y_te[~above], p[~above]), 4)],
                     "bits": round(bits(y_te, p, base), 5),
                     "top20_R": round(float(np.mean(np.where(side == y_te[top], 1.0, -1.0))), 4)}
    rng = np.random.default_rng(5)
    ud = np.unique(days)
    idx = {k: np.flatnonzero(days == k) for k in ud}
    names = list(preds)
    for a, b in zip(names, names[1:]):
        g = []
        for _ in range(200):
            pick = np.concatenate([idx[k] for k in rng.choice(ud, len(ud))])
            g.append(auc(y_te[pick], preds[b][pick]) - auc(y_te[pick], preds[a][pick]))
        g = np.array(g)
        out[f"{b}-{a}"] = {"gain": round(out[b]["auc"] - out[a]["auc"], 4),
                           "ci": [round(float(np.nanquantile(g, 0.025)), 4), round(float(np.nanquantile(g, 0.975)), 4)],
                           "halves": [round(out[b]["halves"][i] - out[a]["halves"][i], 4) for i in (0, 1)]}
    g = []
    for _ in range(200):
        pick = np.concatenate([idx[k] for k in rng.choice(ud, len(ud))])
        g.append(auc(y_te[pick], preds["D4"][pick]) - auc(y_te[pick], preds["D0"][pick]))
    out["D4-D0"] = {"gain": round(out["D4"]["auc"] - out["D0"]["auc"], 4),
                    "ci": [round(float(np.nanquantile(g, 0.025)), 4), round(float(np.nanquantile(g, 0.975)), 4)]}
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fams = os.environ.get("FAMILIES", "real,deriv,walks").split(",")
    with ProcessPoolExecutor(len(fams)) as pool:
        frames = list(pool.map(replay, fams))
    d = pd.concat(frames, ignore_index=True)
    d.to_pickle(OUT / "touches.pkl.gz")
    summary = {}
    for fam, g in d.groupby("family"):
        g = g.copy()
        race = g["race"].fillna("open")
        summary[fam] = {"touches": len(g), "race_shares": race.value_counts(normalize=True).round(3).to_dict()}
        dec = g[race.isin(["up", "down"])].copy()
        dec["y"] = (dec["race"] == "up").astype(float)
        summary[fam]["race"] = score(dec, "y")
        eng = g[g["outcome"].isin(["reject", "backcheck", "break", "trap"]) & (g["push"].fillna(0) != 0)].copy()
        eng["y"] = (eng["push"] > 0).astype(float)
        summary[fam]["push"] = score(eng, "y")
        print(fam, json.dumps(summary[fam], default=str), flush=True)
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1, default=str))


if __name__ == "__main__":
    main()
