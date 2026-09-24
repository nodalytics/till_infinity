"""The two new switches, replayed on the live desk's own closed trades.

The spike switch (`scaling.by_spike`, halve when `tr_percentile` >= 0.8) and the release
gate (`risk.Guard`'s `release_in_hold`, refuse when a high-importance print lands inside the
trade's planned hold) were each validated on stand-in positions - always long, momentum. This
asks what they would have done to the trades the desk actually took.

Two stages, because the journal lives on the lab and the calendar does not:

  extract  (lab)   every closed live trade from `journal.db` - feed, interval, strategy, entry
                   time, R, money - joined to its decision's planned hold, and the entry's
                   `tr_percentile` computed from the lab's broker bars exactly as production
                   computes it: EWMA of true range at alpha 1/14, ranked in its own last 1,500
                   bars, causally (bars closed at or before the entry). Writes JSON.
  score    (here)  the release gate through **production's own `Context.ahead`**, fed the
                   calendar the trader consumes, with the production cap; then both switches'
                   effect on money, the tail and drawdown.

The journal copy on the lab is dated 2026-09-10. Bars: the trade's interval where the lab
holds it, else the nearest held below (1m/5m read 3m, 30m reads 15m, 2h and up read 1h).

  ./.secrets/lab.sh run research/harness/livebook.py MODE=extract SEQLAB=$HOME/till_infinity/data/seqlab
  ./.secrets/lab.sh fetch results .secrets/lab-results
  python research/harness/livebook.py   # MODE=score, reads .secrets/lab-results/livebook_trades.json
"""

from __future__ import annotations

import gzip
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

MODE = os.environ.get("MODE", "score")
TRADES = Path(os.environ.get("TRADES", ".secrets/lab-results/livebook_trades.json"))
BARS_FOR = {"1m": "3m", "3m": "3m", "5m": "3m", "15m": "15m", "30m": "15m", "1h": "1h"}


def norm(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())


def extract():
    seqlab = Path(os.environ["SEQLAB"])
    names = {norm(p.name.split(".")[0]): p.name.split(".")[0] for p in seqlab.glob("*.1h.npz")}
    c = sqlite3.connect("file:data/journal.db?mode=ro", uri=True)
    outs = [json.loads(ctx) | {"_time": t} for t, ctx in c.execute(
        "select time, context from entries where actor='trading' and kind='outcome' order by time")]
    decs = [json.loads(ctx) | {"_time": t} for t, ctx in c.execute(
        "select time, context from entries where actor='trading' and kind='decision' order by time")]
    cache = {}

    def percentile_series(sym, interval):
        key = (sym, interval)
        if key not in cache:
            f = seqlab / f"{sym}.{interval}.npz"
            if not f.exists():
                cache[key] = None
            else:
                z = np.load(f)  # plain arrays; never allow_pickle
                df = pd.DataFrame({k: z[k] for k in ("time", "high", "low", "close")}).drop_duplicates("time")
                prev = df.close.shift(1)
                tr = np.maximum(df.high - df.low, np.maximum((df.high - prev).abs(), (df.low - prev).abs()))
                ew = (tr / df.close).ewm(alpha=1 / 14, adjust=False).mean()
                pct = ew.rolling(1500, min_periods=20).rank(pct=True)
                cache[key] = (df.time.to_numpy(), pct.to_numpy())
        return cache[key]

    rows = []
    for o in outs:
        feed, interval = str(o.get("feed") or ""), str(o.get("interval") or "")
        seconds = float(o.get("seconds") or 0)
        entry_t = float(o["_time"]) - seconds
        # the decision that opened it: same feed, entry price, the latest one at or before entry
        best = None
        for d in decs:
            if d.get("feed") == feed and d["_time"] <= entry_t + 120 and \
                    abs(float(d.get("entry") or 0) - float(o.get("entry") or -1)) <= 1e-6 * max(1, abs(float(o.get("entry") or 1))):
                best = d
        hold = float((best or {}).get("hold_seconds") or o.get("expected_hold_s") or 0)
        pct = None
        sym = names.get(norm(feed))
        tf = BARS_FOR.get(interval, "1h")
        if sym:
            got = percentile_series(sym, tf)
            if got is not None:
                times, vals = got
                i = np.searchsorted(times, entry_t, side="right") - 1
                # a bar is known at its close; `time` is the open, so step back one bar
                i -= 1
                if 0 <= i < len(vals) and np.isfinite(vals[i]) and entry_t - times[i] < 86400 * 2:
                    pct = float(vals[i])
        rows.append(dict(feed=feed, interval=interval, strategy=o.get("strategy"), entry_time=entry_t,
                         seconds=seconds, hold=hold, hold_from=("decision" if best else "expected_hold_s"),
                         r=o.get("r_multiple"), profit=o.get("profit"), risk_money=o.get("risk_money"),
                         exit_kind=o.get("exit_kind"), reason=o.get("reason"), side=o.get("side"),
                         tr_percentile=pct, bars=tf if sym else None))
    Path("results").mkdir(exist_ok=True)
    Path("results/livebook_trades.json").write_text(json.dumps(rows))
    print(f"{len(rows)} trades; percentile found for {sum(r['tr_percentile'] is not None for r in rows)}; "
          f"hold from decision for {sum(r['hold_from'] == 'decision' for r in rows)}")


def drawdown(x):
    cum = np.cumsum(x)
    return float(np.max(np.maximum.accumulate(np.concatenate([[0], cum]))[1:] - cum)) if len(x) else 0.0


def score():
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from till_infinity.trading.config import Settings
    from till_infinity.trading.context import Context

    t = pd.DataFrame(json.loads(TRADES.read_text()))
    t = t.sort_values("entry_time").reset_index(drop=True)
    for c in ("r", "profit", "risk_money", "tr_percentile", "hold"):
        t[c] = pd.to_numeric(t[c], errors="coerce")
    with gzip.open(".secrets/journal/events.jsonl.gz", "rt") as fh:
        events = sorted((json.loads(line) for line in fh), key=lambda e: e.get("time") or 0)
    cap = Settings().release_hold_cap_s
    first_event = min(e["time"] for e in events if e.get("time"))
    t["calendar"] = t.entry_time >= first_event

    def coming(feed, hold, entry):
        """Production's gate as the live trader would have run it at `entry`: a fresh
        `Context` fed the calendar around that moment. Fed the whole calendar at once, it
        forgets old releases as newer ones arrive - `observe_event` prunes - and answers
        every August trade from an empty book."""
        if not (np.isfinite(hold) and hold > 0):
            return False
        # Fed newest-first. `observe_event` prunes against the *event's* time rather than the
        # clock, so a calendar fed in date order - which is how both providers publish it -
        # keeps only its last release and the gate is blind (a production defect, found
        # here). Newest-first keeps every release, which is the gate as it was meant to run.
        ctx = Context()
        for e in reversed(events):
            when = e.get("time") or 0
            if entry - 86400 <= when <= entry + cap + 86400:
                ctx.observe_event(e)
        return ctx.ahead(feed, min(hold, cap), entry) is not None

    t["release"] = [coming(f, h, e) for f, h, e in zip(t.feed, t.hold, t.entry_time)]
    t["loud"] = t.tr_percentile >= 0.8
    t["currencies"] = [bool(__import__("till_infinity.trading.exposure", fromlist=["legs"]).legs(f)[0]
                            or __import__("till_infinity.trading.exposure", fromlist=["legs"]).legs(f)[1]) for f in t.feed]

    n = len(t)
    print(f"{n} closed live trades, {pd.to_datetime(t.entry_time.min(), unit='s').date()} to "
          f"{pd.to_datetime(t.entry_time.max(), unit='s').date()}; total {t.profit.sum():+.2f}, "
          f"mean R {t.r.mean():+.3f}")
    print(f"tr_percentile known on {t.tr_percentile.notna().sum()}; hold from the decision on "
          f"{(t.hold_from == 'decision').sum()}; instruments with a currency leg (the gate can apply) "
          f"{t.currencies.sum()}; inside the calendar's span {t.calendar.sum()}")

    # ---- spike switch
    k = t.tr_percentile.notna()
    print("\nSPIKE SWITCH (halve when tr_percentile >= 0.8), on trades with a percentile:")
    for name, m in (("quiet (< 0.8)", k & ~t.loud), ("loud (>= 0.8)", k & t.loud)):
        s = t[m]
        print(f"  {name:<14} n={len(s):>3}  mean R {s.r.mean():+.3f}  profit {s.profit.sum():+9.2f}  "
              f"worst {s.profit.min():+8.2f}  exits " + ", ".join(
                  f"{k} {v:.0%}" for k, v in s.exit_kind.value_counts(normalize=True).items()))
    flat = t.profit[k].to_numpy()
    switched = np.where(t.loud[k], 0.5, 1.0) * flat
    for name, x in (("flat", flat), ("switched", switched)):
        print(f"  {name:<9} total {x.sum():+9.2f}  worst {x.min():+8.2f}  5 worst {np.sort(x)[:5].sum():+9.2f}  "
              f"max drawdown {drawdown(x):8.2f}  sd {x.std():.2f}")

    # ---- release gate
    c = t.calendar & t.currencies
    print(f"\nRELEASE GATE (refuse when a high-importance print lands inside min(hold, {cap / 3600:.0f}h)),"
          f" on {c.sum()} trades it could apply to:")
    for name, m in (("clear", c & ~t.release), ("release in hold", c & t.release)):
        s = t[m]
        if len(s):
            print(f"  {name:<16} n={len(s):>3}  mean R {s.r.mean():+.3f}  profit {s.profit.sum():+9.2f}  "
                  f"worst {s.profit.min():+8.2f}")
    gated = t.profit.where(~(c & t.release), 0.0).to_numpy()
    both = np.where(t.loud.fillna(False), 0.5, 1.0) * gated
    print(f"\nWHOLE BOOK ({n} trades): flat {t.profit.sum():+.2f} (drawdown {drawdown(t.profit.to_numpy()):.2f}); "
          f"gate {gated.sum():+.2f} (drawdown {drawdown(gated):.2f}); gate + switch {both.sum():+.2f} "
          f"(drawdown {drawdown(both):.2f})")
    print("\nby strategy, loud share and R:")
    g = t[k].groupby("strategy").agg(n=("r", "size"), loud=("loud", "mean"), r=("r", "mean"),
                                       r_loud=("r", lambda s: s[t.loud[s.index]].mean()))
    print(g.sort_values("n", ascending=False).to_string(float_format="%.3f"))


if __name__ == "__main__":
    extract() if MODE == "extract" else score()
