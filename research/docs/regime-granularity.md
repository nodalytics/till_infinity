# At what granularity is a regime label real?

Every pooled statistic on this desk has quietly assumed that members of a
family share a regime - that if EURUSD is in a high-volatility state then so is
GBPUSD. `pooled-medians-invert-subgroups` is the standing reason to distrust
that: the pooled answer there agreed with a claim every subgroup refuted.

`research/ideas/regime_split.py` measures it directly. Two-state causal labels
per instrument, pairwise agreement as the statistic, a circular-rotation null,
66 instruments at 1h across 24 families.

## The answer splits by what the regime is about

**Volatility pools everywhere. Direction pools only inside a cohort.**

| family | vol 24 | vol 168 | drift 24 | drift 168 |
| --- | ---: | ---: | ---: | ---: |
| fx majors *(split quote convention)* | +85.3 | +36.2 | **-10.0** | **-2.4** |
| fx emerging | +55.1 | +27.6 | **+104.7** | +38.4 |
| fx crosses | +60.9 | +33.8 | +45.9 | +17.5 |
| equity indices | +45.8 | +26.5 | +70.5 | +31.6 |
| us indices | +23.9 | - | - | - |
| precious metals | +38.2 | - | - | - |
| crypto | +24.9 | +15.4 | +65.6 | +23.3 |
| us banks | +17.6 | +8.4 | +27.6 | +10.9 |
| us utilities | +16.2 | +5.1 | +24.2 | +8.9 |
| us energy | +20.9 | +6.0 | +24.9 | +13.1 |
| us mega-cap tech | +22.5 | +11.0 | +28.9 | +11.9 |
| softs | +5.5 | +2.9 | +10.6 | +4.5 |
| **between traded families** | **+22.4** | **+9.7** | **-1.7** | **-0.2** |
| *between synthetic families* | *+2.9* | - | *+0.1* | - |

All eleven synthetic families sit at the null on both regimes - 22 cells within
plus the between row, every one inside the noise. That is what licenses reading
the rest of the table rather than suspecting the statistic.

**So the operating rule is:** fold variance across a cohort and even desk-wide;
never fold direction across cohorts. Inside a cohort direction folds strongly,
but only after orientation is handled, and a shared drift regime is a
**co-movement** fact rather than a forecast - `direction-is-closed-not-just-null`
has the gate earning 2% of a spread while correctly finding a planted drift at
z +2.90.

## Orientation is not optional, and it inverts the answer

The fx majors read drift agreement **z -10.0**, far *below* the null, while the
same family read |correlation| **z +178.6**. EURUSD and USDJPY carry USD on
opposite sides, so a USD trend labels them oppositely: the statistic read the
strongest shared drift in the cache as the absence of one. Under perfect USD
sharing, agreement for a 4-vs-3 split is `9/21 = 0.429`; measured 0.486 sits
between that and the 0.500 null. fx emerging is all USD-base, consistently
oriented, and reads +104.7 on the same mechanism.

`a-control-is-only-for-a-named-property`, again: the label said "shared USD
leg" but the statistic measured "same label". The fix is a **sign-free**
companion, mean |correlation| of the labels read as -1/+1 against the same
rotation null, so no convention table is needed and nothing is fitted.

## Three defects this harness had, and how each surfaced

* **A permutation null would have multiplied every z by about seven.** On
  persistent-but-independent labels a smoke test read agreement 0.494 against a
  rotation null of 0.500 sd **0.0173** and a permutation null of 0.496 sd
  **0.0023** - the same centre, a null 7.5x too narrow, because a permutation
  treats every bar as an independent draw when a label persisting 100 bars
  contributes one. `overlapping-windows-inflate-permutation-nulls` in a
  different costume.
* **Four sector rows read "too few members", which looks exactly like a
  measured absence.** Equities are cached as `AAPL.OQ` and `JPM.N` while every
  index, pair and synthetic is bare, so a bare lookup matched none of 523
  names. A missing row and a null row print the same way.
* **A generated family was counted as a traded one.** `deriv volatility pairs`
  carried none of the words the classification inferred from, so it landed
  inside the control that the traded row is read against. The classification
  now asserts its own size and stops the run instead.

## Deriv synthetics have no cross-section at all

This is the sharpest structural result here. Eleven generated families, 22
cells, nothing above the noise - and `Volatility_75_Index` against
`Volatility_75_1s_Index`, which share a *declared* nominal volatility, read
+0.2 and +0.7. Deriv does not drive the two sampling rates from one source.

So they are real markets, as `deriv-synthetics-are-real-markets` says, but each
is a **market of one**: relative value, pairs, sector rotation and
cross-sectional ranking are all inapplicable there, not because the series are
fake but because there is no cross-section to rank. Their structure is entirely
in the time dimension, against a generator whose parameter is in the product
name - and `exotic-spreads-are-a-whole-bar-range` says to cost that before
measuring it.

## The one lead worth following

**Between-synthetic-family co-movement reads z +2.9 / +4.8 on volatility**,
where eleven independent generators should give exactly zero. It is small
(0.509 against a 0.498 null) and rests on 2,241 common bars, so it needs power
before it means anything. But it is the first thing measured here that looks
like shared infrastructure leaking - a server-side clock or RNG coupling - and
that is a generator fingerprint rather than a trading edge.

## What is not measured

The service folds 1m and 5m; every number here is 1h or coarser because the
cache holds nothing shorter for most names. Whether regime sharing survives at
the traded frame is open, and the sign of the window dependence here - z falls
monotonically as the window lengthens while the *level* of agreement rises - is
about effective sample size, not about the effect getting weaker.
