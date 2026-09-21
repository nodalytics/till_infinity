# Exits without a stop, and the three cost escapes — measured 2026-09-21

By `research/harness/stopfree.py` and `research/harness/maker_exits.py`, on 65,000 hourly
bars per instrument.

`costs.md` showed the barrier programme cannot be collected: stop overshoot is 0.24 TR on
Boom and 0.29 TR on gold against a largest-ever effect of 0.08 TR. The conclusion was that
the positive results are unreachable *with a stop*. This tested the formulations that do not
pay for one, and then the three structural escapes from the remaining costs.

**The answer is that the costs were never the only obstacle.** At near-zero cost the signals
are still absent, which closes the question rather than deferring it.

## Removing the stop reverses the direction of the "edge"

This is the cleanest confirmation of `costs.md` available, and it comes from a completely
different method.

| Boom 1000, no stop, gross per hour | mean | p01 |
|---|---|---|
| always **long** | **+0.003** | −1.22 |
| always **short** | **−0.003** | −2.17 |

With a stop, Boom shorts win 54.1% of one-to-one barrier bets. Without one, shorting Boom has
a **negative** mean return. The barrier framing and the actual return distribution disagree
about the *sign*, and the entire difference is the capped-loss assumption. Two independent
methods now agree that the asymmetry is an artefact of charging losses at 1 R.

## Why stop-free does not rescue it either

**Carry is linear in holding time; any edge is at best proportional to its square root.** So
the cost catches up precisely at the horizons a signal would need to work. On Crash 1000 at
0.161 TR/day, a two-day hold costs 0.322 TR while the entire gross mean is ±0.084. Every
stop-free cell across both instruments and all eight horizons is net negative.

The left tail grows as expected and should govern any sizing decision: p01 runs from −2.17 TR
at one bar to −12.25 TR at forty-eight.

## Escape one: swap is charged at rollover, not by the hour

**This corrects `net_edge.py`.** It charged `carry * hours / 24`, which is wrong in both
directions at once - swap is a discrete charge at a rollover instant, so a 2.7-hour trade pays
either nothing or a full day, never a ninth of one. The expected value coincides, which is why
the earlier number looked right, and the consequence was missed: **a trade flat at rollover
pays exactly zero carry.**

It works, and it is nearly free:

| Boom 1000, h=1 | taker, carry charged | taker, flat at rollover | kept |
|---|---|---|---|
| always long | −0.018 | **−0.005** | 96% |
| always short | −0.025 | **−0.011** | 96% |

0.013 TR saved for a 4% reduction in opportunity. This is the one unambiguously good finding
here and it applies to the live book regardless of signal.

**Caveat that limits it.** The rollover instant is assumed to be 00:00 UTC and is **not
confirmed**; it needs reading off the swap actually charged on live tickets. And the exclusion
bites hard at longer horizons - `kept` falls to 75% at six bars and 50% at twelve - so the
long-horizon rows are computed on trades starting early in the UTC day and carry a
**time-of-day selection confound**. Only the short horizons are clean.

## Escape two: maker entry, which is catastrophic in the direction that matters

A resting limit saves the spread but is filled only when price comes to it. On a spike
instrument that selection is severe and it runs the wrong way:

| Boom 1000, h=1, limit entry | net | filled |
|---|---|---|
| always long (the grind side) | **+0.002** | 96% |
| always short (the spike side) | **−0.255** | 72% |

A resting short is filled only when the next bar trades up through it - which on Boom means
**it is filled exactly as a spike begins.** Against a taker short's −0.011, the maker short
loses 0.255. The adverse selection is twenty times the spread it saved.

The lesson generalises past this instrument: **posting a limit on the side an instrument jumps
towards buys you the jump.** Any maker strategy here must be on the grinding side only.

Maker long does turn net positive (+0.002 at one bar rising to +0.033 at twelve) but `vs
always` is 0.000 by construction - that is just being long an instrument that rose 64.9%, not
a signal.

## Escape three: a limit target, which destroys the return it was meant to protect

A limit exit cannot slip, so it was the expected route past the overshoot. It is worse:

| Boom 1000, h=1 | maker, time exit | maker, limit target |
|---|---|---|
| always long | +0.002 | **−0.084** |

**Boom's entire positive return lives in its up-spikes, and a target at 1 TR truncates exactly
those.** A bar that reaches one true range above entry may close three above it; capping at one
discards the difference. The instrument's return is a fat right tail and a limit target is a
machine for cutting fat right tails off.

This is the sharpest single lesson in the study: on a jump process, **capping the upside is not
a risk control, it is the removal of the edge**, and it is much more costly than the slippage
it avoids.

## What survived

Nothing, and the negative is now well bounded rather than merely unmeasured.

Across four configurations, two instruments, eight horizons and seven entry rules, exactly one
cell reached its own two-sigma bar - `gap edge, bull` at six bars, +0.060 against a ±0.060
error bar, `vs always` +0.044. That is marginal at the threshold, on a 75%-kept subsample with
the time-of-day confound, and one marked cell is what several hundred comparisons produce by
chance.

`fade ON spike` is directionally consistent across every configuration and horizon, with `vs
always` between +0.030 and +0.374. It is also n=247 with error bars of ±0.073 to ±0.305, so it
cannot be resolved at all with hourly data. **It is the only hypothesis this study leaves
open**, and settling it needs either finer bars or a longer history, not another harness.

## What this closes, and what it opens

The barrier results were unreachable because of slippage. The stop-free results are unreachable
because of carry. And with both costs removed the means are indistinguishable from the
unconditional trade. **The obstacle was never only the cost structure; on this data, at this
resolution, there is no directional signal to collect.**

Three things remain genuinely untested, and they are cheap:

* ~~**Resolution.**~~ **Settled 2026-09-21, and both halves of the argument were wrong.**
  5m and 15m bars for the Boom/Crash family were downloaded and the hypothesis is refuted -
  see the addendum below.
* **Position sizing.** Every number in this repository is per-trade expectancy. With p01 at
  −2.17 TR and no stop, sizing decides survival, and no Kelly fraction or drawdown estimate has
  ever been computed.
* **Statistical power.** Nothing here has ever reported a minimum detectable effect. Several
  past "nulls" - the spike rules above most clearly - are underpowered rather than negative, and
  an experiment whose detectable effect exceeds its cost hurdle cannot succeed whatever it
  returns.


## Addendum, 2026-09-21: the finer bars settle it, and correct two claims

`fade ON spike` was the one hypothesis this document left open. 5m and 15m bars for the
Boom/Crash family were downloaded to resolve it. It is refuted, and the reasoning that made
finer resolution look attractive was wrong twice over.

### The hypothesis fails on its own mirror symmetry

What made fading a spike interesting was that it was directionally consistent everywhere. At
5m it is not:

| rule, one bar held | at 1h | at 5m |
|---|---|---|
| Boom, `fade ON spike` | +0.031 | **−0.030** |
| Crash, `fade OFF spike` | −0.006 | **+0.085** |

**Each instrument flips sign between resolutions, and they flip in opposite directions.** Only
the Crash 5m cell clears its error bar, at +0.085 against ±0.079, on n=404 - one marked cell
out of dozens, and its mirror on Boom is negative. A structural effect on a pair of
deliberately mirrored instruments does not behave this way; noise does.

### Correction one: the sample barely grew

The expectation was twelve times the events. It was **1.6 times** - 404 against 247.

`MaxBars` caps the bridge at 100,000 bars per symbol, so 5m buys about **347 days** where 1h
buys 7.4 years. Finer resolution does not buy more history, it re-slices less of it. To get
more spike events the lever is the detector's set point - `TARGET_RATE` in `changepoint.py`,
which is an explicit research budget - not the bar size.

### Correction two: carry gets worse at finer resolution, not better

This document said 5m "pays the same spread and a twelfth of the carry". The first half is
right and the second is backwards.

Carry is charged per unit of *time* but measured here in true ranges, and **one true range
shrinks faster than the clock does**:

| carry, in TR per day | 1h | 5m | ratio |
|---|---|---|---|
| Boom 1000 | 0.321 | **1.940** | 6.0x |
| Crash 1000 | 0.161 | **0.974** | 6.0x |

So per hour held, financing costs **six times more** of a risk unit at 5m than at 1h. Per
*bar* held it is about half, because twelve bars fit in the hour - which is the grain of truth
the original claim was built on, and it only helps a strategy whose holding period shrinks in
proportion to the bar size.

The general form is worth keeping: a cost charged per unit of time, expressed in a risk unit
that scales with the square root of time, **gets relatively worse the finer you go**. Moving to
a faster timeframe to escape financing is moving the wrong way.

### What is left

Nothing. Every hypothesis this research opened is now either measured null or refuted, and the
cost structure is understood well enough to say why: the effects are around 0.03-0.08 TR and
the costs are 0.08 TR and up.
