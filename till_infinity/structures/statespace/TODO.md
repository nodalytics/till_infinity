# statespace: what is not done

Carried deliberately rather than forgotten. Order within each section is the
order worth doing them in, and the rule from the package docstring applies to
every line: **nothing here publishes until it has beaten a named null.**

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
