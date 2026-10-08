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



## The second dimension, added 2026-10-08

The filter's state is `(price, slope)` rather than price alone - a
constant-velocity model instead of a random walk.

The reason is that levels which trend were a thing the one-dimensional version
could only ever **lag**. A rising floor met four times is four observations of
a line, and a filter whose only story is "it drifts somewhere" has to be
dragged to each new touch by its gain. It never anticipates, because nothing in
its state can.

### The gate is the whole design

A velocity state will fit a slope to noise given the chance - three scattered
touches are enough to produce a confident-looking trend. So the slope is used
only once it has cleared its own posterior: `trending` asks whether `|slope|`
is at least `SLOPE_SIGMAS` of `sqrt(var_slope)`, and until it is, every
projection treats the level as horizontal.

Three sigmas rather than two, because the costs are asymmetric. Being wrong
means a level that walks away from where price actually turns; being slow means
a level that behaves exactly as it did before this existed. Measured on a
10-touch walk: a series rising 0.5 a bar earns `+0.044/hour` and reads
`trending`; a flat one and a Gaussian-noise one both read not-trending, which
is the test that matters.

### The deadlock that nearly shipped

The first version gated the **covariance** propagation on `trending` as well as
the mean's. That cannot work: the off-diagonal `P01` is the only thing that
lets a slope be learned at all, so a slope gated out of existence never clears
the gate, and the filter reported `slope = 0.0000` forever while looking
entirely healthy. The covariance now propagates either way and only the mean's
carry is gated.

### Flip symmetry

A support that rises and a resistance that falls are the same object with one
sign flipped, and half the book is the second one. Nothing in the filter has a
sign preference, and that is pinned rather than left to be inferred from a
rising fixture: a falling series earns the mirror slope, the mirror mean offset
and the mirror projection, while `variance` and `var_slope` come out
**identical** rather than mirrored, because an uncertainty is a width.

The mirroring is exact to about `1e-10`, not to the bit. `updated` is epoch
seconds - a float near `1.7e9` - so the arithmetic cannot be exact, and a test
asserting equality to the bit would be asserting something about the clock
rather than about the filter.

### A level that never earns a slope is unchanged, to the bit

The slope terms enter `variance` only once `trending`, so a level that stays
horizontal follows **exactly** the variance path it followed before any of this
existed and quotes exactly the band it quoted - not "close to", the same
numbers, which a test pins against a verbatim copy of the old filter.

That was not the first version. The first let the `F P F'` terms through
ungated, on the reasoning that not knowing which way a level is going is a
reason to be less sure about its price later. The reasoning is defensible and
shipping it would still have been wrong: it widened **every** zone in the book
including levels with no slope at all, and it surfaced as `zma_agrees` going
near-constant in `test_no_published_feature_is_near_constant` rather than as
anything that looked like a filter change. The same test caught the same class
of error twice in one day - once here and once on the `displace` formation -
which is the best argument for it there is.

The price of the fix is a small inconsistency: the covariance keeps propagating
while the variance does not. It is taken deliberately. Learnability needs the
off-diagonal; production does not need its bands moved by a slope no level has
earned.

### Why the slope is not extrapolated forever

`F P F'` grows the price variance by `dt**2 * var_slope`, which is the honest
statement that a line reaching further is known less well - and at a month out
it is also an absurd one. Past `SLOPE_HORIZON_HOURS` the level is simply
horizontal with uncertainty still growing the way it always did.

The price process noise stays **linear** in the true elapsed time for the same
reason. The textbook continuous white-noise-acceleration `Q` is cubic in `dt`,
which is fine over a bar and nonsense over a fortnight: a level untested for a
month would come back with a zone the width of the range.

### `zone_at`, and what did not change

`zone` is now `zone_at(filter.updated, vol)` - the band as of the last touch,
which is exactly what every existing caller got before the filter had a slope.
That matters because `.price` is read 71 times and `.zone()` called from 10
places across the engine, confluence and levels itself; redefining either to be
time-dependent would have been a change to the core of a live desk dressed as
an improvement.

A caller that *has* a timestamp gets `zone_at(when, vol)` and the honest
widening instead. The centre moves with `when` only where the slope has cleared
the gate; the width grows either way, because not knowing which direction a
level is going is a reason to be **less** sure about its price later, not more.

### The gain stays a scalar

`update` returns `K[0]`, the gain on the price, not the pair. That number is
journalled as "how much did this touch move the level" and a 2-vector would
have changed what it means without anything downstream noticing. The slope's
share of the same innovation is `K[1]` and is not reported, because nothing has
ever asked for it.

### What this is not

It is not a trendline detector and it is not a regression channel, though it is
the same object a channel approximates: a channel is fitted to closes, this is
estimated from touches, and only the second one is evidence about a level.

Nothing here has been measured against outcomes yet. The gate makes the change
conservative - a level that has not earned a slope behaves as it always did -
but "conservative" is not "better", and whether a trending level predicts its
own next touch more accurately is a replay question nobody has run.

## The zone's width, calibrated rather than assumed (2026-10-08)

`ZONE_SIGMA` is two, and the docstring said the band was wide enough that
"price inside this band is touching the level in any sense the data can
distinguish". That is a **coverage claim** and it was made without a coverage
measurement: two sigmas is 95.4% of a Gaussian, and nothing had checked that
touches are Gaussian around a level or that the observation noise handed to the
filter is the right one. Either being wrong makes the band confidently the
wrong width, in a direction nobody can see.

`structures/conformal.py` replaces the constant with a width that holds its
target coverage by construction.

### Why not a width dimension in the filter

The obvious alternative, and it fails on the observation model rather than the
arithmetic: **width is not observed.** What is observed is a hit or a miss,
which is Bernoulli, and `|touch - centre|`, which is half-normal at best. A
linear-Gaussian filter over width would assume exactly the thing the band
exists to stop assuming. Kalman for the centre, conformal for the width - each
tool on the problem it is valid for.

### It is the machinery the envelope already proved

`vol/envelope.py` runs AgACI over the volatility envelope and
[`conformal.md`](conformal.md) measures it: at 50 bars **89.1-89.6%** across FX,
metals, crypto and Deriv against one-step ACI's 87.8-88.1%, and **2-9%
narrower** with better pinball in every cell. Narrower *and* better calibrated
is the pair of properties a zone wants.

Same correctors, same Bernstein Online Aggregation, one substitution: a zone is
an interval, not a quantile, so the **interval score** stands in for pinball.
Its gradient has the same linearised form, which is why the weighting reads
like `envelope._weights`.

### Two tails, not one width

The band reaches `q-` below the centre and `q+` above, calibrated separately.
The first version scored `|touch - centre|` and quoted one number both ways,
which threw away the sign of the residual - information, not noise.

**How far price overshoots a floor and how far it undershoots it are different
quantities.** A level price spikes through from above but drifts gently into
from below has a long tail one way and a short one the other, and a single
width is wrong on both sides at once: too wide where the distribution is tight,
too narrow where it is not. Forced to be symmetric it cannot even hold its
coverage - it must over-cover the short side or under-cover the long one, and
that is arithmetic rather than preference.

`COVERAGE` stays a statement about the band, so each tail gets `TAIL_MISS`,
half the total. Two tails at the full rate would leave twice as much outside as
asked for.

Measured on synthetic pools: a pool with a long lower tail and a short upper
one reaches **more than twice as far down as up**; a symmetric pool comes out
with the two within 0.35 sigmas and a `skew` of zero, which is the check that
says the `abs` version was losing nothing *there*; and the skewed band still
holds coverage within 0.04 of its 0.95 target, which a symmetric band cannot.

This is a different axis from the pooling. The pool is keyed by the side price
**arrived from**; the tails are the two directions the residual can point once
it has arrived. A level has both.

### Pooled by `(feed, interval, side)`

`CONFIDENT_TOUCHES` is 5 and most levels are sparse, so a per-level corrector
would calibrate on single digits of feedback and mostly report its prior back.
Pooling is not an optimisation here, it is what makes the estimate exist.

**Side** because the premise of this module is that a price met from below and
the same price met from above are two different objects, and there is no reason
their touch dispersion should match. **Feed and interval** because the score is
already normalised by the level's own sigma, so what is left to pool is exactly
the instrument-and-timeframe-shaped part.

That is the shrinkage argument `reactions` makes between a level's own record
and kNN over similar levels, applied to the interval instead of the probability.

### The score is out of sample

`|touch - centre| / sigma`, taken **before** the touch is folded into the
filter. After the fold it would be scored against a centre that had already
moved toward it - a residual being admired rather than a prediction interval
being tested. That ordering is the whole validity argument and it is pinned by
a test.

### What it measures, on synthetic pools

- a Gaussian pool lands at **1.96** sigmas, agreeing with the old constant
  where the old assumption was right - which is the only way to trust it
  elsewhere
- a heavy-tailed pool (a normal mixture, 15% at four times the dispersion)
  **widens past two**, which is the case the Gaussian band gets wrong
- a tight pool **narrows below two**, the other direction, where a band wider
  than it needs to be reads every passing wick as a touch
- coverage comes out within **0.04** of the 0.95 target on the heavy-tailed
  pool

### What it is not

[`edge.md`](edge.md) found a rolling quantile losing to a matched constant four
times out of four, and a walk-forward adaptive floor worse than no floor. Three
nulls is a strong prior and this would be a fourth if it were the same thing.

It is not. Those measured a rolling quantile as an **edge gate** - a statistic
predicting returns, where normalising per cell destroyed a comparability the
raw number already had. This calibrates an interval's **coverage**, a property
of the interval rather than a claim about direction. Worth saying plainly,
because both look like "a quantile over recent history" read quickly.

### Still unmeasured

Everything above is synthetic pools and unit tests. Whether a calibrated zone
changes outcomes on real touches - whether the levels it widens stop producing
spurious resolutions, and whether the ones it narrows produce more - is a
replay question nobody has run. The run-in means a cold service behaves exactly
as it did before, which makes the change safe and does not make it right.
