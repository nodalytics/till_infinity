# Structures Learning Baseline

Rationale moved out of `till_infinity/structures/learning/baseline.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `Bench`

    **One set of models per horizon band, not one across everything.** Pooled,
    every score here was dominated by a population where the answer is written
    into the question: a touch approached from above that resolves inside a
    minute resolves upward 100.0% of the time, because that is what a rejection
    means, and 46% of resolutions are that fast. Every model reproduced the
    definition and scored 84-88% against a 52% base rate.

    Banding is not a reporting change. A parametric model fitted on the pooled
    stream *learns* the fast tautology and carries it into its predictions
    about slow touches, so the band has to reach the training and not only the
    report. See research/similarity.md.

    The kNN needs no equivalent here because it has no parameters - its
    training set is its neighbour pool, and `Memory.neighbours` bands that
    directly.


## `Bench.observe`

        `held` is the ground truth. `knn_said` is what `reactions` claimed, so
        the incumbent is scored on exactly the touches its challengers saw -
        the alternative, two separate runs, compares two samples rather than
        two models.

        `interval` picks the horizon band. Everything is scored twice: into its
        own band, which is the number worth reading, and into the pooled set,
        which is what every earlier figure in this repository was. Keeping both
        is what makes the size of the mistake visible rather than asserted.


