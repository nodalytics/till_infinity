# Where is the origin, really - the grid test

`research/origin_localization_research_specification.docx` sets out a programme
for improving how this system locates the latent origin: the point where an
incoming volatility run becomes an outgoing one. Its section 22.12 is the test
that has to run first, because everything else in the document depends on the
answer:

> Reconstruct the same underlying fine data using different bar boundaries,
> offsets, and aggregation schemes. A robust origin should remain approximately
> stable; a bar artifact will move with the arbitrary candle boundary.

Run 2026-09-07 over 8 instruments and 1,410,154 one-minute bars. **The origin
passes**: it is 2.8x more stable than a matched random book, and what wander
it has sits comfortably inside the band the system already gives it.

An earlier version of this document reported the opposite, from a harness that
warmed its volatility estimate incorrectly. The correction is below rather than
edited away, because the mistake is instructive: every number was in the right
*ratio* and the wrong *scale*, which is the shape of error a comparison-only
reading survives and an absolute reading does not.

## Method

1m bars, aggregated into 15m bars at **all fifteen possible offsets**. The
repository's own detectors run on each grid, unmodified. For every origin found
on the standard grid, the distance to the nearest origin on a shifted grid, in
volatility units.

Every comparison carries a **density-matched null**: a book of random prices
over the same range with the same *count* as the book it is the control for.
This is not decoration. The first version of this test compared 15m origins
against 1m origins and reported 98.7% agreement within a quarter unit - until
the matched null scored **99.9%**. A detector that finds fifteen times as many
prices puts one near anything, and without the null that number reads as
success.

## A correction, first

**The numbers first published here were inflated, and the conclusion drawn
from them was wrong.** The harness warmed its volatility estimate with
`Volatility.observe_bar` alone. That method folds a bar into the *range*
estimators and deliberately does not touch the mean-absolute-return the unit
is built from - its docstring says so, "Closes go to `update`" - so `bps` sat
on its floor and every distance expressed in volatility units came out
inflated by the same factor. `engine.py:1368` calls both, in that order, and
the harness now does too.

The ratios in the first version survive, because both sides of every
comparison were divided by the same wrong unit. The absolute figures do not.
The corrected ones are below and they say something different: **the origin's
localization error is small relative to the band the system already gives it**,
where the first version had it larger.

## Result

Two detectors, because the repository has two and they behave differently.
`runs` draws the boundary between volatility runs; `origin` (`origin_points`)
draws the price a violent move began from, and is what sets the walls of the
swing box.

| detector | | median shift | within 0.25v | within 0.5v | within 1.0v |
| --- | --- | --- | --- | --- | --- |
| **runs** | grid shifted | **0.03v** | 95.0% | 98.4% | 99.5% |
| | its null | 0.05v | 87.9% | 97.1% | 99.9% |
| **origin** | grid shifted | **0.23v** | 53.2% | 74.6% | 91.5% |
| | its null | 0.65v | 24.7% | 41.6% | 65.0% |

The impulse origin is **2.8x more stable than a density-matched random book**
and moves a median 0.23 volatility units when the bars are made to start a
minute later. The run boundary barely moves at all.

### And the band already contains that error

`origins.zone_of` gives every origin a band - the last bar of the opposing leg,
or its body where that bar is mostly wick - and that band is the uncertainty
the rest of the system acts on. Measured on the same data and the same unit:

| | median | p75 | p90 |
| --- | --- | --- | --- |
| origin band width | **1.58v** | 1.95v | 3.24v |
| grid wander | 0.23v | | |

**The band is about seven times the localization error.** So the origin is not
claiming a precision it does not have; if anything the band is generous. The
median detected move is 8.13v against the 4.0v `MOVE_VOL` threshold, which is
the sanity check that says the detector is finding what it was built to find.

## What this licenses, and what it does not

**The origin survived its falsification test.** Section 22.12 was written so
the concept could fail outright, and it did not: 2.8x a matched null, with a
wander well inside the band the system already uses.

**And that substantially weakens the case for the specification's priorities
1 to 3.** Fine-resolution localization, the origin-as-posterior, and the
body-edge rule are all ways of pinning the origin down more precisely. The
measurement says precision is not the binding constraint - there is 0.23v of
localization error sitting inside a 1.58v band, so removing all of it would
tighten the band by about a seventh, and only if the band were re-derived from
the improved estimate rather than left as the bar's range.

That is a claim about *this* data at *this* resolution, and it is falsifiable:
if a fine-resolution estimator cuts the 0.23v materially, the argument changes.
Which is why the estimators were built and measured rather than declined - see
[the estimator comparison](#the-estimators-measured) below.

**Pooling still hides the instruments.** spx500 and us100 barely move at all on
`runs` (0.01v); btc, eth and gold are the loosest. Any estimator claiming an
improvement should show it on the loose ones.

| feed | origin: shifted | its null | ratio |
| --- | --- | --- | --- |
| usdjpy | 0.24v | 1.01v | 4.2x |
| btc | 0.22v | 0.94v | 4.3x |
| eth | 0.19v | 0.76v | 4.0x |
| gold | 0.28v | 0.63v | 2.3x |
| eurusd | 0.24v | 0.58v | 2.4x |
| gbpusd | 0.29v | 0.49v | 1.7x |
| spx500 | 0.25v | 0.50v | 2.0x |
| us100 | 0.15v | 0.39v | 2.6x |

[rounding.md](rounding.md) is a separate finding and is **not** corroborated by
this one, which the first version of this document wrongly implied. That one
could not resolve its own positive control; this one resolves cleanly and comes
out in the level book's favour.

## The estimators, measured

Sections 5, 9 and 13: the candidates behind one interface, every estimate
attached to the **same** events so no method can pick a friendlier population,
compared paired. An event where any estimator cannot produce a price is dropped
from all of them - a body-edge miss must not quietly shrink the population it
is scored on.

There is no observable "true origin" to compute an error against, so the
property being ranked is the one this data can rank: **does the estimator say
the same thing when the bars are made to start a minute later.**

| estimator | median wander | its null | ratio | moves the estimate |
| --- | --- | --- | --- | --- |
| A - baseline (the turn bar's close) | 0.237v | 0.722v | 3.0x | - |
| **F - fine-resolution transition** | **0.124v** | 0.723v | **5.8x** | 71.4% of events |
| H - change point | 0.211v | 0.722v | 3.4x | 90.4% of events |
| D - directional body edge | 0.237v | 0.713v | 3.0x | 21.9% of events |

406 events over 8 instruments, 5,684 paired comparisons.

**Three of the eight candidates §5 names**, and an earlier version of this
document said "the estimators" as though that were all of them. B (candle
boundary), C (body midpoint), E (run intersection) and G (F fed to the Kalman
rather than replacing the price) were never run; they are in
[docs/todo.md](../docs/todo.md) with what each is worth.

### F wins, and the specification was right to rank it first

Locating the transition inside the coarse bar at 1m **halves the grid wander**,
0.237v to 0.124v, and takes the ratio against a matched random book from 3.0x
to 5.7x. It moves the estimate on 71.4% of events, so this is not a rounding
effect on a handful of them.

Per feed it wins everywhere, and by most on the instruments the earlier section
called loose: gbpusd 0.330v to 0.124v, gold 0.295v to 0.122v.

### H is real and still loses, which §18 predicted

Section 6 asks for a change-point estimator as an independent experiment, and
§23 makes it priority 2 of three. It was built on the repository's own `Cusum`
rather than a new statistic - a symmetric change-point filter over a price
series in volatility units is exactly what §6 describes, and `momentum_leads`
already trusts it to say when a regime turned.

The first pass rejected it for the wrong reason. `Cusum`'s default threshold is
2.0 volatility units, set for a stream running for hours; asked to find a
change **inside one bar** it crossed on 12.9% of events and fell back to the
baseline everywhere else, so the comparison was measuring a mis-set constant.
That is the error `at_bound` already made once here. Swept properly:

| threshold | median wander | ratio to null | moves the estimate |
| --- | --- | --- | --- |
| 2.0 (default) | 0.237v | 3.1x | 12.9% |
| 1.0 | 0.216v | 3.5x | 47.9% |
| 0.5 | 0.208v | 3.7x | 82.1% |
| **0.25** | **0.205v** | **3.8x** | 94.3% |
| 0.1 | 0.211v | 3.6x | 99.3% |

So H is **a real improvement on the baseline** - 0.237v to 0.205v - and
**decisively worse than F**, which is at 0.124v. It moves the estimate on 90.4%
of events, so this is a genuine alternative being beaten rather than one that
never fired.

The specification called it: §18 says the strongest expected candidate is the
fine-resolution transition and that the change-point model "should be evaluated
rather than assumed superior". It was, and it is not.

**What that says about §22.1.** Bayesian online change-point detection is the
principled version of what H did crudely - a posterior over "the regime has
ended" rather than a threshold crossing. H losing to F at every threshold is
evidence about the *family* rather than about the tuning, and §22.2 was already
refused here because the band is seven times the localization error. BOCPD
would have to argue past both, and it is listed in todo.md on those terms.

### D adds nothing, and section 18 says what to do about that

> Do not promote the user's body-edge hypothesis to the core definition simply
> because it visually matches selected examples. Promote it only if it
> consistently adds measurable value.

It does not. The body edge differs from the close on 21.9% of events - so it is
a real alternative, not an identity - and on the axis measured here it is
**identical to three decimal places**: 0.237v against 0.237v, 3.0x against 3.0x.
Where it disagrees with the current answer it is neither better nor worse.

There is a reason it lands so close, and it is worth stating because it makes
the result less surprising than it looks. On a clean turn the last bar of the
incoming run closes near its own high and the first bar of the departure opens
there, so the upper edge of the body intersection *is* approximately the turn
bar's close - which is what the repository already uses. The hypothesis is
largely an alternative derivation of the existing estimator rather than a
different one.

**Recommendation: reject D, adopt F.** Not because the body-edge idea is wrong
about what an origin is, but because on this evidence it is a second route to
the price already in use, and F is a first route to a better one.

F is implemented as `origins.refine`, with the coverage guard the measurement
implies: a finer series that does not reach both ends of the coarse bar
returns the origin unchanged, because a refinement computed from two of the
fifteen minutes is worse than none. Nothing calls it in the pipeline yet - the
`Series` window is bounded at 500 bars, so a 1m series covers about eight hours
and cannot reach a 4h origin, and wiring it in means deciding what to do on the
intervals it cannot serve. That decision wants its own measurement.

### What adopting F is worth, stated honestly

The band is 1.58v and the wander is 0.237v, so halving the wander tightens the
localization error inside a band seven times its size. **That is an improvement
in a quantity that is not currently the binding constraint**, and it should not
be expected to move a trading number on its own.

What would make it worth more is re-deriving the *band* from the finer estimate
rather than leaving it as the coarse bar's range - which is the next experiment
rather than a conclusion of this one.

## Three discrepancies between the specification and the repository

Section 20 asks for these to be reported before anything is changed.

**1. Origin detection reads closes, not OHLC.** `runs.points` and
`origins.Origins.observe` both walk a series of *closes*. `origins.zone_of`
uses the bar's OHLC, but only for the zone's **width**; the origin price itself
is a close. So the origin is already quantised to a bar boundary in the
strongest sense - it is one of the fifteen minutes the grid happened to end on.
That is the mechanism behind the numbers above, and it is why the body-edge
hypothesis of section 3 is not the current implementation's nearest neighbour:
the current implementation does not look at bodies at all.

**2. `ARRIVAL_RUN_VOL` / `DEPARTURE_RUN_VOL` are not the origin's thresholds.**
Section 7 asks to respect them. They exist - both 0.5 in `levels.py` - but they
belong to `reactions.py` and govern **touch resolution**: how far price has to
travel for an arrival to count as resolved. Origin formation uses
`runs.RUN_SWING_VOL` (1.0) and `origins.MOVE_VOL` (4.0). The repository keeps
two run concepts apart that the specification treats as one, and an experiment
written to the specification as stated would tune the wrong constants.

**3. Formation is deliberately coarse, and the specification asks to reverse
that.** Section 8 says to gather the finest data available for each event.
`Engine.observe_bar` does the opposite on purpose: *every bar forms levels for
its own interval, and only the finest interval's bars run the touch check.*
That split was a fix - a daily level warmed from daily bars had its origins
quantised to the day - and the docstring says running both would count every
interaction twice. Fine-resolution formation is therefore not a small change to
a threshold; it is a change to the shape of the pipeline, and the double-count
trap is the thing that will bite.

## Re-deriving the band from the finer estimate

The section above said adopting F should not be expected to move a trading
number while the *band* is still the coarse bar's range. This is that step:
`zone_of` applied to the **1m bar at the refined transition** rather than to
the quarter hour containing it - the same definition one resolution down, the
interest placed in the minute the move began rather than in the fifteen
around it.

Scored the way section 12 asks: when price returns, does it turn from inside
the band. A return resolves when price leaves by one volatility unit either
way, with the barrier that contradicts the origin checked first. The control
is a band of the same width at a price drawn uniformly over the same range,
which is what says whether a turn rate is about the origin or about the width.

| band | width | returns | held |
| --- | --- | --- | --- |
| coarse (today) | 1.49v | 384 | **71.1%** |
| fine-derived | **0.57v** | 364 | 63.5% |
| null, fine width, random placement | 0.57v | 251 | 51.0% |

**Both bands are real** - each beats a band of its own width placed at random,
which is the thing that had to be true before anything else mattered.

**And the difference between them is not there.** Paired per instrument, coarse
leads by **+3.26pp against a standard error of 4.27**, winning on 5 of 8. The
pooled 7.6-point gap is btc, eth and eurusd carrying the return count, not a
property of the bands. usdjpy, spx500 and us100 go the other way.

### Which is the argument for the narrow band, not against it

The finding is not "the fine band holds better". It is that a band **2.6 times
narrower catches 94.8% of the same returns and holds about as often**.

That is the money argument the localization work had been missing. The stop on
an origin trade sits beyond the band, so band width is stop width: the same
evidence, at a third of the risk. A 63.5% hold at 0.57v is a better trade than
a 71.1% hold at 1.49v unless the target scales with the band, and it does not -
the target is the opposite origin.

**Stated as a hypothesis, because that is what it is.** The turn rates above
are not a backtest, and the arithmetic that turns them into an edge assumes a
stop just beyond the band and a target that does not move. `swingtest.py` is
the thing that would settle it, and the swing box is drawn from exactly these
origins, so the experiment is available: re-run the eight-cell sweep with the
fine-derived band and see whether +0.299R moves.

That is the next thing to run, and it is the first time in this sequence that
a localization result has had a path to a trading number.

## FOCuS loses as an estimator and pays as a second opinion

`Cusum` reports where a run got long enough to trip. FOCuS maximises the same
likelihood ratio over *every* possible start and reports the argmax, so it
answers "where did this begin" rather than "when did I become sure" - which is
the origin's own definition and not a proxy for it.

Run as a fifth estimator on the population above, it beats the CUSUM version
on six of eight instruments and improves on the baseline:

| estimator | median wander | its null | ratio | moves the estimate |
| --- | --- | --- | --- | --- |
| A - baseline | 0.237v | 0.733v | 3.1x | - |
| **F - fine-resolution transition** | **0.124v** | 0.735v | **5.9x** | 71.4% |
| FOCuS change point | 0.192v | 0.734v | 3.8x | 98.8% |
| H - CUSUM change point | 0.211v | 0.722v | 3.4x | 90.4% |
| D - directional body edge | 0.237v | 0.759v | 3.2x | 21.9% |

5,684 paired comparisons. **And it still loses to F**, for the reason the
section below sets out at length: an origin is an extremum, and a change point
is a near-miss for one.

### Where it does pay

Two estimators built from different statistics landing on the same price is
worth more than either alone. Split F's own wander by whether FOCuS lands
within 0.25v of it:

| | n | F's median wander | within 0.25v |
| --- | --- | --- | --- |
| FOCuS agrees | 2,828 | **0.101v** | 66.4% |
| FOCuS disagrees | 2,856 | 0.152v | 60.9% |

The same origin is located half again as precisely when the two agree, on a
population that splits almost evenly.

### The control, which is the part that makes it a result

The obvious alternative explanation is that agreement just marks *easy events* -
bars with one clean impulse, which any estimator would locate well. If that
were it, every estimator would improve on the agreeing half. Split them all by
the same mask:

| estimator | agreed | apart | gain |
| --- | --- | --- | --- |
| baseline | 0.232v | 0.240v | 1.03x |
| **fine** | **0.101v** | 0.152v | **1.51x** |
| body edge | 0.229v | 0.239v | 1.04x |
| CUSUM change point | 0.205v | 0.212v | 1.03x |
| FOCuS | 0.150v | 0.211v | 1.41x |

The three estimators that do not resolve the transition do not move. Only the
two that do. So the agreement is carrying information about *the estimate*,
not about the event.

This is what `Origin.confirmed` and the `origin_confirmed` feature record, and
`origins.CONFIRM_VOL` is the 0.25v. **Nothing gates on it.** What is measured
is that the price is better *located*; whether a confirmed origin is better
*traded* is a different claim, and publishing the flag beside the outcome is
what lets the journal answer it.

## Six detectors, one population, and the extreme still wins

The change-point literature has more to offer than `Cusum`, and the obvious
question is whether any of it beats what is here. Six methods were written
from their papers - nothing copied from `changepoint-online`, `densratio` or
`ruptures`, because this repository is public with no licence file and a
dependency is a decision nobody has made - and pointed at the same events, the
same windows and the same metric.

* **FOCuS** - the exact CUSUM likelihood ratio maximised over every candidate
  start, which is what `structures/learning/focus.py` implements.
* **MD-FOCuS** - the same statistic over a vector. High, low and close are
  three views of one bar, so a change in the mean *vector* should be stronger
  evidence than a change in the close alone ([arXiv 2104.00581]).
* **BOCPD** - Adams & MacKay's run-length posterior. The only method here that
  reports a distribution over where the change was rather than a point.
* **KCP** - kernel change point, Gaussian kernel at the median width. Fully
  non-parametric, which matters because intraday returns are not Gaussian.
* **RuLSIF** - relative density-ratio estimation between a reference and a test
  window, scored by Pearson divergence. Sees a change in *shape*, not only in
  mean.
* **NEWMA** - two EMAs at different rates. The cheapest thing that could work,
  present so the expensive methods have to beat something.

The last four run on engineered features rather than raw prices - the log
return and the candle spread `log(high/low)` - because a kernel or a density
ratio on a non-stationary price level measures the level.

**The liquidity stream is missing and is not faked.** The argument for feature
engineering asks for log volume as the third stream, and `bt1m.db` carries
open, high, low and close and no volume at all. That half is untested here.

### The result

6,300 paired comparisons, 15-minute bars, so each window is 15 one-minute
observations:

| method | median wander | its null | ratio | within 0.25v |
| --- | --- | --- | --- | --- |
| baseline - the turn bar's close | 0.226v | 0.639v | 2.8x | 53.3% |
| **fine - the extreme, at 1m** | **0.107v** | 0.661v | **6.2x** | 66.7% |
| FOCuS | 0.161v | 0.650v | 4.0x | 58.7% |
| MD-FOCuS | 0.194v | 0.661v | 3.4x | 56.3% |
| NEWMA | 0.211v | 0.628v | 3.0x | 54.4% |
| BOCPD | 0.237v | 0.673v | 2.8x | 51.9% |
| KCP | 0.237v | 0.647v | 2.7x | 52.1% |
| RuLSIF | 0.251v | 0.641v | 2.6x | 49.9% |

**Does BOCPD beat FOCuS? No, and it does not beat doing nothing.** BOCPD, KCP
and RuLSIF all land at or *worse than* the baseline, which is the bar's own
close - the estimate you get by not running a detector at all. NEWMA, the
ten-line one, beats all three of them. FOCuS is the only member of the family
that improves on the baseline, and it still loses to taking the extreme.

### It is not a window-size artefact

The natural objection is that 15 observations is too thin for a method that
compares two densities, so the whole thing was re-run at 60-minute bars, giving
every method four times the sample:

| method | 15m | 60m |
| --- | --- | --- |
| baseline | 0.226v | 0.264v |
| **fine** | **0.107v** | **0.155v** |
| FOCuS | 0.161v | 0.264v |
| MD-FOCuS | 0.194v | 0.264v |
| NEWMA | 0.211v | 0.284v |
| BOCPD | 0.237v | 0.317v |
| KCP | 0.237v | 0.341v |
| RuLSIF | 0.251v | 0.367v |

More data made every one of them **worse**, and the ordering did not change.
The three density methods degrade fastest, and at 60m even FOCuS is level with
the baseline while the extreme still wins by 1.7x. 7,611 paired comparisons.

### Why, and it is the useful part

**This is an extremum problem wearing change-point clothes.** Every method
except `fine` is built to answer "has the distribution changed?" over a stream
with plenty of observations either side of the change. The question actually
being asked is different: given fifteen minutes that contain one turn, *which
single minute is the price the move left from*. An origin is **defined** as an
extremum, so the estimator that goes and finds the extremum is not competing
with these on their terms - it is answering the question, and they are
answering a nearby one.

FOCuS does best of the six because its statistic is a one-sided cumulative sum,
which is the closest thing in the family to "find the extreme". That is a
reason to keep it and not a reason to expect it to win.

### Multivariate made it worse, which is worth saying plainly

MD-FOCuS was the most promising of the six on paper and it lost to the
univariate version, 0.194v against 0.161v, on every instrument but two. The
co-dependence of high, low and close is real and it is not free information:
the high and the low are the bar's *extremes*, which widen with volatility
whatever the direction, so adding them to a directional statistic adds two
noisier views of the same move and dilutes the one that carried the signal.

At 60m the two are level (0.264v each), which fits - with more minutes in the
bar the extremes carry proportionally less of the noise. Neither beats taking
the extreme directly at either size.

The dual-stream framing this came from is still worth testing, but **not
here**: separating a trend reversal from a liquidity spike is a question about
*what kind* of event happened, and this harness only measures how precisely a
price can be located. That experiment wants the trap population in
[trapping.md](trapping.md), where "the range widened and the mean return did
not shift" is exactly the absorption case, and it wants volume, which this
database does not have.

[arXiv 2104.00581]: https://arxiv.org/pdf/2104.00581

### Blending the two does not work, and the reason is the definition

FOCuS pays as a *label* - `Origin.confirmed` above - so the natural next
question is whether it pays as a *number*. Three combinations of the two
estimators that beat the baseline, on the same 6,300 comparisons:

| estimator | median wander | ratio |
| --- | --- | --- |
| **fine alone** | **0.107v** | **6.0x** |
| lean - 0.75 fine + 0.25 FOCuS | 0.153v | 4.2x |
| mid - the midpoint | 0.167v | 3.9x |
| gated - fine when they agree, midpoint when not | 0.168v | 3.8x |
| FOCuS alone | 0.161v | 3.9x |

**Every blend is worse than `fine` alone**, and they get worse the more FOCuS
is mixed in - `lean` at a quarter beats `mid` at a half. Even the gated
version, which only mixes on the events where the two disagree, loses.

That is not a surprise once stated: an origin **is** the extreme, so any
weight on a different price moves the estimate off the thing being estimated.
The change point's value was never a better price - it is 0.161v against
0.107v and always was worse - it is knowing *when to believe the extreme*.
A label and a number are different things and this is the measurement that
says so.

## What would come next

The harness is the deliverable as much as the number. `gridtest.py` gives the
paired, density-matched comparison section 13 asks for, `estimators.py` ranks
the candidates on the same events, and `bands.py` scores a band by what price
does when it returns. Any new estimator or band rule drops into them.

In order:

1. ~~**Re-run the swing sweep with the fine-derived band.**~~ Done, and it is
   the largest single improvement measured on this strategy: +0.349R to
   **+0.576R** a trade, winning in all eight cells. It is also entirely
   inaccessible without persisting origins - a replay limited to the 1m window
   a live `Series` actually holds reproduces the baseline identically. See
   [swinging.md](swinging.md).
2. **The intervals `refine` cannot serve.** The `Series` window is 500 bars, so
   a 1m series covers about eight hours and cannot reach a 4h origin. Either
   the window grows for one series or coarse origins keep the coarse band, and
   that is a measurement rather than a preference.
3. **Cross-timeframe agreement.** Measured, and it is the largest thing to come
   out of this line: a change point confirmed on three or more timeframes is
   followed by continuation, one on a single timeframe by reversal, and at a
   matched realised move they differ by 9.17v a day out. See
   [agreeing.md](agreeing.md).
4. **Asymmetry.** Both bands here are symmetric about the transition. The
   repository already keeps per-side statistics everywhere else, and the
   specification's section 10 asks whether localization changes the wick-depth
   distribution. It should, and nobody has looked.
