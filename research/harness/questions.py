"""Six sharper questions in search of a directional edge, scored identically.

`horizons.py` asked one question at every bar: "does a symmetric race to +-B
within H end up or down?". Three things were wrong with that as a search:
it asks at bars with no reason to ask, market drift leaks into it, and it only
knows a 1:1 payoff. Each question here removes one of those.

  Q1 continuation  the current zigzag swing has travelled S: does it extend 0.5S
                   before giving back 0.5S? Pools up and down swings, so drift cancels.
  Q2 relative      log(A/B) for pairs in one family: does A outperform by B before
                   underperforming by B? The common factor is gone by construction.
  Q3 events        the symmetric race, asked only after a reason: a 4x shock bar, a
                   fresh 50-bar extreme, a compressed-range breakout, a session
                   open, a volatility alarm.
  Q4 asymmetric    +3:-1 and +1:-2 races, long and short, at every bar and after
                   the reversal-shaped events.
  Q5 entry         for a long (and a short) intent held to H: does a limit 0.5 units
                   better fill? The value is choosing limit vs market per bar.
  Q6 path shape    predict log(MFE/MAE) over H, trade the extremes.

Unit U = baseline x sqrt(H), baseline = trailing mean |r|. Races resolve on each bar's high and
low (wicks take stops), fill at the level or at the open on a gap, and a bar spanning both
levels is scored as the stop. Pairs have no bar, so Q2 resolves on closes.

Scoring is the same everywhere: a gradient-boosted model fit on each series' first
60% by time; trades taken where its probability sits beyond the 80th / 20th
percentile *of its training predictions* (no test peeking); test trades thinned so
no two in one series overlap; R in units of the stop, net of an assumed spread;
the two halves of the test period reported separately; every question compared
against the simple rule a trader would try first. With this many cells about one
in twenty clears two standard errors by chance, so the bar is |t| >= 3 net with
both halves agreeing.

Spread assumption (round trip, in M5 volatility units, scaled by sqrt(5min/interval)):
fx 0.8, metal 0.16, crypto 0.5, index 0.5 - from catalogue.md where measured,
guessed for indices. Pairs pay both legs.

Run from the repository root:  .venv-research/bin/python research/harness/questions.py
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.metrics import roc_auc_score

sys.path.insert(0, str(Path(__file__).parent))
from bars import Bars, Fitted, long_R, paths, race
from crashlab import features
from horizons import build, seasonal
from spikerisk import DAILY, DB, SERIES, SETUPS, load

H_FOR = {"15m": 8, "1h": 5, "1d": 5}
MINUTES = {"15m": 15, "1h": 60, "1d": 1440}
COST_V = {"fx": 0.8, "metal": 0.16, "crypto": 0.5, "index": 0.5}
PAIRS = {
    "15m": [("EURUSD", "GBPUSD", "fx"), ("AUDUSD", "NZDUSD", "fx"), ("BTCUSD", "ETHUSD", "crypto"),
            ("ETHUSD", "SOLUSD", "crypto"), ("US500", "NAS100", "index")],
    "1d": [("EURUSD", "GBPUSD", "fx"), ("BTCUSD", "ETHUSD", "crypto"), ("SPX500USD", "NAS100USD", "index")],
}
PAIRS["1h"] = PAIRS["15m"]
VENUE = {  # per interval: BTCUSD is Coinbase intraday and Bitstamp daily
    "15m": {t: v for fam in SERIES.values() for t, v in fam},
    "1d": {t: v for fam in DAILY.values() for t, v in fam},
}
VENUE["1h"] = VENUE["15m"]
SIGNED = ["mom5", "mom20", "mom60", "zscore20", "macd", "fatigue", "impulse", "swing_ext", "season_drift",
          "cx_mom", "skew100", "last"]

ROWS: list[dict] = []


# ---------------------------------------------------------------- path machinery

def thin(d, mask, H):
    """Keep an event only if no kept event in the same series is fewer than H bars earlier."""
    keep = np.zeros(len(d), bool)
    pos, tick = d["_pos"].to_numpy(), d["ticker"].to_numpy()
    last = {}
    for i in np.flatnonzero(mask):
        if pos[i] - last.get(tick[i], -10**9) >= H:
            keep[i] = True
            last[tick[i]] = pos[i]
    return keep


def cost_R(d, interval, stop_log):
    """Round-trip spread in stop units."""
    v = d.family.map(COST_V).to_numpy() * d["_base"].to_numpy() / np.sqrt(MINUTES[interval] / 5)
    return v / stop_log


def gbm():
    return HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=200,
                                          min_samples_leaf=200, l2_regularization=1.0)


# ---------------------------------------------------------------- scoring

def report(q, variant, interval, d, taken, pnl_net, pnl_gross, auc=np.nan, note=""):
    """taken: boolean mask of thinned test trades; pnl arrays aligned to d."""
    split = d.split.to_numpy()
    x = pnl_net[taken]
    n = len(x)
    se = x.std(ddof=1) / np.sqrt(n) if n > 1 else np.nan
    halves = [pnl_net[taken & (split == s)].mean() if (taken & (split == s)).any() else np.nan for s in (1, 2)]
    fam = d.family.to_numpy()
    fams = {f: pnl_net[taken & (fam == f)].mean() for f in COST_V if (taken & (fam == f)).sum() >= 15}
    row = dict(q=q, variant=variant, interval=interval, n=n, gross=pnl_gross[taken].mean() if n else np.nan,
               net=x.mean() if n else np.nan, se=se, t=x.mean() / se if n > 1 and se > 0 else np.nan,
               a=halves[0], b=halves[1], win=np.mean(x > 0) if n else np.nan, auc=auc, note=note,
               **{f"fam_{k}": v for k, v in fams.items()})
    ROWS.append(row)
    flag = "  <==" if n > 1 and row["t"] >= 3 and halves[0] > 0 and halves[1] > 0 else ""
    fs = " ".join(f"{k[:3]}{v:+.2f}" for k, v in fams.items())
    print(f"  {q:<3} {variant:<34} n={n:>5} gross {row['gross']:+.3f} net {row['net']:+.3f} +- {se:.3f} "
          f"t={row['t']:+.1f} | {halves[0]:+.2f} {halves[1]:+.2f} | win {row['win']:.0%} "
          f"auc {auc:.3f} | {fs}{flag}")


def two_sided(q, variant, interval, d, X, events, label, R_long, R_short, cost, H, rules=()):
    """Model P(label) on events; long above train-80th, short below train-20th. Plus simple rules."""
    split = d.split.to_numpy()
    tr = events & (split == 0) & ~np.isnan(R_long)
    te = events & (split > 0) & ~np.isnan(R_long)
    if tr.sum() < 300 or te.sum() < 50 or label[tr].min() == label[tr].max():
        return
    m = Fitted(gbm(), X[tr], label[tr])
    p = np.full(len(d), np.nan)
    p[tr | te] = m.predict_proba(X[tr | te])[:, 1]
    hi, lo = np.quantile(p[tr], 0.8), np.quantile(p[tr], 0.2)
    auc = roc_auc_score(label[te], p[te]) if 0 < label[te].mean() < 1 else np.nan
    side = np.where(p >= hi, 1, np.where(p <= lo, -1, 0))
    gross = np.where(side == 1, R_long, np.where(side == -1, R_short, np.nan))
    taken = thin(d, te & (side != 0), H)
    report(q, variant + " [model]", interval, d, taken, gross - cost, gross, auc)
    for name, rule in rules:
        s = rule(te)
        g = np.where(s == 1, R_long, np.where(s == -1, R_short, np.nan))
        report(q, variant + f" [{name}]", interval, d, thin(d, te & (s != 0), H), g - cost, g)


def one_sided(q, variant, interval, d, X, events, R, cost, H):
    """Model P(R wins) on events; take above train-80th. Compared with taking every event."""
    split = d.split.to_numpy()
    y = (R > 0).astype(float)
    tr = events & (split == 0) & ~np.isnan(R)
    te = events & (split > 0) & ~np.isnan(R)
    if tr.sum() < 300 or te.sum() < 50 or y[tr].min() == y[tr].max():
        return
    m = Fitted(gbm(), X[tr], y[tr])
    p = np.full(len(d), np.nan)
    p[tr | te] = m.predict_proba(X[tr | te])[:, 1]
    auc = roc_auc_score(y[te], p[te]) if 0 < y[te].mean() < 1 else np.nan
    pick = te & (p >= np.quantile(p[tr], 0.8))
    report(q, variant + " [model]", interval, d, thin(d, pick, H), R - cost, R, auc)
    report(q, variant + " [every event]", interval, d, thin(d, te, H), R - cost, R)


# ---------------------------------------------------------------- the questions

def event_masks(d, interval):
    z, split = d["_z"].to_numpy(), d.split.to_numpy()
    t = pd.to_datetime(d.ts.to_numpy(), unit="s")
    bbpct = d.groupby("ticker").bbwidth.transform(lambda s: s.rolling(500, min_periods=200).rank(pct=True)).to_numpy()
    zs = d.zscore20.to_numpy()
    alarm = d["short"].to_numpy() >= np.nanquantile(d["short"].to_numpy()[split == 0], 0.95)
    ev = {
        "shock_dn": z < -4, "shock_up": z > 4,
        "new_low": (d["_lc"] <= d.groupby("ticker")["_lc"].transform(lambda s: s.rolling(50, min_periods=40).min())).to_numpy(),
        "new_high": (d["_lc"] >= d.groupby("ticker")["_lc"].transform(lambda s: s.rolling(50, min_periods=40).max())).to_numpy(),
        "breakout_up": (bbpct <= 0.2) & (zs > 2), "breakout_dn": (bbpct <= 0.2) & (zs < -2),
        "vol_alarm": alarm,
    }
    if interval != "1d":
        ev["london_open"] = (t.hour == 7) & (t.minute == 0)
        ev["ny_open"] = (t.hour == 13) & (t.minute == 0)
    return {k: np.asarray(v, bool) for k, v in ev.items()}


def q1_continuation(d, X, cols, interval, H, fut):
    ext = d.swing_ext.to_numpy()
    base = d["_base"].to_numpy()
    direction = np.sign(ext)
    S = np.abs(ext) * base
    events = np.abs(ext) >= 3
    rel = np.column_stack([X[:, cols.index(c)] * direction for c in SIGNED if c in cols])
    Xr = np.column_stack([X, rel])
    f = fut * direction[:, None]  # continuation-relative path
    R, w = long_R(f, 0.5 * S, 0.5 * S)
    Rrev, _ = long_R(f * -1, 0.5 * S, 0.5 * S)  # its own race: a bar spanning both stops both
    cost = cost_R(d, interval, 0.5 * S)
    label = (w == 1).astype(float)
    two_sided("Q1", "continue vs reverse, 0.5S", interval, d, Xr, events, label, R, Rrev, cost, H,
              rules=[("always continue", lambda te: np.where(te, 1, 0)),
                     ("always reverse", lambda te: np.where(te, -1, 0))])
    for lo_, hi_ in ((3, 5), (5, 8), (8, 1e9)):
        e = events & (np.abs(ext) >= lo_) & (np.abs(ext) < hi_)
        te = e & (d.split.to_numpy() > 0) & ~np.isnan(R)
        report("Q1", f"always continue, S in [{lo_},{hi_:g})", interval, d, thin(d, te, H), R - cost, R)


def pair_frame(interval):
    """One frame per pair: features of log(A/B) as if it were a price, close-only (a ratio has no bar)."""
    seconds, _, long, season = SETUPS[interval]
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    parts = []
    for a, b, fam in PAIRS[interval]:
        A, B_ = load(conn, a, VENUE[interval][a], interval), load(conn, b, VENUE[interval][b], interval)
        m = A.merge(B_, on="ts", suffixes=("_a", "_b"))
        m = m[(m.close_a > 0) & (m.close_b > 0)].reset_index(drop=True)
        if len(m) < long * 3:
            continue
        s = np.exp(np.log(m.close_a) - np.log(m.close_b))
        df = pd.DataFrame({"ts": m.ts, "high": s, "close": s})
        o = features(df, seconds, long, season)
        o = pd.concat([o, seasonal(o, df, seconds)], axis=1)
        for leg, col in (("a", "close_a"), ("b", "close_b")):
            r = np.log(m[col]).diff().abs()
            o[f"_base_{leg}"] = r.rolling(long, min_periods=long // 2).mean()
        o["family"], o["ticker"] = fam, f"{a}/{b}"
        parts.append(o)
    if not parts:
        return None, None
    d = pd.concat(parts, ignore_index=True)
    d = d[d["_base"].notna()].reset_index(drop=True)
    size = d.groupby("ticker").ts.transform("size")
    d["_pos"] = d.groupby("ticker").cumcount()
    d["split"] = np.select([d._pos < size * 0.6, d._pos < size * 0.8], [0, 1], 2)
    cols = [c for c in d.columns if not c.startswith("_") and c not in ("ts", "family", "ticker", "split")]
    return d, cols


def q2_relative(interval, H):
    d, cols = pair_frame(interval)
    if d is None:
        return
    X = d[cols].to_numpy(float)
    fut = paths(d, H)
    U = 1.5 * d["_base"].to_numpy() * np.sqrt(H)
    R, w = long_R(fut, U, U)
    Rs, _ = long_R(fut * -1, U, U)
    legs = (d["_base_a"] + d["_base_b"]).to_numpy() * d.family.map(COST_V).to_numpy() / np.sqrt(MINUTES[interval] / 5)
    cost = legs / U
    zs, mom = d.zscore20.to_numpy(), d.mom20.to_numpy()
    print(f"\n  Q2 pairs: {', '.join(d.ticker.unique())}")
    two_sided("Q2", "A beats B by U first", interval, d, X, np.ones(len(d), bool), (w == 1).astype(float),
              R, Rs, cost, H,
              rules=[("spread momentum", lambda te: np.where(te, np.sign(mom), 0)),
                     ("spread reversion |z|>2", lambda te: np.where(te & (np.abs(zs) > 2), -np.sign(zs), 0))])


def q3_events(d, X, interval, H, fut, ev):
    U = 1.5 * d["_base"].to_numpy() * np.sqrt(H)
    R, w = long_R(fut, U, U)
    Rs, _ = long_R(fut * -1, U, U)
    cost = cost_R(d, interval, U)
    split = d.split.to_numpy()
    onehot = np.column_stack([ev[k].astype(float) for k in ev])
    Xe = np.column_stack([X, onehot])
    for k, e in ev.items():
        tr = e & (split == 0)
        sgn = 1 if np.nanmean(R[tr]) >= np.nanmean(Rs[tr]) else -1  # the rule picks its side on training data only
        two_sided("Q3", f"{k}", interval, d, Xe, e, (w == 1).astype(float), R, Rs, cost, H,
                  rules=[(f"always {'long' if sgn > 0 else 'short'} (train sign)",
                          lambda te, s=sgn: np.where(te, s, 0))])


def q4_asymmetric(d, X, interval, H, fut, ev):
    unit = d["_base"].to_numpy() * np.sqrt(H)
    everybar = np.ones(len(d), bool)
    for up_, dn_ in ((3, 1), (1, 2)):
        for side in (1, -1):
            R, _ = long_R(fut * side, up_ * unit, dn_ * unit)
            cost = cost_R(d, interval, dn_ * unit)
            nm = f"{'long' if side > 0 else 'short'} +{up_}:-{dn_}"
            one_sided("Q4", f"{nm} every bar", interval, d, X, everybar, R, cost, H)
            # vol_alarm on the short side: can the crash-timing score be *entered* short with a wide target?
            for k in (("shock_dn", "new_low") if side > 0 else ("shock_up", "new_high", "vol_alarm")):
                one_sided("Q4", f"{nm} after {k}", interval, d, X, ev[k], R, cost, H)


def q5_entry(d, X, interval, H, fut):
    unit = d["_base"].to_numpy() * np.sqrt(H)
    split = d.split.to_numpy()
    for side in (1, -1):
        f = fut * side
        X_ = 0.5 * unit
        # the limit fills when a low touches it - at the level, or at the open if the bar gaps below
        fillp = np.full(len(d), np.nan)
        for k in range(H - 1, -1, -1):  # walk backwards so the earliest touch wins
            hit = f.l[:, k] <= -X_
            fillp[hit] = np.minimum(f.o[hit, k], -X_[hit])
        filled = (~np.isnan(fillp)).astype(float)
        end = f.end
        market = end / unit
        limit = np.where(filled == 1, (end - fillp) / unit, 0.0)
        ok = ~np.isnan(end)
        tr, te = ok & (split == 0), ok & (split > 0)
        m = Fitted(gbm(), X[tr], filled[tr])
        p = m.predict_proba(X)[:, 1]
        use_limit = p >= np.median(p[tr])
        smart = np.where(use_limit, limit, market)
        slot = te & ((d["_pos"].to_numpy() % H) == 0)
        auc = roc_auc_score(filled[te], p[te])
        nm = "long" if side > 0 else "short"
        # Value in U, gross of spread (a limit also saves the half-spread a market order pays - not credited).
        print(f"  Q5  {nm} intent: fill rate {filled[te].mean():.1%} auc {auc:.3f} | per trade, U units: "
              f"market {market[slot].mean():+.3f}  always-limit {limit[slot].mean():+.3f}  "
              f"model-chooses {smart[slot].mean():+.3f}  "
              f"(model - best fixed {smart[slot].mean() - max(market[slot].mean(), limit[slot].mean()):+.3f}, "
              f"se {np.std(smart[slot] - market[slot]) / np.sqrt(slot.sum()):.3f}, n={slot.sum()})")
        ROWS.append(dict(q="Q5", variant=f"{nm} limit-vs-market", interval=interval, n=int(slot.sum()),
                         gross=smart[slot].mean() - max(market[slot].mean(), limit[slot].mean()), auc=auc,
                         note=f"market {market[slot].mean():+.3f} limit {limit[slot].mean():+.3f}"))


def q6_shape(d, X, interval, H, fut):
    unit = d["_base"].to_numpy() * np.sqrt(H)
    mfe = np.clip(np.nanmax(fut.h, axis=1), 0, None) / unit   # from the wicks, not the closes
    mae = np.clip(-np.nanmin(fut.l, axis=1), 0, None) / unit
    y = np.log((mfe + 0.1) / (mae + 0.1))
    end = fut.end / unit
    split = d.split.to_numpy()
    ok = ~np.isnan(end)
    tr, te = ok & (split == 0), ok & (split > 0)
    m = HistGradientBoostingRegressor(max_depth=3, learning_rate=0.05, max_iter=200, min_samples_leaf=200,
                                      l2_regularization=1.0).fit(X[tr], y[tr])
    p = m.predict(X)
    rho = spearmanr(p[te], y[te]).statistic
    hi, lo = np.quantile(p[tr], 0.8), np.quantile(p[tr], 0.2)
    side = np.where(p >= hi, 1, np.where(p <= lo, -1, 0))
    cost = cost_R(d, interval, unit)
    gross = side * end
    taken = thin(d, te & (side != 0), H)
    report("Q6", "log(MFE/MAE) extremes, hold to H", interval, d, taken, gross - cost, gross, note=f"spearman {rho:.3f}")
    for s, nm in ((1, "top"), (-1, "bottom")):
        k = te & (side == s)
        print(f"      {nm} 20%: mean MFE {mfe[k].mean():.2f}U  MAE {mae[k].mean():.2f}U   (all: {mfe[te].mean():.2f} / {mae[te].mean():.2f}), spearman {rho:.3f}")


def main():
    for interval in ("15m", "1h", "1d"):
        H = H_FOR[interval]
        universe = DAILY if interval == "1d" else SERIES
        d, cols = build(interval, universe)
        d = d.drop(columns=[c for c in d.columns if "@" in c])
        X = d[cols].to_numpy(float)
        fut = paths(d, H)
        ev = event_masks(d, interval)
        print(f"\n{'=' * 120}\n{interval}  H={H} bars  {d.ticker.nunique()} series  {len(d):,} bars  "
              f"events: " + ", ".join(f"{k} {v.sum()}" for k, v in ev.items()))
        q1_continuation(d, X, cols, interval, H, fut)
        q2_relative(interval, H)
        q3_events(d, X, interval, H, fut, ev)
        q4_asymmetric(d, X, interval, H, fut, ev)
        q5_entry(d, X, interval, H, fut)
        q6_shape(d, X, interval, H, fut)
    out = pd.DataFrame(ROWS)
    Path(".data/research").mkdir(parents=True, exist_ok=True)
    out.to_csv(".data/research/questions.csv", index=False)
    s = out.dropna(subset=["t"])
    print(f"\n{len(s)} scored cells; |t|>=2: {(s.t.abs() >= 2).sum()}, t>=3 net with both halves > 0: "
          f"{((s.t >= 3) & (s.a > 0) & (s.b > 0)).sum()}")


if __name__ == "__main__":
    main()
