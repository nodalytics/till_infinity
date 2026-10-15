# The barrier wall on traded instruments is 0.73, not 0.5826

**Measured 2026-10-15.** Code: [`barrier_traded.py`](../ideas/barrier_traded.py).
91 instrument-reach rows across 15m, 1h and 4h.

`statespace/bounding.py` converts between a target, a stop, a probability and a
horizon with two first-passage laws, both carrying an additive barrier wall `B`:

    P = (down + B) / (up + down + 2B)        T = (up + B) * (down + B)

`B` is `SHIFT = 0.5826`, the Broadie-Glasserman-Kou constant: a barrier watched
once a bar sits that much further away than one watched continuously, because
the walk can cross and come back inside the bar.

[`barrier-overshoot.md`](barrier-overshoot.md) earned measured replacements for
eight Deriv families. **It did not measure one traded instrument**, so
`shifts_for` returned the diffusion constant for every live feed on the desk -
a gap its own docstring is honest about, and this closes it.

## The level: a quarter too narrow

| group | reach 2 | reach 4 | reach 8 |
|---|---:|---:|---:|
| fx majors | 0.6814 | 0.7480 | 0.7824 |
| fx crosses | 0.6872 | 0.7494 | 0.9080 |
| **synthetic control** | **0.5851** | **0.5681** | **0.6106** |

Pooled over 64 traded instrument-reach rows, `B` is **0.7262** against the
control's **0.5850** - a gap of **+0.1412 at z +16.71**, or 3.8 control standard
deviations. The control recovering 0.5826 is the check that matters: an
estimator that cannot reproduce the constant it replaces has no business
replacing it.

## It grows with the barrier distance, which a constant cannot express

Traded `B` reads **0.6472, 0.7525 and 0.8619** at reaches of 2, 4 and 8 - a
straight line in `log2(reach)` with a slope of **+0.1074 per doubling** from
0.6465 at two sigmas. The control over the same reaches reads 0.5923, 0.5681
and 0.5954, which is flat, as a diffusion's asymptotic constant must be.

So `B` is not a constant on traded instruments, and `SHIFTS` - one tuple per
class - cannot carry that. `bounding.wall_at(feed, reach)` applies the growth
for a caller who knows the distance; `solve` keeps the pooled figure, because
its job is to find a missing barrier and the reach that sets the wall would be
the thing being solved for.

## The two directions differ, and skew orders them

Pooled log-ratio of the up wall to the down wall, against a noise floor taken
from the control's own spread:

| bucket | rows | mean log-ratio | z | ratio |
|---|---:|---:|---:|---:|
| skew < −0.5 | 24 | −0.2603 | **−11.70** | 0.771 |
| \|skew\| ≤ 0.5 | 29 | −0.1171 | **−5.78** | 0.889 |
| skew > +0.5 | 11 | −0.0373 | −1.14 | 0.963 |
| all traded | 64 | −0.1571 | **−11.53** | 0.855 |
| control | 27 | +0.0259 | — | 1.026 |

Monotone in skew, and the mechanism is the one `bounding` already documents for
the spiking synthetic families: a direction that arrives in larger jumps
overshoots its barrier further. The JPY pairs need it most - USDJPY at skew
−1.14 reads a ratio of 0.794 - and `EURGBP`, at a skew of +0.04, reads 1.008.
Correlation between skew and the log-ratio is +0.613 at reach 2, +0.589 at 4
and +0.456 at 8.

**Per-instrument asymmetry is not claimed, and the control is why.** Its own
ratio wanders from 0.741 to 1.229 on a symmetric process, so a single
instrument's reading is not individually reliable even where the pooled ordering
is certain at z −11.5. The table therefore carries class medians.

## The expected mechanism is refuted

Traded kurtosis runs **13.4 to 35.5** against the synthetics' 3.2, so fat tails
were the obvious explanation for a wider wall - a barrier crossed by a jump is
overshot by the size of the jump. Across instruments, the correlation between
kurtosis and `B` is **+0.113**. The level is up and kurtosis is not what orders
it. Worth recording as a failed explanation rather than quietly dropping, since
it was the reason the measurement was taken.

## Session gaps, which synthetics do not have

A weekend is one row in the cache and a large step in the diff, and a barrier
"crossed" there was never watched. Every path here runs inside a gap-free
segment. Leaving the gaps in inflates `B` further - EURUSD at reach 2 reads
0.7483 unsegmented against 0.6137 segmented - so segmentation is conservative
with respect to the finding, and the planted Gaussian walk recovers 0.5701 to
0.5946 through the segmented estimator, which is the check that segmentation is
harmless.

## What this does and does not change

`bounding` has **no production consumer** - only tests and cross-references from
other `statespace` docstrings - so nothing live moves. What changes is that the
module is now right for the instruments the desk trades, before anything reads
it.

The size of the old error, swept over barriers from 0.5 to 12 sigmas: replacing
0.5826 with 0.7262 lengthens every horizon, by 11.4% at two sigmas a side
falling to 3.4% at eight, and moves the probability by at most **0.0155**.
`T = u * d` is second order in the wall where `P = d / (u + d)` is a ratio, so
the horizon is the quantity the wall decides and the probability barely notices.
