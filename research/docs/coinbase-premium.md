# Coinbase premium

**Measured 2026-09-19 on 23 days of our own quotes. It does not survive.**

The claim: the gap between BTC/USD on Coinbase and BTC/USDT on Binance - the
*Coinbase Premium Index* - proxies US institutional demand, so a positive
premium precedes rallies and a negative one precedes corrections. Trade it
directionally.

Data: `tradingview` quotes, `COINBASE:BTCUSD` (906,003 ticks) against
`BINANCE:BTCUSDT` (741,424), 2026-08-13 to 2026-09-19, resampled to a common
one-minute grid, 33,479 minutes with both legs present.

## 1. The raw sign is a stablecoin basis, not a flow signal

| | |
|---|---|
| mean premium | **−4.03 bp** |
| standard deviation | 4.33 bp |
| negative | **84.1%** of minutes |
| positive | 15.8% |

The premium is almost always negative, and for a reason that has nothing to do
with US demand: **USDT is not a dollar.** It trades slightly below one, so
BTC/USDT prints numerically above BTC/USD and the difference is negative
nearly all the time. "Short when the premium is negative" is therefore a rule
that is short 84% of the time - a constant position wearing a signal's
clothing.

Scored as stated, over 23 days that happened to trend up, it is not merely
unprofitable but inverted, and hugely so: at a one-day horizon the
positive-premium bucket returned **−95.7 bp** and the negative-premium bucket
**+135.0 bp**, a spread of −230.7 bp against the claim. That number is not
evidence the reverse rule works either - it is the sample's uptrend being
picked up by whichever bucket holds 84% of the minutes.

**Any test of this idea has to demean the premium against its own recent
level.** What the story describes - unusual US buying - is a *deviation* from
the prevailing basis, not the sign of the basis.

## 2. It is a level, not an event

Autocorrelation of the premium, in minutes:

| lag | 1m | 5m | 15m | 30m | 1h | 4h | 1d |
|---|---|---|---|---|---|---|---|
| ρ | 0.964 | 0.957 | 0.951 | 0.944 | 0.935 | 0.891 | **0.771** |

Still 0.77 correlated with itself a full day later. This is a slowly drifting
basis, which is consistent with the stablecoin explanation and inconsistent
with a fast flow signal that could be acted on. It answers the first question
asked of it - *how long does the signal last* - with "longer than any scalp,
because it is not really a signal".

## 3. It leads price, barely

Correlation of the premium's change with price returns, by lag:

| k | −60m | −30m | −15m | −5m | −1m | **+1m** | +5m | +15m | +30m | +60m |
|---|---|---|---|---|---|---|---|---|---|---|
| ρ | +0.001 | −0.006 | −0.005 | −0.003 | −0.054 | **+0.077** | +0.009 | +0.005 | −0.021 | +0.012 |

This is the one test the idea passes. The correlation is positive where the
premium *leads* (+1m) and negative where price leads (−1m), so the arrow
points the way the story claims rather than the other way. It is also 0.077,
and gone by five minutes.

## 4. The edge, demeaned, is an artefact of overlapping windows

Conditioning on the premium being more than one standard deviation above or
below its own trailing 24-hour level, sampled **every minute**, looked
convincing - a +7.33 bp spread at four hours with t = +4.55.

It is not. Four-hour windows sampled every minute share 239 of their 240
minutes, so those observations are very nearly the same observation counted
240 times, and the t-statistic is inflated by roughly √240. Re-run on
**non-overlapping** windows - one observation per horizon, no shared minute of
return:

| horizon | n long | long | n short | short | spread | t | p |
|---|---|---|---|---|---|---|---|
| 5m | 1,278 | +0.90 bp | 1,282 | −0.22 bp | **+1.12 bp** | +1.48 | 0.138 |
| 15m | 438 | +1.56 | 424 | +0.63 | +0.92 | +0.43 | 0.666 |
| 1h | 95 | +1.85 | 111 | +5.80 | **−3.95** | −0.50 | 0.618 |
| 4h | 19 | - | 29 | - | *underpowered* | | |
| 1d | 4 | - | 5 | - | *underpowered* | | |

Nothing reaches significance, and the sign flips at an hour.

## 5. And it would not clear the spread anyway

Deriv quoted BTCUSD at bid 81,392.661 / ask 81,411.085 on the day of the
measurement - a spread of 18.42, or **2.26 bp, paid once per round trip**.

The best point estimate anywhere in the honest table is **+1.12 bp** at five
minutes, which is under half the cost of taking it. So even granting the
effect at its most flattering non-overlapping reading, and ignoring that it is
not statistically distinguishable from zero, it loses money on execution
alone. For this to be worth trading the demeaned spread would have to be
somewhere north of 4-5 bp.

## What would change the answer

**This is 23 days, and it is not a proof of absence.** At one hour and beyond
the test is underpowered - 95 and 111 observations at 1h, and fewer than 30 at
4h - so the horizons where a slow flow signal would most plausibly live are
exactly the ones this cannot rule on. What would settle it is months rather
than weeks, at which point the 4h and 1d rows become answerable.

Two things are settled now, on this data:

- The **raw-sign** version is refuted rather than unproven. It is a constant
  short dressed as a signal, and the 84/16 split is structural.
- Whatever survives has to beat 2.26 bp to be worth anything, and nothing here
  is close.

Not extended to ETH. There was no point measuring the second instrument while
the first had not produced an effect on the first.
