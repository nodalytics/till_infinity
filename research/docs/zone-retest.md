# The retest entry: better on both axes, and it does not survive

**Measured 2026-10-07.** The desk's rule, given after the approach-character test
came back empty:

> instead of choppiness, let's use displacement - it's either it enters the zone
> or touches the zone and bounces back in the opposite direction with the strong
> displacement candles, and comes back for retest, forms pattern and moves

Everything measured before this entered on the **first** reaction to the zone.
This rule refuses that bar. The first touch is only evidence; the trade is the
pullback into the origin that the reaction left behind.

Code: `retest()` in [`zones.py`](../ideas/zones.py),
[`retest_split.py`](../ideas/retest_split.py). The rule is
[`zone-rules.md`](zone-rules.md).

## The rule

1. price reaches the zone (`Zone.ret`, as every other trigger uses)
2. within `WINDOW`, **`DISP_N` consecutive impulsive candles leave it** - the
   zone throwing price away from itself rather than drifting off it
3. the candle **before that displacement** is the retest zone, read exactly as
   any zone is: band from its range (or body under `OB_BAND`), line at the near
   edge of its body
4. price comes back into that band within `RETEST` bars

Three triggers come out of it: `retest` (a limit at the band's near edge),
`retest_line` (at the line inside it) and `retest_pin` (which additionally waits
for the candlestick pattern - "forms pattern and moves").

**The stop is the point.** It sits under the retest candle rather than under the
original zone, which is a materially tighter risk on the same idea.

## It is better on both axes at once

1h, no filter, on the same zones:

| trigger | exit | n | R | win |
|---|---|---:|---:|---:|
| `touch` | opp | 721 | **-0.147** | 18.0% |
| **`retest`** | opp | 100 | **+0.349** | 24.0% |
| `retest` | t4 | 112 | +0.398 | 28.6% |
| `retest` | trail | 112 | +0.246 | 35.7% |
| `retest_line` | opp | 70 | +0.535 | 10.0% |
| `retest_pin` | opp | 50 | -0.222 | 24.0% |

The sign flips, across three different exits. And it wins **more often while
risking less** - 24% against 18% at 1h, 34.5% against 29.6% at 4h - which a pure
stop-tightening artefact would not do, since a tighter stop makes the same target
further away in R.

## And it fails both out-of-sample checks

**Across the period.** The 1h `retest` cell is +0.993 in the first half and
**-0.296 in the second**; `retest_line` is +1.696 then **-0.626**. Every cell has
q = 1.0 against both the coin twin and the random-time null. With win rates of
10-24% on the `opp` exit these are lottery-ticket distributions where a handful
of 5R winners carry the mean, which is exactly the shape that produces an
unstable split.

**Across instruments.** Run on all seventy-six at 4h and 1d, with the sixteen
development instruments held apart so the rest are a check and not just a larger
sample:

| iv | trigger | dev n | dev R | held-out n | held-out R |
|---|---|---:|---:|---:|---:|
| 1d | `retest` | 20 | **+0.304** | 2 | -0.238 |
| 4h | `retest` | 29 | **+0.241** | 16 | **-0.552** |
| 4h | `retest_line` | 22 | **+1.187** | 14 | **-0.497** |
| 4h | `touch` (reference) | 328 | -0.005 | 89 | -0.270 |

Pooled: **development +0.267 on 49 trades at a 36.7% win rate; held out -0.517 on
18 trades at 22.2%.** The sign flips on every cell with any held-out data.

Eighteen trades is not decisive by itself. But it is the *opposite* sign rather
than a weaker version of the same one, and it is the second failure, not the
first.

## Why the populations are so thin

The retest needs a displacement **and** a pullback on top of a zone population
that is already only 328 trades at 4h and 144 at 1d. Sixty extra instruments do
not fix it: most are crypto and indices with short histories, and between them
they contribute 89 `touch` trades at 4h and **16** `retest` trades.

That is the same wall the weekly study hit, and it is structural. A rule this
selective cannot be confirmed on this database at 4h or above; 1h is the only
interval with enough bars, and 1h is where the split-half failed.

## What to keep

* **The entry mechanism is real and the result is not.** Waiting for the
  displacement genuinely buys a tighter stop and a higher hit rate on the same
  zones. It does not survive instruments it was not built on.
* **`retest_pin` is worse than `retest` at every exit and both timeframes.** That
  is the fifth independent place in this work where waiting for a candlestick
  pattern costs money at 1h and 4h - see the confirmation split in
  [`zone-rules.md`](zone-rules.md), which found the same thing four ways.
* If this is picked up again, the thing to do is **the barrier test** - did price
  reach the target before the stop - which is where every other idea measured
  this week has died.
