# Persistent homology finds levels, ranges and shapes, and every one of them is something a ruler already had

Three questions, asked on 2026-10-14 while `level-signatures.md` was closing: *also
try topological data analysis, betti numbers, etc*; *we are also looking for tiny
signals in TDA and also can TDA be used to extract levels too*; *also check for
shapes over time and what happened before and after each shape*.

All three are answered, each with a positive control and each with its confound
named rather than argued away. None of them survives.

## Why topology is a reasonable thing to ask for

A price level, stated carefully, is a mode of the measure that says how much
trading happened where - and a volume profile's answer to that depends on its bin
width. The **prominence** of a mode, how far the density must fall before it
merges into a taller one, is its persistence under the superlevel filtration, and
persistence is stable under perturbation. So the bandwidth stops deciding which
levels exist and only decides how fine a mode may be. That is a real improvement
in construction, independent of whether it pays.

A range is a **loop**: embedded as `(price_t, price_{t+k})`, a range-bound stretch
goes out to one boundary, back to the other, and round again, while a trend does
not close. So the longest-lived `H1` class is a range score with an unambiguous
positive control, because Deriv publishes processes whose generator *has* a range
that breaks.

`research/ideas/topology.py` implements both. The prominence sweep is the elder
rule over a 1-D function - exact, no library - and is unit-tested against
hand-computed prominences, including that a flat function has one mode and a ramp
has one mode at the top. The homology is `ripser`.

## The four arms

| arm | what it is | what it must do |
| --- | --- | --- |
| control | `Range_Break_100`, `Range_Break_200` | has a range by construction |
| regime | `Drift_Switch_Index_10/20/30` | has a planted drift and no range |
| traded | twelve FX and metals | the question |
| generated | six volatility and step indices | driftless, no levels |

## Levels from topological prominence

Each window's visitation density is built by spreading every bar's volume across
its own range, smoothed, and its three most prominent modes are nominated as
levels. Each nomination is raced against a distance-matched placebo: does price
come back one typical bar before it goes through one?

| | control | regime | traded | generated |
| --- | ---: | ---: | ---: | ---: |
| nominations | 318 | 371 | 2,181 | 628 |
| hold at a prominent mode | 0.2637 | 0.4429 | 0.4973 | 0.4858 |
| hold at a matched price | 0.2671 | 0.4456 | 0.4960 | 0.4834 |
| paired difference | +0.0016 | -0.0045 | -0.0017 | +0.0008 |
| p | 0.833 | 0.603 | 0.621 | 0.893 |
| prominent half | +0.0042 | -0.0034 | -0.0008 | -0.0068 |
| less prominent half | -0.0010 | -0.0057 | -0.0025 | +0.0083 |

Nothing, anywhere, including where the level is in the generator. And the deep
modes do not beat the shallow ones, which is the specific claim persistence was
making: if prominence does not order them, persistence added nothing to a
histogram.

One arm did look alive. `dispersion.differ` - the estimator merged in #223 - said
the control's nominated modes **genuinely differ from each other**, `tau` 0.0862
against a simulated null of 0.0080, p 0.002, where traded gave p 0.406 and the
driftless indices gave exactly zero. A per-unit statistic with real dispersion is
worth an estimator, so the obvious next step was a better selector.

It is not. The same question asked of the **placebos** on the same process
returns `tau` **0.0965**, p 0.002 - more dispersion than the modes have. The
spread belongs to the process, which spends part of its life in a range and part
breaking out of one, and any price measured during it inherits that. Asking the
placebo was the whole discipline of `statespace-conditional-holds.md` and it
earns its place again here.

## Ranges from one-dimensional homology

The outcome is scale-free: did the next hundred bars' range come in no wider than
this window's?

| | control | regime | traded | generated |
| --- | ---: | ---: | ---: | ---: |
| windows | 198 | 198 | 1,188 | 449 |
| `H1` score, unmatched | 0.3468 | 0.3247 | 0.3307 | 0.2791 |
| **window width, no topology** | **0.8029** | **0.8433** | **0.7387** | **0.8241** |
| `H1` within 5 width strata | 0.4867 | 0.4772 | 0.4418, p 0.002 | 0.4593 |
| `H1` within 10 | 0.4830 | 0.5391 | 0.4530, p 0.007 | 0.4843 |
| `H1` within 20 | 0.5345 | 0.5528 | 0.4601, p 0.027 | 0.4891 |
| `H1` within 40 | - | - | 0.4650, p 0.052 | 0.5209 |

The second row is the finding, and it is not topological: **how wide the window's
range already is** predicts whether the next one fits inside it at an AUC of 0.74
to 0.84. A ruler knew that.

The unmatched `H1` row reads 0.28 to 0.35 - strongly inverted - on every group
including driftless walks, which is the tell for a mechanical relationship rather
than a market one: a range-bound window has a narrow range and is therefore easy
to exceed. Matching on width is what turns it back into a question about shape.

Matched, traded reads 0.4418 at p 0.002, and then it **walks to 0.5 as the strata
narrow** - 0.4530, 0.4601, 0.4650, p 0.002 to 0.052 - which is precisely what
residual confounding looks like and precisely what the sweep was built to detect.
The controls do not move off 0.5 at all.

## Shapes over time, and what sits either side of each

Six shapes are fitted by k-means on the persistence descriptor of each window -
`H0` total and max, `b1`, `H1` total and max, and the `L1` norm of the first
persistence landscape, all computed on the delay embedding of returns
**standardised inside the window** so that no shape is a volatility reading in
disguise - plus the loop score. Fitted on the earlier half of each feed, read on
the later half.

Traded, 2,388 held-out windows:

| shape | n | vol before | move before | vol after | size after | drift after | held |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 240 | 1.099 | -0.021 | 1.136 | 0.955 | -0.051 | 0.067 |
| 1 | 558 | 1.078 | 0.134 | 1.035 | 0.784 | 0.024 | 0.113 |
| 2 | 290 | 0.846 | 0.076 | 0.846 | 0.684 | 0.123 | 0.162 |
| 3 | 539 | 1.026 | 0.027 | 1.053 | 0.834 | 0.053 | 0.130 |
| 4 | 341 | 1.130 | 0.112 | 1.114 | 0.802 | 0.143 | 0.126 |
| 5 | 420 | 1.093 | 0.186 | 1.119 | 0.910 | 0.006 | 0.114 |

The shapes are real: they separate what came before and what came after at
p 0.002. Shape 2 is the quiet one and stays quiet, shape 0 the loud one and gets
louder, and shape 2 is twice as likely as shape 0 to hold its range.

Then the line that matters - the same table scored against **six bins of plain
realised volatility**:

| outcome | `eta^2` shape | p | `eta^2` vol bins | p |
| --- | ---: | ---: | ---: | ---: |
| vol before | 0.0593 | 0.002 | **0.0684** | 0.002 |
| move before | 0.0046 | 0.037 | **0.0080** | 0.002 |
| vol after | 0.0469 | 0.002 | **0.0619** | 0.002 |
| size after | 0.0107 | 0.002 | **0.0118** | 0.002 |
| drift after | 0.0028 | 0.257 | 0.0026 | 0.244 |
| held | 0.0052 | 0.027 | **0.0106** | 0.002 |

A volatility bin beats the shape on **every single outcome**. The persistence
diagram of a standardised window is a volatility measurement that has been
through more machinery and arrives with less. On the controls the shapes are
mostly null while the volatility bins separate `vol before` and `vol after` at
`eta^2` of 0.08 to 0.20 - volatility clustering, which is the thing that is
always there.

And `drift after` is null for both, everywhere, which is the fourth independent
arrival at the same place: direction is closed.

## What is worth keeping

Not the arms - the two instruments they were tested with.

`dispersion.differ` was merged two hours before this and immediately did the job
it was written for: it found dispersion in the control's modes, which is exactly
when a desk starts building a selector, and the placebo column stopped it. It
cost one line.

The **strata sweep** is the other. An effect that survives matching at five bins
and walks toward the null at forty was never the thing being matched out, and
that pattern is readable in four numbers. It belongs in any harness here that
conditions on a confound rather than removing it.

## What should not be tried next

A finer frame, more instruments, a different embedding dimension or delay, or
`H2`. The level arm is null at 2,181 nominations with the placebo column
explaining its one positive reading; the range arm is a ruler; the shape arm
loses to a volatility bin on every outcome it wins on. None of those is a
precision problem.
