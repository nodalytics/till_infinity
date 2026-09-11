# Rebuilding the generators, and what breaks when you try

[deriving.md](deriving.md) wrote the Deriv synthetics down as processes. This
page does the other half of the reverse engineering: it takes that specification
and **re-instantiates** it, one simulator per family, built from the published
and derived parameters alone, and then tries to tell the simulator's output apart
from the feed.

The distinction matters more than it sounds. A description that cannot be
re-instantiated is a list of statistics that happened to be true; one that can is
a model, and a model can be interrogated where the sample runs out - which is
exactly where this desk keeps needing answers, because sixty days of bars and
twenty-four hours of ticks is not enough sample to price a tail.

Eight harnesses. [`rebuildgen.py`](harness/rebuildgen.py) holds the generators,
the statistical battery and the discriminator, and states no results;
[`rebuildall.py`](harness/rebuildall.py) is the one command that runs the rest.
Of the studies, [`rebuildpaper.py`](harness/rebuildpaper.py) needs no database
at all and has run; [`rebuildvol.py`](harness/rebuildvol.py),
[`rebuildstep.py`](harness/rebuildstep.py),
[`rebuildspike.py`](harness/rebuildspike.py),
[`rebuildpower.py`](harness/rebuildpower.py) and
[`rebuildjudge.py`](harness/rebuildjudge.py) read `research.db` and wait on the
lab. Each states its kill conditions in its docstring before any number, and
each records - in the same docstring - which conditions were amended during a dry
run against synthetic data and what forced the amendment.

**The summary line.** The headline this page owes is the sample size at which a
test starts separating the rebuild from the feed. On one-minute log returns for
the Volatility family it is **150,000 to 1.4 million bars** - the rebuild and the
feed are indistinguishable on the 86,410 the store holds, and on nine of twelve
feeds the rebuild is *closer to the feed than the feed's own two halves are to
each other*. The rest of the table is below.

**And the adversarial version of it, which is the stronger claim.** Against the
strongest classifier this environment carries, on the seven Volatility feeds
whose quote grid is fine enough for a tick statistic to be about the law at all,
**no arm beats its own real-against-real floor at any sample size** - the test
arm sits *below* the floor on both views and `n*` is infinite. That took four
attempts at one term of the specification, three of which are refuted and are
published as such. The other families' `n*` runs from **8.2x the stored sample**
(Step Index) to **59 ticks** (Boom 300, where the rebuild is simply wrong).

**Two corrections came out of the loop rather than out of the plan.** The tick
shortfall this page called a collection failure is not one - it is the repeated
quote, and the two quantities agree on twelve feeds of twelve. And the shared
Range Break width of 60 is **withdrawn**: given a simulated truth, the estimator
that measures the range directly returns the width it was given to within 12%,
and it says 39.

## The parameter budget, which is the whole experiment

A rebuild is only evidence about a specification if it is given the
specification and nothing else. So each generator gets a fixed, countable set of
numbers and no access to the feed beyond them:

| family | what the rebuild is given | count | source |
| --- | --- | --- | --- |
| Volatility | annualised volatility from the name, publication rate | **2** | the instrument's name, and `generators.md`'s 0.500/s and 0.995/s |
| Jump | the name, the publication rate, the jump rate, and `1.322^2 - 1 = 0.7477` of the diffusive variance for the jumps | **3 + a budget** | `generators.md` |
| Step | step 0.1, p(up) 0.5, one tick a second, spread one step | **4** | Deriv's own subtitle, confirmed by `generators.md` |
| Boom / Crash | `lambda`, `E[g]`, `CV[g]`, `E[J]`, `median J` | **5** | `deriving.md` section five, per feed |
| Range Break | the break rate, the unit step, the tick rate - **and two parameters that are not published anywhere** | 3 + 2 | `deriving.md` section four, plus a fit |

Three things are deliberately *not* given to any generator: the
Broadie-Glasserman-Kou constant **0.5826**, the Parkinson ratios **0.870** and
**0.909**, and the variance-ratio curves. Those are the predictions.

Also not given: the closure `E[J] = lambda * E[g]`. Boom and Crash are built
from the published `E[g]` and `E[J]` as stated, so whether the rebuilt path comes
out a martingale is a result rather than a construction.

## Three things that decide whether this works at all

**A bar is not the process.** `research.db` holds one-minute bars built from a
tick stream, so every generator here emits *ticks* and one shared aggregator
turns them into bars: open, high, low and close are the first, extreme and last
of the ticks inside the bar, and the previous close is not a candidate for the
range. Simulating bars directly - drawing a one-minute return and inventing a
high and a low around it - gets the volatility right and the high/low statistics
wrong, and would have produced a confident, false conclusion that the
specification is incomplete.

**The quote grid is part of the observation.** Deriv publishes a rounded price.
A continuous-valued simulation and a discretely quoted feed differ in their
tick-return distribution at the first decimal, which a two-sample
Kolmogorov-Smirnov test on eighty thousand points sees instantly and which has
nothing whatever to do with whether the generator is right. The grid is read off
the real quotes - decimal precision for the scale, the greatest common divisor of
the tick moves for the spacing, because two of these feeds are quoted *coarser*
than their decimals suggest - and every generator rounds to it while carrying an
unrounded state forward.

**The Monte Carlo has to be the sharper instrument.** Every rebuild runs at
several times the feed's own sample across several independent seeds, and every
headline number is reported as a mean and a seed-to-seed spread beside the real
feed's standard error. A comparison where the two are the same size has tested
the simulator's luck, not the specification.

## The question this page answers with a number

"Indistinguishable" is not a result until it carries a sample size, so the
headline is not a table of passes. It is, per family:

    n*  =  the sample size at which a two-sided two-sample Kolmogorov-Smirnov
           test at alpha = 0.05 separates the rebuild from the feed

read two ways that have to agree. Empirically, by subsampling both sides to `n`
and counting rejections; and in closed form, from the estimated sup-distance
`D` between the two laws, since equal samples reject when `D > c*sqrt(2/n)` with
`c = 1.3581`, giving `n* = 2c^2/D^2`. Where the real sample runs out before the
test fires - which is most of them - the honest answer is a **lower bound** and
is reported as one.

## The stronger question, and the one this page is really about

Matching a list of statistics is weak evidence. Many wrong processes match four
moments, and a two-sample test on a marginal is blind to everything about the
*ordering* of the increments. The operational definition of replication is that
**nobody can tell which feed is which**, so the primary criterion here is
adversarial: [`rebuildjudge.py`](harness/rebuildjudge.py) trains the strongest
classifier this environment carries on real-against-rebuilt and reads its
held-out AUC.

There is no scikit-learn on the lab, so the learner is a small histogram
gradient-boosting ensemble written into
[`rebuildgen.py`](harness/rebuildgen.py) - quantile-binned features,
depth-limited trees, second-order leaf weights, which is the LightGBM core and
nothing more. It is given three views of each family:

* **k-tuples** of consecutive increments, raw, which tests the joint law
  directly rather than through a summary;
* **window summaries** - thirty-odd statistics over sixty consecutive
  increments, including the ones no marginal test can see: sign runs, the
  autocorrelation of the increments and of their absolute values, the scaled
  range, the share of the window carried by its three largest moves, the count
  of distinct magnitudes;
* **bar OHLC windows**, which is the only view with any power over the tick rate,
  because a tick rate halved and rescaled is invisible in the increments and
  lives entirely in how many ticks resolve a bar's high and low.

An AUC alone means nothing, so every arm is run three more times: on **real
against real**, two disjoint halves of the genuine feed, which is the score
"indistinguishable" actually earns on this data; on **rebuild against rebuild**,
which is the Monte Carlo floor; and on four **deliberately wrong generators**,
which is what says the classifier has any power at all. Three design mistakes
that all inflate an AUC were found and fixed during the dry run, and are recorded
in the harness because each of them would have produced a confident false
positive:

1. **Unequal rows per arm.** An AUC is a property of the classifier as well as
   of the data, and a learner handed twice the rows finds more. The first version
   compared a test arm at 12,000 rows against a floor at 6,000 and read a
   *rebuild-against-rebuild* floor above the real-against-real one.
2. **Unequal feed composition.** Pooling twelve feeds of different lengths into
   two classes lets the classifier learn feed identity, which is shared between
   the classes and has nothing to do with the law. Every build is now truncated
   to its own feed's real tick count, and the bar floor is built per feed and
   then pooled - splitting a pooled row block in half put feeds 1-2 on one side
   and 4-5 on the other and scored **0.96**.
3. **Coarsely quoted feeds.** A feed whose quote lattice is wider than its own
   per-tick sigma has almost all of its information in the rounding, and the
   rounding interacts with the price level. Lattice points per sigma is printed
   per feed and the coarse ones are pooled separately.

**Durations are reported and excluded from the headline.** `research.db`'s tick
timestamps are our own collector's receive clock rather than the venue's
publication clock ([lagging.md](lagging.md)), so a discriminator handed
inter-arrival times is reading our network. It is separable at AUC 1.0 by
construction and says nothing about any generator.

## And whether the venue's randomness is sound

These feeds come out of a seeded generator that the venue makes audit claims
about, so the same page asks a different question with the same data: put the
increment stream through the standard batteries. Serial correlation at fifty
lags, chi-square on 2- and 3-dimensional grids of consecutive tuples, the gap
test, overlapping permutations, a collision test, monobit and runs on the bit
stream - and the empirical form of the **spectral test**, which is the one that
matters. A linear congruential generator's k-tuples lie on a small family of
parallel hyperplanes, so projecting them onto the right integer direction
collapses them and leaves an enormous empty band; the statistic is the largest
gap in units of the `ln(n)/n` a genuine uniform stream produces.

Three choices in that battery are load-bearing:

* **The uniformisation is a rank transform**, not a Gaussian CDF. A Jump index's
  marginal is a mixture and a quantised quote puts an atom on every lattice
  point, so pushing either through `Phi(x/s)` fails every uniformity test for
  reasons that are about the marginal rather than the source. The rank transform
  makes the marginal exactly uniform by construction and leaves the
  **dependence** structure, which is what an RNG battery is actually asking.
* **The lattice search has to reach the generator's own coefficients.** RANDU
  satisfies `x[n+2] = 6 x[n+1] - 9 x[n]`, so the vector that collapses its
  3-tuples is `(9, -6, 1)` and a search over +-4 never finds it. The first
  version searched +-4 and cleared RANDU; at +-10 it reads a gap ratio of
  **2,616** against numpy's **2.1**, which is the resolution the Deriv result is
  quoted against.
* **Two tests were dropped, not passed.** Diehard's birthday spacings and
  Knuth's collision test both read the *spacing* of the values rather than their
  dependence, and a quantised quote leaves only tens of thousands of distinct
  values in a stream of that length. Run anyway they reported z = -334 and
  z = +120 on **every** stream including numpy's own PCG64 - tests with no
  resolution rather than findings. They are calibrated, recorded and excluded,
  and the battery that remains is the dependence half: serial correlation,
  2-, 3- and 4-dimensional tuple grids, the gap test, overlapping permutations
  and the lattice search.

**What this sample can support, said in advance.** Twenty-four hours of ticks is
43,000 to 86,400 draws a feed, about a million pooled. That is four orders of
magnitude short of what TestU01's SmallCrush wants. A pass excludes a grossly
broken source - a short period, a visible lattice, a stuck bit - and does not
certify a cryptographic one.

## What is established

**Everything on this page has now run against the feed.** For a while it had not:
the research lab went unreachable part-way through this work - "no route to host",
not a slow link - and `research.db` exists nowhere else, so the page was for a
time a calibrated apparatus and a set of pre-registered interpretations with no
measurements in it. That division is gone and the pre-registration is kept
verbatim at the end, where the rows can be read against what came back.

**Two things about the order of work are worth keeping.** The apparatus was
calibrated before it was pointed at anything - 103 comparisons against published
measurements, two of which came back as corrections to `deriving.md`, and every
harness run end to end against a synthetic database of sixty days of bars and
twenty-four hours of ticks for all twenty-six feeds, generated by these same
generators, which is how the bugs listed below were found. And every
interpretation below the pre-registration table was written before the numbers
existed.

It is one command, [`rebuildall.py`](harness/rebuildall.py), and about two hours
of one core.

### The Volatility family, against the feed

Two numbers per instrument - the volatility in the name and the publication rate
- simulated as ticks, aggregated into bars, and compared with 86,410 real bars
and 24 hours of real ticks a feed. Four seeds, ten times the real sample each.
**189 pre-registered comparisons, 24 fired**, and the failures are concentrated
rather than scattered.

**Ten of the twelve are reproduced by two numbers.** Realised annualised
volatility comes out between **0.9996 and 1.0005** of the name against a
pre-registered band of 0.5%; kurtosis 2.994 to 3.004 against a feed reading
2.982 to 3.018; the structure-function Hurst exponent 0.4988 to 0.5015; and the
Parkinson-to-close ratio within **0.00% to 0.28%** of the feed's own, which is
the sharpest of them because 0.870 and 0.909 are not inputs anywhere. Pooled by
tick rate the rebuild reads **0.8702** and **0.9057** against the feed's 0.8698
and 0.9084.

**On bar returns the rebuild is indistinguishable, and by a margin.**

| feed | KS D | 5% critical | n* | D, feed's own halves |
| --- | --- | --- | --- | --- |
| volatility_25_index | 0.00161 | 0.00509 | **1.4e6** | 0.00477 |
| volatility_25_1s_index | 0.00188 | 0.00509 | **1.0e6** | 0.00517 |
| volatility_50_1s_index | 0.00203 | 0.00509 | **8.9e5** | 0.00493 |
| volatility_100_1s_index | 0.00220 | 0.00509 | **7.6e5** | 0.00811 |
| volatility_10_index | 0.00234 | 0.00509 | **6.7e5** | 0.00363 |
| volatility_75_index | 0.00337 | 0.00509 | **3.3e5** | 0.00536 |
| volatility_100_index | 0.00433 | 0.00509 | **2.0e5** | 0.00771 |
| volatility_50_index | 0.00500 | 0.00509 | **1.5e5** | 0.00812 |
| *volatility_150_1s_index* | *0.01954* | *0.00509* | *9.7e3* | *0.02436* |

Eleven of twelve do not reject, against a pre-registered bar of three. **On nine
of twelve the rebuild sits closer to the feed than the feed's first thirty days
sit to its last thirty.** So `n*` for this family is **150,000 to 1.4 million
one-minute bars**, against the 86,410 that exist - between two and sixteen times
the whole store.

**On tick returns seven of twelve reject, and the reason is ours.** The failures
are not scattered across the family; they are a near one-for-one function of how
many ticks our own collector dropped:

| feed | ticks captured of 86,400 | drop | KS D on tick returns |
| --- | --- | --- | --- |
| volatility_25_1s_index | 86,391 | 0.01% | 0.0033 |
| volatility_50_1s_index | 86,384 | 0.02% | 0.0035 |
| volatility_75_index | 43,179 | 0.05% | 0.0035 |
| volatility_25_index | 43,103 | 0.2% | 0.0032 |
| volatility_75_1s_index | 85,980 | 0.5% | **0.0081** |
| volatility_10_1s_index | 84,468 | 2.2% | **0.0160** |
| volatility_100_1s_index | 84,250 | 2.5% | **0.0259** |
| volatility_100_index | 41,925 | 3.0% | **0.0263** |
| volatility_250_1s_index | 83,644 | 3.2% | **0.0281** |
| volatility_150_1s_index | 56,793 | **34.3%** | **0.3699** |

`D` tracks the drop fraction almost exactly - 3% dropped gives 0.026, 34%
dropped gives 0.37 - and every feed captured to better than half a percent
passes. A dropped tick merges two increments into one, which fattens the
tick-return distribution precisely where a KS test looks.
The one-minute bars are unaffected because the venue builds them from its own
complete stream.

**That paragraph called the shortfall a collection failure and it is not one.**
The missing ticks are quotes that did not change, and the two quantities agree on
all twelve feeds to within 8% - see *Whose the missing repeated quotes are*
below. The KS rejections stand; what changes is that the fix belongs in the
rebuild rather than in the collector, and `volatility_150_1s_index` is the
extreme of a continuum rather than a broken feed.

**The two coarsely quoted feeds fail, and one of the failures is mine.**
`volatility_150_1s_index` and `volatility_250_1s_index` are the pair `twins.md`
flagged for a coarse quote grid, and `volatility_250_1s_index` is quoted at
`1e-05` on a price of **0.2664**. Simulated for ten times the observed span its
realised volatility comes out at **341.6 +- 183.2** against a nominal 250 and a
feed reading 250.75. That is not a defect in the specification: a geometric
process at 250% annual volatility wanders by a factor of `e^±6` over six hundred
days, and a grid fixed in price that is fine at 0.27 is ruinous at 0.0004. **A
geometric generator cannot be simulated for ten times its observed span when its
quote grid is absolute**, and the honest rebuild of those two feeds is one at the
feed's own length.

**The controls behaved and the parameter recovery is clean.** The honest rebuild
is caught by nothing; sigma 1% wrong is caught by the volatility test; Student-t
tick innovations by kurtosis, Parkinson and the tick KS; half the publication
rate by Parkinson and the tick KS and nothing else; a two-state volatility by
four tests at once. Fitting the rebuild's own output back with the estimators
used on the feeds recovers the input volatility to within **1.08 standard
errors** on all ten sound feeds, with `H` in 0.4988-0.5015 and no drift past 1.65
standard errors.

**And the 0.5826 correction is emergent, on real bars.** The rebuild was never
told about it:

| a:b | P(up) on the feed | **on the rebuild** | continuous | BGK-corrected |
| --- | --- | --- | --- | --- |
| 5:5 | 0.5008 | **0.5018** | 0.5000 | 0.5000 |
| 3:1 | 0.3073 | **0.3081** | 0.2500 | 0.3064 |
| 2:10 | 0.8042 | **0.8053** | 0.8333 | 0.8038 |

with `E[tau]` at 31.485 against the feed's 31.279 and a continuous 25.000.

**The Jump family: reading A, and a tail that is still wrong.** Diffusion at the
name with `1.322^2 - 1` of its variance in the jumps realises **1.3229 to
1.3249** times the name on all five feeds; the alternative reading, diffusion
already at 1.322x, gives **1.581** and is refuted. But the feed's one-minute
kurtosis is **12.8 to 14.2** and the rebuild's is **7.2 to 8.1**, and resampling
the jump magnitudes from the feed's own jumps only reaches 6.6 to 8.6. So the
variance budget is right and **the jump size distribution is not**: the real
Jump indices have far fatter tails than a Poisson process with the measured rate
and magnitudes can produce, which means the jumps are either clustered or much
more variable in size than a 24-hour sample shows.

### The tick-monitored barrier: the published hit rate overstates a 3:1 target by four points

This is the result with money attached and it was predicted before it was
measured. `deriving.md` section one is **close-monitored** - `derivegbm.py` walks
non-overlapping windows on one-minute closes - so `P(up) = (b+B)/(a+b+2B)` with
`B = 0.5826` is the answer for a rule that can only act once a minute. **A real
stop is hit on a tick.** The Broadie-Glasserman-Kou shift scales as
`beta*sigma*sqrt(dt)`, so at `tpb` ticks a minute it falls from 0.5826 of a
one-minute sigma to `0.5826/sqrt(tpb)` - 0.1064 at thirty ticks a bar, 0.0752 at
sixty - and the trading-relevant hit probability sits between the continuous
answer and the published one.

Replayed tick by tick on the rebuilt paths and on `research.db`'s own tick table:

| ticks/bar | a:b | rebuilt | **real feed** | +-SE | **predicted** | z vs predicted | published (close) | z vs published |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 30 | 3:1 | 0.2608 | **0.2664** | 0.0110 | **0.2626** | +0.34 | 0.3064 | **-3.63** |
| 30 | 1:3 | 0.7355 | **0.7425** | 0.0110 | **0.7374** | +0.47 | 0.6936 | **+4.44** |
| 30 | 2:10 | 0.8235 | 0.8385 | 0.0253 | 0.8275 | +0.43 | 0.8038 | +1.37 |
| 60 | 3:1 | 0.2621 | **0.2638** | 0.0091 | **0.2591** | +0.52 | 0.3064 | **-4.69** |
| 60 | 1:3 | 0.7439 | **0.7458** | 0.0091 | **0.7409** | +0.54 | 0.6936 | **+5.73** |
| 60 | 2:10 | 0.8358 | 0.8430 | 0.0227 | 0.8292 | +0.61 | 0.8038 | +1.72 |

Six pooled cells, about 2,100 and 2,600 real non-overlapping trades. **The feed
agrees with the prediction to within 0.61 standard errors everywhere and
disagrees with the published close-monitored figure by up to 5.7.** Per feed,
across 36 cells, the rebuilt column sits within 2.02 standard errors of the
prediction and mostly within one.

So the operational number is this. A trade with a stop one sigma away and a
target three sigmas away is:

* **25.0%** continuously - the textbook answer, and wrong;
* **30.7%** to a rule that can only act on the close - `deriving.md`'s table;
* **26.3%** to a stop sitting in the book, which is every stop this desk places.

**The published figure overstates a 3:1 target's chance by four points**, which
is a fifth of the edge such a geometry is supposed to carry, and it is the figure
`deriving.md` recommends replacing estimators with. The correction is one
substitution - `B -> B/sqrt(tpb)` - and it is now measured on both a rebuild and
the feed.

It does not change the expectancy. `E[net] = -c` holds against any monitoring
rule, because the barrier is still symmetric about a martingale. What it changes
is the *shape* a sizing rule assumes, and a desk that believes a 3:1 is a 30.7%
shot when it is a 26.3% shot is mis-stating its own hit rate by a seventh.

### The discriminator is calibrated, and it has a map of its own blind spots

On ground truth - a rebuild against a feed drawn from the identical law - every
arm sits where it should, and the wrong generators are caught by the arm that
should catch them and by no other:

| arm | floor (real vs real) | rebuild | sigma +2% | Student-t(6) | half the tick rate | two-state volatility |
| --- | --- | --- | --- | --- | --- | --- |
| k-tuples of 8 increments | 0.482 | **0.509** | 0.512 | **0.623** | 0.513 | **0.668** |
| 60-increment windows | 0.481 | **0.483** | 0.558 | **0.834** | 0.548 | **0.950** |
| 30-bar OHLC windows | 0.493 | **0.511** | 0.502 | **0.559** | **0.862** | **0.900** |

Three things worth reading off it. The **bar arm is the only one with any power
over the tick rate** - halve the publication rate and rescale, and the increments
are identical by construction, so the whole of it lives in how many ticks resolve
a bar's high and low; that is 0.862 on bars and nothing anywhere else. The
**window arm is where dependence shows** - a two-state volatility scores 0.950
there against 0.668 on raw tuples. And **sigma +2% is not caught by any of them**,
which is the resolution statement: a distribution test is the wrong instrument
for a scale parameter, and `genvol.py`'s realised-versus-nominal comparison is
**5.5x sharper** than KS on the same bars.

### The discriminator loop: four ways of putting a price on a lattice, three refuted

The discriminator's value is not its verdict, it is its **map**. An arm that
beats the floor comes with a ranked list of what carried it, and every entry on
that list is a hypothesis about the specification that can be measured directly
and then fixed. [`rebuildladder.py`](harness/rebuildladder.py) is that loop run to
exhaustion: read the largest feature, measure it on the feed rather than arguing
from an AUC, name the minimal term it implicates, add exactly that term, re-run -
and publish the rungs that failed beside the one that survived, because a list of
additions that did not work is what makes the surviving specification credible.

Every rung is the same generator - driftless GBM at the volatility in the name,
at the published tick rate - and differs only in how a continuous price is put
onto the venue's quote lattice. **No rung adds a parameter**, so the budget at
the top of this page is unchanged by any of them.

**The floor is measured once and reused by every rung.** Two disjoint halves of
the genuine feed, through the same feature functions, at the same rows per class
as every test arm below. An arm with more features has a higher floor, and
comparing a rich test against a lean floor manufactures a win, so there is one
floor on this page:

| arm | rows/class | **floor, real against real** |
| --- | --- | --- |
| k-tuples of 8 increments | 45,339 | **0.4972** [0.4916, 0.5025] |
| 60-increment windows | 6,045 | **0.6026** [0.5890, 0.6174] |
| 30-bar OHLC windows | 15,840 | **0.4955** [0.4872, 0.5048] |

A window floor of 0.60 is not noise. It is the first thing this loop found and it
is dealt with at the end of the section; it is about `research.db` rather than
about Deriv.

**The ladder.** Pooled over the twelve Volatility feeds, each increment divided by
its own nominal per-tick sigma, four seeds' worth of rebuild truncated to each
feed's own tick count:

| rung | what it does | window | k-tuple | bar OHLC | largest feature over the floor |
| --- | --- | --- | --- | --- | --- |
| `price` | round the accumulated price onto the grid | 0.7649 **caught** | 0.5510 **caught** | 0.5099 at floor | `frac_zero` **+0.1856** |
| `bump` | round the increment, move one unit on a zero | 0.6833 **caught** | 0.5455 **caught** | 0.5031 at floor | `absq10` **+0.0890** |
| `resample` | round the increment, redraw until the quote changes | 0.6275 at floor | 0.5124 **caught** | 0.5026 at floor | `absq10` +0.0168 |
| `drop` | round the price, delete the repeated quotes from the ticks | 0.6403 **caught** | 0.5160 **caught** | 0.5099 at floor | `absq10` +0.0122 |

The largest single feature's advantage over the floor falls **0.186 to 0.089 to
0.017**, which is the loop working. Each fall is one term, and each term was
chosen by measuring the feature rather than by guessing at it.

**Rung 1, `price`, is refuted by the fraction of repeated quotes.** A zero tick
move is a quote printed twice. Rounding a continuous price onto the grid produces
them at the rate `P(|N(0,s)| < g/2)`, which is 2.92% of all ticks on
`volatility_100_index` and **28%** on `volatility_150_1s_index`, whose per-tick
sigma is 1.1 lattice units. The stored feed shows **0.083%** and **0.90%**. The
discriminator found it without being told: `frac_zero` reads AUC 0.6864 against
its own floor of 0.4992, and it is the largest split gain in the ensemble by a
factor of three.

**Rung 2, `bump`, is refuted by the one-unit bin.** If the venue never repeats a
quote, where does the zero bin's mass go? `bump` puts all of it on `|1|`, which
is the obvious reading and is wrong. The three quantisers differ in exactly two
numbers - `P(0)` and `P(|1| given the quote moved)` - so those two are the whole
test, and each rule is fitted its own sd from the feed's own increment variance
so that this is a test of shape and not of scale:

| feed | `P(0)` feed | `price` | `P(1\|moved)` feed | `price` | `bump` | `resample` |
| --- | --- | --- | --- | --- | --- | --- |
| volatility_100_index | 0.00083 | 0.02923 | 0.06059 | 0.06006 | **0.08755** | 0.06100 |
| volatility_250_1s_index | 0.00045 | 0.03189 | 0.06744 | 0.06568 | **0.09549** | 0.06680 |
| volatility_100_1s_index | 0.00039 | 0.02503 | 0.05183 | 0.05125 | **0.07500** | 0.05192 |
| volatility_10_1s_index | 0.00033 | 0.02278 | 0.04706 | 0.04654 | **0.06825** | 0.04709 |
| volatility_75_1s_index | 0.00012 | 0.00454 | 0.00870 | 0.00912 | **0.01362** | 0.00915 |

Median worst `|z|` over those two statistics across the twelve feeds: **`price`
160.8, `bump` 13.1, `resample` 2.8**, and `resample` is the best of the three on
**eleven of twelve**. The exception is `volatility_150_1s_index`, where almost
every move is one unit anyway and `bump` and `resample` are not separable - which
is a statement about power, not a result.

### Whose the missing repeated quotes are, and why the tick shortfall was never a drop

The obvious reading of the two refutations above is that Deriv *moves on* its
quote lattice rather than rounding onto it - a property nobody had written down.
That reading is wrong, and the control that kills it is cheap.

**A collector that never stores an unchanged quote produces the identical
histogram**, and it leaves a signature: the gap to the next tick it did store is
two publication intervals rather than one. So the share of doubled inter-tick
gaps has to be at least the share of zero moves the rounding predicts. It is
almost exactly equal to it, on twelve feeds of twelve:

| feed | modal gap | doubled gaps | zero moves a rounded price predicts | ratio |
| --- | --- | --- | --- | --- |
| volatility_100_index | 2001 ms | 2.943% | 2.923% | **1.007** |
| volatility_250_1s_index | 1001 ms | 3.201% | 3.189% | **1.004** |
| volatility_100_1s_index | 1001 ms | 2.497% | 2.503% | **0.998** |
| volatility_10_1s_index | 1001 ms | 2.242% | 2.278% | **0.985** |
| volatility_25_index | 2000 ms | 0.227% | 0.230% | **0.990** |
| volatility_10_index | 2000 ms | 0.325% | 0.331% | **0.982** |
| volatility_50_index | 2000 ms | 0.334% | 0.344% | **0.973** |
| volatility_75_1s_index | 1000 ms | 0.490% | 0.454% | 1.078 |
| volatility_150_1s_index | 1016 ms | 34.154% | 28.423% | 1.202 |

So **the venue may well round a continuous price onto its grid; we never see the
repeated quote.** The lattice question is not answerable from `research.db` at
all, and a rebuild's job is not to reproduce the venue's quantiser but to
reproduce *the observation*, which is the venue's stream with its repeated quotes
removed. That is the `drop` rung: round the price, build the bars from every
tick - because the venue builds its own bars from its own complete stream - and
delete the repeated quotes from the tick stream only.

**And the same fact retires an unexplained result earlier on this page.** The
tick-return KS section above attributes seven rejections to "how many ticks our
own collector dropped", with a drop fraction it could not explain. The shortfall
is not a drop. It is the repeated quote, and the two quantities agree on all
twelve feeds:

| feed | ticks missing of the published rate | zero moves a rounded price predicts | ratio |
| --- | --- | --- | --- |
| volatility_25_1s_index | 0.010% | 0.011% | 0.95 |
| volatility_50_1s_index | 0.019% | 0.020% | 0.93 |
| volatility_75_index | 0.049% | 0.045% | 1.08 |
| volatility_25_index | 0.225% | 0.230% | 0.98 |
| volatility_10_index | 0.322% | 0.331% | 0.97 |
| volatility_50_index | 0.331% | 0.344% | 0.96 |
| volatility_75_1s_index | 0.486% | 0.454% | 1.07 |
| volatility_10_1s_index | 2.236% | 2.278% | 0.98 |
| volatility_100_1s_index | 2.488% | 2.503% | 0.99 |
| volatility_100_index | 2.951% | 2.923% | 1.01 |
| volatility_250_1s_index | 3.190% | 3.189% | **1.00** |
| volatility_150_1s_index | 34.267% | 28.423% | 1.21 |

Twelve for twelve, eleven within 8%. Nothing was lost in transit. A feed whose
quote grid is coarse relative to its own per-tick sigma simply prints fewer
distinct quotes, and `volatility_150_1s_index` - the feed `twins.md` quarantined
and this page called "34.3% dropped" - is the extreme of a continuum rather than
a collection failure. The KS rejections stand, because a rebuild that emits every
tick is being compared with an observation that does not; what changes is that
the fix is in the rebuild rather than in the collector.

**The prediction this makes, tested.** If the tick-return rejections above are
the repeated quote, a rebuild that deletes its own repeated quotes should shrink
them. It does, and not all the way:

| feed | KS `D`, `price` rebuild | **KS `D`, `drop` rebuild** | change |
| --- | --- | --- | --- |
| volatility_250_1s_index | 0.0281 | **0.0151** | **-46%** |
| volatility_100_1s_index | 0.0259 | **0.0161** | **-38%** |
| volatility_150_1s_index | 0.3699 | **0.2893** | **-22%** |
| volatility_100_index | 0.0263 | **0.0192** | **-27%** |
| volatility_75_1s_index | 0.0081 | **0.0064** | -21% |
| volatility_50_1s_index | 0.0035 | 0.0025 | -29% |
| volatility_10_1s_index | 0.0160 | 0.0173 | +8% |

Six of twelve still reject where seven did, and the distances on the four feeds
that rejected hardest fall by **22% to 46%**. So the repeated quote is most of
that gap and not all of it, and what is left is the same thing the band split
names: the rebuild's price level wanders on its own path, so its lattice points
per sigma follow a different trajectory from the feed's, and a KS test on tick
returns is sensitive to exactly that. Every feed that passes is one with 87 or
more points per sigma; every feed that rejects has 17 or fewer. `n*` on the KS
statistic runs from **1.7e5 to 5.9e5** ticks on the passing feeds and **44** on
`volatility_150_1s_index`.

**`drop` rather than `resample`, on one number.** The two have the same tick law
and different bars. Redrawing a zero increment until the quote changes raises the
per-tick second moment by `1/(1-P(0))` - **1.5% of sigma on
`volatility_100_index`** against a volatility band this page pre-registers at
0.5% - because every tick that would have stood still now moves. Deleting the
repeated quote instead leaves the bars exactly as the venue builds them and
deletes only what our collector deletes.

### Where the loop stops, and what one more term would not fix

After `drop` the largest surviving feature is `absq10` - the tenth percentile of
`|increment|` in a sixty-tick window - at +0.0122 over its floor, against
+0.1856 for the feature that started this. The loop stops there, and the reason
is worth more than another rung.

**Split the arms by quote resolution.** Lattice points per per-tick sigma runs
from 13.2 to 3,674 across the twelve feeds, and the grid is fixed *in price*
while the price is geometric - so a feed's effective resolution drifts as its
level drifts, within the 24 hours of the sample and differently on every realised
path. `volatility_250_1s_index` runs at 11.2 points per sigma in its first twelve
hours and 13.2 in its second. Each band gets its own real-against-real floor and
its own Monte Carlo floor - two *independent rebuilds of the identical law*:

| band | feeds | arm | rebuild vs feed | floor, feed vs itself | MC floor, rebuild vs rebuild | `n*` |
| --- | --- | --- | --- | --- | --- | --- |
| **>= 50 points/sigma** | 7 | window | **0.5040** [0.4841, 0.5217] | 0.5105 | 0.4988 | **inf** |
| **>= 50 points/sigma** | 7 | k-tuple | **0.4928** [0.4858, 0.4999] | 0.5019 | 0.5039 | **inf** |
| < 50 points/sigma | 4 | window | 0.8371 | 0.7279 | 0.6897 | 239 |
| < 50 points/sigma | 4 | k-tuple | 0.5861 | 0.5148 | 0.5346 | 941 |

**On the seven feeds whose quote grid is fine enough for a tick statistic to be
about the law at all, no arm beats its floor at any sample size.** Test, floor
and Monte Carlo floor all sit inside 0.49-0.51, and the test arm is *below* both
floors on both views. That is the strongest statement this battery can make and
it is stated with its scope: seven feeds, a tick arm and a window arm, 24 hours.

**It also explains the 0.6026 pooled window floor**, which was the first thing
the loop found. The floor is 0.5105 on the fine band and 0.7279 on the coarse
one: the feed does not match *its own other half* on the four coarsely quoted
feeds, and pooling them raised the floor for everybody. A floor is a property of
the data, and this one was a property of four feeds out of twelve.

**On the coarse band the bulk of the separability is not about the law either.**
Two independent rebuilds of the identical law separate at **0.6897**, and the
feed's own halves at 0.7279, against a real-against-rebuild 0.8371. So most of
what a classifier finds there is path-to-path drift in the effective resolution,
which no term in a generator can remove, because it is a property of the realised
path rather than of the law. What is left over - about +0.11 of AUC above the
feed's own floor - is real and this page has not closed it.

**The one addition that would close it is outside the parameter budget, which is
why it is written down rather than run.** Hand the rebuild the feed's realised
price *level* through the sample - an hourly median, say - and its lattice
resolution would track the feed's instead of wandering independently. That would
almost certainly collapse the coarse band, and it would do so by giving the
rebuild 24 numbers it is not allowed to have. The honest form of the result is
therefore: **two numbers per instrument re-instantiate a Volatility index
wherever the quote grid is fine enough to tell, and where it is not, the
observation is dominated by an interaction between an absolute grid and a
geometric price that two numbers cannot carry.**

**And the `1/sqrt(n)` assumption behind every `n*` below was checked rather than
assumed.** The same arm at a quarter, a half and all of the rows: the bootstrap
half-width shrank **2.00x over 4x the rows**, against the 2.00x that scaling
predicts. The AUC gap grew with n as expected (+0.018, +0.044, +0.038), which is
why every finite `n*` is an upper bound on the separating sample rather than an
estimate of it.

### `n*`, per family and per arm - the headline this page owes

An AUC at the floor is not proof of identity. It is failure to reject at the
power available, and the honest form of the result is therefore the sample size
at which each arm *would* reject:

    n*  =  n x ( 1.96 x (se_test + se_floor) / (AUC_test - AUC_floor) )^2

The two intervals are bootstrap intervals on a held-out sample, so their
half-widths shrink as `1/sqrt(n)` while the gap between the AUCs does not - and
that shrinkage was checked rather than assumed, at **2.00x over 4x the rows**
against a predicted 2.00x. The gap *grows* with n in practice, because a boosted
ensemble handed more rows finds more, so every finite figure below is an **upper
bound** on the separating sample rather than an estimate of it. `inf` means the
arm sits at or below its own real-against-real floor: no sample separates it by
this battery, which is not the same as identity.

`have` is what one class of the arm is drawn from - half the feed, because the
other half is the floor - so an arm has already separated when `x over` is below
one.

| family | arm | gap over floor | `n*` | in ticks or bars | have | **x over** |
| --- | --- | --- | --- | --- | --- | --- |
| **Volatility, fine band (7 feeds)** | window | -0.0066 | **inf** | **inf** | 176,000 | **inf** |
| **Volatility, fine band (7 feeds)** | k-tuple | -0.0091 | **inf** | **inf** | 215,568 | **inf** |
| Volatility, all 12 pooled | k-tuple | +0.0188 | 15,804 | 126,429 ticks | 362,718 | 0.35 |
| Volatility, all 12 pooled | window | +0.0377 | 3,406 | 204,384 ticks | 362,718 | 0.56 |
| Volatility, all 12 pooled | bar OHLC | +0.0144 | 23,742 | 712,271 bars | 475,255 | **1.50** |
| Volatility, coarse band (4 feeds) | window | +0.1092 | 239 | 14,340 ticks | 55,000 | 0.26 |
| Volatility, coarse band (4 feeds) | k-tuple | +0.0713 | 941 | 7,528 ticks | 73,568 | 0.10 |
| Step Index | k-tuple | +0.0110 | 44,453 | 355,626 ticks | 43,196 | **8.2** |
| Step Index | window | -0.0057 | **inf** | **inf** | 43,196 | **inf** |
| Range Break 100 | k-tuple | +0.0132 | 25,351 | 202,810 ticks | 43,199 | **4.7** |
| Range Break 100 | window | -0.0018 | **inf** | **inf** | 43,199 | **inf** |
| Range Break 200 | k-tuple | -0.0037 | **inf** | **inf** | 43,199 | **inf** |
| Range Break 200 | window | -0.0016 | **inf** | **inf** | 43,199 | **inf** |
| Jump 75 | k-tuple | -0.0008 | **inf** | **inf** | 43,089 | **inf** |
| Jump 75 | window | +0.0882 | 680 | 40,828 ticks | 43,089 | 0.95 |
| Boom 500 | k-tuple | +0.1998 | 120 | **960 ticks** | 42,350 | 0.02 |
| Crash 500 | k-tuple | +0.1390 | 197 | 1,577 ticks | 41,885 | 0.04 |
| **Boom 300** | k-tuple | **+0.4753** | **7** | **59 ticks** | 40,950 | **0.001** |

Read in three groups.

**Where the answer is "more ticks than exist".** Step Index needs **8.2x** the
stored sample on its k-tuple arm and is unseparable on its window arm; Range
Break 100 needs **4.7x**; Range Break 200 and Jump 75 are unseparable on both.
And the Volatility family on the seven feeds where the quote grid can carry a
tick statistic is unseparable on both arms with the test arm *below* both floors.
Those are the passes, and each of them is a bound rather than a claim of
identity.

**Where the answer is "a day and a half of bars".** The pooled Volatility bar arm
would separate at 712,271 one-minute bars against the 475,255 held - **1.5x the
store**, or about ninety more days of collection on twelve feeds. That is the one
row on this table that says *collect more* rather than *fix the model*.

**Where the rebuild is simply wrong.** Boom 300 separates on **59 ticks** - a
minute of tape - and Boom 500 and Crash 500 on a thousand to five thousand. The
Boom/Crash build is not close, and the failure ledger has said so since the first
run: `n_distinct` reads AUC 0.309 there, meaning the rebuild has far fewer
distinct grind magnitudes than the feed. A lognormal on two published moments
does not pin the grind any better than it pins the jump, which is the same
finding this page already recorded for `P(J > D)` and is now quantified: **the
Boom/Crash rebuild is separable from its feed in under a minute of ticks**, and
the quantiles of both `g` and `J` need publishing.

### The randomness battery is calibrated, and two of its tests were retired

| stream | acf out of 50 | grid2 p | grid3 p | grid4 p | gap p | perm p | lattice 2-tuple | **lattice 3-tuple** |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| numpy PCG64 | 2 | 0.084 | 0.891 | 0.465 | 0.052 | 0.284 | 1.45 | **2.11** |
| RANDU *(must fail)* | 5 | 0.743 | 0.018 | **0.0034** | 0.474 | 0.481 | 1.67 | **2616** |

The lattice search recovers RANDU's own recurrence - it reports the vector
`(9, -6, 1)`, which is exactly `x[n+2] = 6 x[n+1] - 9 x[n]` rearranged - and
reads an empty band **1,240 times** what a sound generator produces. That is the
resolution the Deriv result will be quoted against, and it is worth noting that
the *classical* Diehard tests do not carry it: RANDU passes the 2-tuple lattice,
the gap test and the permutation test on this sample size, and is caught only in
three dimensions and in the 4-D grid.

Two tests were **dropped with their calibration recorded rather than passed**.
Birthday spacings and the collision test both read the spacing of the values
rather than their dependence, and a quantised quote leaves only tens of thousands
of distinct values; run anyway they reported z = -334 and z = +120 on *every*
stream including numpy's own. A test that fails its own positive control is not a
finding.

### Can the next tick be predicted before it prints - five rungs, and what each one had the power to say

Not its distribution, which is settled above, but its **value**. This is the last
route by which the generated 72% of this book could ever pay, and the prior is
strongly that it closes negative: Deriv is regulated, audits its generator, and a
cryptographic source is unpredictable from its outputs by construction. So the
job is to write that null *well*, with the sample named, and to separate "we
found nothing" from "we could not have found anything".
[`rebuildpredict.py`](harness/rebuildpredict.py) is five rungs in increasing
ambition. **All five close negative. Two of them close negative with no power,
and saying which is the point of the section.**

**Rung 0, the budget, which decides what is possible at all.** A discretised
variate of standard deviation `s` lattice units carries about
`log2(s sqrt(2 pi e))` bits. Per tick:

| feed | sd in lattice units | **bits a tick** | ticks for a 48-bit LCG | 32-bit word? |
| --- | --- | --- | --- | --- |
| volatility_25_1s_index | 3,676 | **13.89** | 3.5 | no |
| volatility_50_1s_index | 2,015 | 13.02 | 3.7 | no |
| volatility_75_index | 893 | 11.85 | 4.1 | no |
| jump_50_index | 1,555 | 12.65 | 3.8 | no |
| boom_1000_index | 1,215 | 12.29 | 3.9 | no |
| range_break_100_index | 1.93 | **3.00** | 16.0 | no |
| step_index | 1.00 | **2.05** | 23.4 | no |

**Rung 2 is impossible on this data and is reported as untested rather than as a
pass.** Untempering MT19937 needs 624 consecutive *whole 32-bit words*; the
richest feed here shows 13.89 bits a tick. No amount of collection fixes that -
the quote grid throws the bits away before we see them - so a Mersenne Twister
behind these feeds would be invisible to this attack and that is arithmetic
rather than a result.

**Rung 1: k-tuple lattice structure, and its own control says it is weak.** The
empirical spectral test at k = 2, 3, 4 over 26 feeds. Nothing anywhere: the
largest ratio on any real feed is **2.28** (`range_break_100_index`, k = 4)
against numpy's PCG64 at 1.54 / 1.84 / 2.05 and a 3x bar. RANDU reads **2,910**
in three dimensions, so the test has resolution.

But a second control retires the claim this page previously made for it. **A
48-bit LCG truncated to its top ten bits - which is the realistic hypothesis -
reads 2.84 against PCG64's 1.54, inside the 3x bar.** Rung 1 catches a grossly
broken generator and misses a plausibly broken one. A clean rung 1 therefore does
**not** exclude the family rung 3 attacks, which is why rung 3 was run rather than
argued away.

**Rung 3: truncated-LCG recovery by lattice reduction, run rather than argued.**
LLL plus Babai nearest-plane against a catalogue of nine published parameter
sets. Two things make it mean something. The observed word is read off the
**exact** interval the quote pins the uniform to -
`Phi((k-0.5)g/s)` to `Phi((k+0.5)g/s)` - and a tick whose interval straddles a
bit boundary is discarded rather than guessed; a rank transform recovers a uniform
only to `O(1/sqrt(n))` and its leading bits are then wrong often enough to fail
the positive control, which would have been read as a clean feed. And the control
is run **per parameter set**, because the reduction's precision decides which
moduli are attackable at all.

| parameter set | modulus | outputs needed | **positive control recovered** |
| --- | --- | --- | --- |
| java.util.Random | 2^48 | 8 | **yes** |
| MMIX (Knuth) | 2^64 | 10 | **yes** (extended precision; double fails) |
| Numerical Recipes, Borland, MSVC | 2^32 | 6 | **yes** |
| glibc TYPE_0, MINSTD x2, RANDU | 2^31 | 6 | **yes** |

**Nine of nine parameter sets are recoverable from eight observed bits, and none
of them recovers a real feed.** Forty consecutive-valid windows per feed per
parameter set, on the three Volatility feeds carrying ten or more bits a tick:
`volatility_75_index`, `volatility_25_1s_index`, `volatility_50_1s_index`. **0
recoveries of 1,080 attempts.** The scope is exactly nine named generators and
one sampling convention: the attack assumes the venue draws **one** uniform a
tick and maps it through the inverse normal, and Box-Muller or a ziggurat breaks
that map. So this excludes nine published LCGs behind an inverse-CDF sampler, and
nothing wider.

**Rung 4: the joint stream, where the interesting thing is the control.**
`twins.md` found all sixteen synthetics publishing on one clock to within 9ms, so
if one generator serves them all, consecutive draws appear as *different feeds at
the same slot* and a cross-feed tuple is a k-tuple of that stream. Fifteen feeds
aligned on 46,757 common one-second slots.

* pairwise correlation of uniformised increments at the same slot: largest
  `|r| = 0.01095`, **0 of 105 pairs** outside `+-4/sqrt(n)`;
* cross-feed tuples read as one stream: lattice ratio 1.43 / 1.80 / 1.93 against
  PCG64's 1.54 / 1.84 / 2.05 - **below the control on all three**;
* two-dimensional grid chi-square: `p = 6.8e-64` on
  (`volatility_75_1s_index`, `volatility_100_1s_index`), and a sign contingency
  `p = 1.3e-31` on the two Range Breaks. **Both fire by an enormous margin.**

And both are the clock. Only 46,757 of 86,400 one-second slots survive an
intersection over fifteen feeds, so **46% of these aligned increments are sums of
two or more real increments - and which ones is shared by every feed, because the
mask is the intersection.** Run the identical two tests on **fifteen independent
PCG64 rebuilds sampled on the same slot lattice** and they report `p = 1.8e-65`
and `p = 6.0e-55`: *more* extreme than the feed, from fifteen generators with no
shared state whatever. `twins.md` measured the same artefact as a faked +0.19 in
`|return|` on a fixed grid; this is it again, at 64 decimal places. The
cross-feed result is a null and the p-value is a property of the mask.

**Rung 5: held-out forward prediction, and a control that changes two verdicts.**
Fit on the first 60% of the sample in *time*, predict the sign of the next tick
on the last 40%. (The first version of this harness split by interleaved blocks
of row index, which puts a test row between two training rows minutes away; it
read 0.4938 with an interval excluding 0.5, and that was the leak.)

| target | features | n | AUC | 95% CI | verdict |
| --- | --- | --- | --- | --- | --- |
| volatility_75_1s_index | own last 8 | 85,972 | 0.5043 | [0.4978, 0.5095] | null |
| *the same, PCG64 rebuild* | | 85,976 | *0.5003* | *[0.4945, 0.5068]* | |
| step_index | own last 8 | 86,384 | **0.5059** | [0.5001, 0.5119] | *excludes 0.5* |
| *the same, PCG64 rebuild* | | 199,991 | *0.5029* | *[0.4990, 0.5067]* | **same as rebuild** |
| range_break_100_index | own last 8 | 86,391 | **0.5161** | [0.5095, 0.5217] | *excludes 0.5* |
| *the same, PCG64 rebuild* | | 199,991 | *0.5162* | *[0.5123, 0.5200]* | **same as rebuild** |
| volatility_10_1s_index | all 15 feeds, same slot | 46,756 | 0.4956 | [0.4862, 0.5046] | null |
| **CONTROL: truncated LCG** | own last 8 | 299,991 | **0.4998** | [0.4965, 0.5032] | **missed** |

Two feeds have next-tick sign AUCs whose intervals exclude 0.5, and **neither is
about the generator**. Range Break is a bounded walk and a bounded walk
mean-reverts, so its next tick is partly predictable from its own past by
construction - the published mechanism, not a leak - and a PCG64-driven rebuild
of the same box scores **0.5162 against the feed's 0.5161**, agreeing to one part
in ten thousand. Step Index's 0.5059 against its rebuild's 0.5029 is the same
story an order of magnitude smaller. Without this control the first version of
this section reported the Range Break number as though it said something.

**And the last row is the power statement.** A feed synthesised from a
48-bit LCG - a generator that rung 3 breaks completely, in eight ticks, every
time - is predicted by this classifier at **0.4998 [0.4965, 0.5032]**. The
forward test **could not have found an LCG if one were there.** A gradient-boosted
ensemble on eight lagged increments is not an instrument for recovering modular
arithmetic, and its null is therefore evidence about *tradeable smooth
structure* - which is what a desk would exploit - and no evidence at all about
the soundness of the source.

**What this closes, and at what strength.**

| rung | verdict | had the power? |
| --- | --- | --- |
| 1, k-tuple lattice | null, largest ratio 2.28 against a 3x bar | **partly** - catches RANDU at 2,910x, **misses a truncated LCG at 2.84** |
| 2, MT19937 untempering | **untested** | **no** - needs 32-bit words, the richest feed shows 13.89 bits |
| 3, truncated-LCG lattice recovery | null, **0 of 1,080** attempts | **yes** - 9 of 9 positive controls recovered |
| 4, joint sixteen-feed stream | null; the two firings are the shared slot mask | **yes** - independent rebuilds on the same mask fire harder |
| 5, held-out forward prediction | null; two AUCs past 0.5 are both matched by a PCG64 rebuild | **for smooth structure yes, for an RNG no** - the LCG control reads 0.4998 |

So: **nothing in this battery predicts the next tick, the one route that had real
power against a broken generator found nothing in 1,080 attempts, and the route
with the most commercial relevance has no power against an RNG at all.** The
generated half of the book does not pay by prediction. That was the prior and it
is now a measurement with its scope written down.

One thing this section deliberately does not do. If a rung had bitten it would be
a finding about the product and about counterparty risk, not a trading rule:
every set of terms permits voiding trades made against a defective generator, a
venue whose generator is predictable will discover it, and a position built on
one is not bankable. The write-up would be the deliverable and the decision the
desk's.

### A hundred and three published numbers, regenerated from the parameters alone

[`rebuildpaper.py`](harness/rebuildpaper.py) is the whole of what can be done
without the lab. `deriving.md`, `generators.md` and `twins.md` between them state
about a hundred numbers measured off the real feeds, and every one of them is a
number a correct simulator has to produce. None of them is an input to the
rebuild, and all of them were measured before it existed.

**103 comparisons, eleven fired**, at 400,000 bars a cell over three seeds - and
six of the eleven are one finding counted six times.
That is weaker than a two-sample test - it compares two summaries rather than two
distributions, and it can only catch an error large enough to move a summary -
and it is not nothing.

**What passed.** The barrier table is the sharpest of them, because the rebuild
was never told about the 0.5826 constant and the textbook closed form is wrong:

| a:b | measured on the feed | **rebuilt** | continuous | corrected | E[tau] measured | **rebuilt** | continuous |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1:1 | 0.5000 | **0.5007** | 0.5000 | 0.5000 | 2.782 | **2.784** | 1.000 |
| 5:5 | 0.5008 | **0.5014** | 0.5000 | 0.5000 | 31.279 | **31.431** | 25.000 |
| 3:1 | 0.3073 | **0.3082** | 0.2500 | 0.3064 | 5.942 | **5.961** | 3.000 |
| 9:1 | 0.1426 | **0.1430** | 0.1000 | 0.1417 | 15.382 | **15.423** | 9.000 |
| 2:10 | 0.8042 | **0.8049** | 0.8333 | 0.8038 | 27.472 | **27.543** | 20.000 |

Eight geometries, 430,975 replayed trades at the tightest: `P(up)` lands within
**+0.0004 to +0.0012** of the feed's own measurement and `E[tau]` within
**0.09% to 0.49%**, where the continuous form misses `P(up)` by 0.057 and
`E[tau]` by 50-178%. `E[max]` and `E[range]` over 5, 15, 60 and 240 minutes land
within **1.04%** and **0.30%**; the occupation-time deciles within **0.004** of
the feed's; realised volatility within **0.04%** of the name; kurtosis inside
2.98-3.02; Hurst 0.4998; the Parkinson ratios at **0.014%** and **0.10%** of
0.870 and 0.909. Step Index reproduces its gambler's-ruin hit rates to within
**0.79 standard errors** at all six geometries and both fill conventions - the
one-step-past numbers 0.3536, 0.2732 and 0.1874 come back to 1.5%. The twins
carry the `sqrt(2)` per-tick ratio to **0.03%** and identical volatility per
second to **0.06%**. And Boom's five published numbers reproduce `genstop.py`'s
**+13.96R, +6.81R, +2.44R and +1.02R** stop slippage at -8.5%, -16.2%, -18.7%
and -4.6%, from a path that was never shown them.

**What failed, and the big one is a correction to `deriving.md` rather than to
the rebuild.** `deriving.md` section five states, per feed, `lambda`, `E[g]` and
`E[J]`, and its own theorem says `E[J] = lambda * E[g]`. The published numbers do
not satisfy it:

| feed | lambda x E[g] / E[J] | closure z, 3M ticks | with `E[J] := lambda*E[g]` |
| --- | --- | --- | --- |
| boom_300_index | 0.9399 | **-6.70** | +0.22 |
| boom_500_index | 1.0812 | **+5.65** | +2.13 |
| boom_1000_index | 0.9374 | **-2.87** | -0.21 |
| crash_300_index | 1.0848 | **+5.79** | +2.16 |
| crash_500_index | 1.1182 | **+7.55** | +2.39 |
| crash_1000_index | 1.0388 | **+2.92** | +0.95 |

Six for six outside 2%, by **6% to 12%**. Each number is individually fine - the
feed's own 24 hours cannot resolve the product to better than that, and
`deriving.md` says as much when it reports `E[J]/E[g]` at 489.6 against a lambda
of 529.4. But a rebuild at thirty-five times that sample sees the residual drift
immediately, and a compound Poisson built from both published means is **not a
martingale**. Replace `E[J]` by `lambda * E[g]` and every feed comes back inside
2.4 standard errors. That is a one-line amendment to the specification with a
real consequence: anyone simulating Boom or Crash from the published table gets a
drift, and the whole `E[net] = -c` theorem assumes there is none.

**The other failure is the jump's lower tail.** A lognormal matched to `E[J]` and
`median J` - which is exactly what `deriving.md` publishes - has almost no small
jumps, and `P(J > D)` comes out 1.000, 0.999, 0.919 and 0.607 against the
measured 0.963, 0.888, 0.763 and 0.531. Three of four outside 0.05. Two moments
do not pin a tail, and the quantity that depends on it - how often a stop is
gapped straight through - is exactly the one `deriving.md` section five uses for
sizing. **The quantiles of `J` need publishing, not just its mean and median.**

The remaining two are small: Step Index's `E[tau]` at a 50:5 barrier is 7.6% off
a published figure that was itself 6.9% off the theory on 323 trades, and one
occupation decile is 0.0105 from the arcsine law against a bar of 0.01 - where
the feed's own measurement is 0.0147 off in the same direction.

**The negative controls behaved.** A generator with sigma 2% wrong fails the
volatility condition and passes the Parkinson one; one at half the publication
rate passes the volatility condition and fails the Parkinson one. The battery
separates a scale error from a rate error, which is the only way to read a pass
on either.


### Two results about the real instrument that go through published numbers

**The 0.5826 correction emerges from the rebuild rather than being put into it.**
Nothing in `rebuildgen.py` mentions the Broadie-Glasserman-Kou constant. Simulate
ticks at the name's volatility, aggregate them into one-minute bars, and read the
barrier statistics off the bars:

| a:b | continuous closed form | **BGK-corrected** | off the rebuilt bars |
| --- | --- | --- | --- |
| P(up), 3:1 | 0.2500 | **0.3064** | **0.3131** |
| E[tau], 5:5 | 25.0 min | **31.165 min** | **31.62 min** |
| E[tau], 2:10 | 20.0 min | **27.331 min** | **27.20 min** |

and the Parkinson-to-close ratio, which `generators.md` measured at **0.870** on
the two-second family and **0.909** on the one-second family and could not
explain, comes out of a rebuild that was given only a volatility and a tick rate
at **0.8703** and **0.9092**. The discreteness is a property of the
tick-and-aggregate construction, not a patch applied to it.

### Range Break: the range rule, chosen by the data and still not right

This is the family `deriving.md` said outright it could not derive - "the actual
range rule - how wide, how it resets, what counts as a bounce - is unknown" - and
it is the one place where a rebuild can say something the derivation could not.
The published variance-ratio table *is* the measurement, so the three candidate
re-range rules can be scored against it directly without touching the database.
Each rule gets a scan over the two parameters the specification does not contain:
the range width and the size of the break jump.

**Range Break 100**, ex-break variance ratio, against `deriving.md` section four:

| | n=1 | n=5 | n=20 | n=100 | n=500 | n=1000 | MAE | all-bars flatness |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **published** | 0.978 | 0.730 | 0.436 | 0.283 | 0.274 | 0.279 | | **1.118** |
| `edge`, band 60, J 120 | 0.928 | 0.773 | 0.544 | 0.310 | 0.259 | 0.262 | **0.0433** | 1.250 |
| `edge_far`, band 60, J 160 | 0.956 | 0.790 | 0.532 | 0.309 | 0.230 | 0.188 | 0.0565 | 1.444 |
| `centre`, band 110, J 140 | 1.021 | 0.943 | 0.772 | 0.467 | 0.342 | 0.240 | 0.1472 | 1.166 |

**Range Break 200**:

| | n=1 | n=5 | n=20 | n=100 | n=500 | n=1000 | MAE | all-bars flatness |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **published** | 0.930 | 0.750 | 0.477 | 0.192 | 0.116 | 0.112 | | **1.143** |
| `edge`, band 45, J 230 | 0.887 | 0.662 | 0.367 | 0.183 | 0.135 | 0.148 | **0.0508** | 1.169 |
| `edge_far`, band 60, J 230 | 0.921 | 0.753 | 0.482 | 0.218 | 0.142 | 0.127 | 0.0141 | 1.698 |
| `centre`, band 110, J 230 | 0.998 | 0.904 | 0.738 | 0.385 | 0.182 | 0.171 | 0.1337 | 1.315 |

Four things fall out of that, and the last one is the finding.

**The centred rule is refuted on both feeds**, by a factor of three on mean
absolute error. It fails for a reason worth writing down: to carry the plateau at
`n >= 100` a centred range needs a band of about 110 steps, and a band that wide
relaxes in roughly 3,500 ticks against a 5,190-tick break interval, so it cannot
also be confined at twenty minutes. Anchoring the new range **on** the break point
quadruples the displacement a price accumulates inside a range at the same width,
which lets the band be half as wide and relax three times faster. That is a real
constraint on the mechanism, derived from two numbers in a published table.

**The sub-diffusion and the flat total are both reproducible.** A bounded walk
plus a memoryless break gets the ex-break curve from 0.978 down to 0.262 across
three orders of magnitude in horizon with a mean absolute error of **0.043**,
while keeping the all-bars ratio flat to **1.25** against a published 1.118. The
qualitative claim in `deriving.md` section four - the range is real, and the break
pays for it - re-instantiates.

**But the crossover does not.** The residual is not scattered; it sits at
`n = 20`, where the rebuild reads **+0.108** too high on RB100 and **-0.110** too
low on RB200. The real ranges confine on a timescale a uniform reflecting band
does not reproduce, and the two indices miss in opposite directions, which rules
out a single width correction.

**And the two rules that fit best disagree about what the parameters are.** The
fitted band is 60 steps on RB100 and 45 on RB200, and the fitted jump 120 against
230 - so under this mechanism the two indices do not share one range. That is not
what a family with one generator and a rate parameter should look like. The next
section shows it is also not true: the widths were absorbing a shape error and
one shared width fits both feeds better than two free ones.

### The twenty-minute residual, chased

That residual is the most specific unexplained thing on the page, so it is worth
three experiments. All three need only the published table.

**First, what twenty minutes is.** A variance ratio hides the shape; written as
`Var(T)` the confinement is a dip in the local log-log slope, where 1.0 is free
diffusion and 0.0 is a hard box:

| T (ticks) | T (min) | RB100 `Var(T)` | slope | RB200 `Var(T)` | slope |
| --- | --- | --- | --- | --- | --- |
| 60 | 1 | 58.7 | | 55.8 | |
| 300 | 5 | 219.0 | 0.818 | 225.0 | 0.866 |
| 1,200 | 20 | 523.2 | **0.628** | 572.4 | 0.674 |
| 6,000 | 100 | 1,698.0 | 0.731 | 1,152.0 | **0.435** |
| 30,000 | 500 | 8,220.0 | 0.980 | 3,480.0 | 0.687 |
| 60,000 | 1,000 | 16,740.0 | 1.026 | 6,720.0 | 0.949 |

The dip bottoms at **600 ticks (10 minutes)** on RB100 and **2,700 ticks (45
minutes)** on RB200, and it is deeper on RB200 - 0.435 against 0.628. Both
recover to free diffusion at the longest horizons, which is the price hopping
between ranges. A reflecting box of width `L` relaxes on its slowest eigenmode in

    tau_1 = 2 L^2 / pi^2

and at the width that carries the plateau - 60 steps - that is **729 ticks, or
12.2 minutes**. The residual peaks one cell later, at twenty minutes, which is
**1.6 tau_1**. So twenty minutes is not an arbitrary scale: it is the box's own
fundamental relaxation time, and the residual is the rebuild getting the *shape*
of that relaxation wrong rather than its position.

**Second, why the sign flipped - and it stops flipping.** The free per-feed fit
put the widths at 60 and 45, which is backwards: RB200 holds its range twice as
long and its dip is deeper and later, so if anything its range is *wider*. A
product family with one generator and a rate parameter should share a width, so
force it - one width for both indices, only the break jump free per feed:

| shared width | tau_1 (min) | joint MAE | RB100 J / MAE | RB200 J / MAE |
| --- | --- | --- | --- | --- |
| 50 | 8.4 | 0.0603 | 130 / 0.0825 | 210 / 0.0380 |
| 55 | 10.2 | 0.0416 | 130 / 0.0565 | 210 / 0.0267 |
| **60** | **12.2** | **0.0363** | 130 / 0.0427 | 210 / 0.0299 |
| 66 | 14.7 | 0.0475 | 130 / 0.0448 | 210 / 0.0501 |
| 72 | 17.5 | 0.0650 | 110 / 0.0554 | 210 / 0.0747 |
| 80 | 21.6 | 0.0897 | 110 / 0.0700 | 210 / 0.1094 |

**The constraint is free, and it is better than free.** A single shared width of
60 steps scores a joint mean absolute error of **0.0363**, against **0.047** for
the unconstrained per-feed fits - fewer parameters and a closer fit. And the sign
flip goes with it: at twenty minutes the residuals become **+0.047** and
**+0.024**, the same sign on both indices. The opposite-direction residual was
never a property of the instrument; it was two widths absorbing one shape error
in opposite directions.

So the specification gains a number it did not have: **Range Break 100 and 200
share one range, about 60 steps wide, and differ only in how often they break and
how far the break carries**

> **This is wrong and the correction is below.** A direct measurement on the feed
> puts RB100 at about 39 units and RB200 above 60, and the estimator that says so
> was checked against a known truth first. The shared width is withdrawn - see
> *The shared width of 60 is refuted*. - 130 steps against 210. The break rate and the break
size scale together, the range does not.

**The box, written out, so another route can check it.** The mechanism this
reduces to is a particle in a one-dimensional box, and every number in it is
fixed by the fit above. *Read it as the hard box that best fits a published curve
it cannot match rather than as the instrument: the width is refuted below, and
the eigenvalue ladder measured on the feed says the range is not a box at all.*

* width **L = 60 steps**, the same for Range Break 100 and Range Break 200;
* diffusion **D = 1/2 step^2 per tick** - the walk moves exactly one step a tick,
  so `D = sigma^2/2` with `sigma = 1`;
* the box is **reflecting** at both ends and re-anchored at the break point, so a
  new range opens with the price at one edge;
* eigenvalues `lambda_k = k^2 pi^2 D / L^2`, hence relaxation times
  `tau_k = 2L^2 / (k^2 pi^2)` = **730, 182, 81, 46 ticks** for k = 1, 2, 3, 4, which in
  minutes is **12.16, 3.04, 1.35, 0.76**;
* stationary spread `L / sqrt(12)` = **17.3 steps**, and displacement variance
  accumulated inside one range `L^2/3` = **1,200 step^2** because the price
  starts at an edge rather than at the centre;
* breaks arrive memorylessly every **5,196 ticks** (RB100) and **10,734**
  (RB200), carrying **130** and **210** steps.

Anything deriving the same instrument as a box should land on the same `L` and
the same `tau_1`; if it lands somewhere else, one of the two routes is wrong and
the disagreement is more informative than either result alone.

**Third, the one addition that could have fixed it, and does not.** A single box
cannot have a deep dip early *and* a high plateau late, because the plateau needs
a wide box and a wide box relaxes slowly. The obvious escape is a second, quieter
re-range - the range moving to where the price already is, with no jump - which
would let the box be narrow while the price still diffuses between centres, and
which is the only such addition that leaves every tick at exactly one unit. It
was built and scanned and it is **refuted**:

| quiet re-range every | RB100 MAE | RB200 MAE |
| --- | --- | --- |
| **never** | **0.0493** | **0.0369** |
| 4,000 ticks | 0.0941 | 0.1569 |
| 2,000 ticks | 0.2335 | 0.2418 |
| 1,000 ticks | 0.2826 | 0.3703 |
| 500 ticks | 0.4132 | 0.4831 |

Monotone, on both feeds, in the wrong direction. There is no second re-range
event.

**Fourth, the soft edge - which is what the residual looks like, and which does
not fix it either.** Under the shared width the residual is no longer a sign flip
but a shape: the rebuild is **too confined at one minute** (-0.086 and -0.018)
and **too free at twenty** (+0.047 and +0.024). That is what a hard wall looks
like against something smoother - a reflecting barrier bites the moment the price
is near it and then relaxes on a single slow mode, where a graded restoring force
does less at short range and more at the scale of its own relaxation. So the
wall was softened: a lattice walk whose up-probability is
`0.5 - k (|x|/half)^q sign(x)`, which is a reflecting box as `q -> inf` and a
harmonic well at `q = 1`, scanned over `q` in {1, 2, 4, 12}, `k` in {0.25, 0.5}
and the width. The bias is state-dependent so the folding trick that makes the
hard box cheap does not apply; `gen_softbox` steps two hundred independent range
interiors at once instead, which turns a loop over fifty million ticks into a
loop over one range's length with a vector inside it.

It buys shape and pays for it in flatness:

| mechanism | RB100 MAE | RB100 flatness | RB200 MAE | RB200 flatness |
| --- | --- | --- | --- | --- |
| **published** | | **1.118** | | **1.143** |
| hard box, shared width 60 | 0.0427 | 1.266 | 0.0299 | 1.109 |
| soft edge, best (width 72, k 0.25, q 4) | **0.0356** | 1.509 | **0.0282** | 1.407 |

The soft-edge row is its *best ex-break fit* rather than its best overall, which
is the strongest case that can be made for it - the configuration the scan ranks
first on the combined score does worse on both.

Twelve percent better on the ex-break curve and a third worse on the all-bars
one, on both feeds. (The soft-edge scan runs at 40,000 bars against the shared-
width scan's 100,000, so its mean absolute errors carry more Monte Carlo noise
than the hard-box ones; the flatness gap is far too large to be that.) The best
soft-edge width is 72 on both feeds, which is the shared-width result again from
a different mechanism - so that finding survives the change - but the edge itself
is not the missing piece.

**What the residual actually is.** Stated at the end of four experiments, the gap
is not a timescale and not an event: it is that **no single confinement matches
the ex-break shape and the all-bars flatness at once** - and, as the next section
records, the two constraints may not have been one another's business in the
first place. Harden the wall and the
total variance flattens while the crossover goes too gentle; soften it and the
crossover sharpens while the total variance stops being flat. `deriving.md`
section four's two headline facts - sub-diffusive between breaks, flat across
three orders of magnitude - are, under every mechanism tried here, in tension at
the 10-30% level. Something in Range Break couples the break to the range in a
way none of these four candidates does.

### The same width from a completely different direction

[quantising.md](quantising.md) attacks the same instrument as a quantum-mechanics
problem - Wick-rotate the heat equation, read the confinement as a potential well
and the relaxation as an eigenvalue ladder - and inverts `deriving.md`'s published
curve for the box it implies. It uses only the two shortest lags and gets a range
width of **49 units on RB100 and 56 on RB200**, with a fundamental relaxation
time of 6.3 and 8.8 bars.

This page gets **60 steps shared** and `tau_1` = 12.2 minutes by fitting all six
lags of a variance-ratio curve. Two routes, no shared machinery beyond the
published table, and they land within 10-20% of each other on the width and
within a factor of 1.5 on the relaxation time. They also agree on the thing that
matters more: **the two indices have nearly the same range**, which is what the
shared-width constraint here asserts and what their independent per-feed
inversion produces without being asked to.

> **Both halves of that agreement have since been withdrawn.** That page's own
> direct tick measurement supersedes its inversion and puts RB100 at 38 and RB200
> above 60 - a factor of at least 1.6 apart, so the ranges are not nearly the
> same - and the section below refutes the 60 here. Two routes agreeing on a
> number that a third and more direct route refutes is worth recording as such:
> both were inversions of the *same published curve*, and a shared input is not
> independent evidence.

And their page makes a methodological point this one had better take. **The
long-lag cells are the splice, not the process.** Dropping break bars and
concatenating what is left glues independent episodes end to end, and glued
episodes diffuse - so the flatness at `n` = 100 to 1000 is a property of the
stitching rule, and only the short lags carry the confinement. That is right, and
it cuts at the scoring used above, which weights all six lags equally.

It does not move the answer, and that turns out to be a symptom rather than a
reassurance: the section below shows the scan cannot separate 52 from 60 at all.
Rescored on `n = 1` and `n = 5` alone - the only
cells where under 6% of pairs can straddle a break - the best shared width is
**still 60**, with 55 next:

| shared width | 40 | 45 | 50 | 55 | **60** | 66 | 72 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| joint \|error\| on the short lags | 0.1013 | 0.0649 | 0.0400 | 0.0307 | **0.0253** | 0.0341 | 0.0397 |

But it does reframe the impasse. The tension this page ends on - no single
confinement matching the ex-break shape and the all-bars flatness at once - is
partly a tension between a statement about the **range** and a statement about the
**break and the stitching rule**, which were never obliged to be satisfied by one
mechanism. The instrument that separates them is a transfer operator measured
strictly *inside* an episode, which is what that page builds and this one does
not.

**So `deriving.md` is not complete enough to re-instantiate Range Break.** One
parameter has to be supplied from outside the specification - a shared range
width of about 60 steps - plus a per-feed break size, and even then a structured
residual remains at the box's own relaxation time. That is a sharper statement of
the gap than "the mechanism is not published", and it is three falsifiable
claims: one shared width, no second re-range event, and a soft edge.

### The shared width of 60 is refuted, and the estimator that refutes it was tested first

[quantising.md](quantising.md) now measures Range Break's range **directly off
the feed** - `W = sqrt(12 Var)` on within-episode ticks, de-meaned per episode,
scanned against a minimum episode length - and reads **RB100 at about 38 units**,
flat to 2% across its last three cuts, with `RB200 above 60 and not converged`.
This page fitted a simulated variance-ratio curve to `deriving.md`'s published
table and got **one shared 60**. Those cannot both be right.

Neither page had run the thing that settles it, so
[`rebuildwidth.py`](harness/rebuildwidth.py) does: **give both estimators the
same simulated truth, at the feed's own sample, and see which one comes back with
the width it was given.** Six paths a width, Range Break 100 at the published
86.6-minute break rate, episodes cut at the true break points.

**First, the two defects that moved `quantising.md`'s own numbers, checked
here.** That page found an episode filter sized by its longest window and applied
to everything, which discarded nine tenths of its episodes; and the same filter
applied to the data but not to the simulated truths. Neither is present in the
scoring on this page, and the reason is structural rather than lucky. There is no
episode filter at all - the variance-ratio curve is computed over every bar - and
the estimator is one function, `rebuildstep.vr_curves`, run on the simulation and
on the feed alike, which is why `rebuildgen.py` holds the battery rather than
each study holding its own. So the fit is not defended by those two corrections
and is not damaged by them: it fails for a different reason, below.

**The direct estimator is biased low, and nowhere near enough to save 60.**

| true `W` | episodes | saturating cut | **`W` recovered** | mean within-episode range | bias |
| --- | --- | --- | --- | --- | --- |
| 30 | 17.5 | 5,461 | **29.5 +- 0.7** | 30.0 | -1.7% |
| 38 | 19.0 | 4,096 | **36.6 +- 0.7** | 38.0 | -3.8% |
| 45 | 17.0 | 4,779 | **43.6 +- 1.3** | 44.9 | -3.2% |
| 52 | 17.2 | 4,096 | **48.9 +- 0.7** | 51.0 | -6.0% |
| **60** | 20.2 | 4,096 | **53.1 +- 2.4** | 57.7 | **-11.5%** |
| 72 | 18.7 | 5,461 | **63.8 +- 4.2** | 70.0 | -11.4% |

The bias is real and it grows with the width, exactly as a finite episode should
make it - a wider box needs longer to equilibrate and an episode of about 5,000
ticks is fewer relaxation times of a wide box than of a narrow one. At twenty
times the sample it falls to -0.1% to -4.0%, which is what says it is a
finite-episode bias rather than a defect in the estimator.

**But a true 60 reads 53.1, not 38.** The feed reads 37.8. That is **6.3 standard
deviations** from what a true 60 produces under the same estimator at the same
sample, and a true 38 reads 36.6 +- 0.7, which is what the feed shows. Corrected
for its own -3.8% bias, the feed's number is a range of about **39 to 40 units on
RB100**. The shared width of 60 on this page is **refuted**, and the escape that
would have saved it - that the estimator is biased low by a third - does not
exist.

**And the curve this page fitted does not identify a width at all.** Scored the
way this page ends on - the two short lags, after `quantising.md` showed the long
ones are the splice rather than the process - the best hard box is **52**, with 60
next and separated by **0.7 Monte Carlo standard deviations**. A best-fit quoted
as "about 60" from a scan whose neighbours are within one standard deviation was
quoting a precision the estimator never had.

| hard box `W` | `n=1` | `n=5` | `n=20` | `n=100` | MAE, all six | **MAE, short lags** |
| --- | --- | --- | --- | --- | --- | --- |
| **published** | **0.978** | **0.730** | **0.436** | **0.283** | | |
| 30 | 0.780 | 0.474 | 0.215 | 0.124 | 0.1937 | 0.2270 +- 0.0273 |
| 38 | 0.836 | 0.590 | 0.294 | 0.160 | 0.1461 | 0.1408 +- 0.0247 |
| 45 | 0.874 | 0.650 | 0.371 | 0.210 | 0.0961 | 0.0916 +- 0.0228 |
| **52** | 0.902 | 0.720 | 0.461 | 0.250 | **0.0522** | **0.0453 +- 0.0178** |
| 60 | 0.914 | 0.768 | 0.529 | 0.312 | 0.0618 | 0.0569 +- 0.0059 |
| 72 | 0.926 | 0.797 | 0.583 | 0.360 | 0.0776 | 0.0591 +- 0.0058 |

**Read the `n=1` column and the fit stops being a measurement.** The published
one-bar ex-break variance ratio is **0.978 +- 0.007**, which is a series barely
confined at a one-minute horizon - and *every* hard box undershoots it, rising
monotonically through 0.780, 0.836, 0.874, 0.902, 0.914, 0.926 and never
arriving. No box in the scan reaches it and no wider one would arrive in time,
because a box that free at one minute is not a box at twenty. So the scan's
preferred width is the width that minimises an error dominated by **a cell no
hard box can reach**, and pushing it wider is the fit trying to escape
confinement rather than measure it. That is why the curve says 52-to-72 where the
feed says 39.

**The correction, stated plainly.** Range Break 100's range is about **39 units**,
measured on the feed at tick resolution and corrected for a bias measured on a
known truth. This page's **60 is withdrawn**, and so is the claim that the two
indices share one width - `quantising.md` gets RB100 at 38 and RB200 above 60 and
not converged, which is a factor of at least 1.6 between them. What survives from
the shared-width experiment is only the negative half of it: the free per-feed fit
at 60 and 45 had RB200 *narrower* than RB100, which is backwards, and the
direct measurement agrees that it is backwards.

**A caveat that bears on anyone repeating either measurement.** Cutting episodes
at *bar* granularity inflates the direct estimate by **24% to 42%**:

| true `W` | 30 | 38 | 45 | 52 | 60 | 72 |
| --- | --- | --- | --- | --- | --- | --- |
| `W` from true break ticks | 29.5 | 36.6 | 43.6 | 48.9 | 53.1 | 63.8 |
| `W` from `break_bars` on one-minute bars | 41.1 | 47.0 | 61.3 | 57.8 | 75.6 | 85.1 |

A bar detector can only see a break after it has been mixed with a minute of
ordinary movement, so the episode boundary lands up to sixty ticks late and the
de-meaned episode spans two ranges. Neither page's width is affected - both cut
at tick resolution, where a move over five units is a break and nothing else is -
but `rebuildstep.py`'s `break_bars` is a bar detector and it is used here for the
break *rate*, where a sixty-tick error is irrelevant. Anything that fed it into a
width would be 30% out.

**And the soft edge's own prediction is refuted, in the direction neither page
had a row for.** This page and `quantising.md` jointly pre-registered that if the
range's edge is softer than a wall then `lambda_2/lambda_1` must land **strictly
between 2 and 4**. Measured against simulated truths through the identical
pipeline it is **2.076 on RB100 and 1.976 on RB200** - at or below the harmonic
value, so not a hard box, not a soft wall, and not even a spring. The soft-edge
scan on this page searched from the harmonic upward and the answer is at the
other end of it. Kill condition fired; the soft-edge reading of the twenty-minute
residual is withdrawn along with the width.

**What is left of this page's Range Break section is the part that never depended
on the width**: that a bounded walk plus a memoryless break reproduces the
sub-diffusion and the flat total at the 10-30% level and not better, that a
second quiet re-range is refuted monotonically on both feeds, and that
`deriving.md` is not complete enough to re-instantiate Range Break. The box
written out below - `L = 60`, `tau_1 = 12.16` minutes, stationary spread 17.3 -
should be read as the hard box that best fits a published curve it cannot match,
not as the instrument. At `L = 39` the same arithmetic gives `tau_1 = 308` ticks
or **5.1 minutes** and a stationary spread of **11.3 steps**, and those are the
numbers a further experiment should be pointed at.

## What was still to run - the pre-registration, and which rows came back

```bash
./.secrets/lab.sh run research/harness/rebuildall.py
```

**This has now run**, along with [`rebuildladder.py`](harness/rebuildladder.py),
[`rebuildwidth.py`](harness/rebuildwidth.py) and
[`rebuildpredict.py`](harness/rebuildpredict.py). The table below is left exactly
as it was written before any of it, because the point of writing it down was that
the interpretation be fixed before the numbers existed. What came back:

* **the Volatility family** landed on the first row - two numbers per instrument
  re-instantiate the feed - but only on the seven feeds whose quote grid is fine
  enough to tell, and only after the quantiser was corrected twice;
* **KS rejected on more than 3 of 12 tick arms**, which the table calls "a
  distributional defect a moment test cannot see". It was not: it was the
  repeated quote, and the univariate feature map named it;
* **`rebuildjudge`'s arms are above the floor on the pooled Volatility class**,
  which the table says makes the univariate AUC table a map of what the
  specification is missing. That is what it turned out to be, three times over;
* **the randomness battery does not flag the venue's stream**, and the two cells
  it does flag on the pooled class are the coarse feeds' rounding;
* **`rebuildpower`'s `n*` is not above the real sample on every family** - Boom
  and Crash separate in under a minute of ticks - so the honest headline is a
  table rather than a single bound;
* **the null controls did not reject above 5%**, so the `n*` table stands.

Each row below is a thing that could have happened and what it would have meant;
none of them was a thing I would have liked to happen.

| what comes back | what it means |
| --- | --- |
| **Volatility**: realised vol within 0.5% on 12 of 12, kurtosis inside 3.00 +- 3 SE, Hurst inside 0.50 +- 0.01, Parkinson inside 1%, KS rejecting on 3 or fewer | two numbers per instrument re-instantiate the feed. `deriving.md` is complete for this family and the twelve indices can be replaced by a simulator wherever a longer sample is wanted |
| the same but **Parkinson misses while volatility passes** | the law is right and the publication rate is not. The venue's bars are not built from 30 and 60 ticks, and every discrete-monitoring number in `deriving.md` moves with it |
| **KS rejects on more than 3 of 12** | a distributional defect a moment test cannot see. The per-feed `D` and the univariate feature AUCs in `rebuildjudge.py` say where, and the honest headline becomes an `n*` rather than a pass |
| **Jump**: spec A realises 1.322x and spec B does not | `generators.md`'s reading is right - the name is the diffusion and the jumps are extra - and the conditional in `deriving.md` section six is priced against the correct process |
| both readings realise 1.322x but their **kurtosis differs and only one matches** | the multiplier does not identify the generator and the rate does. Worth saying, because the barrier-product arithmetic in `deriving.md` section six depends on which |
| **Step**: concentration, coin, sign ACF, runs and gambler's ruin all pass | four numbers re-instantiate the instrument exactly, which is the cleanest closure available on this book |
| **Boom/Crash**: `spec` (five published numbers) passes and `pool` (empirical marginals) does no better | the published table re-instantiates the family and the sizing arithmetic can be computed for any stop width without re-running anything |
| **`pool` passes and `spec` does not** | the mechanism is right and two moments do not pin the jump. `deriving.md` section five would need the quantiles of `J` published, not just its mean and median - and its own caveat about 86 to 306 spikes would become the binding constraint |
| **the closure fails at the feed's own resolution on more than one feed** | the martingale claim is wrong somewhere, and since `deriving.md`'s whole theorem rests on it, that is the most expensive single outcome on this list |
| **`rebuildjudge`**: every arm at or below the feed-against-itself floor | nothing available here tells the rebuild from the feed. That is the strongest statement the data can support and it is still only a statement about this battery at this sample size |
| **an arm above the floor** | the univariate AUC table is a map of what the specification is missing, and it is more useful than a pass. The three arms separate the kinds: raw tuples read the joint law, windows read dependence, bar OHLC reads the tick rate |
| **the randomness battery flags the venue's stream where PCG64 is clean** | a finding about the product rather than about a trade - counterparty risk, not an edge - and it gets written up as that. The lattice test is the one with teeth: it caught RANDU at 2,616x here |
| **`rebuildpower`**: `n*` above the real sample on every family | "indistinguishable at 86,410 bars, separable above `n`" is the answer, and the bound is the result rather than a hedge |
| **the null controls reject above 5%** | the whole `n*` table is void and nothing in it is reportable |

## What this page does not say

* **Nothing here is a two-sample test against the feed.** Everything above is
  either apparatus calibrated on ground truth, or a comparison against a number
  `deriving.md`, `generators.md` or `twins.md` already published. A published
  summary can only catch an error large enough to move that summary, and it
  cannot see the ordering of the increments at all - which is precisely what the
  discriminator was built for and precisely what has not run.
* **The two corrections are corrections to a *specification*, not to a
  measurement.** The closure failure says the three published Boom parameters
  are mutually inconsistent at the 6-12% level, not that `deriving.md` measured
  any of them wrongly; its own text puts `E[J]/E[g]` at 489.6 against a lambda
  of 529.4 and does not remark on it. The jump-tail failure says two moments do
  not determine a tail, which is arithmetic.
* **A rebuild that survives is not a proof of identity.** It is a statement that
  nothing in this battery, at this sample size, separates the two - which is
  exactly why the headline is `n*` and not a pass mark.
* **The randomness battery is small.** A million uniforms is four orders of
  magnitude short of TestU01's SmallCrush. It excludes a grossly broken source
  and certifies nothing.
* **The Range Break scan is a scan, not a derivation.** The shared width was
  chosen by minimising a distance to a published curve over a six-point grid, and
  the grid's resolution - 5 steps - is the precision of "about 60". The residual
  at twenty minutes is evidence the mechanism is wrong in a specific way; the
  soft-edge reading of it is an interpretation and is marked as one.
* **The Range Break comparison is against six numbers a feed**, which is a
  coarser target than the raw rows. When the lab returns, `rebuildstep.py`
  re-estimates the width from the feed's own visited ranges and scores the curve
  against a twelve-seed Monte Carlo null instead of against a printed table.
* **`deriving.md`'s own Range Break numbers carry noise this page treats as
  exact.** The n=1000 variance ratio is 86 non-overlapping windows on a
  jump-heavy process; its standard error is at least 15%, and the fits here are
  quoted to three decimals against it.
* **The lattice ladder settles what the *observation* is, not what the venue
  does.** `research.db` never stores a repeated quote, so no rule this page can
  test distinguishes a venue that rounds a continuous price from one that moves
  on its grid. The rebuild matches the observation; the generator's own quantiser
  is unobservable from here and would need a tick feed that carries unchanged
  quotes.
* **The `n*` figures hold the AUC gap fixed as the sample grows, and it widens.**
  Every finite figure is an upper bound on the separating sample for *this*
  classifier and this feature set, and every `inf` means "not separable by this
  battery", which is not identity.
* **The prediction ladder excludes nine named generators and one sampling
  convention.** Rung 3 assumes the venue draws one uniform a tick and maps it
  through the inverse normal; Box-Muller or a ziggurat breaks that map and the
  rung then says nothing. Rung 2 is arithmetically impossible on a quantised
  quote and is untested rather than passed.
* **The width recovery is a Monte Carlo on one mechanism.** `rebuildwidth.py`
  tests both estimators against an edge-anchored *hard box*, which is the model
  `quantising.md`'s eigenvalue ladder refutes. It is enough to show that the
  direct estimator recovers a width it is given and that the curve does not
  identify one, and it is not a measurement of a range under the true mechanism,
  which nobody has yet written down.
