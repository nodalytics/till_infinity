# The art of feature design

Companion to `label-design.md`. That one argues a label's information is what remains
after the determined part is removed. This one is about the other side: what a feature
has to be in order to carry information at all, and what this desk has learned by
getting it wrong.

Every claim here has a measurement behind it from this repository.

## 1. Nothing may carry a price unit

A race between volatility estimators once had every candidate correlating at about 0.57
with its target. They were all tracking drift in the price level. Normalising collapsed
them to ~0.30 **and reordered the ranking** - so the conclusion, not only the magnitude,
had been an artefact.

Every feature must be a ratio, a count, or a z-score. Returns are divided by the
prevailing true range, wicks by the bar's own reach, candle windows by both the last
close and the true range. A convolution fed raw prices learns which decade it is looking
at; `tests/test_supervised.py` asserts that multiplying every price by 40 leaves the
windows unchanged, because this is the failure that is easiest to reintroduce.

## 2. Shape and size are different features, and normalising away one loses it

`body_frac`, `upper_wick` and `lower_wick` are fractions of the bar's own range. They
capture **shape** and deliberately discard **size** - which means a doji and a huge
indecisive bar are identical to them.

That is a real loss, because the operator's own rule is about size: a run of
same-coloured candles counts only if one of them is long enough to signify intent. A
model given only the fractions cannot express that rule at all. So `body_tr`,
`upper_wick_tr` and `lower_wick_tr` were added alongside, in true ranges.

The general form: **whenever you normalise to gain invariance, ask what the invariance
just destroyed**, and carry that separately if it matters.

## 3. An event and a standing state are not the same feature

A fair value gap can be expressed two ways, and they answer different questions.

* **as an event** - `gap_2_tr` is non-zero on the bar the gap forms. A fact about one
  candle.
* **as a standing state** - `bull_gap_dist`, `bull_gap_age`, `bull_gap_wick`: there is an
  untouched imbalance at a particular price, this far away, this old, opened by a wick
  of this size. It stops counting the moment price trades back through it.

The second is what an operator actually watches, and it is strictly more informative -
but it is also more expensive, requiring a backward scan per bar rather than a
comparison. Both are carried, because the formation bar and the standing level are
genuinely different moments.

This generalises: **most "signals" have a state form that persists and an event form
that fires once.** Carrying only the event throws away everything between occurrences,
which is most of the data.

## 4. Causality has to be structural, not checked

The guard that matters is not a test but an architecture: `candles.features` indexes
`<= at` only, and every label family indexes `> at`, in separate functions that never
share a window.

This is structural because the obvious check does not work. A forward return left in a
feature table once produced AUC 1.000 here, and **single-feature AUC missed it** - a
signed return against an absolute-magnitude target is not monotonic, and AUC only sees
monotonic relationships.

The tests therefore assert the property in both directions: change a future bar and the
features must not move; change it and the label must. A test that only checked for
leakage would pass on a label that had quietly stopped looking forward, which is a worse
bug.

## 5. A feature that re-derives a known quantity is worse than the quantity

The sharpest lesson of the session. Persistent homology was used to build twelve
features - total persistence, entropy, landscape norms - to forecast forward volatility.
They reached 0.3604 balanced accuracy. **Six trailing realised-volatility ratios reached
0.4279**, and adding the twelve to the six bought 0.0026.

There is a proof behind it. The `L1` landscape norm has closed form `(1/4) sum (d-b)^2` -
a sum of squared lifetimes, dimensionally a variance - and Aromi, Katz and Vives (2021)
prove the norm is homogeneous of degree `1 + 1/p` in scale, bounded by the **second**
eigenvalue of the covariance, and tends to zero as correlation tends to ±1. So it is a
variance measure attenuated by correlation.

Measured directly here, regressing `log ||lambda||_1` on log realised variance over a
64-bar window: slope **0.784**, R² **0.329**. So on a single-series delay embedding it is
only a third variance - less than predicted - but the residual adds just **+0.0122** of
out-of-sample R², which sits inside the 0.0007-0.0329 band that the same construction
produces in a simulation built to contain *no* information beyond volatility.

**Before building an elaborate feature, work out what cheap quantity it is a noisy
version of.** If the answer is "a variance", the cheap version wins.

## 6. The invariance you choose decides what is findable - and cannot manufacture signal

Persistence diagrams are invariant to time-warping and monotone rescaling, so the same
shape at twenty bars or forty gives a similar diagram. That is a real property and a
genuine reason to prefer them over raw-coordinate clustering, which treats those as
unrelated: a shape recurring *at varying speed* is invisible to fixed-length pixel
patterns.

It was also the right idea and it found nothing - 1 of 19 shape clusters clearing its
bootstrap band against 1.0 expected, at two different embeddings. **A better
representation reveals information that is present; it does not create information that
is absent.**

## 7. Measure your own hyperparameters

Two harnesses fixed a delay embedding at dimension 3 with unit lag on no grounds. When
`embed.py` measured it properly - first minimum of mutual information for the lag, false
nearest neighbours for the dimension - the answer was **lag 4, dimension 6**, with
near-identical curves across seven instruments.

Lag 1 embeds adjacent returns, which are nearly redundant, so the cloud collapses toward
its diagonal. Dimension 3 under-embeds a series that does not settle until 6. Both
negative results had been measured at the wrong embedding, and the obvious objection was
correct.

Mutual information rather than autocorrelation, incidentally, because autocorrelation
sees only linear dependence and the entire premise of embedding a price series is that
the dependence is not linear.

## 8. Overlapping windows inflate every importance and every error bar

Consecutive 32-bar windows share 31 bars. A permutation importance or a two-proportion
error computed as though rows were independent is too confident, and not by a little: the
block bootstrap widened `motifs.py` bands by half and **turned 9 of 24 "significant"
clusters into 0**.

Any feature evaluated on overlapping windows needs a block-resampled error bar, and
training needs sample weights by uniqueness.

## What has not been tried here, in order of expected value

**The `spread` field on every broker bar.** The bridge returns `spread` with each candle
and **nothing in this repository reads it.** That is free liquidity and cost information,
per bar, already downloaded. The desk separately measured spread at 0.10-1.07bp and
derived the whole quiet-hours rule from spread behaviour - yet no model has ever been
given it. This is the largest unexploited field in the data.

**Cross-sectional features.** Every feature here is a function of one instrument's own
history. None asks where an instrument sits *relative to the panel at that moment* - its
return rank, its volatility rank, whether it is leading or lagging. That removes the
common factor by construction, which is the same trick residualisation performs on
labels, and it is the one class of feature this desk has never built.

**Regime-conditional normalisation.** Features are standardised against their own trailing
window. Standardising within a *regime* instead - the z-score of this reading among
readings taken in similar volatility - asks whether the value is unusual *for these
conditions*, which is a different and usually sharper question.

**Time-since features.** Bars since the last swing, the last gap, the last regime change.
`bull_gap_age` is the only one that exists. These are cheap, and they carry the state a
purely instantaneous feature cannot.

**Features from the desk's own state.** How many of the sixteen strategies currently
agree; how much heat is on the book; how long since the last loss. These are recorded in
the journal already, and they are the natural inputs to the meta-labelling that
`label-design.md` argues for.

**Asymmetry.** Nothing here measures skew - the difference between upside and downside
realised volatility over the same window. Given that direction is empty and volatility is
not, the asymmetry *of* volatility is the obvious unexplored middle.

## The discipline that makes any of it worth running

Dimensionless, causal by construction, and compared against the cheapest quantity it
could be a noisy version of. Then a purged walk-forward, a block bootstrap that respects
the overlap, leave-one-instrument-out, and a baseline that could plausibly win rather
than a shuffled null.

Six model classes have now agreed that direction at these horizons is close to empty.
Feature design cannot overturn that. What it can do is stop the informative part being
spent on re-deriving arithmetic - and the one signal that did survive was the one where
the determined part had already been divided out.
