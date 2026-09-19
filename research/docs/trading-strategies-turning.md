# Trading Strategies Turning

Rationale moved out of `till_infinity/trading/strategies/turning.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `CycleTurn`

    ## The shape

    **Entry anywhere from 1m to 1h.** The entry timeframe decides when the
    trade is taken, not what it is: every one of them is stopped on the 1h
    horizon and targeted on the 4h, so a 1m entry and a 1h entry aim at the
    same two distances and differ only in how promptly they notice. What keeps
    a fast entry from being one bar of noise is not the bar - it is the
    requirement below that the 1h and 4h cycles both already agree.

    **Anchored on 1h, 4h and 1d, and they are not worth the same.** The 4h is
    the mother cycle: without its agreement there is no agreement at all, and
    a 1h and a 1d that agree with each other while it does not are two
    timeframes agreeing about something the cycle they sit inside has already
    turned away from. So 4h is necessary - and not sufficient, because one
    reading is not an agreement however senior the timeframe. At least one of
    the other two has to agree with it.

    The anchors are read out of the call's own confluence: `structures` has
    already grouped the price into a zone across timeframes, so this reads that
    rather than asking a second, differently-wrong version of the same
    question. The call's own interval never counts - a timeframe cannot confirm
    itself - so a 1h entry is anchored on the 4h and the 1d.

    All three agreeing is recorded as `fully_aligned` and does not gate, which
    keeps the difference between "the mother and one" and "everything" in the
    record where a later comparison can use it.

    **Stop sized for the 1h horizon, target for the 4h**, which is the part
    worth being precise about. The signal publishes no per-timeframe structure
    prices - `last_high_structure` and the zone bounds all belong to the call's
    own interval - so "the stop comes from 1h" cannot mean "placed at the 1h
    swing". It means **sized for how far price travels in an hour**: a
    diffusive move over `T` scales as the square root of `T`, so a 15m call's
    stop is widened by `sqrt(3600/900) = 2` and its target by
    `sqrt(14400/900) = 4`. On a 1h entry the stop is unscaled and only the
    target stretches; on a 1m entry both stretch hard, by 7.7 and 15.5, which
    is the same pair of absolute distances arrived at from a smaller bar.

    That is a real implementation of the intent rather than a relabelling, and
    it is stated here because the alternative reading - that this finds the
    actual 1h swing low - is the one somebody will assume.

    **A break has to have happened first, and its line is the entry.** A change
    point with no broken structure behind it is a turn with nothing under it.
    The order is the claim: a run of higher lows fails, and *then* the cycle
    rolls over. The price that failed - the last higher low - was defended and
    then was not, so price returning to it is the moment worth taking: support
    that broke is tested as resistance, and the move through it took out
    whoever was leaning on it. `structures/breaks.py` finds that line; this
    refuses when there is none, when it points the other way from the cycle,
    and when price is not near enough to it for the line to be an entry at all.
    That last one is not a formality: measured on the desk, the median call
    sits twelve volatility units from its broken line, which is structure
    rather than a setup.

    **Then `ride`'s exit.** A trail half a volatility unit behind the best
    price, which `research/exiting.md` measured as the best of six policies
    over 31,820 replayed touches, with a break-even once the trade is in front.
    The target is deliberately far so the trail is what usually ends the trade.

    ## What it is gated on, and why that matters more than any of the above

    The reading this trades measures **AUC 0.5031 on real outright prices**,
    0.493 to 0.504 on the synthetics against their own shuffles, and a hit rate
    of **0.119 to 0.164 on Boom and Crash**, where it is an anti-signal with a
    known mechanism - see `research/zma.md`, `adapting.md` and `diverging.md`.
    The one place it works is a constructed spread this account cannot hold.

    So the condition is not a threshold on the reading, it is a threshold on
    the reading's **record on that feed**: `zma_min_calls` settled calls at
    `zma_min_accuracy` - the same two settings `zma_gate` reads, so nobody has
    to maintain two ideas of what earning a say means. On a family where the
    reading is an anti-signal that record never clears and this never trades
    there, with nobody maintaining a list of which families those are.

    **The record of the 4h series, not of the bar the call arrived on.** A
    record is a record of its own horizon: `edge_calls` on a 1m series counts
    one-minute-ahead calls, and the 1m series are exactly where the record
    looks best - 0.83 on usdcnh, 0.82 on eurgbp, against a median 0.56 at 4h.
    Reading the entry bar's record here would let a minute of evidence license
    a three-day position, and since the entry may be as fast as 1m the mistake
    would get louder the faster the trade. `zma_gate` still reads the entry
    bar's, because a scalp's horizon *is* the entry bar - the two now differ on
    purpose, each asking about the horizon it trades.

    The cost is that a feed with no 4h record trades nothing, which on the day
    this ships is every feed: the deepest 4h records on the desk are 168 to 184
    scored calls against the 200 the gate wants, six of them, and they arrive
    at six calls a day.


## `CycleTurn.resting_price`

        Support that failed is tested as resistance when price comes back to
        it, and the coming back is the event - so this waits there rather than
        paying the spread to enter wherever price happens to be when the call
        lands. `accept` has already refused anything further than
        `MAX_BREAK_GAP_VOL` from the line, so the wait is short by construction
        and the fill is the price the thesis is about.

        `_park` re-asks this strategy when price arrives, so a setup that
        stopped being worth taking while it waited is refused on arrival like
        any other.


## `CycleTurn._without_a_break`

        A change point that no break preceded is a turn with nothing behind it.
        The sequence that matters is a run of higher lows failing and *then* the
        cycle rolling over - the line that failed is a price that was defended
        and then was not, which is why price returning to it is the moment worth
        taking: support that broke is tested as resistance, and the move through
        it took out whoever was leaning on it.

        Refused rather than taken at the level, because a turn with no broken
        structure behind it is a different trade from the one this is gated to.


## `CycleTurn._unconfirmed`

        Two different failures, and they are not the same size. `4h` missing
        is the whole agreement gone - see `MOTHER`. `4h` present with nothing
        beside it is one reading, not an agreement, and the caller turns that
        into its own refusal.

        The call's own interval is excluded throughout: a timeframe cannot
        confirm itself, which is why a 1h entry is anchored on 4h and 1d.


