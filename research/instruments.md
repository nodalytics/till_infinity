# What each instrument actually earns

Asked directly: *"what are those instruments that are losing money badly and the
ones that are gaining"*. From the journal's own outcomes, 392 closes across 44
instruments.

**Net -746.04. Median close -0.96.**

## The headline number is one trade

Volatility 75 Index shows **+617.58** and reads as the book's best instrument by
a wide margin. Here is every close on it:

    -0.86  -29.90  -6.81  +0.27  -0.87  +21.01
    +8.28  +5.22  -11.70  +4.83  +5.48  +622.63   <- no r_multiple recorded

One trade is **+622.63**, opened by `thesis-only`, and it carries no
`r_multiple` at all. Strip it and the instrument is **-5.05** with a mean R of
**-0.028**.

That single row is flattering the whole book's total, and it is the reason
everything below is ranked by **R** rather than by money wherever the sample
allows. `research/harness/strategies.py` makes the same argument: money hides an
execution leak behind position size, and at this sample size one accident
outweighs a hundred ordinary trades.

## Worst, by money

| instrument | n | $ | win | mean R |
| --- | --- | --- | --- | --- |
| XAUUSD | 35 | **-335.33** | 29% | -0.139 |
| Wall Street 30 | 23 | **-235.74** | 26% | -0.196 |
| Boom 1000 Index | 21 | **-217.54** | 14% | **-0.595** |
| Boom 500 Index | 28 | -136.63 | 32% | -0.215 |
| US Small Cap 2000 | 8 | -117.46 | 38% | +0.109 |
| Volatility 10 Index | 22 | -113.06 | 59% | -0.107 |
| **GBPJPY** | 4 | -77.05 | **0%** | **-1.000** |
| Volatility 50 Index | 13 | -54.48 | 31% | -0.240 |
| US SP 500 | 4 | -54.01 | 25% | -0.571 |
| US Tech 100 | 13 | -53.43 | 38% | +0.065 |

**GBPJPY is four trades, zero wins, and a mean R of exactly -1.000** — every one
a full stop, nothing partial, nothing trailed. Four is not a sample, but -1.000
is not a distribution either: it says the exit never acted on any of them.

Note also that `US Small Cap 2000` and `US Tech 100` are **positive in R and
negative in money**. That is position sizing, not selection, and it is the
clearest argument in the table for reading the R column first.

## Ranked by mean R, with at least eight closes

| instrument | n | mean R |
| --- | --- | --- |
| Boom 1000 Index | 21 | **-0.595** |
| Volatility 50 Index | 12 | -0.240 |
| Boom 500 Index | 27 | -0.215 |
| Wall Street 30 | 12 | -0.196 |
| Step Index | 13 | -0.169 |
| XAUUSD | 9 | -0.139 |
| Volatility 10 Index | 21 | -0.107 |
| Volatility 75 (1s) Index | 10 | -0.071 |
| Volatility 75 Index | 11 | -0.028 |
| Volatility 25 Index | 32 | **+0.033** |
| Crash 1000 Index | 22 | **+0.053** |
| Volatility 100 Index | 10 | **+0.112** |

**Only three instruments with a real sample are positive, and all three
marginally.** Everything else is losing.

## The one asymmetry worth acting on

The Boom family is the worst thing on the book, and its mirror is not:

| | n | mean R |
| --- | --- | --- |
| Boom 1000 Index | 21 | **-0.595** |
| Boom 500 Index | 27 | **-0.215** |
| Crash 1000 Index | 22 | **+0.053** |

Boom and Crash are the same generator with the sign reversed: Boom grinds down
and spikes up, Crash grinds up and spikes down.
[spiking.md](spiking.md) measured that spike directly — one every 11.9 minutes
on Boom 1000, with a waiting time whose coefficient of variation is 0.99 against
a memoryless process's 1.00, which is to say **nothing can call it**.

A level strategy standing in front of an uncallable spike is the trade this
table is describing, and the asymmetry is the evidence: the same strategies on
the mirror instrument, where the spike runs the other way, are flat rather than
-0.595R.

That is a specific and testable claim — that the loss is the spike direction
against the position, not the instrument — and it is the next thing to measure
rather than a reason to switch anything off today.

## What this does not say

* **392 closes across 44 instruments** is about nine each. Only six instruments
  have twenty or more, and the ranking below those is noise with names on it.
* **It mixes strategies.** `thesis-only` alone is -441 across the book and has
  been out of the strategy list since 2026-09-09, so some of what looks like an
  instrument problem is a strategy that no longer runs. The per-strategy split
  is in [giveback.md](giveback.md).
* **It mixes regimes and sizes.** None of these are matched controls, and the
  book changed several times over the window.
