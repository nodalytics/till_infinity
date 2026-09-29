"""Settle the shadowed confirmation gates from the journal, and judge them against confirm.md's bar.

`till_infinity/trading/shadow.py` records, for every live level signal matching one of the five
gates `research/docs/confirm.md` left standing, the gate's verdict and the hypothetical trade:
entry, level-anchored stop, targets, time limit and cost in R. It also records the plain entry at
the window's first bar for the same signal. Nothing was traded on any of it. This settles those
hypothetical trades from bars and asks each gate the question it was shadowed for.

**Settlement**, as `confirm.py`'s `simulate`:
- the bars after the entry bar, up to the record's `limit_bars`;
- the stop or the gate's target, whichever is hit first, with a bar touching both counted as
  stopped;
- still open at the limit is marked to that bar's close;
- net R is R less the record's `cost_r`;
- "stopped then right" is a stop hit with the target reached later inside the limit.

**Bars** come from the broker through the bridge (`models/bridge.py`: `TRADING_MT5_URL` and
`TRADING_MT5_API_KEY`), by the broker symbol each record carries. Without a bridge, the lab's
static seqlab snapshot is used, which only covers signals before it was taken.

**Per gate**, against `confirm.md`'s pre-registered bar:
- beats the plain entry on the same signals by at least 0.05R net with t >= 3, clustered by day;
- beats a random gate of its own pass rate: 2,000 random subsets of the plain trades;
- is ahead of the plain entry in both halves by time.

Live there is no BH and no walks: one hypothesis per gate, and the walks were a control on the
harness, not on the market. Progress is reported against the 200 settled signals per gate the
judgement waits for.

Run on the lab (read-only on the journal):
  JOURNAL=$HOME/till_infinity/data/journal.db python research/harness/shadowreport.py
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

JOURNAL = os.path.expanduser(os.environ.get("JOURNAL", "~/till_infinity/data/journal.db"))
SEQLAB = Path(os.path.expanduser(os.environ.get("SEQLAB", "~/till_infinity/data/seqlab")))
TAG = "shadow-gate"
TARGET_N = 200
BAR = {"margin": 0.05, "t": 3.0}


def records() -> pd.DataFrame:
    conn = sqlite3.connect(f"file:{JOURNAL}?mode=ro", uri=True, timeout=300.0)
    rows = []
    for t, ctx, tags in conn.execute(
        "SELECT time, context, tags FROM entries WHERE kind='observation' AND actor='trading'"
        " AND tags LIKE ?", (f"%{TAG}%",)
    ):
        c = json.loads(ctx)
        c["recorded"] = t
        rows.append(c)
    return pd.DataFrame(rows)


class Bars:
    """Closed bars by (symbol, interval): the bridge when configured, else the seqlab snapshot."""

    def __init__(self) -> None:
        self.cache: dict[tuple[str, str], pd.DataFrame] = {}
        self.http = None
        try:
            from till_infinity.models import bridge

            self.bridge = bridge
            self.http = bridge.client()
        except Exception:
            self.bridge = None
        self.seqlab = {p.name.split(".")[0].lower(): p.name.split(".")[0]
                       for p in SEQLAB.glob("*.npz")} if SEQLAB.exists() else {}

    def of(self, symbol: str, interval: str) -> pd.DataFrame | None:
        key = (symbol, interval)
        if key in self.cache:
            return self.cache[key]
        df = None
        if self.http is not None:
            got = self.bridge.bars(self.http, symbol, interval, 20_000)
            if got:
                df = pd.DataFrame({"ts": [b.time for b in got], "high": [b.high for b in got],
                                   "low": [b.low for b in got], "close": [b.close for b in got]})
        if df is None:
            name = self.seqlab.get(symbol.lower().replace(" ", "_"))
            path = SEQLAB / f"{name}.{interval}.npz" if name else None
            if path is not None and path.exists():
                z = np.load(path)
                df = pd.DataFrame({"ts": z["time"], "high": z["high"], "low": z["low"],
                                   "close": z["close"]})
        self.cache[key] = df
        return df


def settle(df: pd.DataFrame, trade: dict, side: int, stop: float, target_r: int, limit: int):
    """(net R, stopped, stopped then right), or None when the bars do not cover it yet."""
    if df is None or not trade or not trade.get("tradeable"):
        return None
    ts = df["ts"].to_numpy()
    start = int(np.searchsorted(ts, trade["entry_time"], side="left"))
    end = start + limit
    if end > len(df):
        return None  # not settled yet
    hh = df["high"].to_numpy()[start:end]
    ll = df["low"].to_numpy()[start:end]
    target = trade["targets"][str(target_r)]
    stopped = np.flatnonzero(ll <= stop if side > 0 else hh >= stop)
    reached = np.flatnonzero(hh >= target if side > 0 else ll <= target)
    ts_, tk = (stopped[0] if len(stopped) else math.inf), (reached[0] if len(reached) else math.inf)
    if tk < ts_:
        r, was_stopped, then_right = float(target_r), False, False
    elif math.isfinite(ts_):
        r, was_stopped, then_right = -1.0, True, bool(math.isfinite(tk))
    else:
        close = df["close"].to_numpy()[end - 1]
        r, was_stopped, then_right = side * (close - trade["entry"]) / trade["risk"], False, False
    return r - (trade.get("cost_r") or 0.0), was_stopped, then_right


def clustered(values: np.ndarray, days: np.ndarray) -> tuple[float, float]:
    """Mean and its standard error, clustered by day."""
    if len(values) < 3:
        return float("nan"), float("nan")
    m = values.mean()
    sums = pd.Series(values - m).groupby(days).sum()
    return float(m), float(np.sqrt((sums**2).sum()) / len(values))


def report() -> None:
    df = records()
    if df.empty:
        print(f"no shadow-gate observations in {JOURNAL} yet")
        return
    bars = Bars()
    print(f"{len(df):,} shadow-gate records, {pd.to_datetime(df['recorded'].min(), unit='s'):%Y-%m-%d}"
          f" to {pd.to_datetime(df['recorded'].max(), unit='s'):%Y-%m-%d}")
    print(f"bar: beat the plain entry by {BAR['margin']:.2f}R net with t >= {BAR['t']:.0f} (clustered by"
          " day), beat a random gate of the same pass rate, ahead in both halves; judged at "
          f"{TARGET_N} settled signals per gate\n")
    rng = np.random.default_rng(3)
    for gate, g in df.groupby("gate"):
        verdicts = g["verdict"].value_counts().to_dict()
        judged = g[g["verdict"].isin(("pass", "fail"))]
        rate = (judged["verdict"] == "pass").mean() if len(judged) else float("nan")
        gated, plain = [], []
        for _, r in judged.iterrows():
            side = 1 if r["side"] == "buy" else -1
            frame = bars.of(r["symbol"], r["ltf"])
            day = int(r["signal_time"] // 86_400)
            base = settle(frame, r.get("plain"), side, r["stop"], int(r["target_r"]), int(r["limit_bars"]))
            if base is not None:
                plain.append((r["signal_time"], day, *base))
            if r["verdict"] == "pass":
                trade = {k: r.get(k) for k in ("entry", "entry_time", "risk", "tradeable", "targets", "cost_r")}
                got = settle(frame, trade, side, r["stop"], int(r["target_r"]), int(r["limit_bars"]))
                if got is not None:
                    gated.append((r["signal_time"], day, *got))
        print(f"== {gate}: {dict(verdicts)} | pass rate {rate:.1%} | settled: gated {len(gated)}"
              f" / plain {len(plain)} | progress {len(gated)}/{TARGET_N}")
        print(f"   measured: {g['cell'].iloc[0]}")
        if len(gated) < 3 or len(plain) < 3:
            print("   too few settled to say anything yet\n")
            continue
        gv, pv = np.array([x[2] for x in gated]), np.array([x[2] for x in plain])
        gm, gse = clustered(gv, np.array([x[1] for x in gated]))
        pm, pse = clustered(pv, np.array([x[1] for x in plain]))
        diff, t = gm - pm, (gm - pm) / math.sqrt(gse**2 + pse**2) if gse and pse else float("nan")
        draws = [rng.choice(pv, max(1, round(rate * len(pv))), replace=False).mean() for _ in range(2000)]
        beat_random = float(np.mean(np.array(draws) >= gm))
        cut = np.median([x[0] for x in plain])
        halves = []
        for part in (lambda x: x[0] < cut, lambda x: x[0] >= cut):
            a = [x[2] for x in gated if part(x)]
            b = [x[2] for x in plain if part(x)]
            halves.append(np.mean(a) - np.mean(b) if a and b else float("nan"))
        stop_g = np.mean([x[3] for x in gated])
        right_g = np.mean([x[4] for x in gated])
        stop_p = np.mean([x[3] for x in plain])
        right_p = np.mean([x[4] for x in plain])
        verdict = ("PASSES" if len(gated) >= TARGET_N and diff >= BAR["margin"] and t >= BAR["t"]
                   and beat_random < 0.05 and all(h > 0 for h in halves) else
                   "not yet judged" if len(gated) < TARGET_N else "fails")
        print(f"   gated net {gm:+.3f}R against plain {pm:+.3f}R: {diff:+.3f} (t {t:+.1f})"
              f" | random gates at or above it {beat_random:.1%} | halves {halves[0]:+.3f} / {halves[1]:+.3f}")
        print(f"   stopped {stop_g:.1%} (plain {stop_p:.1%}) | stopped then right {right_g:.1%}"
              f" (plain {right_p:.1%}) | {verdict}\n")


if __name__ == "__main__":
    report()
