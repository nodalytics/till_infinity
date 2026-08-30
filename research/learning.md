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

## First result: 442 touches

    attention   72.4% of 442   base 50.6%   edge +21.79%
    knn         72.0% of 442   base 50.6%   edge +21.41%
    linear      71.7% of 442   base 50.6%   edge +21.05%

**The three are within 0.7 points of each other.** At n=442 and p=0.72 the
standard error of a single proportion is 2.1 points, so the spread between them
is well inside noise even before allowing that they are scored on the same
touches. On this evidence the kNN is not buying anything a logistic regression
on the same nine features does not already provide - which is the first of the
three outcomes below, and the one that says simplify.

The weights say why:

    up_rate        +0.9414
    depth_vol      -0.3377
    approach_vol   +0.3150
    backcheck      +0.2649
    regime         +0.1995
    experience     -0.0871

`up_rate` - the level's own record of which way its previous same-side touches
went - is worth nearly three times the next feature. Everything else is small.
That is the model independently rediscovering what research/features.md found
by hand: none of the other eight predicts direction once side is known.

The learned distance kept `depth_vol` at 1.0 and pushed the rest toward zero,
which is the same finding arriving from the other direction - if only one
feature separates outcomes, the *distance* between touches barely matters.

### So the next measurement is the floor, not a better model

If reading `up_rate` straight off scores what all three score, then eight
features and the entire neighbour machinery are earning nothing. That is a
one-line comparison and it is now in the bench as `up_rate` - no model at all,
just the feature. It is the number the other three have to beat, and until they
beat it none of them has demonstrated anything.

Caveats, stated because the result is a strong one on a small sample: 442
decayed touches, one snapshot taken shortly after a cold start, and every
learned model still moving. `up_rate` is point-in-time by construction -
`features_for` runs before `Tracker.begin`, so a touch is not in its own
denominator - which is the one way this number could have been an artefact and
is not.

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

## The learned distance

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
