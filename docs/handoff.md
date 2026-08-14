# Handoff

Written 2026-08-14. What is true, what is broken, and what to do first.

## Start here: two open bugs, both in the learning path

Neither is what I predicted, and each time the evidence corrected the guess
within one query. Do the same — read the data before reasoning about it.

### 1. ~98% of journalled outcomes are unusable as examples

`structures fit` reports **167 examples out of 9,359 outcomes**. In
`facto.dataset`, an outcome becomes an example only if its context carries
`push_vol` **and** `encode()` returns a non-empty feature dict. Almost none do.
The outcome is being recorded without the inputs that produced it.

Raising the journal read limit did *not* help (that was my second wrong guess —
the first was orphaned warm-replay outcomes; all 9,359 have parents). The count
even fell from 170 to 167 as the window slid, so qualifying examples age out
faster than new ones qualify.

**First step, and it settles it:** print one outcome entry's `context` in full
and see which keys are present.

```bash
sudo docker exec -i till-infinity python -c "
import sqlite3, json
c = sqlite3.connect('file:/app/.data/journal/journal.db?mode=ro', uri=True)
row = c.execute(\"select context from entries where kind='outcome' order by time desc limit 1\").fetchone()
print(json.dumps(json.loads(row[0]), indent=2))"
```

Compare against `facto.NUMERIC` and `facto.CATEGORICAL`, then look at where
outcomes are written (`structures/service.py`, `record_outcomes`) versus where
calls are journalled with their features (`_watch_calls`).

### 2. The factorisation machine overflows

```
RuntimeWarning: overflow encountered in dot   (river/facto/fm.py:70)
RuntimeWarning: invalid value encountered in scalar add
```

The latent factors are diverging, not occasionally misbehaving. The NaN guard in
`Model.predict` catches the symptom and returns "no opinion", so nothing crashes
and nothing lies — but the model is not learning. Likely unscaled features:
`run_vol` and `approach_vol` are unbounded in volatility units. Check their
magnitudes first, then consider scaling or a lower learning rate. Answering (1)
gives you the magnitudes for free.

## Then, in order

See [todo.md](todo.md) for the full list. The short version:

1. **Agents have never woken.** One `agents started` line across seven hours and
   ~14 thirty-minute windows. Not the throttle, not the credentials — a one-off
   `agents ask` works on both providers. That leaves the wake gate
   (`AGENTS_SPREAD_BPS`, `AGENTS_IMPORTANCE`). Make it log *why* it declined;
   a gate that never fires and a gate that never runs look identical in an empty
   log.
2. **Split `observe_bar`** — form levels from each interval's own bars, touch
   every interval from the finest. Carries a double-counting trap; read
   [levels.md](levels.md) before starting.
3. **Run-formed levels** as an experiment, not a feature.
4. **Build the score** ([score.md](score.md)).

## What is deployed and working

Levels form on 3m/5m/15m/1h/4h/1d/1w across six instruments, alert to Telegram
with confluence, deduplicated per zone, charged the median spread before
qualifying. Agents run on Groq with a Gemini fallback. 645 tests.

Production: one container on the EC2 box named in `.secrets/samuel.md`, data
under `/home/ubuntu/till-data`, config at `/home/ubuntu/till.env` (backed up to
`.secrets/prod-till.env`, gitignored). CI deploys on push to `main`.

```bash
sudo docker exec till-infinity till-infinity structures levels   # touches should read in the tens
sudo docker exec till-infinity till-infinity structures zones --feed btc --min-timeframes 2
sudo docker logs till-infinity | grep "alert '"                  # what was actually sent
```

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

**Assert properties, not tolerances.** "Less than 3x" is a number someone made
up. "One print in sixty-one cannot move a median" is the property. The first
kind passes for the wrong reason.

**A fix that looks complete often is not.** Touch counting took three rounds —
per quote, per zone-edge crossing, per bar replay — each looking finished. When
a class of bug is found, ask what else reaches the same counter.

**Correct silence and broken silence are indistinguishable.** The channel going
quiet, a gate never firing, an agent never waking, a filter dropping everything:
all present as nothing happening. Every such place needs a positive signal
saying which it is.
