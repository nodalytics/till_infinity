"""`Q` from the bar's range, not from its closes.

`candle-screen.md` measured this and it is the one change the screen produced:
the ratio of a **range-based** volatility estimator to the close-to-close one
predicts whether forward volatility rises, beyond current volatility.

| arm | raw AUC | within strata of current volatility | feeds agreeing |
| --- | ---: | ---: | --- |
| fx | 0.7077 | **0.6484** | 100% of 20 |
| equity | 0.7379 | **0.6671** | **98% of 371** |
| block-shuffled fx | 0.6732 | 0.5448 | 100% of 20 |

Garman-Klass, Parkinson and Rogers-Satchell agree to three decimals, because
they measure the same thing: how much of the variance happened **inside** the
bar rather than between its closes. And it strengthens as the window shortens -
0.6232 at a hundred bars, 0.6484 at forty - which is the regime a filter's
`Q(dt)` update actually lives in.

The surrogate matters for reading it. Block-shuffling keeps each bar's own
geometry and destroys the ordering, so an estimator that is merely **more
efficient** should keep part of its edge there, and it does: 0.5448 against
0.6484. The gap between those two is the part that needs the real series.

## Why a mean-one ratio and not an estimate

`Driven` scales a member's existing process noise. So this supplies a
**multiplier**: how much more variance the bar's range implies than its closes
did. Normalised to average one, by division by an exponential mean of itself,
exactly as `pacing.Profile.factor` does - because what is being compared is the
**shape** of the multiplier and not its level, and a multiplier whose mean is
not one changes the member's average process noise as well as varying it. On FX
volume that mistake measured 2.23 and turned +1734 into +2365 nats of pure
artefact.

## It is a variance multiplier, which is the easy mistake here

`gk_cc` as measured is a ratio of **standard deviations**. `Driven.clock` and
`Driven.control` both take a **variance** factor - its own docstring says a
caller passing a standard-deviation profile would under-drive every busy hour
by its own square. So the ratio is squared before it leaves this module, and
the tests assert it: a bar whose range implies twice the close-to-close
*volatility* has to arrive as a factor of four.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

#: Parkinson's constant: `1 / (4 ln 2)`.
_PARKINSON = 1.0 / (4.0 * math.log(2.0))
#: Garman-Klass's second coefficient: `2 ln 2 - 1`.
_GK = 2.0 * math.log(2.0) - 1.0

ESTIMATORS = ("garman_klass", "parkinson", "rogers_satchell")
#: Which estimator drives the ratio. Garman-Klass measured highest - 0.7077
#: raw, 0.6484 within strata - but the three agree to three decimals, so this
#: is a knob rather than a finding.
DEFAULT = "garman_klass"


def parkinson(high: float, low: float) -> float:
    """Per-bar variance from the high-low range alone."""
    if not (high > 0 and low > 0 and high >= low):
        return 0.0
    return _PARKINSON * math.log(high / low) ** 2


def garman_klass(open_: float, high: float, low: float, close: float) -> float:
    """Per-bar variance from the whole bar, which is the most efficient of these."""
    if not (open_ > 0 and high > 0 and low > 0 and close > 0 and high >= low):
        return 0.0
    span = math.log(high / low)
    body = math.log(close / open_)
    return max(0.5 * span * span - _GK * body * body, 0.0)


def rogers_satchell(open_: float, high: float, low: float, close: float) -> float:
    """Per-bar variance that stays unbiased when the bar has drift in it."""
    if not (open_ > 0 and high > 0 and low > 0 and close > 0 and high >= low):
        return 0.0
    return max(
        math.log(high / close) * math.log(high / open_)
        + math.log(low / close) * math.log(low / open_),
        0.0,
    )


@dataclass(slots=True)
class Span:
    """The range-implied variance multiplier for `Driven.control`.

    Fed one bar at a time. `factor()` returns a variance multiplier averaging
    one, which is what `Driven` multiplies its lever by.

    `half_life` smooths the two variance estimates; `memory` is the slower mean
    the ratio is divided by. The second has to be the slower of the two or the
    normaliser tracks the signal and divides it out.
    """

    estimator: str = DEFAULT
    #: Bars of half-life for the two variance estimates.
    half_life: float = 40.0
    #: Bars of half-life for the mean the ratio is normalised against. Forty
    #: was where the measured edge was strongest; the normaliser has to be
    #: much slower than that to leave the signal in.
    memory: float = 2000.0
    #: Smallest and largest the factor may be. A multiplier that can reach zero
    #: is a state that cannot move; one that is unbounded hands a single
    #: malformed bar the whole filter.
    low: float = 0.25
    high: float = 4.0

    _span_var: float = field(default=0.0, repr=False)
    _close_var: float = field(default=0.0, repr=False)
    _mean_ratio: float = field(default=0.0, repr=False)
    _previous: float = field(default=0.0, repr=False)
    _seen: int = field(default=0, repr=False)

    def __post_init__(self) -> None:
        if self.estimator not in ESTIMATORS:
            raise ValueError(f"estimator must be one of {ESTIMATORS}, got {self.estimator!r}")
        if not self.memory > self.half_life:
            raise ValueError("memory must be slower than half_life or it divides out the signal")

    @staticmethod
    def _alpha(half_life: float) -> float:
        return 1.0 - 0.5 ** (1.0 / max(half_life, 1e-9))

    def observe(self, open_: float, high: float, low: float, close: float) -> None:
        """Take one bar. Bars with a non-positive price or an inverted range are dropped."""
        if self.estimator == "parkinson":
            span = parkinson(high, low)
        elif self.estimator == "rogers_satchell":
            span = rogers_satchell(open_, high, low, close)
        else:
            span = garman_klass(open_, high, low, close)
        if not math.isfinite(span) or span <= 0 or not close > 0:
            return
        # Close-to-close needs the previous close, so the first bar contributes
        # to the range estimate and only the second starts the denominator.
        if self._previous > 0:
            step = math.log(close / self._previous)
            closed = step * step
            if math.isfinite(closed):
                alpha = self._alpha(self.half_life)
                self._span_var += alpha * (span - self._span_var)
                self._close_var += alpha * (closed - self._close_var)
                self._seen += 1
                if self._close_var > 0:
                    ratio = self._span_var / self._close_var
                    if math.isfinite(ratio) and ratio > 0:
                        slow = self._alpha(self.memory)
                        if self._mean_ratio <= 0:
                            self._mean_ratio = ratio
                        else:
                            self._mean_ratio += slow * (ratio - self._mean_ratio)
        self._previous = close

    @property
    def ready(self) -> bool:
        """Whether enough bars have arrived for the ratio to mean anything."""
        return self._seen >= int(self.half_life) and self._close_var > 0 and self._mean_ratio > 0

    def ratio(self) -> float:
        """The raw variance ratio, un-normalised. For diagnostics, not for `Driven`."""
        if not self.ready:
            return 1.0
        return self._span_var / self._close_var

    def factor(self) -> float:
        """The **variance** multiplier for this bar, averaging one.

        Already squared relative to the measured `gk_cc`, which is a ratio of
        standard deviations: this returns a ratio of variances, which is what
        `Driven` wants. A bar implying twice the close-to-close volatility
        arrives here as four.
        """
        if not self.ready:
            return 1.0
        got = self.ratio() / self._mean_ratio
        if not math.isfinite(got) or got <= 0:
            return 1.0
        return min(max(got, self.low), self.high)
