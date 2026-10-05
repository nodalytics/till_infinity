# PCA residuals: how many independent bets, and does the stretched residual revert?

Measured 2026-10-04 on the lab with [`pca_residuals.py`](../ideas/pca_residuals.py), frozen in
[`pca_rule.json`](../ideas/pca_rule.json) (commit `0ef39f7`) before any real-data run. The discovery
pick was made by a frozen procedure and committed in [`pca_selected.json`](../ideas/pca_selected.json)
(commit `0edba03`) before any confirmation run. Tests of the PCA, OU and s-score pieces on synthetic data
with known answers: [`test_pca_residuals.py`](../ideas/test_pca_residuals.py).

## The thesis

A quant article on trading randomness argues that a market is a few shared forces plus noise. Take the
market, sector and style factors out with PCA, and what is left, the residual, mean-reverts when it is
stretched: the Avellaneda-Lee statistical arbitrage. It also warns that such a book can be short crash
risk, and that a signal can be beta in a costume.

## Answer

- **How many bets.** Crypto is one bet plus noise.
  - In a 90-day window of 118 coins, PC1 carries a median **65%** of the variance (90th percentile 75%).
  - The effective number of bets is **6.7** (1d) to **9.2** (4h) by exp(entropy), and **2.3 to 2.5** by
    the participation ratio.
  - Only one eigenvalue clears the Marchenko-Pastur edge. Once the market's variance is taken out of
    the bulk, four or five do.
  - FX: 12 pairs make **4.5** bets (participation ratio 3.4). Metals, indices and energy together: 13
    instruments make **5.2** (3.4).
  - **Deriv's 15 synthetics make 13.8 to 14.8 of 15.** Their top eigenvalue sits at 0.89 to 0.96 of
    the random-matrix edge: a random matrix, as [generated.md](generated.md) said.
- **Correlations spike in crashes.** After 6 of the 10 worst equal-weight crypto days, the 30-day PC1
  share reached its top decile within a week. On 2020-03-12 it reached 0.96, and on 2025-10-10 0.88.
- **The article's trade fails.** The primary, the fresh-coin residual book at 1d and 4h pooled, makes:
  - **net Sharpe −0.97 [−1.59, −0.30]** and gross +0.27;
  - +5.3% a year gross, against 20.2% fees and 4.3% funding, so −19.2% net;
  - −1.21 before 2024 and −0.55 after;
  - against PC1, **alpha −20.7% a year [−34.2%, −6.4%]**, with beta +0.006. The hedge works; there
    is no alpha to keep.
- **Discovery had already said no.** On the 12 coins before 2024, all 36 cells lost *gross*, with
  Sharpe −0.9 to −1.8. The pick (k=1, entry 2.0, exit 0.5, half-life ≤ 10 bars) was the least bad, at
  −2.14 net. Confirmation: 41 secondary cells, every one negative, **none survives BH**.
- **A faint residual reversion exists at 4h, and fees eat it.** On the fresh coins at 4h the book is
  +0.58 Sharpe gross, against −0.48 on the iid null and −0.29 on the shuffle. But it turns over 1.36×
  a day, which costs 35% a year against 15% gross.
- **The controls behave.** The OU positive control earns **+10.5 net Sharpe** on the fresh panel and
  +1.5 to +1.6 on the 12 coins. The iid and shuffle nulls lose about the costs (net −1.9 to −2.0,
  gross −0.5 to −0.6). So the pipeline finds reversion where it exists. Real crypto residuals have
  none worth the fee.
- **Tail.** The book is mildly short crash risk.
  - On the 22 worst index days it loses −0.64% a day, against −0.06% on all days.
  - Skew is −0.95. The worst day is −9.8% (2021-01-15) and the worst week −12.3%.
  - In the weeks of the steepest rise in PC1's share it loses −0.57% a week, against −0.37%.
  - The bleed, not the crashes, dominates its −144% (summed) drawdown.
- **Single-name R version: below the walk.**
  - Fresh coins: **−0.17R [−0.26, −0.08]** at 1d and **−0.19R [−0.24, −0.15]** at 4h.
  - iid null: +0.05R. OU control: +0.25 to +0.42R.
  - P(≥4R) is 0.20, against 0.22 on the null and 0.20 for 1/(N+1). P(≥10R) is 0.07 to 0.08, against
    0.10 to 0.11 on the null and 0.091.
- **DISPLACE_C is market timing, not a residual edge.**
  - On the 131 fresh coins (18,082 trades) it makes +0.041R [−0.003, +0.084], reproducing turn_confirm
    exactly (FRESH 58 +0.049R, SET_C +0.032R).
  - The market part is **+0.056R**. The residual is **−0.016R [−0.025, −0.006]**.
  - Longs: residual −0.004R [−0.021, +0.014]. Shorts: residual −0.025R [−0.035, −0.016].
  - Traded on the equal-weight basket instead of the alt, the same signals make **+34 bps gross,
    +20 bps net a trade** [−11, +54], against +29 bps net for the alt as traded.
  - So most of the edge is the common market turn. It is beta in a costume, though beta that is
    *timed*, not held.

## The design (frozen)

**A. How many independent bets.**
- Rolling PCA of the correlation matrix on trailing 90-day windows, one a day. Universes:
  - crypto: the 12 Binance perpetuals plus the 131 fresh coins (1d and 4h, median 118 coins in a window);
  - FX: 12 pairs (1d from 2016, when the last pair starts; 4h);
  - macro: metals 5 + indices 7 + energy 2 from the broker DB (from 2024; on the rows where all 14 have a bar);
  - Deriv: 15 synthetics, as the check.
- Effective number of bets: exp(entropy of the eigenvalue shares), and the participation ratio
  (sum λ)² / sum λ². Both equal N for N independent series and 1 for one factor.
- Eigenvalues above the Marchenko-Pastur edge (1 + √(N/T))², and above it once the market's variance is
  taken out of the noise bulk (Laloux et al.).
- PC1's share in 30-day windows around the 10 worst equal-weight crypto days.

**B. Residual mean reversion (Avellaneda-Lee), every bar, trailing windows only.**
- PCA over the last 252 bars. Eigenportfolios Q_j = v_j / σ_i.
- Over the last 60 bars, regress each coin on the k eigenportfolio returns with an intercept. Cumulate
  the residual and fit an AR(1), X[t+1] = a + b X[t] + ζ (valid for 0 < b < 1). Half-life ln2 / −ln b.
- s = (X_last − m̃) / σ_eq, with m = a / (1 − b) centred across the coins and σ_eq = √(var ζ / (1 − b²)).
- **Rule.** From flat, go long when s < −entry or short when s > entry, only if the half-life ≤ hl_max.
  A long closes at s > −exit, a short at s < exit. A position also closes when its fit turns invalid
  or the coin leaves the universe.
- **Book.** Each position is the coin hedged with −β_j of each eigenportfolio (factor-neutral). The
  net coin weights are normalised to unit gross, decided at bar t's close and held over bar t+1.
- **Costs.** 0.07% of notional on every weight change, hedge legs included, plus the actual funding
  settled while held: the 12 coins' own files and the fresh coins' `fundingRate` monthly files from
  data.binance.vision.
- **Grid** (36 cells): k ∈ {1, 3, 5}, entry ∈ {1.25, 1.5, 2.0}, exit ∈ {0.5, 0.75}, hl_max ∈ {10, 20}
  bars. Windows are in bars at every timeframe (Avellaneda-Lee's 252/60 days on the bar clock).
- **Discovery.** All 36 cells on the 12 coins only (PCA on the 12), real data before 2024-01-01, 1d and
  4h pooled. The pick is the cell with the best net Sharpe.
- **Confirmation, never seen in discovery:**
  - the 12 coins from 2024;
  - the 131 fresh coins over their whole history (PCA on all 143, positions only in the fresh coins),
    at 1d, 4h, 1h and 15m. 1h and 15m klines for the fresh coins were fetched for this.
- **Primary.** The fresh-coin book at 1d and 4h pooled (0.5 × each daily net return). It passes if all
  of these hold:
  - net Sharpe > 0 with its 90% circular block-bootstrap interval (20-day blocks) above 0;
  - positive before and after 2024;
  - above the same book on the iid-residual null;
  - alpha > 0, interval above 0, in a regression of the daily book on the daily PC1 eigenportfolio return.
- **Single-name R version.** Each book entry is also traded as a trade on the coin alone. Entry at the
  next open. Stop at the trigger bar's extreme ± 0.1 ATR, risk at least 0.25 ATR, 0.05 ATR slippage on
  stop fills. Out at the open after the book closes the position. 0.07% a side.
  - P(N R) is the share that reach +N R before −1R within 100 bars, whatever the exit; a bar touching
    both counts as the stop.

**Synthetic panels** (each on the real panel's clock and gaps):
- The real log returns, standardised by their trailing EWMA volatility (half-life 30 bars).
- Five eigenvectors of the full-sample correlation, with each bar's factor scores from a cross-sectional
  least squares. That keeps the real covariance, the real crashes and the volatility clustering.
- A new residual, re-scaled by the real volatility. Highs and lows come from a 16-step Brownian bridge.
  Real funding is paid on the synthetic panels too. The three residuals:
  - **positive control:** an OU residual in level with a 10-bar half-life;
  - **iid null:** Gaussian iid residual increments (a random-walk residual);
  - **shuffle null:** each coin's real residuals permuted in time within its own life. This keeps the
    factor cross-section bar by bar and the fat tails, and kills any reversion.

**C. Is DISPLACE_C beta?**
- The trades are DISPLACE_C at a 12-bar low with the E2 structure exit, exactly as in `turn_confirm.py`,
  checked trade by trade against `turn_trade.trades_exits`. They run on the fresh coins (FRESH 58 and
  SET_C 73) at 4h and 1d, with that study's own cost (0.07% of price once a trade).
- Each trade's R splits into a market part, side × β × the index's return from the signal bar's close
  to the exit bar's close, in R, and a residual.
- β comes from the trailing 60 bars of the coin on the equal-weight index of the 143 coins. BTC is
  reported as a second market.

## A. How many independent bets

Medians over the rolling 90-day windows (one a day). N is the number of series in a window. "Above MP"
counts eigenvalues above the Marchenko-Pastur edge; "market out" uses the bulk's variance once PC1 is
removed, counted over the top five.

| universe | N | PC1 | PC1 p90 | top 5 | exp(entropy) | partic. ratio | entropy / N | above MP | market out | λ1 / edge |
|---|---|---|---|---|---|---|---|---|---|---|
| crypto 1d | 118 | 0.654 | 0.754 | 0.746 | **6.7** | 2.3 | 0.064 | 1 | 5 | 16.3 |
| crypto 4h | 118 | 0.633 | 0.722 | 0.696 | **9.2** | 2.5 | 0.088 | 1 | 5 | 33.4 |
| crypto 1d, 30-day | 120 | 0.679 | 0.802 | 0.795 | 5.0 | 2.1 | 0.044 | 1 | 4 | 8.8 |
| FX 1d | 12 | 0.456 | 0.522 | 0.942 | **4.5** | 3.4 | 0.373 | 2 | 3 | 2.9 |
| FX 4h | 12 | 0.464 | 0.515 | 0.938 | 4.5 | 3.4 | 0.379 | 3 | 4 | 4.0 |
| macro 1d (metals, indices, energy) | 13 | 0.488 | 0.585 | 0.888 | **5.2** | 3.4 | 0.399 | 2 | 3 | 3.3 |
| macro 4h (106 windows only) | 14 | 0.553 | 0.653 | 0.862 | 5.2 | 3.0 | 0.369 | 2 | 4 | 5.5 |
| **Deriv 1d** | 15 | 0.117 | 0.127 | 0.491 | **13.8** | 12.9 | 0.923 | **0** | 1 | **0.89** |
| **Deriv 4h** | 15 | 0.087 | 0.090 | 0.397 | **14.8** | 14.6 | 0.987 | **0** | 1 | **0.96** |

- **Crypto is one bet.** A book of 118 coins holds about 2.3 to 9 independent bets, depending on the
  measure. The participation ratio, which weights the big eigenvalues, says about two. By year the
  1d exp(entropy) runs from 4.7 (2025) to 11.7 (2026, the least correlated stretch).
  - The 30-day windows have *fewer* bets than the 90-day ones. The common factor dominates more over
    short horizons.
- **FX and macro hold 4.5 to 5 bets** out of 12 to 14. FX's PC1 is the dollar (46%) and PC2 the yen
  crosses (24%).
- **Deriv is a random matrix.** Its spectrum sits inside the Marchenko-Pastur bulk (`spectra_mp.png`),
  and its exp(entropy) is 92 to 99% of N. "Market out" counts 1 there only because removing PC1's
  share shrinks the edge below the largest noise eigenvalue. That is an artefact of the adjustment on
  a matrix with no factor.

**PC1 in crashes.** PC1's share in 30-day windows, the day before each of the 10 worst equal-weight
crypto days and its maximum over the next 7 days (percentile of that maximum over the whole history):

| day | index | 30-day 1d PC1 before | after | percentile | 30-day 4h before | after |
|---|---|---|---|---|---|---|
| 2020-03-12 | −43.9% | 0.82 | 0.96 | 1.00 | 0.79 | 0.90 |
| 2020-09-03 | −20.9% | 0.52 | 0.71 | 0.60 | 0.41 | 0.61 |
| 2021-05-19 | −36.4% | 0.63 | 0.82 | 0.94 | 0.70 | 0.73 |
| 2021-06-21 | −23.0% | 0.77 | 0.82 | 0.94 | 0.77 | 0.78 |
| 2021-09-07 | −18.9% | 0.54 | 0.66 | 0.43 | 0.52 | 0.61 |
| 2022-05-11 | −25.2% | 0.83 | 0.86 | 0.98 | 0.75 | 0.77 |
| 2022-11-09 | −19.7% | 0.73 | 0.83 | 0.95 | 0.58 | 0.71 |
| 2024-04-12 | −16.0% | 0.70 | 0.79 | 0.86 | 0.65 | 0.76 |
| 2024-12-09 | −18.7% | 0.53 | 0.68 | 0.50 | 0.57 | 0.64 |
| 2025-10-10 | −25.7% | 0.77 | 0.88 | 0.99 | 0.69 | 0.82 |

PC1's share rose after every one of the 10. It reached its top decile in 6 and its top 15% in 7. In a
crash the few bets become one.

## B. Residual mean reversion

**Discovery** (12 coins, before 2024, 1d+4h pooled): all 36 cells lose gross (Sharpe −0.92 to −1.78)
and net (−2.14 to −3.53). The top of the table:

| k | entry | exit | hl_max | net Sharpe | gross Sharpe | 1d net | 4h net | turnover / day |
|---|---|---|---|---|---|---|---|---|
| **1** | **2.0** | **0.5** | **10** | **−2.14** | −1.43 | −0.90 | −2.05 | 0.60 |
| 1 | 2.0 | 0.5 | 20 | −2.15 | −1.45 | −0.80 | −2.16 | 0.61 |
| 1 | 2.0 | 0.75 | 10 | −2.18 | −1.41 | −0.96 | −2.08 | 0.67 |
| 3 | 2.0 | 0.5 | 20 | −2.58 | −1.25 | −0.85 | −2.76 | 0.69 |
| 5 | 2.0 | 0.5 | 20 | −2.89 | −1.38 | −1.06 | −2.94 | 0.65 |

The more factors are hedged, the worse the net (more turnover in the hedge legs). Wider entries are
better because they trade less. That is the shape of a signal with nothing to give back.

**Confirmation, the selected cell, 1d+4h pooled** (annualised Sharpe on daily returns, 90% block
bootstrap; returns are a year's sum on unit gross):

| book | sample | gross Sharpe | net Sharpe [90%] | gross / yr | fees / yr | funding / yr | net / yr | turnover / day | positions |
|---|---|---|---|---|---|---|---|---|---|
| **fresh coins, real** | all | +0.27 | **−0.97 [−1.59, −0.30]** | +5.3% | 20.2% | 4.3% | −19.2% | 0.79 | 11.7 |
| fresh coins, real | before 2024 | −0.18 | −1.21 | −3.9% | 19.4% | 3.3% | −26.6% | | |
| fresh coins, real | 2024+ | +1.11 | −0.55 [−1.49, +0.41] | +18.0% | 21.3% | 5.7% | −9.0% | | |
| fresh coins, OU control | all | +11.94 | **+10.47** | +220% | 28.1% | 0.2% | +192% | 1.10 | 7.9 |
| fresh coins, iid null | all | −0.49 | **−1.94** | −7.6% | 22.1% | 0.2% | −29.9% | 0.87 | 12.5 |
| fresh coins, shuffle null | all | −0.64 | **−1.96** | −10.9% | 22.8% | −0.2% | −33.5% | 0.89 | 12.1 |
| 12 coins, real | 2024+ | −0.16 | −1.21 [−2.07, −0.37] | −2.2% | 15.0% | −0.6% | −16.6% | 0.59 | 1.6 |
| 12 coins, OU control | 2024+ | +2.91 | +1.63 | +34.0% | 15.7% | −0.6% | +18.8% | | |
| 12 coins, iid null | 2024+ | −0.23 | −1.39 | −3.2% | 16.1% | −0.2% | −19.1% | | |
| 12 coins, shuffle null | 2024+ | −0.09 | −1.27 | −1.3% | 15.8% | −0.3% | −16.8% | | |

By timeframe (fresh coins all dates; 12 coins 2024+):

| book | gross Sharpe | net Sharpe | iid null gross / net | shuffle gross / net | OU gross / net | fees / yr |
|---|---|---|---|---|---|---|
| fresh 1d | −0.19 | −0.56 | −0.21 / −0.53 | −0.61 / −0.85 | +4.37 / +4.08 | 6.1% |
| fresh 4h | **+0.58** | −0.90 | −0.48 / −2.18 | −0.29 / −2.05 | +12.6 / +10.9 | 34.8% |
| fresh 1h | **+1.80** | −3.69 | +0.51 / −5.98 | −0.84 / −7.41 | +21.8 / +15.7 | 141% |
| fresh 15m | **+6.48** | −16.2 | −0.25 / −26.0 | −0.32 / −24.1 | +32.8 / +14.9 | 581% |
| 12 coins 1d | −0.34 | −0.55 | +0.13 / −0.08 | −0.79 / −1.05 | +0.86 / +0.62 | 4.3% |
| 12 coins 4h | +0.13 | −1.21 | −0.47 / −1.87 | +0.68 / −0.74 | +3.10 / +1.61 | 25.7% |
| 12 coins 1h | −0.26 | −6.61 | −0.91 / −7.15 | −0.92 / −7.26 | +5.44 / −1.00 | 107% |
| 12 coins 15m | +0.06 | −23.4 | −1.03 / −23.2 | −0.49 / −19.8 | +9.85 / −14.3 | 444% |

- **The primary fails every leg** except "above the iid null" (−0.97 against −1.94):
  - the interval is below zero;
  - both halves are negative;
  - alpha on PC1 is −20.7% a year [−34.2%, −6.4%], with beta +0.006.
- **Real gross beats both nulls at 4h, more at 1h and most at 15m.**
  - 1h: +1.80 against +0.51 and −0.84; single-name −0.28R over 61,323 trades, P(≥4R) 0.209, P(≥10R) 0.091.
  - 15m: +6.48 against −0.25 and −0.32; single-name −0.55R [−0.57, −0.53] over 253,046 trades,
    P(≥4R) 0.219 and P(≥10R) 0.094, against 0.229 and 0.109 on the iid null.
  - 4h: +0.58 against −0.48 and −0.29, strongest after 2024 (pooled gross +1.11).
  - That is a small residual reversion, larger the shorter the bar. But the book has to turn over
    1.4× a day at 4h to harvest it, and the fee is twice the gross; at 15m it turns over 23× a day,
    and the fees (581% a year) are more than three times the gross (172%).
  - On the 12 coins at 1h and 15m even the OU control cannot pay the fee: a 10-bar half-life at 15m
    is a 2.5-hour trade. On the fresh coins it still can (+15.7 and +14.9 net), because its reversion
    is far stronger than anything in the real residual.
- **Funding costs the real book 4.3% a year,** against about zero on the synthetic panels, whose
  positions are unrelated to the real funding. The real fades sit on the side that pays.
- **BH:** 41 secondary cells tried, the other 35 grid cells on the primary sample and the selected
  cell's 1h/15m/12-coin books. Every Sharpe is negative (−0.55 to −23.4), and **none survives** at
  q = 0.10.

**Tails of the primary book** (`drawdown.png`):
- **Drawdown and skew:** max drawdown −144% of unit gross summed over 6.5 years, a steady bleed.
  Worst day −9.8% (2021-01-15), worst week −12.3%, skew −0.95.
- **Worst index days:** on the 22 worst equal-weight days (1%; index mean −17.8%) the book loses
  −0.64% a day, against −0.06% on all days. Its beta to the index is +0.016 on down days and −0.009
  on up days. The hedge holds on average, but the residuals move against the book on those days.
- **PC1 spikes:** in the 18 weeks with the top 5% rise of the 30-day PC1 share it makes −0.57% a week,
  against −0.37%.
- **The 10 crashes one by one:** the book was trading on 9 of them and lost on 7 (−0.6% to −3.8%).
  The week after ranged from −9.2% (2021-09) to +8.9% (2025-10).
- So it is mildly short crash risk, as the article warns. But with no edge, the crash exposure is a
  second-order problem.

**Single-name R version** (u143 all dates; 12 coins 2024+). P(N R) is +N R before −1R within 100
bars. For reference, 1/(N+1) is 0.667, 0.500, 0.333, 0.200 and 0.091 at N = 0.5, 1, 2, 4, 10.

| book | trades | mean R [90%] | stopped | P0.5R | P1R | P2R | P4R | P10R |
|---|---|---|---|---|---|---|---|---|
| fresh 1d real | 2,158 | **−0.169 [−0.258, −0.082]** | 72% | 0.515 | 0.429 | 0.317 | 0.199 | 0.072 |
| fresh 1d iid | 1,996 | +0.048 | 83% | 0.444 | 0.402 | 0.322 | 0.218 | 0.103 |
| fresh 1d OU | 1,662 | +0.248 | 79% | 0.477 | 0.430 | 0.362 | 0.249 | 0.126 |
| fresh 4h real | 15,083 | **−0.192 [−0.240, −0.145]** | 75% | 0.494 | 0.427 | 0.318 | 0.198 | 0.083 |
| fresh 4h iid | 13,848 | +0.050 | 83% | 0.447 | 0.405 | 0.328 | 0.226 | 0.112 |
| fresh 4h shuffle | 14,818 | −0.056 | 80% | 0.455 | 0.413 | 0.331 | 0.218 | 0.105 |
| fresh 4h OU | 11,792 | +0.420 | 77% | 0.481 | 0.447 | 0.379 | 0.274 | 0.143 |
| 12 coins 4h real (2024+) | 728 | −0.299 [−0.489, −0.080] | 79% | 0.446 | 0.357 | 0.247 | 0.162 | 0.077 |
| 12 coins 1h real (2024+) | 3,139 | −0.530 | 77% | 0.491 | 0.421 | 0.315 | 0.199 | 0.087 |
| 12 coins 15m real (2024+) | 13,185 | −1.163 | 78% | 0.483 | 0.422 | 0.321 | 0.202 | 0.088 |

- **Real P(N R) is above the null at small N and below it in the tail.** P(≥4R) is 0.198 against
  0.218 to 0.226, and P(≥10R) 0.072 to 0.083 against 0.103 to 0.112.
  - A stretched alt moves back a little and then keeps going the way it was stretched. That is the
    reverse of the shape the desk is looking for.
- **Even the OU control is a thin R trade.** Unhedged, a single-name fade carries all of the market's
  noise against a stop of a fraction of an ATR. That is why the article trades a hedged book.

## C. DISPLACE_C: market beta or residual?

18,082 trades on the 131 fresh coins, E2 structure exit, the turn_confirm cost. The market part uses
the equal-weight index of 143 coins with a trailing 60-bar beta (mean about 1.03). The 90% intervals
are day bootstraps.

| sample | trades | R [90%] | market part | residual [90%] | residual on BTC |
|---|---|---|---|---|---|
| all, 4h+1d | 18,082 | +0.041 [−0.003, +0.084] | **+0.056** | **−0.016 [−0.025, −0.006]** | −0.005 [−0.043, +0.033] |
| longs, 4h+1d | 8,194 | +0.050 [−0.016, +0.114] | +0.054 | −0.004 [−0.021, +0.014] | −0.060 [−0.130, −0.003] |
| shorts, 4h+1d | 9,888 | +0.033 [−0.031, +0.098] | +0.058 | −0.025 [−0.035, −0.016] | +0.040 [−0.009, +0.090] |
| longs, 1d | 958 | +0.207 [+0.024, +0.367] | +0.185 | +0.022 [−0.017, +0.059] | −0.022 |
| shorts, 1d | 1,257 | +0.065 | +0.065 | +0.000 [−0.023, +0.023] | +0.071 |
| longs, 4h | 7,236 | +0.029 | +0.037 | −0.007 [−0.025, +0.012] | −0.065 |
| shorts, 4h | 8,631 | +0.028 | +0.057 | −0.029 [−0.039, −0.018] | +0.036 |
| FRESH 58 (as published) | 8,977 | +0.049 [+0.001, +0.098] | +0.058 | −0.008 [−0.022, +0.006] | |
| SET_C 73 (as published) | 9,105 | +0.032 [−0.014, +0.078] | +0.055 | −0.023 [−0.036, −0.010] | |

- **Against the equal-weight index, the whole edge is the market part,** on both sides and in both
  sets. The residual is at or below zero everywhere. Longs at 1d keep +0.02R of residual, inside its
  interval.
- **Against BTC the split moves.** BTC's beta is higher (about 1.34) and BTC's turns are not the alts'
  turns. Longs then look all-BTC with a negative residual, and shorts keep a residual of +0.04R
  [−0.01, +0.09]. Neither is significant.
- **It is timing, not holding.** Both sides earn a positive market part:
  - a long earns when the index rises over the trade;
  - a short earns when it falls.
  A static beta would make one side pay. The trade turns when the market turns.
- **The "regress the side on the market" check:**
  - The slope of the trade's side on the index's return over the trade is +0.056 per standard
    deviation (4h+1d), +0.032 at 4h and +0.155 at 1d. BTC gives +0.035.
  - The side matches the sign of the index's move only 43.5% of the time. The market part comes from
    size: when it is right, the market move is large and the trade is held longer.

**The same signals traded on the market instead of the alt.** Same side and same holding period. In
basis points of notional a trade, net, with 90% day-bootstrap intervals. The alt is as traded (its R ×
risk, after turn_confirm's 0.07% once). The basket and BTC pay 0.07% a side.

| sample | trades | alt, net | equal-weight basket, gross | basket, net [90%] | BTC, gross | BTC, net [90%] |
|---|---|---|---|---|---|---|
| 4h+1d, both | 17,427 | +28.6 [−7, +68] | +34.0 | **+20.0 [−11, +54]** | +11.5 | −2.5 [−28, +24] |
| 4h+1d, longs | 7,873 | +50.7 [−3, +109] | +49.6 | +35.6 [−13, +87] | +52.0 | +38.0 [−1, +84] |
| 4h+1d, shorts | 9,554 | +10.4 [−41, +64] | +21.2 | +7.2 [−40, +54] | −21.9 | −35.9 [−64, −9] |
| 1d, both | 2,146 | +175 [−2, +350] | +158 | +144 [−24, +320] | +89 | +75 [−45, +215] |
| 4h, both | 15,281 | +8.0 [−24, +40] | +16.7 | +2.7 [−27, +34] | +0.7 | −13.3 [−33, +7] |

- **The equal-weight basket keeps about 70% of the alt's net edge per trade**, with the same signals
  and none of the alt's idiosyncratic risk.
- **BTC keeps the longs and loses the shorts.** An alt's bearish turn is not BTC's.
- **None of these intervals excludes zero.** This is a decomposition of a thin edge, not a new one.

The article's question has a plain answer here: DISPLACE_C's thin edge is beta in a costume, and the
beta is timed. Trading the basket rather than the alt keeps most of it. The residual it adds is zero or
negative.

## Caveats

- **Discovery on 12 coins is a small book.** It averages 1.6 to 1.9 positions, so its Sharpe is noisy.
  The pick was "least bad" among 36 losing cells. Confirmation on 131 coins (about 12 positions) does
  not depend on the pick: every grid cell loses there too.
- **Windows are in bars at every timeframe** (252/60, Avellaneda-Lee in days). At 4h that is a 42-day
  PCA and a 10-day OU fit. Day-based windows at 4h are untested.
- **Survivorship.** The fresh lists are perpetuals that existed on Binance at some point, including
  delisted ones, for as long as their data runs. A coin's last bar before delisting enters with a zero
  next return.
- **The synthetic panels pay real funding** on synthetic positions. That adds noise but no bias. They
  are built from a full-sample factor fit, which is fine for a null but would be look-ahead in a
  trade.
- **The macro 4h universe** has only 106 windows, because its 14 clocks rarely share a 4h bar. The 1d
  row is the one to read.
- **C's market part is measured close to close** from the signal bar to the exit bar. The trade enters
  at the next open and a stop fills intrabar. The equal-weight basket of 143 perpetuals is not one
  instrument. Its "same signals on the market" cost (0.07% a side) is a floor.


## The desk's process against the article's checklist

The article's checklist:
- decompose before you trade;
- trade the residual, not the market;
- demand reversion you can measure (a half-life);
- pay realistic costs;
- test against randomness;
- check whether the "alpha" is beta;
- look at the tail.

The desk already does most of it, in its own form:
- Every rule is frozen in a JSON before the data is seen.
- Every result is set against matched random walks and 1/(N+1) ([walks-and-edge.md](walks-and-edge.md)).
- Costs and funding are real.
- Confirmation is on data never looked at, with BH across the secondary cells.
- Tails are reported as P(≥ N R).

Where it differs:
- **The desk's nulls are per series; the article's are per panel.** A walk matched to one coin cannot
  test a cross-sectional idea. Here the nulls keep the real factor structure and change only the
  residual: an iid residual, a shuffled real residual, and an OU residual as the positive control.
- **The desk measures single-name R, the article a hedged book's Sharpe.** This study reports both.
  They disagree in an informative way (below).
- **The desk had not split its trades into beta and residual.** Study C does it for the one result
  that passed (DISPLACE_C).
- **The article treats PCA as the factor model.** The desk had only used PCA for co-movement
  ([generated.md](generated.md)). Here it is also the yardstick for how many bets the desk actually
  holds when it trades many coins.

## Re-running

On the lab, with `PYTHONPATH` holding the code (and the repo for `mt5bt`), `OUT`, `DATA`, `CACHE`
(the fresh 4h/1d klines) and `MT5BT_DB` set:

- `MODE=fetch` (fresh coins' 1h, 15m and funding)
- `MODE=spectra`, `MODE=discover` (writes `pca_selected.json`), `MODE=confirm`
- `MODE=displace`, `MODE=report`, `MODE=plot`

Plots are in `.data/pca/` (not committed):
- `spectra_mp.png`, `pc1_share_and_bets.png`, `sscore_examples.png`
- `equity.png`, `drawdown.png`, `displace_split.png`, `pnr.png`
