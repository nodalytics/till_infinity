# The z-score, rebuilt with nothing batched in it — and three things that turned out to be nothing

`zma.py` is the shipped indicator and every part of it is batch. Every bar it
takes a softmax over a 50-element deque, refits an OLS slope over the same, and
sorts a 200-element deque twice for two percentiles. Each of those has an exact
O(1) recursion, so [`harness/zmastream.py`](harness/zmastream.py) writes them
and then asks what the rebuild is worth.

The honest answer: **the cost goes away, the answer does not change, and three
things the desk hoped for are not there.** Two of the three were worth finding
out and one of them is a defect in shipped code.

## The shipped attention does nothing at all

`zma.py` weights each bar by `exp(|r| - max|r|)` over the window's absolute
returns and calls it attention. A softmax has an opinion only when its inputs
differ by O(1). Absolute one-minute returns differ by about **1e-4**.

Kish's effective sample size, where a uniform weighting over a 50-bar window is
exactly 50:

| series | max/min weight | effective n |
| --- | --- | --- |
| BTC 1m, real bars | 1.00064 | **49.00** |
| GBM at 1m scale | 1.00025 | **49.00** |
| GBM at 2% a bar | 1.05093 | 48.99 |
| spiky, boom-like | 1.00025 | **49.00** |
| OU theta=0.15 | 1.01297 | **49.00** |

The "attention-weighted z-score" is a plain rolling z-score, on every series
tested, including one deliberately built to have violent isolated bars. This is
the [`inert.md`](inert.md) shape exactly: shipped, configured, logged correctly,
and doing nothing.

**And repairing it changes nothing measurable.** The fix is a temperature -
divide by the running mean absolute return, which puts the exponent at O(1) and
makes the weighting scale-free at the same time. On the same series, same bars,
same everything else:

| | hit | depth skill | z AUC |
| --- | --- | --- | --- |
| attention off | 0.654 | -0.020 | 0.593 |
| attention on | 0.654 | -0.018 | 0.592 |

So the **A** in ZMA is not carrying the indicator, it never was, and it would
not if it worked. That is worth knowing before anybody tunes it.

## Nested timeframes: three ways, and none of them adds anything

Markets are claimed to be fractal - small cycles inside big ones - and a small
cycle fighting the cycle above it is supposed to be worth less than one running
with it. That is testable, and the test needs a control where the claim is
**true by construction**: a fast Ornstein-Uhlenbeck deviation around a slow
level that is itself an OU, with a dial for how much the slow level contaminates
the fast window, and a matched null where the fast part is a **random walk**
under the same visible two-scale shape.

Three readings were tried. `residual` divides the mother cycle out of the price
before the z-score is taken - the one that should work, because it changes the
reading rather than voting on it. `w/trend` keeps only calls running with the
cycle above. `counter` keeps only those fighting it.

| contamination | arm | raw | residual | w/trend | counter |
| --- | --- | --- | --- | --- | --- |
| 0.0 | reverting | 0.698 | 0.696 | 0.682 | 0.715 |
| 0.0 | null walk | 0.498 | 0.502 | 0.506 | 0.494 |
| 0.5 | reverting | 0.688 | 0.687 | 0.688 | 0.688 |
| 1.0 | reverting | 0.654 | 0.656 | 0.650 | 0.673 |
| 2.0 | reverting | 0.613 | 0.613 | 0.608 | 0.610 |
| 4.0 | reverting | 0.552 | 0.553 | 0.546 | 0.559 |
| 8.0 | reverting | 0.538 | 0.534 | 0.534 | 0.538 |
| 8.0 | null walk | 0.501 | 0.498 | 0.479 | 0.521 |

The **raw** column is a real and orderly result: the fast reading degrades
smoothly as the cycle above takes over its window, 0.698 down to 0.538, while
the null stays flat at 0.50 throughout. The detector is reading exactly what it
should and losing exactly what a bigger cycle takes from it.

The other three columns track it within **0.005 at every level**. Dividing the
mother cycle out does not repair the contamination; running with the cycle above
does not beat running against it - if anything `counter` is marginally higher,
which is the opposite of the hypothesis and is inside the noise.

On real bars at real timeframes - 1m, 15m and 1h as their own stored series,
each read only once its own bar has **closed** - the same:

| series | z AUC | hit | with trend | against |
| --- | --- | --- | --- | --- |
| btc BINANCE-COINBASE spread | 0.698 | 0.802 | 0.834 | 0.773 |
| btc BINANCE-KRAKEN spread | 0.698 | 0.773 | 0.815 | 0.739 |
| btc BITSTAMP-DERIV spread | 0.669 | 0.762 | 0.728 | 0.804 |
| btc @ BINANCE | 0.500 | 0.505 | 0.520 | 0.513 |
| gold @ OANDA | 0.504 | 0.502 | 0.487 | 0.513 |
| eurusd @ PEPPERSTONE | 0.491 | 0.475 | 0.489 | 0.465 |

Two spreads up on trend agreement, one down by more than either gain. Mean lift
across the eight instruments is **+0.01**, and the simulation with a matched
null says the mechanism is not there. `cycle_alignment` and `cycle_with_trend`
are published so the journal can settle this on the desk's own instruments over
months rather than from one sample - not because they are believed.

## What does work: how far, but not how long

A turn is a confirmed extremum - price retracing `2.0` volatility units from the
running extreme of a leg. Confirmation arrives **after** the extreme, which is
the delay the prediction exists to bridge, and every prediction made during a
leg settles at once when it turns. Two heads, both scored against the only
baseline that matters: the running mean of their own target, taken at the time.

**How much further price runs before turning is predictable where the process
reverts, and nowhere else.** Skill is negative on every simulated arm including
both OU controls, and positive on 8 of 8 constructed spreads:

| | depth skill |
| --- | --- |
| btc BINANCE-COINBASE | **+0.188** |
| btc BINANCE-DERIV | +0.170 |
| btc BITSTAMP-COINBASE | +0.150 |
| btc COINBASE-KRAKEN | +0.127 |
| btc BINANCE-KRAKEN | +0.092 |
| btc BITSTAMP-DERIV | +0.077 |
| btc BITSTAMP-KRAKEN | +0.030 |
| btc BINANCE-BITSTAMP | +0.030 |
| every simulated arm | -0.012 to -0.052 |

On real multi-timeframe bars the same three spreads give **+0.193, +0.061 and
-0.013**, so the effect is real on some and absent on others rather than uniform.

**How long until the turn is not predictable.** `when` skill is positive on the
nulls too - +0.009 on GBM, +0.022 on the shuffled control - so a positive value
there is a property of the metric and not of the series. It is published and
this sentence is the reason not to read it as a result.

## Two arithmetic defects the rebuild found

**The exact recursion was wrong while warming, by 109x.** Exponentially weighted
least squares against the bar index needs `sum(lam^k)`, `sum(k lam^k)` and
`sum(k^2 lam^k)`. All three have tidy closed forms, and using them is wrong
until the tail vanishes - which for the `k^2` term takes about **2,000 bars** at
a 50-bar decay. Against a least-squares fit computed the slow way, the closed
forms give a slope **109 times too large at 300 bars**, converging by 2,000 and
exact from there. Accumulating the three sums by recursion alongside the other
two is the same O(1) and exact at every length, including the first bar.

That is not a rounding difference. It is the difference between an indicator
that warms up and one that emits noise for the first month of every new
instrument, silently, on exactly the feeds nobody is watching yet.

**A threshold on an unnormalised quantity is a threshold on nothing.** The
alignment readings weight each cycle above by how stretched it is, and a
mid-range cycle has to count as neutral rather than as opposition. With one
cycle above, `total` and `weight` are the same number, so the ratio is `+/-1`
whatever the magnitude: a mother cycle at a z-score of **6e-9** - numerically
still - reported full opposition. A minimum pull fixes it, and the first
minimum applied to the *trend* reading was on a raw slope divided by a mean
absolute return, which passed almost never and made `cycle_with_trend` a
constant zero. `tests/test_published.py` caught that, which is what it is for.

Both are the same mistake in different clothes, and it is the same one as the
softmax: **a number needs a scale before a constant can be compared with it.**

## What shipped

[`structures/cycles.py`](../till_infinity/structures/cycles.py). Everything that
learns is `river`'s - `LinearRegression` under a `StandardScaler` for the heads,
`ADWIN` for drift, `stats.Quantile` for the thresholds - because those are
solved problems already depended on elsewhere in this package. The two things
river has no equivalent for are written by hand: attention-weighted moments,
because no river statistic takes a caller-computed per-observation weight, and
regression against the bar index, which is not regression against features.

Weights save to **their own file**, and that is the point rather than a
convenience. `structures/store.py` hashes the shape of every persisted dataclass
and invalidates the whole state file when any of them changes, so a deploy that
adds one field to one unrelated class would otherwise throw away every turn this
has settled.

Recorded and scored, acting on nothing: `STRUCTURES_CYCLES_ACT` is off, and two
of the three things this adds were measured at nothing above.

    till-infinity structures cycles
