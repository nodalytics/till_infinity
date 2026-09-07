# Where is the origin, really - the grid test

`research/origin_localization_research_specification.docx` sets out a programme
for improving how this system locates the latent origin: the point where an
incoming volatility run becomes an outgoing one. Its section 22.12 is the test
that has to run first, because everything else in the document depends on the
answer:

> Reconstruct the same underlying fine data using different bar boundaries,
> offsets, and aggregation schemes. A robust origin should remain approximately
> stable; a bar artifact will move with the arbitrary candle boundary.

Run 2026-09-07 over 8 instruments and 1,410,154 one-minute bars. **The answer
is "partly", and that is the strongest argument the specification has for its
own priority list.**

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

## Result

Two detectors, because the repository has two and they behave differently.
`runs` draws the boundary between volatility runs; `origin` (`origin_points`)
draws the price a violent move began from, and is what now sets the walls of
the swing box.

| detector | | median shift | within 0.25v | within 0.5v | within 1.0v |
| --- | --- | --- | --- | --- | --- |
| **runs** | grid shifted | **0.34v** | 38.3% | 57.1% | 72.6% |
| | its null | 0.71v | 24.9% | 40.7% | 58.4% |
| **origin** | grid shifted | **2.60v** | 8.8% | 15.4% | 25.9% |
| | its null | 5.98v | 3.8% | 7.4% | 14.1% |

Both detectors are about **twice as stable as random**, so there is a real
event underneath - this is not pure artifact. And both move a lot: choosing to
start the bars one minute later moves the located run boundary by a median
0.34 volatility units, and the located impulse origin by **2.60**.

The impulse origin is the sparser and stronger of the two, and it is the *more*
grid-dependent in volatility units. That is the finding to carry forward,
because it is the one the swing box now rests on.

## Pooling hides the instruments

| feed | runs: shifted | its null | origin: shifted | its null |
| --- | --- | --- | --- | --- |
| spx500 | **0.00v** | 0.30v | 1.61v | 3.17v |
| eurusd | 0.17v | 0.29v | 1.03v | 1.79v |
| usdjpy | 0.25v | 0.77v | 1.51v | 5.19v |
| us100 | 0.34v | 0.54v | 2.96v | 5.37v |
| gbpusd | 0.30v | **0.27v** | 0.89v | 1.89v |
| btc | 0.97v | 3.14v | 5.75v | 24.36v |
| eth | 0.98v | 3.42v | 6.39v | 24.01v |
| gold | 1.21v | 1.72v | 6.81v | 11.15v |

spx500's run boundaries do not move at all under a grid shift. gbpusd's move
*further than random*. Any single pooled number for "is the origin stable"
averages those two, and the average describes neither.

## What this licenses, and what it does not

**It does not license "the drawing is decoration".** Twice random is a real
signal, and section 22.12 was written as a falsification test that the origin
concept could have failed outright. It did not.

**It does license the specification's priority 1**: fine-resolution
localization. A median wander of 0.34v (2.60v for impulse origins) from an
arbitrary choice of where the bars start is exactly the error a finer
transition estimate exists to remove, and it is now a measured quantity rather
than a suspicion - which means any candidate estimator has a number to beat.

**It also says which instruments to test on.** btc, eth and gold have the most
to gain, and spx500 has nothing: its origins are already stable, so an
improvement measured there would be measuring noise.

This is independently consistent with [rounding.md](rounding.md), which found
drawn levels indistinguishable from random prices at a 5m audit resolution.
Two measurements arrived at from different directions both say the level book
carries less information than its machinery implies. Neither is conclusive
alone; together they are the case for doing the specification's work.

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

In the specification's own priority order, and with the numbers above as the
baseline any candidate has to beat:

1. **Fine-resolution run transition** against the 0.34v / 2.60v wander, on btc,
   eth and gold where there is most to gain.
2. **The origin as a posterior rather than a point.** The grid test is already
   a crude version of one: fifteen offsets give fifteen estimates, and their
   spread is an uncertainty interval that costs nothing more to compute.
3. **The directional body-edge rule** (section 9), which has not been
   implemented or tested here and cannot be assessed from this run - the
   current detector reads closes, so there is no body intersection in the
   pipeline to compare against.
