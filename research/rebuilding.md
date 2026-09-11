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

Six harnesses. [`rebuildgen.py`](harness/rebuildgen.py) holds the generators, the
statistical battery and the discriminator, and states no results;
[`rebuildvol.py`](harness/rebuildvol.py),
[`rebuildstep.py`](harness/rebuildstep.py),
[`rebuildspike.py`](harness/rebuildspike.py),
[`rebuildpower.py`](harness/rebuildpower.py) and
[`rebuildjudge.py`](harness/rebuildjudge.py) are the studies. Each states its
kill conditions in its docstring before any number, and each records - in the
same docstring - which conditions were amended during a dry run against
synthetic data and what forced the amendment.

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

## What is established, and what is waiting on a machine

The research lab went unreachable part-way through this work - "no route to
host", not a slow link - and `research.db` exists nowhere else: the local
`prices.db` carries fourteen real instruments and not one synthetic. So this
page divides cleanly, and the division is stated rather than blurred.

**Everything that does not need the feed has been run.** That is more than it
sounds, because it includes the whole calibration of the apparatus and two
results about the real instrument that go through published numbers rather than
raw rows.

**The two-sample comparison against the live feed has not.** Every harness has
been run end to end against a synthetic database - sixty days of bars and
twenty-four hours of ticks for all twenty-six feeds, generated by these same
generators - which is how the bugs below were found, and which establishes that
the machinery behaves when the truth is known. It is not a result about Deriv.
The commands are one line each and are in `research/README.md`.

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
what a family with one generator and a rate parameter should look like, and it is
the clearest evidence on this page that the mechanism is close but not the one
Deriv is running.

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
how far the break carries** - 130 steps against 210. The break rate and the break
size scale together, the range does not.

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

**What is left, and what it points at.** Under the shared width the residual is
no longer a sign flip but a shape: the rebuild is **too confined at one minute**
(-0.086 and -0.018) and **too free at twenty** (+0.047 and +0.024). That is what
a hard wall looks like against something smoother - a reflecting barrier bites
immediately when the price is near it and then relaxes on a single slow mode,
where a graded restoring force does less at short range and more at the scale of
its own relaxation. The specification's missing piece is therefore not a second
timescale and not a second event: it is the **shape of the confinement at the
edge of the range**, and the data says it is softer than a wall.

**So `deriving.md` is not complete enough to re-instantiate Range Break.** One
parameter has to be supplied from outside the specification - a shared range
width of about 60 steps - plus a per-feed break size, and even then a structured
residual remains at the box's own relaxation time. That is a sharper statement of
the gap than "the mechanism is not published", and it is three falsifiable
claims: one shared width, no second re-range event, and a soft edge.

## What is still to run, and exactly what it will settle

Five commands, each one line, each detached with a flag file. They are in
`research/README.md` beside the rest of the generator study and they need nothing
but a reachable lab:

```bash
./.secrets/lab.sh run research/harness/rebuildvol.py MULT=10 JMULT=4
./.secrets/lab.sh run research/harness/rebuildstep.py MULT=10 RBMULT=5
./.secrets/lab.sh run research/harness/rebuildspike.py BMULT=2
./.secrets/lab.sh run research/harness/rebuildjudge.py
./.secrets/lab.sh run research/harness/rebuildpower.py
```

What each one decides is already fixed, because the failure conditions are in
the docstrings and the thresholds are numbers rather than judgements:

* **`rebuildvol.py`** - 12 feeds x 4 seeds x 864,110 bars. Whether two numbers
  per instrument reproduce the feed's realised volatility inside 0.5%, its
  kurtosis inside 3 standard errors of 3.00, its Hurst exponent inside 0.01 of
  0.50, and its Parkinson ratio inside 1%; whether a KS on one-minute log
  returns rejects on more than 3 of the 12; and whether the 66 pairwise
  correlations among the rebuilt feeds look like the 66 among the real ones.
  The two readings of the Jump family's 1.322 are decided here too, and they
  predict different kurtosis, so the data can choose.
* **`rebuildstep.py`** - whether four numbers reproduce Step Index's 99.9988%
  concentration, its fair coin, its sign autocorrelations and its gambler's-ruin
  hit rates; and whether the Range Break rules fitted above survive being scored
  against the feed's own rows rather than against a published table, with the
  band re-estimated from the visited range and a 12-seed Monte Carlo null
  standing in for a standard error that does not apply to a jump process.
* **`rebuildspike.py`** - whether the **five published numbers** re-instantiate
  Boom and Crash, or whether the empirical marginal is needed. Both are built and
  the difference between them is the answer. It also has to reproduce
  `genstop.py`'s +13.96R, +6.81R, +2.44R and +1.02R stop slippage from a path
  that was never shown them.
* **`rebuildjudge.py`** - the headline. Whether a classifier can tell the feed
  from the rebuild, read against the feed-against-itself floor, plus the
  randomness batteries on the venue's own increment stream against the RANDU and
  PCG64 controls calibrated above.
* **`rebuildpower.py`** - `n*` per family: the sample size at which a test starts
  separating the rebuild from the feed, with the closed form and the empirical
  crossing required to agree within a factor of three on the controls.

## What this page does not say

* **It is not yet a result about Deriv.** Everything above is either apparatus
  calibrated on ground truth, or a comparison against numbers `deriving.md` and
  `generators.md` already published. The two-sample tests against
  `research.db`'s own rows have not run, and until they do this page reports a
  method and a Range Break finding, not a verdict on the other four families.
* **A rebuild that survives is not a proof of identity.** It is a statement that
  nothing in this battery, at this sample size, separates the two - which is
  exactly why the headline is `n*` and not a pass mark.
* **The randomness battery is small.** A million uniforms is four orders of
  magnitude short of TestU01's SmallCrush. It excludes a grossly broken source
  and certifies nothing.
* **The Range Break scan is a scan, not a derivation.** Two parameters were
  chosen by minimising a distance to a published curve. The residual at twenty
  minutes is evidence the mechanism is wrong in a specific way; it is not
  evidence about what the right one is.
* **The jump size for Range Break 200 sits at the edge of the scanned grid**
  (230 of a grid ending at 230), so that parameter is a bound rather than a fit.
