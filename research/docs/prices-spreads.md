# Prices Spreads

Rationale moved out of `till_infinity/prices/spreads.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `_fill_keys`

    A named pair carries only feed and venue; without the other two the leg
    query cannot use `bars_series_ts` and scans the table instead - which on
    production is 23GB. Looked up once here rather than per read.

    **Looked up leg by leg, not from a census.** Asking what every stored series
    is costs a full pass over that table, and on 2026-09-15 that pass - taken at
    the top of the collector, before its first `await` - stopped the desk: no
    quotes were written for as long as it ran, because one synchronous query
    holds the loop every actor shares. Four named pairs need five legs, and five
    legs are ten index seeks.


## `named`

    `name=feed@VENUE-feed@VENUE`, comma separated - **the same syntax
    `STRUCTURES_SPREAD_QUOTES` takes**, deliberately, so the bar series and the
    quote series of one spread are configured the same way and can be compared
    without anybody checking whether two configs mean the same pair.

    Discovery is the right default when the question is "what could be built",
    and the wrong one when the answer is eighty series nobody asked for: `btc`
    alone yields ten venue pairs from five venues, and the whole book yields
    hundreds. A spec names what is wanted.

    Malformed entries are skipped with a warning rather than raised. A typo in
    one pair should not stop a collector starting.


