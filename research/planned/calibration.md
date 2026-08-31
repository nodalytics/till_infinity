# Calibration

Does 80% mean 80%.

[todo.md](../../docs/todo.md) item 3 names this as one of three things standing between a
good model and a decision, and it is the first of the three because the other
two consume it. Sizing reads a probability. A rule that stakes more on a 70%
call than a 55% one is only sane if 70% happens seventy times in a hundred; if
the model says 70% and is right 55% of the time, the sizing rule is not
conservative or aggressive, it is *wrong in a direction nobody can see*, and it
will be wrong most confidently exactly where it stakes most.

Nothing here is built. This says what to measure, against which fields, what
would falsify a claim of good calibration, and - the part most likely to be got
wrong - why the obvious fix makes the model worse while making the number
better.

## 1. What the existing numbers cannot see

[`facto.Report`](../till_infinity/structures/facto.py) reports MAE against two
baselines, which is the right discipline for the quantity it scores. It scores
`push_vol`: how far price went, in volatility units. MAE is an average distance
and every probability in this system is invisible to it.

Look at what `evaluate` actually does with the levels model:

```python
if example.predicted is not None:
    levels.update(example.target, example.predicted)
```

`example.predicted` is `expected_push_vol`. So the levels model is graded on the
**size** of its call and never on the **confidence** of it.
`Inference.probability_up` - the number `actionable` gates on through `edge`,
the number the alert prints, the number a sizing rule would consume - is scored
nowhere in this project. Not by MAE, not by either baseline, not by
`Report.direction`.

`Report.direction` looks closest and is not it. It is the share of pushes whose
**sign** the FM called right, against always guessing the commoner way. That is
accuracy at a single threshold, and accuracy and calibration are independent:

- a model that says 99% on everything and is right 99% of the time is accurate
  and calibrated;
- a model that says 99% on everything and is right 70% of the time is accurate
  and badly calibrated - the sizing rule bets the farm on each one;
- a model that says 51% on everything and is right 51% of the time is barely
  better than a coin and **perfectly calibrated**.

The third case is the one to keep in mind, because it is where shrinkage pushes
this system and because it scores beautifully on the metric people reach for
first. See §6.

## 2. What the claim is, and what checks it

A probability needs a matched realised frequency, and the match has to be exact
about what was claimed and about what happened.

**The claim** is `probability_up` on the entry that made the call. **The
outcome** is `push_vol > 0` on the entry that judged it. They live in different
journal rows, joined by `parent`.

| | |
|---|---|
| claim | parent `context["probability_up"]` |
| outcome | child `context["push_vol"] > 0` |
| join | child `parent` → parent `id` |
| when | child `time` - the resolution, not the call |
| instrument | parent/child `tags[0]`, per `cli.FEED_TAGS` |
| timeframe | child `context["interval"]` |

Three things about that pairing are load-bearing.

**`probability_up`, not `probability` and not `confidence`.** All three exist
and only one is a claim about the up/down label the outcome records.
`probability` flips to face the claimed direction, so pairing it with
`push_vol > 0` compares a down-facing number against an up-facing label - the
exact shape [levels.md](../../docs/levels.md) §7 says is "not a comparison". Worse,
`confidence` on the journal row is not a probability at all: `emit` passes
`confidence=min(1.0, signal.score)` and `score` is `abs(edge)`. A local decision
row reads `confidence 0.102` beside `probability_up 0.028`. Anyone calibrating
the column named `confidence` would be calibrating the edge magnitude and
getting a coherent-looking curve out of it. `probability_up` is also what the
journal and `facto` are keyed on and what [levels.md](../../docs/levels.md) §7 promises will
not change meaning, so it is the one field here with a stability guarantee.

**Both parent kinds carry it.** `decide` writes `**signal.features`, which
includes `probability_up`; `observe` writes `**inference.to_dict()`, which
includes it too. So the calibration sample is *every* level call, actioned or
not - which is the whole reason `_watch_calls` journals observations. Only about
one call in forty-three has ever cleared `|edge| >= 0.08`
([levels.md](../../docs/levels.md) §8, measured pre-fix), so a curve built from decisions
alone would be built from a two-percent tail. Build it from everything, and
report the tail separately - see §3.

**"Up" means the resolution rule, not the clock.** The outcome is written by
`Tracker._close`, which resolves at 1.5 volatility units either way, calls a
break provisional until it survives `TRAP_WINDOW`, and records chop at the
horizon. So `probability_up` is a claim about *how this interaction resolves
under that rule* and about nothing else. Change `resolve_vol` or `horizon` and
every historical claim is calibrated against a label that no longer means the
same thing - the same class of invalidation as the touch-count boundary in §4,
and a reason to record the tracker's settings beside any calibration run.

### The tie the label hides

`push_vol` is the signed distance at the moment of closing, and `> 0` splits it.
For a `reject` at 1.5v the sign is emphatic. For a `chop` - price arrived, sat,
and did nothing until the horizon - the sign is the sign of a small number, and
on the stored history chop was 74.3% of outcomes ([levels.md](../../docs/levels.md) §7b).
Those rows are not mislabelled, but their labels are close to coin flips no
model could call, and they set a floor on the Brier score that has nothing to do
with the model.

Do not drop them. `chop` is kept deliberately, because a model never shown
"nothing happened" predicts a move every time, and the model does not get to
decline the small ones at call time either. Report instead a **second** curve
restricted to `|push_vol| >= resolve_vol`, clearly labelled as the
decisive-outcomes-only view, and never as the headline. If the two curves
disagree, the interesting sentence is which rows the model is confident about
rather than either curve alone.

## 3. What to measure, and what is ceremony

Four candidates. Two earn their place, one earns a footnote, one is ceremony
when reported alone and a trap when reported as a target.

### The reliability curve - the artefact, not a summary of it

Bucket the calls by claimed `probability_up`, and in each bucket plot the mean
claim against the realised up-rate. Perfect calibration is the diagonal.

It stays first because it is the only one of these that says *where* the model
is wrong, and where is the whole question. Over-confidence at the extremes and
good behaviour in the middle is a different defect from a uniform slope error,
and they want different responses. Every scalar below compresses this curve into
one number and therefore cannot distinguish them.

**Fixed-width deciles for the reported curve**, not equal-count buckets, even
though the claims are nowhere near uniform. Fixed edges are reproducible, they
are comparable between two runs and between two instruments, and they are
computable incrementally from three counters per bucket. Equal-count buckets
move their own edges as data arrives, so two runs are not comparable and the
edges are themselves an estimate. Report equal-count buckets beside them if the
decile picture is too sparse to read, and say which is which.

**Three counters per bucket** is the whole implementation: `n`, `sum(p)`,
`sum(y)`. Everything in this section falls out of those plus the global counts,
folded one call at a time and keeping nothing - the same shape as
`facto.evaluate`'s single pass and as the streamed `Window` in
[agents.md](../../docs/agents.md).

**When data is thin**, decline rather than draw. The precedent is
`facto.MIN_EXAMPLES`: below the count it reports the count and stops, because a
number produced from too little is noise wearing a decimal point. A reliability
curve is worse than a scalar here, because a bucket with four calls in it draws
a *point* that looks exactly like a bucket with four hundred. Suppress buckets
under a floor rather than plotting them faint, and print the counts beside the
curve always. §5 has the harder version of this problem: `n` is not the sample
size.

### Brier score, which is already in the box

The mean squared error of the probability against the 0/1 label. `river` has no
`BrierScore`, and does not need one: `metrics.MSE().update(1.0 if up else 0.0,
p)` **is** the Brier score, exactly, and `metrics.MSE` is already imported
alongside `metrics.MAE` in `facto`. Verified locally against a hand-rolled
mean-of-squares on 20,000 synthetic pairs; identical to five decimals.

It earns its place as the single headline number because it is a *proper*
scoring rule: it is minimised by quoting your true belief, so a model cannot
improve it by hedging. And it is directly comparable against the one baseline
that matters here - always quoting the base rate, which scores exactly
`ȳ(1 − ȳ)`. A model whose Brier score does not beat that has produced no usable
probability at all, whatever its reliability curve looks like. That is the same
"two baselines, always" instinct as [structures.md](../../docs/structures.md), applied to a
different quantity.

### The decomposition, which is the part that stops the cheat

Brier partitions into reliability, resolution and uncertainty ([Murphy
1973](https://journals.ametsoc.org/view/journals/apme/12/4/1520-0450_1973_012_0595_anvpot_2_0_co_2.xml)):

```
Brier  =  REL  -  RES  +  UNC

REL = (1/N) Σ_k n_k (p̄_k - ȳ_k)²      how far each bucket sits off the diagonal
RES = (1/N) Σ_k n_k (ȳ_k - ȳ)²        how far the buckets separate from each other
UNC = ȳ (1 - ȳ)                        the base rate's own variance - not ours to move
```

All three come from the same three counters. This is the reason to report a
decomposition rather than a bare score: **reliability alone is minimised by a
model that says nothing.** Quote the base rate on every call and `REL` is
identically zero, `RES` is identically zero, and Brier equals `UNC`. Perfectly
calibrated, perfectly useless, and top of the leaderboard on any calibration
metric read in isolation.

`RES` is what stops that. It is the only term that rewards the model for
distinguishing one call from another, and it is untouched by shrinkage in the
sense that matters - see §6. So the pair to watch is `REL` against `RES`, and
the honest verdict sentence is of the form *"miscalibrated by X, informative by
Y"*, never one without the other.

**One caveat, because it will otherwise be quietly wrong.** The identity is
exact when every claim inside a bucket is the same number. With ranges there is
a residual of the order of the within-bucket spread of `p`: on synthetic uniform
claims over ten deciles the gap between `Brier` and `REL − RES + UNC` came to
about 0.001 against a Brier of 0.167. Small, and it is not zero, and a run that
prints the three components without printing the residual is asserting an
identity it has not checked. Print `Brier − (REL − RES + UNC)` as a fourth
number; if it grows, the buckets are too wide for the spread inside them.

### Expected calibration error - ceremony alone, a trap as a target

ECE is the n-weighted mean of `|p̄_k − ȳ_k|` across buckets ([Guo et al.
2017](https://proceedings.mlr.press/v70/guo17a/guo17a.pdf)). It is one line, it
is already implied by the counters, and printing it costs nothing.

It does not earn a place as a *target*, for two reasons.

It is the same quantity `REL` already reports, in an absolute-value form that
does not decompose, so it adds no information to a run that reports the
decomposition - and if it is reported without `RES` beside it, it is gameable in
exactly the degenerate way above. Zero ECE is what a model that has stopped
saying anything looks like.

And the binned estimate is biased. The bias accumulates across bins and gets
*better*-looking with fewer bins ([Kumar, Liang & Ma
2019](https://proceedings.neurips.cc/paper_files/paper/2019/file/f8c0c968632845cd133308b1a494967f-Paper.pdf)),
so the number moves with a presentation choice. That is tolerable for a
diagnostic and disqualifying for a threshold.

Print it. Never gate on it.

### Not worth building here

**Log loss.** `river.metrics.LogLoss` exists and is proper, but it is dominated
by its tail - one confident miss can outweigh a hundred ordinary calls - and it
does not decompose into anything a person can act on. Brier answers the same
question with a bounded contribution per call and a partition that names the
defect. The shrinkage in §6 means `probability_up` never actually reaches 0 or 1
so log loss would not diverge, but "would not divide by zero" is a weak reason
to carry a second scoring rule.

**ROC AUC as a calibration number.** It cannot be one. AUC depends only on the
*ranking* of the claims, so it is unchanged by any strictly monotone
recalibration - halve every probability and the AUC is identical. It answers a
genuinely useful and different question, "is there any signal here to
calibrate", and it is worth reporting exactly once, at the top, as the
precondition. Note when you do that `river`'s implementation is an
approximation over discretised thresholds - ten by default, and its own
docstring shows ten thresholds returning 0.875 where the true answer is 0.75.
Raise `n_thresholds`, and do not quote the last decimal.

## 4. The boundary, and a join that quietly straddles it

The journal is contaminated before 2026-08-14. Inflated touch counts made a
level's history and its next outcome the same price move counted twice, and the
pre-fix data therefore calls direction correctly **99.9%** of the time at
essentially every level of `|edge|`, against ~78% for independent series with
those marginals ([levels.md](../../docs/levels.md), "The attempt to derive it").

For calibration this is not a degradation, it is an inversion. A model whose
claims are near 0 or 1 and whose outcomes agree 99.9% of the time will produce a
reliability curve **hugging the diagonal at both ends**, a tiny `REL`, a large
`RES` and a Brier score close to zero. Contamination here does not look like
noise. It looks like the best-calibrated forecaster anybody has ever built.

So: every calibration run takes a `since`, there is no default, and the boundary
belongs beside the numbers in whatever is printed. This is the same argument as
`facto.fit(since=)` and [structures.md](../../docs/structures.md)'s "Examples have an
expiry", and the same alarm is worth keeping: a near-perfect calibration report
is what this class of contamination looks like from outside, and it would
otherwise read as a triumph.

**One detail to get right that `facto.dataset` currently does not.** It applies
`since` to the rows and *then* builds the id index:

```python
rows = jr.read(journal_db, limit=limit)
if since:
    rows = [entry for entry in rows if entry.time >= since]
by_id = {entry.id: entry for entry in rows}
```

A call made before the boundary whose touch resolved after it loses its parent,
because the parent was filtered out before the index was built. For `facto` that
costs the levels-model comparison on those rows and the example survives, since
its features come from the outcome. For calibration it costs the **example
itself**, because the claim only exists on the parent. With a one-hour horizon
the affected window is bounded, but the loss is one-sided and it presents as
missing data rather than as a filter. Filter on the outcome's time; resolve
parents against everything.

## 5. Why a pooled curve is one instrument's afternoon

Outcomes accumulate at roughly **895 per hour** and are severely concentrated:
of the last 5,000, `sol` alone accounted for 2,430, and 3m and 5m for 4,305
between them, against 10 on 4h and none on the daily or weekly
([todo.md](../../docs/todo.md) item 0). Two hundred consecutive outcomes arrive in a median
of 4.9 minutes.

Three consequences for a reliability curve, in increasing order of how badly
they mislead.

**`n` is not the sample size.** `facto` already says why, about a different
model: "two touches at the same level minutes apart are nearly the same
observation". A decile bucket holding 900 calls may hold thirty independent
episodes. Binomial error bars on that bucket are too tight by roughly the square
root of the cluster size, which is the difference between a point that sits off
the diagonal by more than noise and one that does not - which is to say, the
entire question. Report `n` **and** the number of distinct `(feed, interval,
level_price)` triples in the bucket. `river.sketch.NUnique` does that in bounded
memory if the exact count gets expensive.

**A pooled curve can sit on the diagonal while every stratum misses it.** Two
instruments miscalibrated in opposite directions average to something that looks
correct, and the average is not a property of the model - it is a property of
how much of each instrument happened to be in the window. The rule is the one
this project already applies to base rates: never report the pooled curve
without the per-`(feed, interval)` curves beside it, and treat a pooled curve
that is better than all of its strata as evidence of pooling rather than of
calibration.

**And the pooled curve is mostly one afternoon of sol on 3m.** Weight per
stratum rather than per row for the headline number - equal weight to each
`(feed, interval)` with enough calls to qualify - and print the row counts so
the reader can see what was reweighted. A model of everything that is 49% one
instrument is a model of that instrument with a wide title.

**Blocking, and what needs a batch pass.** The honest error bars here come from
a block bootstrap over contiguous time blocks, which needs the sample retained
and resampled - a batch pass, and the only thing in this document that is not
foldable. That is acceptable for a periodic report and not for anything on the
live path. The incremental substitute is to keep the counters **per time block**
as well as pooled - hour buckets are natural given the arrival rate - and report
how much the curve moves between blocks. It is a weaker statement than a
confidence interval and it is computable while the service runs, and instability
across blocks is the thing you most want to catch anyway (see §7).

## 6. Shrinkage buys calibration with sharpness, and someone will overpay

`probability_up` is not a raw frequency. It is shrunk twice, deliberately: the
kNN prior toward the Jeffreys-smoothed base rate by neighbour count, and the
level's own beta-binomial toward that prior by `PRIOR_WEIGHT`, with the base
rate itself shrunk toward the pooled rate by `BASE_WEIGHT`
([levels.md](../../docs/levels.md) §7, "Certainty the evidence cannot support"). Every one
of those pulls confident claims toward the middle, and every one of them was
added for a reason that has nothing to do with calibration - three touches that
all went up is not 100%.

The consequence is that this system already has a dial that trades one desirable
property for another, and calibration is the property it improves. **Shrinking
harder will almost always make the calibration number better, up to a point, and
will make the model less useful the whole way.** Raise `PRIOR_WEIGHT` far enough
and every call is the base rate: `REL` is zero, ECE is zero, the reliability
curve is a single point sitting exactly on the diagonal, and the model has
stopped saying anything. It would pass any calibration test written carelessly,
and `actionable` would never fire again because `|edge|` would be zero - the
model would be *reported as improved and be silent*, which is precisely the
failure mode [handoff.md](../../docs/handoff.md) warns about under "correct silence and
broken silence are indistinguishable".

The shape of the trade, measured on synthetic data to check the direction rather
than to claim a result: taking an over-confident forecaster and shrinking its
claims toward 0.5 by a factor `w`, reliability improved sharply from `w = 1.0`
to about `w = 0.6`, then **got worse again** as over-shrinkage turned
over-confidence into under-confidence; resolution held roughly flat while the
buckets still separated and then collapsed with them; and at `w = 0` reliability
and resolution were both exactly zero with Brier equal to the uncertainty term.
Three things worth taking from that. There is an interior optimum, so "shrink
more" is not monotonically better even for calibration. Under-confidence is
miscalibration too and shows on the curve as a slope above one. And the
degenerate endpoint scores perfectly on reliability alone, which is why §3
insists on the decomposition.

The discipline this suggests is one sentence, and it is the standard one:
**maximise sharpness subject to calibration** ([Gneiting, Balabdaoui & Raftery
2007](https://rss.onlinelibrary.wiley.com/doi/abs/10.1111/j.1467-9868.2007.00587.x)).
Calibration is a constraint to satisfy, not a quantity to maximise. Concretely,
for this repo:

- **Never move `PRIOR_WEIGHT`, `BASE_WEIGHT` or `DEFAULT_K` on a calibration
  number alone.** Those constants exist to stop the model claiming certainty it
  has not earned, and they are already load-bearing for `edge` and therefore for
  whether the channel speaks at all. A change to them must report `RES` and the
  actionable-call count beside `REL`, and a change that improves `REL` while
  reducing either is a regression being reported as a fix.
- **Sharpness is the spread of the claims**, and it is one number worth printing:
  the standard deviation of `probability_up`, or equivalently how many of the ten
  deciles are occupied. A run where six deciles were occupied last month and two
  are occupied this month has lost sharpness, whatever else improved.
- **The base rate moves too**, and it moves the claims with it. `edge` is
  `conditional − base`, and [levels.md](../../docs/levels.md) has already documented one
  episode where a drifting base rate ate every edge in the system and closed the
  gate. A calibration report that does not carry `base_rate_up` per stratum
  cannot tell a model that changed from a reference that moved underneath it.

## 7. What good enough looks like

Two thresholds are needed and neither can be derived yet, so both are stated as
proposals with their reasoning, in the same spirit as [levels.md](../../docs/levels.md)'s
admission that `0.08` "is not derived from anything". Writing down a number
chosen by argument is honest; writing it down without saying which it is, is not.

**Enough to report at all.** Mirroring `facto.MIN_EXAMPLES`: 200 paired calls
after the boundary, *and* at least 30 in each of at least four occupied deciles,
*and* at least three `(feed, interval)` strata contributing 30 or more, *and* at
least 50 distinct level prices overall. The last two exist because of §5 - 200
calls from one afternoon of sol 3m satisfies the first two and is not a sample of
anything. Below any of them, report the counts and decline. Declining is a
result; a curve drawn from an unrepresentative sample is not.

**Good enough to size on.** The consumer decides this, and the consumer is a
sizing rule reading `probability_up`, so the quantity that matters is the
**slope** of realised against claimed rather than the average gap. A constant
offset stakes uniformly too much or too little; a slope below one stakes most
where the model is most wrong, which is unbounded in a way an offset is not. So:
slope within `[0.8, 1.2]` and intercept within 0.05 of the base rate, on a fit
weighted by distinct clusters rather than rows, with `RES > REL` by at least the
`MARGIN` of 0.05 that `facto` already uses for "better by enough to mean it".

Both of those are chosen, not measured. What would derive them is the sizing
rule itself: given a stake function, the loss from a slope error is computable,
and the tolerance is wherever that loss stops mattering against the spread
already being charged. That calculation belongs with whoever owns the capital -
the same boundary [todo.md](../../docs/todo.md) item 3 draws around sizing - and until it
exists these are placeholders that should be labelled as such wherever they are
printed.

### What would falsify a claim of good calibration

Any one of these, and the first four are the ones most likely to be true while
the headline number looks fine:

1. **The pooled curve sits on the diagonal and the per-stratum curves do not.**
   The claim is about the model; a pooling artefact is a claim about the sample
   mix, and next month's mix will differ.
2. **The curve holds on the bulk and breaks in the actionable tail.** Only calls
   clearing `|edge| >= 0.08` ever reach a consumer - historically about one in
   forty-three. A curve fitted on everything and validated nowhere in particular
   says nothing about the slice that matters. Report the tail separately and
   accept that it will be thin for a long time.
3. **`REL >= RES`.** The miscalibration is larger than the information; there is
   nothing here worth calibrating yet.
4. **Brier at or above `ȳ(1 − ȳ)`.** Worse than quoting the base rate every
   time. Combined with a near-zero `REL`, that is the signature of §6's
   over-shrunk model, and it is the one failure that reads as success.
5. **The curve moves between time blocks by more than it moves between halves of
   a block.** Then calibration is not a property of the model, it is a fit to a
   period, and the period is over.
6. **A near-perfect curve.** Over post-boundary data it means a new leak; over
   data straddling the boundary it means the run included the contaminated era.
   Check the `since` before believing it.

## 8. If it is not calibrated: recalibrate, or fix the model

Two responses, and they are not interchangeable.

**Recalibration** fits a monotone map from claimed probability to corrected
probability, leaving the model alone. Two standard choices, and their standing
here is very different.

*Platt scaling* fits a logistic to the claims ([Platt
1999](https://www.csie.ntu.edu.tw/~cjlin/papers/plattprob.pdf)): two parameters,
and streaming - `river.linear_model.LogisticRegression` over the single feature
`logit(p)`, learned one call at a time, which fits the house pattern exactly. If
it is used, it must be fitted **progressively**, predicting each call before
learning it, for the same reason `facto.evaluate` does: a recalibrator fitted on
the same rows it is scored against will look perfect and will be measuring
memorisation, and touches minutes apart at the same level make that leak large
rather than subtle.

*Isotonic regression* fits an arbitrary monotone step function ([Zadrozny &
Elkan 2002](https://dl.acm.org/doi/10.1145/775047.775151)) and assumes less. It
is also a **batch** method, there is no implementation in `river` - the only ML
dependency here - and it needs enough data per step to not simply memorise the
sample. On this journal, with its clustering, it would fit the shape of one
afternoon. Not now, and possibly not ever at this data volume.

**Fixing the model** means changing what produces the probability: the shrinkage
weights, the neighbour count, the base rate's bucketing, the features kNN
compares on.

**Which is honest here is not a close call: fix the model.** A recalibration
layer is the right tool when the model's ranking is good and its scale is off
for reasons you understand and cannot remove - a margin-based classifier that
was never trying to output a probability, which is what Platt scaling was
invented for. That is not the situation. `probability_up` is a shrunk frequency
estimate, built to be a probability, and every known reason it might be
mis-scaled is a *structural* fact about this system that is already written down:
the touch counts that were inflated, the base rate that was pooled across
instruments, the tracker settings that define the label, the concentration of the
sample. Bolting a corrector on top would paper over exactly the things this
project has spent its effort finding, and it would do it invisibly, because a
recalibrated number looks identical to a correct one.

There is one honest use for Platt scaling here that does not involve shipping it:
**fit it as a measurement.** Its two parameters *are* the slope and intercept
that §7 gates on, estimated without bucketing at all. A slope of 0.6 is a
statement about how over-confident the model is, in one number, and it points at
the shrinkage weights rather than at a patch. Report the fitted parameters;
resist applying them.

If a corrector is ever applied, three conditions, non-negotiable: it is fitted
progressively; the uncorrected claim stays in the journal so the correction is
reversible and auditable; and `RES` is reported before and after, because a
monotone map cannot increase resolution and a corrector that reduces it has
made the model worse in the only dimension it was allowed to leave alone.

## 9. Where this would go

Nothing here is built. The shape that would fit the repo:

- **`facto.dataset` carries one more field.** It already joins the outcome to
  its parent to recover `expected_push_vol`; recovering `probability_up` on the
  same line is the whole data change. `Example` gains a `claimed_up` beside
  `predicted`, and the `since` filter moves off the index build (§4).
- **A `calibration.py` beside `facto.py`**, holding the per-bucket counters, the
  decomposition and a `Report` with the same manners as `facto.Report` - an
  `enough` property, a `verdict` string that names the defect in words, and
  `to_dict`. It is a fold over examples, so it can run inside the same pass
  `evaluate` already makes.
- **`structures calibration`**, mirroring `structures fit`: `--since` required
  rather than defaulted, `--feed` and `--interval` to cut a stratum, exit
  non-zero when it declines, and the per-stratum table printed above the pooled
  line rather than below it.

## Honest status

Nothing in this document has been measured on this system. No calibration run
has been performed, no reliability curve exists, and `probability_up` has never
been scored against anything.

The synthetic checks quoted in §3 and §6 test the arithmetic and the direction of
the trade, not this model. The only journal available locally is a stale
development copy holding 140 paired outcomes, entirely on the wrong side of the
contamination boundary, concentrated on five instruments with 115 of 140 on 5m.
Bucketing it puts 88 of 140 calls in the lowest decile and leaves several
interior buckets holding one to four calls each, most of which realise 100% -
which is a picture of both problems this document is about, thinness and
contamination, and is not evidence about anything. It is quoted as **shape only**
and no figure from it should be repeated as a result.

The precondition is the same one everything else is waiting on: enough
post-boundary outcomes, spread across enough instruments and timeframes, that a
bucket means something. [todo.md](../../docs/todo.md) item 0 is what makes that arrive
honestly rather than quickly.

## Reading

- Brier decomposition into reliability, resolution and uncertainty: A. H. Murphy,
  [*A New Vector Partition of the Probability Score*](https://journals.ametsoc.org/view/journals/apme/12/4/1520-0450_1973_012_0595_anvpot_2_0_co_2.xml),
  Journal of Applied Meteorology 12 (1973), 595-600.
- Sharpness subject to calibration: T. Gneiting, F. Balabdaoui & A. E. Raftery,
  [*Probabilistic Forecasts, Calibration and Sharpness*](https://rss.onlinelibrary.wiley.com/doi/abs/10.1111/j.1467-9868.2007.00587.x),
  JRSS-B 69 (2007), 243-268.
- ECE and reliability diagrams as commonly reported: C. Guo, G. Pleiss, Y. Sun &
  K. Q. Weinberger, [*On Calibration of Modern Neural Networks*](https://proceedings.mlr.press/v70/guo17a/guo17a.pdf), ICML 2017.
- Why the binned ECE estimate is biased: A. Kumar, P. Liang & T. Ma,
  [*Verified Uncertainty Calibration*](https://proceedings.neurips.cc/paper_files/paper/2019/file/f8c0c968632845cd133308b1a494967f-Paper.pdf),
  NeurIPS 2019.
- Recalibration: J. Platt, [*Probabilistic Outputs for Support Vector Machines*](https://www.csie.ntu.edu.tw/~cjlin/papers/plattprob.pdf) (1999);
  B. Zadrozny & C. Elkan, [*Transforming Classifier Scores into Accurate Multiclass Probability Estimates*](https://dl.acm.org/doi/10.1145/775047.775151), KDD 2002.

## Where the numbers are

| | |
|---|---|
| `structures/reactions.py` | `Inference.probability_up`, `base_rate_up`, `edge`, the shrinkage |
| `structures/service.py` | `emit` and `_watch_calls` write the claim; `record_outcomes` writes the label |
| `structures/facto.py` | `dataset`'s parent join, `evaluate`'s progressive pass, `Report`'s manners |
| `journal/store.py` | the schema, and `read(since=)` |
