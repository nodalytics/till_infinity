# The Monte Carlo against the broker, and what their difference measures

**Measured 2026-11-20.** 143 live positions over 14 days, each projected with
the production simulator and raced against the bars that actually followed.
Harness: [`race_calibration.py`](../ideas/race_calibration.py).

| question | answer |
|---|---|
| is the simulator calibrated? | **yes, where the sample is honest.** It converges on the barrier identity - **33.3% projected against a 33.3% geometric** at seven days - and the one cell with no directional concentration agrees with reality to **3.5 points** |
| what is `projected - realised`, then? | **a drift meter.** The simulator is driftless by construction, so the gap is realised drift - and on this sample it tracks each edge's long/short bias cell by cell |
| can we "just hold till one hits"? | **unresolved, and the sample says so.** 143 positions against the **350 to 800** `Trade.trials` requires |
| does a tp1/tp2 split help? | **no. It costs 0.16 to 0.32 R a trade** wherever there is anything to lose, and only "helps" where everything loses |

## What was already there, and what was not

`statespace/projecting.py` already runs the race: `Projection.barrier`,
`Projection.geometry`, `Projection.when` for time-to-touch, and a `Trade` object
that prints `win_rate` beside `geometric` because *"their difference is the only
quantity that can be an edge"*. It also already carried the sample constraint -
**350 to 800 trades before a win rate can be told from the geometric one**, and
that bound is indifferent to the reward chosen.

What had never been done is **comparing the projection to the realisation**. The
simulator says what share of these entries should reach the target before the
stop; the broker's deal history says what share did. This is that comparison.

Two defects were avoided in building it, both already on record. The stop and
target are read from the **entry order's own** ticket, because a trailed stop
would make the geometry something the rule never chose; and the walk starts at
the bar **after** the entry bar, whose high and low include prices from before
the position existed - the same-bar defect `#431` was opened for.

## The identity check, which is the result that matters

| horizon | Zones projected | geometric |
|---|---:|---:|
| 1 day | 7.5% | 33.3% |
| 3 days | 15.9% | 33.3% |
| **7 days** | **33.3%** | **33.3%** |

**The simulator lands exactly on the barrier identity.** At reward-to-risk 2 a
driftless race pays `1 / (1 + 2)`, and that is what it pays once the horizon is
long enough to resolve.

**The low short-horizon numbers are correct rather than a bug**, and the reason
is worth stating because it is the same arithmetic that makes a trailing stop
destructive. With the target twice as far as the stop, the stop resolves first
far more often *early*: the resolved subset at one day is stop-dominated, and
the target needs time it has not had. A projection read at one day on a 2R
target is not a forecast of the trade, it is a forecast of the stop.

`projecting.py` records the version of this that was wrong - *"a driftless race
at reward-to-risk 3 paid 0.3790 where geometry requires 0.2500, and the median
time to touch a two-sigma level read 260 bars"* - fixed by keeping **running**
extremes so the first crossing is a binary search rather than a comparison of
two final extremes. This run is that fix holding.

## `projected - realised` is realised drift

Seven-day horizon, every edge:

| edge | n | short share | projected | realised | **proj - real** |
|---|---:|---:|---:|---:|---:|
| Zones | 60 | 37% | 33.3% | **61.7%** | **-28.3** |
| unknown | 40 | 69% | 36.0% | 32.5% | **+3.5** |
| Surprise | 22 | 62% | 37.4% | 45.5% | -8.1 |
| Structure | 21 | **86%** | 31.1% | **0.0%** | **+31.1** |

The simulator assumes no drift - `projecting.py` says that default *"is the
measurement and not a placeholder"*. So where reality disagrees with it, the
disagreement **is** the drift the market had.

And it tracks the directional bias almost monotonically: the edge that entered
63% long realised 62% target-first, and the edge that entered 86% short
realised **0 of 21**. Same fortnight, same market move, opposite signs. That is
one trend scored four times, which is why none of these cells is an edge
estimate. `a-regime-split-is-information-not-a-verdict` is the standing rule and
this column is the clearest instrument for it the desk has: a per-edge estimate
of how much of its record was the market moving one way.

**The honest cell is the one with no concentration.** `unknown` at 40 positions
reads 32.5% realised against 36.0% projected and a 33.3% geometric - inside 3.5
points of both. Where the entries are not pointed one way, the simulator and
reality agree, which is the calibration claim this page can actually support.

`Surprise` at 45.5% realised against a 34.2% geometric is the only
edge-shaped reading here, and at n=22 against a 350-trade requirement it is
worth nothing yet. It is noted because it is the same edge that was the only
profitable family on the broker over the same window, not because 22 trades
mean anything.

## The tp1/tp2 split costs between a sixth and a third of an R

Half out at `tp1` = 1R, the rest to the 2R target, one stop under both, scored
on the **same resolved races** so the columns are the same trades:

| edge | single target | **tp1 at 1R** | difference |
|---|---:|---:|---:|
| Zones | +0.884 | +0.569 | **-0.315** |
| Surprise | +0.343 | +0.126 | **-0.217** |
| unknown | -0.022 | -0.186 | **-0.164** |
| Structure | -1.000 | -0.952 | +0.048 |

**It is negative wherever there is anything to lose, and positive only where
everything loses.** Halving out at 1R gives up half of the winner's second R and
keeps the whole loser, so it reduces the mean by about half the distance between
`tp1` and the target, weighted by how often the target is reached.

**This confirms arithmetic rather than discovering anything, and that is the
point.** The barrier identity is the martingale theorem: every pure geometry
pays `1 / (1 + r)` on a driftless market, so every blend of them pays the same,
and `the-book-is-composable-judge-rules-marginally` is the standing form -
composition buys variance and conditioning, never expectancy. A split that
appeared to *raise* expectancy would be a bug in the settlement, not a finding;
`a-martingale-cannot-pay` records a harness that won 0.470 of 2R races against a
required 0.333 and turned out to be exactly that.

What a split can still do is **condition**: if an edge is concentrated at short
horizons, a nearer `tp1` collects it while the remainder keeps a claim on the
rare long run. That is a different claim from expectancy and this measurement
does not test it, because the entries here are not sorted by horizon.

**And on this broker a split has to be two positions, not two legs.** An MT5
position carries a single `tp` field, and on a hedging account an opposite-side
limit *opens* rather than closes - `mt5-account-is-hedging`. So the choice is
two positions with their own targets, both exits broker-side, or one position
actively part-closed at `tp1`. The second is what `TRADING_SCALE_OUT_AT=1.0`
already configures and it had **never once completed**, because every managed
close raised a `ValueError` in `_close_out` until 2026-11-20. Two positions keep
working when the desk does not, which after that fortnight is the stronger
argument - at the cost of halving the lot, where `TRADING_MIN_LOT_CEILING` can
refuse what it allowed whole, and of consuming two of `TRADING_MAX_POSITIONS`.

## What this does not answer

**Whether to hold till one hits.** The sample is 143 positions against the 350
to 800 `Trade.trials` requires, every per-edge cell is an order of magnitude
short, and the two largest cells are directional artefacts. The pooled realised
rate over all 143 entries is **41.1% against a 33.3% break-even** - positive,
and on a sample that cannot carry the claim.

The measurement that would settle it is the race on **reconstructed** signals
over years rather than fourteen days of one market direction, with the
discovery and confirmation halves separated. That is the open item, and the
harness for the entry side of it already exists in `rsi_momentum.race`.
