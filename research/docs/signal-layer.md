# Signal = w1*Trend + w2*Momentum + w3*Volatility + w_regime*Regime, measured

**Measured 2026-10-15.** Code: [`signal_layer.py`](../ideas/signal_layer.py).
318,440 rows per cell, 15m and 1h, horizons 3 and 12 bars.

Asked for as statespace's final layer, with the note that most of its terms are
already measured here, that Trend should be tested as slopes and EMAs of slopes,
and that **level return rates** and **tick-volume velocity** should go in beside
them. Then: *it looks like the basic formula for a perceptron?*

**It is one** - `sum(w_i * x_i)` is a perceptron's pre-activation - and that
framing produced three testable predictions. All three were tested and two of
them held.

## The two nulls, because one is not enough

Every arm is scored against two rebuilds of each series:

* **`blocks`** reorders 96-bar runs of returns, leaving `volume` in place. It
  breaks the volume-to-price link and nothing else, so it is the right null for
  the tick terms - and the **wrong** one for the price-only volatility terms,
  because volatility clustering survives inside a 96-bar block. It reproduces
  `vol ratio`'s magnitude AUC to four decimals: 0.5711 against the real 0.5718.
* **`iid`** reorders single returns and destroys the clustering too. Across all
  128 arm-by-cell readings it lands between **0.4937 and 0.5050**, which is what
  a null has to look like before anything is read off it.

`edge` below is the real figure minus the **higher** of the two, so a term has
to beat the best available explanation rather than the most flattering one.

## Direction: a coin, and the formula is the wrong shape to find it

Edge on the direction of the forward return:

| arm | 15m h=3 | 15m h=12 | 1h h=3 | 1h h=12 |
|---|---:|---:|---:|---:|
| hand-tuned, additive | +0.0001 | +0.0003 | −0.0052 | −0.0065 |
| hand-tuned, gated | −0.0033 | −0.0012 | −0.0061 | −0.0068 |
| fitted linear | +0.0017 | −0.0016 | +0.0042 | +0.0029 |
| fitted + regime gates | +0.0024 | −0.0012 | +0.0037 | +0.0069 |
| **boosted ceiling** | **+0.0118** | **+0.0087** | **+0.0105** | **+0.0134** |

The formula as written carries nothing, which agrees with everything this desk
has measured about direction. The **nonlinear** arm is the exception: +0.0087 to
+0.0134 on all four cells, and at 318,000 rows an AUC standard error is about
0.001, so that is ten standard errors and consistent in sign everywhere.

**That is the perceptron limitation showing up with a real effect behind it.** A
hyperplane cannot see what a tree ensemble can, the linear arms read +0.002 to
+0.007 against the boosted +0.012, and no choice of weights closes that gap -
the form is the constraint, not the weights. It is also economically nothing:
+0.012 of AUC on a direction is far inside the spread, and
`direction-is-closed-not-just-null` already prices that at 2% of one.

**Scope of the null.** Planting positive autocorrelation in the returns, the
test finds an AR(1) of **0.30** - fitted goes 0.5171 to 0.5515, boosted 0.5212
to 0.5446 - and misses 0.15. So this excludes strong momentum and not weak
momentum, which is a narrower statement than "direction is a coin".

The first version of this power arm added `choice(-1, 1) * drift` and cumulated
it. That is a random **walk**, not a drift: it adds noise nothing can predict,
and the curve read 0.5135, 0.5135, 0.5132, 0.5131 across planted strengths from
0 to 0.10. A flat power curve is not evidence of a null, it is evidence of no
test.

## Magnitude: the two terms that were asked for are the two that work

Edge on whether the forward move exceeds its median size:

| arm | 15m h=3 | 15m h=12 | 1h h=3 | 1h h=12 |
|---|---:|---:|---:|---:|
| **tick z** | **+0.1017** | **+0.0796** | **+0.0667** | +0.0012 |
| **tick velocity** | **+0.0256** | **+0.0289** | **+0.0551** | **+0.0325** |
| vol ratio / regime | +0.0006 | +0.0024 | −0.0210 | −0.0374 |
| range ratio | −0.0274 | −0.0226 | −0.0184 | −0.0099 |
| level recency | −0.0295 | −0.0339 | −0.0264 | −0.0231 |
| hand-tuned, additive | +0.0192 | +0.0140 | +0.0046 | −0.0236 |
| hand-tuned, gated | +0.0196 | +0.0151 | +0.0115 | −0.0085 |
| fitted linear | +0.0017 | +0.0069 | +0.0062 | −0.0155 |
| boosted ceiling | −0.0028 | +0.0010 | +0.0174 | −0.0071 |

**Tick-volume velocity is the only term positive on every cell**, +0.026 to
+0.055. Tick-volume level is larger where it works - up to +0.102 - and dies at
1h h=12. Both were additions to the formula rather than part of it.

**The formula's own volatility term is mechanical.** `vol ratio` reads a
magnitude AUC of 0.5718 and its block null reads 0.5711: all of it is
volatility clustering that survives a block shuffle, and against the honest
floor it is +0.0006. `range ratio` is negative everywhere. So `w3 * Volatility`
contributes nothing that a reordering of the same series does not.

**The level-return term belongs on the other target.** `level recency` is
negative on all four cells here, −0.023 to −0.034. It was measured as the one
term of `strength` that orders a **return rate**
([`weight-return-rate.md`](weight-return-rate.md)); it does not order move size,
and putting it in this sum makes the sum worse.

**The negative control is clean.** On the generated feeds the tick edge is
−0.0026, +0.0005, +0.0002 and −0.0011. Deriv synthetics have no order flow
behind their tick counts, so a tick-volume-to-magnitude link should not exist
there, and it does not.

## The two things the perceptron framing predicted, and what happened

**Gating beats adding - confirmed, modestly.** `w_regime * Regime` added shifts
the score by a constant per regime; what a regime should do is say which other
terms to believe, which is multiplicative. The gated form beats the additive one
on **all four cells** for magnitude (+0.0196 vs +0.0192, +0.0151 vs +0.0140,
+0.0115 vs +0.0046, −0.0085 vs −0.0236), and the gap widens exactly where the
additive form fails worst.

**Fitting the weights makes it worse - not predicted, and the reason matters.**
Logistic regression is this perceptron with a sigmoid and a proper loss, so its
weights should be the ceiling of any hand-tuned set. On raw AUC they are: 0.6040
fitted against 0.5558 hand-tuned at 15m h=3. On **edge** they are worse, +0.0017
against +0.0192, and on three of four cells. The loss function cannot see which
features are mechanical, so it loads onto the volatility ratios - the features
with the largest in-sample AUC and the least real content - and the fitted model
spends its capacity reproducing what a block shuffle also reproduces.

That is the practical lesson of the whole exercise: **a fit maximises the
quantity you give it, and AUC against the raw series is the wrong quantity.** A
weight set chosen by hand on terms whose nulls were checked beat a weight set
fitted on terms whose nulls were not.

## What this says the layer should be

Not the formula as written. On the two targets measured:

* `Trend` - four variants, slopes and EMAs of slopes - is at or below its null
  on every cell and both targets, which reproduces
  [`slope-signals.md`](slope-signals.md) on a different window.
* `Momentum` as acceleration is within ±0.004 of its null everywhere.
* `Volatility` is mechanical once nulled against a block shuffle.
* `Regime` is worth having as a **gate** and not as a term.
* `Level return` belongs on the return-rate target, where it was measured.
* **Tick volume** - level and velocity - is the only input here with content
  beyond its null, on magnitude only, and it is the one that was not in the
  original formula.

So the honest version of a final layer is a **magnitude** layer driven by tick
volume and gated by regime, not a directional weighted sum. That is the same
shape every other finding on this desk has taken: nothing predicts sign,
everything that works is about size.
