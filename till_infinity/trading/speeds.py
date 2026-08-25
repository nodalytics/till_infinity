"""Three exponential averages of one series, and whether they agree.

From [score.md](../../docs/score.md) §2, which keeps three EWMAs of its score
and treats their agreement as the confidence: "the fast line is what is
happening, the slow line is the context". Half-lives are in observations rather
than bars, because a strategy sees signals as they are published rather than
one per bar.

**What used to be in this module, and why it is not.** An earlier version of
this file also held a rolling-quantile gate — take the top decile of each
instrument's own recent `|edge|` rather than a fixed threshold — on the
strength of score.md §3's argument that a constant is a claim about a
distribution nobody has measured.

[edge.md](../../docs/edge.md) had already measured it, on 10,483 call-outcome
pairs, and the rolling quantile lost to the constant that passes exactly the
same volume by four to ten points of direction in all four comparisons. The
reason is specific and it is not about the instinct being lazy:

> score.md's thresholds are on quantities in instrument-specific units, where a
> constant cannot mean the same thing on gold and EURUSD and a quantile is the
> only honest form. `edge` is *already* scale-free: it is a difference of two
> probabilities, and 0.11 means the same thing everywhere by construction.
> Normalising it per cell therefore destroys the comparability it already had.

That document closes with "do not build the rolling quantile, and record why,
because the instinct will recur". It recurred here, in this module, and this
paragraph is the record.

Nothing else in the level signal wants a per-cell quantile either, because the
whole project is already measured in volatility units for exactly that reason —
so the machinery went rather than waiting for a consumer that has no reason to
appear.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class Speeds:
    """Three speeds over one series per key, and their agreement."""

    half_lives: tuple[float, float, float] = (3.0, 12.0, 48.0)
    _values: dict[str, list[float]] = field(default_factory=dict)
    _seen: dict[str, int] = field(default_factory=dict)

    def observe(self, key: str, value: float) -> tuple[float, float, float]:
        held = self._values.get(key)
        if held is None:
            held = self._values[key] = [value, value, value]
            self._seen[key] = 0
        for index, half_life in enumerate(self.half_lives):
            alpha = 1.0 - 2.0 ** (-1.0 / half_life)
            held[index] += alpha * (value - held[index])
        self._seen[key] = self._seen.get(key, 0) + 1
        return tuple(held)  # type: ignore[return-value]

    def ready(self, key: str) -> bool:
        # The slowest average is meaningless until it has seen about its own
        # half-life; before that it is still mostly its first observation.
        return self._seen.get(key, 0) >= self.half_lives[-1]

    def agree(self, key: str, sign: int) -> bool:
        """True when all three lines point the way `sign` does."""
        held = self._values.get(key)
        if held is None or not self.ready(key):
            return False
        return all((value > 0) == (sign > 0) and value != 0 for value in held)

    def of(self, key: str) -> tuple[float, float, float]:
        held = self._values.get(key)
        return tuple(held) if held else (0.0, 0.0, 0.0)  # type: ignore[return-value]
