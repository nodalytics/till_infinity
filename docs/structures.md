# Structures

The numeric layer. It watches quotes and fast bars, learns continuously what is
normal, and says when something is not — **arithmetic, not judgement, and it
does not stop when a model provider does.**

```bash
uv run till-infinity structures watch --redis redis://localhost:6379
uv run till-infinity structures info      # what the models have learned
```

## Why it is separate from `agents`

The deciding argument is dependency direction. `agents` needs credentials for a
model provider and cannot run without them. The layer that watches for a broken
feed must run continuously whether or not you are paying for inference and
whether or not the provider is up — putting it inside `agents` would make the
always-on layer inherit the availability of the expensive, occasionally-absent
one.

Three consequences follow, and they are the design:

**River models are stateful and incremental.** A `learn_one`/`predict_one` loop
wants every tick. `agents` batches into windows because a model call takes
seconds, and inside `agents` this would inherit that batching and lose exactly
the tick-level learning that makes online ML worth using.

**It replaces a threshold that could never have been right.** The gate in
`agents` was `spread_bps >= 8` — a constant, when the comparison that matters is
"unusual *for this venue, right now, against the others*". A constant cannot
express that. An online model is precisely that comparison.

**It can talk to humans directly.** Not everything needs an agent's judgement.

```
prices ──▶ structures ──┬──▶ structures.signals ──▶ agents ──▶ alerts
                        └──▶ alerts (unambiguous only)
```

## Everything is measured against the other venues

An anomaly detector fed one venue's spread learns what is normal for that
venue. Useful, and not the point — the project collects six venues because the
disagreement between them carries information no single feed does.

| feature | what it asks |
|---|---|
| `dev_bps` | how far this venue's mid is from where the others agree it is |
| `spread_ratio` | its spread against the group's, right now |
| `staleness_ratio` | how long it has been still, against how long the group has |

### The formulas

For venue `v` at time `t`, with `V` the set of venues quoting the same
instrument and still fresh (a quote older than 300s is not evidence about now):

**Consensus** — the median of everyone *except* the venue being judged:

```
mid*(v)     = median{ mid(u) : u in V, u != v }
spread*(v)  = median{ spread_bps(u) : u in V, u != v }
```

The exclusion is not a detail. Including a venue in the number it is measured
against is precisely how a bad feed hides: with six venues one wrong reading
barely moves the number, and with two it moves it halfway. And a **median**
rather than a mean because a mean is dragged by the outlier it exists to expose.

**Deviation** — how far this venue sits from where the others agree, in basis
points, signed:

```
dev_bps(v)      = (mid(v) - mid*(v)) / mid*(v) x 10000
abs_dev_bps(v)  = | dev_bps(v) |
```

**Spread ratio** — wide compared with everyone quoting the same instrument at
the same instant, not wide against a constant:

```
spread_ratio(v) = spread_bps(v) / spread*(v)          (1.0 if spread* = 0)
```

**Staleness** — seconds since this venue's mid last *changed*, against how long
the group has been still:

```
still(v)            = t - moved(v)
group_still         = median{ still(u) : u != v }
staleness_ratio(v)  = still(v) / max(group_still, 1s)
```

The floor of one second in the denominator is load-bearing. When every other
venue is updating, their median stillness is near zero — dividing by it either
explodes or, worse, gets guarded away to a constant, blinding the ratio at
exactly the moment it matters most. That was a real bug.

Two details matter more than they look.

**`moved` is not `t`.** A dead feed usually keeps *sending*; it just keeps
sending the same price. `moved(v)` only advances when the mid actually changes,
which is what makes a stale feed detectable at all.

**Everything is a ratio or a basis point.** No feature carries a price, which is
what lets one model serve gold, BTC and EURUSD without per-instrument tuning.

## Key levels

The largest part of this package, and it has [its own guide](levels.md):
swings found by Perceptually Important Points, each level tracked as a Kalman
state whose variance *is* its zone, statistics kept **per approach side**, and
an answer of the form *given price arrived from this side, P(pushed up) is p and
the expected push is n volatility units — against a base rate of q*.

The level's price is the **origin** — where the leg in ended and the leg out
began — and not the wick's extreme. The extreme is not a second level; it is how
far past the first one price was pushed, which is what makes the zone
[asymmetric](levels.md#5b-the-origin-and-why-it-is-not-the-extreme).

## The four shapes

| shape | what happened | needs an agent? |
|---|---|---|
| `dislocation` | this venue's price is away from the consensus | yes, unless extreme |
| `spread` | its spread is wide for the group *and* for itself | yes |
| `stale` | it has stopped moving while the others have not | **no** |
| `drift` | the volatility regime itself changed | yes |
| `level` | price arrived at a key level with a history | **no**, when actionable |

A **stale** feed goes straight to `alerts`. It needs no language model to
interpret and no economic release to explain, and making it wait for an agent
would put an LLM in the path of the one message that most needs to arrive
during an outage. So does a dislocation beyond `STRUCTURES_DIRECT_DEV_BPS`
(default 100bps) — nothing on the calendar moves one venue 100bps while five
others hold still, so that is a broken quote, not a market opinion.

An **actionable level call** also goes straight through, and it is the one
exception to the paragraph above rather than an instance of it. A fundamental
absolutely can explain why a level gave way — but a level call is the only shape
here that is a *finding* rather than a fault, and it is what the channel exists
for. Every call that reaches the alert path has already passed `actionable`
(enough evidence, enough separation from the base rate, enough size), which is a
stricter gate than any score. Routing it through agents that are switched off
means publishing it to a topic nobody is subscribed to, which is exactly what
happened: the channel carried nothing but feed faults. `STRUCTURES_ALERT_LEVELS=0`
restores the old behaviour if an agent should see them first.

Everything else is *evidence*, published to `structures.signals` for an agent
to weigh against the calendar.

Routing is deliberately **not** keyed on score. Score measures statistical
rarity, and rarity is not unambiguity: an unusually wide spread is rare and is
exactly the case that needs the fundamentals before anyone is woken.

## A note on units

Distances here are in **basis points** (1bps = 0.01%), and ratios like
`spread_ratio` are dimensionless. The levels model uses a third unit —
**volatility units**, where `1v` is one typical move — which is defined with
worked conversions in [levels.md](levels.md#0-what-a-volatility-unit-is).

## The detectors, and what their numbers mean

Three scorers, each answering a different question, and each with a different
notion of "unusual" — which is why none of their outputs is comparable with
another's without the conversions below.

### GaussianScorer — is this unusual *for this venue*

One per `(instrument, venue, metric)`. It fits a normal to the stream and
returns

```
score(y) = 2 * | CDF(y) - 0.5 |
```

which is in `[0, 1]` and two-tailed. For a normal that is exactly

```
score = erf( z / sqrt(2) )
```

so a sigma threshold converts **exactly**, not by a fit:

| sigma | threshold | expected rate |
|---|---|---|
| 2 | 0.9545 | ~1 in 22 |
| 3 | 0.9973 | ~1 in 370 |
| **4** | **0.999937** | **~1 in 15,787** |

That is why the knob is `STRUCTURES_SIGMA` and not a raw score: sigma is the
unit anyone reasoning about markets already thinks in.

**The metric must be the one the fit assumes.** `dev_bps` is scored *signed*,
not absolute. A signed cross-venue deviation is roughly normal, so the fit is
sound and the two-tailed score already covers both directions; folding it to
absolute first makes it half-normal, which a normal cannot represent — the
upper tail is then permanently overweight and the scorer cries wolf. That was
also a real bug.

### HalfSpaceTrees + QuantileFilter — is this *combination* unusual

Scores the joint vector `(abs_dev_bps, spread_ratio, staleness_ratio)`, catching
combinations no single threshold would: a small deviation is fine, a slightly
wide spread is fine, both at once on a venue that has gone quiet is not.

Its score is **not calibrated** — on normal cross-venue data the median lands
around **0.77**, so a fixed `>= 0.75` cutoff fired on 55% of everything.
`QuantileFilter` supplies the missing calibration by tracking the running
distribution of scores and flagging only

```
score(x) > Q_q( scores seen so far )        q = 0.999
```

A threshold that retunes itself as the market changes, which is the whole reason
to be online. It also refuses to learn from what it just flagged, so a detector
cannot drift toward accepting its own detections.

Inputs are min-max scaled first, because HST partitions ranges and staleness in
seconds would otherwise dominate a deviation in basis points.

### ADWIN — has the distribution itself moved

Maintains an adaptive window over absolute returns and cuts it wherever two
sub-windows stop looking like the same distribution — a Hoeffding-style bound,
so no window length has to be chosen in advance and the horizon is discovered
rather than configured.

**Absolute** returns, because ADWIN watches the size of moves: a market that
starts trending and one that starts chopping both register, whereas signed
returns average to zero either way and would hide both.

```
r(t) = | mid(t) - mid(t-1) | / mid(t-1) x 10000
```

Confirmation across timeframes then applies (§*One timeframe is not enough* in
the module): a slow timeframe is believed alone, fast ones need a quorum.

## Timeframes

Ticks up to five-minute bars. Above that, "cross-venue disagreement" is mostly
different bar boundaries rather than different opinions about the price.

## How it avoids crying wolf

Getting this wrong is the default outcome, and it was wrong twice while being
built:

**HalfSpaceTrees scores are not calibrated.** On normal cross-venue data the
median score is about 0.77, so a fixed `>= 0.75` cutoff fired on **55% of
everything**. `QuantileFilter` fixes it by learning the running distribution of
scores and flagging only the top `q` — a threshold that retunes itself as the
market changes, which is the whole reason to be online.

**A signal that cannot be named is not sent.** The joint model reports rare
*combinations* without saying which part was rare. A combination in which no
single component is remarkable is a rare shade of ordinary, and reporting it
sends someone looking for something that is not there. Adding that rule took
false positives from 1.5% to under 0.2%.

Three more, each of which silently destroys a detector:

- **Score before learn, always.** Learning first teaches the model the anomaly
  is normal, and it then scores it as normal.
- **Do not learn from outliers.** One 30bps print folded into the variance makes
  the next 3bps look ordinary — the detector goes quiet right after the
  interesting thing starts.
- **Score the signed deviation.** `GaussianScorer` fits a normal; a signed
  cross-venue deviation is roughly normal, and folding it to absolute first
  makes it half-normal, which a normal fit cannot represent.

Measured on synthetic six-venue data, 1800 quotes of a calm market:

| | |
|---|---|
| false positives | 0–3 (0–0.17%) |
| 30bps dislocation | caught |
| 3bps dislocation | caught |
| spread 10x the group | caught |
| feed stale for 22s | caught |

## Persistence

An online model that resets on restart has learned nothing, so state is saved
to `.data/structures/models.pkl` and restored on start.

Pickle, because river models are ordinary Python objects with no serialisation
format of their own. The consequence is stated rather than hidden: a state file
records the river and Python versions it was written with and **refuses to load
into a mismatch**, costing a warmup. Silently loading a half-restored model
would give scores that look fine and mean nothing.

Writes are atomic — temp file, then rename — so a process killed mid-save
leaves the previous state intact.

## What it records

Every detection is journalled with the features it was found from. Those
features cannot be recovered later: the consensus at that instant is not
written down anywhere else, and by tomorrow the quotes table describes a
different world. See [journal.md](journal.md).

## Planned: grading a regime change instead of flagging it

ADWIN answers *whether* the regime changed. It has no opinion on **how much**,
and that gap is now load-bearing: a confirmed change applies a flat `x 0.4` to
every level's accumulated history, so a marginal change and a violent one are
treated identically — and `0.4` is a number somebody picked.

Two ways to fix it, in the order they are worth doing.

### 1. Percentiles (cheap, and the pattern is already proven here)

The anomaly detector had exactly this defect. HalfSpaceTrees' raw scores turned
out to be uncalibrated — median 0.77 on normal data — and a fixed cutoff fired
on 55% of everything. `QuantileFilter` fixed it by learning the running
distribution of scores. Drift has the same shape of problem and no fix yet.

Three applications, most valuable first:

**Grade the decay.** Keep a running quantile of observed change magnitudes and
scale by where this one falls:

```
decay = 1 - p * (1 - REGIME_DECAY)      p = percentile of this change
```

A 99th-percentile change nearly resets the level's history; a 55th-percentile
one barely touches it. That replaces a hand-picked constant with something
learned, which is the same move that rescued the anomaly detector.

**Gate the confirmation.** ADWIN fires on changes that are statistically real
and practically trivial. Requiring the new volatility to sit outside, say, the
85th/15th percentile band of its own recent history removes those, more cheaply
and more precisely than the multi-timeframe quorum — and complementary to it,
since one filters by size and the other by agreement.

**Make the regime a feature.** "Volatility is at the 92nd percentile of the
last month" is directly usable by the levels kNN; "volatility is 25bps" is not.
`river.stats.RollingQuantile` is the piece.

### 2. Bayesian online changepoint detection (more work, one real trap)

BOCPD maintains a posterior over **run length** — how long since the last
changepoint — so it gives a *probability* of a change rather than a flag, and
its run-length posterior directly answers **how old the current regime is**.

That last part is the thing percentiles cannot supply, and it matters: level
evidence currently decays on wall-clock days, which is a proxy for regime age
rather than the thing itself. Two weeks inside one stable regime should discount
a level's history far less than two weeks spanning three.

**The trap is the predictive model.** BOCPD needs one, plus a hazard rate — both
assumptions ADWIN pointedly avoids. A Gaussian model on fat-tailed financial
returns fires on kurtosis alone and would be *noisier* than what is here now.
Done properly it wants a normal-inverse-gamma conjugate prior, whose posterior
predictive is Student-t and handles the tails correctly. That is the difference
between an improvement and a regression, and it is not optional.

Cost: river does not ship it, so it is an implementation — log-space numerics
for stability and run-length pruning to keep it O(1) per step rather than O(t).

**Order.** Percentiles first, because they deliver the graded magnitude — the
main reason to want BOCPD — at a fraction of the cost and with no distributional
assumption. BOCPD after, once it is clear whether regime *age* changes any
decision, rather than writing a detector that can be subtly wrong to find out.

### 3. Hidden Markov models, and why they are not an alternative to `facto`

Asked often enough to be worth answering here: an HMM and a factorisation
machine are not competing for the same job, and comparing them directly is a
category error.

| | asks | needs | returns |
|---|---|---|---|
| **`facto`** | given *this* touch, how far does price push | labels | a number, in volatility units |
| **HMM** | which world are we in, and how do worlds succeed each other | a sequence | a state, or a posterior over states |

An HMM cannot predict a push, so it cannot replace the FM. What it can do is
**fill the `regime` slot** — the feature that exists so a touch is compared with
touches from a market that felt the same. Today that is planned as a rolling
quantile of volatility; an HMM would put a discrete state there instead. The
two then compose rather than compete, and cleanly: `encode` already one-hots
categoricals, so a state label arrives as `regime_state_violent` alongside
`side_above` and is exactly the kind of thing an FM is built to cross with
everything else.

**Against BOCPD, which is the comparison that matters**, they split on one
axis:

- **BOCPD gives regime _age_.** The run-length posterior answers "how long
  since the last change", which is the quantity the decay actually wants.
- **HMM gives regime _identity_.** "This is the quiet regime we were in last
  month." BOCPD structurally cannot say that — it knows only time since the
  break, never that the current stretch resembles an earlier one.

So the question that decides whether an HMM is worth building is empirical and
already answerable: **do touches cluster by recurring regime identity, or just
by volatility level?** If a rolling percentile captures it, identity buys
nothing. The outcome machinery grades that the same way it grades run-formed
levels, and doing so costs nothing but a comparison.

**Three cautions, and the third is the serious one.**

1. The fat-tail trap is the same as BOCPD's. Gaussian emissions on financial
   returns change state on kurtosis alone, so Student-t emissions are not
   optional here either.
2. river ships neither, so either is an implementation rather than a
   dependency.
3. **An HMM invites look-ahead by default.** Standard fitting is Baum-Welch
   over a whole sequence, and the standard state estimate is *smoothed* —
   forward-backward, which uses the future to label the past. Only the
   **filtered**, forward-only estimate is admissible under
   [levels.md](levels.md) §2. An HMM fitted in batch over all history and then
   used to label historical touches would leak thoroughly and backtest
   beautifully, which is the worst combination available and the specific
   failure this project designs out rather than tests for.

**Order, therefore: unchanged.** Percentiles first — same slot, a fraction of
the cost, no distributional assumption, no look-ahead hazard. An HMM is worth
revisiting only after the recurrence question above has been asked of real
outcomes, and it sits behind BOCPD rather than ahead of it, because regime age
has a decision waiting on it and regime identity does not yet.

## `facto.py` — the interaction model

Factorisation machines model how features *combine*. The levels model treats
them one at a time — deviation, then spread, then how recently the level broke
— and a back check on a strong level in a violent regime is not the sum of
those three. An additive model cannot say so; an FM can.

This was empty until the journal started attaching outcomes, because an FM is
supervised and there was nothing to fit. Collect first, fit second.

```bash
uv run till-infinity structures fit
```

### Walk-forward by construction

Every example is **predicted before it is learned**, in time order:

```
for example in sorted(examples, key=time):
    error += |predict(x) - y|
    model.learn(x, y)
```

There is no split to arrange incorrectly and no way for a later example to
inform an earlier prediction. A shuffled split would leak badly here: two
touches at the same level minutes apart are nearly the same observation, so
splitting them across train and test measures memorisation.

### Two baselines, always

A score alone means nothing, so it is reported beside:

- **predict the average** — the floor. A model that cannot beat this has
  learned nothing from the features.
- **the levels model** — what `reactions.infer` said at the time, already in
  the journal. An FM that does not beat the model it was meant to improve on
  is not an improvement.

Both need beating by a **margin**, not by any amount. On pure noise the FM
edged the running mean by 1.3% — not from learning, but because the running
mean starts cold and is handicapped early. Calling that a win is how a system
talks itself into believing its own noise.

### It declines rather than guess

Below 200 examples it reports the count and stops. A factorisation machine over
eighteen rows will produce a number, and the number is noise wearing a decimal
point. Verified on synthetic data with a pure interaction — sign depending on
`side × regime` with no main effect, which is exactly what an additive model
cannot represent:

```
900 examples · MAE 0.301v (mean 1.513v) · direction 98% vs 75%
```

### Two river edges worth knowing

`FMRegressor.predict_one` raises `AttributeError` rather than anything
catchable by intent, in two situations: before anything has been learned, and
when given fewer than two features. The first is hit by progressive validation
on **every first example**; the second by any sparse row. Both return zero
here, which is also the honest answer — a model with no history, or no pair to
look at, has no opinion.

### Examples have an expiry, and it is not time

A measurement bug corrupts every example recorded while it was live, not only
the numbers it printed. Inflated touch counts fed `experience` and `strength`;
a pooled base rate made `edge` wrong on every row. Examples from before those
fixes describe a model that no longer exists, and fitting across the boundary
teaches the FM the relationship between features and outcomes *as they were
mismeasured* — worse than no model, because it looks like one.

`fit(journal_db, since=<unix ts>)` counts only what was recorded after a
known-good point. There is deliberately no default: where that boundary sits is
a judgement about a particular deployment's history, and the code cannot know
it. The cost is real — it resets progress toward `MIN_EXAMPLES` — and it is
still cheaper than a confident model fitted on a ruler that has since changed
length.

## Environment

| | |
|---|---|
| `STRUCTURES_DIR` | where models persist (`.data/structures`) |
| `STRUCTURES_WARMUP` | readings before a score means anything (60) |
| `STRUCTURES_QUANTILE` | joint-model cutoff (0.999) |
| `STRUCTURES_SIGMA` | per-venue cutoff, in sigma (4) |
| `STRUCTURES_COOLDOWN_S` | one signal per situation per this long (900) |
| `STRUCTURES_DIRECT` | `0` to never alert without an agent |
| `STRUCTURES_ALERT_LEVELS` | `0` to hold actionable level calls back for an agent |
| `STRUCTURES_DIRECT_DEV_BPS` | deviation that is a broken quote (100) |
| `STRUCTURES_SAVE_S` | seconds between saves (300) |
| `STRUCTURES_CHARGE_SPREAD` | `0` to judge level calls on their gross push, for comparison only — it says so in the log, because a configured `cost_vol: 0.0` and a broken one are otherwise identical ([levels.md](levels.md)) |
