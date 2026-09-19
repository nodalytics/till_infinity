# Trading Exposure

Rationale moved out of `till_infinity/trading/exposure.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `register_broker_legs`

    An unmapped feed is not merely unmeasured, it is **exempt** from the
    currency limit - which is the one failure mode that looks like nothing at
    all, and which a test catches by insisting every tracked instrument maps.

    A distinct base token each, because `Volatility 75` and `Volatility 25` are
    unrelated generators and a shared base would net a long in one against a
    short in the other as though they were the same risk. The quote leg is
    real: the account is in dollars and so is the margin.


