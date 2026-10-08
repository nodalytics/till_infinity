# The FX short-term reversal confirms on six majors, and costs more than it earns

Measured 2026-10-08 on the lab with [`statespace_fx.py`](../harness/statespace_fx.py) and
[`statespace_fx_report.py`](../harness/statespace_fx_report.py). The rules were frozen in the
harness before any number was read.

## Verdict

| question | answer |
|---|---|
| Does the EURUSD reversal from [`state-space-filters.md`](state-space-filters.md) hold on other majors? | **Yes, at 15m and 1h.** All six pairs (GBPUSD, USDJPY, AUDUSD, USDCAD, USDCHF, NZDUSD) have a cell passing the frozen rule, where four were needed. 20 of 72 cells pass Benjamini-Hochberg and beat their walks by at least 0.005. |
| How big is it? | AUC 0.508-0.516 with the rollover masked, against walks at 0.496-0.502. The Kalman drift persistence is phi = -0.014 to -0.036 in 10 of the 12 pair-timeframes at 15m and 1h (the other two fits went to a different optimum): the next bar partly undoes this one. |
| Is it the rollover? | **No.** With 20:00-23:00 UTC and every bar after a gap removed, the AUC falls only 0.001-0.009 from the unmasked figure. |
| At 4h and 1d? | **Gone.** Not one 4h or 1d cell passes. The intervals at 4h straddle 0.5 on every pair, and phi wanders in both signs. |
| Does it pay? | **Not at a retail price.** The confident decile, held one bar, grosses -0.3 to +0.7 bps on the passing cells (19 of 20 positive; up to 0.8 pip). 8 of the 20 passing cells clear the broker's quoted spread, by at most +0.37 bps. **None clears a 1-pip round trip.** |

## 1. What was frozen

The finding came from EURUSD, so EURUSD could not confirm it. The rules were fixed before the
run:
- **Pairs:** the six other USD majors. EURUSD was re-run through the same pipeline as a reference
  and not counted.
- **Data:** 15m and 1h from the broker's bars (50,000 each, test blocks from 2025-12 and 2023-07);
  4h and 1d aggregated from the 1h bars in UTC.
- **Models:** exactly the three forms that passed on EURUSD, unchanged from
  [`statespace.py`](../harness/statespace.py): Kalman on closes, Kalman on the full candle, HMM on
  the full candle. Fitted on the first 60%, scored on the last 40%.
- **Walks:** two flip walks (real bars, random sign) and one GARCH-t walk per cell.
- **The rollover mask.** Bar times are UTC: the week opens Sunday 21:00 or 22:00, and the 15m
  spread is 2 points every hour except 21:00, where it is 8. A forecast is scored only if neither
  the bar it is made on nor the bar it predicts overlaps 20:00-23:00 UTC, and the predicted bar
  follows without a gap. That removes 12% of 1h bars. Daily bars contain the rollover, so 1d is
  scored unmasked.
- **Pass:** Benjamini-Hochberg at q = 0.05 over the 72 cells (6 pairs x 4 timeframes x 3 models)
  **and** at least 0.005 above the mean of the cell's walks.
- **Confirmed** if at least four of the six pairs pass at 15m or 1h with EURUSD's sign.
- **Pays** if the confident decile (threshold from training, held one bar, one round trip each) is
  net positive at the pair's quoted spread. It is also reported at 1 pip.

## 2. Results

AUC with the rollover masked, real [95% block interval] (mean of the three walks). A star marks a
cell that passes:

| pair | tf | test bars | kalman close | kalman candle | hmm candle | phi |
|---|---|---:|---|---|---|---:|
| GBPUSD | 15m | 17,291 | 0.515* [0.507-0.522] (0.499) | 0.514* [0.505-0.523] (0.501) | 0.493 (0.499) | -0.022 |
| GBPUSD | 1h | 16,666 | 0.507 [0.498-0.515] (0.498) | 0.508 [0.499-0.516] (0.498) | 0.508 [0.499-0.517] (0.499) | -0.421 |
| USDJPY | 15m | 17,291 | 0.514* [0.505-0.523] (0.498) | 0.516* [0.508-0.525] (0.497) | 0.516* [0.508-0.525] (0.496) | -0.027 |
| USDJPY | 1h | 16,666 | 0.490 (0.499) | 0.490 (0.502) | 0.510* [0.502-0.518] (0.496) | +0.386 |
| AUDUSD | 15m | 17,291 | 0.515* [0.507-0.522] (0.501) | 0.516* [0.508-0.524] (0.501) | 0.497 (0.499) | -0.021 |
| AUDUSD | 1h | 16,666 | 0.506 [0.499-0.514] (0.498) | 0.505 (0.496) | 0.509* [0.501-0.517] (0.501) | -0.036 |
| USDCAD | 15m | 17,291 | 0.512* [0.503-0.520] (0.500) | 0.515* [0.506-0.523] (0.500) | 0.489 (0.501) | -0.026 |
| USDCAD | 1h | 16,666 | 0.508* [0.501-0.516] (0.499) | 0.509* [0.502-0.516] (0.499) | 0.510* [0.504-0.519] (0.495) | -0.027 |
| USDCHF | 15m | 17,293 | 0.508 [0.500-0.517] (0.499) | 0.514* [0.506-0.523] (0.498) | 0.499 (0.500) | -0.014 |
| USDCHF | 1h | 16,665 | 0.510* [0.502-0.519] (0.497) | 0.511* [0.502-0.520] (0.497) | 0.510* [0.501-0.518] (0.498) | -0.018 |
| NZDUSD | 15m | 17,297 | 0.509 [0.501-0.517] (0.500) | 0.512* [0.504-0.522] (0.502) | 0.513* [0.506-0.522] (0.500) | -0.017 |
| NZDUSD | 1h | 16,666 | 0.503 (0.502) | 0.498 (0.503) | 0.500 (0.500) | -0.028 |
| *EURUSD (reference)* | 15m | 17,291 | 0.516 [0.506-0.525] (0.498) | 0.517 [0.507-0.527] (0.498) | 0.495 (0.502) | -0.023 |
| *EURUSD (reference)* | 1h | 16,666 | 0.512 [0.504-0.520] (0.497) | 0.509 [0.502-0.518] (0.497) | 0.511 [0.504-0.519] (0.497) | -0.044 |

4h and 1d, every pair: AUC 0.460-0.517 with intervals across 0.5, walks 0.487-0.523. No cell
passes. The full table, with the unmasked AUCs, is the report script's output.

Three things to read from it:
- **The Kalman form carries it at 15m** on every pair (0.508-0.516). The HMM on the candle carries
  it at 1h on four pairs, including USDJPY and AUDUSD, where the Kalman fit did not.
- **Two Kalman fits went to a different optimum.** GBPUSD 1h (phi -0.42) and USDJPY 1h (phi +0.39)
  found a slow drift instead of the one-bar reversal. USDJPY 1h then scores below a coin (0.490),
  while the HMM on the same bars finds the reversal (0.510). That is a weakness of the fit, not
  evidence against the effect. It was not re-fitted, because the rules were frozen.
- **The rollover is not the source.** Masked against unmasked, Kalman close at 15m: GBPUSD
  0.515 / 0.521, USDJPY 0.514 / 0.519, AUDUSD 0.515 / 0.519, USDCAD 0.512 / 0.520. The mask removes
  a little, about what the noisier rollover bars added, and leaves the effect standing.

## 3. What it is worth

Confident decile, held one bar: gross, then net at the pair's quoted spread and at 1 pip, in bps
(t of the gross):

| pair | quoted / 1 pip cost | best passing cell | n | gross | net, quoted | net, 1 pip |
|---|---|---|---:|---|---|---|
| GBPUSD | 0.22 / 0.75 | 15m kalman close | 1,687 | +0.20 (t 1.5) | -0.03 | -0.55 |
| USDJPY | 0.20 / 0.65 | 15m kalman close | 1,578 | +0.39 (t 1.9) | +0.19 | -0.26 |
| AUDUSD | 0.31 / 1.52 | 1h hmm candle | 1,605 | +0.32 (t 0.9) | +0.02 | -1.20 |
| USDCAD | 0.22 / 0.72 | 15m kalman close | 1,751 | +0.22 (t 2.1) | +0.00 | -0.50 |
| USDCHF | 0.37 / 1.24 | 1h kalman candle | 1,567 | +0.74 (t 2.4) | +0.37 | -0.50 |
| NZDUSD | 1.02 / 1.71 | 15m hmm candle | 1,691 | +0.40 (t 2.3) | -0.63 | -1.31 |

The gross edge is about a third to two thirds of a pip a trade at 15m and 1h. The broker's
quoted spread on the majors is 0.2-0.4 bps, which leaves at most +0.37 bps on the best cell and
about zero on most. A standard retail account's 1-pip round trip turns all 20 passing cells
negative. No t-statistic of the gross reaches 3: a real sign, too small to see trade by trade.

## 4. What this settles, and what it does not

- **It settles that the effect is real and general.** A one-bar reversal at 15m and 1h is present
  on all seven USD majors, survives the rollover mask, and is absent on walks with the same bars.
  It replicates the spring in [`physics.md`](physics.md) (slope -0.015 to -0.028) by a different
  method.
- **It is not seven independent confirmations.** The six pairs share the dollar, which is the
  book's one real factor ([`linear-algebra.md`](linear-algebra.md)), and the 15m test blocks cover
  the same months. Part of what replicates is the same dollar moves seen through six quotes. The
  crosses (EURGBP, EURCHF, AUDJPY and the rest), which do not carry the dollar, are the
  independent test still to run.
- **It does not make a strategy at the desk's costs.** To trade it would take execution near the
  quoted spread on a raw account, or better than the spread: resting limit orders on the
  reversal side, whose own winner's curse [`limitfills.md`](limitfills.md) has measured. That is a
  question about execution, not about the signal.
- **4h and 1d have nothing.** Whatever the reversal is, it lives inside an hour, below where
  multi-timeframe or swing trading on this desk operates.
