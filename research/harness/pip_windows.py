"""Perceptually important points across window lengths, as data for a chart.

Run from the repository root:

    python research/harness/pip_windows.py --out /tmp/pips.json

Uses the production implementation in `till_infinity/structures/drawing/pips.py` rather than a
fresh one, so what is drawn is what the desk actually sees. That matters for a diagnostic: a
picture of a reimplementation tells you nothing about the system.

## The question a window sweep answers

PIP keeps whichever point sits furthest from the line joining the points already kept, so the
number of points requested sets the scale of what survives. Applied to **different window
lengths** it answers something the single-window version cannot: whether the turns a person
would draw are stable under how much history they are looking at.

A level found on 2000 bars and again on 500 and again on 200 is a level that does not depend on
where the chart happened to start. One that appears only at a single window length is an
artefact of the window.

So the sweep is over two axes:

* **window** - how many of the most recent bars are handed to the algorithm;
* **count** - how many points it is asked to keep.

`count` is also reported per window as a **density** (points per hundred bars), because asking
for 12 points from 200 bars and 12 from 2000 are completely different requests and comparing
them directly is the obvious trap.

## Point-in-time correctness is preserved, and visible

Every point carries `confirmed` from the production code - the timestamp of the bar that
settled it - and the export keeps it, along with whether the point was knowable by the end of
its own window. Trailing swings carry infinity until enough bars follow, so a chart can show
them differently instead of pretending they were always there. **That distinction is the whole
difference between a level someone could have drawn and one only visible in hindsight.**
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE.parent / "training"))

import candles  # noqa: E402

from till_infinity.structures.drawing import pips  # noqa: E402

#: Window lengths in bars, and the point counts to ask of each.
WINDOWS = (120, 300, 800, 2000)
COUNTS = (6, 10, 16, 24)


def series(path: Path, window: int) -> tuple[list[int], list[float], list[dict]]:
    """The last `window` bars as times, closes, and full OHLC for drawing."""
    bars, _repaired = candles.read(path)
    tail = bars[-window:]
    times = [int(row[0]) for row in tail]
    closes = [float(row[4]) for row in tail]
    ohlc = [
        {
            "t": int(row[0]),
            "o": float(row[1]),
            "h": float(row[2]),
            "l": float(row[3]),
            "c": float(row[4]),
        }
        for row in tail
    ]
    return times, closes, ohlc


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("symbols", nargs="*", default=["xauusd", "eurusd", "boom_1000_index"])
    ap.add_argument("--where", default=".secrets/broker-deep")
    ap.add_argument("--interval", default="1h")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    payload: dict = {
        "interval": args.interval,
        "windows": list(WINDOWS),
        "counts": list(COUNTS),
        "instruments": {},
    }

    for symbol in args.symbols:
        found = sorted(Path(args.where).glob(f"{symbol}_{args.interval}_*.csv.gz"))
        if not found:
            print(f"{symbol:<22} no {args.interval} file")
            continue
        entry: dict = {"windows": {}}
        for window in WINDOWS:
            times, closes, ohlc = series(found[0], window)
            if len(closes) < window:
                continue
            last = times[-1]
            runs = {}
            for count in COUNTS:
                got = pips.points(times, closes, count)
                runs[str(count)] = [
                    {
                        "t": p.time,
                        "price": round(p.price, 6),
                        "swing": str(p.swing),
                        "prominence_bps": round(p.prominence_bps, 2),
                        # Was this knowable by the end of its own window?
                        "settled": bool(math.isfinite(p.confirmed) and p.confirmed <= last),
                    }
                    for p in got
                ]
            entry["windows"][str(window)] = {"bars": ohlc, "pips": runs}
            print(
                f"  {symbol:<22}{window:>6} bars  "
                + "  ".join(
                    f"{c}->{len(runs[str(c)])} ({len(runs[str(c)]) * 100 / window:.1f}/100)"
                    for c in COUNTS
                )
            )
        if entry["windows"]:
            payload["instruments"][symbol] = entry

    Path(args.out).write_text(json.dumps(payload))
    size = Path(args.out).stat().st_size
    print(f"\nwrote {args.out}  ({size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
