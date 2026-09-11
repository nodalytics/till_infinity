"""Comparisons that cut within strata by default, and say when it matters.

## Why this is mechanical and not a rule

Simpson's paradox has reversed a pooled figure on this project **four times**:

* **`aligning.md`** - pooled said trading against a live higher timeframe costs
  nothing. Conditioned: 2.5-4.1 points at 3m and 5m, nothing at 1m, and it
  **reverses** at 15m.
* **`forecasting.md`** - three clean tables, all three defects.
* **`trapping.md`** - trap-from-break predicted at AUC 0.6187 pooled and 0.567
  within a timeframe. The rest was the timeframe.
* **`instruments.md`** - Boom 1000 was the worst instrument at -0.595R. 36 of
  its 48 closes were one strategy, at -0.595R: **the same number, because that
  strategy was the sample.**

The last is the clearest: an entire investigation, three measurements and two
replays, ran on a composition rather than an instrument.

Each time the lesson was written down. Each time the next cut was pooled again.
**A rule that is correct and does not survive contact with a new question needs
to be mechanical**, because the person writing a cut never believes theirs is
the one that will reverse.

## What it reports

The pooled table, the same cut within each stratum, and - the actual product -
a warning naming the strata whose ordering disagrees with the pooled one.

The check is **ordinal**: does the ranking hold. Not whether a reversal is
statistically significant, because the failure that has happened four times is
ordinal, and a significance test on top invites arguing with the warning rather
than reading the strata.

## `min_n` reports rather than filters

A stratum below `min_n` is shown with its count and excluded from the reversal
check. `sweep-aware` at n=4 on Boom is exactly such a stratum **and it carried
the finding** - hiding it reproduces the original error with an extra step,
while counting it as a reversal makes every noisy cell shout.
"""

from __future__ import annotations

import statistics as st
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .liveness import assert_alive

#: The two that have caused every reversal recorded here.
WITHIN = ("strategy", "interval")


@dataclass(slots=True)
class Cell:
    """One bucket's numbers."""

    n: int
    mean: float
    median: float
    positive: float


@dataclass(slots=True)
class Stratum:
    """One slice, and how its buckets ranked inside it."""

    name: str
    n: int
    buckets: dict[str, Cell]
    thin: bool = False

    @property
    def best(self) -> str | None:
        return max(self.buckets, key=lambda k: self.buckets[k].mean) if self.buckets else None

    @property
    def worst(self) -> str | None:
        return min(self.buckets, key=lambda k: self.buckets[k].mean) if self.buckets else None

    @property
    def gap(self) -> float:
        if len(self.buckets) < 2:
            return 0.0
        means = [c.mean for c in self.buckets.values()]
        return max(means) - min(means)


@dataclass(slots=True)
class Comparison:
    """A pooled cut, the same cut per stratum, and the disagreements."""

    value: str
    buckets: dict[str, Cell]
    strata: dict[str, Stratum] = field(default_factory=dict)
    reversals: list[tuple[str, str]] = field(default_factory=list)

    @property
    def pooled_best(self) -> str | None:
        return max(self.buckets, key=lambda k: self.buckets[k].mean) if self.buckets else None

    @property
    def pooled_worst(self) -> str | None:
        return min(self.buckets, key=lambda k: self.buckets[k].mean) if self.buckets else None

    def render(self) -> str:
        out = [
            f"  {'bucket':>18s} {'n':>7s} {'mean':>9s} {'median':>9s} {'positive':>9s}",
        ]
        for name in sorted(self.buckets, key=lambda k: -self.buckets[k].mean):
            cell = self.buckets[name]
            out.append(
                f"  {name:>18s} {cell.n:7d} {cell.mean:+9.3f} {cell.median:+9.3f} "
                f"{cell.positive:8.1%}"
            )
        out.append(f"  pooled  best={self.pooled_best}  worst={self.pooled_worst}")

        for name, stratum in sorted(self.strata.items()):
            note = "  (below min_n, not counted)" if stratum.thin else ""
            flag = "   ** REVERSED **" if any(n == name for n, _ in self.reversals) else ""
            out.append(
                f"    {name:<22s} n={stratum.n:<6d} best={stratum.best} "
                f"worst={stratum.worst}  gap {stratum.gap:6.3f}{note}{flag}"
            )

        if self.reversals:
            counted = sum(1 for s in self.strata.values() if not s.thin)
            out.append("")
            out.append(
                f"  ** the pooled ordering does not hold in {len(self.reversals)} of "
                f"{counted} strata. The pooled figure is a composition of populations"
            )
            out.append("     that disagree; read the strata, not the total.")
        return "\n".join(out)


def _cells(rows: Sequence[Mapping[str, Any]], value: str, bucket: Callable) -> dict[str, Cell]:
    grouped: dict[str, list[float]] = {}
    for row in rows:
        got = row.get(value)
        if isinstance(got, int | float) and not isinstance(got, bool):
            grouped.setdefault(str(bucket(row)), []).append(float(got))
    return {
        name: Cell(
            n=len(xs),
            mean=st.fmean(xs),
            median=st.median(xs),
            positive=sum(1 for x in xs if x > 0) / len(xs),
        )
        for name, xs in grouped.items()
        if xs
    }


def compare(
    rows: Sequence[Mapping[str, Any]],
    *,
    value: str,
    bucket: Callable[[Mapping[str, Any]], str] | str,
    within: Sequence[str] = WITHIN,
    min_n: int = 100,
) -> Comparison:
    """Compare `value` across buckets, pooled and within each stratum.

    `bucket` is a key or a function of the row. `within` names the stratum keys;
    empty means pooled only, which is the thing this exists to discourage and is
    still allowed, because a caller who has thought about it should not have to
    fight the helper.

    Raises if `value` carries no information - a comparison of a constant is a
    flat table somebody will then try to explain. See `liveness`.
    """
    assert_alive(rows, value)
    read = bucket if callable(bucket) else (lambda r, k=bucket: str(r.get(k, "unknown")))
    got = Comparison(value=value, buckets=_cells(rows, value, read))

    for key in within:
        grouped: dict[str, list[Mapping[str, Any]]] = {}
        for row in rows:
            # An absent key groups under a name rather than vanishing. A row
            # silently dropped from a comparison is the failure this prevents.
            grouped.setdefault(str(row.get(key, "unknown")), []).append(row)
        for name, part in grouped.items():
            stratum = Stratum(
                name=name,
                n=len(part),
                buckets=_cells(part, value, read),
                thin=len(part) < min_n,
            )
            got.strata[name] = stratum
            if stratum.thin or len(stratum.buckets) < 2:
                continue
            if stratum.best != got.pooled_best or stratum.worst != got.pooled_worst:
                got.reversals.append((name, key))
    return got
