# A regime-aware exit does not beat the hold clock, and the clock is not where the money goes

Measured 2026-09-24 with [`holdclock.py`](../harness/holdclock.py) on the lab, on the
journal copy dated 2026-09-10 (decisions 2026-08-13 to 09-10) and 3m bars for 40 symbols.
The question is the first entry of `docs/todo.md`: `thesis-only` lost 389.98 on trades closed
by the clock, every `hold_seconds` is a constant, so would an exit that knows when the
regime ends do better?

**No.** Out of sample, on 1,812 level trades with the book's 30-minute clock, the best
changepoint exit moves the mean by **+0.005R (t 0.5)** and the plain changepoint rule by
**-0.001R**. A randomised exit fired just as often scores **-0.006R**. The dumbest control,
"get out after one bar", does better than any of them at **+0.021R (t 2.0)**, and the regime
rules lose to it head to head (t -1.3 to -2.1). On the 4-hour runner clock every regime exit
is **worse** than the clock (-0.02R to -0.18R). The 74 live trades in the test block show
nothing either way.

Under all of this is a problem with the premise. **"The money went on the clock" describes
which exit booked the loss, not what caused it.** Take the clock away altogether and the same
trades do no better: -0.011R for thesis trades, 0.000R for scalps, -0.043R for runners and
-0.033R for the live trades. Trades end up on the clock *because* they did not reach their
target, so the clock bucket is the losers by construction.

## What was run

| population | source | n (train / test) | clock | cap |
| --- | --- | ---: | ---: | ---: |
| **live** | the desk's closed trades joined to their `trading/decision`, with their own side, stop, target and `hold_seconds` | 185 (111 / 74) | own (median 30m) | 4x the clock |
| **thesis** | every `structures` `level` decision on 1m-30m, stop max(risk_vol, 4)v, target the modelled push: `thesis-only` as it ran, about 0.37 reward-to-risk | 3,955 (2,143 / 1,812) | 30m | 2h |
| **scalp** | the same entries, stop max(risk_vol, 1)v, target 1x push (`level-scalp`) | 3,955 (2,143 / 1,812) | 30m | 2h |
| **runner** | stop max(risk_vol, 1)v, target 3x push (`runner`) | 634 (335 / 299) | 4h | 16h |

`v` is the decision's own `vol_bps` x price. That reproduces the live `risk_price` exactly.
Of the 325 live closes, 140 drop out. Most are cash indices and oil, which have no bars on
the lab. `snap` also goes: its 120-second clock is shorter than one 3m bar. The signal
entries are thinned per symbol so that no two overlap, even under the longest exit. The 20,953
decisions that map to a symbol with bars come down to 3,955 at the 2h cap and 634 at the 16h cap.

The exits, all scored on **the same trades** and compared pair by pair:

| exit | what it does |
| --- | --- |
| `const` | the trade's own clock |
| `none` | stop and target only, closed at the cap |
| `median` | hold for the median bars-to-exit of *winning* training trades (the dumb re-tuned constant) |
| `best_k` | the constant hold that scored best on the training block (a fairer dumb control) |
| `cp` | exit when P(a changepoint since entry) exceeds theta: BOCPD run-length posterior |
| `resid` | exit when the posterior expected **residual time** falls below rho x its pre-test median |
| `rclock` | at entry, set the clock to alpha x the expected residual time |
| `random` | exit each bar with the probability `cp` fired per bar in training (the MQL5 article's control) |

theta, rho, alpha and the constants are chosen on the first 60% by time and then frozen. The
test block starts 2026-09-04 for the signals and 2026-09-03 for the live trades. Stops and
targets resolve on wicks through `bars.race`: the fill is at the level, or at the open on a
gap, and a bar that spans both levels counts as the stop. The spread is charged at
questions.py's `COST_V` (synthetics 0.17v from [catalogue.md](catalogue.md)).

### The regime model

The model is BOCPD with a Normal-Gamma observation model on 3m returns. The returns are
divided by a lagged two-day EWMA of |r| and clipped at 8. The run-length prior is a discrete
Weibull duration: k = 1 is plain BOCPD's constant hazard, and k != 1 is the case where
residual time says anything. Residual time is the Weibull's mean residual life averaged over
the run-length posterior. (lambda, k) is chosen per symbol by the one-step predictive
likelihood on bars before the test block. That is the residual-time quantity of
Agudelo-España et al., **with the duration parameters fitted offline**. Their online
hyper-parameter learning is not implemented. The `cp` rule is run under both the fitted
prior (`fit`) and the best flat hazard (`flat`).

## First the todo's kill check: the hazard is not flat

The todo said to check this before building anything. If regime durations were memoryless,
residual time would be a constant and a lookup would be the whole answer.

| instruments | best shape k | best lambda | log-likelihood over the best flat hazard |
| --- | --- | --- | ---: |
| 15 FX, gold, silver, BTC/ETH/SOL | **0.4** | 5 bars | +165 to +344 per symbol |
| Boom / Crash (5) | 0.6 | 5 | +236 to +890 |
| Jump 10 / 25, Range Break 100 / 200 | 0.4 | 5 | +400 to +1,522 |
| Volatility indices (10), Step | 3.0 | 960 (edge) | +36 to +39 |

Wherever something happens, the hazard **falls** with age (k < 1): a regime that has lasted
tends to keep lasting, so residual time is informative and step 3 of the todo was worth
running. The constant-volatility indices are the ground-truth check. They are iid by
construction ([twins.md](twins.md), [deriving.md](deriving.md)), and the model duly finds
regimes longer than the data. lambda = 5 bars is at the edge of the grid. With a Gaussian
observation model, many of those short "regimes" are fat tails being explained as brief
regime changes. That is a known weakness of the method, and it is part of why the exits
below have little to work with.

## The test block

Mean net R of each exit minus the clock's on the same trades, with t in brackets and the two
halves of the test block separately:

| exit | thesis (1,812) | halves | scalp (1,812) | halves | runner (299) | live (74) |
| --- | --- | --- | --- | --- | --- | --- |
| `const`, the level | -0.156R | -0.169 / -0.144 | -0.375R | -0.400 / -0.351 | -0.086R | -0.111R |
| `none` | -0.011 (-1.2) | -0.021 / -0.002 | +0.000 (+0.0) | -0.007 / +0.007 | -0.043 (-1.4) | -0.033 (-0.6) |
| `median` (3 / 3 / 7 / 5 bars) | +0.005 (+0.7) | +0.007 / +0.004 | +0.008 (+0.8) | -0.002 / +0.018 | -0.139 (-2.0) | -0.020 (-0.5) |
| `best_k` (1 / 1 / 3 / 1 bars) | **+0.021 (+2.0)** | +0.014 / +0.028 | **+0.028 (+1.9)** | +0.014 / +0.043 | -0.136 (-1.7) | +0.023 (+0.4) |
| `cp`, flat hazard | -0.001 (-0.1) | -0.017 / +0.015 | -0.001 (-0.1) | -0.024 / +0.023 | -0.071 (-1.6) | -0.065 (-1.8) |
| `cp`, fitted hazard | -0.001 (-0.1) | -0.018 / +0.016 | +0.005 (+0.6) | -0.020 / +0.029 | -0.074 (-1.7) | -0.012 (-0.3) |
| `resid` | +0.005 (+0.5) | -0.002 / +0.013 | +0.014 (+1.0) | -0.004 / +0.032 | -0.024 (-0.8) | +0.040 (+0.7) |
| `rclock` | +0.008 (+1.2) | -0.005 / +0.022 | +0.000 (+0.0) | -0.015 / +0.015 | **-0.180 (-2.4)** | -0.077 (-2.1) |
| `random`, matched rate | -0.006 (-1.0) | -0.011 / -0.001 | +0.001 (+0.2) | -0.005 / +0.006 | -0.043 (-1.6) | -0.004 (-0.1) |

Head to head against the dumb one-bar constant on thesis trades: `cp` -0.022 (t -1.8),
`resid` -0.016 (t -2.1), `rclock` -0.013 (t -1.3). No regime exit clears the bar this
repository uses (|t| >= 3, with both halves agreeing). None beats a randomised exit fired at
the same rate by more than noise. None beats the re-tuned constant at all. On the runner
geometry the regime exits hurt, which makes sense: its test-block hold curve peaks at the
clock it already has, 30-80 bars.

**The hold barely matters for these trades.** The whole test-block curve for a constant
hold of k bars:

| k (3m bars) | 1 | 3 | 5 | 10 (the clock) | 20 | 40 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| thesis | -0.135 | -0.151 | -0.167 | -0.156 | -0.167 | -0.167 |
| scalp | -0.347 | -0.367 | -0.381 | -0.375 | -0.375 | -0.375 |

Going from 3 minutes to 2 hours moves the result by 0.03R. The trades lose about the same
whatever the hold, because the loss is in the entry and the geometry. [deriving.md](deriving.md)
proves why for the synthetics: on a martingale no predictable exit changes gross expectancy.
A regime-aware exit is one of those, so it can only change variance and how much spread is
paid.

### By family and by strategy

This is the test block for thesis trades. Each cell is the exit's paired difference from the
clock:

| family | n | clock | `best_k` | `cp` fit | `resid` | `rclock` | `random` |
| --- | ---: | ---: | --- | --- | --- | --- | --- |
| synthetic | 1,041 | -0.081 | +0.021 (+1.5) | +0.007 (+0.8) | +0.023 (+1.7) | +0.018 (+1.7) | +0.002 (+0.3) |
| fx | 516 | -0.287 | +0.015 (+0.7) | -0.018 (-0.9) | -0.036 (-1.5) | +0.000 (+0.0) | -0.021 (-1.4) |
| crypto | 184 | -0.274 | +0.034 (+1.1) | -0.005 (-0.3) | +0.021 (+0.8) | -0.014 (-1.1) | -0.020 (-1.7) |
| metal | 71 | +0.002 | +0.035 (+0.7) | +0.010 (+0.3) | +0.015 (+0.3) | -0.011 (-0.4) | +0.025 (+1.2) |

Among the synthetics the largest cell is Boom/Crash `resid` at +0.056 (t 2.0, n 261). That is
one of about 60 family-by-exit cells in this table's sub-family version, so something that
size is expected by chance. The runner's regime exits cost up to -0.63R on Range Break (n 16), so a
regime "change" is exactly the moment not to cut a Range Break runner. Metal scalps like every
early exit, the randomised one included (+0.04, t 3.3, n 71). The random control scoring there
means the gain comes from holding less, not from timing.

Only `thesis-only` has enough live trades in the test block to split out (59). Its paired
differences run from -0.082 (`rclock`) to -0.006 (`resid`), and none is positive.

### The trades that really closed on the clock

The brief asked for these specifically, and they need a warning. Among test-block trades that
the constant clock closes, `best_k` gains **+0.130R at t 9.6** on thesis, and `resid` gains
+0.084 (t 4.2). **Both numbers are selection, not edge.** "Closed by the clock" is known only
after the whole hold, and it means "did not touch the target in 30 minutes". With a target at
0.37 of the stop, the trades that drift the right way hit the target and leave this subset, so
what stays has drifted the wrong way, and any earlier exit looks good on it. On *all* trades the
same rule gains +0.021, because early exits also give up the targets that would have been hit.
The live trades that really closed on the clock (36) show the same pattern at a smaller size:
`best_k` +0.087 (t 1.2), `resid` +0.117 (t 1.7), `cp` +0.006 and -0.062, and no clock at all
-0.075.

The same selection is behind the todo's headline. The 75 `thesis-only` clock closes at -389.98
are the trades that did not work, gathered in one bucket by the exit that happened to end them.

## Defects checked, and the ones that remain

* **Clock alignment.** The live fill price sits inside the 3m bar at its journal time for
  **100%** of trades, against 6-15% at every whole-hour offset from -4h to +4h. The bars and
  the journal share one clock. The harness refuses to score if that ever fails.
* **Look-ahead.** The posterior at bar t uses bars up to t, and every rule decided at a close
  fills at the next bar's open. Entry is the open of the first bar that opens at least one bar
  after the decision, which is safe whether a bar's timestamp is its open or its close. The
  residual clock at entry reads the posterior from the bar *before* the entry bar. A flat-hazard
  `resid` reduces exactly to the `best_k` one-bar exit, as it must when residual time is a
  constant. The code reproduces that identity, which checks the plumbing.
* **Stops booked at the barrier.** Every barrier goes through `bars.race`, so gaps fill at the
  open and a bar spanning both levels counts as the stop.
* **A leaking data source.** `prices.db` on the lab reports *"database disk image is
  malformed"* on a full scan, so nothing here uses it. Everything comes from `seqlab/*.3m.npz` and the
  journal. The bars' own `spread` column is **not** used for cost: ETHUSD carries 58,000
  points, about 2% of price, which cannot be a quoted spread. Using it first made crypto look
  -13R a trade. That spread artefact is still in the bars.
* **Replay fidelity is mediocre.** The simulated clock-exit kind matches the live
  `exit_kind` on **59.9%** of trades, and simulated and real R correlate **0.49**. Live trades
  also had trails, break-even protection and `stale` exits, which this does not model. The path
  is re-anchored to the first safe bar's open, and 3m bars cannot see inside a 30-minute
  scalp's first few minutes. The live rows are therefore a sanity check on the signal rows, not
  a replay of the book.

## What this does not show

* **One regime model on one resolution.** Gaussian BOCPD on 3m returns, with durations fitted
  offline. A model of the regime the *level* lives in (break versus hold, the desk's own
  `learning/regimes.py` states) might see something that return statistics cannot. This is
  the version the todo described, not the only possible one.
* **About a week of test, three to four days per half.** The standard errors of the paired differences
  are about 0.01R on the signal trades, so an effect under about 0.03R could hide here. An
  effect that small would not be worth a changepoint model.
* **Exit mechanics the desk has.** No trails, break-even or partial banks. A regime signal
  could be used to *tighten a trail* rather than to exit, and that is untested.
* **The cash indices and oil** have no bars on the lab, and they account for most of the 140
  live trades that dropped out.

## What follows

* **Do not build residual-time exits.** Step 3 of the todo has been run: the hazard is not
  flat, and the exit it enables still does not beat a constant, a randomised control or
  having no clock. Step 4, changing a production hold on it, should not happen.
* **Stop reading exit-kind attribution as causation.** "-389.98 on the clock" gets smaller
  if the clock is removed, not larger. The comparison that means something is the same trades
  under another exit. For thesis trades, removing the clock costs 0.011R.
* **The one-bar exit is not a recommendation.** +0.021R at t 2.0 on a strategy that loses
  0.156R a trade is a smaller loss, not an edge. It says what the hold curve says: these
  entries have nothing to hold for. The money is in the entry and in a 0.37 reward-to-risk
  geometry ([`opportunity.py`](../../till_infinity/trading/strategies/opportunity.py)'s
  `reward_floor`), which is where [locking.md](locking.md) and the todo's own step 1
  already pointed.
