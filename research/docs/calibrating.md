# How often this desk finds something that is not there

Six results turned out in one day to be properties of a selection rather than
of the market. [spending.md](spending.md) has a book-wide figure that flips sign
depending on which closes carry a `risk_money` field.
[winning.md](winning.md) ran 43 entry features against a 300-permutation
control and nothing cleared the noise floor. [aligning.md](aligning.md) records
a Simpson reversal where the pooled figure says the opposite of every stratum.
The desk's answer each time was to write the lesson down; the lesson each time
failed to survive the next question.

This page does something different. It measures **how often the desk's own
analysis reports an edge on data where the true answer is known to be zero**,
at the sample sizes the desk actually has.

That is possible because [deriving.md](deriving.md) proves a predictable
position on a martingale has expectancy `-(c/2) x turnover` for every stop,
target, trail, entry filter and sizing rule, and [rebuilding.md](rebuilding.md)
re-instantiates the Deriv generators from published parameters. A simulated
path from a validated generator is therefore a world where **every strategy's
true edge is exactly minus its costs and nothing else**, so any "edge" an
analysis finds there is a false positive by construction.

Three harnesses:

* `research/harness/calibnull.py` builds the world.
* `research/harness/calibfpr.py` runs `spending.py`'s methods on it.
* `research/harness/calibscan.py` runs `winning.py`'s feature scan on it.

Run on the lab, 64 cores:

```
./.secrets/lab.sh run research/harness/calibnull.py CLOSES=1000000
./.secrets/lab.sh run research/harness/calibfpr.py BOOKS=2000
./.secrets/lab.sh run research/harness/calibscan.py BOOKS=1000 CLOSES=420000
```

`calibfpr.py` was run twice, at seed 606 and seed 909; where a number moves
between them both are given.

## The answer, before the working

**One `spending.py` run on a book with no edge in it produces at least one
interval that excludes zero 63.05% +-1.08 of the time.** Not 5%.

And in the world the desk is actually in - where the whole book loses at its
own average rate and no strategy is separately worse than any other - **one run
produces at least one row reading `<= -34.3%` of risk with an interval
excluding zero in 95.05% +-0.49 of books.**

That is the `snap` row. It is what a twelve-row cut of a uniformly losing book
does, not what `snap` does.

The bootstrap is not the culprit. At n=133 its 95% interval excludes the truth
4.70% +-0.47 of the time, which is nominal. At n=29 it excludes it 7.05%
+-0.57, which is 40% more often than it should - real, and small next to the
multiplicity. **The table is the problem, not the interval.**

## The world, and why it is a null

`calibnull.py`, 1,000,020 closes replayed through `shared.replay.walk` on
twelve martingale instrument families, charging 2.7% of risk per round trip -
the live stop row's own slippage, measured in `spending.md`, rather than a
guess. A zero-cost null is an easier world and is not used.

| | null world | live book |
| --- | ---: | ---: |
| mean R | **-0.02754** (theorem: -0.02700, SE 0.00083, z = -0.65) | |
| return on risk | **-2.79%** (theorem: -2.70%, z = -1.03) | -22.2% |
| per-close sd | 0.828 | 0.805 |
| skew | +0.58 | +0.72 |
| excess kurtosis | +0.51 | +0.53 |
| stop share | 31.8% | 31.6% |
| stop row, mean R | -0.806 | -1.028 |

Five conditions were written into `calibnull.py` before the numbers were read.
**One fired**: the stop row reads -0.806 against the live -1.028. The cause is
in the output rather than argued away - seven of the twelve shipping shapes
carry a trail or a break-even move, and an exit at a moved stop still wears the
label `stop`. On the five shapes that carry neither, the stop row is
**-1.0146**, which is a stop that is a stop. The other four conditions held.

The martingale property is not assumed. Two of those conditions are the
theorem's own prediction, checked to within two thirds of a standard error.

## The instrument, calibrated before anything is measured with it

A false-positive rate is itself an estimate, and an instrument that cannot
recover a rate that is known exactly cannot measure one that is not.

| check | result | nominal |
| --- | ---: | ---: |
| t-test on Gaussian data, n=133, 40,000 trials | **4.86% +-0.11** | 5.00% |
| percentile bootstrap on a Gaussian mean, n=133, 4,000 trials | 5.53% +-0.36 | 5.00% |
| the `t_crit` expansion against the published t quantiles | worst gap 0.00014 | |

### And one thing the calibration found on the way

The vectorised bootstrap was pre-registered to agree with `spending.interval`
to within 0.004 of risk. **It fired on the first run, because
`spending.interval` does not agree with itself to 0.004.** On the live 133
closes, five seeds move its endpoints:

| seed | interval |
| --- | --- |
| 1 | [-36.739%, -7.455%] |
| 2 | [-36.828%, -7.009%] |
| 3 | [-36.902%, -7.288%] |
| 17 | [-36.670%, -7.259%] |
| 99 | [-36.669%, -7.444%] |

**The published `[-36.7%, -7.5%]` carries about 0.23 points of pure resampling
noise on its lower endpoint and 0.45 on its upper**, at 20,000 draws, and at
n=29 the lower endpoint moves 0.72 points between seeds. Over 21 books
`spending.interval` differs from itself by up to 0.371 points (median 0.159)
and the vectorised version differs from it by up to 0.509 (median 0.209) -
which is the same order, and is what the restated condition requires. The
original constant and the reason it was replaced are both in the harness
docstring rather than edited out.

None of this changes a conclusion. It does mean the third decimal place of any
interval on this desk is decoration.

## 1. The bootstrap, on its own, is close to honest

Coverage of the 95% percentile bootstrap interval on return-on-risk, 2,000
disjoint null books per row. The true value is -2.70% everywhere in this world.

| n | books | excludes the truth | below | above | median width |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 8 | 2000 | **10.55% +-0.69** | 5.55% | 5.00% | 98.8% |
| 16 | 2000 | 7.65% +-0.59 | 4.90% | 2.75% | 76.6% |
| 17 | 2000 | 7.80% +-0.60 | 5.15% | 2.65% | 74.5% |
| 23 | 2000 | 8.50% +-0.62 | 5.60% | 2.90% | 65.6% |
| 28 | 2000 | 6.90% +-0.57 | 4.25% | 2.65% | 60.1% |
| **29** | 2000 | **7.05% +-0.57** | 4.60% | 2.45% | 59.2% |
| 50 | 2000 | 6.20% +-0.54 | 3.85% | 2.35% | 46.0% |
| 100 | 2000 | 5.25% +-0.50 | 2.85% | 2.40% | 33.1% |
| **133** | 2000 | **4.70% +-0.47** | 2.75% | 1.95% | 28.8% |
| 300 | 2000 | 4.70% +-0.47 | 2.60% | 2.10% | 19.3% |
| 685 | 1459 | 5.07% +-0.57 | 3.02% | 2.06% | 12.8% |
| 1000 | 1000 | 4.40% +-0.65 | 2.60% | 1.80% | 10.7% |

Two things to read off it.

**At the book's own size the interval is right.** 4.70% +-0.47 against 5.00% at
n=133. That was pre-registered as a condition and it fired, which by its own
terms means the twelve-row result below is a multiplicity result and must be
reported as one rather than as a complaint about the bootstrap.

**At a strategy row's size it is not.** 7.05% at n=29 and 10.55% at n=8 - the
interval is too short, by enough to raise the error rate by half at the sizes
half this book's tables are cut at. The miss is two-sided but lopsided: 4.60%
below against 2.45% above, because the statistic's sampling distribution is
left-skewed at small n and the percentile method inherits the skew rather than
correcting for it.

**And the width is the practical number.** A 29-close row carries a 95%
interval **59 points of risk wide**. Nothing smaller than that is measurable in
one, whatever the point estimate says.

## 2. The cost of cutting, which is the whole finding

Same books, cut the way `spending.py` cuts them. A row shorter than 8 closes
prints "too few to say" and cannot fire, so a twelve-row table is really a
five-interval table - and that is part of the answer, not a caveat.

| cut | rows | rows with an interval | >=1 excludes the truth | >=1 excludes zero |
| --- | ---: | ---: | ---: | ---: |
| strategy | 12 | 5 | **32.10% +-1.04** | **33.10% +-1.05** |
| exit kind | 5 | 5 | 31.00% +-1.03 | 33.15% +-1.05 |
| reward-to-risk bands | 3 | 3 | 17.95% +-0.86 | 19.65% +-0.89 |
| interval | 7 | 4 | 24.50% +-0.96 | 26.85% +-0.99 |
| hour | 24 | 4 | 29.85% +-1.02 | 32.40% +-1.05 |
| feed | 26 | 5 | 38.60% +-1.09 | 40.35% +-1.10 |
| **one `spending.py` run** (all three tables) | 20 | 13 | **59.55% +-1.10** | **63.05% +-1.08** |

The twelve-row table row by row, largest first, shows where it comes from:

| rows so far | added | n | that row alone | >=1 so far |
| ---: | --- | ---: | ---: | ---: |
| 1 | snap | 29 | 6.05% +-0.53 | 6.05% |
| 2 | thesis-only | 28 | 6.30% +-0.54 | 12.10% |
| 3 | sweep-aware | 23 | 7.50% +-0.59 | 18.45% |
| 4 | runner | 17 | 9.55% +-0.66 | 26.35% |
| 5 | fade-to-value | 16 | 7.90% +-0.60 | **32.10%** |
| 6-12 | the seven rows under n=8 | | cannot fire | 32.10% |

**Five rows take a 5% test to 32%.** The seven short rows add nothing because
they never get an interval - which is the one piece of good news in the table,
and it is an accident of `interval()`'s floor rather than a decision.

### The null the desk actually needs

The world above has a true rate of -2.7%, and the real book runs at -22.2%. So
the question `spending.md` is really asking is not "does `snap` lose" - the
whole book loses - but "is `snap` separately worse". The right null for that is
a world where **every row truly runs at the book's own -22.2%**, which is the
same world shifted. Every row named in it is named wrongly.

| cut | >=1 excludes the truth | >=1 excludes zero | **>=1 reads `<= -34.3%` and excludes zero** |
| --- | ---: | ---: | ---: |
| strategy (12 rows) | 31.80% +-1.04 | 80.75% +-0.88 | **71.15% +-1.01** |
| exit kind (5 rows) | 31.90% +-1.04 | 87.00% +-0.75 | 66.70% +-1.05 |
| reward-to-risk bands (3) | 17.00% +-0.84 | 81.95% +-0.86 | 42.80% +-1.11 |
| interval (7 rows) | 24.50% +-0.96 | 82.00% +-0.86 | 57.15% +-1.11 |
| hour (24 rows) | 30.00% +-1.02 | 65.50% +-1.06 | 62.40% +-1.08 |
| feed (26 rows) | 38.95% +-1.09 | 75.20% +-0.97 | 69.30% +-1.03 |
| **one `spending.py` run** | 59.95% +-1.10 | **99.70% +-0.12** | **95.05% +-0.49** |

A single 29-close row in that world excludes zero 33.15% +-1.05 of the time on
its own, and reads `<= -34.3%` as well in **22.25% +-0.93**.

## 3. How large a false effect gets

The same 2,000 books, in the units `spending.md` reports.

| row | n | 95% of null books land in | when the row excludes the truth |
| --- | ---: | --- | --- |
| snap | 29 | [-32.7%, +29.5%] | [-44.8%, +49.3%] |
| thesis-only | 28 | [-34.2%, +29.8%] | [-46.6%, +44.3%] |
| sweep-aware | 23 | [-36.9%, +34.4%] | [-54.2%, +49.2%] |
| runner | 17 | [-42.5%, +42.6%] | [-54.0%, +62.3%] |
| fade-to-value | 16 | [-42.1%, +40.1%] | [-60.5%, +58.3%] |

The **worst** of the five rows that get an interval has a median of **-23.2%**
of risk, a 5th percentile of -44.4% and a 1st of -54.5%. The best has a median
of +18.4% and a 95th of +43.3%. **The typical null book hands you a worst
strategy at -23% of risk and a best one at +18%, and one book in twenty makes
the spread -44% to +43%. None of it exists.**

A 29-close row reads `<= -34.3%` *and* excludes zero in 2.00% +-0.31 of null
books on its own; at least one of the twelve rows does in **16.50% +-0.83**,
even in the easy world where the truth is only -2.7%.

## 4. Do the published shapes reproduce

### The three-band ordering

`spending.md` reads its far-target result as strengthened because it is
monotone across three bands in two tables. 2,000 null books of 133 closes,
banded on each close's own `reward_to_risk` at 1.0 and 2.0 exactly as
`spending.py::banded` does it:

| shape | in a null book | by chance alone |
| --- | ---: | ---: |
| monotone across the three bands, either direction | 36.25% +-1.07 | 33.33% |
| monotone **and falling**, as published | 15.40% +-0.81 | 16.67% |
| monotone and an end band's interval excludes the truth | 5.45% +-0.51 | |
| the exit-kind table monotone in what it kept | 42.25% +-1.10 | |
| **both tables monotone at once** | **15.25% +-0.80** | 15.32% if independent |

Three things follow. The monotone-and-falling shape happens in a null world
about **one book in six and a half** - 15.40% against the 16.67% a fair
three-way ordering gives, so the shape is not even slightly harder to get by
chance than by arithmetic. The two tables are **statistically independent** -
their joint rate, 15.25%, is within a tenth of a point of the product of their
separate rates - so requiring both to be monotone moves the null rate from
36.25% to 15.25%, a factor of 2.4. That factor is the entire value of the
corroboration. And the exit-kind table on its own comes out monotone 42.25% of
the time, two and a half times the 16.7% a fair ordering would give, because
ordering exits by the distance they aimed at and scoring them on the share of
it they kept is close to arithmetic.

### `strata.compare`

`shared/strata.py` exists because a pooled figure has reversed on this project
four times. On 400 null books of 133 closes, where every reversal it can find
is false:

| bucket | `min_n` | a reversal is flagged | every stratum thin |
| --- | ---: | ---: | ---: |
| reward-to-risk band | 100 (the default) | **0.00%** | 100.0% |
| band | 25 | 99.00% +-0.50 | 0.0% |
| band | 10 | **100.00%** | 0.0% |
| feed | 100 (the default) | **0.00%** | 100.0% |
| feed | 25 | 100.00% | 0.0% |
| feed | 10 | 100.00% | 0.0% |

**At 133 closes the tool has two settings: silent, and always.** At its default
`min_n=100` every stratum of a 133-close book is thin, so nothing is ever
counted and no reversal can ever be flagged. Lower the floor enough to make it
speak and it flags a reversal in essentially every book, because an ordinal
comparison between buckets of five closes is a coin toss and a table of them
always contains one that disagrees.

This is not an argument against the check - the reversals it was built from
were real, and the module's case for being mechanical stands. It is an argument
that **a reversal warning on a book of this size carries no information either
way**, and that a cut of 133 closes should not be sent through it and reported
as having passed or failed.

## 5. The feature scan, and what its control is worth

`calibscan.py` runs `winning.py`'s `scan` and `control` unchanged on 1,000
disjoint null books of 397 closes, each carrying 47 entry features computed
from the simulated bars, of which 45 have enough spread to tercile. They are
the same kinds of quantity the live decision carries - trend, stretch,
efficiency, position in a range, wick shape, clock, and the order's own
geometry - at a comparable count, because the statistic that matters is the
largest gap over the whole set and that depends on how many there are and how
correlated they are. The pool is 420,024 closes with a mean R of -0.02530
+-0.00128 against the theorem's -0.02700, z = +1.33.

**The instrument first.** 43 independent Gaussian features against an
independent Gaussian target, 600 trials: the scan clears its own permutation
control **5.00% +-0.89** of the time. That is what a permutation test must
produce, and it lands on it exactly - which by this project's own rule is a bug
to hunt rather than a success. Hunted: 600 trials fire 30 times, and 30/600 is
exactly 0.0500. The granularity of the estimate is 0.167 points and the chance
of landing on that cell is about one in eleven. A coincidence, and the ledger
records that the check fired.

**On null books**, target R - the only one of `winning.md`'s three targets the
theorem covers:

| | rate |
| --- | ---: |
| the biggest gap clears the permutation control | **4.80% +-0.68** |
| ... and holds its sign into the verify half (the full gate) | 2.30% +-0.47 |
| at least one feature separates its terciles at an uncorrected p<0.05 | **98.50% +-0.38** |
| the biggest feature does | 97.00% +-0.54 |
| the biggest gap reaches `winning.md`'s live 0.433 | 12.90% +-1.06 |

**`winning.md`'s permutation control is the only thing standing between that
page and a false positive, and it works.** Without it, 98.5% of null books
contain a feature that looks significant at p<0.05 and a null book carries 5.5
of them out of 45. With it, the rate is 4.80% +-0.68 - nominal - and the
four-part gate takes it to 2.30%.

That is the one method on this desk that calibrates. It is also the only one
built with its own null in the harness rather than added afterwards.

The live book's largest gap on R was 0.433 and did not clear its control. A
null book's biggest gap reaches 0.433 in 12.9% of cases. **`winning.md`'s null
is reproduced: nothing in the feature set separates winners from losers, and
the number that page reported is an ordinary draw from a world with nothing in
it.**

### The one feature that did clear, and why it is arithmetic

`winning.md`'s single survivor is `spread_over_risk` on the target `P(stop)`.
The theorem does **not** cover `P(stop)`: in a world with no edge whatever, a
trade whose stop sits closer in volatility units is genuinely more likely to be
stopped, and one whose target sits further away is genuinely less likely to
reach it. So the null world should reproduce that result, and it does:

| target | biggest gap clears the control |
| --- | ---: |
| R - covered by the theorem | 4.80% +-0.68 |
| **P(stop)** - not covered | **98.30% +-0.41** |
| P(R>0) - not covered | 12.40% +-1.04 |

And when the cost is charged as a **price** rather than as a share of risk - so
that `spread_over_risk` varies between trades the way it does live - the
mechanical effect reaches R itself:

| priced arm, 300 books | clears the control | names `spread_over_risk` |
| --- | ---: | ---: |
| target R | 34.00% +-2.73 | 13.67% +-1.98 |
| target P(stop) | **99.67% +-0.33** | 50.33% +-2.89 |

**`spread_over_risk` predicting stops is not a discovery about this book.** It
is what a spread does, and a world with no edge in it produces the same result
98 to 100 times in a hundred. That does not make the gate wrong - charging less
spread is still worth doing, and [exiting.md](exiting.md) derived it from a
cost decomposition rather than from this scan - but it should stop being cited
as the feature that survived a scan. It survived because it is the cost, and
the cost is not information.

One pre-registered condition fired here and is not explained away. The priced
pool's mean R is -0.14449 +-0.00226 against the theorem's -0.15140 - minus the
mean of `spread_over_risk` itself - which is **z = +3.06**, so that arm is
0.69 points of risk better than an exact null, or 4.6% of the 15.1 points it
charges. A smaller independent pool at another seed reads +0.33 points
(z = +0.61), so the miss sits at the edge of what the check can resolve, and it
is not concentrated in any one instrument family. It is reported rather than
resolved because it cannot touch what the priced arm is used for: a bias of
half a point of risk does not move a rate of 99.67%.

### Power, on the scan side

An edge injected into half the book, chosen by a feature the scan already sees:

| edge | scan clears its control | names the right feature |
| ---: | ---: | ---: |
| +5% of risk | 6.00% +-1.50 | 0.40% +-0.40 |
| +10% | 7.20% +-1.63 | 0.40% +-0.40 |
| +20% | 12.00% +-2.06 | 2.40% +-0.97 |
| +40% | **41.20% +-3.11** | 25.60% +-2.76 |

**At 397 closes the scan cannot see a 20%-of-risk effect.** It finds a
40%-of-risk one two times in five and names the right feature one time in four.
A method with a nominal false-positive rate and no power is not a conservative
method; it returns "nothing here" almost whatever is true, and `winning.md`'s
null should be read as "this book cannot answer the question" rather than as
"the answer is no".

## 6. Power on the bootstrap side, and what `spending.md` got wrong

A strategy whose true return on risk is `+delta` after costs; the test is the
one the desk runs - a 95% bootstrap interval that excludes zero.

| delta | 100 | 250 | 500 | 1000 | 2000 | 4000 | 8000 | n for 80% |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| +2% | 4.4% | 8.2% | 6.6% | 8.2% | 15.2% | 28.8% | 51.0% | beyond 8,000 |
| +5% | 9.4% | 18.2% | 25.2% | **39.4%** | 74.2% | 96.6% | 100% | **2,393** |
| +10% | 21.4% | 45.2% | 72.8% | 95.6% | 100% | 100% | 100% | **622** |

(Seed 606. The whole file was re-run at seed 909: +5% needs 2,569 and +10% 626,
and at 1,000 closes a genuine +5% is found 46.8% rather than 39.4% of the time -
500 trials a cell, so a cell carries about 2 points of standard error.)

`spending.md` closes with "separating a genuine +5% of risk from zero at 95%
needs about 1,000 closes and +10% needs about 250". **Those are the 50% power
points, not the 80% ones.** They come from `n = (1.96 x sd / delta)^2`, which
is the size at which the estimate sits 1.96 standard errors from zero *on
average* - a coin flip. At 1,000 closes a genuine +5% is found 39-47% of the
time. The 80% figures are **2,400-2,600** and **620-630**, and under a
Bonferroni correction over five rows **3,400-3,800** and **860-900**.

This was pre-registered: if power at the quoted sizes had been near 80%, this
section would have had no content. It fired on both seeds.

## 7. Is it the bootstrap, or is it the sample size

Four interval constructions on the same books and the same resamples -
percentile (what ships), BCa, studentised, and a t interval on the linearised
ratio.

| n | method | excludes the truth | excludes zero | mean width |
| ---: | --- | ---: | ---: | ---: |
| 16 | percentile | 7.70% +-0.60 | 8.05% | 78.6% |
| 16 | BCa | 7.45% +-0.59 | 7.95% | 79.8% |
| 16 | **studentised** | **4.40% +-0.46** | 4.55% | 94.8% |
| 16 | t on the ratio | 5.15% +-0.49 | 5.90% | 88.7% |
| 29 | percentile | 6.95% +-0.57 | 7.90% | 60.2% |
| 29 | BCa | 6.80% +-0.56 | 7.70% | 60.7% |
| 29 | **studentised** | **4.75% +-0.48** | 5.50% | 66.3% |
| 29 | t on the ratio | 5.95% +-0.53 | 6.60% | 64.2% |
| 50 | percentile | 6.20% +-0.54 | 7.30% | 46.5% |
| 50 | studentised | 5.00% +-0.49 | 5.95% | 49.1% |
| 133 | percentile | 5.00% +-0.49 | 7.15% | 29.1% |
| 133 | BCa | 4.60% +-0.47 | 6.85% | 29.1% |
| 133 | studentised | 4.40% +-0.46 | 6.45% | 29.7% |
| 133 | t on the ratio | 4.60% +-0.47 | 7.40% | 29.5% |

**The studentised bootstrap holds its nominal rate where the percentile one
does not**, and costs 10% of width at n=29 and 2% at n=133. BCa - the usual
recommendation - buys almost nothing here: 6.80% against 6.95% at n=29. The
plain t interval on the linearised ratio is most of the way there for no
resampling at all, which is worth knowing for any cut too small to bootstrap.

At n=133 every construction is within a standard error of nominal - which seed
comes out "closest" there changes between runs, and that is the point. **The
bootstrap is a small problem at strategy-row sizes and no problem at book
sizes.**

## 8. What to do about it

### How many closes before a cut means anything

The width of a 95% interval on return-on-risk over `n` closes is
**about 330 / sqrt(n) points of risk**. Measured: 59 points at n=29, 29 at
n=133, 19 at n=300, 11 at n=1,000 - the rule is a little wide below n=50, which
is the under-coverage of section 1 seen from the other side. That one line
settles most arguments before any test is run: **a claim smaller than the
interval's own width is not a claim.**

| you want to claim | closes needed |
| --- | ---: |
| a strategy is 20 points of risk worse than the book | **~270 in that strategy** |
| a strategy is 10 points worse | ~1,100 |
| a genuine +10% of risk, one test, 80% power | 620-630 |
| a genuine +10% of risk, one row of a five-row table | 860-900 |
| a genuine +5% of risk, one test, 80% power | 2,400-2,600 |
| a genuine +5% of risk, one row of a five-row table | 3,400-3,800 |
| a genuine +2% of risk | beyond 8,000 |
| an entry feature worth +20% of risk, by the tercile scan | far beyond 397 |

Ranges are the spread between seed 606 and seed 909. At n=29 - where half this
book's tables are cut - the interval is 59 points wide, so **no strategy-level
claim smaller than 59 points means anything at all**, and the largest claim on
`spending.md`'s strategy table is 34.

### The correction for a twelve-row table

Bonferroni over the number of rows that **actually get an interval**, not over
the number of rows printed. That is 5 here, not 12.

Family-wise rate over the twelve-row strategy table - how often at least one
row's interval excludes the truth - at the shipping 20,000 resamples, 2,000
books, seed 909, both interval constructions:

| correction | percentile | studentised |
| --- | ---: | ---: |
| none (what ships) | 32.10% +-1.04 | 19.60% +-0.89 |
| **Bonferroni over the 5 rows that get an interval** | 10.15% +-0.68 | **2.65% +-0.36** |
| Bonferroni over all 12 rows | 5.60% +-0.51 | 1.15% +-0.24 |
| Sidak over 5 | 10.25% +-0.68 | 2.60% +-0.36 |

Read across the top row first: **changing nothing but the interval takes the
family-wise rate from 32% to 20%.** The percentile method is a third of the
problem on its own.

**Bonferroni over 5 applied to the percentile bootstrap does not restore 5%** -
it gets to 10.15%, and that was pre-registered as a condition that would forbid
recommending it. It fired. The reason is in section 7: at a corrected alpha the
test asks for the 0.5% quantile of the bootstrap distribution, and the
percentile method's far tail is worse behaved than its 2.5% tail, so a
correction applied to it under-corrects. Correcting over all twelve rows lands
on 5.60% by accident - the extra factor of 2.4 happens to absorb the
miscalibration, which is not a reason to do it.

**Bonferroni over 5 applied to the studentised bootstrap does restore it, and
then some**: 2.65% +-0.36, conservative by a factor of about two. That costs
power, and the table in section 6 says what it costs - the +5% detection point
moves from about 2,500 closes to about 3,500.

### So: three rules

1. **Print the interval only where the row can carry one, and say how many
   that is.** A twelve-row table with five intervals is a five-comparison
   table, and the correction should be over five.
2. **Correct the interval as well as the alpha.** A studentised bootstrap at a
   Bonferroni alpha over the rows that get an interval: 2.65% +-0.36
   family-wise against the 32.10% the page currently runs at. Conservative, and
   the conservatism is priced in section 6.
3. **Pre-register the cut or treat it as a scan.** Six cuts of the same book
   are six chances; `spending.md` already says this and then reports the
   surviving row anyway. A cut chosen after the numbers were seen should be
   quoted with the family-wise rate beside it, or not quoted.

## 9. The published findings, re-examined against this calibration

### Survives: the book-wide -22.2%

`spending.md`: **-22.2% of risk, 95% [-36.7%, -7.5%], n=133**.

* It was not a cut. It is the figure the page is about, and the coverage table
  says the interval at n=133 is honest: 4.70% +-0.47 against 5.00%.
* **0.35% of null books of 133 closes read `<= -22.2%`**, and 95% of them land
  in [-16.7%, +11.6%]. The live figure is outside that range.
* Its interval excludes zero in 7.60% +-0.59 of null books, of which 6.55% on
  the low side - so the excursion is large where the significance alone would
  be ordinary.

It survives. The number itself carries about half a point of Monte Carlo noise
on each endpoint, so quote it as **-22% [-37%, -7%]**.

### Does not survive: `snap` at -34.3% [-65.2%, -2.0%], n=29

* In the world where every strategy truly runs at the book's own -22.2%, **at
  least one of the twelve rows reads `<= -34.3%` and excludes zero in 71.15%
  +-1.01 of books**, and a single 29-close row does it in 22.25% +-0.93.
* Even in the easy world where the truth is only -2.7%, at least one of the
  twelve rows does it in 16.50% +-0.83.
* The row's own interval is 59 points of risk wide at n=29 and the percentile
  bootstrap is anti-conservative there (7.05% against 5.00%).
* And `snap`'s interval reaches zero by a margin of about two points, on an
  endpoint that moves **0.42 points between bootstrap seeds** alone: seven
  seeds of `spending.interval` on those 29 closes give upper endpoints from
  -1.64% to -2.06%. It clears zero by four times its own resampling noise,
  which is a margin rather than a comfortable one.

**The `snap` row is what a twelve-row cut of a uniformly losing book produces.
It is not evidence that `snap` is worse than the rest of the book.** The
recommendation to turn it off should rest on its mechanism - a 1:1 payoff over
114 seconds paying two crossings of the spread, which is arithmetic and does
not need this table - and not on the interval.

### Weakened: the far-target band ordering

`spending.md`'s 2:1-and-above band at **-53.3% [-84.6%, -19.0%], n=30**, read
as strengthened by monotonicity across two tables.

* The three-band cut produces at least one interval excluding zero in 19.65%
  +-0.89 of null books, and in **81.95% +-0.86** of books drawn from the
  book-rate world.
* The monotone falling shape arises by chance in 15.40% +-0.81 of null books,
  against 16.67% for a coin.
* The two tables are statistically independent, so requiring both to be
  monotone moves the null rate from 36.25% to 15.25% - a factor of 2.4, which
  is the whole value of the corroboration.
* At n=30 the interval is ~58 points wide, the bootstrap is anti-conservative
  there, and the endpoints move 0.6 to 0.9 points between seeds.

What is left is a **-53.3%** point estimate on 30 closes. In the world where
every row truly runs at the book's own -22.2%, the three-band cut names at
least one row reading `<= -34.3%` with an interval excluding zero **42.80%
+-1.11** of the time, so a band that looks much worse than the book is what a
three-row cut of a uniformly losing book produces two times in five.

The *mechanism* in `spending.md` - that a planned reward-to-risk is an output
of level geometry rather than a decision, and that the median trade reaches
38.5% of its own target - is measured separately and does not depend on this
table. **Keep the mechanism; drop the interval.**

### Never was evidence: the exit-kind table's two closing intervals

`spending.md`'s exit table has `stop` at **-102.7% [-110.3%, -94.4%]** and
`target` at **+81.5% [+54.9%, +116.7%]**, both excluding zero. Neither is a
finding about anything: a stop that fires returns about -1R by definition and a
target that fires returns about +1R times its own ratio. The null world
reproduces both - its stop row reads -1.0146 on the untrailed shapes against a
nominal -1.000, and its target row +0.786 against the live +0.796. They are
useful as a check that the accounting works, which is how the null world uses
them, and they should never be counted among the intervals a page "found".

### Confirmed, with a caveat about what it means: `winning.md`'s null

Nothing in the feature set separates winners from losers, and the calibration
says the page was right for the right reason. Its permutation control clears at
**4.80% +-0.68** on null books - nominal - against 98.50% for the uncontrolled
read it replaces, and a null book's biggest gap reaches the live 0.433 in 12.9%
of cases. That is the only method on this desk that calibrates.

The caveat is power: at 397 closes the same scan finds an injected
+20%-of-risk effect 12.00% +-2.06 of the time. So `winning.md`'s null is
honest, and it means "this book cannot answer the question" rather than "the
answer is no".

### Withdrawn as evidence: `spread_over_risk` on `P(stop)`

It clears the same control in **98.30% +-0.41** of null books, and 99.67%
+-0.33 when the cost is charged as a price. It is the cost, not a pattern. The
gate it motivated can stay - `exiting.md` derived it from a cost decomposition
that does not depend on this scan - but the scan is not evidence for it.

## Two seeds, and the spread between them

Everything in `calibfpr.py` was run twice, at seed 606 and seed 909, on 2,000
disjoint null books each. The headline numbers move by about their standard
errors:

| | seed 606 | seed 909 |
| --- | ---: | ---: |
| coverage at n=29 | 7.05% | 7.05% |
| coverage at n=133 | 4.70% | 5.50% |
| twelve-row family-wise, uncorrected | 31.85% | 32.10% |
| twelve rows in the book-rate world, >=1 reads `<= -34.3%` and excludes zero | 71.15% | 73.35% |
| +5% of risk detected at 80% | 2,393 closes | 2,569 closes |

One pre-registered condition **changes its answer between seeds**: "coverage at
n=133 is within one standard error of nominal" fires at 606 (4.70%) and does
not at 909 (5.50%), because both sit within about one standard error of 5% and
the condition's threshold is exactly one standard error. Reported rather than
resolved: at n=133 the interval covers, and a one-SE test on a rate estimated
from 2,000 books cannot say more than that.

## What would have killed this

Written into the harness docstrings before any number was read.
`calibfpr.py` fired 2 of 13 at seed 909 and 3 of 12 at seed 606 - the
difference is the n=133 condition above and one condition added between the two
runs - `calibscan.py` 3 of 6, `calibnull.py` 1 of 5.

| condition | outcome |
| --- | --- |
| a t-test on Gaussian data does not reject at 5% | **held** - 4.86% +-0.11 over 40,000 trials |
| the `t_crit` expansion misses the published quantiles | **held** - worst gap 0.00014 |
| the vectorised bootstrap disagrees with `spending.interval` | **restated and held** - the original fixed tolerance fired on Monte Carlo noise; see above |
| the cheap bootstrap disagrees with the shipping 20,000 draws | **held** - 7.05% against 7.05% at n=29, 4.70% against 4.85% at n=133 |
| coverage at n=29 lands within 1 SE of nominal | **held** - it does not; 7.05% against 5.00%, which is the finding rather than the failure |
| coverage at n=133 is within 1 SE of nominal | **FIRED at seed 606** (4.70%), held at 909 (5.50%) - either way the twelve-row result is reported as multiplicity, not as a criticism of the bootstrap |
| the twelve-row cut fires no more often than one row | **held** - 32.10% against 6.05% |
| a rate lands on exactly 0.0500 | **FIRED once**, in `calibscan`'s Gaussian toy: 30/600. Hunted - it is the granularity, one cell in eleven |
| power at `spending.md`'s quoted 1,000 closes for +5% is near 80% | **FIRED on both seeds** - 39.4% and 46.8%, so that page's sample-size arithmetic is the 50% power point |
| no other construction beats the percentile bootstrap at n=29 | **held** - studentised, 4.75% against 6.95% |
| Bonferroni over the rows that get an interval restores 5%, percentile | **FIRED** - 10.15%, so it is not recommended on the percentile bootstrap |
| the same, studentised | **held** - 2.65%, conservative, and recommended with that stated |
| the permutation control does not reject at 5% on Gaussian toy data | **held** - 5.00% +-0.89 |
| the permutation control does not reject at 5% on null books | **held** - 4.80% +-0.68 over 1,000 books |
| the scan cannot find a 40%-of-risk edge at 80% | **FIRED** - 41.20% +-3.11, so the scan has little power and its nulls mean less than they look |
| the priced pool's mean R equals minus mean `spread_over_risk` within 3 SE | **FIRED** - z = +3.06, 0.69 points of risk on a 15.1-point cost; reported, not resolved |
| the null world's mean R misses the theorem by 3 SE | **held** - z = -0.65 on a million closes and z = +1.33 on the scan's flat pool of 420,024 |
| the null book does not resemble the live one | **partly FIRED** - the stop row reads -0.806 against -1.028 because trailed exits wear the `stop` label; -1.0146 on the untrailed shapes |

## What this does not say

**It does not say the live book is a null.** It says the desk's methods, at the
desk's sample sizes, cannot tell the difference between the live book's
strategy table and a table cut from a book with no edge in it. The book-wide
-22.2% is real and survives.

**It does not measure the desk's whole process.** Only the cuts `spending.py`
and `winning.py` make. A method not run here has not been calibrated here.

**The null world is not the market.** Its per-close spread is 2.8% wider than
the live one, its skew lower (+0.58 against +0.72) and its target share twice
as high. A false-positive rate measured on a distribution 3% wider than the
real one is, if anything, slightly conservative - the real book's heavier left
tail would make the percentile bootstrap worse at small n, not better.

**And the false-positive rates are themselves estimates.** Each is quoted with
its binomial standard error over 2,000 disjoint null books; the third
significant figure of any of them is noise.
