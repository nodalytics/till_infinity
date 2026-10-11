"""The bar layer the patterns read: OHLC arrays, and the few token classes they use.

A port of the part of `research/mcfl/candles.py` the alert patterns need, and
nothing else. The research token table carries forty-odd columns - point
matrices, wick grades, the lexeme - and every pattern ported here reads five of
them: the bar's direction, its size class, its body-force grade, its close
quartile and the Wilder ATR. Porting the rest would be porting code nothing
runs, which is how a production copy drifts from its source without anyone
noticing.

**Production does not import `research/`.** Research is experiments written to
be read beside their results; a service that imported it would ship whatever
was last edited there. The parity tests in `tests/test_mcfl_parity.py` run this
and the research parser on the same bars and require the same events, bar for
bar - that is the contract, not the import.

## The arithmetic is copied, not rewritten

The classes are thresholds on rolling means and standard deviations, so a value
on a threshold goes one way or the other by the last bit of a float. The
rolling sums below accumulate left to right exactly as the research version
does, and the ATR is the same Wilder recursion warmed on the same simple mean,
so a parity test can demand equality rather than "close enough".

## Flipping

Every directional rule is written for the up side and run again on the chart
turned upside down: prices negated, highs and lows swapped. The size and force
classes do not change under the flip; the bar's direction and its close
quartile trade places (BULL with BEAR, Q4 with Q1). That is what `Tokens.flip`
does, and it is how the research grammar reads its down side too.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

#: Bars in the rolling window each class is measured against.
PERIOD = 10
#: Wilder ATR length.
ATR_N = 14

WARMUP = "WARMUP"
SIZE = ("VERY_SMALL", "SMALL", "MEDIUM", "LARGE", "VERY_LARGE", "EXTREMELY_LARGE")
SIZE_EDGES = (-1.0, -0.5, 0.5, 1.0, 2.0)
GRADE = ("WEAK", "MODERATE", "STRONG", "DOMINANT")
GRADE_EDGES = (-0.5, 0.5, 1.0)

_DIR_FLIP = {"BULL": "BEAR", "BEAR": "BULL", "NONE": "NONE"}
_Q_FLIP = {"Q1": "Q4", "Q4": "Q1", "Q2": "Q3", "Q3": "Q2"}


@dataclass(frozen=True, slots=True)
class Bars:
    """Closed bars, oldest first. `ts` is each bar's open, epoch seconds UTC."""

    ts: np.ndarray
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray

    @classmethod
    def of(cls, rows) -> Bars:
        """From (ts, open, high, low, close[, ...]) rows."""
        a = np.asarray([tuple(r[:5]) for r in rows], float).reshape(-1, 5)
        return cls(a[:, 0].astype(np.int64), a[:, 1], a[:, 2], a[:, 3], a[:, 4])

    def __len__(self) -> int:
        return len(self.close)

    def upto(self, last: int) -> Bars:
        """The bars up to and including index `last` - what was known at its close."""
        k = last + 1
        return Bars(self.ts[:k], self.open[:k], self.high[:k], self.low[:k], self.close[:k])

    def tail(self, count: int) -> Bars:
        return Bars(
            self.ts[-count:],
            self.open[-count:],
            self.high[-count:],
            self.low[-count:],
            self.close[-count:],
        )

    def flip(self) -> Bars:
        """The chart upside down. `flip().flip()` is the chart exactly."""
        return Bars(self.ts, -self.open, -self.low, -self.high, -self.close)


def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, n: int = ATR_N) -> np.ndarray:
    """Wilder ATR, warmed on a simple mean of the first n true ranges (NaN before)."""
    prev = np.r_[close[:1], close[:-1]]
    tr = np.maximum(high, prev) - np.minimum(low, prev)
    out = np.full(len(tr), np.nan)
    if len(tr) <= n:
        return out
    out[n] = tr[1 : n + 1].mean()
    for i in range(n + 1, len(tr)):
        out[i] = out[i - 1] + (tr[i] - out[i - 1]) / n
    return out


def rolling(x: np.ndarray, period: int = PERIOD) -> tuple[np.ndarray, np.ndarray]:
    """Mean and population sd of the window ending at each bar, itself included.

    Summed left to right per window, so a window gives the same numbers
    whatever came before or after it.
    """
    n = len(x)
    m, s = np.full(n, np.nan), np.full(n, np.nan)
    first = period - 1
    if n <= first:
        return m, s
    end = np.arange(first, n) + 1
    acc = np.zeros(len(end))
    for j in range(period):
        acc = acc + x[end - period + j]
    mu = acc / period
    acc = np.zeros(len(end))
    for j in range(period):
        acc = acc + (x[end - period + j] - mu) ** 2
    m[first:], s[first:] = mu, np.sqrt(acc / period)
    return m, s


def graded(
    x: np.ndarray, edges: tuple[float, ...], names: tuple[str, ...], zero: str
) -> np.ndarray:
    """Each value classed against its own rolling window; WARMUP until it is full.

    `zero` for a zero value; the middle class when the window has no spread;
    otherwise the first name whose edge (mean + k sd) the value is at or under.
    """
    m, s = rolling(x)
    xb, mb, sb = np.broadcast_arrays(*(np.asarray(v, float) for v in (x, m, s)))
    conds = [xb == 0, sb == 0] + [xb <= mb + k * sb for k in edges]
    middle = names[sum(k < 0 for k in edges)]
    out = np.select(conds, [zero, middle, *names[:-1]], default=names[-1]).astype(object)
    out[np.isnan(m) | np.isnan(x)] = WARMUP
    return out


def quartile(close: np.ndarray, high: np.ndarray, low: np.ndarray) -> np.ndarray:
    """Q4 when the close sits in the top quarter of the range, Q1 the bottom."""
    a, b = close - low, high - close
    return np.select([a > 3 * b, b > 3 * a, b < a], ["Q4", "Q1", "Q3"], default="Q2").astype(object)


@dataclass(frozen=True, slots=True)
class Tokens:
    """The classes the patterns read, one entry per bar, in one frame.

    `bars` is the frame's own bars - flipped for the down side - so a rule
    that reads a price reads it in the same frame as the classes.
    """

    bars: Bars
    atr: np.ndarray
    body_atr: np.ndarray
    dir: np.ndarray
    size: np.ndarray
    force: np.ndarray
    close_q: np.ndarray

    def flip(self) -> Tokens:
        """The same tokens as the flipped chart has them."""
        return replace(
            self,
            bars=self.bars.flip(),
            dir=np.array([_DIR_FLIP[d] for d in self.dir], object),
            close_q=np.array([_Q_FLIP[q] for q in self.close_q], object),
        )


def tokens(bars: Bars) -> Tokens:
    """The token classes of every bar, on the chart as it is."""
    o, h, low, c = bars.open, bars.high, bars.low, bars.close
    a = atr(h, low, c)
    body = np.maximum(o, c) - np.minimum(o, c)
    with np.errstate(invalid="ignore", divide="ignore"):
        body_atr = np.where(a > 0, body / a, np.nan)
    return Tokens(
        bars=bars,
        atr=a,
        body_atr=body_atr,
        dir=np.where(c > o, "BULL", np.where(c < o, "BEAR", "NONE")).astype(object),
        size=graded(h - low, SIZE_EDGES, SIZE, "NONE"),
        force=graded(body_atr, GRADE_EDGES, GRADE, "WEAK"),
        close_q=quartile(c, h, low),
    )


def frames(bars: Bars) -> dict[int, Tokens]:
    """The tokens in both frames: +1 the chart, -1 the chart flipped."""
    up = tokens(bars)
    return {1: up, -1: up.flip()}


def resample(bars: Bars, seconds: int, sub_seconds: int) -> Bars:
    """Bars of `seconds` built from finer closed bars, on UTC boundaries.

    For a deployment whose `INTERVALS` does not collect 1d: a day is the bars
    opening in [00:00, 24:00) UTC - the research's daily boundary - and is kept
    only once a sub-bar of `sub_seconds` closing at or after its end is in
    hand, so the newest, still-forming day is never emitted. A day with missing
    sub-bars is built from those it has, as a venue's own daily bar would be.
    """
    if not len(bars):
        return bars
    bucket = bars.ts // seconds * seconds
    keys, first = np.unique(bucket, return_index=True)
    last = np.r_[first[1:], len(bucket)] - 1
    done = keys + seconds <= int(bars.ts[-1]) + sub_seconds
    keys, first, last = keys[done], first[done], last[done]
    high = np.array([bars.high[a : b + 1].max() for a, b in zip(first, last, strict=True)])
    low = np.array([bars.low[a : b + 1].min() for a, b in zip(first, last, strict=True)])
    return Bars(keys.astype(np.int64), bars.open[first], high, low, bars.close[last])
