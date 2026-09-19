# Trading Service

Rationale moved out of `till_infinity/trading/service.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `Waiting`

    Entry is a market order, so a call arriving after price has already left
    the level is filled at whatever is on offer - which spends part of the move
    before the trade starts and leaves the stop, anchored to the level, sitting
    close underneath the fill. Parking it turns "buy here because a level is
    over there" into "buy when price comes back to the level".

    What is stored is the **signal**, not the intent. When price arrives the
    strategy is asked again against the current tick, so entry, stop, target
    and size are all re-derived through every gate rather than a stale intent
    being resurrected. A setup that stopped being worth taking while it waited
    is refused on arrival like any other.


## `Untaken`

    `_also_wanted` already asks every strategy what it would have done with a
    signal another one took, and journals the answer with the prices it would
    have used. Until this existed nothing resolved those intents, so the record
    said what each strategy *wanted* and never what it would have *got* - and
    the ranking that settles which strategy should own a signal had to be
    computed by hand, off stored bars, after the fact.

    This closes that loop on the live quote stream. Two stages, because an
    intent is not a trade until it fills:

    1. **Fill.** The named entry has to trade. Several strategies rest their
       entry away from the market, and crediting them with a fill they never
       got would hand them a better price than they would have had.
    2. **Barriers.** From the fill, whichever of target or stop arrives first
       inside the hold. Neither arriving is a timeout, marked to the last
       price, exactly as the live trade would have been.

    Costs one comparison per open intent per quote, on quotes already on the
    bus. It is the feedback channel for arms nobody pulled, which is the thing
    a bandit assumes it cannot have.


## `Shadow`

    The single question the journal could not answer. A stop hit at full size
    looks identical whether the level failed or the stop was simply inside the
    noise, and the account cannot tell them apart - so the argument about stop
    width has had nothing to settle it but reasoning.

    This settles it. When a trade closes at a loss the target it was aiming at
    is kept, and price is watched for as long as the trade would have been
    held. If the target arrives, the thesis was right and the stop was too
    tight. If it does not, the stop was not the problem and widening it would
    only have made the same loss larger.

    Costs nothing to run: the quotes are already on the bus and being consumed.


## `Trader.execution`

        The real terminal only when `TRADING_LIVE` is set; the paper book
        otherwise. Market data always comes from `self.broker`, so an unarmed
        run still resolves real symbols, reads the real account and prices
        against the real bid/ask - it simply cannot place anything.

        This exists because the flag used not to do anything. `take` called
        `self.broker.send` unconditionally and `TRADING_LIVE` changed only a log
        line, so a run in "paper" mode against a live bridge placed real orders
        on the account. Caught by doing exactly that: a paper run opened 0.03
        BTCUSD on the demo, and the next run refused to trade because the
        instrument it had never really traded was already open.

        A safety switch that is checked in one place and ignored in another is
        worse than no switch, because it is believed.


## `Trader._check_gates`

        `structures` will not publish a call below `reactions.MIN_EDGE`, so an
        edge floor at or under it is configuration that looks like a limit and
        is not one. This module shipped with exactly that - 0.08 against an
        upstream 0.10 - and nothing would have said so.

        **Zero is exempt, and the distinction is the point.** A floor of zero
        is a gate deliberately switched off, which is what the measurement in
        `research/harness/gates.py` argued for; a floor of 0.08 is a gate
        somebody believes in that does nothing. Warning about both taught the
        reader to ignore the warning, which is worse than not having it - and
        it started doing exactly that the day the edge floor was turned off on
        purpose.


## `Trader._undealable`

        Two ways we cannot. No quote at all is the obvious one. The other is a
        shut market, which is not obvious: it keeps its last quote, and the
        broker will still accept an order against it. What it will not do is
        let the position out. A us30 position could not be closed for twenty
        minutes through the index's daily break, and a weekend is that same
        failure for two days.

        `spec.tradable` is no help - it reports whether an instrument is
        enabled, not whether it is trading, and said True throughout.

        This catches a market already shut. A market *about* to shut is the
        harder half and is not covered: the spread gate refuses some of it,
        since spreads widen into a close, and the rest needs session hours we
        do not have.

        **Which clock decides.** The broker's, not ours. `_quoted_at` is fed
        from the quotes bus, which is a consensus of other venues, and they
        keep quoting an instrument our broker has closed - so a us30 order was
        refused with "Market closed" while the consensus feed looked perfectly
        live. The broker's own tick time is the only clock that answers the
        question actually being asked, which is whether *this* broker will let
        a position out. Measured against it on a Friday evening: BTCUSD -2s,
        Australia 200 696s, Wall Street 30 1597s - the same epoch as ours, and
        a clean separation between trading and shut.

        The consensus check stays underneath it as a fallback, for a bridge
        that does not report a tick time. A tick with no usable time is not
        called shut: absence of evidence is not evidence of a closed market,
        the same reason a feed that has never quoted is not called shut.


## `Trader._agree`

        Agreement is worth something, and the useful thing to do with it is
        **not** to bet more. Two strategies on one signal is one idea found
        twice, so sizing up on agreement doubles a position on a single
        thesis - which is what the per-instrument limit exists to prevent.

        What agreement can buy is a better-built trade. Among the strategies
        that wanted the same side:

        * the **furthest** stop, because being stopped before the move arrived
          is the failure this session measured most - six of twelve stopped
          trades later reached their target;
        * the **nearest** target, because the same measurement said unreached
          targets are what a wide stop costs.

        That is the combination most likely to resolve as a win, and it is
        deliberately the *worst* reward-to-risk of the ones on offer - which
        `min_reward_to_risk` then judges on its merits. If the safest version
        of a trade cannot clear the floor, that is worth knowing rather than
        trading the flattering version instead.

        Money at risk is unchanged: a wider stop is re-sized into fewer lots by
        `lots`, so the account never notices the difference.


## `Trader._also_wanted`

        The running order decides who trades, and it also decides **who is ever
        asked** - so the strategies never see the same signals and their
        records are not comparable. `level-scalp` scored +1.01R over two
        trades and `fade-to-value` -0.75R over ten, on two different streams,
        which is not a comparison however it is printed.

        Trading them in parallel would fix the comparison and multiply the risk
        - two strategies on one signal is one idea found twice, which is what
        the per-instrument limit exists to prevent. So they are *evaluated* in
        parallel and one of them trades: every other strategy is asked, and
        what it wanted is written down beside what actually happened.

        Nothing here places an order. It costs one arithmetic pass per
        strategy per signal, and it buys the only honest way to rank them.


## `Trader._recover`

        Two things go missing, and the second was found only after the first
        was fixed. **The ref** is the journal decision the trade was opened
        from, without which `_settle` cannot write an outcome at all. **The
        interval** is the timeframe it was triggered on, which `_intent_from`
        cannot know because a broker position carries a symbol and a side and
        nothing else - so an adopted trade closed with its timeframe blank and
        fell out of every per-interval table. 343 of 551 closes over 45 days.

        Both maps are exact and are tried first. The journal lookups behind
        them are fallbacks for positions opened before the maps existed, and
        `_interval_for` is exact too - it reads the very decision the trade
        came from rather than matching on symbol and side.


## `Trader._ref_for`

        **Why this is needed at all.** `_settle` writes an outcome against
        `live.ref`, and `journal.outcome` refuses a record with no parent -
        correctly, since an outcome that cannot be paired with its decision
        teaches nothing. But `ref` is handed over through `_pending`, which is
        only set for a position opened in *this* run. Anything adopted after a
        restart therefore carried an empty ref and vanished from the record on
        close.

        **The bias that made it worth fixing rather than noting.** What went
        missing was precisely the trades that lived long enough to span a
        deploy - so every figure taken from the journal was computed on a set
        that over-represented short trades, including the per-strategy table
        and the stop cost this repository has been reasoning from.

        Matched on symbol and side, newest first, and only against decisions
        that are not already the parent of an outcome - so a position cannot
        adopt the record of an earlier, settled trade on the same instrument.
        Returns "" when nothing matches, which restores the old behaviour for
        that position rather than guessing.


## `Trader._warm_reach`

        The same problem `_warm_trend` was written for, and the same shape.
        These need a sample **per feed and interval** - twenty resolutions for
        a reach quantile - while production publishes on the order of
        twenty-seven signals in fifteen minutes across every series there is.
        A given pair may see one an hour, so a cold estimator is not merely
        cold: it is unavailable for most of a day, and every deploy resets it.

        Verified the way `_warm_trend` was not: the first check after shipping
        the reach estimators found `reach_depth_vol` and `reach_stop_vol`
        absent from every decision, on a container minutes old.

        Failure is not fatal. Starting cold is what happened before this
        existed, and a trading service that will not boot because it could not
        read history is worse than one that starts without an opinion.


## `Trader._warm_trend`

        Without this the measure is not merely cold, it is effectively
        unavailable. A reading needs three prior levels on the **same feed and
        interval** and the window wants twelve, while production publishes on
        the order of twenty-seven signals in fifteen minutes across every feed
        and interval there is - so a given pair may see one an hour. Every
        deploy would reset that to nothing, and on a day of frequent deploys
        the context would never once be available to size a trade.

        The replay that measured this effect ran over resolutions accumulated
        across days, which hid the problem completely: there, twelve prior
        levels per pair is ordinary.

        Failure here is not fatal. A cold start is what happened before this
        existed, and a trading service that will not boot because it could not
        read history is worse than one that starts without an opinion.


## `Trader._note_push`

        Volatility units already normalise for how much an instrument moves per
        bar, and that is not enough: the *push* it makes once it starts moving
        varies on top of that, 1.66v on eurusd against 2.75v on brent. A single
        threshold is late for one and noisy for the other.

        Measured over 59,982 resolutions, the fixed 2.0v was silent through
        **47.5% of all moves** and confirmed after 2.0v of a 2.07v median push
        - the end of the move, which is no use for timing an entry.

        A slow EWMA, because this is a property of the instrument rather than
        of the moment; the threshold should not lurch because one call carried
        a big forecast.


## `Trader._rejected_at`

        A level says where a trade is worth taking and is silent about when.
        The gap between those is where this book loses money: an `inverse` buy
        on gold took its stop at 4591 and then ran to its target at 4604, and
        23 of the first 32 trades were stopped, several later reaching the
        price they were aiming at. Entering because price is *near* a level,
        while the level is still being tested, is a bet that the test is over.

        Two ways to see that it is, and **either is enough**:

        **The move turned.** After price has come back to the level, momentum
        crossing back in the trade's favour says the run against it has ended.
        Only meaningful after a pullback - momentum at a level is adverse by
        construction, because price arriving at support is falling, which is
        what arriving means.

        **A candle rejected the level.** The last closed bar reached the level
        and closed away from it - a hammer, a shooting star, an engulfing
        reversal.

        These are the same claim measured differently. A hammer *is* a momentum
        reversal compressed into one bar; the accumulator reads the same event
        tick by tick. The candle is stronger evidence and has to wait for a
        close, which on a 4h chart is a long time to hold an opinion. Requiring
        both would refuse a fast turn for not yet having a bar to show for
        itself, and refuse a clean rejection for happening inside one bar
        rather than across several. So it is a disjunction, and the trade is
        confirmed by whichever arrives.


## `Trader._park`

        The target is where the stop would otherwise have sat - the far edge of
        the level's sweep zone - approached by `pullback_fraction` of the way
        from the current price. At 1.0 the trade waits for the price the stop
        was going to defend, which is the best fill the setup can offer and the
        one it fills least often; at 0.5 it meets it halfway.

        The trade that gets stopped out today is the trade that gets *filled*
        tomorrow, and the reward-to-risk improves because the target has not
        moved. What it costs is the setups that never come back, and that cost
        is real - a strategy that only fills on retracements is a different
        strategy, not a cheaper version of this one. Which is why this is off
        unless asked for, and why the journal records what it refused.


## `Trader._rest_at_named_price`

        `Strategy.resting_price` names it; almost every strategy names nothing
        and this does not fire. `cycle-turn` names the line a structure broke
        at, because support that failed is tested as resistance when price
        comes back to it and the coming back *is* the trade - taken a unit
        away, it is a different bet with the same name.

        **Only when the line is still on the far side of the quote.** If price
        has already traded through it there is nothing to wait for, and resting
        behind the market would turn "enter at the line" into "enter after the
        move": the trade is taken at market instead, which is what the gates
        already approved.

        Held on this side rather than sent as a pending order, for the reason
        `_edge_entry` gives: the bridge's `POST /orders/pending` would leave the
        stop and target on the terminal between placement and fill.


## `Trader._edge_entry`

        The trade is worth taking at the level; it is worth more a fraction
        nearer it. This waits at that price rather than paying the spread to
        cross now, and the wait is short by construction - a quarter of a unit
        is inside the noise of any instrument that is moving at all.

        **Held here, not sent to the broker.** The bridge has
        `POST /orders/pending`, and using it would put the stop and target on
        the terminal between placement and fill, where nothing here can adjust
        them - and where a market that gapped through would fill at a price
        this never agreed to. The same book that already re-arms parked signals
        watches this one.

        Skipped when the fill is already better than the price being waited
        for, which is the common case on a fast move: there is nothing to
        improve and waiting would only risk the trade.


## `Trader._still_building`

        A trade that has not moved is two different situations. One is dead:
        nothing is happening and the capital should go elsewhere, which is what
        the stale clock is for. The other is coiling - price has not travelled
        yet and the sub-hour timeframes are lining up behind it - and closing
        that one is closing the setup immediately before it works.

        The clock alone cannot tell them apart, because it only reads distance
        travelled. The momentum ensemble can: `agreement` is the share of
        timeframes pointing the trade's way, and it turns before the move
        rather than after it.

        Only a **majority behind the trade** buys more time, and only until the
        hold clock ends it anyway. A silent instrument with no reading is not
        given the benefit - unknown is not the same as building.


## `Trader._stale_after`

        Adaptive above a fixed floor, for the reason the momentum threshold is:
        the setting is one number and hold time is not. Measured across this
        book it varies **163-fold** between series and it persists, which is
        exactly the shape that makes an average useless - a fixed 300s is most
        of a fast series' whole life and a fraction of a slow one's.

        `STALE_HOLDS` times the series' own expected hold. A trade that has not
        moved after twice as long as this instrument usually takes to resolve
        is genuinely going nowhere; the same silence after 300 seconds may be
        an instrument that has not started.

        The estimator is the one already published on every decision as
        `expected_hold_s`, so this is the first thing to act on a number that
        has been visible in the journal for a while - which is the order this
        repository does it in.

        `stale_after` stays the floor: it still means "never sooner than this",
        and a series with no estimate yet behaves exactly as before.


## `Trader._closing_soon`

        The other half of a shut market. `_shut_for` catches one that has
        already closed, by noticing the broker has stopped quoting; nothing
        caught one about to close, and that is the case that costs money. A
        position opened at 20:52 on a Friday cannot be closed until Sunday
        night: the hold clock keeps running while the market does not, and
        `max_hold_multiple` does not save it because the shut branch of the
        deferral has no cap.

        Judged against **this trade's own hold**, not a fixed cutoff, because
        that is the thing that has to fit. A thirty-minute hold needs thirty
        minutes of session; a scalp with a two-minute hold is perfectly fine at
        the same moment, and a blanket "no trading after 20:30" would refuse
        both.

        Stands aside when the hours were not learned, and for instruments that
        never close. See `sessions.py` for how little this claims.


## `Trader._orphans`

        `_waiting` is in-process memory and the broker's order book is not.
        Every path that drops a wait goes through `_withdraw`, which is the
        right design and covers nothing across a restart: the container
        recycles, `_waiting` comes back empty, and the orders it was holding
        sit at the broker with nobody watching them.

        Found live on 2026-09-01 - seven resting orders, the oldest 6.9 hours
        old and placed before a restart the evening before. A stale limit is
        worse than a missed trade: it fills on a setup this system stopped
        believing in hours ago, at a price the market has since left, and the
        first anybody knows is a position nobody opened.

        Deliberately **not** adopting them instead. Reconstructing what a
        `Waiting` believed - which gate it watched, what would have withdrawn
        it - is guesswork, and a wrong guess leaves a live order governed by a
        fiction. Withdrawing is the honest recovery: the signal is gone, and if
        it is still good it will be published again.


## `Trader._watch_reachable`

        **This is the gap `_check_autotrading` could not cover, and it cost two
        hours on 2026-09-12.** `sweep` returns before that check when the broker
        does not answer, so an unreachable terminal wrote one WARNING per
        heartbeat and raised nothing:

            WARNING broker could not select BROKER:Boom 1000 Index: All connection attempts failed
            WARNING trading: could not quote SOLUSD: All connection attempts failed

        The container read `healthy` and `till-infinity health` read seven
        services running throughout, both correctly: nothing in this process was
        wrong. The terminal lives on another host and that host left the network.
        **"I am fine" and "the desk can trade" are different claims**, and until
        now only the first had a voice.

        Not wired into the healthcheck, deliberately. An unhealthy container gets
        restarted, and restarting this process cannot reach a machine that is
        gone - it would be a restart loop through an outage it cannot fix, losing
        the in-memory book each time. A healthcheck answers "should this be
        restarted"; this answers "should somebody look". They are different
        questions and conflating them makes the outage worse.

        Edge-triggered on the `UNREACHABLE_AFTER`-th consecutive miss, for the
        reason `_check_autotrading` gives: one alert per heartbeat for two hours
        is a channel nobody reads, which is how the next one gets missed.


## `Trader._check_autotrading`

        **A connected terminal with AutoTrading off answers every health check
        and rejects every order.** On 2026-09-12 that ran for nine hours and cost
        **171 rejections** with nothing filled, while the container read healthy
        and the log carried one WARNING per attempt and no alert. That is the
        same failure as the outage three hours earlier: a fault that writes a
        line rather than raising its voice.

        Run from `sweep`, so it is periodic without a timer of its own.

        Edge-triggered. The condition persists for as long as somebody takes to
        click a button, and one alert per heartbeat for nine hours is a channel
        nobody reads - which is how the *next* one gets missed. It says so again
        when it clears, because "is it back" is the question that follows.


## `Trader._shut_for`

        **The broker's clock first.** `_quoted_at` is fed from the quotes bus,
        which is a consensus of other venues, and they carry on quoting an
        instrument our broker has closed: a us30 order was refused with
        "Market closed" while the consensus feed looked perfectly live. Only
        the broker's own tick time answers the question being asked, which is
        whether *this* broker will let a position out.

        Measured on a Friday evening, our epoch and theirs agree and the two
        states separate cleanly: BTCUSD -2s against Australia 200 696s and
        Wall Street 30 1597s.

        **The observation has to be fresh too.** A cached tick time goes on
        ageing whether or not we are still asking, so an instrument we simply
        stopped quoting would drift into looking shut. If we have not looked
        recently the broker's clock is not used at all, and the consensus one
        answers instead - which is also what happens for a bridge that reports
        no tick time. Neither missing evidence nor our own silence is evidence
        of a closed market.


## `Trader._quote_is_stale`

        A us30 position could not be closed for twenty minutes through the
        index's daily break. The error was a bare 400 with no retcode; what
        actually identified the cause was the quote not having moved in thirty
        minutes - bid, ask and timestamp identical to half an hour earlier.

        Worth separating from a refusal because they want opposite handling. A
        shut market means wait, and retrying fills the log with warnings that
        read as a fault. A refused order means something about that order is
        wrong and should be loud.

        One definition, shared with the gate that refuses an entry. Two would
        let a position be opened into a market this path already considers
        shut, which is the exact failure the gate exists to prevent.


## `Trader._too_wide_to_leave`

        The hold clock exists to release capital from a thesis that is not
        playing out. It assumes the exit costs about what the entry did, and
        out of hours that assumption fails completely: an aus200 position was
        quoted `bid 8998 / ask 9051` after the ASX closed - 53 points against a
        normal 1 or 2, and against the trade's own 8.89-point risk. Closing
        there would have paid six times the trade's entire risk budget in
        spread alone, to exit a position whose true mid had not reached its
        stop.

        `max_spread_fraction` already refuses to *enter* on a wide spread, and
        that is the easy half - an entry can always wait. This is the other
        half.

        **Bounded, like every extension here.** `max_hold_multiple` still caps
        total age, so an instrument that is permanently wide cannot hold a
        position open indefinitely; past that the trade goes out at whatever
        the market is offering, which is the honest outcome when the
        alternative is never leaving.


## `Trader._stale`

        The median touch resolves in eighteen seconds and 84% of them inside
        five minutes, against holds here measured in half hours. A position
        still sitting at its entry well past that is not the event it was
        opened for - and what it is doing while it waits is not waiting for the
        thesis, it is giving noise time to reach the stop. That is a losing
        trade arrived at slowly, and closing it flat costs the spread instead.

        **Measured from the best price, not the current one**, and that is the
        conservative direction: a trade that reached 0.4R and came back has
        started, so it is left alone. Only a trade that never went anywhere at
        all qualifies. The rule is meant to catch the dead ones, and a rule
        that also caught the retracing ones would be closing winners on the way
        through their pullback.

        Not applied once a position has been scaled or protected - if part is
        banked or the stop is at break even, the thing this protects against
        has already been dealt with by something better.


## `Trader._rearm_stopped`

        Six of twelve stopped trades in the sample later reached the target
        they were aiming at, by between 3.7R and 25.7R. The level survived
        being crossed - which is what a sweep looks like from the outside - and
        the stop settled only that *that fill* was too early, not that the idea
        was wrong.

        **It re-runs the signal, not the trade.** The payload goes back through
        `on_signal` and therefore through every gate, so a setup whose
        probability has since decayed, whose instrument has gone wide, or whose
        level has stopped being a level is refused exactly like a new one. The
        alternative - resurrecting the intent - would re-enter on the strength
        of reasoning that the stop already contradicted.

        **It requires the pullback to be switched on**, and that is the guard
        that makes the rule safe rather than a way to lose twice quickly. At
        the moment a stop fills, price is by definition at the worst point the
        trade has seen; re-entering at market there buys the extreme. With
        `pullback_fraction` above zero the re-armed signal parks and waits for
        price to come back to the level, which is the entry the thesis wanted
        in the first place. Without it, this does nothing.


## `Trader._fill_window`

        **Corrected on 2026-09-02, hours after shipping the wrong version.**
        The first cut gave every intent `max(hold, 60)` to fill, which is up to
        twenty-four hours for `opportunity`. A real resting entry gets
        `pullback_bars` bars of its own interval - fifty minutes on a 5m call -
        and is withdrawn after that.

        So the resolver was crediting fills the live system would never have
        seen, and crediting them to exactly the strategies that rest their
        entry furthest out of reach. `Untaken`'s own docstring says a fill must
        not be assumed because it would rank those strategies above the ones
        that paid the spread to be certain; the fill *window* is the same
        argument and the first version got it wrong.

        Same expression as `_park`, deliberately, so the two cannot drift.


## `Trader._worth_keeping`

        Three conditions, and all of them have to hold.

        **It has to be in front**, by `hold_extends_at` times the risk it was
        sized for. Measured from the current price rather than from the best
        seen: the question is whether to keep the position now, and the best
        price is history the trade may already have given back.

        **It has to be protectable.** The stop is moved to break even plus the
        spread cushion before the extension is granted, so the worst outcome
        after this point is a scratch. That is what makes the rule safe to run
        without the trailing rules in `manage.py` being switched on, and if the
        move is refused the trade is closed on the clock as before rather than
        held unprotected.

        **It has to end.** `max_hold_multiple` caps total age, because a
        position kept indefinitely accrues swap, crosses sessions it was never
        measured in, and eventually sits over a weekend.


## `Trader._unattributed_context`

        **43% of one day's closes reached the journal carrying almost nothing.**
        45 of 104 on 2026-09-11, including a gold trade that made +32.82 at
        **+8.40R** - a number the alert computed and the journal did not hold.

        Losing the *link* is unavoidable: a position that outlives its `_refs`
        entry has no parent, and `journal.outcome` refuses a parentless entry on
        purpose. Losing the *arithmetic* was not. Everything below is already in
        hand at this point - the intent's entry and stop, the extremes the
        trailing rules have been tracking all along - and the branch was
        throwing it away.

        The bias is the reason it matters. What goes missing is exactly the
        trades that lived long enough to span a deploy, so every figure taken
        from `kind='outcome'` was computed on a set over-representing short
        ones: `research/instruments.md`, `research/giveback.md`'s 27%-kept
        figure, and the live fingerprints in the cross-check spec.

        `unattributed` stays on the record, so the two populations remain
        separable rather than being quietly merged.


## `_exit_kind`

    `reason` records how the position left the book - closed by us, or gone
    between polls - not what took it. Stop and target were therefore
    distinguishable only by the sign of the profit, which is a guess dressed as
    a fact: a trade closed on the hold clock while slightly ahead looks like a
    target, and one closed slightly behind looks like a stop.

    **What we closed ourselves, we know**, and it is asked first. The price
    cannot distinguish a stale close from a hold-clock close - both land
    wherever the market happens to be - so both used to read as "hold" and the
    question "is the stale exit helping" had no answer in the record. Every
    rule that closes a position names itself on the way out.

    **Falling through to "hold" is a claim, and it needs the evidence for one.**
    An adopted position carries a placeholder intent with no stop and no
    target, so every comparison below is skipped and the trade would be filed
    as having run its clock - which is not something we know. It reads
    "unknown" instead. Scoring can exclude what is unknown; it cannot exclude
    what is confidently mislabelled.


## `_intent_from`

    A restart leaves positions on the account carrying our magic and no record
    in memory of why they were opened. Adopting them means they are managed and
    closed properly; the reasoning is gone, and the journal entry says so
    rather than inventing one.

    **The feed name has to be the real one.** It was `symbol.lower()`, which
    for a broker whose symbols have spaces gives `volatility 25 index` beside
    the `volatility_25_index` everything else writes - two names for one
    instrument, so its history splits and neither half accumulates. Three
    trades went into the journal under the spaced name. The resolved map is
    passed in rather than guessed at, and the lowered symbol survives only as
    the fallback for a position on an instrument we do not track.

# Trading Service

Rationale moved out of `till_infinity/trading/service.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `Trader._check_order`

        `TRADING_STRATEGIES` is a priority list - the first taker wins - so a
        strategy that is another plus extra refusals only ever sees what the
        permissive one declined, and it declined those for reasons the stricter
        one would decline too. It books nothing, forever, and every other
        signal says it is running: it loaded, it is enabled, it just never
        fires. That is the failure this catches, because it is the kind nobody
        finds by looking.


## `Trader._take_all`

        **The book is re-read between fills, and that is the whole safety
        property.** Asking the guard once, before any of them opened, would
        let all seventeen pass the same position cap on the same stale count -
        which is not a cap. Each intent is checked against the account as it
        stands *after* the previous one filled.

        The first strategy's verdict is passed in already built, so it is not
        reconsidered; the rest are asked here. A strategy that refuses is
        counted exactly as it is on the sequential path.


## `Trader._warm_sessions`

        The broker does not publish its hours - see `sessions.py` - so they are
        read off fifteen-minute bars, which is enough resolution for the daily
        break and the Friday close and cheap enough to fetch for every symbol
        at start-up.

        Failure is not fatal, here as in `_warm_trend` and `_warm_reach`. An
        instrument whose bars cannot be read simply has no session opinion, and
        the gate stands aside for it rather than refusing everything.


## `Trader._copy_to_followers`

        **Risk travels, volume does not.** Each follower re-sizes against its
        own equity, so the same decision is the same *fraction* of each account
        rather than the same number of lots - which on a smaller account would
        be several times the risk the plan authorised. See `replicate.py`.

        Never raises and never blocks the primary. The trade that matters is
        already on; a follower that cannot take it is a fact to record, not a
        reason to unwind an account that did nothing wrong.


## `Trader._leave_with_broker`

        The other half of the hybrid. A poller sees price at its own cadence
        and a deep wick is brief by construction, so the fills most worth
        having are the ones most likely to fall between two reads. The broker
        fills on its own tick.

        Failure here is not fatal and not silent: the local watch is already
        registered, so a rejected order leaves the entry exactly as it was
        before this existed rather than losing it.


## `Trader._turn_wanted`

        Adaptive above a fixed floor, for the reason the CUSUM threshold is:
        volatility units normalise how far an instrument moves per bar, and the
        push it makes once moving varies on top of that - 1.66v on eurusd
        against 2.75v on brent. A turn worth 0.5v is most of a eurusd move and
        a fifth of a brent one, so one number asks two different questions.

        `require_turn_vol` is the **floor**, not the value: the setting still
        says "never accept less than this", and the instrument raises it when
        its own moves are larger. A feed with no push estimate yet gets the
        floor, which is the setting behaving exactly as it did before.


## `Trader._say_what_it_is_doing`

        A trader that has taken nothing looks identical whether the market is
        quiet, the signals are being discarded by a gate, or the subscription
        is broken. handoff.md calls this out as a class of bug: correct silence
        and broken silence are indistinguishable, and every such place needs a
        positive signal saying which it is.

        It cost a day here. Level calls were arriving and being delivered to
        Telegram while the trader discarded every one of them on a timeframe
        filter, and the only trace was a DEBUG line nobody was reading.


## `Trader._known`

        The payload mixes them: `Live` and `Policy` are trading's, `Cusum` and
        `Ensemble` are structures'. Reading it with trading's registry alone
        left every `cusum.*` unresolved - they came back as plain mappings of
        their fields, and the first quote after a restart would have called
        `.push()` on a dict.

        Trading is applied second so it wins the one collision. Keys are
        `basename.ClassName` and `config.Settings` exists in both packages;
        neither is ever persisted here, so which one wins decides nothing - but
        it is decided on purpose rather than by iteration order.


## `Trader._remember_rung`

        **The ladder a level-based trail climbs.** `trail_vol` follows price at
        a fixed distance, which is a distance nobody chose for this instrument
        at this moment; a trail that steps up behind levels moves when the
        market gives it somewhere to move to and sits still when it does not.

        Only `TRAIL_RUNGS` - 15m to 1h. Finer than 15m is noise to a trade held
        for a day, and a stop dragged up behind a 1m level is a stop placed by
        the last minute of trading. Coarser than 1h moves too rarely to be a
        trail at all.


## `Trader._remember_marks`

        Once a heartbeat, not once a quote: the cost of a restart is then
        bounded to a minute of high-water rather than the whole trade, and the
        file stays a few hundred bytes.

        Never raises. A desk that cannot write a convenience file must keep
        trading - `structures` takes the same line on its own state, and for
        the same reason.


## `Trader._expire`

        Unless it is working. The hold exists to release capital from a thesis
        that is not playing out, and it was closing trades that were - a
        position a point in front at the thirty minute mark went out at market
        and the rest of the move happened without us. Observed on gold: out at
        4623 on a fall that carried to 4592.

        So a trade far enough in front is protected and kept instead. See
        `_worth_keeping`, which moves the stop to break even first, so an
        extension can scratch but cannot turn a winner into a loser.


## `Trader._maybe_rearm`

        Only a stop qualifies. A trade closed on its target got what it asked
        for, and one closed on the clock was not refuted by anything - taking
        either again would be trading the same idea twice rather than
        re-taking one that a sweep interrupted.

        Queued rather than re-entered here: `_settle` runs inside
        reconciliation, and opening a position from within the walk over the
        position set is how that walk starts disagreeing with the broker.


## `Trader._turn_exit`

        Empty whenever there is nothing to compare - which is most closes, and
        deliberately so. The depth head stays silent until it has settled two
        hundred turns on that feed, and a made-up exit scored against a real one
        is worse than no comparison at all.

        Swallows its own failures. A shadow comparison must never be able to
        break the record of a real trade, which is the same rule the stopped
        trade `Shadow` already follows two hundred lines up.


## `Trader._heat`

        The mirror of `_reach`, and the number research/stops.md wanted and did
        not have. On a trade that won it says how much of the stop was actually
        used: if winners rarely spend more than a third of their risk, a stop
        four volatility units wide is protection nobody reaches, bought by
        sizing every position at a quarter of what the same money would allow.

        Zero rather than negative when the trade never went against itself at
        all, which is a real case on a fast fill and is not "no reading".


## `_market_closed`

    The last authority on the question, and the only one that cannot be wrong:
    every clock here is an inference about the broker's state, and this is the
    broker stating it. `400 Order failed: Market closed` is what a close
    against a shut US Tech 100 actually returns.

    Kept as a string match because the bridge sends no retcode to match on -
    the same reason the original us30 diagnosis had to go by the quote not
    moving. Worth having anyway: a shut market means wait, and logging it as a
    warning every minute for eight hours reads as a fault that needs fixing.


## `listen`

    The heartbeat runs alongside the message loop rather than inside it,
    because the two are unrelated: a stop can be hit during an hour in which no
    signal is published, and reconciling only when a message arrives would
    leave that trade recorded as open for as long as the market is quiet.

    Both topics are subscribed *before* either pump starts. `Bus.publish` only
    reaches groups that already exist, so subscribing inside the tasks would
    drop whatever was published between the first task starting and the second.

## Inline notes

Passages that stood inside the functions named, moved out on 2026-09-19.
Each keeps its first sentence at the call site.

### `Trader._quote`

and the run that matters is the one that happened on the way there.

The unit comes from the last signal for this feed, so a feed that has
never published one accumulates nothing and the filter reads zero -
no refusal. That is the right failure direction, but it is a real
blind window and worth naming: the filter is inert on a feed until
its first signal arrives. Signals are frequent enough that the window
is short, and the alternative is inventing a second volatility
estimate here that would disagree with the one everything else uses.

### `Trader.on_signal`

the first of two ways a signal stops being a trade before any
strategy is asked, and both were invisible. On 2026-09-19 the
desk took nothing for two days while `passed over` sat frozen,
and the reason it sat frozen is that nothing here touches it.
A desk that has stopped trading must be able to say where the
signals are going.

### `Trader.on_signal`

first, so the records become comparable on one stream
instead of on the slice each strategy happened to be
offered. It multiplies exposure, deliberately: the guard is
re-asked below with the book as it stands after each fill,
and the per-instrument and position caps are what keep it
bounded. Agreement sizing is skipped - rebuilding one trade
from what several asked for *and* letting each take its own
would count the same agreement twice.

### `Trader._take_all`

it to the number of strategies buys the intended shape - eight
strategies, eight positions - and also permits the unintended
one, where a single strategy accumulates eight on the same
instrument across successive signals. That is one idea held
eight times, which is the concentration the cap exists to stop.
Checked by `Live.by`, which is read back from the position's
magic and so survives a restart.

### `Trader._restore_learned`

prices on every published level, and the guard around
`handle` turns the `TypeError` into a skipped signal - 124
of them in one session before the traceback was read.

The log line is not decoration. 392 were found at the
first restore after this was added, in state written by a
build whose codec already coerces them, so how they are
made is still open - and this count at each restart is
what will answer it.

### `Trader._warm_trend`

oldest levels of the batch and discard everything recent, which is
the exact opposite of the intent and would still produce a
confident-looking number.

Not for the reason it first appears: efficiency is order-invariant.
Reversing a sequence flips the sign of the net displacement but not
its magnitude, and leaves the distance travelled untouched, so the
ratio is identical either way. Only which levels survive the deque
depends on the order.

### `Trader._hand_over_trend`

this returned early on every signal, so no reading was ever injected
*and* the window never grew - the measure was inert twice over while
the warm start reported 121 of 140 pairs ready.

The third time today a value has been read from or written to the
wrong level of this payload. `features` is the contract; the top
level carries routing.

### `Trader._candle_at`

and is judged on the bar it is entering on.

**A window, coarsest first.** One timeframe was too narrow a
question: a 4h bar closes six times a day, so insisting on that one
refuses every setup formed inside the last four hours, while asking
only 1h throws away the stronger claim when it exists. Asked coarsest
first so the strongest available evidence is the one reported.

### `Trader._park`

`pullback_fraction` alone rests every entry, which is a different
strategy rather than a cheaper version of this one - it trades only
what comes back. The wick is what says whether coming back is likely:
a long tail means price went well past the level and returned inside
the bar, so the close misrepresents where this can be got. A level
held without drama has no retracement to wait for.

### `Trader._park`

anyway; this is different in kind - a broken structure being retested
is not the same trade a unit away from the line, so there is nothing
for the general rules to improve on.

Then the small, ordinary improvement, tried before the deep one:
resting a fraction of a unit nearer the level is a different bet from
waiting for the sweep edge - 189 signals of 813 reached that wait and
none of them parked, because by then the fill was already past it.

Callables rather than coroutines, so the second is never created when
the first answers: an un-awaited coroutine is a warning and a leak.

### `Trader._park`

A fixed fraction asks every level for the same retracement, and levels
do not retrace the same amount: the wick this one has actually been
pushed to, on the side price is arriving from, is recorded on the
signal and is the measured answer to exactly this question. A level
that gets swept deeply is worth waiting deeper for; a level that
barely gets touched is not, and asking it to retrace as far as the
deep one just means never filling.

`pullback_fraction` becomes the **ceiling** on that wait rather than
the wait itself, so a level with no wick history yet still parks
somewhere sensible instead of not parking at all.

### `Trader._park`

for a retracement nobody has ever observed here.
Mean plus a share of the spread, rather than the mean alone.
Half of all wicks are deeper than the mean by definition, so
waiting at it is waiting at a depth that gets exceeded as often
as not - which for a retracement is the difference between being
met and being missed.

### `Trader._park`

It used to clamp at the edge, twice over - once here and again
through a fraction whose ceiling *was* the edge - so a level
whose wicks run deeper than its own zone had the extra depth
discarded and was met shallow. That threw away the best fill the
setup offers: a deep pullback is the sweep, and buying the sweep
is the whole idea.

The edge is not a safe stopping point either, which was the
stated reason and was wrong. The stop sits *beyond* the edge with
clearance, and `_floored_stop` guarantees it clears the **fill**
by `min_stop_vol` - so a deeper entry gets a proportionally
further stop on its own. An entry that really has gone too far is
refused by the `through` gate when the signal is reconsidered,
which is a check that already exists and is better placed.

### `Trader._park`

A fraction of the hold makes the wait a property of the strategy
rather than of the market, so a 1m call and a 1h call wait the same
wall-clock time for retracements that happen on completely different
clocks. Bars of the entry interval is the same correction the hold
itself got, applied to the other end.
Bars of the interval that produced the call, falling back to the hold
itself when the interval is unknown - which is a real bound rather
than a second setting nobody would ever tune. There was one, and it
became unreachable the moment bars were preferred: the interval is
always known in practice, so the fraction it scaled was dead config
that still looked live.

### `Trader._turned_against`

distance price still had to travel to reach `trigger`, under a local
named `risk` that made it read as the trade's risk. It was not: that
gap shrinks to nothing as price arrives - which is the event the
order is waiting for - so the threshold shrank with it and any spread
at all cleared the bar. This check runs before the arrival check
below, so every resting order was withdrawn on the tick it would
have filled. Measured 2026-09-01: nine rests, no fills, no
expiries, every resolution a spread withdrawal.

Silent with no resting order, and that is not a gap. The point of
this method is to reach in and take back the **broker's** order,
which cannot change its mind; when there is none, arrival re-asks
every gate through `on_signal` and a wide spread is refused there.

### `Trader._say_what_it_is_doing`

entry set produces, and which says nothing. It is the gates *below*
that line that answer "why is it not trading", and on 2026-09-19
they were invisible: 39,643 signals passed over in fifty minutes,
one trade taken, and the log showed four interval counters. The
counter is a dict in memory and is not journalled, so a truncated
line is the only view there is of it.

### `Trader._remember_marks`

`Speeds` needs 48 calls per instrument before its slow line
means anything, and `Book` is where `swing-level` keeps every
level it has seen and builds its valuation from. Both were
created in `__init__` and saved nowhere, so a deploy reset
them - and on a day with ten deploys a counter that needs 48
calls on one feed never arrives.

`momentum-scalp` has taken **no trade in 45 days**: 109 of
its 110 refusals are `warmup: the speeds have not seen enough
calls yet`. It is not a strategy that declines, it is one
that cannot start.

This is the fourth thing found this session that accumulated
in memory and was wiped by the deploy cadence, after
`Drift._agreement`, `Live.ref` and the intent's interval. The
symptom is never an error - it is a component that looks
configured and does nothing.

### `Trader.sweep`

total; taking the file back first means it sees today already in
place and does nothing, which is the correct outcome.

The reconcile that follows is what fills `self.open`, so the extremes
are filtered against a book that is one pass stale on the very first
sweep - and `_recall_marks` keeps whatever it cannot place, because a
position adopted moments later still deserves its high-water mark.

### `Trader._mark_best`

dip before the peak is harmless - but `adverse_r` cannot tell
the two apart, so the one question `manage.py` says nobody
has answered stayed unanswerable. 585 closed trades on
2026-09-17 said a break-even at +0.25R would rescue 107
losers worth -839 while putting at most 143 winners worth
+1,044 at risk, and the width of that "at most" is exactly
this missing ordering.

### `Trader._manage`

Four trades on 2026-09-04 reached 2.75R to 4.32R in front and
closed at their **original** stop for -68.71 between them, with
`break_even_at` 1.0, `trail_vol` 2.0 and `scale_out_at` 1.0 all
configured. This loop had produced two stop moves in 181,039 log
lines and no scale-outs at all, with no errors anywhere: every
position was falling through one of these two guards and nothing
recorded which. That is the shape of every inert feature in
research/inert.md - a legal-looking silence.

### `Trader._reconcile`

These two lines used to sit above `_settle`, which is what reads
them - `_reach` and `_heat` both return 0.0 for a ticket they
cannot find. So `best_r` and `adverse_r` were written as exactly
0.000 on every close the book ever made: 188 and 85 of them, min
and max both zero, and not one stopped trade recorded as ever
having been in profit. The tracking was correct, the recording
was correct, and the state was thrown away in between.

`finally`, so a raising `_settle` still cleans up rather than
leaking a ticket's extremes for the life of the process.

### `Trader._settle`

and the ref lives in memory, so every position that outlived a
restart closed without reaching the journal. Measured on
2026-09-01: twenty distinct tickets closed in fourteen hours and
six outcomes recorded.

Recorded as an **observation**, not an outcome. `journal.outcome`
refuses a parentless entry on purpose - an outcome is a label on
a decision and a label with nothing to label is not one - so
forcing it through there would break that invariant to fix this.
An observation is what this is: something that happened, with no
decision of ours attached.

### `Trader._settle`

account sizes; R is, and it was never recorded - so every
question about how a strategy actually did began with a
derivation from entry, stop and exit that a reader had to
do themselves and could get wrong.

Signed against the side, so a profitable short is
positive. Zero risk means a placeholder intent adopted
after a restart, where the stop is the broker's and the
entry is the fill - not a trade that risked nothing.

### `Trader._settle`

record, so this survives a restart and does not depend on
having kept the order result around.

Until this was written down slippage was not recoverable
from the journal at all: the decision held the requested
price, the outcome held the exit, and the fill in between
reached only an alert. It is signed against the trade -
positive is a worse fill than asked for, on either side -
so the sign means the same thing for a buy and a sell.

Zero on an adopted position, whose synthetic intent is
built from the fill itself.

### `Trader._record_intent`

fixed set of numbers, so "opportunity lost 15.90" says
nothing without it - the arm is the thing being judged, and
its first five trades were recorded with the arm absent.

Empty for a strategy that has no policy, which is every
other one today.

### `listen`

process stays up and the container stays `healthy` - which is how
a single `TypeError` on a resting order's announcement took
trading down on 2026-09-08 and nothing outside said so. The
structures consumer needed the same guard for the same reason.

`CancelledError` still propagates: that is shutdown.

