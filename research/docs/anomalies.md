# Anomalies before they happen: shocks and range blowouts are visible an hour or more ahead, on real markets only

Measured 2026-09-29 on the lab with [`anomalies.py`](../harness/anomalies.py): the lab's broker bars at
15m and 1h for 15 FX pairs, XAU and XAG, BTC, ETH and SOL, with Deriv Boom/Crash, Jump and Volatility
indices as controls. Models are fit on each family's first 60% by time and scored on the last 40%,
both halves reported.

## The question

Production's anomaly detection (`structures/learning/anomaly.py`) flags cross-venue dislocations
**as they happen**: a venue off consensus, a spread blowing out, a quote gone stale. Can anomalies be
seen **before** they happen, and how early?

Four anomalies, each against the series' own trailing history:
- **shock:** a bar's |return| above 4x its trailing mean;
- **range:** a bar's high - low above 4x the trailing mean range;
- **spread:** the broker's spread above 3x its trailing median;
- **gap:** the open more than 3x the mean |return| from the previous close.

The target is any anomaly in the next 4 bars. A lead-time curve moves that window further out: bars
1-4, 5-8, 9-12 and 17-20.

The predictors are all known at the bar's close:
- volatility state: the EWMA of true range against its 500-bar mean, `tr_percentile`, and the
  volatility of volatility;
- spread against its median, and spread creep;
- recent anomaly counts, to test whether anomalies cluster;
- bars to the next and since the last medium- or high-importance release for the instrument's
  currencies;
- the hour, the weekday, and hours to the Friday close.

## Results

| | anomaly rate in the next 4 bars | gradient boosting AUC (halves) | top-decile hit (lift) | lead time: 1-4 / 5-8 / 9-12 / 17-20 bars |
| --- | --- | --- | --- | --- |
| FX shock, 15m | 6.7% | **0.786** (0.785 / 0.787) | 26.1% (3.9x) | 0.785 / 0.762 / 0.752 / 0.740 |
| FX range, 15m | 2.2% | **0.781** (0.785 / 0.778) | 9.7% (4.3x) | 0.781 / 0.755 / 0.743 / 0.723 |
| FX shock, 1h | 7.3% | 0.764 (0.775 / 0.751) | 23.3% (3.2x) | 0.763 / 0.742 / 0.735 / 0.727 |
| FX range, 1h | 2.4% | **0.802** (0.808 / 0.795) | 9.4% (3.9x) | 0.804 / 0.785 / 0.770 / 0.756 |
| metals shock / range, 15m | 7.5% / 2.4% | 0.773 / 0.786 | 3.9x / 4.5x | shock 0.774 → 0.720 |
| metals shock / range, 1h | 8.6% / 2.9% | 0.764 / **0.811** | 3.2x / 4.0x | range 0.813 → 0.776 |
| crypto shock / range, 15m | 8.3% / 2.9% | 0.762 / 0.786 | 3.4x / 4.0x | shock 0.765 → 0.732 |
| crypto shock / range, 1h | 9.0% / 2.9% | 0.778 / 0.795 | 3.3x / 4.3x | range 0.797 → 0.723 |
| **gap**, FX / metals, 15m | 1.0% / 0.5% | **0.972 / 0.970** | 9.6x / 8.3x | flat at 0.95-0.97 |
| **gap**, FX / metals, 1h | 0.9% / 0.6% | 0.967 / 0.922 | 11.2x / 8.7x | flat at 0.92-0.97 |
| **controls: Boom/Crash, Jump, Volatility shocks** | 0.8-4.0% | **0.486-0.518** | 0.9-1.2x | 0.47-0.55 |

- **Shocks and range blowouts can be seen coming**, at AUC 0.76-0.81, with 3-4.5x the base rate in
  the top decile. The two halves agree within 0.02 in most cells and within 0.12 in all (the widest is crypto range at
  15m, 0.717 against 0.833).
- **The warning lasts.** Anomalies 17-20 bars out are still ranked at 0.72-0.78, so the signal is a
  state that persists, not a flicker just before the event. At 1h that is most of a day ahead.
- **What carries it is volatility state:** the EWMA against its norm scores 0.60-0.77 on its own and
  `tr_percentile` 0.60-0.73, then recent anomaly counts (clustering). For metals, closeness to a
  scheduled release carries it too: its single-feature AUC reads 0.32-0.35 because a *shorter* time
  to the release means more risk, which is 0.65-0.68 read the right way round.
- **Gaps are nearly fully predictable (0.92-0.97)**, because they are the calendar: the weekend
  close and scheduled releases. The signal is flat with lead time because the calendar is known
  far ahead.
- **The controls are dead flat (0.49-0.52),** exactly as they must be. Boom and Crash spikes, Jump
  jumps and Volatility index moves are published as memoryless ([`generators.md`](generators.md)),
  so nothing seen beforehand can time them. The one exception is range on Boom/Crash at 15m (0.588,
  volatility of volatility), which is small.
- **Spread blowouts** (3x the median) were too rare in the lab's bar-level spread field to score. The
  production detector's venue-level spread readings are the place to test them.

## What this means

- **Anomalies are predictable before they happen on real markets, and the warning is volatility.**
  This is the same fact as [`crash-timing.md`](crash-timing.md) and the spike switch, measured
  here across four anomaly kinds and with a lead-time curve.
- **Nothing here says which way.** A shock is a shock in either direction.
- **The use is risk:** widen or skip a trade when a shock is likely, and flag it on the card. It is
  not a direction call. [`session-switch.md`](session-switch.md) is the caution. Production's stops
  already scale with volatility, so a *second* volatility-based size cut on top of them sized on
  reversion rather than risk. Any anomaly score used in sizing has to be measured in production's
  R units first. Published on the cards, it costs nothing and tells the reader something true.
