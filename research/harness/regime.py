"""Todo 7i, and the volatility-target number.

**7i.** Volatility clusters and direction does not, so the sharpest statement of
what this system does is: model the predictable part, let structure supply the
sign. That has never been tested.

**Two fields, and they are not the same question.** Both are published on every
call and nothing conditions on either:

* `vol_stretch` is `garch.stretch` - the current scale over its own long-run
  level. **Where we are.** Above one the instrument is livelier than it usually
  is; below one, quieter.
* `forecast_ratio` is `har.ratio` - the next-bar forecast over the last
  realised value. **Where we are going.** Above one the model expects the next
  bar to be livelier than the last, whatever the level.

An instrument can sit at twice its usual volatility (`vol_stretch` 2.0) and be
expected to stay exactly there (`forecast_ratio` 1.0). An earlier version of
this harness read `forecast_ratio` and described it as `vol_stretch`, so the
result was reported as a statement about the regime level when it was a
statement about expected change of scale. Both are measured below.

The touch record carries `regime` directly; both ratios live on the decision,
and every structures outcome has a parent, so they join.

**The sizing number.** `scaling.by_volatility` reduces a position when an
instrument is more volatile than the book is sized for, and it is off:
`TRADING_VOLATILITY_TARGET_BPS` is unset. Choosing it needs the distribution of
`vol_bps` across what is actually traded, which is printed below.
"""

from __future__ import annotations

import json
import os
import sqlite3
import statistics as st
import time

DB = "/app/.data/journal/journal.db"
DAYS = float(os.environ.get("DAYS", "7"))


def bucket(value, edges):
    for i, edge in enumerate(edges):
        if value < edge:
            return i
    return len(edges)


def run():
    now = time.time()
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=180.0)
    since = now - DAYS * 86400

    # Decisions carry forecast_ratio and vol_bps; outcomes carry the result.
    decisions: dict[str, dict] = {}
    for entry_id, ctx in conn.execute(
        "SELECT id, context FROM entries WHERE actor='structures' AND kind='decision' AND time>=?",
        (since,),
    ):
        try:
            d = json.loads(ctx or "{}")
        except Exception:
            continue
        if isinstance(d, dict) and isinstance(d.get("forecast_ratio"), (int, float)):
            decisions[str(entry_id)] = d

    rows = []
    for parent, ctx in conn.execute(
        "SELECT parent, context FROM entries WHERE actor='structures' AND kind='outcome' "
        "AND time>=? AND parent IS NOT NULL",
        (since,),
    ):
        try:
            d = json.loads(ctx or "{}")
        except Exception:
            continue
        if not isinstance(d, dict) or str(d.get("outcome")) not in ("reject", "break"):
            continue
        parent_ctx = decisions.get(str(parent))
        if parent_ctx is None:
            continue
        stretch = parent_ctx.get("vol_stretch")
        rows.append(
            (
                float(parent_ctx["forecast_ratio"]),
                d.get("regime"),
                float(parent_ctx.get("vol_bps") or 0.0),
                str(d.get("outcome")) == "reject",
                str(d.get("feed") or ""),
                float(stretch) if isinstance(stretch, (int, float)) else None,
            )
        )
    print(f"{len(rows)} decisive touches joined to a decision carrying the ratios\n")
    if len(rows) < 200:
        print("not enough to report")
    else:
        def by_ratio(values, label):
            """Held rate in quintiles of one ratio."""
            pairs = [(v, held) for v, held in values if v is not None and v > 0]
            if len(pairs) < 200:
                print(f"\n{label}: only {len(pairs)} touches carry it, not reporting")
                return
            xs = [v for v, _ in pairs]
            edges = [st.quantiles(xs, n=5)[i] for i in range(4)]
            print(f"\nheld rate by {label}:")
            print(f"  edges: {[round(e, 3) for e in edges]}")
            book: dict[int, list] = {}
            for v, held in pairs:
                book.setdefault(bucket(v, edges), []).append(1 if held else 0)
            for k in sorted(book):
                got = book[k]
                lo = "-inf" if k == 0 else f"{edges[k - 1]:.3f}"
                hi = "+inf" if k == len(edges) else f"{edges[k]:.3f}"
                print(f"    {lo:>7s} .. {hi:<7s} {len(got):6d} touches  held {st.fmean(got):6.1%}")

        # Where we are going: the next bar against the last one.
        by_ratio([(r[0], r[3]) for r in rows], "forecast_ratio (next bar vs last)")
        # Where we are: the current scale against its own long-run level.
        by_ratio([(r[5], r[3]) for r in rows], "vol_stretch (scale vs its long-run level)")

        # And whether they are saying the same thing at all. If they were, the
        # correction above would be cosmetic; the point is that they are not.
        both = [(r[0], r[5]) for r in rows if r[5] is not None and r[5] > 0 and r[0] > 0]
        if len(both) > 200:
            import math
            fs = [math.log(a) for a, _ in both]
            ss = [math.log(b) for _, b in both]
            mf, ms = st.fmean(fs), st.fmean(ss)
            cov = st.fmean([(a - mf) * (b - ms) for a, b in zip(fs, ss)])
            sf = st.pstdev(fs) or 1.0
            ss_ = st.pstdev(ss) or 1.0
            print(f"\ncorrelation of log(forecast_ratio) and log(vol_stretch): "
                  f"{cov / (sf * ss_):+.3f} over {len(both)} touches")

        regimes = [r[1] for r in rows if isinstance(r[1], (int, float))]
        if len(regimes) > 200:
            redges = [st.quantiles(regimes, n=5)[i] for i in range(4)]
            print("\nheld rate by `regime` (carried on the touch itself):")
            book = {}
            for _, reg, _, held, _, _ in rows:
                if isinstance(reg, (int, float)):
                    book.setdefault(bucket(float(reg), redges), []).append(1 if held else 0)
            for k in sorted(book):
                v = book[k]
                lo = "-inf" if k == 0 else f"{redges[k - 1]:.3f}"
                hi = "+inf" if k == len(redges) else f"{redges[k]:.3f}"
                print(f"    {lo:>7s} .. {hi:<7s} {len(v):6d} touches  held {st.fmean(v):6.1%}")

    print("\n=== vol_bps across what is published, for the sizing target ===")
    vols: dict[str, list] = {}
    for ctx in (c for (c,) in conn.execute(
        "SELECT context FROM entries WHERE actor='structures' AND kind='decision' AND time>=?",
        (since,))):
        try:
            d = json.loads(ctx or "{}")
        except Exception:
            continue
        if isinstance(d, dict) and isinstance(d.get("vol_bps"), (int, float)) and d["vol_bps"] > 0:
            vols.setdefault(str(d.get("feed") or "?"), []).append(float(d["vol_bps"]))
    every = [v for xs in vols.values() for v in xs]
    if every:
        qs = st.quantiles(every, n=10)
        print(f"  all feeds: n={len(every)}  median {st.median(every):.2f}bps  "
              f"p10 {qs[0]:.2f}  p90 {qs[8]:.2f}")
    TRADED = ("eurusd","gbpusd","usdjpy","gold","silver","btc","us100","spx500",
              "volatility_75_index","boom_500_index")
    print(f"  {'feed':22s} {'n':>6s} {'median':>9s} {'p90':>9s}")
    for feed in TRADED:
        xs = vols.get(feed)
        if not xs or len(xs) < 20:
            continue
        print(f"  {feed:22s} {len(xs):6d} {st.median(xs):8.2f}b {st.quantiles(xs, n=10)[8]:8.2f}b")


if __name__ == "__main__":
    run()
