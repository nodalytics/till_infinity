# Should production draw PIPs at several window lengths? — measured 2026-09-21

By `research/harness/pip_levels.py`, on six instruments across the synthetics, a cross, a dollar
pair, an index and crypto: 234,000 level observations and 99,000 resolved touches.

**No, on two independent grounds.** The proposal was to draw perceptually important points at
several window lengths rather than the single window `engine._points` uses today. The sweep is
almost entirely redundant with the interval ladder production already runs, and agreement across
windows carries no predictive information.

**This is a well-powered negative**, which is rare here and is the point of having computed the
minimum detectable effect before the run rather than after.

## What production does today

`engine._points` calls `pips.points(times, closes, self.pip_count)` on the whole `Series` buffer -
**one window, one count, per interval**. It already runs many different *formations* over that
window (`run`, `origin`, `profile`, `equal`, `gap`, `round`, `wick`, `vwap`) and several
*intervals* beside it, so multi-scale behaviour is already present. The question is whether
varying the window *within* an interval adds anything the interval ladder does not already give.

## Question one: the sweep rediscovers the ladder

Share of levels found by the window sweep that were already within 0.15% of a level the interval
ladder had found anyway:

| windows agreeing | levels | already in the ladder |
|---|---|---|
| 1 | 94,781 | 53.8% |
| 2 | 48,662 | 86.5% |
| 3 | 22,805 | 98.2% |
| 4 | 9,342 | **99.4%** |

The gradient is the finding. A level only one window sees is new about half the time; a level
**all four** windows agree on is new **0.6% of the time**. So the very levels the proposal was
meant to promote - the ones with the most agreement - are precisely the ones the ladder already
has.

That is not a coincidence, it is arithmetic: a 300-bar window on 1h spans the same period as a
75-bar window on 4h, and the ladder is already looking there. Multi-window agreement is a slower
way of asking a question the interval ladder answers.

**And level count is not free.** Every additional level is another thing price can be near, which
dilutes confluence and gives the level set more chances to appear predictive by coincidence. Adding
9,342 levels of which 99.4% are duplicates is a cost with no matching benefit.

## Question two: agreement predicts nothing, and this time we could tell

Each touch is a trade in the rejection direction with stop and target one true range apart, so
fair odds is 50% for every row and geometry cannot explain a result. Costs charged at the measured
live figures - 0.063 TR of slippage from 305 journal fills, plus spread - giving a break-even of
**52.0%**, a 2.0-point hurdle.

| windows | n | hit | excess | detection floor | net R |
|---|---|---|---|---|---|
| 1 | 57,877 | 49.8% | −0.22% | 0.69% | −0.056 |
| 2 | 40,281 | 50.0% | −0.02% | 0.83% | −0.052 |
| 3 | 21,143 | 49.3% | −0.68% | 1.15% | −0.066 |
| 4 | 10,828 | 49.4% | −0.58% | 1.60% | −0.064 |

Flat, and marginally below fair odds throughout - which is the expected sign, since a bar touching
both barriers counts as a stop everywhere in this repository.

**The detection floor column is why this result is worth more than the other nulls here.** Every
bucket's floor sits *below* the 2.0-point hurdle, so each row could have seen a tradable effect and
none did. Compare `power-and-sizing.md`, where seven of fifteen earlier studies had floors of 4 to
15 points and their nulls said nothing. This one says something.

## What this means for production

**Keep the single window.** The change would add code, add levels, and add no information, and the
measurement is powered well enough to say so rather than to be agnostic.

Two narrower conclusions worth keeping:

* **Window length is not a free parameter worth sweeping** on this construction. If a future
  change wants more level diversity, the interval ladder is where it already comes from, and
  adding an interval is cheaper than adding a window dimension.
* **Cross-window agreement is not a strength filter.** It was the plausible version of the
  proposal - a level everything agrees on ought to be stronger - and it is flat across four
  buckets and 130,000 touches. `prominence_bps`, which `pips.py` already records, remains the only
  strength measure here that has not been tested this way, and it is the one worth trying if
  anything is.

## Provenance and the honest caveats

`pips.as_of` is used throughout, so only points confirmed by the decision bar enter a level set -
without that filter a level drawn at a swing the future has already revealed would be respected
beautifully and mean nothing.

Levels are recomputed every 24 bars rather than every bar, which matches how `Series.due` reforms
in production but means a level can be up to 24 bars stale when touched. A per-bar recomputation
would be more faithful and about twenty times slower; the staleness cuts against the proposal's
case only mildly, since all four buckets share it.

The first version of this harness folded the whole prefix inside the loop, which is quadratic and
would not have finished. Folding each interval once and locating the decision bar by timestamp is
the same measurement in linear time.
