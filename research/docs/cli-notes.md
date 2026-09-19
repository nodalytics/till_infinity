# Cli Notes

Rationale moved out of `till_infinity/cli.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `health`

    **The container reported `healthy` for three hours with no trading service.**
    On 2026-09-11 the MT5 bridge missed one health check at start-up, the
    trading task raised out of `listen`, `stack._start`'s supervisor caught it
    and wrote one ERROR line, and nothing restarted it. The probe in
    `Dockerfile` was `till-infinity --version`, which proves the package imports
    and the entry point resolves - and a dead service is precisely what a
    restart fixes, so it is precisely what the probe should have caught.

    Three ways to be unhealthy, and the third is the one that would have caught
    it a minute in rather than three hours in:

    * a service in `failed` - it started and died;
    * nothing in `running` at all;
    * a status file older than `--max-age` - the stack is not writing, so
      whatever it last said about itself is not evidence about now.


## `prune`

    Disk is the constraint that bites first here, and 1m candles across
    fourteen instruments and six venues are most of what grows. A count per
    series rather than a cutoff date, because the models consume a window of
    bars, and one number self-scales: the default 2,000 is about a day and a
    half of 1m and about forty years of 1w, which is roughly how far back each
    one's evidence is worth anything anyway.

    Deleting does not shrink the file - SQLite frees the pages for reuse, so
    growth stops but the size does not fall until it is rebuilt. `--vacuum`
    rebuilds it, and wants room for a second copy while it runs, which is
    exactly what is scarce when this is being reached for.


## `reindex`

    A corrupt index is not a corrupt database. `quotes_feed_ts` on the instance
    has been unusable since 2026-09-10 while every row in `quotes` reads back
    fine - a query that plans through it fails and the same query without it
    does not. That is one B-tree to rebuild, not a database to restore.

    Cheap enough to run on a full disk: rebuilding an index needs room for the
    index, not for a second copy of the file the way `--vacuum` does, and no row
    is ever read as authoritative from an index, so nothing is lost if it fails.

    `--only quotes_feed_ts` is the targeted form. Without it every index in the
    file is checked, and on a multi-gigabyte quotes table that walk is the
    expensive part - so name the one you mean when you know it.


## `structures_zones`

    A level found on the 5m and again on the 4h is one structure seen twice, not
    two structures. This groups them by **zone overlap** rather than a shared
    tolerance, because a tolerance has to be expressed in some timeframe's
    volatility and they differ by more than an order of magnitude - on gold, one
    volatility unit is $0.74 on 5m and $9.87 on 4h.

    The position is fused inverse-variance, so a timeframe that is certain where
    the level sits moves the answer more than one that is vague. `span` is the
    largest structure present and `precision` the finest: a zone reading
    `1w..5m` is a weekly level placed to five-minute accuracy, which is the one
    worth waiting for.

    `--min-timeframes 2` hides everything only one timeframe has seen, which is
    the quickest way to find the prices worth watching.


## `structures_zma`

    **This is the number that decides whether it is ever allowed to vote.** The
    indicator records and scores on every closed bar and influences nothing:
    `STRUCTURES_ZMA_ACTS` gives it a vote inside `structures`, and
    `TRADING_ZMA_GATE` lets `cycle-scalp` refuse a call it leans against. Both
    are off, and the standings here are what would justify turning either on.

    **Two records, because there are two calls.** `flag` is `agrees` - oversold
    with the slope already rising, or overbought with it already falling. `z` is
    the displacement alone, past the same threshold, without waiting for
    momentum. Both are settled against the very next bar, so 0.50 is a coin in
    each column. `research/adapting.md` measured the number beating the flag at
    an identical bet count on three controls - 0.504 against 0.562, 0.578
    against 0.603, 0.646 against 0.724 - and `TRADING_ZMA_GATE` reads the `z`
    column, not the `flag` one.

    `research/zma.md` measured 0.376 to 0.461 on Boom and Crash, and
    `adapting.md` 0.119 and 0.164 with a mechanism for it: those series drift
    one way and spike the other, so the drift leaves the z-score stretched and
    the spike is what turns it back. Sorted worst first for that reason - the
    instruments where the reading is an anti-signal are the ones that would cost
    money first.

        till-infinity structures zma --min-calls 200


## `structures_cycles`

    `depth` is how well the head predicting **how much further** price runs
    before turning beats simply predicting the running mean of that quantity:
    0 is no better, negative is worse. `when` is the same for **how long**, and
    `research/streaming.md` measured it positive on the nulls too - so a
    positive number there is a property of the metric and not of the series.

    Sorted worst first. Weights live in their own file so they survive a
    schema change that invalidates the engine's state - `drift` counts how
    often ADWIN said the model had stopped fitting.

        till-infinity structures cycles


## `trading_affordable`

    `sizing.lots` already refuses a trade whose minimum lot breaches the risk
    budget, and it refuses **rather than rounding up** - which is the right
    call, because placing `volume_min` anyway is how a 0.25% budget quietly
    becomes 3%. What was missing is the **catalogue**: that refusal arrives one
    signal at a time, so an instrument nobody can afford stays watched,
    modelled, signalled and refused, for ever, with nothing anywhere saying
    "this feed is not tradeable at this equity".

    Three things multiply and only the first is obvious: the broker's minimum
    lot, the narrowest stop it will accept (`stops_level`, which on a quiet
    instrument can be wide), and what a stop actually costs - `sizing.lots`
    inflates by the measured 0.087 slippage, two thirds of it the exit, because
    a broker stop is a market order once triggered.

    **It reports; somebody decides.** Dropping a feed is a decision about what
    the desk is for, and an account that grows makes an unaffordable instrument
    affordable again without anything changing about the instrument.

        till-infinity trading affordable
        till-infinity trading affordable --equity 500


## `_volatility_units`

    **Three sources, tried in order, and the order is about cost.** This runs on
    a two-core production box beside a desk that sits near 100% CPU, so the
    obvious implementation - load the structures state and read `vol.of(feed)` -
    is the one thing it must not do by default: that state is 145MB on disk and
    `research/starving.md` measured a 206MB one costing 0.394GB of transient
    memory to load. A second process doing that is how the desk gets starved.

    1. **The published constant.** The Volatility and Jump families state their
       annualised volatility in their own names, verified to within 0.49% on 12
       of 12 instruments. It is exact and it costs nothing - no state, no
       query, no terminal.
    2. **The bar store.** A standard deviation of recent log returns, one
       indexed query per feed. Cheap, and it is the only source for the real
       instruments and for Boom, Crash and Step, which have documented
       mechanics but no published volatility.
    3. **The engine state**, only when `--from-state` asks for it. It is the
       number the desk actually sizes with, which is why it is offered at all,
       but it is not worth starving the desk to read.

    A feed none of the three can price is left out. `survey` then skips it,
    which is correct: an assumed volatility is how an instrument gets called
    affordable that is not.


## `_series_keys`

    **Every one is a full index prefix**, which is the point. `bars` is indexed
    on `(source, venue, ticker, interval, ts)` and nothing else, so addressing a
    series by `feed` scans a 22GB table - and the catalogue already holds the
    mapping, for free, so there is no reason to.

    The broker's own series comes first where it exists: it is the instrument
    the order will be placed on, at the venue it will be placed at. Production
    publishes broker bars for the synthetics only, so everything else falls
    through to the configured consensus venues - **one at a time, pinned**,
    never a query across them, because interleaving two venues' quotes of one
    asset produces a violently reverting series that has silently corrupted two
    earlier measurements here.


## `_vol_from_bars`

    **Addressed through the index, not by feed.** `bars` is indexed on
    `(source, venue, ticker, interval, ts)` and nothing else, so a query
    filtering on `feed` cannot use it: SQLite reports `SCAN bars USING INDEX`
    plus a temp B-tree for the sort, which on production's **22GB** table is a
    full scan. The first version of this did exactly that and hung the command
    for minutes while the desk sat at 99.99% CPU beside it - the same defect
    already found and fixed once in `prices/spreads.py` this session, and
    reintroduced here from the same habit.

    The broker's own series is also the *right* one to size against: it is the
    instrument the order will actually be placed on, at the venue it will be
    placed at, rather than a consensus of places the desk cannot trade.


