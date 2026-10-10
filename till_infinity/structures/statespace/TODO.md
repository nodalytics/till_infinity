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

For a level touched forty times across three weeks, "the entire touch history
compressed into k numbers, optimally" is a different claim from "position, rate
and acceleration right now" — and it is nearer the claim this desk's levels are
supposed to embody, that a level **is** its history.

**Null:** `linear` and `reverting` on held-out one-step predictive likelihood over
the same measurement series, scored exactly as I5 was. It is a drop-in: same
`Filter` protocol, same `smooth` factory, a different `A` and `C`. Legendre
Memory Units (Voelker, Kajic and Eliasmith 2019) are the same idea a generation
earlier and worth reading beside it.

### D2. Selectivity, which is the step size as a function of the input — S6/Mamba

The article's selective SSM makes the parameters depend on the input, breaking
time-invariance to buy "a capability previously offered only by the self-attention
mechanism of the transformer architecture". The step size `delta` is one of those
parameters.

Half of this is already here under another name: `robust` makes the measurement
weight a function of the innovation, which is an input-dependent gain. The
missing half is the interesting one. **`dt` here is clock time between touches,
and a level does not age by the clock** — one untouched across a dead weekend has
advanced less than `dt` says, one untouched through an NFP print more. `regime`
and the per-feed volatility are already computed, so `delta = dt * activity`
costs one parameter and no new data.

**Null:** the same member on clock `dt`, held out. If event time does not beat the
clock then the clock was right and this closes.

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

### Noted and declined

| from the article | status here |
| --- | --- |
| S4, DSS, S5 — structured SSMs | **declined**: their structure is a trained `A`, and we have ~10^5 touches and need an explainable refusal |
| Mamba, selective SSM (S6) | **declined as an architecture**, adopted as D2's idea |
| recurrence/convolution duality, FFT training | **noted, little use here**: it needs uniform `delta` and time-invariance, and touches are irregular; the harnesses that do use uniform bars loop over 999 of them |
| hardware-aware parallel scan | **noted**: a throughput fix for sequence lengths this desk does not have |
| zero-order hold, bilinear, Euler | **already stronger**: `reverting.py` uses the exact closed form, with `-expm1(-theta*dt)` where the naive expression cancels, and `tests/test_statespace.py` checks it against both a van Loan reference and quadrature |
| expectation maximization, N4SID | **already named** — I11 and `family.PENDING` |
| HiPPO, Legendre Memory Units | **adopted as D1** |
| trained `A`,`B`,`C` by backpropagation | **declined**, in the article's own words: a great deal of training data, and not interpretable |

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

**This is not a speed argument.** The recursions run over hundreds of points, not
millions. It is that the arithmetic is the part most likely to be quietly wrong
and the part numpy makes unnecessary to write.

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
