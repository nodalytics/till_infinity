"""Every testable idea from the imported catalogues, as a causal rule with trade geometry.

Each setup takes a `Ctx` and returns a signal frame for mt5bt: `i` (the bar whose close knows the
signal), `side`, `stop_px` (the structural invalidation price), and for resting entries `entry`
(the price), `limit` and `expires`. `run.py` turns `stop_px` into mt5bt's stop distance and adds
the exit (trail, 4R or 10R), so the entry and the invalidation are each idea's own and the exits
are the same for all.

The geometry is a trader's, not the source's where the source left it loose: enter at the
structure, put the stop just beyond what would prove the idea wrong (`BUF` x ATR past it), and let
the market decide the exit. Where the source did fix a geometry (zma's stop at one sigma and target
at the mean, structural_setup's 3R), that version is run as well, marked `src`.

Mirror images are built by `mirror()` so every rule is symmetric by construction: the bear side is
the bull side on the negated chart (code-symmetry test, catalogue 2.24).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

import prims as P

BUF = 0.1  # stop buffer beyond the structure, in ATR


@dataclass
class Ctx:
    sym: str
    family: str
    interval: str
    sec: int
    df: pd.DataFrame  # bid OHLC + ts (+ tick_volume)
    htf: dict = field(default_factory=dict)  # interval -> (df, index map from this TF)
    peers: dict = field(default_factory=dict)  # symbol -> close series aligned to df.ts
    cache: dict = field(default_factory=dict)

    def get(self, key, fn):
        if key not in self.cache:
            self.cache[key] = fn()
        return self.cache[key]

    @property
    def a(self):
        return self.get("atr", lambda: P.atr(self.df, 14))


def flip(df: pd.DataFrame) -> pd.DataFrame:
    """The chart upside down: negate prices, swap high and low."""
    out = df.copy()
    out["open"], out["close"] = -df["open"], -df["close"]
    out["high"], out["low"] = -df["low"], -df["high"]
    return out


def mirror(fn):
    """Run a bull-side rule on the chart and on its mirror; the mirror's longs are shorts."""
    def both(ctx: Ctx) -> pd.DataFrame:
        bull = fn(ctx, ctx.df)
        m = Ctx(ctx.sym, ctx.family, ctx.interval, ctx.sec, flip(ctx.df),
                {k: (flip(d), ix) for k, (d, ix) in ctx.htf.items()},
                {k: -v for k, v in ctx.peers.items()})
        m.cache["atr"] = ctx.a
        bear = fn(m, m.df)
        if not bear.empty:
            bear = bear.copy()
            bear["side"] = -bear["side"]
            for col in ("stop_px", "entry", "target_px"):
                if col in bear:
                    bear[col] = -bear[col]
        return pd.concat([bull, bear], ignore_index=True)
    both.__name__ = fn.__name__
    return both


def frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["i", "side", "stop_px", "entry", "limit", "expires", "tag"]) \
        if not rows else pd.DataFrame(rows)


def long_(i, stop_px, entry=np.nan, limit=0, expires=1, tag=""):
    return dict(i=int(i), side=1, stop_px=float(stop_px), entry=float(entry), limit=int(limit),
                expires=int(expires), tag=tag)


def arrays(df):
    return (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))


# ------------------------------------------------------------------------------------- SMC / ICT

def _bos_up(df, ph_known):
    """Bars whose close first takes the last known pivot high: (i, level, pivot index)."""
    c = df["close"].to_numpy()
    out, used = [], set()
    for i, piv in enumerate(ph_known):
        if not piv:
            continue
        p_idx, lvl = piv[-1]
        if p_idx in used or i <= p_idx:
            continue
        if c[i] > lvl:
            used.add(p_idx)
            out.append((i, lvl, p_idx))
    return out


def _piv(ctx, df, left=5, right=5, k=2):
    key = ("piv", id(df), left, right, k)
    return ctx.get(key, lambda: _piv_raw(df, left, right, k))


def _piv_raw(df, left, right, k):
    ph, pl = P.pivots(df["high"].to_numpy(), df["low"].to_numpy(), left, right)
    n = len(df)
    return P.last_known(ph, n, k), P.last_known(pl, n, k)


@mirror
def bos_fvg(ctx, df):
    """Break of structure up with a fresh bullish FVG (gap >= 0.3 ATR) in the last 3 bars."""
    o, h, l, c = arrays(df)
    a = ctx.a
    ph, _ = _piv(ctx, df)
    rows = []
    for i, lvl, _p in _bos_up(df, ph):
        for k in range(i, max(i - 3, 2) - 1, -1):  # the FVG's third candle k, middle k-1 >= i-3
            top, bot = l[k], h[k - 2]
            if top - bot >= 0.3 * a[i] and l[k + 1:i + 1].min(initial=np.inf) > bot:
                stop = bot - BUF * a[i]
                rows.append(long_(i, stop, tag="mkt"))
                rows.append(long_(i, stop, entry=top, limit=1, expires=10, tag="lmt"))
                break
    return frame(rows)


@mirror
def choch(ctx, df):
    """Change of character: after lower highs and lower lows, the first close above the last LH."""
    o, h, l, c = arrays(df)
    a = ctx.a
    ph, pl = _piv(ctx, df)
    rows, used = [], set()
    for i in range(len(df)):
        if len(ph[i]) < 2 or len(pl[i]) < 2:
            continue
        (h1i, h1), (h2i, h2) = ph[i]
        (_, l1), (_, l2) = pl[i]
        if not (h2 < h1 and l2 < l1) or h2i in used:
            continue
        if c[i] > h2 and c[i - 1] <= h2:
            used.add(h2i)
            low = l[h2i:i + 1].min()
            rows.append(long_(i, low - BUF * a[i]))
    return frame(rows)


@mirror
def sweep_equal_lows(ctx, df):
    """Equal lows (two known pivot lows within 0.1 ATR, inside 50 bars) taken by a wick, close back above."""
    o, h, l, c = arrays(df)
    a = ctx.a
    _, pl = _piv(ctx, df, k=4)
    rows, used = [], set()
    for i in range(1, len(df)):
        lows = [(j, v) for j, v in pl[i] if i - j <= 50]
        if len(lows) < 2 or not a[i] > 0:
            continue
        for (j1, v1), (j2, v2) in zip(lows[:-1], lows[1:]):
            if abs(v1 - v2) <= 0.1 * a[i] and (j1, j2) not in used:
                pool = min(v1, v2)
                if l[i] < pool and c[i] > pool and l[max(j2, j1) + 1:i].min(initial=np.inf) >= pool:
                    used.add((j1, j2))
                    rows.append(long_(i, l[i] - BUF * a[i]))
                    break
    return frame(rows)


def _order_blocks(df, a, k_body=1.5):
    """Bullish order blocks: a bearish bar followed by a bullish bar with body >= 1.5 ATR."""
    o, h, l, c = arrays(df)
    out = []
    for k in range(1, len(df) - 1):
        if c[k] < o[k] and c[k + 1] > o[k + 1] and (c[k + 1] - o[k + 1]) >= k_body * a[k + 1] > 0:
            out.append((k + 1, l[k], h[k]))  # known at k+1, zone [low, high]
    return out


@mirror
def order_block(ctx, df):
    """Order-block retest: the first return into the zone, confirmed by a bullish candle (mkt), or a
    resting limit at the zone's top (lmt). Stop beyond the zone's low."""
    o, h, l, c = arrays(df)
    a = ctx.a
    cd = ctx.get(("cd", id(df)), lambda: P.candles(df, a))
    rows = []
    for known, zl, zh in _order_blocks(df, a):
        rows.append(long_(known, zl - BUF * a[known], entry=zh, limit=1, expires=50, tag="lmt"))
        for i in range(known + 1, min(len(df), known + 51)):
            if c[i] < zl:
                break
            if l[i] <= zh:
                if cd["bull"].iat[i] and c[i] > zl:
                    rows.append(long_(i, min(zl, l[i]) - BUF * a[i], tag="mkt"))
                break
    return frame(rows)


@mirror
def cisd(ctx, df):
    """Change in state of delivery at a support: a run of >= 2 down candles into the level, and a
    close back above the open of the run's first candle. `swept` when the run took the level."""
    o, h, l, c = arrays(df)
    a = ctx.a
    _, pl = _piv(ctx, df)
    rows, last_line = [], None
    for i in range(12, len(df)):
        if not pl[i] or not a[i] > 0:
            continue
        lvl = pl[i][-1][1]
        # the last run of >= 2 consecutive down candles in the 10 bars before i
        j = i - 1
        while j > i - 11 and not (c[j] < o[j]):
            j -= 1
        end = j
        while j > i - 11 and c[j] < o[j]:
            j -= 1
        start = j + 1
        if end - start + 1 < 2:
            continue
        leg_low = l[start:end + 1].min()
        if abs(leg_low - lvl) > 1.5 * a[i]:
            continue
        line = o[start]
        if c[i] > line and c[i - 1] <= line and (start, i) != last_line:
            last_line = (start, i)
            rows.append(long_(i, leg_low - BUF * a[i], tag="swept" if leg_low < lvl else "near"))
    return frame(rows)


@mirror
def turtle_soup(ctx, df):
    """A new 20-bar low, then a close back above the prior 20-bar low within 3 bars."""
    o, h, l, c = arrays(df)
    a = ctx.a
    prior = pd.Series(l).shift(1).rolling(20, min_periods=20).min().to_numpy()
    rows, last = [], -10
    for i in range(22, len(df)):
        for j in range(i, i - 3, -1):
            if l[j] < prior[j] and c[i] > prior[j] and i - last > 3:
                rows.append(long_(i, l[j:i + 1].min() - BUF * a[i]))
                last = i
                break
    return frame(rows)


@mirror
def crt_raid(ctx, df):
    """Candle range theory: a bar takes the previous bar's low and closes back inside its range."""
    o, h, l, c = arrays(df)
    a = ctx.a
    i = np.flatnonzero((l[1:] < l[:-1]) & (c[1:] > l[:-1]) & (c[1:] < h[:-1])) + 1
    return frame([long_(k, l[k] - BUF * a[k]) for k in i if a[k] > 0])


@mirror
def ote(ctx, df):
    """Optimal trade entry: after a break of structure, a limit at the 0.705 retracement of the leg
    from the last pivot low to the break bar's high; stop beyond the leg's low."""
    o, h, l, c = arrays(df)
    a = ctx.a
    ph, pl = _piv(ctx, df)
    rows = []
    for i, _lvl, _p in _bos_up(df, ph):
        if not pl[i]:
            continue
        lo = pl[i][-1][1]
        hi = h[i]
        if hi - lo < a[i]:
            continue
        rows.append(long_(i, lo - BUF * a[i], entry=hi - 0.705 * (hi - lo), limit=1, expires=20))
    return frame(rows)


@mirror
def ame_sweep(ctx, df):
    """Accumulation-manipulation-expansion: a 20-bar range no wider than 3 ATR, a wick below its low
    that closes back inside (mkt, stop under the wick), or the later close above the range's high
    within 10 bars (exp, stop under the breakout bar)."""
    o, h, l, c = arrays(df)
    a = ctx.a
    hi = pd.Series(h).shift(1).rolling(20).max().to_numpy()
    lo = pd.Series(l).shift(1).rolling(20).min().to_numpy()
    rows = []
    i = 21
    while i < len(df):
        if a[i] > 0 and hi[i] - lo[i] <= 3 * a[i] and l[i] < lo[i] and c[i] > lo[i]:
            rows.append(long_(i, l[i] - BUF * a[i], tag="sweep"))
            for k in range(i + 1, min(len(df), i + 11)):
                if c[k] < l[i]:
                    break
                if c[k] > hi[i]:
                    rows.append(long_(k, l[k] - BUF * a[k], tag="expansion"))
                    break
            i += 5
        i += 1
    return frame(rows)


@mirror
def impulse_zone(ctx, df):
    """Demand from an impulse bar (body > 1.5 ATR, small upper wick, tick volume > 1.5x its mean):
    a resting limit at the bar's open, stop beyond its low, valid 100 bars."""
    o, h, l, c = arrays(df)
    a = ctx.a
    v = P.tick_volume(df)
    vm = P.sma(v, 20)
    rng = np.maximum(h - l, 1e-12)
    ok = (c - o > 1.5 * a) & ((h - c) < 0.25 * rng) & (v > 1.5 * np.nan_to_num(vm, nan=np.inf))
    return frame([long_(k, l[k] - BUF * a[k], entry=o[k], limit=1, expires=100)
                  for k in np.flatnonzero(ok)])


# ------------------------------------------------------------------- levels: bjorgum, sage style

def _bjorgum_zones(df, left=20, right=15, keep=4):
    """Heikin-Ashi pivot zones, half-width min(0.5 ATR30, 2.5%), the newest `keep` per side,
    each known `right` bars after its pivot. Returns per-bar lists of (bottom, top, is_res)."""
    o, h, l, c = arrays(df)
    hc = (o + h + l + c) / 4
    ho = np.empty_like(hc)
    ho[0] = (o[0] + c[0]) / 2
    for i in range(1, len(hc)):
        ho[i] = (ho[i - 1] + hc[i - 1]) / 2
    top, bot = np.maximum(ho, hc), np.minimum(ho, hc)
    a30 = P.atr(df, 30)
    ph, pl = P.pivots(top, bot, left, right)
    ev = sorted([(k, p, v, True) for k, p, v in ph] + [(k, p, v, False) for k, p, v in pl])
    out, j = [], 0
    res, sup = [], []
    for i in range(len(df)):
        while j < len(ev) and ev[j][0] <= i:
            _, p, v, is_res = ev[j]
            half = min(0.5 * np.nan_to_num(a30[p]), 0.025 * abs(v))
            (res if is_res else sup).append((v - half, v + half, is_res))
            del res[:-keep], sup[:-keep]
            j += 1
        out.append(res + sup)
    return out


@mirror
def bjorgum(ctx, df):
    """Sage's bjorgum reactions at the nearest zone within 1 ATR30, confirmed by a candle:
    break (close up through a zone's top), push (a bounce off a support's top), false break
    (close back inside after closing below). Stop just beyond the zone."""
    o, h, l, c = arrays(df)
    a = ctx.a
    zones = ctx.get(("bjz", id(df)), lambda: _bjorgum_zones(df))
    cd = ctx.get(("cd", id(df)), lambda: P.candles(df, a))
    rows = []
    for i in range(1, len(df)):
        if not zones[i] or not a[i] > 0:
            continue
        zb, zt, _ = min(zones[i], key=lambda z: abs(c[i] - (z[0] + z[1]) / 2))
        if min(abs(c[i] - zb), abs(c[i] - zt)) > 1.0 * a[i] and not (zb <= c[i] <= zt):
            continue
        if c[i - 1] <= zt < c[i] and cd["bull"].iat[i]:
            rows.append(long_(i, zb - BUF * a[i], tag="break"))
        elif c[i - 1] > zt and l[i] <= zt and c[i] > zt and cd["bull"].iat[i]:
            rows.append(long_(i, min(l[i], zb) - BUF * a[i], tag="push"))
        elif c[i - 1] < zb and zb <= c[i] <= zt:
            rows.append(long_(i, min(l[i], l[i - 1]) - BUF * a[i], tag="false_break"))
    return frame(rows)


@mirror
def level_reaction(ctx, df):
    """Sage's level reaction: a bullish candle (this bar or the last) at a support within 0.5 ATR,
    levels being bjorgum zone mids and the 200/50-day SMAs. Tagged by the sage grade: swept
    (pierced >= 0.1 ATR within 3 bars and closed back) and higher timeframes carrying a zone there."""
    o, h, l, c = arrays(df)
    a = ctx.a
    zones = ctx.get(("bjz", id(df)), lambda: _bjorgum_zones(df))
    cd = ctx.get(("cd", id(df)), lambda: P.candles(df, a))
    mas = []
    if "1d" in ctx.htf:
        d1, ix = ctx.htf["1d"]
        for n in (200, 50):
            m = P.sma(d1["close"].to_numpy(), n)
            mas.append(np.where(ix >= 0, m[np.clip(ix, 0, None)], np.nan))
    htz = {k: ctx.get(("bjz", id(d)), lambda d=d: _bjorgum_zones(d)) for k, (d, _) in ctx.htf.items()}
    hta = {k: P.atr(d, 30) for k, (d, _) in ctx.htf.items()}
    adx, pdi, mdi = ctx.get(("adx", id(df)), lambda: P.adx(df))
    rows, last = [], -5
    for i in range(3, len(df)):
        if not a[i] > 0 or i - last < 3:
            continue
        levels = [(z[0] + z[1]) / 2 for z in zones[i]] + [m[i] for m in mas if np.isfinite(m[i])]
        sup = [v for v in levels if v < c[i] and l[i] - v <= 0.5 * a[i]]
        if not sup or not (cd["bull"].iat[i] or cd["bull"].iat[i - 1]):
            continue
        lvl = max(sup)
        swept = (lvl - l[i - 2:i + 1].min()) >= 0.1 * a[i] and c[i] > lvl
        credit = 0
        for k, (d, ix) in ctx.htf.items():
            j = ix[i]
            if j >= 0 and any(abs((z[0] + z[1]) / 2 - lvl) <= 0.5 * np.nan_to_num(hta[k][j]) for z in htz[k][j]):
                credit += 1
        grade = "none" if credit < 1 and not (swept and not ctx.htf) else \
            ("B+" if not swept else {1: "A", 2: "A+"}.get(credit, "S" if credit >= 3 else "A"))
        counter = adx[i] >= 28 and mdi[i] > pdi[i]
        rows.append(long_(i, min(l[i], lvl) - BUF * a[i], tag=f"{grade}{'|counter' if counter else ''}"))
        last = i
    return frame(rows)


# ------------------------------------------------------------------------------------- reversion

@mirror
def zma(ctx, df):
    """Sage's zma: z over 50 bars against thresholds at the 85th/65th percentile of |z| (250 bars),
    with the demand/supply momentum read. Tagged A+ (strong, momentum turning), B+ (weak, turning),
    B (strong, neutral). The source geometry: stop one sigma beyond, target the mean (`src`)."""
    o, h, l, c = arrays(df)
    m, s = P.sma(c, 50), P.std(c, 50)
    z = (c - m) / np.where(s > 0, s, np.nan)
    az = pd.Series(np.abs(z))
    strong = az.rolling(250, min_periods=10).quantile(0.85).to_numpy()
    weak = az.rolling(250, min_periods=10).quantile(0.65).to_numpy()
    first = pd.Series(c).rolling(25).mean().shift(25).to_numpy()
    second = pd.Series(c).rolling(25).mean().to_numpy()
    slope = (second - first) / np.where(first != 0, first, np.nan) * 100
    thr = pd.Series(np.abs(slope)).rolling(200, min_periods=20).median().to_numpy()
    prev = np.r_[np.nan, slope[:-1]]
    rising_demand = (slope > thr) & (slope > prev)
    weak_supply = (slope < -thr) & ~(slope < prev)
    neutral = np.abs(slope) <= thr
    adx, pdi, mdi = ctx.get(("adx", id(df)), lambda: P.adx(df))
    rows, last = [], -10
    for i in range(300, len(df)):
        if not np.isfinite(z[i]) or i - last < 5 or (adx[i] >= 28 and mdi[i] > pdi[i]):
            continue
        turn = rising_demand[i] or weak_supply[i]
        tag = "A+" if z[i] < -strong[i] and turn else "B+" if z[i] < -weak[i] and turn else \
            "B" if z[i] < -strong[i] and neutral[i] else ""
        if not tag:
            continue
        r = long_(i, c[i] - s[i], tag=tag)
        r["target_px"] = m[i]
        rows.append(r)
        last = i
    return frame(rows)


@mirror
def anomaly(ctx, df):
    """A return beyond 5 robust sigmas of the previous 60, closing in the top third: follow it,
    stop under the bar's low."""
    o, h, l, c = arrays(df)
    a = ctx.a
    r = np.r_[0, np.diff(np.log(np.maximum(c, 1e-12)))]
    s = pd.Series(r)
    med = s.shift(1).rolling(60).median()
    mad = (s - med).abs().shift(1).rolling(60).median() * 1.4826
    z = ((s - med) / mad.replace(0, np.nan)).to_numpy()
    pos = (c - l) / np.maximum(h - l, 1e-12)
    k = np.flatnonzero((z >= 5) & (pos >= 0.65))
    return frame([long_(i, l[i] - BUF * a[i]) for i in k if a[i] > 0])


# --------------------------------------------------------------------------- patterns and levels

@mirror
def ma_reaction(ctx, df):
    """A bar whose low reaches the 200- or 50-day SMA (within 0.25 ATR) and closes above it with a
    bullish candle; stop under the bar."""
    o, h, l, c = arrays(df)
    a = ctx.a
    if ctx.interval == "1d":
        mas = [P.sma(c, 200), P.sma(c, 50)]
    elif "1d" in ctx.htf:
        d1, ix = ctx.htf["1d"]
        mas = [np.where(ix >= 0, P.sma(d1["close"].to_numpy(), n)[np.clip(ix, 0, None)], np.nan)
               for n in (200, 50)]
    else:
        return frame([])
    cd = ctx.get(("cd", id(df)), lambda: P.candles(df, a))
    rows, last = [], -10
    for i in range(len(df)):
        for m in mas:
            if np.isfinite(m[i]) and l[i] <= m[i] + 0.25 * a[i] and c[i] > m[i] and cd["bull"].iat[i] \
                    and i - last > 5:
                rows.append(long_(i, min(l[i], m[i]) - BUF * a[i]))
                last = i
    return frame(rows)


@mirror
def double_bottom(ctx, df):
    """Two known pivot lows within 0.25 ATR, at least 5 bars apart: the close above the neckline
    (the highest high between them), stop under the breakout bar."""
    o, h, l, c = arrays(df)
    a = ctx.a
    _, pl = _piv(ctx, df, k=2)
    rows, used = [], set()
    for i in range(len(df)):
        if len(pl[i]) < 2 or not a[i] > 0:
            continue
        (j1, v1), (j2, v2) = pl[i]
        if j2 - j1 < 5 or abs(v1 - v2) > 0.25 * a[i] or (j1, j2) in used:
            continue
        neck = h[j1:j2 + 1].max()
        if c[i] > neck and c[i - 1] <= neck:
            used.add((j1, j2))
            rows.append(long_(i, l[i] - BUF * a[i]))
    return frame(rows)


@mirror
def asc_triangle(ctx, df):
    """Two known pivot highs within 0.2 ATR (a flat top) over two rising pivot lows; the close above
    the top on 1.5x mean tick volume (mkt, stop under the bar), or a limit back at the top (retest,
    stop half an ATR under it)."""
    o, h, l, c = arrays(df)
    a = ctx.a
    ph, pl = _piv(ctx, df)
    v = P.tick_volume(df)
    vm = P.sma(v, 20)
    rows, used = [], set()
    for i in range(len(df)):
        if len(ph[i]) < 2 or len(pl[i]) < 2 or not a[i] > 0:
            continue
        (hi1, t1), (hi2, t2) = ph[i]
        (_, b1), (_, b2) = pl[i]
        top = max(t1, t2)
        if abs(t1 - t2) > 0.2 * a[i] or not b2 > b1 or (hi1, hi2) in used:
            continue
        if c[i] > top and c[i - 1] <= top:
            used.add((hi1, hi2))
            loud = not np.isfinite(vm[i]) or v[i] >= 1.5 * vm[i]
            rows.append(long_(i, l[i] - BUF * a[i], tag="mkt" if loud else "mkt_quiet"))
            rows.append(long_(i, top - 0.5 * a[i], entry=top, limit=1, expires=5, tag="retest"))
    return frame(rows)


@mirror
def pullback_confluence(ctx, df):
    """In an uptrend (EMA21 > EMA50), a pullback into the 0.5-0.618 retracement of the last known
    swing that is within half an ATR of the EMA21, confirmed by a bullish candle; stop under it."""
    o, h, l, c = arrays(df)
    a = ctx.a
    e21, e50 = P.ema(c, 21), P.ema(c, 50)
    ph, pl = _piv(ctx, df, k=1)
    cd = ctx.get(("cd", id(df)), lambda: P.candles(df, a))
    rows, last = [], -10
    for i in range(60, len(df)):
        if not (ph[i] and pl[i]) or e21[i] <= e50[i] or i - last < 5:
            continue
        (hj, hv), (lj, lv) = ph[i][-1], pl[i][-1]
        if lj >= hj or hv - lv < a[i]:
            continue
        f50, f618 = hv - 0.5 * (hv - lv), hv - 0.618 * (hv - lv)
        if f618 <= l[i] <= f50 and abs(l[i] - e21[i]) <= 0.5 * a[i] and cd["bull"].iat[i]:
            rows.append(long_(i, l[i] - BUF * a[i]))
            last = i
    return frame(rows)


def volume_day(ctx):
    """Daily tick-volume z >= 2 over 30 days: quiet (|change| < 1.5%, side = the change's sign) and
    momentum (|change| >= 3%, follow). Stop one ATR away; the change's sign decides the side."""
    if ctx.interval != "1d":
        return frame([])
    df = ctx.df
    o, h, l, c = arrays(df)
    a = ctx.a
    v = P.tick_volume(df)
    z = (v - pd.Series(v).shift(1).rolling(30).mean().to_numpy()) / pd.Series(v).shift(1).rolling(30).std().to_numpy()
    chg = np.r_[np.nan, c[1:] / c[:-1] - 1]
    rows = []
    for i in np.flatnonzero(z >= 2):
        if not np.isfinite(chg[i]) or not a[i] > 0 or chg[i] == 0:
            continue
        side = 1 if chg[i] > 0 else -1
        tag = "quiet" if abs(chg[i]) < 0.015 else "momentum" if abs(chg[i]) >= 0.03 else ""
        if tag:
            rows.append(dict(i=int(i), side=side, stop_px=c[i] - side * a[i], entry=np.nan, limit=0,
                             expires=1, tag=tag))
    return frame(rows)


# ------------------------------------------------------------------------------ the clock (ICT)

@mirror
def asia_sweep(ctx, df):
    """Judas swing / London killzone: the Asia range (20:00-00:00 New York) swept below during
    02:00-05:00 New York and closed back inside; stop under the sweep. Intraday only."""
    if ctx.sec > 3600:
        return frame([])
    o, h, l, c = arrays(df)
    a = ctx.a
    hr = P.ny_hour(df["ts"].to_numpy())
    day = (pd.to_datetime(df["ts"], unit="s", utc=True).dt.tz_convert("America/New_York")
           + pd.Timedelta(hours=4)).dt.date.to_numpy()  # an Asia session belongs to the next day
    rows, done = [], set()
    asia_lo = {}
    for i in range(len(df)):
        d = day[i]
        if hr[i] >= 20 or hr[i] < 0:
            asia_lo[d] = min(asia_lo.get(d, np.inf), l[i])
        elif 2 <= hr[i] < 5 and d in asia_lo and d not in done and a[i] > 0:
            lo = asia_lo[d]
            if l[i] < lo and c[i] > lo:
                rows.append(long_(i, l[i] - BUF * a[i]))
                done.add(d)
    return frame(rows)


@mirror
def silver_bullet(ctx, df):
    """ICT silver bullet: a bullish FVG formed inside 10:00-11:00 New York, traded with a limit at
    its top for the rest of the window plus an hour, stop under its bottom. 15m and finer."""
    if ctx.sec > 900:
        return frame([])
    o, h, l, c = arrays(df)
    a = ctx.a
    hr = P.ny_hour(df["ts"].to_numpy())
    rows = []
    for k in range(2, len(df)):
        if 10 <= hr[k] < 11 and l[k] > h[k - 2] and l[k] - h[k - 2] >= 0.1 * a[k] > 0:
            rows.append(long_(k, h[k - 2] - BUF * a[k], entry=l[k], limit=1,
                              expires=max(1, int(7200 / ctx.sec))))
    return frame(rows)


def btc_overnight(ctx):
    """Long BTC from 22:00 to 00:00 UTC (the overnight seasonality claim); time exit, wide stop."""
    if not ctx.sym.startswith("BTC") or ctx.sec > 3600:
        return frame([])
    ts = ctx.df["ts"].to_numpy()
    hr = pd.to_datetime(ts, unit="s", utc=True).hour.to_numpy()
    c, a = ctx.df["close"].to_numpy(), ctx.a
    k = np.flatnonzero((hr == 21) & (ts % 3600 == 3600 - ctx.sec))  # the bar closing at 22:00
    rows = [dict(i=int(i), side=1, stop_px=c[i] - 2 * a[i], entry=np.nan, limit=0, expires=1,
                 tag="time", hold=int(7200 / ctx.sec)) for i in k if a[i] > 0]
    return frame(rows)


# -------------------------------------------------------------------------------- cross-asset

def divergence(ctx):
    """Relative strength against BTC (crypto) with R^2 >= 0.3 over 30 bars: the 5-bar residual's z
    over 60 bars beyond 1.5 is followed (sage's sign). Stop 1.5 ATR."""
    lead = ctx.peers.get("BTCUSD")
    if lead is None or ctx.sym == "BTCUSD":
        return frame([])
    c, a = ctx.df["close"].to_numpy(), ctx.a
    rf, rl = np.r_[0, np.diff(np.log(c))], np.r_[0, np.diff(np.log(lead))]
    sf, sl = pd.Series(rf), pd.Series(rl)
    cov = sf.rolling(30).cov(sl)
    var = sl.rolling(30).var()
    beta = (cov / var).to_numpy()
    r2 = (sf.rolling(30).corr(sl) ** 2).to_numpy()
    resid = pd.Series(rf - beta * rl).rolling(5).sum()
    z = ((resid - resid.shift(1).rolling(60).mean()) / resid.shift(1).rolling(60).std()).to_numpy()
    rows, last = [], -10
    for i in range(100, len(c)):
        if r2[i] >= 0.3 and abs(z[i]) >= 1.5 and i - last >= 5 and a[i] > 0:
            side = 1 if z[i] > 0 else -1
            rows.append(dict(i=i, side=side, stop_px=c[i] - side * 1.5 * a[i], entry=np.nan,
                             limit=0, expires=1, tag=""))
            last = i
    return frame(rows)


USD = {"EURUSD": -1, "GBPUSD": -1, "AUDUSD": -1, "NZDUSD": -1, "USDJPY": 1, "USDCHF": 1, "USDCAD": 1}


def usd_confluence(ctx):
    """Sage's dollar confluence, oriented properly: >= 4 of the 7 majors at a level (a 10-bar swing
    or the 120-bar extreme, within 0.4 ATR) and >= 66% of them implying the same dollar move.
    Traded on this pair if it is one of them, with a one-ATR stop."""
    if ctx.sym not in USD or len(ctx.peers) < 6:
        return frame([])
    rows = []
    reads = {}
    for s, sgn in USD.items():
        cs = ctx.df["close"].to_numpy() if s == ctx.sym else ctx.peers.get(s)
        if cs is None:
            continue
        cs = pd.Series(cs)
        a = (cs.diff().abs().rolling(14).mean()).to_numpy()
        hi = cs.rolling(120).max().to_numpy()
        lo = cs.rolling(120).min().to_numpy()
        x = cs.to_numpy()
        at_hi = (hi - x) <= 0.4 * a
        at_lo = (x - lo) <= 0.4 * a
        # at a high the pair should fall: for EURUSD (sgn -1) that is the dollar rising
        usd = np.where(at_hi, -sgn, np.where(at_lo, sgn, 0))
        reads[s] = usd
    if len(reads) < 6:
        return frame([])
    M = np.vstack(list(reads.values()))
    ready = (M != 0).sum(axis=0)
    up, dn = (M > 0).sum(axis=0), (M < 0).sum(axis=0)
    c, a = ctx.df["close"].to_numpy(), ctx.a
    last = -10
    for i in range(130, len(c)):
        if ready[i] >= 4 and max(up[i], dn[i]) / ready[i] >= 0.66 and i - last >= 5 and a[i] > 0:
            usd_dir = 1 if up[i] > dn[i] else -1
            side = usd_dir * USD[ctx.sym]
            rows.append(dict(i=i, side=side, stop_px=c[i] - side * a[i], entry=np.nan, limit=0,
                             expires=1, tag=""))
            last = i
    return frame(rows)


# ------------------------------------------------------------------------------------- FOCuS

def _focus(ctx, df, up):
    th = 12.0 + 3.0 * np.log(3600.0 / ctx.sec)
    c = df["close"].to_numpy()
    r = np.r_[0, np.diff(c)]
    scale = pd.Series(r).abs().ewm(span=100).mean().shift(1).to_numpy() * np.sqrt(np.pi / 2)
    return P.focus_series(r, scale, max(th, 3.0), up)


@mirror
def focus_follow(ctx, df):
    """FOCuS on signed returns: an upward change in the mean is followed at market; stop under the
    lowest low since the change began."""
    o, h, l, c = arrays(df)
    a = ctx.a
    fired, at = ctx.get(("fu", id(df)), lambda: _focus(ctx, df, True))
    rows = [long_(i, l[max(at[i], 0):i + 1].min() - BUF * a[i]) for i in np.flatnonzero(fired)
            if a[i] > 0 and at[i] >= 0]
    return frame(rows)


@mirror
def focus_retest(ctx, df):
    """FOCuS zone: after an upward change, a resting limit back at the change's starting bar's
    high, stop under that bar's low (the zone), valid 50 bars."""
    o, h, l, c = arrays(df)
    a = ctx.a
    fired, at = ctx.get(("fu", id(df)), lambda: _focus(ctx, df, True))
    rows = []
    for i in np.flatnonzero(fired):
        k = at[i]
        if k < 0 or not a[i] > 0 or h[k] >= c[i]:
            continue
        rows.append(long_(i, l[k] - BUF * a[i], entry=h[k], limit=1, expires=50))
    return frame(rows)


@mirror
def focus_fade(ctx, df):
    """FOCuS faded: after a downward change, buy; stop under the low of the move."""
    o, h, l, c = arrays(df)
    a = ctx.a
    fired, at = ctx.get(("fd", id(df)), lambda: _focus(ctx, df, False))
    rows = [long_(i, l[max(at[i], 0):i + 1].min() - BUF * a[i]) for i in np.flatnonzero(fired)
            if a[i] > 0 and at[i] >= 0]
    return frame(rows)


@mirror
def focus_mtf(ctx, df):
    """FOCuS agreeing across timeframes: an upward change here while every higher timeframe loaded
    has fired upward within its last 3 bars. Stop as `focus_follow`."""
    if not ctx.htf:
        return frame([])
    o, h, l, c = arrays(df)
    a = ctx.a
    fired, at = ctx.get(("fu", id(df)), lambda: _focus(ctx, df, True))
    agree = np.ones(len(df), bool)
    for k, (d, ix) in ctx.htf.items():
        sec = {"15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}[k]
        sub = Ctx(ctx.sym, ctx.family, k, sec, d)
        f, _ = _focus(sub, d, True)
        recent = pd.Series(f.astype(float)).rolling(3, min_periods=1).max().to_numpy() > 0
        agree &= np.where(ix >= 0, recent[np.clip(ix, 0, None)], False)
    rows = [long_(i, l[max(at[i], 0):i + 1].min() - BUF * a[i]) for i in np.flatnonzero(fired & agree)
            if a[i] > 0 and at[i] >= 0]
    return frame(rows)


def focus_size(ctx):
    """FOCuS on absolute returns: when move size shifts up, follow the alarm bar's direction; stop
    beyond that bar's far end."""
    df = ctx.df
    o, h, l, c = arrays(df)
    a = ctx.a
    r = np.abs(np.r_[0, np.diff(c)])
    base = pd.Series(r).ewm(span=200).mean().shift(1).to_numpy()
    th = max(12.0 + 3.0 * np.log(3600.0 / ctx.sec), 3.0)
    fired, _ = P.focus_series(r - base, base, th, True)
    rows = []
    for i in np.flatnonzero(fired):
        if c[i] == o[i] or not a[i] > 0:
            continue
        side = 1 if c[i] > o[i] else -1
        stop = l[i] - BUF * a[i] if side > 0 else h[i] + BUF * a[i]
        rows.append(dict(i=int(i), side=side, stop_px=stop, entry=np.nan, limit=0, expires=1, tag=""))
    return frame(rows)


SETUPS = {f.__name__: f for f in (
    bos_fvg, choch, sweep_equal_lows, order_block, cisd, turtle_soup, crt_raid, ote, ame_sweep,
    impulse_zone, bjorgum, level_reaction, zma, anomaly, ma_reaction, double_bottom, asc_triangle,
    pullback_confluence, volume_day, asia_sweep, silver_bullet, btc_overnight, divergence,
    usd_confluence, focus_follow, focus_retest, focus_fade, focus_mtf, focus_size,
)}


# ================================================================ batch 2: the api and lab ideas

def _sided(i, side, stop_px, entry=np.nan, limit=0, expires=1, tag="", hold=None):
    r = dict(i=int(i), side=int(side), stop_px=float(stop_px), entry=float(entry), limit=int(limit),
             expires=int(expires), tag=tag)
    if hold is not None:
        r["hold"] = int(hold)
    return r


@mirror
def ame_raid(ctx, df):
    """The api's AME sweep patterns at the 20-bar equal-low pool (lows within 0.2% of price):
    single bar (low through, close back above) and judas (two bars below, then a close above the
    previous high). Traded both ways: `smc` buys the reclaim (stop under the raid), `inverted`
    sells it - the direction AME actually shipped (stop above the bar)."""
    o, h, l, c = arrays(df)
    a = ctx.a
    rows, last = [], -5
    for i in range(22, len(df)):
        if i - last < 3 or not a[i] > 0:
            continue
        w = l[i - 20:i]
        lo = w.min()
        eq = w[w <= lo * 1.002]
        if len(eq) < 2:
            continue
        pool = eq.mean()
        single = l[i] < pool < c[i]
        judas = l[i - 1] < pool and c[i - 1] < pool and c[i] > h[i - 1]
        if single or judas:
            tag = "single" if single else "judas"
            rows.append(long_(i, l[i] - BUF * a[i], tag=f"smc|{tag}"))
            rows.append(dict(i=i, side=-1, stop_px=h[i] + BUF * a[i], entry=np.nan, limit=0, expires=1,
                             tag=f"inverted|{tag}"))
            last = i
    return frame(rows)


@mirror
def cisd_live(ctx, df):
    """The api's live CISD: >= 2 bearish bars, then a bullish flip bar with body >= 40% of its range
    closing above the high two bars back; stop under the run's low."""
    o, h, l, c = arrays(df)
    a = ctx.a
    rows = []
    for i in range(4, len(df)):
        rng = h[i] - l[i]
        if not (c[i] > o[i] and rng > 0 and (c[i] - o[i]) / rng >= 0.4 and c[i] > h[i - 2]) or not a[i] > 0:
            continue
        j = i - 1
        while j >= max(0, i - 10) and c[j] < o[j]:
            j -= 1
        if i - 1 - j >= 2:
            rows.append(long_(i, l[j + 1:i + 1].min() - BUF * a[i]))
    return frame(rows)


@mirror
def triangle_cook(ctx, df):
    """Breakouts' 'cooking' triangle: over 60 bars, >= 3 local highs falling and >= 3 lows rising
    (+-3 bar extrema, known 3 bars later); price within half an ATR of the upper line with the apex
    <= 10 bars away. A buy stop on the upper line, stop on the lower line."""
    o, h, l, c = arrays(df)
    a = ctx.a
    ph, pl = _piv(ctx, df, 3, 3, k=6)
    rows, last = [], -20
    for i in range(60, len(df)):
        if i - last < 10 or not a[i] > 0:
            continue
        hs = [(j, v) for j, v in ph[i] if i - j <= 60][-3:]
        ls = [(j, v) for j, v in pl[i] if i - j <= 60][-3:]
        if len(hs) < 3 or len(ls) < 3:
            continue
        bh, ah = np.polyfit([j for j, _ in hs], [v for _, v in hs], 1)
        bl, al_ = np.polyfit([j for j, _ in ls], [v for _, v in ls], 1)
        if not (bh < 0 < bl):
            continue
        up, dn = bh * i + ah, bl * i + al_
        if up - dn < 0.5 * a[i] or up - c[i] > 0.5 * a[i] or c[i] > up:
            continue
        apex = (ah - al_) / (bl - bh) - i
        if 0 < apex <= 10:
            rows.append(long_(i, dn - BUF * a[i], entry=up, limit=0, expires=10))
            last = i
    out = frame(rows)
    if not out.empty:
        out["limit"] = 0  # a buy *stop* at the line: mt5bt's resting stop order
    return out


@mirror
def proximity_limit(ctx, df):
    """The api's proximity peer as a trade: a resting buy limit at the nearest bjorgum support
    within half an ATR below, stop half an ATR beyond it, valid 10 bars."""
    o, h, l, c = arrays(df)
    a = ctx.a
    zones = ctx.get(("bjz", id(df)), lambda: _bjorgum_zones(df))
    rows, last = [], -10
    for i in range(len(df)):
        if not zones[i] or not a[i] > 0 or i - last < 10:
            continue
        sup = [z for z in zones[i] if z[1] < c[i] and c[i] - z[1] <= 0.5 * a[i]]
        if sup:
            zb, zt, _ = max(sup, key=lambda z: z[1])
            rows.append(long_(i, zt - 0.5 * a[i], entry=zt, limit=1, expires=10))
            last = i
    return frame(rows)


@mirror
def cusum_follow(ctx, df):
    """The api's CUSUM: drift k = 0.5 sigma, line h = 5 sigma, sigma from the 60 returns before the
    last 30; the first bar the up-sum crosses is followed, stop two ATR."""
    o, h, l, c = arrays(df)
    a = ctx.a
    r = np.r_[0, np.diff(np.log(np.maximum(c, 1e-12)))]
    sig = pd.Series(r).shift(30).rolling(60).std().to_numpy()
    rows, s_up, armed = [], 0.0, True
    for i in range(100, len(df)):
        if not np.isfinite(sig[i]) or sig[i] <= 0:
            continue
        s_up = max(0.0, s_up + r[i] - 0.5 * sig[i])
        if s_up > 5 * sig[i]:
            if armed and a[i] > 0:
                rows.append(long_(i, c[i] - 2 * a[i]))
            armed, s_up = False, 0.0
        elif s_up == 0.0:
            armed = True
    return frame(rows)


def rug_short(ctx):
    """Blow-off top: up 50% from the 60-bar low (5% on non-crypto), the last 10 bars at twice the
    earlier pace, within 5% of the high, then a rejection bar closing in its lower 40% on a volume
    jump. Short, stop over the bar."""
    df = ctx.df
    o, h, l, c = arrays(df)
    a = ctx.a
    v = P.tick_volume(df)
    need = 0.5 if ctx.family == "crypto" else 0.05
    rows, last = [], -20
    for i in range(65, len(df)):
        lo60, hi60 = l[i - 59:i + 1].min(), h[i - 59:i + 1].max()
        recent, base = c[i] / c[i - 10] - 1, c[i - 10] / c[i - 59] - 1
        accel = (recent / 10) / (base / 50) if base > 0 else (np.inf if recent > 0.01 else 0)
        vb = v[i - 59:i - 9]
        vz = (v[i - 9:i + 1].mean() - vb.mean()) / (vb.std() or np.inf)
        pos = (c[i] - l[i]) / max(h[i] - l[i], 1e-12)
        if (c[i] / lo60 - 1 >= need and accel >= 2 and recent > 0 and c[i] >= 0.95 * hi60
                and pos <= 0.4 and vz >= 1.5 and i - last > 10 and a[i] > 0):
            rows.append(_sided(i, -1, h[i] + BUF * a[i]))
            last = i
    return frame(rows)


@mirror
def vwap_band_fade(ctx, df):
    """Fade the 50-bar tick-volume VWAP's lower 1.5-sigma band: a close back above it after closing
    below; stop under the low of the excursion."""
    o, h, l, c = arrays(df)
    a = ctx.a
    v = np.nan_to_num(P.tick_volume(df), nan=1.0) + 1e-9
    tp = (h + l + c) / 3
    vw = pd.Series(tp * v).rolling(50).sum().to_numpy() / pd.Series(v).rolling(50).sum().to_numpy()
    var = pd.Series((tp - vw) ** 2 * v).rolling(50).sum().to_numpy() / pd.Series(v).rolling(50).sum().to_numpy()
    band = vw - 1.5 * np.sqrt(np.maximum(var, 0))
    k = np.flatnonzero((c[1:] > band[1:]) & (c[:-1] < band[:-1])) + 1
    return frame([long_(i, l[max(0, i - 3):i + 1].min() - BUF * a[i]) for i in k if a[i] > 0])


@mirror
def absorption(ctx, df):
    """Absorption at a low: a new 19-bar low on a bullish bar whose lower wick is >= half its range,
    on a wick-delta z >= 1.5 (tick volume x wick imbalance against the last 19). Stop under the wick."""
    o, h, l, c = arrays(df)
    a = ctx.a
    v = np.nan_to_num(P.tick_volume(df), nan=1.0)
    rng = np.maximum(h - l, 1e-12)
    uw, lw = h - np.maximum(o, c), np.minimum(o, c) - l
    wd = (lw - uw) / rng * v
    s = pd.Series(wd)
    z = ((s - s.shift(1).rolling(19).mean()) / s.shift(1).rolling(19).std()).to_numpy()
    newlow = l <= pd.Series(l).rolling(19).min().to_numpy()
    k = np.flatnonzero((z >= 1.5) & (c > o) & newlow & (lw >= 0.5 * rng))
    return frame([long_(i, l[i] - BUF * a[i]) for i in k if a[i] > 0])


@mirror
def cvd_divergence(ctx, df):
    """Bar-delta divergence: price below where it was 25 bars ago while the 24-bar sum of
    tick-volume delta (v x (2c - h - l)/(h - l)) is positive; the first such bar, stop 1.5 ATR."""
    o, h, l, c = arrays(df)
    a = ctx.a
    v = np.nan_to_num(P.tick_volume(df), nan=1.0)
    d = v * (2 * c - h - l) / np.maximum(h - l, 1e-12)
    ds = pd.Series(d).rolling(24).sum().to_numpy()
    cond = (c < np.r_[np.full(25, np.nan), c[:-25]]) & (ds > 0)
    k = np.flatnonzero(cond & ~np.r_[False, cond[:-1]])
    return frame([long_(i, c[i] - 1.5 * a[i]) for i in k if a[i] > 0])


PUMP = {"fx": {"15m": .004, "1h": .0025, "4h": .005, "1d": .02}, "metal": {"15m": .004, "1h": .0025, "4h": .005, "1d": .02},
        "index": {"15m": .005, "1h": .01, "4h": .012, "1d": .015}, "energy": {"15m": .005, "1h": .01, "4h": .012, "1d": .015},
        "deriv": {"15m": .02, "1h": .03, "4h": .03, "1d": .03}, "crypto": {"15m": .03, "1h": .03, "4h": .03, "1d": .03}}


@mirror
def pump_follow(ctx, df):
    """The bar pump scanner: a 9-bar close change past the class threshold is followed; stop at the
    9-bar opposite extreme, held 3 bars."""
    o, h, l, c = arrays(df)
    a = ctx.a
    th = PUMP.get(ctx.family, PUMP["crypto"]).get(ctx.interval, 0.03)
    chg = np.r_[np.full(9, np.nan), c[9:] / c[:-9] - 1]
    cond = chg >= th
    k = np.flatnonzero(cond & ~np.r_[False, cond[:-1]])
    return frame([_sided(i, 1, l[i - 9:i + 1].min() - BUF * a[i], hold=3) for i in k if a[i] > 0 and i >= 9])


@mirror
def fisher_extreme(ctx, df):
    """Fisher transform (10, unsmoothed) at or below -1.5: buy the reversion, held 6 bars, stop under
    the 10-bar low. Tagged by session (UTC 7-12 and 16-23, the proposed gate)."""
    o, h, l, c = arrays(df)
    a = ctx.a
    hh = pd.Series(h).rolling(10).max().to_numpy()
    ll = pd.Series(l).rolling(10).min().to_numpy()
    x = np.clip(2 * (c - ll) / np.maximum(hh - ll, 1e-12) - 1, -0.999, 0.999)
    f = 0.5 * np.log((1 + x) / (1 - x))
    hr = pd.to_datetime(df["ts"].to_numpy(), unit="s", utc=True).hour.to_numpy()
    cond = f <= -1.5
    k = np.flatnonzero(cond & ~np.r_[False, cond[:-1]])
    return frame([_sided(i, 1, ll[i] - BUF * a[i], hold=6,
                         tag="gate" if (7 <= hr[i] <= 12 or 16 <= hr[i] <= 23) else "off")
                  for i in k if a[i] > 0])


@mirror
def tf_coherent_breakout(ctx, df):
    """A close above the 20-bar high, tagged coherent when the next timeframe's EMA20 (closed bars)
    slopes up, discoherent when not; stop under the breakout bar."""
    o, h, l, c = arrays(df)
    a = ctx.a
    up = UP_OF.get(ctx.interval)
    if up not in ctx.htf:
        return frame([])
    d, ix = ctx.htf[up]
    e = P.ema(d["close"].to_numpy(), 20)
    slope = np.r_[0, np.diff(e)]
    hs = np.where(ix >= 0, slope[np.clip(ix, 0, None)], 0)
    prior = pd.Series(h).shift(1).rolling(20).max().to_numpy()
    cond = c > prior
    k = np.flatnonzero(cond & ~np.r_[False, cond[:-1]])
    return frame([long_(i, l[i] - BUF * a[i], tag="coherent" if hs[i] > 0 else "discoherent")
                  for i in k if a[i] > 0])


UP_OF = {"15m": "1h", "1h": "4h", "4h": "1d"}


@mirror
def candle_fade(ctx, df):
    """The lab's finding that textbook candles work backwards: a bullish pattern (hammer, engulfing,
    piercing, tweezer) is sold, held 3 bars, stop above the pattern's high."""
    o, h, l, c = arrays(df)
    a = ctx.a
    cd = ctx.get(("cd", id(df)), lambda: P.candles(df, a))
    k = np.flatnonzero(cd["bull"].to_numpy())
    return frame([_sided(i, -1, h[i] + BUF * a[i], hold=3) for i in k if a[i] > 0])


@mirror
def three_bar_continuation(ctx, df):
    """A 3-bar rise of more than 2 ATR continues (FX claim): buy, held 3 bars, stop under bar 3's low."""
    o, h, l, c = arrays(df)
    a = ctx.a
    mv = np.r_[np.full(3, np.nan), c[3:] - c[:-3]]
    cond = mv > 2 * a
    k = np.flatnonzero(cond & ~np.r_[False, cond[:-1]])
    return frame([_sided(i, 1, l[i] - BUF * a[i], hold=3) for i in k if a[i] > 0])


@mirror
def sweep_fade_hivol(ctx, df):
    """A wick under the prior 24-bar low that closes back inside, when 12-bar realised vol is above
    its 500-bar 66th percentile: buy. `src` geometry is the lab's (stop 2.5 ATR, target 4 ATR, 24
    bars); the trader's stop sits under the wick."""
    o, h, l, c = arrays(df)
    a = ctx.a
    r = np.r_[0, np.diff(np.log(np.maximum(c, 1e-12)))]
    rv = pd.Series(r).rolling(12).std()
    gate = (rv > rv.rolling(500, min_periods=100).quantile(0.66)).to_numpy()
    prior = pd.Series(l).shift(1).rolling(24).min().to_numpy()
    k = np.flatnonzero((l < prior) & (c > prior) & gate)
    rows = []
    for i in k:
        if a[i] > 0:
            rows.append(long_(i, l[i] - BUF * a[i], tag="trader"))
            r_ = _sided(i, 1, c[i] - 2.5 * a[i], tag="lab", hold=24)
            r_["target_px"] = c[i] + 4 * a[i]
            rows.append(r_)
    return frame(rows)


def fatigue(ctx):
    """The lab's liquidity fatigue: touches of the 50-bar high and low, decayed 0.95 a bar. SweepPred:
    buy when the low side's fatigue is above its 500-bar 80th percentile (sell for the high side);
    FadeSweep: buy a low-side touch while that fatigue was already high. Held 6 bars, stop 1.5 ATR."""
    df = ctx.df
    o, h, l, c = arrays(df)
    a = ctx.a
    bsl = pd.Series(h).shift(1).rolling(50).max().to_numpy()
    ssl = pd.Series(l).shift(1).rolling(50).min().to_numpy()
    tb, ts_ = (h >= bsl).astype(float), (l <= ssl).astype(float)
    fb, fs = np.zeros(len(df)), np.zeros(len(df))
    for i in range(1, len(df)):
        fb[i], fs[i] = 0.95 * fb[i - 1] + tb[i], 0.95 * fs[i - 1] + ts_[i]
    qb = pd.Series(fb).rolling(500, min_periods=100).quantile(0.8).to_numpy()
    qs = pd.Series(fs).rolling(500, min_periods=100).quantile(0.8).to_numpy()
    rows, last = [], -6
    for i in range(100, len(df)):
        if not a[i] > 0 or i - last < 6:
            continue
        if fs[i] >= qs[i]:
            rows.append(_sided(i, 1, c[i] - 1.5 * a[i], hold=6, tag="sweep_pred"))
            last = i
        elif fb[i] >= qb[i]:
            rows.append(_sided(i, -1, c[i] + 1.5 * a[i], hold=6, tag="sweep_pred"))
            last = i
        if ts_[i] and fs[i - 1] >= qs[i - 1]:
            rows.append(_sided(i, 1, l[i] - BUF * a[i], hold=6, tag="fade_sweep"))
        if tb[i] and fb[i - 1] >= qb[i - 1]:
            rows.append(_sided(i, -1, h[i] + BUF * a[i], hold=6, tag="fade_sweep"))
    return frame(rows)


def _slope(c, k):
    x = np.arange(k) - (k - 1) / 2
    return pd.Series(c).rolling(k).apply(lambda y: float(np.dot(x, y) / np.dot(x, x)), raw=True).to_numpy()


def physics(ctx):
    """The lab's 'verified' per-instrument signals, computed every 6 bars on the last 100, held 6 bars,
    stop 1.5 ATR. Hurst (> .55 follow the 20-bar slope, < .45 fade it), permutation entropy (order 4,
    normalised < .92: follow the 10-bar slope), and two the lab computed with lookahead, rebuilt
    causally: MaxwellCurl (sign change of SMA5 - SMA20 of the bar's order-flow proxy's change, follow
    the new sign) and Omori (aftershock decay of the last 48 bars, fade fast decay, follow slow)."""
    df = ctx.df
    o, h, l, c = arrays(df)
    a = ctx.a
    s20, s10 = _slope(c, 20), _slope(c, 10)
    r = np.r_[0, np.diff(np.log(np.maximum(c, 1e-12)))]
    ofi = 2 * (c - l) / np.maximum(h - l, 1e-12) - 1
    B = np.r_[0, np.diff(ofi)]
    curl = P.sma(B, 5) - P.sma(B, 20)
    rows = []
    for i in range(120, len(df), 6):
        if not a[i] > 0:
            continue
        w = r[i - 99:i + 1]
        # Hurst by rescaled range over 4 block sizes
        hs = []
        for n in (8, 16, 32, 64):
            m = len(w) // n
            blocks = w[:m * n].reshape(m, n)
            dev = np.cumsum(blocks - blocks.mean(axis=1, keepdims=True), axis=1)
            rs = (dev.max(axis=1) - dev.min(axis=1)) / np.maximum(blocks.std(axis=1), 1e-12)
            hs.append(np.log(rs.mean()))
        H = np.polyfit(np.log([8, 16, 32, 64]), hs, 1)[0]
        if H > 0.55 and s20[i]:
            rows.append(_sided(i, np.sign(s20[i]), c[i] - np.sign(s20[i]) * 1.5 * a[i], hold=6, tag="hurst"))
        elif H < 0.45 and s20[i]:
            rows.append(_sided(i, -np.sign(s20[i]), c[i] + np.sign(s20[i]) * 1.5 * a[i], hold=6, tag="hurst"))
        # permutation entropy, order 4
        pats = np.argsort(np.lib.stride_tricks.sliding_window_view(c[i - 99:i + 1], 4), axis=1)
        _, cnt = np.unique(pats @ np.array([1, 4, 16, 64]), return_counts=True)
        p_ = cnt / cnt.sum()
        pe = -(p_ * np.log(p_)).sum() / np.log(24)
        if pe < 0.92 and s10[i]:
            rows.append(_sided(i, np.sign(s10[i]), c[i] - np.sign(s10[i]) * 1.5 * a[i], hold=6, tag="permen"))
        # MaxwellCurl, causal: a sign change of curl within the last 24 bars, as of bar i
        seg = np.sign(curl[i - 24:i + 1])
        if np.isfinite(seg).all() and (np.diff(seg) != 0).any() and seg[-1] != 0:
            rows.append(_sided(i, seg[-1], c[i] - seg[-1] * 1.5 * a[i], hold=6, tag="maxwell"))
        # Omori, causal: the mainshock's aftershocks only up to bar i
        ab = np.abs(r[:i + 1])
        thr95 = np.quantile(ab[max(0, i - 500):], 0.95)
        thr80 = np.quantile(ab[max(0, i - 500):], 0.80)
        mains = [j for j in range(i - 47, i - 5) if ab[j] > thr95]
        if mains and s10[i]:
            j = mains[-1]
            after = ab[j + 1:i + 1] > thr80
            t = np.arange(1, len(after) + 1)
            cum = np.cumsum(after)
            ok = cum > 0
            if ok.sum() >= 3:
                p = -np.polyfit(np.log(t[ok]), np.log(cum[ok] / t[ok]), 1)[0]
                side = -np.sign(s10[i]) if p > 0.5 else np.sign(s10[i])
                rows.append(_sided(i, side, c[i] - side * 1.5 * a[i], hold=6, tag="omori"))
    return frame(rows)


def ts_momentum(ctx):
    """The lab's daily time-series momentum: the signs of the 7/14/30/60-day returns; long when 3 of
    4 are up (short when 3 are down), out when that flips; shorts also out on a close above the
    10-bar swing high. Daily only, stop 3 ATR."""
    if ctx.interval != "1d":
        return frame([])
    df = ctx.df
    o, h, l, c = arrays(df)
    a = ctx.a
    votes = sum(np.sign(c - np.r_[np.full(k, np.nan), c[:-k]]) for k in (7, 14, 30, 60))
    state = np.where(votes >= 2, 1, np.where(votes <= -2, -1, 0))
    rows, i = [], 61
    hi10 = pd.Series(h).shift(1).rolling(10).max().to_numpy()
    while i < len(df):
        s = state[i]
        if s != 0 and state[i - 1] != s and a[i] > 0:
            j = i + 1
            while j < len(df) and state[j] == s and not (s < 0 and c[j] > hi10[j]):
                j += 1
            rows.append(_sided(i, s, c[i] - s * 3 * a[i], hold=max(1, j - i), tag="long" if s > 0 else "short"))
            i = j
        else:
            i += 1
    return frame(rows)


@mirror
def donchian_trend(ctx, df):
    """A close above the 20-bar high while EMA50 > EMA200: buy, stop under the breakout bar."""
    o, h, l, c = arrays(df)
    a = ctx.a
    e50, e200 = P.ema(c, 50), P.ema(c, 200)
    prior = pd.Series(h).shift(1).rolling(20).max().to_numpy()
    cond = (c > prior) & (e50 > e200)
    k = np.flatnonzero(cond & ~np.r_[False, cond[:-1]])
    return frame([long_(i, l[i] - BUF * a[i]) for i in k if a[i] > 0 and i > 200])


SETUPS.update({f.__name__: f for f in (
    ame_raid, cisd_live, triangle_cook, proximity_limit, cusum_follow, rug_short, vwap_band_fade,
    absorption, cvd_divergence, pump_follow, fisher_extreme, tf_coherent_breakout, candle_fade,
    three_bar_continuation, sweep_fade_hivol, fatigue, physics, ts_momentum, donchian_trend,
)})


# ================================================================ batch 3: the lab scripts' ideas

def _exit_when(cond_exit: np.ndarray, i: int, cap: int = 300) -> int:
    """Bars from i to the first later bar where the exit condition holds."""
    j = np.flatnonzero(cond_exit[i + 1:i + 1 + cap])
    return int(j[0] + 1) if len(j) else cap


@mirror
def bb_sr_reversion(ctx, df):
    """The lab's FX/index 'one survivor': Bollinger z < -2 (exit when z crosses 0), range position in
    50 bars < 0.1 (exit at 0.5), and both together (conflu). Stop 3 ATR as a disaster stop only."""
    o, h, l, c = arrays(df)
    a = ctx.a
    z = (c - P.sma(c, 20)) / np.maximum(P.std(c, 20), 1e-12)
    lo = pd.Series(l).rolling(50).min().to_numpy()
    hi = pd.Series(h).rolling(50).max().to_numpy()
    pir = (c - lo) / np.maximum(hi - lo, 1e-12)
    rows = []
    for name, cond, done in (("bb", z < -2, z >= 0), ("sr", pir < 0.1, pir >= 0.5),
                             ("conflu", (z < -2) & (pir < 0.2), z >= 0)):
        k = np.flatnonzero(cond & ~np.r_[False, cond[:-1]])
        rows += [_sided(i, 1, c[i] - 3 * a[i], hold=_exit_when(done, i), tag=name) for i in k if a[i] > 0]
    return frame(rows)


@mirror
def htf_pullback(ctx, df):
    """The lab's range cycle: the higher timeframe up (close above its close 20 bars back) and this
    timeframe low in its 20-bar range (< 0.34): buy, out when the position leaves the lower third or
    the higher timeframe turns. Stop 2 ATR."""
    up = UP_OF.get(ctx.interval)
    if up not in ctx.htf:
        return frame([])
    o, h, l, c = arrays(df)
    a = ctx.a
    d, ix = ctx.htf[up]
    dc = d["close"].to_numpy()
    hdir = np.sign(dc - np.r_[np.full(20, np.nan), dc[:-20]])
    hd = np.where(ix >= 0, hdir[np.clip(ix, 0, None)], 0)
    lo = pd.Series(l).rolling(20).min().to_numpy()
    hi = pd.Series(h).rolling(20).max().to_numpy()
    pos = (c - lo) / np.maximum(hi - lo, 1e-12)
    cond = (hd > 0) & (pos < 0.34)
    k = np.flatnonzero(cond & ~np.r_[False, cond[:-1]])
    return frame([_sided(i, 1, c[i] - 2 * a[i], hold=_exit_when(~cond, i)) for i in k if a[i] > 0])


@mirror
def range_traverse(ctx, df):
    """Sweep one side of a 20-bar range no wider than 6 ATR, close back inside: buy at the close,
    stop under the wick by 0.15 of the bar's range, target the range's other edge (`src`)."""
    o, h, l, c = arrays(df)
    a = ctx.a
    lo = pd.Series(l).shift(1).rolling(20).min().to_numpy()
    hi = pd.Series(h).shift(1).rolling(20).max().to_numpy()
    rows = []
    for i in np.flatnonzero((l < lo) & (c > lo)):
        if a[i] > 0 and hi[i] - lo[i] <= 6 * a[i]:
            r = _sided(i, 1, l[i] - 0.15 * (h[i] - l[i]), hold=120)
            r["target_px"] = hi[i]
            rows.append(r)
    return frame(rows)


@mirror
def box_breakout(ctx, df):
    """The lab's Donchian box: the first close above the prior 20-bar box, entered at that close (not
    at the box edge, which the original assumed), stop one box width below, target two (`src`);
    tagged compressed when ATR is in its 200-bar lowest 30%."""
    o, h, l, c = arrays(df)
    a = ctx.a
    hi = pd.Series(h).shift(1).rolling(20).max().to_numpy()
    lo = pd.Series(l).shift(1).rolling(20).min().to_numpy()
    q30 = pd.Series(a).rolling(200, min_periods=100).quantile(0.3).to_numpy()
    cond = c > hi
    k = np.flatnonzero(cond & ~np.r_[False, cond[:-1]])
    rows = []
    for i in k:
        w = hi[i] - lo[i]
        if a[i] > 0 and w > 0:
            r = _sided(i, 1, c[i] - w, hold=96, tag="compressed" if a[i] <= q30[i] else "open")
            r["target_px"] = c[i] + 2 * w
            rows.append(r)
    return frame(rows)


SETUPS.update({f.__name__: f for f in (bb_sr_reversion, htf_pullback, range_traverse, box_breakout)})


# ================================================================ batch 4: cross-pollination
# Combinations of the pieces that survived alone. Exploratory: their parts were chosen on the
# same data, so a combination that "works" here still needs instruments and time it has not seen.

def _ens(c: np.ndarray) -> np.ndarray:
    """The time-series momentum ensemble: the mean sign of the 7/14/30/60-bar returns."""
    return sum(np.sign(c - np.r_[np.full(k, np.nan), c[:-k]]) for k in (7, 14, 30, 60)) / 4


def _gate(sig: pd.DataFrame, ok_long: np.ndarray, ok_short: np.ndarray) -> pd.DataFrame:
    if sig.empty:
        return sig
    i, s = sig["i"].to_numpy(int), sig["side"].to_numpy(int)
    keep = np.where(s > 0, ok_long[i], ok_short[i])
    return sig[keep].reset_index(drop=True)


def cusum_x_trend(ctx):
    """CUSUM ignition, taken only with the momentum ensemble on its side (>= 0.5)."""
    e = _ens(ctx.df["close"].to_numpy())
    return _gate(cusum_follow(ctx), e >= 0.5, e <= -0.5)


def anomaly_x_trend(ctx):
    """A 5-sigma bar followed, only with the momentum ensemble on its side."""
    e = _ens(ctx.df["close"].to_numpy())
    return _gate(anomaly(ctx), e >= 0.5, e <= -0.5)


def _near(sig: pd.DataFrame, other: pd.DataFrame, n: int, bars: int = 3) -> pd.DataFrame:
    """Keep the signals that `other` confirmed on the same side within the last `bars` bars."""
    if sig.empty or other.empty:
        return sig.iloc[0:0]
    marks = {1: np.zeros(n, bool), -1: np.zeros(n, bool)}
    for i, s in zip(other["i"].to_numpy(int), other["side"].to_numpy(int)):
        marks[int(s)][i:min(n, i + bars + 1)] = True
    keep = [marks[int(s)][i] for i, s in zip(sig["i"].to_numpy(int), sig["side"].to_numpy(int))]
    return sig[np.array(keep, bool)].reset_index(drop=True)


def cusum_x_anomaly(ctx):
    """CUSUM ignition confirmed by a 5-sigma bar on the same side within 3 bars."""
    return _near(cusum_follow(ctx), anomaly(ctx), len(ctx.df))


def breakout_x_cusum(ctx):
    """A Donchian or box breakout confirmed by CUSUM on the same side within 3 bars."""
    b = pd.concat([donchian_trend(ctx), box_breakout(ctx)], ignore_index=True)
    if "target_px" in b:
        b = b.drop(columns=["target_px"])
    return _near(b, cusum_follow(ctx), len(ctx.df))


SETUPS.update({f.__name__: f for f in (cusum_x_trend, anomaly_x_trend, cusum_x_anomaly, breakout_x_cusum)})
