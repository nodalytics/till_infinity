"""The indicators behind the geraked Expert Advisors, ported from MQL5 to numpy.

Source: github.com/geraked/metatrader5 (MIT licence, Copyright 2023-2024 Geraked / Rabist). The
custom indicators (`Indicators/*.mq5`) and the MetaTrader built-ins the EAs call (iMA, iRSI, iBands,
iStochastic, iMACD, iMomentum, iATR, iFractals, the Heiken Ashi example) are re-expressed here, one
function each. Arrays run oldest to newest; the value at index t uses bars up to and including t,
which is what MQL5 holds for a closed bar (the EAs read buffer 1 = the last closed bar on the first
tick of a new one). Where MetaTrader's own warm-up differs from a textbook formula (EMA seeded with
the first price, RSI seeded with a simple mean, ATR as a simple mean of true range) the MQL5 rule is
kept. Hand-checked values are in `test_geraked.py`.
"""
from __future__ import annotations

import numpy as np

EMPTY = np.nan  # MQL5's EMPTY_VALUE / an uncomputed bar


def _win(x, n):
    """Rolling windows ending at each bar (rows for t >= n-1)."""
    return np.lib.stride_tricks.sliding_window_view(np.asarray(x, float), n)


def rmax(x, n):
    out = np.full(len(x), np.nan)
    if len(x) >= n:
        out[n - 1:] = _win(x, n).max(1)
    return out


def rmin(x, n):
    out = np.full(len(x), np.nan)
    if len(x) >= n:
        out[n - 1:] = _win(x, n).min(1)
    return out


def sma(x, n):
    x = np.asarray(x, float)
    out = np.full(len(x), np.nan)
    if len(x) >= n:
        bad = ~np.isfinite(x)
        c = np.cumsum(np.r_[0.0, np.where(bad, 0.0, x)])
        k = np.cumsum(np.r_[0, bad.astype(int)])
        out[n - 1:] = np.where(k[n:] - k[:-n] > 0, np.nan, (c[n:] - c[:-n]) / n)
    return out


def ema(x, n):
    """MetaTrader's EMA: seeded with the first price, smoothing 2/(n+1)."""
    x = np.asarray(x, float)
    a = 2.0 / (n + 1)
    out = np.empty(len(x))
    if not len(x):
        return out
    out[0] = x[0]
    for i in range(1, len(x)):  # a plain recursion; lfilter would do, scipy is not needed for 1e5 bars
        out[i] = x[i] * a + out[i - 1] * (1 - a)
    return out


def wma(x, n):
    """Linear weights, newest = n (MQL5's LRMA numerator)."""
    x = np.asarray(x, float)
    out = np.full(len(x), np.nan)
    if len(x) >= n:
        w = np.arange(1, n + 1, dtype=float)
        out[n - 1:] = _win(x, n) @ w / w.sum()
    return out


def lrma(x, n):
    """End point of the least-squares line over n bars: 3 WMA - 2 SMA (LinearRegressionCandles, ZLSMA)."""
    return 3.0 * wma(x, n) - 2.0 * sma(x, n)


def macd_main(c, fast, slow):
    """iMACD(fast, slow, signal 1) buffer 0: EMA(fast) - EMA(slow) of the close."""
    return ema(c, fast) - ema(c, slow)


def momentum(c, n):
    """iMomentum: close / close n bars ago x 100."""
    c = np.asarray(c, float)
    out = np.full(len(c), np.nan)
    out[n:] = c[n:] / c[:-n] * 100.0
    return out


def rsi(c, n):
    """iRSI: Wilder's smoothing, seeded with the simple mean of the first n changes."""
    c = np.asarray(c, float)
    out = np.full(len(c), np.nan)
    if len(c) <= n:
        return out
    d = np.diff(c)
    up, dn = np.maximum(d, 0.0), np.maximum(-d, 0.0)
    pu, pd_ = up[:n].mean(), dn[:n].mean()
    out[n] = _rsi_val(pu, pd_)
    for i in range(n + 1, len(c)):
        pu = (pu * (n - 1) + up[i - 1]) / n
        pd_ = (pd_ * (n - 1) + dn[i - 1]) / n
        out[i] = _rsi_val(pu, pd_)
    return out


def _rsi_val(pu, pd_):
    if pd_ != 0:
        return 100.0 - 100.0 / (1 + pu / pd_)
    return 100.0 if pu != 0 else 50.0


def bands(c, n, dev):
    """iBands: SMA middle, population standard deviation x dev."""
    m = sma(c, n)
    sd = np.full(len(c), np.nan)
    if len(c) >= n:
        sd[n - 1:] = _win(c, n).std(1)
    return m, m + dev * sd, m - dev * sd


def stochastic(h, l, c, k, d, slowing):
    """iStochastic with MODE_SMA and STO_LOWHIGH: main = sum(c-LL)/sum(HH-LL) over `slowing`, signal = SMA(d)."""
    ll, hh = rmin(l, k), rmax(h, k)
    num, den = sma(np.asarray(c, float) - ll, slowing), sma(hh - ll, slowing)
    main = np.where(den == 0, 100.0, num / np.where(den == 0, 1, den) * 100.0)
    return main, sma(main, d)


def true_range(h, l, c):
    h, l, c = (np.asarray(x, float) for x in (h, l, c))
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h, pc) - np.minimum(l, pc)
    tr[0] = h[0] - l[0]
    return tr


def atr(h, l, c, n):
    """iATR: a simple mean of true range (MetaTrader's, not Wilder's)."""
    return sma(true_range(h, l, c), n)


def heiken_ashi(o, h, l, c):
    """Examples/Heiken_Ashi.mq5: open = mean of the last HA open and close, close = OHLC/4."""
    o, h, l, c = (np.asarray(x, float) for x in (o, h, l, c))
    n = len(o)
    hc = (o + h + l + c) / 4.0
    hc[0] = c[0]
    ho = np.empty(n)
    ho[0] = o[0]
    for i in range(1, n):
        ho[i] = (ho[i - 1] + hc[i - 1]) / 2.0
    hh = np.maximum(h, np.maximum(ho, hc))
    hl = np.minimum(l, np.minimum(ho, hc))
    hh[0], hl[0] = h[0], l[0]
    return ho, hh, hl, hc


def andean(o, c, length=50, signal=9):
    """AndeanOscillator.mq5: bull, bear and the EMA of max(bull, bear)."""
    o, c = np.asarray(o, float), np.asarray(c, float)
    n = len(c)
    a = 2.0 / (length + 1)
    bull, bear, sig = np.zeros(n), np.zeros(n), np.zeros(n)
    u1 = u2 = d1 = d2 = 0.0
    for i in range(1, n):
        ci, oi = c[i], o[i]
        c2 = ci * ci
        u1 = max(max(ci, oi), u1 - (u1 - ci) * a)
        if u1 == 0:
            u1 = ci
        u2 = max(max(c2, oi * oi), u2 - (u2 - c2) * a)
        if u2 == 0:
            u2 = c2
        d1 = min(min(ci, oi), d1 + (ci - d1) * a)
        if d1 == 0:
            d1 = ci
        d2 = min(min(c2, oi * oi), d2 + (c2 - d2) * a)
        if d2 == 0:
            d2 = c2
        vb, vr = d2 - d1 * d1, u2 - u1 * u1
        # a variance of exactly zero can round below it; MQL's sqrt would give NaN and its max() would
        # then drop it, which is what flooring at zero does
        bull[i] = np.sqrt(vb) if vb > 0 else 0.0
        bear[i] = np.sqrt(vr) if vr > 0 else 0.0
        sig[i] = max(bull[i], bear[i])
    sf = 2.0 / (1.0 + signal)
    for i in range(1, n):  # the EMA is applied in place, over the raw max
        sig[i] = sig[i] * sf + sig[i - 1] * (1.0 - sf)
    return bull, bear, sig


def average_force(h, l, c, p=20, s=9):
    """AverageForce.mq5: where the close sits in the p-bar range (-0.5..0.5), averaged over s bars."""
    hh, ll = rmax(h, p), rmin(l, p)
    diff = hh - ll
    c1 = np.where(diff == 0, 0.0, (np.asarray(c, float) - ll) / np.where(diff == 0, 1, diff) - 0.5)
    return sma(c1, s)


def atr_sl_finder(h, l, c, length=14, mult=1.5):
    """AtrSlFinder.mq5: high + mult x SMA(true range), low - the same."""
    m = sma(true_range(h, l, c), length)
    return np.asarray(h, float) + m * mult, np.asarray(l, float) - m * mult


def chandelier_exit(o, h, l, c, atr_period=1, mult=0.75):
    """ChandelierExit.mq5 on Heiken Ashi closes and ATR_HeikenAshi: the long stop on a buy flip, the
    short stop on a sell flip, 0 elsewhere."""
    ho, hh, hl, hc = heiken_ashi(o, h, l, c)
    n = len(hc)
    pc = np.r_[hc[0], hc[:-1]]
    tr = np.maximum(hh, pc) - np.minimum(hl, pc)
    tr[0] = 0.0
    a = np.zeros(n)  # ATR_HeikenAshi: a running simple mean of HA true range, first value at index period
    if n > atr_period:
        a[atr_period] = tr[1:atr_period + 1].mean()
        for i in range(atr_period + 1, n):
            a[i] = a[i - 1] + (tr[i] - tr[i - atr_period]) / atr_period
    mx, mn = rmax(hc, atr_period), rmin(hc, atr_period)
    a1, a2 = a * mult, np.r_[0.0, a[:-1]] * mult
    mx2, mn2 = np.r_[np.nan, mx[:-1]], np.r_[np.nan, mn[:-1]]
    ls1, ls2 = mx - a1, mx2 - a2
    ss1, ss2 = mn + a1, mn2 + a2
    long_stop = np.where(pc > ls2, np.maximum(ls1, ls2), ls1)
    short_stop = np.where(pc < ss2, np.minimum(ss1, ss2), ss1)
    raw = np.where(hc > ss2, 1.0, np.where(hc < ls2, -1.0, np.nan))
    start = atr_period
    raw[:start] = 1.0
    d = _ffill(raw)
    prev = np.r_[1.0, d[:-1]]
    buy = np.where((d == 1) & (prev == -1), long_stop, 0.0)
    sell = np.where((d == -1) & (prev == 1), short_stop, 0.0)
    buy[:start], sell[:start] = 0.0, 0.0
    return buy, sell, hc


def _ffill(x):
    x = np.asarray(x, float)
    idx = np.where(np.isfinite(x), np.arange(len(x)), 0)
    np.maximum.accumulate(idx, out=idx)
    return x[idx]


def zlsma(src, period=50):
    """ZLSMA.mq5: 2 x LRMA(src) - LRMA(LRMA(src))."""
    b2 = lrma(src, period)
    return 2 * b2 - lrma(b2, period)


def lrc(o, h, l, c, length=11, sig=7):
    """LinearRegressionCandles.mq5: each price's LRMA, and the signal = SMA of the LRMA close."""
    lo, lc = lrma(o, length), lrma(c, length)
    return lo, lrma(h, length), lrma(l, length), lc, sma(lc, sig)


def utbot(h, l, c, coef=2.0, atr_len=1):
    """UTBot.mq5: an ATR trailing line; Bull/Bear are nonzero on the bar the close crosses it."""
    h, l, c = (np.asarray(x, float) for x in (h, l, c))
    n = len(c)
    loss = atr(h, l, c, atr_len) * coef
    c1 = np.zeros(n)
    bull, bear = np.zeros(n), np.zeros(n)
    first = max(1, atr_len)
    for i in range(first, n):
        p = c1[i - 1]
        ci, cp = c[i], c[i - 1]
        t1 = ci - loss[i] if ci > p else ci + loss[i]
        t2 = min(p, ci + loss[i]) if (ci < p and cp < p) else t1
        c1[i] = max(p, ci - loss[i]) if (ci > p and cp > p) else t2
        rng_ = abs(h[i - 1] - l[i - 1])
        if ci > c1[i] and cp <= p:
            bull[i] = l[i] - rng_
        if ci < c1[i] and cp >= p:
            bear[i] = h[i] + rng_
    return bull, bear, c1


def nadaraya_watson(c, bandwidth=8.0, mult=3.0, window=500):
    """NadarayaWatsonEnvelope.mq5 (the causal end-point form): a Gaussian-weighted mean of the last
    `window` closes, plus/minus mult x the mean absolute deviation over the window."""
    c = np.asarray(c, float)
    n = len(c)
    up, dn = np.full(n, np.nan), np.full(n, np.nan)
    if n <= window:
        return up, dn
    k = np.arange(window, dtype=float)
    g = np.exp(-(k ** 2) / (bandwidth * bandwidth * 2))
    mid = np.full(n, np.nan)
    mid[window - 1:] = _win(c, window) @ g[::-1] / g.sum()
    dev = np.abs(c - mid)
    band = np.full(n, np.nan)
    if n >= 2 * window - 1:
        band[2 * window - 2:] = _win(dev[window - 1:], window).sum(1) / window * mult
    return mid + band, mid - band


def fractals(h, l):
    """iFractals: an up fractal at bar i when its high beats the two later bars strictly and is not
    beaten by the two earlier ones (lows mirrored). Value at i needs bars i+1, i+2: NaN where unknown."""
    h, l = np.asarray(h, float), np.asarray(l, float)
    n = len(h)
    up, dn = np.full(n, np.nan), np.full(n, np.nan)
    i = np.arange(2, n - 2)
    cu = (h[i] > h[i + 1]) & (h[i] > h[i + 2]) & (h[i] >= h[i - 1]) & (h[i] >= h[i - 2])
    cd = (l[i] < l[i + 1]) & (l[i] < l[i + 2]) & (l[i] <= l[i - 1]) & (l[i] <= l[i - 2])
    up[i[cu]], dn[i[cd]] = h[i[cu]], l[i[cd]]
    return up, dn


def prev_day_hl(ts, h, l, day_ts=None):
    """DailyHighLow.mq5 (Previous = true, DHL_LOWHIGH): the high and low of the day before each bar's
    day. Days come from the broker's own D1 opens when given, else UTC midnights."""
    ts = np.asarray(ts, np.int64)
    if day_ts is None:
        day = ts // 86400
    else:
        day = np.searchsorted(np.asarray(day_ts, np.int64), ts, side="right") - 1
    h, l = np.asarray(h, float), np.asarray(l, float)
    uniq, inv = np.unique(day, return_inverse=True)
    dh = np.full(len(uniq), -np.inf)
    dl = np.full(len(uniq), np.inf)
    np.maximum.at(dh, inv, h)
    np.minimum.at(dl, inv, l)
    ph = np.r_[np.nan, dh[:-1]][inv]
    pl = np.r_[np.nan, dl[:-1]][inv]
    return ph, pl
