"""Volatility read from the whole bar, not just its last price.

`volatility.py` measures the move from one close to the next. Everything
between them is thrown away - and `prices.announce_bars` has carried the open,
high and low on every bar since the doji bug was fixed, so what is discarded
here is information already in hand.

## Why the extremes are worth having

A close-to-close estimate sees one number per bar. A bar that ran twenty basis
points up, twenty back down and finished where it started reads as *no
movement at all*, which is the opposite of the truth and exactly the bar a
level cares about most - price went somewhere, was rejected, and came back.

Range estimators use the path. Published efficiency gains over close-to-close
run around five-fold for Garman-Klass and up to eight for Yang-Zhang at the
same sample size, which is not a small number: it means the same confidence
from a fifth of the history, or a far steadier estimate from the history there
is.

## Which one, and why not the simplest

Three are implemented because they fail differently and the differences matter
here.

**Parkinson** uses the high-low range alone. Simple, and it assumes no
overnight gap and no drift - it treats the bar as a continuous walk observed
throughout. Cheapest, and biased low whenever a series gaps.

**Garman-Klass** adds the open and close. More efficient again, and still
assumes the bar opened where the last one closed. On a 1m FX bar that is
nearly true; across a weekend on gold it is badly false.

**Yang-Zhang** is the one this module leads with. It is the only one of the
three that is **unbiased in the presence of opening gaps** *and* independent of
drift, which it achieves by decomposing the estimate into three pieces - the
overnight jump, the open-to-close move, and the Rogers-Satchell within-bar term
- and weighting them. Every instrument here gaps: FX over the weekend, indices
over their cash session, crypto never but it is quoted against instruments that
do. An estimator that assumes no gap would read those gaps as calm.

## What this does not do

It does not replace anything. `volatility.py` still produces the number every
threshold divides by, and this is published alongside it for the same reason
the mean-reverting estimate in `garch.py` is: given how much depends on that
one number, changing it on the strength of a literature citation would be the
mistake this repository keeps recording. These are fed the same bars, and the
journal is what decides.

One consequence worth stating: these need **bars**, and the live path is fed by
quotes as well. An estimate that only updates on bar closes is coarser in time
than one updating on every tick, so a fair comparison has to be made per bar
rather than per update.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from itertools import pairwise

from ..state import Restorable

#: Bars before a range estimate is trusted. Lower than the close-to-close
#: warmup precisely because that is the point: each bar carries more.
WARMUP = 12

#: Bars in the window. These are unweighted means over a window rather than
#: exponential, because the standard forms are defined that way and the
#: constants below only hold for that definition.
WINDOW = 60

#: A floor in basis points, matching `volatility.MIN_VOL_BPS`. A bar that did
#: not move at all gives zero, and everything downstream divides.
MIN_VOL_BPS = 0.05


#: Yang-Zhang's weight on the overnight term. `k` is chosen to minimise the
#: variance of the estimator; this is the standard form with n = WINDOW.
def _k(n: int) -> float:
    return 0.34 / (1.34 + (n + 1) / max(n - 1, 1))


@dataclass(slots=True)
class Bar(Restorable):
    """One bar, as the estimators need it. Prices, not returns.

    `Restorable` because these are held inside `Ranges` and therefore saved.
    A plain dataclass here would raise on the first restore after a field was
    added, and the throw lands inside the structures consumer - the container
    stays healthy and simply stops producing. See state.py.
    """

    open: float
    high: float
    low: float
    close: float


def parkinson(bars: list[Bar]) -> float:
    """High-low only. Assumes no gap and no drift."""
    usable = [b for b in bars if b.high > 0 and b.low > 0]
    if not usable:
        return 0.0
    total = sum(math.log(b.high / b.low) ** 2 for b in usable)
    return math.sqrt(total / (4.0 * math.log(2.0) * len(usable)))


def garman_klass(bars: list[Bar]) -> float:
    """High, low, open and close. Still assumes the bar opened at the last close."""
    usable = [b for b in bars if b.high > 0 and b.low > 0 and b.open > 0 and b.close > 0]
    if not usable:
        return 0.0
    total = 0.0
    for b in usable:
        hl = math.log(b.high / b.low) ** 2
        co = math.log(b.close / b.open) ** 2
        total += 0.5 * hl - (2.0 * math.log(2.0) - 1.0) * co
    return math.sqrt(max(total, 0.0) / len(usable))


def rogers_satchell(bars: list[Bar]) -> float:
    """Independent of drift, but still assumes no opening gap."""
    usable = [b for b in bars if b.high > 0 and b.low > 0 and b.open > 0 and b.close > 0]
    if not usable:
        return 0.0
    total = 0.0
    for b in usable:
        total += math.log(b.high / b.close) * math.log(b.high / b.open)
        total += math.log(b.low / b.close) * math.log(b.low / b.open)
    return math.sqrt(max(total, 0.0) / len(usable))


def yang_zhang(bars: list[Bar]) -> float:
    """Unbiased across opening gaps and independent of drift.

    Three components: the overnight jump from the previous close to this open,
    the open-to-close move, and the Rogers-Satchell within-bar term. Needs at
    least two bars, because the first has no previous close to gap from.
    """
    usable = [b for b in bars if b.high > 0 and b.low > 0 and b.open > 0 and b.close > 0]
    n = len(usable)
    if n < 2:
        return 0.0

    overnight = [math.log(b.open / prev.close) for prev, b in pairwise(usable)]
    open_close = [math.log(b.close / b.open) for b in usable[1:]]
    if not overnight:
        return 0.0

    def _var(values: list[float]) -> float:
        if len(values) < 2:
            return 0.0
        mean = sum(values) / len(values)
        return sum((v - mean) ** 2 for v in values) / (len(values) - 1)

    k = _k(len(overnight))
    rs = rogers_satchell(usable[1:]) ** 2
    return math.sqrt(max(_var(overnight) + k * _var(open_close) + (1.0 - k) * rs, 0.0))


@dataclass(slots=True)
class Ranges(Restorable):
    """A rolling window of bars, and the range estimates over them."""

    window: int = WINDOW
    warmup: int = WARMUP
    floor_bps: float = MIN_VOL_BPS
    _bars: list[Bar] = field(default_factory=list)

    def observe(self, open_: float, high: float, low: float, close: float) -> None:
        """Fold in one bar. Prices, in the order a candle is usually written."""
        if min(open_, high, low, close) <= 0:
            return
        self._bars.append(Bar(open=open_, high=high, low=low, close=close))
        if len(self._bars) > self.window:
            del self._bars[: len(self._bars) - self.window]

    @property
    def warm(self) -> bool:
        return len(self._bars) >= self.warmup

    def _as_bps(self, value: float) -> float:
        return max(value * 10_000, self.floor_bps) if value > 0 else self.floor_bps

    @property
    def bps(self) -> float:
        """Yang-Zhang, in basis points. The one to read if only reading one."""
        return self._as_bps(yang_zhang(self._bars))

    @property
    def parkinson_bps(self) -> float:
        return self._as_bps(parkinson(self._bars))

    @property
    def garman_klass_bps(self) -> float:
        return self._as_bps(garman_klass(self._bars))

    @property
    def rogers_satchell_bps(self) -> float:
        return self._as_bps(rogers_satchell(self._bars))
