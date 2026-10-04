"""The desk's setup: a linear regression channel for the trend, a break of structure, the retest.

Frozen in `lrc_rule.json` before this ran (see `research/docs/lrc-retest.md`). In a downtrend price
breaks a prior confirmed swing low, pulls back up to the broken level and is sold there, with the stop
just above the pullback and a ~2R target. Every rule is written for the up side and run on the chart
and on the flipped chart. Rules:

  R1  LRC trend, a close beyond the last confirmed swing (BOS), a limit at the broken level for 20 bars
  R2  as R1, entered on a confirmed higher low near the level instead
  R3  the published RSI + LRC strategy, as written
  R4  'fade to value': counter-trend at the opposite LRC band (the case the desk lost on)
  R5  earlier BOS / CHoCH levels as support in the trend, first touch after 20 bars (R5s: sweep then reject)

plus the strength of the moves before and after the break (terciles) and the hold rate of BOS, CHoCH
and plain swing levels. Against 1/(N+1), iid and GARCH walks matched to each series, and a coin twin.

  OUT=... MT5BT_DB=... MODE=run|agg|plot python research/ideas/lrc_retest.py
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import zlib
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1]))

OUT = Path(os.environ.get("OUT", ".data/lrc"))
HOME = Path(os.path.expanduser("~/till_infinity"))
BIN = Path(os.environ.get("BINANCE", HOME / "data/binance"))
FRESH_DIR = Path(os.environ.get("CACHE", HOME / "data/binance_fresh"))
LRC_DB = os.environ.get("LRC_DB", str(HOME / "data/lrc_bars.db"))
RESEARCH_DB = os.environ.get("RESEARCH_DB", str(HOME / "data/research.db"))

IVS = ("15m", "30m", "1h", "4h", "1d")
SEC = {"15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400}
SPLIT = pd.Timestamp("2024-01-01", tz="UTC").timestamp()
NS = (0.5, 1, 2, 4, 10)
LENS = (50, 100, 200)
TREND_L = 100
BAND_K = 2.0
SWING = 3
EQ_TOL = 0.1
ESTABLISH = 2
WINDOW = 20          # R1: bars a retest order lives; R5: bars before an earlier level arms
PAD, MIN_RISK, SLIP = 0.1, 0.25, 0.05
CAP, HORIZON = 100, 1000
TRAIL = 2.0
R2_NEAR = 1.0
R3_CAP = 500
R5_PAD, R5_AGE, R5_LIVE = 0.5, 500, 10
HOLD_ATR, HOLD_MAX = 1.0, 500
FEE = 0.0007
MAX_COST_ATR = 0.5
WALK_STEPS = 256

FX = "EURUSD GBPUSD USDJPY AUDUSD USDCAD USDCHF NZDUSD EURJPY GBPJPY EURGBP AUDJPY USDCNH".split()
METAL = "XAUUSD XAGUSD XPTUSD XPDUSD XCUUSD".split()
INDEX = ["US SP 500", "US Tech 100", "Wall Street 30", "Germany 40", "UK 100", "Japan 225", "Australia 200"]
ENERGY = ["US Oil", "UK Brent Oil"]
CRYPTO_MAJOR = ["BTCUSD", "ETHUSD", "SOLUSD"]
CRYPTO_ALT = ("AAVUSD ADAUSD ALGUSD APEUSD APTUSD AVAUSD BATUSD BCHUSD BNBUSD COMUSD DOGUSD DOTUSD DSHUSD ETCUSD "
              "FILUSD IMXUSD IOTUSD LNKUSD LTCUSD MLNUSD NEOUSD NERUSD SANUSD SHBUSD TRUUSD TRXUSD UNIUSD XLMUSD "
              "XMRUSD XRPUSD XTZUSD ZECUSD").split()
DERIV_DIFFUSIVE = ["Volatility 10 Index", "Volatility 25 Index", "Volatility 50 Index", "Volatility 75 Index",
                   "Volatility 100 Index", "Step Index", "Step Index 200", "Step Index 500",
                   "Drift Switch Index 10", "Drift Switch Index 20", "Drift Switch Index 30"]
DERIV_JUMPY = ["Jump 50 Index", "Boom 1000 Index", "Crash 1000 Index"]
RANGE_BREAK = ["Range Break 100 Index"]
DERIV_1S = ["volatility_10_1s_index", "volatility_25_1s_index", "volatility_50_1s_index",
            "volatility_75_1s_index", "volatility_100_1s_index"]
COINS = ("BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK", "LTC", "DOT", "TRX")
NONDERIV = ("FX", "METAL", "INDEX", "ENERGY", "CRYPTO_CFD", "BINANCE")
CLASS_ORDER = NONDERIV + ("FRESH", "DERIV_1S", "DERIV_DIFFUSIVE", "DERIV_JUMPY", "RANGE_BREAK", "KNOWN_BAD")


# ------------------------------------------------------------------------------------------- indicators

def atr(h, l, c, n=14):
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h, pc) - np.minimum(l, pc)
    return pd.Series(tr).ewm(alpha=1 / n, adjust=False).mean().to_numpy()


def lrc(c, L, chunk=20000):
    """The rolling linear regression channel: at each bar t, the least-squares line through closes
    t-L+1..t. Returns (slope per bar, mid = the line's value at t, dev = RMS residual about the line,
    population). NaN before bar L-1."""
    c = np.asarray(c, float)
    n = len(c)
    slope, mid, dev = (np.full(n, np.nan) for _ in range(3))
    if n < L:
        return slope, mid, dev
    x = np.arange(L, dtype=float)
    xc = x - x.mean()
    sxx = float((xc ** 2).sum())
    W = np.lib.stride_tricks.sliding_window_view(c, L)
    for s in range(0, len(W), chunk):
        w = W[s:s + chunk]
        m = w.mean(1)
        b = (w - m[:, None]) @ xc / sxx
        res = w - m[:, None] - b[:, None] * xc[None, :]
        slope[L - 1 + s:L - 1 + s + len(w)] = b
        mid[L - 1 + s:L - 1 + s + len(w)] = m + b * xc[-1]
        dev[L - 1 + s:L - 1 + s + len(w)] = np.sqrt((res ** 2).mean(1))
    return slope, mid, dev


def rsi(c, n=14):
    d = np.diff(np.asarray(c, float), prepend=np.nan)
    up = pd.Series(np.where(d > 0, d, 0.0)).ewm(alpha=1 / n, adjust=False).mean().to_numpy()
    dn = pd.Series(np.where(d < 0, -d, 0.0)).ewm(alpha=1 / n, adjust=False).mean().to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        r = 100 - 100 / (1 + up / dn)
    r = np.where(dn == 0, 100.0, r)
    r[:n] = np.nan
    return r


def pivots(h, l, k=SWING):
    """3/3 pivots as MCFL's EXTREME: strictly above the k bars before, at or above the k after."""
    n = len(h)
    hi = np.zeros(n, bool)
    lo = np.zeros(n, bool)
    if n < 2 * k + 1:
        return hi, lo
    hi[k:n - k] = True
    lo[k:n - k] = True
    for j in range(1, k + 1):
        hi[k:n - k] &= (h[k - j:n - k - j] < h[k:n - k]) & (h[k + j:n - k + j] <= h[k:n - k])
        lo[k:n - k] &= (l[k - j:n - k - j] > l[k:n - k]) & (l[k + j:n - k + j] >= l[k:n - k])
    return hi, lo


def structure(h, l, a, hi, lo):
    """MCFL v2 labels and state, known at each bar: (state, run count, run id) per bar, and each
    pivot low's label. State: +1 UP, -1 DOWN, 0 MIXED."""
    n = len(h)
    lab_hi, lab_lo = {}, {}
    ph = np.flatnonzero(hi)
    pl = np.flatnonzero(lo)
    for piv, px, out, more, less in ((ph, h, lab_hi, "HH", "LH"), (pl, l, lab_lo, "LL", "HL")):
        s = 1.0 if out is lab_hi else -1.0
        for prev, p in zip(piv, piv[1:]):
            tol = EQ_TOL * a[p] if a[p] > 0 else 0.0
            diff = s * (px[p] - px[prev])
            out[p] = more if diff > tol else less if diff < -tol else ("EH" if s > 0 else "EL")
    known = {}
    for p, lab in lab_hi.items():
        known.setdefault(p + SWING, []).append(("H", lab))
    for p, lab in lab_lo.items():
        known.setdefault(p + SWING, []).append(("L", lab))
    st = np.zeros(n, np.int8)
    cnt = np.zeros(n, np.int32)
    rid = np.full(n, -1, np.int64)
    state, last_h, last_l, run, run_id = 0, None, None, 0, -1
    changes = []
    for k in sorted(known):
        g = known[k]
        for kind, lab in g:
            if kind == "H":
                last_h = lab
            else:
                last_l = lab
        new = 1 if (last_h == "HH" and last_l == "HL") else -1 if (last_h == "LH" and last_l == "LL") else 0
        if new != state:
            state, run, run_id = new, len(g), k
        else:
            run += len(g)
        changes.append((k, state, run, run_id))
    j, cur = 0, (0, 0, -1)
    for t in range(n):
        while j < len(changes) and changes[j][0] <= t:
            cur = changes[j][1:]
            j += 1
        st[t], cnt[t], rid[t] = cur
    return st, cnt, rid, lab_lo


def breaks(c, h, hi, st, cnt, rid):
    """Up-breaks: the first close above the most recent confirmed swing high. Each: (bar, level, pivot,
    type) with type BOS (with the state), CHOCH (the first against an established state in its run)
    or OTHER."""
    n = len(c)
    known_at = {p + SWING: p for p in np.flatnonzero(hi)}
    cur, broken = None, True
    fired = set()
    out = []
    for t in range(n):
        if cur is not None and not broken and c[t] > h[cur]:
            s = st[t]
            if s == 1:
                typ = "BOS"
            elif s == -1 and cnt[t] >= ESTABLISH and rid[t] not in fired:
                typ = "CHOCH"
                fired.add(int(rid[t]))
            else:
                typ = "OTHER"
            out.append((t, float(h[cur]), int(cur), typ))
            broken = True
        p = known_at.get(t)
        if p is not None:
            cur, broken = p, False
    return out


# ------------------------------------------------------------------------------------------------ exits

def fill_path(o, h, l, c, entry, fill):
    """The fill bar after the fill, as an ordered list of prices. Bars are read O-L-H-C when they close
    up and O-H-L-C when they close down (the usual OHLC path convention, mirror-consistent). `fill`:
    'open' (a fill at the open: everything after it), 'down' (a limit reached while price fell: from
    the first downward crossing of the entry on that path), 'up' (reached while price rose)."""
    pts = [o, l, h, c] if c >= o else [o, h, l, c]
    if fill == "open":
        return pts[1:]
    for k in range(3):
        a, b = pts[k], pts[k + 1]
        if (fill == "down" and a >= entry >= b) or (fill == "up" and a <= entry <= b):
            return pts[k + 1:]
    return pts[-1:]


def fill_bar(o, h, l, c, f, entry, stop, tgt, fill):
    """On the fill bar: ('stop' | 'target' | None, the best price reached before a stop)."""
    best = entry
    for x in fill_path(o[f], h[f], l[f], c[f], entry, fill):
        if x <= stop:
            return "stop", best
        best = max(best, x)
        if tgt is not None and x >= tgt:
            return "target", best
    return None, best


def reach(h, l, f, entry, stop, risk, best0):
    """The most R reached before the stop, within HORIZON bars, gross of cost; a bar touching both
    counts as the stop. `best0`: the best price on the fill bar after the fill (None if it stopped)."""
    if best0 is None:
        return 0.0
    best = best0
    hh, ll = h[f + 1:f + 1 + HORIZON], l[f + 1:f + 1 + HORIZON]
    hit = ll <= stop
    k = int(np.argmax(hit)) if hit.any() else len(ll)
    if k > 0:
        best = max(best, hh[:k].max())
    return max(0.0, (best - entry) / risk)


def exits(o, h, l, c, f, entry, stop, a_t, cost_px, band=None, fill="down"):
    """A long filled at `entry` on bar f with its stop: X2 (2R target), TR (2-ATR trail behind completed
    bars' best high) and BAND (a limit at band[j-1] from bar f+1). R net of cost, plus each exit's bar.
    The fill bar is read with `fill_path`: a stop reached after the fill is a loss, X2's target counts
    there if it is reached after the fill and before the stop."""
    n = len(c)
    risk = entry - stop
    cost = cost_px / risk
    stopR = (stop - SLIP * a_t - entry) / risk
    end = min(n - 1, f + CAP)
    seg = slice(f + 1, end + 1)
    hh, ll, oo = h[seg], l[seg], o[seg]
    js = np.flatnonzero(ll <= stop)
    js = js[0] if len(js) else None
    tgt = entry + 2 * risk
    first, best_f = fill_bar(o, h, l, c, f, entry, stop, tgt, fill)
    stopped = fill_bar(o, h, l, c, f, entry, stop, None, fill)[0] == "stop"
    res = {}
    # X2
    if first == "stop":
        r, xb = stopR, f
    elif first == "target":
        r, xb = 2.0, f
    else:
        jt = np.flatnonzero(hh >= tgt)
        jt = jt[0] if len(jt) else None
        if js is not None and (jt is None or js <= jt):
            r, xb = (min(oo[js], stop) - SLIP * a_t - entry) / risk, f + 1 + js
        elif jt is not None:
            r, xb = (max(oo[jt], tgt) - entry) / risk, f + 1 + jt
        else:
            r, xb = (c[end] - entry) / risk, end
    res["X2"], res["x2_bar"] = r - cost, xb
    # TR
    if stopped:
        r, xb = stopR, f
    elif len(hh) == 0:
        r, xb = (c[end] - entry) / risk, end
    else:
        best0 = max(entry, c[f])
        prev_best = np.maximum.accumulate(np.r_[best0, np.maximum(best0, hh[:-1])])
        trail = np.maximum(stop, prev_best - TRAIL * a_t)
        jx = np.flatnonzero(ll <= trail)
        if len(jx):
            j = jx[0]
            r, xb = (min(oo[j], trail[j]) - SLIP * a_t - entry) / risk, f + 1 + j
        else:
            r, xb = (c[end] - entry) / risk, end
    res["TR"], res["tr_bar"] = r - cost, xb
    # BAND
    if band is not None:
        if stopped:
            r, xb = stopR, f
        else:
            tb = band[f:end]  # band[j-1] for j = f+1..end
            jb = np.flatnonzero(hh >= tb)
            jb = jb[0] if len(jb) else None
            if js is not None and (jb is None or js <= jb):
                r, xb = (min(oo[js], stop) - SLIP * a_t - entry) / risk, f + 1 + js
            elif jb is not None:
                r, xb = (max(oo[jb], tb[jb]) - entry) / risk, f + 1 + jb
            else:
                r, xb = (c[end] - entry) / risk, end
        res["BAND"], res["band_bar"] = r - cost, xb
    res["mfe"] = reach(h, l, f, entry, stop, risk, None if stopped else best_f)
    return res


# -------------------------------------------------------------------------------------- one chart side

class Frame:
    """One orientation of a series with everything the rules read."""

    def __init__(self, o, h, l, c, ts, cost_px):
        self.o, self.h, self.l, self.c, self.ts, self.cost = o, h, l, c, ts, cost_px
        self.n = len(c)
        self.a = atr(h, l, c)
        self.slope, self.mid, self.dev = {}, {}, {}
        for L in LENS:
            self.slope[L], self.mid[L], self.dev[L] = lrc(c, L)
        self.ub = self.mid[TREND_L] + BAND_K * self.dev[TREND_L]
        self.lb = self.mid[TREND_L] - BAND_K * self.dev[TREND_L]
        self.hi, self.lo = pivots(h, l)
        self.st, self.cnt, self.rid, self.lab_lo = structure(h, l, self.a, self.hi, self.lo)
        self.brk = breaks(c, h, self.hi, self.st, self.cnt, self.rid)
        self.piv_lo = np.flatnonzero(self.lo)


def strength(F, b, level, p, end):
    """Move before (the leg into the broken swing) and after (the displacement through the break, over
    bars b..end, never the entry bar)."""
    q = F.piv_lo[F.piv_lo < p]
    if len(q) and F.a[p] > 0:
        q = q[-1]
        bsz = (level - F.l[q]) / F.a[p]
        bsp = bsz / (p - q)
    else:
        bsz = bsp = np.nan
    end = max(b, min(end, b + WINDOW))
    w = F.h[b:end + 1]
    k = int(np.argmax(w))
    asz = (w[k] - level) / F.a[b] if F.a[b] > 0 else np.nan
    return dict(b_size=bsz, b_speed=bsp, a_size=asz, a_speed=asz / (k + 1))


def trade_row(F, rule, f, entry, stop, a_t, band, at_open=False, **kw):
    """A limit at `entry` fills while price falls to it, unless the bar opened through it."""
    fill = "open" if (at_open or F.o[f] <= entry) else "down"
    res = exits(F.o, F.h, F.l, F.c, f, entry, stop, a_t, F.cost[f], band, fill)
    return dict(rule=rule, f=f, ts=int(F.ts[f]), entry=entry, stop=stop, risk_atr=(entry - stop) / a_t,
                fill=fill, **res, **kw)


def rules_r1_r2(F):
    rows = []
    n = F.n
    bars = [b for b, *_ in F.brk]
    for i, (b, level, p, typ) in enumerate(F.brk):
        if b < max(LENS) or b + 1 >= n:
            continue
        nxt = bars[i + 1] if i + 1 < len(bars) else n
        trend = {f"t{L}": bool(F.slope[L][b] > 0) for L in LENS}
        # R1: a limit at the broken level for WINDOW bars, cancelled after the next break
        last = min(n - 1, b + WINDOW, nxt)
        seg = F.l[b + 1:last + 1]
        hit = np.flatnonzero(seg <= level)
        if len(hit) and any(trend.values()):
            f = b + 1 + hit[0]
            a_t = F.a[f - 1]
            entry = min(F.o[f], level)
            stop = min(level, F.l[b:f].min()) - PAD * a_t
            if a_t > 0 and entry - stop >= MIN_RISK * a_t:
                rows.append(trade_row(F, "R1", f, entry, stop, a_t, F.ub, b=b, p=p, level=level, btype=typ,
                                      **trend, **strength(F, b, level, p, f - 1)))
        # R2: the first confirmed swing low after the break, labelled HL, within R2_NEAR ATR of the level
        if trend[f"t{TREND_L}"]:
            q = F.piv_lo[(F.piv_lo > b) & (F.piv_lo <= b + WINDOW)]
            if len(q):
                q = int(q[0])
                f = q + SWING + 1
                if f < n and F.lab_lo.get(q) == "HL" and abs(F.l[q] - level) <= R2_NEAR * F.a[q]:
                    a_t = F.a[f - 1]
                    entry, stop = F.o[f], F.l[q] - PAD * a_t
                    if a_t > 0 and entry - stop >= MIN_RISK * a_t:
                        rows.append(trade_row(F, "R2", f, entry, stop, a_t, F.ub, True, b=b, p=p, level=level, q=q,
                                              btype=typ, **trend, **strength(F, b, level, p, f - 1)))
    return rows


def rule_r3(F):
    """The published RSI + LRC strategy as written (long side of this chart)."""
    c, o, n = F.c, F.o, F.n
    basis = F.mid[100]
    sd = pd.Series(c).rolling(100).std(ddof=0).to_numpy()
    r = rsi(c)
    entry_sig = (c <= basis - sd) & (r < 30)
    exit_sig = (c >= basis + sd) & (r > 70)
    rows = []
    t = 0
    ex = np.flatnonzero(exit_sig)
    while t < n - 1:
        if not entry_sig[t]:
            t += 1
            continue
        f, a_t = t + 1, F.a[t]
        if not a_t > 0:
            t += 1
            continue
        entry = o[f]
        k = ex[np.searchsorted(ex, f)] if np.searchsorted(ex, f) < len(ex) else None
        if k is not None and k + 1 < n and k + 1 - f <= R3_CAP:
            xb, px = k + 1, o[k + 1]
        else:
            xb = min(n - 1, f + R3_CAP)
            px = c[xb]
        R = (px - entry) / a_t - F.cost[f] / a_t
        first, best_f = fill_bar(o, F.h, F.l, c, f, entry, entry - a_t, None, "open")
        best_f = None if first == "stop" else best_f
        rows.append(dict(rule="R3", f=f, ts=int(F.ts[f]), entry=entry, stop=entry - a_t, risk_atr=1.0, X2=R,
                         x2_bar=xb, mfe=reach(F.h, F.l, f, entry, entry - a_t, a_t, best_f)))
        t = xb + 1  # one position at a time
    return rows


def rule_r4(F):
    """Fade to value: in an LRC downtrend, buy the first touch of the lower band; stop 1 ATR."""
    rows = []
    lb, sl = F.lb, F.slope[TREND_L]
    for t in np.flatnonzero((F.l[2:] <= lb[1:-1]) & (F.l[1:-1] > lb[:-2])) + 2:
        if not sl[t - 1] < 0:
            continue
        a_t = F.a[t - 1]
        if not a_t > 0:
            continue
        entry = min(F.o[t], lb[t - 1])
        rows.append(trade_row(F, "R4", t, entry, entry - a_t, a_t, F.mid[TREND_L]))
    return rows


def first_touch(F, level, start, stop_at, die_below=True):
    """Arm on the first bar from `start` whose low is above the level; then the first touch. A close
    1 ATR below the level before arming kills it. Returns (arm, touch) or None."""
    l, c, a = F.l, F.c, F.a
    end = min(F.n, stop_at)
    if start >= end:
        return None
    seg = l[start:end] > level
    if not seg.any():
        return None
    j = start + int(np.argmax(seg))
    if die_below and j > start and (c[start:j] <= level - HOLD_ATR * a[start:j]).any():
        return None
    t = l[j + 1:end] <= level
    if not t.any():
        return None
    return j, j + 1 + int(np.argmax(t))


def hold_outcome(F, level, k):
    A = F.a[k - 1]
    if not A > 0:
        return None
    if F.c[k] <= level - HOLD_ATR * A:
        return 0
    hh, cc = F.h[k + 1:k + 1 + HOLD_MAX], F.c[k + 1:k + 1 + HOLD_MAX]
    up, dn = hh >= level + HOLD_ATR * A, cc <= level - HOLD_ATR * A
    ju = int(np.argmax(up)) if up.any() else None
    jd = int(np.argmax(dn)) if dn.any() else None
    if ju is None and jd is None:
        return None
    return int(jd is None or (ju is not None and ju <= jd))


def levels_r5(F):
    """Hold rates of plain swing lows and broken swing highs, and the R5 / R5s trades."""
    holds, rows = [], []
    sl = F.slope[TREND_L]
    for q in F.piv_lo:
        if q < max(LENS):
            continue
        lv = F.l[q]
        ft = first_touch(F, lv, q + SWING + 1, q + SWING + HOLD_MAX)
        if ft is None:
            continue
        k = ft[1]
        out = hold_outcome(F, lv, k)
        if out is not None:
            holds.append(dict(type="SWING", age=k - q - SWING, hold=out, sweep=bool(F.l[k] < lv < F.c[k]),
                              intrend=bool(sl[k - 1] > 0), ts=int(F.ts[k])))
    bars_by_type = {}
    for b, *_rest in F.brk:
        bars_by_type.setdefault(_rest[2], []).append(b)
    for b, lv, p, typ in F.brk:
        if b < max(LENS):
            continue
        tb = np.asarray(bars_by_type[typ])
        ft = first_touch(F, lv, b + 1, b + HOLD_MAX)
        if ft is not None:
            k = ft[1]
            out = hold_outcome(F, lv, k)
            if out is not None:
                holds.append(dict(type=typ, age=k - b, hold=out, sweep=bool(F.l[k] < lv < F.c[k]),
                                  intrend=bool(sl[k - 1] > 0), ts=int(F.ts[k]), **strength(F, b, lv, p, k - 1)))
        if typ not in ("BOS", "CHOCH"):
            continue
        ft = first_touch(F, lv, b + WINDOW, b + R5_AGE)
        if ft is None:
            continue
        k = ft[1]
        newer = int(((tb > b) & (tb < k)).sum())
        if newer >= R5_LIVE:
            continue
        st = strength(F, b, lv, p, b + WINDOW)
        a_t = F.a[k - 1]
        if sl[k - 1] > 0 and a_t > 0:
            entry = min(F.o[k], lv)
            stop = lv - R5_PAD * a_t
            if entry - stop >= MIN_RISK * a_t:
                rows.append(trade_row(F, "R5", k, entry, stop, a_t, F.ub, b=b, p=p, level=lv, btype=typ,
                                      age=k - b, **st))
        if F.l[k] < lv < F.c[k] and sl[k] > 0 and k + 1 < F.n and F.a[k] > 0:
            a_t = F.a[k]
            entry, stop = F.o[k + 1], F.l[k] - PAD * a_t
            if entry - stop >= MIN_RISK * a_t:
                rows.append(trade_row(F, "R5s", k + 1, entry, stop, a_t, F.ub, True, b=b, p=p, level=lv, btype=typ,
                                      age=k - b, **st))
    return rows, holds


def twins(rows, F_other, rng):
    """The coin twin: each trade with a random side at the same fill bar, entry and risk."""
    for r in rows:
        if r["rule"] == "R3":
            continue
        if rng.random() < 0.5:
            for k in ("X2", "TR", "BAND", "mfe"):
                if k in r:
                    r[f"tw_{k}"] = r[k]
            continue
        e = -r["entry"]
        risk = r["entry"] - r["stop"]
        a_t = risk / r["risk_atr"]
        band = F_other.mid[TREND_L] if r["rule"] == "R4" else F_other.ub
        fill = {"open": "open", "down": "up"}[r["fill"]]  # the original fell to the entry: the twin rose to it
        res = exits(F_other.o, F_other.h, F_other.l, F_other.c, r["f"], e, e - risk, a_t, F_other.cost[r["f"]], band,
                    fill)
        for k in ("X2", "TR", "BAND", "mfe"):
            if k in res:
                r[f"tw_{k}"] = res[k]


def flip(df):
    return df.assign(open=-df["open"], close=-df["close"], high=-df["low"], low=-df["high"])


def scan(df, cost_px, twin_seed=None):
    """Every rule on both sides of one series. Returns (trades, holds)."""
    up = df
    dn = flip(df)
    frames = []
    for side, d in ((1, up), (-1, dn)):
        frames.append((side, Frame(*(d[k].to_numpy(float) for k in ("open", "high", "low", "close")),
                                   d["ts"].to_numpy(np.int64), cost_px)))
    trades, holds = [], []
    rng = np.random.default_rng(twin_seed) if twin_seed is not None else None
    for i, (side, F) in enumerate(frames):
        rows = rules_r1_r2(F) + rule_r3(F) + rule_r4(F)
        r5, hl = levels_r5(F)
        rows += r5
        if rng is not None:
            twins(rows, frames[1 - i][1], rng)
        for r in rows:
            r["side"] = side
        for h_ in hl:
            h_["side"] = side
        trades += rows
        holds += hl
    return trades, holds


# ------------------------------------------------------------------------------------------------- data

def resample(df, sec):
    g = df.groupby(df["ts"] // sec * sec)
    out = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
                        "close": g["close"].last(), "volume": g["volume"].sum()})
    if "spread" in df:
        out["spread"] = g["spread"].median()
    return out.rename_axis("ts").reset_index()


def _mt5(sym, iv):
    from mt5bt import load_bars
    db = os.environ.get("MT5BT_DB")
    try:
        df = load_bars(sym, "15m" if iv == "30m" else iv, "sqlite", db)
    except (ValueError, OSError):
        return None, None
    if iv == "30m":
        df = resample(df, 1800)
    import run as R
    from mt5bt import load_specs
    R.DB = db
    spec = load_specs(db).get(sym)
    if spec is None:
        return None, None
    floor = R.spread_floor(sym, spec)
    if not floor > 0:
        sp = df["spread"].to_numpy(float) if "spread" in df else np.array([np.nan])
        floor = float(np.nanmedian(sp)) if np.isfinite(sp).any() else 0.0
    return df, floor * spec.point


def _binance(coin, iv):
    path = BIN / f"{coin}USDT.klines.{'15m' if iv == '30m' else iv}.npz"
    if not path.exists():
        return None
    z = np.load(path)
    df = pd.DataFrame({k: z[k] for k in ("time", "open", "high", "low", "close", "volume")}).rename(columns={"time": "ts"})
    df = df.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
    if df["ts"].max() > 1e11:
        df["ts"] //= 1000
    return resample(df, 1800) if iv == "30m" else df


def _fresh(coin, iv):
    path = FRESH_DIR / f"{coin}USDT.{iv}.npz"
    if not path.exists():
        return None
    z = np.load(path)
    df = pd.DataFrame({k: z[k] for k in ("ts", "open", "high", "low", "close", "volume")})
    df = df.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
    if df["ts"].max() > 1e11:
        df["ts"] //= 1000
    return df


def _deriv1s(feed, iv):
    conn = sqlite3.connect(f"file:{LRC_DB}?mode=ro", uri=True)
    try:
        df = pd.read_sql_query("SELECT ts, open, high, low, close, volume FROM bars WHERE feed = ? AND interval = ? "
                               "ORDER BY ts", conn, params=(feed, iv))
    finally:
        conn.close()
    if df.empty:
        return None, None
    df["ts"] //= 1000
    conn = sqlite3.connect(f"file:{RESEARCH_DB}?mode=ro", uri=True)
    try:
        sp = conn.execute("SELECT ask - bid FROM ticks WHERE feed = ? LIMIT 20000", (feed,)).fetchall()
    finally:
        conn.close()
    return df.drop_duplicates("ts").reset_index(drop=True), float(np.median([s[0] for s in sp])) if sp else 0.0


def klass(venue, sym, iv):
    if venue == "binance":
        return "BINANCE"
    if venue == "fresh":
        return "FRESH"
    if venue == "deriv1s":
        return "DERIV_1S"
    for name, syms in (("FX", FX), ("METAL", METAL), ("INDEX", INDEX), ("ENERGY", ENERGY),
                       ("DERIV_DIFFUSIVE", DERIV_DIFFUSIVE), ("DERIV_JUMPY", DERIV_JUMPY), ("RANGE_BREAK", RANGE_BREAK)):
        if sym in syms:
            return name
    if sym in CRYPTO_MAJOR:
        return "CRYPTO_CFD"
    if sym in CRYPTO_ALT:
        return "KNOWN_BAD" if iv in ("15m", "30m") else "CRYPTO_CFD"
    return None


def load(venue, sym, iv):
    """(bars, cost per bar in price)."""
    if venue in ("binance", "fresh"):
        df = _binance(sym, iv) if venue == "binance" else _fresh(sym, iv)
        if df is None:
            return None, None
        return df, FEE * df["close"].to_numpy(float)
    df, cost = _mt5(sym, iv) if venue == "mt5" else _deriv1s(sym, iv)
    if df is None:
        return None, None
    df = df[["ts", "open", "high", "low", "close", "volume"]].reset_index(drop=True)
    return df, np.full(len(df), cost)


def jobs_list():
    mt5 = FX + METAL + INDEX + ENERGY + CRYPTO_MAJOR + CRYPTO_ALT + DERIV_DIFFUSIVE + DERIV_JUMPY + RANGE_BREAK
    js = [("mt5", s, iv) for s in mt5 for iv in IVS]
    js += [("binance", s, iv) for s in COINS for iv in IVS]
    js += [("deriv1s", s, iv) for s in DERIV_1S for iv in IVS]
    import turn_confirm as C
    js += [("fresh", s, iv) for s in C.FRESH for iv in ("4h", "1d")]
    return js


def one(job):
    """One series and source: trades and holds written to OUT/parts."""
    venue, sym, iv, source = job
    tag = f"{venue}_{sym}_{iv}_{source}".replace(" ", "-").replace("/", "-")
    part = OUT / "parts" / f"{tag}.pkl"
    if part.exists():
        return tag, "cached"
    try:
        df, cost_px = load(venue, sym, iv)
    except Exception as exc:  # noqa: BLE001
        return tag, f"load failed: {exc}"
    if df is None or len(df) < 400:
        return tag, "no data"
    h, l, c = (df[k].to_numpy(float) for k in ("high", "low", "close"))
    a = atr(h, l, c)
    cost_atr = cost_px / np.maximum(a, 1e-12)
    cost_atr = np.where(np.isfinite(cost_atr), cost_atr, np.nanmedian(cost_atr))
    med = float(np.nanmedian(cost_atr[50:])) if len(cost_atr) > 60 else np.nan
    if not med <= MAX_COST_ATR:
        pd.to_pickle(dict(dropped=True, cost_atr=med), part)
        return tag, f"dropped: cost {med:.2f} ATR"
    if source != "real":
        from mcfl import synth
        ts, n = df["ts"].to_numpy(), len(df)
        sigma = float(np.std(np.diff(c)))
        seed = zlib.crc32(f"{venue}{sym}{iv}{source}lrc".encode()) % 100000
        gen = synth.walk if source == "walk" else synth.garch
        w = gen(n, sigma=sigma, seed=seed, steps=WALK_STEPS).reset_index(drop=True).iloc[:n]
        w["ts"] = ts[:len(w)]
        w["volume"] = 0.0
        df = w
        wa = atr(*(df[k].to_numpy(float) for k in ("high", "low", "close")))
        cost_px = cost_atr[:len(df)] * wa
    seed = zlib.crc32(f"{tag}twin".encode()) % 100000 if source == "real" else None
    trades, holds = scan(df, np.asarray(cost_px, float), seed)
    cls = klass(venue, sym, iv)
    t = pd.DataFrame(trades)
    hd = pd.DataFrame(holds)
    for d in (t, hd):
        if len(d):
            d["venue"], d["sym"], d["iv"], d["src"], d["cls"] = venue, sym, iv, source, cls
    for col in t.columns if len(t) else []:
        if t[col].dtype == np.float64:
            t[col] = t[col].astype(np.float32) if col not in ("entry", "stop", "level") else t[col]
    pd.to_pickle(dict(trades=t, holds=hd, cost_atr=med, bars=len(df), first=int(df["ts"].iloc[0])), part)
    return tag, f"{len(t)} trades, {len(hd)} touches"


def run():
    (OUT / "parts").mkdir(parents=True, exist_ok=True)
    js = [(v, s, iv, src) for src in ("real", "walk", "garch") for v, s, iv in jobs_list()]
    if os.environ.get("ONLY"):
        js = [j for j in js if os.environ["ONLY"] in f"{j[0]}_{j[1]}_{j[2]}_{j[3]}"]
    # the biggest first, so the pool drains evenly
    js.sort(key=lambda j: (SEC[j[2]], j[0] != "binance"))
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", 12))) as pool:
        for tag, msg in pool.map(one, js, chunksize=1):
            print(f"  {tag}: {msg}", flush=True)
    print("run done", flush=True)


# ------------------------------------------------------------------------------------------- aggregation

def boot(ts, R, rng, draws=1000):
    """Day-bootstrap of the mean: (lo 5%, hi 95%, one-sided p of mean <= 0)."""
    day = ts // 86400
    u, inv = np.unique(day, return_inverse=True)
    s = np.bincount(inv, weights=R)
    k = np.bincount(inv).astype(float)
    if len(u) < 10:
        return np.nan, np.nan, np.nan
    m = np.empty(draws)
    for i in range(0, draws, 100):
        idx = rng.integers(0, len(u), (min(100, draws - i), len(u)))
        m[i:i + len(idx)] = s[idx].sum(1) / k[idx].sum(1)
    return float(np.quantile(m, 0.05)), float(np.quantile(m, 0.95)), float((m <= 0).mean())


def collect():
    """Read the parts this script wrote (our own pickles, never outside data)."""
    T, H, meta = [], [], []
    for p in sorted((OUT / "parts").glob("*.pkl")):
        d = pd.read_pickle(p)
        if d.get("dropped"):
            meta.append(dict(part=p.stem, dropped=True, cost_atr=d["cost_atr"]))
            continue
        meta.append(dict(part=p.stem, dropped=False, cost_atr=d["cost_atr"], bars=d["bars"], first=d["first"]))
        if len(d["trades"]):
            T.append(d["trades"])
        if len(d["holds"]):
            H.append(d["holds"])
    t = pd.concat(T, ignore_index=True)
    h = pd.concat(H, ignore_index=True)
    for d in (t, h):
        d["half"] = np.where(d["ts"] < SPLIT, "disc", "conf")
    return t, h, pd.DataFrame(meta)


FEATS = ("b_size", "b_speed", "a_size", "a_speed")


def terciles(t, h):
    """Strength score and terciles, cut on the real non-Deriv R1 discovery trades per timeframe."""
    ref = t[(t["rule"] == "R1") & t[f"t{TREND_L}"] & (t["src"] == "real") & t["cls"].isin(NONDERIV) & (t["half"] == "disc")]
    cuts = {}
    for d in (t, h):
        d["score"] = np.nan
        d["tercile"] = None
    for iv in IVS:
        r = ref[ref["iv"] == iv].dropna(subset=list(FEATS))
        if len(r) < 30:
            continue
        sorted_ = {f: np.sort(r[f].to_numpy(float)) for f in FEATS}

        def score(d):
            return sum(np.searchsorted(sorted_[f], d[f].to_numpy(float), "right") / len(sorted_[f]) for f in FEATS)
        rs = score(r)
        q1, q2 = np.quantile(rs, [1 / 3, 2 / 3])
        cuts[iv] = (float(q1), float(q2), len(r))
        for d in (t, h):
            if "b_size" not in d:
                continue
            m = (d["iv"] == iv) & d[list(FEATS)].notna().all(axis=1)
            sc = score(d[m])
            d.loc[m, "score"] = sc
            d.loc[m, "tercile"] = np.where(sc <= q1, "WEAK", np.where(sc <= q2, "MID", "STRONG"))
    return cuts


def cell(x, col, rng, mfe="mfe", draws=1000):
    x = x[x[col].notna()]
    R = x[col].to_numpy(float)
    if len(R) == 0:
        return dict(n=0)
    lo, hi, p = boot(x["ts"].to_numpy(np.int64), R, rng, draws) if len(R) > 30 else (np.nan, np.nan, np.nan)
    out = dict(n=len(R), R=R.mean(), lo=lo, hi=hi, p=p, win=(R > 0).mean())
    if mfe in x:
        m = x[mfe].to_numpy(float)
        out.update({f"P{N}": float((m >= N).mean()) for N in NS})
    return out


RULE_CELLS = {  # name: (rule, filter column or None, exits)
    "R1": ("R1", f"t{TREND_L}", ("X2", "TR", "BAND")),
    "R1_L50": ("R1", "t50", ("X2", "TR", "BAND")),
    "R1_L200": ("R1", "t200", ("X2", "TR", "BAND")),
    "R2": ("R2", None, ("X2", "TR", "BAND")),
    "R3": ("R3", None, ("X2",)),
    "R4": ("R4", None, ("X2", "TR", "BAND")),
    "R5": ("R5", None, ("X2", "TR", "BAND")),
    "R5s": ("R5s", None, ("X2", "TR", "BAND")),
}


def sel(t, name):
    rule, flt, _ = RULE_CELLS[name]
    x = t[t["rule"] == rule]
    return x[x[flt].astype(bool)] if flt else x


def pools(x):
    """(class label, rows) for each class, the non-Deriv pool and the Deriv 1s Volatility 10 alone."""
    yield "NONDERIV", x[x["cls"].isin(NONDERIV)]
    for k in CLASS_ORDER:
        yield k, x[x["cls"] == k]
    yield "V10_1S", x[x["sym"] == "volatility_10_1s_index"]


def agg():
    rng = np.random.default_rng(2026)
    t, h, meta = collect()
    cuts = terciles(t, h)
    t.to_pickle(OUT / "lrc_trades.pkl.gz")
    h.to_pickle(OUT / "lrc_holds.pkl.gz")
    meta.to_csv(OUT / "lrc_series.csv", index=False)
    json.dump(cuts, open(OUT / "lrc_cuts.json", "w"), indent=1)
    rows = []
    for name, (_rule, _f, exs) in RULE_CELLS.items():
        x0 = sel(t, name)
        for cls, x1 in pools(x0):
            for iv in IVS + ("ALL",):
                x2 = x1 if iv == "ALL" else x1[x1["iv"] == iv]
                if not len(x2):
                    continue
                for half in ("disc", "conf"):
                    x3 = x2[x2["half"] == half]
                    for ex in exs:
                        for src in ("real", "walk", "garch", "twin"):
                            if src == "twin":
                                if name == "R3":
                                    continue
                                x4 = x3[x3["src"] == "real"]
                                c = cell(x4, f"tw_{ex}", rng, "tw_mfe")
                            else:
                                c = cell(x3[x3["src"] == src], ex, rng)
                            if c["n"]:
                                rows.append(dict(rule=name, cls=cls, iv=iv, half=half, exit=ex, src=src, **c))
    tab = pd.DataFrame(rows)
    tab.to_csv(OUT / "lrc_table.csv", index=False)
    # strength terciles: R1 and R2, X2
    srows = []
    for name in ("R1", "R2", "R5"):
        x0 = sel(t, name)
        for cls, x1 in pools(x0):
            for iv in IVS + ("ALL",):
                x2 = x1 if iv == "ALL" else x1[x1["iv"] == iv]
                for half in ("disc", "conf"):
                    for src in ("real", "walk", "garch"):
                        x3 = x2[(x2["half"] == half) & (x2["src"] == src)]
                        for ter in ("WEAK", "MID", "STRONG"):
                            c = cell(x3[x3["tercile"] == ter], "X2", rng)
                            if c["n"]:
                                srows.append(dict(rule=name, cls=cls, iv=iv, half=half, src=src, tercile=ter, **c))
    stab = pd.DataFrame(srows)
    stab.to_csv(OUT / "lrc_strength.csv", index=False)
    # hold rates
    h["age_b"] = pd.cut(h["age"], [-1, 20, 100, 10 ** 6], labels=["0-20", "20-100", "100+"]).astype(str)
    hrows = []
    for cls, x1 in pools(h):
        for iv in IVS + ("ALL",):
            x2 = x1 if iv == "ALL" else x1[x1["iv"] == iv]
            for src in ("real", "walk", "garch"):
                x3 = x2[x2["src"] == src]
                for typ, x4 in x3.groupby("type"):
                    base = dict(cls=cls, iv=iv, src=src, type=typ)
                    hrows.append(dict(**base, split="all", value="all", n=len(x4), hold=x4["hold"].mean()))
                    for col in ("age_b", "sweep", "intrend", "tercile"):
                        for v, x5 in x4.groupby(col):
                            hrows.append(dict(**base, split=col, value=str(v), n=len(x5), hold=x5["hold"].mean()))
    htab = pd.DataFrame(hrows)
    htab.to_csv(OUT / "lrc_holds.csv", index=False)
    verdicts(tab, stab, htab, cuts)


def verdicts(tab, stab, htab, cuts):
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 500)
    pd.set_option("display.max_columns", 30)
    lines = []

    def g(rule, cls, iv, half, ex, src):
        r = tab[(tab["rule"] == rule) & (tab["cls"] == cls) & (tab["iv"] == iv) & (tab["half"] == half)
                & (tab["exit"] == ex) & (tab["src"] == src)]
        return r.iloc[0] if len(r) else None

    p, d = g("R1", "NONDERIV", "ALL", "conf", "X2", "real"), g("R1", "NONDERIV", "ALL", "disc", "X2", "real")
    w, gw, tw = (g("R1", "NONDERIV", "ALL", "conf", "X2", s) for s in ("walk", "garch", "twin"))
    fr = g("R1", "FRESH", "ALL", "conf", "X2", "real")
    ok = (p is not None and d is not None and p["R"] > 0 and p["lo"] > 0 and d["R"] > 0
          and p["R"] > w["R"] and p["R"] > gw["R"] and p["R"] > tw["R"])
    lines.append(f"P1 R1 X2 non-Deriv 15m-1d, confirmation: R {p['R']:+.4f} [{p['lo']:+.4f}, {p['hi']:+.4f}] n={int(p['n'])}; "
                 f"discovery {d['R']:+.4f}; walk {w['R']:+.4f}; garch {gw['R']:+.4f}; twin {tw['R']:+.4f}; "
                 f"fresh {fr['R'] if fr is not None else float('nan'):+.4f} -> {'PASSES' if ok else 'fails'}")

    def s(rule, cls, iv, half, src, ter):
        r = stab[(stab["rule"] == rule) & (stab["cls"] == cls) & (stab["iv"] == iv) & (stab["half"] == half)
                 & (stab["src"] == src) & (stab["tercile"] == ter)]
        return r.iloc[0] if len(r) else None
    sp, sd = s("R1", "NONDERIV", "ALL", "conf", "real", "STRONG"), s("R1", "NONDERIV", "ALL", "disc", "real", "STRONG")
    wk = s("R1", "NONDERIV", "ALL", "conf", "real", "WEAK")
    if sp is not None and wk is not None:
        sw = {src: (s("R1", "NONDERIV", "ALL", "conf", src, "STRONG"), s("R1", "NONDERIV", "ALL", "conf", src, "WEAK"))
              for src in ("walk", "garch")}
        gap = sp["R"] - wk["R"]
        wgap = {k: v[0]["R"] - v[1]["R"] for k, v in sw.items()}
        ok2 = (sp["R"] > 0 and sp["lo"] > 0 and sd["R"] > 0 and sp["R"] > sw["walk"][0]["R"]
               and sp["R"] > sw["garch"][0]["R"] and gap > 0 and all(gap > v for v in wgap.values()))
        lines.append(f"P2 R1 STRONG X2 non-Deriv, confirmation: R {sp['R']:+.4f} [{sp['lo']:+.4f}, {sp['hi']:+.4f}] "
                     f"n={int(sp['n'])}; discovery {sd['R']:+.4f}; WEAK {wk['R']:+.4f} (gap {gap:+.4f}); walk STRONG "
                     f"{sw['walk'][0]['R']:+.4f} gap {wgap['walk']:+.4f}; garch STRONG {sw['garch'][0]['R']:+.4f} gap "
                     f"{wgap['garch']:+.4f} -> {'PASSES' if ok2 else 'fails'}")
    # BH over secondary cells: real, confirmation, single class x single timeframe, every rule and exit
    sec = tab[(tab["src"] == "real") & (tab["half"] == "conf") & (tab["iv"] != "ALL")
              & ~tab["cls"].isin(["NONDERIV", "V10_1S"]) & tab["p"].notna()].copy()
    m = len(sec)
    sec = sec.sort_values("p")
    sec["bh"] = sec["p"].to_numpy() <= 0.10 * np.arange(1, m + 1) / m
    k = np.flatnonzero(sec["bh"].to_numpy())
    surv = sec.iloc[:k[-1] + 1] if len(k) else sec.iloc[:0]
    keep = []
    for _, r in surv.iterrows():
        ws = [g(r["rule"], r["cls"], r["iv"], "conf", r["exit"], s_) for s_ in ("walk", "garch")]
        keep.append(all(x is not None and r["R"] > x["R"] for x in ws))
    surv = surv.assign(beats_walks=keep)
    surv.to_csv(OUT / "lrc_bh.csv", index=False)
    lines.append(f"BH q=0.10 over {m} secondary cells (real, confirmation, rule x exit x class x timeframe): "
                 f"{len(surv)} survive, {int(np.sum(keep))} of them above both walks")
    lines.append(f"tercile cut-offs (score 0..4, n discovery R1): {cuts}")
    txt = "\n".join(lines)
    (OUT / "lrc_verdicts.txt").write_text(txt + "\n")
    print(txt)
    show = tab[(tab["half"] == "conf") & (tab["iv"] == "ALL") & (tab["exit"] == "X2")]
    print(show[["rule", "cls", "src", "n", "R", "lo", "hi", "P0.5", "P1", "P2", "P4", "P10"]].round(3).to_string(index=False))


# ------------------------------------------------------------------------------------------------- plots

SRC_STYLE = (("real", "-o", "#1d3557"), ("walk", "--s", "#e76f51"), ("garch", ":^", "#2a9d8f"), ("twin", "-.d", "#9b5de5"))


def plot_pnr(tab, rule, ex="X2", half="conf"):
    import matplotlib.pyplot as plt
    classes = [c for c in ("NONDERIV",) + CLASS_ORDER if len(tab[(tab["rule"] == rule) & (tab["cls"] == c)])]
    fig, axes = plt.subplots(len(classes), len(IVS) + 1, figsize=(3.2 * (len(IVS) + 1), 2.5 * len(classes)),
                             sharey=True, squeeze=False)
    for i, cls in enumerate(classes):
        for j, iv in enumerate(IVS + ("ALL",)):
            ax = axes[i, j]
            for src, st, col in SRC_STYLE:
                r = tab[(tab["rule"] == rule) & (tab["cls"] == cls) & (tab["iv"] == iv) & (tab["half"] == half)
                        & (tab["exit"] == ex) & (tab["src"] == src)]
                if len(r) and "P1" in r:
                    r = r.iloc[0]
                    ax.plot(NS, [r[f"P{N}"] for N in NS], st, color=col, ms=3, lw=1,
                            label=f"{src} {r['R']:+.3f} n{int(r['n'])}")
            ax.plot(NS, [1 / (N + 1) for N in NS], color="grey", lw=0.8, label="1/(N+1)")
            ax.set_xscale("log")
            ax.set_yscale("log")
            ax.set_ylim(0.01, 1)
            ax.set_title(f"{cls} {iv}", fontsize=8)
            ax.legend(fontsize=5.5, loc="lower left")
            ax.tick_params(labelsize=6)
    fig.suptitle(f"{rule}: P(+N R before -1R), {half}; real vs iid walk, GARCH walk, coin twin, 1/(N+1). "
                 f"Legend: mean R per trade at {ex} after costs, n", fontsize=10)
    fig.tight_layout()
    fig.savefig(OUT / f"lrc_pnr_{rule}.png", dpi=70)
    plt.close(fig)


def plot_compare(tab):
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 3, figsize=(20, 6))
    classes = ["NONDERIV"] + [c for c in CLASS_ORDER if c != "KNOWN_BAD"]
    for ax, metric in zip(axes[:2], ("R", "P2")):
        x = np.arange(len(classes))
        for k, (rule, col) in enumerate((("R1", "#1d3557"), ("R4", "#e63946"))):
            for m, src in enumerate(("real", "walk")):
                v = []
                for cls in classes:
                    r = tab[(tab["rule"] == rule) & (tab["cls"] == cls) & (tab["iv"] == "ALL") & (tab["half"] == "conf")
                            & (tab["exit"] == "X2") & (tab["src"] == src)]
                    v.append(r.iloc[0][metric] if len(r) else np.nan)
                ax.bar(x + (2 * k + m) * 0.2 - 0.3, v, 0.2, color=col, alpha=1.0 if src == "real" else 0.4,
                       label=f"{rule} {src}")
        if metric == "P2":
            ax.axhline(1 / 3, color="grey", lw=0.8, ls="--", label="1/3")
        ax.axhline(0, color="k", lw=0.6)
        ax.set_xticks(x)
        ax.set_xticklabels(classes, rotation=45, ha="right", fontsize=8)
        ax.set_title({"R": "mean R after costs (2R exit), confirmation", "P2": "P(+2R before -1R), confirmation"}[metric])
        ax.legend(fontsize=8)
    ax = axes[2]
    for rule, col in (("R1", "#1d3557"), ("R4", "#e63946")):
        for src, st in (("real", "-o"), ("walk", "--s")):
            r = tab[(tab["rule"] == rule) & (tab["cls"] == "NONDERIV") & (tab["iv"] == "ALL") & (tab["half"] == "conf")
                    & (tab["exit"] == "X2") & (tab["src"] == src)]
            if len(r):
                r = r.iloc[0]
                ax.plot(NS, [r[f"P{N}"] for N in NS], st, color=col, label=f"{rule} {src}")
    ax.plot(NS, [1 / (N + 1) for N in NS], color="grey", label="1/(N+1)")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_title("non-Deriv pool: P(N R), R1 (with the trend) vs R4 (fade to value)")
    ax.legend()
    fig.suptitle("R1 (break and retest, with the LRC trend) against R4 (counter-trend fade to value)")
    fig.tight_layout()
    fig.savefig(OUT / "lrc_r1_vs_r4.png", dpi=75)
    plt.close(fig)


def plot_strength(stab):
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, len(IVS) + 1, figsize=(24, 8), sharey="row")
    for i, rule in enumerate(("R1", "R2")):
        for j, iv in enumerate(IVS + ("ALL",)):
            ax = axes[i, j]
            for k, (src, col) in enumerate((("real", "#1d3557"), ("walk", "#e76f51"), ("garch", "#2a9d8f"))):
                for half, alpha in (("disc", 0.45), ("conf", 1.0)):
                    v = []
                    for ter in ("WEAK", "MID", "STRONG"):
                        r = stab[(stab["rule"] == rule) & (stab["cls"] == "NONDERIV") & (stab["iv"] == iv)
                                 & (stab["half"] == half) & (stab["src"] == src) & (stab["tercile"] == ter)]
                        v.append(r.iloc[0]["R"] if len(r) else np.nan)
                    ax.plot([0, 1, 2], v, "-o", color=col, alpha=alpha, label=f"{src} {half}")
            ax.axhline(0, color="k", lw=0.6)
            ax.set_xticks([0, 1, 2])
            ax.set_xticklabels(["WEAK", "MID", "STRONG"])
            ax.set_title(f"{rule} {iv} (non-Deriv)", fontsize=9)
            ax.legend(fontsize=6)
    axes[0, 0].set_ylabel("mean R, 2R exit, after costs")
    fig.suptitle("strength of the moves before and after the break: mean R by tercile, real vs walks")
    fig.tight_layout()
    fig.savefig(OUT / "lrc_strength.png", dpi=75)
    plt.close(fig)


def plot_holds(htab):
    import matplotlib.pyplot as plt
    classes = ["NONDERIV"] + [c for c in CLASS_ORDER if c != "KNOWN_BAD"]
    fig, axes = plt.subplots(1, 4, figsize=(24, 6), sharey=True)
    for ax, split in zip(axes, ("all", "age_b", "sweep", "tercile")):
        x = htab[(htab["iv"] == "ALL") & (htab["split"] == split) & (htab["cls"] == "NONDERIV")]
        labels = []
        vals = {s: [] for s in ("real", "walk", "garch")}
        for (typ, val), g_ in x.groupby(["type", "value"]):
            labels.append(f"{typ}\n{val}")
            for s_ in vals:
                r = g_[g_["src"] == s_]
                vals[s_].append(r.iloc[0]["hold"] if len(r) else np.nan)
        xs = np.arange(len(labels))
        for k, (s_, col) in enumerate((("real", "#1d3557"), ("walk", "#e76f51"), ("garch", "#2a9d8f"))):
            ax.bar(xs + (k - 1) * 0.27, vals[s_], 0.27, color=col, label=s_)
        ax.set_xticks(xs)
        ax.set_xticklabels(labels, fontsize=7, rotation=90)
        ax.set_ylim(0.4, 0.75)
        ax.axhline(0.5, color="grey", lw=0.6)
        ax.set_title(f"non-Deriv, split by {split}")
        ax.legend(fontsize=8)
    axes[0].set_ylabel("P(1 ATR away before a close 1 ATR through)")
    fig.suptitle("hold rate on the first touch: plain swing levels vs BOS / CHoCH levels, real vs walks")
    fig.tight_layout()
    fig.savefig(OUT / "lrc_holds.png", dpi=75)
    plt.close(fig)
    _ = classes


def gallery(t, rule, sel_, fname, title):
    """Six winners and six losers, drawn as the desk would see them."""
    import matplotlib.pyplot as plt
    x = t[(t["rule"] == rule) & (t["src"] == "real") & sel_(t)]
    if rule == "R1":
        x = x[x[f"t{TREND_L}"].astype(bool)]
    if not len(x):
        return
    rng = np.random.default_rng(7)
    for tag, sub in (("winners", x[x["X2"] > 0]), ("losers", x[x["X2"] <= 0])):
        if not len(sub):
            continue
        pick = sub.iloc[np.sort(rng.choice(len(sub), min(6, len(sub)), replace=False))]
        fig, axes = plt.subplots(2, 3, figsize=(24, 12))
        for ax, (_, r) in zip(axes.flat, pick.iterrows()):
            df, _c = load(r["venue"], r["sym"], r["iv"])
            frame = df if r["side"] > 0 else flip(df)
            s = r["side"]
            c = frame["close"].to_numpy(float)
            slope, mid, dev = lrc(c, TREND_L)
            f, b, p = int(r["f"]), int(r["b"]), int(r["p"])
            xb = int(r["x2_bar"])
            i0, i1 = max(0, min(p, b) - 40), min(len(df) - 1, max(f, xb) + 25)
            w = df.iloc[i0:i1 + 1]
            xs = np.arange(i0, i1 + 1)
            upc = (w["close"] >= w["open"]).to_numpy()
            ax.vlines(xs, w["low"], w["high"], color="#555", lw=0.6)
            ax.bar(xs[upc], (w["close"] - w["open"])[upc], bottom=w["open"][upc], color="#2a9d8f", width=0.7)
            ax.bar(xs[~upc], (w["close"] - w["open"])[~upc], bottom=w["open"][~upc], color="#e76f51", width=0.7)
            # the rolling channel (what was known at each bar) and the channel fitted at the entry
            ax.plot(xs, s * mid[i0:i1 + 1], color="#457b9d", lw=1, label="LRC(100) mid, rolling")
            ax.plot(xs, s * (mid + BAND_K * dev)[i0:i1 + 1], color="#457b9d", lw=0.6, ls="--")
            ax.plot(xs, s * (mid - BAND_K * dev)[i0:i1 + 1], color="#457b9d", lw=0.6, ls="--")
            k0 = max(0, f - 1 - TREND_L + 1)
            xx = np.arange(k0, f)
            bfit = slope[f - 1]
            yfit = mid[f - 1] + bfit * (xx - (f - 1))
            ax.plot(xx, s * yfit, color="purple", lw=1.4, label="channel at the entry")
            ax.plot(xx, s * (yfit + BAND_K * dev[f - 1]), color="purple", lw=0.8)
            ax.plot(xx, s * (yfit - BAND_K * dev[f - 1]), color="purple", lw=0.8)
            lev, ent, stp = r["level"], r["entry"], r["stop"]
            risk = ent - stp
            name = "BOS" if rule != "R5" else str(r.get("btype", "BOS"))
            ax.hlines(s * lev, p, f, colors="black", lw=1.2, label=f"broken swing / {name} level")
            ax.plot([p], [s * lev], "kv" if s > 0 else "k^", ms=8)
            ax.axvline(b, color="orange", lw=1, ls=":", label="break (close beyond)")
            ax.hlines(s * stp, f, xb, colors="red", lw=1.2, label="stop")
            ax.hlines(s * (ent + 2 * risk), f, xb, colors="green", lw=1.2, label="target 2R")
            ax.plot([f], [s * ent], ">", color="k", ms=10, label="entry")
            xr = r["X2"]  # net R at the exit
            ax.plot([xb], [s * (ent + xr * risk)], "x", color="k", ms=10, mew=2, label="exit (net of cost)")
            ax.set_xlim(i0 - 1, i1 + 1)
            when = pd.Timestamp(int(r["ts"]), unit="s", tz="UTC")
            ax.set_title(f"{r['sym']} {r['iv']} {'buy' if s > 0 else 'sell'} {when:%Y-%m-%d %H:%M}  "
                         f"strength {r.get('tercile') or 'n/a'}  risk {r['risk_atr']:.2f} ATR -> {xr:+.2f}R", fontsize=9)
            ax.legend(fontsize=6, loc="best")
        fig.suptitle(f"{title} ({tag}): black - the broken swing and its level; orange dotted - the break; "
                     "purple - the channel at the entry; red/green - stop/target", fontsize=11)
        fig.tight_layout()
        fig.savefig(OUT / f"{fname}_{tag}.png", dpi=70)
        plt.close(fig)


def plot():
    import matplotlib
    matplotlib.use("Agg")
    tab = pd.read_csv(OUT / "lrc_table.csv")
    for rule in RULE_CELLS:
        plot_pnr(tab, rule)
    plot_compare(tab)
    plot_strength(pd.read_csv(OUT / "lrc_strength.csv"))
    plot_holds(pd.read_csv(OUT / "lrc_holds.csv"))
    t = pd.read_pickle(OUT / "lrc_trades.pkl.gz")
    v10 = "volatility_10_1s_index"
    gallery(t, "R1", lambda d: (d["sym"] == v10) & d["iv"].isin(["15m", "30m"]), "lrc_gallery_v10",
            "R1 on Volatility 10 (1s), M15/M30")
    gallery(t, "R1", lambda d: (d["sym"] == "XAUUSD") & d["iv"].isin(["15m", "30m"]), "lrc_gallery_xau",
            "R1 on XAUUSD, M15/M30")
    gallery(t, "R5", lambda d: d["cls"].isin(NONDERIV) & d["iv"].isin(["1h", "4h"]), "lrc_gallery_r5",
            "R5: a pullback to an earlier BOS / CHoCH level, non-Deriv 1h/4h")
    print("plots written", flush=True)


def main():
    {"run": run, "agg": agg, "plot": plot}[os.environ.get("MODE", "run")]()


if __name__ == "__main__":
    main()
