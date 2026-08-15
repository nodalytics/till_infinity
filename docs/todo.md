# Outstanding

Ordered by what would change the numbers most. Each entry says where the detail
lives, because the reasoning belongs next to the code it explains rather than
duplicated here.

## 0. The outcome rate — **answered on 2026-08-14**, and it was the consensus

*Read this before the rest of item 0, which is the trail that led here and is
kept because two of its hypotheses were wrong in instructive ways.*

The rate was not a level problem, a granularity problem or a re-arm problem. It
was that **the touch check ran once per venue row rather than once per bar.**

`Consensus.observe` answers again on every venue that reports a bar — by
design, so the median improves within a sweep instead of waiting for a venue
that may never arrive. `Engine.observe_bar` then ran the whole touch check on
each of those answers, and the consensus median *moves* as venues arrive. On
spx500, whose venues quote genuinely different absolute prices, it moves by
more than four volatility units inside a single bar. The tracker was handed
that jitter as though it were price, so a touch opened on one venue's row and
resolved on the next one's — at the same timestamp, having observed nothing
but the median rearranging itself.

Measured on a replay of the stored 5m bars, before and after:

| | resolutions | resolved at the instant they opened |
|---|---|---|
| before | 500 | 224 (44.8%) |
| checking once per bar | 255 | **0** |
| and resolving from the origin | 206 | 0 |

**49% of all resolutions were manufactured**, and spx500 alone fell from 263 to
39. The production journal agrees independently: 46% of its outcomes have
`seconds <= 0`, and 97% of those were already past `resolve_vol` when they
resolved, with a median `depth_vol` of 0.12 against 0.25 for touches that
lasted — they clipped the zone edge and were recorded as rejections.

It also explains why two runs of the same replay disagreed: venue arrival order
is not stable.

A second, independent cause survived that fix at 16.7% of touches, spread
evenly across all six instruments: a zone reaches `MAX_ZONE_VOL` from the level
while a rejection needs `resolve_vol`, which is half of it, so price clipping
the far edge arrived already past the threshold. Rejections are now measured
from the origin. Both in `ddc7aec`.

**What this does not do is unblock `fit`.** The rate should fall by about half
and the concentration by more, but neither has been re-measured on production —
the replay is not the live system. Re-measure before lifting the gate, and note
that three of the four counting bugs found this day were only visible *because*
someone measured rather than reasoned.

### The other three found the same day

- **Volatility was estimated once per venue row too** (`18e95c0`), so it came
  out divided by the venues past quorum — 4x on EURUSD and GBPUSD, 3x on
  XAUUSD, 2x on BTCUSD. Every distance in volatility units read that much too
  large. This invalidates measurements, not just numbers: see [levels.md](
  levels.md) §10b and the agreement section, and [strength.md](strength.md).
- **`expire`'s return value was discarded** (`04d24c0`), so touches that
  resolved on the clock reached only the kNN memory — no `level.record`, no
  journal, no `facto`. Breaks went 11 to 61 and back checks 3 to 29.
- **The first-passage null was handed a MAD where it wanted a sigma**
  (`e5dec8d`), understating every reach probability by a quarter of a distance.

## 0y. What the weekend could not answer — read these first on a weekday

Everything measured on 2026-08-15 was measured on a Saturday, with FX and the
indices shut. Crypto was the only thing trading, so any number involving the
other eleven instruments is describing a closed market rather than a quiet one.
Several conclusions are provisional on that and are gathered here rather than
left scattered.

**0. There is a recorder running — read it first.** A cron entry on the
instance appends one measurement every thirty minutes to
`/home/ubuntu/rate-watch.log`, from `/home/ubuntu/rate-watch.sh`. It survives
deploys (the script lives on the host and copies itself into the container) and
logs "container down" rather than skipping, so a gap in the series reads as a
gap rather than as quiet.

Each row is one thirty-minute window: total outcomes, the outcome mix, and the
busiest cells as `feed/interval=count@per-1k-bars`. Two days of that is the
sample every question below has been waiting for.

It already settled one thing. On Saturday afternoon `eth` was resolving five
times as often as `btc` and none of the three structural explanations held —
zone width, level density and a lagging volatility estimate were all ruled out
by measurement. The first recorder row an hour later had **btc ahead of eth**.
So the ratio is not structural, and any explanation built on that hour would
have been a story.

**Six hours of it now say: mild, persistent, and nothing like five.** Across
twelve windows, 128 eth against 96 btc — a ratio of **1.3**, with eth ahead in
eight windows and btc in three. The 5x was one hour of noise, and an hour is
apparently enough to produce a factor of five in a rate this size. Worth
remembering the next time a single reading looks structural. Still crypto-only
and still a weekend; check it against a weekday.

**1. The outcome rate, properly this time.** Item 0 was answered but never
re-measured on a comparable population: 887/hour was a weekday across fourteen
instruments, and 40/hour was a Saturday across three. Measure a full weekday,
on a box that has not restarted for hours, and compare *per bar within the same
window* — not against all-time bars, which is a mistake this file made once
already and which turned 11,037 per thousand into "582".

**2. Whether the five FX pairs the gate declines deserve it.** `audusd`,
`eurusd`, `usdcad`, `usdchf` and `nzdusd` at 1m fail `MIN_TICKS_PER_ZONE` on
tick estimates taken while those markets were shut. `eurusd` produced four
outcomes in twenty-four hours, which says nothing. If they behave on a weekday
the floor is too high for FX and should come down.

**3. Whether the tick estimates for FX are real at all.** `audusd 3m` and
`eurusd 3m` report a tick of 0.00000-0.00001, which passes the gate for the
right reason only if the estimate has been exercised. It has not been since
Friday.

**4. The instant-resolution residual.** Crypto sits at 2.5% post-fix against
47.8% before, which is the headline result of the day. The session instruments
read 82.8% — but on twenty-nine outcomes from shut markets, which is not a
measurement. Re-read it when they trade.

**5. A trustworthy baseline for what a healthy rate even is.** `btc 1m` at 59
per thousand bars and `btc 3m` at 179 are the closest thing to a control, and
both were measured over a weekend too. Nothing here knows what the right number
looks like, which makes every other rate hard to judge.

**~~6. The outcome mix.~~ — answered on 2026-08-15.** It was almost all
rejects because the box kept restarting before a horizon could elapse. Six
uninterrupted hours give 233 outcomes at 39/hour:

| outcome | share |
|---|---|
| reject | 62% |
| trap | 23% |
| break | 11% |
| backcheck | 5% |

**38% of resolutions are not a bounce**, which is what this item was asking.
The model sees breaks and traps in quantity, so the pipeline is not degenerate
— and traps at 23% are a large enough class to be worth their own accuracy
number rather than being folded into "not a reject".

Two caveats. This is crypto on a Saturday, so it says nothing about the eleven
instruments that were shut, and the mix under a session open may differ. And a
62% reject share sits close to the "assume the level holds" base rate that
already beats the model ([features.md](../research/features.md) §3) — the mix
being healthy is not evidence the *predictions* are.

## 0z. Two things found on 2026-08-14, both ahead of everything below

The two learning-path bugs from the same day are **fixed** — the silent
`journal.read` clamp that starved `facto.dataset`, and the unscaled features
that diverged the FM. Both accounted for in [handoff.md](handoff.md). Neither
touches the two items below, and the first of them now matters *more*: a fit
can finally see the whole journal, so nothing but the warning below stops it
drawing 9,000 examples from one afternoon.

**The outcome rate needs explaining before any fit** — *the fourth route was
found; the rate itself still needs re-measuring.* The journal recorded 976
outcomes in one hour and 8,411 in six, against 76 the previous day, and the
guess was right: there was a fourth route to over-counting that the three touch
fixes did not close. It was `observe_bar` running the touch check at its own
interval during replay, which item 1 has now split out. On production
`own_touches` fell from 171 to 0.0.

**Re-measured on 2026-08-14 after the split, and it is not fixed.** 18,228
outcomes over 20.4 hours is **895/hour**, against the 976/hour that raised this
item; the three most recent full hours were 2,290, 2,257 and 2,285. Splitting
`observe_bar` fixed the *per-level* inflation — `own_touches` fell from 171 to
single figures — and did not touch the rate. Those were two problems wearing
one symptom.

The consequence this item exists for is therefore unchanged and now measured:
**200 consecutive outcomes accumulate in a median of 4.9 minutes**, fastest 1.1.
`MIN_EXAMPLES` is reached from five minutes of one afternoon, which is not a
spread of market conditions and not the dataset progressive validation assumes.

They are concentrated as well as fast. Of the last 5,000: `sol` alone accounts
for 2,430, and 3m and 5m for 4,305 between them, against 10 on 4h and none on
the daily or weekly. So a fit would learn one instrument on two fine
timeframes over one afternoon and report it as a model of everything.

**So `fit` stays gated, and the fourth route was not the last one.**

**Investigated, with one hypothesis refuted and one candidate measured.** The
re-arm hole is *not* it: `check` sets `waiting = contains(price)` after a
resolution, which looked like it bypassed `REARM_VOL`, but a reproduction
oscillating across a zone edge produced one resolution rather than dozens — a
small oscillation never resolves at all, it times out.

The candidate is **price granularity**. sol carries the same volatility as btc
and eth on one eight-hundredth of the price, so its smallest quotable step is
0.0726v against btc's 0.0083v — nine times larger as a fraction of a typical
move, and a fifth of a minimum-width zone. Price steps across a sol zone in
five ticks where btc needs forty. Numbers and the proposed remedy in
[levels.md](levels.md), "Price is not continuous, and the zone floor assumes it
is".

**Checked against a price gradient, and it is broader than sol.** Of eight
instruments, six have a tick worth more than a third of a minimum-width zone
and two — ADA and LTC — have a tick **larger than the whole zone**. The tidy
law is wrong though: tick-in-volatility against price fits a log-log slope of
−0.33, not the −1 that proportionality predicts, because exchanges set tick
sizes in decade steps. ADA at $0.18 is worse than SOL at $75.

So it cannot be predicted from price and has to be measured per instrument.
**Before adding any cheap instrument, measure its tick in volatility units** —
ADA today would be a sixth of the zone it is supposed to sit inside.

Still a candidate for the *rate* specifically: the granularity is measured, the
causal link to sol's 2,430 outcomes is not.

**The fix is shipped and unverified**, which is the open loop. `Level.zone` now
takes its floor as the larger of `MIN_ZONE_VOL` and six ticks, with the tick
read off a low quantile of observed changes — measured effect ADA 8.6x, LTC
6.9x, SOL 4.2x, btc and eth untouched. All of that measures *zone width*.
**None of it measures the outcome rate**, which is what the change was for.

So the next step is the same measurement that opened this item, run again after
the fix has been live long enough to matter:

```bash
sudo docker exec -i till-infinity python -c "..."   # outcomes per hour, by feed
```

What would confirm it: sol's share of outcomes falling from its half of the
total, and the per-hour rate dropping from ~895. What would refute it: the rate
unchanged, which would mean the zones were never the reason and the cause is
still unfound — the third time that has happened on this item, after the
re-arm hypothesis and the `observe_bar` split.

Do not treat wider zones as the answer until the rate says so. Widening a zone
also *reduces* touch counts mechanically, so a fall in the rate is necessary
evidence rather than sufficient — the question is whether the remaining touches
are better, and that needs the hold rate beside the count.

The older examples remain unusable regardless: recorded under the inflated
counts, and the pre-fix journal calls direction correctly 99.9% of the time
because a level's history and its next outcome were the same move counted
twice. `fit(since=)` exists for exactly this boundary. Do not fit across it.

**~~Agents have never woken~~** — done, and it was neither of the suspects. Not
the thresholds: left alone for thirty minutes the gate fired on its first
window, on 94,311 messages, naming usdcnh, nzdusd and usdchf. **It was the
window never closing.** `AGENTS_WINDOW_S` is 1800 in production and every
deploy restarts that timer, so on a day with deploys more often than every half
hour the gate never runs at all — which the "watch rather than act" note below
had predicted and nobody had connected to this item.

The analysis then died on `tool_calls_limit of 12 (tool_calls=14)`, a budget set
when six instruments were tracked and never revisited at fourteen. Raised to 32,
since the failure discards a whole judgement rather than truncating it. The
wake gate also now reports its closest approach at INFO rather than DEBUG, so a
gate that declines can be told from one that never ran.

Full account in [agents.md](agents.md), "Why agents appeared never to wake".
Still to confirm: that a window survives end to end now, which needs half an
hour without a deploy.

## ~~0a. Put 1m back on the level set~~ — done, and the detour is the lesson

1m was removed on 2026-08-14 to buy memory, and put back the same day once the
memory was actually measured. Keeping the whole shape because the mistake is a
better guide than the fix.

**The reasoning for removing it was wrong, and it was wrong in a way that
looked rigorous.** Two measured points — 42 series at ~232MB, 112 at ~400MB —
fitted a tidy 2.4MB per series, and that line predicted the failure. It was
still attribution by correlation: more instruments means more quotes per
second, which is what actually grew. Profiling the engine directly put its
retained structures at **0.15MB per series**, sixteen times smaller, so
dropping 1m from fourteen instruments saved about **2MB of a 400MB process**.
It changed no bus traffic at all, since `prices` collects 1m regardless.

**The memory was in the agents watcher.** It held every message of a
thirty-minute window — **101,297 messages, 199MB**, about half the resident
size at the moment of the kill — in order to derive fifteen triggers. The
window is bounded now at 20,000 messages (~40MB) and reports what it dropped.

Worth carrying forward: a curve fit through two points will happily predict the
thing you already saw while pointing at the wrong cause. The profiler took five
minutes and disagreed with it immediately.

**The window is streamed now**, not bounded: `Window` folds each message into
the running answer and keeps none, so the 101,297-message window that cost
199MB costs 464 bytes. `interesting()` folds a sequence into the same
accumulator, so there is one implementation rather than two that could drift.

**Still open:** swap does not exist, which is why an overshoot is a kill rather
than a slowdown — and that does not improve on a bigger box, it just gets
harder to reach.

## 0b. Three found on 2026-08-14 while tracing the silent channel

Ordered by what is holding back the most. All three are documented with their
measurements in [levels.md](levels.md).

**~~The spread cost charges zero on every call~~** — *resolved by item 1, watch
it.* `cost_of` reads a window filled by `observe_quote` only, and every recorded
call used to come off the bar path before any quote had landed, so the window
was empty and the charge a true zero — not a rounding artefact. Splitting
`observe_bar` moved when calls happen, and production now records a non-zero
`cost_vol`. Worth confirming over a longer run than the half hour it has had.

The measured charges are worth carrying in your head, because this gate is not
one threshold: 0.003v on btc against 2.5v on gbpusd 3m, so it is nearly free on
crypto and close to absolute on FX intraday. `STRUCTURES_CHARGE_SPREAD=0` turns
it off for comparison, and says so in the log while it is off.

**~~`risk_vol` is 0.0 on every recorded call~~** — done. `vol` was an optional
argument to `infer` with a zero fallback, so the risk geometry was something a
caller could forget, and all three callers did — each with `vol` right there in
scope. `reward_to_risk`, documented as the number that decides whether an edge
is worth taking, was therefore identically zero on every call ever journalled.
It stayed invisible because nothing gates on it and because zero reads as a
number rather than as an omission.

`vol` is now required rather than more carefully defaulted, so the next caller
cannot repeat the omission quietly. Both numbers are real: over a gold warm,
`risk_vol` on 16 of 16 calls and `reward_to_risk` spanning 0.45 to 3.12.

**And now gated.** `actionable` requires reward-to-risk ≥ 1.0 — a break-even
rather than a preference, since below it the predicted move is shorter than the
stop behind it. On the ratio and never on `risk_vol`, because risk is in each
timeframe's own units and 0.90 is $0.77 on 15m gold against $24.76 on the
daily; only the ratio travels. Measured cost: **13 of 35** otherwise-actionable
calls suppressed across gold, btc and eurusd, mostly large moves sitting behind
larger stops. Detail in [levels.md](levels.md), "The risk gate, and why it is a
ratio".

Raising it above 1.0 is the part that is a policy about capital rather than a
property of the model — the same argument as sizing in item 3 — and wants
outcomes behind it rather than a number that sounds professional.

**`0.08` was never derived from anything.** Not in the commit that introduced
it, not in the docs. It is the number currently separating signal from silence,
with the median call sitting five thousandths under it. It sits near the 97.7th
percentile of its own input — 2.3% of calls reach it — which is a defensible
place for a gate to be and not a chosen one.

Deriving it from the journal was **tried and does not work yet**: the pre-fix
data calls direction correctly 99.9% of the time at every level of `|edge|`,
against ~78% for independent series with those marginals, because inflated touch
counts made a level's history and its next outcome the same move counted twice.
Detail in [levels.md](levels.md), "The attempt to derive it, and why it failed".

So this waits on post-fix data. Then make it a rolling quantile of realised
edges rather than a constant — the same instinct as [score.md](score.md)'s
thresholds — rather than picking a new number by hand.

## 0c. Left open by the 2026-08-14 fixes, in the order they would bite

**~~Guard every pickled slots dataclass~~ — the important half is done, the
cheap half is not.** `_schema` now derives the fingerprint by walking the
package rather than from a hand-written list of seven, so a field added to any
of the twenty-seven persisted dataclasses invalidates the saved state and the
service starts cold instead of crashing on it (`98e45be`). That was the root
cause: the list existed, `Volatility` was not on it, and using it correctly
required knowing it was there. It fired correctly on its first real test —
`schema 25296b265b0805a0, this is c6229bdc019bc469 — starting cold`.

What is left is belt-and-braces: fourteen of those classes still have no
`__setstate__`, so if state is ever loaded that the schema did *not* catch, the
read still raises. The schema stops bad state being loaded; a `__setstate__`
stops a crash if it ever is. Lower priority now, and it wants one shared mixin
rather than a fourth hand-written method.

**Confirm the engine fixes on production — mostly done, one number left.**
Measured over 87 outcomes on 2026-08-14:

| | before | after |
|---|---|---|
| instant | 47.8% (n=18,709) | **9.2%** |
| back checks | 1, all history | **30** |
| breaks | 43, all history | 3 in two hours |
| bus drops | 372/min | 0 |

The back check number is the one to notice: it was not low because back checks
are rare, it was low because `expire`'s resolutions were discarded and
`broke_at` is what makes a retest detectable.

**Still unread: whether negatives went to zero.** They went the wrong way first
— 1.7% before the clock fix, 5.7% after it, because stamping a bar at its close
puts the *forming* bar in the future. `e02e7d7` clamps to now and has no sample
yet, because it deployed into the cold start above. Read it next sitting.
Until then item 4's gate stays shut.

**The box is re-learning from cold.** The schema change was correct and cost the
accumulated touch history and kNN memory. Levels re-form from stored bars, but
the per-level statistics that `quality_l` depends on start from nothing, so the
strength work below has no history behind it for a while.

**Replace `Level.strength`, do not merely stop multiplying it.** Removing
confluence breadth from `Zone.strength` was the cheap half.
[strength.md](strength.md) finds the composite loses to its own best term in
every run — AUC 0.548 against 0.648 for the level's own same-side record — and
this number is not only reported: `reactions.py` passes it into the model as a
feature. Mixing one signal that works with three that do not is diluting the
feature the model is given. The proposed `quality_l` is unfitted and beats it on
all four runs. Prerequisite is touch counting being trustworthy, which is item 0.

**One horizon serves every timeframe.** `Tracker.horizon` is 3,600 seconds
whatever the interval, so 1,054 of 1,270 chops in the absorption replay are 4h,
1d and 1w touches labelled by the clock rather than by price. A daily level
cannot resolve at all inside an hour. Make it a multiple of the interval, the
same argument as evidence half-life in [levels.md](levels.md) §10b.

**`Touch.energy` divides by `approach_vol` with no floor** and reaches 4.6e10
in a replay. Nothing consumes it yet, which is the only reason it has not
already poisoned something — the same shape as the unbounded features that
diverged the FM.

**Record press depth on every touch.** [absorption.md](absorption.md) measures
it non-zero on 68.8% of real interactions against `excursion_vol`'s 25.2%; the
quantity [behaviours.md](behaviours.md) nominates is zero on 82.7% of touches,
so the thing being modelled is mostly absent. Cheap, and it is a measurement
input rather than a feature.

**~~`0.08` is now derivable~~ — derived. See [edge.md](edge.md).** The blocker
was inflated touch counts making a level's history and its next outcome the
same move twice, which showed as the direction being called correctly 99.9% of
the time at every level of |edge|. Fixed, and it now reads 71.1%, so the
measurement means something.

Two results, one of them against what this file used to say:

- **0.08 sits inside a flat region and should be 0.11.** Below roughly 0.11,
  direction runs 54-61% — a coin flip with a push near zero — and at 0.11 it
  steps to 75%. Six instruments out of six show the same step. The gate also
  is not where it was believed to be: on corrected data the median |edge| is
  0.1373, so 0.08 is *below* the median and passes 69.6% of calls, against the
  2.3% recorded in [levels.md](levels.md).
- **Keep it a constant. Do not build the rolling quantile this item used to
  ask for.** Against the constant that passes exactly the same number of
  calls, the rolling rule is four to ten points worse on direction at every
  selectivity tried, and 9 of 24 cells never reach the 50 calls it needs.
  `edge` is a difference of two probabilities and so already means the same
  thing on every instrument; normalising it per cell destroys that. The
  instinct is right for anything in volatility units and wrong here, which is
  the distinction worth keeping.

**Can it be computed rather than chosen? Yes, and it buys maintenance rather
than accuracy.** Accuracy-targeting — the lowest |edge| whose *realised*
accuracy clears a target, re-estimated from outcomes and kept global — looked
like a clear win over the whole replay, +3.6 to +5.1 points. Scored on the
second half alone at matched volume it is **equal to a constant three times out
of three**. The earlier margin was the rule riding the warm-up drift; its own
threshold fell from 0.26 to 0.06 across the replay.

So it is worth building, for a different reason than the one this item
originally gave. `0.08` was defensible when set — 97.7th percentile, passing
2.3% — and today passes 69.6% without anyone touching it. A constant is as good
as the adaptive rule *provided somebody keeps re-deriving it*, and nobody did.
The evidence-scaled form `z * sqrt(p(1-p)/n)` is the more principled shape and
has nothing to work with today — see the item below, which is its prerequisite.

Not yet done, and deliberately: the constant is unchanged in code. The
measurement is a bars-only replay, and today established twice that the quote
path behaves differently enough to overturn a replay result. Re-derive on
production once there are enough post-fix outcomes, then move it.

**~~Let `k` reflect how much similar history there actually is~~ — measured
first, and the radius must not be built.** The plan was a similarity cutoff so
the neighbour count would mean something. The cutoff was measured before being
built and the measurement killed it: **the nearest twelve neighbours predict no
better than twelve at random** (72.9% against 72.7%), and pairwise agreement
*rises* with distance across every control — within a cell, across cells, and
restricted to pairs more than a day apart. `Features.distance` does not order
neighbours by relevance. Full numbers in [edge.md](edge.md) §6.

The kNN prior still works — twelve neighbours call the direction correctly 73%
against a 51% base rate — but the similarity is not what does it. A pooled vote
of recent touches captures the market's prevailing direction, which is the same
dependence that makes any two touches agree 57-62% a day apart.

So the open item is the **metric**, not the cutoff: which features belong in
`Features.distance` and with what weights is an empirical question nobody has
asked, and until it is asked a radius would only restrict the pool to
neighbours carrying no advantage. Two smaller consequences stand on their own:
the `1/(1+d)` weighting in `prior` gains 0.9 points over unweighted and still
loses to the farthest twelve, and the alert's "+12 similar" is decorative
wording for a count that is always twelve.

Original reasoning, kept because the three consequences are still true:

- **`Inference.neighbours` is not an evidence count**, though it reads as one
  and is printed in the alert as "+12 similar".
- **The shrinkage cannot weaken when it should.** `prior` shrinks toward the
  base rate with `weight = len(found) / (len(found) + PRIOR_WEIGHT)`, so twelve
  distant strangers are trusted exactly as much as twelve close matches.
- **The evidence-scaled gate has nothing to bite on.** Measured over 2,003
  calls, the effective count runs 12.5 / 13.8 / 15.3 across the quartiles, and
  a rule of the form `|edge| >= z * sqrt(p(1-p)/n)` is therefore almost a
  constant in disguise. See [edge.md](edge.md) §4.

The change is a similarity radius: take neighbours within a distance cutoff, up
to `k`, rather than the nearest `k` unconditionally. `Features.distance` is
already scale-free, so a cutoff means the same thing on every instrument. Then
the count means "how much genuinely comparable history exists", the shrinkage
follows it honestly, and the evidence-scaled gate becomes testable.

Pick the cutoff by measuring, not by choosing: the distance distribution of
neighbours that did and did not predict correctly will say where similarity
stops carrying information.

**Make the agents service better: faster, more accurate, and pointed at
meaning rather than at numbers.** *Found on 2026-08-15 while reading the
alerts: **news can never wake the agent**, and the news specialist never runs.*

`Window.observe` dispatches on `SIGNALS`, `QUOTES` and `EVENTS`. `ARTICLES` is
in `TOPICS` and subscribed to, and there is no branch for it — so a headline is
readable once the agent is awake and is never the reason it wakes. `BARS` is
subscribed and unhandled too. Every trigger is therefore a price trigger: the
loudest structures signal per feed, the worst spread, and calendar releases
that printed.

And only one role runs, `DEFAULT_ROLE = RISK`. `MACRO` — the role whose whole
lens is the calendar and "several independent outlets converging on the same
story" — is never instantiated in production. That is why every alert in the
channel is a spread, a stale quote or a divergence.

**Wiring `ARTICLES` to a trigger on its own would produce noise**, and today's
research says why: [news-dedup.md](news-dedup.md) found the corpus contains no
observation of independent outlets converging — 94 of 105 duplicate groups are
one outlet counted twice by our own collection — so `MACRO`'s headline lens is
looking for something the data does not contain. And symbol normalisation is
unbuilt, so half the corpus cannot be routed to an instrument at all.

So the order is the one [news-models.md](news-models.md) §2 already gives:
symbol normalisation, then keyword matching against TradingView's tagged rows,
then a headline trigger, then the join with price. Wiring the trigger first
inverts it. Today the roles read prices and structures
and describe what changed. The more valuable half is the news — what a headline
*means* and what intent sits behind it — with the technicals brought in as
corroboration rather than as the subject.

Concretely, in the order the groundwork exists:

- **Intent and meaning from the news, not keywords.** [news-models.md](
  news-models.md) ranks what fits on this box, and [news-dedup.md](news-dedup.md)
  settled the first question on it: deduplication is hygiene, not signal, so
  the restatement count is not the feature. Symbol normalisation (§2 there) is
  the real prerequisite, because nothing routes without it and half the corpus
  is untagged.
- **Then join the technicals to it.** A headline that means something about
  the dollar is worth more when EURUSD is sitting at a level with a record —
  which is exactly what `agents/data.py` already exposes. The join is the
  product; either half alone is what we have now.
- **Faster.** The window is the scarcest resource in the system. See
  [bandits.md](../research/bandits.md): choosing which instruments deserve the
  ten trigger slots is the one genuinely bandit-shaped problem here, and the
  incumbent policy is "first ten past the gate".
- **More accurate.** The spread finding on 2026-08-14 reported a reading "at
  the historical maximum" against a maximum computed over a window containing
  it. That class of error is a tool-framing problem, fixed in `05a0abf` for
  spreads; the other tools in `agents/tools.py` want the same read-through.

**The directional call does not beat "assume the level holds", and the feature
set is why.** Measured in [features.md](../research/features.md), and it is the
most serious finding of 2026-08-14 because it is about the premise rather than
the plumbing.

- **`side` alone predicts direction at 78.8%; all nine features together
  manage 77.8%.** Dropping side costs 26.6 points and drops the model to
  chance. Dropping any other feature costs nothing, and three of them are worth
  negative accuracy.
- **The trivial rule beats us at every gate.** A touch from above pushes back
  up: 77.7% against the edge sign's 71.1%, and still ahead at 0.08, 0.11, 0.14,
  0.20 and 0.30. The two converge as the gate tightens — 97.8% agreement above
  0.20 — so a high-edge call is nearly always just restating the trivial rule,
  and the disagreements are where it loses.
- **Generated features do not rescue it.** Pairwise products are 3.3 points
  worse, a random Fourier basis 1.3 worse, target encoding neutral.

This explains the kNN result above rather than sitting beside it:
`Features.distance` is a metric over eight features with no directional signal,
so of course it could not order neighbours by relevance.

What it does *not* say: the gate still selects larger moves — mean realised
push rises from 0.73 to 1.83 across the same thresholds — and magnitude and
risk are untested. So the gate earns its place and the direction does not.

The next step is not a model. It is **what to measure at a touch**, because
nothing currently collected predicts direction beyond the side, and no amount
of modelling fixes that. Until then, `facto.Report` should carry "assume the
level holds" as a baseline alongside the two it already compares against.

**~~Decline the instrument and timeframe pairs that cannot support a level~~
— built, `ef7fa71`, with one thing to re-check.** Asked whether more
instruments can be added, especially crypto and indices. Resources say yes;
the model says *it depends on the pair*, and that is measurable before adding
anything.

The number that decides it is **ticks per zone** — how many price steps fit
inside a level's band. Price is supposed to enter a band, react, and leave. If
the venue's tick is a large fraction of a typical move, price cannot enter it,
only jump across, and every crossing becomes a touch. Measured on the
instance:

| pair | ticks per zone | |
|---|---|---|
| sol 3m | 2.5 | unusable |
| sol 1m | 2.7 | unusable |
| **audusd 1m** | **2.7** | unusable |
| sol 5m | 3.5 | unusable |
| nzdusd 1m | 4.1 | marginal |
| eurusd 1m | 5.9 | marginal |
| spx500 3m | 6.7 | marginal |
| btc 5m | 170.2 | fine |
| gold 15m | 109.7 | fine |

**It is not a crypto problem.** `audusd 1m` is as bad as sol, and six FX pairs
are marginal at 1m — coarse pip quoting does what a cheap coin does. It is also
not fixed by the zone floor: `GRID_ZONE_VOL` stopped the zone being absurdly
*wide*, which was making everything a touch; what remains is a zone only two or
three ticks across, which is the opposite failure and the one
`MIN_ZONE_TICKS` was originally added for. Both ends are bad, and the honest
answer is that the pair cannot be modelled at that resolution.

So: **form no levels where ticks-per-zone falls below a floor**, log it once,
and let the coarser timeframes for that instrument carry it. sol is fine at
15m and up; it is noise at 1m and 3m. This is the same shape as `trading()` —
refusing to produce rather than producing something meaningless.

Then the answer to "can we add more" becomes mechanical:

- **Indices are safe.** spx500 and us100 sit between 6.7 and 36 ticks per zone.
  More of them should behave.
- **Cheap crypto is not**, at fine timeframes. ADA at about \$0.18 was already
  measured with a tick larger than the whole zone, which is worse than sol.
  With the gate they would simply carry fewer timeframes rather than poison
  the sample.
- **Measure before adding, not after.** `Engine.supports(feed, interval)` is
  the check and it now runs itself: `reform` forms nothing for a pair below
  `MIN_TICKS_PER_ZONE = 4`, drops whatever was already formed on that geometry,
  and logs it once.

**What it declines today, and the one thing to re-check.** Eight of fifteen
sampled pairs: sol at 1m, 3m and 5m, and audusd, nzdusd, eurusd, usdcad and
usdchf at 1m. sol keeps 15m and coarser, so the instrument is not lost, only
the resolutions it cannot carry.

More than the observed widths suggested, because `supports` judges the **floor**
zone rather than the widened one — wicks make an established level roomier, but
a new level gets the floor and the question is whether to form one at all.

**The FX pairs were assessed over a weekend, with those markets shut.** Their
measured rates say nothing — eurusd produced 4 outcomes in 24 hours, which is a
closed market rather than a quiet one. Re-check those five on a weekday: if
they behave, the floor is too high for FX and should come down. Erring toward
declining in the meantime, because losing a good pair costs alerts visibly
while keeping a bad one poisons the sample invisibly — sol alone was half of
every outcome in the journal.

Resource headroom, so the other half of the question is answered too: memory
257MB of a 2.6GB cap, disk 235GB free at about 461MB a day of quotes, no bus
drops. **CPU is the binding constraint**, at 76.4% of a 150% allowance —
doubling the instrument count would reach the `--cpus 1.5` ceiling before
anything else complained.

**Quotes have no retention, and they are three quarters of the prices file.**
`prices prune` covers bars only, and the reason written into `store.prune` was
wrong in both halves: quotes are not bounded by `dedupe_quotes`, and bars are
not what grows. Measured on the instance:

| object | size |
|---|---|
| quotes | 333.2 MB |
| quotes_series_ts | 212.3 MB *(index)* |
| quotes_feed_ts | 191.3 MB *(index)* |
| bars | 51.7 MB |
| bars_series_ts | 36.2 MB *(index)* |

Quotes are 76% of the file and their two indexes cost more than the rows.
`dedupe_quotes` skips a quote whose price is *unchanged* — it lowers the write
rate in a quiet market and deletes nothing. On the instance quotes spanned
39.3 hours, which was the **entire age of the database**: not one had ever been
removed, at roughly 64,000 rows an hour, about 450MB a day.

The first prune ever run dropped 27,004 bars and a VACUUM took the file from
787MB to 567MB, so the bar half is now handled. The quote half is not.

Two things to decide together, because they pull in opposite directions:

- **Retention** would cap the growth. 450MB a day is nothing against 242GB, so
  this is no longer urgent — but unbounded is still unbounded, and the indexes
  make each row cost triple.
- **The item below wants the opposite**: microstructure at a touch is
  unanswerable precisely because quote *history* does not survive. Cutting
  retention harder makes that worse.

The resolution is probably that they are not in tension at all. Snapshotting
what a touch needed — spread, dispersion, staleness — into the touch itself
makes the raw quotes disposable, which is what allows a short retention rather
than what argues against it. Do that one first.

**Snapshot the microstructure state into a touch when it opens.** The
question "what should we measure at a touch" is answered in
[research/features.md](../research/features.md) for everything derivable from
bars: nothing predicts direction beyond `side` except the level's own record,
now added as `up_rate`. The candidates that remain are microstructure, and they
cannot be tested — not because they were tried and failed, but because there is
no history to try them on.

`quotes` holds **8.6 hours** against years of bars. It is a rolling recent
window, so a quote-driven replay yields a handful of touches where the bar
replay yields two thousand. That is also the concrete reason every result in
`research/` is bars-only, and why a replay has twice disagreed with production.

Retaining every quote is the wrong fix — expensive, and mostly noise. Write the
state into the touch instead, at `Tracker.begin`, exactly as `up_rate` now
records the level's record:

- spread in volatility units at the moment of contact, not the windowed median
  `cost_of` already keeps
- cross-venue dispersion, which `features.Book` computes for the anomaly
  detector and never shares
- staleness of the freshest venue, and how old the quote driving the touch is

All three are already computed somewhere in the process and thrown away. Then
the question is answerable from the journal in a few weeks rather than never,
and the two weak candidates already measured — venue dispersion at +3.1pp
within cell over 11 of 13 cells, volume at +2.3pp over 9 of 13 — get a sample
large enough to settle them.

Order flow proper stays out of reach: there is no book, which is the same wall
[absorption.md](absorption.md) hit. That one is a data-source question, not a
retention question.

**Form levels at momentum turns, not only at price turns.** Asked directly:
are we already doing this? **No.** `momentum`, `velocity` and `acceleration`
appear nowhere in the package. The two formations that exist both segment on
*price*:

- `pips.points` picks bar extremes and waits `confirm` bars to call one a turn.
- `runs.points` ends a run when price has retraced from its extreme by
  `RUN_SWING_VOL` volatility units — displacement, not rate.

The nearest thing to momentum is `Engine._speed`, one bar's change over the
previous in volatility units per bar. It is computed only at the instant a
touch opens, becomes `Features.approach_vol`, and is used nowhere else.

The proposal is a third formation and it is well posed: segment the series by
where the **rate of change** turns rather than where price does, and take the
last bar before that turn as the *momentum origin* — the same role
`touch.origin` plays for a reaction, the point where the leg stopped
extending. Momentum turns lead price turns, so a level drawn there sits where
the move began losing its push rather than where it finally stopped, and those
are different prices.

It is cheap to test and the machinery is already built for exactly this
comparison. `Engine(formation=...)` takes `pip`, `run` or `both` and
`levels.form` consumes whatever `Point` objects it is handed, so a
`momentum.points` producing the same shape drops in beside the other two. Then
`research/harness/` replays all three over one history and the outcome
machinery says which set price respects — the same question
[levels.md](levels.md) leaves unresolved for pip against run, and which
[strength.md](../research/strength.md) showed was measured on a broken
volatility denominator anyway and needs redoing regardless.

One caution from what is already measured, and it cuts both ways.
[research/features.md](../research/features.md) found `approach_vol` predicts
nothing about direction once side is known — so momentum *at a touch* is not
informative. That is not evidence against momentum-derived *levels*: the claim
here is about where a level should be drawn, not about what predicts once
price arrives. But it is a reason to test the formation on outcomes rather than
assume the idea transfers.

**Two smaller ones.** `yahoo.to_bars` converts an entire frame and then keeps
only the last `bars` of it; slicing first is much faster but changes the count
when rows are dropped as NaN, so it needs a decision rather than a patch. And
the agents' spread finding reports a reading as being "at the historical
maximum" while computing that maximum over a window *containing* the reading —
true by construction, and it belongs in the tool's framing rather than the
prompt.

**A deploy is an outage.** Every push restarts the container, including
docs-only ones, and four this afternoon each cost a backfill. `e4b0f3f` stops a
backfill starving the consumer, which shortens it, but does not make a restart
free. Batching pushes is the cheap discipline; not rebuilding on a docs-only
change is the real fix.

## ~~1. Split `observe_bar`: form from own bars, touch from the finest~~ — done

Every bar forms levels for its own interval; only the finest interval touches,
against every interval at once — the replay equivalent of `observe_quote`.

The documented trap was the wrong one to worry about. What actually bit is that
**"finest available" is not the globally finest series, it is the finest one
available *at that moment*.** Venues keep years of 1w and days of 1m, so a few
hundred bars per interval covers hours at 1m and years at 1w; pinning the check
to 1m left every earlier era untouched, 1w and 4h opened *zero* touches across
20,159 replayed gold bars, and their levels were pruned for never having been
visited. Twenty-one levels became four. The touch source now hands over as finer
history begins.

Measured rather than argued, on the same history: levels 20 → 21, touches median
2.0 → 2.9, max 11.1 → 14.0, none at or above 100 in either. Coarse levels
register interactions they previously could not see — 1d median 1.5 → 3.3, 4h
1.8 → 5.5, 15m 1.3 → 9.1 — and the absence of inflation is what says the trap
was avoided.

**On production the effect is what it was meant to be:** `own_touches` fell from
171 to 0.0, and the spread cost started charging for the first time. Alerts are
still gated by `0.08` above.

One casualty worth remembering: adding `_touch_eras` to `Engine` took structures
down on deploy, because state is a pickle and unpickling never calls `__init__`.
See [structures.md](structures.md) on persistence.

Detail: [levels.md](levels.md), "The live path is already fine".

## ~~2. Split `RUN_VOL` into arrival and departure constants~~ — done

`ARRIVAL_RUN_VOL` and `DEPARTURE_RUN_VOL`, equal at 0.5 because nothing yet says
they should differ. They answer different questions: the arrival threshold
decides where the level *is*, and being wrong moves every statistic the level
owns; the departure threshold decides how much of what followed counts as this
reaction, and being wrong changes one feature.

Each leg is now sabotage-checkable alone — disabling the departure rule fails
only the departure test, and the arrival test still passes.

## ~~3. Wire the measured spread into `cost_vol`~~ — done

Quotes carry `spread_bps`; the engine keeps a window of them per instrument and
charges the **median**, in volatility units, to every level call. A median for
the reason the consensus is one — a mean is dragged by the outlier it exists to
ignore. An exponential average was tried first and failed its own test: at a 0.1
weight a single hundred-fold print moved the charged cost tenfold, which would
have silenced a whole instrument until it decayed.

Some signals will now stop qualifying. That is the point of it.

Three further steps stand between this and anything resembling a buy/sell
decision, and they are listed so nobody mistakes a good model for a decision:

- **Calibration.** MAE says predictions are close on average; it does not say
  that when the model claims 80% it is right 80% of the time. Confidence is
  what any sizing rule consumes, so it has to be checked directly — bucket the
  predictions, compare claimed against realised.
- **Sizing.** `risk_vol` and `reward_to_risk` describe how wrong a call can be.
  Turning that into a position is a policy about capital, not a property of the
  model, and it belongs to whoever owns the capital.
- **Out-of-sample evidence.** Progressive validation gives this honestly by
  construction; it needs the examples.

`facto` sits *after* all three. It sharpens an estimate that first has to be
measuring the right quantity.

## 4a. The concentration gating `fit` was geometry, and is fixed

`sol` was 4,940 of the last 24 hours' 9,863 outcomes — half of everything —
which is what item 4 means by a fit learning one instrument and reporting it as
a model of everything. Measured per bar, so "more bars means more outcomes" is
removed:

| cell | outcomes per 1,000 bars |
|---|---|
| **sol 3m** | **582.0** |
| sol 5m | 429.9 |
| eth 3m | 159.2 |
| btc 3m | 62.8 |

A resolution every 1.7 bars on sol against one every sixteen on btc. That is
not a sampling problem and no stratification fixes it; it is the zone.

`MIN_ZONE_TICKS = 6` is a sensible floor while a tick is a small part of a
typical move. **On sol a tick is 0.378 volatility units**, so six of them is
2.27 — wider than `resolve_vol`, the distance a touch must travel to resolve at
all. sol's zone measured 2.268v against btc's 0.484v, 4.7 times wider in the
only units that compare, so it caught 4.7 times the price action.

The floor added on 2026-08-14 to stop price crossing a zone in a few ticks
over-corrected: it made the zone enormous instead. `GRID_ZONE_VOL = 0.75`
bounds the grid-derived part at half of `resolve_vol`, so the ladder alone can
never open a zone wide enough to resolve a touch. The filter's own uncertainty
and observed wicks may still exceed it — those are evidence about this level,
where the grid is a fact about the venue.

**Prediction, so this one is falsifiable unlike the last zone change.** sol's
zone half falls from 2.268v to 0.75v, three times narrower, so sol 3m should
drop from 582 per thousand bars towards roughly 200 — closer to eth's 159 than
to btc's 63, because sol's grid is still coarse, just no longer unbounded. If
it does not move, the tick is not the cause and this document is wrong.

Not verified on the replay: the local prices database holds no `sol`, so the
instrument this is about cannot be measured there. It has to be read off
production.

## 4. `fit(since=)` once 200 post-fix outcomes exist

No code needed. The counter restarts from the **2026-08-14** fixes, not the
13th's: examples recorded under inflated touch counts and a pooled base rate
describe a model that no longer exists, and half of everything recorded before
the 14th was a touch resolving at the instant it opened. Detail:
[structures.md](structures.md), "Examples have an expiry".

The count therefore starts from zero again as of `ddc7aec`, and at the corrected
rate — roughly half the old one, with the concentration on `sol` 3m and 5m
unmeasured since — 200 outcomes is a longer wait than the 4.9 minutes item 0
recorded. That is the point of the gate rather than a problem with it.

## ~~5. Run-formed levels — built, run, and answered~~ — done

`runs.py` and `Engine(formation="run")` exist; the comparison has been run.
Detail and the numbers in [levels.md](levels.md), "Built and run, 2026-08-14".

**The resolution claim holds** — 26 of 27 coarse run boundaries appear in the
fine set against 5 of 7 bar extremes, and that is now a test. **The outcome
comparison did not settle anything**: run formation lost 83.3% to 59.7% on gold
alone and won 82.2% to 79.5% across three instruments. A 24-point gap that
looked decisive was sample noise.

Both flaws are fixed: resolutions are drained *during* the replay through the
progress callback, so nothing is censored, and four instruments at 400 bars
raised the decisive samples from 36 to between 624 and 1,133.

**On hold rate, PIP still wins narrowly** — 81.6% against 77.9% — but now on
samples that mean something. **The merge is what earned its place**, and not
for accuracy: it finds twice the levels at a hold rate two points lower, and
agreement between the formations turns out to predict holding. See 5a.

Left open: `both` is not the default, and the pip-versus-agreement ordering is
unresolved on 50 interactions. More history would settle it.

## ~~5a. Merge the two formations rather than picking one~~ — done

`Engine(formation="both")` forms each way and merges; `lv.agree` keeps every
formation that found a level, so `origin` reads `pip+run` where they concur.
Merging rather than pooling the swings, so a bar extreme and a run boundary a
hair apart cannot form a level *between* them and lose which pass found it.

**Agreement predicts holding**, which is what the merge was for: a level both
passes find holds 80–83% against 75–77% for run-only, at every threshold
tested, on samples in the hundreds. It does not clearly beat PIP alone — that
comparison is unresolved on 50 interactions. Numbers in
[levels.md](levels.md), "Agreement between the formations is a real strength
signal".

Left deliberately: `both` is not the default. It roughly doubles the level
count for a hold rate two points lower, which is a coverage-for-quality trade
somebody should choose knowingly rather than inherit.

## 5b. Weak and strong, as a first-class notion

Nothing in the model currently says a level is *weak* except `strength`, which
is a continuous score mixing touches, agreement, recency and breadth, and which
is consumed nowhere as a decision. There is no point at which the system says
"this one is worth less" and acts on it.

Three sources of evidence were proposed for that judgement. **All three have
now been measured** ([strength.md](strength.md)), and only one of them earns
its place:

- **What it has done — yes, and by a wide margin.** A level's own same-side
  record separates holds from fails by +32.8 points on corrected code, and the
  separation *grows* with the gap since the last touch (+25.1 at 20 bars or
  more), which answers the obvious objection that it is just measuring a
  grind. Point-in-time safe, since `SideStats` at contact holds only resolved
  interactions — but only trustworthy while touch counting is, so item 0 is a
  prerequisite rather than a nicety.
- **How it was found — no, and the earlier evidence was an artefact.** The
  agreement result in [levels.md](levels.md) was measured on the broken
  volatility denominator, and it **inverts** on the corrected one. Origin came
  out of the design. Status is unresolved rather than reversed, and either way
  it is not a validated input.
- **How many timeframes see it — no.** Confluence breadth does not separate at
  all: four runs, four orderings, AUC 0.45-0.51, bootstrap -2.2 [-6.3, +1.7].
  The 15%-per-timeframe multiplier it used to earn has been removed from
  `Zone.strength`, since that ordering decides what the agents are shown.

A fourth finding matters more than any of them: **the existing `strength`
composite loses to its own best term** in every run (AUC 0.548 against 0.648
for the record alone). Mixing touches, agreement, recency and breadth into one
number dilutes the one part that works with three that do not.

[strength.md](strength.md) proposes a concrete `quality_l` built from the
record and experience only, graded *within* `(feed, interval)` — the grading is
load-bearing, since chart identity alone reaches AUC 0.586-0.608. It is
unfitted and beats `Level.strength` on all four runs. The open risks are the
quantile window, which leaks unless it is causal, and the trap classification:
with 12 breaks against 933 traps, counting a trap as a hold makes everything
read 99.8% and nothing separates.

Two places it should show up:

**In levels**, as a grade rather than a hidden float. The zone width, the
`|edge|` gate and the reward-to-risk floor could all reasonably move with it: a
strong level deserves a tighter zone and a lower bar, a weak one the reverse.
Today every level is gated identically no matter what is behind it.

**In the [score](score.md)**, which is where it matters more. The score is one
number per instrument and a level call is its main input, so a call from a weak
level and one from a strong level currently contribute the same. They should
not. The score's own thresholds are already designed as rolling quantiles
rather than constants, and level strength wants the same treatment — graded
against what strength has looked like recently, not against a number somebody
picked.

**The trap, and it is the same one as everywhere else here.** Grading levels by
what they have done and then measuring how well the graded levels do is
circular. The grade has to be formed from evidence available *before* the
interaction being judged, which is exactly what `as_of` and the journal's
copied-in context already exist to enforce. Do not skip it because the
arithmetic looks harmless.

## 6. Build the score

Designed in [score.md](score.md), not built: one number per instrument in
[-1, +1], three EWMAs, thresholds as rolling quantiles, transitions only.

## 6b. Let the constants adjust themselves

The pattern this project keeps rediscovering is not that a particular number
was wrong. It is that **hand-set numbers go stale and nothing notices**:

| constant | set to | what measuring found |
|---|---|---|
| `0.08` edge gate | a judgement | passed 2.3% of calls when set, 69.6% by 2026-08-15 — below the median |
| `HALF_LIFE` | 60 bars | optimum is 7-10 at every interval ([volatility.md](../research/volatility.md)) |
| `MIN_ZONE_TICKS` | 6 | opened a 2.27v zone on sol, wider than `resolve_vol` |
| `MAX_ZONE_VOL` | 3.0 | twice `resolve_vol`, so a touch could be born resolved |
| `DEFAULT_K` | 12 | a fixed count, so the neighbour count carries no information |

Five for five, and each was found by measuring rather than by anything in the
system complaining. That is the argument for adaptation, and it is structural
rather than a list of numbers to re-pick.

### The mechanism is expert aggregation, not a bandit — mostly

The instinct to reach for a bandit is close but not quite right, and the
distinction is the same one [bandits.md](../research/bandits.md) draws for the
alert gate. A bandit exists to handle **partial feedback**: it sees the reward
of the arm it pulled and never the others. For a parameter like `HALF_LIFE`
there is no such limitation — several estimators can run side by side and every
one of them is scored against the same realised move, every bar. That is full
feedback, and with full feedback **expert aggregation beats a bandit**: run the
candidates, weight them by recent loss, and let the weights move. `river` has
`EWARegressor` and the `ensemble` module for exactly this shape.

So:

- **`HALF_LIFE`** — the obvious first candidate, and **measuring it produced
  the most important correction to this whole section.** Weighting several
  half-lives by realised *forecast* loss would optimise the wrong thing:
  [volatility.md](../research/volatility.md) found the forecast optimum at 7 to
  10 bars, and running the edge machinery at each half-life found the calls do
  not improve — h=7 and h=10 are worse on direction than the current 60, and
  the spread across all four is 3.1 points against a standard error of 1.1.

  So **whatever adapts must be scored on outcomes, not on the quantity it
  predicts.** That is harder: a forecast is scored every bar, an outcome takes
  hours, and the loop that closes in hours cannot use the per-bar aggregation
  that makes this cheap. Any scheme here has to confront that gap rather than
  quietly optimise the convenient metric — which is exactly the mistake the
  measurement caught before it was made.
- **`resolve_vol`, `MIN_ZONE_VOL`, `GRID_ZONE_VOL`** — harder, because their
  loss is not observable per bar. These feed touch outcomes, so the loop closes
  in hours rather than bars, and the honest form is periodic re-derivation
  against realised outcomes rather than online weighting.
- **The edge gate** — already designed in [edge.md](edge.md) §4 as accuracy
  targeting, and already measured: **equal to a well-chosen constant at matched
  volume, three times out of three.** Its value is maintenance, not accuracy,
  which is precisely the argument of this section rather than an exception to
  it.
- **The agents' attention budget** — genuinely a bandit, for the reason the
  others are not: analysing gold tells you nothing about what analysing btc
  would have found. See [bandits.md](../research/bandits.md).

### The trap to design against

Adaptation makes a system that *looks* responsive while being harder to reason
about, and this project has already been bitten by drift-following once:
edge.md §4's accuracy-targeting rule looked like a +3.6 to +5.1 point win until
it was scored on a homogeneous window, where the margin vanished entirely. It
had been riding the replay's warm-up trend.

So any adaptive rule here needs the same discipline the constants now get:
**scored against the fixed value it replaces, at matched selectivity, on a
window without a trend running through it.** An adaptive parameter that merely
tracks a drift is not better, it is only harder to audit.

## 6a. Model the next major turn, not just the next touch

Everything built so far answers a question measured in minutes: price has
arrived at a level, which way does it go and how far. A **major turn** — the
end of a trend, the reversal that matters over weeks — is a different object,
and nothing here models it.

What exists to build on, and what each is not:

- **`drift.py`** already answers "has what counts as usual moved?" with ADWIN
  across timeframes, and a drift *invalidates* accumulated history rather than
  predicting anything. It says the regime changed; it does not say a turn is
  coming, and it says so after the fact.
- **BOCPD** (item 7) would *grade* a change rather than flag it. Closer, still
  retrospective.
- **`score.md`** (item 6) is one number per instrument in [-1, +1] with
  transitions. That is the shape a turn signal would have to take, and it is
  the natural home for this rather than a new subsystem.
- **The momentum-turn formation** in §0c is the same idea two scales down —
  where a leg loses its push rather than where a trend does. If it works at the
  swing scale it is evidence the framing transfers; if it does not, that is
  worth knowing before attempting the harder version.

### The problem that makes this hard, stated first

**Major turns are rare, and the sample is the whole difficulty.** Fourteen
instruments with a handful of genuine reversals each a year is *tens* of
examples, not thousands. Every guard this project has built assumes otherwise:
`MIN_EXAMPLES`, progressive validation, the kNN prior, the beta-binomial
shrinkage. None of them work on tens.

Three of today's research documents ran into exactly this shape and it is worth
reading them before starting rather than rediscovering it:

- [news-dedup.md](news-dedup.md) — the falsification could not be run because
  the cell was empty, and the honest answer was to say so.
- [magnet.md](magnet.md) — 45 point estimates, and the one positive had an
  interval five times its own width.
- [features.md](../research/features.md) — an effect that looked like +22.9
  points pooled collapsed to +3.1 within cells.

A turn model will produce a confident-looking number from a dozen observations
unless it is built to refuse. **Design the refusal first.**

### What would make it worth building

Write the falsification before the model, as [edge.md](edge.md) §3 did:

> Label the major turns in the stored history — by a rule, not by eye, or the
> labels encode hindsight. Then ask whether any signal available *before* each
> one separates it from the far more numerous moments that looked similar and
> continued. If the separation does not survive a walk-forward split by time
> **and** hold across instruments, there is no model here, only a fitted story.

The rule for labelling is itself the first piece of work and probably the
hardest: "a major turn" has no definition in this codebase, and one chosen
loosely will make everything downstream look excellent.

### What not to do

Do not start from the news. [news-dedup.md](news-dedup.md) established that
the corpus contains no observation of independent outlets converging on a
story, and [news-models.md](news-models.md) §1 was demoted on the strength of
it. Sentiment or crowding as a turn signal is the same claim in a longer coat,
and the data to test it does not exist yet.

Do not start from levels either. [magnet.md](magnet.md) found levels do not
attract price, and a level is a price rather than a regime — the wrong object
at the wrong scale for this question.

## 6c. Cyclical context — where a level sits in the larger move

Every feature the model has is **local to the touch**. `approach_vol`,
`depth_vol`, `run_vol`, `pivot`, `backcheck`, and the six candidates tested in
[features.md](../research/features.md) §4 all describe the last few bars before
price arrived. None of them describes *where that arrival sits in anything
larger* — whether the instrument has been climbing for a month, falling for a
month, or oscillating in a range, and if in a range, whether this level is near
its floor or near its ceiling.

That is a real gap and it is a different gap from the one already recorded.
features.md concluded "the missing information is probably not another function
of price" and named order flow as the absent class. Order flow is absent
*downward* — finer than a bar, and uncollected. This is absent **upward**: the
same stored bars, read at a scale nothing currently reads them at. The two are
not alternatives and the second is far cheaper to test, because the data is
already on disk.

The intuition: a support level in the third month of a downtrend and the same
support in the second week of a recovery are not the same object, and the model
cannot currently tell them apart. Nor can it tell the bottom of a range — where
the next move is up because there is nowhere else — from the top of one.

### Why this is not obviously a good idea

Three findings point the other way and should be read first:

- [magnet.md](magnet.md) found levels **do not attract price**. A cycle claim is
  a bigger version of the same kind of claim, and the smaller one failed.
- [features.md](../research/features.md) §1 found `side` carries essentially all
  of the signal and eight other features carry none. The prior on any tenth
  feature mattering should be low.
- The pooled-to-within-cell collapse: +22.9 points became +3.1. Anything
  measured across instruments and regimes without conditioning will look good.

And a fourth, structural: **regime labels are the easiest thing in this field to
fit backwards.** "We were in an uptrend" is trivially true in hindsight and
nearly useless in advance, which is the same trap §6a names for major turns.
The label must be computable from data strictly before the touch — a rule, not
an eye — or the whole thing is hindsight wearing a feature's clothes.

### The shape it would take

Two values, both point-in-time, both from bars already stored:

1. **Direction at scale** — up, down, or ranging, over a window much longer than
   the touch horizon. `drift.py` already tracks whether what counts as usual has
   moved, but a drift says the regime *changed*, not which way it is pointing;
   this is the missing sign. A slope with a band around it is the crude version
   and is the right first attempt.
2. **Position within the range** — where price sits between the range floor and
   ceiling, as a fraction, when direction is "ranging". Undefined, and correctly
   so, when it is trending: a trend has no ceiling to be near.

Both are one number per instrument per timeframe, recomputed as bars arrive, and
both fit `Features` without touching the touch pipeline.

### The falsification, written first

The interaction is the whole claim, so test the interaction and not the main
effect. Position-in-range on its own will correlate with `side` — near the range
floor most touches are from above — and would score as a discovery while adding
nothing to what `side` already says.

> Split resolved touches by cycle state. Within each state, does the up-rate for
> a given `side` differ from the pooled up-rate by more than the cell interval?
> If a support touch in an uptrend and a support touch in a downtrend resolve at
> the same rate, there is nothing here.

Then the standard gates: walk-forward by time, hold across instruments, AUC
beside accuracy, and scored against "assume the level holds" — which currently
beats the model at 74.8% against 71.1%, and is the baseline any new feature has
to move.

Sample is the binding constraint again. A month-scale cycle gives *tens* of
independent observations per instrument, not thousands, however many touches sit
inside them — the touches within one uptrend are not independent draws on the
question "does an uptrend matter". Count cycles, not touches, when sizing the
claim.

### Where it connects

- **§6a (major turns)** is the same question one scale up and asked as an event
  rather than a state. A cycle label is most of the labelling work that item
  says is its hardest part, so doing this first is the cheaper order.
- **§5b (weak and strong)** would gain the obvious conditioning: a level is
  probably strong or weak *relative to the prevailing direction*, not absolutely.
- **§6 (the score)** is where a cycle state belongs if it survives, as context
  on the number rather than a term in it.
- **`regime`** already exists in `Features` and is a **volatility** percentile,
  not a direction. Not the same thing, and the name collision will mislead
  someone — whatever this ends up called, it should not be called regime.

## 7. BOCPD

Documented in [structures.md](structures.md) as a way to *grade* a regime change
rather than flag it. Deliberately deferred.

## Watch rather than act

> **Migrated on 2026-08-15.** The three notes that follow describe the
> 908MB instance this ran on until then and are kept because the reasoning
> is still how to read a kill — but the numbers are not the current box, and
> several of them were the *reason* a diagnostic was deferred. Those reasons
> are gone.
>
> | | old | new |
> |---|---|---|
> | RAM | 908MB | 3,823MB |
> | swap | none | 2GB |
> | disk | 6.7GB, 79% used | 242GB, 3% used |
> | container cap | 640MB, pinned | 70% of host, derived |
> | architecture | amd64 | **arm64** — the image is now built for both |
>
> **So do the deferred work.** `prices prune` has never actually run, `VACUUM`
> was waiting on room for a second copy of the file, and the outcome-rate
> re-measure and `structures gaps` were both put off because a second process
> was enough to OOM the box. None of that is true now. What has *not* changed
> is that a cold start is still the expensive moment — see item 0c — though it
> costs 36MB rather than 410MB since the warm was streamed.

- **~~Nothing heavier than a read can run on this box.~~** Established the hard
  way on 2026-08-14: `agents ask` and `prices prune` each OOM-killed the
  container, three restarts between them. Kills landed at ~260MB resident
  against 908MB total with ~148MB available, so *any* second process was
  enough. The database survived every one — `pragma quick_check` clean, no rows
  lost, which is SQLite's transactionality doing its job — but the agent window
  timer resets on each restart, so the diagnostics kept destroying the test they
  were run for.
- **Memory bit before disk did**, and the shape of the kill is worth keeping
  even on a bigger box. The container was capped at 640MB but the kill came
  from the *host* running out — `oomkilled=false` on the container with
  `global_oom` in `dmesg`, which is a confusing pair to read and reads as "not
  a memory problem" if taken at face value. Watch resident size against the
  host's total, not against the container's cap.
- **Disk** was next at 79% of 6.7GB, and is now 3% of 242GB. `prices` is 961MB
  and grows continuously; the instrument count went from six to fourteen on
  2026-08-14 and 1m joined the level set, so the growth *rate* is roughly 2.3x
  what the original note was written against. `till-infinity prices prune`
  exists for this and still nothing runs it — see [prices.md](prices.md),
  "Retention". A cron entry with `--yes` is the intended shape, and `--vacuum`
  is now affordable whenever, since a second copy of the file is 0.4% of the
  disk rather than most of it.
- **Agents** wake every 30 minutes, and every deploy restarts that timer. On a
  busy deploy day they may never reach a wake.
- **Confluence text** in a delivered alert should match `structures zones` for
  the same instrument. Both are logged; if they diverge, the per-batch grouping
  in `_level_calls` is where to look.
