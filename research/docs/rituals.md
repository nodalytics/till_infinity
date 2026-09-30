# Market rituals: the market is louder on the day, not quieter or leaning before it

Harness: [`research/harness/rituals.py`](../harness/rituals.py). Lab run 2026-09-30,
`logs/rituals.log`, results in `data/rituals/results.csv`.

## The question

Anthropology's word for a recurring, socially coordinated event is a ritual. Markets have plenty,
and participants anticipate them together:
- options expiry and triple witching;
- index reviews;
- month- and quarter-end rebalancing and the 4pm London fix;
- central-bank decisions and payrolls;
- crypto futures expiry and funding.

The question is whether that shared anticipation shows in the bars **before**, **on** and **after**
the day, beyond what the weekday clock already explains. Three predictions:
- does volatility compress into a ritual and expand after it?
- is there drift that anticipation creates, such as the pre-FOMC drift (Lucca & Moench 2015) or the
  turn of the month?
- can a known ritual day improve the next day's volatility forecast?

Not repeated here:
- the weekday × hour clock ([`calendar-returns.md`](calendar-returns.md));
- release surprise drift ([`surprise.md`](surprise.md));
- the daily FX rollover ([`rollover.md`](rollover.md), [`vetoes.md`](vetoes.md));
- weekends ([`fridayflag.md`](fridayflag.md), [`gaptrade.md`](gaptrade.md)).

## Method

**Rituals.** The dates are computed, fetched or read:

| ritual | source | events |
|---|---|---|
| opex (third Friday, non-quarter months) | computed | 296 |
| witching (third Friday of Mar/Jun/Sep/Dec: triple witching and the S&P rebalance) | computed | 148 |
| MSCI reviews (last business day of Feb/May/Aug/Nov) | computed | 148 |
| Russell reconstitution (last Friday of June) | computed | 37 |
| month-end, quarter-end, turn of month | computed | 296 / 148 / 444 |
| crypto quarterly expiry (last Friday of Mar/Jun/Sep/Dec) | computed | 148 |
| FOMC scheduled decisions | federalreserve.gov, 1994-2026 | 267 |
| ECB, BoE, BoJ, NFP | the lab's calendar, **2022 on only** | 38 / 37 / 37 / 56 |
| crypto funding (00/08/16 UTC) | Binance funding history (`data/crowding`) | hourly |

Token unlocks are untestable: there is no data for them on the lab.

**Assets.**
- **FX:** 12 pairs pooled for |y| and range; a USD proxy (the USD legs, signed as USD) for drift.
- **Metals, crypto:** XAU/XAG; BTC/ETH/SOL.
- **Stocks:** a basket of the broker's 391 US share CFDs. It starts 2025-09, so there are only 8-12
  events per ritual, and it is survivorship-biased.
- **Deriv:** Volatility and Boom/Crash, as a market with no institutions. That makes it a design
  comparison, not a null.
- **Controls:** iid Student-t(3) walks we generate, on the FX calendar and 24/7.

**Daily event study.** Each measure is y = r / σ (σ the daily EWMA true range as of the day before),
|y|, range / σ, and log volume against its 20-day mean. Each is taken **minus its weekday mean**, so
the weekly clock is not re-found as a ritual. The tests:
- **V-pre:** |y| on days −3..−1;
- **V-post:** |y| on days 0..+2;
- **R0:** the event day's range;
- **VOL0:** the event day's volume;
- **D-1, D0:** drift the day before and on the day;
- **D-tom:** turn-of-month drift, summed over days −1..+3.

p-values come from 300 placebo sets: every event shifted a random 2-8 weeks on the same weekday,
avoiding real events, so the floor is 1/301. Halves are split at each family's median date.
Benjamini-Hochberg runs across the 247 tests on markets, and the largest |z| is deflated against
the False Strategy Theorem's expected maximum ([`lopez-de-prado.md`](lopez-de-prado.md)).

**Intraday (1h, 2018 on).**
- **Pre-FOMC:** the 24 hours before 14:00 New York.
- **The fix:** the 15:00 and 16:00 London bars on month-end days against other days, with the
  weekday × London-hour clock removed.
- **Funding:** whether the move into and out of a settlement hour scales with the funding rate,
  beyond the same regression at other hours.

**Risk.** The next day's |y| forecast is the weekday profile, which on σ-normalised moves is σ × the
clock, against that profile times a per-ritual multiplier. The multipliers are fitted on the first
60% of days, and the relative MSE is taken on the last 40%. Worth production if below 0.99 in both
halves.

**Trade.** A drift test that survives BH is traded out of sample: its sign from the first 60% of
events, net of `COST_V` on the rest. It passes only with t ≥ 3 in both halves and not on the walks.

## Results

**The largest effects are on the day, and they are volatility.** The top of the deflation table is
below. The expected maximum |z| under the null for 247 tests is 2.83; the largest on our walks was
3.3.

| ritual | family | test | n | effect (vol units) | z | halves |
|---|---|---|---|---|---|---|
| FOMC | USD | R0 | 208 | +0.230 | 10.9 | +0.098 / +0.368 |
| FOMC | FX | V-post | 208 | +0.090 | 10.7 | +0.038 / +0.143 |
| month-end fix (15-16h London) | FX \|y\| | fix | 97 | +0.246 | 9.9 | +0.287 / +0.206 |
| FOMC | metals | R0 | 119 | +0.319 | 9.0 | +0.330 / +0.308 |
| BoJ | FX | R0 | 37 | +0.368 | 8.3 | 2022 on only |
| NFP | USD | R0 | 56 | +0.286 | 8.2 | 2022 on only |
| BoE | FX | R0 | 37 | +0.347 | 7.4 | 2022 on only |
| month-end | FX | VOL0 / R0 | 214 | +0.088 / +0.103 | 5.5 / 4.9 | both positive |
| turn of month | USD | R0 | 321 | +0.063 | 4.2 | +0.069 / +0.057 |
| **opex** | FX / USD / metals | R0 | 214 / 214 / 126 | **−0.076 / −0.082 / −0.133** | −3.9 / −4.2 / −3.1 | both negative |

51 of 247 market tests survive BH, and nearly all are range, volume and |y| on or just after the day.

**Anticipation barely shows.**
- **Compression before** (V-pre) survives only for quarter-end on FX and USD (−0.041 / −0.045, z
  −3.4 / −3.1, both halves) and turn of month on crypto (−0.055, z −3.1). These are small: 4-5% of
  a day's move.
- FOMC's pre-days are only a hint (USD −0.017, z −1.8; metals −0.048, z −2.4); neither survives BH.
- Before triple witching, volatility is *higher*, not lower (USD +0.058, z 3.4), and not stably
  (halves −0.018 / +0.134).
- **Monthly opex days are quieter:** the range is 8-13% of a day smaller, consistently in both
  halves. That is the one anticipation-shaped effect with a consistent sign: pinning into expiry,
  as the options literature describes.

**No drift survives.**

| test | effect | z | out-of-sample trade |
|---|---|---|---|
| **pre-FOMC**, USD, day −1, before 2012 | −0.002 | −0.8 | - |
| pre-FOMC, USD, day −1, 2015 on | +0.001 | −0.4 | - |
| pre-FOMC 24h, USD / XAU / BTC | −0.54 / +0.41 / +0.72 | −1.3 / −0.3 / +0.5 | - |
| turn of month, USD / metals / crypto | −0.114 / +0.086 / +0.110 | −2.1 / 0.7 / 0.8 | - |
| month-end fix drift, USD | −0.023 | −0.4 | - |
| FOMC day, metals (the best BH drift survivor) | +0.197 | 3.1 | net +0.224, t +1.7 (halves +1.9 / +0.7) |
| month-end, metals / crypto | −0.146 / +0.124 | −2.6 / 2.7 | t +0.7 / 0.0 |
| NFP, crypto day −1 | −0.216 | −2.3 | t +1.6 |

Lucca & Moench's pre-FOMC drift is an *equity* effect. It does not appear in the dollar, gold or
bitcoin, before 2012 or after 2015. On equities it is untestable here: the stock basket has only 9
FOMC days. No drift survivor trades: none reaches t ≥ 3, and the walks' version is within noise.

**The fix moves the market without direction.** The 4pm London fix window on month-end days is
+0.25 vol units louder across FX (z 9.9, both halves). Its USD drift is −0.02 (z −0.4). The flows are
real, but their direction is not predictable from the calendar alone. Melvin & Prins (2015) predict
it from the month's equity performance, which was not tested here.

**Crypto funding and expiry: null.** The slope of the settlement hour's move on the funding rate is
indistinguishable from the other hours' (BTC −0.010, ETH +0.006, SOL −0.014 into settlement, all
|z| < 1). SOL out of settlement reads z 2.4, but its halves flip sign. Crypto quarterly expiry moves
nothing (all |z| ≤ 1.6).

**Deriv.** Boom/Crash tick volume is *lower* on FOMC and month-end days (−3.7%, z −5.3; −3.9%,
z −3.7). No price measure moves. The generator is time-invariant, so this is a finding about the
feed's tick delivery on busy days, not about price.

**Risk: a ritual flag does not improve the daily volatility forecast enough.**

| family | relative MSE (halves) | largest multipliers |
|---|---|---|
| USD | 0.9965 / 0.9850 | FOMC 1.17, quarter-end 1.10 |
| FX | 1.0033 / 0.9862 | FOMC 1.15, month-end 1.12 |
| metals | 1.0048 / 0.9855 | **FOMC 1.64**, quarter-end 1.17 |
| crypto | 1.0074 / 1.0012 | expiry 1.24, month-end 1.24 |
| Deriv Volatility | 1.0152 / 1.0416 | - |
| walks | 1.0001 / 1.0014 | - |

No family is below 0.99 in both halves. The multipliers are large on the days themselves (gold on an
FOMC day is 1.6× its usual move), but the days are rare. Across all days the gain is under 1.5%, and
in the first half the flag slightly hurts.

## What this means

- **Rituals are volatility events on the day, not drift, and hardly anticipation.** FOMC, payrolls,
  central-bank decisions and the month-end fix are 10-35% of a day's move louder when they happen,
  in both halves and far past deflation. That is known; this measures its size on our instruments.
- **Anticipation is weak.** There is a small compression into quarter-end and a quieter opex day, the
  one consistent pre-event pattern.
- **The pre-FOMC drift is not in FX, gold or crypto,** and the equity version cannot be tested on 9
  events.
- **Nothing trades.** Every drift test that survives BH fails out of sample.
- **Deriv shows no price ritual,** as its law implies, and a tick-volume dip on busy days.
- **Caveats:**
  - ECB, BoE, BoJ and NFP dates start in 2022, so they have no first-half check;
  - the stock basket is a year long and survivorship-biased;
  - placebo p-values floor at 1/301, which is why BH is paired with the z-scores and deflation;
  - volume is the broker's tick volume.

## For production

- **No trade, and no new veto.** The existing news blackout already covers the release minutes, and
  [`vetoes.md`](vetoes.md) found it adds nothing measurable.
- **Candidate: a card line on scheduled ritual days,** e.g. "FOMC today: gold's day is usually 1.6×
  its normal range". It is descriptive and cheap, and it is true on the day. It does not pass the
  daily forecasting bar, so it should not scale the envelope or size.
- **Not recommended:** a ritual multiplier in the envelope or sizing. It fails the pre-registered
  0.99 bar in every family; the intraday envelope and the shock forecaster already see the event
  hour's volatility as it builds.
