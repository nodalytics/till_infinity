# What statespace can feed its own output layer: two terms, and both are coins

**Measured 2026-10-16.** Code: [`surprise_edge.py`](../ideas/surprise_edge.py).
Ten instruments, 12,000 1h bars each, the filter's measurement noise swept
over three settings, three horizons, against a 96-bar block twin and against
two choices of base for the forward return.

[`output-encoding.md`](output-encoding.md) built the output layer and settled
how a signal should be encoded. It left the layer abstract: it takes any term
mapping. This asks what **statespace itself** can put in that mapping.

## A term that existed and was not published

`facade.Desk.read` computes the standardised one-step innovation on every bar -
`(value - prediction) / sqrt(predictive spread)` - and appends it to the
deque the empirical quantile band is built from. Until now it was not on the
`Readout`, so a caller wanting statespace's own reading of a bar had to
reconstruct it, and the obvious reconstruction is wrong twice over:

- `readout.value` is the state **after** the observation was folded in, so the
  residual has already been pulled toward the price it is measuring;
- `readout.spread` is documented as the spread of the **next** observation, not
  the one this bar was scored against.

Both errors shrink it. On a flat series at 100 with a single 0.5 step, the
innovation is **+21.16** and the naive reconstruction is **+12.28** - an
attenuation of **1.7x**, which reads as a weak signal rather than as a bug.
`Readout.surprise` now publishes it, and a test pins the ratio.

Also pinned: the **first** bar of a feed reports a surprise of 173 on a flat
series, because the prior sits at zero and the first observation is the whole
of the level. `Readout.warm` is already `False` there, so a caller that checks
it - as the field says to - never sees the cold-start value.

## Two terms, and the ones left out are the interesting part

`signalling.terms_from(readout)` offers `surprise` and `pace`
(`pace_factor - 1.0`, so an inert mechanism contributes nothing rather than
one). `spread` is offered only against a caller-supplied reference, since a
spread is in the instrument's units.

**`walls`, `family` and `absorbs` are deliberately not terms.** Each is a
lookup by market class, so each is the same number on every bar of a feed. In a
weighted sum that is a **bias wearing a term's name**: it shifts every signal
for that feed equally, changes no ordering, and looks as though it had been
measured. They belong in the weights, in the choice of layer, or in a gate.

## Both terms are coins

Median edge over the block twin, on the feeds where pacing is live:

| noise | h | surprise, base `t` | surprise, base `t+1` | artefact | pace |
|---:|---:|---:|---:|---:|---:|
| 0.25 | 1 | −0.0001 | −0.0008 | +0.0007 | +0.0015 |
| 0.25 | 3 | +0.0017 | −0.0012 | +0.0030 | +0.0005 |
| 0.25 | 12 | +0.0004 | −0.0001 | +0.0005 | +0.0001 |
| 1.0 | 1 | +0.0012 | −0.0004 | +0.0016 | −0.0053 |
| 1.0 | 3 | +0.0014 | −0.0017 | +0.0031 | −0.0020 |
| 1.0 | 12 | +0.0012 | +0.0007 | +0.0005 | −0.0008 |
| 4.0 | 1 | +0.0024 | +0.0015 | +0.0008 | −0.0054 |
| 4.0 | 3 | −0.0021 | +0.0002 | −0.0023 | −0.0088 |
| 4.0 | 12 | +0.0013 | +0.0016 | −0.0003 | +0.0021 |

Nine cells, three noise settings, and nothing anywhere outside ±0.009. The
generated feeds read the same scatter, −0.0014 to +0.0058, which is what a
null looks like when the twin is doing its job.

The **level** is not nothing - raw AUC for `-surprise` reaches 0.5165 on EURJPY
and 0.5130 on silver, which is reversion of a size people trade. The twin
reproduces essentially all of it. That is
`trailing-zscore-fakes-reversion` again, now on a Kalman innovation rather
than a rolling z-score: a better estimate of the centre does not make the
residual mean anything.

## The artefact the two bases were there to catch

A surprise at bar `t` is computed from `close(t)`; a forward return measured
from `close(t)` shares that price, so a bad print inflates the surprise and
depresses the return by the same amount. Measuring the return from
`close(t+1)` removes the shared price, and the gap between the two columns is
the artefact: **+0.0005 to +0.0031** at the two tighter noise settings, and
mixed at the loosest.

Small - and the same size as the whole effect being looked for. Base `t` with
no twin would have reported a +0.002 reversion edge at every noise setting,
which is exactly the magnitude that survives a careless write-up.

## The control that nearly ate its own median

`behaving.drives_q` is `False` for a feed whose generator fixes its tick count,
so pacing is inert there and the `pace` term is **exactly** constant - AUC
0.5000 against a twin's 0.5000, an edge of exactly zero. Pooling those two
feeds with the eight live ones put the median of ten instruments **on a
control**, printing `pace +0.0000` at three of nine cells.

That reads as "perfectly neutral" and is nothing of the kind. The pools are now
split by whether the mechanism is live, which is also the better control
statement: the term is inert exactly where the family table says activity
carries nothing, and live - 0.4823 to 0.5204 - everywhere else.

## What the terms are for, given they predict nothing

`surprise` stays published and stays offered, because its value is diagnostic
rather than directional: it is the quantity the quantile band is built from, it
says whether the model is being surprised, and a caller cannot compute it. Use
it as a novelty flag or a gate - "the filter did not expect this" - and not as
a side-picker.

Which leaves the output layer with no term that carries a direction, from
either source: not the eleven hand-built features of
[`signal-layer.md`](signal-layer.md), whose best arm reached +0.0008 of edge,
and not statespace's own two. The layer is the right place to put the
arithmetic, and nothing measured yet deserves to go through it.

That is consistent with where this desk's losses actually come from. The one
live strategy measured in detail loses on **geometry and timing** - 62% of its
positions stop out within seven minutes while its targets pay when reached -
and not on a signal that was too weak. A better weighted sum would not have
helped it.
