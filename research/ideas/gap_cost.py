"""The weekend gap, with the Sunday spread attached.

`mt5-ideas.md` found the one idea of twelve that beats a placebo: FX weekend
gaps fill at 0.856 within a day against a matched placebo at 0.611. The next
question is not statistical. This desk has already paid for the lesson once -
good fills on the up/down book and **-98%** - so a fill rate is not an edge
until the cost is in the same table.

## What the trade actually pays

Fading a gap means entering at the Sunday open and targeting Friday's close, so
the gross is the **gap itself** and the cost is a **round trip** - the spread
paid getting in and the spread paid getting out. The Sunday open is the widest
spread of the week, which is exactly when this trade has to be entered.

So three numbers decide it:

1. The Sunday spread against the week's own median - the multiple.
2. The share of gaps whose size exceeds the round trip.
3. The realised net, which needs the **unfilled** gaps too. A fill rate of 0.86
   says nothing about what the other 0.14 cost, and they are the ones that ran.

The third is the only one that answers the question, so it is computed as the
move toward Friday's close over the window, minus the round trip, averaged over
**every** gap including the ones that went the wrong way.

`spread` is in **points**, not price: dividing by the wrong constant once gave
EURUSD a 476% round trip and reordered every instrument by cost. A JPY cross
divides by 100 and everything else by 10,000.
"""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
ROOT = HERE.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from level_signatures import SEED  # noqa: E402
from screen import load  # noqa: E402

PAIRS = tuple(
    os.environ.get(
        "PAIRS", "EURUSD,GBPUSD,USDJPY,XAUUSD,AUDUSD,USDCAD,EURJPY,GBPJPY,EURGBP,USDCHF"
    ).split(",")
)
HOURS = tuple(int(k) for k in os.environ.get("HOURS", "24,48").split(","))
LEAST_GAP = float(os.environ.get("LEAST_GAP", "0.5"))


def points(name: str) -> float:
    """Points per price unit. A JPY cross quotes to three decimals."""
    if name.endswith("JPY"):
        return 100.0
    if name.startswith("XAU"):
        return 100.0
    if name.startswith("XAG"):
        return 1000.0
    return 10000.0


def gaps_with_cost(bars, name: str) -> list[dict]:
    when, o, h, l_, c, s = (
        bars["time"],
        bars["open"],
        bars["high"],
        bars["low"],
        bars["close"],
        bars["spread"],
    )
    scale = points(name)
    breaks = np.flatnonzero(np.diff(when) > 12 * 3600) + 1
    out: list[dict] = []
    for at in breaks:
        if at < 200 or at + max(HOURS) + 2 >= len(c):
            continue
        before = slice(at - 200, at)
        typical = float(np.median(h[before] - l_[before]))
        weekday_spread = float(np.median(s[before])) / scale
        friday = float(c[at - 1])
        sunday = float(o[at])
        gap = sunday - friday
        if not (typical > 0 and friday > 0) or abs(gap) < LEAST_GAP * typical:
            continue
        sunday_spread = float(s[at]) / scale
        row = {
            "feed": name,
            "gap_price": abs(gap),
            "gap_typical": abs(gap) / typical,
            "sunday_spread": sunday_spread,
            "weekday_spread": weekday_spread,
            "multiple": sunday_spread / weekday_spread if weekday_spread > 0 else float("nan"),
        }
        for hours in HOURS:
            window = slice(at + 1, at + 1 + hours)
            # The fade: short a gap up, long a gap down, targeting Friday's
            # close. Exit at the target if touched, else mark at the window end.
            if gap > 0:
                hit = float(l_[window].min()) <= friday
                gross = abs(gap) if hit else (sunday - float(c[at + hours]))
            else:
                hit = float(h[window].max()) >= friday
                gross = abs(gap) if hit else (float(c[at + hours]) - sunday)
            # A round trip: in at the Sunday spread, out at the weekday one.
            cost = sunday_spread + weekday_spread
            row[f"hit_{hours}"] = 1.0 if hit else 0.0
            row[f"gross_{hours}"] = gross
            row[f"net_{hours}"] = gross - cost
            row[f"pays_{hours}"] = 1.0 if abs(gap) > cost else 0.0
        out.append(row)
    return out


def main() -> None:
    _ = np.random.default_rng(SEED)
    rows: list[dict] = []
    for name in PAIRS:
        bars = load(name, "1h")
        if bars is None:
            continue
        rows += gaps_with_cost(bars, name)
    if len(rows) < 50:
        print(f"{len(rows)} gaps, too few")
        return
    print(f"{len(rows):,} weekend gaps across {len({r['feed'] for r in rows})} pairs\n")

    print("THE SUNDAY SPREAD AGAINST THE WEEK'S OWN MEDIAN")
    print(f"  {'pair':<10}{'gaps':>6}{'weekday':>10}{'sunday':>10}{'multiple':>10}{'gap size':>10}")
    for name in sorted({r["feed"] for r in rows}):
        got = [r for r in rows if r["feed"] == name]
        print(
            f"  {name:<10}{len(got):>6}"
            f"{float(np.median([r['weekday_spread'] for r in got])):>10.6f}"
            f"{float(np.median([r['sunday_spread'] for r in got])):>10.6f}"
            f"{float(np.median([r['multiple'] for r in got])):>10.2f}"
            f"{float(np.median([r['gap_price'] for r in got])):>10.6f}"
        )
    print(
        f"\n  pooled median multiple "
        f"{float(np.median([r['multiple'] for r in rows if math.isfinite(r['multiple'])])):.2f}x"
    )

    print("\nDOES THE GAP COVER THE ROUND TRIP, AND WHAT DOES THE FADE NET")
    print(
        f"  {'window':<8}{'hit rate':>10}{'pays cost':>11}{'mean gross':>12}{'mean net':>11}{'net > 0':>9}"
    )
    for hours in HOURS:
        hit = float(np.mean([r[f"hit_{hours}"] for r in rows]))
        pays = float(np.mean([r[f"pays_{hours}"] for r in rows]))
        gross = float(np.mean([r[f"gross_{hours}"] for r in rows]))
        net = float(np.mean([r[f"net_{hours}"] for r in rows]))
        won = float(np.mean([1.0 if r[f"net_{hours}"] > 0 else 0.0 for r in rows]))
        print(
            f"  {str(hours) + 'h':<8}{hit:>10.3f}{pays:>11.3f}{gross:>12.6f}{net:>11.6f}{won:>9.3f}"
        )
    print(
        "\n  `mean gross` averages the realised move toward Friday's close over\n"
        "  **every** gap, including the ones that never filled - which is where a\n"
        "  fill rate of 0.86 hides its losses. `mean net` is that minus the round\n"
        "  trip, so it is the number the trade would have earned."
    )

    print("\nBY GAP SIZE - the edge has to survive the cost at the size it occurs")
    print(f"  {'size':<10}{'n':>6}{'hit 48h':>9}{'mean net 48h':>14}{'net > 0':>9}")
    for lo, hi in ((0.5, 1.0), (1.0, 2.0), (2.0, 4.0), (4.0, 99.0)):
        got = [r for r in rows if lo <= r["gap_typical"] < hi]
        if len(got) < 30:
            continue
        span = f"{lo:g}-{hi:g}" if hi < 90 else f"{lo:g}+"
        print(
            f"  {span:<10}{len(got):>6}"
            f"{float(np.mean([r['hit_48'] for r in got])):>9.3f}"
            f"{float(np.mean([r['net_48'] for r in got])):>14.6f}"
            f"{float(np.mean([1.0 if r['net_48'] > 0 else 0.0 for r in got])):>9.3f}"
        )


if __name__ == "__main__":
    main()
