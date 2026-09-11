"""Where the book spends its trades, and what each half gives back.

Reads the closes export rather than the journal, because the export carries
`risk_money` beside `profit` and that pairing is what makes two instruments
comparable. A P&L on its own compares position sizes.

## What would have killed this

Stated before the numbers were looked at:

* **If the real-market half's sign moves when the sample is restricted to
  closes carrying a risk figure**, the result is a statement about which closes
  carry that field and nothing else, and the page should not be written. Both
  halves are reported with and without the restriction for exactly this reason.
* **If the loss is five closes**, it is one bad week and not a property of the
  book. The five largest and five smallest are reported separately and the
  trimmed figure is given.
* **If one strategy carries it**, the finding is about that strategy rather
  than about real markets, and should be named that way.
* **If a bootstrap interval on the real-market half includes zero**, nothing
  here is resolved and the page says so.

Run: `.venv/bin/python research/harness/spending.py [path/to/closes.json]`
"""

from __future__ import annotations

import collections
import json
import random
import re
import statistics
import sys
from pathlib import Path
from typing import Any

#: Feeds the venue generates rather than quotes. `research/deriving.md` proves
#: a predictable position on one of these has expectancy `-(c/2) * turnover`,
#: for every stop, target, trail, entry filter and sizing rule - so the only
#: interesting question about this half is how much of the book it is.
GENERATED = re.compile(r"^(volatility|jump|boom|crash|step|range_break)_", re.I)

#: Bootstrap resamples. Twenty thousand because the statistic is a ratio of
#: sums and its sampling distribution is skewed; a thousand leaves the tail
#: quantiles visibly noisy between seeds.
DRAWS = 20_000


def generated(feed: object) -> bool:
    return bool(GENERATED.match(str(feed or "")))


def load(path: Path) -> list[dict[str, Any]]:
    rows = json.loads(path.read_text())
    return [row.get("ctx", {}) for row in rows if isinstance(row, dict)]


def payable(rows: list[dict[str, Any]]) -> list[tuple[float, float]]:
    """`(profit, risk)` for the closes where both are known.

    Both, not either. A close with a P&L and no risk figure cannot be put in
    units of what it risked, and pooling it with ones that can compares two
    different quantities.
    """
    out = []
    for row in rows:
        risk = float(row.get("risk_money") or 0.0)
        if row.get("profit") is None or risk <= 0:
            continue
        out.append((float(row["profit"]), risk))
    return out


def on_risk(pairs: list[tuple[float, float]]) -> float:
    """P&L as a share of the risk that was deployed to earn it."""
    risk = sum(r for _, r in pairs)
    return sum(p for p, _ in pairs) / risk if risk else 0.0


def interval(pairs: list[tuple[float, float]], *, seed: int = 1) -> tuple[float, float] | None:
    """A 95% bootstrap interval on `on_risk`, or None when there is too little.

    Resampled as pairs rather than as ratios: the denominator varies between
    closes, and resampling a ratio throws away the fact that a close risking
    three times as much carries three times the weight in the pooled figure.
    """
    if len(pairs) < 8:
        return None
    rand = random.Random(seed)
    draws = sorted(on_risk(rand.choices(pairs, k=len(pairs))) for _ in range(DRAWS))
    return draws[int(DRAWS * 0.025)], draws[int(DRAWS * 0.975)]


def band(pairs: list[tuple[float, float]]) -> str:
    got = interval(pairs)
    return f"[{got[0] * 100:+.1f}%, {got[1] * 100:+.1f}%]" if got else "too few to say"


def halves(rows: list[dict[str, Any]]) -> None:
    print("## The two halves, and whether the restriction moves either\n")
    for label, want in (("generated", True), ("real markets", False)):
        half = [row for row in rows if generated(row.get("feed")) is want]
        with_risk = payable(half)
        keyed = {id(row) for row in half if float(row.get("risk_money") or 0) > 0}
        rest = [row for row in half if id(row) not in keyed]
        total = sum(float(row.get("profit") or 0.0) for row in half)
        print(f"  {label}")
        print(f"    every close        n={len(half):4}  P&L {total:+9.2f}")
        print(
            f"    with a risk figure n={len(with_risk):4}  P&L "
            f"{sum(p for p, _ in with_risk):+9.2f}"
            f"  = {on_risk(with_risk) * 100:+6.1f}% of risk   95% {band(with_risk)}"
        )
        print(
            f"    without one        n={len(rest):4}  P&L "
            f"{sum(float(row.get('profit') or 0.0) for row in rest):+9.2f}"
        )
        print()


def geometry(rows: list[dict[str, Any]], pairs: list[tuple[float, float]], label: str) -> None:
    """Hit rate against payoff, measured and as planned.

    Both, because they answer different questions. The measured payoff says
    whether the book clears its own costs. The *planned* one - `reward_to_risk`,
    written at entry - says whether the hit rate was ever the problem: a book
    hitting 40% needs a 1.5:1 payoff, and if it planned 1.36:1 and realised
    0.70:1 then the entries are close to adequate and the exits are not.
    """
    wins = [(p, r) for p, r in pairs if p > 0]
    losses = [(p, r) for p, r in pairs if p < 0]
    if not wins or not losses:
        return
    up = statistics.mean(p / r for p, r in wins)
    down = statistics.mean(p / r for p, r in losses)
    hit = len(wins) / (len(wins) + len(losses))
    payoff = abs(up / down)
    need = 1 / (1 + payoff)
    print(f"## {label}: what it wins against what it loses\n")
    print(f"  wins   n={len(wins):4}  mean {up * 100:+6.1f}% of risk")
    print(f"  losses n={len(losses):4}  mean {down * 100:+6.1f}% of risk")
    print(f"  hit rate {hit * 100:.1f}%, payoff {payoff:.2f}:1")
    print(f"  break-even at that payoff needs {need * 100:.1f}%")
    print(f"  short by {(hit - need) * 100:+.1f} points\n")

    # From the same closes the hit rate came from. Pooling in entries with no
    # risk figure would compare a payoff planned on one set of trades against a
    # hit rate measured on another.
    planned = [
        float(row["reward_to_risk"])
        for row in rows
        if row.get("reward_to_risk")
        and row.get("profit") is not None
        and float(row.get("risk_money") or 0) > 0
    ]
    if not planned:
        return
    aimed = statistics.median(planned)
    at_plan = 1 / (1 + aimed)
    print(f"  planned payoff, median of {len(planned)} entries: {aimed:.2f}:1")
    print(f"  that payoff would need {at_plan * 100:.1f}%, and the book hits {hit * 100:.1f}%")
    print(f"  so at the payoff it aims for it is short by {(hit - at_plan) * 100:+.1f} points\n")


def concentration(pairs: list[tuple[float, float]], label: str) -> None:
    ordered = sorted(pairs, key=lambda pair: pair[0])
    worst, best = ordered[:5], ordered[-5:]
    trimmed = ordered[5:]
    print(f"## {label}: is it five closes?\n")
    print(
        f"  five worst {sum(p for p, _ in worst):+9.2f}   five best {sum(p for p, _ in best):+9.2f}"
    )
    print(f"  without the five worst: {on_risk(trimmed) * 100:+.1f}% of risk\n")


def cut_by(rows: list[dict[str, Any]], field: str, label: str) -> None:
    print(f"## {label}\n")
    grouped: dict[str, list[tuple[float, float]]] = collections.defaultdict(list)
    for row in rows:
        risk = float(row.get("risk_money") or 0.0)
        if row.get("profit") is None or risk <= 0:
            continue
        grouped[str(row.get(field) or "unknown")].append((float(row["profit"]), risk))
    for name, pairs in sorted(grouped.items(), key=lambda kv: -len(kv[1])):
        print(
            f"  {name:20} n={len(pairs):4} {sum(p for p, _ in pairs):+9.2f} on "
            f"{sum(r for _, r in pairs):8.2f} = {on_risk(pairs) * 100:+7.1f}%"
            f"   95% {band(pairs)}"
        )
    print()


def main() -> None:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else ".data/closes.json")
    rows = load(path)
    print(f"{path}: {len(rows)} closes\n")
    halves(rows)
    real = [row for row in rows if not generated(row.get("feed"))]
    pairs = payable(real)
    geometry(real, pairs, "Real markets")
    concentration(pairs, "Real markets")
    cut_by(real, "strategy", "Real markets by strategy")
    cut_by(real, "exit_kind", "Real markets by how the trade ended")


if __name__ == "__main__":
    main()
