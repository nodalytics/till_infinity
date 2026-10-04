"""How price comes back to an aged zone, and its higher-timeframe context.

Frozen in `aged_context_rule.json` before its first run, whose SLOW / FAST cut-offs turned out to be
absolute and left SLOW nearly empty; v2 (`aged_context2_rule.json`) splits a measured speed into thirds. Reads `aged_zones.py`'s trades, rebuilds each
series (the same walks and seeds) and attaches, known at the fill: the manner of the return from the
bars before the fill bar, and the higher timeframe from its closed bars only.

  OUT=... MT5BT_DB=... CACHE=... python research/ideas/aged_context.py
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

import aged_zones as A  # noqa: E402
import turn_confirm as C  # noqa: E402
import turn_trade as TT  # noqa: E402
import turn_zones as TZ  # noqa: E402

OUT = Path(os.environ.get("OUT", ".data/aged_zones"))
NS = (0.5, 1, 2, 4, 10)


def series(venue, sym, iv, source):
    """The bars `aged_zones.one` traded, rebuilt the same way."""
    from mcfl import synth
    df, _ = C.load(venue, sym, iv)
    if df is None:
        return None
    if source != "real":
        ts, n = df["ts"].to_numpy(), len(df)
        sigma = float(np.std(np.diff(df["close"].to_numpy(float))))
        seed = zlib.crc32(f"{venue}{sym}{iv}{source}aged".encode()) % 100000
        gen = synth.walk if source == "walk" else synth.garch
        df = gen(n, sigma=sigma, seed=seed, steps=TT.WALK_STEPS).reset_index(drop=True).iloc[:n]
        df["ts"] = ts[:len(df)]
        df["volume"] = 0.0
    return df


def htf_state(frame, iv):
    """For each bar: the HTF state from HTF bars closed at or before the bar's open. 4h zones read UTC
    days, 1d zones weeks from Monday 00:00 UTC (the epoch began on a Thursday, hence the 4-day shift)."""
    ts = frame["ts"].to_numpy(np.int64)
    period = 86400 if iv == "4h" else 7 * 86400
    shift = 0 if iv == "4h" else 4 * 86400
    key = (ts - shift) // period * period + shift
    hb = frame.assign(key=key).groupby("key").agg(high=("high", "max"), low=("low", "min"), close=("close", "last"))
    end = hb.index.to_numpy() + period
    sma = hb["close"].rolling(20).mean()
    up = ((hb["close"] > sma) & (sma > sma.shift(5))).to_numpy()
    dn = ((hb["close"] < sma) & (sma < sma.shift(5))).to_numpy()
    state = np.where(up, "ALIGNED", np.where(dn, "COUNTER", "NEUTRAL"))
    mid = ((hb["low"].rolling(20).min() + hb["high"].rolling(20).max()) / 2).to_numpy()
    k = np.searchsorted(end, ts, side="right") - 1  # the last HTF bar whose end <= this bar's open
    ok = k >= 24  # 20 for the SMA, 5 more for its slope
    kk = np.clip(k, 0, None)
    return np.where(ok, state[kk], "NEUTRAL"), np.where(ok, mid[kk], np.nan)


def one(key):
    from mcfl.parse import flip
    src, sym, iv, rows = key
    venue, source = src.split(":")
    df = series(venue, sym, iv, source)
    if df is None:
        return None
    out = []
    for side in (1, -1):
        frame = df if side > 0 else flip(df)
        g = rows[rows["side"] == side]
        if not len(g):
            continue
        o, h, l, c = (frame[k].to_numpy(float) for k in ("open", "high", "low", "close"))
        a = TZ.atr(frame)
        down = TT.ups(flip(frame), both=True)  # productions of the flipped frame: moves toward a long zone
        push_bar = down["DISPLACE_C"] | down["DELIVERY_SHIFT"]
        st, mid = htf_state(frame, iv)
        low3 = pd.Series(l).rolling(3).min().to_numpy()
        for _, r in g.iterrows():
            t, f, live = int(r.t), int(r.f), int(r.live)
            top = low3[t] + TZ.WIDTH * a[t]
            s10 = max(live, f - 10)
            now = a[f - 1] if f > 0 and a[f - 1] > 0 else a[t]
            speed = (h[s10:f].max() - top) / (now * np.sqrt(f - s10)) if f > s10 else 0.0
            s0 = max(live, f - 5)
            if f <= s0:
                app5, big5, push = 0.0, 0, False
            else:
                app5 = (h[s0:f].max() - top) / a[t]
                big5 = int(((o[s0:f] - c[s0:f]) >= 0.7 * a[s0:f]).sum())
                push = bool(push_bar[s0:f].any())
            manner = ("FAST" if app5 >= 3 or big5 >= 2 or push else
                      "SLOW" if app5 < 1.5 and big5 == 0 else "MEDIUM")
            out.append(dict(r.to_dict(), app5=app5, big5=big5, push=push, manner=manner, speed=speed, htf=st[f],
                            discount=bool(np.isfinite(mid[f]) and top <= mid[f])))
    print(f"  {src} {sym} {iv}: {len(out)}", flush=True)
    return pd.DataFrame(out)


def terciles(d, by):
    """v2 (aged_context2_rule.json): SLOW / MEDIUM / FAST as the thirds of `speed`, the cut-offs from the
    real rows of each group (no outcome is used), applied to that group's walks too."""
    d = d.copy()
    d["manner2"] = "MEDIUM"
    real = d["src"].str.endswith(":real")
    for _, idx in d.groupby(by).groups.items():
        g = d.loc[idx]
        q1, q2 = g.loc[real.loc[idx], "speed"].quantile([1 / 3, 2 / 3])
        d.loc[idx[g["speed"].to_numpy() <= q1], "manner2"] = "SLOW"
        d.loc[idx[g["speed"].to_numpy() >= q2], "manner2"] = "FAST"
    return d


def score(d, rng, col="manner"):
    rows = []
    d = d.assign(manner=d[col], SLOW_ALIGNED=(d[col] == "SLOW") & (d["htf"] == "ALIGNED"))
    for src, g in d.groupby("src"):
        for fam in ("ALL", "SIG"):
            x0 = g[g[fam]] if fam == "SIG" else g
            cells = [("SLOW & ALIGNED", x0["SLOW_ALIGNED"]), ("not (SLOW & ALIGNED)", ~x0["SLOW_ALIGNED"])]
            cells += [(f"{m} | {hh}", (x0["manner"] == m) & (x0["htf"] == hh))
                      for m in ("SLOW", "MEDIUM", "FAST") for hh in ("ALIGNED", "NEUTRAL", "COUNTER")]
            cells += [(m, x0["manner"] == m) for m in ("SLOW", "MEDIUM", "FAST")]
            cells += [(hh, x0["htf"] == hh) for hh in ("ALIGNED", "NEUTRAL", "COUNTER")]
            cells += [("discount", x0["discount"]), ("premium", ~x0["discount"])]
            for wait in ("any", ">=10d"):
                for name, m in cells:
                    x = x0[m & (x0["wait_d"] >= 10)] if wait == ">=10d" else x0[m]
                    y = x.assign(R=x["E1"])
                    lo, hi = TT.boot(y, rng) if len(y) > 30 else (np.nan, np.nan)
                    rows.append(dict(src=src, family=fam, wait=wait, cell=name, n=len(y), R=y["R"].mean(), lo=lo, hi=hi,
                                     X2=x["X2"].mean(), R_before=y.loc[y["ts"] < TT.SPLIT, "R"].mean(),
                                     R_after=y.loc[y["ts"] >= TT.SPLIT, "R"].mean(),
                                     **{f"P{N}R": (x["mfe"] >= N).mean() for N in NS}))
    return pd.DataFrame(rows).round(3)


def run():
    d = pd.read_pickle(OUT / "aged_zones.pkl.gz")  # our own output, written by aged_zones.py
    d["wait_d"] = d["wait"] * d["iv"].map(TZ.SEC) / 86400
    keys = [(src, sym, iv, g) for (src, sym, iv), g in d.groupby(["src", "sym", "iv"])]
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", 8))) as pool:
        got = [g for g in pool.map(one, keys) if g is not None and len(g)]
    x = pd.concat(got, ignore_index=True)
    x["venue"] = x["src"].str.split(":").str[0]
    x = terciles(x, ["venue", "iv"])
    x.to_pickle(OUT / "aged_context2.pkl.gz")
    t = score(x, np.random.default_rng(91), col="manner2")
    t.to_csv(OUT / "aged_context2.csv", index=False)
    pd.set_option("display.width", 260)
    pd.set_option("display.max_rows", 600)
    print(t.to_string(index=False))
    print("1/(N+1):", {N: round(1 / (N + 1), 3) for N in NS})

    def cell(src, name):
        return t[(t["src"] == src) & (t["family"] == "ALL") & (t["wait"] == "any") & (t["cell"] == name)].iloc[0]
    p, rest = cell("fresh:real", "SLOW & ALIGNED"), cell("fresh:real", "not (SLOW & ALIGNED)")
    w, gw = cell("fresh:walk", "SLOW & ALIGNED"), cell("fresh:garch", "SLOW & ALIGNED")
    ok = (p["R"] > 0 and p["lo"] > 0 and p["R_before"] > 0 and p["R_after"] > 0
          and p["R"] > w["R"] and p["R"] > gw["R"] and p["R"] > rest["R"])
    print(f"\nPRIMARY (ALL, SLOW & ALIGNED, E1, fresh 4h+1d): R {p['R']:+.3f} [{p['lo']:+.3f}, {p['hi']:+.3f}] n={p['n']}, "
          f"before {p['R_before']:+.3f}, after {p['R_after']:+.3f}; walk {w['R']:+.3f}; garch {gw['R']:+.3f}; "
          f"the rest {rest['R']:+.3f} -> {'PASSES' if ok else 'fails'}")


if __name__ == "__main__":
    run()
