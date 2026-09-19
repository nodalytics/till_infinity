# sweep-aware's entries under its own exit and under ride's

`sweep-aware` is the best live performer on this book - **+104.40 over 18
closes** the day the strategy list changed - and it runs the **third-worst exit
policy** in the table `Ride` was built from: target at 1x the modelled push, no
trail, measured at **-0.041R** against ride's **+0.404R** over 31,820 replayed
touches.

That suggested its edge is the entry filter and its exit is a drag. It also
suggested a change that `Ride`'s own docstring warns against: *"the replay
models no spread, which is precisely what sinks fast entries live"* - and
sweep-aware trades from 1m.

Its own record cannot settle it. It has 30 closes and only **14 carry a stop
and a target**; the rest are unattributed. So this replays its **entry rule**
over the published call stream and charges the spread.

## The run

52,395 published calls over 7 days. sweep-aware's rule accepts 40,557 of them -
refusing 2,416 on interval, 9,200 for a stop standing in front of resting
liquidity, and 222 for a level run too often from that side. 30,875 had enough
1m history to walk forward.

| policy | n | mean R | median | win |
| --- | --- | --- | --- | --- |
| its own: target 1x push, no trail | 30,875 | **+0.099** | +0.467 | 61.6% |
| **ride's: trail 0.5v, target out of reach** | 30,875 | **+0.655** | +0.353 | 64.4% |
| its own, spread removed | 30,875 | +0.172 | +0.499 | 62.8% |

**Paired on the same trades: +0.556R mean, +0.500R median, and ride's exit is
better on 70.8% of them.**

The spread is real and does not reverse it: it costs the current policy 0.073R
a trade, which is 42% of what that policy makes.

## The shape of the win is the thing to notice

Ride's exit has a **lower median** (+0.353 against +0.467) and a far higher
mean. It wins by the right tail - fewer trades taken to a big number, more
given back from a good position - which is exactly what a trail does and
exactly what `Ride`'s docstring says about itself: *"the mean rides on the right
tail."*

That is a different risk profile, not only a better number. A book on ride's
exit has a worse typical trade and a better average one, and it needs the
patience to sit through the difference.

## What is not modelled

* **No queue position.** A resting entry is assumed filled the moment price
  touches the level. That flatters both policies and flatters the *current* one
  more, because it is the one that rests - `never filled` was 3.9% of
  sweep-aware's live attempts, and those are excluded here by construction.
* **Spread only where it is known** - 33 feeds, median 1.503bps. Everything
  else is charged zero, which biases the result optimistic on the instruments
  with no spread record.
* **No commission, no funding, no slippage beyond the spread.**
* **A 24-hour hold cap.** Ride's exit holds longer by design, so it commits
  capital for longer, and with `max_positions` at 10 that has an opportunity
  cost this replay cannot see.

## What it supports

Changing sweep-aware's exit is now the best-evidenced single change available
on this book: 30,875 paired observations, spread charged, better on 70.8% of
the same trades, and consistent with a table measured independently on 31,820
touches a month earlier.

**It is still a replay.** The book has watched replayed edges fail on contact -
`thesis-only` most recently - and the honest step is not to swap the exit but
to let `ride` and `sweep-aware` run side by side on the live stream, which the
current strategy list already does: `ride` is first and `sweep-aware` fourth.
The comparison will make itself, on real fills, in a few days.

# 2026-09-11: the exit that cannot engage, and two look-aheads in the replay

## The observation that started it

*"We give back more in sweep-aware. The last trade went up to $60+ but we only
banked $17 and even still ended with a loss."*

Every trading outcome carries `best_r`, the high-water mark. So this is directly
measurable from the live record rather than by replay, and it is not one trade:

| strategy | n | mean peak | mean realised | keeps | $ |
| --- | --- | --- | --- | --- | --- |
| sweep-aware | 47 | +0.549R | +0.134R | **27.1%** | +92 |
| thesis-only | 159 | +0.267R | -0.136R | **-13.7%** | **-441** |
| confluence-scalp | 10 | +1.401R | -0.357R | 18.8% | -92 |
| opportunity | 5 | +0.489R | -0.209R | -71.5% | -23 |
| fade-to-value | 9 | +0.020R | -0.573R | - | -160 |

`thesis-only` is the larger bleed and was already out of the strategy list.
`confluence-scalp` gives back **1.758R a trade**, the most of any of them.

## Why sweep-aware gives it back: the exit never gets to act

Its exits break down as **38 `hold`, 6 `stop`, 2 `target`** out of 47. Four in
five trades end because the 30-minute clock ran out, not because any rule fired.

The reason is arithmetic, and it is visible in a day of logs: **104 `trailing`
lines against exactly one `break even` line**, and the trailing widths read
`2.00v` and `2.07v` where the class asks for `0.5v`.

`manage.stop_for` widens the trail to clear the level's own wicks:

    room = max(trail_vol, wick + spread_sd * trail_sigmas)

and that rule **has no ceiling**. Over 47,233 level calls the computed trail is
the 0.5v floor only 59% of the time, exceeds 1v on 30.2%, exceeds 3v on 9.4%,
and its maximum is **2,239v** - because `wick_below_vol` itself reaches 4,360v
and nothing clips it. On levels selected for being swept, the wick distribution
is exactly the fat-tailed one that rule cannot survive.

A trail sits `room / risk_vol` R behind the peak, and the trail is only allowed
to replace the original stop once it is in front of it. So with a 2v trail on a
typical 1.5v risk, **the trail cannot engage until the trade is up 1.33R**. And:

| the trade ever reached | of 54 closes |
| --- | --- |
| 0.25R | 63.0% |
| 0.50R | 50.0% |
| **1.00R** - where `break_even_at` engages | **11.1%** |
| **1.33R** - where a 2v trail engages | **7.4%** |
| 2.00R | 3.7% |

Median peak is **0.445R**. So for roughly nine trades in ten, *neither* the
break-even nor the widened trail is reachable, and the trade rides to the
timeout giving back whatever it made. The exit policy is not badly tuned; on
this distribution it is **inert**.

That is the mechanism behind the $60 that became $17.

## What the policy replay says, and why it took three tries to believe it

`research/harness/sweepstops.py` replays sweep-aware's own entries over 11,053
trades under 18 exit policies, paired, spread charged, split 60/40 by time.

**The first version reported `grace_10` - ignore the stop for ten bars - at
+1.335R against the shipping policy's +0.344R, better on 63.5% of the same
trades, holding in both halves.** It was a look-ahead. During the grace window
the trail kept tightening while exits were forbidden, so the exit at bar ten
booked a stop price the market had already passed through and left.

Fixing that exposed a second one: the trail was being raised on a bar's own
high and then allowed to fill on that same bar, which protects a trade with
information it did not have. Bar order is unknowable from OHLC, so the only
honest sequence is to test the levels that were resting when the bar opened and
only then let the bar's extreme move them. A gap fill was added at the same
time - a bar that opens through the stop fills at the open, not the stop.

Corrected, on the live 30-bar hold:

| policy | discovery | verify | vs current (verify) | better on |
| --- | --- | --- | --- | --- |
| `beyond_pool` | -0.052 | **+0.051** | +0.019 | 46.0% |
| `wick_cap_1v` | -0.204 | +0.032 | +0.001 | 6.8% |
| **`current`** (ships) | -0.198 | +0.032 | - | - |
| `live_wick` | -0.199 | +0.018 | -0.013 | 9.2% |
| `grace_10` | -0.188 | +0.014 | -0.017 | 44.0% |
| `no_trail` | -0.227 | -0.007 | -0.039 | 26.3% |
| `close_only` | -0.226 | -0.033 | -0.064 | 29.7% |

`grace_10` went from +1.335R to noise. **None of the eighteen beats what ships
by more than noise.** `no_trail` is clearly worse, so the trail earns its place;
`close_only` - stopping on the close rather than the wick, which sounded like
the natural policy for a sweep-aware strategy - is worse, not better.

### The replay disagrees with the live record, and the live record wins

The replay exits **98%** by stop; live exits **81%** by timeout. It also scores
`live_wick` the same as `current`, which does not reproduce the inert-trail
effect the live logs show directly. Something about the replay's trail is
firing when the real one cannot - most likely that `best` is tracked live from
the quote stream at 20-second resolution while the replay uses 1m bars.

So the policy table is **not** evidence that the exit is fine. It is evidence
that this replay cannot see the problem, and the arithmetic above can.

## What this supports

1. **Cap the wick widening.** A trail wider than the trade's own risk can never
   engage before 1R, and 89% of these trades never reach 1R. `min(room, risk)`
   is the natural ceiling; the uncapped rule producing a 2,239v trail is not a
   tuning question.
2. **Lower `break_even_at`.** At 1.0R it fires on 11% of trades. The median
   peak is 0.445R.
3. **Neither is supported by the replay**, which is why neither has been
   changed here. They are supported by the live distribution of `best_r`, and
   the honest next step is to measure them against it rather than to ship a
   number because the arithmetic is suggestive.

## What was changed, and why that one was different

`confluence-scalp` was given `ride`'s exit and turned back on. Not because the
replay supports it - it does not - but because that strategy had **no exit
policy at all** and its mean peak is **1.401R**, which is the regime those
numbers were chosen for and the regime `sweep-aware` never reaches. The failure
mode documented above is specifically that the thresholds sit above the
distribution; for this strategy they sit inside it.

Ten closes cannot settle an exit policy. This makes the record be about the
question that was asked.

# 2026-09-11: decomposing the regime survivors, and a correction to my own reading

`research/harness/sweepregimes.py` cuts sweep-aware's replayed trades by 21
dimensions, split 60/40 by time, against a control of three random buckets of
the same trades. Corrected for the same two look-aheads as `sweepstops` - the
two harnesses now share one `walk`, because they had diverged and one was wrong
- seven dimensions survive:

| dimension | gap R | best | worst |
| --- | --- | --- | --- |
| risk_vol | **0.822** | high | low |
| vol_bps | **0.636** | high | low |
| vol_stretch | 0.186 | mid | low |
| origin_size_vol | 0.185 | high | low |
| edge | 0.185 | mid | high |
| origin_distance_vol | 0.153 | mid | low |
| strength | 0.152 | mid | high |

Control gap 0.069R. `risk_vol` and `vol_bps` hold their ordering in **every**
interval, which is the Simpson check this project needs after being caught by it
three times.

Both are also suspicious as *regimes* and obvious as *arithmetic*, so both were
decomposed by re-running with one thing changed at a time.

## `vol_bps` was the spread, entirely

| run | pooled mean | `vol_bps` gap |
| --- | --- | --- |
| as it ships | -0.015R | 0.636 |
| **spread charged at zero** | **+0.348R** | **absent** |
| trail scaled to risk | -0.015R | 0.634 |

Charge no spread and `vol_bps` **drops out of the survivor list altogether**.
The mechanism is not subtle: R is normalised by risk, so the cost in R is
`spread / (risk_vol * vol_bps)`, which grows without bound as volatility falls.
Low-volatility setups do not lose because the market is quiet; they lose because
the same spread is a larger fraction of a smaller move.

That is a **cost** finding, not a regime one, and the two want different actions.
"Do not trade quiet markets" is a rule about the market. "Refuse a setup whose
spread is too large a share of what it is reaching for" is a rule about the
trade, generalises to every instrument, and is the correct form.

## `risk_vol` was **not** the trail, which was my hypothesis

The guess was that a **fixed** 0.5v trail gives back 0.5R against a 1v stop and
0.25R against a 2v one, so wider stops would score better for purely mechanical
reasons. Scaling the trail to half the *risk* moves the gap from 0.822 to
**0.812**. It is not the trail.

Removing the cost moves it from 0.822 to 0.498, so roughly 40% of it is the same
spread effect - a wider stop buys more R per unit of spread - and about 60%
survives both tests unexplained.

## A correction: the spread is not eating the live edge

The natural reading of "+0.348R without cost against -0.015R with it" is that
transaction costs consume this strategy's entire edge. **That reading is wrong,
and the live record says so.** Over 305 journalled decisions carrying a spread,
a risk and a target:

| | median | p75 | p90 |
| --- | --- | --- | --- |
| spread / risk | **0.081** | 0.157 | 0.324 |
| spread / reward | 0.112 | 0.189 | 0.275 |

The desk actually pays about **0.08R**, not 0.36R. The difference is that the
replay charges every call passing sweep-aware's *entry* rule, and `risk.py`'s
`max_spread_fraction` gate then refuses the expensive ones before any of them
becomes a trade.

So the honest statement is narrower and more useful than the one the table
first suggested: **the replay's pooled figure is not the desk's expected
return**, because the desk does not take that population - the risk gates are
doing real work, and a replay that skips them measures a strategy nobody runs.

What the decomposition still establishes is the `vol_bps` result above, which
does not depend on the level of the cost, only on its shape.

# 2026-09-11: the number that chose this exit was inflated tenfold

`exits.py` scored `sweep-aware`'s old exit at **+0.099R against ride's +0.655R**
over 30,875 replayed calls, and that is why `SweepAware` carries
`target_multiple=6.0`, `trail_vol=0.5` and `break_even_at=1.0` in production.

That harness had both look-aheads found this morning. It has been rewritten onto
the shared kernel (`till_infinity/shared/replay.py`), and the old arithmetic
kept beside it as `_legacy_walk` so both can run over **the same trades** and the
difference attributed to the bug rather than to the data.

18,272 replayed calls, both walks, both policies, spread charged:

| walk | policy | mean R | median | win | stopped | ride − own | better on |
| --- | --- | --- | --- | --- | --- | --- | --- |
| legacy | old | -0.052 | +0.427 | 58.3% | 41.7% | | |
| legacy | **ride** | **+0.381** | +0.208 | 58.1% | 99.9% | **+0.432** | **68.0%** |
| kernel | old | -0.058 | +0.498 | 58.3% | 41.7% | | |
| kernel | **ride** | **-0.013** | +0.133 | 54.4% | 98.9% | **+0.046** | **36.3%** |

**The bug was worth +0.386R to the trailing policy and +0.006R to the
fixed-target one.** That asymmetry is the whole finding, and it was predicted
before the run: a trailing stop benefits from being raised on a bar's own high
and from being filled at its own price on a bar that gapped through it. A fixed
target does neither.

It holds in both halves - ride's advantage goes 0.439 -> 0.038 in discovery and
0.422 -> 0.057 in verify - so this is not a period effect.

## What that does and does not say

**It does not say revert.** Ride's exit still has a positive mean edge on the
corrected walk, +0.046R pooled and +0.057R on the verify half.

**It does say the decision rested on evidence about ten times weaker than the
number it was made on**, and that the *shape* of the trade-off is different from
the one documented. The original write-up said "the median falls while the mean
rises - a trail wins by the right tail". That was true and is now much more
extreme: the median falls from **+0.498 to +0.133** and the policy is worse on
**64% of the same trades**, winning only through a thin right tail.

An edge that lives entirely in a tail is a different risk profile from one that
is broadly present, and it needs a larger sample before anyone should be
confident in it - 18,272 replayed trades is a lot, but a tail is measured by its
rare members rather than by its total.

**And the live record now agrees with the corrected version rather than the
original.** `giveback.md` records that `sweep-aware` keeps **27%** of its
high-water mark and that 38 of its 47 closes end on the hold timeout rather than
on any rule. A policy that is worse on two trades in three, winning only in the
tail, is what that feels like from the outside.

## Re-run 2026-09-12 with rule 3 declined, and it changes nothing here

`shared/replay.py`'s rule 3 - "a stop and a target both touched in one bar
resolve as the stop" - turns out to be **0.47 to 0.68 accurate**, and 0.415 on
btc, against a five-state reconstruction. Because it always says the same thing
its error is a one-sided bias rather than noise, worth -9 to -44 points of risk
per resolved trade. This page chose the exit policy that ships, off replayed
*trailed* exits, which is exactly where that bias was expected to bite.

It does not bite here. Re-run with `ambiguous="expected"`, which returns the
probability-weighted R instead of asserting the worse barrier:

| walk | policy | mean R | | |
| --- | --- | ---: | ---: | ---: |
| kernel | old | **+0.076** | | |
| kernel | ride | **+0.134** | | |
| weighted | old | **+0.082** | | |
| weighted | ride | **+0.135** | | |

**146 of 36,544 resolutions were ambiguous - 0.4%** - and the two columns agree
to 0.006R on the untrailed arm and 0.001R on the trailed one. So the comparison
that put ride's exit on the desk never rested on the convention, and the
conclusion stands as written.

Worth separating two things that are both true. The bias is real and the fix was
right to make: on a book where ambiguity reaches 10% to 43% of resolving bars -
which is what happens once a stop has trailed right up to price - it is the size
of the findings it feeds. On *this* harness it is 0.4%, because `ride` aims at
six times the push and `old` closes before the trail ever engages. A rule can be
badly wrong and still not matter for a particular question, and saying which is
the point of re-running rather than arguing.

## The methodological point

This is the second time in one day that a replay's answer moved by an order of
magnitude on a bug fix, and both times the original passed every statistical
guard applied to it. The guards test whether a result is stable and general.
**None of them can test whether the simulation was honest**, and a look-ahead
produces results that are stable, general and reproducible.

That is the argument for the kernel, and it is why the walk now lives in the
package where CI lints it and the suite covers it, rather than in the one part
of this repository that had no gate on it.
