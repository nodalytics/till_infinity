# Shared Strata

Rationale moved out of `till_infinity/shared/strata.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `compare`

    `bucket` is a key or a function of the row. `within` names the stratum keys;
    empty means pooled only, which is the thing this exists to discourage and is
    still allowed, because a caller who has thought about it should not have to
    fight the helper.

    Raises if `value` carries no information - a comparison of a constant is a
    flat table somebody will then try to explain. See `liveness`.


