# Trading Turning

Rationale moved out of `till_infinity/trading/turning.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `score`

    **Both arguments are in R, and that is deliberate.** `best_r` is what the
    service already computes for the journal - how far in front the trade got,
    in units of the risk it was sized for - and `ahead` is built on the same
    denominator, so "was the suggestion reached" is one comparison with no
    prices, no signs and no conversion to get backwards.

    If the suggestion sat inside the path, a resting order there would have
    filled and the trade would have banked `ahead` R; if it did not, the
    suggestion never triggered and the trade ended however it actually ended.


