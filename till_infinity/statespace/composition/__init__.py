"""More than one of something: many members, many instruments, many subjects.

Everything in `filters/` models **one** quantity with **one** member. This
folder is what happens when that is not enough - and in every case the
composition is a measured choice rather than an averaging convenience.

## The entries

| module | what it combines |
| --- | --- |
| `pooling` | several members on one subject, combined by **precision to a power** |
| `cohort` | cross-sectional pooling: the members of one cohort, oriented and combined |
| `panel` | many instruments at once - the vector observation the family lacked |
| `paired` | a filter member watched by the FOCuS detector that was already here |
| `subjects` | one model, three subjects: a level, an instrument, a relationship |
| `ranking` | predict the **order** across subjects, then map the order to the value |

## Why composition is not free

`the-book-is-composable-judge-rules-marginally` is the rule this folder is
judged by: **composition buys variance and conditioning, never expectancy.**
Combining two members cannot manufacture an edge neither has; what it can do is
make the estimate steadier, which is a different and smaller claim.

Two measured constraints shape how it is done here. `pooled-medians-invert-
subgroups` - a pooled answer agreed with a claim that every subgroup refuted,
so `cohort` orients its members before combining rather than after. And
`the-noise-argument-is-a-variance` - two members squared it, invisible within
one member and enough to reverse a cross-member study, which is why `pooling`
weights by precision to a power rather than equally.
"""

from __future__ import annotations
