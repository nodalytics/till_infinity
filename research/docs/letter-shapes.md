# Named candle letters are a volatility-clustering reading with no sequence and no side, and the one place they beat a walk is the shape a burst-then-quiet makes

Measured 2026-11-05 on the lab with [`letter_shapes.py`](../harness/letter_shapes.py) and
reported with [`letter_report.py`](../harness/letter_report.py), on bars pulled by
[`seqlab_pull.py`](../harness/seqlab_pull.py): 8 traded markets and 4 Deriv synthetics at a
15-minute base, **198,529 to 294,532 bars each (5.7 to 11.8 years)**, read at four timeframes
and four window lengths. 5,376 census cells, 384 transition cells, 14,058 conditional
volatility cells and 14,226 direction cells.

| question | verdict |
|---|---|
| **A census.** Do named shapes occur at rates a matched random walk does not produce? | **Yes, and almost all of it is volatility clustering.** Against an i.i.d. shuffle of each instrument's own returns the traded panel's median cell ratio is **0.786**; against a **day-block** shuffle of the same series it is **0.942**, and the four generated markets read **0.958 / 0.977**. Benjamini-Hochberg over the z keeps **787 of 5,376** cells against the i.i.d. walk and only **132** against the day-block one. The largest single effect is `L` and its mirror - a sharp drop then a flat shelf - at **1.54x and 1.75x** the i.i.d. walk and **0.84x and 0.86x** the day-block twin, which is a burst-then-quiet signature and not a shape |
| **Transitions.** Does the sequence of completed shapes carry structure beyond a walk's? | **No.** Mutual information between consecutive letters exceeds its own label permutation by **-0.034 to +0.018 bits** across the grid, **31 of 384** cells reach p<0.05 where chance gives 19.2, and **0 survive BH** |
| **Letters as a volatility label**, controlling for the volatility at completion | **A weak one, and much weaker than an impulse.** Pooled by letter on the traded panel, forward volatility over a volatility-and-hour-matched bar runs **-0.037 to +0.083** of a forecast unit at 12 bars, against the **+0.167 to +0.355** [`impulse-vol.md`](impulse-vol.md) measured on the same instruments, the same estimator and the same bootstrap. The i.i.d.-shuffled twin reads -0.019 to +0.019 and the generated markets -0.008 to +0.011, so the reading is real and small |
| Does the volatility **after a W** differ from after an **M**? | **No.** The W-minus-M gap is positive on **3 of 8** traded instruments, mean absolute size **0.050**, every interval straddling zero. On the absolute gate the question cannot be asked at all: a `W` clears `corr >= 0.90` about **three times in eleven years** |
| **The textbook trade for each letter, and its opposite** (carried as a closed claim) | **Null, and worse than its own walk.** On a 2:1 barrier race the traded panel hits **0.3448** against the walk's arithmetic **0.3333** - and the i.i.d.-shuffled twin of the same series hits **0.3670**, beating the real series on **13 of 14 letters**. Net of the quoted round trip **1 of 8** traded instruments is positive (XAUUSD, +0.012R). The opposite side is exactly minus this and is not separately measured |
| Should anything be built? | **No.** The only reading that clears its controls is a weaker restatement of the volatility memory this desk already forecasts |

## The claim, and the ones it is distinct from

[`fractal-twins.md`](fractal-twins.md) embedded 64-bar candle shapes and multi-timeframe ones,
retrieved nearest historical twins and scored direction and volatility against random-walk
controls on 20 instruments and ~1.18 million moments. Its verdict: markets remember their
volatility fractally and their direction not at all. [`bos-predict.md`](bos-predict.md)
separately found a break of structure carries no side beyond the geometry of two levels.

A named letter is a **lower-dimensional special case of those embeddings**, so *"the textbook
trade for each letter, and its opposite"* is a closed claim. It is carried below as an arm that
was expected to be null, with the walk as its null, and the rule that if it came back positive
that would be a finding about selection. It did not.

Three sentences those studies could not have tested, because they measured retrieval quality
and never a shape's **frequency**, its **successor**, or its reading **conditional on the
volatility state**:

1. Do named shapes occur at rates a matched random walk does not produce? A walk makes letters
   too - that is the whole point of the comparison.
2. Does the sequence of completed shapes carry structure beyond a walk's?
3. Does the volatility after a W differ from after an M, controlling for the volatility at
   completion?

## The rules, as frozen before the run

| | |
|---|---|
| base | 15-minute bars, UTC |
| timeframes | 15m, 1h, 4h, 1d, each a **calendar bin** of the base. The slow return is the **sum of the fast returns in the bin**, never a difference of aligned closes, which would make every session gap a fabricated one-bar return |
| windows | 12, 24, 48, 96 bars |
| letters | 14 templates, piecewise-linear and z-scored: **A V U W M N Z L J** as briefed, plus the five mirrors the brief's list is missing (`U'`, `N'`, `S`, `L'`, `J'`) so the set is **closed under price negation** |
| matching | **both**, as the brief requires: Pearson correlation of the z-scored close path with the z-scored template, **and** banded dynamic time warping (Sakoe-Chiba radius `W/10`, distance divided by `W`, so it is in standard deviations per step) |
| the label | the **argmax of correlation** over the 14 templates; a window counts only if that letter clears both gates |
| gates | `strict` = corr >= 0.90, `loose` = corr >= 0.80, each with its own DTW limit |
| the DTW limit | **calibrated on a walk, not on the data**: the median DTW among the windows of an independently generated 400,000-step Gaussian random walk that already pass the correlation gate. So DTW rejects half of what correlation accepts *on a process with no shapes in it*, and nothing about the markets sets the strictness |
| completion | the window is `[i-W+1, i]` and the occurrence is recorded at `i`. No bar after `i` is read |
| de-overlap | greedy, **across all letters at once**: an occurrence is kept only if the last kept one was at least `W` bars earlier. Overlapping windows inflate permutation nulls and leak into forward windows, and both failures are already on file here |
| the `rank` gate | a third, **per-letter and balanced** gate for the conditional channels only: a window counts for letter `L` if its correlation to `L` is at or above the reference walk's top **2%** for `L`, with that threshold's own walk DTW median. See *Why a third gate* below |
| volatility forecast | `EWMA(abs(r), span 60).shift(1)` - shifted, so it never sees its own bar |
| forward volatility | the **mean `abs(return)`** over the window divided by the pre-event forecast, so the null is exactly 1.0 |
| horizons | 4, 12, 48 bars |
| headline cell | 15m, window 48, gate `rank`, horizon 12 - named before the grid was read |
| the barrier arm | stop at **3.0** forecast units (the live desk's median `Intent.stop_vol`), target at **2x** the stop, 96 bars, the stop taken when both fall in one bar. A driftless walk answers exactly `1/(1+2) = 0.3333` |
| uncertainty | day-block bootstrap, 500 draws, 90% interval, because shapes cluster in days |
| below 100 events | reported with its `n` and read as noise, never dropped - a dropped cell is invisible |

### Why a third gate, and what it costs

A four-leg template is very hard to match. On a 300,000-step walk at `W = 48`, `corr >= 0.90`
to the `W` template fires **0.0 to 0.1 times per 10,000 windows** - about three events in
eleven years of 15-minute bars. So on the absolute gate the question *"does volatility after a
W differ from after an M"* has no sample at all, and reporting a null from it would be
reporting the gate.

The `rank` gate fixes that with a rule that is still calibrated on a walk: each letter's
threshold is the walk's own 98th percentile of correlation to that letter, which gives **483 to
729 events per letter** on 300,000 windows after the DTW median and de-overlap. The price is
stated rather than hidden: a `rank` W is a **weaker** W - the walk's top 2% of correlation to
the W template starts at about **0.66**, where V starts at 0.84 and Z at 0.95. The census and
the transition matrix are **not** read on this gate, because its rate is fixed by construction.

## The controls, which are the study

1. **The i.i.d.-shuffled twin**, 24 draws per instrument, per timeframe, per window. A
   permutation of that instrument's own returns: the exact marginal distribution, every fat
   tail, with the ordering destroyed. This is the matched random walk.
2. **The day-block-shuffled twin**, 24 draws, permuting whole days among days of the **same bar
   count** so the timestamp alignment stays exact. Intraday volatility clustering survives and
   cross-day ordering does not. Without it the census cannot separate "letters are shapes" from
   "letters are clustering", and that separation turns out to be the entire result.
3. **Four Deriv synthetics**, each for one named property of its published generator.
   `findings.md` sets the rule that they are real markets rather than a general null:
   `Volatility 25/75 Index` are generated at constant volatility, `Step Index` is a fixed step,
   and `Jump 75 Index` has fat tails without clustering - the one that separates "the harness
   found memory" from "the harness manufactured a reading out of a heavy tail".
4. **A label-permutation null** for the transition matrix, 200 draws: the same letter sequence
   reordered, so the census is preserved exactly and only the order dies. Mutual information is
   biased upward at finite `n` and this null carries the identical bias.
5. **A volatility-and-hour-matched placebo** for the conditional channels - a non-occurrence
   bar from the same instrument, the same volatility bin (20 of them) and the same hour. The
   matching filled completely: `placebo_n == n` at every headline cell.
6. **Day-block bootstrap** on every mean.
7. **Benjamini-Hochberg** over the full cell count.
8. **The negation check.** Correlation against `-t` is minus correlation against `t`, and a
   walk is symmetric under price negation, so a letter and its mirror must occur at the same
   rate. They do: the walk's pair ratios run 0.998 to 1.238 and the real panel's 0.817 to 1.221
   on every pair with a usable sample. The one outlier is `M/W` at 0.535 on **18 events**, which
   is what a count of eighteen looks like.

## The data

Pulled from the MT5 bridge on 2026-11-05 with `seqlab_pull.py`, 15-minute bars.

| instrument | bars | years | windows at W=48, 15m | quoted round trip at 15m, in forecast-vol units |
|---|---|---|---|---|
| EURUSD | 294,498 | 11.8 | 294,451 | 0.276 |
| GBPUSD | 294,523 | 11.8 | 294,476 | 0.252 |
| USDJPY | 294,521 | 11.8 | 294,474 | 0.247 |
| AUDUSD | 294,532 | 11.8 | 294,485 | 0.238 |
| USDCAD | 294,516 | 11.8 | 294,469 | 0.270 |
| XAUUSD | 276,422 | 11.8 | 276,375 | 0.163 |
| XAGUSD | 278,206 | 11.8 | 278,159 | 1.354 |
| BTCUSD | 259,485 | 7.4 | 259,438 | 0.258 |
| Volatility 75 Index | 275,052 | 7.8 | 275,005 | 0.013 |
| Volatility 25 Index | 275,052 | 7.8 | 275,005 | 0.127 |
| Step Index | 260,916 | 7.4 | 260,869 | 0.043 |
| Jump 75 Index | 198,529 | 5.7 | 198,482 | 0.028 |

**M5 could not be measured.** The lab's cache holds the 15-minute pull only; a 5-minute pull
needs the terminal host, and this run did not touch it. The grid therefore runs **15m, 1h, 4h,
1d**, and the brief's M5 row is open rather than null.

**The cost line does not come from the bars.** The per-bar `spread` column is in points, not
price, and it understates the terminal's quote by **3.3x to 8.3x** on the five FX pairs
(EURUSD 8.3x, BTCUSD 7.8x, GBPUSD 5.1x) while *overstating* it by 6.5x on `Volatility 75
Index`. Every cost statement here is made at the quote; both are computed and printed.

## Result 1: the census - shapes are rarer than an i.i.d. walk makes them, and a day-block shuffle explains most of it

At the headline window, pooled over the 14 letters, per instrument. `ratio` is the real
occurrence rate divided by the arm's.

| instrument | events | windows | rate per 10,000 | i.i.d. walk | **ratio** | day-block twin | **ratio** |
|---|---|---|---|---|---|---|---|
| EURUSD | 1,909 | 294,451 | 64.83 | 69.85 | **0.928** | 67.01 | 0.968 |
| GBPUSD | 1,896 | 294,476 | 64.39 | 69.50 | **0.926** | 65.30 | 0.986 |
| USDJPY | 1,901 | 294,474 | 64.56 | 70.06 | **0.922** | 67.58 | 0.955 |
| AUDUSD | 1,908 | 294,485 | 64.79 | 69.31 | **0.935** | 66.91 | 0.968 |
| USDCAD | 1,832 | 294,469 | 62.21 | 69.45 | **0.896** | 64.96 | 0.958 |
| XAUUSD | 1,834 | 276,375 | 66.36 | 71.04 | **0.934** | 68.19 | 0.973 |
| XAGUSD | 1,641 | 278,159 | 59.00 | 71.00 | **0.831** | 62.86 | 0.939 |
| BTCUSD | 1,439 | 259,438 | 55.47 | 71.59 | **0.775** | 60.81 | 0.912 |
| *Volatility 75 Index* | 1,764 | 275,005 | 64.14 | 65.82 | *0.975* | 63.63 | *1.008* |
| *Volatility 25 Index* | 1,886 | 275,005 | 68.58 | 65.57 | *1.046* | 67.87 | *1.011* |
| *Step Index* | 1,675 | 260,869 | 64.21 | 65.83 | *0.975* | 64.55 | *0.995* |
| *Jump 75 Index* | 1,268 | 198,482 | 63.88 | 65.96 | *0.969* | 64.50 | *0.991* |

**Eight of eight traded markets make fewer letters than an i.i.d. shuffle of their own returns,
and four of four generated markets do not.** The separation tracks how much volatility
clustering each series has - BTCUSD and XAGUSD, the two with the strongest clustering in
[`impulse-vol.md`](impulse-vol.md), are the two furthest from the walk.

Over the whole surface:

| gate | | cells | median i.i.d. ratio | median day-block ratio | mean abs(i.i.d. z) | mean abs(day-block z) |
|---|---|---|---|---|---|---|
| strict | traded | 1,792 | **0.786** | **0.942** | 1.762 | 0.979 |
| strict | generated | 896 | 0.958 | 0.977 | 0.830 | 0.830 |
| loose | traded | 1,792 | 0.923 | 0.989 | 1.767 | 0.976 |
| loose | generated | 896 | 0.991 | 0.998 | 0.904 | 0.868 |

**The day-block shuffle takes the gap from 0.786 to 0.942 and leaves the generated markets
where they already were.** Benjamini-Hochberg over the z (see *Bugs*, item 3) keeps **787 of
5,376** cells against the i.i.d. walk, of which **62 are on generated markets** - 7.9% of the
survivors where generated markets are 33% of the instruments - and only **132** against the
day-block twin, of which 27 are generated.

### Per letter, and the one letter that goes the other way

At the headline cell, averaged over instruments:

| letter | traded: rate/10k | i.i.d. ratio | i.i.d. z | day-block ratio | day-block z | generated: i.i.d. ratio |
|---|---|---|---|---|---|---|
| V | 0.37 | 0.352 | -3.59 | 0.991 | -0.06 | 0.991 |
| A | 0.48 | 0.412 | -3.04 | 1.044 | +0.37 | 0.983 |
| U | 0.19 | 0.648 | -1.01 | 1.036 | -0.01 | 0.944 |
| U' | 0.16 | 0.648 | -0.97 | 0.852 | -0.41 | 1.670 |
| W | 0.00 | 0.000 | -0.71 | 0.000 | -0.36 | 1.677 |
| M | 0.01 | 0.772 | -0.22 | 1.743 | +0.14 | 1.338 |
| N | 1.46 | 0.601 | -3.29 | 1.058 | +0.44 | 0.967 |
| N' | 1.32 | 0.562 | -3.93 | 1.054 | +0.44 | 1.024 |
| Z | 23.80 | 0.860 | -5.71 | 0.968 | -2.17 | 0.955 |
| S | 26.29 | 0.901 | -4.01 | 0.968 | -2.26 | 1.010 |
| **L** | 3.35 | **1.540** | **+4.71** | 0.844 | -2.23 | 1.110 |
| **L'** | 3.87 | **1.745** | **+6.17** | 0.864 | -2.07 | 1.037 |
| J | 0.61 | 0.848 | -0.73 | 0.858 | -1.18 | 0.862 |
| J' | 0.79 | 1.132 | +0.55 | 1.099 | +0.57 | 1.173 |

`W` and `M` have **0 and 3 events** across the whole traded panel at this cell, which is the
sample problem the `rank` gate exists for and not a finding about double bottoms.

**`L` and its mirror are the exception and they are the interesting row.** A sharp drop then a
flat shelf occurs **1.54x** as often as an i.i.d. shuffle of the same returns makes it, and
**0.84x** as often as a day-block shuffle of the same returns makes it. That is the signature
of a burst followed by quiet inside a day: i.i.d. returns never cluster a large move next to
small ones, a day-block shuffle preserves that clustering, and the real series sits between the
two - fewer such shapes than the day-block twin because real bursts are followed by elevated
rather than dead volatility. Every other letter is **below** the i.i.d. walk and at the
day-block twin.

The largest single cells in the whole surface are the same story at the shortest window:
BTCUSD `Z` at 15m, W=12 reads 0.625 of its i.i.d. walk at **z -31.4**, XAGUSD `S` 0.704 at
z -29.9. Against the day-block twin the largest real-market cells are BTCUSD `L` and `L'` at 0.66-0.91,
z -5.0 to -6.0 - the same letter again.

The single largest day-block z in the whole 5,376-cell surface is **`Step Index`, 4h, W=96,
letter V, on 5 events**, at 8.6x its twin. That is what a count of five looks like, it is on a
generated market, and it is printed with its `n` rather than dropped because a dropped cell is
invisible.

## Result 2: transitions - nothing

Mutual information between consecutive completed letters, in bits, against the permutation of
the same label sequence (which preserves the census exactly), gate `strict`:

| timeframe | window | cells | mean events | MI | MI, permuted | excess | share at p<0.05 | MI, i.i.d. walk |
|---|---|---|---|---|---|---|---|---|
| 15m | 12 | 12 | 7,744 | 0.0164 | 0.0156 | +0.0008 | 0.083 | 0.0134 |
| 15m | 24 | 12 | 3,518 | 0.0257 | 0.0263 | -0.0005 | 0.000 | 0.0239 |
| 15m | 48 | 12 | 1,746 | 0.0468 | 0.0457 | +0.0011 | 0.083 | 0.0456 |
| 15m | 96 | 12 | 919 | 0.0725 | 0.0710 | +0.0015 | 0.000 | 0.0811 |
| 1h | 12 | 12 | 2,066 | 0.0551 | 0.0513 | +0.0038 | 0.167 | 0.0505 |
| 1h | 96 | 12 | 237 | 0.1960 | 0.1798 | +0.0162 | 0.250 | 0.2125 |
| 4h | 24 | 12 | 254 | 0.1953 | 0.1776 | +0.0177 | 0.167 | 0.2135 |
| 1d | 96 | 12 | 10 | 0.4099 | 0.4439 | -0.0341 | 0.000 | 0.6610 |

(the full 16-row grid is in `trans.csv`; the eight above span its range.)

**MI rises with the window and falls with the sample, exactly as a finite-sample bias does, and
the permutation null rises with it.** The excess is **-0.034 to +0.018 bits** across the grid,
**31 of 384** cells reach p<0.05 where chance gives 19.2, and **0 survive BH**. The i.i.d.
walk's own MI tracks the real series to within the same margin.

Per instrument at the headline cell, the permutation p runs 0.114 to 0.821 on the eight traded
markets and the smallest value in the panel is **0.045 on `Volatility 75 Index`** - a generated
market, where there is no sequence to find.

## Result 3: letters as a volatility label - real, small, and not what an impulse is

Forward volatility at 12 bars over a volatility-and-hour-matched bar, in units of the
pre-event forecast. Gate `rank`, 15m, W=48, pooled over the eight traded markets:

| letter | n | rv | placebo | **d_rv** | i.i.d. twin | d_rv, non-impulse completions only | share of completions that are impulses |
|---|---|---|---|---|---|---|---|
| V | 2,113 | 1.033 | 1.045 | -0.012 | +0.019 | -0.001 | 0.130 |
| A | 2,179 | 1.089 | 1.044 | +0.045 | +0.006 | +0.039 | 0.155 |
| U | 2,817 | 1.076 | 1.050 | +0.026 | +0.002 | +0.011 | 0.186 |
| U' | 3,290 | 1.122 | 1.087 | +0.036 | -0.003 | +0.030 | 0.201 |
| W | 3,668 | 1.089 | 1.096 | -0.007 | +0.002 | -0.008 | 0.160 |
| M | 3,979 | 1.097 | 1.079 | +0.018 | -0.005 | +0.018 | 0.172 |
| N | 2,374 | 1.052 | 1.045 | +0.007 | -0.002 | +0.020 | 0.126 |
| N' | 2,227 | 1.098 | 1.015 | **+0.083** | +0.001 | +0.076 | 0.141 |
| Z | 3,539 | 0.996 | 0.955 | +0.040 | -0.019 | +0.041 | 0.084 |
| S | 3,894 | 1.012 | 1.015 | -0.003 | -0.010 | +0.012 | 0.085 |
| L | 4,936 | 0.890 | 0.905 | -0.015 | -0.009 | -0.010 | 0.070 |
| L' | 5,202 | 0.897 | 0.933 | **-0.037** | +0.002 | -0.034 | 0.066 |
| J | 3,462 | 1.185 | 1.121 | +0.064 | +0.009 | +0.047 | 0.258 |
| J' | 4,030 | 1.228 | 1.145 | **+0.083** | -0.012 | +0.061 | 0.291 |

The same cells on the four generated markets read **-0.008 to +0.011**, and their own
i.i.d.-shuffled twins -0.012 to +0.011.

Three readings:

* **It is real.** Per instrument the traded `d_rv` spans **-0.087 to +0.262** where the
  i.i.d.-shuffled twin of the same series spans -0.064 to +0.067 and the generated markets
  -0.031 to +0.030. Over the 4,830 cells with at least 100 events, BH keeps **280**, of which
  only **6** are on generated markets. The largest is BTCUSD `N'` at **+0.262 [+0.145, +0.391]**
  against its twin's +0.026.
* **It is small, and it is not what an impulse is.** The best pooled letter reads +0.083 where
  [`impulse-vol.md`](impulse-vol.md) measured **+0.167 to +0.355** on 8 of 8 traded markets,
  through the same estimator, the same placebo and the same bootstrap. It is also not simply the
  impulse the letter contains: restricting to completions whose own bar is **not** an impulse
  keeps 0.047 of J's 0.064 and 0.061 of J''s 0.083.
* **What it mostly says is the level the letter sits at, not the letter.** `L` and `L'` - the
  drop-then-shelf - land at `rv` **0.89-0.90**, the quietest forward volatility in the table,
  and `J` and `J'` - the long decline with a sharp finish - at **1.19-1.23**, the loudest. The
  matched placebo moves with them (0.91-0.93 and 1.12-1.15), and the gap between a letter and
  its own placebo is what the `d_rv` column is.

### The question the brief named: W against M

| instrument | n, W | n, M | d_rv, W | 90% interval | d_rv, M | 90% interval | **W - M** |
|---|---|---|---|---|---|---|---|
| EURUSD | 452 | 486 | +0.024 | [-0.030, +0.089] | -0.015 | [-0.073, +0.043] | **+0.039** |
| GBPUSD | 425 | 470 | +0.069 | [+0.006, +0.130] | +0.012 | [-0.055, +0.079] | **+0.057** |
| USDJPY | 512 | 586 | -0.066 | [-0.130, -0.006] | +0.021 | [-0.037, +0.069] | **-0.087** |
| AUDUSD | 542 | 539 | -0.048 | [-0.101, +0.004] | -0.015 | [-0.074, +0.044] | **-0.033** |
| USDCAD | 479 | 490 | -0.005 | [-0.068, +0.059] | -0.008 | [-0.079, +0.063] | **+0.003** |
| XAUUSD | 456 | 517 | -0.026 | [-0.091, +0.039] | +0.038 | [-0.020, +0.094] | **-0.064** |
| XAGUSD | 389 | 448 | -0.032 | [-0.108, +0.041] | +0.005 | [-0.081, +0.088] | **-0.036** |
| BTCUSD | 413 | 443 | +0.024 | [-0.051, +0.099] | +0.106 | [+0.041, +0.163] | **-0.082** |
| *Volatility 75 Index* | 665 | 663 | +0.003 | | +0.025 | | *-0.021* |
| *Volatility 25 Index* | 644 | 692 | +0.023 | | +0.017 | | *+0.006* |
| *Step Index* | 602 | 672 | -0.009 | | -0.011 | | *+0.002* |
| *Jump 75 Index* | 495 | 466 | -0.014 | | +0.012 | | *-0.026* |

**Three of eight traded instruments have a positive gap, mean absolute gap 0.050, and the
generated markets' gaps (-0.026 to +0.006) sit inside the traded ones' spread.** A double
bottom and a double top say the same thing about the next three hours.

The same question asked as "how much do the letters differ from each other at all" gives the
same answer: within an instrument the standard deviation of `d_rv` across the 14 letters is
**0.012-0.015 on the four generated markets** and **0.030-0.104 on the eight traded ones**,
against the i.i.d. twin's own cross-letter spread of 0.012-0.032. There is a difference between
letters; it is between one and three times the noise floor, and it does not line up with what
the letters are supposed to mean.

## Result 4: the trade arm, which was expected to be null and is

The textbook side for each letter was frozen before the run (`V U W N S L J` long, `A U' M N' Z L' J'` short). **The opposite arm is exactly minus this reading**, so it is not measured
separately.

### The tail, which is what this desk leads with

A 2:1 barrier race - stop at 3.0 forecast units, target at 6.0, 96 bars, the stop taken when
both fall in one bar. A driftless walk answers exactly **0.3333**.

| instrument | races | P(target first) | the same on its i.i.d. twin | cost in R | **net, R per trade** |
|---|---|---|---|---|---|
| EURUSD | 6,110 | 0.3423 | 0.3685 | 0.091 | **-0.064** |
| GBPUSD | 5,929 | 0.3412 | 0.3607 | 0.085 | **-0.062** |
| USDJPY | 6,400 | 0.3551 | 0.3773 | 0.079 | **-0.014** |
| AUDUSD | 6,664 | 0.3448 | 0.3496 | 0.079 | **-0.045** |
| USDCAD | 6,250 | 0.3377 | 0.3602 | 0.090 | **-0.077** |
| XAUUSD | 5,988 | 0.3554 | 0.3769 | 0.055 | **+0.012** |
| XAGUSD | 5,497 | 0.3369 | 0.3799 | 0.451 | **-0.441** |
| BTCUSD | 4,450 | 0.3451 | 0.3629 | 0.081 | **-0.046** |
| *Volatility 75 Index* | 7,261 | 0.3398 | 0.3608 | 0.004 | *+0.015* |
| *Volatility 25 Index* | 7,586 | 0.3637 | 0.3548 | 0.042 | *+0.049* |
| *Step Index* | 7,085 | 0.3611 | 0.3601 | 0.014 | *+0.069* |
| *Jump 75 Index* | 5,364 | 0.3539 | 0.3495 | 0.010 | *+0.052* |

**The i.i.d.-shuffled twin of the same series beats the real series on 13 of 14 letters and on
8 of 8 traded instruments.** Pooled, the traded panel hits 0.3448 and its twin 0.3670. That is
the cleanest statement in the study: the textbook trade does **worse** than the same trade
taken on a shuffled version of the same returns. Net of the quoted round trip, **1 of 8** traded
instruments is positive, by 0.012R, and all four generated markets are - which is the
spread doing the work, since their round trips are 0.004 to 0.042R against the traded panel's
0.055 to 0.451.

### The conditional mean, for completeness

At the headline cell, the forward move signed by the textbook side, pooled over the traded
panel, runs **-0.195 (N') to +0.151 (W)** forecast units against a mean quoted round trip of
**0.382** at that cell. Every letter is negative net of cost, and the i.i.d. twin's readings
(-0.053 to +0.147) cover the same range. The per-instrument table is in `dir.csv`; of 4,830
cells with at least 100 events, 1,425 are positive net of the quote.

**Costed from the stored `spread` column instead, 1,846 are** - 421 cells change sign on the
choice of cost line alone.

## Power, before any of these nulls is believed

Planted on the four generated markets, where the real answer is null, and swept. The zero cell
is reported first because it is what makes the rest readable.

**The census.** Letter-shaped stretches spliced into the series at a multiple of the observed
rate. The plant is reported **as delivered**, not as aimed - splicing a stretch does not
guarantee it passes the gate, so a 2x plant raises the observed rate by 1.73x:

| aimed | delivered rate ratio | detected (p<0.05) |
|---|---|---|
| 0.00 | 1.000 | **0.063** |
| 0.10 | 1.008 | 0.031 |
| 0.25 | 1.042 | 0.063 |
| 0.50 | 1.111 | 0.094 |
| 1.00 | 1.424 | 0.219 |
| 2.00 | 1.727 | 0.500 |

**Where it goes blind: below a rate ratio of about 1.4 per cell.** These cells carry about
**33 events** each - the sweep plants into `V`, `A`, `W` and `M`, the sparse letters, because
they are the ones a template can be spliced in as. The cells the census finding actually rests
on are `Z`, `S`, `L` and `L'`, with 500 to 6,000 events, where a 10% ratio difference is a z of
2 to 3 and the measured z's run to -31.

**The risk channel.** A lift of known size added to the forward window's `abs(return)`:

| planted lift | detected |
|---|---|
| 0.00 | **0.063** |
| 0.02 | 0.344 |
| 0.05 | **1.000** |
| 0.10 | 1.000 |
| 0.20 | 1.000 |

**It is certain at a planted lift of 0.05 and sees a third of cells at 0.02.** The letters read -0.037 to +0.083
pooled and up to +0.262 on a single instrument, so the readings in Result 3 are above the floor
and an effect the size of an impulse's (+0.167 to +0.355) would have been seen on every cell.

**The direction channel, which is the weak arm and must be read as such.**

| planted drift | mean cell statistic | detected |
|---|---|---|
| 0.00 | -0.061 | **0.094** |
| 0.02 | -0.041 | 0.063 |
| 0.05 | -0.011 | 0.063 |
| 0.10 | +0.039 | 0.063 |
| 0.20 | +0.139 | 0.156 |

The plant lands exactly where it is aimed - the statistic moves by the planted amount at every
step - and the **test never sees it**. With about 800 events per cell and a per-cell standard
deviation of 0.18, the day-block bootstrap cannot resolve 0.20 of a forecast unit, and a round
trip at this cell costs 0.25 to 0.38. **So the conditional-mean direction arm is underpowered
relative to its own cost line and its null is weak.** The zero cell at 0.094 against a claimed
0.05 says the same thing from the other side: that p is anti-conservative here.

The direction verdict therefore rests on the **barrier arm**, which pools 4,450 to 7,586 races
per instrument and compares against both `1/(1+N)` and the instrument's own shuffled twin,
rather than on the conditional mean.

## Bugs and measurement defects this run caught

1. **The surrogates were never regridded onto the timeframe.** The shuffle happens at the
   15-minute base and every slow timeframe is a calendar bin of it, so a surrogate read on the
   1-hour grid was a 294,498-bar path compared against a 73,644-bar one. It raised at 1h - and
   it would have been **invisible at 15m**, where the two lengths coincide and every number
   would have looked fine. There is now one length check per instrument per timeframe covering
   every array at once.
2. **A four-leg template has no sample on an absolute gate.** `corr >= 0.90` to the `W`
   template fires about three times in eleven years of 15-minute bars, so the brief's own
   question - W against M - could not be asked at all. That is why there is a third,
   walk-calibrated, per-letter gate, and why its cost (a `rank` W starts at correlation 0.66) is
   stated rather than buried.
3. **A rank p-value cannot carry Benjamini-Hochberg over 5,376 cells.** With 24 surrogate
   draws the floor is 1/25 = 0.040, BH needs 1.9e-5 to reject anything in a family that size,
   and the run therefore returned **0 survivors whatever the data said**. The rate is a count
   over 200,000-300,000 windows, so its sampling distribution is close to normal; BH is run on
   the z against the 24 draws and both numbers are printed.
4. **The direction channel's zero cell reads 0.094 against a claimed 0.05.** The day-block
   bootstrap p is anti-conservative on this statistic at this sample size. Reported rather than
   adjusted, and the direction verdict moved onto the barrier arm because of it.
5. **A planted census does not land where it is aimed.** Splicing a letter's own increments
   into the series does not make the gate accept it: a 2x plant delivers 1.73x. The power table
   is indexed by the **delivered** ratio.
6. **The per-bar `spread` column is not a cost, in both directions.** It understates the
   terminal's quote by 3.3x to 8.3x on FX and gold, and **overstates** it by 6.5x on
   `Volatility 75 Index`. Reading it instead of the quote turns 1,425 profitable direction cells
   into 1,846 - 421 cells change sign on the cost line alone, which is the same defect
   [`impulse-vol.md`](impulse-vol.md) reported and the same direction of error.
7. **A NaN cast silently filled a volatility bin.** `(state * 20).astype(int)` on a NaN state
   produced a garbage bin index that was then masked out, which worked, but raised a warning on
   every call and would have placed events in bin 0 had the mask ever been dropped.

## What this does not close

* **M5 was not measured.** The brief asked for M5 upwards and the cache holds 15 minutes
  upwards. The shortest clock is also the one where cost bites hardest - the same spread is 19x
  dearer at 15m than at 1d - so an M5 arm would be the most expensive and the least likely to
  pay, but it is untested.
* **The conditional-mean direction arm is underpowered**, as the power table says. It is a
  weak null, not a strong one; the barrier arm is the one carrying the verdict.
* **The transition study tests one statistic.** Mutual information between consecutive letters
  is a test of the whole matrix; a single strong transition in a 14x14 table against a weak rest
  could hide inside it. The per-transition table is in the harness output and was not mined,
  deliberately, because 196 transitions x 384 cells is a surface that would produce winners.
* **The `rank` gate's letters are weaker letters.** Everything in Result 3 and Result 4 is
  read on the walk's top 2% of correlation to each template. A reader who means "a textbook W,
  the kind a person would circle" should read the `strict` rows, and accept that `W` has three
  events there.
* **Nothing here was traded.** There is no fill model, no slippage and no queue; the barrier
  arm charges the quoted spread once per round trip at the stop distance and nothing else.
