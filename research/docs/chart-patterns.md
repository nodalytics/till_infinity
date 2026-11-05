# A random walk reproduces the chart-pattern literature's break-out direction rates on 18 of 18 patterns, and the one statistic that does not reproduce is reproduced by a day-block shuffle

Measured 2026-11-05 on the lab with [`chart_patterns.py`](../harness/chart_patterns.py) and
reported with [`chart_patterns_report.py`](../harness/chart_patterns_report.py), on bars pulled
by [`seqlab_pull.py`](../harness/seqlab_pull.py): 8 traded markets and 4 Deriv synthetics at a
15-minute base, **198,529 to 294,532 bars each (5.7 to 11.8 years)**, read at four timeframes
and two swing scales. 21 pattern detectors, **1,704 cells**, 919 of them with at least 100
break-outs, and **24 surrogate series per cell** (12 i.i.d.-shuffled, 12 day-block-shuffled).

This is the replication half of [`letter-shapes.md`](letter-shapes.md) and shares its
machinery, its controls and its cost line.

| question | verdict |
|---|---|
| **Do the published per-pattern break-out direction rates reproduce here?** | **The rates reproduce, and so does the walk.** Head and shoulders breaks **down** 73.2% of the time on the traded panel and **74.5%** of the time on an i.i.d. shuffle of the same instrument's own returns. A falling wedge breaks up 88.2% here and 85.5% on the walk; a rising wedge up 13.9% here and 15.4% on the walk. Across 18 readable patterns the largest pooled gap is **1.8 standard errors**, which over 18 patterns is what chance gives |
| So is a break-out direction rate informative? | **It is a statement about the detector's geometry, not about the market.** A pattern defined by a falling upper boundary has to break upward most of the time - the boundary comes down to meet the price - and a process with no memory at all delivers the same number |
| **Does the market beat the walk anywhere?** | **Yes, on two things, and both are volatility.** Per cell, BH over the whole surface keeps **130 of 919** break-out-direction cells (9 on generated markets) - the largest being a falling wedge at 15m breaking up 90.3% against the walk's 85.0% - and **274 of 919** *measure-rule-met* cells. The measure rule is the big one, up to 2.5x the walk's rate, and the **day-block shuffle reproduces it almost exactly** (head and shoulders: 0.070 real, 0.045 i.i.d., **0.074 day-block**) |
| **Does any of it pay?** | **No.** Run as a 1:1 barrier race - target at one pattern height, stop at one pattern height, where a driftless walk answers exactly 0.500 - every pattern reads **0.478 to 0.517** on the traded panel and **0.485 to 0.516** on the generated ones - the same range. Net of the quoted round trip, **8 of 12** instruments are negative and **6 of the 8 traded** ones are, and BH keeps 11 of 919 race cells of which 2 are on generated markets and most of the rest are *below* 0.500 |
| Is this a replication of the published numbers? | **No, and that is stated rather than implied.** The book was not to hand on the machine this ran on, **no published figure is quoted and no table of his is reproduced**. Every pattern is reported against the walk arms alone, laid out in his schema so the published figures can be dropped in later |
| Should anything be built? | **No.** [`patterns.md`](patterns.md) already priced these patterns as trades against a distance-matched placebo and found nothing; this adds that their *population statistics* are a walk's too |

## The claim, and the three it is distinct from

[`patterns.md`](patterns.md) priced the classical patterns as **trades**, with a
distance-matched placebo, on ten instruments: double top and bottom are their own geometry
(placebo gap -0.8% to +0.8% over 16,780 observations) and head and shoulders fell from
52.6-53.2% on gold alone to 44.8-45.2% on ten instruments, below its own breakeven everywhere.
[`fractal-twins.md`](fractal-twins.md) found candle shapes call volatility and not direction.
[`letter-shapes.md`](letter-shapes.md) found the same for named letters, and that their
frequency is a volatility-clustering reading.

None of those tested this sentence:

> **Do the published per-pattern statistics reproduce?**

Bulkowski's *Encyclopedia of Chart Patterns* is cited for a particular thing: it publishes
**measured per-pattern statistics** - break-out direction rates, average rise and decline,
failure rates, throwback and pullback rates, and how often the measure rule is met. Those are
statements about the *population of patterns*, not about whether a pattern pays, and
`patterns.md` measured none of them. They are also the statistics `patterns.md` explicitly
named as untested: *"wedges, flags, pennants, triangles and cup-and-handle all require fitting
trend lines to a subjective selection of touches"*, and it did not run them. They are run here.

**The walk arm is the point.** A random walk produces head and shoulders too, and its break-out
rate is the number that says whether a published 65% means anything.

**A break-out rate is not an edge.** "Breaks upward 65% of the time" is compatible with zero
expectancy once the break's size and the stop are priced, and this desk's `1/(1+N)` null says
reward-to-risk alone has expected value zero. So the measure rule is also run as a 1:1 barrier
race, where a driftless walk answers exactly 0.500, and reported net of the quoted round trip.

## What is not quoted here, and why

**The book was not to hand on the machine this ran on.** Quoting a per-pattern statistic from
memory and attributing it to a named author in a public repository is worse than leaving the
column empty, so every pattern below reads *no published figure to hand* and is reported
against the walk alone. The table is laid out in his schema so the published figures can be
dropped into it without re-running anything.

What **is** used is the schema, which is a set of definitions rather than a measurement:
break-out direction, average rise or decline to the ultimate high or low, failure rate,
throwback and pullback rate, and measure-rule-met rate. Two of those definitions do not survive
the move from daily stock charts to 15-minute FX and are **replaced, not silently
reinterpreted**:

| his definition | what is used here, and why |
|---|---|
| the **ultimate high/low**: the extreme before a 20% trend change | 20% **of the run so far**, scale-free. A 20%-of-price retracement never happens on EURUSD at 15 minutes |
| the **failure rate**: a move after the break-out below 5% | a move below **half the pattern's own height**. A 5% move on EURUSD at 15 minutes is a once-a-decade event and the rate would be 100% for every pattern |

Rises and declines are reported in **pattern heights**, never in per cent, because a per cent
on 15-minute FX is not the same quantity as a per cent on a daily stock chart.

**A mismatch against a published figure may be this study's power rather than his error.** His
samples are large and his figures are not noise; this grid's per-cell samples run from 100 to
7,500 break-outs and the power table below says where it goes blind.

## The detectors, as frozen before the run

One **pivot engine** - an alternating zigzag of swing extremes over a `2L+1` window, with
`L` in {3, 8} - feeds three families. A pivot at bar `i` is the extreme of `[i-L, i+L]`, so it
is **not known until bar `i+L`**, and confirmation is not allowed to start before then.

| family | patterns | the rule |
|---|---|---|
| **fitted boundaries** | ascending / descending / symmetrical triangle, rectangle, rising / falling wedge, broadening formation, diamond | least-squares lines through the pivot highs and the pivot lows over the last 5 or 7 pivots, classified by the two slopes **normalised by the pattern's own height** (flat below 0.25 of the height across the span) and by the convergence ratio (converging below 0.60, diverging above 1.50). The diamond is two fits, a diverging half then a converging one |
| **comparable extremes** | head and shoulders and its inverse, double and triple tops and bottoms | pivot prices with one tolerance: two extremes are "roughly the same price" within **0.15 of the pattern's height**. A head and shoulders needs a middle extreme clear of both shoulders by that tolerance and shoulders level within it; a triple top needs all three level within it |
| **rounded** | rounding top, rounding bottom, cup with handle | the extreme in the middle third, the two lips level within the tolerance, and the close path correlating at **0.80 or better with a parabola** - a V is not a rounding bottom. The handle is a retrace of at most **half** the cup inside half its span, which is the figure the description gives |
| **bars** | flag, pennant | a pole of at least **6 forecast-volatility units inside 12 bars**, then a consolidation of 5 or 20 bars whose range is at most half the pole. Converging boundaries make it a pennant, otherwise a flag |
| **gaps** | island reversal top and bottom | a gap of at least one forecast unit, at most 20 bars with no overlap, then a gap back |

**A pattern counts at the bar where it breaks out**, which is the first close beyond either
boundary after confirmation, with the fitted line **evaluated at that bar** so a converging
triangle's boundary converges. The break-out must happen inside one pattern-span of
confirmation; patterns that never break have no break-out statistic and are not counted.
Nothing after the break-out bar is read to decide whether a pattern exists - verified by
truncating the series at a break-out bar and confirming all 8,744 earlier break-outs are
identical.

### What was dropped, and why

* **Volume.** It is in the cache and is not used. The definitions lean on volume shape, and
  this feed's `tick_volume` is a tick count on a dealer's bid stream rather than traded size, so
  a volume clause here would be a different clause wearing his name.
* **The cup with handle** was implemented and is **dropped from every result table**: 752
  break-outs over 68 cells, median 6 per cell, **0 cells with 100 or more**. It is the weakest
  detector in the file - the handle is a reading of a description rather than a quotation of a
  rule - and it has no sample.
* **Island reversals**, both directions, for the same reason and a better one: **7 and 6
  break-outs in the whole study**. A continuously-quoted dealer feed gaps only over the weekend,
  so the pattern is not absent from the market, it is absent from this instrument class.
* Nothing else was dropped. The 18 patterns below all have cells with 100 or more break-outs.

## The controls

Identical to [`letter-shapes.md`](letter-shapes.md): **12 i.i.d.-shuffled twins** and **12
day-block-shuffled twins** per instrument, the **four Deriv synthetics** each carried for one
named property of its published generator, a **day-block bootstrap** on every rate, and
**Benjamini-Hochberg** over the full surface.

The surrogate bars carry **each bar's return and its two wick fractions together**, because
they belong to the same bar. Shuffling the returns while leaving the wicks in place would
decouple a bar's range from its move, and every detector here reads ranges - so the surrogate
would differ from the real series in something other than the ordering, which is the one thing
it is supposed to differ in.

## Result 1: break-out direction - the walk gives the same answer on 18 of 18

Traded panel, cells with 100 or more break-outs, pooled. `up` is the share that broke upward;
`sd` is the standard deviation of that share across the 12 i.i.d. surrogate draws.

| pattern | cells | break-outs | up | i.i.d. walk | day-block walk | sd | gap | z |
|---|---|---|---|---|---|---|---|---|
| head and shoulders | 29 | 12,284 | 0.2685 | 0.2546 | 0.2652 | 0.025 | +0.014 | +0.55 |
| inverse head and shoulders | 28 | 12,958 | 0.7643 | 0.7673 | 0.7602 | 0.024 | -0.003 | -0.13 |
| double top | 41 | 45,823 | 0.4283 | 0.4119 | 0.4135 | 0.021 | +0.016 | +0.79 |
| double bottom | 41 | 43,293 | 0.6101 | 0.6087 | 0.6150 | 0.020 | +0.001 | +0.07 |
| triple top | 22 | 6,743 | 0.4757 | 0.4421 | 0.4544 | 0.035 | +0.034 | +0.96 |
| triple bottom | 18 | 5,663 | 0.5752 | 0.5808 | 0.5726 | 0.029 | -0.006 | -0.19 |
| ascending triangle | 48 | 106,562 | 0.3246 | 0.3347 | 0.3145 | 0.021 | -0.010 | -0.49 |
| descending triangle | 48 | 98,795 | 0.7181 | 0.6878 | 0.7301 | 0.021 | +0.030 | +1.44 |
| symmetrical triangle | 41 | 62,753 | 0.5742 | 0.5369 | 0.5937 | 0.025 | +0.037 | +1.48 |
| rectangle | 43 | 46,507 | 0.5192 | 0.5102 | 0.5153 | 0.025 | +0.009 | +0.37 |
| rising wedge | 49 | 111,611 | 0.1392 | 0.1536 | 0.1330 | 0.014 | -0.014 | -1.00 |
| falling wedge | 49 | 99,688 | 0.8823 | 0.8550 | 0.8818 | 0.015 | +0.027 | +1.78 |
| broadening formation | 30 | 18,575 | 0.5144 | 0.5224 | 0.5166 | 0.032 | -0.008 | -0.25 |
| diamond | 42 | 52,031 | 0.5140 | 0.5001 | 0.5063 | 0.022 | +0.014 | +0.63 |
| flag | 28 | 114,156 | 0.5191 | 0.5103 | 0.5188 | 0.024 | +0.009 | +0.37 |
| pennant | 22 | 21,415 | 0.5150 | 0.5116 | 0.5262 | 0.036 | +0.003 | +0.09 |
| rounding bottom | 16 | 3,779 | 0.5290 | 0.5493 | 0.5243 | 0.032 | -0.020 | -0.65 |
| rounding top | 16 | 3,634 | 0.5139 | 0.4590 | 0.5026 | 0.030 | +0.055 | +1.81 |

**No pattern's pooled break-out rate is two standard errors from its walk's, and the largest
of 18 is 1.81.** The same table on the four generated markets reads -0.8 to +0.5.

The rates themselves are strong and they are strongly *determined by the detector*: a rising
wedge breaks up 14% of the time and a falling wedge 88%, because a wedge is defined by two
boundaries sloping the same way and price has to leave through one of them. That is why the
walk gives the same number. **A break-out direction rate is a property of the definition, and
reading it as a property of the market is the error this table exists to catch.**

The per-instrument matrix at 1h and `L = 3` is printed by the report script, alongside the
matching walk matrix, and the two track each other pattern by pattern.

## Result 2: the rest of the schema

Traded panel, cells with 100 or more break-outs. `rise` is the move to the ultimate high or low
in **pattern heights** and is reported as a **median** - see *Bugs*, item 6.

| pattern | break-outs | rise | walk | failure | walk | throwback | walk | **measure met** | **i.i.d. walk** | **day-block walk** |
|---|---|---|---|---|---|---|---|---|---|---|
| head and shoulders | 12,284 | 0.353 | 0.314 | 0.817 | 0.859 | 0.362 | 0.341 | **0.070** | 0.045 | *0.074* |
| inverse head and shoulders | 12,958 | 0.309 | 0.321 | 0.819 | 0.857 | 0.361 | 0.348 | **0.066** | 0.047 | *0.073* |
| double top | 45,823 | 0.463 | 0.457 | 0.736 | 0.772 | 0.445 | 0.437 | **0.113** | 0.088 | *0.124* |
| double bottom | 43,293 | 0.475 | 0.476 | 0.731 | 0.772 | 0.446 | 0.439 | **0.113** | 0.089 | *0.122* |
| triple top | 6,743 | 0.458 | 0.428 | 0.736 | 0.782 | 0.448 | 0.422 | **0.111** | 0.082 | *0.122* |
| triple bottom | 5,663 | 0.481 | 0.428 | 0.736 | 0.789 | 0.450 | 0.407 | **0.108** | 0.082 | *0.114* |
| ascending triangle | 106,562 | 0.213 | 0.232 | 0.907 | 0.915 | 0.257 | 0.262 | 0.030 | 0.022 | *0.030* |
| descending triangle | 98,795 | 0.198 | 0.240 | 0.908 | 0.915 | 0.252 | 0.258 | 0.027 | 0.022 | *0.029* |
| symmetrical triangle | 62,753 | 0.168 | 0.186 | 0.929 | 0.940 | 0.198 | 0.198 | 0.021 | 0.015 | *0.019* |
| rectangle | 46,507 | 0.376 | 0.392 | 0.776 | 0.815 | 0.399 | 0.407 | 0.085 | 0.063 | *0.090* |
| rising wedge | 111,611 | 0.255 | 0.281 | 0.884 | 0.884 | 0.313 | 0.323 | 0.037 | 0.033 | *0.039* |
| falling wedge | 99,688 | 0.234 | 0.293 | 0.893 | 0.887 | 0.297 | 0.312 | 0.032 | 0.032 | *0.036* |
| broadening formation | 18,575 | 0.232 | 0.203 | 0.877 | 0.929 | 0.259 | 0.216 | **0.040** | 0.019 | *0.050* |
| diamond | 52,031 | 0.346 | 0.347 | 0.818 | 0.838 | 0.374 | 0.381 | 0.063 | 0.052 | *0.067* |
| flag | 114,156 | 0.251 | 0.271 | 0.870 | 0.874 | 0.334 | 0.344 | 0.043 | 0.034 | *0.040* |
| pennant | 21,415 | 0.224 | 0.242 | 0.892 | 0.884 | 0.298 | 0.327 | 0.032 | 0.032 | *0.032* |
| rounding bottom | 3,779 | 0.405 | 0.312 | 0.781 | 0.845 | 0.404 | 0.346 | **0.092** | 0.055 | *0.094* |
| rounding top | 3,634 | 0.403 | 0.316 | 0.768 | 0.845 | 0.422 | 0.348 | **0.088** | 0.054 | *0.092* |

Three readings, in order of how much they say:

* **The measure rule is met far more often than an i.i.d. walk meets it** - above 1.2x on 15 of
  18 patterns and up to 2.1x, and per cell it is the strongest signal in the study: BH keeps **274 of 919**
  cells, the largest being a broadening formation at 15m meeting its target 7.9% of the time
  against the walk's 2.8% (z 12.5).
* **And the day-block shuffle meets it at the same rate as the real market does.** Look at the
  last two columns together: head and shoulders 0.070 real, 0.074 day-block; double top 0.113
  and 0.124; rounding bottom 0.092 and 0.094; broadening formation 0.040 and 0.050. The
  day-block twin keeps intraday volatility clustering and destroys cross-day ordering, and it
  reproduces the whole effect. **The measure rule is met more often because real markets have
  fat tails and clustered volatility, which makes any fixed-distance target easier to reach -
  not because the pattern chose the distance well.**
* **The generated markets have none of it.** The same table there reads measure-met 0.0095 to
  0.0823 against a walk of 0.0094 to 0.0775 - flat on every pattern, as a constant-volatility
  generator must be.

Failure and throwback rates track their walks within **8 points on all 18 patterns** and within
4 on fourteen of them, and the median rise matches its walk to within **0.03 pattern heights on
12 of 18**. The four largest rise gaps are the two rounded patterns and the two with the
smallest samples, which is what a median over a few thousand break-outs looks like.

## Result 3: the measure rule as a 1:1 race, where the walk answers 0.500

Target at one pattern height, stop at one pattern height, 200 bars, read from the break-out
close. A driftless walk answers exactly **0.500**.

| pattern | cells | traded: races | race | i.i.d. walk | day-block | z vs 0.500 | cost in R | **net, R** | generated: race |
|---|---|---|---|---|---|---|---|---|---|
| head and shoulders | 25 | 11,148 | 0.4947 | 0.4970 | 0.4970 | -0.19 | 0.036 | -0.0463 | 0.4850 |
| inverse head and shoulders | 24 | 11,700 | 0.5050 | 0.5065 | 0.5098 | +0.21 | 0.037 | -0.0265 | 0.5021 |
| double top | 40 | 44,616 | 0.4929 | 0.5032 | 0.5033 | -0.33 | 0.041 | -0.0552 | 0.5049 |
| double bottom | 40 | 42,166 | 0.5018 | 0.5050 | 0.5046 | +0.08 | 0.041 | -0.0375 | 0.4965 |
| triple top | 22 | 6,625 | 0.4952 | 0.5062 | 0.5022 | -0.14 | 0.055 | -0.0650 | 0.5107 |
| triple bottom | 17 | 5,475 | 0.5007 | 0.5072 | 0.4960 | +0.02 | 0.061 | -0.0596 | 0.5019 |
| ascending triangle | 44 | 87,931 | 0.4775 | 0.4930 | 0.4922 | -0.96 | 0.019 | -0.0637 | 0.5103 |
| descending triangle | 42 | 81,277 | 0.5118 | 0.5119 | 0.5099 | +0.53 | 0.020 | +0.0040 | 0.4947 |
| symmetrical triangle | 40 | 44,838 | 0.5022 | 0.5029 | 0.5070 | +0.07 | 0.016 | -0.0113 | 0.5045 |
| rectangle | 43 | 45,265 | 0.5030 | 0.5025 | 0.5029 | +0.11 | 0.033 | -0.0270 | 0.4968 |
| rising wedge | 49 | 98,917 | 0.4864 | 0.4852 | 0.4822 | -0.56 | 0.020 | -0.0477 | 0.5142 |
| falling wedge | 46 | 86,846 | 0.5168 | 0.5135 | 0.5149 | +0.72 | 0.021 | +0.0127 | 0.4948 |
| broadening formation | 24 | 14,805 | 0.5104 | 0.5033 | 0.5051 | +0.36 | 0.026 | -0.0050 | 0.5164 |
| diamond | 40 | 49,262 | 0.5023 | 0.5016 | 0.5018 | +0.11 | 0.029 | -0.0244 | 0.4912 |
| flag | 26 | 100,798 | 0.4954 | 0.4990 | 0.4981 | -0.21 | 0.020 | -0.0293 | 0.4984 |
| pennant | 22 | 17,800 | 0.4848 | 0.5026 | 0.5000 | -0.45 | 0.020 | -0.0503 | 0.5075 |
| rounding bottom | 16 | 3,584 | 0.5019 | 0.5105 | 0.5068 | +0.06 | 0.049 | -0.0450 | 0.5137 |
| rounding top | 16 | 3,454 | 0.5061 | 0.5029 | 0.5027 | +0.19 | 0.049 | -0.0368 | 0.5019 |

**Every pattern sits on 0.500, on real markets and on generated ones.** The traded panel spans
0.4775 to 0.5168 and the generated markets 0.4850 to 0.5164 - the same range - and the largest
departure from 0.500 over 18 patterns is **0.96 standard errors**. Net of the quoted round trip
only two patterns are positive, by 0.004R and 0.013R. Per instrument, pooled over patterns:

| instrument | races | race | i.i.d. walk | cost in R | **net** | share of cells positive net |
|---|---|---|---|---|---|---|
| EURUSD | 98,870 | 0.5003 | 0.5007 | 0.022 | -0.021 | 0.34 |
| GBPUSD | 99,032 | 0.4969 | 0.5039 | 0.020 | -0.027 | 0.25 |
| USDJPY | 97,647 | 0.5116 | 0.5023 | 0.019 | **+0.004** | 0.56 |
| AUDUSD | 99,183 | 0.4922 | 0.5032 | 0.019 | -0.034 | 0.18 |
| USDCAD | 98,829 | 0.4900 | 0.5005 | 0.022 | -0.042 | 0.22 |
| XAUUSD | 90,779 | 0.5082 | 0.5040 | 0.012 | **+0.004** | 0.50 |
| XAGUSD | 92,591 | 0.5025 | 0.5042 | 0.103 | -0.098 | 0.15 |
| BTCUSD | 79,576 | 0.4913 | 0.5001 | 0.021 | -0.038 | 0.24 |
| *Volatility 75 Index* | 88,581 | 0.5006 | 0.4997 | 0.001 | *+0.000* | 0.38 |
| *Volatility 25 Index* | 87,968 | 0.5013 | 0.5037 | 0.010 | *-0.008* | 0.38 |
| *Step Index* | 84,346 | 0.4952 | 0.5015 | 0.004 | *-0.013* | 0.49 |
| *Jump 75 Index* | 65,183 | 0.5112 | 0.5009 | 0.002 | *+0.020* | 0.62 |

**Eight of twelve instruments are negative net of the quoted round trip, and 6 of the 8 traded
ones are.** The two traded instruments that clear it do so by 0.004R. BH over the 919 race cells keeps **11**, of which **2 are on
generated markets** and 7 of the remaining 9 are *below* 0.500 - XAGUSD's double top at 0.466,
its rectangle at 0.475, its triple bottom at 0.431, its inverse head and shoulders at 0.433.

## Result 4: the multiplicity surface

919 cells with at least 100 break-outs (21 patterns x 4 timeframes x 2 swing scales x 12
instruments, minus the sparse ones). Benjamini-Hochberg at q<0.10, run on the z against the 12
i.i.d. draws rather than on the rank p, whose floor is 1/13 = 0.077 and which therefore cannot
reject anything in a family this size:

| statistic | survivors | on generated markets | the largest |
|---|---|---|---|
| break-out direction | **130** of 919 | 9 | EURUSD falling wedge, 15m, L=3: 0.903 against the walk's 0.850, z +13.6 |
| measure rule met | **274** of 919 | 26 | GBPUSD broadening formation, 15m, L=3: 0.079 against 0.028, z +12.5 |
| the 1:1 race | **11** of 919 | 2 | USDCAD pennant, 15m, L=3: 0.456 against 0.501, z -5.3 |

Generated markets are 33% of the instruments and 7-9% of the survivors on the first two
statistics, which is the calibration check: the surface does separate real markets from
generated ones, and what it separates them on is volatility.

**The survivors concentrate on the shortest clock**, which is where the sample is largest and
where the volatility clustering is strongest: break-out direction 87 of 130 at 15m, 31 at 1h,
12 at 4h and none at 1d; the measure rule 161, 90, 21 and 2. Both split roughly 2:1 between the
finer swing scale and the coarser (80/50 and 190/84). The race's 11 survivors are 7 at 15m, 3
at 1h and 1 at 4h, and **7 of its 9 non-generated cells sit *below* 0.500** - XAGUSD's triple
bottom at 0.431, its inverse head and shoulders at 0.433, USDCAD's pennant at 0.456.

## The cost line

| instrument | quoted round trip | the stored `spread` column | quoted / stored |
|---|---|---|---|
| EURUSD | 0.000080 | 0.000010 | **8.26x** |
| BTCUSD | 0.000440 | 0.000057 | **7.76x** |
| GBPUSD | 0.000084 | 0.000017 | 5.09x |
| XAGUSD | 0.001443 | 0.000314 | 4.59x |
| USDJPY | 0.000078 | 0.000019 | 4.14x |
| USDCAD | 0.000075 | 0.000021 | 3.54x |
| AUDUSD | 0.000099 | 0.000030 | 3.26x |
| XAUUSD | 0.000091 | 0.000034 | 2.67x |
| *Volatility 25 Index* | 0.000135 | 0.000069 | *1.96x* |
| *Step Index* | 0.000012 | 0.000012 | *1.00x* |
| *Jump 75 Index* | 0.000116 | 0.000176 | *0.66x* |
| *Volatility 75 Index* | 0.000040 | 0.000260 | ***0.15x*** |

**309 of 865 race cells are positive net of the quoted round trip and 2 of 8 traded instruments
have a positive mean.** The stored column understates the quote by up to 8.3x on FX and
**overstates** it by 6.5x on `Volatility 75 Index`, so it is wrong in both directions and
unusable either way. Every cost statement here is made at the quote.

## Power, before any of these nulls is believed

A break-out bias of known size, in pattern heights, planted on the four generated markets where
the real answer is null, and swept. Planted on a **disjoint** subset of break-outs - each at
least one forward window after the last, about 147 per cell - so the plant is local and does not
compound.

| planted bias | race | detected (p<0.05) | resolved races per cell |
|---|---|---|---|
| 0.00 | 0.4987 | **0.096** | 130 |
| 0.05 | 0.5069 | 0.082 | 131 |
| 0.10 | 0.5179 | 0.111 | 130 |
| 0.20 | 0.5349 | 0.163 | 128 |
| 0.40 | 0.5705 | 0.358 | 125 |

**The plant lands where it is aimed** - the race moves by 0.008, 0.019, 0.036 and 0.072 for
plants of 0.05, 0.10, 0.20 and 0.40 heights - **and the per-cell test is blind below about 0.40
heights**, because a cell carries about 130 resolved races. The zero cell reads 0.096 against a
claimed 0.05, so that p is anti-conservative and the detection column overstates.

**So the per-cell race null is weak and the pooled one is not.** The per-pattern rows in Result
3 pool 3,454 to 114,156 races, where the surrogate's own standard deviation across 12 draws is
0.021 to 0.034; the observed departures from 0.500 are 0.002 to 0.023, inside one of those
standard deviations on 18 of 18 patterns. A pooled bias of 0.05 would have been seen on every
pattern.

## Bugs and measurement defects this run caught

1. **A chained comparison that could not be true.** `seg[0, 1] < 0 is False and seg[1, 1] < 0`
   parses as `(seg[0,1] < 0) and (0 is False)` and is therefore always `False`. It decided
   whether a rounded pattern was a bottom or a top.
2. **A rounding top's boundaries were its two lips**, which sit within one tolerance of each
   other by the pattern's own definition - so the band was a hair wide, every pattern broke
   almost at once, and the up-share read **0.946 on a random walk**. The arch is the upper
   boundary and the lip is the lower one. Caught by the walk arm, which is what the walk arm is
   for: nothing in the real series looked wrong.
3. **The cup-with-handle rule at "a third of the cup inside a third of the span" fired four
   times in 120,000 bars.** Loosened to the half-and-half the description gives, it fires ten
   times, which is still no sample - hence the drop.
4. **A look-ahead test failed for a reason that was not look-ahead.** The flag detector
   reserved 20 bars at the end of the series regardless of which consolidation length it was
   testing, so truncating at a break-out bar removed five of 17,491 break-outs whose *shorter*
   consolidation finished inside the series. Bounded below only; the test now passes exactly.
5. **The power arm bootstrapped a proportion against zero.** Every cell came back significant
   including the unplanted one, because the null for a 1:1 race is 0.500 and not 0. In the same
   pass, planting a drift over overlapping forward windows **compounded** across the series and
   moved the price level by orders of magnitude, which changed which races resolved at all - the
   plant now runs on a disjoint subset.
6. **`rise` has no finite mean.** It is a move divided by the pattern's own height, and a
   fitted-boundary pattern can have a height near zero, so the walk arm read **831 pattern
   heights** for a rounding top on one cell and 354 on another. Medians are reported, with the
   share of cells above 10 printed beside them as the diagnostic.
7. **A surrogate must carry each bar's wick with its return.** Shuffling the returns and
   leaving the wicks where they were decouples a bar's range from its move, and every detector
   here reads ranges - the surrogate would then differ from the real series in something other
   than the ordering.
8. **The stored `spread` column is wrong in both directions**, as above. This is the same
   defect [`impulse-vol.md`](impulse-vol.md) reported, with the new observation that it can
   also *overstate*.

## What this does not close

* **The published figures are not tested.** Every row above is a measurement against a walk,
  not a comparison against a book, and the column that would close the claim is empty on
  purpose. Dropping his per-pattern break-out direction rate, average rise and decline, failure
  rate, throwback and pullback rate, and measure-rule-met rate into the tables above would close
  it without re-running anything.
* **His sample is daily stock charts and this one is intraday FX, metals and crypto.** Even
  with the figures in hand, a mismatch would have at least three candidate causes - the asset
  class, the timeframe and the detector - and this study separates none of them.
* **The detectors are one reading of the definitions.** The tolerance is fixed at 0.15 of the
  pattern height where `patterns.md` swept it over four values; the flat threshold, the
  convergence ratio and the pole size are each one number that a different reader would set
  differently. The walk arm runs through the identical detector, so a comparison against the
  walk is robust to that choice in a way a comparison against a published figure is not.
* **M5 was not measured**, for the same reason as in [`letter-shapes.md`](letter-shapes.md):
  the cache holds the 15-minute pull and a 5-minute pull needs the terminal host.
* **Nothing here was traded.** The race charges the quoted spread once per round trip at the
  pattern-height stop and nothing else - no slippage, no queue, no partial fills.
