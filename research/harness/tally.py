"""Does a level hold better when the paired instrument is at one of its own?

`research/tallying.md`. The user's question: an EURUSD level tallying with a
GBPUSD level - is the pair worth more than either alone?

## The operationalisation, chosen to avoid a fitted parameter

"The corresponding price" needs a mapping, and every candidate mapping is a
modelling choice that can manufacture the answer. So the mapping is avoided
entirely: instead of asking whether B has a level at a price corresponding to
A's, this asks whether **B was resolving a touch of its own level at the same
moment**. That is what a desk means by two levels tallying, it needs no beta,
and it is exactly measurable from the touch record.

## The outcome

`reject` is the level holding; `break` is price going through. So the reading
is the **held rate** among decisive touches, and the excursion beside it.

## The three controls, fixed before the run

* **A pair with no shared currency.** EURUSD and GBPUSD are largely one dollar
  trade - one witness seen twice, which is what killed the change-point version
  in `peering.md`. EURUSD against AUDJPY shares nothing, so an effect that is
  really about the dollar should collapse there.
* **The synthetics.** Two Deriv volatility indices share no factor at all. Any
  effect there is the clock, not the market.
* **The hour of day.** Touches cluster in the active session and so does
  everything else, so the paired and unpaired sets are compared **within the
  same hour** as well as pooled. The pooled number is reported first and is the
  one that means least.
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
#: How close in time two touches must be to count as tallying, in seconds.
#: **Tight on purpose.** At 15 minutes 94% of EURUSD touches had a GBPUSD
#: touch nearby, so the variable barely varied and the "no" group was whatever
#: happens in the quiet hours. A tally has to be rare enough to mean something.
WINDOW = float(os.environ.get("WINDOW", "120"))
PAIRS = [
    # The metals, which is the sharpest real case here: gold and silver share a
    # factor that is not the dollar, so an effect on them and not on the dollar
    # pairs would be about the metal rather than the numeraire.
    ("gold", "silver", "metals - shared non-dollar factor"),
    ("silver", "gold", "metals, the other way round"),
    # Gold against a dollar pair: shares only the numeraire.
    ("gold", "eurusd", "dollar only"),
    ("gold", "usdjpy", "dollar only"),
    ("silver", "eurusd", "dollar only"),
    # The dollar bloc.
    ("eurusd", "gbpusd", "both dollar - the question"),
    ("gbpusd", "usdjpy", "both dollar"),
    ("eurusd", "usdchf", "both dollar"),
    ("usdcad", "usdchf", "both dollar, same side"),
    ("audusd", "nzdusd", "both dollar, closest real proxies"),
    ("eurusd", "eurgbp", "shared EUR, no shared dollar exposure"),
    # Controls.
    ("eurusd", "audjpy", "no shared currency - control"),
    ("gold", "audjpy", "no shared currency - control"),
    ("volatility_25_index", "volatility_75_index", "synthetic - control"),
    ("boom_500_index", "crash_500_index", "synthetic - control"),
]


def load(conn, since):
    """Every decisive touch: feed -> [(time, held, excursion, hour)]."""
    book: dict[str, list] = {}
    for when, ctx in conn.execute(
        "SELECT time, context FROM entries WHERE actor='structures' AND kind='outcome' "
        "AND time>=?",
        (since,),
    ):
        try:
            d = json.loads(ctx or "{}")
        except Exception:
            continue
        if not isinstance(d, dict):
            continue
        feed = str(d.get("feed") or "")
        result = str(d.get("outcome") or "")
        # Only the decisive ones. `trap`, `backcheck` and `chop` are their own
        # questions and mixing them in would make "held" mean three things.
        if not feed or result not in ("reject", "break"):
            continue
        excursion = d.get("excursion_vol")
        book.setdefault(feed, []).append(
            (
                float(when),
                result == "reject",
                float(excursion) if isinstance(excursion, (int, float)) else None,
                dt.datetime.fromtimestamp(float(when), dt.timezone.utc).hour,
            )
        )
    for feed in book:
        book[feed].sort()
    return book


def near(stamps: list[float], when: float) -> bool:
    left = bisect.bisect_left(stamps, when - WINDOW)
    right = bisect.bisect_right(stamps, when + WINDOW)
    return right > left


def summarise(rows):
    held = [1 if h else 0 for _, h, _, _ in rows]
    exc = [e for _, _, e, _ in rows if e is not None]
    return (
        len(rows),
        st.fmean(held) if held else float("nan"),
        st.median(exc) if exc else float("nan"),
    )


def run():
    now = time.time()
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=120.0)
    book = load(conn, now - DAYS * 86400)
    rng = random.Random(17)
    print(f"{DAYS:.0f} days, tally window +/-{WINDOW / 60:.0f} min\n")
    print(
        f"{'pair':38s} {'n':>6s} {'tallied':>8s} {'held|yes':>9s} {'held|no':>8s} "
        f"{'gap':>7s} {'p(perm)':>8s}"
    )
    for a, b, note in PAIRS:
        rows_a, rows_b = book.get(a), book.get(b)
        if not rows_a or not rows_b:
            print(f"{a}/{b:22s} - one side has no decisive touches")
            continue
        stamps_b = [w for w, _, _, _ in rows_b]
        yes = [r for r in rows_a if near(stamps_b, r[0])]
        no = [r for r in rows_a if not near(stamps_b, r[0])]
        if len(yes) < 25 or len(no) < 25:
            print(f"{a + '/' + b:38s} {len(rows_a):6d}  too few ({len(yes)} / {len(no)})")
            continue
        ny, hy, _ = summarise(yes)
        nn, hn, _ = summarise(no)
        gap = hy - hn
        # Permutation: the same touches with the tallied label shuffled.
        labels = [True] * ny + [False] * nn
        values = [1 if h else 0 for _, h, _, _ in yes + no]
        beaten = 0
        for _ in range(500):
            rng.shuffle(labels)
            fy = [v for lab, v in zip(labels, values) if lab]
            fn = [v for lab, v in zip(labels, values) if not lab]
            if fy and fn and (st.fmean(fy) - st.fmean(fn)) >= gap:
                beaten += 1
        print(
            f"{a + '/' + b:38s} {len(rows_a):6d} {ny / len(rows_a):7.1%} "
            f"{hy:8.1%} {hn:7.1%} {gap:+6.1%} {beaten / 500:8.3f}   {note}"
        )

    print("\nwithin the same hour of day (the session confound):")
    for a, b, note in PAIRS:
        rows_a, rows_b = book.get(a), book.get(b)
        if not rows_a or not rows_b:
            continue
        stamps_b = [w for w, _, _, _ in rows_b]
        cells: dict[int, list] = {}
        for r in rows_a:
            cells.setdefault(r[3], []).append((r, near(stamps_b, r[0])))
        gaps = []
        total = 0
        for rows in cells.values():
            y = [r for r, flag in rows if flag]
            n = [r for r, flag in rows if not flag]
            if len(y) < 10 or len(n) < 10:
                continue
            gaps.append(summarise(y)[1] - summarise(n)[1])
            total += len(y) + len(n)
        if len(gaps) < 3:
            print(f"  {a + '/' + b:38s} only {len(gaps)} usable hours")
            continue
        print(
            f"  {a + '/' + b:38s} {len(gaps):2d} hours, {total:5d} touches, "
            f"median gap {st.median(gaps):+6.1%}, "
            f"{sum(1 for g in gaps if g > 0)}/{len(gaps)} positive   {note}"
        )


if __name__ == "__main__":
    run()
