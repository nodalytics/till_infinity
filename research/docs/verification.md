# Verification: what the risk layer guarantees, rather than what a backtest saw

Tests: [`tests/test_invariants.py`](../../tests/test_invariants.py). Run 2026-09-30.

## The question

A backtest says a rule made money on the path history happened to take. A risk layer makes
promises about **every** path: never more than N positions, never more than the budget at risk, no
entries in the rollover, a halt that lasts the day. Are those promises true of the code, on all
inputs, or only on the inputs someone thought to write a test for?

This borrows three tools from formal methods and software verification:

- **Property-based testing** (`hypothesis`): state the invariant, let the tool search for a
  counterexample, and have it shrink any it finds to the smallest failing case.
- **Stateful testing** (`hypothesis.stateful`): a model of the account is driven through random
  sequences of signals, fills, closes, clock jumps and day rolls. The code and an independent model
  must agree after every step.
- **Exhaustive model checking** where the state space is small enough to enumerate. The clock-based
  vetoes are checked at every minute of three full weeks, including both 2026 US daylight-saving
  changes, against a New York clock written out by hand rather than taken from zoneinfo.

## The invariants, and where each is stated

| # | Invariant | Source | How it is checked |
|---|---|---|---|
| 1 | Never more than `max_positions` open | `risk.py` `Guard.allows` (max_positions) | state machine |
| 2 | Never more than `max_per_symbol` on one symbol | `Guard.allows` (already_open) | state machine |
| 3 | After a halting loss, nothing opens until the next UTC day, then the halt lifts | `Guard.record`, `Guard.roll`, `allows` (halted) | state machine; exhaustive over 3 days |
| 4 | The guard's day, realised P&L and halt agree with an independent model | `Guard.roll`, `record` | state machine |
| 5 | No entry within `loss_cooldown` of a loss on that feed, and exactly then | `allows` (cooldown) | state machine; exhaustive, second by second at the edge |
| 6 | No entry in a UTC `quiet_hours` hour | `allows` (quiet_hour) | state machine |
| 7 | FX entries refused at exactly 16:00-18:59 New York and the Sunday open's first hour; nothing else refused by it | `risk.fx_window` | exhaustive, every minute, both DST weeks |
| 8 | The rollover mask covers exactly 16:55-17:10 New York, FX only | `structures/rollover.masked` | exhaustive, every minute, both DST weeks |
| 9 | A refusal names exactly one gate and counts once; an allowed trade counts none | `Guard._no` | state machine |
| 10 | A sized trade never risks more than `equity x risk_fraction` (or `max_risk_money`), is on the lot grid, and is within the broker's min/max | `sizing.lots`, `SymbolSpec.round_volume` | property |
| 11 | A wider stop never buys more lots; a bigger budget never buys fewer | `sizing.lots` | property |
| 12 | Rounding a volume is downward, on the grid, idempotent | `SymbolSpec.round_volume` | property |
| 13 | The combined size reduction is always in [FLOOR, 1] and monotone in each reduction; an interval weight never enlarges a trade | `scaling.combined`, `scaling.by_interval` | property |
| 14 | A managed stop only ever tightens, even after rounding; nothing moves a stop on a trade that has not gone our way | `manage.advance`, `manage.better` | property |
| 15 | The z-score veto can only remove a trade, and only for a feed that has earned it | `strategies/scalper.zma_gate`, `Settings.zma_earned` | property |
| 16 | Both cycle permissions refuse unless the record is earned | `strategies/turning.py`, `stretching.py` | property |
| 17 | A record at or under a coin never earns; more right calls never un-earn one | `Settings.zma_earned` | property |
| 18 | Swap nights never fall as a hold lengthens; a hold ending before the next 17:00 New York pays none; swap cost is never negative | `trading/swap.py` | property |
| 19 | The shadow confirmation gates never change a decision | `trading/shadow.py` | already in `tests/test_shadow.py` (`test_the_shadow_changes_nothing_trading_decides`) |

## Results

**Every invariant holds** on the CI profile (150 examples per property, 60 state-machine runs of 40
steps) and on a deep run (3,000 examples per property, 400 state-machine runs), with no
counterexample in the code.

**One counterexample was found, and it was in the test, not the code.** The first statement of
invariant 18 said a hold shorter than "the minutes to the next 17:00" pays no swap, computed on
24-hour days. Hypothesis shrank a failure to Saturday 2026-03-07 17:00 New York, held 23h58m. The
next day is the 23-hour spring-forward day, so that hold does cross Sunday's rollover, and
`swap.nights` correctly charges it. It gets this right because it works through zoneinfo. The
invariant was restated in real elapsed time, and the case is kept as a regression test. It is the
kind of case that example-based tests never contain.

## Guarantees the code does not make, and decisions for the desk

These are not bugs against a documented intent, so nothing was changed. Each is a place where the
guarantee rests on something other than the risk layer.

1. **Stop side is guaranteed by construction, not by the guard.** Neither `Guard.allows` nor
   `service.take` checks that a stop sits on the losing side of the entry. `sizing.lots` uses
   `abs(entry - stop)`, so a BUY with its stop above the entry would size normally. Today every
   stop is built by `sizing.stop_for`, which always places it correctly, and the broker would
   reject a wrong-side stop. A one-line gate (`stop_side`) would make it a guarantee of the risk
   layer rather than of each strategy. **Decision: add it or not.**
2. **The halt's day is the UTC calendar day, and a close is booked to the day it closes.** If the
   first event of a UTC day is a losing close recorded before the service's next roll, the day's
   opening equity is taken *after* that loss (9,750 rather than 10,000 on a 250 loss), so the limit
   tightens slightly (292.5 rather than 300) and the loss counts against the new day. This is
   conservative, never looser. **Decision: keep, or roll on the close's time before booking it.**
3. **The daily halt depends on the service rolling the day.** `allows` does not roll the calendar
   itself. The service calls `roll` at start-up and every cycle (`service.py` lines ~770 and
   ~2823), so the halt lifts on the first cycle of the new UTC day. A process that stopped cycling
   would keep yesterday's halt in force, which is the safe direction.
4. **Sizing in the agreed and parallel paths ignores the interval weight and the other reductions
   except the spike switch.** This is by design ("re-sized flat, as before",
   `service.py` `_agree` / `_take_all`). Invariant 10 holds on every path, because the budget is
   still `equity x risk_fraction x spike_scale`, but the interval brake shipped in PR #22 does not
   apply there. **Decision: whether it should.**
5. **Not covered here:**
   - the currency-exposure gate, which needs the open book's risk per ticket;
   - the news, drift, wide and dislocation gates, which need a `Context`;
   - broker-side behaviour (partial fills, rejects).

   These are the next state-machine extensions.

## For the test suite

`tests/test_invariants.py` adds 21 tests, about 25 seconds in CI including collection.
`HYPOTHESIS_PROFILE=deep` and `HYPOTHESIS_STATEFUL_EXAMPLES=400` give the long run used above, about
five minutes. `hypothesis` joins the dev dependency group. The exhaustive clock checks are
deterministic and run on every CI build: 3 weeks × 1,440 minutes, both DST transitions.
