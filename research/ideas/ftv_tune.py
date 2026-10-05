"""Fade-to-value x structures: can the two be tuned to each other? Frozen in `ftv_tune_rule.json`.

Phase 2 of `lrc-retest.md`'s R4b. The replay in `lrc_fade.py` logged, for every series and source
(real, iid walk, GARCH walk), the 15m bars, every actionable call the production engine published,
and every 15m / 30m call with the valuation book production's `FadeToValue` held at that moment.
This study re-decides those calls offline under every configuration of the frozen search space,
tunes on discovery data only (before 2024-01-01: the Binance perpetuals), tunes the walks the same
way, and confirms the selected configuration on 2024+ and on classes the tuning never saw.

  OUT=... FADE=... MODE=tune|confirm|holds|plot python research/ideas/ftv_tune.py
"""
from __future__ import annotations

import itertools
import json
import zlib
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1]))

import lrc_retest as L  # noqa: E402

OUT = Path(os.environ.get("OUT", ".data/ftv_tune"))
FADE = Path(os.environ.get("FADE", ".data/lrc_fade"))
RULE = json.load(open(HERE / "ftv_tune_rule.json"))
SPLIT = L.SPLIT
HOLD_BARS = 16          # production's 4h hold on 15m bars
MERGE = 0.35            # production's Book.MERGE_VOL: levels this close (vol units) are one level
TRAIL_VOL = 2.0
NS = (0.5, 1, 2, 4, 10)
CONTEXT_IVS = {"all": ("1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h"), "1h+": ("1h", "2h", "4h"), "2h+": ("2h", "4h")}

S = RULE["search"]
VALUE_DEFS = list(itertools.product(S["min_touches"], S["min_probability"], S["min_strength_q"], S["max_age_h"],
                                    S["level_intervals"], S["min_agree"], S["max_distance_vol"]))
STOPS = list(itertools.product(S["stop_clearance_vol"], S["stop_risk_vol_multiple"]))
TARGETS = S["target"]
MIN_D = S["min_distance_vol"]
ENTRY = S["entry_interval"]
TREND = S["trend"]
REGIME = S["regime"]


def n_configs():
    return len(VALUE_DEFS) * len(STOPS) * len(TARGETS) * len(MIN_D) * len(ENTRY) * len(TREND) * len(REGIME)


def lrc_trend(bars, ts):
    """LRC(100) slope sign on 1h bars resampled from the 15m bars, at the last 1h bar completed by `ts`."""
    h1 = L.resample(bars, 3600)
    slope, _m, _d = L.lrc(h1["close"].to_numpy(float), 100)
    done = h1["ts"].to_numpy() + 3600
    k = np.searchsorted(done, ts, "right") - 1
    out = np.where(k >= 0, np.sign(slope[np.clip(k, 0, None)]), 0.0)
    return np.nan_to_num(out)


def windows(bars):
    """Up and down 15m arrays (the flipped chart for shorts) padded for HOLD_BARS windows."""
    up = {k: bars[k].to_numpy(float) for k in ("open", "high", "low", "close")}
    dn = {"open": -up["open"], "close": -up["close"], "high": -up["low"], "low": -up["high"]}
    return up, dn


def simulate(up, dn, k, side, entry, stop, target, trail_u, spread):
    """Vectorised: each trade entered at the open of bar k (at `entry`, the mid at the call), long on the
    chart for side > 0 and on the flipped chart for side < 0; out at the stop (0.05 ATR slippage), the
    target, a TRAIL_VOL-unit trail behind completed bars' best high when `target` is NaN, or the close
    of the 16th bar. A bar touching both counts as the stop. Returns net R, the most R reached before the
    stop within the hold, and the exit bar."""
    n = len(up["close"])
    m = len(k)
    if m == 0:
        return np.zeros(0), np.zeros(0), np.zeros(0, int)
    idx = np.clip(k[:, None] + np.arange(HOLD_BARS)[None, :], 0, n - 1)
    valid = (k[:, None] + np.arange(HOLD_BARS)[None, :]) < n
    s = side[:, None] > 0
    H = np.where(s, up["high"][idx], dn["high"][idx])
    Lo = np.where(s, up["low"][idx], dn["low"][idx])
    O = np.where(s, up["open"][idx], dn["open"][idx])
    C = np.where(s, up["close"][idx], dn["close"][idx])
    e = side * entry
    st = side * stop
    risk = e - st
    a = L.atr(up["high"], up["low"], up["close"])[np.clip(k - 1, 0, n - 1)]
    is_trail = ~np.isfinite(target)
    tg = np.where(is_trail, np.inf, side * np.nan_to_num(target))
    # the trail: behind the best high of completed bars, never below the stop
    best = np.maximum.accumulate(np.concatenate([e[:, None], H[:, :-1]], 1), 1)
    stop_line = np.where(is_trail[:, None], np.maximum(st[:, None], best - TRAIL_VOL * trail_u[:, None]), st[:, None])
    hit_s = (Lo <= stop_line) & valid
    hit_t = (H >= tg[:, None]) & valid
    js = np.where(hit_s.any(1), hit_s.argmax(1), HOLD_BARS)
    jt = np.where(hit_t.any(1), hit_t.argmax(1), HOLD_BARS)
    last = np.minimum(valid.sum(1), HOLD_BARS) - 1
    rows = np.arange(m)
    stop_first = (js <= jt) & (js < HOLD_BARS)
    px_s = np.minimum(O[rows, np.minimum(js, HOLD_BARS - 1)], stop_line[rows, np.minimum(js, HOLD_BARS - 1)]) - L.SLIP * a
    px_t = np.maximum(O[rows, np.minimum(jt, HOLD_BARS - 1)], np.where(np.isfinite(tg), tg, 0.0))
    px_c = C[rows, last]
    exit_px = np.where(stop_first, px_s, np.where(jt < HOLD_BARS, px_t, px_c))
    xb = np.where(stop_first, js, np.where(jt < HOLD_BARS, jt, last))
    R = (exit_px - e) / risk - spread / risk
    # most R before the fixed stop within the hold
    hs = (Lo <= st[:, None]) & valid
    ks = np.where(hs.any(1), hs.argmax(1), HOLD_BARS)
    upto = np.arange(HOLD_BARS)[None, :] < ks[:, None]
    mfe = np.where(upto & valid, H, -np.inf).max(1)
    mfe = np.maximum(0.0, (np.where(np.isfinite(mfe), mfe, e) - e) / risk)
    return R, mfe, k + xb


def load_log(path):
    d = pd.read_pickle(path)  # our own replay logs (lrc_fade.py), never outside data
    return d


def candidates(snaps, t_snap):
    """The book around each snapshot, one row per (snapshot, level): price, interval, probability,
    strength, touches, age in hours, and how many distinct timeframes the book holds within MERGE vol."""
    rows = []
    for i, (book, spot, vb, t) in enumerate(zip(snaps["book"], snaps["spot"], snaps["vol_bps"], t_snap)):
        if not book:
            continue
        u = spot * vb / 1e4
        px = np.array([b[0] for b in book])
        iv = [b[1] for b in book]
        for j, b in enumerate(book):
            near = {iv[q] for q in range(len(book)) if abs(px[q] - b[0]) <= MERGE * u}
            rows.append((i, b[0], b[1], b[2], b[3], b[4], (t - b[5]) / 3600.0, len(near), (b[0] - spot) / u if u > 0 else np.nan))
    return pd.DataFrame(rows, columns=["snap", "price", "iv", "prob", "strength", "touches", "age_h", "agree", "dist"])


def series_table(path, strength_cut):
    """Every (snapshot, configuration) outcome for one series, summed into cells for the filters."""
    log = load_log(path)
    snaps, bars = log["snaps"], log["bars"]
    if not len(snaps):
        return None
    snaps = snaps.reset_index(drop=True)
    t = snaps["t"].to_numpy(float)
    ts = bars["ts"].to_numpy(np.int64)
    k = np.searchsorted(ts, t)  # the first 15m bar opening at or after the call's close
    ok = k < len(ts) - 1
    snaps, t, k = snaps[ok].reset_index(drop=True), t[ok], k[ok]
    cand = candidates(snaps, t)
    if not len(cand):
        return None
    cand = cand.sort_values(["snap", "touches", "dist"], ascending=[True, False, True], key=lambda c: c.abs() if c.name == "dist" else c)
    cs = cand["snap"].to_numpy()
    up, dn = windows(bars)
    spot = snaps["spot"].to_numpy(float)
    u = spot * snaps["vol_bps"].to_numpy(float) / 1e4
    here = snaps["level"].to_numpy(float)
    rv = np.abs(snaps["risk_vol"].fillna(1.0).to_numpy(float))
    rv = np.where(rv > 0, rv, 1.0)
    zlo, zhi = snaps["zone_low"].fillna(0.0).to_numpy(float), snaps["zone_high"].fillna(0.0).to_numpy(float)
    spread = float(log["spread"])
    half = np.where(t < SPLIT, 0, 1)
    ivc = np.where(snaps["iv"].to_numpy() == "15m", 0, 1)
    trend = lrc_trend(bars, t)
    regime = np.where(snaps.get("vol_stretch", pd.Series(np.nan, index=snaps.index)).fillna(1.0).to_numpy(float) < 1.0, 0, 1)
    out = []
    for vi, (mt, mp, msq, ma, liv, mg, md) in enumerate(VALUE_DEFS):
        m = ((cand["touches"] >= mt) & (cand["prob"] >= mp) & (cand["strength"] >= strength_cut[msq])
             & (cand["age_h"] <= ma) & cand["iv"].isin(CONTEXT_IVS[liv]) & (cand["agree"] >= mg)
             & (cand["dist"].abs() <= md)).to_numpy()
        idx = np.flatnonzero(m)
        if not len(idx):
            continue
        first = idx[np.r_[True, cs[idx][1:] != cs[idx][:-1]]]
        si = cs[first]
        V = cand["price"].to_numpy()[first]
        d = (V - spot[si]) / u[si]
        side = np.sign(d)
        keep = np.abs(d) >= min(MIN_D)
        si, V, d, side = si[keep], V[keep], d[keep], side[keep]
        if not len(si):
            continue
        dbin = np.digitize(np.abs(d), MIN_D) - 1  # 0 .. len(MIN_D)-1
        rel = np.where(trend[si] == 0, 2, np.where(np.sign(trend[si]) == side, 0, 1))  # with / against / flat
        for sti, (clr, mult) in enumerate(STOPS):
            dist = mult * rv[si] * u[si]
            edge = np.where(side > 0, zlo[si], zhi[si])
            beyond = here[si] - side * dist
            outside = edge - side * clr * u[si]
            stop = np.where(edge != 0, np.where(side > 0, np.minimum(beyond, outside), np.maximum(beyond, outside)), beyond)
            for ti, tgt in enumerate(TARGETS):
                if tgt == "trail":
                    target = np.full(len(si), np.nan)
                else:
                    target = V - side * float(tgt) * u[si]
                good = ((spot[si] - stop) * side > 0)
                if tgt != "trail":
                    good &= (target - spot[si]) * side > 0
                if not good.any():
                    continue
                g = np.flatnonzero(good)
                R, mfe, _xb = simulate(up, dn, k[si[g]], side[g], spot[si[g]], stop[g], target[g], u[si[g]], spread)
                cell = (((half[si[g]] * 2 + ivc[si[g]]) * 3 + rel[g]) * 2 + regime[si[g]]) * len(MIN_D) + dbin[g]
                ncell = 2 * 2 * 3 * 2 * len(MIN_D)
                out.append((vi, sti, ti,
                            np.bincount(cell, minlength=ncell), np.bincount(cell, weights=R, minlength=ncell),
                            np.bincount(cell, weights=(mfe >= 2).astype(float), minlength=ncell),
                            np.bincount(cell, weights=R * R, minlength=ncell)))
    return out


def tune_one(args):
    path, cut = args
    try:
        return path.stem, series_table(path, cut)
    except Exception as exc:  # noqa: BLE001
        return path.stem, f"failed: {exc}"


def strength_cuts(paths):
    """The strength threshold for each quantile in the search, from the real discovery books."""
    vals = []
    for p in paths:
        if not p.stem.endswith("_real"):
            continue
        sn = load_log(p)["snaps"]
        if not len(sn):
            continue
        sn = sn[sn["t"] < SPLIT]
        for book in sn["book"]:
            vals += [b[3] for b in book]
    vals = np.array(vals) if vals else np.array([0.0])
    return {q: (float(np.quantile(vals, q)) if q > 0 else -np.inf) for q in S["min_strength_q"]}


def configs_frame(totals):
    """Every configuration's discovery and confirmation numbers from the summed cells."""
    nb = len(MIN_D)
    rows = []
    for (vi, sti, ti), (cnt, sm, p2, sq) in totals.items():
        c = cnt.reshape(2, 2, 3, 2, nb)
        s_ = sm.reshape(2, 2, 3, 2, nb)
        p = p2.reshape(2, 2, 3, 2, nb)
        q = sq.reshape(2, 2, 3, 2, nb)
        for mi, md in enumerate(MIN_D):
            for ei, ent in enumerate(ENTRY):
                ivsel = [0] if ent == "15m" else [1] if ent == "30m" else [0, 1]
                for tri, tr in enumerate(TREND):
                    rsel = [0, 1, 2] if tr == "none" else [0] if tr == "with" else [1]
                    for rgi, rg in enumerate(REGIME):
                        gsel = [0, 1] if rg == "none" else [0] if rg == "low" else [1]
                        sub = np.ix_([0, 1], ivsel, rsel, gsel, list(range(mi, nb)))
                        cc, ss, pp, qq = (x[sub].sum(axis=(1, 2, 3, 4)) for x in (c, s_, p, q))
                        rows.append(dict(vi=vi, sti=sti, ti=ti, md=md, entry=ent, trend=tr, regime=rg,
                                         n_disc=cc[0], R_disc=ss[0] / cc[0] if cc[0] else np.nan,
                                         P2_disc=pp[0] / cc[0] if cc[0] else np.nan,
                                         sd_disc=np.sqrt(max(qq[0] / cc[0] - (ss[0] / cc[0]) ** 2, 0)) if cc[0] else np.nan,
                                         n_conf=cc[1], R_conf=ss[1] / cc[1] if cc[1] else np.nan,
                                         P2_conf=pp[1] / cc[1] if cc[1] else np.nan))
    return pd.DataFrame(rows)


def label(row):
    mt, mp, msq, ma, liv, mg, md_ = VALUE_DEFS[int(row["vi"])]
    clr, mult = STOPS[int(row["sti"])]
    return (f"touches>={mt} prob>={mp} strength>=q{msq} age<={ma}h levels={liv} agree>={mg} maxd={md_} "
            f"mind={row['md']} stop(clear {clr}, x{mult} risk_vol) target={TARGETS[int(row['ti'])]} "
            f"entry={row['entry']} trend={row['trend']} regime={row['regime']}")


def tune():
    OUT.mkdir(parents=True, exist_ok=True)
    logs = sorted((FADE / "logs").glob("*.pkl"))
    tune_set = [p for p in logs if p.stem.startswith("binance_")]
    cut = strength_cuts(tune_set)
    json.dump({str(k): v for k, v in cut.items()}, open(OUT / "strength_cuts.json", "w"))
    print(f"{n_configs():,} configurations; strength cuts {cut}", flush=True)
    totals = {src: {} for src in ("real", "walk", "garch")}
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", 12))) as pool:
        for stem, res in pool.map(tune_one, [(p, cut) for p in logs], chunksize=1):
            src = stem.rsplit("_", 1)[1]
            if not isinstance(res, list):
                print(f"  {stem}: {res}", flush=True)
                continue
            scope = "tune" if stem.startswith("binance_") else "unseen"
            for vi, sti, ti, cnt, sm, p2, sq in res:
                key = (scope, vi, sti, ti)
                acc = totals[src].setdefault(key, [np.zeros_like(cnt, float), np.zeros_like(sm), np.zeros_like(p2), np.zeros_like(sq)])
                for a_, b_ in zip(acc, (cnt, sm, p2, sq)):
                    a_ += b_
            print(f"  {stem}: {len(res)} tables", flush=True)
    frames = {}
    for src in totals:
        for scope in ("tune", "unseen"):
            sub = {k[1:]: v for k, v in totals[src].items() if k[0] == scope}
            if sub:
                f = configs_frame(sub)
                f["src"], f["scope"] = src, scope
                frames[(src, scope)] = f
    allc = pd.concat(frames.values(), ignore_index=True)
    allc.to_pickle(OUT / "configs.pkl.gz")
    select(allc)


def select(allc):
    """The frozen objective on discovery: the highest mean net R with n >= MIN_TRADES and P(2R) at or
    above the same configuration's P(2R) on the reference walk (iid for real; the other walk for walks)."""
    key = ["vi", "sti", "ti", "md", "entry", "trend", "regime"]
    t = allc[allc["scope"] == "tune"].set_index(key)
    ref = {"real": "walk", "walk": "garch", "garch": "walk"}
    best = {}
    for src in ("real", "walk", "garch"):
        x = t[t["src"] == src].copy()
        r = t[t["src"] == ref[src]]["P2_disc"]
        x["P2_ref"] = r.reindex(x.index)
        x["excess"] = x["P2_disc"] - x["P2_ref"]
        ok = x[(x["n_disc"] >= int(os.environ.get("MIN_TRADES", RULE["objective"]["min_trades"]))) & (x["excess"] >= 0)]  # env: tests only
        ok = ok.sort_values("R_disc", ascending=False)
        ok.head(50).reset_index().to_csv(OUT / f"top_{src}.csv", index=False)
        best[src] = ok.head(RULE["confirm"]["top_k"]).reset_index()
        print(f"\n{src}: {len(x):,} configurations scored, {len(ok):,} eligible; best in-sample R "
              f"{ok['R_disc'].iloc[0] if len(ok) else float('nan'):+.4f}", flush=True)
        for _, row in best[src].iterrows():
            print(f"   R_disc {row['R_disc']:+.4f} n {int(row['n_disc'])} P2 {row['P2_disc']:.3f} excess {row['excess']:+.3f} | {label(row)}")
    pd.to_pickle(best, OUT / "selected.pkl")


# ------------------------------------------------------------------------------------- confirmation

def decide(path, cfgs, cut):
    """Trades for the given full configurations on one series: one row per trade."""
    log = load_log(path)
    snaps, bars = log["snaps"], log["bars"]
    if not len(snaps):
        return []
    snaps = snaps.reset_index(drop=True)
    t = snaps["t"].to_numpy(float)
    ts = bars["ts"].to_numpy(np.int64)
    k = np.searchsorted(ts, t)
    ok = k < len(ts) - 1
    snaps, t, k = snaps[ok].reset_index(drop=True), t[ok], k[ok]
    cand = candidates(snaps, t)
    if not len(cand):
        return []
    cand = cand.sort_values(["snap", "touches", "dist"], ascending=[True, False, True],
                            key=lambda c: c.abs() if c.name == "dist" else c)
    cs = cand["snap"].to_numpy()
    up, dn = windows(bars)
    spot = snaps["spot"].to_numpy(float)
    u = spot * snaps["vol_bps"].to_numpy(float) / 1e4
    here = snaps["level"].to_numpy(float)
    rv = np.abs(snaps["risk_vol"].fillna(1.0).to_numpy(float))
    rv = np.where(rv > 0, rv, 1.0)
    zlo, zhi = snaps["zone_low"].fillna(0.0).to_numpy(float), snaps["zone_high"].fillna(0.0).to_numpy(float)
    spread = float(log["spread"])
    ivs = snaps["iv"].to_numpy()
    trend = lrc_trend(bars, t)
    vs = snaps.get("vol_stretch", pd.Series(np.nan, index=snaps.index)).fillna(1.0).to_numpy(float)
    rows = []
    for name, c in cfgs.items():
        mt, mp, msq, ma, liv, mg, md_ = VALUE_DEFS[int(c["vi"])]
        clr, mult = STOPS[int(c["sti"])]
        tgt = TARGETS[int(c["ti"])]
        m = ((cand["touches"] >= mt) & (cand["prob"] >= mp) & (cand["strength"] >= cut[msq])
             & (cand["age_h"] <= ma) & cand["iv"].isin(CONTEXT_IVS[liv]) & (cand["agree"] >= mg)
             & (cand["dist"].abs() <= md_)).to_numpy()
        idx = np.flatnonzero(m)
        if not len(idx):
            continue
        first = idx[np.r_[True, cs[idx][1:] != cs[idx][:-1]]]
        si = cs[first]
        V = cand["price"].to_numpy()[first]
        d = (V - spot[si]) / u[si]
        side = np.sign(d)
        keep = np.abs(d) >= float(c["md"])
        if c["entry"] != "both":
            keep &= ivs[si] == c["entry"]
        if c["trend"] != "none":
            rel = np.sign(trend[si]) == side
            keep &= (rel if c["trend"] == "with" else (~rel & (trend[si] != 0)))
        if c["regime"] != "none":
            keep &= (vs[si] < 1.0) if c["regime"] == "low" else (vs[si] >= 1.0)
        si, V, d, side = si[keep], V[keep], d[keep], side[keep]
        dist = mult * rv[si] * u[si]
        edge = np.where(side > 0, zlo[si], zhi[si])
        beyond = here[si] - side * dist
        outside = edge - side * clr * u[si]
        stop = np.where(edge != 0, np.where(side > 0, np.minimum(beyond, outside), np.maximum(beyond, outside)), beyond)
        target = np.full(len(si), np.nan) if tgt == "trail" else V - side * float(tgt) * u[si]
        good = (spot[si] - stop) * side > 0
        if tgt != "trail":
            good &= (target - spot[si]) * side > 0
        g = np.flatnonzero(good)
        if not len(g):
            continue
        R, mfe, xb = simulate(up, dn, k[si[g]], side[g], spot[si[g]], stop[g], target[g], u[si[g]], spread)
        rng = np.random.default_rng(zlib.crc32(f"{path.stem}{name}".encode()))
        tw = np.where(rng.random(len(g)) < 0.5, 1.0, -1.0) * side[g]
        twR, twm, _ = simulate(up, dn, k[si[g]], tw, spot[si[g]], spot[si[g]] - tw * np.abs(spot[si[g]] - stop[g]),
                               np.where(np.isfinite(target[g]), spot[si[g]] + tw * np.abs(target[g] - spot[si[g]]), np.nan),
                               u[si[g]], spread)
        # one open trade per series: skip a trade entered before the previous one's exit bar
        order = np.argsort(k[si[g]], kind="stable")
        solo = np.zeros(len(g), bool)
        busy = -1
        for j in order:
            if k[si[g]][j] > busy:
                solo[j] = True
                busy = xb[j]
        rows.append(pd.DataFrame(dict(cfg=name, ts=ts[k[si[g]]], R=R, mfe=mfe, twR=twR, twmfe=twm, solo=solo,
                                      side=side[g], d=d[g], risk_u=np.abs(spot[si[g]] - stop[g]) / u[si[g]])))
    return rows


def confirm_one(args):
    path, cfgs, cut = args
    rows = decide(path, cfgs, cut)
    if not rows:
        return None
    d = pd.concat(rows, ignore_index=True)
    venue, rest = path.stem.split("_", 1)
    sym, src = rest.rsplit("_", 1)
    d["venue"], d["sym"], d["src"] = venue, sym.replace("-", " "), src
    d["cls"] = L.klass(venue, sym.replace("-", " "), "15m")
    return d


def baseline():
    """Production's defaults, as a configuration of the search space."""
    vi = VALUE_DEFS.index((4, 0.0, 0, 6, "all", 1, 8))
    return dict(vi=vi, sti=STOPS.index((0.25, 1)), ti=TARGETS.index(0.25), md=1.5, entry="both", trend="none",
                regime="none")


def confirm():
    best = pd.read_pickle(OUT / "selected.pkl")  # our own selection
    cut = {(0 if float(k) == 0 else float(k)): v for k, v in json.load(open(OUT / "strength_cuts.json")).items()}
    cfgs = {"baseline": baseline()}
    for src in ("real", "walk", "garch"):
        for i, row in best[src].iterrows():
            cfgs[f"{src}#{i + 1}"] = {k: row[k] for k in ("vi", "sti", "ti", "md", "entry", "trend", "regime")}
    logs = sorted((FADE / "logs").glob("*.pkl"))
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", 12))) as pool:
        got = [g for g in pool.map(confirm_one, [(p, cfgs, cut) for p in logs], chunksize=1) if g is not None]
    d = pd.concat(got, ignore_index=True)
    d["half"] = np.where(d["ts"] < SPLIT, "disc", "conf")
    d["scope"] = np.where(d["venue"] == "binance", "BINANCE", np.where(d["cls"].isin(L.NONDERIV), "UNSEEN_NONDERIV", d["cls"]))
    d.to_pickle(OUT / "confirm_trades.pkl.gz")
    rng = np.random.default_rng(77)
    rows = []
    for (cfg, src, scope, half), g in d.groupby(["cfg", "src", "scope", "half"]):
        for solo in (False, True):
            x = g[g["solo"]] if solo else g
            for col, mcol, nm in (("R", "mfe", src), ("twR", "twmfe", "twin")):
                if nm == "twin" and src != "real":
                    continue
                R = x[col].to_numpy(float)
                if not len(R):
                    continue
                lo, hi, p = L.boot(x["ts"].to_numpy(np.int64), R, rng) if len(R) > 30 else (np.nan,) * 3
                rows.append(dict(cfg=cfg, src=nm, scope=scope, half=half, solo=solo, n=len(R), R=R.mean(), lo=lo, hi=hi,
                                 p=p, **{f"P{N}": float((x[mcol] >= N).mean()) for N in NS}))
    tab = pd.DataFrame(rows)
    tab.to_csv(OUT / "confirm.csv", index=False)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 500)
    print(tab[~tab["solo"]].round(4).to_string(index=False))
    json.dump({k: {kk: (vv if not isinstance(vv, np.generic) else vv.item()) for kk, vv in v.items()} for k, v in cfgs.items()},
              open(OUT / "confirm_configs.json", "w"), indent=1)


# ------------------------------------------------------------------------------------------ hold rates

def holds_one(path):
    log = load_log(path)
    calls, bars = log["calls"], log["bars"]
    if not len(calls):
        return None
    ts = bars["ts"].to_numpy(np.int64)
    h, l, c = (bars[k].to_numpy(float) for k in ("high", "low", "close"))
    out = []
    for r in calls.itertuples(index=False):
        k = int(np.searchsorted(ts, r.t))
        u = r.spot * r.vol_bps / 1e4
        if k >= len(ts) - 1 or not u > 0 or not np.isfinite(r.level):
            continue
        hh, ll, cc = h[k:k + 500], l[k:k + 500], c[k:k + 500]
        res = {}
        for name, s in (("hold", 1.0 if r.above else -1.0), ("called", 1.0 if r.up else -1.0)):
            away = (hh >= r.level + u) if s > 0 else (ll <= r.level - u)
            thru = (cc <= r.level - u) if s > 0 else (cc >= r.level + u)
            ja = int(np.argmax(away)) if away.any() else None
            jt = int(np.argmax(thru)) if thru.any() else None
            res[name] = np.nan if ja is None and jt is None else float(jt is None or (ja is not None and ja <= jt))
        out.append(dict(t=r.t, iv=r.iv, probability=r.probability, strength=r.strength, touches=r.own_touches, **res))
    d = pd.DataFrame(out)
    venue, rest = path.stem.split("_", 1)
    sym, src = rest.rsplit("_", 1)
    d["venue"], d["sym"], d["src"] = venue, sym.replace("-", " "), src
    d["cls"] = L.klass(venue, sym.replace("-", " "), "15m")
    return d


def holds():
    OUT.mkdir(parents=True, exist_ok=True)
    logs = sorted((FADE / "logs").glob("*.pkl"))
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", 12))) as pool:
        got = [g for g in pool.map(holds_one, logs, chunksize=1) if g is not None and len(g)]
    d = pd.concat(got, ignore_index=True)
    d["half"] = np.where(d["t"] < SPLIT, "disc", "conf")
    ref = d[(d["src"] == "real") & (d["venue"] == "binance") & (d["half"] == "disc")]
    rows = []
    for score in ("probability", "strength"):
        edges = np.unique(np.nanquantile(ref[score], np.linspace(0, 1, 11)))
        d[f"{score}_dec"] = np.clip(np.searchsorted(edges, d[score], "right") - 1, 0, len(edges) - 2)
        for (src, dec), g in d.groupby(["src", f"{score}_dec"]):
            for pool_, x in (("ALL", g), ("NONDERIV", g[g["cls"].isin(L.NONDERIV)]), ("DERIV", g[~g["cls"].isin(L.NONDERIV)])):
                rows.append(dict(score=score, src=src, pool=pool_, decile=int(dec) + 1, n=len(x),
                                 hold=x["hold"].mean(), called=x["called"].mean(),
                                 lo_edge=edges[int(dec)], hi_edge=edges[int(dec) + 1]))
    tab = pd.DataFrame(rows)
    tab.to_csv(OUT / "holds_deciles.csv", index=False)
    d.to_pickle(OUT / "holds.pkl.gz")
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 500)
    for score in ("probability", "strength"):
        x = tab[(tab["score"] == score) & (tab["pool"] == "ALL")]
        print(score)
        print(x.pivot_table(index="decile", columns="src", values=["hold", "called", "n"]).round(3).to_string())


# ------------------------------------------------------------------------------------------------ plots

def plot():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    allc = pd.read_pickle(OUT / "configs.pkl.gz")
    t = allc[(allc["scope"] == "tune") & (allc["n_disc"] >= RULE["objective"]["min_trades"])]
    fig, axes = plt.subplots(2, 4, figsize=(24, 10))
    ax = axes[0, 0]
    for src, col in (("real", "#1d3557"), ("walk", "#e76f51"), ("garch", "#2a9d8f")):
        x = t[t["src"] == src]["R_disc"]
        ax.hist(x, bins=120, histtype="step", color=col, label=f"{src}: best {x.max():+.3f}, median {x.median():+.3f}", density=True)
    ax.set_title("every configuration's discovery mean R (n >= 300)")
    ax.set_xlabel("mean R after costs")
    ax.legend(fontsize=8)
    dims = [("min touches", lambda r: VALUE_DEFS[int(r)][0], "vi"), ("max age h", lambda r: VALUE_DEFS[int(r)][3], "vi"),
            ("level timeframes", lambda r: VALUE_DEFS[int(r)][4], "vi"), ("min distance", lambda r: r, "md"),
            ("target", lambda r: str(TARGETS[int(r)]), "ti"), ("trend", lambda r: r, "trend"), ("regime", lambda r: r, "regime")]
    for ax, (name, f, col) in zip(axes.flat[1:], dims):
        for k_, (src, c_) in enumerate((("real", "#1d3557"), ("walk", "#e76f51"), ("garch", "#2a9d8f"))):
            x = t[t["src"] == src].copy()
            x["key"] = x[col].map(f)
            g = x.groupby("key")["R_disc"].quantile(0.9)
            ax.plot(range(len(g)), g.values, "-o", color=c_, label=src)
            ax.set_xticks(range(len(g)))
            ax.set_xticklabels([str(v) for v in g.index], fontsize=8)
        ax.set_title(f"90th percentile of discovery R by {name}", fontsize=9)
        ax.legend(fontsize=7)
    fig.suptitle(f"fade-to-value tuning surface, {n_configs():,} configurations: real (Binance before 2024) vs the same search on walks")
    fig.tight_layout()
    fig.savefig(OUT / "ftv_surface.png", dpi=70)
    plt.close(fig)
    tab = pd.read_csv(OUT / "confirm.csv")
    fig, axes = plt.subplots(1, 3, figsize=(20, 6), sharey=True)
    for ax, (scope, half) in zip(axes, (("BINANCE", "disc"), ("BINANCE", "conf"), ("UNSEEN_NONDERIV", "conf"))):
        for cfg, st, colr in (("real#1", "-o", "#1d3557"), ("baseline", "--s", "#999999")):
            for src, alpha in (("real", 1.0), ("walk", 0.5), ("garch", 0.5), ("twin", 0.5)):
                r = tab[(tab["cfg"] == cfg) & (tab["src"] == src) & (tab["scope"] == scope) & (tab["half"] == half) & ~tab["solo"]]
                if len(r):
                    r = r.iloc[0]
                    ax.plot(NS, [r[f"P{N}"] for N in NS], st, color=colr if src == "real" else None, alpha=alpha,
                            label=f"{cfg} {src} {r['R']:+.3f} n{int(r['n'])}")
        ax.plot(NS, [1 / (N + 1) for N in NS], color="k", lw=0.7, label="1/(N+1)")
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_title(f"{scope} {half}")
        ax.legend(fontsize=6)
    fig.suptitle("the selected configuration's P(+N R before the stop, within the 4h hold), against the baseline, walks and 1/(N+1)")
    fig.tight_layout()
    fig.savefig(OUT / "ftv_selected_pnr.png", dpi=75)
    plt.close(fig)
    hd = pd.read_csv(OUT / "holds_deciles.csv")
    fig, axes = plt.subplots(2, 2, figsize=(16, 9), sharey="row")
    for i, what in enumerate(("hold", "called")):
        for j, score in enumerate(("probability", "strength")):
            ax = axes[i, j]
            for src, col in (("real", "#1d3557"), ("walk", "#e76f51"), ("garch", "#2a9d8f")):
                x = hd[(hd["score"] == score) & (hd["src"] == src) & (hd["pool"] == "ALL")].sort_values("decile")
                ax.plot(x["decile"], x[what], "-o", color=col, label=src)
            ax.set_title(f"{what} rate by {score} decile (deciles cut on real Binance discovery calls)")
            ax.set_xlabel("decile")
            ax.legend()
    fig.suptitle("do structures' scores predict whether a level holds, beyond walks?")
    fig.tight_layout()
    fig.savefig(OUT / "ftv_holds_deciles.png", dpi=75)
    plt.close(fig)
    print("plots written", flush=True)


def main():
    {"tune": tune, "confirm": confirm, "holds": holds, "plot": plot}[os.environ.get("MODE", "tune")]()


if __name__ == "__main__":
    main()
