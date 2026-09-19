# Trading Venues Broker

Rationale moved out of `till_infinity/trading/venues/broker.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `Broker.rest`

        The half of a resting entry we cannot do ourselves. A poller sees price
        at its own cadence, and a deep wick is brief by construction - it is
        the 14.6% tail of the depth distribution - so the fills most worth
        having are the ones most likely to be missed between two reads.

        The broker fills on its own tick and never blinks. What it cannot do is
        change its mind, which is why this is half of a hybrid rather than a
        replacement: the order is placed here and withdrawn by `withdraw` the
        moment a gate turns.

        `until` is a broker-side expiry, so an order outlives neither its
        window nor this process's memory of it.


## `Broker.catalogue`

        None is not a failure - it means "ask me one at a time", which is the
        honest answer for the HTTP bridge, whose only symbol route takes a
        name. The native terminal can enumerate, and when it can, resolution
        scans the list instead of guessing suffixes.

        That distinction matters more than it looks. A broker's account-type
        suffix is not a standard: `.raw`, `.r`, `.s`, `m`, `+`, `_SB` and a
        dozen others are all in use, and no list of them can be complete. A
        scan finds whatever this broker actually calls gold without anybody
        having guessed it first.


## `Broker.closed_deal`

        The terminal's own record, rather than the last snapshot we happened to
        hold. A position closed server-side vanishes between polls, and
        settling it at its last observed `price_current` is a guess that is
        always a little stale and always in the direction of the move that
        closed it: the first live trade recorded +52.20 where the broker had
        paid +59.40, a 12% error on the one number every strategy will later be
        scored by.

        None when the backend cannot answer, in which case the caller keeps the
        stale estimate and says so.


