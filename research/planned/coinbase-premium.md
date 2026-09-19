# Coinbase premium

Status: **not measured on this system.** Nothing here exists in the code.

The claim, as it usually circulates: the percentage gap between BTC/USD on
Coinbase and BTC/USDT on Binance - the *Coinbase Premium Index* - proxies US
institutional demand. Positive premium precedes rallies, negative precedes
corrections, flat means indecision. Therefore: long on positive, short on
negative.

That is a directional claim about a spread this desk already computes, which
is what makes it worth the measurement rather than the argument. Four BTC
spreads built here score 0.772-0.815 on 1,000+ calls each, and `zma` already
trades cross-venue dislocation as a *reversion* signal. The proposal is to use
the same quantity the other way round - as a *directional* one.

## What has to be answered before any of it is tradeable

The claim as stated is untestable. It names a sign and an outcome and no
horizon, and a sign with no horizon cannot be wrong. Three questions, in the
order that kills the idea cheapest:

1. **How long does the signal last?** Autocorrelation of the premium itself.
   If the sign flips every few minutes, there is no position to hold; if it
   persists for hours, there is. This is one query against stored quotes and it
   decides whether the rest is worth doing.
2. **How long do we have to hold?** The forward return of BTC conditioned on
   the premium's sign, at the offsets `Forward` already records - 60s, 300s,
   900s - and beyond, since a daily-scale flow story implies a daily-scale
   hold. `structures/reactions.py` now produces exactly this label, signed so
   positive means the call was right.
3. **Does the sign lead or lag?** The failure mode that makes this look
   profitable in a backtest and lose money live: if the premium moves *with*
   price rather than before it, every positive reading is a rally already
   happening, and entering on it buys the top of the move that produced the
   reading. Cross-correlation at negative and positive lags, not a
   contemporaneous fit.

A fourth, which decides the size of the opportunity rather than its existence:
**what does the spread cost to cross?** The premium is quoted in basis points
and Deriv's BTC spread is not free. A 4bp signal under a 6bp spread is a
measurement, not a trade.

## Why it is worth doing here specifically

The execution venue is Deriv, which does not need a Coinbase or Binance
account - the premium is *information*, and the position is taken on whatever
BTC instrument the broker offers. So a positive result is tradeable
immediately, with no new venue, no new custody and no new counterparty.

If it works on BTC it should be tested on ETH and on whatever else moves with
BTC, since the story is about US flow rather than about Bitcoin. That is a
second measurement, not an assumption: the premium may be informative about
BTC and silent about everything else.

## What would falsify it

- The premium's sign has no autocorrelation beyond a few minutes.
- Forward returns conditioned on the sign are indistinguishable from the
  unconditional distribution at every offset.
- The cross-correlation peaks at a *negative* lag - price leads the premium.
- The conditional edge is smaller than the round-trip spread.

Any one of those ends it, and the first is a single afternoon's work.
