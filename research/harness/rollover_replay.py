"""Re-measure the rollover mask: FX history through the production engine, mask on and off.

`rollover.md` found the FX 21:00 UTC spread spike resolving touches in production; `structures/
rollover.py` now masks it. Rather than wait for production to accumulate, this replays the lab's
FX bars through the production `Engine` twice (one process each, `STRUCTURES_ROLLOVER_MASK=1` and
`=0`) and records every resolved touch:

  the hour it resolved     does the 21:00 bulge disappear with the mask on?
  its outcome              does the trap share at 21:00 fall back to the other hours'?
  hold rate per timeframe  rejects / (rejects + breaks + traps), the level record's own measure,
                           read off the resolved outcomes per level interval, with and without

Run on the lab, one process per setting, then PART=report:
  STRUCTURES_ROLLOVER_MASK=1 SEQLAB=$HOME/till_infinity/data/seqlab python research/harness/rollover_replay.py
  STRUCTURES_ROLLOVER_MASK=0 ...
"""
from __future__ import annotations

import heapq
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import spikerisk

from till_infinity.structures import rollover as ro
from till_infinity.structures.engine import Engine

PART = os.environ.get("PART", "run")
OUT = Path(os.environ.get("OUT", ".data/rollover_replay"))
START = pd.Timestamp(os.environ.get("START", "2025-06-01"), tz="UTC").timestamp()
SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "EURJPY", "GBPJPY", "EURGBP", "NZDUSD",
           "USDCHF"]
INTERVALS = ("15m", "1h")


def bars_of(sym, iv, df):
    """A function, so `sym` and `iv` bind now."""
    for t, o, h, lo, c in zip(df["ts"].to_numpy(), df["open"].to_numpy(), df["high"].to_numpy(),
                              df["low"].to_numpy(), df["close"].to_numpy(), strict=True):
        yield {"feed": sym.lower(), "venue": "SEQLAB", "interval": iv, "time": int(t),
               "open": float(o), "high": float(h), "low": float(lo), "close": float(c)}


def run() -> None:
    series = []
    for sym in SYMBOLS:
        for iv in INTERVALS:
            try:
                df = spikerisk.load(None, sym, "SEQLAB", iv)
            except (ValueError, FileNotFoundError) as exc:
                print(f"  skip {sym} {iv}: {str(exc)[:60]}", flush=True)
                continue
            series.append(bars_of(sym, iv, df[df["ts"] >= START]))
    engine = Engine(intervals=INTERVALS)
    engine.consensus.single_source = frozenset(s.lower() for s in SYMBOLS)
    rows = []
    for n, bar in enumerate(heapq.merge(*series, key=lambda b: (b["time"], b["interval"]))):
        engine.observe_bar(bar)
        for level, touch in engine.drain_resolved():
            rows.append({"feed": touch.feed, "interval": level.interval, "time": float(touch.resolved),
                         "outcome": str(touch.outcome).split(".")[-1].lower()})
        if n % 100_000 == 0:
            print(f"  {n:,} bars, {len(rows):,} resolved", flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    name = "on" if ro.ENABLED else "off"
    (OUT / f"{name}.json").write_text(json.dumps(rows))
    print(f"mask {name}: {len(rows):,} resolved touches written", flush=True)


def report() -> None:
    frames = {}
    for name in ("off", "on"):
        path = OUT / f"{name}.json"
        if path.exists():
            df = pd.DataFrame(json.loads(path.read_text()))
            t = pd.to_datetime(df["time"], unit="s")
            df["hour"], df["weekday"] = t.dt.hour, t.dt.weekday
            frames[name] = df[df["weekday"] < 5]
    print("FX, weekdays: share of resolved touches by UTC hour, and the trap share (mask off | on)")
    for h in range(24):
        cells = []
        for name in ("off", "on"):
            df = frames.get(name)
            if df is None:
                cells.append("   -   ")
                continue
            g = df[df["hour"] == h]
            cells.append(f"{len(g) / len(df):5.1%} trap {np.mean(g['outcome'] == 'trap'):5.1%}")
        print(f"  {h:02d}  " + "  |  ".join(cells))
    print("\nShare resolved in 20-22 UTC (even spread 12.5%), and hold rate = rejects / (rejects + "
          "breaks + traps), per level interval")
    for iv in sorted({i for df in frames.values() for i in df["interval"].unique()}):
        out = []
        for name in ("off", "on"):
            df = frames.get(name)
            if df is None:
                continue
            g = df[df["interval"] == iv]
            o = g["outcome"]
            decisive = o.isin(("reject", "break", "trap")).sum()
            hold = (o == "reject").sum() / decisive if decisive else float("nan")
            out.append(f"{name}: n={len(g):7,} in 20-22 {g['hour'].isin((20, 21, 22)).mean():5.1%}"
                       f" hold {hold:.3f} trap {np.mean(o == 'trap'):.1%} break {np.mean(o == 'break'):.1%}")
        print(f"  {iv:6s} " + " | ".join(out))


if __name__ == "__main__":
    report() if PART == "report" else run()
