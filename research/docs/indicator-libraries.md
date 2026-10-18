# Four public change-point libraries, read against what is already measured here

**2026-10-17/18.** Four public sources on regime and change-point detection were
put forward in one session: two TradingView scripts, one Pine library and one
GitHub repository, with three paywalled papers alongside. One was reproduced and
measured; the rest are settled on paper, by naming the measurement here that
already covers the claim. This page is the record, so the same four are not
assessed from scratch a third time.

| source | what it is | verdict |
| --- | --- | --- |
| LuxAlgo, "Change-Point Detection (CUSUM)" | two-sided CUSUM on standardised log returns, side = whichever accumulator trips | **reproduced and measured null**: [`cusum.md`](cusum.md) |
| RegimeLib | BOCPD with a hazard and a run-length posterior | **already in the package**: `statespace/changepoint.py`; one component worth porting |
| CyberSignalLib v2 | N-dimensional Kalman, three change-point detectors, microstructure metrics | one genuine convergence, one thing already refuted here, one hazard |
| `Trading---CUSUM-FILTER` | a CUSUM filter implementation | **not read** - see the last section |

## RegimeLib is BOCPD, and the package already has a stronger one

`statespace/changepoint.py` is Adams & MacKay with a Normal-Inverse-Gamma
conjugate, which makes the predictive a Student-t: the same hazard, the same
run-length posterior, the same `changepoint` and `run_length` outputs. Two
things ours has that the published version does not - it **infers its own
measurement variance**, which no other member in the package does, and it is
time-aware through `FRESH_HOURS`.

One component goes the other way and is worth porting: **score-driven
variance**, a GARCH-shaped `omega/alpha/beta` recursion on the variance rather
than a conjugate update. It belongs as a *dispersion* arm, which is the half of
the problem that pays ([`dispersion-forecast.md`](dispersion-forecast.md)).

Note what RegimeLib deliberately does not return: a direction. Its outputs are
run length, a change-point flag, a regime id and a current variance. That is
independent confirmation of the emission rule this desk arrived at by
measurement and then shipped in `statespace/service.py` - **change-point and
dispersion, no side.**

## CyberSignalLib, component by component

| their component | ours | verdict |
| --- | --- | --- |
| `KalmanStateN`, packed covariance, adaptive Q/R | `statespace/linear.py`, `smoothing.py`, `adapting.py`, `pooling.Pooled(adapt=True)` | ours is measured: 5.6x CRPS over the best single member ([`statespace-pooling-exponent.md`](statespace-pooling-exponent.md)) |
| `ChangepointKind.BOCPD` | `statespace/changepoint.py` | **ours is the recursion; theirs is not** - below |
| `ChangepointKind.NIS`, innovation squared over S | `Desk.read`'s `surprise` | we keep a *window* of them and build the published band out of it |
| `ChangepointKind.CUSUM` | [`cusum.md`](cusum.md) | measured: the side is null, the change-point is beaten by more lags |
| `efficiency_ratio`, abs(close-open)/(high-low) | `spanning.py` | **independent convergence on the strongest dispersion feature here** |
| `delta_aggressor`, Kyle's lambda, VPIN | [`lopez-de-prado.md`](lopez-de-prado.md) section 4, [`orderflow.md`](orderflow.md) | already measured, already null |

### Their BOCPD is not BOCPD, and the algebra says so

`bocpd_step` computes one Gaussian log-likelihood `ll`, forms
`growth = log(1 - h) + ll` and `change = log(h) + ll`, and flags a change when
`change > growth + threshold`. `ll` appears on both sides, so it **cancels**:
the test reduces to `log(h) - log(1 - h) > threshold`, which is a constant. It
fires always or never, depending only on where the threshold sits relative to a
fixed number, and the data never enters. It also tracks a single integer run
length rather than a posterior over run lengths, so there is no recursion to
normalise and nothing to be uncertain about.

This matters beyond one library: a detector whose statistic cancels still
*plots*, and a plot that moves with the price - because the state estimate it
rides on moves with the price - reads as a working detector.

### `efficiency_ratio` is the encouraging part, and we have it

`abs(close - open) / (high - low)` is a monotone cousin of the range-vs-close
estimator ratio in `spanning.py`, which is the strongest dispersion feature on
this desk: AUC **0.648** within strata of current volatility on FX and
**0.667** on 98% of the 371 equities scored out of 392
([`candle-screen.md`](candle-screen.md)).
Two independent paths arriving at the same statistic is worth more than any
single claim in the file.

### The microstructure section is closed here, with numbers

`delta_aggressor` is the tick rule on sub-bars with a bulk-volume `tanh`
fallback for flat bars - the construction already measured in
[`lopez-de-prado.md`](lopez-de-prado.md) section 4:

| family | base AUC | + VPIN | gain [95%] |
| --- | --- | --- | ---: |
| FX | 0.7613 | 0.7583 | **-0.0030** |
| crypto | 0.7511 | 0.7564 | +0.0052 |
| **walks** | 0.5032 | 0.5084 | **+0.0052** |

The walks row ends it: a walk's volume is drawn independently of its price and
gains exactly as much as crypto did. On Kyle's lambda,
[`orderflow.md`](orderflow.md) records signed flow correlating **+0.51 to
+0.65 with the same window's return** - it is the price move relabelled. The
root cause is structural rather than statistical: MT5 tick volume is a count of
*quote updates*, not signed trade flow, so VPIN's premise has nothing to
measure on these feeds. Easley and co-authors built it on exchange volume.

### One hazard worth naming before anybody ports it

`update_scalar` does a one-sided covariance update, `P_ij -= K_i * (H P)_j`,
and its comment calls this "a practical compromise vs full Joseph". That is the
form which can silently lose positive-definiteness, and it is exactly where
this package got burned once: `smoothing.py`'s `_gain` built the `P F'` columns
reversed, still smoothed, still beat the filter, and ran **19% worse while
looking right**. If that code is ever ported, the Joseph form is not optional.

## The one genuinely untested idea: entropy of the direction sequence

Binary or ternary Shannon entropy over a rolling window of sign codes is in
none of our harnesses. Note what it is: a function of the **sign** sequence,
which is the half measured closed here - Kronos reads 0.50 across 112,429 rows
and an ESN's direction AUC is 0.4981 to 0.5295 ([`biases.md`](biases.md)). As a
**bias** the prior is null, and direction being closed rather than merely
null is why that is not worth a run of its own.

As a **dispersion feature** it is more interesting, because low sign-entropy
means persistent runs, which is a volatility-clustering statement rather than a
directional one. That makes it one arm on the harness in
[`changepoint-increment.md`](changepoint-increment.md), beside the
exponentially-weighted control that page already names as next.

## What was not read, and what would change

Three sources could not be opened: IEEE 10660149 and 10729381 are paywalled,
and the ASQ article on the step cumulative sum chart returned 403. The GitHub
CUSUM filter repository arrived mid-turn and was never fetched; the measured
result in [`cusum.md`](cusum.md) comes from reproducing the Pine source
directly, not from that repository.

What an abstract could change: nothing about the side, which is measured null
over 6,778 fires with a sweep monotone in 1/n rather than in `(lookback, slack,
threshold)`. What it could change is the **statistic** - a step CUSUM accumulates
a fitted step size rather than a fixed slack, and if one of those papers states
a step rule for the slack, that is a different detector and a cheap second arm.
Until then the parameterisation we measured is the published one.
