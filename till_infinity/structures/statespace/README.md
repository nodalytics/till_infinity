# statespace: what is known, what is measured, and what is not done

`__init__.py` is the contract - what this package is for, the rule that nothing
in it publishes, and what a state space can honestly claim about a market. This
file is the working record underneath it: every measurement taken, every
reference read, every idea carried, and every mistake worth not repeating.

**The rule from the package docstring applies to every line here: nothing
publishes until it has beaten a named null on held-out data.** Order within each
section is the order worth doing them in.

## What is in this file

| | |
| --- | --- |
| **Making this module work well** | the current priority, and what is already closed |
| **Measured** | the eurusd and four-symbol runs, the four quantities on real data, and what each one actually showed |
| **The members** | `selective` and `swarm` - what they are, what they cost, and what fixes each trade-off |
| **The papers and the code** | S4, Mamba 1/2/3, HiPPO, LMU, the reference implementations, and which of their ideas transfer |
| **D1 to D4** | the four borrowed ideas that are worth testing here, each with its null |
| **Questions answered** | trend changes, multi-timeframe, candlestick liquidity, and whether any of this can model an adaptive market |
| **Members not written** | with the null each must beat, from `family.PENDING` |
| **I1 to I11** | the spec's own improvement list and where each one stands |

Three things in here are corrections of claims this package made earlier and got
wrong - the touch price was never missing, numpy did not speed up the smoother,
and "zero-order hold, which is what Mamba uses" was wrong twice over. They are
kept with their measurements rather than quietly fixed, because each one was
believed for a while and the reason it was believed is the useful part.

## Making this module work well — the current priority

1. ~~**The smoother.**~~ Written — `smoothing.py`, the Rauch-Tung-Striebel
   recursion, **verified against a dense reference** rather than against itself.
   On a generated path with known truth it takes RMSE **0.2213 to 0.1135**, its
   standard deviation is never worse than the filtered one, and at the true
   parameters its error matches its own stated uncertainty to within 5%.
   Research only: reading it live would be using tomorrow's bars to decide
   today's trade.

   The reference was not optional. The first version had `_gain` building the
   columns of `P F'` in reverse and was **19% worse than it should have been**
   while still looking right — it smoothed, it beat the filter, and nothing in
   the output said otherwise. What exposed it was the property that a *wrong*
   `jerk` beat the true one on 25 seeds out of 25, which is impossible for a
   correct RTS because its mean is the minimum-mean-square estimator at the
   true parameters.
   **What is left is the fixed-lag form**, which bounds latency by the lag
   rather than by the end of the series — the only version a desk could read,
   and even then probably should not.
2. ~~**A stable state equation (I3).**~~ Written — `reverting.py`, an integrated
   Ornstein-Uhlenbeck where the rate reverts at `theta` instead of
   random-walking. Measured first, held out, on eurusd 4h: **+0.96 nats per
   point**, innovation spread 1.294 to **0.985**, Ljung-Box 5.96e-27 to
   1.22e-04. Projection is bounded by `rate / theta` however far ahead you ask,
   so the horizon cap becomes unnecessary rather than merely unused.

   **Three things it does not do, and they set what comes next:**

   * **Autocorrelation survives** at p = 1.22e-04. Structure remains that a
     reverting rate does not capture — that is **I8**, and the candidates are
     quantities the desk already computes (hour-of-day share, activity) rather
     than another dynamics tweak.
   * **Non-normality gets worse**, 9.18e-89 to 8.83e-183. A reveal, not a
     regression: a marginally stable rate absorbs a large move by running away
     with it, so the move never appears as an outlier. Fix the dynamics and it
     does. **This inverts the order** — `robust.py` is a `PY` change and was the
     smaller error while `PX` was wrong; it is the dominant remaining one now
     that `PX` is not, and it has a far better case than before.
   * **`theta` came out at 0.5 per hour**, a 1.39-hour half-life, so a 4h bar
     retains 13.5% of its drift. The best-fitting model of a level's drift is
     one in which that drift is **very nearly noise** — which is where every
     other result on this desk that survived a control has landed: magnitude
     predictable, direction not.

   All of it measured on **closes, not touches**, so it sets the direction and
   none of the constants.

3. **EM**, which needs the smoother first because the E-step *is* the smoothed
   posterior. `diagnostics.fit_jerk` searches one parameter; EM fits the set,
   with a closed-form M-step for the noise covariances. That is the route to
   `jerk` **and** `R` together rather than measuring one and searching the other.
4. ~~**An end-to-end exercise on real bars.**~~ Run —
   `research/ideas/statespace_first_contact.py`, eurusd 4h, 1,073 bars. The
   machinery works and **the model is wrong on this series in all three ways at
   once**: autocorrelated (Ljung-Box p = 2e-47), non-normal (p = 9e-95) and
   over-confident by 44%.

   `robust.py` now has evidence either way, and it is the first thing here that
   does: its gate fired on **7.55%** of measurements against the ~1.2% a true
   Gaussian gives, and it took kurtosis from 6.12 to 4.67. So the tails are real
   and the cheap arm for them earns something — but the autocorrelation barely
   moves, which says **the state equation is the dominant error and the tails
   are the smaller one.** That is the order to attack them in, and the opposite
   of where reading the kurtosis alone would send you.

   **The fitted `jerk` is not evidence about `DRIFT_VOL_PER_HOUR.**` It implies
   27.0 volatility units of drift a day against the constant's 0.48, a factor of
   56 — and a bar close is not a touch. The close moves because price moved; a
   level is not supposed to. Reading that factor as a correction would be #136's
   mistake again: a number validated without checking what it is a number
   about. The touch price this needs is in the episode record, not the
   resolutions one — see the correction below.

5. ~~**The smoother is linear-only.**~~ Fixed — `smooth` takes a filter factory
   and reads its dimension from the member, so it smooths `Reverting` (two
   states) and `Gaussian` (three) through one recursion. `linear`'s result is
   unchanged to the digit, which is the check that the generalisation cost
   nothing.

   **A factory alone was not enough**, and that was the interesting part. The
   RTS gain is `C = P_t F' P_{t+1|t}^-1`, so the smoother needs each member's
   *transition* and not merely the ability to run it forward. Members now answer
   `state()`, `covariance()` and `transition(dt)`; a member that cannot state its
   own `F` declines to be smoothed, which is a true statement about the member
   rather than a limitation here.

   The 3x3 cofactor inverse went with it — one Gauss-Jordan solve, general in the
   dimension, because the members are not all the same size.

6. **A reference for anything hand-written.** Every formula in the module is now
   checked against an independent one — the generator's Cholesky against its own
   empirical covariance, `band` against actually predicting forward, the OLS
   slope and its variance against numpy, Ljung-Box and Jarque-Bera against
   numpy. That audit exists because `smoothing._gain` was wrong and was checked
   against nothing. **Anything added here arrives with its reference.**
7. **`Subject` carries no `PX0` / `PX` / `PY`.** And `Subject.filter()` always
   returns a `Gaussian`, so no subject can declare that it wants the reverting
   member — which is now the one with evidence behind it. `family.py` says a member is
   identified by which of the three distributions changes, and `subjects.py`
   still describes its state in prose. Making the three explicit per subject is
   what would let a subject and a member be composed rather than paired by hand.

## Velocity is two variables, and only one of them is learnable

Measured 2026-10-10 on 999 eurusd 4h returns —
`research/ideas/statespace_speed_and_direction.py`:

| component | ACF lag 1 | sum of first 5 |
| --- | ---: | ---: |
| signed velocity | −0.00 | **−0.047** |
| speed `|v|` | +0.16 | **+0.381** |
| direction `sign(v)` | −0.01 | −0.100 |

**Speed is 8.1× as persistent as the signed rate, and direction is a coin** —
consecutive signs agree 49.499% against 50% ± 3.102% at 95%.

The minimal-state principle says not to split velocity into speed and direction,
because they are a redundant reparameterisation of one signed number. That
assumes both halves are equally learnable. **Here one half carries all the
structure and the other is noise**, so a filter handed signed velocity is
tracking a quantity with no autocorrelation while discarding a magnitude with
+0.38.

**It also reinterprets `reverting`'s own result.** `theta = 0.5` per hour — drift
decaying 86% per 4h bar — is not the market being memoryless. It is the filter
correctly reporting that the state variable it was given does not persist.

So the implied state is `(position, log speed)` plus a separate direction
process: continuous magnitude, discrete direction, which is a **switching
state-space model**. That is I9 and it is what the HMM member would be for. The
null is already written in `family.PENDING`, and the comparison has to be
held-out because a switching model carries more parameters.

Measured on bar returns, not on a level's rate. Repeating it on a level's rate
is task 3 and it is **not** blocked: `entry` on the episode record is the touch
price, 250k of them since 2026-10-02.

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

## numpy is available here, and three hand-rolled things should go

Checked 2026-10-10. **numpy is importable in `till_infinity/structures` today**:
`structures/cycles.py` already does it, and numpy 2.5.2 is in `uv.lock` because
`river[pandas]`, `yfinance` and `pandas` all require it.

Two conditions on using it, and the second is the one that matters:

1. **It is not a declared dependency.** It is purely transitive — absent from
   `pyproject.toml`'s `dependencies`. So nothing here pins it and dropping
   `yfinance` or `river` would remove it silently. If this package comes to
   depend on numpy, it goes in `dependencies` in the same change.
2. **Import it lazily, or inside this package only.** `cycles.py` imports it
   *inside the function* with the comment "only for the simulation", and that
   is load-bearing rather than a style tic: the desk runs in a 2.6GiB cgroup on
   two cores and sits at ~2.4GB of 3.8GB, so a module-level import in anything
   `engine.py` loads at startup makes every process pay for numpy whether the
   feature runs or not. This package publishes nothing and is reached only from
   tests and harnesses, which is what makes it the safe place to use it.

### What it would replace

`smoothing.py` carries `_transpose`, `_matmul` and `_inverse` — the last being a
Gauss-Jordan solve with partial pivoting, written general in the dimension
because the members are not all the same size. It replaced a 3x3 cofactor
expansion that could only serve one member. All three are numpy one-liners, and
the tests **already** use numpy as the dense reference they are verified against:
`numpy.linalg.inv` at both two and three states and on an asymmetric matrix.

So the hand-rolled versions are a reimplementation of the reference they are
checked against, in the one module where a bug hid longest — `_gain` built the
`P F'` columns reversed and was 19% worse while still looking right, found only
when a wrong jerk beat the true one on 25 of 25 seeds.

### It is a speed argument too, which the first version of this section denied

Measured 2026-10-10, because "the recursions run over hundreds of points so this
is not about speed" was an assumption and it was wrong in two of three places:

| shape | scalar python | numpy | |
| --- | ---: | ---: | ---: |
| one series, 4,000 steps, `linear` | 9.1 ms | — | not the bottleneck |
| the 3x3 work inside a step, 4,000 times | 49.6 ms | 12.0 ms | **4.1x** |
| 500 series x 400 steps, advanced together | 205.8 ms | 7.7 ms | **26.6x** |

**The 4.1x does not survive contact with the real call pattern, and that is the
finding.** It was measured on arrays that already existed. `_matmul` and
`_inverse` take lists and return lists, so the real version pays an
`np.asarray` per call, and converting a 3x3 costs more than nine
multiplications save. Implemented as a drop-in and measured end to end over
1,200 points:

    scalar fallback   73.2 ms
    numpy arm         87.8 ms   -> 0.83x

**17% slower**, with the two arms agreeing to 9.9e-14 - so the numpy version
was correct and still worse. It was written, measured and reverted on
2026-10-10, and this paragraph exists so the next person does not spend the
afternoon rediscovering it.

The lesson generalises past this module: at 2x2 and 3x3, numpy's per-call
overhead is the dominant term, and a helper-level swap is the one refactor
guaranteed not to pay. **numpy only wins here if the data never becomes lists
in the first place** - arrays built once at the boundary of `smooth` and kept
through the forward and backward passes - which is a real refactor of the
recursion and not a substitution inside it.

**The 26.6x is the one to build for.** It is not the recursion going faster -
the recursion is sequential and numpy cannot vectorise across time, which is why
row one shows no entry. It is many *series* advanced together: one array
operation per time step covering 500 levels instead of 500 Python loops. That is
the shape every outer loop in this package already has - a grid over `theta` and
`jerk`, a sweep over feeds, a per-level fit - and it is where the time actually
goes.

So the order of operations is the reverse of the obvious one:

1. **Batch the outer loops** - the grid over `theta` and `jerk`, the sweep over
   feeds, the per-level fit. One array operation per time step across 500
   levels instead of 500 Python loops. This is the 26.6x and it is where the
   time actually goes.
2. **D1's HiPPO matrix**, the only thing here that *needs* numpy rather than
   merely benefiting from it: a dense `k x k` construction with an
   eigendecomposition behind its stability argument.
3. **The recursion itself, if ever** - and only as arrays carried end to end,
   never as a helper swap. Measured at 0.83x the scalar version, so there is a
   negative result to beat and not merely an improvement to make.

The better reason to use numpy in the recursion was never speed anyway: the
arithmetic is the part most likely to be quietly wrong, and `_gain` building
its `P F'` columns reversed - 19% worse while still looking right, caught only
because a wrong jerk beat the true one on 25 of 25 seeds - is what that costs.
`np.linalg.solve` cannot transpose the wrong operand. That argument stands
whatever the clock says, and it is worth about 15 milliseconds *against* us.

### The order to do it in

1. `smoothing._inverse`, `_matmul`, `_transpose` → `numpy.linalg.solve` and `@`.
   Solve rather than invert: the RTS gain is `P_t F' P_{t+1|t}^-1`, which is a
   linear system and not a request for an inverse, and forming the inverse is
   the less stable way to get it. The existing tests are the check, unchanged.
2. `rates.py`'s regression loops, which are a least-squares fit written out.
3. Leave `linear.py` and `reverting.py` **alone** for now. Their 2x2 and 3x3
   updates are written out with the cancellation-safe forms the tests pin —
   `-expm1(-theta*dt)` where the naive expression loses precision — and numpy
   does not help with that; it would only hide which expression is being
   evaluated.

D1's HiPPO matrix is the first thing here that genuinely wants numpy rather than
merely tolerating it: it is a `k x k` construction with an eigendecomposition
behind its stability argument, and writing that by hand would be the mistake
this section is about.

## The output equation is written down now, and `C` is where D3 will go

Added 2026-10-10, asked for as "asides the latent state we also want output y
too", and the package had been carrying the gap quietly: the **state** equation
was explicit from the first commit and the **observation** equation was not.
`value` was the first slot of the state vector by convention.

That convention is true for `linear` and `reverting` and it is not true in
general — and `selective` broke it the day it was written. Its state holds
coefficients of a basis the transition chose, so there is no slot to point at
and the output is a weighted sum of all of them. A member whose state is not
the measured quantity has nowhere to put `value` unless `C` exists.

So every member now answers:

| | |
| --- | --- |
| `state()` | `h`, the latent state, in `NAMES` order |
| `observation()` | `C`, one row per output and one column per state |
| `output()` | `y = C h`, in `OUTPUTS` order |
| `OUTPUTS` | what the rows are called |

`y[0] == value` for every member and a test holds them together, so the
convenience and the model cannot drift apart.

**`C` is where D3 arrives.** One row today because one thing is measured, a
touch price. A second row is the whole of MIMO: `drawing/confluence.py` already
argues that evidence gathered at three resolutions of one price is evidence
about one price, and the arithmetic is a `C` row per resolution over one shared
state — which is exactly what the article's worked example does, reading a
two-state system through four output rows. Nothing else has to change for it:
the `Filter` protocol carries the shape, and `output()` already returns a
vector rather than a number.

`D`, the direct input-to-output term, stays absent. The article notes it is
usually dropped; here the reason is stronger and is I1 — there is no input.

## numpy's one real opportunity, and why it is not `fit_jerk`

`fit_jerk` is golden-section, so each candidate depends on the comparison before
it. It is **sequential in candidates by construction** and cannot be batched; it
is also cheap, which is why golden-section was chosen over a grid.

`Selective` is the member that changes this. Five parameters, and there is no
golden-section in five dimensions, so fitting it means a grid — and a grid is
the shape the 26.6x was measured on: K candidates advanced through one pass of
the series together, one array operation per time step instead of K Python
loops. That is numpy where the speed-up is felt, it is required for the member
to be fittable at all rather than being an optimisation of something that
already works, and it is the next thing to write here.

The shape it needs: `h` of `(K, SIZE)`, the five parameters as `(K,)` arrays,
and the recurrence stepped once per measurement. The test it needs is agreement
with the scalar member to around 1e-12 on a handful of candidates, because a
batched scorer that disagrees with the member it is scoring is worse than no
scorer.

## The complex-adaptive question, as work rather than as a position

`__init__.py` now carries the answer as a guiding principle - non-determinism is
the premise, adaptivity is the real challenge, the model is of an observable and
never of "the market", and these members are known-misspecified with the
diagnostics to prove it. What follows from that are four jobs, none of them
written:

1. **Parameter stability across refits.** The one failure mode with no remedy is
   parameters drifting faster than they can be estimated. Fit `theta` or `jerk`
   on rolling windows and look at the spread of the estimates: if it is wide
   relative to its own standard error, no member is learnable on this series and
   that is the answer rather than a reason to try another member. **This is the
   measurement that decides whether the whole package is viable**, and it is
   cheaper than everything else in this file.
2. **Run the diagnostics on every member, routinely.** `diagnostics.py` can
   report autocorrelated residuals and non-normal ones, and it is currently
   called from harnesses by hand. A member that beats a null while failing
   Ljung-Box has found a pattern it is not modelling - which is interesting and
   is not the same as being right.
3. **Score on the observable, not on the market.** Every comparison here is one
   quantity's held-out likelihood. No member should ever be reported as
   "modelling the market", and the wording in a merge message is part of the
   discipline, not decoration.
4. **The reflexivity gap, written down because it cannot be closed here.** Every
   member assumes a passive observation. Our own orders move the book. Nothing
   in this package represents that, and a level the desk itself has been
   defending is the case where it matters most.

## Measured on eurusd, 3m to 1d: selection loses, and the LTI basis wins the fast end

`research/ideas/statespace_eurusd_timeframes.py`, run on the lab 2026-10-10.
Fitted by grid on the first half of each series, scored on the **second half**,
held-out one-step predictive log-likelihood **a point** so the timeframes are
comparable. 6,000 bars each. There is no eurusd 5m on the lab - `data/fine`
carries 5m only for the boom/crash indices - so 3m and 15m bracket it.

| timeframe | `linear` I3 jerk | `reverting` I2 OU | **S4D-Real LTI** | **S6 selection on** |
| --- | ---: | ---: | ---: | ---: |
| 3m | -24.07 | -8.49 | **-4.60** | -10.47 |
| 15m | -6.56 | -3.06 | **-2.36** | -19.00 |
| 30m | -3.99 | -2.36 | **-2.20** | -2.73 |
| 1h | -2.81 | **-1.98** | -2.21 | -2.33 |
| 4h | -3.61 | **-2.49** | -4.56 | -4.59 |
| 1d | -3.32 | **-2.10** | -2.15 | -2.15 |

Three findings, and the first was predicted, the second was not.

**1. Selection loses, on five of six timeframes.** The sixth is 1d, where the
grid picked `scale = 0.1` and it changed the score by 0.0000 - a tie reported as
a win by a harness comparing floats, not a result. This is the clean experiment
the harness was built for: `S4D-Real LTI` is `selective` with `scale = 0`, so
the last two columns are **the same model one parameter apart**. Gu and Dao said
selection "can impede their performance on data that LTI SSMs excel on" and that
layers near a raw continuous signal "should be LTI". On eurusd closes they are
right, and at 15m they are right by 16.6 nats a point.

**2. The four-state LTI basis is the best model at 3m, 15m and 30m** - better
than the integrated jerk and better than the integrated OU, by 0.16 to 3.9 nats
a point. That is new. It arrived as a by-product: `selective`'s own nested null
*is* S4D-Real, so writing the neural member handed this package a multi-timescale
LTI member it did not have and would not have thought to write. **It deserves to
be a class of its own rather than a special case of the member it beats.**

**3. There is a crossover between 30m and 1h**, and it reads as a real structural
claim rather than noise: the fast end wants **several decay rates at once** - a
basis - and the slow end wants **mean reversion** in one. `reverting` wins 1h,
4h and 1d; the basis wins everything faster. If that survives a second series it
says the right model is timeframe-dependent, which is not what either camp
assumes.

### What is wrong with this measurement

* **Bars are not touches.** A close moves because price moved; a level is not
  supposed to. Sets the direction, none of the constants - the same caveat every
  harness here carries. The version on touches uses the episode record's `entry`
  and is not written.
* **`drift = 1.5` was the top of the grid in every single `selective` fit.** The
  member wanted a larger step multiplier than it was offered, so **both
  selective columns are lower bounds** and the LTI win at the fast end may be
  understated. Widen it before quoting these numbers again. `theta = 2.0` at 1d
  is the same problem on `reverting`, and `theta = 0.1` at 15m and 30m is the
  *bottom* edge.
* **Unequal search.** 5 candidates for `linear`, 20 for `reverting`, 20 for the
  LTI arm, 80 for S6. More search for S6 and it still lost, which only
  strengthens that conclusion - but `linear` is undersearched and its last place
  is not established.
* **One split, chronological.** No rolling origin, so this is one sample of the
  answer, not its distribution.

### The 15m pathology is worth naming

S6 scored **-19.00** at 15m against the LTI arm's -2.36 - an order of magnitude
worse, where elsewhere the gap is fractions of a nat. The mechanism is a feedback
loop and it is visible in the code: a large innovation opens `delta`, a large
`delta` resets the state onto that reading, and a state sitting on an outlier
makes the next innovation large too. Selection on an unrobustified residual is
positive feedback.

**Which is also the fix, and it is already in the family.** `robust` exists to
bound the influence of a surprising reading. Composing them - selection reading a
Huber-gated `z` rather than a raw one - is the one version of S6 this data might
not reject, and it costs no new parameter.

## `selective`'s trade-offs, and what fixes each one

Asked 2026-10-10: what are the trade-offs and how do we improve on them. Seven,
ordered by how much the eurusd measurement says they cost. Three have one-line
fixes and one of them is probably why the member lost at 4h.

**1. No posterior at all.** A selective SSM is a deterministic map: `sd` is a
*fitted* parameter rather than an inferred spread, `covariance()` is absent, the
smoother returns None, and `band()` does not widen as time passes. For a desk
that sizes on uncertainty this is the worst of the seven.
*Fix:* a particle or ensemble wrapper - see the section below, which is the
principled answer and also the cheapest real one.

**2. Forward extrapolation decays to zero.** `h` summarises readings that
arrived, not a quantity that persists, so with no further readings `C h -> 0`.
A level is a thing whose whole character is sitting still.
*Fix, one line:* give the spectrum a **zero eigenvalue** - `A = diag(0, -1, -2, -3)`
instead of `diag(-1, -2, -3, -4)`. One component then never decays and holds the
level while the others track its movement. This is very likely why 4h lost by
2 nats while 15m won: a 4h gap decays everything the member knows.

**3. A zero-length step folds in nothing.** `delta` is the only entry channel,
so two venues printing the same instant give a Kalman member two pieces of
evidence and give this one none.
*Fix, one line:* floor `delta`, which is what the reference does with
`dt_init_floor = 1e-4`.

**4. Selection is positive feedback on an unrobustified residual.** The -19.00
at 15m. A large innovation opens `delta`, which resets the state onto the
outlier, which makes the next innovation large.
*Fix:* read a Huber-gated `z`, which is exactly what `robust` already computes.
Composition, not a new parameter.

**5. Five parameters and no gradient.** Grid cost grows exponentially, and the
eurusd grid was coarse enough that `drift` pinned at its top edge in all six
runs.
*Fix:* the batched numpy scorer - K candidates advanced through one pass
together, the shape measured at **26.6x** - plus coordinate descent warm-started
from the nested null at `scale = 0`, which is now known to be a good starting
point because it wins outright at the fast end.

**6. A fixed `C` reading the mean of a redundant basis.** Under a constant input
every state converges to the same value, so four states carry one number. Mamba
does not care because its `C` is learned.
*Fix:* D1's HiPPO coupling, which is precisely the off-diagonal that makes the
basis non-redundant - and which we established is the *only* structural
difference between HiPPO-LegS and the S4D-Real spectrum this member already has.
The cheaper half-fix is to fit `C`, four parameters instead of one.

**7. Selection is wrong for this data, measured.** Five of six timeframes.
*Fix:* stop selecting on the innovation and select on something discrete, which
is what selection was built for - a session flag, a news window, a regime label
from `hmm`. Selecting on a continuous residual is asking a content-based
mechanism to work on data with no content.

## A neural architecture with a particle state space - yes, and it is the right fix

Asked 2026-10-10, and it answers trade-off 1 above, closes the gap the survey
leaves open, and reuses the one numpy win that measured well. Three threads
meeting is usually a sign.

**What it is.** A particle filter whose *transition* is the selective
recurrence: K particles, each a `(SIZE,)` state, advanced by `h = keep*h + (1-keep)*gain*x`
with per-particle noise, weighted by the Gaussian likelihood of the reading, and
resampled. The posterior is then the particle spread - **uncertainty the
deterministic map cannot produce**, and it comes out as a distribution rather
than as a fitted scalar.

**Why it is affordable.** `family.PENDING` already records that fitting
*through* a particle filter needs differentiable resampling - PyDPF,
arXiv:2510.25693 - and costs a PyTorch dependency this desk does not have. That
constraint does not bite here: **running** a particle filter needs no gradients
at all, and the parameters come from the same likelihood grid everything else
here uses. The autodiff wall is only in front of backpropagating through the
resampling step, which we are not doing.

**Why it is the natural shape for numpy.** K particles x SIZE states advanced one
step at a time is exactly the batch the 26.6x was measured on. The thing that
makes a particle filter expensive is the thing numpy is good at, and the thing
that makes the recursion slow - sequential time - is unchanged either way.

**The null, which is already written.** `family.PENDING["particle"]` says it:
the linearised Kalman arm on the same model - tied for levels, won on all four
volatility series. For this version the null is sharper and nearer: `selective`
itself, scored on the same series. If the particles buy nothing over the
deterministic map, the answer is that this quantity is Gaussian enough and the
member should stay deterministic.

**Resampling is a choice and `PENDING` names them**: multinomial, residual,
stratified, systematic, SSP - and systematic is what the volatility harness
used, so start there rather than re-deciding it.

**What it does not fix.** Particles give a posterior over the state; they do not
give the state a reason to persist. Trade-off 2 - extrapolation decaying to zero
- is a property of the spectrum and has to be fixed in the spectrum. Do the zero
eigenvalue first; it is one line and it is free.

## Other neural members worth cooking up, in the order the measurement suggests

1. **S4D-Real as a first-class member.** It just won 3m, 15m and 30m outright
   while existing only as `selective`'s nested null. Promote it: four LTI states,
   spectrum `-(n+1)`, no selection, nothing input-dependent. The cheapest thing
   in this list and already the best model at the fast end.
2. **The zero-eigenvalue variant of it**, which is trade-off 2's one-line fix and
   the first candidate to beat `reverting` at 4h and 1d.
3. **D1, HiPPO coupling** - the off-diagonal, which is the only structural gap
   between what won at the fast end and the matrix the S4 paper is about.
4. **D4, an oscillatory state** - `fourier_diag`'s skew-symmetric tridiagonal.
   Nothing in the family can turn around.
5. **LMU/LegT**, for `theta` as a memory window in hours - a parameter a desk
   can argue with.
6. **Liquid S4 / LTC / CfC.** Input-dependent *time constants*, from the
   continuous-time literature rather than the language-model one, and built for
   irregularly sampled data. The Mamba paper dismisses Liquid S4 as having "a
   limited form" of selection, which is a recommendation here rather than a
   criticism: a limited, continuous-time form of selection is what survived our
   own measurement, where the unlimited discrete form lost five times out of six.
   **And it is the literature gap**: the S4-to-Mamba survey (arXiv:2503.18970)
   addresses neither irregular sampling nor uncertainty, which are this desk's
   two actual problems.
7. **The particle-selective hybrid above**, once the spectrum is fixed.

**Not worth cooking.** Mamba-2 and the SSD duality: its trade is a *scalar* `A`
per head, collapsing every state to one decay rate, and our own measurement says
the win at the fast end **came from having several**. It is contraindicated by
this desk's data rather than merely unnecessary. Likewise the gated MLP, the
attention hybrids and the hardware-aware scan - all of them exist because there
is a neural network and a GPU around the recurrence, and here there is neither.

## `swarm`: the two trade-offs fixed in a separate member

Written 2026-10-10, asked for as "let do it but another model not the current one
we have, call it another name" - so `selective` keeps losing on its own terms and
stays comparable to the runs that scored it.

`swarm` is a bootstrap particle filter over an **anchored** selective
recurrence. Two fixes, and they are separable on purpose:

* **the spectrum** - `(0, -1, -2, -3)`. The zero does not decay, so it holds the
  level while the others track movement, and `at_time` far ahead returns the
  **anchor** rather than zero. A true zero cannot be driven by the recurrence -
  the entry weight `1 - exp(delta*A)` is exactly zero there - so the anchor is a
  random walk corrected by which particles the data prefers, and the deviations
  absorb the residual around it.
* **the posterior** - `sd` is the weighted spread of the ensemble rather than a
  fitted parameter, and the band widens in a gap because the anchor wanders.
  `covariance()` comes back from the sample covariance, so unlike `selective`
  this member can be smoothed.

**`count = 1` is the anchored member without the ensemble**, which is how the
two fixes are attributed separately: S4D-Real has neither, `count = 1` has the
spectrum only, `count = 200` has both. At `count = 1` it falls back to an
asserted `sd`, honestly, because one particle has no spread.

It is not bolted onto `selective` for a measured reason: that member's read-out
is the **mean** of its basis, because all of its states converge to the reading.
Put one slow component in and it retains `1/SIZE` of the level - 39 of 250 over
48 hours. The anchor needs a read-out of *anchor plus deviations*, which is this
member's.

### The first score of it was wrong, and the bug is the interesting part

The four-symbol run had `swarm` winning 18 of 24 series. **That number was
inflated** and is withdrawn. The weighting step subtracts `max(log w)` to keep
`exp` off the floor and the shift was never added back into the likelihood, so
every step's log density was too high by `0.5 * min(error**2)` - a log-sum-exp
missing its shift.

The regression test is non-circular and worth keeping for the shape of it: with a
negligible seed spread every particle holds the same state, so the ensemble's
weighted mean predictive density **is** the ordinary Gaussian density of the
reading. That test fails with the bug and passes without it, and no comparison
against another member is involved.

## Two accessors that were the same name and different quantities

Both found by comparing members rather than by reading either one, and both the
same mistake a level down from the first:

**`loglike`.** The three Kalman members had it and `selective` called its density
`predictive`. Fixed when the family was audited - every member now answers
`loglike` and the `Filter` contract requires it.

**`last_standardised`.** `linear` divides the innovation by `sqrt(p00 + noise)`,
the full one-step predictive variance. `selective` divided by the measurement
noise alone. Over 285,688 held-out points that read as this member having a mean
`|z|` of **3.05** against `reverting`'s **1.22** while its RMSE was *smaller* -
two scales masquerading as two accuracies. Ljung-Box and Jarque-Bera are
scale-invariant so the diagnostics were unaffected, but anything comparing the
numbers was not. Both this and `swarm` now standardise by the predictive spread.

**The lesson, since it has now happened twice:** a protocol that names a quantity
does not make two members compute the same one, and the way these surfaced was
putting all the members in one table. Any new accessor added to `Filter` should
arrive with a test that it means the same thing on every member, not only that it
exists.

## What the four quantities showed on real data

285,688 held-out points, 24 series of four symbols, 3m to 1d. Coverage
recomputed on a **predictive** band - `sqrt(sd^2 + R)` - because the harness's own
column compared a state band on three members against a fitted predictive spread
on the fourth, which is the same comparability trap again.

| model | cover +/-2 | RMSE | lag-1 autocorrelation of `z` |
| --- | ---: | ---: | ---: |
| `linear` | 68.6% | 50.25 | **+0.323** |
| `reverting` | 79.4% | 2.84 | +0.092 |
| **S4D-Real LTI** | **94.2%** | **2.53** | **+0.031** |
| S6 selective | 91.4% | 14.44 | +0.071 |

**Three independent criteria agree, which is the finding.** S4D-Real fits best,
is the only member whose two-sigma band is honest - 94.2% against a nominal 95%,
where `linear` claims far more than it knows - and has the whitest residuals.
Autocorrelation is scale-free, so that last column is comparable even where the
`|z|` column was not, and `linear`'s **+0.32** is the diagnostic saying its state
equation is wrong rather than merely imprecise.

**Every member is still misspecified**, which is what `__init__.py`'s fourth
principle says to expect: no residual series is white and none is normal. The
honest reading is a ranking of wrongness, not a model that works.

**`existence` was identical across all four at 0.958** - as it must be, since it
decays on elapsed time alone and they were fed one timeline. That is a check
passed rather than a result, and it is the cheap confirmation that the harness
drove every member on the same clock.

## Can these track where a trend changed, and what happens when price returns?

Asked 2026-10-10, about a specific case: the market trends up for five days,
stalls, bounces the other way - can the models find the exact turn, and what do
they say when price comes back to it? The answer is in three parts and only one
of them is a gap in this package.

**The stall is learnable and the reversal is not, and that is measured.** A trend
change is a sign change in the rate. On 999 eurusd 4h returns, **speed is 8.1x as
persistent as signed velocity** - the sum of the first five autocorrelations is
+0.381 against -0.047 - and consecutive directions agree 49.499% against 50%
+/- 3.102%. So "the trend stalled" is a statement about speed, which carries
structure; "and will bounce the other way" is a statement about direction, which
is a coin. A member tracking the signed rate is tracking the half with nothing
in it.

**No member can represent the turn itself.** `linear` integrates, `reverting`
pulls back, `selective` averages, `swarm` anchors - all purely decaying. They can
notice a turn *after* it has happened, as the old rate decays and a new one
builds, and none of them can produce one. That is D4 and it is the only gap in
the family that no pending member fills.

**The exact point is a level, and that machinery already exists.** A turn becomes
a level in `structures`, and `fade-to-value` already targets the displacement
origin - where its 82% figure is a target hit rate and not an entry signal. The
state space's job is not to find the turn; it is to say where that level is *now*
and how well it is known.

**What it says when price returns, which is the interesting half.** Four
quantities, and each answers a different question about a five-day-old turn:

| quantity | what it says on the return touch |
| --- | --- |
| `output()` | where the level is estimated to be now - it may have drifted, which is what `jerk` and `DRIFT_VOL_PER_HOUR` model |
| `band(when)` | how precisely, and it has **widened** over the five days |
| `existence` | whether it is still a level at all: a 7-day half-life puts a 5-day-old turn at about **0.63** |
| `last_standardised` | **the signal.** Did the touch land where the level was expected? |

That last row is the one worth building on. A return touch inside the band is the
level confirming its own position; a touch far outside it is either a level that
moved or a different level, and those are different trades. Bounding how much a
surprising touch moves the state is exactly what `robust` is for.

**And the "what does it do when it comes back" question is already answered
250,412 times.** `reactions.Episode` follows every touch for `EPISODE_BARS` both
ways and records `mfe_up_r`, `mfe_down_r`, `first`, `held_first`, `bars_up_*`,
`bars_down_*`, `bars_opposite` and a `kind` - `whipsaw` among its values. The
measurement is: condition those outcomes on the level's **age** and on its
`existence`, and ask whether a five-day-old turn behaves differently from a
five-hour-old one. No new data and no new member required, and it would settle
whether `existence`'s seven-day half-life is the right clock or a guess that
happens to match `engine.FORGET_FEED_SECONDS`.

## Multi-timeframe: not tried, and the results argue for it

Asked 2026-10-10. **No** - every timeframe in the harness is fitted and scored
independently, 3m against 3m and 1d against 1d. There is no member that sees two
timeframes at once.

**That is D3, and the measurement is now an argument for it rather than an
analogy.** The crossover is the evidence: the fast end wants several decay rates
at once and the slow end wants mean reversion, and a model fitted on one does not
describe the other. Two timeframes carrying different information is the premise
of stacking them - if 3m and 1d agreed, one `C` row would do.

The shape, which needs no new data: one state per level, one `C` row per
resolution, `output()` returning a vector it already returns. `mamba3.py` has
this implemented as `is_mimo=True` at `mimo_rank=4` - low-rank rather than dense,
which is the better first shape for the same reason the third state lost in I5:
fewer things to estimate from the same touches.

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

## Seven symbols, 3m to 1d, scored properly: S4D-Real wins and the anchor needs the particles

`research/ideas/statespace_symbols_timeframes.py`, 2026-10-10, after the
log-sum-exp fix. Four FX pairs and three Deriv synthetics - **the synthetics are
the control that matters**, because their volatility is generated and stationary
by construction, so a member winning only there is describing a simulator.

39 series. Wins by member:

| member | series won |
| --- | ---: |
| **S4D-Real LTI** | **21** |
| `reverting` | 8 |
| S6 selective | 6, every one of them a tie or within 0.002 |
| `swarm` | 2 - v25 15m and v75 15m |
| `anchored`, `count = 1` | **0, and catastrophically** |

### The anchor cannot be had without the particles, and that is structural

`count = 1` was written to answer "fix the extrapolation without the particle
part". It scores between **-71 and -101,256** a point. That is not a close loss
or a tuning failure, and the reason is worth more than the member:

**a zero eigenvalue cannot be driven by the recurrence** - the entry weight
`1 - exp(delta * A)` is exactly zero there - so the anchor is a random walk, and
with one particle there is nothing to reweight and nothing to resample. **The
anchor is therefore never corrected toward the data.** The deviations track, the
anchor drifts off, and `value = anchor + deviations` drifts with it.

So the ensemble is not an optional extra that buys uncertainty on top of a
working point estimate. **It is the anchor's only correction mechanism.** The
alternative - a gain that pulls a persistent component toward each reading - is
precisely a Kalman update on that state, which is what `linear` and `reverting`
already are. Asked to separate the two fixes, the measurement says they do not
separate.

### What `swarm` is actually good at, which is not the likelihood

It wins two series of 39, and it is **the best-calibrated member where it runs**:
96.8% coverage at v75 15m against S4D-Real's 94.3%, on a nominal 95%. That is
what it was built for and it delivers it - an inferred spread that widens in a
gap, where `selective`'s is a fitted constant.

The honest summary is that `swarm` buys **honest uncertainty at a small cost in
fit**, and on this data S4D-Real's fit is better. Which of those a caller wants
depends on whether it sizes on the band or only reads the point, and this desk
sizes on the band.

**Its first score is withdrawn.** The run before the log-sum-exp fix had it
winning 18 of 24; that number was inflated by the missing shift and should not be
quoted.

### Selection, over 39 series rather than six

Still essentially never: six nominal wins, all ties or within 0.002 a point, and
the failures remain catastrophic - **-128.86** at xauusd 4h and **-570.31** at
usdjpy 3m against LTI arms at -6.74 and -2.69. The feedback loop is unchanged: a
large innovation opens `delta`, the state resets onto the outlier, the next
innovation is larger. The paper's own limitation holds on seven symbols.

### The synthetics behave differently, and in a readable way

On v25, v75 and v100, `reverting` wins 1h and 4h where it loses those on FX, and
the whole field is closer together - v75 4h has S4D-Real at **-0.145** against
`linear`'s -0.883, the widest relative gap anywhere. A generated volatility
process is more nearly the thing these models assume, which is the expected
result and is the reason to keep them in the table: a member that cannot win on
a stationary generator has no business being trusted on a market.

### Still at the grid edge

`drift = 4.0` and `wander = 2.0` pin at the top for nearly every fit, and
`noise = 2.0` often. **Every selective and swarm number here is a lower bound**
and the grids want another widening before these are quoted as final.

## What the market does when the model is uncertain, and what signals a move

Measured 2026-10-10 on the 285,688 held-out points, conditioning the **next**
move on each quantity at the time. Asked as: what does the market do when
uncertainty is high or low, and what gives a signal that a movement - up or
down - is about to happen.

**One answer covers all of it: every quantity predicts the size of the next move
and none of them predicts its direction.**

Ratio of mean `|next move|` in the highest bucket against the lowest, over
quintiles of 71,374 points on the best-calibrated member:

| conditioned on | ratio | and the direction? |
| --- | ---: | --- |
| **`loglike_step`** - how surprised the model was | **2.18x** | coin |
| **`last_standardised`**, `\|z\|` | **2.02x** | coin |
| disagreement between the four members | 1.24x | coin |
| `sd` - the model's own prior uncertainty | 1.24x | coin |

`continue` - the next two moves sharing a sign - sat between **48.3% and 49.6%**
in every bucket of every cut. Including the signed test, which is the one that
would have been an edge: bucketed by **signed** `z`, the most negative quintile
and the most positive both give `|next|` near 1.5, with mean next moves of
`+0.034` and `-0.013`. A surprise above the model and a surprise below it are
followed by moves of the same size in no particular direction.

### The realised surprise beats the expected uncertainty, by about 2x

This is the finding worth building on. `sd` is what the model *thinks* it does
not know; `|z|` and `loglike_step` are what just surprised it. The residual is
nearly twice the signal that the covariance is - 2.0x against 1.24x - which is
volatility clustering stated in state-space terms: **what just happened predicts
the next move's size better than what the model expected to happen.**

So the usable signal here is **residual-based, not covariance-based**, and it is
direction-free, which matches what was asked for - "it could be an up or down
volatile movement". A reading the filter found surprising is followed by a move
1.8 vol units on average against 0.9 for an unsurprising one.

### A safety finding: two members are overconfident exactly when they claim precision

Coverage of the two-sigma band, by quintile of the member's own `sd`:

| member | lowest `sd` bucket | highest |
| --- | ---: | ---: |
| `linear` | **19.3%** | 87.9% |
| `reverting` | **34.0%** | 95.1% |
| S4D-Real LTI | 86.6% | 93.9% |

When `linear` is most confident its band fails **four times out of five**. That
is worse than useless to a desk that sizes on the band, and it is not visible in
an average - pooled, `linear` covers 68.6%. The failure is concentrated in
precisely the states where a caller would trust it most.

### The `existence` cut is confounded, and the confound is the lesson

Bucketing by `existence` sorted the points by **timeframe**: the median gap in
the five buckets came out 24.00h, 4.00h, 1.00h, 0.25h and 0.05h. Within a
regularly sampled bar series `existence` is nearly constant - it decays on the
clock and every bar restores it - so it varies mainly *between* timeframes. The
`|next|` and `continue` columns were identical across two different members,
which is the giveaway: they were properties of the data, not of the model.

**`existence` cannot be tested on bar data.** It needs genuinely irregular gaps,
which is the touch series - `reactions.Episode`, 250,412 of them - where a level
can go untouched for five days and then be hit. That is the measurement that
would say whether the seven-day half-life is right or is just
`engine.FORGET_FEED_SECONDS` borrowed.

### What else could signal a move, and is not yet tested

* **Speed rather than uncertainty.** Speed is 8.1x as persistent as signed
  velocity, and `rate` is on every member. Untested as a size predictor, and it
  is the obvious companion to `|z|`.
* **The band *narrowing*, not its level.** This measured the level of `sd`. A
  squeeze - `sd` contracting and then expanding - is the classic version and is
  a different variable. `linear` also exposes `sd_rate` and `sd_accel`, which
  are uncertainty about the *rate*, and neither has been looked at.
* **A rolling Ljung-Box breaking.** Residuals that suddenly correlate are a
  state equation that has just stopped describing the series, which is a regime
  change by definition. `diagnostics.residuals` already computes it; nothing
  calls it on a rolling window.
* **The wick subject.** Mazza's one directly usable result is that Dojis go with
  sharply *lower* high-low volatility and higher book liquidity, and this desk
  can compute spread, high-low and activity even without a book.

## Is the innovation's reversion bigger than the spread? Mostly no

`research/ideas/statespace_innovation_reversion.py`, 2026-10-10. The four-step
plan, executed in the order where the first step can kill the rest.

**1. The cost gate. 3m fails, eurusd 15m passes, and the sign is not stable.**
"Edge" is the predicted move for a two-sigma surprise divided by the median
spread, so below 1.0 the effect sits inside the cost of taking it.

| series | best t | edge, spreads | verdict |
| --- | ---: | ---: | --- |
| eurusd 3m | **-7.1** | 0.16 - 0.85 | **strongest effect, least tradeable** |
| eurusd 15m | -5.2 | 1.15 - **2.42** | clears the spread at h = 2, 5, 10 |
| eurusd 1h | -2.2 | up to 3.41 | weak t, wide bands |
| gbpusd 3m | -5.8 | - | same sign as eurusd |
| usdjpy 3m | **+5.8** | 0.13 - 1.00 | **sign flips: momentum, not reversion** |
| xauusd | -3.2 | 0.07 - 0.83 | nothing consistent, signs flip |

The first row is the lesson. eurusd 3m has the best statistics in the whole
table and the worst cost ratio, because the 3m spread is **0.343 volatility
units** - a third of a typical bar. A statistical effect that lives inside the
spread is microstructure, and the fact that it is strongest where the spread is
widest relative to the move is the signature of bid-ask bounce rather than of a
view about price.

**And the sign is not stable across symbols**: eurusd and gbpusd revert at 3m,
usdjpy trends, xauusd does neither consistently. That is not one phenomenon. The
search covered roughly 150 cells - five symbols by three timeframes by five
horizons by clipped and raw - so eurusd 15m surviving is **a candidate, not an
edge**, and it needs a different period before it is anything.

**2. Robustifying works, and for the predicted reason.** Clipping the innovation
at 2.5 sigma strengthens reversion where it exists - eurusd 3m `t` from -4.6 to
-6.1 at h=1 and -5.6 to -7.1 at h=5, eurusd 15m h=10 edge from 1.58 to 2.42 -
and **kills momentum where that is what is there**: usdjpy 3m from `t = +5.8` to
`+1.6`. So **large innovations carry continuation and small ones carry
reversion**, and the Huber gate separates them. That is exactly what `robust`
was written for and this is the first measurement of it doing the job.

**3. Ten bars beats one, confirmed.** On eurusd 15m the clipped edge runs 0.92,
1.30, 1.54, **2.42**, 0.98 across h = 1, 2, 5, 10, 20. It accrues to ten bars
and then decays, so the natural horizon there is about two and a half hours and
not a bar.

**4. Cross-resolution confirmation buys nothing, and the first version of that
test was invalid.** With the 15m innovation correctly lagged by one 15m bar, the
"3m and 15m agreeing" slope has the same sign and a *weaker* `t` than 3m alone -
-2.2 against -4.8 on eurusd - because only 58-61% of bars agree and the sample
shrinks. Requiring confirmation costs more than it buys.

**The version before the lag reported slopes of +0.43 to +0.73 at `t` of +14.5
to +20.8, uniformly positive on all five symbols including the synthetic
generator.** A 15m bar stamped at T does not close until T+15m, so attaching its
innovation to 3m bars from T onward used up to twelve minutes of the future. An
effect that strong, that uniform, and present on a generated series is the
signature of leakage - and the agreement rate falling from 73% to 59% once the
lag was added is how much was leaking.

### And the unit error before it, which is the same kind of mistake

The first run of this harness reported the median spread as **136 volatility
units** on usdjpy 3m. A spread 136 times the typical bar move would mean the
market is untradeable, which is how it announced itself: `spread` in the seqlab
npz is in **points**, not price, and dividing as though it were price inflated
the cost by `1/tick` - a factor of 100,000 on EURUSD. `tick_size` now infers it
from the series as the smallest non-zero absolute change, which recovers 1e-5
for EURUSD, 1e-3 for USDJPY and 1e-2 for XAUUSD and the synthetics.

**Both mistakes were caught by the result being physically absurd rather than by
reading the code.** That is worth keeping as a habit: a number that cannot be
true about a market is a faster check than a review.

## One-step scoring is the wrong objective, and it favours the wrong member

Noted 2026-10-10: the desk trades many bars ahead, and **every comparison in
this file was scored on one-step predictive likelihood.** That is the objective a
random walk is best at, and it is the objective `at_time` is irrelevant to.

It matters most for the member it was supposed to favour. `swarm`'s anchor exists
precisely so that extrapolation far ahead returns the level rather than decaying
to zero, and one-step scoring cannot see that: at `h = 1` the anchor has barely
moved. So `swarm` was measured on the one horizon where its distinguishing
feature does nothing.

The signals do survive longer horizons, which is the encouraging half - ratio of
the next move's size, highest signal quintile against lowest:

| signal | h=1 | h=5 | h=20 | h=50 |
| --- | ---: | ---: | ---: | ---: |
| speed | 3.13 | 2.89 | 2.39 | **2.03** |
| `\|z\|` | 2.02 | 1.85 | 1.59 | 1.47 |
| `sd` | 1.25 | 1.23 | 1.16 | 1.08 |
| squeeze | 1.53 | 1.45 | 1.25 | 1.17 |

**Speed still gives 2.03x at fifty bars.** And the series itself diffuses at
1.00, 1.04, 1.06 and 1.07 times a `sqrt(h)` random walk over those horizons - so
very nearly pure diffusion, with a hint of trending that grows with the horizon.

**What this requires:** an `h`-step scoring arm in the harness, comparing
`at_time(t + h)` against the realised close `h` bars later and the coverage of
`band(t + h)`. Until that exists, every ranking in this file is a ranking at one
bar and should be read as such.

## Fade the slope, or follow it? Follow, on the daily - and the fades were an artefact

`research/ideas/slope_fade.py`, 2026-10-11. Asked for: forecast volatility and
**invert** the recent slope, try a one-to-two week lookback, size by
`1/forecast vol`, filter on overstretch above one standard deviation, add an EMA
over slopes and an EMA over z-scores, and check by volatility regime.

1,800 cells - five symbols by four timeframes by five lookbacks by three signal
flavours by three horizons - of which **4.9 are expected above `|t| = 3` by
chance**. So the list matters less than whether the survivors cluster.

### The correction that changed the answer

The first run found fading a one-to-two week slope on 15m bars with
`t = -10.8`, on usdjpy **and on v75**. A generated series showing the same
effect as a market is the synthetic control doing its job, and the cause was
overlapping windows: at `look = 960` and `h = 50`, consecutive observations
share 1,010 bars out of 1,010, so ten thousand of them are nothing like ten
thousand independent draws. Overstating `t` by about `sqrt(overlap)` is how this
kind of test manufactures significance.

`independent()` now steps by the horizon and keeps one observation per
non-overlapping window. **Every long-lookback fade disappeared.** The table still
prints the overlapping `t` beside it, because the gap between the two is the
most instructive number in the harness.

### What survives

**Following the slope on daily bars, on usdjpy, in nine neighbouring cells:**

| signal | look | h | follow R | independent t | after cost |
| --- | ---: | ---: | ---: | ---: | ---: |
| slope | 10 | 5 | +0.151 | +3.9 | +0.102 |
| slope | 20 | 5 | +0.177 | +4.9 | +0.129 |
| ema slope | 5 | 5 | +0.137 | +4.1 | +0.089 |
| ema slope | 10 | 5 | +0.157 | **+4.7** | +0.109 |
| ema slope | 20 | 5 | +0.156 | +4.3 | +0.108 |
| ema zscore | 5 | 5 | +0.138 | +3.9 | +0.089 |
| ema zscore | 10 | 5 | +0.158 | +4.5 | +0.110 |
| ema zscore | 20 | 5 | +0.166 | +4.6 | +0.118 |

All three signal flavours, all three lookbacks, the same horizon, the same sign,
and **positive after one spread**. That is the pattern a real effect makes and an
isolated square does not. eurusd 1d agrees on two cells, `t` +3.1 and +3.4.

**The EMA variants are the best of the three**, slightly: `ema slope` and
`ema zscore` reach `t = +4.7` where the raw slope reaches +4.9 at one lookback
and +3.9 at another. Smoothing helps a little and standardising before smoothing
helps about as much as smoothing alone, which is worth knowing because the
z-score version is the more expensive one to compute.

**v75 produced no survivors at all**, which is the control working: the
surviving effects are on markets and not on a generator.

### The one surviving fade is exactly eaten by the spread

gbpusd 15m, `ema slope` and `ema zscore`, `look` 5 and 10 at `h = 5`:
`follow` is -0.113 to -0.147 at independent `t` of -3.0 to -3.2, so fading earns
that much gross. The 15m spread there is 0.113 volatility units. **The edge and
the cost are the same number**, which is the third time in this file that a real
effect has turned out to be the size of the spread.

### Volatility regime: no structure, and the claim is not supported

"Fading breaks in high-vol breakouts" is testable and does not hold here. On
eurusd 15m the fade is **strongest in the quietest regime** - `follow` -0.166 at
`t = -4.0` - and also negative in the fastest, -0.181, with the `fast` bucket
*positive* at +0.106. eurusd 1h runs the other way: positive in the two quiet
buckets, negative in `fast`. The sign flips across regimes and timeframes without
order.

### How wide does it get in N bars - the useful table

The full range travelled inside the window, in volatility units. This is the
number a stop and a target actually need and it was the easiest of the four
questions to answer:

| series | N | median | p90 | p99 | max |
| --- | ---: | ---: | ---: | ---: | ---: |
| eurusd 15m | 5 | 3.45 | 8.37 | 17.65 | 44.71 |
| eurusd 15m | 20 | 8.75 | 19.26 | 35.72 | 66.57 |
| eurusd 15m | 50 | 15.57 | 31.70 | 58.43 | 88.95 |
| eurusd 1h | 50 | 20.07 | 37.48 | 62.33 | 127.40 |
| eurusd 4h | 50 | 19.99 | 37.29 | 62.39 | 90.06 |

**A trade held 50 bars on eurusd 15m sits through 15.6 volatility units of
wandering at the median and 58 at the 99th percentile.** Against that, the
scalper strategies' `max_against_vol = 1.5` and `trail_vol = 0.5` are sized for
a completely different horizon - which is consistent, since those are scalps,
and is worth having written down the moment anyone proposes holding one longer.

The range grows faster than `sqrt(N)`: the ratio runs 1.54, 1.96, 2.20 at 15m
across N of 5, 20, 50. A random walk's expected range is about `1.6*sqrt(N)`
times the per-step size, so 15m is near that and the longer timeframes sit
above it.

### What this says about the proposal

**Invert the slope: no.** The fades either vanish under the overlap correction or
are the size of the spread. The direction that survives is **follow**, which is
consistent with the diffusion measurement that preceded it - this series travels
at 1.00 to 1.07 times a `sqrt(h)` walk, faintly *trending*, and a fade wants the
opposite.

**Forecast volatility: yes, and it was never the doubtful half.** Speed predicts
the next move's size with a 3.12x spread at one bar and 2.03x at fifty, which is
what makes `1/sigma` sizing and the overstretch ratio meaningful.

**One-to-two weeks: on daily bars it is the 5-10 bar lookback**, which is where
following works. On 15m it is 480-960 bars, where the apparent effect was the
overlap artefact.

## Are these models finding structure in randomness?

Asked on 2026-10-11, and it is the right question. **Mostly yes, and this file
now contains six demonstrations of it - four of them mine.** Written down as a
section rather than a footnote because the methodological lesson outlasts every
number above it.

### The six times structure appeared and was not there

| what was claimed | how large | what it was |
| --- | --- | --- |
| fading a 1-2 week slope at 15m | `t = -10.8` | overlapping windows; gone at `t` on independent ones |
| the same, on **v75** | `t = -10.7` | a *generated* series, so there was nothing to find |
| 3m and 15m innovations confirming each other | `t = +20.8` | lookahead: a 15m bar stamped at T closes at T+15m |
| `swarm` winning 18 of 24 series | - | a log-sum-exp missing its shift, inflating every step |
| `S4D-Real` winning 21 of 39 | - | too narrow a grid; it **is** the random walk once `drift` is free |
| the innovation reverting at 3m | `t = -7.1` | real, and 0.16 spreads wide - inside the cost |

Three were my bugs, two were method artefacts, one was real and unusable. Not
one of them was caught by reading the code.

### What caught them, which is the transferable part

**The synthetic control.** v75, v25 and v100 have *generated* volatility. A
method that finds an effect there is finding it in its own machinery - and when
the 15m fade appeared on v75 as strongly as on usdjpy, that was the end of it.
After the overlap correction v75 produces **no survivors at all**, which is the
control working in the other direction: it now says the surviving effects are
properties of markets.

**Counting the cells.** The slope harness tests 2,250 of them, so **6.1 are
expected above `|t| = 3` by chance**. It found nine. A list of survivors whose
length matches the noise rate is not evidence, and printing the expected count
beside the found count is what makes that impossible to forget.

**Asking whether survivors cluster.** Noise scatters; structure does not. The one
effect that survived everything is six cells in a single corner - usdjpy daily,
`h = 5`, two related signals, three adjacent lookbacks, same sign, positive after
cost. That is a different object from nine cells sprinkled across five symbols.

**Correcting the overlap properly.** Observations are independent only when they
share neither outcome window nor *signal* window, so the step is
`max(look, horizon)`. Stepping by the horizon alone still left a four-week
lookback sharing 1,870 of its 1,920 signal bars. Tightening it removed every raw
`slope` survivor on usdjpy 1d and left only the EMA ones.

**Costing everything.** Three separate real effects in this file turned out to be
the size of the spread: the 3m innovation reversion at 0.16 spreads, the gbpusd
15m fade where the edge and the cost were both 0.113 volatility units, and the
usdjpy 15m innovation. A return before costs is not a result.

**Noticing when a number cannot be true.** Two unit errors were found because
the output was physically absurd - a spread of 136 volatility units on a market
that trades, and an `existence` of 0.045 on a level touched every fifteen
minutes. Faster than review, and it should be the first check.

### And what is left, which is not nothing

**The data looks like a random walk with forecastable volatility.** That is the
synthesis and every measurement here is consistent with it:

* it **diffuses at 1.00, 1.04, 1.06 and 1.07** times `sqrt(h)` across horizons of
  1, 5, 20 and 50 - a martingale, with the faintest trend
* **direction is unforecastable.** Every signal tested gave `continue` between
  48.3% and 49.6%, and the best signed `t` on 70,000 points was -1.7
* **size is forecastable, robustly.** Recent speed predicts the next move's
  magnitude with a 3.12x spread between extreme quintiles at one bar and still
  **2.03x at fifty**. That replicated across symbols, timeframes and horizons
* the random walk wins 17 to 21 of 39 series at every horizon, and **nothing
  beats it on the point forecast**

A random walk with time-varying volatility produces exactly what was measured:
unforecastable sign, forecastable magnitude. So the honest reading is not that
the models found nothing - it is that they found **the volatility**, which is
real, and that every directional find was artefact or spread-sized.

### What that means for the package

It does not invalidate the state space. It sets what it is for.

`reverting` beats the random walk on 11 of 39 series at **all four horizons**,
which is a member-level result repeated across series rather than a cell-level
fluke, and it is the one member that does. `swarm` is the only model whose band
is honest far out - 92.8% coverage at `h = 50` against `reverting`'s 88.0% and
`linear`'s 88.8%. Neither of those is a directional edge and neither needs to be:
a desk that sizes on the band needs an honest band, and a desk that forecasts
volatility needs the member whose uncertainty means something.

**The rule from `__init__.py` was right and is now expensive to ignore**: nothing
publishes until it has beaten a *named* null. The null has to include the random
walk, the synthetic control, the overlap correction, the cell count and the
spread - and the first version of every measurement in this file failed at least
one of those.

## Deliberate lookahead: the machinery works, and 87% of the volatility is on the table

`research/ideas/lookahead_oracle.py`, 2026-10-11. Asked for as a diagnostic, and
it is the right one: every null result so far has two explanations that the
measurements cannot separate - **there is no signal**, or **the models cannot use
it**. Handing them the future on purpose separates them.

### 1. Given the answer, the models report it. The machinery is sound.

The leak dial feeds a member `k` bars past the decision point before asking it to
forecast `h` ahead. RMSE, eurusd:

| h | leak=0 | leak=1 | leak=2 | leak=5 | leak=20 |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 20 (15m) | 7.28 | 7.11 | 6.94 | 6.38 | **0.99** |
| 20 (1h) | 9.34 | 9.09 | 8.83 | 8.09 | **0.51** |
| 20 (1d) | 7.12 | 6.95 | 6.79 | 6.25 | **0.01** |

**The error collapses exactly when the leak reaches the horizon** - when the
member has seen the bar it is being asked about - and it collapses to 0.01 on
daily bars. Beyond that it rises again, because the state has moved past the
target. So the filters can represent and report the value when they have it: the
null results are **not** a broken implementation.

### 2. Perfect direction is worth 7 to 800 spreads. Cost is not the constraint.

The ceiling on any directional strategy, as a multiple of the spread it would
pay:

| series | h=1 | h=5 | h=20 |
| --- | ---: | ---: | ---: |
| eurusd 15m | 7.2 | 15.5 | 31.9 |
| eurusd 1h | 29.2 | 68.2 | 143.3 |
| eurusd 1d | **174.9** | **411.5** | **798.3** |
| v75 15m | 2.3 | 5.2 | 10.5 |

**This reframes every "inside the spread" conclusion in this file.** The effects
found were spread-sized; the *prize* is 7 to 800 times the spread. So the honest
statement is not "nothing is worth trading here" - it is **"we found nothing
worth trading, and the search is justified by a large ceiling"**. The binding
constraint is signal, not cost.

### 3. The volatility forecast captures about a tenth of what is achievable

Ranking by recent speed against ranking by the realised future move, which is
the ceiling:

| series | h | recent speed | perfect foresight | captured |
| --- | ---: | ---: | ---: | ---: |
| eurusd | 1 | 5.73x | 45.32x | **10.7%** |
| eurusd | 5 | 4.77x | 29.13x | 13.4% |
| eurusd | 20 | 4.00x | 26.15x | 11.9% |
| v75 | 1 | 1.04x | 13.65x | **0.3%** |

**This is the most actionable number in the session.** Volatility is the one
thing measured as forecastable here, and the simplest possible forecast - a
twenty-bar mean absolute move - captures roughly **an eighth** of the available
dispersion. There is a seven-to-nine-fold improvement available in the one
quantity that is known to be predictable, which is a far better place to spend
effort than another attempt at direction.

### 4. v75 has no volatility clustering, so it is the wrong control for this

Recent speed captures **0.3%** of the ceiling on v75 against 10.7% on eurusd,
while the oracle still shows 13.65x of dispersion to forecast. The generator's
volatility varies and **does not autocorrelate**.

That is useful twice over. It explains why v75 produced no slope-fade survivors -
there is no volatility structure there to be mistaken for direction. And it
disqualifies v75 as a control for volatility work: it is a control for *direction*
only, and a volatility model that fails on it is not necessarily wrong.

### The flaw in the smoother arm, which measured the wrong target

The filter-against-smoother comparison reported ratios **below 1.0** - 0.62 on
v75 1h - which reads as hindsight making the estimate worse. It cannot, and the
test is at fault: it compares each estimate to the **measurement**, and a
smoother's job is to be *further* from a noisy reading than the filter is. Being
closer to the reading is what a member that simply copies it achieves - which is
exactly what `swarm` scored, 0.056 against the reading and a 1.00x ratio.

Comparing against the latent truth is the only version that means anything, and
the truth is unobservable on real data. `paths.simulate` generates a path with
known states, so the honest form of this arm runs there. **Not fixed, recorded** -
the arm is marked in the harness as measuring the wrong quantity rather than
left to be read as a result.

## Members not written

Each already names the null it must beat, in `family.PENDING`. Do not add one
without it.

- **particle** — resampling is a choice (systematic is what the volatility
  harness used); fitting *through* one needs differentiable resampling (PyDPF,
  arXiv:2510.25693), which costs a PyTorch dependency this desk does not have.
- **HMM** — a discrete state is a different claim about the world, not a better
  fit, so the comparison is held-out likelihood and not regimes it can draw.
- **`rfs.py`** — the set layer: birth, death, data association, existence
  probability. Phase 2, and the only part that replaces geometry.
- **`factor.py`** — the family an instrument is measured against (I11). Measured
  twice and failed twice in its tradeable form; the escape is that as an
  instrument *state* it carries no hedge, turnover or funding.

## Not blocked. The touch price has been in the journal all along

**Corrected 2026-10-10, and it was my error, repeated across six files and three
merge messages.** This section used to say the fit was blocked on the structures
outcomes journal recording a raw touch price. It is not, and the old text gave
itself away by naming the field in the next paragraph. `Episode.to_dict`
records `entry` - the touch price - alongside `level` and `r_price`, all three
rounded to **eight decimal places**, and `service.py` journals one of these for
every touch, called or not, under `context={"shape": "episode", ...}`. There are
**250,412** of them in the journal as of 2026-10-10.

What I actually checked was the shape of the **resolutions** write, which does
carry `feed`, `interval`, `interval_log` and `level` only — and then generalised
from one write to "the journal". The episode write is a different write, it is
the one built to follow the whole path after contact, and it has what the fit
needs.

So **every `jerk` in `subjects.py` is still a placeholder**, but for the ordinary
reason that nobody has run the fit, not because the data is missing. The fit is
the same shape for all three — `var(m2 - m1) = q*dt + 2R` over measurement
pairs, slope the process variance and intercept twice the measurement noise.

The intercept is a free check on something else: it should come back near
`2 * TOUCH_NOISE_VOL**2`, and `TOUCH_NOISE_VOL = 0.40` is itself a guess, so a
fit that returns ~0.32 would be evidence and one that returns 1.5 would be a
problem found.

**The same field blocks two other measurements**, which is the argument for
adding it now rather than when one of them comes up:

- `DRIFT_VOL_PER_HOUR = 0.02` in `levels.py` — chosen per hour, applied at every
  timeframe, never fitted.
- whether cross-instrument coupling is worth building at all: correlate the
  per-level Kalman **innovations** across instruments, and if they are
  uncorrelated the off-diagonal blocks are zero and a matrix filter *is* the
  independent filters already running.

## What the three-state measurement also said

Worth separating, because it changes where effort goes. Held out on eurusd 4h:

| model | per point vs best |
| --- | ---: |
| two states, reverting rate | best |
| three states, two-factor drift | -0.138 |
| three states, white jerk | -0.831 |

**Almost all of the gap was the instability, not the state count.** Stability is
worth about 0.7 nats a point here; the third state is worth -0.14. So I3 was the
large win and I5 is a small loss, which is the opposite of how the spec's
suggested order ranks them — it puts I5 second and I3 outside the list on the
grounds that it is conditional on I5's answer. I5's answer turned out not to
gate it.

## The improvements, in the spec's suggested order

`I6` is done (`rates.py`). The rest apply to the per-level row and need none of
the set-layer rewrite, which is why they are worth doing before it is settled.

| item | what it is |
| --- | --- |
| I5 | **partly answered, 2026-10-10.** Observability is *not* the blocker: the condition number for price-only measurements at 4h is 2.5 with two states and ~40 with three, against the ~1e8 where a state stops being identifiable. A third state is estimable and still loses — a two-factor drift is 0.138 nats a point worse held out, and the fit set its second component's noise to zero rather than use it. What is left of I5 is the same question at finer sampling, where the condition number rises |
| I9 | two state spaces, and there already are two |
| I10 | the slope has a volatility, and it is currently a guess |
| I2 | the state is the memory of the system, and this one leaks |
| I8 | state, input or output — the question a feature list never asks |
| I1 | there is no input; `B` and `u` do not exist here |
| I7 | two barriers, from one model instead of three |

I3 and I4 are conditional on I5's answer. I11 is above, under members.

## Outside this package, noted so it is not lost

Not statespace's work, and not to be fixed from here.

- **The codec walk is opt-out now, and only for this package.** Any new
  subpackage of any service still lands in that service's persistence schema by
  module discovery, and the default is right — a class that should persist and
  silently does not is the worse failure — but the next package built beside a
  live one will hit the same thing. `shared/codec.py::UNPERSISTED` is the
  mechanism when it does.
- **`prune_bars_sync` is ineffective as shipped** (#129): `LIMIT` bounds the
  delete and not the ranking, so the first batch never completes on a 15.6GB
  file. Needs rewriting per-series against `bars_series_ts`.
- **Seven of fourteen frozen models have no file anywhere** — `touch90_fx15m`
  and the whole envelope for metals and crypto, three levels each — so those
  readings are silently absent. `envelope_fx15m_50` loads from inside the image,
  an older vintage than the 5 and 20 beside it.
- **Online counterparts** for shocks, expansion, touches and the envelope. The
  first three are `Scaler | Logistic` on the identical features plus a
  pending-outcome queue; the envelope needs an online quantile learner, and is
  where metals and crypto would get a reading at all.
- **A pre-existing test-ordering failure**:
  `test_levels.py::test_a_pickle_round_trip_keeps_what_was_learned` fails when
  `test_structures.py` runs before it, from a module reload in that file. It
  reproduces on clean `main` and passes in the full-suite ordering.
- **GitHub Actions has refused to start any job since 2026-10-09 09:34 UTC** for
  account billing. Every merge since has substituted locally-run `ruff` and the
  relevant suites, stated in each merge message.
- **187 broken relative links** across the repository's markdown, all
  pre-existing.

## Confirmed resolved, kept until the next restart proves it

The first successful `structures` save since 2026-09-23 landed on 2026-10-10 at
04:57:34Z, 128,017,171 bytes, with the repair line reporting 2,880 splitters and
65,689 non-finite thresholds dropped and the depth cap lowered from 980.

**The twenty feeds should stop re-warming on the next restart**, because the
restored state will finally be current. That is the claim to check rather than
assume — and the measurement is the bar count in `levels: warming` against the
747,871 of 2026-10-09.
