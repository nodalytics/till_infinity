"""The time core's alphabets on real markets, against walks given the same calendar.

Every real series is cut into chunks of CHUNK bars and each chunk is parsed with the time core. Its
nulls are walks on the chunk's OWN timestamps - weekends, closures and holidays included - so every
calendar anchor, window and HTF close is the same, and only what price does differs:

  profile   an iid walk whose volatility follows the chunk's own hour-of-day profile (the sd of
            close-to-close changes per UTC hour) with its own overnight jumps (`synth.matched_profiled`):
            THE null for a time effect - without it any time-of-day pattern of volatility would read
            as a time effect of the language
  clustered the same with GARCH(1,1) clustering on top (alpha 0.05, beta 0.94): real volatility
            clusters, and a stall or a tempo state can come from clustering alone
  flat      one volatility for every hour (`synth.matched_on_calendar`), to show what the plain
            matched walk would have called a time effect
Each walk gets a tick volume (`synth.ticks`). R sets of each kind are drawn; a real number is
compared with each kind's R set values (z = (real - mean) / sd over the sets).

Measured per item: event rates per 1,000 bars; shares (a share of events or of bars); the hour
concentration of BREAKs; and, for the events used as signals, P(>= N R) - the most R reached before
the stop, horizon HORIZON bars, the stop checked first on every bar - against each walk and 1/(N+1).

  SIGNAL                         entry (close of)    side                 stop
  fade the first move [window]   its known_at bar    against the move     the first swing's extreme
  BREAK [all, LATE, EARLY]       its known_at bar    the break's          the origin's far edge

Real data: MT5 15-minute bars (UTC) on the lab, MT5BT_DB; the markets in MARKETS. Deriv's synthetic
indices are markets in their own right and are reported as markets, never as a control.

  MT5BT_DB=... python research/mcfl/time_study.py [--markets ...] [--chunk 6000] [--reps 3] [--workers 16]
  python research/mcfl/time_study.py --demo     # no market data: two generated "markets", to test the code

z is (real - the walk sets' mean) / max(the walk sets' sd, the real number's own binomial or Poisson
standard error): with a few walk sets their sd alone is too rough, and the real number is a sample too.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
import zlib
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcfl import synth  # noqa: E402

OUT = Path(__file__).resolve().parent / "out"
MARKETS = ("EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "US SP 500", "US Tech 100", "Germany 40", "US Oil", "BTCUSD",
           "ETHUSD", "Volatility 75 Index", "Step Index")
CRYPTO_CAL = ("BTCUSD", "ETHUSD", "Volatility 75 Index", "Step Index")
"""Markets that never close: no holidays, no weekends (`calendars.CRYPTO`); the rest use NYSE's."""
DERIV = ("Volatility 75 Index", "Step Index")
KINDS = ("profile", "clustered", "flat")
GARCH = (0.05, 0.94)
N_LEVELS = (1, 2, 3, 4, 5, 10)
HORIZON = 500
SESSIONS = ("ASIA", "LONDON", "OVERLAP", "NY")


# ---------------------------------------------------------------- data

def load_mt5(sym: str, db: str, interval: str = "15m") -> pd.DataFrame | None:
    con = sqlite3.connect(db)
    try:
        d = pd.read_sql_query("SELECT ts, open, high, low, close, volume FROM bars WHERE symbol = ? AND interval = ?"
                              " ORDER BY ts", con, params=(sym, interval))
    finally:
        con.close()
    if d.empty:
        return None
    d = d.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
    d["ts"] = d["ts"].astype(np.int64)
    d["high"] = d[["open", "high", "close"]].max(axis=1)
    d["low"] = d[["open", "low", "close"]].min(axis=1)
    return d


def demo_markets(n: int = 24000) -> dict[str, pd.DataFrame]:
    """Two generated stand-ins (no market data): an FX-like calendar with a London / New York profile,
    and a 24/7 one with GARCH clustering. For testing the study's code only."""
    t0 = 1_704_067_200
    out = {}
    for name, market, garch in (("DEMO_FX", "fx", None), ("DEMO_247", "crypto", GARCH)):
        ts, t = [], t0
        while len(ts) < n:
            wd, h = (t // 86400 + 3) % 7, (t % 86400) // 3600
            if market == "crypto" or not ((wd == 4 and h >= 21) or wd == 5 or (wd == 6 and h < 22)):
                ts.append(t)
            t += 900
        sig = np.where((np.arange(24) >= 7) & (np.arange(24) < 17), 1.6, 0.7)
        df = synth.profiled(np.array(ts), sig, 0.5, seed=zlib.crc32(name.encode()), garch=garch)
        out[name] = synth.ticks(df, seed=7)
    return out


# ---------------------------------------------------------------- what is measured

def mfe(t: int, side: int, stop: float, hi: np.ndarray, lo: np.ndarray, cl: np.ndarray) -> float | None:
    """The most R reached `side`'s way after entering at the close of bar t, before the stop."""
    n = len(cl)
    if t + 1 >= n:
        return None
    entry = cl[t]
    risk = side * (entry - stop)
    if not risk > 0:
        return None
    best = 0.0
    for k in range(t + 1, min(n, t + 1 + HORIZON)):
        if (lo[k] <= stop) if side > 0 else (hi[k] >= stop):
            break
        best = max(best, side * ((hi[k] if side > 0 else lo[k]) - entry) / risk)
    return best


def measure(df: pd.DataFrame, ch) -> dict:
    from mcfl.core import Dir
    n = ch.n
    ts = df["ts"].to_numpy(np.int64)
    hr = (ts // 3600) % 24
    c = sorted(ch.of("CANDLE"), key=lambda e: e.at)
    hi, lo, cl = (np.array([e.get(k) for e in c]) for k in ("high", "low", "close"))
    ids = ch.by_id()
    rates: Counter = Counter()
    shares: dict[str, list[int]] = {}

    def share(name: str, num: int, den: int) -> None:
        x = shares.setdefault(name, [0, 0])
        x[0] += int(num)
        x[1] += int(den)

    # item 1: episodes
    for e in ch.of("EPISODE"):
        k = ids[e.get("of")].type
        rates[f"EPISODE[{k}:{e.get('outcome')}]"] += 1
        if k == "ZONE":
            share("ZONE episodes across a closure (gap_sec > 0)", e.time.gap_sec > 0, 1)
            share("ZONE episodes over 96 bars", e.time.bars > 96, 1)
    # item 2: interval relations
    inw = ch.of("IN_WINDOW")
    rev = len(ch.of("REVISIT"))
    for s in SESSIONS:
        share(f"REVISITs in {s} (IN_WINDOW)", sum(1 for e in inw if e.get("kind") == "SESSION" and e.get("name") == s),
              rev)
        share(f"bars in {s}", sum(1 for x in c if x.get("session") == s), n)
    tk = ch.of("SESSION_EXTREME_TAKEN")
    share("session high/low taken inside a killzone", sum(1 for e in inw if e.get("kind") == "KILLZONE"), len(tk))
    share("... base: bars inside a killzone", sum(1 for x in c if x.get("killzone") != "NONE"), n)
    pt = ch.of("POOL_TAKEN")
    share("pool taken inside a macro window", sum(1 for e in inw if e.get("kind") == "MACRO"), len(pt))
    share("... base: bars wholly inside a macro window", _bars_in(ts, ch.clock.length, "MACRO"), n)
    # item 3: calendar
    br = ch.of("BREAK")
    me = np.array([x.get("month_end") for x in c], bool)
    share("BREAKs on month-end days", sum(1 for b in br if me[b.at]), len(br))
    share("... base: bars on month-end days", int(me.sum()), n)
    dow = np.array([x.get("dow") for x in c])
    share("BREAKs on Mondays", sum(1 for b in br if dow[b.at] == "MON"), len(br))
    share("... base: bars on Mondays", int((dow == "MON").sum()), n)
    # item 4: anchors - where in a session its extremes form (a walk's are at the ends: the arcsine law)
    for e in ch.of("SESSION_EXTREME"):
        a, b = e.get("start"), e.get("end")
        if b - a >= 8:
            pos = (e.at - a) / (b - a)
            share("session extremes in the first quarter of the session", pos < 0.25, 1)
            share("session extremes in the last quarter of the session", pos > 0.75, 1)
    # item 5: elapsed / remaining
    prog = np.array([x.get("prog_4h") for x in c], float)
    share("BREAKs in the last quarter of a 4h bar", sum(1 for b in br if b.at > 0 and prog[b.at] > 0.75), len(br))
    share("... base: bars in the last quarter of a 4h bar", int((prog[1:] > 0.75).sum()), n - 1)
    # item 6: time-based events
    for e in ch.of("TIMEOUT"):
        rates[f"TIMEOUT[{e.get('kind')}]"] += 1
    share("ZONEs that TIMEOUT (no revisit in 48 bars)", sum(1 for e in ch.of("TIMEOUT") if e.get("kind") == "ZONE"),
          sum(1 for z in ch.of("ZONE") if z.known_at + 48 < n))
    rates["STALL"] = len(ch.of("STALL"))
    for e in ch.of("SESSION_FIRST_MOVE"):
        rates[f"SESSION_FIRST_MOVE[{e.get('kind')}]"] += 1
    rates.update(f"{e.type}[{e.get('of_type')}]" for e in ch.of("LATE", "EARLY"))
    sx = {(e.get("session"), e.at, e.dir): e for e in ch.of("SESSION_EXTREME")}
    for e in ch.of("SESSION_FIRST_MOVE"):
        if e.get("kind") != "SESSION":
            continue
        w = ids[e.get("window")]
        share("first swing is the session's own extreme", (e.get("name"), e.at, e.dir) in sx, 1)
        # reversed: price back through the window's open before beyond the first swing's extreme
        s = 1 if e.dir is Dir.UP else -1
        rev_ = None
        for k in range(e.known_at + 1, min(n, e.known_at + 1 + HORIZON)):
            beyond = (hi[k] > e.get("price")) if s > 0 else (lo[k] < e.get("price"))
            back = (lo[k] <= w.get("open")) if s > 0 else (hi[k] >= w.get("open"))
            if beyond or back:
                rev_ = back and not beyond
                break
        if rev_ is not None and s * (cl[e.known_at] - w.get("open")) > 0:
            share("first move reverses through the session open first (Judas)", rev_, 1)
    # item 7: clocks - how bursty the event clock is against the bar clock
    ev = np.zeros(n)
    for e in ch.entities:
        if e.type in ("EXTREME", "VOID", "BREAK", "DISPLACE", "BREACH_REVERT", "DELIVERY_SHIFT"):
            ev[e.known_at] += 1
    blocks = ev[:n // 16 * 16].reshape(-1, 16).sum(1)
    shares["event clock: variance / mean of events per 16 bars (x1000)"] = [
        int(1000 * blocks.var() / blocks.mean()) if blocks.mean() > 0 else 0, 1000]
    # item 8: seasonality and tempo
    tv = [x.get("tod_vol") for x in c]
    share("bars UNUSUAL for their hour (tod_vol)", sum(v == "UNUSUAL" for v in tv), sum(v != "WARMUP" for v in tv))
    states = sorted(ch.of("TEMPO_STATE"), key=lambda e: e.at)
    for a_, b_ in zip(states, states[1:] + [None]):
        end = b_.at if b_ is not None else n
        for st in ("FAST", "SLOW"):
            share(f"time in TEMPO_STATE {st}", (end - a_.at) * (a_.get("state") == st), end - a_.at)
    rates.update(f"TEMPO_STATE[{e.get('state')}]" for e in states)
    hb = Counter(int(hr[b.at]) for b in br)
    hn = Counter(int(h) for h in hr)
    # signals
    sig: dict[str, list[float]] = {}

    def add(name: str, v: float | None) -> None:
        if v is not None:
            sig.setdefault(name, []).append(v)

    for e in ch.of("SESSION_FIRST_MOVE"):
        s = -1 if e.dir is Dir.UP else 1
        v = mfe(e.known_at, s, e.get("price"), hi, lo, cl)
        add(f"fade the first move: {e.get('kind').lower()}", v)
        if e.get("name") in ("LONDON", "NY", "LONDON_KZ", "NY_AM_KZ"):
            add(f"fade the first move: {e.get('name')}", v)
    late = {e.get("of"): e.type for e in ch.of("LATE", "EARLY")}
    for b in br:
        s = 1 if b.dir is Dir.UP else -1
        v = mfe(b.known_at, s, ids[b.get("origin")].get("far"), hi, lo, cl)
        add("BREAK: all", v)
        if b.id in late:
            add(f"BREAK: {late[b.id]}", v)
    return {"bars": n, "rates": rates, "shares": shares, "hour_breaks": hb, "hour_bars": hn, "mfe": sig}


def _bars_in(ts: np.ndarray, length: np.ndarray, kind: str) -> int:
    """Bars lying wholly inside a window of `kind` (open and close within its scheduled interval)."""
    from mcfl.anchors import layout
    inside = np.zeros(len(ts), bool)
    for w in layout(ts).values():
        if w.kind == kind:
            inside |= w.inn & (ts + length <= w.end)
    return int(inside.sum())


# ---------------------------------------------------------------- runs

def chunks(df: pd.DataFrame, size: int) -> list[pd.DataFrame]:
    k = len(df) // size
    off = len(df) - k * size  # the most recent k chunks
    return [df.iloc[off + i * size: off + (i + 1) * size].reset_index(drop=True) for i in range(k)]


def job(args: tuple) -> tuple:
    from mcfl import calendars
    from mcfl.parse import parse
    market, i, kind, rep, df = args
    seed = zlib.crc32(f"{market}|{i}|{kind}|{rep}".encode()) % 2**31
    if kind == "profile":
        df = synth.ticks(synth.matched_profiled(df, seed), seed=seed + 1)
    elif kind == "clustered":
        df = synth.ticks(synth.matched_profiled(df, seed, garch=GARCH), seed=seed + 1)
    elif kind == "flat":
        w = synth.matched_on_calendar(df, seed)
        shift = float(df["open"].iloc[0]) - synth.START  # from the chunk's own price, as the others
        df = synth.ticks(w.assign(**{k: w[k] + shift for k in ("open", "high", "low", "close")}), seed=seed + 1)
    cal = calendars.CRYPTO if market in CRYPTO_CAL or market.endswith("247") else calendars.NYSE
    t = time.time()
    ch = parse(df, cal=cal)
    out = measure(df, ch)
    out["secs"] = time.time() - t
    return market, i, kind, rep, out


def pool(rs: list[dict]) -> dict:
    tot = {"bars": 0, "rates": Counter(), "shares": {}, "hour_breaks": Counter(), "hour_bars": Counter(), "mfe": {}}
    for r in rs:
        tot["bars"] += r["bars"]
        tot["rates"].update(r["rates"])
        for k, (a, b) in r["shares"].items():
            x = tot["shares"].setdefault(k, [0, 0])
            x[0] += a
            x[1] += b
        tot["hour_breaks"].update(r["hour_breaks"])
        tot["hour_bars"].update(r["hour_bars"])
        for k, v in r["mfe"].items():
            tot["mfe"].setdefault(k, []).extend(v)
    return tot


def concentration(p: dict) -> float:
    """How unevenly BREAKs fall over the hours, against the bars: sum over hours of (share of breaks -
    share of bars)^2 / share of bars (chi-square / n), 0 when breaks follow the bars."""
    nb, nn = sum(p["hour_breaks"].values()), sum(p["hour_bars"].values())
    if not nb:
        return float("nan")
    return float(sum((p["hour_breaks"][h] / nb - p["hour_bars"][h] / nn) ** 2 / (p["hour_bars"][h] / nn)
                     for h in p["hour_bars"] if p["hour_bars"][h]))


def _z(x: float, xs: list[float], se: float) -> str:
    """(real - walk mean) / the larger of the walk sets' sd and the real number's own sampling error -
    with a handful of walk sets their sd alone is too rough to divide by."""
    xs = [v for v in xs if v == v]
    if len(xs) < 2 or x != x:
        return "     "
    sd = max(float(np.std(xs, ddof=1)), se)
    return f"{(x - np.mean(xs)) / sd:+5.1f}" if sd > 0 else "  0.0"


def _fmt_row(name: str, real: float, walks: dict[str, list[float]], se: float, width: int = 64,
             f: str = "{:8.3f}") -> str:
    cells = [f.format(real)]
    for k in KINDS:
        xs = walks.get(k, [])
        fin = [v for v in xs if v == v]
        m = float(np.mean(fin)) if fin else float("nan")
        cells.append(f.format(m) + " " + _z(real, xs, se))
    return f"  {name:<{width}} " + "   ".join(cells)


def _se_share(p: float, n: int) -> float:
    return float(np.sqrt(p * (1 - p) / n)) if n and p == p else 0.0


def report(results: list[tuple], markets: list[str], reps: int) -> list[str]:
    by: dict[tuple, list[dict]] = {}
    for market, i, kind, rep, out in results:
        by.setdefault((market, kind, rep), []).append(out)
    L = []

    def block(title: str, mk: list[str]) -> None:
        real = pool([o for m in mk for o in by.get((m, "real", 0), [])])
        if not real["bars"]:
            return
        walks = {k: [pool([o for m in mk for o in by.get((m, k, r), [])]) for r in range(reps)] for k in KINDS}
        L.append(f"-- {title}: {real['bars']:,} real bars; walks: {', '.join(f'{k} x{reps}' for k in KINDS)}")
        L.append(f"  {'':<64} {'real':>8}   " + "   ".join(f"{k:>8} {'z':>5}" for k in KINDS))
        L.append("  per 1,000 bars")
        keys = sorted(set(real["rates"]) | {k for ws in walks.values() for w in ws for k in w["rates"]})
        for k in keys:
            L.append(_fmt_row(k, 1000 * real["rates"][k] / real["bars"],
                              {kk: [1000 * w["rates"][k] / w["bars"] for w in ws] for kk, ws in walks.items()},
                              1000 * np.sqrt(real["rates"][k]) / real["bars"]))
        L.append("  shares (real n in brackets)")
        for k in real["shares"]:
            a, b = real["shares"][k]
            x = a / b if b else float("nan")
            se = 0.0 if k.startswith("event clock") else _se_share(x, b)
            L.append(_fmt_row(f"{k} [{b}]", x, {kk: [w["shares"][k][0] / w["shares"][k][1] if w["shares"].get(k, [0, 0])[1]
                                                     else float("nan") for w in ws] for kk, ws in walks.items()}, se))
        L.append(_fmt_row("BREAK hour concentration (chi2 / n)", concentration(real),
                          {kk: [concentration(w) for w in ws] for kk, ws in walks.items()}, 0.0, f="{:8.4f}"))
        L.append("  signals: P(>= N R) before the stop [real n]; 1/(N+1) = " +
                 ", ".join(f"{N}:{1 / (N + 1):.3f}" for N in N_LEVELS))
        for s in sorted(real["mfe"]):
            xs = np.array(real["mfe"][s])
            for N in N_LEVELS:
                walk_p = {kk: [float(np.mean(np.array(w["mfe"].get(s, [])) >= N)) if w["mfe"].get(s) else float("nan")
                               for w in ws] for kk, ws in walks.items()}
                p = float(np.mean(xs >= N))
                L.append(_fmt_row(f"{s} P(>={N}R) [{len(xs)}]", p, walk_p, _se_share(p, len(xs))))
        L.append("")

    block("all markets", markets)
    block("all but Deriv", [m for m in markets if m not in DERIV])
    for m in markets:
        block(m, [m])
    return L


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--markets", default=",".join(MARKETS))
    ap.add_argument("--chunk", type=int, default=6000)
    ap.add_argument("--max-chunks", type=int, default=12)
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--out", default=str(OUT / "time.txt"))
    a = ap.parse_args()
    if a.demo:
        data = demo_markets()
    else:
        db = os.environ.get("MT5BT_DB")
        if not db or not Path(db).exists():
            raise SystemExit("set MT5BT_DB to the MT5 bars database (on the lab), or run --demo")
        data = {}
        for m in a.markets.split(","):
            d = load_mt5(m, db)
            if d is not None:
                data[m] = d
                print(f"  {m}: {len(d):,} bars from {pd.Timestamp(d['ts'].iloc[0], unit='s'):%Y-%m-%d}", flush=True)
    jobs = []
    for m, d in data.items():
        cs = chunks(d, a.chunk)[-a.max_chunks:]
        for i, cdf in enumerate(cs):
            jobs.append((m, i, "real", 0, cdf))
            for k in KINDS:
                for r in range(a.reps):
                    jobs.append((m, i, k, r, cdf))
    print(f"{len(jobs)} parses of {a.chunk} bars on {a.workers} workers", flush=True)
    t0 = time.time()
    results = []
    with ProcessPoolExecutor(a.workers) as ex:
        for k, res in enumerate(ex.map(job, jobs, chunksize=1)):
            results.append(res)
            if k % 50 == 0:
                print(f"  {k + 1}/{len(jobs)} done, {time.time() - t0:.0f}s", flush=True)
    head = [f"MCFL time core against walks on the same calendar: {len(data)} markets, 15-minute bars in chunks of "
            f"{a.chunk}, {a.reps} walks of each kind per chunk ({', '.join(KINDS)}); "
            f"{len(results)} parses in {time.time() - t0:.0f}s", ""]
    text = "\n".join(head + report(results, list(data), a.reps))
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(text + "\n")
    print(text)
    print(f"written {a.out}")


if __name__ == "__main__":
    main()
