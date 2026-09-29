# A wider stop at proportional size is a smaller trade, and nothing else

Harness: [`research/harness/widestop.py`](../harness/widestop.py). Lab run 2026-09-29.

## The question

A stop m times wider at 1/m the size risks the same money. Three effects could make the wider
version end better, measured in R (P&L over the money at risk):

- **noise:** the entry's own noise hits a wider stop less often. This is the sweep problem.
- **cost:** the spread is a smaller share of a wider risk. This is mechanical.
- **exit:** the shipping exit trails a fixed 0.5 vol and moves to break-even at 1R, and both behave
  differently against a wider risk.

[`stop-width.md`](stop-width.md) answered this on synthetic positions (always long, always short,
momentum): the widest stop had the thinnest tail everywhere. This asks it of **the entries
production actually takes**.

## Method

Stops at 1x (what ships), 1.5x, 2x and 3x. Entry, direction, target, hold and size in R are held
fixed. There are two exits:

- `ships` is the production walk's class defaults: the 0.5-vol trail, and break-even at 1R.
- `barrier` has no trail and no break-even, so a trade can only earn drift
  ([`barrier-geometry-is-irrelevant.md`](barrier-geometry-is-irrelevant.md)).

Both samples are replayed through the production forward walk, `till_infinity.shared.replay.walk`.
It fills a gapped stop at the open, and a bar that touches both barriers resolves as the stop.

| sample | what | n |
|---|---|---|
| **fills** | every trade the desk entered (`trading` decisions in the journal), with its own entry, stop, target and hold | 269 (252 with market bars) |
| **calls** | every published structures level call at the strategies' entry timeframes, with the call's own risk and push and a 30-minute hold | 67,879 (23,017 with market 1m bars) |

The cost is each feed's median observed spread from the journal, charged on both legs.

**Control:** the same trades on walks we generate, iid Student-t(3), one path per trade in the
trade's own volatility unit. A wider stop improves R on the control through cost alone, and only
improvement beyond the control is the market. The control runs on every trade, and the market only
on trades with stored bars, so the two populations differ in size (67,879 against 23,017 calls).
Deriv indices are entries like any other; the log does not report them separately.

Each sample is split by time: the first 60% is discovery and the last 40% verification.

**Pre-registered:** a wider stop is worth shipping if, on `calls` in the verification half, all of
these hold:

- its paired gain over 1x is at least 0.05R with t >= 3, clustered by feed-day;
- the gain exceeds the control's at the same width;
- it does not raise the maximum drawdown in R;
- `fills` agrees in sign.

## Results

### Calls, verification half (the pre-registered test)

| exit | stop | market mean R | market vs 1x (t) | control vs 1x (t) | market hit | market stopped | market max DD R |
|---|---|---|---|---|---|---|---|
| ships | 1.0 | +0.180 | | | 62.1% | 98.1% | 82.9 |
| ships | 1.5 | +0.120 | **-0.061 (-6.7)** | +0.018 (+5.3) | 62.3% | 98.1% | 53.4 |
| ships | 2.0 | +0.089 | **-0.091 (-6.7)** | +0.027 (+5.6) | 62.4% | 98.1% | 38.3 |
| ships | 3.0 | +0.059 | **-0.121 (-6.7)** | +0.036 (+5.6) | 62.4% | 98.1% | 25.1 |
| barrier | 1.0 | +0.159 | | | 46.5% | 45.0% | 140.8 |
| barrier | 1.5 | +0.106 | -0.053 (-4.3) | +0.015 (+2.6) | 50.1% | 36.5% | 97.7 |
| barrier | 2.0 | +0.073 | -0.086 (-5.1) | +0.020 (+2.6) | 52.4% | 30.3% | 105.0 |
| barrier | 3.0 | +0.044 | -0.115 (-5.2) | +0.028 (+3.0) | 55.1% | 20.9% | 84.4 |

In discovery the market calls were slightly negative at 1x (ships -0.016R, barrier -0.068R). A
wider stop "gained" there: +0.008 to +0.014R (t 0.7) under ships, and +0.023 to +0.045R (t 1.9-2.1)
under barrier.

### Fills (market), both halves

| half | exit | 1x mean R | 1.5x | 2x | 3x | vs 1x at 3x (t) | control vs 1x at 3x |
|---|---|---|---|---|---|---|---|
| discovery (151) | ships | -0.390 | -0.278 | -0.196 | -0.132 | +0.258 (+6.1) | +0.164 |
| discovery (151) | barrier | -0.380 | -0.312 | -0.221 | -0.143 | +0.237 (+2.7) | +0.130 |
| verification (101) | ships | -0.069 | -0.047 | -0.036 | -0.024 | +0.045 (+2.4) | +0.020 |
| verification (101) | barrier | -0.154 | -0.118 | -0.082 | -0.074 | +0.080 (+1.5) | +0.116 |

The per-strategy pools (fade-to-value 24, runner 26, snap 32, sweep-aware 24, thesis-only 120)
all lose money at 1x (-0.054 to -0.631R under ships). All of them "improve" with width, in the same
proportion.

### The pattern in every row: mean R scales as 1/m

Mean R at m times the stop is the 1x mean divided by m, to within a few thousandths:

| row | 1x | 1x / 1.5 vs 1.5x | 1x / 2 vs 2x | 1x / 3 vs 3x |
|---|---|---|---|---|
| calls market verif., ships | +0.180 | +0.120 / +0.120 | +0.090 / +0.089 | +0.060 / +0.059 |
| calls market discov., barrier | -0.068 | -0.045 / -0.046 | -0.034 / -0.031 | -0.023 / -0.023 |
| calls control discov., ships | -0.210 | -0.140 / -0.141 | -0.105 / -0.105 | -0.070 / -0.070 |
| fills market verif., ships | -0.069 | -0.046 / -0.047 | -0.035 / -0.036 | -0.023 / -0.024 |

Maximum drawdown in R scales the same way (calls market verification, ships: 82.9 -> 53.4 -> 38.3
-> 25.1).

Multiplying back by m gives the price P&L in units of the 1x risk. That shows what the stop did to
the trade itself:

| calls, market | 1x | 1.5x | 2x | 3x |
|---|---|---|---|---|
| verification, ships | +0.180 | +0.180 | +0.178 | +0.177 |
| verification, barrier | +0.159 | +0.159 | +0.146 | +0.132 |
| discovery, barrier | -0.068 | -0.069 | -0.062 | -0.069 |

The price outcome barely moves with the width of the stop. Under `barrier` the stopped share falls
from 45% to 21% of trades, yet the price P&L stays where it was, or gets slightly worse at 3x in
verification.

## What this means

- **A wider stop at constant money risk is a smaller position.** On a martingale this is exact:
  expected price P&L doesn't depend on the stop (the barrier theorem), so R = P&L / (m x risk) falls
  as 1/m. On these real entries it holds almost exactly too. The stops that fire at 1x end, on
  average, about where price would have been at the hold's end anyway.
- **There is no sweep effect at these entries.** The noise hypothesis says a 1x stop is taken out and
  price then comes back, and a wider stop would catch the return. That predicts a price-P&L gain
  with width, and there is none: +0.180 at 1x against +0.177 at 3x in verification, and -0.068
  against -0.069 in discovery.
- **The "gain" is the sign of the edge, divided by m.** Where the entries lose (costs, the discovery
  half, every strategy's fills), shrinking the position shrinks the loss, so a wider stop looks
  better. Where they win (market calls, verification: +0.180R at 1x), it shrinks the win by the
  same factor: -0.061R at 1.5x (t -6.7) and -0.121R at 3x. The control's positive "gain" (+0.018
  to +0.036R) is the same arithmetic on a losing, costs-only sample, not a separate cost mechanism.
- **The pre-registered test fails, decisively.** On calls in verification the paired change is
  negative at every width (-0.053 to -0.121R, t -4.3 to -6.7) and below the control's. `fills`
  disagrees in sign (+0.022 to +0.080R), because the desk's fills lose at 1x. The drawdown criterion
  "passes" (25.1 against 82.9R at 3x), but only because drawdown in R also scales as 1/m. That
  criterion was uninformative as written.
- **The lesson for this harness and its successors:** comparisons in R across stop widths at fixed
  money risk mostly measure 1/m. Judge a stop by the price P&L in units of the base risk (R x m),
  which isolates what the stop did to the trade.
- **Beside [`stop-width.md`](stop-width.md):** there, a wider stop's thinner tail was the reason to
  prefer it at equal money risk. That remains true, and it is the same fact seen from the tail: the
  position is smaller, so gaps and jumps past the stop cost fewer R. It is a sizing effect.

The market calls' +0.180R at 1x in verification, with a 62% hit rate, sits against -0.016R in
discovery. That instability is a question about the calls, not the stop, and is outside this study.

## For production

**Leave the stop as it ships.** Widening it at proportional size changes nothing about the trade's
price outcome at these entries and holds. It only scales every result, good or bad, by 1/m. If the
aim is smaller losses on the strategies that currently lose, that is a size (or a
stop-trading-them) decision and should be made as one. Hiding it in the stop would also shrink any
edge those entries do have.
