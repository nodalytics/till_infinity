"""What a wick carries: Part B of the wicks study (frozen in `wick_rule.json`).

Per bar of one series (real, a matched walk, or a fitted generator path): the wick's size and share,
its context (swing, sweep, round number, LRC band, previous day's extreme, repeated wicks, extended
trend, session, rollover, reopen, wide spread, calendar times), the rejection outcome after a long
wick, forward returns over 1/5/20 bars, and next-bar range and 5-bar realised variance. Stored as a
uniform sample of bars plus the long-wick bars, with exact histograms from every bar; the report fits
the models and the walk twins.
"""
from __future__ import annotations

import zlib

import numpy as np
import pandas as pd

import lrc_retest as LR
import wick_levels as WL

LONG_SHARE, LONG_MIN = 0.4, 0.25
REJ_X = 1.0
N_SAMPLE, N_LONG = 25_000, 40_000
WARM = 250
HBINS = np.r_[np.arange(0, 3.0001, 0.05), np.inf]
SBINS = np.linspace(0, 1, 21)
HTF = {"15m": 3600, "1h": 14400, "4h": 86400}
FEATS = ["r1", "r5", "r20", "s50", "s20", "rA", "vstate", "uA", "lA", "ush", "lsh", "bodyA", "clv", "wpi5", "wpi20",
         "d_sh", "d_sl", "d_round", "d_band", "d_pdh", "d_pdl", "h_ush", "h_lsh", "h_clv", "h_slope", "hsin", "hcos",
         "dow", "rollover", "reopen"]
VOL_BASE = ["lrA", "lr5", "lr20", "lpk", "lgk"]
VOL_WICK = ["uA", "lA", "wsh", "wasym", "wsh5", "wA5"]


def _ny_minutes(ts, tz):
    t = pd.to_datetime(np.asarray(ts, np.int64), unit="s", utc=True).tz_convert(tz)
    return (t.hour * 60 + t.minute).to_numpy()


def span_has(ts, sec, tz, minute):
    """Whether the bar [ts, ts + sec) contains the local clock time `minute` (minutes after midnight)."""
    m0 = _ny_minutes(ts, tz)
    return (m0 <= minute) & (minute < m0 + sec // 60)


def htf_feats(df, a, iv):
    """The last completed higher-timeframe bar (UTC blocks built from this series' bars) at the close of t:
    upper and lower wick shares, close location and its change over 5 blocks / ATR of t."""
    n = len(df)
    out = {k: np.full(n, np.nan) for k in ("h_ush", "h_lsh", "h_clv", "h_slope", "h_wi")}
    if iv not in HTF:
        return out
    HS, sec = HTF[iv], WL.SEC[iv]
    ts = df["ts"].to_numpy(np.int64)
    b = ts // HS
    g = pd.DataFrame({"b": b, "o": df["open"].to_numpy(float), "h": df["high"].to_numpy(float),
                      "l": df["low"].to_numpy(float), "c": df["close"].to_numpy(float)}).groupby("b")
    B = pd.DataFrame({"o": g["o"].first(), "h": g["h"].max(), "l": g["l"].min(), "c": g["c"].last()})
    r = (B["h"] - B["l"]).to_numpy()
    rr = np.where(r > 0, r, np.nan)
    ush = (B["h"] - np.maximum(B["o"], B["c"])).to_numpy() / rr
    lsh = (np.minimum(B["o"], B["c"]) - B["l"]).to_numpy() / rr
    clv = (B["c"] - B["l"]).to_numpy() / rr
    c5 = B["c"].diff(5).to_numpy()
    ids = B.index.to_numpy()
    closes_block = (ts + sec) % HS == 0
    done = np.where(closes_block, b, b - 1)
    k = np.searchsorted(ids, done)
    ok = (k < len(ids)) & (ids[np.minimum(k, len(ids) - 1)] == done)
    kk = np.minimum(k, len(ids) - 1)
    out["h_ush"] = np.where(ok, ush[kk], np.nan)
    out["h_lsh"] = np.where(ok, lsh[kk], np.nan)
    out["h_clv"] = np.where(ok, clv[kk], np.nan)
    out["h_slope"] = np.where(ok, c5[kk], np.nan) / a
    out["h_wi"] = out["h_lsh"] - out["h_ush"]
    return out


def first_after(mask, lo, hi):
    return WL.first_after(mask, lo, hi)


def bar_rows(df, cost_px, iv, seed, spread=None, tape_ctx=None, deriv=False):
    """(sample rows, long-wick rows, histograms, trades) for one series."""
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    ts = df["ts"].to_numpy(np.int64)
    n = len(c)
    sec = WL.SEC[iv]
    a = LR.atr(h, l, c)
    aa = np.where(a > 0, a, np.nan)
    top, bot = np.maximum(o, c), np.minimum(o, c)
    u, lw, r = h - top, bot - l, h - l
    rr = np.where(r > 0, r, np.nan)
    uA, lA, rA = u / aa, lw / aa, r / aa
    ush, lsh = np.nan_to_num(u / rr), np.nan_to_num(lw / rr)
    clv = np.where(r > 0, (c - l) / np.where(r > 0, r, 1), 0.5)
    long_up = (ush >= LONG_SHARE) & (uA >= LONG_MIN)
    long_dn = (lsh >= LONG_SHARE) & (lA >= LONG_MIN)
    conf = ts >= WL.SPLIT
    ok = np.zeros(n, bool)
    ok[WARM:n - 21] = True
    ok &= np.isfinite(aa)
    # ---- exact histograms (every bar)
    hist = {}
    for per, m in (("disc", ok & ~conf), ("conf", ok & conf)):
        hist[per] = dict(n=int(m.sum()),
                         up=np.histogram(uA[m], HBINS)[0], dn=np.histogram(lA[m], HBINS)[0],
                         ush=np.histogram(ush[m], SBINS)[0], lsh=np.histogram(lsh[m], SBINS)[0],
                         long_up=int((long_up & m).sum()), long_dn=int((long_dn & m).sum()))
    # ---- cheap full-length features
    def chg(k):
        x = np.full(n, np.nan)
        x[k:] = c[k:] - c[:-k]
        return x / aa
    def fwd(k):
        x = np.full(n, np.nan)
        x[:-k] = c[k:] - c[:-k]
        return x / aa
    s50, mid50, dev50 = LR.lrc(c, 50)
    s20, _, _ = LR.lrc(c, 20)
    a5, a50 = LR.atr(h, l, c, 5), LR.atr(h, l, c, 50)
    wi = lA - uA
    wpi5 = pd.Series(wi).rolling(5).sum().to_numpy()
    wpi20 = pd.Series(wi).rolling(20).sum().to_numpy()
    rs = pd.Series(r)
    r5 = rs.rolling(5).mean().to_numpy()
    r20 = rs.rolling(20).mean().to_numpy()
    pk = (rs ** 2).rolling(20).mean().to_numpy() / (4 * np.log(2))
    gk = (0.5 * rs ** 2 - (2 * np.log(2) - 1) * pd.Series(c - o) ** 2).rolling(20).mean().to_numpy()
    wsh = np.nan_to_num((u + lw) / rr)
    F = dict(r1=chg(1), r5=chg(5), r20=chg(20), s50=s50 / aa, s20=s20 / aa, rA=rA, vstate=np.log(a5 / np.where(a50 > 0, a50, np.nan)),
             uA=uA, lA=lA, ush=ush, lsh=lsh, bodyA=(c - o) / aa, clv=clv, wpi5=wpi5, wpi20=wpi20,
             d_band=(c - mid50) / np.where(dev50 > 0, dev50, np.nan),
             wbr=np.log(np.maximum((u + lw) / aa, 1e-3) / (np.abs(c - o) / aa + 0.05)), wi=np.nan_to_num(lsh - ush),
             fr1=fwd(1), fr5=fwd(5), fr20=fwd(20),
             lrA=np.log(np.maximum(rA, 1e-3)), lr5=np.log(np.maximum(r5 / aa, 1e-3)), lr20=np.log(np.maximum(r20 / aa, 1e-3)),
             lpk=np.log(np.maximum(pk / aa ** 2, 1e-6)), lgk=np.log(np.maximum(gk / aa ** 2, 1e-6)),
             wsh=wsh, wasym=np.nan_to_num(np.abs(u - lw) / rr),
             wsh5=pd.Series(wsh).rolling(5).mean().to_numpy(), wA5=pd.Series(uA + lA).rolling(5).mean().to_numpy())
    nxt_r = np.r_[r[1:], np.nan]
    F["y_rng"] = np.log(np.maximum(nxt_r / aa, 1e-3))
    dc = np.r_[np.diff(c), np.nan]
    rv5 = pd.Series(dc ** 2).rolling(5).sum().shift(-4).to_numpy()  # sum of the next 5 squared changes
    F["y_rv5"] = np.log(rv5 / aa ** 2 + 1e-4)
    F["long_up_next"] = np.r_[long_up[1:], False].astype(np.int8)
    F["long_dn_next"] = np.r_[long_dn[1:], False].astype(np.int8)
    F.update(htf_feats(df, aa, iv))
    hr = (ts // 3600) % 24
    F["hour"] = hr
    F["hsin"], F["hcos"] = np.sin(2 * np.pi * hr / 24), np.cos(2 * np.pi * hr / 24)
    F["dow"] = ((ts // 86400) + 3) % 7
    intraday = iv != "1d"
    F["rollover"] = span_has(ts, sec, "America/New_York", 17 * 60) if intraday else np.zeros(n, bool)
    F["news"] = span_has(ts, sec, "America/New_York", 8 * 60 + 30) if intraday else np.zeros(n, bool)
    F["ny_open"] = span_has(ts, sec, "America/New_York", 9 * 60 + 30) if intraday else np.zeros(n, bool)
    F["ldn_open"] = span_has(ts, sec, "Europe/London", 8 * 60) if intraday else np.zeros(n, bool)
    F["reopen"] = np.r_[False, np.diff(ts) > 2 * 86400]
    if spread is not None and len(spread) == n and np.isfinite(spread).any():
        med = np.nanmedian(spread)
        F["wide"] = spread > 3 * med if med > 0 else np.zeros(n, bool)
    else:
        F["wide"] = np.zeros(n, bool)
    # ---- the rows we keep
    rng = np.random.default_rng(seed)
    cand = np.flatnonzero(ok)
    samp = np.sort(rng.choice(cand, min(N_SAMPLE, len(cand)), replace=False)) if len(cand) else cand
    lu = np.flatnonzero(ok & long_up)
    ld = np.flatnonzero(ok & long_dn)
    lrows = np.r_[lu, ld]
    ldir = np.r_[np.ones(len(lu), np.int8), -np.ones(len(ld), np.int8)]
    if len(lrows) > N_LONG:
        pick = np.sort(rng.choice(len(lrows), N_LONG, replace=False))
        lrows, ldir = lrows[pick], ldir[pick]
    need = np.union1d(samp, lrows)
    # ---- expensive context, only where needed
    ph, pl = WL.pivot_high(h), WL.pivot_high(-l)
    ph_i, pl_i = np.flatnonzero(ph), np.flatnonzero(pl)
    d_sh = np.full(n, np.nan)
    d_sl = np.full(n, np.nan)
    at_sh = np.zeros(n, bool)
    at_sl = np.zeros(n, bool)
    sw_h = np.zeros(n, bool)
    sw_l = np.zeros(n, bool)
    for t in need:
        # the latest pivot high known before bar t (p + 3 <= t - 1) and still standing at t - 1
        k = np.searchsorted(ph_i, t - 4, "right") - 1
        if k >= 0:
            p = ph_i[k]
            if h[p + 1:t].max(initial=-np.inf) <= h[p]:
                d_sh[t] = (h[p] - c[t]) / aa[t]
                at_sh[t] = h[t] >= h[p] - 0.25 * aa[t]
                sw_h[t] = h[t] > h[p] and c[t] <= h[p]
        k = np.searchsorted(pl_i, t - 4, "right") - 1
        if k >= 0:
            p = pl_i[k]
            if l[p + 1:t].min(initial=np.inf) >= l[p]:
                d_sl[t] = (c[t] - l[p]) / aa[t]
                at_sl[t] = l[t] <= l[p] + 0.25 * aa[t]
                sw_l[t] = l[t] < l[p] and c[t] >= l[p]
    step = 10.0 ** np.ceil(np.log10(np.where(aa > 0, aa, 1)))
    rnd_c = np.round(c / step) * step
    d_round = np.abs(c - rnd_c) / aa
    at_rnd_h = np.abs(h - np.round(h / step) * step) <= 0.1 * aa
    at_rnd_l = np.abs(l - np.round(l / step) * step) <= 0.1 * aa
    up_band = np.r_[np.nan, (mid50 + 2 * dev50)[:-1]]
    dn_band = np.r_[np.nan, (mid50 - 2 * dev50)[:-1]]
    day = ts // 86400
    if intraday:
        g = pd.DataFrame({"d": day, "h": h, "l": l}).groupby("d").agg(h=("h", "max"), l=("l", "min"))
        days = g.index.to_numpy()
        k = np.searchsorted(days, day) - 1  # the previous day present in the data
        okd = k >= 0
        pdh = np.where(okd, g["h"].to_numpy()[np.maximum(k, 0)], np.nan)
        pdl = np.where(okd, g["l"].to_numpy()[np.maximum(k, 0)], np.nan)
    else:
        pdh = pdl = np.full(n, np.nan)
    F["d_pdh"] = (pdh - c) / aa
    F["d_pdl"] = (c - pdl) / aa
    F["d_sh"], F["d_sl"], F["d_round"] = d_sh, d_sl, d_round
    # ---- sample table
    keep_cols = FEATS + ["wi", "wbr", "fr1", "fr5", "fr20", "y_rng", "y_rv5", "long_up_next", "long_dn_next", "h_wi",
                         "hour", "news", "ny_open", "ldn_open", "wide"] + VOL_BASE + VOL_WICK
    keep_cols = list(dict.fromkeys(keep_cols))
    S = pd.DataFrame({k: np.asarray(F[k])[samp] for k in keep_cols})
    S.insert(0, "ts", ts[samp])
    S.insert(1, "t", samp)
    # ---- long-wick rows: rejection, context flags
    rows = []
    wb, uu, tp = WL.wick_bars(o, h, l, c, a)
    wbl, ul, tpl = WL.wick_bars(-o, -l, -h, -c, a)
    for t, d in zip(lrows, ldir):
        end = min(n - 1, t + WL.HORIZON)
        if d > 0:
            away = first_after(l <= c[t] - REJ_X * a[t], t + 1, end)
            back = first_after(h >= h[t], t + 1, end)
            ext, size, share = h[t], uA[t], ush[t]
            at_sw, sweep, at_rnd = at_sh[t], sw_h[t], at_rnd_h[t]
            at_band = h[t] >= up_band[t] if np.isfinite(up_band[t]) else False
            at_pd = (h[t] >= pdh[t] - 0.25 * a[t]) if np.isfinite(pdh[t]) else False
            exhaust = (c[t] - c[t - 20]) >= 3 * a[t]
            hh, cc, tpp, wbb, uuu = h, c, tp, wb, uu
            pe = h[t]
        else:
            away = first_after(h >= c[t] + REJ_X * a[t], t + 1, end)
            back = first_after(l <= l[t], t + 1, end)
            ext, size, share = l[t], lA[t], lsh[t]
            at_sw, sweep, at_rnd = at_sl[t], sw_l[t], at_rnd_l[t]
            at_band = l[t] <= dn_band[t] if np.isfinite(dn_band[t]) else False
            at_pd = (l[t] <= pdl[t] + 0.25 * a[t]) if np.isfinite(pdl[t]) else False
            exhaust = (c[t - 20] - c[t]) >= 3 * a[t]
            hh, cc, tpp, wbb, uuu = -l, -c, tpl, wbl, ul
            pe = -l[t]
        if away < 0 and back < 0:
            rej = np.nan
        elif away == back:
            rej = np.nan
        else:
            rej = 1.0 if (away >= 0 and (back < 0 or away < back)) else 0.0
        # absorption: Part A's member rule at the wick extreme, bars [t - 200, t]
        tol = WL.TOL * a[t]
        lo = max(0, t - WL.LB)
        mem = wbb[lo:t + 1] & (np.abs(hh[lo:t + 1] - pe) <= tol) & (tpp[lo:t + 1] <= pe - tol)
        K = WL.runs(mem)
        rows.append((t, ts[t], d, size, share, rej, at_sw, sweep, at_rnd, at_band, at_pd, K, exhaust))
    Lw = pd.DataFrame(rows, columns=["t", "ts", "dir", "size", "share", "rej", "at_swing", "sweep", "at_round",
                                     "at_band", "at_pdx", "K", "exhaust"])
    if len(Lw):
        for k in FEATS + ["hour", "news", "ny_open", "ldn_open", "wide", "rollover", "reopen"]:
            Lw[k] = np.asarray(F[k])[Lw["t"].to_numpy()]
        for k in ("bool_cast",):
            pass
        # dist to the swing on the wick's side: d_sh for upper, d_sl for lower
    # ---- B5 trades
    T = trades_b5(o, h, l, c, ts, a, cost_px, Lw, wpi20, conf, tape_ctx)
    return S, Lw, hist, T


def trades_b5(o, h, l, c, ts, a, cost_px, Lw, wpi20, conf, tape_ctx):
    """T_REJ: at a long wick at a level (AT_SWING or ABSORB), against the wick at the next open, stop beyond
    the wick extreme + 0.1 ATR (min 0.25 ATR), E1. T_WPI: WPI20 beyond its own discovery 10/90% quantile,
    toward the pressure at the next open, stop beyond the last 3 bars' extreme + 0.1 ATR, E1; one at a time."""
    n = len(c)
    out = []
    X = (o, h, l, c)
    XN = (-o, -l, -h, -c)

    def trade(kind, side, t, stop_px, extra):
        f = t + 1
        if f >= n - 1 or not a[t] > 0:
            return None
        A = a[t]
        if side > 0:
            ent = o[f]
            stop = min(stop_px, ent - WL.MIN_RISK * A)
            R, xb, entry, risk, fp = WL.exits_e1(*X, f, ent, stop, A, cost_px[f])
        else:
            ent = o[f]
            stop = max(stop_px, ent + WL.MIN_RISK * A)
            R, xb, entry, risk, fp = WL.exits_e1(*XN, f, -ent, -stop, A, cost_px[f])
        r = dict(kind=kind, side=side, t=int(t), ts=int(ts[f]), R=R, cost_R=cost_px[f] / risk, risk_atr=risk / A,
                 xb=int(xb), **{f"fp{N}": v for N, v in zip(WL.NS, fp)}, **extra)
        if tape_ctx is not None:
            tape, tts, sec = tape_ctx
            HC = (h, c) if side > 0 else (-l, -c)
            res = WL.tick_fill(tape, side, tts, sec, HC[0], HC[1], f, "market", ent, stop, A)
            if res is None:
                r.update(R_tick=np.nan, **{f"tfp{N}": -1 for N in WL.NS})
            else:
                r.update(R_tick=res[0], **{f"tfp{N}": v for N, v in zip(WL.NS, res[2])})
        return r, xb

    if len(Lw):
        sel = Lw[(Lw["at_swing"].astype(bool)) | (Lw["K"] >= 2)]
        for t, d, K, sw in zip(sel["t"].to_numpy(), sel["dir"].to_numpy(), sel["K"].to_numpy(), sel["at_swing"].to_numpy()):
            stop_px = h[t] + 0.1 * a[t] if d > 0 else l[t] - 0.1 * a[t]
            res = trade("T_REJ", -int(d), int(t), stop_px, dict(K=int(K), at_swing=bool(sw)))
            if res:
                out.append(res[0])
    disc = ~conf & np.isfinite(wpi20)
    if disc.sum() > 500:
        q10, q90 = np.quantile(wpi20[disc], [0.1, 0.9])
        busy = {1: -1, -1: -1}
        for t in np.flatnonzero(np.isfinite(wpi20)):
            if t < WARM or t >= n - 2:
                continue
            for side, cond in ((1, wpi20[t] >= q90), (-1, wpi20[t] <= q10)):
                if not cond or t <= busy[side]:
                    continue
                stop_px = (l[t - 2:t + 1].min() - 0.1 * a[t]) if side > 0 else (h[t - 2:t + 1].max() + 0.1 * a[t])
                res = trade("T_WPI", side, int(t), stop_px, dict(wpi=float(wpi20[t])))
                if res:
                    out.append(res[0])
                    busy[side] = res[1]
    return pd.DataFrame(out)
