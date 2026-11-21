"""The mechanics every member shares: `Q`, the input channel, time, the band.

**This is the folder that keeps the family a fair contest.** A member in
`filters/` is a candidate measured against the others on the same data, and
that only means something if the things around it are held constant. If
`ornstein` carried its own idea of where `Q` comes from and `landau` carried
another, a comparison between them would be a comparison of two changes at
once and neither result would be attributable.

So anything here is **subject-agnostic and member-agnostic on purpose**: it
answers a question about the filter's plumbing rather than about a market.

## The entries

| module | the question it answers |
| --- | --- |
| `inputs` | `B` and `u`: what drives the state from outside, every window in **time** |
| `driven` | the other door the exogenous channel can come through - `Q`, not `B u` |
| `spanning` | `Q` from the bar's **range** rather than from its closes |
| `pacing` | activity as the second door onto `Q`: how far, driven by how busy |
| `rates` | a rate is per unit time and a bar is not a unit of time (I6) |
| `adapting` | error feedback on the filter's own noise - online learning |
| `smoothing` | where the quantity really was, given everything that happened next |
| `tails` | how wide a band must be once the residuals are known not to be Gaussian |
| `bounding` | two barriers from one model instead of three (I7) |
| `yielding` | stop asserting continuity where the evidence says there isn't any |
| `anchored` | an anchored fair value, and the distance from it in band units |
| `spectrum` | what a member's eigenvalues say, **in hours** |

## Why `Q` has four modules and that is not duplication

`spanning`, `pacing` and `driven` are three different *doors* onto the same
quantity, and `seasonality-belongs-on-q` is why they are separated rather than
merged: the intraday pattern belongs on `Q` and never on `R`, and a module that
blurred which door a multiplier came through would make that impossible to
check. `q-multipliers-need-mean-one` is the constraint they share - a
multiplier whose mean is not 1 moves the average as well as the shape.
"""

from __future__ import annotations
