# The field-liveness audit

**Status:** design, 2026-09-11. Not yet approved.

## The problem, and it is live right now

Across the last **20,000 production `structures` outcomes**:

| field | zero | nonzero |
| --- | --- | --- |
| `run_vol` | **20,000** | **0** |
| `pivot` | **20,000** | **0** |
| `backcheck` | 17,836 | 2,164 |
| `experience` | 3,043 | 16,957 |

`run_vol` and `pivot` are **identically zero on every row**. They are published
on every level call, journalled on every outcome, and carried into the models
that consume those features. A model weighting a constant learns nothing from
it and spends capacity doing so; a research cut on it finds nothing and cannot
say whether that is because the effect is absent or because the column is dead.

Neither is a new field. Both have been zero for as long as the sample reaches.

## The same failure, one step earlier

On 2026-09-11 a research direction was planned around option open interest, and
a collector was nearly written before anyone checked the field carried data:

| ticker | contracts | volume > 0 | **openInterest > 0** |
| --- | --- | --- | --- |
| SPY front expiry | 366 | 359 | **0** |
| ^SPX front expiry | 462 | 454 | **1** |
| QQQ front expiry | 370 | 357 | **3** |

SPY's front expiry carries 1,587,783 contracts of *volume* and **zero** open
interest. That is a dead field, not a market state. The check cost ten minutes
and saved a collector that would have stored zeros for months.

`prices/options.py` already names this failure mode precisely - *"not a number
nothing reads, but a number read as more than it is"* - and it happened anyway,
because nothing systematically asks.

## What this builds

A check that answers one question about any numeric field: **does it vary?**

Two places it runs, because the field can die in either:

1. **Over the journal.** Every numeric key in `context`, per actor and kind,
   reported with its distinct-value count, its constant value if it has one, and
   how long it has been that way. Run on demand and on a schedule; the output is
   a short list of dead and near-dead fields.
2. **Before a research harness depends on a field.** A one-line assertion a
   harness calls on the columns it is about to cut by, which fails loudly rather
   than returning a flat table.

## Design

`till_infinity/shared/liveness.py`, in the package for the reason the replay
kernel is: `research/` is excluded from ruff and from `testpaths`, so a check
that lives there is a check nothing checks.

```python
def survey(rows: Iterable[Mapping[str, Any]]) -> dict[str, Reading]:
    """Every numeric key, and whether it carries information."""

def assert_alive(rows, *keys: str) -> None:
    """Raise if any named key is constant across `rows`."""
```

`Reading` carries `seen`, `distinct`, `constant` (the value or `None`), and
`share_zero`. Three states worth separating, because they want different
actions:

* **constant** - one distinct value across the sample. Dead.
* **near-constant** - above a threshold share on a single value, default 99%.
  Alive but nearly useless, and the shape a field takes while it is dying.
* **absent** - the key is not present on the rows at all, which is a different
  fault from being present and zero and is currently indistinguishable in every
  cut this project makes.

### Reporting it where someone reads it

A `liveness` line in the periodic `structures` log, in the same place
`origin_tally` and `drift_tally` already report, naming any field that has gone
constant since the last save. Those tallies exist because *a comparison nobody
reads settles nothing*, and this is the same argument: an audit that has to be
run by hand is an audit that runs once.

## Scope

**In:** the survey, the assertion, journal coverage, and the log line.

**Out:** fixing `run_vol` and `pivot`. Finding out *why* they are zero is a
separate investigation - it could be a dead code path, a feature never wired to
its source, or a computation that always returns zero - and each has a different
fix. This spec is about never again needing someone to notice by accident.

## Testing

1. A constant field is reported constant; a varying one is not.
2. An absent key is reported absent, not constant - they are different faults.
3. A field that is 99.5% one value is near-constant at the default threshold and
   alive at a looser one.
4. `assert_alive` raises on a dead key and names it in the message.
5. A field that is constant *within* one actor and varies across actors is alive
   overall and dead per-actor, and the survey says so per-actor - because that
   is the shape `run_vol` would have if only one producer were broken.

## Why this is worth doing before more research

Three of the day's conclusions died to measurement faults rather than to the
market. Two of those - the dead option field and the constant features - are the
same fault: **depending on a column without asking whether it carries anything.**
That question is cheap, mechanical and currently asked by nobody.
