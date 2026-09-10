"""The levels this module has been told about, per instrument.

`trading` reads signals off a bus and never touches the level engine, which is
the right seam - but it leaves it knowing about exactly one level at a time,
the one the current call is at. Trading *toward* a level needs the other ones:
where the next level above price is, and the next below.

So the book is built from what arrives. Every `LEVEL` signal names a price for
an instrument, and remembering those gives a map of the levels the engine
currently holds, without a shared database, an import from `structures`, or a
second copy of the level model. It is a cache of things already published, and
it is honest about being one - a level nobody has published a call for recently
is one this module has never heard of, and `forget` drops what has gone quiet
rather than keeping a map that describes last week.

Two levels within `MERGE_VOL` of each other are the same level: the engine's
Kalman mean moves as touches are folded in, so the same structure arrives at
slightly different prices over an hour and would otherwise accumulate as a
dozen neighbours.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

#: Levels closer together than this, in volatility units, are one level.
MERGE_VOL = 0.35

#: Forget a level nobody has published a call for in this long. Long enough to
#: survive a quiet session, short enough that a restarted engine's revised map
#: replaces the old one rather than merging with it.
FORGET_SECONDS = 6 * 3_600.0


@dataclass(frozen=True, slots=True)
class Seen:
    """One level, as last reported."""

    price: float
    interval: str
    probability: float = 0.0
    strength: float = 0.0
    touches: float = 0.0
    when: float = 0.0

    def __post_init__(self) -> None:
        """Coerce the numbers, because one of these is subtracted every tick.

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
        """
        for name in ("price", "probability", "strength", "touches", "when"):
            value = getattr(self, name)
            if not isinstance(value, int | float):
                try:
                    object.__setattr__(self, name, float(value))
                except (TypeError, ValueError):
                    object.__setattr__(self, name, 0.0)

    def age(self, now: float) -> float:
        return max(0.0, now - self.when)


@dataclass(slots=True)
class Book:
    """Known levels per feed, newest reading wins."""

    merge_vol: float = MERGE_VOL
    forget: float = FORGET_SECONDS
    _levels: dict[str, list[Seen]] = field(default_factory=dict)

    def repair(self) -> int:
        """Rebuild any `Seen` whose numbers came back as strings.

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
        """
        fixed = 0
        for feed, held in self._levels.items():
            out = []
            for seen in held:
                if isinstance(getattr(seen, "price", None), int | float):
                    out.append(seen)
                    continue
                out.append(
                    Seen(
                        price=seen.price,
                        interval=getattr(seen, "interval", ""),
                        probability=getattr(seen, "probability", 0.0),
                        strength=getattr(seen, "strength", 0.0),
                        touches=getattr(seen, "touches", 0.0),
                        when=getattr(seen, "when", 0.0),
                    )
                )
                fixed += 1
            self._levels[feed] = [s for s in out if s.price > 0]
        return fixed

    def observe(self, feed: str, level: Seen, vol_bps: float) -> None:
        """Record a level. Merges into a neighbour if there is one."""
        if level.price <= 0:
            return
        held = self._levels.setdefault(feed, [])
        near = self._tolerance(level.price, vol_bps)
        for index, existing in enumerate(held):
            if abs(existing.price - level.price) <= near:
                held[index] = level  # the newest reading of the same structure
                return
        held.append(level)
        held.sort(key=lambda seen: seen.price)

    def levels(self, feed: str, now: float | None = None) -> list[Seen]:
        when = now if now is not None else time.time()
        held = self._levels.get(feed)
        if not held:
            return []
        alive = [seen for seen in held if seen.age(when) <= self.forget]
        if len(alive) != len(held):
            self._levels[feed] = alive
        return alive

    def next_above(self, feed: str, price: float, now: float | None = None) -> Seen | None:
        """The nearest level above `price`, or None."""
        return next((seen for seen in self.levels(feed, now) if seen.price > price), None)

    def next_below(self, feed: str, price: float, now: float | None = None) -> Seen | None:
        """The nearest level below `price`, or None."""
        found = [seen for seen in self.levels(feed, now) if seen.price < price]
        return found[-1] if found else None

    def toward(self, feed: str, price: float, sign: int, now: float | None = None) -> Seen | None:
        """The next level in the direction `sign` points."""
        return self.next_above(feed, price, now) if sign > 0 else self.next_below(feed, price, now)

    def count(self, feed: str) -> int:
        return len(self.levels(feed))

    def _tolerance(self, price: float, vol_bps: float) -> float:
        if vol_bps <= 0:
            return 0.0
        return abs(price * (vol_bps * self.merge_vol) / 10_000)
