# Topology on price: shape discovery, and what the representation decides

Three attempts at finding exploitable shapes, in the order they were made, because the
order is the argument. Each failed for a reason that motivated the next.

| harness | representation | what it can see | outcome |
|---------|----------------|-----------------|---------|
| `motifs.py` | raw candle windows, k-means | fixed-length pixel patterns | died on its own bootstrap |
| `tda.py` | persistence **scalars** | how much structure, not which | loses to 6 trailing-vol ratios |
| `shapes.py` | persistence **images** | which shape, warp-invariant | chance, at the wrong embedding |
| `embed.py` | - | the embedding itself | **lag 4, dimension 6 - not 1 and 3** |

## What clustering raw windows found, and why it does not count

`motifs.py` clusters scale-free candle windows - price level and volatility divided
out - and asks whether any cluster is followed by something other than the base rate.
Because every row carries the same symmetric barrier, the geometry is constant and the
overall hit rate **is** the "same geometry entered at an arbitrary moment" placebo that
`patterns.md` had to construct by hand.

On two instruments it looked strong: **9 of 24 motifs cleared two standard errors
against about 1.1 expected by chance**, with a 5.9-point spread between the best motif
(53.2% resolving up) and the worst (47.3%) around a 50.0% base. Symmetric in both
directions, which is what a real partition looks like rather than a fluke. On ten
instruments it fell to 3 of 24.

**Then the block bootstrap removed it.** Consecutive windows share 31 of their 32 bars
and their forward windows intersect, so a two-proportion error assuming independent
rows is too narrow. Resampling contiguous blocks longer than window-plus-horizon:

| | naive band | block bootstrap |
|---|---:|---:|
| best motif | +/-1.3% | **+/-2.0%** on a +1.8% gap |
| worst motif | +/-1.3% | **+/-1.7%** on a -1.6% gap |

Both straddle zero. The correction widened the bands by about half and the result did
not survive it. **The independence assumption was the entire finding.**

That is worth stating plainly because the intermediate state - "9 of 24 against 1.1
expected" - was reported here as promising before the bootstrap ran. It was not.

## Why persistence scalars cannot find a shape

`tda.py` implements the standard pipeline for a scalar series: delay embedding of log
returns into a point cloud, Vietoris-Rips filtration, persistent homology in `H0` and
`H1`, then the diagram summarised into twelve numbers - total persistence, max
persistence, count, entropy, and the `L1`/`L2` norms of the persistence landscape.

**Those twelve numbers cannot identify a shape, by construction.** Two entirely
different shapes with equal total persistence are identical to them. They answer "how
much topological structure is in this window", which is a magnitude question.

So the prediction was written into the docstring before the run:

> the persistence features will **fail on direction** and **may work on forward
> volatility**.

The grounds were the literature and this repository agreeing. Gidea and Katz (Physica A
491, 2018) and Aguilar and Ensor (J. Math. Finance 10(4), 2020) both report persistence
landscape norms rising before crashes - an instability result, not a directional one.
And `clustering.md` opens with "direction is noise; volatility is the part that
repeats", while the `triple` run in `supervised-candles.md` had `vol_log_gap` as its
single most important feature ahead of every return feature.

### The prediction held

64,335 rows, 10 instruments, 5 purged walk-forward folds, balanced accuracy against a
block-shuffled null:

| label | balanced accuracy | shuffled null | lift |
|-------|------------------:|--------------:|-----:|
| `banded` (direction) | 0.3371 | 0.3332 | **+0.0039** |
| `expansion` (volatility) | 0.3604 | 0.3326 | **+0.0278** |

Direction is 0.4 points of balanced accuracy on a three-class problem - nothing.
Volatility is seven times larger. Registering the prediction first is what makes this
worth anything; found by searching, it would be one cell of many.

### And it is mostly not topology

Beating block-shuffled labels at forward volatility is nearly free, because volatility
clusters - the most replicated fact in finance. A trailing realised-volatility ratio
clears that null easily. So the harness now fits three models on identical rows:
topology alone, trailing volatility alone, and both together.

**And the baseline wins.** Three models on identical rows, `expansion`, 64,335 rows:

| model | balanced accuracy | lift over null | features |
|-------|------------------:|---------------:|---------:|
| block-shuffled null | 0.3324 | - | - |
| topology only | 0.3604 | +0.0280 | 12 |
| **trailing volatility only** | **0.4279** | **+0.0954** | **6** |
| both together | 0.4305 | +0.0981 | 18 |

Six trivial realised-volatility ratios beat twelve persistence features by **6.8
points**, and adding topology on top of them buys **0.0026** - a quarter of a point
for a Vietoris-Rips filtration per window.

So persistence is re-deriving volatility clustering the expensive way, and doing it
worse than four lines of numpy. The registered prediction was correct that volatility
beats noise where direction does not, and the baseline shows that this was never the
interesting comparison.

**The bar is not the shuffled null, it is GARCH.** A volatility signal that has not
been compared against a conditional-variance model has established nothing, because
GARCH is standard and is about sixty lines of code. Trailing realised volatility here
is a stand-in for it and a weaker one; a proper comparison is still owed.

## What `shapes.py` does differently, and why it might work

Two changes, each answering a specific failure above.

**A persistence image instead of persistence norms.** The image vectorises the diagram
onto a fixed grid while preserving *where* features are born and die, so different
shapes give different vectors. That makes clustering them a search over shapes rather
than over magnitudes - the thing `tda.py` structurally could not do.

**A topological representation instead of raw coordinates.** This is the real argument
for the expense: **a persistence diagram is invariant to time-warping and to monotone
rescaling.** The same shape unfolding over twenty bars or forty, in a quiet regime or a
violent one, gives a similar diagram. Raw-coordinate k-means treats those as unrelated,
so any shape that recurs *at varying speed* was invisible to `motifs.py`. That is a
falsifiable reason to expect a different answer, rather than a hope that a more
sophisticated method will find more.

### Old, new, undiscovered

Every cluster is cross-tabulated against the textbook patterns from `patterns.py` that
trigger inside it, so each comes back labelled:

* **old** - mostly one named pattern, and its edge should match what `patterns.md`
  measured for it;
* **new** - contains several named patterns, so the clustering groups what the books
  split or splits what they group;
* **undiscovered** - almost no named pattern in it at all.

The third column is the interesting one and also the one most likely to be noise, which
is why the controls are not optional: base rate as placebo, block bootstrap sized to
window plus horizon, fit on the past and score on the future, leave one instrument out,
and the survivor count printed against the count expected by chance.

### The result: exactly chance

77,190 windows across ten instruments, 19 shapes large enough to judge:

| shape | n | hit | gap | bootstrap band | what is in it |
|------:|--:|----:|----:|---------------:|---------------|
| 17 | 1,021 | 51.9% | +2.2% | +/-3.3% | undiscovered |
| 13 | 4,383 | 51.2% | +1.7% | +/-1.6% | 3% named, mostly double bottom |
| 14 | 1,815 | 51.2% | +1.5% | +/-2.1% | 3% named, mostly double top |
| 8 | 2,065 | 50.7% | +1.0% | +/-2.3% | undiscovered |
| 0 | 611 | 46.2% | -3.7% | +/-4.1% | undiscovered |
| 18 | 364 | 46.4% | -3.4% | +/-5.3% | 5% named, mostly double bottom |

**1 of 19 shapes clears its bootstrap band, against about 1.0 expected by chance.**
That is not a weak result, it is precisely the null: one survivor is what nineteen coin
flips produce. The single survivor, shape 13 at +1.7% +/- 1.6%, clears by 0.1 points.

The **undiscovered** clusters - those containing almost no named pattern, which were the
whole point of the exercise - did no better than the rest. The best of them is +2.2%
+/- 3.3%, which does not clear.

A smoke test on two instruments had returned 0 of 7 against 0.4 expected, with bands of
+/-5 to 7% too wide to conclude from. The panel has ten times the data and lands on
chance.

### What this rules out, and what it does not

It rules out the specific claim the harness was built for: that clustering warp-invariant
topological signatures of 40-bar windows finds shapes followed by a directional edge. On
this instrument set, at this window and horizon, with these controls, it does not - and
the `undiscovered` column being no better than the named one is the cleanest part of the
answer.

It does not rule out shapes in general, and one of the reasons turned out to be real
rather than rhetorical.

## The embedding was wrong, and it was measurable

`tda.py` and `shapes.py` both fixed the delay embedding at dimension 3 with unit lag.
Neither had any justification for that, and the measure-theoretic embedding paper is
explicit that `tau` and `m` should come from false nearest neighbours or mutual
information rather than be assumed. So `embed.py` measures them.

| instrument | lag | dim | false-neighbour fraction, dimensions 1-6 |
|------------|----:|----:|------------------------------------------|
| xauusd | 5 | 6 | 1.00 0.88 0.50 0.20 0.06 0.02 |
| eurusd | 5 | 6 | 1.00 0.87 0.51 0.21 0.06 0.02 |
| gbpusd | 2 | 6 | 1.00 0.88 0.51 0.19 0.07 0.02 |
| usdjpy | 4 | 6 | 1.00 0.88 0.51 0.19 0.06 0.02 |
| volatility_75 | 4 | 5 | 1.00 0.91 0.56 0.19 0.04 0.00 |
| boom_1000 | 4 | 5 | 1.00 0.91 0.57 0.21 0.04 0.01 |
| btcusd | 3 | 6 | 1.00 0.88 0.51 0.19 0.06 0.02 |

**Median lag 4, median dimension 6.** Lag 1 embeds adjacent returns, which are nearly
redundant, so the cloud collapses towards its diagonal and carries little shape;
dimension 3 under-embeds a series whose false neighbours do not settle until 6. The
curves are near-identical across seven instruments, so this is not a noisy estimate.

A small structural detail worth keeping: every real instrument needs dimension **6**
while both synthetics settle at **5**. The generated processes are genuinely simpler.

So the `shapes.py` result above was measured at the wrong embedding, and the obvious
objection to it - "your embedding was bad" - was correct. It is re-run at lag 4,
dimension 6, window 64.

**This affects the two harnesses differently.** The shape search is provisional until
the re-run. The `tda.py` conclusion is far more robust to it: a better embedding would
have to close a 6.8-point gap to six trailing-volatility ratios *and then* improve on
the combined model, which is a much taller order than lifting 0.3604.

### What `embed.py` cannot settle

Both criteria were designed for deterministic chaotic systems observed with little
noise, and a price series is neither. These are the least arbitrary choice available,
not the correct embedding. Their value is that the next negative result is no longer
answerable with "you picked 3 and 1 out of the air".

## Which branch of topology is usable, and a correction

General topology is the wrong tool: a finite candle series is a finite point set, so
every finite set is compact and totally disconnected and those properties carry no
information. Differential topology needs a differentiable manifold, and price is not
differentiable. **Algebraic topology, through persistent homology, is the branch that
applies.**

Three sources were considered and an error was made about all three, recorded here so
it is not repeated. Each was dismissed as a "dead end" for not being *about* finance,
when the question is whether the *method* applies. It does:

* **Fast Betti numbers on 3D cubical complexes** (Gonzalez-Lorenzo et al., CTIC 2016).
  Cubical complexes are the natural construction for **image-like** data, and a price
  window can be made image-like - a rasterised chart, a recurrence plot, a Gramian
  angular field. That is a different pipeline from the one built here and sees chart
  geometry rather than dynamics. `gudhi` is installed for it; it is not yet written.
* **Measure-theoretic time-delay embedding** (Botvinick-Greenhouse et al., math.DS
  2024). Lifts the Takens embedding to a pushforward between probability spaces using
  optimal transport, motivated explicitly by classical Takens assuming determinism and
  noise-free observation - which markets violate. It reports 2x to 5x lower
  reconstruction error than a pointwise loss on noisy chaotic systems. That makes it a
  better-founded version of exactly what `tda.py` does, and noise robustness is the
  binding problem here.
* **Thick and cohesive Betti numbers** (Hernandez-Garcia et al., math.AT 2025). New
  invariants measuring how well a homological feature is *supported* and whether it
  survives degradation. Applied to a correlation complex of this desk's instruments it
  would be a market-fragility reading. The paper defers empirical validation entirely,
  so this would be new work rather than replication.

## The honest position

Across three representations, the only thing to clear a null is a **volatility** signal,
and it loses to six lines of trailing volatility by 6.8 points. Nothing has identified an
exploitable *shape* - old, new, or undiscovered. The shape search landed exactly on its
chance line.

That is now consistent enough across this repository to be a prior rather than a
coincidence: direction has failed six independent ways in `directional-edge`, again in
`supervised-candles.md`, again in `anchors.md`, and again here. Volatility keeps being
the part that carries information. Any further shape work should be judged against
that prior, and any shape result that predicts direction should be treated as
surprising and checked twice.
