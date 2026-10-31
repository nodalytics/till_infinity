# baseline

What the desk was running before Nautilus, kept so the Nautilus version can be
checked against it rather than compared to a memory.

Copied 2026-10-31 from `services/statespace`, `services/ticks`,
`packages/till-platform` and `packages/till-channels` at their state on main.
Nothing here is imported by anything. `research/` is excluded from ruff and
from `testpaths`, so these copies neither lint nor run - which is correct for a
reference, and is also why they will drift. The commit that added them is the
version that matters.

## Why a baseline and not a retirement

`research/retire/` holds code whose thesis lost - structures, agents, the
offline models. This is different: `statespace` is the one component with
measured edge, and it is being *ported*, not dropped. The question a port has
to answer is whether the numbers survive it, and that question needs the old
implementation present to ask.

## What the port has to reproduce, measured

`statespace` driven as a Nautilus `Actor` was compared against
`Engine.observe_bar` on identical bars out of `.data/prices/prices.db`, all
eleven fields of every `Readout`, from an empty state directory on both sides:

| feed | interval | price precision | result |
| --- | --- | --- | --- |
| eurusd | 1m, 5m | 9 | identical, bit for bit |
| spx500 | 15m | 9 | identical (2,941 readouts) |
| gold | 5m | 9 | worst relative 9.4e-12 - float noise |
| btc | 15m | 2 | worst relative 5.7e-14 |
| btc | 1m | 2 | worst relative 3.2e-05 |

The Actor is about fifteen lines: `Bar` -> payload -> the same `observe_bar`.
Nothing in this package needed changing, which is the finding.

**Two conversions decide whether those numbers hold.** `ts_event` on a
Nautilus bar is the bar's *close* and these payloads carry its *open*; get
that wrong and `observe_bar`'s monotonicity guard (`when <= seen.at`) does not
shift the series, it silences it. And `Price`/`Quantity` are fixed-precision,
so the precision chosen per instrument truncates the input: btc at its
tradable 2 decimal places moves 1m dispersion by 3e-5 while 15m stays at
noise, because truncation matters in proportion to how small the bar's range
is against its tick size.

## What the comparison also found, which is not about Nautilus

**About 1,200 malformed daily bars.** Close outside `[low, high]`, 0.3-0.8% of
daily bars per FX feed, one bar with `high < low`, all of them in `1d` and
`1w` and none at `1m` or `5m`. Nautilus refuses such a bar; `observe_bar`
checks only `close > 0`, and the estimators return a number anyway - Garman-
Klass and Rogers-Satchell disagree threefold on the same bad bar.

Production folds `1m` and `5m`, so it is untouched. **Research is not.**
`drive-q-from-the-range` is a range-versus-close estimator ratio, which is
exactly the quantity that breaks when the close sits outside the range, and it
is reported on FX dailies. Worth re-running with those bars excluded before
the result is relied on again.

**Neither package installed on its own.** `till-platform` imports `rich` at
module level and `msgpack` inside `codec`; `statespace` imports `msgpack`
inside `store`. All three were undeclared, and the earlier claim that
statespace installs standalone came from `uv run --project`, which uses the
workspace environment. numpy is correctly an extra: every numpy import in the
package is inside a function, and 2,000 bars folded with it absent.
