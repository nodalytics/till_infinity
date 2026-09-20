# Replaying shapes on the broker's own bars

Built 2026-09-20 to answer whether the shape policy can be seeded from history.
Status: **the replay mechanics pass; the timing policy is untested.**

## Why history, and why not the journal

`Policy` learns which exit geometry suits which instrument family from full
information: `_also_wanted` asks every strategy what it would have done with each
signal, `Untaken` follows each to its own target or stop, and `_credit` files the
R-multiple per `(family, interval, arm)`. That is the right algorithm - exponential
weights, not a bandit, because the counterfactual is observed rather than missing.

The problem is volume. The live ledger holds **2,349 observations across 241
cells, 9.7 per cell**, and only 97 cells are warm. Rankings on n=5-30 are the
error its own docstring warns about.

The journal is not the answer: it holds **1,599** shadow resolutions, *fewer*
than the ledger. Simulating instead gives every `PRESETS` shape an outcome on
every historical call, which is two orders of magnitude more.

## The data

The MT5 bridge serves the broker's own M1 OHLC and, on every bar, the broker's
own **spread**. 2,519,958 bars for 42 instruments, 2026-07-20 to 2026-09-20,
pulled from the host rather than inside the container - a 2.5M-row job in the
desk's cgroup pushes a 2.6GB ceiling that has been hit 63 times.

This replaces an earlier extract from the price store, which was wrong twice
over: it had no high or low, so no barrier could be resolved at all, and its
venues were SAXO/CAPITALCOM/BINANCE while the desk trades Deriv. **74% of the
policy's evidence is on Deriv synthetics that exist on no other venue.**

Eleven feeds still do not resolve - `us100 us30 ger40 fra40 eu50 hk50 aus200
us2000 jp225 brent wti` - because Deriv names its indices differently from the
candidates in `INSTRUMENTS`. Until those aliases are added, the `index` and
energy contexts cannot be replayed.

## The gate

1,599 recorded shadows are ground truth: each carries its entry, stop, target
and what actually happened. A replay that cannot reproduce them cannot be
trusted to invent outcomes for calls never shadowed. 1,460 are on feeds now
covered.

| | agreement |
|---|---|
| exact outcome | 1158/1460 = **79.3%** |
| **stop vs target, once filled** | 846/893 = **94.7%** |
| reward correlation | **+0.875** |
| mean absolute R difference | 0.120 |
| mean R, recorded vs replayed | -0.253 vs **-0.208** |

Three corrections got it there from 57.2%, each worth keeping:

* **The journal entry's time is when the outcome was recorded, not when the
  intent was placed.** Walking forward from it finds a market that has already
  moved on, which made 259 filled trades look unfilled. The start is
  `time - seconds`.
* **MT5 bars are bid.** `_step_untaken` fills a BUY when the *ask* reaches the
  entry, so the test is `low + spread <= entry`, and a SELL pays the spread on
  the way out.
* **A same-bar tie goes to the stop.** At one-minute resolution the order is
  unknowable, and taking the target is how a replay flatters itself.

## What passes, and what is still unproven

**The barrier mechanics pass at 94.7%.** Given a fill and a time window, the
replay resolves stop against target as the live desk did, and the R it computes
correlates at 0.875 with a mean absolute error of 0.120R.

**The fill model differs, and the replay is probably the more accurate one.**
118 of 150 `never filled` records resolve to a barrier here. `_step_untaken`
tests `reached` only on quotes it receives, while a bar's low and high are the
true extremes of that minute, so the desk records "never filled" for entries the
market did trade. That is a finding about the desk rather than about the replay:
**shadow fills are under-counted, so shapes resting a distant entry earn less
evidence than they should.** It also explains the replay's +0.045R optimism -
the extra fills are marginal ones.

**The timing policy is untested, and this is the gap that matters.** Every number
above uses each record's *recorded* duration as the time budget. That is an
outcome-derived quantity, so it establishes only that the mechanics work *given*
the right window - not that the right window can be derived from a shape's
`fill_by` and `hold` alone, which is exactly what seeding unshadowed calls
requires. That has to be validated before any ledger is written.
