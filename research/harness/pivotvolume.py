"""How many Deriv pivot-level signals production publishes a day: the `deriv_pivot_mfi` shadow
gate's volume.

The journal snapshot (to 2026-09-10) holds no pivot calls because pivot levels were never checked
until 869031d (2026-09-11). This replays the lab's 3m bars for the Deriv indices the gate covers
through the production `Engine` and counts the daily / weekly pivot calls, and the actionable ones,
which are the ones published as signals and so seen by the shadow gate.

  SEQLAB=$HOME/till_infinity/data/seqlab python research/harness/pivotvolume.py
"""
from __future__ import annotations

import collections
import heapq
import os
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import spikerisk

from till_infinity.structures.engine import Engine

START = pd.Timestamp(os.environ.get("START", "2026-06-01"), tz="UTC").timestamp()
SYMBOLS = ([f"Volatility_{v}_Index" for v in (10, 25, 50, 75, 100)]
           + [f"Jump_{v}_Index" for v in (10, 25, 50, 75, 100)]
           + ["Boom_500_Index", "Boom_1000_Index", "Crash_500_Index", "Crash_1000_Index",
              "Step_Index"])


def bars_of(sym, df):
    for t, o, h, lo, c in zip(df["ts"], df["open"], df["high"], df["low"], df["close"], strict=True):
        yield {"feed": sym.lower(), "venue": "SEQLAB", "interval": "3m", "time": int(t),
               "open": float(o), "high": float(h), "low": float(lo), "close": float(c)}


def main() -> None:
    streams, feeds = [], []
    for sym in SYMBOLS:
        try:
            df = spikerisk.load(None, sym, "SEQLAB", "3m")
        except (ValueError, FileNotFoundError):
            continue
        streams.append(bars_of(sym, df[df["ts"] >= START]))
        feeds.append(sym.lower())
    engine = Engine()
    engine.consensus.single_source = frozenset(feeds)
    calls, actionable = collections.Counter(), collections.Counter()
    first = last = None
    for bar in heapq.merge(*streams, key=lambda b: b["time"]):
        first = first or bar["time"]
        last = bar["time"]
        for call in engine.observe_bar(bar):
            if call.interval in ("daily", "weekly"):
                calls[call.interval] += 1
                if call.inference.actionable:
                    actionable[call.interval] += 1
        engine.drain_resolved()
    days = (last - first) / 86_400 if first and last else 0.0
    total = sum(actionable.values())
    print(f"{len(feeds)} Deriv feeds, {days:.0f} days of 3m bars")
    print(f"pivot calls {dict(calls)} ({sum(calls.values()) / max(days, 1):.1f}/day)")
    print(f"actionable (published) {dict(actionable)} ({total / max(days, 1):.1f}/day across feeds)")
    per_day = total / max(days, 1)
    if per_day:
        print(f"days to 200 settled gated trades at the gate's 10% pass rate: {200 / (per_day * 0.10):.0f}")


if __name__ == "__main__":
    main()
