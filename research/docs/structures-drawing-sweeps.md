# Structures Drawing Sweeps

Rationale moved out of `till_infinity/structures/drawing/sweeps.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `liquidity_beyond`

    "Beyond" is away from where price is arriving from: an arrival from above
    is heading down, so what is beyond is *below*. That is the direction a
    sweep of this level would travel, and therefore the only side whose resting
    orders are a reason to run it.

    Returns a distance of 0.0 when there is nothing within reach, which is the
    interesting case rather than a missing value - it says a stop placed beyond
    this level is not sitting in front of an obvious target.


## `exposure`

    The number a strategy actually wants. Above 1.0 the stop sits *past* the
    liquidity resting beyond, so a run that takes those orders takes this one
    on the way - the worst place to stand. Near zero the stop is nowhere near
    it. Zero exactly means there is nothing within reach to be run toward.

    Deliberately a ratio rather than a verdict. Where the line falls is a
    question for the journal, and hard-coding one here would be inventing the
    answer this module exists to make measurable.


