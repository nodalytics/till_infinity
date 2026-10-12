# The Landau cubic: the trend has no double well

Schmidhuber's lattice-gas renormalisation-group model of a market gives the
trend a Landau free energy whose derivative is the drift on returns:

```
V(phi) = b~ phi^2 / 2 - c~ phi^4 / 4 + ...   =>   R(t+T) = a + b phi(t) + c phi(t)^3 + eps
```

**It was worth testing because it is the only claim in the reading pile quoted
with error bars**: daily `b = 1.29% +/- 0.43%`, `c = -0.62% +/- 0.23%`, and
intraday (>= 1h) `b = +0.132% +/- 0.046%`, `c = -0.039% +/- 0.014%`. Almost
nothing else there quotes an uncertainty, so this one can be *replicated*
rather than merely re-found - and a replication can fail in a way that is
informative, which a re-finding cannot.

Its state-space form is a member the library did not have: a reverting rate
with a **cubic** restoring force. That member is now
`statespace/landau.py`, the harness is `research/ideas/landau_cubic.py`.

## Four predictions, written before the harness ran

1. **Signs.** `b > 0` and `c < 0`: the origin repels, the cubic stabilises.
2. **A scale ladder.** The paper's own table says `c -> 0` below ~30 minutes
   and `c < 0` from ~1 hour out, so `|c|` should grow with scale.
3. **A bimodal trend.** `b > 0 > c` puts stable drifts at `+/- sqrt(b/-c)` and
   makes zero *unstable*, so the trend's own distribution should have a
   **trough at zero**. From the daily coefficients the modes sit at `+/- 1.44`
   standardised units. This needs no filter and no likelihood.
4. **A tradeable size.** At `phi = 2` the daily coefficients predict
   `1.29*2 - 0.62*8 = -2.38%` over the next day.

Numbered because the answers differ: one of them half-survives and three fail.

## Prediction 1, the sign: a real but tiny excess

Across 37 real cells (ten FX pairs, two metals, two crypto; 1d; lookbacks 5,
20 and 60 bars; non-overlapping windows), **six have `c < 0` at `|t| > 2`**:

| | back | real `c` | `t` | flat-shuffled `t` | **block-shuffled `t`** |
| --- | ---: | ---: | ---: | ---: | ---: |
| BTCUSD | 20 | -0.307 | **-4.89** | +0.04 | **-0.15** |
| XAGUSD | 20 | -0.076 | **-4.76** | +0.07 | **-1.11** |
| XAUUSD | 20 | -0.074 | **-2.71** | -0.61 | **-1.32** |
| USDCHF | 20 | -0.052 | **-2.53** | +1.04 | **-1.02** |
| EURUSD | 5 | -0.012 | **-2.25** | -1.49 | **-0.79** |
| USDCHF | 60 | -0.309 | **-2.02** | -0.93 | **+0.22** |

Three more cells exceed `+2` with the *wrong* sign (EURJPY 60, GBPJPY 20 and
60), so nine of 37 are beyond `|2|` against the ~1.9 chance expects. The same
37 cells give **one** such cell under a flat shuffle and **three** under a
block shuffle - both consistent with chance.

So there is an excess of significant cubic coefficients in real data, it is
predominantly negative, and **every significant cell's block-shuffled twin is
null.** The block shuffle reorders 20-bar blocks: it keeps volatility
clustering and destroys the long-range ordering. That the signal dies with the
ordering and not with the clustering is the one piece of this claim that
behaves the way the claim says it should.

**Why the block shuffle is the null that counts.** A flat shuffle destroys
clustering too, so a fat-tailed clustered series compared against an i.i.d.
one differs in two ways at once and a surviving coefficient says nothing about
which. Blocks hold the clustering fixed. Of the two nulls only the second can
isolate ordering, and it is also the weaker-looking one - it leaves three
cells past `|2|` where the flat shuffle leaves one.

The generated markets are null here (`Volatility_75` at back 20, `t = -0.16`;
`Volatility_25`, `t = -1.17`), but they carry about **half the windows** of the
metals and crypto cells - 119 against 221 - so their `t` values are deflated
by roughly 1.36. Correcting for it moves them to -0.22 and -1.59, still null,
so the asymmetry does not rescue the control; it does mean the real-against-
generated contrast here is weaker than the table makes it look, and is stated
rather than left to be discovered.

## Prediction 2, the scale ladder: no

| | 3m | 15m | 1h | 4h | 1d |
| --- | ---: | ---: | ---: | ---: | ---: |
| real, median `c` | +0.000 | +0.000 | +0.000 | -0.000 | -0.000 |
| real, share `c < 0` | 0.42 | **0.23** | 0.47 | **0.65** | 0.51 |
| generated, share `c < 0` | 0.48 | 0.48 | 0.58 | 0.55 | 0.59 |

The predicted ladder is `c -> 0` below 30 minutes, then `c < 0`. Observed, the
*lowest* share is at 15m - where `c` is mostly **positive** - and the highest
at 4h, with 1h and 1d in between and 3m below both. There is no order in it,
and the generated markets' shares sit in the same range. A claim that holds at
one scale after being fitted at one scale is not a ladder.

## Prediction 3, the bimodal trend: no, decisively

This is the prediction worth the most, because it needs no model. The ratio of
the trend's density at zero to its density at `+/- 1 sigma`:

| | real | generated | a Gaussian | **a double well needs** |
| --- | ---: | ---: | ---: | ---: |
| 3m | 3.64 | 1.74 | 1.65 | **< 1** |
| 1h | 3.26 | 1.68 | 1.65 | **< 1** |
| 4h | 2.54 | 1.76 | 1.65 | **< 1** |
| 1d | 2.46 | 1.93 | 1.65 | **< 1** |

Real markets' trends are **two to three times more concentrated at zero than a
Gaussian's**, where the claim requires a trough. Not a near miss in the wrong
direction - the opposite shape. The excess over the Gaussian is leptokurtosis:
the flat-shuffled series, which keeps the marginal exactly, gives 1.9 to 2.4,
so it is the distribution and not the ordering.

The one anomaly in the first run was instructive. USDJPY at lookback 5 reported
a trough of **49.31** and standard errors of 0.000. The cache carries EURUSD,
USDJPY and USDCHF daily back to **1971**, when the price was administered -
11.6% of USDJPY's 1970s daily returns are *exactly* zero. A series that spans a
change in how the price is set is two series. The harness now starts at
1973-03-01. Cutting it barely moved the medians, so the headline was never
peg-driven, but the 49.31 was entirely peg.

## Prediction 4, the tradeable size, and the unit problem

`b` and `c` are **not scale-free**, and the published numbers cannot be
compared to anything without the horizon. BTCUSD at 1d:

| back | `b` | `c` | predicted return at `phi = 2` |
| ---: | ---: | ---: | ---: |
| 1 | +0.205 | -0.006 | +0.36% |
| 5 | +1.284 | -0.072 | +2.00% |
| 20 | +4.262 | -0.307 | +6.07% |
| 60 | +13.830 | -3.045 | +3.30% |

`R` is a sum over the window, so both coefficients grow with it - roughly
linearly. The paper reports `b = 1.29` "at daily scales" and pins no horizon.
At a one-day horizon the best real estimate is `c = -0.006`; the published
`-0.62` is about a hundredfold larger. **The sign replicates and the magnitude
does not, by two orders of magnitude.**

## The sharpest test is the filter, and it is flat

The regression fights two collinear regressors - `phi` and `phi^3` correlate
about 0.77 - so the harness reads `c` off an orthogonalised cubic
`psi = phi^3 - gamma phi`, where the coefficient on `psi` *is* `c` with no
collinearity in it and `b = beta_phi - gamma c` recovers the published
parametrisation. Even so, the cleaner test is the nested one: `Landau` with
`kappa` free against `Reverting`, which is the same model at `kappa = 0`.

**The member can find a well that is there.** On a planted series with
`theta = -0.6, kappa = 0.4` - wells at `+/- 1.225` - it recovers wells at
`+/- 1.0` with no parameter on a grid edge and beats `Reverting` by **+193.8
nats** held out.

**On 24 real and generated cells it finds nothing.**

| | cells | fitted `theta` | fitted `kappa` | wells | median gain |
| --- | ---: | --- | --- | --- | ---: |
| real, 4h and 1d | 24 | **+0.25 to +4.0, always positive** | 0 on 17 of 24 | **none, 24 of 24** | **+0.0** |
| best cell | | | 50 (grid edge) | none | +2.9 |
| `Volatility_75`, `Drift_Switch` | 6 | positive | 0 or 50 | none | +0.1 |

Gains of 0 to 2.9 nats over ~3,000 scored observations, with the non-zero ones
sitting on the grid edge, and the known-generator controls producing the same.

**And the filter explains the regression.** `theta` positive on every cell
means a drift half-life of 0.17 to 2.8 hours on 4h and 1d bars - the latent
trend does not survive one bar. There is no persistent `phi` for a quartic
potential to act on, which is why a cubic term has nothing to add: **the
linear term has already said the trend is noise.** That is the same wall as
the fitted jerk landing on its floor and every member degenerating toward the
random walk, reached by a third route.

The two arms are not in conflict, they measure different things. The regression
asks whether a *chosen* 20-day realised trend predicts the next 20 days; the
filter asks about the *latent* drift with no lookback chosen at all. Only the
second is free of an arbitrary window, and it is the one that is flat.

## Two bugs worth keeping

**The first arm-2 run had `Landau` winning by three thousand nats on every
instrument** with `theta = -1.2, kappa = 0` - an explosive model whose
covariance reaches infinity within a few hundred bars. Its held-out likelihood
came back as exactly `0.0`: it had scored **nothing**, and nothing beat
`Reverting`'s honest `-3346`.

That is the identical defect `reverting.py`'s own docstring records from its
first comparison - *a likelihood over fewer observations is not a smaller
number, it is a different quantity.* Having the warning written down in the
package did not stop it being rewritten, so `score` now returns the count and
`best` discards any cell that scored fewer observations than the winner. The
guard belongs in the code, not the prose.

**The travel integral was Simpson's rule at four panels** while the docstring
claimed it converged to 1e-9. It landed 2e-3 from the answer. `int r dt`
turned out to have a closed form - `w = e^{a t}` reduces it to
`int dw / (w sqrt(A w + B))` - so the member now has no quadrature in it at
all, costs four transcendentals a step instead of nine, and lands 4e-12 from a
40,000-panel reference.

## What the member is still worth

It stays, for three reasons that do not depend on this claim.

- **It is the only non-linear member, and its mean is exact.** `kappa = 0`
  reduces to `Reverting` bit for bit, so anything that scores against
  `Reverting` can score against it for one extra parameter.
- **`wells` is a falsifiable property** rather than a fitted number, and a
  member that makes a checkable claim about data is worth more than one that
  only improves a likelihood.
- **The planted arm is a reusable control.** A cubic potential with known
  wells is a hard target that the fitting machinery demonstrably hits, which
  makes it a test instrument for anything that claims to find regime structure
  in a drift.

What it is *not* is evidence for a double well in any market measured here.
