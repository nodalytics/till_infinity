# services/, retired 2026-10-31

`services/ticks` - a Go tick-ingest service, 11 tests, backfilling 14 FX feeds
to Parquet - and `services/redis`, the broker's configuration.

**Retired because Nautilus supplies both.** Its `ParquetDataCatalog` is the
corpus, its adapters are the ingest, and its `MessageBus` takes the Redis
configuration that `services/redis` held. ADR 0003's decision to add Go is
superseded: the polyglot goal is met by Nautilus's own Rust core, so the
desk is Python and Rust without us writing either.

**These were deleted by accident before being retired on purpose.** A
`git add -A` after a long sequence of moves swept them out in `a80de7e`, and
the loss was found by `test_the_go_service_is_excluded_rather_than_broken`
failing with "services/ticks is excluded but does not exist" - a guard written
for a different reason catching a different mistake. Restored from
`a80de7e^`.

## Worth keeping out of the Go service

**The tick corpus is tiny next to the terminal's own cache.** About 500KB per
feed-day against 104GB of `.tkc`, because the terminal stores every quote
revision in its own format and the corpus stores what a study needs.

**`flags` is a bitfield with an undocumented bit 128.** Measured on eurusd:
`4` (ask only) 10.0%, `130` (bid only) 12.8%, `134` (both) 77.2%. Testing
`flags in (2, 4)` reports 10.0% one-sided where the truth is 22.8%. Test the
bits, never the value - which is now recorded in the adapter that replaced
this service.

**Temp-file-and-rename, and a refusal to write an empty day.** `store.Done()`
rejects a zero-length file and `Write()` refuses a day with no ticks, because
a truncated or empty Parquet file is indistinguishable from a quiet market
until somebody tries to use it.
