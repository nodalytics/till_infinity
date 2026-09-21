# Do the holdable spreads pay? — not measured

**Status: a measurement nobody has taken.** The series exist; the question does not have an
answer.

## Why this is the most important open question here

[`constructing.md`](../docs/constructing.md) contains **the only positive directional result in
this repository**, and it is not close:

| | AUC | hit rate |
|---|---|---|
| constructed cross-venue spreads (8 series) | **0.6985** | ~0.82 |
| the same assets as outright prices (7 series) | **0.5031** | ~0.51 |

Same days, same bars, same detector, and independently replicated at 0.67-0.73 in
[`zma.md`](../docs/zma.md) with spreads built a different way.

Set that beside what this session measured. `costs.md`, `stop-free.md`, `breakout-runs.md`,
`stretch.md`, `detectors.md` and `pip-windows.md` are all studies of **outright single-venue
prices** - the 0.5031 column - and all of them landed there. Dozens of transformations of one
series, every one within a point or two of fair odds, while the one thing that ever read
*relative* pricing between venues sat at 0.70 and was not revisited.

That is the structural lesson in [`more-mathematics.md`](more-mathematics.md) arriving from the
other direction: a new transform of one series cannot add information, and cross-venue pricing is
not a transform of one series.

## The wall, which is already documented and is real

**The 0.70 spreads cannot be held by this account.** A `venue` spread is the same asset at two
venues, `+1` and `-1` in logs; holding it means a position at each and this desk has one broker.
`Spread.tradeable` is `False` for every row in that table, and [`crossing.md`](../docs/crossing.md)
measured the same wall from the other side: **90.2% of cross-venue deviations belong to a venue the
desk cannot hold.** Those series are built to be measured.

So the open question is not "does the 0.70 pay". It is whether the **holdable** kind carries any of
it.

## The holdable kind, and the prediction

A `cross` spread is two dollar pairs at **one** venue, which is an implied cross exactly:

    ln(EURUSD) - ln(GBPUSD) = ln(EURGBP)

No residual, no fitted ratio, verified against the real level at 0.85476. Two orders, one account,
so it **is** holdable. `constructing.md` says in terms: *"whether it is worth its two spreads is not
answered here."*

**The prediction, recorded before the run, is that it does not carry the edge - and the reason
matters more than the answer.** A `venue` spread reverts *by arbitrage*: two venues quoting one
asset must converge, and the deviation is a mispricing with a mechanism forcing it shut. A `cross`
spread is not a mispricing at all. It is EURGBP - a real instrument with its own order book, whose
outright behaviour is precisely what the 0.5031 column measures.

So the 0.70 is not a property of "spreads". It is a property of **arbitrage residuals**, and the
account cannot hold arbitrage residuals. If that is right, the positive result is structurally out
of reach rather than merely expensive, and saying so cleanly is worth the run.

**What would falsify the prediction**: the cross series scoring materially above 0.53 on the same
detector and the same bars. If it does, the reversion is not purely arbitrage and there is
something here worth the execution work.

## What the run has to charge

This is where the machinery built this session earns its place. `asking.md` lists the
AUC-versus-money gap as outstanding and `constructing.md` explicitly does not close it. **An AUC of
0.70 on the next bar's sign is not money**, and a two-leg position pays:

* **two spreads, not one.** Both legs are crossed on entry and on exit.
* **two lots of financing.** Both sides are held; `costs.md` found the synthetics charging 36% a
  year as an annual percentage of notional, and the FX legs charge swap in points on both.
* **the joint stop.** `trading` places one order per signal; a spread needs a stop, target, size
  and cost model that are joint rather than per-leg, and `prices.spreads.definition(feed)` exists
  for exactly that execution path with nothing reading it yet.

So the headline number must be **expectancy net of both legs' costs**, not an AUC. The break-even
arithmetic from `power-and-sizing.md` applies with the cost roughly doubled: at reward-to-risk one
with two FX spreads and the measured 0.063 of slippage, break-even lands near **53%** rather than
52%, so the hurdle is about **+3 points** over fair odds.

And the detection floor comes first, per `power.py`: at +3 points a single hypothesis needs about
**2,200 resolved trades**. `constructing.md` scored 5,599 bars at 1m across eight series, so this is
comfortably answerable - which is why it should be answered.

## Three more ideas worth carrying, from the same source

From a prediction-market system of mine elsewhere. Each is filtered on the same question: does it
add a sensor, or re-express the series?

**Model-versus-market divergence.** Compare the desk's own forecast to a price the market makes.
This is a genuine second sensor and the pieces exist: `vol/implied.py` and
[`implied.md`](../docs/implied.md) carry implied volatility, and `har.py` forecasts realised. The
gap between forecast realised and implied is the variance risk premium - a quantity with an
economic reason to be non-zero, unlike anything measured this session. Nothing here has looked at
it.

**Cascade detection across venues.** The `Consensus` class already folds every venue's bar in and
takes the median, then **discards the dispersion**. That is the same shape as `history.py`
discarding the `spread` field - a measured quantity thrown away at the point of collection. Venue
disagreement and which venue moves first are information the median deletes, and it costs nothing
to keep. This is the cheapest sensor addition available.

**Pre-registration as standing practice.** That system writes a pre-registration document before
running a study. `jump_odds.py` and `norm_variance.py` did this informally here and both
predictions failed, which is exactly why it is worth doing - a prediction that fails is only
informative if it was written down first. Combined with `power.py` computing the detection floor
before the run, that is a two-item checklist that would have caught most of this session's
artefacts.

## What is deliberately not carried over

Whale and large-order detection, and order-flow absorption: both need depth the bridge does not
serve. They are the same blocked acquisition as the tick data that would narrow the slippage
bracket in `costs.md`, and they belong in the same queue rather than in a harness.
