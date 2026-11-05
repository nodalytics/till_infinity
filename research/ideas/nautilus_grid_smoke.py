"""Does the chain run at all, and does a cell repeat itself?

Four things this has to establish before the grid is worth launching, each one
a defect this desk has already paid for.

1. **Bars reach the strategy and orders reach the venue.** Counted at every
   stage - bars, warm, signals, sized, orders, trades - so a zero says where it
   died rather than that the rule declined.
2. **A count of zero beside a non-zero P&L is a reporting bug.** Both are read
   here and disagreement is a failure, not a result.
3. **Two identical cells in one process agree.** Any sweep whose cells share
   state passes its first cell and silently zeroes the rest; `leaf_sweep.py`
   placed 18 orders on cell one and 0 on cell two over identical data.
4. **The indicator snapshot is the previous bar's.** Nautilus updates a
   registered indicator before `on_bar`, so an unsnapshotted `donchian.upper`
   is already this bar's high and a breakout rule can never fire. A rule that
   fires zero times would otherwise read as a market with no breakouts.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

OUT = Path(os.environ.get("GRID_OUT", Path.home() / "till_infinity" / "out" / "grid-smoke"))


def main() -> None:
    os.environ.setdefault("BACKTEST_BALANCE", "100000")
    from nautilus_trader.backtest.node import BacktestNode

    from nautilus_grid import cell_config
    from till_infinity.node.backtest import described

    instrument = os.environ.get("GRID_SMOKE_ID", "EUR/USD.DERIV")
    print(f"venue: {described()}")
    print(f"catalogue: {os.environ.get('CORPUS_DIR', '(default)')}")
    OUT.mkdir(parents=True, exist_ok=True)

    rules = (
        ("ema_cross", 10),
        ("donchian_break", 20),
        ("rsi_revert", 14),
        ("macd_signal", 12),
        ("bb_revert", 20),
        ("keltner_break", 20),
    )
    for rule, param in rules:
        for attempt in (1, 2):
            out = OUT / f"{rule}-{param}-{attempt}.json"
            results = BacktestNode(
                configs=[cell_config(instrument, rule, param, "base", str(out))]
            ).run()
            found = results[0]
            pnl = 0.0
            for stats in (getattr(found, "stats_pnls", None) or {}).values():
                if isinstance(stats, dict):
                    pnl += float(stats.get("PnL (total)", 0.0) or 0.0)
            written = json.loads(out.read_text()) if out.exists() else {"counts": {}, "trades": []}
            counts = written["counts"]
            orders = int(getattr(found, "total_orders", 0) or 0)
            flag = ""
            if orders == 0 and pnl != 0.0:
                flag = "  <- REPORTING BUG: 0 orders beside a non-zero P&L"
            print(
                f"{rule:16s} p{param:<3d} try{attempt}  "
                f"bars {counts.get('bars', 0):6d} warm {counts.get('warm', 0):6d} "
                f"sig {counts.get('signals', 0):5d} gate {counts.get('gated', 0):4d} "
                f"sized {counts.get('sized', 0):5d} unsized {counts.get('unsized', 0):4d} "
                f"trades {counts.get('trades', 0):5d}  "
                f"result.orders {orders:5d} pnl {pnl:+10.2f}{flag}",
                flush=True,
            )
            if counts.get("notes"):
                print(f"    notes: {counts['notes'][:3]}")

        first = json.loads((OUT / f"{rule}-{param}-1.json").read_text())
        second = json.loads((OUT / f"{rule}-{param}-2.json").read_text())
        same = first["trades"] == second["trades"]
        print(f"    repeatable: {same}" + ("" if same else "   <- CELLS SHARE STATE"))


if __name__ == "__main__":
    main()
