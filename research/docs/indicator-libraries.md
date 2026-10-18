# Eight public change-point sources, read against what is already measured here

**2026-10-17/18.** Eight public sources on regime and change-point detection were
put forward over two sessions: four TradingView scripts, two Pine libraries and
one GitHub repository, with three paywalled papers alongside. One was reproduced
and measured; the rest are settled on paper, by naming the measurement here that
already covers the claim. This page is the record, so the same sources are not
assessed from scratch a third time.

**The pattern across all of them is worth stating first.** Five implement the
Adams & MacKay recursion, and four of those five get something structural
wrong - a likelihood that cancels, sufficient statistics that do not travel
with the run length, a variance recursion that is not the one its own citation
gives, or a hazard learned from the wrong spacing. The recursion is short and
easy to write; wiring it to its own sufficient statistics is where it fails.
None of the four would look broken on a chart.

| source | what it is | verdict |
| --- | --- | --- |
| LuxAlgo, "Change-Point Detection (CUSUM)" | two-sided CUSUM on standardised log returns, side = whichever accumulator trips | **reproduced and measured null**: [`cusum.md`](cusum.md) |
| RegimeLib | BOCPD with a hazard and a run-length posterior | **already in the package**: `statespace/changepoint.py`; one component worth porting |
| CyberSignalLib v2 | N-dimensional Kalman, three change-point detectors, microstructure metrics | one genuine convergence, one thing already refuted here, one hazard |
| `Trading---CUSUM-FILTER` | a CUSUM filter implementation | **not read** - see the last section |
| AetherEdge AE-BCP | BOCPD on log squared return, run-length heatmap | the recursion is real and on the right quantity; it cannot infer its own `R` |
| AetherEdge AE-SHIFT | BOCPD on ATR-normalised returns, adaptive hazard, directional signal | one portable idea (the adaptive hazard), learned from the wrong spacing |
| EntropyLib | binary and ternary Shannon entropy of a sign series | **resolves the untested idea: as implemented it is a folded up-rate** |
| RegimeLib, source read | BOCPD plus score-driven variance | confirms the description and adds two implementation faults - port the paper |

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

## Entropy of the direction sequence, as it stood before the source was read

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

**That was the position before `EntropyLib`'s source was read, and the source
changed it.** The published implementation is order-invariant, so it is not a
sequence statistic and the run it would have justified would have been scoring
the up-rate - see the `EntropyLib` section below. The sequence version, over
transitions or k-gram blocks, is what is still untested.

## The three AetherEdge and cybermediaboy scripts, with their sources read

### AE-BCP: the right recursion on the right quantity, and it cannot infer `R`

`AE-BCP` monitors `log(r^2 + eps)` by default - a log variance proxy - runs the
full run-length recursion with a Gaussian predictive at `pvar = 1 + 1/r`, and
publishes a change-point probability, an expected run length and a MAP run
length. No direction anywhere. That is a fourth independent arrival at this
desk's emission rule, and the recursion is correct as written.

Two things it cannot do, both structural. It **standardises its observation
over a trailing 200-bar window** and clips to six sigma, so what it monitors is
a trailing z-score: a slow drift in the volatility level is invisible to it by
construction, and `trailing-zscore-fakes-reversion` is the measured reason to
be careful with that family - a shuffled twin took +0.111 of a +0.137 effect at
z 4.23. And because the standardisation pins the predictive variance at one, it
has **no measurement variance to infer** - which is the quantity
`dispersion_noise.py` had to measure here, and the quantity whose inferred
value carried the entire +0.2 increment in
[`changepoint-increment.md`](changepoint-increment.md).

### AE-SHIFT: a real recursion, a closed signal, and one portable idea

The recursion is genuine - per-hypothesis Welford statistics that travel with
the run length, growth and change-point mass, normalisation - and the author
says so honestly: a Gaussian predictive rather than the Student-t conjugate,
which under-states predictive spread for short runs, exactly where a break is
being declared. Its **signal is the direction** of the fresh segment from
three-bar momentum, which is the half measured closed over 112,429 rows.

**The adaptive hazard is the one genuinely portable idea in any of these
files**, and ours does not have it: re-estimate the expected run length from
the observed spacing between change-points, so the hazard is learned per
instrument rather than fixed. One flaw to fix before porting - it learns from
the spacing between *fired signals*, which require a change-point **and** a
direction flip **and** a side different from the last one. So the spacing it
averages is of a direction-filtered subset, which biases the learned run length
upward and couples the hazard to the one quantity that carries nothing. Learned
from the change-point posterior instead, it is one arm on the harness that
already runs BOCPD, and the metric is already chosen: the hazard moves the
run-length mixture, so it moves the predictive `sd` - which is the column that
reads +0.21 to +0.24 on a 48-lag ridge.

### EntropyLib settles the untested idea, and the answer is no

The entropy of the direction sequence was the one idea this page had down as
untested. `EntropyLib` implements it, and reading it answers the question
without a run:

    upRate = sma(x > 0 ? 1 : 0, length)
    h = -(p log p + (1-p) log(1-p)) / log 2

`upRate` is the **count** of up bars over the window divided by its length, so
`h` is a function of `p` alone. It is therefore **invariant to every reordering
of the window**: shuffle the bars and it does not move. It is not a sequence
statistic at all - it is a monotone transform of `|p - 0.5|`, which is the
up-rate folded about its centre, which is *direction imbalance*. That is the
half measured closed, approached from a new angle and arriving at the same
place.

The ternary version adds a flat zone at a percentile of `|x|`, which pins
`p_flat` near the percentile asked for by construction - `flatPct = 55` gives
`p_flat` near 0.55 on every window - so it is a near-constant plus the same
folded up/down split of the large moves, and order-invariant for the same
reason.

**What remains untested is the sequence version**, and it is a different
statistic: entropy of the *transition* distribution, or block entropy over
k-grams of the sign. Those are not order-invariant, and low block entropy means
persistent runs, which is a volatility-clustering statement rather than a
directional one. That is still worth one arm, as a dispersion feature - but it
is not what this library computes, and anything that scored the library's
version would have been scoring the up-rate.

### RegimeLib's source: the citation is the thing to port, not the code

Reading the implementation confirms the description assessed above - BOCPD with
a score-driven variance - and names the paper to take it from: Tsaknaki, Lillo
and Mazzarisi 2023, `arXiv:2307.02375`. Two faults make the code itself the
wrong thing to port.

**The sufficient statistics do not travel with the run length.** The posterior
shifts - `growth[r + 1]` is built from `rl_probs[r]` - while `run_means[r]` and
`run_vars[r]` are updated **in place**. After the first bar, hypothesis `r`
therefore carries statistics that never belonged to a run of length `r`, and
`n_r = r + 1` divides the Welford step by a count the accumulator never saw.
AE-SHIFT writes `newMean[r + 1]` for exactly this reason.

**The variance recursion is not the paper's.** It computes
`score = delta^2 / var - 1` and then `var <- omega + alpha * score^2 + beta *
var`, which is **quartic** in the residual and sign-blind, where a score-driven
update is linear in the score. On a tail it explodes rather than adapts. The
vanilla path is safe only because `omega = 0, alpha = 0, beta = 1` switches the
whole term off.

So the earlier verdict stands with its reason changed: score-driven variance is
worth having as a dispersion arm, from the paper, and this is not an
implementation of it.

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
