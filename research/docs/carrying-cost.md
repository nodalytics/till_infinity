# What holding a position costs

Measured 2026-09-20 from the broker's own deal history and symbol specs.

Raised because the swap rates the bridge publishes looked alarming - Crash 1000
charges **-18% a year on both sides**, BTC -20%, the volatility indices -2.5% -
and the desk trades synthetics more than anything else, while no cost accounting
here had ever counted a swap.

## It is immaterial, because the desk does not hold overnight

30 days of deal history, 3,331 deals:

| | |
|---|---|
| realised profit | **-2,760.57** |
| total swap | **-24.03** (0.9% of it) |
| deals charged any swap | **9 of 3,331** (0.27%) |
| commission | **+0.00** |
| fees | +0.00 |

The rate is real where it lands - Crash 1000 cost -14.23 over two deals, so -7.12
each, Boom 500 -5.79 on one - but swap is charged at the broker's rollover and
almost nothing is held that long. The concern was right about the rate and wrong
about the exposure.

## So the cost model is complete, and short

* **Spread**, 0.10-1.07bp measured per bar - see `banded-labels.md`.
* **Stop overshoot**, a further 2-8% of risk on a typical trade and 42% on boom,
  measured from the desk's own fills - see `first-passage.md`.
* **Commission: zero** on this account.
* **Swap: under 1%** while holds are minutes.

Nothing else is charged, which is worth stating because two of today's four cost
figures started as assumptions off by four to six times.

## The accounting gap, which is small only conditionally

`_settle` takes `profit = live.position.profit`, and MT5's position profit
**excludes swap**. The swap-inclusive figure comes from `Broker.closed_deal`,
which sums `profit + swap + commission + fee` over the closing deals - and
`_reconcile` consults it **only when `why == "gone"`**, the case where the desk
finds a position missing without knowing why. Every normal exit - stop, target,
hold, stale - therefore records a profit with no swap in it: 955 of 971 outcomes.

That is under 1% today. It is under 1% **because holds are minutes**, and it grows
directly with holding period, so it is a latent error rather than a harmless one.
Anything that lengthens holds - a carry strategy, a wider target, a longer
`max_hold` - makes this misreport its own results, and on the synthetics it would
do so heavily.

## What this rules out

**Carry on the synthetics, completely.** A carry trade needs a side that is paid
to hold. Crash 1000, Boom, the volatility indices and BTC all charge on **both**
sides, so no direction is payable and the only question is how fast the charge
accrues. That is not an asymmetry to harvest; it is rent.

Carry survives only where one side is genuinely paid, which on this account is FX
and metals: short EURUSD +2.34, long USDJPY +5.00, long USDCHF +5.31, short
XAUUSD +20.0, all in points per lot per night against the losing side's larger
debit. That is roughly +2% a year on the paid side - real, mechanical, needing no
forecast, and about an order of magnitude smaller than the -0.19R a barrier trade
the desk currently gives up. It is a different business rather than a fix to this
one, and it would require the holding period that makes the gap above matter.
