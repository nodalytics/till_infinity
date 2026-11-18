"""The one cell of the sweep that separated: a 3-day ranking window at 15m.

Everything else in [`rsi-ma-momentum.md`](../docs/rsi-ma-momentum.md) is a
coin. At a **3-day** window on 15m bars, last window's top cells beat last
window's bottom cells in the next window by `+0.0431` to `+0.0762R` over eight
years, while a day-shuffled market reads `-0.0187` to `+0.0075`. That is the
right control structure and the wrong amount of scrutiny so far, so this run
applies the three checks that decide it:

* **disjoint halves** - the recent four years and the four before them, since
  the 2-year smoke test read `+0.1590R` against the 8-year's `+0.0693` and a
  recency gradient that steep is usually a regime;
* **per instrument** - `pooled-medians-invert-subgroups` measured a pooled
  answer agreeing with a claim every subgroup refuted;
* **every `k`** - 1, 3 and 10, because an effect that lives only at one
  selection width is a property of the width.

    ./.secrets/lab.sh run research/ideas/rsi_shortwindow_run.py
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import rsi_walkforward  # noqa: E402

CATALOGUE = os.environ.get("CATALOGUE", "data/mt5-deep")
MARKETS = ("EURUSD", "GBPUSD", "GOLD", "USDJPY", "AUDUSD")


def main() -> None:
    halves = (("recent 4y", "4", "0"), ("the 4y before it", "4", "4"))
    for name, years, before in halves:
        for symbols in (",".join(MARKETS), *MARKETS):
            print("\n" + "=" * 78)
            print(f"@@@ {name}, 15m, 3-day windows, {symbols}")
            print("=" * 78, flush=True)
            sys.argv = [
                "rsi_walkforward.py", "--catalogue", CATALOGUE, "--frames", "15m",
                "--symbols", symbols, "--years", years, "--before", before,
                "--arms", "real,shuffled", "--top", "1,3,10", "--windows", "3",
                "--workers", "10",
            ]
            try:
                rsi_walkforward.main()
            except Exception:
                traceback.print_exc()
            sys.stdout.flush()


if __name__ == "__main__":
    main()
