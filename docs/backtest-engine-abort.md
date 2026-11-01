# `BacktestEngine.run()` aborts on this workstation, and it is not our code

**Found 2026-11-01**, while trying to prove the ported desks end to end before
retiring `strategies/service.py`. The retirement is **held** on this: there is
no point swapping a path that has traded for a path whose engine loop has never
run.

## What happens

A bare engine - no strategy, no actor, no indicator, **one bar**, and without
importing `till_infinity` at all - dies with:

```
running bare...
double free or corruption (out)
```

Exit code **134**, which is SIGABRT. It never reaches the line after `run()`.

| | |
|---|---|
| `nautilus_trader` | 1.221.0 |
| Python | 3.11.14 |
| glibc | **2.41** |
| host | `parrot` (this workstation) |

## The bisection, because the first guess was wrong

The crash first appeared while testing `EdgeEntry.place` through
`engine.run()`, and the obvious suspects were ours. Each was cleared in turn:

1. **With our indicators registered** - crash. The suspicion was real: the
   detectors in `till_infinity/indicators/` are `slots=True` dataclasses
   inheriting a Cython `cdef class`, which is exactly the shape that could
   corrupt an allocator.
2. **With `indicators=()`** - crash. Not the indicators.
3. **With no order placed at all** - crash. Not `submit_order_list`, not the
   bracket, not the exec client.
4. **With no strategy added** - crash. Not `Desk`, not the gates.
5. **In a script that does not import `till_infinity`** - crash. Not ours at
   all.
6. **With one bar instead of 120** - crash. Not the volume or the data shape.

The script is `bare.py` in the session scratchpad and is twenty lines: a venue,
an instrument, one bar, one quote, `run()`.

## Why the test suite is green anyway

**All 1625 tests pass, and that is not a contradiction.** Every one of them
either drives handlers directly - `strategy.handle_bar(...)`,
`strategy.on_quote_tick(...)`, `strategy.place(...)` - or builds a config and
asserts on it. None enters the engine's run loop, so none reaches the code that
aborts.

That is worth being precise about rather than reassured by: the handler-level
coverage is real, and the engine loop is genuinely unproven. A green suite here
says the gates, the entries, the exits and the counterfactual behave as
specified when fed; it says nothing about whether a backtest completes.

## The likely cause, stated as a guess

glibc 2.41 is very new, and `nautilus_trader` ships prebuilt Rust and Cython
extensions. An allocator mismatch between a wheel built against an older glibc
and 2.41 at runtime fits the symptom - a double free inside native code, on any
input, with no Python-level traceback. **Not confirmed**, and the confirmation
is cheap: run the same twenty-line script on a box with an older glibc.

## What this blocks, and what it does not

**Blocked.** Anything that needs the loop: `node/backtest.py`'s
`desk_config` -> `BacktestNode(...).run()`, the discovery and backtest rungs of
the pipeline, and any measurement of the ported desks. `node/sizing.py` already
refuses to run a backtest on the *trading* host for a different reason; this is
a second host that cannot run one, for a worse one.

**Not blocked.** The live node builds and its desks register - that path does
not go through `BacktestEngine`. The handler-level suite runs. Development
continues.

## What would settle it

1. Run `bare.py` on another host. If it completes, this is a glibc or wheel
   problem and the fix is a build or a container, not code.
2. If it aborts there too, it is `nautilus_trader` 1.221.0 and the pin needs
   revisiting - `pyproject.toml` has `>=1.221,<1.230`.

Until one of those happens, **`strategies/service.py` and
`strategies/venues/` stay where they are.** They are the path that has traded,
and retiring them in favour of a path whose loop has never completed would
leave the desk with no proven way to trade at all. The ported desks are
additive and cost nothing by sitting alongside.
