# VIX as a scored member of the volatility ensemble

**Status:** design, agreed in conversation 2026-09-11. Sits behind the
measurement work (C before A); written now while the reasoning is fresh.

## Why this one and not a sizing knob

[implied.md](../implied.md) is the only positive result in this research folder.
Over 15 years, walk-forward, refit at every step, VIX beats a trailing realised
estimate by **12 to 20 points of R-squared**, and beats the naive baseline -
which has beaten GARCH, HAR, the pooled tree and the factorisation machine - by
**+0.26 to +0.43**.

Its sharpest finding is the one that decides this design: **`both` is not better
than `vix` alone.** The historical estimate adds nothing once VIX is present.
That is not "VIX helps", it is "VIX replaces". A sizing multiplier bolted on
the side would not use that finding; replacing part of the estimate does.

It transfers to ^NDX and ^DJI, and the *matched* index series are not needed:
`own - vix` is +0.0014 for us100 at one day and **-0.0080** for us30, where
plain VIX is better than VXD. **One feed for four instruments**, not four.

## Where it goes

`structures/vol/consensus_vol.py` already holds four estimates of one quantity,
converts them to a common convention, scores each against **what the next bar
actually did**, and can weight by that score. Its own module note says nothing
may be combined before it can be scored.

VIX becomes a fifth member on that machinery. Nothing new is invented:

* `Ensemble.observe()` takes a `name -> bps` mapping and a `sigma_scaled` set
  naming the members that report a standard deviation. VIX reports a sigma, so
  it joins `sigma_scaled` and the existing code does the mean-absolute
  conversion.
* `Ensemble.settle()` scores it against the realised bar, free.
* `Ensemble.standings()` already reports members by accuracy, and its docstring
  says "what the journal is for".

**That last point is why this shape beats a scaler.** A scaler that is wrong
sits there being wrong. A scored member that is wrong loses its vote, and the
journal says so without anyone intervening.

## Scope: `1d` and `1w`, four feeds

VIX is a **30-day** forward view published **daily**. Scaling that to a 1m bar
by root-time assumes a flat term structure and no intraday seasonality, and the
intraday U-shape is large and real. The other four members read actual bars and
have no such problem.

`implied.md` measured VIX at 1, 5 and 21 days and its own scope line is "the
equity indices at a day and up". So: `1d` and `1w` only, on `spx500`, `us100`,
`us30` and `us2000`.

At `1d` the conversion is `vix / 100 * sqrt(1 / 252)` - a division by
`sqrt(252)` with no intraday assumption at all. That is the reason for the
scope, not a consequence of it.

**What this improves is the volatility estimate daily and weekly levels and
origins are drawn from** - not the 1m-30m entries the desk fires on. Stated
plainly because it is easy to read this as a bigger change than it is.

## Weighting, which must change with it

`Ensemble.weighted` is `False`: members are combined **equally**. Drop VIX in as
an equal fifth member and it receives 20% of the vote regardless of merit, while
the research says it should carry most of it.

`Ensemble` is constructed per `(feed, interval)` inside `Volatility`, so
`weighted=True` can be set **only on the instances VIX joins**. The other 49
instruments are untouched. This is not a global behaviour change and must not
become one inside this piece of work.

## The warm start, which is most of the work

`SCORE_WARMUP = 60`. At `1d` that is about **three months** before VIX earns any
weight; at `1w`, over a year. A design that does nothing until December is not a
design.

`Score.accuracy` returns zero until warm, and when every weight is zero the
ensemble falls back to equal weights - so an unwarmed VIX is safe, but inert.

So the scores are **seeded from history**:

* `prices.db` already holds **9,144 daily** and **8,621 weekly** bars across the
  four indices. The index side needs no fetching.
* `^VIX` daily history comes from yfinance, already a dependency, free, 15
  years.
* Replay the five members over that history, compute each one's decayed
  relative error exactly as `Score.record` does, and seed `error` and `seen`.

`research/harness/impliedone.py` already scores VIX against forward realised
volatility over this period. The harness that produced the finding becomes the
warm start for the thing the finding justifies.

**The seed is a claim about history, not a measurement of this code**, so live
standings are logged alongside the seeded ones for the first months. A seed that
the live scores contradict is a finding about the seed.

## Collection

A daily `^VIX` close through `prices/yahoo.py`, published to the four feeds.

**Staleness is the failure that matters.** If the feed dies, the last value
keeps voting with full confidence on every subsequent bar. Past an age limit the
member is simply **absent from the mapping**, which the ensemble already handles
- members are whatever `observe()` was given. Holidays and closures resolve the
same way for free.

## Testing

1. The conversion, against a hand-computed value: VIX 20 at `1d` is a stated
   number of bps, written out in the test so a future edit argues with the
   arithmetic.
2. A stale reading is absent from the members mapping, not zero and not carried.
3. `weighted` is true on the instances VIX joins and **false everywhere else** -
   asserted across a book containing both, because the blast radius is the
   thing most likely to be got wrong.
4. A seeded score is overridden by enough live observations - the seed is a
   prior, not a floor.
5. VIX is absent from the members at `1m`, `5m`, `1h` and every interval below
   `1d`, on a feed where it is present at `1d`. The scope is a property to
   assert, not a convention to remember.

## Risks

* **The conversion is wrong.** Root-time scaling from an annualised 30-day
  number is a modelling assumption even at `1d`. The score catches it - a
  mis-scaled member ranks last and loses weight - but only after the warm-up it
  was seeded past. The hand-computed test is the real guard.
* **The seed is wrong**, and being seeded it is trusted for months. Mitigated by
  logging live standings against it, not eliminated.
* **`implied.md` measured `^GSPC`, not `spx500`.** The CFD tracks the index, but
  that is an assumption this work inherits rather than tests.
* **It is R-squared against realised volatility, not money.** Nothing here has
  been joined to a P&L, and a better volatility estimate improves stops,
  targets and level units on four instruments at a day and up - which is a
  claim about inputs, not about profit.
