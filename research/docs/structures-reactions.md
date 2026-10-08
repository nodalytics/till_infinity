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


## `Episode`

    **The episode database's row**, added 2026-10-02 (ideas.md Part L, L8). One per
    touch, called or not, opened at first contact and followed for `EPISODE_BARS`
    (48 bars of the level's timeframe), the symmetric race's horizon. Unlike the
    race it does not stop at the first barrier: what happens after 1R is the point.

    R is `EPISODE_R_VOL` (1.5) volatility units at the contact price, fixed at open,
    the same distance the race settles at. Both sides are measured from one path,
    so a long and a short hypothesis are scored together:

    | field | meaning |
    |---|---|
    | `bars_up_{1,2,3}r`, `bars_down_{1,2,3}r` | first passage to 1R, 2R, 3R each way, in bars; null if never |
    | `mfe_up_r`, `mfe_down_r` | the furthest each side went, in R |
    | `mae_at_up1_r`, `mae_at_down1_r` | how far against a side had gone when it reached 1R; ≥ 1 means a stop at 1R would have killed it first |
    | `first`, `held_first` | which side reached 1R first (+1 up, -1 down, 0 neither or ambiguous), and whether that is the way a held level goes |
    | `bars_opposite` | when the other side reached 1R after the first had: the whipsaw's clock |
    | `bars_peak`, `bars_fade`, `velocity_r` | when the leading excursion last grew, when it first gave back 1R from that peak (the expansion's end, two ways), and R per bar to the peak |
    | `kind` | `clean` (2R before the other side's 1R), `whipsaw` (the other side's 1R first), `partial` (1R, no more), `stall` (neither 1R), `ambiguous` (both in one bar) |
    | `probability_up`, `base_rate_up`, `edge`, `actionable` | what was believed at contact, so beliefs can be scored against paths |

    Wicks are used as `advance_races` uses them: an episode that began inside the
    bar being delivered sees only its close. A bar that takes both sides to their
    first 1R is `ambiguous`, never guessed. On a fair coin the first 1R goes each
    way half the time (`tests/test_episodes.py`).

    Journalled by `service.record_outcomes` as an observation with
    `context.shape == "episode"`. Recorded, not used: nothing gates on it.

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

## Inline notes

Passages that stood inside the functions named, moved out on 2026-09-19.
Each keeps its first sentence at the call site.

### `Tracker.update`

MAX_ZONE_VOL from the centre while a rejection needs only
resolve_vol, so price clipping the far edge of a wide zone arrived
already past the threshold and closed on the next observation having
reacted to nothing - 17% of touches, spread evenly across feeds.

Only the rejection. A break is defined by the level, and the trap
that follows one has to be measured from the level too: `origin`
keeps tracking the deepest print while the leg in is still
extending, so during a break it follows price *through* the level,
and a trap judged against it fires on any small bounce. Measured:
traps tripled when this was applied to both.

### `Tracker._live`

the meantime can be handed a bar describing a window it did not exist
in. That resolved 28.9% of outcomes at a negative duration - median
exactly one bar on a 1m series - and anything reading `seconds` off a
resolution was reading a quarter of its input backwards.

Refused rather than clamped: clamping keeps the outcome and lies
about its length, when the bar's range is evidence about a period
before the touch and says nothing about what the touch did. The touch
stays open and the next observation resolves it properly.

### `Tracker._carry`

level quoted once an hour would otherwise have one late price
written into the one-minute, five-minute and fifteen-minute
slots alike - three readings of the same moment, presented as a
path. That is the smear `_walk` refuses, and a test caught this
doing it.
**Relative, like `elapsed`.** `deadline` is an absolute clock
time, so closing the last window with it compared an age in
seconds against an epoch: `900 <= elapsed < 1.79e9` is true for
every quote that ever arrives, and the final offset went back to
being filled by whichever one turned up. The tests missed it
because they resolve a touch at `when=0.0`, where an age and a
clock read the same.


## `PRIOR_WEIGHT`, estimated rather than chosen (2026-10-08)

`infer` blends a level's own record with its neighbours':

    weight = own.touches / (own.touches + PRIOR_WEIGHT)

`PRIOR_WEIGHT` was 4.0, and its docstring says "roughly: borrowed evidence is
worth this much of the level's own". Right shape, guessed number - and what a
guess costs here is not obvious in either direction:

* if levels genuinely differ, the true weight is **smaller** and 4.0
  **over-shrinks**, averaging real idiosyncrasy away
* if levels barely differ, the true weight is **larger** and 4.0
  **under-shrinks**, letting three noisy touches override a pooled estimate
  built on hundreds

Nobody had checked which, and it is not a matter of taste.

### It is a variance ratio with a closed form

`PRIOR_WEIGHT` is the `K` of a shrinkage estimator. The Bayes weight for a rate
observed `n` times is `n / (n + K)` with

    K = sigma_within^2 / tau^2

`sigma_within^2` is the noise in one observation - `p(1-p)` for a rate - and
`tau^2` is the **real** spread of rates between levels. Both halves of the
intuition fall straight out: levels that really differ give a large `tau^2` and
a small `K`; levels that do not give `tau^2` near zero and a `K` that says pool
almost everything.

`tau^2` is estimated by DerSimonian and Laird's method of moments.
**Subtracting the sampling noise is the method, not a refinement**: the spread
of observed rates already contains each level's own binomial noise, so the raw
variance always overstates `tau^2` and cannot tell "levels differ" from "levels
were counted few times".

### How wrong the naive version is, measured

200 identical levels, counted eight times each - so the true `tau^2` is zero
and every scrap of observed spread is noise:

| | `tau^2` | implied `K` | reads as |
|---|---:|---:|---|
| raw variance of the rates | 0.0370 | **6.7** | "these levels differ" |
| after subtracting binomial noise | 0.0060 | **41.7** | "these levels are the same" |

The naive route errs in the direction that costs most: it **under-pools**,
letting a handful of noisy touches override an estimate built on hundreds. The
binomial noise of a rate counted eight times is 0.0312 - almost the whole of
the raw spread, which is exactly what the correction removes.

### What it needs, and the caveat taken seriously

`K` needs enough **levels** in a pool, not enough touches in a level - a pool
of three levels cannot say how much levels differ however often each was
touched. Below `MIN_LEVELS` it returns the constant unchanged, the same run-in
shape `conformal.SETTLE` uses and for the same reason, and it is clamped at
both ends because "indistinguishable" is a claim no finite sample earns
outright.

The estimator's own noise is visible and pinned by a test: on the same
identical-level pool the residual `tau^2` is far larger at 60 levels than at
600. It sharpens with levels, not with touches.

### Why this is not the thing `edge.md` refuted

[`edge.md`](edge.md) found a rolling quantile losing to a matched constant
**four times out of four**, and a walk-forward adaptive probability floor worse
than no floor. That is a strong prior against replacing a constant with
something adaptive, and it is taken seriously rather than waved at.

The difference is what is estimated. Those fitted a **threshold against
returns** - a free parameter tuned until a number looked good, with no identity
constraining it. This estimates a **variance ratio with a closed form** from
the touch counts themselves, with no reference to whether anything made money.
It is the same arithmetic that says a mean of ten samples is worth ten times
one sample.

### Still unmeasured

Whether the estimated weight produces better inferences than 4.0 on real
touches. The fallback means a cold or thin book behaves exactly as before,
which makes it safe and not right - the same distinction the slope and the
calibrated zone sit behind.

## Penetration, and the features the learner could not see (2026-10-08)

Asked what else of the physics-flavoured family - energy, force, velocity,
momentum - was missing. Almost none of it was. The survey is in
[`learned-vol.md`](learned-vol.md); the one term with no implementation was
**penetration**, and chasing it turned up a second problem.

### What penetration is, and why `depth_vol` is not it

    penetration_vol = how far past the level the extreme got, in vol units

`depth_vol` is `abs(level.distance_vol(price, vol))` at **arrival** - where
price was when the touch opened. Penetration is the furthest the move ever
reached on the level's **far side**, kept as a high-water mark.

They separate outcomes arrival cannot:

| | never crossed | crossed, came back | crossed, stayed |
|---|---|---|---|
| outcome | reject | **trap** | break |
| `depth_vol` | can be identical | can be identical | can be identical |
| `penetration_vol` | **0** | **> 0** | **> 0** |

A reject and a trap can arrive at exactly the same depth, and only one of them
got through. That is the whole case for the feature, and the tests are written
as that comparison rather than as a number.

Measured against the level **price** rather than the zone edge, with `risk_vol`
published beside it, so a consumer can compare the two instead of being handed
a subtraction it cannot inspect.

### The second problem: `Touch.to_dict` is not what gets journalled

`Touch.energy` - `departure_vol / approach_vol`, "how much harder it left than
it arrived" - has been computed since it was written and read by **nothing**.
It appears once in `structures` (its own definition) and zero times in
`trading`.

The reason is not that nobody wanted it. The outcome context in
`service.record_outcomes` is **hand-assembled**, field by field, and it is not
`Touch.to_dict()`. A property can be added to the touch, published in its
`to_dict`, and still never reach the journal - which is what happened. Both
are now written into that dict explicitly.

### And `slowing` was measured but not an input

`force.md` gave `slowing` an **AUC of 0.5237 in band** over 10,871 resolved
touches, and it sits in `context/registry.py`'s roster with that number beside
it. It was not in `facto.NUMERIC`, so the factorisation machine learning from
level outcomes could not see it.

That is the same shape as the envelope features in October: computed,
published, invisible to the thing that learns. `slowing`, `penetration_vol` and
`energy` now join the FM's inputs - and an FM is the right consumer for them
specifically because it models how features **combine**. How hard price
arrived, how far through it got, and how much harder it left are three angles
on one event, and an additive model cannot say that a hard arrival which
penetrated and left slowly is different from the sum of those three.

`penetration_vol` and `energy` are saturated like `approach_vol` and the rest -
both are ratios over a volatility estimate, so a touch in a dead pocket divides
by a small number and arrives arbitrarily large. `slowing` is already bounded
and is not.

### Unmeasured

Whether any of the three adds anything. They are offered to a supervised model
that reports `model_mae` against `baseline_mae` and `levels_mae`, so a feature
that does not help will show up as not helping - which is the reason to put
them there rather than into a hand-written gate.
