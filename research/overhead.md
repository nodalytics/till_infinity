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

## The `in_origin` effect looked keepable and is not

Standing *inside* an origin looked worse for both directions - sells 80.7%
against 81.9%, buys 81.9% against 84.4%. Pooled over 24,320 touches that is
-1.9% at p = 0.002, and -2.5% at p < 0.001 on buys alone. It was written up
here as the thing worth keeping from this experiment.

**It does not survive the interval.**

| interval | inside | outside | gap | p |
| --- | --- | --- | --- | --- |
| 1m | 76.6% (8,716) | 78.5% (3,537) | -1.9% | 0.008 |
| 3m | 80.8% (3,164) | 79.9% (1,023) | **+1.0%** | 0.763 |
| 5m | 87.0% (3,834) | 84.4% (1,635) | **+2.6%** | 0.995 |
| 15m | 96.5% (810) | 99.5% (567) | -2.9% | 0.000 |
| 30m | 98.7% (318) | 99.7% (357) | -1.0% | 0.152 |

**On 5m, being inside an origin is better by 2.6 points.** The sign is not
stable across timeframes, so the pooled number is a mixing artefact: 1m carries
half the touches at a 77% base rate, 5m a fifth at 85%, and the proportion
inside an origin differs between them. Simpson's paradox, for the third time in
a week in this folder.

Per instrument it is nothing: only three of the busiest ten carried enough of
both, median gap -0.5%, two of three negative.

**So nothing here is worth acting on**, and the thing that would have been
acted on is the one that failed. What the table does show plainly is the
**interval gradient** - 76.6% held on 1m against 98.7% on 30m - which is
already known, already measured on trade outcomes (`-821.75` over 129 closes
sub-15m against `+35.03` over 21 at 15m and above), and already scaled for by
`scaling.by_interval`.

## A field that has never carried anything

`run_vol` is present on every touch outcome and its **maximum over 2,000
samples is 0.000**. Not near zero - exactly zero, every time. Another entry for
[inert.md](inert.md), found the same way as the last one: by reaching for a
field while testing something else.
