"""What the desk's losses are, from the live journal. See `docs/what-loses.md`.

Pairs every outcome to the decision that sized it and decomposes the result four
ways: the cost of trading against the gross edge, the holding time, the stop
width, and a search over every cut with the multiplicity correction that search
needs.

**Read from the host's bind-mount, never through `docker exec`.** The desk runs
on two cores with a 2.6GB container limit and research inside it has OOM-killed
the live process; `~/till-data` is mounted on the host for exactly this.

Every interval here is a **day block bootstrap**. Trades cluster in days and
share a regime, so an interval over trades is far too narrow - which is how a
study like this talks itself into a finding.
"""

from __future__ import annotations

import json
import os
import random
import sqlite3
import statistics as st
from collections import defaultdict

DB = os.environ.get("JOURNAL_DB", os.path.expanduser("~/till-data/journal/journal.db"))
DRAWS = 4000
#: A cell needs this many trades before it is worth a number at all.
ENOUGH = 40


def trades(db: str = DB) -> list[dict]:
    """Every closed trade with the numbers its decision was sized from."""
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        dec = {}
        for r in con.execute(
            "SELECT id, context FROM entries WHERE actor='trading' AND kind='decision'"
        ):
            try:
                dec[r["id"]] = json.loads(r["context"] or "{}")
            except json.JSONDecodeError:
                pass
        out = []
        for r in con.execute(
            "SELECT parent, time, context FROM entries WHERE actor='trading' AND kind='outcome'"
        ):
            d = dec.get(r["parent"])
            if d is None:
                continue
            try:
                o = json.loads(r["context"] or "{}")
            except json.JSONDecodeError:
                continue
            profit = _num(o.get("profit"))
            # The decision's figure when the outcome's is a restart's zero - see
            # `trading/report.py` on the 839 trades that cost.
            risk = _num(o.get("risk_money")) or _num(d.get("risk_money"))
            if profit is None or not risk or risk <= 0:
                continue
            price = _num(d.get("risk_price"))
            spread = _num(d.get("spread_at_entry")) or 0.0
            out.append(
                dict(
                    day=int(r["time"] // 86400),
                    r=profit / risk,
                    profit=profit,
                    # The spread as a share of the risk, which is the cost in R
                    # and depends on the stop alone - no target changes it.
                    cost=(spread / price) if price else None,
                    secs=_num(o.get("seconds")) or 0.0,
                    adverse=_num(o.get("adverse_r")),
                    best=_num(o.get("best_r")),
                    stop_vol=_num(d.get("stop_vol")),
                    strategy=d.get("strategy", "?"),
                    feed=d.get("feed", "?"),
                    side=d.get("side", "?"),
                    interval=d.get("interval", "?"),
                    source=o.get("exit_source") or "?",
                )
            )
        return out
    finally:
        con.close()


def _num(x) -> float | None:
    return float(x) if isinstance(x, int | float) and x == x else None


def block(rows, pick, rng, draws: int = DRAWS):
    """Mean of `pick` with a day-block interval and a two-sided p against zero.

    Resamples whole days, because a regime lasts longer than a trade.
    """
    vals = [(t["day"], pick(t)) for t in rows]
    vals = [(d, v) for d, v in vals if v is not None]
    if len(vals) < 30:
        return None
    by = defaultdict(lambda: [0.0, 0])
    for d, v in vals:
        by[d][0] += v
        by[d][1] += 1
    days = list(by)
    if len(days) < 4:
        return None
    got = []
    for _ in range(draws):
        total = count = 0.0
        for _ in days:
            s, c = by[days[rng.randrange(len(days))]]
            total += s
            count += c
        got.append(total / count if count else 0.0)
    got.sort()
    mean = sum(v for _, v in vals) / len(vals)
    below = sum(1 for v in got if v <= 0) / len(got)
    return mean, got[int(0.05 * draws)], got[int(0.95 * draws)], 2 * min(below, 1 - below)


def benjamini_hochberg(cells, q: float = 0.10) -> set[int]:
    """Indices of the cells that survive at `q`. A search over cells finds a
    winner every time; this is what stops that being reported as one."""
    order = sorted(range(len(cells)), key=lambda i: cells[i]["p"])
    keep = 0
    for rank, i in enumerate(order, 1):
        if cells[i]["p"] <= q * rank / len(order):
            keep = rank
    return set(order[:keep])


def main() -> None:
    rng = random.Random(11)
    T = trades()
    total = sum(t["profit"] for t in T)
    print(f"{len(T)} closed trades, net {total:+.2f}\n")

    print("=== the cost of trading against the gross edge ===")
    for name, pick in (
        ("realised R", lambda t: t["r"]),
        ("spread in R", lambda t: t["cost"]),
        ("gross (R + cost)", lambda t: None if t["cost"] is None else t["r"] + t["cost"]),
    ):
        got = block(T, pick, rng)
        if got:
            m, lo, hi, _p = got
            flag = "   <- excludes zero" if lo > 0 or hi < 0 else ""
            print(f"  {name:<18}{m:+.4f}  [{lo:+.4f}, {hi:+.4f}]{flag}")

    print("\n=== holding time ===")
    print(f"  {'hold':<9}{'n':>5}{'profit':>10}{'mean R':>9}{'90% interval':>22}{'gross R':>9}")
    for name, lo_s, hi_s in (
        ("<1m", 0, 60), ("1-5m", 60, 300), ("5-30m", 300, 1800),
        ("30m-2h", 1800, 7200), (">2h", 7200, 1e12),
    ):
        sel = [t for t in T if lo_s <= t["secs"] < hi_s]
        if len(sel) < 20:
            continue
        got = block(sel, lambda t: t["r"], rng)
        gross = [t["r"] + t["cost"] for t in sel if t["cost"] is not None]
        ci = f"[{got[1]:+.3f}, {got[2]:+.3f}]" if got else "-"
        print(
            f"  {name:<9}{len(sel):>5}{sum(t['profit'] for t in sel):>10.2f}"
            f"{st.fmean(t['r'] for t in sel):>9.3f}{ci:>22}"
            f"{(st.fmean(gross) if gross else float('nan')):>9.3f}"
        )

    print("\n=== stop width ===")
    print(f"  {'stop_vol':<12}{'n':>5}{'profit':>10}{'mean R':>9}{'won':>6}{'stopped':>9}")
    edges = [0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 8.0, 1e9]
    wide = sorted((t for t in T if t["stop_vol"] is not None), key=lambda t: t["stop_vol"])
    for lo_v, hi_v in zip(edges, edges[1:], strict=False):
        sel = [t for t in wide if lo_v <= t["stop_vol"] < hi_v]
        if len(sel) < 25:
            continue
        stopped = sum(1 for t in sel if t["source"] == "broker" and t["profit"] <= 0)
        won = sum(1 for t in sel if t["profit"] > 0)
        label = f"{lo_v:g}-{hi_v:g}" if hi_v < 1e9 else f"{lo_v:g}+"
        print(
            f"  {label:<12}{len(sel):>5}{sum(t['profit'] for t in sel):>10.2f}"
            f"{st.fmean(t['r'] for t in sel):>9.3f}{won / len(sel):>6.0%}"
            f"{stopped / len(sel):>9.0%}"
        )

    print("\n=== how much heat a winner takes, and whether losers ever worked ===")
    have = [t for t in T if t["adverse"] is not None and t["best"] is not None]
    win = [t for t in have if t["profit"] > 0]
    lose = [t for t in have if t["profit"] <= 0]
    if win:
        heat = sorted(abs(t["adverse"]) for t in win)
        print(f"  {len(win)} winners: median heat {st.median(heat):.3f}R, "
              f"90th {heat[int(0.9 * len(heat))]:.3f}R")
        for level in (0.25, 0.5, 0.75, 1.0):
            k = sum(1 for h in heat if h >= level)
            print(f"    a stop at {level:.2f}R would have killed {k} of them ({k / len(win):.0%})")
    if lose:
        never = sum(1 for t in lose if t["best"] <= 0.05)
        print(f"  {len(lose)} losers: {never / len(lose):.0%} never reached 0.05R in favour, "
              f"so a wider stop would not have saved them")

    print("\n=== every cut, with the correction a search needs ===")
    cells = []
    for family, key in (
        ("strategy", lambda t: t["strategy"]), ("instrument", lambda t: t["feed"]),
        ("entry tf", lambda t: t["interval"]), ("side", lambda t: t["side"]),
    ):
        grouped = defaultdict(list)
        for t in T:
            grouped[key(t)].append(t)
        for name, sel in grouped.items():
            if len(sel) >= ENOUGH:
                cells.append((family, str(name), sel))
    for name, lo_s, hi_s in (
        ("hold <1m", 0, 60), ("hold 1-5m", 60, 300), ("hold 5-30m", 300, 1800),
        ("hold 30m-2h", 1800, 7200), ("hold >2h", 7200, 1e12),
    ):
        sel = [t for t in T if lo_s <= t["secs"] < hi_s]
        if len(sel) >= ENOUGH:
            cells.append(("holding time", name, sel))
    step = max(1, len(wide) // 5)
    for i in range(0, len(wide), step):
        sel = wide[i:i + step]
        if len(sel) >= ENOUGH:
            cells.append(("stop width", f"{sel[0]['stop_vol']:.2f}-{sel[-1]['stop_vol']:.2f}", sel))

    scored = []
    for family, name, sel in cells:
        got = block(sel, lambda t: t["r"], rng)
        if got is None:
            continue
        m, lo, hi, p = got
        scored.append(dict(family=family, name=name, n=len(sel), m=m, lo=lo, hi=hi, p=p,
                           profit=sum(t["profit"] for t in sel)))
    survivors = benjamini_hochberg(scored)
    print(f"  {len(scored)} cells, Benjamini-Hochberg at q=0.10")
    print(f"  {'family':<14}{'cell':<22}{'n':>5}{'profit':>10}{'mean R':>9}"
          f"{'90% interval':>22}{'p':>7}  BH")
    for i, x in sorted(enumerate(scored), key=lambda kv: -kv[1]["m"]):
        ci = f"[{x['lo']:+.3f}, {x['hi']:+.3f}]"
        print(f"  {x['family']:<14}{x['name'][:21]:<22}{x['n']:>5}{x['profit']:>10.2f}"
              f"{x['m']:>9.3f}{ci:>22}{x['p']:>7.3f}  {'YES' if i in survivors else ''}")
    good = [x for x in scored if x["m"] > 0]
    print(f"\n  {len(good)} of {len(scored)} cells have a positive mean R; "
          f"{len([i for i in survivors if scored[i]['m'] > 0])} survive as profitable")


if __name__ == "__main__":
    main()
