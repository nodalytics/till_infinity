"""Digging into the break rate: joint separation, size, and whether it pays.

research/force.md found two features that separate hold from break -
`approach_vol` at AUC 0.560 and `depth_vol` at 0.599 read the right way round -
in a feature set fitted to predict direction instead.

Three questions follow and none of them is "what is the AUC":

1. **Together, how well do they separate?** Two weak separators that disagree
   are worth more than two that agree.
2. **Is a break a bigger move than a hold?** A break rate is not money. What
   makes predicting one worth anything is the size of what follows.
3. **Does it pay the spread**, per instrument, on the same terms
   research/paying.md holds direction to.
"""

from __future__ import annotations

import json
import math
import sqlite3
import statistics as st
from collections import defaultdict

JOURNAL = "file:/app/.data/journal/journal.db?mode=ro"
LOW, HIGH = 300.0, 1800.0
HELD, BROKE = ("reject", "backcheck"), ("break", "trap")
FEATURES = ("approach_vol", "depth_vol")


def rows() -> list[dict]:
    conn = sqlite3.connect(JOURNAL, uri=True)
    out = []
    for (blob,) in conn.execute(
        "SELECT context FROM entries WHERE actor='structures' AND kind='outcome'"
        " ORDER BY time DESC LIMIT 400000"
    ):
        try:
            d = json.loads(blob or "{}")
        except (ValueError, TypeError):
            continue
        outcome, secs = str(d.get("outcome") or ""), d.get("seconds")
        if secs is None or outcome not in HELD + BROKE:
            continue
        try:
            secs, push = float(secs), abs(float(d.get("push_vol") or 0.0))
        except (TypeError, ValueError):
            continue
        if not (LOW <= secs < HIGH):
            continue
        got = {"broke": outcome in BROKE, "push": push, "feed": str(d.get("feed") or "")}
        for name in FEATURES:
            try:
                got[name] = float(d.get(name) or 0.0)
            except (TypeError, ValueError):
                got[name] = 0.0
        out.append(got)
    return out


def auc(scored: list[tuple[float, bool]]) -> float:
    scored = sorted(scored, key=lambda kv: kv[0])
    positives = sum(1 for _s, b in scored if b)
    negatives = len(scored) - positives
    if not positives or not negatives:
        return 0.5
    ranks, i = {}, 0
    while i < len(scored):
        j = i
        while j + 1 < len(scored) and scored[j + 1][0] == scored[i][0]:
            j += 1
        shared = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[k] = shared
        i = j + 1
    got = sum(ranks[k] for k, (_s, b) in enumerate(scored) if b)
    return (got - positives * (positives + 1) / 2.0) / (positives * negatives)


def fit(seen: list[dict], passes: int = 8, rate: float = 0.05):
    """Walk-forward logistic on the two features. Predict, score, then learn."""
    mean = {n: st.fmean(r[n] for r in seen) for n in FEATURES}
    sd = {n: (st.pstdev(r[n] for r in seen) or 1.0) for n in FEATURES}
    w = dict.fromkeys(FEATURES, 0.0)
    bias = 0.0
    scored: list[tuple[float, bool]] = []
    for _ in range(passes):
        for r in seen:
            x = {n: (r[n] - mean[n]) / sd[n] for n in FEATURES}
            z = bias + sum(w[n] * x[n] for n in FEATURES)
            p = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))
            if _ == passes - 1:
                scored.append((p, r["broke"]))
            err = (1.0 if r["broke"] else 0.0) - p
            for n in FEATURES:
                w[n] += rate * err * x[n]
            bias += rate * err
    return w, scored


def main() -> None:
    seen = rows()
    broke = [r for r in seen if r["broke"]]
    held = [r for r in seen if not r["broke"]]
    print(f"{len(seen)} touches in {LOW:.0f}-{HIGH:.0f}s: {len(broke)} broke, {len(held)} held\n")

    print("1. separation, alone and together")
    for n in FEATURES:
        print(f"   {n:14s} {auc([(r[n], r['broke']) for r in seen]):.4f}")
    w, scored = fit(seen)
    print(
        f"   {'both':14s} {auc(scored):.4f}   weights "
        + ", ".join(f"{n} {v:+.3f}" for n, v in w.items())
    )

    print("\n2. is a break a bigger move than a hold?")
    print(
        f"   break  median |push| {st.median(r['push'] for r in broke):.2f}v"
        f"   mean {st.fmean(r['push'] for r in broke):.2f}v"
    )
    print(
        f"   hold   median |push| {st.median(r['push'] for r in held):.2f}v"
        f"   mean {st.fmean(r['push'] for r in held):.2f}v"
    )

    print("\n3. break rate and size per instrument, most-touched first")
    by = defaultdict(list)
    for r in seen:
        by[r["feed"]].append(r)
    print(f"   {'feed':22s} {'n':>5s} {'break%':>7s} {'auc both':>9s} {'E|push| break':>14s}")
    for feed, cut in sorted(by.items(), key=lambda kv: -len(kv[1]))[:14]:
        if len(cut) < 100:
            continue
        rate = sum(1 for r in cut if r["broke"]) / len(cut)
        _w, s = fit(cut, passes=6)
        theirs = [r["push"] for r in cut if r["broke"]]
        print(
            f"   {feed:22s} {len(cut):5d} {rate:7.1%} {auc(s):9.4f}"
            f" {st.median(theirs) if theirs else 0:14.2f}"
        )


if __name__ == "__main__":
    main()
