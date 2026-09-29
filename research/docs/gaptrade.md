# Trading the FX weekend gap: enter at Friday's close against its last hours, exit at Sunday's open

Harness: [`research/harness/gaptrade.py`](../harness/gaptrade.py). Lab run 2026-09-29, 1h bars, 14 FX
pairs over 415 weekends, 2 metals over 429, 6 generated walks over 605.

## The question

[`fridayflag.md`](fridayflag.md) found one directional signal in the weekend gap. It reverses
Friday's last 4 hours, with rank r −0.242 and −0.234 in the two halves against −0.03 on walks. The
desk asked whether that can be traded: enter on Friday before the close, exit at Sunday's open, and
take the gap's direction.

Two things could make the reversal useless:

- **Bid-ask bounce.** MT5 bars are bid prices. A noisy last print at a wide Friday spread would
  "reverse" at the open with nothing tradable behind it.
- **The cost at the open.** Sunday's opening spread is several times the weekday one, and the gap
  is paid through it.

## Method

Per pair and weekend, j is Friday's last 1h bar and j + 1 is Sunday's first.

- **Signal:** side = −sign(log(close[j−lag] / close[j−lag−K])), for K = 1, 4 and 8 hours and 120
  (the week).
- **Entry:** close[j − lag], with lag = 0, 1 or 2 hours. This is the bounce test: a real reversal
  survives an earlier entry, and a bounce at the final print does not.
- **Exit:** Sunday's first open, or the close of Sunday's first hour, after the opening spread has
  come in.
- **Cost:** MT5's recorded spread for each bar, on the side that crosses it. A long pays the entry
  bar's spread (it buys at the ask); a short pays the exit's. The open exit is charged Sunday's
  first bar; the 1h exit, Sunday's second.
- **Swap:** read from the terminal's symbol info and reported, not charged.
- **Scoring:** the first 60% and last 40% of weekends. Pooled t and 95% intervals come from a
  bootstrap over whole weekends, because a weekend is shared by every pair.
- **Controls:** FX-calendar walks we generate (iid Student-t(3) through the week and an independent
  weekend gap). Deriv indices trade through the weekend and have no gap, so they are not in this
  study.

Pre-registered: the trade is worth building if, in pooled FX, the lag-0 net of the recorded spread
is positive in both halves with a verification 95% interval above zero, lag 1 keeps at least half
of lag 0's gross, and the walks' intervals contain zero.

## Results

### The reversal is real, and it is not bounce

Pooled FX, fading the last 4 hours. Gross bps (t) and hit rate, discovery | verification:

| lag | exit at Sunday's open | exit after Sunday's first hour |
|---|---|---|
| 0 | +2.11 (5.0) 56.8% \| +2.33 (3.0) 54.1% | +2.29 (4.6) 57.7% \| +1.68 (2.2) 55.8% |
| 1 | +2.22 (4.6) 55.4% \| +2.09 (3.0) 56.4% | +2.09 (3.3) 55.2% \| +1.23 (1.8) 55.9% |
| 2 | +2.71 (5.0) 57.3% \| +1.26 (1.9) 52.7% | +1.84 (3.0) 56.5% \| +0.60 (0.9) 53.1% |

- **It survives an earlier entry.** At lag 1 it is +2.22 and +2.09 against lag 0's +2.11 and +2.33.
  A bounce at the final print would have vanished.
- **Every one of the 14 pairs is positive** at lag 0, K = 4, exit at the open: +0.94 (EURAUD) to
  +3.76 bps (USDCHF), t +1.3 to +5.0.
- **K = 4 is the strongest window.** K = 1 and K = 8 are weaker (+0.4 to +1.7 in verification), and
  fading the whole week does nothing (+0.4 to +1.3, t ≤ 1.5).
- **In volatility units it is small:** +0.24 to +0.34 hourly vol per weekend.

### The cost eats it

Recorded spreads, median bps. On the weekday, Friday's last bar and Sunday's second bar they are
ordinary; at Sunday's first bar they are several times wider:

| pair | weekday 07–17 UTC | Friday's last | Sunday's first | Sunday's second |
|---|---|---|---|---|
| EURUSD | 0.00 | 0.00 | 0.62 | 0.09 |
| GBPUSD | 0.07 | 0.08 | 1.68 | 0.08 |
| USDJPY | 0.09 | 0.09 | 0.71 | 0.09 |
| USDCHF | 0.11 | 0.12 | 4.70 | 0.22 |
| GBPJPY | 0.21 | 0.25 | 3.70 | 0.28 |
| CHFJPY | 0.33 | 0.49 | 7.59 | 0.64 |
| EURCHF | 0.18 | 0.19 | 4.42 | 0.27 |

Pooled FX, verification half, lag 0, K = 4:

| exit | gross (breakeven) | spread paid | net [95%] |
|---|---|---|---|
| Sunday's open | +2.33 | 2.10 | **+0.23 [−1.26, +1.81]** |
| after Sunday's first hour | +1.68 | 0.36 | **+1.31 [−0.17, +2.73]** |

- **Exiting at the open pays the open's spread**, 2.1 bps on average against a 2.3 bps edge. Per
  pair, net at the open runs from −1.74 (CHFJPY) to +1.35 bps (EURUSD).
- **Waiting out the first hour** avoids most of the spread (0.36 bps), but gives back a third of the
  edge. Its interval still touches zero.
- **Two costs are not in "paid":**
  - *Swap.* One night is held past Friday's rollover. The terminal's swaps average −0.39 bps per
    night over the 14 pairs (long and short averaged, range −0.20 to −0.78); the triple swap falls
    on Wednesday, so Friday is a single night.
  - *Commission.* EURUSD's recorded spread is 0.0 on weekdays, which suggests a raw-spread account
    that charges commission per lot instead. On such an account a round trip is typically another
    0.5–0.7 bps; the size of this account's commission is not in the data.
- **Taking both into account,** the best variant's +1.31 bps comes down to roughly +0.2 to +0.4
  bps.
- **MT5's bar spread is a floor, not the fill.** On many brokers it is the lowest spread seen in the
  bar, so the first minutes of Sunday are likely worse than the 0.6–7.6 bps recorded.

### Metals and the control

- **Metals do not reverse.** XAUUSD is −0.32 bps (t −0.2). The pooled verification half runs the
  other way, −9.96 bps (t −3.0), driven by silver, after +2.74 in discovery. It is unstable in sign.
- **The walks read zero.** 22 of 24 variants' verification intervals contain zero. The two that
  don't (lag 2, K = 4: +3.59 and +3.79 bps, lower bounds +0.20 and +0.23) are what 24 tries give by
  chance, and their discovery halves are negative.

## What this means

- **The weekend gap does reverse Friday's last hours, by about 2 bps, in all 14 FX pairs and in
  both halves.** It survives an entry an hour earlier, so it is not bid-ask bounce at the final
  print.
- **It is not a trade.** The pre-registered test fails:
  - exiting at the open, Sunday's spread takes the whole edge (net +0.23 [−1.26, +1.81]);
  - exiting after the first hour leaves +1.31 [−0.17, +2.73] before swap (≈ −0.4 bps) and any
    commission (≈ 0.5–0.7 bps), and the interval already includes zero.
- **The cost is the binding constraint, not the signal.** At about 0.3 hourly vol per weekend, the
  edge is roughly what one wide spread costs.

## For production

- **Nothing to build as a trade.**
- **One useful reading for positions already open:** a position that gained in Friday's last hours
  should expect about 2 bps of it back at the open, on average. That is not worth acting on, but it
  is a reason not to add in Friday's last hours.
- **A cheaper route would change the answer.** An account whose spread at Sunday's open is near the
  weekday spread, commission-free, would turn the 1h-exit variant into a candidate. That is only
  worth revisiting with the account's real Sunday-open fills, or tick-level spreads from the first
  minutes of the week, which the bar data does not have.
