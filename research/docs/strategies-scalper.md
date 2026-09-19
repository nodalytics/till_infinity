# Strategies Scalper

Rationale moved out of `till_infinity/trading/strategies/scalper.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `LevelStrategy._parked_stop`

        Zero for a market entry, which is most of them, and the caller takes
        the smaller of this and the ordinary distance - so this can only ever
        tighten a stop, never widen one. A setting that could widen would be a
        way to increase risk through a field named for reducing it.

        **Zero as well for a trade held longer than `PARKED_STOP_HOLD`**, and
        that bound is the correction of a real mistake. The tighter stop was
        adopted from a replay grid, and the grid was scored over resolutions
        with a median life of eighteen seconds; it says nothing about a
        position held for thirty minutes. Stop width has to match hold length,
        and applying a short-hold number to a long-hold trade is how five gold
        sells were stopped inside a point and a half on a day gold fell
        twenty-eight.


## `LevelStrategy.stop_floor_vol`

        `min_stop_vol` is denominated in **one bar** of the entry interval,
        because that is what `vol_bps` measures. The trade is held for many
        bars, and volatility grows with the square root of time - measured on
        our own instruments, not assumed - so a one-bar stop on a thirty-bar
        trade sits inside the noise it has to survive and is taken by ordinary
        wandering rather than by the level failing.

        Scaled by `sqrt(hold_bars)`, capped by `max_stop_scale`. The cap is
        there because the uncapped number is large enough that
        `reward_to_risk` refuses nearly everything - possibly the honest
        answer, but not one to arrive at without deciding to.


## `LevelStrategy._aim`

        **The stop and the target were computed from unrelated quantities.**
        The stop comes from the call's risk estimate and a floor; the target
        from the modelled push. Nothing tied them, so a floor that widened the
        stop left the target where it was and the trade went on at whatever
        reward-to-risk fell out - 0.37 for `thesis-only`, measured over 159
        closed trades, against the 73% win rate that geometry needs.

        `reward_floor` is zero everywhere by default, so this returns exactly
        what it always did unless a shape asks otherwise.

        The two distances are anchored differently - the stop from the level,
        the target from the entry - and this compares them in volatility units
        as though they were not. That is a small error next to the one it
        fixes, and it is the same approximation `reward_to_risk` already makes.


## `LevelStrategy._anchored_stop`

        `stop_for` anchors it beyond the level's zone, which is the right place
        to decide the trade is wrong: the level is the thing being traded, and
        the invalidation should not move because the spread did.

        What that leaves open is the fill. `distances` floors the stop at
        `min_stop_vol` measured **from the level**, and says nothing about how
        far the entry ended up from it. Entry is market, so it lands wherever
        price is when the call arrives, and it can land most of the way to a
        level-anchored stop - hardest on `approach-scalp`, whose whole geometry
        is entering away from the level it measures.

        Sizing then uses `abs(entry - stop)`, correctly, because that is what
        is actually lost. The two together are the failure: a fill one unit
        above its own stop is sized as a one-unit trade, which is a large one,
        and is then taken out by ordinary movement rather than by the thesis
        breaking. That is the loss this was written after - a gold buy filled
        1.0v above a stop sitting 5.9v below the level, sized 0.18 lots on the
        short distance, stopped within minutes.

        So the floor is applied twice, from both anchors. It can only ever push
        the stop further from the fill, which only ever reduces size for the
        same money at risk. It never moves a stop closer in.


## `LevelStrategy._short_of`

        A target sitting exactly where everyone else is watching fills last.
        Price stalls *at* a level rather than through it, so the final fraction
        is the part most often not given - and giving it up costs a known
        small amount to avoid an unknown larger one. `approach-scalp` has
        always done this; this is the same idea for every other target.

        Applied after the strategy has aimed, so an override that already
        stands off - the next level minus a buffer, the opposite origin's near
        edge - gets the same treatment and does not have to remember to.

        **Never past the entry.** A buffer larger than the move would invert
        the trade, and a target behind the fill is not a smaller target.


## `ConfluenceScalp`

    The intuition is the one the level model states about itself: a price that
    several timeframes independently placed a level at is one structure seen
    several times, the higher carrying the significance and the lower the
    placement. Taking fewer trades for that reason is paid for with half a
    volatility unit more room on the stop, since a confirmed level is not a
    more *precisely located* one.

    **The only measurement bearing on this says breadth does not predict.**
    [strength.md](../../research/strength.md) tested confluence depth against
    whether a level holds and found nothing, in the strongest form of nothing:
    four runs produced four different orderings - best at depth 1, at depth 2,
    monotone increasing, and best at depth 3 - and as a ranking signal depth
    scores an **AUC of 0.476 and 0.452**, below the 0.5 that means no
    information at all. `depth >= 3` against `depth < 3` came out -2.2
    [-6.3, +1.7], -5.2 [-9.4, -1.2] and +0.3 [-4.2, +4.9]; not one interval
    excludes zero in the direction this strategy assumes. That document also
    calls `Zone.strength`'s existing `1 + 0.15 x (depth - 1)` multiplier
    "unearned on this evidence".

    So why is this still here. Two reasons, and neither is that the measurement
    is wrong. First, what it measured is *did price get through the level*, and
    strength.md is explicit that this is not the same question as *did the
    trade make money* - a level that holds after a 3v excursion is a hold and a
    loss. Second, this uses depth to **select** rather than to weight, and a
    filter that halves the trade count is a different object from a multiplier
    on a score.

    Both of those are excuses until something measures them, so treat this as
    **unvalidated and probably not better than `level-scalp`**. It is kept as a
    named strategy precisely so the journal can settle it rather than having
    the assumption buried as a flag inside the default.

    ## 2026-09-11: ride's exit and sweep-aware's gate

    Turned back on with both, because the live record says its problem is not
    what it enters - it is what it does afterwards. Over ten closes it reached a
    mean high-water mark of **+1.401R** and realised **-0.357R**: it gave back
    **1.758R a trade**, the largest give-back of any strategy on the book, and
    lost 92 units doing it.

    A strategy that is right about direction often enough to average +1.4R of
    open profit and still loses money has an exit problem, and this one had no
    exit policy at all - a fixed target at one push, no trail, no protection.
    `Ride`'s exit was measured over 31,820 replayed touches as the best of six.

    **And unlike `sweep-aware`, its break-even can actually engage.** That
    matters more than it sounds: `sweep-aware` protects at 1.0R and its median
    trade peaks at 0.445R, so the rule fires on 11% of its trades and the other
    89% ride to the hold timeout giving back whatever they made - one
    `break even` line against 104 `trailing` lines in a day of logs. This
    strategy's mean peak is 1.401R, which is the regime those numbers were
    chosen for.

    The sweep gate comes too, on the argument the presets table makes: it and
    `level-scalp` are the same point apart from an entry gate, so if the gate is
    worth having it is worth having here. Its wider stop makes the gate bite
    harder - `stop_multiple` 1.5 against sweep-aware's 1.0 - which is the gate
    doing its job rather than a setting that needs matching.

    **All of this is a repair, not a claim that the strategy works.** The
    breadth premise is still what strength.md refuses to support, and ten closes
    cannot settle an exit policy. What it can do is stop the record being about
    a question nobody asked.


## `MomentumScalp`

    score.md §2 keeps three exponential averages of its score and treats their
    agreement as the confidence: "the fast line is what is happening, the slow
    line is the context". The same three speeds are kept here over the *signed*
    edge of the calls arriving for each instrument, and a trade is taken only
    when all three agree with the direction it states.

    What that buys is a filter against calls fighting their own context - a
    short at a level while every recent call on that instrument has been long.
    What it costs is the turn: the trade at the exact moment a move reverses is
    precisely the one all three lines disagree with, and this strategy will
    always miss it. That is the trade-off, not a defect, and it is the reason
    this is a separate strategy rather than a filter added to the default.


## `Snap`

    Every other strategy here holds for a fraction of an hour. Measured over
    53,372 resolutions, that is roughly a hundred times longer than the event
    it is trading:

    | resolved within | share | median push |
    | --- | ---: | ---: |
    | 30s | 53.1% | 2.47v |
    | 60s | 63.5% | 2.41v |
    | 120s | 72.2% | 2.33v |
    | 300s | 84.1% | 2.24v |

    **The median touch resolves in eighteen seconds**, and the fast ones carry
    the *larger* push - 2.47v inside thirty seconds against 2.24v for
    everything. Holding longer does not get more of the move; it gets less of
    it, on a resolution that has already happened, while remaining exposed to
    whatever comes next.

    That reframes two failures this session kept producing. A trade stopped
    before its move arrived and a trade that gave back profit are both what
    holding a twenty-second event for thirty minutes looks like from the
    account. This strategy holds for `hold_seconds` instead and lets the clock
    be the exit rather than the accident.

    **It is the same call as `level-scalp` with one difference**, deliberately,
    so the comparison says something. Same entries, same anchors, same stop
    rule, same target. Only the hold changes.

    A caveat on the measurement it rests on: about a tenth of recorded
    resolutions carry a negative duration, from bar timestamps being compared
    against quote clocks - a bug the tracker documents. The very fastest tail
    is therefore partly artefact. The median at eighteen seconds and the
    thirty- and sixty-second shares sit well clear of it.


## `ThesisOnly`

    Six of twelve stopped trades later reached the target they were aiming at,
    by between 3.7R and 25.7R - so the direction the level model produces is
    largely right and something in the execution is giving back money the
    thesis earned. That is a hypothesis, and every fix for it so far has been
    another adjustment to where the stop goes. This tests it directly by taking
    the stop out of the decision entirely and letting the trade end on its
    target or on the clock.

    **It is not stopless, and the difference matters.** A genuinely stopless
    trade on a leveraged account is how accounts die, and it would also break
    sizing - `lots` derives position size *from* the stop distance, so with no
    stop there is no size. What this does is move the stop far enough out that
    it stops being a trade decision and becomes a circuit breaker: at
    `thesis_stop_vol` volatility units it should almost never be reached, and
    when it is, something has gone wrong that no thesis anticipated.

    Money at risk is therefore unchanged and bounded exactly as everywhere
    else. What changes is that the position is much smaller, because the same
    risk spread over a stop several times wider buys proportionally fewer lots
    - which is the honest price of giving a trade room, and is itself part of
    what the comparison will show.

    **What it is for.** Run beside the others on the same signals it becomes a
    controlled comparison: same calls, same gates, same sizing rule, one
    difference. If it beats them, the stops were the problem and the fixes have
    been treating a symptom. If it loses, the theses were wrong and no amount
    of room would have saved them - which is worth knowing before another
    session is spent moving stops around.


## `Inverse`

    Every strategy here trades the direction the level model names, and the
    account has been going down while doing it. Two explanations fit that
    equally well from the outside: the direction is right and the execution
    gives it back, or the direction is wrong and better execution would only
    lose money faster. Everything built this session has assumed the first.
    Nothing has tested the second.

    This tests it directly. It takes the calls the model likes *best* - the
    gates run unchanged, on the side the call named, so it selects the same
    signals `level-scalp` selects - and then trades the opposite side. Same
    entries, same anchors, same stop rule, same target. One difference, and it
    is the one that matters.

    **What each outcome would mean.** If this loses roughly what the others
    lose, direction is not the problem and the execution work is aimed
    correctly. If it wins, the direction model is worse than nothing and the
    entries, stops and trails have been polishing a sign error - which would
    be the single most valuable thing this repo could learn, and the cheapest
    way to learn it is to have run the control from the start.

    **It is not a prediction that the model is backwards.** Anti-correlation
    strong enough to trade is rare and usually turns out to be a measurement
    artefact. The expected result is that it loses, and a control that is
    expected to lose is still worth running, because the alternative is
    continuing to assume the answer.

    A caveat that will matter when this is scored. The gates are
    direction-aware - the probability floor is a per-direction percentile, the
    base-rate floor reads `base_rate_up` - so this is not a clean sign flip of
    the whole system. It inverts the *trade* while keeping the *selection*,
    which is the comparison that isolates direction. A version that also
    inverted the selection would be a different strategy and a different
    question.


## `zma_gate`

    Two conditions, and the second is what makes this defensible.

    **It reads the number, not the state.** `structures/zma.py` publishes both:
    `zma_agrees` is the flag - oversold *and* momentum already turning - and
    `zma_z` against `zma_strong` is the displacement it was thresholded out of.
    `research/adapting.md` put the two against each other at an identical bet
    count on three OU controls and the continuous reading won every time, by
    0.504 against 0.562, 0.578 against 0.603, and 0.646 against 0.724. **The
    percentile threshold is a loss, not a filter.** The flag is still carried in
    `features` for the alert and the journal; the decision uses the number.

    **And it defers to what that feed's z-score has actually done.** The book
    scores every continuous call against the next bar, per feed and timeframe,
    and the counts ride along on the signal. Below `ZMA_MIN_CALLS` there is no
    record and this does nothing; at or below a coin it does nothing either.

    That second condition is not caution for its own sake - it is the only
    thing standing between this gate and the Boom and Crash families, where the
    reading is an **anti-signal with a mechanism**. Those series drift slowly
    one way and spike the other, so the long drift leaves the z-score
    persistently stretched and the spike is what finally turns it back; a
    reading taken then calls for continuation at the moment the drift resumes.
    `adapting.md` measured the flag at a 0.119 and 0.164 hit rate there and
    `zma.md` at 0.376 to 0.461 independently. A veto driven by that would
    refuse the *correct* side, and it would do it most confidently on the
    instruments where one loss is largest.

    Deferring to the per-feed record handles it without anybody maintaining a
    list of which families spike, which is the same reason `consensus_vol`
    settles estimators by their record instead of by argument.

    Read off the call's stated direction rather than the traded side, the same
    way `quality` is: the gates deliberately run before `orient` and
    `_better_side`, so a strategy that trades against the call still selects
    from the calls the model liked best.


## `sweep_gate`

    Lifted out of `SweepAware.accept` when `confluence-scalp` was given the same
    gate, so the two cannot drift apart. `stop_multiple` is read off the
    strategy rather than assumed, which matters: `confluence-scalp` stops 1.5x
    wider than `sweep-aware`, so the same level can stand in open ground for one
    and in front of the pool for the other. That is the gate working, not an
    inconsistency - what it judges is where *this* strategy's stop would sit.

    Two pieces of evidence, both from `structures.sweeps`:

    * `sweep_rate` - the share of this level's decisive interactions, from this
      side, that were price through and back.
    * `liquidity_beyond_vol` - how far to the next level out, on the side a
      sweep would travel.

    Replayed over 54,873 calls it refuses 12,617 as `in_front` and 389 as
    `swept_often`, so it is overwhelmingly the geometry doing the work and not
    the level's own history.


## `SweepAware`

    `level-scalp` places its stop outside the level's zone and stops thinking
    about it. This one asks the further question: is that stop sitting between
    price and the next obvious pool of resting orders. If it is, a run at those
    orders takes this one on the way, and the trade is closed by a move that
    was never about it.

    Two pieces of evidence, both published by `structures.sweeps` and both
    derived from what is already recorded rather than declared:

    * `sweep_rate` - the share of this level's decisive interactions, on this
      side, that were `TRAP`: price through and back. A level that has been run
      four times in ten is telling you about itself directly, and no geometry
      has to be inferred to hear it.
    * `liquidity_beyond_vol` - how far to the next level out, on the side a
      sweep would travel. Close liquidity beyond is a reason for price to run
      this one; nothing within reach means the stop is not in front of an
      obvious target.

    The ratio of the two is what gets judged. A stop at 1.2v with liquidity at
    1.0v beyond sits *past* the pool, which is the worst place to stand; the
    same stop with the next level six units away is standing in open ground.

    **It refuses rather than adjusting.** Widening the stop to clear the pool
    would keep the trade and change what it costs, which sizes a worse trade
    smaller rather than declining it - and the sizing already assumes the stop
    is where the thesis is wrong, not where it is convenient.

    Unvalidated, like everything else here. The prior from elsewhere is
    discouraging for anything in this family, which is a reason to measure it
    against `level-scalp` on the same signals rather than to skip it.


