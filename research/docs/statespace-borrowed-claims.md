# Seven in-house papers, two claims tested, both null

Reviewed 2026-10-11 from internal research material held elsewhere in the
workspace. Summarised rather than cited. Most of it needs data this desk does
not have; **two claims were cheap and decisive here**, and one of them
contradicted this repository's own record, which made it the more interesting.

Harness: `research/ideas/borrowed_claims.py`.

## 1. Ising susceptibility: the conflict, resolved on our data

A study over **38.8 million bars and 97 instruments** reports susceptibility -
the variance of a magnetisation built from **signed volume flow** - firing at
7-8% of bars with a mean edge of +0.30 to +0.42% at twenty-four bars, and
calls it the highest-capacity microstructure signal in its dataset.

`README.md` here lists an Ising susceptibility among the things a **trailing
standard deviation beat**, beside a three-state HMM and a fifty-neighbour
analogue.

The candidate explanation for the disagreement was good: their order parameter
uses **traded size**, and every FX feed here reports a tick count. BTCUSD is
the one instrument with real volume, so the test was susceptibility with a
properly signed magnetisation where that is possible.

| series | order parameter | rho vs \|move\| | control | trailing sd |
|---|---|---|---|---|
| eurusd | sign only | -0.034 | -0.039 | **+0.170** |
| eurusd | signed volume | -0.089 | -0.033 | **+0.170** |
| xauusd | sign only | +0.058 | -0.003 | **+0.280** |
| **btcusd** | sign only | -0.034 | +0.023 | **+0.154** |
| **btcusd** | **signed volume** | **+0.004** | +0.016 | **+0.154** |
| usdjpy | signed volume | +0.037 | -0.039 | **+0.270** |

**Real volume does not rescue it.** On the one instrument where the paper's
own construction is possible, susceptibility reads **+0.004** against a
rotated control of +0.016 and a trailing standard deviation of +0.154. The
directional column is -0.016 to +0.080 across every series, which is nothing.

So this desk's original finding stands, and the explanation that would have
reconciled the two is ruled out rather than left open. What remains unresolved
is why the external study sees what it sees - its sample is five thousand
times larger and on M1-M5 where this ran on 1h, and either could matter. The
honest statement is that **the claim does not reproduce here, at this
resolution, against this null**, which is narrower than "it is wrong".

## 2. The Thursday effect

The same dataset reports systematic negative Thursday returns - Bitcoin at a
Sharpe of -2.43, US Tech 100 at -2.07 - with Monday strength in equities and
Wednesday strength in crypto.

Mean bar return on each weekday over its own standard error:

| | Mon | Tue | Wed | **Thu** | Fri | Sun |
|---|---|---|---|---|---|---|
| eurusd | +1.40 | +0.06 | -0.34 | **+0.17** | +0.02 | -0.27 |
| xauusd | +1.36 | +0.80 | +1.67 | **+0.52** | +0.43 | +0.49 |
| gbpusd | **+2.86** | +0.24 | -0.65 | **-0.65** | -0.14 | -0.84 |
| usdjpy | +0.19 | +0.73 | +0.33 | **-0.83** | +0.07 | +1.36 |
| btcusd | +0.62 | -0.41 | +1.37 | **-1.53** | +0.28 | +0.02 |
| v75 | **-2.09** | +0.78 | -1.58 | **-0.29** | +0.25 | -0.12 |

**Thursday is negative on four of six and significant on none** - the largest
is btcusd at -1.53. Two cells clear `|t| > 2` out of forty-two, which is
exactly what chance gives, and they are **Monday on two different
instruments with opposite signs**: gbpusd +2.86 and v75 -2.09. Opposite signs
on the same day is the signature of noise, and v75 is generated.

Day-of-week effects are the most heavily mined anomaly in finance, and 97
instruments times seven days times five timeframes is a very large surface.
This is what that surface produces on a different sample.

## The five not tested, and why

* **Market geometry** and **nodal displacement sequencing** model price as
  alternating trend and pullback functions joined at nodes, with a fractal
  decomposition. The transferable idea is sharp and worth keeping: **operate
  on the sequence of moves between reversal points, not on price**, because
  the geometric relationships between consecutive swings are claimed to be
  more stable than levels. This desk now computes confirmed pivots
  (`inputs.pivot_levels`), so the observation process exists - but the counted
  pivots measured null, and the *displacement ratios between* pivots are a
  different quantity that has not been tried. That is the testable residue.
* **Symmetry transformations on displacement sequences** formalises five
  transformations (reflection, scaling, phase-space rotation, glide, spiral),
  one per regime, with a maximum-likelihood detector for which is active. As a
  state-space object this is a **switching model whose observation is a
  displacement sequence** - `switching.py` is the machinery and the
  observation is the missing half. Its null is `switching` on price.
* **Wasserstein regime clustering** reports clustering rolling return
  distributions by optimal-transport distance is 10x faster and 5x more
  stable than Euclidean k-means on detector outputs, and that **novelty**
  events - a distribution matching no known cluster - precede positive returns
  in commodities and negative ones in FX. Two things transfer: **Wasserstein
  as a metric**, which Düring's work pointed at independently and which this
  package does not use at all; and novelty as `changepoint`'s question asked
  distributionally rather than about a level. The caveat is in the paper's own
  numbers: novelty is **0.0-0.2% of bars**, so on the 8,000-bar samples here
  that is zero to sixteen events, and the asset-class split is eight classes
  times two signs.

## What this says about reading in-house material

The same standard as the external papers, and it matters more here because the
source shares this desk's vocabulary and some of its data. Two claims were
cheap to check and both came back null against the controls this repository
uses. That is not a verdict on the work - its sample is far larger and its
resolution finer - but it is the only basis on which anything would be built
here, and neither clears it.

The three ideas worth keeping are the ones that are **structural rather than
empirical**: displacement sequences as an observation process, symmetry
detection as a switching model, and Wasserstein as a second metric beside
likelihood. None of them is a claim that needs replicating; each is a shape
that can be built and then measured the usual way.
