# Structures Zma

Rationale moved out of `till_infinity/structures/zma.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `Zma.__post_init__`

        A `default_factory` is evaluated with no access to the instance, so
        `deque(maxlen=PERIOD)` captures the *module* constant and every `Zma`
        kept fifty prices and two hundred z-scores however it was constructed.
        The two fields were decorative, and silently so: `Zma(period=200)`
        built, reported `period == 200`, and behaved exactly like the default.

        Found by `research/harness/zmaonline.py`, whose mixture over periods
        20/50/100/200 produced four experts with identical predictions and
        therefore an exactly uniform weight vector - which is not a result a
        mixture can produce by accident.

        Production only ever builds the default, so nothing shipped was wrong;
        a study of whether some other period is better could not have been run.


## `Zma._attention`

        **This was inert for the whole life of the indicator.** The weights were
        `exp(|r| - max|r|)` over raw returns, and a softmax only has an opinion
        when its inputs differ by O(1). Absolute one-minute returns differ by
        about 1e-4, so every weight came out at 1.0000 and the
        "attention-weighted" mean was the plain one. `research/streaming.md`
        measured Kish's effective sample size at **49.00 of 50** on real BTC
        bars, on a deliberately spiky series and on an Ornstein-Uhlenbeck
        process - a uniform weighting over this window is exactly 50.

        The fix is a **temperature**: divide by the window's own mean absolute
        return before exponentiating. That puts the exponent at O(1), where a
        softmax discriminates, and makes the weighting scale-free at the same
        time - gold at 4,400 and a volatility index at 1.0 weight their moves
        alike, which the raw form never did either.

        Subtracting the maximum is kept and is now doing its actual job. It
        cancels in the normalisation and exists only to stop `exp` overflowing;
        applied to *unscaled* inputs, as before, it was the entire computation.

        `CAP` bounds how far one bar can get above the rest. Without it a single
        print a hundred times the typical move drives every other weight to
        underflow and the mean is that one bar, which is not attention - it is
        a lookup.


## `Book.warm`

        **Because nothing else fills it on a restore.** `Engine.seed` feeds
        this through `observe_bar`, but `warm_new` only replays feeds the
        engine has *no series* for - and a restored engine has series for
        everything, so on any restart that keeps its levels the book stays
        empty and starts counting from the next live bar. That is weeks to
        reach the two hundred settled calls `TRADING_ZMA_GATE` and `cycle-turn`
        both wait on, and it was measured at zero series against 261,192
        restored level closes on the live desk.

        `series` yields `(feed, interval, closes)` oldest-first. Kept free of
        where the bars came from: this module has no business knowing about the
        price store, and a caller that hands it the wrong closes - several
        venues interleaved by timestamp, say - would be handing it a violently
        reverting series that is an artefact of the query.

        A series that already has a record is never replayed *on top of* it -
        doubling counts would be worse than not warming at all, because the gate
        reads the count as evidence.

        **But it is rebuilt when the store holds a great deal more history than
        the series has seen.** Not a hypothetical: a record earned against a
        shallow store outlives the store growing, and the first thing anybody
        does when a gate is short of evidence is fetch more bars. Without this
        those bars are written, and read by nothing, because the series they
        belong to already has a record and was therefore skipped forever.

        Rebuilding means a *fresh* series over the whole stored run, not an
        extension of the old one: an online model is sequential, and replaying
        older bars into a state that has already seen newer ones is not a
        record of anything. The rebuilt pass is prequential exactly as the live
        one is - each call scored on the bar after it - so what it produces is
        the same measurement over more of the same series.

        `seen + WARM` as the bar, so this does not churn: after a rebuild the
        series has seen the whole store, and the next restart finds nothing new
        enough to be worth another pass.


## `Book.save`

        **Only the record, not the stream.** The prices, z-scores and dynamic
        thresholds rebuild themselves from a few hundred bars, and a restored
        window pasted beside counts earned on a different stretch of history is
        a mismatch nobody would notice. What cannot be rebuilt is how often
        this reading has been right on this feed, which is the only number that
        decides whether it is ever allowed to act.

        Written to a temporary file and renamed, so an interrupted save leaves
        the previous record rather than a truncated one.


