# news/service.py, retired 2026-10-31

The news service's orchestration: `collect`, `poll_once`, `build_sources`,
`Summary` and `Announcer` - a loop over the six sources on two clocks, writing
to a store and publishing `news.articles`, `news.events` and `news.macro` on
the carrier.

**Replaced by `till_infinity/adapters/news/`**, a Nautilus `LiveDataClient`.
Everything that fetches moved there unchanged - the six sources, `source.py`,
`models.py`, `config.py` and `store.py` - and only this file was left behind,
because only this file is about the bus.

| was | is |
|---|---|
| `collect` / `poll_once` | `NewsDataClient._poll` and the module-level `fetch_into` in `client.py` |
| `build_sources` / `SOURCES` | `adapters/news/sources/__init__.py`, beside the sources they name |
| `Announcer` and the three topics | `_handle_data`, publishing `CalendarEvent` on the engine's own bus |
| `Summary` | `Harvest` in `client.py` |

**Why the client and not an Actor, which is the whole reason for the move.**
An Actor that fetched from the network could not be backtested: during a
backtest it would call the live API and get *today's* calendar. A data
client's `_request` serves history out of the store instead, so a backtest
replays the calendar as it stood - which is what this desk's journal already
records, and what news is for.

## Worth keeping out of it

**The announcer's LRU was not a set, and the reason generalises.** The stores
dedup on write but report only counts, so the publishing side needed its own
memory of what it had already announced - otherwise every poll re-announced
the whole feed. `_published` in the client is the same memory keyed on
`(event_id, stage)`, and the bound matters for the same reason: a collector
left running for a week must not grow a set forever.

**`actual` was part of the announce key on purpose.** An event announced as
upcoming is worth announcing *again* once it prints. That is now the two-stage
publish in `data.py`, which is stronger: the stages are separate values with a
guard that refuses a `SCHEDULED` entry carrying an actual, rather than a
convention in a tuple.

**Macro moved in bulk and was announced as a count.** One IMF pull is
thousands of historic rows; announcing each would be noise, so the notice said
the series changed and the subscriber read the store. The client does not
publish macro live at all yet, for a sharper reason: the store records the
*period* a figure describes, not the day it was published, and those are weeks
apart. `_request` serves it; the live side stays silent until a source carries
a publication date.
