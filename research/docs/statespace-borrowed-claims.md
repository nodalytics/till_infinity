# Twelve in-house papers: two claims tested null, seven refuted, five reviewed

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

**All three are now built, and seven numbers from the same family are
measured.** See `statespace-displacement-sequences.md`: the correction factor
is 0.99 rather than 0.86 or 0.73, its celebrated serial correlation is the
arithmetic of a shared denominator, the branching ratio is 2.1 rather than
3.2, and the rotation count's hazard alternates by parity in a way a random
walk reproduces exactly.

## Five more from the same source, reviewed rather than measured

Four write-ups and one retired indicator, read after the three above were
built. None needed a harness: each is refuted, already answered here, or
reduces to something this package has.

### The recurrence indicator, and why it was retired

A rolling recurrence-quantification laminarity, cited to a 2011 nonlinear
dynamics paper and validated there across five crashes. Its neighbourhood
threshold is **2% of the current price**, compared against raw price
differences. That is not a volatility unit, so the same setting means
different things on different instruments:

| at 1h | the 2% threshold, in bar sigmas | recurrence rate |
| --- | --- | --- |
| EURUSD | 16.7 | **1.000** |
| XAUUSD | 5.7 | **1.000** |
| BTCUSD | 2.5 | 0.774 |
| a v75-like series | 1.7 | 0.562 |

On FX and gold the matrix **saturates**: every pair of points in the window
counts as recurrent, so every column is one unbroken vertical run, laminarity
is identically 1, and the z-score against its own baseline divides by the
1e-9 floor. The indicator is a constant on the instruments this desk trades
most and varies only on the noisiest ones. One line - the threshold in
volatility units rather than price percent - would fix it, and it is the same
lesson already recorded twice here: distance-to-swing had to move to log
units, and duration-defined features port at 0.93-1.00 where bar-count ones
manage 0.3-0.4.

Separately its line-counting adds `length - (min_line - 1)` per vertical run
where the cited definition adds `length`, which biases laminarity down for
short runs - and "collapsing laminarity" is the signal.

**What transfers**: laminarity has a free state-space reading. A laminar
stretch is one where the filter is tracking, so it is the run-length
distribution of `|last_standardised| < 1` on any member. That version is
properly normalised by construction, because the member's own predicted
spread is in the denominator. No new model, a readout.

### The combinatorics note

Derives the practitioner's rotation formulas from Catalan numbers. The
arithmetic is written backwards from the conclusion: `C(4) + C(3)` is 19, and
the note renders it "14 + 5 - 8 ~= 11" with an unexplained -8; the next line
lists four terms for a three-term sum and reaches 26 from numbers totalling
21. A derivation that needs a different fudge per row is a fit.

It also proposes replacing a linear exhaustion score, `rotations/expected`,
with a Catalan-weighted one. **Both are strictly increasing in the rotation
count**, so any threshold on one is a different threshold on the other: the
two fire on exactly the same bars in exactly the same order. The proposal
cannot change timing, which is the thing it is offered to improve.

Its backtest table is the most useful number in the whole family, and it
agrees with this desk the hard way: win rates of 61-75% across six regimes
with PnL often negative. That is `polymarket-updown-edge-is-dead` restated -
a high hit rate with the payoff asymmetry against you is not an edge.

### The particle-physics survey

Mostly things already answered here: topological data analysis measured null
against a GARCH control, Ising susceptibility null, Hurst and kurtosis
already in `facts.py`. Three items are new.

**The renormalisation-group regression is the one worth building.** It gives
`R(t+T) = a + b*phi(t) + c*phi(t)^3`, reads the regime off the **sign of the
cubic term**, and reports coefficients with error bars - `b = 1.29% +/- 0.43%`
and `c = -0.62% +/- 0.23%` at daily scales, `b = +0.132% +/- 0.046%` and
`c = -0.039% +/- 0.014%` intraday. Numbers with uncertainty are replicable,
unlike everything in the geometry family, and `phi` is a cumulative return
which this desk now computes over durations.

Its state-space translation is a **member this library does not have**: a
reverting process whose restoring force is cubic rather than linear.
`reverting` is an Ornstein-Uhlenbeck pull proportional to displacement; a
cubic term is weak near the anchor and strong far from it, which is what
produces trending at small displacement and reversion at large. One extra
parameter on an existing member, physically motivated, and it would be scored
the usual way. Queued.

**Critical slowing down comes with its own refutation**: variance rises before
every major crash, and the false-positive rate is 44% - sixteen high-variance
episodes in 115 years, nine of them crises. A detector at that rate cannot
gate anything, and the note says so.

**The Kuramoto order parameter is already readable here.** It measures how
much of a cross-asset panel moves together, which is `panel`'s factor variance
share - the member exists and the reading is free.

### The ecology survey

Its central framing, strategy types as competing species with
density-dependent returns, has already been tested here and come back null:
`strategy-rotation-is-not-timeable` found every pause rule matching random
pausing at the same duty cycle. The ecology framing predicts exactly the
opposite - that the population state tells you which strategy to deploy.

Its predator-prey oscillation claim has a sharper answer. **A Lotka-Volterra
system linearised about its fixed point is a damped harmonic oscillator**, so
the claim that buyer and seller populations oscillate with a characteristic
frequency is, in this library, `oscillator.py` - the one member with complex
eigenvalues. Fitted, it returns a damping ratio of 67: overdamped by a factor
of sixty, with no oscillation left. Testing it properly needs signed order
flow rather than price, which this desk does not have.

Its one cheap replicable number is a Gini coefficient of absolute returns
converging to 0.84 +/- 0.03 in self-organised critical systems. Queued with
the cubic regression.

### The pattern-memory note

Proposes a hash-indexed lookup from a discretised recent state to what
happened next. The objection is arithmetic: eight hash heads over
65,537-element tables at two n-gram orders is about a million cells, and a
40,000-bar series fills 0.04 of them. Hash collisions would supply every
reading, averaging unrelated patterns. A lookup table is the
maximum-capacity, zero-regularisation end of the bias-variance range, which
is the worst available choice for a low-signal non-stationary series - and
this desk has the nearest measurement: binned state could order at most 6 of
45 bin pairs in `statespace-informatory-pairs.md`.

Its gating is the good part, and it is already here exactly. "Gate the
memory down when it contradicts the context" is a learned sigmoid
approximating what an interacting multiple model does in closed form:
reweight each component by how well it predicted. `switching.py` and
`symmetry.py` both do it, and theirs is the exact version.

## The maths and information-theory survey, and one bound worth having

A different source family - eight domains, each with papers and URLs rather
than assertions. Much of it is already answered here: topological data
analysis measured null against a GARCH control, and the Wasserstein regime
work is the same Horvath paper reviewed above, whose own novelty rate of
0.0-0.2% of bars is the caveat.

One item is worth more than everything else reviewed today, because **it does
not need an edge to be true.**

### Leverage, from non-ergodicity

Under multiplicative dynamics the time-average growth rate of a leveraged
position is `g(l) = l*(mu - r) - l^2 * sigma^2 / 2`, a downward parabola. It
peaks at the Kelly leverage `l* = (mu - r)/sigma^2` and crosses back through
zero at `l_crit = 2*l*`. Above `l_crit` the time-average growth rate is not
merely worse, it is **negative** - so ruin is certain given enough time,
however positive the expectation looks.

That is a bound from the drift and the volatility alone. Computed on daily
bars, with the drift's own standard error propagated:

| instrument | years | sigma/yr | l* | +/- | l_crit |
| --- | --- | --- | --- | --- | --- |
| BTCUSD | 15.5 | 0.845 | 1.53 | 0.30 | **3.06** |
| ETHUSD | 11.1 | 1.073 | 1.08 | 0.28 | **2.17** |
| XAUUSD | 15.7 | 0.170 | 2.97 | 1.49 | 5.94 |
| XAGUSD | 15.7 | 0.335 | 0.92 | 0.75 | 1.83 |
| EURUSD | 55.7 | 0.098 | 1.95 | 1.37 | 3.89 |
| GBPUSD | 33.3 | 0.090 | 0.03 | 1.92 | 0.06 |
| USDJPY | 55.7 | 0.102 | -0.95 | 1.31 | -1.90 |
| USDCHF | 55.7 | 0.112 | -1.90 | 1.20 | -3.81 |
| Volatility_75_Index | 7.7 | 0.745 | 0.31 | 0.48 | 0.62 |
| Volatility_100_Index | 7.7 | 0.981 | 0.25 | 0.37 | 0.49 |
| Step_Index | 7.3 | 0.062 | -9.62 | 5.98 | -19.23 |

**The error bars decide where this is usable.** The drift's standard error
over a sample of `T` years is about `sigma/sqrt(T)`, so `l*` carries an error
of `1/(sigma*sqrt(T))` - which *shrinks* as volatility rises. The ratio of
estimate to error is 5.1 on BTC, 3.9 on ETH, 2.0 on gold, and **below one on
every FX pair and every generated market.**

So:

* On **BTC and ETH** the bound is real and tight: above about 3x and 2.2x
  respectively, long-run growth is negative. The survey's claim that optimal
  BTC leverage is "~0.47x" does not reproduce - measured `l*` is 1.53 - but
  its actionable half survives, because the 2x-10x it describes as common
  straddles a critical leverage of 3.06.
* On **FX** the drift is indistinguishable from zero over 33 to 56 years:
  EURUSD's `l*` is 1.95 +/- 1.37 and GBPUSD's is 0.03 +/- 1.92. There is no
  optimal leverage to compute, and `l_crit` inherits the same uncertainty.
* On the **generated markets** `l*` sits at 0.07 to 0.36 with error bars
  covering zero, and `Boom`, `Crash` and `Step` have negative drift outright,
  so any long leverage on them is already past critical. `Step_Index` also
  shows the formula's numerical weakness: a volatility of 0.062 puts `l*` at
  -9.6 +/- 6.0, because dividing by `sigma^2` explodes when the volatility is
  small.

**What this does not do is replace the existing risk limit.** The desk's
exposure is in FX and the synthetics, which is precisely where the bound is
not estimable, so the daily-loss fraction stays what it is. The bound is a
ceiling to respect where it is computable, not a sizing rule to adopt.

### Three queued, with their priors

* **Levy area for lead-lag.** The Levy area of a two-asset path is
  `(1/2) * integral(X dY - Y dX)`, whose **sign** says which asset leads -
  an asymmetry correlation cannot express. It needs no library and it is the
  right shape for `relating`, whose hedge ratio is already a state, and for
  the cross-impact measurement still pending in
  `statespace-stat-arb-and-volume.md`.
* **Wasserstein regime clustering against an HMM.** The paper claims
  Wasserstein k-means "vastly outperforms" HMM regime detectors because HMMs
  assume Gaussian emissions and returns have fat tails. This package now has
  both halves - `distance.py` and two HMMs in `switching.py` and
  `symmetry.py` - so it is a head-to-head rather than a claim, and it is the
  natural next use of the metric.
* **Lempel-Ziv complexity as a predictability gate.** A few dozen lines, and
  the only reviewed statistic that asks whether the series is compressible at
  all rather than which way it is going. The prior is unkind: every gate
  measured at this desk has matched its rotated control, and
  `till-infinity-measured-nulls` records the rolling-quantile family going
  the same way. It is cheap enough to be worth the refutation.
