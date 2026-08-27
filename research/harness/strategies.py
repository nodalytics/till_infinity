"""Score each strategy from the journal, on the trades it actually took.

The in-log day counter resets whenever the container is recreated, and this
session has deployed many times - so it reads `0/1` on a day with more trades
than that behind it. The journal spans restarts, and every outcome carries the
strategy that opened it, so this is the record that can be trusted.

Reports the number that matters more than profit at this sample size: **R
realised against R risked**. A trade sized to lose $24 that loses $32 has an
execution leak worth naming, and money alone hides it behind position size.

Usage: python -m research.harness.strategies [journal.db]
"""

import json
import sqlite3
import sys
from collections import defaultdict

def load(db):
    con = sqlite3.connect(db)
    q = "select context from entries where actor='trading' and kind='outcome'"
    out = []
    for (ctx,) in con.execute(q):
        d = json.loads(ctx or "{}")
        if d.get("profit") is None:
            continue
        out.append(d)
    return out


def main():
    db = sys.argv[1] if len(sys.argv) > 1 else ".data/journal/journal.db"
    rows = load(db)
    if not rows:
        print("no closed trades in the journal")
        return
    print(f"{len(rows)} closed trades\n")

    by = defaultdict(list)
    for d in rows:
        by[d.get("strategy") or "[unattributed]"].append(d)

    print(f"{'strategy':>18s} {'n':>3s} {'won':>4s} {'money':>9s} {'R':>7s} {'worst':>7s} {'exits'}")
    print("-" * 78)
    order = sorted(by, key=lambda k: -sum(x["profit"] for x in by[k]))
    for name in order:
        got = by[name]
        money = sum(x["profit"] for x in got)
        won = sum(1 for x in got if x["profit"] > 0)
        # R realised: profit over the money the trade was *sized* to risk. The
        # gap between this and the intended +/-1 is execution, not thesis.
        rs = [x["profit"] / x["risk_money"] for x in got if x.get("risk_money")]
        total_r = sum(rs)
        worst = min(rs) if rs else 0.0
        kinds = defaultdict(int)
        for x in got:
            kinds[x.get("exit_kind") or "?"] += 1
        shape = " ".join(f"{k}:{v}" for k, v in sorted(kinds.items()))
        print(
            f"{name:>18s} {len(got):>3d} {won:>4d} {money:>9.2f} {total_r:>7.2f} {worst:>7.2f}  {shape}"
        )

    print("-" * 78)
    money = sum(x["profit"] for x in rows)
    rs = [x["profit"] / x["risk_money"] for x in rows if x.get("risk_money")]
    print(f"{'all':>18s} {len(rows):>3d} {sum(1 for x in rows if x['profit'] > 0):>4d} "
          f"{money:>9.2f} {sum(rs):>7.2f}")

    # The leak the money column hides: a stop that costs more than 1R.
    stopped = [x for x in rows if x.get("exit_kind") == "stop" and x.get("risk_money")]
    if stopped:
        over = [abs(x["profit"] / x["risk_money"]) for x in stopped]
        print(f"\nstopped trades: {len(stopped)}, mean cost {sum(over) / len(over):.2f}R")
        print("a stop should cost 1.00R; more than that is slippage on the way in or out")


if __name__ == "__main__":
    main()
