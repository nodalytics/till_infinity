"""The level engine: bars in, levels and directional calls out.

Ties the pieces together. Bars arrive from the bus; the engine keeps a rolling
window per instrument, re-forms levels from the perceptually important points
in it, tracks price against those levels, and produces a call whenever price
comes into one.

Two things it is careful about, because both are easy to get wrong in ways that
do not show up until the results are being trusted:

**Levels are formed only from confirmed swings.** A turning point is not
knowable as one until the bars after it have printed, so `pips.as_of` filters
to what was visible. Without that the engine would draw levels through swings
nobody could have seen and then congratulate itself for respecting them.

**Levels persist across re-forming.** Re-deriving from a window would discard
the touch history that makes a level worth anything, so new candidates are
merged into the existing set rather than replacing it. A level rediscovered is
evidence about an old level, not a new one.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field

from ..logging import get_logger
from . import levels as lv
from . import pips, reactions
from .models import Shape, Signal
from .volatility import Book as VolBook

log = get_logger(__name__)

#: Bars kept per instrument. Enough to hold the swings that matter on a 5m
#: chart without the window itself becoming the thing being modelled.
WINDOW = 500

#: Perceptually important points pulled from the window. Roughly one per ten
#: bars: fewer and real swings are missed, more and noise becomes a level.
PIP_COUNT = 50

#: Re-form levels this often, in bars. Every bar would be wasted work — the
#: swings barely change — and never would let the set go stale.
REFORM_EVERY = 20

#: Intervals levels are built from. Levels are a structure of the chart people
#: look at, and nobody draws them from tick data.
LEVEL_INTERVALS: tuple[str, ...] = ("5m", "15m", "1h")


@dataclass(slots=True)
class Series:
    """A rolling window of one instrument at one interval."""

    feed: str
    interval: str
    times: deque[int] = field(default_factory=lambda: deque(maxlen=WINDOW))
    closes: deque[float] = field(default_factory=lambda: deque(maxlen=WINDOW))
    highs: deque[float] = field(default_factory=lambda: deque(maxlen=WINDOW))
    lows: deque[float] = field(default_factory=lambda: deque(maxlen=WINDOW))
    since_reform: int = 0

    def add(self, when: int, high: float, low: float, close: float) -> None:
        # A bar arriving for a time already held is a correction, not a new bar.
        if self.times and when == self.times[-1]:
            self.highs[-1], self.lows[-1], self.closes[-1] = high, low, close
            return
        self.times.append(when)
        self.highs.append(high)
        self.lows.append(low)
        self.closes.append(close)
        self.since_reform += 1

    @property
    def ready(self) -> bool:
        return len(self.closes) >= pips.MIN_POINTS * 4

    @property
    def due(self) -> bool:
        return self.since_reform >= REFORM_EVERY


@dataclass(slots=True)
class Call:
    """A directional call at a level, with everything behind it."""

    feed: str
    interval: str
    level: lv.Level
    inference: reactions.Inference
    price: float
    time: float

    def to_signal(self, vol) -> Signal:
        detail = (
            f"{self.inference.direction} from {self.inference.side} at "
            f"{self.level.price:.5g} — p={self.inference.probability_up:.0%} "
            f"vs {self.inference.base_rate_up:.0%} base, "
            f"push {self.inference.expected_push:+.2f}v"
        )
        return Signal(
            shape=Shape.LEVEL,
            feed=self.feed,
            venue="consensus",
            score=abs(self.inference.edge),
            detail=detail,
            features={
                "level": self.level.price,
                "probability_up": self.inference.probability_up,
                "expected_push_vol": self.inference.expected_push,
                "base_rate_up": self.inference.base_rate_up,
                "edge": self.inference.edge,
                "own_touches": float(self.inference.own_touches),
                "neighbours": float(self.inference.neighbours),
                "strength": self.level.strength(self.time, vol),
            },
            interval=self.interval,
            time=self.time,
        )


class Engine:
    """Levels and directional calls for every instrument at once."""

    def __init__(
        self,
        *,
        window: int = WINDOW,
        pip_count: int = PIP_COUNT,
        intervals: tuple[str, ...] = LEVEL_INTERVALS,
        horizon: float = 3600.0,
    ) -> None:
        self.window = window
        self.pip_count = pip_count
        self.intervals = intervals
        self.vol = VolBook()
        self.tracker = reactions.Tracker(horizon=horizon)
        self._series: dict[tuple[str, str], Series] = {}
        self._levels: dict[tuple[str, str], list[lv.Level]] = {}
        self.calls = 0

    # --------------------------------------------------------------- levels

    def series(self, feed: str, interval: str) -> Series:
        key = (feed, interval)
        found = self._series.get(key)
        if found is None:
            found = self._series[key] = Series(feed, interval)
        return found

    def levels(self, feed: str, interval: str = "") -> list[lv.Level]:
        if interval:
            return list(self._levels.get((feed, interval), []))
        return [
            level
            for (this_feed, _), found in self._levels.items()
            if this_feed == feed
            for level in found
        ]

    def reform(self, series: Series, when: float) -> list[lv.Level]:
        """Re-derive levels from the confirmed swings in the window."""
        vol = self.vol.of(series.feed)
        found = pips.points(list(series.times), list(series.closes), self.pip_count)
        visible = pips.as_of(found, when)
        candidates = lv.form(series.feed, series.interval, pips.turns(visible), vol)
        key = (series.feed, series.interval)
        merged = lv.merge(self._levels.get(key, []), candidates, vol)
        self._levels[key] = merged
        series.since_reform = 0
        return merged

    # -------------------------------------------------------------- feeding

    def observe_bar(self, payload: dict) -> list[Call]:
        """One `prices.bars` message. Returns any calls it produced."""
        feed = str(payload.get("feed") or "")
        interval = str(payload.get("interval") or "")
        if not feed or interval not in self.intervals:
            return []
        close = payload.get("close")
        if not isinstance(close, int | float) or not close:
            return []
        when = int(payload.get("time") or time.time())
        high = float(payload.get("high") or close)
        low = float(payload.get("low") or close)

        series = self.series(feed, interval)
        series.add(when, high, low, float(close))
        vol = self.vol.of(feed)
        vol.update(float(close))
        if not series.ready:
            return []
        if series.due or not self._levels.get((feed, interval)):
            self.reform(series, when)
        return self.check(feed, interval, float(close), when)

    def observe_quote(self, payload: dict) -> list[Call]:
        """A quote moves price against existing levels without re-forming them.

        Quotes are what make a touch detectable in time to matter — waiting for
        a 5m bar to close means reporting the interaction after it happened.
        """
        feed = str(payload.get("feed") or "")
        mid = payload.get("mid")
        if not feed or not isinstance(mid, int | float) or not mid:
            return []
        when = float(payload.get("time") or time.time())
        vol = self.vol.of(feed)
        vol.update(float(mid))
        calls: list[Call] = []
        for interval in self.intervals:
            calls += self.check(feed, interval, float(mid), when)
        return calls

    # ------------------------------------------------------------- touching

    def check(self, feed: str, interval: str, price: float, when: float) -> list[Call]:
        """Advance every open interaction, and open one where price has arrived."""
        vol = self.vol.of(feed)
        if not vol.warm:
            return []
        calls: list[Call] = []
        for level in self._levels.get((feed, interval), []):
            open_touch = self.tracker.open_touch(level)
            if open_touch is not None:
                done = self.tracker.update(level, price, vol, when)
                if done is not None:
                    # Where price actually turned is the better observation of
                    # where the level is than where it first arrived.
                    level.observe_touch(done.extreme, vol, when)
                    log.debug("level %s %.5g resolved %s", feed, level.price, done.outcome)
                continue

            if not level.contains(price, vol):
                continue
            side = self._approach(level, price)
            features = reactions.features_for(
                level, side, price, vol, approach_vol=self._speed(feed, interval, vol), when=when
            )
            self.tracker.begin(level, price, features, when)
            inference = reactions.infer(level, side, features, self.tracker.memory)
            calls.append(
                Call(
                    feed=feed,
                    interval=interval,
                    level=level,
                    inference=inference,
                    price=price,
                    time=when,
                )
            )
            self.calls += 1
        self.tracker.expire(when)
        return calls

    def _approach(self, level: lv.Level, price: float) -> lv.Side:
        """Which side price came from — the previous bar, not the current one.

        Using the current price would be circular: inside the zone, price is by
        definition next to the level, and the question is where it came *from*.
        """
        series = self._series.get((level.feed, level.interval))
        if series is not None and len(series.closes) >= 2:
            return level.side_of(series.closes[-2])
        return level.side_of(price)

    def _speed(self, feed: str, interval: str, vol) -> float:
        """How fast price is moving, in volatility units per bar."""
        series = self._series.get((feed, interval))
        if series is None or len(series.closes) < 2:
            return 0.0
        previous, latest = series.closes[-2], series.closes[-1]
        if not previous:
            return 0.0
        return abs((latest - previous) / previous * 10_000) / vol.bps

    # ---------------------------------------------------------------- state

    def summary(self) -> list[dict]:
        """What the engine knows, for `structures levels`."""
        rows = []
        for (feed, interval), found in sorted(self._levels.items()):
            vol = self.vol.of(feed)
            for level in sorted(found, key=lambda level: level.price):
                rows.append(level.to_dict(vol))
                rows[-1]["interval"] = interval
        return rows
