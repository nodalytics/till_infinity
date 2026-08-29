# Cost-basis levels: do high-activity bands get respected?

Glassnode's long-term-holder cost basis reports how much bitcoin last moved in
each price band - 1.05m BTC between $83k and $86k with spot near $79k. The claim
is that a band holding a lot of supply is a price the market has to get through.

There is no on-chain feed here and a cost basis is bitcoin-specific anyway, so
what is built is the market-data form of the same object: the distribution of
activity over price, whose peaks are the bands. `structures/profile.py`.

Harness: [`harness/shelves.py`](harness/shelves.py). Build a profile on 600
bars, take its richest node, and ask whether price reaches it in the next 200 -
against **an arbitrary price the same distance the other way**, which is the
control [magnet.md](../docs/magnet.md) already uses.

## What it says

| instrument | weight | windows | node | control | gap |
| --- | --- | --- | --- | --- | --- |
| spx500 | time | 258 | 84.5% | 56.6% | **+27.9%** |
| us100 | time | 289 | 71.3% | 59.2% | **+12.1%** |
| ger40 | time | 66 | 62.1% | 50.0% | **+12.1%** |
| gold | time | 236 | 52.1% | 44.9% | +7.2% |
| eurusd | time | 326 | 54.3% | 51.5% | +2.8% |
| **btc** | **volume** | 357 | 41.2% | 48.5% | **-7.3%** |
| Volatility 25 | time | 34 | 52.9% | 61.8% | -8.8% |
| Volatility 75 | time | 42 | 47.6% | 45.2% | +2.4% |

**Time-weighted nodes are reached more than the control on every real
instrument that used time**, from +2.8% to +27.9%. The synthetics straddle zero
on small samples, which is what a null should do.

**The one volume-weighted instrument is negative.** btc is the only feed here
whose volume means contracts rather than tick count, and it is the only real
instrument where the node is reached *less* than the control. That is either
volume being the wrong weight or btc being a different market - one instrument
cannot separate those, and it should not be read as either.

## The confound, stated

A node usually sits **behind** price, where price has spent time. The control
sits the same distance the *other* way, which in a trend is ahead. So in a
trending market the control is the more reachable of the two, and the test is
biased **against** nodes. A positive gap survives that bias; a negative one on
the hardest-trending instrument here is exactly what the bias predicts, which
is another reason not to read btc as a verdict on volume.

## What this does not say

Reached is not profitable. It says price came within half a volatility unit of
the band inside 200 bars, which is the magnet question and not a trade. Nothing
here measures a stop, a target, or what happened on arrival - which is the
question `revisits.py` asks of origins and nobody has yet asked of these.

The formation is built and **not enabled**: `STRUCTURES_FORMATION` is still
`pip`. Turning it on is what would put these levels in front of the outcome
machinery, which is the only thing that can say whether they are respected as
opposed to reached.
