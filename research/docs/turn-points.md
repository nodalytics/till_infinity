# Turn points and legs: four definitions, and whether a leg takes out the last one

**Measured 2026-11-17.** Five majors at 1h and 15m, 8 years, wick and body
sourced, plus four Deriv synthetics at 1h. Up to **278,023 legs** in one cell.
Harness: [`leg_sequence.py`](../ideas/leg_sequence.py) and
[`turn_shape.py`](../ideas/turn_shape.py); grids in
[`leg_sequence_run.py`](../ideas/leg_sequence_run.py),
[`leg_source_run.py`](../ideas/leg_source_run.py),
[`leg_matched_run.py`](../ideas/leg_matched_run.py) and
[`turn_shape_run.py`](../ideas/turn_shape_run.py).

The operator's standing instruction, 2026-11-17: *"anything that concerns
leg(s) analysis, we are in, the data we are using has to do with legs, so turn
points, etc are important to us"* - so this is a **description** of the objects
first and a set of refutations second.

| question | answer |
|---|---|
| **does a leg penetrate the previous turn point before reversing?** | **about half the time, and it is the distance** - 0.42 to 0.50 pooled, running from **0.89 at 1.5 ATR to 0.05 past 3.8**. The median leg ends **0.16 ATR short** of the previous turn point and the mean overshoots it by **+0.06**, which is what independent leg sizes give |
| **more or less often than chance?** | **less, and consistently** - distance *and* volatility matched against a day-shuffled market: origin **-0.0441** `[-0.0579, -0.0325]`, pivot **-0.0160** `[-0.0273, -0.0050]`, zigzag **-0.0108** `[-0.0145, -0.0072]`, fractal **+0.0035** `[-0.0028, +0.0090]`. The shortfall grows with how selective the definition is |
| **do turn points enable other turn points?** | **no.** Arrival gaps have a coefficient of variation of **0.98 to 1.24** against a memoryless 1.00, and the 1.24 is a wick artefact - on body-sourced pivots it is 0.983. Degree over turn points reads **-0.029 to +0.046** against a placebo node, every value inside its own +/-0.06 |
| **are there patterns - a grammar of HH/HL/LH/LL?** | **no.** Within each side the order-1 model saves **+0.000 to +0.013 bits** of a 1-bit alphabet, against [`grammar.md`](grammar.md)'s **+0.04 to +0.06** for a real bar-shape grammar that every walk read at 0 |
| **clustering, PCA, histogram binning, graph degree** | **all four find nothing the distance does not already say, and every apparent finding is matched or beaten by the same method on a day-shuffled market** |
| **wicks or bodies?** | **a different object, not a tidier one.** At a 1.5 ATR zigzag: 5,445 turns against 1,449, a 3.4-bar gap against 8.6, clearance 0.4150 against 0.4720 |

## What a turn point is, and what a leg is

Four definitions, each with the bar it happened at and - separately - the bar it
became **knowable** at. That separation is the whole of the honesty here: every
definition needs bars after the turn to confirm it, and a study that places the
turn at `at` and then measures the leg from `at` has read those bars twice.

| kind | the rule | known at | turns, 1h, 8 years, 5 markets |
|---|---|---|---:|
| `origin` | the operator's detector, confirmed: a 15-bar pivot low, a 1.5 ATR fall into it over 24 bars, then a 3 ATR directional rise within 24 bars that never trades below the low | the bar the 3 ATR rise completes | 6,364 legs, median reach 6.37 ATR, median hold 26 bars |
| `pivot` | the lowest low of 15 before and 5 after | `at + 5` | 10,782 legs, median reach 5.35 ATR, median hold 19 bars |
| `zigzag` | the running extreme, flipped when price retraces 1.5 ATR from it | the flip bar | 68,977 legs, median reach 2.49 ATR, median hold 2 bars |
| `fractal` | Williams: the lowest low of 2 before and 2 after | `at + 2` | 51,945 legs, median reach 2.26 ATR, median hold 4 bars |

Runs of same-side turns are collapsed to the **most extreme** of the run,
because "the previous opposite turn point" only exists on an alternating
sequence. Keeping the extreme is what a chartist drawing the leg does and it is
the conservative choice: it puts the barrier as far away as the run allows.

**A leg** runs from where turn `k` became knowable to where turn `k+1` became
knowable; its extreme is the highest high (or lowest low) of the chosen source
over that stretch; its barrier is turn `k-1`, the previous opposite turn.
`reach_atr` is the distance from the turn's own price to that barrier in ATR of
the turn's bar.

**One configuration is excluded and should be named.** When the prior opposite
turn is already behind the new turn - a prior high below this low, which is an
established trend - there is nothing to penetrate. Those legs are counted out
rather than scored as clearances; scoring them would inflate the rate by
whatever share of the sequence is trending.

### Wicks or bodies

The desk disagreed with itself. The supplied origin definition says "the
candle's **low**", a wick reading; the operator's Bjorgum preset sets *source of
pivots = high/low body*, so production's level detector is a body reading. They
are different objects, measured at a 1.5 ATR zigzag on hourly EURUSD:

| source | turns | gap, bars | arrival CV | cleared |
|---|---:|---:|---:|---:|
| wick | 5,445 | 3.4 | **1.236** | 0.4150 |
| body | 1,449 | 8.6 | **0.983** | 0.4720 |

A body zigzag gives a third as many turns, twice as long, and - the part that
matters - arrivals that are **memoryless** where the wick version looks
clustered. The wick clustering is wicks clustering, which is volatility
clustering printing extra pivots, not turns arriving in bursts.

## The size of a leg

Never written down here before. 1h swing pivots, per market, 2,034 to 2,337
legs each; the five markets agree to within a tenth of an ATR on every column.

| quantity | mean | p10 | p25 | p50 | p75 | p90 | p99 |
|---|---:|---:|---:|---:|---:|---:|---:|
| leg extent, ATR | 6.07 | 2.67 | 3.63 | 5.10 | 7.40 | 10.53 | 18.92 |
| leg duration, hours | 21.2 | 5 | 9 | 18 | 27 | 43 | 83 |
| reach to the prior turn, ATR | 6.01 | 3.06 | 3.85 | 5.18 | 7.36 | 10.15 | 16.25 |
| **overshoot of it, ATR** | **+0.06** | -5.11 | -2.48 | **-0.16** | +2.25 | +5.35 | +14.63 |

**The previous turn point is the median leg target.** The overshoot
distribution is centred on it - mean +0.06 to +0.22 across the five markets,
median -0.04 to -0.28 - which is exactly what independent leg sizes produce: if
the new leg's extent is drawn from the same distribution as the old one's, it
exceeds it half the time and the median overshoot is zero. The clearance rate of
0.48 is the same fact stated as a rate.

So "legs take out the previous high about half the time" is not structure. The
only question with content is whether it is *exactly* half.

## It is slightly less than half, and matching volatility does not explain it

Day-shuffled bars, compared inside the real arm's own bins, with a **day-block**
bootstrap:

| frame | source | kind | distance-matched | + volatility-matched | legs |
|---|---|---|---:|---:|---:|
| 1h | wick | origin | -0.0425 `[-0.0561, -0.0311]` | **-0.0441** `[-0.0579, -0.0325]` | 6,364 |
| 1h | wick | pivot | -0.0152 `[-0.0246, -0.0043]` | **-0.0160** `[-0.0273, -0.0050]` | 10,782 |
| 1h | wick | zigzag | -0.0114 `[-0.0154, -0.0078]` | **-0.0108** `[-0.0145, -0.0072]` | 68,977 |
| 1h | wick | fractal | +0.0044 `[-0.0015, +0.0100]` | +0.0035 `[-0.0028, +0.0090]` | 51,945 |
| 1h | body | origin | -0.0249 | **-0.0264** `[-0.0408, -0.0149]` | 6,364 |
| 1h | body | pivot | -0.0143 | **-0.0169** `[-0.0276, -0.0065]` | 10,279 |
| 1h | body | zigzag | -0.0041 | -0.0050 `[-0.0106, +0.0003]` | 27,786 |
| 1h | body | fractal | +0.0080 | **+0.0069** `[+0.0014, +0.0126]` | 47,101 |
| 15m | wick | origin | -0.0232 | **-0.0239** `[-0.0302, -0.0183]` | 24,991 |
| 15m | wick | pivot | -0.0068 | **-0.0075** `[-0.0140, -0.0015]` | 42,912 |
| 15m | wick | zigzag | -0.0058 | **-0.0056** `[-0.0074, -0.0037]` | 278,023 |
| 15m | wick | fractal | +0.0052 | **+0.0050** `[+0.0029, +0.0074]` | 210,341 |

**There is a ladder in it.** The shortfall grows with how selective the
definition is: a two-bar fractal is *positive* at +0.004 to +0.007, a 1.5 ATR
zigzag reads -0.005 to -0.011, a 15/5 swing pivot -0.007 to -0.017, and the
operator's confirmed origin - which requires a completed 3 ATR thrust before
the leg is even measured - reads **-0.024 to -0.044**. That ordering is the
same on both clocks and both sources.

The obvious competing explanation is volatility decay: the barrier is a
distance in ATR of the turn's bar, real ATR mean-reverts and a shuffled series'
does not, so a turn formed in a burst should be followed by a quieter leg that
covers less of that ATR. **It is not the explanation** - crossing the distance
bins with the volatility quantile at the turn moves every figure by less than
0.003, and in the wrong direction as often as the right one.

What the selectivity ladder suggests instead is **exhaustion**: the more a
definition requires a move to have already happened, the further the next leg
falls short. The origin's leg starts after 3 ATR is already spent.

Two caveats, both working against the finding rather than for it:

* the shuffled arm re-bases days to join up, so it has **no weekend gaps** -
  and a gap can jump a prior turn point, which would make the real arm clear
  *more* often, not less;
* the effect is 0.5 to 4.4 points on a rate whose base is 0.42 to 0.50. It is
  not a side. Turning it into one means a trade that profits when a leg falls
  short, priced against the **geometric** fair value rather than against the
  shuffled rate, and [`level-shield.md`](level-shield.md) already closed the
  nearest version of that claim. **That measurement has not been made** and is
  the one thing this page leaves open.

## Volatility around a turn

For every turn point, the true range of each bar from 24 before to 24 after, in
units of the ATR **24 bars before** the turn - not at it, because dividing by
the ATR at the turn is what makes every such event study read as a spike
followed by decay. The denominator is fixed before the window opens.

1h swing pivots, 864 turns on EURUSD alone; the pooled shape is the same:

```
 -24 1.23   -20 1.05   -16 0.93   -12 0.85   -10 0.84    -8 0.89    -4 1.01
  -2 1.06    -1 1.28    +0 1.73    +1 1.41    +2 1.19    +4 1.06    +8 0.97
 +10 0.86   +12 0.86   +15 0.85   +18 1.00   +20 1.02   +22 1.13   +24 1.28
```

**Volatility collapses into a turn, spikes on it, and collapses again.** It
falls to **0.84** of its level a day earlier about ten bars before the turn,
rises through 1.06 and 1.28 on the two bars before, prints **1.73** on the turn
bar itself, and is back to 0.85 within fifteen bars.

**The wings are the clock, not the turn.** At 1h, bars -24 and +24 are the same
hour of day, and they read 1.23 and 1.28. That symmetry is the diurnal cycle
showing through, which is a useful internal check on the profile and a warning
against reading anything into its ends - `seasonality-belongs-on-q` and the
continuity result in [`persistence.md`](persistence.md), where the session clock
is the whole predictor, are the same phenomenon.

This agrees with `reactive-zones.md`'s finding that ATR *rises* into a level
sequence, and sharpens it: the rise is two bars long and sits on top of a
trough.

## Clustering, PCA, binning and the graph, scored on one scale

The operator asked for all four and for a comparison. Every one is asking the
same thing - *is there a region of turn-point space where the clearance rate is
not what the distance implies* - so each is scored by **the largest gap it
finds**, against **two** floors:

* a **permuted label**, shuffled inside each distance decile, which keeps the
  one relationship not in question and controls the multiplicity of picking the
  best of 64 cells;
* the **same method on a day-shuffled market**, which is the only arm that can
  name a *mechanical* finding. `shuffled-twin-names-the-mechanical-observables`
  is why both are needed: a permuted floor cannot tell you that a cell is
  nearly deterministic by construction.

1h, wick, five markets, 8 years:

| kind | method | real gap | permuted floor | **shuffled arm** |
|---|---|---:|---:|---:|
| pivot | bins: reach x regime x efficiency | -0.0905 | 0.1054 | -0.1479 |
| pivot | bins: size x wick x body | -0.1713 | 0.0917 | - |
| zigzag | bins: reach x regime x efficiency | **+0.6281** | 0.0469 | **+0.5838** |
| zigzag | bins: size x wick x body | +0.2024 | 0.0559 | +0.2245 |
| zigzag | k-means, k=5 | 0.0544 | 0.0043 | **0.0745** |
| fractal | bins: reach x regime x efficiency | +0.0776 | 0.0607 | **+0.1611** |
| fractal | bins: size x wick x body | -0.1961 | 0.0772 | +0.1867 |
| fractal | k-means, k=5 | 0.0452 | 0.0050 | **0.0689** |
| origin | bins: reach x regime x efficiency | +0.1095 | **0.1145** | -0.1329 |
| origin | bins: size x wick x body | +0.0589 | **0.0936** | -0.1099 |
| origin | k-means, k=5 | 0.0207 | 0.0148 | 0.0157 |

**Read the last column.** The zigzag's +0.6281 looks enormous against a 0.0469
permuted floor - and a day-shuffled market gives +0.5838 by the same method, so
it is the zigzag's own construction and not the market. The fractal's gaps and
both k-means results are *larger on shuffled data*. The origin's two gaps sit
**below their own permuted floors**. Nothing survives.

### What the components actually are

PCA on twelve columns describing a turn - the candle, the approach, the
volatility state, the hour and the distance to the barrier:

| component | variance | what loads on it |
|---|---:|---|
| PC1 | 0.257 | `approach_atr` +0.52, `approach_efficiency` +0.47, `reach_atr` +0.45, `pre_vol` +0.32 |
| PC2 | 0.161 | `body_share` +0.69, `reject_wick` -0.60, `opposite_wick` -0.24 |
| PC3 | 0.119 | `hour_sin` -0.49, `regime` +0.46, `bar_size` +0.41 |
| PC4 | 0.098 | `pre_vol` +0.62, `hour_sin` +0.50 |

Four components carry **64%**, and they are interpretable: **the approach
geometry, the candle, the clock-and-regime, and the pre-turn volatility.** That
is a real and useful description of what varies between turn points.

It predicts nothing. Each component's AUC on clearance, **within distance
strata**, across the four definitions: **0.4192 to 0.5431 on the real arm**,
and **0.4735 to 0.5819 on the shuffled one** - the single best reading of the
whole exercise is a shuffled market's PC2 at 0.5819.

### The graph

Degree, not centrality: how many of the next 50 turns land within 0.25 ATR of
this one, against a placebo node 1 to 3 ATR away with the same window.

Across kinds and the five markets the difference runs **-0.029 to +0.046**,
every value inside its own +/-0.054 to +/-0.070 interval. Pooled it is a flat
zero.

That is the one statistic this family had left. [`level-graph.md`](level-graph.md)
closed *centrality* on a level graph - real below its hardest null in **226 of
231** cells, with the null arms producing about 27x the real effect - and
[`topology.md`](topology.md) closed persistent homology, which it found was
reading volatility clustering. Degree over turn points was the watchedness
reformulation `a-magnet-is-a-shared-reference` leaves open, and it is null too.

### The grammar

Each turn as one letter against the previous turn **on its own side**: a low
above the last low is `HL`, below it `LL`. Within a side the alphabet is one
bit, and an order-1 Markov model saves **+0.000 to +0.013 bits** of it across
every definition and market; the `higher` share runs 0.456 to 0.575.

**Measured across sides it reads +1.1213 bits, and that is the apparatus.** A
turn sequence alternates by construction, so the previous letter says with
certainty whether the next comes from the low pair or the high pair - exactly
one bit of a two-bit alphabet, free. An effect twenty times the size of the one
`grammar.md` found for a real bar-shape grammar was the tell.

## What this closes, and what it does not

**Closed:** that a turn point's description - its candle, its approach, its
volatility state, its hour, its position - says anything about whether the next
leg clears the previous turn point, beyond the distance to it. Closed by four
methods, each against two floors, with the shuffled market beating the real one
on most cells.

Also closed: a grammar over HH/HL/LH/LL; degree over turn points as a
watchedness measure; turns arriving in clusters once the source is a body.

**Measured and standing:** the leg size distribution; the previous turn point as
the median leg target; the volatility profile around a turn; the four-component
description of what varies between turns; and the **selectivity ladder in the
penetration shortfall**, from +0.005 on a two-bar fractal to -0.044 on a
confirmed origin, matched on distance and volatility, on both clocks and both
sources.

**Open, and the one thing worth doing next:** pricing that shortfall. A rate
difference against a shuffled market is not a trade; the trade is a position
that profits when a leg falls short of the prior turn point, scored in R against
the geometric fair value, with the spread charged. Everything needed for it is
in `penetrate()` already.
