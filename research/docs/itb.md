# What intelligent-trading-bot does differently - four nulls and one candidate: hold until the opposite signal, 15m FX

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

## One candidate: ITB's two-state machine on 15m FX

**C** is ITB's trading rule, not its label:
- the score is P(up) - P(down) from the same two gradient-boosted race models `horizons.py` uses (2-hour race, 54 features);
- enter above theta_buy, leave (or reverse, in the long/short variant) below theta_sell, and hold in between;
- no stop, no fixed horizon.

The models are fit on the first 40% of each series, the two thresholds are chosen on the next
20% (from 20 quantile pairs), and the last 40% is the test.

On 15m FX it makes money after costs, and it survived every check applied:

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

## What follows

* **Walk it forward before anything else.** Refit the models and re-choose the thresholds monthly, on 15m FX only, and score each month on data after its fit. That is the replication the single split cannot give.
* **Paper-trade it live** on the desk's own feed, recorded and never sized, for a few weeks. The broker's real fills and spreads - including rollover and news widening - are the test the bars cannot run.
* **A through E stay closed** - including ITB's labels, its rolling retrain on race trades, and its crypto setting.
