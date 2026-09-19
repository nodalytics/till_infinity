# Structures Vol Consensus_Vol

Rationale moved out of `till_infinity/structures/vol/consensus_vol.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `Ensemble.observe`

        `sigma_scaled` names the members that report a standard deviation - the
        range estimators and `vix` - so they are brought onto the mean-absolute
        convention rather than being averaged against it directly.

        `ratio` is **the series' own measured conversion**, defaulting to the
        Gaussian `sqrt(pi/2)`. The default is a convenience for callers without
        a series; the caller that has one should pass it, because the constant
        is 23% low at 1m across this book and 27% on FX - and right on the
        generated 72%, which is why it cannot simply be replaced. See
        `Volatility.mad_to_sigma` and `research/cascading.md`.


## `Ensemble.seed`

        **`SCORE_WARMUP` is 60**, and at daily bars that is about three months
        before a member earns any weight - over a year at weekly. A member that
        does nothing until December is not a member, so the score can be seeded
        from a replay over history and then left to live observations.

        The seed is a **prior, not a floor.** `Score.record` decays toward what
        it is currently seeing, so a seed the live bars contradict loses; and
        `seen` is what decides how long that takes, which is why it is supplied
        rather than assumed. A seed is a claim about history and not a
        measurement of this code, so live standings are worth logging beside it.


