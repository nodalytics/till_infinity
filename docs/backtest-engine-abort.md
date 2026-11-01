# `BacktestEngine.run()` aborted, and it was `nautilus_trader` 1.221.0

**Found 2026-11-01**, while trying to prove the ported desks end to end before
retiring `strategies/service.py`; **settled the same day.** Kept because the
first explanation was wrong in an instructive way, and because the thing that
hid it is a trap this suite can fall into again.

## What happened

A bare engine - no strategy, no actor, no indicator, **one bar**, and without
importing `till_infinity` at all - died with:

```
running bare...
double free or corruption (out)
```

Exit code **134**, which is SIGABRT. It never reached the line after `run()`.

## The fix

| | was | is |
|---|---|---|
| `nautilus_trader` | 1.221.0 | **1.231.0** |
| Python | 3.11.14 | **3.13.5** |

The two move together and that is the whole reason the bug survived: every
`nautilus_trader` line that fixes the abort requires **Python >= 3.12**, and
1.221 was the last release with a cp311 wheel. A desk pinned to 3.11 could not
take the fix without also moving the interpreter, so `pyproject.toml` now reads
`requires-python = ">=3.12"` and `nautilus_trader>=1.231,<1.240`.

## The bisection, because the first two guesses were wrong

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
6. **With one bar instead of 120** - crash. Not the volume.

### Wrong guess one: glibc

This workstation runs glibc **2.41**, which is very new, and
`nautilus_trader` ships prebuilt Rust and Cython extensions. An allocator
mismatch between a wheel built against an older glibc and 2.41 at runtime fits
the symptom exactly - a double free inside native code, on any input, with no
Python-level traceback. It was written up here as the likely cause, labelled a
guess.

**Refuted on a second host.** The same twenty-line script on a box with glibc
**2.39** - older, not newer - aborted identically. Whatever the cause was, it
was not this machine's libc.

### Wrong guess two: the data

Worth recording because it was the right question to ask and the answer was
still no. Each of these aborts:

| variant | result |
|---|---|
| bars only | abort |
| quotes only | abort |
| `BID` prices | abort |
| `LAST` prices | abort |
| every timestamp identical | abort |
| timestamps offset | abort |
| **no data at all** | **clean** |

An empty run completing is not evidence the data was at fault; it is evidence
that the loop aborts as soon as it has anything to iterate. A crash that needs
*some* input and does not care *which* is a crash in the iteration, not in the
input.

## Why the test suite was green, which is the part worth keeping

**All 1625 tests passed throughout, and that was not a contradiction.** Every
one of them either drives handlers directly - `strategy.handle_bar(...)`,
`strategy.on_quote_tick(...)`, `strategy.place(...)` - or builds a config and
asserts on it. None entered the engine's run loop, so none reached the code
that aborted.

The handler-level coverage was real and the engine loop was genuinely unproven,
and nothing in the suite's output distinguished those two states. That is the
standing lesson here: **a green suite says the gates, the entries, the exits
and the counterfactual behave as specified when fed. It says nothing about
whether a backtest completes.** One run of the real loop is a different test
from any number of handler calls, and the retirement of `service.py` was held
on it for exactly that reason.

## What it blocked while it lasted

`node/backtest.py`'s `desk_config` -> `BacktestNode(...).run()`, the discovery
and backtest rungs of the pipeline, any measurement of the ported desks, and
therefore the retirement of `strategies/service.py` and `strategies/venues/` -
there was no point swapping a path that had traded for a path whose loop had
never completed. The live node was never blocked; it does not go through
`BacktestEngine`.

All of that is unblocked. The retirement landed on 2026-11-01; see
[`research/retire/strategies/RETIRED.md`](../research/retire/strategies/RETIRED.md).
