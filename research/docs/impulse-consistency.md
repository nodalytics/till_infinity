# Consistency as volatility: same-direction candles with expanding bodies

The operator's definition, measured 2026-09-20: *"volatility to us also means clean
consistent movement in one direction - red candle, longer red candle, longer red
candle"*, a minimum of two or three in a row, with at least one long candle
signifying strong intent.

Two separable claims sit in that, and they come out differently.

## The pattern

A run ends at bar `i` when the last `need` bodies all share a direction, each body
is at least as large as the one before, and the final body is at least `2x` that
instrument's median body. Runs are taken non-overlapping - one observation per run,
not one per bar - so a long impulse is not counted three times.

Measured on the broker's own M1 bars, 42 instruments, 2026-07-20 to 2026-09-20,
with the broker's own per-bar spread.

## As direction: no

Using the first passage test from `first-passage.md` - which barrier is touched
first at a 10x spread band, where only 0.9% of cases are ambiguous:

| | |
|---|---|
| continuation after a qualifying run | **49.5%** |
| base rate from an arbitrary bar | 49.4% |
| lift | **+0.1%** |
| breakeven at a 10x band | **55.0%** |
| instruments continuing more often | 23 of 37 |

23 of 37 is chance. Four volatility indices reached 53-54% at t = 2.0 to 2.6, but
37 tests give about 1.85 of those by chance, they are correlated synthetics rather
than four independent tests, and **the best of them is still below breakeven.**

## As volatility: yes, and on the real instruments only

The claim as actually stated - that consistency marks movement - holds. Absolute
move over the next 30 minutes, and the range travelled, both against an arbitrary
bar on the same instrument in units of its own median body:

| | median ratio |
|---|---|
| move over the next 30 minutes | **1.17x** |
| range travelled in that window | **1.21x** |
| instruments where the move was bigger | **30 of 37** |

The split is the useful part:

| | move ratio |
|---|---|
| usdcnh | 1.50 |
| usdjpy | 1.40 |
| usdcad | 1.24 |
| usdchf | 1.21 |
| **every volatility index** | **0.96 - 1.08** |

So the pattern forecasts movement on real markets and forecasts nothing on the
Deriv synthetics. That is what a random walk with flat volatility should do, and it
agrees with the variance ratios measured on 2026-09-19: there is no volatility
clustering in them to detect.

## Why this is worth having anyway

Every measurement here has found direction absent, and the one use of a volatility
forecast that survives is **sizing** - risk less when the next half hour is likely
to be quiet, more when it is not. The desk already forecasts variance through
GARCH, HAR and an ensemble; this is a different kind of input, a pattern rather
than a second moment, and it is strongest on exactly the instruments where the
existing forecasts have something to work with.

It also says something about the synthetics that the desk trades most: **no
volatility signal can help size them**, because their volatility does not vary.
Sizing work should be aimed at the real instruments.

## Caveats

* Runs are non-overlapping but instruments are not independent of each other -
  the four majors move together, so 30 of 37 is fewer effective observations than
  it looks.
* `2x` the median body and 30 minutes forward were chosen once and not swept. A
  sweep would need its cells counted.
* This is a forecast of *magnitude*, so it cannot be traded on its own. It is an
  input to size, and the sizing rule it would feed has not been built or measured.
