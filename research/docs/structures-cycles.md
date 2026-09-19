# Structures Cycles

Rationale moved out of `till_infinity/structures/cycles.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `Slope`

    With weights `lam^k` on the bar `k` steps back, `a = sum(lam^k x)` and
    `b = sum(lam^k k x)` are everything a regression needs beyond the three
    weight sums. `a <- x + lam*a` is the usual recursion; `b <- lam*(b + a)` is
    the one that makes this possible, and it holds because every lag increases
    by one when a bar arrives.

    **The weight sums are accumulated too, rather than taken from their closed
    forms.** `sum(lam^k)`, `sum(k lam^k)` and `sum(k^2 lam^k)` have tidy
    infinite-series expressions and using them is wrong until the stream is
    long enough for the tail to vanish - which for the `k^2` term takes about
    **2,000 bars** at this decay. Checked against a least-squares fit computed
    the slow way: with the closed forms the slope is **109 times too large at
    300 bars**, converges by 2,000, and is exact from there. With the
    accumulated sums it is exact at every length, including the first bar.

    That is not a rounding difference. A slope 109x too large is the difference
    between an indicator that warms up and one that emits noise for the first
    month of every new instrument, silently, on exactly the feeds nobody is
    watching yet.


## `Cycles`

    **None of the three is believed.** `research/streaming.md` measured all of
    them at nothing against a matched null, and they are here so the question
    can be settled from the journal on this desk's own instruments rather than
    from a simulation. See the module note.

    * `alignment` - displacement agreement, weighted by how stretched each cycle
      above is. A mother cycle sitting mid-range is not disagreeing with
      anything, and counting it as opposition would be a coin.
    * `with_trend` - the traders' version: the fast reversion call points the
      way the cycle above is already moving.
    * `residual` - a stream fed `price / anchor`, the mother cycle divided out
      before the z-score is ever taken. Different in kind from the other two,
      because it changes the reading rather than voting on it.


## `Cycles.features`

        Four families, and they are the four things a reversal is described by
        wherever it is described:

        * **the extreme** - how stretched, and how far the leg has already run;
        * **the derivatives** - the slope and its own rate of change, because a
          first derivative crossing zero says a turning point and only the
          second says which kind;
        * **the extremes behind** - the pivots the current structure is built
          on, whose loss is the change of character;
        * **volatility** - the unit everything else is measured in, and how far
          it sits from its own normal.


## `Turns`

    A turn confirms when price retraces `TURN_SIGMAS` volatility units from the
    running extreme. The extreme is then in the past - that delay is not a flaw
    in the detector, it is why the prediction is worth making.

    **Feedback is delayed and batched, because that is how the answer arrives.**
    No prediction can be scored until the turn confirms, and then every
    prediction made during the leg settles at once. `ADWIN` watches the residual
    so the desk can be told when the model has stopped fitting rather than
    discovering it from a drawdown.

    `depth` is how much further price runs before turning, in volatility units.
    `when` is `log1p(bars)` until it does. `research/streaming.md` measured the
    first as predictable on constructed spreads and **the second as not**: its
    skill is positive on the nulls too, so a positive value is a property of the
    metric and not of the series. `when_skill` is published anyway, and this
    note is the reason not to read it as a result.


## `Series.capped_push`

        Returns `(push, why)`. `why` is empty when nothing was changed, which is
        the overwhelming majority of calls: the switch is off, the head is cold,
        the feed has not earned it, or the claim already sits inside the turn.

        **Never raises the push.** A model that could enlarge a target would be
        a model placing trades. This one can only decline to claim a push
        through a turn it expects, which is the conservative half of a forecast
        and the only half worth acting on before the record is long.


## `Book.save`

        **Separate from the engine's state on purpose.** `structures/store.py`
        hashes the shape of every persisted dataclass and invalidates the whole
        file when any of them changes, so a deploy that adds one field to one
        unrelated class throws away every weight this has learned. Months of
        settled turns are not something to lose to an unrelated refactor.

        Written to a temporary file and renamed, so an interrupted save leaves
        the previous weights rather than a truncated file.


