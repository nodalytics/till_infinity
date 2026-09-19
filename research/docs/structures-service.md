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

## Inline notes

Passages that stood inside the functions named, moved out on 2026-09-19.
Each keeps its first sentence at the call site.

### `alert_payload`

It was absent, and its absence made that filter silently inert: the
filter reads the interval off the alert, found none, and kept
everything - so a floor could be configured, describe itself
correctly in the log, pass its own tests, and drop nothing at all.
The filter's own rule that a missing interval is *kept* is right for
a trade or a fault and was hiding this.

### `alert_payload`

parse it to find the one they wanted. Nothing here is new evidence - it
is the same fields, laid out so the eye can skip.
No header line here. `Notice.as_text` already prints the title above the
body, so a name-and-direction line inside it arrived as the same thing
said twice - and the clock is printed after the body for the same reason,
which is why the time is not repeated either.

### `alert_payload`


The first version of this line printed "2.4 to 1", which a reader takes
for a reward-to-risk ratio: target over stop. It is not. `expected_push`
is the *mean* outcome over every resolved touch, the bad ones included,
so it is already something closer to an expected value than to a target -
a better number, under a label that meant something else.

The dispersion goes beside it for the reason `Inference` states in one
line: "a large mean with a larger sigma is not a call". A reader who
cannot see the spread cannot tell those apart.

### `alert_payload`

`zma_*` and `cycle_*` have been published into `features` since they were
wired, so the journal has had them all along - and the card renders a
hand-picked set of fields, which these were never added to. The reading
was therefore recorded, scored, gated on, and **invisible to the person
the alert is for**. Publishing a feature and showing it are two jobs and
only one of them was done.

Read to a person and acted on by almost nothing, the same standing as the
break risk above: `TRADING_ZMA_GATE` can veto on it once a feed's record
earns that, and nothing else uses it. It is here so the number can be
disagreed with against what the chart then did.

### `Watcher.load`

so every one of these was inert from the moment a state file existed:
production drew levels with `pip` alone for the whole life of a
`STRUCTURES_FORMATION` that asked for three passes, and the only
symptom was `run` and `origin` never drawing anything.

What is learned is kept - the levels, their touch history, the
filters. What was *chosen* comes from this deployment.
**Weights come from their own file, after the engine is restored.**
`store._schema` invalidates the whole state file when any persisted
dataclass changes shape, so a deploy touching one unrelated field
would otherwise throw away every turn this has settled. See
`structures/cycles.py`.

### `Watcher.direct`

explain why a level gave way - but it is the only shape here that is
a *finding* rather than a fault, and the one the channel exists for.
Every call that reaches this point is already `actionable`
(`_level_calls` drops the rest), which is a stricter gate than any
score: enough evidence, enough separation from the base rate, enough
size. Routing it through agents that are switched off means publishing
it to a topic nobody is subscribed to.

### `Watcher.emit`

so every recorded call was anonymous as to instrument and
timeframe - which made "how does volatility scale across
intervals" unanswerable from our own record, and it is a
question we went looking for an answer to.

`feed` was recoverable from the first tag and `interval`
was nowhere at all. Both are here now, because a tag is
for filtering and a context is for measuring.

### `Watcher.record_outcomes`

and it is folded in before this runs - so looking up by
`level.price` searches for a key that no longer exists.
Every resolution, not only the predicted ones - and before the
journal lookup for the same reason the announcement is: most
touches were never called by anything, and those are the sample
a model learns most from.

### `Watcher.record_outcomes`

price getting through. Chop is neither and is not counted, which
is the discipline the rest of the package applies to it.
Named `resolved_as`, not `outcome`: `outcome` is the journal
function imported at the top of this module, and shadowing it
here made the very next call to it a TypeError. Caught by two
existing tests within a minute, which is the argument for having
them.

### `Watcher.record_outcomes`

merging them is that the journal says which price gets
respected, and it cannot say that if the record does not
carry which pass found it.

On the **outcome**, not the signal's features. Features
are `dict[str, float]` and `Signal.to_dict` rounds every
value, so a string there raises `TypeError: type str
doesn't define __round__` - which stopped the structures
service in production for four minutes.

`drawn_by` rather than `origin`, which in this namespace
already means the impulse origin.

### `Watcher.record_outcomes`

here**, so all 12,504 resolutions record zero timeframes
and "does agreement across timeframes predict anything"
cannot be asked of the only record that can answer it.

A string, so it belongs in the outcome context rather
than the features, for the reason `drawn_by` does:
features are `dict[str, float]` and a string there raises
on the first signal.

### `Watcher._read_implied`

is the one the loop keeps. A fetch that hangs here does not slow
the service, it stops it - and on CI, which has no network, it
held a Deploy job `in_progress` for **fifty minutes**, blocking
every deploy queued behind it.

`to_thread` cannot be cancelled, so this frees the *loop* and
leaves the thread running until the library gives up. That is the
right trade - the service keeps working - and it is not a full
answer: a wedged fetch still holds a worker. `FETCH_TIMEOUT` is
what bounds that, and this is what bounds the damage if it does
not hold.

### `Watcher._level_calls`

`Level.origin` has always carried the passes that drew it -
"pip+run+origin" - and `agree()` has always maintained it through
a merge. Nothing ever counted it, so "does a level two methods
found behave better than a level one method found" could not be
asked, of 969 recorded outcomes or of any others.

A feature and not a gate, deliberately and in that order: it
lands in the journal beside the outcome, and the outcome
machinery gets to say whether agreement is worth anything before
anything is refused for lacking it.

### `Watcher._level_calls`

Two corrections to what this used to be, and the second is the
larger. The first: the call's interval is the wrong anchor for a
strategy that enters below the hour on purpose, since a 15m
trigger gave a box made of two prices a quarter hour of auction
paused at.

The second: the walls were **confluence zones**, and a zone is a
price several timeframes drew a level at rather than a price
anyone defended. Measured over 4,117 published calls, at 4h the
zone box runs 385bps against the origin box's 71bps and is wider
on 2,711 of 2,724 - so the wall it named was open air with a
price on it, and a 24-hour trade was being asked to aim at it.

An origin is where a violent move began, so the interest that
stopped the last advance is still resting there. That is a wall.

Published beside the call's own box, not instead of it. A scalp
wants the box it is trading inside; a swing wants the room before
the next unfilled interest, and at the same moment on the same
instrument those are different boxes.

### `Watcher.run`

a day at fastest, so a restart would otherwise publish level calls
with no policy on them for however long the next poll is away - with
four hundred days of it already sitting in the store.

**And emit what it finds.** This discarded the return value, which
was worse than not calling it: `calls` records the stance it just
announced, so seven stance changes were computed, marked as already
published, and dropped - and the feeds they were about then stayed
silent until they flipped again. Nothing reached the journal, so the
expensive half of the FRED work looked like a model that never fires.

### `Watcher.run`

TaskGroup and the structures consumer is simply gone -
while the process stays up and the container stays
`healthy`, so nothing outside says so. That has now
happened three times: twice this month per
`_origin_at`'s note, and again on 2026-09-08, when the
only trace was 132,807 bus warnings that rotated the
supervisor's own error out of the logs.

Re-raised for `CancelledError` alone, which is shutdown
and must not be swallowed.

