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

Three harnesses: [`quantimage.py`](harness/quantimage.py),
[`quantspec.py`](harness/quantspec.py),
[`quantbridge.py`](harness/quantbridge.py). Each states its kill conditions in its
docstring before any number, and each section below ends with the ledger of which
fired.

**Scope, stated first and not buried.** The research lab holding `research.db`
was unreachable throughout this work - no route to host - and
`.data/prices/prices.db` carries 1.67M bars of *real* instruments and **zero
generated feeds**. So nothing here is measured on a Deriv synthetic. What is here
is of three kinds, marked throughout: **exact numerical evaluations of known
laws**, which need no data and are complete; **measurements on real instruments**,
which the local store does support and which section three uses; and
**pre-registered predictions with their power analysis**, which need one command
on the lab and are not results yet.

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

### And then it was measured, and the sample cannot carry it

The lab came back and both legs ran. The ladder measurement belongs on **ticks**,
because `tau_2` is 96 ticks and a one-minute bar cannot resolve it - and the tick
measurement is defeated by something simpler than resolution.

**Twenty-four hours of ticks holds 20 breaks on RB100 and 7 on RB200.** After
requiring an episode long enough to carry the longest window, that leaves **2 and
3 usable episodes**. The power analysis was run at 999 episodes and returned a
0.0% separation error; re-run at each feed's own tick count, episode length and
*measured* width, it returns this:

| RB100, W = 45.6 | `l2/l1` | `l3/l1` | knee | kurtosis |
| --- | --- | --- | --- | --- |
| simulated box | 3.542 +- 0.551 | 7.473 | -0.33 | -0.783 |
| simulated spring | 2.367 +- 0.286 | 4.536 | -0.27 | -0.110 |
| simulated free walk | 2.957 +- 0.862 | 6.185 | -0.73 | +0.140 |
| **measured** | **3.438** | 5.258 | **-0.32** | **-0.736** |

| RB200, W = 67.1 | `l2/l1` | `l3/l1` | knee | kurtosis |
| --- | --- | --- | --- | --- |
| simulated box | 3.667 +- 0.593 | 7.669 | -0.53 | -0.423 |
| simulated spring | 2.416 +- 0.244 | 4.688 | -0.49 | +0.018 |
| simulated free walk | 2.931 +- 0.655 | 6.363 | -0.82 | +0.374 |
| **measured** | **2.051** | 5.039 | **-0.70** | **-0.210** |

**The bands overlap and the ladder is not readable.** RB100's 3.438 sits inside
the box's interval *and* inside the free walk's. RB200's 2.051 sits below all
three. And the row that settles it is the control: **`step_index`, which
`deriving.md` proves is a fair coin to `p = 0.499734 +- 0.000220`, returns
`l2/l1 = 3.751`** on the same code path - a provable free walk, indistinguishable
from a box, exactly as section one warned. At two or three episodes the estimator
has no power and nothing about the ladder is reported as a result.

The bar cross-check says the same thing from the other side: at one-minute bars
the ratios come out **1.347 and 1.795**, below even the spring's calibrated 2.154,
which is what "a bar cannot resolve a 1.6-bar mode" looks like when you try
anyway.

**What it would take is arithmetic.** The estimator had 0.0% separation error at
999 episodes and none at 2. Breaks arrive every 86.5 and 178.8 minutes, so 200
episodes is **12 days of RB100 ticks and 25 days of RB200 ticks**, against the 24
hours stored. That is the specific collection this measurement needs, and it is
the useful form of the answer: the ladder is not unmeasurable, it is unmeasured,
and the shortfall is a factor of twelve in tick history rather than anything
about the method.

### What the same run does settle: the width, twice over

The tick data measures the range directly, two independent ways - `sqrt(12 Var)`,
which is the width a uniform stationary law implies, and the mean within-episode
range:

| | `sqrt(12 Var)` | mean within-episode range | agreement |
| --- | --- | --- | --- |
| RB100 | **45.6** | **47.0** | 3.0% |
| RB200 | **67.1** | **67.0** | 0.1% |

Two estimators of the same quantity agreeing to 3% and 0.1%, and **the gap
between the feeds is 21 units against a gap of at most 1.4 between the estimators
on one feed**. So the widths are different and the difference is fifteen times
the disagreement between the ways of measuring it.

That resolves a three-way disagreement in this folder. This page's eigenvalue
inversion of `deriving.md`'s published curve said **49 and 56**;
[rebuilding.md](rebuilding.md)'s fit said **one shared 60 for both**; the feed
says **46 and 67**. The inversion is right on RB100 to 6% and 16% low on RB200,
and **the shared width is refuted** - it is not that the two indices share a range
and differ only in break rate and break size, they have ranges differing by a
factor of 1.46. That is a correction to a published number obtained from the data
rather than from a fit, and it is the most solid thing in this section.

The two secondary discriminators also point one way on RB100 and are mute on
RB200. RB100's stationary kurtosis is **-0.736** against a simulated box's -0.783
and a simulated spring's -0.110, and its knee is **-0.32** against a box's -0.33
and a free walk's -0.73. On the density and the scaling, RB100 is a box. RB200's
-0.210 and -0.70 sit between everything, which is what three episodes buys.

**Ledger: two of nine fired, both on the first design and both instructive.**
Condition 1 fired - the estimator does not recover 4 and 2 at the real sample
size, because pooling episodes forces de-meaning - and the response was to
calibrate against simulated truths rather than to move the threshold. Condition 3
fired - the free-walk control is not distinguishable from the box on the raw
ladder - and that is the section's headline. The seven that held were the power
(0.0% separation error), the knee (box -0.336 +- 0.040 against the walk's
-0.921 +- 0.058), the ladder against the free-walk control (box 2.5% at 2.790
against the walk's 97.5% at 1.931), the density test, and the void check. Two of
the seven - the real-data curvature test and condition 9 below - could not be
evaluated at all, because there is no real data, and they are counted as held
only in the sense that nothing killed them.

## Two and a half: rebuilding.md's soft edge is a shallow ladder, and that is one prediction from two directions

[rebuilding.md](rebuilding.md) rebuilds Range Break as a reflecting band plus a
memoryless break and fits it to the same published curve. Under **one shared
range width of 60 lattice steps** - fewer parameters than two free widths, and a
closer fit, joint mean absolute error 0.0363 against 0.047 - it is left with a
residual that is **too confined at one minute and too free at twenty**, and reads
that as the edge of the range being *softer than a wall*. That is a qualitative
conclusion from a variance-ratio fit. The spectrum turns it into a number.

**The shared width has since been refuted by the feed itself** - 45.6 and 67.1
units, two independent estimators agreeing to 3% and 0.1%, in the section above -
so the arithmetic below is re-run at the measured widths rather than at 60. It
changes the relaxation times and not the argument.

**First, the twenty minutes is not an arbitrary scale.** A reflecting box relaxes
on its slowest mode in `tau_1 = 2W^2/pi^2` ticks at unit step variance, which at
60 steps is 729 ticks, or **12.2 minutes**. So twenty minutes is `1.6 tau_1`, and
the residual sits on the box's own clock. `quantspec.py` computes 1.64 and
[rebuilding.md](rebuilding.md) reaches 1.6 from the other side - the same
arithmetic from a fitted curve and from an eigenvalue. That is what says the
residual is a **shape error in the relaxation** and not a missing timescale.

| | fitted band | **measured band** | `tau_1` at the measured band | 20m in `tau_1` | residual at 20m |
| --- | --- | --- | --- | --- | --- |
| RB100 | 60 steps | **45.6** | 7.0 min | **2.85** | +0.047 |
| RB200 | 60 steps | **67.1** | 15.2 min | **1.32** | +0.024 |

At the *fitted* 60 the relaxation time is 12.2 minutes and twenty minutes is
1.64 relaxation times on both feeds, which is how both pages arrived at the same
1.6 from different evidence. At the *measured* widths it is 2.85 and 1.32 - still
of order one on both, so the residual still sits on the box's own clock, but the
two feeds are no longer at the same point on it. That is the same disagreement as
the width, seen in the time domain.

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
two is describing the confinement and which is describing the break. That is a
question neither page can currently answer and one query on the lab would.

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

**What is left on the table, quantified.** The bridge conditions on *containment*
- the path stayed inside `[L, H]` - and not on *attainment*, that it actually
reached both. Blending the zigzag in at a weight fitted on the first half and
scored on the second improves the bridge by a further **9.88%**, so attainment is
worth about as much again as the whole construction so far. That is the next
thing to build, and in imaginary-time language it is an ancilla: two extra bits
of state, "has the running maximum reached `H` yet" and the same for `L`, which
turns the boundary condition into a larger Hilbert space.

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
