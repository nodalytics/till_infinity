"""The primitives every idea is built from, all causal: a value at bar i uses bars 0..i only.

Pivots are the trap. A pivot high at bar p is known only once `right` bars after it have printed,
so `pivots()` reports it at bar p + right, never at p. Everything that reads swings goes through
`swings_known`, which hands each bar only the swings confirmed by then.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd


def atr(df: pd.DataFrame, n: int = 14) -> np.ndarray:
    """Wilder ATR, warmed on a simple mean of the first n true ranges."""
    h, l, c = df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy()
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h, pc) - np.minimum(l, pc)
    out = np.full(len(tr), np.nan)
    if len(tr) <= n:
        return out
    out[n] = tr[1:n + 1].mean()
    for i in range(n + 1, len(tr)):
        out[i] = out[i - 1] + (tr[i] - out[i - 1]) / n
    return out


def sma(x: np.ndarray, n: int) -> np.ndarray:
    return pd.Series(x).rolling(n, min_periods=n).mean().to_numpy()


def ema(x: np.ndarray, n: int) -> np.ndarray:
    return pd.Series(x).ewm(span=n, adjust=False).mean().to_numpy()


def std(x: np.ndarray, n: int) -> np.ndarray:
    return pd.Series(x).rolling(n, min_periods=n).std(ddof=0).to_numpy()


def pivots(high: np.ndarray, low: np.ndarray, left: int = 5, right: int = 5):
    """Pivot highs and lows as (known_at, index, price) lists, sorted by known_at.

    A pivot high at p: strictly above the `left` bars before it, at or above the `right` after it
    (so a flat top reports once, at its first bar). Known at p + right."""
    n = len(high)
    ph, pl = [], []
    for p in range(left, n - right):
        hv, lv = high[p], low[p]
        if hv > high[p - left:p].max() and hv >= high[p + 1:p + right + 1].max():
            ph.append((p + right, p, float(hv)))
        if lv < low[p - left:p].min() and lv <= low[p + 1:p + right + 1].min():
            pl.append((p + right, p, float(lv)))
    return ph, pl


def last_known(piv: list, n: int, k: int = 1) -> list[list]:
    """For each bar i, the last k pivots known by i (most recent last), as (index, price)."""
    out, j, buf = [], 0, []
    for i in range(n):
        while j < len(piv) and piv[j][0] <= i:
            buf.append((piv[j][1], piv[j][2]))
            j += 1
        out.append(buf[-k:] if buf else [])
    return out


def body(df):
    return (df["close"] - df["open"]).to_numpy()


def candles(df: pd.DataFrame, a: np.ndarray) -> pd.DataFrame:
    """Candle patterns on each bar (and the one before), with production sage's definitions."""
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    rng = np.maximum(h - l, 1e-12)
    bd = np.abs(c - o)
    up_w = h - np.maximum(o, c)
    lo_w = np.minimum(o, c) - l
    big = ~(a > 0) | (rng >= 0.5 * np.nan_to_num(a))
    po, pc, pl, ph = np.r_[o[0], o[:-1]], np.r_[c[0], c[:-1]], np.r_[l[0], l[:-1]], np.r_[h[0], h[:-1]]
    pbd = np.abs(pc - po)
    bull, pbull = c > o, pc > po
    tol = 0.1 * np.where(a > 0, a, rng)
    out = pd.DataFrame({
        "hammer": (lo_w >= 2 * bd) & (up_w <= 0.25 * rng) & big,
        "star": (up_w >= 2 * bd) & (lo_w <= 0.25 * rng) & big,
        "bull_engulf": ~pbull & bull & (c >= po) & (o <= pc) & (bd > pbd),
        "bear_engulf": pbull & ~bull & (c <= po) & (o >= pc) & (bd > pbd),
        "tweezer_bot": (np.abs(pl - l) <= tol) & ~pbull & bull,
        "tweezer_top": (np.abs(ph - h) <= tol) & pbull & ~bull,
        "piercing": ~pbull & bull & (o < pc) & (c >= (po + pc) / 2),
        "dark_cloud": pbull & ~bull & (o > pc) & (c <= (po + pc) / 2),
    })
    out["bull"] = out[["hammer", "bull_engulf", "tweezer_bot", "piercing"]].any(axis=1) & \
        ~out[["star", "bear_engulf", "tweezer_top", "dark_cloud"]].any(axis=1)
    out["bear"] = out[["star", "bear_engulf", "tweezer_top", "dark_cloud"]].any(axis=1) & \
        ~out[["hammer", "bull_engulf", "tweezer_bot", "piercing"]].any(axis=1)
    return out


def adx(df: pd.DataFrame, n: int = 14):
    """Wilder ADX, +DI and -DI."""
    h, l, c = df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy()
    up, dn = np.r_[0, np.diff(h)], np.r_[0, -np.diff(l)]
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    mdm = np.where((dn > up) & (dn > 0), dn, 0.0)
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h, pc) - np.minimum(l, pc)
    rma = lambda x: pd.Series(x).ewm(alpha=1 / n, adjust=False).mean().to_numpy()  # noqa: E731
    atr_ = np.maximum(rma(tr), 1e-12)
    pdi, mdi = 100 * rma(pdm) / atr_, 100 * rma(mdm) / atr_
    dx = 100 * np.abs(pdi - mdi) / np.maximum(pdi + mdi, 1e-12)
    return rma(dx), pdi, mdi


def tick_volume(df: pd.DataFrame) -> np.ndarray:
    for k in ("tick_volume", "volume"):
        if k in df:
            return df[k].to_numpy(float)
    return np.full(len(df), np.nan)


def htf_index(ts_lo: np.ndarray, sec_lo: int, ts_hi: np.ndarray, sec_hi: int) -> np.ndarray:
    """For each lower-TF bar, the last higher-TF bar closed at or before its close (-1 if none)."""
    return np.searchsorted(ts_hi + sec_hi, ts_lo + sec_lo, side="right") - 1


def ny_hour(ts: np.ndarray) -> np.ndarray:
    """New York local hour (DST-aware) of each bar's open."""
    t = pd.to_datetime(ts, unit="s", utc=True).tz_convert("America/New_York")
    return (t.hour + t.minute / 60.0).to_numpy()


def focus_series(x: np.ndarray, scale: np.ndarray, threshold: float, up: bool):
    """Run the production FOCuS detector over a series; returns (fired, at) per bar, resetting
    after each alarm as the indicator does. `at` is the bar index the change started at."""
    from till_infinity.structures.learning.focus import Focus
    f = Focus(threshold=threshold, up=up)
    fired = np.zeros(len(x), bool)
    at = np.full(len(x), -1)
    for i, (v, s) in enumerate(zip(x, scale)):
        if not (math.isfinite(v) and math.isfinite(s) and s > 0):
            f.update(0.0, 1.0)
            continue
        if f.update(float(v), float(s)):
            fired[i], at[i] = True, f.at  # observations from index `at` on are the changed ones
            f.reset()
    return fired, at
