# State Space

`__init__.py` is the contract - what this package is for, the rule that nothing
in it publishes, that every horizon is expressed in time rather than in bars,
and what a state space can honestly claim about a market. This file is the
**design** record underneath it: the members, what each one costs, the borrowed
ideas worth testing, and the work carried deliberately rather than forgotten.

**The rule applies to every line here: nothing publishes until it has beaten a
named null on held-out data.** Order within each section is the order worth
doing them in.

## The measurements live in research/docs

This file held the design *and* the entire measurement record and reached 2,586
lines, which is past the point where either is findable. The studies moved to
where this repository keeps studies - beside `pca-residuals.md`, `peering.md`
and `imbalance.md`, which are cited from code the same way:

| | |
| --- | --- |
| **`statespace-measured.md`** | the members against each other and against a random-walk null, on seven symbols and four horizons. **S4D-Real *is* the random walk once its grid is wide enough**, and `reverting` is the only member that beats it |
| **`statespace-signals.md`** | what signals a move. Everything predicts **size** and nothing predicts **direction**; speed 3.12x, the residual beats the covariance, and three separate real effects were the size of the spread |
| **`statespace-volatility.md`** | the one forecastable quantity, and two corrections to how much of it is available - both of mine, in opposite directions |
| **`statespace-method.md`** | the six times an effect appeared and was not there. Four were my bugs and none was caught by reading the code |
| **`statespace-reading.md`** | every reference read and what it gave: S4 to Mamba-3, HiPPO, LMU, BOCPD, FOCuS, Cboe, candlestick liquidity, order flow, kinetic modelling |

What stays below is the part that describes the code rather than the market.

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
   ~~**What is left is the fixed-lag form**~~ — written 2026-10-11,
   `smoothing.lagged`. It bounds latency by the lag rather than by the end of
   the series, which is the only version a desk could read. **The lag is a
   duration, not a count**: `lagged(hours=...)` converts through the series' own
   spacing and `coverage`, because a lag of ten observations is two and a half
   hours at 15m and ten days at 1d. That conversion was itself wrong until the
   audit on the same day - it divided by the median spacing alone, which reads
   `hours` as *trading* time while `Window.bars` reads it as calendar, so
   `lagged(hours=2)` and the `2h` rung of the ladder were different lags on
   anything that closes.
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

3. **EM — still open, and now the oldest thing on this list.** It needs the
   smoother first because the E-step *is* the smoothed posterior, and the
   smoother has been written and verified since, so the blocker is gone and the
   work has not been done. `diagnostics.fit_jerk` searches one parameter; EM fits the set,
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
7. **`Subject` carries no `PX0` / `PX` / `PY` — still open.** Checked again on
   2026-10-11: `Subject.filter()` still ends `return Gaussian(...)`, hardcoded. And `Subject.filter()` always
   returns a `Gaussian`, so no subject can declare that it wants the reverting
   member — which is now the one with evidence behind it. `family.py` says a member is
   identified by which of the three distributions changes, and `subjects.py`
   still describes its state in prose. Making the three explicit per subject is
   what would let a subject and a member be composed rather than paired by hand.

### Where this list actually stands, 2026-10-11

Checked against the code rather than against the prose above, because a list
that marks its own items is a list that drifts.

| | status |
|---|---|
| 1. the smoother, and the fixed-lag form | **done** - `smoothing.smooth`, `smoothing.lagged` |
| 2. a stable state equation (I3) | **done** - `reverting.py` |
| 3. EM | **open**, and no longer blocked |
| 4. an end-to-end exercise on real bars | **done**, but see below |
| 5. the smoother is linear-only | **done** |
| 6. a reference for anything hand-written | **a standing rule, and newly in arrears** |
| 7. a subject composing with a member | **open** |

Three things the list does not say, and all three are debts rather than plans:

* **Item 2's first follow-up (I8) is open.** `reverting` left autocorrelation at
  `p = 1.22e-04`, and the named candidates were quantities the desk already
  computes - hour-of-day share, activity. `inputs.py` now *builds* those as an
  exogenous channel, and **no member consumes it**: `B` is not wired. So the
  input channel exists and the thing it was built for has not been done.
* **Item 4's follow-up is open.** Everything measured since has been on **bar
  closes**, and the note under item 4 is explicit that a close is not a touch -
  reading the fitted `jerk` as a correction to `DRIFT_VOL_PER_HOUR` would be a
  number validated without checking what it is a number about. The touch prices
  are in the episode record, 250k of them, and nothing has used them.
* **Item 6 is in arrears, including from today.** The rule is that anything
  hand-written arrives with an independent reference. `ranking.Mapping` has
  tests that pin its *behaviour* - robustness to a bad anchor, the monotone
  fallback - but its `_least_squares` is a hand-rolled Gauss-Jordan normal-
  equations solve checked against nothing. numpy is importable here. That is
  the same shape as `smoothing._gain`, which was 19% wrong while looking right,
  and it is the reason the rule exists.

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

## How to use all of this to improve the members, in order

Asked 2026-10-11, after the measurements. Six changes, ordered by expected value
over cost, and the first is free because the capability is already there.

### 1. Feed a time-varying `R`. It is already supported and was never used.

`update(measured, noise, when)` takes the measurement variance **per call** on
every member. **Every harness in this file passed a constant `NOISE = 0.4`.**

So the single most justified change needs no library edit at all: pass
`R_t` from the HAR-Parkinson forecast instead of a constant.

And it explains a result that is otherwise just a defect. `linear` covers
**19.3%** of readings in the quintile where it is most confident and 87.9% where
it is least - its band is worst exactly where a caller would trust it. A filter
whose `R` is constant while true volatility varies several-fold will do precisely
that: in quiet periods it believes a noise level far above the truth and reports
a band that is too *narrow* relative to what it should be, because the state has
been over-smoothed.

**Null:** the same member with constant `R`, on coverage and interval score
rather than on point likelihood. Cost: a line in the caller.

### 2. Scale the process noise with the same forecast.

`jerk`, `sigma2` and `wander` are **fields**, set once. A level's drift rate
should scale with market volatility for the same reason `R` should, and this one
does need a member change - either per-call process noise or a `scale(factor)`
that multiplies it.

`DRIFT_VOL_PER_HOUR = 0.02` in production is a constant chosen once and applied
at every timeframe, which is the same mistake one level up.

**Null:** constant `q`.

### 3. Give the members the high and the low. This is D3 with a reason.

A bar is **three** observations of one state - high, low and close - and
Parkinson's estimator being more efficient than close-to-close says the range is
where the information is. The package has had `high` and `low` all along and no
member has ever seen them.

`C` already takes multiple rows and `output()` already returns a vector, so the
machinery is in place: one `C` row for the close, one for the high, one for the
low, with the high and low given larger `R` because they are extremes rather
than consensus prices.

**Null:** the same member on closes only. This is the first MIMO application
with a measured reason behind it rather than an analogy.

### 4. Score on the band, not the point.

The random walk beats every member on the point forecast at every horizon, and
`swarm` is the only member whose band is honest far out - 92.8% at `h = 50`
against `reverting`'s 88.0%. **The members' value is the interval.** So the
objective should be a proper interval score - CRPS, or the interval score with
its coverage penalty - and not one-step predictive likelihood, which is the
objective a martingale wins by default.

This changes which member wins, and it is the metric that matches how the desk
sizes. It is also the cheapest reframing in this list: the harness already
records coverage and band width at four horizons.

### 5. Robustify the measurement. `robust` was never in a single comparison.

Roll's implied spread reaching 16-36% of the achievable volatility signal
confirms that bid-ask bounce is a large part of the innovation at fast
timeframes. That is a measurement artefact, not a level moving, and `robust`'s
Huber gate exists to bound its influence - and the innovation-reversion harness
found clipping at 2.5 sigma strengthening reversion and killing momentum, which
is the gate separating the two.

**Null:** `linear` and `reverting` unclipped, which is what every table here has
used.

### 6. The reframing: point the machinery at variance, not at price.

This is the conclusion the measurements actually support, and it is larger than
the five items above.

**Price is a near-martingale.** It diffuses at 1.00 to 1.07 times `sqrt(h)`;
direction is a coin in every test; the random walk wins the point forecast at
every horizon on 17 to 21 of 39 series. There is very little for a state space
to track, which is why the best member here is the one that tracks the least.

**Log-variance is not.** It is persistent, it is forecastable - 79% of achievable
with HAR-Parkinson - and HAR's win says it has structure at **several time
scales** at once. That is a description of a quantity a multi-component state
space is built for, and it is exactly what D1's HiPPO basis offers: several
decay rates in one state, which is the thing that lost on price because price has
no memory to compress.

So `subjects.py` should carry a fourth subject - **VOLATILITY**, measured by
realised variance over a bar, in log units so the state is unconstrained - and
the members should be scored on forecasting it. Everything in this file that
failed on price has a reason to work there:

| what failed on price | why it should work on log-variance |
| --- | --- |
| the multi-timescale basis (D1, S4D-Real) | HAR's win **is** the multi-scale result |
| `reverting`'s mean reversion | volatility mean-reverts; price does not |
| a persistent state (`swarm`'s anchor) | variance has a level to return to |
| the state space at all | there is something to track |

**And the honest caveat**: this is an argument, not a measurement. The null is
HAR-Parkinson itself, which is a linear regression on three realised variances
and captures 79% - so a state space on log-variance has a high bar to clear and
a cheap incumbent to beat. That is the right shape for this package: a named
null that already works.

## Looking back in time: what was added, and the half that is still missing

Asked 2026-10-11 whether these models support looking back to make decisions.
Three mechanisms, and two of them were gaps until now.

### Fixed-lag smoothing, written: `smoothing.lagged`

`smooth` conditions on the **whole** series, so its answer for ten minutes ago
arrives when the series ends - which `smoothing.py` already called "fine for a
study, useless live". `lagged` conditions on exactly `lag` measurements past
each point, so the answer for ten minutes ago arrives `lag` bars after it:
late, bounded, and usable.

It is the same Rauch-Tung-Striebel recursion run over a window rather than over
everything, so it is the same algorithm conditioned on less - **not** an
approximation of a different one. Two things stated because they are easy to
assume away:

* **it is not equal to `smooth` at the same point**, and it converges on it as
  the lag grows. Measured: the worst gap falls 0.337, 0.268, 0.241, 0.045,
  0.0006 across lags of 1, 3, 10, 30, 100. The test asserts that monotone
  convergence, which is the only honest check of a fixed-lag smoother.
* **every measurement gets an estimate**, with the `delay` that was actually
  available - fewer than `lag` while the window fills and zero for the last
  bar, which has no future at all. Returned rather than dropped, because a
  caller zipping output to input would otherwise misalign silently.

`revision` is the quantity worth watching: how far hindsight moved the estimate.
A revision much larger than the filter's own standard deviation means the filter
was confidently wrong at the time, which is a statement about the process noise
rather than about the smoother.

**What a desk would use it for**: *where was this level ten bars ago, given what
has happened since* is a better basis for placing a stop than where the filter
thought it was at the time.

### The input channel: `u` is written, `B` is not

`I1` has said since this package started that "there is no input; `B` and `u` do
not exist here". `inputs.py` closes the `u` half.

**Every window is measured in hours, never bars**, which was the specific ask
and is the right call. "200 bars" is not a horizon, it is a horizon times a
timeframe - ten hours at 3m and eight months at 1d - so a feature defined that
way means something different on every series, and this file's whole habit of
comparing across timeframes would be comparing definitions.

**And the week is seven calendar days, with `coverage` doing the rest.** The
first version hardcoded five days, on the grounds that a trading week is five
and the weekend is a closed market rather than a quiet one. That is right for FX
and **wrong for crypto and for the Deriv synthetics, which trade all seven** - it
silently shortened every crypto window by two sevenths. A constant cannot be
right for both and a per-symbol calendar table is one more thing to keep in step
with reality, so the window is **calendar** hours and the conversion uses the
series' own coverage: `(n - 1) * bar_hours / span_hours`, the share of the
calendar it actually trades.

Measured on the real files, which is the test of the inference:

| series | coverage | 1 week in bars, 15m |
| --- | ---: | ---: |
| EURUSD | **0.711** | 478 |
| GBPUSD | 0.711 | 478 |
| XAUUSD | 0.674 | 453 |
| Volatility_75 | **1.000** | 672 |
| Volatility_25 | 1.000 | 672 |

0.711 against 5/7 = 0.714 on the FX pairs and exactly 1.000 on the synthetics,
so the same `Window(168)` spans five trading days on one and seven on the other.
It reproduces the hardcoded FX answer - 478 against 480 - and fixes the other
case, which is the shape a good inference has.

Four features per window - the high, the low, the **position** of the last close
inside that range, and realised volatility over it. `position` is the one worth
having: it is unit-free in `[0, 1]`, so it travels across symbols as well as
timeframes, where a raw high is in the instrument's own units. Realised
volatility aggregates **variance** and takes the root once, per the Cboe
reading.

**Causality is the whole correctness of it.** `at(i)` reads `[start:i]` and
never `[start:i + 1]`, and there is a test for exactly that off-by-one: a spike
planted at bar 300 is invisible to `at(300)` and visible to `at(301)`. The
cross-resolution test has already shown what the other answer looks like -
`t = +20.8` across five symbols including a generated one.

### Why `B` is not wired in, which is a decision rather than an omission

`B` maps `u` into the state, and applying it needs a **state setter**. The
members are `slots=True` dataclasses with named fields - `linear` holds
`value`, `rate`, `accel`; `swarm` holds an array - and `state()` is a getter
only. So `B u` needs either a per-member `drive()` or a new protocol method with
a generic implementation behind it.

Doing it on one member would recreate exactly the inconsistency this file has
spent its measurements removing: `loglike`, `last_standardised`, `existence` and
`noise` each meant two things across members, and every one of them was found by
putting the members in a table rather than by reading any of them. A fifth of
those is not worth a reference implementation.

**And the case for `B` on a level is weak anyway**, which is worth saying before
anyone builds it. `B u` is a *known external force*: `INSTRUMENT` has one - its
family's move - and `RELATION` has one, and a level's position does not
obviously have any. The honest use of these features on a level is not `B u` at
all: it is scaling the **process noise** with the realised-volatility
component, which is improvement 2 above and a different mechanism. `I8` is the
question that decides each case - "state, input or output - the question a
feature list never asks".

## The profile's window, and whether the ladder belongs on it

Asked 2026-10-11, in two parts.

### Why modes and not bins: it was bins, and they failed measurably

`drawing/profile.py` already answers this and the reasoning is strong enough to
repeat here, because the same trap is available to anything in this package that
reaches for a histogram.

**The fair-share threshold could only ever fire when one band dominated.** A bin
qualified by holding several times its fair share, where fair is one over the
number of occupied bins - and with `N` equally busy bands each holds *exactly*
its fair share, never three times it. So a range, which is the one situation a
volume-at-price formation exists for, produced nothing by construction. **In
production it drew 3 levels out of 1,808.** The threshold is now relative to the
*busiest* mode, so several equally busy bands all pass.

**And bins have edges.** A band straddling one is split between two that each
look ordinary, where an Epanechnikov kernel puts a bump at every observation and
a band peaks wherever it falls.

A third reason was not about bins at all: **a mode is emitted once per visit,
not once.** `levels.form` clusters turns and needs three within a volatility
unit, so one point per band stamped at the window's end can never cluster.

### The ladder does belong on it, and the engine already says why

`profile.points` is handed the engine's whole series, so its horizon is
`WINDOW = 1000` **bars** - a fixed bar count, which is about two days at 3m and
three years at 1d. `engine.py`'s own comment names the consequence: "a 4h level
from four months ago was outside the window, so the levels drawn there came from
a short memory whatever their timeframe implied."

That is the same defect `inputs.py` was written to fix, and the fix is the same:
hours rather than bars, converted per series by `coverage`.

**What the multi-horizon version would buy**, and it is not just portability. A
single window cannot distinguish *busy recently* from *busy historically*, and
the difference is the thing a desk wants: a band busy over four weeks and quiet
over one is being abandoned, and one busy over a week but not four has just
formed. Density over the rungs of the ladder makes that a slope rather than an
impression - and the volatility work is direct evidence it helps, because HAR's
multi-scale blend beat every single-lookback estimator it was measured against.

An exponential weighting on visits is the other half, so a visit last week
counts more than one a month ago at the same price - `inputs.ema` is already
written and the kernel density is already a weighted sum, so this is a weight
and not a rewrite.

**The discipline is different here, and that is the point.** This package
publishes nothing; `profile` is a **production** formation pass, in
`STRUCTURES_FORMATION` alongside `pip,run,origin,equal,gap,round`. So the
multi-horizon profile gets measured in a harness against the current one-window
version before anything in `drawing/` is touched, and the null is the pass as it
stands - which already draws 204 attributions in 32,603 level calls and whose
`gap` sibling was measured at a coin.

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

## The improvements, in the spec's suggested order

`I6` is done (`rates.py`). The rest apply to the per-level row and need none of
the set-layer rewrite, which is why they are worth doing before it is settled.

| item | what it is |
| --- | --- |
| I5 | **partly answered, 2026-10-10.** Observability is *not* the blocker: the condition number for price-only measurements at 4h is 2.5 with two states and ~40 with three, against the ~1e8 where a state stops being identifiable. A third state is estimable and still loses — a two-factor drift is 0.138 nats a point worse held out, and the fit set its second component's noise to zero rather than use it. What is left of I5 is the same question at finer sampling, where the condition number rises |
| I9 | two state spaces, and there already are two |
| I10 | the slope has a volatility, and it is currently a guess |
| I2 | the state is the memory of the system, and this one leaks. **Fixed-lag smoothing is now written** — `smoothing.lagged` — which is the memory a desk can actually act on |
| I8 | state, input or output — the question a feature list never asks |
| I1 | **half closed.** `u` exists now — `inputs.py`, windows in hours — and `B` does not: see the section below |
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
