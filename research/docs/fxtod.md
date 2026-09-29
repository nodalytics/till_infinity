# Do currencies weaken during their own working hours? FX time-of-day drift, out of sample

Harness: [`research/harness/fxtod.py`](../harness/fxtod.py). Lab run 2026-09-29.

## The question

Ranaldo (2009, "Segmentation and time-of-day patterns in foreign exchange markets") found that a
currency tends to depreciate during its home market's working hours and appreciate during foreign
hours. He attributed it to domestic firms' home-currency flow and to order flow segmented by time
zone. If it held out of sample, it would be a small drift that a session-aware sizer or entry timer
could lean on.

## Method

The pattern was fixed before any run. Home hours in UTC, on standard time:

| currency | home hours (UTC) |
|---|---|
| JPY | 00–07 |
| AUD, NZD | 22–06 |
| EUR, CHF, GBP | 07–15 |
| USD, CAD | 13–21 |

For a pair BASE/QUOTE in hour h, the signal s is:

- **−1** when BASE is at home and QUOTE is not, so BASE weakens and the pair falls;
- **+1** when QUOTE is at home and BASE is not;
- **0** otherwise.

Pairs whose currencies share a home block (EURCHF, EURGBP, USDCAD) never get a signal. The return
is the hour's log return over the slow causal hourly volatility, which is known before the hour.

The study uses 1h bars since 2015 and 14 FX pairs (690,661 hours), split 60/40 by time. Four listed
pairs have no bars on the lab. It scores four things:

- the pooled mean of s × return, with t-stats clustered by calendar day, because pairs share
  currencies;
- the same split by which currency produced the signal;
- the persistence of each pair's whole 24-hour return profile between the halves, Ranaldo's shape
  or not;
- a session trade that holds s through each block and pays a round trip (0.8 M5-vol units, scaled to
  hourly).

The control is FX-calendar walks we generate (iid Student-t(3) hourly moves), given pair names so
the same signal applies. Deriv indices and crypto have no home currency, so they are outside this
question rather than controls.

**Pre-registered.** The pattern holds only if the pooled s × return is positive with clustered
t ≥ 3 in both halves, and the control's |t| < 2. It is worth trading only if the net session trade
is positive in verification with t ≥ 2.

## Results

| s × return, mean in hourly-volatility units (clustered t) | discovery | verification |
|---|---|---|
| **FX pooled** | −0.0073 (t −1.4, n 182,539) | −0.0082 (t −1.2, n 121,676) |
| walks pooled | −0.0025 (t −0.7) | +0.0049 (t +1.2) |
| AUDJPY | −0.0687 (t −4.1) | −0.1296 (t −5.9) |
| NZDUSD | −0.0325 (t −4.0) | −0.0162 (t −1.6) |
| AUDUSD | −0.0254 (t −3.1) | −0.0194 (t −1.8) |
| CHFJPY | −0.0189 (t −2.1) | −0.0066 (t −0.6) |
| EURAUD | +0.0148 (t +1.8) | +0.0192 (t +1.8) |
| USDCHF | +0.0055 (t +0.5) | +0.0167 (t +1.3) |
| EURUSD / GBPUSD / USDJPY / EURJPY / GBPJPY | within ±0.012, all \|t\| ≤ 1.1 | within ±0.013, all \|t\| ≤ 1.1 |

By the currency whose home hours produced the signal:

| currency | discovery | verification |
|---|---|---|
| USD | −0.0148 (t −1.4) | −0.0068 (t −0.5) |
| EUR | +0.0067 (t +0.6) | −0.0021 (t −0.2) |
| GBP | +0.0114 (t +0.8) | −0.0027 (t −0.2) |
| CHF | −0.0209 (t −1.6) | +0.0015 (t +0.1) |
| JPY | +0.0024 (t +0.2) | −0.0131 (t −0.9) |
| AUD | −0.0125 (t −1.2) | −0.0166 (t −1.3) |
| NZD | −0.0399 (t −3.7) | −0.0233 (t −1.7) |

The session trade, per pair-day:

| half | gross | net of costs |
|---|---|---|
| discovery | −0.0637 (t −1.4) | −0.4068 (t −9.2) |
| verification | −0.0714 (t −1.2) | −0.4133 (t −7.1) |

The walks' net is −0.3774 and −0.3051 (the cost alone).

The correlation of each pair's 24-hour mean-return profile between discovery and verification:

- **FX:** +0.24 (USDJPY) to +0.90 (EURCHF). 11 of 14 pairs are above +0.5.
- **Walks:** −0.10 to +0.41.

In every FX pair, discovery's three largest hours are **20–23 UTC**. Most keep their sign and size
out of sample. For example:

| pair | hour (UTC) | discovery | verification |
|---|---|---|---|
| EURCHF | 22 | +0.431 | +0.553 |
| CHFJPY | 22 | +0.354 | +0.463 |
| USDCHF | 22 | +0.253 | +0.410 |
| AUDJPY | 22 | +0.116 | +0.275 |

## What this means

- **Ranaldo's home-hours depreciation does not hold here.** The pooled effect is the wrong sign
  (−0.0073, −0.0082) and not significant (t −1.4, −1.2), where the bar was positive with t ≥ 3. No
  currency carries it in both halves. The control behaves (t −0.7, +1.2), so the harness is sound.
  Twenty-odd years after the paper's sample, on a retail broker's bars, the pattern is gone.
- **The significant pair-level readings are the opposite of Ranaldo, and they come from one
  window.** AUDJPY (t −4.1, −5.9), NZDUSD and AUDUSD are negative because their signal hours include
  22–23 UTC, the AUD/NZD home hours. In exactly those hours, these pairs rise, in both halves.
- **A strong, persistent hour pattern exists, but it sits at 20–23 UTC.** That is the New York close
  and the broker's daily rollover, when liquidity is thinnest and spreads widen most. Profiles
  correlate +0.24 to +0.90 between halves against at most +0.41 on the walks, and the largest hours
  keep their sign.
  - The likelier cause is the quote, not flow: bars around the rollover close on a widened or
    one-sided spread, and the next hours revert. That is the same shared-noisy-price mechanism as
    the late-Friday reversal in [`fridayflag.md`](fridayflag.md).
  - It cannot be traded at the price it is measured at. The session trade loses −0.41 of a
    volatility per pair-day net (t −7.1), and even its gross is negative.

## For production

1. **Nothing to trade.** The pre-registered pattern fails, and the session trade fails its cost bar
   by a wide margin.
2. **A caution worth checking in production.** Anything the desk scores on bar closes between 20:00
   and 23:00 UTC may be reading rollover quote artefacts, not moves: level touches, envelope
   outcomes, strategy fills. Check how often production's signals and fills land in that window, and
   whether their outcomes differ there. If they do, the fix is a rollover-hours exclusion or a
   spread gate, not a signal.
