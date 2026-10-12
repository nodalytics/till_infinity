# The triple barrier: the vertical barrier is the only part volatility moves

Asked for the state-space form of the triple barrier. Two bodies of work
already cover most of it, so the useful contribution turned out to be a single
missing term in a shipped function - and the control says the remedy is
arithmetic, not a filter.

The harness is `research/ideas/triple_barrier.py`.

## What was already settled, and should not be rebuilt

**`barrier-geometry-is-irrelevant.md`** proves, with 21 jump-diffusion
configurations at 40,000 paths each, that a barrier trade with market exits on
both sides earns

    E[P&L] = m = mu E[tau]

and **the geometry cancels entirely.** Since every directional result on this
desk is null against a matched control, the triple barrier cannot produce
expectancy here from its shape.

**That extends to the vertical barrier in one line.** `min(tau, T)` is a
*bounded* stopping time, so optional stopping still applies to the martingale
`X_t - mu t` and `E[X_min(tau,T)] = mu E[min(tau, T)]`. A time limit shortens
the holding period and changes nothing else. The third barrier is not a source
of edge either, and nobody needs to measure that to know it.

**`trading/barriers.py`** ships the forms - `P = (b+B)/(a+b+2B)`,
`E[bars] = (a+B)(b+B)` with the Broadie-Glasserman-Kou shift - plus
`SLOWER_ON_FEED`, a measured table of how much longer real trades run: 1.251x
at 2.5 predicted bars to **1.958x at 112, on 19 feeds of 19**, against a flat
1.047-1.111 on Brownian feeds. Its mechanism is already named there: volatility
mean-reverts, first-passage time is convex in `1/sigma`.

## Finding 1: the label is invariant to volatility. Only the timing is not

Three volatility paths, zero drift, identical absolute barriers at `+2.0` and
`-4.0`, 40,000 paths each:

| volatility path | `P(up first)` | vs gambler's ruin | mean bars |
| --- | ---: | ---: | ---: |
| flat | 0.6655 | -0.0012 | 835 |
| ramp | 0.6624 | -0.0042 | **1694** |
| two-regime step | 0.6592 | -0.0075 | 772 |

Theory says `b/(a+b) = 0.6667`. **All three agree within 0.008 while the
durations differ by 2.2x.** The small negative biases are discrete-monitoring
overshoot, in the direction it predicts.

And on real data, `P(up | resolved)` across entry-volatility quintiles:

| | lowest-volatility quintile | highest | spread |
| --- | ---: | ---: | ---: |
| traded, 48 cells | 0.510 | 0.501 | **-0.009** |
| generated, 24 cells | 0.500 | 0.486 | -0.014 |

**Flat, and the control's spread is larger than the market's.** So volatility
is a **timing** model for a barrier trade and not a label model. Anyone
predicting the triple-barrier up/down label from a volatility model is
predicting a constant - which is worth stating, because the label is exactly
what a triple-barrier ML pipeline trains on.

This also means `probability` needs no correction at all, and only `duration`
does.

## Finding 2: `slowdown` is conditionally biased, by about a factor of two

`slowdown(bars)` returns one multiple per predicted duration. Splitting trials
into quintiles by where the **entry volatility estimate sat against its own
longer mean** - 48 bars against 480 - and measuring realised over predicted:

| | cells | lowest-vol | q2 | q3 | q4 | highest | spread | `slowdown` says |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **traded** | 48 | **0.79** | - | - | - | **1.51** | **+0.61** | **1.26** |
| **generated** | 24 | 0.73 | - | - | - | 1.20 | +0.43 | 1.26 |

The same geometry runs from 79% to 151% of its predicted duration depending on
a variable the production function does not take.

**The time-out share moves with it**, 3% in the lowest quintile to **20%** in
the highest on traded feeds. That is the triple barrier's third label, and
`groundbarrier.py` deliberately sets a generous horizon to keep it small while
noting that dropping those trials is "a selection, not a rounding". The two
statements are consistent and worth separating: that comment conditions on
*realised* volatility falling short, this conditions on the *entry estimate*
running high, and they are the same event seen from either end.

## Finding 3: most of it is the estimator, not the market

This is the control doing its job, and it overturned the mechanism I predicted.

The Deriv generated feeds have **constant volatility by construction**, so they
cannot have volatility mean reversion - and they show **+0.43 of the +0.61
spread.** About 70% of the conditional bias on a real feed is therefore
regression in the volatility *estimate*: a high short-window estimate is partly
high true volatility and partly noise, the noise does not persist, and barriers
sized from it are too wide for what follows.

Sweeping a geometric shrinkage weight `w` on the entry estimate -
`sigma_used = sigma_entry^w * sigma_long^(1-w)`, with `w = 1` being production:

| `w` | traded spread | generated spread |
| ---: | ---: | ---: |
| **1.0** (production) | **+0.61** | **+0.43** |
| 0.7 | +0.30 | +0.31 |
| **0.5** | **+0.08** | +0.22 |
| 0.3 | -0.14 | +0.13 |
| **0.0** | -0.48 | **+0.01** |

**The generated feeds flatten to +0.01 at `w = 0`** - full shrinkage removes
their spread *entirely*, because their short estimate carries no information
about future volatility and never did. **Traded feeds flatten at `w ~ 0.5` and
over-correct to -0.48 at zero**, so about half of a real feed's short-estimate
deviation is real and half is noise.

So the remedy is **shrinking the estimate, not forecasting it** - which is a
negative result for the state-space approach on this question and the right
answer. A `Q` model would address the ~30% that is genuine volatility
dynamics; the other ~70% needs two numbers and one exponent.

## Finding 4: the correction is derived, not fitted, and it checks out

Barriers sit at `k * sigma_entry` in absolute terms, so in units of the
*realised* volatility they sit at `k * sigma_entry / sigma_realised`, and
`(a+B)(b+B)` scales as `(sigma_entry/sigma_realised)^2`. With
`sigma_realised = sigma_entry^w * sigma_long^(1-w)`:

    correction = (sigma_entry / sigma_long) ** (2 * (1 - w))

so the exponent is **1.0 at the measured `w = 0.5`** on traded feeds and
**2.0 at `w = 0`** on generated ones. Both were predicted before being
checked, and both quintile profiles are normalised to the middle bucket so
only the shape is under test:

| | `sigma_e/mean` | observed | **exp 1.0** | **exp 2.0** |
| --- | ---: | ---: | ---: | ---: |
| traded, lowest | 0.723 | 0.766 | **0.723** | 0.523 |
| traded, highest | 1.442 | 1.315 | **1.442** | 2.079 |
| generated, lowest | 0.874 | 0.772 | 0.874 | **0.763** |
| generated, highest | 1.128 | 1.215 | 1.128 | **1.273** |

**Traded matches exponent 1.0 and generated matches 2.0**, each badly missed by
the other's. The traded profile is slightly *flatter* than exponent 1.0 at the
extremes, and the reason is the next section.

`trading/barriers.conditional_slowdown(sigma_entry, sigma_long, generated=)`
now implements it, with the derivation in its docstring and the exponents
asserted as exact powers rather than inequalities - a fitted drift away from
1.0 and 2.0 would mean the derivation had stopped applying.

## What this measurement gets wrong, stated rather than left

**The vertical barrier truncates the durations.** A trade that times out is
recorded at the cap rather than at its true length, so every `ratio` here is
an **underestimate**, and more so where time-outs are frequent - 20% in the
highest quintile against 3% in the lowest. So:

* the *level* is not comparable to `SLOWER_ON_FEED` (measured 1.09 against the
  table's 1.26 for this geometry mix) and no claim is made that the table is
  wrong;
* the *spread* of +0.61 is a **floor**, since truncation pulls the high
  quintile down hardest;
* and that is why arm 5's observed profile is flatter than exponent 1.0 at the
  top while the shrinkage sweep puts `w` just under 0.5. The two agree once
  truncation is accounted for.

## What landed, and what deliberately did not

`conditional_slowdown` is a **helper, and changes no live number.** A test
asserts `duration_on_feed` does not call it: that function is what
`trading/models.py` uses for `needs`, so switching it changes how long the desk
expects to hold a position, which is a decision to take deliberately rather
than a side effect of adding a function.

What it would take to switch it on: a `sigma_long` at the call site - the
callers in `trading/models.py` and `structures/vol/projection.py` currently
pass only barrier units - and a decision about whether `GENERATED` feeds take
the exponent-2 branch, which `barriers.GENERATED` can already identify.

`probability` needs nothing, by Finding 1.
