# Handoff

What is true, what is broken, and what to do first. Started 2026-08-14, current
to **2026-08-31**.

Read the next section before anything else. It is not a bug; it is the reason
most of the numbers in this repository were measuring something other than what
they appeared to.

## The finding that reframes everything, 2026-08-31

**At the horizons that dominate the record, the label is a tautology.** Split
resolved touches by how long they took and by which side price approached from:

| held for | side above → up | side below → down |
| --- | --- | --- |
| 0-60s | **100.0%** (n=7,649) | **100.0%** (n=22,473) |
| 60-300s | 99.7% (n=12,157) | 99.8% (n=11,344) |
| 300-1,800s | 68.9% (n=5,086) | 66.4% (n=5,627) |
| beyond 1,800s | 52.8% (n=830) | 50.1% (n=932) |

A touch approached from above that resolves inside a minute resolves *upward*.
That is not a prediction, it is what "rejection" means - and 46% of resolutions
are that fast. So a model scoring 97% on the pooled population is reproducing a
definition.

By thirty minutes it is a coin, and `max_hold` is 1,800 seconds. **The horizon
at which the model knows nothing is the horizon the desk trades.**

What this invalidates, and it is a lot:

* every pooled model score here, which is what all of them were;
* [features.md](../research/features.md)'s "`side` alone matches all nine
  features" - true, and now explained;
* the kNN's apparent 3.1-point edge over a one-feature floor
  ([learning.md](../research/learning.md));
* any reading of the account that assumed good signals were being traded badly.

See [horizon.md](../research/horizon.md) and
[similarity.md](../research/similarity.md). Scores are now cut by realised
duration; training is banded by interval, because how long a touch turned out
to take is not knowable when it opens and selecting on it would be selecting
the training set with the answer.

## Both fixed on 2026-08-14. What they actually were

Neither was what I predicted, and the third guess was wrong too. Reading the
data settled the first inside one query; the second needed the magnitudes.

### 1. ~98% of outcomes unusable - it was the read window, not the data

Not missing features. `journal.read` silently clamped **every** caller's limit
to `MAX_ROWS = 500`:

```python
params.append(max(1, min(int(limit), MAX_ROWS)))
```

`facto.dataset` asked for its 200,000 rows and got the most recent 500, which
held ~167 outcomes. Every symptom follows from that one line: raising
`JOURNAL_ROWS` did nothing because the clamp ate it, and 170 → 167 was the
500-row window sliding forward, not examples ageing out of qualification.

The premise was checkable and false. Every outcome context carries `push_vol`
and the full feature set - `record_outcomes` is the only place outcomes are
written and it always spreads `touch.features.to_dict()` in. Reproduced by
inflating a journal copy to 9,408 rows: 3,264 outcomes → 185 examples, and
identical at limits of 500, 5,000 and 200,000. That last equality is the tell,
and it costs one command to look for.

`read` now honours the limit it is given. `MAX_ROWS` stays as what it always
was in practice - the ceiling the CLI puts on a listing.

The old test could not have caught this: it wrote ten entries and asserted the
result was under five hundred. True whatever the clamp did. Replaced with one
that writes past `MAX_ROWS`.

### 2. The factorisation machine overflowed - unscaled features, confirmed

The guess was right and the magnitudes prove it. `strength`, `regime`, `pivot`
and `backcheck` are already in [0, 1] and `experience` is log-compressed, but
`approach_vol`, `depth_vol` and `run_vol` are ratios with a volatility estimate
underneath - a touch arriving in a dead pocket divides by a small number and
comes back arbitrarily large.

An FM multiplies its features together, so its gradients are *quadratic* in
magnitude and an unbounded input does not skew the fit, it diverges it. Scaling
one touch in 37 by 5x diverged the model within 55 examples; by 20x, within 18.
So on production it was diverged almost from the start, and `Model.predict`'s
NaN guard had been returning "no opinion" ever since - up, honest, and learning
nothing.

`encode` now saturates the three through `x/(1+x)` about a typical value of 2,
which bounds them into [0, 1) while keeping the ordering - a clip would need a
maximum, and any maximum here would call a 4v approach and a 40v one the same
event. Survives 10,000x spikes now, and predicts real numbers instead of zero.

The NaN guard stays. It was never the bug, and it is the reason a diverged
model cost accuracy rather than uptime.

## The channel speaks again, 2026-08-14

Three alerts delivered within minutes of the fixes below landing - SPX500, ETH
and SOL, all `1/1 channels`:

```
alert 'SPX500 3m - up' [level 7801.5 · this timeframe only]
alert 'ETH 3m - up'    [level 1875.1 · this timeframe only]
alert 'SOL 3m - up'    [level 75.413 · this timeframe only]
```

The journalled decision behind the last one, which is the whole chain working:

```
sol: up from above at 75.413 - p=51% vs 24% base, push +1.43
    edge 0.265   expected_push +1.428   risk_vol 0.641   → r:r 2.23
```

`own_touches` on production fell from 171 to single figures once `observe_bar`
was split, which is what unlocked it: the base rate stopped being dragged
lopsided by one grind counted a hundred and seventy times, so an ordinary call
could clear `|edge| >= 0.08` again. `risk_vol` is populated, and that call
passed the new reward-to-risk gate on its merits rather than by default.

The account below is kept because the reasoning is what matters, not the
symptom.

## Why the channel was silent, traced 2026-08-14

Worth reading because it is one chain and the obvious suspect was innocent -
the same shape of mistake will be made again, on something else.

**It was not the spread cost.** That gate charged `cost_vol` of exactly 0.0 on
every call recorded up to then, so it had never suppressed a signal at all.
The window it charges from is filled by `observe_quote` alone, and the recorded
calls all come off the **bar** path in a burst after start-up, before a quote
has landed. Not a rounding artefact: the smallest real charge on any instrument
is btc at 0.0031 against a journal that rounds to four decimals.

**It was the edge gate, and underneath it the touch counts.** Every recorded
call but one failed `|edge| >= 0.08`, median `0.0748`. The edges were small
because a single 3m level took a touch every two seconds until it held 171 of
them, dragging the base rate to 92.6% down - against which even a 99.7% call
earns only seven points. Inflated touches, lopsided base rate, eaten edge,
closed gate, silent channel. Four steps, each reasonable alone.

Splitting `observe_bar` fixed it, and the channel spoke within minutes. Detail
and the measured numbers are in [levels.md](../docs/levels.md), "The base rate is what
actually closed the gate" and "It charges zero on the replay path".

Two smaller things found alongside, both now fixed: `risk_vol` was 0.0 on every
recorded call, so `reward_to_risk` was meaningless - `vol` was optional on
`infer` and every caller forgot it. And `0.08` itself was never derived from
anything, which is still true and still open: see "0.08 is not derived from
anything" for the attempt to derive it and why the pre-fix journal cannot.

## Then, in order

See [todo.md](../docs/todo.md) for the full list. What the 2026-08-31 findings make
first:

1. **Wait for the duration-banded scores.** Nothing about model quality should
   be acted on until `beyond 1800s` has a readable sample. Everything before it
   was measured on the tautology. The prediction to hold this to: that bucket
   should come back near zero edge for every model.
2. **`Memory` still pools training across intervals**, banded now but by
   interval rather than by anything that separates a fast resolution from a
   slow one - which is the best that can be done without leaking, and is a
   proxy rather than a fix.
3. **Stops are the account.** -897.84 over 38 trades, none up, against +920.20
   from 20 targets. Twenty of the 27 judgeable never reached target, so the
   answer is a better entry rather than a wider stop
   ([stops.md](../research/stops.md)). `adverse_r` now records how much of the
   stop a winner actually uses, which is what would size a change.
4. **Macro needs weeks, not hours.** The features land on 1,197 level calls and
   the conditional test exists; the band where a daily signal could matter has
   fourteen calls in it ([macro.md](../research/macro.md)).
5. **Score the trading.** 120 closed trades, net -688 excluding one
   sizing-bug outlier. Not enough to say anything about any strategy.

## What is deployed and working, 2026-08-31

**53 instruments** - 33 conventional plus 20 Deriv synthetics - on
1m/3m/5m/15m/30m/1h/2h/4h/1d/1w. 2,956 levels held, 55.6% of them on 15m or
slower. Seven formations run merged: `pip,run,origin,profile,equal,gap,round`,
and 57% of levels now carry more than one, where every level used to be `pip`
alone. Trading is live on a Deriv demo account. 1,589 tests.

The synthetics are worth their place for a measured reason: in volatility units
- what `charge_spread` actually deducts - they cost 0.170v to cross against
FX's 2.267v ([catalogue.md](../research/catalogue.md)). In raw points they look
ten times dearer, which is why the screen has to be in the right currency.

Production: one container on `tis`, data under `/home/ubuntu/till-data`, config
at `/home/ubuntu/till.env`, backed up to `strut/.secrets/env-backups/`. CI
deploys on push to `main`. **A `docker restart` does not re-read `till.env`** -
only a redeploy recreates the container.

```bash
sudo docker exec till-infinity till-infinity structures levels
sudo docker exec till-infinity till-infinity journal levels    # PnL per level
sudo docker logs till-infinity | grep -A 20 "model bench"      # the comparison
```

## Trading, added 2026-08-26

> **First live trades, 2026-08-26.** Two on gold, both sells, from real
> `structures` calls on a Deriv demo. One took its target for +59.40; the other
> was stopped for -31.20 and price then went 9.79 points the right way. The
> chain works unattended - signal, strategy, gates, sizing, order, broker fill,
> reconciliation, journal - and n=2 says nothing at all about whether it should
> keep doing it. `trading report` prints dashes rather than rates under thirty
> closed trades, which is the correct answer and the reason it does that.
>
> The loss produced the `min_stop_vol` floor below. The refusal tally from the
> same session is the more useful artefact: 9 on `reward_to_risk`, 5 on
> `dislocated`, 1 each on `news` and `spread`, against 1 taken.

The level calls now reach an account. `trading` consumes `structures.signals`,
sizes against the terminal's own symbol rules, and places the order - on paper
unless `TRADING_LIVE=1`, and off entirely unless `TRADING_ENABLED=1`. Neither
switch implies the other. Full guide: [trading.md](../docs/trading.md).

**Where the terminal runs, and why not here.** MetaTrader 5 is an x86-64
Windows binary and WineHQ publishes no arm64 packages, so it cannot run on the
aarch64 deployment box at all. It runs on a separate x86-64 host behind the
FastAPI bridge ([`metatrader-terminal`](https://github.com/nodalytics/metatrader-terminal))
and is reached over an SSH tunnel in `mt5-bridge-tunnel.service`. The tunnel
binds to the **docker bridge gateway**, not loopback: the consumer is the
container, and bound to 127.0.0.1 it works perfectly from a shell here and is
invisible to the only thing that needs it. `--add-host` in `deploy.sh` is the
other half.

There are two other routes to a terminal - the native package on Windows, and
the module proxied over RPyC out of a Wine prefix - and `trading doctor` says
which this host can use and why the others are out.

```bash
docker exec till-infinity till-infinity trading doctor    # what this host can reach
docker exec till-infinity till-infinity trading symbols   # what the broker offers
docker exec till-infinity till-infinity trading report    # what it has actually done
```

**Verified against a live Deriv demo on 2026-08-26**: reads, an order, a stop
moved by ticket and confirmed on the terminal, and the close. All fourteen
instruments resolve. Six defects were found doing it that no unit test could
have caught, listed under the next heading.

**What it does not claim.** No strategy here has been evaluated against its own
outcomes. `structures.resolutions` now carries ground truth on the bus and
`trading report` will score it, but there are no closed trades to score yet.

## Silent faults found on 2026-08-26, and what they have in common

Five, all live, none of which produced an error or a failing test. Every one
was a component quietly doing less than it appeared to, which is the shape
worth learning rather than the individual bugs.

**Losses were being hidden from the channel.** The notification cooldown keyed
on `(shape, instrument, venue)`, and a fill and its own close share all three -
so a position opened and closed inside fifteen minutes had its close dropped as
a repeat of its fill. A trade that closes that fast is usually one that was
stopped out, so what disappeared was disproportionately the losses and the
channel read as a record of wins. A filter that silently changes what a feed
appears to *say* is worse than one that is merely too quiet.

**The hold was cutting winners.** `_expire` closed on age alone without asking
what the trade was doing, so a position a point in front at the thirty-minute
mark went out at market and the rest of the move happened without us. Out at
4623 on a gold fall that carried to 4592.

**Stops cleared the level but not the fill.** `min_stop_vol` floored the stop's
distance from the *level*; sizing measured from the *fill*. A market entry can
land most of the way to a level-anchored stop, and the position is then sized
as a short-distance trade - a large one - and taken out by ordinary movement. A
gold buy filled 1.0v above a stop sitting 5.9v below the level, sized 0.18
lots, stopped in minutes for -26.64.

**The live path saw less than the store.** `announce_bars` published one notice
per sweep carrying only the newest bar. After a gap, a restart, or on any
interval slower than the sweep cadence, the rest went to the store and never
reached the bus - so levels formed from a subset of the series and touches were
counted on a subset of the interactions, differently from a replay of the same
data.

**A log announced a decision nobody made.** The wide-market gate's
"standing aside" line sat outside the check that decides whether to stand
aside, so it fired once per venue report across a dozen instruments while no
trade was ever refused. This one is the most dangerous of the five, because it
is what gets believed later when somebody reads the logs to work out what
happened.

The pattern: **each looked like it was working from every angle except its own
output.** The tests passed, the container was healthy, the logs were busy. What
found them was asking what a specific number should have been and checking, or
in one case a user asking why a particular signal did not trade.

### Five more of the same, 2026-08-30/31

The pattern recurred often enough in two days to be worth treating as the
default suspicion rather than a surprise. Every one was **configured, deployed
and inert**, and in each case the setting was never the problem - the
*handover* was.

**The formation setting had never worked.** `Watcher.load` replaced the
configured engine with the pickled one, and a pickle carries the settings it
was *first* built with. Production drew levels with `pip` alone for the entire
life of a `STRUCTURES_FORMATION` that said `pip,run,origin`. The symptom was
that `run` and `origin` never drew anything, which reads exactly like two
formations that do not work - the worst kind of silent failure, because it
produces evidence and the evidence is wrong.

**FRED collected 2,174 rows and nothing read them.** Collection without
consumption looks like progress from outside.

**The macro model's signals were discarded.** `run` called `_read_macro` and
threw the return away, which is worse than not calling it: `calls` records the
stance it announces, so seven stance changes were computed, marked as already
published, and dropped - and those feeds then stayed silent until they flipped.

**Eleven new instruments were polled by nothing.** Three lists have to agree -
what is tradable, what the broker source knows the name of, and what is
*collected* - and naming an instrument in the first two left it registered,
tradable, given an exposure leg, and quoted by no one. Zero quotes and zero
bars, which is the same silence as a feed that does not exist.

**And then warmed by nothing.** The fix for that shipped clean and did nothing,
because `cold` asks whether the engine holds *any* levels and with 2,018
restored it does. A second attempt asked whether the engine had ever *seen* the
feed - by then it had, about twenty live bars each - so it reported nothing to
warm while they sat on 2,700 stored bars apiece. A feed is warm when its window
holds enough, not when a series exists for it.

**A document that did not exist was cited as evidence.** `similarity.md` was
referenced three times, including from `prior.md`, as the case for deleting
`Memory`, `Features.distance` and the kNN - "no better than random across 13.5M
pairs". No such file, in the tree or in git history. It has since been written
and measured; the claim holds at tradable horizons and the deletion still does
not follow. **Check that a cited document exists before believing a number in
it.**

## Things that cost time, so they do not cost it twice

**Verify by running, not by reading.** Every bug that mattered was found by
running the thing. Unit tests passed throughout the outcome-pairing bug that
produced exactly zero outcomes.

**Sabotage every test that guards an invariant.** Break the mechanism
deliberately and confirm the test fails. One look-ahead test and one re-arm test
had no teeth until this was done, and the cost-netting sign-flip bug was caught
this way before it shipped.

**`cmd | tail` returns tail's exit code.** A red `pytest` and a failing `ruff`
were both pushed because of this, on separate days. Run gates unpiped.

It happened a third time on 2026-08-26, in a new disguise: the gates were
chained into a *backgrounded* command whose tail printed the pytest summary, so
a failing `ruff format` scrolled past inside output that ended in "962 passed".
Every gate had run and one of them was red. Backgrounding and piping are the
same mistake wearing different clothes - if the thing you read is not the exit
code, you have not checked.

**Measure the window you think you are measuring.** A fix for negative touch
durations was checked against "the last hour" and came back at 26% - unchanged
- because the deploy was seven minutes old and the hour was mostly the old
code. Filtered to rows written since the container started: zero. The fix was
correct and the check was not.

**A cut is a claim.** Banding the model bench by the *interval's* horizon
looked like it separated fast touches from slow ones and did not: a weekly
level can be touched and resolve in thirty seconds. Scoring must be cut by the
realised duration, which is knowable afterwards; training can only be banded by
what is knowable when the touch opens. Getting those the same way round is the
difference between a measurement and a leak.

**Ask whether a strong number is possible.** 100.0% agreement between
same-side touch pairs was not a strong result, it was an impossible one, and
chasing why produced the tautology at the top of this document. 95% accuracy on
FX direction should have prompted the same question weeks earlier.

**Assert properties, not tolerances.** "Less than 3x" is a number someone made
up. "One print in sixty-one cannot move a median" is the property. The first
kind passes for the wrong reason.

**A field left off a message is a silent, partial version of the system.** For
months `prices.announce_bars` carried the close and not the extremes, and
`Engine.observe_bar` reads them as `float(payload.get("high") or close)`. Every
bar arriving on the bus was therefore a doji, and three things followed
quietly:

- levels formed on the live path sat at **closing prices**, when the origin is
  supposed to be an extreme - the leg in meeting the leg out;
- session pivots were the highest and lowest **close** rather than the session
  high and low;
- a bar that pierced a level intrabar and closed away from it recorded **no
  touch** on the bar path.

Nothing failed. The stored history has always held true OHLC, so every warm
start rebuilt a correct model and the defect only reappeared as live bars
accumulated - which means it was invisible at exactly the moments anyone looked
at it. The quote path drives touches live and carries real prices, which is the
only reason it was not worse.

Two general lessons. **A fallback that looks sensible hides a missing input**:
`or close` reads as defensive and is indistinguishable, at the call site, from
the data being present. And **the wire format is part of the model** - a
notice carrying seven fields was carrying six of the seven that mattered, and
no test asserted what a bar announcement should contain because both sides were
written to agree with each other rather than with the bar.

**A fix that looks complete often is not.** Touch counting took three rounds -
per quote, per zone-edge crossing, per bar replay - each looking finished. When
a class of bug is found, ask what else reaches the same counter.

**A safety switch checked in one place and ignored in another is worse than no
switch, because it is believed.** `TRADING_LIVE` gated a log line and nothing
else: `take` called `broker.send` unconditionally, so a run in "paper" mode
against a live bridge placed real orders. The README, the docs, `.env.example`
and the start-up banner all described a switch that was not wired to anything.
Found only by arming it against a demo and noticing the *previous* run had
already traded.

**An error usually blames the wrong component.** Every defect found against the
live terminal presented as something else. A rejected login arrived as
`connection reset by peer`, because the process exited mid-response. An
unsupported fill policy arrived as `Unsupported filling mode` - reading like a
bad order, and really a bad constant, since the symbol's own mask says FOK only.
AutoTrading being off arrived as `AutoTrading disabled by client`, naming the
client that sent the order rather than the terminal that refused it. Ask what
the component *could* know before believing what it says.

**Toggles are not switches.** `enable_algo_trading` pressed Ctrl+E once, which
is correct exactly half the time. Every restart flipped AutoTrading to whatever
it was not. The fix has to read the state back, and the first attempt at *that*
failed too - the terminal writes its log asynchronously, so a fixed sleep read
the previous line and toggled a second time. Wait for evidence, not for a
duration.

**A stop inside one volatility unit is not a stop.** The first two live trades
placed theirs 0.53 and 0.61 units from the level. The second was stopped at
4626.09 on a 1.05-point stop and price then fell to 4615: the direction was
right and the stop was inside the noise of the estimate it was protecting.
`risk_vol` from the level model is frequently under a unit on young levels -
where the zone has no recorded wicks to widen it either, so the zone-aware stop
cannot save it. Floored at `min_stop_vol`, and the size shrinks to hold the
risk budget.

The general form: **the same number cannot be both the invalidation point and
the affordable one.** The model says where the level stops being true; what a
tradable stop costs is a separate question, and answering them with one number
means the cheaper answer silently wins.

**Correct silence and broken silence are indistinguishable.** The channel going
quiet, a gate never firing, an agent never waking, a filter dropping everything:
all present as nothing happening. Every such place needs a positive signal
saying which it is.
