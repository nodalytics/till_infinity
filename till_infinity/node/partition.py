"""Keeping two operators off each other's edges.

Two people running this pipeline on the same data with the same gates converge
on the same winners, and then compete for the same liquidity. The requirement
is that independent runs rarely produce the same edges.

**Randomising the seed does not do it, and would do harm.** If the gates work,
the real edges are exactly what every run finds; what differs between seeds is
which *noise* survived. Seed-based differentiation therefore hands each
operator a different set of artefacts while leaving the genuine overlap
untouched - the opposite of the intent, and undetectable without comparing the
two sets.

So the search space is partitioned instead. It is deterministic, which means a
run is reproducible and an overlap is explainable rather than mysterious, and
the partition is *checkable* - `overlap` measures what actually happened
rather than trusting that the scheme worked.

Three levers, in order of how much separation they buy:

1. **Disjoint slices.** Feeds, intervals and question types are assigned, not
   drawn. Two operators then explore genuinely different regions.
2. **A register of what is live.** The direct answer to fighting: an edge
   already being traded is not promoted again, whoever found it.
3. **Capacity.** An edge that clears cost at small size and not at large is
   found by one operator and correctly rejected by the other. That is a real
   difference in what is tradable, not a manufactured one.

**What this cannot do, stated plainly:** if one instrument at one interval
carries the only edge on the desk, every partition that includes it will find
it. Separation is bounded by how much genuine structure there is, and a scheme
that claimed otherwise would be hiding the overlap rather than removing it.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field


def _digest(*parts: str) -> int:
    """A stable integer from strings. Stable across processes and versions.

    `hash()` is salted per process in Python, so a partition built on it would
    differ between runs of the *same* operator - which is the one thing this
    must not do.
    """
    joined = "\x00".join(parts).encode()
    return int.from_bytes(hashlib.blake2b(joined, digest_size=8).digest(), "big")


@dataclass(frozen=True, slots=True)
class Slice:
    """One operator's region of the search space."""

    operator: str
    feeds: tuple[str, ...]
    intervals: tuple[str, ...]
    questions: tuple[str, ...]
    #: Account size this operator trades, which decides what clears cost.
    capacity: float = 0.0

    def covers(self, feed: str, interval: str, question: str) -> bool:
        return feed in self.feeds and interval in self.intervals and question in self.questions

    @property
    def size(self) -> int:
        return len(self.feeds) * len(self.intervals) * len(self.questions)


def assign(
    operator: str,
    *,
    feeds: Sequence[str],
    intervals: Sequence[str],
    questions: Sequence[str],
    operators: Sequence[str],
    capacity: float = 0.0,
) -> Slice:
    """Deal this operator a slice of the space, deterministically.

    Every operator must be named in `operators`, because the partition depends
    on the whole set: a slice that did not know how many others existed could
    not be disjoint from them.

    **Feeds are dealt round-robin over a stable shuffle rather than split into
    contiguous blocks.** Contiguous blocks would hand one operator every FX
    major and another every synthetic, which is not a partition of the
    *search* so much as of the market - and those regions have very different
    amounts of structure in them.
    """
    if operator not in operators:
        raise ValueError(
            f"{operator!r} is not among {list(operators)} - a slice cannot be disjoint "
            f"from operators it does not know about"
        )
    count = len(operators)
    index = sorted(operators).index(operator)

    def deal(items: Sequence[str], stride: int) -> tuple[str, ...]:
        ordered = sorted(items, key=lambda x: _digest("order", x))
        taken = tuple(ordered[i] for i in range(index, len(ordered), stride))
        # Never deal an empty dimension: an operator with no intervals has no
        # search at all, which is a silent withdrawal rather than a partition.
        return taken or (ordered[index % len(ordered)],)

    return Slice(
        operator=operator,
        feeds=deal(feeds, count),
        # Intervals and questions are dealt on a rotation rather than split,
        # because there are few of them and splitting would leave an operator
        # unable to ask most of the questions.
        intervals=tuple(
            sorted(intervals, key=lambda x: _digest(operator, "interval", x))[
                : max(1, len(intervals) - count + 1)
            ]
        ),
        questions=tuple(
            sorted(questions, key=lambda x: _digest(operator, "question", x))[
                : max(1, len(questions) - 1)
            ]
        ),
        capacity=capacity,
    )


@dataclass(frozen=True, slots=True)
class Overlap:
    """How much two runs actually agreed."""

    shared: tuple[str, ...]
    only_left: tuple[str, ...]
    only_right: tuple[str, ...]

    @property
    def jaccard(self) -> float:
        """Shared over the union. Zero is disjoint, one is identical."""
        union = len(self.shared) + len(self.only_left) + len(self.only_right)
        return len(self.shared) / union if union else 0.0

    @property
    def acceptable(self) -> bool:
        """Under a fifth shared.

        A bar rather than zero, because zero overlap would mean the gates
        disagree about real structure - which is a worse problem than
        crowding.
        """
        return self.jaccard < 0.2

    def lines(self) -> list[str]:
        out = [
            f"overlap {self.jaccard:.0%}: {len(self.shared)} shared, "
            f"{len(self.only_left)} and {len(self.only_right)} unique"
        ]
        if self.shared:
            out.append("  shared: " + ", ".join(sorted(self.shared)[:6]))
        return out


def overlap(left: Sequence[str], right: Sequence[str]) -> Overlap:
    """Compare two runs' discovered edges.

    **Measured rather than assumed.** A partition scheme that is never checked
    is a scheme that is believed, and the whole point of making the partition
    deterministic is that this comparison means something.
    """
    a, b = set(left), set(right)
    return Overlap(
        shared=tuple(sorted(a & b)),
        only_left=tuple(sorted(a - b)),
        only_right=tuple(sorted(b - a)),
    )


@dataclass(slots=True)
class LiveRegister:
    """What is already being traded, by whom.

    **The direct answer to fighting over an edge**, and the one lever that
    does not depend on the partition working. A slice can overlap by accident;
    this refuses a promotion outright.

    Shared state between operators, so it is a file somebody else writes. A
    stale register is worse than none - it would block promotions for edges
    nobody runs any more - so entries carry a heartbeat and go cold.
    """

    #: edge name -> (operator, last seen)
    entries: dict[str, tuple[str, float]] = field(default_factory=dict)
    #: Seconds after which an entry is treated as abandoned.
    cold_after: float = 7 * 86_400.0

    def claim(self, edge: str, operator: str, at: float) -> bool:
        """Record that `operator` is trading `edge`. False if somebody else is."""
        held = self.entries.get(edge)
        if held is not None and held[0] != operator and (at - held[1]) < self.cold_after:
            return False
        self.entries[edge] = (operator, at)
        return True

    def heartbeat(self, edge: str, operator: str, at: float) -> None:
        held = self.entries.get(edge)
        if held is None or held[0] == operator:
            self.entries[edge] = (operator, at)

    def release(self, edge: str, operator: str) -> None:
        held = self.entries.get(edge)
        if held is not None and held[0] == operator:
            del self.entries[edge]

    def taken_by(self, edge: str, at: float) -> str | None:
        held = self.entries.get(edge)
        if held is None or (at - held[1]) >= self.cold_after:
            return None
        return held[0]

    def cold(self, at: float) -> tuple[str, ...]:
        """Edges whose operator has stopped reporting."""
        return tuple(
            edge for edge, (_who, seen) in self.entries.items() if (at - seen) >= self.cold_after
        )


def clears_cost(edge_per_trade: float, round_trip_cost: float, size: float) -> bool:
    """Does this edge survive its cost at this size?

    **The honest differentiator between operators, and the only one that is
    not manufactured.** A larger account pays more of the spread and more
    impact, so an edge worth 0.4 of a spread is tradable for somebody small
    and not for somebody large - and that is a real difference in what is
    tradable rather than a scheme to keep people apart.

    Cost scales with size here as a square root, which is the conventional
    shape for impact and is approximately right for what matters: the
    direction and the order of magnitude. `exotic-spreads-are-a-whole-bar-
    range` is why cost is checked at all before anything else - 0.40 to 0.97
    of a bar's range round trip ends most ideas, and costing them first is the
    cheapest way to find that out.
    """
    if size <= 0.0:
        return edge_per_trade > round_trip_cost
    scaled = round_trip_cost * (1.0 + size**0.5)
    return edge_per_trade > scaled


def differentiate(
    candidates: Sequence[str],
    slice_: Slice,
    register: LiveRegister,
    *,
    at: float,
    coordinates: dict[str, tuple[str, str, str]] | None = None,
) -> tuple[list[str], dict[str, str]]:
    """Filter candidates to what this operator should pursue.

    Returns what passes and why each rejection happened, because an operator
    told only "nothing for you" cannot tell a partition from an outage.
    """
    keep: list[str] = []
    why: dict[str, str] = {}
    places = coordinates or {}
    for name in candidates:
        holder = register.taken_by(name, at)
        if holder is not None and holder != slice_.operator:
            why[name] = f"already traded by {holder}"
            continue
        place = places.get(name)
        if place is not None and not slice_.covers(*place):
            why[name] = f"outside this slice {place}"
            continue
        keep.append(name)
    return keep, why
