# Stretch signals for mean reversion: what works, and what z to use

Four harnesses, asking whether a "price is stretched" signal works for mean
reversion, what its AUC is, and - the question that turned out to be the useful
one - **what z-score an excursion actually reaches before it comes back**.

The short answer: as a *predictor* it does not work, with AUC capping at 0.518
and two thirds of that reproduced by a surrogate. As a *description* it gives a
number worth having, and that number is far lower than the thresholds these
ideas propose.

## The measurement that matters: z at the turn

The return rate to a displacement origin is high - **0.89 to 0.91 within 300
bars** on this definition, consistent with the 82% on record, slightly above it
because the target here is the origin bar's full band rather than its body
edge. What was never measured is how far price stretches first.

So: at the **turn** - the bar of furthest distance from the origin before price
re-enters its band - what is the z-score? One well-defined bar per excursion,
with no running maximum to confound it.

At a 100-bar window, signed away from the origin:

| frame | class | arm | n | q25 | median | q75 | q90 |
|---|---|---|---|---|---|---|---|
| 15m | fx majors | **returned** | 5,447 | -0.03 | **1.22** | 2.01 | 2.62 |
| 15m | fx majors | never returned | 558 | 1.80 | **2.24** | 2.80 | 3.32 |
| 15m | fx crosses | **returned** | 4,412 | 0.11 | **1.33** | 2.08 | 2.73 |
| 15m | fx crosses | never returned | 450 | 1.83 | **2.25** | 2.80 | 3.25 |
| 1h | fx majors | **returned** | 4,706 | 0.07 | **1.33** | 2.03 | 2.58 |
| 1h | fx majors | never returned | 477 | 1.75 | **2.11** | 2.61 | 3.26 |
| 1h | metals | **returned** | 1,157 | 0.06 | **1.28** | 2.10 | 2.69 |
| 1h | metals | never returned | 133 | 1.89 | **2.25** | 2.67 | 3.21 |
| 4h | fx majors | **returned** | 3,475 | 0.22 | **1.43** | 2.03 | 2.54 |
| 4h | fx majors | never returned | 409 | 1.70 | **2.06** | 2.56 | 3.13 |

**The excursions that come back turn at a median z near 1.3. The ones that
never come back reach a median near 2.2.** A high stretch selects *against* the
return, in every class and at every frame.

### What a 2.5 threshold would cost

The share of **returners** that ever reached each level:

| frame | class | z 2.0 | z 2.5 | z 3.0 |
|---|---|---|---|---|
| 15m | fx majors | 0.255 | 0.125 | 0.054 |
| 15m | fx crosses | 0.277 | 0.145 | 0.067 |
| 1h | fx majors | 0.260 | 0.116 | 0.044 |
| 1h | fx crosses | 0.285 | 0.137 | 0.053 |
| 4h | metals | 0.342 | 0.162 | 0.069 |

**An entry rule waiting for z 2.5 misses 85 to 89% of all the returns**, and
the ones it does catch are drawn from the population that is *least* likely to
return. That is the practical result of this document.

### The duration confound, measured rather than assumed

A slow return has more bars in which to reach a high z, so the median above is
a mixture. Median z at the turn by time to return, 1h:

| class | 1-10 bars | 11-30 | 31-100 | 101-300 |
|---|---|---|---|---|
| fx majors | 0.79 | 1.50 | 1.94 | 1.95 |
| fx crosses | 0.70 | 1.60 | 1.91 | 2.05 |
| metals | 0.82 | 1.47 | 1.94 | 2.17 |
| synth volatility | 0.94 | 1.62 | 1.98 | 2.08 |

Fast returns barely stretch at all, and the figure **plateaus near 1.95** for
anything taking more than 30 bars. So 1.95 is the honest number for a return
you would have time to trade, and the 1.3 median is pulled down by excursions
that reverse almost immediately.

### The threshold is meaningless without its window

Median z at the turn, 1h, for returners:

| class | 50 bars | 100 | 200 | 300 | 1 day | 1 week | 2 weeks |
|---|---|---|---|---|---|---|---|
| fx majors | 1.51 | 1.33 | 1.05 | 0.93 | 1.56 | 1.25 | 1.00 |
| fx crosses | 1.54 | 1.34 | 1.03 | 0.84 | 1.61 | 1.28 | 0.96 |
| metals | 1.49 | 1.28 | 1.10 | 0.98 | 1.53 | 1.27 | 1.04 |
| synth volatility | 1.70 | 1.54 | 1.20 | 0.98 | 1.68 | 1.46 | 1.10 |

The same excursion scores 1.5 against a 50-bar window and 0.93 against a
300-bar one, because a longer window has a larger deviation to divide by. **A z
threshold quoted without its window is not a specification.**

### Does the stretch predict *whether* it returns?

AUC of z at the turn against eventual return, 1h, by return window:

| class | 50 | 100 | 300 | 500 | twin |
|---|---|---|---|---|---|
| fx majors | 0.2382 | 0.2657 | 0.2364 | 0.2465 | 0.2338 |
| fx crosses | 0.2517 | 0.2687 | 0.2222 | 0.2485 | 0.2388 |
| metals | 0.2212 | 0.2353 | 0.2237 | 0.2533 | 0.2158 |
| synth volatility | 0.2900 | 0.2904 | 0.2713 | 0.2567 | 0.2563 |

Strongly **anti**-predictive, and the block-shuffled twin reads 0.216 to 0.256 -
so most of it is geometry: a bigger stretch is further from the origin and has
further to travel back. The live arm sits a little above the twin, which if
anything says the stretch is *less* anti-predictive than geometry alone implies.

## As a predictor of the next return, it does not work

The forward-return target, AUC of the reversion signal against the next 3-bar
return, tie-aware, spaced by the horizon, with the block-shuffled twin as the
baseline rather than 0.5.

Best cells at a 100-bar window:

| frame | class | centre | AUC | twin | edge |
|---|---|---|---|---|---|
| 15m | fx crosses | ema | 0.5180 | 0.5103 | **+0.0078** |
| 15m | fx majors | ema | 0.5144 | 0.5086 | +0.0057 |
| 3m | fx majors | mean | 0.5167 | 0.5112 | +0.0055 |
| 1h | metals | mean | 0.5002 | 0.5100 | **-0.0098** |

**AUC never exceeds 0.518, and the surrogate accounts for about two thirds of
the excess over 0.5.** The best edge over it is +0.008. Metals are consistently
**negative** - they trend rather than revert - at -0.0065 at 100 bars and
-0.0159 at 500.

### Centres, scales and spans all fail to rescue it

* **Centre.** A trailing mean, an EMA and a rolling least-squares line were all
  run. The regression centre - which removes the drift that
  [[trailing-zscore-fakes-reversion]] identified as the artefact - drives the
  edge to **zero or below** on FX (-0.0008 at 15m), confirming the diagnosis:
  the trailing mean's apparent edge *was* its lag.
* **Scale.** The **modified z-score** on the median and the median absolute
  deviation, scaled by 1.4826, is immune to news spikes by construction and
  changes the answer by **0.0005**. Immunity to outliers was never the problem.
* **Span.** Lookbacks as durations - 24 hours, 2 days, 3 days, 2 and 3 weeks -
  rather than bar counts, which is the matched comparison across frames. At 2
  days every edge falls inside +-0.008. The bar-count sweep peaks at 70 to 100
  bars and decays by 500.
* **Subjects.** Eight Deriv synthetic families as first-class subjects. `synth
  dex` reads an edge of **exactly 0.0000** and the volatility indices +-0.003,
  which is the measurement proving itself calibrated on markets with known
  generators and no reversion designed in.

### The volume combination runs backwards

Conditioning the price signal on the volume stretch, edge by stratum at 15m,
lowest volume on the left:

| class | centre | v0 | v1 | v2 |
|---|---|---|---|---|
| fx majors | ema | **+0.0134** | +0.0066 | -0.0019 |
| fx crosses | ema | **+0.0182** | +0.0070 | -0.0005 |
| fx crosses | regress | **+0.0169** | -0.0044 | -0.0061 |
| metals | mean | +0.0029 | -0.0096 | -0.0110 |

The published volume-climax idea predicts the edge **rising** across each row.
It falls, monotonically, in every real class and under every centre.
**Reversion is strongest where the volume stretch is lowest**, which inverts the
story: a high-volume stretch is a repricing and does not come back, a
low-volume one is noise and does. It is also the largest edge in the whole
exploration at +0.018, which is still far too small to trade.

## A design flaw worth recording

The origin-arrival target was also run as an AUC - does the stretch, pointed at
the line, predict arrival within 24 bars - and it reads **0.32 to 0.49**, far
below 0.5. That is not an anti-signal, it is a **confound in the score**:
`-z * sign(line - price)` is large exactly when price is stretched away from a
distant line, so it reads how far the target is rather than how likely it is to
be reached.

The twin carries the same geometry, so the **edge is still valid and it is
+-0.02, which is nothing**. But the raw figure is uninterpretable, and the
lesson is that a signal pointed at a level has to be stratified by the distance
to that level before its AUC means anything.

## What to take from this

1. **If you are fading to a displacement origin, do not wait for an extreme
   stretch.** The median turn is z 1.3 overall and about **1.95** for returns
   slow enough to trade, against a 100-bar window; z 2.5 misses 85 to 89% of
   returns and selects the population least likely to come back.
2. **Quote every z threshold with its window.** The same excursion is 1.5
   against 50 bars and 0.93 against 300.
3. **The stretch says nothing about whether price returns** - AUC 0.22 to 0.29,
   almost all geometry.
4. **Volume cuts the other way from the published idea**, and that is the only
   coherent conditioning effect found.
5. **A robust scale is not the fix, and neither is a longer window.** The centre
   was the problem, and removing its lag removes the apparent signal with it.
