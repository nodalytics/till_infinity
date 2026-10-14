"""What happened last time price came here, and what that says about now.

A level with a history is only useful if the history is turned into an answer.
This module does two things: it watches an interaction from first contact to
resolution, and it turns the record of past interactions into a direction with
a probability and an expected size.

## The answer is a direction, not a verdict

"Will it hold" is the wrong question, because a level does different things
depending on which side price arrives from, and because "held" says nothing
about how far the push carried. What is produced instead is:

    given price arrived from *this* side, P(pushed up), and how far, in
    volatility units

Both halves matter. A 55% chance of a push worth 0.1 volatility units is not
worth acting on; a 55% chance of two volatility units might be.

## Two sources of evidence, and the honest weighting between them

A level that has been touched twenty times knows its own behaviour. A level
formed yesterday knows nothing - but it *resembles* levels that have been
touched hundreds of times, and that resemblance is real evidence.

So the estimate is a shrinkage between:

- **this level's own per-side record**, which is specific but often sparse;
- **kNN over historical touches at similar levels**, which is plentiful but
  only as relevant as the similarity is real.

The weight moves with the level's own touch count, so a level's own history
takes over as it earns one. That is the whole reason both exist: neither alone
is right at both ends.

## What stops it fooling itself

Every conditional probability here is reported next to the **base rate** - the
unconditional chance price went up over the same horizon. A level where
P(up | touched from below) equals the base rate has told you nothing, however
confident the number looks, and a system that does not show both will find
signal in noise every time.
"""

from __future__ import annotations

import math
import time
from collections.abc import Sequence
from dataclasses import dataclass, field

from .levels import (
    ARRIVAL_RUN_VOL,
    CONFIDENT_TOUCHES,
    DEPARTURE_RUN_VOL,
    RESOLVE_VOL,
    SECONDS,
    TRAP_VOL,
    TRAP_WINDOW,
    Level,
    Outcome,
    Side,
    SideStats,
)
from .state import Restorable
from .vol.volatility import Volatility

#: Neighbours consulted for the cold-start prior.
DEFAULT_K = 12

#: Historical touches kept for kNN. Bounded because this runs forever, and the
#: oldest touches describe a market that no longer exists anyway.
MEMORY = 4_000

#: Seconds after first contact at which the path is sampled.
#:
#: Wall clock rather than bars, so a 1m touch and a 1h touch are comparable at
#: the same horizon - the question "which way had it gone after five minutes"
#: means the same thing on both, where "after five bars" does not. The
#: magnitude is in volatility units of the touch's own interval, so the two
#: axes are normalised differently and on purpose.
#:
#: Stops at an hour because that is `Tracker`'s own horizon: past it a touch is
#: discarded rather than resolved, so there would be nothing to attach a later
#: sample to.
PATH_OFFSETS: tuple[int, ...] = (60, 300, 900, 1800, 3600)

#: Seconds after a touch **resolves** at which the forward return is sampled.
#:
#: Shorter than `PATH_OFFSETS` at the near end because that is where the
#: question lives: a scalp holds fifteen minutes, so what price did an hour
#: later is history rather than evidence. Longer than one sample because a rule
#: that is right at five minutes and wrong at fifteen is a different rule from
#: one that is right at both, and only two numbers can tell them apart.
FORWARD_OFFSETS: tuple[int, ...] = (60, 300, 900)

#: How many of a series' own resolved touches it takes before its base rate
#: mostly stops leaning on the pooled one. Higher than `PRIOR_WEIGHT` on
#: purpose: a base rate is the reference everything else is measured against,
#: so it should move more slowly than any single conditional built on it.
BASE_WEIGHT = 20.0

#: How strongly a kNN prior counts, in pseudo-touches. Roughly: borrowed
#: evidence is worth this much of the level's own.
PRIOR_WEIGHT = 4.0

#: Multiples of the horizon after which an open touch is **discarded** rather
#: than resolved.
#:
#: A touch that outlives its horizon normally means price sat at the level and
#: did nothing, which is `chop` and worth recording - a model never shown
#: "nothing happened" predicts a move every time. But a touch open for two days
#: does not mean that. It means nobody was watching: the FX market shut on
#: Friday evening and reopened on Sunday, or the collector was down.
#:
#: The difference matters because `_close` records `push_vol` as the distance
#: at the moment of closing. A touch opened before the weekend and closed after
#: it writes **the opening gap** into the level's own statistics and into
#: `facto`'s training targets, labelled as this level's reaction. It is not a
#: reaction to anything; it is the price of the market being shut.
#:
#: Four rather than two, so an ordinary slow session still resolves as chop and
#: only a genuine absence of observation is thrown away. Discarding is the
#: honest answer: an interaction spanning a period nobody observed has no
#: outcome, and inventing one is worse than losing it.
GAP_FACTOR = 4.0

#: **No longer a gate.** Kept as a reported number, because a ratio of expected
#: move to stop distance is worth a human seeing, and removed from `actionable`
#: on 2026-08-17 because it was measured to invert the sign of the return.
#:
#: The argument for it was clean and wrong. Below one, the move being predicted
#: is smaller than the distance to the stop, so the trade loses more when wrong
#: than it makes when right - break-even, not taste. That reasoning holds if
#: the two quantities are what they claim to be, and
#: [magnitude.md](../../research/magnitude.md) measured that they are not:
#:
#: | RR at least | n | mean realised push |
#: |---|---|---|
#: | 0.0 | 11,113 | **+0.496** |
#: | 1.0 | 1,560 | **-0.268** |
#: | 2.0 | 298 | -0.614 |
#:
#: End to end, the 9.9% of calls passing every gate returned **-0.151** while
#: everything the gate rejected returned **+0.569**.
#:
#: **The mechanism.** The ratio correlates +0.571 with its numerator and -0.359
#: with its denominator, so a high ratio is substantially a *small* `risk_vol`
#: - a tight zone, so a close stop. Top-decile calls are stopped out 44.8% of
#: the time against 29.1% in the bottom. `Level.stop_for` states the principle
#: the ratio violates: a stop inside the zone "is a stop inside the noise - it
#: gets hit by the level working."
#:
#: There is no threshold that fixes this, because the quantity is
#: anti-correlated with what it claims to measure. A stop derived from realised
#: adverse excursion - `Touch.excursion_vol`, already recorded - could make the
#: ratio mean something. Until then it is a number, not a decision.
MIN_REWARD_TO_RISK = 1.0

#: The least separation from the base rate a call may claim.
#:
#: **Measured, twice.** [edge.md](../../docs/edge.md) §1 replayed every call
#: against the outcome of the touch it opened and found a step: below it the
#: calls are a coin flip with a mean realised push of zero, above it they are
#: not, and nothing after the step goes back.
#:
#: | \|edge\| decile | from | direction | mean push |
#: |---|---|---|---|
#: | 1-3 | 0.0000 | 54.8% - 61.5% | ~0.00 |
#: | 4 | **0.0968** | **69.3%** | **0.49** |
#: | 5-10 | 0.1262+ | 68.8% - 77.9% | 0.37 - 1.11 |
#:
#: This was **0.08**, which was never derived from anything - not in the commit
#: that introduced it, not in the docs - and which sat inside the flat region.
#: Three deciles of calls, a quarter of everything said out loud, were being
#: published at a coin flip.
#:
#: The first measurement put the step at 0.11 on six bands over 1,990 calls; the
#: second put it at 0.0968 on ten deciles over 10,483 calls across fourteen
#: instruments. Ten is the round number between them, and both readings agree on
#: the only thing that matters here - that 0.08 is below the step.
#:
#: **What this does not claim.** The step's *location* is well established; the
#: accuracy either side of it is not a number to quote, because it does not
#: transport across a time split (edge.md §3). And a bigger edge is not a better
#: model: "assume the level holds" still beats the published direction at every
#: gate except the highest, where they tie ([features.md](../../research/features.md)
#: §3). This threshold selects larger, cleaner moves. It does not make the
#: direction right.
MIN_EDGE = 0.10

#: How many bars of its **own timeframe** a touch gets before it is chop.
#:
#: `horizon` was 3,600 seconds for every timeframe, which is not one rule but
#: eight different ones. In bars of the chart the touch is on, it granted:
#:
#:     1m  60 bars    15m   4 bars    1d  0.04 bars
#:     5m  12         1h    1         1w  0.01
#:     3m  20         4h    0.25
#:
#: On 4h and coarser a touch expired **before a single bar of its own
#: timeframe closed**, so it could not resolve by price at all - only by the
#: clock. Measured over a replay, the chop rate follows the horizon exactly and
#: not the market: 0.2% on 1m, 2.1% on 5m, 13.7% on 15m and **73.4% on 1h**,
#: with 91% of every chop recorded coming from 1h or coarser. Those are not
#: observations of price sitting still; they are the timer running out.
#:
#: Twelve, for two reasons that agree. It is what 5m already had - the
#: timeframe carrying most of the outcomes, so it is the value the system has
#: actually been exercised at - and the first-passage arithmetic in
#: `timing.py` puts the median resolution at about 3.2 bars and 12 bars at
#: roughly 73% of touches resolving by price, which is a defensible place to
#: call the rest chop.
HORIZON_BARS = 12.0

#: How wide a horizon band is, as a power of two in seconds. A band therefore
#: holds intervals whose horizons are within a factor of two of each other -
#: 1m and 3m can inform one another, 1m and 1w cannot.
#:
#: Two rather than a finer split because the alternative is a band per
#: interval, and there are ten of them over 1,762 resolved touches at the slow
#: end. A partition that leaves every slow band empty is the pooling problem
#: with extra steps.
HORIZON_BAND = 2.0

#: How far outside its own band a draw may reach before giving up. Two bands is
#: a factor of four in horizon, which is the point past which "comparable
#: length" stops meaning anything.
MAX_WIDEN = 2


def band_of(interval: str) -> int | None:
    """Which horizon band an interval belongs to, or None if it has no length.

    From the interval rather than from the touch's realised duration, because
    the band has to be known when the touch *opens* - how long it will take to
    resolve is the future, and choosing neighbours by it would be selecting the
    training set with the answer.
    """
    seconds = SECONDS.get(interval, 0.0)
    if seconds <= 0:
        return None
    return int(math.log(seconds * HORIZON_BARS, HORIZON_BAND))


#: How many bars a break stays provisional before it counts as having held.
#: Six, which is what 5m already had at `TRAP_WINDOW` of 1,800 seconds, and
#: half the horizon as before. It had the same defect: 1,800 seconds is 2% of a
#: daily bar, so a break on the daily was confirmed before the bar it broke on
#: had finished printing.
TRAP_BARS = 6.0

#: **The symmetric label's barrier**, in volatility units either side of the price a touch began at.
#: The production resolution distance, so the two labels ask about moves of the same size.
SYM_VOL = RESOLVE_VOL

#: How long a symmetric race may run, in bars of its level's timeframe. Four production horizons,
#: so nearly every race settles. Expiry is symmetric - a race that reaches neither barrier is
#: dropped, not scored - so the cap cannot move the 50% it reads on noise.
SYM_HORIZON_BARS = 4 * HORIZON_BARS

#: Races held open at once, across the book. A bound for a process that runs forever.
MAX_RACES = 5000

#: **One R for an episode**, in volatility units: the symmetric race's barrier, so an episode's 1R
#: and the race's settlement are the same distance. See `Episode`.
EPISODE_R_VOL = SYM_VOL

#: How long an episode is followed, in bars of its level's timeframe. The symmetric race's horizon,
#: but an episode runs all of it rather than stopping at the first barrier, because what happens
#: after 1R - the run, the reversal, the fade - is the point of it.
EPISODE_BARS = SYM_HORIZON_BARS

#: The R multiples whose first-passage times are recorded, each side.
EPISODE_MULTIPLES = (1, 2, 3)

#: Episodes held open at once. The same bound as the races, for the same reason.
MAX_EPISODES = MAX_RACES


#: Ceiling on a reward-to-risk reading. Median 0.364, p99 13.2, max 15,846.
RR_CAP = 20.0


@dataclass(frozen=True, slots=True)
class Features(Restorable):
    """What makes two touches comparable.

    Deliberately small, and every entry scale-free. A feature in price units or
    basis points would make gold and EURUSD incomparable, which would defeat
    the point of borrowing evidence across them.
    """

    side: Side
    #: How fast price was travelling into the level, in volatility units per bar.
    approach_vol: float
    #: How far into the zone it pushed, in volatility units.
    depth_vol: float
    #: The level's own quality at the time, in [0, 1].
    strength: float
    #: How many volatility units price had already travelled in this leg.
    run_vol: float
    #: Touch count, log-compressed: the difference between 1 and 5 touches
    #: matters far more than between 50 and 54.
    experience: float
    #: 1.0 for a pivot, 0.0 for a swing level. A dimension rather than a hard
    #: split: pivots do behave differently, but a pivot with no history should
    #: still be able to borrow from swing levels rather than from nothing.
    pivot: float = 0.0
    #: 1.0 when this touch is a retest of a recent break. Also a dimension: a
    #: back check is a different setup from a first touch, and the neighbours
    #: worth learning from are the other back checks.
    backcheck: float = 0.0
    #: Where volatility sat in its own recent range when this happened, in
    #: [0, 1]. Everything else here is *scaled* by volatility, which makes
    #: sizes comparable but deliberately erases the regime - and a level held
    #: in a dead session is weaker evidence about a violent one than the
    #: normalised numbers suggest. This puts that back as a dimension, so a
    #: touch is compared with touches from a market that felt the same.
    regime: float = 0.5
    #: The share of this side's previous touches that pushed **up**, in [0, 1],
    #: as it stood the instant this touch opened.
    #:
    #: The one measured addition to this set. Everything else here describes
    #: the level or the approach, and research/features.md found that none of
    #: it predicts direction once `side` is known - while the level's own
    #: record, which was never among the features, is worth +0.024 AUC on
    #: levels with three or more prior same-side touches.
    #:
    #: It was hiding inside `strength`, diluted with three terms that do not
    #: separate anything (research/strength.md), and behind `experience`, which
    #: counts touches without saying what they did.
    #:
    #: 0.5 means no history rather than an even split, which are different
    #: things the model cannot distinguish - `experience` carries how much
    #: evidence there is, so the pair reads correctly together.
    #:
    #: Point in time by construction: `features_for` runs before
    #: `Tracker.begin`, so this touch is not yet in its own denominator.
    up_rate: float = 0.5
    #: Speed over the last few bars against the speed of the few before them.
    #: Below one means price was **decelerating** into this level; above one
    #: that it was still accelerating.
    #:
    #: The second frame of a sequence whose first frame is `approach_vol`, and
    #: it is worth carrying because it is nearly **orthogonal** to it -
    #: correlation +0.008 over 4,078 resolved touches. On its own it separates
    #: hold from break at AUC 0.5237, weaker than arrival speed's 0.5429 and
    #: adding where a second correlated feature would not. See
    #: research/force.md.
    #:
    #: Zero means no reading rather than "not decelerating": there was not
    #: enough series, or the earlier leg did not move and a ratio against
    #: nothing is not a deceleration.
    slowing: float = 0.0
    #: Regression slope into the touch, in volatility units per bar, and the
    #: slope of the window before it. See `Engine._slope`.
    slope: float = 0.0
    prior_slope: float = 0.0
    #: Natural log of the seconds in the timeframe this level was drawn on.
    #: See `Engine._interval_log` and `structures/breaking.py`.
    interval_log: float = 0.0

    def distance(self, other: Features) -> float:
        """Similarity for kNN. Side is a hard constraint, not a dimension.

        See `structures-reactions.md` in research/docs.
        """
        if self.side is not other.side:
            return math.inf
        return math.sqrt(
            (self.approach_vol - other.approach_vol) ** 2
            + (self.depth_vol - other.depth_vol) ** 2
            + (self.strength - other.strength) ** 2
            + (self.run_vol - other.run_vol) ** 2
            + (self.experience - other.experience) ** 2
            + (self.pivot - other.pivot) ** 2
            + (self.backcheck - other.backcheck) ** 2
            + (self.regime - other.regime) ** 2
            + (self.up_rate - other.up_rate) ** 2
        )

    def to_dict(self) -> dict[str, float | str]:
        return {
            "side": str(self.side),
            "approach_vol": round(self.approach_vol, 4),
            "depth_vol": round(self.depth_vol, 4),
            "slowing": round(self.slowing, 4),
            "slope": round(self.slope, 4),
            "prior_slope": round(self.prior_slope, 4),
            "interval_log": round(self.interval_log, 4),
            "strength": round(self.strength, 4),
            "run_vol": round(self.run_vol, 4),
            "experience": round(self.experience, 4),
            "pivot": self.pivot,
            "backcheck": self.backcheck,
            "regime": round(self.regime, 4),
            # Journalled, so `facto.dataset` can read it back off an outcome
            # and the feature is learnable from history rather than only live.
            "up_rate": round(self.up_rate, 4),
        }


def experience_of(touches: float) -> float:
    return math.log1p(max(0.0, touches)) / math.log1p(50)


@dataclass(slots=True)
class Touch(Restorable):
    """One interaction, from first contact to resolution."""

    feed: str
    level_price: float
    features: Features
    started: float

    entry: float
    #: The furthest price reached while inside the zone. Kept, but **not** what
    #: the level's position is learned from - see `origin`.
    extreme: float
    #: The timeframe this level lives on. The base rate is per
    #: `(feed, interval)`, since an unconditional rate pooled across BTC 15m and
    #: GBPUSD daily describes neither. Empty means "do not bucket this" - a
    #: touch assembled by hand has no timeframe to speak for, and guessing one
    #: would put it in a bucket it does not belong to.
    interval: str = ""
    #: Where the leg coming in ended and the leg going out began.
    #:
    #: The better observation of where the level actually is. The extreme is a
    #: wick: liquidity taken a fraction beyond the level, at a price nobody
    #: traded around. The origin is where the move *turned* - in bar terms the
    #: close of the last bar in against the open of the first bar out, which
    #: are usually the same price outside a session gap.
    origin: float = 0.0
    #: How hard price left, in volatility units. Against `features.approach_vol`
    #: this is the whole reaction: weak in and strong out is a hard rejection,
    #: strong in and weak out is absorption, and the two look identical if only
    #: one of them is recorded.
    departure_vol: float = 0.0
    #: Set once price has turned, so the origin stops being updated.
    turned: bool = False
    #: Set once the leg *out* has ended, so `departure_vol` stops growing.
    #:
    #: Symmetric with `turned`, and for the same reason. Without it the
    #: departure is the largest excursion anywhere in the touch's life, which
    #: can be a move that happened long after the reaction and had nothing to do
    #: with it - "how hard price left" quietly becoming "the biggest thing that
    #: happened while we were watching".
    departure_done: bool = False
    outcome: Outcome = Outcome.OPEN
    push_vol: float = 0.0
    resolved: float = 0.0
    #: When price first got beyond the level. A break is provisional until it
    #: survives `TRAP_WINDOW`, so this is set long before the outcome is.
    broke_at: float = 0.0
    #: Furthest it reached beyond the level, in volatility units. What a
    #: breakout entry would have been offered before it was taken back.
    excursion_vol: float = 0.0
    #: The deepest price went **against** the reaction, in volatility units,
    #: recorded continuously from the first observation.
    #:
    #: `excursion_vol` beside it is not this, and the difference cost a day of
    #: replay work. That field is only assigned once `beyond >= resolve_vol`,
    #: so it records how far past a level price went *given it went past by a
    #: full unit* and is left at zero otherwise: 42,442 zeros against 12,105
    #: values of 1.0 or more, and **nothing in between**. Every replay that
    #: stopped a trade when `excursion >= stop` therefore modelled the same
    #: 1.0v stop whatever width it was asked for, and reported a rising R for
    #: tighter stops that was arithmetic on the denominator.
    #:
    #: This one has no threshold. It is what a stop actually has to survive,
    #: which is the question `min_stop_vol`, `reach_stop_vol` and every
    #: stop-width comparison were trying to answer.
    adverse_vol: float = 0.0
    #: How far **past** the level the extreme got, in volatility units, and
    #: zero while it never crossed.
    #:
    #: `depth_vol` is the distance at **arrival** and this is the furthest the
    #: move ever reached on the level's far side, which are different questions
    #: and separate different outcomes. A touch that never crossed is a reject;
    #: one that crossed and came back is a trap; one that crossed and stayed is
    #: a break. Only the first is visible in `depth_vol`.
    #:
    #: Measured against the level price rather than the zone edge, with
    #: `risk_vol` published beside it, so a consumer can compare the two
    #: instead of being handed a subtraction it cannot inspect.
    penetration_vol: float = 0.0

    #: What the model thought when this touch opened, kept so the resolution
    #: can be scored against it.
    #:
    #: Only *published* calls carried an edge before, and publication requires
    #: `edge >= MIN_EDGE` - so every edge ever recorded was already above the
    #: threshold, and the question "does a larger edge resolve better" could
    #: only ever be asked of the half of the distribution that passed. Attached
    #: to the touch instead, every interaction becomes evidence, including the
    #: ones nobody was told about. Answering it that way costs nothing and
    #: risks nothing, where sampling below the threshold by *trading* it means
    #: paying spread to re-run a measurement that has already been made.
    edge: float = 0.0
    probability_up: float = 0.0
    base_rate_up: float = 0.0
    #: The level's own posterior **before** this touch was counted into it.
    #:
    #: **Why a second field rather than reading the first.** `probability_up`
    #: is stamped on the touch after `level.record` has already added this
    #: touch to the level's counters, so the journalled value contains the
    #: outcome it is scored against. Measured over 502,233 journalled touches
    #: that reads an AUC of 0.9280 against the realised push, and exactly
    #: **1.0000** on daily - and the calibration curve is a step at 0.5, which
    #: is where counting one up-push carries the posterior across. Joining to
    #: the parent decision entry does not help: 81.6% of parents carry an
    #: identical value.
    #:
    #: It cannot be undone afterwards either. The count is recoverable from
    #: `probability_up` and `up_rate`, but removing this touch from an all-up
    #: history leaves an all-up history - and the history is all-up because
    #: 49% of consecutive 1m touches of a level land within five bars.
    #:
    #: So the only fix is to record the number as it stood. Rebuilt with
    #: spacing the same estimator reads 0.5092, so this field is what any
    #: future direction claim has to be scored on. See
    #: `research/docs/journal-probability.md`.
    probability_up_before: float = 0.0
    #: Whether this touch would have been published as a call.
    actionable: bool = False
    #: The other timeframes with a level at this price, coarsest first, as
    #: "1d+4h+1h". Empty means none, which is the common case - 7,198 of 7,966
    #: published calls have no other timeframe agreeing.
    #:
    #: Recorded for the same reason the edge is: it was on the signal and not
    #: on the resolution, so "does agreement across timeframes predict the
    #: outcome" could only be asked of the two dozen touches that were traded,
    #: where it is noise. Attached here it becomes answerable from the whole
    #: population.
    confluence: str = ""

    #: Where price actually went afterwards, at fixed offsets from first
    #: contact, in volatility units and signed - positive is up.
    #:
    #: **Recorded because every other measure of "what happened" is signed by
    #: the outcome.** `push_vol` is the resolved push, and its sign is fixed by
    #: which side price arrived from together with how the touch resolved: a
    #: reject from above pushes up by construction. Decomposed within each
    #: outcome that relationship is 0% or 100% at every one of the eight
    #: cells, which makes it an identity rather than a forecast - and it means
    #: no rule for choosing a **side** can be scored against it, because the
    #: answer is already in the question.
    #:
    #: This is the raw path instead. It knows nothing about rejects, traps or
    #: breaks, and it is what any side rule has to be tested against.
    path: dict[str, float] = field(default_factory=dict)

    @property
    def open(self) -> bool:
        return self.outcome is Outcome.OPEN

    @property
    def breaking(self) -> bool:
        """Through the level, but not yet proven to have stayed through."""
        return bool(self.broke_at) and self.open

    @property
    def energy(self) -> float:
        """How much harder it left than it arrived.

        Above one, the level pushed price away faster than price came in -
        which is what a level doing something looks like. At or below one,
        price walked in and drifted out, and the level was scenery.
        """
        approach = self.features.approach_vol
        return self.departure_vol / approach if approach else 0.0

    def to_dict(self) -> dict:
        return {
            "feed": self.feed,
            "level_price": round(self.level_price, 8),
            "started": self.started,
            "entry": round(self.entry, 8),
            "extreme": round(self.extreme, 8),
            "origin": round(self.origin or self.extreme, 8),
            "departure_vol": round(self.departure_vol, 4),
            "energy": round(self.energy, 4),
            "outcome": str(self.outcome),
            "push_vol": round(self.push_vol, 4),
            "excursion_vol": round(self.excursion_vol, 4),
            "penetration_vol": round(self.penetration_vol, 4),
            "adverse_vol": round(self.adverse_vol, 4),
            "edge": round(self.edge, 4),
            "probability_up": round(self.probability_up, 4),
            "probability_up_before": round(self.probability_up_before, 4),
            "base_rate_up": round(self.base_rate_up, 4),
            "actionable": self.actionable,
            "confluence": self.confluence,
            "confluence_n": float(len([x for x in self.confluence.split("+") if x])),
            **{f"path_{k}": round(v, 4) for k, v in self.path.items()},
            "resolved": self.resolved,
            **self.features.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class Inference(Restorable):
    """What the history says about the direction from here."""

    side: Side
    probability_up: float
    #: Expected push in volatility units, signed. Positive is upward.
    expected_push: float
    #: Dispersion of that push. A large mean with a larger sigma is not a call.
    push_sigma: float
    #: The unconditional rate, for comparison. If these match, there is no edge.
    base_rate_up: float
    own_touches: float
    neighbours: int
    #: Of those `neighbours`, how many the distance weighting actually leans
    #: on. `neighbours` is `k` by construction and therefore constant; this is
    #: the number that says whether anything comparable was found.
    comparable: float = 0.0
    detail: str = ""
    #: A retest of a recent break, arriving from the side it broke to.
    backcheck: bool = False
    #: Distance to a stop beyond the flipped level, in volatility units. What
    #: being wrong costs, which an expected push means nothing without.
    risk_vol: float = 0.0
    #: What taking this costs, in volatility units - spread, and eventually
    #: slippage. Zero until a caller supplies it, which keeps every existing
    #: call unchanged rather than silently re-gating history against a cost
    #: nobody measured.
    cost_vol: float = 0.0
    #: The level's own hold rate **on this side**, and how many decisive
    #: interactions are behind it. Carried separately from `probability_up`,
    #: which blends it with the neighbours' prior - the blend is the better
    #: estimate of what happens next, and the raw record is the better
    #: *ranking* signal, which are different jobs.
    #:
    #: strength.md measures this as the strongest thing a level knows: AUC
    #: 0.648 against `Level.strength`'s 0.548. It was computed on every touch
    #: and published nowhere, so nothing downstream could rank on it.
    record_hold: float = 0.0
    record_n: float = 0.0

    @property
    def direction(self) -> str:
        """Which way to lean - taken from the expected push, not the win rate.

        See `structures-reactions.md` in research/docs.
        """
        if self.expected_push > 0:
            return "up"
        if self.expected_push < 0:
            return "down"
        if self.probability_up > 0.5:
            return "up"
        if self.probability_up < 0.5:
            return "down"
        return ""

    @property
    def mixed(self) -> bool:
        """True when the win rate and the expected move point opposite ways.

        Not an error - it is a skewed distribution, usually many small moves one
        way and a few large ones the other. Worth surfacing rather than hiding,
        because it is exactly the shape where a win rate alone misleads.
        """
        leans_up = self.probability_up >= 0.5
        return leans_up != (self.expected_push > 0) and self.expected_push != 0

    @property
    def net_push(self) -> float:
        """Expected push after the cost of taking it, in volatility units.

        See `structures-reactions.md` in research/docs.
        """
        if self.expected_push == 0.0:
            return 0.0
        direction = 1.0 if self.expected_push > 0 else -1.0
        return self.expected_push - direction * self.cost_vol

    @property
    def probability_down(self) -> float:
        """`1 - P(up)`, exactly - not a second model.

        See `structures-reactions.md` in research/docs.
        """
        return 1.0 - self.probability_up

    @property
    def probability(self) -> float:
        """P(the direction actually being claimed).

        The number a reader wants, and the reason this exists: printing P(up)
        beside a *down* call renders as `down p=23%`, which invites reading 23%
        as the confidence in down when it is the confidence against it. When
        `mixed`, this deliberately comes out below 50% - the direction is taken
        from the expected push while the win rate points the other way, and the
        honest rendering of that is a low number with `mixed` beside it.
        """
        return self.probability_up if self.direction == "up" else self.probability_down

    @property
    def base_rate(self) -> float:
        """The unconditional rate for the *same* direction, so the pair compares.

        A conditional in one direction against a base rate in the other is not a
        comparison, and it is the shape most likely to be quoted approvingly.
        """
        return self.base_rate_up if self.direction == "up" else 1.0 - self.base_rate_up

    @property
    def edge(self) -> float:
        """How far the conditional sits from the unconditional. The real number.

        Signed in the *up* direction, which makes it direction-agnostic in
        magnitude: for a down call the same separation appears as `-edge`,
        because `(1-p) - (1-b) = -(p - b)`. Gates use `abs(edge)` for this
        reason; `edge_for_direction` is the one to show a person.
        """
        return self.probability_up - self.base_rate_up

    @property
    def edge_for_direction(self) -> float:
        """The separation from the base rate, in the direction being claimed."""
        return self.probability - self.base_rate

    @property
    def reward_to_risk(self) -> float:
        """Expected push against what being wrong costs, both in volatility units.

        The number that decides whether an edge is worth taking. A 70% call
        worth half what it risks is a losing trade; a 55% call worth three
        times it is not.
        """
        if not self.risk_vol:
            return 0.0
        # Bounded: 131,505 published values run median 0.364, p99 13.2, max
        # **15,846**. A risk distance near zero is what produces those, and a
        # reward-to-risk of fifteen thousand is a statement about the
        # denominator. Twenty is far outside anything actionable and well past
        # the 99th percentile.
        return min(abs(self.net_push) / self.risk_vol, RR_CAP)

    @property
    def actionable(self) -> bool:
        """Enough evidence, enough separation, enough size, pointing one way.

        See `structures-reactions.md` in research/docs.
        """
        return (
            self.own_touches + self.neighbours >= 8
            # See MIN_EDGE: below the step, calls are a coin flip with a mean
            # realised push of zero.
            and abs(self.edge) >= MIN_EDGE
            # Net, not gross: the cost of taking it comes off before the size
            # test, so an edge smaller than the spread cannot qualify.
            and abs(self.net_push) >= 0.5
            # And the cost must not have flipped it. A net push pointing the
            # other way is not a trade in the other direction - it means the
            # edge was eaten, and a large enough cost would otherwise sail back
            # through the size test above wearing the opposite sign.
            and self.net_push * self.expected_push > 0
            # A win rate and an expected move pointing opposite ways is a real
            # shape, but it is not a call - whichever one you act on, the other
            # says you are wrong.
            and not self.mixed
            # And it has to point somewhere. `direction` is empty on a true
            # tie, which used to resolve to "up" and publish a coin flip as a
            # call.
            and bool(self.direction)
        )

    def to_dict(self) -> dict:
        return {
            "side": str(self.side),
            "direction": self.direction,
            "probability_up": round(self.probability_up, 4),
            # Both, because `probability_up` is what the models and the journal
            # are keyed on and must not change meaning, while `probability` is
            # the one that reads correctly for a down call.
            "probability_down": round(self.probability_down, 4),
            "probability": round(self.probability, 4),
            "expected_push_vol": round(self.expected_push, 4),
            "push_sigma_vol": round(self.push_sigma, 4),
            "base_rate_up": round(self.base_rate_up, 4),
            "base_rate": round(self.base_rate, 4),
            "edge": round(self.edge, 4),
            "edge_for_direction": round(self.edge_for_direction, 4),
            "own_touches": round(self.own_touches, 2),
            "backcheck": self.backcheck,
            "risk_vol": round(self.risk_vol, 3),
            "cost_vol": round(self.cost_vol, 4),
            "net_push_vol": round(self.net_push, 4),
            "reward_to_risk": round(self.reward_to_risk, 3),
            "neighbours": self.neighbours,
            "comparable": round(self.comparable, 2),
            "actionable": self.actionable,
            "mixed": self.mixed,
            "detail": self.detail,
        }

    def __str__(self) -> str:
        note = " mixed" if self.mixed else ""
        return (
            f"{self.direction} p={self.probability:.0%} "
            f"(base {self.base_rate:.0%}) push={self.expected_push:+.2f}v "
            f"n={self.own_touches:.1f}+{self.neighbours}{note}"
        )


class Memory:
    """Resolved touches, and the kNN over them.

    A plain scan rather than a spatial index. The bound is a few thousand rows
    of five floats, which is microseconds - an index here would be complexity
    bought with nothing, and it would have to be rebuilt as touches age out.
    """

    def __init__(self, capacity: int = MEMORY, k: int = DEFAULT_K) -> None:
        self.capacity = capacity
        self.k = k
        self._touches: list[Touch] = []
        self._ups = 0
        #: (feed, interval) -> [ups, n]. Maintained alongside the pooled counts
        #: rather than derived on demand, because deriving it would mean a scan
        #: of every touch on every call.
        self._buckets: dict[tuple[str, str], list[int]] = {}
        #: How often a neighbour draw had to reach outside its own horizon
        #: band, and how often one happened at all. A band that cannot fill `k`
        #: is borrowing from a population that resolves on a different
        #: timescale, and that is exactly the mixing this banding exists to
        #: stop - so it is counted rather than left to be inferred.
        self.widened = 0
        self.drawn = 0

    def _bucket(self, touch: Touch) -> list[int] | None:
        if not touch.interval:
            return None
        return self._buckets.setdefault((touch.feed, touch.interval), [0, 0])

    def add(self, touch: Touch) -> None:
        if touch.open:
            return
        self._touches.append(touch)
        bucket = self._bucket(touch)
        if bucket is not None:
            bucket[1] += 1
        if touch.push_vol > 0:
            self._ups += 1
            if bucket is not None:
                bucket[0] += 1
        while len(self._touches) > self.capacity:
            dropped = self._touches.pop(0)
            gone = self._bucket(dropped)
            if gone is not None:
                gone[1] -= 1
            if dropped.push_vol > 0:
                self._ups -= 1
                if gone is not None:
                    gone[0] -= 1
            if gone is not None and gone[1] <= 0:
                self._buckets.pop((dropped.feed, dropped.interval), None)

    @property
    def base_rate_up(self) -> float:
        """The unconditional rate. Without it no conditional means anything.

        Jeffreys-smoothed - `(ups + 0.5) / (n + 1)` - so it never reaches 0 or
        1. Twenty observations that all went up make the base rate 0.98, not
        1.0, and the difference matters because everything else is shrunk
        *toward* this number: an unsmoothed 1.0 would propagate certainty into
        every conditional built on it, and no finite sample earns that.
        """
        if not self._touches:
            return 0.5
        return (self._ups + 0.5) / (len(self._touches) + 1.0)

    def base_rate_for(self, feed: str, interval: str) -> float:
        """The unconditional rate for *this* series, not for everything at once.

        See `structures-reactions.md` in research/docs.
        """
        pooled = self.base_rate_up
        ups, seen = self._buckets.get((feed, interval), (0, 0))
        if not seen:
            return pooled
        return (ups + BASE_WEIGHT * pooled) / (seen + BASE_WEIGHT)

    def neighbours(
        self, features: Features, interval: str = "", widen: bool = True
    ) -> list[tuple[float, Touch]]:
        """The k most similar resolved touches **of comparable length**, nearest first.

        See `structures-reactions.md` in research/docs.
        """
        want = band_of(interval)
        pools: list[int | None] = [want] if want is not None else [None]
        found: list[tuple[float, Touch]] = []
        reach = 0
        while True:
            scored = [
                (features.distance(touch.features), touch)
                for touch in self._touches
                if touch.features.side is features.side
                and (pools[0] is None or band_of(touch.interval) in pools)
            ]
            found = sorted(
                (pair for pair in scored if math.isfinite(pair[0])), key=lambda pair: pair[0]
            )[: self.k]
            if not widen or pools[0] is None or len(found) >= self.k or reach >= MAX_WIDEN:
                break
            reach += 1
            pools = [want - reach, *pools, want + reach]
        if reach:
            self.widened += 1
        self.drawn += 1
        return found

    def prior(self, features: Features, interval: str = "") -> tuple[float, float, int, float]:
        """(P(up), mean push, count, effective count) from touches at *other* levels.

        See `structures-reactions.md` in research/docs.
        """
        found = self.neighbours(features, interval)
        if not found:
            return self.base_rate_up, 0.0, 0, 0.0
        weights = [1.0 / (1.0 + distance) for distance, _ in found]
        total = sum(weights)
        ups = sum(w for w, (_, touch) in zip(weights, found, strict=True) if touch.push_vol > 0)
        push = sum(w * touch.push_vol for w, (_, touch) in zip(weights, found, strict=True))

        base = self.base_rate_up
        weight = len(found) / (len(found) + PRIOR_WEIGHT)
        smoothed = weight * (ups / total) + (1.0 - weight) * base
        # **How many of them the answer actually rests on.** The count is
        # always `k` - twelve, every time, on every card this desk has ever
        # sent - so printing it says nothing about whether anything comparable
        # was found. Kish's effective sample size does: twelve near-identical
        # neighbours come out near twelve, and twelve where one is close and
        # eleven are distant come out near one.
        spread = sum(w * w for w in weights)
        effective = (total * total / spread) if spread else 0.0
        return smoothed, push / total, len(found), effective

    def __len__(self) -> int:
        return len(self._touches)


def infer(
    level: Level,
    side: Side,
    features: Features,
    memory: Memory,
    vol: Volatility,
    price: float = 0.0,
    cost_vol: float = 0.0,
    prior_weight: float = PRIOR_WEIGHT,
) -> Inference:
    """Combine the level's own record with its neighbours' into one answer.

    See `structures-reactions.md` in research/docs.
    """
    own = level.stats(side)
    # Banded by the level's own interval, so a weekly touch is not informed by
    # a population of sub-minute touches whose direction is definitional. See
    # research/similarity.md.
    prior_up, prior_push, neighbours, comparable = memory.prior(features, level.interval)

    # Shrinkage: the level's own history takes over as it accumulates. With no
    # touches this is entirely the neighbours' answer; past CONFIDENT_TOUCHES it
    # is mostly the level's own.
    # `prior_weight` is `PRIOR_WEIGHT` unless the caller has enough levels in
    # this pool to have estimated it - see `structures/shrinkage.py`. The
    # constant is a guess at a quantity with a closed form; the estimate is
    # that quantity, measured, and it falls back to the guess when it cannot
    # be measured.
    weight = own.touches / (own.touches + prior_weight) if own.touches else 0.0
    probability = weight * own.probability_up(prior_up, prior_weight) + (1 - weight) * prior_up
    push = weight * own.mean_push + (1 - weight) * prior_push

    if own.touches >= CONFIDENT_TOUCHES:
        detail = f"{own.touches:.1f} prior touches from {side}"
    elif neighbours:
        detail = f"{own.touches:.1f} own touches, {neighbours} similar elsewhere"
    else:
        detail = "no comparable history"

    return Inference(
        side=side,
        probability_up=probability,
        expected_push=push,
        push_sigma=own.push_sigma,
        base_rate_up=memory.base_rate_for(level.feed, level.interval),
        cost_vol=cost_vol,
        own_touches=own.touches,
        neighbours=neighbours,
        comparable=comparable,
        detail=detail,
        backcheck=bool(features.backcheck),
        risk_vol=level.risk_vol(side, price or level.price, vol),
        record_hold=own.hold_rate,
        record_n=own.decisive,
    )


# ------------------------------------------------------------------ tracking


def _confluence_n(confluence: object) -> float:
    """How many timeframes agreed, whatever shape the field is in.

    Declared `str` and written as `"1h+4h+1d"` on the live path, and handed a
    sequence by several callers - so reading it one way only works until it
    does not. Counted rather than assumed.
    """
    if not confluence:
        return 0.0
    if isinstance(confluence, str):
        return float(len([x for x in confluence.split("+") if x]))
    try:
        return float(len([x for x in confluence if x]))
    except TypeError:
        return 0.0


@dataclass(slots=True)
class Forward(Restorable):
    """Where price went after a touch resolved, signed by the call's side.

    See `structures-reactions.md` in research/docs.
    """

    feed: str
    interval: str
    level: float
    #: +1 if the call expected a rise, -1 a fall. The whole point of the field.
    side: int
    resolved: float
    #: Seconds after resolution the touch is still followed for.
    deadline: float
    #: Offset in seconds -> signed return in the volatility units the level is
    #: measured in, which is **not the same denominator for every interval**:
    #: `Engine.vol_for` hands a daily or weekly level the reference estimate
    #: rather than its own, because the daily series' own volatility never
    #: warms. One unit is therefore a much smaller price distance there, and
    #: the first live records showed it - daily levels reading -34 and -27
    #: against 1m levels reading -1.5. Correct, and not poolable: cut by
    #: `interval` before averaging anything, or the long intervals decide the
    #: answer. Absent rather than zero when no quote landed on an offset: a gap
    #: in the record is not a measurement.
    after: dict[str, float] = field(default_factory=dict)
    #: Conditions carried along so the analysis is self-contained rather than a
    #: join against a 1.1GB journal on a two-core box.
    touches: float = 0.0
    confluence_n: float = 0.0
    actionable: bool = False

    @property
    def done(self) -> bool:
        return len(self.after) >= len(FORWARD_OFFSETS)

    def to_dict(self) -> dict:
        return {
            "feed": self.feed,
            "interval": self.interval,
            "level": round(self.level, 8),
            "side": self.side,
            "resolved": self.resolved,
            "touches": self.touches,
            "confluence_n": self.confluence_n,
            "actionable": self.actionable,
            **{f"after_{k}": round(v, 4) for k, v in self.after.items()},
        }


@dataclass(slots=True)
class Race(Restorable):
    """One touch's **symmetric** race: fixed barriers `SYM_VOL` either side of where it began.

    The production outcomes are measured from a ratcheting origin for a hold and from the fixed
    level for a break, and a break has to survive a trap window; on a random walk that reads as
    holding 55-65% of the time (research/docs/holdlabel.md, research/docs/skill.md). This race has
    none of that. Its barriers are fixed in price when the touch opens, it runs to its own end
    regardless of when the production touch closes, and a bar that reaches both barriers is
    dropped rather than guessed - so on noise it settles each way half the time, and a level that
    holds more often than that is telling us something about the market.
    """

    feed: str
    interval: str
    level_price: float
    side: Side
    started: float
    up: float
    down: float
    deadline: float
    #: +1 if the upper barrier was reached first, -1 the lower, 0 while open or if dropped.
    outcome: int = 0

    @property
    def held(self) -> bool:
        """Went back the way it came: up off a floor (arrived from above), down off a ceiling."""
        return self.outcome == (1 if self.side is Side.ABOVE else -1)


@dataclass(slots=True)
class Episode(Restorable):
    """The whole path after a touch begins, measured in R either way: the episode database's row.

    `Race` asks one question - which barrier first - and stops. An episode keeps going to its
    horizon and records what a trade from the touch would have lived through, **on both sides**,
    so a long and a short hypothesis are scored from one path:

    - when each side first reached 1R, 2R and 3R (`t_up`, `t_down`), and how far against it had
      gone by then (`mae_at_up1`, `mae_at_down1`) - a 1R reached only after a 1R adverse move is
      one a stop would have killed;
    - the furthest each side went (`mfe_up`, `mfe_down`), in R;
    - which side reached 1R first, and when the other side reached 1R after it (`opposite`);
    - when the leading side's excursion last grew (`t_peak`), and when it first gave back 1R
      from that peak (`t_fade`): the expansion's end, measured two ways.

    R is `EPISODE_R_VOL` volatility units at the price the touch began at, fixed when it opens.
    A bar that takes both sides to their first 1R at once is marked `ambiguous`, not guessed,
    because which came first is unknowable from a bar. Times are seconds after `started`.

    Recorded, not used: nothing gates on an episode. See `structures-reactions.md`.
    """

    feed: str
    interval: str
    level_price: float
    level_id: str
    #: Which side of the level price was on at contact. A floor (ABOVE) holds by going up.
    side: Side
    started: float
    entry: float
    #: One R as a price distance.
    unit: float
    deadline: float
    #: Seconds in one bar of the level's timeframe, so the record can speak in bars.
    bar: float
    #: What was believed when the touch opened. Set by the engine after the inference.
    probability_up: float = 0.5
    base_rate_up: float = 0.5
    edge: float = 0.0
    actionable: bool = False
    mfe_up: float = 0.0
    mfe_down: float = 0.0
    t_up: dict[int, float] = field(default_factory=dict)
    t_down: dict[int, float] = field(default_factory=dict)
    mae_at_up1: float | None = None
    mae_at_down1: float | None = None
    #: +1 if the upper 1R came first, -1 the lower, 0 while neither has or when `ambiguous`.
    first: int = 0
    ambiguous: bool = False
    t_peak: float | None = None
    t_fade: float | None = None

    def step(self, when: float, top: float, bottom: float, last: float) -> None:
        """Fold in one observation: the high and low since the last one, and the last price."""
        if self.unit <= 0:
            return
        elapsed = max(0.0, when - self.started)
        up = (top - self.entry) / self.unit
        down = (self.entry - bottom) / self.unit
        hit_up = up >= 1.0 and 1 not in self.t_up
        hit_down = down >= 1.0 and 1 not in self.t_down
        if hit_up and hit_down and self.first == 0 and not self.ambiguous:
            self.ambiguous = True
        elif self.first == 0 and not self.ambiguous and (hit_up or hit_down):
            self.first = 1 if hit_up else -1
        if hit_up:
            self.mae_at_up1 = max(self.mfe_down, down)
        if hit_down:
            self.mae_at_down1 = max(self.mfe_up, up)
        for k in EPISODE_MULTIPLES:
            if up >= k and k not in self.t_up:
                self.t_up[k] = elapsed
            if down >= k and k not in self.t_down:
                self.t_down[k] = elapsed
        lead_before = self.mfe_up if self.first >= 0 else self.mfe_down
        self.mfe_up = max(self.mfe_up, up)
        self.mfe_down = max(self.mfe_down, down)
        if self.first:
            lead = self.mfe_up if self.first > 0 else self.mfe_down
            if lead > lead_before or self.t_peak is None:
                self.t_peak = elapsed
            now = (last - self.entry) / self.unit * self.first
            if self.t_fade is None and lead - now >= 1.0:
                self.t_fade = elapsed

    @property
    def opposite(self) -> float | None:
        """When the side that did not reach 1R first reached it anyway."""
        if not self.first or self.ambiguous:
            return None
        return (self.t_down if self.first > 0 else self.t_up).get(1)

    @property
    def kind(self) -> str:
        """The path's class, from the side that reached 1R first.

        clean    it went on to 2R before the other side reached 1R
        whipsaw  the other side reached 1R before it reached 2R
        partial  1R and no more either way
        stall    neither side reached 1R
        ambiguous both did inside one bar
        """
        if self.ambiguous:
            return "ambiguous"
        if not self.first:
            return "stall"
        mine, theirs = (self.t_up, self.t_down) if self.first > 0 else (self.t_down, self.t_up)
        two, back = mine.get(2), theirs.get(1)
        if two is not None and (back is None or two < back):
            return "clean"
        if back is not None:
            return "whipsaw"
        return "partial"

    def to_dict(self) -> dict:
        bars = self.bar or 1.0

        def b(seconds: float | None) -> float | None:
            return None if seconds is None else round(seconds / bars, 3)

        held = 1 if self.side is Side.ABOVE else -1
        return {
            "feed": self.feed,
            "interval": self.interval,
            "level": round(self.level_price, 8),
            "level_id": self.level_id,
            "side": str(self.side),
            "started": self.started,
            "entry": round(self.entry, 8),
            "r_price": round(self.unit, 8),
            "r_vol": EPISODE_R_VOL,
            "horizon_bars": EPISODE_BARS,
            "kind": self.kind,
            "first": self.first,
            # Whether the first 1R went the way a held level would send it.
            "held_first": (self.first == held) if self.first else None,
            "mfe_up_r": round(self.mfe_up, 4),
            "mfe_down_r": round(self.mfe_down, 4),
            "mae_at_up1_r": None if self.mae_at_up1 is None else round(self.mae_at_up1, 4),
            "mae_at_down1_r": None if self.mae_at_down1 is None else round(self.mae_at_down1, 4),
            **{f"bars_up_{k}r": b(self.t_up.get(k)) for k in EPISODE_MULTIPLES},
            **{f"bars_down_{k}r": b(self.t_down.get(k)) for k in EPISODE_MULTIPLES},
            # When the other side reached 1R, after the first side had: the whipsaw's clock.
            "bars_opposite": b(self.opposite),
            "bars_peak": b(self.t_peak),
            "bars_fade": b(self.t_fade),
            # How fast the leading side travelled to its furthest point, in R a bar.
            "velocity_r": (
                round(
                    (self.mfe_up if self.first > 0 else self.mfe_down)
                    / max(self.t_peak / bars, 1.0),
                    4,
                )
                if self.first and self.t_peak is not None
                else None
            ),
            "probability_up": round(self.probability_up, 4),
            "base_rate_up": round(self.base_rate_up, 4),
            "edge": round(self.edge, 4),
            "actionable": self.actionable,
        }


@dataclass(slots=True)
class Tracker(Restorable):
    """Follows interactions from first contact to resolution.

    Resolution is what makes the record a training example rather than an
    observation, so it is the part that has to be right: a touch is resolved
    when price has travelled `resolve_vol` volatility units away from the
    level, in either direction, and is chopped if it has not done so within
    `horizon` seconds.
    """

    resolve_vol: float = 1.5
    break_vol: float = 0.75
    #: **The fallback only**, for a touch whose interval is not a known
    #: timeframe. Every real touch is scaled by `horizon_for` instead, so
    #: passing this expecting to shorten a 5m touch does nothing - set
    #: `horizon_bars`, which is the knob that survives the scaling.
    horizon: float = 3600.0
    #: Bars of the touch's own timeframe. See `HORIZON_BARS`.
    horizon_bars: float = HORIZON_BARS
    #: Bars a break stays provisional. See `TRAP_BARS`.
    trap_bars: float = TRAP_BARS
    #: How far back through the level counts as the break being taken back.
    trap_vol: float = TRAP_VOL
    #: How long a break stays provisional before it counts as having held.
    trap_window: float = TRAP_WINDOW
    memory: Memory = field(default_factory=Memory)
    _open: dict[tuple[str, float], Touch] = field(default_factory=dict)
    #: Resolved touches still being followed for their forward return, and the
    #: finished ones waiting to be drained. See `Forward`.
    #: Keyed by the level's **id**, never by its price. The Kalman mean moves
    #: every time the level learns something, and it learns from the touch that
    #: has just resolved - so a follower stored under the price at resolution
    #: is looked up, moments later, under a key that no longer exists. All 27
    #: records in the first half hour came back empty for exactly that reason.
    #: `service.py` warns about this trap fifty lines from where it was made.
    _forward: dict[str, Forward] = field(default_factory=dict)
    _followed: list[Forward] = field(default_factory=list)
    #: Symmetric races still running, and those settled but not yet credited to a level.
    _races: list[Race] = field(default_factory=list)
    _raced: list[Race] = field(default_factory=list)
    #: Episodes still being followed, and those finished but not yet drained. See `Episode`.
    _episodes: list[Episode] = field(default_factory=list)
    _episoded: list[Episode] = field(default_factory=list)

    def horizon_for(self, touch: Touch) -> float:
        """How long this touch gets, in seconds, for its own timeframe.

        A daily level tested at noon has not failed to react by one o'clock; it
        has barely been observed. See `HORIZON_BARS`.
        """
        seconds = SECONDS.get(touch.interval, 0.0)
        return seconds * self.horizon_bars if seconds else self.horizon

    def _walk(
        self, touch: Touch | None, level: Level, price: float, vol: Volatility, when: float
    ) -> None:
        """Note where price was, at each offset it has just passed.

        Written once per offset and never revised: the point is where price was
        *then*, and letting a later quote overwrite it would turn a path into a
        smear. An offset that no quote lands on is simply absent, which is
        honest - a gap in the record is not a zero.
        """
        if touch is None or not level.price:
            return
        elapsed = when - touch.started
        if elapsed < PATH_OFFSETS[0]:
            return
        unit = vol.price_units(level.price, 1.0)
        if unit <= 0:
            return
        for offset in PATH_OFFSETS:
            if elapsed < offset:
                break
            key = str(offset)
            if key not in touch.path:
                touch.path[key] = (price - level.price) / unit

    def note_confluence(self, feed: str, price: float, timeframes: str) -> None:
        """Tell an open touch which other timeframes agree with its level.

        Written back rather than set at `begin`, because confluence is worked
        out from the zone after the call exists and the touch is opened before
        that. A narrow accessor rather than reaching into `_open` from the
        service, so the key stays this class's business.
        """
        if not timeframes:
            return
        touch = self._open.get((feed, round(price, 8)))
        if touch is not None and not touch.confluence:
            touch.confluence = timeframes

    def trap_window_for(self, touch: Touch) -> float:
        """How long a break on this touch's timeframe stays provisional."""
        seconds = SECONDS.get(touch.interval, 0.0)
        return seconds * self.trap_bars if seconds else self.trap_window

    def key(self, level: Level) -> tuple[str, float]:
        return (level.feed, round(level.price, 8))

    def start_race(
        self, level: Level, side: Side, price: float, vol: Volatility, when: float
    ) -> Race | None:
        """Open the symmetric race for a touch that has just begun. See `Race`."""
        distance = vol.price_units(price, SYM_VOL) if vol.bps > 0 else 0.0
        if distance <= 0 or price <= 0:
            return None
        seconds = SECONDS.get(level.interval, 0.0) or self.horizon / self.horizon_bars
        race = Race(
            feed=level.feed,
            interval=level.interval,
            level_price=level.price,
            side=side,
            started=when,
            up=price + distance,
            down=price - distance,
            deadline=when + seconds * SYM_HORIZON_BARS,
        )
        self._races.append(race)
        if len(self._races) > MAX_RACES:
            del self._races[: len(self._races) - MAX_RACES]
        return race

    def advance_races(
        self,
        feed: str,
        price: float,
        when: float,
        low: float | None = None,
        high: float | None = None,
        since: float | None = None,
    ) -> None:
        """Move every open race on `feed` against the latest price, and a bar's extremes.

        A race that began inside the bar being delivered (`started >= since`) sees only its close:
        the bar's earlier wick happened before the race existed. Settled races wait in `_raced`
        for `drain_races`.
        """
        still: list[Race] = []
        for race in self._races:
            if race.feed != feed:
                still.append(race)
                continue
            use_wicks = since is None or race.started < since
            top = high if (use_wicks and high is not None) else price
            bottom = low if (use_wicks and low is not None) else price
            up, down = top >= race.up, bottom <= race.down
            if up and down:
                continue  # both inside one bar: which came first is unknowable, so it is not scored
            if up or down:
                race.outcome = 1 if up else -1
                self._raced.append(race)
                continue
            if when >= race.deadline:
                continue  # neither barrier in time: dropped, symmetrically
            still.append(race)
        self._races = still
        if len(self._raced) > MAX_RACES:
            del self._raced[: len(self._raced) - MAX_RACES]

    def drain_races(self) -> list[Race]:
        """The races settled since the last call."""
        out, self._raced = self._raced, []
        return out

    def start_episode(
        self, level: Level, side: Side, price: float, vol: Volatility, when: float
    ) -> Episode | None:
        """Open the episode for a touch that has just begun. See `Episode`."""
        unit = vol.price_units(price, EPISODE_R_VOL) if vol.bps > 0 else 0.0
        if unit <= 0 or price <= 0:
            return None
        seconds = SECONDS.get(level.interval, 0.0) or self.horizon / self.horizon_bars
        episode = Episode(
            feed=level.feed,
            interval=level.interval,
            level_price=level.price,
            level_id=level.id,
            side=side,
            started=when,
            entry=price,
            unit=unit,
            deadline=when + seconds * EPISODE_BARS,
            bar=seconds,
        )
        self._episodes.append(episode)
        if len(self._episodes) > MAX_EPISODES:
            del self._episodes[: len(self._episodes) - MAX_EPISODES]
        return episode

    def advance_episodes(
        self,
        feed: str,
        price: float,
        when: float,
        low: float | None = None,
        high: float | None = None,
        since: float | None = None,
    ) -> None:
        """Move every open episode on `feed` on by one price, with `advance_races`' rule for wicks.

        An episode that began inside the bar being delivered sees only its close. One that has
        reached its deadline is finished and waits in `_episoded` for `drain_episodes`.
        """
        still: list[Episode] = []
        for episode in self._episodes:
            if episode.feed != feed:
                still.append(episode)
                continue
            use_wicks = since is None or episode.started < since
            top = high if (use_wicks and high is not None) else price
            bottom = low if (use_wicks and low is not None) else price
            episode.step(min(when, episode.deadline), max(top, price), min(bottom, price), price)
            if when >= episode.deadline:
                self._episoded.append(episode)
                continue
            still.append(episode)
        self._episodes = still
        if len(self._episoded) > MAX_EPISODES:
            del self._episoded[: len(self._episoded) - MAX_EPISODES]

    def drain_episodes(self) -> list[Episode]:
        """The episodes finished since the last call."""
        out, self._episoded = self._episoded, []
        return out

    def begin(self, level: Level, price: float, features: Features, when: float) -> Touch:
        """Record first contact. The side comes from `features`, not separately -
        two sources for one fact is two things that can disagree."""
        touch = Touch(
            feed=level.feed,
            interval=level.interval,
            level_price=level.price,
            features=features,
            started=when,
            entry=price,
            extreme=price,
            # First contact is already part of the leg in, so the origin starts
            # there rather than at zero. Left falsy, the first `update` compared
            # price against `touch.origin or price` - price against itself, so
            # every first observation read as "deeper" and moved the origin to
            # wherever price happened to be. Nothing downstream noticed while
            # the leg out was measured from the level; measuring it from the
            # origin makes that self-comparison a guarantee of zero.
            origin=price,
        )
        self._open[self.key(level)] = touch
        return touch

    def update(
        self,
        level: Level,
        price: float,
        vol: Volatility,
        when: float,
        low: float | None = None,
        high: float | None = None,
    ) -> Touch | None:
        """Advance an open interaction. Returns it once resolved.

        See `structures-reactions.md` in research/docs.
        """
        touch = self._live(level, when)
        if touch is not None:
            self._walk(touch, level, price, vol, when)
        if touch is None:
            return None

        side = touch.features.side
        # Which end of the bar is the reach depends on which way price came in.
        reach = (low if side is Side.ABOVE else high) or price
        # The wick sets the extreme; the close sets the origin. They move
        # together only when no wick was supplied.
        if side is Side.ABOVE:
            touch.extreme = min(touch.extreme, reach)
            deeper = price <= (touch.origin or price)
        else:
            touch.extreme = max(touch.extreme, reach)
            deeper = price >= (touch.origin or price)
        # How far through the level the extreme got. `distance_vol` is positive
        # above, so arriving from above means the far side is negative.
        through = level.distance_vol(touch.extreme, vol)
        if side is Side.ABOVE:
            through = -through
        touch.penetration_vol = max(touch.penetration_vol, through, 0.0)
        if deeper and not touch.turned:
            touch.origin = price
        elif not touch.turned and touch.origin:
            # Not the first observation that fails to extend - that is a pause,
            # not a departure. The leg in is a *run*, and it is over only once
            # price has come back off its deepest point by a run's worth. Until
            # then a deeper print re-extends it and moves the origin with it.
            back = abs(level.distance_vol(price, vol) - level.distance_vol(touch.origin, vol))
            if back >= ARRIVAL_RUN_VOL:
                touch.turned = True
        # The leg out is a run too: it grows while price keeps going, and ends
        # once price has given back a run's worth of it. What comes after
        # belongs to whatever happens next, not to this reaction.
        if not touch.departure_done:
            reached = abs(
                level.distance_vol(price, vol) - level.distance_vol(touch.origin or price, vol)
            )
            if reached > touch.departure_vol:
                touch.departure_vol = reached
            elif touch.turned and touch.departure_vol - reached >= DEPARTURE_RUN_VOL:
                touch.departure_done = True

        travelled = level.distance_vol(price, vol)
        away = travelled if side is Side.ABOVE else -travelled
        beyond = -away
        # Recorded on every observation, with no threshold, because a stop has
        # to survive what price actually did rather than what it did once it
        # had already gone a full unit past. See `Touch.adverse_vol`.
        touch.adverse_vol = max(touch.adverse_vol, beyond)
        # A *rejection* is the one test measured from where the leg in ended
        # rather than from the level's centre line. The zone reaches as far as
        # See `structures-reactions.md` in research/docs.
        began = level.distance_vol(touch.origin or touch.entry, vol)
        moved = travelled - began
        left = moved if side is Side.ABOVE else -moved

        if touch.breaking:
            # A break is provisional. Coming back through the level means the
            # breakout was a trap, and the trade it invited has lost - which is
            # a different fact from the level holding in the first place, and
            # the one worth knowing before trading the next break here.
            touch.excursion_vol = max(touch.excursion_vol, beyond)
            if away >= self.trap_vol:
                return self._close(level, touch, Outcome.TRAP, travelled, side, when)
            if when - touch.broke_at >= self.trap_window_for(touch):
                return self._close(level, touch, Outcome.BREAK, travelled, side, when)
            return None

        if left >= self.resolve_vol:
            # A retest of a recent break that holds is a back check, not a
            # plain rejection: the direction is already established, so this is
            # a continuation entry rather than a reversal one.
            held = Outcome.BACKCHECK if level.is_backcheck(side, touch.started) else Outcome.REJECT
            return self._close(level, touch, held, travelled, side, when)
        if beyond >= self.resolve_vol:
            # Through it - but not resolved yet. A break is not a break until
            # it survives, which is how anyone trading one treats it.
            touch.broke_at = when
            touch.excursion_vol = beyond
            return None
        if when - touch.started >= self.horizon_for(touch):
            return self._close(level, touch, Outcome.CHOP, travelled, side, when)
        return None

    def _live(self, level: Level, when: float) -> Touch | None:
        """The open touch, unless it has outlived any reading of the price.

        See `structures-reactions.md` in research/docs.
        """
        touch = self._open.get(self.key(level))
        if touch is None:
            return None
        # And **not before it began**. A bar reaches here stamped at its own
        # close and arrives *after* that close, so a touch a quote opened in
        # See `structures-reactions.md` in research/docs.
        if when < touch.started:
            return None
        if when - touch.started >= self.horizon_for(touch) * GAP_FACTOR:
            self._open.pop(self.key(level), None)
            return None
        return touch

    def _close(
        self,
        level: Level,
        touch: Touch,
        outcome: Outcome,
        travelled: float,
        side: Side,
        when: float,
    ) -> Touch:
        touch.outcome = outcome
        # Signed in absolute terms - positive is up - rather than relative to
        # the approach. A consumer wants to know which way to lean, not whether
        # the level "won".
        touch.push_vol = travelled
        # Never before it began. `update` already refuses a stale observation,
        # and this is the backstop for every other path into `_close` - a
        # duration that runs backwards is not a small error, it silently
        # reverses whatever reads it.
        touch.resolved = max(when, touch.started)
        self._open.pop(self.key(level), None)
        # Before `record`, not after: once this touch is counted, the posterior
        # contains its own answer. One line, and the journal becomes scorable.
        touch.probability_up_before = level.stats(side).probability_up()
        level.record(side, outcome, touch.push_vol, when)
        if outcome is Outcome.BREAK and touch.broke_at:
            # The retest clock starts when price *got through*, not when the
            # break was confirmed. Confirmation waits out the trap window, so
            # dating it from there spends most of the window before a retest
            # could possibly happen - which is why almost none were detected.
            level.broke_at = touch.broke_at
        self.memory.add(touch)
        # **Followed past its own resolution.** Everything else recorded about
        # a touch is decided by the moment it resolves, which is why none of it
        # can score a direction rule. See `Forward`.
        self._follow(level, touch, side, when)
        return touch

    def _follow(self, level: Level, touch: Touch, side: Side, when: float) -> None:
        """Start watching where price goes now the touch is over.

        Signed by the side the *call* took rather than by the approach: a call
        that expected a fall and got one is right, and that is the only sense
        in which a forward return is a label.
        """
        if not level.price:
            return
        lean = -1 if side is Side.ABOVE else 1
        self._forward[level.id] = Forward(
            feed=touch.feed,
            interval=touch.interval,
            level=level.price,
            side=lean,
            resolved=when,
            # **Past the last offset, not at it.** The final sample needs a
            # window to land in like every other one, and a deadline equal to
            # the offset leaves it exactly zero seconds wide - which a test
            # caught by never filling it. As wide as the gap before it.
            deadline=when + FORWARD_OFFSETS[-1] + (FORWARD_OFFSETS[-1] - FORWARD_OFFSETS[-2]),
            touches=float(getattr(touch.features, "experience", 0.0) or 0.0),
            confluence_n=_confluence_n(touch.confluence),
            actionable=bool(touch.actionable),
        )

    def carry(self, level: Level, price: float, vol: Volatility, when: float) -> None:
        """Advance a forward return on an observation, touch or no touch.

        See `structures-reactions.md` in research/docs.
        """
        self._carry(level, price, vol, when)

    def _carry(self, level: Level, price: float, vol: Volatility, when: float) -> None:
        """Fill in a followed touch's return at each offset it has passed.

        Written once per offset and never revised, for the reason `_walk` gives:
        the point is where price was *then*, and a later quote overwriting it
        turns a path into a smear.
        """
        found = self._forward.get(level.id)
        if found is None:
            return
        unit = vol.price_units(found.level, 1.0)
        if unit > 0:
            elapsed = when - found.resolved
            # **Each offset is filled only by a quote that landed in its own
            # window**, never by whichever quote happens to arrive next. A
            # See `structures-reactions.md` in research/docs.
            last = found.deadline - found.resolved
            windows = list(zip(FORWARD_OFFSETS, (*FORWARD_OFFSETS[1:], last), strict=True))
            for offset, until in windows:
                mark = str(offset)
                if mark not in found.after and offset <= elapsed < until:
                    found.after[mark] = found.side * (price - found.level) / unit
        if found.done or when >= found.deadline:
            self._forward.pop(level.id, None)
            # Kept even when incomplete: a level that stopped being quoted is
            # itself a fact, and an absent offset is honest where a zero is not.
            self._followed.append(found)

    def _flush_followed(self, when: float) -> None:
        """Retire followers whose window has closed, quote or no quote.

        Kept with whatever offsets did fill. A level price walked away from has
        an empty forward return and that is the honest record of it - the
        alternative is a sample made only of levels price came back to.
        """
        done = [key for key, found in self._forward.items() if when >= found.deadline]
        for key in done:
            self._followed.append(self._forward.pop(key))

    def drain_followed(self) -> list[Forward]:
        """Take the forward returns finished since the last call.

        Draining rather than reading, for the reason `drain_resolved` gives:
        a consumer that read without clearing would record the same label on
        every message.
        """
        found, self._followed = self._followed, []
        return found

    def open_touch(self, level: Level) -> Touch | None:
        return self._open.get(self.key(level))

    @property
    def open_count(self) -> int:
        return len(self._open)

    def expire(self, when: float) -> list[Touch]:
        """Close out anything that has sat open too long.

        See `structures-reactions.md` in research/docs.
        """
        self._flush_followed(when)
        stale = [
            key
            for key, touch in self._open.items()
            if when - touch.started >= self.horizon_for(touch) * 2
            or (touch.breaking and when - touch.broke_at >= self.trap_window_for(touch))
        ]
        dropped = []
        for key in stale:
            touch = self._open.pop(key)
            if when - touch.started >= self.horizon_for(touch) * GAP_FACTOR:
                continue  # a gap, not an outcome - see GAP_FACTOR
            touch.outcome = Outcome.BREAK if touch.breaking else Outcome.CHOP
            touch.resolved = max(when, touch.started)
            # No price arrived to close this out, so the push is whatever the
            # touch had already reached: the excursion for a break that got
            # through and went quiet, and nothing at all for chop, which is
            # what chop means. Signed like `_close`'s - positive is up - so a
            # break away from a level approached from above reads negative.
            if touch.outcome is Outcome.BREAK:
                sign = -1.0 if touch.features.side is Side.ABOVE else 1.0
                touch.push_vol = sign * touch.excursion_vol
            self.memory.add(touch)
            dropped.append(touch)
        return dropped


def features_for(
    level: Level,
    side: Side,
    price: float,
    vol: Volatility,
    *,
    approach_vol: float = 0.0,
    run_vol: float = 0.0,
    slowing: float = 0.0,
    slope: float = 0.0,
    prior_slope: float = 0.0,
    interval_log: float = 0.0,
    when: float | None = None,
) -> Features:
    """Describe one touch in the scale-free terms kNN compares."""
    when = time.time() if when is None else when
    return Features(
        side=side,
        approach_vol=approach_vol,
        depth_vol=abs(level.distance_vol(price, vol)),
        strength=level.strength(when, vol),
        run_vol=run_vol,
        experience=experience_of(level.touches),
        pivot=1.0 if level.origin.startswith("pivot") else 0.0,
        backcheck=1.0 if level.is_backcheck(side, when) else 0.0,
        regime=vol.regime,
        up_rate=up_rate_of(level.stats(side)),
        slowing=slowing,
        slope=slope,
        prior_slope=prior_slope,
        interval_log=interval_log,
    )


def up_rate_of(stats: SideStats) -> float:
    """What share of this side's touches pushed up, or 0.5 for no history.

    Counts are decayed, so this is already an age-weighted rate rather than a
    lifetime average - a level that held ten times last year and broke twice
    this week reads closer to the recent behaviour, which is the one worth
    knowing.
    """
    return stats.ups / stats.touches if stats.touches else 0.5


def rank(inferences: Sequence[Inference]) -> list[Inference]:
    """Strongest first: real edge, then size, then evidence."""
    return sorted(
        inferences,
        key=lambda i: (i.actionable, abs(i.edge), abs(i.expected_push)),
        reverse=True,
    )
