# How strong is a level, and does it matter

**Status: measured, not built.** The measurements below were run on stored
history on 2026-08-14. The weight they argue for - `quality_l` in
[score.md](score.md) §1 - does not exist in the code, and neither does anything
that consumes it. This document exists so that when it is written, the weights
are ones somebody measured rather than ones somebody liked.

The question is the one [todo.md](todo.md) 5b asks: the model has no way of
saying *this level is weak*. `Level.strength` is a continuous score mixing
touches, zone tightness, recency and breadth, and it is consumed nowhere as a
decision. Before giving it a job, it is worth finding out whether it - or any
of its parts, or anything else a level knows about itself - predicts anything
at all.

## The denominator was wrong while this was measured

**Read this before any number below.** After these runs were taken, a fault was
found and fixed in `Engine.observe_bar` (commit `18e95c0`): the volatility
estimate folded the same bar close in once per reporting venue, so `vol.bps`
came out divided by roughly the number of venues past quorum - four on eurusd
and gbpusd, three on gold, two on btc, and one, meaning correct, on spx500.
Every distance in volatility units therefore read **two to four times larger
than it was, by a factor that differs per instrument**.

That is not a cosmetic problem for this document. Volatility units decide the
zone width, the clustering tolerance, the resolve distance and the keep
distance - which is to say they decide which levels exist, which arrivals count
as touches, and which touches resolve as what. **The labels are affected, not
only the covariates**, and the commit message names the mechanism: a level 0.4
units away presented as 1.6 is past `resolve_vol`, so an arrival that observed
nothing was recorded as a rejection.

| claim | status after the fix |
|---|---|
| **orderings ranked within one `(feed, interval)`** | the bias is a single rescale inside a series, so the ordering should survive - but the sample it was measured on will not be the same sample |
| **the instrument table** (gold 72.3% … spx500 90.8%) | **suspect**. spx500 is the one instrument whose denominator was correct and it sits at the top, which is the shape the bias would produce |
| **the timeframe table** | the bias is per instrument rather than per timeframe, but the rows are pooled across instruments, so read the direction and not the numbers |
| **pooled spreads** in the measured table | each is a blend of four differently scaled series; direction is more trustworthy than size |
| **the absolute hold rate**, 80.9% | not trustworthy in either direction |
| **zone width** | measured *in* the biased units. Discarded above on other grounds, and now doubly unproven |
| **confluence breadth** | zones are grouped by overlap in vol units, so both the grouping and the depth counts move with the fix |
| **counts and labels** - record, experience, origin, swings | not volatility quantities themselves, but produced by touches whose detection is, so they move with the fix even though their units do not |

**A check run on the corrected code was taken** - same six instruments, 800
bars, 2,864 decisive interactions - and it is reported in full under "Does it
survive the fix" below, because it does not agree with the pre-fix runs about
everything. The short version: the record signal survives and strengthens, the
instrument spread collapses to a third of its size, and the origin ordering
**inverts**. The rule that survives either way is the one applied throughout:
**grade within the series, and trust an ordering further than a number.**

## What is being predicted, and the asymmetry hiding inside it

A resolved interaction is *held* (`reject`, `backcheck`), *broke* (`break`,
`trap`) or `chop`. Chop is counted separately throughout rather than folded
into whichever side flatters the number - a level price loiters at without
resolving is a third thing, and hiding it in either column would make every
rate below look better or worse for no reason.

**One number has to be stated before any of the rest can be read.** Across the
main run, 4,950 decisive interactions were 3,987 rejects, 18 back checks, 933
traps and **12 breaks**. Under the alternative reading - [levels.md](levels.md)
§7b is explicit that a trap *is* the level holding, violently - the hold rate
is **99.8%** and nothing separates from anything, because there is nothing left
to separate.

So the quantity actually being modelled here is not "did the level hold" in the
trading sense. It is **did price get through the level at all**, with a trap
counted as having got through and come back. That is a real and useful
distinction - it is the difference between a level that turns price away and
one that has to reclaim it - but every number below is a number about *that*,
and the design at the end inherits the choice. A `quality_l` fitted to this
target is a weight on "will price be turned away cleanly", not on "will this
level make money".

## The harness, and why it is shaped this way

```python
engine = Engine(formation="both", run_threshold=2.0)
engine.seed(
    DB, feeds=FEEDS, bars=BARS, on_progress=lambda d, t: collected.extend(engine.drain_resolved())
)
```

Three details are load-bearing:

- **Drained during the replay**, through `on_progress`. `MAX_RESOLVED` caps the
  queue at 500 and silently drops the oldest beyond it, and an earlier run of
  this comparison was invalidated exactly that way - see
  [levels.md](levels.md), "Rerun with both flaws fixed".
- **Attributes snapshotted at first contact**, not at drain time. The tracker
  calls `level.record(...)` when an interaction closes, so by the time a pair
  reaches `drain_resolved()` the level already contains the outcome being
  predicted. Grading a level by a touch count that includes the touch under
  test is not a subtle error, it is a guaranteed positive result. The snapshot
  is taken in `Tracker.begin`, which runs at first contact and before anything
  is recorded.
- **`formation="both"`**, so `origin` reads `pip`, `run` or `pip+run` and the
  agreement signal from 5a can be reproduced as a check that the harness is
  known-good before anything new is asked of it.

Data is the local store, which holds six instruments - gold, btc, eurusd,
gbpusd, spx500, us100 - across seven of the eight level timeframes, there being
no 3m bars in it.

| run | bars replayed | resolutions | decisive | chop | levels touched |
|---|---|---|---|---|---|
| **main**, 2,500 bars/series @2v | 385,273 | 5,495 | 4,950 | 545 | 497 |
| replication, 800 bars/series @2v | 197,281 | 3,154 | 2,817 | 337 | 373 |
| replication, 800 bars/series @4v | 197,281 | 2,452 | 2,179 | 273 | 289 |
| repeat of the main run, carrying touch gaps | 388,500 | 5,594 | 5,047 | 547 | 501 |
| **on corrected code**, 800 bars/series @2v | 198,212 | 3,352 | 2,864 | 488 | 278 |

Pooled hold rates: **80.9%**, 82.2%, 83.2%, 80.8%, and **86.5%** on the
corrected code. The first four are one codebase and the last is another, so
the first four are compared with each other and the fifth is compared with the
second, which shares its size and settings.

**Ten decisive touches per level, not one.** That matters more than the sample
size does. Binomial intervals over 4,950 touches assume 4,950 independent
observations and there are closer to 497, so every interval quoted from a
straight bucket count is optimistic. Where a difference is claimed below, it is
also given as a **bootstrap resampling levels** rather than touches, which is
the unit that actually repeats.

## The largest effect is not a level property at all

Before any level attribute earns credit, this:

| timeframe | decisive | hold | | instrument | decisive | hold |
|---|---|---|---|---|---|---|
| 15m | 738 | 73.4% | | gold | 383 | 72.3% |
| 5m | 1,129 | 78.3% | | btc | 1,229 | 78.8% |
| 1m | 2,430 | 80.6% | | gbpusd | 1,099 | 78.4% |
| 1h | 475 | 93.7% | | eurusd | 778 | 79.4% |
| 4h | 63 | 95.2% | | us100 | 590 | 82.9% |
| 1d | 79 | 100.0% | | spx500 | 871 | 90.8% |

Both halves of that table are pre-fix, and the instrument half is the one the
denominator bug hits hardest - on corrected code that spread runs 83.5% to
90.5% rather than eighteen points wide. The point it makes survives the
shrinking, which is why the table is still here.

A model with **nothing in it but which chart the level is on** reaches an
out-of-sample AUC of **0.608** on the main run and 0.586 on the corrected one,
and the best model found here, with every candidate signal in it, reaches
0.660 and 0.659 respectively. Most of what is predictable about
whether a level holds is *where it is*, not *what it is*.

That is not a reason to give up on level quality; it is a reason to grade it
**within** its own series. A quality score compared across a 1m gold level and
a 1h spx500 level would mostly be measuring gold and spx500. Every quality
figure below is therefore also reported ranked within `(feed, interval)`, and
the design at the end makes that ranking the definition rather than an
afterthought.

## The measured table

Each signal against the hold rate, on the main run. "Spread" is the top bucket
minus the bottom; the bootstrap column resamples levels.

| signal | n decisive | spread, top vs bottom | clustered bootstrap | verdict |
|---|---|---|---|---|
| **the level's own record**, same side | 3,175 | 67.5% → 88.3%, **+20.8** | +20.5 [+16.8, +23.9] | **separates, and by the most** |
| **experience** (log touches) | 4,950 | 76.2% → 86.6%, **+10.4** | +6.7 [+2.9, +10.5] | **separates** |
| **origin** - found by both passes | 4,950 | 78.0% → 84.1%, **+6.1** | +6.0 [+2.6, +9.9] | separates pre-fix, **inverts after** |
| `Level.strength`, the composite | 4,950 | 77.2% → 85.7%, +8.5 | - | separates, beaten by its parts |
| age in days | 4,950 | 75.6% → 85.9%, +10.3 | - | a proxy for touches; dies beside them |
| swings that formed it | 4,950 | 72.7% → 82.6%, +9.9 | - | another touch count; adds nothing |
| zone width | 4,950 | 78.4% → 84.4%, +6.1 | - | **ordering unstable across runs** |
| **confluence breadth** | 4,950 | 79.5% → 84.3%, +4.7 | −2.2 [−6.3, +1.7] | **does not separate** |

**Every row of that table is from the pre-fix code**, so read the verdicts and
not the sizes, and read "Does it survive the fix" below before relying on any
of them. The same signals as models, five-fold with **whole levels held out**,
so no level appears in both training and test:

| model | AUC (main) | AUC (800 @2v) | **AUC (corrected 800)** |
|---|---|---|---|
| chart alone (timeframe + instrument) | 0.6076 | 0.6497 | 0.5859 |
| + `Level.strength` | 0.6321 | 0.6695 | 0.6047 |
| + experience | 0.6386 | 0.6751 | 0.6327 |
| + own record, shrunk | 0.6382 | 0.6607 | 0.6361 |
| + same-side record, shrunk | 0.6404 | 0.6558 | **0.6576** |
| + origin | 0.6004 | 0.6732 | **0.5351** |
| + confluence depth | 0.6192 | 0.6427 | 0.6014 |
| + record and experience | 0.6544 | 0.6694 | 0.6397 |
| + everything above | 0.6599 | 0.6790 | 0.6588 |

The third column is the only one taken on corrected code. Read down it and the
design at the end writes itself: the same-side record is the best single thing
a level knows about itself, origin is worse than knowing nothing, and the
composite sits between them.

## Signal by signal

### The level's own record is the strongest thing it knows

Bucketing by the level's hold rate **on the side price is arriving from**,
counted from resolved interactions before this one and requiring at least two:

| same-side record | decisive | hold |
|---|---|---|
| under 60% | 243 | 67.5% |
| 60-80% | 790 | 78.7% |
| 80-95% | 1,188 | 84.1% |
| 95-100% | 954 | 88.3% |

Monotone, twenty points end to end, and it replicates: +15.6 and +11.7 points
across the two smaller runs, monotone in both. Shrunk toward the pooled rate
with a Beta prior of weight 4, `record ≥ 0.9` against `< 0.75` is **+20.5
points [+16.8, +23.9]** resampling levels, and +15.2 [+10.0, +19.8] on the 800
run.

**On corrected code it separates further still**: 59.4% to 92.2% across the
same four buckets, a standardised coefficient of +0.44 against +0.24, and
+13.5 points [+4.9, +21.5] resampling levels for `≥ 0.9` against `< 0.75`. Of
everything measured here, this is the only signal that got *stronger* when the
denominator was fixed.

This is the component that has to be defended hardest, and the defence is in
"How this could fool itself" below.

### Experience separates; the raw touch count barely does

`experience` - `log1p(touches)/log1p(50)`, already computed in `Features` on
every touch - rises monotonically with the hold rate: 76.2%, 78.9%, 81.9%,
86.6% by quartile. The raw effective touch count does not, because its low
buckets are noise: a level with *zero* effective touches holds 78.0% while one
with 0.5-2 holds 75.8%. The log compression is doing real work rather than
cosmetic work, which is what the comment on `Features.experience` claims for
it.

**It is much weaker on corrected code**, and this is the honest limit of the
second component: 85.3%, 84.8%, 85.1%, 90.6% by quartile - flat until the top
one - a standardised coefficient of +0.21 (z = 2.0), and above against below
its median is +2.6 points [−2.9, +7.5] resampling levels, an interval through
zero. It still lifts held-out AUC from 0.586 to 0.633, which is why it is kept,
but it is kept as the junior term and as the answer for levels with no record
rather than as a second strong signal.

### Origin: the one result the fix took away

Reproducing 5a as the harness check, pre-fix:

| origin | decisive | hold |
|---|---|---|
| pip only | 291 | 83.5% |
| pip + run | 2,123 | 84.1% |
| run only | 2,536 | 78.0% |

Agreement over run-only is **+6.0 points [+2.6, +9.9]** resampling levels, and
+8.4 [+4.4, +12.6] on the 800 run - the same direction and roughly the same
size as the numbers in [levels.md](levels.md), on a different sample. As a
check that the harness was known-good before anything new was asked of it, that
worked.

Pre-fix, **pip-only was also at least as good as agreement** on all three runs
(83.5%, 87.8%, 89.4% against 84.1%, 85.4%, 84.3%), leaving that ordering
unresolved exactly as 5a left it, while "run-only is the weak one" looked
settled at both thresholds.

**On corrected code it is run-only that holds most** - 88.4% against 86.1% for
agreement and 84.8% for pip-only - and adding origin to a model that knows the
timeframe and instrument drops held-out AUC from 0.586 to **0.535**, which is
worse than knowing nothing about the level at all. Resampling levels, agreement
against run-only is −0.2 points [−8.3, +11.5].

The mechanism is not mysterious: `run_threshold` is expressed in volatility
units, so a denominator two to four times too small changed which swings the
run pass found at all. The pre-fix and post-fix runs are not grading the same
levels differently; they are grading different levels. **So origin is out of
the design**, and it is out on a measurement rather than on taste - with the
note that [levels.md](levels.md)'s agreement result rests on the same
denominator and should be re-run before it is relied on again.

### Confluence breadth does not separate, and may lean the wrong way

This is the result worth stating plainly, because it is the signal that already
exists, is already reported in every alert, and is the one most likely to be
adopted on the strength of how sensible it sounds.

| depth (timeframes agreeing) | main run | 800 @2v | 800 @4v | corrected |
|---|---|---|---|---|
| 1 | 84.3% (1,273) | 82.4% (620) | 80.9% (650) | 82.1% (392) |
| 2 | 79.5% (1,007) | 86.7% (789) | 82.8% (657) | 87.4% (1,647) |
| 3 | 79.7% (1,063) | 82.8% (522) | 84.4% (545) | 88.7% (379) |
| 4+ | 79.9% (1,607) | 77.7% (886) | 86.9% (327) | 84.8% (446) |

Four runs, four orderings: best at depth 1, at depth 2, monotone increasing,
and best at depth 3. As a ranking signal on its own, depth scores an AUC of
**0.476** and **0.452** on the two 2v runs - *below* 0.5, meaning that if
anything, more timeframes agreeing goes very slightly with breaking rather than
holding. Resampling levels, `depth ≥ 3` against `depth < 3` is −2.2 [−6.3,
+1.7] and −5.2 [−9.4, −1.2] pre-fix, and +0.3 [−4.2, +4.9] on corrected code -
three intervals, none of which excludes zero in the direction the multiplier
assumes.

Two readings are available and this measurement cannot separate them. Either
confluence carries no information about whether a level holds, or depth is
confounded with the timeframe mix in a way that six instruments cannot unpick -
a price agreed on by five timeframes is usually a price the 1m chart is sitting
on, and 1m is the weak end of the timeframe table above. Either way there is no
support for weighting it today.

**It has a consequence in code.** `Zone.strength` multiplies the best member's
strength by `1 + 0.15 × (depth − 1)`, so a four-timeframe zone is lifted 45%
for a property that does not predict this outcome. That multiplier is unearned
on this evidence and should be treated as unproven rather than as a base to
build on.

### Zone width, age and swings: three near-misses that are already counted

- **Zone width.** A wider zone holds slightly *more* - the opposite of what
  `strength`'s tightness term assumes - at +0.116 standardised (z = 2.7) on the
  main run. But the bucket ordering is not stable across runs (the second
  quartile is best on both 800 runs), and there is a mechanical explanation
  that has nothing to do with quality: a wider zone is more distance for price
  to cross before an interaction counts as a break. A signal with a mechanical
  explanation and an unstable ordering is not a finding.
- **Age.** +10.3 points across quartiles, and **+0.045 standardised (z = 0.4)**
  once the record and experience are in the same model. It is a proxy for
  having been touched, which is what [levels.md](levels.md) §10 already says
  under "age is deliberately not rewarded". Confirmed rather than overturned.
- **Swings.** +9.9 points, and no improvement in held-out AUC over experience
  alone. It is a third way of counting the same evidence.

### The composite does not beat its parts

`Level.strength` separates: 77.2% to 85.7% by quartile, +8.5 points, an odds
ratio of 1.77 between top and bottom. It is beaten by `experience`, which is
one of its own four terms, in every pre-fix run - AUC 0.565 against 0.572 on
the main run, 0.590 against 0.602 on the 800 run - and by the record, which it
does not contain at all. **On corrected code the gap widens**: 0.548 against
the same-side record's 0.648, and held out by level, `+ strength` reaches 0.605
where `+ same-side record` reaches 0.658.

That is not surprising once its terms are read against the table above. Of the
four, one (evidence) predicts, one (breadth, as swings) is the same thing
counted again, one (recency) is age with a fixed 14-day half-life that means
something completely different on 1m and 1w, and one (tightness) points the
opposite way to the measurement. **A composite of four terms where one works
does not beat the term that works.**

So `strength` should keep its job as a kNN feature - `facto.py` lists it in
`NUMERIC`, and journalled examples were recorded under its current definition,
so changing the formula in place would silently redefine a feature that
existing training data is labelled against. `quality` should be a **new**
function beside it, not a rewrite of it.

## Does it survive the fix

One run on the corrected code, same six instruments, 800 bars per series:
198,212 bars, 3,352 resolutions, **2,864 decisive**, 488 chop, 278 levels
touched. Pooled hold **86.5%** against 82.2% for the matching pre-fix run - the
same shape of sample, so the comparison is like for like.

| signal | pre-fix (800 @2v) | **corrected (800 @2v)** |
|---|---|---|
| same-side record, worst → best bucket | 74.4% → 89.9%, +15.6 | **59.4% → 92.2%, +32.8** |
| experience, q1 → q4 | 75.5% → 90.4%, +14.9 | 85.3% → 90.6%, **+5.8**, and flat until the top quartile |
| origin: pip / pip+run / run-only | 87.8% / 85.4% / **76.8%** | 84.8% / 86.1% / **88.4%** |
| confluence depth 1 → 4+ | 82.4% / 86.7% / 82.8% / 77.7% | 82.1% / 87.4% / 88.7% / 84.8% |
| `Level.strength`, q1 → q4 | 75.9% → 88.1%, +12.2 | 85.1% → 91.2%, +6.1, flat until the top |
| instrument spread, worst to best | 74.0% → 93.0%, **19.0 points** | 83.5% → 90.5%, **7.0 points** |

Standardised coefficients on the corrected run, timeframe and instrument held
fixed: **same-side record +0.44 (z = 8.8)**, experience +0.21 (z = 2.0),
confirmed origin **−0.05 (z = −0.8)**, confluence depth −0.01 (z = −0.2), zone
width +0.30 (z = 2.8), age +0.06 (z = 0.3).

Held out by whole levels, five-fold, on the corrected run: chart alone 0.586,
`+ same-side record` **0.658**, `+ experience` 0.633, `+ Level.strength` 0.605,
`+ origin` **0.535** - below the chart-only baseline - and everything together
0.659. Resampling levels, the record at `≥ 0.9` against `< 0.75` is **+13.5
points [+4.9, +21.5]**, agreement against run-only is **−0.2 [−8.3, +11.5]**,
depth is +0.3 [−4.2, +4.9], and experience above against below its median is
+2.6 [−2.9, +7.5] - positive but with an interval through zero, which is the
honest reading of the weaker of the two components kept.

Three things to take from that, and one of them costs a component:

- **The instrument spread was largely the bug.** Nineteen points between the
  worst and best instrument became seven once the denominator was fixed, and
  the instrument whose denominator had been correct all along - spx500 -
  stopped being the outlier at the top. This is the cleanest confirmation
  available that the cross-instrument numbers above should not be believed.
- **The record signal is not the bug.** It separates *more* on corrected data,
  and by a wide margin: 59.4% to 92.2%, with a standardised coefficient twice
  the size it had before. Whatever else moves, the component the design leans
  on hardest gets stronger.
- **The origin ordering inverts, so origin comes out of the design.** Run-only
  levels went from the weakest group in all three pre-fix runs - by six to
  fourteen points against the other two origins - to the *strongest* on
  corrected code, by two to four. Both readings cannot be true. The likely
  mechanism is that run formation thresholds on volatility directly -
  `run_threshold` is in volatility units - so a denominator two to four times
  too small was changing which swings the run pass found at all. The two
  codebases are not grading the same levels differently; they are grading
  different levels. Until it is re-measured on corrected data at
  size, "found by both formations" is **unresolved**, and
  [levels.md](levels.md)'s agreement result inherits the same doubt.

Confluence breadth does not separate on the corrected run either - a
coefficient of −0.01 and, once again, a non-monotone bucket table with a
different shape from every previous run. Four runs, four orderings, no support.

Zone width strengthens (+0.30, z = 2.8) and is still not adopted: the
mechanical explanation - a wider zone is further for price to travel before
anything counts as a break - applies with exactly the same force on corrected
data, and the bucket table is still not monotone.

## The design

```
record_l   = (holds + κ·r̄) / (holds + fails + κ)     same side, κ = 4
evidence_l = log1p(n_l) / log1p(50)                   = Features.experience

raw_l   = 0.65·record_l + 0.35·evidence_l
u_l     = rolling quantile rank of raw_l within (feed, interval)
quality = 0.45 + 0.55·u_l                             ∈ [0.45, 1.0]
```

and it enters the score exactly where §1 leaves the hole:

```
w_l = proximity_l · confidence_l · quality_l
```

**Two components, and nothing else.** Origin was in this formula until the
corrected run inverted it; confluence depth, zone width, age and swings never
were, and each has a measured reason above rather than a preference. Two terms
with support beat four terms where one works, which is the diagnosis of
`Level.strength` restated as a design rule.

Scored with no fitting at all, ranked within each `(feed, interval)`:

| | q1 | q2 | q3 | q4 | odds ratio | AUC |
|---|---|---|---|---|---|---|
| **corrected run** | 79.6% | 84.4% | 89.3% | 91.1% | **2.62** | 0.6197 |
| pre-fix, main | 74.7% | 78.5% | 80.9% | 88.1% | 2.51 | 0.6005 |
| pre-fix, 800 @2v | 77.6% | 81.0% | 84.5% | 83.9% | 1.51 | 0.6174 |
| pre-fix, 800 @4v | 80.7% | 80.3% | 84.7% | 86.3% | 1.51 | 0.6161 |
| `Level.strength`, same four runs | - | - | - | - | - | 0.548, 0.565, 0.590, 0.597 |

It beats `Level.strength` on **all four runs**, including the one taken on
corrected code, which is the only comparison in this document not subject to
the denominator caveat. The AUCs are computed the same way for both, over the
same touches; the odds ratios are not quoted for `strength` because the ones
reported for it earlier are pooled quartiles rather than within-series ranks,
and mixing the two in one column would flatter whichever happened to be
ranked.

**`r̄` is the rolling pooled hold rate for that `(feed, interval)`**, not 0.5
and not a constant: shrinking a level's record toward 0.5 on a series where
levels hold 90% of the time would penalise every level for being on that
series. κ = 4 matches the prior weight already used in
`SideStats.probability_up`; between κ = 2, 4 and 8 the ranking barely moves
(AUC 0.604, 0.606, 0.607), so this is not a number worth tuning.

**Why the same-side record rather than the level's overall record.** The
asymmetry is the point of the whole level model ([levels.md](levels.md) §5),
and same-side buckets separate more than pooled ones on both codebases -
+20.8 against +17.1 before the fix, +32.8 against +26.1 after. It costs
nothing: `SideStats` already holds it.

**Why a blend at all, when the record alone often ranks better.** It does rank
better on two of the four runs - AUC 0.643 against 0.620 on the corrected run,
0.606 against 0.601 on the main pre-fix one - and worse on the other two. The
blend is not there to win the ranking. It is there because **31% of decisive
touches had fewer than two prior resolved interactions on the arriving side,
and 10% had none at all** (corrected run; 36% and 10% on the main pre-fix one).
For those, the record is only its prior, and `evidence_l` is the whole of the
grading. A weight that says nothing about a third of its cases is not a weight.

**The weights are the least measured part of this.** Standardised coefficients
per run:

| | corrected | main pre-fix | 800 @2v | 800 @4v |
|---|---|---|---|---|
| same-side record | **0.68** | 0.49 | 0.23 | 0.16 |
| experience | 0.32 | 0.39 | 0.37 | 0.13 |
| confirmed origin | 0.00 | 0.12 | 0.40 | 0.72 |

`0.65 / 0.35` is the corrected run's own answer rounded, and it is the only row
taken on code that was not dividing by the wrong number. The pre-fix rows are
kept to show how far the split moves between samples: not measured to better
than a factor of three, which is survivable only because the ranking barely
moves with it - across `(0.65, 0.35)`, `(0.5, 0.5)` and record-only, AUC moves
by about 0.02 on three runs and by 0.05 on the corrected one, and every blend
tested beats `Level.strength` on every run.
Refit it as data accumulates; do not defend it.

**Where the range comes from.** The odds ratio between the top and bottom
quality quartile, ranked within series, is 2.62 on the corrected run and 2.51,
1.51 and 1.51 on the pre-fix ones. If the weight is meant to be proportional to
the evidence a level carries, the floor should be about `1/OR` - which is
between 0.38 and 0.66 across those four, and `0.45` sits inside that. It is a
measured ratio with a wide interval rather than a chosen constant, and it
should be **recomputed from the rolling window** rather than frozen at today's
value.

**A quantile rank, not a raw score**, for the reason [score.md](score.md) §3
gives for the thresholds and the reason the timeframe table gives: `raw_l` is
not comparable between a 1m gold level and a 1h spx500 one, and a constant cut
would be another number nobody chose. The window has to be long enough to be a
distribution and short enough to still be this market, which is the same
tension the score's thresholds have and should use the same answer.

## Which parts are point-in-time safe, and which are not

This is where the design is most likely to be quietly wrong, so it is worth
being specific rather than reassuring.

| component | point-in-time | why |
|---|---|---|
| `evidence_l` | **safe, and already journalled** | `Features.experience` is computed in `features_for` at first contact and copied into the journal with the outcome |
| `record_l` | **safe by construction, fragile in practice** | `SideStats` at contact contains only interactions that have already resolved - but see below |
| `origin`, had it been kept | safe, and dropped anyway | `origin` at contact only ever accumulates formations, so it cannot see the future - it is out of the design for inverting on corrected data, not for leaking |
| `quality_l` itself | **safe only if the quantile window is** | a rank against a window that includes later levels is look-ahead through the back door |
| confluence depth | safe, but **not recorded** | computable at contact from the levels then alive; nothing stores it, so it cannot be checked after the fact today |

Two of these are worth spelling out.

**`record_l` is point-in-time and still dangerous.** The evidence in
`SideStats` at contact is genuinely all past, because the tracker records an
outcome only when an interaction closes. What it is *not* is independent of
what follows. [levels.md](levels.md) §8 describes the failure exactly: when one
grinding episode is counted as many touches, "the level's history and its next
outcome are the same price action counted twice", and that produced a 99.9%
direction column that looked like skill. A record-based weight is the same
machinery pointed at the same hazard. It is only trustworthy while touch
counting is, which makes item 1 in [todo.md](todo.md) a **prerequisite** for
this design rather than an unrelated bug.

**The quantile window is a look-ahead risk that does not look like one.**
Ranking today's `raw_l` against a window of quality values that includes
tomorrow's is a leak even though every component is individually
point-in-time. The window must be causal - values as of each moment, in the
order they occurred - which the score's rolling-quantile machinery already has
to get right for its own thresholds.

## How a backtest of this could fool itself

Six ways, in the order they are likely to happen:

1. **Grading by history and then measuring the graded levels.** The circular
   one 5b names. Everything here is snapshotted at contact for exactly this
   reason, and the snapshot is taken in `Tracker.begin` rather than at drain
   time because `level.record(...)` has already run by then. If a future
   version reads the level's attributes at drain time, every number in this
   document becomes meaningless and will look *better*.
2. **Counting touches as observations.** 4,950 decisive interactions came from
   497 levels. A test that treated those as 4,950 independent trials would
   find nearly everything significant; every interval quoted here is from
   resampling levels, and they are the honest ones.
3. **Rediscovering the timeframe.** A chart-only model already reaches 0.608
   AUC. Any quality score that is not graded within its series will inherit
   that separation and be credited for it.
4. **The grind.** If price loiters at a level and the counting inflates,
   `record_l` and the next outcome are the same move, and the weight will fire
   hardest exactly where the counting is worst - which is also where the
   channel is loudest. See §8 of [levels.md](levels.md) for what this looks
   like from the outside: it looks like a triumph.
5. **A denominator that is wrong in the units everything is expressed in.**
   Not hypothetical: it happened here, it was invisible in every summary
   statistic, and it moved a headline ordering. Nothing in the outcome
   machinery can catch it, because the labels move with the covariates and the
   result stays internally consistent. The only defence that worked was
   re-running on the fix and comparing.
6. **Reading the trap column.** With 12 breaks against 933 traps, almost every
   "failure" here is a level that was breached and reclaimed. If a later
   version reclassifies traps as holds, this entire document evaluates to "no
   signal anywhere" - not because the signals died, but because the target did.

## What would falsify it

Concrete, and each of these is a test somebody can run:

- **The record does not survive a gap - run, and it survived.** If `record_l`
  predicted only when the previous touch was minutes ago, it would be measuring
  persistence inside one grinding episode rather than a property of the level.
  On a repeat of the main run carrying the gap since each level was last
  touched - 5,047 decisive - `record ≥ 0.9` against `< 0.75` is **+16.9 points
  over all 3,252 touches that had a record at all, +15.4 with a gap of at least
  five bars, and +25.1 with a gap of at least twenty** (n = 293, AUC 0.660).
  Past a hundred bars the arms are too thin to read. That is the strongest
  single piece of evidence that this component is not the grind, and it is the
  test to repeat on corrected data, where the gap-split arms are thin already.
- **The components do not survive on fourteen instruments.** Six is what the
  local store holds, and the origin ordering has already flipped once between
  codebases rather than between instruments. If the record's ordering flips on
  the other eight, the design has nothing left.
- **Quality does not improve the score.** The point of the weight is the score,
  not the hold rate. If `w_l = proximity · confidence · quality` scores no
  better against realised pushes than `w_l = proximity · confidence`, the
  weight is arithmetic. That test needs the score to exist and needs journalled
  transitions, which is why it is last in the order below and not first.
- **A quantile window long enough to be stable is longer than the regime.** If
  the rank has to be taken over a window that spans a regime change to be
  usable at all, the grade is describing a market that has gone, and ADWIN
  already knows when that has happened.

## Order of work

1. **Re-run the whole measurement on the corrected denominator.** Everything
   here was taken before `18e95c0`, on distances two to four times too large by
   an instrument-dependent factor. One check run on the corrected code is
   reported above; it is 800 bars, not the main sample.
2. **Trust the touch counting first.** [todo.md](todo.md) item 1. Both
   components are counts, and a count that inflates during a grind makes the
   weight strongest where it is least earned.
3. **Record what is already computable but not kept** - confluence depth at
   contact, and the level's same-side record - in the journalled context beside
   `experience` and `strength`, which are already there. It costs two fields
   and it is the difference between checking this in a month and re-running the
   replay.
4. **Add `quality()` beside `strength()`**, not instead of it. `strength` is a
   kNN feature in `facto.py` and journalled examples carry its current
   definition.
5. **Wire it into the score** as `w_l = proximity · confidence · quality`, once
   the score itself exists - [score.md](score.md) §6 already orders it third
   for the same reason.
6. **Rerun this measurement on fourteen instruments** and refit the two
   weights. The split between them is the least-measured thing here.
7. **Leave `Zone.strength`'s confluence multiplier alone until it is
   defended.** It lifts a zone by up to 45% for a property that did not
   separate in any of four runs. It is not obviously wrong; it is unmeasured,
   and it is now known to be unmeasured.

Everything above is a measurement of one target - whether price is turned away
from a level without going through it - on six instruments: a main run of 4,950
decisive interactions, two replications over the same history at a different
depth and a different run threshold, a repeat of the main run carrying the
touch gaps, and one run on corrected code. The signals that separated are
stated with what they separated by; the ones that did not are stated as
failures rather than left out; and the one that separated before the fix and
reversed after it is stated as unresolved, which is what it is.
