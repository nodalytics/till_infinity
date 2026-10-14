"""A range the current price sits inside, with liquidity-aware edges.

Asked for on 2026-10-14: *"statespace should be able to pick levels too, and a
range too, the current price should [be] inside [the] range, those ranges levels
can also act as key support/resistance levels, these levels should be liquidity
aware too"*.

## Why this formulation is buildable where "find the levels" was not

`docs/specs/2026-10-14-statespace-as-the-structures-library.md` recorded level
discovery as the one item blocked on **design** rather than effort, and the
obstacle is measured: `definitions-cannot-be-states` found that a mixture whose
centres are **free states collapses onto the data**, so a filter asked to
estimate where a level *is* estimates where the data happens to be.

A **range edge is not a free position.** It is defined by a share of
something - of the observations, or of the traded volume - so it is anchored by
construction, and the filter's job becomes estimating how far out that share
sits rather than guessing a price. That is the same move that made the forecast
band work, and it is why this is the version of the request that can be
measured.

## And the claim that these edges are support has already been refuted once

`research/docs/game-theory.md` tested the "levels hold" family and its verdict
was blunt: round numbers *"turn price no more than placebo levels"*, there is no
hunt at yesterday's high or low in FX - **66.2% against a placebo's 67.7%** -
and *"a trap's new extreme holds worse than a random price"*. The level magnet
effect is refuted in `research/docs/` as well.

So this module builds the range and **does not claim its edges are support.**
`research/ideas/range_levels.py` tests that separately, against the same
placebo standard those studies used, and the answer belongs in a doc rather
than in a docstring. A range is useful whether or not its edges hold: it is a
calibrated interval, and an interval is what a stop and a size are set from.

## Candlestick order flow, because there is no order book

Asked for on 2026-10-14: *"the levels should also be candlestick orderflow aware
since we don't have access to orderbook/l2 data"*. With OHLC there is one honest
distinction available, and `statespace-orderflow-from-bars.md` is what makes it
more than a convention:

* a price inside a bar's **body** was **accepted** - price traded through it and
  closed past it;
* a price inside a **wick** was **rejected** - price went there and came back
  within the bar.

That study measured the sign of exactly this and found it separates a real order
book from a generated one with no exceptions across nineteen classes: traded
markets close **nearer the middle of their range** than a matched random walk on
8 of 8 instruments, and every jump generator does the reverse. Rejection is what
a book does; a generator has no mechanism for it.

So each bar's volume is split: the part covering its body counts as acceptance
and the part covering its wicks as rejection. `weight` chooses which profile an
edge is taken from, and the three disagree by construction - a price can be
heavily traded *and* heavily rejected, which is what an absorbing level is
supposed to look like.

## Liquidity-aware means weighted by where trade happened

Each bar contributes its volume to the prices it covered, so the profile is
volume-at-price rather than a count of visits. Two edges follow from it and
they are different objects:

* the **value edges**, where a central share of the volume ends - the classic
  70% value area, which is a quantile and therefore anchored;
* the **thin edges**, the nearest prices on each side where volume per bin
  falls below a fraction of the mode. Volume profile's own claim is that price
  moves *through* thin prices and stalls at heavy ones, so a thin price is the
  honest candidate for where a range ends.

Both are reported, because they disagree and the disagreement is informative:
a value edge sitting far inside a thin edge says the range has a heavy shoulder.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

#: Share of volume inside the value area. The conventional 70%, kept because
#: changing it changes what the number means to anyone who has seen one before.
VALUE_SHARE = 0.70

#: A bin is "thin" below this fraction of the modal bin's volume.
THIN_SHARE = 0.25

#: Bins across the window. Enough that an edge is located to about a
#: fiftieth of the range, few enough that a bin has volume in it.
BINS = 50

#: Bars kept. A profile over a window this long is what the next few bars trade
#: against; much longer and it describes a market that has gone.
WINDOW = 300

#: Bars a profile needs before it reports anything. Below this the modal bin is
#: whichever one the first few bars happened to land in.
LEAST = 60


@dataclass(frozen=True, slots=True)
class Range:
    """A price range containing `price`, and the levels its edges imply."""

    price: float
    #: The heaviest-volume price in the window. Volume profile's "point of
    #: control", reported because it is the one level in this family that
    #: `game-theory.md` did not test and so is not yet refuted.
    centre: float
    #: Edges of the central `VALUE_SHARE` of volume.
    value_low: float
    value_high: float
    #: Nearest price each side where volume per bin falls under `THIN_SHARE`
    #: of the mode, or the window's extreme if it never does.
    thin_low: float
    thin_high: float
    #: Volume share in the bin each edge sits in, relative to the mode. A thin
    #: edge should be near `THIN_SHARE`; a value edge can be anything, and
    #: when it is heavy the range has a shoulder rather than a boundary.
    thin_low_share: float = 0.0
    thin_high_share: float = 0.0
    bars: int = 0

    @property
    def inside(self) -> bool:
        """Whether the current price sits inside the value edges.

        **Not guaranteed, and worth checking rather than assuming.** A value
        area is a central share of *past* volume; price can be outside it, and
        that is the ordinary meaning of "price has left value". A caller that
        needs the price bracketed should use the thin edges, which are taken
        from the current price outwards and so contain it by construction.
        """
        return self.value_low <= self.price <= self.value_high

    @property
    def width(self) -> float:
        return self.thin_high - self.thin_low

    @property
    def position(self) -> float:
        """Where price sits across the thin range, 0 at the low and 1 at the high."""
        span = self.width
        return (self.price - self.thin_low) / span if span > 0 else 0.5


@dataclass(slots=True)
class Profile:
    """Volume at price over a rolling window, and the range it implies."""

    window: int = WINDOW
    bins: int = BINS
    value_share: float = VALUE_SHARE
    thin_share: float = THIN_SHARE
    #: `(low, high, body low, body high, volume)` per bar, oldest first.
    _bars: list[tuple[float, float, float, float, float]] = field(default_factory=list)

    def observe(
        self,
        low: float,
        high: float,
        volume: float = 1.0,
        open_: float | None = None,
        close: float | None = None,
    ) -> None:
        """Fold in one bar. `volume` of 1.0 makes this a count of visits.

        `open_` and `close` are what make the acceptance and rejection profiles
        possible: without them every price in the bar is treated as body, which
        is the same as having no candlestick information at all.
        """
        low, high = (float(low), float(high)) if low <= high else (float(high), float(low))
        if not (math.isfinite(low) and math.isfinite(high)):
            return
        if open_ is None or close is None:
            body_low, body_high = low, high
        else:
            body_low, body_high = sorted((float(open_), float(close)))
            body_low = min(max(body_low, low), high)
            body_high = min(max(body_high, low), high)
        self._bars.append((low, high, body_low, body_high, max(float(volume), 0.0)))
        if len(self._bars) > self.window:
            del self._bars[: len(self._bars) - self.window]

    @property
    def bars(self) -> int:
        return len(self._bars)

    def histogram(self, weight: str = "volume") -> tuple[list[float], list[float]] | None:
        """`(bin centres, volume per bin)`, or `None` while warming.

        A bar spreads its volume evenly across the bins it covers, which is the
        standard construction and the only one available from OHLC: without
        ticks there is no way to know where inside the bar the volume went, and
        assuming it went to the close would put every bar's weight on one bin
        and call the result a profile.
        """
        if len(self._bars) < LEAST:
            return None
        if weight not in ("volume", "acceptance", "rejection"):
            raise ValueError(f"unknown weight {weight!r}")
        low = min(b[0] for b in self._bars)
        high = max(b[1] for b in self._bars)
        if not (high > low):
            return None
        step = (high - low) / self.bins
        weights = [0.0] * self.bins
        for bar_low, bar_high, body_low, body_high, volume in self._bars:
            first = min(int((bar_low - low) / step), self.bins - 1)
            last = min(int((bar_high - low) / step), self.bins - 1)
            share = volume / (last - first + 1)
            for k in range(first, last + 1):
                if weight != "volume":
                    bin_low = low + k * step
                    bin_high = bin_low + step
                    overlaps = bin_high >= body_low and bin_low <= body_high
                    if (weight == "acceptance") != overlaps:
                        continue
                weights[k] += share
        centres = [low + (k + 0.5) * step for k in range(self.bins)]
        return centres, weights

    def range_at(self, price: float, weight: str = "volume") -> Range | None:
        """The range containing `price`, or `None` while warming.

        `weight` picks the profile: all volume, only what was **accepted**
        (body), or only what was **rejected** (wick).
        """
        got = self.histogram(weight)
        if got is None:
            return None
        centres, weights = got
        total = sum(weights)
        if total <= 0:
            return None
        peak = max(range(len(weights)), key=lambda k: weights[k])
        mode = weights[peak]

        # The value area, grown out from the mode until it holds its share.
        low_at = high_at = peak
        held = mode
        while held < self.value_share * total and (low_at > 0 or high_at < len(weights) - 1):
            below = weights[low_at - 1] if low_at > 0 else -1.0
            above = weights[high_at + 1] if high_at < len(weights) - 1 else -1.0
            if above >= below:
                high_at += 1
                held += above
            else:
                low_at -= 1
                held += below

        # The thin edges, walked out from the **current price** so they bracket
        # it by construction rather than by luck.
        here = min(range(len(centres)), key=lambda k: abs(centres[k] - float(price)))
        floor = self.thin_share * mode
        # **Walk out from the bin *beside* the current one, not from it.**
        # Starting at `here` and stopping on the first thin bin returns `here`
        # twice whenever price is itself in a thin bin - which is exactly when
        # price has just moved somewhere little was traded - giving a
        # zero-width range that does not contain the price it was asked about.
        down = here
        while down > 0:
            down -= 1
            if weights[down] < floor:
                break
        up = here
        while up < len(weights) - 1:
            up += 1
            if weights[up] < floor:
                break
        # And containment is guaranteed rather than hoped for: these are bin
        # centres, so the nearest one can sit the wrong side of the price.
        low_edge = min(centres[down], float(price))
        high_edge = max(centres[up], float(price))
        return Range(
            price=float(price),
            centre=centres[peak],
            value_low=centres[low_at],
            value_high=centres[high_at],
            thin_low=low_edge,
            thin_high=high_edge,
            thin_low_share=weights[down] / mode if mode > 0 else 0.0,
            thin_high_share=weights[up] / mode if mode > 0 else 0.0,
            bars=len(self._bars),
        )
