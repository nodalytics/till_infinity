"""Does a price level with many wicks hold? Part A of the wicks study (frozen in `wick_rule.json`).

Every wick bar spawns a level at its extreme; its next touch after price has left it by 1 ATR is the
test. At the test the level's history is read from closed bars only: the number of distinct wick
rejections in the bucket (K), the touch episodes, body touches, wick length, recency and spread, and
whether the spawning bar was a swing pivot. Outcome: does price reverse 1 ATR before closing 1 ATR
beyond (the desk's hold label), how soon does it break, and how far does a break extend. Trades: a
fade at the level with the stop beyond the wick extreme, and a breakout once the level gives way.

Real series against matched iid and GARCH walks (256 sub-steps, so walks have wicks too); Boom/Crash
and Range Break against their fitted generators, with tick fills.

  OUT=... MT5BT_DB=... MODE=run|smoke python research/ideas/wick_levels.py
"""
from __future__ import annotations

import os
import pickle
import sys
import time
import zlib
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1]))

import lrc_retest as LR  # noqa: E402

OUT = Path(os.environ.get("OUT", ".data/wicks"))
HOME = Path(os.path.expanduser("~/till_infinity"))
BC_OUT = Path(os.environ.get("BC_OUT", HOME / "boomcrash/out"))
RB_OUT = Path(os.environ.get("RB_OUT", HOME / "rb100/out"))
WORKERS = int(os.environ.get("WORKERS", "8"))

IVS = ("15m", "1h", "4h", "1d")
SEC = {"15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}
SPLIT = int(pd.Timestamp("2024-01-01", tz="UTC").timestamp())
ALT15_END = int(pd.Timestamp("2025-08-01", tz="UTC").timestamp())
WALK_STEPS = 256
SOURCES = ("real", "iid", "garch")

# the rule's numbers
WICK_FRAC, WICK_MIN = 0.4, 0.2      # a wick bar: wick >= 0.4 of the range and >= 0.2 ATR
TOL = 0.125                         # bucket half-width, ATR(w)
LIFE = 200                          # bars a level lives after its wick
LB, LB2 = 200, 50                   # count windows
DEPART = 0.5                        # ATR(w): a close this far below ends a touch episode
HORIZON = 300
PAD, MIN_RISK, SLIP, TRAIL = 0.1, 0.25, 0.05, 2.0
NS = (1, 2, 3, 4, 5, 10)
WARM = 60

STEP = ["Step Index", "Step Index 200", "Step Index 500"]
DIFFUSIVE = [s for s in LR.DERIV_DIFFUSIVE if s not in STEP]
BC = ("boom_300", "boom_500", "boom_1000", "crash_300", "crash_500", "crash_1000")
RB = ("RB100", "RB200")
NULL_SEEDS = (0, 1, 2, 3)


def klass(venue, sym, iv):
    if venue == "bc":
        return "DERIV_JUMPY"
    if venue == "rb":
        return "RANGE_BREAK"
    if venue == "deriv1s":
        return "DERIV_DIFFUSIVE"
    if sym in STEP:
        return "DERIV_STEP"
    if sym in DIFFUSIVE:
        return "DERIV_DIFFUSIVE"
    if sym == "Jump 50 Index":
        return "JUMP50"
    if sym in LR.CRYPTO_ALT:
        return "CRYPTO_CFD"
    return LR.klass(venue, sym, iv)


# ------------------------------------------------------------------------------------------- data

def first_after(mask, lo, hi):
    """The first index in [lo, hi] where mask is True, else -1."""
    if lo > hi or lo >= len(mask):
        return -1
    x = np.flatnonzero(mask[lo:hi + 1])
    return lo + int(x[0]) if len(x) else -1


def make_walk(df, cost_px, source, tag):
    """lrc_retest.one's matched walk: same length, close-change sd, timestamps; cost in ATR units."""
    from mcfl import synth
    h, l, c = (df[k].to_numpy(float) for k in ("high", "low", "close"))
    a = LR.atr(h, l, c)
    cost_atr = cost_px / np.maximum(a, 1e-12)
    cost_atr = np.where(np.isfinite(cost_atr), cost_atr, np.nanmedian(cost_atr))
    n = len(df)
    sigma = float(np.std(np.diff(c)))
    seed = zlib.crc32(f"{tag}{source}wicks".encode()) % 100000
    gen = synth.walk if source == "iid" else synth.garch
    w = gen(n, sigma=sigma, seed=seed, steps=WALK_STEPS).reset_index(drop=True).iloc[:n].copy()
    w["ts"] = df["ts"].to_numpy()[:len(w)]
    w["volume"] = 0.0
    wa = LR.atr(*(w[k].to_numpy(float) for k in ("high", "low", "close")))
    return w[["ts", "open", "high", "low", "close", "volume"]], cost_atr[:len(w)] * wa


def boot_walk(df, cost_px, tag):
    """JUMP50's iid bar bootstrap (sweeps.boot_bars), cost in ATR units."""
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    a = LR.atr(h, l, c)
    cost_atr = cost_px / np.maximum(a, 1e-12)
    rng = np.random.default_rng(zlib.crc32(f"{tag}boot".encode()) % 100000)
    i = rng.integers(0, len(df), len(df))
    dc, dh, dl = (c - o)[i], (h - o)[i], (l - o)[i]
    op = o[0] + np.r_[0.0, np.cumsum(dc)[:-1]]
    w = pd.DataFrame({"ts": df["ts"].to_numpy(), "open": op, "high": op + dh, "low": op + dl, "close": op + dc,
                      "volume": 0.0})
    wa = LR.atr(*(w[k].to_numpy(float) for k in ("high", "low", "close")))
    return w, cost_atr * wa


def series(venue, sym, iv, source):
    """(bars, cost per bar in price, class, extra) for one market series and source, or None.
    The alt-coin 15m feed is cut at 2025-08-01; `extra['grid']` keeps the cut-off bars (real only)."""
    df, cost_px = LR.load(venue, sym, iv)
    if df is None or len(df) < 400:
        return None
    df = df.reset_index(drop=True)
    cost_px = np.asarray(cost_px, float)
    extra = {}
    if "spread" in df:
        extra["spread"] = df["spread"].to_numpy(float)
    if venue == "mt5" and sym in LR.CRYPTO_ALT and iv == "15m":
        keep = df["ts"].to_numpy() < ALT15_END
        if source == "real" and (~keep).sum() > 400:
            extra["grid"] = df.loc[~keep].reset_index(drop=True)
        df, cost_px = df.loc[keep].reset_index(drop=True), cost_px[keep]
        if "spread" in extra:
            extra["spread"] = extra["spread"][keep]
        if len(df) < 400:
            return None
    h, l, c = (df[k].to_numpy(float) for k in ("high", "low", "close"))
    a = LR.atr(h, l, c)
    med = float(np.nanmedian((cost_px / np.maximum(a, 1e-12))[50:]))
    if not med <= LR.MAX_COST_ATR:
        return dict(dropped=True, cost_atr=med)
    df = df[["ts", "open", "high", "low", "close", "volume"]]
    tag = f"{venue}{sym}{iv}"
    if source in ("iid", "garch"):
        df, cost_px = make_walk(df, cost_px, source, tag)
        extra = {}
    elif source == "boot":
        df, cost_px = boot_walk(df, cost_px, tag)
        extra = {}
    return df, cost_px, klass(venue, sym, iv), extra


# --------------------------------------------------------------------------------- exits and fills

def exits_e1(o, h, l, c, f, top, stop, a_t, cost_px, hold=HORIZON):
    """A long limit at `top` (a market entry passes top = open[f]) filled on bar f, stop `stop`: E1, the
    2-ATR trail behind completed bars' best high (tv_indicators.exits_x's E1). Returns (R net, exit bar,
    entry, risk, first-passage flags for NS: +N R before the fixed stop, the fill bar's own stop first)."""
    n = len(c)
    entry = min(o[f], top)
    risk = top - stop
    cost = cost_px / risk
    end = min(n - 1, f + hold)
    R, xb, best, st = None, end, max(entry, c[f]), stop
    if l[f] <= stop:
        R, xb = (min(entry, stop) - SLIP * a_t - entry) / risk, f
    else:
        for j in range(f + 1, end + 1):
            st = max(st, best - TRAIL * a_t)
            if l[j] <= st:
                R, xb = (min(o[j], st) - SLIP * a_t - entry) / risk, j
                break
            best = max(best, h[j])
        if R is None:
            R = (c[end] - entry) / risk
    s = first_after(l <= stop, f, end)
    fp = []
    for N in NS:
        t = first_after(h >= entry + N * risk, f + 1, end)
        fp.append(int(t >= 0 and (s < 0 or t < s)))
    return R - cost, xb, entry, risk, fp


class Tape:
    """A per-second bid series and its spread. In a trade's frame (side +1 long, -1 short) the exit price is
    side x (bid, or ask for a short) and the entry price is that plus the spread (rb100.Tape)."""

    def __init__(self, T0, P, spread, swap_rate=0.0, swap_night=0.0):
        self.T0, self.P, self.s = int(T0), P, float(spread)
        self.swap_rate, self.swap_night = swap_rate, swap_night

    def seg(self, side, t0, t1):
        a, b = t0 - self.T0, t1 - self.T0
        if a < 0 or b > len(self.P) or b <= a:
            return None
        x = self.P[a:b]
        return x if side > 0 else -(x + self.s)


def tick_fill(tape, side, ts, sec, H, C, f, kind, lvl, stop, a_t, hold=HORIZON):
    """The same trade on the tick tape. `side` +1 long / -1 short in price; H and C are the bar highs and
    closes in the trade's frame (side x price: a short's frame highs are -low). kind 'limit' fills at the
    first second of bar f whose entry price crosses lvl (at that price, better if it jumped), 'market' at
    bar f's first second. The stop fills at the first second at or beyond it, where the price is; the
    E1 trail moves at bar closes. Returns (R net of spread and swap, how, first-passage flags) or None."""
    n = len(ts)
    end = min(n - 1, f + hold)
    t0, t1 = int(ts[f]), int(ts[end]) + sec
    x = tape.seg(side, t0, t1)
    if x is None:
        return None
    Sf = side * stop
    if kind == "limit":
        Lf = side * lvl
        fb = x[:sec] + tape.s <= Lf
        if not fb.any():
            return None  # the ticks never crossed the limit inside the bar
        k0 = int(np.argmax(fb))
        risk = Lf - Sf
    else:
        k0 = 0
        risk = x[0] + tape.s - Sf
    if not risk > 0:
        return None
    entry = x[k0] + tape.s
    nb = end - f + 1
    best0 = max(entry, C[f])
    cm = np.maximum.accumulate(np.r_[best0, H[f + 1:end + 1]])
    thr_bar = np.r_[Sf, np.maximum(Sf, cm[:nb - 1] - TRAIL * a_t)]
    bar_of = np.searchsorted(ts, t0 + np.arange(len(x)), "right") - 1 - f
    thr = thr_bar[np.clip(bar_of, 0, nb - 1)]
    hit = x[k0 + 1:] <= thr[k0 + 1:]
    if hit.any():
        k = k0 + 1 + int(np.argmax(hit))
        px, how = x[k], ("stop" if thr[k] == Sf else "trail")
    else:
        k, px, how = len(x) - 1, x[-1], "cap"
    held = k - k0
    sw = (tape.swap_rate * abs(entry) * held / (365 * 86400) + tape.swap_night * held / 86400) / risk
    R = (px - entry) / risk - sw
    s_hit = np.flatnonzero(x[k0 + 1:] <= Sf)
    s_at = s_hit[0] if len(s_hit) else len(x)
    fp = []
    for N in NS:
        t_hit = np.flatnonzero(x[k0 + 1:] >= entry + N * risk)
        fp.append(int(len(t_hit) > 0 and t_hit[0] < s_at))
    return R, how, fp


# ------------------------------------------------------------------------------------------ levels

def wick_bars(o, h, l, c, a):
    top = np.maximum(o, c)
    u = h - top
    r = h - l
    wb = (r > 0) & (u >= WICK_FRAC * r) & (u >= WICK_MIN * a)
    return wb, u, top


def pivot_high(h, k=3):
    s = pd.Series(h)
    left = s.shift(1).rolling(k).max().to_numpy()
    right = s[::-1].shift(1).rolling(k).max().to_numpy()[::-1]
    return np.nan_to_num(h > left).astype(bool) & np.nan_to_num(h >= right).astype(bool)


def runs(mask):
    return int((mask & ~np.r_[False, mask[:-1]]).sum())


def counts_at(f, p, tol, aw, h, c, wb, u, top, a):
    """The level's history read at test bar f from bars [f - LB, f - 1]."""
    lo = max(0, f - LB)
    hs, cs, ts_ = h[lo:f], c[lo:f], top[lo:f]
    mem = wb[lo:f] & (np.abs(hs - p) <= tol) & (ts_ <= p - tol)
    K = runs(mem)
    m50 = mem[-LB2:]
    K50 = runs(m50)
    touch = hs >= p - tol
    dep = cs <= p - DEPART * aw
    tk = np.flatnonzero(touch)
    if len(tk):
        Dp = np.r_[0, np.cumsum(dep)]
        tests = 1 + int((Dp[tk[1:]] - Dp[tk[:-1]] > 0).sum())
    else:
        tests = 0
    B = int((ts_ >= p - tol).sum())
    mi = np.flatnonzero(mem)
    if len(mi):
        mtop = float(hs[mi].max())
        wick_atr = float(u[lo:f][mi].sum() / a[f - 1])
        recency = int(f - (lo + mi[-1]))
        spread = float((mi[-1] - mi[0]) / LB)
    else:
        mtop, wick_atr, recency, spread = p, 0.0, -1, 0.0
    return dict(K=K, K50=K50, tests=tests, B=B, wick_atr=wick_atr, recency=recency, spread=spread), mtop, lo + mi


def level_rows(X, ts, a, cost_px, chart, keep_members=False, tape_ctx=None):
    """Every test of a wick level on one chart (resistances; pass the flipped chart for supports).
    Returns (events, trades)."""
    o, h, l, c = X
    n = len(c)
    wb, u, top = wick_bars(o, h, l, c, a)
    piv = pivot_high(h)
    tests = {}
    for w in np.flatnonzero(wb):
        if w < WARM or w >= n - 6 or not a[w] > 0:
            continue
        p, tol = h[w], TOL * a[w]
        end = min(n - 2, w + LIFE)
        brk0 = first_after(c > p + tol, w + 1, end)
        last = brk0 if brk0 >= 0 else end
        lv = first_after(c <= p - a[w], w + 1, last)
        if lv < 0:
            continue
        f = first_after(h >= p - tol, max(lv + 1, w + 4), last)
        if f < 0:
            continue
        tests[f] = w  # w ascends: the latest level wins
    ev, tr = [], []
    brk_seen = {}
    for f, w in sorted(tests.items()):
        p, tol, aw = h[w], TOL * a[w], a[w]
        if not a[f] > 0 or not a[f - 1] > 0:
            continue
        cnt, mtop, mem_idx = counts_at(f, p, tol, aw, h, c, wb, u, top, a)
        A = a[f]
        end = min(n - 1, f + HORIZON)
        brk = first_after(c >= p + A, f, end)
        rv = first_after(l <= p - A, f + 1, end)
        if brk < 0 and rv < 0:
            held = np.nan
        else:
            held = 1.0 if (rv >= 0 and (brk < 0 or rv < brk)) else 0.0
        ext20 = follow = np.nan
        if brk >= 0 and brk + 1 < n:
            ext20 = float((h[brk + 1:min(n, brk + 21)].max() - c[brk]) / a[brk])
            up = first_after(h >= c[brk] + a[brk], brk + 1, min(n - 1, brk + HORIZON))
            dn = first_after(l <= c[brk] - a[brk], brk + 1, min(n - 1, brk + HORIZON))
            if up >= 0 or dn >= 0:
                if up == dn:
                    follow = np.nan
                else:
                    follow = 1.0 if (up >= 0 and (dn < 0 or up < dn)) else 0.0
        row = dict(chart=chart, w=int(w), f=int(f), ts=int(ts[f]), **cnt, piv=bool(piv[w]), held=held,
                   tbrk=(brk - f) if brk >= 0 else -1, ext20=ext20, follow=follow,
                   dist_w=float((p - c[f - 1]) / a[f - 1]))
        if keep_members and cnt["K"] >= 4:
            row.update(p=float(chart * p), tol=float(tol), mtop=float(chart * mtop),
                       members=",".join(str(int(x)) for x in mem_idx))
        ev.append(row)
        base = dict(chart=chart, w=int(w), f=int(f), K=cnt["K"], tests=cnt["tests"], B=cnt["B"], piv=bool(piv[w]))
        # FADE: a short at a limit p - tol, stop beyond the wick extreme (on the negated chart it is a long)
        A1 = a[f - 1]
        lvl = p - tol
        stop = max(mtop + PAD * A1, lvl + MIN_RISK * A1)
        R, xb, entry, risk, fp = exits_e1(-o, -l, -h, -c, f, -lvl, -stop, A1, cost_px[f])
        t = dict(base, kind="fade", ts=int(ts[f]), fill=f, side=-chart, R=R, cost_R=cost_px[f] / risk,
                 risk_atr=risk / A1, xb=xb, **{f"fp{N}": v for N, v in zip(NS, fp)})
        if tape_ctx is not None:
            _tick(t, tape_ctx, -1, f, "limit", lvl, stop, A1, (-l, -c), chart)
        tr.append(t)
        # BREAK: the first close beyond max(top member, p + tol) after the test, next open, stop back inside
        k = first_after(c > max(mtop, p + tol), f, min(n - 2, f + HORIZON))
        if k >= 0 and k + 1 < n and a[k] > 0:
            brk_seen[k] = len(tr)
            ent = o[k + 1]
            stop_b = min(p - tol - PAD * a[k], ent - MIN_RISK * a[k])
            R, xb, entry, risk, fp = exits_e1(o, h, l, c, k + 1, ent, stop_b, a[k], cost_px[k + 1])
            t = dict(base, kind="break", ts=int(ts[k + 1]), fill=k + 1, side=chart, R=R,
                     cost_R=cost_px[k + 1] / risk, risk_atr=risk / a[k], xb=xb, brk_bar=int(k),
                     **{f"fp{N}": v for N, v in zip(NS, fp)})
            if tape_ctx is not None:
                _tick(t, tape_ctx, +1, k + 1, "market", ent, stop_b, a[k], (h, c), chart)
            tr.append(t)
    # one break trade per break bar: keep the latest test
    if tr:
        keep = []
        last_for = {}
        for i, t in enumerate(tr):
            if t["kind"] == "break":
                last_for[t["brk_bar"]] = i
        for i, t in enumerate(tr):
            if t["kind"] != "break" or last_for[t["brk_bar"]] == i:
                keep.append(t)
        tr = keep
    return ev, tr


def _tick(t, ctx, fside, f, kind, lvl, stop, a_t, HC, chart):
    """Fill one trade on the tape. fside is the trade's way on this chart (+1 long, -1 short); lvl and stop
    are in this chart's prices (chart x price) and HC the trade frame's bar highs and closes on it."""
    tape, ts, sec = ctx
    res = tick_fill(tape, fside * chart, ts, sec, HC[0], HC[1], f, kind, chart * lvl, chart * stop, a_t)
    if res is None:
        t.update(R_tick=np.nan, how="", **{f"tfp{N}": -1 for N in NS})
        return
    R, how, fp = res
    t.update(R_tick=R, how=how, **{f"tfp{N}": v for N, v in zip(NS, fp)})


def scan(df, cost_px, keep_members=False, tape_ctx=None):
    """Both charts of one series: (events, trades) DataFrames."""
    ts = df["ts"].to_numpy(np.int64)
    EV, TR = [], []
    for chart, d in ((1, df), (-1, LR.flip(df))):
        X = tuple(d[k].to_numpy(float) for k in ("open", "high", "low", "close"))
        a = LR.atr(X[1], X[2], X[3])
        e, t = level_rows(X, ts, a, np.asarray(cost_px, float), chart, keep_members, tape_ctx)
        EV += e
        TR += t
    return pd.DataFrame(EV), pd.DataFrame(TR)


# ----------------------------------------------------------------------------------- Deriv sources

def bc_build(sl, src, seed):
    """Boom/Crash bars from the per-second tape of the real ticks, or of the fitted constant-hazard null
    (boomcrash_trend.simulate on the real tick times). Returns ({iv: bars}, Tape)."""
    import json as _json
    import boomcrash_trend as BCT
    import rb100 as RBM
    cache = BC_OUT / "cache" / sl
    ms = np.load(cache / "ms.npy")
    spread = float(np.median(np.load(cache / "spread.npy", mmap_mode="r")))
    if src == "real":
        bid = np.load(cache / "bid.npy")
    else:
        with open(cache / "null.pkl", "rb") as fh:
            nl = pickle.load(fh)
        bid = BCT.simulate(ms, nl["start"], nl["par"], BCT.side(sl), 7_000_000 + 1000 * BC.index(sl) + seed)
    T0, P = RBM.per_second(ms, bid)
    del ms, bid
    meta = _json.loads((BC_OUT / "meta.json").read_text())
    swap = abs(float(meta["swap"].get(sl, 0.0))) / 100
    bars = {}
    for iv in IVS:
        sec = SEC[iv]
        g0 = -(-T0 // sec) * sec
        grid = np.arange(g0, T0 + len(P) - sec + 1, sec, dtype=np.int64)
        bars[iv] = RBM.bars_from_sec(P, T0, grid, sec)
    return bars, Tape(T0, P, spread, swap_rate=swap), spread


def rb_build(inst, src, seed):
    """Range Break bars and tape (rb100.build): the broker's bars and the real tick tape, or the fitted rbsim."""
    import json as _json
    import rb100 as RBM
    prm = _json.loads((RB_OUT / "rb_sim_params.json").read_text())
    bars, tp, costs = RBM.build(inst, src, seed, prm)
    return bars, tp, costs


# ----------------------------------------------------------------------------------------- the jobs

def part_path(tag):
    return OUT / "parts" / f"{tag}.pkl"


def _tagify(*x):
    return "_".join(str(v) for v in x).replace(" ", "-").replace("/", "-")


def _analyse(df, cost_px, cls, iv, src, seed_tag, extra=None, tape_ctx=None, deriv=False):
    import wick_info as WI
    keep = src == "real"
    ev, tr = scan(df, cost_px, keep_members=keep, tape_ctx=tape_ctx)
    seed = zlib.crc32(f"{seed_tag}rows".encode()) % 2 ** 31
    S, Lw, hist, T = WI.bar_rows(df, cost_px, iv, seed, spread=(extra or {}).get("spread"), tape_ctx=tape_ctx,
                                 deriv=deriv)
    return dict(events=_slim(ev), trades=_slim(tr), sample=_slim(S), long=_slim(Lw), hist=hist, btrades=_slim(T),
                bars=len(df), first=int(df["ts"].iloc[0]), last=int(df["ts"].iloc[-1]), cls=cls, iv=iv, src=src)


def _slim(d):
    if d is None or not len(d):
        return d
    for col in d.columns:
        if d[col].dtype == np.float64 and col not in ("p", "mtop", "tol"):
            d[col] = d[col].astype(np.float32)
        elif d[col].dtype == np.int64 and col not in ("ts", "w", "f", "t", "fill", "xb", "brk_bar"):
            d[col] = d[col].astype(np.int32)
    return d


def one(job):
    """One series and source (or one Deriv instrument and source with all four timeframes)."""
    venue = job[0]
    tag = _tagify(*job)
    path = part_path(tag)
    if path.exists():
        return tag, "cached"
    t0 = time.time()
    try:
        out = {}
        if venue == "bc":
            _, sl, src, seed = job
            bars, tape, spread = bc_build(sl, src, seed)
            for iv, df in bars.items():
                if len(df) < 400:
                    continue
                cost = np.full(len(df), spread)
                out[iv] = _analyse(df, cost, "DERIV_JUMPY", iv, src, f"{tag}{iv}", tape_ctx=(tape, df["ts"].to_numpy(np.int64), SEC[iv]), deriv=True)
        elif venue == "rb":
            _, inst, src, seed = job
            bars, tp, costs = rb_build(inst, src, seed)
            for iv, df in bars.items():
                sp, sw = costs[iv]
                tape = Tape(tp[0], tp[1], sp, swap_night=sw) if tp is not None else None
                ctx = (tape, df["ts"].to_numpy(np.int64), SEC[iv]) if tape is not None else None
                out[iv] = _analyse(df, np.full(len(df), sp), "RANGE_BREAK", iv, src, f"{tag}{iv}", tape_ctx=ctx, deriv=True)
        else:
            _, sym, iv, src = job
            got = series(venue, sym, iv, src)
            if got is None:
                pd.to_pickle(dict(none=True), path)
                return tag, "no data"
            if isinstance(got, dict):
                pd.to_pickle(got, path)
                return tag, f"dropped: cost {got['cost_atr']:.2f} ATR"
            df, cost_px, cls, extra = got
            out[iv] = _analyse(df, cost_px, cls, iv, src, tag, extra)
            if "grid" in extra:  # the alt-coin 15m feed after 2025-08: Part B only, apart
                import wick_info as WI
                g = extra["grid"]
                gc = np.full(len(g), float(np.median(cost_px)))
                S, Lw, hist, _ = WI.bar_rows(g[["ts", "open", "high", "low", "close", "volume"]], gc, iv,
                                             zlib.crc32(f"{tag}grid".encode()) % 2 ** 31)
                out["grid"] = dict(sample=_slim(S), long=_slim(Lw), hist=hist, bars=len(g), cls="ALT15_GRID", iv=iv, src=src)
    except Exception as exc:  # one bad series should not sink the run
        import traceback
        return tag, f"FAILED {exc!r}\n{traceback.format_exc()}"
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.to_pickle(out, path)
    n_ev = sum(len(v["events"]) for k, v in out.items() if "events" in v and v["events"] is not None)
    return tag, f"{n_ev} tests, {time.time() - t0:.0f}s"


def jobs_list():
    import turn_confirm as C
    mt5 = (LR.FX + LR.METAL + LR.INDEX + LR.ENERGY + LR.CRYPTO_MAJOR + LR.CRYPTO_ALT + LR.DERIV_DIFFUSIVE
           + ["Jump 50 Index"])
    js = []
    for iv in IVS:
        for s in mt5:
            srcs = SOURCES + (("boot",) if s == "Jump 50 Index" else ())
            js += [("mt5", s, iv, src) for src in srcs]
        js += [("binance", s, iv, src) for s in LR.COINS for src in SOURCES]
        js += [("fresh", s, iv, src) for s in C.FRESH for src in SOURCES]
        js += [("deriv1s", s, iv, src) for s in LR.DERIV_1S for src in SOURCES]
    js += [("bc", sl, "real", 0) for sl in BC] + [("bc", sl, "null", k) for sl in BC for k in NULL_SEEDS]
    js += [("rb", i, "real", 0) for i in RB] + [("rb", i, "rbsim", k) for i in RB for k in NULL_SEEDS]
    js += [("rb", i, s, 0) for i in RB for s in ("iid", "garch")]
    return js


def run():
    (OUT / "parts").mkdir(parents=True, exist_ok=True)
    js = jobs_list()
    only = os.environ.get("ONLY")
    if only:
        js = [j for j in js if any(o in _tagify(*j) for o in only.split(","))]
    # the heavy Deriv tape jobs first, then the longest series
    order = {"bc": 0, "rb": 0, "binance": 1, "fresh": 2, "mt5": 3, "deriv1s": 4}
    js.sort(key=lambda j: (order[j[0]], SEC.get(j[2], 0)))
    print(f"{len(js)} jobs", flush=True)
    with ProcessPoolExecutor(WORKERS) as pool:
        for tag, msg in pool.map(one, js, chunksize=1):
            print(f"  {tag}: {msg}", flush=True)
    print("run done", flush=True)


def fetch_fresh():
    """15m and 1h klines of the 58 fresh coins (turn_confirm.fetch_one into CACHE)."""
    from concurrent.futures import ThreadPoolExecutor
    import turn_confirm as C
    C.CACHE.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(4) as pool:
        list(pool.map(C.fetch_one, [(c, iv) for c in C.FRESH for iv in ("1h", "15m")]))
    print("fetch done", flush=True)


def smoke():
    """A walk only (no real data): counts, timings and the hold rate."""
    from mcfl import synth
    n = int(os.environ.get("SMOKE_N", "20000"))
    w = synth.walk(n, sigma=1.0, seed=5, steps=WALK_STEPS).reset_index(drop=True)
    w["ts"] = 1_600_000_000 + 3600 * np.arange(len(w))
    w = w[["ts", "open", "high", "low", "close", "volume"]]
    t0 = time.time()
    r = _analyse(w, np.full(len(w), 0.02), "WALK", "1h", "iid", "smoke")
    ev, tr = r["events"], r["trades"]
    print(f"{len(w)} bars: {len(ev)} tests, {len(tr)} trades in {time.time() - t0:.1f}s")
    print("hold by K bin:", ev.assign(kb=np.minimum(ev["K"], 6)).groupby("kb")["held"].agg(["mean", "count"]).round(3).to_dict())
    print(tr.groupby("kind")[["R"] + [f"fp{N}" for N in NS]].mean().round(3))
    print("sample", r["sample"].shape, "long", r["long"].shape, "btrades", r["btrades"].groupby("kind")["R"].agg(["mean", "count"]))
    print(r["long"]["rej"].mean())


def main():
    mode = os.environ.get("MODE", "run")
    {"run": run, "smoke": smoke, "fetch": fetch_fresh}[mode]()


if __name__ == "__main__":
    main()
