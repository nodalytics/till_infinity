# The tick corpus

The on-disk contract for quote history pulled from the MT5 terminal. Written by
`services/ticks` (Go), read by `research/` (Python) and by anything later that
wants ticks. [ADR 0002](../../docs/adr/0002-services-are-self-contained.md): a
thing both sides of a boundary must agree on lives here, not inside whichever
service wrote it first.

## Layout

```
<root>/feed=<feed>/date=<YYYY-MM-DD>/ticks.parquet
```

One file per feed per **UTC** day. Hive-style partitioning because every reader
worth using - pandas, polars, duckdb - discovers `feed` and `date` as columns
from the path without being told, and because a day is the unit a backfill can
resume on: a file that exists is a day that is done.

`feed` is the desk's own lowercase name (`eurusd`), not the broker's symbol
(`EURUSD`). The desk names feeds, brokers name symbols, and the mapping belongs
to whoever talks to the broker.

## Schema

| column | type | |
| --- | --- | --- |
| `time_msc` | int64 | **The timestamp.** Epoch milliseconds, UTC. |
| `bid` | float64 | |
| `ask` | float64 | |
| `last` | float64 | |
| `volume` | int64 | |
| `volume_real` | float64 | |
| `flags` | int32 | Which fields this update changed. See below. |

Sorted by `time_msc` ascending within a file.

**`time_msc` is the only timestamp kept.** The terminal also returns `time`, a
second-resolution copy of the same instant - the millisecond value truncated.
Keeping both invites a reader to join on the wrong one.

## `flags` is the one thing here that bar data cannot express

MT5 sets a bit per field the update changed:

| bit | meaning |
| ---: | --- |
| 2 | the **bid** changed |
| 4 | the **ask** changed |
| 8 | `last` changed |
| 16 | `volume` changed |
| 32 | a buy was the last deal |
| 64 | a sell was the last deal |

**A one-sided revision is bit 2 without bit 4, or the reverse** - the bid moved
and the ask did not. Every OHLC series collapses bid and ask into one price, so
this is a class of observable the desk has never had, and the only directional
one this feed can support.

**Test the bits, never the value.** Measured on `eurusd`, 2026-10-27, 134,550
ticks: the values that actually appear are `4` (ask only, 10.0%), `130` (bid
only, 12.8%) and `134` (both, 77.2%). An undocumented **bit 128** rides along
with every bid-carrying update, so `flags in (2, 4)` finds the ask-only case
and misses the bid-only one - it would report 10.0% one-sided where the truth
is **22.8%**. Use `flags & 2` and `flags & 4`.

Note also that `df.flags` is pandas' own `DataFrame.flags` property, not this
column. Read it as `df["flags"]`. Worth testing precisely because the bar is honest
about what it cannot say: `statespace-signals.md` records that everything
surviving a null predicts *size*, and `direction-is-closed-not-just-null.md`
records a gate finding a planted drift at z +2.90 and earning 2% of a spread.

**Bits 32 and 64 are absent, and are kept to prove it** - measured as exactly
zero over that day, alongside one distinct value each for `last`, `volume` and
`volume_real`. This
broker publishes no trade prints - `last`, `volume` and `volume_real` read 0 or
a constant, and `market_book_add` fails outright, so there is no depth either.
That is why VPIN, signed flow and micro-price are not on any roadmap here: they
are unavailable rather than hard. The columns stay so a reader can check that
rather than taking this paragraph on trust, and so that the day the broker
starts publishing them, the corpus notices.

## What this is not

**Not the stream.** The bridge also pushes ticks over a WebSocket, but MT5 has
no push API, so that endpoint *polls* `symbol_info_tick` every 0.25s (0.1s
floor) and sends only changes. That is the right shape for a live desk and the
wrong one for a corpus: a feed that moves twice inside a poll yields one row.
`copy_ticks_range` returns what the terminal actually recorded, which is what a
measurement needs.

**Not complete before the terminal has it.** History downloads on demand, so a
range the terminal has never been asked for returns nothing until it has
fetched it - the first deep request can fail and a retry succeed. A backfill
that reads an empty answer as "no ticks that day" writes a hole and calls it
data, so `services/ticks` records an empty day as **absent** rather than as an
empty file, and says how many days came back empty.
