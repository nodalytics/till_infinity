# Does the distance order neighbours better than chance?

This document was cited three times - `research/prior.md` item 4 and two
entries in `docs/todo.md` - as the evidence for deleting `Memory`,
`Features.distance` and the kNN. **It did not exist**, in the tree or anywhere
in git history, so the figure attributed to it ("no better than random across
13.5M pairs") had never been checkable by anyone while standing as the case for
removing the model behind every level call.

This is the measurement it should have been. Harness:
[`harness/similarity.py`](harness/similarity.py), over 66,068 resolved touches.

## The question

The kNN's premise is that a **near** touch is better evidence about this one
than a **far** touch. That is a claim about ordering and it is testable without
reference to any model: take pairs of resolved touches on the same side, and
ask whether the pairs the metric calls close agree about direction more often
than the pairs it calls distant.

Scored as AUC of `-distance` predicting agreement, beside a control that
shuffles the distances. The control returns 0.4985–0.5084 throughout, which is
what says the routine measures anything at all.

## What it says

| population | touches | AUC | shuffled | pairs agreeing | nearest tenth | farthest tenth |
| --- | --- | --- | --- | --- | --- | --- |
| pooled | 66,068 | 0.4625 | 0.5003 | 87.3% | 84.7% | 89.6% |
| 0–60s | 30,118 | 0.7240 | 0.4985 | **100.0%** | 100.0% | 99.9% |
| 60–300s | 23,484 | 0.5935 | 0.5084 | **99.5%** | 99.7% | 99.1% |
| 300–1,800s | 10,704 | **0.4921** | 0.5000 | 56.2% | 55.0% | 55.2% |
| beyond 1,800s | 1,762 | **0.5120** | 0.5019 | 50.0% | 51.7% | 47.0% |

**The missing document was right where it matters.** At 300–1,800s the AUC is
0.4921 and the nearest tenth of pairs agree 55.0% against the farthest tenth's
55.2% - flat. Beyond 1,800s it is 0.5120 on 1,762 touches, inside noise. At
every horizon the desk actually trades, the metric orders neighbours no better
than shuffling it.

## The fast buckets are not evidence for it - they are a tautology

100.0% agreement is not a strong result, it is an impossible one, and chasing
it is what this measurement is for. Split the same touches by side:

| held for | side above → up | side below → down |
| --- | --- | --- |
| 0–60s | **100.0%** (n=7,649) | **100.0%** (n=22,473) |
| 60–300s | 99.7% (n=12,157) | 99.8% (n=11,344) |
| 300–1,800s | 68.9% (n=5,086) | 66.4% (n=5,627) |
| beyond 1,800s | 52.8% (n=830) | 50.1% (n=932) |

A touch approached from above that resolves inside a minute resolves *upward*.
That is not a prediction, it is what "rejection" means - the label is the
definition. So within a side every fast pair agrees, there is nothing left to
order, and an AUC computed on the handful of disagreements is noise wearing a
number.

By thirty minutes `side` gives 52.8% and 50.1%. The tautology has dissolved and
what is left is a coin.

## What this explains

One fact, showing up in four places that were each treated as separate:

* [features.md](features.md) - "`side` alone matches all nine features
  together". Of course: at the horizons that dominate the sample, side *is* the
  answer.
* [learning.md](learning.md) - every model scoring 84–88% with a base rate near
  52%. They are all reproducing the definition of a rejection.
* the kNN's 3.1-point edge over a one-feature floor, on the same pooled
  population, which this shows cannot be read as evidence about the metric.
* [horizon.md](horizon.md) - +45% edge inside five minutes and **+0.00%**
  beyond thirty, which is the same boundary from the other side.

## Why the deletion is still not warranted

Two things are true at once and only one of them was cited.

The metric orders neighbours no better than chance **at tradable horizons**.
That is confirmed. It does not follow that the kNN can be deleted, because the
alternative was never measured on that population either: the one-feature floor
that appeared to beat it and the model that appeared to beat the floor were
both scored on the tautology.

What follows is narrower and more useful: **nothing here has yet been measured
on the population the desk trades.** The deletion, the retention and the
learned distance are all arguments about a sample where the answer is written
into the question.

## The design flaw this exposes

`Memory` pools touches across intervals. A 1w touch borrows its neighbours from
a population that is 46% sub-minute touches whose direction is definitional -
so the evidence a slow touch learns from is drawn overwhelmingly from a regime
where the label is not a prediction.

That is not a scoring artefact that better reporting fixes. It is in the
training set. A model asked to predict a coin flip, given neighbours drawn from
a population where the answer is free, will learn the free answer.
