# Osler's control, run - and why it could not answer the question

`research/reading.md` records the finding this was built to test. Osler
(*Support for Resistance*, FRBNY Economic Policy Review, 2000) took the support
and resistance levels **six FX firms published to their customers**, found they
predict intraday trend interruptions, and found that **round numbers predict
about as well as most published levels**. If that held here, the Kalman
filters, the swing origins, the eight timeframes and the confluence grouping
would be decoration.

It was run on 2026-09-07 over 16 instruments and 1,119,800 stored bars. **The
answer is that this measurement cannot resolve the question**, and the way that
was established is the useful part.

## What was run

Three books, scored by one counter on the same bars:

* **drawn** - the engine's own levels, formed causally on the first 60% of each
  series and then frozen, so nothing is scored on data that shaped it.
* **round** - the round-number grid, two decades below the price, thinned to
  the drawn book's density.
* **random** - prices drawn uniformly over the same range at the same density.
  [magnet.md](../docs/magnet.md)'s baseline, here because an arbitrary price
  has already beaten a level on this book once.

An approach opens when a bar reaches within 0.25 volatility units of a
candidate price, with no approach already open there - the rule `Level.waiting`
enforces, and for the reason it exists: without it one visit becomes one touch
per bar and the counter measures loitering rather than turning. It resolves
when price travels one volatility unit away (**held**) or through (**broke**)
within twelve 5m bars, with the contradicting barrier checked first.

Density is matched because it has to be. A book with twice the prices gets
twice the chances, and comparing hit counts without matching would measure how
finely each grid was cut.

## The pooled numbers, which are the wrong ones to read

| book | approaches | hold rate |
| --- | --- | --- |
| drawn | 5,877 | 61.2% |
| round | 2,540 | 56.5% |
| random | 5,454 | 61.3% |

The pooled rate is dominated by the equity indices, where **all three books
hold at 79-84%** - a property of those instruments, not of any book. spx500,
us100 and us30 are 32% of the drawn approaches, so pooling weights the answer
by which instruments happened to produce approaches.

## Paired per instrument, which is the right one

| comparison | mean difference | s.e. | feeds won |
| --- | --- | --- | --- |
| drawn - random | **+0.13pp** | 1.29 | 7 of 16 |
| drawn - round | +1.04pp | 1.42 | 10 of 16 |
| round - random | -0.92pp | 0.78 | 5 of 16 |

**Every pair is inside one standard error.** A drawn level, a round number and
a price picked out of a hat hold price equally well on this measurement. The
round-number deficit that looked like 4.8 points pooled is 0.9 points paired,
and it is the density and feed-mix confound rather than a finding.

## The positive control, which is why none of that can be believed

If a counter cannot separate a level from a random price, there are two
explanations and they have opposite consequences: the levels carry nothing, or
the counter is blind. So the same run scored the drawn book split in half by
its own touch count - the strongest thing the book records about itself.

| | approaches | hold rate |
| --- | --- | --- |
| well-tested half | 3,027 | 61.7% |
| untested half | 2,850 | 60.6% |

Paired per instrument: **+2.34pp, s.e. 2.03, winning on 9 of 16.** Just over
one standard error, which is not separation.

**The control failed, so the null is uninformative.** A counter that cannot
tell a level touched forty times from one touched twice is not entitled to an
opinion about whether levels beat round numbers.

## Why it failed, and it was already written down

[resolution.md](resolution.md) measured this in production: **two thirds of
touch outcomes resolve within two seconds.** A 5m bar cannot see them at all -
a bar's wick was found to be resolving touches born inside the same bar, and
the conclusion recorded there was that no bars-only replay could see it.

That is exactly what this run is. The engine's own machinery, fed from the
quote stream, separates hold from break at **AUC 0.658** over 10,904 touches
([force.md](force.md)). The same book, audited at 5m resolution with a frozen
level set, separates nothing at all. The gap between those two numbers is the
resolution of the audit, not the quality of the levels.

Two further handicaps, both stated rather than corrected:

* **The book is frozen** after the formation window. Live, the Kalman filter
  moves each level on every touch and pruning removes the ones that stop
  earning their place; a frozen book has neither.
* **1m and 3m are missing** from the extract, so the levels were formed on 5m
  and coarser - and 1m levels break 57.9% of the time against 12.8% at 15m,
  which is a distribution the drawn book here never saw.

## What would actually answer it

The control is worth running properly, because the question it asks is the
sharpest one available about this system. It needs the **quote stream**, not
bars:

1. Store quotes for a set of instruments at the resolution the engine already
   consumes - the `quotes` table exists and is indexed on feed.
2. Run the round-number and random books through the **engine's own touch
   machinery** rather than a second counter written for the audit. A separate
   implementation of "did this level hold" is a second thing to get wrong, and
   this document is what that costs.
3. Score all three books through the outcome machinery that produced the 0.658,
   so the comparison is against a number that is known to resolve.

Until then the honest position is the one this document ends on: **the level
book has never been compared against a trivial baseline at a resolution capable
of telling them apart.** It is not evidence that levels work, and it is not
evidence that they do not.
