# 0005. The journal is the shared record; a hot path owns its own store

Date: 2026-10-29

## Status

Accepted.

## Context

[ADR 0002](0002-services-are-self-contained.md) says services talk over the
bus. Applying that to `journal` exposed the one place where it is not enough.

`journal` is 895 lines with no third-party dependency, which makes it the
cheapest service to port to another language. But it is not a leaf.
`trading/service.py` imports `decide`, `observe` and `outcome` at module level
and calls `read` at four separate points, and `structures/service.py` and
`trading/report.py` import it too. Those are in-process function calls on the
path that decides whether to place an order.

Moving the journal behind the bus therefore proposes a round trip in the
middle of a decision - and the journal is also the record we do research on,
so a port that changes a rounding or a field quietly corrupts the thing we
reason from.

The choice looked like one between a slow hot path and an unportable service.

## Decision

Neither. The two uses are separated:

- **The journal is the durable shared record.** Everything that is written
  once and read later - entries, outcomes, ledgers, what the desk did and why
  - goes to the journal over the bus. One writer, which is why it is on the
  bus at all.
- **A service that must read on its own hot path owns a local store.**
  Trading keeps its own database for the state it consults inline. It is that
  service's private business, not a shared schema, and nothing else reads it.

So a hot-path read never becomes a network call, and the journal never has to
serve one.

## Consequences

**The journal becomes portable.** With nothing reading it inline, it is a
subscriber that writes - the shape that ports to Go without a latency
argument. Same for `news` and `notifications`, which were already leaves.

**Trading gains a store to get right.** A private store is still state: it
needs bounds, a restore path and the same `Restorable` discipline as anything
else that survives a restart. `restore-drops-deque-maxlen` is the warning -
a capped field came back unbounded from a restore, and the declaration looked
correct while the live heap was wrong.

**Two things now hold the same facts**, and they can disagree. The rule that
keeps that tolerable is which one is authoritative: the journal is, for
anything after the fact. A disagreement is a bug in the local store, never a
reason to trust it over the record.

**This is not a licence for a service to keep a database because it is
convenient.** The test is whether a read is on a path that must not wait. A
report, a backfill or a nightly recompute is not, and belongs on the journal
like everything else.
