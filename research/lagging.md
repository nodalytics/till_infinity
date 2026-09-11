# Deriv's crypto quote is late, by about as much as every other venue is, and its spread is wider than the lateness is worth

The question was whether Deriv's `btc`, `eth` and `sol` CFDs follow the
exchanges with a delay that could be traded. They do follow with a delay. The
delay is real, it survives a placebo, it reproduces in both halves of a
three-week window, and it is **not a Deriv property**: every exchange on the
board lags a consensus of the others by the same amount or more. What separates
Deriv from them is not lateness, it is the spread - 2.39bps on btc against
Binance's 0.001 - and the spread is larger than the lag is worth at every
horizon a round trip could reach.

**Before anything else.** Trading a broker's own quote against the market it is
priced from is latency arbitrage, and it is the single behaviour retail brokers
surveil for. Retail CFD terms standardly reserve the right to void such trades
and close the account, and the behaviour is easy to see from the broker's own
side - short holds, entered against its quote, timed to public moves.

This is a demo account, so the question here is academic, and it would not be
academic on real money: a strategy built on this page would be one whose best
case is a closed account. That is a reason not to build it that stands
whether or not the numbers work, and it belongs here rather than in a footnote
under a result.

Harness: [`harness/lagging.py`](harness/lagging.py).

    ./.secrets/lab.sh run research/harness/lagging.py DAYS=21

**9,673,547 stored quotes** across six venues and three feeds, 2026-08-18 to
2026-09-08 UTC, on a 250ms grid - 7,257,551 points per series, 66-67% of them
usable. The gap between those two numbers is collector outages, which the
staleness mask refuses rather than carries forward: the 25th holds 6,650 Binance
btc rows against a 35,000 norm and the last day holds 154. Plus 481,400 MT5
ticks from the broker's own bridge for the cost side.

## What `structures` already had, and why it could not answer this

`features.Book` gives every venue a `staleness` against the group and the
`stale` shape fires when one venue stops while the others carry on. The lab's
copy of the journal holds **588** such decisions in its most recent 40,000
entries, **31** of them naming DERIV. They look like this:

    CAPITALCOM us30: has not moved in 37s while 4 other venues have

Thirty-seven seconds. That machinery is a dead-feed detector and it is correctly
tuned to be one. The lag this page is about is **two orders of magnitude
smaller** - it is over before `staleness` has a number worth printing - so
nothing already collected was going to answer the question and a separate
measurement was needed.

## The clock, which is where this kind of study usually dies

Every quote row in `prices.db` is stamped **by us, on arrival**:

    quotes.py   parse_quote(merged, now=time.time())      # the socket handler
    store.py    int(quote.time * 1000)                     # what gets written

TradingView's own `lp_time` is listed in `QUOTE_FIELDS`, requested on every
subscription, and then dropped on the floor by `parse_quote`, which builds the
`Quote` with `time=now`. **There is no venue-side timestamp anywhere in the
store.**

That is half good news. All six venues share one clock, so there is no
clock-offset term between them and a difference in arrival is a real difference
in arrival. It is also half bad: what is measured is

    venue moves + TradingView ingests + TradingView fans out + our handler runs

and only the first term is tradeable. Two facts from the data bound how much of
the rest there is.

**The cadence.** A row is written only when the top of book actually changed,
and the median gap between rows is 1.4 to 2.0 seconds on every exchange. That is
TradingView's push rate, not Binance's matching engine. **This data cannot
resolve a lead finer than about a second**, however the arithmetic is arranged.

**The phase.** Where inside the second each row lands should be uniform for a
receive time from a continuously pushing source. For four of the five exchanges
it is - every decile at 0.09 to 0.11. For Binance it is not:

| venue (btc) | deciles of `ts % 1000`, 0-100ms first |
| --- | --- |
| BINANCE | 0.02 0.02 0.03 **0.44** 0.19 0.11 0.07 0.06 0.04 0.03 |
| BYBIT | 0.10 0.09 0.10 0.09 0.10 0.10 0.11 0.09 0.11 0.09 |
| COINBASE | 0.09 0.11 0.09 0.11 0.10 0.10 0.11 0.09 0.11 0.10 |
| DERIV | 0.11 0.10 0.10 0.07 0.10 0.10 0.11 0.10 0.11 0.10 |

44% of Binance's btc rows arrive in one tenth of the second, and on `sol` the
concentration sits in a *different* decile. Binance is reaching us on somebody's
schedule, and a schedule is a fixed offset that reads exactly like a lead. So
"Binance leads X by 400ms" was never going to be a statement about Binance.

## Two Deriv quotes, and they are not the same series

The desk trades Deriv through the MT5 bridge. `research.db`'s `ticks` table is
that bridge - 416,481 btc ticks on a 105ms poll, 64,919 eth ticks - on the
broker's own server clock. `prices.db`'s DERIV rows are TradingView's copy of
Deriv, on ours. The plan was to align them and read the transport delay off the
peak. That failed for a dull reason: the dense quote window ends on the 6th and
the tick pull covers the 9th to the 10th, by which time the quote collector was
writing a few hundred rows a day. 400 overlapping DERIV rows is not a lead-lag
estimate.

What the overlap does support is a level comparison, and it is worse news than
the missing alignment:

| | MT5 (traded) | TradingView (measured) |
| --- | --- | --- |
| btc spread | **0.310bps** | 2.356bps |
| eth spread | **2.353bps** | 6.395bps |
| btc mid difference, p5..p95 | | **-5.38 to +15.47bps** |
| eth mid difference, p5..p95 | | **-19.03 to +17.53bps** |

The two Deriv quotes disagree by more basis points than the MT5 spread is wide,
and the disagreement wanders. They are related series, not one series down two
pipes. **Every number below is measured on the TradingView copy**, and the
window in which the traded copy could differ is wider than any edge on this
page.

## The cross-correlation says nothing at all

Log returns on the 250ms grid, `corr(x[t], y[t+k])` for k across ±15s, with
exchange-against-exchange pairs as the floor: whatever lead the pipe
manufactures between two venues that track each other to the millisecond in
reality is not a lead.

| feed | exchange-vs-exchange \|peak\| reaches | DERIV peaks span |
| --- | --- | --- |
| btc | 1.25s | -0.75s to +0.50s |
| eth | 1.50s | +0.25s to +0.75s |
| sol | 0.50s | -0.50s to +0.50s |

Deriv sits inside the floor on all three. And the profiles are flat: on btc,
`BYBIT -> COINBASE` peaks at r=0.093 with r=0.093 at zero lag, `KRAKEN -> DERIV`
at 0.056 against 0.056. The argmax of a flat profile is a rounding error with a
sign, which is why every row of the harness prints `r@0` beside the peak.

**First failure criterion, met.** Written before the run: *the cross-correlation
peak for Deriv sitting inside the exchange-against-exchange band*. It does.

## Conditioning on a dislocation finds something real

The continuous measure is dominated by noise, so the second measurement
conditions on the moments that would matter. A consensus log-price index is
built from the five exchanges with each venue's basis removed against its own
**trailing** hour - two of the five quote USDT pairs and three quote USD, so the
raw levels are not comparable and their median is not a price. The dislocation
is the consensus minus Deriv, in bps, against its own trailing hour. Trailing,
never centred: a centred baseline reads the future.

An event is `|dislocation| >= one Deriv spread`, with a 60s cooldown so windows
do not overlap. btc: 5,925 events in 21 days, 2.05% of usable time. eth: 1,172,
0.56%. sol: 251, 0.06%.

btc, threshold one spread (2.39bps). `deriv` is Deriv's own signed mid move;
`placebo` the same after a dislocation measured against a consensus rotated
twelve hours; `market` the consensus's own move, so convergence that is the
market coming back rather than Deriv catching up is visible; `round trip` buys
Deriv's ask and sells its bid (or the reverse), with nothing subtracted
afterwards because the spread is paid inside it.

| ahead | deriv | placebo | market | **round trip** | win% |
| --- | --- | --- | --- | --- | --- |
| 0.25s | +0.327 | -0.006 | -0.259 | **-2.191** | 6.7% |
| 0.50s | +0.620 | -0.005 | -0.493 | **-1.899** | 12.6% |
| 1s | +1.047 | -0.005 | -0.810 | **-1.473** | 21.3% |
| 2s | +1.299 | -0.023 | -1.090 | **-1.223** | 28.2% |
| 10s | +1.371 | -0.047 | -1.331 | **-1.149** | 33.4% |
| 300s | +1.671 | -0.091 | -1.139 | **-0.845** | 47.1% |

Deriv does move toward the consensus, the placebo never reaches 0.12bps at any
horizon inside a minute against dislocations of 2 to 15, and the round trip is
negative everywhere. The lateness is worth +1.3bps of mid and the spread is
2.39.

**It is not all lateness.** Splitting events by who opened the gap in the
previous five seconds - the market moving away from Deriv, or Deriv's own quote
moving away from the market - separates them completely:

| btc, 2s | n | deriv mid | round trip | win% |
| --- | --- | --- | --- | --- |
| market-made | 1,761 | +3.729 | **+1.223** | 72.7% |
| broker-made | 4,162 | +0.271 | **-2.257** | 9.4% |

Only the first is the hypothesis. The second is Deriv's quote wobbling and
coming back, which produces the same convergence and means nothing about
lateness - and it is **70% of the events**. On the market-made subset the round
trip is positive on all three feeds: btc +1.223, eth +3.229, sol +4.176. That is
where the page looked, for about an hour, like a finding.

## The control that killed it: put every exchange in Deriv's chair

Any venue measured against a median of the others will appear to revert to it,
because one top of book wanders and a median of four does not. That is a fact
about quotes, not about brokers - so the rotated placebo is not enough. Each
venue is therefore measured against a consensus that **excludes it**, at the
same absolute threshold (Deriv's own spread on that feed), paying its own
spread on the round trip. `Book.consensus(exclude=...)` takes the same argument
for the same reason and the harness borrows it.

btc, dislocation ≥ 2.390bps, measured 2s later:

| venue | spread | events | mid catch-up | **round trip** | market-made trip |
| --- | --- | --- | --- | --- | --- |
| BINANCE | 0.001 | 5,318 | +1.873 | **+1.870** | +3.202 |
| BITSTAMP | 0.001 | 6,508 | +1.603 | **+1.303** | +1.771 |
| BYBIT | 0.013 | 5,313 | +1.007 | **+0.990** | +3.012 |
| KRAKEN | 0.013 | 8,950 | +0.825 | **+0.755** | +0.815 |
| COINBASE | 0.001 | 6,767 | +0.174 | **+0.072** | +2.090 |
| **DERIV** | **2.390** | 5,923 | +1.299 | **-1.223** | +1.223 |

eth, ≥ 6.501bps, and sol, ≥ 14.610bps, in mid catch-up and round trip:

| venue | eth catch-up | eth trip | sol catch-up | sol trip |
| --- | --- | --- | --- | --- |
| BINANCE | +5.168 | +5.119 | +11.133 | +10.020 |
| BITSTAMP | +5.037 | +3.502 | +14.222 | +10.236 |
| KRAKEN | +4.760 | +3.745 | +10.568 | +7.686 |
| BYBIT | +3.208 | +3.125 | +10.630 | +9.409 |
| COINBASE | +1.168 | +0.551 | +6.128 | +3.522 |
| **DERIV** | **+5.578** | **-1.107** | **+13.710** | **-2.142** |

**Deriv's lateness is unremarkable.** In mid terms it is third of six on btc,
first on eth, second on sol - inside the range the exchanges produce among
themselves, and beaten by Bitstamp on two of three. The same dislocation in
Binance's quote converges by *more* than in Deriv's on btc. There is no
Deriv-specific lag to trade; there is a board of six venues that all wander
around their consensus and all come back.

The only column where Deriv is alone is the last one, and it is the spread. Five
venues turn a catch-up worth one to fourteen basis points into a profit because
crossing costs them a hundredth of a basis point. Deriv turns the same catch-up
into a loss because crossing costs 2.39, 6.50 and 14.61.

**This control was added after the market-made numbers came back positive.**
That sequence is worth naming: adding a *control* to a result that looks good is
the right move and adding a *filter* is not, and the difference is whether the
new thing can make the answer worse. This one did.

## Latency finishes it

The market-made subset is the only thing left that pays. Entry is not at the
instant the dislocation appears on the grid - it is after `structures` sees a
written quote, the bus carries it, `trading` decides and the broker fills.
Market-made dislocations ≥ one spread, held 5s, entered after a delay:

| delay | btc trip | eth trip | sol trip | btc gap still open |
| --- | --- | --- | --- | --- |
| 0.00s | **+1.538** | **+3.488** | **+5.290** | 3.400bps |
| 0.25s | +0.604 | +1.099 | -0.039 | 2.543 |
| 0.50s | **-0.256** | **-1.213** | **-4.780** | 1.758 |
| 1.00s | -1.491 | -4.773 | -9.799 | 0.645 |
| 2.00s | -2.161 | -6.467 | -13.640 | 0.159 |
| 3.00s | -2.299 | -6.833 | -14.154 | 0.169 |

Half a second. The gap closes by 81% within one second and by 95% within two,
and the whole of the edge is gone before half of it has elapsed. Zero delay is
already an optimistic accounting - the dislocation is only visible once the
arrival lag has happened - and even at zero it is +1.5bps on btc against a
measurement whose disagreement with the traded quote spans 21bps.

`reacting.md` records that latency "was going to be the interesting question and
never got asked", because the edge was zero before latency touched it. Here it
was worth asking and the answer is the same size as the question.

## The conditioned cut, and a thing that did not reverse

Simpson's paradox has reversed a pooled figure on this project four times, so
`shared.strata.compare` cuts everything by feed, by who opened the gap, by
six-hour block, by dislocation size and by threshold. The headline cut:

| bucket | n | mean round trip | median | positive |
| --- | --- | --- | --- | --- |
| market | 3,232 | **+3.306** | +1.799 | 76.3% |
| broker | 5,639 | **-2.716** | -2.521 | 11.2% |

The ordering holds in all twelve strata above `min_n` - every feed, every hour
block, every size, every threshold - and the thirteenth, the 4x threshold at
n=181, is reported with its count rather than hidden. No reversals in either the
event-against-placebo cut or this one. The conditioned answer and the pooled one
agree for once, which is worth saying out loud given what usually happens here.

## Split sample

First half against second half of the 21 days, Deriv's round trip at 2s and its
market-made subset:

| | btc | eth | sol |
| --- | --- | --- | --- |
| first half, all | -1.270 | -1.678 | -2.019 |
| second half, all | -0.974 | +1.209 | -0.830 |
| first half, market-made | +1.309 | +3.032 | +4.683 |
| second half, market-made | +1.254 | +3.759 | +3.224 |

Stable, on both sides, including the sign. The one positive cell - second-half
eth at +1.209 on 213 events - is the exception that a 21-day window produces
about once per table.

## Failure criteria, as written before the run

1. *The cross-correlation peak for Deriv sitting inside the exchange-against-
   exchange band.* **Met.** All three feeds.
2. *The peak not reproducing in both halves.* Not reached - there is no peak to
   reproduce.
3. *The catch-up being no larger than after a placebo dislocation.* **Not met.**
   The placebo stays inside 0.12bps at every horizon within a minute, on all
   three feeds, and the catch-up is real. This is the one test the hypothesis
   passed.
4. *The catch-up, net of placebo, being smaller than Deriv's spread.* **Met** on
   all three feeds, at every horizon, for the pooled events; met on the
   market-made subset as soon as entry is delayed by half a second.

And a fifth that was not written down and should have been, because it is the
one that decided the page: *the same catch-up appearing when an exchange is put
in the broker's chair.* It does.

## What would change the answer

**Not more of this data.** The edge is 1.5bps at an unachievable zero delay
against a 21bps gap between the quote measured and the quote traded. More
samples tighten an error bar around a number that is already smaller than the
uncertainty about which series it describes.

**MT5 ticks covering the same window as the quotes would.** That is the one
measurement that could settle whether the traded Deriv quote lags differently
from the TradingView copy, and it is cheap: `harness/mt5fill.py ticks` pulls
windows from the bridge. It was not run here because that bridge is the one the
live desk places orders through and `starving.md` is three days old.

**A tighter account would not.** Deriv's MT5 spread on btc is 0.310bps against
TradingView's 2.356, and at 0.310 the btc mid catch-up clears its cost from a
quarter of a second outward - the harness prints that column as `net MT5`.

It is a demo account. Demo spreads are a marketing number, the 21bps
disagreement between the two quotes sits on top of whichever one is real, the
half-second latency budget above does not move, and the surveillance argument at
the top of this page applies with full force the moment the account is.

## Two things found on the way

**`prices.db` is not corrupt.** It has been treated as unusable on this project
because `SELECT count(*) FROM quotes` raises `database disk image is malformed`,
and that belief cost this study its first hour. `PRAGMA integrity_check` names
**tree 6** - `quotes_feed_ts` - holding page numbers 5,365,662 and 5,366,040 in
a file of 5,365,199 pages, and then dies itself. The **table** is intact: every
query in this harness gives equality on all four leading primary key columns
with a bounded `ts` range, so the planner walks the table's own btree, and
10,871,879 rows across 18 series - 27 days, every venue, every feed - came back
without an error in 6.6 seconds. A `count(*)` picks the smallest index to count,
and the smallest index is the broken one. Anything that lets the planner reach a
secondary index - including an unbounded `min(ts)` - still raises, so the
constraint is real and the harness says so where it connects.

**A log price that starts at zero is a 113,000 basis point return.** `gridify`
has nothing to carry forward before a venue's first row, the first version
filled that with `log(1.0)`, and the masks hid it from the event selection but
not from the trailing means that the baseline is built on. The result was a
consensus whose 250ms return had a standard deviation of 18.6bps against a truth
near 0.5, a regression of any venue on the consensus with a slope of **0.03**
when it should be 1, and a first table reporting a mean forward market move of
+49.7bps. The tell was the slope: every venue at 0.03, including the four the
consensus is made of. A number that is wrong for all six venues identically is
not a finding about one of them.
