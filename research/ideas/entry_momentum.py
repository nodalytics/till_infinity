"""Does momentum at the entry predict the trade? See `docs/entry-momentum.md`.

Production refuses a trade when `pressure_vol` - the accumulated run measured by
`structures.cusum` - is more than `max_against_vol` against it. The desk asked
whether that limit should be tighter, and whether the mirror case needs a gate
of its own: entering *with* a large run, which is chasing a move that has
already happened.

Both are answered the same way and the answer is no, but only after a
discovery / confirmation split. Pooled, tightening the limit looks like it
removes the entire loss. It does not survive being tested on the half it was
not chosen on, and the threshold's sign flips inside the discovery half, which
is what a fitted number looks like.

Read from the host bind-mount; see `loss_anatomy.py` on why not `docker exec`.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import random
import sqlite3
import statistics as st
from collections import defaultdict

DB = os.environ.get("JOURNAL_DB", os.path.expanduser("~/till-data/journal/journal.db"))
DRAWS = 3000
#: Limits to try, in volatility units. Production runs 1.5.
LIMITS = (0.5, 0.75, 1.0, 1.25, 1.5, 2.0)


def _num(x) -> float | None:
    return float(x) if isinstance(x, int | float) and x == x else None


def trades(db: str = DB) -> list[dict]:
    """Closed trades carrying `pressure_vol`, signed against the trade's side."""
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
            risk = _num(o.get("risk_money")) or _num(d.get("risk_money"))
            pressure = _num(d.get("pressure_vol"))
            if profit is None or not risk or risk <= 0 or pressure is None:
                continue
            # The gate's own convention: a buy is opposed by downward pressure.
            sign = 1 if "buy" in str(d.get("side", "")).lower() else -1
            against = -pressure if sign > 0 else pressure
            out.append(
                dict(time=float(r["time"]), day=int(r["time"] // 86400), r=profit / risk,
                     profit=profit, against=against, with_=-against,
                     strategy=d.get("strategy", "?"))
            )
        out.sort(key=lambda t: t["time"])
        return out
    finally:
        con.close()


def block(rows, pick, rng, draws: int = DRAWS):
    """Mean with a day-block interval. Trades share a day and a regime."""
    by = defaultdict(lambda: [0.0, 0])
    for t in rows:
        by[t["day"]][0] += pick(t)
        by[t["day"]][1] += 1
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
    return st.fmean(pick(t) for t in rows), got[int(0.05 * draws)], got[int(0.95 * draws)]


def bands(rows, key, label, rng) -> None:
    """Outcome by quintile of `key`, so the shape is visible before any threshold."""
    vals = sorted(key(t) for t in rows)
    edges = [vals[int(q * len(vals))] for q in (0.0, 0.2, 0.4, 0.6, 0.8)] + [float("inf")]
    print(f"\n=== outcome by {label} ===")
    print(f"  {'band':<18}{'n':>5}{'profit':>10}{'mean R':>9}{'90% interval':>22}{'won':>6}")
    for lo, hi in zip(edges, edges[1:], strict=False):
        sel = [t for t in rows if lo <= key(t) < hi]
        if len(sel) < 40:
            continue
        got = block(sel, lambda t: t["r"], rng)
        name = f"{lo:+.2f} to {hi:+.2f}" if hi != float("inf") else f"{lo:+.2f}+"
        ci = f"[{got[1]:+.3f}, {got[2]:+.3f}]" if got else "-"
        print(f"  {name:<18}{len(sel):>5}{sum(t['profit'] for t in sel):>10.2f}"
              f"{st.fmean(t['r'] for t in sel):>9.3f}{ci:>22}"
              f"{sum(1 for t in sel if t['profit'] > 0) / len(sel):>6.0%}")


def main() -> None:
    rng = random.Random(9)
    T = trades()
    print(f"{len(T)} closed trades carry pressure_vol, net {sum(t['profit'] for t in T):+.2f}")
    bands(T, lambda t: t["against"], "momentum against the trade (what the gate reads)", rng)
    bands(T, lambda t: t["with_"], "momentum with the trade (chasing; no gate exists)", rng)

    print("\n=== pooled: what a limit would have refused ===")
    print(f"  {'rule':<22}{'refused':>9}{'their R':>10}{'kept R':>9}{'kept profit':>13}")
    print(f"  {'nothing refused':<22}{0:>9}{'-':>10}"
          f"{st.fmean(t['r'] for t in T):>9.3f}{sum(t['profit'] for t in T):>13.2f}")
    for name, key in (("against", lambda t: t["against"]), ("with", lambda t: t["with_"])):
        for limit in LIMITS:
            out = [t for t in T if key(t) > limit]
            keep = [t for t in T if key(t) <= limit]
            if len(out) < 25 or len(keep) < 50:
                continue
            print(f"  {f'{name} > {limit:g}v':<22}{len(out):>9}"
                  f"{st.fmean(t['r'] for t in out):>10.3f}"
                  f"{st.fmean(t['r'] for t in keep):>9.3f}"
                  f"{sum(t['profit'] for t in keep):>13.2f}")

    # **The split is the whole study.** A threshold chosen on everything is a
    # threshold fitted to everything, and this one looks decisive until it is
    # asked about data it did not see.
    half = len(T) // 2
    disc, conf = T[:half], T[half:]
    when = dt.datetime.fromtimestamp(T[half]["time"], dt.UTC).strftime("%Y-%m-%d %H:%M")
    print(f"\n=== discovery {len(disc)} / confirmation {len(conf)}, split at {when} UTC ===")
    print(f"  {'limit':<8}{'half':<14}{'refused':>8}{'their R':>10}{'kept R':>9}"
          f"{'kept 90% ci':>22}{'kept profit':>13}")
    for limit in LIMITS:
        for name, rows in (("discovery", disc), ("confirmation", conf)):
            out = [t for t in rows if t["against"] > limit]
            keep = [t for t in rows if t["against"] <= limit]
            if len(out) < 15 or len(keep) < 50:
                continue
            got = block(keep, lambda t: t["r"], rng)
            ci = f"[{got[1]:+.3f}, {got[2]:+.3f}]" if got else "-"
            print(f"  {limit:<8g}{name:<14}{len(out):>8}"
                  f"{st.fmean(t['r'] for t in out):>10.3f}"
                  f"{st.fmean(t['r'] for t in keep):>9.3f}{ci:>22}"
                  f"{sum(t['profit'] for t in keep):>13.2f}")
        print()
    for name, rows in (("discovery", disc), ("confirmation", conf)):
        got = block(rows, lambda t: t["r"], rng)
        ci = f"  [{got[1]:+.3f}, {got[2]:+.3f}]" if got else ""
        print(f"  {name:<14} baseline n={len(rows):<5} mean R "
              f"{st.fmean(t['r'] for t in rows):+.3f}  "
              f"profit {sum(t['profit'] for t in rows):+.2f}{ci}")


if __name__ == "__main__":
    main()
