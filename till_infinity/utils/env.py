"""Reading settings out of the environment, the same way in every service.

Six services each grew their own, and they did not agree - which would be a
tidiness complaint if the disagreement were cosmetic. It is not. Given
`SOMETHING=abc` where a number was wanted:

* `agents`, `structures` and `trading` caught `ValueError` and **used the
  default**, silently.
* `news` and `prices` did `float(raw) if raw else default`, which **raises** -
  and a raise at import time takes the service down before it starts.

So the same typo stopped one service and was invisible in another, and which
you got depended on which prefix you mistyped. `docs/trading.md` already has a
rule about this, arrived at from the strategy list rather than from here:

> **An unrecognised value runs everything rather than nothing.** A typo in an
> environment variable must not be able to stop trading - a mis-set base-rate
> floor once refused 99 signals out of 99 and did exactly that.

This module takes that rule and adds the half both versions were missing: a
bad value **falls back and says so**. Silent defaulting hides the typo until
someone wonders why a setting has no effect; raising turns a typo into an
outage. A warning does neither, and it is the only one of the three that leads
anybody to the actual mistake.
"""

from __future__ import annotations

import os

from .logging import get_logger

log = get_logger(__name__)

#: What counts as off. Everything else that is set counts as on, so a flag set
#: to a typo is **on** - the direction that leaves a service running.
FALSE = frozenset({"", "0", "false", "no", "off"})


def env(name: str, default: str = "") -> str:
    """A setting as text, stripped. Absent and empty are the same thing.

    They are the same thing because `NAME=` in an env file is how people
    comment a setting out, and treating that as "set to the empty string"
    means a blank line changes behaviour.
    """
    return (os.environ.get(name) or "").strip() or default


def number(name: str, default: float) -> float:
    """A setting as a float, falling back **loudly** on anything unreadable."""
    raw = env(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        log.warning("config: %s=%r is not a number - using %s", name, raw, default)
        return default


def whole(name: str, default: int) -> int:
    """A setting as an int, falling back loudly.

    Via `float` so `NAME=10.0` is read as 10 rather than discarded. An env file
    written by a human or by another tool is a text file, and `10.0` there is
    someone saying ten.
    """
    raw = env(name)
    if not raw:
        return default
    try:
        return int(float(raw))
    except ValueError:
        log.warning("config: %s=%r is not a whole number - using %s", name, raw, default)
        return default


def flag(name: str, default: bool = False) -> bool:
    """A setting as a switch. Unset takes the default; anything else is on
    unless it is one of `FALSE`."""
    raw = env(name)
    if not raw:
        return default
    return raw.lower() not in FALSE


def symbol_names(value: str | None) -> tuple[str, ...]:
    """Broker symbol names from one env value. **Commas win over spaces.**

    Moved here from `node/desks` so the adapter can read the same list the
    desks are built from. Two derivations of this disagreed on exactly the
    names that have a space in them, which is the whole family this guard is
    about.

    It used to split on both at once - `value.replace(",", " ").split()` -
    which cannot express a broker symbol containing a space. Deriv's
    synthetics all do: `TRADING_SYMBOLS="Volatility 75 Index"` became the three
    symbols `Volatility`, `75` and `Index`, so one synthetic produced three
    desks on instruments no venue lists. Nothing raised - `Symbol("75")` is
    valid and the instrument simply never resolves - so the node came up,
    registered three desks and traded none of them.

    So: **a comma anywhere makes commas the only separator.** Whitespace still
    works where there is no comma, because that is how every existing deploy
    and test writes `EURUSD GBPUSD`. A single spaced name needs a trailing
    comma - `"Volatility 75 Index,"` - which is what a hand-edited env file
    tends to look like anyway.
    """
    if not value:
        return ()
    if "," in value:
        return tuple(part.strip() for part in value.split(",") if part.strip())
    found = tuple(part for part in value.split() if part)
    # **Refuse the shape that used to pass silently.** No broker lists a symbol
    # called `75`, so a bare number among whitespace-split parts means a name
    # was torn apart: `Volatility 75 Index`, `Boom 1000 Index`, `Jump 25
    # Index`. Raising costs a deploy a clear error; the alternative cost three
    # desks quoting instruments that do not exist, with nothing to say so.
    #
    # It does not catch every case - `Step Index` has no number in it - and the
    # comma rule is the one that always works.
    if any(part.isdigit() for part in found):
        raise ValueError(
            f"{value!r} splits on whitespace into {list(found)}, which contains a "
            f"bare number - so a symbol name with a space in it has been torn "
            f"apart. Separate the names with commas: "
            f'"Volatility 75 Index,Boom 1000 Index", or a single one with a '
            f'trailing comma: "Volatility 75 Index,".'
        )
    return found


def names(name: str, default: tuple[str, ...] = ()) -> tuple[str, ...]:
    """A comma-separated list, trimmed, with the empties dropped.

    Written out in five places and slightly differently in each. The empties
    matter: `a,,b` and a trailing comma are what a hand-edited env file looks
    like, and an empty name reaching a lookup is a silent miss rather than an
    error.
    """
    found = tuple(part.strip() for part in env(name).split(",") if part.strip())
    return found or default
