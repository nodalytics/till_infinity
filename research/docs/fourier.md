# Causal Fourier forecasting: the cycles forecast nothing, the line underneath them is the FX and bitcoin reversal, and seasonality belongs to an hour-of-week table

Measured 2026-10-08 on the lab with [`statespace_fourier.py`](../harness/statespace_fourier.py)
and [`statespace_fourier_report.py`](../harness/statespace_fourier_report.py). The method is from
an article the desk passed on ("Fourier methods reveal cycles", abouttrading.substack.com). The
article reports no result of its own.

## Verdict

| question | answer |
|---|---|
| Does the causal Fourier forecast call direction? | **Only through its straight line, not its cycles.** 7 of 66 cells pass the frozen rule: EURUSD, USDJPY, USDCAD, XAUUSD and BTCUSD at 15m, BTCUSD at 1h, XAUUSD at 1d (AUC 0.511-0.533 against walks 0.498-0.506). In six of the seven the *cycle* part alone scores 0.488-0.501, at or below a coin, and the *trend* part (distance from the 128-bar regression line) carries it (0.513-0.530). |
| Why don't the cycles help? | **A DFT extrapolated one step wraps around.** The reconstruction is periodic in the window length, so its value one bar ahead is its value at the window's first bar, 128 bars ago (checked: -0.527978 at both). On the article's own synthetic series (trend + 50- and 12-bar cycles + noise) the forecaster's error is **twice** that of "tomorrow equals today" (MAE 1.445 against 0.720). |
| Deriv indices (V10, V10 (1s), V25, V25 (1s), V75, V15, V15 (1s), Jump 25)? | **Nothing.** 30 cells, AUC 0.434-0.524, no pass. The extremes are small daily or 4h samples, on both sides of 0.5. |
| Does it pay? | **No.** The best passing cell, BTCUSD 15m, grosses +1.65 bps on the confident decile (t 3.4), and the 2.39-bps spread makes it **-0.74**. On FX 15m the gross is +0.07 to +0.54 bps: USDJPY clears its 0.19-bps quoted spread by +0.35, and nothing clears a 1-pip retail spread. |
| Tail? | **No consistent excess over the walks.** The two largest are BTCUSD 15m (P(>= 4R) 0.233 against walks at 0.18; P(>= 10R) 0.109 against 0.075, on 386 trades) and USDJPY 15m (P(>= 4R) 0.272 against 0.19-0.21; P(>= 10R) 0.105 against 0.09-0.10, on 313). Each is about 2 standard errors and the best of ~60 tail cells, so each needs its own frozen test. |
| Volatility, as the article suggests? | **Fourier adds nothing; a plain hour-of-week table adds a lot.** On FX, gold and bitcoin at 15m and 1h, the Fourier volatility forecast moves next-bar shock AUC by -0.001 to +0.003 over EWMA. The training hour-of-week profile adds **+0.014 to +0.103** (EURUSD 1h 0.677 -> 0.747, USDCAD 1h 0.674 -> 0.777), and Fourier adds nothing on top of it. |
| Band power as features? | **Nothing** for direction (0.49-0.51 at 15m-4h) or risk (-0.005 to +0.009 over EWMA). |

## 1. The method and the property that decides it

At each bar, on the trailing window of N = 128 log closes only:
1. fit a straight line and subtract it;
2. take the FFT of the residual and keep the K = 5 strongest non-zero frequencies;
3. rebuild those cosines one step past the window and add the line extrapolated there.

The signal is the forecast minus the current close. Everything uses past bars only, so there is
no look-ahead; the article's checklist on that point is sound.

**The catch is in step 3.** A discrete Fourier reconstruction repeats every N bars. "One step past
the window" is index N, and index N is index 0 again: the forecast is the smoothed residual of the
oldest bar in the window, not a projection of the cycles forward. A cycle continues correctly only
if its period divides 128 exactly. This was checked numerically before any market data was read:
the reconstruction gives -0.527978 at index 128 and at index 0.

The article's own example confirms it. On its synthetic series (n = 500, seed 7, trend 0.03 a
bar, cycles of 50 and 12 bars, noise 0.6), the one-step forecast misses by 1.445 on average, and
"the next value equals this one" by 0.720. The forecast does carry some direction there
(correlation 0.215 with the next change), because the series really is built from cycles and the
line carries the trend.

What is left is the **line**. `a N + b - x_t` is the 128-bar regression's slope (momentum) plus
the distance of the close from the line (reversion). Both parts were scored separately, so
whichever carries the skill is visible.

## 2. What was frozen

- **Instruments:** EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, USDCHF, NZDUSD, XAUUSD, BTCUSD, and
  Deriv's Volatility 75, 10, 10 (1s), 25, 25 (1s), 15, 15 (1s) and Jump 25.
  - The request named "hump 15", which is not a Deriv index (Jump comes in 10, 25, 50, 75 and 100),
    so Volatility 15 and 15 (1s) were run as the nearest reading.
  - Volatility 15 started in 2026-02, so its 1d is skipped (211 bars), as is V15 (1s) 1d (589).
- **Timeframes:** 15m, 1h, 4h and 1d from the broker's bars. FX and gold from 2005, bitcoin from
  2017.
- **Fit and score:** fit on the first 60% by time, score on the last 40%. FX and gold rows that
  touch the 20:00-23:00 UTC rollover, and rows after a gap, are not scored.
- **Walks:** two flip walks (real bars, random sign) and a GARCH-t walk for every cell.
- **Direction passes:** Benjamini-Hochberg q = 0.05 over the 66 primary cells (N = 128, K = 5),
  AUC above 0.5, and at least 0.005 above its walks.
- **Sensitivity, reported and not counted:** N = 64 and 256; K = 3 and 10.
- **Volatility:** next bar a top-10% |r| (threshold from training). EWMA alone; + the Fourier
  forecast of log r^2; + the hour-of-week profile; + both; + band power. Here the GARCH walk is the
  control, because a flip walk keeps the real volatility path.
- **Costs:** one quoted spread a trade. For bitcoin that is the 2.39 bps measured in
  [`lagging.md`](lagging.md): the bar file's spread field reads 0.3 bps, and the larger, measured
  figure was used.

## 3. Direction

Test AUC of the full forecast (mean of the three walks), and the two parts on their own, for
every passing cell:

| instrument | tf | test bars | full [95% CI] (walks) | cycle part | trend part |
|---|---|---:|---|---|---|
| EURUSD | 15m | 17,288 | 0.511 [0.504-0.518] (0.501) | 0.494 | 0.513 |
| USDJPY | 15m | 17,288 | 0.513 [0.505-0.522] (0.505) | 0.507 | 0.503 |
| USDCAD | 15m | 17,290 | 0.518 [0.509-0.527] (0.506) | 0.499 | 0.514 |
| XAUUSD | 15m | 18,122 | 0.515 [0.508-0.524] (0.504) | 0.495 | 0.514 |
| XAUUSD | 1d | 1,612 | 0.533 [0.508-0.561] (0.501) | 0.501 | 0.515 |
| BTCUSD | 15m | 19,996 | 0.530 [0.523-0.538] (0.498) | 0.488 | 0.530 |
| BTCUSD | 1h | 19,996 | 0.516 [0.510-0.523] (0.502) | 0.490 | 0.517 |

- **The cycle part never carries a pass.** Across all 66 cells it ranges 0.480-0.516; its walks
  sit at the same place. USDJPY 15m is the one cell where it is above the trend part, and it is
  0.507.
- **The trend part is the short-term reversal** measured in [`fx-reversal.md`](fx-reversal.md):
  a close far above its recent line tends to come back. It is the same effect on FX, now seen on
  gold at 15m and on bitcoin at 15m and 1h, the strongest cell here (0.530).
- **XAUUSD 1d** (0.533) is carried partly by band power (0.543) on 1,612 test days. It is one
  daily cell out of 66 and needs its own confirmation before anyone reads it as a gold cycle.
- **Deriv:** 30 cells, 0.434-0.524, none passing. The Volatility indices are random walks by
  construction ([`deriv-variants.md`](deriv-variants.md)), and the Fourier forecaster duly finds
  nothing in them.
- **Seven cells sit 0.01 or more below their walks**, all at 1d or on short series (V15 4h at
  0.434 on 506 bars). That is the other side of the same noise that gives the daily passes their
  width.
- **The window and the frequency count change little.** On the passing cells N = 64 / 256 and K =
  3 / 10 stay within 0.01 of the main setting, which is what a line-driven signal predicts.

## 4. Trades and the tail

Confident decile (threshold from training), held one bar, net of one spread:

| instrument | tf | cost bps | n | gross bps (t) | net bps | P(>=4R) / P(>=10R) (walks) |
|---|---|---|---:|---|---|---|
| EURUSD | 15m | 0.17 | 1,584 | +0.07 (+0.8) | -0.10 | 0.222 / 0.076 (0.22-0.23 / 0.09-0.10) |
| USDJPY | 15m | 0.19 | 1,217 | +0.54 (+2.9) | +0.35 | 0.272 / 0.105 (0.19-0.21 / 0.09-0.10) |
| USDCAD | 15m | 0.22 | 1,338 | +0.08 (+1.1) | -0.13 | 0.207 / 0.093 (0.21-0.24 / 0.08-0.12) |
| XAUUSD | 15m | 0.32 | 1,603 | -0.22 (-0.4) | -0.54 | 0.188 / 0.084 (0.19-0.22 / 0.09-0.11) |
| XAUUSD | 1h | 0.32 | 1,609 | +1.40 (+2.1) | +1.08 | 0.187 / 0.085 (0.18-0.20 / 0.09) |
| BTCUSD | 15m | 2.39 | 1,710 | +1.65 (+3.4) | -0.74 | 0.233 / 0.109 (0.18-0.19 / 0.07-0.08) |
| BTCUSD | 1h | 2.39 | 1,978 | +0.94 (+1.0) | -1.45 | 0.168 / 0.071 (0.17-0.21 / 0.08-0.10) |

- **The direction skill does not survive the spread** on bitcoin. On FX it clears the quoted
  spread only on USDJPY 15m, and it clears no retail spread.
- **XAUUSD 1h** nets +1.08 bps, but it is not a passing direction cell (0.509 against walks
  0.501), so it is a selection from 66, not a result.
- **The tail matches the walks except in two cells.** BTCUSD 15m (P(>= 10R) 0.109 against
  0.074-0.075) and USDJPY 15m (P(>= 4R) 0.272 against 0.19-0.21) are each about two standard
  errors out, picked from about 60 tail cells. They are leads for a frozen test, bitcoin on fresh
  coins, not findings.

## 5. Volatility and seasonality: what the article suggested instead

Next bar a top-10% move, test AUC:

| instrument | tf | EWMA | + Fourier | + hour-of-week | + both |
|---|---|---|---|---|---|
| EURUSD | 15m | 0.766 | 0.766 | **0.802** | 0.802 |
| EURUSD | 1h | 0.677 | 0.680 | **0.747** | 0.747 |
| GBPUSD | 1h | 0.653 | 0.657 | **0.738** | 0.738 |
| USDCAD | 1h | 0.674 | 0.676 | **0.777** | 0.776 |
| USDCHF | 1h | 0.659 | 0.660 | **0.730** | 0.730 |
| XAUUSD | 15m | 0.677 | 0.676 | **0.712** | 0.712 |
| BTCUSD | 1h | 0.717 | 0.716 | **0.757** | 0.756 |

Across all FX, gold and bitcoin cells at 15m and 1h:
- the Fourier volatility forecast adds -0.001 to +0.003;
- band power adds -0.005 to +0.009;
- the hour-of-week table adds **+0.014 to +0.103**.

The article's intuition is right: intraday volatility has a rhythm. But a 128-bar Fourier window
cannot hold a 96-bar (15m) or 24-bar (1h) daily cycle *and* the week, and the table already holds
both exactly. It is the desk's volatility clock ([`calendar-returns.md`](calendar-returns.md)),
which this re-measures at +0.02 to +0.10 AUC.

**On the Deriv indices EWMA itself scores 0.467-0.528**, against 0.65-0.78 on their GARCH walks.
There is no volatility to forecast in a generator with a fixed sigma. The frozen volatility rule
flags 8 cells, but they are this noise: six Deriv cells, plus USDCAD and USDCHF at 1d, each on a
few hundred test bars. The rule set no multiplicity correction for volatility, which was an
oversight in it. With 66 cells and a 0.005 threshold, 8 such cells is about what noise gives.

## 6. What the tests caught

- **A cost bug, caught before the write-up.** The first run inferred each instrument's price point
  with `np.allclose`. Its default *relative* tolerance let prices in the thousands (49,275.93 x 10)
  pass as integers, so every non-FX cost came out 10-100x too large (V75 at 31 bps against its
  measured 3.1). AUCs were untouched. The point is now inferred with `rtol = 0`, and the run was
  repeated: the re-run's AUCs match the first to the last digit, and only the nets moved.
- **Bitcoin's spread field disagrees with its measured spread** (0.3 bps against 2.39). The larger
  figure was used.
- **V15 is young** (from 2026-02). Its 1h and 4h cells rest on 2,026 and 506 test bars, which is
  where the most extreme AUCs on both sides come from.
