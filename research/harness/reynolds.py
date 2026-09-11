"""A Reynolds number for a market, and whether it beats the incumbent.

`research/cascading.md` §4, and the one the document itself expects to fail:
"the honest prior is that it will not, because the first three tests are
borrowed from a literature with thirty years of results behind them and this
one is an analogy I constructed."

Turbulence begins when inertial forces overwhelm viscous ones, and the
threshold is a dimensionless ratio rather than a speed. The market analogue
proposed is **order flow over the liquidity absorbing it**: quote intensity
over spread, as a first guess.

    Re = (quotes per minute) / (relative spread in bps)

## What it is measured against, and what beats what

The incumbent is `forecast_ratio` - `har.ratio`, the next-bar forecast over the
last realised value - which `research/clustering.md` measured at **5.1 points**
of held-rate separation across its quintiles where the regime *level* separates
by 1.2. Anything proposed here has to beat 5.1 points to matter.

Two targets are run, because the one the proposition names cannot carry the
comparison on its own:

**A - the level-holding target, as specified.** Journal outcomes joined to the
decision that carried `forecast_ratio`, restricted to feeds with stored quotes.
This is the exact comparison `clustering.md` made. **It is underpowered and the
power is stated before the numbers**: `research.db` holds ticks for a single
24-hour window, which leaves a few hundred decisive touches rather than 32,362.
At ~150 touches a quintile the standard error on a held rate near 84% is about
3 points, so the standard error on a peak-minus-tail difference is about 4.5.
**A 5.1-point separation is at the edge of what this sample can see at all**,
and a null here is a statement about the sample, not about the ratio. Declared
in this docstring rather than after the fact.

**B - a volatility-regime target, which has the power A lacks.** For every feed
and every minute of the quote window, the volatility scale over the next 30
minutes against the last 30. Computable from stored bars for all 53 feeds, so
it gives tens of thousands of observations instead of hundreds. Both `Re` and
the real `forecast_ratio` - taken from `Book`, the live estimator, warmed on the
bars preceding the window - are scored on it by AUC.

It is asked **twice**, and the second is the one that carries the comparison:

* `change` - does the scale move by more than this instrument's usual amount,
  in either direction. This is "a transition" in the sense `clustering.md`
  meant, and it is a magnitude question.
* `rise` - is the next half-hour livelier than the last. This is the question a
  volatility forecaster is *for*, and `forecast_ratio` is the incumbent
  precisely because it answers it. A challenger that cannot be read against an
  incumbent scoring above chance has not been tested against anything, so if
  the first target leaves every predictor at 0.500 the comparison is void and
  the second target is where it is settled.

## What kills it

Not beating `forecast_ratio` on B. On A, nothing is killed either way, because
A cannot resolve the difference that matters.

## Controls

* **The generated book is its own control, and this is the sharpest thing here.**
  Deriv's synthetics emit quotes on a **fixed schedule** - the Range Break
  indices land on exactly 86,400 ticks in 24 hours, one a second. On those
  feeds the numerator of `Re` is a constant by construction, so `Re` is `1 /
  spread` wearing a different name. Any result pooled over the book is 72%
  composed of instruments where half the proposed quantity does not vary.
  Everything is therefore cut by class before it is read.
* **A shuffled `Re`** - the same values reassigned across minutes within a feed
  - gives the AUC floor for a predictor with the right marginal and no timing.
* **Split-sample** on the 24 hours, first half proposing and second disposing.
  The confound is stated rather than solved: half a day is half a session, so
  the two halves differ by time of day as well as by sample. The synthetics,
  which have no session, are the part of the book where that confound is absent.
* **`shared.strata.compare`** on held rate by `Re` bucket, within class.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import statistics as st
import sys
import time
from collections import defaultdict

import numpy as np

sys.path.insert(0, os.path.expanduser("~/till_infinity/repo"))

from till_infinity.shared.strata import compare  # noqa: E402
from till_infinity.structures.vol.volatility import Book  # noqa: E402

DATA = os.environ.get("DATA", os.path.expanduser("~/till_infinity/data"))
DB = os.environ.get("DB", os.path.join(DATA, "research.db"))
JOURNAL = os.environ.get("JOURNAL", os.path.join(DATA, "journal.db"))
SEED = int(os.environ.get("SEED", "23"))
#: Minutes either side of the split for target B.
WINDOW = int(os.environ.get("WINDOW", "30"))
#: Bars of 1m history used to warm `Book` before the quote window opens.
WARMUP = int(os.environ.get("WARMUP", "20000"))
HELD = ("reject", "backcheck", "trap")
BROKE = ("break",)
MINUTE = 60_000

SYNTH = ("boom_", "crash_", "jump_", "volatility_", "step_", "range_break_")
FX = (
    "audjpy", "audusd", "cadjpy", "chfjpy", "euraud", "eurchf", "eurgbp",
    "eurjpy", "eurusd", "gbpjpy", "gbpusd", "nzdusd", "usdcad", "usdchf", "usdjpy",
)
INDEX = ("aus200", "fra40", "ger40", "hk50", "jp225", "uk100", "us100", "us30")


def klass(feed: str) -> str:
    if feed.startswith(SYNTH):
        return "synthetic"
    if feed in FX:
        return "fx"
    if feed in INDEX:
        return "index"
    if feed in ("gold", "silver"):
        return "metal"
    if feed in ("btc", "eth"):
        return "crypto"
    return "other"


def auc(scores: list[float], labels: list[int]) -> float:
    """Rank AUC. 0.5 is chance; below it the predictor is inverted, not useless."""
    pairs = [(s, y) for s, y in zip(scores, labels) if math.isfinite(s)]
    pos = sum(y for _, y in pairs)
    neg = len(pairs) - pos
    if pos == 0 or neg == 0:
        return float("nan")
    order = sorted(range(len(pairs)), key=lambda i: pairs[i][0])
    ranks = [0.0] * len(pairs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and pairs[order[j + 1]][0] == pairs[order[i]][0]:
            j += 1
        mid = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = mid
        i = j + 1
    got = sum(r for r, (_, y) in zip(ranks, pairs) if y == 1)
    return (got - pos * (pos + 1) / 2.0) / (pos * neg)


def quintiles(values: list[float]) -> list[float]:
    xs = sorted(v for v in values if math.isfinite(v))
    if len(xs) < 25:
        return []
    return [xs[int(len(xs) * q)] for q in (0.2, 0.4, 0.6, 0.8)]


def bucket_of(value: float, edges: list[float]) -> int:
    for i, edge in enumerate(edges):
        if value < edge:
            return i
    return len(edges)


def quote_minutes(conn, feed: str) -> dict[int, tuple[float, float, float]]:
    """Per minute: quote count, mean relative spread in bps, and their ratio."""
    rows = conn.execute(
        "SELECT ts, bid, ask FROM ticks WHERE feed=? ORDER BY ts", (feed,)
    ).fetchall()
    if len(rows) < 500:
        return {}
    ts = np.array([r[0] for r in rows], dtype=np.int64)
    bid = np.array([float(r[1] or 0.0) for r in rows])
    ask = np.array([float(r[2] or 0.0) for r in rows])
    ok = (bid > 0) & (ask > 0) & (ask >= bid)
    ts, bid, ask = ts[ok], bid[ok], ask[ok]
    if ts.size < 500:
        return {}
    mid = 0.5 * (bid + ask)
    spread = (ask - bid) / mid * 1e4
    key = ts // MINUTE
    uniq, first, counts = np.unique(key, return_index=True, return_counts=True)
    sums = np.add.reduceat(spread, first)
    out: dict[int, tuple[float, float, float]] = {}
    for u, n, s in zip(uniq, counts, sums):
        mean_spread = float(s) / int(n)
        if mean_spread <= 0:
            continue
        out[int(u)] = (float(n), mean_spread, float(n) / mean_spread)
    return out


def target_b(conn, feed: str, lo: int, hi: int, quotes: dict) -> list[dict]:
    """Per minute in the quote window: is the volatility scale about to change?

    The scale is the mean absolute 1m return over `WINDOW` minutes. The target
    is `|log(next / last)|`, labelled against that feed's own median - so the
    question is "is this instrument about to move to a different regime than the
    one it is in", asked of every instrument on its own terms rather than
    pooled. Pooling it would make the label mostly a statement about which
    instrument the row came from.
    """
    raw = conn.execute(
        "SELECT ts, open, high, low, close FROM bars WHERE feed=? AND interval='1m' "
        "AND ts<=? ORDER BY ts DESC LIMIT ?",
        (feed, hi, WARMUP),
    ).fetchall()
    raw.reverse()
    if len(raw) < WARMUP // 4:
        return []
    ts = np.array([r[0] for r in raw], dtype=np.int64)
    close = np.array([float(r[4]) for r in raw])
    if not (close > 0).all():
        return []
    vol = Book().of(feed, "1m")
    ratio: dict[int, tuple[float, float, float]] = {}
    for i, row in enumerate(raw):
        _, o, h, low, c = row
        if not all(isinstance(v, int | float) and v > 0 for v in (o, h, low, c)):
            continue
        vol.update(float(c))
        vol.observe_bar(float(o), float(h), float(low), float(c))
        when = int(ts[i]) // MINUTE
        if ts[i] >= lo:
            ratio[when] = (vol.forecast_ratio, vol.bps, vol.stretch)
    step = np.diff(ts) == MINUTE
    r = np.abs(np.log(close[1:] / close[:-1]))
    r = np.where(step, r, np.nan)
    rts = ts[1:] // MINUTE
    pos = {int(t): i for i, t in enumerate(rts)}
    out = []
    for minute, (count, spread, re) in quotes.items():
        i = pos.get(minute)
        if i is None or i < WINDOW or i + WINDOW >= r.size:
            continue
        back = r[i - WINDOW:i]
        fore = r[i:i + WINDOW]
        if np.isnan(back).any() or np.isnan(fore).any():
            continue
        a, b = float(np.mean(back)), float(np.mean(fore))
        if a <= 0 or b <= 0:
            continue
        fr = ratio.get(minute)
        out.append({
            "feed": feed, "klass": klass(feed), "minute": minute,
            "re": re, "intensity": count, "inv_spread": 1.0 / spread,
            "change": abs(math.log(b / a)),
            "direction": math.log(b / a),
            "forecast_ratio": fr[0] if fr else float("nan"),
            "vol_bps": fr[1] if fr else float("nan"),
            "stretch": fr[2] if fr else float("nan"),
        })
    return out


def score(rows: list[dict], label: str, names: tuple[str, ...]) -> dict[str, float]:
    got = {}
    ys = [r[label] for r in rows]
    for name in names:
        got[name] = auc([r.get(name, float("nan")) for r in rows], ys)
    return got


def run() -> None:
    started = time.time()
    rng = np.random.default_rng(SEED)
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=600.0)
    lo, hi = conn.execute("SELECT MIN(ts), MAX(ts) FROM ticks").fetchone()
    feeds = [f for (f,) in conn.execute("SELECT DISTINCT feed FROM ticks ORDER BY feed")]
    mid = (lo + hi) // 2
    print(f"quote window {lo} .. {hi}  ({(hi - lo) / 3_600_000:.1f} hours), {len(feeds)} feeds")
    print(f"split at {mid}\n")

    print("=" * 100)
    print("The numerator, before anything is predicted with it. A generated feed that emits one")
    print("quote a second has no flow to measure: on those, Re is 1/spread under another name.")
    print("=" * 100)
    print(f"  {'feed':>24s} {'class':>10s} {'quotes':>9s} {'per min':>8s} {'cv':>7s} "
          f"{'spread bps':>11s} {'spread cv':>10s}")
    quotes: dict[str, dict] = {}
    flat: list[str] = []
    for feed in feeds:
        q = quote_minutes(conn, feed)
        if len(q) < 600:
            continue
        quotes[feed] = q
        counts = [v[0] for v in q.values()]
        spreads = [v[1] for v in q.values()]
        cv = st.stdev(counts) / st.fmean(counts) if len(counts) > 1 and st.fmean(counts) else 0.0
        scv = st.stdev(spreads) / st.fmean(spreads) if len(spreads) > 1 and st.fmean(spreads) else 0.0
        if cv < 0.05:
            flat.append(feed)
        print(f"  {feed:>24s} {klass(feed):>10s} {int(sum(counts)):9,d} {st.fmean(counts):8.1f} "
              f"{cv:7.3f} {st.fmean(spreads):11.3f} {scv:10.3f}")
    print(f"\n  {len(flat)} of {len(quotes)} feeds have a quote rate that barely varies "
          f"(coefficient of variation below 0.05):")
    print("   " + ", ".join(flat) if flat else "   none")

    # ---------------------------------------------------------------- target B
    rows: list[dict] = []
    for feed in quotes:
        rows.extend(target_b(conn, feed, lo, hi, quotes[feed]))
        if len(rows) and len(rows) % 20000 < 1500:
            print(f"  ... {len(rows):,} minutes  {time.time() - started:.0f}s")
    print(f"\n{len(rows):,} feed-minutes for target B across {len({r['feed'] for r in rows})} feeds")

    # Label per feed, against that feed's own median change.
    by_feed: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_feed[r["feed"]].append(r)
    for feed, part in by_feed.items():
        cutoff = st.median(r["change"] for r in part)
        for r in part:
            r["_y"] = 1 if r["change"] > cutoff else 0
            r["_rise"] = 1 if r["direction"] > 0 else 0
        shuffled = rng.permutation([r["re"] for r in part])
        for r, v in zip(part, shuffled):
            r["re_shuffled"] = float(v)

    names = ("re", "intensity", "inv_spread", "forecast_ratio", "vol_bps", "stretch", "re_shuffled")
    print("\n" + "=" * 100)
    print("B: AUC for 'the volatility scale over the next 30 minutes differs from the last 30")
    print("   by more than this instrument's own median'. 0.500 is chance.")
    print("=" * 100)

    def table(label: str, title: str, part: list[dict]) -> None:
        if len(part) < 500:
            print(f"\n  {title}: {len(part)} rows, not reported")
            return
        got = score(part, label, names)
        print(f"\n  {title}  n={len(part):,}")
        print("   " + "".join(f"{n:>16s}" for n in names))
        print("   " + "".join(f"{got[n]:16.4f}" for n in names))

    varying = [r for r in rows if r["feed"] not in flat]
    for label, what in (("_y", "CHANGE - the scale moves by more than usual, either way"),
                        ("_rise", "RISE - the next half hour is livelier than the last")):
        print("\n" + "-" * 100)
        print(f"  target: {what}")
        print("-" * 100)
        table(label, "pooled, all feeds", rows)
        for name in sorted({r["klass"] for r in rows}):
            table(label, f"class {name}", [r for r in rows if r["klass"] == name])
        table(label, "first half of the window", [r for r in rows if r["minute"] * MINUTE < mid])
        table(label, "second half of the window", [r for r in rows if r["minute"] * MINUTE >= mid])
        table(label, "feeds whose quote rate actually varies", varying)

    for label, what in (("_y", "change"), ("_rise", "rise")):
        print(f"\nper feed on '{what}', Re against forecast_ratio (AUC), quote rate varying:")
        print(f"  {'feed':>24s} {'class':>10s} {'n':>7s} {'Re':>8s} {'forecast':>9s} "
              f"{'1/spread':>9s} {'vol_bps':>8s}")
        wins = 0
        seen = 0
        for feed in sorted(by_feed):
            if feed in flat:
                continue
            part = by_feed[feed]
            if len(part) < 300:
                continue
            got = score(part, label, ("re", "forecast_ratio", "inv_spread", "vol_bps"))
            seen += 1
            if abs(got["re"] - 0.5) > abs(got["forecast_ratio"] - 0.5):
                wins += 1
            print(f"  {feed:>24s} {klass(feed):>10s} {len(part):7d} {got['re']:8.4f} "
                  f"{got['forecast_ratio']:9.4f} {got['inv_spread']:9.4f} {got['vol_bps']:8.4f}")
        print(f"  Re separates further from chance than forecast_ratio on {wins}/{seen} feeds")

        # And the question that decides whether any of that is Re: busy markets are
        # volatile markets, so `re` and `vol_bps` order the same rows. Scoring `re`
        # inside quintiles of `vol_bps`, per feed, asks whether it knows anything the
        # volatility level does not - which is the whole claim. Pooled it would be
        # Simpson's paradox for the fifth time on this project.
        conditioned: dict[str, list[float]] = defaultdict(list)
        cells_seen = 0
        for feed, part in by_feed.items():
            edges = quintiles([r["vol_bps"] for r in part])
            if not edges:
                continue
            cells: dict[int, list[dict]] = defaultdict(list)
            for r in part:
                if math.isfinite(r["vol_bps"]):
                    cells[bucket_of(r["vol_bps"], edges)].append(r)
            for cell in cells.values():
                if len(cell) < 80:
                    continue
                cells_seen += 1
                for name in names:
                    got = auc([r.get(name, float("nan")) for r in cell],
                              [r[label] for r in cell])
                    if math.isfinite(got):
                        conditioned[name].append(got)
        if cells_seen:
            print(f"\n  every predictor inside quintiles of vol_bps, per feed, "
                  f"{cells_seen} cells. A challenger")
            print("  conditioned against an unconditioned incumbent is not a comparison, so all of")
            print("  them are conditioned. re_shuffled is the floor and must sit at 0.500.")
            print("   " + "".join(f"{n:>16s}" for n in names))
            print("   " + "".join(
                f"{(st.fmean(conditioned[n]) if conditioned[n] else float('nan')):16.4f}"
                for n in names))

    # ---------------------------------------------------------------- target A
    print("\n" + "=" * 100)
    print("A: the level-holding target the proposition names. Underpowered by design - see the")
    print("   docstring - and reported so the size of the gap between what is wanted and what")
    print("   exists is on the page rather than in a footnote.")
    print("=" * 100)
    jour = sqlite3.connect(f"file:{JOURNAL}?mode=ro", uri=True, timeout=600.0)
    decisions: dict[str, dict] = {}
    for entry, ctx in jour.execute(
        "SELECT id, context FROM entries WHERE actor='structures' AND kind='decision' "
        "AND time BETWEEN ? AND ?", (lo / 1000.0 - 3600, hi / 1000.0)
    ):
        try:
            d = json.loads(ctx or "{}")
        except Exception:
            continue
        if isinstance(d, dict) and isinstance(d.get("forecast_ratio"), int | float):
            decisions[str(entry)] = d

    touches: list[dict] = []
    for when, parent, ctx in jour.execute(
        "SELECT time, parent, context FROM entries WHERE actor='structures' AND kind='outcome' "
        "AND time BETWEEN ? AND ?", (lo / 1000.0, hi / 1000.0)
    ):
        try:
            d = json.loads(ctx or "{}")
        except Exception:
            continue
        if not isinstance(d, dict):
            continue
        result = str(d.get("outcome") or "")
        if result not in HELD + BROKE:
            continue
        feed = str(d.get("feed") or "")
        got = quotes.get(feed)
        parent_ctx = decisions.get(str(parent))
        if got is None or parent_ctx is None:
            continue
        minute = int(float(when) * 1000.0) // MINUTE
        near = [got[m] for m in range(minute - 5, minute) if m in got]
        if len(near) < 3:
            continue
        touches.append({
            "feed": feed, "klass": klass(feed), "time": float(when),
            "held": result in HELD,
            "re": st.fmean(v[2] for v in near),
            "intensity": st.fmean(v[0] for v in near),
            "inv_spread": st.fmean(1.0 / v[1] for v in near),
            "forecast_ratio": float(parent_ctx["forecast_ratio"]),
            "interval": str(d.get("interval") or ""),
        })
    print(f"\n  {len(touches)} decisive touches inside the quote window, on "
          f"{len({t['feed'] for t in touches})} feeds carrying quotes")
    base = st.fmean(1.0 if t["held"] else 0.0 for t in touches) if touches else float("nan")
    print(f"  base held rate {base:.1%}")
    if len(touches) >= 25:
        cell = len(touches) / 5.0
        se = math.sqrt(base * (1 - base) / cell) if cell > 0 else float("nan")
        print(f"  ~{cell:.0f} touches a quintile, standard error on a cell {se * 100:.1f} points,")
        print(f"  so about {se * math.sqrt(2) * 100 * 1.96:.1f} points is the smallest peak-minus-tail")
        print(f"  difference this sample could call real. The incumbent's separation is 5.1.")

    for field in ("re", "forecast_ratio", "intensity", "inv_spread"):
        vals = [t[field] for t in touches]
        edges = quintiles(vals)
        if not edges:
            print(f"\n  {field}: too few to bucket")
            continue
        book: dict[int, list[int]] = defaultdict(list)
        for t in touches:
            book[bucket_of(t[field], edges)].append(1 if t["held"] else 0)
        print(f"\n  held rate by {field} quintile:")
        rates = []
        for k in sorted(book):
            got = book[k]
            rate = st.fmean(got)
            rates.append(rate)
            print(f"    q{k + 1}  n={len(got):4d}  held {rate:6.1%}")
        if rates:
            print(f"    peak - tail: {(max(rates) - min(rates)) * 100:.1f} points")

    if len(touches) >= 100:
        print("\n" + "=" * 100)
        print("Conditioned: held rate by Re bucket, within class and interval")
        print("=" * 100)
        edges = quintiles([t["re"] for t in touches])
        cut = [
            {"held": 1.0 if t["held"] else 0.0, "re_bucket": f"q{bucket_of(t['re'], edges) + 1}",
             "klass": t["klass"], "interval": t["interval"], "feed": t["feed"]}
            for t in touches
        ]
        print(compare(cut, value="held", bucket="re_bucket",
                      within=("klass", "interval"), min_n=40).render())

    print(f"\n{time.time() - started:.0f}s")


if __name__ == "__main__":
    run()
