# Rank-then-map, built and measured

`till_infinity/structures/statespace/ranking.py`, built 2026-10-11 after the
pre-test in `informatory-pairs.md` said its premise holds. Harness:
`research/ideas/rank_then_map.py`.

## What the pre-test had already decided

Three design questions that would otherwise have been guesses:

* **The target is magnitude.** At most 6 of 45 bin pairs could be ordered by
  their mean *signed* outcome at two standard errors. There is no ordering of
  direction to learn, so the model does not try.
* **One model spans every instrument and resolution** - instrument reads 5.1%
  informatory, timeframe 0.0%.
* **Volatility regime and session are input features, not separate models** -
  47.1% and 23.4% informatory, which is how the paper treats column and pH.

## The two pieces

`Ranker` is a linear RankNet with **no intercept**, because a constant cancels
in every pairwise difference and fitting one would be fitting a parameter the
loss cannot see. Pairs closer together than `margin` are not compared at all -
the paper's ten-second rule - which puts the cost threshold inside the loss
rather than beside it, and pairs that do clear it are weighted by `tanh` of the
gap so one just past the threshold does not count as much as one at the far end.

`Mapping` turns a score into a quantity: median regression by iteratively
reweighted least squares, then least squares on the inliers, on a degree-two
polynomial. The paper measured that against generalised additive models,
shape-constrained additive models and constrained B-splines, and the simplest
won. One addition they do not make: **a quantity that rises with rank must not
fall again**, and a parabola has a turning point that anchors clustered at one
end can put inside the range, so the fit falls back to a straight line and sets
`straightened` when that happens.

## The evaluation: leave one instrument out

The paper's own design - condition-disjoint folds. The ranker trains on four
instruments and is asked about the fifth, which it has never seen, with thirty
anchors from that fifth instrument's own *training* period to set the scale.

Rank correlation against the realised magnitude, 1h bars, horizon 4h:

| held out | GLOBAL | per-instrument | one-step | trailing sd |
|---|---|---|---|---|
| eurusd | **+0.189** | +0.187 | -0.116 | +0.138 |
| xauusd | **+0.221** | +0.221 | +0.116 | +0.242 |
| gbpusd | **+0.211** | +0.191 | -0.099 | +0.185 |
| usdjpy | +0.191 | **+0.273** | -0.173 | +0.230 |
| v75 | +0.050 | -0.039 | -0.039 | +0.102 |

**The transferability claim holds.** A ranker that has never seen the instrument
matches one trained on it - identical on xauusd, better on gbpusd and v75,
within noise on eurusd, worse only on usdjpy. That is the paper's result,
reproduced here, and it confirms the pre-test that predicted it.

**The two-step is earned.** One step - least squares straight onto the value -
is *negative* on four of five instruments. Disentangling the order from the
scale is not decoration; predicting the value directly across instruments does
worse than nothing.

**And it does not beat the trailing standard deviation.** Two of five on rank
correlation at 4h, two of five at 24h, and on mean absolute error the mapped
quantity ties a trailing sd given the same thirty anchors to scale on: 7.45
against 7.33 on eurusd, 26.88 against 27.11 on gold, 8.11 against 8.08 on
gbpusd. So the model is not shippable, which is this desk's base rate and the
reason the null is fixed in advance.

## The bug, which was the whole first answer

The first run reported GLOBAL at **+0.042 to +0.083** against per-instrument at
**+0.178 to +0.272** - the transferability claim failing by a factor of four,
and in direct contradiction of the pre-test that said instrument carries 5.1%.

When a measurement contradicts one that was done carefully, suspect the new one.
The training target was `|move|` in **basis points**. Pooling four instruments
to train a pairwise ranker therefore asked it to compare gold's move against the
euro's - a comparison whose answer is "which instrument is this", which is not
in the features and cannot be learned. The per-instrument ranker never faced
that comparison, so it was unharmed, and the gap looked like a property of
transfer.

Ranking now trains on `|move| / (unit * sqrt(horizon))`, a `z`, and the mapping
keeps the raw value because putting the instrument's scale back is its entire
job. GLOBAL went from +0.05 to +0.19 on one line.

**The general shape:** a model that pools conditions must be trained on a
quantity that is comparable across them. It is the same error as the harness
that normalised by arithmetic return from a fixed base, and the same error as
comparing a bar count across timeframes - a quantity that silently means
different things in different places.
