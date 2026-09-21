# The art of label design

Everything this desk has tested for direction has landed on its null. The models were
not the problem - logistic regression, gradient boosting, a dense net, a convolution,
k-means on raw windows, k-means on persistence images and persistent homology all
returned the same answer. When six model classes agree, the model class is not the
variable.

**The label is.** This is what a session of failures taught about designing them, with
the evidence for each claim.

## The central principle: a label's information is what remains after the determined part is removed

Every null tonight had the same shape. The label was dominated by a component that was
*determined*, so the model spent its capacity re-deriving something that was never in
doubt and had nothing left for the part that mattered.

| label | the determined part | proved by |
|-------|--------------------|-----------|
| `triple`, symmetric barrier | base rate is `a / (a + b)` = 0.5, from geometry alone | `barrier_pde.py`, analytically |
| `banded` | majority class 51% flat, set by band width over volatility | `supervised-candles.md` |
| textbook patterns | the measured-move target fixes R:R, hence breakeven | `patterns.md` |
| `expansion` via persistence norms | the norm **is** a variance, degree-2 homogeneous | `topology.md` |

That last one is the sharpest. The persistence-landscape norm has closed form
`(1/4) sum (d - b)^2` - a sum of squared lifetimes, dimensionally a variance - so
predicting forward volatility with it is predicting variance with variance. It scored
0.3604 against 0.4279 for six trailing volatility ratios. The "signal" was a worse
measurement of the predictor.

So the first question about any label is: **what part of this is arithmetic?** Subtract
that, and what remains is the only thing a model can learn.

## Techniques, and what each one removes

### 1. Residualise against a known model

Make the label the *excess* over what something already explains. `labels.seasonal`
already does this - it subtracts the instrument's own running mean for that calendar slot
and bands what is left, so it asks whether anything beyond the season is there.

The generalisation: subtract any baseline you would otherwise have to beat.

* barriers → subtract the fair-odds probability `a / (a + b)` (`beat_theory.py`)
* volatility → subtract a GARCH or trailing-realised forecast
* cross-section → subtract the same-bar mean across instruments, which removes the
  common factor entirely

**The trap, and it is not obvious:** residualising against a *constant* removes nothing.
A symmetric barrier has fair odds of exactly 0.5 for every row, so subtracting it is
recentring. The baseline has to **vary per row** for the subtraction to carry
information, which is why `beat_theory.py` takes its barriers from the last confirmed
swings rather than from a multiple of volatility.

### 2. Meta-labelling

Do not label which way price goes. Label whether a **primary signal was right**.

This is the most promising unexplored direction here, for a specific reason: this desk
runs sixteen strategies that already emit signals, and `directional-edge` plus four
other studies say the direction question is empty. But "was *this* signal correct" is a
different question with a different base rate - the strategy's own precision, typically
nowhere near 50% - and a model that only decides *whether to act* never has to solve the
problem that has failed six times.

It also matches the machinery already built: `service.py` records every signal and
`_credit` files the outcome, so the labels exist without any new computation.

### 3. Weight by uniqueness, because overlapping labels are not independent observations

A 40-bar window with a 24-bar horizon shares nearly everything with its neighbour. Every
naive error bar tonight was too narrow for exactly this reason, and it was not a small
effect: the block bootstrap widened the `motifs.py` bands by half and **erased a result
that a two-proportion error had passed** - 9 of 24 clusters "significant" became 0.

The block bootstrap fixes the *evaluation* side. The training side needs sample weights
proportional to how much of each label's window is unique, or the fit is dominated by
whichever period was sampled most densely.

Both belong in any label that looks forward over a window, which is all of them.

### 4. Sample in event time, not clock time

Fixed-interval sampling gives a quiet Sunday the same number of rows as a violent
Thursday, so the label's variance is not stationary and the model sees mostly nothing
happening. Alternatives, all standard:

* **volume or dollar bars** - one row per fixed traded quantity
* **CUSUM event sampling** - one row each time cumulative return breaches a threshold,
  which is what `structures/context/cusum.py` already computes for the live desk

The desk's own `Cusum` is already running and already filters for material moves. Using
it to *select rows* rather than only to read momentum is nearly free.

### 5. Let the data choose the horizon

Every horizon in this repository was picked by hand - 5 bars, 12, 24, 48 - and none was
justified. **Trend scanning** removes the choice: fit a line over forward windows of
several lengths, take the one whose slope has the largest t-statistic, and label by that
sign and significance. The label then carries how *clean* the move was, not merely its
direction at an arbitrary distance.

This also fixes a subtle problem with banded labels: a row labelled flat because the move
arrived just after the horizon is labelled wrongly, and there are many of them.

### 6. Label the tail, not the middle

Most rows are noise. A three-class band puts about half of them in the middle class,
where there is nothing to learn, and they dominate the loss. Labelling only the extremes
- was this in the top decile of forward moves - raises signal-to-noise by discarding the
part that was never predictable.

The cost is sample size and a base rate that must be handled explicitly. `speed` does a
version of this already by asking whether a move of a given size arrives at all.

### 7. Duration and censoring instead of a timeout class

`triple` has three classes, and one of them - `timeout` - is not an outcome but an
absence of one. That is survival data wearing a classification label, and the honest
form is a duration with a censoring flag: how long until the barrier, and was the
observation cut short.

It also answers a question the desk actually has. `speed` was written because "when does
a move arrive" matters for sizing and for the hold, and a duration label answers it
directly rather than through a three-way bucket.

### 8. Put the cost inside the label

A win that does not cover its costs is a loss, and every result tonight had to be read
against a separately computed breakeven - 51.5% for a symmetric barrier at 0.03R,
46-55% for the textbook patterns depending on their geometry. Folding the cost into the
label makes "profitable" the thing being predicted, and stops a 50.2% hit rate reading
as a small edge when it is a loss.

## What this session's evidence supports, ranked

1. **Meta-labelling.** Direction has failed six ways; "was this signal right" is a
   different question, the data already exists, and the base rate is not 50%.
2. **Uniqueness weighting and block bootstraps everywhere.** This is not an improvement,
   it is a correction - one result has already been withdrawn for want of it.
3. **Event-time sampling via the existing `Cusum`.** Nearly free, and fixes a
   non-stationarity that affects every label here.
4. **Residualising against a per-row baseline.** Implemented in `beat_theory.py`; the
   principle generalises to every label with a computable fair value.
5. **Trend scanning.** Removes an arbitrary parameter that is currently chosen by hand
   in six harnesses.

## What this does not claim

None of this manufactures an edge. A better label cannot create information that is not
in the data, and the honest reading of this session is that direction at these horizons
on these instruments is close to empty. What label design buys is **not wasting the
information that is there** on re-deriving arithmetic - and the evidence that this matters
is that the one signal which did survive a null was volatility, where the determined part
had already been divided out by construction.

The test of any new label is the same as for any other result here: a purged
walk-forward, a block bootstrap that respects the overlap, leave-one-instrument-out, and
a comparison against the cheapest baseline that could possibly work rather than against
noise.
