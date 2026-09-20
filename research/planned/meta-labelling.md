# Meta-labelling: take the signal, or its inverse

Status: **measured 2026-09-19 on reconstructed labels. No edge - AUC 0.506.** See the result at the end.

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

## Result, 2026-09-19

Labels rebuilt from stored bars for 28,208 level calls on the 33 core
instruments (FX, indices, metals, energy, btc/eth/sol), synthetics excluded:
the return from the close at decision time to the close 5 minutes later,
signed by the call. The corrected label confirms the trap above -

| horizon | old label "right" | corrected "right" |
|---|---|---|
| 60s | 4.9% (synthetics) | 47.8% |
| 300s | 11.6% | 49.6% |
| 900s | 20.7% | 50.0% |

- the raw call is a coin flip once it is measured from where a trade could
enter.

Then 59 features (the 68 numeric ones less ten raw price levels, which
identify the instrument and the week rather than the setup), walk-forward
over five time-ordered folds with the 5-minute horizon purged and a
30-minute embargo. 16,627 calls out of sample:

| strategy | hit | AUC | gross | net of spread |
|---|---|---|---|---|
| always raw | 50.1% | - | -0.06bp | -2.13bp |
| always invert | 49.9% | - | +0.06bp | -2.00bp |
| logistic regression | 49.7% | 0.506 | -0.12bp | -2.18bp |
| gradient boosting | 50.4% | 0.506 | -0.00bp | -2.07bp |
| logistic, p >= 0.55 only | 51.0% | - | +0.13bp | -2.02bp |

Nothing separates a right call from a wrong one, and every strategy nets the
spread. Spreads are stated per market class (1.5bp FX to 3bp crypto and
energy), not measured per trade; the conclusion does not depend on them,
since the gross column is already zero.

So the meta-model has nothing to find at this horizon: the level calls carry
no directional information at 5 minutes, conditioned on anything recorded.

Re-run at longer horizons on 2026-09-20, out to a day: the call stays at
50.5-50.8% through 4 hours, and the one row that looks different (48.0% at a
day, which would make inverting worth +6.20bp net) is overlapping windows -
t = -8.31 overlapping becomes t = -0.94 on one call per instrument per day, and
a shuffled control beats that 34.5% of the time. See the horizon sweep in
`directional-edge.md`, including the part that does hold: the mean absolute
move is 2.1bp at a minute against a ~2bp round trip.

**What this means for the two changes this document asks for.** Recording the
label from the entry price and writing `level_id` are still the right fix - the
current label is measured from the level and leaks the resolution side, so it
will mislead anything that reads it later. But they buy no edge at the horizons
the desk trades, so they are correctness work on the record, not a route to a
model. Worth doing when the recording path is touched anyway; not worth a
deploy of its own.

