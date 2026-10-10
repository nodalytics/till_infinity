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
   about. Still blocked on the touch-price field.

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

## Blocked on one missing field

**Every `jerk` in `subjects.py` is a placeholder and every one says so.** The fit
is the same shape for all three — `var(m2 - m1) = q*dt + 2R`, slope the process
variance and intercept twice the measurement noise — and for `LEVEL` it needs a
**raw touch price**, which the structures outcomes journal does not record: it
has `feed`, `interval`, `interval_log` and `level` only.

The field belongs on `reactions.Episode`, which is written for every touch and
already carries `level_id`, `level_price`, `started`, `entry` and `unit`. The
journal write is `service.py::record_outcomes`.

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
