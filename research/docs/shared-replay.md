# Shared Replay

Rationale moved out of `till_infinity/shared/replay.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `_first_target`

    The first-passage form `trading/barriers.probability` derives, with the
    distances measured **from the bar's open** and expressed in units of the
    bar's own range - which is the only volatility scale a single bar carries.

    Nearer barrier first, in proportion, with the overshoot pushing both walls
    out equally so an open exactly between them is a coin. That last property is
    what makes this a refusal to guess rather than a different guess: it cannot
    manufacture a direction the bar does not contain.


## `walk`

    None means the trade could not be replayed at all: no volatility unit, no
    modelled push, no stop the policy could place, or no bars left after
    `start`. **Not zero** - scoring an absence as a flat trade is how a replay
    gains a population it never made.

    The exit kind matters as much as the R. A policy that lifts mean R while
    being stopped just as often has bought something other than what was asked.

    `ambiguous` decides a bar that touched both barriers - see rule 3.

    * `"stop"` keeps the historical convention and its one-sided bias, so an
      existing result is reproducible rather than silently restated.
    * `"expected"` returns the **probability-weighted R** and the exit kind
      `"both"`. Not a better guess at which happened - a refusal to guess. Over
      many trades the weighted value is unbiased where a guess is not, and the
      bias is the whole problem: it is worth more than the findings it feeds.

    The weight is the first-passage probability from the bar's open, with the
    discrete-monitoring shift that `trading/barriers.py` derives. Implemented
    here rather than imported because `shared` sits under `trading` and must not
    reach up into it; the two are checked against each other in the tests.


