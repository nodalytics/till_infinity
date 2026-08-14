# Handoff

Written 2026-08-14. What is true, what is broken, and what to do first.

## Both fixed on 2026-08-14. What they actually were

Neither was what I predicted, and the third guess was wrong too. Reading the
data settled the first inside one query; the second needed the magnitudes.

### 1. ~98% of outcomes unusable — it was the read window, not the data

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
and the full feature set — `record_outcomes` is the only place outcomes are
written and it always spreads `touch.features.to_dict()` in. Reproduced by
inflating a journal copy to 9,408 rows: 3,264 outcomes → 185 examples, and
identical at limits of 500, 5,000 and 200,000. That last equality is the tell,
and it costs one command to look for.

`read` now honours the limit it is given. `MAX_ROWS` stays as what it always
was in practice — the ceiling the CLI puts on a listing.

The old test could not have caught this: it wrote ten entries and asserted the
result was under five hundred. True whatever the clamp did. Replaced with one
that writes past `MAX_ROWS`.

### 2. The factorisation machine overflowed — unscaled features, confirmed

The guess was right and the magnitudes prove it. `strength`, `regime`, `pivot`
and `backcheck` are already in [0, 1] and `experience` is log-compressed, but
`approach_vol`, `depth_vol` and `run_vol` are ratios with a volatility estimate
underneath — a touch arriving in a dead pocket divides by a small number and
comes back arbitrarily large.

An FM multiplies its features together, so its gradients are *quadratic* in
magnitude and an unbounded input does not skew the fit, it diverges it. Scaling
one touch in 37 by 5x diverged the model within 55 examples; by 20x, within 18.
So on production it was diverged almost from the start, and `Model.predict`'s
NaN guard had been returning "no opinion" ever since — up, honest, and learning
nothing.

`encode` now saturates the three through `x/(1+x)` about a typical value of 2,
which bounds them into [0, 1) while keeping the ordering — a clip would need a
maximum, and any maximum here would call a 4v approach and a 40v one the same
event. Survives 10,000x spikes now, and predicts real numbers instead of zero.

The NaN guard stays. It was never the bug, and it is the reason a diverged
model cost accuracy rather than uptime.

## The channel speaks again, 2026-08-14

Three alerts delivered within minutes of the fixes below landing — SPX500, ETH
and SOL, all `1/1 channels`:

```
alert 'SPX500 3m — up' [level 7801.5 · this timeframe only]
alert 'ETH 3m — up'    [level 1875.1 · this timeframe only]
alert 'SOL 3m — up'    [level 75.413 · this timeframe only]
```

The journalled decision behind the last one, which is the whole chain working:

```
sol: up from above at 75.413 — p=51% vs 24% base, push +1.43
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

Worth reading because it is one chain and the obvious suspect was innocent —
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
them, dragging the base rate to 92.6% down — against which even a 99.7% call
earns only seven points. Inflated touches, lopsided base rate, eaten edge,
closed gate, silent channel. Four steps, each reasonable alone.

Splitting `observe_bar` fixed it, and the channel spoke within minutes. Detail
and the measured numbers are in [levels.md](levels.md), "The base rate is what
actually closed the gate" and "It charges zero on the replay path".

Two smaller things found alongside, both now fixed: `risk_vol` was 0.0 on every
recorded call, so `reward_to_risk` was meaningless — `vol` was optional on
`infer` and every caller forgot it. And `0.08` itself was never derived from
anything, which is still true and still open: see "0.08 is not derived from
anything" for the attempt to derive it and why the pre-fix journal cannot.

## Then, in order

See [todo.md](todo.md) for the full list. The short version:

1. **Re-measure memory now the window is bounded.** The box is 908MB with no
   swap and was OOM-killed five times on 2026-08-14. The cause was not the
   level set — it was the agents watcher holding 101,297 messages, 199MB, to
   derive fifteen triggers. Bounded at 20,000 now, and 1m went back on the
   level set once the real cause was measured. Swap still does not exist.
2. **Re-measure the outcome rate** before any `fit`, now that touch counting is
   fixed. Then `0.08`, which is still the one gate nobody chose.
3. **Run-formed levels** as an experiment, not a feature.
4. **Build the score** ([score.md](score.md)).

## What is deployed and working

Levels form on 1m/3m/5m/15m/1h/4h/1d/1w across fourteen instruments — gold, btc,
eth, sol, eurusd, gbpusd, usdjpy, audusd, usdcad, usdchf, nzdusd, usdcnh,
us100, spx500 — alert to Telegram
with confluence, deduplicated per zone, and charged the median spread before
qualifying — which now records a non-zero cost, having charged nothing until
`observe_bar` was split. Agents run on Groq with a Gemini fallback. 690 tests.

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
