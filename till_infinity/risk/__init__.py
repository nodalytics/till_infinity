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

**`node/promotion.py`'s `Allocation.limits()` is what makes the first row
real.** A cap we apply ourselves is a cap a new code path can miss; one in
`LiveRiskEngineConfig` is applied where every order passes. So that policy is
*compiled into* the engine's configuration rather than enforced beside it.

## What the 2026-11-01 move brought here, and what it could not

`sizing` and `affordable` came from `strategies/`. Both answer account
questions rather than signal questions, and - the part that actually decided
it - both import nothing above `domain`, so they arrive without pointing back
up at the layer they left.

Four candidates stayed, in three groups, each for a reason worth writing down
rather than re-litigating:

* **`guard`** is the hard case, because "may this account, right now, take
  another trade" is this package's row verbatim. It needs nineteen fields of
  `strategies.config.Settings` and five methods of
  `strategies.context.Context` - the news blackout, the release inside the
  hold, drift, a wide peer quote and a dislocation - and this package
  importing that one is a cycle and a failing
  `test_a_layer_only_imports_what_is_below_it`. **This is the second attempt:**
  `tests/test_service_boundaries.py` already records `guard.py` being placed
  here once and sent back, with the same import as the symptom.
* **`plans`** names the limits as coherent bundles, which is this package's
  subject, and then *writes them into* `Settings` - `Plan.apply` sets the
  twelve fields of `CONTROLS` on it plus `risk_plan`, and
  `_fields_are_covered` calls `dataclasses.fields` on it.
  A writer into the strategies configuration object has to be able to see one.
* **`sessions`** and **`spreads`** are not risk at all. Tradable hours and what
  a round trip costs are *inputs* to a decision - read by `strategies.context`
  and by `guard`'s spread gates - and neither can refuse anything on its own.

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
`Profile.risk_scale`, whose lazy import of this package is written one dot too
deep and raises `ImportError` - so the path is doubly dead today.

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

Both blockers have the same shape: the limit is an account fact, but the
*number* lives in `Settings`, which is 1,583 lines of `TRADING_*` knobs about
what to trade and on which terminal. Until either a risk-shaped subset of that
configuration exists, or the gates take their values as arguments, `guard` and
`plans` cannot move without dragging the whole desk's configuration behind
them.
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
#     from till_infinity.risk import affordable, exposure, scaling, sizing

__all__: list[str] = []
