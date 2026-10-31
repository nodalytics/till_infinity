"""Does a replay resemble the desk it claims to describe.

## The problem

`sweepstops.py` replayed `sweep-aware`'s own entries under its own exit policy
and reported that **98.8% of trades end on the stop**. The live desk, running
that policy on that strategy, ends **13%** of them on the stop and **66% on the
hold timeout**.

That is not a small gap in a performance number. It is a different machine. And
the mean R figures **agreed** - +0.032 replayed against +0.134 live - which is
exactly why nobody noticed: the number everyone looks at matched while the
mechanics did not.

The consequence is already in production: `exits.py` chose `sweep-aware`'s
shipping exit on a replay that exits 98% by stop where the desk exits 13%. The
replay kernel fixed that harness's arithmetic. It did not make the simulation
resemble the desk, and nothing was checking.

## Structure, not performance

Comparing mean R would fire on every healthy replay. The two are **different
populations by construction**: a replay walks every published call, and
`risk.py` refuses the expensive ones before they become trades - the desk pays a
median 0.081R of spread where the replayed population averages 0.363R. Those
means *should* differ.

What should not differ is **how trades end**. Same entries, same policy, same
instrument: the exit-kind mix, the hold duration and the distribution of
high-water marks are fingerprints of the *mechanics*, and none of them depends
on whether the strategy has an edge.

## It labels, it does not refuse

Sometimes a population the desk does not take is exactly what is being studied -
`spikeside.py` deliberately replayed every level call on six feeds. A check that
blocked that would be worked around rather than read.

What this removes is the case where nobody compared.

## What it cannot do

It says a replay does not resemble the desk. It does **not** say which of them
is right, and it cannot: a replay may diverge because it is broken or because it
is deliberately studying something else, and only its author knows which.

And passing is necessary rather than sufficient. Both look-aheads found on
2026-09-11 would have produced a perfectly plausible exit mix while paying
prices the market never offered. **This is a check on resemblance, not on
honesty**, and `shared/replay.py` remains the answer to the second.
"""

from __future__ import annotations

import statistics as st
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

#: Share of closes on any single exit kind that may differ before the mechanics
#: are called different. The observed case was **86 points**; this catches it
#: three times over while leaving room for the ordinary difference between a
#: replay's population and the desk's.
MIX_POINTS = 0.25

#: Ratio of median hold durations. The observed case was 4.7x, from a harness
#: holding 1,440 bars where the desk holds 30.
HOLD_RATIO = 2.0

#: Below this many live closes there is no verdict at all. `confluence-scalp` at
#: n=11 is exactly where a threshold fires on noise - the same argument
#: `strata.min_n` makes, and the same resolution: report, do not judge.
MIN_LIVE = 30


@dataclass(slots=True)
class Fingerprint:
    """How a population of trades ended, as structure rather than performance."""

    n: int = 0
    mix: dict[str, float] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)
    hold: float | None = None
    best: float | None = None
    #: Closes that never said how they ended. Counted separately rather than
    #: folded in as a fourth category, because `exit_kind` is missing on 8% of
    #: `sweep-aware` closes and 20% of `fade-to-value` - a liveness problem in
    #: the field this check depends on, and folding it in would hide it.
    unknown: int = 0

    def share(self, kind: str) -> float:
        return self.mix.get(kind, 0.0)


def fingerprint(rows: Iterable[Mapping[str, Any]]) -> Fingerprint:
    """Build a fingerprint from closes - replayed or live, same code both sides.

    Rows carry `exit_kind` and optionally `seconds` and `best_r`. Both sides go
    through here so the two cannot drift in how they count, which is the whole
    reason this is a function rather than two comprehensions in two harnesses.
    """
    counts: dict[str, int] = {}
    holds: list[float] = []
    bests: list[float] = []
    unknown = 0
    for row in rows:
        kind = row.get("exit_kind")
        if not isinstance(kind, str) or not kind or kind == "?":
            unknown += 1
            continue
        counts[kind] = counts.get(kind, 0) + 1
        for key, dest in (("seconds", holds), ("best_r", bests)):
            value = row.get(key)
            if isinstance(value, int | float) and not isinstance(value, bool):
                dest.append(float(value))

    total = sum(counts.values())
    return Fingerprint(
        n=total,
        counts=counts,
        mix={k: v / total for k, v in counts.items()} if total else {},
        hold=st.median(holds) if holds else None,
        best=st.median(bests) if bests else None,
        unknown=unknown,
    )


@dataclass(slots=True)
class Verdict:
    """Whether a replay reproduces the desk, and where it does not."""

    replayed: Fingerprint
    live: Fingerprint
    #: None when there was not enough live evidence to judge on.
    reproduces: bool | None = None
    judged: bool = False
    #: Exit kinds one side produces and the other cannot, at any rate.
    structural: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)

    def render(self) -> str:
        out = ["CROSS-CHECK: "]
        if not self.judged:
            out[0] += "too few live closes to compare."
        elif self.reproduces:
            out[0] += "this replay reproduces the live mechanics."
        else:
            out[0] += "this replay does NOT reproduce the live mechanics."

        kinds = sorted(set(self.replayed.mix) | set(self.live.mix))
        mix = ", ".join(
            f"{k} {self.replayed.share(k):.1%} vs {self.live.share(k):.1%}" for k in kinds
        )
        out.append(f"  exit mix   {mix}")
        if self.replayed.hold is not None and self.live.hold is not None:
            ratio = max(self.replayed.hold, self.live.hold) / max(
                min(self.replayed.hold, self.live.hold), 1e-9
            )
            out.append(
                f"  hold secs  median {self.replayed.hold:.0f} vs "
                f"{self.live.hold:.0f}   ({ratio:.1f}x)"
            )
        if self.replayed.best is not None or self.live.best is not None:
            # Reported and not gated: `best_r` still reads 0.000 as a median on
            # four of six strategies, so the field is not reliable enough to
            # judge on - and printing it is how anybody finds out when it is.
            out.append(
                f"  best_r     median {_maybe(self.replayed.best)} vs "
                f"{_maybe(self.live.best)}   (reported, not gated)"
            )
        out.append(f"  replayed n={self.replayed.n}, live n={self.live.n}")
        if self.replayed.unknown or self.live.unknown:
            out.append(
                f"  ** {self.replayed.unknown} replayed and {self.live.unknown} live "
                f"closes never said how they ended"
            )
        out.extend(f"  ** {line}" for line in self.gaps)
        if self.judged and not self.reproduces:
            out.append("  Conclusions below describe a desk that does not exist.")
        return "\n".join(out)


def _maybe(value: float | None) -> str:
    return f"{value:+.3f}" if value is not None else "-"


def agree(replayed: Fingerprint, live: Fingerprint) -> Verdict:
    """Whether the replay reproduces the desk, and where it does not."""
    got = Verdict(replayed=replayed, live=live)

    # An absence is not agreement. A replay that produced nothing and a desk
    # that has traded nothing are both absences.
    if live.n < MIN_LIVE or replayed.n == 0:
        return got
    got.judged = True

    for kind in sorted(set(replayed.mix) | set(live.mix)):
        here, there = replayed.share(kind), live.share(kind)
        # A kind one side never produces is a structural mismatch rather than a
        # percentage gap. `stale` is 12% of `thesis-only` and the replay has no
        # concept of it; calling that "12 points" would understate it.
        if (kind not in replayed.mix) and there > 0:
            got.structural.append(kind)
            got.gaps.append(f"the replay cannot produce a {kind!r} exit; live it is {there:.1%}")
        elif abs(here - there) > MIX_POINTS:
            got.gaps.append(
                f"{kind}: {here:.1%} replayed against {there:.1%} live "
                f"({abs(here - there) * 100:.0f} points)"
            )

    if replayed.hold is not None and live.hold is not None:
        low = max(min(replayed.hold, live.hold), 1e-9)
        if max(replayed.hold, live.hold) / low > HOLD_RATIO:
            got.gaps.append(
                f"hold: median {replayed.hold:.0f}s replayed against {live.hold:.0f}s live"
            )

    got.reproduces = not got.gaps
    return got
