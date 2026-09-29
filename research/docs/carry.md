# Carry and safe haven: the broker keeps the carry, and the havens move with the shock, not after it

Harness: [`research/harness/carry.py`](../harness/carry.py). Lab run 2026-09-29.

## The question

- **Carry.** Does the classic FX carry trade pay this desk after spread and the broker's own
  financing? The trade is long the high-yielding currency against the low-yielding one, and it is
  known for crashing in risk-off.
- **Safe haven.** Do JPY, CHF, gold and the dollar rise when equities fall? And if they do, do they
  move *after* the equity shock, early enough to trade?

## Data and method

- **Rates.** FRED's OECD 3-month interbank rates, `IR3TIB01{cc}M156N`, for USD, EUR, GBP, JPY, CHF,
  AUD, NZD and CAD. They are monthly averages, so each is used only from the first day of the month
  after next, allowing for publication lag and ruling out look-ahead. Coverage runs to 2026-08
  except EUR and GBP (2026-01), which are carried forward. Policy-rate series
  (`IRSTCI01*`, `IRSTCB01*`) stop in 2023-24 for several currencies, which is why the interbank
  family was used.
- **The broker's financing.** MT5's `swap_long` / `swap_short` per symbol, read through the
  bridge. The bridge serves today's swap only, so today's **markup** (the interbank differential
  minus the broker's annualised swap, averaged over the two sides) is charged over the whole
  history as a haircut on both sides. The broker's current swap was used; its historical swaps are
  not available.
- **Prices.** The lab's daily FX bars for 14 pairs, from 2002-06 (the JPY series' start) to
  2026-09.
- **Cost.** COST_V × each pair's 5-minute volatility over its last year: 0.8-1.9 bps a round trip.
  The broker's spread snapshot (3-27 bps) was taken just after the 17:00 New York rollover, when
  spreads are wide ([`rollover.md`](rollover.md)), so it is reported but not used.
- **Risk-off.** An S&P 500 daily return (Yahoo `^GSPC`) below -2 sd of the prior 250 days: 287 days
  since 2002. Intraday, the bridge's `US SP 500` CFD bar below -2 sd of the prior 500 bars: 481
  shock bars at 1h (2024-01 to 2026-09) and 1,388 at 15m (2024-08 to 2026-09).
- **Controls.** 500 random monthly rankings with the same structure and costs; walks we generate
  (each pair's returns replaced by iid Student-t(3) at its own sd, with the same carry and costs);
  placebo random days and bars.
- **Pre-registered bars.**
  - Carry pays if the cross-sectional portfolio's net Sharpe exceeds 0.3 in both halves and beats
    the 95th percentile of random rankings.
  - A haven lead-lag is tradeable if the next-bar haven return, net of cost, is positive with t >= 3
    in both halves and beats placebo bars.

## Results

### The broker's financing takes most of the differential

The markup is the gap between the interbank differential and what the broker pays or charges, per
side, annualised:

| pair | differential (base - quote) | broker long / short | markup per side |
|---|---|---|---|
| AUDJPY | +3.02% | +3.21% / -5.61% | 1.20% |
| USDCHF | +3.86% | +3.09% / -7.17% | 2.04% |
| USDJPY | +2.36% | +2.35% / -5.19% | 1.42% |
| GBPJPY | +2.25% | +2.24% / -5.01% | 1.38% |
| EURUSD | -1.79% | -3.59% / +0.84% | 1.38% |
| NZDUSD | -0.97% | -4.03% / -1.61% | 2.82% |
| all 14 | | | **0.74-2.82%**, median 1.38% |

- **The receiving side is paid about the full differential or a little less,** and the paying side
  is charged about the differential plus 2-3 points. A carry position keeps roughly the
  differential minus 1.4%.
- **On pairs whose differential is small, both sides pay.** GBPUSD charges 1.47% long and 1.12%
  short, and NZDUSD charges 4.03% long and 1.61% short.

### Carry: no premium left, and the crash is intact

Cross-sectional carry is long the top 3 differentials and short the bottom 3, rebalanced monthly,
net of cost and markup, 2002-2026:

| | annual | vol | Sharpe (halves) | max DD | monthly skew | worst month | on risk-off days | corr S&P |
|---|---|---|---|---|---|---|---|---|
| **cross-sectional, net** | +0.39% | 6.23% | +0.06 (+0.19 / -0.12) | -42.7% | -1.31 | -12.7% | **-58.2 bps** | **+0.45** |
| its price component | -0.30% | 6.24% | -0.05 | -45.5% | -1.34 | -12.8% | -58.7 bps | +0.45 |
| its carry less markup | +0.70% | 0.05% | - | - | - | - | +0.2 bps | -0.01 |
| time-series, net | -0.23% | 4.27% | -0.05 (+0.01 / -0.17) | -39.3% | -1.42 | -9.0% | -39.0 bps | +0.43 |
| walks, same carry and costs | +0.23% | 3.89% | +0.06 (+0.01 / +0.12) | -19.0% | +0.01 | -3.7% | -1.6 bps | -0.00 |

Random monthly rankings have a median Sharpe of -0.36 and a 95th percentile of -0.10. Carry's
+0.06 beats 99.6% of them.

- **The pre-registered test fails.** Net Sharpe is +0.06 against a bar of 0.3, and the second half
  is negative (-0.12).
- **What is left is the accrual:** +0.70% a year after the markup. The price component loses it
  back (-0.30% a year), and our walks with the same accrual earn about the same net (+0.23%). The
  differential is being paid; the currencies are not rewarding the risk.
- **Beating random rankings is not a premium.** A random ranking pays the markup on both sides and
  a negative differential half the time, so its median is -0.36. Carry "beats" that by not paying
  the wrong way.
- **The crash is fully there.**
  - It loses 58 bps on the average S&P risk-off day.
  - Its correlation with the S&P is +0.45.
  - Monthly skew is -1.31, the worst month -12.7% and the maximum drawdown -42.7%.

  The walks, with the same carry, have none of it (skew +0.01, -1.6 bps on risk-off days). Carry
  is a short-volatility, long-equity position that the broker's markup has left unpaid.
- **Per pair,** time-series carry's net Sharpe runs -0.28 (EURGBP) to +0.26 (AUDJPY). Only AUDJPY
  and GBPJPY are positive in both halves, at +0.34 / +0.16 and +0.06 / +0.15, which is nowhere near
  significant.

### Safe haven: real, same-day, and gone by the next bar

Daily, the mean haven return on S&P risk-off days, in bps, with a 95% CI, halves, and the share of
placebo random days reaching it (p):

| haven | n | same day | halves | p | next day | halves | p |
|---|---|---|---|---|---|---|---|
| **JPY** (USDJPY inverted) | 287 | **+46.6** [+36.5, +56.5] | +10.1 / +55.3 | 0.000 | -10.2 [-18.6, -1.5] | +0.1 / -12.6 | 0.998 |
| **CHF** (USDCHF inverted) | 287 | **+16.7** [+7.0, +26.9] | +13.3 / +17.5 | 0.000 | -8.3 [-16.6, +0.5] | +2.1 / -10.8 | 0.994 |
| gold (XAUUSD) | 137 | -4.0 [-34.3, +23.4] | +20.6 / -26.5 | 0.790 | -4.8 [-26.6, +16.2] | -8.7 / -1.3 | 0.796 |
| dollar (DXY) | 287 | +0.6 [-7.9, +9.2] | -16.9 / +13.0 | 0.426 | +11.0 [+4.1, +18.1] | +0.9 / +18.1 | 0.000 |

Intraday, on the S&P CFD's shock bars, the haven's return on the same bar and the next, net of
cost (t clustered by day):

| haven | 1h same bar | 1h next bar, net (t) | 15m same bar | 15m next bar, net (t) |
|---|---|---|---|---|
| JPY | +3.45 | -0.60 (-0.8) | +1.51 | -1.33 (-5.8) |
| CHF | +0.38 | -0.90 (-1.6) | -0.55 | -1.49 (-7.9) |
| gold | **-18.04** | -3.16 (-1.9) | -9.19 | -1.69 (-2.6) |
| dollar (DXYUSD) | +5.18 | -1.17 (-1.8) | +2.66 | -1.08 (-5.3) |

- **JPY and CHF are havens on the day,** in both halves: +47 and +17 bps on an S&P -2 sd day, far
  outside placebo days. JPY's effect is much larger in the second half (+55 against +10).
- **They give some of it back the next day** (-10 and -8 bps). The move is a same-day repricing,
  not the start of a trend.
- **Intraday there is no lead-lag.** The haven moves in the same bar as the shock (JPY +3.5 bps at
  1h, the dollar +5.2). On the next bar gross returns are about zero, and net of cost they are
  negative at every horizon. **The pre-registered bar fails for every haven.**
- **Gold is not a haven here; intraday it sells off with equities,** by 18 bps on the 1h shock
  bar and 9 bps at 15m. On the day it is flat, with a very wide interval.
- **The dollar's next-day +11 bps** is outside placebo but sits in one half only (+0.9 / +18.1),
  so it fails the both-halves rule.
- **The desk's own drawdowns could not be tested.** The journal's 14 days of trade P&L
  (2026-08-26 to 09-10) contain no S&P risk-off day.

### Deriv: no rate, no risk link, but a large swap

- **Risk-off days.** Deriv's indices show no reliable risk-off response:
  - Volatility 75: -35.8 bps [-117.6, +45.1];
  - Crash 1000: +6.3 [-16.5, +29.6];
  - Step: +3.5 [-3.4, +10.8].

  Boom 1000's same-day +39.0 bps (p 0.008) and Jump 50's next-day -105.6 are two of ten Deriv tests
  on 46-66 days, and neither survives a correction for ten tries (0.005). They are treated as
  chance, as the generator's construction predicts.
- **The broker's swap on Deriv** is an annual interest rate on the price (MT5 swap mode 5), charged
  on *both* sides:

  | index | annual rate, both sides | per night |
  |---|---|---|
  | Boom 1000 | 36% | about 9.9 bps |
  | Crash 1000 | 18% | about 4.9 bps |
  | Volatility 75 | 7.5% | about 2.1 bps |
  | Jump 50 | 7% | about 1.9 bps |
  | Step | 1% | about 0.3 bps |

  For comparison, FX's markup is 1-3% a year per side, under 1 bp a night (the median 1.4% is
  about 0.4 bps). Gold's
  swap is -45 points long and +20 points short a night.

## What this means

- **Carry does not pay this desk.** After the broker's markup (median 1.4% per side, per year),
  cross-sectional carry nets +0.4% a year at a Sharpe of 0.06. That is negative in the second half
  and carries its full crash: -58 bps on an S&P risk-off day, correlation +0.45 with the S&P, and a
  -43% drawdown. The differential is paid, and the markup and the crashes take it back.
- **High-yield FX longs are equity risk.** A long in AUDJPY, GBPJPY or USDJPY, the pairs carry
  would hold, loses with the S&P. The desk should know that when it is long those pairs into a
  risk-off day, whatever the reason for the trade.
- **The havens are real but already priced when they are visible.** JPY and CHF firm on the day of
  an equity shock and partly reverse the next day. Intraday they move in the same bar as the S&P,
  so there is nothing to trade after it. Gold falls with equities intraday.
- **Deriv has no carry and no risk-off link, but holding it overnight is expensive.** Boom 1000
  costs about 10 bps a night whichever side you hold, 36% a year. That matters to any hold longer
  than a day, and more than it would on FX.

## For production

1. **No carry trade and no carry tilt in sizing.** Nothing passes.
2. **A swap-aware cost for holds that cross the rollover,** Deriv first. Charge the broker's
   `swap_long` / `swap_short` (in its swap mode) against a trade's expected edge whenever its
   hold can cross 17:00 New York. On Boom 1000 that is about 10 bps a night on either side, which
   can exceed a small edge; on FX it is negligible. First check whether the trading service already
   accounts for the swap (`research/harness/spread_cost.py` measured it for one study).
3. **Optionally, a risk-off note on FX cards.** On an S&P -2 sd day, JPY and CHF firm (+47 / +17
   bps) and carry longs fall (-58 bps). This is context for a reader who is long a high-yielder, not
   a signal. Nothing is tradeable after the shock.
4. **Re-run the hedge question later:** once the journal holds trades across a few S&P risk-off
   days, check whether a JPY or CHF position would have cut the desk's drawdowns on them.
