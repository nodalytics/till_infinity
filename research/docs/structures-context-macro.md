# Structures Context Macro

Rationale moved out of `till_infinity/structures/context/macro.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `Reading`

    Every field is optional and `None` means *not published*, never zero. A
    currency with no overnight series is not a currency at zero rates.

    `Restorable` and a default on every field although nothing pickles this:
    the guard that asks for it is a walk over every slotted dataclass in the
    package, and the version of that guard which named its classes passed while
    being blind to twenty others. Arguing the exemption is how the walk gets a
    hole in it, and inheriting costs nothing.


## `Macro.features`

        Only what is actually known. An absent series leaves its key out rather
        than writing a zero, because a zero here is indistinguishable from a
        rate of zero and the yen would read as the flattest curve in the book.

        Every key is prefixed `macro_` so a journal query can select the block
        without knowing what is in it, and every value is a float, which is the
        contract `Signal.features` enforces - a string put here raised on the
        first signal and stopped the structures consumer for four minutes.


## `Macro.stance`

        Two rules, and both ask for the level and the change to **agree**:

        * a currency pair follows the carry. The base is favoured when it pays
          more *and* the gap is widening. A wide gap on its own is priced - it
          has been there for everyone to see - so the level alone says nothing
          and this declines to speak on it.
        * a dollar-quoted asset with no carry follows the discount rate. Gold,
          the crypto and the indices go up when the real yield falls and the
          balance sheet expands, and the two have to agree for the same reason.

        Disagreement returns 0, which is the common case and is the point. A
        model that always has an opinion is not reading anything.


## `stored`

    Read directly rather than through `news.store`, and that is the same choice
    the level warm-up already makes with the prices database: `structures` is
    downstream of `news` on the bus and importing its store to read it would
    put a writer's lock handling in a consumer that only ever reads.

    A missing or unreadable database is not an error here. Macro features are
    an enrichment - the level calls they attach to are correct without them -
    so this returns nothing and says so once, rather than stopping the service
    that consumes it.


