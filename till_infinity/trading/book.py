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

        Both construction sites already pass floats. This is for the state:
        `Book` is persisted and restored, the `Seen` objects inside it come back
        through pickle rather than through the codec's coercion, and a value
        written as a string by an older build is read back as a string, written
        out again at the next save, and circulates indefinitely. Coercing here
        catches them the moment anything constructs one, and `Book.repair`
        catches the ones already in the file.

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

        A restored `Book` arrives through pickle, which reproduces exactly what
        was written - including values an older build stored as strings. Those
        never pass through `Seen.__post_init__` again, so they survive every
        restart and every coercion added since, and the first level published
        near one raises on the subtraction in `observe`.

        Returns how many it fixed, so a caller can say whether the state it
        just loaded was carrying any.
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
