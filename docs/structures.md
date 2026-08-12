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

Two details in there matter more than they look.

**The consensus is a median, taken without the venue being measured.** Robust to
the one feed that has gone wrong — a mean is dragged by the outlier it is meant
to expose, and including a venue in the number it is judged by is precisely how
a bad feed hides.

**"Spoke" and "moved" are tracked separately.** A dead feed usually keeps
sending; it just keeps sending the same price. Staleness measures the second.

## Key levels

The largest part of this package, and it has [its own guide](levels.md):
swings found by Perceptually Important Points, each level tracked as a Kalman
state whose variance *is* its zone, statistics kept **per approach side**, and
an answer of the form *given price arrived from this side, P(pushed up) is p and
the expected push is n volatility units — against a base rate of q*.

## The four shapes

| shape | what happened | needs an agent? |
|---|---|---|
| `dislocation` | this venue's price is away from the consensus | yes, unless extreme |
| `spread` | its spread is wide for the group *and* for itself | yes |
| `stale` | it has stopped moving while the others have not | **no** |
| `drift` | the volatility regime itself changed | yes |
| `level` | price arrived at a key level with a history | yes — see [levels.md](levels.md) |

A **stale** feed goes straight to `alerts`. It needs no language model to
interpret and no economic release to explain, and making it wait for an agent
would put an LLM in the path of the one message that most needs to arrive
during an outage. So does a dislocation beyond `STRUCTURES_DIRECT_DEV_BPS`
(default 100bps) — nothing on the calendar moves one venue 100bps while five
others hold still, so that is a broken quote, not a market opinion.

Everything else is *evidence*, published to `structures.signals` for an agent
to weigh against the calendar.

Routing is deliberately **not** keyed on score. Score measures statistical
rarity, and rarity is not unambiguity: an unusually wide spread is rare and is
exactly the case that needs the fundamentals before anyone is woken.

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

## `facto.py` is deliberately empty

Factorisation machines model how features *combine* — venue × instrument ×
session × calendar-proximity. That is genuinely the next thing worth having and
genuinely not buildable yet: an FM is supervised, and the honest targets are
things like "what happened over the next five minutes", which is to say
*labels*. Those are what the journal has just started collecting.

Collect first, fit second. Writing one now would mean inventing a target, and a
model fitted to an invented target learns to predict the invention.

## Environment

| | |
|---|---|
| `STRUCTURES_DIR` | where models persist (`.data/structures`) |
| `STRUCTURES_WARMUP` | readings before a score means anything (60) |
| `STRUCTURES_QUANTILE` | joint-model cutoff (0.999) |
| `STRUCTURES_SIGMA` | per-venue cutoff, in sigma (4) |
| `STRUCTURES_COOLDOWN_S` | one signal per situation per this long (900) |
| `STRUCTURES_DIRECT` | `0` to never alert without an agent |
| `STRUCTURES_DIRECT_DEV_BPS` | deviation that is a broken quote (100) |
| `STRUCTURES_SAVE_S` | seconds between saves (300) |
