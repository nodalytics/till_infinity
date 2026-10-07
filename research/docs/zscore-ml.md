# Changing what the model optimises for, and the one question that settles it

**Measured 2026-10-07.** [`zscore-variants.md`](zscore-variants.md) found a
boosted model that saw something real (+0.056 ATR at the decile against a flat
shuffled control) and still lost to two hand-written inequalities, and blamed the
loss: *squared error over every bar optimises the middle, while the hand
condition goes straight to the rare corner*. That is a claim about the objective,
so this changes the objective.

Code: [`zscore_ml2.py`](../ideas/zscore_ml2.py). 218,440 4h bars, sixteen
instruments, one date split (train to 2024-04, boundary purged by the horizon).

## The losses

Out of sample, forward move in ATR, at three sharpnesses:

| loss | 10% | 5% | 1% |
|---|---:|---:|---:|
| squared error (baseline) | +0.043 | +0.074 | +0.173 |
| quantile 0.90 | +0.015 | +0.023 | +0.109 |
| quantile 0.10 | +0.014 | +0.002 | -0.095 |
| both quantiles averaged | +0.037 | +0.047 | +0.054 |
| **squared error weighted by \\|y\\|** | **+0.064** | **+0.079** | **+0.196** |
| **fitted on the rare corner only** | +0.036 | +0.012 | **+0.257** |
| shuffled control | +0.016 | +0.019 | -0.100 |

Two of the five changes help and three do not.

**Weighting by `|y|` helps a little** - it is the same loss with the big moves
counting for more, and it beats the baseline at every sharpness.

**Fitting only on the rare corner helps most, exactly where predicted.** Trained
on the 79,758 bars already past 0.6 of the attainable z and scored on the
matching 34,527, its top 1% reaches **+0.257 [+0.022, +0.358] on 346 bars - the
only cell in this file whose interval clears zero**. So the diagnosis was right:
capacity spent on the 90% of bars nobody would trade is capacity wasted.

**The quantile losses are worse, not better.** That is worth stating plainly
because they were the obvious idea - predict the upper quantile, trade the upper
quantile - and the 0.10 quantile is actively negative at the sharp end.

## The question that settles it

The last fit asks what a trade asks: **did price reach +1 ATR before -1 ATR
within twelve bars?** Ties go to the stop, because a single bar spanning both
barriers cannot say which came first and the desk's engine resolves that against
the trade.

| selection | n | win rate | 90% interval | at 1:1, before costs |
|---|---:|---:|---|---:|
| base rate | 214,787 | **48.6%** | - | -0.028 R |
| classifier top 20% | 12,858 | 49.1% | [47.9%, 50.2%] | -0.019 R |
| classifier top 10% | 6,429 | 48.7% | [47.2%, 50.2%] | -0.025 R |
| classifier top 5% | 3,215 | 48.9% | [47.0%, 50.8%] | -0.021 R |
| classifier top 1% | 643 | **46.2%** | [42.1%, 50.7%] | -0.076 R |

**Nothing.** The top decile wins 48.7% against a base rate of 48.6%, and the top
1% is *worse* than the base rate. Every interval contains the base rate.

This is the most useful number in the whole z-score line of work, and it explains
the rest of it. **A conditional mean of +0.14 ATR over three bars does not move
the odds of touching +1 ATR before -1 ATR at all.** The two are not the same
statement: the mean is lifted by a few large moves, while the barrier question is
decided by the path, and a stop converts path into outcome. Every figure in
[`zscore-window.md`](zscore-window.md) and
[`zscore-variants.md`](zscore-variants.md) is of the first kind.

It also matches what the desk has already measured elsewhere. The loss has been
traced four independent ways to stops sitting inside the instrument's own noise;
a signal that shifts the mean without shifting the touch probability is precisely
a signal that dies at the stop.

## The head to head, after the fact

The comparison above was unfair in one direction and the one in
`zscore-variants.md` was unfair in the other: the hand rules were scored on the
conditional mean and the model on the barrier. So both were put through the
barrier on the same bars and the same test period
([`zscore_barrier.py`](../ideas/zscore_barrier.py)):

| rule | n | win rate | 90% interval | at 1:1 |
|---|---:|---:|---|---:|
| **base rate** | 64,290 | **48.6%** | [47.9%, 49.3%] | -0.028 R |
| `\|z\| >= 2` | 5,452 | 47.1% | [45.7%, 48.6%] | -0.058 R |
| `\|z\| >= 2` and body >= 70% | 2,727 | 48.4% | [46.5%, 50.1%] | -0.033 R |
| normalised `\|z\| >= 0.8` | 1,056 | **46.4%** | [43.4%, 49.5%] | -0.072 R |
| term structure aligned | 3,372 | 47.5% | [45.4%, 49.5%] | -0.050 R |
| model (corner), top 1% | 650 | 48.9% | [44.1%, 53.2%] | -0.022 R |
| model (barrier), top 1% | 644 | 46.1% | [41.7%, 50.7%] | -0.078 R |

**Not one rule beats the base rate, and the ranking inverts.** The cell with the
largest mean-move spread in the whole study - normalised `|z| >= 0.8`, 0.250 ATR
with both tails clear of zero - has the second-worst win rate in the table. The
hand rules won the metric that does not convert and lost the one that does; the
corner-trained model is the least bad row here.

Mechanically: these rules select bars that just moved a long way, so realised
volatility sits above the trailing ATR that sets the barrier, more bars span both
barriers, and every one of those is a loss under the tie convention. Part of the
gap is therefore the tie rule, and tick resolution would soften it - but that is
the desk's own engine convention, so it is the right one for a decision.

## Online learners see the same nothing

Production's structures models are online, so a result only a batch fit can see
does not transfer. [`zscore_online.py`](../ideas/zscore_online.py) runs the same
features **prequentially** - predict, then learn, with each label withheld until
its own window has elapsed.

| model | forward-move IC | barrier, top decile |
|---|---:|---:|
| linear SGD | +0.0047 | - |
| passive aggressive | +0.0035 | - |
| Hoeffding adaptive tree | -0.0006 | 49.3% |
| adaptive random forest | +0.0014 | - |
| logistic | - | 49.7% |
| *base rate* | - | *49.0%* |

Nothing, online or batch.

**The first version of that file reported an IC of +0.30** - a hundredfold jump -
because it learned from each bar as it arrived. The label is a move over the next
three bars, so that handed the model the answer for every overlapping window. A
bar now enters a queue when it closes and is learned from only once its label's
own window has elapsed, keyed on timestamp rather than position because bars are
interleaved across sixteen instruments. It is also the only version a live desk
could run: the outcome of a trade opened now is not a training example until it
is over.

## What the model was using

Permutation importance on the test set, as the drop in the decile spread:

| feature | drop |
|---|---:|
| `z_fast_slow` | **+0.0224** |
| `z36` | +0.0181 |
| `z8` | +0.0124 |
| `atr_rel` | +0.0099 |
| `body_atr` | +0.0053 |

The **term structure is the model's most important single feature**, ahead of
every individual window. That is independent agreement with the hand study, which
found the same thing by cross-tabulation: a fast reading is worth six times as
much inside an extended slow window as inside a flat one. Two methods, one
answer, and the one the model reaches for first.

## What to conclude

* **The loss was the right thing to blame, and fixing it is not enough.**
  Training on the corner sharpens the forward-move prediction to the best cell in
  the study. It still does not produce a tradeable edge, because the forward-move
  metric was never the trade.
* **Score on the barrier, not the mean, from now on.** Any future idea on this
  desk should be put through the barrier question before anyone reports a
  conditional mean, because that is the step where this one died and it costs one
  function to ask.
* **The term structure is real enough to be found twice**, by hand and by a
  model that was not told to look for it. It is still not an edge.
