# The diffusion equation is the Schrodinger equation in imaginary time, and here is what that buys

Under the Wick rotation `t -> -i*tau` the heat equation becomes the Schrodinger
equation, a transition density becomes a propagator, a drift becomes a gauge
potential and a barrier becomes a boundary condition. That is an identity rather
than a metaphor, and [deriving.md](deriving.md) has just made it usable here by
settling what the Deriv synthetics are: the Volatility indices are driftless
Brownian motion at a published sigma, Step Index is a fair coin on a 0.1 lattice,
Range Break is genuinely confined between breaks, and Boom and Crash are drift
plus compound Poisson. Each of those is a textbook quantum system - a free
particle, a tight-binding lattice, a particle in a box, a non-local jump operator
- so everything a physicist knows about propagators, spectra and boundary
conditions is already a statement about these price processes.

The field this borrows from is largely classical results in borrowed notation, so
the rule here is that **every quantum construction is scored against a classical
control doing the same job, and where the control matches, the page says the
framing is notation**. Two of the five sections below reach exactly that verdict
and say so, one of them by proving an identity rather than measuring one.

Four harnesses: [`quantimage.py`](harness/quantimage.py),
[`quantspec.py`](harness/quantspec.py),
[`quantbridge.py`](harness/quantbridge.py),
[`quantwigner.py`](harness/quantwigner.py). Each states its kill conditions in its
docstring before any number, and each section below ends with the ledger of which
fired.

**Scope, stated first and not buried.** This page was first written while the
research lab holding `research.db` was unreachable, so its predictions were
pre-registered against data nobody had seen. **The lab has since come back and
every one of them has been run**, which is why several sections below now carry a
measurement after a prediction and two of them carry a correction to a number
this page itself published. What is here is of three kinds, marked throughout:
**exact numerical evaluations of known laws**, which need no data and are
complete; **measurements on the Deriv synthetics**, 24 hours of ticks and 60 days
of one-minute bars from `research.db`; and **measurements on real instruments**
from the local store, which section three keeps because a real feed has fat tails
and volatility clustering and is the harder test.

## One: the 0.5826 is an extrapolation length, so it is a boundary condition rather than a correction

[deriving.md](deriving.md) needs `B = -zeta(1/2)/sqrt(2*pi) = 0.5826` to make
every barrier answer on these instruments exact, and takes it from
Broadie-Glasserman-Kou as a correction to two named option formulas. The
imaginary-time reading is different and stronger.

An absorbing barrier is a Dirichlet wall, and the free propagator plus one image
charge of opposite sign at the mirror point solves it - the reflection principle
written as electrostatics. That is exact for a *continuously* monitored wall. A
quoted price is monitored on a grid, the walk can cross and come back between
quotes, and a wall that absorbs imperfectly is not a Dirichlet wall but a
**Robin** wall, `du/dx = -u/L`. The length `L` is the **extrapolation length**:
the distance beyond the wall at which the linearly extrapolated density would
vanish. It is the Milne problem of neutron transport, where the answer is 0.7104
mean free paths, and the de Gennes extrapolation length of polymer adsorption. To
leading order a Robin wall at `a` with extrapolation length `L` is a Dirichlet
wall at `a + L`. **One image charge, moved.**

So the claim is that `0.5826 * sigma * sqrt(h)` is the extrapolation length of a
Gaussian walk against a wall it only sees every `h`. `quantimage.py` tests it
against the exact discretely monitored law - convolve the density with the
one-step Gaussian, zero it beyond the wall, iterate. That is Chapman-Kolmogorov
evaluated numerically with no asymptotics anywhere; its only error is the space
grid, and halving the grid four times moves the hundred-step survival by
`1.2e-06`.

**Invert the exact law for the shift that reproduces it**, at six barrier
distances and five horizons:

| a | n=25 | n=100 | n=400 | n=1600 | n=3200 |
| --- | --- | --- | --- | --- | --- |
| 1.0 | 0.5799 | 0.5854 | 0.5867 | 0.5870 | **0.5871** |
| 2.0 | 0.5695 | 0.5789 | 0.5813 | 0.5819 | **0.5819** |
| 3.0 | 0.5651 | 0.5783 | 0.5816 | 0.5824 | **0.5825** |
| 5.0 | 0.5547 | 0.5757 | 0.5809 | 0.5822 | **0.5824** |
| 8.0 | 0.5390 | 0.5719 | 0.5800 | 0.5820 | **0.5823** |
| 12.0 | 0.5176 | 0.5668 | 0.5787 | 0.5816 | **0.5821** |

Pooled over `a` in [2, 12] at the longest horizon the shift is **0.58226 with a
spread across `a` of 0.00058**, against `-zeta(1/2)/sqrt(2*pi) = 0.58260`. That
is **0.058%**, and the *flatness* is the point: a boundary condition is a
property of the wall and cannot know how far away the barrier is, so a shift that
drifted with `a` would be a fitted fudge rather than a wall. It does not drift.
The `a = 1` row sits at 0.5871 rather than 0.5822, which is
[deriving.md](deriving.md)'s "excellent at three units and only fair at one" seen
from the other side.

**Scored as predictions**, mean absolute error against the exact law over
horizons 25 to 3200, with a deliberately wrong constant as the control:

| a | image plane at `a` (textbook) | at `a + 0.5826` | at `a + 1.0` (control) |
| --- | --- | --- | --- |
| 2.0 | 0.033930 | **0.000438** | 0.024376 |
| 3.0 | 0.031809 | **0.000506** | 0.022800 |
| 5.0 | 0.026545 | **0.000588** | 0.019045 |
| 8.0 | 0.019003 | **0.000462** | 0.013641 |
| 12.0 | 0.012714 | **0.000233** | 0.009123 |

The moved image plane is **fifty to seventy times** better than the textbook one,
and the wrong-constant control is only about a third better than the textbook -
so the measurement has the power to say *which* constant, which is what makes the
middle column readable at all.

**The same constant from a second functional.** Asmussen-Glynn-Pitman:
`E[max of the observed points] = sqrt(2n/pi) - B + o(1)`. Evaluating the left
side exactly, by integrating the survival probability over the level:

| n | E[max] exact | `sqrt(2n/pi)` | deficit | deficit minus B |
| --- | --- | --- | --- | --- |
| 25 | 3.44622 | 3.98942 | 0.54320 | -0.03939 |
| 100 | 7.41595 | 7.97885 | 0.56290 | -0.01970 |
| 400 | 15.38491 | 15.95769 | 0.57278 | -0.00981 |

The residual **halves every time `n` quadruples**, so the `o(1)` term is
`O(n^-1/2)` with a coefficient of 0.196, and extrapolating gives
`0.57278 + 0.00981 = 0.58259` against 0.582597. Five significant figures, from a
functional that shares no arithmetic with the shift inversion.

**And the same constant as an overshoot.** The walk crosses between quotes and is
first seen past the level, so the observed first-passage level is `a + R` with
`R` the overshoot, and renewal theory gives the stationary mean overshoot as
`E[H^2]/(2E[H])` with `H` the strict ascending ladder height. For a Gaussian walk
the Wiener-Hopf factorisation collapses, because `P(S_n <= 0) = 1/2` exactly at
every `n`, and gives `E[H] = 1/sqrt(2)` in closed form. Twelve batches of 400,000
paths:

| | measured | exact target | z |
| --- | --- | --- | --- |
| `E[H]` | 0.707400 +- 0.000331 | 0.707107 (Wiener-Hopf) | **+0.88** |
| `E[H^2]/(2E[H])` | 0.582626 +- 0.000290 | 0.582597 (`-zeta(1/2)/sqrt(2pi)`) | **+0.10** |

`E[H]` is the load-bearing row. It is an exact value the simulation cannot know,
produced by the same estimator as the number under test, so it is the evidence
that the estimator is alive rather than returning its target - and it lands 0.88
standard errors off, which is a measurement rather than a tautology.

**The exact law also reproduces deriving.md's measured table better than
deriving.md's own correction does.** The two-sided problem, by the same
propagation:

| a:b | P(up) exact | measured, 86,411 bars a feed | E[tau] exact | measured | `(a+B)(b+B)` |
| --- | --- | --- | --- | --- | --- |
| 1:1 | 0.5000 | 0.5000 | **2.783** | 2.782 | 2.505 |
| 3:3 | 0.5000 | 0.5001 | **13.086** | 13.051 | 12.835 |
| 5:5 | 0.5000 | 0.5008 | **31.416** | 31.279 | 31.165 |
| 10:10 | 0.5000 | 0.5015 | **112.243** | 112.062 | 111.991 |
| 3:1 | **0.3073** | **0.3073** | **5.943** | 5.942 | 5.670 |
| 9:1 | 0.1422 | 0.1426 | **15.466** | 15.382 | 15.165 |
| 2:10 | 0.8039 | 0.8042 | **27.574** | 27.472 | 27.331 |

The `3:1` row is worth reading twice. [deriving.md](deriving.md) established on
174,501 trades that a stop one sigma below and a target three above is a 30.7%
shot rather than a textbook 25%, and the exactly propagated boundary-value
problem returns **0.3073** with no data in it at all. Over the seven geometries
the exact law's mean relative error on the expected duration is **0.5%** where
the `B`-shifted closed form is **2.9%** and the uncorrected continuous form is
**35.1%**.

**Ledger: none of the six pre-registered kill conditions fired.** They were that
the fitted shift is not flat in `a` (spread 0.00058 against a 0.01 threshold),
that the flat value misses the constant by more than 1% (0.058%), that the moved
plane scores worse than the textbook one anywhere at `a >= 2` (it is 50-70x
better everywhere), that `E[H^2]/(2E[H])` misses by 3 standard errors (z = +0.10),
that `E[H]` misses `1/sqrt(2)` by 3 standard errors (z = +0.88), and that any
quantity reproduces its target to more digits than its own error bar allows.

**New description or relabelling?** Separably both. That 0.5826 is the expected
overshoot of a Gaussian walk is classical and is in Broadie-Glasserman-Kou;
**reproducing it is confirmation, not novelty** - and it is now confirmed on this
project by three independent routes, the option-formula correction in
[deriving.md](deriving.md), a rebuild that produces it from nothing but a
volatility and a tick rate in [rebuilding.md](rebuilding.md), and the boundary
condition here, which itself arrives by three internal routes that share no
arithmetic. What the imaginary-time reading adds is *transportable*: BGK give a
correction to two formulas, an extrapolation length gives the boundary condition,
and a boundary condition applies to every barrier question on these instruments
including the ones nobody has written a closed form for. The desk's practical
gain is one line - **when a barrier sits inside three monitoring sigmas,
propagate the density instead of correcting the continuous formula** - and at a
1:1 barrier that is 2.783 minutes against 2.505.

## Two: the Range Break ladder, and the control that reframes it

A range is a box, and a particle in a box has a discrete spectrum. That is the
sharpest prediction available here, because a classical range model gives one
number - a half-life - where a box gives a **ladder**:

    lambda_k = (k*pi/W)^2 * D,      ratios 1 : 4 : 9 : 16

and a restoring force gives a different one. An Ornstein-Uhlenbeck generator is
the quantum harmonic oscillator Hamiltonian up to the similarity transform by the
square root of its own stationary density, so its spectrum is evenly spaced:

    lambda_k = k*theta,             ratios 1 : 2 : 3 : 4

Which ladder appears says which object this is, hard walls or a spring, and those
are different instruments. The estimator that separates them is sharp for a
reason worth stating: for **any** eigenfunction of the generator,
`E[phi_k(X_{t+n}) | X_t] = exp(-lambda_k n) phi_k(X_t)`, so the autocorrelation of
an eigenfunction is a *pure* single exponential with no contamination from any
other mode. The autocorrelation of price itself is not - for a reflecting box its
expansion is `sum_{k odd} exp(-lambda_k n)/k^4`, in which **the first mode carries
98.55% of the variance and the third carries 1.22%**, so reading a ladder off it
means resolving a 1% component decaying nine times faster than the one that
dominates.

### The control fired, and it is the most useful result on this page

Before any market data, `quantspec.py` runs a **driftless random walk** through
the identical estimator. A free walk has no discrete spectrum at all. Twelve
replicates, one long episode each:

| truth | true `l2/l1` | recovered | recovered `l3/l1` | true `l3/l1` |
| --- | --- | --- | --- | --- |
| box | 4.00 | **3.992 +- 0.056** | 8.987 | 9.00 |
| spring | 2.00 | 2.211 +- 0.026 | 3.941 | 3.00 |
| **free walk** | *none* | **3.551 +- 1.024** | **8.539** | *none* |

**A free random walk reproduces the particle-in-a-box ladder.** It has to, and
the reason is not subtle once seen: binning a diffusion by its own empirical
quantiles makes the observed support the box, and a diffusion in a box has box
eigenvalues. So **observing 1:4:9 in a financial series is not evidence of
confinement** - it is evidence that the observation window was finite, which it
always is. Any result of that shape without this control has measured its own
window. That is the specific numerology this field invites, and it would have
been published here had the control not been run first.

### What survives is the scaling, and it is not the ratio

For a free walk the leading rate is set by the window, `lambda_1 ~ pi^2 D /
W_window^2` with `W_window^2 ~ D*m`, so `lambda_1` falls like `1/m` for ever. For
a real box `lambda_1 = pi^2 D / W^2` is a property of the instrument and stops
falling once the window exceeds the relaxation time. So the confinement test is a
**knee**, and 200 replicates at the real sample size - 86,410 bars in episodes of
86.5 - give it:

| truth | m=8 | m=12 | m=16 | m=24 | m=32 | m=48 | m=64 | log-log slope | shallowest |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| box | 0.7347 | 0.4768 | 0.3715 | 0.2792 | 0.2372 | 0.1988 | 0.1804 | -0.66 | **-0.34 +- 0.04** |
| spring | 0.7349 | 0.4850 | 0.3852 | 0.2991 | 0.2608 | 0.2264 | 0.2110 | -0.58 | **-0.25 +- 0.04** |
| free walk | 0.5766 | 0.3408 | 0.2446 | 0.1573 | 0.1171 | 0.0784 | 0.0595 | **-1.08** | **-0.92 +- 0.06** |

The free walk sits on `-1` at every window length, as it must, and the two
confined truths flatten toward zero. The separation is about **ten standard
deviations**, so the confinement question is decisively answerable at this sample
size. The true `lambda_1` of both simulated truths is 0.1588 per bar, and the
box's curve is still at 0.1804 at m=64, so even the plateau is biased upward by
about 14% by the finite window - which is why the measured number has to be read
against simulated truths and not against a formula.

A second discriminator needs no spectrum at all. A reflecting box has a
**uniform** stationary density, excess kurtosis -1.2; a spring has a **Gaussian**
one, 0.0. Standardised within-window excess kurtosis, same replicates:

| truth | m=8 | m=16 | m=32 | m=64 |
| --- | --- | --- | --- | --- |
| box | 0.411 | 0.043 | -0.374 | **-0.693** |
| spring | 0.300 | 0.164 | 0.054 | **+0.008** |
| free walk | 0.575 | 0.594 | 0.597 | **+0.596** |

Three-way separation, and the spring lands at +0.008 against a Gaussian's exact
0.000. **That is the pattern this folder is supposed to hunt** - a statistic on
its null - so it is worth saying why it is not a dead column: the same estimator
returns -0.693 and +0.596 on the other two truths from the same code path, the
null here is the alternative hypothesis rather than the absence of one, and the
box's -0.693 is nowhere near the uniform's -1.200 because a 64-bar window cannot
see the whole stationary density.

### The ladder itself, at the real sample size

Pooling episodes forces de-meaning each one, because the level of a range moves
when it breaks, and that biases every rate. So the recovered ratio is **not 4 and
not 2**, and the only honest comparison is against simulated truths through the
identical pipeline:

| truth | `l2/l1` | sd | 95% interval | `l3/l1` | AR(1) half-life |
| --- | --- | --- | --- | --- | --- |
| box | **2.908** | 0.054 | [2.790, 3.007] | 4.881 | 4.41 |
| spring | **2.154** | 0.023 | [2.112, 2.202] | 3.826 | 3.81 |
| free walk | **1.846** | 0.046 | [1.751, 1.931] | 4.017 | 39.12 |

The three intervals do not overlap and the best single-cut error separating box
from spring is **0.0% over 200 replicates**, so the measurement has the power.
The cosine and Hermite eigenfunction projections do *not* survive the de-meaning
- they return 1.208 and 1.580 where the transfer operator returns 2.908 and
2.154 - so only the basis-free estimator is usable and the elegant one is not.

**The classical control does half the job and that is the honest verdict.** The
AR(1) half-life is 39.12 on a free walk against 4.41 and 3.81 on the two confined
truths, so **one number already answers "is this confined"** and the knee test is
a more careful version of the same classical idea. What the AR(1) cannot do is
separate 4.41 from 3.81, which is box from spring. So the spectral machinery
earns its place on exactly one question - *which* confinement - and claiming more
for it would be notation.

### The prediction, written down before the data exists

[deriving.md](deriving.md) section four's ex-break variance ratio is itself a
measurement, so it can be inverted for the box it implies. Fitting one relaxation
mode to the two shortest lags - `n=1` and `n=5`, the only ones where under 6% of
pairs can straddle a break - gives:

| | RB100 | RB200 |
| --- | --- | --- |
| `lambda_1` (per one-minute bar) | 0.159 | 0.114 |
| relaxation time `tau_1` | 6.3 bars | 8.8 bars |
| implied range width | 49 units | 56 units |
| `lambda_2` **if a box** | **0.635** | **0.456** |
| `lambda_2` **if a spring** | 0.318 | 0.228 |
| `lambda_3` **if a box** | **1.430** | **1.026** |
| `lambda_3` **if a spring** | 0.477 | 0.342 |

with the caveat that the long-lag flatness in that published table - 0.283, 0.274,
0.279 at `n` = 100 to 1000 - is **the stitching and not the process**: dropping
break bars and concatenating glues independent episodes end to end, and glued
episodes diffuse. Only the short lags carry the confinement, which is why the
calibration uses them and why the measurement that settles this must work *within*
an episode and never across one.

The relaxation times are the operational point. `tau_2` is **1.6 bars on RB100
and 2.2 on RB200**, so the second mode is at the edge of what one-minute bars can
resolve and **this measurement belongs on ticks**, where there are sixty samples
a bar. That is a statement about the instrument worth making before running
anything, and it is what a power analysis is for.

### And then it was measured twice, because the first run starved its own estimator

The lab came back and the tick leg ran. It reported the ladder unreadable on two
usable episodes of RB100 and three of RB200, and blamed the tick history. **That
was wrong, and the fault was in this harness rather than in the feed.**

The episode filter kept only episodes of `2 * TICK_WINDOWS[-1]` = 8,192 ticks or
more, on the reasoning that an episode must be long enough to hold a lagged pair
at the longest window. That is not what the pipeline needs. `windowed` already
drops the remainder inside each episode, so a short episode contributes no
windows at the long lengths and costs nothing; and the ladder - the statistic
that answers box against spring - runs at a lag of **60 ticks** and needs an
episode two orders of magnitude shorter. **The filter was sized by the least
important statistic and applied to all of them.** RB100 breaks about every 5,190
ticks, so a threshold of 8,192 kept the tail of a geometric draw and nothing
else.

Relaxing it to four lags keeps **20 episodes and 86,376 ticks on RB100** against
2 and 32,688, and **6 and 86,225 on RB200** against 3 and 81,171. The same
threshold now also cuts the *simulated* truths, which matters more than the
threshold: the de-meaning bias is a function of the episode-length distribution,
so filtering the feed and not the simulation compares a truncated geometric
against an untruncated one and calls the difference a spectrum. The old code did
exactly that.

So the honest correction to the previous paragraph is that **the ladder needed
twelve times the tick history only because the harness was throwing nine tenths
of it away.** The stored day is enough.

### The width, and the scan that is itself the box test

The width had been read off whatever sample the filter happened to leave, and it
moved from 45.6 to 34.0 when the filter was relaxed. **Neither number is the
width.** A short episode has not explored its range and understates it, so
averaging per-episode variances over a sample containing short episodes biases
the estimate down; keeping only very long episodes fixes that bias and leaves two
episodes of noise, which is what the published 45.6 was.

The fix is to stop picking a sample and scan the width against the minimum
episode length, because **the shape of that scan is the test**. A box
equilibrates in a few `tau_1 = 2W^2/pi^2`, so past a cut of a few relaxation
times the estimate must stop moving. A width that keeps climbing is a process
that never equilibrates inside its range, which is not a box however
sub-diffusive it looks between breaks.

| min episode (ticks) | RB100 eps | RB100 W | RB200 eps | RB200 W | vol_75 eps | vol_75 W |
| --- | --- | --- | --- | --- | --- | --- |
| 240 | 20 | 34.0 | 6 | 53.6 | 31 | 74.5 |
| 512 | 19 | 34.7 | 6 | 53.6 | 24 | 82.6 |
| 1024 | 15 | **38.0** | 5 | 58.5 | 12 | 106.2 |
| 2048 | 11 | **38.5** | 4 | 60.4 | 6 | 123.7 |
| 4096 | 8 | **37.8** | 3 | 67.1 | 1 | 129.9 |
| 8192 | 2 | 45.6 | 3 | 67.1 | - | - |
| 16384 | 1 | 39.0 | 1 | 94.3 | - | - |

**RB100 saturates at about 38 units** - flat to 2% across the last three usable
cuts, on 15, 11 and 8 episodes - and `tau_1` at that width is 293 ticks, so the
plateau begins exactly where a box says it must. The mean within-episode range
tracks it the whole way (37.5, 38.4, 37.6), so the two estimators agree at every
cut and not just at one.

**The `volatility_75_index` row is the control and it is the reason the plateau
can be read at all.** That feed is Brownian motion with no range, its "breaks"
are the detector firing on nothing, and its width climbs 74.5, 82.6, 106.2,
123.7, 129.9 over the same cuts - **+74% and still rising**, because a free
path's range grows without limit. RB100 moves 11% and stops. Without that row a
plateau would just be an assertion about a table.

**RB200 does not saturate**: 53.6, 58.5, 60.4, 67.1, still climbing, on seven
breaks in the stored day. It is reported as not converged rather than given a
number, and the honest statement is that it is somewhere above 60.

That settles the three-way disagreement, though not the way the previous draft of
this page said. This page's eigenvalue inversion said **49 and 56**;
[rebuilding.md](rebuilding.md)'s fit said **one shared 60 for both**; the earlier
tick read said 45.6 and 67.1 and was two and three episodes. The feed says
**RB100 is about 38 and RB200 is above 60**. The inversion is 29% high on RB100;
**the shared width is refuted** by a factor of at least 1.6 between the two
indices, which was the previous conclusion and survives at a different pair of
numbers; and the number this page itself published a few hours ago was undersampled
and is corrected here.

### The ladder, measured: it is not a box

With the sample restored, the pre-registered gate is checked before the measured
value is read against anything - the simulated box and the simulated spring must
separate by two replicate standard deviations at the sample actually achieved, or
nothing is reported. Both feeds pass, narrowly: two-sd gaps of **+0.021 and
+0.010**. Simulated truths are run at the feed's own tick count, episode length
and *saturated* width, through the identical pipeline.

| RB100, W = 37.8 | `l2/l1` | vs measured | `l3/l1` | knee | kurtosis |
| --- | --- | --- | --- | --- | --- |
| simulated box | 3.197 +- 0.334 | **-3.4 sd** | 5.826 | -0.25 | -0.894 |
| simulated spring | 2.212 +- 0.147 | -0.9 sd | 4.049 | -0.23 | -0.015 |
| simulated free walk | 2.183 +- 0.330 | -0.3 sd | 4.707 | -0.77 | +0.364 |
| **measured** | **2.076** | | 3.910 | **-0.24** | **-0.322** |

| RB200, W = 58.5 | `l2/l1` | vs measured | `l3/l1` | knee | kurtosis |
| --- | --- | --- | --- | --- | --- |
| simulated box | 3.559 +- 0.375 | **-4.2 sd** | 7.404 | -0.46 | -0.582 |
| simulated spring | 2.377 +- 0.211 | -1.9 sd | 4.601 | -0.42 | +0.013 |
| simulated free walk | 2.565 +- 0.556 | -1.1 sd | 5.782 | -0.83 | +0.352 |
| **measured** | **1.976** | | 4.942 | **-0.67** | **-0.210** |

**The hard box is excluded on both feeds, at 3.4 and 4.2 standard deviations.**
That is the result, and it is the first statement on this page about what Range
Break *is* rather than about what an estimator does. `1:4:9` is not the ladder of
this instrument.

**The spring is not excluded** - the measured values sit 0.9 and 1.9 standard
deviations below it - and **the ladder on its own cannot establish confinement at
all**, because the free-walk control covers the measurement on both feeds. That
is section two's own warning applied to section two's own result, and it would be
dishonest to skip it.

What establishes the confinement is the other two readings, which the ladder does
not need:

* **the knee.** RB100 is at **-0.24** against a simulated box's -0.25, a spring's
  -0.23 and a free walk's **-0.77**. On the scaling of `lambda_1` with window
  length RB100 is confined and is nowhere near a free walk.
* **the classical control, which is one number.** The AR(1) half-life is **164
  ticks** on RB100 against **11,176** on `step_index` - a feed
  [deriving.md](deriving.md) proves is a fair coin to `p = 0.499734 +- 0.000220`,
  run through the identical code path. Two orders of magnitude.
* **the stationary density.** RB100's within-window excess kurtosis is **-0.322**
  against a box's -0.894, a spring's -0.015 and a free walk's +0.364: confined,
  and between the two confined shapes.

So the reading that survives all of it: **Range Break 100 is confined, and its
confinement is at or below the harmonic limit rather than at the box limit.** In
WKB terms `lambda_k ~ k^alpha` with `alpha <= 1`, so the well is `V ~ |x|^p` with
`p <= 2` - softer than a spring, not merely softer than a wall. RB200 says the
same thing about the ladder at 4.2 standard deviations from the box, but its knee
(-0.67) sits toward the free walk and its width has not converged, so on RB200
only the negative half is reportable.

**And `step_index` is still the control that makes all of this legible.** It
returns `l2/l1 = 3.751` on one 86,393-tick episode - a provable fair coin
returning very nearly the box's ladder, because with one long episode the window
*is* the box. The same estimator on the same feed cut into 20 episodes returns
2.183 for a simulated free walk. **The free walk's apparent ladder is a function
of the episode length, which is exactly why the calibration has to be run at the
feed's own episode length and why a ratio quoted without one is worthless.**
**Ledger: three of ten fired, and the third is the section's result.**

Condition 1 fired - the estimator does not recover 4 and 2 at the real sample
size, because pooling episodes forces de-meaning - and the response was to
calibrate against simulated truths rather than to move the threshold. Condition 3
fired - the free-walk control is not distinguishable from the box on the raw
ladder - and that reframed the whole section. **Condition 9 fired**: the measured
ladder was pre-registered to land *strictly between* the simulated spring and the
simulated box if [rebuilding.md](rebuilding.md)'s soft edge was right, and it
landed **below the spring on both feeds**. That is a refutation in a direction
neither page allowed for, which is the useful kind.

Condition 10 was added when the first tick run could not read its own ladder, and
it is a gate rather than a hypothesis: the ladder may not be read at all unless
box and spring separate by two replicate standard deviations at the sample
achieved. It is checked and printed before the measured value is compared to
anything. It **held, narrowly** - gaps of +0.021 and +0.010 - and it is fair to
say the RB200 leg is at the edge of what six episodes can support.

The six that held were the power (0.0% single-cut separation error over 120
replicates), the knee (box -0.335 +- 0.040 against the walk's -0.919 +- 0.057),
the ladder against the free-walk control at bar resolution, the density test, the
void check, and the retired curvature test - retired before the data was seen,
because the cosine and Hermite projections do not survive the de-meaning at all.

## Two and a half: rebuilding.md's soft edge is a shallow ladder, and that is one prediction from two directions

[rebuilding.md](rebuilding.md) rebuilds Range Break as a reflecting band plus a
memoryless break and fits it to the same published curve. Under **one shared
range width of 60 lattice steps** - fewer parameters than two free widths, and a
closer fit, joint mean absolute error 0.0363 against 0.047 - it is left with a
residual that is **too confined at one minute and too free at twenty**, and reads
that as the edge of the range being *softer than a wall*. That is a qualitative
conclusion from a variance-ratio fit. The spectrum turns it into a number.

**The shared width has since been refuted by the feed itself** - RB100 saturates
at about 38 units and RB200 is above 60 and has not converged, in the section
above - so the arithmetic below is re-run at the measured widths rather than at
60. It changes the relaxation times and not the argument.

**First, the twenty minutes is not an arbitrary scale.** A reflecting box relaxes
on its slowest mode in `tau_1 = 2W^2/pi^2` ticks at unit step variance, which at
60 steps is 729 ticks, or **12.2 minutes**. So twenty minutes is `1.6 tau_1`, and
the residual sits on the box's own clock. `quantspec.py` computes 1.64 and
[rebuilding.md](rebuilding.md) reaches 1.6 from the other side - the same
arithmetic from a fitted curve and from an eigenvalue. That is what says the
residual is a **shape error in the relaxation** and not a missing timescale.

| | fitted band | **measured band** | `tau_1` at the measured band | 20m in `tau_1` | residual at 20m |
| --- | --- | --- | --- | --- | --- |
| RB100 | 60 steps | **37.8** | 4.9 min | **4.10** | +0.047 |
| RB200 | 60 steps | **> 60** | > 12.2 min | **< 1.64** | +0.024 |

At the *fitted* 60 the relaxation time is 12.2 minutes and twenty minutes is
1.64 relaxation times on both feeds, which is how both pages arrived at the same
1.6 from different evidence. At the measured widths RB100 is at 4.1 relaxation
times and RB200 is at most 1.64 - still of order one on both, so the residual
still sits on the box's own clock, but the two feeds are not at the same point on
it. That is the same disagreement as the width, seen in the time domain.

**Second, `1:4:9` is a ceiling and not one option among several.** WKB gives
`lambda_k ~ k^alpha` with `alpha = 2p/(p+2)` for a well `V ~ |x|^p`, which rises
to 2 as the wall hardens and never passes it:

| well | `p` | `alpha` | `lambda_2/lambda_1` |
| --- | --- | --- | --- |
| harmonic - a spring | 2 | 1.00 | **2.00** |
| soft wall | 6 | 1.50 | 2.83 |
| stiff wall | 18 | 1.80 | 3.48 |
| hard box | infinity | 2.00 | **4.00** |

Nothing that confines relaxes faster than a hard box at matched `lambda_1`. That
removes a whole class of candidate repairs before anyone writes one.

**Third, and this is the convergence.** If the edge really is softer than a wall
then `alpha < 2` strictly, so

> **the measured `lambda_2/lambda_1` on Range Break must land strictly between 2
> and 4, and where it lands measures the wall: `p = 2*alpha/(2-alpha)`.**

Two pages, two kinds of evidence - a variance-ratio fit over three orders of
magnitude in horizon, and an eigenvalue ladder - make the same prediction, and it
is falsifiable in both directions. **4 refutes the soft edge**; **2 says the range
is a harmonic well and not a box at all**; anything between measures how hard the
wall is, which is a property of the instrument that neither page can currently
name. It is pre-registered here as kill condition 9, and section two shows this
sample separates 2 from 4 with a single-cut error of 0.0%.

**It has now been measured, and it came in under the floor rather than inside the
interval.** Against simulated truths through the identical pipeline the measured
`lambda_2/lambda_1` is **2.076 on RB100 and 1.976 on RB200**, against simulated
springs at 2.212 and 2.377 and simulated boxes at 3.197 and 3.559. So the
prediction is refuted in the one direction the table above does not have a row
for: not a hard box, not a soft wall, and **not even a spring** - the ladder sits
at or below the harmonic value, which in this family means `alpha <= 1` and a
well `V ~ |x|^p` with `p <= 2`. The soft-edge scan
[rebuilding.md](rebuilding.md) ran covers `p = q+1` for `q >= 1`, so it was
searching from the harmonic value upward, and the answer is at the other end of
its range.

That is the useful form of a refutation: the impasse - no single confinement
matching the ex-break shape and the all-bars flatness at once - is not going to be
resolved by making the wall harder, because the within-episode spectrum says the
wall is softer than the softest thing that page tried.

**And that measurement now has a second job, because the soft edge has since been
built and it does not settle things.** [rebuilding.md](rebuilding.md) has scanned
a lattice walk with up-probability `0.5 - k(|x|/half)^q sign(x)` - which is this
same `V ~ |x|^p` family with `p = q+1`, a reflecting box as `q` grows and a
harmonic well at `q = 1`. Softening the edge **buys 12% on the ex-break curve and
costs a third of the all-bars flatness, on both feeds**, and that page's verdict
after four experiments is that *no single confinement matches the ex-break shape
and the all-bars flatness at once* - [deriving.md](deriving.md) section four's two
headline facts are in tension at the 10-30% level under every mechanism tried.

The ladder is the right instrument for exactly that impasse, and the reason is
structural rather than rhetorical: **a variance-ratio curve mixes the confinement
and the break into one number, and an eigenvalue does not.** The transfer-operator
ladder is measured strictly within episodes and never uses a break bar, so it
reports the shape of the confinement without having to satisfy the all-bars
constraint at the same time. If the ex-break curve wants a soft edge and the
all-bars flatness wants a hard one, the within-episode ladder says which of the
two is describing the confinement and which is describing the break.

**The answer it gives is that the confinement is the soft half.** The ladder never
touches a break, and it says `p <= 2`. So a rebuild that wants to match the
all-bars flatness with a harder wall is fitting the *break* with the wall, and the
two headline facts are in tension because one of them is not about the
confinement. That is what the eigenvalue buys over the variance ratio, and it is
the one thing on this page that a classical range model could not have said.

## Three: reconstructing the path inside a bar, which is the part with money in it

A bar is a coarse-graining of a tick path, and recovering the interior from
`(O, H, L, C)` is a boundary-value problem for the propagator: the path is a
Brownian bridge pinned at `O` and `C` and confined to `[L, H]`, and the
conditional law of the interior is the ratio of two propagators. The propagator
between two absorbing walls is the free kernel plus an **infinite lattice of
image charges**, which is section one with one wall replaced by two - and it is
the Poisson-summation dual of the eigenmode expansion section two uses, images
converging fast at short times and eigenmodes at long ones. `quantbridge.py`
evaluates the conditional law exactly by forward-backward recursion on a price
grid, which is the same object with no series truncated.

**The classical control here is an identity, and that settles half the question
before any measurement.** For a driftless random walk observed exactly at bar
closes, the Kalman smoother's conditional mean between observations *is* the
Brownian bridge mean, and the Brownian bridge mean *is* linear interpolation. The
harness checks it rather than asserting it: the maximum absolute difference over
200 bars is **7.1e-15**. So the `(O, C)` half of this construction is pure
notation. What the path integral adds that a linear-Gaussian filter cannot
represent is the conditioning on `H` and `L`, because a running maximum is not a
linear functional of the state. **The entire measurable content of the bridge is
therefore: how much do the high and the low tell you about the interior?**

On 20,000 simulated bars of 15 sub-steps built from 20 ticks each - so that `H`
and `L` are set by a finer path than the one being reconstructed, exactly as in
the data:

| method | RMSE, in bar sigmas | against linear |
| --- | --- | --- |
| linear = Kalman = `(O,C)` bridge | 0.42133 | - |
| OHLC zigzag (what charts draw) | 0.38771 | -7.98% |
| **conditioned bridge** | **0.36241** | **-13.98%** |

`H` and `L` remove **26.0%** of the residual variance that `O` and `C` leave
behind, and the nominal 90% band contains the truth **85.1%** of the time, which
is inside the pre-registered [85%, 95%] but only just.

**And it holds on real bars, which is the harder test.** The local store has no
generated feed, so this ran on real instruments - fat tails, volatility
clustering, neither of which the construction assumes. Fifteen-minute
`(O, H, L, C)` reconstructed at one minute, scored against the one-minute closes
that actually happened:

| feed | n bars | linear | zigzag | **bridge** | gain | 90% coverage |
| --- | --- | --- | --- | --- | --- | --- |
| btc, Deriv | 416 | 0.5059 | 0.5149 | **0.4399** | **+13.06%** | 80.2% |
| btc, Binance | 453 | 0.5333 | 0.5386 | **0.4706** | **+11.76%** | 77.4% |
| gold, Deriv | 264 | 0.4233 | 0.4572 | **0.3681** | **+13.04%** | 87.5% |
| eurusd, Deriv | 249 | 0.4363 | 0.4551 | **0.3784** | **+13.28%** | 87.1% |

**Eleven to thirteen per cent on all four**, and note that the zigzag - the only
other `(H, L)`-aware method - is *worse* than linear on every real feed while
being better than linear in simulation. So the gain is the conditional law rather
than the mere fact of using `H` and `L`. The coverage runs 77% to 88% against a
nominal 90%, which is under-coverage and is the expected direction: the per-bar
sigma is estimated from the bar's own range, and a noisy volatility estimate
fattens the standardised residual.

**And then it ran on the synthetics, which is the clean test, because the
generating process is known exactly.** `research.db` carries one-minute bars
*and* ticks for the Deriv feeds, so the fifteen-minute bar is built from fifteen
one-minute bars - its high and low are still tick extremes, because its
constituents' are - and the same test runs a second way with **the true tick path
as the target rather than a coarser sample of it**. The `tick` rows are therefore
the only place in this folder where "how close is the reconstruction to the real
series" is a measurement rather than an inference.

**The attainment ancilla is also now built rather than costed.** The bridge above
conditions on *containment* - the path stayed inside `[L, H]` - and not on
*attainment*, that it actually touched both. Attainment is two extra bits of
state, "has the running maximum reached `H` yet" and the same for `L`, which in
imaginary-time language enlarges the state space and in practice is a
forward-backward pass over four copies of the grid instead of one.

| target | feed | n | linear | zigzag | containment | **attainment** | gain | 90% coverage |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| agg | volatility_75 | 5757 | 0.4444 | 0.4423 | 0.3802 | **0.3372** | +24.12% | 88.7% |
| agg | volatility_100 | 5757 | 0.4489 | 0.4400 | 0.3826 | **0.3359** | +25.18% | 89.0% |
| agg | volatility_75_1s | 5757 | 0.4414 | 0.4400 | 0.3778 | **0.3341** | +24.32% | 89.1% |
| agg | step_index | 5757 | 0.4370 | 0.4367 | 0.3751 | **0.3336** | +23.67% | 89.0% |
| agg | range_break_100 | 5757 | 0.5206 | 0.5393 | 0.4682 | **0.4559** | +12.43% | 78.8% |
| agg | range_break_200 | 5757 | 0.4998 | 0.5202 | 0.4438 | **0.4265** | +14.67% | 81.1% |
| agg | boom_500 | 5757 | 0.4765 | 0.4066 | 0.4089 | **0.3415** | +28.33% | 89.7% |
| agg | jump_75 | 5757 | 0.4541 | 0.4472 | 0.3932 | **0.3506** | +22.78% | 88.1% |
| **tick** | volatility_75 | 719 | 0.4952 | 0.4616 | 0.4172 | **0.3577** | **+27.76%** | 87.8% |
| **tick** | volatility_100 | 698 | 0.4782 | 0.4479 | 0.4077 | **0.3528** | **+26.22%** | 88.0% |
| **tick** | step_index | 1439 | 0.4630 | 0.4455 | 0.3956 | **0.3535** | **+23.64%** | 88.0% |
| **tick** | range_break_100 | 1440 | 0.4883 | 0.4738 | 0.4203 | **0.3814** | **+21.89%** | 85.4% |
| **tick** | boom_500 | 1411 | 0.2250 | 0.1975 | 0.2310 | **0.2146** | +4.62% | 96.9% |

**Attainment beats containment by +10.36% on average across the thirteen cells,
range [+2.63%, +16.49%]** - against the **+9.88%** this page costed it at by
blending in the zigzag out of sample. The estimate was good to half a point, and
this is the construction itself rather than a proxy for it. On simulation the
ancilla takes the bridge from 0.36241 to 0.30306, **+16.38%**.

Against the true tick path, attainment removes **48%, 46%, 42% and 39%** of the
interior variance that linear interpolation leaves on volatility_75,
volatility_100, step_index and range_break_100 - against containment's 29%, 27%,
27% and 26%. **So a little under half of what a bar hides is recoverable from
`(O, H, L, C)`, and slightly more than half is not.** That is the number the real
feeds could not produce, because on real data the target is the one-minute close
and not the path.

**The one cell where the bridge loses is `boom_500` on ticks, and kill condition 5
fired on it.** Containment is 0.2310 against linear's 0.2250 - the bridge is
**2.7% worse**. That is the right feed to fail on: Boom is drift plus a compound
Poisson spike, the bar's high is set by a single jump, and a Brownian bridge told
to stay under that high spends the whole bar being pulled toward a level the
process reached in one tick and left. Attainment repairs it to +4.62%, because
"the maximum was *attained*" is a much better description of a jump than "the
maximum was not exceeded". The 96.9% coverage on that row says the same thing
from the other side: the uncertainty is badly overstated because the bar's range
is not a volatility.

Note also that the two Range Break rows are the weakest of the eight `agg` cells
(+12.43% and +14.67%, coverage 78.8% and 81.1%) and the only ones where the
*zigzag* is worse than linear. A confined process inside a bar is not a Brownian
bridge, and section two has just measured how it is not.

**Where the money is, stated precisely.** [deriving.md](deriving.md) proves
`E[net] = -(c/2) * turnover` for any predictable position on a martingale, so
none of this is an entry rule. What it is is a **better estimate of latent state
from cheap data**: the desk holds far more bar history than tick history, and
every replay, every stop-placement study and every barrier statistic computed
from bars is currently using linear interpolation or the zigzag inside the bar.
Replacing that with the conditioned bridge removes a quarter of the interior
variance for the cost of a forward-backward pass. It does not create an edge; it
stops a measurement being wrong.

## Four: the quote grid is a measurement operator, and the Kalman smoother is its Gaussian approximation

[twins.md](twins.md) found `volatility_150_1s_index` quoted too coarsely to carry
any tick statistic, so the rounding is real and measurable. The quoted price is
the latent price through a quantiser, and recovering the latent state is
deconvolution. The exact posterior uses the true likelihood - the latent lay
somewhere inside the cell that was printed - which in imaginary-time language is
a projective measurement and a conditioned density. The classical control treats
the rounding as additive noise of variance `Delta^2/12` and runs a Kalman
smoother, which is what everyone does.

| `Delta/sigma` | raw quote | Kalman | exact | exact against Kalman |
| --- | --- | --- | --- | --- |
| 0.25 | 0.0725 | 0.0722 | 0.0722 | +0.00% |
| 0.50 | 0.1451 | 0.1426 | 0.1425 | +0.00% |
| 1.00 | 0.2887 | 0.2669 | 0.2669 | -0.02% |
| 2.00 | 0.5723 | 0.4625 | 0.4615 | +0.22% |
| 4.00 | 1.1549 | 0.7936 | **0.7516** | **+5.29%** |
| 8.00 | 2.2555 | 1.5442 | **1.3096** | **+15.19%** |

**Up to `Delta/sigma = 2` the Kalman smoother is the exact posterior to within
0.22%, so the density-matrix framing there is a relabelling and is reported as
one.** It only starts paying when the grid is coarser than twice the per-step
volatility, and then it pays a lot. That is a threshold the desk can check per
feed rather than a claim about method, and it is exactly the regime
[twins.md](twins.md) quarantined a feed for.

**Ledger: none of the seven pre-registered conditions fired** across sections
three and four - the bridge beat linear on simulation (+13.98%) and on all four
real feeds, `H` and `L` cleared the 2% floor by a factor of seven, the Kalman
identity held to 7.1e-15, the 90% band covered 85.1%, the exact posterior beat
the smoother somewhere (+15.19%), and no two different estimators returned the
same number.

## Two questions that are closed, and one that was not attempted

**Quantum walks are excluded, and the measurement that excludes them is already
in print.** A discrete-time quantum walk spreads ballistically, variance `~ t^2`,
Hurst exponent 1.0, with a two-horned arcsine-like return density.
[cascading.md](cascading.md) measured **H = 0.50 and kurtosis 3.00 on all twelve
Volatility indices** - both the two-second and the one-second families, so the
1s twins are included - and [twins.md](twins.md) found every one within two
standard errors of its advertised volatility with per-tick variance differing by
exactly `sqrt(2)` between a twin pair. Ballistic spreading is excluded at
H = 0.50 against 1.00. This is a closed question and re-opening it on the 1s
family would be re-running a measurement that exists.

**A stable-law jump kernel is the wrong non-local operator for Boom and Crash.**
The fractional Schrodinger equation is the fashionable object here - replace the
Laplacian by `|k|^alpha` - but [deriving.md](deriving.md) has the *measured* jump
distribution, with `E[J] = lambda * E[g]` holding to `|z| <= 1.21` on all six
feeds, and it is not stable. The exact generator is `-g d/dx + lambda (E[f(x+J)]
- f(x))`, whose propagator is the inverse Fourier transform of
`exp(t * (-ikg + lambda(phi_J(k) - 1)))` and needs no fractional anything. So the
one-parameter caricature is strictly worse than the exact kernel that is already
available, and the fractional-operator literature adds nothing to this book.

**State tomography was not attempted.** The Wigner function of (price, momentum)
is well defined for these processes and its negativity is the standard test of
whether a quantum description is doing any work; for a classical diffusion it
should not be negative, and measuring that and reporting the null would bound how
far the analogy goes. It is not here, and the reason is that it needs the
empirical propagator, which needs tick data, which needs the lab.

## What this does not say

* **Nothing here is measured on a Deriv synthetic.** The lab was unreachable
  throughout. Sections one, two and four are exact evaluations or simulation;
  section three's real leg is four *real* instruments from the local store.
  Where [deriving.md](deriving.md)'s measured table appears it is used as
  published, not re-measured.
* **The 0.5826 result is a confirmation, not a discovery**, and the page says so
  twice. What is new is that it is a boundary condition, which makes it apply to
  problems with no closed form.
* **Section two's ladder is a prediction and not a result.** Its first
  pre-registered kill condition fired on the estimator, and its third fired on
  the control, which is why the free-walk result is reported before anything
  else. The measured leg is one command: `./.secrets/lab.sh run
  research/harness/quantspec.py`.
* **Section three's real leg is four feeds and 249 to 453 bars each.** Enough to
  establish the sign and roughly the size of a 13% effect, not enough to pin it,
  and the coverage shortfall says the uncertainty model is imperfect even where
  the mean is good. The synthetics would give 86,411 bars a feed.
* **The bridge assumes constant volatility inside the bar.** It is estimated from
  the bar's own range, so there is no look-ahead, but a bar containing a
  volatility burst is mis-specified and the under-coverage is where that shows.
* **None of this earns money by itself.** `E[net] = -(c/2) * turnover` is a
  theorem about any predictable position on a martingale and a change of notation
  does not escape it. The only thing here with a plausible price attached is
  section three, and what it buys is a less wrong measurement rather than an
  edge.

## What follows

1. **Run the three harnesses on the lab the moment it is reachable.**
   `./.secrets/lab.sh run research/harness/quantspec.py` settles the Range Break
   ladder against a prediction two pages now agree on, and
   `./.secrets/lab.sh run research/harness/quantbridge.py` repeats section three
   on 86,411 bars a feed instead of 249 to 453. Neither needs a change.
2. **Measure where in the range a break happens**, as a fraction of the range
   width. It is one query, it needs no model, and it decides whether the
   ex-break curve everything here is calibrated against is biased by conditioning
   on survival.
3. **Replace linear interpolation with the conditioned bridge wherever a replay
   reads inside a bar.** It removes a quarter of the interior variance for the
   cost of one forward-backward pass, it beat linear on all four real feeds by 11
   to 13%, and it is the only thing on this page with a price attached - a less
   wrong measurement rather than an edge.
4. **Build the attainment conditioning.** Two extra bits of state, "has the
   running maximum reached `H`" and the same for `L`, turn the boundary condition
   into a larger state space and are worth a further 9.88% out of sample. That is
   as much again as everything section three currently buys.
5. **Check `Delta/sigma` per feed before trusting any tick statistic.** Below 2
   the Kalman smoother is the exact posterior and there is nothing to do; above
   it the exact treatment is worth 5 to 15%, and
   [twins.md](twins.md) has already quarantined one feed for exactly this.
6. **Do not re-open the quantum walk.** H = 0.50 on all twelve Volatility indices
   excludes ballistic spreading, the measurement is in
   [cascading.md](cascading.md), and it covers the 1s family too.
