# Returns by weekday and hour: volatility has a clock, drift does not

Harness: [`research/harness/calendar_returns.py`](../harness/calendar_returns.py). Lab run 2026-09-30
(`logs/calendar_returns_*.log`).

## The question

How are returns distributed by day of the week and hour of the day, and does any of it persist out
of sample or trade? The distribution here means mean, volatility, skew, tails and up-share, not only
the mean. The coverage is 168 weekday x hour buckets per family, for every family the lab holds.

Earlier studies covered pieces of this:

- [`fxtod.md`](fxtod.md) found that Ranaldo's home-hours depreciation fails, and that the FX hours
  which persist are the 20-23 UTC rollover.
- [`rollover.md`](rollover.md), [`vetoes.md`](vetoes.md), [`fridayflag.md`](fridayflag.md) and
  [`gaptrade.md`](gaptrade.md) cover the rollover, the Sunday open and the weekend gap.

This study is the full picture.

## Method

**Data.** seqlab 1h bars from 2019 (crypto and Deriv from late 2020):

| family | series | hourly bars |
|---|---|---|
| FX | 15 pairs | 718,352 |
| metals | XAU, XAG | 90,704 |
| crypto | BTC, ETH, SOL | 143,136 |
| Deriv Volatility | 5 indices | 249,995 |
| Deriv Boom/Crash | 4 indices | 199,996 |
| Deriv Jump | 5 indices | 241,695 |
| Deriv Step | 2 indices | 71,395 |
| Deriv Range Break | 2 indices | 99,996 |

There are no equity indices in the store. Deriv is treated as a market, not a control.

**Controls.** Walks we generate from iid Student-t(3) hourly moves: one set on the FX calendar and
one set running 24/7.

**The move.** Each bar's move is r = log(close/open), the hour's own move, so a weekend gap is not
counted in Monday's first hour. It is expressed in bps, and as y = r / sigma in volatility units,
where sigma is the production unit (the EWMA of true range, alpha 1/14) as of the previous bar.

**Buckets.** UTC weekday x hour. For FX and metals there is also a New York local version, so
daylight saving does not blur the rollover across two UTC hours.

**Out-of-sample checks.** The split is 60/40 by time, with standard errors clustered by day.

- Drift is screened with Benjamini-Hochberg across the buckets at q = 0.05. A bucket counts only if
  it also holds its sign with p < 0.05 in the verification period.
- The volatility profile from the discovery period is tested as a multiplier on sigma for
  forecasting the next hour's |r|.
- A trade was pre-registered: go long the 5 best and short the 5 worst drift buckets, net of
  COST_V.

**Pass bars, set before the run:**

- **drift:** survives the multiple-testing screen and holds its sign out of sample;
- **trade:** net positive with t ≥ 3 in both halves of the verification period, and the walks do
  not pass;
- **volatility profile:** relative MSE below 0.97 in both halves.

## Results

### Volatility has a strong, stable clock on the markets people trade

The volatility ratio is a bucket's mean |y| divided by its family's mean.

| family | ANOVA F on \|y\| across buckets (1.0 = no structure) | vol-profile corr, discovery vs verification | loudest hours (vol ratio) | quietest hours |
|---|---|---|---|---|
| FX | **511.8** | **+0.96** | Fri 14h 1.63x, Thu 12-13h 1.59x (London/NY overlap); 07-08h 1.3-1.5x (London open) | Fri 19-21h 0.59-0.61x; 19-23h every day 0.6-0.7x; 03-05h 0.62-0.9x |
| metals | **100.5** | **+0.94** | 13h UTC 1.97-2.08x every weekday (US data, COMEX) | Fri 20-21h 0.43-0.50x |
| crypto | **44.0** | **+0.86** | Tue 14h 1.84x, Fri 14h 1.69x (US hours); Sun 22h-Mon 00h 1.68-1.71x | Saturday 02-09h 0.60-0.66x |
| Deriv Volatility | 1.12 | +0.18 | none beyond 1.07x | none below 0.93x |
| Deriv Boom/Crash | 0.94 | -0.06 | (1.07x) | (0.92x) |
| Deriv Jump | 1.05 | +0.06 | (1.04x) | (0.93x) |
| Deriv Step | 1.05 | +0.02 | (1.08x) | (0.91x) |
| Deriv Range Break | 1.11 | +0.06 | (1.16x) | (0.83x) |
| walks, FX calendar | 1.01 | +0.08 | (1.07x) | (0.94x) |
| walks, 24/7 | 0.90 | -0.10 | (1.08x) | (0.92x) |

On FX, the New York clock sharpens the profile. The loudest buckets are Thu and Fri 08h New York at
1.76-1.78x, and the quietest are 15-17h New York at 0.57-0.61x.

In crypto, the weekend is quieter: 0.89x weekdays, and Saturday is 0.78x.

**Does the profile improve the production volatility forecast?** Relative MSE of sigma x profile
against sigma alone, for the next hour's |r|:

| family | UTC, halves | New York, halves | pass (< 0.97 in both) |
|---|---|---|---|
| FX | 0.945 / 0.954 | **0.937 / 0.948** | **yes** |
| crypto | 0.957 / 0.958 | - | **yes** |
| metals | 0.870 / 1.007 | 0.869 / 0.996 | no: the second half has no gain |
| every Deriv family | 1.000-1.004 | - | no |
| walks | 1.000-1.001 | 1.000-1.001 | no, as designed |

### Drift has no clock except the rollover's quote artefact

| family | buckets surviving BH on discovery | of those, holding in verification | discovery vs verification drift-profile corr |
|---|---|---|---|
| FX (UTC) | 17 | **17** | +0.86 |
| FX (New York) | 15 | 14 | +0.88 |
| metals (UTC) | 18 | 11 | +0.34 |
| crypto | 0 | 0 | +0.11 |
| every Deriv family | 0 | 0 | -0.13 to +0.05 |
| walks | 0 | 0 | -0.12 to +0.18 |

**All 17 FX survivors are the rollover and the Sunday open.** Each weekday dips at 20h UTC (−9.7
to −13.4 hundredths of a vol unit, t −9 to −12) and at Fri 21h. It then recovers at 22-23h (+4 to
+21, t +3.7 to +13) and on Sunday 21-23h (+10 to +40, t up to +20). Outside 19-23 UTC no FX
hour survives. This is the bid-based quote dipping as the spread widens at 17:00 New York and
recovering as it narrows (`rollover.md`), not a price anyone can trade. The metals survivors are the
same window.

**Weekdays.** The summed day in vol units, discovery / verification:

- **FX:** Sunday reads **+0.39 / +0.72 (t +18 / +25)** and Monday +0.29 / +0.34 (t +4.3 / +4.0).
  Both are the same artefact: the reopening spread normalising on bid bars, and Monday's 22-23h
  recovery. Friday's −0.18 (t −2.3) does not hold (−0.05).
- **Metals, crypto, Deriv:** no weekday replicates. Crypto's weekend reads +0.15 (t +1.3) against
  weekdays' −0.04. Deriv's largest is Step's weekend at −0.30 (t −2.7), and its halves disagree.

### The pre-registered trade loses everywhere it is honest

Net per trade in vol units, verification period, t clustered by day:

| family | net per trade | halves | verdict |
|---|---|---|---|
| FX UTC (short 20-21h, long 22-23h) | −0.054 (t −6.5) | −0.104 / −0.002 | fails |
| FX New York (short 16h, long 18h) | −0.039 (t −5.6) | −0.090 / +0.013 | fails |
| metals UTC | +0.049 (t +3.5) | +0.076 / +0.020 (t +1.0) | fails the second half |
| metals New York | +0.066 (t +6.3) | +0.106 / +0.025 (t +1.6) | fails the second half |
| crypto | −0.157 (t −7.3) | −0.143 / −0.172 | fails |
| Deriv (each family) | −0.028 to −0.070 | all negative | fails |
| walks | −0.033 to −0.050 | all negative | the cost, as expected |

The metals rows are charged normal-hours costs. The rollover's real spread is several times wider
(`rollover.md`: 15.4x the median at 21:00 UTC on the broker's quotes), which is where this trade
sits.

### The distribution around the clock

- **FX skew and tails are also a rollover story.** Skew runs from −7.7 to +2.9 by bucket, and the
  most negative is Wed 22h. Excess kurtosis has a median of 5.0 and a maximum of 181, at the
  rollover. The up-share runs from 37% to 69%, and its extremes are the rollover buckets.
- **Metals** show the same pattern: skew as low as −10.7 at Sun 22h, and kurtosis up to 156.
- **Crypto:** skew −3.2 to +3.4, kurtosis median 5.9, up-share 42-59%, with no persistent drift.
- **Deriv's shapes match their published laws and are the same at every hour:**
  - Volatility is Gaussian (kurtosis 0.0, skew ±0.18);
  - Jump has kurtosis 0.2;
  - Boom/Crash has kurtosis 0.6;
  - Step has kurtosis 0.0;
  - Range Break has kurtosis 6.2, from its breaks.
- **Tail rates** above 3 sd are 0.29% (Volatility) to 2.13% (Range Break), and they are flat by
  hour.

## What this means

- **Volatility has a clock, and it is stable.** FX, metals and crypto have strong hour-of-week
  volatility profiles (F 44-512) that repeat out of sample (corr 0.86-0.96). The quiet hours are
  about 0.6x the average and the loud hours 1.6-2x. For FX and crypto the profile improves the
  production volatility unit's next-hour forecast by about 5% MSE in both halves.
- **Drift has no clock.** Outside the FX and metals rollover and Sunday open, no weekday or hour
  bucket survives multiple-testing correction and replicates, in any family. The survivors inside
  the rollover are a bid-quote artefact, and trading them loses once costs are paid.
- **Deriv has no calendar at all.** Volatility F is 0.94-1.12, the profile correlation is about 0,
  there is no drift, and there is no weekday effect. That matches its published time-invariant
  generators on a second measure, and it confirms Deriv as a market that simply has no clock.
- **The weekday "effects" are artefacts too.** FX's large Sunday and Monday gains are the
  reopening and the rollover recovery on bid bars. Crypto's weekend is quieter, not different in
  drift.

## For production

1. **Candidate: an hour-of-week volatility multiplier for FX (New York clock) and crypto.** Scale
   the production volatility unit by the bucket's ratio from a trailing year, re-estimated
   periodically. Out of sample it cuts the next-hour |r| forecast error by about 5-6%, which is what
   the envelope and stop sizing read. It needs its own build and test through the envelope
   (conformal) before it replaces anything. It is not for metals (the second half shows no gain) or
   Deriv (no structure).
2. **Safe to ship: a card line** such as "this hour is historically 1.6x average volatility" for
   FX, metals and crypto. It is descriptive, and the profile repeats (corr 0.94-0.96).
3. **No new time vetoes and no hour or weekday trades.** The only drift structure is the rollover
   and Sunday open, which production already vetoes for FX (`vetoes.md`, New York 16:00-18:59 and
   the Sunday open). Metals show the same quote artefact in the same window; `vetoes.md` found
   metals' outcomes flat there, so nothing changes.
4. **Deriv:** nothing calendar-based applies.
