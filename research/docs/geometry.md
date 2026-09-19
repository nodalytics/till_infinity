# Where the money is going: entry, target, and the exits

119 closed trades, net **-70.27**. Broken down by how each ended, using
`exit_kind` rather than `reason` - the latter records only whether we closed
the position or found it gone, which is the price source and not the cause:

| kind | n | wins | net $ | median $ | median s |
| --- | --- | --- | --- | --- | --- |
| hold | 40 | 52.5% | +12.67 | +0.78 | 276 |
| stop | 38 | 0.0% | -897.84 | -24.39 | 151 |
| target | 19 | 100.0% | +915.29 | +11.42 | 161 |
| stale | 6 | 50.0% | -5.01 | -0.76 | 326 |
| gone | 2 | 50.0% | +50.76 | +25.38 | 59 |

**The timers are not the problem.** Stale is six trades and -5.01 at a 50% win
rate; the hold clock is forty trades and roughly flat. A better hold or stale
estimator would be tuning something that is not costing anything.

## Far targets are never reached

Bucketing the same trades by the reward-to-risk they were given:

| R:R | n | hit target | stopped | net $ | per trade |
| --- | --- | --- | --- | --- | --- |
| 0-0.6 | 28 | 35.7% | 10.7% | 0.01 | 0.00 |
| 0.6-1 | 21 | 28.6% | 14.3% | 640.25 | 30.49 |
| 1-1.5 | 24 | 8.3% | 41.7% | -90.45 | -3.77 |
| 1.5-2.5 | 33 | 3.0% | 48.5% | -431.25 | -13.07 |
| 2.5+ | 13 | 0.0% | 46.2% | -188.83 | -14.53 |

Hit rate falls monotonically, 35.7% to zero. Stop rate rises monotonically,
10.7% to 48.5%. The further the target sits relative to the stop, the less
often price gets there and the more often the stop is taken instead - which
says `expected_push_vol` over-reaches.

**The P&L column is contaminated and the rate columns are not.** The +640 in
the 0.6-1 bucket is almost entirely one trade: the Volatility 75 windfall,
reward-to-risk 0.702, which was itself the sizing bug in
[trading.md](../docs/trading.md). Strip it and that bucket is about +0.88 a
trade. The hit and stop gradients do not depend on P&L at all.

## So no reward-to-risk floor

A floor keeps the losing trades and refuses the winning ones. Simulated over
the same 119:

| floor | keeps | refuses |
| --- | --- | --- |
| 0.8 | 78 worth **-737.16** | 41 worth **+666.89** |
| 1.0 | 70 worth -710.53 | 49 worth +640.26 |
| 1.5 | 46 worth -620.08 | 73 worth +549.81 |

This is not new. `risk.py` carries a re-verification from 2026-08-27 over
**47,676 production touches**: 0.908R ungated against 0.868R at the 1.2 floor,
monotonically worse as the floor rises, refusing 40,421 of 47,676 calls to gain
0.047R. `TRADING_MIN_RR=0.0` keeps it off, and the `Guard` reads the setting
directly rather than the risk plan - which still carries 1.2 and does not reach
it.

## Fixing the geometry from the entry instead

Reward-to-risk has two terms and only one of them is a forecast. The target
depends on `expected_push_vol`, which the table above says over-reaches; the
entry does not depend on a forecast at all.

A limit resting `d` volatility units inside the level fills only on touches
that go at least that deep. `depth_vol` on every resolved touch is exactly that
distribution - 72,452 of them, against a median stop of 3.02v:

| depth | fills | risk left | risk cut | R:R |
| --- | --- | --- | --- | --- |
| 0.25v | 75.0% | 2.77v | 8.3% | 1.09x |
| 0.50v | 49.6% | 2.52v | 16.6% | 1.20x |
| 1.00v | 25.9% | 2.02v | 33.1% | 1.50x |
| **1.50v** | **14.6%** | **1.52v** | **49.7%** | **1.99x** |
| 2.00v | 7.9% | 1.02v | 66.3% | 2.96x |

Halving the risk costs 85% of the setups. It buys more than the ratio shows,
because the target is measured from the **fill** while the stop is anchored to
the **level**: a deeper fill shrinks the risk and brings the target nearer in
absolute terms at the same time.

`TRADING_ENTRY_EDGE_VOL` is the depth, live at 1.5. It is held here and fired
at market on arrival rather than sent as a broker pending order - the bridge
has `POST /orders/pending`, and using it would put the stop and target on the
terminal between placement and fill, where nothing here can adjust them.

## What is not measured

**Whether a trade filled on a deep wick still works.** The depth distribution
says how often price gets there and nothing about what it does next, and buying
a deeper fall is a different trade from buying a shallow one. That is the
question the next hundred trades answer, and it is the one that decides whether
1.5v was the right depth or merely the arithmetic one.

`TRADING_TARGET_BUFFER_VOL` is built and off. The hit-rate gradient argues it
is directionally right - a nearer target is reached more often - but it trades
payoff for frequency on a book whose payoff is already the weaker half, and it
should not be turned on in the same week as the entry depth or neither can be
attributed.
