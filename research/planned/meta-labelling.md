# Meta-labelling: take the signal, or its inverse

Status: **not built. Blocked on the label, which is measured wrong today.**

The proposal: for each level signal, a second model decides whether to take
it as published or the other way round, from the features the signal carried
when it was made. Trained offline and walked forward, then kept current
online.

## The inverse does not need to trade live to be learned

The outcome of the inverse is the outcome of the raw call negated, less a
second spread. One label - the raw call's forward return - decides both. So
the `inverse` strategy running live adds no information to this model; it
adds a second spread to every signal it takes.

## What is recorded today

| | count, 3 days | carries `level_id` | features |
|---|---|---|---|
| level decisions | 5,628 | **yes** | **95**, at the top level |
| forward returns | 5,478 (4,601 all horizons) | **no** | 7 |

The features are rich - break probability, base rate, edge, GARCH and
ensemble volatility, forecast, hour, macro - and every decision names its
level. The forward returns are recorded for every resolved touch, traded or
not, which is what an unbiased label needs. They cannot currently be joined:
the tracker keys followers by `level.id` and then drops the id when a record
is drained.

## The trap, measured 2026-09-19

The forward return is `side × (price − level)` - measured from the **level**,
not from the price when the decision was made. A touch only resolves once
price has moved away from the level, so the sign is largely settled at
resolution. On synthetic instruments, which are random walks:

| horizon | call "right" | median |
|---|---|---|
| 60s | 4.9% | −1.98 |
| 300s | 11.6% | −2.07 |
| 900s | 20.7% | −1.98 |

The median is −2.0 volatility units **at every horizon**, and for 80.3% of
labels the sign at 60s already equals the sign at 900s. The rising "right"
column is a random walk diffusing back across zero from that offset. Nothing
predicts a random walk 88% of the time in reverse, so this is the resolution
side leaking into the label, not an edge.

A model trained on it learns "always invert", scores 80-95% in any backtest,
and loses money live - because at decision time the entry is the current
price, not the level, and the resolution side is not yet known.

## What has to change before training

1. **The label is the forward return from the price at decision time**,
   signed by the call's side - not from the level. This is the only label
   that corresponds to a trade anybody could actually take.
2. **Write `level_id` onto the label**, so it joins to the 95 features
   without matching on a price the Kalman filter moves.
3. **Exclude the synthetics from training.** They are random walks - see
   `research/docs/coinbase-premium.md` for the method and today's
   measurement for the result - so their label is noise, and a model fed
   noise fits it.

The first two can also be reconstructed for past decisions, without waiting,
by joining each decision's time and feed to the stored bars for the entry and
exit prices. That buys a training set immediately instead of in weeks.

## The model

* **Offline first**: gradient-boosted trees and a regularised logistic
  regression on the 95 features, predicting the sign of the corrected label.
* **Walk-forward only**. Never shuffled cross-validation: neighbouring
  signals share a market, so a shuffle leaks the answer. Purge the overlap
  between a label's horizon and the next fold, and embargo past it.
* **Online after**: `river` is already a dependency, so an incremental
  logistic model can learn from each label as it lands and be scored
  prequentially - predict, then learn.

## What decides whether it is worth anything

Out of sample, after the spread, against three baselines: always take the
raw signal, always invert it, and the base rate. A model that does not beat
the better of "always raw" and "always invert" is a coin with extra steps.

## What would falsify it

* The corrected label's hit rate is indistinguishable from 50% across
  instruments, so there is nothing for a meta-model to find.
* Walk-forward accuracy does not beat the better constant baseline.
* An edge exists in sample and vanishes on the held-out period - the
  Coinbase premium's pattern, and the reason every claim here is scored
  out of sample.
