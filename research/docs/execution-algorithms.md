# Execution algorithms: the seam is real, the prize is 0.097 of a spread

**Measured 2026-11-10** on the broker's own order and deal history, 2026-10-01
to 2026-11-11. Code: [`harness/slippage.py`](../harness/slippage.py). Asked
because Nautilus separates `Strategy` from `ExecAlgorithm` and this desk has
never used the second, which is a real gap worth either filling or closing with
a number.

**The number: on the current book a market entry pays `+0.097` of its spread in
slippage** (21 fills, se 0.029). A working algorithm therefore has about a
tenth of a spread to win, and loses a whole one every time it fails to fill and
has to chase. That is the verdict; the rest of this file is why, and what would
overturn it.

## The seam exists and is unused

`nautilus_trader.execution.algorithm.ExecAlgorithm` is a first-class citizen
beside `Strategy` - the node clears both on dispose - and an order is routed to
one by `exec_algorithm_id` on the order itself, so it is venue-agnostic. The
framework ships exactly **one** example, `examples/algorithms/twap.py`.

`ExecAlgorithm` and `exec_algorithm` appear **nowhere** in `till_infinity/` or
`tests/`. The seam has never been used here.

## Two of the three classic algorithms cannot be built on this venue

**VWAP is impossible, and this is measured rather than argued.** The venue
sends no depth and `real_volume` is 0; `adapters/mt5/data.py` reads
`tick_volume or real_volume or 0.0`, so a bar's "volume" is a **quote count**.
`no-order-flow-and-no-real-volume` records this. A volume-participation
algorithm has no volume to participate in.

**TWAP trades market impact for spread, and there is no impact to trade.**
Slicing hides size in a deep book. This desk sends 0.01-0.1 lots to a retail
CFD broker, far below any size that moves a quote, so slicing does not reduce
impact it is not causing - it pays the spread once per child order. On the
instruments `exotic-spreads-are-a-whole-bar-range` costed at **0.40 to 0.97 of
a whole bar range** round trip, that is not a marginal loss.

**Implementation shortfall is the only one of the three that fits**, and it is
the one the measurement below prices.

## The measurement

Positive is adverse: a buy filled above what it asked, or a sell below.
Reported as a share of each symbol's own spread, because a point is not
comparable across instruments - `Crash 500 Index` and `EURUSD` differ by four
orders of magnitude and a pooled mean in points is meaningless.

The two engines are separate arms. Pooling them would attribute the retired
engine's execution to the current one.

| arm | fills | instruments | per-fill mean | se | per-instrument median |
| --- | ---: | ---: | ---: | ---: | ---: |
| **Nautilus** (from 2026-10-31) | 21 | 9 | **+0.097** | 0.029 | +0.063 |
| pre-Nautilus | 1,320 | 40 | +0.428 | 0.059 | +0.155 |

**Under ~100 fills the prior is noise, and the Nautilus arm has 21.** It is
reported because its direction agrees with the much larger pre-Nautilus arm on
the same instrument classes, not because 21 settles anything.

### Where it is small, and it is almost everywhere we trade

Per instrument, Nautilus arm: `EURUSD +0.031` (n=8), `GBPUSD +0.056` (n=3),
`USDCAD +0.150` (n=4), `XAGUSD +0.000` (n=1). The pre-Nautilus arm agrees on
the majors with a usable sample: `EURUSD +0.047` (n=16), `EURJPY +0.020`
(n=17), `AUDUSD +0.036`, `USDCAD +0.086`, `GBPUSD +0.106`, `USDJPY +0.129`.

Indices sit higher but still inside a fifth of a spread: `US SP 500 +0.160`
(n=64), `UK 100 +0.149` (n=87), `Germany 40 +0.168` (n=86), `France 40 +0.046`
(n=56).

### Where it is large, and we do not trade it

| instrument | fills | mean |
| --- | ---: | ---: |
| Crash 300 Index | 20 | **+2.102** spreads |
| Crash 500 Index | 137 | **+1.984** spreads |
| Jump 25 Index | 105 | +0.907 spreads |
| BTCUSD | 49 | +0.384 spreads |

The Deriv spike synthetics pay **one to two whole spreads** on a market entry.
That is consistent with `generators.md` finding 10-19R on the spike side of
Boom and Crash, and with `DEFAULT_STOP_OVERSHOOT` existing at all.

**None of Crash 300, Crash 500 or Jump 25 is in the deployed `TRADING_SYMBOLS`.**
The instruments where a working algorithm would pay for itself are precisely
the ones not being traded.

### What this does not establish

**The spread is the one read at query time, not at fill time.** It varies -
`seasonality-belongs-on-q` measured FX intraday volatility peaking 14-15 UTC at
3x - so `mean/spread` is indicative. A ratio near a decision boundary needs
re-measuring against the spread each fill actually faced.

**`ETHUSD` is excluded from any reading.** 16 fills with a standard deviation
of 42,038 points on a mean of -1,910: one outlier is the entire statistic.

**Pending orders are a different quantity and are not evidence here.** A limit
fills at its price or better by construction, so its slippage is favourable
almost everywhere (`CHFJPY -1.52` points, `EURUSD -0.39`, `Germany 40 -57.4`)
and says nothing about what a market order costs.

## The architectural reason not to move entries, which outranks the number

**On this desk the entry mechanism is part of the rule, not an execution
detail.** `strategies/leaves.py` states it: `smc_bos_c_L50|M15|N20|time` "says
'at market, on the open of the first minute after the M15 close', so a rest at
a named price and a wait for an arrival are both a different rule" - which is
why that rule is registered for `edge` alone while `statespace-surprise` is
registered for three entries, and why `desks.build` composes rule x entry x
exit rather than treating the entry as configuration.

Moving entry behind an `ExecAlgorithm` would let the execution layer reshape
the thing that was measured. CLAUDE.md puts one requirement above all others -
that the thing which measured an idea and the thing which trades it are the
same thing - and every expensive mistake on this desk has been a version of
those two drifting apart.

## What the seam would be right for

The **thesis-neutral** half of order working, which is currently spread across
two places: retrying a retryable retcode (`RETRYABLE_RETCODES`, and the
inflight-retry path that produced the `UNKNOWN` rejections), and completing a
partial fill. Those are not trading decisions.

The honest counter is that most of it is adapter-shaped anyway, because MT5
carries stops as fields on a position rather than as orders and fills FOK - so
it would move from one correct place to another, for no measured gain.

## Verdict, and the condition that would overturn it

**Do not build one.** At `+0.097` of a spread there is roughly a tenth of a
spread to win per entry, and a limit-with-fallback pays a full spread whenever
it misses and chases. Break-even needs a fill rate above about 90% before any
of the gain survives, which is an assumption and not a measurement.

Three things would change the answer, in order of likelihood:

1. **A synthetic re-enters the book.** Crash 300 and Crash 500 at +2.1 and
   +2.0 spreads make a resting entry worth real money. `research/docs/` should
   be re-read first: `synthetics-are-a-poor-tail-control` and
   `a-control-is-only-for-a-named-property` are about these instruments.
2. **The Nautilus arm reaches a usable sample and disagrees.** 21 fills is
   noise; re-run `harness/slippage.py` at a few hundred.
3. **Size grows enough to matter.** At 0.01-0.1 lots there is no impact. The
   measurement is of a *venue*, not of a market, and it would need redoing at
   any size where the broker's own fill behaviour changes.
