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
    SECONDS,
    TRAP_VOL,
    TRAP_WINDOW,
    Level,
    Outcome,
    Side,
    SideStats,
)
from .state import Restorable
from .volatility import Volatility

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

#: How many bars a break stays provisional before it counts as having held.
#: Six, which is what 5m already had at `TRAP_WINDOW` of 1,800 seconds, and
#: half the horizon as before. It had the same defect: 1,800 seconds is 2% of a
#: daily bar, so a break on the daily was confirmed before the bar it broke on
#: had finished printing.
TRAP_BARS = 6.0


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

    def distance(self, other: Features) -> float:
        """Similarity for kNN. Side is a hard constraint, not a dimension.

        Mixing sides would let a floor's history vote on a ceiling's future,
        which is precisely the asymmetry the whole design exists to respect.

        Being worth *predicting* with and worth *comparing* on are separate
        claims, so `up_rate` was measured on both before being added here:
        over a replay of the stored bars it takes the neighbour vote's AUC from
        0.797 to 0.813. Unweighted, like every other dimension - weighting it
        two or four times over reached 0.816 and 0.819, which is not enough to
        justify fitting a constant to two thousand touches.

        The other eight are kept despite research/features.md finding that none
        of them predicts direction once side is known. They are cheap, removing
        them is a separate change with its own risk, and "does not predict
        direction" is not "does not identify a comparable touch".
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
            "adverse_vol": round(self.adverse_vol, 4),
            "edge": round(self.edge, 4),
            "probability_up": round(self.probability_up, 4),
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

        The two can disagree, and when they do the expected value is what a
        consumer acts on: a level that drifts down four times in five and jumps
        hard on the fifth has a losing win rate and a positive expectation.
        Reporting "down" there while the expected move is upward would be
        incoherent to anyone reading it.

        A true tie has **no** direction and says so. `>= 0.5` resolved a coin
        flip to "up", which is a lean invented out of nothing: 0.5 is the
        absence of a view, not a weak vote for up. Rare - `probability_up` is
        exactly 0.5 on one outcome in 71,988 - and rare is the reason to fix
        it rather than to leave it, because a bias that fires occasionally is
        one that never shows up in a summary.

        `actionable` requires a direction, so a call with none is refused
        rather than published pointing at whichever way the comparison fell.
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

        Every push in this system is **gross**, and that is the single largest
        gap between what it produces and something worth acting on. A `+0.5v`
        edge on an instrument whose spread is `0.3v` is not an edge; it is a
        rounding error with a direction attached, and gross numbers cannot tell
        the two apart. The project measures spread - it is one of the signal
        shapes - and until now never subtracted it from anything.

        Signed toward the same direction as the push, so cost always makes the
        claim smaller and can flip it through zero. A cost larger than the edge
        should produce a *negative* net push rather than a small positive one:
        that is not a weak trade, it is the wrong side of one.
        """
        if self.expected_push == 0.0:
            return 0.0
        direction = 1.0 if self.expected_push > 0 else -1.0
        return self.expected_push - direction * self.cost_vol

    @property
    def probability_down(self) -> float:
        """`1 - P(up)`, exactly - not a second model.

        There is one number because there are two outcomes: `record` increments
        `ups` when the push was positive, and the beta-binomial's `beta` term is
        `touches - ups`, so everything that was not an up is a down. Asking for
        P(down) separately would be asking the same counter twice.

        The one wrinkle, stated because it is invisible otherwise: a push of
        *exactly* zero falls to the down side of `push_vol > 0`. Push is a
        continuous quantity in volatility units, so this is a measure-zero case
        rather than a lean, but it is a tie broken by an implementation detail
        rather than by evidence.
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
        return abs(self.net_push) / self.risk_vol if self.risk_vol else 0.0

    @property
    def actionable(self) -> bool:
        """Enough evidence, enough separation, enough size, pointing one way.

        Every one of them, because any single one alone is how a backtest lies:
        a big edge on four touches is noise, a large sample at the base rate is
        nothing, and a confident call worth 0.1 volatility units does not pay
        for itself.

        **A fifth gate was removed on 2026-08-17.** `reward_to_risk >=
        MIN_REWARD_TO_RISK` read as the most principled of the set - a call
        worth less than the stop behind it loses more when wrong than it makes
        when right - and was measured to invert the sign of the expected
        return. See `MIN_REWARD_TO_RISK` for the numbers.

        That is worth remembering about the remaining four. They are gates
        because a measurement says they select better calls, not because the
        reasoning behind them sounds right. The removed one had the best
        reasoning of any of them.
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

        The pooled rate above is one number for the whole system, and for a
        while it was the only one: every call on every instrument and timeframe
        was measured against it. That is wrong in a way that does real damage,
        because `edge` is `conditional - base` and `actionable` gates on it -
        so a pool that happens to sit at 72% down hands every down call a
        twenty-point apparent edge and handicaps every up call, systematically,
        on instruments that have nothing to do with the samples that set it.

        BTC on 15m and GBPUSD on the daily do not share an unconditional drift,
        and the neighbours being pooled across them is a separate matter: the
        features are scale-free so that a *conditional* can borrow evidence, and
        borrowing a conditional is not the same as borrowing the thing it is
        supposed to be compared against.

        Shrunk toward the pooled rate rather than switched to the bucket the
        moment one exists, because a bucket with three touches in it is not an
        estimate of anything. `BASE_WEIGHT` is how many of its own observations
        a series needs before it mostly speaks for itself.
        """
        pooled = self.base_rate_up
        ups, seen = self._buckets.get((feed, interval), (0, 0))
        if not seen:
            return pooled
        return (ups + BASE_WEIGHT * pooled) / (seen + BASE_WEIGHT)

    def neighbours(self, features: Features) -> list[tuple[float, Touch]]:
        """The k most similar resolved touches, nearest first."""
        scored = [
            (features.distance(touch.features), touch)
            for touch in self._touches
            if touch.features.side is features.side
        ]
        scored = [pair for pair in scored if math.isfinite(pair[0])]
        scored.sort(key=lambda pair: pair[0])
        return scored[: self.k]

    def prior(self, features: Features) -> tuple[float, float, int]:
        """(P(up), mean push, count) from similar touches at *other* levels.

        Distance-weighted, so a close neighbour counts for more than a distant
        one. Without the weighting, k neighbours of wildly different similarity
        vote equally and the estimate is dominated by whichever level happened
        to be touched most.

        The result is then **shrunk toward the base rate**, which matters more
        than it sounds: twelve neighbours that all went the same way would
        otherwise return exactly 0.0 or 1.0, and a level with no history of its
        own would inherit that certainty and report it. Twelve agreeing
        observations are evidence; they are not proof, and a system that prints
        "0%" from them will eventually print it about something it is wrong
        about.
        """
        found = self.neighbours(features)
        if not found:
            return self.base_rate_up, 0.0, 0
        weights = [1.0 / (1.0 + distance) for distance, _ in found]
        total = sum(weights)
        ups = sum(w for w, (_, touch) in zip(weights, found, strict=True) if touch.push_vol > 0)
        push = sum(w * touch.push_vol for w, (_, touch) in zip(weights, found, strict=True))

        base = self.base_rate_up
        weight = len(found) / (len(found) + PRIOR_WEIGHT)
        smoothed = weight * (ups / total) + (1.0 - weight) * base
        return smoothed, push / total, len(found)

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
) -> Inference:
    """Combine the level's own record with its neighbours' into one answer.

    `vol` is **required**, and used to be optional with a zero fallback. That
    made the risk geometry something a caller could forget, and every caller
    did: `risk_vol` was 0.0 on every level call ever journalled, which made
    `reward_to_risk` identically zero - the number documented as deciding
    whether an edge is worth taking, never once computed. It went unnoticed
    because nothing gates on it yet and because zero is a plausible-looking
    number rather than an obviously missing one.

    Every caller already had `vol` in scope. The fix is not to default it more
    carefully; it is to stop it being optional, so the next caller cannot make
    the same omission quietly.

    `price` stays optional and falls back to the level's own price, which is
    the honest answer when no arrival price is known: the stop sits a fixed
    distance beyond the level either way.
    """
    own = level.stats(side)
    prior_up, prior_push, neighbours = memory.prior(features)

    # Shrinkage: the level's own history takes over as it accumulates. With no
    # touches this is entirely the neighbours' answer; past CONFIDENT_TOUCHES it
    # is mostly the level's own.
    weight = own.touches / (own.touches + PRIOR_WEIGHT) if own.touches else 0.0
    probability = weight * own.probability_up(prior_up, PRIOR_WEIGHT) + (1 - weight) * prior_up
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
        detail=detail,
        backcheck=bool(features.backcheck),
        risk_vol=level.risk_vol(side, price or level.price, vol),
        record_hold=own.hold_rate,
        record_n=own.decisive,
    )


# ------------------------------------------------------------------ tracking


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

        `price` is where the bar closed (or the current mid); `wick` is how far
        it reached - the bar's low approaching from above, its high from below.
        The two are what separate the **extreme** from the **origin**, and with
        only one of them they collapse into the same number: the deepest price
        seen is trivially also the last one before the turn.

        The wick is where liquidity was taken. The close is where the leg in
        ended and the leg out began, and it is the close that the level is
        drawn at.
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
        # MAX_ZONE_VOL from the centre while a rejection needs only
        # resolve_vol, so price clipping the far edge of a wide zone arrived
        # already past the threshold and closed on the next observation having
        # reacted to nothing - 17% of touches, spread evenly across feeds.
        #
        # Only the rejection. A break is defined by the level, and the trap
        # that follows one has to be measured from the level too: `origin`
        # keeps tracking the deepest print while the leg in is still
        # extending, so during a break it follows price *through* the level,
        # and a trap judged against it fires on any small bounce. Measured:
        # traps tripled when this was applied to both.
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

        Checked before anything is read from `price`, because a touch open this
        long spans a period nobody observed and where price sits *now* says
        nothing about what this level did. The movement tests in `update` would
        otherwise read the reopening gap as a decisive reaction - a weekend on
        EURUSD resolving as a 27-volatility-unit rejection, which is the market
        having been shut rather than the level having done anything. Dropped
        without an outcome; see GAP_FACTOR.
        """
        touch = self._open.get(self.key(level))
        if touch is not None and when - touch.started >= self.horizon_for(touch) * GAP_FACTOR:
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
        touch.resolved = when
        self._open.pop(self.key(level), None)
        level.record(side, outcome, touch.push_vol, when)
        if outcome is Outcome.BREAK and touch.broke_at:
            # The retest clock starts when price *got through*, not when the
            # break was confirmed. Confirmation waits out the trap window, so
            # dating it from there spends most of the window before a retest
            # could possibly happen - which is why almost none were detected.
            level.broke_at = touch.broke_at
        self.memory.add(touch)
        return touch

    def open_touch(self, level: Level) -> Touch | None:
        return self._open.get(self.key(level))

    @property
    def open_count(self) -> int:
        return len(self._open)

    def expire(self, when: float) -> list[Touch]:
        """Close out anything that has sat open too long.

        A touch that broke and then went quiet counts as a break: it got
        through and nothing took it back. One that never got anywhere is chop.
        """
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
            touch.resolved = when
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
