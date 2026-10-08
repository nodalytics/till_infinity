# Learned Vol

Rationale moved out of `till_infinity/structures/vol/learned.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `_anomaly_model`

    Every other reading in this package is **univariate**: `vol_stretch` asks
    whether the scale is unusual, `focus_nats` whether the mean just moved,
    the rolling quantiles whether this reading is high for this instrument.
    None of them can say that a combination is unusual while every part of it
    is ordinary - and `learning/anomaly.py` makes exactly that case for the
    cross-venue model: "a small deviation is fine, a slightly wide spread is
    fine, both at once on a venue that has gone quiet is not".

    Here that becomes: an elevated `span_rel` is ordinary, some `focus_nats` is
    ordinary, both together in an hour this instrument is normally quiet in is
    not. That is a statement no single feature in the row can make.

    `MinMaxScaler` in front because `HalfSpaceTrees` partitions the unit cube
    and expects bounded inputs; the ratios here are not bounded. Five trees of
    height six rather than the default ten and eight: measured in this
    container at 290us and 123KB against 685us and 1.16MB, on a two-core box
    with about a gigabyte spare, and the dynamic range that costs is recovered
    by the percentile transform rather than by the model.


## `Learned._anomaly_pct`

        **The percentile, not the score.** `HalfSpaceTrees` is uncalibrated -
        `learning/anomaly.py` records its median landing around 0.77 on normal
        data, and measured here on random rows the tenth and ninetieth
        percentiles were 0.70 and 0.83. A feature living in a tenth of its range
        is one a tree can barely split on, and the position of that band drifts
        as the market changes, so a constant read off it today would mean
        something else next month.

        Ranking against the model's own recent output fixes both: it fills
        [0, 1], and it re-centres itself the way `QuantileFilter` does for the
        cross-venue detector rather than the way a fixed cutoff does not.

        0.5 while cold - deliberately the middle. This is one feature among
        twenty and a missing reading should sit where it says nothing, not at
        an extreme that says "most anomalous thing I have ever seen".



## Directional efficiency (2026-10-08)

`research/papers/state-space.md` records someone else's zone-fill model, whose
inputs are tick speed, zone size, distance to the zone and **directional
efficiency**.

**A correction to the first version of this note.** It claimed nothing in
`structures` computed net move over path length. That was wrong:
`context/trend.py` already had it, as `Trend.efficiency`, and the formula is
identical - `abs(sum(steps)) / sum(abs(steps))` is `|last - first| / path`.

What is actually new is the **series it is asked of**. `Trend` runs the ratio
over recent *level prices*, to scale sizing. This runs it over recent *bar
closes*, as a model feature. Same statistic, different input, different
purpose - and now **one definition**: `trend.ratio`, which both call.

    efficiency = |last - first| / sum(|step|)

Kaufman's ratio. One is a move that went straight there; zero is ground covered
to no end. Bounded in `[0, 1]` by the triangle inequality, which is why it
needs no scaling and compares across instruments as it stands.

Below `trend.FEWEST` points it reads zero, using that constant rather than
inventing a second one - two points are trivially perfectly efficient and say
nothing, which is why it exists. Collapsing the two copies into one changed
that behaviour and a test caught it, which is the argument for having written
the test before noticing the duplication.

### What else of that family already exists

Checked, because the first claim here was wrong and the same mistake is cheap
to repeat. Most of the physics-flavoured vocabulary is already in the tree:

| | where | measured? |
|---|---|---|
| efficiency | `context/trend.py` `Trend.efficiency` | used for sizing |
| **energy** | `reactions.py` `Touch.energy` - `departure_vol / approach_vol`, "how much harder it left than it arrived" | published per touch |
| **force** | [`force.md`](force.md) - `approach_vol` AUC **0.5429** in band, `slowing` **0.5237**, `depth_vol` **0.4180** read inverted | yes, 10,871 touches |
| velocity | `reactions.py` `velocity_r` | published |
| momentum | `context/cusum.py`, an accumulating sum rather than a fixed lookback | published |
| **penetration** | nothing | **absent** |

So "force" is not a gap - it is a question already asked and answered, and the
answer is in `context/registry.py`'s roster with its AUC beside it. The one
term with no implementation is **penetration**: how far past a level price got
before turning. `depth_vol` is close and is not it, since depth is measured
into the zone rather than beyond it.

### Why it is worth having on its own

**It is the distinction `origins` and `displacement` keep circling, said
continuously.**

One asks whether a move was **large** - `MOVE_VOL` units in `MOVE_BARS` bars.
The other asks whether it was **one-sided** - `PUSH_N` bars of `PUSH_BODY`+
body. They were measured against each other and agree only 59-78% of the time,
and `displace` against MCFL's `DISPLACE_C` agree on about a quarter
([`structures-drawing-displacement.md`](structures-drawing-displacement.md)).

Every one of those answers with a **threshold**, and every threshold has been
argued over: 0.70 became 0.65 on the desk's call, the origin's body became a
band, `DISPLACE_C` grades against the last ten bars instead. Efficiency is the
same question with the threshold removed, so a model finds its own cut rather
than being handed one.

It also costs nothing to compute: `Series.closes` is already a 21-deep deque,
so this is a pass over state that was already kept.

### It is unsigned, and that is the finding applied

`|net| / path`, so a fall as straight as a rise reads the same. Direction is
already carried by `r1`, `r5` and `r20`, and the one positive result of the
whole z-score line was that **stripping the sign** took IC from +0.0024 to
+0.0782 ([`zscore-magnitude.md`](zscore-magnitude.md)). Efficiency being
unsigned is that result applied rather than an oversight.

### The window

`EFFICIENCY_N` is ten, matching `MOVZ`. Nothing yet says which window is right,
and two unexplained constants are worse than one. Whether ten is the right
number is a sweep nobody has run.

### How it will be judged

It joins `MODEL_NAMES` as the fourteenth feature rather than becoming a gate,
which is the same route `body`, `displaced` and the forward readings took: a
feature that does not help fails `vs_champion` in the retrain contest and never
ships. That is a safer way to use an input nobody has traded on than a
hand-written threshold - and it is the reason the recipe string is bumped with
it, so a model trained without `efficiency` is **refused** rather than fed an
input it never saw.

`MODEL_RECIPES` keeps the two older recipes, so the three FX models in service
still load and quote on the features they declare while they wait for a
retrain.

### Unmeasured

Whether it separates anything. The note that suggested it claims it as an input
to a zone-fill probability, and that claim has a free null already in the tree
- `timing.probability_within`, the reflection-principle chance of touching
something that far away within that many bars, with no weights to tune. Beating
that is the test, and it has not been run.
