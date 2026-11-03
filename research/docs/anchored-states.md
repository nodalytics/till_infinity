# Does an anchored state call the next move's size?

**Pre-registered 2026-11-03 in [anchored-states-prereg.md](anchored-states-prereg.md)
(commit `0d4234c5`), before any cell of this study existed.** The anchors, the
outcome and its horizon, the four null arms, the draw count, the stratification,
the five-part pass rule, the trial count, the metrics and the two ways a pass
would still be uninteresting were all frozen there. Everything that departs
from it is in [Deviations](#deviations-from-the-pre-registration), numbered,
each with the number that caused it.

The question replaces the geometric framing, and the user's reframing names a
defect rather than a preference: **a geometric pattern is only identifiable
once it completes**, so the shape exists only after the move it describes.
`trend.pivots` is honest about this - it confirms a pivot `reach` bars later -
and the measurement side reached it from the other direction, in
`a-return-rate-is-geometry` and `the-origin-picks-a-distance-not-a-probability`.
A **state** is a reading of what has already printed, so it is causal by
construction.

So the claim is about **magnitude** - what sizing and stop placement consume -
and direction is carried only as an interaction with the state, which the
prereg expected to fail. No gate ships from this document whatever it says.

> **Status: the harness, its 36 tests and the run command are complete; the
> panel has not been run.** It must not run on an 8-core box - three studies
> competed on one earlier in this session at load 25-31, one never completed
> its panel at all, and a "406 seconds per leg" timing turned out to be a
> measurement of contention rather than of the job, a twentyfold-wrong
> projection where the same panels ran in 91 and 96 seconds on a 64-core
> machine. The coverage, verdict and numbers go in below once it has run.

## What will be run, stated before any result

**No outcome statistic below this line has been read.** The coverage is
measured - every one of the 42 (feed, interval) pairs was loaded and walked
through the state detector, and all 42 produced rows with no failure and no
missing series. The *timing* is a projection from single-process legs, and is
labelled as one.

| | |
|---|---|
| feeds | the 14 of `level_shield.FEEDS`, one venue each by bar count, ties alphabetically - a data-volume rule fixed before any result |
| placebo pair | `nzdusd` and `usdcad`, carried in every table and excluded from every pass count |
| intervals | 15m, 1h, 1d. 1h is reported separately rather than pooled: FX and gold hold 0.8-0.9 years there and the two indices 1.03-2.87 |
| rows | measured: **100 to 285** de-overlapped anchors an instrument at 1d - 234-235 on the eight FX majors, gold and btc, 285 on the two indices, 208 on usdcnh, 186 on eth and **100 on sol** - **64 to 93** at 1h and **63 to 70** at 15m |
| anchors | 6 states; `session` is **excluded at 1d**, where daily bars all carry one stamp hour and the state has one level |
| arms | `garch-bars`, `walk-geometry`, `bar-shuffle`, `duty-twin`, 16 draws each - **64 draws a cell**, so a chance pass is 1 in 65. Plus `walk-geometry-abs` and `bar-shuffle-abs` at 1d as a non-deciding diagnostic, and `sign-flip` for the secondary claim |
| cells | 238 primary, 238 secondary, 952 in the two halves, 208 power legs - of order **1,640**, matching the prereg's stated order of 1,500 |
| cost | **nothing is costed.** Only `eurusd`, `gbpusd`, `gold`, `btc`, `us100` and `spx500` have enough recorded quotes to measure a median spread per venue; the other eight carry two or fewer, and no spread is invented for any feed |

**63 to 93 rows an instrument is below the ~100 at which this desk's own
standing note says the prior is noise**, and that is a property of the
pre-registered design rather than a choice made here: a non-overlapping block
of 48 bars over 5,136 bars leaves 68 of them. `sol` at 1d has 100 and is the
thinnest 1d feed. The power sweep is what says where that leaves the test
blind, and it is reported before the panel for that reason.

**The machinery check:** all 42 pairs measure, `Pivots.room` resolves on every
feed, and the only bars any state could not be read on are **3 of gold's 1d
bars**, where `FearGreed` raises (see [Defects](#defects-found-on-the-way)).
Walking one series takes **0.34 to 0.79 seconds** on an idle core; the same
walk read 4.46 seconds while this box was at load 12, which is the contention
error in one line.

## The rules, as frozen

### The anchors

Every one is pinned to a quantity this desk already publishes.
`definitions-cannot-be-states` is the recorded failure: a mixture centre left
as a free state **collapses onto the data**, and three members needed anchors
to stay distinct. **No threshold here is chosen against an outcome.** The only
cuts are the fixed thirds of a 0..1 quantity, or equal-mass bins of the state's
own **trailing** distribution.

| anchor | levels | reading | the cut |
|---|---|---|---|
| `session` | 4 | `pivots.session_of` - sydney / tokyo / london / newyork | a clock, conventional boundaries, no fit |
| `through` | 3 | `Pivots.through`, of the **day** at 15m and 1h and of the **month** at 1d | the period's own fixed thirds |
| `compression` | 5 | the causal EWMA of the bar range as a share of price | trailing quintiles |
| `pivot_room` | 3 | `Pivots.room`, the nearer wall, in volatility units, from the **daily** set at 15m and 1h and the **weekly** set at 1d | trailing thirds |
| `mood_vol` | 3 | `FearGreed.volatile` - the half with the measured prior | trailing thirds |
| `mood_dir` | 3 | `FearGreed.directional` - the half measured closed | trailing thirds |

`mood_dir` is here so the secondary claim is built from the quantity most
likely to carry it, not because it is expected to work.

### Causality

Every reading is computable from bars closed at or before the decision bar, and
the harness is built so that this is testable rather than argued:
`test_no_state_reading_moves_when_a_bar_past_the_decision_bar_changes` replaces
every bar after an anchor's outcome window and asserts no level moves, and
`test_the_outcome_does_move_when_a_bar_inside_its_window_changes` is the
control that stops the first from being vacuous.

**The pivot set is the only real risk and it is guarded by
`strategies.timeframes.Frames`.** `Pivots` publishes a period only once a bar
from the next one has arrived, which is necessary and not sufficient:
`node/corpus.py` records that the store's `ts` is probably the bar's **open**,
so a set stamped at its source period's last `ts` would be knowable one bar
early. Each set is registered at `last ts + one interval` - the close under the
pessimistic reading - and read back through `Frames.ready`, which drops any
frame whose last close is after the decision moment. A set `ready` does not
return is a `nan`, never an approximation. `Frames` also decides the 1d pivot
period: it refuses a context frame that is not strictly coarser than the
signal, so a daily set on daily bars cannot be read as context at all.

### The outcome

`size` is the absolute log move from the decision bar's close to the close `H`
bars later, in volatility units of the decision bar; `signed` is the same with
its sign. `H` is **20 at 1d and 48 at 15m and 1h**, matching
[level-bounce.md](level-bounce.md) so the two are comparable. Fixed, not swept.

The unit is a causal EWMA of the bar **range**, per `drive-q-from-the-range`:
the range-vs-close estimator ratio reads 0.648 within strata on FX and 0.667 on
371 of 392 equities.

**Outcome windows are de-overlapped** - one outcome per non-overlapping block
of `H` bars. `overlapping-outcome-windows-leak` is the refutation: a short skip
rule with a long forward window gave a direction AUC of **0.79 that collapsed
to 0.51**, and the tell was the placebo and shuffled arms tracking it. It is
also what makes the duty twin's within-stratum permutation legitimate, which
`overlapping-windows-inflate-permutation-nulls` says it would not be on
overlapping anchors.

### Stratification

Every reading is **within quintiles of trailing compression**,
`log(fast unit / slow unit)`, and the stratified figure is the one that decides.
`AUC-is-free-on-volatility-targets` is why this is not optional: an AUC of
**0.805** was measured on a constant-volatility process where the true answer
is 0.5, falling to **0.525 within strata**, with incumbent features alone
reading 0.74-0.78. A dispersion target is exactly that kind of target, so **an
unstratified AUC on `size` is not a result and is not reported as one** - it is
printed beside the stratified one because the size of the gap is itself the
measurement.

### The nulls

Every arm goes through the **same detector** over the same anchors: the anchor
set is seeded on `(feed, interval)` alone, so every arm and every draw walks
the identical bars over the identical day structure.

| arm | keeps | removes |
|---|---|---|
| `garch-bars` | volatility clustering, fat tails, bar wickiness | path structure |
| `walk-geometry` | bar wickiness, the log-step distribution | path structure **and** clustering |
| `bar-shuffle` | each bar's own shape, the marginal log step | all memory |
| `duty-twin` | the state's firing rate and the bars it fires on, by construction | any association between state and outcome |

`garch-bars` is required because `walk-geometry` resamples steps i.i.d. and so
has none of this market's clustering - and clustering is the mechanical route
by which a state defined on recent range predicts a forward excursion.

**Seeds are `blake2b` over the arm's parts, never `hash()`.** The builtin hash
of a tuple containing a string is salted per process, and three harnesses
carried that bug in one session: `stop-anchor.md` had gold.15m's hardest null
move +0.0267 to +0.0239 and flip a cell from fail to pass with no real reading
moving, and `fear-greed.md` had audjpy's `bar-shuffle` read -0.172 locally and
-0.266 on the panel while every real value matched to the digit.
`test_seeds_reproduce_in_a_second_interpreter` runs the seed in a second
interpreter under a different `PYTHONHASHSEED`.

**Sixteen draws an arm, so 64 a cell.** `fear-greed.md`'s eighth defect is a
hardest-of-20 test manufacturing both of a study's positive cells: one of
sixteen `bar-shuffle` draws reached -0.334 against a real -0.297, where the
four panel draws had landed in a range of 0.06 against a true range of 0.44.
Every pass count here is quoted against `cells / 65` with its Poisson spread,
because `stop-anchor.md`'s report printed a hardcoded expectation whatever
`--draws` was and made 3 of 140 read as "far below chance".

### Two statistics, and the rank one carries its own arms

`effect` is a mean-based between-level contrast and `size` has this market's
tails - kurtosis 47-74 on traded feeds - so a mean over a dozen rows is not
robust to them. A within-stratum Kruskal-Wallis statistic is reported beside
it **with its own sixteen draws an arm**, because a robustness companion
reported against nothing is not a null. The pass rule is evaluated on `effect`,
which is the pre-registered quantity standardised; where the two disagree the
cell is tail-driven and that is said.

### The pass rule

The primary claim passes only if **all** of:

1. the state's effect on `size` exceeds its **hardest** null draw, within
   strata, on at least **3 of the non-placebo instruments**, and on **both** of
   two non-overlapping halves of the history;
2. the effect survives Benjamini-Hochberg across every cell;
3. the **placebo pair does not pass** under the same rule;
4. the **duty-cycle twin does not pass** - otherwise the finding is the firing
   rate rather than the state. Here it is **subsumed by criterion 1**, because
   the twin is one of the four deciding arms: a cell that beats its hardest
   null draw has already beaten all sixteen duty draws. What is reported
   instead is which arm is hardest, since where the twin is hardest the firing
   rate is the binding constraint rather than the series structure;
5. the power sweep shows the test could have seen an effect of the measured
   size.

Anything else is a fail. Passing all five is "worth a fresh-data test", not an
edge: DSR >= 0.95 over the true trial count is still required before that word
is used.

The secondary claim needs the same five **and** the state's own direction
effect to exceed the same state's effect with the sign randomised, which is
what the `sign-flip` arm carries.

### And two ways a pass would still be uninteresting

Both are checked and both are reported:

- **if the effect is monotone in the compression quintile**, the state restates
  the volatility estimate and `topology-restates-volatility` already covers it.
  Cramer's V between each state and the compression stratum is printed in every
  table for this.
- **if the magnitude is smaller than the cost of acting on it.** The stop is
  `Intent.stop_vol`, whose measured median is 3.0 volatility units, and
  `costs.MAX_SPREAD_RISK_FRACTION` is **0.16 of the risk**, so the bar is
  **0.48 volatility units**. `stop-anchor.md` is the cautionary case: its
  anchor could only move a 2-unit stop by 1.4 to 5.3%, which settled it before
  any null was consulted.

## Power

RESULTS PENDING.

The planted effect is the alternative hypothesis itself rather than a proxy: a
log-space walk with this market's bar geometry, with the forward move after
each picked anchor scaled by `1 + strength` **and its bar ranges scaled with
it**. `fear-greed.md` is why the ranges matter - its planted crash was a smooth
drift that never widened a range, so it validated the direction half and read
0 of 4 on the volatility half at depth 0.45.

**The plant is on a clock anchor, where the label is a function of the
timestamp and no price plant can reach it.** `fear-greed.md`'s sixth defect is
the reason: a label-conditional plant changed the path, the labels recomputed on
the planted series no longer marked the same bars, and **the act of planting
destroyed the association being planted** - its zero cell read +0.1412 and a
book of hard walls recovered the wrong sign. A second plant on `mood_vol` is
carried to measure that attenuation rather than assume it, and it has its own
zero control. A zero cell outside its arms is a broken arm, not a weak effect,
and the sweep says so where it happens.

**The sweep runs to a lift of 3.2x and takes eight draws an arm**, both
because a first pass at two draws and a ceiling of 0.80 did not locate a blind
point: on eurusd 15m a plant delivering **2.22x** the other levels' mean
absolute move raised the recovered effect from 0.257 to 0.483 and still sat
inside the arms. With 68 rows and four `session` levels the statistic's own
noise floor is `sqrt(3/68) = 0.21`, so that is where most of 0.483 came from.
A sweep that stops before the test sees anything has confirmed the null rather
than calibrated it.

**Two plant shapes, because the outcome's denominator is trailing.** The unit
is an EWMA whose span is the horizon, so **86% of its weight sits on the
previous `H` bars** at every interval here. At 1d the stride is exactly `H`, so
consecutive windows are adjacent and a picked anchor following a picked anchor
reads a unit that has already absorbed the first window's lift - and the ratio
cancels. At 15m and 1h the jitter leaves an unplanted gap of 24 bars on
average, so the absorption there is partial. `all` plants every anchor
at the picked level and measures that absorption; `isolated` thins the plant so
no two consecutive anchors are picked and measures the power against a
**transient** lift, which is the only kind a trailing unit can see. A
`delivered` column - the picked level's mean absolute log move against the
others', with no volatility unit in it - separates the plant arriving from the
statistic seeing it.

## Coverage actually run

RESULTS PENDING - the per-feed table from the report goes here, and it goes
**before** the verdict on purpose: a reader cannot judge a null without
knowing which cells were measurable, and a cell a guard refused is not a cell
that read nothing.

## The verdict

RESULTS PENDING.

## Deviations from the pre-registration

Numbered, each with the number that caused it. None was made after an outcome
statistic had been seen on the changed quantity: 1-8 were settled by the
mechanics, by a crash or by a count of how many levels a state could take, and
9 and 10 by the power sweep's own calibration - which the prereg puts before
the panel for exactly this reason.

1. **The arms are built in log space.** The prereg names
   `level_shield.bar_shuffle` and `walk_geometry`, which permute and resample
   **absolute** close-to-close steps and absolute spans. Over 19 years the
   price level moves up to 8.45x, and `fear-greed.md`'s fifth defect is the
   measured consequence: an absolute-step arm and its log twin disagreed by
   **more than the effect**, +0.142 against +0.236 on a real +0.213. Measured
   here on three 1d feeds, `walk-geometry-abs` reads mean `size` **1.404x** the
   real series' with a per-row sd of **10.19 against the real's 2.28**. The
   deciding arms are therefore the log-space versions; the absolute ones are
   carried at 1d as a named diagnostic and decide nothing.
2. **The deciding statistic is standardised.** The prereg's metric is the mean
   and dispersion of `size`; the statistic that decides is
   `spread / resid_sd`, a dimensionless between-level effect size, and the raw
   spread in volatility units is reported beside it for the cost check. The
   reason is measured: on eurusd 1d the real arm's `size` has mean 2.300 and sd
   1.904 while `level_shield.garch_bars` reads **1.257-1.410 and 1.054-1.195**,
   because that arm scales a bar range by the simulated **sd** against a
   **median** absolute return and so runs about 1.5x too wide. An
   unstandardised spread would compare an effect against a noise floor set by
   the arm's own variance.
   `test_the_deciding_statistic_is_scale_free_where_the_raw_spread_is_not`
   pins it.
3. **The de-overlapping stride carries a jitter at 15m and 1h.** There the
   lock is exact - 48 bars is exactly 12 hours and exactly 2 days - and with a
   fixed stride of `H` every 1h anchor fell in **one** hour of the day, so
   `session` and `through` would have been states measured on one value, which
   reads as a null without having been tested. The gap is now
   `H + U{0..H-1}`, so blocks stay disjoint and the cumulative stride walks
   over the whole day; it costs about a third of the rows. **At 1d the jitter
   is 0, and that is measured rather than assumed**: 20 daily bars is nearly
   four calendar weeks, but the store's holiday gaps accumulate drift, so at a
   fixed stride eurusd and gold both read all three monthly thirds (72/72/91
   and 81/76/78 of 235 anchors) and all five weekdays. A jitter there would
   have cost 10% of the rows on the one interval with 19 years in it, for
   nothing.
4. **The cuts are causal, not full-sample.** The prereg permitted full-sample
   quantile edges for the stratification variable and declared them. They are
   not used, for the strata or for the state cuts: a full-sample edge is not
   computable at the decision bar and the prereg's own causality rule is the
   stronger constraint. Every cut is the expanding empirical rank of the
   reading among the readings of bars closed at or before the decision bar,
   with anchors carrying fewer than 200 prior readings dropped. This is
   stricter than the prereg, not looser.
5. **`through` reads the month at 1d, and `pivot_room` the week.** The prereg
   says "early / middle / late in the period" without naming the period.
   Thirds of a *week* are not three states on daily bars: a weekday bar stamped
   at midnight reaches at most 5/7 = 0.714 of its week, so the last third is
   only ever the **Sunday** bar - gold, which has none, saw two levels, and
   eurusd's third level was made entirely of the FX Sunday open, which this
   desk already vetoes entries in. Thirds of a month are three buckets of about
   seven trading days. `pivot_room` keeps the weekly set at 1d because a daily
   set there is arithmetic on a one-bar "prior period", which
   `level-bounce.md` measured as 3,640 episodes over 20 distinct tags.
6. **The statistic centres on the stratum rather than flooring a table.** The
   contrast is a within-stratum fixed-effects de-meaning followed by a
   comparison of level means, which needs mass per level rather than per
   (stratum x level) cell. 68 rows at 15m over 5 quintiles and 4 session levels
   is 3.5 rows a cell, and `level-bounce.md`'s thin-cell defect is the recorded
   version: `grade_gap_for` guarded on the rows going *in*, and 209 rows over
   25 cells left almost every cell under the 10-episode floor while -0.0769 was
   still reported on the 26 that survived. The guard here sits on the mass that
   **survives** the flooring and that share is printed beside every number.
7. **The placebo pair is two carried feeds, not two Deriv volatility indices.**
   `carry-an-independent-placebo-pair` names the indices and **the store has
   none** - no synthetic family appears in it at any interval. The pair is
   `nzdusd` and `usdcad`, by a result-blind rule: they are the only two feeds
   in the carried set with no named prior claim anywhere in `findings.md` or
   this folder's index, and both have the full 19.2 years of daily history, so
   the placebo has the same power as the decision set. A lower-powered placebo
   would be the anti-conservative choice, since pass rule 3 only bites when the
   placebo *can* pass. It is a weaker control than a generated one and is
   labelled as such.
8. **The duty twin's construction is named here.** The prereg names the arm and
   what it must keep. It is implemented as a permutation of the outcome within
   the compression stratum, with the labels never moving - so the firing rate
   and the bars it fires on are identical by construction rather than by
   matching, and the stratum marginals are identical too.
9. **The power sweep has two plant shapes and a `delivered` column**, for the
   trailing-denominator absorption described under [Power](#power). The prereg
   asks for a strength sweep and does not say how many shapes it takes; one
   shape would have reported a blind spot that is really a property of the
   outcome's unit.
10. **The sweep's ceiling and draw count were raised** from a lift of 0.80 and
   four draws an arm, for the measurement under [Power](#power). Neither is
   pre-registered - the prereg asks for a sweep and not for its grid - and the
   change was made on the calibration, before any panel cell existed, which is
   the order the prereg puts the power sweep in for exactly this reason.

## Defects found on the way

- **`FearGreed` crashes on a dead window, and this is a production defect.**
  `sentiment._expansion` guards `middle <= 0.0` but not `now <= 0.0`, so
  `math.log2(now / middle)` raises `ValueError: math domain error` whenever the
  **last fifth** of the 60-bar window is entirely zero-range bars while the
  window's median range is positive. gold's 1d history has it. On the live desk
  `handle_bar` would propagate that into the Nautilus bar handler on any feed
  that goes flat for twelve bars. The one-line fix is to widen the existing
  guard to `if middle <= 0.0 or now <= 0.0`. **Reported, not made** - it is a
  production file and this is a research branch. It did not block the study: the
  harness catches it, records `nan` moods rather than the previous bar's stale
  reading (`absent is not zero`), counts the bars and prints the count in the
  coverage table, and `test_a_dead_window_is_a_missing_mood_and_not_a_stale_one`
  pins both halves. Three bars of gold 1d are affected.
- **`level_shield.garch_bars` is mis-scaled against its own close path**, by
  about 1.5x on the bar range, for the reason in deviation 2. It does not
  invalidate [level-shield.md](level-shield.md), whose distances are in the same
  range units on both arms, but any study normalising an outcome by the range
  inherits it. Reported, not changed: changing it would move that document's
  published numbers.
- **The pooled AUC was being computed on the centred residual**, which made the
  "unstratified" figure read 0.507 where its whole purpose is to show the free
  AUC. The two orderings are now fitted separately - the stratified one on the
  residual, the pooled one on the raw mean - and
  `test_the_pooled_auc_is_free_on_a_volatility_target_and_the_stratified_one_is_not`
  fails if they are collapsed again.

## How the run behaves when something goes wrong

A job that raises becomes **one `error` record** rather than taking the panel
with it, and the report prints every one of them **before any result**, because
a missing cell is not a null. `pool.map` propagates an exception out of a
worker, and this study has already hit the case: `FearGreed`'s crash on gold's
dead 1d bars killed a three-feed smoke run outright, and forty-one good jobs
are not worth losing to one bad feed. A bad `--store` is refused up front with
the flag named, rather than as a traceback once the panel is already spent.

## What was not done, and why

- **Nothing is costed.** Eight of the fourteen feeds carry two or fewer
  recorded quotes, so no median spread exists for them and none is invented. A
  result priced off a guessed spread is the one result that looks like a
  measurement and is not.
- **No 4h interval**, where the store holds about 714 days on the indices and
  0.17-0.23 years on FX and gold.
- **No synthetic cross.** Measured this session: a constructed cross's range
  over |close change| reads 4.03 against a 2.300-2.439 band on every real
  instrument, about 1.7x too wide, and `levels.chains` finds four displacement
  legs in nineteen years instead of eighty-three. The range-based volatility
  unit this study's strata depend on is invalid there.
- **No generated placebo pair**, for the reason in deviation 7.
- **No sweep of `H`, of the number of state levels, or of the strata count.**
  All three are frozen in the prereg. A sweep buys cells rather than evidence
  unless the claim changes.
- **`Hours`, the per-hour volatility profile, is not used.** It ships empty and
  normalised to geometric mean one, so switching it on would change nothing;
  and a profile invented here would look like a measurement and not be one.
- **No `Levels` or `BjorgumLevels` book.** `pivot_room` uses `Pivots`, which has
  no parameters at all and was the only book with power in `fear-greed.md`'s
  level section (3,232-3,685 touched levels against `Levels`' 158-241). A swing
  book is a different object with its own parameters and belongs in its own
  claim.

## The code

| file | what it is |
|---|---|
| `research/ideas/anchored_states.py` | the data, the six state readings off the production indicators, the log-space null arms, the de-overlapped anchors, the causal cuts and the planted effect |
| `research/ideas/anchored_states_agg.py` | the within-strata effect-size statistic, the duty and sign-flip twins, the cross-fit AUC pair, Cramer's V against the stratum, the t-based p and Benjamini-Hochberg |
| `research/ideas/anchored_states_run.py` | one invocation: sanity, the power sweep, the panel |
| `research/ideas/anchored_states_report.py` | the tables above |
| `research/ideas/test_anchored_states.py` | 36 tests, causality first, ending with one that runs the report over a hand-built panel so a schema change cannot break it silently |

Reused rather than rebuilt: `level_shield`'s `Series`, `load`, `venue_for`,
`units`, `compression`, `fit_garch`, `garch_bars` and the absolute-step arms;
`indicators/pivots.py` and `indicators/sentiment.py` as the state readings;
`strategies/timeframes.Frames` as the look-ahead guard;
`domain/costs.MAX_SPREAD_RISK_FRACTION` as the reachability bar.

## Running it

```sh
uv run pytest research/ideas/test_anchored_states.py -q
uv run ruff check --isolated --select F821 research/ideas/anchored_states*.py

uv run python -m research.ideas.anchored_states_run --out .data/out/anchored --workers 48
uv run python -m research.ideas.anchored_states_report .data/out/anchored
```

The sanity section runs first and unconditionally: a `blake2b` fingerprint and
byte count for each harness file, the venue resolved for every feed, and the
frozen settings per interval. `failed-sync-still-launches-the-run` is why -
`lab.sh run` prints "launched" whether or not the sync carried the new code, so
the run states what it is running rather than leaving it to be grepped for
afterwards.

Flags: `--out` (directory, one jsonl a section), `--workers`, `--store` (an
sqlite URI, so a copy of the store on another box needs no edit to this repo),
`--draws` (16, the prereg's minimum), `--power-draws` (4), `--feeds`,
`--intervals`, `--sections` (`power,panel`, power first so a broken plant is
cheap), `--power-feeds`.

42 panel jobs and 26 power jobs, one process each, about **3 CPU-hours** in
total. The wall clock is set by the longest single job rather than by the
total, and that is a 1d power leg at roughly 6 minutes, so **6 to 12 minutes
at `--workers 48`**. That is a projection from single-process legs and is
labelled as one: the contention error above is exactly what a projection taken
on a loaded box looks like. Each worker holds one series and its rows, so peak
memory is the interpreter count rather than the data - about 300 MB a worker.
