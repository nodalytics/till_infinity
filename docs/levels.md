# Key price levels

Where price has turned before, how sure we are it turns *there*, and what it
did last time it arrived - from that side.

```bash
uv run till-infinity structures watch --redis redis://localhost:6379
```

The output is not "this level will hold". It is:

> given price arrived from **this side**, P(pushed up) is *p*, and the expected
> push is *n* volatility units - against a base rate of *q*

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
| **1 volatility unit** | one typical move - **however big that is today** | see below |

Basis points and per cent are **fixed**: 1bps is always 0.01%. A volatility
unit is **not fixed** - it is whatever a normal move happens to be at the
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
| `0.5v` | half a typical move - the floor for a call being worth anything |
| `1v` | one typical move |
| `2v` | twice a typical move - a decisive break |
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
perpendicular distance depends on the aspect ratio of an imaginary chart -
rescale the x-axis and the "important" points change. Vertical distance asks how
far price was from where a straight line between its neighbours said it should
be, which is a question about price alone.

A kept point is a **high** if it is above both neighbours, a **low** if below,
and an **edge** otherwise. Only highs and lows can carry a level.

## 2. Point-in-time correctness

The failure that does not show up until the numbers are being trusted.

A turning point is not recognisable as one until the bars *after* it have
printed. A PIP found in a window that includes future bars was not knowable
when it formed, so levels built from it are levels nobody could have drawn -
and every measurement against them flatters itself.

Every point therefore carries `confirmed`, the timestamp of the bar that settled
it, and `as_of(points, t)` filters to what was visible at `t`.

```python
confirmed = times[i + confirm]     if i + confirm <= last
          = ∞                      otherwise
```

**The infinity is the whole thing.** An earlier version clamped confirmation to
the end of the window, which let a swing one bar from the edge claim to be
settled after one bar instead of three - and trailing swings are precisely the
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
arithmetic - a level we are sure about is a thin band, one inferred from three
scattered touches is a wide one:

```
half-width = clamp(2σ, floor, 3.0v)      floor = max(0.35v, 6 ticks)
```

The floor is the larger of a fraction of a typical move and a few of the
smallest price changes the venue can quote - because on a coarsely quoted
instrument the second is bigger, and a band narrower than the price grid is a
rounding boundary rather than a zone. See §6b.

Observation noise `R` scales with volatility, so in a violent market the price
at which price turned says less about where the level is - and the filter
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
window because a window has an edge - a violent bar leaves the average abruptly
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

Push is **signed and in volatility units** - positive is up. Summing signed push
rather than counting rejections is deliberate: two rejections of very different
size are not the same evidence, and a direction with no magnitude cannot be
sized or compared against the cost of being wrong.

## 5b. The origin, and why it is not the extreme

Which price *is* the level? The obvious answer is the extreme - the high of the
swing, the low of the wick. It is the wrong one, and this is the single
correction that most changed what the model learns.

A leg of volatility comes into a level and a leg of volatility leaves it. The
**origin** is where those two meet: where the move in stopped and the move out
began. Most of the time that is the close of one bar sitting on the open of the
next. The extreme is somewhere past it - the distance price was pushed *beyond*
the turn before it turned.

```
        ╱╲   ← extreme (the wick's tip)
       ╱  ╲
──────•─────  ← origin (leg in ends, leg out begins)
     ╱
    ╱
```

The distinction matters because the two prices answer different questions:

- **the origin** is where the level *is*. Price turning here twice is the same
  level twice, and it is what the statistics in §5 and the Kalman update in §3
  are fed.
- **the extreme** is how far past it price was pushed getting there. That is not
  a second level; it is the **width of the first one**.

Feeding the extreme to the filter instead makes every level drift outward by
whatever the last wick happened to be, and makes two touches of the same level
look like two levels a wick apart.

### Planned: an origin spans periods, not bars

### The live path is already fine; the warm path is not

Worth stating because it inverts the obvious assumption. `Engine.observe_quote`
runs the touch check on **every** interval the instrument has levels at:

```python
for interval in self.intervals_for(feed):
    calls += self.check(feed, interval, float(mid), when)
```

So a daily level's touch is advanced by every quote, at tick resolution. Live,
origins are already located from the finest evidence there is - the
bar-boundary problem does not exist there.

`Engine.seed` is where it does. Warming replays stored bars through
`observe_bar`, which both **forms** levels for that row's interval and **runs
the touch check** at that interval's own resolution. So a daily level warmed
from daily bars gets daily-quantised origins - and since a cold start warms from
six-figure bar counts, that is most of what any level knows.

The fix is to split those two responsibilities, which `observe_bar` currently
does together:

1. **Form** levels for each interval from *its own* bars. Unchanged: PIP needs
   confirmed swings on the timeframe the level belongs to, and a daily swing is
   not visible in 3m data.
2. **Touch** every interval from the *finest* bars available, once, in time
   order - the replay equivalent of what `observe_quote` does live. A 1d level
   would then learn its origins at 3m resolution during warming, exactly as it
   does from quotes afterwards.

The trap to avoid is running both: the single pass already recorded touches at
each interval's own resolution, so simply adding a fine-bar pass on top would
count every interaction twice - the same double-counting that produced 591
effective touches, arriving by a third route.

**Done on 2026-08-14, and the trap that actually bit was a different one.**
`Engine.touch_interval` names the interval carrying the check and everything
else forms only. What the plan above misses is that **"the finest bars
available" is not a fixed series - it is whichever is finest *at that moment*.**

Venues keep far less fine history than coarse: Yahoo serves seven days of 1m
against decades of 1w, so a replay of a few hundred bars per interval covers
hours at 1m and years at 1w. Pinning the check to the globally finest series
therefore leaves every earlier era untouched. On gold, 1w and 4h opened **zero**
touches across 20,159 replayed bars, and `prune` keeps a level only once
`touches >= 1.0` - so their levels were dropped for never having been visited,
and twenty-one levels became four.

`Engine._eras` computes the handover from the replay before it starts: the
earliest timestamp of each interval, keeping the improvements, so the check
moves to 1d when 1d data begins and to 1m when 1m does. Each era is touched at
the best resolution that era actually has, which is what the plan meant.

Measured on the same history rather than argued: levels 20 → 21, touches median
2.0 → 2.9, max 11.1 → 14.0, and none at or above 100 in either - the absence of
inflation being what says the double-counting trap was avoided. Coarse levels
register interactions they previously could not see: 1d median 1.5 → 3.3, 4h
1.8 → 5.5, 15m 1.3 → 9.1.

**Mostly implemented, and this paragraph has been behind the code twice.**

**Both legs are run-segmented.** The leg in ends when price has come back off
its deepest point by `ARRIVAL_RUN_VOL`, and the leg out when it has come back
off *its* extreme by `DEPARTURE_RUN_VOL` - rather than either ending on the
first observation that fails to extend, which made the origin a property of the
sampling rate. A single non-extending tick is a pause, not a departure. The two
constants are separate because they answer different questions: the arrival
threshold decides where the level *is*, and the departure threshold decides how
much of what followed counts as this reaction.

**Origins are now located from the finest evidence available**, which was the
other half. Splitting `observe_bar` on 2026-08-14 means the touch check runs
from the finest series of each era against every interval at once, so a daily
level's origin is placed at minute resolution during a replay and at tick
resolution live, instead of being quantised to the timeframe that happened to
reveal the level. The measured effect is in the split's own entry:
1d levels went from a median 1.5 touches to 3.3, because interactions they
could not previously see now register.

**What is genuinely left** is the level *formation* side rather than the touch
side: swings are still bar extremes, so a level's price is still a property of
the sampling grid even though its origin is no longer. That is
[todo.md](todo.md) item 5, and it is written there as an experiment rather than
a feature because the outcome machinery can settle it.

The paragraph below describes what the original implementation did. It is kept
because the reasoning for the run intersection is the part worth having, not
because the bar-boundary behaviour survives.

The implementation located the origin at a **bar boundary** - the close of the
last bar in against the open of the first bar out. That is a convenient
approximation and it is not what the idea says.

The leg coming in and the leg going out are each *runs of volatility*, and a run
is not one bar. It can be six bars on the 3m, or most of a session, or a stretch
that only resolves into a single move when you step back to the daily. The
origin is where those two runs **meet** - the intersection of a period of
arrival with a period of departure - and only in the simplest case does that
intersection land on a bar boundary.

This has a consequence already visible in the data. If the origin were a
property of one bar on one timeframe, the same origin would not keep appearing
across timeframes - yet the confluence table routinely shows one price agreed on
by `1d+5m+3m`. That is what a run intersection looks like when it is measured
three times at three resolutions: the runs differ in length, the meeting point
does not.

So the origin should be located **per run**, not per bar:

1. segment the approach and the departure into runs - the same volatility-unit
   threshold the swing selection already needs, rather than a bar count;
2. take the origin as the boundary between them, which may fall *inside* a bar
   on the coarse timeframe and be visible exactly at a bar edge on a fine one;
3. keep the current close/open rule as the degenerate case, since it is what a
   run intersection reduces to when both runs are one bar long.

The reason this is worth doing rather than filing away: a bar-boundary origin is
quantised by the timeframe it was found on, so the *same* structure gets a
slightly different price on every timeframe, and the inverse-variance fusion in
§11 then spends its precision reconciling an artefact of the sampling rather
than a disagreement about the market. Per-run origins should make the
timeframes agree more sharply, and if they do not, that is evidence the
confluence being seen is coincidence.

### Which extreme, and it depends on the approach

A wick only runs *through* a level in the direction price was already going, so
the relevant extreme is fixed by the side of the approach:

| price arrives | it wicks | extreme used |
|---|---|---|
| from **above** | *down* through the level | the bar's **low** |
| from **below** | *up* through the level | the bar's **high** |

```
reach = low if side is ABOVE else high
```

Taking the high of a touch approached from above would measure the leg that
brought price *in*, not the overshoot - a number about the approach wearing the
name of the level.

### Wick depth, and the zone it defines

Depth is measured from the origin to the extreme, in volatility units (§0), so
it means the same thing on gold as on EURUSD:

```
depth = |wick − origin| / origin × 10⁴ / bps
```

and folded into a per-side EWMA, the same shape as everything else here - the
level's *recent* habit, not its lifetime average:

```
wick_vol ← 0.8·wick_vol + 0.2·depth
```

That number is one edge of the zone. And because it is recorded per approach
side, **the zone is asymmetric**: the side price keeps overshooting into is the
side that stretches.

```
half     = clamp(σ_kalman × 2.0,  0.35v,  3.0v)      ← §3, the filter's own doubt
lower    = price − min(max(half, wick_vol[from above]), 3.0v)
upper    = price + min(max(half, wick_vol[from below]), 3.0v)
```

Read the indices carefully - they cross on purpose. Touches coming **from above**
wick *downwards*, so they set the **lower** edge.

The floor and the two clamps each stop a different failure. `half` keeps a level
with no wicks yet from being an infinitely thin line nothing ever touches; the
0.35v floor keeps a filter that has become very confident from shrinking the
zone to nothing; the 3.0v ceiling stops one violent wick from turning a level
into a region so wide that everything is inside it.

### What this bought

Levels stopped drifting. Before the change, `observe_touch` was fed the extreme
and the Kalman mean walked away from the price that was actually being defended,
a fraction of a wick at a time. The zone was also symmetric, which said a
ceiling being tested and a floor being tested overshoot equally - they do not,
and the asymmetry is now a measured number per side rather than an assumption.

## 6. Levels break, and the tide changes

A level that rejected ten times in January and broke three times last week is
not a rejecting level. Counts are therefore **floats carrying an effective touch
count**, discounted three ways:

Every counter in a side's record is multiplied by the same factor, so the
*ratios* survive and only the weight changes:

```
n, rejects, breaks, chops, ups, sum(push), sum(push^2)   <-  all x f
```

Three factors compose:

| factor | when | why |
|---|---|---|
| `f = 0.5^(Δdays / 21)` | on every touch, for the gap since the last one | evidence ages; markets change |
| `f = 0.25` | a break with `\|push\| ≥ 2v` | a level that just conspicuously failed should stop predicting a bounce |
| `f = 0.4` | the drift detector confirms for this instrument | its behaviour was learned in a market that no longer exists |

Because counts are multiplied rather than dropped, `n` becomes an **effective
touch count** - a real number, not an integer - and every estimate downstream
gets age-weighting for free without knowing it exists.

Worked: ten rejections, then a three-month gap, then three breaks.

```
after the gap:   n = 10 x 0.5^(90/21) = 10 x 0.052 = 0.52
after 3 breaks:  n = 0.52 + 3 = 3.52,  ups = 0.52
P(up) = (0.5x4 + 0.52) / (4 + 3.52) = 0.33
```

The ten January rejections no longer outvote three breaks last week, which is
the entire point.

Discounted, never erased - the level is still there, and a hard cut-off would
make it forget abruptly on an arbitrary boundary, with the estimate jumping for
a reason nobody could point at.

That third row is where `structures`' regime detection earns its keep: ADWIN
noticing the volatility regime changed now has a consumer.

States: `fresh → tested → broken → flipped`. **Flipped** - broken, then
respected from the other side - has its own state because it is a *repeating
structure*, which is the thing this package exists to notice.

### Price is not continuous, and the zone floor assumes it is

`MIN_ZONE_VOL` puts a floor of 0.35v under a zone's half-width, which stops a
confident level becoming a line. It says nothing about the **smallest step
price can actually take**, and on a cheap instrument that turns out to matter.

Measured over 1,794 3m bars per feed, where "tick" is the smallest non-zero
change actually observed:

| feed | price | volatility | tick | tick in volatility units |
|---|---|---|---|---|
| btc | 63,138 | 9.70bps | 0.51 | 0.0083v |
| eth | 1,885 | 9.17bps | 0.005 | 0.0029v |
| gold | 4,387 | 1.04bps | 0.002 | 0.0044v |
| **sol** | **75.56** | 9.12bps | 0.005 | **0.0726v** |

sol carries the same volatility as btc and eth and **one eight-hundredth of the
price**, so its smallest quotable step is nine times btc's and twenty-five
times eth's as a fraction of a typical move. Against the 0.35v floor, one sol
tick is a fifth of a minimum-width zone: price steps across in five ticks where
btc needs forty.

**The consequence is more interactions, not different ones.** Every model here
assumes price is effectively continuous relative to the zones it is measured
against - that arriving in a zone and leaving it are distinguishable events
rather than consecutive quotes. That assumption degrades smoothly with price,
and sol is the first instrument cheap enough to break it.

**Checked against a price gradient, and sol turns out to be unremarkable.**
Eight instruments on one venue, same method:

| ticker | price | volatility | tick | tick in v | % of a minimum zone |
|---|---|---|---|---|---|
| DOGE | 0.07 | 5.64bps | 0.00001 | 0.254v | 72% |
| **ADA** | 0.18 | 8.84bps | 0.0001 | **0.628v** | **180%** |
| XRP | 1.00 | 6.16bps | 0.0001 | 0.162v | 46% |
| LINK | 8.85 | 9.37bps | 0.001 | 0.121v | 35% |
| **LTC** | 43.92 | 5.68bps | 0.01 | **0.401v** | **114%** |
| SOL | 75.49 | 5.36bps | 0.01 | 0.247v | 71% |
| ETH | 1,885 | 5.89bps | 0.01 | 0.009v | 2.6% |
| BTC | 63,158 | 4.94bps | 0.12 | 0.004v | 1.1% |

**Six of the eight have a tick worth more than a third of a minimum-width zone,
and two have a tick larger than the whole zone.** ADA's smallest possible price
change is 1.8 zones wide. For those instruments a level cannot be approached
gradually at all: price is either outside it or through it, and "arrived" and
"left" are the same quote.

**The obvious law is wrong, and worth recording as wrong.** If this were simply
about price, tick-in-volatility would go as its reciprocal - a log-log slope of
−1. Measured, the slope is **−0.33 with R² 0.71**. Exchanges set tick size in
decade steps rather than proportionally, so the ratio jumps between decades
instead of scaling within them: ADA at \$0.18 is worse than SOL at \$75, and LTC
at \$44 is worse than DOGE at \$0.07.

So the finding is broader and less tidy than "sol is cheap". **The continuity
assumption is satisfied by btc and eth and violated by most of the crypto
universe**, and which instruments violate it cannot be predicted from price
alone - it has to be measured per instrument, because it is a property of the
venue's tick table.

### The fix: a zone floor that knows about the grid

`Level.zone` now takes its floor as the larger of `MIN_ZONE_VOL` and
`MIN_ZONE_TICKS` (six) ticks either side, so a zone spans a dozen quotable
prices and an approach, a touch and a departure can be different quotes.

**The tick is measured, not configured.** `structures` has no route to the
venue's tick table - `prices` sees the quotes and does not pass it on - and a
configured number would go stale silently when an exchange re-tiers. Every
price sits on a grid and every change is a multiple of its step, so the
smallest non-zero change observed *is* the step, once enough have gone past.

Measured effect, on 300 3m bars per instrument:

| ticker | tick | zone before | zone after | |
|---|---|---|---|---|
| ADA | 0.0001 | 0.000111 | 0.000955 | **8.6x** |
| LTC | 0.01 | 0.017 | 0.120 | **6.9x** |
| DOGE | 0.00001 | 0.000028 | 0.000120 | 4.4x |
| SOL | 0.01 | 0.028 | 0.120 | 4.2x |
| XRP | 0.0001 | 0.000432 | 0.001200 | 2.8x |
| LINK | 0.001 | 0.0058 | 0.0120 | 2.1x |
| ETH | 0.01 | 0.777 | 0.777 | 1.0x |
| BTC | 0.12 | 21.84 | 21.84 | 1.0x |

It does nothing where price is already continuous relative to its zones and
widens only where the grid binds, which is the shape it should have.

**Two guards, and the first one I wrote was wrong.** A series that only ever
moves by one identical amount says nothing about the grid: "the tick is that
size" and "the tick is tiny and price is jumping" fit equally. My first guard
was "the tick must be small against a typical move" - which sounds right and
**rejects ADA**, the instrument this exists for, because there the tick
genuinely *is* most of a typical move. That is the whole problem, not evidence
against it.

What separates them is the spread of multiples: a real grid produces moves of
one step, then two, then five. A uniform jump produces only one. So the
estimate is withheld until `TICK_MULTIPLES` distinct multiples have been seen.

**The value is a low quantile, not the minimum**, and three estimators were
scored against each other to settle that. A tick divides every change price
makes, so a candidate can be checked without knowing the venue's tick table:
what share of observed changes are integer multiples of it.

| | clean data | after one spurious print |
|---|---|---|
| minimum | correct on 8/8 | **collapses on 8/8** - 0.01 to 0.0014 |
| **1st percentile** | correct on 8/8 | **unmoved on 8/8** |
| approximate GCD | degenerate on btc | collapses like the minimum |

The minimum is a one-observation estimator and behaves like one: a single bad
print a seventh the size of a real tick destroyed it everywhere, and this
number *widens a zone*. The GCD was tried on the sound reasoning that the tick
divides every change; it went degenerate on btc at 0.000064, which trivially
divides everything - a warning that the consistency score has to be read next
to the estimate rather than alone, since a small enough answer always scores
perfectly.

The two roles are now separate, which is what makes it robust: **the minimum
decides whether there is a grid, the quantile decides how wide it is.** A bad
print drags the minimum down, which only loosens the guard, while the quantile
it would have to move is defended by every other change.

It has a pleasing property. The quantile is *exact* on every instrument where
the floor binds - on those, most changes really are one tick - and overshoots
only on btc, where volatility dominates and the tick is never consulted. It is
accurate precisely where it is used.

**And the ceiling still wins.** The estimate is read off changes that have
*happened*, so an instrument yet to print a single-step move reads coarser than
it is, and the error is upward. `MAX_ZONE_VOL` bounds what that can do.

### That fix over-corrected, and the bound that stops it

The floor above is right in shape and was unbounded in size, which turned out
to matter more than the problem it solved. `MIN_ZONE_TICKS` is six, so a zone
is six ticks either side - sensible while a tick is a small part of a typical
move, and a disaster when it is not.

**On `sol` a tick is 0.378 volatility units**, so six of them is **2.27** -
wider than `resolve_vol`, the distance a touch must travel before it counts as
a rejection. A zone that wide catches everything. Measured over twenty-four
hours with bars counted over the same window, `sol 3m` produced **11,037
resolutions per thousand bars**: eleven per bar. sol alone was **half of every
outcome in the journal**, which is what gates `fit` in [todo.md](todo.md).

`GRID_ZONE_VOL` bounds the grid-derived part of the floor at **0.75**, half of
`resolve_vol`, so the venue's ladder alone can never open a zone wide enough to
resolve a touch inside it. The filter's own uncertainty and the observed wicks
may still push a zone past that - they are evidence about *this* level. The
grid is not; it is a fact about where the venue lets price sit.

Effect on `sol 3m`: **11,037 to 359 per thousand bars**, about thirty times.

### Some pairs cannot carry a level at any width

Bounding the floor fixed one end and exposed the other. A zone capped at 0.75
volatility units on an instrument whose tick is 0.378 is **two ticks across** -
which is the failure `MIN_ZONE_TICKS` was added for in the first place. Wide
catches everything; narrow is jumped over. There is no width in between.

So the pair is declined rather than tuned. `MIN_TICKS_PER_ZONE` is **four**,
and `Engine.supports(feed, interval)` refuses to form levels below it:

| pair | ticks per zone | |
|---|---|---|
| sol 3m | 2.5 | declined |
| **audusd 1m** | 2.7 | declined |
| eurusd 1m | 3.3 | declined |
| spx500 3m | 6.7 | kept |
| eth 3m | 14.0 | kept |
| btc 5m | 58.3 | kept |

Four because `depth_vol` - how far into the zone price pushed - is a feature,
and a feature with two distinguishable values is not one. It is also where the
measurement separates.

**It is not a crypto problem.** Five of the eight pairs declined on the
instance are FX: coarse pip quoting does what a cheap coin does. No instrument
is lost, only the resolutions it cannot carry - sol keeps 15m and coarser.

Applied at **startup**, not just at the next re-form. `reform` enforces the
same rule but a series only comes due every `REFORM_EVERY` bars, so a restored
15m series would carry levels it should not have for five hours. State read
from disk was formed under whatever geometry was current when it was saved,
which is exactly when this needs to be fast.

Judged on the **floor** zone rather than the observed one, which declines more:
wicks widen an established level, but a new level gets the floor and the
question is whether to form one at all. And silent about what it cannot judge -
a cold volatility estimate, or an instrument that has not yet printed a
single-step move, is missing evidence rather than evidence of a problem.

### Why the finely-quoted instruments do not need a better estimate

btc's estimate is 0.32 against a real tick nearer 0.12, because in 300 bars of
3m data btc never prints a single-tick move - most of its changes are hundreds
of ticks, so even the first percentile is several. **No estimator recovers a
tick the data never shows**, and that is a property of the data rather than a
flaw to fix.

It does not need fixing, and the margin says by how much. The floor only binds
when `MIN_ZONE_TICKS × tick` exceeds `MIN_ZONE_VOL × volatility`, so each
instrument has a factor by which the estimate could be wrong before anything
changes:

| | binds today | margin |
|---|---|---|
| ADA | yes | 10.8x past the threshold |
| LTC | yes | 6.9x |
| SOL | yes | 4.2x |
| XRP | yes | 2.8x |
| LINK | yes | 2.1x |
| **btc** | **no** | inert until **5.7x** larger |
| **eth** | **no** | inert until **6.5x** larger |

btc's estimate is roughly 2.7x too large and would need to be 5.7x too large to
matter. The design is robust there **by irrelevance rather than by accuracy** -
and that is the useful shape, because it means precision is only ever demanded
where the estimator is exact, which is the instruments whose changes really are
one tick.

### The unified resolution scale, tested and rejected

The tidier framing was to drop the special case entirely: since everything here
is measured in volatility units and the tick is a second scale, take
`resolution = max(volatility unit, tick)` as the instrument's real resolution
and let the zone floor fall out of it.

Measured, it does not work:

| | tick / vol unit | floor as shipped | floor under one scale | |
|---|---|---|---|---|
| ADA | 0.63 | 0.000600 | 0.000056 | **0.09x** |
| LTC | 0.40 | 0.060000 | 0.008736 | 0.15x |
| SOL | 0.25 | 0.060000 | 0.014173 | 0.24x |
| btc | 0.01 | 10.92 | 10.92 | 1.00x |

The tick never exceeds one volatility unit on any instrument - 0.63 at worst -
so `max()` always chooses volatility and the fix disappears. It compares *one*
tick against *one* volatility unit, where the floor that works compares six
ticks against 0.35 units: a ratio of seventeen. Recovering that means writing
`max(unit, 17 × tick)`, which is the same two constants with one fewer place to
read them. **The elegance was in the notation rather than in the model.**

Still a **candidate for the outcome rate specifically**: the granularity is
measured and the causal link to sol's 2,430 outcomes is not. But it is now a
measured property of six tracked-or-plausible instruments rather than a story
about one.

## 6b. One visit is one touch

A touch counter must measure how many times price *turned* at a level, not how
long it sat there. For a while it measured the second thing.

The bug was in the arming, not the counting. An interaction resolved, and the
level became eligible again immediately - so the next quote arrived with price
still inside the zone and no open touch, and a fresh touch began. It resolved,
and another began. One visit became one touch per quote for as long as price
loitered.

The damage was not a wrong number, it was a wrong number that looked like
confidence. A BTC level reached **316 effective touches in a day** - on an
instrument with 288 five-minute bars in one - and at 316 counts the
beta-binomial prior of §7 is swamped, so it reported **P(up) = 100%**, the exact
outcome the shrinkage exists to prevent. A level price hovered at outranked one
it reversed off hard, which is backwards.

So a level has to be **re-armed by price leaving its zone**:

```
resolved:            waiting ← price is still inside the zone
outside the zone:    waiting ← false
inside and waiting:  no new touch
```

A touch that resolved *by* price leaving re-arms at once. It has already done
the leaving, and requiring a second exit would drop the next real approach.

**Leaving the zone is not the same as going away from the level**, and the first
version of this fix missed the difference. Price sitting on a zone edge crosses
it constantly, so re-arming on any exit still counted one consolidation as
dozens of turns - a BTC zone read **337 effective touches** on a cold start,
after the flag above was already in place. Re-arming therefore needs distance:

```
re-armed when |distance from the level| ≥ REARM_VOL   (1 volatility unit)
```

In volatility units, so it means the same thing on a quiet 3m chart and a
violent daily one. This is the second half of the same bug, and it is worth
noticing that the first fix looked complete and was not: the flag stopped price
*loitering* from counting, and left price *hovering* untouched.

## 7. Turning history into a direction

Two sources of evidence, and an honest weighting between them.

A level touched twenty times knows its own behaviour. A level formed yesterday
knows nothing - but it *resembles* levels that have been touched hundreds of
times, and that resemblance is real evidence.

**Own record** - beta-binomial, shrunk toward a prior:

```
P(up) = (π·w + ups) / (w + touches)
```

Three touches that all went up is not 100%. Reporting it as such is how a system
talks itself into a trade it has no evidence for.

**The base rate is per `(feed, interval)`.** For a while it was not: one
pooled rate over the whole kNN memory served every call on every instrument and
timeframe, so GBPUSD on the daily and BTC on 15m were both reported against the
same 72%. That is wrong in a way that does real damage, because `edge` is
`conditional − base` and `actionable` gates on `|edge| ≥ 0.10` - a pool sitting
at 72% down hands every down call a twenty-point apparent edge and handicaps
every up call, on series that had nothing to do with the samples that set it.

The neighbours stay pooled, and that is not the same thing. The features are
scale-free precisely so a *conditional* can borrow evidence across instruments;
borrowing a conditional is not borrowing the thing it is supposed to be measured
against. A series' own rate is shrunk toward the pooled one until it has
`BASE_WEIGHT` (20) observations of its own, because a bucket with three touches
in it is not an estimate:

```
base(feed, interval) = (ups + 20·pooled) / (n + 20)
```

**There is no separate P(down).** It is `1 − P(up)`, exactly: a touch either
pushed up or it did not, so the beta-binomial's `β` term is `touches − ups` and
one counter carries both. (One wrinkle, invisible otherwise: a push of *exactly*
zero falls to the down side of `push_vol > 0`. Push is continuous in volatility
units, so this is measure-zero rather than a lean - but it is a tie broken by an
implementation detail rather than by evidence.)

What is reported, though, is the probability of **the direction being claimed**,
not always P(up). Printing P(up) beside a down call renders as `down p=23%`,
which invites reading 23% as the confidence in down when it is the confidence
against it. The same call now reads:

```
down p=77% (base 53%) push=-1.40v n=9.0+12
```

The base rate flips with it, because a conditional in one direction against a
base rate in the other is not a comparison - and it is exactly the shape most
likely to be quoted approvingly. `probability_up` keeps its meaning in the
journal and in `facto.py`, since the models are keyed on it; `probability` and
`base_rate` are the ones for a person. When the call is `mixed` (§7, win rate
and expected move disagreeing) this deliberately prints below 50%, which is the
honest rendering: the direction came from the push while the win rate points the
other way, and `mixed` sits next to it.

**Neighbours** - kNN over resolved touches at *other* levels, distance-weighted
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
| `backcheck` | 1.0 when this is a retest of a recent break |
| `regime` | where volatility sat in its own recent range, in [0, 1] |
| `up_rate` | **the share of this side's previous touches that pushed up**, [0, 1] |

`up_rate` is the only one of these that has been measured to earn its place,
and it was added late. [research/features.md](../research/features.md) dropped
each feature in turn and found that **none of the other eight predicts
direction once `side` is known** - while the level's own same-side record,
which was not among them, is worth +0.024 AUC on levels with three or more
prior touches. It had been hiding inside `strength`, diluted with three terms
[research/strength.md](../research/strength.md) shows separate nothing, and
behind `experience`, which counts touches without saying what they did.

0.5 means *no history*, not an even split. Those are different things and the
number cannot tell them apart on its own, which is why `experience` sits beside
it: the pair reads correctly together where either alone would mislead.

It is point-in-time by construction - `features_for` runs before
`Tracker.begin`, and the record is only written by `_close`, so a touch is
never in its own denominator. There is a test pinning that ordering, because a
refactor would break it silently and the symptom would be a model that looks
excellent and predicts nothing.

Distance is plain Euclidean over those nine, with side as a gate rather than a
term:

```
d(a, b) = inf                             if side(a) != side(b)
        = sqrt( sum_k (a_k - b_k)^2 )     otherwise
```

Adding `up_rate` there as well as to the model was a separate question, and was
measured separately: being worth predicting with and being worth comparing on
are different claims. Over a replay of the stored bars it takes the neighbour
vote's AUC from 0.797 to 0.813. Unweighted, like every other dimension -
weighting it two or four times over reached 0.816 and 0.819, which is not
enough to justify fitting a constant to two thousand touches.

The other eight stay despite predicting nothing, because they are cheap,
removing them is its own change with its own risk, and "does not predict
direction" is not the same as "does not identify a comparable touch".

`regime` is there because everything else is *scaled* by volatility, which
makes sizes comparable and deliberately erases what the market felt like. A
level held in a dead session is weaker evidence about a violent one than the
normalised numbers suggest, so the regime goes back in as its own dimension and
a touch is compared with touches from a market that felt the same.

**Side is a hard constraint, not a dimension** - infinite across sides, because
a floor's history must never vote on a ceiling's future. Contributions are
distance-weighted, so a close neighbour counts for more than a marginal one:

```
w_i    = 1 / (1 + d_i)
P(up)  = sum( w_i . [push_i > 0] ) / sum( w_i )
push   = sum( w_i . push_i )       / sum( w_i )
```

**Shrinkage between them**, so a level's own history takes over as it earns one:

```
w = touches / (touches + 4)
P = w · own + (1 - w) · neighbours
```

With no touches this is entirely the neighbours' answer. That is the cold-start
fix: a brand-new level gets a prior instead of a shrug.

### Certainty the evidence cannot support

Two places where an unsmoothed count would print a number nobody earned.

The **base rate** is Jeffreys-smoothed, `(ups + 0.5) / (n + 1)`, so it never
reaches 0 or 1. Everything else is shrunk *toward* it, so an unsmoothed 1.0
would propagate certainty into every conditional built on top of it.

The **kNN prior** is shrunk toward that base rate by neighbour count. Twelve
neighbours that all went the same way would otherwise return exactly 0.0, and a
level with no history of its own would inherit that and report it - a system
that prints "0%" from twelve observations will eventually print it about
something it is wrong about.

### When the win rate and the expected move disagree

They measure different things and can point opposite ways: a level that drifts
down four times in five and jumps hard on the fifth has a losing win rate and a
positive expectation. That is a real shape, not an error.

`direction` follows the **expected move**, because that is what a consumer acts
on, and the disagreement is surfaced as `mixed` rather than hidden. A mixed
signal is never `actionable`: whichever half you act on, the other says you are
wrong.

### Closed markets, and why the weekend is a data problem rather than an alert one

FX and the indices stop trading at the weekend; crypto does not. Two questions
follow, and only one of them was a problem.

**Alerts are structurally safe, by accident rather than design.**
`staleness_ratio` divides a venue's stillness by the *group's*, so when every
FX venue freezes together the ratio stays near 1 and nothing fires. The
cross-venue construction that exists to catch one dead feed also happens to
recognise a closed market. Level calls are safe for a different reason: a new
call needs a *new* touch to open, and a frozen price opens nothing.

**The outcomes were not safe.** A touch open at the Friday close stayed open,
and `_close` records `push_vol` as the distance at the moment of closing - so
the Sunday reopening gap would be written into the level's own statistics and
into `facto`'s training targets as this level's reaction to being touched. On
EURUSD a weekend resolved as a **27-volatility-unit rejection**, which is the
market having been shut rather than the level having done anything.

`GAP_FACTOR` (4× the horizon) discards those instead of resolving them, and the
check runs **before anything is read from the price** - placing it after the
movement tests, as the first attempt did, meant the gap was already being read
as a decisive rejection before the elapsed time was ever considered.

Discarding rather than recording is the honest answer: an interaction spanning
a period nobody observed has no outcome, and inventing one is worse than losing
it. Chop is deliberately kept - price arriving, sitting and doing nothing is a
real result, and a model never shown it predicts a move every time. Only the
absence of observation is thrown away.

**And "a frozen price opens nothing" turned out to be wrong.** The paragraph
above says a new call needs a new touch and a still price opens none, which is
true of the price and false of the system: the venues keep answering polls all
weekend. At 06:03 on a Saturday the FX quotes were sixteen minutes old while
the last 3m bar was **nine hours** old, and USDCNH and AUDUSD both published
directional calls - one of them `down 97%` on a market where nothing could go
anywhere.

`Engine.trading(feed, when)` judges on **bars**, because bars stop when a
market does and quotes do not. An instrument whose finest series has not
printed for `STALE_BARS` (four) of its own intervals is treated as closed, and
only the *opening* of a touch is gated: an open one must still be advanced so
`GAP_FACTOR` can discard it, and levels must still form. Crypto prints all
weekend and passes. An instrument with no series is not judged, because no
evidence of a closure is not evidence of one.

Four to match `GAP_FACTOR`, which makes the same judgement at the other end -
long enough that an ordinary thin session still counts as trading, short enough
that a weekend does not.

**A second cause of the same alerts was ours.** `_drain_expired` did not set
`level.waiting`, which the resolving path does. A touch expires precisely
because price sat at the level and went nowhere, so price is still there - and
a re-armed level opened another touch against the same visit on the very next
observation, with another call behind it. On a frozen price, where nothing can
ever resolve, that is a loop rather than a duplicate, which is why USDCNH
arrived twice at the same level with the same numbers.

### Venues that stop quoting, and the mid that must not follow them

Quotes get a cross-venue median for the same reason bars do (§11), and it needs
one thing bars do not: a venue that has stopped publishing must drop out.
`QUOTE_STALE` is **thirty seconds**. Without it a silent venue holds its last
mid in the median for ever, and on a fast move the consensus lags every venue
that is still live - the opposite of the problem the median exists to solve.

### The horizon was one number for eight timeframes

A touch that has not travelled `resolve_vol` within the horizon is chop. The
horizon was **3,600 seconds for every timeframe**, which is not one rule but
eight, because what it grants depends entirely on the chart:

| | bars allowed | | bars allowed |
|---|---|---|---|
| 1m | 60 | 1h | 1 |
| 3m | 20 | 4h | **0.25** |
| 5m | 12 | 1d | **0.04** |
| 15m | 4 | 1w | **0.01** |

**On 4h and coarser a touch expired before a single bar of its own timeframe
closed.** It could not resolve by price at all; only the clock could end it. A
daily level tested at noon had not failed to react by one o'clock - it had
barely been observed.

The chop rate follows the horizon exactly and not the market:

| interval | chop before | chop after |
|---|---|---|
| 1m | 0.2% | 4.0% |
| 5m | 2.1% | 2.1% |
| 15m | 13.7% | 2.4% |
| 1h | **73.4%** | 3.6% |

Overall chop fell from **27.9% to 3.3%** of outcomes, and the share of chops
coming from 1h or coarser fell from **91% to 27%**. On 1h the mix stopped being
a timer: 485 chops became 17, while rejects went 84 to 252, breaks 70 to 113
and back checks 17 to 47. Those outcomes existed all along and were being
labelled "price did nothing" because nobody had waited.

`HORIZON_BARS` is **twelve bars of the touch's own timeframe**, and `TRAP_BARS`
is six - the same numbers 5m already had at 3,600 and 1,800 seconds, so the
timeframe carrying most of the outcomes is unchanged and every other one is
corrected. Twelve is also where the first-passage arithmetic (§7d) puts roughly
73% of touches resolving by price, which is a defensible place to call the rest
chop.

The knob is `horizon_bars`, not `horizon`. `horizon` survives only as the
fallback for a touch whose interval is not a known timeframe, and passing it
expecting to shorten a 5m touch does nothing - which is worth stating because
four tests were doing exactly that and still passing.

**And the calls improved.** Direction went from 69.2% to 71.1%, and the deficit
against "assume the level holds" - the trivial rule that has beaten this model
everywhere ([features.md](../research/features.md) §3) - roughly halved, from
−7.1 points to −3.7. On about 1,850 calls against a standard error near 1.1
that is suggestive rather than settled, and the outcome population changed by
construction, so it is not a paired comparison.

## 7b. False breakouts

A trap is price getting through a level convincingly enough to invite the
breakout trade, and then giving it all back. It is not a shade of "break" and
not a shade of "reject" - the price action before it is a break and the price
action after it is a rejection - so a model with only those two words records
it as **a break that worked**, which is the opposite of what happened.

That is what this did until it was measured. On the stored history:

| outcome | | |
|---|---|---|
| chop | 535 | 74.3% |
| reject | 115 | 16.0% |
| break | 43 | 6.0% |
| **trap** | **27** | **3.8%** |

**27 of 70 breakout attempts were false - 39%.** All of them previously counted
as clean breaks, so the model was learning that breaking works about 1.6 times
more often than it does.

### A break is provisional until it survives

Which is how anyone trading one treats it. Price crossing `resolve_vol` beyond
the level no longer resolves the touch; it marks it `breaking` and starts a
clock:

- price comes back through the level by `TRAP_VOL` -> **trap**
- the clock runs out with price still beyond -> **break**

The push recorded for a trap is where price *ended*, not how far it went - a
breakout entry loses, and the number has to say so. How far it went is kept
separately as `excursion_vol`: what the trade was offered before it was taken
back.

### A trap is the level holding

Violently, after letting price through first. So a trap does not mark the level
broken and does not decay its history - this is the level doing exactly what it
did before, and the evidence is worth more, not less.

`trap_rate` is the number worth knowing before trading a break: of the times
price got through here, how often it was taken back. A level where half the
breakouts fail is not a level you break out of.

On the real history, `btc 63,678.75` (5m, from below) carries three effective
traps and **no** clean breaks.

## 7c. Back checks

The third thing that happens at a level, and the one worth the most.

Price breaks a level and the break holds. Price then comes back to that same
level - now flipped, old resistance become support - holds, and carries on the
way it broke. It sits between the other two:

| | momentum | entry | risk |
|---|---|---|---|
| breakout | proven | chasing | undefined |
| **back check** | **proven** | **pullback** | **defined by the flipped level** |
| false breakout | - | - | you were wrong |

Two conditions, and both are the definition rather than a threshold:

- the break must be **recent** - `BACKCHECK_BARS` of that timeframe, so a
  couple of hours on 5m and most of a year on 1w. A return three months later
  is a level, not a retest.
- price must arrive from the side it broke **to**. Arriving from the original
  side is the break failing late, which is a different event entirely.

A back check is recorded as *both* a reject and a back check: the level held,
and it held in this particular way. `backcheck` is also a kNN dimension, so a
retest learns from other retests rather than from first touches - a
continuation setup and a reversal setup are not the same population.

### Risk is the point

The reason this structure matters is that it defines the stop, so the trade is
finally comparable with any other:

```
stop            = beyond the zone, by STOP_BUFFER_VOL
risk_vol        = |price - stop| in volatility units
reward_to_risk  = |expected push| / risk_vol
```

The stop goes **beyond the zone**, not at the level. The zone is precisely the
band where price can sit and still be respecting the level, so a stop inside it
is a stop inside the noise - it gets hit by the level working.

**`reward_to_risk` stopped deciding anything on 2026-08-17.** It was measured
to invert the sign of the return - gating at 1.0 turned a mean realised push of
+0.496 into -0.268 across 11,113 calls, and end to end the 9.9% of calls
passing every gate returned -0.151 while everything the gate rejected returned
+0.569. The ratio correlates -0.359 with its own denominator, so a high value
is substantially a *tight stop*, and a tight stop sits inside the noise the
level is made of. See [magnitude.md](../research/magnitude.md). It is still
computed and reported; it is no longer a gate.

The reasoning it was built on follows, because it was the best-argued gate in
the set and it was still wrong. A 70% call
worth half what it risks is a losing trade; a 55% call worth three times it is
not.

### How often it actually happens

> **These counts were of the survivors.** `Engine.check` discarded what
> `Tracker.expire` returned, and expiry is where a break that got through and
> then went quiet resolves - so most breaks never reached the level, the
> journal or `facto` at all. Worse for this section specifically: `broke_at`
> is what makes a retest detectable as a back check, and it was only ever set
> on the path that already worked, so the back check count was measuring the
> bug rather than the market. Fixed in `04d24c0`; on a replay of the stored 5m
> bars, delivering these took breaks from 11 to 61 and back checks from 3 to
> 29. The table below is left as it was recorded, because what it counted is
> the point.

| | |
|---|---|
| breaks recorded | 43 |
| breaks ever revisited | **15** |
| back checks | **1** |

The reasoning still holds where it does not depend on the counts: most breaks
are never retested at all, which is what a break is, and a retest that drifts
sideways resolves as chop, which is correct, because a back check that produces
no move is not a tradeable one.

One occurrence is not evidence about anything, and neither is twenty-nine. The
mechanism is verified by construction in the tests; whether back checks pay is
a question for the journal once there are enough of them to ask, and the count
only started being collected honestly at the commit above.

## 7d. When price will get there

A level three volatility units away is not "near" or "far" - it is a distance a
walk has to cover, which is a **first-passage time** problem with a known
answer. The input is the distance in volatility units, which is exactly what
`distance_vol` already produces.

```
bars(q)  =  ( n / Phi^-1(1 - q/2) )^2

P(touched within N bars)  =  2 * ( 1 - Phi( n / sqrt(N) ) )
```

Both exact for Brownian motion, and neither needs anything beyond the normal
quantile function.

### Time goes as the square of distance

The single most useful thing here, because it is not what intuition offers:

| distance | median | slow (90th) | within 24 bars |
|---|---|---|---|
| 1v | 2.2 bars | 63 | 84% |
| 2v | 8.8 bars | 253 | 68% |
| 3v | 19.8 bars | 570 | 54% |
| 5v | 55 bars | 1583 | 31% |
| 10v | 220 bars | 6333 | 4% |

**Twice as far is four times as long, not twice.**

**The table above is corrected, and the correction is the interesting part.**
The reflection principle wants distances in **standard deviations**, and a
distance in volatility units is a distance in **mean absolute deviations** -
that is what `Volatility.bps` returns, chosen there because it is the more
stable estimator on financial returns (§0, §4). For a normal walk
MAD = σ·√(2/π), so every distance arrived a quarter too large and every
probability came out too low.

`timing.MAD_TO_SIGMA` is the conversion, and it was missing. The null was
right; the unit handed to it was not - which is the harder version to notice,
because it fails quietly and only in one direction. Measured against 22,219
bars of realised excursions, the old form quoted **7.4% at eight volatility
units where the truth is 17.4%**; corrected it tracks the realised curve across
the range, and the realised median excursion implies a per-bar σ of 1.24
against the factor's 1.253.

The test that guarded this asserted the 2.198 first-passage constant, which was
correct about the constant and silent about the unit, so it passed throughout.
It now converts explicitly and a second test pins the conversion itself.

### There is no average, and that is not pedantry

The expected first-passage time of a driftless walk is **infinite** - the tail
is heavy enough that the mean does not converge. Any "average time to reach"
would be an artefact of where the sample was cut, and would grow the longer you
collected data for. Quantiles are reported instead: a median and a slow case,
with the slow case reading `beyond` when it hits the bound rather than printing
a ceiling as though it were an estimate.

### Ordered by time, not distance

The clock differs by more than the distance does, so the orderings are not the
same. On live btc, a level at +0.13% on 15m ranks *behind* one at +0.13% on 5m,
because the same distance is 13 hours on one clock and 5 on the other.

### What it is not

Markets are not Brownian: volatility clusters, tails are fat, price trends.
This is the **null model** - what distance and volatility alone imply, before
anything about direction. A level reached far sooner than this repeatedly is
saying something, and the estimate is what makes "sooner" mean anything.

Drift is excluded deliberately. Estimating it from recent data is noisy enough
that a wrong sign makes the answer worse than the null, and the honest version
of "price is heading there" is the directional inference, which is a separate
question with its own answer.

## 8. What stops it fooling itself

Every conditional is reported beside the **base rate** - the unconditional
chance price went up over the same horizon. A level where P(up | touched from
below) equals the base rate has told you nothing, however confident the number
looks.

`edge = P(up) − base_rate`, and a call is `actionable` only with **all three**:

| guard | without it |
|---|---|
| ≥ 8 observations | a big edge on three touches is noise |
| \|edge\| ≥ 0.10 | a large sample at the base rate is nothing |
| \|push\| ≥ 0.5v | a confident call worth a tenth of a volatility unit does not pay |
| reward-to-risk ≥ 1.0 | a move smaller than the stop behind it loses more when wrong than it makes when right |

### The risk gate, and why it is a ratio

`MIN_REWARD_TO_RISK` is **1.0**, and that is a break-even rather than a
preference: below it the predicted move is shorter than the distance to the
stop, so the trade loses more when it is wrong than it makes when it is right -
before any question of how often it is right. It is the one number in
`actionable` that is not somebody's taste, which is why it sits there rather
than at 1.5 or 2.

**It gates on the ratio, never on `risk_vol`.** Risk is measured in each
timeframe's own volatility units, so the same figure means completely different
money depending on where it came from:

| timeframe | vol | `risk_vol` | in dollars |
|---|---|---|---|
| 1m | 0.35bps | 1.38 | $0.21 |
| 15m | 1.94bps | 0.90 | $0.77 |
| 1d | 63.05bps | 0.90 | $24.76 |
| 1w | 118.38bps | 1.08 | $23.18 |

0.90 is seventy cents on the 15m and twenty-five dollars on the daily. A
threshold on `risk_vol` would therefore mean something different on every
timeframe, which is the mistake §10b exists to prevent. The ratio divides the
units out and is the only part of this geometry that travels.

Those readings were taken while 1m was briefly a level timeframe; it is not
one today (see [todo.md](todo.md) item 0a), and the row is kept because the
hundredfold spread between the ends is the whole point.

**It is not free.** Measured across gold, btc and eurusd, the gate suppressed
**13 of 35** otherwise-actionable calls - 37%. What it removes is mostly large
moves sitting behind larger stops: a `+2.05v` push against a `3.50v` stop reads
as a strong call and is a losing one. One call was dropped at 0.969, which is
the boundary doing exactly what it says.

This gate could not have been written before `risk_vol` was fixed. Until then
`reward_to_risk` was identically zero, so it would have rejected everything.

### ~~0.08 is not derived from anything~~ - it is now, and it moved to 0.10

**Resolved on 2026-08-16.** The gate is `MIN_EDGE = 0.10`, derived in
[edge.md](edge.md) §1 from a step in realised outcomes: replaying every call
against the outcome of the touch it opened, the three lowest deciles of `|edge|`
run **54.8% to 61.5% direction with a mean realised push of zero**, and the
fourth - starting at **0.0968** - jumps to 69.3% and a push of 0.49. Nothing
after the step goes back.

Measured twice: 0.11 on six bands over 1,990 calls, then 0.0968 on ten deciles
over 10,483 calls across fourteen instruments. Both readings agree that 0.08
sat *inside the flat region*, so roughly a quarter of everything said out loud
was a coin flip.

The rest of this section is the record of why it was arbitrary, kept because
the reasoning is what led to the measurement.

---

Stated because it was the number deciding whether the channel speaks.
The guard is sound - a conditional equal to its base rate has said nothing -
but the *threshold* had never been justified anywhere: not in the commit that
introduced it, not here, not beside the code. It was a made-up tolerance of
exactly the kind this project otherwise refuses, and it was load-bearing.

On 2026-08-14 every recorded call but one failed this gate, with a median
`|edge|` of **0.0748** - five thousandths under the line. A threshold nobody
chose deliberately is separating signal from silence at the third decimal
place. Either it should be derived from something (what separation is
distinguishable from noise at a given number of observations, which is a
question with an answer) or it should be a rolling quantile of realised edges
rather than a constant. Until then, the honest description is: arbitrary.

**Where it sits in the distribution.** Across the 9,359 journalled outcomes and
the calls that predicted them:

| p10 | p50 | p75 | p90 | p95 | p99 |
|---|---|---|---|---|---|
| 0.0014 | 0.0182 | 0.0449 | 0.0711 | 0.0763 | 0.3277 |

Only **2.3%** of calls reach 0.08, so the gate sits near the 97.7th percentile
of its own input and admits about one call in forty-three. That is a defensible
place for a threshold to be - but nobody chose it to be there, and it is worth
knowing that moving it by 0.005 changes which side of it the median call falls
on.

### The attempt to derive it, and why it failed

The obvious move is to let the data set the number: bucket calls by `|edge|` and
see where realised outcomes start separating. Doing that on the pre-2026-08-14
journal produces a result that looks wonderful and means nothing.

Direction was called correctly on **99.9%** of 9,353 paired outcomes, and at
essentially every level of `|edge|` - 100.0% below the threshold, 98.6% above
it. Predictions ran 8,200 down to 1,153 up and outcomes 8,196 down to 1,163 up.
Two independent series with those marginals would agree about **78%** of the
time. Ninety-nine point nine is not skill.

The cause is the touch inflation described in
[handoff.md](handoff.md): when one grinding episode is counted as 171 separate
touches, the level's *history* and its *next outcome* are the same price action
counted twice. The model predicts down because it just went down 148 times, and
it goes down again because it is still the same move. Nothing leaked from the
future; the past was double-counted until it became the present.

**So the threshold cannot be derived from any data recorded before the touch
counting was fixed**, and neither can anything else - this is the concrete form
of the warning in [todo.md](todo.md) item 0 about examples recorded under
inflated counts, and the reason `fit` takes a `since=`. A near-perfect direction
column is a useful alarm to keep: it is what this class of contamination looks
like from the outside, and it would otherwise read as a triumph.

### The base rate is what actually closed the gate

The edges above were not small because the levels were uninformative. They were
small because the base rate had drifted to 92.6% down, and a conditional of
99.7% can only earn seven points against it. Watch one 3m level over
thirty-six seconds:

```
06:32:09  edge=-0.0799  touches=148.3
06:32:29  edge=-0.0748  touches=161.2
06:32:45  edge=-0.0712  touches=171.2
```

One touch every two seconds on a single level, and `edge` climbing in lockstep
as the count inflates. Touch counts in the hundreds are the double-counting
described in [todo.md](todo.md) item 1 - `structures levels` should read in the
tens - and this is what they cost: an inflated count feeds a lopsided base
rate, the base rate eats the edge, and the edge gate closes. The chain from a
miscounted touch to a silent channel is four steps long and every step looks
reasonable on its own.

`chop` is kept as an outcome alongside reject and break. A model never shown
"nothing happened" will predict a move every time.

## 9. Pivots

Yesterday's high, low and close, plus the classic floor-trader set:

```
PP = (H + L + C)/3        R1 = 2·PP − L        S1 = 2·PP − H
R2 = PP + (H − L)         S2 = PP − (H − L)
R3 = H + 2·(PP − L)       S3 = L − 2·(H − PP)
```

plus `PH`, `PL`, `PC` - the prior range itself, which is watched more than the
computed pivots.

Two reasons they earn a place beside swing levels:

- **No look-ahead question at all.** Today's pivots are fully determined by
  yesterday. That makes them a clean control: if PIP levels do not outperform
  pivots, the swing detection is not earning its complexity.
- **They exist before the first touch**, which is when a level is most useful
  and a swing level knows least.

Sessions are UTC, and a session is only emitted once a bar from the *next* one
arrives - the same discipline the swing detection follows.

## 10. Level formation

Swings are clustered one-dimensionally: sort by price, and start a new cluster
wherever consecutive swings are further apart than the tolerance -

```
gap(i) = | p(i) - p(i-1) | / p(i-1) x 10000 / vol_bps      (volatility units)

same cluster   if gap(i) <= 1.0
new cluster    otherwise
```

then seed each cluster's filter from its members:

```
x0  = mean(prices in cluster)
P0  = max( var(prices in cluster), (0.175v in price)^2 )
```

The variance floor matters: three touches at an identical price is luck, not
certainty, and a filter that starts at zero variance can never be moved again. Simple and correct for the shape of the problem - the
data is a line, so cluster boundaries are just the gaps in it, and k-means or
DBSCAN either need k chosen in advance or rediscover exactly this in more code.

Clustering in **volatility units** is what lets one tolerance work across gold,
BTC and EURUSD at once.

A cluster needs **three** distinct swings. Two is not enough: any two points
define a line, so a two-swing level is evidence of nothing.

**Fragmentation is the failure mode.** The first version produced 38 levels on a
series with two real ones - at that density every price is "at a level" and the
model predicts nothing. Three fixes brought it to seven:

- merge on the level's **own zone** rather than a fixed tolerance, so a
  confident level absorbs only what is close and an uncertain one absorbs more
  and tightens as a result;
- fold together levels whose zones overlap, carrying the history across, since
  levels drift as they learn and two can converge on one price;
- refuse two-swing levels.

Re-forming **merges into** the existing set rather than replacing it. A level
rediscovered is evidence about an old level, not a new one - replacing would
throw away the touch history that makes it worth anything.

### How strong is a level

```
strength = 0.40 x min(n, 10)/10          evidence
         + 0.25 x max(0, 1 - sigma/1v)   agreement - a tight zone
         + 0.20 x exp(-Δt / 14 days)     recency
         + 0.15 x min(swings, 5)/5       breadth
```

Age is deliberately **not** rewarded. An old level with two touches is not
strong, it is stale, and treating longevity as authority is how a chart ends up
covered in lines nobody trades.

## 10b. Volatility is per timeframe

The unit in §0 is *a typical move* - and a typical 4h move is not a typical 5m
move. Measured on gold:

> **The figures below are roughly half what they should be**, and by a factor
> that differs per instrument. They were measured through `Engine.observe_bar`,
> which updated the volatility estimate once per *venue row* rather than once
> per bar: `Consensus.observe` answers again on every venue that reports a bar
> so the median improves within a sweep, and each of those answers folded the
> same close in again, so the estimator read a run of zero returns between
> them. The estimate came out divided by the number of venues past quorum -
> four on EURUSD and GBPUSD, three on XAUUSD, two on BTCUSD, and only US500 at
> exactly quorum was right. Gold 1d measures 125.80bps per bar against the
> 63.17bps below. Fixed in `18e95c0`; the *shape* of the table is unaffected,
> since the error is a near-constant factor within an instrument, and the
> argument this section makes is about the shape. Anything comparing one
> instrument against another in volatility units is not safe to reuse.

| timeframe | volatility | 1v at 4400 | evidence half-life |
|---|---|---|---|
| 5m | 1.70bps | $0.75 | 0.9 days |
| 15m | 2.49bps | $1.10 | 2.6 days |
| 1h | 4.70bps | $2.07 | 10 days |
| 4h | 22.44bps | $9.87 | 42 days |
| 1d | 63.17bps | $27.80 | 250 days |
| **1w** | **118.70bps** | **$52.23** | **1750 days** |

Seventy times, end to end. A single estimate per instrument - in practice
dominated by whichever series updates most often - therefore makes every
threshold expressed in volatility units wrong for every timeframe but one.

The symptom was concrete: clustering swings at 1.0 volatility unit meant
grouping within **$0.86**, while the 4h window spanned seventy days over a $574
range. Swings at that scale essentially never clustered, so 4h produced almost
no levels at all - and the fault was invisible, because "few levels on the
highest timeframe" looks like a reasonable outcome rather than a broken
denominator.

So estimates are kept per `(instrument, timeframe)`, updated from that
timeframe's bars, and used for that timeframe's zones, clustering and pushes.

**Evidence ages on the same scale.** A single decay constant cannot serve both
ends either: twenty-one days is far too long for a 5m level - behaviour from
three weeks ago on a five-minute chart is not evidence about now - and far too
short for a weekly one, which might be tested a handful of times a year and
would forget each touch before the next arrived. The half-life is anchored to
the window instead, so evidence halves over roughly half the history that
timeframe can see. A 1w gold level at 1806 still carries 6.4 effective touches
from years back, which is correct and would be zero under a fixed constant.

**One exception, and it is deliberate.** Cross-timeframe questions - which
level is nearest, is this one worth acting on - need a single denominator, or
"three volatility units away" means something different for every level and
they cannot be ranked against each other. That is the **reference** estimate:
the tick-level one fed by quotes, falling back to the finest timeframe with
data when no quotes have arrived, which is the case when warming from bars.

### Risk is per timeframe, and therefore not comparable across them

`risk_vol` - the distance from price to the stop beyond the flipped level - is
measured in the volatility of the timeframe the level belongs to. That is
correct, and it has a consequence sharp enough to be worth its own heading,
because the number *looks* comparable and is not. Measured on gold:

| timeframe | volatility | `risk_vol` | what that is in money |
|---|---|---|---|
| 1m | 0.35bps | 1.38 | **$0.21** |
| 5m | 0.72bps | 1.15 | $0.36 |
| 15m | 1.94bps | 0.90 | **$0.77** |
| 1h | 4.52bps | 1.17 | $2.15 |
| 4h | 21.37bps | 2.09 | $18.00 |
| 1d | 63.05bps | 0.90 | **$24.76** |
| 1w | 118.38bps | 1.08 | $23.18 |

The `risk_vol` column is nearly flat - between 0.9 and 2.1 across a hundredfold
range of volatility - because the stop sits a fixed number of volatility units
beyond the level by construction. The money column spans **a hundred and
twenty times**. Two levels both reading 0.90 are seventy-seven cents on the 15m
and twenty-five dollars on the daily.

So:

- **Never rank or threshold on `risk_vol` across timeframes.** It is a
  within-timeframe quantity. Doing so would repeat the fixed-tolerance mistake
  this whole section exists to correct, one layer up.
- **`reward_to_risk` is the quantity that travels.** Expected push and risk are
  both in that timeframe's units, so the ratio divides them out and is
  dimensionless. A 2:1 call is a 2:1 call on the 1m and on the 1w. That is why
  `actionable` gates on the ratio and not on the risk - see §8.
- **To compare risk across timeframes, convert to money or to reference units
  first.** `vol.price_units(price, risk_vol)` is the conversion, and it is what
  produced the table above.

Nothing consumes `risk_vol` cross-timeframe today. It is written down because
the next thing that wants to - a sizing rule, a ranking of open calls, a
portfolio view - will reach for it, and the number will look like it means one
thing while meaning seven.

## 11. Multi-timeframe confluence

A level on the 4h chart and one on the 15m chart at the same price are one
level at two resolutions, and each knows something the other does not:

| | knows |
|---|---|
| **higher** timeframe | that the level *matters* - it is a larger structure |
| **lower** timeframe | *where it is* - its swings cluster in a tighter band |

Levels are grouped by **zone overlap**, each zone computed in its own
timeframe's volatility. Not by a shared tolerance: a tolerance is necessarily
expressed in one timeframe's units, and with 4h at thirteen times 5m a shared
one meant a 4h level had to sit within about fifty cents of a 5m level to count
as the same price. Nothing ever combined, and the zero looked like a market
observation rather than a bug.

A level's zone already encodes how precisely its timeframe can place it, so two
levels describe one price when their zones overlap - the same test `dedupe`
uses within a timeframe, applied across them.

Fusing them is then **inverse-variance weighting**, which is already the right
tool because every level carries a Kalman variance and a finer timeframe
naturally has a smaller one:

```
1/sigma^2  =  sum of 1/sigma_i^2
x          =  sum(x_i / sigma_i^2) / sum(1 / sigma_i^2)
```

So the finer timeframe dominates the position - *the lower you go, the more
precise you get* is not a rule anyone wrote, it falls out of the arithmetic.
The fused sigma is smaller than any member's, which is correct: several
timeframes agreeing is more evidence about where the price is than any one.

**Confluence is carried separately.** A price that is a level on 15m, 1h *and*
4h is a different object from one that appears only on 15m, and no
per-timeframe statistic can express that, so `depth` is its own term.
Averaging would let a weak 15m level drag down a strong 4h one it merely sits
beside, so the zone is worth its best member.

> **It no longer lifts strength as a multiplier.** `depth` used to add 15% per
> extra timeframe, so a 4-deep zone was scored 45% above its best member.
> Measured against whether the level then held, over four replays, breadth
> does not separate at all: four runs produced four different orderings, AUC
> 0.45-0.51, and a bootstrap over levels put the spread at -2.2 points
> [-6.3, +1.7]. See [strength.md](strength.md). The multiplier is gone; `depth`
> and `timeframes` are still reported, because the object really is different
> even if the difference does not predict holding. This ordered what the agents
> are shown and what the CLI prints, so it was a live decision rather than a
> display detail.

**Significance follows the highest timeframe, precision the lowest.** A 15m
level breaking inside a 4h level that holds is an ordinary morning; letting the
finer timeframe overrule the coarser one on significance would invert the point.

Measured on stored history:

```
btc      63500.18  [1h+15m+5m]  span=1h  precision=5m  6.7 touches  strength 0.90
eurusd       1.15  [4h+5m]      span=4h  precision=5m  8.9 touches  strength 0.83
```

Gold has none, and that is a real answer rather than a failure: it has been
trending, so its timeframes describe different price ranges and there is
nothing at one price for them to agree about.

Touch histories merge across members, because evidence at three resolutions of
one price is evidence about the same price - rather than three thin piles none
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

Normalising is z-scoring:

```
z(i) = ( p(i) - mean(p) ) / stdev(p)        zeros if stdev ~ 0
```

That second point is what **dynamic time warping** exists for. Comparing
point-by-point would call a three-day double top and a three-hour double top
different shapes. DTW finds the order-preserving alignment minimising total
distance, by the recurrence

```
D(i,j) = |a(i) - b(j)|  +  min( D(i-1, j),      insert
                                D(i,   j-1),    delete
                                D(i-1, j-1) )   match

d(a,b) = D(n,m) / (n + m)
```

with `D(0,0) = 0` and everything else initialised to infinity. Dividing by
`n + m` is what makes distances comparable between shapes of different lengths;
without it a longer sequence is penalised for being long.

The **Sakoe-Chiba band** restricts `j` to `|i - j| <= w`:

```
w = max( 0.4 x max(n, m), |n - m| ) + 1
```

so a stretched instance matches a compressed one:

| | normalised DTW distance | |
|---|---|---|
| peak vs a stretched peak | 0.196 | **match** |
| peak vs an inverted peak | 0.748 | no |
| peak vs a straight rise | 0.479 | no |

The Sakoe-Chiba band is not an optimisation detail: unconstrained warping will
align almost anything to almost anything, so without it the "matches" are
alignments rather than resemblances.

Searching many shapes across many instruments **will** turn up repeats by
chance - that is what multiple comparisons do. The guards are the same three
the level model uses, because it is the same failure: enough instances, an edge
clear of the base rate, and a move worth having in volatility units.

DTW is not a metric - it violates the triangle inequality - so the library is a
linear scan rather than a spatial index, which is honest at a few thousand short
sequences and would be complexity bought with nothing at this size.

## 13. Bootstrapping, and why the bus is not enough

The bus carries **notice, not data** - a `prices.bars` message announces the
latest bar per sweep, so the engine sees roughly one bar per venue per minute.
Levels need hundreds. Learning from the bus alone would take days while a
backfilled store already holds the history.

So on start the engine **warms from the store**, read-only:

```bash
uv run till-infinity structures watch          # warms automatically
uv run till-infinity structures watch --no-warm
```

25,000 stored bars replay in under two seconds. Bars go through the ordinary
`observe_bar` path rather than a separate loader, so levels form from confirmed
swings exactly as they would live and there is no second implementation to
drift. Calls produced during the replay are **discarded** - they describe
touches from days ago and publishing them would alert on history.

Saved model state wins over warming: a restored model already contains that
history, and replaying it on top would count every stored bar twice.

The payoff is that the touch statistics exist from the first minute. Without
them every level starts at zero touches and the directional inference has only
kNN to work with.

### One series, not one per venue

Bars arrive per venue and several venues report the same bar. The series took
whichever published *last*, and the winner changed from bar to bar - so the
swing detection was reading a series stitched together from different venues,
injecting exactly the cross-venue disagreement this project exists to *measure*.

It now takes the **median across venues** at each timestamp, recomputed as more
arrive, and a bar needs three venues before it counts. Below that the "median"
is one venue's opinion wearing a median's clothes.

### Pruning, or every price is at a level

Warming from a fortnight of gold produced **148 levels, 135 of them never
touched**. A swing price never returned to is a swing, not a level, and at that
density every price is near something.

Two rules, in order:

- **anything with a touch stays**, however far away price has since moved - a
  level price reacted at is worth remembering precisely *because* price left it;
- everything else must be within 8 volatility units to be tested soon, and then
  only the strongest 15 per timeframe survive.

Pivots are pruned the same way, and that is not optional: a session adds ten of
them and sessions keep completing, so a fortnight accrued 140 that nothing ever
removed. Yesterday's pivots are watched; the ones from twelve days ago are not.

Result on the same history: **8-14 levels per instrument** across all
timeframes, which is the order of magnitude a person marks on a chart.

## Planned: levels from ticks

Levels are **built** from bars and **touched** by quotes. That split is
deliberate and this section is about the case for narrowing it, not for
abandoning it.

Quotes already drive detection - `Engine.observe_quote` runs the touch check on
every interval an instrument has levels at, which is why a daily level can fire
mid-session instead of at the close, and why the interaction is reported as
price arrives rather than confirmed afterwards. What quotes do *not* do is form
levels, and there are two reasons, one weak and one strong.

The weak one is mechanical: PIP selection needs a high and a low, and a quote
has neither. A synthetic bar built from ticks over a rolling window solves that.

The strong one is that **a level is a price other people are watching**, and
tick data is far better at showing where price *went* than where anyone is
waiting. Run PIP on ticks and every local squiggle qualifies: the swing count
explodes, the merge step folds most of it back together, and what survives is a
level at essentially every price - the same failure as the 38-levels-for-2-real
episode in §"Pruning", arrived at from the other direction.

Three things would have to be true before this is worth building:

1. **A vertical-distance threshold in volatility units, not in ticks.** The PIP
   selection would need a floor on how far a swing must travel before it counts
   - probably around 1v - and that floor is the whole design. Without it this is
   a noise generator.
2. **Enough tick history to test on.** Quotes are stored, but a level formed
   from ticks has to be judged by whether price later respects it, and that
   needs weeks of stored quotes to evaluate honestly.
3. **A reason bars cannot already do it.** The 3m series exists precisely
   because a finer view was wanted. If 3m levels turn out to hold as well as 5m
   ones, then 1m is the next cheap step and ticks are unnecessary; if 3m levels
   are visibly noisier than 5m, that is evidence *against* going finer still,
   and it should be believed.

The honest expectation is that (3) settles it before (1) and (2) get built. It
is written down because the question keeps coming up, and the answer is not
obvious from the code - nothing in `pips.py` says "this would not work on
ticks", and it wouldn't.

## Planned: a level spans periods too

The origin work says the leg in and the leg out are *runs*. The same argument
applies one level up, to how a level is found at all - and this is the larger
claim, because it reaches the swing selection in §1 rather than the touch
tracking in §5b.

**Today a swing is a bar.** `pips.py` selects bar *indices* by vertical
distance: the level is the high or low of the bar that was picked. That makes
every level a property of the sampling grid. Move to a finer timeframe and the
same turn is a different bar with a different extreme, so the same structure
gets a different price - which is exactly the quantisation the origin work
removed from touches, still present in formation.

**A swing should be a run boundary.** Price does not turn at a bar; it turns
where one run of volatility ends and the next begins. Segment the series into
runs - the same volatility-unit threshold the origin uses - and the turning
points *between* runs are the swings. A level is then defined by a period on
each side of it, not by one bar's extreme.

Three things follow, and the third is the reason to do it:

**Levels stop moving when the timeframe changes.** A run intersection is the
same price whether it is observed at 3m or 1d; the runs differ in length, the
meeting point does not. Today the confluence view has to *fuse* slightly
different prices from each timeframe and calls the result agreement. With
run-based swings it would be measuring the same number three times, and the
inverse-variance fusion in §11 would spend its precision on genuine
disagreement rather than on sampling artefacts.

**The zone follows from the runs rather than from the filter.** Zone width is
currently the Kalman posterior variance plus recorded wick depth. If a level is
a run boundary, the natural width is how tightly the runs on each side agree on
where they met - which is a measurement rather than an inference, and it would
make the zone narrow where price turned sharply and wide where it ground.

**It makes the timeframe list an implementation detail.** Levels are currently
built on seven fixed intervals, and adding 3m meant touching six places and
finding two ordering bugs. Runs have no interval - the threshold is in
volatility units - so a run-based formation would find every structure the data
contains and let confluence report which resolutions can see it, rather than
asking in advance which resolutions to look at.

The honest counter-argument, which should be tested before any of this is
built: **a bar is not only a sampling artefact.** Daily and weekly closes are
prices that real participants act on, and session boundaries are real events, so
some bar-quantised levels are levels *because* they are bar-quantised. A
run-based pass would miss those, which suggests the two should coexist -
`origin` already records how a level was found (`pip`, `pivot`), and run-formed
levels would be a third kind rather than a replacement.

The cheap first experiment: run both on the same history and compare which set
price respects more often. The outcome machinery to answer that already exists.

### Built and run, 2026-08-14 - and it did not settle it

[`runs.py`](../till_infinity/structures/runs.py) segments a series into runs
and emits the boundaries as ordinary `Point`s, so `form`, `as_of` and the whole
outcome machinery cannot tell which formation produced them.
`Engine(formation="run")` switches between them, which is what makes the
comparison possible rather than arguable.

**The resolution claim holds.** One synthetic path observed on two sampling
grids, with a single volatility so the threshold is the same *price* move at
each: **26 of 27** coarse run boundaries have a counterpart in the fine set,
against **5 of 7** for bar extremes. That is the property the idea was for, and
it is now a test.

**The outcome comparison did not.** Judged on how often price respected each
set:

| | levels | resolved | respected |
|---|---|---|---|
| gold only - pip | 22 | 93 | **83.3%** |
| gold only - run @4v | 20 | 82 | 59.7% |
| gold, btc, eurusd - pip | 69 | 457 | 79.5% |
| gold, btc, eurusd - run @4v | 73 | 353 | **82.2%** |

Thresholds chosen to match level counts, since more levels means more marginal
ones and an unmatched comparison measures selectivity rather than quality.
**The single-instrument result reversed on three instruments**, which is the
whole finding: a 24-point gap that looked decisive was sample noise, and the
honest reading is that the two are indistinguishable on this evidence.

Two flaws in the experiment worth fixing before it is rerun. `MAX_RESOLVED`
caps the resolution queue at 500, so any row hitting exactly 500 is censored
and not comparable - two rows did. And the decisive samples are small: 36
interactions for gold's headline 83.3%.

### Rerun with both flaws fixed, and the answer changed shape

Draining resolutions *during* the replay removed the censoring; four
instruments at 400 bars raised the decisive samples from 36 to between 624 and
1,133. `Engine(formation="both")` was added at the same time, forming each way
and merging, so agreement could be measured rather than assumed.

| formation | levels | decisive | respected |
|---|---|---|---|
| pip | 90 | 624 | **81.6%** |
| run @2v | 178 | 1,020 | 77.9% |
| run @4v | 126 | 662 | 77.9% |
| both @2v | 188 | 1,133 | 79.3% |
| both @4v | 142 | 819 | 79.6% |

**On hold rate alone, PIP still wins narrowly and run formation does not
justify itself.** Two to four points, but now on samples large enough to mean
something rather than on 36 interactions.

**What justifies the merge is coverage, not accuracy.** `both` finds roughly
twice the levels - 188 against 90 - and produces 1,133 decisive interactions
against 624, at a hold rate two points lower. Double the opportunities for two
points of quality is a trade worth having, and it is a different claim from the
one the original design made.

### Agreement between the formations is a real strength signal

The measurement that pays for all of this. Splitting outcomes by how the level
was found, under `both`:

| run threshold | found by both | run only | pip only |
|---|---|---|---|
| 1v | **80.3%** (707) | 77.4% (455) | - |
| 2v | **81.7%** (726) | 77.1% (415) | - |
| 4v | **82.7%** (538) | 75.2% (210) | 88.0% (n=50) |

A level both passes find holds more often than one only the run pass finds, at
**every** threshold - +3.0, +4.6 and +7.5 points, on samples in the hundreds.
Two methods that fail differently agreeing is worth something, and it is now
measured rather than asserted.

The honest limit: agreement does **not** clearly beat PIP alone. Pip-only reads
88.0% at 4v, but on fifty interactions, and it is the only threshold where
enough pip-only levels survived the merge to report at all. So the ordering
between "found by both" and "found by PIP" is unresolved, while the ordering
between "found by both" and "found by runs alone" is not.

So: **not adopted as a replacement, adopted as evidence.** `origin` records
every formation that found a level.

> **The last claim did not survive re-measurement, and the table above is under
> the same doubt.** Both were measured while the volatility estimate was being
> divided by the number of venues reporting each bar (see §10b), and every
> threshold here - 1v, 2v, 4v - is in volatility units, so the *arms of the
> comparison were not the distances they say they were*. Re-run on the
> corrected denominator in [strength.md](strength.md), the ordering **inverts**:
> run-only goes from weakest to strongest, and adding origin to a hold model
> drops its held-out AUC below a chart-identity baseline. Origin came out of
> that design.
>
> Two runs disagreeing is not a result either way, so the honest status is
> **unresolved**, on a smaller corrected sample (800 bars) than the original.
> What is settled is that origin is *not* a validated input to the strength
> weight, and [todo.md](todo.md) 5b should not treat it as one. What predicted
> holding on corrected data was the level's own same-side record, by a wide
> margin.
>
> No code changed for this: `origin` is a label. It is written to `to_dict`,
> merged by `agree`, and read to spot pivots, and it feeds no score, gate or
> feature - so the cost of the inversion is this correction rather than a
> behaviour change.

## Costs come off before anything is claimed

Every push this model produces is **gross**, and for a long time nothing
subtracted the cost of taking it. That is the largest single gap between a
number and a decision: a `+0.5v` edge on an instrument whose spread is `0.3v`
is not an edge, it is a rounding error with a direction attached, and gross
figures cannot tell those apart.

```
net_push = expected_push - sign(expected_push) x cost_vol
```

Signed toward the push, so cost always shrinks the claim and can carry it
through zero. Both gates now read the net figure: the size test in
`actionable`, and `reward_to_risk`.

A cost **larger** than the edge is the case worth stating, because it nearly
went wrong here. It produces a net push with the *opposite* sign, and a large
enough one clears an `abs(net_push) >= 0.5` test comfortably - so the naive
version would have promoted a fully-consumed edge into a confident call in the
wrong direction. `actionable` therefore also requires the net push to still
point the way the gross push did. A consumed edge is not a trade in reverse; it
is no trade.

Quotes carry `spread_bps`, so the engine keeps a window of them per instrument
and charges the **median** - a median for the reason the consensus is one: a
mean is dragged by the outlier it exists to ignore. An exponential average went
in first and failed its own test, moving the charged cost tenfold on a single
hundred-fold print, which would have silenced a whole instrument until it
decayed.

### Expect the channel to go quieter, and read that as the change working

Every edge is now charged the cost of taking it, so any signal whose expected
push sits inside the spread stops qualifying. Some of what was being sent before
was gross - an edge that looked takeable because nothing had deducted what
taking it costs.

**A drop in volume is the success case here, not a regression.** This is worth
knowing in advance, because the two are indistinguishable from the outside: a
filter working perfectly and a service quietly broken both present as a channel
that went quiet. If it goes *silent* rather than quieter, check
`structures levels` - levels still forming with calls still logged means the
cost gate is doing its job; no levels at all means something else broke.

### What the cost actually comes to, measured

Taken from production on 2026-08-14: median quoted spread per instrument
against a typical move on each timeframe, both in basis points, so the ratio is
the charge in volatility units.

| instrument | median spread | 3m | 15m | 1h | 1d |
|---|---|---|---|---|---|
| btc | 0.016bps | 0.003 | 0.003 | 0.003 | 0.005 |
| us100 | 0.599bps | 0.154 | 0.054 | 0.071 | 0.054 |
| spx500 | 0.513bps | 0.103 | 0.058 | 0.059 | 0.070 |
| gold | 0.786bps | **2.07** | **1.10** | **1.03** | 0.407 |
| gbpusd | 0.741bps | **2.50** | **2.25** | **1.99** | 0.407 |
| eurusd | 0.433bps | **2.50** | **1.23** | **1.17** | 0.322 |

Two things fall out of this, and neither was visible before it was measured.

**The instruments are in different regimes entirely.** A charge of 0.003v on
btc is a rounding error; the same gate on gbpusd at fine resolution charges
**2.5 volatility units**, which is larger than almost any push the model
predicts. Once the cost engages, FX below the daily should stop producing
signals more or less completely - not because the filter is broken but because
crossing that spread genuinely costs more than the move being predicted. The
crypto and index feeds are barely touched by the same gate.

**So `abs(net_push) >= 0.5` is not one threshold.** It is a near-free pass on
btc and an almost total block on FX intraday, and the difference comes from the
market rather than from anything chosen here. That is the gate working as
designed; it is stated because a per-instrument outcome from a global constant
is the kind of thing that later reads as a bug.

### It charges zero on the replay path, which is where it was measured

Also found on 2026-08-14, and the reason the table above had to be computed
rather than read off the journal: **every level call recorded so far carries
`cost_vol` of exactly 0.0**.

Not a rounding artefact - the journal rounds to four decimals, and the smallest
real charge in the table is btc at 0.0031, sixty times the rounding floor. It
is a true zero, and `cost_of` returns exactly that when its spread window is
empty:

```python
seen = self._spread.get(feed)
if not seen or vol is None or not vol.bps:
    return 0.0
```

`_spread` is filled by `observe_quote` alone. The recorded calls all arrived in
a burst shortly after start-up, off the **bar** path, before any quote had
landed - so the window was empty and every one of them was charged nothing. The
gate is not wrong, it is simply not yet armed at the moment those calls are
made, which is precisely when a cold start makes the most of them.

Worth stating plainly: the spread cost has therefore never yet suppressed a
single signal in production. The quiet channel is not this feature working.

### Turning it off, and why that needs to be audible

`STRUCTURES_CHARGE_SPREAD=0` (or `Engine(charge_spread=False)`) stops the
charge. It exists for one purpose - running the same history both ways, where
the difference *is* what the cost is worth - and not for production, where an
uncharged edge is a gross number.

It is a switch rather than a threshold on purpose. The cost is measured; a
measured quantity is either charged or it is not, and a dial on it would be
inventing a number to sit between two honest positions.

The switch **logs a warning when it is off**, which is the part that matters.
A disabled charge and an unarmed one both write `cost_vol: 0.0` into the
journal and are indistinguishable there forever after - which is exactly how
the inert charge above went unnoticed. A zero that was configured must not be
readable as a zero that went wrong.

Remember that the charge is not uniform when reading the difference: switching
it off relaxes btc by 0.003v and gbpusd intraday by 2.5v. It does not loosen
one gate evenly, it removes six different gates.

## Honest status

Everything above is validated on **synthetic mean-reverting data**, where the
edges exist by construction. That tests the machinery - the filter, the decay,
the asymmetry, the guards - and says nothing about whether real levels predict
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
| `structures/runs.py` | swings as run boundaries - the second formation |
| `structures/volatility.py` | the unit everything is measured in |
| `structures/levels.py` | Kalman state, zones, per-side stats, decay, clustering, `agree` |
| `structures/pivots.py` | sessions and the floor-trader set |
| `structures/reactions.py` | touch tracking, kNN, inference, the guards |
| `structures/engine.py` | bars and quotes in, calls out |
