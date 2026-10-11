# statespace: six times an effect appeared and was not there

Extracted from `statespace/README.md` on 2026-10-11, and the most reusable thing in it. Four of the six were my own bugs, and **not one was caught by reading the code**.

What caught them - the synthetic feeds, counting the cells, asking whether survivors cluster, correcting the overlap, costing everything, and noticing when a number cannot be true about a market - applies to any measurement in this repository and not only to a state space.

## Are these models finding structure in randomness?

Asked on 2026-10-11, and it is the right question. **Mostly yes, and this file
now contains six demonstrations of it - four of them mine.** Written down as a
section rather than a footnote because the methodological lesson outlasts every
number above it.

### The six times structure appeared and was not there

| what was claimed | how large | what it was |
| --- | --- | --- |
| fading a 1-2 week slope at 15m | `t = -10.8` | overlapping windows; gone at `t` on independent ones |
| the same, on **v75** | `t = -10.7` | a *generated* series, so there was nothing to find |
| 3m and 15m innovations confirming each other | `t = +20.8` | lookahead: a 15m bar stamped at T closes at T+15m |
| `swarm` winning 18 of 24 series | - | a log-sum-exp missing its shift, inflating every step |
| `S4D-Real` winning 21 of 39 | - | too narrow a grid; it **is** the random walk once `drift` is free |
| the innovation reverting at 3m | `t = -7.1` | real, and 0.16 spreads wide - inside the cost |

Three were my bugs, two were method artefacts, one was real and unusable. Not
one of them was caught by reading the code.

### What caught them, which is the transferable part

**The synthetic control.** v75, v25 and v100 have *generated* volatility. A
method that finds an effect there is finding it in its own machinery - and when
the 15m fade appeared on v75 as strongly as on usdjpy, that was the end of it.
After the overlap correction v75 produces **no survivors at all**, which is the
control working in the other direction: it now says the surviving effects are
properties of markets.

**Counting the cells.** The slope harness tests 2,250 of them, so **6.1 are
expected above `|t| = 3` by chance**. It found nine. A list of survivors whose
length matches the noise rate is not evidence, and printing the expected count
beside the found count is what makes that impossible to forget.

**Asking whether survivors cluster.** Noise scatters; structure does not. The one
effect that survived everything is six cells in a single corner - usdjpy daily,
`h = 5`, two related signals, three adjacent lookbacks, same sign, positive after
cost. That is a different object from nine cells sprinkled across five symbols.

**Correcting the overlap properly.** Observations are independent only when they
share neither outcome window nor *signal* window, so the step is
`max(look, horizon)`. Stepping by the horizon alone still left a four-week
lookback sharing 1,870 of its 1,920 signal bars. Tightening it removed every raw
`slope` survivor on usdjpy 1d and left only the EMA ones.

**Costing everything.** Three separate real effects in this file turned out to be
the size of the spread: the 3m innovation reversion at 0.16 spreads, the gbpusd
15m fade where the edge and the cost were both 0.113 volatility units, and the
usdjpy 15m innovation. A return before costs is not a result.

**Noticing when a number cannot be true.** Two unit errors were found because
the output was physically absurd - a spread of 136 volatility units on a market
that trades, and an `existence` of 0.045 on a level touched every fifteen
minutes. Faster than review, and it should be the first check.

### And what is left, which is not nothing

**The data looks like a random walk with forecastable volatility.** That is the
synthesis and every measurement here is consistent with it:

* it **diffuses at 1.00, 1.04, 1.06 and 1.07** times `sqrt(h)` across horizons of
  1, 5, 20 and 50 - a martingale, with the faintest trend
* **direction is unforecastable.** Every signal tested gave `continue` between
  48.3% and 49.6%, and the best signed `t` on 70,000 points was -1.7
* **size is forecastable, robustly.** Recent speed predicts the next move's
  magnitude with a 3.12x spread between extreme quintiles at one bar and still
  **2.03x at fifty**. That replicated across symbols, timeframes and horizons
* the random walk wins 17 to 21 of 39 series at every horizon, and **nothing
  beats it on the point forecast**

A random walk with time-varying volatility produces exactly what was measured:
unforecastable sign, forecastable magnitude. So the honest reading is not that
the models found nothing - it is that they found **the volatility**, which is
real, and that every directional find was artefact or spread-sized.

### What that means for the package

It does not invalidate the state space. It sets what it is for.

`reverting` beats the random walk on 11 of 39 series at **all four horizons**,
which is a member-level result repeated across series rather than a cell-level
fluke, and it is the one member that does. `swarm` is the only model whose band
is honest far out - 92.8% coverage at `h = 50` against `reverting`'s 88.0% and
`linear`'s 88.8%. Neither of those is a directional edge and neither needs to be:
a desk that sizes on the band needs an honest band, and a desk that forecasts
volatility needs the member whose uncertainty means something.

**The rule from `__init__.py` was right and is now expensive to ignore**: nothing
publishes until it has beaten a *named* null. The null has to include the random
walk, the synthetic control, the overlap correction, the cell count and the
spread - and the first version of every measurement in this file failed at least
one of those.

## The audit: four bar counts in a library that forbids them

Asked on 2026-10-11, after a harness bug turned out to be two conversions of
one duration: *is the library itself clean, or only the rule?* It was not clean.
Four bar counts, two of which were defects and two of which are correct, and the
difference between those pairs is the reusable part.

**`resolvable()` counted calendar bars.** Its first bound exists so no rung is
shorter than two bars - below that the window clamps to one and reports a single
bar's own high and low under a name claiming a horizon. The bound was computed
without `coverage`, so on a market that closes it admitted rungs the series
could not build: the exact failure it was written to prevent. Half an hour is
two bars of a 24/7 15m feed and about **one** of a weekday one. The fix moved
the bottom rung on every part-time market - a 3m FX series loses `5m` and gains
`2w` - and is pinned by a test that asserts the `30m` rung disappears from a
weekday 15m series.

**`smoothing.lagged(hours=...)` divided by the median spacing alone**, which
converts *trading* hours rather than calendar ones, because the median gap
between consecutive bars is the bar size and skips the closures. So
`lagged(hours=2)` and the `2h` rung of the ladder were different lags on
anything that closes. Two meanings of one word, which is shape #5 in the
`finding-bugs` skill and the thing to watch for here rather than a missing
conversion.

**`changepoint`'s freshness window and its truncation were horizons wearing
counts.** "The run is at most two readings old" is half an hour at 15m and two
days at 1d. And the cap of 300 components was justified in its own comment as
the point where the geometric prior's tail is negligible - which is a claim
about *time*. At 1d, 300 components is 300 days against a ten-day expected
regime and the claim holds. At 15m it is **three days**, less than a third of
one regime, so the posterior sat against the cap permanently and `run_hours`
reported a lower bound while reading like an estimate. Both are durations now,
the cap covers three expected regimes of time inside a compute ceiling, and
`Changepoint.saturated` publishes when the truncation binds.

**Two counts were kept.** `LAGS` in the Ljung-Box test and `WARMUP` in `paired`
are about the innovation *sequence* and the convex hull's point count, neither
of which is a horizon. The test for autocorrelation in a sequence of
innovations is a statement about that sequence; a detector needing twenty points
before it fires is a statement about the hull.

So the rule is not "no integers". It is:

> A count is right only when the question is about the sequence. If the question
> is about the market, it is a duration, and `coverage` converts it.

### And `saturated` is why the first version of the fix was wrong

The flag was first written as "mass sits at the last component", which is True
on any quiet series - with no change to find, the posterior concentrates on the
*longest* run length it holds, truncation or not. It needs both conditions: the
component list has reached the cap **and** mass is at the edge. The test caught
it on the first run, which is the argument for writing the assertion before
believing the property.
