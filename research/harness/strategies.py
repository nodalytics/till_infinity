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


def classify(d):
    """The exit kind, recomputed when the record predates the field.

    Sixteen of the first thirty-two outcomes carry no `exit_kind`, and no
    `strategy` either - they were written before either field existed. The
    field cannot be backfilled at the source, but it does not need to be: entry,
    stop, target and exit are all on the record, and the classification is a
    pure function of them. So old rows are classified here by the same rule the
    service uses, and marked as inferred rather than passed off as recorded.

    Two limits worth stating. A row whose `exit_source` is "last seen" has an
    exit price the service inferred rather than read from the broker - the
    position was gone between polls - so the classification inherits that
    uncertainty. And nothing recomputed here can recover *stale* or *hold*,
    which are facts about which rule fired rather than about where price
    ended; an old row that reads "hold" means only that it reached neither
    level.
    """
    got = d.get("exit_kind")
    if got:
        return got, False
    stop, target = d.get("stop"), d.get("target")
    exit_at, side = d.get("exit"), d.get("side")
    if exit_at is None or side not in ("buy", "sell"):
        return "unknown", True
    sign = 1.0 if side == "buy" else -1.0
    if stop and (exit_at - stop) * sign <= 0:
        return "stop", True
    if target and (exit_at - target) * sign >= 0:
        return "target", True
    if not stop and not target:
        return "unknown", True
    return "hold", True


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

    print(
        f"{'strategy':>18s} {'n':>3s} {'won':>4s} {'money':>9s} {'R':>7s} {'worst':>7s} {'exits'}"
    )
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
            kind, _ = classify(x)
            kinds[kind] += 1
        shape = " ".join(f"{k}:{v}" for k, v in sorted(kinds.items()))
        print(
            f"{name:>18s} {len(got):>3d} {won:>4d} {money:>9.2f} "
            f"{total_r:>7.2f} {worst:>7.2f}  {shape}"
        )

    print("-" * 78)
    money = sum(x["profit"] for x in rows)
    rs = [x["profit"] / x["risk_money"] for x in rows if x.get("risk_money")]
    print(
        f"{'all':>18s} {len(rows):>3d} {sum(1 for x in rows if x['profit'] > 0):>4d} "
        f"{money:>9.2f} {sum(rs):>7.2f}"
    )

    inferred = sum(1 for x in rows if classify(x)[1])
    if inferred:
        print(f"\n{inferred} of {len(rows)} exits classified after the fact - those rows")
        print("predate the field. Recomputed from entry/stop/target/exit, not recorded.")

    # The leak the money column hides: a stop that costs more than 1R.
    stopped = [x for x in rows if classify(x)[0] == "stop" and x.get("risk_money")]
    if stopped:
        over = [abs(x["profit"] / x["risk_money"]) for x in stopped]
        print(f"\nstopped trades: {len(stopped)}, mean cost {sum(over) / len(over):.2f}R")
        print("a stop should cost 1.00R; more than that is slippage on the way in or out")


if __name__ == "__main__":
    main()
