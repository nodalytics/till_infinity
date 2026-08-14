# Outstanding

Ordered by what would change the numbers most. Each entry says where the detail
lives, because the reasoning belongs next to the code it explains rather than
duplicated here.

## 1. Split `observe_bar`: form from own bars, touch from the finest

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

## 3. `fit(since=)` once 200 post-fix outcomes exist

No code needed. The counter restarts from the 2026-08-13 fixes, because
examples recorded under inflated touch counts and a pooled base rate describe a
model that no longer exists. Detail: [structures.md](structures.md), "Examples
have an expiry".

## 4. Run-formed levels, as an experiment before a feature

Swings are currently bar extremes, which makes every level a property of the
sampling grid. Run boundaries would not be. Run both over the same history and
compare which set price respects more often — the outcome machinery already
answers that. Detail: [levels.md](levels.md), "A level spans periods too".

## 5. Build the score

Designed in [score.md](score.md), not built: one number per instrument in
[-1, +1], three EWMAs, thresholds as rolling quantiles, transitions only.

## 6. BOCPD

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
