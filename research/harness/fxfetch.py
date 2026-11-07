"""Fetch FX legs for the triangle identities, into the lab's own store.

Runs ON the lab and talks to the bridge at localhost. **That box also hosts the
MT5 terminal the live desk's market data and order route go through**, and a
200-symbol sweep has previously starved it and taken the desk down - so this
fetches one symbol at a time, sleeps between, and pings the bridge between
symbols, stopping if it stops answering.

  ./.secrets/lab.sh run research/harness/fxfetch.py \
      TF=M1 BARS=5000 OUT=$HOME/till_infinity/data/fx

`time` comes back as an **ISO 8601 string**, not epoch seconds - `int()` on it
raises, which is how the first attempt at this reported "0 bars served" for a
route that works perfectly.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse as up
import urllib.request as u
from datetime import datetime
from pathlib import Path

import numpy as np

KEY = (Path.home() / ".mt5key").read_text().strip()
BASE = os.environ.get("BRIDGE", "http://localhost:8000") + "/api/v1"
TF = os.environ.get("TF", "M1")
BARS = int(os.environ.get("BARS", "5000"))
OUT = Path(os.environ.get("OUT", str(Path.home() / "till_infinity/data/fx")))
PAUSE = float(os.environ.get("PAUSE", "2.0"))

CCY = ("EUR", "USD", "GBP", "JPY", "CHF", "AUD", "CAD", "NZD")


def get(path: str, **q):
    if q:
        path += "?" + up.urlencode(q)
    req = u.Request(BASE + path, headers={"X-API-Key": KEY})
    with u.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode())


def alive() -> bool:
    try:
        get("/terminal/ping")
        return True
    except Exception:
        return False


def wanted(listed: set[str]) -> list[str]:
    """Every leg of every complete triangle among `CCY`, deduplicated."""
    pairs = {n for n in listed if len(n) == 6 and n[:3] in CCY and n[3:] in CCY}
    legs: set[str] = set()
    for a in CCY:
        for b in CCY:
            if a >= b or "USD" in (a, b):
                continue
            trio = []
            for x, y in ((a, "USD"), (b, "USD"), (a, b)):
                trio.append(f"{x}{y}" if f"{x}{y}" in pairs else
                            (f"{y}{x}" if f"{y}{x}" in pairs else None))
            if all(trio):
                legs.update(trio)
    return sorted(legs)


def main() -> int:
    raw = get("/symbols/")
    listed = raw if isinstance(raw, list) else (raw.get("symbols") or raw.get("data") or [])
    listed = {n if isinstance(n, str) else (n.get("name") or n.get("symbol")) for n in listed}
    listed = {n for n in listed if n}
    #: `SYMBOLS` overrides the triangle construction, because some panels are
    #: a named list rather than a closed set of legs - the COT fade wants the
    #: seven USD majors **and gold**, and gold is in no currency triangle, so
    #: `wanted` cannot produce it. Names not listed by the venue are printed
    #: and skipped rather than silently dropped: a panel that is quietly one
    #: instrument short still produces a table.
    named = [s.strip() for s in os.environ.get("SYMBOLS", "").split(",") if s.strip()]
    if named:
        legs = [s for s in named if s in listed]
        absent = [s for s in named if s not in listed]
        if absent:
            print(f"not listed by the venue, skipped: {', '.join(absent)}")
    else:
        legs = wanted(listed)
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"{len(legs)} legs at {TF} x{BARS} -> {OUT}\n")
    done = 0
    for name in legs:
        if not alive():
            print("  bridge stopped answering - stopping here")
            return 1
        try:
            raw = get("/symbols/rates/pos", symbol=name, timeframe=TF, num_bars=BARS)
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError) as exc:
            print(f"  {name:<9} FAILED {type(exc).__name__}")
            time.sleep(PAUSE)
            continue
        bars = raw if isinstance(raw, list) else (raw.get("rates") or raw.get("data") or [])
        if not bars:
            print(f"  {name:<9} 0 bars")
            time.sleep(PAUSE)
            continue
        #: ISO 8601, not epoch. Parsed rather than cast.
        ts = np.array(
            [datetime.fromisoformat(str(b["time"])).timestamp() for b in bars], dtype=np.float64
        )
        cols = {k: np.array([float(b.get(k) or 0.0) for b in bars]) for k in
                ("open", "high", "low", "close", "spread")}
        vol = np.array([float(b.get("tick_volume") or 0.0) for b in bars])
        #: **The label, not the bridge's code.** `relationship_screen` globs
        #: `*.<FRAME>.npz` with FRAME like `1h`, while the bridge wants `H1`.
        #: Writing the bridge's code produces a cache the screen cannot see,
        #: and it reports "nothing read" rather than an error.
        label = os.environ.get("LABEL", TF)
        np.savez_compressed(OUT / f"{name}.{label}.npz", time=ts, volume=vol, **cols)
        span = (ts[-1] - ts[0]) / 86400.0
        print(f"  {name:<9} {len(bars):6d} bars  {span:6.1f} days  "
              f"median spread {np.median(cols['spread']):.0f} pts")
        done += 1
        time.sleep(PAUSE)
    print(f"\n{done} of {len(legs)} written")
    return 0 if done else 1


if __name__ == "__main__":
    raise SystemExit(main())
