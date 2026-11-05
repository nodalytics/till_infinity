"""Does the engine charge the catalogue's modelled spread, or its own tick?

The smoke run showed every entry filling **one price increment** from the bar's
close on EUR/USD, where the catalogue's modelled half-spread at the measured
1.0414 bps is six increments. One sample is an anecdote, so this makes it a
measurement: the same feed, the same rule, written twice at spreads two orders
of magnitude apart.

If the fill distance does not move with the spread, `BacktestVenueConfig
.bar_execution` is building the book from bars with a one-tick spread and the
modelled quotes are not the price anything trades at. That is the cost line,
and `exotic-spreads-are-a-whole-bar-range` plus the 421 of 4,830 direction
cells that changed sign on cost alone are why it is settled before the grid
runs rather than after.
"""

from __future__ import annotations

import json
import os
import shutil
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path.home() / "till-data" / "cost-probe"
STORE = Path.home() / "till_infinity" / ".data" / "prices" / "prices.db"


def build(bps: float, where: Path) -> None:
    from till_infinity.node import corpus

    if where.exists():
        shutil.rmtree(where)
    where.mkdir(parents=True, exist_ok=True)
    for row in corpus.write(("eurusd",), venue="DERIV", path=where, store=STORE, spread=bps):
        print(f"  {row}")


def run(where: Path, bps: float) -> None:
    os.environ["CORPUS_DIR"] = str(where)
    os.environ.setdefault("BACKTEST_BALANCE", "100000")
    from nautilus_trader.backtest.node import BacktestNode

    from nautilus_grid import cell_config

    out = ROOT / f"trades-{bps:g}.json"
    BacktestNode(
        configs=[cell_config("EUR/USD.DERIV", "donchian_break", 20, "base", str(out))]
    ).run()
    trades = json.loads(out.read_text())["trades"]
    if not trades:
        print(f"  {bps:g} bps: no trades")
        return
    entry = [abs(t["entry_fill"] - t["entry_ref"]) for t in trades]
    modelled = statistics.fmean(t["entry_ref"] for t in trades) * bps / 1e4 / 2.0
    stops = [t for t in trades if t["reason"] == "stop"]
    print(
        f"  {bps:g} bps: n={len(trades)} median entry slip={statistics.median(entry):.7f} "
        f"(modelled half-spread {modelled:.7f}, one tick 0.0000100)  "
        f"mean R on stops {statistics.fmean(t['r'] for t in stops) if stops else float('nan'):+.3f}"
    )


def main() -> None:
    for bps in (1.0414, 100.0):
        where = ROOT / f"cat-{bps:g}"
        print(f"spread {bps:g} bps")
        build(bps, where)
        run(where, bps)


if __name__ == "__main__":
    main()
