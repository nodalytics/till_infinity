# Structures Service

Rationale moved out of `till_infinity/structures/service.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `Watcher.unwarmed`

        An instrument added to a running deployment lands here: it collects
        bars immediately and forms levels only from the live stream, one bar at
        a time, while every feed that was present at the last cold start got a
        several-hundred-thousand-bar replay. Eleven synthetics added this way
        had 2,700 stored bars each and seven levels between them.

        The engine's own series are the test rather than its levels: a feed
        that has been replayed and legitimately formed no level is warm, and
        seeding it again would count every one of its bars twice.

        **Thin counts as unwarmed, and "has a series" did not.** The first
        version of this asked only whether the engine had ever seen the feed,
        and the eleven new synthetics had - about twenty bars each, collected
        live since they were added. So it reported nothing to warm while they
        sat on 2,700 stored bars apiece. A window holding less than
        `WARM_MIN_BARS` is not a warm feed, it is a feed at the start of a very
        slow one.

        The overlap that costs is real and small: replaying a feed with twenty
        live bars re-counts those twenty. Against five hundred replayed bars
        that is noise, and the alternative is leaving the instrument thin for
        hours.


## `Watcher._warm_zma`

        **Nothing else does this on a restore.** `Engine.seed` feeds the book
        through `observe_bar`, but `warm_new` only replays feeds the engine has
        no series for, and a restored engine has series for everything. So on
        any restart that keeps its levels the book starts empty and counts from
        the next live bar - weeks to reach the two hundred settled calls
        `TRADING_ZMA_GATE` and `cycle-turn` both wait on. Measured on the live
        desk: zero series against 261,192 restored level closes.

        **Every read is a full index prefix.** `bars` is indexed on
        `(source, venue, ticker, interval, ts)` and nothing else, so a query
        naming the feed scans a table that is 22GB on production - which hung a
        CLI command for minutes earlier today. The feed catalogue already holds
        the triples, so this seeks.

        **One venue per series, pinned.** A query across venues returns their
        rows interleaved by timestamp, and the alternation between two quotes
        of one asset is itself a violently reverting series - it has silently
        corrupted two measurements in this repository.


## `Watcher.refinement_tally`

        **The number this exists to explain is 2.4%.** `refine` is the largest
        single improvement ever measured on the swing strategy - +0.349R a
        trade becoming +0.576R, winning in all eight cells - and it reaches one
        origin in forty. `origin_confirmed` inherits the same ceiling, which is
        why 414 of 415 published calls read zero.

        Broken down by interval because the constraint is a per-interval one:
        `_capture_fine` needs the 1m series to cover the whole coarse bar at the
        moment it closes, `Series` holds 500 bars, and 500 one-minute bars is
        **eight hours**. A 1d bar is 1,440 minutes and can never be covered; a
        4h bar is 240 and always can. Which of those actually happens is a
        measurement rather than an argument, and this is it.

        `fine` is the count of captured bars per series - a series with origins
        and no captures is one where the fine data never arrived, which is a
        different fault from one where it arrived too late.


## `Watcher.liveness_tally`

        Same argument as `origin_tally`, `drift_tally` and `change_tally`, and a
        sharper case for it: **`run_vol` and `pivot` were identically zero across
        20,000 outcomes** and had been for as long as the journal reached. They
        are published on every level call, journalled on every outcome, and fed
        to models that weight them. Nothing noticed until somebody cut by them
        by hand.

        Both causes are now found, and neither was the feature. `run_vol` had no
        producer. `pivot` had levels that were never checked: `Engine.check`
        opens with `if not vol.warm: return []` and asked `vol.of(feed, 'daily')`
        for a period that has no bar stream to warm one, so every pivot level was
        skipped on its first line, on every bar and every quote, for the whole
        life of the formation - see `Engine.vol_for`. A zero column is a question
        about the pipeline before it is a question about the market, and this
        tally exists to ask it at the next save rather than the next audit.

        Read off the decisions this process has published rather than off the
        journal, so it costs no query and describes what *this* build is
        producing - a field that died in a deploy shows up at the next save
        rather than whenever someone next goes looking.


## `Watcher._benchmark`

        **Direction**, not hold-versus-break, because direction is what the kNN
        actually predicts and a comparison has to be on the incumbent's own
        quantity. `Memory.prior` returns P(up); so does everything here.

        **The same neighbour set for all of them**, derived once. That is what
        makes this like-for-like rather than two numbers from two runs: the
        fixed distance and the learned one are handed identical evidence, and
        the only difference is how they weight it.

        **The touch itself is excluded.** It is added to memory during
        resolution, so it can appear among its own neighbours at distance zero
        and hand every model the answer - which would report a perfect score
        for whichever model trusted its nearest neighbour most.

        Wrapped, because this is measurement and not machinery: a model that
        raises must not stop the service recording what happened, which is the
        one thing here that cannot be recomputed later.


## `Watcher.record_outcomes`

        A decision without its result is half a training example, and until
        this ran the journal held only halves - decisions with no outcomes and
        no parent links at all. The touch resolving *is* the label: which way
        price went from the level, how far, and whether a break it made was
        taken back.

        Every resolution is also published to `structures.resolutions`, which
        is the only ground truth on the bus. Anything acting on `signals` - the
        trader, in particular - is otherwise blind to whether the calls it
        acted on were right, and a threshold that should move with outcomes
        cannot move without seeing them.

# Structures Service

Rationale moved out of `till_infinity/structures/service.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `_named`

    `broker` is accurate and says nothing - the reader wants to know *which*
    broker, and on this desk it is Deriv. `PRICES_BROKER_LABEL` carries that.

    **Display only, and deliberately not the venue tag itself.** Stored bars
    and quotes are keyed by venue, so renaming `BROKER` to `DERIV` at the
    source would orphan every row already written under the old key - a
    cosmetic change that silently discards history.


## `single_source_feeds`

    Read from the price catalogue rather than guessed: a feed whose symbol map
    has exactly one source is one nobody else quotes. Synthetics are the case
    that matters - they have no underlying, so the broker is not one opinion
    among several, it is the instrument.

    Import kept local because `structures` does not otherwise depend on
    `prices`, and a missing catalogue must not stop the engine starting.


## `_price`

    `:.5g` was doing this and produced **8.468e+05** for a synthetic quoted at
    846,800 - an exponent in a trading alert, on the one line a reader needs to
    match against a chart. Five significant figures is the right idea and the
    wrong presentation.

    Decimals come from the magnitude, so gold keeps its 0.5 and EURUSD keeps
    its fourth place, and thousands are grouped because six digits in a row are
    not read, they are counted.


## `_cycle_lines`

    **No z-scores on the card.** The underlying number is a z - how far price
    sits from its own recent mean, in standard deviations - and printing it
    that way makes the block unreadable to anybody who has not read
    `structures/zma.py`. An alert is for a person deciding in a few seconds,
    so the reading is given as a **multiple of this instrument's own usual
    stretch**, which is the same information without the vocabulary.

    Absent rather than a placeholder when cold, which is the rule the features
    dict itself follows: a line reading "cycle neutral" on every alert of a
    feed that never warms trains the reader to skip the block.


## `alert_payload`

    `Signal.title` is built for a log line - venue, feed, then the whole detail
    string - which arrives on a phone as one long sentence with the numbers
    buried in it. What a reader wants first is the instrument, the timeframe and
    the direction; the evidence belongs underneath, one claim per line.

    Routing fields (`shape`, `instrument`, `venue`, `direction`) are set for the
    notification filter and are deliberately not rendered again - the title
    already carries them.


## `Watcher.arm`

        **These used to live inside `load`, after its `if not state: return
        False`.** Which meant that on a cold start - exactly when the books are
        empty and the backfill matters most - none of them ran. A schema change
        invalidates the state file, so the deploy that *adds* a persisted class
        is the deploy where this is skipped, which is the worst possible time
        for it.

        Idempotent and cheap on a warm start: the record load is a small file,
        the backfill skips every series that already has a record, and the
        watcher is rebuilt from the environment either way.


## `Watcher.warm_new`

        Called after every restore, not only a cold one. `cold` asks whether
        the engine holds *any* levels, which was the right question when the
        instrument set never changed and is the wrong one now: with 2,018
        levels restored the engine is not cold, so the warm-up was skipped
        entirely and eleven new feeds were left to learn from the bus at
        roughly one bar a minute.

        Safe to call every start because it seeds only what has no series, and
        a feed with no series has no bars to double count.


## `Watcher.warm`

        The bus carries a notice per sweep, not a series - roughly one bar per
        venue per minute - so an engine that only learned from it would take
        days to see enough bars to place a level. The store already holds the
        history, read-only.

        `on_progress(done, total)` is for a caller with a terminal to draw into.
        Without one the replay reports itself to the log instead, which is the
        only place a running service can be watched from.


## `Watcher.vol_model_tally`

        This is the deliverable, not a diagnostic. `learned.py` is allowed to
        be worse than the line it replaces and the only thing that can say so
        is a head-to-head on identical bars - so if this never reaches a log,
        the model is exactly the thing `research/inert.md` catalogues: computed
        forever, read by nobody, settling nothing.

        `naive` is the last realised value. A forecaster that cannot beat it
        has not earned the CPU, whatever it beats among the others.


## `Watcher.drift_tally`

        **The counters existed and nothing read them.** `Drift.watching` was
        written to answer whether a second detector earned its window, and it
        had no caller anywhere in the service - so the one number that settles
        it was computed every tick and thrown away at every restart. That is
        the shape `research/inert.md` catalogues.

        Once it was finally logged it settled the question in a day: KSWIN
        fired zero times against ADWIN's 136, and is gone. What is left is
        ADWIN's own rate, which is worth seeing for its own sake - the whole
        episode happened because nobody could see either number.


## `Watcher._read_implied`

        On a thread because yfinance does its own HTTP, and wrapped because a
        quote is not worth an outage - `latest` already swallows its own errors
        and this is the belt for the braces.

        **Silence is handled by not writing.** A source that stops returns None,
        the last good reading stays where it is, and `Implied.MAX_AGE` retires
        it after three days. That is the failure mode that matters for a daily
        series: it looks alive for a long time after it dies.


