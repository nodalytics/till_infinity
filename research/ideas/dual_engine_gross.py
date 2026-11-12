"""Gross against net on the same bars: is any of this a cost problem?

Every arm of the dual-engine rule measured so far has lost, and the standing
suspicion was that the round trip was eating it. This runs each structure
timeframe twice on identical bars - once at the broker's own recorded spread
and once at **zero** - so the question stops being an inference.

It is not a cost problem. See `research/docs/dual-engine-confluence.md`.

Run it as `uv run python research/ideas/dual_engine_gross.py`, after building
both catalogues with `mt5_catalogue.py` (the second with `--costless`).
"""

import sys
from pathlib import Path
sys.path.insert(0, "research/ideas")
from dual_engine_grid import Cell, load_all, measure, run_cell, span_days

SPEC = "5-MINUTE-LAST-EXTERNAL"
ARMS = {"net": Path.home() / "till-data" / "mt5",
        "gross": Path.home() / "till-data" / "mt5-costless"}
STRUCTS = (("4H", 48), ("1H", 12), ("15m", 3), ("1D", 288))

loaded = {}
for name, cat in ARMS.items():
    if cat.exists():
        loaded[name] = load_all(cat, SPEC)

print(f"{'struct':<6} {'arm':<6} {'side':<5} {'n':>5} {'R/trade':>9} {'se':>6} "
      f"{'gross $':>11} {'sharpe':>7} {'maxdd':>7}")
print("-" * 76)
for label, span in STRUCTS:
    for arm, (instruments, data) in loaded.items():
        days = span_days(data)
        for flip in (False, True):
            cell = Cell(0.015, 0.85, 0.01, flip, bars_per_structure=span,
                        tp_trigger_r=2.0, bar_spec=SPEC)
            trades = run_cell(instruments, data, cell)
            m = measure(cell, trades, days)
            money = sum(t.profit for t in trades)
            print(f"{label:<6} {arm:<6} {'flip' if flip else 'rule':<5} {m.trades:>5} "
                  f"{m.reward:>+9.3f} {m.reward_se:>6.3f} {money:>+11,.0f} "
                  f"{m.sharpe:>+7.2f} {m.drawdown:>6.1%}", flush=True)
