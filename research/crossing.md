# Nothing crosses its own spread except one cross on one day of the week

Run: `python research/harness/crossing.py`

> **Named `crossing.md`, not `structure.md`.** The brief asked for
> `research/structure.md`; that file exists and is the level set's shape and
> transit graph, measured in August. Overwriting a measured document to satisfy
> a filename is the one thing this folder cannot do. The harness is
> `crossing.py` for the same reason - `structure.py` is taken. The name is not
> arbitrary either: cross-venue, cross-rate and cross-instrument all end at the
> same place, which is a spread that has to be crossed.

The desk's one profitable strategy measures **+0.154R with a 95% interval of
[-0.022, +0.346]**. A tendency that marginal cannot be levered. A *structural*
edge could be, because its sign is known in advance and its payoff is locked at
entry rather than forecast - so it can be sized against a margin limit rather
than against an error bar. This is a hunt for one across the 53 instruments and
the six consensus venues already collected.

**One candidate survived, and it is small, weekly, and probably a swap.**
Everything else is null, and two of the nulls are cleaner than they look
because they were killed by arithmetic rather than by a p-value.

## What would have counted as failure, written before the run

| question | what kills it |
|---|---|
| consensus deviation reverts | reversion no larger than a permutation of the same sample; or less than the deviating venue's own spread; or the venue is one the desk cannot trade |
| triangular residual pays | the executable residual is never positive, or only when a leg is stale |
| one instrument leads another | the off-zero correlation peak is no larger on related pairs than unrelated ones, or implies less than the spread |
| a Volatility index is off its name | it is not, to within the split-sample spread |

Three of the four failed on their own terms. The fourth failed in a way worth
reading.

**546 comparisons**: 22 deviation cells, 24 broker-reaction cells, 40 triangle
cells with 8 controls and 72 offset scans, 8 sign checks, 8 carry-removed
checks, 8 weekday tables, 8 sixty-day triangles, 336 lead-lag correlations, 12
index definitions.

---

## 0. The clock, established first, because it decides three of the four answers

`reacting.md` was killed by cost. A cross-source study gets killed by the
clock, and the failure is silent: a lead-lag is a latency measurement unless
you know what each timestamp means. **There are two clocks here and they are
not the same clock.**

**`research.db.ticks` is the broker's own clock.** `mt5fill.py` reads MT5's
`time_msc` from the bridge, and every one of the 53 feeds is stamped by the
same terminal. So a comparison *inside* this table - between eurjpy and
eurusd, between us100 and us30 - is a comparison between instruments, not
between collectors. 99.1% to 99.9% of FX ticks land off a round second, so the
millisecond is real rather than a second wearing three zeroes. The Deriv
synthetics land on exactly 1000ms boundaries, which is a poll and not a push,
and is why nothing sub-minute was asked of them.

**`journal.db` is our receive clock.** `dev_bps` is computed by
`structures/features.py` with `now` taken from the `time` field of a
`prices.quotes` message. For every TradingView venue that field is set by

```python
parse_quote(merged, now=time.time())     # quotes.py:346
```

`lp_time` - the venue's own stamp - is asked for in `QUOTE_FIELDS` and then
never read by `parse_quote`. It is requested and discarded. So for the six
consensus venues:

    staleness  =  seconds since *we* last saw that venue's price change
    dev_bps    =  this venue's mid against the others' mids as *we* last had them

A venue that drops a websocket subscription is indistinguishable from a venue
whose market has stopped. A venue 200ms behind on delivery is indistinguishable
from a venue 200ms behind on price. **No cross-venue lead-lag is measurable
from what is stored**, at any horizon, however clever the estimator. That is
not a limitation of this study; it is a fact about the collection, and it is
the reason question 1 is asked only as a level comparison and starts at five
seconds.

The single-clock claim for the tick table is not asserted, it is measured. Each
triangle's residual was recomputed with the direct leg shifted from -2000ms to
+2000ms:

```
eurjpy offset scan, median |resid| bps:
  -2000ms 0.186  -1000ms 0.144  -500ms 0.120  -250ms 0.100
     +0ms 0.078
  +250ms 0.100   +500ms 0.116   +1000ms 0.139  +2000ms 0.179
```

A clean V with its minimum at exactly zero, on seven of eight triangles. If the
feeds were on different clocks the minimum would sit somewhere else, and it
does not.

---

## 1. Consensus deviation reverts less than a shuffle of itself

163,365 journal decisions carry `dev_bps`; 83,557 carry a venue and a feed,
across 183 (feed, venue) pairs and 28 days. Pairing each observation with the
next observation of the *same* (feed, venue) gives **49,660 transitions** inside
900 seconds.

**The sample is anomaly-triggered at both ends,** so regression to the mean is
guaranteed before any dynamics exist. The control is therefore not optional:
shuffle the second element within each (feed, venue), which keeps every
marginal and destroys the time order, and re-fit. 200 shuffles per cell.

`beta` regresses `dev_next - dev_now` on `dev_now`. **-1 is full reversion to
consensus, 0 is a random walk.**

| cell | n | beta | permutation 95% | verdict | median closed | venue spread |
|---|---|---|---|---|---|---|
| all, 5-15s | 1,025 | **-0.787** | [-0.907, -0.830] | less | +0.066bps | 0.910bps |
| all, 15-60s | 4,024 | -0.558 | [-0.709, -0.599] | less | +0.000 | 0.799 |
| all, 60-300s | 17,208 | -0.056 | [-0.287, -0.236] | less | +0.000 | 0.867 |
| all, 300-900s | 25,310 | -0.040 | [-0.244, -0.209] | less | -0.000 | 0.941 |
| stale, 5-60s | 1,243 | -0.176 | [-0.416, -0.204] | less | -0.277 | 0.935 |
| dislocation, 5-60s | 2,192 | -0.503 | [-0.889, -0.638] | less | +0.809 | 0.343 |
| spread, 60-300s | 4,891 | -0.200 | [-0.518, -0.429] | less | -0.405 | 1.201 |
| staleness <5s, 5-60s | 3,598 | -0.781 | [-0.887, -0.838] | less | +0.251 | 0.785 |
| staleness >=20s, 5-60s | 1,149 | -0.147 | [-0.231, -0.162] | less | -0.222 | 0.778 |

**Deviation reverts. It reverts less than a random re-pairing of the same
numbers, in 20 of 22 cells** - the two exceptions are DERIV cells at n≈100. The
reversion is the marginal distribution reasserting itself; what the time
ordering adds is *persistence*, in the wrong direction for a mean-reversion
trade.

The conditioning the brief predicted does appear and does not help. A fresh
venue's deviation (`staleness < 5s`) has beta -0.781 and a stale one -0.147, so
the *stale* deviation is the persistent one - the opposite of "a stale venue's
deviation is an artefact that reverts mechanically". That makes sense once the
clock is understood: `staleness` is our receiver's silence, and a receiver that
has been silent for 20 seconds stays silent.

**And the amount closed is below the venue's own spread in every cell.** The
best is `dislocation, 5-60s` at +0.809bps closed against a 0.343bps spread -
the one cell where the sign is right and the size clears - and it dies on the
next table.

### The table that ends it regardless of the statistics

| venue | deviations | share | can the desk trade it |
|---|---|---|---|
| OANDA | 13,250 | 15.9% | no |
| FOREXCOM | 9,722 | 11.6% | no |
| PEPPERSTONE | 9,213 | 11.0% | no |
| **DERIV** | **8,149** | **9.8%** | **yes - this is our broker** |
| SAXO | 7,870 | 9.4% | no |
| CAPITALCOM | 7,398 | 8.9% | no |
| FX_IDC | 7,100 | 8.5% | no |
| BITSTAMP, KRAKEN, COINBASE, BYBIT, BINANCE, TVC, BLACKBULL | 20,855 | 25.0% | no |

`dev_bps` is a **relative** quantity. Closing it is a two-legged trade: long
the cheap venue, short the consensus. The desk has one leg. **90.2% of all
measured deviations belong to a venue the desk cannot hold at any price**, and
the remaining 9.8% is our own broker, where the trade is "our price is wrong,
wait for it to be right" - which is a forecast about our own book, not an
arbitrage.

### So: does the price we can actually fill against move back?

Take the deviation as a signal and ask what the broker's own mid did next, on
broker ticks, against `reacting.md`'s control - same feed, same sign, a random
moment in the same window. Sign convention matters and would invert the
question if got wrong: DERIV deviating is a *revert* signal (our price is off);
anyone else deviating is a *follow* signal (someone else knows something).

| venue | n | 5s net | 15s net | 60s net | 300s net |
|---|---|---|---|---|---|
| DERIV | 125 | -0.289 | -0.214 | -0.555 | **+0.308** |
| OANDA | 158 | -0.520 | -0.324 | -0.242 | -0.110 |
| FOREXCOM | 153 | -0.428 | -0.455 | -0.074 | -1.131 |
| PEPPERSTONE | 124 | -0.618 | -0.620 | -0.126 | -0.819 |
| SAXO | 101 | -0.489 | -0.580 | -0.373 | -0.963 |
| CAPITALCOM | 138 | -0.504 | -0.431 | -0.465 | -0.413 |

`net` is edge over control minus the broker's spread, in basis points. **One
cell of 24 is positive**, at the longest horizon, on the smallest sample, with
a control of -0.521 where the same horizon's controls elsewhere run from -0.055
to +0.448. One in twenty-four at the 96th percentile of nothing is what
twenty-four draws from nothing looks like.

Sample is the honest limit here: the tick table spans 24 hours and the journal
spans 28 days, so fewer than a thousand deviations of 83,557 land inside both across the six venues with enough overlap to report. A wider tick
pull would tighten it. It would not rescue a reversion that runs below the
spread in every cell of the table above it.

### The dead column this harness produced, and kept

The first run reported `beta = -0.000 +- 0.000` with a permutation interval of
**zero width**. That is the signature `README.md` warns about - a statistic
sitting on exactly its null value is a defect, not a finding, and it has been
published here as a result once before. The cause was an OLS slope on a
variable whose tail reaches thousands of basis points: one observation owned
the entire regression, and shuffling the others changed nothing. Winsorising
both series to their central 98% is what produced every number above. The
broken form is kept in `winsorise()`'s docstring because the next person to
regress `dev_bps` on anything will hit it too.

---

## 2. The triangular residual is real, is tiny, and is mostly an accounting convention

`eurjpy` and `eurusd x usdjpy` are the same asset. Eight such identities exist
in the book. Every leg comes from one broker on one clock, so the only
synchrony problem left is that legs tick at different moments - which is why
every row below is also cut by the staleness of the *stalest* leg.

Executability is computed from real bid and ask, both directions:

    sell the direct, buy the synthetic:   bid_direct - ask_synthetic
    buy the direct, sell the synthetic:   bid_synthetic - ask_direct

with `ask_synthetic = ask_A x ask_B` or `ask_A / bid_B` as the identity
requires. A positive number there is not a tendency. It is a **locked
arbitrage**: the two positions are equal and opposite in every currency, so the
P&L is fixed at entry and there is nothing to hold for and nothing to be right
about. That is what "structural" means, and it is why this was the question
worth asking.

Over **4,570,847 observation points** across one day:

| triangle | median \|resid\| | p99 | p99.9 | 3-leg cost | free lunches |
|---|---|---|---|---|---|
| eurjpy = eurusd x usdjpy | 0.080 | 0.399 | 1.072 | 0.845 | 0.761% |
| gbpjpy = gbpusd x usdjpy | 0.067 | 0.314 | 1.108 | 1.013 | 0.156% |
| audjpy = audusd x usdjpy | 0.100 | 0.501 | 2.216 | 1.347 | 0.254% |
| eurchf = eurusd x usdchf | 0.075 | 0.420 | 1.017 | 1.261 | 0.243% |
| chfjpy = usdjpy / usdchf | 0.085 | 0.491 | 2.111 | 1.544 | 0.315% |
| eurgbp = eurusd / gbpusd | 0.078 | 0.328 | 1.490 | 0.976 | 0.122% |
| euraud = eurusd / audusd | 0.078 | 0.359 | 2.114 | 1.307 | 0.049% |
| **cadjpy = usdjpy / usdcad** | **0.668** | **1.571** | 2.843 | 1.091 | **59.9%** |

All in basis points, all with every leg fresh inside 100ms.

**Seven of the eight are tight to about eight hundredths of a basis point
against a cost thirteen times larger.** The locked residual's *99th percentile*
is still negative on all seven (-0.054 to -0.309bps): not "rarely profitable",
but "not profitable at the 99th percentile of a day". The free-lunch column is
the far tail of a distribution centred an order of magnitude below cost, and it
is worth fractions of a basis point when it appears.

Worth saying plainly, because it is the opposite of what the pre-registered
failure condition expected: **those moments are not stale legs.** Tightening
the freshness requirement from "any" to "<100ms" makes the free-lunch column
*larger* on six of the seven (eurjpy 0.505% to 0.761%, eurgbp 0.044% to 0.122%,
euraud 0.015% to 0.049%), because a stale leg blurs a real dislocation as
readily as it invents a fake one. So the tail is genuine - genuine, rare, and
smaller than the tickets. Question 2's stated kill condition was "never
positive, or positive only when a leg is stale"; the honest verdict is that it
fails on neither of those and on size instead, which is a worse failure for the
idea and a better one for the harness.

That the triangle is genuinely tight rather than merely noisy is established by
the desynchronisation control - the same computation with one leg taken from
sixty seconds later, which preserves every marginal and destroys the
simultaneity:

| triangle | true median \|resid\| | control | ratio |
|---|---|---|---|
| eurjpy | 0.076 | 1.008 | 13.3x |
| gbpjpy | 0.066 | 0.951 | 14.4x |
| chfjpy | 0.084 | 0.776 | 9.2x |
| eurgbp | 0.074 | 0.532 | 7.2x |
| **cadjpy** | **0.912** | **0.970** | **1.06x** |

The broker's cross rates track its own majors to within a tenth of a basis
point. Except one, which tracks them no better than a quote from a minute ago.

### Then sixty days of bars said every triangle had a one-signed offset, and that was arithmetic

The tick table is one day. Recomputing the mid residual from 62,500 one-minute
bars over 53 trading days produced a table where **every triangle sat
one-signed** - `euraud` negative on 0 of 53 days, `eurjpy` positive on 53 of
53. Eight persistent, stable, instrument-specific dislocations. It looked like
the finding.

It is not a finding. MT5 bars are built from the **bid**; the tick table says
what each leg's spread is; and the difference between a bid-built residual and
a mid-built one is then fixed arithmetic with no free parameters:

    direct = A x B :   resid_bid - resid_mid = (sA + sB - sD) / 2
    direct = A / B :   resid_bid - resid_mid = (sA - sB - sD) / 2

Predicting one table from a different table:

| triangle | 60-day median | predicted from spreads | left over |
|---|---|---|---|
| eurjpy | +0.152 | +0.119 | +0.033 |
| gbpjpy | +0.060 | +0.061 | -0.001 |
| audjpy | +0.060 | +0.068 | -0.007 |
| eurchf | +0.154 | +0.163 | -0.009 |
| chfjpy | -0.467 | -0.512 | +0.045 |
| eurgbp | -0.200 | -0.193 | -0.006 |
| euraud | -0.353 | -0.327 | -0.025 |
| **cadjpy** | **+0.174** | **-0.284** | **+0.458** |

**Seven of eight are explained to within 0.045bps by a bid/mid convention.**
The eighth is out by half a basis point, in a table it was not fitted to, built
from a different instrument-day, and it is the same instrument the freshness
and desynchronisation controls had already isolated. Three independent routes,
one name.

### CADJPY, and the day of the week

Splitting the sixty days by weekday - the whole table, not just the suspect:

| triangle | Mon | Tue | Wed | **Thu** | Fri | Sun | Thu / other |
|---|---|---|---|---|---|---|---|
| eurjpy | +0.152 | +0.139 | +0.135 | +0.163 | +0.187 | +0.200 | 1.07x |
| gbpjpy | +0.061 | +0.069 | +0.070 | +0.052 | +0.045 | -0.006 | 0.85x |
| audjpy | +0.063 | +0.085 | +0.083 | +0.040 | +0.011 | +0.041 | 0.63x |
| eurchf | +0.158 | +0.155 | +0.151 | +0.152 | +0.149 | +0.235 | 0.99x |
| chfjpy | -0.475 | -0.484 | -0.481 | -0.451 | -0.419 | -0.574 | 0.94x |
| eurgbp | -0.206 | -0.204 | -0.203 | -0.193 | -0.183 | -0.253 | 0.95x |
| euraud | -0.359 | -0.355 | -0.359 | -0.343 | -0.332 | -0.454 | 0.95x |
| **cadjpy** | +0.132 | +0.127 | +0.143 | **+0.950** | +0.147 | +0.018 | **7.22x** |

Seven triangles are flat to within 0.63-1.07x. One is 7.22x, on Thursday, and
on **nine Thursdays out of nine** in the sample. Converting out of the bid
convention, CADJPY's mid sits **+0.42bps** above its own synthetic on an
ordinary day and **+1.23bps** on a Thursday - and the tick table, measured
independently, gives +0.43 for its Wednesday hours and +1.22 to +1.32 for its
Thursday hours. Two tables built from different rows of different databases
agree to two hundredths of a basis point.

**A spot cross settles T+2.** Rolling from Wednesday to Thursday moves the
value date three days instead of one, so the forward points embedded in the
price triple on Thursday. That is the textbook signature, and it says what this
is: **the broker's direct CADJPY carries a forward/value-date adjustment that
its own USDJPY and USDCAD do not**, worth about four tenths of a basis point on
an ordinary day and three times that on the roll.

### What it would take to trade, what it would cost, and how large it could be

The trade is one order in each of three symbols, held. Sell CADJPY, buy USDJPY,
sell USDCAD, matched in notional. Net exposure in CAD, JPY and USD is zero, the
P&L is fixed the moment the third fill lands, and there is nothing to forecast,
no stop, no timeout and no exit rule - which is precisely the property that
lets a structural edge take size where `+0.154R [-0.022, +0.346]` cannot.

Charging every leg of every spread, as `reacting.md` insists:

| | ordinary day | Thursday |
|---|---|---|
| CADJPY mid against its synthetic | +0.42bps | +1.23bps |
| crossing three spreads, once | 0.545bps | 0.545bps |
| **locked P&L** | **-0.13bps** | **+0.69bps** |

**Six days a week it does not clear its own cost. On the seventh it clears by
about seven tenths of a basis point**, which is what the tick data measured
directly on 2026-09-10 (locked p50 +0.15 blended across the Wednesday and
Thursday halves of the window, p99 +1.05).

**Sizing.** Determinism is the argument for size, and it is genuine here: the
sign is known before the order goes in, the payoff does not depend on anything
happening next, and the position has no price risk to stop out of. So size is
bounded by margin on three legs and by the broker's position limit, not by an
error bar - which is a different kind of constraint and a much larger number.
Against that: **+0.69bps once a week is about 0.36% a year** on one leg's
notional, gross. It is levered *well* or it is not worth the three tickets.

**And the number that decides it is not in any database here.** A locked
three-leg CFD position is charged an overnight swap on each leg, and it is
charged the *triple* swap on exactly the night this trade wants to be open. The
most likely explanation for the whole effect is that the broker has put the
value date into the CADJPY price and will take it back out through the swap
that evening - in which case the +0.69bps is not profit, it is a receipt.

That is one bridge call away from settled. `/api/v1/symbols/...` returns
`swap_long` and `swap_short` per symbol, and the test is arithmetic:

> **Pre-registered.** Read the three symbols' swap rates. If the combined
> overnight charge on short CADJPY + long USDJPY + short USDCAD over the
> Wednesday-to-Thursday roll is **more than 0.69bps of notional, there is
> nothing here** and this section is a description of how a broker quotes a
> cross. If it is materially less, it is a deterministic weekly payment and the
> only question left is size.

### Settled 2026-09-11: there is nothing here, and the swap says why

The bridge call was made. Live specs, `swap_mode` 1 (points):

| leg | side | swap, points/night | **triple lands** |
| --- | --- | ---: | --- |
| CADJPY | short | -7.81 | **Wednesday** |
| USDJPY | long | +5.00 | **Wednesday** |
| USDCAD | short | -9.83 | **Thursday** |

**`swap_rollover3days` is 4 on USDCAD and 3 on the other two**, and that single
field is the whole explanation. USDCAD settles **T+1** - it is the textbook
exception - so its triple charge lands on Thursday, while the T+2 majors take
theirs on Wednesday. The synthetic CADJPY is built as USDJPY over USDCAD, so on
Thursday the denominator carries a three-day forward adjustment that neither the
direct CADJPY nor USDJPY carries. **The Thursday anomaly is a settlement
convention showing up in the synthetic, not a mispricing of the direct quote**,
which is why it appears on nine Thursdays out of nine and nowhere else.

The arithmetic, per one lot a leg, held through the Wednesday night:

| leg | points charged | USD |
| --- | ---: | ---: |
| CADJPY short, tripled | -23.43 | -15.25 |
| USDJPY long, tripled | +15.00 | +9.76 |
| USDCAD short, single | -9.83 | -7.09 |
| | | **-12.58** |

Against roughly 100,000 USD of notional a leg that is **-1.258bps for one
night**, against the **+0.69bps** the triangle collects. **Net -0.568bps.**

The condition fired on the side it was written to fire on. The +0.69bps is a
receipt, exactly as the paragraph above guessed, and the broker takes back
rather more than it hands over. The two things that page said were true either
way still are: CADJPY's price disagrees with the rest of the book, so anything
built on it is built on a different curve; and seven of the fifteen FX
instruments are redundant to within a tenth of a basis point.

Two things that are true either way, and cost nothing to know. **CADJPY is the
one instrument in the book whose price disagrees with the rest of the book**,
so any level, volatility or consensus figure built on it is built on a
different curve from its neighbours. And the other seven crosses are redundant
to within a tenth of a basis point, which means seven of the fifteen FX
instruments carry no information the other eight do not - relevant to anything
that counts instruments as independent samples.

### The part of the residual that is not carry is smaller still

Removing the window's own median - taking out the level and leaving the wiggle:

| triangle | \|resid\| p50 | p99 | half-cost | locked > 0 |
|---|---|---|---|---|
| eurjpy | 0.078 | 0.376 | 0.423 | 0.61% |
| gbpjpy | 0.066 | 0.299 | 0.507 | 0.11% |
| audjpy | 0.102 | 0.554 | 0.667 | 0.36% |
| eurchf | 0.074 | 0.404 | 0.631 | 0.22% |
| chfjpy | 0.087 | 0.552 | 0.772 | 0.39% |
| eurgbp | 0.077 | 0.322 | 0.488 | 0.08% |
| euraud | 0.077 | 0.339 | 0.654 | 0.03% |

Once the level is gone, the 99th percentile of the residual is below half the
crossing cost on every triangle. **There is no dislocation trade in FX
crosses on this broker.** There is a level, and the level is a convention.

(`cadjpy` is excluded from that table: its window straddles a Wednesday and a
Thursday, so subtracting one median from a two-regime sample leaves the regime
gap behind and reports 26.7%, which is the two days and not a dislocation. The
day-by-day table is the honest form.)

---

## 3. Related instruments do not lead each other, and two unrelated ones look like they do

One broker, one clock, so a lead here would be between instruments rather than
between collectors. 1s log returns on a fixed grid, a quote required within 5s
on both sides, lags +-10s: **336 correlations over 16 pairs.**

| pair | n | rho(0) | best off-zero | at lag | implied bps | spread | net |
|---|---|---|---|---|---|---|---|
| **related** | | | | | | | |
| us100 / us30 | 68,364 | 0.4449 | 0.0344 | +1s | 0.0081 | 0.2469 | -0.239 |
| ger40 / fra40 | 42,238 | 0.5312 | 0.0404 | +1s | 0.0162 | 0.9792 | -0.963 |
| ger40 / uk100 | 50,490 | 0.4678 | 0.0393 | +1s | 0.0147 | 0.5631 | -0.548 |
| fra40 / uk100 | 40,927 | 0.4388 | 0.0335 | -1s | 0.0131 | 0.5631 | -0.550 |
| gold / silver | 79,198 | 0.7598 | 0.0494 | +1s | 0.0434 | 3.7383 | -3.695 |
| btc / eth | 58,345 | 0.7692 | **0.1131** | -1s | 0.0889 | 2.3531 | -2.264 |
| eurusd / gbpusd | 75,141 | 0.2720 | 0.0163 | -2s | 0.0038 | 0.2953 | -0.292 |
| usdjpy / eurjpy | 77,638 | 0.7597 | 0.0552 | +1s | 0.0083 | 0.2801 | -0.272 |
| **unrelated controls** | | | | | | | |
| us30 / btc | 68,213 | 0.1603 | **0.0961** | +1s | 0.0569 | 0.3104 | -0.254 |
| ger40 / gold | 60,189 | 0.2471 | 0.0422 | +1s | 0.0215 | 0.3412 | -0.320 |
| us100 / gold | 81,500 | 0.3244 | 0.0383 | +1s | 0.0181 | 0.3412 | -0.323 |
| gold / uk100 | 58,384 | 0.1978 | 0.0373 | -1s | 0.0133 | 0.5631 | -0.550 |
| us100 / volatility_75_index | 82,011 | 0.0011 | 0.0084 | -5s | 0.0113 | 3.5308 | -3.520 |
| btc / gbpusd | 81,901 | 0.0265 | 0.0163 | -1s | 0.0051 | 0.2953 | -0.290 |
| eurusd / step_index | 77,169 | -0.0006 | 0.0059 | -8s | 0.0008 | 0.1322 | -0.131 |
| silver / boom_500_index | 79,332 | 0.0011 | 0.0072 | +1s | 0.0039 | 0.1399 | -0.136 |

**The second-largest off-zero correlation in the study is between the Dow and
bitcoin**, and it beats six of the eight related pairs including every index
pair the brief asked about. This is `generated.md` again from a different
direction: in a 325-pair study there the largest correlation was between two
unrelated instruments, and here in a 16-pair study the runner-up is Wall Street
30 against BTC at one second. Any ranking of "which index leads which" built
without these controls would have reported us100/us30 at 0.0344 as a lead-lag
and never learned that an instrument with no relationship to either scores
2.8x higher.

The contemporaneous correlations *are* real and large - 0.27 to 0.77 on the
related pairs (0.27 on the weakest, eurusd/gbpusd) against -0.00 to 0.32 on the controls - which is the shape of
instruments moving together rather than one after the other. **There is no
lead; there is simultaneity.**

And the cost table closes it independently. The largest implied move anywhere,
taking the best off-zero correlation entirely at face value, is **0.089bps
against a 2.35bps spread**. Every one of the sixteen is negative net by between
0.13 and 3.70bps. Even if a lead existed it would be worth about a fortieth of
the cheapest spread in the book.

---

## 4. The Volatility indices are exactly what they are named

53 days of one-minute closes, annualised at 365x24x60 minutes because these run
continuously, split in half by time.

| feed | named | measured | ratio | 1st half | 2nd half |
|---|---|---|---|---|---|
| volatility_10_index | 10 | 10.04 | 1.004 | 10.02 | 10.05 |
| volatility_25_index | 25 | 24.99 | 1.000 | 24.93 | 25.04 |
| volatility_50_index | 50 | 49.92 | 0.998 | 49.77 | 50.08 |
| volatility_75_index | 75 | 74.98 | 1.000 | 74.91 | 75.05 |
| volatility_100_index | 100 | 99.91 | 0.999 | 99.65 | 100.17 |
| volatility_10_1s_index | 10 | 9.99 | 0.999 | 10.00 | 9.98 |
| volatility_25_1s_index | 25 | 25.06 | 1.002 | 25.06 | 25.05 |
| volatility_50_1s_index | 50 | 50.12 | 1.002 | 50.08 | 50.15 |
| volatility_75_1s_index | 75 | 74.99 | 1.000 | 75.09 | 74.90 |
| volatility_100_1s_index | 100 | 100.50 | 1.005 | 100.72 | 100.27 |
| volatility_150_1s_index | 150 | 150.70 | 1.005 | 151.22 | 150.17 |
| volatility_250_1s_index | 250 | 250.75 | 1.003 | 250.69 | 250.82 |

**Twelve of twelve, within half a percent, in both halves.** The generator does
exactly what the label says, so there is no instrument-versus-definition edge
and - the part that matters for everything else - the desk's own volatility
estimate on these inherits no bias from the instrument. It can be wrong for its
own reasons (`volatility.md` says a flat 20-bar mean beats it), but not because
the thing it is measuring is mislabelled.

This is deliberately only the level check - the generator study, iid-ness,
shared drivers and the twins, is somebody else's and was running beside this
one. It landed on the same number from a different harness and a different
estimator: [generators.md](generators.md) reports 12 of 12 within **0.49%**
and [twins.md](twins.md) reports all twelve inside two standard errors of
their advertised volatility. Three independent measurements agreeing is
worth more than any one of them, and it means the answer to question 4 is
settled rather than merely unrefuted.

---

## What this does not say

**It does not say the consensus layer is useless.** It says `dev_bps` cannot be
*traded* from one leg, and that its reversion is weaker than a shuffle. Whether
it is a useful *feature* - a filter on when not to trade, a check that a quote
is real - is a different question, asked in `venues.py`, and this is silent on
it.

**It does not clear the cross-venue lead-lag question.** It shows the question
cannot be asked of what is stored, because `lp_time` is discarded. Storing it
is a one-line change in `parse_quote` and would make the question answerable in
about a month of collection. That is the single highest-value change this study
found, and it is not in `till_infinity/` - it is one field.

**The tick sample is one day.** Every tick-level number here - the triangular
residuals, the lead-lags, the broker reactions - comes from 2026-09-09 12:08 to
2026-09-10 12:08 UTC. The sixty-day bar tables are what stop that being fatal
for question 2, and there is no bar-based equivalent for question 3 because a
one-minute bar cannot see a one-second lead.

**The CADJPY result is one instrument.** Nine Thursdays is nine observations of
a weekly event, the mechanism is inferred rather than confirmed, and the number
that decides whether it is money has not been read yet.

## Two harness bugs, kept

**The dead column.** `beta = -0.000 +- 0.000` with a zero-width permutation
interval, from an OLS slope on a variable with a thousand-basis-point tail.
Winsorising fixed it and every number in §1 is post-fix. Documented in
`winsorise()`.

**The weekday off by one.** 1970-01-01 was a Thursday, so epoch day 0 must map
to index 3 when Monday is 0; the first version added 4 and printed the CADJPY
spike under Friday. It was caught because the day-by-day table listed the dates
and nine of nine were Thursdays, which is the reason to print dates next to a
dial rather than only the dial.

## Answer, in one line each

- **Does consensus deviation revert?** Yes, and less than a shuffle of itself,
  by less than the deviating venue's spread, on venues the desk cannot trade
  90.2% of the time.
- **Does the triangular residual ever exceed costs?** On seven of eight
  crosses, no - not at the 99th percentile of 4.5 million observations. On
  CADJPY, yes, on Thursdays, by about 0.69bps.
- **Is anything deterministic enough to lever?** The CADJPY Thursday trade is,
  structurally - locked payoff, no forecast, no exit rule. Whether it is
  *profitable* rests entirely on three swap rates nobody has read.
