# The Boom spike is memoryless, so nothing can call it

Deriv publishes the rule in the instrument's own subtitle: *"On average 1 spike
occurs in the price series every 500 ticks."* That is a stated hazard, which
made these the one place on this book where a real-time trap predictor could be
scored against a ground truth - and the reason to check the hazard first was
that a flat one makes prediction impossible by construction.

Measured 2026-09-08 over 13,673 one-minute bars of `boom_500_index`, 228 hours.

## The spike is visible in data already stored

A spike-up index should have a fat up-leg tail and a tight down-leg, and it
does, unmistakably:

| leg | p50 | p75 | p90 | p95 | p99 | max |
| --- | --- | --- | --- | --- | --- | --- |
| **up** (`high - open`) | 0.00 | 0.00 | 0.91 | 4.60 | 9.52 | 20.80 |
| **down** (`open - low`) | 0.55 | 0.58 | 0.61 | 0.64 | 0.67 | 0.79 |

p99 up over p99 down is **14.15**. Taking a spike as an up-leg beyond three
times the down-leg's p99 finds **1,150 spikes, one every 11.9 minutes** - which
sits between the 8.3 and 16.7 minutes that 500 ticks implies at one and two
seconds a tick. So the feed delivers roughly what the name claims, and 1m bars
resolve it. No tick subscription is needed.

## And the waiting time is memoryless

| | |
| --- | --- |
| mean gap | 11.9 min |
| standard deviation | 11.7 min |
| **coefficient of variation** | **0.99** |
| p10 / median / p90 | 2 / 8 / 28 min |
| min / max | 1 / 119 min |

**A geometric waiting time has a coefficient of variation of exactly 1.00. This
is 0.99.**

That is the whole answer. The gaps are drawn from a memoryless process, so *how
long you have waited tells you nothing about when the next spike comes*. The
hazard is flat at about 1/11.9 per minute whether the last spike was one minute
ago or ninety.

Which is exactly what a correct implementation of "on average 1 spike every 500
ticks" would produce. The venue is not hiding a pattern; it is running the
generator it describes.

## What this kills

* **Predicting a spike.** Not hard, not a modelling problem - impossible from
  the arrival series, because the arrival series contains no information about
  the next arrival. Any model that appears to call one has found the
  implementation, not the process, and `research/null.md`'s framing applies:
  report it as a fact about the generator.
* **Ticks-since-the-last-spike as a feature.** It is the state variable a
  hazard model would need, and here its hazard is constant, so it carries
  nothing.
* **The residual-time argument for Boom and Crash.** `docs/todo.md`'s BOCPD
  entry names its own kill condition - *"if the hazard is flat, residual time is
  a constant and the lookup is the whole answer"* - and on these instruments it
  is flat to two decimal places. Residual time here is 11.9 minutes, always.

## What survives, and it is arithmetic rather than a model

The down-leg table is the striking half and it was not what was being looked
for. **The grind is nearly deterministic**: p50 0.55, p99 0.67, max 0.79 - the
whole distribution inside a 0.24 band. Boom falls by almost exactly the same
amount every minute, then jumps.

So the instrument is fully described by two published numbers and one measured
one: a constant drift down, a memoryless arrival at a known rate, and a spike
size distribution. **The expected value of any position is then a calculation,
not a forecast** - grind collected against the chance of a spike times its
size - and it needs no model at all.

That is worth doing precisely because it explains the loss already on the book:
the spike indices are 20% of trades and 42% of the loss at -5.33 a trade
(`docs/todo.md`). If the arithmetic says a short on Boom is negative-expectancy
before costs, that is the finding, and it needs no prediction to act on.

## What was not measured

Only `boom_500_index` completed - the query is a full scan of a 19GB store per
feed and the other two had not finished. `boom_1000_index` should show the same
shape at half the rate and `crash_1000_index` the mirror; if either does not,
that is the interesting result and this document is wrong about the family
rather than about Boom 500.
