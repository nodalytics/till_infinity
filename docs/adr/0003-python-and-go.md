# 0003. Python and Go, with Rust deferred

- **Status:** Accepted (product owner, 2026-10-28)
- **Date:** 2026-10-28
- **Depends on:** 0002 (services are self-contained)

## Context

Two pressures point at a second language.

**The hot path is about to get 100x more work.** Statespace folds one
observation per bar per `(feed, interval)` - 212 of them, 1,028,025 bars folded
on the instance now. The tick project replaces bars with quote updates as the
measurement, which is one to two orders of magnitude more arrivals, on a box
with **2 cores**.

**The parts that are not the hot path are not CPU-bound at all.** Feeds,
journalling, supervision, broker connections and notifications are long-lived
I/O with concurrency, which is Go's subject rather than Python's.

Against that, the research is Python and not negotiably so - numpy,
statsmodels, and a measurement culture of nulls and placebos that lives in
`research/`. And the MT5 bridge has no choice: the `MetaTrader5` package is
Python-only, running under Wine.

## Decision

**Two languages: Python and Go.**

| Part | Language | Why |
| --- | --- | --- |
| research, measurement | Python, permanently | the whole null-and-placebo apparatus is here |
| MT5 bridge | Python, forced | `MetaTrader5` is Python-only under Wine |
| tick ingest and store | **Go**, first | sustained writes, a goroutine per feed, almost no state |
| trading: gates, sizing, orders | Python for now, Go when earned | holds the measured behaviour and a 4,100-test suite |
| statespace | Python; Go only if ticks prove it necessary | measure before porting |
| agents, notifications, news | Python | LLM SDKs, low throughput, nothing to gain |

**Tick ingest is the first Go service.** It is new code, so there is no port to
get wrong; it is I/O-bound and concurrent, which is where Go pays; and it holds
almost no state, so the pickled-state problem in 0002 barely applies to it. It
is also the first step of the tick work, so the first Go service and the next
piece of research are the same artefact.

**Nothing is ported on faith.** Whether Python can fold ticks is measurable,
and that measurement decides whether statespace moves at all.

## Rust, deferred

Rust was considered for the hot path and is **deferred, not rejected**, on the
product owner's call: the current box does not justify a third toolchain.

**What would revive it:** a bigger box. The case for Rust over Go here was
never raw throughput, it was the absence of a garbage collector in a filter
that must run per tick across hundreds of feed-intervals - and on 2 cores the
constraint is simply cores, which neither language fixes. On a machine with
cores to spare, where the remaining variance is GC pause rather than CPU, the
comparison becomes worth making. PyO3 is the way in, because it keeps the
research calling the same function.

Until then this stays here as a recorded option with its condition, rather than
as a plan.

## Consequences

- CI gains a Go job. The repository holds both languages, each under
  `services/<name>/` with its own manifest.
- Two runtimes to build, test and deploy, and two sets of dependency
  advisories.
- The boundary is only as good as the contracts, which is why 0004 exists: a
  second language consuming a payload is a second language that can misread
  it.
