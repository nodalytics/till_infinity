# The hedge ratio as a state, BTC with real volume, and what is still missing

2026-10-11. Three things: an architecture question answered by building the
thing that was missing, a volume measurement whose first answer was my own bug,
and an honest inventory of what remains.

## 1. Could statespace do statistical arbitrage? Not until today

`subjects.py` has said since the package began that statistical arbitrage is
not a second system here - *"level becomes relationship, distance becomes
deviation, and **the slope becomes a drifting hedge ratio**"*. Nothing
implemented the last clause.

Every member's `update(measured: float, ...)` takes a **scalar**, so the only
way to use one on a pair was to compute the spread elsewhere, at a hedge ratio
chosen elsewhere and held fixed, and hand in the residual. That is the thesis
with its hardest part done by hand - and a fixed hedge ratio is the assumption
that ends a pairs trade.

**The gap was one parameter wide.** A pair does not need a vector observation:

    y_t = w0_t + w1_t x1_t + ... + wn_t xn_t + e_t

is **one** scalar observation whose *observation row* carries the other legs,
`H_t = [1, x1, ..., xn]`. The weights become states, estimated jointly with
their covariance, and the spread is the innovation. The only thing the existing
members could not do is let `H` change per reading - `Gaussian` hardcodes
`[1, 0, 0]`. `relating.py` is that member.

Measured on a pair whose true hedge ratio drifts from 1.0 to 2.0 over 3,000
bars:

| | final ratio | mean abs error after warm-up |
|---|---|---|
| true | 2.000 | |
| **`Relating`** | **1.998** | **0.0036** |
| static least squares | 0.566 | 1.0171 |

A basket is the same recursion in a loop, so `legs=3` recovers
`0.924, -0.434, 1.338` against a true `0.8, -0.5, 1.3`, and a pair is the
`legs=1` case rather than a separate class.

### What it still cannot do, stated plainly

* **It is a regression, not a joint model.** One leg explained by the others,
  which is the right shape for a *hedge*. A joint model of all legs needs a
  genuinely vector observation and an `n`-square measurement noise, and that is
  what **cross-impact** requires - Lillo measures the response of asset `j` to
  an order on asset `i` as non-zero and about five times smaller than the
  self-response. A hedge does not need it; a cross-impact study does.
* **The stated weight uncertainty is optimistic in levels, measurably.** On a
  collinear basket of random walks the filter recovers the weights well and
  reports standard deviations of **0.004 against errors of 0.12** - thirty
  times too confident. That is the recursion correctly propagating an
  assumption the data violates: a levels regression on near-collinear random
  walks has autocorrelated residuals, and the filter believes they are white.
  The remedies are the caller's - regress returns, or check the innovations
  with the Ljung-Box already in `diagnostics.py` - and a test pins the
  limitation so nobody quotes `ratio_sd` from a levels fit without meeting it.
* **It does not choose the basket**, test for cointegration, or pick which leg
  is dependent - and `y on x` and `x on y` give different ratios.

And the desk's own prior remains discouraging: the relationship trade has been
measured here at a gross Sharpe of **+0.27** and a net of **-0.97**. The bar is
not "does the spread revert" but "does it revert past two spreads and a
financing cost".

## 2. BTC with real volume

Every FX and synthetic feed reports a "volume" that is a **tick count**, not
traded size. BTCUSD carries 50,000 hourly bars with real volume on every one,
so it is the only instrument here where a volume feature means what it says.

Three features, all scale-free: log volume against its own trailing mean,
**signed flow** (volume carrying the bar's sign - the closest a bar feed gets
to order flow, and Lillo's review says the *sign* of order flow is the
long-memory process), and Amihud illiquidity.

Per-instrument rank correlation against realised magnitude, 1h bars, 4h ahead:

| | without volume | **with volume** | trailing sd |
|---|---|---|---|
| **btcusd** | +0.209 | **+0.241** | +0.189 |
| gbpusd | +0.191 | **+0.226** | +0.185 |
| xauusd | +0.221 | +0.228 | +0.242 |
| usdjpy | +0.273 | +0.272 | +0.230 |
| eurusd | +0.187 | +0.171 | +0.138 |
| v75 | -0.039 | -0.004 | +0.102 |

**BTC gains the most, which is the result that makes sense**: real traded size
adds more than a tick count does. The gain is modest - 15% of a small number -
and it does not change the verdict count against the trailing standard
deviation, which per-instrument beats on four of six either way.

**And BTC transfers.** With the feature sets matched at twelve columns, a
ranker trained on FX, gold and the synthetics - having **never seen crypto** -
scores **+0.123** on BTC. Lower than the +0.209 from training on BTC itself,
and clearly not zero. The transferability claim survives a change of asset
class, which is a stronger test than the one it was built on.

### The first answer was my own bug, again

The first run with volume made **every instrument worse** - eurusd's
per-instrument score fell from +0.187 to +0.064, usdjpy's from +0.273 to
+0.154 - and the obvious reading was that the volume columns are noise that
dilutes a linear ranker's weights.

Two defects, both mine. **Amihud divided by `log(volume)`** rather than by
volume, and a logarithm is near zero whenever volume is near one, so the
feature had no bounded scale and an SGD ranker cannot survive a column like
that. And **log volume was centred on the mean of the whole series**, test
period included - a constant rather than a leak of any particular outcome, but
the `Ranker` has no intercept, so a constant offset in a feature is a free
parameter it can use, and it was computed from data the model may not see.

Fixed - Amihud on traded size, then logged; a trailing mean rather than a
global one - and the sign of the result reverses. Had I reported the first
run, the finding would have been "volume does not help", with a table behind
it.

## 3. What is still not implemented

Checked against the code on 2026-10-11, not against the prose.

**Done today:** `B` is wired - `Gaussian.predict(when, control=...)` applies
`x <- x + B u dt`, with `drive` defaulting to zeros so every existing
measurement is untouched. `relating.py` exists. That closes the two halves of
one unfinished idea: `__init__.py` has written `x' = F x + B u` since the
package began with no member implementing it, while `inputs.py` grew an
exogenous channel nothing consumed.

**Still open, in the order I would take them:**

1. **EM.** The oldest item on the README's own priority list. The E-step *is*
   the smoothed posterior, the smoother has been written and verified since,
   so the blocker is gone and the work is not done. `diagnostics.fit_jerk`
   still searches one parameter where EM would fit `jerk` and `R` together with
   a closed-form M-step.
2. **A member that consumes the input channel through `Q` rather than `B`.**
   `B u` is a *mean* term, and the inputs named for I8 - hour-of-day share,
   activity - modulate **volatility**, which is `Q`. Wiring them through `B`
   would be putting a variance effect in a mean term. `yielding.py` is the
   pattern (scale a named lever by a signal); what is missing is the arm driven
   by an exogenous input rather than by its own detector, and the harness that
   says which door the channel actually helps through.
3. **Subject composition.** `Subject.filter()` still ends `return Gaussian(...)`,
   hardcoded, so no subject can ask for the member with evidence behind it -
   and `RELATION` now has one it could ask for.
4. **A long-memory kernel member.** Every member decays exponentially because
   that is what a Markovian state does, and an exponential kernel cannot
   produce the long memory the data has. The standard state-space remedy is a
   sum of geometrically spaced exponential modes approximating a power law,
   which is what the S4/HiPPO lineage in this package's reading list exists
   for. Null: beat the exponential member on held-out likelihood.
5. ~~**The spread as a subject.**~~ **Done, and the answer is no.**
   `statespace-spread.md` filtered the quoted spread on tick data: its
   hour-of-day profile is 1.02x to 1.09x peak to trough where volatility's is
   2.7x to 3.7x, a five-observation trailing mean beats the filter on the one
   instrument whose spread moves at all, and the constant gate every harness
   uses is wrong by under 8%. So no cost-gated conclusion here changes, which
   supports them rather than undermining them. The hard null held.
6. **A balance/imbalance two-state member**, which is auction market theory
   stated as a switching model and is also I9. Its 70% claims need the matched
   control that already killed "price is a magnet".

**And three debts that are not features:** every measurement since the start
has been on bar closes rather than touches, which item 4 of the README's list
explicitly warns about; `paths.simulate` is used for parameter recovery and
nothing else, when it could separate "the model cannot find the ordering" from
"the market has no ordering"; and `Paired`'s threshold is still uncalibrated
against a stationary stream, which `focus.py` names as the right measurement
and skips.

---

## The panel: the vector observation, built

Added 2026-10-11, after the limit above was named. `relating.Relating` puts the
other legs in the observation **row**, which is a regression - one leg
explained by the others - and cannot hold a matrix. `panel.Panel` is the member
with a genuinely vector observation: `n` readings at a time, an `n + 1` state,
and the cross terms kept.

### A factor plus reverting idiosyncratics, and why the first version failed

The first build was `n` correlated random walks. It did not work, for the
reason that is obvious afterwards: **a random walk absorbs a dislocation**.
Instrument 2 was given a persistent 2.0 shift halfway through a 3,000-bar
fixture and its mean absolute residual afterwards was 1.31 - against 1.31 and
1.34 for the two that had not moved. Nothing separated, because a free walk has
no level to be away from.

The model that works is the classical one:

    value_i(t) = factor(t) + idio_i(t)
    factor  random-walks      - what they share
    idio_i  reverts           - what makes a deviation temporary

and the reversion is what makes `idio_i` a spread rather than a second walk.
`theta` is a half-life in hours, which is the number a pairs desk actually
wants: how long a dislocation takes to close.

**Reverting to zero was the second mistake.** Instruments sit at permanent
different levels, those offsets land in the idiosyncratics at initialisation,
and a target of zero makes the filter fight them every step - z-scores of
**610, 105 and 505** when the only dislocation was 2.0. Each idiosyncratic
reverts to its own anchor now, fixed at the first reading. Same shape as
`Relating`'s centring: a quantity that reverts has to revert to where it lives.

### The property that makes it a panel rather than a pair

A factor model has to decide how much of a one-instrument shift was the factor,
and the contamination is about `1/n`. So separation is a function of **width**:

| instruments | dislocated \|z\| | others | ratio |
|---|---|---|---|
| 3 | 22.0 | 11.0 | **2.0x** |
| 8 | 22.2 | 3.6 | **6.2x** |
| 16 | 25.8 | 2.5 | **10.3x** |

**A pair cannot tell a dislocation from a factor move.** That is not a defect
of the implementation; it is what two observations of one factor can support,
and it is the strongest argument for a panel over a pair that this desk has.

### What it enables and what it still does not

It enables cross-impact, which needs the matrix a regression cannot hold -
`Panel.correlation(i, j)` is the estimated correlation of two latent values,
in both directions. It does not fit `theta`, the factor wander or the
idiosyncratic wander; `diagnostics.fit_both` is the pattern and this does not
use it. And it is one factor, not several: a panel spanning genuinely
different asset classes wants more, which is a `k`-factor generalisation of
the same recursion.

---

## Choosing the basket, which was the second limit

`relating.Relating` does not pick its own legs. The obvious remedy - fit every
candidate and keep the best - is also the oldest way to manufacture a result,
so the question measured was not *which basket wins* but **does the winner keep
winning**. Harness: `research/ideas/basket_choice.py`.

Three arms. **chosen**: best training likelihood, scored on held-out data.
**random**: a basket of the same size drawn blind, same held-out data.
**oracle**: best on the held-out data, which nobody could pick. The oracle is
there because `random` alone cannot tell "selection does not work" from "no
basket works".

Six instruments on a 1h clock, baskets of one, two and three legs:

| legs | candidates | captured |
|---|---|---|
| 1 | 5 | **100%** |
| 2 | 10 | **100%** |
| 3 | 10 | **100%** |

**The basket chosen on the training period is the one that wins on the test
period, every time.** Selection generalises completely here, and the gap it
captures is real: a blind basket loses 100 to 150 nats against the chosen one
on a base of about 15,000.

### Why this result needs its caveat more than most

Uniformity is bug shape #10 in the `finding-bugs` skill - *the result that is
too good* - and 100% in every cell of every width is exactly that shape. Here
the mechanism is visible and benign: with five to ten candidates the ranking
by likelihood is stable between periods because it is driven by which
instrument is genuinely most related, and that does not change in half a
sample.

**Selection bias is a function of the candidate count**, and this tested five
to ten. A desk screening hundreds of pairs is in a different regime, and this
measurement says nothing about it. Two cells read `nan` because the random
draw happened to *be* the oracle, which is itself a reminder of how small the
surface is.

So: choosing works at this width, and the experiment that matters next is the
same one with a hundred candidates, where the maximum of a pile of noise
starts to look like skill.
