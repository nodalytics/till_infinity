"""Risk, at the level it applies: the account, not one strategy.

**Top level rather than inside `strategies/`, and that is the substantive
choice.** An exposure budget and a position size are about the account, so a
second strategy package could not share them from inside the first. Nautilus's
own `RiskEngine` is node-level for the same reason.

The split with Nautilus is the point of this package, and
`docs/specs/2026-10-31-service-becomes-nautilus-strategies.md` re-checked it on
1.231.0: `RiskEngine`'s entire public surface is `set_max_notional_per_order`,
`set_trading_state` and `reset`, and every actual check is private with no
registration hook. **Risk is not pluggable**, so this package decides pre-trade
and the engine is the last-line notional and rate cap.

| what | where it lives | why |
| --- | --- | --- |
| order rate, max notional, HALTED/REDUCING | `LiveRiskEngineConfig` | the
  engine applies them to every order already |
| lots from a risk budget and a stop distance | `sizing` | an *input* to an
  order, not a limit on one |
| the eight reasons to size below that | `scaling` | each can only reduce, and
  they compose by multiplication |
| which instruments this equity cannot trade | `affordable` | answerable before
  a signal exists, so it is a catalogue rather than a refusal |
| exposure budget across correlated feeds | `exposure` | the engine caps per
  order, not per book |
| may this account, right now, take another trade | `guard` | the spec's row
  for this package, word for word |
| the limits as named, coherent bundles | `plans` | ten numbers that have to
  agree are not ten settings |
| the twenty-two numbers all of that reads | `envelope` | so none of it has to
  see the desk's configuration object |

**`node/promotion.py`'s `Allocation.limits()` is what makes the first row
real.** A cap we apply ourselves is a cap a new code path can miss; one in
`LiveRiskEngineConfig` is applied where every order passes. So that policy is
*compiled into* the engine's configuration rather than enforced beside it.

## What the 2026-11-01 move brought here, and what `envelope.py` unblocked

`sizing` and `affordable` came first. Both answer account questions rather
than signal questions, and - the part that actually decided it - both import
nothing above `domain`, so they arrived without pointing back up at the layer
they left.

`guard` and `plans` came second, and could not have without `envelope.py`.
The record of why is worth keeping, because the obstruction was real: this
file was placed here once and sent back, and the next attempt was refused
rather than forced, which was the right call both times.

* **`guard`** is this package's row verbatim, and it read nineteen fields of
  the strategies `Settings` object and five methods of the context that
  consumes the bus - the news blackout, the release inside the hold, drift, a
  wide peer quote and a dislocation. `tests/test_service_boundaries.py`
  records it being placed here once and sent back, with that import as the
  symptom.
* **`plans`** names the limits as coherent bundles, which is this package's
  subject, and then *wrote them into* `Settings`: `Plan.apply` set the twelve
  fields of `CONTROLS` plus `risk_plan`, and `_fields_are_covered` called
  `dataclasses.fields` on the class. A writer into a configuration object has
  to be able to see one.

Both blockers had one shape - the limit is an account fact, but the *number*
lived in 1,583 lines of `TRADING_*` knobs about what to trade and on which
terminal - and each half needed a different answer:

* **The read** is `envelope.Envelope`: a frozen dataclass carrying exactly the
  twenty-two fields this package reads, built by `Settings.envelope()`
  upstairs and handed in as an argument. It declares **no defaults**, so the
  numbers have one home and a field added here fails at the projection until
  the projection names it.
* **The context** is `guard.Conditions`, a structural protocol naming the five
  methods. The implementation stays upstairs and satisfies it without either
  file importing the other, exactly as `scaling.by_regime` takes a regime as a
  plain `float`.
* **The write** split in two. `Plan.values` returns what the plan would set
  and knows nothing about where it lands; `strategies.config.apply_plan` does
  the `setattr`, because that is the layer that owns the object. The mutation
  survives for its original reason - `Settings` is what the desk already holds
  a reference to - and only the direction of the dependency changed.

**`sessions` and `spreads` are still not risk** and did not come. Tradable
hours and what a round trip costs are *inputs* to a decision - read by the
strategies' context and by `guard`'s spread gates - and neither can refuse
anything on its own.

**One thing the move exposed rather than fixed.** `apply_plan` has no caller:
the CLI that called it is retired and the node has not taken it over. So
`TRADING_RISK_PLAN` is read into `Settings.risk_plan`, printed at start-up and
never applied, and the desk trades the `Settings` defaults - which are
`standard`'s twelve numbers exactly, which is why nobody noticed. Naming
`conservative` today changes nothing.

## A regime is consumed here, never produced here

Checked rather than assumed, on 2026-11-01: this package imports neither
`statespace` nor `indicators`, and `scaling.by_regime` takes the ratio as a
plain `float` that its caller supplies. That is the ruling - a regime *model*
is an inference, it needs the indicator panel and a null harness to be worth
anything, and it stays in `statespace/`. What belongs here is the policy
conditioned on it. A fitted model reached from this package would make the one
component that has to stay auditable the one with the most moving parts.
`test_risk_imports_no_layer_above_it` is what keeps that true.

`strategies/profile.py` is where the handoff happens: it reads
`features["forecast_ratio"]` off the published proposal and passes the number
down. Two things about that path are worth knowing before anyone relies on it.
`regime_band` defaults to 0.0 and `by_regime` returns 1.0 on a non-positive
width, so the lever is **off as shipped**; and its only call site sits in
`Profile.risk_scale`, which is gated on `SIZING_MULTIPLIERS` and returns 1.0
without it. The lazy import that used to be written one dot too deep - three
dots, `ImportError: attempted relative import beyond top-level package`, so
the whole eight-multiplier path raised - **is fixed**, and the switch is still
off. Corrected here on 2026-11-01: this paragraph still said the path was
"doubly dead", which was true of the import and has not been since.

**`by_regime` cannot both have mean one and only reduce.** Measured over
200,000 lognormal(0, 0.5) ratios: the mean multiplier is 1.0000 at the shipped
band of 0.0, then 0.7713, 0.9249 and 0.9958 at bands of 0.25, 0.5 and 1.0, and
the maximum is exactly 1.000 at every band. So the mean is one only while the
gate never fires, because the function is bounded above by one - which is this
module's deliberate invariant, that a sizing model able to enlarge a position
can turn a measurement error into a margin call. A mean-one multiplier has to
be able to exceed one. The two rules contradict each other and nothing here
asserts either, because choosing between them is a decision about what the
desk wants rather than a property of the code.

## What this package may still not have

The envelope is a subset of the configuration, not a second configuration.
Anything that would need the *rest* of `Settings` - which symbols resolve on
which terminal, which decisions are registered, where state is written - does
not become importable because this file exists, and the honest answer for such
a module is that it belongs upstairs. `test_risk_imports_no_layer_above_it` is
what makes the next attempt argue the case rather than add an import.
"""
# **Nothing is imported eagerly here, and that is not a style choice.**
#
# It used to be about a cycle: `exposure` read `strategies.models` for `Intent`,
# `Position` and `Side`, so an eager re-export surfaced as "partially
# initialized module". **That cycle is gone** - those types moved to `domain/`,
# and this package now imports nothing above itself, which is the property
# `LAYERS` asserts in `tests/test_service_boundaries.py`.
#
# What remains is narrower and still worth keeping. Flattening four modules into
# this namespace would give every function two import paths, and the keys
# `utils/codec.py` persists state under are `basename.ClassName` - so one path
# per class is how a reader can tell which `Sizing` a state file means. Callers
# import the submodule they want:
#
#     from till_infinity.risk import affordable, envelope, exposure, guard, plans

__all__: list[str] = []
