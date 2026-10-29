# 0002. Services are self-contained, and the bus is the only link between them

- **Status:** Accepted (2026-10-28)
- **Date:** 2026-10-28

## Context

Today the desk is one Python package and one process. Services are
subdirectories - `prices`, `structures`, `statespace`, `trading`, `agents`,
`notifications`, `news` - and they talk two ways:

1. **Over the bus**, which is already a real abstraction. `bus.py` is backed by
   `channels.py`: in-memory by default, **Redis Streams when `TILL_REDIS_URL`
   is set**, with consumer groups. Topics are named and their payload shapes
   are documented per topic.
2. **By importing each other**, which is the problem. `trading/service.py`
   alone holds **11** imports from `structures`, and there are **54** such
   import sites across **19** modules outside it.

The second path is what makes a service un-relocatable and un-portable. A
service that reaches into another service's package for its change detector,
its volatility envelope or its persistence layer cannot be moved, cannot be
deployed on its own, and certainly cannot be written in another language.

There is precedent for the fix inside the repository already.
`structures/codec.py` is a 63-line shim whose own docstring says the machinery
moved to `shared/codec.py` "when `trading` turned out to be importing it from
here - a service reaching into another service for its persistence layer, which
is the shape the shared folder exists to end." `structures/state.py` is a
12-line shim for the same reason. This ADR is that move, finished and made a
rule.

## Decision

- **Every service lives in `services/<name>/` and is self-contained.** It
  carries its own code, its own dependency manifest and its own container
  build. Nothing outside it imports from inside it.
- **`services/` holds both languages.** A Go service and a Python service are
  peers there - `services/ticks/` with a `go.mod` beside the Python ones - and
  nothing about the directory says which language is inside. That is the point:
  a service's language is its own business, visible in its manifest rather than
  in where it lives.
- **A message broker gets a directory too, holding configuration and no code.**
  If this moves to Redis or NATS, its config lives in `services/redis/` or
  `services/nats/` with a README saying what it is for, beside the services
  that use it rather than in a deployment folder away from them.
- **The bus is the only link between services.** A service publishes and
  subscribes; it does not import another service.
- **`shared/` holds contracts, not utilities.** Topic names, message schemas
  and state formats - things that must be identical on both sides of a
  boundary. It does not hold code that happens to be useful twice.
- **Infrastructure with many consumers is a package, in `packages/`.**
  Amended 2026-10-29. The rule above was written against a drawer of
  utilities and it still is: code with one consumer travels to that consumer.
  But a service cannot carry its own dependency manifest while importing the
  desk, so what *every* service needs has to be installable on its own -
  `packages/till-platform/` holds the logger, environment parsing,
  `Restorable`, the persistence codec and the contract reader.

  The test is whether removing it would leave two services wanting the same
  thing. A volatility envelope used only by trading fails it. `Restorable`
  passes absolutely: `codec` keys persisted state on `basename.ClassName`, so
  two copies would collide - it cannot be duplicated even in principle.

  Libraries live in `packages/` rather than `services/` because `services/`
  is for things that *run*, and a transport nothing starts is not one.
- **Code with one consumer travels to that consumer.** The 1,894 lines of
  `rollover`, `cusum`, `trend`, `focus`, `envelope`, `holds` and `reach` are
  imported by exactly one service, `trading`. They looked shared only because
  they lived in another service's folder. They go to `services/trading/`.
- **One process remains the default.** The layout is a source-tree decision,
  not a deployment decision. tis has **2 cores** and the container is given
  **2,676MB**; splitting one Python process into seven containers costs a
  runtime's memory each and turns a function call into a network hop. A service
  gets its own process when it has a reason - measured CPU, or a different
  language - and not before.

## What this looked like in practice

`services/statespace/` was the first Python service to leave, on 2026-10-29. It
installs and imports with no reference to the desk -
`uv run --project services/statespace` proves it - and the desk depends on it as
a workspace member so `stack.py` still runs it in one process. Separable
without being separated, which is the whole point of the last bullet above.

Its manifest names exactly one dependency, `till-platform`, for 21,000 lines
across 58 modules with no third-party runtime requirement at all.

**Two things cost more than expected, and both are worth knowing before the
next service moves.**

A `__file__`-relative path is a hidden dependency on a module's *position*.
`frozen.py` resolved the shipped models as `Path(__file__).parent.parent /
"models"`, which was the desk's own directory while it lived inside the desk
and a non-existent one afterwards - and an absent directory read as "no model
found" rather than as an error, so seven tests failed saying nothing about a
path. Whoever ships files now declares where they are.

A guard goes quiet when its subject moves. `test_service_boundaries.py` kept
passing after statespace left, because the scan looked in `till_infinity/`,
found no directory and returned an empty set - so the test that says statespace
owes nothing passed by asking nothing. Two tests in `test_statespace.py` had
been vacuous for longer, globbing a path that stopped existing when the package
left `structures/`. Services are now named in a registry the tests assert
against, rather than discovered by a scan that cannot tell absence from
innocence.

## Consequences

- Each service can be moved, deployed and written independently, which is what
  0003 needs.
- `shared/` shrinks. Anything in it that is not a contract has an owner to go
  to.
- The in-process bus and the Redis bus must stay behaviourally identical,
  because the layout promises a service does not care which it is on. The
  transport already switches on one environment variable and that is the whole
  point of `channels.py`.
- **A network bus multiplies a failure this desk has already had.**
  `statespace.proposals` was published for weeks with nobody subscribed, and
  what hid it was that the producer's tally counted what it *sent*. Every
  boundary made real is another place that can happen, so a subscriber count
  belongs in the contract rather than in a warning line.
