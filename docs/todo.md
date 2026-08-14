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

Two things still stand between here and a fit. **Re-measure the rate** over a
few post-fix hours — it should be far lower, and if it is not, the fourth route
was not the last one. And the older examples remain unusable regardless: they
were recorded under the inflated counts, which is not a tidiness problem but a
correctness one — the pre-fix journal calls direction correctly 99.9% of the
time because a level's history and its next outcome were the same move counted
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

**Still open, and cheap:** the better fix is to fold each message into the
running answer as it arrives and never hold the list — `interesting()` already
computes exactly that. And **swap still does not exist**, which is why an
overshoot is a kill rather than a slowdown; that does not improve on a bigger
box, it just gets harder to reach.

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

## 5. Run-formed levels, as an experiment before a feature

Swings are currently bar extremes, which makes every level a property of the
sampling grid. Run boundaries would not be. Run both over the same history and
compare which set price respects more often — the outcome machinery already
answers that. Detail: [levels.md](levels.md), "A level spans periods too".

## 6. Build the score

Designed in [score.md](score.md), not built: one number per instrument in
[-1, +1], three EWMAs, thresholds as rolling quantiles, transitions only.

## 7. BOCPD

Documented in [structures.md](structures.md) as a way to *grade* a regime change
rather than flag it. Deliberately deferred.

## Watch rather than act

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
