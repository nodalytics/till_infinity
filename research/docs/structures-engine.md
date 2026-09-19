# Structures Engine

Rationale moved out of `till_infinity/structures/engine.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `_interval_log`

    **The largest single separator measured on this book.** Break rate by the
    interval a level was drawn on, over 126,296 resolutions lasting five
    minutes or more, against a 33.1% base:

    | 1m | 3m | 5m | 15m | 30m | 1h | 2h | 4h |
    | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
    | 57.9% | 26.8% | 20.4% | 12.8% | 2.8% | 1.4% | 0.0% | 4.3% |

    Monotone, and a fortyfold spread. `Breaks` could not see it: its features
    are scale-free by construction, which is exactly why the timeframe is
    orthogonal to them and why it was not already captured. Adding it takes
    that model from 0.5999 to **0.7542** AUC on the five-minute cut.

    Logged rather than raw: the seconds span 60 to 604,800, and a linear fit on
    that range is dominated by its top end.

    **The confound, stated because it is real.** A break is defined relative to
    the level's own scale, and a 1m level's scale is smaller - the move that
    breaks a 1m level is a rounding error at 4h. So part of this is
    definitional. What carries it anyway is that the money says the same thing
    with no scaling involved: sub-15m is -821.75 over 129 closes against
    +35.03 over 21 at 15m and above.


## `_widen_to_origin`

    **Only when the level is inside one.** `in_origin` is the condition: a
    level that happens to have an origin somewhere nearby is an ordinary level,
    and stretching its zone towards an unrelated one would put stops where
    nothing has ever been defended.

    The zone is the band a stop has to clear, built from how far wicks have run
    past the level. When the level coincides with an origin - the last opposing
    bar before an impulse that broke structure - the interest left stranded
    there is the thing price reacts to, and its far edge is further out than
    the wick average knows. A stop inside it is stopped by the rejection the
    trade is trading.

    The level price itself does not move. Every statistic the level owns is
    recorded against that price, and shifting it would silently re-key history
    that was measured somewhere else.

    Union, never contraction: an origin narrower than the observed wicks does
    not make the wicks smaller. The zone can only widen.


## `Quotes`

    The same argument as `Consensus`, for the stream that needed it more. Bars
    got a median across venues and quotes did not, so `check` was called with
    whichever venue published last - and venues do not agree on the price.
    Measured across a five second window: 6.12bps between venues on US500 and
    5.74 on BTCUSD, which in each instrument's own volatility units is **3.46**
    and **1.09**. `resolve_vol` is 1.5, so on spx500 two consecutive quotes
    from different venues looked like a three-and-a-half unit move and opened
    and closed a touch between them, having observed nothing but a change of
    publisher.

    That is why spx500 and btc led the instant-resolution table at 41% and 39%
    while gold and the FX majors, whose venues agree to within a twentieth of a
    unit, sat near zero.

    Held per feed rather than per (feed, interval): a quote has no interval, and
    the mid is the instrument's price whatever chart is being tested against it.


## `Engine.forget`

        **The state grew to six times the book and nothing ever shrank it.**
        Measured on a live 206MB save: `_series` held **3,280 entries across 349
        feeds** and `vol._by_key` **5,416 across 445**, for a desk that trades
        **53 instruments**. Together they were 324MB of a 552MB state, and that
        state costs 1.33GB resident - the structural half of the OOM kills that
        `research/starving.md` records.

        The feeds are crypto swaps, and the interesting part is *why capping the
        collector did not stop them*. `PRICES_CCXT_TOP=25` bounds how many are
        discovered **at any one moment**; it says nothing about how many are
        discovered over a month, because the top twenty-five by volume
        **rotates**. 235 distinct crypto feeds had produced a bar within three
        days of that save. A rotating window against a store that never forgets
        is unbounded by construction, and no value of `TOP` fixes it.

        So the bound has to live here, where the state does. Two rules:

        * **Outside the universe.** When `keep` is given, a feed not in it is
          dropped outright. That is immediate and is what reclaims what has
          already accumulated.
        * **Gone quiet.** A feed whose most recent bar, across *all* its
          intervals, is older than `forget_feed` seconds. Per feed rather than
          per series on purpose: a 1w series gets one bar a week and would look
          abandoned every time, while a live feed's 1m series updates
          constantly. This is the rule that handles rotation once the universe
          filter is not set, and the safety net when it is.

        `keep=None` with `now=0` is a no-op, so an unconfigured desk behaves
        exactly as it did.

        What is **not** dropped is anything pooled: the learner's tree, the
        shape library, the regime labeller. Those are trained on scale-free
        features precisely so what they learned from a feed outlives the feed.


## `Engine.origins_bracketing`

        The **space price can travel before it meets unfilled interest**, which
        is what a swing target is asking for and what a confluence zone cannot
        answer. A zone is a price several timeframes drew a level at; an origin
        is a price a violent move began from, so the interest that stopped the
        last advance is still sitting there.

        Measured on 2026-09-07 over 4,117 published calls, the two disagree by
        an order of magnitude: at 4h the confluence box runs **385bps** against
        the origin box's **71bps**, and the confluence one is wider on 2,711 of
        2,724. A 3.85% box is not something a day-long trade traverses, so the
        wall it named was not a target - it was open air with a price on it.

        Near edges rather than centres. An origin is a band, and the tradeable
        room ends where the band starts: `high` for the one below, `low` for
        the one above. Using the centre would put the wall inside interest that
        has already begun defending.


## `Engine._note_change`

        One `Focus` per direction per (feed, timeframe), reset when it fires, so
        what is recorded is a **discrete call** rather than a level sitting
        above a line. `research/agreeing.md` is the measurement.

        **The scale has to be this timeframe's own.** A typical 1h step dwarfs a
        typical 5m one, so a single unit across the four would leave the slow
        detector firing on every bar and the fast one on none - and the count
        those produce would be a fact about the scale rather than about the
        market. `self.vol.of(feed, interval)` already keeps one estimate per
        pair for exactly this reason.

        Called once per *bar*, not once per venue row, for the reason the
        volatility update beside it gives at length: `Consensus.observe` answers
        again on every venue past quorum, and folding the same close in
        repeatedly feeds a run of zero steps.

        Silent on anything it cannot compute. A change reading nobody has yet
        is a missing feature; a wrong one is a number in the journal that looks
        like evidence.


## `Engine._learn_vol`

        Everything gathered here is a **leading** input or a bar shape the
        existing estimators cannot express, which is the only reason this is a
        separate call rather than part of `Volatility.observe_bar` - a
        per-series estimate has no route to the clock or the change detectors.
        See `vol.Book.learn`.

        `hour_share` is the one worth pointing at. `sessions.Clock` has been
        computing each instrument's volatility by hour of day, as a share of
        its own daily mean, and publishing it on every call. **No volatility
        model has ever read it**, which is odd given it is the one input here
        genuinely known in advance: the London open is violent tomorrow for the
        reason it was violent today.

        Silent on anything it cannot get. Every argument to `learn` has a
        default meaning "no reading", so a missing collaborator degrades this
        to the price-only feature set rather than dropping the bar.


## `Engine._settle_projection`

        **Not inside `_learn_vol`, and the move is the point.** It sat there
        first, which put it behind `STRUCTURES_VOL_LEARNER` - a flag about a
        different model entirely. Turning that off would have stopped this
        accumulating with nothing to say so, and a feature that is silently
        inert while its own flag reads `1` is the exact failure this desk hit
        twice on 2026-09-12. It is gated by `STRUCTURES_PROJECTION` and nothing
        else.

        A bar's **open is the price at `t` and its close is the price at
        `t + interval_seconds`**, so one closed bar is a complete, already
        paid-for observation of a one-bar-ahead forecast: no previous-bar
        bookkeeping, and both prices already in hand.

        What accumulates is not a forecast score but an **identification**.
        `projection.py` carries both drift conventions Deriv's recursion could
        be running - they differ by `sigma^2 T / 2` - and scores each by the
        probability integral transform. Whichever calibrates is the one the
        generator uses, which is a fact about the venue obtained from
        arithmetic the desk was doing anyway.

        Swallows its own failures, like every other reading on the bar path
        that nothing gates on: two outages this month were a fault in here
        taking the whole structures service down.


## `Engine.changing`

        The published reading, and it is a **count** rather than a flag because
        that is what was measured: one timeframe alone is followed by price
        giving back 1.24v a day out and three or more by it continuing 7.92v,
        at a matched realised move. A flag would collapse the two events the
        measurement exists to separate.

        Absent rather than zero when no timeframe has a detector yet - a
        missing key is a missing reading downstream, and a zero is the claim
        that four timeframes looked and none of them saw anything. Those are
        different and the journal has to be able to tell them apart. This is
        the rule `LevelRange.features` already follows.


## `Engine._capture_fine`

        **The whole point is the timing, twice over.** Attempting this when an
        origin is finally detected refined one 4h origin in 924, because on 4h
        that is hours to days after the turn and the 1m window holding eight
        hours has moved on. Attempting it on the *newest* bar failed
        differently and completely: the newest bar is the one still forming, so
        its span runs into the future and the finer series can never cover it.
        Production captured a few percent of 3m through 30m bars and **zero**
        of 1h, 2h, 4h, 1d and 1w.

        A bar is complete exactly when the next one starts, so the last two are
        offered: the one before the end, which has certainly closed, and the
        end itself, which will fail until it has. Cheap, since `extremes_in`
        refuses partial cover before doing any work worth counting.

        Silent when the finer series does not cover the bar - a pair that could
        not be computed never overwrites one that could.


## `Engine._remember_origins`

        **The refinement has one moment to happen and this is it.** `refine`
        relocates an origin to the transition inside its own bar at 1m, and
        `research/swinging.md` measured what the band that follows is worth to
        the swing strategy: +0.349R a trade becomes **+0.576R**, winning in all
        eight cells of the sweep. That gain was unreachable while origins were
        recomputed from the closes series on every call, because a 1m series
        holds about eight hours and by the time a wall is wanted its minutes
        have scrolled away - a replay limited to that window reproduced the
        unrefined baseline identically, in every cell.

        So the origin is refined when it first appears, while its fine
        evidence is still in the window, and the answer is kept. `Origins` is
        `Restorable` and this dict rides on the engine, so a refinement
        computed today survives a restart and is still there in a month.

        Falls back to the fresh detection if anything here fails: an origin
        with a coarse band is the previous behaviour, and no band at all is a
        feature silently missing from a call.


## `Engine._origin_at`

        An origin is where a violent move began - the last price in the
        previous direction before the new one took over - and the zone is the
        last bar of that opposing leg. A level that coincides with one is
        sitting on interest that was placed and not filled; the same level in
        open space is not. See `structures/origins.py`.

        **Recorded, not acted on.** Nothing gates or sizes on these yet. They
        go on the call so the journal can say whether a level inside an origin
        behaves differently from one outside it, which is the only thing that
        would justify acting on it. That is the same order this repository got
        wrong with `reward_to_risk` and right with `strength`.

        Wrapped, and deliberately. Two production outages this month were a
        fault in this engine stopping the whole structures service, and an
        annotation nobody reads yet is not worth a third. A failure here costs
        the features on one call.


## `Engine.draw_with`

        A method rather than two lines in `__init__` because it has to be
        callable **after a restore**, and that is not a refinement - it is the
        correction of a setting that was inert for its whole life. `Watcher.load`
        replaces the freshly configured engine with the pickled one, so a
        deployment that asked for three passes got whichever one the state file
        was first saved with and kept it across every restart. Production ran
        `pip` alone while `STRUCTURES_FORMATION` said `pip,run,origin`, and the
        only visible symptom was that `run` and `origin` never drew anything -
        which reads exactly like two formations that do not work.

        Levels already formed are not redrawn. They are evidence gathered under
        the old geometry and throwing them away would cost the touch history
        that makes them worth holding; what changes is how the next reform
        draws, which is where the agreement between passes comes from.


## `Engine.__setstate__`

        Unpickling rebuilds `__dict__` directly and **never calls `__init__`**,
        so every attribute added since a state file was written is simply
        absent from the restored object. That is not theoretical: adding
        `_touch_eras` took the whole structures service down on the next
        deploy - restored models, then `AttributeError` on the first bar, five
        seconds after start. Nothing consumed the bus afterwards, so the
        symptom was dropped quotes and a silent journal rather than anything
        naming the cause.

        Filling the gaps from a default-constructed engine rather than from a
        hand-written list of names, because the hand-written list is the part
        that goes stale - it would need editing every time a field is added,
        which is precisely the thing nobody remembers to do. Anything the state
        carries wins; anything it lacks arrives at its default.


## `Engine.touch_interval`

        The finest one available *at that moment*, which is not the same as the
        finest one overall and is the whole subtlety here. Venues keep far less
        fine history than coarse - Yahoo serves seven days of 1m against
        decades of 1w - so a replay of a few hundred bars per interval covers
        hours at 1m and years at 1w. Pinning the touch check to the globally
        finest series therefore leaves every earlier era untouched: on gold,
        1w and 4h opened *zero* touches across 20,159 replayed bars, and their
        levels were then pruned for never having been visited. Twenty-one
        levels became four.

        So the touch source changes as history advances. Before 1m data begins,
        the finest thing that exists carries the check; once it begins, it takes
        over. Each era is touched at the best resolution that era actually has,
        which is what "from the finest bars available" was always meant to say.


## `Engine.observe_bar`

        **Forming and touching are separate jobs**, and this used to do both at
        one resolution. A daily level warmed from daily bars had its origins
        quantised to the day - and since a cold start replays six-figure bar
        counts, that was most of what any level knew about itself.

        So: every bar forms levels for its own interval, and only the *finest*
        interval's bars run the touch check, against every interval at once.
        That is the replay equivalent of `observe_quote`, which has always
        checked every interval on every quote and is why the live path never
        had this problem.

        The trap the doc warns about is running both - keeping the per-interval
        check and adding a fine-grained pass on top, which would count every
        interaction twice. The `return []` below is what avoids it: a coarse
        bar forms and then stops, rather than also touching.


## `Engine.cost_of`

        The same quantity on every instrument and timeframe, which is the only
        way it can be compared against an expected push measured the same way.
        A spread of 3bps is nothing on a violent daily chart and most of the
        move on a quiet 3m one - in units, that difference is the answer rather
        than something a reader has to hold in their head.

        A **median** over a recent window, for the reason the consensus is also
        a median: a mean is dragged by the outlier it exists to ignore. The cost
        that matters is what this instrument normally costs to trade, not
        whatever the spread happened to be in the microsecond a level was
        touched - one wide print during a release must not disqualify an edge
        that is ordinarily takeable. An exponential average was tried first and
        is not good enough here: at a 0.1 weight a single hundred-fold print
        moved the charged cost tenfold, which would silence a whole instrument
        for as long as it took to decay.


## `Engine.trading`

        Judged on **bars**, because quotes keep arriving after a market shuts.
        On a Saturday morning the FX venues were still answering every poll -
        quotes sixteen minutes old - while the last 3m bar was nine hours old.
        Those quotes carry Friday's closing price, and price that cannot move
        is not price arriving at a level.

        Without this, an instrument that had closed still opened touches on its
        frozen price and published directional calls for them: USDCNH and
        AUDUSD both alerted on a Saturday, with a `down 97%` on a market where
        nothing could go anywhere.

        `GAP_FACTOR` is the same judgement applied at the other end - it throws
        away a touch that *spans* a closure, because the reopening gap is not a
        reaction. This stops one being opened inside a closure at all.

        Silent about instruments it cannot judge: no series, or none yet, means
        no evidence of a closure rather than evidence of one, and crypto - which
        genuinely trades all weekend - keeps printing bars and passes.


## `Engine._drain_expired`

        `Tracker.expire` closes them, sets an outcome and folds them into the
        kNN memory - and its return value was discarded, so that memory was the
        only place they reached. No `level.record`, no Kalman update, nothing in
        `_resolved`, so nothing in the journal and nothing in `facto`. Measured
        on a replay of the stored bars: 26.7% of all resolutions, and because
        it is where a break that got through and went quiet resolves, 97.5% of
        breaks. The break rate downstream read 0.3% against a real 8.2%.

        Touches are keyed by (feed, price) and `expire` hands back only the
        touch, but a `Touch` carries its feed, interval and level price, so the
        level can be found again without the tracker holding a reference to it
        - which matters, because the engine is pickled and a new field would
        have to be migrated.


## `Engine.vol_for`

        Bar intervals have their own estimate and should use it. **Session
        periods do not have one at all**, and that is what made pivots inert.

        `_roll_sessions` already knows this - it builds pivots with
        `reference(feed)` because a session structure is priced at today's
        scale rather than at whichever bar interval happened to complete the
        day. Everything that came *after* the build asked `vol.of(feed, period)`
        instead, and there is no `daily` bar stream to warm one, so it got a
        fresh estimate that was never warm.

        `check` opens with `if not vol.warm: return []`, so every pivot level
        was skipped on the first line, on every bar and every quote, for the
        whole life of the formation. They were built, merged and pruned
        correctly and then never looked at: measured 2026-09-11 on 1,400 bars
        of gold, 4 daily pivot levels formed and **0** of 231 calls came from
        one. That is why `pivot` is identically zero across 20,000 journalled
        outcomes - the feature was not dead, the levels carrying it were never
        checked. See `service.liveness_tally`.


## `Engine.check`

        `low` and `high` are how far the bar reached beyond its close. Both are
        offered and each touch takes the end that faces the side it arrived
        from. Without them the extreme and the origin are the same number, and
        the distinction between where liquidity was taken and where the level
        is drawn disappears.

        `since` is when the bar supplying them **opened**, and it exists to stop
        a range being applied to a touch that did not live through it. A quote
        opens a touch part way through a bar; the bar then arrives carrying a
        low and a high that describe the *whole* period, including the minutes
        before that touch existed. Applied to it, the touch resolves instantly
        on movement that predates it - recording a large push, a duration of
        zero, and `run_vol` of exactly 0.00 because no leg in was ever seen.

        That was **33.6% of production outcomes**, and 41.9% of 3m ones. See
        todo 0g. A touch that began inside this bar therefore sees only the
        close, and picks the wick up on the next bar it genuinely lives through.


## `Engine._slope`

        Least squares of close on bar number over `SLOPE_BARS`, in **volatility
        units per bar** so it pools across instruments - the same scale
        `_speed` uses, and the same one research/slopes.md measured in.

        Returns the current slope and the slope of the window before it,
        because the pair separates two states that look identical from the
        current value alone. A flat slope usually means quiet continues; a flat
        slope that was steep one window ago is a pause inside a move, and over
        10,869 touches lasting five minutes or more it carries a **17.2% break
        rate against a 29.6% base** - the strongest single hold signal measured
        here, and invisible to any feature the engine publishes today.

        Signed, not absolute. The sign says which way the fit points, and the
        consumer decides whether it cares: `Breaks` takes the magnitude, and a
        directional consumer can have the sign for free.

        **Why this is worth the arithmetic.** Over 961,957 samples the slope's
        correlation with the next hour's movement is +0.3470 against +0.1120
        for a rolling volatility over the same window, and it separates inside
        every volatility band - so it is not the volatility estimate wearing a
        different hat. Deriv's generated indices, which have no structure to
        find, give +0.0366: the control says the measurement is not inventing
        it.

        Zero for both when the series is short or the volatility unit is not
        warm, which everything downstream reads as "no reading".


## `Engine._run`

        **This had no producer at all until 2026-09-11.** `features_for` took it
        as a keyword-only argument defaulting to 0.0, and no call site in any
        revision passed one - so the column was 0.0 on every row the journal has
        ever held, and three consumers (`reactions`' kNN metric, `baseline`'s
        logistic, `facto`) carried a dead input each.

        It also produced a published finding. `research/harness/force.py` scored
        the column and got **AUC exactly 0.5000**, which `breaking.py` cited as
        "distance already covered does not matter". An AUC of *exactly* 0.5 is
        the signature of a constant rather than of a null - an uninformative
        feature lands near 0.5 and essentially never on it. That claim is now
        retracted and the question is open.

        Distance from the extreme of the recent window to here, which is the leg
        as `docs/idea.md` means it: not how fast price arrived - `_speed` is
        that, and the two are meant to be different - but how much ground was
        already covered getting here.

        Needs no new state, like `_speed` and `_slowing`: the series window
        already holds the closes. Returns 0.0 when there is no series, no
        volatility estimate yet, or nothing to measure - which everything
        downstream reads as "no reading".


## `Engine._slowing`

        Below one means price is **decelerating** into wherever it is going;
        above one that it is still accelerating.

        A different quantity from `_speed`, and measurably so: over 4,078
        resolved touches the correlation between them is **+0.008**, and
        deceleration separates hold from break at AUC 0.5237 on its own. A weak
        separator uncorrelated with a strong one adds where a second strong one
        would not - see research/force.md.

        Needs no new state. The series window already holds the closes; this
        reads six of them instead of two, which is the whole reason it was
        worth building rather than the reason it was not.

        Returns 0.0 when there is not enough series, or when the earlier leg did
        not move - a ratio against nothing is not a deceleration, and zero is
        read as "no reading" by everything downstream.


## `Engine.seed`

        Without this the engine can only learn from the bus, which carries a
        *notice* per sweep rather than a series - roughly one bar per venue per
        minute. Levels need hundreds, so bootstrapping from the bus alone would
        take days while a backfilled store already holds the history.

        The store is opened **read-only**: the numeric layer reads prices, it
        does not own them, and enforcing that at the driver is cheaper than
        remembering it.

        Bars are replayed in time order through the ordinary path, so levels
        form from confirmed swings exactly as they would live, and the touch
        statistics that make the directional inference work exist from the
        first minute. Calls produced during the replay are discarded - they
        describe touches that happened days ago, and publishing them would
        alert on history.

# Structures Engine

Rationale moved out of `till_infinity/structures/engine.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `Consensus`

    Bars arrive one venue at a time and several venues report the same bar.
    Without this the series took whichever venue published last, and the winner
    changed from bar to bar - so the swing detection was reading a series
    stitched together from different venues, injecting exactly the cross-venue
    disagreement this project exists to *measure* rather than suffer.

    The median is taken across whichever venues have reported that bar so far
    and recomputed as more arrive, so the estimate improves within the sweep
    rather than waiting for a venue that may never report.


## `Series.note_fine`

        By timestamp rather than "the last one", because the last one is the
        bar still **forming** - its span runs into the future, so the finer
        series can never cover it and the capture would never once succeed on
        a coarse interval. Measured in production: 3m through 30m captured a
        few percent of bars and 1h, 2h, 4h, 1d and 1w captured **zero**. A bar
        is complete exactly when the next one starts, and that is when this is
        asked for it.


## `_zma_context`

    **Handed the reading rather than fetching it.** `to_signal` is a method on
    the call, which has no engine to ask - and giving it one would turn a
    reading that is deliberately recorded-and-scored into a dependency of the
    thing that decides, which is the opposite of what `structures/zma.py` says
    this signal has earned.

    Absent rather than zero when it is cold, which is the rule
    `LevelRange.features` follows: a missing key is a missing reading
    downstream, where a zero would be read as a measurement of stillness.


## `_break_context`

    **The broken line travels as a price, because that is what it is for.** A
    level that failed as support is tested as resistance when price returns to
    it, and the return is the tradeable moment - so a consumer needs the price
    itself, not a flag saying a break happened.

    Absent rather than zero when there has been no break: a market that has
    simply been trending has not changed its mind, and a zero price would be
    read downstream as a level at zero. See `structures/breaks.py`.


## `_anchor_context`

    A reading's record is a record of its own horizon: `zma_edge_calls` on a 1m
    series counts one-minute-ahead calls, and a trade stopped on the hour and
    targeted at four hours is not that bet however good those minutes were. The
    two travel together so a consumer can ask the question that matches the
    trade it is about to place rather than the one the entry bar happens to
    answer.

    The record only, not the reading: whether the mother cycle *agrees* is
    already settled upstream by the confluence the call carries, and a second
    answer to it here would be a differently-wrong one. See `zma.ANCHOR`.


## `_read_bars`

    Shaped like a `prices.bars` message so the replay goes through exactly the
    same code the live path does. A separate warm-up path would be a second
    implementation of level formation, and the two would drift.

    A generator rather than a list, and the ordering is SQLite's rather than
    Python's. Materialising the whole warm cost over 330,000 dicts on fourteen
    instruments - 410MB resident against a host with 908MB and no swap - and
    OOM-killed the container on every cold start it attempted. Sixteen kills,
    never finishing. SQLite sorts in its own temp space and hands rows over one
    at a time; the engine only ever needed one at a time.


## `Engine._observe_cycles`

        **Closed, which is why it is on this path and not the tick path.** A
        higher-timeframe bar that has not finished carries the close of a candle
        containing the current fast bar, and a z-score built on it knows where
        the fast bars inside it ended up. `Cycles.observe` ignores an interval
        it does not track, so every bar can be offered to it.

        Swallows its own failures like every other reading here that nothing
        gates on: two outages this month were a fault on this path taking the
        whole structures service down.


## `Engine._form`

        Under `both` the two formations are run as separate passes and merged,
        rather than pooled into one clustering. Pooling would let a bar extreme
        and a run boundary a hair apart form a level *between* them and lose
        which pass found it; merging keeps each pass's own clusters and folds
        them only where one falls inside the other's zone - the same test a
        rediscovered level already passes. `agree` then records that both found
        it, which is the whole reason for doing this rather than choosing.


## `Engine.drop_unsupported`

        `reform` applies the same rule, but only when a series comes due -
        `REFORM_EVERY` is twenty bars, so a 15m series carries levels it should
        not have for five hours after a restart, producing touches and calls
        from them the whole time. The gate was correct and slow, and a restart
        is exactly when it needs to be fast: state restored from disk was
        formed under whatever geometry was current when it was saved.

        Returns how many pairs were dropped, so a caller can say so.


## `Engine.prune`

        A swing price never returned to is not a level, it is a swing. On real
        history most of them are exactly that - warming from a fortnight of
        gold produced 148 levels of which 135 had never been touched - and
        keeping them means every price is near something.

        Two rules, in this order. **Anything with a touch stays**, however far
        away it now is: a level price reacted at is worth remembering precisely
        because price left it. Everything else must be close enough to be
        tested soon, and then only the strongest survive the cap.


## `Engine.regime_changed`

        The drift detector saying the volatility regime changed means these
        levels learned their behaviour in a market that no longer exists. They
        are still levels; their statistics are just much weaker evidence now.

        `severity` is the change's percentile among past changes, so a marginal
        change costs a level little and a violent one costs it most of its
        history. A flat discount would treat both the same.

## Inline notes

Passages that stood inside the functions named, moved out on 2026-09-19.
Each keeps its first sentence at the call site.

### `Series.add`

Evicted alongside the window it belongs to.

**`window_for(self.interval)`, not the module constant.** These two
halves have to agree: the trigger counts entries and the filter keeps
everything back to `times[0]`. With one window they did. With a window
per interval the fine series holds 1,500 bars of `times` while the
constant says 1,000, so the filter put back what the trigger had just
decided was too many - and `fine` settled above its bound instead of
at it. A test caught it at 1,059.

### `_zma_context`

momentum to have turned as well and fires on about 1.5% of the
signals this desk publishes, while `stretched` is the continuous
call `edge_calls`/`edge_right` actually score - and the one
`research/adapting.md` measured winning by 2.5 to 7.8 points at an
identical bet count. A consumer should be able to choose, and to
size on the difference between them.

### `Call.to_signal`

single signal a level carries - strength.md puts it at AUC
0.648 where the `strength` composite reaches 0.548 - and it
was computed on every touch and published nowhere.

Unshrunk, with its count beside it, so a consumer can apply
its own prior. A rate with two interactions behind it and one
with ninety are not the same number and must not arrive
looking like it.

### `_read_bars`

that timestamp. `bars * 8` because several venues report each one.
**`open` and `volume` travel too**, and their absence was a
silent defect rather than an omission. The live notice carries
both, so a warmed series held `volumes` full of `nan` while a live
one did not - and `profile`, which is enabled and draws 13,919 of
the book's levels, falls back to equal weights when its weights
are nan. Its own comment says "`Series.volumes` is what it was
waiting for"; on warmed history it was still waiting. `vwap`
cannot draw at all without them.

**Asked for only if the table has them**, because naming a column
that is not there raises `no such column` and the handler below
turns that into one warning line and *no warm at all*. A store
that is merely older should warm with less, not silently fail to
warm - which is what a narrower fixture did the moment these two
were added.

### `Engine._origin_at`

enters and the far one is what it aims at, and "nearest" alone
cannot say which side of price it sits on.
**An origin price is standing inside is structure, not absent
structure.** Filtering on `low > price` and `high < price` alone
drops every origin whose band straddles the current price, and it
is not a rare case: measured on the live book, 14 of 46 kept 4h
origins on eurusd contained price, 5 of 23 on gold, and on btc
three did while *none* sat above - so the range reported open air
upward while price stood inside a zone with its ceiling directly
overhead.

The bound wanted is "the next price at which structure begins or
ends, going that way". For an origin above, that is where its
band starts. For one price is already inside, it is where that
band **finishes** - the far edge is the wall this move meets.

**The zone travels with its edge.** Choosing the bound from a
list of bare floats threw away which origin it came from, and
with it `origin_above_high`, `origin_above_revisits`,
`origin_below_low` and `origin_below_revisits` - four fields that
were published until 2026-09-07 and are still read by
`trading/strategies/swing.py`. `OriginSwing._anchored_stop` asks
for the far edge and falls back to the level-anchored stop
without it, which is the exact placement that commit was written
to correct, and its `max_revisits` staleness gate reads a count
that is never there, so it can never refuse anything. Neither
failed: both took a documented default for "unknown".

### `Engine._origin_at`

price wanders 0.101v under a shifted sampling grid when the
two agree and 0.152v when they do not, and the agreement is
not just marking easy events - it barely moves the estimators
that do not resolve the transition. See `origins.CONFIRM_VOL`
and `research/localising.md`.

**Published, not acted on.** What is measured is that the
price is better *located*; whether it is better *traded* is
the question this field exists to let the journal answer.

### `Engine.observe_bar`

origin is made of. The fallback above is deliberate, because a notice
from an older producer is better folded in flat than dropped, but it
must not be quiet: `prices.announce_bars` shipped for a while sending
close alone, every live bar arrived flat, and levels on the live path
were built from closing prices while the leg extremes existed only in
replayed history. Nothing said so. This is what would have said so.

### `Engine.observe_bar`

median improves within a sweep rather than waiting; `Series.add`
handles the repeat by overwriting. A volatility estimate has no such
handling - folding the same close in once per venue fed it a run of
zero returns and dragged the estimate down by however many venues
report past quorum. Measured on the live feeds: six venues on EURUSD
and GBPUSD divided it by four, five on XAUUSD by three, four on
BTCUSD by two, and US500 at exactly quorum was the only one correct.

Everything this project expresses in volatility units divides by that
number, so distances read two to four times larger than they were:
zone width, resolve distance, KEEP_VOL, the edge gate. The cost of
taking the first quorum's median rather than the last venue's is a
rounding error beside it.

### `Engine.observe_bar`

median *moves* as venues arrive - on spx500, whose venues quote
genuinely different absolute prices, it moves by more than four
volatility units within a single bar. Checking touches on each
row fed that jitter to the tracker as though it were price: a
touch opened on one venue's row and resolved on the next one's,
at the same timestamp, having observed nothing but the median
rearranging itself. That is 45% of resolutions in this replay and
46% in the production journal, and it is why two runs of the same
replay disagree - venue arrival order is not stable.

### `Engine.observe_bar`

mixed two clocks a bar apart: a touch opened by a quote and resolved
by the bar that closed after it recorded a *negative* duration, which
is 10% of resolved touches in the journal, every one of them 5m and
every one about 300 seconds. The number itself is the small harm. The
large one is that `horizon`, `trap_window` and the GAP_FACTOR weekend
guard all test `when - touch.started`, and a negative elapsed trips
none of them.
...but never later than now, because the bar being delivered is
usually the one still forming. Stamping that one at its close puts it
up to a whole interval in the *future*, and a quote arriving in the
meantime then resolves a touch before it started - the same negative
duration this line was written to remove, in the other direction.
Measured on production: it took negatives from 1.7% of outcomes to
5.7%, at -98, -98, -98, -7 and -1 seconds rather than the clean one
bar of before, which is the shape of a partly-formed bar rather than
a closed one.

`min` is right for both cases without knowing which this is. A bar
that has closed was knowable at its close and that is earlier than
now; one still forming is knowable now. During a seed every bar is
long closed, so this leaves the replay alone.

### `Engine._drain_expired`

never went anywhere, so price is still there - and leaving the
level re-armed opened another touch against the same visit on the
very next observation, which produced another call and another
alert. On a market that has closed, where the price is frozen and
nothing can ever resolve, that is a loop: it fired repeatedly on
USDCNH and AUDUSD at the same levels on a Saturday morning.

`True` rather than `contains(price)` because there is no current
price here - expiry is a clock event. It is also the right answer:
the visit is not over, only this observation of it. `check`
re-arms it once price is REARM_VOL away, which is what "over"
means.

### `Engine._slowing`

zero and nothing else. Measured 2026-09-03 from the break model's own
standardiser: the running mean of this feature was **141,380,329**,
against 1.36 for `approach_vol` and 0.18 for `slope`.

That poisons everything standardised beside it. One input whose
variance is eight orders of magnitude larger than its neighbours'
makes every other weight rescale each time a new extreme lands, which
is exactly what the weight watcher caught: `approach_vol` moving from
-0.313 to -0.034 in thirty minutes with no change in what it measures.

`SLOWING_CAP` is far outside anything meaningful - a leg ten times
faster than the one before it is already an extreme reading - so this
discards no information a linear model could have used.

