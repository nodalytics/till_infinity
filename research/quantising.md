# The diffusion equation is the Schrodinger equation in imaginary time, and here is what that buys

Under the Wick rotation `t -> -i*tau` the heat equation becomes the Schrodinger
equation, a transition density becomes a propagator, a drift becomes a gauge
potential and a barrier becomes a boundary condition. That is an identity, not a
metaphor, and [deriving.md](deriving.md) has just made it usable here by
establishing what the Deriv synthetics actually are: the Volatility indices are
driftless Brownian motion at a published sigma, Step Index is a fair coin on a
0.1 lattice, Range Break is genuinely confined between breaks, and Boom and Crash
are drift plus compound Poisson. Each of those is a textbook quantum system - a
free particle, a tight-binding lattice, a particle in a box, a non-local jump
operator - so everything a physicist knows about propagators, spectra and
boundary conditions is already a statement about these price processes.

The field this borrows from is full of classical results in borrowed notation, so
the rule on this page is that **every quantum construction is scored against a
classical control doing the same job, and where the control matches, the page
says the framing is notation**. Two of the four sections below reach exactly that
verdict and say so.

Three harnesses: [`quantimage.py`](harness/quantimage.py),
[`quantspec.py`](harness/quantspec.py), [`quantbridge.py`](harness/quantbridge.py).
Each states its kill conditions in its docstring before any number, and the
ledger of which fired is at the bottom of each section.

**Scope, stated first.** The research lab holding `research.db` was unreachable
for the whole of this work - no route to host - and `.data/prices/prices.db`
carries 1.67M bars of real instruments and **zero generated feeds**. So the tick
and bar legs on the synthetics themselves are written and not run. What is here
is therefore of two kinds, marked throughout: **derivations and numerical
evaluations**, which need no data and are complete, and **pre-registered
predictions with their power analysis**, which need one command on the lab and
are not results yet. Nothing measured on the synthetics is claimed.

## One: the 0.5826 is an extrapolation length, and that is a boundary condition rather than a correction

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
against the exact discretely monitored law, computed by convolving the density
with the one-step Gaussian and zeroing it beyond the wall, iterated. That is the
Chapman-Kolmogorov recursion evaluated numerically with no asymptotics anywhere;
its only error is the space grid, and halving the grid four times moves the
hundred-step survival by `1.2e-06`.

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
is **0.058%**, and the flatness is the point: a boundary condition is a property
of the wall and cannot know how far away the barrier is, so a shift that drifted
with `a` would be a fitted fudge rather than a wall. It does not drift. The
column at `a = 1` sits at 0.5871 rather than 0.5822, which is
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
and the wrong-constant control is only a third better than the textbook - so the
measurement has the power to say *which* constant, which is what makes the first
column readable.

**The same constant as an overshoot.** The walk crosses between quotes and is
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
produced by the same estimator as the number under test, so it is the proof that
the estimator is alive rather than returning its target - and it lands 0.88
standard errors off, which is a measurement rather than a tautology.

**And the exact discrete law reproduces deriving.md's measured table better than
deriving.md's own correction does.** The two-sided problem, solved by the same
propagation:

| a:b | P(up) exact | measured on 86,411 bars a feed | E[tau] exact | measured | `(a+B)(b+B)` |
| --- | --- | --- | --- | --- | --- |
| 1:1 | 0.5000 | 0.5000 | **2.783** | 2.782 | 2.505 |
| 3:3 | 0.5000 | 0.5001 | **13.086** | 13.051 | 12.835 |
| 5:5 | 0.5000 | 0.5008 | **31.416** | 31.279 | 31.165 |
| 10:10 | 0.5000 | 0.5015 | **112.243** | 112.062 | 111.991 |
| 3:1 | **0.3073** | **0.3073** | **5.943** | 5.942 | 5.670 |
| 9:1 | 0.1422 | 0.1426 | **15.466** | 15.382 | 15.165 |
| 2:10 | 0.8039 | 0.8042 | **27.574** | 27.472 | 27.331 |

The `3:1` row is the one worth reading twice. [deriving.md](deriving.md)
established on 174,501 trades that a stop one sigma below and a target three
above is a 30.7% shot rather than a textbook 25%, and the exactly propagated
boundary-value problem returns **0.3073** with no data in it at all. Over the
seven geometries the exact law's mean relative error on the expected duration is
**0.5%** where the `B`-shifted closed form is **2.9%** and the uncorrected
continuous form is **35.1%**. So the practical consequence is small and concrete:
`(a+B)(b+B)` is a good approximation, and where the barrier is inside three
monitoring sigmas the propagation itself is better and costs a second.

**Ledger: none of the six pre-registered kill conditions fired.** They were that
the fitted shift is not flat in `a` (spread 0.00058 against a 0.01 threshold),
that the flat value is not the constant to 1% (0.058%), that the moved plane
scores worse than the textbook one anywhere at `a >= 2` (it is 50-70x better
everywhere), that `E[H^2]/(2E[H])` misses the constant by 3 standard errors
(z = +0.10), that `E[H]` misses `1/sqrt(2)` by 3 standard errors (z = +0.88), and
that any quantity reproduces its target to more digits than its own error bar
allows.

**Is this a new description or a relabelling?** Both, in separable parts. That
0.5826 is the expected overshoot of a Gaussian walk is classical and is in
Broadie-Glasserman-Kou; **reproducing it is confirmation, not novelty**, and it
is now confirmed on this project by three independent routes - the option-formula
correction in [deriving.md](deriving.md), a rebuild that produces it from nothing
but a volatility and a tick rate in [rebuilding.md](rebuilding.md), and the
boundary condition here. What the imaginary-time reading adds is *transportable*:
BGK give a correction to two formulas, an extrapolation length gives the
boundary condition, and a boundary condition applies to every barrier question on
these instruments including the ones with no closed form. The desk's practical
gain is one line - **when a barrier sits inside three monitoring sigmas, propagate
the density instead of correcting the continuous formula** - and it is worth
about 2.4 points of expected duration at a 1:1 barrier.

## Two: the Range Break ladder, the control that reframes it, and the prediction left on the table

A range is a box, and a particle in a box has a discrete spectrum. That is the
sharpest prediction available here, because a classical range model gives one
number - a half-life - where a box gives a **ladder**:

    lambda_k = (k*pi/W)^2 * D,      ratios 1 : 4 : 9 : 16

and a restoring force gives a different one. An Ornstein-Uhlenbeck process's
generator is the quantum harmonic oscillator Hamiltonian up to the similarity
transform by the square root of its own stationary density, so its spectrum is
evenly spaced:

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

### The control fired, and it is the most useful result in this section

Before any market data, `quantspec.py` runs a **driftless random walk** through
the identical estimator. A free walk has no discrete spectrum at all. It returns

    lambda_2/lambda_1 = 3.86 +- 0.18,   lambda_3/lambda_1 = 8.63

against a box's 4 and 9.

**A free random walk reproduces the particle-in-a-box ladder to within 4%.** It
has to, and the reason is not subtle once seen: binning a diffusion by its own
empirical quantiles makes the observed support the box, and a diffusion in a box
has box eigenvalues. So **observing 1:4:9 in a financial series is not evidence of
confinement** - it is evidence that the observation window was finite, which it
always is. Any result of that shape without this control has measured its own
window. That is the specific numerology this field invites, and it would have
been published here had the control not been run.

### What survives is the scaling, not the ratio

For a free walk the leading rate is set by the window: `lambda_1 ~ pi^2 D /
W_window^2` with `W_window^2 ~ D*m`, so `lambda_1` falls like `1/m` for ever. For
a real box `lambda_1 = pi^2 D / W^2` is a property of the instrument and **stops
falling** once the window is longer than the relaxation time. So the confinement
test is a **knee** in `lambda_1(m)` and the plateau it flattens onto is the
measurement; only once a knee exists does the ladder ratio mean anything at all.

A second discriminator needs no spectrum: a reflecting box has a **uniform**
stationary density, excess kurtosis -1.2, and a spring has a **Gaussian** one,
excess kurtosis 0.0. On 86,000 observations that separates them on its own, and
it is cheaper than the spectrum.

### The prediction, written down before the data exists

[deriving.md](deriving.md) section four's ex-break variance ratio is itself a
measurement, so it can be inverted for the box it implies. Fitting one relaxation
mode to the two shortest lags - `n=1` and `n=5`, the only ones where under 6% of
pairs can straddle a break - gives, for RB100, `lambda_1 = 0.159` per bar, a
relaxation time of **6.3 bars** and an implied width of **49 units**; for RB200,
`lambda_1 = 0.114`, **8.8 bars** and **56 units**. So the pre-registered
prediction is

| | RB100 | RB200 |
| --- | --- | --- |
| `lambda_1` (per one-minute bar) | 0.159 | 0.114 |
| `lambda_2` **if a box** | **0.635** | **0.456** |
| `lambda_2` **if a spring** | 0.318 | 0.228 |
| `lambda_3` **if a box** | 1.430 | 1.026 |
| `lambda_3` **if a spring** | 0.477 | 0.342 |

with the caveat that the long-lag flatness in that published table - 0.283, 0.274,
0.279 at `n` = 100 to 1000 - is **the stitching and not the process**: dropping
break bars and concatenating glues independent episodes end to end, and glued
episodes diffuse. Only the short lags carry the confinement, which is why the
calibration uses them and why the measurement that settles this has to work
*within* an episode and never across one.

The relaxation times are the operational point. `tau_2` is **1.6 bars on RB100
and 2.2 on RB200**, so the second mode is at the edge of what one-minute bars can
resolve and **this measurement belongs on ticks**, where there are sixty samples
per bar, not on bars. That is a statement about the instrument to make before
running anything, and it is the kind of thing a power analysis exists to produce.

### The classical control

An AR(1) half-life is what this desk would otherwise fit, and it is printed beside
every spectral number in the harness. It returns one number for a box, one for a
spring and one for a free walk, and it does not order them. That is the honest
comparison: the spectral machinery is doing something the classical control
cannot, *provided* the knee test establishes confinement first.

**Status: the measured leg has not been run.** `research.db` is on the lab and the
lab is down. `quantspec.py` skips the measured section with a printed notice
rather than producing nothing silently, and the one command is
`./.secrets/lab.sh run research/harness/quantspec.py`.

## What this does not say

* **Nothing here is measured on a Deriv synthetic.** The lab was unreachable
  throughout. Section one is exact numerical evaluation of a known law and needs
  no data; section two is a derivation plus a power analysis on simulated
  processes whose spectra are known by construction. Where a number below is
  compared with [deriving.md](deriving.md)'s measured table, that table is being
  used as published, not re-measured.
* **The 0.5826 result is a confirmation, not a discovery.** It is in
  Broadie-Glasserman-Kou. What is new here is only that it is a boundary
  condition, which makes it apply to problems with no closed form.
* **Section two's ladder is a prediction and not a result**, and its first
  pre-registered kill condition already fired once on the estimator, which is why
  the free-walk control is reported before anything else.
* **None of this earns money.** [deriving.md](deriving.md) proves
  `E[net] = -(c/2) * turnover` for any predictable position on a martingale, and a
  change of notation does not escape a theorem. The only places anything here
  could pay are the two that page already named - better estimates of latent state
  from cheap data, and barrier pricing against a venue quote - and the first of
  those is section three, which is not finished.
