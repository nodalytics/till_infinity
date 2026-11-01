# `service.py` becomes several Nautilus strategies

**Written 2026-10-31**, before any of it is built, because
`strategies/service.py` is 5,024 lines with a 4,349-line `Trader` class and a
port that size is only reviewable if the classification is written down first.

The finding that shapes the whole thing: **most of `Trader` is not ours to
port.** The split it implements is already documented in
`strategies/strategies/strategy.py`:

| | decides |
|---|---|
| `strategy` | is this signal worth trading, and where do the stop and target go |
| `plans` | how much may be lost, per trade and per day |
| `risk` | may *this account, right now* take another one |
| `service` | send it, record it, and reconcile what came back |

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

**`risk` stays above Nautilus, not inside it.** Checked on 1.221.0:
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

## Step 6 is held, as of 2026-11-01

Steps 1 to 5 are done and the desks are wired into both nodes. **The
retirement is not**, and the reason is not the port:
`nautilus_trader`'s `BacktestEngine.run()` aborts on this workstation with
`double free or corruption (out)` and exit 134, reproduced with one bar, no
strategy and without importing `till_infinity` at all. See
[`backtest-loop-aborts-here.md`](../backtest-loop-aborts-here.md) for the
bisection.

So the ported desks have handler-level coverage - 1625 tests - and **no proven
engine loop**. All 1625 pass because none of them enters it. Retiring
`service.py` now would swap a path that has traded for a path whose loop has
never completed, which would leave the desk with no proven way to trade at
all. The ported desks are additive and cost nothing by sitting alongside, so
they wait.

What unblocks it is one run of a twenty-line bare engine on another host.
