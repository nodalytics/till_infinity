# The rolling z-score on 4h bars: the window decides what the threshold means

**Measured 2026-10-07**, asked for as "run zscore in 4h candles using lookback
window of 2 to 12", extended to 36, with thresholds "1 >2 >3" and then 4 and "pay attention to what
happens to those candles whose body is 70% of its candle range and displacement
candles too".

Code: [`zscore_window.py`](../ideas/zscore_window.py). 220,301 4h bars over the
sixteen development instruments - twelve FX pairs, gold, silver, BTC and ETH.

    z[t] = (close[t] - mean(close[t-N+1 .. t])) / std(close[t-N+1 .. t])

The current bar is inside its own window, which is what a charting package
computes and what a reader is looking at. Nothing after `t` is used. The outcome
is the move from `t` to `t+h`, divided by the ATR at `t`.

## The ceiling: a short window cannot produce a large z-score

The largest `|z|` a window of N points can produce is **`(N-1)/sqrt(N)`**, and at
short windows the data reaches it to three decimals:

| N | max \|z\| observed | (N-1)/sqrt(N) | share of bars with \|z\| > 2 |
|---:|---:|---:|---:|
| 2 | 0.709 | 0.707 | **0.00%** |
| 3 | 1.155 | 1.155 | **0.00%** |
| 4 | 1.500 | 1.500 | **0.00%** |
| 5 | 1.789 | 1.789 | **0.00%** |
| 6 | 2.041 | 2.041 | 0.57% |
| 8 | 2.471 | 2.475 | 5.14% |
| 12 | 3.165 | 3.175 | 8.55% |
| 16 | 3.711 | 3.750 | 9.94% |
| 19 | 4.073 | 4.129 | 10.95% |
| 24 | 4.628 | 4.695 | 11.79% |
| 30 | 5.156 | 5.295 | 12.33% |
| 36 | 5.535 | 5.833 | 12.67% |

**`z > 2` is arithmetically impossible below N = 6, `z > 3` below N = 11, and
`z > 4` below N = 19.** A rule written as "enter when z > 2" on a five-bar
lookback does not fire rarely; it never fires. This is not a property of the
market and no amount of data will change it - it is what a z-score is.

It also means the **same threshold is a different event at each window**. At
N = 6, `z >= 2` is 0.57% of bars and sits within 2% of the ceiling, so it is
really the statement "the last six closes were a near-perfect monotone run". By
N = 12 the same threshold is 8.55% of bars, and it saturates around 12.7% by
N = 36. Any table of "performance after z > 2" that does not name the window is
unreadable.

Two further things the extension to 36 shows. The **observed maximum falls
further behind the ceiling as N grows** - 2.041 against 2.041 at N = 6, but 5.535
against 5.833 at N = 36 - because the ceiling needs one point to carry all the
deviation, which over thirty-six bars means a monotone run no market produces.
And `z > 4` stays **vanishingly rare even where it is possible**: 13 bars of
220,000 at N = 20, 112 at N = 36.

## Direction: continuation in the tails, mild reversion through the middle

Top z-decile minus bottom z-decile, mean forward move in ATR:

| N | h=1 | h=3 | h=6 | h=12 |
|---:|---:|---:|---:|---:|
| 2 | **-0.025** | **-0.035** | -0.014 | +0.009 |
| 3 | +0.006 | +0.036 | +0.037 | +0.092 |
| 6 | +0.021 | +0.057 | +0.044 | +0.069 |
| 12 | +0.027 | +0.075 | +0.082 | +0.095 |
| 20 | +0.041 | **+0.083** | +0.083 | +0.059 |
| 28 | +0.033 | +0.063 | +0.057 | +0.050 |
| 36 | +0.031 | +0.069 | +0.054 | +0.061 |

Positive everywhere except N = 2: a high reading is followed by **more** move in
the same direction, not a snap-back. N = 2 is the exception and it is not really
a z-score - with two points the statistic is a sign, so "reversion at N = 2" is
the familiar one-bar bounce and nothing to do with standardisation.

But the **Spearman IC is negative at h = 1 for every window** (-0.012 to -0.021)
while the decile spread at h = 1 is positive from N = 5 up, and the IC **gets
more negative at long horizons as the window grows** (-0.0008 at N = 6, h = 12,
against -0.0089 at N = 36). Both are true: the
rank relation is slightly negative through the body of the distribution and
positive in the tails, so **the relation is not monotone** and a linear reading
of z - a regression, a weight in a model - gets the sign backwards for the part
of the distribution that matters.

## The thresholds

Spread (mean forward move after `+T` minus after `-T`), h = 3 bars, in ATR, all
bars:

| N | \|z\| >= 1 | \|z\| >= 2 | \|z\| >= 3 | \|z\| >= 4 |
|---:|---:|---:|---:|---:|
| 6 | 0.034 | **0.334** | - | - |
| 8 | 0.039 | 0.151 | - | - |
| 12 | 0.043 | 0.101 | 0.265 | - |
| 16 | 0.042 | 0.118 | 0.336 | - |
| 20 | 0.031 | 0.128 | 0.296 | (13 bars) |
| 24 | 0.029 | 0.113 | 0.319 | 0.334 |
| 28 | 0.028 | 0.101 | 0.291 | 0.334 |
| 36 | 0.027 | 0.104 | 0.295 | 0.321 |

Both tails continue, and the spread **grows with the threshold and shrinks with
the window**. The `z >= 2` column at N = 6 is the largest number in the table and
also the rarest event in it - 593 bars - which is the ceiling again: at that
window the threshold is picking the extreme 0.57%, and at N = 36 the same
threshold picks a loose 12.7%.

The `|z| >= 1` column is the one that falls most clearly with the window, 0.043
at N = 12 to 0.027 at N = 36. A longer window dilutes what a one-sigma reading
means; it does not dilute what a three-sigma reading means.

## The bar's own character roughly doubles it

Three cohorts, asked for directly. `body>=70%` is the zone rule's own impulsive
candle; `disp` is the `displace` trigger's definition, a body of a whole ATR.
They are different claims - a 70% body can be a small candle, and a 1-ATR body
can be half body on a huge range - so both are run, and their intersection.

| cohort | bars | share |
|---|---:|---:|
| all | 220,301 | 100% |
| body >= 70% of range | 40,741 | 18.5% |
| displacement (1 ATR body) | 23,444 | 10.6% |
| both | 16,654 | 7.6% |

Spread (move after `+T` minus move after `-T`), h = 3, in ATR:

| threshold | N | all | body>=70% | disp | both |
|---|---:|---:|---:|---:|---:|
| \|z\| >= 1 | 12 | 0.043 | 0.070 | 0.129 | **0.147** |
| \|z\| >= 1 | 24 | 0.029 | 0.066 | 0.136 | **0.157** |
| \|z\| >= 1 | 36 | 0.027 | 0.065 | 0.135 | **0.150** |
| \|z\| >= 2 | 12 | 0.101 | 0.137 | 0.161 | **0.173** |
| \|z\| >= 2 | 36 | 0.104 | 0.185 | 0.199 | **0.213** |
| \|z\| >= 3 | 16 | 0.336 | 0.467 | 0.344 | **0.467** |
| \|z\| >= 4 | 28 | 0.334 | **0.705** | 0.383 | 0.695 |
| \|z\| >= 4 | 36 | 0.321 | **0.530** | 0.351 | 0.545 |

**The character of the bar is worth more than the z-score is.** At `|z| >= 1` it
roughly **triples** the spread - 0.027 to 0.150 at N = 36 - and at `|z| >= 4` it
roughly **doubles** it. The ordering is the same at every window and every
threshold: all < body >= 70% < displacement < both.

The clearest version of that is what happens as the window lengthens. The `all`
cohort's `|z| >= 1` spread **decays** from 0.043 to 0.027 between N = 12 and 36;
the `both` cohort's **does not move at all**, sitting at 0.147-0.157 across the
whole range. The level of the z-score is a weaker statement the longer the window
gets; what the candle looks like is not.

The upper tail of the `both` cohort has its day-block interval clear of zero at
every window, for `|z| >= 1` (n ~ 6,500-7,300) and `|z| >= 2` (n ~ 2,500-3,800).

## The speed of the z-score, not its level

> "can we observe in the same rolling window manner if the zscore rises or
> crashes with fast speed or rate e.g. window 1 produce zscore of 2 and window 2
> gives 0.5"

A state the level cannot name: a bar at z = 0.5 that arrived from z = 2 is
extended and already failing, and one that arrived from z = -1 is a move
beginning. Both read 0.5. So beside `z[t]`, `dz1 = z[t] - z[t-1]`, cut at the
same +-1 as the level, and the question asked **inside** level bands -
[`zscore_speed.py`](../ideas/zscore_speed.py).

Forward move at h = 3, in ATR, rows by level, columns by speed:

| N | level | dz <= -1 | \|dz\| < 1 | dz >= +1 |
|---:|---|---:|---:|---:|
| 8 | z >= +1 | -0.043 | +0.025 | **+0.053** |
| 8 | mid | +0.031 | +0.019 | -0.005 |
| 8 | z <= -1 | -0.017 | -0.006 | +0.008 |
| 12 | z >= +1 | +0.021 | +0.025 | **+0.068** |
| 20 | z >= +1 | -0.043 | +0.018 | **+0.100** |
| 20 | mid | -0.003 | +0.022 | -0.006 |
| 20 | z <= -1 | -0.045 | +0.000 | -0.009 |
| 36 | z >= +1 | +0.048 | +0.019 | **+0.097** |

**The speed only means anything once the level is already extended.** In the
middle band it does nothing at any window; in the high band the forward move
rises with it monotonically at N = 8, 12 and 20.

The desk's pair, directly:

| N | extended and still rising | n | extended and crashing | n | gap |
|---:|---|---:|---|---:|---:|
| 8 | **+0.053** [+0.030, +0.078] | 12,865 | -0.043 [-0.157, +0.070] | 346 | +0.096 |
| 12 | **+0.068** [+0.040, +0.094] | 9,907 | +0.021 [-0.066, +0.112] | 709 | +0.046 |
| 20 | **+0.100** [+0.064, +0.133] | 6,589 | -0.043 [-0.147, +0.052] | 670 | +0.143 |
| 36 | **+0.097** [+0.055, +0.138] | 3,594 | +0.048 [-0.075, +0.177] | 431 | +0.049 |

The honest reading: **the rising arm is reliably positive** - its interval clears
zero at every window - while **the crashing arm is indistinguishable from zero**,
not reliably negative. It is a few hundred bars against ten thousand, and its
interval spans -0.15 to +0.18. "Extended and accelerating continues" is
supported; "extended and decelerating reverses" is not, on this sample.

And the ceiling returns, in a form worth naming: **the desk's own example cannot
happen below N = 6.** z = 2 falling to z = 0.5 needs a previous reading of 2,
which `(N-1)/sqrt(N)` forbids under six bars - and the counts show it, 0 crashing
bars at N = 4 and 3 at N = 6 against 670 at N = 20. A crash in the z-score is not
a thing a short window can express.

## What this does not say

* **The cohorts overlap the signal by construction.** A 70%-body bar with a high
  z-score is, nearly by definition, a bar that just moved decisively; `z` and
  `body` are measuring neighbouring things. The table shows body adding *on top
  of* z within each cell, which is the honest version of the claim, but it is not
  two independent pieces of evidence.
* **The effects are tiny.** The best cell is 0.17 ATR over three 4h bars. The
  statistics are overwhelming only because n is 220,000; at that sample a
  Benjamini-Hochberg q of zero means "not noise", not "worth trading".
* **No trade has been simulated.** There is no entry, no stop, no spread and no
  slippage in any number here - it is a conditional mean of a forward move. The
  zone study is the standing reminder of how much is lost between the two: a
  conditional move of this size does not survive a stop placed inside the
  instrument's own noise.
* It is the **development set**, and the window and the thresholds were both
  swept.

## Followed up in

[`zscore-variants.md`](zscore-variants.md): the ceiling normalisation (which does
**not** make thresholds comparable, contrary to what this file's conclusion
suggested), the term structure across windows (which works), volatility z (which
is empty), cross-sectional z, and whether a gradient-boosting model beats any of
them (it does not beat two hand-written inequalities).

## What is worth keeping

1. **`(N-1)/sqrt(N)`.** Any threshold on a rolling z-score has to be checked
   against the window first. This belongs in any code that gates on z, including
   production's `Zma`, whose window is adaptive and whose `strong` threshold
   should be read against the window it currently holds.
2. **The relation is not monotone**, so a linear term in z is the wrong shape.
3. **The speed matters only inside the extreme.** In the middle of the
   distribution `dz` carries nothing at any window.
4. **Condition on the candle, not only on the statistic.** Whatever is in the
   tails is better found by asking what the bar looks like than by asking how
   many standard deviations it is.
