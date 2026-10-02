"""Part J (research/docs/ideas.md): the 1R-first framework - P(1R before the stop), by setup and state.

For each setup with entry E and stop distance R: P1R = P(the favourable side reaches 1R before
the adverse side reaches 1R), E[T1R | 1R first], P(2R before stop), P(3R before stop), the
pathological share (1R reached only after a 2R adverse excursion, path ignoring the stop), and
the spread in R. On a martingale P1R = 0.5 whatever the volatility (bars through both levels are
scored as the stop, so the walks give the exact empirical null).

Pre-registered (2026-10-02), before any run. Lab broker bars, 15m and 1h, real families and Deriv;
GARCH walks (4 per interval) are the control. R = 1 ATR(14) unless stated.

  J1  compressed (range percentile <= 0.2), then the first close beyond the 16-bar box within 16
      bars: the breakout's side
  J2  the previous bar's percentile <= 0.3 and this bar's true range >= 2x the smoothed range:
      the side of this bar's move
  J5  a J1 breakout that closes back inside the box within 4 bars: the opposite side
  J6  an impulse of >= 2 ATR (close to close, 3 bars), then the first bar retracing >= 38% of it:
      the impulse's side; stop at the retracement's extreme (R >= 0.5 ATR)
  J7  inside the 16-bar box, price touches its lower (upper) quarter, then closes back above
      (below) the middle: up (down)
  J8  percentile <= 0.3 and the change in vol-of-vol (50 bars) above its 80th percentile: the
      side of the bar's move
  J9  directional entropy (32 bars) falls from >= 0.95 to <= 0.75 within 8 bars: the side of the
      32-bar majority
  J11 15m only: the 4h and 1h percentiles <= 0.3 (last closed bars), then a 15m close beyond its
      16-bar box: the breakout's side
  J12 percentile >= 0.8 with expansion age a (bars since it crossed 0.8): the side of the move since
      the onset; reported by age (0-2, 3-8, 9-16, 17+)
  judged    P1R against the walks' P1R for the same setup, day-bootstrap CI, both halves; a setup
            counts if it beats the walks by >= 0.02 in both halves with the CI above 0
  surface   gradient boosting of 1R-first on the state (percentile, vol-of-vol, entropy, efficiency,
            age, 1h/4h percentile, hour) per setup, first half trains, second half scores; AUC on
            markets against the same on walks
"""
from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research" / "harness"))
sys.path.insert(0, str(ROOT / "research"))
sys.path.insert(0, str(ROOT))

OUT = Path(os.environ.get("OUT", ".data/attainment"))
SEQLAB = os.environ.get("SEQLAB", ".data/seqlab")
HMAX = 200
STATE = ["pct", "volvol", "entropy", "efficiency", "age", "pct_1h", "pct_4h", "hour"]


def prep(df: pd.DataFrame) -> pd.DataFrame:
    o, h, l, c = (df[k] for k in ("open", "high", "low", "close"))
    pc = c.shift()
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / 14, adjust=False).mean()
    ltr = np.log((h / l).clip(lower=1 + 1e-12))
    slow = ltr.ewm(alpha=1 / 14, adjust=False).mean()
    pct = slow.rolling(1500, min_periods=300).rank(pct=True)
    vv = np.log(ltr.clip(lower=1e-12)).rolling(50).std()
    up = (c.diff() > 0).astype(float).rolling(32).mean().clip(1e-9, 1 - 1e-9)
    ent = -(up * np.log2(up) + (1 - up) * np.log2(1 - up))
    lc = np.log(c)
    eff = lc.diff(16).abs() / lc.diff().abs().rolling(16).sum()
    hot = pct >= 0.8
    onset = hot & ~hot.shift(fill_value=False)
    grp = onset.cumsum()
    age = hot.groupby(grp).cumsum().where(hot, np.nan) - 1
    onset_close = c.where(onset).ffill()
    return pd.DataFrame({"atr": atr, "slow": slow, "ltr": ltr, "pct": pct, "volvol": vv, "dvolvol": vv.diff(),
                         "entropy": ent, "efficiency": eff, "age": age, "since_onset": c - onset_close,
                         "box_hi": h.rolling(16).max().shift(), "box_lo": l.rolling(16).min().shift(),
                         "hour": pd.to_datetime(df["ts"], unit="s", utc=True).dt.hour})


def events(df: pd.DataFrame, f: pd.DataFrame, iv: str) -> list[tuple]:
    """(setup, signal bar, side, R) per pre-registered rule."""
    c, h, l = df["close"].to_numpy(), df["high"].to_numpy(), df["low"].to_numpy()
    n = len(c)
    atr, pct = f["atr"].to_numpy(), f["pct"].to_numpy()
    bh, bl = f["box_hi"].to_numpy(), f["box_lo"].to_numpy()
    out = []
    # J1 and J5
    last = -16
    for i in np.flatnonzero(pct <= 0.2):
        if i - last < 16 or np.isnan(bh[i]):
            continue
        last = i
        H, L = bh[i], bl[i]
        for b in range(i + 1, min(n - 1, i + 17)):
            s = 1 if c[b] > H else (-1 if c[b] < L else 0)
            if s:
                out.append(("J1", b, s, atr[b]))
                for k in range(b + 1, min(n - 1, b + 5)):
                    if L <= c[k] <= H:
                        out.append(("J5", k, -s, atr[k]))
                        break
                break
    # J2
    ratio = np.exp(f["ltr"].to_numpy()) - 1
    for i in np.flatnonzero((np.r_[np.nan, pct[:-1]] <= 0.3) & (ratio >= 2 * (np.exp(np.r_[np.nan, f["slow"].to_numpy()[:-1]]) - 1))):
        s = int(np.sign(c[i] - c[i - 1]))
        if s:
            out.append(("J2", i, s, atr[i]))
    # J6
    imp = c - np.r_[[np.nan] * 3, c[:-3]]
    k = 3
    while k < n - 5:
        if abs(imp[k]) >= 2 * atr[k]:
            s = int(np.sign(imp[k]))
            peak = c[k]
            for j in range(k + 1, min(n - 1, k + 16)):
                ext = l[j] if s > 0 else h[j]
                if s * (peak - ext) >= 0.38 * abs(imp[k]):
                    R = max(abs(c[j] - ext), 0.5 * atr[j])
                    out.append(("J6", j, s, R))
                    k = j
                    break
                peak = max(peak, h[j]) if s > 0 else min(peak, l[j])
        k += 1
    # J7
    q_lo, q_hi = bl + 0.25 * (bh - bl), bh - 0.25 * (bh - bl)
    midb = (bh + bl) / 2
    touched_lo = pd.Series(l <= q_lo).rolling(8).max().to_numpy() > 0
    touched_hi = pd.Series(h >= q_hi).rolling(8).max().to_numpy() > 0
    up = touched_lo & (c > midb) & (np.r_[np.nan, c[:-1]] <= np.r_[np.nan, midb[:-1]])
    dn = touched_hi & (c < midb) & (np.r_[np.nan, c[:-1]] >= np.r_[np.nan, midb[:-1]])
    out += [("J7", i, 1, atr[i]) for i in np.flatnonzero(up)] + [("J7", i, -1, atr[i]) for i in np.flatnonzero(dn)]
    # J8
    dvv = f["dvolvol"]
    hi_dvv = dvv > dvv.rolling(500, min_periods=100).quantile(0.8)
    for i in np.flatnonzero((pct <= 0.3) & hi_dvv.to_numpy()):
        s = int(np.sign(c[i] - c[i - 1]))
        if s:
            out.append(("J8", i, s, atr[i]))
    # J9
    ent = f["entropy"].to_numpy()
    was_high = pd.Series(ent >= 0.95).rolling(8).max().to_numpy() > 0
    maj = np.sign(pd.Series(c).diff().rolling(32).sum().to_numpy())
    for i in np.flatnonzero(was_high & (ent <= 0.75) & (np.r_[np.nan, ent[:-1]] > 0.75)):
        if maj[i]:
            out.append(("J9", i, int(maj[i]), atr[i]))
    # J11 is added by the caller (needs the higher timeframes)
    # J12
    age, since = f["age"].to_numpy(), f["since_onset"].to_numpy()
    for i in np.flatnonzero(~np.isnan(age)):
        s = int(np.sign(since[i]))
        if s and i % 2 == 0:  # every other bar, to thin the overlap
            a = age[i]
            bucket = "J12_age0-2" if a <= 2 else "J12_age3-8" if a <= 8 else "J12_age9-16" if a <= 16 else "J12_age17+"
            out.append((bucket, i, s, atr[i]))
    return out


def race(df: pd.DataFrame, i: int, side: int, R: float) -> dict | None:
    """From the next bar's open: 1R, 2R, 3R before the stop; time to 1R; pathological 1R."""
    o, h, l = df["open"].to_numpy(), df["high"].to_numpy(), df["low"].to_numpy()
    n = len(o)
    if i + 1 >= n or not R > 0:
        return None
    e = o[i + 1]
    z = min(n, i + 1 + HMAX)
    fav = (h[i + 1:z] - e) * side if side > 0 else (e - l[i + 1:z])
    adv = (e - l[i + 1:z]) if side > 0 else (h[i + 1:z] - e)
    out = {}
    stop = np.nonzero(adv >= R)[0]
    t_sl = stop[0] if len(stop) else 10**9
    for m in (1, 2, 3):
        hit = np.nonzero(fav >= m * R)[0]
        t = hit[0] if len(hit) else 10**9
        out[f"p{m}"] = float(t < t_sl)  # a bar through both counts as the stop (t == t_sl)
        if m == 1:
            out["t1"] = float(t + 1) if t < t_sl else np.nan
            # pathological: ignoring the stop, 1R came only after a 2R adverse excursion
            out["patho"] = float(t < 10**9 and (adv[: t + 1] >= 2 * R).any())
    out["resolved"] = float(min(t_sl, 10**9) < 10**9 or out["p1"] > 0)
    return out


def one(job: tuple) -> pd.DataFrame | None:
    from mt5bt import load_bars
    from mt5bt.nulls import garch_walk

    kind, sym, fam, iv = job
    try:
        df = garch_walk(30_000, interval=iv, spread_points=8.0, seed=int(sym)) if kind == "walk" \
            else load_bars(sym, iv, "seqlab", SEQLAB)
    except (OSError, ValueError):
        return None
    if len(df) < 2000:
        return None
    f = prep(df)
    ev = events(df, f, iv)
    if iv == "15m" and kind == "market":
        for tf in ("1h", "4h"):
            try:
                up = load_bars(sym, tf, "seqlab", SEQLAB)
            except (OSError, ValueError):
                break
            fu = prep(up)
            close_up = up["ts"].to_numpy() + {"1h": 3600, "4h": 14400}[tf]
            pos = np.searchsorted(close_up, df["ts"].to_numpy() + 900, side="right") - 1
            f[f"pct_{tf}"] = np.where(pos >= 0, fu["pct"].to_numpy()[np.clip(pos, 0, None)], np.nan)
        if "pct_4h" in f:
            cmp = (f["pct_1h"] <= 0.3) & (f["pct_4h"] <= 0.3)
            ev += [("J11", b, s, R) for (name, b, s, R) in ev if name == "J1" and cmp.iat[b - 1]]
    for col in ("pct_1h", "pct_4h"):
        if col not in f:
            f[col] = np.nan
    rows = []
    mid = len(df) // 2
    for name, i, s, R in ev:
        r = race(df, i, s, R)
        if r is None:
            continue
        sp = df["spread"].iat[i] if "spread" in df and not np.isnan(df["spread"].iat[i]) else np.nan
        rows.append(dict(kind=kind, sym=sym, family=fam, interval=iv, setup=name, i=i, side=s,
                         second=i >= mid, day=int(df["ts"].iat[i] // 86400), spread_pts=sp,
                         R=R, **r, **{k: f[k].iat[i] for k in STATE}))
    print(f"  {kind} {sym} {iv}: {len(rows)} events", flush=True)
    return pd.DataFrame(rows) if rows else None


def main() -> None:
    import expansion_build as eb

    OUT.mkdir(parents=True, exist_ok=True)
    jobs = [("market", s, f, iv) for s, f in eb.FAMILY.items() for iv in ("15m", "1h")]
    jobs += [("walk", str(1700 + k), "walk", iv) for k in range(4) for iv in ("15m", "1h")]
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", "40"))) as pool:
        parts = [p for p in pool.map(one, jobs) if p is not None]
    d = pd.concat(parts, ignore_index=True)
    d.to_pickle(OUT / "events.pkl.gz")  # our own output
    rng = np.random.default_rng(131)
    walk = d[d["kind"] == "walk"].groupby("setup")["p1"].mean()
    res = {}
    for setup, g in d[d["kind"] == "market"].groupby("setup"):
        w = walk.get(setup, np.nan)
        days = g.groupby("day")["p1"].agg(["sum", "count"])
        boots = []
        for _ in range(500):
            pk = days.sample(len(days), replace=True, random_state=int(rng.integers(1 << 30)))
            boots.append(pk["sum"].sum() / pk["count"].sum() - w)
        cell = dict(n=len(g), p1=round(g["p1"].mean(), 4), walk_p1=round(float(w), 4),
                    excess=round(g["p1"].mean() - w, 4),
                    ci=[round(float(np.percentile(boots, 2.5)), 4), round(float(np.percentile(boots, 97.5)), 4)],
                    halves=[round(g.loc[~g["second"], "p1"].mean() - w, 4), round(g.loc[g["second"], "p1"].mean() - w, 4)],
                    t1_median=float(g["t1"].median()), p2=round(g["p2"].mean(), 4), p3=round(g["p3"].mean(), 4),
                    patho=round(g["patho"].mean(), 4),
                    by_family={f: round(x["p1"].mean() - w, 4) for f, x in g.groupby("family")})
        cell["counts"] = bool(min(cell["halves"]) >= 0.02 and cell["ci"][0] > 0)
        res[setup] = cell
        print(setup, json.dumps(cell), flush=True)
    # the attainment surface: does the state predict 1R-first, beyond the walks?
    from sklearn.ensemble import HistGradientBoostingClassifier

    from till_infinity.models.shocks_train import auc
    surface = {}
    for kind in ("market", "walk"):
        for setup, g in d[d["kind"] == kind].groupby("setup"):
            if len(g) < 2000:
                continue
            X, y = g[STATE].to_numpy(float), g["p1"].to_numpy()
            tr = ~g["second"].to_numpy()
            X[:, np.all(np.isnan(X[tr]), axis=0)] = 0.0
            m = HistGradientBoostingClassifier(max_depth=3, max_iter=150, learning_rate=0.05,
                                               min_samples_leaf=200).fit(X[tr], y[tr])
            surface[f"{kind}/{setup}"] = round(auc(y[~tr], m.predict_proba(X[~tr])[:, 1]), 4)
    res["surface_auc"] = surface
    print(json.dumps(surface, indent=1), flush=True)
    (OUT / "attainment.json").write_text(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    main()
