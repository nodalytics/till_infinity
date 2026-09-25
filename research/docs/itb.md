# What intelligent-trading-bot does differently - five nulls, and a candidate that did not survive its walk-forward

Measured 2026-09-25 on the lab, with [`itb.py`](../harness/itb.py), on every real instrument in
the lab's broker bars: 15 FX pairs, XAU, XAG, BTC, ETH and SOL, at 15m and 1h (and 3m crypto).

[asavinov/intelligent-trading-bot](https://github.com/asavinov/intelligent-trading-bot) (MIT,
~1,870 stars) is a config-driven signalling framework, mostly for BTC. **It publishes no
performance numbers**, and its simulator could not produce trustworthy ones:
- it charges no fees and fills at the close of the bar that made the signal;
- it grid-searches the buy/sell thresholds on the same predictions it reports;
- it has no benchmark and no drawdown figure.

Its core - up/down race labels, P(up) - P(down) as the score, LightGBM/LR/NN on TA features -
is what `horizons.py`, `questions.py` and `ensemble.py` already tested. Five things it does
differently had not been. House rules throughout:
- stops resolved on wicks (`bars.py`; a bar that touches both levels counts as the stop);
- non-overlapping entries;
- spread charged;
- thresholds chosen before the test block;
- both halves of the test period reported.

## Four nulls

| | what ITB does | result (test block, net) | verdict |
| --- | --- | --- | --- |
| **A** | purged rolling retrain | monthly refits improve the fixed fit slightly and stay negative: 15m long -0.030 -> -0.016R, short -0.079 -> -0.058R; 1h long -0.077 -> -0.062R, short -0.057 -> -0.036R | **null** - drift is not what made the fixed fit fail |
| **B** | a 5:1 race (target T, stop 0.2T) | -0.052 to -0.080R for the models' top 20% at 15m and 1h; every-bar -0.08 to -0.16R. Short-window volatility alone predicts the label at AUC 0.58-0.66 | **null** - fixed or volatility-scaled, the label is mostly size |
| **D** | smoothing the score | race trades: smoothing cuts trade count by up to a third and leaves net unchanged (-0.030 to -0.052R) | **null** for fixed-horizon trades |
| **E** | ITB's own setting: crypto, +2% before -0.4% within two hours | -0.38 to -0.60R at a 0.1%-per-side taker fee (the fee alone is half the stop); -0.01 to -0.22R at house spread | **null**. ITB's optimistic tie rule changed nothing on 3m bars: no race had a first bar touching both levels |

## The candidate: ITB's two-state machine on 15m FX, on one split

**C** is ITB's trading rule, not its label:
- the score is P(up) - P(down) from the same two gradient-boosted race models `horizons.py` uses (2-hour race, 54 features);
- enter above theta_buy, leave (or reverse, in the long/short variant) below theta_sell, and hold in between;
- no stop, no fixed horizon.

The models are fit on the first 40% of each series, the two thresholds are chosen on the next
20% (from 20 quantile pairs), and the last 40% is the test.

On 15m FX, on the single split, it made money after costs and survived every check applied to it:

| check | result |
| --- | --- |
| **random-walk control** - the identical machine on 10 Volatility indices, which are exact random walks | z +1.3 to +1.4 at 15m, +0.1 to +0.4 at 1h - chance. The method does not manufacture wins |
| **latency** - enter one or two bars (15-30 minutes) late | FX long/short net +1.23 / +1.06 log over 15 pairs; independent-shift z +8.3 / +7.4 |
| **a correlation-aware null** - every pair shifted by the *same* offset, so the dollar's common timing is kept | z **+4.0 to +4.8**; the real result beats 99.7-100% of 300 shifts |
| **costs** - at 1x, 2x, 3x the assumption, delay 1 | long/short **+1.18, +0.63, +0.08** log; long-only +0.61, +0.34, +0.06 - breaks even near 3x |
| **real spreads** - the broker's own spread field, 15m, 15 pairs | median **0.25x** the assumption (EURUSD 0.17bp against 1.14bp assumed; max 0.58x on USDCNH). With a typical raw-account commission (~0.5-0.7bp round trip) the assumption is about right |
| **month by month** (delay 1, assumed cost) | **9 of 11** months positive, long/short and long-only alike |
| **breadth** | 11 of 15 pairs positive |
| **exposure** | long/short is always in the market; long-only about 18-28% exposed, beating always-long (+0.05 log on FX over the period) |

**What it is not:**
- **Not 1h.** The 1h version wins only with a same-bar fill. One bar late, z drops to +2.7 and net goes negative; two bars late, z is +0.2. That is a first-bar effect a real order cannot reach.
- **Not metals, crypto or the synthetics.** Metals are z -1.2 to +1.7 across delays and intervals, crypto -1.4 to +2.1, and the control +0.1 to +1.4.
- **Not the race.** The same models traded as fixed 2-hour races lose (D above, -0.03R). The value is in how the machine *holds*: it stays in until the score turns. About 4,560 trades over 15 pairs in roughly 11 months puts the average long/short hold on the order of a day (an estimate from counts, not measured per trade), far longer than the 2-hour race.

**Why it is a candidate and not a strategy:**
- It is one test period, November 2025 to September 2026 (about 11 months), from one fit.
- Its 15 pairs share the dollar, so they are fewer independent bets than 15.
- The thresholds were chosen on 20 combinations of validation data.
- This page ran five tests, and C with its variants is several cells. The correlation-aware z of 4-5 is well beyond what that search produces by chance, but it is one number, not a replication.

## The walk-forward, and why C is closed

`itb.py` `PART=F`, 15m FX, monthly. Each test month:
- both models are fit on the trailing six months, ending two months before the month, less a purge;
- the thresholds are chosen on those two months with the same grid;
- the month is traded from a flat start, one and two bars late, at 1x and 2x cost.

Nothing about a month is seen before it is traded. The months before November 2025 were never in
the single-split test that selected C, so they are the only new evidence:

| | months | long-only, delay 1, 1x cost | long/short, delay 1, 1x cost | long/short, delay 2, 2x cost |
| --- | ---: | --- | --- | --- |
| **May-Oct 2025 - new evidence** | 6 | +0.214, 5/6 positive; **holding long made +0.41** | **+0.048, 3/6 positive** | -0.530, 1/6 |
| Nov 2025-Sep 2026 - overlaps the split that picked C | 11 | +0.790, 9/11 | +1.447, 10/11 | +0.283, 5/11 |
| all | 17 | +1.004, 14/17 | +1.495, 13/17 | -0.246, 6/17 |

**On the months that could not have influenced its selection, C is flat: long/short +0.05 over
six months, and long-only earns half what holding long did.** Nearly all of the walk-forward's
money is in the very period that picked it. That is the signature of selection - the result
found the period, not an edge - and it fails the cost and latency margin the single split
appeared to have. **C is closed.** It is recorded here with every check it passed, because
passing them all was not enough, and that is the finding worth keeping: a
correlation-aware z of 4-5, a random-walk control, 2x costs and 9 of 11 months can all hold on
one period and still not replicate on the next.

## The Deriv synthetics

`PART=Y`: the same machine on every synthetic family the lab holds - Volatility, Boom, Crash,
Jump, Step and Multi Step, Range Break, DEX, Drift Switch, Skew Step - fit and thresholded per
family, at 15m and 1h, costs from `catalogue.md` (0.2 where it did not measure).
`Drift_Switch_Index_20` at 15m failed the leak check and was skipped.

**Null in every family, at both intervals: the common-offset z runs from -1.3 to +1.4.** Several
raw totals are positive - Boom long/short +1.66 at 15m, Volatility long/short +4.21 at 1h - and
the shifted null earns the same from the same exposure: they are the instruments' own drift
(Boom grinds down, so a standing short pays), not timing. This agrees with `generated.md`,
`spiking.md` and `twins.md`: these are generated processes whose next move does not depend on
the past, so there is nothing for a timing rule to find.

## What follows

* **A through E and the synthetics stay closed** - ITB's labels, its rolling retrain, its
  smoothing, its crypto setting and its two-state machine.
* **The method note is the durable result.** A single split, however well controlled, is one
  period. The walk-forward's split into "before the choice" and "after" is what exposed this, and
  it is cheap: any future candidate here should report it before anything else.
