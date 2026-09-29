"""Does a wider stop at proportionally smaller size do better, on the entries production takes?

A stop m times wider at 1/m the size risks the same money. In R (P&L over the money at risk) the two
are directly comparable, so the question is only whether the wider stop's trades end better. Three
effects pull in different directions, and this measures the sum on real entries:

  noise     a wider stop is hit less often by the entry's own noise (the sweep problem)
  cost      the spread is a smaller share of a wider risk, so it costs fewer R - mechanical
  exit      the shipping exit trails a fixed 0.5 vol and moves to break-even at 1R, and both
            behave differently against a wider risk

Stops at 1x (what ships), 1.5x, 2x and 3x, with everything else held fixed: entry, direction,
target, hold and size in R. Two exits: `ships` (the class defaults of the production walk: the 0.5
vol trail and break-even at 1R) and `barrier` (no trail, no break-even), where a trade can only
earn drift.

Two samples, both replayed through the production forward walk (`till_infinity.shared.replay.walk`,
linted and tested, which fills a gapped stop at the open and resolves a bar that touches both
barriers as the stop):

  fills  every trade the desk actually entered (`trading` decisions in the journal): its own entry,
         stop, target and hold. Small - a few hundred - but exactly what production does
  calls  every published structures level call at the strategies' entry timeframes, the
         population every strategy draws from, with the call's own risk and push and a 30-minute
         hold (the live desk's typical hold, not the 1,440 bars older harnesses used)

The cost is each feed's median observed spread, charged on both legs by the walk. This is the real
cost for these entries, so it replaces the COST_V model the bar-level harnesses use.

Control: the same trades on walks we generate (iid Student-t(3), one path per trade with the
trade's own volatility unit). A wider stop improves R there too, through cost alone. The control
measures that mechanical part, and only improvement beyond it is the market. Deriv indices are
entries like any other.

Scores, per stop and exit: mean net R with a t-stat clustered by feed-day on the paired difference
from 1x, the hit rate (R > 0), the stopped share, and the maximum drawdown in R of the cumulative
sum in time order. Walk-forward: the first 60% of each sample by time is discovery and the last 40%
verification, and both are reported.

Pre-registered: a wider stop is worth shipping if, on `calls` in the verification half, its paired
gain over 1x is at least 0.05R with t >= 3, it exceeds the control's gain at the same width, it
does not raise the maximum drawdown in R, and `fills` agrees in sign.

Run on the lab:
  JOURNAL=$HOME/till_infinity/data/journal.db BARS=$HOME/till_infinity/data/research.db \\
    python research/harness/widestop.py
"""
from __future__ import annotations

import bisect
import json
import os
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from research.harness.sweepregimes import ENTRIES, bars_for, candidates, spreads  # noqa: E402
from till_infinity.shared.replay import walk  # noqa: E402

JOURNAL = os.path.expanduser(os.environ.get("JOURNAL", "~/till_infinity/data/journal.db"))
BARS = os.path.expanduser(os.environ.get("BARS", "~/till_infinity/data/research.db"))
OUT = Path(os.environ.get("OUT", ".data/widestop"))
SPLIT = 0.6
MULTS = (1.0, 1.5, 2.0, 3.0)
EXITS = {"ships": {}, "barrier": {"trail_vol": 0.0, "protect_r": 0.0}}
CALL_HOLD = int(os.environ.get("CALL_HOLD", "30"))  # 1m bars
MINUTES = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30, "1h": 60}
SEED = 20260929


# ---------------------------------------------------------------------------------------- samples

def fills(conn) -> list[dict]:
    """Every trade the desk entered, as the walk's trade: entry, stop and target as placed."""
    out = []
    for when, ctx in conn.execute(
        "SELECT time, context FROM entries WHERE actor='trading' AND kind='decision' ORDER BY time"
    ):
        try:
            d = json.loads(ctx or "{}")
        except Exception:
            continue
        if not all(isinstance(d.get(k), int | float) for k in ("entry", "stop", "target", "vol_bps")):
            continue
        entry, stop, target = float(d["entry"]), float(d["stop"]), float(d["target"])
        unit = entry * float(d["vol_bps"]) / 10_000.0
        up = str(d["side"]) == "buy"
        risk, reward = abs(entry - stop), abs(target - entry)
        if unit <= 0 or risk <= 0 or reward <= 0:
            continue
        push = max(abs(float(d.get("expected_push_vol") or 0.0)), 1e-9)
        out.append({
            "sample": "fills", "when": float(when), "feed": str(d["feed"]),
            "interval": str(d.get("interval")), "strategy": str(d.get("strategy")),
            "up": up, "level": entry, "unit": unit, "risk_vol": risk / unit, "push_vol": push,
            "target_mult": reward / (push * unit),
            "hold": max(1, int(float(d.get("hold_seconds") or 1800) // 60)), "context": d,
        })
    return out


def calls(conn, settings) -> list[dict]:
    """Every published level call at the entry timeframes (no strategy's gate applied)."""
    got, _, _ = candidates(conn, settings, gate=False)
    for t in got:
        t.update(sample="calls", strategy="calls", target_mult=6.0, hold=CALL_HOLD)
    return [t for t in got if t["push_vol"] > 0 and t["unit"] > 0]


# ---------------------------------------------------------------------------------------- replay

def policies():
    for exit_name, base in EXITS.items():
        for m in MULTS:
            yield exit_name, m, {**base, "stop_mult": m}


def replay_trade(rows, start, t, cost) -> dict | None:
    out = {}
    for exit_name, m, policy in policies():
        got = walk(rows, start, t, cost=cost, hold=t["hold"],
                   policy={**policy, "target_mult": t["target_mult"]})
        if got is None:
            return None
        out[(exit_name, m)] = got
    return out


def synthetic_path(t: dict, rng) -> list[tuple]:
    """A 1m walk we generate for this trade: iid Student-t(3), scaled so one bar of the trade's
    interval has the trade's own volatility unit. Memoryless by construction."""
    per_bar = t["unit"] / np.sqrt(MINUTES.get(t["interval"], 5)) / np.sqrt(3.0)  # t(3) sd is sqrt 3
    n = t["hold"] + 2
    moves = rng.standard_t(3, n) * per_bar
    wicks = np.abs(rng.standard_t(3, (n, 2))) * per_bar * 0.5
    price, rows = t["level"], []
    for i in range(n):
        close = price + moves[i]
        rows.append((t["when"] + 60 * i, price, max(price, close) + wicks[i, 0],
                     min(price, close) - wicks[i, 1], close))
        price = close
    return rows


def replay(trades: list[dict], spread: dict) -> list[dict]:
    conn = sqlite3.connect(f"file:{BARS}?mode=ro", uri=True, timeout=300.0)
    rng = np.random.default_rng(SEED)
    by_feed = defaultdict(list)
    for t in trades:
        by_feed[t["feed"]].append(t)
    out = []
    for n, (feed, part) in enumerate(sorted(by_feed.items(), key=lambda kv: -len(kv[1]))):
        rows, stamps = bars_for(conn, feed)
        bps = spread.get(feed, 0.0)
        for t in part:
            cost = t["level"] * bps / 10_000.0
            for universe in ("market", "control"):
                if universe == "market":
                    start = bisect.bisect_left(stamps, t["when"])
                    if len(rows) < 500 or start >= len(rows) - 10:
                        continue
                    got = replay_trade(rows, start, t, cost)
                else:
                    got = replay_trade(synthetic_path(t, rng), 0, t, cost)
                if got is None:
                    continue
                for (exit_name, m), (r, how) in got.items():
                    out.append({"sample": t["sample"], "universe": universe, "feed": feed,
                                "interval": t["interval"], "strategy": t["strategy"],
                                "when": t["when"], "exit": exit_name, "mult": m, "r": r,
                                "how": how})
        print(f"  {n + 1}/{len(by_feed)} feeds, {len(out):,} rows", flush=True)
    conn.close()
    return out


# ---------------------------------------------------------------------------------------- scoring

def clustered_t(diff: pd.Series, feed: pd.Series, when: pd.Series) -> float:
    ok = np.isfinite(diff)
    diff, feed, when = diff[ok], feed[ok], when[ok]
    if len(diff) < 3:
        return float("nan")
    cluster = feed + "|" + (when // 86_400).astype(int).astype(str)
    sums = (diff - diff.mean()).groupby(cluster).sum()
    se = np.sqrt((sums**2).sum()) / len(diff)
    return float(diff.mean() / se) if se > 0 else float("nan")


def drawdown(r: pd.Series) -> float:
    equity = r.cumsum().to_numpy()
    return float((np.maximum.accumulate(np.r_[0.0, equity])[1:] - equity).max()) if len(equity) else 0.0


def table(df: pd.DataFrame, title: str) -> None:
    if df.empty:
        return
    key = ["feed", "when", "strategy"]
    print(f"\n  {title}")
    print(f"    {'exit':8s} {'stop':>5s} {'n':>7s} {'mean R':>8s} {'vs 1x':>8s} {'t':>6s} "
          f"{'hit':>6s} {'stopped':>8s} {'max DD R':>9s}")
    for exit_name in EXITS:
        e = df[df["exit"] == exit_name]
        base = e[e["mult"] == 1.0].set_index(key)["r"]
        for m in MULTS:
            part = e[e["mult"] == m].sort_values("when")
            paired = part.set_index(key)["r"] - base
            paired = paired.reset_index()
            t = clustered_t(paired["r"], paired["feed"], paired["when"])
            print(f"    {exit_name:8s} {m:5.1f} {len(part):7,} {part['r'].mean():+8.3f} "
                  f"{paired['r'].mean():+8.3f} {t:+6.1f} {np.mean(part['r'] > 0):6.1%} "
                  f"{np.mean(part['how'] == 'stop'):8.1%} {drawdown(part['r']):9.1f}")


def report(df: pd.DataFrame) -> None:
    for (sample, universe), g in df.groupby(["sample", "universe"]):
        cut = g["when"].quantile(SPLIT)
        print(f"\n== {sample} · {universe} · {g[g['mult'] == 1.0]['when'].count() // len(EXITS):,} trades")
        table(g[g["when"] < cut], "discovery (first 60%)")
        table(g[g["when"] >= cut], "verification (last 40%)")
        if sample == "fills" and universe == "market":
            for strategy, s in g.groupby("strategy"):
                if s["when"].nunique() >= 20:
                    table(s, f"strategy {strategy}, pooled")
    print("\nR is P&L over the money at risk; a wider stop is a smaller position for the same risk.")
    print("`stopped` counts every exit on a stop, including a trailed or break-even one, so under the")
    print("`ships` exit it is close to 100% by construction; read it under `barrier`.")
    print("The control's gain is the mechanical part (the spread is fewer R against a wider risk).")


def run() -> None:
    from till_infinity.trading.config import Settings

    settings = Settings.from_env()
    jn = sqlite3.connect(f"file:{JOURNAL}?mode=ro", uri=True, timeout=300.0)
    spread = spreads(jn)
    got = fills(jn)
    got_calls = [t for t in calls(jn, settings) if t["interval"] in ENTRIES]
    jn.close()
    print(f"{len(got)} fills, {len(got_calls):,} level calls", flush=True)
    df = pd.DataFrame(replay(got + got_calls, spread))
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_pickle(OUT / "widestop.pkl.gz")  # our own output, read back only by PART=report
    report(df)


if __name__ == "__main__":
    if os.environ.get("PART") == "report":
        report(pd.read_pickle(OUT / "widestop.pkl.gz"))
    else:
        run()
