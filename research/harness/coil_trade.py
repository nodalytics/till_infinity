"""B1 and F2: a breakout straddle armed by the expansion alert, or by unrecovered stress.

research/docs/ideas.md B1 and F2. An unconditional two-sided stop straddle lost at every stop
(fractal-twins.md); the question is whether arming it only when the alert fires (B1), or only when
a compressed market still carries unrecovered stress (F2), changes that.

Pre-registered (2026-10-01), before any run:

  box       the high and low of the 16 bars ending at the arming bar (bid)
  orders    a buy stop at the box high plus the spread (the bid must clear the box) and a sell
            stop at the box low, both resting 16 bars
  stop      at the opposite edge of the box (box height plus the spread): caps each side's loss.
            No take-profit. Exit by the stop or after 16 bars (the alert's horizon).
  versions  "straddle": both legs live, so a failed breakout that reverses fills the other side;
            "oco": the first fill cancels the other
  skip      a box under 3 spreads (untradeable); one arming per series per 16 bars
  costs     MT5's per-bar spread from the broker's own bars, swap at the rollover from the broker's
            symbol specs, no commission (CFD spreads)
  arms      B1      alert lift >= 2.5 (held-out predictions of the walk-forward model)
            quiet   compressed, alert lift < 1           (the null for B1)
            any     compressed, every one                (the unconditional straddle)
            F2      compressed and stress in its top fifth of its own last 1,500 bars
            F2-low  compressed and stress in its bottom fifth
            B1+F2   both
  stress    F_t = 0.98 F_t-1 + max(0, log(TR_t / median TR of the last 500 bars))
  walks     B1's rules on 12 GARCH walks, the alert computed on them by the same model
  judged    mean R net, day-bootstrap CI, both halves of the held-out period. B1 must beat
            `quiet` and `any`; F2 must beat F2-low and `any`; and neither may show on the walks.

  ./.secrets/lab.sh run research/harness/coil_trade.py (with SEQLAB, OUT, MT5BT_DB)
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "research"))

from mt5bt import Book, Costs, load_bars, load_specs, run  # noqa: E402
from mt5bt.data import EXAMPLE_SPECS  # noqa: E402
from mt5bt.nulls import garch_walk  # noqa: E402
from mt5bt.report import day_bootstrap  # noqa: E402
from till_infinity.shared import frozen  # noqa: E402
from till_infinity.structures.learning import expansion as ex  # noqa: E402

OUT = Path(os.environ.get("OUT", ".data/expansion"))
SEQLAB = os.environ.get("SEQLAB", ".data/seqlab")
SECONDS = {"15m": 900, "1h": 3600}
BOX, HOLD, ARM_LIFT, QUIET_LIFT = 16, 16, 2.5, 1.0


def stress(bars: pd.DataFrame) -> np.ndarray:
    h, l, c = (np.log(bars[k].to_numpy()) for k in ("high", "low", "close"))
    prev = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(abs(h - prev), abs(l - prev)))
    norm = pd.Series(tr).rolling(500, min_periods=200).median().to_numpy()
    excess = np.maximum(0.0, np.log(np.maximum(tr, 1e-12) / np.maximum(norm, 1e-12)))
    excess = np.nan_to_num(excess)
    f = np.empty(len(tr))
    acc = 0.0
    for k in range(len(tr)):
        acc = 0.98 * acc + excess[k]
        f[k] = acc
    return pd.Series(f).rolling(1500, min_periods=300).rank(pct=True).to_numpy()


def straddles(bars: pd.DataFrame, arms: np.ndarray, oco: bool) -> pd.DataFrame:
    """Two resting legs per arming bar; one arming per BOX bars."""
    hi = bars["high"].rolling(BOX).max().to_numpy()
    lo = bars["low"].rolling(BOX).min().to_numpy()
    sp = bars["spread_price"].to_numpy()
    rows, last = [], -BOX
    for n, i in enumerate(np.sort(arms)):
        if i - last < BOX or np.isnan(hi[i]) or np.isnan(sp[i]):
            continue
        height = hi[i] - lo[i]
        if height < 3 * sp[i]:
            continue
        last = i
        stop = height + sp[i]
        group = n if oco else -1
        rows.append(dict(i=i, side=1, entry=hi[i] + sp[i], expires=BOX, stop=stop, hold=HOLD, oco=group))
        rows.append(dict(i=i, side=-1, entry=lo[i], expires=BOX, stop=stop, hold=HOLD, oco=group))
    return pd.DataFrame(rows)


def judge(trades: pd.DataFrame) -> dict:
    if trades.empty:
        return dict(n=0)
    t = trades.sort_values("entry_ts")
    half = len(t) // 2
    lo, hi = day_bootstrap(t)
    risk = t["risk_money"]
    return dict(n=len(t), mean_R=round(t["R"].mean(), 4), ci=[round(lo, 4), round(hi, 4)],
                first_half=round(t["R"].iloc[:half].mean(), 4),
                second_half=round(t["R"].iloc[half:].mean(), 4),
                gross_R=round((t["gross"] / risk).mean(), 4),
                spread_R=round((t["spread_cost"] / risk).mean(), 4),
                swap_R=round((t["swap_cost"] / risk).mean(), 4),
                hit=round(float((t["net"] > 0).mean()), 3),
                exits=t["reason"].value_counts().to_dict())


def main() -> None:
    pred = pd.read_csv(OUT / "test_predictions.csv")
    pred = pred[pred["test"] & (pred["kind"] == "real")]
    wf = json.loads((OUT / "expansion_wf.json").read_text())
    base = wf["base_rate"]
    pred["lift"] = pred["p"] / base
    specs = load_specs(os.environ.get("MT5BT_DB"))
    results: dict = {}
    rng = np.random.default_rng(3)
    arms_all = {}
    books = {}
    for key, g in pred.groupby("key"):
        sym, iv = key.split("|")
        spec = specs.get(sym) or next((v for k, v in specs.items() if k.split(".")[0] == sym), None)
        if spec is None:
            print(f"  no spec for {sym}", flush=True)
            continue
        bars = load_bars(sym, iv, "seqlab", SEQLAB)
        book = Book(spec.symbol, bars, spec, iv, feed=sym.lower(),
                    meta={"family": g["family"].iloc[0]})
        ts = book.bars["ts"].to_numpy()
        idx = np.searchsorted(ts, (g["when"].to_numpy() - SECONDS[iv]).astype(np.int64))
        ok = (idx < len(ts)) & (ts[np.minimum(idx, len(ts) - 1)] == g["when"].to_numpy() - SECONDS[iv])
        g, idx = g[ok], idx[ok]
        f = stress(book.bars)[idx]
        lift = g["lift"].to_numpy()
        arms = {"B1": idx[lift >= ARM_LIFT], "quiet": idx[lift < QUIET_LIFT], "any": idx,
                "F2": idx[f >= 0.8], "F2-low": idx[f <= 0.2],
                "B1+F2": idx[(lift >= ARM_LIFT) & (f >= 0.8)]}
        books[key] = book
        arms_all[key] = arms
    print(f"{len(books)} series", flush=True)
    for version in ("straddle", "oco"):
        for arm in ("B1", "quiet", "any", "F2", "F2-low", "B1+F2"):
            sigs, bks = {}, []
            for key, book in books.items():
                s = straddles(book.bars, arms_all[key][arm], version == "oco")
                if len(s):
                    sigs[book.symbol + "|" + book.interval] = s
                    bks.append(book)
            # run per book (same symbol can appear at two intervals)
            parts = []
            for book in bks:
                k = book.symbol + "|" + book.interval
                t, _ = run(Book(k, book.bars, book.spec, book.interval, feed=book.feed), None,
                           Costs(), equity=1e7, risk=0.001, one_per_symbol=False,
                           signals={k: sigs[k]})
                if len(t):
                    t["family"] = book.meta["family"]
                    parts.append(t)
            tr = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
            res = judge(tr)
            if len(tr):
                res["by_family"] = {f: round(x["R"].mean(), 4) for f, x in tr.groupby("family")}
            results[f"{version}/{arm}"] = res
            print(f"  {version:8s} {arm:7s} {json.dumps(res)}", flush=True)

    # the walk control: B1's rules on GARCH walks, the alert computed by the same model
    spec = frozen.Trees(wf)
    walk_parts = {"straddle": [], "oco": []}
    for w in range(12):
        bars = garch_walk(30_000, interval="15m", price=1.10, spread_points=8.0, seed=500 + w)
        book = Book("EURUSD", bars, EXAMPLE_SPECS["EURUSD"], "15m")
        model = ex.Expansion()
        armed = []
        for k, r in enumerate(book.bars.itertuples(index=False)):
            model.observe("w", "15m", 900, r.ts + 900, r.high, r.low, r.close)
            s = model.series.get("w|15m")
            if k > 18_000 and s is not None and s.compressed and s.latest:
                if spec.predict(s.latest) / base >= ARM_LIFT:
                    armed.append(k)
        for version in walk_parts:
            sig = straddles(book.bars, np.array(armed, int), version == "oco")
            if len(sig):
                t, _ = run(book, None, Costs(), equity=1e7, risk=0.001, one_per_symbol=False,
                           signals={"EURUSD": sig})
                walk_parts[version].append(t.assign(walk=w))
    for version, parts in walk_parts.items():
        tr = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
        res = judge(tr)
        if len(tr):
            per = tr.groupby("walk")["R"].mean()
            res["per_walk_mean"] = round(per.mean(), 4)
            res["per_walk_se"] = round(per.std(ddof=1) / np.sqrt(len(per)), 4)
        results[f"walks/{version}/B1"] = res
        print(f"  walks {version:8s} {json.dumps(res)}", flush=True)
    (OUT / "coil_trade.json").write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
