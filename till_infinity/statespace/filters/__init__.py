"""The family of filter members: the alternative models, one per file.

**This folder is a catalogue, and the thing it catalogues is a comparison.**
`family.members()` is the registry a `Subject` resolves through, so a member is
not "a file about a model" - it is a candidate that has been measured against
the others on the same data, and `family.py` records which has beaten which,
where. A file here is an entry in that contest.

## What belongs here

A module whose job is to *be* a member: it carries the state, the transition
and the update for one way of modelling a quantity, and it can be handed to
the registry. The nine the registry resolves today are `diagonal`, `landau`,
`linear`, `ornstein`, `reverting`, `robust`, `selective`, `swarm` and
`relating`; the rest are members in the same sense that are reached directly
rather than through the registry.

## What does not

* **The mechanics every member shares** - `Q` from the range or from activity,
  the input channel, the band width, the smoother. Those are one level up,
  because a member that owned its own copy would make the comparison a
  comparison of two things at once.
* **The evidence** - diagnostics, nulls, forward facts, the sweep. A member
  cannot grade itself.
* **The observables** - what a pivot or a displacement *is*. A member consumes
  those; it does not define them.

## The entries

| module | what it is |
| --- | --- |
| `family` | the registry, and the record of which member won where |
| `linear` | the linear-Gaussian baseline, continuous-time and subject-agnostic |
| `ornstein` | a **value** that reverts to a level - the member the family lacked |
| `reverting` | a **rate** that pulls back instead of running away (I3) |
| `landau` | a rate whose reversion stiffens with its own size - the Landau cubic |
| `oscillator` | a damped harmonic oscillator: the member that can actually cycle |
| `diagonal` | S4D-Real as a member in its own right, not another member's null |
| `fractional` | long memory from a sum of short memories |
| `selective` | the neural architectural family, as a member not a dependency |
| `swarm` | a particle ensemble over an anchored selective recurrence |
| `robust` | the same model, with an update that does not believe every measurement |
| `switching` | balance and imbalance as two regimes, transition fitted not drawn |
| `hmm` | direction as a discrete chain: the half of velocity that is a coin |
| `seasonal` | a seasonal phase-locked to the clock, not to the bar |
| `symmetry` | symmetry in the displacement sequence, as a switching model over it |
| `relating` | the hedge ratio as a state - what statistical arbitrage needed |

**Nothing is re-exported here on purpose.** `statespace/__init__.py` already
decides the package's public surface, and a second list in this file would be a
second thing to keep in step with the first. Import the module you want:
`from till_infinity.statespace.filters import linear`.
"""

from __future__ import annotations
