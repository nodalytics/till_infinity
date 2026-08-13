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

## 5b. The origin, and why it is not the extreme

Which price *is* the level? The obvious answer is the extreme — the high of the
swing, the low of the wick. It is the wrong one, and this is the single
correction that most changed what the model learns.

A leg of volatility comes into a level and a leg of volatility leaves it. The
**origin** is where those two meet: where the move in stopped and the move out
began. Most of the time that is the close of one bar sitting on the open of the
next. The extreme is somewhere past it — the distance price was pushed *beyond*
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
brought price *in*, not the overshoot — a number about the approach wearing the
name of the level.

### Wick depth, and the zone it defines

Depth is measured from the origin to the extreme, in volatility units (§0), so
it means the same thing on gold as on EURUSD:

```
depth = |wick − origin| / origin × 10⁴ / bps
```

and folded into a per-side EWMA, the same shape as everything else here — the
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

Read the indices carefully — they cross on purpose. Touches coming **from above**
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
ceiling being tested and a floor being tested overshoot equally — they do not,
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
touch count** — a real number, not an integer — and every estimate downstream
gets age-weighting for free without knowing it exists.

Worked: ten rejections, then a three-month gap, then three breaks.

```
after the gap:   n = 10 x 0.5^(90/21) = 10 x 0.052 = 0.52
after 3 breaks:  n = 0.52 + 3 = 3.52,  ups = 0.52
P(up) = (0.5x4 + 0.52) / (4 + 3.52) = 0.33
```

The ten January rejections no longer outvote three breaks last week, which is
the entire point.

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

**The base rate is per `(feed, interval)`.** For a while it was not: one
pooled rate over the whole kNN memory served every call on every instrument and
timeframe, so GBPUSD on the daily and BTC on 15m were both reported against the
same 72%. That is wrong in a way that does real damage, because `edge` is
`conditional − base` and `actionable` gates on `|edge| ≥ 0.08` — a pool sitting
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
units, so this is measure-zero rather than a lean — but it is a tie broken by an
implementation detail rather than by evidence.)

What is reported, though, is the probability of **the direction being claimed**,
not always P(up). Printing P(up) beside a down call renders as `down p=23%`,
which invites reading 23% as the confidence in down when it is the confidence
against it. The same call now reads:

```
down p=77% (base 53%) push=-1.40v n=9.0+12
```

The base rate flips with it, because a conditional in one direction against a
base rate in the other is not a comparison — and it is exactly the shape most
likely to be quoted approvingly. `probability_up` keeps its meaning in the
journal and in `facto.py`, since the models are keyed on it; `probability` and
`base_rate` are the ones for a person. When the call is `mixed` (§7, win rate
and expected move disagreeing) this deliberately prints below 50%, which is the
honest rendering: the direction came from the push while the win rate points the
other way, and `mixed` sits next to it.

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
| `backcheck` | 1.0 when this is a retest of a recent break |
| `regime` | where volatility sat in its own recent range, in [0, 1] |

Distance is plain Euclidean over those six, with side as a gate rather than a
term:

```
d(a, b) = inf                             if side(a) != side(b)
        = sqrt( sum_k (a_k - b_k)^2 )     otherwise
```

`regime` is there because everything else is *scaled* by volatility, which
makes sizes comparable and deliberately erases what the market felt like. A
level held in a dead session is weaker evidence about a violent one than the
normalised numbers suggest, so the regime goes back in as its own dimension and
a touch is compared with touches from a market that felt the same.

**Side is a hard constraint, not a dimension** — infinite across sides, because
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
level with no history of its own would inherit that and report it — a system
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

## 7b. False breakouts

A trap is price getting through a level convincingly enough to invite the
breakout trade, and then giving it all back. It is not a shade of "break" and
not a shade of "reject" — the price action before it is a break and the price
action after it is a rejection — so a model with only those two words records
it as **a break that worked**, which is the opposite of what happened.

That is what this did until it was measured. On the stored history:

| outcome | | |
|---|---|---|
| chop | 535 | 74.3% |
| reject | 115 | 16.0% |
| break | 43 | 6.0% |
| **trap** | **27** | **3.8%** |

**27 of 70 breakout attempts were false — 39%.** All of them previously counted
as clean breaks, so the model was learning that breaking works about 1.6 times
more often than it does.

### A break is provisional until it survives

Which is how anyone trading one treats it. Price crossing `resolve_vol` beyond
the level no longer resolves the touch; it marks it `breaking` and starts a
clock:

- price comes back through the level by `TRAP_VOL` -> **trap**
- the clock runs out with price still beyond -> **break**

The push recorded for a trap is where price *ended*, not how far it went — a
breakout entry loses, and the number has to say so. How far it went is kept
separately as `excursion_vol`: what the trade was offered before it was taken
back.

### A trap is the level holding

Violently, after letting price through first. So a trap does not mark the level
broken and does not decay its history — this is the level doing exactly what it
did before, and the evidence is worth more, not less.

`trap_rate` is the number worth knowing before trading a break: of the times
price got through here, how often it was taken back. A level where half the
breakouts fail is not a level you break out of.

On the real history, `btc 63,678.75` (5m, from below) carries three effective
traps and **no** clean breaks.

## 7c. Back checks

The third thing that happens at a level, and the one worth the most.

Price breaks a level and the break holds. Price then comes back to that same
level — now flipped, old resistance become support — holds, and carries on the
way it broke. It sits between the other two:

| | momentum | entry | risk |
|---|---|---|---|
| breakout | proven | chasing | undefined |
| **back check** | **proven** | **pullback** | **defined by the flipped level** |
| false breakout | — | — | you were wrong |

Two conditions, and both are the definition rather than a threshold:

- the break must be **recent** — `BACKCHECK_BARS` of that timeframe, so a
  couple of hours on 5m and most of a year on 1w. A return three months later
  is a level, not a retest.
- price must arrive from the side it broke **to**. Arriving from the original
  side is the break failing late, which is a different event entirely.

A back check is recorded as *both* a reject and a back check: the level held,
and it held in this particular way. `backcheck` is also a kNN dimension, so a
retest learns from other retests rather than from first touches — a
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
is a stop inside the noise — it gets hit by the level working.

`reward_to_risk` is what decides whether an edge is worth taking. A 70% call
worth half what it risks is a losing trade; a 55% call worth three times it is
not.

### How often it actually happens

Rarely, on the history collected so far — and the honest numbers are more
useful than a tuned threshold:

| | |
|---|---|
| breaks recorded | 43 |
| breaks ever revisited | **15** |
| back checks | **1** |

The ceiling is 15, not 43: most breaks are never retested at all, which is what
a break is. The binding constraint on the rest is the 74% chop rate — a retest
that drifts sideways rather than moving resolves as chop, which is correct,
because a back check that produces no move is not a tradeable one.

One occurrence is not evidence about anything. The mechanism is verified by
construction in the tests; whether back checks pay is a question for the
journal once there are enough of them to ask.

## 7d. When price will get there

A level three volatility units away is not "near" or "far" — it is a distance a
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

### There is no average, and that is not pedantry

The expected first-passage time of a driftless walk is **infinite** — the tail
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
This is the **null model** — what distance and volatility alone imply, before
anything about direction. A level reached far sooner than this repeatedly is
saying something, and the estimate is what makes "sooner" mean anything.

Drift is excluded deliberately. Estimating it from recent data is noisy enough
that a wrong sign makes the answer worse than the null, and the honest version
of "price is heading there" is the directional inference, which is a separate
question with its own answer.

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

Swings are clustered one-dimensionally: sort by price, and start a new cluster
wherever consecutive swings are further apart than the tolerance —

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
certainty, and a filter that starts at zero variance can never be moved again. Simple and correct for the shape of the problem — the
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

### How strong is a level

```
strength = 0.40 x min(n, 10)/10          evidence
         + 0.25 x max(0, 1 - sigma/1v)   agreement — a tight zone
         + 0.20 x exp(-Δt / 14 days)     recency
         + 0.15 x min(swings, 5)/5       breadth
```

Age is deliberately **not** rewarded. An old level with two touches is not
strong, it is stale, and treating longevity as authority is how a chart ends up
covered in lines nobody trades.

## 10b. Volatility is per timeframe

The unit in §0 is *a typical move* — and a typical 4h move is not a typical 5m
move. Measured on gold:

| timeframe | volatility | 1v at 4400 | evidence half-life |
|---|---|---|---|
| 5m | 1.70bps | $0.75 | 0.9 days |
| 15m | 2.49bps | $1.10 | 2.6 days |
| 1h | 4.70bps | $2.07 | 10 days |
| 4h | 22.44bps | $9.87 | 42 days |
| 1d | 63.17bps | $27.80 | 250 days |
| **1w** | **118.70bps** | **$52.23** | **1750 days** |

Seventy times, end to end. A single estimate per instrument — in practice
dominated by whichever series updates most often — therefore makes every
threshold expressed in volatility units wrong for every timeframe but one.

The symptom was concrete: clustering swings at 1.0 volatility unit meant
grouping within **$0.86**, while the 4h window spanned seventy days over a $574
range. Swings at that scale essentially never clustered, so 4h produced almost
no levels at all — and the fault was invisible, because "few levels on the
highest timeframe" looks like a reasonable outcome rather than a broken
denominator.

So estimates are kept per `(instrument, timeframe)`, updated from that
timeframe's bars, and used for that timeframe's zones, clustering and pushes.

**Evidence ages on the same scale.** A single decay constant cannot serve both
ends either: twenty-one days is far too long for a 5m level — behaviour from
three weeks ago on a five-minute chart is not evidence about now — and far too
short for a weekly one, which might be tested a handful of times a year and
would forget each touch before the next arrived. The half-life is anchored to
the window instead, so evidence halves over roughly half the history that
timeframe can see. A 1w gold level at 1806 still carries 6.4 effective touches
from years back, which is correct and would be zero under a fixed constant.

**One exception, and it is deliberate.** Cross-timeframe questions — which
level is nearest, is this one worth acting on — need a single denominator, or
"three volatility units away" means something different for every level and
they cannot be ranked against each other. That is the **reference** estimate:
the tick-level one fed by quotes, falling back to the finest timeframe with
data when no quotes have arrived, which is the case when warming from bars.

## 11. Multi-timeframe confluence

A level on the 4h chart and one on the 15m chart at the same price are one
level at two resolutions, and each knows something the other does not:

| | knows |
|---|---|
| **higher** timeframe | that the level *matters* — it is a larger structure |
| **lower** timeframe | *where it is* — its swings cluster in a tighter band |

Levels are grouped by **zone overlap**, each zone computed in its own
timeframe's volatility. Not by a shared tolerance: a tolerance is necessarily
expressed in one timeframe's units, and with 4h at thirteen times 5m a shared
one meant a 4h level had to sit within about fifty cents of a 5m level to count
as the same price. Nothing ever combined, and the zero looked like a market
observation rather than a bug.

A level's zone already encodes how precisely its timeframe can place it, so two
levels describe one price when their zones overlap — the same test `dedupe`
uses within a timeframe, applied across them.

Fusing them is then **inverse-variance weighting**, which is already the right
tool because every level carries a Kalman variance and a finer timeframe
naturally has a smaller one:

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

Measured on stored history:

```
btc      63500.18  [1h+15m+5m]  span=1h  precision=5m  6.7 touches  strength 0.90
eurusd       1.15  [4h+5m]      span=4h  precision=5m  8.9 touches  strength 0.83
```

Gold has none, and that is a real answer rather than a failure: it has been
trending, so its timeframes describe different price ranges and there is
nothing at one price for them to agree about.

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
chance — that is what multiple comparisons do. The guards are the same three
the level model uses, because it is the same failure: enough instances, an edge
clear of the base rate, and a move worth having in volatility units.

DTW is not a metric — it violates the triangle inequality — so the library is a
linear scan rather than a spatial index, which is honest at a few thousand short
sequences and would be complexity bought with nothing at this size.

## 13. Bootstrapping, and why the bus is not enough

The bus carries **notice, not data** — a `prices.bars` message announces the
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
drift. Calls produced during the replay are **discarded** — they describe
touches from days ago and publishing them would alert on history.

Saved model state wins over warming: a restored model already contains that
history, and replaying it on top would count every stored bar twice.

The payoff is that the touch statistics exist from the first minute. Without
them every level starts at zero touches and the directional inference has only
kNN to work with.

### One series, not one per venue

Bars arrive per venue and several venues report the same bar. The series took
whichever published *last*, and the winner changed from bar to bar — so the
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

- **anything with a touch stays**, however far away price has since moved — a
  level price reacted at is worth remembering precisely *because* price left it;
- everything else must be within 8 volatility units to be tested soon, and then
  only the strongest 15 per timeframe survive.

Pivots are pruned the same way, and that is not optional: a session adds ten of
them and sessions keep completing, so a fortnight accrued 140 that nothing ever
removed. Yesterday's pivots are watched; the ones from twelve days ago are not.

Result on the same history: **8–14 levels per instrument** across all
timeframes, which is the order of magnitude a person marks on a chart.

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
