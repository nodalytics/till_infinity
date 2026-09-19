# Prices Options

Rationale moved out of `till_infinity/prices/options.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `dealer_sign`

    The convention behind every "GEX" chart is that the public buys calls and
    dealers sell them, so dealers are short call gamma and long put gamma. On
    crypto venues, where covered-call selling by holders is a large share of
    the flow, that is arguably backwards - which is exactly why this is a
    parameter with a default rather than arithmetic baked into a total.

    Nothing in this repository is entitled to use it without saying which way
    it set it and why.


