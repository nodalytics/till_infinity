# Structures Vol Learned

Rationale moved out of `till_infinity/structures/vol/learned.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `_model`

    `HoeffdingTreeRegressor` on the table above: within 10% of the adaptive
    variant's learning cost, an order of magnitude cheaper to predict, and the
    smallest of the tree family by memory - which is the constraint that
    actually binds here.

    The adaptive variant was the tempting choice, since it carries its own
    drift detection. It is not needed: drift is what `focus_nats` is *for*, and
    handing the model the evidence as a feature is a better answer than having
    the tree quietly rebuild a subtree without saying so. One of those appears
    in the journal and the other does not.


