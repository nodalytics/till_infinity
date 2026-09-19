# Trading Book

Rationale moved out of `till_infinity/trading/book.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `Seen.__post_init__`

        `Book.observe` does `abs(existing.price - level.price)` on every
        published level, so a single string price raises `TypeError` and the
        per-message guard skips that signal. It ran at **124 dropped signals a
        session** before anyone read past the guard to the traceback.

        **The door this closes is construction, and the mechanism behind the
        392 found in live state is not settled.** The first guess written here
        was that a restored `Book` bypasses the codec through pickle; that is
        wrong, and measurably so - packing a `Seen` with `price="1.2345"` and
        unpacking it through `codec` with trading's registry returns a float,
        because `Seen` is a slotted non-`Restorable` dataclass and so takes the
        coercion branch added on 2026-09-10. Yet `Book.repair` still found 392
        string prices in state written by a build that had that branch.

        So something creates them *after* restore - most likely a payload whose
        price arrives as text and reaches `Book.observe` as a `Seen` - and this
        is the coercion for that path, wherever it starts. `Book.repair` covers
        whatever is already in the file. The discriminating measurement is the
        next restart: `repair` reporting zero says the file is clean and this
        is holding; reporting a number again says they are still being made and
        the door is somewhere else.

        Frozen, so `object.__setattr__`.


## `Book.repair`

        Restore is the one path `Seen.__post_init__` cannot cover: the codec
        builds through `cls.__new__` and a generated `__setstate__`, so a value
        already in the file never passes a constructor again. It survives every
        restart, is written out at the next save, and the first level published
        near it raises on the subtraction in `observe`.

        The count is the reason this returns anything. It found **392** at the
        first restore after being added, in state written by a build whose codec
        already coerces `Seen` - see `__post_init__` for why that is not yet
        explained. A repair that logs how much it repaired is what turns the
        next restart into a measurement rather than another guess.


