# Perpetual-swap data: what is reachable, and what it might be worth

Probed against live exchanges on 2026-09-05 through ccxt 4.5.77. This is an
availability survey and a set of hypotheses. **Nothing below has been measured
against outcomes yet**, and the last section says what would settle each one.

## What each exchange actually answers

| | binance | bybit | okx | mexc | gate |
| --- | --- | --- | --- | --- | --- |
| funding rate, current (all pairs, one call) | ✅ | ✅ | ✅ | ✅ | ✅ |
| funding rate history (per pair) | ✅ | ✅ | ✅ | ✅ | ✅ |
| open interest, current | ✅ | ✅ | ✅ | — | — |
| open interest, all pairs in one call | — | — | ✅ | — | — |
| open interest history | ✅ | ✅ | ✅ | — | ✅ |
| long/short ratio history | ✅ | ✅ | ✅ | — | — |
| **public** liquidations | — | — | — | — | advertised, returns nothing |
| mark OHLCV | ✅ | ✅ | ✅ | ✅ | ✅ |
| index OHLCV | ✅ | ✅ | ✅ | ✅ | ✅ |
| premium index OHLCV | ✅ | ✅ | — | — | — |
| order book | ✅ | ✅ | ✅ | ✅ | ✅ |

Two corrections to the first version of this table, both from reading the probe
rather than remembering it:

* **Premium index OHLCV is binance and bybit only.** okx, mexc and gate expose
  mark and index but not the premium series, so the basis has to be built from
  the two rather than read directly there.
* **Only okx answers open interest for every pair in one call**
  (`fetchOpenInterests`, plural). Everywhere else it is one request per pair,
  which puts OI on the same expensive footing as funding history rather than
  the cheap footing of current funding.

Funding coverage where it was counted: binance returned a rate on 898 of 898
pairs, bybit 821 of 861, okx 636 of 636.

### The unit trap in open interest

`openInterestAmount` came back populated everywhere; `openInterestValue` only
on okx. **Amount is in contracts or base units and does not compare across
pairs** - 107,919 BTC contracts and 2,744,748 okx contracts are not the same
kind of number, and neither is comparable to a small-cap altcoin's.

Notional is the comparable quantity, which is `amount × mark`, and the *change*
in notional matters more than its level. This is the same argument
`research/catalogue.md` makes for volatility units: a raw number that means
something different per instrument cannot be a feature in a model that borrows
evidence across instruments, which is every model here.

## Why open interest ranks above funding

**OI plus price direction separates new money from closing**, and funding
cannot:

| price | open interest | what it is |
| --- | --- | --- |
| up | up | fresh longs - new money committing |
| up | down | shorts covering - old money leaving |
| down | up | fresh shorts |
| down | down | longs capitulating |

Those four resolve at a level completely differently. A level approached by
fresh longs has buyers who will defend it; the same level approached by shorts
covering has buying that stops the moment the covering finishes. **The price
path is identical in both cases**, which is precisely why this is worth having:
it is information a price-only model cannot recover.

Funding does not have that property. It is computed from the premium, which is
computed from price, so a model handed funding may be handed a lagged transform
of what it already sees. That is the leakage-shaped risk, and it is the reason
funding is second here despite being the thing that costs money.

Long/short ratio is positioning **measured rather than inferred**, which makes
it the most direct of the three and the one with the least coverage.

## Liquidations, which are mostly not available

Only gate exposes a public liquidation feed. Everywhere else `fetchLiquidations`
means *your own* liquidations, which is an account endpoint and useless as
market data - and easy to mistake for the public one, since `ex.has` lists
`fetchMyLiquidations` right beside it.

**And gate's returns nothing.** Asked for BTC and ETH, with and without a
24-hour window, it answered **zero rows** on pairs that certainly had
liquidations in that window. So the honest state of the table above is that
public liquidations are advertised by one exchange and delivered by none.

That is a `has` map describing a method that exists rather than data that
arrives, and a collector built on it would ship, configure, log correctly and
collect nothing - the pattern [inert.md](inert.md) catalogues. None was built.

So a liquidation cascade has to be **inferred, not observed**: open interest
collapsing against a price move in the same direction is forced closing, and
that is the shape to look for. Inferred at whatever resolution OI history
offers, which is coarser than the event itself.

This matters for `docs/todo.md` §6m, which lists a tracked liquidation price as
something freqtrade has and this desk does not. The per-position version is
computable from leverage and margin mode; the *market-wide* version, which is
what moves a level, is not directly readable and has to come from OI.

## What would settle any of it

The same discipline `slowing` had to pass in `structures/learning/breaking.py`,
and it is worth restating because it is what stops a plausible feature becoming
a permanent one:

> A weak separator uncorrelated with a strong one adds information; a second
> strong one that agrees restates it.

`slowing` earned its place at AUC 0.5237 - barely better than a coin - because
its correlation with `approach_vol` was **+0.008** over 4,078 touches. The order
is therefore:

1. **Collect and store**, changing nothing. Funding is built
   (`prices/funding.py`), and so are open interest and the long/short split
   (`prices/positioning.py`). Nothing consumes any of them yet.
2. **Correlate against what is already in the break model** - `approach_vol`,
   `depth_vol` - before looking at AUC at all. A feature that correlates highly
   with `depth_vol` is not a new input however well it scores.
3. **Then marginal AUC**, on resolved touches, in the horizon band where the
   answer is not definitional (`research/horizon.md`).
4. **Only then** anything that trades on it.

### The null that has to be run

Crypto perpetuals trend, and a feature measured on a trending series will look
predictive whether or not it is. `research/null.md`'s argument applies
unchanged: the control is the same measurement on a generated process with no
structure, and if the feature scores there too, it is measuring the trend.

### What is deliberately not claimed

That funding predicts direction. It is a **cost** first - one that scales with
time in the trade, which is the dimension `research/paying.md` does not price -
and a positioning signal second. The cost is arithmetic and certain; the signal
is a hypothesis with a plausible leakage explanation sitting next to it.
