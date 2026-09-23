"""Barrier races on OHLC bars, shared by the direction harnesses.

A stop is taken by a wick, not a close. Every race here reads the next H bars'
open, high, low and close relative to the entry close, fills at the level (or at the
open when a bar gaps through it), and scores a bar whose range spans both levels as
the stop - the bar cannot say which came first, and guessing the target flatters.
"""

from __future__ import annotations

import numpy as np


class Bars:
    """The next H bars relative to the entry close: open, high, low, close, each (n, H).

    Multiplying by a side (+1 long, -1 short; a scalar or one per row) re-expresses the path
    from that side's point of view - a short's favourable extreme is the negated low.
    """

    def __init__(self, o, h, l, c):
        self.o, self.h, self.l, self.c = o, h, l, c

    def __mul__(self, s):
        s = np.asarray(s, float)
        s = np.full(len(self.c), float(s)) if s.ndim == 0 else s.reshape(len(self.c), -1)[:, 0]
        S, up = s[:, None], s[:, None] > 0
        return Bars(S * self.o, np.where(up, self.h, -self.l), np.where(up, self.l, -self.h), S * self.c)

    __rmul__ = __mul__

    @property
    def end(self):
        return self.c[:, -1]


def paths(d, H):
    """Path of the next H bars within each ticker. A close-only frame gets bars with no range."""
    g = d.groupby("ticker")
    col = lambda c: c if c in d else "_lc"
    m = lambda c: np.column_stack([(g[col(c)].shift(-k) - d["_lc"]).to_numpy() for k in range(1, H + 1)])
    return Bars(m("_op"), m("_hi"), m("_lo"), m("_lc"))


def race(P, up, dn):
    """Long race on bars: +1 if +up is touched first, -1 if -dn first, 0 neither; and the fill.

    Touches are read from the wick, not the close - a stop is taken out by a low that
    closes back above it. Fills: at the open if the bar gaps through a level, otherwise at
    the level itself. A bar whose range spans both levels is scored as the stop, because
    the bar does not say which came first and assuming the target would flatter the bet.
    """
    n, H = P.c.shape
    out = np.zeros(n)
    fill = np.full(n, np.nan)
    done = np.zeros(n, bool)
    for k in range(H):
        o, h, l = P.o[:, k], P.h[:, k], P.l[:, k]
        gap_dn = ~done & (o <= -dn)
        gap_up = ~done & ~gap_dn & (o >= up)
        rest = ~done & ~gap_dn & ~gap_up
        stop = rest & (l <= -dn)
        take = rest & ~stop & (h >= up)
        out[gap_dn | stop], out[gap_up | take] = -1, 1
        fill[gap_dn], fill[gap_up] = o[gap_dn], o[gap_up]
        fill[stop] = -np.broadcast_to(dn, n)[stop]
        fill[take] = np.broadcast_to(up, n)[take]
        done |= gap_dn | gap_up | stop | take
    return out, fill


def long_R(P, up, dn):
    """R of a long with target +up and stop -dn, in stop units; open at H -> marked to the close.

    The first version resolved on closes and marked a stop at exactly -1 and a target at
    exactly +up/dn. Closes overshoot both, and on a +3:-1 bet the stop is crossed three
    times as often as the target, so the omission manufactured +0.15R on every-bar longs.
    Resolving on the bar's own high and low removes the overshoot rather than modelling it.
    """
    w, fill = race(P, up, dn)
    return np.where(w != 0, fill / dn, P.end / dn), w


class Fitted:
    """A classifier fit on only the columns that carry a value in its training rows.

    HistGradientBoosting handles NaN but crashes binning a column that is *entirely* NaN,
    which a pair ratio's bar features and an event subset's sparse columns both produce.
    """

    def __init__(self, model, X, y):
        self.keep = np.isfinite(X).any(axis=0)
        self.model = model.fit(X[:, self.keep], y)

    def predict_proba(self, X):
        return self.model.predict_proba(X[:, self.keep])
