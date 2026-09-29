# Do lagging indicators time entries at structure zones?

Harness: [`research/harness/indicators.py`](../harness/indicators.py). Lab run 2026-09-29.

## The question

The desk's framing is that nobody trades support and resistance as such. A level marks a *zone of
interest*, and an indicator tells you when to enter inside it. Structures supplies the zones. This
study asks whether any of the usual lagging indicators times the entry better than simply taking
the touch: EMA, SMA, RSI, stochastic, stoch-RSI, Bollinger bands, MACD, or a Fibonacci retracement.

## Method

**Zones.** Every touch the production `Engine` opens, replayed over the lab's bars from 2025-01-01
with 15m and 1h interleaved in time, as [`skill.md`](skill.md) does. There are 44,732 zone touches
on real markets and 29,188 on Deriv.

| family | instruments |
|---|---|
| **fx** | EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, EURJPY, GBPJPY |
| **metals** | XAUUSD, XAGUSD |
| **crypto** | BTCUSD, ETHUSD |
| **deriv** | Volatility 75 and 25, Jump 50, Step, Boom 1000, Crash 1000. Deriv is a market, not a control. |

**The trade.** Each trade fades the arrival: long when price came down onto the level, short when
it came up. Taking the break instead is the same trade with the sign flipped.

**Entries.** Each touch at bar i is entered at the close of the trigger bar, in
[i, i + 8]. If the rule never fires, there is no trade.

| rule | trigger (long shown; short mirrors) |
|---|---|
| **touch** | enter at the touch, bar i; the baseline |
| **rsi** | RSI(14) crosses back up through 30 |
| **stoch** | %K(14,3) crosses %D(3) below 20 |
| **stochrsi** | the same cross on the stochastic of RSI(14), below 20 |
| **bb** | a close back inside the band (20, 2) after a close outside it |
| **ema** | close reclaims EMA(9) |
| **sma** | close reclaims SMA(20) |
| **macd** | MACD(12, 26) crosses its signal(9) |
| **fib** | enter at the touch, only when the level lies within 0.5 bar-volatility of the 38.2, 50 or 61.8% retracement of the last 50-bar swing; a filter, not a trigger |
| **fib+rsi** | the fib filter and the rsi trigger together |

**Outcome.** The signed log return over H = 5 and 20 bars from the entry close, in units of the
bar's causal volatility, net of round-trip cost. A target-and-stop label earns only drift, so the
signed return is the P&L.

| family | cost at 15m | cost at 1h |
|---|---|---|
| fx | 0.46 | 0.23 |
| crypto | 0.29 | 0.14 |
| metals | 0.09 | 0.05 |
| deriv and walks | 0.09 | 0.04 |

Costs are in bar volatilities: `COST_V` scaled by sqrt(5 / minutes).

**Baselines.** Each indicator is compared, on the same family, interval and horizon, with two
baselines. Both count only returns *after* the entry bar, so both are unbiased on a martingale.

- **vs touch:** every touch, entered at the touch.
- **vs wait:** every touch, entered after a delay drawn from the indicator's own delays but
  independent of the price path. This separates the signal from the waiting.

A first version split each result into "which touches" and "when". Those returns span the path that
fired the trigger, so they were biased by construction: t = 12-25 on memoryless walks. They were
dropped before the run.

**Controls.**
- **walks:** the same engine, rules and scoring on six iid Student-t(3) walks we generate
  ourselves.
- **placebo:** random bars instead of zones, fading the last 5 bars' move.

t-statistics use standard errors clustered by series-day.

**Pre-registered pass rule.** A rule passes if it beats both baselines by at least 0.05 vol with
t ≥ 3, beats the touch in both halves of the 60/40 time split, and the walks show no such
improvement.

## Results

**No rule passes on any family, interval or horizon.** No indicator reaches t ≥ 3 against the
touch in any zone cell. The largest improvements, all below the bar:

| cell | rule | n | net | vs touch (t) | vs wait (t) | halves | the same rule on walks |
|---|---|---|---|---|---|---|---|
| crypto 1h H=5 | macd | 556 | +0.105 | +0.354 (2.3) | +0.276 (1.8) | +0.322 / +0.510 | +0.345 (0.9) |
| metals 1h H=5 | macd | 115 | +0.304 | +0.597 (2.1) | +0.467 (1.7) | +0.487 / +0.782 | +0.345 (0.9) |
| fx 15m H=5 | fib+rsi | 277 | −0.276 | +0.179 (1.4) | +0.206 (1.6) | +0.176 / +0.194 | +0.274 (**2.1**) |
| crypto 15m H=5 | macd | 2,090 | −0.209 | +0.125 (1.8) | +0.094 (1.3) | +0.145 / +0.109 | +0.017 (0.3) |
| metals 15m H=20 | sma | 2,424 | +0.122 | +0.157 (1.0) | +0.120 (0.8) | +0.123 / +0.222 | −0.082 (−1.0) |

This is what chance looks like. About 170 zone comparisons were made (9 rules, 5 families including
walks, 2 intervals, 2 horizons). Four of them reached |t| ≥ 2 against the touch, fewer than the
about eight that chance alone would give. One of the four is on our own memoryless walks (fib+rsi, +0.274,
t 2.1). The two MACD cells at 1h rest on 556 and 115 trades, and MACD shows a similar-sized, equally
insignificant lift on the walks at 1h.

### Does fading the zone pay at all?

No. The touch baseline is negative after costs in every real family. Gross of cost it is close to
zero:

| family | 15m H=5 | 15m H=20 | 1h H=5 | 1h H=20 | touches (15m / 1h) |
|---|---|---|---|---|---|
| fx | −0.455 (gross +0.007) | −0.440 (+0.022) | −0.158 (+0.073) | −0.220 (+0.011) | 20,751 / 1,474 |
| metals | −0.086 (+0.006) | −0.035 (+0.057) | −0.293 (−0.247) | −0.417 (−0.371) | 5,460 / 340 |
| crypto | −0.334 (−0.045) | −0.336 (−0.047) | −0.250 (−0.106) | −0.295 (−0.151) | 6,283 / 1,752 |
| deriv | −0.099 (−0.012) | −0.086 (+0.001) | −0.030 (+0.013) | −0.044 (−0.001) | 18,605 / 5,663 |
| walks | −0.095 (−0.008) | −0.079 (+0.008) | +0.044 (+0.087) | +0.522 (+0.565) | 23,011 / 551 |

Net mean in bar volatilities; gross in brackets.

- **The break direction does not pay either.** Taking the break is the same gross with the sign
  flipped, so it is also about zero before costs and negative after them. Neither side of a zone
  carries drift.
- **The placebo** (random bars, fading the last 5 bars' move) reads the same as the zones: FX 15m
  H=5 is −0.389 net (gross +0.073) against the zones' −0.455 (+0.007). A zone is no better an entry
  point than a random bar after a move. This matches [`skill.md`](skill.md): structures' measured
  skill is the geometry of its label, not a drift at the level.
- **The walks** read like the markets: gross within ±0.09 wherever n is large. The +0.565 at 1h H=20
  rests on only 551 touches, and its t is not significant.

### One consistent loss: reclaim triggers on FX 15m

Waiting for price to reclaim a moving average *costs* money on FX at 15m, whether or not the bar is
a zone:

| FX 15m H=5 | ema vs touch (t) | sma vs touch (t) | macd vs touch (t) |
|---|---|---|---|
| zones | −0.073 (−2.2) | −0.067 (−1.7) | −0.080 (−1.7) |
| placebo | −0.129 (**−4.0**) | −0.130 (**−3.5**) | −0.119 (**−3.0**) |
| walks, zones | −0.007 (−0.2) | −0.020 (−0.5) | +0.017 (0.3) |

The loss is negative in both halves in the zone and placebo rows, and absent on the walks. A reclaim fires after a
move in the trade's direction, and FX at 15m partly reverses short moves, so the entry arrives after
the part of the move that gets given back. This is a property of FX at 15m, not of zones.

## What this means

- **None of the lagging indicators tested times entries at structure zones.** RSI, stochastic,
  stoch-RSI, Bollinger, EMA, SMA, MACD and Fibonacci fail on every family, including Deriv. The
  largest lifts are the size chance produces in about 170 comparisons, and one of them appears on
  memoryless walks.
- **The zone is not an entry edge by itself either.** Fading the touch is about zero gross
  everywhere and negative after costs; taking the break is the mirror. Random bars after a move read
  the same. The desk's framing, that a zone marks where to look rather than a trade, is the correct
  reading of this. But the indicators do not add the missing timing edge on top of it.
- **Momentum-style confirmation hurts on FX 15m.** Waiting for an EMA, SMA or MACD reclaim loses
  0.07-0.13 vol per trade against entering at once. It is significant on random bars (t −3.0 to
  −4.0), and it matters to any rule that asks for "confirmation" before entering FX at 15m.

## For production

- **Nothing ships as an entry trigger.** No indicator improves on the touch after costs, so there is
  no rule to add to a strategy's accept path.
- **Worth checking in production:** any strategy that waits for a moving-average or MACD cross
  before entering FX at 15m is paying the cost measured above. A strategy that needs confirmation
  should enter at the signal on FX 15m rather than wait for the reclaim. That should be measured on
  production's own entries in R before anything changes.
- **Not tested here:** indicators as *exit* or *filter* rules (skipping a zone, rather than delaying
  the entry), and longer timeframes (4h, daily), where the touch counts were too small in this data.
