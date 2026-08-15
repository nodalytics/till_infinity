"""Does the edge beat "assume the level holds"?

`features.py` found `side` alone predicts direction at 78.8% while all nine
features together manage 77.8%. That makes the trivial rule — a touch from
above pushes back up, a touch from below pushes down, i.e. the level holds — a
baseline nothing here had been measured against.

Scored on identical rows, which the first version of this script did not do: it
used `base_rate_up > 0.5`, the *series* unconditional up-rate, which is not the
per-side rule at all and answered a question nobody asked.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from edge_gate import collect, rate  # noqa: E402


def held(row):
    """The trivial rule. Above means price came down to it and bounces up."""
    return row["above"]


def score(rows, rule):
    decided = [r for r in rows if r["push_vol"]]
    if not decided:
        return 0.0, 0
    hits = sum(1 for r in decided if rule(r) == (r["push_vol"] > 0))
    return hits / len(decided), len(decided)


paired, _, _ = collect()
print(f"{len(paired):,} calls paired with the outcome of the touch they opened\n")

print(f"{'rule':<36} {'n':>6} {'direction right':>17}")
print("-" * 62)
got, n = rate(paired)
print(f"{'the edge sign (what we publish)':<36} {n:>6} {got:>16.1%}")
got, n = score(paired, held)
print(f"{'assume the level holds':<36} {n:>6} {got:>16.1%}")
got, n = score(paired, lambda r: not held(r))
print(f"{'assume it breaks':<36} {n:>6} {got:>16.1%}")

print(f"\n{'|edge| at least':>16} {'n':>6} {'edge sign':>11} {'level holds':>13} {'better by':>11}")
print("-" * 62)
for t in (0.0, 0.08, 0.11, 0.14, 0.20, 0.30):
    kept = [r for r in paired if abs(r["edge"]) >= t]
    if not kept:
        continue
    edge, n = rate(kept)
    trivial, _ = score(kept, held)
    print(f"{t:>16.2f} {n:>6} {edge:>10.1%} {trivial:>12.1%} {100 * (edge - trivial):>+10.1f}pp")

print(f"\n{'how often the edge agrees with the trivial rule':<50}")
for t in (0.0, 0.11, 0.20):
    kept = [r for r in paired if abs(r["edge"]) >= t]
    same = sum(1 for r in kept if (r["edge"] > 0) == held(r))
    print(f"  |edge| >= {t:.2f}: {same / len(kept):.1%} of {len(kept)} calls")
