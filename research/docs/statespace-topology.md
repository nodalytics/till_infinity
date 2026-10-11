# Algebraic topology, tested before it was added

Asked on 2026-10-11: can we test and add algebraic topology to the statespace
models? Tested first, which was the instruction and also the right order.
Harness: `research/ideas/topology.py`.

## What was measured

A **delay embedding** of each return series - three dimensions, two bars
apart, forty points a window - and the **persistence entropy** of the `H1`
lifetimes of its Vietoris-Rips filtration. A loop surviving a wide range of
scales is a recurrent structure in the embedding rather than an artifact of
the scale you happened to pick, and persistence entropy is the one-number
summary the literature reports most often.

Scored against the size of the next move at four and twenty-four bars, with
three nulls:

* the **rotated control** on the feature itself;
* a **trailing standard deviation** on the same points, which is the null
  nothing in this repository has beaten;
* a **GARCH(1,1) with `t(5)` innovations** - clustered volatility, no
  participants, no recurrence. This is the null that kills most published
  topological results in finance, because a series with clustered volatility
  produces structured-looking persistence diagrams for reasons that have
  nothing to do with recurrence.

| series | h | rho | control | edge | trailing sd |
|---|---|---|---|---|---|
| eurusd | 4 | -0.038 | +0.007 | -0.045 | **+0.186** |
| eurusd | 24 | -0.085 | +0.013 | -0.099 | **+0.213** |
| xauusd | 4 | -0.000 | +0.023 | -0.023 | **+0.264** |
| xauusd | 24 | -0.094 | -0.043 | -0.051 | **+0.234** |
| gbpusd | 4 | +0.000 | +0.011 | -0.011 | **+0.159** |
| gbpusd | 24 | +0.133 | -0.044 | **+0.177** | +0.148 |
| btcusd | 4 | +0.018 | -0.015 | +0.033 | **+0.213** |
| btcusd | 24 | -0.023 | -0.010 | -0.013 | **+0.101** |
| v75 | 24 | +0.036 | -0.059 | +0.095 | +0.050 |
| **GARCH t(5)** | 24 | +0.046 | -0.023 | **+0.069** | +0.995 |
| gaussian walk | 24 | -0.077 | -0.008 | -0.069 | +0.071 |

## The answer is no, and the GARCH row is why

**Persistence entropy's edge on the real markets is in the same range as on a
surrogate that has no recurrence at all.** The markets read -0.099 to +0.177;
the GARCH surrogate reads +0.069, sitting comfortably inside that range. A
statistic that cannot distinguish six real markets from a random-number
generator with clustered volatility is reading the clustering.

The gaussian walk reads -0.069, which is the same magnitude with the opposite
sign - so the spread of these numbers is the spread of noise at this sample
size, not a signal with a sign.

And the comparison that decides it: **the trailing standard deviation reads
+0.10 to +0.26 on the same points.** The one cell where topology nominally
wins - gbpusd at twenty-four bars, +0.177 against +0.148 - is one cell out of
ten, at the sample size where `n` falls to 329, and the surrogate posts +0.069
in the same column.

The GARCH row also carries an incidental confirmation: a trailing standard
deviation reads **+0.995** against GARCH's own realised sizes, which is what a
volatility forecast should score on a series that is nothing but volatility
clustering. The instrument is calibrated; it just has nothing to find here.

## What this does not refute

Persistence entropy over a Rips filtration of a three-dimensional delay
embedding, at these windows, as a forecaster of the next move's **size**.
That is one statistic, one embedding and one target, and the literature has
others - persistence images, landscapes, higher homology, embeddings chosen by
false-nearest-neighbours rather than fixed at three.

What the result does say is that the **cheap decisive version came back inside
its own control**, and the richer summaries cost a dependency and an order of
magnitude more compute to test the same hypothesis. The next version would
need a reason to expect a different answer, not merely a different estimator.

## Two notes on the implementation

The `H1` lifetimes come from the **minimum spanning tree** plus the
cycle-closing edges - a loop is born when an edge closes a cycle, which is an
edge not in the MST, and dies at the cheapest triangle that fills it. That is
a standard shortcut and **not the full persistence algorithm**: it gives
correct lifetimes for the dominant cycles without pairing them canonically,
which is enough for persistence entropy and is stated in the harness rather
than implied, because `ripser` and `giotto-tda` are not dependencies here and
were not going to become ones for a test.

And the GARCH surrogate is the one `research/harness/ecology.py` already uses,
rather than a new one invented for this - a control that differs between
studies is a control that eventually differs in the study's favour.
