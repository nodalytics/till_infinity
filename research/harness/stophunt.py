"""Do lagging indicators stop us being stopped out before the market goes our way?

The desk's claim: a zone entry is often right about direction but early. Price runs the stop, then
goes where the trade said. The hope is that waiting for an indicator avoids that. `indicators.md`
scored fixed-horizon returns and never tested this, and `widestop.md` found that a wider stop halves
the stopped share while price P&L stays flat. So this measures the complaint itself, trade by trade,
with a stop and a target.

The trade: every zone touch the production `Engine` opens (replayed exactly as `indicators.py` does)
is faded - long when price came down onto the level, short when it came up.

  stop     anchored to the **level**, not the entry: the level minus (long) or plus (short)
           B x the bar's volatility x price, with B = 0.5, 1 and 2
  R        the actual risk from *that entry* to the stop. A later entry nearer the stop risks less,
           and one that has already moved away risks more, so timing changes R, as it would live.
           Entries with R under 0.25 bar volatility are skipped: a stop that tight is noise
  target   1R, 2R and 3R from the entry
  limit    40 bars. A trade still open is closed at the 40th close, and its R is marked to that close
  order    a bar that touches both stop and target counts as stopped (the conservative reading)
  cost     the round trip in bar volatilities (`indicators.COST_V`, scaled to the interval), in R

Entries, each within 8 bars of the touch:

  touch      at the touch's close
  rsi ... macd, fib+rsi    `indicators.py`'s triggers
  sweep      the stop-hunt the desk describes: price trades through the level (a low under it,
             for a long), no close beyond the stop, and then a close back on the level's side -
             entered at that close
  candle     production's candlestick confirmation - `trading/candles.py` `confirms` exactly as
             `trading/service.py` `_candle_at` calls it: the last 3 closed bars of the entry
             timeframe, tolerance `price_distance(level, vol_bps, 0.25)` (the default
             `TRADING_CANDLE_TOLERANCE_VOL`), entered at the close of the first bar in the window
             where it names a pattern. This is the rule `TRADING_REQUIRE_CANDLE` switches on. The
             volatility is the bar volatility here, where production reads its own per-feed estimate
  wait:<x>   every touch, entered after a delay drawn from x's own delays, independent of the path

Reported per family, interval, buffer B and target k:

  stop       share of trades stopped
  s-then-r   **stopped, then the target price reached within the 40 bars** - the complaint,
             measured. Shown as a share of all trades, and as a share of stopped trades
  net R      mean R after costs, its difference from the touch and from the random wait, with
             t-stats clustered by series-day, and the difference from the touch in each half
  hit        share reaching the target
  share      trades as a share of the touches (a rule that trades fewer touches is also selecting)

Controls: walks we generate ourselves (iid Student-t(3), memoryless). There the barrier theorem says
every entry's net R is about minus its cost, whatever the timing. Deriv's indices are a market and
are reported as their own family.

Pre-registered: the claim holds for a rule on a family if, against the touch, it lowers **both** the
stop rate and the stopped-then-right rate, **and** raises net R by at least 0.05R with t >= 3, in
both halves, at a majority of (B, k) cells on that family, **and** the walks show no such rise.

Added after the smoke test on walks, before any market data was seen: the walks *do* rise, for a
mechanical reason. With the stop anchored to the level, a trigger that enters after price has moved
away from it risks more per trade, so the round-trip cost is fewer R and a bar that spans both stop
and target (counted as stopped) is rarer. The EMA and SMA reclaims gained +0.12-0.15R on memoryless
walks (t 4.2-4.4) this way. So the report also shows gross R, and judges each market cell by its
**difference from the same cell on the walks** (rule minus touch, market minus walks), needing
+0.05R at t >= 3 there too.

Added after the first full run, before this version's results: the market passes clustered in FX
15m, and the literal passes ranked the families by their cost (FX 0.8 > crypto 0.5 > metals 0.16),
which the walks (cost 0.15) cannot net out - the cost-per-R effect scales with the cost. So the
comparison with the walks is made on **gross** R, before costs, where the walks are a fair null
whatever the family's cost; net R is still reported and still has to clear the literal rule.

Run on the lab, one process per universe:
  UNIVERSE=real SEQLAB=$HOME/till_infinity/data/seqlab python research/harness/stophunt.py
  UNIVERSE=deriv ...    UNIVERSE=walks ...    then  PART=report
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import indicators as ind

from till_infinity.trading import candles
from till_infinity.trading.sizing import price_distance

UNIVERSE = os.environ.get("UNIVERSE", "real")
PART = os.environ.get("PART", "run")
OUT = Path(os.environ.get("OUT", ".data/stophunt"))
BUFFERS = (0.5, 1.0, 2.0)
TARGETS = (1, 2, 3)
LIMIT = 40
MIN_R = 0.25  # in bar volatilities of price
RULES = ("touch", "rsi", "stoch", "stochrsi", "bb", "ema", "sma", "macd", "fib+rsi", "sweep", "candle")


def sweep_entry(h, lo, c, i, s, level, stop) -> int | None:
    """The first close back on the level's side after price traded through the level without
    closing beyond the stop, within the window."""
    swept = False
    for j in range(i, min(i + ind.WINDOW + 1, len(c))):
        if s * (c[j] - stop) <= 0:
            return None  # closed beyond the stop: the level broke
        through = lo[j] < level if s > 0 else h[j] > level
        swept = swept or through
        if swept and s * (c[j] - level) > 0 and (j > i or through):
            return j
    return None


def candle_entry(o, h, lo, c, i, s, level, vol) -> int | None:
    """The first bar in the window whose last 3 closed bars `candles.confirms` accepts, exactly as
    the trading service asks it."""
    tolerance = price_distance(level, vol * 10_000, 0.25)
    for j in range(max(i, 2), min(i + ind.WINDOW + 1, len(c))):
        bars = [candles.Bar(o[m], h[m], lo[m], c[m]) for m in range(j - 2, j + 1)]
        if candles.confirms(bars, level, s > 0, tolerance):
            return j
    return None


def simulate(h, lo, c, j, s, stop, risk):
    """(R per target, stopped, stopped-then-right per target, hit per target) for an entry at the
    close of bar j."""
    end = min(j + LIMIT, len(c) - 1)
    if end <= j:
        return None
    hh, ll = h[j + 1 : end + 1], lo[j + 1 : end + 1]
    stopped_at = np.flatnonzero(ll <= stop if s > 0 else hh >= stop)
    ts = stopped_at[0] if len(stopped_at) else np.inf
    out = []
    for k in TARGETS:
        target = c[j] + s * k * risk
        reached = np.flatnonzero(hh >= target if s > 0 else ll <= target)
        tk = reached[0] if len(reached) else np.inf
        if tk < ts:
            r, stopped, then_right, hit = float(k), False, False, True
        elif np.isfinite(ts):
            r, stopped, then_right, hit = -1.0, True, bool(np.isfinite(tk)), False
        else:
            r, stopped, then_right, hit = float(s * (c[end] - c[j]) / risk), False, False, False
        out.append((k, r, stopped, then_right, hit))
    return out


def run() -> None:
    frames = {}
    for sym in ind.SYMBOLS[UNIVERSE]:
        for iv in ind.INTERVALS:
            df = ind.frame(sym, iv)
            if df is not None and len(df) > 2 * ind.SWING:
                frames[(sym, iv)] = df
    print(f"{UNIVERSE}: {len(frames)} series", flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    cache = OUT / f"{UNIVERSE}.touches.json"
    if cache.exists():
        touches = json.loads(cache.read_text())
    else:
        touches = ind.zones(frames)
        cache.write_text(json.dumps(touches))
    print(f"{UNIVERSE}: {len(touches):,} zone touches", flush=True)

    series = {}
    for (sym, iv), df in frames.items():
        x = ind.indicators(df)
        series[(sym.lower(), iv)] = (x, df["high"].to_numpy(), df["low"].to_numpy(), df["ts"].to_numpy(),
                                     df["open"].to_numpy())
    fam_of = {s.lower(): ind.FAMILY.get(s, "walks") for s, _ in frames}

    # pass 1: where each rule enters, per touch and buffer (the sweep depends on the stop)
    plans = []
    for z in touches:
        options = [z["interval"]] if z["interval"] in ind.MINUTES else list(ind.INTERVALS)
        for iv in options:
            key = (z["feed"], iv)
            if key not in series:
                continue
            x, h, lo, ts, o = series[key]
            i = int(np.searchsorted(ts, z["time"]))
            if not (i < len(ts) and ts[i] == z["time"] and i >= ind.SWING):
                continue
            v, c = x["vol"][i], x["close"]
            if not np.isfinite(v) or v <= 0:
                break
            s = 1 if z["above"] else -1
            for b in BUFFERS:
                stop = z["level"] - s * b * v * c[i]
                entries = {}
                for rule in RULES:
                    if rule == "sweep":
                        j = sweep_entry(h, lo, c, i, s, z["level"], stop)
                    elif rule == "candle":
                        j = candle_entry(o, h, lo, c, i, s, z["level"], v)
                    else:
                        j = ind.entry(rule, x, i, s, z["level"])
                    if j is not None:
                        entries[rule] = j
                plans.append((key, i, s, b, stop, v, z["time"], entries))
            break
    delays = {r: [] for r in RULES[1:]}
    for _key, i, _s, _b, _stop, _v, _t, entries in plans:
        for r, j in entries.items():
            if r != "touch":
                delays[r].append(j - i)

    # pass 2: simulate every entry, and every rule's random wait
    rng = np.random.default_rng(11)
    rows = []

    def trade(kind, key, j, s, stop, v, t, b):
        x, h, lo, _, _ = series[key]
        c = x["close"]
        if j >= len(c) - 1:
            return
        risk = s * (c[j] - stop)
        if not risk > MIN_R * v * c[j]:
            return
        got = simulate(h, lo, c, j, s, stop, risk)
        if got is None:
            return
        cost_r = ind.COST_V[fam_of[key[0]]] * np.sqrt(5 / ind.MINUTES[key[1]]) * v * c[j] / risk
        for k, r, stopped, then_right, hit in got:
            rows.append((kind, fam_of[key[0]], key[0], key[1], t, b, k, r - cost_r, r, stopped, then_right, hit))

    for n, (key, i, s, b, stop, v, t, entries) in enumerate(plans):
        for rule, j in entries.items():
            trade(rule, key, j, s, stop, v, t, b)
        for rule, ds in delays.items():
            if ds:
                trade(f"wait:{rule}", key, i + int(rng.choice(ds)), s, stop, v, t, b)
        if n % 20_000 == 0:
            print(f"  {n:,} of {len(plans):,} touch x buffer plans, {len(rows):,} rows", flush=True)
    df = pd.DataFrame(rows, columns=["rule", "family", "feed", "interval", "time", "b", "k", "net",
                                     "gross", "stopped", "then_right", "hit"])
    df["universe"] = UNIVERSE
    df.to_pickle(OUT / f"{UNIVERSE}.pkl.gz")
    print(f"{UNIVERSE}: {len(df):,} trade rows written", flush=True)


def _gross(g: pd.DataFrame) -> pd.DataFrame:
    """The same rows scored before costs, for `ind.welch`, which reads `net`."""
    return g.assign(net=g["gross"])


def report() -> None:
    df = pd.concat([pd.read_pickle(p) for p in sorted(OUT.glob("*.pkl.gz"))], ignore_index=True)
    cut = df["time"].quantile(0.6)
    walks = {}  # (interval, b, k, rule) -> (delta vs touch, its standard error) on our walks
    for (iv, b, k), g in df[df["family"] == "walks"].groupby(["interval", "b", "k"]):
        base = g[g["rule"] == "touch"]
        for rule in RULES[1:]:
            d, t = ind.welch(_gross(g[g["rule"] == rule]), _gross(base))
            if np.isfinite(t) and t != 0:
                walks[(iv, b, k, rule)] = (d, abs(d / t))
    print("net R after costs; stop = share stopped; s-then-r = stopped then target reached within 40 bars")
    print("gross vs touch = before costs; vs walks = gross (rule - touch) here minus the same on our walks")
    verdicts = []
    for (family, iv, b, k), g in df.groupby(["family", "interval", "b", "k"]):
        base = g[g["rule"] == "touch"]
        if len(base) < 50:
            continue
        n0 = len(base)
        print(f"\n== {family} · {iv} · stop {b} vol past the level · target {k}R · touch n={n0:,} "
              f"stop {base['stopped'].mean():.1%} s-then-r {base['then_right'].mean():.1%} "
              f"({base['then_right'].sum() / max(base['stopped'].sum(), 1):.0%} of stops) "
              f"net {base['net'].mean():+.3f} hit {base['hit'].mean():.1%}")
        for rule in RULES[1:]:
            r = g[g["rule"] == rule]
            if len(r) < 50:
                continue
            dt, tt = ind.welch(r, base)
            wait = g[g["rule"] == f"wait:{rule}"]
            dw, tw = ind.welch(r, wait) if len(wait) >= 50 else (float("nan"), float("nan"))
            halves = [ind.welch(p[p["rule"] == rule], p[p["rule"] == "touch"])[0]
                      for p in (g[g["time"] < cut], g[g["time"] >= cut])]
            dg, tg = ind.welch(_gross(r), _gross(base))
            dd, td = float("nan"), float("nan")
            if family != "walks" and (iv, b, k, rule) in walks and np.isfinite(tg) and tg != 0:
                wd, wse = walks[(iv, b, k, rule)]
                dd = dg - wd
                td = dd / np.sqrt((dg / tg) ** 2 + wse**2)
            literal = (r["stopped"].mean() < base["stopped"].mean()
                       and r["then_right"].mean() < base["then_right"].mean()
                       and dt >= 0.05 and tt >= 3 and min(halves) > 0)
            ok = literal and family != "walks" and dd >= 0.05 and td >= 3
            verdicts.append((family, iv, b, k, rule, literal, ok))
            print(f"  {rule:9s} n={len(r):7,} ({len(r) / n0:5.1%}) stop {r['stopped'].mean():5.1%}"
                  f" s-then-r {r['then_right'].mean():5.1%}"
                  f" ({r['then_right'].sum() / max(r['stopped'].sum(), 1):3.0%} of stops)"
                  f" | net {r['net'].mean():+.3f} vs touch {dt:+.3f} (t {tt:+.1f})"
                  f" vs wait {dw:+.3f} (t {tw:+.1f}) | gross vs touch {dg:+.3f} (t {tg:+.1f})"
                  f" vs walks {dd:+.3f} (t {td:+.1f})"
                  f" | halves {halves[0]:+.3f} / {halves[1]:+.3f}"
                  f" | hit {r['hit'].mean():5.1%}{'  PASS' if ok else '  (literal)' if literal else ''}")
    v = pd.DataFrame(verdicts, columns=["family", "interval", "b", "k", "rule", "literal", "ok"])
    for col, label in (("literal", "the literal rule"), ("ok", "the literal rule and beating the walks")):
        print(f"\ncells passing {label}, per rule and family (of 9 buffer x target cells per interval):")
        print(v.groupby(["family", "interval", "rule"])[col].sum().unstack("rule").fillna(0).astype(int).to_string())


if __name__ == "__main__":
    report() if PART == "report" else run()
