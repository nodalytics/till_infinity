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


