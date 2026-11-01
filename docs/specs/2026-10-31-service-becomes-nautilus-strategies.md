# `service.py` becomes several Nautilus strategies

**Written 2026-10-31**, before any of it is built, because
`strategies/service.py` is 5,024 lines with a 4,349-line `Trader` class and a
port that size is only reviewable if the classification is written down first.

The finding that shapes the whole thing: **most of `Trader` is not ours to
port.** The split it implements is already documented in
`strategies/strategies/strategy.py`:

| | decides | where it lives now |
|---|---|---|
| `strategy` | is this signal worth trading, and where do the stop and target go | `strategies/` |
| `plans` | how much may be lost, per trade and per day | `risk/plans.py` |
| `risk` | may *this account, right now* take another one | `risk/guard.py` |
| `service` | send it, record it, and reconcile what came back | Nautilus |

The third column was added on 2026-11-01, when the last two rows finally
reached the package their names describe. `guard.py` and `plans.py` had stayed
in `strategies/` through two attempts, because the limit is an account fact
while the *number* lived in `Settings` - 1,583 lines of `TRADING_*` knobs
about what to trade and on which terminal, which `risk` may not import. The
seam is `risk/envelope.py`, a frozen projection of the 22 fields the gates
actually read, declaring **no defaults** so a number cannot come to live in
two places.

Two things that move exposed rather than caused, both worth knowing when
reading the rows above:

* **`TRADING_RISK_PLAN` was read, printed and never applied.** `apply_plan`'s
  only caller was the CLI. It is applied in `Settings.from_env` now - not by
  the node, because `from_env` runs in six live places and a node applying a
  plan to its own instance would leave the other five on the defaults.
* **Nothing sized a trade, so nothing could place one.** The first row's
  "where do the stop and target go" worked and the *volume* was nobody's: a
  5,136-bar replay accepted 25 intents and refused all 25 at
  `(desk):zero-volume`, `Profile.risk_scale` had no caller in the package at
  all, and the spec `Desk._spec` built left the tick value on a dataclass
  default - 1.0, which is right for a standard lot of nearly every
  dollar-quoted instrument the desk trades and wrong for everything else.
  The step is in `Desk.consider` now, between the decision and the order,
  because sizing needs the account and a producer reading bars cannot see
  one. See `strategies/sizes.py`; `tests/test_first_trade.py` is the first
  test in the suite that runs the whole chain.
* **`Guard.allows` has no production caller.** Only `Guard.basket` runs,
  through `BasketExit`, so the account-level gate chain and its eighteen
  reason strings are exercised by tests alone and have never reached a
  journal. That is a gap in the second row above, not in the table. It is the
  **last** of these: with sizing wired, the risk layer's remaining absence
  from the trading path is this one chain.

The fourth row is `Trader`, and Nautilus's `ExecutionEngine`, `Cache` and
`Portfolio` are that row. So this is mostly deletion, and the part that is
genuinely ours is smaller and more interesting than the line count suggests.

## Why several strategies and not one

`Trader` runs every rule inside one object and tells them apart by a broker
magic number. `DEFAULT_MAGIC` is `777_701`, and the desk has already recorded
what that costs: **off by one relabels every strategy as its neighbour**, which
is why the standing instruction is to judge the desk on the broker rather than
on the journal.

Nautilus puts a `strategy_id` on every order, every fill and every position,
assigned by the framework and carried through the whole lifecycle. Running each
rule as its own `Strategy` makes that bug class **impossible** rather than
guarded against, and it is the single strongest argument for the carve-up.

It also removes `_take_all`, `_agree` and `_also_wanted` - roughly 200 lines
whose job is to let several rules consider one signal and reconcile what they
each wanted. Nautilus runs strategies side by side by design; each one sees the
data and acts or does not.

## The classification

### Nautilus owns it - delete, do not port

| `Trader` method | what replaces it |
|---|---|
| `_positions`, `_tick`, `_quote`, `_mark_best` | `self.cache.positions()`, `self.cache.quote_tick()` |
| `_reconcile`, `_orphans` | `ExecutionEngine` reconciliation on start |
| `_protect` | a bracket order, or `modify_order` |
| `_forget_path`, `_restore_refs`, `_restore_learned`, `_restore_intervals`, `_remember_marks`, `_recall_marks`, `_known` | `Cache`, and the framework's own state |
| `execution`, `_check_order`, `_check_magics`, `_check_autotrading`, `_watch_reachable` | `ExecutionClient` connection state, `on_order_denied` |
| `_refresh_swaps` | `InstrumentProvider` |
| `_expire`, `sweep` | `self.clock.set_time_alert`, `set_timer` |
| `_market_closed` | `on_order_rejected`'s reason |
| `_book_progress`, `_book_against` | `self.portfolio` |

### Ours - port

**The gate sequence.** `on_signal` is ~170 lines of one gate per branch, and
every refusal it can emit is a journal reason the desk reads. That is the core
of a strategy's `on_data`. With it: `_undealable`, `_closing_soon`,
`_shut_for`, `_quote_is_stale`, `_too_wide_to_leave`.

**The counterfactual.** `_shadow_unfilled`, `_watch_shadows`,
`_remember_untaken`, `_resolve_untaken`, `_step_untaken`, `_record_untaken` -
what would have happened to the trades it declined. This is the "keep the
losers" discipline that every honest trial count depends on, and nothing in
Nautilus does it. Port carefully.

**The journal reasons.** `_settle`, `_record_intent`, `_record_refusal`,
`_unattributed_context`, `_record_gate`. Nautilus persists orders, fills and
positions; it does not persist *why*, and the why is the whole value of the
journal ([ADR 0005](../adr/0005-the-journal-is-the-record-not-the-hot-path.md)).

**The feature intake.** `_read_the_trend`, `_warm_sessions`, `_warm_reach`,
`_warm_trend`, `_hand_over_*`, `_note_push` - these hand published readings to
the rules. Most of this becomes indicator registration plus `on_data`, now that
`till_infinity/indicators/` exists.

### The carve-out: entries

Each becomes its own `nautilus_trader.trading.Strategy`.

1. **`EdgeEntry`** - market order on an edge signal. From `_edge_entry`.
2. **`RestingEntry`** - a limit left at a named price, withdrawn if price turns
   against it first. From `_rest_at_named_price`, `_restable`,
   `_leave_with_broker`, `_withdraw`, `_turned_against`.
3. **`ArrivalEntry`** - entry when price arrives at a level and the bar
   confirms a rejection. From `_arrived`, `_rejected_at`, `_candle_at`, `_park`.

`Dispersing` ("statespace-surprise") is the one registered decision rule left
and stays a decision rule: it says whether there is a trade, and one of the
three entries above places it.

### The carve-out: exits

Nautilus has no "exit strategy" concept, so these are management on the
strategy that opened the position - which is correct, because an exit rule that
could close another strategy's position is the magic-number bug wearing a new
hat.

| | from |
|---|---|
| **`TrailManage`** | `_manage`, `_maybe_rearm`, `_rearm_stopped` |
| **`BankTake`** | `_bank`, `_announce_bank` |
| **`TurnExit`** | `_turn_exit`, and `turning.TurnExit` which already exists |
| **`StaleExit`** | `_stale`, `_worth_keeping`, `_stale_after`, `_still_building` |
| **`BasketExit`** | `_basket` - the only one that is genuinely portfolio-wide, so it belongs in an Actor rather than a strategy |

## What this does not change

**`risk` stays above Nautilus, not inside it.** Checked on 1.221.0 and
re-checked on 1.231.0:
`RiskEngine`'s entire public surface is `set_max_notional_per_order`,
`set_trading_state` and `reset`, with a config of `bypass`, two rate throttles,
`max_notional_per_order` and `debug`. Every actual check - `_check_order`,
`_check_orders_risk`, `_check_order_price` - is private, with no registration
hook. **Risk is not pluggable**, unlike metrics, where `register_statistic` is
a real plugin point. So `till_infinity/risk/` decides size pre-trade and
Nautilus's engine is the last-line notional and rate cap, which is already how
`node/promotion.py`'s `Allocation` emits `max_notional_per_order`.

**`strategies/venues/` retires with this and not before.** 2,211 lines of
pre-Nautilus execution clients - `mt5_http`, `mt5_native`, `mt5_rpyc`,
`broker`, `paper`, `symbols` - that `adapters/mt5/` supersedes by design but
that `service.py` still imports. They are redundant and load-bearing at the
same time, which is why they are still here.

## Order of work

1. A shared base carrying the gate sequence and the journal reasons, so the
   three entries differ only in how they place.
2. `EdgeEntry` with `Dispersing`, end to end, through `BacktestNode` - the
   smallest thing that proves the shape.
3. `RestingEntry` and `ArrivalEntry`.
4. The exits, in the order above.
5. The counterfactual, which is the one piece with no framework equivalent and
   the one most worth not rushing.
6. Retire `service.py` and `strategies/venues/` together.

Each step keeps the suite green, and none of them is finished until the
behaviour it replaces has a test that would have caught its absence.

## Step 6 landed, 2026-11-01

Steps 1 to 5 are done, the desks are wired into both nodes, and
`service.py`, `strategies/venues/` and `strategies/strategies/` are in
`research/retire/strategies/`. `holds.py`, `reach.py` and `shadow.py` went with
them for having no caller once `service.py` was gone; `floors.py` moved up a
level instead, because `Profile.floored_target` still reads it.

It was held for most of a day on something that was not the port.
`BacktestEngine.run()` aborted with `double free or corruption (out)` and exit
134 - reproduced with one bar, no strategy, and without importing
`till_infinity` at all. The handler-level suite was green throughout, because
no test in it enters the run loop, so the suite could not tell a working engine
from an aborting one. That was the whole reason to hold: retiring the traded
path in favour of a path whose loop had never completed would have left the
desk with no proven way to trade.

The cause was `nautilus_trader` 1.221.0 itself - not this workstation's glibc,
which was the first guess and was refuted on an older one, and not the data
shape, which was the right second question and also no. Every release that
fixes it needs Python >= 3.12, and 1.221 was the last line with a cp311 wheel,
so the pin and the interpreter had to move together: **Python 3.13.5 and
`nautilus_trader>=1.231,<1.240`**. The bisection and both wrong guesses are in
[`backtest-engine-abort.md`](../backtest-engine-abort.md).

With the loop running, the desks have one synthetic end-to-end backtest
(+990.58 on generated bars, which proves the loop and nothing about the edge)
on top of the handler coverage. What they do not have is a traded record, and
that is the next thing they need rather than another test.

## Step 4 had not landed, 2026-11-01

"Steps 1 to 5 are done" above was wrong about step 4, and the way it was wrong
is worth more than the correction. Every piece of the exits table existed, was
tested and was correct. None of it was **reachable**:

| piece | state before |
|---|---|
| `exits.Exits` | no constructor call anywhere in `till_infinity/` |
| `manage.advance`, `manage.partial` | no caller |
| `Profile.protection`, `Profile.hold_for` | no caller |
| `Exits.conflicts` | no caller, so the "exactly one may trail" rule was a docstring |
| `Exits.apply` | named in the class docstring and never written |
| `BasketExit._close` | published on `alerts`, whose only subscriber is the Telegram notifier |

So the exit a trade actually got was whichever bracket its `place` happened to
submit: the same exit for every decision, with no way for a decision to state
one, and - because `RestingEntry.place` leaves a bare limit and its
`on_order_filled` only forgets the wait - **no exit at all for a rest that
filled**. The basket stop logged "closing all N position(s)", counted them
closed, and closed none of them.

The fix is the third mixin the docstrings had been describing as if it existed.
`exits.ExitMechanism` is composed **in front of** the entry, because two of the
three entries override `on_order_filled` without calling `super()`:

    class SurpriseEdge(Surprise, ManagedExit, EdgeEntry): ...
        #                ^decision ^exit      ^entry

`VenueExit` leaves the exit where the venue holds it, which is the honest
pairing on a deploy whose bridge is already trailing; `ManagedExit` owns the
stop and runs `advance`, `partial` and the clocks. **Both ship with every
policy off**, which is the finding `manage.py` records rather than a default:
break-even and trailing each cut the loss tail and each cut winners, and
nothing here answers which dominates. What changed is that the four
combinations can now be run at all.

Two things found on the way, each a separate reason the desk could not trade:

* **`node/desks.py` built the bare entries.** `EdgeEntry`, `RestingEntry`,
  `ArrivalEntry`, with no decision mixin in front of them - and `Desk.decide`
  raises by design, so every registered desk raised `NotImplementedError` on
  its first proposal. The composed leaves were tested and built by nothing.
  `strategies/leaves.py` is now the one place a desk's three pieces are named,
  and `tests/test_exit_mechanisms.py` points the end-to-end harness at
  `desks.build_all()` rather than at a class a test names - which is the
  assertion that catches a working leaf nobody builds *and* a builder that
  builds the wrong thing, in one run.
* **`statespace`'s side leaves could decide and not be sized.** `SideProfile`
  is a plain class, because `statespace` may not import `strategies`, and
  `Desk` sizes through `profile.multipliers`, which only a `Profile` has.
  `leaves.StatespaceLongProfile` is the seam.

### What is still not asymmetric, and is labelled rather than asserted

The exit can now differ per rule, per trade and per **side** -
`exits.protection_for` resolves `boom_500_index.sell` before
`boom_500_index`, in the spelling `DEFAULT_STOP_OVERSHOOT` already uses, for
the reason `risk/scaling.py` gives: on a jump instrument a stop on the spike
side can only be gapped over.

**The shipped table is empty and every leaf resolves both sides identically.**
No long/short difference in *exit* behaviour has been measured here. The
measured asymmetry next door is in the gapping - 2.0 on a boom's sell and a
crash's buy - and converting an overshoot multiple into a trail distance is
arithmetic nobody has done. A test asserts the table is empty, so the
capability cannot quietly become a claim.

Also still unmeasured and deliberately not wired: `Profile.protection` and
`Profile.hold_for` remain uncalled, so no rule yet carries its own protection
speed or hold; `Intent.trail_levels` is off because no `Book` of levels reaches
a strategy, and a level trail with no levels is the inert shape again; and
`Settings.max_hold` (1800s) is **not** folded into the exit clock, because
`research/spending.md` found the holds already running short - 50 of 133 closes
exited at 5% of their planned target when the clock ran out before the geometry
could resolve.
