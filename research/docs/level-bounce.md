# Does price bounce at a level, and is a level graded by how it bounced before?

**Pre-registered 2026-11-03, before any panel result was read.** The rules,
the shape definitions, the pass rule and the direction of every claim below
were written and frozen first. Five changes were made during the build and
every one is recorded in
[Deviations](#deviations-from-the-pre-registration) with the number that caused
it; none was made after an outcome statistic had been seen on the quantity it
changed.

Two questions, and the second is the one nothing on this desk had asked.

1. **Does price bounce at all?** At a touch, what happens next, and is it
   different from a matched price that is not a level?
2. **Is a level graded by how it bounced before?** The claim is that a level
   whose **previous** departures were a spike/crash or a trend run is a
   *better* level than one price merely drifted away from - so bounce shape
   ranks a book of 24 and the five best are the ones worth placing against.

The payoff if true is a ranking, not an entry.

## Status

**The harness, the pre-registration, the nulls and the power design are
complete; the panel has not been run.** The development box has 8 cores and was
shared with another study at a load average of 19, so a multi-process sweep
there would have been both wrong and useless. The run is a single invocation
with a configurable output directory - see [Running it](#running-it).

[What a one-feed local pass shows](#what-a-one-feed-local-pass-shows) is a
single-process sanity check on **eurusd 1d at one draw an arm**, run to prove
the machinery end to end. **It is not the study.** Nothing in it clears the
pass rule, which needs 14 feeds, three intervals, four draws and the
cross-interval sign check, and one feed cannot distinguish a result from a
cell.

## The verdict table, to be filled from the panel

| question | answer |
|---|---|
| Does price bounce at a level, in mean R? | *pending the panel.* On the one feed measured, mean R is **-0.057 / -0.038 / +0.002** at 1R / 2R / 3R against a walk's exact zero, every one inside its own standard error |
| Does a level's **previous** bounce shape raise the mean R of its next touch? | *pending the panel.* On the one feed measured the R difference is **+0.0021 +- 0.0989** - a fortieth of its own noise - **while the same grade sorts the hit rate at AUC 0.5335.** If the panel holds that pattern the answer is the most interesting kind of null: the score works on the rate and the rate is not worth anything |
| Does the Kalman book beat parameter-free session pivots? | *pending the panel.* One feed: `levels` -0.0382 +- 0.0448 against `pivots` -0.0638 +- 0.0281, which is not a separation |
| Where does the test go blind? | *pending the power run.* The design is a **graded** plant with the uniform plant as a control that must read nothing |
| Does the harness reproduce a known number? | **Yes.** `hold_share`'s AUC reads 0.5078 on eurusd 1d against [`record-auc.md`](record-auc.md)'s 0.4977-0.5104 over twelve configurations - a different detector, a different venue policy and a different outcome definition landing inside the published interval |
| Did splitting the claim matter? | **Yes, and it is the methodological finding so far.** `run_share` 0.5523 against `bar_share` 0.4450 - **opposite signs**, averaged into `sharp_share`'s 0.5335. Reporting only the union would have published a shape effect that is one part restated outcome and one part the claim with its sign reversed |

## What decides, and what is only description

**Mean R decides. A hit rate does not.** A poor win rate is not a failure: a
score that raises expectancy while lowering the hit rate is still an edge. This
matters more here than in most studies, because a bounce rate is *precisely*
the quantity that is geometry - `fade-to-value`'s 82% return rate was matched
by a distance-matched placebo on every class and a random walk reads 0.825, and
[`magnet.md`](../../docs/magnet.md) has levels reached *less* often than an
arbitrary price the same distance away. So a bounce rate was never going to be
the finding. What a quality score has to improve is the **R of what follows the
bounce**, against the matched and shuffled arms.

Reported with every mean, and not optional:

* a **block-bootstrap standard error**, because nearby episodes share outcome
  bars and an ordinary one is far too narrow;
* the **per-trade sd**;
* the **sample the arm's own mean and sd imply** for |t| = 2. A score that
  selects sharper bounces selects larger moves, so it buys variance; two arms'
  means are not comparable without the evidence each rests on, and an arm that
  wins on the mean while needing four times the sample has not won;
* **profit factor** and win rate;
* a **deflated Sharpe over the full trial count**, since picking the best of 43
  instruments gives a winner every time.

### Why this is a lookahead trap by construction, and the form that is not

The shape of *this* bounce is known only after it, so grading this touch by
this touch is a lookahead and would read as a finding. **The usable claim is
that a level whose *previous* bounces were sharp predicts something about its
*next* touch**, and that is the only version measured. Every grade is built
from episodes strictly earlier at the same level, against a pooled prior that
is itself a running mean over strictly earlier episodes - never the
whole-sample rate, which would be the same lookahead through the back door.

`test_a_levels_first_episode_is_graded_on_the_prior_and_not_on_itself` is the
test that pins it: a level's first episode must carry exactly the prior.

## The rules, as frozen

* **Primary interval 1d**, where the power is: about 5,000 bars spanning
  19.2-19.9 years for the FX pairs and gold (first bars 2006-07) and 6,008 over
  11.95 years for the indices. 1h (0.8-1.0 years) and 15m (0.14-0.24 years)
  are carried only for the cross-interval sign-consistency requirement.
* **14 feeds, one venue each**, the venue chosen by bar count at that interval
  with ties alphabetically - a data-volume rule fixed before any result.
  Several venues of one feed are one instrument reported more than once, and
  counting them as independent cells is the multiplicity mistake.
* **The volatility unit** is a causal EWMA of the bar range over `unit_span`
  bars (20 at 1d, 48 at 1h and 15m), the range rather than a close-to-close
  sigma because `drive-q-from-the-range` is the measured choice.
* **A touch** at bar `i` is the book **as of bar `i-1`** coming within
  `TOUCH_VOL` 0.10 units of the bar's range, so the level existed before the
  bar that reached it. 0.10 is well inside the 0.40-unit touch scatter
  [`level-dispersion.md`](level-dispersion.md) fitted over 22,402 levels, so it
  does not manufacture touches.
* **De-overlapped**: an episode is scored only when the previous bar did not
  also touch that level and no earlier episode at that level was scored within
  the forward window itself, so two scored episodes never share an outcome bar.
* **Entry** is the touch bar's close - the only causal one, since the touch is
  known only once that bar has closed. **Stop** one unit through the level, so
  the level has to break before the trade is wrong. **Risk is measured from the
  entry, not from the level** (`risk-vol-is-not-the-stop-distance`), so a touch
  bar that closed a long way away buys a wider stop and a worse R, as it would
  live.
* **Targets at 1, 2 and 3 times the realised risk.** As multiples of risk and
  not of the unit, a driftless walk reaches the target with probability
  `1/(1+k)` and the expected R is **exactly zero at every k**, so no
  reward-to-risk can manufacture a result and any departure from zero is the
  finding. The headline is read at 2R.
* **Horizon** 20 bars at 1d, 48 at 1h and 15m.
* **Strata**: quintiles of trailing compression - `log(fast unit / slow unit)` -
  of each arm's **own** distribution, because the arms have different
  volatility processes. The grade comparison is additionally **within bins of
  how many previous episodes the level has** (1, 2, 3-4, 5+), because an
  eight-episode level is an older level in a longer-lived regime and not the
  same object as a two-episode one.
* **Bootstrap blocks** are `max(horizon, bars per day)` bars - 20 at 1d, 48 at
  1h, 96 at 15m - so a block is never shorter than the outcome window. A
  calendar day at 1d is one bar against a 20-bar horizon, and resampling those
  would share nineteen of twenty outcome bars and give a standard error far too
  narrow.
* **Two selections on the scored population, counted rather than hidden.** A
  touch whose bar **closed more than one unit through the level** leaves the
  stop already behind the entry, so there is no trade to price and it is
  dropped - which removes the episodes where the level broke hardest and tilts
  what survives in favour of the bounce. A touch whose descriptive +/-1 race
  never resolves is excluded from the hold rate and **kept** for R, since price
  sitting inside one unit of the level all horizon has no hold/break answer but
  does have a small R, and dropping it would discard the quiet outcomes and
  inflate every arm's variance. Both counts travel in the panel output as
  `skipped` and `undecided`. Both are applied identically to every arm, so the
  arm comparison holds; the absolute hold rate and mean R are conditioned on
  them and have to be read that way.
* **The compression quintile edges are full-sample**, which is the one
  non-causal quantity in the harness. It is a *conditioning* variable and not a
  predictor - both halves of every comparison sit inside the same cell and get
  the same edges - so it cannot manufacture a difference between high-grade and
  low-grade touches. `compression` itself is a causal EWMA.
* **Nothing is costed.** A hold rate, a bounce shape and an R measured in
  volatility units are geometry, so the primary result is **gross** and runs on
  the full history. Six feeds have enough recorded quotes to measure a median
  spread per venue (eurusd, gbpusd, gold, btc, us100, spx500) and the other
  eight have at most two, so no spread was invented for them - and the last two
  of the six are not the venue the live desk trades.

## The four kinds, and which one is the control

| kind | what it is | price read |
|---|---|---|
| `levels` | the Kalman book over `trend.pivots`, the primary - the book a strategy here actually reads | the posterior mean `Level.at(when)` |
| `bjorgum` | ATR-banded zones at confirmed pivots | `Zone.level`, the pivot price, **not the band** |
| `pips` | perceptually important points, confirmed turns only | `Point.price` |
| `pivots` | **the control**: PP, R1-R3, S1-S3, PH, PL, PC off the prior period - weekly and monthly at 1d, daily and weekly below | the published price exactly |

**`pivots` is the control and that is its main purpose.** It has no parameters,
no detector and nothing to fit, and a set is fully determined by the prior
period. **If the Kalman book does not beat pivots, the swing detection is not
earning its complexity** - and nothing on this desk has ever checked. Every
kind is reported against it.

`bjorgum` is read at `Zone.level` rather than through the band because the
band's width is the feature [`bjorgum.md`](bjorgum.md) found was about half
label leakage, and `Zone.near` exists precisely so that a touch test does not
enter through the thing under test.

**One asymmetry has to be stated rather than smoothed over.** `levels`,
`bjorgum` and `pips` carry a **per-instance** history, so a level accumulates
its own episodes. A daily pivot does not - it exists for one period and is
recomputed - so its history is **per name**: R1's record is R1's record across
periods. That is a different and far better-sampled object (20 tags and ~3,600
episodes on eurusd 1d against 248 tags and ~960 episodes for `levels`), and it
means **part 2's pivot column is not the same measurement as the other three**.
Part 1 is comparable across all four.

## The shape definitions, pre-registered

Every bit comes from code that already exists, named here so the write-up and
the harness cannot drift apart. The bits are a **mask, not a partition** -
`smc-primitives-overlap-and-are-closed` is measured on this desk, an engulf is
the opposite shape to a displacement origin, and the primitives overlap. A
harness forcing a partition would hide the overlap and pick a winner by the
order of its own `elif` chain, so the shares below do not sum to one and are
not meant to.

| bit | definition | code |
|---|---|---|
| `REJECT` | a hammer, shooting star or engulfing bar that **touched the level and closed away from it** | `indicators.candles.confirms` |
| `SPIKE` | within 2 bars, a bar that is impulsive (body >= 0.70 of range), at least **1.5 units wide**, pointing away **and closing on the away side** | `indicators.levels.Candle.impulsive` at the desk's `PUSH_BODY` |
| `LEG` | the multi-candle displacement leg, starting within 2 bars and pointing away | `indicators.levels.chains` at `PUSH_MIN` 2 / `PUSH_BODY` 0.70 / `CHAIN_GAP` 1 |
| `RUN` | Kaufman efficiency of the 4 closes from the touch **>= 0.60**, with the net move away clearing 0.5 units | `indicators.trend.ratio` |
| `DRIFT` | departed by 0.5 units and none of the above - **the residual the question compares against** | — |
| `THROUGH` / `STALL` | did not depart, ending on the far side of the level or not | — |

`RUN` uses `trend.ratio` rather than a hand-rolled consistency rule because
"net travel over gross travel" *is* "two or more bars one way with one or two
small hiccups", and the repo's copy exists because Nautilus's own
`EfficiencyRatio` is biased by `1/period` and can never report a perfectly
efficient move. Efficiency alone is direction-blind - a clean run **through**
the level is just as efficient - so the move condition is what makes it a
bounce and is what carries the sign. `efficiency` went into this repo unsigned
once and the note says the obvious way to trade it would have had the sign
backwards.

`RUN_EFF` is **swept** over 0.45, 0.60, 0.75, 0.90 and the whole grid is
reported with its mean rather than the best cell with its z:
`sweep-thresholds-on-the-mean-not-z` is recorded because a z grid faked a ridge
at the chosen threshold where the mean grid was monotone.

### The grades

Each is a shrunk share over a level's **previous** episodes only, two
pseudo-episodes toward the running pooled rate.

| grade | numerator | why it is carried |
|---|---|---|
| `sharp_share` | `REJECT \| SPIKE \| LEG \| RUN` | **the claim, as the user put it**: either shape counts |
| `run_share` | `RUN` | the half that **entails departure**, so it is the half most at risk of restating the previous episode's outcome |
| `bar_share` | `REJECT \| SPIKE \| LEG` | **shape uncontaminated by outcome** - these do not require the departure to hold |
| `hold_share` | the raw same-side record | the **reproduction arm**: [`record-auc.md`](record-auc.md) puts this between 0.4977 and 0.5104 across twelve configurations, so a reading far from 0.50 means the harness is wrong before it means anything about levels |
| `hold_dev` | `\|hold_share - 0.5\|` | the decisiveness reading that scored 0.6006 against the raw record's 0.5005, and the reason a *magnitude* grade is worth testing at all |

Splitting `sharp_share` was pre-registered and immediately earned its place:
on eurusd 1d the two halves point in **opposite directions**, `run_share` at
AUC 0.5523 and `bar_share` at 0.4450, and the union at 0.5335 was hiding both.
Reporting only the union would have left "which one carried it" unanswerable.

## The nulls, reused rather than rebuilt

[`level-shield.md`](level-shield.md)'s `ARMS` is imported whole, so the two
studies' arms are the same objects and not two implementations of one idea.
Every arm goes through the **same detector** over the same bar geometry.

| arm | keeps | removes |
|---|---|---|
| `placebo` | the real bar path exactly; every level displaced 1.5-3.0 units, refused within 0.70 units of any real level | the level being a level |
| `garch-bars` | volatility clustering, fat tails, bar wickiness | path structure |
| `walk-geometry` | bar wickiness, the step distribution (`node/surrogates.walk_with_bar_geometry`) | path structure **and** clustering |
| `bar-shuffle` | each bar's own shape, the marginal step distribution | all memory |

**The placebo's offset is drawn once per level, not once per bar.** That is the
whole point: a placebo has to persist so its own previous episodes can grade
its next one. Redrawing per bar would give every placebo an empty record and
part 2 would have a real arm and no matched arm at all.

**`garch-bars` is why the shuffle is not enough.** Clustering is the mechanical
route by which "this level bounced sharply before" predicts a sharp bounce
next: a spike is a large bar, large bars cluster, so the grade is partly "this
level was touched in a volatile stretch". An arm without clustering cannot
judge that. And `bar-shuffle` is the arm that names the mechanical part -
`let-the-shuffled-twin-name-the-mechanical-observables`, and
`level-shield.md` is the instance, where the raw mirror gap read as a barrier
with the sign backwards until the shuffle named it.

Real is read against the **hardest** arm, the maximum over all four and all
draws, never against zero alone.

## The pass rule, pre-registered

A grade survives for a kind only if **all** of:

1. the real R difference exceeds the **hardest null arm's** R difference;
2. the sign agrees between 1d and at least one of 1h/15m - `level-shield.md`'s
   single best cell failed exactly this and was recorded rather than built on;
3. it survives Benjamini-Hochberg over every cell (feed x interval x kind x
   grade);
4. the deflated Sharpe over the full trial count clears the expected maximum;
5. the implied sample is not worse than the arm it beats by more than it gains.

And separately, for the complexity question: **`levels` earns its detector only
if its mean-R excess over its own nulls beats `pivots`' excess over its own**,
on a majority of feeds.

The direction is pre-stated. The claim predicts a **positive** R difference for
`sharp_share`. A negative one is not a weaker version of the claim, it is the
opposite of it, and will be reported as such.

**If nothing survives, the null ships and no gate ships**, and the write-up
says what would have had to be true. The prior for that is poor and openly so:
`topology-restates-volatility` has levels, ranges and shapes all reading null
once volatility is stratified; `statespace-conditional-holds.md` read tau
0.0109 over 279 levels against a simulated 0.0085, so a level's own record is
sampling noise; [`level-signatures.md`](level-signatures.md) ran nineteen
observables over 6,902 touches and found nothing further than 0.006 from AUC
0.5 while catching a planted 0.02-sigma shift at p 0.020; and
[`level-shield.md`](level-shield.md) found a level in the path does not suppress
the move over 210 cells. **A clean null is the valued result.**

What is nonetheless new, and why the question is worth a measurement: those
studies tested a *binary, shapeless* record and the *touch bar*. This tests the
**departure's shape**, which is a magnitude - and the one reading that ever
beat the raw record on this desk was `|record - 0.5|` at 0.6006 against 0.5005,
also a magnitude.

## Power, before the null

Two sweeps, because the study asks two questions and one plant cannot answer
both. Both reuse `level_shield_power`'s construction: price walks with this
market's bar geometry, the production `Levels` book is maintained causally over
the planted bars, and steps that would cross a level are reflected about it.

**Sweep 1, part 1.** Uniform reflectivity over 0, 0.1, 0.25, 0.5, 0.75, 1.0 -
`level-shield.md`'s own grid, so the two studies' blind points sit on one axis.

**Sweep 2, part 2, and this is the one the study needs.** A uniform barrier
makes every level the same, so a grade over a level's own past **cannot**
predict its future - at uniform strength the correct answer is *zero grade
difference however hard the barriers are*. That makes the uniform plant a
**control that must read nothing**, which the skill calls the strongest kind,
and not a power test. The graded plant gives each level its **own**
reflectivity, drawn once on first sight from `0.5 -/+ spread/2` by a fair coin,
swept over spread 0, 0.2, 0.4, 0.6, 0.8. Now levels genuinely differ, a level's
past departures reveal which kind it is, and the grade has something real to
find.

The reflection generates the *shape* as well, and that is deliberate rather
than incidental: a step turned back about the level is a move away as large as
the move that would have gone through, so a strongly reflecting level emits
larger and straighter departures. The plant therefore delivers the signal
through the same channel the measurement claims to read it from.

**Both sweeps are calibrated on the R difference, not on the hold-rate gap.**
That is not a detail: the one feed measured has a grade that sorts the hit rate
at AUC 0.5335 while moving mean R by a fortieth of its standard error, so the
two statistics demonstrably go blind at different strengths and a power sweep
on the rate would report the blind point of something nothing is judged on.
The hold-rate gap is printed beside it.

## What a one-feed local pass shows

*Sanity check only - eurusd 1d, one draw an arm, one process. Run to prove the
machinery end to end, not to answer anything. **Nothing here clears the pass
rule**, which needs 14 feeds, three intervals, four draws and the
cross-interval sign check.*

The numbers worth recording from it, because they are what the full panel will
be read against:

| reading | eurusd 1d, `levels` | what it means |
|---|---|---|
| episodes | 960 over 248 level tags | the sample a 19.2-year feed gives one kind |
| hold rate | 0.5500 +- 0.0156 | descriptive; 0.50 is the walk's |
| mean R at 1R | **-0.0570 +- 0.0321** | t -1.77 |
| mean R at 2R | **-0.0382 +- 0.0448** | t -0.85, per-trade sd 1.357 |
| mean R at 3R | **+0.0024 +- 0.0516** | t +0.05 |
| `hold_share` AUC | **0.5078** | **the reproduction check**: [`record-auc.md`](record-auc.md) reads 0.4977-0.5104 |
| `sharp_share` AUC | 0.5335 | the claim, on hit rate |
| `run_share` AUC | 0.5523 | the half that entails departure |
| `bar_share` AUC | **0.4450** | pure shape, **opposite sign** |
| `sharp_share` R difference at 2R | **+0.0021 +- 0.0989** | **the point of the metric change** |

Two things in that table are worth stating plainly before the panel runs,
because they are what the panel is most likely to confirm.

**The hit-rate signal does not convert into R.** `sharp_share` reads an AUC of
0.5335 against the next touch holding, which read alone looks like the finding
this study was looking for. The same grade's **R difference is +0.0021 against
a standard error of 0.0989** - a fortieth of its own noise. A score can sort
touches by whether they hold and be worth nothing, because what it sorts out
are small wins and what it sorts in are larger losses. This is exactly why mean
R decides and the rate is description.

**Splitting the claim was decisive and the union was hiding it.** `run_share`
and `bar_share` point in **opposite directions** - 0.5523 against 0.4450 - and
`sharp_share`'s 0.5335 is their average. `run_share` is the half that requires
the departure to have held, so it is the half closest to being an outcome
autocorrelation rather than a shape reading; `bar_share` is shape with the
outcome taken out, and it reads *below* 0.5. Had the pre-registration kept only
the union, the write-up would have reported a shape effect that is one part
restated outcome and one part the claim with its sign reversed.

The pivot control on the same feed: 2,297 episodes over 20 tags, hold 0.539,
mean R at 2R **-0.0638 +- 0.0281**. Against `levels`' -0.0382 +- 0.0448 that is
one feed and well inside noise, which is the honest statement until 14 are in.

**The whole chain has been run end to end on a 2,500-bar slice** - `measure` to
`panel.jsonl` to the report, with the `placebo` and `bar-shuffle` arms,
Benjamini-Hochberg, the deflated Sharpe, the shape-share table and the
kinds-against-pivots column all producing output. The numbers from that slice
are not quoted here because one draw on half a feed is not a measurement, and
the deflated Sharpe over **two** cells is degenerate by construction. It
establishes that the panel will produce a readable report and nothing more.
`skipped` ran at about 3% of touches on that slice (38 of 1,186), so the
no-trade selection described above is small.

## Running it

Three invocations, in order. `BOUNCE_OUT` is the only path that has to be set
and must be the same for all three - the report reads what the other two wrote.

```sh
# 1. the panel, and the RUN_EFF grid beside it
BOUNCE_OUT=<output-dir> BOUNCE_WORKERS=<cores> BOUNCE_DRAWS=4 \
  uv run python -m research.ideas.level_bounce_run

# 2. the power sweeps: planted bounce, then planted grading
BOUNCE_OUT=<output-dir> POWER_FEEDS="eurusd gold spx500" \
  POWER_INTERVALS="1d" POWER_DRAWS=3 \
  uv run python -m research.ideas.level_bounce_power

# 3. the tables
BOUNCE_OUT=<output-dir> uv run python -m research.ideas.level_bounce_report
```

`BOUNCE_STORE` points at a copy of `prices.db` if it is not at
`.data/prices/prices.db`. `BOUNCE_FEEDS`, `BOUNCE_KINDS` and
`BOUNCE_INTERVALS` narrow the panel for a shorter pass.

168 jobs (14 feeds x 3 intervals x 4 kinds), 17 passes each at `BOUNCE_DRAWS`
4. **`BOUNCE_WORKERS` defaults to 2 and not to the core count**, deliberately:
this file gets run on a shared box by accident and a pool sized to the machine
starves whatever else is on it, which happened here.

**The surrogate arms dominate the budget and that is the thing to size on.**
Replaying the book bar by bar is the cost; the estimators are 0.3s a pass.
Clean figures, one process on an idle box, for the **real** arm at 1d:
`levels` 1.3s, `bjorgum` 0.2s, `pips` 3.4s, `pivots` 0.3s - about 5s for all
four.

A surrogate pass runs **2 to 20 times slower** than its real counterpart,
worst on `pips` and `levels`. Those multiples were measured on a box shared
with another study, so they are upper bounds contaminated by contention rather
than clean per-arm timings, and the range below is wide for that reason rather
than from optimism. At `BOUNCE_DRAWS` 4 a job is 17 passes (1 real, 4 placebo,
12 surrogate).

| what | estimate |
|---|---|
| the panel, 168 jobs | **3-8 CPU-hours; 15-40 min wall** at a high worker count. The bound is the longest single job, not the total, so more workers than 168 buys nothing |
| the power sweep, 11 grid points x 3 draws x 3 feeds | **20-60 min**, one process per feed |

Nothing is written until the first job returns, because `pool.map` yields in
order. **Several minutes of apparent silence at the start is normal and is not
a hang** - that mistake cost two restarts here.

## The code

| file | what it is |
|---|---|
| `research/ideas/level_bounce.py` | the data, the four books, the touch episodes, the shape bits, the races and the causal grades |
| `research/ideas/level_bounce_agg.py` | the estimators as count tensors with a block bootstrap, and the R statistics |
| `research/ideas/level_bounce_run.py` | the panel and the `RUN_EFF` grid, one job per (feed, interval, kind) |
| `research/ideas/level_bounce_power.py` | the uniform plant, the graded plant, and both sweeps |
| `research/ideas/level_bounce_report.py` | the tables above, with Benjamini-Hochberg and the deflated Sharpe |
| `research/ideas/test_level_bounce.py` | 18 tests, run with `uv run pytest research/ideas/test_level_bounce.py` since `research/` is outside `testpaths`. The first two are the lookahead guards |

## What was not done, and why

* **The panel and the power sweeps have not been run.** The development box has
  8 cores and was shared with a concurrent study at a load average of 30, so
  every multi-worker attempt starved. Everything reported here is from
  single-process passes. The commands and the budget are above.
* **No quality score ships, and none should until the panel has run.** The
  claim has not survived anything yet - on the one feed measured its R
  difference is a fortieth of its own standard error - and `publish, then
  measure, then gate` is the ordering every refuted gate on this desk skipped.
  What would have to be true is set out in
  [The pass rule](#the-pass-rule-pre-registered); the shortest version is that
  `sharp_share`'s R difference has to clear its hardest null arm, keep its sign
  across intervals, survive Benjamini-Hochberg and clear a deflated Sharpe, and
  that `bar_share` - shape with the outcome taken out - has to stop reading
  below 0.5.
* **Nothing is costed**, by design. Six feeds could carry a spread (eurusd,
  gbpusd, gold, btc, us100, spx500) and the other eight have at most two
  recorded quotes, so no spread was invented for them. Note that `us100` and
  `spx500` are not on the venue the live desk trades. A cost pass is the
  obvious follow-up **only if** a kind survives gross - costing a null buys
  nothing.
* **No 4h interval.** The store holds about 714 days on the indices there and
  0.17-0.23 years on FX and gold, which is not enough for a per-instance level
  record.
* **The `bjorgum` part-2 column may stay empty even on the full panel.** Its
  zones are short-lived, so after de-overlapping, 209 usable eurusd 1d
  episodes spread over 25 compression-by-age cells left nothing above the
  floor. That is a property of the primitive, not a harness fault: a zone that
  is rarely re-touched cannot have a record. Part 1 is unaffected.
* **A second `Pivots` boundary was not tested.** `boundary` can shift the
  session cut to the broker's 21:00 FX day, and the `Pivots` docstring records
  that 21:00 is exactly where a survivorship confound lives. The default UTC
  cut is used throughout because it is the one reproducible across observers;
  comparing the two is a separate measurement.

## Deviations from the pre-registration

* **`SPIKE` was split into `SPIKE` and `LEG` after a firing-rate measurement,
  before any outcome was read.** The first version defined a spike as a
  `chains` displacement leg **and** a 1.5-unit-wide bar, which fired on
  **0.2%** of eurusd 1d episodes - no test at all. Measured separately, a
  `chains` leg pointing away within two bars fires on 1.0% of eurusd episodes
  and 3.3% of gold's, where a single impulsive bar away fires on 12.0% and
  20.1%. Both are kept and reported apart. The change was made on the firing
  rates alone; no hold rate, R or grade statistic had been computed on either
  version.
* **The pivot period is scaled with the bar, which is not the indicator's
  default**, and without this the control would not have been one. `Pivots`
  defaults to daily and weekly, which is right on intraday bars; **on 1d bars a
  daily session is a single bar**, so the whole set would be recomputed every
  bar from one bar's high, low and close - `R2` would be the prior *bar's*
  range rather than the prior period's and the ten prices would move every bar.
  Measured on the default, eurusd 1d gave **3,640 episodes over 20 tags**
  against `levels`' 960 over 248, which is not a comparable object and would
  have made the control look better evidenced than it was. Scaled to weekly and
  monthly at 1d - which the `Pivots` docstring says 19 years of daily bars
  support - the same feed gives 2,297 episodes over 20 tags, hold 0.539 and
  mean R at 2R of -0.0638 +- 0.0281. The argument for the change is structural,
  not an outcome: a one-bar "prior period" is not a period.
* **The deciding metric moved from the hold rate to mean R** on instruction
  during the build, before the panel was run. The hold rate is retained as
  description. This is the correct call for the reason recorded above: a bounce
  rate is the quantity that is geometry.
* **The placebo's offset is stored in price, not in volatility units.** Held as
  a unit offset and re-multiplied by the current unit each bar, a placebo level
  is a price that *wanders as volatility changes* - and a wandering level is
  reached more often in a volatile stretch, which is precisely the confound the
  compression strata exist to remove, re-introduced inside the control. It
  would have shown up as the real arm failing to beat its placebo for a reason
  that has nothing to do with levels. Fixed in price at first sight, the
  placebo tracks its real level's own drift plus a constant.
  `test_a_placebo_does_not_wander_when_volatility_changes`.
* **`r_mtm`'s denominator is the level's one unit, not the entry's risk.**
  Measured: with the entry risk it reads a per-trade sd of 10.3 on eurusd 1d
  and 20.6 on pivots, because a touch bar closing just through the level leaves
  a risk near zero and the ratio explodes. Flooring or dropping those episodes
  would be worse than either, since they are the episodes where the level
  already failed and excluding them selects in favour of the bounce. With a
  fixed denominator the arm is the forward excursion in units and the sd is
  3.0.

## Three defects the tests caught on the way

* **A gap reported on 26 episodes past a 100-episode guard.** `grade_gap_for`
  checked the row count going in, so 209 bjorgum rows spread over 25
  compression-by-age cells left almost every cell under the 10-episode floor
  and it returned -0.0769 on the 26 that survived, as though it were a
  measurement. The guard is now on the mass that survives flooring.
  `test_a_cell_thinner_than_the_floor_reports_nothing_rather_than_a_gap`.
* **One shared `stopped` flag would have closed every reward-to-risk at the
  first stop.** Each target is its own trade: the 1R target can fill on bar 3
  while the 3R trade is still live and stops on bar 7. The first version
  carried one flag, which charges the banked 1R trade for a loss it had already
  taken profit out of - about one R on every episode that turns after a partial
  move. `test_a_tighter_target_can_pay_while_a_wider_one_on_the_same_touch_stops_out`.
* **`hash(arm)` seeded the surrogate draws.** String hashing is salted per
  process, so the run was not reproducible and two workers would disagree about
  which draw they had made. Seeded off the arm's position instead.
