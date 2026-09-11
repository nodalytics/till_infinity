# Features that ship, configure, log correctly, and do nothing

Four in one day on 2026-09-03, and more the day after. Each passed its tests,
each described itself accurately in the logs, and each changed nothing about
the running system. They are collected here because the pattern is now the most
common defect in this repository and the individual write-ups bury it.

## The four

| what | why it did nothing | how long |
| --- | --- | --- |
| `slowing` capped at 10.0 | the standardiser's running mean was 141,380,329 and `Scaler` has no decay, so the cap needed ~1e11 samples to matter | ~1 hour |
| `NOTIFY_MIN_INTERVAL=15m` | the alert carried no `interval`, so the filter's "missing means keep" rule fired every time | ~1 hour |
| `STRUCTURES_FORMATION` | `Watcher.load` replaced the configured engine with the pickled one | its whole life |
| `best_r` / `adverse_r` | `_best`/`_worst` were popped on the line *above* the code that reads them | every close ever made |

Two more from the same week: eleven new synthetic feeds polled by nothing and
then warmed by nothing, and `confluence` absent from every outcome so 12,504
resolutions recorded zero agreeing timeframes.

## The fifth, and the one that reported a result — 2026-09-04

| what | why it did nothing | how long |
| --- | --- | --- |
| `max_spread` / `min_days` on the ccxt board | `fetch_tickers` carries neither field, and `_rejects` skips a zero reading on purpose | since written |
| `drift.py`'s "settled" report | read `models.pkl`, which stopped being the live state when the store moved to msgpack | ~12 hours |

The first is the familiar shape. Measured against the live Binance board, all
762 rows came back `bid=0, ask=0` and `listed_days=0`, so a `max_spread` of
1e-9 rejected nothing and a `min_days` of 10,000 rejected nothing, while a
control `min_volume` of 1e12 correctly rejected all 762. Two of six filters were
decoration, and the fixtures hid it by setting both fields by hand.

**The second is worse than inert and belongs in a category of its own: it
produced a confident, specific, wrong answer, and I relayed it.** `drift.py`
watches the break model's weights and reports whether they are settling. Its
path was hardcoded to `models.pkl`. When the store moved to msgpack that file
stopped being written, and from 07:05 onwards every check compared one frozen
snapshot against itself. Movement came out at exactly 0.000 three times running
and it announced the model **SETTLED**.

It had not settled. Against the live state the weights were

    approach_vol -0.371 · depth_vol -0.285 · slowing -0.153
    prior_slope  +0.121 · interval_log -0.078 · slope  +0.057

against the stale file's `-0.166 / -0.492 / +0.011 / -0.138 / +0.067 / -0.100`:
three signs flipped, the ordering changed, total movement **1.135**.

Everything above this section is about a feature that goes quiet. This one
*spoke*, and what it said was the strongest possible version of the claim it
was built to test. **A monitor reading a stale source does not fall silent - it
reports perfect stability**, because an unchanging file is indistinguishable
from a converged model by every measure the monitor has. That is the most
dangerous form of this defect, since silence invites a check and a clean result
ends one.

The same script also killed the link alert it rode on. It unpickled by hand
rather than through `store.load`, so once `structures/` grew subpackages it
died with `No module named 'till_infinity.structures.anomaly'` - and because it
ran last over ssh, **its exit code became the link's**. The watcher reported the
host unreachable for an hour while the host was answering every request. A
failing component inside a health check is reported as the health of the whole.

### What it added to the list

* **A watcher needs a check that it is watching.** Movement is now only counted
  when the state file's mtime has changed; otherwise it says so. Two checks
  inside one save window read identical bytes and would otherwise score a
  perfect 0.000 - the same trap one level down.
* **Operational scripts rot faster than code and are tested by nobody.** These
  two lived only in `/tmp` on the box. Nothing imported them, no test ran them,
  and the refactor that moved `structures/` could not have known they existed.
  They are in `research/harness/` now.
* **Zero movement is not evidence of convergence.** It is evidence of *nothing
  having been read*, until the source is shown to have changed.

## The sixth: a gate that has never rejected anything — 2026-09-05

`Inference.actionable` is four gates, and the first is

```python
self.own_touches + self.neighbours >= 8
```

Its docstring explains the reasoning well: *"a big edge on four touches is
noise"*. It cannot enforce that. `neighbours` is the kNN's `DEFAULT_K = 12`,
returned in full whenever the model is warm - which it always is, because it
pools across instruments - so the sum clears 8 on borrowed evidence alone
before the level's own record is consulted at all.

Measured over 20,000 level calls:

| | |
| --- | --- |
| `neighbours == 12` | 19,992 of 20,000 |
| passes `own + neighbours >= 8` | **20,000 of 20,000 (100%)** |
| calls with **zero** own touches | 2,559 (13%) |

It has never rejected a call. It surfaced because 250 ccxt feeds were
registered on 2026-09-04 and immediately produced level alerts reading
`0 touches here + 12 similar` - the gate reporting eight touches' worth of
evidence for a level that had never been touched.

### And the obvious fix is not supported by the record

Requiring the touches be the level's own is the reading the docstring invites,
so it was measured before being written. Over 141,857 resolved touches:

```
actionable only    n       median |push|    held
own 0            1,252          2.272      90.2%
own 8+           5,825          2.222      91.7%
```

**1.5 points of held rate across the entire range, and the median push is
flat.** A level's own touch count barely separates how its next touch resolves,
so tightening the gate on it would refuse a seventh of all calls to buy almost
nothing.

That is the same trap `actionable` already documents at the top of its own
docstring - `MIN_REWARD_TO_RISK` was "the most principled of the set" and was
measured to *invert* the expected return. An inert gate is worth recording; it
is not on its own an argument for a stricter one.

**What was fixed instead** is the thing that actually did harm: the alert
budget. `NOTIFY_MAX_PER_HOUR` is 15, and eight of them went to DRAM, FARTCOIN,
MUU and MSTR inside four minutes - instruments with no broker behind them,
because nothing trades ccxt. A message no action can follow is spending
attention that a tradable instrument needed, so `NOTIFY_FEEDS` now allows only
the traded set. The signal keeps being recorded and learned from; it stops
interrupting anybody.

## The seventh, eighth and ninth: state that was never kept — 2026-09-05

Three faults, one cause. **The trading service persisted nothing at all** -
every dict on it was in memory only - and each of these looked like a separate
bug until the third one made the pattern obvious.

| what | why it did nothing | how long |
| --- | --- | --- |
| `break_even_at` on a restarted position | `_best` reset, so a trade at 2R looked like one at its entry | every restart |
| the daily loss limit | a fresh `Guard` cleared `realised` and `halted` and re-based `opening_equity` | every restart |
| the strategy ranking | `policy` and the untaken record started empty | every restart |

The first cost money and can be counted: **nine trades reached 1R or better and
lost anyway, six of them closing at a full stop** - break-even never proposed on
a move already earned. It also hid its own size, because `best_r` on the close
is read from the same dict, so any give-back measured after a restart records
only the peak since the restart.

The second is worse in kind, because it is a **risk control that silently
resets**. `Guard.roll`'s docstring rejects carrying a halt "until someone
restarts the process", and the code had the opposite failure: a deploy cleared
the day's realised loss, lifted the halt, and set `opening_equity` to the
already-reduced equity - a lower base, from which another full daily loss was
allowed. There were ten deploys that day.

### What made it invisible

Everything downstream **kept working on a defensible default**. An empty
`_best` is not an error; it is a position nobody has quoted yet, which is a
real state on the first tick after adoption. A zero `realised` is a day that
has not lost anything, which is true every morning. An empty ranking is a
desk that has not learned yet, which is true on a first run. Each reset
produced a legal value that the code was already written to handle.

> Nothing here failed. Everything here started again, and starting again looks
> exactly like starting.

### And the same shape, one level down

Fixing it introduced a fresh instance of the pattern within the hour. The new
`state_dir` defaulted to `.data/trading`, a real directory in the repository,
so every test that built a `Trader` wrote the day's total there and the next
test read it back. `realised` came out at 103.8 where the test had earned 59.4;
the other 44.4 belonged to a different test. One shared temporary directory
had the same fault - it has to be per call.

A test that reads state it did not write is not testing the thing it names.

## What they have in common

**The output is a legal value.** Zero is a legal `best_r`. Keeping an alert is
a legal filter decision. A standardised feature near zero is a legal input.
Nothing raises, nothing warns, and every downstream consumer keeps working on a
number that means "nothing happened" when the truth is "this was never
measured".

**The tests were right and tested the wrong end.** `best_r` had tests that
called `_reach` directly, where the ticket is still tracked - they passed
throughout. The notification floor had seven tests that drove the filter with a
hand-made payload. The filter was correct; the *alert* was missing the field
the filter reads.

> Assert against the thing that writes the record, not against a method that
> feeds it.

**The safe default is what hides it.** Every one of these had a deliberate,
correct fallback - keep the alert when the interval is unknown, return 0.0 when
a ticket is missing, use the class default when the setting is absent. Each is
the right behaviour for the case it was written for, and each converts "this is
broken" into "this is quiet".

## What actually finds them

Not tests, in every case so far. What found them:

1. **Asking whether the record is being written.** Three of the four were
   caught by querying the journal for the field after deploying, rather than
   trusting the deploy. The question is always the same: *does this reach the
   thing that reads it?*
2. **A watcher on something that should move.** The `slowing` mean was found
   because a weight watcher armed for an unrelated reason reported
   `approach_vol` moving 0.279 in half an hour. It was looking for whether new
   features earned their place and found a feature that had been mute for
   weeks.
3. **A result that makes no sense under your own explanation.** The
   notification floor was caught because a probe said "1h kept: False". Under
   the story I was telling, that was impossible - and it was the *wrong*
   answer, from a probe that was itself wrong, that made me look again.
4. **A false alarm, chased rather than dismissed.** `drift.py` was found only
   because a link-down alert fired while the link was demonstrably up. The
   alert was wrong, the thing it was wrong about was real, and the twelve
   hours of "SETTLED" would still be uncorrected if the noisy alert had been
   silenced instead of explained.

## The verification that is worth doing

Cheap, and it would have caught all four:

* **Build the payload the way production builds it.** The first check of the
  notification floor invented a dict with `shape` at the top level, where the
  filter reads it from `fields`. Everything was rejected on shape, the floor
  was never reached, and `1m rejected: True` was true for the wrong reason. The
  second used the real `Signal` and the real `alert_payload`, and immediately
  showed `fields.interval` was absent.
* **Read the state, not the output.** The break model's weights looked
  plausible for weeks. Its standardiser's running mean was eight orders of
  magnitude out and had never been looked at.
* **Check on the far side.** A reverse SSH tunnel bound to the wrong address is
  indistinguishable from a working one on the side that opened it. The same is
  true of every producer/consumer pair here.

## The one that has no fix yet

`Scaler` silently ignores a vector whose length it does not recognise, and
`apply` then returns raw values. That is how adding two features left the
standardiser stale. `RECIPE` handles an input **changing meaning**, and a
length change is handled by rebuilding - but the silent-return remains, and
some other model will find it.

## Ten: the origin refinement fires on 2.4% of origins

Measured on the live book, 2026-09-08: **33,211 origins kept across 1,751
series, 810 refined.** The refinement is the largest single improvement ever
measured on the swing strategy - +0.349R a trade becoming +0.576R - and it
reaches one origin in forty.

`refine` needs the 1m series to have covered the coarse bar the origin sits in
at the moment that bar closed. `Series` holds 500 bars, so 1m covers about
eight hours, and every origin on a timeframe whose lookback is longer than that
mostly misses.

**And the change-point confirmation inherits the problem.** `origin_confirmed`
is a subset of refined by construction - the change point can only agree with a
relocation that happened - so of 415 published calls carrying the field in six
hours, **414 read zero and one read one**. The field is not broken; it is
measuring a population that barely exists.

Two things follow, and neither is "the feature is wrong":

* The journal cannot score `origin_confirmed` at this rate. It needs either far
  more time or a larger refined population.
* `research/localising.md` already names the fix - the `Series` window is 500
  bars and a 1m series therefore reaches eight hours. Growing it for that one
  series, or keeping the coarse band on coarse origins, is a measurement nobody
  has made.

## Eleven: `articles.symbols` has been empty on every row ever written

24,214 articles in `news.db`, every one carrying a `symbols` column, and the
value is `[]` on all of them. The field is populated - it is not null, it is an
empty list - so nothing reads as missing and every join against it succeeds and
returns nothing.

Found on 2026-09-09 while trying to test whether a catalyst changes how often a
trade expires ([catalysing.md](catalysing.md)). The experiment fell back to the
economic calendar, which can say the dollar had a print and cannot say a
headline was about gold.

An always-empty field that looks like a working join is worse than an absent
one: the absent one asks a question at the point of use.

## Twelve: `run_vol` is exactly zero on every touch

Present on every structures touch outcome, and its maximum over 2,000 sampled
resolutions is **0.000** - not small, exactly zero, every time. Whatever fills
it either never runs or always computes nothing.

Found on 2026-09-09 while reaching for a way to measure how far price travelled
against a call ([overhead.md](overhead.md)) - which is the same way
`articles.symbols` turned up: a field looks available, is used, and returns
nothing without ever raising.

## Thirteen: the service was restarting every 2.5 hours and every surface said healthy

Not an inert reading - an inert *observer*. The container was OOM-killed
nineteen times between 1 and 10 September, roughly every two and a half hours,
and nothing in the ordinary places said so: `docker ps` showed `Up`, the health
check passed between kills, and the restart was clean enough that `docker
inspect` reported `exit=0`. Only `dmesg` had it.

It belongs in this catalogue because the cost is the same shape as the others -
a thing that appears to be running and is not doing its job - and because of how
it presented. Six separate puzzles in one session were all this single event:
`restarts=3` on a container nobody deployed, trading silent for two hours, a
save cycle that never completed, three harnesses dying with empty output, CPU
reading 7.6% then 153%, and a replay window that looked like a regime change and
was actually the feed count growing from 42 to 364.

Every one was diagnosed as something else first, and two of them were written up
as findings before being retracted.

Cause and fix in [starving.md](starving.md): the price collector was discovering
up to 1,250 crypto swaps against a 53-symbol book. The lesson for this page is
narrower - **when several unrelated things are behaving oddly at once, the
common cause is usually the platform rather than any of them.**


## Fourteen: the changepoint detector fires and lands on origins at below chance

`_note_change` runs two `Focus` detectors per (feed, timeframe) and stamps every
firing, and `changing()` publishes the count on every call. At the shipped
threshold of 12 nats it matches **1.9%** of the origins the engine records at
1h - which reads as "the threshold is too high" and was believed to be that for
some time.

It is not. Measured against what a detector firing at the same rate but knowing
nothing would score, the **lift is 0.85 to 0.94 at every threshold from 1 to 20**
- consistently *below* one. Lowering it to 1 nat raises the hit rate to 68.6%
by firing on 37% of all bars, 25.84 times per origin, where blind firing at that
rate gives 75%.

So this is not an inert *reading* - the numbers move, and they move a lot when
the threshold moves. It is an inert *relationship*: the count is a function of
the firing rate and carries nothing about where origins are. A reading that
responds to its own parameter and to nothing else is the hardest kind to notice,
because every experiment on it appears to work.

Recorded on 2026-09-10 in [generated.md](generated.md), on generated series at
1h only - 2h and 4h had no bars to test.

## Fifteen to eighteen: the audit that went looking — 2026-09-11

`run_vol`, `pivot` and `round` were all found by hand, in one day, by somebody
cutting a table. So every number this package publishes was enumerated and
asked the same question mechanically: **does it vary, and over what window?**

`research/harness/varying.py` is the harness and `tests/test_published.py` is
the half that outlasts it - a gate that fails when a published feature is
constant under a fixture rich enough to reach every producer.

**Where the numbers come from.** Every production figure below was read from
the instance's journal - 804,539 entries over 28.9 days - with the harness'
`journal` route, streaming off the `(kind, time)` index at `nice -n 19`. Two
things to know before re-running it. A distinct count of "4,000+" is the
harness' own `CAP`, not the true count: it stops tracking distinct values at
4,000 so a survey of a million rows cannot grow without bound on a field that
is a price. And the local `.data/journal/journal.db` holds 465 rows, so nothing
here can be reproduced from it - the local `fresh.db` (203,503 entries, 13 to
27 August) is the nearest offline substitute and predates about half the
fields. The fixture route needs neither.

### The surface

**123 numeric fields** reach the journal or a model from the structures side:

| producer | fields |
| --- | --- |
| `Call.to_signal` literals | 37 |
| `Engine._origin_at` | 20 |
| `changing` + `_learned_at` | 5 |
| the `service` publish site - `drawn_by_n`, `Breaks`, the calibrator, `Races`, both `LevelRange` boxes | 20 |
| `emit` - `score` | 1 |
| `Macro.features` | 16 |
| **on a published level call** | **99** |
| `reactions.Features`, less `strength` which is also on the call | 12 |
| the inference dict on a non-actionable observation | 7 |
| stamped on the resolution - `push_vol`, `excursion_vol`, `adverse_vol`, `seconds`, `confluence_n` | 5 |

The production journal shows 95 of the 99 on a recent level call, and the four
missing ones are finding seventeen below.

### The most useful result is a retraction

A first pass at this ran three **engine-only** fixtures over 970 calls and
reported ten fields with one distinct value. Against the production journal -
22,770 level decisions over 3.61 days - **all ten are alive**:

| field | in the journal | why the fixture said otherwise |
| --- | --- | --- |
| `activity` | 4,000+ values, 3.6e-9 .. 20 | folded on in `service`; an engine-only fixture never runs it, and the bars carried no `volume` |
| `hour_hold` | 4,000+ values, 0.39 .. 0.95 | `to_signal` got `clock=None` |
| `hour_vol_share` | 4,000+ values, 0.078 .. 2.01 | as above |
| `hour_n` | 210 values, 0 .. 588 | as above |
| `liquidity_beyond_vol` | 4,000+ values, 66.0% zero | `peers` was empty |
| `liquidity_beyond_n` | 6 values, 0 .. 5 | as above |
| `change_up_tf` | 5 values, 92.5% zero | the drift detector watches 5m/15m/30m/1h; the fixture fed 5m alone |
| `change_down_tf` | 5 values, 92.6% zero | as above |
| `change_watched_tf` | 4 values, **98.2% on one** | as above |
| `origin_confirmed` | 2 values, 85.1% zero | genuinely rare - already the tenth entry on this page |

**Eight of the ten were the fixture and two were rarity. None was a bug.** A
fixture that cannot reach a producer reports its own shape and calls it a
finding, which is worse than not looking - and it is the same error this page
records against the macro features, one layer down.

`change_watched_tf` is the one to watch: 98.2% on a single value is a point and
a half from `liveness.NEAR`, which is the shape a field takes while it is
dying rather than after.

### And the same caution, stated with a window

`macro_us_core_inflation` is **two values across 11.8 days**, 99.8% on one.
Core inflation is published **monthly**, so an 11.8-day window can contain at
most one print, and it contains exactly one. The field moved the maximum number
of times it was able to. Nothing on this page is called dead for being flat in
a window shorter than its own release schedule.

For the record, over the same 11.8-day sample: `macro_dollar` 3 values,
`macro_us_breakeven` 5, `macro_us_curve` 5, `macro_us_real_yield` 6,
`macro_carry_gap` 27. Slow, all of them, and all alive.

### Fifteen: `break_probability` has never seen a touch

`service._level_calls` scores the break model like this:

```python
extra.update(self.breaks.reading(getattr(call, "features", None) or {}))
```

`Call` is a `@dataclass(slots=True)` whose slots are `feed`, `interval`,
`level`, `inference`, `price`, `time`, `origin`, `context`. There is no
`features` slot, so the attribute **could never be set** - assigning one raises
`AttributeError`. The `or {}` therefore fired on every call ever made, and
`Breaks.inputs` reads six missing keys as zeros.

Measured under the rich fixture: `Breaks.reading` was called **426 times, with
an empty dict 426 times, producing exactly one distinct input vector** -
`[0, 0, 0, 0, 0, 0]`. Every level on every instrument at every timeframe was
scored on the same six numbers.

**It does not read as a dead field, and that is the whole point.** In the
production journal `break_probability` has 4,000+ distinct values across 6,086
rows spanning 0.00011 to 0.99686. A fixed input through a continuously-learning
logistic tracks its own standardiser's running mean, so the output wanders
convincingly while carrying nothing about the call. That is the `drift.py`
shape from earlier on this page, arrived at from the other direction: **a
monitor reading a stale source reports perfect stability; a model reading a
constant input reports plausible variety.** Neither falls silent.

Fixed by giving `Call` the `features` field the publish site was already
reaching for, populated in `Engine.check` where the object is already in hand.
Same fixture afterwards: **426 calls, 426 distinct input vectors.**

`trading/strategies/scalper.py` reads `break_probability` for risk, so this was
not only a journalled number.

### Sixteen: `break_seen` is exactly 2000 and always will be

Constant `2000` across **22,770 production level decisions over 3.61 days**.
Across a one-in-twenty sample of the whole 28.8-day record it runs 447.9 to
2000 with **88.5% at 2000** - it climbed once, arrived, and stopped.

Constant by construction, and provable rather than sampled. `Logistic.seen` is
a decayed count:

```python
keep = max(0.0, 1.0 - 1.0 / SCORE_MEMORY)  # SCORE_MEMORY = 2_000
self.seen = self.seen * keep + 1.0
```

whose fixed point is exactly `SCORE_MEMORY`. It is a **window length wearing a
sample size's name**, and it is published beside `break_probability` as the
evidence a consumer would weight the probability by - `Breaks.warm` is
`seen >= 200`, so after roughly ten thousand resolutions the field says 2000
for the rest of the deployment's life.

**Not fixed**, because the fix is a decision rather than a repair. The change
would be to keep an undecayed `resolutions` counter on `Logistic` beside the
decayed `seen`, publish that as `break_seen`, and either drop the decayed one
or publish it as `break_window`. `up_first_seen` on `Races` is the same
construction and has not saturated yet - 60.1 to 1118.9 over 6.82 days - so it
will arrive at the same place without anything changing.

### Seventeen: four fields lost their producer and two consumers did not notice

`origin_above_high`, `origin_above_revisits`, `origin_below_low` and
`origin_below_revisits` were published until **2026-09-07**, when `c2e15f7`
corrected the bracket to handle an origin price is standing *inside*. The
corrected version chose its bound from a list of bare floats, which threw away
which origin the bound came from - and with it those four fields.

In the journal they are present on 1,769 to 1,870 rows across the 9.24 days
ending four days ago, and absent from every row since. **Absent, not constant**,
which is `liveness`' third state and the one no survey of the published rows
can see: a field that is not there cannot be counted.

`trading/strategies/swing.py` reads all four:

* `OriginSwing._anchored_stop` asks for the far edge of the zone being traded
  and falls back to the level-anchored stop without it - which is the exact
  placement its own docstring says put "a stop *above* its own entry" and was
  written to correct.
* the `max_revisits` staleness gate reads a count that is never there, so it
  **can never refuse anything**. Its comment is the giveaway: *"A missing count
  is not a stale origin - it is an unknown one, and refusing on it would stand
  this strategy down on every feed whose origins have not been published yet."*
  Correct reasoning, and it converts a broken gate into silence - the same
  safe-default trap this page opens with.

Costing nothing today: `origin-swing` is not in the deployed
`TRADING_STRATEGIES`. It would have cost from the first day it was.

Fixed: the bracket now carries the zone alongside its edge, so the winning
origin's far edge and revisit count are published again. Under the fixture the
four are present on 262 to 346 of 360 calls with 17 to 64 distinct values each.

### Eighteen: `net_edge_vol` is read by the position sizer and written by nothing

```python
scaling.by_edge(features.get("net_edge_vol"), settings.edge_full_at)
```

`net_edge_vol` has no producer anywhere in the package and appears on none of
the 99 fields of a level call. `by_edge` returns 1.0 for a `None` edge, so the
edge scaler is a no-op.

**Doubly inert, and the second switch hides the first.** `edge_full_at`
defaults to 0.0 and is unset in the deployment, and `by_edge` returns 1.0 on
that before it ever looks at the edge. So the feature being absent is currently
invisible, and turning `TRADING_EDGE_FULL_AT` on would change nothing at all -
which reads as "sizing by edge does not help" rather than as "sizing by edge
was never wired up". That is a landmine under a future experiment, not a
present loss.

**Not fixed.** Publishing it means deciding what "net edge per touch" is
measured over and on what sample, which is `research/paying.md`'s open
question and not a rename.

### What the gate now guards

`tests/test_published.py` drives the **service** - not the engine - over three
feeds at three price scales, three venues, nine intervals covering
`config.INTERVALS` and `config.DRIFT_INTERVALS`, real `open` and `volume`,
quotes as well as bars, a real journal so `emit` remembers and the session
clock can learn, and two and a half days of wall clock so the 4h swing anchor
has twelve bars to find an origin in. It asserts:

* no published numeric field is constant, and none is near-constant;
* no kNN feature is constant;
* **every level bucket has a volatility that warms**, which is the pivot fault
  stated as a property instead of a symptom - `Engine.check` opens with
  `if not vol.warm: return []`, and a bucket keyed by a session period had no
  daily bar stream to warm one. Deterministic, where the `pivot` feature's
  variation needs price to return to one of ten prices;
* every configured formation pass drew at least one level, which is `round`;
* the break model sees more than one input vector, which is fifteen;
* the four origin bracket fields are present and vary, which is seventeen;
* and a richness floor under all of it, because **a gate that can pass by
  producing nothing is not a gate** - the count of published calls, of resolved
  touches, of fields with enough rows to judge, and the three inputs an
  engine-only fixture cannot supply, asserted directly rather than inferred
  from the fields they feed.

Falsified before being trusted, which is the part a gate is usually missing:

* re-breaking `Engine._run` the way it was actually broken - returning 0.0 -
  makes the kNN check fail with `run_vol: constant 0 across 686`;
* reverting `Engine.vol_for` to `self.vol.of`, which is the code as it stood
  before `869031d`, makes the bucket check fail with
  `['btcusd/daily', 'eurusd/daily', 'gold/daily']`. With the fix in place the
  list is empty.

And it is not a one-seed result: seeds 23, 77 and 101 each judge 76 fields at
2.5 days and each report nothing constant and nothing near-constant on either
population.

One deliberate softening. A field needs `MIN_ROWS = 25` rows before this has an
opinion about it, because **one observation is not a distribution**.
`swing_range_width_vol` needs origins on both sides of price and a trending
stretch legitimately has open air on one, so on some seeds it is published
three times - and a survey of three rows calls a field constant when it is
merely unmeasured. Whatever falls under the floor is printed by the richness
test rather than quietly dropped.

Two entries on the allow-list, each with its reason in the file: `neighbours`,
which is the sixth entry on this page and is near-constant in production too;
and `pivot`, which is a rare-event flag on a formation that arrives at most once
per instrument per day.

### Filed so the next survey does not re-find them

`channel_lower`, `channel_upper`, `channel_position` and `channel_width_vol`
appear once each in a 28.8-day sample and look constant. They are **retired
names** - `racing.py` records that `channel_position` became `range_position` -
and a single surviving row is not a reading.
