# Trading Manage

Rationale moved out of `till_infinity/trading/manage.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `partial`

    **Measured from the current price, after the first version read `best` and
    was wrong.** The original argument was that a trade which touched 1.2R and
    retraced had already *earned* the partial, so the retracement should not
    cancel it. Production showed what that means in practice: a us30 position
    logged "banking 50% at 1.5R" and booked **-1.14**, because the trigger read
    a high-water mark while the close executed at market whenever the manage
    loop next ran, by which time price was back through the entry.

    The point of banking is to capture a gain that is *there*. A high-water
    mark is a gain that was there. Reading it arms a market order at a price
    nobody is offering any more, and the log line then describes an event that
    did not happen - which is worse than not banking at all.

    `best` is still taken, because break-even and trailing genuinely do want
    the high-water mark: they protect a trade against giving back what it made,
    which is a different question from realising it.

    **The volume arithmetic is where this goes wrong if it goes wrong.** A
    position of the minimum lot cannot be halved, and a broker asked to close
    0.005 of a 0.01 lot either refuses or - worse - closes the lot. So the
    slice is rounded down to the volume step, and both halves must survive:
    if what comes off or what stays behind lands under `volume_min`, nothing
    is taken and the position runs whole. That is the honest outcome, because
    a scale-out that silently closes everything is not a smaller version of
    this rule, it is a different and much worse one.


## `_behind_the_last_rung`

    "Cleared" is doing the work. For a long that is the **highest** rung below
    the high-water mark: the last price the market agreed on that the trade has
    got past, and therefore the last one it can fall back to and still be
    right. A rung above `best` has not been reached and is a target.

    `clearance` puts the stop beyond the level rather than on it, because a
    level is where price turns and a stop sitting exactly there is taken by the
    turn it is meant to survive.


