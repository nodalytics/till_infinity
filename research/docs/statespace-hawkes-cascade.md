# Hawkes cascades: the detector works, on the quantity that was not in dispute

The claim, from a 97-instrument study: forward returns conditioned on a
high-intensity Hawkes signal are **asset-class dependent in sign**. Indices
`+0.010%` and synthetics `+0.004%` continue; metals `-0.013%` and equities
`-0.015%` revert, at the M5 24-bar horizon. The proposed strategy follows the
cascade on one class and fades it on the other.

Two observations about the claim before any measurement.

**The indicator is not a Hawkes process.** As published it is

    intensity(t) = intensity(t-1) * exp(-0.1) + 0.5 * magnitude(t)
    magnitude    = |return| * volume_spike * (1 + wick_ratio)

which is an exponentially weighted mean with about a ten-bar memory over a
volatility-and-volume proxy. There is no point process, no fitted `alpha` or
`beta`, and no branching ratio - so none of the Hawkes literature's results
about criticality or reflexivity transfer to it, and the name is doing no work.
A `2 sigma` reading means **a big, high-volume, wicky bar just happened.**

**The quoted effects are a fraction of a spread.** `0.010%` is one basis
point; gold's spread is several. So the cost gate is the first thing to report
rather than the last.

The harness is `research/ideas/hawkes_cascade.py`, with the published
parameters unchanged.

## What the indicator does predict, and it is clean

The next three bars' absolute move on signal bars, over its unconditional
mean - `size x` in the tables:

| | cells | 3m | 15m | 1h |
| --- | ---: | ---: | ---: | ---: |
| forex | 12 | **1.30** | **1.36** | **1.18** |
| metals | 2 | **1.35** | **1.38** | **1.17** |
| crypto | 3 | **1.34** | **1.41** | **1.25** |
| equities | 433 | - | - | **1.10** |
| `synth:Volatility` | 20 | **1.00** | 1.00 | 1.00 |
| `synth:Step` | 2 | 1.01 | 1.00 | 1.00 |
| `synth:Jump` | 5 | 1.01 | 1.00 | 1.00 |
| `synth:Boom` | 9 | 1.00 | 1.00 | 0.98 |
| `synth:Crash` | 9 | 0.99 | 1.00 | 1.00 |

**A 10% to 41% lift on every traded class and exactly nothing on 56 synthetic
cells.** Equities are the weakest at 1.10, which is what gappy overnight bars
should do to a ten-bar volatility memory. That is the indicator working precisely as its construction implies:
it is a volatility-spike detector, it finds volatility spikes where volatility
clusters, and it finds none where the generator has no clustering to find.

This is worth stating generously, because it is the paper's microstructure
intuition arriving at the right answer attached to the wrong dependent
variable. "Asset class matters" is true. It matters for **magnitude**.

## The directional claim does not replicate

`in sprd` is the edge net of a matched random control, in spread units - the
only column a desk could act on. Break-even needs 1.0, and a round trip 2.0:

| class | 3m | 15m | 1h |
| --- | ---: | ---: | ---: |
| forex | -0.000 | +0.000 | -0.000 |
| metals | -0.002 | **+0.036** | -0.035 |
| crypto | +0.000 | +0.002 | +0.007 |
| equities (433) | - | - | **-0.051** |
| `synth:Volatility` | -0.000 | -0.002 | +0.003 |

**The best traded cell in the table is metals at 15m, at 3.6% of one spread -
about 28 times short of break-even** before the round trip. Everything else is
at zero to three decimal places.

### And the signs are not the claimed ones

| class | claimed | 3m | 15m | 1h |
| --- | ---: | ---: | ---: | ---: |
| metals | **-0.013** | -0.0020 | **+0.0345** | +0.0050 |
| equities (433) | **-0.015** | - | - | **-0.1717** |
| crypto / indices | +0.010 | +0.0002 | +0.0328 | +0.0565 |

Metals are claimed to **revert** and the largest reading on them is
**continuation** at `+0.0345` with the table's highest `z` of `+3.55` - the
wrong sign, from the cell that looks most significant.

**Equities are the one place the claimed sign appears**, and it deserves
saying plainly: the median of 433 names reverts, which is the claimed
direction. It fails on everything else. The magnitude is `-0.1717` against a
claimed `-0.015`, **eleven times larger**; the matched random control reads
`-0.0477` on the same bars, so most of it is not the signal; the net is
`z = -0.45`, inside noise; and in spread units it is `-0.051`, so fading the
cascade would earn 5% of one spread and needs 100% before the round trip.

The first run of this arm reported equities at `+0.0373` on **21** names,
because the loader required more than 2,000 bars and most equities carry
1,883 at 1h. That silently kept only the long-history large caps and inverted
the class median. Lowering the floor to 1,200 bars brought 433 names in and
turned `+0.0373` into `-0.1717` - a sign change from a threshold, on a class
whose claim is about sign.

And nothing is consistent across frames: metals run `-0.0020`, `+0.0345`,
`+0.0050` from 3m to 1h. A sign that changes with the sampling interval is not
a property of the asset class.

### The claim as a difference, which is what it actually asserts

The assertion is not that metals revert but that metals and indices have
**opposite** signs, so the difference is the right statistic - and it survives
a common-mode artefact that two separate signs would not:

| pair | observed | claimed |
| --- | ---: | ---: |
| 3m, metals - crypto | -0.0022 | **-0.0230** |
| 15m, metals - crypto | **+0.0017** | -0.0230 |
| 3m, metals - forex | -0.0015 | -0.0230 |
| 15m, metals - forex | **+0.0374** | -0.0230 |

The right sign once, at a tenth of the size, and the wrong sign at the other
frame.

## Splitting the synthetics is what kills "synthetics continue"

The paper pools fifteen synthetics into one class. Their generators are
**known and different**, and pooling across arms has inverted a conclusion on
this desk before:

| family | what the generator permits | 3m | 15m | 1h |
| --- | --- | ---: | ---: | ---: |
| `Volatility` (20) | fixed-vol Brownian: **must be zero** | +0.0006 | -0.0146 | -0.0054 |
| `Step` (2) | constant steps: **must be zero** | +0.0005 | -0.0058 | +0.0024 |
| `Jump` (5) | symmetric Poisson jumps: no direction | +0.0027 | +0.0079 | +0.0170 |
| **`Boom` (9)** | **engineered asymmetric jumps: can be non-zero** | +0.0001 | +0.0013 | -0.0031 |
| **`Crash` (9)** | **engineered asymmetric jumps: can be non-zero** | +0.0052 | -0.0005 | +0.0280 |
| `Drift_Switch` (3) | switching drift: can be non-zero | +0.0141 | +0.0162 | -0.0144 |
| `DEX` (6) | engineered directional bias | +0.0043 | -0.0176 | -0.0413 |

Every `z` in this block is inside `|1.4|`. The two families whose engine
**could** produce a directional cascade edge by construction - `Boom` and
`Crash` - are as null as the fixed-volatility ones, so a pooled `+0.004%` is
not coming from the engineered mechanics the paper's explanation appeals to.

`Volatility` and `Step` reading null is the method check rather than the
result: a non-zero there would have been measurement artefact, and both come
back at zero to three decimals on 22 cells across three frames.

### The equity cross-section is not 433 independent tests

`|z| > 2` fires on **0.24** of the 433 equity cells against the 0.05 chance
expects - about 104 names rather than 22 - while the **median `z` is only
-0.45**. A z-distribution that is centred near zero and far too wide is the
signature of **cross-sectional correlation**: equities share a market factor,
so a common shock throws many cells past the threshold together and in the
same direction.

The matched random control is drawn per instrument, so it handles the duty
cycle and **not** the shared factor. So the 104 extreme cells are not 104
findings, and the honest reading of this class is the median against its own
control, which is `z = -0.45`.

Doing it properly would mean Fama-MacBeth across dates or date-clustered
errors, as the cubic work needed. That is not done here, and the reason it is
not needed is that the cost gate already settles it at 5% of a spread.

## The stated sample is internally inconsistent

Worth recording because it bears on whether a one-basis-point effect could
have been resolved at all:

| | |
| --- | ---: |
| 97 instruments x 4 timeframes | **388 jobs** |
| at "up to 1,000 bars per instrument per timeframe" | **388,000 bars** |
| stated total | **38,806,492 bars** |
| ratio | **100.02x** |

The two figures differ by almost exactly a factor of a hundred, and "1,000 M5
bars" is **3.5 days** rather than the "approximately 2 years" claimed in the
same paragraph - two years of M5 is about 210,000 bars. One of the three
statements is wrong and the text does not say which.

At 388,000 bars with a 6% duty cycle, each of eight classes holds roughly 2,900
signal events, and a one-basis-point edge is well inside the noise of that. At
38.8 million it could be statistically resolvable and still economically
worthless. Either way the figures here supersede it, so this is a caveat
rather than the argument.

## What survives

**The detector.** A 1.17x to 1.41x magnitude lift on every traded class
against exactly 1.00 on 56 synthetic cells is a real, clean, well-controlled
result, and it is the same conclusion this desk keeps reaching from other
directions: magnitude is predictable and direction is not.

What does not survive is every directional claim in the paper - the signs, the
sign flip, the asset-class dependence of direction, and the strategy that
selects follow or fade from class membership. Nothing in the table clears 4% of
one spread.
