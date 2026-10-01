"""Are the positive Deriv bracket and hedged-pair results real, or bar-fill optimism?

energy.py (2026-10-01, with Deriv and 4h/1d) put the alert-armed bracket at +0.019R and the hedged
pair at +0.082R, both carried by Deriv (+0.12 to +0.16R at 15m and 1h). Two reasons to doubt it:
on a martingale every rule nets minus its costs (deriving.md), and a bar backtest fills a stop at
its level even when price jumped through it - Boom/Crash stops really fill 10-19R past the level
(generators.md), and Jump indices jump by design.

Pre-registered: per instrument, the four arms (A_primary, B_primary, HB_edges, HB_sigma) with
exits by type; then the same with stop slippage charged at the instrument's own jump size - the
95th percentile of |bar return| beyond 3 sigma, as a share of the stop - on Boom, Crash, Jump and
Range Break. A result counts only if it survives the slippage in both halves, per instrument.
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
from mt5bt import Book, Costs, load_bars, load_specs, run  # noqa: E402

OUT = Path(os.environ.get("OUT", ".data/expansion"))
JUMPY = ("Boom", "Crash", "Jump", "Range")
ARMS = {
    "A_primary": dict(gate="any", two_sided=True, buffer=0.0, trail_k=2.0, confirm=False),
    "B_primary": dict(gate="alert", two_sided=True, buffer=0.0, trail_k=2.0, confirm=False),
    "HB_edges": dict(gate="alert", two_sided=True, buffer=0.0, trail_k=2.0, confirm=False, hedge="edges"),
    "HB_sigma": dict(gate="alert", two_sided=True, buffer=0.0, trail_k=2.0, confirm=False, hedge="sigma"),
}


def jump_slip(bars: pd.DataFrame, st: pd.DataFrame) -> float:
    """The instrument's own jump: 95th percentile of the overshoot of |bar move| beyond 3 sigma,
    as a multiple of a 2-sigma stop."""
    lc = np.log(bars["close"].to_numpy())
    r = np.abs(np.diff(lc, prepend=lc[0])) / np.maximum(st["sig"].to_numpy(), 1e-12)
    over = r[r > 3] - 3
    return float(np.percentile(over, 95) / 2) if len(over) > 20 else 0.0


def main() -> None:
    pred = pd.read_csv(OUT / "test_predictions.csv")
    pred = pred[pred["test"] & (pred["family"] == "deriv")]
    specs = load_specs(os.environ.get("MT5BT_DB"))
    rows = []
    for key, g in pred.groupby("key"):
        sym, iv = key.split("|")
        spec = en.spec_for(specs, sym)
        if spec is None:
            continue
        bars = load_bars(sym, iv, "seqlab", en.SEQLAB)
        book = Book(key, bars, spec, iv, feed=sym.replace("_", " ").lower())
        st = en.state(book.bars)
        ts = book.bars["ts"].to_numpy()
        idx = np.searchsorted(ts, (g["when"].to_numpy() - en.SECONDS[iv]).astype(np.int64))
        ok = (idx < len(ts)) & (ts[np.minimum(idx, len(ts) - 1)] == g["when"].to_numpy() - en.SECONDS[iv])
        idx, lift = idx[ok], g["lift"].to_numpy()[ok]
        slip = jump_slip(book.bars, st) if any(w in sym for w in JUMPY) else 0.0
        mid = np.median(idx)
        for arm, cfg in ARMS.items():
            arms = idx[lift >= 2.5] if cfg["gate"] == "alert" else idx
            sig = en.orders(book.bars, st, arms, two_sided=cfg["two_sided"], buffer=cfg["buffer"],
                            trail_k=cfg["trail_k"], confirm=cfg["confirm"], hedge=cfg.get("hedge"))
            if sig.empty:
                continue
            for label, frac in (("as_bars", 0.0), ("jump_slip", slip)):
                t, _ = run(book, None, Costs(stop_slip_frac=frac), equity=1e7, risk=0.001,
                           one_per_symbol=False, signals={key: sig})
                if t.empty:
                    continue
                second = t["signal_bar"] >= mid
                rows.append(dict(symbol=sym, interval=iv, arm=arm, fills=label, slip=round(frac, 3),
                                 n=len(t), R=round(t["R"].mean(), 4),
                                 first=round(t.loc[~second, "R"].mean(), 4),
                                 second=round(t.loc[second, "R"].mean(), 4),
                                 stops_at_level=round(float((t["reason"].isin(["stop", "trail"])).mean()), 3)))
        print(f"  {key} done (jump slip {slip:.2f} of a stop)", flush=True)
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "deriv_check.csv", index=False)
    pd.set_option("display.width", 220)
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
