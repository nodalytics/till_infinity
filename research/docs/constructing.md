# The constructed spreads exist now, and they are the only series here ZMA reads

[`zma.md`](zma.md) and [`adapting.md`](adapting.md) reach the same conclusion
from opposite ends: the attention-weighted z-score is a working mean-reversion
detector, and every outright price this desk follows is a random walk with no
mean to come back to. The one place it paid was **constructed cross-venue
spreads**, built inside a harness from six BTC pairs and existing nowhere else.

They exist now. [`prices/spreads.py`](../till_infinity/prices/spreads.py) builds
them into the bar store like any other feed, which is the whole design: nothing
downstream can tell them apart. `structures` discovers them from
`SELECT DISTINCT feed FROM bars`, `vol` measures them, `zma` scores them,
`trading` would read their signals off the bus.

## Measured through the shipped code, on stored bars

The earlier figure came from a harness that constructed its own series in
memory. This is the shipped `structures.zma.Zma` over the shipped construction
path, 5,599 scored bars each at 1m:

| series | AUC | calls | hit |
| --- | --- | --- | --- |
| btc BINANCE-COINBASE | **0.7221** | 874 | **0.8444** |
| btc COINBASE-KRAKEN | 0.7194 | 894 | 0.8345 |
| btc BINANCE-DERIV | 0.7141 | 890 | 0.8202 |
| btc BITSTAMP-COINBASE | 0.7028 | 884 | 0.8371 |
| btc BINANCE-KRAKEN | 0.6980 | 865 | 0.7977 |
| btc BITSTAMP-KRAKEN | 0.6881 | 828 | 0.8116 |
| btc BITSTAMP-DERIV | 0.6812 | 884 | 0.8145 |
| btc BINANCE-BITSTAMP | 0.6620 | 838 | 0.8019 |
| **mean** | **0.6985** | | |

And the same instruments as outright prices, one venue each:

| series | AUC | calls | hit |
| --- | --- | --- | --- |
| btc @ DERIV | 0.5108 | 881 | 0.5153 |
| btc @ BINANCE | 0.4995 | 790 | 0.4911 |
| btc @ KRAKEN | 0.4825 | 746 | 0.4692 |
| gold @ OANDA | 0.5102 | 623 | 0.5056 |
| eurusd @ PEPPERSTONE | 0.5073 | 551 | 0.5336 |
| eurusd @ DERIV | 0.4980 | 556 | 0.5126 |
| spx500 @ OANDA | 0.5134 | 421 | 0.5226 |
| **mean** | **0.5031** | | |

0.6985 against 0.5031, on the same days, the same bars and the same detector.
The independent replication matters more than the number: `zma.md` built its
spreads a different way and got 0.67 to 0.73.

### The control that nearly wasn't run

The first version of that outright table read **btc 0.78, spx500 0.86, eurusd
0.64** - which would have said the detector works everywhere and the spreads are
nothing special. The query selected on `feed` and `source` and **not on
`venue`**, so it returned six venues' rows interleaved by timestamp, and the
alternation between two venues' quotes of the same asset is itself a violently
reverting series. It is the same defect that produced a VR(8) of 0.145 in an
earlier local test, and it is worth writing down because it is *silent*: the
query returns plausible prices in ascending time order and there is nothing to
notice.

## Two kinds, and only one of them can be held

**`venue`** - the same asset at two venues, weighted `+1` and `-1` in logs. It
reverts **by arbitrage** rather than by hope, needs no fitted ratio, and is what
the table above measures.

**It is not tradeable by this account.** Holding it means a position at each
venue and this desk has one broker, which is why `Spread.tradeable` exists and
why it is `False` for every row above. `crossing.md` measured the same wall from
the other side: 90.2% of cross-venue deviations belong to a venue the desk
cannot hold. These are built to be *measured*.

**`cross`** - two USD pairs at **one** venue, which is an implied cross exactly:
`ln(EURUSD) - ln(GBPUSD) = ln(EURGBP)`, no residual, no ratio, verified against
the real level at 0.85476. This one **is** holdable - two orders, one account -
and it is a new instrument rather than a reverting residual. Whether it is worth
its two spreads is not answered here.

## What is exact, and what is not

**Open and close are exact.** Both legs' opens are at the bar's open time and
both closes at its close.

**High and low are not**, and cannot be: each leg's extreme happened at an
unknown instant inside the bar, and pairing them would assume they coincided. So
the range is built from a finer interval where one exists, and is `max(open,
close)` where none does. That fallback is not cosmetic - aggregating 1m into 15m
gives a mean range **2.53x** the endpoints-only version on the same bars, so a
spread built only at its own interval hands `rogers_satchell_bps`, and therefore
`har.py`, a number 60% too small. `Built.exact_range` says which it was.

**A missing leg drops the bucket.** Never forward-filled. Carrying one leg
forward while the other moves manufactures a spread move that did not happen,
and on a series whose entire content is the difference between two nearly equal
numbers that is not a small error - it *is* the signal.

**One provider per spread by default.** A TradingView leg and a Yahoo leg are
two clocks: `lagging.md` measured that every timestamp stored here is our own
receive clock, so a cross-source spread carries the skew as if it were price.

**These do not revert to zero.** BTC Binance-against-Bitstamp sits at a median
+10.8 bps with a standard deviation of 2.2 bps; Binance-against-Deriv at +6.0
bps and 0.69 bps. The persistent offset is a quoting convention, and what
reverts is the deviation around a slowly-moving level - which is what a z-score
over a rolling window measures and a fixed threshold on the raw spread would
not.

## What this does not do

**It does not trade them.** `trading` places one order per signal, and a spread
is two orders with a stop, a target, a size and a cost model that are all joint
rather than per-leg. `prices.spreads.definition(feed)` returns what a feed is
made of precisely so that a two-leg execution path can be written against it,
and nothing reads that yet.

**Nothing says these pay.** An AUC of 0.70 on the next bar's sign is not money,
and the cost of a two-venue position is two spreads plus the funding to hold
both sides. `asking.md` lists the AUC-versus-money gap as outstanding and this
does not close it. What it closes is that the series now exist to ask the
question on.

    till-infinity prices spreads
    till-infinity prices spreads --kind venue --build 1m --build 15m

---

## Addendum, 2026-09-21: the signal lives entirely inside one bar

Re-measured on the multi-venue store — 63 venue pairs across btc, eth and sol, six venues,
2026-08-14 to 2026-09-08.

**The finding replicates and does not decay.** Mean AUC across 63 spread series is **0.7610**
against **0.5122** for the same detector on outright single-venue prices, and it is stable across
the two halves of the window — 0.7574 then 0.7647. That is above the 0.6985 reported here
originally, with the control flat at chance in both halves. Whatever it is, it is real and it is
not a fluke of the original sample.

**But it reaches only one bar ahead.** Scoring the same `-z` against the step at increasing lag:

| lag (minutes) | 1 | 2 | 3 | 5 | 10 | 20 |
|---|---|---|---|---|---|---|
| mean AUC, 63 pairs | **0.7610** | **0.5151** | 0.5077 | 0.5032 | 0.5001 | 0.5007 |

It collapses at lag 2 and is gone by lag 10.

### What that does and does not settle

**It does not identify the mechanism**, and a harness written here first claimed it did. Two
explanations produce an identical lag-1-only profile:

* **non-synchronous sampling** — every timestamp in this store is our own receive clock
  ([lagging.md](lagging.md)), so a spread between two venues carries measurement noise that
  reverts within one bar by construction, and was never a real price difference;
* **genuine sub-minute arbitrage** — cross-venue crypto arbitrage closes in seconds, so a real
  deviation also completes inside one 1-minute bar and leaves nothing for the next close.

One-minute bars cannot separate them. This document already half-said so — the spreads "revert by
arbitrage... which operates in seconds", and "a 1m close samples a seconds-scale process once and
misses most of it" — and [`spreadquotes.py`](../../till_infinity/structures/spreadquotes.py)
exists because of it. Settling the mechanism needs the `quotes` table, not `bars`.

**It does settle reachability, and that is the practical point.** The whole signal is inside one
bar, so **a rule that reads a bar close and then acts has nothing left to trade**. That holds
whichever mechanism is right, and it is a stronger constraint than the untradeability already
recorded here: it was never only that the second leg sits at a venue the desk cannot hold, it is
that by the time a bar has closed the deviation has already gone.

### Where that leaves the only positive result here

AUC 0.70 stands as a measurement and is no longer the thing to build on. Two routes remain, and
both are about *data* rather than method, which is the same conclusion
[`a-theory-from-ohlc.md`](a-theory-from-ohlc.md) reaches from the other end:

* **quotes rather than bars**, which would both identify the mechanism and give the only
  resolution at which the deviation is still open;
* **a venue pair the account can actually hold**, since `Spread.tradeable` is false for every row
  above and [`crossing.md`](crossing.md) measured 90.2% of cross-venue deviations belonging to a
  venue the desk cannot reach.

One further limit worth stating, which this document did not: the whole result rests on **25 days
of one asset class**. Stability across two twelve-day halves is what was testable, and it passed;
stability across years remains unmeasured.
