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
5. **The spread as a subject.** Every cost gate here uses a constant, and the
   SEC paper's whole finding is that the number moves with the composition of
   the flow. Null: beat a trailing average of the spread, out of sample - a
   hard null.
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
