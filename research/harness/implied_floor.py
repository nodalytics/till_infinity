"""The bar a volatility forecast has to clear on Deribit, from recorded data.

## Why this is its own file, and runs first

The result of phase 0 is a comparison, and a comparison needs a threshold decided
in advance. Every null in `research/docs/` that survived scrutiny had its
detection floor computed before the study; the ones that did not are the ones that
had to be retracted.

## What the cost actually is

`bid_iv` and `ask_iv` are **not** in `get_book_summary_by_currency` - they need one
`get_order_book` call per instrument, and there are 1,050 of them. So cost is taken
in price terms, which is what is paid anyway:

    cost_fraction = ((ask - bid) / 2) / mark

Half the spread, because a single trade crosses half of it. As a fraction of mark,
so it is comparable across strikes whose premiums differ by orders of magnitude.

**This makes phase 0 a weaker test than the ideal one.** The ideal compares our
forecast against `ask_iv` when buying and `bid_iv` when selling. This compares
against `mark_iv` and subtracts a price-terms cost, which is not the same thing,
and the write-up must say so rather than imply a cleaner experiment than was run.

**And the floor it produces is optimistic**, which is the more important caveat.
`deribit.parse_summary` drops any strike with no book at all - 492 of 1,894 on the
first live sweep, 26%. Those are precisely the widest spreads, so every number here
is computed over the liquid subset and understates what trading the whole surface
would cost.

## Reading recorded rows

Everything arrives from `csv.DictReader`, so every value is a string and a dropped
column is `''` rather than `None`. `_as_float` turns all of absent, empty, `None`
and unparseable into `nan`, and `cost_fraction` refuses `nan` - so a missing side
produces no row instead of a free option.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Iterable


def _as_float(value: object) -> float:
    """A float, or `nan`. Never raises, because the caller is reading a CSV."""
    if value is None or value == "":
        return float("nan")
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return float("nan")


def cost_fraction(bid: float, ask: float, mark: float) -> float | None:
    """Half the spread over mark, or `None` when the book cannot say.

    `None` rather than zero throughout. A strike with no book has no cost *that we
    know of*, and recording that as zero is recording a free option. A book whose
    bid and ask touch is different - that is a real zero, and it is returned.
    """
    for value in (bid, ask, mark):
        if value is None or not math.isfinite(value):
            return None
    if mark <= 0.0 or ask < bid:
        return None
    return ((ask - bid) / 2.0) / mark


def floor(rows: Iterable[dict]) -> dict[str, float]:
    """The floor over a recorded surface.

    `iv_points_needed` converts the median cost into volatility points, the units
    `mark_iv` is quoted in, using the crude local approximation that a relative
    change in premium of `c` needs a relative change in implied volatility of about
    `c` near the money. It is a scale, not a pricing model, and it is here so the
    floor can be stated in the same units as the thing it gates.
    """
    costs: list[float] = []
    for row in rows:
        cost = cost_fraction(
            _as_float(row.get("bid_price")),
            _as_float(row.get("ask_price")),
            _as_float(row.get("mark_price")),
        )
        if cost is not None:
            costs.append(cost)
    if not costs:
        nan = float("nan")
        return {
            "n": 0,
            "median_cost": nan,
            "mean_cost": nan,
            "p90_cost": nan,
            "iv_points_needed": nan,
        }
    costs.sort()
    median = statistics.median(costs)
    return {
        "n": len(costs),
        "median_cost": median,
        "mean_cost": statistics.fmean(costs),
        "p90_cost": costs[min(len(costs) - 1, int(0.90 * len(costs)))],
        "iv_points_needed": median * 100.0,
    }
