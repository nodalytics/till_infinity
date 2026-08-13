# Key price levels

Where price has turned before, how sure we are it turns *there*, and what it
did last time it arrived — from that side.

```bash
uv run till-infinity structures watch --redis redis://localhost:6379
```

The output is not "this level will hold". It is:

> given price arrived from **this side**, P(pushed up) is *p*, and the expected
> push is *n* volatility units — against a base rate of *q*

Both halves matter. A 55% chance of a push worth 0.1 volatility units is not
worth acting on; a 55% chance of two volatility units might be.

---

## 0. What a "volatility unit" is

Every distance in this document is quoted in **volatility units**, written
`v`. One volatility unit is **the size of a typical recent move** for that
instrument, on that timeframe, right now.

It is a ratio, so it has no dimension of its own:

```
1v  =  the current volatility estimate, in basis points
```

and the current estimate is the exponentially-weighted mean absolute return
(§4). So converting is one multiplication:

```
basis points  =  volatility units x current volatility (bps)
per cent      =  basis points / 100
price         =  per cent / 100 x price
```

### The chain of units

| unit | meaning | example on gold at 4400 |
|---|---|---|
| 1 basis point (bps) | one hundredth of a per cent, `0.0001` | $0.44 |
| 1 per cent | 100 bps | $44.00 |
| **1 volatility unit** | one typical move — **however big that is today** | see below |

Basis points and per cent are **fixed**: 1bps is always 0.01%. A volatility
unit is **not fixed** — it is whatever a normal move happens to be at the
moment you ask.

### A worked example

Gold, 5-minute bars, with the volatility estimate reading `4.68bps`:

| | volatility units | basis points | per cent | price at 4400 |
|---|---|---|---|---|
| a typical 5m move | 1.00v | 4.68 | 0.047% | $2.06 |
| the level zone floor | 0.35v | 1.64 | 0.016% | $0.72 |
| a push worth acting on | 0.50v | 2.34 | 0.023% | $1.03 |
| the call at 4401 above | 1.78v | 8.33 | 0.083% | $3.67 |
| a decisive break | 2.00v | 9.36 | 0.094% | $4.12 |

Now the same numbers during a violent session where volatility has risen to
`25bps`:

| | volatility units | basis points | per cent | price at 4400 |
|---|---|---|---|---|
| a typical 5m move | 1.00v | 25.0 | 0.25% | $11.00 |
| a decisive break | 2.00v | 50.0 | 0.50% | $22.00 |

**Nothing in the model changed.** "A decisive break is 2v" held in both
sessions, while the basis-point number it corresponds to more than quintupled.
That is the entire reason for the unit.

### Reading it

| | |
|---|---|
| `0.2v` | inside the noise; price does this constantly |
| `0.5v` | half a typical move — the floor for a call being worth anything |
| `1v` | one typical move |
| `2v` | twice a typical move — a decisive break |
| `4v` | far outside normal; this is the anomaly detector's threshold |

### Why not just use basis points

Two failures it avoids, both of which look fine until they do not:

**Across instruments.** Gold moves ~5bps in five minutes, BTC ten times that,
EURUSD less. A single "wide spread" or "big push" threshold in basis points is
simultaneously too tight for one and too loose for another, so a model tuned on
gold silently mis-reads BTC. In volatility units they share one number.

**Across time.** A level learned in a calm January and consulted in a violent
June is consulted with January's expectations. A 20bps push meant "large" then
and means "ordinary" now, so the level's own history would stop describing the
level. Dividing by current volatility keeps the record comparable with itself.

Signed throughout: **positive is up**, negative is down, regardless of which
side price arrived from. A consumer wants to know which way to lean, not
whether the level "won".

---

## 1. Finding the swings: Perceptually Important Points

A price series has thousands of bars and perhaps a dozen turns that matter. PIP
finds those turns by repeatedly keeping whichever point sits furthest from the
line joining the points already kept.

Start with both endpoints. Then, until there are enough points, add the index
maximising the vertical gap to the chord between its two current neighbours:

```
        p[b] - p[a]
ŷ(i) = p[a] + ─────────── · (i - a)          gap(i) = | p[i] - ŷ(i) |
                 b - a
```

where `a` and `b` are the kept points either side of `i`.

**Why vertical and not perpendicular.** Time and price are different units, so a
perpendicular distance depends on the aspect ratio of an imaginary chart —
rescale the x-axis and the "important" points change. Vertical distance asks how
far price was from where a straight line between its neighbours said it should
be, which is a question about price alone.

A kept point is a **high** if it is above both neighbours, a **low** if below,
and an **edge** otherwise. Only highs and lows can carry a level.

## 2. Point-in-time correctness

The failure that does not show up until the numbers are being trusted.

A turning point is not recognisable as one until the bars *after* it have
printed. A PIP found in a window that includes future bars was not knowable
when it formed, so levels built from it are levels nobody could have drawn —
and every measurement against them flatters itself.

Every point therefore carries `confirmed`, the timestamp of the bar that settled
it, and `as_of(points, t)` filters to what was visible at `t`.

```python
confirmed = times[i + confirm]     if i + confirm <= last
          = ∞                      otherwise
```

**The infinity is the whole thing.** An earlier version clamped confirmation to
the end of the window, which let a swing one bar from the edge claim to be
settled after one bar instead of three — and trailing swings are precisely the
ones that have not earned it. That bug survived a test that looked correct.

The test that caught it deletes the `as_of` guard and asserts the suite fails.
A look-ahead test that still passes with the protection removed is proving
nothing, which is worth checking for directly rather than assuming.

## 3. The level is a Kalman state, not a line

Price turned somewhere near a level a dozen times and never at exactly the same
place. Each of those turns is one **noisy observation** of where the level
actually sits, so a level is a latent state with a mean and a variance.

One touch, one update:

```
predict     P ← P + q²·Δt                     (levels drift, slowly)
gain        K = P / (P + R)
update      x ← x + K·(z - x)                 z = where price actually turned
            P ← (1 - K)·P
```

This is what lets a level **be pushed up or down by what price does**, without
anyone choosing a smoothing constant. The gain weights a new touch by how
uncertain the level currently is against how noisy the observation is:

| | K | effect of one touch |
|---|---|---|
| twenty consistent touches | small | barely moves |
| formed yesterday | large | moves a long way |

An exponential average needs an α picked in advance and is wrong at both ends of
that range. Here the adaptation rate is *derived*.

**The variance is the zone.** Confidence and width come from the same
arithmetic — a level we are sure about is a thin band, one inferred from three
scattered touches is a wide one:

```
half-width = clamp(2σ, 0.35v, 3.0v)
```

Observation noise `R` scales with volatility, so in a violent market the price
at which price turned says less about where the level is — and the filter
believes it less, automatically. That is the volatility-widening of the zone,
with no separate rule.

Uncertainty also grows with time untested (`q²·Δt`), so a level nobody has
touched for a month widens back into a guess.

## 4. Where the volatility number comes from

§0 defines the unit; this is how the denominator is estimated.

Volatility is the exponentially-weighted **mean absolute return**, in bps:

```
m ← m + α·(|r| - m)          α = 1 - exp(ln(0.5) / half_life)
```

Mean absolute deviation rather than standard deviation: the question is "how big
is a normal move", and for fat-tailed returns the MAD answers that more stably
than a variance a single outlier can dominate. Exponential rather than a rolling
window because a window has an edge — a violent bar leaves the average abruptly
N bars later and the zone jumps for no reason anyone can point at.

There is a floor (0.05bps). Without one, an instrument that has not moved for an
hour gets a near-zero volatility and every subsequent tick becomes a
hundred-sigma event.

## 5. A level does different things from each side

The important asymmetry, and the reason the answer is a direction rather than a
verdict. The same price met from below and met from above are two different
objects: one is a ceiling being tested, the other a floor.

So every statistic is kept **per approach side**. On synthetic data the same
level reads:

| | from **above** | from **below** |
|---|---|---|
| P(up) | 80% (vs 52% base) | 0% |
| expected push | +1.01v | −1.68v |

Push is **signed and in volatility units** — positive is up. Summing signed push
rather than counting rejections is deliberate: two rejections of very different
size are not the same evidence, and a direction with no magnitude cannot be
sized or compared against the cost of being wrong.

## 6. Levels break, and the tide changes

A level that rejected ten times in January and broke three times last week is
not a rejecting level. Counts are therefore **floats carrying an effective touch
count**, discounted three ways:

| decay | when | why |
|---|---|---|
| `0.5^(days / 21)` | on every touch | evidence ages; markets change |
| `× 0.25` | a break beyond 2 volatility units | a level that just conspicuously failed should stop predicting a bounce |
| `× 0.4` | the drift detector fires for this instrument | its behaviour was learned in a market that no longer exists |

Discounted, never erased — the level is still there, and a hard cut-off would
make it forget abruptly on an arbitrary boundary, with the estimate jumping for
a reason nobody could point at.

That third row is where `structures`' regime detection earns its keep: ADWIN
noticing the volatility regime changed now has a consumer.

States: `fresh → tested → broken → flipped`. **Flipped** — broken, then
respected from the other side — has its own state because it is a *repeating
structure*, which is the thing this package exists to notice.

## 7. Turning history into a direction

Two sources of evidence, and an honest weighting between them.

A level touched twenty times knows its own behaviour. A level formed yesterday
knows nothing — but it *resembles* levels that have been touched hundreds of
times, and that resemblance is real evidence.

**Own record** — beta-binomial, shrunk toward a prior:

```
P(up) = (π·w + ups) / (w + touches)
```

Three touches that all went up is not 100%. Reporting it as such is how a system
talks itself into a trade it has no evidence for.

**Neighbours** — kNN over resolved touches at *other* levels, distance-weighted
so a close neighbour counts for more than a distant one, over five scale-free
features plus a pivot flag:

| feature | |
|---|---|
| `approach_vol` | speed into the level, volatility units per bar |
| `depth_vol` | how far into the zone it pushed |
| `strength` | the level's own quality, [0, 1] |
| `run_vol` | how far price had already travelled in this leg |
| `experience` | log-compressed touch count |
| `pivot` | 1.0 for a pivot, 0.0 for a swing level |

**Side is a hard constraint, not a dimension** — distance is infinite across
sides, because a floor's history must never vote on a ceiling's future.

**Shrinkage between them**, so a level's own history takes over as it earns one:

```
w = touches / (touches + 4)
P = w · own + (1 - w) · neighbours
```

With no touches this is entirely the neighbours' answer. That is the cold-start
fix: a brand-new level gets a prior instead of a shrug.

## 8. What stops it fooling itself

Every conditional is reported beside the **base rate** — the unconditional
chance price went up over the same horizon. A level where P(up | touched from
below) equals the base rate has told you nothing, however confident the number
looks.

`edge = P(up) − base_rate`, and a call is `actionable` only with **all three**:

| guard | without it |
|---|---|
| ≥ 8 observations | a big edge on three touches is noise |
| \|edge\| ≥ 0.08 | a large sample at the base rate is nothing |
| \|push\| ≥ 0.5v | a confident call worth a tenth of a volatility unit does not pay |

`chop` is kept as an outcome alongside reject and break. A model never shown
"nothing happened" will predict a move every time.

## 9. Pivots

Yesterday's high, low and close, plus the classic floor-trader set:

```
PP = (H + L + C)/3        R1 = 2·PP − L        S1 = 2·PP − H
R2 = PP + (H − L)         S2 = PP − (H − L)
R3 = H + 2·(PP − L)       S3 = L − 2·(H − PP)
```

plus `PH`, `PL`, `PC` — the prior range itself, which is watched more than the
computed pivots.

Two reasons they earn a place beside swing levels:

- **No look-ahead question at all.** Today's pivots are fully determined by
  yesterday. That makes them a clean control: if PIP levels do not outperform
  pivots, the swing detection is not earning its complexity.
- **They exist before the first touch**, which is when a level is most useful
  and a swing level knows least.

Sessions are UTC, and a session is only emitted once a bar from the *next* one
arrives — the same discipline the swing detection follows.

## 10. Level formation

Swings are clustered one-dimensionally: sort by price, merge neighbours within
`1.0` volatility units. Simple and correct for the shape of the problem — the
data is a line, so cluster boundaries are just the gaps in it, and k-means or
DBSCAN either need k chosen in advance or rediscover exactly this in more code.

Clustering in **volatility units** is what lets one tolerance work across gold,
BTC and EURUSD at once.

A cluster needs **three** distinct swings. Two is not enough: any two points
define a line, so a two-swing level is evidence of nothing.

**Fragmentation is the failure mode.** The first version produced 38 levels on a
series with two real ones — at that density every price is "at a level" and the
model predicts nothing. Three fixes brought it to seven:

- merge on the level's **own zone** rather than a fixed tolerance, so a
  confident level absorbs only what is close and an uncertain one absorbs more
  and tightens as a result;
- fold together levels whose zones overlap, carrying the history across, since
  levels drift as they learn and two can converge on one price;
- refuse two-swing levels.

Re-forming **merges into** the existing set rather than replacing it. A level
rediscovered is evidence about an old level, not a new one — replacing would
throw away the touch history that makes it worth anything.

## 11. Multi-timeframe confluence

A level on the 4h chart and one on the 15m chart at the same price are one
level at two resolutions, and each knows something the other does not:

| | knows |
|---|---|
| **higher** timeframe | that the level *matters* — it is a larger structure |
| **lower** timeframe | *where it is* — its swings cluster in a tighter band |

Fusing them is **inverse-variance weighting**, which is already the right tool
because every level carries a Kalman variance and a finer timeframe naturally
has a smaller one:

```
1/sigma^2  =  sum of 1/sigma_i^2
x          =  sum(x_i / sigma_i^2) / sum(1 / sigma_i^2)
```

So the finer timeframe dominates the position — *the lower you go, the more
precise you get* is not a rule anyone wrote, it falls out of the arithmetic.
The fused sigma is smaller than any member's, which is correct: several
timeframes agreeing is more evidence about where the price is than any one.

**Confluence is carried separately.** A price that is a level on 15m, 1h *and*
4h is a different object from one that appears only on 15m, and no
per-timeframe statistic can express that, so `depth` is its own term and lifts
strength as a multiplier. Averaging would let a weak 15m level drag down a
strong 4h one it merely sits beside.

**Significance follows the highest timeframe, precision the lowest.** A 15m
level breaking inside a 4h level that holds is an ordinary morning; letting the
finer timeframe overrule the coarser one on significance would invert the point.

Touch histories merge across members, because evidence at three resolutions of
one price is evidence about the same price — rather than three thin piles none
of which clears the bar alone.

## 12. Repeating structures

Levels answer *"price has been here before"*. This answers *"price has done
this before"*, and the two are independent: a double top is the same structure
at 4400 and at 95,000, on gold and on BTC, in January and in June. Nothing in
the level machinery can see that, because a level is a price and a shape is not.

A shape is the last five confirmed swings, normalised twice:

- **price** is z-scored, so the same shape at any level or any volatility is
  the same shape;
- **time** is dropped and only order kept, because two instances of a pattern
  rarely take the same number of bars.

That second point is what **dynamic time warping** exists for. Comparing
point-by-point would call a three-day double top and a three-hour double top
different shapes; DTW finds the order-preserving alignment minimising total
distance, so a stretched instance matches a compressed one:

| | normalised DTW distance | |
|---|---|---|
| peak vs a stretched peak | 0.196 | **match** |
| peak vs an inverted peak | 0.748 | no |
| peak vs a straight rise | 0.479 | no |

The Sakoe-Chiba band is not an optimisation detail: unconstrained warping will
align almost anything to almost anything, so without it the "matches" are
alignments rather than resemblances.

Searching many shapes across many instruments **will** turn up repeats by
chance — that is what multiple comparisons do. The guards are the same three
the level model uses, because it is the same failure: enough instances, an edge
clear of the base rate, and a move worth having in volatility units.

DTW is not a metric — it violates the triangle inequality — so the library is a
linear scan rather than a spatial index, which is honest at a few thousand short
sequences and would be complexity bought with nothing at this size.

## Honest status

Everything above is validated on **synthetic mean-reverting data**, where the
edges exist by construction. That tests the machinery — the filter, the decay,
the asymmetry, the guards — and says nothing about whether real levels predict
anything.

The [journal](journal.md) is now collecting the `(features, call, outcome)`
triples needed to answer that properly, which is also the precondition for
[`facto.py`](structures.md) and anything supervised.

## Reading

- Perceptually Important Points, and its use with dynamic time warping for
  prediction: *A prediction scheme using perceptually important points and
  dynamic time warping*; *Forecasting stock market trends using support vector
  regression and perceptually important points*.
- Reference implementations: [cmosongo/Perceptually-Important-Points](https://github.com/cmosongo/Perceptually-Important-Points),
  [intelie/python-fastpip](https://github.com/intelie/python-fastpip).

## Where the code is

| | |
|---|---|
| `structures/pips.py` | swing extraction, confirmation, `as_of` |
| `structures/volatility.py` | the unit everything is measured in |
| `structures/levels.py` | Kalman state, zones, per-side stats, decay, clustering |
| `structures/pivots.py` | sessions and the floor-trader set |
| `structures/reactions.py` | touch tracking, kNN, inference, the guards |
| `structures/engine.py` | bars and quotes in, calls out |
