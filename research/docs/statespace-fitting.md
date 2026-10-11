# Fitting the members, and the two mistakes that nearly made it a result

`statespace-new-members-measured.md` scored every member on real instruments
and the random walk won nearly everywhere - with a caveat written at the time
that none of them was fitted, and that a member with five states at a default
noise is "shown unusable as shipped, which is a different and much smaller
claim".

This is that caveat cashed in. Harness: `research/ideas/fitted_members.py`.
Each member's own parameters are chosen by maximum likelihood on the
**training** period by coordinate ascent, then scored on the back of the
series. Same split, same readings.

It took three runs to get an answer, and the two wrong ones are the useful
part.

## Run one: fitting transforms every member, and the walk is crushed

| eurusd | default | fitted | gain |
|---|---|---|---|
| linear | -89,846 | -12,616 | **+77,231** |
| reverting | -121,764 | -48,107 | +73,657 |
| fractional | -143,385 | **-6,861** | **+136,524** |
| switching | -22,017 | -22,094 | -77 |

Against a walk at **-21,401**, fitted `fractional` wins by 14,540 and fitted
`linear` by 8,785. The long-memory member goes from worst by a wide margin to
best by a wide margin, purely on its parameters.

**That reading was wrong, and two things were wrong with it.**

## Mistake one: the null was not fitted

Every member got a parameter search and the walk got `noise = 0.4`, asserted.
That is not a comparison. The walk has exactly one parameter and it gets the
same treatment:

| | walk at 0.4 | **walk fitted** | gain to the null |
|---|---|---|---|
| eurusd | -21,401 | **-6,838** (noise 2.28) | +14,563 |
| xauusd | -13,528 | **-6,043** (noise 1.34) | +7,485 |
| gbpusd | -21,844 | **-6,829** (noise 2.14) | +15,015 |
| btcusd | -16,629 | **-6,450** (noise 2.08) | +10,179 |
| usdjpy | -8,024 | **-5,067** (noise 1.18) | +2,957 |

**Fitting the null gained it more than fitting most members gained them.**

## Mistake two: three parameters were pinned at the edge of their brackets

`jerk` came back at 0.987 against a ceiling of 1.0, `theta` at 0.0101 against
a floor of 0.01, `slowest` at 986 of 1000. A parameter at the edge of its grid
is a grid, not a fit - and this package has the scar already: every
`selective` and `swarm` fit pinned `drift` at the top of its grid, and the
limit of that family turned out to be the random walk. The harness now widens
the brackets and prints a `!` beside any parameter still at an edge.

## The answer, with both fixed

| | walk (fitted) | fractional | linear | reverting | switching |
|---|---|---|---|---|---|
| eurusd | **-6,838** | -6,846 | -10,647 | -48,074 | -22,029 |
| xauusd | **-6,043** | -6,085 | -9,400 | -29,891 | -13,142 |
| gbpusd | **-6,829** | **-6,829** | -10,649 | -47,349 | -21,603 |
| usdjpy | -5,067 | **-5,151** | -7,510 | -17,188 | -7,718 |
| btcusd | **-6,450** | -6,475 | -9,870 | -35,930 | -17,142 |

**Fitted, `fractional` ties the random walk and nothing beats it.** The
margins are 8, 42, 0, 84 and 25 nats over thousands of readings - which is a
tie, not a win in either direction.

And the reason it ties is visible in its own parameters: **`slowest` pins at
the top of every bracket it is given** - 9,870 hours, which is 411 days, so
its slowest mode never decays over an 8,000-hour sample. A mode that never
decays is a random walk. `linear` does the same thing from the other side with
`jerk` at 48.9 and 72.2, which is exactly what `nulls.Walk`'s own docstring
predicts: *"as `drift` grows, retention goes to zero and every state collapses
onto the current reading - so the limit of that family is exactly 'the next
value equals this one'."*

So the members do not tie the walk by matching it. **They tie it by becoming
it.**

## What survives

* **`switching` is the only member whose defaults were nearly right.** Its
  fitting gain is -12 to +1,240 against five-figure gains elsewhere, because
  its parameters are durations in hours and the asserted 24h/4h were close to
  what the data wanted (1 to 2.8 hours for balance, 20 to 42 for imbalance -
  **the opposite ordering to the one asserted**, which is a finding in itself:
  the data says imbalance is the persistent state).
* **`reverting` loses badly even fitted**, by a factor of five to seven, with
  `theta` pinning toward zero - which is the same collapse again, a reversion
  rate going to zero being a random walk, except that it cannot get there from
  below as fast as the others get there from above.
* **The earlier "the walk wins" result stands**, but for a different reason
  than it appeared to. It is not that the members are badly parameterised; it
  is that the best they can do, fitted, is reproduce the null.

## The methodological point, which is the durable part

Three runs produced three different headlines - *the walk crushes everything*,
*fitting makes everything beat the walk*, *fitted members tie the walk by
degenerating into it* - from the same code and the same data. What changed was
whether the **null got the same treatment as the hypothesis**, and whether the
search was allowed to reach its own optimum.

A fitted model against an asserted null is not a comparison, and it is an easy
one to publish by accident.

---

## Every member, fitted, becomes the random walk

`oscillator.py` was added after the first version of this document - a damped
harmonic oscillator, `phi'' + gamma phi' + omega^2 phi = noise`, which is the
one member in the family that *can* cycle, because underdamped its eigenvalues
are complex. Unfitted it is catastrophic (-1,310,685 on eurusd, the worst
number this desk has produced). Fitted it reaches **-6,936** against a walk at
**-6,838**.

So it ties too. And its fitted parameters say why, in the same voice as the
others:

| member | fitted parameter | what that value means |
|---|---|---|
| `fractional` | `slowest = 9,870h` (pinned) | the slowest mode never decays over the sample |
| `linear` | `jerk = 48.9` to `72.2` | retention goes to zero, the state collapses onto the reading |
| `oscillator` | `omega = 0.009`, `gamma = 1.21` | `zeta = 67` - massively overdamped, no restoring force |
| `reverting` | `theta = 0.0016` | the reversion rate goes to zero |

**A mode that never decays, a retention that collapses, a restoring force sent
to zero and a reversion rate sent to zero are the same thing said four ways.**
Each member reaches the random walk from whichever direction its own
parameterisation allows, and then stops, because that is where the likelihood
is maximised.

That is a stronger statement than "the walk wins". It says the optimum of this
family's likelihood surface **is** the walk, and the members are
parameterisations of a neighbourhood around it. `nulls.Walk`'s docstring
guessed exactly this for one member -

> as `drift` grows, retention goes to zero and every state collapses onto the
> current reading - so the limit of that family is exactly "the next value
> equals this one"

\- and fitting four members found it is true of all of them.

**What would falsify it**, and is the next thing worth running: a member whose
degenerate limit is *not* a walk. `switching` is the candidate, because its
extra structure is a discrete regime rather than a continuous rate, and it is
the only member here whose fitted parameters did **not** run to an edge - its
durations came back interior, at 1 to 2.8 hours for balance and 20 to 42 for
imbalance. A model that cannot collapse into the null by turning one knob is
the only kind that can beat it.
