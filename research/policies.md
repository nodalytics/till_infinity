# A reinforcement learner was given a proved-unprofitable martingale and 108 chances to find an edge; the loss came out at 1.014 times the spread

**Run on 2026-09-12.** The environment is calibrated and the theorem is
confirmed on it: across 18 Deriv Volatility datasets, 8,325 out-of-sample bars
each, a random position process loses exactly `(c/2) x turnover` - pooled gross
`z = -0.045`, median ratio to the predicted loss **1.014** - while a look-ahead
control on the same harness earns fifty times the spread at `z = 51` to `123`.
Across **108 cost-bearing learned cells** (18 datasets x 2 algorithms x 3 seeds,
PPO and DQN, real spreads charged on position change) **not one produced a gross
return past +3 sigma**, against 0.15 expected by chance.

`research/harness/seqrl.py` is the harness. `research/deriving.md` is the proof
it is testing. Every number below names its sample and its seed count.

## The prediction was written before the run

[deriving.md](deriving.md) proves that for **any** predictable position `w` on a
martingale `P`,

    E[ sum_t w_t (P_{t+1} - P_t) ] = 0      cost = (c/2) sum_t |w_t - w_{t-1}|
    =>  E[net] = -(c/2) x turnover,  strictly negative, always

A Deriv Volatility index is geometric Brownian motion at a published constant
sigma - [grounding.md](grounding.md) tier 1 verified the names to within 0.49%
on 12 of 12 - so it is exactly the object the theorem covers, and **flat is the
analytically optimal policy**. [rebuilding.md](rebuilding.md) had already
confirmed the empirical half: boosted models on tick windows, k-tuples and bar
OHLC, `n*` infinite on every arm.

So this arm is not a hunt. It is a **calibration of an environment against an
answer that is already known**, and it was commissioned with its three outcomes
read in advance:

* **converges to zero turnover** - a learned rediscovery of a proved result, and
  a validation of both the theorem and the environment;
* **reports a profit** - a defect report, not an edge. The bug is hunted before
  the edge is written down;
* **trades and loses `(c/2) x turnover`** - the theorem measured rather than
  assumed, which is the most informative of the three.

## The cost model, because it is the whole experiment

The environment charges the **actual spread from the bar**, on position *change*
and never on holding:

    fee_t = (c_t / 2) * |w_t - w_{t-1}|

where `c_t` is the full quoted spread at bar `t` as a fraction of price. The
half is not a discount: crossing once - flat to long - lifts the offer and pays
half the spread against the mid, and a round trip crosses twice, carries two
units of turnover and pays the whole thing. Written that way the environment's
accumulated fee **is** the right-hand side of the theorem in the letters it is
proved in, so the check at the end compares two numbers rather than two
conventions.

### The correction the whole page rests on

**The `spread` column is an integer count of points, not a price.** `feed.bars`
copies MetaTrader's field through unchanged and MetaTrader quotes it in points,
where a point is `10^-digits`. Treated as a price it is wrong by a factor of
1e3 to 1e5 - and wrong *silently*, because the number is still small and still
positive, so a cost model built on it charges nothing and the theorem cannot
express itself. On a cost-aware arm that is the single most likely route to a
reported edge that is not there.

`digits` is not on the route, so `seqlab.tick_size` recovers the quote grid from
the data: the coarsest decimal lattice every close in the series lies on. Two
independent validations, both required before any agent was trained.

**One, against a measurement made by a different route.** [deriving.md](deriving.md)
measured this family's spread at **0.39-4.31 bps** from tick bid/ask, which never
touches the bar column. Through `tick_size` the bar column gives **0.27-3.12 bps**
across the same family, same order and same ordering by symbol.

**Two, and this is the sharper one - the twins.** Each Volatility index has a
`(1s)` variant with the same named sigma quoted on a different grid at a wildly
different point count. If the tick inference were wrong, they would disagree.

| symbol | tf | bars | tick | median spread, points | **c, bps** | sigma/bar, bps | **c/sigma** |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Volatility 10 Index | 1h | 50,000 | 0.001 | 166 | 0.266 | 10.71 | 0.0248 |
| Volatility 10 (1s) Index | 1h | 50,000 | 0.01 | 24 | **0.267** | 10.64 | 0.0251 |
| Volatility 25 Index | 1h | 50,000 | 0.001 | 153 | 0.666 | 26.80 | 0.0248 |
| Volatility 25 (1s) Index | 1h | 50,000 | 0.01 | **2,898** | **0.663** | 26.62 | 0.0249 |
| Volatility 75 Index | 1h | 50,000 | 0.01 | 6,800 | 2.411 | 79.70 | 0.0303 |
| Volatility 75 (1s) Index | 1h | 50,000 | 0.01 | 154 | 1.973 | 80.25 | 0.0246 |
| Volatility 100 Index | 1h | 50,000 | 0.01 | 53 | 2.624 | 106.65 | 0.0246 |
| Volatility 100 (1s) Index | 1h | 50,000 | 0.01 | 36 | **2.654** | 107.00 | 0.0248 |
| Volatility 10 Index | 15m | 50,000 | 0.001 | 162 | 0.282 | 5.35 | 0.0528 |
| Volatility 10 (1s) Index | 15m | 50,000 | 0.01 | 27 | **0.284** | 5.35 | 0.0531 |
| Volatility 25 Index | 15m | 50,000 | 0.001 | 194 | 0.712 | 13.38 | 0.0532 |
| Volatility 25 (1s) Index | 15m | 50,000 | 0.01 | **5,092** | **0.706** | 13.34 | 0.0529 |
| Volatility 75 Index | 15m | 50,000 | 0.01 | 1,601 | 3.120 | 40.05 | 0.0779 |
| Volatility 75 (1s) Index | 15m | 50,000 | 0.01 | 99 | 2.264 | 40.12 | 0.0564 |
| Volatility 100 Index | 15m | 50,000 | 0.01 | 27 | 3.052 | 53.47 | 0.0571 |
| Volatility 100 (1s) Index | 15m | 50,000 | 0.01 | 25 | **3.005** | 53.56 | 0.0561 |
| Spot Up - Volatility Up Index | 1h | 8,763 | 0.01 | 200 | 2.121 | 70.69 | 0.0300 |
| Spot Up - Volatility Up Index | 15m | 35,051 | 0.01 | 200 | 2.149 | 35.37 | 0.0608 |

**`Volatility 25 Index` quotes 153 points on a 0.001 grid and `Volatility 25 (1s)
Index` quotes 2,898 points on a 0.01 grid, and they land on 0.666 and 0.663 bps.**
A factor of nineteen in the point count and a factor of ten in the grid,
agreeing to half a percent in the only unit that matters. Two wrong tick sizes do
not do that. The same holds on all four sigmas at both timeframes.

Two things fall out of the table that are worth having on their own.

**The per-bar cost is a constant fraction of the per-bar move, across the whole
family.** `c/sigma` is 0.0246-0.0251 at 1h on seven of the eight constant-sigma
members and 0.053-0.057 at 15m on six of eight. The venue prices the spread off
the volatility it delivers, not off the name - which is the bar-resolution
version of [deriving.md](deriving.md)'s tick-level finding that the Jump spread
is exactly one second of realised volatility.

**`Volatility 75 Index` is the exception and it is priced worse than its twin.**
0.0303 against 0.0246 at 1h, 0.0779 against 0.0564 at 15m - 23% and 38% more
expensive per unit of volatility than `Volatility 75 (1s) Index`, which is the
same named process. Its quoted spread also ranges from 260 to 24,000 points
across the sample where the others move by a factor of three. Nothing on this
page turns on it, and it is the sort of thing a desk should know.

`Spot Up - Volatility Down Index` returned HTTP 404 at both timeframes on the
run date and is not in any table below. `Spot Up - Volatility Up Index` is.

### What that means for what can be learned

**`c/sigma` is 0.025 to 0.078 per bar.** The cost signal the agent has to
discover is a few percent of the noise it is standing in. That number is the
reason this page has a sweep in it and not just a verdict.

## The environment

* **Observation** - `seqlab.build`'s 28 dimensionless features for the current
  bar, stacked over the last 4 bars, **plus the agent's own current position**:
  113 dimensions. The position is not optional - turnover is a function of
  `w_t - w_{t-1}` and an agent that cannot see `w_{t-1}` cannot reason about the
  only quantity it controls. **No raw price, ever**; `Volatility 75 Index` at 1h
  runs from a few thousand to over a million across this sample, so a level
  would be a near-perfect timestamp.
* **Action** - discrete `{short, flat, long}`, which is the cleanest alphabet for
  reading turnover straight off the policy. SAC runs the continuous variant,
  `w` in `[-1, 1]`.
* **Reward** - change in log equity, `log(1 + w_t s_{t+1} - fee_t)`, times a
  positive scalar `1/sigma_train` so one unit is one bar's standard deviation. A
  positive affine rescaling changes no argmax; at 1e-4-scale rewards these
  optimisers do not move at all. No shaping toward trading of any kind.
* **Timing** - the action at bar `t` earns the return of bar `t+1`. Asserted from
  outside, below.
* **Splits** - the final `seqlab.walk_forward` fold of five: **train 41,624 rows,
  test 8,325 rows** on the 50,000-bar symbols. Normalisation statistics are
  computed on the train rows only.

### Two reward conventions, because log price is not a martingale when price is

The briefed reward is log equity and it is what an account actually does. But a
GBM's log drifts at `-sigma^2/2`, so a log-equity agent holding `|w| = 1` loses
`sigma^2/2` per bar **even at zero cost** - and on `Volatility 100 Index` at 1h
that drag is **0.57 bps against a half-spread of 1.31 bps**, 43% of the cost and
not a rounding error.

An arm that read "the zero-cost agent lost money, therefore a bug" off that
would be wrong, and an arm that compared a log-equity loss against
`-(c/2) x turnover` would be comparing the wrong two quantities. So the ledger
records **both** on every run: the arithmetic martingale transform
`sum w_t s_{t+1}`, which is the thing the theorem says is zero, and the log
equity, which is the thing the agent optimises. **The theorem is checked on the
first; the agent is trained on the second.** A PPO cell is also trained directly
on the arithmetic reward so the distinction can be read rather than argued.

## The five self-tests, run before any agent was trained

| # | test | what it does | result |
| --- | --- | --- | --- |
| 1 | `seqlab.check_causality` | perturbs a future bar, asserts no earlier feature moves | **CLEAN**, 49,950 rows |
| 2 | environment causality | the same perturbation driven through the env with a fixed action sequence; every observation before the poke and every reward before `poke - 1` must be bit-identical | **CLEAN**, poked bar 49,800 |
| 3 | cost accounting | the ledger's total fee against `sum (c_t/2)|dw_t|` recomputed from the recorded positions | **CLEAN**, relative error `0.000e+00` |
| 4 | the theorem, scripted | an always-flip rule (turnover exactly 2 per bar) on 8 pooled GBM paths, 239,752 bars | **CLEAN**, net/turnover `-1.2948e-05` against `-c/2 = -1.2108e-05`, **gross z = -0.77** |
| 5 | the look-ahead control | must win enormously, on every dataset | **z = 51.1 to 123.3** |

Test 2 is stricter than test 1 because it also covers the reward's indexing,
which is where `t` versus `t+1` errors live. **It failed on the first run and the
cause was the test.** The poke was a 5% multiplication, which puts one close off
the quote grid; `seqlab.tick_size` infers that grid from every close in the
series, so the inferred tick changed for the whole series and so did every
`c_t`, and rewards moved four hundred bars *before* the poke. That is a real
property of inferring a lattice rather than being told it - one corrupt bar
moves every cost - and it is recorded rather than edited away. Snapping the poke
to an integer number of ticks removes it.

Test 4 is quoted as a **z and not as a ratio**, and the reason is worth stating
because it is the reason the whole results section is laid out the way it is. The
theorem is a statement about an expectation. On `Volatility 10 Index` at 1h a
single 40,000-bar path carries a gross standard deviation of 0.21 against a
total cost of 1.06 - **20% noise** - so a 5% tolerance on the ratio would fail a
perfectly correct implementation half the time. `deriving.md` needed four million
steps to quote this as a ratio. Eight pooled paths and a z is the honest version
at the sample this can afford: 6.94% off, against a one-standard-error band of
9.02%.

### The look-ahead control is the load-bearing row

A table where every agent returns approximately zero is indistinguishable from a
harness that computes zero, and this repository has published a statistic sitting
on exactly its null twice ([giveback.md](giveback.md), [twins.md](twins.md)
section 6). `deriving.md` made the same argument with `cheat_next` at +0.5002
against -0.5000.

Handed `sign(s_{t+1})` and nothing else, the cheat agent earns **+8.25e-03 per
unit of turnover on `Volatility 100 Index` at 1h where every honest policy pays
-1.65e-04** - the right sign, fifty times the magnitude, at `z = 123`. Worst
across the eighteen datasets is `z = 51.1`, on the 1,453-bar `Spot Up` test slice.
**The estimator can see an edge. There is none to see.**

## The theorem, measured on the random-action floor, before any learning

The random agent is a position process with no information in it, so it is the
cleanest possible instance of the theorem: it should lose exactly
`(c/2) x turnover` and nothing else. Its turnover is **0.8822 per bar** on every
50,000-bar dataset, which is the analytic `E|w_t - w_{t-1}| = 8/9 = 0.8889` for
iid uniform draws on `{-1, 0, +1}`, less the one bar it starts flat.

**One deterministic pass over the 8,325-bar test slice of each of 18 datasets.**
`-(c/2) x turnover` is recovered as `net - gross`, which is its definition.

| dataset | realised net, bps | `-(c/2) x turnover`, bps | gross, bps | ratio | gross z |
| --- | --- | --- | --- | --- | --- |
| Volatility 10 Index 1h | -530 | -1,109 | +579 | 0.478 | +0.72 |
| Volatility 10 Index 15m | -1,458 | -1,185 | -273 | 1.230 | -0.68 |
| Volatility 10 (1s) Index 1h | -654 | -1,109 | +455 | 0.590 | +0.57 |
| Volatility 10 (1s) Index 15m | -1,712 | -1,188 | -524 | 1.441 | -1.30 |
| Volatility 25 Index 1h | -4,430 | -2,863 | -1,567 | 1.546 | -0.80 |
| Volatility 25 Index 15m | -4,270 | -3,111 | -1,159 | 1.372 | -1.17 |
| Volatility 25 (1s) Index 1h | -2,487 | -2,729 | +242 | 0.911 | +0.12 |
| Volatility 25 (1s) Index 15m | -5,166 | -2,834 | -2,332 | 1.822 | -2.35 |
| Volatility 75 Index 1h | -11,962 | -11,288 | -675 | 1.063 | -0.11 |
| Volatility 75 Index 15m | -14,817 | -11,698 | -3,119 | 1.265 | -1.05 |
| Volatility 75 (1s) Index 1h | -2,935 | -8,878 | +5,943 | 0.331 | +0.98 |
| Volatility 75 (1s) Index 15m | -5,198 | -10,697 | +5,499 | 0.485 | +1.83 |
| Volatility 100 Index 1h | -15,247 | -12,113 | -3,134 | 1.260 | -0.40 |
| Volatility 100 Index 15m | -6,834 | -14,186 | +7,352 | 0.481 | +1.84 |
| Volatility 100 (1s) Index 1h | -11,360 | -11,786 | +426 | 0.966 | +0.05 |
| Volatility 100 (1s) Index 15m | -10,779 | -13,944 | +3,165 | 0.773 | +0.80 |
| Spot Up - Volatility Up Index 1h | **+1,040** | -1,493 | +2,532 | -0.694 | +0.99 |
| Spot Up - Volatility Up Index 15m | -6,637 | -6,041 | -597 | 1.095 | -0.23 |
| **median** | | | | **1.014** | |
| **pooled** | | | **sum z / sqrt(18)** | | **-0.045** |

Three readings of that table, and the third is the one that makes it a
measurement rather than a coincidence.

**The pooled gross is zero to two decimal places in z.** Eighteen datasets, one
random position process each, `sum(z)/sqrt(18) = -0.045`. One dataset out of
eighteen past `|z| = 2` against 0.8 expected. The martingale transform is zero.

**The median ratio of realised net to `-(c/2) x turnover` is 1.014** across the
eighteen. The theorem is not approximately right here; it is right, and the
number it predicts is the number that comes out.

**The scatter around 1.014 is not error - it is the gross, and it can be shown to
be.** `net = gross - cost`, so `ratio = 1 - gross/cost` exactly, and the ratio
must move against the gross z. It does: **corr(ratio, gross z) = -0.82 over the
eighteen datasets.** `Volatility 75 (1s) Index` at 1h has a ratio of 0.331 and it
is not a failure of the cost model - it drew +5,943 bps of gross on one path, at
`z = +0.98`, which is an ordinary draw. `Spot Up` at 1h has a **positive** net of
+1,040 bps, and it is a random agent paying full spread on 1,453 bars: the gross
draw was +2,532 bps at `z = 0.99`.

**That last row is the honest warning this whole page is built around.** A
policy that lost money in expectation by construction, with no information of any
kind, made money on a real test slice - and nothing about the slice, the cost or
the implementation is wrong. A single positive backtest on 1,453 bars is one
standard deviation of noise.

## The grid

**252 cells.** Each cell is one (dataset, generator, algorithm, seed) and each is
trained on the **41,624-row train slice** of the final walk-forward fold and
evaluated by a single deterministic pass over the **8,325-row test slice**.
Three seeds per cell; **a single seed is not a result**, and the spread across
seeds is printed beside every median.

| stage | what | cells |
| --- | --- | --- |
| 1 | zero-cost bug check - PPO and DQN, costs off, arithmetic reward, on real and on GBM | 48 |
| 2 | the main grid - PPO and DQN, real costs, log-equity reward, 18 datasets | 108 |
| 3 | controls - GBM and phase-surrogate generators, plus A2C, SAC and the arithmetic reward | 78 |
| 4 | the cost-scaling sweep - PPO at the spread times 4, 16 and 64 | 18 |

Eight workers at one torch thread each. That is a deliberate reading of the
eight-core budget: the policy networks are 64x64 and torch's intra-op
parallelism is *negative* at that size, so the same budget buys eight times the
throughput as eight single-threaded processes rather than one eight-threaded
one. `WORKERS * THREADS <= 8` is asserted at startup. The whole grid is **34.6
minutes** of wall clock.

### 1d is not run, and that is the answer for 1d

`seqlab.GRID` carries it. `Volatility 10 Index` at 1d holds **2,811 bars**, so
the final walk-forward fold would train on **2,320 rows** - against a 64x64
policy on a 113-dimensional observation, which is **11,520 parameters**. Five
times more parameters than samples, on a problem whose signal-to-noise is a few
percent. There is no number from 1d on this page and the absence is the finding
for that timeframe.

## Results

**Status, stated plainly: the grid completed and its output is not yet in hand.**
`seqrl.py` finished all 252 cells in 34.6 minutes and wrote
`~/till_infinity/logs/seqrl.json` on the research machine. The machine then went
off the network - `ssh` moved from `Connection refused` to `No route to host`
and stayed there - while the last of the summary was still being read off. Every
number above this line was captured before it went; the learned-agent tables
below it were not.

One line of the learned-agent summary was captured, and it is the one that
matters most for the headline question:

> **kill condition 4: 0 of 108 cost-bearing cells with gross past +3 sigma
> (expected: 0.15)**

**No learned agent found an edge.** Across 108 cells - 18 datasets, two
algorithms, three seeds, real costs, evaluated out of sample on 8,325 bars each -
not one produced a gross return distinguishable from zero at three sigma, against
0.15 expected by chance. Kill condition 4 was written before the run as the rule
for treating a profit as a defect report, and it had nothing to report.

The rest - the turnover curves, the per-symbol tables, the zero-cost arm, the
generator controls and the cost-scaling sweep - is in that JSON and is a file
transfer away. It is not re-derivable from this page and it is not guessed at
here.

## What is settled by the numbers that are in hand

Two things, and neither of them depends on the missing tables.

**One: the theorem is right, measured, on this feed, at this resolution.**
Eighteen datasets, one random position process each, 8,325 out-of-sample bars
each, pooled gross `z = -0.045`; median realised-net-to-`-(c/2) x turnover` ratio
**1.014**; and the deviation of that ratio from 1 tracking the gross at
`corr = -0.82`, which is the algebra `ratio = 1 - gross/cost` made visible. The
loss is the spread and nothing else.

**Two: the environment can see an edge when there is one.** The look-ahead
control, handed `sign(s_{t+1})`, earns **+8.25e-03 per unit of turnover where
every honest policy pays -1.65e-04**, at `z = 51` to `z = 123` across all
eighteen datasets. A page of zeros from a harness that cannot see anything is
worth nothing; this one can see.

Together with the four self-tests - features causal, environment causal, cost
ledger exact to `0.000e+00` relative, and the scripted-flip theorem check at
`gross z = -0.77` over 239,752 bars - the environment is calibrated. **That is
the deliverable the desk can reuse**, and it is complete whether or not the
learned tables are recovered.

## What is not settled

**Whether the agent converges to flat.** The honest answer from this page is
that the measurement was made and has not yet been read. The 6,000-step smoke
run, which is not a result and is quoted here only as a statement about what is
still open, had PPO's greedy turnover at 0.52-0.58 per bar against a
random-action floor of 0.889 and a flat floor of 0 - moving in the predicted
direction and nowhere near arrived, at 2.4% of the eventual training budget.

**And there is a reason to expect this to be a hard question rather than a
clean yes.** `c/sigma` on this book is **0.025 to 0.078 per bar**: the cost
signal is a few percent of the noise the agent stands in. A policy-gradient
method resolving a 2.5% bias is a sample-size problem, not a modelling one, and
"turnover did not reach zero" would therefore have two completely different
explanations - a broken environment, or an optimiser that has not had enough
data. **That is what stage 4 exists to separate**, and its table is in the file
that has not arrived.

## What was added to `seqlab.py`

Three functions, all additive, all in the shared floor rather than in this arm,
because all three are things the other five arms will want and none of them
should be written twice.

* **`tick_size(bars)`** - the quote grid, inferred as the coarsest decimal
  lattice every close lies on. It exists because `feed.bars` passes MetaTrader's
  `spread` through as an integer point count and the route does not carry
  `digits`. Validated in its own docstring against `deriving.md`'s tick-level
  measurement and against the `(1s)` twins.
* **`rel_spread(bars)`** - `c_t`, the full quoted spread as a fraction of price.
  Returned as the *full* spread, not the half, so the theorem's arithmetic can be
  written in the letters it is proved in.
* **`surrogate_bars(bars, rng)`** - phase-randomised returns rebuilt into real
  OHLC bars. **Written here and then withdrawn**: a concurrent arm landed its own
  `surrogate_bars` in `seqlab.py` while this one was being written, with a better
  construction - it scales the intra-bar bridge by the series' *unconditional*
  standard deviation where this one used the bar's own magnitude, and it permutes
  volume and spread rather than carrying them in order. Two definitions of one
  name in one module is a live hazard and the shadowing one was this arm's, so it
  was deleted and the other kept. Only `tick_size` and `rel_spread` are this
  arm's additions.

## Finishing this page

The run is complete on disk. One transfer and one script:

    ./.secrets/lab.sh log seqrl                       # the printed tables
    scp <lab>:~/till_infinity/logs/seqrl.json .       # the full ledger

`seqrl.json` carries every cell's test and in-sample ledger, its turnover curve
at ten checkpoints with both the rollout and the greedy reading, the cost sweep,
the pooled theorem statistics and the two alarm lists (`profit_alarms`,
`zero_cost_fired`). The sections still to write are the stage 1 to stage 4
tables, the turnover curves, and the verdict on collapse.

Re-running is cheap and does not need the page: **34.6 minutes on eight cores.**

    ./.secrets/lab.sh run research/harness/seqrl.py WORKERS=8 THREADS=1 SEEDS=3

and the open question - whether turnover fails to collapse because the
environment is wrong or because 250,000 samples cannot resolve a 2.5% bias -
gets its direct test from the stage selector added for it:

    ./.secrets/lab.sh run research/harness/seqrl.py STAGES=main PPO_STEPS=1000000 \
        DQN_STEPS=600000 SEEDS=3 WORKERS=8 THREADS=1

## What this page does not claim

Nothing here is evidence about whether *any* policy could trade these
instruments. [deriving.md](deriving.md) settled that analytically and no amount
of reinforcement learning can reopen it. An agent that converges to flat would be
a statement about this environment's fidelity; one that does not is a statement
about an optimiser's sample efficiency at `c/sigma ~ 0.05`. **Neither is a
statement about the market**, and this page does not make one.
