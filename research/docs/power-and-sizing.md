# Could these studies have found anything, and how much should the book bet?

By `research/harness/power.py` and `research/harness/sizing_kelly.py`, 2026-09-21. The two
questions this research programme never asked about itself.

Both answers are uncomfortable. **Roughly half the studies were incapable of detecting a
tradable effect**, so their nulls say little; and **the live book's realised edge is negative**,
so the growth-optimal position size is zero.

## Part one: the power audit

Nothing here has ever reported a minimum detectable effect. That matters because an experiment
whose smallest detectable effect exceeds its own cost hurdle cannot succeed whatever it returns
- a null from it is uninformative and a positive from it is the largest of many comparisons.

### The hurdle

At reward-to-risk one, break-even is `p = (1 + c) / (2 + c)`. With the live slippage of 0.063
and spread of 0.020, that is **52.0%** on FX and metals and **51.6%** on the synthetics - so a
rule needs **+2.0** or **+1.6 points** over fair odds. Detecting that at 80% power as a single
hypothesis takes **4,944** and **7,471** resolved trades respectively.

### The verdicts

`MDE*` is Bonferroni-corrected for the number of cells the study scored, because a study that
marks whichever of `k` cells clears a bar is running `k` tests.

| study | n/cell | cells | hurdle | MDE | MDE* | verdict |
|---|---|---|---|---|---|---|
| changepoint, gap alone | 390,603 | 7 | 1.62% | 0.22% | 0.28% | could have seen it |
| imbalance, gap edges | 52,000 | 24 | 1.99% | 0.61% | 0.86% | could have seen it |
| premium_discount | 31,479 | 10 | 1.99% | 0.79% | 1.03% | could have seen it |
| changepoint, gap + spike | 15,038 | 7 | 1.62% | 1.14% | 1.44% | could have seen it |
| breakout_runs, duration | 13,291 | 32 | 1.99% | 1.22% | 1.74% | could have seen it |
| jump_odds, Boom R:R 1 | 16,000 | 72 | 1.62% | 1.11% | 1.67% | only uncorrected |
| patterns, double bottom | 8,000 | 16 | 1.99% | 1.57% | 2.12% | only uncorrected |
| regression_channel, best | 2,673 | 144 | 1.99% | 2.71% | 4.27% | **blind, 5x short** |
| smc, sweep | 1,500 | 18 | 1.99% | 3.62% | 4.95% | **blind, 6x short** |
| displacement, ALL THREE | 1,200 | 8 | 1.99% | 4.04% | 5.16% | **blind, 7x short** |
| changepoint, spike alone | 1,266 | 7 | 1.62% | 3.94% | 4.96% | **blind, 9x short** |
| stretch, typical cell | 800 | 1536 | 1.99% | 4.95% | 8.83% | **blind, 20x short** |
| stretch, best cell | 437 | 1536 | 1.99% | 6.70% | 11.95% | **blind, 36x short** |
| maker_exits, fade 5m | 404 | 300 | 1.62% | 6.97% | 11.46% | **blind, 50x short** |
| stopfree, fade ON spike | 247 | 300 | 1.62% | 8.91% | 14.66% | **blind, 82x short** |

**Seven of fifteen could not have seen a tradable effect if one were there.**

### What this changes, and what it does not

It **does not** reopen the large-sample nulls. A study landing on the fair-odds line to within a
fraction of a point across hundreds of thousands of trades had the power and found nothing;
`premium_discount.py`, `imbalance.py` and the gap cells in `changepoint.py` are real negative
results and this audit leaves them exactly as they were.

It **does** demote the small-cell studies in both directions at once, which is the only honest
way to apply it. Their nulls are uninformative about effects of the size that would matter -
and their marginally positive cells are demoted by the same arithmetic. `stretch.py`'s best
cell of +8.80% sits under an 11.95% detection floor: it is inside the noise of its own design.

### A correction it forces

`stop-free.md` says fade-the-spike is **refuted** by the 5m data. That overstates it. The study
was **50 to 82 times short** of the sample needed, so it cannot distinguish a real +1.6-point
effect from zero. The observed sign flip between resolutions is what an underpowered test looks
like whether or not there is something there.

The correct statement is that fade-the-spike is **unresolvable with the data available**, and
the route to resolving it is not finer bars - `MaxBars` caps those at about a year - but a
larger event budget from the detector's `TARGET_RATE`, which is an explicit knob and would give
thousands of events rather than hundreds.

### The lesson for anything run after this

**Compute the minimum detectable effect before running the study, not after.** If it exceeds
the cost hurdle, the design is wrong and no amount of running it will help. And keep the cell
count down: 1536 cells cost `stretch.py` a factor of 1.73 on its detection floor before any
data was collected.

## Part two: sizing, from the book's own trades

Sized against 957 closed trades from the live journal, so every cost measured in `costs.md` is
already inside the numbers rather than modelled on top. The growth-optimal fraction maximises
`E[log(1 + f R)]`, solved numerically over the empirical distribution rather than from the
Gaussian approximation - realised R has a hard floor near -1 with a tail beyond it, and a
mean/variance formula on that shape errs optimistically.

### The result, which is not about sizing

| | per trade | per day |
|---|---|---|
| observations | 957 | 21 |
| mean | **-0.0757 R** | **-3.449 R** |
| standard deviation | 0.813 | 6.524 |
| Sharpe per bet | -0.093 | -0.529 |
| worst | -2.879 R | -18.751 R |
| ruin above fraction | 0.347 | **0.053** |
| growth-optimal fraction | **0** | **0** |

**The book's realised edge is negative, so the growth-optimal bet is nothing.** No sizing
rescues a negative expectancy - that is the whole of the answer, and it makes the Kelly
machinery moot rather than informative.

At the configured `TRADING_RISK_FRACTION=0.005`, expected growth is **-0.00039 per trade**, and
bootstrapped equity paths give a **median maximum drawdown of 35.3%** and a 95th percentile of
**49.0%**. Those drawdowns are mostly the negative drift compounding, not volatility: 957 trades
at -0.00039 is about -31% by itself.

### How much to believe it

Less than the per-trade count suggests. There are **21 trading days** here at 45.6 trades a day,
so the trades are heavily concurrent and the effective sample is nearer 21 than 957. On daily
aggregates the mean is -3.449 R with a standard deviation of 6.524, which is

    t = -3.449 / (6.524 / sqrt(21)) = -2.42

So the loss is real at about two and a half standard errors over three weeks. That is enough to
act on and not enough to be certain of, and it is a demo book.

### What the numbers do say about configuration

Three things worth keeping regardless of the edge:

**The per-day ruin bound is 0.053, not 0.347.** Concurrency costs a factor of six and a half.
Any sizing argument made on single trades is wrong by that much for this book.

**34 positions at 0.5% each is 17% of equity at risk simultaneously.** `TRADING_MAX_POSITIONS`
is 34 and `TRADING_RISK_FRACTION` is 0.005, and those two have never been checked against each
other. Correlated instruments - and the majors all share a dollar leg - mean the effective
simultaneous risk is higher than independence would give.

**The worst realised day used 37% of the daily loss limit.** -18.75 R at 0.5% is -9.4% of
equity against a `TRADING_DAILY_LOSS_FRACTION` of 0.25. So the limit is not currently binding,
but it is within a factor of three of a day that has already happened.

## What to do

* **Do not change the risk fraction.** It is not the problem. A negative edge sized smaller
  loses more slowly, which is not a fix.
* **Check `MAX_POSITIONS` against `RISK_FRACTION`.** 17% simultaneous exposure on correlated
  instruments is a real exposure question independent of edge, and it has never been looked at.
* **Compute the minimum detectable effect before the next study**, and keep the cell count
  small enough that the correction does not eat the design.
* **Resolve fade-the-spike properly or drop it.** Raising the detector's `TARGET_RATE` is the
  cheap route to thousands of events; finer bars are not, because of the `MaxBars` cap.
* **The live book needs more history before anything can be concluded from it.** Three weeks and
  21 independent days is not a basis for a sizing decision, and the honest next step is to keep
  recording rather than to tune.
