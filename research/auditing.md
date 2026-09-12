# The corpus, audited against this desk's own false-positive rate

[calibrating.md](calibrating.md) measured what the methods in this folder do on
a world where the true answer is known to be zero. This page spends that
measurement on the fifty-odd documents that were written before it.

The four numbers it turns on:

| | |
| --- | ---: |
| a twelve-row cut of a null book throws at least one spurious interval | **33.10% +-1.05** |
| one whole `spending.py` run does | **63.05% +-1.08** |
| the percentile bootstrap's miss rate at n=29 / n=8 | **7.05%** / **10.55%** |
| a feature read with no permutation control fires on a null book | **98.50% +-0.38** |

The last is the one that reaches furthest. `winning.md` introduced the
permutation control on 2026-09-11; **every scan before that date is suspect by
construction**, and this folder has several.

`research/harness/calibaudit.py` re-runs every cut the closes export can
reproduce rather than arguing from the published number. Run:

```
.venv/bin/python research/harness/calibaudit.py
```

## How a verdict is assigned

Three outcomes, and the distinction between the first two is the whole point:

* **survives** - the claim holds under the correction, or it never depended on
  an interval in the first place.
* **weakened - keep the mechanism, drop the interval** - there is an
  independent derivation, cost decomposition or arithmetic identity that
  reaches the same place, and the statistics were decoration on top of it.
  Nothing needs to change except how the claim is quoted.
* **withdrawn** - the number is what the method produces on noise, and there is
  no mechanism underneath.

Two cautions, because this audit can be wrong in both directions.

**A mechanism plus a weak interval is not the same thing as an interval alone.**
`generators.md` measures a factor of six hundred between two rows of the same
table and explains it with a monotone price process; that does not become
fragile because the table has ten rows. Each verdict below says which of the two
it is judging.

**A null is not vulnerable to a multiple-comparison correction the way a
positive is.** Correcting a null makes it more null, which is not informative.
What *does* bear on a null is power, and `calibrating.md` measured this desk's
to be poor: the feature scan finds an injected +20%-of-risk edge 12.00% +-2.06
of the time at 397 closes. So several nulls in this folder are downgraded from
"nothing is there" to **"this book cannot answer the question"**, which is the
reading `winning.md` already gave itself.

## 1. What the re-run says

`calibaudit.py` reproduces every published point estimate it reprints - the
pre-registered condition that would otherwise have made the comparison
meaningless - and the studentised interval runs 1.14 to 1.20 times the width of
the percentile one on live rows, against the 1.10 calibrated at n=29.

| table | rows | rows with an interval | family-wise | excluded zero | survive the correction |
| --- | ---: | ---: | ---: | ---: | --- |
| `spending.md` by strategy | 12 | 5 | 32.6% | 1 (`snap`) | **none** |
| `spending.md` by exit kind | 5 | 5 | 27.4% | 2 | `stop`, `target` - both by construction |
| `spending.md` by reward-to-risk band | 3 | 3 | 16.9% | 1 (2:1 and above) | **none** |
| `spending.md` by interval | 8 | 5 | 29.2% | 1 (`1m`) | **none** |
| `spending.md` by hour | 23 | 4 | 30.1% | 1 (hour 14) | **none** |
| `instruments.md` by instrument | 55 | 13 | **71.6%** | 3 (gold, us30, boom_1000) | **none** |
| the generated half, by instrument | 19 | 8 | 53.9% | 1 (boom_1000) | **none** |

Four things to read off it.

**`snap` does not need the multiplicity correction to fall.** Swapping the
percentile interval for the studentised one at an uncorrected 5% already takes
it from `[-64.7%, -1.4%]` to `[-65.2%, +8.2%]`. The correction is not what
kills it; the interval construction is.

**Two cuts nobody published would have looked like findings.** `1m` at
**-33.1% [-61.2%, -1.1%]** and hour 14 at **-53.1% [-83.9%, -20.4%]** both
exclude zero on the shipping method. `spending.md` ran both cuts and reported
neither, saying so at the time - which is the correct behaviour and is also the
reason those two numbers are here rather than in a recommendation.

**The instrument table is the worst case in the folder.** 55 rows, 13 of them
testable, and a **71.6%** chance that at least one row misses its true value by
chance alone. Three rows exclude zero and none survives.

**The exit-kind table's two survivors are arithmetic.** A `stop` returns about
-1R because that is what a stop is, and a `target` returns about its own ratio.
They are a check that the accounting works, not findings, and should never be
counted among the intervals a page found.

### And the uncontrolled feature read, on the live book

The scan `winning.md`'s permutation control replaced, run on the live record:
**59 decision features with enough coverage to tercile, 282 closes carrying R,
and 5 separate their terciles at an uncorrected p<0.05.** A null book of 397
closes carries **5.5 of 45**.

| feature | t | top tercile minus bottom |
| --- | ---: | ---: |
| `macro_inflation_surprise` | 3.33 | +0.539R |
| `forecast_bps` | 2.61 | +0.376R |
| `macro_us_breakeven` | 2.10 | +0.331R |
| `macro_us_real_yield` | 2.09 | +0.329R |
| `wick_below_sd` | 1.99 | +0.270R |

Bonferroni over the 59 needs |t| > 3.37 and **none survives**. Three of the five
are the slow macro series `shared/liveness.py` already documents as
near-constant inside a window this short - a tercile of a monthly series over
twelve days is a tercile of the date.

**The live count is the null count.** Any page that reported the top of a
feature table without a permutation control was reading this.

## 2. The pages the desk acts on

### `generators.md` - the stop slippage, and `stop_overshoot` - **survives**

*Judged on: a mechanism, with statistics that agree.*

A stop on the spike side of Boom or Crash fills **10 to 19 R** past where it was
placed, against **+0.02R** on the grind side of the same instrument at the same
width. n is 1,725 to 3,089 non-overlapping entries per feed.

The multiplicity question does not arise. The mechanism is that
**84,506 of `boom_500`'s 84,701 tick-to-tick moves are down and 160 of the 162
up-moves are spikes**, so a stop above a Boom short can only ever be jumped
over. Two control rows behave exactly as that mechanism predicts and were chosen
in advance: `volatility_75_index` has no spike mechanism and slips +0.061R with
**not one trade in 435** past half an R, and `step_index` is the deterministic
case where the loss is bounded at one increment and every trade lands there.

An effect of a factor of six hundred, with a mechanism, a bound and two
controls, is not something a ten-row table can manufacture.

`DEFAULT_STOP_OVERSHOOT` ships **2.0** on `boom.sell` and `crash.buy`, which is
the multiple measured at a fifty-spread stop - the most conservative cell in the
table, and documented in `config.py` as "a floor rather than the answer". **The
shipped setting is under-applied relative to its own evidence**, which is the
right direction for a setting to err in.

### `exiting.md` - the exit that ships - **weakened, and the page got there first**

*Judged on: an interval, over a replayed population.*

`SweepAware` carries `target_multiple=6.0`, `trail_vol=0.5` and
`break_even_at=1.0` because `exits.py` scored ride's exit at **+0.655R against
+0.099R**. That number was two look-aheads. Corrected on the shared kernel and
run over the same 18,272 calls, ride's advantage is **+0.046R pooled and +0.057R
on the verify half** - the bug was worth **+0.386R** to a trailing policy and
+0.006R to a fixed-target one, exactly the asymmetry predicted before the run.

The page says the decision "rested on evidence about ten times weaker than the
number it was made on", and it is right. What the audit adds is where the
remaining +0.046R lives: the policy is **worse on 64% of the same trades** and
wins through a thin right tail. A mean carried by a tail has an effective sample
size of its tail members, not of its 18,272 rows, and the bootstrap that would
put an interval on it is the one `calibrating.md` found over-rejecting on
skewed, heavy-tailed distributions at small effective n.

**Keep the exit - it is not measured negative - and stop quoting +0.655R.** The
live comparison the page asks for (ride and sweep-aware running side by side) is
the right test and no replay will settle it.

#### The twenty-one-dimension regime cut - **withdrawn as a survivor list**

`sweepregimes.py` cuts the replayed trades **21 ways** and reports seven
survivors against a control of "three random buckets of the same trades", gap
0.069R. Three random buckets is not a null for the maximum of twenty-one
dimensions; it is a null for one. `winning.md`'s own control - permute the
outcome, re-run the whole scan, take the largest gap - is the shape this needs,
and `calibrating.md` measures the difference between having it and not at
**4.80% against 98.50%**.

Two of the seven do not need it. **`vol_bps` is the spread**: charge no spread
and it drops out of the survivor list entirely, and the cost in R is
`spread / (risk_vol * vol_bps)`, which grows without bound as volatility falls.
That is a decomposition, not a regime, and the page says so. **`risk_vol`
survives two decompositions with about 60% unexplained** and is the one real
open question in the list.

**The other five - `vol_stretch`, `origin_size_vol`, `edge`,
`origin_distance_vol`, `strength`, at gaps of 0.152 to 0.186 against a
one-dimension control of 0.069 - are the top of a twenty-one-way scan with no
max-statistic null, and should not be treated as survivors.**

### `giveback.md` - the give-back, and the `confluence-scalp` change - **split**

*Judged on: a mechanism for the shape, an interval for the size.*

Re-run on the current export with a t interval on what each strategy did not
keep - the quantity with money in it:

| strategy | n | peak | kept | gave back | 95% | corrected over 5 rows |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| `thesis-only` | 159 | +0.267 | -0.136 | **+0.403** | [+0.289, +0.516] | [+0.252, +0.553] |
| `sweep-aware` | 77 | +0.564 | +0.154 | **+0.410** | [+0.286, +0.534] | [+0.246, +0.575] |
| `runner` | 17 | +0.003 | -0.127 | +0.130 | [-0.159, +0.418] | [-0.268, +0.527] |
| `confluence-scalp` | 10 | +1.401 | -0.357 | **+1.758** | [+0.382, +3.134] | **[-0.218, +3.734]** |
| `fade-to-value` | 9 | +0.020 | -0.573 | +0.593 | [+0.211, +0.975] | [+0.037, +1.149] |

**The give-back itself survives**, on the two rows with a sample: about
**0.41R a trade** on both `thesis-only` and `sweep-aware`, intervals excluding
zero before and after the correction. `sweep-aware`'s n has grown from 47 to 77
since publication and the estimate moved by 0.005R, which is the best kind of
replication.

**The `confluence-scalp` row does not survive.** +1.758R on ten closes reaches
`[-0.218, +3.734]` once the table's five testable rows are corrected for, and
that row is the one a live setting was changed on.

But the change was not made on the interval. It was made because that strategy
**had no exit policy at all**, and the argument for giving it ride's was that
its mean peak of 1.401R sits inside the thresholds rather than above them. The
page says so explicitly: *"Not because the replay supports it - it does not."*
**Keep the change, drop the row as evidence**, and let the live `best_r`
distribution settle it as the page already proposes.

The *mechanism* section of that page is the strongest thing in it and needs no
correction at all: a trail of `room / risk_vol` R can only replace the original
stop once it is in front of it, `manage.stop_for`'s widening **has no ceiling**
and reaches 2,239v over 47,233 level calls, and **11.1% of 54 closes ever reach
1R** against a median peak of 0.445R. That is arithmetic over the live
distribution, and it is why the two changes it argues for were correctly *not*
shipped on it.

### `edge.md` and `giveback.md` - `confluence-scalp`, switched on and off in three days - **both rows withdrawn**

*Judged on: two intervals, on the same strategy, pointing opposite ways.*

This is the sharpest case in the folder and it is worth setting out in order.

**2026-09-11, morning.** `giveback.md` gives `confluence-scalp` ride's exit and
turns it back on, citing a mean peak of **+1.401R** and a give-back of
**1.758R** over **10 closes**.

**2026-09-11, later.** `edge.md` removes it, citing a bootstrap interval of
**[-12.21, -0.04]** on money over 30 closes and **[-0.696, -0.018]** on R over
10 - both excluding zero, "**on the evidence above**".

Recomputed on the current export, the point estimates reproduce exactly -
**-6.371** on money and **-0.357** on R, so this is the same data. The
intervals do not:

| | n | mean | `edge.md`'s percentile bootstrap | a t interval | corrected over the 11 rows |
| --- | ---: | ---: | --- | --- | --- |
| money | 30 | -6.371 | **[-12.21, -0.04]** | **[-12.81, +0.06]** | [-16.05, +3.31] |
| R | 10 | -0.357 | **[-0.696, -0.018]** | **[-0.765, +0.050]** | [-1.03, +0.32] |

**Both bootstrap endpoints sit within a hair of zero - -0.04 and -0.018 - and
the better-behaved interval covers zero on both.** That is not a matter of
taste: `calibrating.md` [7] measured the two constructions head to head on 2,000
null books at these sample sizes, and the percentile one misses at **7.70%**
where the studentised misses at **4.40%**. The endpoint that decided this is
inside the gap between them.

So the strategy was **turned on** on a ten-close row and **turned off** on a
thirty-close row, and neither row survives. The right reading of both is that
`confluence-scalp` has never had a sample.

**And the same table contains an inversion nobody acted on.** Under a t
interval over the same 688 closes:

| strategy | n | mean $ | 95% | corrected | |
| --- | ---: | ---: | --- | --- | --- |
| **`fade-to-value`** | 30 | **-11.45** | [-18.84, -4.06] | **[-22.56, -0.34]** | **survives both** |
| `runner` | 47 | -5.34 | [-10.07, -0.61] | [-12.35, +1.68] | 5% only |
| `snap` | 29 | -7.25 | [-14.28, -0.23] | [-17.84, +3.33] | 5% only |
| `confluence-scalp` | 30 | -6.37 | [-12.81, +0.06] | [-16.05, +3.31] | neither |

`fade-to-value` is the one row in the strategy table that excludes zero **after**
the correction, on money and at 5% on R (-0.573 [-0.938, -0.207]). It is also
the one strategy in that group that was left running. Nothing here says remove
it - one surviving row out of eleven is what a family-wise 5% permits, and
`spending.md` reads it at -38.7% of risk with an interval that covers zero. But
**if a row of this table is going to decide a roster, it is not the row that
decided one.**

### `instruments.md` - the instrument ranking - **withdrawn, and the page half-withdrew it**

*Judged on: a cut, with no interval anywhere in it.*

The page already withdrew its headline - "Boom loses because of the spike" - on
finding that **36 of Boom's 48 closes are `thesis-only` at -0.595R, which is
exactly the figure the instrument row reports, because that strategy is the
sample**. That was the fourth Simpson reversal on this project.

What remains is the ranking itself: twelve instruments with at least eight
closes, ordered by mean R, and the reading that "only three instruments with a
real sample are positive". The re-run puts numbers on what that is worth: **55
rows, 13 testable, a 71.6% family-wise chance that at least one row misses, and
not one row surviving the correction.** The page's own closing caveat - "the
ranking below those is noise with names on it" - is exactly right and should be
the first line rather than the last.

## 3. The alignment gate, which is the one live recommendation that moves

`aligning.md` recommends: *"An alignment gate is justified at 3m and 5m and
nowhere else."* The page reports no interval on any cell. Computed from its own
counts:

| rung | aligned − opposed | SE | z | p |
| --- | ---: | ---: | ---: | ---: |
| 1m | -0.1 points | 0.81 | -0.12 | 0.90 |
| **3m** | **+2.5 points** | 1.40 | **+1.78** | **0.074** |
| **5m** | **+4.1 points** | 1.50 | **+2.73** | **0.0063** |
| 15m | -2.9 points | 1.91 | -1.52 | 0.13 |

**The 3m rung is not significant even uncorrected.** p = 0.074 on the page's own
numbers, before any correction for having run four rungs.

The 5m rung passes Bonferroni over the four rungs that have data (needs
|z| > 2.50) and fails over the twelve cells in the table (needs |z| > 2.87).
Which denominator is right is arguable; that the 3m rung is inside noise is not.

The page's defence is real and worth keeping: the stratification was **written
before the numbers were seen**, and `none` sitting between `aligned` and
`opposed` is the ordering a genuine agreement effect produces rather than an
activity effect. But that ordering is a three-way arrangement, and a specific
element lands in the middle by chance one time in three -
`calibrating.md` measures the closely related three-band monotone ordering at
15.40% against a coin's 16.67%. It is worth a factor of about three, not a proof.

**Verdict: the alignment gate is justified at 5m. The 3m half of the
recommendation is withdrawn.** Nothing about the Simpson correction that page
made is affected - the pooled reading is still an artefact, and that part of the
page is the best worked example of a stratified cut in the folder.

## 4. The verdict table

Forty-six pages read, and the load-bearing claim from each that a correction
could touch. `K` is how many comparisons were made before the number was
reported - rows in the cut, features scanned, thresholds swept.

### Withdrawn

| page | claim | n | K | why |
| --- | --- | ---: | ---: | --- |
| `spending.md` | `snap` at **-34.3% [-65.2%, -2.0%]** | 29 | 12 rows, 5 testable | falls to the studentised interval before any correction; 71.15% of book-rate null books produce a row like it |
| `instruments.md` | the twelve-instrument ranking by mean R | 8-32 a row | 55 rows, 13 testable | 71.6% family-wise; no row survives; the page's own closing caveat is the finding |
| `aligning.md` | the alignment gate **at 3m**, +2.5 points | 3,018 | 12 cells | z = +1.78, p = 0.074 on the page's own counts, before any correction |
| `exiting.md` | five of the seven surviving regime dimensions | 11,053 | **21 dimensions** | the control is three random buckets, which is a null for one comparison and not for the maximum of twenty-one |
| `winning.md` | `spread_over_risk` separates `P(stop)` | 397 | 43 features | clears the same control in **98.30% +-0.41** of null books - it is the cost, not a pattern |
| `edge.md` | `confluence-scalp` removed on **[-12.21, -0.04]** | 30 / 10 | 8 rows | both endpoints inside the gap between the percentile bootstrap and a construction that holds its rate; a t interval covers zero on both measures |
| `giveback.md` | `confluence-scalp` turned on at a **+1.401R** mean peak | 10 | 6 rows | the row that turned it on and the row that turned it off are both inside noise |

### Weakened - keep the mechanism, drop the interval

| page | claim | n | K | what survives |
| --- | --- | ---: | ---: | --- |
| `exiting.md` | ride's exit beats sweep-aware's own | 18,272 | 18 policies | the corrected **+0.046R**, not the **+0.655R** the setting was chosen on; and it lives in a tail |
| `giveback.md` | `confluence-scalp` gives back **1.758R** | 10 | 6 rows | `[-0.218, +3.734]` corrected. The change was made on "it had no exit policy at all", which stands |
| `turns.md` | trend exhaustion, **AUC 0.595 [0.540, 0.654]** | 222 turns | 10 signals, 7 configs | the headline configuration was pre-registered and the episode bootstrap is the right unit; but `vol` alone at 0.604 is the top of a ten-signal scan, and **two of fourteen instruments score below 0.5** |
| `strength.md` | the level's own record, **+32.8 points** | 2,864 | 8 signals | clustered by level, held out by level, and it **survived a pre-registered gap test** - strong for a scan top, and still "measured, not built" |
| `clustering.md` | `forecast_ratio`'s inverted U, **5.1 points** | 32,362 | 10-15 cells | the shape replicated on twice the data and shrank by a quarter; no permutation control, and the page says a block bootstrap "is still owed" |
| `swinging.md` | the fine band, **+0.576R a trade** | 71 | 8 cells, in-sample | the page calls it "an upper bound, not a forecast", and production reaches **1 origin in 2,230** |
| `tallying.md` | `eurusd/gbpusd` tallying, **+5.6%** | 14 days | 14 pairs | the page's own conditioning already retracts it - GBPUSD was standing in for "the dollar bloc is at a level" |
| `timeframes.md` | 1m is the best band, **+4.23 a trade** | 61 | 6 bands | contradicts the earlier measurement, and **62% of the record carries no interval at all** |
| `focusing.md` | the zone beats random placement | 205 | 5 stop widths | "205 trades cannot tell" - the page's own words after replacing one shuffle with 500 |
| `slopes.md` | reversion, and the break-gate lift **+0.030 AUC** | 2.99M bars / 5,452 | 15 cells / 8 | statistically enormous, economically nil by the page's own costing; the AUC lift shipped and "has to earn it again from its own stream" |
| `edge.md` | `sweep-aware` at **+0.154R [-0.022, +0.346]** | 77 | 8 rows | the top of an eight-row scan, and the page says so - "not enough to lever". A t interval reads [-0.032, +0.339], the same answer |
| `gamma.md` | expiry-day suppression, **0.768 to 0.921** | 25 yr x 4 | 20 cells | the second-Friday placebo at 1.00 is a real control and does real work; but the split sample loses `^DJI` entirely and **the pre-declared direction failed** - the effect weakened as option volume tripled |
| `stops.md` | gold's stops are early, **5 of 8** reached target | 8 | 39 instruments screened | `parked_stop_vol` was turned **off** on eight judgeable trades. The mechanism is independent and the action removes a setting rather than adding one, so the direction is safe |

### Survives

| page | claim | n | why it holds |
| --- | --- | ---: | --- |
| `generators.md` | stop slippage **+9.9R to +19.1R** on the spike side | 1,725-3,089 a feed | a factor of six hundred, a mechanism (96.7-100% of adverse moves are spikes), and two controls that behave as predicted |
| `features.md` | `side` alone matches all nine features, **+21.1pp** | 10,484 | the largest effect in the folder, re-measured on five times the data, with a design argument for why the other eight carry nothing |
| `prior.md` | `edge` is a re-encoding of `side`; the remainder is **AUC 0.520** | 11,053 | mechanism: `Memory.neighbours` filters on side and `base_rate_for` does not |
| `similarity.md` | the fast buckets are a tautology - **100.0%** agreement under 60s | 66,068 | definitional, with a shuffled control on the parent table, and it invalidates `learning.md`'s headline rather than being invalidated |
| `spiking.md` | Boom's spike waiting time has **cv 0.99** against a memoryless 1.00 | 1,150 spikes | pre-registered against the venue's published rate, and the rate reproduces it |
| `resolution.md` | **33.6%** of touches resolved in zero seconds | 26,538 | a defect, with a before-and-after (31.2% to 0.3%) and a predicted 60% fall in outcome volume |
| `horizon.md` | **14,140 of 52,238** resolutions have a negative duration | 52,238 | arithmetic, with a physical account (-660s is one 15m bar) and a fix |
| `starving.md` | the save path costs **0.394GB** and streaming costs **0.000GB** | 1 state file | byte-identical output, same SHA-256, and a msgpack header-width mechanism |
| `standardising.md` | four ratio fields exceed a hundred times their own p99 | 19k-131k a field | exhaustive rather than a scan, with near-zero denominators as the mechanism, and caps shipped |
| `generated.md` | the synthetics share no driver | 325 pairs | **the largest correlation in the study is on a stranger pair** - the control written before the numbers |
| `null.md` | signal-free entries reach the target **84%** against stopped trades' 82% | 684 controls | the matched null that killed `failing.md`'s headline, run through the same code path |
| `structure.md` | the transit graph carries nothing; the three that separated were `side` | 11,097 | Šidák over 33 tests, and the three survivors were **still** an artefact, caught by a median table |
| `cycles.md` | adding cycle state is worth **+0.0041 AUC [-0.0008, +0.0085]** | 73 cycles | resampled by instrument, Šidák over six cells, and the page counts cycles rather than touches |
| `states.md` | after two holds **74.9%**, after two failures **74.9%** | 5,048 / 561 | a pre-registered sharp test, and it names the trap - "runs are longer than chance" is heterogeneity, not state |
| `localising.md` | the origin is **2.8x** more stable than a matched random book | 1.41M bars | density-matched nulls on every comparison, and the null killed an earlier version at 99.9% |
| `detecting.md` | EDDM alarms every 270-940 observations on an unchanged model | 3,000 x 5 seeds | the null stream *is* the design |
| `twins.md` | the five twin pairs share no path - **0 of 5** | 916,248 comparisons | the bar was set **in code before the numbers**: a twin counts only if it exceeds every control at every one of 1,201 lags, in both halves. The largest number in the study is on an unrelated pair |
| `compounding.md` | the book's mean is **-0.1354R [-0.2082, -0.0595]** | 398 | K=1 - the pooled figure, not a cut - with day-clustering established by permutation (p=0.001) and the sizing rule derived from it |
| `cascading.md` | the multifractal discriminator does not work | 5 control arms | the arms were run **before any instrument was read**, and a process with zero intermittency by construction scored 0.157 |
| `convexity.md` | the book's tail is the position sizer, not the trades | 325 | counts its own comparison budget (**"about 250"**), scores concentration against a thin-tailed null, and splits 60/40 by time |
| `lagging.md` | the broker's lateness is unremarkable across six venues | 5,923 events | the rotated-venue control was added **after** a positive result, and the page names that sequence as the correct one |
| `implied.md` | `vix_fit` beats the incumbent on **8 of 8** series | 20 yr x 8 | walk-forward with every coefficient fitted before the bar it predicts, and it ships **off** behind a flag |
| `overhead.md` | the pooled -1.9% at p=0.002 is a mixing artefact | 24,320 | the page stratified by interval, found the sign unstable, and withdrew the one thing it was going to act on |

### Nulls, re-read for power rather than corrected

`calibrating.md` measured this desk's power to be poor, so several nulls need
re-reading. Correcting a null makes it more null and tells you nothing; what
bears on it is whether the study could have found the effect had it been there.

| page | null | the honest reading |
| --- | --- | --- |
| `winning.md` | nothing in 43 entry features separates winners from losers | the control is sound (**4.80% +-0.68**), and an injected +20%-of-risk edge is found **12.00% +-2.06** of the time. **This book cannot answer the question.** |
| `cycles.md` | cycle state adds nothing | binding n is **73 cycles**, and the page says so. Not answerable here either |
| `shelves.md` | volume nodes do not hold price | 849 windows, about a quarter independent - the page computes the effective sample itself |
| `rounding.md` | drawn levels do not beat round numbers | **the positive control failed**, so the page correctly declares its own null uninformative |
| `positioning.md` | nothing in COT leads price weekly | 84 weeks against a +-0.22 noise band; a real weekly effect below 0.3 could not be seen |
| `catalysing.md` | news does not explain the losses | the matched design found **not a single cell** with both arms. The experiment did not run |
| `peering.md` | peer counts do not predict | the shuffled null is sometimes **larger than the effect**, and the synthetics show a bigger effect than the real assets. A control failure, reported as one |

## 5. What the audit found about the folder as a whole

**The controls are already here, and they work.** `generated.md`'s stranger
pairs, `null.md`'s signal-free entries, `structure.md`'s Šidák, `cycles.md`'s
cycle-counting, `peering.md`'s synthetic arm, `catalysing.md`'s placebo,
`localising.md`'s density-matched null, `rounding.md`'s positive control,
`bjorgum.md`'s synthetic control, `states.md`'s trivial-rule baseline. In every
case where a control was run, it did its job - several times by killing the
page's own headline.

**No claim is withdrawn here because its control failed to catch something.**
The one entry in the withdrawn table that had a permutation control -
`winning.md`'s `spread_over_risk` - is there because the quantity it measured
is mechanical rather than informative, which is a reading error and not a
control failure. Everything else withdrawn ran no control at all.

**What moves is the cut table with no interval on it.** `aligning.md`,
`instruments.md`, `timeframes.md`, `choosing.md`, `signs.md`, `geometry.md` and
`spending.md`'s strategy table all report bucket tables with point estimates and
no interval anywhere, and they are where the withdrawals are. A table of means
with no interval is not a weaker version of a table with one; it is a different
kind of object, and the eye supplies a precision it does not have.

**The self-correction rate is high and the pages get there first.**
`instruments.md` withdrew its own headline on finding a composition.
`exiting.md` found two look-aheads and restated a tenfold error against itself.
`failing.md`'s 82% recovery was killed by `null.md`. `forecasting.md` carries a
standing retraction header. `focusing.md` replaced one shuffle with five
permutation tests and downgraded its own result. `strength.md` re-ran on a
denominator fix and let an effect invert. That is the behaviour the correction
is meant to produce, and it was already happening.

**The best discipline in the folder is already better than what this audit
recommends.** `twins.md` sets its bar in code before the numbers - a twin
counts only if its statistic exceeds every control's at every one of 1,201 lags
**and** in both halves of a split - and then reports 916,248 comparisons
against it. `cascading.md` ran five synthetic control arms with known ground
truth before reading a single instrument, and they caught the estimator being
biased rather than noisy. `convexity.md` counts its own comparison budget out
loud. Those three are the template; nothing in this audit improves on them.

**The one systematic gap is the maximum-of-K null.** Where this folder uses a
control it is almost always a null for *one* comparison - a shuffled label, a
matched random draw, a synthetic arm. `winning.md` is the only page that takes
the maximum over the whole scan and compares *that* to its permuted
distribution. `exiting.md`'s twenty-one dimensions against a three-bucket
control is the clearest case of the gap, and `localising.md`'s ten estimator
variants and `turns.md`'s ten signals are the same shape at smaller K.

## 6. What to do

1. **Put an interval on every bucket table, or state the width the sample can
   carry.** `calibrating.md`'s rule is one line: a 95% interval on `n` closes is
   about **330 / sqrt(n)** points of risk wide. A table that cannot carry the
   claim being read off it should say so in the header.
2. **When a scan has a maximum, the null is the maximum.** `winning.py`'s
   `control` is forty lines and is the only correct form of this in the folder.
   It should be what a multi-dimension survivor list is scored against, starting
   with `sweepregimes.py`.
3. **Three live consequences.** Narrow the alignment gate to **5m**. Stop
   citing `+0.655R` for sweep-aware's exit - the number is `+0.046R`. And treat
   `confluence-scalp` as **unmeasured** rather than as measured-negative: the
   row that removed it covers zero on a t interval, as does the row that turned
   it on three days earlier.
4. **Nothing else needs reverting.** Every other live setting this audit
   touched is either backed by a mechanism that does not depend on the interval
   (`stop_overshoot`, gold's `parked_stop_vol`, the `confluence-scalp` *exit*
   as distinct from the roster decision), or is a setting that was correctly
   left off.
5. **One thing to add, and it is cheap.** `spending.py::interval` is the
   function every one of these tables goes through. Replacing its percentile
   endpoints with the studentised ones is about thirty lines, and it is the
   single change that would have prevented `snap`, the 2:1 band and
   `confluence-scalp` from ever reading as findings.

## What this audit does not say

**It does not re-measure anything that needs a replay.** `exiting.md`'s exit
policies, `sweepregimes`' dimensions, `generators.md`'s tick-level slippage and
every bar-replay result in the folder are judged on their published numbers with
the arithmetic of the correction applied. Only the cuts the closes export can
reproduce were actually re-run.

**It does not audit the two pages being written as it ran** - `rebuilding.md`
and `quantising.md` are in flight and belong to their authors.

**And a verdict of "survives" is not a verdict of "true".** It means the claim
is not what this desk's methods produce on noise. Several of the survivors are
defects rather than edges, which is the easiest kind of claim to be right about.
