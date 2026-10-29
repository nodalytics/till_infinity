# Restructuring into services, and the Python/Go boundary

- **Date:** 2026-10-28
- **Decisions:** [ADR 0002](../adr/0002-services-are-self-contained.md),
  [0003](../adr/0003-python-and-go.md),
  [0004](../adr/0004-risk-rules-have-one-owner.md)

## Intent

Make each service self-contained so it can be deployed, replaced or written in
another language on its own, and do it in slices that each leave the suite
green.

The reason to do it **now** rather than later is that the structures service is
being retired. Boundaries are cheapest to draw around a smaller system, and
28,587 lines are on their way out: formalising a contract for a service that is
about to be deleted is work that gets thrown away with it.

## Goals

- Every service in `services/<name>/`, importing no other service.
- `shared/` holds contracts only.
- The bus is the only link, and already is for everything except imports.
- A Go service running in production, chosen so that nothing has to be ported
  to get it there.

## Non-goals

- Seven containers. The layout is a source-tree decision; one process stays the
  default until a service earns its own (ADR 0002).
- Porting statespace. Whether Python folds ticks fast enough is a measurement,
  not an assumption (ADR 0003).
- A new message broker. The bus already speaks Redis Streams with consumer
  groups, and nothing here needs request/reply.

## Anti-goals

Things that would make this a failure even if every file moved:

- **`shared/` becoming a library.** If it holds code rather than contracts,
  every language has to link against Python and the boundary is decorative.
- **A payload that carries risk decisions.** ADR 0004. A second runtime sizing
  a real position is the one failure that costs money rather than time.
- **A boundary with no subscriber check.** `statespace.proposals` published to
  nobody for weeks and the producer's tally said "proposed". Each new boundary
  repeats that unless the contract counts receipt.

## The measured surface

| | |
| --- | ---: |
| `structures/` | 77 files, 28,587 lines |
| external import sites | 54, across 19 modules |
| worst single importer | `trading/service.py`, 11 |
| single-consumer machinery (to `trading`) | 1,894 lines |
| `statespace` imports from `structures` | **none** - the two hits are prose |
| already shimmed to `shared/` | `codec.py` (63 lines), `state.py` (12) |
| strategies that survive structures | 1 of 17 (`statespace-surprise`) |
| the box | 2 cores, 2,676MB to the container |

Two of those matter more than the rest. **Statespace is already clean**, so the
service that now drives the desk needs no untangling. And **two shims already
exist**, so the pattern this spec generalises is one the repository chose for
itself when `trading` was caught importing another service's persistence layer.

## Target layout

```
packages/         installable libraries. Nothing here runs.
  till-platform/  logging, env, Restorable, the codec, the contract reader
services/         things that run, in whatever language suits them
  trading/        the authority: gates, sizing, orders. Owns rollover, cusum,
                  trend, focus, envelope, holds, reach - its own consumers.
  statespace/     folds variance, publishes measurements only
  prices/         feeds, bars, quotes, ticks
  ticks/          Go. Ingest and store.
  agents/ notifications/ news/ journal/
  redis/ | nats/  a broker's config, when one is chosen. Config, no code.
shared/
  contracts/      topic names, message schemas, state formats. No utilities.
docs/adr/         decisions, with their history
research/         Python, permanently. retire/ is where structures goes.
```

`packages/` is an amendment, dated 2026-10-29 and recorded in ADR 0002. The
spec as written had every service carry its own manifest, and a manifest cannot
name the desk as a dependency without making the service a leaf of the thing it
was meant to leave. What every service needs is therefore a library, and a
library is not a service: `services/` is for things that *run*.

## Slices

Each is a PR that leaves both ruff checks and the suite green.

1. **Retire structures.**
   1. Move the 1,894 lines of single-consumer machinery into `trading/`.
   2. Retire the 16 level strategies; drop them from `MAGIC_ORDER`'s live set
      without renumbering it, which is append-only.
   3. Strip the level machinery from `trading/service.py` - the level gates in
      `on_signal`, `gates.consider` and the shadow gates, holds and reaches.
   4. Move what remains of `structures/` to `research/retire/structures/`, and
      its tests with it. `research` is excluded from ruff, which is correct for
      retired code.
   5. Clean the edges: `stack.py` loses the service, and `notifications/filters`,
      `agents/{data,tools}`, `cli.py` and `models/*_train.py` lose their
      imports. `STRUCTURES_ENABLED` leaves `.env.example` and
      `docs/environment.md`.
2. **Create `services/` and move each service in whole**, including the two
   shims' call sites so the shims can be deleted.
3. **Shrink `shared/` to contracts.** Anything left that is not one has an
   owner to go to.
4. **Declare the message schemas.** The payload shapes are already documented
   per topic in `bus.py`; this turns those docstrings into the artefact both
   languages read, and adds the subscriber check the anti-goal asks for.
5. **Flip the bus to Redis in production.** Supported already; one variable.
   Still all Python, now polyglot-capable.
6. **Neutral state serialisation** for whichever service is ported first -
   which for ticks is nearly nothing, by design.
7. **Go tick ingest**, and the CI job that builds it.

## As built

Dated 2026-10-29, after slices 1, 3 and 4 and the first half of slice 2.

| Slice | State | What actually happened |
| --- | --- | --- |
| 1 Retire structures | part | The 16 level strategies and the service are retired, `STRUCTURES_ENABLED=0` is live and the desk trades one strategy. The `structures/` package itself, the level machinery in `trading/service.py` and the CLI group are still in place. |
| 2 Move each service | part | `statespace/` moved first and whole, with its own manifest and env. The rest are still `till_infinity/<name>/`, and `test_service_boundaries.py` records each one's debts as data so the list can only shrink. |
| 3 Shrink `shared/` | done, differently | `shared/` did not shrink to contracts - it became `packages/till-platform`, because the thing needing an owner turned out to need an *installer*. `shared/contracts/` stays where the spec put it. |
| 4 Declare the schemas | done | Six JSON Schemas under `shared/contracts/bus/`, validated in CI against payloads from the real producers rather than hand-written examples. |
| 5 Redis in production | not started | |
| 6 Neutral state | not started | |
| 7 Go tick ingest | part | `services/ticks/` backfills the 14 FX feeds to Parquet, 11 tests, excluded from the uv workspace by name so a missing Python manifest is a deliberate exclusion rather than a break. |

**Slice 4 moved ahead of the rest of slice 2, and that was right.** The schemas
are what makes a service movable: statespace could leave because its output was
already a declared shape rather than whatever its producer happened to emit.
Moving services first and declaring the shapes afterwards would have meant
moving each one twice.

**The ordering claim in the next section held, with one correction.** Slice 1
being subtraction did make everything after it easier. But slice 1 is *also*
the slice that is still unfinished, because the level machinery in
`trading/service.py` is entangled with the gates that stay - and subtraction
whose remainder has to keep working is not cheap just because it removes code.

## Order, and why this one

Slice 1 is first because it is subtraction, and the rest is easier against a
smaller system. Slice 4 is the pivot: before it, the layout is organisation;
after it, another language can be written against the bus. Slice 7 is last
because it is the only one that cannot be done without the ones above it.

## Left to the builder

- Where in `trading/` the moved machinery lands - one module each, or grouped.
- Whether `research/retire/structures/` keeps its package layout or is
  flattened. Keeping it costs nothing and preserves the import paths its own
  docs cite.
- The schema format in slice 4. JSON Schema is the obvious default; the hot
  path may later want something tighter, and nothing in slice 4 forecloses it.
