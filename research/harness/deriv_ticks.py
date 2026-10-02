"""Settle the two Deriv candidates on real ticks: Drift Switch Index 10 and Jump 50 Index, 15m.

deriv_check.py left them standing after the bar-fill optimism that sank Boom, Crash and Range
Break: on 15m bars the alert-armed bracket and the hedged pairs made +0.08 to +0.20R. Bars fill a
stop at its level; ticks fill it where price actually was. The bridge serves their ticks.

Pre-registered (2026-10-02), before any run.

  held-out  2026-02-13 to 2026-09-12 (the window the candidates were judged on), the same entries
            and exits as energy.py: A_primary (any compressed bar), B_primary (the alert), HB_edges
            and HB_sigma (hedged pairs) - each filled on bars, and on ticks (resting orders at the
            tick that reached the level, trailing stops on ticks, jumps filled where they landed)
  fresh     2026-09-12 to now: 15m bars built from the ticks, the alert computed by the production
            class and the shipped model, the same four arms on ticks (descriptive: three weeks)
  survives  only an arm positive on ticks in both halves of the held-out window
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research" / "harness"))
sys.path.insert(0, str(ROOT / "research"))
sys.path.insert(0, str(ROOT))

import energy as en  # noqa: E402
from mt5bt import Book, Costs, bars_from_ticks, load_bars, load_specs, load_ticks, run  # noqa: E402
from till_infinity.structures.learning import expansion as ex  # noqa: E402

OUT = Path(os.environ.get("OUT", ".data/deriv_ticks"))
PRED = Path(os.environ.get("PRED", ".data/expansion_all"))
CANDIDATES = {"Drift_Switch_Index_10": "Drift Switch Index 10", "Jump_50_Index": "Jump 50 Index"}
FRESH_FROM = pd.Timestamp("2026-09-12", tz="UTC").timestamp()


def arms_of(idx: np.ndarray, lift: np.ndarray) -> dict:
    return {
        "A_primary": (idx, dict(two_sided=True, buffer=0.0, trail_k=2.0, confirm=False)),
        "B_primary": (idx[lift >= 2.5], dict(two_sided=True, buffer=0.0, trail_k=2.0, confirm=False)),
        "HB_edges": (idx[lift >= 2.5], dict(two_sided=True, buffer=0.0, trail_k=2.0, confirm=False, hedge="edges")),
        "HB_sigma": (idx[lift >= 2.5], dict(two_sided=True, buffer=0.0, trail_k=2.0, confirm=False, hedge="sigma")),
    }


def trade(book: Book, st: pd.DataFrame, idx, lift, fill: str, mid: float) -> dict:
    out = {}
    for name, (arm, cfg) in arms_of(idx, lift).items():
        sig = en.orders(book.bars, st, arm, **cfg)
        if sig.empty:
            out[name] = dict(n=0)
            continue
        t, _ = run(book, None, Costs(fill=fill), equity=1e7, risk=0.001, one_per_symbol=False,
                   signals={book.symbol: sig})
        if t.empty:
            out[name] = dict(n=0)
            continue
        second = t["signal_bar"] >= mid
        out[name] = dict(n=len(t), R=round(t["R"].mean(), 4),
                         halves=[round(t.loc[~second, "R"].mean(), 4), round(t.loc[second, "R"].mean(), 4)],
                         gross=round((t["gross"] / t["risk_money"]).mean(), 4),
                         tick_fills=round(float((t["fill"] == "ticks").mean()), 3),
                         exits=t["reason"].value_counts().to_dict())
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    pred = pd.read_csv(PRED / "test_predictions.csv")
    specs = load_specs(os.environ.get("MT5BT_DB"))
    res = {}
    for lab_name, broker in CANDIDATES.items():
        key = f"{lab_name}|15m"
        g = pred[(pred["key"] == key) & pred["test"]]
        spec = specs[broker]
        bars = load_bars(lab_name, "15m", "seqlab", en.SEQLAB)
        start = float(g["when"].min()) - 3 * 86400
        ticks = load_ticks(broker, start, pd.Timestamp.now(tz="UTC").timestamp(), os.environ.get("MT5BT_DB"))
        print(f"{broker}: {len(ticks):,} ticks", flush=True)
        book = Book(broker, bars, spec, "15m", feed=broker.lower())
        book.ticks = ticks
        st = en.state(book.bars)
        ts = book.bars["ts"].to_numpy()
        idx = np.searchsorted(ts, (g["when"].to_numpy() - 900).astype(np.int64))
        ok = (idx < len(ts)) & (ts[np.minimum(idx, len(ts) - 1)] == g["when"].to_numpy() - 900)
        idx, lift = idx[ok], g["lift"].to_numpy()[ok]
        mid = float(np.median(idx))
        cell = {"held_out_bars": trade(book, st, idx, lift, "bars", mid),
                "held_out_ticks": trade(book, st, idx, lift, "ticks", mid)}
        # fresh: bars built from the ticks after the lab's bars end, the alert from the shipped model
        fresh_ticks = ticks[ticks["ts_ms"] >= FRESH_FROM * 1000]
        if len(fresh_ticks) > 10_000:
            fb = bars_from_ticks(fresh_ticks, "15m", spec)
            old = book.bars[book.bars["ts"] < fb["ts"].min()][["ts", "open", "high", "low", "close", "volume", "spread"]]
            allb = pd.concat([old, fb[old.columns]], ignore_index=True)
            fbook = Book(broker, allb, spec, "15m", feed=broker.lower())
            fbook.ticks = ticks
            model = ex.Expansion()
            fidx, flift = [], []
            for k, r in enumerate(fbook.bars.itertuples(index=False)):
                model.observe(lab_name, "15m", 900, r.ts + 900, r.high, r.low, r.close, r.volume)
                if r.ts >= fb["ts"].min():
                    got = model.reading(lab_name, "15m")
                    if got:
                        fidx.append(k)
                        flift.append(got["expansion_lift"])
            fidx, flift = np.array(fidx, int), np.array(flift)
            fst = en.state(fbook.bars)
            cell["fresh_ticks"] = trade(fbook, fst, fidx, flift, "ticks", float(np.median(fidx)) if len(fidx) else 0)
            cell["fresh_compressed_bars"] = int(len(fidx))
        survives = {a: bool(v.get("n") and min(v["halves"]) > 0) for a, v in cell["held_out_ticks"].items()}
        cell["survives"] = survives
        res[broker] = cell
        print(json.dumps({broker: cell}, indent=1), flush=True)
    (OUT / "deriv_ticks.json").write_text(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    main()
