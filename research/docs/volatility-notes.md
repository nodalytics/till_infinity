# Volatility Notes

Rationale moved out of `till_infinity/structures/vol/volatility.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `Volatility.tick`

        Every price on a venue sits on a grid and every change is a multiple of
        its step, so the smallest non-zero change observed *is* the step - once
        enough have gone past for the smallest to be a single step rather than
        the smallest jump that happened to occur. Measured rather than
        configured, because the tick table belongs to the venue and changes
        without notice, and because `structures` has no other route to it:
        `prices` sees the quotes and does not pass this on.

        **Zero unless the series has actually demonstrated a grid**, and the
        two guards matter more than the estimate.

        A series that only ever moves by one identical amount says nothing
        about the step: "the tick is that size" and "the tick is tiny and price
        is jumping" fit the data equally well, and taking the first would widen
        every zone on the instrument by that jump. So the estimate is withheld
        until price has been seen to move by several *different* multiples of
        it - one step, then two, then five - which is what a grid being
        resolved looks like and what a uniform jump never produces. See
        `TICK_MULTIPLES`, and note that the tempting test - "the tick should be
        small against a typical move" - rejects ADA, the instrument this exists
        for.

        It is also withheld until `TICK_WARMUP` observations, because the
        minimum of three samples is not a minimum.

        **The estimate is only ever an upper bound.** It is the smallest change
        that has *happened*, not the smallest that is possible, so an
        instrument whose prints are all several steps apart reads as coarser
        than it is. The error is always in that direction and it shrinks with
        data, never growing - but a consumer should bound what it does with the
        number rather than trust it early. `Level.zone` clamps it at
        `MAX_ZONE_VOL` for exactly this reason.

        Both failures return zero, so anything built on this falls back rather
        than inventing a number, and the estimate can only shrink with more
        data - biasing it towards the old behaviour rather than towards a
        spuriously wide band. That is the safe direction for a value whose job
        is to widen one.


## `Volatility.stretch`

        1.0 when there is no view yet. Above 1 the instrument is livelier than
        it usually is and the model expects that to fade. The exponentially
        weighted estimate cannot express this at all, because it has no usual.

        **Published as `vol_stretch` and measured to predict nothing.** Across
        32,362 decisive touches on 14 days a level held 84.6 / 83.4 / 83.6 /
        83.4 / 84.0 percent across its quintiles - flat to within 1.2 points,
        no shape. `forecast_ratio` on the same touches spans 5.1 points in an
        inverted U. Being in a violent regime says little about whether a level
        holds; being about to *leave* the current one says a good deal.

        Kept and still published: a null that has been measured is worth more
        than an absence, and this is the field a reader reaches for first when
        they want "the regime". `research/clustering.md` records the run.


## `Volatility.warm`

        `WARMUP` was declared with a docstring saying why it matters - below it
        "the variance of the variance is larger than anything it would be used
        to decide" - and this property was written to express it. **Nothing
        consulted either.** The constant, the field, the counter and this
        property all existed and no code joined them to a decision.

        What that cost: a cold estimate returns `floor_bps`, every distance in
        this package is a price divided by it, and at the old floor of 0.05 a
        four-and-a-half point move on brent became an expected push of **10,229
        volatility units**. It reached trading, produced a target forty-three
        times the price of the instrument, and the broker refused the order -
        which is the only reason anybody saw it. `Engine` now declines to
        publish a call from an estimate that is not warm.


## `Book`

    Per timeframe, not merely per instrument, and that distinction is
    load-bearing. A typical 4h move on gold is tens of times a typical 5m move,
    so a single estimate - in practice dominated by whichever series updates
    most often - makes every threshold expressed in volatility units wrong for
    every timeframe but one.

    Concretely: with one estimate, gold's clustering tolerance came out at about
    $0.86 while the 4h window spanned seventy days over a $574 range. Swings at
    that scale essentially never clustered, so the higher timeframes produced
    almost no levels at all.

    An empty `interval` is the instrument's tick-level estimate, updated from
    quotes. That is the right denominator for cross-timeframe comparisons: it
    is the only one every level can be measured against on the same footing.


## `Book.seed_implied`

        **Without this the member cannot speak for about a year.** `MIN_FIT` is
        250 observations and production gets one daily bar a day; `SCORE_WARMUP`
        is 60 more before its weight means anything. The seed is twenty years of
        public data, 6KB, shipped with the package.

        **Never overwrites what was learned live.** A seed applied on every
        restart would stop live observations accumulating past one container's
        lifetime - the fit would reset to its historical value every deploy, and
        on a day with ten deploys it would never learn anything at all. So a
        series whose fit already has more observations than the seed is left
        exactly as it is. Returns how many series were seeded.

        A seed is a **prior, not a floor**: `Score.record` decays toward what it
        is currently seeing and `Fit` accumulates on top, so live evidence that
        contradicts the seed wins - it just has to arrive first rather than
        wait a year to start.


## `Book.learn`

        Split from `Volatility.observe_bar` rather than called inside it,
        because the leading features live outside this package: the hour's
        volatility share comes from `context/sessions`, the changepoint
        evidence from `learning/focus`, and the volume from the bar payload.
        A per-series estimate has no route to any of them, and passing three
        collaborators into `Volatility` to get them there would put the whole
        engine inside an object that measures one number.

        Order is the part worth getting right, and it is the reverse of what
        reads naturally: the row is built from the state **before** this bar,
        handed to `observe` along with what the bar did, and only then does the
        state advance. Building the row first from updated state would give the
        model a feature set containing its own answer.


