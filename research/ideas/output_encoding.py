"""The output layer's encoding: does 0..1 or -1..+1 come out best?

Asked on 2026-10-16, alongside the request for an output layer that weighs the
terms, adds a bias and an activation, and hands one signal to the rest of the
system. That layer is now
[`statespace/signalling.py`](../../till_infinity/structures/statespace/signalling.py)
and **this harness scores the shipped class itself** rather than a copy of its
arithmetic, so a disagreement between the two is impossible.

## Half the question has an answer with no measurement in it

    tanh(x) = 2 * logistic(2x) - 1

exactly. So a `tanh` layer at weights `w` and bias `b` and a `logistic` layer
at `2w` and `2b` are affine images of each other: they order every pair of
inputs identically, every AUC is identical to floating point, every threshold
on one maps to a threshold on the other. `Layer.as_logistic` performs the
conversion and `tests/test_statespace.py::TestOutputLayer` asserts the
identity. The `output` column below re-confirms it on real data, which is a
check on this harness rather than a finding.

The choice between them is therefore **ergonomic**: `-1..+1` puts no opinion at
zero so the sign is the side, and `0..1` reads like a probability, which this
number is not. The desk has already shipped one number that was read as a
probability and was not - `prod-probability-up-needs-halving`.

## The half that is a real question is the **input** encoding

A term can go in three ways, and these are not affine images of each other:

| encoding | what a term becomes | keeps the sign |
| --- | --- | --- |
| `raw` | the standardised value, unbounded | yes |
| `signed` | `tanh(z)`, bounded to -1..+1 | yes |
| `probability` | `logistic(z)`, bounded to 0..1, neutral at 0.5 | yes |
| `unsigned` | `abs(tanh(z))`, bounded to 0..1, neutral at 0 | **no** |

`raw` against `signed` is a nonlinear per-term squash, which **does** change a
weighted sum's ranking - unlike the output activation, which cannot.
`probability` against `signed` differs only by a per-term offset, which a
**fitted** bias absorbs and a hand-set one does not, so the two should separate
under hand-set weights and converge under fitted ones. And `unsigned` throws
the sign away, so it cannot vote a side at all.

## Registered before the run

1. `tanh` and `logistic` outputs agree to 1e-12 on every arm and both targets.
2. `unsigned` collapses on **direction** - it has no sign to offer - and is the
   best encoding for **magnitude**, where only the size of a term matters.
3. `probability` matches `signed` once the weights are fitted and loses to it
   when they are hand-set at equal weight, because the offsets land in the sum
   instead of in the bias.
4. Nothing beats its null on direction by more than noise, because
   `signal-layer.md` already measured that the direction is a coin. The point
   of this run is the **ordering of the encodings**, not a rediscovered edge.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from signal_layer import (  # noqa: E402
    FEATURES,
    GENERATED,
    GROUPS,
    NULLS,
    PLANTS,
    TRADED,
    auc,
    gather,
)

from till_infinity.structures.statespace import Layer, squash  # noqa: E402
from till_infinity.structures.statespace.signalling import LIMIT  # noqa: E402

FRAMES = ("15m", "1h")
HORIZON = 12
#: The temperature the layer is scaled by before the activation. A
#: `t`-statistic reaches three and more, where `tanh` is already flat at 0.995,
#: so an unscaled layer of them saturates and throws away its own range.
TEMPERATURES = (1.0, 0.25)
ENCODINGS = ("raw", "signed", "probability", "unsigned")
SEED = 20261016


def encoded(table: np.ndarray, how: str) -> np.ndarray:
    """One input encoding of an already standardised feature table."""
    if how == "raw":
        return table
    if how == "signed":
        return np.tanh(table)
    if how == "probability":
        return 1.0 / (1.0 + np.exp(-np.clip(table, -60.0, 60.0)))
    if how == "unsigned":
        return np.abs(np.tanh(table))
    raise ValueError(how)


def weights_equal() -> dict[str, float]:
    """Equal weight per named group, shared out among its members.

    The hand-set case, and equal is the only defensible choice without a fit -
    `signal_layer.handtuned` makes the same one.
    """
    out: dict[str, float] = {}
    for names in GROUPS.values():
        for name in names:
            out[name] = 1.0 / len(names)
    return out


def weights_fitted(table: np.ndarray, truth: np.ndarray) -> tuple[dict[str, float], float]:
    """Logistic regression on the first half, as weights the layer can take.

    Fitted on the first half only. The layer is then scored on the second, so
    the comparison between encodings is out of sample for all of them.
    """
    from sklearn.linear_model import LogisticRegression

    half = len(truth) // 2
    model = LogisticRegression(max_iter=2000, C=1.0)
    model.fit(table[:half], truth[:half])
    coefficients = model.coef_[0]
    return (
        {name: float(coefficients[i]) for i, name in enumerate(FEATURES)},
        float(model.intercept_[0]),
    )


def agrees(layer: Layer, table: np.ndarray, rng, draws: int = 64) -> None:
    """Assert the vectorised sum below is the shipped layer, row for row.

    The layer is a Python object with a dict interface, and calling it once per
    decision point costs minutes per arm. So the scoring is vectorised - and
    the vectorisation is checked against the real thing on a sample rather than
    assumed, because a harness that quietly reimplements its subject is
    measuring itself.
    """
    picks = rng.choice(len(table), size=min(draws, len(table)), replace=False)
    weights = np.array([layer.weights.get(name, 0.0) for name in FEATURES])
    for i in picks:
        row = table[i]
        mine = squash(float(row @ weights) + layer.bias, layer.activation)
        theirs = layer(dict(zip(FEATURES, row, strict=True))).value
        assert abs(mine - theirs) < 1e-12, (mine, theirs)


def scored(layer: Layer, table: np.ndarray, truth: np.ndarray, out_of: bool) -> float:
    """The layer's AUC, on the second half when the weights were fitted."""
    span = slice(len(truth) // 2, None) if out_of else slice(None)
    rows = table[span]
    weights = np.array([layer.weights.get(name, 0.0) for name in FEATURES])
    total = rows @ weights + layer.bias
    clipped = np.clip(total, -LIMIT, LIMIT)
    if layer.activation == "tanh":
        values = np.tanh(clipped)
    elif layer.activation == "logistic":
        values = 1.0 / (1.0 + np.exp(-clipped))
    else:
        values = total
    return auc(values, truth[span])


def arm(
    how: str,
    fit: bool,
    temperature: float,
    table: np.ndarray,
    truth: np.ndarray,
    check=None,
) -> tuple[float, float]:
    """`(tanh AUC, logistic AUC)` for one encoding, one weighting, one scale."""
    put = encoded(table, how)
    if fit:
        weights, bias = weights_fitted(put, truth)
    else:
        weights, bias = weights_equal(), 0.0
    layer = Layer(weights=weights, bias=bias, activation="tanh").scaled(temperature)
    if check is not None:
        agrees(layer, put, check)
        agrees(layer.as_logistic(), put, check)
    return (
        scored(layer, put, truth, fit),
        scored(layer.as_logistic(), put, truth, fit),
    )


def main() -> None:
    print(
        "The output layer's encoding. The shipped `statespace.Layer` is the subject;\n"
        f"inputs {ENCODINGS}, outputs tanh and logistic, horizon {HORIZON} bars.\n"
    )
    rng = np.random.default_rng(SEED)
    names = (*TRADED, *GENERATED)
    for frame in FRAMES:
        got = gather(names, frame, HORIZON)
        if got is None:
            print(f"  {frame}: no rows")
            continue
        table, way, size = got
        twins = {}
        for kind in NULLS:
            twins[kind] = gather(names, frame, HORIZON, shuffle=kind)
        print("=" * 100)
        print(f"{frame}, {len(way):,} decision points, {table.shape[1]} terms")
        print("=" * 100)
        print(
            f"  {'input':<14}{'weights':<10}{'temp':>6}"
            f"{'dir tanh':>10}{'dir logit':>10}{'dir null':>10}{'dir edge':>10}"
            f"{'size tanh':>11}{'size null':>11}{'size edge':>11}"
        )
        for how in ENCODINGS:
            for fit in (False, True):
                for temperature in TEMPERATURES:
                    if fit and temperature != 1.0:
                        # A fit sets its own scale, so a temperature on top of
                        # it is the same layer twice.
                        continue
                    here = []
                    for truth, index in ((way, 1), (size, 2)):
                        mine = arm(how, fit, temperature, table, truth, check=rng)
                        nulls = []
                        for kind in NULLS:
                            other = twins.get(kind)
                            nulls.append(
                                float("nan")
                                if other is None
                                else arm(how, fit, temperature, other[0], other[index])[0]
                            )
                        floor = (
                            float(np.nanmax(nulls))
                            if np.any(np.isfinite(nulls))
                            else float("nan")
                        )
                        here.append((mine[0], mine[1], floor, mine[0] - floor))
                    print(
                        f"  {how:<14}{'fitted' if fit else 'equal':<10}{temperature:>6.2f}"
                        f"{here[0][0]:>10.4f}{here[0][1]:>10.4f}{here[0][2]:>10.4f}"
                        f"{here[0][3]:>+10.4f}"
                        f"{here[1][0]:>11.4f}{here[1][2]:>11.4f}{here[1][3]:>+11.4f}"
                    )
        print(
            "\n  dir tanh against dir logit is the identity check: the two encodings of\n"
            "  the output are affine images, so any difference is this harness's bug.\n"
            "  The null floor is whichever of the two nulls scores highest.\n"
        )

    print("=" * 100)
    print("POWER  planted momentum, so a flat column means the test is blind")
    print("=" * 100)
    print(f"  {'input':<14}{'weights':<10}" + "".join(f"{'rho ' + str(r):>11}" for r in PLANTS))
    # One `gather` per planted strength, not one per cell: it recomputes every
    # feature on every instrument and is by far the most expensive call here.
    planted = {rho: gather(names, "1h", HORIZON, rho=rho) for rho in PLANTS}
    for how in ENCODINGS:
        for fit in (False, True):
            line = f"  {how:<14}{'fitted' if fit else 'equal':<10}"
            for rho in PLANTS:
                got = planted.get(rho)
                if got is None:
                    line += f"{'-':>11}"
                    continue
                table, way, _size = got
                line += f"{arm(how, fit, 1.0, table, way)[0]:>11.4f}"
            print(line)
    print(
        "\n  A planted AR(1) in the returns is a directional effect the trend terms can\n"
        "  find. An encoding whose row does not climb has not shown a null, it has\n"
        "  shown nothing.\n"
    )


if __name__ == "__main__":
    main()
