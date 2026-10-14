# What the live z-score record actually says

`structures/zma.py` keeps a scored record and does not vote, and its note in
`engine.py` said why: *"measured at 0.50 on this desk's instruments and worse
than that on Boom and Crash, so it keeps a record until the record says
otherwise."* The record has been accumulating in its own file since that was
written. This reads it.

Fetched from the live desk - 14KB, outside the engine state, read at idle
priority and never loaded on the host, which has about 1GB of 3.8GB free.

## What is in it

**464 series**, of which **165** have the `WARM = 200` settled calls that make
`accuracy` readable. Four of those are not instruments at all but constructed
cross-venue BTC spreads, and they are the easiest numbers in the file:

| series | calls | accuracy | edge calls | edge accuracy |
|---|---|---|---|---|
| btc_binance_coinbase tick | 17,340 | 0.8736 | 69,917 | 0.8493 |
| btc_coinbase_kraken tick | 16,288 | 0.8715 | 66,903 | 0.8560 |
| btc_bitstamp_coinbase tick | 12,879 | 0.8512 | 55,030 | 0.8323 |
| btc_binance_deriv tick | 20,662 | 0.8412 | 94,948 | 0.7987 |

**These are not evidence for the signal.** A cross-venue spread on the same
asset is mean-reverting by arbitrage, so a z-score call on it is right by
construction, and capturing it needs both venues. They are separated out
everywhere below.

## The headline is not 0.50, and it is not trustworthy either

On the 161 warm instrument series the pooled accuracy is **0.5654** and the
median **0.5548**, so the note in `engine.py` is **stale** - the record has
moved off 0.50.

It should not be read at face value, and the reason is in its own spread:

| measure | series | pooled | median | range | median n | overdispersion | effective n |
|---|---|---|---|---|---|---|---|
| accuracy | 161 | 0.5654 | 0.5548 | 0.141 to 0.826 | 477 | **4.8x** | **~21** |
| edge accuracy | 312 | 0.5517 | 0.5324 | 0.263 to 0.747 | 3,715 | **3.5x** | ~302 |

If every call were independent, the spread of accuracies across series would be
the binomial standard error at each series' own count. It is **4.8 times wider
than that** on `accuracy` and 3.5 times on `edge accuracy`.

The cause is not leakage - `_settle` is clean, scoring the previous bar's call
against the next bar's move with no overlap and no look-ahead. **The cause is
that the calls are serially dependent.** A z-score past a threshold is a
*state*, not an event: it persists for runs of bars, so every bar in an
excursion is scored as a fresh call while being near-identical to its
neighbour. `research/docs/direction-rules.md` measured the same thing from the
other direction this week - a price z-score's "level" events re-sample one
excursion many times, which is why every harness there spaces its events.

So a series with 477 nominal calls carries about **21 independent ones**, and
that is what produces accuracies from 0.141 to 0.826 at a nominal ten sigma in
both directions. Those extremes are not skill and not inverted skill; they are
the dispersion of a sample twenty times smaller than it looks.

## The consequence for a live gate

`TRADING_ZMA_GATE` is **on by default**, and `zma_min_calls` is 200, matched
deliberately to `WARM`. Below that count the gate passes everything; at or above
it, the gate starts believing the record and may veto.

**200 nominal calls is about 9 independent ones.** An accuracy estimated from 9
observations has a standard error near 0.17, so the gate begins acting on a
number that could be seventeen points away from the truth in either direction.
Reaching 200 *effective* calls at this overdispersion needs roughly **4,600**
nominal ones.

Two ways out, and they are not equivalent:

- **raise `zma_min_calls`** to something like 4,600, which is the cheap fix and
  leaves the record's own inflation in place for anyone else who reads it;
- **count episodes rather than bars** - settle one call per excursion, when the
  reading crosses the threshold rather than on every bar it stays past it.
  That makes `calls` mean what its name says, and it is the same spacing
  discipline every research harness here already applies.

The second is the right fix. It is also a change to a live scoring path, so it
is named here rather than made.

## Where accuracy sits by interval, and why that is a warning too

| interval | warm series | median accuracy | best |
|---|---|---|---|
| 1m | 24 | 0.6779 | 0.7802 |
| 15m | 20 | 0.5933 | 0.7944 |
| 2h | 13 | 0.5847 | 0.7301 |
| 30m | 18 | 0.5689 | 0.7251 |
| 5m | 20 | 0.5526 | 0.6484 |
| 3m | 20 | 0.5453 | 0.6121 |
| 1d | 13 | 0.5153 | 0.6471 |
| 1h | 17 | 0.4978 | 0.8257 |
| 4h | 14 | 0.4944 | 0.6411 |

Accuracy **falls as the interval lengthens**, from 0.678 at 1m to 0.494 at 4h.
Short-horizon hit rates on this desk's instruments are the ones least likely to
clear a spread: a 1m FX bar frequently does not move further than the quote is
wide, and this repo already records that fill quality is not signal validation
and that members lose exactly the spread on direction. A 0.55 one-bar-ahead hit
rate is not a tradeable edge until it is shown against cost, and nothing in
this record is.

## The verdict on the retirement question

**Neither retire nor promote.**

Promoting it to a vote is not supported: the pooled 0.55 is one-bar-ahead,
untested against cost, concentrated at the intervals where cost bites hardest,
and resting on a sample 4.8 times smaller than its own counter says.

Retiring it is not supported either, and the reason the original note gave -
"measured at 0.50" - is **no longer what the record says**. It says 0.5654
pooled with an honest standard error several times wider than it appears.

What is supported is fixing the counter, because a live gate is already acting
on it.
