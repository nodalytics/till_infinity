# Structures Context Cusum

Rationale moved out of `till_infinity/structures/context/cusum.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `adaptive_threshold`

    Volatility units already normalise for how much an instrument moves per
    bar, and that turns out not to be enough: the *push* an instrument makes
    once it starts moving varies on top of it, from 1.66v on eurusd to 2.75v
    on brent - a 1.7x spread that a single number cannot serve. A threshold
    right for one is late for the other.

    So the threshold is a share of the typical push, floored and capped. The
    floor is what keeps this honest when the estimate is missing, cold, or
    absurd: an unknown push returns the floor rather than zero, because a
    threshold of zero makes every tick an event.


## `Ensemble`

    A single tick-driven filter answers "is there momentum" at one speed, and
    which speed it happens to be is an accident of how often quotes arrive. A
    burst on a quiet instrument and a drift on a busy one produce the same
    accumulation for different reasons.

    Several filters, each sampled at its own cadence, separate those. Momentum
    that shows on 1m and nowhere else is noise; momentum that shows on 1m, 5m
    and 15m at once is the market doing one thing at several resolutions. What
    the ensemble adds over any single member is **agreement**, which is the
    part a single filter cannot report however it is tuned.

    Members are sampled rather than resampled: a tick is handed to a member
    only once its interval has elapsed since that member last saw one. That
    makes each member a filter over that timeframe's closes without needing
    bars, which matters because this is fed from the quote stream.


## `Ensemble.agreement`

        1.0 is every timeframe pushing up, -1.0 every one pushing down, and
        zero either a split or nothing moving. This is the reading a single
        filter cannot give, and the reason for the ensemble.

        Divided by every warm member, not only those with a view, so a
        timeframe that is genuinely flat dilutes the reading. That is the
        honest answer: not all of them agree.


