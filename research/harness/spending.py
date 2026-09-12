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
import math
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


def _standard_error(pairs: list[tuple[float, float]]) -> float:
    """Delta-method standard error of `on_risk`, which is a ratio of sums.

    Linearised about the ratio: with `u_i = p_i - R*r_i` the numerator's error
    and the denominator's move together, `sum(u) = 0` by construction, and
    `Var(R) ~ n*var(u)/Q^2`. Cheap enough to evaluate inside every bootstrap
    resample, which is what the studentised interval needs.
    """
    risk = sum(r for _, r in pairs)
    if risk <= 0 or len(pairs) < 2:
        return 0.0
    ratio = sum(p for p, _ in pairs) / risk
    spread = statistics.pvariance([p - ratio * r for p, r in pairs])
    return math.sqrt(len(pairs) * spread) / risk


def interval(pairs: list[tuple[float, float]], *, seed: int = 1) -> tuple[float, float] | None:
    """A 95% **studentised** bootstrap interval on `on_risk`, or None if too few.

    Resampled as pairs rather than as ratios: the denominator varies between
    closes, and resampling a ratio throws away the fact that a close risking
    three times as much carries three times the weight in the pooled figure.

    **Studentised rather than percentile, and that choice decided three of this
    folder's findings.** `research/calibrating.md` measured the percentile
    endpoints over-rejecting on this book - **7.05%** at n=29 and **10.55%** at
    n=8 against a nominal 5% - because the statistic is a ratio of sums over a
    skewed, heavy-tailed distribution and the percentile method assumes away
    exactly the asymmetry that produces. Dividing each resample by its own
    standard error removes the scale the skew rides on, and restores **4.75%**
    at n=29.

    `research/auditing.md` then found what that cost. `spending.md`'s `snap` row
    went from `[-64.7%, -1.4%]` to `[-65.2%, +8.2%]` on this change alone,
    before any multiplicity correction - so it never needed the twelve-row
    argument to fall. The 2:1 band and `confluence-scalp`'s roster decision
    turn on endpoints inside the same gap.

    Falls back to the percentile endpoints when a resample's error is
    degenerate, which happens when every close in it carries the same outcome.
    Reported that way rather than silently: a fallback that cannot be seen is
    how a method ends up trusted at a coverage it does not have.
    """
    if len(pairs) < 8:
        return None
    point = on_risk(pairs)
    error = _standard_error(pairs)
    if error <= 0:
        return None
    rand = random.Random(seed)
    scores: list[float] = []
    plain: list[float] = []
    for _ in range(DRAWS):
        drawn = rand.choices(pairs, k=len(pairs))
        got = on_risk(drawn)
        plain.append(got)
        spread = _standard_error(drawn)
        if spread > 0:
            scores.append((got - point) / spread)
    if len(scores) < DRAWS // 2:  # too many degenerate resamples to studentise
        plain.sort()
        return plain[int(DRAWS * 0.025)], plain[int(DRAWS * 0.975)]
    scores.sort()
    low = scores[int(len(scores) * 0.975)]
    high = scores[int(len(scores) * 0.025)]
    # The t quantiles enter with their signs reversed: a resample landing high
    # implies the truth sits low. Getting this backwards is the classic way to
    # publish a studentised interval that is the percentile one mirrored.
    return point - low * error, point - high * error


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


#: Planned reward-to-risk bands. Chosen at the natural boundaries - below
#: parity, the ordinary range, and ambitious - before any number was cut by
#: them, because `winning.md` has already shown that a scan over this book does
#: not clear its own noise floor and a band picked after the fact would be that
#: scan with one survivor reported.
BANDS: tuple[tuple[str, float, float], ...] = (
    ("below 1:1", 0.0, 1.0),
    ("1:1 to 2:1", 1.0, 2.0),
    ("2:1 and above", 2.0, float("inf")),
)


def banded(rows: list[dict[str, Any]], label: str) -> None:
    """Outcome by the reward-to-risk the order was written at.

    The ratio is worth cutting by precisely because no strategy chooses it:
    targets are placed at structure, so it is set by how far the next level
    happens to be. A book that sizes or selects on it is treating an output of
    the level geometry as a decision.
    """
    print(f"## {label}\n")
    print(f"  {'band':16} {'n':>4} {'hit':>7} {'on risk':>9} {'95%':>22} {'plan':>7} {'payoff':>8}")
    for name, low, high in BANDS:
        part = [
            row
            for row in rows
            if row.get("reward_to_risk")
            and low <= float(row["reward_to_risk"]) < high
            and row.get("profit") is not None
            and float(row.get("risk_money") or 0) > 0
        ]
        if not part:
            continue
        pairs = [(float(row["profit"]), float(row["risk_money"])) for row in part]
        got = [p / r for p, r in pairs]
        wins = [g for g in got if g > 0]
        losses = [g for g in got if g < 0]
        payoff = (
            abs(statistics.mean(wins) / statistics.mean(losses))
            if wins and losses
            else float("nan")
        )
        print(
            f"  {name:16} {len(part):4} {len(wins) / len(got) * 100:6.1f}% "
            f"{on_risk(pairs) * 100:+8.1f}% {band(pairs):>22} "
            f"{statistics.median(float(row['reward_to_risk']) for row in part):7.2f} "
            f"{payoff:8.3f}"
        )
    print()


def kept(rows: list[dict[str, Any]], label: str) -> None:
    """What each exit aimed at against what it actually collected.

    The point of pairing them: an exit kind's mean says whether it was a good
    day, and the ratio says whether the rule that fired was the rule the trade
    was sized for. A clock that lands at 5% of the target it replaced is not an
    exit policy, it is the absence of one.
    """
    print(f"## {label}\n")
    print(f"  {'exit':12} {'n':>4} {'planned':>9} {'realised':>9} {'kept':>7}")
    grouped: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for row in rows:
        if row.get("reward_to_risk") and float(row.get("risk_money") or 0) > 0:
            grouped[str(row.get("exit_kind") or "unknown")].append(row)
    for name, part in sorted(grouped.items(), key=lambda kv: -len(kv[1])):
        aimed = statistics.median(float(row["reward_to_risk"]) for row in part)
        took = statistics.median(float(row["profit"]) / float(row["risk_money"]) for row in part)
        print(
            f"  {name:12} {len(part):4} {aimed:+9.3f} {took:+9.3f} "
            f"{took / aimed * 100 if aimed else 0:6.0f}%"
        )
    print()


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
    banded(real, "Real markets by the reward-to-risk the trade was planned at")
    cut_by(real, "strategy", "Real markets by strategy")
    cut_by(real, "exit_kind", "Real markets by how the trade ended")
    kept(real, "What each exit kind aimed at and what it collected")


if __name__ == "__main__":
    main()
