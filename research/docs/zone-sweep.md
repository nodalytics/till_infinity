# Sweeping the zone rule: nothing moves, and the one thing that did was noise

**Measured 2026-10-07**, asked for as "test different parameters". The rule is
[`zone-rules.md`](zone-rules.md); the code is
[`zone_sweep.py`](../ideas/zone_sweep.py), the table `.data/zsweep4/sweep.csv`.
Twenty-four arms, each tunable moved on its own around the desk's setting, on the
sixteen instruments the rule was developed on - twelve FX pairs, gold, silver,
BTC and ETH - at 4h and 1d.

**This is a development-set sweep and it selects nothing.** 135 cells, so at a
90% interval about fourteen clear zero by chance; twenty-four do, and
**twenty-three of those twenty-four are negative**. Read it for shape, not for a
maximum.

> Run twice: once before the freshness correction (`FRESH`, no bar may trade back
> into the band between the displacement and the setup being known) and once
> after. The correction removes six trades of 334 and no figure here moves by
> more than 0.01R. The numbers below are the corrected run.

## The base rule, in full

| iv | trigger | n | long | win | R | 90% interval | coin | at market | flipped |
|---|---|---:|---:|---:|---:|---|---:|---:|---:|
| 1d | touch | 144 | 51% | 29% | -0.104 | [-0.397, +0.231] | +0.055 | -0.778 | +0.735 |
| 1d | pin | 41 | 49% | 54% | **+0.211** | [-0.157, +0.634] | +0.022 | -0.073 | -0.186 |
| 1d | wick | 75 | 52% | 48% | +0.087 | [-0.192, +0.400] | +0.030 | -0.064 | +0.071 |
| 4h | touch | 328 | 59% | 30% | -0.005 | [-0.176, +0.167] | +0.100 | -0.779 | +1.145 |
| 4h | pin | 86 | 62% | 33% | **-0.368** | [-0.558, -0.168] | -0.266 | -0.415 | +0.173 |
| 4h | wick | 153 | 58% | 36% | -0.149 | [-0.337, +0.050] | -0.028 | -0.197 | -0.033 |

**Exactly one cell of 135 is positive with its interval clear of zero**:
`origin_small` at 1d `pin`, +0.567 [+0.033, +1.220], on **23 trades**. One cell,
the smallest population in its column, from looking 135 times.

## The strong displacement is a no-op

The desk asked for the strong form - the second candle closing past the first's
whole range - in place of the weak one. It changes almost nothing:

| | n | R | win |
|---|---:|---:|---:|
| strong (`PUSH_STRONG=1`), 4h touch | 328 | -0.005 | 29.6% |
| weak (`PUSH_STRONG=0`), 4h touch | 329 | -0.003 | 29.6% |

**One trade in 329.** At a 70% body floor a candle that closes past the previous
*close* has nearly always closed past its *high* too, so the two forms select the
same population. The distinction only had room to matter at a looser body floor,
where the first build measured it - as a *filter*, on the 84%-long population -
so that earlier reading ("the strong form is worse than the weak one") should be
discarded rather than reversed.

## The lookback breaks the one positive cell

`OB_BACK` - the desk's "check backward too for more info" - lets the scan walk
back from the impulse until it finds a bar that passes the zone tests. It can
only **add** setups; it cannot remove one that already qualified.

| | 4h touch n | 4h touch R | 4h pin R | 1d pin n | **1d pin R** |
|---|---:|---:|---:|---:|---:|
| `OB_BACK` 0 | 328 | -0.005 | -0.368 | 41 | **+0.211** |
| `OB_BACK` 1 | 429 | +0.001 | -0.341 | 58 | -0.006 |
| `OB_BACK` 3 | 534 | -0.006 | -0.249 | 91 | -0.075 |
| `OB_BACK` 5 | 603 | +0.034 | -0.196 | 101 | **-0.089** |

The 4h figures do not move - and 4h `pin`, the worst cell in the table, improves
steadily as the population grows, which is what a sampling artefact does when you
dilute it. The **1d `pin` result goes from +0.211 to -0.089 as its population
goes 41 to 101**.

That is the cheapest available test of a small positive cell: widen the
population along an axis that cannot remove the trades you already have. It
failed. Those 41 trades were a favourable subset of a rule that is flat.

## Every parameter is a plateau

Across all twenty-four arms, with no confirmation:

| | min | median | max |
|---|---:|---:|---:|
| 4h touch | -0.550 | **-0.005** | +0.862 |
| 1d touch | -0.672 | -0.133 | +0.154 |

Both extremes are the smallest populations in the sweep (`push_n3` n=37,
`push_n4` n=2). Nothing in the middle moves the result: `OB_LOOKBACK` 10 against
40, `OB_MINLEG` 0 against 3, the band body-high against wick-high, the clip on or
off, the window 12 bars or 36, the hold 5 days or 15 - each lands within 0.1R of
the base.

That is the useful finding. **The zone rule's parameters are not where its result
lives.** A rule whose answer is the same from `OB_LOOKBACK` 10 to 40 is not being
tuned - and a sweep that cannot move it cannot have found its result by tuning
either.

Two arms look like exceptions and are not. `push_body_80` is +0.168 at 4h and
**-0.475** at 1d; `origin_colour` is +0.334 at 4h and **-0.425** at 1d. Opposite
signs across timeframes on 104 and 74 trades is what noise looks like when it is
given two chances.

## The confirmation splits clean across timeframes

The one consistent structure in the table, and it points both ways:

| | pin minus touch | positive in |
|---|---:|---:|
| **4h** | **-0.341** | **0 of 22 arms** |
| **1d** | **+0.271** | **20 of 22 arms** |

`wick`, the looser reading, sits between them both times (-0.107 and +0.164), as
a superset of `pin` should.

Waiting for a candlestick confirmation **costs about a third of an R at 4h and
pays about a quarter at 1d**, in essentially every parameter arm. Arms share most
of their trades, so this is two observations rather than forty-four - but two
that survive every change made to the rule around them.

The win rates say what it is doing: at 1d, `pin` wins 53.7% against `touch`'s
28.5%. The confirmation is not finding better trades, it is **refusing the ones
price went straight through** - worth more on a daily bar, where the next bar is
the whole day, than on a 4h bar, where waiting gives up a quarter of the move.

**But the lookback arms break the 1d half of it** (above), so what is left is the
4h half: confirmation at 4h is reliably expensive. That is a real and usable
negative.

## Freshness, and the reading that was not meant

`FRESH` - the zone untested between the displacement and the setup being known -
costs six trades of 334 and moves nothing. The hole it closes was real and rarely
fell through.

`QUIET` - the band sitting where price had not lately been working - is a
different claim and a dead end at these settings: 328 trades become **71** at 20
bars and the result gets worse (-0.005 to -0.162). A filter that removes 78% of a
flat population and makes it worse is removing signal or nothing; either way it
is not what "fresh" meant.

## The thing that does move, and why it is probably not an edge

`flip` - the same fills and stops, entered at market, on the **opposite** side -
is positive in every arm and both timeframes, median **+1.05R** at 4h and
**+0.74R** at 1d, intervals clear of zero in every `touch` cell.

The column beside it explains most of that. `straight`, the *same* side at
market, is **-0.78R** across the board while the real limit entry is -0.005R.
Entering at market once price has reached the zone is three-quarters of an R
worse than resting a limit at its edge, and `flip` is `straight` reflected.

What survives the reflection is small and points where everything else this week
has pointed: **price that reaches a zone tends to keep going through it**. The
band is not holding - which matches the measured hold rate of ~50% at 1d and ~46%
at 4h in [`zone-approach.md`](zone-approach.md), and
[`magnet.md`](../../docs/magnet.md) on levels not being magnets.

## What is left

* **4h: confirmation is expensive**, reliably, across every arm. Negative, usable.
* **1d: nothing survives the lookback.** The only positive cell in the table is
  one of 135 at n=23.
* The held-out instruments produced about a hundred zones in total and no cell
  reached thirty trades, so they cannot confirm anything at these settings. What
  this needs is **more time, not more instruments**.
* Nothing here should be traded.
