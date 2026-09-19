# Trading Config

Rationale moved out of `till_infinity/trading/config.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `register_broker_instruments`

    An instrument needs four things to be traded here: a name the broker
    answers to, an exposure leg, a price feed, and a place in the symbol list.
    All four were written by hand for nine synthetics, in three files, keyed on
    a slug each computed for itself - which is three chances to disagree and no
    way to notice.

    This is the generated form. The broker's own name is the only alias,
    because for an instrument nothing else quotes there is nothing to guess at.

    **Not the whole catalogue.** The account lists 798 symbols and level
    building scales with feeds times timeframes, so what is registered is what
    is asked for. Naming them is the operator's decision; keeping the four
    tables in step is not.


## `magic_for`

    Names in `MAGIC_ORDER` get their fixed slot. Anything else - a strategy
    registered by something outside this package - is hashed into the rest of
    the band, deterministically, because Python's own `hash` is salted per
    process and would hand the same strategy a different magic on every
    restart. Collisions are possible in that tail and are reported at start-up
    rather than left to be discovered in a report that quietly merges two
    strategies' results.


## `_overshoot`

    **The side matters and a per-feed number is wrong on a jump instrument.**
    On `boom_500_index`, 84,506 of 84,701 tick moves are down and 162 are up, of
    which 160 are spikes - so a stop above price can never be *walked* to, only
    jumped over, while a stop below behaves normally. Measured in
    `research/generators.md`: the spike side overshoots by **+9.9R to +19.1R**
    and the grind side by **+0.02R**. One number for the feed would either leave
    the tail unsized or shrink the side that works.

    A bare `feed=` still applies to both sides, so existing settings are
    unchanged.

    A malformed pair is dropped rather than raised on: this is a sizing
    reduction, and a typo in it should cost the correction, not the desk.

    `none` turns the correction off entirely, and exists so that "unset" and
    "deliberately empty" are different instructions. Without it an unset
    variable would have to mean no scaling, which would silently discard
    `DEFAULT_STOP_OVERSHOOT` - the exact drift `DEFAULT_FORMATION` was named to
    stop, where a field default and its environment fallback disagreed and the
    deployment got whichever one `from_env` happened to say.


## `feed_for`

    The reverse of `INSTRUMENTS`, and it has to work *without* a resolved
    symbol map because the map is built by asking a broker for specs, and a
    broker being asked for a spec may need to know which instrument it is
    answering about. Consulting `Settings.resolved` there is circular, and the
    paper book did exactly that: while resolution was still running the map was
    empty, gold fell through to the currency-pair default, and a 100-ounce
    contract was priced as 100,000 units - a stop that should cost $440 a lot
    priced at $440,000, so every trade refused itself as too large to size.

    Exact matches win over prefixes, and the longest prefix wins among the
    rest, so `BTCUSDT` does not resolve against a shorter name from another
    instrument.


