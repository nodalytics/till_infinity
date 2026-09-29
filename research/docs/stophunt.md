# Being stopped out before the market goes our way: does an entry trigger prevent it?

Harness: [`research/harness/stophunt.py`](../harness/stophunt.py). Lab run 2026-09-29.

## The question

The desk's complaint is that a zone trade is often right about direction but early: price runs the
stop, then goes where the trade said. The hope is that a lagging indicator times the entry well
enough to avoid that. [`indicators.md`](indicators.md) scored fixed-horizon returns and never tested
this path-dependent claim, and [`widestop.md`](widestop.md) found that a wider stop halves the
stopped share while price P&L stays flat. So this measures the complaint itself, trade by trade,
with a stop and a target.

It also answers a direct production question: would switching on `TRADING_REQUIRE_CANDLE`, which
makes the desk wait for production's own candlestick confirmation, cut stop-outs and improve R?

## Method

- **Zones.** Every touch the production `Engine` opens (44,732 real-market and 29,188 Deriv touches,
  15m and 1h, the same replay as `indicators.py`), faded: long when price came down onto the level,
  short when it came up.
- **Stop, anchored to the level, not the entry.** The level minus (long) or plus (short) B x the
  bar's volatility x price, for B = 0.5, 1 and 2.
- **R.** The actual risk from *that* entry to the stop, so a later entry changes its own R, as it
  would live. Entries with R under 0.25 bar volatility are skipped.
- **Targets.** 1R, 2R and 3R. Time limit 40 bars, marked to the 40th close. A bar that touches both
  stop and target counts as stopped.
- **Cost.** The round trip in bar volatilities (FX 0.8, crypto 0.5, metals 0.16, Deriv 0.15, all
  scaled to the interval), expressed in R.
- **Entries**, each within 8 bars of the touch:
  - the touch itself;
  - the triggers from `indicators.py`: rsi, stoch, stochrsi, bb, ema, sma, macd and fib+rsi;
  - **sweep**: price trades through the level without closing beyond the stop, then closes back on
    the level's side. This is the stop-hunt pattern described;
  - **candle**: production's confirmation, `trading/candles.py` `confirms()` called exactly as
    `trading/service.py` `_candle_at` calls it. It takes the last 3 closed bars, a tolerance of 0.25
    vol, and enters at the first confirming close. The one difference is that the volatility here
    is the bar volatility, where production reads its own per-feed estimate.
  - **wait:x**: every touch entered after a delay drawn from x's own delays, independent of the path.
- **"Stopped then right".** Stopped, and then the target price reached within the same 40 bars. This
  is the complaint, measured.
- **Controls.** Walks we generate ourselves (iid Student-t(3), memoryless), run through the same
  engine and the same scoring. Deriv's indices are a market and are reported as their own family.

**Pre-registered rule.** Against the touch, a rule must lower *both* the stop rate and the
stopped-then-right rate, and raise net R by at least 0.05R with clustered t >= 3, in both halves, on
real markets, and not on walks.

**Two amendments, both written before the data they were applied to:**

1. **After the smoke test on walks.** Later entries improve R on memoryless walks for a mechanical
   reason. A stop anchored to the level is further from an entry made after price has moved away,
   so the cost is fewer R and a bar spanning both stop and target is rarer. EMA and SMA gained
   +0.12-0.15R on walks (t 4.2-4.4). So each market cell is also compared with the same cell on the
   walks.
2. **After the first full run.** The literal passes ranked the families by their cost (FX 0.8 >
   crypto 0.5 > metals 0.16), which walks costed at 0.15 cannot net out, since the cost-per-R gain
   scales with the cost. So the comparison with the walks is made on **gross** R, before costs. Net
   R still has to clear the literal rule.

## Results

**The complaint is real in size, and memoryless walks show it just as often.** Touch entries, 15m,
target 2R:

| stop buffer | FX: stopped | FX: stopped then right | walks: stopped | walks: stopped then right |
|---|---|---|---|---|
| 0.5 vol | 64.5% | 29.7% (46% of stops) | 66.3% | 32.5% (49% of stops) |
| 1 vol | 62.4% | 24.5% (39% of stops) | 64.8% | 26.6% (41% of stops) |
| 2 vol | 57.3% | 14.7% (26% of stops) | 60.4% | 14.9% (25% of stops) |

About 4 in 10 stopped trades would have reached the target later in the window, and on noise the
share is the same or slightly higher. The same holds on crypto (38%), metals (42%) and Deriv (37%) at
the 1-vol stop. It is the geometry of a stop about 1 vol away against a 2R target over 40 bars, not
a market that hunts stops.

**The triggers lower the stop rate, but so does waiting on noise.** FX 15m, 1-vol stop, 2R target:

| entry | trades | stopped | stopped then right | net R | net vs touch (t) | gross vs touch (t) | gross vs walks (t) |
|---|---|---|---|---|---|---|---|
| touch | 18,509 | 62.4% | 24.5% | -0.351 | | | |
| macd | 36.7% | 52.5% | 10.5% | -0.173 | +0.178 (+8.1) | +0.007 (+0.3) | -0.016 (-0.5) |
| sma | 47.5% | 55.6% | 13.4% | -0.194 | +0.157 (+7.3) | +0.003 (+0.1) | -0.015 (-0.5) |
| ema | 72.7% | 58.8% | 16.0% | -0.253 | +0.097 (+5.1) | -0.016 (-0.8) | -0.044 (-1.7) |
| candle | 14.6% | 63.0% | 23.2% | -0.260 | +0.090 (+2.7) | +0.011 (+0.3) | -0.021 (-0.4) |
| sweep | 63.0% | 64.2% | 26.3% | -0.301 | +0.050 (+2.7) | +0.001 (+0.1) | -0.013 (-0.5) |
| rsi | 11.2% | 62.2% | 20.6% | -0.376 | -0.025 (-0.7) | -0.048 (-1.3) | -0.067 (-1.4) |
| stoch / stochrsi / bb | 22-32% | 62.4-63.4% | 24.3-25.4% | -0.38 | -0.03 | about 0 | about 0 |

The same cell on our walks: touch stopped 64.8%, macd 54.1% and 10.5%, sma 56.7% and 11.5%, ema
59.6% and 15.7%. The triggers lower the stop rate and the stopped-then-right rate by the same amount
on memoryless noise. They enter after price has moved away from a stop anchored to the level, so
the stop is further away. They are not catching a better moment.

**Pass counts** (of 9 buffer x target cells per family and interval):

| family, 15m | literal rule (net R) | literal rule and gross R beats the walks |
|---|---|---|
| FX | sma 9, macd 9, ema 6, candle 1 | **0** |
| crypto | sma 5, macd 5, ema 2 | **0** |
| Deriv | sma 2, macd 2, ema 2 | **0** |
| metals | macd 1 | **0** |
| our walks | sma 3, macd 3, ema 2 | (control) |

Nothing passes at 1h in any family. Once the walks are compared before costs, no rule passes
anywhere.

**Other families**, 15m, 1-vol stop, 2R, gross R against the touch:

| family | macd | sma | candle |
|---|---|---|---|
| crypto | +0.040 (t 1.0) | +0.045 (t 1.2) | +0.004 (t 0.1) |
| metals | +0.012 (t 0.3) | -0.037 (t -0.9) | -0.033 (t -0.5) |
| Deriv | +0.019 (t 0.8) | -0.005 (t -0.2) | +0.014 (t 0.5) |

Every trade loses after costs, whatever the entry. On FX the touch nets -0.351R and the best trigger
-0.173R.

## What this means

- **Being stopped before the market goes our way is real and frequent**: 4 in 10 stopped trades
  would have reached the target later in the window.
- **But it happens exactly as often on memoryless noise.** A stop about 1 vol past the level sits
  inside ordinary noise, and over 40 bars noise wanders back past the target as often as not. There
  is no stop hunt here to time around: the sweep entry, which waits for exactly that pattern, gains
  nothing (gross +0.001, t 0.1).
- **The indicators "work" the same way on noise.** Waiting for a MACD, SMA or EMA reclaim cuts
  stop-outs by up to 10 points and "stopped then right" by more than half. But it does that on our
  walks too, because the wait itself moves the entry away from the stop.
- **Before costs, no trigger improves R** on any family, interval or buffer (the best is +0.045R, t
  1.2, crypto SMA).
- **The net-R gain on FX is cost arithmetic, not timing.** A later entry with a larger R pays the
  same spread in fewer R. At constant money risk that is a smaller position paying a smaller spread,
  which is `widestop.md`'s finding from the entry side. It makes a losing trade lose less (FX -0.351R
  becomes -0.173R). It does not make it win.
- **The part of the idea that holds:** if the desk wants fewer stop-outs, the lever is where the stop
  sits relative to noise (buffer B), not an indicator. At a 2-vol buffer the stopped-then-right
  share falls from 39% to 26% of stops on FX, on noise the same. And as `widestop.md` showed, that
  changes the trade's size, not its expectancy.

## Would switching on `TRADING_REQUIRE_CANDLE` help?

**No.** On FX 15m with a 1-vol stop and a 2R target:

- **Stop-outs don't fall:** 63.0% against 62.4% for the touch.
- **"Stopped then right" barely moves:** 23.2% against 24.5%.
- **R before costs doesn't move:** +0.011R, t 0.3.
- **It gives up most of the trades:** it trades 14.6% of touches.

It is the same in crypto (+0.004R, t 0.1), metals (-0.033R, t -0.5) and Deriv (+0.014R, t 0.5).
Its only net gain on FX, +0.090R at t 2.7, is the same cost-per-R effect as above, and it passes
the literal rule in 1 of 18 FX cells. Leave `TRADING_REQUIRE_CANDLE` off.

## For production

- **No entry trigger ships:** none of the eight indicators, the sweep, or the candle confirmation.
- **`TRADING_REQUIRE_CANDLE` stays off.**
- **If stop-outs are the concern, the question is the stop's distance from the level in volatility
  units, judged at constant risk.** [`widestop.md`](widestop.md) already answers that: a wider stop
  at constant risk is a smaller trade, not a better one.
- **Any strategy that already waits for a moving-average or MACD cross** is paying for a delay that
  buys only cost arithmetic. `indicators.md` found the same delay costs 0.07-0.13 vol per trade on FX
  15m in fixed-horizon terms. It is worth checking production's own entries in R before changing
  one.
