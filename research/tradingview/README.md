# A FOCuS indicator for TradingView

[`focus_zones.pine`](focus_zones.pine) puts the change-point work of
[localising.md](../localising.md) and [agreeing.md](../agreeing.md) on a chart:
it finds the candle a move *began from*, on four timeframes at once, and draws
that candle's own high and low as a support or resistance zone.

This is not a port of a strategy. Nothing here is measured to make money and
the indicator does not signal an entry - it draws the object the research has
been measuring, so it can be looked at directly rather than only in tables.

## What it draws, and why that is a level at all

An **origin** is the price a violent move started from. The claim is about
unfilled interest: if price dropped 1% in four bars, whoever was selling at the
top did not get filled, and the drop *is* the evidence they did not - so price
returning there meets the remainder. That is a different object from "a price
that has been touched several times", which is what most support/resistance
tools draw.

So the zone is **the changepoint candle's own high and low**. Not a padded
constant, and not a single line: the band is what actually traded there.

## Why FOCuS and not a CUSUM, an EMA cross or BOCPD

Measured on 8 instruments and 24 days of one-minute bars, as origin locators,
scored by how much each moves when the sampling grid is shifted by a minute
(6,300 paired comparisons - see [localising.md](../localising.md)):

| method | grid wander | verdict |
| --- | --- | --- |
| the extreme inside the bar | 0.107v | best, and it is not a detector |
| **FOCuS** | **0.161v** | best of the change-point family |
| MD-FOCuS (OHLC as a vector) | 0.194v | co-dependence is not free information |
| NEWMA | 0.211v | the ten-line one |
| doing nothing (the bar's close) | 0.226v | the bar to beat |
| BOCPD | 0.237v | worse than doing nothing |
| KCP | 0.237v | worse than doing nothing |
| RuLSIF | 0.251v | worse than doing nothing |

A CUSUM crosses a line and reports **where it crossed**, which is where the run
got long enough to be sure. FOCuS maximises the same likelihood ratio over
every possible starting point at once and reports the **argmax**, which is
where the change most likely began. For a level, those are different questions
and only the second one is the level.

Three of the four alternatives lose to *not running a detector*, which is why
none of them are in the script.

## Two timeframes, and what each is for

**Detection and placement are different questions and one statistic is not best
at both.** The anchor decides *that* a change happened; the refinement decides
*where the zone goes* inside the anchor bar that carried it.

That split is the measurement, not a convenience. FOCuS is the best of six
change-point methods at finding the bar (0.161v of grid wander) and **loses to
simply taking the extreme inside it** (0.107v) at finding the price. Every
blend of the two is worse than the extreme alone - 0.153v at a quarter weight,
degrading as more is mixed in - because an origin **is** an extremum, so weight
on any other price moves off the thing being estimated.

Defaults are a **4h anchor and a 5m refinement**: rare enough that each zone is
an event, tight enough that the band is an order's width rather than a region
of the chart.

The first version of this ran four detectors and drew all of them. It was
unreadable - the fast timeframes fire constantly and bury the zones that
matter. Timeframes below the anchor now *confirm* a zone rather than create
one.

## The agreement count drives the opacity, and that is the measured part

[agreeing.md](../agreeing.md): a change point calling on **three or more
timeframes** is followed by **+7.92v** a day out; one calling on a **single
timeframe** by **-1.24v**, at a matched realised move, with a shuffled-label
null at -0.66v and the effect present on 6 of 6 instruments that produce enough
of both.

They are not the same event at two strengths - they point opposite ways. So a
zone confirmed by one timeframe is drawn faint and one confirmed by four is
drawn solid, and the label carries the count.

**One agreement window for every timeframe**, not each timeframe's own bar
length. That was the mistake in the first version of the measurement: it gives
the 5m detector five minutes to be agreed with and the 4h one four hours, so
agreement becomes an artefact of the fastest clock rather than a fact about the
market.

`minAgree` defaults to **3**, which is that cut. Set it to 1 to draw every
anchor change and see what the filter is removing.

**Every standard rung inside the span counts, not a fixed four.** With the
defaults - 5m to 4h - the ladder is 5m, 15m, 30m, 1h, 2h and 4h: six chances to
agree. Narrowing the span narrows the ladder; the two inputs choose which part
of the standard set is live rather than stretching a fixed number of rungs
across it.

The rungs are **literals** in the script and that is not laziness.
`request.security` demands a *simple* string for its timeframe, and a rung
computed at runtime comes back as a series string and will not compile.
Deriving the ladder from the inputs looks tidier and does not work.

**Height is weighted, and that part is a prior rather than a measurement.** 1h
confirming counts for more than 15m confirming, weighted by the log of the
rung's length, and the label reports both the raw count and the weighted
`strength` as a percentage. The anchor rung agrees by construction - a zone
exists because the anchor fired - so the label also reports how far *below* the
anchor the confirmation reaches.

The distinction matters and the script keeps it visible:
[agreeing.md](../agreeing.md) scored the **count** and never scored which rungs.
It did measure that a slower timeframe firing is a larger event - as a
**confound it had to condition away**, not as an effect. So the count filters
and the weighting only shades.

## What was tried and did not work

Two negative results are worth knowing before anyone extends this:

* **Multivariate FOCuS over the OHLC vector lost to the univariate version**
  (0.194v against 0.161v). High and low are the bar's extremes, which widen
  with volatility whatever the direction, so two co-dependent views of the same
  move dilute the directional statistic rather than reinforcing it.
* **Cross-*instrument* agreement did not survive its control.** Running the
  same idea across eight instruments produced effects of about a volatility
  unit with shuffled-label nulls of comparable size - and Deriv's synthetic
  indices, which share no macro factor at all, produced a *larger* effect than
  real assets that share the dollar. See [peering.md](../peering.md). Nothing
  in this indicator looks at other symbols, and that is deliberate.

## Span and precision, which is the idea worth stealing

The **coarsest** timeframe that agrees decides how *significant* a zone is. The
**finest** one decides where its *edges* go.

A 4h changepoint tells you the level matters and gives a band far too wide to
rest an order in - measured on the live book, the 4h confluence box is 385bps
wide against an origin box's 71bps. The 5m bar inside the same change is where
the order actually goes. Collapsing the two into one number throws away
whichever half you needed.

This is the same split the source repository uses for confluence zones
(`Zone.span` and `Zone.precision`) and it arrived there by the same route.

## Honest limits

* **It has never been executed.** Pine cannot be run from where this was
  written, so the script is reviewed rather than tested. Several compile-level
  faults were found and fixed by reading alone - a global assigned inside a
  function, a computed timeframe string where a simple one is required,
  comma-separated assignments, an int/float ternary, and `for i = 0 to
  size - 1` on an empty array, which Pine runs *downwards* and throws on. There
  may be more. Compare its zones against the harness output on the same
  instrument and period before trusting it.

* **`lookahead_off` is load-bearing.** Without it a higher-timeframe bar is
  visible before it has closed, every historical zone is drawn using its own
  future, and the indicator looks superb on history and does nothing live.
  It is set; do not unset it.
* **A zone is not knowable when its candle prints.** The origin exists only
  once the move that followed has happened, so a zone appears some bars *after*
  the candle it is drawn on. That is correct rather than a lag to be tuned out
  - a repainting version of this would be drawing levels nobody could have
  known were levels.
* **Nothing here is a trade.** The measurements behind it are about where a
  price *is* and how far it *travels*, in volatility units, with no spread, no
  slippage and no fee. On the venue this repository trades, the taker fee alone
  is about 3.5%.
* **The zones wear out and the script does not model it.** Each return trades
  away some of whatever was resting there; the repository tracks `revisits` per
  origin and how fast they decay is unmeasured. A zone price has already worked
  through twice is drawn exactly like a fresh one here.
* **24 days.** Every number quoted above comes from the whole one-minute
  database, which is 24 days over 8 instruments, with overlapping forward
  windows. They are large effects on a short sample.

## Loading it

Pine v5. Paste into the Pine Editor, add to chart. Defaults are a **1d anchor**
and a **5m refinement**, a 3-nat threshold, a 250-bar volatility lookback, 2
timeframes minimum, a 6-anchor-bar agreement window, 12 zones a side and a
3-ATR minimum gap.

**The chart's own timeframe is the floor of the ladder.** A rung finer than the
chart is dropped rather than requested - `request.security` will happily fetch
a finer timeframe and what comes back cannot be relied on, which is a silent
wrong answer rather than a missing one. So on a 4h chart the eligible rungs are
4h, 8h and 1d, and `minAgree` must be reachable within them. When it is not,
the indicator **says so in the corner** instead of drawing an empty chart:
that failure was silent in the first version and is why it drew nothing above
1h.

**The 3-nat default is deliberately looser than the repository's 12.** Twelve is
the value `structures` ships, chosen to be conservative rather than fitted and
quiet enough on a stationary Gaussian stream to produce at most 5 false alarms
across five runs of 3,000 bars ([detecting.md](../detecting.md)). That is the
right setting for a detector nobody is watching. A chart is watched, a daily
anchor gives it few bars to work with, and 12 nats on a daily series produces
almost nothing - so the indicator trades some of that quiet for zones on the
screen, and `minAgree` does the filtering instead.

It is a log-likelihood ratio, so it is
"how many nats of evidence before this is worth saying" rather than a price
distance, and it means the same thing on every instrument.
