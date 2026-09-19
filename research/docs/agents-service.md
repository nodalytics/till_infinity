# Agents Service

Rationale moved out of `till_infinity/agents/service.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `Headlines`

    A headline is worth waking a model for when there is more of it than usual
    - and "usual" differs by two orders of magnitude across the instruments
    tracked. Over seven days: **300 headlines about btc and five about usdchf**.
    A gate that fired on every routed headline would be 90 model calls a day,
    almost half of them btc doing nothing but being btc; one that demanded a
    burst would never hear about usdchf at all, which is the instrument a
    headline is most informative about precisely because it is so rarely
    mentioned.

    So the comparison is per feed, against that feed's own arrival rate - the
    same argument the spread gate makes about venues. Treating arrivals as
    Poisson, the question is how unlikely this many headlines in ten minutes
    would be at the rate this feed normally runs at. A lone usdchf headline
    sits right at the threshold and clears it whenever the feed has been
    quieter than its average - three times over the replay week - while btc
    needs a cluster before it means anything.

    ## The rate has to move

    An average over all of history was the first attempt and it was wrong in a
    way worth recording. Adding the crypto sources multiplied btc's headline
    volume roughly tenfold inside a week; the all-time rate still carried the
    old number, so the gate read the collection change as news and fired on
    **34.9 windows a day**, most of them btc. The rate is therefore a decaying
    count with a three-day constant - recent arrivals count fully, a week-old
    one barely - which brings the same replay to 10.3/day.

    Rates are also shrunk toward the average feed's, weakly. A feed with no
    history of its own would otherwise have a rate of zero, under which its
    first headline is infinitely surprising. Toward the *median* feed rather
    than the mean, which btc's volume alone would otherwise define.

    ## What this cannot see

    Nothing about the *time of day*: Asian hours are quieter than the New York
    open, and the gate will be a little eager in a busy session and a little
    deaf in a dead one. Modelling that is a bigger change than the size of the
    effect justifies at ten wakes a day.

    Nor anything about what a headline *says*. This measures how much is being
    written, not whether it matters, which is deliberate - judging the content
    is the analyst's job, and it is the thing being woken.


## `because`

    A fallback model raises an `ExceptionGroup`, and `str()` on one of those is
    **"All models from FallbackModel failed (2 sub-exceptions)"** - a sentence
    with no information in it. Production logged exactly that twenty-six times
    in a day while both models answered a direct call perfectly, and finding
    out why meant reproducing it by hand on the box.

    So the group is unwrapped, and so is the `__cause__` chain underneath it,
    because the useful line is usually the one furthest in: a rate limit, a
    token ceiling, a decommissioned model name.


## `Window`

    The list this replaces held every message until the window elapsed -
    101,297 of them, 199MB, to derive fifteen triggers. Nothing downstream
    ever wanted the messages: `interesting` reduces them to the widest spread,
    the loudest signal per instrument and the releases that printed, and
    `prompt_for` wants counts. All of that is computable one message at a time,
    so none of it needs keeping.

    Bounding the list was the stopgap; this removes the question. Memory is now
    proportional to the number of *instruments*, not to the traffic, so a busy
    session costs no more than a quiet one - and the spread spike that a bound
    could drop from the front of a full window can no longer be lost.

    One accumulator, used by both paths: `interesting()` folds a sequence into
    it and asks the same questions the watcher asks live, so the two cannot
    drift.


## `interesting`

    Cheap and deliberately blunt. Its only job is to keep quiet markets free;
    anything it lets through is judged properly by the analyst afterwards.

    A fold over `Window`, which is the same accumulator the watcher fills live.
    Keeping one implementation matters more than it looks: the streaming path
    and the batch path answering differently would be a bug nobody could see
    from either side.

    `spreads` makes the quote gate self-calibrating. Without it the configured
    threshold is used, which is the old behaviour and is only right for
    whichever instrument it was chosen on.


## `Quiet`

    Exists because a gate that never fires and a gate that never runs look
    identical from outside, and this one looked like the second for seven hours
    - the whole log held a single `agents started` line. It was in fact the
    first, declining correctly and saying so only at DEBUG, which production
    does not print.

    Reporting the *closest approach* rather than the fact of declining is what
    makes it useful: "nothing crossed" is unfalsifiable, while "widest spread
    1.9bps against 8.0 needed" is a threshold someone can judge.


## `prompt_for`

    The triggers are stated as what changed rather than as conclusions, and the
    model is pointed at its tools instead of being handed the data - the store
    holds far more than the window does, and the comparison it needs (is this
    spread unusual *for this venue*) is not in the messages at all.

    `seen` is the one-line summary of what arrived. A sequence of messages is
    still accepted and counted, because that is what the tests hand it and the
    counting is trivial; the watcher passes the string, having counted as the
    messages went past rather than keeping them to count later.


