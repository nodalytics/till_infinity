# What it costs to trade, and why that ends the barrier programme

Measured 2026-09-21 by `research/harness/spread_cost.py` and `research/harness/net_edge.py`,
from the broker's own symbol specifications and 65,000 hourly bars per instrument.

This is the most consequential measurement in this research, and it does not report a
strategy. It reports that **every barrier study in this repository has been measuring a
quantity that cannot be collected**, and by a margin several times larger than any effect
any of those studies found.

## The question it was set up to answer

`jump_odds.py` produced the one large structural deviation in months of work: on Boom,
shorts beat the driftless fair-odds line by +4.1 points at a reward-to-risk of one, with
Crash mirroring it on longs and FX flat. Gross expectancy is

    p (1 + r) - 1    with p = 0.541, r = 1  ->  +0.082 R

The standing objection was cost, assumed at 0.03 R and never measured. At a
reward-to-risk of one the entire edge is 8.2% of one stop, so the question was whether
the real cost cleared that.

It does, twice over, and then a third cost nobody had priced killed it anyway.

## Spread: settled, and smaller than assumed

`history.py` was writing only time, open, high, low, close and volume, so the saved files
could not answer this at all - the bridge returns a `spread` on every bar and it was
being discarded on download. Read directly from 20,000 hourly bars per symbol:

| instrument | median spread | as share of 1 TR | on the loudest 5% of bars |
|---|---|---|---|
| Boom 1000 | 0.174 | **0.004** | 0.004 |
| Crash 1000 | 0.054 | **0.004** | 0.004 |
| Boom 900 | 0.104 | 0.004 | 0.004 |
| XAUUSD | 0.090 | 0.013 | 0.021 |
| EURUSD | 0.2 pip | 0.020 | 0.020 |

Two things worth keeping. The assumed 0.03 R was **seven times too pessimistic** for the
synthetics, and counter-intuitively the synthetics are *cheaper* than FX in risk-adjusted
terms because their hourly range is enormous relative to their spread.

And the spread **does not widen on spike bars** - the median on the widest 5% of bars is
the same 0.004 as the median everywhere. That was a real concern, since the Boom trade
lives in exactly that population, and it is now closed.

## Financing: an order of magnitude larger, and nearly reported wrong

The bridge reports `swap_mode 5` on the synthetics. That is
`SYMBOL_SWAP_MODE_INTEREST_CURRENT`, where the swap figure is an **annual percentage of
notional**, not a number of points. The first version of `spread_cost.py` guarded against
converting an unrecognised mode and returned nothing rather than a number; had it treated
mode 5 as points it would have reported a cost about a thousandth of the truth and the
error would have looked entirely plausible.

Boom 1000 charges 36% a year and Crash 1000 18%, and **both sides pay the same**, so no
direction earns the carry back. Converting at the measured true range:

| instrument | annual | per day | in R per day | hours 0.082 R buys |
|---|---|---|---|---|
| Boom 1000 | 36% | 0.0986% | 0.321 R | **6.1** |
| Crash 1000 | 18% | 0.0493% | 0.161 R | **12.2** |

`jump_odds.py` allowed 192 bars - eight days - to resolve. Had trades actually lasted
that long the result would have been inverted many times over. They do not: the mean
holding time at a reward-to-risk of one is **2.7 hours**, so carry costs 0.036 R and the
trade still nets +0.041 R.

At that point the result appeared to survive. It does not.

## The contradiction that exposed the real problem

Three facts could not all be innocent:

1. shorting Boom 1000 wins 54.1% of one-to-one barrier bets over these bars;
2. at roughly six trades a day, +0.041 R a trade compounds to about **+32% a year** of
   notional;
3. **Boom 1000 rose 64.9% over the same 7.43 years** - and Crash, Boom 500 and Crash 500
   all drift the wrong way for their own supposed edge too.

A strategy cannot print 32% a year shorting an instrument that went up, measured on the
very path it went up along. Something in the accounting had to be wrong, and the search
for it found an assumption that every barrier study here has been making silently.

## The assumption: that a stop fills at the stop price

`patterns.py`, `imbalance.py`, `premium_discount.py`, `displacement.py`, `smc.py`,
`regression_channel.py`, `jump_odds.py` and `changepoint.py` all resolve a trade by asking
whether a bar's extreme reached the stop, and then charge the loss as exactly 1 R. That is
a modelling choice, and on a series built from instantaneous spikes it is a bad one: a
spike does not walk up to a short's stop and halt there.

Measuring how far past the stop the bar actually reached, at a reward-to-risk of one:

| instrument | gross edge | worst-case stop overshoot |
|---|---|---|
| Boom 1000 | +0.081 | 0.236 |
| Crash 1000 | +0.080 | 0.239 |
| Boom 500 | +0.050 | 0.213 |
| XAUUSD | -0.012 | **0.286** |
| EURUSD | -0.009 | **0.268** |
| Volatility 75 | +0.000 | 0.166 |

**The problem is not confined to the spike instruments - FX is worse.** It also grows with
the reward-to-risk ratio, reaching 0.49 R on EURUSD at a ratio of four, because a wider
target means longer in the market and more chances to meet an extreme bar.

Charging it turns every positive cell negative: Boom 1000 goes from +0.041 R to **-0.195
R**, Crash 1000 from +0.058 R to -0.181 R. And that accounting now agrees with the price
series, which is the point of it.

## What is actually known, stated as a bracket

The bar extreme is the **worst** price printed in that hour, and a stop fills somewhere
between the stop and that extreme, so 0.24 R is an upper bound and not an estimate.
Narrowing it needs tick data, which these files are not.

The lower bound comes from the price path and is the more interesting half: for the
strategy not to contradict the series it was measured on, effective slippage must be at
least enough to cancel +0.041 R a trade, which is roughly **0.04 R**.

    0.04 R  <=  true slippage  <=  0.24 R        against a gross edge of 0.081 R

At the bottom of that range half the edge survives. At the top it is gone three times
over. **No barrier effect measured anywhere in this repository - the largest was +4.1
points, or 0.08 R - exceeds the uncertainty in its own exit price.**

## Live trades point the same way, from a different direction

[excursion.md](excursion.md) measured adverse excursion on 71 fully-tracked live closes on
2026-09-04, for a book running stops at 1.0 R. Losers recorded a p90 adverse excursion of
**1.267 R and a maximum of 1.434 R**.

A trade with a 1.0 R stop cannot record 1.27 R of adverse excursion if it exits at its
stop price. Those readings are above the stop, and the excess - roughly 0.27 R at p90 -
lands inside the bracket this document derives from bar data, at the upper end of it.

This is **live fill data rather than an estimate from bars**, so it is better evidence than
anything here, and it was collected for an unrelated purpose. It should be treated as
corroboration and not proof: the figures could also arise from stops being moved or
trailed during the trade, and confirming that needs the journal's per-ticket history rather
than its summary. That check is worth doing and has not been done.

## What this means for the rest of the work

This does not make the earlier nulls wrong. Gaps, chart patterns, premium/discount,
topology, motif clustering and regression channels all came back at or below the
fair-odds line, and a cost correction only pushes them further down. Those conclusions
harden.

It makes the *positive* results unreachable rather than false. The Boom/Crash asymmetry is
still there in the data and still has a structural explanation; it simply cannot be
collected with a stop, because the same spikes that create it destroy the exit.

Three things follow, in order of value:

* **Stop-free formulations are the only ones worth testing next.** Time-based exits, or
  positions sized so no stop is needed, do not pay the overshoot. This is a change of
  question, not a refinement of the answer.
* **Tick data would settle the bracket**, and nothing else will. It is the single highest
  value acquisition available.
* **Every future barrier harness must charge the overshoot**, which `net_edge.py` now does
  and the others do not. Until they do, their positive cells should be read as upper
  bounds rather than results.

## Provenance

* `research/harness/spread_cost.py` - reads `spread` live from the bridge, converts by the
  symbol's point size, reports quiet, 99th-percentile and loud-bar spread, and refuses to
  convert a swap mode it does not recognise.
* `research/harness/net_edge.py` - re-runs the `jump_odds.py` trades recording holding
  time and stop overshoot, and charges spread, carry and slippage against the gross edge.
* Swap figures read from the bridge's `symbols/info`: `swap_mode`, `swap_long`,
  `swap_short`. Both sides negative and equal on the synthetics.
