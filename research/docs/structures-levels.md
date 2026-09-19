# Structures Levels

Rationale moved out of `till_infinity/structures/levels.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `SideStats.hold_rate`

        `rejects` already carries back checks, because a retest that holds is
        the level holding - see `record`. Breaks and traps both count as price
        having got through, a trap being one that came back.

        This is the strongest thing a level knows about itself. Bucketed on
        corrected code it runs 59.4% to 92.2% across four bands with an AUC of
        0.648, and it is the only signal in that study that got *stronger* when
        the volatility denominator was fixed - against `Level.strength`'s 0.548,
        a composite that does not contain it.

        Unshrunk on purpose. Consumers want different priors and the honest
        pooled rate to shrink toward is instrument- and epoch-specific, so the
        raw rate is published beside `decisive` and the caller does its own.
        Zero decisive interactions gives 0.0, which is why the count travels
        with it - a rate with nothing behind it is not a low rate.


## `Level.sweep_zone`

        `zone` answers "is price at this level", and for that a band built from
        the average wick is right - widening it would make every passing tick an
        interaction and the level's own statistics would stop meaning anything.

        A stop asks a different question: *how far past this level does price
        go when it goes past*. Answering it with the same average puts the stop
        at the depth roughly half of all sweeps exceed, which from the account
        looks like being stopped out and then watching the move happen. This is
        the same construction with the far edge pushed out by `sigmas` of the
        wick's own spread instead.

        Clamped by the same ceiling as `zone`: past that width a level predicts
        nothing, and that stays true whichever question is being asked.


## `Level.regime_changed`

        `severity` is the change's percentile among past changes, in [0, 1], so
        the discount is graded rather than flat:

            decay = 1 - severity * (1 - REGIME_DECAY)

        A 99th-percentile change nearly resets the history; a 55th-percentile
        one barely touches it. Grading matters because the alternative is one
        constant standing in for every regime change there will ever be.

        The level itself survives either way - price still turns there. It is
        the statistics that were learned in a market that no longer exists.


## `form`

    Agglomerative and one-dimensional: sort the swings by price and merge
    neighbours that sit within `tolerance_vol` volatility units of each other.
    Simple, and correct for the shape of the problem - the data is a line, so
    the cluster boundaries are just the gaps in it, and the popular alternatives
    (k-means, DBSCAN) either need k chosen in advance or rediscover exactly this
    in more code.

    Clustering in **volatility units** rather than basis points is what lets one
    tolerance work across gold, BTC and EURUSD at once.

    A cluster needs `min_swings` distinct turns. Two is not enough: any two
    swings define a line, so a two-swing level is not evidence of anything, and
    admitting them is how a chart ends up with a level every few basis points -
    at which density every price is "at a level" and the model predicts nothing.

# Structures Levels

Rationale moved out of `till_infinity/structures/levels.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `half_life_days`

    A single constant cannot serve both ends. Twenty-one days is far too long
    for a 5m level - behaviour from three weeks ago on a five-minute chart is
    not evidence about now - and far too short for a weekly one, which might
    only be tested a handful of times a year and would have forgotten each
    touch before the next arrived.

    Anchoring to the window instead makes it self-scaling: evidence halves over
    about half the history that timeframe can see. That works out at under a
    day for 5m, ten days for 1h, six weeks for 4h and most of a year for 1d.


## `Level.zone`

        A level is a zone, not a line, and it is not symmetric. The centre is
        the **origin** - where the leg in ended and the leg out began - and each
        edge extends by however far the **wick** ran past it on that side. Price
        arriving from above wicks *down* through the level, so the lower edge is
        the one that stretches; arriving from below stretches the upper.

        Width also has a floor from the filter's own uncertainty, so a level
        with no wicks recorded yet is still a band rather than a line, and both
        edges are clamped in volatility units to stay meaningful in any regime.


## `agree`

    The point of forming levels two ways is not to pick a winner but to notice
    where they **agree**: a bar extreme that is also a run boundary has been
    confirmed by two methods that fail differently, which is a stronger claim
    than either makes alone. A level only one pass found is weaker, and the
    difference is invisible unless it is recorded here.

    Sorted and joined so `pip+run` and `run+pip` are the same string - an
    origin that depends on the order the passes happened to run in would be a
    fact about the code rather than about the level.


