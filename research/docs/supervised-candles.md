# Supervised learning on candles: the data, the labels, and the controls

Batch-trained ML and DL models over long candle history, with six interchangeable
label families. This document records what was **measured** while building it. Model
results are a separate section and are marked as such - nothing is claimed here that
was not run.

## The sources, measured rather than assumed

Stooq was the requested source and it cannot be used: every request to both
`stooq.com` and `stooq.pl`, with a browser user-agent, answers HTTP 200 with a
JavaScript proof-of-work page instead of the CSV. That is a deliberate
anti-automation measure and this repository will not carry code to defeat it.
`research/harness/stooq.py` stays, because the wall may lift and because a reader
should see it was tried.

What does answer, pulled on 2026-09-20:

| source   | what it has                      | daily reach     | hourly reach     |
|----------|----------------------------------|-----------------|------------------|
| `yahoo`  | indices, futures, FX, crypto     | 1950 (`^GSPC`)  | last 720 days    |
| `broker` | the desk's own feed, synthetics  | 1971 (FX)       | 2010-2011, paged |

### The broker has far more history than this repository believed

It has been on record here that the broker's own history stops at 2011 for dailies
and 2016 for hourlies, and `monthly-momentum.md` rests a complaint on it: 218
non-overlapping months, too few to separate a decayed effect from a noisy one.

**That is true for metals and wrong for FX.**

| symbol | daily bars | from       | 4h bars | from       |
|--------|-----------:|------------|--------:|------------|
| EURUSD |     15,806 | 1971-01-03 |  49,999 | 1977-12-12 |
| USDJPY |     15,806 | 1971-01-03 |  49,999 | 1977-12-26 |
| GBPUSD |     10,110 | 1993-05-11 |  46,035 | 1993-05-11 |
| XAUUSD |      4,849 | 2011-01-02 |  24,887 | 2011-01-02 |
| XAGUSD |      4,857 | 2011-01-02 |  24,972 | 2011-01-02 |

EURUSD and USDJPY give **55.7 years** of dailies from the desk's own feed - 668
non-overlapping months, three times what the momentum work had, and from bars whose
extremes can be trusted. Yahoo only starts these pairs in 2003. So for FX the broker
wins on depth *and* quality, and the earlier sample-size complaint was measuring the
bridge's reach rather than the broker's.

Yahoo still wins on equity indices, which the broker does not carry with depth:
`^GSPC` to 1950 (19,300 bars), `^N225` to 1988, `^FTSE` to 1984.

### Hourly reaches 2011, and the route I called broken was not

Hourly first came back at 49,999 bars per symbol - 8.0 to 8.5 years - and this
document said the cause was a bridge bug: that `/rates/from` "ignores the count it is
given", returning one bar whether asked for 10 or 5,000.

**That was wrong, and the mistake was mine.** `/rates/from` counts *backward* from the
date it is handed, mirroring MQL5's `CopyRates`: `date_from` is the newest bar of the
sample, not the oldest. Measured - `date_from=2026-09-01, count=3000` returns 3,000
bars running 2026-02-27 to 2026-09-01. Asking it for a date at the very start of a
symbol's history correctly returns the single bar that exists there, which is what I
read as a broken count.

Paging backwards with it gives the full depth:

| symbol      | before | after  | from       | repaired bars |
|-------------|-------:|-------:|------------|--------------:|
| XAUUSD 1h   | 49,999 | 92,108 | 2011-01-02 |             0 |
| XAGUSD 1h   | 49,999 | 92,472 | 2011-01-02 |             0 |
| EURUSD 1h   | 49,999 | 99,999 | 2010-08-11 |             0 |
| GBPUSD 1h   | 49,999 | 99,999 | 2010-08-11 |             0 |
| USDJPY 1h   | 49,999 | 99,999 | 2010-08-11 |             0 |

Gold hourly is 15.7 years, 1.84x what it was. **Zero bars needed repair in any of
them**, against up to 6.9% on Yahoo dailies - the quality claim, confirmed rather
than assumed.

Two real ceilings remain, and neither is the one I named:

* **Response size, not history.** A single response fails near 50,000 records on both
  the positional and the range route - every bar becomes a dict and then JSON inside a
  1GB container - so history is paged rather than requested. `PAGE` is 20,000.
* **The terminal's own bar limit.** The three FX pairs all stop at exactly 99,999
  while the two metals stop at different numbers, which puts the FX limit at MT5's
  100,000 "max bars in chart" setting rather than at the broker's history. Raising it
  in the terminal would give more; the metals are already at their true start.

The bridge did have a defect in this story, and it is the one that made the
misdiagnosis possible: `copy_rates_*` answers `None` both for a symbol that does not
exist and for a request the terminal could not marshal, and all three rate routes
turned that into `404 "No rate data found"`. A request for 400,000 bars therefore read
as "this symbol has no data", which is why the first run reported all 722 symbols as
absent. That is fixed in the bridge - a 502 carrying MT5's own error - along with an
empty window, which used to 500 outright because `pd.DataFrame([])` has no `time`
column. Three unit tests cover it.

### Public daily bars are not internally consistent

Yahoo reports a close outside the bar's own high/low on a material share of rows:

| instrument | rows  | close outside | share |
|------------|------:|--------------:|------:|
| gold       | 6,214 |           430 |  6.9% |
| nzdusd     | 5,897 |           367 |  6.2% |
| copper     | 6,538 |           275 |  4.2% |
| usdjpy     | 7,740 |           261 |  3.4% |
| spx500     | 19,300 |            0 |  0.0% |

Indices are clean; FX and commodities are not. `candles.read` repairs these by
widening the range to contain open and close - the minimal fix, since a close outside
its range means the *range* was misreported - and counts every repair per instrument.
Any label reading extremes (`triple`, `speed`) is therefore softer on Yahoo data than
it looks, and the trainers print the worst repair count before reporting a result.
**This is the reason to prefer the broker feed for barrier work.**

## What a label may and may not look at

A supervised label *must* look into the future. That is what makes it supervised, and
`labels.py` does it deliberately: every family reads bars strictly after `t`. So
"leakage" here never means "the label looked forward". It means two specific things,
and both are closed:

1. **Forward information reaching a feature.** `candles.features` indexes `<= at`
   only, and is a separate function from every label family, so the two never share a
   window. This matters because the previous incident was not caught by the obvious
   check: a forward return left in a feature table produced AUC 1.000, and
   single-feature AUC missed it, because a *signed* return against an
   *absolute-magnitude* target is not monotonic and AUC only sees monotonic
   relationships.
2. **A forward window straddling a split boundary.** A plain date cut leaves the last
   `horizon` training rows labelled from bars inside the test period. `splits.py`
   purges exactly `horizon` rows at the boundary and embargoes `WARMUP` rows after it,
   because features are built from trailing windows up to 120 bars long.

Verified empirically: across all six families on 20 instruments, the strongest
absolute correlation between any single feature and its label is **0.166**
(`lower_wick` under `triple`). Nothing is near 1.

## The six label families

| family      | question                                            | classes                    |
|-------------|-----------------------------------------------------|----------------------------|
| `banded`    | up/flat/down by `band` true ranges, close to close  | down, flat, up             |
| `triple`    | target, stop and clock - what the desk actually does | stopped, timeout, target   |
| `speed`     | how fast a move of that size arrives, unsigned      | fast, slow, never          |
| `expansion` | is volatility about to expand, hold or contract     | contract, steady, expand   |
| `regime`    | is the next stretch trending, reverting or neither  | revert, neither, trend     |
| `seasonal`  | the move net of what the calendar already explains  | under, as-usual, over      |

Class balance on 6 Yahoo daily instruments, 38,060 rows, horizon 5, band 1.0 TR:

| family      | majority | distribution                                |
|-------------|---------:|---------------------------------------------|
| `banded`    |    51.4% | down 24%, flat 51%, up 25%                  |
| `triple`    |    43.7% | stopped 43%, timeout 13%, target 44%        |
| `speed`     |    54.0% | fast 54%, slow 33%, never 13%               |
| `expansion` |    36.3% | contract 36%, steady 28%, expand 36%        |
| `regime`    |    64.0% | revert 64%, neither 7%, trend 29% (h=20)    |
| `seasonal`  |    51.3% | under 24%, as-usual 51%, over 24%           |

Two of these are worth noting on their own.

`triple` comes out **43% stopped against 44% target** at a symmetric barrier, which
is the fair-odds line the barrier-geometry work kept arriving at from four different
directions. A first-passage label at a symmetric barrier is close to a coin flip
before costs, exactly as that work predicted, and a model has to beat the coin rather
than beat 50%.

`regime` reports **64% reverting against 29% trending** on daily bars at a 20-bar
horizon. That agrees with the intraday regime result - mean reversion nearly
everywhere - now confirmed one timeframe up. It does not make it tradeable: intraday
reversion was measured at less than the spread, and this label says nothing about
size.

### Two design choices that come from earlier failures here

**Everything is dimensionless.** Returns are divided by the prevailing EWMA true
range, wicks by the bar's own reach, the convolutional input by both the last close
and the true range. The estimator race once had every candidate correlating near 0.57
purely because price-unit quantities were being compared to a price-unit target -
they were all tracking drift in the level. Normalising collapsed them to ~0.30 and
reordered the ranking.

**The band is in true ranges, not basis points.** One threshold then means the same
thing on gold and on the yen, and the same thing in 1974 and 2026.

### The operator's consistency rule is a feature

`run_signed` and `run_has_intent` encode volatility-as-direction: the signed length of
the current run of same-coloured candles, and whether that run contains a candle whose
body is at least one true range. A run without a long candle is drift; a run with one
is intent. This was measured at 1.17x forward movement on real instruments and at
nothing on synthetics, which is the pattern a real effect leaves rather than an
artifact.

## The controls every run reports

1. **Majority-class share**, printed next to accuracy so accuracy cannot be read
   alone. A three-class banded label is 51% flat; 51% accuracy is a model that has
   learned to say nothing.
2. **Balanced accuracy**, the first number that distinguishes a model from a constant.
3. **Edge per call**, net of a 2bp round-trip cost - above the 0.10-1.07bp measured
   spread, to cover the 2-8% stop overshoot measured alongside it. This is the only
   number denominated in money.
4. **A block-shuffled null.** Labels permuted in contiguous blocks, not
   element-wise: overlapping forward windows make neighbouring labels genuinely
   similar, so an element-wise shuffle destroys structure the model can otherwise
   score on and makes the null too easy to clear.
5. **Leave-one-instrument-out.** The control that caught the momentum result when
   clustered errors, parameter robustness, a synthetic control and a shuffled null all
   passed and the effect was still nothing but bitcoin.

No hyperparameter search, deliberately. Tuning against a walk-forward score and then
reporting that score is how a null becomes a finding.

## Where the code is

    research/harness/history.py          any instrument, any source -> gzipped CSV
    research/harness/broker_history.py   the deep pull, run on the research machine
    research/training/candles.py         bars -> features, panel, candle-shape windows
    research/training/labels.py          the six families
    research/training/splits.py          purged walk-forward, embargo, leave-one-out
    research/training/sk_batch.py        scikit-learn: boosted trees, logistic, dummy
    research/training/tf_batch.py        TensorFlow: dense net and 1D convolution
    research/training/requirements.txt   the research-only stack

scikit-learn and TensorFlow are installed in `.venv-research`, not in the desk's
dependencies. The live container has a 2.6GB limit and has been OOM-killed 63 times;
a 247MB TensorFlow wheel has no business in its image, and nothing at runtime imports
any of this.

## Model results

### `banded`, daily, horizon 5, band 1.0 TR - a null

64,854 rows over 10 broker instruments; 24.6% down, 49.6% flat, 25.8% up. Five
purged walk-forward folds, 2bp round-trip cost:

| model    |   acc |   bal | calls | edge/call |     t |
|----------|------:|------:|------:|----------:|------:|
| majority | 0.521 | 0.333 |  0.0% |  +0.00000 |  0.00 |
| logistic | 0.404 | 0.338 | 44.2% |  -0.00062 | -1.57 |
| boosted  | 0.502 | 0.338 |  8.2% |  -0.00022 | -0.19 |

The same pipeline on block-shuffled labels scored balanced accuracy 0.333-0.336 -
**indistinguishable from the real labels at 0.338**. Accuracy of 0.502 is below the
49.6% majority share once rounding is accounted for, so the boosted model is not
beating a constant. Edge is negative for both models and neither t-statistic
reaches 1.6.

Leave-one-instrument-out: **5 of 10 profitable**, which is a coin flip.

This is the seventh independent test to find no directional edge at this desk, and
it agrees with the previous six.

### `triple`, daily, horizon 5 - a null, and crypto again

29 broker instruments held out one at a time. 14 of 29 profitable - a coin flip -
and the ranking is the tell: the best four are `btcusd` (+0.0035), `ethusd.conv`
(+0.0026), `btcusd.conv` (+0.0019) and `jump` (+0.0014). Crypto and a synthetic
jump index at the top is the same signature that turned out to be the whole of the
daily-to-monthly momentum result.

What the model leaned on, by permutation importance on the last fold:
`vol_log_gap` (+0.0105), `range_pos_60` (+0.0058), `ret_20_tr` (+0.0044). The
volatility features outrank every return feature, which is consistent with the
directional question being empty and the magnitude question not being tested here.

### What has not been run yet

`speed` on the deep hourly panel, and the whole of `tf_batch.py`. `speed` is the
one worth the compute: it is unsigned, so it asks whether a move worth taking
arrives at all rather than which way it goes, and the importance ranking above
points the same way. `expansion` is the other, for the reason in `labels.py` - the
desk sizes every position off a *backward* EWMA of true range, and a forward
reading would let it size for the volatility it is about to meet.
