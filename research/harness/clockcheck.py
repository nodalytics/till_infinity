"""Validate the production hour-of-week clock and the Mondrian envelope against their studies.

PART=mse  The production `vol/clock.py` Clock, learned online per family from 1h bars in time
          order, as a multiplier on the production unit (the EWMA of true range, `Ranges`) for
          the next hour's |r|. The relative MSE against the unit alone, scale fitted per half on
          the last 40%. calendar-returns.md measured 0.937 / 0.948 on FX (New York clock) and
          0.957 / 0.958 on crypto. Metals and Deriv must read 1.000 (the clock does not scale them).
PART=env  The production envelope `Book` driven as the engine drives it (the z-score first, then
          the clock, then, on FX 15m, `Touches` for the boosted base), four ways: Mondrian on or
          off x clock on or off (VARIANT=mc, m, c, none). Scored on the last 40% as conformal.py
          scores: P10/P90 coverage overall and by ZMA bucket, pinball and width, from the quote
          actually published (a bucket's once it has its own history, else the pooled one).
          zma-conformal.md: FX N = 5 stretched-up P90 85.2% -> 89.9% under Mondrian.

Run on the lab:
  PART=mse SEQLAB=$HOME/till_infinity/data/seqlab python research/harness/clockcheck.py
  PART=env VARIANT=mc INTERVAL=15m ...
"""
from __future__ import annotations

import heapq
import math
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import spikerisk

from till_infinity.structures import rollover as ro
from till_infinity.structures import zma as zm
from till_infinity.structures.learning import touches as tc
from till_infinity.structures.vol import clock as ck
from till_infinity.structures.vol import envelope as ev
from till_infinity.structures.vol.ranges import Ranges

PART = os.environ.get("PART", "mse")
START = pd.Timestamp(os.environ.get("START", "2019-01-01"), tz="UTC").timestamp()
FAMILIES = {
    "fx": ["EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDCAD", "USDCHF", "USDJPY", "EURJPY", "GBPJPY",
           "EURGBP", "EURCHF", "AUDJPY", "CHFJPY", "EURAUD", "USDCNH"],
    "crypto": ["BTCUSD", "ETHUSD", "SOLUSD"],
    "metals": ["XAUUSD", "XAGUSD"],
    "deriv": ["Volatility_75_Index", "Boom_1000_Index", "Range_Break_100_Index"],
}
SECONDS = {"15m": 900.0, "1h": 3600.0}


def load(sym: str, interval: str, start: float) -> pd.DataFrame | None:
    try:
        df = spikerisk.load(None, sym, "SEQLAB", interval)
    except (ValueError, FileNotFoundError):
        return None
    df = df[df["ts"] >= start].reset_index(drop=True)
    return df if len(df) > 500 else None


def stream(sym: str, df: pd.DataFrame):
    """A function, so `sym` binds now (the late-binding bug)."""
    for row in zip(df["ts"], df["open"], df["high"], df["low"], df["close"], strict=True):
        yield (float(row[0]), sym, *map(float, row[1:]))


def mse() -> None:
    for fam, syms in FAMILIES.items():
        frames = {s: d for s in syms if (d := load(s, "1h", START)) is not None}
        if not frames:
            continue
        clock, ranges, rows = ck.Clock(), {s: Ranges() for s in frames}, []
        prev: dict[str, tuple[float, float]] = {}
        merged = heapq.merge(*(stream(s, d) for s, d in frames.items()))
        for t, sym, o, h, lo, c in merged:
            feed = sym.lower()
            if sym in prev:  # the forecast made at the previous close, settled by this bar
                p_close, p_sigma, mult = prev[sym]
                rows.append((t, abs(math.log(c / p_close)), p_sigma, mult))
            ranges[sym].observe(o, h, lo, c)
            sigma = ranges[sym].ewma_tr_bps / 10_000
            if not (sigma > 0):
                continue
            clock.observe(feed, "1h", t, c, sigma)
            prev[sym] = (c, sigma, clock.multiplier(feed, "1h", t + 3600, 1, 3600))
        a = np.array(rows)
        ver = a[a[:, 0] >= np.quantile(a[:, 0], 0.6)]
        mid = np.quantile(ver[:, 0], 0.5)
        out = []
        for part in (ver[ver[:, 0] < mid], ver[ver[:, 0] >= mid]):
            r, s, m = part[:, 1], part[:, 2], part[:, 3]
            c1 = np.sum(r * s) / np.sum(s * s)
            c2 = np.sum(r * s * m) / np.sum((s * m) ** 2)
            out.append(np.mean((r - c2 * s * m) ** 2) / np.mean((r - c1 * s) ** 2))
        warm = np.mean(ver[:, 3] != 1.0)
        print(f"{fam:7s} {len(frames)} series · {len(a):,} hours · clock active on {warm:.0%} of the "
              f"last 40% · relative MSE of next-hour |r|, unit x clock vs unit: "
              f"{out[0]:.3f} / {out[1]:.3f} (halves)", flush=True)


def env() -> None:
    variant = os.environ.get("VARIANT", "mc")
    interval = os.environ.get("INTERVAL", "15m")
    fams = os.environ.get("FAMS", "fx,crypto").split(",")
    ev.MONDRIAN = "m" in variant
    ck.ENABLED = "c" in variant
    seconds = SECONDS[interval]
    for fam in fams:
        frames = {s: d for s in FAMILIES[fam] if (d := load(s, interval, START)) is not None}
        if not frames:
            continue
        book, zbook, clock, tbook = ev.Book(), zm.Book(), ck.Clock(), tc.Touches()
        ranges = {s: Ranges() for s in frames}
        rec: list[tuple] = []
        for t, sym, o, h, lo, c in heapq.merge(*(stream(s, d) for s, d in frames.items())):
            feed = sym.lower()
            h, lo, c = ro.trimmed(feed, t, t + seconds, o, h, lo, c)  # as the engine trims
            ranges[sym].observe(o, h, lo, c)
            sigma = ranges[sym].ewma_tr_bps / 10_000
            if not (sigma > 0 and c > 0):
                continue
            zbook.observe(feed, interval, c)  # the engine's order: the z-score first
            bucket = int(zbook.of(feed, interval).stretched)
            clock.observe(feed, interval, t, c, sigma)
            scale = None
            if ck.family(feed) in ck.FORECAST:
                scale = {n: clock.multiplier(feed, interval, t + seconds, n, seconds)
                         for n in ev.HORIZONS}
            features = None
            if tc.applies(feed, interval) and tbook.advance(feed, interval, t, h, lo, c, sigma):
                features = tbook.base(feed, interval)
            book.observe(feed, interval, c, sigma, features, bucket=bucket, scale=scale)
            for n in ev.HORIZONS:
                key = f"{feed}|{interval}|{n}"
                b = book.chosen.get(key)
                use = book.mondrian.get(f"{key}|{b}") if b is not None else book.envelopes[key]
                if use.warm:
                    rec.append((sym, t, n, c, use.sigma, *use.quote, bucket))
        df = pd.DataFrame(rec, columns=["sym", "t", "n", "c", "unit", "q10", "q50", "q90", "zb"])
        # settle each quote against the close n bars later on its own series
        scored = []
        for (sym, n), g in df.groupby(["sym", "n"]):
            g = g.sort_values("t").reset_index(drop=True)
            closes = frames[sym].set_index("ts")["close"]
            later = closes.reindex(g["t"] + n * seconds).to_numpy()
            y = np.log(later / g["c"].to_numpy()) / g["unit"].to_numpy()
            g["y"] = y
            scored.append(g[np.isfinite(y)])
        s = pd.concat(scored)
        s = s[s["t"] >= s["t"].quantile(0.6)]
        for n, g in s.groupby("n"):
            y = g["y"].to_numpy()
            pin = sum(np.mean(np.maximum(q * (y - g[f"q{round(q * 100)}"]),
                                         (q - 1) * (y - g[f"q{round(q * 100)}"])))
                      for q in (0.1, 0.5, 0.9))
            by = " | ".join(
                f"z{b:+d} P10 {np.mean(y[m] <= gb['q10']):.1%} P90 {np.mean(y[m] <= gb['q90']):.1%}"
                f" (n {m.sum():,})"
                for b in (-1, 0, 1)
                if (m := (g["zb"] == b).to_numpy()).sum() > 100
                for gb in [g[m]])
            # pinball in log-return bps, comparable across variants whose units differ
            unit = g["unit"].to_numpy()
            pin_bps = sum(np.mean(np.maximum(q * (y - g[f"q{round(q * 100)}"]),
                                             (q - 1) * (y - g[f"q{round(q * 100)}"])) * unit) * 1e4
                          for q in (0.1, 0.5, 0.9))
            width = np.mean((g["q90"] - g["q10"]) * unit) * 1e4
            print(f"{variant:4s} {fam:6s} {interval} N={n:2d} n {len(g):,} | P10/P90 "
                  f"{np.mean(y <= g['q10']):.1%} / {np.mean(y <= g['q90']):.1%} | pinball "
                  f"{pin_bps:.2f} bps (vol units {pin:.3f}) | width {width:.1f} bps | {by}", flush=True)


if __name__ == "__main__":
    mse() if PART == "mse" else env()
