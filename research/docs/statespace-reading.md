# statespace: the references read, and what each one gave

Extracted from `statespace/README.md` on 2026-10-11. S4 through Mamba-3, HiPPO, LMU, BOCPD, FOCuS, the Cboe methodology, candlestick liquidity, order flow, and kinetic modelling - with what transferred, what did not, and why.

**Three entries record a claim this package made and got wrong after reading only the paper**: the HiPPO matrix was missing its `B`, "zero-order hold, which is what Mamba uses" was wrong twice over, and "A stays fixed" is true of the paper and not of the line of work. Reading the implementations is what corrected all three.

## The deep state-space family, and the three ideas from it that transfer

Reviewed 2026-10-10 from IBM's *What are state space models?* (Bergmann, 7 July
2025), asked for because the article names RNNs, CNNs, Mamba and S4 and none of
them appears anywhere in this package.

They are absent because this package is the **classical** half of the field:
`A` and `C` are written down from what a level is, and the Kalman recursion is
exact given them. The article's half learns `A`, `B` and `C` as neural network
weights by backpropagation, and is explicit about the price — it needs "a great
deal of training data" and is "not interpretable". Both are disqualifying here:
this desk has ~10^5 touches, not 10^9 tokens, and a gate that cannot say why it
refused cannot be journalled.

That is a refusal of the deep *models*. It is not a refusal of the ideas
underneath them, and three of those are cheap on data already in hand.

### The two halves are the same recursion

The article's continuous form is `h'(t) = A h(t) + B x(t)`, `y(t) = C h(t) + D x(t)`,
discretised to `h_t = Abar h_{t-1} + Bbar x_t`, `y_t = Cbar h_t`. So a discretised
SSM **is** a linear RNN whose hidden state is the state vector — the article says
so outright — and one with a fixed `Abar` unrolls into a 1-D convolution kernel
`(Cbar Bbar, Cbar Abar Bbar, Cbar Abar^2 Bbar, ...)` trainable by FFT. RNN, CNN
and SSM are three readings of one recursion rather than three models, which is
worth knowing before reaching for any of the three by name.

`D` is the direct input-to-output term; the article notes it is usually dropped.
This package drops it for the stronger reason in I1 — there is no input at all.

### D1. The transition as a chosen memory rather than a chosen physics — HiPPO

**The one to do first**, and the article's sharpest number: on sequential MNIST,
replacing a random `A` with the **HiPPO** matrix moved accuracy from 60% to 98%.
Nothing was learned differently. The transition was chosen rather than guessed.

Both members here choose `A` from physics. `linear` is an integrated jerk — a
local Taylor expansion of where the level is going; `reverting` is an integrated
OU — the same with a pull-back. Both describe the level **now**. HiPPO-LegS
instead chooses `A` so that the state is the optimal least-squares projection of
the *whole history so far* onto Legendre polynomials, in closed form and needing
no dependency:

    A[n,k] = -sqrt(2n+1)*sqrt(2k+1)   for n > k
             -(n+1)                   for n = k
             0                        for n < k

**Checked against the reference, 2026-10-10** — `srush/annotated-s4` and
`state-spaces/s4`. The formula above is right, to 8.9e-16 at N = 2, 3, 4 and 6
against `make_HiPPO`, which builds it as `tril(sqrt(2n+1) sqrt(2k+1)) -
diag(n)` and negates. Two things it was missing:

**HiPPO specifies `B` as well**, and leaving it out would have left half the
model to guess: `B[n] = sqrt(2n+1)`.

**The eigenvalues are the diagonal, because the matrix is lower-triangular** —
so HiPPO-LegS at N = 4 has spectrum `-1, -2, -3, -4`, which is *exactly*
`selective.eigenvalues()` and exactly Mamba's S4D-Real. **S4D-Real is HiPPO with
the coupling thrown away and the time constants kept**, which is why the paper
finds it ties with the full matrix, and it means D1's gain over `selective` is
the off-diagonal coupling alone and not the decay rates. That lowers the
expected prize and sharpens what is being tested: whether a level's history
wants its basis coefficients *coupled*.

**It is non-normal**, verified - `A Aᵀ != Aᵀ A` - which is the whole reason S4
carries NPLR/DPLR machinery: add a rank-one `P Pᵀ` with `P[n] = sqrt(n + 0.5)`
to make it normal, then diagonalise. **None of that is needed here.** DPLR
exists to get an `O(N log N)` convolution kernel at N in the dozens and to keep
gradients stable through it; at N = 4 with no backpropagation, the dense matrix
is four rows and the direct recursion is correct and fast.

For a level touched forty times across three weeks, "the entire touch history
compressed into k numbers, optimally" is a different claim from "position, rate
and acceleration right now" — and it is nearer the claim this desk's levels are
supposed to embody, that a level **is** its history.

**Which measure.** `state-spaces/s4`'s `transition()` implements `legs`, `legt`,
`lmu`, `lagt`, `glagt`, `fourier`/`fout`, `fourier_decay`, `fourier2`, `random`
and `diagonal`. Three are worth trying and they encode different beliefs about
what a level remembers:

| measure | what it remembers |
| --- | --- |
| `legs` | the whole history, scaled - every touch ever, older ones coarser |
| `legt` | a sliding window - touches inside it, nothing before |
| `fout` | an oscillatory basis - see D4 |

`legs` first, because "a level is all of its history" is the desk's own claim.
`legt` is the honest rival: a level that was last respected in March may simply
be a different level.

**Null:** `linear` and `reverting` on held-out one-step predictive likelihood over
the same measurement series, scored exactly as I5 was. It is a drop-in: same
`Filter` protocol, same `smooth` factory, a different `A` and `C`. Legendre
Memory Units (Voelker, Kajic and Eliasmith 2019) are the same idea a generation
earlier and are `lmu` in that list.

### D2. Selectivity — and the Mamba paper says our data is the case it hurts

**Demoted on 2026-10-10 after reading the paper rather than the summary of it**
(Gu and Dao, arXiv:2312.00752). The summary version of this idea was the second
thing to do here. The paper's own limitations section moves it down, and the
sentence that does it is this:

> the selection mechanism helps on discrete modalities, "but this conversely can
> impede their performance on data that LTI SSMs excel on"

They are not speculating. Replacing S4 with the selective S6 layer
**"significantly hampers performance"** on long-form audio waveforms, and their
conclusion is that "layers closer to the raw audio signal should be LTI" —
selection only earns its place once an outer layer has tokenised and compressed
the signal. Structured SSMs have "a strong inductive bias toward continuous-time
data modalities such as perceptual signals", and selection exists to fix their
weakness on **text and DNA**.

A price series is the first kind and not the second. A level's position is a
continuous-time quantity sampled irregularly, with no vocabulary and nothing to
retrieve by content. So this package sits in the regime the authors say
selection impedes, and `linear` and `reverting` being LTI is a match to the data
rather than a limitation to fix.

**What the paper corrects in the earlier note here.** Selectivity is not
"making `delta` input-dependent". `B`, `C` and `delta` become input-dependent in
Algorithm 2; **`A` stays a fixed parameter**, and the authors say they left
selective `A` untested, hypothesising it would be similar. That matters twice: it
means D1 and D2 compose rather than compete — a chosen `A` survives selectivity —
and it means the ablation below is about `B`, `C` and `delta` only.

**And `mamba3.py` has since done it**, so "A stays fixed" is true of the paper
and not of the line of work. Mamba-3 makes the decay data-dependent per head and
per timestep, through a heavy-tailed map - `1 + x` for `x >= 0`, `1 / (1 - x)`
for `x < 0` - clamped to at most `-A_floor` with `A_floor = 1e-4`, under the
comment that it "can improve stability during WSD training and at higher
learning rates". The clamp is the part that transfers: it is the guard that
keeps the decay strictly negative, and `reverting`'s `theta` needs the same one
for the same reason.

**The one fragment that still transfers, and it has a theorem.** Their Theorem 1:
with one state, `A = -1`, `B = 1` and `delta = softplus(param + Linear(x))`, the
recurrence becomes

    g_t = sigmoid(Linear(x_t))
    h_t = (1 - g_t) h_{t-1} + g_t x_t

which is **an exponentially weighted moving average whose decay is a function of
the input**. This desk is full of EWMAs with fixed decay. So the cheapest
possible version of this idea is not a new member at all: take one existing
fixed-decay average and let its decay depend on activity rather than on the
clock. Large `delta` resets the state onto the current input; small `delta`
keeps the state and ignores the input — which is the behaviour wanted across a
regime break, where a level's older history should stop counting.

`dt` here is clock time between touches and a level does not age by the clock:
one untouched across a dead weekend has advanced less than `dt` says, one
untouched through an NFP print more. `regime` and per-feed volatility are
already computed, so `delta = dt * activity` costs one parameter and no new data.

**Null:** the same member on clock `dt`, held out — and on this data the null is
expected to win. Run it anyway, because "the paper says our modality is the
other one" is an argument and not a measurement, but do not run it before D1 and
D3, and do not read a loss as a surprise.

**What is not worth copying at all.** The selection mechanism's cost is that a
time-varying `Abar` cannot be unrolled into a convolution, which is why Mamba
needs a hardware-aware parallel scan that keeps `delta, A, B, C` in SRAM and
recomputes intermediate states in the backward pass instead of storing them.
That is an answer to a problem created by selectivity, at sequence lengths this
desk does not have. Taking the scan without the selectivity would be taking the
cost without the reason.

### D3. One state, several measurements — MIMO

The article's worked example reads a two-state system through a `C` with four
output rows, and names MIMO explicitly. This package runs a filter per
`(level, interval)` row. `drawing/confluence.py` already argues the other way in
prose — "evidence gathered at three resolutions of one price is evidence about
one price" — and MIMO is the arithmetic for exactly that: one state per level,
one `C` row per resolution, several measurements updating one state.

It also answers part of the matrix question that started `subjects.py`. The first
useful matrix is **not** instruments side by side; it is resolutions of one level
stacked, and it needs no data that is not already recorded.

**Null:** the independent per-interval filters on the same held-out measurements.
If the resolutions are independent the stacked `C` buys nothing — which is the
same shape of test as the cross-instrument innovation correlation.

### The neural family member exists: `selective.py`

**Written on 2026-10-10, after this table had said "declined as an
architecture".** Asked for directly - "we can have a neural architectural
family like mamba inside our statespace lib" - and the decline was aimed at the
wrong half. The architecture is a recurrence and it costs nothing to write; what
needs an autodiff framework is the *training*, and only that is still declined.

`family.members()` now answers `{kalman, reverting, robust, selective}`.
`Selective` is S6 with `A` a fixed diagonal `-(n+1)` - S4D-Real, the best of the
four initialisations the paper ablates and tied with random - and `B`, `C` and
`delta` affine in one scalar, five parameters in total, which the same
likelihood search that fits `theta` and `jerk` can fit. The paper's `Linear`
layers are thousands of weights fitted by backpropagation; this is five numbers
fitted by grid. Smaller claim, and the one checkable here.

Three things it taught while being written, all pinned by tests:

* **Theorem 1 is exact.** `1 - exp(-softplus(z)) == sigmoid(z)` to 1.1e-16 over
  `z` in `[-8, 12]`, so a one-state selective SSM **is** an exponentially
  weighted average whose decay depends on its input. That is the single most
  reusable thing in either paper, because this desk is full of fixed-decay
  averages and the cheapest experiment in this document is letting one of their
  decays depend on activity instead of on the clock.
* **It cannot be smoothed, and that is honest.** A selective SSM is a
  deterministic map with no posterior covariance, so `smooth` returns None for
  it - the same contract a member that cannot state its own `F` already has. It
  *can* state `F`; the missing piece is the covariance.
* **A zero-length step folds in nothing.** `delta` is its only entry channel,
  so two venues printing the same instant give a Kalman member two pieces of
  evidence and give this one none. Mamba has no notion of two tokens at one
  position and neither does this.

### D4. An oscillatory state, which is the one the desk already believes in

**New on 2026-10-10, and the best-motivated idea in this document** because
four independent things point at it and none of them is a paper's headline
number.

1. **The Mamba paper's own audio result.** Complex-valued parameters were used
   in exactly one experiment - long-form audio - and the authors conclude they
   help "continuous modalities" and not discrete ones like text or DNA. A price
   series is a continuous modality. The same section is where they say layers
   near a raw signal "should be LTI".
2. **`mamba3.py` applies data-dependent rotary angles to `B` and `C`**, carried
   in the decode state and passed to the kernel. The file does not call it a
   complex eigenvalue, but a rotation applied to the input and output maps is
   what a complex conjugate pair *is*.
3. **HiPPO already has the basis**, and it is not speculative:
   `fourier_diag`/`foud` builds `A = 2*pi*(-diag(d, 1) + diag(d, -1))` with the
   frequencies interleaved - a skew-symmetric tridiagonal, which is a pure
   rotation generator. `fourier`/`fout` and `fourier_decay` are the damped
   relatives.
4. **Every member here is purely decaying.** `linear` integrates, `reverting`
   pulls back, `selective` averages. **Not one of them can turn around.** If a
   level's approach oscillates, a state space that cannot represent an
   oscillation is the wrong one, and this is the only gap in the family that no
   pending member fills either.

   The weaker version of this leg, and it was checked before being written down:
   the desk's own cycle strategies do **not** support the premise.
   `cycle-scalp` is `-0.021 +/-0.024 R` over 600 closed trades - t of -0.9, so
   indistinguishable from zero - `cycle-turn` has never traded, and
   `cycle-turn-scalp` has two. So "this desk already believes in cycles" is true
   of the code and **not** of the record: no evidence either way, which is
   weaker than the premise wanted and stronger than a refutation.

A complex conjugate pair is two states, the same count `reverting` already uses,
so this is not a request for more parameters - it is the same budget spent on a
rotation rather than on a pull-back. That makes the comparison clean.

**Null:** `reverting` on held-out one-step likelihood, which is the current
winner and also the natural rival: both say "the rate does not run away", and
they disagree about whether it decays to zero or circles.

**What would make it false:** a measurement on the levels themselves rather
than on strategies that trade them. The check above used strategy P&L, which is
entry, exit and sizing on top of the question being asked; the direct version is
whether a level's *rate* has negative autocorrelation at any lag - an
oscillation - on the episode series. That is the same shape as the
speed-and-direction measurement and it is not done.

### `mamba_ssm/modules/` read through, for what else is borrowable

| module | what it is | here |
| --- | --- | --- |
| `mamba_simple.py` | Mamba-1 | **read**, and it corrected this package's ZOH claim |
| `mamba2.py`, `ssd_minimal.py` | Mamba-2 / state space duality | **noted, not adopted.** Mamba-2's trade is a *scalar* `A` per head instead of a diagonal one, which is what lets the recurrence become a matmul and gives the duality with attention. It buys speed by collapsing every state to one decay rate - the opposite direction from D1, where the whole point is that the basis carries several timescales. At N = 4 we have no speed problem to trade for it |
| `mamba3.py` | Mamba-3 | **the richest file.** Data-dependent `A` (superseding the paper's "A is fixed"), an implemented `is_mimo` mode at `mimo_rank=4`, a trapezoidal discretisation term, rotary angles on `B`/`C`, and RMS-norm on `B`/`C` with learned biases. Three of those feed D2, D3 and D4 |
| `block.py` | norm, mixer, residual, then norm, MLP, residual | **a real idea, cheap to try.** Residual stacking means layer two models what layer one could not. Here that is a second filter on the first's **residual series** - and `diagnostics.residuals` already produces exactly that series, to test whether it is white. If it is not white, something is left to model, and a stacked member is the thing that would model it. One line of plumbing, no new maths |
| `mha.py` | multi-head attention, for hybrid stacks | **not transferable**: there is no attention here and nothing to attend over. The *hybrid* idea - different mixers in one stack - is already this package's `members()` plus the switching model in I9 |
| `mlp.py` | GatedMLP | no |

**`is_mimo=True` is the find.** D3 was argued from the article's worked example
and from `drawing/confluence.py`; the reference has it implemented, with a
rank-`R` input and output projection per head rather than a full matrix, and a
chunk-size note recommending `64/mimo_rank`. A low-rank coupling is a better
first shape than a dense one for the same reason the third state lost in I5:
fewer things to estimate from the same touches.

### LMU, and the parameter a desk can actually reason about

`compneuro.uwaterloo.ca/publications/voelker2019lmu.html` - abstract only on the
web page, so the matrices below are from `state-spaces/s4`'s `transition()`,
whose `lmu` branch carries the comment "equivalent to LegT up to normalization":

    A[i,j] = (2i + 1) * (-1 if i < j else (-1)^(i-j+1))
    B[i]   = (2i + 1) * (-1)^i

both divided by **theta**, which the source leaves as a commented-out `/ theta`
on the shared factor.

**That `theta` is the point.** The abstract's claim is that the state "linearly
maps onto sliding windows of time via the Legendre polynomials up to degree
d - 1" - so `theta` is a **memory window in time units** and `d` is how finely
that window is resolved. Compare what this package currently asks a user to
choose: `jerk`, a spectral density in value units squared per hour to the fifth,
whose production counterpart was picked once and never fitted.

"This level's state summarises the last 72 hours, at four degrees of detail" is a
sentence a trading desk can argue with. "The third derivative has spectral
density 1e-4" is not, and `DRIFT_VOL_PER_HOUR = 0.02` is what happens when
nobody can.

So LMU/LegT is worth writing **for its parameterisation** even if it ties, and
it is a different experiment from D1: `legs` compresses all history, `legt` and
`lmu` summarise a window and forget what is behind it. For a level that may
simply have stopped mattering, forgetting is a feature.

Careful about one collision: `reverting.theta` is a mean-reversion **rate**, per
hour, and LMU's `theta` is a **window length**, in hours. Same letter, reciprocal
units, and they will end up in the same config if nobody says so first.

### Read against the reference implementation, not only the paper

`state-spaces/mamba`, `mamba_ssm/modules/mamba_simple.py`, 2026-10-10. Worth
doing separately: the paper says what the model is, the code says what the
authors ran, and they differ in one place that had already made it into
`selective.py` as a wrong comment.

**Two things confirmed.** `A` really is `-(n+1)`: the code builds
`arange(1, d_state + 1)`, stores `A_log = log(A)` and uses `A = -exp(A_log)` in
forward, so `eigenvalues()` here matches the implementation and not just the
ablation table. And the step size's bias is set to `dt + log(-expm1(-dt))` so
that `softplus(bias)` recovers a chosen `dt` - exactly `INERT`, which was
already `log(e - 1)` and is now written as `inverse_softplus(1.0)` because that
form generalises to any target.

**One thing corrected, and it was mine.** `selective.py` described its
discretisation as "zero-order hold, which is what Mamba uses". Wrong twice:

* the reference computes `dB = einsum("bd,bn->bdn", dt, B)`, which is plainly
  `delta * B` - **Euler, not ZOH**
* and the form here, `1 - exp(delta * A)`, is exact ZOH only at `A = -1`. Exact
  ZOH carries a `1/|A|`: at `delta = 0.5` this member's entry weight is 0.632
  against ZOH's 0.316 for `A = -2`, and 0.865 against 0.216 for `A = -4`

The form is still the right one *here*, for a reason the reference does not
have: weights summing to one make every state a normalised exponential average
that converges to the reading, so their mean is an estimate and `C` can be
fixed. Mamba's `C` is learned and absorbs whatever scale the states settle at,
so it does not care. Three tests pin this rather than a comment asserting it.

**`dt_min = 0.001` to `dt_max = 0.1`, log-uniform, floored at 1e-4.** Kept as
`REFERENCE_DELTA` for the *shape* a grid over `drift` should take - log-uniform
across orders of magnitude - and explicitly not as the values: theirs is a step
per token in a sequence with no clock, and `delta` here multiplies real elapsed
hours.

**`D` exists in the implementation**, which the article said was usually
dropped: `D` is a parameter of ones and the output is `y = C h + D * x` before
the gate. In this package's terms that is a direct pass-through of the current
reading to the output - a blend of the filtered state with the raw touch. It is
*not* adopted, and the reason is sharper than I1's "there is no input": the
whole purpose of a filter here is that a reading is noisy, so a skip connection
from it to the output is the one thing a level estimator should not have. Worth
knowing it is there, because a reader comparing this to the reference will
notice its absence.

**A depthwise causal `conv1d` of width 4 sits before the SSM**, with SiLU after
it. In our terms, a four-tap local smoother on the touch series ahead of the
state update. Noted, not adopted: it is a fifth parameter set on a member that
cannot yet beat a two-state LTI null with five.

Not transferable: `use_fast_path`, the fused `selective_scan_fn`, the BLH/BDL
layout choices, and the gated `z` branch with `out_proj`, which exist because
there is a neural network around the recurrence. There is not one here.

### Noted and declined

| from the papers | status here |
| --- | --- |
| Mamba, selective SSM (S6) | **written** — `selective.py`, above |
| trained `A`,`B`,`C` by backpropagation | **declined**, in the article's own words: a great deal of training data, and not interpretable. The same wall `family.PENDING` records for PyDPF |
| S4, DSS, S5 — structured SSMs | **declined**: their structure is a trained `A`, and we have ~10^5 touches and need an explainable refusal |
| recurrence/convolution duality, FFT training | **noted, little use here**: it needs uniform `delta` and time-invariance *and the whole sequence known in advance* — true in a backtest, false live, and our touches are irregular besides |
| hardware-aware parallel scan | **declined, and for a specific reason**: it answers a problem *created* by selectivity, at sequence lengths this desk does not have. Taking the scan without the selectivity is taking the cost without the reason |
| zero-order hold, bilinear, Euler | **already stronger**: `reverting.py` uses the exact closed form, with `-expm1(-theta*dt)` where the naive expression cancels, and `tests/test_statespace.py` checks it against both a van Loan reference and quadrature. `selective.py` uses ZOH, as Mamba does, because with a diagonal `A` it is exact |
| expectation maximization, N4SID | **already named** — I11 and `family.PENDING`. Note the paper's condition: both want linear *time-invariant* dynamics, so they apply to `linear` and `reverting` and **not** to `robust` or `selective`, whose gains depend on their input |
| HiPPO, Legendre Memory Units | **adopted as D1** |
| state expansion `N` | **corroborates I5 from outside.** The paper's ablation raises `N` from 1 to 16 and gains almost nothing while `B` and `C` are not selective — 9.88 to 9.81 — and 1.0 perplexity once they are. Our own I5 found a third state estimable and still 0.138 nats a point worse. Two independent measurements saying more state buys nothing without selection |

What would move the first row: a reason to accept a gate that cannot explain its
refusal, which this desk does not have, and an order of magnitude more data than
the 250k episodes it does.

## Liquidity on candlesticks: most of it is already tracked

Asked 2026-10-10 with a list of candlestick liquidity features. Checked against
the codebase before proposing anything, and the honest answer is that the desk
measures most of this already under different names:

| the feature | here |
| --- | --- |
| wicks and their size | `wick_above_vol`, `wick_below_vol`, `wick_above_sd`, `wick_below_sd`, `wick_n`, per level, in `engine.py` |
| buy-side liquidity above swing highs | `liquidity_beyond_vol` - the next level out, which `drawing/sweeps.py` defines as "a price where stops accumulate because it is a price everybody else can see too" |
| sell-side liquidity below swing lows | the same, by side |
| a liquidity grab - spike through and snap back | **`Outcome.TRAP`**, already recorded per side, and `sweep_rate` is its decayed share |
| a stop needing to clear the wick | `engine.py` already sizes in "sigmas of wick spread a stop has to clear beyond the level's own average" |

**Two real gaps.** The body-to-wick *ratio* is not a named feature - the wick
sizes are there and the small-body-long-wick shape is not. And the single-bar
grab is not distinguished from the multi-bar sweep: `TRAP` is per interaction,
and the multi-bar version - break, consolidate, reverse - is closer to
`Episode.kind == "whipsaw"`, which is defined by R-multiples rather than by
shape.

### What Mazza (2012) actually found, which is not the folk version

*Intraday Liquidity Dynamics and Price Movements*, 15-minute candlestick
configurations against limit-order-book liquidity - spread, depth, order
imbalance, dispersion, slope, plus activity and volatility.

* **Dojis**: high-low volatility falls sharply, significant at 1%. Higher book
  liquidity. Trading activity is **lower** while orders are **more aggressive**,
  and asymmetrically: sellers aggressive immediately, buyers only 15 minutes
  later. Gravestone tilts seller-aggressive, Dragonfly buyer-aggressive.
* **Hammer family**: higher liquidity *just before* formation, and "not provided
  by more depth: the book is more dense and the spread is lower". The Hanging
  Man shows it only *after* it has fully appeared.
* **Where the body sits in the range matters**: body near the high goes with more
  liquidity at the ask, near the low with more at the bid, and more so when the
  body is short.
* Robust to 30 and 60 minute intervals for Dojis; the Hammer patterns lose
  significance as the interval lengthens.

**The conclusion is about execution, not direction**: "traders might benefit from
candlesticks analysis as a way to better time their order submissions in order to
improve their transaction costs management." The paper does not establish a
directional edge, and the effects are short-lived. That is a narrower and more
usable claim than the folk version, which reads a long wick as a reversal signal.

**The caveat that decides how much transfers.** Mazza's measures come from a
limit order book. This desk has no book - bid, ask and volume, no depth, no
dispersion, no slope, no order imbalance. What survives is **spread**, **high-low
volatility** and **activity**, which is enough for the Doji result and not enough
for most of the rest.

### The state-space reading of all of it, which is the part worth building

**A wick is a measurement outlier, not information about where the level is.** It
says where stops were. Two consequences, and both are already half-built here:

1. **The filter should not move its state on a wick.** That is bounded influence,
   which is `robust`. And it is not theoretical: the S6 member's -128.86 at
   xauusd 4h and -570.31 at usdjpy 3m are a feedback loop in which a large
   innovation opens `delta`, the state resets onto the outlier, and the next
   innovation is larger still. Selection reading a Huber-gated residual is the
   version of that member this data might not reject.
2. **The wick belongs to a different quantity.** `subjects.py` names three -
   LEVEL, INSTRUMENT, RELATION - and this argues for a fourth, measured by wick
   excursions rather than by touch prices, with its own `jerk` and its own
   noise. A level says where price is agreed; liquidity says where stops are
   resting. They are different states with different time constants and one
   filter should not be asked to carry both.

And one structural point that ties back to the trend question: **a Hammer and a
Hanging Man are the same shape.** The name depends entirely on the preceding
trend. That is a state-dependent reading of an identical measurement, which is
what a switching model is - I9, and the HMM member's job.

## Online change-point detection, and the parameter update it comes with

Read 2026-10-11: *Online Learning of Order Flow and Market Impact with Bayesian
Change-Point Detection Methods*, Tsaknaki, Lillo and Mazzarisi, arXiv:2307.02375.
Its application does not transfer - order flow and market impact need signed
trades and a book, and this desk has neither - but **two of its methods do, and
one of them answers a question left open above.**

### BOCPD belongs in the family, and it is better motivated than `hmm`

Bayesian online change-point detection maintains a posterior over the **run
length** - how long since the last regime change - rather than over a fixed set
of states. Two consequences that matter here:

* **it does not require the number of regimes to be chosen**, which is the
  objection `family.PENDING` records against `hmm` ("a discrete state is a
  different claim about the world") and the reason `dpm` is listed at all. BOCPD
  is the change-point formulation of `dpm`'s unbounded-mixture idea and is
  cheaper: a run-length posterior rather than a mixture over partitions.
* **it is genuinely online.** `hmm` as usually fitted needs the series; this
  updates per observation, which is the only form the desk could run - the same
  objection that made `smooth` unusable live and `lagged` necessary.

**Null:** the same member without change-points, on held-out likelihood. And the
paper's own claim is the bar: regime information improved their online
predictions over models without it, which is exactly what `hmm`/I9 would have to
show here.

### Score-driven parameters: the self-contained version of improvements 1 and 2

This is the part that answers an open question. Improvements 1 and 2 above say to
make `R` and `q` time-varying, and the mechanism proposed there was an
**external** forecast - HAR-Parkinson feeding `R_t`. That works and it needs a
second model.

The paper's novelty is a **score-driven** update: the parameter moves with the
*score* of the likelihood, which for a Gaussian observation is a function of the
standardised innovation. Every member in this package already reports exactly
that, as `last_standardised`, and it was measured as the best model-provided
volatility signal here - a 2.02x quintile spread against `sd`'s 1.24x.

So a score-driven `R_t` is self-contained: the filter updates its own
measurement variance from its own innovations, with no second forecaster and one
new parameter. **Both versions are worth running against each other**, and they
are different claims - the external one says volatility is a property of the
market that a better estimator can read, the score-driven one says it is
whatever has been surprising this filter lately.

Their result (ii) is the target either way: residuals well specified in **both**
distribution and temporal correlation. Every member in this file currently fails
both - Ljung-Box and Jarque-Bera at `p = 0.000` nearly everywhere - so a member
whose residuals pass would be the first here to manage it.

## Order flow: almost none of it is computable here, and the one piece that is already exists

Two references read 2026-10-11. The second one is unusually honest for the genre
- it names Cont, Kukanov and Stoikov's OFI and VPIN rather than gesturing at
them - and it states the constraint itself: **"bar data is enough for price
action, while order flow needs trades with aggressor classification."**

This desk has OHLCV bars from MT5. No depth, no signed trades, no quote stream.

| the tool | what it needs | here |
| --- | --- | --- |
| delta, cumulative delta | trade direction | **not available** |
| footprint | trade direction | not available |
| book imbalance, `(Qbid - Qask) / (Qbid + Qask)` | Level 2 depth | not available |
| OFI (Cont-Kukanov-Stoikov) | L1 quote updates | not available |
| VPIN | trade direction inside volume buckets | not available |
| queue position | order-by-order feed | not available |
| **volume profile, point of control** | volume by price | **`drawing/profile.py`** - already drawn |

`profile.py` is the one piece that survives the data constraint, and it was
written before any of this reading: "levels where a lot of supply changed hands,
found as modes rather than bins", from "the distribution of activity over
price, which every instrument has and which needs nothing bought". It is in
production - `STRUCTURES_FORMATION` reads
`pip,run,origin,profile,equal,gap,round`.

### Three things that do transfer

**1. The cost lesson, arrived at independently for the fourth time.** The
article's own worked example conditions on a book imbalance above 0.5 and raises
the up-move probability from 50% to 58% - then says "half a tick of spread plus
fees can consume the whole edge". That is precisely what this file measured three
times from a different direction: the 3m innovation reversion at **0.16
spreads**, the gbpusd 15m fade where the edge and the cost were both **0.113**
volatility units, and the usdjpy 15m innovation. A retail order-flow guide and a
state-space package reach the same conclusion about the same market, which is
worth more than either reaching it alone.

**2. VPIN's volume clock is the citation D2 was missing.** VPIN buckets by
**volume** rather than by time, and D2 - selectivity as a step size - proposed
`delta = dt * activity`, which is the same idea: sample in event time rather
than clock time. So the reference for that is VPIN and, behind it, the
subordination literature.

Concretely: `inputs.py`'s windows are in hours and its ladder resolves rungs by
elapsed time. A volume-clock variant would express them in **cumulative
volume**, and `resolvable` would pick rungs the same way. The data is there.

**And the caveat is the one Amihud already found.** `|r|/volume` scored -1% to
8% of achievable here because a CFD "volume" is a **tick count**, not traded
size. A tick count is still a measure of *activity*, so a clock built on it is a
tick clock rather than a volume clock - which is the original form of the idea
and defensible, but it is a different quantity and should be called by its own
name.

**3. The tick rule has a bar-level proxy, and it is already written.** The
article gives the rule - at or above the ask is a buy - and no ticks are stored
here. The standard bar-level stand-in is where the close sits inside the bar's
range: a close near the high means buying pressure won the bar. That is
`Features.position`, added today, and it is unit-free so it travels across
symbols. It is a *proxy for* delta and should never be called delta.

### What this changes about the package: nothing, and that is the finding

No new member, no new feature, no new subject. The honest output of reading two
order-flow references against this codebase is that the data constraint is
binding, the one computable tool was already built, and the one new idea - the
volume clock - is a citation for something already recorded as D2.

That is worth writing down because the alternative was to implement a delta
proxy, call it delta, and have it measured against a null six months from now by
someone who had forgotten it was a proxy.

## Kinetic and PDE modelling: one thing to use, two framings, the rest out of reach

Bertram Düring's research page, read 2026-10-11. Kinetic and Fokker-Planck
modelling of economic systems, numerical analysis, and financial mathematics.
Most of it needs a PDE or agent-level data that this desk does not have. Three
things are worth keeping.

**1. Use a Student-t observation, not a Gaussian. This is actionable now.** The
kinetic wealth models - Cordier-Pareschi-Toscani, Chakrabarti-Chatterjee-Manna -
*derive* Pareto tails from conservative exchange rules, which is a reason to
**expect** heavy tails rather than to treat them as misspecification. And this
file has measured them: Jarque-Bera at `p = 0.000` on every member, every
series, every timeframe.

`changepoint` is already the only member with a heavy-tailed predictive - its
Normal-Inverse-Gamma posterior marginalises to a Student-t - and it got there by
inferring its variance rather than by choosing a tail. Every other member is
Gaussian. So a t-distributed observation is a small change with a derivation
behind it, and `robust`'s Huber gate is the cheap approximation of the same
thing: bounded influence is what a t-likelihood does automatically.

**2. "Two-factor stochastic volatility information processes that explain
crash-like price movements"** (Düring, 2009) is a citation for the reframing
above. I5 measured a two-factor drift on **price** and it lost - the fit set the
second component's noise to zero. Two factors on **volatility** is a different
claim, and the HAR result says variance does have structure at several time
scales. A continuous-time two-factor stochastic volatility model is that claim
in SDE form, and it is the natural shape for the VOLATILITY subject.

**3. Two framings worth having, neither a method.** A Fokker-Planck equation
propagates a **density** where a Kalman filter propagates a point and a
covariance and `swarm` propagates a sample - so the kinetic literature is the
continuum limit of what `swarm` approximates. Not actionable at four states and
two hundred particles, and useful for knowing what the approximation is *of*.

And the opinion-dynamics work - "Breaking consensus in kinetic opinion formation
models on graphons" - is literally about consensus forming and breaking. A level
**is** a consensus price, and a level breaking is consensus breaking. That is
the most precise statement of this package's own thesis found in any reference
read today, and it arrives with no way to apply it: these models need the
agents, and this desk sees only the price they agreed on.

**Out of reach, recorded so nobody re-reads them hoping**: high-order compact
finite differences, Wasserstein gradient flows, minimizing-movement schemes and
Lagrangian meshes all need a PDE to solve. Local volatility calibration by SQP
or semi-smooth Newton is the right machinery for a hundred parameters and this
package fits one to five, where a grid is both sufficient and auditable.

## A unified theory of order flow, market impact and volatility

Muhle-Karbe, Ouazzani Chahdi, Rosenbaum and Szymanski, March 2026. **The most
directly relevant paper read for this work**, and the one that says the members
are the wrong shape.

Order flow is split into **core orders** and **reaction flow**, both Hawkes
processes, and the scaling limit pins four separate empirical facts to a single
statistic `H0` - the persistence of the core flow:

| quantity | the theory |
| --- | --- |
| signed order flow | fractional with Hurst `H0`, plus a martingale |
| traded volume | rough, Hurst `H0 - 1/2` |
| volatility | rough, Hurst `2*H0 - 3/2` (no-arbitrage forces this) |
| market impact | power law, exponent `2 - 2*H0` |

Empirically `H0 ~ 3/4`, which gives volume roughness `1/4`, **volatility
roughness ~ 0**, and an impact exponent of **1/2** - the square-root law. Four
facts, one parameter, and the estimate matches all of them.

### What it says about this package: every member is too smooth

**Volatility is rough, with Hurst near zero.** Every member here models smooth
dynamics - `linear` integrates a jerk, `reverting` is an Ornstein-Uhlenbeck,
`selective` is a sum of exponential averages, `swarm` anchors a random walk -
and a rough process is nothing like any of them. Its increments are negatively
correlated and its paths are far more jagged than Brownian motion, where OU is
diffusive at short scales.

**And it explains why HAR won.** A multi-scale blend of realised variances is
the practical approximation of a long-memory fractional process, which is why
Corsi's model is hard to beat - so `statespace-volatility.md`'s result is
*evidence for* rough volatility rather than merely a good estimator. The theory
then says a properly fractional model should beat HAR, which makes HAR the
named null for it rather than the answer.

So the member this points at is **a rough or fractional volatility state**, and
it is the natural occupant of the VOLATILITY subject argued for in
`statespace/README.md`. It is not in `family.PENDING`, which lists
particle, hmm, rfs and dpm - all of them smooth.

**Two things are cheap to measure from data already held**: the Hurst exponent
of realised variance, which the theory says should be near zero rather than
1/2, and the impact exponent, which it says should be 1/2. The first is the
decisive one and needs nothing but the bars.

**The mechanism is out of reach and the consequences are not.** Hawkes
processes on signed order flow need aggressor-classified trades, which this desk
does not have - the same wall `statespace-reading.md` records for delta, OFI and
VPIN. But rough volatility, rough volume and power-law impact are all
statements about price and volume series, and those are held.

One caveat on the volume half: the theory's "traded volume" is size, and a CFD
volume is a **tick count**. So the `H0 - 1/2 = 1/4` prediction is not testable
on these feeds, for the same reason Amihud scored -1% to 8% here.

### And the warning it carries about every comparison in these documents

The paper's own estimation problem is the one this work has been fighting:
**"Hurst exponent estimates for signed order flow are strongly scale dependent:
they are close to 0.5 at high frequencies and increase steadily as the sampling
frequency decreases."** Their resolution is a *mixed* model - fractional plus
martingale - under which "parameter estimates become remarkably stable across
aggregation scales".

That is the same disease as bar-counted windows, treated at the other end. This
package made the **window** scale-invariant; the paper makes the **estimator**
scale-aware. **Both are needed**, and only one of them is done here - so a
comparison across 15m, 1h and 1d with spans correctly stated in hours can still
be comparing scale-dependent estimates. See the time section in
`statespace/__init__.py`: portability of the window is necessary and not
sufficient.
