# At equal money at risk the widest stop has the thinnest tail, and the volatility state does not change that

Measured 2026-09-24 on the lab's seqlab bars: 15 FX pairs, gold and silver, BTC/ETH/SOL, and
every Deriv synthetic family the lab carries - Volatility (20 series), Jump (5), Step (9),
Boom (9), Crash (9), Range Break (2), DEX (6), Drift Switch (3) - at 15m, 1h and 1d. Every
series passed the close-location leak check except `Drift_Switch_Index_20` at 15m (+0.15,
skipped). Harness: [`stopgrid.py`](../harness/stopgrid.py).

The question: production halves *size* when `tr_percentile` >= 0.8 and leaves the stop where
it was. Should it also *widen* the stop there - or is there a better rule?

**Short answer: no rule that depends on the state beats one that does not.** With the money
at risk held equal, a wider stop at a proportionally smaller size has a thinner tail in every
family, at every interval, in both halves of the test period. It helps about as much in the
calm state as in the hot one. On FX the worst losses come from weekend gaps, and those arrive
more often in the calm state than the hot one. On the synthetics the state is noise. So
switching the stop width on `tr_percentile` gets part of a uniform widening's benefit and
none of anything else.

## The set-up

A rule is `(k_lo, k_hi, theta, m)`: below `theta` a stop at `k_lo x U` at size `1/k_lo`;
at or above it a stop at `k_hi x U` at size `m/k_hi`. Every loss is therefore capped near
**-1R** (or -m in the hot state). A wider stop means a smaller position, not more risk. Only
a gap, a jump or the spread goes past the cap.

| | |
| --- | --- |
| grid | k in {0.5, 0.75, 1, 1.5, 2, 3}; theta in {0.5 ... 0.95}, six values; m in {1, 0.5}: **402 rules** |
| positions | always long, always short, momentum (sign of the last 20 closes), held H = 8 bars at 15m, 5 at 1h and 1d |
| U | trailing mean \|log return\| (500 bars, 250 daily) x sqrt(H) |
| state | `tr_percentile`: 14-bar EWMA of true range, ranked in its own last 1500 bars, known at the entry close |
| stops | resting orders taken by the wick, filled at the level or at a gapping open (`bars.race`) |
| cost | a round-trip spread, `questions.COST_V` for real markets and `catalogue.md` for synthetics, paid at the position's size, so a wider stop pays less of it in R |
| sample | every H-th bar (no overlap); each series split 60/40 by time; rules chosen on the first 60% only, reported on the last 40%, which is also split into halves A and B |
| units | R of the flat rule (1U stop, size 1) |

Named rules: **flat** = 1U always. **production** = 1U, size halved at >= 0.8. **widen** =
1U, becoming 2U at half size at >= 0.8 (equal money). **widen x.25** = 2U at a quarter size at
>= 0.8, which risks the same money as production.

## The tail: expected shortfall of the worst 1%, test period

The momentum position stands in for "whatever the desk holds". Boom and Crash are shown on
the spike side, where the stop sits beyond the spike: a short on Boom, a long on Crash.

| | no stop | flat 1U | production | widen | 2U always | **3U always** |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| FX 15m | -5.54 | -2.43 | -2.37 | -2.38 | -1.41 | **-1.16** |
| FX 1h | -5.79 | -1.93 | -1.77 | -1.78 | -1.20 | **-1.07** |
| FX 1d | -5.11 | -1.18 | -1.16 | -1.16 | -1.05 | **-1.01** |
| metal 1h | -5.65 | -1.41 | -1.32 | -1.33 | -1.06 | **-1.01** |
| crypto 1h | -5.31 | -1.07 | -1.07 | -1.07 | -1.03 | **-1.02** |
| Boom short 1h | -3.68 | -2.50 | -2.44 | -2.44 | -1.56 | **-1.21** |
| Crash long 1h | -3.63 | -2.50 | -2.43 | -2.43 | -1.57 | **-1.20** |
| DEX 1h | -3.74 | -2.54 | -2.53 | -2.53 | -1.58 | **-1.21** |
| Volatility 1h | -3.39 | -1.02 | -1.02 | -1.02 | -1.01 | **-1.01** |
| Step 1h | -3.35 | -1.01 | -1.01 | -1.01 | -1.01 | **-1.00** |

Wider is thinner at every interval, and 3U beats 1U in both test halves in 92 of 93
(interval, family, position) cells. Production and widen differ from flat and from each other
by hundredths, with signs that vary from cell to cell. The stop removes most of
the tail on its own: without one the worst 1% averages -3.4R on the synthetics and -5 to -6R
on real markets. Everything left beyond -1R is gap, spike and spread. All three shrink as 1/k
at equal money at risk:

| family, 1h | share of 1U stops that gapped | slip past the stop, 1% worst (R) | worst single stop (R) | the same at 3U: 1% / worst |
| --- | ---: | ---: | ---: | ---: |
| FX | 2.5% | -0.89 | -10.2 | -0.49 / -2.7 |
| metal | 1.6% | -0.36 | -3.1 | -0.12 / -1.3 |
| crypto | <0.1% | 0.00 | -2.5 | 0.00 / -0.2 |
| Boom / Crash, spike side | (every stop is a jump) | -1.5 / -1.6 | -2.7 / -2.5 | -0.4 / -0.7 and -0.35 / -0.5 |
| DEX | (every stop is a jump) | -1.6 | -3.0 | -0.6 / -0.7 |
| Volatility, Step, Jump, Range Break | <0.2% | 0.00 | > -0.4 | 0.00 |

FX at 15m is worse again: 2.9% of stops gapped, the 1% slip was -1.6R and the worst was -11R.
Almost all of it is the weekend. A 2-hour hold entered after 19:00 UTC on a Friday reopens on
Sunday night.

## The state knows about stop *frequency*, not about the tail

Stop rate of a 1U stop, and the 1% expected shortfall at 1U, split by `tr_percentile`
(1h, momentum, test):

| | stop rate, hot | stop rate, calm | ES1 at 1U, hot | ES1 at 1U, calm |
| --- | ---: | ---: | ---: | ---: |
| FX | **48.8%** | 39.2% | -2.09 | -1.89 |
| metal | **47.4%** | 37.4% | -1.48 | -1.39 |
| crypto | **52.1%** | 34.9% | -1.06 | -1.06 |
| Volatility | 42.2% | 42.3% | -1.02 | -1.02 |
| Boom | 40.9% | 39.0% | -2.05 | -2.33 |
| Crash | 39.1% | 40.1% | -2.02 | -2.33 |
| Jump | 41.1% | 41.3% | -1.02 | -1.02 |
| Step | 42.4% | 42.0% | -1.01 | -1.01 |

* **On real markets the hot state is hit more often: 1.2 to 1.5 times the stop rate**, as
  `riskswitch.py` found. The tail per stop barely moves, because the stop caps it either way.
* **On the synthetics the state is noise.** A generator with a constant volatility has no
  volatility regime, so the top fifth of `tr_percentile` is just the top fifth of sampling
  error. Stop rates match to a point or two and the tails do not separate. The switch
  deciding anything for Volatility, Step, Jump, Boom or Crash is decoration.
* **The FX tail lives in the calm state.** At 15m the long's ES1 at 1U is **-2.99 calm
  against -2.00 hot**, and at 1d it is -2.72 against -1.38. Weekend gaps and holiday
  reopenings follow quiet Fridays, and a quiet Friday is exactly what a 14-bar true-range
  average calls calm. At 1h the hot state is worse (-2.60 against -2.09). A 3U stop takes both
  states to -1.07 to -1.23.

This is why "widen only when hot" cannot compete with "widen": the gaps it needs to shrink
mostly happen when it has not switched on.

## Choosing on training, reporting on test

The rule was chosen per (interval, family, position) - 31 interval-family pairs x 3 positions
= 93 selections - on the first 60%, by the best 1% expected shortfall with ties to the higher
mean. Each group holds only rules that risk the same money as the rule they would replace,
because a rule that risks less always wins a tail contest:

| group | rules | what training chose | test: ES1 better than the comparator | both halves |
| --- | ---: | --- | ---: | ---: |
| A: any widths, m = 1, vs flat | 186 | **3U always** in 90 of 93 | 93 of 93, median +0.03R, up to +1.6R | 92 of 93 |
| C: 1U when calm, any width when hot, m = 1, vs flat | 36 | 1U -> 3U at theta = **0.5** in 63 of 93, the lowest theta offered | 54 of 93, median 0.00 | 43 of 93 |
| B: production's risk (m = 0.5 at 0.8), vs production | 36 | **3U \| 3U x0.5** in 57 of 93 | 93 of 93, median +0.04R | 93 of 93 |
| production vs flat | - | - | 47 of 93, median 0.00 | 35 of 93 |
| widen x.25 vs production | - | - | 11 of 93, median 0.00 | 7 of 93 |

Of the 186 rules, the winner is the uniform one in 90 selections of 93. When the hot state is
the only lever (group C), training asks to use it as often as possible: theta = 0.5, which
means "widen whenever the state is above its median". That is a uniform widening applied to
half the bars. So the state carries no information about stop width. Across 402 rules x 93
cells a few thousand comparisons were made, and nothing here rests on a borderline one: the
ES1 gains are arithmetic (slip and spread divided by k), not estimates near 2 SE.

**The production switch itself does very little to a stopped position's tail.** It improves
ES1 in both halves in only 35 of 93 cells, by 0.1-0.2R on FX and metal at 1h and by
nothing elsewhere. Earlier pages measured it cutting the 1% tail by 10-14% on *unstopped*
positions. That result stands - it is simply the part of the tail that a stop already
removes. Adding a 2U stop in the hot state at production's risk (widen x.25) changes ES1 in
11 of 93 cells.

## What it costs: mean R, test period

These toy positions have no edge, so their mean is the price of the rule: spread, slip, and
whatever the path does after a stop is touched. Momentum position, 1h:

| | flat 1U | production | widen | 3U always | spread per trade at 1U -> 3U |
| --- | ---: | ---: | ---: | ---: | ---: |
| FX | -0.135 | -0.122 | -0.120 | **-0.036** | 0.103 -> 0.034 |
| metal | -0.001 | -0.002 | +0.002 | +0.007 | 0.021 -> 0.007 |
| crypto | -0.054 | -0.049 | -0.046 | -0.017 | 0.065 -> 0.022 |
| Boom short | -0.105 | -0.094 | -0.086 | **-0.004** | 0.017 -> 0.006 |
| Crash long | -0.131 | -0.117 | -0.110 | **-0.013** | 0.022 -> 0.007 |
| Volatility | -0.023 | -0.020 | -0.020 | -0.009 | 0.022 -> 0.007 |

On FX, crypto and Volatility almost all of the difference is spread: a 3U stop at a third of
the size pays a third of it in R. On the spike side of Boom and Crash it is the spike slip,
which a wider stop divides by 3. The "stop tax" - the stop's R minus holding the same size
without it, before spread - is within 0.06R of zero at 1U on FX, metal, crypto, Volatility
and Step at 15m and 1h. Stops neither systematically sell the low nor save the position here.

**The mean does not favour 3U in every cell.** In 18 of 93, both test halves favour the 1U
flat rule over 3U:
Range Break and Drift Switch at 15m and 1h, and some Jump cells. Range Break's is a defect,
covered below. Drift Switch's looks real - its stops carry +0.04 to +0.09R of tax, because
a stopped position in a drift regime would have kept losing - and it is also the family whose
15m series failed the leak check on persistence.

## What this does not show

* **An edge.** The positions know nothing, so the table prices the stop, not the strategy. At
  equal money at risk a 3U stop means a third of the exposure. A strategy with real edge
  earns a third of it, and its targets, written as multiples of the stop, move with the stop.
  Whether that trade is worth it can only be answered on the strategies' own entries.
* **Fills inside a bar.** `bars.race` fills at the level unless a bar opens beyond it. On a
  continuous path that is slightly optimistic: in a simulated random walk it misses the tick
  overshoot, worth +0.02R per trade at 1U. On a jump it is badly wrong: on simulated
  Boom ticks it made a short's 1U stop look like **+0.19R a trade against -0.009R
  exact**. So on the spike side of Boom, Crash and DEX the stop fills at the extreme of the
  bar that took it. Against the exact tick fill that overstates the loss per stop by about
  0.09R (-1.58 against -1.50), so the spike-side columns are slightly pessimistic.
* **Jump and Range Break, honestly.** They jump both ways, so neither fill is right. Range
  Break on the level fill shows a +0.29R mean for a 1U stop at 15m. That is not an edge: it
  is the fill pretending the break stopped at the level. On the bar-extreme fill the same
  rule's ES1 is **-5.95R** instead of -1.04R. The truth lies between the two, and the ordering
  - wider is thinner - holds under both bounds.
* **Daily synthetics and daily metal/crypto.** 173 to 1,685 test entries per family, so ES1
  there rests on 2 to 17 trades.
* **One outlier to know about.** The 1d FX long's worst outcome is **-137R**: EURCHF entered
  on 2014-12-31, and the broker's daily history has no bars from 1 to 17 January 2015. The
  next bar opens after the SNB removed the floor, and U was tiny because the pair was pegged.
  The loss is real in kind - a pegged market breaks - but its size is set by the hole.
* **Costs** for DEX and Drift Switch are a guessed 0.2 (M5-vol units); `catalogue.md` did
  not sample them. FX uses questions.py's 0.8, not the catalogue's 21:00 worst case of 2.3.
* **The research `tr_percentile`** ranks log true range with ties averaged. Production counts
  strictly-below values of `ewma_tr_bps`. Neither difference matters at a 0.8 threshold.

## Defects found on the way

* **The first criterion was wrong, and training showed it.** Tail per unit of standard
  deviation (ES1/sd) chose a 0.5U stop at double size everywhere, because the right tail of
  that lottery inflates its sd. It was replaced by ES1 within equal-risk groups before any
  test number was printed. The harness docstring records both.
* **The first pessimistic fill charged every stop the bar's extreme.** That gave a 0.5U stop
  0.2-0.4R of "slip" on walked paths - Boom's grind side, and Jump. It now applies only
  where the stop sits on the spike side.
* **Unequal-risk rules compared on the tail.** In the first pass, rules risking half in the
  hot state won ES1 by risking less. They now compete only against rules at the same risk.

## What follows

* **No stop-width switch for production.** No state-dependent rule beat a uniform one on
  the tail, and on the synthetics the state carries no information at all. Keep
  `spike_above = 0.8` / `spike_floor = 0.5` as it is. It is cheap, it does no harm, and on
  unstopped exposure it is the measured tail cut. But do not describe it as protecting a
  stopped position's tail: on stopped positions it moved ES1 in a third of cells, by at most
  0.2R.
* **If the stop is to change, change it for every state, and test it on the strategies.** The
  candidate these numbers support is a wider stop at a proportionally smaller size - 2U at
  half, or 3U at a third. On FX it takes the 1h expected shortfall from -1.9R to -1.1R and
  pays a third of the spread. Before that ships it needs the strategies' own entries run
  through it, with targets rescaled, because a toy position cannot price the edge given up.
* **The spike side is the exception that does not wait.** A short on Boom, a long on Crash or
  the jump side of DEX loses 2.4-2.5R in its worst 1% at a 1U stop, against 1.2R at 3U. This
  is the same arithmetic [`generators.md`](generators.md) gave from ticks: wider and smaller,
  or not that side at all.
* **Weekend exposure on FX is its own risk input.** The largest FX stop losses are Friday
  entries gapping on the Sunday reopen, in the *calm* state. A time-to-weekend flag -
  `horizons.py` already builds `to_weekend` - would target them. `tr_percentile` cannot.
* **Not yet measured:** the same grid on the live book's own trades, and a 3m or tick replay
  for Jump and Range Break stop fills, which would replace the two bounds with a number.
