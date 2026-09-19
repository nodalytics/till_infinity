# The model is right on a timescale the desk does not trade

The bench's accuracy climbed from ~72% to ~87% while the base rate held near
52%. That looked like learning. It is mostly the sample.

Split the same predictions by **how long the touch took to resolve** - the
floor (`up_rate > 0.5` predicts the push direction), scored on 52,238
resolutions the journal already held:

| held for | n | accuracy | base | edge |
| --- | --- | --- | --- | --- |
| 0–2s | 944 | 98.1% | 70.1% | +27.97% |
| 2–10s | 1,411 | 98.4% | 68.5% | +29.91% |
| 10–60s | 7,836 | 97.8% | 54.7% | +43.11% |
| 60–300s | 19,820 | 97.4% | 51.8% | +45.57% |
| **300–1,800s** | 8,572 | **66.6%** | 50.8% | +15.83% |
| **beyond 1,800s** | 1,326 | **53.2%** | 53.2% | **+0.00%** |

**The edge is exactly zero at thirty minutes and beyond**, and `max_hold` is
1,800 seconds. The horizon at which the model knows nothing is the horizon the
desk trades.

## Why the short buckets score 97%

They are not predictions. A touch resolving in ninety seconds is a slice of a
move already in progress, and consecutive slices at one level agree with each
other because they are the same move counted several times. The base rate
confirms it: 70.1% at 0–2s against 51.8% at 60–300s - the outcomes themselves
are lopsided there, which is the signature of one push producing several
same-direction touches rather than of several independent events.

`up_rate` is the share of this level's previous same-side touches that pushed
up. Where touches are clustered in time, that is a reading of the last few
minutes, and the next touch continues it. Real, worthless, and 97% accurate.

## What it costs to have missed this

Everything scored on the pooled population is scored on a mixture that is 96%
sub-five-minute touches. That includes the model bench in
[learning.md](learning.md): the kNN beating the one-feature floor by 3.1 points
is a fact about a population the desk does not trade, and says nothing yet
about whether it beats the floor on a thirty-minute horizon.

It is also consistent with the account. `research/stops.md` found 20 of 27
stopped trades never reached their target, and the desk is at -688 excluding
the sizing-bug outlier. A model that is right about the next ninety seconds and
neutral about the next thirty minutes produces exactly that: good-looking
signals, trades that do not work.

## What this does not say

That the level machinery is worthless. It says the **evidence for it** has been
gathered on the wrong population, and that the honest number for a
thirty-minute horizon is +0.00% on 1,326 resolutions - which is a small sample
and a real result, not a proof of nothing.

Two things follow, and neither is "turn it off":

* every model score in this repository should be reported **per horizon
  bucket** rather than pooled, starting with the bench;
* the interesting question is whether anything at all separates at 1,800s.
  Nothing here has ever been asked that, because the pooled number always
  looked good enough not to.

## A defect found on the way

**14,140 of 52,238 resolutions have a negative duration** - resolved before
they began. Median -94 seconds, minimum -660, none positive. Those rows were
excluded from the table above.

That is 27% of the record, and the shape fits a mixed clock: a touch begun from
a quote at wall-clock time and resolved from a bar stamped with the bar's
*open*, which is up to one interval in the past. -660 is consistent with a 15m
bar. The same class of error as the two timestamp bugs this project has already
found.

Anything that reads `seconds` off a resolution - hold estimates, the reach
book, this document's own buckets - was reading a quarter of its input
backwards.

**Fixed.** `Tracker._live` now refuses an observation stamped earlier than the
touch it would advance. Refused rather than clamped: the bar's range is
evidence about a period before the touch began and says nothing about what the
touch did, so clamping would keep the outcome and lie about its length. The
touch stays open and the next observation resolves it properly. `_close` and
`expire` carry a `max(when, started)` backstop for the paths that do not go
through `update`.

It had been fixed twice before in `observe_bar`, which is why the third
attempt is at the consumer rather than the producer: a bar cannot know what
touches a quote opened after its close, and the tracker can.

## Confirmed by the live bench, 2026-08-31

The prediction this document made was that every model would fall to zero edge
beyond thirty minutes. Measured by the bench, cut by realised duration:

| resolved in | n | knn | attention | up_rate | linear | base |
| --- | --- | --- | --- | --- | --- | --- |
| 0–60s | 37 | +43.19% | +43.19% | +24.23% | +24.23% | 51.4% |
| 60–300s | 403 | +37.19% | +37.18% | +33.81% | +31.42% | 51.4% |
| 300–1,800s | 325 | +15.89% | +15.87% | +9.98% | +9.61% | 50.7% |
| **beyond 1,800s** | **150** | **−2.03%** | **−2.03%** | **−0.01%** | **−1.43%** | 59.1% |

**Every model is at or below zero past thirty minutes**, and `max_hold` is
1,800 seconds. The edge decays monotonically as the population stops being
definitional - +43 under a minute, +37 to five, +16 to thirty, nothing beyond.

Three readings, kept separate because they are different claims:

* **The kNN's advantage is real and lives entirely in the fast population.** It
  leads by 3 to 19 points in every bucket up to thirty minutes and then goes
  negative with everything else. So [learning.md](learning.md)'s "the kNN beats
  the floor by 3.1 points" was true and was measured on the tautology - the
  argument for deleting it and the argument for keeping it were both about the
  wrong sample.
* **kNN and attention are identical to two decimals in all four buckets**, a
  fourth independent confirmation that the learned distance finds nothing.
* **−2% is "no edge", not "anti-edge".** On 150 observations that is inside a
  standard error of zero. What it is emphatically not is the +25% the pooled
  figure showed.

### Re-read an hour later, on roughly twice the sample

| resolved in | n | knn | attention | up_rate | linear | base |
| --- | --- | --- | --- | --- | --- | --- |
| 0–60s | 56 | +42.07% | +42.07% | +28.04% | +28.04% | 52.7% |
| 60–300s | 664 | +38.87% | +38.86% | +35.80% | +33.25% | 52.2% |
| 300–1,800s | 484 | +16.44% | +16.83% | +10.96% | +10.54% | 50.7% |
| **beyond 1,800s** | **196** | **−8.08%** | **−8.08%** | **−5.54%** | **−7.62%** | 61.8% |

The shape holds and sharpens: +42 → +39 → +16 → below zero, now over about
1,400 observations.

**The slow bucket looks worse and mostly is not.** Its base rate moved from
59.1% to 61.8%, and edge is accuracy minus base rate, so a sample becoming more
imbalanced pushes edge down mechanically. Accuracy itself only fell from 57.1%
to 53.7%. At n=196 and p≈0.54 one standard error is about 3.6 points, so −8.08%
is roughly two of them from zero - leaning harder than the first reading, still
short of "reliably wrong". **No demonstrated edge** remains the honest phrasing.

**kNN and attention are identical to two decimals in all four buckets again**,
which is the fifth independent confirmation that the learned distance finds
nothing.

### The bucket worth chasing - and it was worth chasing

**Followed up in [paying.md](paying.md).** The edge is real: the synthetic null
scores 47% in this band where real instruments score 70%, so it is not an
artefact of the method. Eleven of twenty-six instruments clear their own
spread, and gold and spx500 clear it by an order of magnitude over the next
tier.


`300–1,800s` is the one number here that is unambiguously real: +16.44% on 484
observations is about 4.5 standard errors. It sits between the tautology and the
hold - too slow to be the definition of a rejection, too fast to be the horizon
`max_hold` trades.

That makes it the interesting place to look, and it frames the choice in front
of the desk more usefully than "shorten the hold or give up": there is a
measured edge at five to thirty minutes, and the question is whether it
survives the spread. See [catalogue.md](catalogue.md) - the cost to cross runs
from 0.170v on a synthetic to 2.267v on FX, and an edge that cannot pay 2v is
not an edge on those instruments.

### What it means for the desk

**There is no demonstrated directional edge at the horizon this system
trades.** The 120 closed trades netting −688 are consistent with that rather
than with bad execution - the stop work, the entry geometry and the
reward-to-risk arithmetic were all improving the execution of calls that carry
no measured information at thirty minutes.

Two responses, and neither should be taken before the next measurement:

1. **Shorten the hold to where the edge is.** If the model is right at 60–300s,
   a 1,800s hold is three to thirty times longer than the signal supports.
2. **Or treat the slow horizon as unsolved**, and the current strategies as
   unvalidated until something separates at 1,800s.

The measurement that should come first: the 60–300s bucket has +37% edge and is
also where cost bites hardest relative to the move. `charge_spread` already
deducts the quoted spread, and [catalogue.md](catalogue.md) puts it at 0.170v
on a synthetic against 2.267v on FX. Whether a +37% directional edge survives
that is answerable from the same data, and decides whether shortening the hold
is an opportunity or a faster way to pay the spread.

## Where the evidence actually comes from

Levels are spread evenly across timeframes and touches are not:

| interval | series | levels | touches |
| --- | --- | --- | --- |
| 1m | 53 | 542 | 5,713 |
| 5m | 53 | 343 | 1,744 |
| 15m | 53 | 252 | 1,006 |
| 1h | 52 | 241 | 548 |
| 1d | 46 | 251 | 361 |
| 1w | 43 | 269 | 542 |

55.6% of levels sit on 15m or slower, and the fast end supplies most of the
touches anyway. So the population problem is not that the higher timeframes are
missing - they are there and forming - it is that they resolve rarely, and a
pooled score is dominated by the interval that resolves most.
