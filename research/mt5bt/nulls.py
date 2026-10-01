"""The two nulls every result here is judged against.

1. `random_null`: the same number of trades, at random bars and on random sides, each keeping
   its own stop, target and hold - rescaled by the local true range, so the geometry is the same
   in volatility units. A strategy that cannot beat a random pick of its own geometry has no
   entry skill (research/docs/triage.md's standard).
2. `t_walk` / `garch_walk`: bars from walks we generate ourselves, with the real book's spread
   and contract, for a strategy to be run on. A walk has no edge to find, so whatever a strategy
   earns there is the harness, the costs or luck. Deriv's markets are markets, not walks.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .data import Book
from .engine import SECONDS, run


def true_range(bars: pd.DataFrame, n: int = 14) -> np.ndarray:
    h, l, c = bars["high"].to_numpy(), bars["low"].to_numpy(), bars["close"].to_numpy()
    prev = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(abs(h - prev), abs(l - prev)))
    return pd.Series(tr).rolling(n, min_periods=1).mean().to_numpy()


def random_null(books: list[Book], trades: pd.DataFrame, draws: int = 200, seed: int = 7,
                **kw) -> pd.DataFrame:
    """Mean R of `draws` random-entry replays of `trades`. `kw` goes to `run` (costs, risk...)."""
    rng = np.random.default_rng(seed)
    by = {b.symbol: b for b in books}
    atr = {s: true_range(b.bars) for s, b in by.items()}
    rows = []
    for d in range(draws):
        sigs = {}
        for sym, g in trades.groupby("symbol"):
            n = len(by[sym].bars)
            i = rng.integers(14, n - 2, size=len(g))
            scale = atr[sym][i] / np.maximum(atr[sym][g["signal_bar"].to_numpy()], 1e-12)
            sigs[sym] = pd.DataFrame({"i": i, "side": rng.choice([-1, 1], size=len(g)),
                                      "stop": g["stop_d"].to_numpy() * scale,
                                      "target": g["target_d"].to_numpy() * scale,
                                      "hold": g["hold"].to_numpy()})
        got, _ = run([by[s] for s in sigs], None, signals=sigs, **kw)
        rows.append(dict(draw=d, n=len(got), mean_R=got["R"].mean() if len(got) else np.nan))
    return pd.DataFrame(rows)


def _calendar(n: int, interval: str, start: str = "2024-01-01") -> np.ndarray:
    """Bar opens on a 24/5 clock: Friday 21:00 to Sunday 21:00 UTC is closed."""
    step = SECONDS[interval]
    t = pd.Timestamp(start, tz="UTC").timestamp()
    out = []
    while len(out) < n:
        d = pd.Timestamp(t, unit="s", tz="UTC")
        wd, hr = d.weekday(), d.hour
        if not (wd == 5 or (wd == 4 and hr >= 21) or (wd == 6 and hr < 21)):
            out.append(int(t))
        t += step
    return np.array(out)


def _bars(steps: np.ndarray, price: float, spread_points: float) -> pd.DataFrame:
    """OHLC from independent sub-step price increments, `steps` of shape (bars, sub).

    The path is built from the increments forward - never pinned to a bar's return and filled
    in - so it is a martingale at every scale, inside the bar included. (A first version drew
    each bar's return and then a bridge to it; the path inside the bar then drifted predictably
    toward its close, and a stop taken mid-bar dodged a move already coming: +0.07R a trade of
    free edge on a walk.) Arithmetic, so the price itself is the martingale, not its log.
    """
    path = price + np.cumsum(steps.ravel()).reshape(steps.shape)
    o = np.r_[price, path[:-1, -1]]
    c = path[:, -1]
    h = np.maximum(path.max(axis=1), o)
    lo = np.minimum(path.min(axis=1), o)
    return pd.DataFrame({"open": o, "high": h, "low": lo, "close": c,
                         "volume": 0.0, "spread": spread_points})


def _t(rng, df, shape):
    """Unit-variance Student-t draws."""
    return rng.standard_t(df, shape) / np.sqrt(df / (df - 2))


CHUNK = 4096


def t_walk(n: int, *, interval: str = "15m", price: float = 1.10, bar_vol: float = 0.001,
           df: float = 3.0, spread_points: float = 8.0, seed: int = 1, sub: int = 256) -> pd.DataFrame:
    """iid Student-t sub-steps, `bar_vol` per bar: no clustering, no edge.

    `sub` sub-steps a bar. Few sub-steps make a bar backtest optimistic: a stop filled at its
    level when the path jumped through it gives back the overshoot (+0.09R a trade at 16
    sub-steps of t(3), +0.03 at 64, none at 256 - see README)."""
    rng = np.random.default_rng(seed)
    parts, last = [], price
    for a in range(0, n, CHUNK):
        m = min(CHUNK, n - a)
        part = _bars(_t(rng, df, (m, sub)) * price * bar_vol / np.sqrt(sub), last, spread_points)
        last = part["close"].iat[-1]
        parts.append(part)
    out = pd.concat(parts, ignore_index=True)
    out.insert(0, "ts", _calendar(n, interval))
    return out


def garch_walk(n: int, *, interval: str = "15m", price: float = 1.10, bar_vol: float = 0.001,
               alpha: float = 0.06, beta: float = 0.92, df: float = 5.0, spread_points: float = 8.0,
               seed: int = 1, sub: int = 256) -> pd.DataFrame:
    """GARCH(1,1) set bar by bar, t sub-steps inside: volatility clusters, direction does not."""
    rng = np.random.default_rng(seed)
    omega = bar_vol**2 * (1 - alpha - beta)
    var = bar_vol**2
    parts, last = [], price
    for a in range(0, n, CHUNK):
        m = min(CHUNK, n - a)
        z = _t(rng, df, (m, sub)) / np.sqrt(sub)
        zbar = z.sum(axis=1)  # each bar's unit-variance return
        sig = np.empty(m)
        for k in range(m):
            sig[k] = np.sqrt(var)
            var = omega + alpha * (sig[k] * zbar[k]) ** 2 + beta * var
        part = _bars(z * sig[:, None] * price, last, spread_points)
        last = part["close"].iat[-1]
        parts.append(part)
    out = pd.concat(parts, ignore_index=True)
    out.insert(0, "ts", _calendar(n, interval))
    return out
