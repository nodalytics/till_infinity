"""Key price levels: where they are, and what they do when price arrives.

A level is not a line on a chart. It is a **latent state observed noisily**:
price turned somewhere near it a dozen times, never at exactly the same place,
and each of those turns is one noisy measurement of where the level actually
sits. That framing decides most of the design.

## The level is a Kalman state

Each touch updates a 1D Kalman filter whose state is the level's price and
whose transition is a slow random walk — levels do drift, slowly, as the market
repositions around them.

This is what gives the level its ability to be pushed up or down by what price
actually does, without anyone choosing a smoothing constant. The Kalman gain
weights a new touch by how uncertain the level currently is against how noisy
that observation is, so a level with twenty consistent touches barely moves for
the twenty-first while a fresh level moves a long way. An exponential average
needs an alpha picked in advance and is wrong at both ends of that range.

The posterior variance is not a by-product either: **it is the zone**. A level
we are confident about is a thin band; a level inferred from three scattered
touches is a wide one. The width comes from the same arithmetic as the centre.

## A level does different things from different sides

The important asymmetry. The same price met from below and met from above are
two different objects: one is a ceiling being tested, the other a floor. What
matters is not "does the level hold" but "given price arrived from *this* side,
which way does it get pushed, and how hard".

So every statistic here is kept **per approach side**, and the answer is a
direction with a magnitude rather than a hold-or-break bit.

## Everything is in volatility units

A 20bps push is enormous in a quiet hour and noise in a violent one. Storing
raw basis points would make a level's history incomparable with its own past
the moment the regime changed. Distances, zone widths and pushes are all
divided by current volatility, which is what lets a level learned in January
still mean something in June — and what lets gold and EURUSD share one model.
"""

from __future__ import annotations

import math
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from .pips import Point
from .volatility import Volatility

#: How wide a level's zone is, as a multiple of its own uncertainty. Two
#: standard deviations: price inside this band is touching the level in any
#: sense the data can distinguish.
ZONE_SIGMA = 2.0

#: A zone is never narrower than this many volatility units, however confident
#: the filter becomes. A band tighter than a typical move is a band price
#: crosses by accident, and every crossing would count as a touch.
MIN_ZONE_VOL = 0.35

#: ...and never wider than this, however scattered the touches. Past this the
#: "level" is a region, and a region that wide predicts nothing.
MAX_ZONE_VOL = 3.0

#: How far price must travel away from a level, in volatility units, before the
#: interaction counts as resolved rather than still in progress.
RESOLVE_VOL = 1.5

#: How far price must come back off its deepest point, in volatility units,
#: before the leg in is treated as over and the origin is fixed.
#:
#: The legs meeting at an origin are *runs*, and a run survives noise: a single
#: observation that fails to extend the move is not a departure, it is a pause.
#: Fixing the origin on the first such tick makes the origin a property of the
#: sampling rate — the finer the timeframe, the earlier some tick fails to
#: extend, so the same structure gets a different origin on every timeframe and
#: the multi-timeframe fusion then spends its precision reconciling an artefact.
ARRIVAL_RUN_VOL = 0.5

#: The same, for the leg *out*. A separate constant because the two are not the
#: same question and only looked like one: the arrival threshold decides where
#: the level *is*, and being wrong moves every statistic the level owns. The
#: departure threshold decides how much of the move that followed counts as
#: this reaction, and being wrong changes one feature. They are equal today
#: because nothing yet says they should differ — but one shared constant also
#: made the departure rule impossible to test in isolation, since disabling it
#: disabled the arrival rule first.
DEPARTURE_RUN_VOL = 0.5

#: How far price must get from a level, in volatility units, before another
#: interaction can begin. Leaving the *zone* is not enough: an edge crossed by a
#: hundredth of a unit is noise, and counting each crossing turns one
#: consolidation into dozens of turns. This is the difference between "price
#: left" and "price went away", and only the second is a new approach.
REARM_VOL = 1.0

#: How far beyond a level price must close for a break rather than a wick.
BREAK_VOL = 0.75

#: How far back through a level a broken-out price must come for the break to
#: have been a trap. Measured from the level, on the side price started from,
#: so a drift back into the zone is not enough — it has to give it all back.
TRAP_VOL = 0.5

#: How long a break stays provisional, in seconds. A break is not a break until
#: it survives; before this elapses the outcome is genuinely not yet known.
TRAP_WINDOW = 1_800.0

#: Bars after a break within which a return counts as a back check rather than
#: an unrelated visit. Scaled by timeframe, because "recently" on a weekly
#: chart and on a five-minute one are different amounts of time.
BACKCHECK_BARS = 30.0

#: How far beyond the flipped level a stop belongs, in volatility units, on top
#: of the zone itself. The zone is where price can sit and still be respecting
#: the level; the stop has to be outside it or it is inside the noise.
STOP_BUFFER_VOL = 0.5

#: Process noise per hour, in volatility units. Levels drift slowly; this is
#: what stops a filter with many observations from freezing solid.
DRIFT_VOL_PER_HOUR = 0.02

#: Touches needed before a level's own history is worth more than its
#: neighbours'. Below this, inference leans on kNN over similar levels.
CONFIDENT_TOUCHES = 5

#: How long one bar of each timeframe lasts. Needed here because evidence
#: decays in *time* while a level lives on a timeframe, and the two only line
#: up if the conversion is written down.
SECONDS: dict[str, float] = {
    "1m": 60.0,
    "3m": 180.0,
    "5m": 300.0,
    "15m": 900.0,
    "30m": 1_800.0,
    "1h": 3_600.0,
    "2h": 7_200.0,
    "4h": 14_400.0,
    "1d": 86_400.0,
    "daily": 86_400.0,
    "1w": 604_800.0,
    "weekly": 604_800.0,
}

#: Bars of evidence half-life. Anchored to the window a level is formed from
#: (500 bars), so evidence halves over roughly half the history the timeframe
#: can see.
HALF_LIFE_BARS = 250.0

#: Fallback for a timeframe with no duration on record.
TOUCH_HALF_LIFE_DAYS = 21.0


def half_life_days(interval: str) -> float:
    """How fast a level's evidence should fade, for its timeframe.

    A single constant cannot serve both ends. Twenty-one days is far too long
    for a 5m level — behaviour from three weeks ago on a five-minute chart is
    not evidence about now — and far too short for a weekly one, which might
    only be tested a handful of times a year and would have forgotten each
    touch before the next arrived.

    Anchoring to the window instead makes it self-scaling: evidence halves over
    about half the history that timeframe can see. That works out at under a
    day for 5m, ten days for 1h, six weeks for 4h and most of a year for 1d.
    """
    seconds = SECONDS.get(interval)
    if not seconds:
        return TOUCH_HALF_LIFE_DAYS
    return max(0.5, HALF_LIFE_BARS * seconds / 86_400.0)


#: Extra decay applied when the volatility regime itself changes. Not zero and
#: not one: the level is still there, but what it did in the old regime is much
#: weaker evidence about what it does in the new one.
REGIME_DECAY = 0.4

#: A break this far beyond the level, in volatility units, is decisive. Past
#: this the level's prior behaviour on that side is mostly stale evidence.
DECISIVE_BREAK_VOL = 2.0

#: How much of the approach side's history survives a decisive break.
BREAK_DECAY = 0.25


class Side(StrEnum):
    """Which side price arrived from. The level behaves differently per side."""

    #: Price came down onto the level — a floor being tested.
    ABOVE = "above"
    #: Price came up into the level — a ceiling being tested.
    BELOW = "below"

    @property
    def opposite(self) -> Side:
        return Side.BELOW if self is Side.ABOVE else Side.ABOVE

    @property
    def rejection_is_up(self) -> bool:
        """A floor tested from above rejects upward; a ceiling rejects downward."""
        return self is Side.ABOVE


class Outcome(StrEnum):
    """What the level did to price."""

    #: Pushed it back the way it came.
    REJECT = "reject"
    #: Let it through, and it kept going.
    BREAK = "break"
    #: Price came back to a level it recently broke, held, and carried on the
    #: way it broke. The middle ground between the two below it: momentum is
    #: already proven by the break, the entry is a pullback rather than a
    #: chase, and the risk is defined because the flipped level is the stop.
    BACKCHECK = "backcheck"
    #: Let it through, then took it back — a false breakout. Distinct from both
    #: of the above and not a shade of either: the price action that precedes it
    #: is a break, and the price action that follows is a rejection, so a model
    #: that only has those two words records it as a break that worked.
    TRAP = "trap"
    #: Neither, within the horizon. Kept because "nothing happened" is a real
    #: answer and a model that never sees it will predict a move every time.
    CHOP = "chop"
    #: Still in progress.
    OPEN = "open"


class State(StrEnum):
    FRESH = "fresh"
    TESTED = "tested"
    BROKEN = "broken"
    #: Broken, then respected from the other side — the classic flip. Worth its
    #: own state because a flipped level is a *repeating structure*, which is
    #: the thing this whole package exists to notice.
    FLIPPED = "flipped"


@dataclass(slots=True)
class Kalman:
    """One-dimensional Kalman filter over a slowly drifting price.

    `mean` is where the level is, `variance` how unsure we are. Both are in
    price units; callers convert to volatility units at the point of use, since
    the volatility that matters is the one at the moment of the question.
    """

    mean: float
    variance: float
    updated: float = field(default_factory=time.time)

    def predict(self, when: float, drift_per_hour: float) -> None:
        """Let uncertainty grow with time. A level untested for a month is a
        guess; one tested a minute ago is not."""
        elapsed_hours = max(0.0, (when - self.updated)) / 3600.0
        self.variance += (drift_per_hour**2) * elapsed_hours
        self.updated = max(self.updated, when)

    def update(self, observation: float, noise: float, when: float) -> float:
        """Fold in one touch. Returns the Kalman gain that was applied.

        The gain is returned because it *is* the answer to "how much did this
        touch move the level", which is worth journalling: a gain near 1 means
        the level had no idea where it was, near 0 that it was already sure.
        """
        self.predict(when, 0.0)
        noise = max(noise, 1e-12)
        gain = self.variance / (self.variance + noise)
        self.mean += gain * (observation - self.mean)
        self.variance *= 1.0 - gain
        self.updated = max(self.updated, when)
        return gain

    @property
    def sigma(self) -> float:
        return math.sqrt(max(self.variance, 0.0))


@dataclass(slots=True)
class SideStats:
    """What the level has done to price arriving from one particular side.

    Push is signed and in volatility units: positive is upward. Summing the
    signed push rather than counting rejections is deliberate — two rejections
    of very different size are not the same evidence, and a direction with no
    magnitude cannot be sized or compared with the cost of being wrong.
    """

    #: Counts are floats, not integers, because they decay. What is tracked is
    #: an *effective* touch count — how much evidence there is once age has been
    #: discounted — which is the number every downstream estimate wants anyway.
    touches: float = 0.0
    rejects: float = 0.0
    #: Retests of a recent break that held. Counted apart from plain rejects
    #: because the trade is different: the direction is already established, so
    #: it is a continuation rather than a reversal.
    backchecks: float = 0.0
    breaks: float = 0.0
    #: False breakouts. Tracked apart from rejects because they are the more
    #: useful fact: a level that traps is one where the obvious trade loses,
    #: which is different from one that simply holds.
    traps: float = 0.0
    chops: float = 0.0
    #: How far past the origin the wick reached, in volatility units, averaged
    #: over touches from this side. The zone's far edge: the origin is where
    #: price turned and the wick is how far it was pushed to get there, so the
    #: level occupies the span between them rather than a band centred on one.
    wick_vol: float = 0.0
    #: Sum and sum-of-squares of the signed push, for mean and dispersion.
    push_sum: float = 0.0
    push_sq: float = 0.0
    ups: float = 0.0

    def decay(self, factor: float) -> None:
        """Discount everything by `factor`. Old evidence fades; it is not erased.

        Fading rather than dropping matters: a hard cut-off would make a level
        forget its behaviour abruptly on an arbitrary boundary, and the
        estimate would jump for a reason nobody could point at.
        """
        factor = min(max(factor, 0.0), 1.0)
        self.touches *= factor
        self.rejects *= factor
        self.backchecks *= factor
        self.breaks *= factor
        self.traps *= factor
        self.chops *= factor
        self.push_sum *= factor
        self.push_sq *= factor
        self.ups *= factor

    def observe_wick(self, depth_vol: float) -> None:
        """Fold in how far the wick ran past the origin, exponentially."""
        depth_vol = max(0.0, depth_vol)
        self.wick_vol = depth_vol if not self.wick_vol else self.wick_vol * 0.8 + depth_vol * 0.2

    def record(self, outcome: Outcome, push_vol: float) -> None:
        self.touches += 1
        self.push_sum += push_vol
        self.push_sq += push_vol * push_vol
        if push_vol > 0:
            self.ups += 1
        match outcome:
            case Outcome.REJECT:
                self.rejects += 1
            case Outcome.BACKCHECK:
                # Also a rejection — the level held — but recorded as its own
                # thing so "does a retest work here" can be asked directly.
                self.rejects += 1
                self.backchecks += 1
            case Outcome.BREAK:
                self.breaks += 1
            case Outcome.TRAP:
                self.traps += 1
            case Outcome.CHOP:
                self.chops += 1

    @property
    def mean_push(self) -> float:
        return self.push_sum / self.touches if self.touches else 0.0

    @property
    def trap_rate(self) -> float:
        """Of the times price got through, how often it was taken back.

        The number worth knowing before trading a break: a level where half the
        breakouts fail is not a level you break out of.
        """
        attempts = self.breaks + self.traps
        return self.traps / attempts if attempts else 0.0

    @property
    def push_sigma(self) -> float:
        if self.touches < 2.0:
            return 0.0
        mean = self.mean_push
        var = max(0.0, self.push_sq / self.touches - mean * mean)
        return math.sqrt(var)

    def probability_up(self, prior_up: float = 0.5, prior_weight: float = 4.0) -> float:
        """Beta-binomial posterior that the next push is upward.

        Shrunk towards a prior on purpose. Three touches that all went up is
        not 100% — reporting it as such is how a system talks itself into a
        trade it has no evidence for. The prior is where kNN over similar
        levels supplies what this level's own history cannot.
        """
        alpha = prior_up * prior_weight + self.ups
        beta = (1.0 - prior_up) * prior_weight + (self.touches - self.ups)
        return alpha / (alpha + beta)

    def to_dict(self) -> dict[str, float]:
        return {
            "touches": round(self.touches, 3),
            "rejects": round(self.rejects, 3),
            "backchecks": round(self.backchecks, 3),
            "breaks": round(self.breaks, 3),
            "traps": round(self.traps, 3),
            "chops": round(self.chops, 3),
            "wick_vol": round(self.wick_vol, 4),
            "mean_push_vol": round(self.mean_push, 4),
            "push_sigma_vol": round(self.push_sigma, 4),
            "ups": round(self.ups, 3),
        }


@dataclass(slots=True)
class Level:
    """One key price level, and what it has done to price."""

    feed: str
    interval: str
    filter: Kalman
    origin: str = "pip"
    created: float = field(default_factory=time.time)
    state: State = State.FRESH
    last_touch: float = 0.0
    #: Statistics per approach side. The asymmetry is the whole point.
    sides: dict[Side, SideStats] = field(default_factory=dict)
    #: How many distinct swings formed it. A level from six swings is not the
    #: same object as one from two, however similar their prices.
    swings: int = 1
    #: When it was last broken, and the side price broke *from*. Kept because a
    #: back check is only a back check relative to a recent break — without the
    #: link it is just another touch at a level that happens to have flipped.
    broke_at: float = 0.0
    broke_from: Side | None = None
    #: True while price has not yet left the zone since the last interaction
    #: resolved. A level in this state cannot start another touch.
    #:
    #: Without it, one visit becomes one touch *per quote*: the interaction
    #: resolves, the next quote arrives with price still inside the zone and no
    #: open touch, and a fresh touch begins immediately. The counter then
    #: measures how long price loitered rather than how many times it turned,
    #: which is the opposite of evidence — a level price hovers at looks
    #: stronger than one it reverses off hard. It reached 316 "touches" on a BTC
    #: level in a day, on an instrument with 288 five-minute bars in one, and
    #: swamped the beta-binomial prior badly enough to report p=100%.
    waiting: bool = False

    @property
    def price(self) -> float:
        return self.filter.mean

    @property
    def touches(self) -> float:
        """Effective touches, after age has been discounted."""
        return sum(stats.touches for stats in self.sides.values())

    def stats(self, side: Side) -> SideStats:
        found = self.sides.get(side)
        if found is None:
            found = self.sides[side] = SideStats()
        return found

    def zone(self, vol: Volatility) -> tuple[float, float]:
        """The band that counts as touching, in price.

        A level is a zone, not a line, and it is not symmetric. The centre is
        the **origin** — where the leg in ended and the leg out began — and each
        edge extends by however far the **wick** ran past it on that side. Price
        arriving from above wicks *down* through the level, so the lower edge is
        the one that stretches; arriving from below stretches the upper.

        Width also has a floor from the filter's own uncertainty, so a level
        with no wicks recorded yet is still a band rather than a line, and both
        edges are clamped in volatility units to stay meaningful in any regime.
        """
        half = self.filter.sigma * ZONE_SIGMA
        floor = vol.price_units(self.price, MIN_ZONE_VOL)
        ceiling = vol.price_units(self.price, MAX_ZONE_VOL)
        half = min(max(half, floor), ceiling)

        below = self.sides.get(Side.ABOVE)
        above = self.sides.get(Side.BELOW)
        down = max(half, vol.price_units(self.price, below.wick_vol) if below else 0.0)
        up = max(half, vol.price_units(self.price, above.wick_vol) if above else 0.0)
        return self.price - min(down, ceiling), self.price + min(up, ceiling)

    def contains(self, price: float, vol: Volatility) -> bool:
        low, high = self.zone(vol)
        return low <= price <= high

    def distance_vol(self, price: float, vol: Volatility) -> float:
        """Signed distance from the level, in volatility units. Positive above."""
        if not self.price:
            return 0.0
        return ((price - self.price) / self.price * 10_000) / vol.bps

    def side_of(self, price: float) -> Side:
        """Which side price is on now, hence which side it would arrive from."""
        return Side.ABOVE if price >= self.price else Side.BELOW

    def backcheck_window(self) -> float:
        """How long after a break a return still counts as a retest, in seconds."""
        return BACKCHECK_BARS * SECONDS.get(self.interval, 3_600.0)

    def is_backcheck(self, side: Side, when: float) -> bool:
        """Whether a touch from `side` right now is a retest of a recent break.

        Two conditions, and both matter. The break has to be **recent** — a
        return three months later is a level, not a retest — and price has to be
        arriving from the side it broke *to*, which is the definition of coming
        back to it. Arriving from the original side is not a back check; it is
        the break failing late.
        """
        if not self.broke_at or self.broke_from is None:
            return False
        if when - self.broke_at > self.backcheck_window():
            return False
        return side is self.broke_from.opposite

    def stop_for(self, side: Side, vol: Volatility) -> float:
        """Where a stop belongs for a trade taken at this level from `side`.

        Beyond the zone, not at the level. The zone is precisely the band in
        which price can sit and still be respecting the level, so a stop inside
        it is a stop inside the noise — it gets hit by the level working.
        """
        low, high = self.zone(vol)
        buffer = vol.price_units(self.price, STOP_BUFFER_VOL)
        return low - buffer if side is Side.ABOVE else high + buffer

    def risk_vol(self, side: Side, price: float, vol: Volatility) -> float:
        """Distance from `price` to the stop, in volatility units.

        The number that makes a setup comparable with any other: an expected
        push is only worth having next to what it costs to be wrong.
        """
        stop = self.stop_for(side, vol)
        if not price:
            return 0.0
        return abs((price - stop) / price * 10_000) / vol.bps

    def strength(self, when: float, vol: Volatility) -> float:
        """How much this level deserves attention, in [0, 1].

        Three things, and they trade off. Touches are evidence. Confidence — a
        tight zone — means the evidence agrees. Age cuts both ways, so it is
        deliberately not rewarded: an old level with two touches is not strong,
        it is stale, and treating longevity as authority is how a chart ends up
        covered in lines nobody trades.
        """
        evidence = min(self.touches, 10.0) / 10.0
        agreement = 1.0 - min(1.0, self.filter.sigma / max(vol.price_units(self.price, 1.0), 1e-9))
        recency = (
            math.exp(-max(0.0, when - self.last_touch) / (14 * 86_400)) if self.last_touch else 0.3
        )
        breadth = min(self.swings, 5) / 5.0
        return round(
            0.4 * evidence + 0.25 * max(0.0, agreement) + 0.2 * recency + 0.15 * breadth, 4
        )

    def observe_wick(self, side: Side, origin: float, wick: float, vol: Volatility) -> None:
        """Record how far past the origin the wick ran, on the side it came from."""
        if not origin:
            return
        depth = abs((wick - origin) / origin * 10_000) / vol.bps
        self.stats(side).observe_wick(depth)

    def observe_touch(self, extreme: float, vol: Volatility, when: float) -> float:
        """Fold a touch into the level's position. Returns the Kalman gain.

        Observation noise scales with volatility: in a violent market the price
        at which price turned says less about where the level is, and the
        filter should — and now does — believe it less.
        """
        self.filter.predict(when, vol.price_units(self.price, DRIFT_VOL_PER_HOUR))
        noise = vol.price_units(self.price, 0.5) ** 2
        gain = self.filter.update(extreme, noise, when)
        self.last_touch = when
        if self.state is State.FRESH:
            self.state = State.TESTED
        return gain

    def age(self, when: float, half_life: float | None = None) -> None:
        """Discount every side's evidence for the time since the last touch.

        The half-life comes from the level's own timeframe unless one is given:
        a weekly level and a five-minute level forget at very different rates.
        """
        if not self.last_touch or when <= self.last_touch:
            return
        half_life = half_life_days(self.interval) if half_life is None else half_life
        elapsed_days = (when - self.last_touch) / 86_400.0
        factor = 0.5 ** (elapsed_days / max(half_life, 1e-9))
        for stats in self.sides.values():
            stats.decay(factor)

    def regime_changed(self, severity: float = 0.5) -> None:
        """The market changed character. What this level used to do counts less.

        `severity` is the change's percentile among past changes, in [0, 1], so
        the discount is graded rather than flat:

            decay = 1 - severity * (1 - REGIME_DECAY)

        A 99th-percentile change nearly resets the history; a 55th-percentile
        one barely touches it. Grading matters because the alternative is one
        constant standing in for every regime change there will ever be.

        The level itself survives either way — price still turns there. It is
        the statistics that were learned in a market that no longer exists.
        """
        severity = min(max(severity, 0.0), 1.0)
        decay = 1.0 - severity * (1.0 - REGIME_DECAY)
        for stats in self.sides.values():
            stats.decay(decay)

    def record(self, side: Side, outcome: Outcome, push_vol: float, when: float = 0.0) -> None:
        when = when or self.last_touch
        self.age(when)
        self.stats(side).record(outcome, push_vol)
        if outcome is Outcome.BREAK:
            self.state = State.BROKEN
            self.broke_at, self.broke_from = when, side
            if abs(push_vol) >= DECISIVE_BREAK_VOL:
                # A decisive break says the level stopped doing what it did.
                # Keeping its rejection history at full weight would have it
                # still predicting a bounce it has just conspicuously failed.
                self.stats(side).decay(BREAK_DECAY)
        elif outcome is Outcome.TRAP:
            # A trap is the level holding, not failing — violently, after
            # letting price through first. Its history stays intact, because
            # this is the level doing exactly what it did before.
            self.state = State.FLIPPED if self.state is State.BROKEN else State.TESTED
        elif outcome in (Outcome.REJECT, Outcome.BACKCHECK) and self.state is State.BROKEN:
            # Broken, and now respected again — the level flipped, which is a
            # repeating structure rather than a dead one.
            self.state = State.FLIPPED
        # The statistics keep their own clock. Relying on observe_touch to
        # advance it would mean evidence silently never ages whenever a caller
        # records an outcome without also folding in a price observation.
        self.last_touch = max(self.last_touch, when)

    def to_dict(self, vol: Volatility | None = None, when: float | None = None) -> dict:
        when = time.time() if when is None else when
        out: dict = {
            "feed": self.feed,
            "interval": self.interval,
            "price": round(self.price, 8),
            "sigma": round(self.filter.sigma, 8),
            "origin": self.origin,
            "state": str(self.state),
            "touches": self.touches,
            "swings": self.swings,
            "created": self.created,
            "last_touch": self.last_touch,
            "sides": {str(side): stats.to_dict() for side, stats in self.sides.items()},
        }
        if vol is not None:
            low, high = self.zone(vol)
            out |= {
                "low": round(low, 8),
                "high": round(high, 8),
                "strength": self.strength(when, vol),
                "vol_bps": round(vol.bps, 4),
            }
        return out


# ------------------------------------------------------------------ forming


def seed_price(point: Point) -> float:
    return point.price


def form(
    feed: str,
    interval: str,
    turns: Sequence[Point],
    vol: Volatility,
    *,
    tolerance_vol: float = 1.0,
    min_swings: int = 3,
) -> list[Level]:
    """Cluster swing points into levels.

    Agglomerative and one-dimensional: sort the swings by price and merge
    neighbours that sit within `tolerance_vol` volatility units of each other.
    Simple, and correct for the shape of the problem — the data is a line, so
    the cluster boundaries are just the gaps in it, and the popular alternatives
    (k-means, DBSCAN) either need k chosen in advance or rediscover exactly this
    in more code.

    Clustering in **volatility units** rather than basis points is what lets one
    tolerance work across gold, BTC and EURUSD at once.

    A cluster needs `min_swings` distinct turns. Two is not enough: any two
    swings define a line, so a two-swing level is not evidence of anything, and
    admitting them is how a chart ends up with a level every few basis points —
    at which density every price is "at a level" and the model predicts nothing.
    """
    ordered = sorted((point for point in turns if point.is_turn), key=lambda p: p.price)
    if not ordered:
        return []

    clusters: list[list[Point]] = [[ordered[0]]]
    for point in ordered[1:]:
        last = clusters[-1][-1]
        gap_bps = abs(point.price - last.price) / last.price * 10_000 if last.price else 0.0
        if vol.units(gap_bps) <= tolerance_vol:
            clusters[-1].append(point)
        else:
            clusters.append([point])

    levels: list[Level] = []
    for cluster in clusters:
        if len(cluster) < min_swings:
            continue
        prices = [point.price for point in cluster]
        centre = sum(prices) / len(prices)
        # Initial variance from the spread of the swings that formed it, with a
        # floor: three touches at an identical price is luck, not certainty.
        spread = _variance(prices, centre)
        floor = vol.price_units(centre, MIN_ZONE_VOL / ZONE_SIGMA) ** 2
        newest = max(point.confirmed for point in cluster)
        levels.append(
            Level(
                feed=feed,
                interval=interval,
                filter=Kalman(mean=centre, variance=max(spread, floor), updated=newest),
                origin="pip",
                created=newest,
                swings=len(cluster),
            )
        )
    return levels


def _variance(values: Sequence[float], mean: float) -> float:
    if len(values) < 2:
        return 0.0
    return sum((value - mean) ** 2 for value in values) / (len(values) - 1)


def merge(existing: Sequence[Level], found: Sequence[Level], vol: Volatility) -> list[Level]:
    """Fold newly formed levels into the ones already known.

    A level rediscovered is not a new level — it is evidence about an old one,
    and treating it as new would throw away exactly the touch history that
    makes it worth anything.
    """
    kept = list(existing)
    for candidate in found:
        near = _nearest(kept, candidate.price, vol)
        # Merge if the candidate falls inside the existing level's own zone,
        # not inside a fixed tolerance. The zone already encodes how sure that
        # level is about where it sits, which is exactly the right question:
        # a confident level absorbs only what is close, an uncertain one
        # absorbs more and tightens as a result.
        if near is not None and near.contains(candidate.price, vol):
            near.filter.update(
                candidate.price, vol.price_units(candidate.price, 0.5) ** 2, candidate.created
            )
            near.swings += candidate.swings
        else:
            kept.append(candidate)
    return dedupe(kept, vol)


def dedupe(levels: Sequence[Level], vol: Volatility) -> list[Level]:
    """Fold together levels whose zones overlap.

    Levels drift as they learn, so two that formed apart can converge onto the
    same price. Left alone they split the touch history between them and both
    look weaker than the one real level they describe.
    """
    ordered = sorted(levels, key=lambda level: level.price)
    kept: list[Level] = []
    for level in ordered:
        if not kept:
            kept.append(level)
            continue
        previous = kept[-1]
        _, prev_high = previous.zone(vol)
        low, _ = level.zone(vol)
        if low > prev_high:
            kept.append(level)
            continue
        # Keep the better-evidenced one and give it the other's history.
        winner, loser = (
            (previous, level) if previous.touches >= level.touches else (level, previous)
        )
        winner.filter.update(loser.price, vol.price_units(loser.price, 0.5) ** 2, loser.created)
        winner.swings += loser.swings
        for side, stats in loser.sides.items():
            into = winner.stats(side)
            into.touches += stats.touches
            into.rejects += stats.rejects
            into.breaks += stats.breaks
            into.chops += stats.chops
            into.push_sum += stats.push_sum
            into.push_sq += stats.push_sq
            into.ups += stats.ups
        winner.last_touch = max(winner.last_touch, loser.last_touch)
        kept[-1] = winner
    return kept


def _nearest(levels: Sequence[Level], price: float, vol: Volatility) -> Level | None:
    if not levels:
        return None
    return min(levels, key=lambda level: abs(level.distance_vol(price, vol)))


def nearby(
    levels: Sequence[Level], price: float, vol: Volatility, within_vol: float = 3.0
) -> list[Level]:
    """Levels close enough to matter, nearest first."""
    scored = [
        (abs(level.distance_vol(price, vol)), level)
        for level in levels
        if abs(level.distance_vol(price, vol)) <= within_vol
    ]
    return [level for _, level in sorted(scored, key=lambda pair: pair[0])]
