# The spike switch fires on the session clock, and in the units production sizes in it is worse than a uniform cut

Measured 2026-09-28 on the lab with [`sessionswitch.py`](../harness/sessionswitch.py): 20 real
instruments (15 FX pairs, XAU, XAG, BTC, ETH, SOL) and four exact random walks from the Deriv
synthetics as the control, at 3m, 15m and 1h, about 480,000 test-block bars per interval. Everything is
reported on the last 40% of each series by time, with both halves.

## The question

[`manifold.md`](manifold.md) found that the largest structure in these markets' states is the
**hour of day**. Production's risk switch (`scaling.by_spike`) halves size when `tr_percentile`
reaches 0.8. `tr_percentile` is the 14-bar EWMA of true range, ranked in the instrument's own last
1,500 bars, and it has no idea what hour it is. A London open ranked against a window that holds
the Asian night looks like a spike every day. Two questions follow:
- Is the switch firing on the clock?
- Would a session-aware percentile do better?

Three switches were tested. All are parameter-free, and all halve size at >= 0.8:
- **`prod`:** production's percentile, as it runs today.
- **`samehour`:** the same EWMA, ranked only among its own readings at the same UTC hour over the
  last 20 days.
- **`deseason`:** the EWMA divided by its 20-day mean at the same hour, then ranked in the last
  1,500 bars.

Each was applied to two toy positions that know nothing about it: always long, and the sign of the
last 20 bars. Positions are held H bars (10 at 3m, 8 at 15m, 5 at 1h) and do not overlap. They are
scored unstopped and with a 1U stop taken by the wick, filled at the level or at the open on a gap.

## 1. Yes, production's switch is largely the clock - at short intervals

Real markets, `prod`:

| | FX: fire rate by hour | share of firing explained by the hour | metals | crypto |
| --- | --- | ---: | --- | --- |
| 3m | 2.4% to 73.4% | **22.8%** | 0.4% to 88.5%, **39.9%** | 6.2% to 68.1%, **17.3%** |
| 15m | 6.6% to 50.8% | 9.5% | 9.4% to 47.2%, 6.7% | 6.4% to 38.8%, 7.0% |
| 1h | 12.1% to 31.1% | 2.0% | 15.0% to 33.5%, 2.1% | 14.1% to 25.0%, 0.8% |

At 3m the switch is on for three quarters of FX bars in the busiest hour and for 2% in the
quietest. On metals the range is 0.4% to 88.5%. A 3m window of 1,500 bars is three days, and the
session cycle dominates it. At 1h, where the window is two months, the clock nearly vanishes. Both
session-aware switches bring the hour's share to 0.7% or less everywhere. On the random walks,
which have no session, all three are flat.

**Removing the clock costs foresight at 3m and buys it at 1h.** P(a bar beyond 4x the baseline
|return| within H) when the switch is on, relative to when it is off:

| lift (AUC) | FX | metals | crypto |
| --- | --- | --- | --- |
| 3m prod / samehour / deseason | **2.99x** (0.687) / 1.71x / 2.01x | **3.19x** (0.700) / 1.89x / 2.06x | **2.98x** (0.699) / 1.64x / 2.40x |
| 15m | 2.06x / 2.02x / 2.07x | 1.82x / 1.99x / 1.98x | 2.19x / 2.14x / 2.31x |
| 1h | 2.15x / 2.45x / **2.56x** (0.652) | 1.83x / 2.00x / **2.14x** | 2.50x / 2.99x / **3.10x** (0.711) |

(random walks: 0.71x-0.95x for every switch)

At 3m, a large bar mostly means "the session is opening", and the clock is the best predictor of
it. At 1h, removing the clock sharpens the switch. That half of the hypothesis holds.

## 2. The switch is worse than halving at random, in production's units

The first question is the wrong one for production. The switch was validated in
[`crash-timing.md`](crash-timing.md) on positions measured in a fixed, session-blind unit (a
500-bar mean |return|). But production sets its stops in multiples of the *entry-time*
`ewma_tr_bps` (`strategy.py`, `sizing.price_distance`) and sizes each position so that the stop
risks a fixed amount (`scaling.by_volatility` is off by default). A position opened into high volatility already has a wider stop and a
smaller size. So the harness was run both ways:
- **`UNIT=base`:** fixed-size positions, as in crash-timing.md.
- **`UNIT=live`:** R measured against the entry-time EWMA of true range, which is production's R.

**The benchmark is a placebo:** the production switch's own sizes dealt to random positions,
50 times. Halving any 20% of positions shortens the tail, so a switch is only worth something if
it beats that.

The number reported is how much the expected shortfall of the worst 1% (ES1) improves per unit of
average size given up, for the always-long position. The momentum position shows the same
pattern.

| | fixed units: prod / placebo | **production's units: prod / samehour / deseason / placebo** | production's units, 1U stop: prod / placebo |
| --- | --- | --- | --- |
| 3m FX | +13.57 / +4.74 | +2.82 / **+4.06** / +2.58 / +2.56 | +0.03 / **+1.53** |
| 3m metals | +13.66 / +3.71 | +0.88 / +0.73 / +1.39 / +1.07 | +0.00 / +0.23 |
| 3m crypto | +12.22 / +3.95 | +0.69 / +1.02 / +0.95 / **+1.91** | +0.00 / +0.02 |
| 15m FX | +10.79 / +3.83 | +1.68 / +2.04 / +2.19 / +1.81 | +0.07 / **+1.19** |
| 15m metals | +10.98 / +3.22 | +1.10 / +1.42 / +0.92 / **+1.60** | +0.01 / +0.41 |
| 15m crypto | +4.16 / +2.59 | +0.05 / +0.19 / +0.40 / **+2.07** | +0.00 / +0.17 |
| 1h FX | +9.19 / +3.74 | +0.93 / +1.20 / +1.25 / **+1.67** | +0.25 / +0.33 |
| 1h metals | +8.49 / +3.52 | +0.65 / +1.13 / +0.96 / **+1.40** | +0.03 / +0.16 |
| 1h crypto | +8.99 / +3.36 | +1.17 / +1.20 / +1.20 / **+1.65** | +0.00 / +0.04 |

- **In fixed units the switch works as crash-timing.md said.** It beats the placebo 2-4x, and
  beats the placebo's 95th percentile in 17 of 18 unstopped real cells (both positions, three
  families, three intervals).
- **In production's units it is worse than random.**
  - Unstopped, `prod` beats the placebo's mean in 1 of 18 real cells.
  - With the 1U stop, in 0 of 18.
  - The session-aware switches are no rescue: 3 of 18 each unstopped, and 0 of 18 stopped.

The likely reason is arithmetic, though it was not measured separately. `ewma_tr_bps` is already
in the stop, so a high-volatility moment is
already a small position. What the switch then catches is volatility *after* it has risen. Measured
against that raised unit, the next move is usually smaller, because volatility reverts. So it
halves the positions that are least risky in R and leaves the tail where it was. Halving a random
fifth of positions cuts the tail more, and so does simply risking less per trade.

This agrees with [`stop-width.md`](stop-width.md), which found the switch "does very little to a
stopped position's tail" and improved ES1 in only 35 of 93 cells. The likely explanation is
the same: the stop and the sizing already carry the volatility the switch reads.

## What this settles

- **Leave the spike switch off** (`TRADING_SPIKE_ABOVE` unset, as it is by default). In the units
  production risks in, it buys less tail protection per unit of size than a uniform size cut, and
  with a stop it buys almost none. The crash-timing result stands for fixed-size positions, which
  production does not hold. The earlier advice to enable it at 0.8 is withdrawn.
- **If the tail needs to be smaller, lower the risk per trade.** A uniform cut shrinks ES1 by its
  full size, |ES1| per unit given up (3.02 for 15m FX long). In production's units that beats
  every switch in every real cell but one, the same-hour switch on 3m FX long (+4.06 against 3.72).
- **The switch is largely the session clock at 3m** (the hour explains 17-40% of when it fires),
  and hardly at all at 1h. A same-hour percentile removes the clock and sharpens the big-bar
  forecast at 1h (lift 2.15x to 2.56x on FX), but it does not change the verdict above.
- **The finding that sticks** is that volatility-scaled stops already do the volatility timing. A
  second volatility signal layered on top of them sizes on reversion rather than on risk.
