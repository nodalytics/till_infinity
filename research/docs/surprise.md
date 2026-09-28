# The gap between expectations and reality moves currencies, and it is fully priced within three minutes

Measured 2026-09-28 on the lab with [`surprise.py`](../harness/surprise.py) (`PART=fetch`, the
study, and `PART=fast`). The calendar is TradingView's (the provider `news/calendar.py` already
polls): 51,354 releases for the G10 and China from January 2022 to September 2026. Prices are the
lab's broker bars: 15 FX pairs, XAU and XAG, at 15m from September 2024 and at 3m from April 2026.

## The claim

From "How the $7 Trillion Currency Market ACTUALLY Works" (Lock Stock Finance; notes in
`.secrets/videos/notes.md`):

> If everybody already expects the Fed to raise rates, the dollar might not move much when it
> happens because the market has already priced it in. If inflation comes in higher than expected
> ... the dollar could strengthen quickly. **Markets move based on the gap between expectations
> and reality.**

## How it was measured

- **Surprise** = actual - forecast, divided by the standard deviation of that indicator's *own
  earlier* surprises (at least six, strictly before the release). The result is a z-score that is
  comparable across 354 indicators and uses nothing from the future. It is signed so that + is good
  for the currency; unemployment, jobless claims and claimant counts are inverted. Energy
  inventories are dropped.
- **Releases for one currency at one minute are one event.** US CPI's headline, core, month and
  year are one print; their z is averaged, weighted by importance.
- **The reaction** is averaged over every pair carrying that currency: +1 as base, -1 as quote,
  gold and silver as USD-quoted. It is measured in units of each pair's trailing mean |15m move|,
  so one release is one observation however many pairs it touches. That gives 3,303 currency-events
  on 15m bars.
- **The control** is the same clock time on the day before, where there is no release.

**Is `actual` the first print or a revised one?** Revisions rewritten in place were the look-ahead
hazard that `news-models.md` warned about. In 44.8% of releases the stored `actual` differs from
what the next release reports as `previous`. So the stored value is the first print as released,
and the revision shows up only in the next row. The forecast is the provider's pre-release
forecast; whether it matches the market consensus to the decimal was not verified.

## 1. The surprise moves the release bar, as claimed

Spearman correlation of the surprise with the currency's aligned move in the first 15 minutes
(the two halves of the two years in brackets):

| | events | release bar | placebo, same time the day before | \|z\| >= 1: sign agrees | aligned mean |
| --- | ---: | --- | --- | ---: | ---: |
| all | 3,303 | **+0.173** (+0.200 / +0.147) | +0.024 | 59.5% | +0.62 |
| medium and high | 2,525 | **+0.207** (+0.231 / +0.183) | +0.013 | 61.7% | +0.78 |
| high only | 840 | **+0.322** (+0.332 / +0.315) | +0.061 | 65.2% | +1.44 |

It is stable across both halves and flat on the placebo. By category, the video's hierarchy holds:
**GDP +0.469, inflation (prices) +0.410 and labour +0.361**, then business surveys +0.213, consumer
+0.141 and housing +0.121. Trade (-0.007), energy (+0.021) and money supply / credit (+0.028) do not
move the currency.

**"The expected part does not move" is only half right.** Mean |first 15m| by the size of the
surprise (medium and high), against the placebo:

| \|z\| | n | \|move\| | aligned move | placebo \|move\| |
| --- | ---: | ---: | ---: | ---: |
| 0 - 0.25 | 834 | 1.86 | +0.19 | 1.14 |
| 0.25 - 0.75 | 976 | 1.58 | +0.65 | 1.16 |
| 0.75 - 1.5 | 523 | 1.65 | +0.83 | 0.99 |
| 1.5 - 3 | 175 | 1.74 | +0.73 | 1.19 |
| 3+ | 17 | 2.04 | +1.40 | 0.80 |

A release with essentially no surprise still moves the currency 1.6 times as much as a normal
quarter-hour; that is the volatility spike [`news-volatility.md`](news-volatility.md) already
measured and shipped. **What the surprise decides is the direction, not the size.** The aligned
move grows from +0.19 to +0.83 while the size barely changes.

## 2. Before the release: the high-importance prints are partly anticipated

Over the 4 hours before a high-importance release, the currency already drifts toward the coming
surprise: rho **+0.122** (+0.085 / +0.161 in the halves), with the sign agreeing 60.7% of the time
when |z| >= 1. For all releases the figure is +0.038. The likely source is earlier related
prints: German state CPIs before German CPI, which comes before the euro-area flash, and ADP before
payrolls. This was not separated here. It cannot be traded before the release, because the
surprise is not known yet.

## 3. After the release: nothing is left

From the close of the release bar, aligned with the surprise (medium and high):

| | rho | \|z\| >= 1: sign agrees | aligned mean | trade net of 2x spread |
| --- | --- | ---: | ---: | --- |
| next 1h | -0.003 | 45.2% | -0.15 | -1.07 (shuffled-sign p 0.85) |
| next 4h | -0.018 | 46.5% | -0.35 | -1.27 (p 0.92) |
| next 1d | +0.005 | 51.0% | +1.29 | +0.36 (p 0.008) |

- **At 1h and 4h there is no continuation.** If anything there is slight give-back: high-importance
  releases agree with the surprise only 36-38% of the time over the next hours, but that reverses
  between halves (+0.03 in the first, -0.15 in the second).
- **The one-day cell is not a result.** Its p is 0.008, but its halves are +0.19 and +2.19, its rank
  correlation is +0.005, and the |z| >= 2 version is negative net (-0.20). It is one cell of 18
  looked at (3 horizons x 2 thresholds x 3 importance tiers), and its standard error is 0.52 against a mean
  of 1.29.

**What a bot could catch.** On 3m bars (516 medium/high events since April 2026), with the move in
units of the trailing |3m move|:

| window | rho | \|z\| >= 1 aligned (n = 112) | sign agrees |
| --- | --- | --- | ---: |
| first 3 minutes | **+0.231** | **+1.01 +- 0.43** | 56.2% |
| 3 - 15 min | +0.033 | -0.05 +- 0.27 | 50.0% |
| 3 - 60 min | -0.025 | +0.04 +- 0.56 | 49.1% |
| 15 - 60 min | -0.056 | +0.09 +- 0.52 | 46.4% |

(spread in these units: 0.8 normally, about 1.6 at a release)

**The whole reaction happens inside the first three minutes.** A desk that reads bars, enters on
the next one and pays a news-time spread starts after the move is over.

## What this settles

- **The claim is true, and it describes the market rather than offering a trade.** The surprise
  sets the release-bar direction (rho +0.21 to +0.32; inflation, GDP and labour most), and a
  zero-surprise print still spikes volatility.
- **It is priced within three minutes.** From three minutes after the print, the surprise predicts
  nothing at 15m, 1h or 4h. The one-day cell does not survive its own halves.
- **For production:** nothing new to build. Release *timing* is already a volatility input
  (`structures/context/releases.py`). The *surprise* would only be tradeable at sub-minute latency
  into a widened spread, which is not this desk's game.
