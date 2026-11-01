"""Breaking a result down by when it happened.

**The other check that caught what DSR, PBO and SPA missed.** Six artefacts on
this desk are held to have passed all three, with surrogate reruns and an
hourly breakdown exposing them - **and that figure is unsourced**:
`research/docs/lopez-de-prado.md` is the only deflation on record here and
records no PBO or SPA run at all. Read it as the reason the module was written
rather than as a measurement. So this is not a diagnostic to run afterwards -
it is one of the two gates worth most.

Why the hour specifically, measured rather than assumed:

- intraday pattern lives in **volatility**, and FX peaks at 14-15 UTC at about
  three times its quiet level - `research/docs/direction-rules.md`, confirmed
  independently in `research/docs/statespace-profile-and-legs.md`. A statistic
  that does not control for the hour is partly reading the clock.
- `a-pair-of-bars-needs-the-hour-of-day-null`: ordering suppresses two-bar
  statistics by 0.046 to 0.072, and **half of that is the daily cycle**. A
  generated null has none of it, which is how a generated null passes
  something it should refuse.
- `calendar-claims-need-the-weekday-control`: a z of -4.99 survived both a
  placebo and a shuffle, and Wednesday turned out to be the second *weakest*
  of five weekdays. The weekday breakdown is here for the same reason.

**A result concentrated in one hour is a result about that hour.** Not
necessarily false - a release window is real - but it is a different and much
narrower claim than the one usually made, and the breakdown is what forces the
narrower claim to be stated.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

#: Hours where FX volatility is highest - the London/New York overlap.
#: Named so a concentration there can be recognised rather than discovered.
OVERLAP_HOURS = (13, 14, 15, 16)


@dataclass(frozen=True, slots=True)
class Cell:
    """One bucket of a breakdown."""

    key: int
    count: int
    mean: float
    total: float

    @property
    def label(self) -> str:
        return f"{self.key:02d}"


@dataclass(frozen=True, slots=True)
class Breakdown:
    """A statistic split by a clock field, and what the split implies."""

    field: str
    cells: tuple[Cell, ...]
    overall_mean: float
    overall_total: float

    @property
    def populated(self) -> tuple[Cell, ...]:
        return tuple(c for c in self.cells if c.count > 0)

    @property
    def concentration(self) -> float:
        """Share of the total contributed by the single best cell.

        The reading that matters. A strategy whose whole result comes from one
        hour has one trade idea, repeated - and its effective sample is the
        number of episodes in that hour, not in the series.
        """
        if not self.overall_total or not self.populated:
            return 0.0
        best = max((c.total for c in self.populated), default=0.0)
        return best / self.overall_total if self.overall_total else 0.0

    @property
    def positive_cells(self) -> int:
        return sum(1 for c in self.populated if c.mean > 0.0)

    @property
    def spread(self) -> bool:
        """Is the result spread across the clock rather than sitting in one cell?

        The bar is deliberately modest: more than half the populated cells
        positive, and no single cell carrying more than 40% of the total. It
        is a check against concentration, not a demand for uniformity - a real
        effect can be stronger at some hours without being only about them.
        """
        populated = self.populated
        if not populated:
            return False
        return self.positive_cells > len(populated) / 2 and self.concentration <= 0.40

    def worst_offender(self) -> Cell | None:
        """The cell carrying the most, for naming in a report."""
        return max(self.populated, key=lambda c: c.total, default=None)

    def lines(self) -> list[str]:
        out = [
            f"by {self.field}: {self.positive_cells}/{len(self.populated)} cells positive, "
            f"top cell carries {self.concentration:.0%}"
        ]
        offender = self.worst_offender()
        if offender is not None:
            out.append(
                f"  heaviest {self.field} {offender.label}: {offender.count} obs, "
                f"mean {offender.mean:+.5f}"
            )
            if self.field == "hour" and offender.key in OVERLAP_HOURS:
                out.append(
                    "  that is the London/New York overlap, where FX volatility runs "
                    "about three times its quiet level - a result sitting there may be "
                    "reading the clock"
                )
        return out


def by_clock(stamps: Sequence[float], values: Sequence[float], *, field: str = "hour") -> Breakdown:
    """Split `values` by the UTC hour or weekday of their stamps.

    Epoch seconds in, because that is what the bus and the store carry. The
    stamps must be the *event's* time rather than the moment it was recorded:
    a delivery delayed by a retry would otherwise land in the wrong cell, which
    is exactly the kind of error this function exists to catch elsewhere.
    """
    if len(stamps) != len(values):
        raise ValueError(f"{len(stamps)} stamps and {len(values)} values")
    if field not in ("hour", "weekday"):
        raise ValueError(f"field must be hour or weekday, got {field!r}")
    size = 24 if field == "hour" else 7
    counts = [0] * size
    totals = [0.0] * size
    for stamp, value in zip(stamps, values, strict=True):
        when = datetime.fromtimestamp(stamp, tz=UTC)
        key = when.hour if field == "hour" else when.weekday()
        counts[key] += 1
        totals[key] += value
    cells = tuple(
        Cell(
            key=key,
            count=counts[key],
            mean=(totals[key] / counts[key]) if counts[key] else 0.0,
            total=totals[key],
        )
        for key in range(size)
    )
    n = len(values)
    return Breakdown(
        field=field,
        cells=cells,
        overall_mean=(sum(values) / n) if n else 0.0,
        overall_total=sum(values),
    )


def concentration_penalty(breakdown: Breakdown) -> float:
    """How much to shrink an effective sample size for concentration.

    A result where one hour carries everything has that hour's episode count
    as its real sample, not the series'. Returns the fraction of the sample
    that should be believed - `1.0` when the result is spread, falling towards
    the single cell's share when it is not.

    **This is the link between the breakdown and the selection statistics.**
    `overlapping-outcome-windows-leak` cost 0.79 against a truth of 0.51 by
    counting one event as many; concentration is the same error wearing a
    clock, and feeding this into `effective_trials` or an episode count is how
    it stops being free.
    """
    if not breakdown.populated:
        return 0.0
    share = breakdown.concentration
    if share <= 0.0:
        return 1.0
    # Even spread over k cells gives 1/k each, so compare against that.
    even = 1.0 / len(breakdown.populated)
    return min(1.0, even / share) if share > even else 1.0


def effective_observations(breakdown: Breakdown) -> float:
    """The sample size a concentrated result actually has."""
    total = sum(c.count for c in breakdown.populated)
    return total * concentration_penalty(breakdown)


def stable_across(breakdown: Breakdown, *, minimum_cells: int = 6) -> tuple[bool, str]:
    """Is this result spread across the clock, and if not, where does it sit?

    `minimum_cells` guards the other failure: a breakdown over two populated
    hours can look perfectly spread while being about two hours.
    `pool-events-before-a-per-feed-guard` is the neighbouring lesson, where a
    min-events guard dropped 141 of 146 feeds and made 0.9 sigma look like 4.8.
    """
    populated = breakdown.populated
    if len(populated) < minimum_cells:
        return False, (
            f"only {len(populated)} {breakdown.field} cells have observations, under "
            f"{minimum_cells} - too few to tell spread from concentration"
        )
    if not breakdown.spread:
        offender = breakdown.worst_offender()
        where = offender.label if offender else "?"
        return False, (
            f"concentrated: {breakdown.field} {where} carries "
            f"{breakdown.concentration:.0%} of the total, and "
            f"{breakdown.positive_cells} of {len(populated)} cells are positive"
        )
    return True, (
        f"spread: {breakdown.positive_cells}/{len(populated)} {breakdown.field} cells "
        f"positive, top cell {breakdown.concentration:.0%}"
    )


def sharpe_by_cell(breakdown: Breakdown) -> dict[str, float]:
    """A crude per-cell Sharpe, for the report.

    Crude because a cell's standard deviation is not carried - this is
    `mean * sqrt(count)`, which ranks cells correctly without claiming to be
    a Sharpe. Named so nobody reads it as one.
    """
    return {c.label: c.mean * math.sqrt(c.count) for c in breakdown.populated if c.count > 1}
