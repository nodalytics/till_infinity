"""Are any of the generated series driven by the same process?

The synthetics are sold as independent instruments, so the prior is that every
pair of them is uncorrelated. If that prior is wrong anywhere the consequence is
large - a shared driver between two separately quoted instruments is close to
arbitrage, and a *lead* between them is closer still.

Four hypotheses, in descending order of how much they would matter:

* **Mirrors.** `Boom 500` spikes up and `Crash 500` spikes down. If they are one
  process with the sign flipped, their correlation is near **-1** and the two
  quotes are one instrument sold twice.
* **Twins.** `Volatility 75` and `Volatility 75 (1s)` carry the same parameter
  and differ in tick rate. Shared stream or independent draws?
* **Siblings.** `Boom 500` against `Boom 1000`, `Jump 10` against `Jump 25`,
  `Crash 300/500/1000`. Same mechanism, different frequency.
* **Strangers.** `Volatility 75` against `Boom 500`. These share nothing but the
  generator that produced them, and they are the control everything else is
  read against.

## Why the control decides the test, not the biggest number

Twenty-odd feeds is more than two hundred pairs, and each is measured at seven
lags. That is well over a thousand numbers, and **the largest of a thousand
noise draws is not small.** Reporting the winner would therefore find something
every time it was run, on any data, including data with no structure in it at
all.

So nothing is read on its own. The strangers give the null distribution of
|correlation| under "these really are independent", and every other category is
reported as a distance from it. A twin at 0.04 against strangers averaging 0.04
is not a finding, however much it looks like one in isolation.

This is the same discipline `research/forecasting.md` had to learn twice in one
day: a clean table is not a result, and one cell out of twelve is arithmetic.
"""

from __future__ import annotations

import math
import os
import sqlite3
import statistics as st
import time
from collections import defaultdict
from itertools import combinations

DATA = os.environ.get("DATA", os.path.expanduser("~/till_infinity/data"))
#: Defaults to the research store rather than production's. `research.db` is
#: 60 days deep, carries the 1s series production's collector loses entirely,
#: and is indexed on (feed, interval, ts) - the way this actually queries.
PRICES = os.environ.get("DB", os.path.join(DATA, "research.db"))

INTERVAL = os.environ.get("INTERVAL", "1m")
DAYS = float(os.environ.get("DAYS", "30"))
LAGS = (-3, -2, -1, 0, 1, 2, 3)
MIN_BARS = 300
MIN_OVERLAP = 200

#: Every generated series this book carries, by the slug `prices` stores.
SYNTHETICS = [
    # Plain volatility indices - one tick every two seconds.
    "volatility_10_index", "volatility_25_index", "volatility_50_index",
    "volatility_75_index", "volatility_100_index",
    # The 1s family. Five have plain counterparts and are the twins; 150, 200
    # and 250 exist only here, and are included because a family test wants the
    # whole family - if the 1s series share a driver among *themselves* that is
    # as interesting as sharing one with their twin.
    "volatility_10_1s_index", "volatility_25_1s_index", "volatility_50_1s_index",
    "volatility_75_1s_index", "volatility_100_1s_index",
    "volatility_150_1s_index", "volatility_200_1s_index", "volatility_250_1s_index",
    # Spike families. Boom rises in steps and drops in spikes; Crash the
    # reverse. If a Boom and its matching Crash are one process with the sign
    # flipped, that is the largest finding available here.
    "boom_300_index", "boom_500_index", "boom_1000_index",
    "crash_300_index", "crash_500_index", "crash_1000_index",
    "jump_10_index", "jump_25_index", "jump_50_index",
    "jump_75_index", "jump_100_index",
    "step_index",
    "range_break_100_index", "range_break_200_index",
]


def family(feed: str) -> tuple[str, str, bool]:
    """(family, parameter, is_1s) - what kind of series this is."""
    fast = "_1s_" in feed
    base = feed.replace("_1s_", "_")
    for name in ("volatility", "boom", "crash", "jump", "range_break", "step"):
        if base.startswith(name):
            rest = base[len(name) :].strip("_").replace("_index", "")
            return name, rest, fast
    return "other", "", fast


def kind(a: str, b: str) -> str:
    """How this pair is related, if at all."""
    fa, pa, sa = family(a)
    fb, pb, sb = family(b)
    if fa == fb and pa == pb and sa != sb:
        return "twin"          # V75 vs V75(1s)
    if {fa, fb} == {"boom", "crash"} and pa == pb:
        return "mirror"        # Boom 500 vs Crash 500
    if {fa, fb} == {"boom", "crash"}:
        return "mirror-ish"    # Boom 500 vs Crash 1000
    if fa == fb and sa == sb:
        return "sibling"       # Boom 500 vs Boom 1000
    if fa == fb:
        return "sibling-1s"    # V75 vs V25(1s)
    return "stranger"


def series(conn, feed: str, since: float) -> dict[int, float]:
    out = {}
    for ts, close in conn.execute(
        "SELECT ts, close FROM bars WHERE feed=? AND interval=? AND ts>=? ORDER BY ts ASC",
        (feed, INTERVAL, int(since * 1000)),
    ):
        if isinstance(close, int | float) and close > 0:
            out[int(ts)] = float(close)
    return out


def returns(bars: dict[int, float]) -> dict[int, float]:
    keys = sorted(bars)
    out = {}
    for i in range(1, len(keys)):
        a, b = bars[keys[i - 1]], bars[keys[i]]
        if a > 0 and b > 0:
            out[keys[i]] = math.log(b / a)
    return out


def corr(a: dict[int, float], b: dict[int, float], lag: int, step: int) -> tuple[float, int]:
    xs, ys = [], []
    for t, x in a.items():
        y = b.get(t + lag * step)
        if y is not None:
            xs.append(x)
            ys.append(y)
    if len(xs) < MIN_OVERLAP:
        return float("nan"), len(xs)
    mx, my = st.fmean(xs), st.fmean(ys)
    num = math.fsum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    dx = math.sqrt(math.fsum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(math.fsum((y - my) ** 2 for y in ys))
    return (num / (dx * dy) if dx > 0 and dy > 0 else float("nan")), len(xs)


def run() -> None:
    conn = sqlite3.connect(f"file:{PRICES}?mode=ro", uri=True, timeout=900.0)
    since = time.time() - DAYS * 86400
    step = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600}.get(INTERVAL, 60) * 1000

    loaded, counts = {}, {}
    for feed in SYNTHETICS:
        bars = series(conn, feed, since)
        counts[feed] = len(bars)
        if len(bars) >= MIN_BARS:
            loaded[feed] = returns(bars)
    print(f"=== bars available, {INTERVAL}, {DAYS:g} days ===")
    for feed in SYNTHETICS:
        mark = "ok " if feed in loaded else "SKIP"
        print(f"  {mark} {feed:26s} {counts[feed]:7d}")
    print(f"\n{len(loaded)} series usable, {len(list(combinations(loaded, 2)))} pairs\n")
    if len(loaded) < 3:
        print("not enough series with bars to compare")
        return

    rows = []
    for a, b in combinations(sorted(loaded), 2):
        best, at_lag, n0 = 0.0, 0, 0
        contemporaneous = float("nan")
        for lag in LAGS:
            c, n = corr(loaded[a], loaded[b], lag, step)
            if c != c:
                continue
            if lag == 0:
                contemporaneous, n0 = c, n
            if abs(c) > abs(best):
                best, at_lag = c, lag
        if n0 < MIN_OVERLAP:
            continue
        rows.append((kind(a, b), a, b, contemporaneous, best, at_lag, n0))

    by_kind = defaultdict(list)
    for k, *_rest in rows:
        by_kind[k].append(_rest)

    strangers = [abs(r[3]) for r in rows if r[0] == "stranger"]
    null_mean = st.fmean(strangers) if strangers else float("nan")
    null_sd = st.pstdev(strangers) if len(strangers) > 2 else float("nan")

    print("=== by relationship: |best correlation across lags| ===")
    print(f"  {'kind':>12s} {'pairs':>6s} {'mean':>8s} {'max':>8s}   worst offender")
    for k in ("mirror", "twin", "sibling", "mirror-ish", "sibling-1s", "stranger"):
        got = [r for r in rows if r[0] == k]
        if not got:
            continue
        mags = [abs(r[4]) for r in got]
        worst = max(got, key=lambda r: abs(r[4]))
        print(f"  {k:>12s} {len(got):6d} {st.fmean(mags):8.4f} {max(mags):8.4f}   "
              f"{worst[1]} / {worst[2]} = {worst[4]:+.4f} at lag {worst[5]:+d}")

    print(f"\nnull from strangers: mean |corr| {null_mean:.4f}, sd {null_sd:.4f}")
    if null_sd and null_sd == null_sd and null_sd > 0:
        print("\n=== anything standing clear of the null (>5 sd) ===")
        flagged = [
            r for r in rows
            if r[0] != "stranger" and abs(r[4]) > null_mean + 5 * null_sd
        ]
        if not flagged:
            print("  none - every pair sits inside the range unrelated series occupy,")
            print("  which is the expected answer and says they are independently generated.")
        for k, a, b, c0, best, lag, n in sorted(flagged, key=lambda r: -abs(r[4])):
            print(f"  {k:>11s}  {a} / {b}")
            print(f"              lag0 {c0:+.4f}   best {best:+.4f} at lag {lag:+d}   n={n}")

    print("\nA mirror near -1 would mean two quotes on one process. A twin or")
    print("sibling clear of the null would mean a shared driver. Everything")
    print("sitting on the null is the answer the prior expects.")


if __name__ == "__main__":
    run()
