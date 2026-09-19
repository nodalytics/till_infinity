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

## The one asymmetry worth acting on - and it was not an instrument at all

**Withdrawn. It is `thesis-only` wearing an instrument's name**, and the
investigation is kept because the shape is one this project keeps repeating.

The claim below was that Boom loses because a level strategy stands in front of
an uncallable spike. Three measurements, in the order they were run:

**1. The spike direction, live.** Split by side, the hypothesis needs *opposite*
signs on the two families - the spike runs against a Boom sell and against a
Crash buy:

    boom   buy  n=25  -0.394R     boom  sell n=23  -0.367R   <- spike against
    crash  buy  n=10  +0.314R <-  crash sell n=14  -0.195R

Boom loses on both sides alike, and on Crash the side the spike runs against is
the side that *wins*. Wrong direction, twice.

**2. The spike direction, replayed.** 1,811 published level calls on the six
Boom and Crash feeds, walked forward on 1m bars with spread charged
(`research/harness/spikeside.py`):

| family | side | n | mean R | |
| --- | --- | --- | --- | --- |
| boom | buy | 433 | +0.545 | |
| boom | sell | 266 | +0.408 | spike against |
| crash | buy | 442 | +0.643 | spike against |
| crash | sell | 670 | +0.512 | |

`buy - sell` is **+0.138R on boom and +0.131R on crash** - the *same* sign on
both. The hypothesis requires opposite signs, so this is a general long bias in
the replay and not a spike effect. On Boom the gap also reverses to -0.025R in
the verify half.

**3. Entry slippage**, in units of each trade's own risk:

| family | n | mean | median | p90 |
| --- | --- | --- | --- | --- |
| jump | 8 | +0.031 | +0.001 | +0.207 |
| other | 188 | +0.015 | +0.000 | +0.069 |
| boom | 49 | **+0.000** | +0.000 | **+0.004** |

Boom fills are the *cleanest on the book*. Not fill quality either.

### What it actually was

| family | strategy | n | mean R |
| --- | --- | --- | --- |
| boom | **thesis-only** | **36** | **-0.595** |
| boom | sweep-aware | 4 | **+1.134** |
| boom | confluence-scalp | 4 | -0.433 |
| crash | thesis-only | 18 | +0.111 |

**36 of Boom's 48 closes are `thesis-only`, at -0.595R** - which is exactly the
figure the table below reports for Boom 1000, because that strategy *is* the
sample. `sweep-aware` on the same instrument runs +1.134R.

`thesis-only` is -441 across the whole book and has been out of the strategy
list since **2026-09-09**. So the bleed stopped before it was investigated, and
there is nothing to gate: an instrument cut that mixes strategies is a
composition, and this is the **fourth** time on this project that a pooled
figure has reversed on being conditioned - after `aligning.md`, `forecasting.md`
and `trapping.md`.

The rule that would have caught it earlier is the one those three already
imply: **before attributing a loss to an instrument, cut it by the strategy that
placed the trades.**

## The asymmetry as it was first written

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
