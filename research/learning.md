# Is the kNN buying anything?

`reactions.py` decides every level call. It compares the touch in front of it
with past touches by a **hand-built** Euclidean distance over nine
equally-weighted features, takes the nearest, and votes distance-weighted.

It has never been compared with anything. Which means "the kNN works" has never
been distinguished from "the features work and any model would do" - and that
matters, because they call for opposite responses.

## The bench

Every resolved touch goes to four models, each of which must predict **before**
it is told the answer. All four are asked the same question the kNN is asked -
*which way does price go from here* - because a comparison on a different
quantity is not a comparison.

| model | what it is | what it adds |
| --- | --- | --- |
| `knn` | the incumbent: fixed distance, distance-weighted vote | — |
| `linear` | logistic regression on the same nine features | a baseline, and readable weights |
| `attention` | the same neighbours, weighted by a **learned** distance | drops features that separate nothing |
| `sequence` | an n-gram over price symbols | knows nothing about the level |

The same neighbour set is derived once and handed to `knn` and `attention`
together, so the only difference between them is how they weight it. **The
touch itself is excluded**: it is added to memory during resolution, so it can
appear among its own neighbours at distance zero and hand every model the
answer.

## The result, at a matched sample

    attention   87.8% of 1996   base 52.0%   edge +35.78%
    knn         87.7% of 1996   base 52.0%   edge +35.71%
    up_rate     84.7% of 1995   base 52.0%   edge +32.67%
    linear      84.6% of 1996   base 52.0%   edge +32.61%

Three findings, and they point in different directions:

**The neighbour structure earns its place.** The kNN beats the one-feature
floor by 3.1 points of edge. At n=1996 the standard error on a proportion is
0.75 points and the models are scored on the same touches, so that gap is real.
Something in *which past touches resemble this one* predicts beyond the level's
own record.

**Learning the distance adds nothing.** Attention scores +35.78 against the
kNN's +35.71 - a 0.07 point gap, indistinguishable. Its learned weights are
still all within 0.004 of 1.0 after two thousand touches, which is the model
saying it could not find a metric worth having. The value is in the neighbours,
not in how they are weighted.

**The linear model is the floor.** +32.61 against reading `up_rate` straight
off at +32.67. Logistic regression on nine features matches one feature and no
model, and the weights say why: `up_rate` at +2.29 with nothing else above
0.22. Beyond it, the features carry nothing *linearly*.

Together: the signal is in **local, non-linear** structure - exactly what a kNN
captures and a linear model cannot.

### This reverses an earlier reading

At 442 touches the three models sat within 0.7 points of each other, and when
the floor was added it appeared to beat all of them by 3 points. That was
written up here as "the kNN is not buying anything", and it was wrong.

The cause was a sample mismatch, not arithmetic: `up_rate` was added later, so
it had 394 touches against the others' 776 and a base rate of 55.0% against
their 53.2%. Different touches, different period. The ordering inverted as soon
as the counts converged.

Two things kept it from becoming a bad decision. The comparison was recorded
rather than acted on, and the caveat that the samples were not matched was
written down beside the number at the time. The simplification it seemed to
argue for - drop the neighbour search, read the level's record - would have
cost 3 points of edge on the most important path in the system.

## What to read

**Edge**, not accuracy. 63% accuracy on a problem whose base rate is 63% is a
model that has discovered which answer is commoner, and accuracy alone presents
that as skill. Edge is accuracy minus always guessing the commoner class.

Three outcomes and two of them are useful:

* **the linear model matches the kNN** — the kNN is complexity with no return
  in the most important path in the system, and simplifying is a plain win;
* **both sit at zero edge** — the features do not carry the signal. That is a
  finding about the *features*, and no amount of model fixes it;
* **the kNN wins clearly** — worth knowing, and it would be the first evidence
  for it rather than the assumption it has been.

The third is what happened, and it took a matched sample to see it.

## It also settles a deletion that was queued on a document nobody can read

`prior.md` item 4 and two entries in `docs/todo.md` proposed deleting `Memory`,
`Features.distance` and the kNN outright. All three cited **`similarity.md`**,
"which found the distance orders neighbours no better than random across 13.5M
pairs".

There is no such file. Not in the tree, and not anywhere in git history - so
the 13.5M-pair figure has never been checkable by anyone, and it was standing
as the evidence for removing the model behind every level call.

The claim has now been tested rather than cited. The learned distance below
agrees with the half of it that was right: no reweighting of the nine features
improves the ordering. And the bench above shows the deletion would have been
wrong anyway, because the kNN beats a one-feature floor by 3.1 points on 1,996
matched touches. Both hold together - a metric can order neighbours no better
than chance while the neighbourhood still carries signal, which is a fact about
the *features* being flat rather than about the method.

Those three entries are withdrawn in place rather than deleted, with the reason
beside them.

## The learned distance, and why it is kept rather than removed

`Attention` scores a past touch by `-sum(w_i * (query_i - key_i)^2)`, softmaxes
those into a weighting, and predicts the weighted average. With every `w` equal
it *is* the kNN's distance with a soft edge instead of a hard cut at k, which is
where it starts deliberately: a comparison that starts from noise measures the
training, not the idea.

**It found nothing, and that is a result rather than a failure.** After two
thousand touches its nine weights are all within 0.004 of 1.0 and it scores
0.07 points from the kNN - indistinguishable. It has not drifted, wandered or
collapsed; it has converged on the metric it was given and reported that there
is no better one to find. The value in the neighbour vote is the neighbours,
not how they are weighted.

The case for deleting it is that it is measurement, the measurement is taken,
and it costs a small amount of work on every resolution. That case is real and
it is outweighed by two things:

* **it is a live control.** The claim "the fixed distance is adequate" is
  currently true of nine features on one population. Change the feature set -
  and [horizon.md](horizon.md) argues the population should change too - and
  that claim has to be re-established. An arm already running re-establishes it
  for free; one that was deleted has to be rebuilt and rewarmed first.
* **a converged weight vector is a continuing statement.** Weights at 1.0 today
  and 1.4 next month would be the model saying the distance had started to
  matter, which is exactly the kind of drift nothing else here would notice.

So it stays, and this section is the record of what it found, so nobody has to
re-run it to know.

## How the learned distance works

`Attention` scores a past touch by `-sum(w_i * (query_i - key_i)^2)`, softmaxes
those into a weighting, and predicts the weighted average. With every `w` equal
it *is* the kNN's distance with a soft edge instead of a hard cut at k, which is
why it starts there: a comparison that starts from noise measures the training,
not the idea.

The weights then move by gradient on the prediction error, so a feature that is
large exactly where the neighbours disagree with the outcome loses weight. Its
`importance()` is the answer to "which of these nine features decides who the
neighbours are", which the neighbour vote structurally cannot report.

The temperature is learned too, which retires a constant: a high temperature
averages over everything (the base rate) and a low one attends to the single
nearest touch (1-NN), so "how many neighbours" stops being a number somebody
chose.

## Level embeddings

`Embedding` gives each level a vector, nudged toward a direction when it holds
and away when it breaks. Two levels end up near each other when they have
**behaved** alike, which is a different claim from being **described** alike -
the hand-built features say what a level looks like.

The limitation is the same as the idea: a level with two touches has a vector
made of two nudges. `similar()` refuses to rank anything below three, because
returning it beside a vector made of forty would make them look like the same
kind of claim.

## Sequences

`patterns.py` already asks "has this shape happened before" and answers with
dynamic time warping - a *continuous* comparison. That is the right tool for
"is this the same shape" and the wrong one for "what comes next", because a
continuous space has no next.

So legs between turning points are discretised into symbols by direction and
size in volatility units - `U1`, `D3`, `F` - a finite vocabulary derived from
the series rather than clustered into existence, and scale-free by construction:
`U2` means the same thing on gold and on eurusd.

Then it counts. Given the last k symbols, what followed? No gradient, no
parameters, and no capacity to memorise. **Backoff** is the only machinery: ask
the longest context with at least `MIN_COUNT` observations and shorten until
one qualifies, because without it the model is silent exactly where it is most
confident and loud where it has three examples.

Contexts are ranked by **t**, not by mean. The largest means belong to the
rarest contexts by construction, so a list of them is a list of small samples.

This is not a language model and the resemblance should not be oversold. What
carries over is the framing - a sequence over a finite vocabulary with a backoff
n-gram baseline - and the reason to start there is that the baseline is what
anything more elaborate has to beat, and nobody has established it here.

## The returns estimator

The one model here that predicts price rather than a level: forward return over
`HORIZON` bars, in volatility units, from market and policy state.

It exists to make the null a **measurement**. A walk-forward R² near zero is the
efficient-market answer arriving as evidence rather than as an assumption, and
the same estimator would report a non-zero one if there were one.

It is deliberately built to fail the trick every "predict the gold price"
tutorial passes: regress tomorrow's *price* on a moving average of today's and
report 99% R². A random walk's level is almost entirely explained by its own
recent average, so that number is an identity, not a finding - it survives being
wrong about everything that matters. Target the **return** and the trick scores
nothing.

For levels it is a second opinion built from something else entirely: the state
of the market and of policy, rather than the history of one price. Where it
agrees with the kNN there is more behind the call than either provides alone;
where it disagrees, that is worth knowing before sizing.

## Everything here decides nothing

All of it publishes numbers beside the incumbent's and the record settles it.
That is not caution for its own sake - it is the only arrangement in which a
negative result is as useful as a positive one, and on this evidence a negative
result is the more likely.
