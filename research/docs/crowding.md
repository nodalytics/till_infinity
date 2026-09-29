# Crowding and reversal: a small, consistent lean in crypto that does not trade, and nothing in FX

Measured 2026-09-29 on the lab with [`crowding.py`](../harness/crowding.py). The hypothesis was
pre-registered before any data was read, following "maximum consensus = maximum fragility"
([`atlas.md`](atlas.md)), the one non-price directional idea this desk had not tested: **the more
crowded a side, the worse it does next.** It had to hold **beyond the past return**, because
positioning follows price.

## Data

- **Crypto:** 10 Binance USDT-M perpetuals (BTC, ETH, SOL, BNB, XRP, DOGE, ADA, AVAX, LINK, LTC),
  hourly, January 2022 to August 2026: 408,600 coin-hours.
  - Four readings, each a z-score against its own trailing 30 days: the funding rate, the all-account
    long/short ratio, the top traders' long/short ratio, and the 24-hour change in open interest.
  - `crowded` is their mean.
  - Forward returns start one hour after the reading.
- **FX:** CFTC Commitments of Traders, weekly.
  - The legacy report's speculators, 2000-2026 (8,457 currency-weeks), and the TFF report's leveraged
    funds, 2017-2026 (2,950).
  - EUR, JPY, GBP, AUD, CAD, CHF and NZD, each against its USD pair.
  - Net position over open interest is a z-score against the trailing 156 weeks.
  - Tuesday's report is public on Friday, so the return starts at the next close.

## Crypto: the lean is there, and it is small

Rank correlation of each reading with the forward return, then [beyond the past 7-day return], then
(the two halves by time). The standard error is about 0.022 after allowing for overlap:

| | 8h | 1d | 3d | 7d |
| --- | --- | --- | --- | --- |
| funding | -0.027 [-0.023] (-0.029 / -0.026) | -0.029 [-0.023] | -0.028 [-0.022] | -0.010 [+0.001] |
| all-account long/short | -0.007 | -0.014 [-0.021] | -0.034 [-0.043] (-0.064 / -0.004) | -0.035 [-0.047] |
| top traders' long/short | -0.006 | -0.006 | -0.003 | -0.002 |
| open interest change | -0.032 [-0.029] | -0.029 [-0.026] (-0.053 / -0.004) | -0.019 | -0.012 |
| **crowded (all four)** | **-0.030** [-0.026] (-0.035 / -0.025) | **-0.035** [-0.032] (-0.044 / -0.027) | **-0.038** [-0.034] (-0.039 / -0.038) | -0.024 [-0.017] |
| *past 7-day return* | -0.018 | -0.022 | -0.026 | -0.037 |

- **The direction is the hypothesis's**, and it is consistent. The composite is negative at every
  horizon, in both halves, and beyond past return.
- **It is small**: about 1.5 standard errors on a conservative estimate, at a correlation of -0.03.
- **The top traders' positioning carries nothing.** The signal is in funding, the crowd's
  long/short ratio and open interest.

**Traded:** fading each coin's own extremes (the trailing 10% / 90% over 180 days), one position per
horizon at a time, net per trade:

| | n | gross (halves) | net of Deriv / taker | shifted-null z |
| --- | --- | --- | --- | --- |
| crowded, 1 day | 3,684 | **+17.4bp** ± 7.7 (+41.5 / **-6.9**) | +15.0 / +7.4 | +2.6 |
| crowded, 7 days | 503 | -70.4bp ± 50.5 (+16.7 / -180.7) | -72.8 / -80.4 | -1.6 |
| funding, 1 day | 3,869 | +9.4bp ± 7.5 (+15.3 / +3.8) | +7.0 / -0.6 | +1.3 |
| all-account long/short, 1 day | 3,371 | +11.9bp ± 7.6 (+14.7 / +9.4) | +9.5 / +1.9 | +1.5 |
| **cross-section** (short the 3 most-funded coins, long the 3 least), 1 day | 1,684 days | +2.9bp ± 5.2 (+3.0 / +2.8) | below the 4.8bp it costs | t +0.55 |

- **The best trade** (the composite, 1 day) clears its shifted null at z +2.6. But all of it comes from
  the first half (+41.5), and the second half is negative (-6.9).
- **At 7 days** every version loses.
- **The cross-sectional version**, the textbook "funding carry" trade on price alone, makes 2.9bp
  a day against 4.8bp of round trips.

## FX: nothing

| | 1 week | 4 weeks | 13 weeks |
| --- | --- | --- | --- |
| speculators' crowding z (legacy), 2000-2026 | -0.002 [+0.002] | +0.012 [+0.018] | +0.010 [+0.020] |
| leveraged funds' crowding z (TFF), 2017-2026 | -0.021 [-0.015] | -0.042 [-0.032] | -0.032 [+0.001] |
| weekly change in speculators' positioning | -0.016 | -0.017 | -0.000 |

(standard errors about 0.022 for the legacy report and 0.037 for TFF at 4 weeks)

**Fading the extremes loses on the legacy report:** -21bp per 4 weeks at |z| ≥ 1.5 (n = 435) and
-45bp at |z| ≥ 2. On TFF it makes +20 ± 22bp, which is noise.

## What this settles

- **Crowding does reverse in crypto, weakly:** a correlation of about -0.03 with the next day or
  three, consistent in sign and in both halves. It is the first non-price, non-flow directional
  reading here with a consistent sign.
- **It does not trade.** The one positive trade lives in one half. The 7-day version loses, and the
  cross-section loses to costs.
- **FX speculator positioning predicts nothing** at one to thirteen weeks.
- **Possible use:** as a size or vote input it would need a pre-registered forward test. At -0.03 it
  is not worth wiring into production yet.
