# till-platform

What every service needs and no service owns: the logger, environment parsing,
`Restorable`, the persistence codec, and the reader for the bus contracts.

**Why a package rather than a `shared/` directory inside the desk.**
[ADR 0002](../../docs/adr/0002-services-are-self-contained.md) says a service
carries its own code and its own dependency manifest. A service cannot do that
while importing `till_infinity.shared`, because then it depends on the whole
desk - and `services/statespace` is the first one that had to stand alone.

**This is not a licence to put utilities here.** The ADR's warning stands: code
with one consumer travels to that consumer, and a Python library every service
links against is the thing `services/` exists to prevent. The test is whether
removing it would leave two services needing the same thing. A volatility
envelope used only by trading fails that test; `Restorable`, which every
persisted dataclass on the desk inherits, passes it.

## What is here, and why each one qualifies

| | |
| --- | --- |
| `logging` | every service logs, and they must log the same shape or the journal cannot read them |
| `env` | every service reads its settings from the environment with the same coercions |
| `state`, `codec` | **the same state file.** `codec` keys on `basename.ClassName`, so two copies of `Restorable` would collide - this cannot be duplicated even in principle |
| `intervals` | what `"5m"` means. A unit of time is a contract |
| `contracts` | the reader for `shared/contracts/bus/*.json`, which a Go service reads directly |
| `frozen`, `strata`, `effects`, `crosscheck`, `replay`, `liveness`, `db` | measurement and persistence machinery with more than one consumer |

The last row is the one to watch. If any of those turns out to have a single
consumer, it belongs with that consumer instead.

## The JSON stays at the root

`shared/contracts/` is at the repository root, not in here, because Go reads
those files and a Go service should not have to know about a Python package
layout. `contracts.py` resolves its way up to them.
