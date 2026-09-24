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
first live sweep, 26% - refusing a zero bid, ask or mark as firmly as a missing one.
Those are precisely the widest spreads, so every number here is computed over the
liquid subset and understates what trading the whole surface would cost.

That the recorder refuses zeros is worth stating here rather than assumed, because
this function is also fed by hand during analysis, where nothing has filtered the
rows first. Hence `cost_fraction` refuses them again.

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

    Three numbers, in three units, each under its own name - because an earlier
    version reported `median_cost * 100` as **volatility points** while its own
    docstring derived them as `cost * mark_iv`. Those differ by 1.9x on real data,
    and `main` printed the same digits under both labels.

    * `median_cost` - a fraction of premium;
    * `cost_percent_of_premium` - the same thing as a percentage, which is what the
      1.89% figure is;
    * `iv_points_needed` - volatility points, the units `mark_iv` is quoted in,
      as `median_cost * median(mark_iv)`. The approximation is the crude local one
      that a relative change in premium of `c` needs a relative change in implied
      volatility of about `c` near the money. It is a scale, not a pricing model,
      and it is `nan` when no row carries a `mark_iv` - because a missing column is
      not a 100.
    """
    nan = float("nan")
    costs: list[float] = []
    ivs: list[float] = []
    for row in rows:
        cost = cost_fraction(
            _as_float(row.get("bid_price")),
            _as_float(row.get("ask_price")),
            _as_float(row.get("mark_price")),
        )
        if cost is None:
            continue
        costs.append(cost)
        # Only from rows that contribute a cost, so the two medians describe the
        # same population.
        iv = _as_float(row.get("mark_iv"))
        if math.isfinite(iv) and iv > 0.0:
            ivs.append(iv)
    if not costs:
        return {
            "n": 0,
            "median_cost": nan,
            "mean_cost": nan,
            "p90_cost": nan,
            "cost_percent_of_premium": nan,
            "iv_points_needed": nan,
        }
    costs.sort()
    median = statistics.median(costs)
    return {
        "n": len(costs),
        "median_cost": median,
        "mean_cost": statistics.fmean(costs),
        "p90_cost": costs[min(len(costs) - 1, int(0.90 * len(costs)))],
        "cost_percent_of_premium": median * 100.0,
        "iv_points_needed": median * statistics.median(ivs) if ivs else nan,
    }
