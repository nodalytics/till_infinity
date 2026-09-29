# The rollover hour in production: FX level statistics are learning from a quote artefact

Harness: [`research/harness/rollover.py`](../harness/rollover.py). Read-only, on the lab's journal
snapshot (2026-08-13 to 2026-09-10). Run 2026-09-29.

## The question

[`fxtod.md`](fxtod.md) found that the one FX hour-of-day pattern that persists is at 20-23 UTC,
the New York close and the broker's daily rollover, and that it looks like quote artefacts rather
than order flow. What does that window do to production?

## Results

**The desk's trades: the window is not worse, and FX barely trades in it.** There are 207 closed
trades with an R multiple, from 2026-08-28 to 2026-09-10.

| | n | mean R [95%, days resampled] | hit | median slippage |
|---|---|---|---|---|
| all, entered 20-23 UTC | 30 | -0.014 [-0.249, +0.182] | 57% | 0.10 bps |
| all, other hours | 177 | -0.201 [-0.273, -0.109] | 40% | 0.00 bps |
| Deriv, 20-23 UTC | 28 | -0.031 [-0.313, +0.149] | 57% | 0.15 bps |
| Deriv, other hours | 120 | -0.239 [-0.352, -0.067] | 40% | 0.00 bps |

Only 1 of 19 FX trades was entered in the window. The trades that are in it are Deriv, which has no
rollover.

**The structure calls: FX outcomes pile up at 21:00 UTC.** These are 253,566 resolved calls. The
first table is by family; the second is FX weekdays by the hour the call resolved.

| family | calls | share resolved in 20-23 UTC (even spread: 16.7%) |
|---|---|---|
| FX | 77,136 | **29.7%** |
| Deriv | 19,253 | 17.1% |
| metals | 1,893 | 16.4% |
| crypto | 11,068 | 16.3% |

| UTC hour | share of FX calls | trap | break | reject |
|---|---|---|---|---|
| 00-20 (range over the hours) | 2.5-6.7% | 9.3-15.7% | 3.5-9.0% | 70.5-76.6% |
| **21** | **14.7%** (n = 10,843) | **19.0%** | **1.0%** | 70.7% |
| 22 | 3.8% | 11.6% | 3.5% | 75.3% |

Share of FX outcomes resolving in 21-22 UTC, by timeframe (even spread: 8.3%):

| 1m | 3m | 5m | 15m | 30m |
|---|---|---|---|---|
| 12.6% | 22.8% | 28.3% | **40.6%** | **46.1%** |

## What this means

- **The rollover spike is resolving FX touches.** At 21:00 UTC (17:00 New York) the broker's spread
  widens for the daily rollover. On bid-based bars that prints a wick through nearby levels and back.
  The engine reads this as a touch that resolves, most often as a trap: the trap share rises to 19%
  and the break share falls to 1%. The same hour is flat on Deriv, metals and crypto, which have no
  FX rollover.
- **The slower the timeframe, the worse the contamination.** A 15m or 30m level is touched rarely
  in normal trading, so the one spike a day is a large share of its record: 41-46% of FX 15m and 30m
  outcomes resolve in two hours out of twenty-four.
- **That record feeds everything built on it:** each level's hold and symmetric rates, the break
  model, the trap re-labelling, `record_hold` on the cards, and the retraining data. A level
  "held" at 21:00 because of a spread spike is not evidence that it holds.
- **The desk's own trades are not hurt,** because they rarely enter FX in the window. The damage is
  upstream, in what the engine learns about FX levels.

## For production

1. **Done: the FX rollover is masked in `structures`** (`structures/rollover.py`, on by default,
   `STRUCTURES_ROLLOVER_MASK=0` turns it off).
   - **Window:** 16:55-17:10 New York, so 21:00 UTC in northern summer and 22:00 in winter.
   - **What the mask does:** for FX feeds only, a price update that reaches the window neither
     opens a touch nor resolves one, and does not advance the symmetric races.
   - **What still happens:** touches opened before the window are carried through it untouched
     and judged on the prices after it, and levels still form from these bars.
   - **What is left alone:** bars longer than two hours, which always span 17:00 but in which the
     spike is a small part of the range; and Deriv, metals and crypto.
   - **Follow-up:** levels drawn from the rollover wick itself (a pivot at a spike extreme) are not
     yet excluded.
2. **Measure it again after the mask.** The 21:00 bulge should disappear, and the FX 15m and 30m
   hold rates should be re-read without it.
3. Optionally, **discount the FX 15m and 30m levels' existing records,** since up to 46% of their
   outcomes are rollover-made. Decaying them faster once the mask is in would let clean outcomes
   take over.
