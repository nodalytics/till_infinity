# Does unfilled interest above make a sell early?

The observation that prompted this: a Volatility 10 sell whose **side** was
right and whose **timing** was wrong, because there was still an imbalance
above that price would likely revisit first.

The system already computes that object. An **origin** is where a violent move
began, so an origin above price is selling interest that was placed and not
filled, and `origin_above_vol` - its distance in volatility units - is on every
published call. So the claim is directly testable and needed no new machinery.

## Two readings, pointing opposite ways

* **Resistance.** Unfilled selling above caps a rally, so a sell placed under
  it is *safer* - the level has help.
* **A magnet.** Unfilled interest is somewhere price wants to go, so a sell
  placed under one is *early* and gets run over on the way up.

Which is why it is worth measuring rather than reasoning about.

## Held rate says the resistance reading, weakly

24,627 decisive touches over 7 days, each joined to the decision that carried
the origin features.

**Sells, by distance to the origin above:**

| distance | touches | held |
| --- | --- | --- |
| 0 - 0.25v | 1,895 | 80.9% |
| 0.25 - 0.71v | 1,895 | 81.2% |
| 0.71 - 1.54v | 1,896 | **81.5%** |
| 1.54 - 3.10v | 1,895 | 79.5% |
| above 3.10v | 1,895 | **78.6%** |

A *near* origin above is mildly **better** for a sell, not worse - the opposite
of the magnet reading, and about 2.9 points across the range.

**Buys, by distance to the origin above:**

| distance | touches | held |
| --- | --- | --- |
| 0 - 0.29v | 2,116 | **81.7%** |
| 0.82 - 1.81v | 2,117 | 82.7% |
| above 3.70v | 2,117 | **84.3%** |

The cleaner of the two: a buy does worse with a ceiling close overhead, better
with room. Same object, read as a ceiling rather than as a magnet, and it is
the direction that makes sense.

**And standing inside an origin is worse for both**: sells 80.7% inside against
81.9% outside, buys 81.9% against 84.4%.

## Adverse excursion says nothing at all, which settles it

Held rate is the wrong instrument for "the entry was early" - a level can hold
and the trade still be uncomfortable. The right one is how far price travelled
*against* the call before resolving, and `depth_vol` is that.

If the magnet reading were right, a sell with a near origin above should show a
**deeper** adverse excursion. Median `depth_vol`:

| distance to the origin above | sells | buys |
| --- | --- | --- |
| nearest fifth | 0.554 | 0.523 |
| middle | 0.584 | 0.569 |
| farthest fifth | 0.483 | 0.479 |

**Flat, and identical in both directions.** Buys show the same mild rise-then-
fall against the origin *above* as sells do, and both show it against the
origin *below* too. That symmetry is the answer: it is not about direction at
all, it is that an origin near price means price is in congested ground, which
makes any touch slightly deeper.

## Conclusion

**The magnet reading is not supported.** Neither held rate nor adverse
excursion shows the asymmetry it predicts, and the one directional effect that
does appear - buys doing worse under a near ceiling - is its opposite.

That does not make the original observation wrong about the trade it was made
on. It makes it wrong as a *general* rule, which is the only thing a
measurement over 24,627 touches can settle. A single trade where price ran up
into an imbalance before falling is entirely consistent with an effect that
does not exist on average.

**What is worth keeping:** standing *inside* an origin is worse for both
directions, by 1.2 points on sells and 2.5 on buys. That is a different claim
from the one tested, it is already computed as `in_origin`, and nothing acts on
it.

## A field that has never carried anything

`run_vol` is present on every touch outcome and its **maximum over 2,000
samples is 0.000**. Not near zero - exactly zero, every time. Another entry for
[inert.md](inert.md), found the same way as the last one: by reaching for a
field while testing something else.
