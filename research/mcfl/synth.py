"""Bars we generate: the only data MCFL v0 has, and the null every count is compared against.

Each bar is built from STEPS Gaussian sub-steps, so highs and lows come from a path rather than a
formula: open is the previous close, high and low the path's extremes. Prices are arithmetic
(additive), so a flip is the same process.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

STEPS = 8
"""Sub-steps per bar; sets how wide a bar's range is against its close-to-close move."""
START = 1000.0
"""First open. Arithmetic prices: a walk of sigma 1 a bar wanders about sqrt(n) from here."""


def bars_from_path(path: np.ndarray, steps: int = STEPS) -> pd.DataFrame:
    """A price path sampled `steps` times per bar (length n * steps + 1) into OHLC bars."""
    n = (len(path) - 1) // steps
    seg = np.lib.stride_tricks.sliding_window_view(path, steps + 1)[::steps][:n]
    return pd.DataFrame({"open": seg[:, 0], "high": seg.max(1), "low": seg.min(1), "close": seg[:, -1],
                         "volume": np.full(n, float(steps))})


def walk(n: int, sigma: float = 1.0, seed: int = 0, steps: int = STEPS) -> pd.DataFrame:
    """An iid Gaussian walk: sigma per bar close to close. No structure of any kind."""
    rng = np.random.default_rng(seed)
    inc = rng.normal(0.0, sigma / np.sqrt(steps), n * steps)
    return bars_from_path(START + np.r_[0.0, np.cumsum(inc)], steps)


def garch(n: int, sigma: float = 1.0, alpha: float = 0.08, beta: float = 0.9, seed: int = 0,
          steps: int = STEPS) -> pd.DataFrame:
    """GARCH(1,1) per bar with unconditional sigma per bar: volatility clusters, direction does not."""
    rng = np.random.default_rng(seed)
    omega = sigma ** 2 * (1 - alpha - beta)
    var, r_prev = sigma ** 2, 0.0
    vols = np.empty(n)
    for i in range(n):
        var = omega + alpha * r_prev ** 2 + beta * var
        vols[i] = np.sqrt(var)
        r_prev = rng.normal(0.0, vols[i])
    # the bar's sub-steps carry its volatility; the drawn r_prev only drives the recursion's shocks,
    # so redraw the path from the per-bar vols to keep sub-steps and bar consistent
    inc = rng.normal(0.0, 1.0, (n, steps)) * (vols / np.sqrt(steps))[:, None]
    return bars_from_path(START + np.r_[0.0, np.cumsum(inc.ravel())], steps)


def trend(n: int, sigma: float = 1.0, phi: float = 0.2, seed: int = 0, steps: int = STEPS) -> pd.DataFrame:
    """AR(1) bar returns with coefficient phi: momentum, a structure a parser should be able to see.
    The positive control for the walk null."""
    rng = np.random.default_rng(seed)
    eps = rng.normal(0.0, sigma * np.sqrt(1 - phi ** 2), n)
    r = np.empty(n)
    prev = 0.0
    for i in range(n):
        prev = phi * prev + eps[i]
        r[i] = prev
    # sub-steps: a Brownian bridge-free split - the bar's return spread evenly plus within-bar noise
    noise = rng.normal(0.0, sigma / np.sqrt(steps), (n, steps))
    noise -= noise.mean(1, keepdims=True)
    inc = r[:, None] / steps + noise
    return bars_from_path(START + np.r_[0.0, np.cumsum(inc.ravel())], steps)


def matched_walk(df: pd.DataFrame, seed: int, steps: int = STEPS) -> pd.DataFrame:
    """The null for `df`: an iid walk of the same length and the same close-to-close volatility."""
    sigma = float(np.std(np.diff(df["close"].to_numpy(float))))
    return walk(len(df), sigma=sigma, seed=seed, steps=steps)


TICK_RATE = 40.0
"""v2: mean ticks per unit of the bar's range in units of sigma (`ticks`)."""


def ticks(df: pd.DataFrame, seed: int, rate: float = TICK_RATE, skew: float = 0.2) -> pd.DataFrame:
    """v2: a tick volume and a taker split for generated bars, as a CFD's and an exchange's feed would
    have them. Volume ~ Poisson(rate x range / sd(close changes)) x a lognormal(0, 0.3) burst, so it
    tracks the bar's range (and GARCH's clustering) with noise of its own; taker buys ~ Binomial(volume,
    0.5 + skew x (close - open) / range), so the taker side leans with the bar."""
    rng = np.random.default_rng(seed)
    c = df["close"].to_numpy(float)
    sd = float(np.std(np.diff(c))) or 1.0
    r = (df["high"] - df["low"]).to_numpy(float) / sd
    lam = rate * r * np.exp(rng.normal(0.0, 0.3, len(r)))
    v = rng.poisson(np.maximum(lam, 0.0)).astype(float)
    body = (df["close"] - df["open"]).to_numpy(float)
    p = 0.5 + skew * np.where(r > 0, body / np.where(r > 0, r * sd, 1.0), 0.0)
    buy = rng.binomial(v.astype(np.int64), np.clip(p, 0.0, 1.0)).astype(float)
    return df.assign(volume=v, taker_buy_volume=buy)


def gapped(n: int, sigma: float = 1.0, gap: float = 0.5, seed: int = 0, steps: int = STEPS) -> pd.DataFrame:
    """v2: an iid walk whose bars open away from the last close - a session market's overnight gap. Each
    bar opens at the previous close plus a N(0, (gap x sigma)^2) jump that is not traded (it is not in
    the bar's high or low), then moves as `walk` does. Without gaps a third of the Japanese candlestick
    vocabulary cannot occur at all."""
    rng = np.random.default_rng(seed)
    jump = rng.normal(0.0, gap * sigma, n)
    inc = rng.normal(0.0, sigma / np.sqrt(steps), (n, steps))
    o, h, l, c = (np.empty(n) for _ in range(4))
    prev = START
    for i in range(n):
        path = prev + jump[i] + np.r_[0.0, np.cumsum(inc[i])]
        o[i], h[i], l[i], c[i] = path[0], path.max(), path.min(), path[-1]
        prev = c[i]
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": np.full(n, float(steps))})


# ---------------------------------------------------------------- the time core: walks on a market's calendar

def gaps(ts: np.ndarray) -> np.ndarray:
    """Per bar, whether it opens after a hole in the clock (a gap longer than the bar's spacing)."""
    d = np.diff(np.asarray(ts, np.int64))
    if not len(d):
        return np.zeros(len(ts), bool)
    step = d[d > 0].min() if (d > 0).any() else 1
    return np.r_[False, d > step]


def hour_sigma(df: pd.DataFrame) -> tuple[np.ndarray, float]:
    """A market's intraday volatility profile: the sd of close-to-close changes of the bars that open
    in each UTC hour (bars after a hole in the clock left out), and the sd of the jump from the last
    close to the open across those holes. An hour with fewer than 20 bars takes the median sd."""
    ts = df["ts"].to_numpy(np.int64)
    c, o = df["close"].to_numpy(float), df["open"].to_numpy(float)
    g = gaps(ts)
    dc = np.r_[np.nan, np.diff(c)]
    hr = (ts // 3600) % 24
    sig = np.full(24, np.nan)
    for h in range(24):
        x = dc[(hr == h) & ~g]
        x = x[np.isfinite(x)]
        if len(x) >= 20:
            sig[h] = float(np.std(x))
    sig[~np.isfinite(sig)] = np.nanmedian(sig) if np.isfinite(sig).any() else float(np.nanstd(dc))
    jump = o[1:][g[1:]] - c[:-1][g[1:]]
    return sig, float(np.std(jump)) if len(jump) >= 5 else 0.0


def profiled(ts: np.ndarray, sigma_hour: np.ndarray, gap_sigma: float = 0.0, seed: int = 0,
             steps: int = STEPS, garch: tuple[float, float] | None = None, start: float = START) -> pd.DataFrame:
    """An iid walk on the given timestamps whose volatility follows an hour-of-day profile: each bar's
    sub-steps carry sigma_hour[its UTC hour], and a bar opening after a hole in the clock opens away
    from the last close by an untraded N(0, gap_sigma^2) jump (as `gapped`). The null for a time
    effect: the same calendar and the same intraday volatility, and nothing else - no clustering, no
    direction, no memory. `garch=(alpha, beta)` multiplies the profile by a GARCH(1,1) variance of
    mean 1, so volatility also clusters (a stricter null: real markets cluster)."""
    ts = np.asarray(ts, np.int64)
    n = len(ts)
    rng = np.random.default_rng(seed)
    sig = np.asarray(sigma_hour, float)[(ts // 3600) % 24]
    if garch is not None:
        a, b = garch
        z = rng.normal(0.0, 1.0, n)
        var = np.empty(n)
        v = 1.0
        for i in range(n):
            var[i] = v
            v = (1 - a - b) + a * v * z[i] ** 2 + b * v
        sig = sig * np.sqrt(var / var.mean())
    inc = rng.normal(0.0, 1.0, (n, steps)) * (sig / np.sqrt(steps))[:, None]
    jump = np.where(gaps(ts), rng.normal(0.0, gap_sigma, n) if gap_sigma > 0 else 0.0, 0.0)
    start = start + np.r_[0.0, np.cumsum(inc.sum(1) + jump)[:-1]] + jump
    path = start[:, None] + np.c_[np.zeros(n), np.cumsum(inc, 1)]
    return pd.DataFrame({"open": path[:, 0], "high": path.max(1), "low": path.min(1), "close": path[:, -1],
                         "volume": np.full(n, float(steps)), "ts": ts})


def matched_profiled(df: pd.DataFrame, seed: int, steps: int = STEPS, garch: tuple[float, float] | None = None
                     ) -> pd.DataFrame:
    """The time-core null for `df`: a `profiled` walk on df's own timestamps with df's own hour-of-day
    volatility and overnight jumps, from df's first open."""
    sig, jump = hour_sigma(df)
    return profiled(df["ts"].to_numpy(np.int64), sig, jump, seed, steps, garch, float(df["open"].iloc[0]))


def matched_on_calendar(df: pd.DataFrame, seed: int, steps: int = STEPS) -> pd.DataFrame:
    """The plain null on df's own timestamps: `matched_walk`, one volatility for every hour. Against it
    any intraday volatility pattern reads as a time effect."""
    return matched_walk(df, seed, steps).assign(ts=df["ts"].to_numpy(np.int64))
