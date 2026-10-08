"""Do MCFL's DISPLACE_C and structures' `displace` fire on the same bars?

Both claim the same thing in two vocabularies - **two consecutive one-sided
bars** - and they were written in different packages, months apart, by
different routes. If they agree, one should import the other's threshold and
there is one concept. If they do not, the disagreement is the finding, and it
is the same shape as `origins` against `displacement`: magnitude and
one-sidedness agreeing only 59-78% of the time.

They are not obviously the same rule:

  DISPLACE_C  dir BULL, force in (STRONG, DOMINANT), close in Q4.
              `force` is a **rolling grade** - the body against the last
              `PERIOD` bars' bodies - so it is relative and adapts.
  displace    body >= PUSH_BODY of the bar's own range, twice, one colour.
              **Absolute**: the same bar is a displacement in any regime.

One is "big for lately", the other "decisive in itself", and those come apart
exactly where a regime changes. Reported per instrument and timeframe.

  MT5BT_DB=... python research/ideas/displace_vs_displace_c.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
for q in (HERE, HERE.parent, HERE.parents[1]):
    sys.path.insert(0, str(q))

from till_infinity.mcfl import events as mev  # noqa: E402
from till_infinity.mcfl import tokens as mtok  # noqa: E402
from till_infinity.structures.vol.volatility import Volatility  # noqa: E402

#: `drawing/displacement.py`'s rule, restated here rather than imported.
#: The research machine's checkout is older than the module and this script
#: is about *what the rule is*, so stating it is clearer than importing it
#: and quieter than a version skew.
PUSH_BODY, PUSH_N = 0.65, 2
ORIGIN_BODY_MIN, ORIGIN_BODY_MAX = 0.10, 0.60
MIN_LEG_VOL = 1.5

INTERVALS = os.environ.get("INTERVALS", "1h,4h,1d").split(",")


def mcfl_bars(df) -> set[int]:
    """Index of the **second** bar of every DISPLACE_C run, both sides."""
    bars = mtok.Bars(
        df["ts"].to_numpy(np.int64),
        df["open"].to_numpy(float),
        df["high"].to_numpy(float),
        df["low"].to_numpy(float),
        df["close"].to_numpy(float),
    )
    frames = mtok.frames(bars)
    out: set[int] = set()
    for event in mev.displace_c(frames):
        if event.get("rule") == "RUN":
            out.add(int(event.at))
    return out


def _pushed(o, h, low, c, start: int, run: int, body: float) -> int:
    """`+1`, `-1` or `0`: the direction of a push of `run` bars from `start`."""
    if start + run > len(c):
        return 0
    first = c[start] - o[start]
    side = 1 if first > 0 else -1 if first < 0 else 0
    if side == 0:
        return 0
    for i in range(start, start + run):
        span = h[i] - low[i]
        if span <= 0 or side * (c[i] - o[i]) < body * span:
            return 0
    return side


def structures_bars(df) -> set[int]:
    """Index of the second push bar of every `displace` origin."""
    o = df["open"].to_numpy(float)
    h = df["high"].to_numpy(float)
    low = df["low"].to_numpy(float)
    c = df["close"].to_numpy(float)
    vol = Volatility()
    for price in c:
        vol.update(float(price))
    out: set[int] = set()
    for i in range(len(c) - PUSH_N):
        side = _pushed(o, h, low, c, i + 1, PUSH_N, PUSH_BODY)
        if side == 0:
            continue
        span = h[i] - low[i]
        if span <= 0:
            continue
        bottom, top = (c[i], o[i]) if o[i] > c[i] else (o[i], c[i])
        share = (top - bottom) / span
        if not ORIGIN_BODY_MIN <= share <= ORIGIN_BODY_MAX:
            continue
        line = bottom if side > 0 else top
        reach = h[i + PUSH_N] if side > 0 else low[i + PUSH_N]
        if line <= 0:
            continue
        if vol.units(abs(reach - line) / line * 10_000) < MIN_LEG_VOL:
            continue
        out.add(i + PUSH_N)
    return out


def main() -> None:
    import run as runner
    import survivors

    db = os.environ.get("MT5BT_DB")
    runner.DB = survivors.DB = db
    syms = os.environ.get("SYMBOLS")
    syms = syms.split(",") if syms else [s for s in runner.FAMILY if s not in runner.FRESH]

    rows = []
    for iv in INTERVALS:
        for sym in syms:
            got = survivors.book_for(sym, iv)
            if got is None:
                continue
            df = got[0].bars.reset_index(drop=True)
            if len(df) < 200:
                continue
            a, b = mcfl_bars(df), structures_bars(df)
            both = a & b
            rows.append(
                {
                    "iv": iv,
                    "sym": sym,
                    "bars": len(df),
                    "displace_c": len(a),
                    "displace": len(b),
                    "both": len(both),
                    "jaccard": len(both) / max(len(a | b), 1),
                    "c_covered": len(both) / max(len(a), 1),
                    "s_covered": len(both) / max(len(b), 1),
                }
            )
    d = pd.DataFrame(rows)
    if d.empty:
        print("no bars")
        return
    pd.set_option("display.width", 200)
    print(f"{len(d)} instrument-timeframes\n")
    print("=== per timeframe, summed ===")
    g = d.groupby("iv")[["bars", "displace_c", "displace", "both"]].sum()
    g["jaccard"] = g.both / (g.displace_c + g.displace - g.both)
    g["of DISPLACE_C"] = g.both / g.displace_c
    g["of displace"] = g.both / g.displace
    g["C per 1k bars"] = g.displace_c / g.bars * 1000
    g["s per 1k bars"] = g.displace / g.bars * 1000
    print(g.round(4).to_string())
    print("\n=== the ten least agreeing ===")
    print(d.sort_values("jaccard").head(10).round(4).to_string(index=False))
    out = Path(os.environ.get("OUT", ".data/displace_cmp"))
    out.mkdir(parents=True, exist_ok=True)
    d.to_csv(out / "compare.csv", index=False)
    print(f"\nwritten: {out / 'compare.csv'}")


if __name__ == "__main__":
    main()
