# Trading Venues Mt5_Native

Rationale moved out of `till_infinity/trading/venues/mt5_native.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `NativeBroker._filling`

        Brokers differ, and a policy the symbol does not allow is rejected with
        "Unsupported filling mode" - a failure that looks like a bad order and
        is really a bad constant. The symbol's own `filling_mode` mask is the
        authority; the setting only chooses between what it permits.

        Async because the lookup is a call into the terminal, and over RPyC
        that is a socket round trip. Building it into the request dict
        synchronously blocked the event loop on the network for every order.


