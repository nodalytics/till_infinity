# Structures Vol Projection

Rationale moved out of `till_infinity/structures/vol/projection.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `Cone`

    `Restorable` although a cone is computed fresh on every call and never
    saved. The invariant this package enforces is that **every slotted
    dataclass under `structures` restores a snapshot written before one of its
    fields existed**, and it is enforced blanket rather than per-class because
    the alternative is deciding, per class, whether something might one day be
    held inside something that is persisted - which is exactly the judgement
    that gets made wrong. `ranges.Bar` carries it for the same reason.


## `cone_at`

    `project` reads sigma off the instrument's name, which is the point of this
    module. A calibration study needs the other thing: the same geometry at a
    sigma the name does not give - fitted out of sample, or scaled by a bar's own
    tick count - so two parameterisations can be scored on identical rows.

    It exists because building a `Cone` by hand is a trap: `bands` defaults empty
    and nothing fills it, so a hand-built cone fails several frames below the
    caller on whichever row of a long run reaches it first.


## `Calibration.resolved`

        Accumulated `sigma^2 T`, not a count of bars. A drift is a statement
        about calendar span: the log returns telescope, so a million one-minute
        bars say no more about it than the same span of daily ones. Counting
        rows instead raises this flag at a fifth of the separation it promises
        at hourly spacing - see `RESOLVES_AT`, and `research/pipeline.md` for
        the estimator that measured it.

        Reported rather than enforced, because a caller is entitled to read an
        unresolved number as long as it is labelled as one. The alternative -
        returning a winner at `n = 300` - is how a convention gets adopted on
        noise and stays adopted.


## `Book`

    Per feed rather than per feed and timeframe, which is the one place this
    deliberately differs from `volatility.Book`. A cone is parameterised by a
    horizon in **seconds** and its width scales as `sqrt(t)` from a single
    published constant, so one projector answers every timeframe exactly. The
    volatility estimates need a key per timeframe because they are *estimates*
    and a 4h estimate of a 5m move is wrong; this needs none because it is a
    derivation and the horizon is an argument.


