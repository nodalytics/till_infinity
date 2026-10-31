"""Displacement, and the gaps it leaves behind.

A move that covers ground in few bars is a different event from one that covers
the same ground slowly, and the desk has been describing both with the same
numbers. `speeds` keeps exponential averages of a score, `efficiency` is net
travel over gross, `regression` fits a line - none of them says "price just
*lurched*, and here is how far and how fast".

This module says that, in two readings a chart reader would recognise:

* **Displacement** - the most recent directional leg in the window, signed, in
  volatility units, with the bars it took. Size and speed are reported apart
  because they are different claims: four units over four bars is a run, and
  four units over forty is a drift.
* **Imbalance** - the three-bar gap a fast move leaves, where the middle bar
  travels so far that the wicks either side do not overlap. Reported above and
  below price separately, each with its distance, its width and its age, and
  only while **unfilled** - a gap price has already traded back through is
  history, not a level.

**It gates nothing, and nothing here decides a trade.** The desk's own LRC
break-and-retest study measured the setup these features describe at -0.291R
over 167,501 trades against walks at -0.274R, and its strength terciles - the
closest published thing to `displacement_vol` - differ from the walks by
+0.14R, the one real deviation in that study and still not enough to pay. So
these are published to be scored, exactly as `regression.features` is, and a
rule that reads them should be a separate change with its own measurement.

The sign is carried everywhere it exists. `efficiency` was added unsigned and
the repo's own note on it says the obvious way to trade it would have had the
sign backwards; a displacement without a direction invites the same mistake.

Absent readings are **left out** rather than written as zero. A window with no
unfilled gap has no imbalance, and a zero in that column would read later as
"the gap was here", which is the opposite of the truth.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from .candles import Bar

NAN = float("nan")

#: Bars the readings are taken over. Shorter than the regression's 100: a
#: displacement is a local event and a hundred bars of context would bury the
#: one that just happened under every older one.
SPAN = 40

#: The least a gap must span, in volatility units, before it counts. Without a
#: floor every rounding tick between two bars is an "imbalance" and the count
#: becomes a measure of the tick size.
MIN_GAP_VOL = 0.10


@dataclass(frozen=True, slots=True)
class Gap:
    """One three-bar imbalance, as the far side of the hole it left."""

    #: Index of the middle bar - the one that displaced.
    at: int
    #: +1 when the gap points up (price left a hole above it), -1 down.
    side: int
    #: The edges of the hole, low first.
    low: float
    high: float

    @property
    def size(self) -> float:
        return self.high - self.low

    @property
    def far(self) -> float:
        """The edge price has to clear to be past it."""
        return self.high if self.side > 0 else self.low


def gaps(bars: Sequence[Bar], unit: float = 0.0) -> list[Gap]:
    """Every three-bar imbalance in `bars`, oldest first, unfilled ones only.

    A gap is filled once any later bar trades back inside it, which is checked
    against the whole remainder of the window rather than the next bar alone:
    the question a reader asks is "is that hole still there", not "was it
    skipped once".

    `unit` of zero keeps every gap; a positive one drops those under
    `MIN_GAP_VOL`, which is how a caller with a volatility scale avoids
    counting tick noise.
    """
    out: list[Gap] = []
    floor = MIN_GAP_VOL * unit if unit > 0 else 0.0
    for k in range(1, len(bars) - 1):
        before, after = bars[k - 1], bars[k + 1]
        if after.low > before.high:
            low, high, side = before.high, after.low, 1
        elif after.high < before.low:
            low, high, side = after.high, before.low, -1
        else:
            continue
        if high - low <= floor:
            continue
        # Still open: nothing after the gap has traded back into it.
        rest = bars[k + 2 :]
        if side > 0 and any(b.low < high for b in rest):
            continue
        if side < 0 and any(b.high > low for b in rest):
            continue
        out.append(Gap(at=k, side=side, low=low, high=high))
    return out


def displacement(bars: Sequence[Bar]) -> tuple[float, int, int]:
    """The most recent directional leg: (signed price move, bars, bars since).

    The leg is read between the window's extremes in the order they happened -
    if the low came first the leg is up, if the high came first it is down.
    That is the plainest reading of "the move that got us here" and it needs no
    pivot definition, no lookback parameter and no tuning, which is three fewer
    things to be wrong about.

    `(nan, 0, 0)` when there are not two bars to measure between.
    """
    if len(bars) < 2:
        return NAN, 0, 0
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    hi = max(range(len(bars)), key=lambda i: highs[i])
    lo = min(range(len(bars)), key=lambda i: lows[i])
    if hi == lo:
        return NAN, 0, 0
    if lo < hi:
        move, took, ended = highs[hi] - lows[lo], hi - lo, hi
    else:
        move, took, ended = lows[lo] - highs[hi], lo - hi, lo
    return move, max(1, took), len(bars) - 1 - ended


def features(bars: Sequence[Bar], *, unit: float = 0.0, span: int = SPAN) -> dict[str, float]:
    """The readings as journal features, or `{}` when there is nothing to say.

    `unit` is one volatility unit in price - the same one every distance on a
    decision is quoted in. Without it there is no scale to divide by and the
    numbers would not be comparable between an index at 30,000 and a rate at
    1.12, so the honest answer is an empty dict rather than price-unit figures
    wearing the same names.
    """
    if unit <= 0 or math.isnan(unit) or span < 3 or len(bars) < 3:
        return {}
    window = list(bars[-span:])
    if len(window) < 3:
        return {}
    spot = float(window[-1].close)
    move, took, since = displacement(window)
    out: dict[str, float] = {}
    if not math.isnan(move):
        out["displacement_vol"] = move / unit
        out["displacement_bars"] = float(took)
        out["displacement_speed_vol"] = (move / unit) / float(took)
        out["displacement_age"] = float(since)
    found = gaps(window, unit)
    out["imbalance_n"] = float(len(found))
    above = [g for g in found if g.low >= spot]
    below = [g for g in found if g.high <= spot]
    # Nearest first: the one price would meet, which is the one a target has to
    # clear. The furthest is reported too, because "way past the imbalance" is
    # a different target from "past the first one".
    if above:
        near = min(above, key=lambda g: g.low - spot)
        far = max(above, key=lambda g: g.high - spot)
        out["imbalance_above_vol"] = (near.low - spot) / unit
        out["imbalance_above_far_vol"] = (far.high - spot) / unit
        out["imbalance_above_size_vol"] = near.size / unit
        out["imbalance_above_age"] = float(len(window) - 1 - near.at)
    if below:
        near = min(below, key=lambda g: spot - g.high)
        far = max(below, key=lambda g: spot - g.low)
        out["imbalance_below_vol"] = (spot - near.high) / unit
        out["imbalance_below_far_vol"] = (spot - far.low) / unit
        out["imbalance_below_size_vol"] = near.size / unit
        out["imbalance_below_age"] = float(len(window) - 1 - near.at)
    return out


def card_line(got: dict[str, float]) -> list[str]:
    """The impulse line for an alert card, or nothing when there is no reading."""
    move = got.get("displacement_vol")
    if move is None or math.isnan(float(move)):
        return []
    move = float(move)
    bars_ = int(float(got.get("displacement_bars") or 0))
    age = int(float(got.get("displacement_age") or 0))
    which = "up" if move > 0 else "down"
    line = f"displaced {abs(move):.1f}v {which} over {bars_} bars"
    if age:
        line += f", {age} ago"
    n = got.get("imbalance_n")
    if n is not None and float(n) > 0:
        parts = []
        up, down = got.get("imbalance_above_vol"), got.get("imbalance_below_vol")
        if up is not None and not math.isnan(float(up)):
            parts.append(f"{float(up):.1f}v above")
        if down is not None and not math.isnan(float(down)):
            parts.append(f"{float(down):.1f}v below")
        if parts:
            many = "s" if float(n) > 1 else ""
            line += f" · {int(float(n))} open imbalance{many} ({', '.join(parts)})"
    return [line]
