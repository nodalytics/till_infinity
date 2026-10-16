# 0..1 or -1..+1 is an empty choice; keeping the sign is the whole of it

**Measured 2026-10-16.** Code: [`output_encoding.py`](../ideas/output_encoding.py).
The subject is the shipped
[`statespace.Layer`](../../till_infinity/structures/statespace/signalling.py),
scored on 403,171 decision points at 15m and 407,671 at 1h, eleven terms, both
targets, against two nulls and a planted power arm.

The request was an output layer for statespace - weigh the terms, add them, add
an optional bias and an activation, hand one signal to the rest of the system -
with the signal bounded either 0 to 1 or -1 to +1, "and we can test both and
see the one that comes out best".

## Half of it needs no measurement

    tanh(x) = 2 * logistic(2x) - 1

exactly, so a `tanh` layer at weights `w` and bias `b` and a `logistic` layer at
`2w` and `2b` are affine images of each other. They order every pair of inputs
identically. `Layer.as_logistic` performs that conversion and
`tests/test_statespace.py::TestOutputLayer` asserts it; the table below
re-confirms it on real data, where **`dir tanh` and `dir logit` agree to four
decimal places on all 24 arms**. Any difference would have been a bug in the
harness, not a property of the encoding.

## Two more things turn out to be identities, one of them against prediction

| input | weights | temp | dir AUC | dir logit | dir null | dir edge | size AUC | size null | size edge |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| raw | equal | 1.00 | 0.5005 | 0.5005 | 0.4998 | +0.0007 | 0.5351 | 0.5229 | +0.0122 |
| raw | equal | 0.25 | 0.5005 | 0.5005 | 0.4998 | +0.0007 | 0.5351 | 0.5229 | +0.0122 |
| raw | fitted | 1.00 | 0.5018 | 0.5018 | 0.5068 | −0.0049 | 0.5545 | 0.5539 | +0.0006 |
| signed | equal | 1.00 | 0.4996 | 0.4996 | 0.4989 | +0.0007 | 0.5338 | 0.5205 | +0.0133 |
| signed | fitted | 1.00 | 0.5022 | 0.5022 | 0.5070 | −0.0048 | 0.5536 | 0.5508 | +0.0027 |
| probability | equal | 1.00 | 0.5002 | 0.5002 | 0.4994 | +0.0008 | 0.5351 | 0.5217 | +0.0134 |
| probability | fitted | 1.00 | 0.5022 | 0.5022 | 0.5072 | −0.0049 | 0.5539 | 0.5534 | +0.0005 |
| **unsigned** | equal | 1.00 | 0.5011 | 0.5011 | 0.5026 | −0.0016 | 0.5087 | 0.5053 | +0.0034 |
| **unsigned** | fitted | 1.00 | 0.4995 | 0.4995 | 0.5026 | −0.0031 | 0.5238 | 0.5235 | +0.0003 |

15m. `raw` is the standardised term, `signed` is `tanh(z)`, `probability` is
`logistic(z)`, `unsigned` is `abs(tanh(z))`.

**The temperature is an identity too.** Every `temp 0.25` row equals its
`temp 1.00` row to four decimals, because a positive scale factor cannot
reorder a weighted sum and AUC reads only the order. It still changes the
*value*, so it matters to a consumer that thresholds `strength` at a fixed
number - and not to anything that ranks.

**`probability` matches `signed` everywhere, which was predicted to happen only
under fitted weights.** The registered reasoning was that a per-term offset
would land in the sum when the weights were hand-set and be absorbed when they
were fitted. That was wrong: `logistic(z) = (tanh(z/2) + 1) / 2`, so the two
differ by a temperature and a **constant**, and a constant shift of every row's
total is as invisible to a rank statistic as the scale is. A hand-set bias has
nothing to absorb because there is nothing row-dependent to absorb.

So three of the four things one might change about an output layer - the
activation, the scale, a constant offset - cannot move a ranking at all.

## The one thing that can matter, and it is decisive

Planted momentum, an AR(1) in the returns, which the trend terms can find:

| input | weights | rho 0.0 | rho 0.05 | rho 0.15 | rho 0.30 |
|---|---|---:|---:|---:|---:|
| raw | fitted | 0.5040 | 0.5050 | 0.5111 | **0.5268** |
| signed | fitted | 0.5032 | 0.5037 | 0.5090 | **0.5245** |
| probability | fitted | 0.5038 | 0.5042 | 0.5110 | **0.5272** |
| **unsigned** | equal | 0.5060 | 0.5059 | 0.5059 | **0.5060** |
| **unsigned** | fitted | 0.4993 | 0.4990 | 0.4990 | **0.4984** |

Every sign-preserving encoding climbs to 0.525-0.527 at the strongest plant.
**The sign-destroying one is flat to four decimals at every strength**, and its
fitted arm drifts the wrong way. An encoding that keeps only a term's magnitude
is not weak on direction, it is **blind** to it by construction, and the power
arm is what makes that a measurement instead of an argument.

That is the entire content of the 0..1 versus -1..+1 question. Both intervals
can carry the sign - `logistic` puts neutral at 0.5 and above-or-below is the
side - and either is fine if it does. What cannot be undone is folding the sign
away before the sum.

## The direction is still a coin

`dir edge` is −0.0050 to +0.0008 on every arm of both frames.
[`signal-layer.md`](signal-layer.md) measured that on this feature set already;
this is 810,842 fresh decision points saying it again, and it is the reason the
production module's docstring opens by disclaiming prediction. Fitting makes it
slightly worse out of sample (−0.0048 to −0.0049 against +0.0007 hand-set),
which is `fit-on-the-edge-not-the-raw-score` once more: the fitted arms win on
raw AUC, 0.5018-0.5022 against 0.4996-0.5005, and lose on edge.

## Magnitude is frame-dependent, so nothing is claimed for it

At 15m the sign-preserving encodings carry +0.0122 to +0.0134 of edge on
"is the next move bigger than usual", and fitting destroys it - +0.0005 to
+0.0027. At 1h every sign-preserving arm is **negative**, −0.0113 to −0.0196,
and the only positive reading in the whole frame is `unsigned fitted` at
+0.0046.

The registered prediction was that `unsigned` would be the best encoding for
magnitude. It is at 1h and it is not at 15m, where it is the worst of the four.
A result that swaps sign between two frames of the same instruments is not a
result, so the second half of that prediction is **withdrawn rather than
confirmed**, and a magnitude layer is not recommended on this evidence.

## What the layer should therefore be

- **`tanh`, -1..+1, as the default.** Not because it measures better - it
  cannot - but because neutral at zero makes the sign the side, the desk
  already does `Side.sign` arithmetic everywhere, and a deadband is symmetric.
  `Signal.strength` returns the same number under either encoding so a consumer
  never has to know which it was handed.
- **Every term signed.** This is the only rule here with a measurement behind
  it.
- **No temperature unless a consumer reads `strength` against a fixed
  threshold.** `Layer.scaled` exists for that case and for `t`-statistic terms,
  where `tanh(3) = 0.995` leaves four terms at `t = 3` indistinguishable from
  four at `t = 10`; it is a no-op for anything that ranks.
- **Nothing wired to it yet.** The layer composes terms that are each measured
  elsewhere and the direction is closed, so a consumer would be acting on a
  coin. It is a place to put the arithmetic once, with per-term contributions
  visible, for the day a term with an edge turns up.

## A note on the harness

Calling a Python object once per decision point costs minutes per arm, so the
scoring is vectorised - and `agrees` checks the vectorised sum against the real
`Layer`, row for row, on a sample of each arm. A harness that quietly
reimplements its subject is measuring itself.
