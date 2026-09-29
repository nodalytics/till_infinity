"""The winner's curse on limit fills: are the better prices the desk waits for the ones it should
not have got?

`research/docs/game-theory.md` ranks this fourth. A resting order at a better price is filled only
when price trades to it, and trades to it more often on the way *through*. So the fills a limit
gets are conditioned on the move against it, and the ones it misses are the ones that went its way
at once. That is adverse selection, and it is what a better price has to pay for.

How production waits for a better price (`trading/service.py`):

  park        `_park` holds a signal as a `Waiting`: a trigger price at the level's wick depth,
              `wick + pullback_sigmas x wick sd` (capped at `pullback_max_vol`), or a strategy's
              own resting price (`_rest_at_named_price`), or `entry_edge_vol` better than the quote
              (`_edge_entry`, off by default). The signal wakes when the quote crosses the trigger
              and is then sent **at market**, so it pays the spread like any other entry. It
              expires after `pullback_bars` (10) bars of its interval. The journal records it as a
              declined signal with reason `waiting` ("holding out for <price>"), and a woken one as
              a trade with `after_pullback = 1`.

Part 1, the journal (PART=journal):

  outcomes    the desk's closed trades, entered after a pullback against at market: R, adverse and
              best excursion in R, hit rate, day-bootstrap intervals, overall and within the one
              strategy large enough to split (thesis-only). Observational: the two groups differ
              in more than the entry.
  parks       every `waiting` signal replayed on 1m bars (`research.db`), deduplicated by feed and
              trigger. Market: entered at the signal's own price when it was parked. Park: filled
              when the low (buy) or high (sell) reaches the trigger within 10 bars of the interval
              (**touch**), or goes a spread beyond it (**through**). Both trades use the record's
              stop and target and the same clock, 10 bars of the interval after entry. R is in each
              entry's own risk (production sizes by risk), less one spread (the feed's median, from
              the journal) per round trip. Unfilled parks earn 0.

Part 2, simulated on production's zone touches (PART=run, UNIVERSE=real|deriv|walks), reusing
`stophunt.py`'s cached touches from the production `Engine`:

  market      enter at the touch bar's close, fading the arrival, stop 2 bar-vols past the level
              (anchored to the level, as a structure stop is)
  limit       rest at level - side x k x vol, k = 0.25, 0.5, 1.0, for a life of 1, 3 or 10 bars.
              Filled on the first bar whose low (buy) reaches it (**touch**) or goes 0.02 vol past
              it (**through**), at the limit or at a better open. The fill bar's own range can stop
              it (counted as stopped: the order of prices inside a bar is unknown, and conservative)

Each is scored three ways:
  own R       targets 1R and 2R from its own entry, R in its own risk: constant money risk, as
              production sizes. Costs are `COST_V` x sqrt(5 / minutes) of vol per round trip.
  unit P&L    the market trade's stop and 2R target prices, at unit size, in vol: the curse alone,
              without the leverage a closer stop brings
  the curse   two measures, in vol. **thru**: where the fill bar closed against the fill price
              (negative: it closed through the order's price, filled on the way through).
              **after**: the fills' own drift over the 10 bars after the fill bar; zero on a
              martingale, negative if fills keep running against the order. Printed beside it, the
              market entry's 10-bar drift on the same touches - negative by selection, since those
              are the touches that fell back to the limit

Controls: walks we generate. On a martingale a limit fill is conditioned on the path reaching it,
so fills show "adverse" drift by construction; the walks give that mechanical baseline. Deriv is a
market (reported, never a control). Standard errors are clustered by series-day; both halves.

Pre-registered: a limit variant is better only if its **total** net R per signal (fills, plus 0 for
misses) at the 2R target beats market entry on the same touches by at least 0.03R with t >= 3, in
both halves, and by more than the same difference on the walks.

Run on the lab (one process per universe), then PART=report and PART=journal:
  UNIVERSE=real OUT=$HOME/till_infinity/data/limitfills TOUCHES=$HOME/till_infinity/data/stophunt \\
    SEQLAB=$HOME/till_infinity/data/seqlab python research/harness/limitfills.py
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import indicators as ind

UNIVERSE = os.environ.get("UNIVERSE", "real")
PART = os.environ.get("PART", "run")
OUT = Path(os.environ.get("OUT", ".data/limitfills"))
TOUCHES = Path(os.environ.get("TOUCHES", ".data/stophunt"))
JOURNAL = os.path.expanduser(os.environ.get("JOURNAL", "~/till_infinity/data/journal.db"))
BARS = os.path.expanduser(os.environ.get("BARS", "~/till_infinity/data/research.db"))

BUFFER = 2.0  # the structure stop, in bar vols past the level
KS = (0.25, 0.5, 1.0)
LIVES = (1, 3, 10)
TICK = 0.02  # "through", in bar vols
TARGETS = (1, 2)
LIMIT = 40  # bars a trade may run
FWD = 10  # bars for the forward move
MIN_R = 0.25  # least risk, in bar vols, as stophunt.py
PARK_BARS = 10  # production's pullback_bars
MINUTES = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30, "1h": 60}


# ---------------------------------------------------------------------------------------- simulation

def barrier(h, lo, c, j, s, entry, stop, target, end, fill_bar_checked):
    """Exit price of a trade entered at `entry` during bar j: the stop, the target, or bar end's
    close. With `fill_bar_checked`, bar j's own range can stop it (never target it)."""
    if fill_bar_checked and (lo[j] <= stop if s > 0 else h[j] >= stop):
        return stop
    for m in range(j + 1, end + 1):
        hit_stop = lo[m] <= stop if s > 0 else h[m] >= stop
        hit_target = h[m] >= target if s > 0 else lo[m] <= target
        if hit_stop:  # both in one bar: the stop, conservatively
            return stop
        if hit_target:
            return target
    return c[end]


def trade(h, lo, c, j, s, entry, stop, unit, fill_bar_checked):
    """Own-R results at each target, and the forward move, for an entry at `entry` in bar j."""
    end = min(j + LIMIT, len(c) - 1)
    if end <= j:
        return None
    risk = s * (entry - stop)
    if not risk > MIN_R * unit:
        return None
    out = {}
    for k in TARGETS:
        exit_ = barrier(h, lo, c, j, s, entry, stop, entry + s * k * risk, end, fill_bar_checked)
        out[f"r{k}"] = s * (exit_ - entry) / risk
    fwd_end = min(j + FWD, len(c) - 1)
    # Where the fill bar closed against the entry (negative: it closed through the price, the
    # curse's signature), and the drift after it (zero on a martingale; negative if fills keep
    # running against the order).
    out["thru"] = s * (c[j] - entry) / unit
    out["after"] = s * (c[fwd_end] - c[j]) / unit
    out["risk"] = risk
    return out


def run() -> None:
    touches = json.loads((TOUCHES / f"{UNIVERSE}.touches.json").read_text())
    frames = {}
    for sym in ind.SYMBOLS[UNIVERSE]:
        for iv in ind.INTERVALS:
            df = ind.frame(sym, iv)
            if df is not None and len(df) > 2 * ind.SWING:
                frames[(sym.lower(), iv)] = df
    fam_of = {s.lower(): ind.FAMILY.get(s, "walks") for s in ind.SYMBOLS[UNIVERSE]}
    series = {}
    for key, df in frames.items():
        x = ind.indicators(df)
        series[key] = (df["open"].to_numpy(), df["high"].to_numpy(), df["low"].to_numpy(),
                       df["close"].to_numpy(), x["vol"], df["ts"].to_numpy())
    print(f"{UNIVERSE}: {len(series)} series, {len(touches):,} touches", flush=True)
    rows = []
    for n, z in enumerate(touches):
        options = [z["interval"]] if z["interval"] in ind.MINUTES else list(ind.INTERVALS)
        for iv in options:
            key = (z["feed"], iv)
            if key not in series:
                continue
            o, h, lo, c, vol, ts = series[key]
            i = int(np.searchsorted(ts, z["time"]))
            if not (i < len(ts) and ts[i] == z["time"] and i >= ind.SWING):
                continue
            v = vol[i]
            if not np.isfinite(v) or v <= 0:
                break
            s = 1 if z["above"] else -1
            level, unit = z["level"], v * c[i]
            stop = level - s * BUFFER * unit
            cost_vol = ind.COST_V[fam_of[z["feed"]]] * np.sqrt(5 / ind.MINUTES[iv])
            mkt = trade(h, lo, c, i, s, c[i], stop, unit, False)
            if mkt is None:
                break
            m_target = c[i] + s * 2 * mkt["risk"]
            m_exit = barrier(h, lo, c, i, s, c[i], stop, m_target, min(i + LIMIT, len(c) - 1), False)
            base = {"universe": UNIVERSE, "family": fam_of[z["feed"]], "feed": z["feed"], "interval": iv,
                    "time": z["time"], "m_r1": mkt["r1"] - cost_vol * unit / mkt["risk"],
                    "m_r2": mkt["r2"] - cost_vol * unit / mkt["risk"], "m_r2_gross": mkt["r2"],
                    "m_pnl": s * (m_exit - c[i]) / unit - cost_vol, "m_after": mkt["after"]}
            for k in KS:
                limit = level - s * k * unit
                for rule, extra in (("touch", 0.0), ("through", TICK * unit)):
                    for life in LIVES:
                        row = {**base, "k": k, "rule": rule, "life": life, "filled": 0,
                               "r1": 0.0, "r2": 0.0, "r2_gross": 0.0, "pnl": 0.0, "thru": np.nan,
                               "after": np.nan}
                        if s * (c[i] - limit) <= 0:  # already at or past the limit at the touch
                            j, fill = i, c[i]
                        else:
                            j, fill = None, None
                            for m in range(i + 1, min(i + life + 1, len(c))):
                                if (lo[m] <= limit - extra) if s > 0 else (h[m] >= limit + extra):
                                    j = m
                                    fill = min(o[m], limit) if s > 0 else max(o[m], limit)
                                    break
                        if j is not None:
                            got = trade(h, lo, c, j, s, fill, stop, unit, j > i)
                            if got is not None:
                                cost_r = cost_vol * unit / got["risk"]
                                exit_ = barrier(h, lo, c, j, s, fill, stop, m_target,
                                                min(j + LIMIT, len(c) - 1), j > i)
                                row.update(filled=1, r1=got["r1"] - cost_r, r2=got["r2"] - cost_r,
                                           r2_gross=got["r2"], pnl=s * (exit_ - fill) / unit - cost_vol,
                                           thru=got["thru"], after=got["after"])
                        rows.append(row)
            break
        if n % 20_000 == 0:
            print(f"  {n:,} touches, {len(rows):,} rows", flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_pickle(OUT / f"{UNIVERSE}.pkl.gz")
    print(f"{UNIVERSE}: {len(rows):,} rows written", flush=True)


# ---------------------------------------------------------------------------------------- scoring

def clustered(diff: pd.Series, g: pd.DataFrame) -> tuple[float, float]:
    """Mean of `diff` and its t, standard error clustered by series-day."""
    d = diff.to_numpy(dtype=float)
    ok = np.isfinite(d)
    if ok.sum() < 5:
        return float("nan"), float("nan")
    cluster = (g["feed"].astype(str) + "|" + g["interval"].astype(str) + "|"
               + (g["time"] // 86_400).astype(int).astype(str)).to_numpy()[ok]
    d = d[ok]
    m = d.mean()
    sums = pd.Series(d - m).groupby(cluster).sum()
    se = np.sqrt((sums**2).sum()) / len(d)
    return float(m), float(m / se) if se > 0 else float("nan")


def report() -> None:
    # Our own outputs, written by `run` above - not data from anywhere else.
    frames = [pd.read_pickle(p) for p in sorted(OUT.glob("*.pkl.gz"))]
    df = pd.concat(frames, ignore_index=True)
    cut = df["time"].quantile(0.6)
    walks = df[df["universe"] == "walks"]
    wdiff = {}
    for (k, rule, life), g in walks.groupby(["k", "rule", "life"]):
        wdiff[(k, rule, life)] = (g["r2"] - g["m_r2"]).mean()
    print("per signal: net R at the 2R target, limit (misses 0) minus market on the same touches;")
    print("filled: the fills' R against the market's R on those touches; missed: market R where it never filled;")
    print("thru: where the fill bar closed against the fill price (vol; negative = through it); after: the fills'")
    print("own 10-bar drift after the fill bar (vol; 0 on a martingale), with the market entry's on those touches\n")
    for (fam, iv), g in df.groupby(["family", "interval"]):
        base = g.drop_duplicates(["feed", "interval", "time"])
        print(f"== {fam} · {iv} · touches {len(base):,} · market net R 2R {base['m_r2'].mean():+.3f} "
              f"(gross {base['m_r2_gross'].mean():+.3f}) · 1R {base['m_r1'].mean():+.3f} · unit P&L "
              f"{base['m_pnl'].mean():+.3f} vol")
        for (k, rule, life), v in g.groupby(["k", "rule", "life"]):
            d, t = clustered(v["r2"] - v["m_r2"], v)
            d1, _ = clustered(v["r1"] - v["m_r1"], v)
            dp, tp = clustered(v["pnl"] - v["m_pnl"], v)
            f = v[v["filled"] == 1]
            u = v[v["filled"] == 0]
            halves = [(p["r2"] - p["m_r2"]).mean() for p in (v[v["time"] < cut], v[v["time"] >= cut])]
            after = f["after"].mean() if len(f) else float("nan")
            m_after = f["m_after"].mean() if len(f) else float("nan")
            thru = f["thru"].mean() if len(f) else float("nan")
            verdict = ("PASS" if d >= 0.03 and t >= 3 and min(halves) > 0 and fam != "walks"
                       and d > wdiff.get((k, rule, life), 0.0) else "")
            print(f"  k {k:4.2f} {rule:7s} life {life:2d} | fill {v['filled'].mean():5.1%} | per signal "
                  f"{d:+.3f} (t {t:+.1f}) 1R {d1:+.3f} | halves {halves[0]:+.3f} / {halves[1]:+.3f} | "
                  f"walks {wdiff.get((k, rule, life), float('nan')):+.3f} | filled {f['r2'].mean():+.3f} vs "
                  f"{f['m_r2'].mean():+.3f} | missed {u['m_r2'].mean():+.3f} | thru {thru:+.3f} after {after:+.3f} "
                  f"(market {m_after:+.3f}) | "
                  f"unit P&L {dp:+.3f} (t {tp:+.1f}) {verdict}")


# ---------------------------------------------------------------------------------------- the journal

def boot(values: np.ndarray, days: np.ndarray, n: int = 2000, seed: int = 0):
    ok = np.isfinite(values)
    values, days = values[ok], days[ok]
    if len(values) < 5:
        return float("nan"), (float("nan"), float("nan"))
    uniq = np.unique(days)
    by = {d: values[days == d] for d in uniq}
    rng = np.random.default_rng(seed)
    means = [np.concatenate([by[d] for d in rng.choice(uniq, len(uniq))]).mean() for _ in range(n)]
    return float(values.mean()), tuple(np.quantile(means, [0.025, 0.975]))


def fmt(m, ci):
    return f"{m:+.3f} [{ci[0]:+.3f}, {ci[1]:+.3f}]"


def journal_outcomes(conn) -> None:
    rows = []
    for t, ctx in conn.execute("SELECT time, context FROM entries WHERE kind='outcome' AND actor='trading'"):
        d = json.loads(ctx or "{}")
        if not isinstance(d.get("r_multiple"), int | float):
            continue
        entered = t - float(d.get("seconds") or 0)
        rows.append({"r": float(d["r_multiple"]), "pullback": bool(d.get("after_pullback")),
                     "strategy": str(d.get("strategy")), "adverse": d.get("adverse_r"), "best": d.get("best_r"),
                     "day": int(entered // 86_400)})
    df = pd.DataFrame(rows)
    df["adverse"] = pd.to_numeric(df["adverse"], errors="coerce")
    df["best"] = pd.to_numeric(df["best"], errors="coerce")
    print(f"JOURNAL TRADES: {len(df)} closed with an R ({df['pullback'].sum()} after a pullback)")
    for label, g in (("all", df), ("thesis-only", df[df["strategy"] == "thesis-only"])):
        for name, part in (("after pullback", g[g["pullback"]]), ("at market", g[~g["pullback"]])):
            m, ci = boot(part["r"].to_numpy(), part["day"].to_numpy())
            print(f"  {label:12s} {name:15s} n={len(part):3d} R {fmt(m, ci)} | hit {np.mean(part['r'] > 0):.0%}"
                  f" | adverse {part['adverse'].mean():.2f}R best {part['best'].mean():.2f}R")


def journal_parks(conn) -> None:
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from research.harness.sweepregimes import bars_for, spreads

    spread = spreads(conn)
    found, seen = [], set()
    for t, rationale, ctx in conn.execute(
        "SELECT time, rationale, context FROM entries WHERE kind='observation' AND actor='trading' "
        "AND title LIKE 'declined%' AND rationale LIKE 'waiting%'"
    ):
        got = re.search(r"holding out for ([0-9.]+)", rationale or "")
        d = json.loads(ctx or "{}")
        if not got or not all(isinstance(d.get(k), int | float) for k in ("entry", "stop", "target")):
            continue
        key = (d.get("feed"), round(float(got.group(1)), 6))
        if key in seen:
            continue
        seen.add(key)
        found.append({"time": float(t), "feed": str(d["feed"]), "interval": str(d.get("interval")),
                      "strategy": str(d.get("strategy")), "s": 1 if d.get("side") == "buy" else -1,
                      "entry": float(d["entry"]), "stop": float(d["stop"]), "target": float(d["target"]),
                      "trigger": float(got.group(1))})
    print(f"\nJOURNAL PARKS: {len(found)} distinct parked signals (feed x trigger)")
    bars = sqlite3.connect(f"file:{BARS}?mode=ro", uri=True, timeout=300.0)
    by_feed = defaultdict(list)
    for p in found:
        by_feed[p["feed"]].append(p)
    rows = []
    for feed, part in by_feed.items():
        data, stamps = bars_for(bars, feed)
        if not data:
            continue
        ts = np.array(stamps)
        o, h, lo, c = (np.array([r[k] for r in data]) for k in (1, 2, 3, 4))
        bps = spread.get(feed, 0.0)
        for p in part:
            i = int(np.searchsorted(ts, p["time"]))
            span = PARK_BARS * MINUTES.get(p["interval"], 5)
            if i + 2 * span + 1 >= len(c) or ts[i] - p["time"] > 120:
                continue
            s, stop, target = p["s"], p["stop"], p["target"]
            cost = bps * p["entry"] / 10_000

            def run_from(j, entry, checked):
                risk = s * (entry - stop)
                if risk <= 0:
                    return None
                exit_ = barrier(h, lo, c, j, s, entry, stop, target, min(j + span, len(c) - 1), checked)
                after = s * (c[min(j + span, len(c) - 1)] - c[j])
                return (s * (exit_ - entry) - cost) / risk, after, s * (c[j] - entry)

            mkt = run_from(i, p["entry"], False)
            if mkt is None:
                continue
            risk_m = s * (p["entry"] - stop)
            for rule, extra in (("touch", 0.0), ("through", bps * p["trigger"] / 10_000)):
                j = None
                for m in range(i, min(i + span + 1, len(c))):
                    if (lo[m] <= p["trigger"] - extra) if s > 0 else (h[m] >= p["trigger"] + extra):
                        j = m
                        break
                row = {"feed": feed, "time": p["time"], "rule": rule, "strategy": p["strategy"],
                       "m_r": mkt[0], "m_after": mkt[1] / risk_m, "filled": 0, "r": 0.0, "after": np.nan,
                       "thru": np.nan,
                       "day": int(p["time"] // 86_400)}
                if j is not None:
                    fill = min(o[j], p["trigger"]) if s > 0 else max(o[j], p["trigger"])
                    got = run_from(j, fill, j > i)
                    if got is not None:
                        row.update(filled=1, r=got[0], after=got[1] / risk_m, thru=got[2] / risk_m)
                rows.append(row)
    df = pd.DataFrame(rows)
    if df.empty:
        print("  no parks could be replayed")
        return
    for rule, g in df.groupby("rule"):
        f, u = g[g["filled"] == 1], g[g["filled"] == 0]
        m, ci = boot((g["r"] - g["m_r"]).to_numpy(), g["day"].to_numpy())
        print(f"  {rule:7s} n={len(g)} fill {g['filled'].mean():.0%} | per signal park {g['r'].mean():+.3f}R vs "
              f"market {g['m_r'].mean():+.3f}R, diff {fmt(m, ci)} | fills {f['r'].mean():+.3f}R vs market "
              f"{f['m_r'].mean():+.3f}R on them | missed (market R) {u['m_r'].mean():+.3f} | in market-risk units: fill "
              f"bar closed {f['thru'].mean():+.3f} past the fill, drift after {f['after'].mean():+.3f} against the "
              f"market's {f['m_after'].mean():+.3f}")


def journal() -> None:
    conn = sqlite3.connect(f"file:{JOURNAL}?mode=ro", uri=True, timeout=300.0)
    journal_outcomes(conn)
    journal_parks(conn)


if __name__ == "__main__":
    {"run": run, "report": report, "journal": journal}[PART]()
