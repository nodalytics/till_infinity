# What is built and not called (2026-11-19)

**Audited 2026-11-19** with a token pass over `till_infinity/`: every top-level
function and class whose name appears nowhere in the package outside its own
file. Framework callbacks (`on_*`), entry points (`main`, `build`, `run`,
`settings`), private names and names under four characters are excluded, so
these are things written to be called by us.

**196 of them. 125 are referenced by the test suite and by nothing else; 71 are
referenced nowhere at all.**

The audit script is `.secrets/audit/unwired.py` - gitignored only because it
writes there, and it is twenty lines of `ast` and a `Counter`.

## Why this is worth a document

Two faults found the same morning are the same shape, and neither is a bug a
test can catch:

* **`node/statistics.py`** wraps nine of our metrics as Nautilus
  `PortfolioStatistic` plug-ins and registers them inside `register()`.
  `register()` was called by the test suite and **by nothing else**, so
  `SR_period`, `PSR`, `MinTRL`, `Expectancy`, `ProfitFactor`, `WinRate`,
  `Payoff` and `P_WinRate` reported on **no run, live or backtest**, for as long
  as the module has existed. The module's own docstring said "called by the
  backtest and live nodes". Fixed: `live.build()` calls it.
* **`news-adapters-have-no-consumers`** is the same finding from 2026-11-16,
  already in memory: `fred`, `calendar`, `cot` and `imf` are all built and
  unread.

A tested-but-unwired function is the most expensive kind of code here, because
**every signal says it works**. It has tests, the tests pass, it is documented,
`ruff` is clean - and it runs on nothing. `venue-faults-hide-below-the-strategy`
is the live-trading version of the same sentence: a rule that never fires and a
route that never works read identically.

## Referenced nowhere at all

Grouped by what the absence probably means. **Nothing below is deleted on this
evidence** - a name with no caller may be a deliberate shelf, and this document
exists to make the choice explicit rather than to force it.

### Reporting that no report reaches

| where | names |
|---|---|
| `node/statistics.py` | `PerPeriodSharpe`, `ProbabilisticSharpe`, `MinimumTrackRecord`, `Expectancy`-adjacent `Payoff`, `ProfitFactor`, `WinRate`, `ProbabilisticWinRate` |
| `node/breakdown.py` | `Breakdown`, `sharpe_by_cell` |
| `node/multiple.py` | `Survivors`, `p_from_sharpe` |
| `node/selection.py` | `Haircut` |
| `node/stability.py` | `WalkForward`, `WalkBack` |
| `node/windows.py` | `required_sharpe` |

The `statistics.py` classes are reached by `register()` inside their own file,
which is why they show here; the rest are not reached at all. **`breakdown.py`
is the one to look at first**: its own docstring calls the hourly breakdown
"one of the two gates worth most", and nothing calls it.

### Nulls and controls that no study calls

`node/surrogates.py`: `ewma_t`, `geometric_null`, `topological_null`.
`statespace/searching.py`: `block_shuffled_candles`, `rotated_candles`.
`statespace/nulls.py`: `garch_persistence`.

Six null-generators with no consumer, in a repository whose method is
null-first. Worth checking against the research harnesses, which build their
own shuffles - `research/ideas/` has at least four separate block-shuffle
implementations, and these may be the better ones going unused.

### Indicators and state nobody reads

`indicators/levels.py`: `Estimator`, `as_of`, `origins_of`.
`indicators/candles.py`: `rejection_wick`. `indicators/bars.py`: `tick_price`.
`indicators/momentum.py`: `adaptive_threshold`.
`statespace/`: `Oscillator`, `Spectrum`, `Geometry`, `Exogenous`, `Traits`,
`pivot_levels`, `wicking`, `from_pivots`, `classify_feed`, `steps_for`,
`mean_diagonal`, `bar_reader`.
`strategies/`: `BandProfile`, `Untaken`, `as_domain`, `broker_slug`,
`register_broker_instruments`.

### Risk and sizing

`risk/exposure.py`: `feeds_for`. `risk/sizing.py`: `target_for`.
`node/sizing.py`: `memory_bytes`. `node/partition.py`: `LiveRegister`,
`Overlap`, `Slice`, `clears_cost`, `differentiate`. `node/ladder.py`:
`LadderConfig`. `node/closed.py`: `Established`.
`adapters/mt5/config.py`: `MT5BridgeConfig`. `adapters/news/store.py`:
`MultiStore`. `node/backtest.py`: `WrongHostError`.

`node/partition.py` has five unreferenced names of its own, which makes it the
module most likely to be wholly unused.

## The 125 tested but unwired

Too many to list usefully; the audit prints them. By module, the heaviest are
`statespace/` (the filters `Seasonal`, `Switching`, `Fractional` at 19, 18 and
13 test references each), `node/` (`gate_from`, `swap_charged`, `by_clock`,
`haircut_sharpe`, `required_dsr`, `hansen_spa`, `walk_forward`,
`day_block_interval`, `benjamini_hochberg`) and `indicators/`.

**That list is not a to-do.** Some of it is a shelf on purpose - `CLAUDE.md`
keeps an "alive and unproven" section for exactly that, and six formation kinds
sit there behind guards. What the audit gives is the distinction between *on a
shelf* and *believed to be running*, which is the distinction the statistics
module lost.

## How to keep it from recurring

The one cheap guard that works is the one now in `tests/test_diagnostics.py`:
**assert the call site, not the function.** A test that exercises
`statistics.register` proves the function works; a test that asserts
`live.build()` calls it proves the figure reaches a report. The second is the
claim that matters and it is the one nothing was making.
