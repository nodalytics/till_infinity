# What this research can hand to production — 2026-09-21

Written after `costs.md`, `stop-free.md`, `detectors.md` and `breakout-runs.md`. It is the
answer to a direct question: from all of it, what goes to prod?

**No signal.** Nothing cleared its own error bar and its cost line together. What follows is
corrections and guardrails, ranked by expected value, and the first one is measured, one line,
and currently wrong.

## A. `TRADING_STOP_SLIPPAGE` is 0.0 and should not be

The knob already exists in `trading/config.py` and its own docstring describes exactly what
this research measured: *"a broker stop fills through the spread and the money that leaves the
account is what a risk budget is about."* It inflates the stop distance used for sizing, so
positions come out smaller.

`TRADING_STOP_SLIPPAGE` is unset in the live environment, so it defaults to `0.0`.

Measured stop overshoot, as a share of a 1 TR stop, from 65,000 hourly bars per instrument:

| instrument | overshoot at R:R 1 |
|---|---|
| XAUUSD | **0.286** |
| EURUSD | **0.268** |
| Crash 1000 | 0.239 |
| Boom 1000 | 0.236 |
| Volatility 75 | 0.166 |

**Prod is therefore sizing every position roughly 20% too large**, and the error is worst on
gold and EURUSD rather than on the synthetics, which is the opposite of what anyone assumed.
This reduces risk rather than chasing return, which is why it is first.

Caveat on the number: the bar extreme is the *worst* price printed in the hour, so 0.24-0.29
is an upper bound and the truth is bracketed at `0.04 <= slippage <= 0.24` - see `costs.md`
for how the lower bound is derived from the price path. A value near the bottom of the bracket
is the conservative choice to ship; the bracket only narrows with tick data.

Independent corroboration: `excursion.md` recorded live losers at a p90 adverse excursion of
**1.267 R against 1.0 R stops** - overshoot of about 0.27 R from real fills, at the top of the
bracket. That reading could also come from stops being moved mid-trade, which the journal's
per-ticket history would settle and nobody has checked.

## B. Be flat at rollover

**Swap is charged at a rollover instant, not by the hour.** A 2.7-hour trade pays either
nothing or a full day - never a ninth of one. This corrects `net_edge.py`, which smeared the
charge and got the expected value right for the wrong reason.

The consequence was missed entirely: **a trade flat at rollover pays exactly zero carry.**

Measured on Boom 1000 at one bar: net improves from −0.018 to −0.005 TR while **96% of
opportunity is kept**. That is 0.013 TR a trade, about 44% of the largest gross edge this
research ever found, for almost nothing.

It matters most on the synthetics, which charge as an annual percentage of notional with
**both sides paying**: Boom 1000 at 36%/yr is 0.321 TR a day, Crash 1000 at 18% is 0.161.

**Gate before shipping.** The rollover instant is assumed 00:00 UTC and is *not confirmed*.
It needs reading off the `swap` actually charged on live tickets, which the venue adapters
already parse. Do not ship this on the assumption.

## C. Never post a limit on the side an instrument jumps towards

A resting Boom short fills only when the next bar trades up through it - which on Boom means
**it is filled exactly as a spike begins**:

| Boom 1000, h=1 | net | filled |
|---|---|---|
| maker short (the spike side) | **−0.255** | 72% |
| taker short | −0.011 | 100% |
| maker long (the grind side) | +0.002 | 96% |

The adverse selection is twenty times the spread it saved. Generalised: posting a limit on the
side an instrument jumps towards buys you the jump. Any maker logic here must be on the
grinding side only, and this should be a hard rule rather than a parameter.

## D. Do not cap upside with a fixed target on jump instruments

A limit target at 1 TR took Boom always-long from +0.002 to **−0.084** TR.

**Boom's entire positive return is its up-spikes, and a fixed target truncates exactly
those.** A bar that reaches one true range above entry may close three above it. On a jump
process, capping the upside is not a risk control, it is the removal of the edge - and it
costs far more than the slippage a limit exit avoids.

If prod uses fixed-R targets on Boom/Crash, that is actively destroying return.

## E. The character monitor — shipped

`structures-context-character.md`. The one piece of this research that became production code,
and it is a monitor rather than a signal: it alarms when an instrument's up/down jump balance
leaves its own history, which is how a synthetic's generator changing would be noticed at all.
Implemented, tested, and documented separately.

## F. Two guardrails from the negatives

**Do not implement** gaps-as-levels, chart patterns, premium/discount, zma anchors, 4h
alignment, topological features, regression channels or motif clustering. All measured at or
below the fair-odds line across hundreds of thousands of trades, and the cost corrections in
`costs.md` push every one of them further down. If any are live, they should be demoted.

**Do not tune trailing-stop width.** `breakout-runs.md` measured breakout excursion as
exponential with mean equal to the giveback, matching the driftless law on Volatility 75 to
within 0.05 at every quantile. Widening the trail widens the run proportionally, so **the
captured fraction is scale-invariant and that knob has no optimum.** Time spent tuning it is
time wasted, which is worth knowing before someone spends it.

Related and useful: the reversal hazard steps from 0.243 to 0.362 after two bars and is then
flat. **Momentum persists for about two bars and never exhausts**, so there is no "due a
reversal" state for a mean-reversion exit to target.

## What is not ready, and should not be shipped as a number

`excursion.md` found the largest verified live defect anywhere in this work: median capture of
favourable excursion **0.698**, and eight trades that reached 1R or better and still lost,
costing **−5.01 R** between them. That is real money and bigger than any backtested effect
here.

It deserves attention, but the obvious fix is ruled out by F - tuning the trail cannot help,
because the excursion distribution rescales. So it needs the shadow counterfactual
(`_also_wanted`) running both variants live rather than a chosen constant, which is what
`bandits.md` already argues is the honest way to rank anything here.

## Coverage gap worth fixing regardless

**Prod trades 32 symbols. This research covered 7 of them at hourly resolution** - gold,
silver, btc, eurusd, gbpusd, usdjpy, usdcad. usdchf, audusd and nzdusd had only 4h and 1d
bars; 22 symbols had no hourly data at all, including every index, every cross, both energies
and eth/sol.

Every conclusion above is therefore measured on under a quarter of the live book. A deep
hourly pull for the remainder was launched on 2026-09-21 using prod's own alias table in
`trading/config.py`, which is where the broker's descriptive names (`Wall Street 30`,
`US Tech 100`, `UK Brent Oil`) are already recorded.

## Still open

**Fade the spike** is the only hypothesis this research leaves alive. It is directionally
consistent across every configuration and horizon tested, with `vs always` between +0.030 and
+0.374 TR - but n=247 with error bars of ±0.073 to ±0.305, so it cannot be resolved with
hourly bars at all. A 5m and 15m pull of the synthetic family would give roughly twelve times
the sample and settle it; that download is running.
