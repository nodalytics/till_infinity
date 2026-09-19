# Trading Models

Rationale moved out of `till_infinity/trading/models.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `Intent.geometry`

        **Nothing in this package asked this until 2026-09-12.** `min_probability`
        gates on the kNN's *directional* call and `min_reward_to_risk` on a ratio
        with no probability attached, so the one question that decides whether a
        geometry is worth taking - P(target before stop, given these barriers) -
        was never computed. See `trading/barriers.py`.

        Recorded, not gated. That is this repository's convention for a number
        that moves money, and it matters more than usual here: the forms are
        derived and confirmed on the Volatility indices, where the process is
        known to be Brownian, and on a real feed they are a sharp prior rather
        than a measurement. The journal is where that gets tested.

        `barrier_ticks` is carried alongside because the answer depends on it and
        the desk does not yet measure it per feed - so a later reading can
        recompute these from the same rows rather than guess what was assumed.
        `barriers.ticks_from_slippage` already suggests the default is far too
        coarse for a liquid feed: the desk's own stops imply about 280 looks a
        bar, not thirty.

        Empty rather than zeroed when the geometry cannot carry it, so an absent
        reading is distinguishable from a real one - `research/inert.md` is a
        catalogue of the alternative.


## `money`

    `$` for dollars, `12.56 SGD` for anything without a well-known symbol - an
    unrecognised code is written out rather than guessed at, because a wrong
    symbol is worse than a verbose one. The sign sits outside the symbol:
    `+$12.56`, not `$+12.56`.

    Here rather than on `Trader` because more than one thing prints money. The
    running day total in `risk.Guard.summary` did not, and read as a bare
    number beside a title that had the symbol - which is the sort of
    inconsistency that makes a reader doubt both.


