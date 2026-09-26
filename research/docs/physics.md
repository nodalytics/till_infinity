# Price as a particle, with physics instead of the metaphor: fat tails and a spring, no direction

Measured 2026-09-26 on the lab with [`physics.py`](../harness/physics.py): 20 real instruments
(15 FX pairs, XAU, XAG, BTC, ETH, SOL) and four exact random walks from the Deriv synthetics as
the control, at 15m, 1h, 4h and 1d, and across timeframes.

Rules throughout:
- fit on each series' first 60% by time, scored on the last 40%;
- one bar of latency;
- non-overlapping trades, net of spread;
- both halves of the test period reported;
- a null that shifts every series' positions by one common offset.

Asked for after [`zone-fill.md`](zone-fill.md): the method there was described in quantum terms,
so this does the physics properly. Three standard tools, each a model that can be fitted and
tested rather than an analogy.

## 1. Langevin / Fokker-Planck: measure the force field

Model the log-price as a particle, dx = D1(s) dt + sqrt(2 D2(s)) dW, and estimate the drift
D1 - the force - directly from data (Kramers-Moyal), as a function of the particle's state s:
- displacement from equilibrium (the EMA50);
- directional efficiency;
- position inside the 50-bar range - the zone idea.

Only drift can pay ([`barrier-geometry-is-irrelevant.md`](barrier-geometry-is-irrelevant.md)).

**The force field does not persist.** The drift profile across ten state deciles, measured on the
training block, correlates with the test block's anywhere from -0.59 to +0.68 - positive at a
one-hour hold, flipping sign at four hours, near zero on daily. Trading its sign, only in deciles
whose training drift is two standard errors from zero, real markets, net in baseline moves:

| interval | displacement | efficiency | range position |
| --- | --- | --- | --- |
| 15m | -0.36 / -0.51 | -0.38 / -0.44 | -0.37 / -0.74 |
| 1h | -0.18 | -0.17 | -0.17 |
| 4h | -0.10 / -0.10 | -0.09 / -0.07 | -0.11 / +0.03 |
| 1d | -0.08 / -0.18 | -0.14 / -0.17 | -0.10 / +0.26 (z +0.7) |

(short hold / long hold; the shifted-null z is within +-2.3 in every real cell)

**There is one real force, and it is a spring.** A linear Ornstein-Uhlenbeck fit of the next
bar's move on displacement:
- **FX is mean-reverting within a bar**: slope -0.015 to -0.028, t -4.2 to -8.5, on both the
  training and the test block at 15m and 1h. At 4h it is -0.018 (t -4.4) on test but only
  -0.006 (t -1.6) on training. That consistency across blocks at 15m and 1h is what a real
  effect looks like.
- **Crypto is the opposite**: momentum, with a positive slope at t +1.3 to +5.1.
- **The control is flat**, at t below 1.4.

The spring is too weak to trade: it is the very structure the displacement trades above capture,
and they lose, because a pull of 1.5-2.8% of a bar's move per unit of displacement is smaller
than the spread.

## 2. The quantum harmonic oscillator: a fat-tail model, and not the best one

Quantum finance models the return density as a mixture of squared oscillator eigenfunctions,
|psi_n|^2. It was fitted to returns standardised by an EWMA sigma and scored on out-of-sample
log-likelihood per bar:

| | Gaussian | **Student-t** | QHO (best of 1, 3, 5 states) |
| --- | ---: | ---: | ---: |
| real, 15m | -1.483 | **-1.372** | -1.442 |
| real, 1h | -1.483 | **-1.367** | -1.437 |
| real, 4h | -1.474 | **-1.368** | -1.428 |
| real, 1d | -1.453 | **-1.399** | -1.424 |
| control, 1h | -1.4358 | -1.4355 | -1.4355 |

The oscillator beats a Gaussian and loses to a Student-t at every interval and in every family.
Its best fit is about **97% ground state - which is exactly a Gaussian - plus 3% of the fourth
excited state** to fatten the tails. On the random walks all three tie, as they must. It is a
density model: it says how fat the tails are and nothing about which way.

## 3. Collapsing the wave function: Bayesian filtering of the drift

A latent drift that wanders, observed through each bar's return. A particle filter tracks the
posterior cloud over it; in this linear-Gaussian model its exact limit is the Kalman filter,
which is what was run. Trade the sign of the posterior drift when it is in its top 20% of
confidence.

| interval | real, net per trade (short / long hold) | z |
| --- | --- | --- |
| 15m | -0.38 / -0.29 | +0.1 / +0.6 |
| 1h | -0.22 / -0.34 | -1.1 / -1.0 |
| 4h | -0.08 / -0.09 | +0.7 / -0.1 |
| 1d | +0.04 / +0.27 | +0.7 / +0.6 |

The noise level was chosen on training, where the best information coefficient was -0.011 to
+0.057. After the "collapse" there is nothing to collapse onto.

## Across timeframes

Each higher timeframe's state, taken from its last *completed* bar, joined onto every
lower-timeframe decision:
- a joint force field on a 3x3 grid of lower-timeframe against higher-timeframe state (1h against
  4h and daily; 15m against 1h and 4h);
- a rule that trades only when the posterior drift agrees in sign on every timeframe.

**All negative for real markets**: 1h joint fields -0.04 to -0.31, 15m -0.38 to -0.50, agreement
rules -0.10 to -0.44, z between -1.3 and +2.5 across 32 rule-and-hold cells. The few positive cells are metals
(+0.07 to +0.23 at 1h), in a test period when gold trended up, and they do not clear the
shifted null.

## What this settles

The physics tools each found what physics would predict for a market like this:
- a restoring force too weak to pay for its own spread;
- fat tails better described by a Student-t than by an oscillator;
- a drift field that moves from one period to the next.

None of them gives a direction. That is the same wall the barrier theorem describes: the only
term that pays is drift, and drift is what none of these can estimate reliably from price.
