# `service.py`, `venues/` and `strategies/` — retired 2026-11-01

8,514 lines, replaced by Nautilus and by the strategies carved out of them. The
plan and the classification are
[`docs/specs/2026-10-31-service-becomes-nautilus-strategies.md`](../../../docs/specs/2026-10-31-service-becomes-nautilus-strategies.md);
this records what went where and what the pieces knew.

## What replaced what

| retired | replaced by |
|---|---|
| `service.Trader`'s send / record / reconcile | Nautilus's `ExecutionEngine`, `Cache` and `Portfolio` |
| `service.on_signal`'s gate sequence | `strategies/desk.py` |
| `service._edge_entry` | `strategies/entries.py` — `EdgeEntry` |
| `_rest_at_named_price`, `_restable`, `_withdraw`, `_turned_against` | `RestingEntry` |
| `_arrived`, `_park`, `_rejected_at`, `_candle_at` | `ArrivalEntry` |
| `_manage`, `_bank`, `_stale`, `_worth_keeping`, `_maybe_rearm` | `strategies/exits.py` |
| `_basket` | `strategies/basket.py`, an Actor |
| `_shadow_unfilled`, `_watch_shadows`, `_remember_untaken` | `strategies/counterfactual.py` |
| `strategies/strategy.py`'s ABC | `strategies/profile.py` plus a decision mixin |
| `strategies/dispersing.py` | `strategies/surprise.py` |
| `venues/{mt5_http,mt5_native,mt5_rpyc,broker,paper}.py` | `adapters/mt5/` |
| `venues/symbols.py` | Nautilus's `InstrumentProvider` |

## The magic number went with it, and that is the point

`Trader` told its rules apart by a broker magic number. `DEFAULT_MAGIC` is
`777_701`, and the recorded cost is that **off by one relabels every strategy
as its neighbour** - which is why the standing instruction was to judge the
desk on the broker rather than on the journal. Nautilus assigns a
`strategy_id` and carries it on every order, fill and position, so that bug
class is now impossible rather than guarded against. `DEFAULT_MAGIC` survives
in `node/live.py` as one number the bridge stamps to tell desk orders from a
human's, which is all a magic was ever good for.

`_take_all`, `_agree` and `_also_wanted` - about 200 lines letting several
rules share one object and reconcile what each wanted - went with no
replacement. Nautilus runs strategies side by side by design.

## Three modules retired for having no caller, and what they measured

The sweep after the move found these with **zero importers**: they were wired
only into `service.py`. They are here for their measurements, not their code.

**`holds.py`** - how long a touch actually takes to resolve. Measured over
**38,244 resolutions**: 4 seconds at p25 to 651 at p90, a **163x spread**, so
the single configured hold constant was right for a slice of trades and wrong
for the rest. And it persists - lag-1 autocorrelation **+0.269** on the log,
positive in 86% of series - which is the finding: the hold is predictable and
was not being predicted.

**`reach.py`** - the three distances chosen by hand (the pullback, where in the
zone to enter, the stop) and the two journal quantities that would settle them.
Nothing measured them; the module is the statement of what to measure.

**`shadow.py`** - the five confirmation gates from `confirm.md`, shadowed.
That study searched **45 TA gates across nine timeframe pairings** and found no
general confirmation layer: **17 of 8,366 cells** passed every control, and
they reduce to five narrow gates each resting on a few hundred trades. The
module recorded their verdicts and never acted on them.

**The discipline survives even though the module did not.** `shadow.py`'s
shape - record what you did not do, act on none of it - is
`strategies/counterfactual.py`, which follows declined trades and stopped ones
to their barriers because the deflated Sharpe's `Var(SR_trials)` needs the
search's losers.

## What was rescued rather than retired

`floors.py` moved **out** of `strategies/strategies/` to `strategies/floors.py`
rather than retiring with it. It is the measured answer to a one-sided book:
over **7,498 published level calls** the two directions do not share a
distribution - up has a median probability of 0.824 and down 0.880, while the
signals themselves are 48.1/51.9 - so a single absolute floor on an asymmetric
distribution produced a book that was mostly one way. `Profile.risk_scale`
reads it.

## The tests

`test_basket.py`, `test_broker_alarm.py`, `test_replicate.py` and
`test_strategies_dispersing.py` moved here whole - they test retired subjects.
`test_impulse_through_the_service.py` is the three tests split out of
`tests/test_impulse.py` that drove the impulse features through `Trader`; the
features are still tested there.

`tests/mechanics.py` was the test vehicle implementing the ABC's contract, and
`tests/conftest.py`'s only job was registering it and appending it a
`MAGIC_ORDER` slot. Both went: a decision is a mixin now, so a test that wants
one defines it in the test file - `tests/test_desk.py` has `_Deciding`,
`_Unwanting` and `_Declining`.

## What is not proven

The ported desks have handler-level coverage and **one** end-to-end engine run
on a synthetic series: market buy filled, target limit filled, stop cancelled,
position flat at +990.58. They have never traded. `research/retire/` exists so
that is recoverable rather than gone.
