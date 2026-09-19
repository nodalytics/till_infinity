# Structures Context Trend

Rationale moved out of `till_infinity/structures/context/trend.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `Trend.scale`

        `span` is how far either side of 1 the multiplier may reach, so 0.3
        gives 0.7x in the flattest chop and 1.3x in a clean trend. Bounded on
        purpose: the measured effect is 0.34R between extreme deciles, which
        justifies leaning, not doubling.

        Sizing rather than a gate uses the whole curve. The relationship is
        continuous and monotonic across the top deciles, so a threshold throws
        away the middle - and a gate that turns out to be wrong shows up as
        nothing happening, which is the failure this repository keeps finding
        late.

        No opinion means no adjustment: a feed without enough history sizes
        exactly as it did before this existed.


