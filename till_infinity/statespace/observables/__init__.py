"""What the service reads off a market, before any model is asked about it.

**A member consumes a pivot; it does not define one.** Everything here answers
"what *is* this, as a number" for some feature of price - a reversal, a
displacement, a range, a level's effect - so that the question a filter asks
can be about the dynamics rather than about the vocabulary.

Keeping them apart from `filters/` is what lets a null be built on the same
detector as the claim, which is the rule
`null-structure-claims-on-the-same-detector` states: walk through the *same*
detector with the *same* bar geometry, test both sides, sweep the reach.

## The entries

| module | what it measures |
| --- | --- |
| `behaving` | what each market class measurably **is**, as a table the library looks up |
| `displacements` | the sequence of moves between reversal points, as an observation process |
| `pivoting` | pivots by directional change: scale-free, alternating, checkable against a law |
| `shaping` | shapes as an enumerated candidate family, not as a chart vocabulary |
| `ranging` | a range the current price sits inside, with liquidity-aware edges |
| `interacting` | what a level has done to price, as posteriors rather than as ratios |
| `depths` | turn depth, as a dispersion quantity |
| `noticing` | transitions on the dispersion reading, and the line that explains one |
| `transitions` | which state follows which, with what probability and what expected time |

## The trap every module here is written against

**A bar-derived observable cannot be used to build its own null.**
`rehung-bar-shapes-break-bar-derived-nulls` is the finding: re-hanging bar
shapes invalidates stops, forecasts and gaps, so the null has to be built from
the path. And `let-the-shuffled-twin-name-the-mechanical-observables` is the
other half - overshoot at an extreme is **definitional**, so a detector that
reports it has reported arithmetic rather than structure.
"""

from __future__ import annotations
