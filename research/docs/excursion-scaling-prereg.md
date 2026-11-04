# Does the adverse excursion scale as the square root of the horizon?

**Pre-registered 2026-11-03, before any result was read.** The claim, the
statistic, the nulls, the controls and the pass rule below were written and
frozen first.

## Why this is worth asking

[stop-coverage.md](stop-coverage.md), measured earlier today, is the one
positive result this desk has produced in a while: the production stop is a
flat 3.0 volatility units with no horizon term, it is reached **0.016 of the
time at one bar and 0.750 at ninety-six** against a 0.100 target, and scaling
the same Student-t quantile by `sqrt(H)` beats it on **30 of 30 cells and both
sides of 15 of 15 feeds**.

**But the square root was never measured. It was derived.**
`research/ideas/stop_coverage.py` takes it from the reflection principle on a
driftless Gaussian walk - `P(min_H <= -a) = 2 Phi(-a / (sigma sqrt(H)))` - so
`sqrt(H)` is what the *model* says, not what the data says. And the same
study's own numbers say the model is not quite right: the `t-sqrt-h` arm reads

| H | 1 | 5 | 20 | 48 | 96 |
|---|---|---|---|---|---|
| realised rate | 0.133 | 0.136 | 0.150 | 0.170 | 0.160 |

against a **0.100** target. That is not noise around a constant - it rises with
the horizon and then flattens, which is the signature of a scaling exponent
that is not 0.5. A stop built on the wrong exponent is miscalibrated in a way
that *grows with the hold*, which is exactly the defect `sqrt(H)` was
introduced to fix at a different scale.

**And this is a risk claim, not a direction claim.** `findings.md` holds that
this desk can forecast risk and cannot yet forecast direction;
`direction-is-closed-not-just-null` records the direction gate finding a
*planted* drift at z +2.90 while earning 2% of a spread. The exponent governs a
stop distance, which is the half that works.

## What is not this

* `rough_volatility.py` and `volatility_roughness.py` measure roughness **in
  the variance** - how jagged volatility is - not how a price excursion grows
  with the horizon. Different quantity, different exponent.
* A Hurst exponent on the *level* has been in `inputs.py` for a long time and
  is about the level's own persistence.
* This is the exponent of the **running adverse extreme**, which is not the
  exponent of the terminal return. A variance ratio below 1 at some horizon -
  the standard reversion measure - does not imply the excursion grows slower,
  because the excursion is a maximum and the variance ratio is about where the
  path ended. Conflating them is the obvious mistake here and is named in
  advance.

## The statistic

For each feed, side and horizon `H` in {1, 2, 5, 10, 20, 48, 96}:

1. Take non-overlapping windows of `H` bars, stride `H`. Overlapping windows
   share `H - 1` bars and `overlapping-windows-inflate-permutation-nulls`
   records a level finding at p 0.015 that was anchor overlap.
2. Compute the adverse excursion: the running maximum move **against** the
   side, in trailing volatility units, as `stop_coverage.py` defines it so the
   two studies' numbers are comparable.
3. Take the `TAU` quantile of `|excursion|` at that `H`.

Then fit `log q(H) = k log H + c` by least squares over the seven horizons.
**`k` is the claim.** A walk gives `k = 0.5`.

Reported per feed and per side, never pooled first -
`pooled-medians-invert-subgroups` records a pooled median agreeing with a claim
every subgroup refuted.

## The nulls

The three arms from `level_shield.py`, unchanged, which is what
`null-structure-claims-on-the-same-detector` requires - the null walks through
the same estimator with the same bar geometry:

| arm | what it holds | what it destroys |
|---|---|---|
| `bar-shuffle` | the real bar distribution and its skew | the order, so any scaling other than 0.5 |
| `walk-geometry` | volatility and the calendar | the return distribution's shape |
| `garch-bars` | clustering, fitted per feed | everything else |

**`bar-shuffle` is the arm that matters.** Shuffling bars destroys serial
dependence and must therefore return `k = 0.5` whatever the marginal
distribution is. So it is simultaneously the null *and* a positive control on
the estimator: an estimator that returns 0.47 on shuffled real bars is
measuring its own bias, not the market.

16 draws an arm, seeded by `sha256` of the cell. `hash()` of a tuple holding a
string is salted per process and has broken four harnesses here.

## Controls, stated before the run

* **A generated Gaussian walk must return `k = 0.5`** within the surrogate
  spread. If it does not, the estimator is biased and no reading below is
  interpretable. This is the hard control and it is cheap.
* **A generated walk with fat tails** (Student-t innovations, same variance)
  must *also* return 0.5, because the exponent is a property of the dependence
  and not of the marginal. If fat tails move `k`, the estimator is reading
  kurtosis and the study is measuring `how-markets-differ-from-every-simple-
  process` again rather than scaling.
* **The two Deriv volatility indices as a placebo pair**, carried in every
  cell. `the-placebo-arm-selects-the-null` rejects any null a placebo passes.

## The pass rule, frozen

All four:

1. `|k - 0.5|` exceeds the hardest surrogate draw's deviation on **3 or more**
   non-placebo instruments, on both sides.
2. The sign of `k - 0.5` **agrees across instruments**. A mixture of exponents
   above and below 0.5 is a spread of noise, not a scaling law, however many
   cells are individually large.
3. Both generated walks return `k = 0.5` within the surrogate spread.
4. **The fitted stop flattens the coverage drift.** Replacing `sqrt(H)` with
   `H^k` must reduce the spread of realised coverage across horizons -
   `max - min`, which is **0.037** for `t-sqrt-h` as measured - on two thirds
   of feed-sides.

Criterion 4 is the one that matters. An exponent that differs from 0.5 and does
not improve calibration is a fact about the series and not a better stop, and
`fit-on-the-edge-not-the-raw-score` is the standing reason to score the thing
the desk consumes rather than the fit: fitted weights once beat hand-tuned ones
on AUC 0.604 against 0.556 while **losing on edge, +0.002 against +0.019**.

## And the ways a pass would still be uninteresting

* **If it cannot move a stop.** The bar is 0.16 of the risk. At H = 48,
  `H^0.5` is 6.93 units and `H^0.45` is 5.76 - a 17% change, which clears it -
  but at H = 5 the same exponent gap moves the stop by 4%, which does not. So
  the gain is horizon-dependent by construction and the useful claim is about
  **long holds only**, which must be stated rather than discovered.
* **If it is the spread.** The quotes in the catalogue are modelled at a
  constant median spread per feed, so a *constant* spread cannot manufacture a
  scaling. But a **changing** one can: a mid built as `bid + spread/2`
  mechanically produces negative autocorrelation when the spread moves, which
  is a known artefact on quote-derived mids. The 1d store's mids are not built
  that way, and this is checked rather than assumed by re-running the primary
  cell on `close` alone.
* **If it is one era.** Fitted on the first half and read on the second, both
  reported. An exponent is supposed to be a property of the process.

## Data

The 1d FX history plus gold - 4,477 to 6,008 bars over 6.3 to 19.9 years -
because the exponent needs horizons out to 96 and `96 * 20` de-overlapped
windows is a sample only the long history has. The 15-minute catalogue is
**explicitly secondary**: 76 days gives about 50 non-overlapping windows at
H = 96, which is too few for a quantile, and that is stated with the number
rather than omitted.

## What is deliberately not done

**No trading rule.** This changes a stop distance, which `exits.py` already
consumes through `Intent.stop_vol`, and `publish-then-measure-then-gate` is the
order: if `k` survives, it ships as a published reading and is scored on the
record before anything sizes off it.
