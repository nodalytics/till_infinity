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

**Agents have never woken** — *half done: the gate now says why.* It was
declining every window and reporting it at DEBUG, which production does not
print, so a gate that ran every time was indistinguishable from one that never
ran. It now logs the closest approach at INFO: "widest spread 1.9bps at TVC gold
against 8.0bps needed; strongest release importance 1 against 2 needed".

What remains is the config question that was underneath it all along, and it is
now answerable rather than guessable: read a few of those lines and see whether
`AGENTS_SPREAD_BPS` and `AGENTS_IMPORTANCE` are set somewhere a real market
never reaches. Do not change them before reading the near misses — that is how
the thresholds got wherever they are.

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

**`risk_vol` is 0.0 on every recorded call**, which makes `reward_to_risk`
identically zero — "expected push against what being wrong costs" is documented
as the number that decides whether an edge is worth taking, and it is currently
not being computed. Nothing gates on it yet, which is the only reason this has
been invisible.

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

- **Disk** is the constraint that bites first: 69% used, 2.1GB free, prices
  growing continuously. CPU sits at 8.5% and memory at 232MB of 640MB.
- **Agents** wake every 30 minutes, and every deploy restarts that timer. On a
  busy deploy day they may never reach a wake.
- **Confluence text** in a delivered alert should match `structures zones` for
  the same instrument. Both are logged; if they diverge, the per-batch grouping
  in `_level_calls` is where to look.
