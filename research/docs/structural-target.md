# A structural take-profit: the leg's extreme, or past the imbalance

The desk's note on its own charts, 2026-10-05: *"The TP is supposed to be just
below those choppy zones upward, way past the imbalance candles."* The target
should not be a multiple of the stop; it should be a place - the extreme the
displacement ran to, or the far side of the gap that displacement left open.

[`lrc-retest.md`](lrc-retest.md) had already settled the *fixed* targets. For R1
the chance of reaching N R before -1R is 0.456 / 0.320 / 0.195 / 0.090 at
N = 1, 2, 4, 10, against 0.5 / 0.333 / 0.2 / 0.091 from 1/(1+N) and the same on
matched walks. No constant distance has an edge, so moving 2R out to 4R or 6R
needed no second test.

A target that moves with the chart is a different claim, and pooled P(N R)
cannot see it: it averages over trades whose own targets sit at different
distances. If structure carries information, a trade whose structural target
happens to land at 3R should reach it more often than 1/(1+3).

It does not.

## The verdict

| | |
|---|---|
| **Does the structural target get reached more often than chance?** | **No.** Over 157 distance bins, the realised P(reach) beats 1/(1+D) in **58** and beats *both* walks in **82** - 52%, a coin flip. Weighted over every bin: real **-0.0413**, iid walk -0.0486, GARCH walk -0.0508. The 0.007-0.010 by which real is less negative is the stop artefact below, not an edge. |
| **Does it make more money than a fixed 2R?** | **No, and for R1 it makes less** - -0.353R against -0.303R on 95,051 trades. The leg extreme sits at a median **0.95R**, so it is a smaller win for the same risk. The same -0.05R appears on both walks, which is how you can tell it is geometry rather than markets. |
| **Past the imbalance?** | **No.** 2,212 R1 trades had an open imbalance to aim past: **-0.382R** against **-0.379R** for the fixed target on the same trades. |
| **Anywhere it helps?** | R5 non-Deriv: XL **-0.348R** against X2 -0.414R, +0.066. But the iid walk gains +0.031 doing the same thing and GARCH gains -0.000, and the sign flips between sources in other cells (R5 V10_1S: GARCH +0.064, real -0.029, walk -0.131). Noise. |

## The targets, as code

In [`lrc_retest.py`](../ideas/lrc_retest.py), beside the fixed 2R on every
trade, so the comparison is the same fill, the same stop and the same costs:

- **XL** - `leg_top`: the highest high between the break bar and the bar before
  the fill. The same window `strength` measures `a_size` over, so the two agree
  by construction. Always available.
- **XI** - `imbalance_top`: the far side of the last **unfilled** three-bar gap
  in that leg, where `low[k+1] > high[k-1]` on the long frame. Unfilled is
  checked against the whole remainder of the leg: a hole price has traded back
  through is history, not a destination. NaN when the leg left no gap, and left
  NaN rather than substituted, so the trades that have one are read on their own.
- **XF** - XI when there is one, XL otherwise. The rule as a desk would trade it.

Each records `d_*`, the target's distance in R, which is the number the whole
question turns on.

## Data

The `lrc-retest.md` run, re-scanned with the new columns: FX, metals, indices,
energy, crypto CFDs, Binance, fresh coins and Deriv, 15m-1d, real against iid
and GARCH walks. **1,928,819 trades** over 603 series (7,686 duplicates
dropped). R1 non-Deriv confirmation reproduces at **-0.303R** against the
published -0.291R, which is the check that the harness still behaves.

## P(reach) against 1/(1+D)

R1, non-Deriv, confirmation half, real, target XL:

| D | n | median D | P(reach) | 1/(1+D) | edge |
|---|---|---|---|---|---|
| 0 - 0.5 | 26,784 | 0.29 | 0.665 | 0.785 | **-0.121** |
| 0.5 - 1 | 22,345 | 0.72 | 0.529 | 0.583 | -0.054 |
| 1 - 1.5 | 13,450 | 1.22 | 0.422 | 0.450 | -0.028 |
| 1.5 - 2 | 8,932 | 1.72 | 0.358 | 0.367 | -0.009 |
| 2 - 3 | 10,327 | 2.42 | 0.288 | 0.292 | -0.004 |
| 3 - 4 | 5,341 | 3.42 | 0.218 | 0.226 | -0.008 |
| 4 - 6 | 4,816 | 4.75 | 0.176 | 0.173 | +0.003 |
| 6 - 10 | 2,417 | 7.19 | 0.119 | 0.120 | -0.001 |
| 10+ | 639 | 11.8 | 0.067 | 0.076 | -0.009 |

The matched iid walk gives the same shape (-0.130, -0.062, -0.024, -0.014,
-0.016, +0.000, -0.003, -0.004, -0.019). Real and walk are the same curve.

**The near bins are biased against the null and the far bins are not.** `mfe`
is the furthest a trade got *before its stop*, while 1/(1+D) is a driftless walk
with no stop at all, so a trade stopped early fails a near target it might
otherwise have reached. That is the whole -0.121 in the first bin. It is also
why the far bins are the honest comparison, and there the edge is zero.

## Mean R

R1, non-Deriv, confirmation. `X2_XI` is the fixed target on exactly the trades
XI could be formed for, so the two are compared like for like.

| src | n | X2 | XL | d_XL | n_XI | XI | X2_XI | XF | d_XF |
|---|---|---|---|---|---|---|---|---|---|
| real | 95,051 | -0.303 | -0.353 | 0.95 | 2,212 | -0.382 | -0.379 | -0.354 | 0.93 |
| walk | 99,212 | -0.299 | -0.361 | 0.81 | 3,037 | -0.329 | -0.298 | -0.362 | 0.78 |
| garch | 99,381 | -0.307 | -0.364 | 0.81 | 3,065 | -0.264 | -0.205 | -0.366 | 0.78 |

XL minus X2 is -0.050 on real, -0.062 on the iid walk and -0.057 on GARCH. A
structural target is worse than a fixed one by the same amount on a random
walk as on a market, which is the definition of a geometric effect.

## What it means

The target was never the problem. A setup whose reach is a random walk at every
distance cannot be repaired by choosing a different place to get out - the only
thing a target changes is the shape of a zero-mean distribution, and the cost is
set by the stop (`cost = cost_px / risk`), which no target touches. The 2R exit
loses 0.29R because the entry is a coin and the stop is 0.78 ATR, not because
2R is the wrong distance.

That does not make displacement and imbalance worthless readings - it makes them
**descriptions rather than destinations**. The one place `lrc-retest.md` found
real markets differing from walks is the strength tercile: a strong move into
and out of the break beats a weak one by +0.025R where the walks show -0.117R,
+0.14R relative and still a losing trade. `displacement_vol` in
[`trading/impulse.py`](../../till_infinity/trading/impulse.py) is the live
version of exactly that quantity, published on every decision for that reason
and gating nothing.

## Also run, and also nothing

Do Boom and Crash spikes follow the higher-timeframe trend?
[`spike_trend.py`](../ideas/spike_trend.py), 76,799 15m bars each on Boom 1000,
Crash 1000 and Jump 50 as a control, trend from the desk's own channel at the
reference constants carried down from 1h, 4h and 1d.

**No.** Crash 1000's spike rate is 4.59-5.90 per 1,000 bars across every trend
bucket at every timeframe, and the spike size is 51.7, 51.7, 53.7 bps in a 1h
uptrend, flat and downtrend. At 4h the *downtrend* bucket has the fewest spikes.
Boom 1000 is the same (49.7-52.5 bps, 4.63-5.43 per 1,000). Every forward-return
interval contains zero. One cell of about 45 excludes zero - Jump 50, 4h
downtrend, +59 bps over 96 bars - which is what a 90% interval does by chance
two or three times in forty-five. [`sweeps.md`](sweeps.md) already had these
spikes memoryless at AUC 0.49-0.50; this adds that they are also trend-blind.

The useful part was a mechanism, not a signal. Crash drifts up and spikes down,
so selling it is a positive-skew, zero-expectation bet - and a stop converts it
into a losing one, because the grind reaches the stop long before the jump
arrives. In the live record 47 of 96 Crash 500 trades exited at the stop, and
11 of 12 on Boom 1000.
