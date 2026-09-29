"""Does `structures` have skill, and does its Brier score mean anything?

The production `Engine` and the production break model (`learning.breaking.Breaks`, wired exactly as
`structures/service.py` wires it: read when a call is published, observe when its touch resolves)
are replayed over the lab's broker bars, 15m and 1h interleaved in time. Every prediction is made
before its outcome is known - the models learn online, predict-then-learn - so the whole record is
out of sample.

**The control is the same code on random walks.** The Deriv Volatility and Step indices are exact
random walks (`generators.md`), so anything the engine "knows" about them is geometry: how a touch
is defined, where it starts relative to the level, how far each resolution boundary is. Real
markets and random walks run in **separate** engines, so neither's neighbours or break model sees
the other.

What is scored, each against the references that could replace it:

  direction   P(up) at the touch (`Inference.probability_up`) against the touch's resolution
              (push up or down; chop and open excluded). References:
                base rate    the engine's own per-(feed, interval) `base_rate_up`
                side rule    "the level holds": P(up | arrived from above), accumulated causally
                record_hold  the level's own hold rate on this side (`Inference.record_hold`)
  break       P(break) raw and Platt-calibrated, against break vs held (reject/backcheck/trap).
              Reference: the causal running break rate.
  push        `expected_push` against the realised push, and the call's own trade (in the
              direction `edge` claims) in volatility units

Metrics: Brier and its skill score against each reference (1 - B/B_ref), log loss and its skill
score, AUC, AUC **within each arrival side** (does it rank beyond `side`), and Murphy's
decomposition into reliability (lower is better) and resolution (higher is better) over ten bins.

Run on the lab:
  UNIVERSE=real SEQLAB=$HOME/till_infinity/data/seqlab python research/harness/skill.py
  UNIVERSE=control ...
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

from till_infinity.structures.engine import Engine
from till_infinity.structures.learning.breaking import BROKE, HELD, Breaks

UNIVERSE = os.environ.get("UNIVERSE", "real")
SYMBOLS = {
    "real": ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "EURJPY", "XAUUSD", "BTCUSD", "ETHUSD"],
    "control": ["Volatility_10_Index", "Volatility_25_Index", "Volatility_50_Index", "Volatility_75_Index",
                "Volatility_100_Index", "Step_Index"],
}[UNIVERSE]
INTERVALS = ("15m", "1h")
START = pd.Timestamp(os.environ.get("START", "2025-01-01"), tz="UTC").timestamp()
OUT = Path(os.environ.get("OUT", ".data/skill")) / f"{UNIVERSE}.json"


def stream():
    """Every bar of every symbol and interval, merged in time order."""
    series = []
    for sym in SYMBOLS:
        for iv in INTERVALS:
            try:
                df = spikerisk.load(None, sym, "SEQLAB", iv)
            except (ValueError, FileNotFoundError) as exc:
                print(f"  skip {sym} {iv}: {str(exc)[:60]}", flush=True)
                continue
            series.append(bars_of(sym, iv, df[df["ts"] >= START]))
    yield from heapq.merge(*series, key=lambda b: (b["time"], b["interval"]))


def bars_of(sym, iv, df):
    """A function, not a generator expression in the loop: those bind `sym` and `iv` late, and the
    first version of this file labelled every bar of every series with the last symbol and interval."""
    for t, h, lo, c in zip(df["ts"].to_numpy(), df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy()):
        yield {"feed": sym.lower(), "venue": "SEQLAB", "interval": iv, "time": int(t),
               "high": float(h), "low": float(lo), "close": float(c)}


def key(feed, interval, price, when):
    return (feed, interval, round(price, 8), when)


def replay():
    engine = Engine(intervals=INTERVALS)
    # One broker per series here, where production takes the median of three or more venues for
    # FX; without this the engine waits for venues that never come and forms no level at all.
    engine.consensus.single_source = frozenset(s.lower() for s in SYMBOLS)
    breaks = Breaks()
    side_counts: dict[tuple, list[float]] = {}  # (feed, interval, above) -> [ups, n], for the side rule
    brk = [0.0, 0.0]  # running break rate
    pending, rows = {}, []
    for n, bar in enumerate(stream()):
        for call in engine.observe_bar(bar):
            touch = engine.tracker.open_touch(call.level)
            if touch is None or touch.started != call.time:
                continue
            inf = call.inference
            above = touch.features.side.name == "ABOVE"
            ups, cnt = side_counts.get((call.feed, call.interval, above), [0.0, 0.0])
            reading = breaks.reading(getattr(call, "features", None) or touch.features)
            pending[key(call.feed, call.interval, touch.level_price, touch.started)] = dict(
                feed=call.feed, interval=call.interval, time=call.time, above=above,
                p_up=inf.probability_up, base_up=inf.base_rate_up, record_hold=inf.record_hold,
                record_n=inf.record_n, expected_push=inf.expected_push, push_sigma=inf.push_sigma,
                edge=inf.edge, actionable=bool(getattr(inf, "actionable", False)), risk_vol=inf.risk_vol,
                side_up=(ups + 1.0) / (cnt + 2.0), side_n=cnt, brk_rate=(brk[0] + 1) / (brk[1] + 2),
                p_break=reading.get("break_probability"), p_break_cal=reading.get("break_probability_calibrated"))
        for _level, touch in engine.drain_resolved():
            row = pending.pop(key(touch.feed, touch.interval, touch.level_price, touch.started), None)
            outcome = str(touch.outcome).split(".")[-1].lower()
            breaks.observe(touch.features, outcome)
            if outcome in BROKE or outcome in HELD:
                brk[0] += outcome in BROKE
                brk[1] += 1
            if row is None:
                continue
            row.update(outcome=outcome, push=float(touch.push_vol), adverse=float(touch.adverse_vol))
            if touch.push_vol:
                s = side_counts.setdefault((row["feed"], row["interval"], row["above"]), [0.0, 0.0])
                s[0] += touch.push_vol > 0
                s[1] += 1
            rows.append(row)
        if n % 20_000 == 0:
            print(f"  {n:,} bars, {len(rows):,} resolved touches", flush=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rows))
    return rows


# ---------------------------------------------------------------------------------------------- scoring

def brier(p, y):
    return float(np.mean((p - y) ** 2))


def logloss(p, y):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def auc(p, y):
    from sklearn.metrics import roc_auc_score
    return float(roc_auc_score(y, p)) if 0 < y.mean() < 1 else float("nan")


def murphy(p, y, bins=10):
    """Brier = reliability - resolution + uncertainty, over equal-count bins."""
    q = np.unique(np.quantile(p, np.linspace(0, 1, bins + 1)))
    b = np.clip(np.searchsorted(q, p, side="right") - 1, 0, len(q) - 2)
    ybar = y.mean()
    rel = res = 0.0
    for k in np.unique(b):
        m = b == k
        rel += m.mean() * (p[m].mean() - y[m].mean()) ** 2
        res += m.mean() * (y[m].mean() - ybar) ** 2
    return rel, res, ybar * (1 - ybar)


def score(name, p, y, refs, sides=None):
    ok = np.isfinite(p)
    p, y = p[ok], y[ok]
    refs = {k: v[ok] for k, v in refs.items()}
    B, L = brier(p, y), logloss(p, y)
    rel, res, unc = murphy(p, y)
    cells = [f"n={len(y):,}", f"Brier {B:.4f}", f"logloss {L:.4f}", f"AUC {auc(p, y):.3f}"]
    for rn, rp in refs.items():
        cells.append(f"BSS vs {rn} {1 - B / brier(rp, y):+.3f} (LLS {1 - L / logloss(rp, y):+.3f})")
    if sides is not None:
        s = sides[ok]
        within = [auc(p[s == v], y[s == v]) for v in (True, False)]
        cells.append(f"AUC within side {within[0]:.3f}/{within[1]:.3f}")
    cells.append(f"reliability {rel:.4f} resolution {res:.4f} uncertainty {unc:.4f}")
    print(f"    {name:<22} " + " | ".join(cells))


def report(rows, label):
    d = pd.DataFrame(rows)
    d = d.sort_values("time")
    mid = d["time"].quantile(0.5)
    print(f"\n  {label}: {len(d):,} resolved touches, outcomes {d['outcome'].value_counts(normalize=True).round(3).to_dict()}")
    for half, part in (("all", d), ("first half", d[d["time"] < mid]), ("second half", d[d["time"] >= mid])):
        print(f"   [{half}]")
        dd = part[(part["push"] != 0) & part["outcome"].isin(list(BROKE) + list(HELD))]
        y = (dd["push"] > 0).to_numpy(float)
        sides = dd["above"].to_numpy()
        held = np.mean(np.where(sides, y, 1 - y))
        print(f"    direction: P(up) from above {y[sides].mean():.3f}, from below {y[~sides].mean():.3f} "
              f"-> the level holds {held:.1%}")
        refs = {"base rate": dd["base_up"].to_numpy(float), "side rule": dd["side_up"].to_numpy(float)}
        score("P(up) model", dd["p_up"].to_numpy(float), y, refs, sides)
        rh = np.where(sides, dd["record_hold"], 1 - dd["record_hold"]).astype(float)
        rh = np.where(dd["record_n"] > 0, rh, np.nan)
        score("record_hold as P(up)", rh, y, refs, sides)
        score("side rule", dd["side_up"].to_numpy(float), y, {"base rate": dd["base_up"].to_numpy(float)}, sides)
        bb = part[part["outcome"].isin(list(BROKE) + list(HELD))]
        yb = bb["outcome"].isin(list(BROKE)).to_numpy(float)
        ref = {"running rate": bb["brk_rate"].to_numpy(float)}
        for col, nm in (("p_break", "P(break) raw"), ("p_break_cal", "P(break) calibrated")):
            p = pd.to_numeric(bb[col], errors="coerce").to_numpy(float)
            if np.isfinite(p).sum() > 100:
                score(nm, p, yb, ref)
        # magnitude and the call's own trade
        from scipy import stats
        e, push = dd["expected_push"].to_numpy(float), dd["push"].to_numpy(float)
        own = np.sign(dd["edge"].to_numpy(float)) * push
        hold_trade = np.where(sides, push, -push)
        act = dd["actionable"].to_numpy(bool)
        print(f"    push: Spearman(|expected|, |realised|) {stats.spearmanr(np.abs(e), np.abs(push)).statistic:+.3f}, "
              f"(expected, realised) {stats.spearmanr(e, push).statistic:+.3f} | call's own trade {own.mean():+.3f}v "
              f"(actionable {own[act].mean() if act.any() else float('nan'):+.3f}v, n={act.sum():,}) | "
              f"'level holds' trade {hold_trade.mean():+.3f}v | median adverse {dd['adverse'].median():.2f}v")


if __name__ == "__main__":
    if os.environ.get("PART", "replay") == "replay":
        rows = replay()
    else:
        rows = json.loads(OUT.read_text())
    print(f"\n{'=' * 110}\nSKILL - structures replayed on {UNIVERSE} ({', '.join(SYMBOLS)}), {', '.join(INTERVALS)}, "
          f"from {pd.Timestamp(START, unit='s'):%Y-%m-%d}")
    report(rows, UNIVERSE)
