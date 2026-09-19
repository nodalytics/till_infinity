# Prices Store

Rationale moved out of `till_infinity/prices/store.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `SqliteStore.prune`

        Per **series**, not per table and not per age. A count rather than a
        cutoff date because the models consume a *window of bars* - the level
        engine seeds from the last few hundred per instrument and timeframe -
        so a count keeps exactly what can still be used. It also self-scales
        across timeframes without a table of durations: 2,000 is about a day
        and a half of 1m and about forty years of 1w, which is the right shape,
        since that is also roughly how far back each one's evidence is worth
        anything.

        **Quotes are left alone, and that is a gap rather than a decision.**
        The claim that used to sit here - that they are bounded by
        `dedupe_quotes`, and that bars are what grow without limit - is wrong
        in both halves, and measuring the file says so plainly:

            quotes             333.2 MB
            quotes_series_ts   212.3 MB   index
            quotes_feed_ts     191.3 MB   index
            bars                51.7 MB
            bars_series_ts      36.2 MB   index

        Quotes are 76% of it and their two indexes cost more than the rows.
        `dedupe_quotes` skips a quote whose price is *unchanged*, which lowers
        the write rate in a quiet market and removes nothing - every price
        change is kept for ever. On the instance they spanned 39.3 hours,
        which was the entire age of the database: not one had ever been
        deleted, at roughly 64,000 rows an hour.

        So this prunes the smaller, slower half. See todo.md - quote retention
        is its own item, and the answer there is probably not "keep them
        longer" but "record what a touch needed at the moment it happened".

        **Deleting does not shrink the file.** SQLite frees the pages for reuse,
        so growth stops but the database stays its current size until it is
        rebuilt. `vacuum=True` rebuilds it, and needs room for a second copy
        while it runs - which is the one thing in short supply when this is
        being reached for, so it is off by default and the caller decides.


## `SqliteStore.reindex`

        **A corrupt index is not a corrupt database**, and the difference has
        very different answers. `quotes_feed_ts` on the production file has been
        unusable since 2026-09-10 while every row in `quotes` reads back fine: a
        query that plans through it fails and the same query without it does
        not. That is one B-tree to rebuild, not a database to restore - and two
        agents were told the file was corrupt on the strength of the first
        symptom.

        `REINDEX` reads the table and writes a new tree, so it needs room for
        the index but not for a second copy of the file. That is the difference
        between a repair that can run on a full instance and one that cannot -
        and unlike `VACUUM`, nothing is lost if it fails, because no row is ever
        read as authoritative from an index.

        Targeted rather than blanket: `only` names one index, because rebuilding
        every index on a multi-gigabyte quotes table to fix one of them is how a
        repair becomes an outage.


## `SqliteStore._rebuild`

        `REINDEX` is tried first because it is the narrow operation - it keeps
        the definition and replaces the tree. It can itself fail on a badly
        enough damaged tree, raising the same "database disk image is malformed"
        that sent us here, because it has to walk what it is replacing.

        So the fallback is to drop the definition and write it again from
        `sqlite_master.sql`, which is the index's own `CREATE INDEX` statement
        as SQLite stored it. That is still only an index: the rows are
        untouched either way, and an index that cannot be rebuilt by either
        route is reported rather than raised, because the caller reached for a
        repair and an exception is not one.


