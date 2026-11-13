# Carver's framework on five instruments: buy-and-hold beat it

Run: `python research/ideas/carver.py`

**Measured 2026-11-13**, on **eight years** of the broker's own daily closes - EURUSD, GBPUSD,
XAUUSD, USDJPY and AUDUSD, 2018-10 to 2026-11, aggregated from 600,000 five-minute bars a symbol.

The reason for running it: [`dual-engine-confluence.md`](dual-engine-confluence.md) measured that a
break-even stop, a partial at 2R, an ATR trail and a 48-hour time stop together cost about **0.2R a
trade on a direction-free entry** - twenty-five times what the spread costs. That is a finding about
*management*, and Carver's framework is the obvious alternative because it does not manage a trade
at all: no stop, no target, no partial, no time limit, just a continuous position sized as a
forecast over a volatility estimate.

| question | answer |
|---|---|
| does the framework make money here? | yes, net **+$208,507** across five instruments, mean Sharpe **+0.15** |
| does it beat buying and holding? | **no.** Hold made **+$299,742** at mean Sharpe **+0.29**, with a fiftieth of the costs |
| are its costs sane? | **yes** - 5.1% of gross, well inside Carver's one-third speed limit |
| does it beat a shuffled market? | not clearly - gold's +0.69 sits **under** its own shuffled best of +0.84 |
| is this a fair test of Carver? | **no** - see the envelope section. Five correlated instruments is not the portfolio the framework is built for |

## What was run

Carver's own machinery, nothing borrowed from the dual-engine work: exponentially weighted
volatility (36-day span, price units), **EWMAC** forecasts at his six canonical speeds (2,8) through
(64,256), each scaled to an average absolute value of 10 and capped at ±20, averaged, re-scaled,
and turned into a position by `capital × daily_vol_target × (forecast/10) / vol_price` at a 20%
annualised target, with his 10% position-inertia rule and costs charged per unit traded at each
instrument's measured median spread.

Two choices are mine and are stated in the module: **the forecast scalars are estimated on an
expanding window rather than quoted**, because putting half-remembered constants from a book into a
backtest is how a result ends up resting on a misremembered number; and **there is no stop**,
because the whole point of running this was to measure management without an exit stack.

## The result

| instrument | rule | hold | shuffled mean | shuffled best | rule costs / gross |
|---|---|---|---|---|---|
| EURUSD | +0.04 | -0.09 | -0.29 | +0.39 | 19.6% |
| GBPUSD | -0.04 | -0.05 | -0.28 | +0.12 | n/a (gross<=0) |
| XAUUSD | **+0.69** | **+1.07** | +0.28 | +0.84 | 1.7% |
| USDJPY | **+0.25** | **+0.64** | +0.10 | +0.46 | 2.9% |
| AUDUSD | -0.19 | -0.11 | -0.28 | +0.65 | n/a (gross<=0) |
| **portfolio** | **+0.15** | **+0.29** | -0.10 | +0.84 | **5.1%** |

Sharpe, annualised, net of costs.

**Buy and hold beat it, at the same volatility target, on the same instruments, over the same
window, paying $1,439 of costs against $11,127.** The entire gross came from two instruments - gold
and the yen - and holding captured more of both: +1.07 against +0.69 on gold, +0.64 against +0.25
on USDJPY. On the three that did not trend, the framework lost on two and made +0.04 on the third.

The shuffled control adds the rest. Block-shuffling each instrument's own daily moves - keeping the
distribution and the within-block clustering, destroying the trend - and running the identical
system twenty times gives gold a mean of +0.28 and a **best of +0.84**. The real gold run scored
**+0.69**. A result that its own shuffled market beats in 20 draws is not evidence of trend, and
gold was the strongest instrument in the set.

## Why the flip is reported and means nothing

For a linear continuous rule, reversing the forecast negates the position exactly, so
`gross_flip = -gross_rule` by construction - EURUSD came out +8,734 against -8,734, to the dollar.
"Beats its own flip" therefore reduces to "gross is positive" and carries no information. It is in
the output because it would otherwise look like an omission.

This is worth recording because the flip *was* informative for the discrete dual-engine rule, where
a stop, a target and a time limit break the symmetry. **The same null is load-bearing for one system
and decoration for another**, which is not obvious until the arithmetic is written down.

## The envelope, and why this is not a refutation of Carver

**Five instruments is not the portfolio this framework is built for.** Carver's systems run thirty
to fifty futures across equities, bonds, rates, commodities and FX, and the diversification
multiplier exists precisely because combining weakly correlated forecasts is where the Sharpe comes
from. Four of the five here are USD pairs; the fifth is gold. That is close to one bet, and a
framework whose central claim is about diversification cannot be tested on an undiversified book.

So the honest statement is: **on this desk's five instruments, over this window, the apparatus did
not beat holding.** It is not "Carver does not work". What it does establish is that adopting the
machinery here, on this instrument set, would not have paid - and that is the question that was
asked.

Three further limits, each of which would flatter the result rather than the opposite:

* **No margin constraint and no bankruptcy.** The simulation lets equity go negative, which is how
  the gold flip prints a 208% drawdown. The rule arms never go negative, but their drawdowns -
  43.9%, 48.4%, 50.6%, 32.1%, **80.5%** - are far above what a 20% volatility target implies, and
  a real account would have been margin-called out of AUDUSD before the recovery.
* **One regime.** 2018-2026 contains a long gold bull and a long yen depreciation. Both instruments
  that carried the result were trending for most of the sample.
* **Daily closes from a 5-minute series**, by calendar day rather than session, so a weekend is
  absent rather than gapped and no roll or carry is modelled.

## What to take from it

* **The speed limit is adoptable and this desk lacks it.** "Costs at or under a third of gross
  profit" is a threshold, where this repository has been eyeballing cost as a fraction of R. It also
  reframes the dual-engine finding usefully: 0.008R a trade sounds free until it is multiplied by
  713 trades a year against no gross profit at all. **Cost is a rate against an edge, not a number
  per trade.**
* **Continuous sizing did not fix the management problem here**, but it did not reproduce it
  either. The dual-engine exit stack destroyed 0.2R a trade; this framework's costs were 5.1% of
  gross. The machinery is cheap. It simply had no forecast worth sizing on these five.
* **The next test, if this is pursued, is a wider instrument set** - which is the one thing that
  would make it a fair trial, and which this store cannot currently supply.
