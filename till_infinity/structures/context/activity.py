"""How busy a bar was, against how busy this instrument's bars usually are.

The closest independent estimate of fair value anybody trades on is a volume
profile: the price where the most business was done. This package estimates the
same quantity from where volatility turned, and the obvious question is whether
volume adds anything to it.

That question cannot be asked directly, and the reason is worth stating before
any of the arithmetic.

## What our "volume" actually is

TradingView's series carries `v`, and on most feeds it is **tick volume**: the
number of price changes in the bar, not the number of contracts. It is a proxy
for *activity*, and a decent one, but it is not size. Worse for our purposes it
is not comparable between venues - two brokers quoting the same instrument
publish different tick counts for the same minute, because they are counting
their own updates.

And spot FX has no consolidated volume at all. Of the fifteen instruments
tracked here, the crypto venues report real traded size, the futures stand-ins
(GC=F, SI=F, NQ=F, ES=F) report exchange volume, and the seven majors, gold and
silver report ticks or nothing.

So a raw volume term would mean a different thing per instrument, per venue,
and would be missing entirely for most of the book. Putting that into a feature
set whose whole premise is that gold and EURUSD are comparable would quietly
destroy the comparability.

## What is comparable

The **ratio** of a bar's activity to what this instrument's bars usually carry
on this timeframe. Whatever the units, and whoever is counting, "three times as
busy as normal" means the same thing on gold as on BTC. It is dimensionless by
construction, which is the standard every entry in `Features` is held to.

That is all this module produces: one exponential mean per instrument and
timeframe, and a share against it. A bar with no volume reported returns a
share of 1.0 - "ordinary" - so an instrument that reports nothing contributes a
constant and cannot skew anything it is compared against.

## It decides nothing

The share goes onto the touch features and the level signal, and is recorded
against outcomes. Whether busy touches resolve differently from quiet ones is
then answerable from our own resolutions, which is the only honest way to find
out - and the cheap version of that question, asked before anything is built on
the answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..state import Restorable

#: Bars before the mean is trusted. Below this the share is reported as 1.0,
#: because a ratio against two observations is not a ratio against anything.
WARMUP = 30

#: Half-life in bars, matching the volatility estimator's. Activity clusters
#: the way volatility does and for the same reasons, so it should forget at the
#: same rate.
HALF_LIFE = 60.0

#: A share this far from ordinary is almost always a data artefact - a venue
#: resetting its counter, a session gap counted as one bar - rather than a real
#: burst, and letting it through would put an outlier into a feature set the
#: kNN reads as distances.
MAX_SHARE = 20.0


def _alpha(half_life: float) -> float:
    return 1.0 - 0.5 ** (1.0 / max(half_life, 1e-9))


@dataclass(slots=True)
class Activity(Restorable):
    """One instrument-and-timeframe's typical bar."""

    half_life: float = HALF_LIFE
    warmup: int = WARMUP
    mean: float = 0.0
    seen: int = 0

    def update(self, volume: float) -> float:
        """Fold a bar in and return its share. 1.0 while warming or absent."""
        if volume is None or volume <= 0:
            return 1.0
        self.seen += 1
        if not self.mean:
            self.mean = volume
        else:
            self.mean += _alpha(self.half_life) * (volume - self.mean)
        return self.share(volume)

    def share(self, volume: float) -> float:
        if not volume or volume <= 0 or self.seen < self.warmup or self.mean <= 0:
            return 1.0
        return min(volume / self.mean, MAX_SHARE)

    @property
    def warm(self) -> bool:
        return self.seen >= self.warmup


@dataclass(slots=True)
class Book(Restorable):
    """Activity per instrument and timeframe.

    Split by timeframe as well as instrument, because a 1m bar and a 1h bar
    carry entirely different counts and pooling them would make the ratio
    describe the timeframe mix rather than the market.
    """

    half_life: float = HALF_LIFE
    _by_key: dict[tuple[str, str], Activity] = field(default_factory=dict)

    def of(self, feed: str, interval: str) -> Activity:
        key = (feed, interval)
        found = self._by_key.get(key)
        if found is None:
            found = self._by_key[key] = Activity(half_life=self.half_life)
        return found

    def update(self, feed: str, interval: str, volume: float) -> float:
        return self.of(feed, interval).update(volume)

    def share(self, feed: str, interval: str, volume: float) -> float:
        return self.of(feed, interval).share(volume)

    def feeds(self) -> list[str]:
        return sorted({feed for feed, _ in self._by_key})
