# The venue sells the option only where the option cannot pay

`docs/plans/2026-10-13-statespace-strategies.md` ranked one arm first: price a
barrier or digital payoff from the member's own `Q` forecast and compare against
the venue's price. The reasoning was Blue Ocean's - direction is the crowded
axis and this desk has measured it closed twice, while every uncrowded axis it
has found is a **"how far"** rather than a "which way", and the instrument that
pays for "how far" directly is a barrier payoff rather than a spot position.

The plan also wrote down the check that would close it cheaply:

> If the barrier payoffs are priced off the venue's own generator with no margin
> for the variance structure, item 1 is arithmetic rather than research and will
> read zero.

That check has now been run, and the answer is sharper than the plan's version
of it. The line is closed **structurally** rather than statistically.

## What the venue quotes, and at what price

`research/harness/payout_logger.py` sends `proposal` requests only - there is no
`buy` in the file - and had never produced data, because Deriv's WebSocket
endpoint returned HTTP 520 from three hosts when it was written. The legacy
`websockets/v3` endpoints **still** return 520. The options endpoint,
`wss://api.derivws.com/trading/v1/options/ws/public`, answers.

Forty live quotes, plus the 227 and 572 rows from September:

| | implied probability | margin |
| --- | ---: | ---: |
| `R_10` through `R_100`, 1 to 60 minutes | **0.5120** | **1.20 pp** |
| range across all 40 quotes | 0.5099 to 0.5141 | 0.99 to 1.41 pp |

**The margin is flat.** It does not vary with the index's volatility - `R_10`
and `R_100` differ tenfold in sigma and quote the same 0.5120 - and it does not
vary with duration from one minute to sixty.

## That is correct pricing, which is what closes it

A rise/fall binary pays on whether the close exceeds the entry. For a
**driftless** geometric Brownian motion that probability is **exactly 0.5**,
whatever sigma is and whatever the horizon, because the median of a driftless
Brownian motion is its starting point at every time. There is no volatility
structure in the fair price at all, so there is nothing for a volatility
forecast to be right about.

And those indices **are** that process, validated rather than assumed:
`research/generators.md`, `twins.md` and `derivegbm.py` put `volatility_N_index`
at Hurst 0.50, kurtosis 3.00, Jarque-Bera p 0.40-0.95, variance ratios 1.000
and no volatility clustering, on 86,411 bars, with an annualised sigma of
exactly `N` per cent.

So the fair price is 0.5, the venue charges 0.5120, and the expectancy of a
rise/fall on these symbols is **exactly minus 1.20 percentage points per
trade** - for every entry rule, every filter, every duration and every sizing
scheme. That is `deriving.md`'s result instantiated: a predictable position on a
martingale earns `-(c/2) x turnover` and nothing else. **The desk's largest
measured edge cannot help here, because the quantity it forecasts does not
enter the price.**

## And the symbols where an edge exists are not on the menu

The synthetics whose generators have a **designed** asymmetry are the only ones
where a directional edge exists by construction - Boom and Crash spike one way
and grind the other, recovered at `+0.136` and `-0.136` through realised
semivariance in `susceptibility.md`, and `Drift_Switch` carries a planted drift
regime that this desk's own gate detects at `z + 2.90`.

`payout_logger.py` recorded on 2026-09-24 that neither Boom nor Crash quotes a
CALL at any duration, and asked for a re-check before anything was concluded
from it. `research/harness/asymmetric_probe.py` is that re-check:

**89 symbols offered on the options endpoint. Zero asymmetric synthetics** -
no Boom, no Crash, no DEX, no Drift Switch, no Jump, no Range Break.

Across three sessions the venue has produced a successful quote for **only** the
five volatility indices. `frxEURUSD`, `frxGBPUSD` and `frxXAUUSD` appear in the
log solely as `ContractBuyValidationError`, so even the real markets - where
direction is at least not provably zero - have never priced.

**The venue sells the option exactly where the option is worthless to the
buyer, and does not sell it where it could pay.** That is not a null result
about a signal; it is a fact about the product menu, and it is far more useful,
because no amount of better forecasting changes it.

## What this does to the plan

**Item 1 is closed.** Not "measured and found small" - closed, with a proof for
the symbols that quote and an empty menu for the symbols that would not need
one.

The Blue Ocean reading survives and its conclusion is unchanged: the desk's
edges are in "how far" and spot makes you convert them into "which way". What
changes is the assumed escape route. **The instrument that pays for "how far"
directly does not exist on this venue** - not for the synthetics with a drift,
not for the FX pairs, and the one it does sell has no volatility term in its
fair price.

So the plan's remaining items move up, and one of them is now the first:

1. **the two-leg hedge** on the dollar-controlled pairs, as a
   variance-reduction question rather than a spread-reversion one;
2. **entries and exits from `bounding` plus the conformal band**, which is
   mostly wiring measured parts together and needs no new research;
3. ~~the maker-side version of absorption~~ - already closed by
   `statespace-maker-side.md`: the maker fee is zero, and the venue with the
   signal has no maker side.

And one new item, which this study is the argument for: **find a venue that
sells a barrier or digital on something that is not a martingale.** The
arithmetic of item 1 was never the problem. The menu was.

## Method note

Both harnesses send `proposal` and `active_symbols` only. Neither contains a
`buy`, and neither was given a token - `DERIV_API_TOKEN` was explicitly unset
for every run here - so nothing in this study could reach an account.
