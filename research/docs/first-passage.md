# First passage: which barrier arrives first, and how fast

Measured 2026-09-20 on 37,426 level calls against the broker's own M1 bars.

Every earlier test in this repository measured the return at a **fixed horizon**.
A stop/target trade does not resolve that way: it resolves on **first passage** -
which barrier price touches first. A call can be a coin flip on endpoints and not
on first passage, and it is the second question the desk's geometry actually
poses. This asks it.

## The band has to be wide enough to be readable

At a tight band both barriers sit inside one 1-minute bar and their order is
unknowable, so a simulator that picks one is inventing the answer. Measured
before anything was claimed:

| band | both in one bar | neither within 2h | median first passage |
|---|---|---|---|
| 2x spread | **14.1%** | 0.5% | 43s |
| 5x | 2.8% | 2.0% | 151s |
| 10x | 0.9% | 6.6% | 434s |
| 20x | 0.4% | 19.3% | 1,087s |
| 40x | 0.2% | 47.4% | 1,827s |

5x and above are usable. Below that, 1-minute bars cannot answer the question.

## No edge, and the gap to breakeven is wide

With symmetric barriers at +/-B and a spread S paid on entry, EV > 0 needs
accuracy above `0.5 + S/(2B)`. Stated per band, because it is the whole test:

| band | n | call right | breakeven | gap | t | shuffled beats it |
|---|---|---|---|---|---|---|
| 5x | 35,634 | 50.5% | 60.0% | **-9.5%** | +2.03 | 4.2% |
| 10x | 34,650 | 49.0% | 55.0% | **-6.0%** | -3.55 | 0.0% |
| 20x | 30,167 | 49.7% | 52.5% | **-2.8%** | -1.18 | 25.0% |

First passage agrees with every other measurement here: the call carries no
direction. Note breakeven is *higher* than intuition suggests - the spread is
paid once against a symmetric barrier, so a 5x band needs 60%.

## The one apparent edge is a simulator artifact

By family at 10x, two cells are strongly significant:

| family | n | call right | t |
|---|---|---|---|
| **boom** | 1,285 | **39.8%** | **-7.34** |
| **crash** | 2,212 | **45.5%** | **-4.25** |
| crypto | 2,967 | 50.7% | +0.72 |
| fx | 9,872 | 49.7% | -0.56 |
| index | 3,148 | 48.4% | -1.78 |
| metals/oil | 1,680 | 51.4% | +1.17 |
| volatility | 13,486 | 49.5% | -1.10 |

Inverting on boom gives 60.2% against a 55% breakeven, which reads as +5.2% on
1,285 observations at t = -7.34. It is not an edge. **The replay assumes a stop
fills exactly at its barrier, and on Boom and Crash that is the one assumption
guaranteed to be false.** Measured overshoot past a 10x band, as a multiple of
the band:

| feed | up p50 | up p95 | up max | down p95 | down max |
|---|---|---|---|---|---|
| **boom_500** | **7.08** | **17.81** | 35.4 | 1.09 | 1.2 |
| **crash_500** | 1.02 | 1.08 | 1.2 | **17.58** | **38.3** |
| volatility_25 | 1.08 | 1.47 | 1.8 | 1.36 | 1.6 |
| eurusd | 1.20 | 2.25 | 13.5 | 2.42 | 13.2 |
| gold | 1.47 | 3.25 | 27.9 | 3.32 | 19.3 |
| btc | 1.77 | 5.14 | **90.2** | 4.96 | 48.0 |

Return skew confirms the shape: boom +6.04, crash -6.03.

Trading down on boom therefore wins `+B` on 60.2% and loses a **median 7B** on
the 39.8%, because the losing side *is* the spike:

    EV = 0.602*B - 0.398*7B - S ~= -2.18B

which is the drift paying for the spike, exactly as
`coinbase-premium.md` measured it from the other direction. Any backtest on
Boom or Crash that fills stops at their level will show this same false edge.

## The correction this forces on the spread finding

`banded-labels.md` records that the round trip is 0.10-1.07bp rather than the
1.5-3bp assumed, and concluded breakeven at one minute is about 56%. That
conclusion is too generous, because **the spread was never the dominant cost.**
Slippage past the stop is larger, and it is not confined to the synthetics: at a
10x band, btc overshoots by 5.14x in 5% of crossings, gold by 3.25x, eurusd by
2.25x. A stop is a request, not a fill price.

So the cost of a trade is the spread *plus* the expected overshoot on the losing
side, and only the first of those has been measured properly. The desk records
its own fills, so the second is measurable rather than assumable - and it should
be measured per instrument before any short-horizon breakeven is trusted.

## Tests run

3 bands and 7 families, so 10 cells: one at p < 0.05 is expected by chance. Two
were far beyond it, and both are explained by the overshoot above rather than by
anything predictive.
