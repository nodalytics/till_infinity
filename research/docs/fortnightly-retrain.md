# Measure it the way production runs it: a fortnightly retrain contest

**Measured 2026-10-08.** Asked for as "can we recalibrate models every 2 weeks
based on data, for offline models training included, cause that is how it is
gonna be in real life".

The gap was not production. Production already runs
`till-infinity models retrain --every-days 14`, holds out the most recent
fortnight, trains a challenger on everything before it, scores both the
challenger and the champion in service on that hold-out, and **promotes only if
the challenger wins**. The gap was the research side: every model in
[`zscore-magnitude.md`](zscore-magnitude.md) was fitted once and scored on
everything after, which is not a number this desk could ever have collected.

Code: [`fortnightly.py`](../ideas/fortnightly.py). It mirrors
`models/retrain.py` rather than inventing a protocol, including the step a plain
walk-forward cannot see.

## The protocol, and the step that matters

1. every 14 days, hold out the most recent 14 days
2. train a **challenger** on everything before that hold-out, with the boundary
   purged by the horizon
3. score challenger **and champion** - the model actually in service - on the
   hold-out, which neither was trained on
4. **promote only if the challenger wins**; otherwise the champion keeps trading
5. trade the next fortnight with whatever is in service

Step 4 is the one a walk-forward leaves out. A plain walk-forward always deploys
the newest fit, so it measures a desk that redeploys blindly. Production does
not, and the difference is measurable rather than rhetorical - see below.

## The result

218,440 4h bars, sixteen instruments, 2,975 days, **174 fortnights**:

| training window | mode | IC mean | IC median | positive | decile spread | promoted | served challenger |
|---|---|---:|---:|---:|---:|---:|---:|
| expanding | `always_new` | +0.0936 | +0.0973 | 166/174 | +0.289 | 86/174 | 174 |
| expanding | **`gated`** | **+0.0936** | **+0.0974** | **165/174** | **+0.290** | 89/174 | **89** |
| trailing 2y | `always_new` | +0.0855 | +0.0857 | 166/174 | +0.266 | 93/174 | 174 |
| trailing 2y | `gated` | +0.0854 | +0.0868 | 166/174 | +0.268 | 92/174 | 92 |
| **fit once** (the published figure) | | **+0.0753** | - | - | **+0.239** | - | - |

### The published number understated it

Refitting fortnightly gives **IC +0.0936 against +0.0753** and a decile spread of
**+0.290 against +0.239** - about a quarter better on both. Measuring a model the
way it would actually be run usually deflates it; here it did the opposite,
because a model refitted every two weeks is simply a better model than one
fitted in 2022 and left alone.

### Positive in 165 of 174 fortnights

95%, across six and a half years including 2020. That is a far stronger
statement than any single date split, and it is the statement the desk can act
on, because every one of those fortnights is a fortnight the model could have
been serving.

### The promotion gate is free insurance

`gated` and `always_new` are **identical to four decimals** - +0.0936 both - but
the gated desk promotes only **89 of 174 times**. It runs a stale champion in
half the fortnights at no measurable cost.

Two things follow. Production's contest rule is safe to keep, since it buys
protection against a bad refit and gives up nothing. And the retrain **cadence**
could be relaxed without harm: half the retrains are not being deployed anyway.

### Expanding beats trailing

All history (+0.0936) against a two-year window (+0.0855). There is no case here
for discarding old data, which is worth knowing before anyone adds a retention
policy to save space.

## What this does not settle

* **It is one model on one target.** The same harness should be pointed at the
  offline models that production actually promotes - the envelope quantile
  forecaster above all - and that run is
  [`envelope_vs_magnitude.md`](envelope-vs-magnitude.md)'s question, not this
  one's.
* **The magnitude model is a sizing input, not a signal.** Nothing here predicts
  direction; see [`zscore-ml.md`](zscore-ml.md), where the barrier test found
  48.7% against a 48.6% base rate.
* `WARM` is 540 days before the first fit and `TRAIL` is 730. Neither was swept.
