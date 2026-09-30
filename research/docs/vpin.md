# VPIN as a shock warning: true order-flow toxicity adds nothing that volume does not

Harness: [`research/harness/vpin.py`](../harness/vpin.py). Lab runs 2026-09-30:
`logs/vpin_15m.log`, `logs/vpin_1h.log`, `logs/vpin_lead.log`.

## The question

VPIN, the Volume-Synchronized Probability of Informed Trading (Easley, López de Prado & O'Hara,
"Flow Toxicity and Liquidity in a High-Frequency World", RFS 2012; "The Microstructure of the
'Flash Crash'", JPM 2011), was built to warn of liquidity events. It was never meant to call
direction. This repo had only tested order flow for direction, in [`orderflow.md`](orderflow.md) and
[`directional-questions.md`](directional-questions.md), and both were null.

This study asks what VPIN was built for. Does flow toxicity warn of shocks, range blowouts and
volatility bursts, beyond what the production shock forecaster already knows, and beyond plain
volume and trade intensity?

## Data and method

**Data.** Binance USDT-M futures for BTC, ETH and SOL, from 2025-09 to 2026-08. These are the
1-minute bars of [`orderflow.md`](orderflow.md), which carry the **true taker buy and sell volume**
(`is_buyer_maker`). That gives a real VPIN, not an estimate.

**VPIN.**
- Volume is cut into equal-volume buckets, each 1/50 of the average daily volume (about half an hour
  of trading). A minute that straddles a bucket boundary is split pro rata.
- VPIN is the mean |buy − sell| / V over the last 50 buckets, known once the last bucket completes.
- Its CDF is its rank against the trailing 1,500 buckets.

**Variants and controls.**
- **`bvc`:** the same buckets, with buy volume estimated by bulk volume classification from 1-minute
  prices. This is what VPIN becomes without an aggressor side.
- **`barproxy`:** the bar-level proxy used in `ensemble.py`.
- **`shuffled`:** true VPIN with each minute's buy share permuted within its day. Volume and timing
  are kept, and toxicity is destroyed.
- **Volume placebo:** bar volume, trade count and the last four bars' volume, each against its
  trailing median. This is the Andersen & Bondarenko (2014) critique: VPIN may just track volume and
  intensity.
- **Walks we generate:** iid t(3) prices, with the real series' volume and trade counts, and a
  random buy share.

**Targets,** on 15m and 1h clock bars, as production uses:
- a 4× shock in the next 4 bars, which is the production forecaster's own label. Its features come
  from replaying the bars through the production `Shocks` class;
- a range blowout, meaning a bar range above 3× the trailing mean, in the next 4 bars;
- realised volatility over the next 1h and 4h.

**Fitting.** Gradient boosting, fit on the first 60% of time and scored on the last 40%, with the
halves of the test block reported. Confidence intervals come from resampling whole days.

**Pass bar, pre-registered.** The AUC gain of (forecaster + volume + VPIN) over (forecaster +
volume) must be at least 0.01, with its confidence interval above 0, in both halves. There must be
no such gain on shuffled signs or on walks.

## Results

**VPIN adds nothing to the shock forecaster.** Pooled over BTC, ETH and SOL:

| 15m (104,358 rows) | AUC | gain over base + volume [95%] | halves |
|---|---|---|---|
| base (the production forecaster's features) | 0.7676 | | |
| base + volume | **0.7821** | +0.0145 [+0.0066, +0.0233] over base | +0.0097 / +0.0191 |
| base + volume + **true VPIN** | 0.7757 | **−0.0064 [−0.0099, −0.0024]** | −0.0104 / −0.0024 |
| base + volume + shuffled VPIN | 0.7796 | −0.0024 [−0.0058, +0.0017] | −0.0029 / −0.0022 |
| base + volume + BVC VPIN | 0.7808 | −0.0013 [−0.0053, +0.0035] | −0.0027 / +0.0000 |
| base + volume + bar proxy | 0.7808 | −0.0013 [−0.0032, +0.0005] | −0.0016 / −0.0009 |

| 1h (25,518 rows) | AUC | gain over base + volume [95%] |
|---|---|---|
| base | 0.7603 | |
| base + volume | 0.7526 | |
| base + volume + true VPIN | 0.7463 | −0.0063 [−0.0187, +0.0061] |

Per symbol at 15m, true VPIN's gain over base + volume:

| symbol | gain [95%] |
|---|---|
| BTC | +0.0022 [−0.0039, +0.0096] |
| ETH | −0.0086 [−0.0177, +0.0004] |
| SOL | −0.0080 [−0.0188, +0.0014] |

At 1h, ETH's gain is −0.0263, with its interval below zero. No symbol, interval or variant passes.

**Robustness.** At 15m, the gain over base + volume across bucket size (ADV/25, /50, /100) and window
(25, 50, 100 buckets) runs from −0.0007 to −0.0064. It is never positive.

**Blowouts and realised volatility.**
- Blowout AUC gain from true VPIN over base + volume is +0.0004 [−0.0033, +0.0033] at 15m and −0.0106
  at 1h.
- For realised volatility, true VPIN adds +0.007 to +0.010 of out-of-sample R² over the production
  unit plus volume.
- **Shuffled VPIN adds the same or more** (+0.009 to +0.015), so what little it carries is the
  volume clock, not toxicity.
- Volume itself adds +0.023 (15m, 1h target) and +0.086 (1h bars, 1h target) over the production
  unit.

**The flash-crash claim.** Shock lift in the bars where VPIN's CDF is above 0.9, against the top
decile of plain volume:

| | true VPIN | shuffled | BVC | volume top decile |
|---|---|---|---|---|
| 15m | 1.42x | 1.23x | 1.97x | **2.89x** |
| 1h | 1.64x | 1.22x | 2.38x | **2.64x** |

High VPIN does come before more shocks, but plain volume comes before twice as many. The move over
the next 4 bars after high VPIN is 0.95-1.02x its usual size, so no larger adverse move follows.

**Lead-lag.** Across 1,237 one-minute shocks (|r| above 10× the trailing mean, at least an hour
apart), the table gives VPIN's CDF around each shock minus its CDF at random minutes:

| minutes from the shock | −60 | −5 | 0 | +15 |
|---|---|---|---|---|
| BTC | −0.036 | −0.039 | −0.013 | +0.019 |
| ETH | −0.029 | −0.020 | +0.012 | +0.048 |
| SOL | −0.025 | −0.018 | +0.021 | +0.055 |

- **VPIN is below normal before a shock** and rises only with it and after it.
- The shuffled version shows the same shape, so the rise is the shock's own volume filling the
  buckets.
- Plain 60-minute volume is **already 1.5-1.7x its norm an hour before** the shock.

**FX and Deriv.** [`lopez-de-prado.md`](lopez-de-prado.md) tested VPIN built from tick volume with
bulk volume classification. The gain over the forecaster was −0.0030 on FX, −0.0021 on Deriv and
+0.0052 on crypto, the same as its walks' +0.0052. A retail MT5 feed's tick volume counts quote
updates, not signed trades, so VPIN's premise has nothing to measure there.

## What this means

- **VPIN does not warn of shocks beyond what the desk already knows.** True, exchange-grade order
  flow toxicity makes the production shock forecaster slightly *worse* at 15m (−0.006) and does
  nothing at 1h. Every variant fails: BVC, bar proxy, and every bucket size and window.
- **The Andersen & Bondarenko critique holds here.** What looks like VPIN's warning is trading
  volume. Plain volume and trade intensity add +0.015 AUC to the forecaster and lead shocks by an
  hour. Their top decile carries twice the shock lift of VPIN's top decile, and shuffling the
  aggressor side keeps what VPIN adds to realised volatility.
- **Before a shock, flow is if anything *less* one-sided than usual.** Toxicity shows up only as the
  shock's own volume arrives, which is too late to be a warning.

## For production

- **No VPIN.** Nothing passed, so no trade feed with an aggressor side is needed for it.
- **The finding that does carry is volume.** Bar volume and trade count against their trailing
  median add +0.0145 [+0.0066, +0.0233] AUC to the shock forecaster on crypto 15m, in both halves.
  This test measured it on true exchange volume only. Before the forecaster takes volume features, it
  needs its own test on the volume production actually has: exchange volume on crypto feeds, and the
  broker's tick volume on FX and Deriv, where [`lopez-de-prado.md`](lopez-de-prado.md) found tick
  counts carry nothing for VPIN.
