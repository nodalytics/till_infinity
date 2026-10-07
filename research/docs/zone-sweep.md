# Sweeping the zone rule: nothing moves, and one thing does

**Measured 2026-10-07**, asked for as "test different parameters". The rule is
[`zone-rules.md`](zone-rules.md); the code is
[`zone_sweep.py`](../ideas/zone_sweep.py), the table is `.data/zsweep/sweep.csv`.
Twenty-three arms, each one tunable moved on its own around the desk's setting,
on the sixteen instruments the rule was developed on - twelve FX pairs, gold,
silver, BTC and ETH - at 4h and 1d.

**This is a development-set sweep and it selects nothing.** 138 cells, so at a
90% interval about fourteen clear zero by chance; twenty-eight do. Read it for
shape, not for a maximum.

## What the sweep says

### The strong displacement is a no-op

The desk asked for the strong form - the second candle closing past the first's
whole range - in place of the weak one. It changes almost nothing:

| | n | R | win |
|---|---:|---:|---:|
| strong (`PUSH_STRONG=1`), 4h touch | 334 | -0.013 | 29.3% |
| weak (`PUSH_STRONG=0`), 4h touch | 335 | -0.011 | 29.6% |

**One trade in 335.** At a 70% body floor a candle that closes past the previous
*close* has nearly always closed past its *high* as well, so the two forms select
the same population. The distinction only had room to matter at a looser body
floor, where the first build measured it - and measured it as a *filter* on the
84%-long population, which is why that earlier reading ("the strong form is worse
than the weak one") should be discarded rather than reversed.

### Every parameter is a plateau

Across all twenty-three arms, at 4h, with no confirmation:

| | min | median | max |
|---|---:|---:|---:|
| R | -0.550 | **-0.018** | +0.282 |

and at 1d, -0.445 / -0.139 / +0.154. The two extremes are the smallest
populations in the sweep (`push_n3`, n=37; `origin_colour`, n=77). Nothing in
the middle of the range moves the result: `OB_LOOKBACK` 10 against 40,
`OB_MINLEG` 0 against 3, the band drawn body-high against wick-high, the clip on
or off, the window 12 bars or 36, the hold 5 days or 15 - every one of them lands
within 0.1R of the base.

That is the useful finding. **The zone rule's parameters are not where its
result lives.** A rule whose answer is the same from `OB_LOOKBACK` 10 to 40 is
not being tuned, and a sweep that cannot move it cannot be accused of having
found the result by tuning either.

### The confirmation splits clean across timeframes

The one consistent structure in the whole table, and it points both ways:

| | pin minus touch | positive in |
|---|---:|---:|
| **4h** | **-0.339** | **0 of 23 arms** |
| **1d** | **+0.294** | **22 of 23 arms** |

`wick`, the looser reading, sits between them both times (-0.131 and +0.183), as
a superset of `pin` should.

So waiting for a candlestick confirmation **costs about a third of an R at 4h and
pays about a third at 1d**, and it does so in essentially every parameter arm.
Arms share most of their trades, so this is two observations and not forty-six -
but it is two observations that survive every change made to the rule around
them, and the sign flip is not something a single sample noise story explains
comfortably.

Read against the win rates it makes sense: at 1d, `pin` wins 53.5% of the time
against `touch`'s 28.4%. The confirmation is not finding better trades, it is
**refusing the ones where price went straight through** - which is worth more on
a daily bar, where the next bar's range is the whole day, than on a 4h bar, where
waiting means giving up a quarter of the move.

### What is still negative

The base rule, in full:

| iv | trigger | n | long | win | R | 90% interval | coin | at market | flipped |
|---|---|---:|---:|---:|---:|---|---:|---:|---:|
| 1d | touch | 148 | 53% | 28% | -0.114 | [-0.400, +0.236] | +0.060 | -0.784 | +0.721 |
| 1d | pin | 43 | 51% | 54% | **+0.180** | [-0.170, +0.585] | -0.014 | -0.091 | -0.212 |
| 1d | wick | 77 | 53% | 48% | +0.073 | [-0.206, +0.369] | +0.067 | -0.089 | +0.049 |
| 4h | touch | 334 | 60% | 29% | -0.013 | [-0.179, +0.161] | +0.064 | -0.783 | +1.141 |
| 4h | pin | 87 | 62% | 32% | **-0.376** | [-0.563, -0.178] | -0.236 | -0.422 | +0.287 |
| 4h | wick | 155 | 58% | 36% | -0.160 | [-0.345, +0.036] | -0.059 | -0.208 | +0.031 |

**Not one cell in the sweep is positive with an interval clear of zero**, except
`origin_small` 1d `pin` at +0.519 [+0.008, +1.152] on **25 trades** - one cell in
138, at the smallest population in its column, which is what one expects to find
by looking 138 times.

## The thing that does move, and why it is probably not an edge

`flip` - the same fills and stops, entered at market, on the **opposite** side -
is positive in **every arm and both timeframes**, median +1.11R at 4h and +0.72R
at 1d, with intervals clear of zero in all forty-six `touch` cells.

It would be easy to call that an edge. It is mostly an entry artefact, and the
column beside it says so: `straight`, the *same* side at market, is **-0.78R**
across the board while the real limit entry is -0.01R. Entering at market once
price has reached the zone is three-quarters of an R worse than resting a limit
at its edge. `flip` is the mirror of `straight`, so most of what it earns is that
same three-quarters of an R, reflected.

What survives after that reflection is small and in the same direction as
everything else the desk has measured this week: **price that reaches a zone
tends to keep going through it**. The band is not holding. That is consistent
with [`magnet.md`](../../docs/magnet.md) - levels are not magnets - and with the
82% return rate being a statement about fifty days of wandering rather than about
the zone.

## What this does not settle

* The `pin`-at-1d result is the only live candidate, and it is **43 trades**. It
  has not been tested out of sample at all. The held-out instruments - indices,
  energy, crypto alts, Deriv, the minor metals - produced about a hundred zones
  in total and **no cell reached thirty trades**, so that set cannot confirm
  anything at these settings. A forward test needs either more instruments or
  more time, and more time is the honest one.
* `FRESH` and the larger `OB_BACK` arms were added after this table was taken and
  are measured separately.
* Everything here is the development set. Nothing in it should be traded.
