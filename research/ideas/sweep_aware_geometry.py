"""Should `sweep-aware` widen its stop, or its target, or neither?

Asked on 2026-10-10. The target half already has an answer in the strategy's own
docstring and it is **no**: `target_multiple = 6.0` is documented as far past the
p99 of what touches reach, so the target is not what ends these trades - the
`trail_vol = 0.5` exit is - and the reward-to-risk bands say wider is worse,
because above 3.0 RR the win rate falls from 61-63% to 45%.

The stop half has no answer, and the premise for asking is good: `max_against_vol`
carries the note that "nine of its twelve trades were stopped, more than any
other strategy here". Twelve trades is not a record. There are over 1,800
outcomes in the journal now.

## What this measures

Everything is read from the paired decision and outcome entries, the way
`trading/report.py` builds a `Trade` - outcomes carry what happened and decisions
carry what was intended, and only the pair has both the strategy and the risk it
was sized for.

1. **How these trades end.** `exit_source` and `reason` over every close. If the
   stop rarely ends them, widening it cannot matter much whatever else is true.
2. **Stop-outs against the rest**, in R. A stop that ends a trade at -1R is doing
   its job; the question is whether the trades it ends were going to come back.
3. **By reward-to-risk band**, reproducing the table in the strategy's docstring
   so the method is checkable against a number someone already published.
4. **By hold time**, because a stop that fires early and a stop that fires after
   an hour are different failures - the first is noise, the second is a view
   that was wrong.

## What it cannot settle

Whether a *wider* stop would have saved a stopped trade needs the path after the
stop, which a closed-trade record does not carry. `reactions.Episode` does -
it follows every touch for `EPISODE_BARS` both ways - so the honest version of
this question is asked there, and this harness is the cheaper screen that says
whether it is worth asking.

**And attribution is the trap.** `DEFAULT_MAGIC` is 777701; reading a magic
against 777700 shifts every strategy to its neighbour in `MAGIC_ORDER`, and every
neighbour is a plausible name, so the mistake reads as a finding. This reads the
`strategy` field the decision recorded rather than doing that arithmetic.

Runs on the lab. Production has two cores and a 2.6GB container limit, and
research on it OOM-killed the live desk three times - see `research/starving.md`.
"""

from __future__ import annotations

import json
import os
import statistics
from collections import Counter, defaultdict
from pathlib import Path

#: The extracted decision and outcome entries, one JSON object a line. Produced
#: from the journal on the instance rather than read here: `journal.db` is 2.5GB
#: and the two kinds that matter are 5,087 rows.
SOURCE = Path(os.environ.get("TRADES", "trades.jsonl"))

#: The strategy under the microscope, overridable so the same harness answers
#: the question for any of them.
STRATEGY = os.environ.get("STRATEGY", "sweep-aware")

#: Closed trades below which a rate is not quoted. `report.ENOUGH`'s reasoning:
#: not significance, just the point where a percentage misleads more than the
#: count informs.
ENOUGH = 30


def load(path: Path) -> list[dict]:
    """Pair every outcome to its decision, as `trading/report.trades` does."""
    decisions: dict[str, dict] = {}
    outcomes: list[dict] = []
    with path.open() as fh:
        for line in fh:
            row = json.loads(line)
            try:
                row["ctx"] = json.loads(row["context"]) if row["context"] else {}
            except (TypeError, ValueError):
                row["ctx"] = {}
            if row["kind"] == "decision":
                decisions[row["id"]] = row
            else:
                outcomes.append(row)

    trades: list[dict] = []
    for outcome in outcomes:
        parent = decisions.get(outcome.get("parent") or "")
        if parent is None:
            continue
        ctx = {**parent["ctx"], **outcome["ctx"]}
        risk = float(ctx.get("risk_money") or 0.0)
        if risk <= 0:
            # The decision knew the sizing even when the close spread a zero
            # over it - 56% of the record was invisible to every report until
            # that fallback existed. Measured 2026-10-04.
            risk = float(parent["ctx"].get("risk_money") or 0.0)
        if risk <= 0:
            continue
        profit = float(ctx.get("profit") or 0.0)
        trades.append(
            {
                "strategy": str(ctx.get("strategy") or "unknown"),
                "feed": str(ctx.get("feed") or ""),
                "mode": str(ctx.get("mode") or "paper"),
                "r": profit / risk,
                "profit": profit,
                "seconds": float(ctx.get("seconds") or 0.0),
                "reason": str(ctx.get("reason") or ""),
                "exit_source": str(ctx.get("exit_source") or ""),
                "rr": float(ctx.get("reward_to_risk") or 0.0),
                "opened": float(parent["time"]),
            }
        )
    trades.sort(key=lambda t: t["opened"])
    return trades


def band(rows: list[dict], label: str) -> str:
    if not rows:
        return f"  {label:<22} n=   0"
    n = len(rows)
    wins = sum(1 for t in rows if t["r"] > 0)
    mean = statistics.fmean(t["r"] for t in rows)
    total = sum(t["r"] for t in rows)
    rate = f"{wins / n:>4.0%}" if n >= ENOUGH else f"{wins}/{n}"
    return f"  {label:<22} n={n:>4}  win {rate:>6}  mean R {mean:+.3f}  total R {total:+8.2f}"


def main() -> None:
    trades = load(SOURCE)
    mine = [t for t in trades if t["strategy"] == STRATEGY]
    print(f"{len(trades)} closed trades in the record, {len(mine)} from {STRATEGY!r}\n")
    if not mine:
        print("strategies present:", Counter(t["strategy"] for t in trades).most_common())
        return

    live = [t for t in mine if t["mode"] != "paper"]
    print(band(mine, "all"))
    print(band(live, "live only"))
    print()

    print("=== 1. how these trades end ===")
    for key in ("exit_source", "reason"):
        print(f"  by {key}:")
        groups = defaultdict(list)
        for t in mine:
            groups[t[key] or "(blank)"].append(t)
        for name, rows in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            print("  " + band(rows, name))
        print()

    print("=== 2. stop-outs against everything else ===")
    stopped = [t for t in mine if "stop" in (t["exit_source"] + t["reason"]).lower()]
    other = [t for t in mine if t not in stopped]
    print(band(stopped, "stopped"))
    print(band(other, "ended otherwise"))
    if stopped:
        share = len(stopped) / len(mine)
        print(f"\n  stops end {share:.1%} of these trades")
        print("  a wider stop can only matter in proportion to that share")

    print("\n=== 3. by reward-to-risk band (reproducing the docstring's table) ===")
    edges = [(0.0, 1.1), (1.1, 1.5), (1.5, 2.0), (2.0, 3.0), (3.0, 1e9)]
    for low, high in edges:
        rows = [t for t in mine if low <= t["rr"] < high]
        print(band(rows, f"RR {low:.1f}-{high:.1f}" if high < 1e9 else f"RR {low:.1f}+"))
    rrs = [t["rr"] for t in mine if t["rr"] > 0]
    if rrs:
        print(f"\n  median reward-to-risk {statistics.median(rrs):.2f}")

    print("\n=== 4. by hold time: noise or a wrong view? ===")
    for low, high, label in (
        (0.0, 300.0, "under 5 min"),
        (300.0, 1800.0, "5-30 min"),
        (1800.0, 7200.0, "30 min - 2h"),
        (7200.0, 1e9, "over 2h"),
    ):
        rows = [t for t in stopped if low <= t["seconds"] < high]
        print(band(rows, f"stopped, {label}"))

    print("\n=== 5. the same bands for every strategy, for contrast ===")
    by_strategy = defaultdict(list)
    for t in trades:
        by_strategy[t["strategy"]].append(t)
    for name, rows in sorted(by_strategy.items(), key=lambda kv: -len(kv[1]))[:8]:
        hit = [t for t in rows if "stop" in (t["exit_source"] + t["reason"]).lower()]
        share = len(hit) / len(rows) if rows else 0.0
        print(f"  {name:<20} n={len(rows):>4}  stopped {share:>5.1%}  mean R {statistics.fmean(t['r'] for t in rows):+.3f}")


if __name__ == "__main__":
    main()
