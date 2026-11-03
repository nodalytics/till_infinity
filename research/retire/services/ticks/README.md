# services/ticks

Quote history out of the MT5 terminal and into the tick corpus. Go, because
this is a sustained I/O path with almost no state - the case
[ADR 0003](../../docs/adr/0003-python-and-go.md) makes for the first service
out of Python.

The on-disk contract is [`shared/contracts/ticks.md`](../../shared/contracts/ticks.md).
Read it first: it is the part both languages have to agree on, and it explains
the two rules this code exists to keep.

## Running a backfill

```sh
export TRADING_MT5_URL=http://127.0.0.1:8000     # the bridge
export TRADING_MT5_API_KEY=...                   # same key the desk uses
go run ./cmd/backfill -root ~/tick-data -from 2025-01-01
```

The same two variables the desk's broker client reads, so a box configured to
trade is already configured to backfill. `-dry-run` says what it would fetch.
`-feeds` narrows the default set, which is the fourteen FX majors and crosses
`statespace-surprise` trades.

**Run it on the box with the terminal.** The bridge answers on loopback there;
over the reverse tunnel every request pays the round trip twice and the
terminal is the bottleneck either way.

## Why it is slow on purpose

One request at a time, with a pause between. There is a single terminal behind
the bridge and every call goes through its IPC pipe - the bridge's own stream
router says six parallel sweeps against one terminal is not six times the
throughput. The same component starved its own HTTP server into timing out when
the terminal was configured for a million bars per chart, which is how the desk
lost its broker for most of a day on 2026-10-28.

To go faster, ask for a wider range per request rather than more requests at
once.

## The two rules

**A file that exists is a day that is complete.** Each day is written under a
temporary name and renamed, so a reader walking the corpus during a backfill
sees a whole day or no day. A zero-length file - what a process killed
mid-write leaves behind - does not count as done, or a resumable run would
write a permanent hole.

**An empty day is absent, not empty.** History downloads on demand, so a period
the terminal has never been asked for comes back empty until it has fetched it.
A weekend and an undownloaded month are indistinguishable from here, so neither
is written, and the run reports the empty count separately from the failures.

## Layout

```
cmd/backfill/      the command
internal/bridge/   the MT5 bridge client, and the tick row
internal/store/    the Parquet writer and the partition layout
```

`cmd/` and `internal/` rather than a flat package, so nothing outside this
service can import its innards - the boundary ADR 0002 asks for, enforced by
the language rather than by a test.
