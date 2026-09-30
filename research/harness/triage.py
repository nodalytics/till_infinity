"""Strategy triage: which production strategies to keep, fix or cut.

stophunt.md, limitfills.md, widestop.md and vetoes.md each found every entry style losing after
costs, and each ended with the same advice: judge the strategies directly. This does.

Evidence, from the lab's journal snapshot (read only):

  taken    every closed desk trade (`outcome` by `trading`), with the R the account booked
  intents  every trade a strategy *asked for*, taken or not: its fills (`decision`), the intents
           the risk layer declined (`declined ...`, with entry, stop and target as placed), the
           untaken intents the service followed (`would have ...`) and those considered and wanted
           while another strategy took the signal. Deduplicated per strategy, feed and minute.
           Every one is settled on 1m bars from research.db through the production walk
           (`shared.replay.walk`), at the stop and target it was placed with, under two exits:
           `ships` (the walk's default, protecting at 1R as production manages) and `barrier`
           (stop, target or the hold, nothing else). Cost is each feed's median recorded spread,
           charged on both legs; gross is the same walk at zero cost.

This settles what each strategy *selected*, which is far more trades than the few hundred the
account closed. It does not reproduce every live management rule (trailing variants, stale exits,
parking) - the `taken` table is the live record, and where the two disagree the live record wins.

Nulls, per strategy:

  random   the same signals it drew from - every published structures call at its entry
           timeframes - entered in the call's own direction, with this strategy's median geometry
           (risk in volatility units, reward-to-risk and hold), at up to three times its count.
           Does its selection beat a random pick of the same signals with the same exits?
  walks    every intent replayed on a walk we generate at its own volatility: the geometry's
           mechanical cost
  BH       across strategies, on the one-sided p-values, because with a dozen strategies one looks
           good by chance

Pre-registered verdicts, per strategy (intents, `ships` exit):

  keep     net R > 0 with its CI above 0, in both halves
  fix      gross R > 0 (CI above 0) but net <= 0: a cost or size problem, not a selection one
  cut      gross R <= 0 and its gross does not beat the random null (BH q > 0.05)
  unclear  anything else, or fewer than 50 intents

Deriv is a market: reported per strategy x family where the sample allows.

Run on the lab:
  JOURNAL=$HOME/till_infinity/data/journal.db BARS=$HOME/till_infinity/data/research.db \\
    python research/harness/triage.py            (PART=report re-reads the saved rows)
"""
from __future__ import annotations

import bisect
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

from research.harness.sweepregimes import ENTRIES, bars_for, candidates, spreads  # noqa: E402
from till_infinity.shared.replay import walk  # noqa: E402
from till_infinity.trading.strategies.policy import family_of  # noqa: E402

JOURNAL = os.path.expanduser(os.environ.get("JOURNAL", "~/till_infinity/data/journal.db"))
BARS = os.path.expanduser(os.environ.get("BARS", "~/till_infinity/data/research.db"))
OUT = Path(os.environ.get("OUT", ".data/triage"))
EXITS = {"ships": {}, "barrier": {"trail_vol": 0.0, "protect_r": 0.0}}
MINUTES = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30, "1h": 60}
MAX_HOLD = 24 * 60  # 1m bars
RANDOM_MULT = 3
SEED = 20260930


def number(d: dict, key: str, default: float = 0.0) -> float:
    got = d.get(key)
    return float(got) if isinstance(got, int | float) and math.isfinite(got) else default


# ---------------------------------------------------------------------------------------- samples

def taken(conn) -> pd.DataFrame:
    """The live record: every closed desk trade with the R the account booked."""
    rows = []
    for when, ctx in conn.execute(
        "SELECT time, context FROM entries WHERE actor='trading' AND kind='outcome' ORDER BY time"
    ):
        d = json.loads(ctx or "{}")
        r = d.get("r_multiple")
        if not isinstance(r, int | float) or not math.isfinite(r):
            continue
        feed = str(d.get("feed") or "")
        rows.append({"when": float(when) - number(d, "seconds"), "strategy": str(d.get("strategy")),
                     "feed": feed, "family": family_of(feed), "r": float(r)})
    return pd.DataFrame(rows)


def trade_from(when: float, d: dict, strategy: str, source: str) -> dict | None:
    """A walk trade at the entry, stop and target the strategy placed."""
    entry, stop, target = number(d, "entry"), number(d, "stop"), number(d, "target")
    if entry <= 0 or stop <= 0 or target <= 0:
        return None
    side = str(d.get("side") or "")
    up = side == "buy" if side in ("buy", "sell") else target > entry
    risk, reward = abs(entry - stop), abs(target - entry)
    # A reward-to-risk outside 0.05-20 is a malformed placement (a stop on the entry, a target a
    # continent away), not a trade anyone would take; a handful in the journal read 30,000.
    if risk <= 0 or reward <= 0 or not 0.05 <= reward / risk <= 20:
        return None
    if (up and (stop >= entry or target <= entry)) or (
        not up and (stop <= entry or target >= entry)
    ):
        return None
    vol_bps = number(d, "vol_bps")
    unit = entry * vol_bps / 10_000.0 if vol_bps > 0 else risk
    hold_s = number(d, "hold_seconds") or number(d, "expected_hold_s") or 1800.0
    feed = str(d.get("feed") or "")
    return {
        "source": source, "when": float(when), "strategy": strategy, "feed": feed,
        "family": family_of(feed), "interval": str(d.get("interval") or ""), "up": up,
        "level": entry, "unit": unit, "risk_vol": risk / unit, "push_vol": reward / unit,
        "target_mult": 1.0, "rr": reward / risk, "hold": int(min(MAX_HOLD, max(1, hold_s // 60))),
        "context": d,
    }


def intents(conn) -> list[dict]:
    """Every trade a strategy asked for, deduplicated per strategy, feed and minute."""
    out, seen = [], set()
    for kind, when, title, ctx in conn.execute(
        "SELECT kind, time, title, context FROM entries WHERE actor='trading' "
        "AND kind IN ('decision', 'observation') ORDER BY time"
    ):
        d = json.loads(ctx or "{}")
        strategy = str(d.get("strategy") or "")
        if not strategy:
            continue
        if kind == "decision":
            source = "fill"
        elif d.get("shape") == "untaken":
            if d.get("filled") is False:
                continue  # it never filled: nothing to settle
            source = "untaken"
        elif d.get("shape") == "considered":
            if not d.get("wanted"):
                continue
            source = "considered"
        elif str(title).startswith("declined"):
            source = "declined"
        else:
            continue
        t = trade_from(when, d, strategy, source)
        if t is None:
            continue
        key = (strategy, t["feed"], round(t["level"], 6), int(when // 60))
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
    return out


def random_null(conn, settings, per_strategy: pd.DataFrame, rng) -> list[dict]:
    """For each strategy: random published calls at its entry timeframes, in the call's own
    direction, with the strategy's median geometry."""
    calls, _, _ = candidates(conn, settings, gate=False)
    calls = [c for c in calls if c["unit"] > 0]
    by_interval = defaultdict(list)
    for c in calls:
        by_interval[c["interval"]].append(c)
    out = []
    for strategy, g in per_strategy.groupby("strategy"):
        intervals = [iv for iv in g["interval"].unique() if iv in by_interval]
        pool = [c for iv in intervals for c in by_interval[iv]]
        if not pool:
            continue
        rv, rr = float(g["risk_vol"].median()), float(g["rr"].median())
        hold = int(g["hold"].median())
        # Risk in the call's own volatility units only where the strategy's was: otherwise one
        # unit of risk is the placed risk, and a fixed share of the call's volatility stands in.
        if not (g["context"].map(lambda c: number(c, "vol_bps") > 0)).mean() > 0.5:
            rv = 1.0
        n = min(len(pool), RANDOM_MULT * len(g))
        for i in rng.choice(len(pool), n, replace=False):
            c = pool[i]
            out.append({
                "source": "random", "when": c["when"], "strategy": strategy, "feed": c["feed"],
                "family": family_of(c["feed"]), "interval": c["interval"], "up": c["up"],
                "level": c["level"], "unit": c["unit"], "risk_vol": rv, "push_vol": rv * rr,
                "target_mult": 1.0, "rr": rr, "hold": hold, "context": c["context"],
            })
    return out


# ---------------------------------------------------------------------------------------- replay

def synthetic_path(t: dict, rng) -> list[tuple]:
    """A 1m walk we generate: iid Student-t(3) at the trade's own volatility unit per bar of its
    interval. Memoryless by construction."""
    per_bar = t["unit"] / np.sqrt(MINUTES.get(t["interval"], 5)) / np.sqrt(3.0)
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
    skipped: dict[str, int] = defaultdict(int)
    for n, (feed, part) in enumerate(sorted(by_feed.items(), key=lambda kv: -len(kv[1]))):
        rows, stamps = bars_for(conn, feed)
        bps = spread.get(feed, 0.0)
        for t in part:
            universes = [("market", None)]
            if t["source"] != "random":
                universes.append(("walks", synthetic_path(t, rng)))
            for universe, path in universes:
                trade = t
                if universe == "market":
                    start = bisect.bisect_left(stamps, t["when"])
                    if len(rows) < 500 or start >= len(rows) - 10:
                        continue
                    bars = rows
                    # The walk enters at `level`. An intent is walked only if that was the market
                    # at the time - a resting limit away from price, or a zone call's level, would
                    # book a fill the market never offered. Random picks enter at the market,
                    # with the same stop and target distances.
                    price = rows[start][1]
                    if t["source"] == "random":
                        trade = {**t, "level": price}
                    elif abs(price - t["level"]) > 0.25 * t["risk_vol"] * t["unit"]:
                        skipped[t["strategy"]] += 1
                        continue
                else:
                    bars, start = path, 0
                for exit_name, policy in EXITS.items():
                    for cost_name, cost in (("net", t["level"] * bps / 10_000.0), ("gross", 0.0)):
                        got = walk(bars, start, trade, cost=cost, hold=t["hold"],
                                   policy={**policy, "target_mult": t["target_mult"]})
                        if got is None:
                            continue
                        out.append({"source": t["source"], "universe": universe, "strategy":
                                    t["strategy"], "feed": feed, "family": t["family"],
                                    "interval": t["interval"], "when": t["when"], "exit": exit_name,
                                    "cost": cost_name, "r": got[0], "how": got[1]})
        if (n + 1) % 25 == 0 or n + 1 == len(by_feed):
            print(f"  {n + 1}/{len(by_feed)} feeds, {len(out):,} rows", flush=True)
    conn.close()
    print("intents not at market when placed (resting limits, skipped): "
          + ", ".join(f"{k} {v}" for k, v in sorted(skipped.items())), flush=True)
    return out


# ---------------------------------------------------------------------------------------- scoring

def mean_ci(r: pd.Series, when: pd.Series, n: int = 1000, seed: int = 0) -> tuple[float, float, float]:
    """Mean and a 95% interval resampling whole days."""
    r = r.to_numpy()
    if len(r) < 5:
        return float("nan"), float("nan"), float("nan")
    days = (when.to_numpy() // 86_400).astype(int)
    uniq = np.unique(days)
    idx = {d: np.flatnonzero(days == d) for d in uniq}
    rng = np.random.default_rng(seed)
    means = [r[np.concatenate([idx[d] for d in rng.choice(uniq, len(uniq))])].mean()
             for _ in range(n)]
    lo, hi = np.quantile(means, [0.025, 0.975])
    return float(r.mean()), float(lo), float(hi)


def p_above(a: pd.Series, when: pd.Series, b: pd.Series | None = None, bwhen=None, n: int = 1000):
    """One-sided bootstrap p that mean(a) - mean(b) <= 0 (b absent: <= 0), resampling days."""
    rng = np.random.default_rng(1)

    def boot(r, w):
        r, days = r.to_numpy(), (w.to_numpy() // 86_400).astype(int)
        uniq = np.unique(days)
        idx = {d: np.flatnonzero(days == d) for d in uniq}
        return [r[np.concatenate([idx[d] for d in rng.choice(uniq, len(uniq))])].mean()
                for _ in range(n)]

    if len(a) < 5 or (b is not None and len(b) < 5):
        return float("nan")
    da = np.array(boot(a, when))
    diff = da - (np.array(boot(b, bwhen)) if b is not None else 0.0)
    return float((np.sum(diff <= 0) + 1) / (n + 1))


def bh(p: dict) -> dict:
    keys = [k for k, v in p.items() if math.isfinite(v)]
    order = sorted(keys, key=lambda k: p[k])
    m, q, prev = len(order), {}, 1.0
    for rank, k in reversed(list(enumerate(order, 1))):
        prev = min(prev, p[k] * m / rank)
        q[k] = prev
    return q


def report(df: pd.DataFrame, live: pd.DataFrame) -> None:
    print("\n" + "=" * 110)
    print("LIVE RECORD - every closed desk trade, R as booked (day-bootstrap 95%)")
    print(f"  {'strategy':18s} {'n':>5s} {'mean R':>8s} {'95% CI':>18s} {'hit':>6s} {'total R':>8s} "
          f"{'max DD':>7s} {'halves':>15s}")
    cut_live = live["when"].median() if len(live) else 0.0
    for s, g in live.groupby("strategy"):
        m, lo, hi = mean_ci(g["r"], g["when"])
        eq = g.sort_values("when")["r"].cumsum().to_numpy()
        dd = float((np.maximum.accumulate(np.r_[0.0, eq])[1:] - eq).max()) if len(eq) else 0.0
        h1, h2 = g[g["when"] < cut_live]["r"].mean(), g[g["when"] >= cut_live]["r"].mean()
        print(f"  {s:18s} {len(g):5d} {m:+8.3f} [{lo:+.3f}, {hi:+.3f}] {np.mean(g['r'] > 0):6.0%} "
              f"{g['r'].sum():+8.1f} {dd:7.1f} {h1:+.3f}/{h2:+.3f}")

    mk = df[(df["universe"] == "market")]
    cut = df["when"].median()
    for exit_name in EXITS:
        print("\n" + "=" * 110)
        print(f"SELECTIONS REPLAYED - every intent each strategy placed, exit '{exit_name}' "
              "(day-bootstrap 95%)")
        print(f"  {'strategy':18s} {'n':>6s} {'net R':>22s} {'gross R':>22s} {'halves net':>15s} "
              f"{'random gross':>13s} {'walks net':>10s} {'hit':>5s}")
        e = mk[mk["exit"] == exit_name]
        w = df[(df["universe"] == "walks") & (df["exit"] == exit_name)]
        p_net, p_sel, rows = {}, {}, {}
        for s in sorted(e[e["source"] != "random"]["strategy"].unique()):
            mine = e[(e["strategy"] == s) & (e["source"] != "random")]
            net, gross = mine[mine["cost"] == "net"], mine[mine["cost"] == "gross"]
            rnd = e[(e["strategy"] == s) & (e["source"] == "random") & (e["cost"] == "gross")]
            wk = w[(w["strategy"] == s) & (w["cost"] == "net")]
            n_m, n_lo, n_hi = mean_ci(net["r"], net["when"])
            g_m, g_lo, g_hi = mean_ci(gross["r"], gross["when"])
            h1 = net[net["when"] < cut]["r"].mean()
            h2 = net[net["when"] >= cut]["r"].mean()
            p_net[s] = p_above(net["r"], net["when"])
            p_sel[s] = p_above(gross["r"], gross["when"], rnd["r"], rnd["when"]) if len(rnd) else float("nan")
            rows[s] = dict(n=len(net), net=(n_m, n_lo, n_hi), gross=(g_m, g_lo, g_hi), h=(h1, h2),
                           rnd=rnd["r"].mean() if len(rnd) else float("nan"),
                           walks=wk["r"].mean() if len(wk) else float("nan"),
                           hit=float(np.mean(net["r"] > 0)) if len(net) else float("nan"))
            print(f"  {s:18s} {len(net):6d} {n_m:+.3f} [{n_lo:+.3f}, {n_hi:+.3f}] "
                  f"{g_m:+.3f} [{g_lo:+.3f}, {g_hi:+.3f}] {h1:+.3f}/{h2:+.3f} "
                  f"{rows[s]['rnd']:+13.3f} {rows[s]['walks']:+10.3f} {rows[s]['hit']:5.0%}")
        q_net, q_sel = bh(p_net), bh(p_sel)
        print(f"\n  verdicts ('{exit_name}'): BH q for net > 0 and for gross beating random selection")
        for s, r in rows.items():
            (n_m, n_lo, _), (g_m, g_lo, _), (h1, h2) = r["net"], r["gross"], r["h"]
            qn, qs = q_net.get(s, float("nan")), q_sel.get(s, float("nan"))
            if r["n"] < 50:
                verdict = "unclear (n < 50)"
            elif n_lo > 0 and h1 > 0 and h2 > 0:
                verdict = "keep"
            elif g_lo > 0 and n_m <= 0:
                verdict = "fix (gross > 0, cost eats it)"
            elif g_m <= 0 and not qs <= 0.05:
                verdict = "cut"
            else:
                verdict = "unclear"
            print(f"    {s:18s} n {r['n']:6d} | net {n_m:+.3f} q {qn:.3f} | gross {g_m:+.3f} | "
                  f"vs random q {qs:.3f} | {verdict}")
        print(f"\n  by family, net R ('{exit_name}'), n >= 30:")
        for (s, fam), g in e[(e["source"] != "random") & (e["cost"] == "net")].groupby(
            ["strategy", "family"]
        ):
            if len(g) >= 30:
                m, lo, hi = mean_ci(g["r"], g["when"], n=300)
                print(f"    {s:18s} {fam:12s} n {len(g):5d} net {m:+.3f} [{lo:+.3f}, {hi:+.3f}]")

    print("\n" + "=" * 110)
    print("WHERE THE INTENTS CAME FROM (ships exit, net):")
    e = mk[(mk["exit"] == "ships") & (mk["cost"] == "net") & (mk["source"] != "random")]
    for (s, src), g in e.groupby(["strategy", "source"]):
        print(f"  {s:18s} {src:10s} n {len(g):6d} mean R {g['r'].mean():+.3f}")


def run() -> None:
    from till_infinity.trading.config import Settings

    settings = Settings.from_env()
    jn = sqlite3.connect(f"file:{JOURNAL}?mode=ro", uri=True, timeout=300.0)
    spread = spreads(jn)
    live = taken(jn)
    mine = intents(jn)
    frame = pd.DataFrame(mine)
    rng = np.random.default_rng(SEED)
    rnd = random_null(jn, settings, frame[frame["interval"].isin(ENTRIES)], rng) if len(frame) else []
    jn.close()
    print(f"{len(live)} closed trades; {len(mine):,} intents across "
          f"{frame['strategy'].nunique() if len(frame) else 0} strategies; {len(rnd):,} random picks",
          flush=True)
    print(frame.groupby(["strategy", "source"]).size().to_string() if len(frame) else "", flush=True)
    df = pd.DataFrame(replay(mine + rnd, spread))
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_pickle(OUT / "triage.pkl.gz")  # our own output, read back only by PART=report
    live.to_pickle(OUT / "live.pkl.gz")
    report(df, live)


if __name__ == "__main__":
    if os.environ.get("PART") == "report":
        report(pd.read_pickle(OUT / "triage.pkl.gz"), pd.read_pickle(OUT / "live.pkl.gz"))
    else:
        run()
