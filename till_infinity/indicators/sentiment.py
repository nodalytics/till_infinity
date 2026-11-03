"""Fear and greed, from bars alone, with the parts kept separate on purpose.

The published fear-and-greed indices are composites of things this desk does
not have: put/call ratios, market breadth, junk-bond demand, safe-haven flows,
social-media volume. None of that is computable from OHLCV, so this is **not**
a reimplementation of one and should not be compared to one.

What is computable from bars is the thing those indices are proxying for: a
market falling fast with ranges opening up, against one grinding up with
ranges closing in. That is a volatility reading and a direction reading, and
the whole design of this module follows from one fact about them:

**On this desk the volatility half is large and the direction half is closed.**
`relationships-are-contemporaneous` records that volatility and tails are huge
while every lagged measure is null. `direction-is-closed-not-just-null` records
that the direction gate finds a *planted* drift at z +2.90 and earns 2% of a
spread. A single fear-and-greed number mixes the two, so a claim made on it
cannot be attributed to either - and the honest prediction is that any level
or signal quality it appears to carry is the volatility term, which
`topology-restates-volatility` says is already removed by stratifying.

So `parts` exposes every component, and `volatile` and `directional` expose
the two halves separately. **Test the halves, not the composite.** A result on
`reading` alone is uninterpretable by construction.

## Why the weights are equal and not fitted

A composite is a weighted sum, and `only-the-sign-survives-into-a-weighted-sum`
holds that activation, scale and per-term offset are all rank identities within
one. `fit-on-the-edge-not-the-raw-score` measured fitted weights beating
hand-tuned ones on AUC 0.604 against 0.556 while **losing on edge, +0.002
against +0.019**. So fitting these weights is predicted null and is not
offered; the information, if any, is in the components.

## What is deliberately left out

**Volume.** The store's volume column is unverified, an FX bar's figure is
tick count rather than traded size, and several feeds carry zero. A component
present on some feeds and absent on others makes the composite incomparable
across feeds while still returning a number, which is the shape of a bug
nobody sees. If volume is wanted it belongs in its own reading with its own
per-feed validity check.

**Any scaling fitted over the whole sample.** Every window here is trailing
and the readings are bounded by construction, so there is no normaliser that
has seen the future.
"""

from __future__ import annotations

import statistics
from collections import deque
from enum import StrEnum
from typing import Any

from nautilus_trader.indicators.base import Indicator
from nautilus_trader.model.data import Bar

NANOS = 1_000_000_000

#: Bars in the trailing window. Sixty, so a reading exists within a session on
#: an hourly feed and within a quarter of a day at 15m.
SPAN = 60

#: The fewest bars that will produce a reading. A share of down closes over
#: three bars takes four values and a semivariance over three is noise, so a
#: reading before this would be a number without a measurement behind it.
WARMUP = 20


class Mood(StrEnum):
    """A label for a reading, for logs and journals rather than for maths.

    Thresholds are **conventional and not measured**: nothing on this desk has
    established that -0.5 is a meaningful boundary. They exist so a journal
    entry reads "fear" rather than "-0.63", and no gate should key on them.
    """

    FEAR = "fear"
    CALM = "calm"
    GREED = "greed"


#: The components, and which half each belongs to.
#:
#: **This split is the point of the module.** `direction` components are the
#: ones measured closed here; `volatility` components are the ones measured
#: large. A claim has to say which half it rests on.
HALVES: dict[str, str] = {
    "position": "direction",
    "pressure": "direction",
    "conviction": "direction",
    "expansion": "volatility",
    "skew": "volatility",
}


def _clamp(value: float) -> float:
    return max(-1.0, min(1.0, value))


class FearGreed(Indicator):
    """A bounded fear-and-greed reading from bars, with its parts.

    Registered with `Actor.register_indicator_for_bars` or the identical
    method on `Strategy`.

    **-1 is fear, +1 is greed, 0 is neither**, which is the convention the
    statespace signal already uses, so the two can be compared without a
    mapping that somebody has to remember.
    """

    def __init__(self, *, span: int = SPAN, warmup: int = WARMUP) -> None:
        if span < 3:
            raise ValueError(f"span={span} cannot carry a trailing distribution")
        if warmup < 3 or warmup > span:
            raise ValueError(
                f"warmup={warmup} must be between 3 and span={span}: below three "
                f"there is no distribution, and above the span it never fills"
            )
        super().__init__([span, warmup])
        self.span = int(span)
        self.warmup = int(warmup)
        self._highs: deque[float] = deque(maxlen=self.span)
        self._lows: deque[float] = deque(maxlen=self.span)
        self._closes: deque[float] = deque(maxlen=self.span)
        self._ranges: deque[float] = deque(maxlen=self.span)
        self._bodies: deque[float] = deque(maxlen=self.span)
        self._returns: deque[float] = deque(maxlen=self.span)
        self.parts: dict[str, float] = {}
        self.when = 0.0

    # ----------------------------------------------------------------- feeding

    def handle_bar(self, bar: Bar) -> None:
        """Nautilus's entry point. `ts_event` is the bar's close."""
        self.update_raw(
            float(bar.open),
            float(bar.high),
            float(bar.low),
            float(bar.close),
            bar.ts_event / NANOS,
        )

    def update_raw(
        self,
        open_: float,
        high: float,
        low: float,
        close: float,
        when: float = 0.0,
    ) -> None:
        """Fold one bar in and recompute every part.

        A bar with a non-positive price or an inverted range is refused rather
        than folded: it is bad data, and averaging it in would move a bounded
        reading without any way to see that it had.
        """
        if close <= 0.0 or high < low:
            return
        self.when = when
        previous = self._closes[-1] if self._closes else 0.0
        self._highs.append(high)
        self._lows.append(low)
        self._ranges.append(max(0.0, high - low))
        self._bodies.append(abs(close - open_))
        if previous > 0.0:
            self._returns.append((close - previous) / previous)
        self._closes.append(close)
        self._set_has_inputs(True)

        if len(self._closes) < self.warmup:
            return
        self.parts = {
            "position": self._position(),
            "pressure": self._pressure(),
            "conviction": self._conviction(),
            "expansion": self._expansion(),
            "skew": self._skew(),
        }
        self._set_initialized(True)

    # -------------------------------------------------------------- the parts

    def _position(self) -> float:
        """Where the close sits in the trailing range. **Direction.**

        A drawdown from the window's high is the fear reading most people
        recognise; this is the two-sided version, so a close at the high reads
        +1 and one at the low reads -1.
        """
        top, bottom = max(self._highs), min(self._lows)
        width = top - bottom
        if width <= 0.0:
            return 0.0
        return _clamp(2.0 * (self._closes[-1] - bottom) / width - 1.0)

    def _pressure(self) -> float:
        """The balance of up and down closes over the window. **Direction.**

        A share rather than a sum of returns, so one large bar cannot carry
        it - that would make this a second reading of the same move
        `position` already measures.
        """
        if not self._returns:
            return 0.0
        ups = sum(1 for r in self._returns if r > 0.0)
        downs = sum(1 for r in self._returns if r < 0.0)
        decided = ups + downs
        return (ups - downs) / decided if decided else 0.0

    def _conviction(self) -> float:
        """Body as a share of range, signed by the window's net move.
        **Direction**, because the sign is what makes it fear or greed.

        A market closing near its extremes is acting with conviction; which
        way is the net move's business. Unsigned this would be a volatility
        component, and it is kept signed so the split in `HALVES` is honest
        about what it contributes.
        """
        pairs = [(b, r) for b, r in zip(self._bodies, self._ranges, strict=True) if r > 0.0]
        if not pairs:
            return 0.0
        share = sum(b / r for b, r in pairs) / len(pairs)
        net = self._closes[-1] - self._closes[0]
        if net == 0.0:
            return 0.0
        return _clamp(share * (1.0 if net > 0.0 else -1.0))

    def _expansion(self) -> float:
        """Recent range against the window's own median. **Volatility.**

        Negative when ranges are opening up, because expansion is the fear
        side - which is a convention, and the reason `volatile` is reported
        separately rather than folded in silently.

        Measured on the last fifth of the window against the whole, so it is a
        change in regime rather than one bar's size.
        """
        if len(self._ranges) < self.warmup:
            return 0.0
        middle = statistics.median(self._ranges)
        if middle <= 0.0:
            return 0.0
        recent = max(1, len(self._ranges) // 5)
        now = statistics.fmean(list(self._ranges)[-recent:])
        # **`now` as well as `middle`, and the second guard was missing.**
        # A window whose median range is positive while its *last fifth* is
        # all zero-range bars gives `log2(0 / middle)` - a `ValueError: math
        # domain error` raised straight into Nautilus's bar handler on any
        # feed that goes flat for a fifth of the window. Gold's own daily
        # history carries three such bars. Twelve flat bars at the default
        # span was enough to take the desk down.
        if now <= 0.0:
            return 0.0
        # A ratio of 1 reads 0, 2 reads -1, 0.5 reads +1: symmetric in the log
        # so a doubling and a halving are the same distance from neutral.
        import math

        return _clamp(-math.log2(now / middle))

    def _skew(self) -> float:
        """Downside against upside realised volatility. **Volatility.**

        The leverage effect: a down move raises volatility more than an up
        move of the same size, which is a volatility asymmetry rather than a
        direction claim, and is the component here with the best prior.
        Negative when the downside half is the larger.
        """
        downs = [r * r for r in self._returns if r < 0.0]
        ups = [r * r for r in self._returns if r > 0.0]
        if not downs or not ups:
            return 0.0
        down = statistics.fmean(downs) ** 0.5
        up = statistics.fmean(ups) ** 0.5
        total = down + up
        return _clamp((up - down) / total) if total > 0.0 else 0.0

    # ------------------------------------------------------------- the reading

    def _mean(self, half: str) -> float:
        picked = [v for name, v in self.parts.items() if HALVES[name] == half]
        return statistics.fmean(picked) if picked else 0.0

    @property
    def volatile(self) -> float:
        """The volatility half alone. The one with the measured prior."""
        return self._mean("volatility")

    @property
    def directional(self) -> float:
        """The direction half alone. Measured closed on this desk."""
        return self._mean("direction")

    @property
    def reading(self) -> float:
        """The composite, equally weighted. **Report the halves instead.**

        Kept because a label and a journal line need one number, and because
        refusing to produce it would mean every caller inventing its own
        weighting. A claim resting on this is uninterpretable: it cannot say
        whether it rests on the half that is measured large or the half that
        is measured closed.
        """
        return statistics.fmean(self.parts.values()) if self.parts else 0.0

    def mood(self, *, edge: float = 0.5) -> Mood:
        """A label for a log. `edge` is conventional and not measured."""
        value = self.reading
        if value <= -edge:
            return Mood.FEAR
        return Mood.GREED if value >= edge else Mood.CALM

    def _reset(self) -> None:
        for buffer in (
            self._highs,
            self._lows,
            self._closes,
            self._ranges,
            self._bodies,
            self._returns,
        ):
            buffer.clear()
        self.parts = {}
        self.when = 0.0
        self._set_has_inputs(False)
        self._set_initialized(False)

    def handle_quote_tick(self, tick: Any) -> None:
        """Refused rather than ignored: every part here needs a bar's range or
        its body, and a quote carries neither."""
        raise NotImplementedError(
            "FearGreed needs bars - a range and a body - so register it with "
            "register_indicator_for_bars, not for quote ticks."
        )
