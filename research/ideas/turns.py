"""What do turning points share? Read in MCFL v1's words, on real markets against matched walks.

Pre-registered 2026-10-03, before any run.

  turns     (labelled after the fact - used only to group bars, never as a feature)
            major turn low  a bar whose low is the lowest of the 10 bars either side, after which
                            price rallies 3 ATR before trading below it
            ordinary low    a bar whose low is the lowest of the 10 either side without that rally
            Highs are the same on the flipped chart; both are pooled in the low's terms
  features  only what MCFL knows at the turn bar's close (known_at <= t):
            the CANDLE classes of bars t, t-1, t-2 (direction, size, body, wicks, body force, close
            quartile), the BAR_RELATION of t (range relation, engulf), and each production completed
            in the 5 bars to t (PIN, ENGULF, STAR, INSIDE_BREAK, DISPLACE_C, DELIVERY_SHIFT,
            BREACH_REVERT, REJECT, VOID, BREAK)
  compare   for each feature: its rate at major turns, at ordinary lows and at all bars; the lift of
            major turns over ordinary lows (what separates a turn from a low that does not turn);
            the same on a GARCH walk matched to each series (`mcfl.synth.matched_walk`). A feature
            matters only where real markets lift it beyond what the walks do
  precision for the features that do: P(this bar is a major turn | the feature here, and the bar is a
            10-bar low so far) - knowable at t, since "lowest of the 10 bars before" is - real vs walk
  data      MT5: EURUSD, GBPUSD, USDJPY, XAUUSD, US500, NAS100, DAX, US Oil, BTCUSD, ETHUSD, on 1h
            and 4h, the full history

  OUT=... MT5BT_DB=... python research/ideas/turns.py
"""
from __future__ import annotations

import os
import sys
import zlib
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1]))

OUT = Path(os.environ.get("OUT", ".data/turns"))
W, RALLY, HORIZON, WIN = 10, 3.0, 60, 5
SYMS = ("EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "US SP 500", "US Tech 100", "Germany 40", "US Oil", "BTCUSD",
        "ETHUSD")
CLASS_COLS = ("dir", "size", "body", "upper", "lower", "force_g", "close_q")
PRODS = ("PIN", "ENGULF", "STAR", "INSIDE_BREAK", "DISPLACE_C", "DELIVERY_SHIFT", "BREACH_REVERT", "REJECT",
         "VOID", "BREAK")


def label(df: pd.DataFrame, atr: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(major turn low, ordinary low, 10-bar low so far) for each bar of this chart."""
    h, l = df["high"].to_numpy(), df["low"].to_numpy()
    n = len(l)
    lowest_c = pd.Series(l).rolling(2 * W + 1, center=True).min().to_numpy()
    lowest_b = pd.Series(l).rolling(W + 1).min().to_numpy()  # lowest of the 10 before and this one
    local = (l == lowest_c)
    so_far = (l == lowest_b)
    major = np.zeros(n, bool)
    for t in np.flatnonzero(local):
        if not atr[t] > 0:
            continue
        target = l[t] + RALLY * atr[t]
        for k in range(t + 1, min(n, t + HORIZON)):
            if l[k] < l[t]:
                break
            if h[k] >= target:
                major[t] = True
                break
    return major, local & ~major, so_far


def features(df: pd.DataFrame) -> tuple[pd.DataFrame, np.ndarray]:
    """One row a bar: the MCFL facts known at that bar's close, as booleans."""
    from mcfl import candles
    from mcfl.parse import parse
    T = candles.table(df)
    n = len(df)
    cols = {}
    for lag in (0, 1, 2):
        for c in CLASS_COLS:
            v = np.asarray(T[c], dtype=object)
            v = np.r_[np.full(lag, None, dtype=object), v[:n - lag]] if lag else v
            for val in pd.unique(v[~pd.isna(v)]):
                if val in ("WARMUP", None):
                    continue
                cols[f"c{lag}.{c}={val}"] = v == val
    for c in ("rel", "engulf"):
        v = np.asarray(T[c], dtype=object)
        for val in pd.unique(v[~pd.isna(v)]):
            cols[f"r0.{c}={val}"] = v == val
    ch = parse(df)
    done = {p: np.zeros(n, bool) for p in PRODS}
    for e in ch.entities:
        if e.type in done and 0 <= e.known_at < n:
            # which way: an UP production at a low is the low's way (a turn up)
            up = getattr(e.dir, "name", str(e.dir)).upper() in ("UP", "U")
            key = f"{e.type}{'↑' if up else '↓'}"
            done.setdefault(key, np.zeros(n, bool))[e.known_at] = True
    for key, arr in done.items():
        if key in PRODS or not arr.any():
            continue
        win = pd.Series(arr.astype(float)).rolling(WIN + 1, min_periods=1).max().to_numpy() > 0
        cols[f"w5.{key}"] = win
        cols[f"at.{key}"] = arr
    return pd.DataFrame(cols), T["atr"]


def one(job):
    import run as R
    from mcfl import synth
    from mcfl.parse import flip
    sym, iv, source = job
    R.DB = os.environ.get("MT5BT_DB")
    df = R.load(sym, iv)
    if df is None:
        return None
    df = df.reset_index(drop=True)[["ts", "open", "high", "low", "close", "volume"]]
    if source == "walk":
        df = synth.matched_walk(df, seed=zlib.crc32(f"{sym}{iv}".encode()) % 100000)
    rows = []
    for side, frame in ((1, df), (-1, flip(df))):
        F, atr = features(frame)
        major, ordinary, so_far = label(frame, np.asarray(atr, float))
        F = F.assign(major=major, ordinary=ordinary, so_far=so_far, side=side)
        rows.append(F)
    out = pd.concat(rows, ignore_index=True).fillna(False)
    print(f"  {source} {sym} {iv}: {len(out)} bars, {int(out['major'].sum())} major turns", flush=True)
    return out.assign(sym=sym, iv=iv, source=source)


def summarise(d: pd.DataFrame) -> pd.DataFrame:
    feats = [c for c in d.columns if c[:3] in ("c0.", "c1.", "c2.", "r0.", "w5.", "at.")]
    m, o, s = d["major"].to_numpy(), d["ordinary"].to_numpy(), d["so_far"].to_numpy()
    rows = []
    for f in feats:
        x = d[f].to_numpy().astype(bool)
        r_m, r_o, r_a = x[m].mean(), x[o].mean(), x.mean()
        prec = m[x & s].mean() if (x & s).sum() else np.nan
        rows.append(dict(feature=f, at_major=r_m, at_ordinary=r_o, at_all=r_a,
                         lift_vs_ordinary=r_m / r_o if r_o > 0 else np.nan, lift_vs_all=r_m / r_a if r_a > 0 else np.nan,
                         precision=prec, n_major=int(x[m].sum())))
    t = pd.DataFrame(rows)
    t["base_precision"] = m[s].mean()
    return t


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    jobs = [(s, iv, src) for src in ("real", "walk") for iv in ("1h", "4h") for s in SYMS]
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", 16))) as pool:
        got = [g for g in pool.map(one, jobs) if g is not None]
    d = pd.concat(got, ignore_index=True).fillna(False)
    tabs = {src: summarise(d[d["source"] == src]).set_index("feature") for src in ("real", "walk")}
    t = tabs["real"].join(tabs["walk"], rsuffix="_walk", how="inner")
    t["excess_lift"] = t["lift_vs_ordinary"] - t["lift_vs_ordinary_walk"]
    t["excess_precision"] = t["precision"] - t["precision_walk"]
    t = t[t["n_major"] >= 200]
    t.round(4).to_csv(OUT / "turns.csv")
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 80)
    cols = ["at_major", "at_ordinary", "lift_vs_ordinary", "lift_vs_ordinary_walk", "excess_lift", "precision",
            "precision_walk", "n_major"]
    print(f"\nbars: real {int((d['source'] == 'real').sum())}, walk {int((d['source'] == 'walk').sum())}; "
          f"major turns real {int(d.loc[d['source'] == 'real', 'major'].sum())}, walk "
          f"{int(d.loc[d['source'] == 'walk', 'major'].sum())}; base precision real "
          f"{tabs['real']['base_precision'].iloc[0]:.4f}, walk {tabs['walk']['base_precision'].iloc[0]:.4f}")
    print("\nwhat separates a major turn from an ordinary low - largest lifts on real markets:")
    print(t.sort_values("lift_vs_ordinary", ascending=False)[cols].head(25).round(3).to_string())
    print("\nreal markets beyond the walks - largest excess lift:")
    print(t.sort_values("excess_lift", ascending=False)[cols].head(25).round(3).to_string())
    print("\nand the most depleted beyond the walks:")
    print(t.sort_values("excess_lift")[cols].head(12).round(3).to_string())
    for iv in ("1h", "4h"):
        for half, m in (("first", None), ("second", None)):
            pass
    # stability: the top excess features, by timeframe and family halves
    top = t.sort_values("excess_lift", ascending=False).head(10).index
    rows = []
    for (iv, src), g in d.groupby(["iv", "source"]):
        s_ = summarise(g).set_index("feature")
        for f in top:
            if f in s_.index:
                rows.append(dict(feature=f, iv=iv, source=src, lift=s_.loc[f, "lift_vs_ordinary"],
                                 precision=s_.loc[f, "precision"]))
    print("\nthe top ten by timeframe:")
    print(pd.DataFrame(rows).pivot_table(index="feature", columns=["iv", "source"], values="lift").round(3).to_string())


if __name__ == "__main__":
    main()
