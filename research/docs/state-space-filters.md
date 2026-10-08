# State-space filters and the "quantum" zone method on EURUSD and Volatility 75: the quantum filter works where coherence exists, and the market shows none

Measured 2026-10-08 on the lab with [`statespace.py`](../harness/statespace.py),
[`statespace_power.py`](../harness/statespace_power.py) and
[`statespace_liquidity.py`](../harness/statespace_liquidity.py); tables from
[`statespace_report.py`](../harness/statespace_report.py). The questions are in
[`../papers/state-space.md`](../papers/state-space.md) and its research note
(`Kalman_Particle_Quantum_State_Space_Research_Note.docx`).

## Verdict

| question | answer |
|---|---|
| Can a quantum density-matrix filter find coherence when it is there? | **Yes.** On series generated with coherence it recovers the oracle at every strength (AUC 0.574 / 0.620 / 0.677 / 0.725 / 0.791, oracle the same to three decimals) and beats HMM, particle and its own decohered twin by 0.01-0.03 AUC and 20-35 mnats a bar. It does so on 2,800 bars too. On a classical regime series it ties the HMM (0.517 vs 0.520) and does not invent coherence. |
| Does it beat Kalman, HMM and particle filters on EURUSD or V75? | **No.** 96 direction cells (2 instruments x 4 timeframes x 6 filters x close-only / full candle). Every V75 cell is a coin (0.48-0.525, walks the same). On EURUSD the quantum filter is never better than the classical filters beyond noise; where it differs it is often worse (EURUSD 4h close 0.488, 1d close 0.480). |
| Does coherence carry information the classical state does not? | **Not about direction.** The fitted dephasing often leaves some coherence on EURUSD (gamma 0.01-0.11 on close-only 1h-1d), and that lifts the predictive *density* on 4h and 1d (+23 / +19 mnats a bar against the HMM's +2 / +4), but not the next bar's sign. On V75 coherence adds 0.0002-0.0006 nats a bar in training at 15m-4h (0.005 on daily) and nothing out of sample. |
| Is there anything real on EURUSD? | **A small, consistent short-term reversal**, already known. 13 of 96 cells pass Benjamini-Hochberg, all EURUSD 15m-4h, AUC 0.510-0.523 against 0.494-0.505 on the walks. The Kalman filter's fitted drift persistence is phi = -0.02 to -0.04: next-bar mean reversion, the Ornstein-Uhlenbeck spring of [`physics.md`](physics.md). Its size is 0.07-0.45 bps a bar gross (0.1-0.5 pip) and it does not survive a realistic retail spread. |
| Does using the whole candle help? | **On EURUSD 1h and 4h, yes, by about 0.01 AUC**: HMM 0.504 -> 0.513 (1h), 0.504 -> 0.516 (4h), quantum 0.488 -> 0.520 (4h). The walks gain nothing from the candle. It is the same reversal, read better: where the close sits in its bar. On V75 the candle adds nothing. |
| Multi-timeframe? | **Nothing.** Adding the higher frame's state (from closed bars only) moves lower-frame AUC by +0.0008 on average across 60 real pairs (max +0.020), against -0.0012 on 120 walk pairs (max +0.016). Trading only when both frames agree does not raise the hit rate. |
| The zone method (fill probability from speed, directional efficiency, zone size and distance; trade the most probable, ideally at 1) | **Distance, again, on both instruments at all four timeframes.** A no-fit physics formula scores AUC 0.882-0.924; the method's fitted weights add -0.002 to +0.005; the whole candle up to +0.004; the higher-frame state +0.000. Walks score the same or higher. "Certainty" (P >= 0.99) is realised 0.95-0.98 and trades at **-1.0 to -2.1R net** on real bars. Replicates [`zone-fill.md`](zone-fill.md). |
| Liquidity proxies from candles (Amihud, Corwin-Schultz, Abdi-Ranaldo, Roll, Kyle lambda, volume, range per volume; volume resting at the zone) | **They forecast risk, not direction or fills.** Next-bar shock AUC on EURUSD 0.61 -> 0.68 (15m), 0.64 -> 0.71 (1h), 0.58 -> 0.64 (4h). Direction 0.49-0.51 everywhere, zone fill at most +0.007, zone profit nothing. |
| Tail (stop one bar-sigma, no target) | **No excess.** On EURUSD real P(>= 4R) is 0.16-0.24 and P(>= 10R) 0.06-0.09 on the confident calls, against walks at 0.16-0.29 / 0.06-0.14 and 1/(N+1) = 0.200 / 0.091. V75 is the same within noise. |

## 1. The two claims, restated

**The note** proposes a ladder from Kalman (Gaussian mean and covariance) to particle (weighted
samples, non-Gaussian, multimodal) to a quantum-inspired state: a density matrix with
off-diagonal *coherence*, unitary evolution and non-commuting measurements. It asks, correctly,
that the quantum representation beat strong classical baselines out of sample. That is a
falsifiable test, and it is what was built: identical observations, an ablation that removes only
the quantum part, and positive controls where the answer is known.

**The trader's method** (quoted in the paper file) treats price as a particle whose position is
known only as a probability. It estimates a fill probability for each liquidity zone from speed,
directional efficiency, zone size and distance, and trades the most probable zone, at first only
at probability 1. With the hand weights fitted, that is a logistic first-passage model. It was
measured on 21 other series in [`zone-fill.md`](zone-fill.md); here it is repeated on the two
instruments asked for.

## 2. Data and the rules, frozen before the run

| series | bars | span | test bars (last 40%) |
|---|---:|---|---:|
| EURUSD 15m | 50,000 | 2024-09 to 2026-09 | 20,000 |
| EURUSD 1h | 50,000 | 2018-09 to 2026-09 | 20,000 |
| EURUSD 4h | 34,890 | 2005 to 2026-09 | 13,956 |
| EURUSD 1d | 6,770 | 2005 to 2026-09 | 2,708 |
| V75 15m | 50,000 | 2025-04 to 2026-09 | 20,000 |
| V75 1h | 50,000 | 2021-01 to 2026-09 | 20,000 |
| V75 4h | 16,918 | 2019-01 to 2026-09 | 6,767 |
| V75 1d | 2,820 | 2019-01 to 2026-09 | 1,128 |

The broker's bars as exported (15m and 1h with quoted spreads, 4h and 1d from the long history).
**Costs:** one round-trip spread per trade: EURUSD 0.2 pip ([`costs.md`](costs.md)), V75 its median
quoted 15m spread, 3.2 bps of price. The EURUSD figure is a raw-account spread with no commission.
That is the optimistic end, and the conclusions below do not depend on it.

**Observations.** Each bar's log return over the EWMA sigma known before it (lambda 0.94), so the
filters are asked about direction and shape, not the level of volatility. The **full-candle**
variant adds two columns: where the close sits in its own range, `(close - mid) / (high - low)`, and
the log range over sigma, both standardised on the training block. The forecast is always
P(next return > 0), and the log score is always the density of the *return*, so close-only and
candle runs are scored on the same thing.

**The filters,** each fitted on the first 60% of the series and run forward without smoothing:

| | state | fit |
|---|---|---|
| kalman | AR(1) latent drift; with candles, the close location loads on the same drift | MLE |
| hmm | 3 regimes, Gaussian emissions | Baum-Welch, forward-filtered only |
| particle | 3 regimes x stochastic volatility, Student-t returns, 1,000 particles | regimes from the HMM, SV and tail by grid on likelihood |
| qdecoh | the quantum filter with coherence destroyed each step and measured in the regime basis: exactly a classical HMM with a unistochastic transition matrix | MLE |
| qbasis | coherence kept (dephasing gamma fitted), measured in the regime basis | MLE |
| quantum | coherence kept and a rotated measurement basis: a non-commuting POVM | MLE |

The quantum filter: `rho_pred = D_gamma(U rho U^dag)` with `U = exp(-iH)`, `D_gamma` scaling the
off-diagonals by `1 - gamma`. The measurement operators `M_y = V diag(sqrt f_k(y)) V^dag` integrate
to the identity, so `p(y) = sum_k f_k(y) (V^dag rho V)_kk` is a proper density, and the update is
`rho <- M_y rho M_y^dag / p(y)`. `qdecoh -> qbasis -> quantum` adds one quantum ingredient at a
time, so any gain is attributable. 25-37 parameters against the HMM's 12-24; out-of-sample log
score charges for them.

**Walks we generate** (Deriv's V75 is a market here, not a control):
- *flip*: each real bar mirrored about the previous close with a random sign. The volatility path,
  bar shapes, gaps and volume are exactly the real ones; direction is a coin.
- *garch*: GARCH(1,1)-t at the real unconditional variance, OHLC from 8 sub-steps a bar.

**Multi-timeframe:** higher bars aggregated from the lower series (15m -> 1h, 4h; 1h -> 4h, 1d;
4h -> 1d) for real and walks alike, every filter refitted there. A higher bar's reading is joined
to a lower bar only once the higher bar has closed. Then: a logistic on both forecasts, and an
"agree" subset where the two frames call the same side.

**Scoring:** test AUC with a block-bootstrap interval (whole days resampled; a week on 1d);
Benjamini-Hochberg over all 96 real direction cells; trades always-in on the sign (cost on each
flip) and on the confident decile (threshold from training, full round trip each); the tail as
P(>= 4R), P(>= 10R) before a one-sigma stop within 100 bars, non-overlapping.

## 3. Positive controls: the test can see coherence

Before reading a single market number, the filters were run where the truth is known.

**S1, a classical 3-regime series** (sticky, drift -0.15 / 0 / +0.15 sigma). AUC / log score over a
t walk (mnats a bar) / regime accuracy:

| oracle | hmm | particle | qdecoh | qbasis | quantum |
|---|---|---|---|---|---|
| 0.520 / +7.4 / 0.651 | 0.520 / +6.7 / 0.642 | 0.519 / +5.8 / 0.629 | 0.519 / +7.1 / 0.652 | 0.517 / +7.1 / 0.652 | 0.517 / +7.1 / 0.648 |

The quantum filter ties the classical ones and does not invent an advantage.

**S2 to S6, series generated by the quantum filter itself** with full coherence, at rising regime
spacing (the power curve). AUC / log score / regime accuracy, 30,000 bars:

| spacing | oracle | hmm | particle | qdecoh | **quantum** |
|---|---|---|---|---|---|
| 0.4 | 0.574 / +34 / 0.70 | 0.546 / +12 / 0.59 | 0.545 / +11 / 0.59 | 0.545 / +12 / 0.59 | **0.574 / +34 / 0.70** |
| 0.6 | 0.620 / +62 / 0.73 | 0.594 / +33 / 0.66 | 0.593 / +32 / 0.66 | 0.594 / +33 / 0.66 | **0.620 / +62 / 0.73** |
| 0.8 | 0.677 / +107 / 0.77 | 0.654 / +74 / 0.71 | 0.654 / +74 / 0.71 | 0.655 / +74 / 0.72 | **0.677 / +106 / 0.77** |
| 1.0 | 0.725 / +164 / 0.81 | 0.708 / +130 / 0.76 | 0.708 / +129 / 0.76 | 0.708 / +129 / 0.77 | **0.725 / +163 / 0.81** |
| 1.3 | 0.791 / +259 / 0.87 | 0.782 / +229 / 0.83 | 0.781 / +227 / 0.83 | 0.782 / +228 / 0.84 | **0.791 / +258 / 0.87** |

At 2,800 bars (the length of V75 daily) the quantum filter is within 0.007 of the oracle at every
spacing (0.594 / 0.638 / 0.689 / 0.722 / 0.784). The fitted dephasing goes to gamma = 0.00 every
time.

So the machinery works. If EURUSD or V75 had coherence-like structure even at the weakest of
these strengths, the quantum filter would beat the HMM by 0.02-0.03 AUC and 20-30 mnats a bar on
these sample sizes. How high a synthetic AUC can go is set by the generator, not by the method;
what the curve fixes is the size of effect the market tables below could have shown.

## 4. Direction on the markets

Test AUC, real bars, with the mean of the two walks in brackets. Bold where real beats walks by
0.01 or more.

**Close only:**

| series | kalman | hmm | particle | qdecoh | qbasis | quantum |
|---|---|---|---|---|---|---|
| EURUSD 15m | **0.521** (0.503) | 0.494 (0.500) | 0.494 (0.501) | 0.494 (0.502) | 0.495 (0.502) | 0.494 (0.501) |
| EURUSD 1h | **0.517** (0.505) | 0.504 (0.502) | 0.503 (0.503) | 0.503 (0.498) | 0.506 (0.503) | 0.507 (0.505) |
| EURUSD 4h | 0.484 (0.504) | 0.504 (0.498) | 0.508 (0.500) | 0.492 (0.499) | 0.488 (0.498) | 0.488 (0.495) |
| EURUSD 1d | **0.525** (0.482) | **0.505** (0.490) | **0.502** (0.488) | **0.514** (0.482) | 0.476 (0.504) | 0.480 (0.505) |
| V75 15m | 0.497 (0.502) | 0.493 (0.498) | 0.495 (0.498) | 0.495 (0.501) | 0.503 (0.500) | 0.502 (0.501) |
| V75 1h | 0.504 (0.504) | 0.499 (0.500) | 0.498 (0.501) | 0.495 (0.498) | 0.502 (0.501) | 0.501 (0.503) |
| V75 4h | **0.508** (0.493) | 0.507 (0.498) | **0.507** (0.497) | 0.495 (0.499) | 0.501 (0.503) | 0.503 (0.497) |
| V75 1d | 0.496 (0.493) | 0.482 (0.501) | 0.486 (0.506) | 0.500 (0.493) | 0.520 (0.514) | **0.525** (0.511) |

**Full candle:**

| series | kalman | hmm | particle | qdecoh | qbasis | quantum |
|---|---|---|---|---|---|---|
| EURUSD 15m | **0.523** (0.502) | 0.498 (0.502) | 0.498 (0.501) | 0.498 (0.498) | 0.496 (0.499) | 0.498 (0.499) |
| EURUSD 1h | **0.514** (0.504) | 0.513 (0.504) | 0.508 (0.501) | **0.513** (0.498) | **0.513** (0.497) | **0.510** (0.498) |
| EURUSD 4h | **0.515** (0.496) | **0.516** (0.495) | **0.510** (0.498) | **0.515** (0.494) | **0.515** (0.495) | **0.520** (0.496) |
| EURUSD 1d | **0.505** (0.484) | 0.525 (0.516) | 0.508 (0.502) | 0.526 (0.517) | **0.502** (0.487) | 0.509 (0.512) |
| V75 15m | 0.496 (0.501) | 0.500 (0.502) | 0.496 (0.504) | 0.501 (0.499) | 0.505 (0.497) | 0.503 (0.499) |
| V75 1h | 0.503 (0.503) | 0.505 (0.500) | 0.498 (0.501) | 0.504 (0.503) | 0.502 (0.507) | 0.503 (0.498) |
| V75 4h | 0.501 (0.493) | 0.499 (0.498) | 0.498 (0.498) | 0.498 (0.498) | 0.505 (0.500) | **0.503** (0.493) |
| V75 1d | 0.497 (0.496) | 0.498 (0.498) | 0.497 (0.500) | 0.497 (0.488) | **0.515** (0.499) | **0.518** (0.501) |

**Benjamini-Hochberg over the 96 real cells: 13 pass,** all EURUSD: Kalman at 15m, 1h (both
observation sets) and 4h (candle); HMM, qdecoh, qbasis and quantum on the 1h and 4h candle. The
1d bold cells and every V75 cell fail it (V75 1d intervals are 0.49-0.55 on 1,128 bars).

**What the 13 are.** One effect read six ways:
- The Kalman filter's fitted drift persistence is phi = -0.023 (15m), -0.044 (1h), -0.043 (4h
  candle). A negative phi forecasts that the next bar partly undoes this one: short-term mean
  reversion, the spring [`physics.md`](physics.md) measured in FX at slope -0.015 to -0.028.
- With the candle, the HMMs spend their states on where the close sits in the bar (state means
  -1.05 / 0 / +1.04 on 1h), and the forecast is the same reversal, read more sharply.
- The flip walk, with real bar shapes and a random sign, scores 0.49-0.51 on all of them. So it is
  behaviour, not chart shape ([`walks-and-edge.md`](walks-and-edge.md)): real minus walk +0.009
  to +0.024.
- **The quantum filter adds nothing to it.** On the 4h candle it is 0.520 against the decohered
  twin's 0.515, inside one interval (0.510-0.528 against 0.505-0.524).

**What it is worth.** Gross and net per bar, always in; confident decile (n, gross, net):

| EURUSD | obs | model | AUC | gross bps | net bps | confident n, gross, net bps |
|---|---|---|---|---|---|---|
| 15m | candle | kalman | 0.523 | +0.07 | -0.02 | 2,083, +0.30, +0.13 |
| 1h | close | kalman | 0.517 | +0.15 | +0.06 | 1,941, +0.38, +0.21 |
| 1h | candle | quantum | 0.510 | +0.09 | +0.00 | 2,125, +0.35, +0.17 |
| 4h | candle | kalman | 0.515 | +0.26 | +0.17 | 1,825, +1.07, +0.89 |
| 4h | candle | hmm | 0.516 | +0.39 | +0.30 | 1,651, +0.90, +0.72 |
| 4h | candle | quantum | 0.520 | +0.45 | +0.37 | 1,393, +0.79, +0.61 |

One basis point is 1.1 pips here. The best confident trade grosses about 1.2 pips. That pays the
0.2-pip raw spread and does not pay a standard retail spread of about 1 pip, or a raw spread plus
commission (about 0.9 pip round trip). **It does not pay as a strategy at the desk's cost.** It is
a real behavioural skill sitting below the cost line, the same place
[`physics.md`](physics.md) left it.

**The tail.** On the confident calls with a one-sigma stop and no target:
- **EURUSD:** real P(>= 4R) 0.16-0.24 against walks 0.16-0.29, and P(>= 10R) 0.06-0.09 against
  0.06-0.14.
- **V75:** the same picture; its best cell (4h quantum close, 0.264 / 0.079 on 242 trades) sits
  inside its walks (0.251 / 0.095 and 0.234 / 0.108).
- **Against 1/(N+1):** nothing sits above 0.200 / 0.091 by more than noise, so there is no tail
  excess anywhere. (A check of the tail code on a pure random walk returned 0.212 / 0.102 on
  3,066 trades, the theorem's 0.200 / 0.091 plus the bar-monitoring shift.)

## 5. Coherence: is the quantum part doing anything?

Training log likelihood per bar (decohered -> coherent in the regime basis -> rotated measurement),
and the fitted dephasing (1 = classical):

| series | close-only | gamma | candle | gamma |
|---|---|---|---|---|
| EURUSD 15m | -1.4078 -> -1.4076 -> -1.4075 | 0.64, 0.79 | -3.8778 -> -3.8634 -> -3.8599 | 0.39, 0.82 |
| EURUSD 1h | -1.3781 -> -1.3699 -> -1.3667 | 0.02, 0.09 | -3.6668 -> -3.6668 -> -3.6663 | 1.00, 0.78 |
| EURUSD 4h | -1.3844 -> -1.3666 -> -1.3652 | 0.07, 0.11 | -3.7776 -> -3.7757 -> -3.7729 | 0.78, 0.74 |
| EURUSD 1d | -1.4378 -> -1.4169 -> -1.4167 | 0.01, 0.02 | -3.4769 -> -3.4736 -> -3.4707 | 0.72, 0.57 |
| V75 15m | -1.4483 -> -1.4481 -> -1.4479 | 0.22, 0.70 | -3.5397 -> -3.5395 -> -3.5393 | 0.93, 0.77 |
| V75 1h | -1.4484 -> -1.4482 -> -1.4482 | 0.02, 0.02 | -3.5414 -> -3.5414 -> -3.5412 | 1.00, 0.94 |
| V75 4h | -1.4489 -> -1.4484 -> -1.4483 | 0.00, 0.62 | -3.5406 -> -3.5402 -> -3.5400 | 0.90, 0.71 |
| V75 1d | -1.4449 -> -1.4401 -> -1.4394 | 0.27, 0.26 | -3.5128 -> -3.5096 -> -3.5071 | 0.70, 0.54 |

On EURUSD close-only at 1h-1d the coherent filter fits better in training (+0.01 to +0.02 nats a
bar), and on 4h and 1d that carries into the test log score:

| series (close) | hmm | particle | qdecoh | qbasis | quantum |
|---|---|---|---|---|---|
| EURUSD 15m | +18.2 | +19.7 | +3.7 | +4.0 | +4.2 |
| EURUSD 1h | +18.4 | +19.1 | -1.8 | -6.9 | +1.2 |
| EURUSD 4h | +2.4 | +2.7 | -2.4 | **+22.9** | **+23.9** |
| EURUSD 1d | +4.1 | +3.5 | +6.9 | **+18.3** | **+19.3** |
| V75 15m-1d | -0.6 to -4.4 | -3.6 to -7.5 | -0.1 to -8.7 | 0.0 to -14.1 | -0.1 to -13.7 |

(mnats a bar over a Student-t walk; Kalman, Gaussian, is -36 to -157 on EURUSD because a
Gaussian misses FX's tails.)

So on EURUSD 4h and 1d the coherent state describes the *shape* of the next return better than
any classical filter here. But the same filters' direction AUC there is 0.488 and 0.480, below a
coin. Whatever coherence buys is in the density (how wide, how peaked), which the desk already
forecasts with simpler tools ([`conformal.md`](conformal.md),
[`gbm-envelope.md`](gbm-envelope.md)), not in the sign. On 15m and 1h the classical HMM and
particle filters have the better density. On V75, a constant-volatility random walk by design,
every filter is at or below the t walk, as it should be.

## 6. Multi-timeframe

Across all 60 real (pair x observation x filter) cells, adding the closed higher-frame forecast
moves the lower frame's AUC by **+0.0008 on average** (max +0.020). The 120 walk cells move
-0.0012 (max +0.016). Selected rows:

| pair | obs | model | lower | lower + higher | higher alone | agree hit | disagree hit |
|---|---|---|---|---|---|---|---|
| EURUSD 15m -> 1h | candle | kalman | 0.523 | 0.525 | 0.509 | 0.517 | 0.500 |
| EURUSD 1h -> 4h | candle | hmm | 0.513 | 0.514 | 0.506 | 0.498 | 0.504 |
| EURUSD 4h -> 1d | candle | quantum | 0.520 | 0.519 | 0.496 | 0.513 | 0.509 |
| V75 15m -> 4h | close | quantum | 0.502 | 0.509 | 0.509 | 0.507 | 0.490 |
| V75 1h -> 1d | candle | hmm | 0.505 | 0.507 | 0.493 | 0.504 | 0.519 |

The higher frame alone is 0.49-0.51 everywhere, so there is nothing for the lower frame to borrow.
"Trade only when both frames agree" never lifts the hit rate by more than the walks' own scatter
(agree and disagree hit rates both 0.48-0.52 in nearly every row). The one row that looks like help, EURUSD 15m ->
1h Kalman (agree 0.517 against 0.500), is the lower frame's reversal again: the higher-frame
reading is near 0.5 and the agreement filter is mostly a coin flip on top of it.

## 7. The zone method on these two instruments

Fill AUC on the test block, a zone filled when a wick reaches the nearest untaken 50-bar swing
within 8 bars:

| series | fill rate | physics (no fit) | method (fitted) | + candle | + higher state | flip walk method | garch walk method |
|---|---|---|---|---|---|---|---|
| EURUSD 15m | 0.195 | 0.883 | 0.888 | 0.891 | 0.888 | 0.894 | 0.904 |
| EURUSD 1h | 0.185 | 0.882 | 0.881 | 0.885 | 0.881 | 0.886 | 0.904 |
| EURUSD 4h | 0.204 | 0.902 | 0.903 | 0.903 | 0.902 | 0.905 | 0.899 |
| EURUSD 1d | 0.193 | 0.884 | 0.888 | 0.888 | - | 0.901 | 0.894 |
| V75 15m | 0.217 | 0.914 | 0.914 | 0.914 | 0.914 | 0.910 | 0.904 |
| V75 1h | 0.208 | 0.914 | 0.913 | 0.913 | 0.913 | 0.920 | 0.904 |
| V75 4h | 0.211 | 0.905 | 0.903 | 0.903 | 0.904 | 0.900 | 0.898 |
| V75 1d | 0.197 | 0.924 | 0.922 | 0.921 | - | 0.921 | 0.908 |

Calibration and the trade toward the most probable zone (target the zone, stop the same distance
away, net of spread):

| series | P >= 0.95: predicted / realised (n) | P >= 0.99: predicted / realised (n) | net R, every bar | net R, P >= 0.95 | net R, P >= 0.99 |
|---|---|---|---|---|---|
| EURUSD 15m | 0.971 / 0.914 (409) | 0.996 / 0.976 (208) | -0.089 | -1.384 | -2.115 |
| EURUSD 1h | 0.970 / 0.890 (353) | 0.996 / 0.973 (183) | -0.068 | -0.991 | -1.277 |
| EURUSD 4h | 0.972 / 0.938 (371) | 0.996 / 0.981 (210) | -0.055 | -0.710 | -1.100 |
| EURUSD 1d | 0.972 / 0.933 (60) | 0.997 / 0.949 (39) | +0.004 | -0.488 | -1.133 |
| V75 15m | 0.972 / 0.879 (726) | 0.997 / 0.959 (518) | -0.107 | -0.908 | -1.580 |
| V75 1h | 0.972 / 0.888 (726) | 0.997 / 0.960 (519) | -0.115 | -0.729 | -1.271 |
| V75 4h | 0.971 / 0.923 (233) | 0.997 / 0.946 (168) | -0.083 | -0.745 | -0.999 |
| V75 1d | 0.974 / 0.969 (32) | 0.997 / 1.000 (18) | -0.050 | -0.388 | -1.181 |

Everything [`zone-fill.md`](zone-fill.md) found holds on EURUSD and V75 at all four timeframes:
- the probability is distance;
- the fitted weights, the whole candle and the higher-frame state add nothing a walk does not;
- "certainty" is overconfident by 2-9 points, and its zones are inside one bar's move, so the stop
  and the spread cost more than the near-certain fill pays.

**The surer the method is, the more it loses, on every series.**

## 8. Liquidity from candles

[`statespace_liquidity.py`](../harness/statespace_liquidity.py) builds the proxies a candle
allows, all from closed bars:
- **amihud:** |r| / volume;
- **Corwin-Schultz:** the spread from two bars' high-low;
- **Abdi-Ranaldo:** the spread from close, high and low;
- **Roll:** the spread from return autocovariance;
- **Kyle lambda:** the slope of return on volume signed by the close's place in the bar;
- **volume z-score** and **range per volume**;
- **zone liquidity:** the volume of recent bars that tagged the zone's level, and the volume of
  the bar that made it.

**V75's volume is a fixed tick rate** (450 a 15m bar), so its volume proxies are price measures in
disguise and zone volume is undefined. On V75 only the three spread estimators mean anything.

| question | EURUSD | V75 |
|---|---|---|
| zone fill AUC, method -> + all liquidity | 15m 0.888 -> 0.890, 1h 0.881 -> 0.888, 4h/1d -0.001; flip walk gains the same (+0.005-0.006) | +0.000 |
| zone profit (net win) AUC, method -> + liquidity | 0.526-0.538 -> 0.525-0.538 | 0.497-0.538 -> 0.501-0.540 |
| direction, liquidity alone | 0.495-0.510 (walks 0.491-0.511) | 0.492-0.510 (walks 0.484-0.520) |
| direction, HMM or Kalman + liquidity | never above the filter alone | never above the filter alone |
| next bar a top-10% move, EWMA -> + liquidity | **15m 0.610 -> 0.680, 1h 0.638 -> 0.713, 4h 0.578 -> 0.642**, 1d 0.568 -> 0.574 | 0.62-0.66 -> unchanged |
| the same on the walks | flip (real volume, real bar sizes) gains the same; GARCH (real volume, its own volatility) gains nothing | - |
| higher-frame liquidity added | direction +0.000, risk +0.01 on EURUSD 1h, matched by the flip walk | nothing |

**Liquidity is a risk variable.** The gain needs real volume next to the real volatility path, and
vanishes when the volatility is synthetic. That is volume carrying information about volatility,
the result [`shockvolume.md`](shockvolume.md) already uses in production, now seen at 15m-4h on
EURUSD through Amihud, Kyle and the spread estimators. It says nothing about which way.

## 9. Caveats, and what the tests caught

- **The EURUSD reversal was found here, and has since been confirmed** on the six other USD majors
  at 15m and 1h, rollover masked, without paying a retail spread ([`fx-reversal.md`](fx-reversal.md)).
  As first written: It sits where [`physics.md`](physics.md)
  put it, so it is a replication of a known effect rather than a new search result. But to trade
  it as a quantum or HMM state on the 4h candle would need a frozen test on unseen data (other
  majors, or forward time) and an execution cost under about 0.5 pip round trip.
- **The EURUSD cost is optimistic** (0.2 pip, no commission). Every net figure above is an upper
  bound.
- **Equal-length GARCH walks share one draw.** The GARCH walk is scale-free and seeded once, so
  the four 50,000-bar series have the same walk underneath. That does not bias any comparison,
  but it means there are fewer independent GARCH walks than rows. The flip walks are all
  distinct.
- **Small daily samples.** V75 1d has 1,128 test bars and 18-57 confident trades. Its quantum
  0.525 has an interval of 0.493-0.556 and fails BH.
- **Fits are local optima.** The quantum filters are fitted from two starts with L-BFGS on at most
  20,000 training bars. The positive controls show that is enough to reach the oracle on 2,800 and
  30,000 bars of coherent data.
- **Bugs caught on the way:**
  - a division by zero in the compiled HMM when a regime emptied on a GARCH walk (guarded);
  - the multi-timeframe join scoring rows where the higher frame had not yet closed a bar, which
    crashed the first full run rather than leaking (fixed by reading only rows where both
    forecasts exist).

## Reproduce

On the lab, with the bar exports laid out as `pipeline_bars/` and `broker/` under `BARS`:

```
./.secrets/lab.sh run research/harness/statespace.py BARS=<bars> OUT=<out> WORKERS=26 OMP_NUM_THREADS=1
OUT=<out>/power.json python research/harness/statespace_power.py
BARS=<bars> OUT=<out>/liquidity.json python research/harness/statespace_liquidity.py
uv run python research/harness/statespace_report.py <out>/results.json
```

The filters need `numba`. The full run takes about 40 minutes on 26 cores; the liquidity and power
runs take minutes.
