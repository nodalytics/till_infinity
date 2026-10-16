"""The output layer: weigh the terms, add a bias, squash, and say what it did.

Asked for on 2026-10-16 - "feed everything into the signal function with
weights, then `y` will be the signal", bounded either 0 to 1 or -1 to +1, and
"optionally add a bias and an activation function and give the final signals to
be used by the other parts of the system".

This is that layer and **only** that layer. It composes; it does not measure.
Every term it weighs is measured somewhere else and the measurements are not
flattering, which is exactly why the composition belongs in one audited place:

- `research/docs/signal-layer.md` fitted this sum eleven terms wide and found
  **direction is a coin**. Tick volume velocity carried +0.026 to +0.055 of
  edge and the volatility term was mechanical - it reads a quantity the outcome
  is defined against.
- `prod-probability-up-needs-halving`: the 0.6365 that `probability_up` once
  reported was overlapping touches, and de-overlapped it is 0.5092.
- `fit-on-the-edge-not-the-raw-score`: fitted weights beat hand-tuned ones on
  AUC, 0.604 against 0.556, and **lost** on edge, +0.002 against +0.019.

So nothing here claims a direction is predictable. What it claims is that if
several readings are going to be added up and acted on, the sum should be
written once, with its per-term contributions visible and its bounds known.

## The two encodings are the same function

The question was which of 0..1 and -1..+1 "comes out best", so here is the
answer before any measurement: they are the same, because

    tanh(x) = 2 * logistic(2x) - 1

exactly. A `tanh` layer at weights `w` and bias `b` and a `logistic` layer at
`2w` and `2b` produce values that are affine images of each other, so they
order every pair of inputs identically, every AUC is identical to floating
point, and any threshold on one maps to a threshold on the other.
`Layer.as_logistic` and `Layer.as_tanh` perform that conversion and
`tests/test_statespace.py` asserts the identity rather than describing it.

What differs is **ergonomics**, and that is a real choice rather than a
measurable one:

- `-1..+1` puts "no opinion" at zero, so the sign is the side and the magnitude
  is the conviction. The desk already does `Side.sign` arithmetic everywhere,
  and a deadband is symmetric by construction.
- `0..1` puts "no opinion" at 0.5 and reads like a probability, which this one
  is **not**: it is a squashed weighted sum with no calibration behind it, and
  the desk has already shipped one number that was read as a probability and
  was not (`probability_up`).

`tanh` is therefore the default. `Signal.strength` is computed the same way
under either, so a consumer never has to know which was used.

## Missing terms are recorded, not silently zeroed

A term that is absent contributes nothing, which is the right neutral for a
**signed** term and the wrong one for an unsigned term whose own neutral is
0.5 or 1. The layer cannot know which it was handed, so it names what was
missing in `Signal.missing` and leaves the judgement to the caller. A consumer
that acts on a signal built from half its terms should be able to see that it
did.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field

#: The activations this layer offers, and the interval each one lands in.
BOUNDS: dict[str, tuple[float, float]] = {
    "identity": (-math.inf, math.inf),
    "tanh": (-1.0, 1.0),
    "logistic": (0.0, 1.0),
}
#: Where "no opinion" sits under each activation.
NEUTRAL: dict[str, float] = {"identity": 0.0, "tanh": 0.0, "logistic": 0.5}
#: The largest total passed to an exponential, so a saturated layer returns a
#: bound rather than an overflow warning and a nan.
LIMIT = 60.0


def squash(total: float, activation: str) -> float:
    """One activation, by name, saturating rather than overflowing."""
    if activation == "identity":
        return float(total)
    clipped = max(-LIMIT, min(LIMIT, float(total)))
    if activation == "tanh":
        return math.tanh(clipped)
    if activation == "logistic":
        return 1.0 / (1.0 + math.exp(-clipped))
    raise ValueError(f"unknown activation {activation!r}")


def terms_from(readout, *, reference_spread: float = 0.0) -> dict[str, float]:
    """The terms a `facade.Readout` can offer a layer, and only those.

    Two, by default, and the shortness of the list is the point.

    * **`surprise`** - the standardised one-step innovation. Signed,
      scale-free, and the one quantity here that is genuinely statespace's own
      reading of the bar. Taken from the field rather than reconstructed:
      `(price - readout.value) / readout.spread` is a **post-update** residual
      against a **next-step** spread, attenuated by an unknown amount.
    * **`pace`** - `pace_factor - 1.0`, so an inert pacing mechanism
      contributes exactly nothing rather than contributing one.

    **What is deliberately not here.** `walls`, `family` and `absorbs` are
    constant for a feed - `shifts_for` and `traits_for` are lookups by class -
    so each would enter a weighted sum as the same number on every bar. That is
    a **bias wearing a term's name**: it shifts every signal for that feed
    equally, changes no ordering, and makes the bias look as though it had been
    measured. Put them in the weights, in the choice of layer, or in a gate -
    not in the sum.

    `spread` and `seen` do vary, and neither is scale-free on its own: a spread
    is in the instrument's units and `seen` only grows. `spread` is offered
    against a `reference_spread` the caller supplies - its own trailing median,
    typically - as `spread / reference - 1.0`, and left out entirely when no
    reference is given, because dividing by the wrong thing silently is worse
    than not offering the term at all.
    """
    terms = {
        "surprise": float(readout.surprise),
        "pace": float(readout.pace_factor) - 1.0,
    }
    if reference_spread > 0:
        terms["spread"] = float(readout.spread) / float(reference_spread) - 1.0
    return terms


@dataclass(frozen=True, slots=True)
class Signal:
    """One output, with the arithmetic that produced it kept alongside it."""

    value: float
    total: float
    activation: str
    contributions: tuple[tuple[str, float], ...] = ()
    missing: tuple[str, ...] = ()

    @property
    def neutral(self) -> float:
        """The value that means "no opinion" under this activation."""
        return NEUTRAL[self.activation]

    @property
    def side(self) -> int:
        """+1, -1, or 0 when the signal sits exactly at its neutral point.

        A deadband belongs to the layer and not here, because the width of
        "no opinion" is a decision about the signal and not about arithmetic.
        """
        if self.value > self.neutral:
            return 1
        if self.value < self.neutral:
            return -1
        return 0

    @property
    def strength(self) -> float:
        """Conviction in 0..1, the same number under either bounded encoding.

        For `tanh` that is `abs(value)`; for `logistic` it is the distance from
        0.5 doubled, which is the image of the same quantity. A consumer can
        therefore read `strength` without knowing which encoding it was handed,
        and that is the whole reason it exists.
        """
        if self.activation == "identity":
            return abs(self.value)
        low, high = BOUNDS[self.activation]
        half = (high - low) / 2.0
        return min(1.0, abs(self.value - self.neutral) / half)

    @property
    def leading(self) -> tuple[str, float] | None:
        """The term that moved the sum most, by absolute contribution."""
        return self.contributions[0] if self.contributions else None


@dataclass(frozen=True, slots=True)
class Layer:
    """Weights, a bias, and an activation. The whole output layer.

    `weights` names the terms this layer consumes; anything else in the mapping
    handed to `__call__` is ignored, so adding a term to an upstream reader
    cannot change a signal until the weight is added here too.
    """

    weights: Mapping[str, float] = field(default_factory=dict)
    bias: float = 0.0
    activation: str = "tanh"
    #: Inside this much of neutral, `settled` reports no side. In `strength`
    #: units, so it means the same thing under either encoding.
    deadband: float = 0.0

    def __post_init__(self) -> None:
        if self.activation not in BOUNDS:
            raise ValueError(f"unknown activation {self.activation!r}")
        if not 0.0 <= self.deadband < 1.0:
            raise ValueError(f"deadband {self.deadband} is outside 0..1")

    def __call__(self, terms: Mapping[str, float]) -> Signal:
        """Weigh, add, squash. Terms that are absent or `nan` are recorded."""
        total = float(self.bias)
        parts: list[tuple[str, float]] = []
        absent: list[str] = []
        for name, weight in self.weights.items():
            if name not in terms:
                absent.append(name)
                continue
            value = float(terms[name])
            if math.isnan(value):
                absent.append(name)
                continue
            share = float(weight) * value
            total += share
            parts.append((name, share))
        parts.sort(key=lambda pair: -abs(pair[1]))
        return Signal(
            value=squash(total, self.activation),
            total=total,
            activation=self.activation,
            contributions=tuple(parts),
            missing=tuple(absent),
        )

    def settled(self, terms: Mapping[str, float]) -> int:
        """The side this layer would take, or 0 inside the deadband."""
        got = self(terms)
        return 0 if got.strength <= self.deadband else got.side

    def as_logistic(self) -> Layer:
        """The same layer in 0..1, by `tanh(x) = 2 logistic(2x) - 1`.

        Doubling the weights and the bias is the whole conversion. The returned
        layer's value is `(this layer's value + 1) / 2` on every input, which
        is asserted in the tests, so the two encodings are one layer and not a
        choice with consequences.
        """
        if self.activation == "logistic":
            return self
        if self.activation != "tanh":
            raise ValueError(f"no logistic twin for {self.activation!r}")
        return Layer(
            weights={name: 2.0 * weight for name, weight in self.weights.items()},
            bias=2.0 * self.bias,
            activation="logistic",
            deadband=self.deadband,
        )

    def as_tanh(self) -> Layer:
        """The same layer in -1..+1, halving what `as_logistic` doubled."""
        if self.activation == "tanh":
            return self
        if self.activation != "logistic":
            raise ValueError(f"no tanh twin for {self.activation!r}")
        return Layer(
            weights={name: 0.5 * weight for name, weight in self.weights.items()},
            bias=0.5 * self.bias,
            activation="tanh",
            deadband=self.deadband,
        )

    def scaled(self, factor: float) -> Layer:
        """Every weight and the bias times `factor`, the activation kept.

        A temperature, in other words: it cannot change the order of two
        signals, only how hard the activation saturates. Useful for turning a
        layer whose terms are `t`-statistics - which reach 3 and more, where
        `tanh` is already flat - into one that uses its range.
        """
        return Layer(
            weights={name: factor * weight for name, weight in self.weights.items()},
            bias=factor * self.bias,
            activation=self.activation,
            deadband=self.deadband,
        )
