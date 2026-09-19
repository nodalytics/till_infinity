# Structures Reactions

Rationale moved out of `till_infinity/structures/reactions.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `Features.distance`

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


## `Inference.direction`

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


## `Inference.net_push`

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


## `Inference.actionable`

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


## `Memory.base_rate_for`

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


## `Memory.neighbours`

        `interval` bands the draw, and leaving it out pools everything as this
        did for its whole life. That pooling is the flaw research/similarity.md
        found, and it is in the training set rather than in the report.

        A touch approached from above that resolves inside a minute resolves
        upward **100.0% of the time**, because that is what a rejection is. So
        46% of the pool is a population where the label is the definition, and a
        1w touch - whose real answer is 52.8%, a coin - drew its neighbours
        from there. A model given free answers learns the free answer.

        Banded by `HORIZON_BAND`, a log-2 bucket of the horizon the touch is
        judged over, so a 1m touch and a 3m touch can still inform each other
        while a 1m touch and a weekly one cannot.

        **Widening is recorded, not silent.** Bands are thin by construction -
        1,762 resolved touches beyond thirty minutes against 30,118 under a
        minute - so a strict band would leave the slow end with nothing, which
        is the cold-start problem pooling was introduced to solve. When a band
        cannot fill k, adjacent bands are added outward; `widened` counts it,
        because a neighbour set assembled from two bands away is weaker
        evidence and nothing downstream can tell by looking.


## `Memory.prior`

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


## `infer`

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


## `Forward`

    **The one thing this desk records about a level that is not an identity.**
    `push_vol` is signed by how the touch resolved together with which side
    price arrived from, which makes it 0% or 100% in every cell - the codebase
    says so in as many words, and it means no rule for choosing a side can be
    scored against it. `excursion_vol` is only assigned once price goes a full
    unit past, giving 42,442 zeros against 12,105 values of 1.0 or more with
    nothing in between. And `path` stops at resolution, which for a touch that
    resolves in zero seconds is never sampled at all.

    So on 2026-09-17, of 6,352 resolved touches in two days, not one carried an
    outcome a direction rule could be tested against. Freshness, confluence,
    push-against-risk - every condition anybody might want to gate on was
    unfalsifiable on our own data.

    This is the missing label: the return from the level, at fixed horizons
    after resolution, **multiplied by the side the call took**. Positive means
    the call was right. Nothing else here has that property.


## `Tracker.update`

        `price` is where the bar closed (or the current mid); `wick` is how far
        it reached - the bar's low approaching from above, its high from below.
        The two are what separate the **extreme** from the **origin**, and with
        only one of them they collapse into the same number: the deepest price
        seen is trivially also the last one before the turn.

        The wick is where liquidity was taken. The close is where the leg in
        ended and the leg out began, and it is the close that the level is
        drawn at.

        An observation older than the touch is refused - see `_live`.

# Structures Reactions

Rationale moved out of `till_infinity/structures/reactions.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `Inference.probability_down`

        There is one number because there are two outcomes: `record` increments
        `ups` when the push was positive, and the beta-binomial's `beta` term is
        `touches - ups`, so everything that was not an up is a down. Asking for
        P(down) separately would be asking the same counter twice.

        The one wrinkle, stated because it is invisible otherwise: a push of
        *exactly* zero falls to the down side of `push_vol > 0`. Push is a
        continuous quantity in volatility units, so this is a measure-zero case
        rather than a lean, but it is a tie broken by an implementation detail
        rather than by evidence.


## `Tracker._live`

        Checked before anything is read from `price`, because a touch open this
        long spans a period nobody observed and where price sits *now* says
        nothing about what this level did. The movement tests in `update` would
        otherwise read the reopening gap as a decisive reaction - a weekend on
        EURUSD resolving as a 27-volatility-unit rejection, which is the market
        having been shut rather than the level having done anything. Dropped
        without an outcome; see GAP_FACTOR.


## `Tracker.carry`

        **Called for every level on every observation, and that is the whole
        point.** This used to sit inside `update`, which reads as though it
        outlives the touch - but `update` is only ever called for a level with
        an *open* touch, so once the touch resolved the follower stopped being
        offered prices and its window closed empty. Production said so
        plainly: 256 of 258 records had every offset absent, and the two that
        filled were levels price happened to come back to and open a second
        touch on. That is precisely the sample `expire` warns about, arrived
        at from the other side.


## `Tracker.expire`

        A touch that broke and then went quiet counts as a break: it got
        through and nothing took it back. One that never got anywhere is chop.

        **Forward returns are flushed here too, and that is not housekeeping.**
        `_carry` only runs when a quote arrives for that level, so a record
        completed only where price stayed near the level it had just left -
        which is the least representative sample there is, and it showed:
        two records in an hour against roughly 130 resolutions. Every other
        follower sat in the map for ever, never journalled and never freed.


