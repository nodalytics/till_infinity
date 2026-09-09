"""Is the cross-pair level effect just "the dollar is at a level"?

`tallying.md` measured that a EURUSD level holds 5.6 points more often when
GBPUSD is simultaneously at one of its own, within the hour of day, on 21 of 24
hours - and that gold/silver, the pair that would show a *non*-dollar shared
factor, returns a coin flip.

The reading that fits is that the dollar bloc moves together, so "GBPUSD is at
a level" is largely a restatement of "the dollar is at a level". This tests it.

## The test, and why it needs no DXY feed

No dollar index is collected here, and building one would mean detecting levels
on a synthetic series with a detector that has never been calibrated on it -
introducing a new object in order to test a claim about an existing one.

The same question is answerable directly: **count how many dollar pairs are at
a level at once.** If the composite carries the effect then

* the held rate should rise with that count, and
* **conditioned on the count, the identity of the paired instrument should add
  nothing** - GBPUSD specifically tallying should be worth no more than any
  other pair doing so.

The second is the decisive one. A pairwise effect that survives conditioning on
the count is about *that pair*; one that vanishes was the dollar all along.

## The control

The same construction on instruments that share no dollar: for a gold touch,
count how many *metals* are at a level. If the count effect is a general
"markets are at levels together" phenomenon rather than a dollar one, it should
appear there too.
"""

from __future__ import annotations

import bisect
import datetime as dt
import json
import os
import random
import sqlite3
import statistics as st
import time

DB = "/app/.data/journal/journal.db"
DAYS = float(os.environ.get("DAYS", "14"))
WINDOW = float(os.environ.get("WINDOW", "120"))
DOLLAR = ("eurusd", "gbpusd", "usdjpy", "usdcad", "usdchf", "audusd", "nzdusd")
METALS = ("gold", "silver")


def load(conn, since):
    book: dict[str, list] = {}
    for when, ctx in conn.execute(
        "SELECT time, context FROM entries WHERE actor='structures' AND kind='outcome' AND time>=?",
        (since,),
    ):
        try:
            d = json.loads(ctx or "{}")
        except Exception:
            continue
        if not isinstance(d, dict):
            continue
        feed, result = str(d.get("feed") or ""), str(d.get("outcome") or "")
        if not feed or result not in ("reject", "break"):
            continue
        book.setdefault(feed, []).append(
            (
                float(when),
                result == "reject",
                dt.datetime.fromtimestamp(float(when), dt.timezone.utc).hour,
            )
        )
    for feed in book:
        book[feed].sort()
    return book


def near(stamps, when):
    return bisect.bisect_right(stamps, when + WINDOW) > bisect.bisect_left(stamps, when - WINDOW)


def held_of(rows):
    return st.fmean([1 if h else 0 for h in rows]) if rows else float("nan")


def run():
    now = time.time()
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=120.0)
    book = load(conn, now - DAYS * 86400)
    rng = random.Random(23)
    print(f"{DAYS:.0f} days, window +/-{WINDOW / 60:.0f} min\n")

    for family, name in ((DOLLAR, "dollar bloc"), (METALS, "metals")):
        present = [f for f in family if book.get(f)]
        print(f"=== {name}: {', '.join(present)} ===")
        stamps = {f: [w for w, _, _ in book[f]] for f in present}
        for subject in present:
            others = [f for f in present if f != subject]
            rows = []
            for when, held, hour in book[subject]:
                count = sum(1 for f in others if near(stamps[f], when))
                rows.append((count, held, hour, when))
            if len(rows) < 200:
                continue
            buckets: dict[int, list] = {}
            for count, held, _, _ in rows:
                buckets.setdefault(min(count, 4), []).append(held)
            line = "  ".join(
                f"{k}:{held_of(v):.0%}({len(v)})" for k, v in sorted(buckets.items()) if len(v) >= 25
            )
            print(f"  {subject:10s} {len(rows):5d} touches   held by how many others: {line}")
        print()

    # The decisive one: does a named pair add anything once the count is known?
    print("=== does the *identity* of the pair add anything, at a fixed count? ===")
    present = [f for f in DOLLAR if book.get(f)]
    stamps = {f: [w for w, _, _ in book[f]] for f in present}
    for subject, partner in (("eurusd", "gbpusd"), ("eurusd", "usdchf"), ("usdcad", "usdchf")):
        if subject not in stamps or partner not in stamps:
            continue
        others = [f for f in present if f != subject]
        rows = []
        for when, held, _ in book[subject]:
            count = sum(1 for f in others if near(stamps[f], when))
            rows.append((count, near(stamps[partner], when), held))
        print(f"\n  {subject} / {partner}")
        print(f"    {'others at a level':>18s} {'n':>6s} {'held|tallied':>13s} "
              f"{'held|not':>9s} {'gap':>7s} {'p(perm)':>8s}")
        pooled_gap = []
        for count in range(0, 6):
            part = [(t, h) for c, t, h in rows if c == count]
            yes = [h for t, h in part if t]
            no = [h for t, h in part if not t]
            if len(yes) < 25 or len(no) < 25:
                continue
            gap = held_of(yes) - held_of(no)
            pooled_gap.append(gap)
            labels = [True] * len(yes) + [False] * len(no)
            vals = [1 if h else 0 for h in yes + no]
            beaten = 0
            for _ in range(400):
                rng.shuffle(labels)
                fy = [v for lab, v in zip(labels, vals) if lab]
                fn = [v for lab, v in zip(labels, vals) if not lab]
                if fy and fn and (st.fmean(fy) - st.fmean(fn)) >= gap:
                    beaten += 1
            print(f"    {count:18d} {len(part):6d} {held_of(yes):12.1%} {held_of(no):8.1%} "
                  f"{gap:+6.1%} {beaten / 400:8.3f}")
        if pooled_gap:
            print(f"    median gap across counts: {st.median(pooled_gap):+.1%} "
                  f"({sum(1 for g in pooled_gap if g > 0)}/{len(pooled_gap)} positive)")


if __name__ == "__main__":
    run()
