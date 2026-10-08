# What a level is, and what it could be

**2026-10-08.** A day of work on `structures` plus the design argument that ran
alongside it, written down so the argument is not lost and the work can be
judged against it.

The short version: a level is currently **one number with a variance**, and the
design that emerged is **four machines** rather than one bigger filter.

## What was built

| | what | measured? |
|---|---|---|
| [#105] | five more imbalance kinds beside the fair-value gap - `vi`, `og`, `void`, `ifvg`, `bpr` | no, emitted for the outcome machinery to judge |
| [#106] | the desk's supply/demand rule as a formation - `displace` | the *trade* is refuted; the *level* is unjudged |
| [#107] | the level's filter becomes `(price, slope)` | no |
| [#108] | the zone's width calibrated by adaptive conformal inference | on synthetic pools only |
| - | `displace` against MCFL's `DISPLACE_C` | **yes** - they are not the same rule |

## The four machines

The architecture the day's argument converged on. Each answers a different
question, and the reason to keep them apart is that each is only *valid* for
its own question.

| machine | question | state |
|---|---|---|
| **Kalman** | where is this object, and is it drifting? | `(p, v)` |
| **Conformal** | how wide must the band be to hold its coverage? | `q` (and `q⁻, q⁺` - not yet) |
| **Grammar** | what event does this state constitute? | `ORIGIN → DISPLACE → VOID → BREAK → REVISIT` |
| **Lifecycle** | which objects exist, and in what state? | birth, track, weaken, die |

### Why width is not a filter dimension

The single most useful constraint found all day, and it is about the
observation model rather than the arithmetic. **Width is not observed.** What
is observed is a hit or a miss - Bernoulli - and `|touch - centre|`, which is
half-normal at best. A linear-Gaussian filter over width would assume exactly
the thing the band exists to stop assuming.

Hence: **Kalman for the centre, conformal for the width.** Not a compromise -
each tool on the problem it is valid for.

### Why not a 6- or 8-dimensional state

Arithmetic, not taste. **You cannot estimate more latent states than your
observations identify.** A level sees a handful of scalar observations in its
life - one price per touch. An 8-dimensional state fed one scalar at a time is
unidentifiable: the unobserved directions do not converge, they track whatever
the prior said, and the filter then reports confident numbers for quantities
the data never constrained. That failure is silent, which is the worst kind
here.

The 2D filter is already near that edge, which is exactly why the slope is
gated at three sigmas of its own posterior.

An earlier draft of this cited `CONFIDENT_TOUCHES = 5` as the bound. **That
constant does not do what the name suggests** - it appears in one `if` that
chooses between "5.2 prior touches from above" and "1.0 own touches, 40 similar
elsewhere", and affects no number. The shrinkage is `PRIOR_WEIGHT = 4.0`, with
`BASE_WEIGHT = 20.0` for base rates, deliberately slower because "a base rate
is the reference everything else is measured against".

**The rule that follows: per-level state stays small; anything richer is
pooled.** That is the same shrinkage `reactions` already does between a level's
own record and kNN over similar levels, applied to the state vector instead of
the probability. It is also why the conformal calibrator pools by
`(feed, interval, side)` rather than per level - at five touches a per-level
corrector would mostly report its prior back.

## The repo already implements more of this than it says

Three places where the machinery exists without the vocabulary.

**The grammar half is MCFL.** `mcfl-roadmap.md` already specifies `BOS`, `FVG`,
`SWEEP` and `VOID` as productions with `known_at`, truncation-invariance and
flip-symmetry tests - including the VOID lifecycle `UNTOUCHED → PARTIAL →
FILLED → INVERTED`, which is the same object #105 ships as the `ifvg`
formation. The separation "continuous latent geometry here, discrete events
there" is not a proposal; it is the two tracks this repo is already on. What is
missing is the wire: MCFL re-derives its own geometry rather than reading
`structures`'.

**The lifecycle half is `levels.form` and `lv.merge`.** Read them as object
tracking and they already do birth ("a new candidate"), data association ("a
level rediscovered is evidence about an old level, not a new one"), death
(`KEEP`, `half_life_days`, `Level.age`) and state (`FRESH`, `TESTED`). It is a
hand-rolled multiple-hypothesis tracker that **commits** at every step instead
of carrying competing hypotheses. Naming it that says exactly what is missing -
association probabilities, an explicit birth/death model, and the ability to
hold "this is the old level" and "this is a new one" at once rather than
picking.

**The heavy-tail problem is already known and already dodged.** `observe_touch`
takes `done.origin or done.extreme` with the comment "the origin, not the
extreme. The extreme is a wick - liquidity taken a fraction beyond the level at
a price nobody traded around". That is the robust-filtering problem solved
**upstream** of the filter by choosing a better observation, rather than inside
it with a heavier-tailed likelihood. A Student-t observation model is the
principled version and is a handful of lines.

## Alternatives to the Kalman state, assessed against this codebase

Surveyed during the day. Ordered by what I would actually do.

### Worth doing, in this order

**1. Asymmetric conformal widths, `q⁻` and `q⁺`.** #108 pools by approach side
but still scores `|touch - centre|`, throwing the sign away. A level's residual
is not symmetric - the distance price overshoots below a floor and above it are
different quantities - and keeping the sign is strictly more information for no
extra machinery. **The cheapest real improvement available.**

**2. Normalised innovation as an event primitive.** The filter already computes
`residual` and `innovation` inside `update`; `e = residual / sqrt(S)` is free
and currently thrown away. `|e| > θ` is "price is behaving unusually relative
to what this structural zone expected" - a sensor for deviation from structural
expectation rather than just a tracker. It is the natural handshake between the
filter and the grammar.

Note it is **not** the same number as the conformal score: the conformity score
normalises by `sqrt(P00)` and asks about where price is; the innovation
normalises by `sqrt(P00 + R)` and asks whether the filter is consistent. Both
are useful and they answer different questions.

**3. Student-t observation noise.** One enormous wick can yank a Gaussian
estimator. The repo dodges this by choosing the origin over the extreme; the
filter itself is still Gaussian. And #108 gives the diagnostic for free - **the
conformity-score pools are a direct measurement of whether the residuals are
heavy-tailed**, so for once the question can be settled before the change is
made rather than after.

**4. Estimate `PRIOR_WEIGHT` instead of choosing it.** It is the `K` of a
shrinkage estimator and `K` is not a taste parameter - it has a closed form,
`K = sigma_within^2 / sigma_between^2`, the ratio of noise within one level to
real spread between levels. Both components are estimable from what the engine
already collects: the spread of per-level push-up rates across a pool, against
the binomial noise `p(1-p)/n` at each level's own touch count.

That makes the current value checkable rather than arbitrary. `PRIOR_WEIGHT =
4.0` asserts that borrowed evidence is worth four of a level's own touches. If
levels genuinely differ, true `K` is smaller and 4.0 **over-shrinks**, erasing
idiosyncrasy; if they barely differ, true `K` is larger and 4.0
**under-shrinks**, letting three noisy touches override a good pooled estimate.
Nobody has checked which.

Two things make it tractable here. The grouping it needs is the one the
conformal calibrator already maintains, so the pooling machinery exists. And
the same hand-picked `K` appears elsewhere - the per-strategy reward floors
shrink each win rate toward the desk's 46.7% with `K = 150` - so one estimator
would serve both.

The caveat is that `K` needs enough **levels** per pool rather than enough
touches per level, so it wants a run-in and a fallback to the constant, the
same shape as the conformal `SETTLE`. And `edge.md`'s four nulls are a standing
warning about adaptive parameters replacing constants - the difference is that
this estimates a variance ratio with a closed form rather than fitting a
threshold to returns.

**5. A shared drift factor.** `v_i = beta_i * G_t + eta_i`, where `G_t` is an
instrument-wide latent drift. Defensible precisely because it does not add
per-level dimensions - it pools them. If five zones all begin drifting together
that is a market-state transition rather than five coincidences, and nothing in
the codebase can currently say so.

**6. Autocorrelated observation noise, and seasonal noise.** Two more state-space
extensions with real dynamical models, unlike acceleration.

**Autocorrelation first, because it is a defect rather than a feature.** The
filter assumes white observation noise. Touches of one level are plausibly
*not* independent - consecutive touches happen in the same regime, with the
same participants - and if they are correlated the filter is **overconfident**:
it treats correlated evidence as fresh evidence and shrinks its variance too
fast. The textbook fix is to model the noise as AR(1) and augment the state
with it, `x = [price, slope, e]` with `e_t = phi * e_{t-1} + eta`, which is a
third dimension that **earns** its place in a way acceleration does not.

The reason to put it near the top is that it is already measurable with no new
machinery: the conformal pools are time-ordered residuals, so their lag-1
autocorrelation is a direct test of whether the whiteness assumption holds. If
it does not, the zone is mis-sized for a reason nobody has looked at.

**And there is a trap worth naming.** Adaptive conformal would *absorb* an
autocorrelated-noise problem - it would widen the band until coverage came
right - without fixing or revealing the cause. The calibrator repairs the
symptom. Only looking at the autocorrelation of the scores finds the disease.
That is an argument for measuring it, not against the calibrator.

Precedent for the measurement and a warning with it: lag-1 autocorrelations of
per-strategy daily P&L came out between -0.47 and +0.17 and **all inside their
own standard error** at 8-18 observations. Autocorrelation is easy to see and
hard to establish, so this wants a proper sample before it changes anything.

**Seasonality second, and not where it first sounds.** The basic structural
model adds a seasonal block - `m - 1` states constrained to sum to zero - and
for a daily or hourly cycle it is entirely standard. But a level's *price* is
not seasonal: a floor is not higher at 3pm. What plausibly is seasonal is the
**noise around it** - a touch during the Asia session and one at the New York
open are not equally informative about where the level sits.

So the honest version is a seasonal `R_t`, time-varying observation noise,
rather than a seasonal component in the state. That is cheaper, it is where the
effect actually lives, and the repo already half-believes it: `hour` is a
feature of the envelope model, `to_weekend` beside it, and `rollover.py` masks
a window around the New York rollover outright. All of that says time-of-day
matters and none of it reaches the level filter, which weighs a 3am touch
exactly like a 3pm one.

Per-level seasonality would be hopeless - `m - 1` extra states from a handful
of touches, straight back into the identifiability problem. Per **instrument**
it is very estimable, which is the same pooling conclusion everything else here
reaches.

### Interesting, and not next

**Particle filters / Gaussian mixtures.** The honest argument for them is
multimodality: "the level is at 100.2 or at 101.0" is a real state a Gaussian
blurs into one mediocre estimate. The honest argument against, here, is that
the thing producing multimodality is **two levels**, not one level with two
modes - and the repo's answer to that is `form` and `merge`, which is the
multi-object framing. Fix the object model first and the multimodality may stop
being the filter's problem.

**HSMM for the lifecycle.** A good fit on paper: `FRESH` surviving 8 bars and
`WEAKENING` 3 is exactly a duration model, and duration is what a plain HMM
gets wrong. The blocker is labels - the lifecycle states are currently
`State.FRESH` / `TESTED` and the richer vocabulary does not exist yet.

**Multi-object tracking / RFS / PHD.** The most radical suggestion and the one
with the best claim to matching the true ontology: zones are a *set* whose
cardinality changes, with birth, death, association and competition. Worth
taking seriously **because the repo already does this by hand** - which means
the upgrade path is to make `form`/`merge` probabilistic rather than to import
a new paradigm wholesale.

**Bayesian online change-point detection.** Already partly here: `prims.focus_series`
is a FOCuS change detector and `mcfl-roadmap.md` plans `FOCUS_UP`/`FOCUS_DOWN`
as grammar words. So this is less an alternative than an existing component
nobody has pointed at levels.

### Not worth doing

**Acceleration as a third dimension.** A level that curves is overfitting at
five touches, and it is the least identifiable direction in the state.

**Gaussian processes over the latent path.** The cost is real and the risk is
"an expensive way to fit noise" on a series that gives you five observations
per object.

**Force, quality, decay and pressure as Kalman dimensions.** Force belongs on
the **event** as a formation fingerprint - `DISPLACE {magnitude, speed,
efficiency, penetration}` - not in a state vector, because nobody can write
down what `F_{t+1}` means. Quality and decay already exist outside the filter
with dynamics that work: `Level.age()` discounts on a half-life, `SideStats`
carries per-side touch counts, `origins` keeps `revisits`. Moving them in buys
nothing and makes identifiability worse.

**Pressure** is the one genuinely new object of that group - "pressure building
while the centre stays put" has no representation anywhere in this codebase -
and it is testable, because the breakout is a labelled outcome. It is also the
one with the thinnest data: `fade-to-value` publishes `origin_*` on 5 of 75
closed trades, so it needs a bar-level replay rather than a read of the live
record.

## What is measured, and what is a story

Being explicit, because most of the above is a story.

**Measured.** `displace` is not `DISPLACE_C`: 131 instrument-timeframes, 2.0M
bars, the two fire at nearly the same rate and agree on about a quarter of
their union. Relative ("big for lately") against absolute ("decisive in
itself"), and they come apart hardest on thin instruments. Also measured, and
negative: the fade-to-origin trade, in all 105 cells
([`fade-to-origin.md`](fade-to-origin.md)).

**Measured elsewhere, borrowed here.** AgACI beating one-step ACI on the
volatility envelope, 89.1-89.6% against 87.8-88.1% and 2-9% narrower
([`conformal.md`](conformal.md)). That is the precedent #108 leans on, and it
is a different interval on different data.

**Not measured.** Whether a level that has earned a slope predicts its own next
touch better than a horizontal one. Whether a calibrated zone changes outcomes
on real touches. Whether any of the five new imbalance kinds, or `displace`,
mark levels price respects. Every one of those is a replay question and none of
them has been run.

**The guard rails that let unmeasured work ship.** The slope is gated so a
level that never earns one is bit-identical to the old filter; the conformal
width has a run-in so a cold service quotes exactly what it quoted before. Both
make the changes *safe*. Neither makes them *right*, and the difference is the
whole reason this section exists.

## One more thing the day taught

`test_no_published_feature_is_near_constant` caught **two** different errors on
the same feature, hours apart: the `displace` formation biasing the level book,
and the slope widening every zone. Neither looked like what it was. Both
surfaced as a published statistic going constant.

A test that asserts a distribution has not collapsed is worth more than it
looks, because the failures it catches are the ones that do not announce
themselves.

[#105]: https://github.com/nodalytics/till_infinity/pull/105
[#106]: https://github.com/nodalytics/till_infinity/pull/106
[#107]: https://github.com/nodalytics/till_infinity/pull/107
[#108]: https://github.com/nodalytics/till_infinity/pull/108
