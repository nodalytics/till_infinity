# The ground state is the stationary density, and that hands you a learning algorithm

[quantising.md](quantising.md) established that the Wick rotation makes each Deriv
generator a textbook quantum system and then used it to read propagators,
boundary conditions and spectra. This page asks the next question: **if these
processes are quantum systems, can a learning algorithm be derived from the
mechanics rather than borrowed from the literature and dressed in it?**

Five constructions are derived here. Four turn out to be classical results in
different notation or to lose to their own classical control, and the page says
which and by how much; one is new, cheap, and answers a question
`quantising.md` could not. Along the way the derivation gets
pointed at `till_infinity/trading/barriers.py`, which landed this week and prices
a stop-and-target geometry under an explicitly unvalidated Brownian assumption,
and **the largest number on this page is that `barriers.duration` understates how
long a real trade takes by 25% at tight geometries and by 96% at ten sigmas, on
19 of 19 real feeds.**

Four harnesses: [`groundlib.py`](harness/groundlib.py) (the shared estimators, no
claims), [`groundstate.py`](harness/groundstate.py),
[`groundbarrier.py`](harness/groundbarrier.py),
[`groundslow.py`](harness/groundslow.py). Each states its kill conditions in its
docstring before any number, and each section ends with the ledger of which
fired.

**Scope.** The derivations are exact and need no data. The measurements are on
`research.db` - 60 days of one-minute bars and a 24-hour tick snapshot across 53
feeds, of which 19 are real markets and the rest are the Deriv synthetics whose
generators [deriving.md](deriving.md) and [rebuilding.md](rebuilding.md) have
pinned. Nothing here is a trading rule, and [deriving.md](deriving.md)'s theorem
says nothing here can be: `E[net] = -(c/2) x turnover` for every predictable
position on a martingale. What is on offer is a **better conditional estimate**,
which is what [spending.md](spending.md) says the desk's weakness actually is.

## One: the box and the spring are one formula, not two facts

[quantising.md](quantising.md) reads its Range Break ladder against a dictionary
it takes as given - a reflecting band is the particle in a box and gives
`1:4:9`, an Ornstein-Uhlenbeck generator is the harmonic oscillator up to a
similarity transform and gives `1:2:3`. Those are presented as two separate
textbook facts. They are one.

A reversible diffusion `dX = b dt + sqrt(2D) dW` with stationary density `p` has
`b = D (log p)'` - that is what reversibility means in one dimension - and its
generator is self-adjoint in `L^2(p)` with Dirichlet form

    <f, -L f>_p  =  D * Integral p(x) f'(x)^2 dx

The Rayleigh-Ritz principle - *the ground state minimises the energy, each
excited state minimises it subject to orthogonality to the ones below* - then
says the relaxation rates are the successive minima of
`D Int p f'^2 / Int p f^2` over functions orthogonal to the constants.
Equivalently the ground-state transform `psi = sqrt(p)` conjugates the generator
into `H = -D d^2/dx^2 + V` with

    V(x) = D [ (1/4) ((log p)')^2 + (1/2) (log p)'' ]

and `H sqrt(p) = 0` exactly, so **the stationary density is the ground state and
the relaxation rates are the excitation energies.**

What is worth stopping on is what is not on the right-hand side. **No transition
data.** Under the reversible-diffusion hypothesis the whole spectrum is a
functional of the marginal density and one diffusivity, and the *ratios* do not
need even that. So `lambda_2/lambda_1` - the number `quantising.md` measures from
the dynamics on 86,376 ticks - is predicted by the histogram with nothing dynamic
in it at all.

`groundlib.static_rates` evaluates the Dirichlet form with piecewise-linear
finite elements rather than forming `V`, because `V` needs two numerical
derivatives of an estimated density and the Dirichlet form needs none. It reduces
to a `p`-weighted graph Laplacian against a `p`-weighted mass. Fed the two exact
densities, with no simulation and no data anywhere:

| density | cells | `lambda_1` / true | `l2/l1` | `l3/l1` | true ladder |
| --- | --- | --- | --- | --- | --- |
| uniform | 64 | 0.99980 | 3.99759 | 8.98555 | 1 : 4 : 9 |
| uniform | 256 | 0.99999 | 3.99985 | 8.99910 | |
| **uniform** | **1024** | **1.00000** | **3.99999** | **8.99994** | |
| Gaussian | 64 | 0.97951 | 1.96942 | 2.90920 | 1 : 2 : 3 |
| Gaussian | 256 | 0.99870 | 1.99805 | 2.99415 | |
| **Gaussian** | **1024** | **0.99992** | **1.99988** | **2.99963** | |

`lambda_1` is checked against `(pi/W)^2 D` and `D/s^2`, which the estimator
cannot know. **The particle in a box and the harmonic oscillator are the same
formula evaluated at two densities**, and the dictionary `quantising.md` uses is
one line rather than two entries.

**Kill condition 1 held.** It would have fired if either ladder or either
`lambda_1` missed by more than 1% at the finest grid; the worst is 0.008%.

**And one knob is exposed rather than tuned.** The grid can be trimmed at the
tails, and trimming moves the reflecting boundary inward, and an inward wall is a
harder wall. On 400,000 exact Gaussian samples whose true ladder is 2.000, the
recovered value runs 1.994 at no trim, 2.032 at 0.02%, 2.102 at 0.1%, 2.269 at
0.5% and **2.567 at 2%** - a third of the way to a box, monotonically, on data
that is exactly a spring. A parameter that walks the answer toward the more
interesting hypothesis is precisely what this field hides in, so it is defaulted
to zero, documented in the function that owns it, and scanned wherever it is
used.

## Two: Range Break read from its histogram, which is a second opinion on a published result

[quantising.md](quantising.md) concluded that **Range Break is not a hard box**,
excluding `1:4:9` at 3.4 and 4.2 standard deviations, and that its confinement
sits at or below the harmonic value - `p <= 2` in a well `V ~ |x|^p`. That was
measured from the *dynamics*: Ulam's method on the lagged transition matrix,
within episodes, never across a break.

The static route is an independent second opinion, because it reads only the
marginal of the same data. Same ticks, same episode split, same de-meaning, same
uniform grid - and the joint law of `(x_t, x_{t+lag})` thrown away.

On `range_break_100_index`, 86,376 ticks in 20 episodes averaging 4,319, against
simulated truths run at that feed's own tick count, episode-length distribution
and stationary spread through the identical pipeline, 200 replicates each:

| | `l2/l1` from the **density** | `l2/l1` from the **dynamics** |
| --- | --- | --- |
| simulated box | 3.469 +- 0.243 | 3.007 +- 0.327 |
| simulated spring | 1.913 +- 0.227 | 1.942 +- 0.229 |
| simulated free walk | 2.381 +- 1.760 | 9.019 +- 21.808 |
| **measured RB100** | **1.911** | **1.275** |

**The density says Range Break 100 is a spring, to three decimal places**: 1.911
measured against a simulated spring's 1.913, and 6.4 replicate standard
deviations below a simulated box. That is `quantising.md`'s negative half
confirmed by a route that shares no arithmetic with it - and it lands on the
harmonic value rather than below it.

The dynamics on this page's own grid read 1.275, which is 2.9 standard deviations
*below* the simulated spring. `quantising.md`'s own dynamical read was 2.076
against its simulated spring's 2.212, 0.9 below. All three agree the wall is not
a box. **They disagree on how far past the spring to go, and the disagreement is
now a number rather than an impression** - which is the same tension
`quantising.md` flagged between its ladder and its kurtosis, since a kurtosis is
a statistic of the density and so is this.

That disagreement is not a nuisance. It is the point of section three: a density
and a dynamics that disagree are telling you the process is not a reversible
one-dimensional diffusion. Range Break is not one, because it breaks.

**`range_break_200_index` is not reported.** Six episodes, and the pre-registered
gate - a simulated box and a simulated spring must separate by two replicate
standard deviations at the sample achieved - **fails**: 3.174 +- 0.588 against
2.039 +- 0.388. `quantising.md` had to add the same gate for the same feed and
passed it by +0.010. Here it does not pass, so the honest report is "still
unmeasured", which is what a gate is for.

**And trimming reproduces the hazard on live data.** RB100's static ladder reads
1.911 at no trim, 1.977 at 0.05% and **2.255 at 0.2%** - so a reader who trimmed
the tails would have concluded the wall was harder than harmonic, on the same
ticks.

## Three: the ratio that measures whether the marginal is lying to you

There are now two estimates of the same spectrum: one from the histogram, one
from the transitions, on the same grid so that neither can blame the binning.
Under the reversible-one-dimensional-diffusion hypothesis they are the same
object, so

    R  =  lambda_1(dynamics) / lambda_1(density)

is that hypothesis written as a number, and `R != 1` says the process is not
Markov in what is observed, or its drift is not a gradient, or it is not a
diffusion. **This is the one genuinely new instrument on the page**, and it is
new only because nobody had both estimates on the same grid before.

It needs calibrating against things that should and should not move it. Four
controls, 200 replicates each, all through the episode-splitting and de-meaning
pipeline that Range Break's data gets, at Range Break's sample size, with the box
and the spring matched to the *same* `lambda_1` so the two truths differ in the
shape of the ladder and not in its speed:

| truth | `lambda_1` static | `lambda_1` Ulam | static `l2/l1` | **R** | AR(1) half-life |
| --- | --- | --- | --- | --- | --- |
| box | 0.00406 +- 0.00031 | 0.00405 +- 0.00043 | 3.472 +- 0.269 | 0.9986 +- 0.083 | 151.9 |
| spring | 0.00378 +- 0.00047 | 0.00388 +- 0.00049 | 1.924 +- 0.340 | 1.0288 +- 0.120 | 177.4 |
| free walk | 0.00033 +- 0.00020 | 0.00033 +- 0.00025 | 2.454 +- 2.375 | 1.2985 +- 1.797 | 1880.3 |
| **hidden volatility** | 0.00206 +- 0.00107 | 0.00387 +- 0.00050 | 2.302 +- 1.472 | **3.1803 +- 4.956** | 180.2 |
| **two timescales** | 0.00435 +- 0.00057 | 0.00428 +- 0.00057 | 1.876 +- 0.243 | 0.9886 +- 0.107 | 154.4 |

True `lambda_1` is 0.003417 for both confined truths. **`R` sits on 1.00 for a
genuine diffusion and moves to 3.18 when the marginal is a scale mixture that the
dynamics do not share** - which is exactly the failure it was built to see.

Two positive controls rather than one, and that was not the original plan. The
dry run had only the hidden-volatility process, and the implied-timescale scan -
the classical Markov test, `lambda_1` recovered at a ladder of lags, which is
flat for any Markov process - did not move on it at all. The reason is that the
two instruments detect different failures: **`R` catches a marginal that misleads
and the timescale scan catches memory**, and the first control has the former and
almost none of the latter. The second control, a sum of a fast and a slow
Ornstein-Uhlenbeck with its lag-1 autocorrelation matched to the plain spring so
that it is not merely *slower*, was added for the scan. Without the matching an
AR(1) half-life separated it with **zero** error, which would have been a control
for "is this slow" rather than for "is this Markov".

### The power table, and the classical control winning half of it

Best single-threshold misclassification rate between each pair of truths, 200
replicates, the same metric `quantising.md` uses so the two pages are comparable.
Zero means no overlap.

| discriminator | box vs spring | spring vs hidden | spring vs two-scale | box vs free |
| --- | --- | --- | --- | --- |
| **static ladder** (derived) | **0.003** | 0.330 | 0.450 | 0.070 |
| Ulam ladder (dynamics) | 0.025 | 0.280 | 0.445 | 0.220 |
| **Kramers-Moyal ladder** (classical control) | **0.000** | 0.285 | 0.445 | 0.136 |
| AR(1) half-life (what the desk would do) | 0.130 | 0.435 | 0.215 | **0.000** |
| **R** (derived) | 0.375 | **0.073** | 0.263 | 0.305 |
| implied-timescale slope (classical) | 0.367 | 0.383 | **0.143** | 0.395 |

Three things to read off it, and one of them is uncomfortable.

**On "which confinement", the classical control wins.** A Kramers-Moyal
generator - bin the state, estimate the drift and diffusivity as conditional
moments, take the eigenvalues, which is statistical physics with no Wick rotation
anywhere - separates a box from a spring with **zero** single-cut error. The
derived static route gets 0.003 and the dynamical Ulam ladder gets 0.025. So the
derivation is not the best available instrument for the question `quantising.md`
asked; it is merely a very good one that needs less. What it has that
Kramers-Moyal does not is that it needs no transitions, which is what makes `R`
possible at all.

**The static ladder beats the dynamical one by a factor of eight** on box against
spring, 0.003 against 0.025, at the sample size Range Break actually has. That is
worth saying plainly because `quantising.md` had to add a power gate after a run
whose dynamical ladder could not separate its own truths, and passed it by
+0.021 and +0.010. **The histogram would have passed it more comfortably than the
transition matrix did.**

**`R` is the only thing that sees a lying marginal, and the timescale scan is the
only thing that sees memory**, at 0.073 and 0.143 against every other row at 0.26
or worse. They are complementary rather than competing, and neither is redundant
with the AR(1) half-life the desk already has.

**Ledger for sections one to three: three of ten fired.**

Condition 3 fired - the static route's replicate interval does not cover the true
`lambda_1` on a simulated box, reading 0.00406 +- 0.00031 against 0.003417, which
is **+18.8% and 2.1 standard deviations high**. The cause is known and is not
this estimator's: `quantising.md` measured the same finite-window upward bias at
+14% on the same pipeline. It is why this page reads ladders and not rates, and
why every measured value is compared against a simulated truth through the
identical code rather than against a formula.

Condition 4a fired: `R` does not classify a *single* series - the hidden-volatility
control needs a gap of 10.15 to separate per-replicate and has 2.15. It was
restated during the dry run, before any feed was read, into a per-series form and
a comparative form, with the restatement narrowing what may be claimed rather
than widening it. **`R` is never quoted here as a verdict about one feed**, only
against a control arm of other feeds through the same code.

Condition 10, the timescale scan's comparative form, fired on its own control at
this sample: gap 0.059 against a requirement of 0.079. So the scan is reported as
the better *instrument* for memory on the single-cut metric and as **not powered
in the mean** at 200 replicates, which are both true and the second is the one a
reader should carry.

Condition 8 fired on `range_break_200_index` and that feed is not reported.
Conditions 1, 2, 5, 6, 7 and 9 held.

## Four: log realised volatility, and the feeds that provably have none

The instruments now get pointed at the quantity
`till_infinity/trading/barriers.py` takes as an input and holds constant for the
life of a trade. Its relaxation rate is the volatility half-life, and whether it
has one at all is the question.

**The control is what makes this readable.** [generators.md](generators.md)
measured no volatility clustering anywhere on the Deriv Volatility indices -
largest `|acf|` 0.017 against 0.219 on the real feeds - and
[cascading.md](cascading.md) has them at H = 0.50 and kurtosis 3.00. Their log
realised volatility is therefore estimation noise around a constant, and whatever
the estimator returns there is its own floor.

Log realised volatility over 30 one-minute bars, sampled every 30 bars so
successive points use disjoint returns:

| | n | `lambda_1` density | `lambda_1` dynamics | **R** | half-life, bars | lag-1 acf |
| --- | --- | --- | --- | --- | --- | --- |
| volatility_10_index | 2880 | 0.978 | 2.193 | 2.24 | **4.0** | -0.006 |
| volatility_50_index | 2880 | 0.989 | 2.029 | 2.05 | **4.0** | -0.006 |
| volatility_100_index | 2880 | 0.978 | 1.949 | 1.99 | **4.9** | -0.015 |
| btc | 2861 | 0.149 | 0.251 | 1.69 | **76.6** | 0.762 |
| gold | 1982 | 0.427 | 0.484 | 1.13 | **41.1** | 0.603 |
| eurusd | 2087 | 0.350 | 0.354 | 1.01 | **50.8** | 0.664 |
| usdjpy | 2087 | 0.138 | 0.266 | 1.92 | **67.3** | 0.734 |
| us30 | 1989 | 0.218 | 0.240 | 1.10 | **78.8** | 0.768 |
| audusd | 2086 | 0.375 | 0.527 | 1.40 | **30.2** | 0.502 |

Pooled: **the five control feeds have a mean volatility half-life of 5.0 bars and
a lag-1 autocorrelation of -0.018; the nineteen real feeds have 56.4 bars and
+0.66.** The control's floor is clean, the real feeds are an order of magnitude
past it, and kill condition 7 - which would have voided this leg if a family with
no clustering in it looked as persistent as gold - did not fire.

Note also what `R` does on the control: **2.0, not 1.0.** For an independent
sequence the dynamical route returns a large rate and the static route returns
1 by construction, so `R = 2` is the *iid* limit of this estimator at this
sample, not its null. The real feeds run from 1.00 to 1.92, so they sit between a
diffusion and noise, and the ones nearest 1 - eurusd 1.01, gbpjpy 1.00, usdcad
1.04 - are the ones whose volatility is best described as a one-dimensional
diffusion. **That is a reading only available because the control was run**, and
it is the second time on this page that a statistic's null turned out not to be
where it looked.

### And the threshold that falls out

`barriers.duration` returns `(a+B)(b+B)` bars. A 3:3 geometry is 12.8 bars, 5:5
is 31.2 and 10:10 is 112.0. The real feeds' volatility half-life is 30 to 79
bars. So **any geometry whose expected duration approaches the feed's own
volatility half-life is being priced at a volatility it will not still have**,
and the crossing happens at about 5:5 on this book. That is a derived statement
about when to stop trusting a closed form, from two numbers the desk can compute.

Section five measures what it costs.

## Five: when the Brownian assumption behind `barriers.py` actually fails

`till_infinity/trading/barriers.py` is candid in its own docstring - *"on real
markets it is a better prior than the continuous form and is not validated"*.
This validates it.

A stop-and-target trade is a first-passage problem between two absorbing walls,
which under the Wick rotation is a Schrodinger problem with two Dirichlet
boundaries, and `quantising.md` section one established the right boundary
condition for a wall watched on a grid: Robin, which to leading order is
Dirichlet at `a + B`. For a process that is not a free particle the same problem
is still exactly solvable by propagating the sub-stochastic operator with the
absorbing states deleted. So the whole question is **what state the operator is
defined on**, and that is where the physics has to earn its place.

Five arms, differing in one thing at a time, on the same trials, monitored the
same way - one-minute closes, `ticks_per_bar = 1`, so the shift is 0.5826
unmodified and this is the regime [deriving.md](deriving.md) validated:

| arm | carries |
| --- | --- |
| **A** | `barriers.py` itself - Gaussian, independent, constant volatility, Robin wall |
| **B** | the same law propagated exactly rather than approximated: a check on the propagator |
| **C** | the feed's **own** standardised-return histogram, still independent - the classical control |
| **D** | the same histogram plus a learned nine-state volatility chain - the transfer operator |
| **T** | the feed, non-overlapping trials, out of sample |

`A - T` is the total error; `A - C` is the part the marginal explains; `C - T` is
what is left for dependence; `D - T` is what the learned operator leaves.

**The propagator first, because a first-passage harness whose walls are wrong
measures its walls.** Arm B reproduces `quantising.md`'s independently propagated
table from a code path that shares nothing with it: `E[bars]` of 2.783, 13.086,
31.416 and 112.243 at 1:1, 3:3, 5:5 and 10:10, approached monotonically as the
space grid is refined (2.691, 2.752, 2.773 at 16, 48 and 144 cells per volatility
unit), and `P(up)` of 0.3073 at 3:1 and 0.1422 at 9:1. Every symmetric geometry
returns exactly 0.50000 at every grid. Condition 1 held: the worst `|A - B|` at
`min(a,b) >= 2` is **0.00056**.

Two bugs were found getting there and both are in the harness rather than the
module. The first grid put the start on a cell *edge*, which returned 0.50724,
0.49581, 0.50292 and 0.49813 on the symmetric geometries - oscillating in sign
and shrinking with the geometry, which is a parity artefact. A symmetric barrier
is the one answer known without any calculation, which is why it is the right
thing to be wrong on first. The second built the step law on its own grid and
re-rounded it onto the propagator's, which left every duration about 1% short.

### Where it holds, and where it does not

Pooled over feeds, mean absolute error in `P(target first)`, with `t` computed
across **feeds** rather than trials - because 19 index and FX feeds are not 19
independent samples and the between-feed spread is the honest denominator:

| group | geometry | trials | \|A-T\| | \|C-T\| | \|D-T\| | \|D shuffled-T\| | t over feeds | sign |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **GBM control** | 1:1 | 93,116 | **0.0025** | 0.0037 | 0.0038 | 0.0037 | 0.93 | 4/6 |
| GBM control | 3:1 | 43,353 | **0.0029** | 0.0053 | 0.0048 | 0.0047 | -0.27 | 3/6 |
| GBM control | 10:10 | 2,125 | **0.0152** | 0.0236 | 0.0253 | 0.0255 | 0.03 | 4/6 |
| **Boom/Crash** | 1:1 | 60,349 | 0.2706 | 0.0063 | **0.0034** | 0.0033 | 1.33 | 3/4 |
| Boom/Crash | 3:1 | 41,609 | 0.1579 | 0.0087 | **0.0053** | 0.0054 | 1.39 | 3/4 |
| **real feeds** | 1:1 | 192,709 | **0.0041** | 0.0068 | 0.0072 | 0.0073 | -0.99 | 11/19 |
| real feeds | 3:3 | 36,470 | **0.0081** | 0.0120 | 0.0136 | 0.0146 | 0.57 | 11/19 |
| real feeds | **3:1** | 85,754 | 0.0090 | **0.0082** | 0.0103 | 0.0156 | **-5.30** | **17/19** |
| real feeds | **1:3** | 86,192 | 0.0096 | 0.0081 | **0.0076** | 0.0087 | **+6.03** | **17/19** |
| real feeds | **1.36:1** | 159,677 | **0.0057** | 0.0070 | 0.0076 | 0.0080 | **-3.52** | 15/19 |

**Condition 2 held and it is the load-bearing row.** On six feeds
[deriving.md](deriving.md) proves are Brownian, arm A is the best of the five at
every one of ten geometries and every interval covers zero. The closed form is
right where its assumptions are exactly true, so a failure elsewhere is about the
market and not about the harness.

**Condition 3 held.** On Boom and Crash the closed form is wrong by **55.7
standard errors** at 1:1 and 30.8 at 3:1, which is what a compound Poisson must
do to a Gaussian first-passage formula. The test has power.

**On real feeds the closed form is unbiased at symmetric geometries and biased at
asymmetric ones.** At 1:1 through 10:10 the largest `|t|` over feeds is 1.50 and
the sign splits 10-11 of 19, which is a coin. At 3:1 and 1:3 it is -5.30 and
+6.03 with 17 of 19 feeds agreeing, and the two are **mirror images of each
other**, which is the signature of a symmetric fat tail and is not what a scan
artefact produces.

In points of hit rate, signed, with a 95% interval over the 19 feeds:

| geometry | `barriers.py` says | measured | **difference** | same on the GBM control |
| --- | --- | --- | --- | --- |
| 3:1 | 0.3064 | 0.3147 | **+0.0083 [+0.0052, +0.0113]** | +0.0004 [-0.0026, +0.0034] |
| 1:3 | 0.6936 | 0.6848 | **-0.0088 [-0.0117, -0.0058]** | -0.0032 [-0.0066, +0.0002] |
| 1.36:1 | 0.4489 | 0.4533 | **+0.0044 [+0.0019, +0.0069]** | +0.0012 [-0.0014, +0.0038] |
| 2:6 | 0.7182 | 0.7097 | -0.0086 [-0.0136, -0.0035] | -0.0007 [-0.0062, +0.0049] |
| 1:1 | 0.5000 | 0.5011 | +0.0011 [-0.0013, +0.0035] | -0.0011 [-0.0034, +0.0012] |

**A real feed reaches the far barrier about 0.85 points more often than the
closed form says, whichever side the far barrier is on**, and at the payoff
[spending.md](spending.md) says the book actually plans - 1.36:1 - it is +0.44
points. On the six feeds where the assumption is exactly true the same
construction returns +0.04 points with an interval covering zero.

**And the fix is the marginal, not the dynamics.** Arm C carries its own
estimation bias, which the control measures at -0.0043 at 3:1; on real feeds it
reads -0.0046. Subtracting each arm's own control-group value, arm A's excess at
3:1 is **+0.0079** and arm C's is **-0.0003**. The feed's own return histogram
removes 96% of it. The learned volatility operator does not improve on that, and
**condition 5 fired**: the regime-shuffled arm matches the unshuffled one almost
everywhere (0.0034 against 0.0033 on Boom at 1:1; 0.0072 against 0.0073 on real
feeds at 1:1), so what the operator buys is its regime-conditional *marginals* and
not the persistence of the chain. Condition 4 fires too: `|D-T| >= |C-T|` on a
majority of real feeds. **The transfer operator is notation here and the page
says so.**

### The duration, which is the number with money attached

`barriers.duration`'s own docstring says it is *"the number a hold timeout should
be set from and is not"*, and points at [spending.md](spending.md)'s finding that
the clock fired on 50 of 133 real-market trades at 5% of their planned target.
So: how long does the geometry actually take?

Measured duration divided by `barriers.duration`, mean over feeds:

| geometry | GBM control | **real feeds** | feeds with truth longer |
| --- | --- | --- | --- |
| 1:1 | 1.111 +- 0.004 | **1.251** | 19/19 |
| 2:2 | 1.047 | **1.209** | 19/19 |
| 3:3 | 1.047 +- 0.010 | **1.271 +- 0.055** | 19/19 |
| 5:5 | 1.053 +- 0.028 | **1.417 +- 0.091** | 19/19 |
| 10:10 | 1.091 +- 0.091 | **1.958 +- 0.215** | 19/19 |

The control column is the closed form's own known approximation error - 2.783
against 2.505 at 1:1 is a ratio of 1.111, which is `quantising.md`'s exactly
propagated value against the `(a+B)(b+B)` form - and it is **flat in geometry**,
as an approximation error should be.

The real-feed column is not flat. **At ten sigmas a real trade takes 1.96 times
as long as `barriers.duration` says, on 19 feeds out of 19, and the excess grows
monotonically with the geometry.** Against the control it is a factor of 1.79.

The mechanism is section four. The barriers are fixed at entry in units of the
entry volatility; the real feeds' volatility half-life is 30 to 79 bars; a
geometry that needs 112 bars is being held at a volatility that has had one and a
half half-lives to revert. Expected first-passage time is convex in `1/sigma`, so
the periods where volatility falls lengthen the trade by more than the periods
where it rises shorten it, and the average moves up.

**What does not work is the obvious repair.** The learned nine-state operator
reads 120.45 bars at 10:10 against a truth of 219.31 - it is *further* from the
answer than the closed form's 112.0. A nine-bin chain on the stationary log-volatility
distribution truncates exactly the tail that does the damage, which is the quiet
periods where a trade runs forever.

**And the cross-section is a warning about how to quote this.** The correlation
between a feed's volatility half-life and its duration excess is **+0.891 across
all 24 feeds** and **-0.11, +0.09 and -0.05 within the 19 real feeds alone**. The
+0.891 is entirely the separation between two clusters - synthetics with a 5-bar
half-life and no excess, real markets with a 56-bar half-life and a large one -
and there is no per-feed reading in it at all. Quoted without the within-group
number it would have been a regression on a dummy variable wearing a mechanism's
name.

What is usable is that the excess is **tight**: 1.271 +- 0.055 at 3:3 and 1.417
+- 0.091 at 5:5 across nineteen instruments spanning crypto, metals, FX and five
equity indices. One correction factor for real markets and none for the
synthetics, rather than a factor per feed.

**The drop rate is accounted.** Trials unresolved inside the horizon are a
selection - they are the quiet periods - so they are counted rather than
silently skipped, and the horizon scales with each geometry's own expected
duration. On real feeds the rate is 0.00% to 1.68%, and dropping the longest
trials biases the duration excess **down**, so 1.958 is if anything conservative.

**Ledger for section five: three of seven fired, and two of the three are the
result.** Condition 1 held (worst `|A - B|` 0.00056). Condition 2 held - the
closed form is best of five at all ten geometries on the GBM control. Condition 3
held - it fails at 55.7 standard errors on Boom and Crash, so the test has power.
**Condition 4 fired**: `|D-T| >= |C-T|` on a majority of real feeds, so the
learned operator is notation. **Condition 5 fired**: the regime-shuffled arm
matches the unshuffled one, so the chain's persistence buys nothing. Condition 6
held - no arm reproduces the feed to more digits than its standard error allows.
Condition 7 is why every interval in this section is a `t` over feeds.

## Six: the variational principle gives TICA, and PCA beats it

The transfer operator `T_tau f(x) = E[f(X_{t+tau}) | X_t = x]` is self-adjoint in
`L^2(p)` for a reversible process, and its Rayleigh quotient is

    rho[f]  =  <f, T_tau f>_p / <f, f>_p  =  Corr_tau( f(X) )

so the variational principle reads, here: **the slowest coordinates of a process
are the functions of maximal autocorrelation at lag `tau`, found one at a time
under orthogonality.** Restricted to linear combinations of a lag-embedded state
the stationary points solve `C_tau v = mu C_0 v`, which is TICA. That is a
derivation and not an analogy - and it is not a new one. It is the variational
approach to conformational dynamics; TICA itself is Molgedey and Schuster.
Derived here, not invented here.

It is worth running because it is a genuinely *different objective* from the one
the desk would otherwise use: PCA solves `C_0 v = sigma v` and maximises
variance, TICA maximises autocorrelation, and they coincide only when the two
covariances share an eigenbasis. So the control is PCA on the identical
lag-embedded matrix at the identical rank on the identical split.

32 lags of log absolute return, fitted on the first half of each feed and scored
on the second, target log realised volatility over the next 30 bars:

| | TICA-1 | TICA-3 | TICA-8 | PCA-1 | PCA-3 | PCA-8 | flat 20-bar | ridge, all 32 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| mean over 19 real feeds | 0.5041 | 0.5041 | 0.5251 | **0.5163** | **0.5301** | **0.5311** | 0.5079 | 0.5267 |
| mean over 6 control feeds | 0.0000 | -0.0001 | -0.0004 | 0.0000 | 0.0000 | -0.0002 | -0.0005 | -0.0012 |

**PCA beats TICA at every rank**, by 0.012, 0.026 and 0.006 of out-of-sample
`R^2`. **Kill condition 2 fired**, and in the direction the page was written to
allow for: the derived objective is not merely matched by the classical control,
it loses to it.

And the more useful comparison is the third from the right. **A flat 20-bar mean
of log absolute return - one number, and the thing
[volatility.md](volatility.md) already found beating the shipping estimator at
every interval - scores 0.5079 against the best method's 0.5311.** The entire
spread between the worst construction here and the best is 0.027 of `R^2`, and
the desk's existing one-number baseline captures **95.6%** of what the best of
them reaches. Thirty-two lags, two projections, five ranks and a ridge, to add
two points of `R^2` over an average.

**The control feeds are the reason that is readable.** On six feeds
[generators.md](generators.md) proves have independent increments, every method
returns `R^2` between +0.0002 and -0.0016 - zero to three decimals. Kill
condition 3 technically fired on four of them, where the "clears the permutation
floor" flag went true at `R^2 = 0.0002` against a floor of 0.0001; that is the
flag's own granularity at the fourth decimal rather than a finding, and it was
hunted rather than explained away.

The other two targets are nulls and both are worth having. **The excursion, once
divided by the volatility estimate, is not predictable at all** - every real feed
returns a negative out-of-sample `R^2` between -0.004 and -0.006, so how far
price reaches in volatility units carries nothing beyond the volatility scaling
itself. And direction is negative everywhere, which is
[winning.md](winning.md)'s null arriving from a different direction on a
different sample.

### And the entanglement spectrum says why, before any of it is fitted

Cut the series into a past block and a future block. For a Gaussian state the
Schmidt coefficients across that cut are the **canonical correlations** `rho_k`
between the two blocks and the entanglement entropy is
`-(1/2) sum log(1 - rho_k^2)`, which is also exactly the past-future mutual
information. The quantum object and the classical object here are not merely
equal - they are the same log-determinant, so **this section is a relabelling and
is reported as one.** It is run for the number.

| | `rho_1` | `rho_2` | `rho_3` | `rho_1` shuffled | `I`, nats | `I` shuffled |
| --- | --- | --- | --- | --- | --- | --- |
| volatility_10_index | 0.0214 | 0.0206 | 0.0182 | 0.0255 | 0.0015 | 0.0013 |
| volatility_100_index | 0.0199 | 0.0191 | 0.0189 | 0.0267 | 0.0011 | 0.0015 |
| btc | **0.8016** | 0.0726 | 0.0357 | 0.0258 | **0.5194** | 0.0015 |
| usdjpy | **0.8322** | 0.0686 | 0.0374 | 0.0287 | **0.5948** | 0.0020 |
| gold | **0.6617** | 0.0476 | 0.0339 | 0.0322 | **0.2918** | 0.0026 |
| eurusd | **0.7243** | 0.0504 | 0.0359 | 0.0296 | **0.3762** | 0.0021 |
| aus200 | **0.6359** | 0.0361 | 0.0301 | 0.0289 | **0.2615** | 0.0019 |

**The six control feeds sit exactly on their own shuffled floor** - `rho_1` of
0.0199 to 0.0280 against a shuffle's 0.0229 to 0.0267, and a past-future mutual
information of 0.0011 to 0.0018 nats against the shuffle's 0.0013 to 0.0016.
Independent increments have no predictive information and the estimator says so,
which is condition 5 held.

**The nineteen real feeds share 0.26 to 0.59 nats between past and future, and it
is one mode.** `rho_1` runs 0.64 to 0.83; `rho_2` runs 0.036 to 0.080, an order
of magnitude down; `rho_3` is at three or four times the shuffled floor. Two to
six modes clear the floor at all, and the first is fifteen times the second.

**That is the bound, and it explains section six's own result before it was
run.** A feed whose past and future share essentially one degree of freedom
cannot reward a rank-8 projection over a rank-1 one, and cannot reward a clever
rank-1 projection over the obvious one, because there is only one thing to find
and it is the volatility level. `R^2` of 0.5041 to 0.5311 across every
construction, and a one-number average inside two points of the best of them, is
what rank-one predictive structure looks like from the other side. It is also the
same shape as [models.md](models.md)'s finding on a completely different problem:
a 1KB logistic regression beat trees, forests, cosine similarity and an MLP, and
five times the data did not change it.

### The one derived hyperparameter, and the estimator it does not transfer to

Estimating a slow mode needs a lag, and the separation between the first two
eigenvalues is `exp(-lambda_1 tau) - exp(-lambda_2 tau)`. Setting the derivative
to zero:

    tau*  =  log(lambda_2 / lambda_1) / (lambda_2 - lambda_1)

with no data in it. At a matched `lambda_1` a box wants `0.462/lambda_1` and a
spring `0.693/lambda_1`, **so the best hyperparameter differs by 50% between two
processes a mean-reversion fit cannot tell apart.** That is the shape a learning
algorithm derived from mechanics ought to have: it sets a knob from a spectrum
rather than from a search. Against 24 replicates of each truth at
`lambda_1 = 0.00342`:

| truth | `l2/l1` | `tau*` derived | grid optimum | separation profile peak |
| --- | --- | --- | --- | --- |
| spring | 2 | **203** | **180** | 0.247 at 180, 0.242 at 250 |
| box | 4 | **135** | **130** | 0.478 at 130 |

Each lands on its own prediction, and the two differ by the factor the
derivation asks for. Condition 4 held - `tau*` maximises separation only, while
the variance also falls with lag, so it is an upper bound and both optima sit
below it.

**And it does not transfer to the estimator this section's first half uses**,
which the dry run established the expensive way. Asked of a lag-embedded scalar,
the grid returned lag 34 for every ladder - the signature of a statistic not
seeing the spectrum at all. It was not: the second TICA eigenvalue of a delay
embedding reads 0.00 to 0.03 where the true `exp(-lambda_2 tau*)` is 0.25, 0.157
and 0.084, because the span holds many near-degenerate copies of the slow mode
and the direction orthogonal to all of them is innovation noise. **So the derived
lag governs Ulam's method on a state that is observed, and says nothing about
TICA on a delay embedding of it** - which is exactly the estimator anyone would
reach for on a price series. A derived hyperparameter for an estimator you cannot
use is the honest summary, and it is the half of this worth keeping.

**Ledger for section six: two of seven fired.** Condition 1 held. **Condition 2
fired** - PCA matches TICA and then beats it, so the derived objective is
notation. **Condition 3 fired on a technicality** at the fourth decimal and was
hunted rather than explained: four control feeds tripped a flag comparing
`R^2 = 0.0002` against a floor of 0.0001, which is the flag's granularity, and
every control number is zero to three decimals. Condition 4 held after being
restated during the dry run to name its estimator. Conditions 5, 6 and 7 held.

## Running it

```bash
./.secrets/lab.sh run research/harness/groundstate.py  NREP=200 WORKERS=60
./.secrets/lab.sh run research/harness/groundbarrier.py WORKERS=40 NU=24
./.secrets/lab.sh run research/harness/groundslow.py    WORKERS=48 NPERM=300
```

`groundlib.py` is the shared estimators and is imported rather than run; its
`check_analytic` is section one's table and needs no data at all, so
`python research/harness/groundlib.py` reproduces it anywhere.

## What is new here, and what is classical results in different notation

Stated plainly, because the whole exercise is borrowed notation and the borrowing
has to be accounted for.

**Classical results relabelled:**

* **TICA from Rayleigh-Ritz.** The derivation is correct and it is not mine: it is
  the variational approach to conformational dynamics of Noe and Nuske, and TICA
  itself is Molgedey and Schuster. Section six measures what it is worth, and the
  answer is **less than nothing**: PCA on the same matrix at the same rank beats
  it at every rank, and a flat 20-bar average - one number - captures 95.6% of
  what the best of eight constructions reaches. Relabelling that also loses.
* **The entanglement spectrum of a Gaussian state.** It is the canonical
  correlation between past and future, and the entanglement entropy is the
  past-future mutual information. These are not merely equal in value - they are
  the same log-determinant. Pure relabelling, and the section is run for the
  number rather than for the framing.
* **The ground-state transform.** `psi = sqrt(p)` conjugating a Fokker-Planck
  generator into a Schrodinger operator is supersymmetric quantum mechanics and
  is decades old. What this page does with it is not the transform but the
  consequence: that the ladder is a functional of the histogram.
* **The propagator.** Solving a first-passage problem by propagating a
  sub-stochastic matrix is what anyone would do; calling the walls Dirichlet does
  not change a line of the code. The only thing the quantum reading contributes
  is `quantising.md`'s Robin correction, which was already published there.

**What is actually new:**

* **`R`, the density-against-dynamics ratio.** Two estimates of one spectrum on
  one grid, one of which never sees a transition. It separates a hidden-volatility
  process from a plain diffusion at a single-cut error of **0.073** where every
  other statistic here is at 0.26 or worse, and it is 2.0 rather than 1.0 on
  independent data, which is a calibration nobody would have guessed.
* **That `l2/l1` is a functional of the marginal**, so `quantising.md`'s dictionary
  is one formula and its ladder has a second opinion that needs no transitions -
  and at Range Break's sample size that second opinion separates box from spring
  **eight times better** than the transition matrix does.
* **The measurement that `barriers.duration` is short by 25% to 96% on real
  feeds**, 19 of 19, monotone in geometry, against a flat 5-11% on feeds that are
  provably Brownian. Nothing quantum is needed to state it, but the spectral
  measurement of the volatility half-life in section four is what says *why* and
  predicts *where* the crossing is.
* **That a real feed's past and future share one degree of freedom.** `rho_1` of
  0.64 to 0.83 against a `rho_2` of 0.036 to 0.080, and a control set at its own
  shuffled floor. The *computation* is textbook; what is new is running it on
  these feeds with a provably-independent control beside it, and the number bounds
  every linear model anyone builds here - including the rank-8 one in the same
  section, which it correctly predicted would be worth nothing.
* **The derived optimal lag, and the estimator it does not reach.** `tau*` lands
  at 135 against a measured 130 for a box and 203 against 180 for a spring, so a
  hyperparameter really is readable off a spectrum. It then fails to transfer to
  a delay embedding, whose second eigenvalue is 0.00 where the spectrum says
  0.25, and that failure is the more transportable half.
* **The bound, again.** Three learned objects were built here and every one is
  beaten by something simpler: a Kramers-Moyal generator beats the derived ladder
  on which-confinement, the feed's own return histogram beats the learned
  volatility operator on barrier probability, and PCA and a 20-bar average both
  beat TICA on volatility. That is a measurement of how far the framing goes, and
  it goes about as far as `quantising.md` said it would.

## What this does not say

* **It does not find an edge and could not.** [deriving.md](deriving.md)'s theorem
  fixes `E[net] = -(c/2) x turnover` for every predictable position on a
  martingale, and every improvement here is to a *conditional estimate*. The
  duration result changes where a timeout should sit; it does not change the sign
  of anything.
* **The `R = 2` calibration is this estimator's, at this sample size.** It is not
  a universal constant and it should be re-measured on any other sampling scheme
  rather than carried across.
* **Section two is one feed.** RB100 has 20 usable episodes; RB200 failed its own
  power gate and is not reported. The density and the dynamics disagree on RB100
  by 2.9 replicate standard deviations and this page does not resolve which is
  right - it says the disagreement is itself informative and leaves it there.
* **The barrier legs are bar-monitored.** `barriers.py`'s own headline correction
  is that a real stop is hit on a tick and the shift falls as `B/sqrt(n)`. Every
  number in section five is the close-monitored case, which is the regime where
  `B = 0.5826` is validated; the tick-monitored case is section five's obvious
  next run and is not done here.
* **The duration excess is measured on 60 days.** It is tight across nineteen
  instruments, which is the argument for transporting it, and it has not been
  tested across eras.
* **Nineteen real feeds are not nineteen independent samples.** Every interval in
  section five is a `t` over feeds rather than over trials for that reason, which
  is the conservative choice and still leaves 3:1 at 5.3 standard errors.

## What follows

1. **Multiply `barriers.duration` by about 1.25 on real feeds, and by more at
   wide geometries.** It is the largest, tightest and most directly usable number
   here: 1.271 at 3:3, 1.417 at 5:5, 1.958 at 10:10, 19 of 19 feeds, against
   1.05-1.09 on feeds that are provably Brownian. A `max_hold` set from the
   uncorrected form converts trades that had not finished into trades scored as
   if they had, which is [spending.md](spending.md)'s 50-of-133 finding.
2. **Leave `barriers.probability` alone at symmetric geometries and know the sign
   of its error at asymmetric ones.** It is unbiased at 1:1 through 10:10 and
   understates the far barrier by 0.85 points at 3:1. If that is ever worth
   correcting, correct it with the feed's own return histogram, which removes 96%
   of it, and not with a learned operator, which does not.
3. **Do not build the volatility-regime operator into anything.** Its persistence
   is worth nothing - the shuffled control matches it - and on the one quantity
   where it might have helped, the duration, it is worse than the closed form.
4. **Run the barrier legs on ticks.** `feed.py` now reaches 200,000 ticks a
   symbol at a 146ms mean gap, and `barriers.py`'s whole monitoring-rate
   correction is untested on real feeds. That is the measurement this page most
   obviously lacks.
5. **Use the static ladder, not the transition matrix, when episodes are short.**
   At Range Break's sample size it separates box from spring at a single-cut
   error of 0.003 against 0.025, and it costs one histogram.
6. **Do not quote `R` about a single feed.** Its own kill condition 4a says it
   cannot carry that, and the control arm is what makes it readable.
7. **Stop reaching for rank-reduced projections on return history.** The
   past-future spectrum says there is one predictable mode, TICA loses to PCA at
   every rank, and both lose most of their margin to a 20-bar average. If a
   volatility forecast is wanted, the cheapest thing on the table is within two
   points of `R^2` of the most expensive.
8. **Measure the past-future `rho` spectrum before building any model on a new
   feed.** It costs one SVD, it has a shuffled floor that is honest, and a feed
   whose `rho_1` sits on that floor cannot support a linear model of any order.
   It would have said in advance that section six was not worth running.
