"""Which enabled patterns completed on the newest closed bar of a window.

`detect` parses one window of closed bars - the last `LOOKBACK` of a series,
ending at the bar that just closed - and returns a `Finding` for every event of
an enabled pattern whose `known_at` is that bar. Nothing earlier: an event
known three bars ago was alerted three bars ago, or deliberately was not.

The parse is lazy. The default set needs DISPLACE_C and the 12-bar low and
nothing else, so a series with only the default on never builds zones.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property

from . import events as ev
from . import registry
from .tokens import Bars, Tokens, frames
from .trade import Signal, signals

#: Event kinds whose `dir` is the *opposite* of the side they are evidence for.
_REVERSED = frozenset({"BREACH_REVERT", "CLOSE_REVERT", "PROTECTED_TAKEN", "BREAKER_RETEST"})


@dataclass(frozen=True, slots=True)
class Finding:
    """One alertable event on the newest bar of a window."""

    pattern: str
    kind: str
    side: int
    at: int
    known_at: int
    attrs: dict = field(default_factory=dict)
    signal: Signal | None = None

    @property
    def level(self) -> float | None:
        value = self.attrs.get("level")
        return float(value) if value is not None else None


def side_of(kind: str, d: int) -> int:
    """+1 when an event of this kind and label is bullish, -1 when bearish."""
    return -d if kind in _REVERSED else d


class Parse:
    """The events of one window, each computed the first time it is asked for."""

    def __init__(self, bars: Bars, *, pivot: int = 10, move_atr: float = 3.0) -> None:
        self.bars = bars
        self.pivot = pivot
        self.move_atr = move_atr

    @cached_property
    def fr(self) -> dict[int, Tokens]:
        return frames(self.bars)

    @cached_property
    def ext(self) -> list[ev.Event]:
        return ev.extremes(self.fr)

    @cached_property
    def displace(self) -> list[ev.Event]:
        return ev.displace_c(self.fr)

    @cached_property
    def shifts(self) -> list[ev.Event]:
        return ev.delivery_shifts(self.fr)

    @cached_property
    def breach(self) -> list[ev.Event]:
        return ev.breach_reverts(self.fr, self.ext)

    @cached_property
    def close_rev(self) -> list[ev.Event]:
        return ev.close_reverts(self.fr, self.ext)

    @cached_property
    def legs(self) -> ev.Legs:
        return ev.legs(self.fr, self.ext)

    @cached_property
    def voids(self) -> list[ev.Event]:
        return ev.voids(self.fr)

    @cached_property
    def zones(self) -> list[ev.Event]:
        return ev.zones(self.legs, self.voids)

    @cached_property
    def life(self) -> list[ev.Event]:
        return ev.lifecycle(self.bars, self.zones)

    @cached_property
    def breakers(self) -> list[ev.Event]:
        inverted = ev.void_inversions(self.fr, self.voids)
        return ev.breakers(self.fr, self.zones, self.life, self.voids, inverted)

    @cached_property
    def protected(self) -> list[ev.Event]:
        return ev.protected(self.fr, self.legs, ev.sweep_protected(self.fr, self.ext))

    @cached_property
    def signals(self) -> list[Signal]:
        return signals(self.bars, self.fr)

    def kind(self, name: str) -> list[ev.Event]:
        """Every event of one alertable kind in the window."""
        if name == "DISPLACE_C":
            return self.displace
        if name == "DELIVERY_SHIFT":
            return self.shifts
        if name == "BREACH_REVERT":
            return self.breach
        if name == "CLOSE_REVERT":
            return self.close_rev
        if name == "STRUCTURE_SHIFT":
            return ev.structure_shifts(ev.swing_labels(self.ext, self.fr[1].atr))
        if name == "MAJOR_BOS":
            return ev.major_bos(self.fr, self.pivot, self.move_atr)
        if name == "SWEEP_SHIFT":
            return ev.sweep_shifts(
                self.breach + self.close_rev, self.displace + self.shifts, len(self.bars)
            )
        if name == "INDUCEMENT":
            return ev.inducements(self.fr, self.ext, self.zones, self.life)
        if name in ("BREAKER_RETEST", "RECLAIM"):
            return [e for e in self.breakers if e.kind == name]
        if name in ("PROTECTED", "PROTECTED_TAKEN"):
            return [e for e in self.protected if e.kind == name]
        raise KeyError(name)


def applies(pattern: str, timeframe: str, klass: str) -> bool:
    p = registry.PATTERNS[pattern]
    return timeframe in p.timeframes and klass in p.classes


def detect(
    bars: Bars,
    timeframe: str,
    klass: str,
    enabled: tuple[str, ...],
    *,
    pivot: int = 10,
    move_atr: float = 3.0,
) -> list[Finding]:
    """Findings of the enabled patterns completed on the last bar of `bars`."""
    last = len(bars) - 1
    if last < 0:
        return []
    parse = Parse(bars, pivot=pivot, move_atr=move_atr)
    out: list[Finding] = []
    for name in enabled:
        if name in ("M1", "B") or not applies(name, timeframe, klass):
            continue
        p = registry.PATTERNS[name]
        if p.trade:
            out += [
                Finding(name, "DISPLACE_C_LOW12", s.side, s.at, s.at, {"level": s.low3}, s)
                for s in parse.signals
                if s.at == last
            ]
            continue
        for kind in p.kinds:
            # 15m alerts only the major break; ordinary 3/3 shifts never do.
            if kind == "STRUCTURE_SHIFT" and timeframe == "15m":
                continue
            if kind == "MAJOR_BOS" and timeframe != "15m":
                continue
            out += [
                Finding(name, e.kind, side_of(e.kind, e.dir), e.at, e.known_at, dict(e.attrs))
                for e in parse.kind(kind)
                if e.known_at == last
            ]
    return out
