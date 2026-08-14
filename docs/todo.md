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

**The outcome rate needs explaining before any fit.** The journal recorded 976
outcomes in one hour and 8,411 in six, against a total of 76 the previous day.
The re-arm fixes should have made resolutions *rarer*. Either the cold start and
warm replay generate them en masse, or there is a fourth route to over-counting
that the three touch fixes did not close. It matters beyond tidiness: at
~1,000/hour, `MIN_EXAMPLES` is reached from a few minutes of one afternoon
rather than from a spread of market conditions, which is not the dataset the
walk-forward validation assumes. Do not run `fit` until this is understood.

**Agents have never woken.** The whole log contains one line — `agents started`
— across roughly seven hours and ~14 thirty-minute windows. It is not the
throttle and not the credentials: a one-off `agents ask` works on both
providers. That leaves the wake gate, `AGENTS_SPREAD_BPS` and
`AGENTS_IMPORTANCE`, whose thresholds are apparently never met. A config
question before it is a code one, and the gate should probably report *why* it
declined to wake rather than staying silent.

## 0b. Three found on 2026-08-14 while tracing the silent channel

Ordered by what is holding back the most. All three are documented with their
measurements in [levels.md](levels.md).

**The spread cost charges zero on every call so far.** `cost_of` reads a window
filled by `observe_quote` only, and the recorded calls come off the bar path
before any quote lands, so the window is empty and the charge is a true zero —
not a rounding artefact. The feature is wired correctly and has never yet
suppressed a signal. Either the window should survive across the replay
boundary, or a call made with no spread evidence should say so rather than
silently costing nothing. The measured charges are worth seeing before choosing:
0.003v on btc against 2.5v on gbpusd 3m, so this gate is nearly free on crypto
and close to absolute on FX intraday.

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

## 1. Split `observe_bar`: form from own bars, touch from the finest

This is now the fix for the silent channel, not only a correctness tidy-up: the
touch counts it inflates are what drag the base rate lopsided and close the
edge gate. See [handoff.md](handoff.md), "Why the channel is silent".

`Engine.seed` replays stored bars through `observe_bar`, which both **forms**
levels for that row's interval and **runs the touch check** at that interval's
resolution. So a daily level warmed from daily bars gets daily-quantised
origins — and a cold start warms from six-figure bar counts, so that is most of
what any level knows. The live path does not have this problem:
`observe_quote` already checks every interval on every quote.

The fix is a **split, not an addition**:

1. **Form** levels for each interval from *its own* bars. Unchanged — PIP needs
   confirmed swings on the timeframe the level belongs to, and a daily swing is
   not visible in 3m data.
2. **Touch** every interval from the *finest* bars available, once, in time
   order — the replay equivalent of what `observe_quote` does live.

**The trap:** the current single pass already records touches at each interval's
own resolution. Adding a fine-bar pass *on top* would count every interaction
twice — the 591-effective-touches bug arriving by a third route, after two
other routes to it were closed on 2026-08-13. Doing it correctly means changing
what `observe_bar` is responsible for, and then proving touch counts stayed
sane: cold start, warm, and check `structures levels` reads in the tens rather
than the hundreds.

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
