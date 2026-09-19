# Trading Venues Symbols

Rationale moved out of `till_infinity/trading/venues/symbols.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `matches`

    A match is one of the instrument's names plus **anything**, which is what
    makes an unguessed suffix findable. Ranked by how much was appended, so an
    exact `XAUUSD` beats `XAUUSD.s` beats `XAUUSD.raw.cfd` - the shortest
    addition is the plain instrument and the longer ones are variants of it.

    Case-insensitive **on both sides**, because it was only half so and that
    half worked by luck. The listing was upper-cased and the configured name
    was not, which every entry survived by being upper-case already. The first
    mixed-case instrument added - `Volatility 75 Index` - matched nothing at
    all, and the failure reads as "the broker does not carry it".


