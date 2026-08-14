# Outstanding

Ordered by what would change the numbers most. Each entry says where the detail
lives, because the reasoning belongs next to the code it explains rather than
duplicated here.

## 0. Two things found on 2026-08-14, both ahead of everything below

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

## 4. `fit(since=)` once 200 post-fix outcomes exist

No code needed. The counter restarts from the 2026-08-13 fixes, because
examples recorded under inflated touch counts and a pooled base rate describe a
model that no longer exists. Detail: [structures.md](structures.md), "Examples
have an expiry".

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

Three sources of evidence for that judgement now exist or are close to:

- **How it was found.** One formation or both, per 5a. Two methods that fail
  differently agreeing is the cheapest strength signal available.
- **How many timeframes see it.** [Confluence](levels.md) already computes
  this and reports it in the alert text, but it does not weight anything.
- **What it has done.** Touch count, hold rate and `strength` — measured, and
  currently only reported.

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

## 7. BOCPD

Documented in [structures.md](structures.md) as a way to *grade* a regime change
rather than flag it. Deliberately deferred.

## Watch rather than act

- **Nothing heavier than a read can run on this box.** Established the hard way
  on 2026-08-14: `agents ask` and `prices prune` each OOM-killed the container,
  three restarts between them. Kills land at ~260MB resident against 908MB
  total with ~148MB available, so *any* second process is enough. The database
  survived every one — `pragma quick_check` clean, no rows lost, which is
  SQLite's transactionality doing its job — but the agent window timer resets
  on each restart, so the diagnostics kept destroying the test they were run
  for. **Retention has therefore never actually run.** Do it on the new box.
- **Memory bit before disk did.** The note below was written when this said
  disk was the constraint that bites first; on 2026-08-14 it was memory, five
  times. The box is **908MB total with no swap**, the container is capped at
  640MB but the kill came from the *host* running out — `oomkilled=false` on
  the container with `global_oom` in `dmesg`, which is a confusing pair to read
  and worth recognising. Watch the resident size against 908MB, not against the
  container's cap. See item 0a.
- **Disk** is next: 70% used, 2.1GB free, prices at 394MB and growing
  continuously. CPU sits at 13%.
  The instrument count went from six to fourteen on 2026-08-14 and 1m joined
  the level set, so the *growth rate* is now roughly 2.3x what this note was
  first written against, even though the free space has barely moved yet.
  `till-infinity prices prune` exists for this and nothing runs it — see
  [prices.md](prices.md), "Retention". A cron entry with `--yes` is the
  intended shape; `--vacuum` occasionally, when there is room for a second
  copy of the file.
- **Agents** wake every 30 minutes, and every deploy restarts that timer. On a
  busy deploy day they may never reach a wake.
- **Confluence text** in a delivered alert should match `structures zones` for
  the same instrument. Both are logged; if they diverge, the per-batch grouping
  in `_level_calls` is where to look.
