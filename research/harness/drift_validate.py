"""Validate ta_ticks.py's Drift Switch survivors on the sister indices it never saw.

ta_ticks.py (592 cells on real ticks) left four Drift Switch Index 10 trend cells standing, at
+0.02 to +0.09R a trade with coin twins far below. One instrument out of 592 cells is a selection,
so the four cells are re-run unchanged on Drift Switch Index 20 and 30: the same published design,
never used in choosing.

Pre-registered (2026-10-02), before any run.

  cells     15m macd aligned (4h), 5m ema_20_50 aligned (1h), 15m cci aligned (4h), 15m keltner plain
  data      Drift Switch Index 20 and 30 ticks, 2026-02-13 to 2026-10-02 (MT5 bridge)
  method    exactly ta_ticks.py: candles from ticks, ta_battery exits, every fill on ticks, coin twins
  passes    net R > 0, beats its coin with a day-bootstrap p < 0.05 after Benjamini-Hochberg across
            the 8 cells (4 cells x 2 indices), and positive in both halves
"""
from __future__ import annotations

import json
import os
import sys
import zlib
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research" / "harness"))
sys.path.insert(0, str(ROOT / "research"))
sys.path.insert(0, str(ROOT))

import ta_battery as tb  # noqa: E402
import ta_ticks as tt  # noqa: E402

OUT = Path(os.environ.get("OUT", ".data/drift_validate"))
CELLS = [("15m", "macd", "aligned"), ("5m", "ema_20_50", "aligned"), ("15m", "cci", "aligned"), ("15m", "keltner", "plain")]
SYMS = ["Drift Switch Index 20", "Drift Switch Index 30"]


def main() -> None:
    from mt5bt import Book, Costs, bars_from_ticks, load_specs, load_ticks, run

    OUT.mkdir(parents=True, exist_ok=True)
    db = os.environ.get("MT5BT_DB")
    specs = load_specs(db)
    rng = np.random.default_rng(151)
    rows = []
    for sym in SYMS:
        spec = specs[sym]
        ticks = load_ticks(sym, pd.Timestamp("2026-02-13", tz="UTC").timestamp(),
                           pd.Timestamp.now(tz="UTC").timestamp(), db).dropna().drop_duplicates("ts_ms")
        print(f"{sym}: {len(ticks):,} ticks", flush=True)
        candles = {iv: bars_from_ticks(ticks, iv, spec) for iv in ("5m", "15m", "1h", "4h")}
        for iv, rule, var in CELLS:
            book = Book(sym, candles[iv], spec, iv, feed=sym.lower())
            book.ticks = ticks
            sg = tb.signals(book.bars)[rule]
            if var == "aligned":
                up = candles[tt.UP[iv]]
                upsig = tb.signals(Book(sym, up, spec, tt.UP[iv], feed=sym.lower()).bars)[rule]
                pos = np.searchsorted(up["ts"].to_numpy() + tt.tb_seconds(tt.UP[iv]),
                                      book.bars["ts"].to_numpy() + tt.tb_seconds(iv), side="right") - 1
                side = np.where(pos >= 0, tt.state(upsig).to_numpy()[np.clip(pos, 0, None)], 0)
                sg = sg.where(sg.to_numpy() == side, 0)
            mid = book.bars["ts"].iat[len(book.bars) // 2]
            res = {}
            for coin in (False, True):
                od = tb.orders(book.bars, sg, coin, zlib.crc32(f"{sym}{iv}{rule}{var}".encode()))
                t, _ = run(book, None, Costs(fill="ticks"), equity=1e7, risk=0.001, one_per_symbol=True,
                           signals={sym: od})
                res[coin] = t
            s, c = res[False], res[True]
            sd = {d: x["R"].to_numpy() for d, x in s.groupby(s["entry_ts"] // 86400)}
            cd = {d: x["R"].to_numpy() for d, x in c.groupby(c["entry_ts"] // 86400)}
            days = np.array(sorted(set(sd) | set(cd)))
            diffs = []
            for _ in range(1000):
                pick = rng.choice(days, len(days))
                a = np.concatenate([sd[d] for d in pick if d in sd] or [np.array([0.0])])
                b = np.concatenate([cd[d] for d in pick if d in cd] or [np.array([0.0])])
                diffs.append(a.mean() - b.mean())
            second = s["entry_ts"] >= mid
            rows.append(dict(sym=sym, interval=iv, rule=rule, variant=var, n=len(s), R=s["R"].mean(),
                             coin_R=c["R"].mean(), diff=s["R"].mean() - c["R"].mean(),
                             p=float((np.array(diffs) <= 0).mean()),
                             first=s.loc[~second, "R"].mean(), second=s.loc[second, "R"].mean(),
                             tick_fills=float((s["fill"] == "ticks").mean())))
            print(json.dumps(rows[-1], default=float), flush=True)
    d = pd.DataFrame(rows)
    m = len(d)
    order = np.argsort(d["p"].to_numpy())
    q = np.empty(m)
    q[order] = np.minimum.accumulate((d["p"].to_numpy()[order] * m / np.arange(1, m + 1))[::-1])[::-1]
    d["q"] = np.minimum(q, 1.0)
    d["passes"] = (d["R"] > 0) & (d["q"] < 0.05) & (d["first"] > 0) & (d["second"] > 0)
    pd.set_option("display.width", 220)
    print(d.round(4).to_string(index=False), flush=True)
    d.to_csv(OUT / "drift_validate.csv", index=False)


if __name__ == "__main__":
    main()
