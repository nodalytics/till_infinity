"""Does `Features.distance` order neighbours better than chance?

The document this reconstructs was cited three times - `research/prior.md` item
4 and two entries in `docs/todo.md` - as the evidence for deleting `Memory`,
`Features.distance` and the kNN. It did not exist in the tree or in git
history, so the figure attributed to it ("no better than random across 13.5M
pairs") had never been checkable. This is the measurement it should have been.

## The question, stated so it can fail

The kNN's premise is that a *near* touch is better evidence about this one than
a *far* touch. That is a claim about ordering, and it is testable without
reference to any model: take pairs of resolved touches on the same side, and
ask whether the pairs the metric calls close agree about direction more often
than the pairs it calls distant.

Scored as AUC of `-distance` predicting agreement. **0.5 is the null** - the
metric orders no better than shuffling it. Reported beside a control that
shuffles the distances, because an AUC routine that cannot return 0.5 for
random input is not measuring anything.

## Per horizon, not pooled

research/horizon.md found the level model's edge is +45% on touches resolving
inside five minutes and +0.00% beyond thirty, so a pooled number here would be
dominated by the population the desk does not trade. Every result below is cut
by how long the touch took to resolve.
"""

from __future__ import annotations

import json
import math
import random
import sqlite3
from collections import defaultdict

JOURNAL = "file:/app/.data/journal/journal.db?mode=ro"
LIMIT = 300_000
PAIRS = 400_000

#: The nine, in the order `Features.distance` compares them.
NAMES = (
    "approach_vol",
    "depth_vol",
    "strength",
    "run_vol",
    "experience",
    "pivot",
    "backcheck",
    "regime",
    "up_rate",
)

BUCKETS = (
    ("0-60s", 0.0, 60.0),
    ("60-300s", 60.0, 300.0),
    ("300-1800s", 300.0, 1800.0),
    ("beyond 1800s", 1800.0, float("inf")),
)


def load() -> list[dict]:
    conn = sqlite3.connect(JOURNAL, uri=True)
    out = []
    for (blob,) in conn.execute(
        "SELECT context FROM entries WHERE actor='structures' AND kind='outcome'"
        " ORDER BY time DESC LIMIT ?",
        (LIMIT,),
    ):
        try:
            d = json.loads(blob or "{}")
        except (ValueError, TypeError):
            continue
        push, side, secs = d.get("push_vol"), d.get("side"), d.get("seconds")
        if push is None or side is None or secs is None:
            continue
        try:
            # Negative durations were a mixed-clock defect, fixed 2026-08-31.
            # Excluded rather than clamped: they are the rows whose length is
            # not known, and this document is cut by length.
            secs = float(secs)
            if secs < 0:
                continue
            row = {n: float(d.get(n) or 0.0) for n in NAMES}
        except (TypeError, ValueError):
            continue
        row["side"] = str(side)
        row["up"] = float(push) > 0
        row["seconds"] = secs
        out.append(row)
    return out


def distance(a: dict, b: dict) -> float:
    """`Features.distance`, reproduced. Side is a hard constraint there too."""
    if a["side"] != b["side"]:
        return math.inf
    return math.sqrt(sum((a[n] - b[n]) ** 2 for n in NAMES))


def auc(scored: list[tuple[float, bool]]) -> float:
    """Rank AUC of `score` predicting the label, with ties handled."""
    if not scored:
        return 0.5
    scored.sort(key=lambda kv: kv[0])
    ranks: list[float] = [0.0] * len(scored)
    i = 0
    while i < len(scored):
        j = i
        while j + 1 < len(scored) and scored[j + 1][0] == scored[i][0]:
            j += 1
        shared = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[k] = shared
        i = j + 1
    positives = sum(1 for _s, label in scored if label)
    negatives = len(scored) - positives
    if not positives or not negatives:
        return 0.5
    got = sum(r for r, (_s, label) in zip(ranks, scored, strict=True) if label)
    return (got - positives * (positives + 1) / 2.0) / (positives * negatives)


def sample(rows: list[dict], pairs: int, seed: int = 7) -> list[tuple[float, bool]]:
    """Random same-side pairs, as `(-distance, they agreed)`."""
    rng = random.Random(seed)
    by_side: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_side[row["side"]].append(row)
    out: list[tuple[float, bool]] = []
    sides = [s for s, members in by_side.items() if len(members) > 1]
    if not sides:
        return out
    for _ in range(pairs):
        members = by_side[rng.choice(sides)]
        a, b = rng.sample(members, 2)
        out.append((-distance(a, b), a["up"] == b["up"]))
    return out


def report(name: str, rows: list[dict], pairs: int) -> None:
    scored = sample(rows, pairs)
    if len(scored) < 1_000:
        print(f"   {name:16s} {len(rows):7d} touches - too few to pair")
        return
    shuffled = [s for s, _ in scored]
    random.Random(11).shuffle(shuffled)
    control = list(zip(shuffled, [lab for _s, lab in scored], strict=True))
    agreed = sum(1 for _s, lab in scored if lab) / len(scored)

    # Agreement by distance decile, which is what AUC compresses.
    scored.sort(key=lambda kv: -kv[0])  # nearest first
    tenth = len(scored) // 10
    near = sum(1 for _s, lab in scored[:tenth] if lab) / max(tenth, 1)
    far = sum(1 for _s, lab in scored[-tenth:] if lab) / max(tenth, 1)

    print(
        f"   {name:16s} {len(rows):7d} touches  auc {auc(scored):.4f}"
        f"  (shuffled {auc(control):.4f})  agree {agreed:.1%}"
        f"  nearest-tenth {near:.1%}  farthest-tenth {far:.1%}"
    )


def main() -> None:
    rows = load()
    print(f"{len(rows)} resolved touches with a usable duration\n")
    print("does a smaller distance mean the two touches agreed about direction?")
    print("auc 0.5 is the null - the metric orders no better than shuffling it\n")
    report("pooled", rows, PAIRS)
    print()
    for name, low, high in BUCKETS:
        cut = [r for r in rows if low <= r["seconds"] < high]
        report(name, cut, PAIRS)


if __name__ == "__main__":
    main()
