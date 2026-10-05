"""Trade, grid and account engines for the geraked Expert Advisors.

Re-expresses the order and risk layer of github.com/geraked/metatrader5 (MIT; `Include/EAUtils.mqh`:
calcVolume, order, checkForTrail, checkForGrid, checkForEquity, BuySL/SellSL) for bar data. Price runs
through each bar along open -> low -> high -> close (up bar) or open -> high -> low -> close (down bar);
levels are checked at those vertices, which is exact for that path, and a level crossed by a gap
fills at the open. Shorts are run as longs on the negated path ("side frame").

  run_trade      one position with a stop, a target, the EA's trailing stop and its close rule (Mode S/R)
  first_passage  did price reach +N R before the initial stop (the P(N R) tail)
  grid_cycle     one position and the grid it grows, in money, until it is flat (Mode G)
  account        a sequence of closed trades as an account, under each sizing rule (Mode R)
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

SLIP = 0.05  # ATR of adverse slippage on every stop fill
MIN_POINTS = 30  # EAUtils' minPoints: a stop closer than this to price closes the trade instead


def path(o, h, l, c):
    """Four vertices a bar: open, the first extreme, the second extreme, close."""
    o, h, l, c = (np.asarray(x, float) for x in (o, h, l, c))
    up = c >= o
    return np.stack([o, np.where(up, l, h), np.where(up, h, l), c], 1).ravel()


@dataclass
class Spec:
    """What the money side needs from the broker's contract. `vpu`: account currency per 1.0 of
    price per lot (tick_value / tick_size)."""
    point: float
    vpu: float
    vol_min: float = 0.01
    vol_step: float = 0.01
    vol_max: float = 100.0
    leverage: float = 100.0
    stop_out: float = 0.5


def norm_vol(v, spec: Spec):
    """calcVolume's tail: round to the lot step's digits, clamp to [min, max]."""
    digits = max(0, int(round(-np.log10(spec.vol_step)))) if spec.vol_step < 1 else 0
    v = round(v, digits)
    return float(min(max(v, spec.vol_min), spec.vol_max))


# ------------------------------------------------------------------------------------- one trade
def run_trade(V, side, e, sl, tp, pd, lvl, spec_point, closes=None, gated=True):
    """A position opened at the open of bar e (vertex 4e). sl/tp in price (tp None = none), pd = the
    distance in the order comment (the trail's unit), lvl = TrailingStopLevel (0 = no trail).
    `closes`: bool per vertex, True at a bar open where the EA's close rule fires for this side;
    `gated`: CloseOnProfit (only close in profit). Returns (exit vertex, exit price, reason, mfe, mae)
    with mfe/mae in price, in the side frame."""
    n = len(V)
    k0 = 4 * e
    pin = side * V[k0]
    s_sl = side * sl
    s_tp = np.inf if tp is None else side * tp
    if lvl > 0 and lvl * pd < MIN_POINTS * spec_point:
        s_tp = min(s_tp, pin + lvl * pd)  # the trail's first move would sit inside 30 points: close
    k, size, cm, mfe, mae = k0 + 1, 256, pin, 0.0, 0.0
    while k < n:
        k1 = min(n, k + size)
        seg = side * V[k:k1]
        cmx = np.maximum.accumulate(np.r_[cm, seg])[:-1]
        if lvl > 0:
            tr = cmx - lvl * pd
            stop = np.where(tr >= pin, np.maximum(tr, s_sl), s_sl)
        else:
            stop = s_sl
        hit = (seg <= stop) | (seg >= s_tp)
        if closes is not None:
            cl = closes[k:k1]
            if gated:
                cl = cl & (seg >= pin)
            hit |= cl
        if hit.any():
            j = int(np.argmax(hit))
            kk = k + j
            px = seg[j]
            st = stop if np.isscalar(stop) else stop[j]
            gap = kk % 4 == 0
            mfe = max(mfe, float(seg[:j + 1].max()) - pin)
            mae = max(mae, pin - float(seg[:j + 1].min()))
            if px <= st:
                fill, why = (min(px, st) if gap else st), ("trail" if st > s_sl else "sl")
            elif px >= s_tp:
                fill, why = (max(px, s_tp) if gap else s_tp), "tp"
            else:
                fill, why = px, "close"
            return kk, fill, why, mfe, mae
        mfe = max(mfe, float(seg.max()) - pin)
        mae = max(mae, pin - float(seg.min()))
        cm = max(cm, float(seg.max()))
        k, size = k1, size * 2
    return n - 1, side * V[-1], "end", mfe, mae


def first_passage(V, side, e, sl, ns, cap_bars=20000):
    """For each N: did price reach entry + N R before the initial stop (R = |entry - sl|)? Before costs,
    exits ignored, to the end of data or `cap_bars`."""
    n = len(V)
    k0 = 4 * e
    pin = side * V[k0]
    r0 = pin - side * sl
    lv = pin + np.asarray(ns, float) * r0
    hit = np.zeros(len(lv), bool)
    open_ = np.ones(len(lv), bool)
    k, size, kmax = k0 + 1, 512, min(n, k0 + 1 + 4 * cap_bars)
    best = pin
    while k < kmax and open_.any():
        k1 = min(kmax, k + size)
        seg = side * V[k:k1]
        down = seg <= pin - r0
        jd = int(np.argmax(down)) if down.any() else len(seg)
        upto = seg[:jd]
        hi = max(best, float(upto.max())) if len(upto) else best
        now = open_ & (lv <= hi)
        hit[now] = True
        open_[now] = False
        if jd < len(seg):
            break
        best = hi
        k, size = k1, size * 2
    return hit


# ------------------------------------------------------------------------------------- the grid
@dataclass
class GridCfg:
    risk: float = 0.01
    ignore_sl: bool = True
    ignore_tp: bool = True
    trail: bool = True
    trail_lvl: float = 0.5
    grid: bool = True
    mult: float = 1.1
    grid_trail: float = 0.0
    max_lvl: int = 20
    eq_limit: float = 0.0


def grid_cycle(V, side, e, sl, tp, pd, cfg: GridCfg, spec: Spec, bal, cost_px, closes=None):
    """One order and everything checkForGrid adds to it, until flat. Money in account currency.
    sl/tp are the order's coded levels (they size the lot even when ignored); pd its comment.
    Returns a dict: exit vertex, balance after, the worst equity seen, max level, stop-out flag,
    and per-event (vertex, equity) points for the curve."""
    n = len(V)
    k0 = 4 * e
    px0 = V[k0]
    pin = side * px0
    r0 = abs(px0 - sl)
    vol = norm_vol(bal * cfg.risk / (r0 * spec.vpu), spec)
    if vol * spec.vpu * abs(px0) / spec.leverage > bal:
        return None  # NO_MONEY
    grid = cfg.grid
    use_sl = not (cfg.ignore_sl or grid)
    s_sl = side * sl if use_sl else -np.inf
    s_tp = np.inf if (cfg.ignore_tp or tp is None) else side * tp
    pos_p, pos_v = [pin], [vol]
    margin = vol * spec.vpu * abs(px0) / spec.leverage
    bal = bal - cost_px * vol * spec.vpu
    target = vol * spec.vpu * pd  # the first order's loss at one pd: what the grid TP earns back
    grid_tp, gstop, blocked = np.inf, -np.inf, None
    cm = pin
    k = k0 + 1
    worst, peak_eq = bal, bal
    curve = [(k0, bal)]
    segs = [(k0, bal, vol * spec.vpu, pin)]  # (from vertex, balance, lots x vpu, mean price): the open book
    max_lvl, stopped_out = 1, False
    pt30 = MIN_POINTS * spec.point
    while k < n:
        nn = len(pos_p)
        vt = sum(pos_v)
        A = sum(p * v for p, v in zip(pos_p, pos_v)) / vt
        k_val = vt * spec.vpu
        downs = []  # (threshold, kind)
        if use_sl:
            downs.append((s_sl, "sl"))
        if grid and nn < cfg.max_lvl and blocked is None:
            lvl = pin - nn * pd
            last = min(pos_p)
            if abs(last - pd - lvl) > 0.5 * pd:
                lvl = last - pd
            downs.append((lvl, "add"))
        downs.append((A + (spec.stop_out * margin - bal) / k_val, "stopout"))
        if cfg.eq_limit > 0:
            downs.append((A - cfg.eq_limit * bal / k_val, "eqlimit"))
        ups = []
        if nn == 1:
            if s_tp < np.inf:
                ups.append((s_tp, "tp"))
            if cfg.trail and cfg.trail_lvl > 0 and cfg.trail_lvl * pd < pt30:
                ups.append((pin + cfg.trail_lvl * pd, "tp"))
        else:
            ups.append((grid_tp, "tp"))
            if cfg.grid_trail > 0:
                dist = cfg.grid_trail * target / k_val
                if dist < pt30:
                    ups.append((A + dist, "tp"))
        if blocked is not None:
            ups.append((blocked, "unblock"))
        dn = max(t for t, _ in downs)
        up = min((t for t, _ in ups), default=np.inf)
        k1 = min(n, k + 2048)
        seg = side * V[k:k1]
        # the dynamic stops: the single position's trail, or the grid's
        cmx = np.maximum.accumulate(np.r_[cm, seg])[:-1]
        if nn == 1 and cfg.trail and cfg.trail_lvl > 0:
            tr = cmx - cfg.trail_lvl * pd
            dyn = np.where(tr >= pin, tr, -np.inf)
        elif nn > 1 and cfg.grid_trail > 0:
            dist = cfg.grid_trail * target / k_val
            dyn = np.where(cmx > A + dist, cmx - dist, -np.inf)
        else:
            dyn = None
        if dyn is not None:
            dyn = np.maximum(dyn, gstop)
            lo = np.maximum(dyn, dn)
        else:
            lo = np.maximum(gstop, dn)
        hit = (seg <= lo) | (seg >= up)
        if closes is not None:
            hit |= closes[k:k1] & (seg >= A)
        if not hit.any():
            m = float(seg.min())
            worst = min(worst, bal + k_val * (m - A))
            cm = max(cm, float(seg.max()))
            k = k1
            continue
        j = int(np.argmax(hit))
        kk = k + j
        p = float(seg[j])
        if j:
            worst = min(worst, bal + k_val * (float(seg[:j].min()) - A))
            cm = max(cm, float(seg[:j].max()))
        gap = kk % 4 == 0
        lo_j = lo if np.isscalar(lo) else lo[j]
        if p <= lo_j:
            # falling: the highest level crossed acts first
            cands = list(downs)
            if dyn is not None and dyn[j] > -np.inf:
                cands.append((float(dyn[j]), "trail"))
            elif gstop > -np.inf:
                cands.append((gstop, "trail"))
            thr, kind = max((c for c in cands if c[0] >= p), key=lambda c: c[0])
            fill = p if gap else thr
            worst = min(worst, bal + k_val * (fill - A))
            if kind == "add":
                nv = norm_vol(max(pos_v) * cfg.mult, spec)
                eq = bal + k_val * (fill - A)
                need = nv * spec.vpu * abs(side * fill) / spec.leverage
                if eq - margin < need:
                    blocked = thr + 1e-12
                    k = kk
                    continue
                pos_p.append(fill)
                pos_v.append(nv)
                margin += need
                bal -= cost_px * nv * spec.vpu
                max_lvl = max(max_lvl, len(pos_p))
                vt2 = sum(pos_v)
                A2 = sum(pp * v for pp, v in zip(pos_p, pos_v)) / vt2
                grid_tp = A2 + target / (vt2 * spec.vpu)
                if grid_tp - fill < pt30:
                    grid_tp = fill + pt30
                cm = fill
                curve.append((kk, bal + vt2 * spec.vpu * (fill - A2)))
                segs.append((kk, bal, vt2 * spec.vpu, A2))
                k = kk  # the same vertex again: a deeper level may be crossed too
                continue
            # anything else closes the whole book
            bal = bal + k_val * (fill - A)
            stopped_out = kind == "stopout"
            curve.append((kk, bal))
            return dict(k=kk, bal=bal, worst=min(worst, bal), lvl=max_lvl, stopout=stopped_out, why=kind,
                        curve=curve, segs=segs)
        if p >= up or (closes is not None and closes[kk] and p >= A):
            kind = "close"
            if p >= up:
                thr, kind = min(((t, kd) for t, kd in ups if t <= p), key=lambda c: c[0])
                if kind == "unblock":
                    blocked = None
                    cm = max(cm, p)
                    k = kk + 1
                    continue
            fill = p if (gap or kind == "close") else thr
            bal = bal + k_val * (fill - A)
            curve.append((kk, bal))
            return dict(k=kk, bal=bal, worst=worst, lvl=max_lvl, stopout=False, why=kind, curve=curve, segs=segs)
        k = kk + 1
    p = side * V[-1]
    vt = sum(pos_v)
    A = sum(pp * v for pp, v in zip(pos_p, pos_v)) / vt
    bal = bal + vt * spec.vpu * (p - A)
    curve.append((n - 1, bal))
    return dict(k=n - 1, bal=bal, worst=min(worst, bal), lvl=max_lvl, stopout=False, why="end", curve=curve,
                segs=segs)


def book_equity(V, side, segs, k_end):
    """Equity at each bar close while a grid cycle is open, from its segments: (bar indices, equity)."""
    idx, val = [], []
    bounds = [sg[0] for sg in segs[1:]] + [k_end]
    for (k_from, bal, kv, A), k_to in zip(segs, bounds):
        kc = np.arange(4 * (k_from // 4) + 3, k_to, 4)
        kc = kc[kc >= k_from]
        idx.append(kc // 4)
        val.append(bal + kv * (side * V[kc] - A))
    return (np.concatenate(idx), np.concatenate(val)) if idx else (np.array([], int), np.array([]))


# ------------------------------------------------------------------------------------- accounts
def account(tr, spec: Spec, mode="default", risk=0.01, start=10_000.0, mart=False, mart_risk=0.04,
            eq_limit=0.0, fixed_vol=None, min_amount=None):
    """A sequence of non-overlapping closed trades as an account. `tr`: dict of arrays R (net), r0
    (stop distance, price), tpd (TP distance, price; 0 = none), mae (price), px (entry price).
    Sizing per calcVolume: default/equity/balance = equity x risk / (r0 x vpu) (identical with one
    position open at a time); fixed = fixed_vol lots; min_amount = equity / min_amount x step.
    Martingale: after a losing trade, 2 x the last stop distance x its lots / this TP distance, capped
    at mart_risk x balance / this stop. Returns equity after each trade, the worst open equity within
    each, and the fraction of equity each trade made."""
    R, r0, tpd, mae, px = (np.asarray(tr[k], float) for k in ("R", "r0", "tpd", "mae", "px"))
    eq = start
    out_eq, out_lo, frac = np.empty(len(R)), np.empty(len(R)), np.empty(len(R))
    last = None  # (profit, r0, vol)
    for i in range(len(R)):
        if mode == "fixed":
            vol = fixed_vol
        elif mode == "min_amount":
            vol = eq / min_amount * spec.vol_step
        else:
            vol = eq * risk / (r0[i] * spec.vpu)
        if mart and last is not None and last[0] < 0:
            dist_tp = tpd[i] if tpd[i] > 0 else px[i]  # tp = 0: |in - 0| is the price itself
            mv = 2 * last[1] * last[2] / dist_tp
            vol = min(mv, eq * mart_risk / (r0[i] * spec.vpu))
        vol = norm_vol(vol, spec) if eq > 0 else 0.0
        pnl_r = R[i]
        if eq_limit > 0 and vol > 0:
            cap = eq_limit * eq / (vol * spec.vpu * r0[i])  # the kill switch, in R
            if mae[i] / r0[i] >= cap:
                pnl_r = max(pnl_r, -cap)
        pnl = vol * spec.vpu * r0[i] * pnl_r
        out_lo[i] = eq - vol * spec.vpu * mae[i]
        frac[i] = pnl / eq if eq > 0 else 0.0
        eq = max(eq + pnl, 0.0)
        out_eq[i] = eq
        last = (pnl, r0[i], vol)
    return out_eq, out_lo, frac


def max_dd(eq, start=10_000.0):
    e = np.r_[start, np.asarray(eq, float)]
    peak = np.maximum.accumulate(e)
    return float(((peak - e) / np.where(peak > 0, peak, 1)).max())


def worst_open_dd(eq_after, eq_low, start=10_000.0):
    """Worst equity inside any trade against the running peak of closed equity."""
    if not len(eq_low):
        return 0.0
    e = np.r_[start, np.asarray(eq_after, float)]
    peak = np.maximum.accumulate(e)[:-1]
    return float(((peak - np.asarray(eq_low, float)) / np.where(peak > 0, peak, 1)).max())


def mc_ruin(frac, n_trades=1000, paths=2000, seed=0, floor=0.5):
    """Resample a trade sequence's fractional returns: P(touching -50%) and P(ending below the start)."""
    f = np.asarray(frac, float)
    f = f[np.isfinite(f)]
    if len(f) < 20:
        return np.nan, np.nan, None
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(f), (paths, n_trades))
    eq = np.cumprod(1 + np.clip(f[idx], -1, None), axis=1)
    return float((eq.min(1) <= floor).mean()), float((eq[:, -1] < 1).mean()), eq[:200:4]


def mc_martingale(R, tpr, n_trades=1000, paths=2000, seed=0, risk=0.01, mart_risk=0.04, floor=0.5):
    """The martingale rule in R terms, on resampled (R, TP/stop) pairs: after a loss the money at risk
    is 2 x the last money at risk / TP ratio, capped at mart_risk of balance; back to `risk` after a win.
    No TP (ratio 0) sizes to nothing (calcVolume divides by the price): the minimum lot, here 0."""
    R, tpr = np.asarray(R, float), np.asarray(tpr, float)
    if len(R) < 20:
        return np.nan, np.nan, None
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(R), (paths, n_trades))
    eq = np.ones(paths)
    at_risk = np.full(paths, risk)
    lo = np.ones(paths)
    keep = np.empty((paths, n_trades))
    for i in range(n_trades):
        r, q = R[idx[:, i]], tpr[idx[:, i]]
        pnl = at_risk * eq * r
        eq = np.maximum(eq + pnl, 0.0)
        lo = np.minimum(lo, eq)
        loss = pnl < 0
        nxt = np.where(q > 0, 2 * at_risk * np.where(eq > 0, (eq - pnl) / np.maximum(eq, 1e-12), 0) / np.where(q > 0, q, 1), 0.0)
        at_risk = np.where(loss, np.minimum(nxt, mart_risk), risk)
        keep[:, i] = eq
    return float((lo <= floor).mean()), float((eq < 1).mean()), keep[:200:4]
