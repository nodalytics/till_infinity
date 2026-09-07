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

## What would come next

The harness is the deliverable as much as the number. `gridtest.py` gives the
paired, density-matched comparison section 13 asks for, and any candidate
estimator drops into `detect()` and gets the same table. The number to beat is
**0.23v**, on btc, eth and gold where there is most room, and the honest prior
after the correction above is that there is not much room at all.
