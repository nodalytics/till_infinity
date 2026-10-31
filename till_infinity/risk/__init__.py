"""Risk, at the level it applies: the account, not one strategy.

**Top level rather than inside `strategies/`, and that is the substantive
choice.** A drawdown guard and an exposure budget are about the account, so a
second strategy package could not share them from inside the first. Nautilus's
own `RiskEngine` is node-level for the same reason.

The split with Nautilus is the point of this package:

| what | where it lives | why |
| --- | --- | --- |
| order rate, max notional, HALTED/REDUCING | `RiskEngineConfig` | the engine
  applies them to every order already |
| position size from a stop distance | `sizing` | an *input* to an order, not a limit on one |
| exposure budget across correlated feeds | `exposure` | the engine caps per order, not per book |
| equity-peak drawdown | `guard` | the engine has no notion of a peak |
| watching equity and halting | `monitor` | the one risk question that is a bus participant |

**`engine.limits()` is what makes the first row real.** A cap we apply
ourselves is a cap a new code path can miss; one in `RiskEngineConfig` is
applied where every order passes. So the policy here is *compiled into* the
engine's configuration rather than enforced beside it.
"""
# **Nothing is imported eagerly here, and that is not a style choice.**
# `exposure` reads `strategies.models` for `Intent`, `Position` and `Side`,
# and `strategies` reaches back into risk - so an eager re-export makes a
# cycle that surfaces only as "partially initialized module". Callers import
# the submodule they want:
#
#     from till_infinity.risk import exposure, scaling
#     from till_infinity.risk import exposure, scaling
#
# The shared data types are the real coupling and they are transitional: under
# Nautilus, `Position` and `Side` are the engine's own, at which point this
# cycle has nothing left to cut.

__all__: list[str] = []
