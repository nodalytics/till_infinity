"""Volume profile: do its levels hold more than random prices do?

Volume profile says volume traded at a price leaves a memory there:
  POC / HVN   the price(s) where the most volume traded - "acceptance": price is drawn back and
              stalls there, and a trader like Trader Dale ("How to Trade The Absorption Setup") takes
              long/short levels from heavy-volume nodes formed inside a rejection
  LVN         thin volume - "rejection": price moves through quickly
  VAH / VAL   the edges of the 70% value area - where a return into value turns

Every UTC day, a profile is built from the previous three days (volume at typical price, bins of
half a baseline bar move), and the next day's first touch of each level is followed. Each touch is
a race from the level: does price reach one baseline move back the way it came (a bounce) before it
reaches one baseline move through (a break), within an hour? A bar reaching both counts as a
break. Also measured: how long price stays within half a move of the level over the next hour
(stickiness).

The control is placebo levels: random prices, uniform over the same three-day range, excluded
within half a move of any real level, followed exactly the same way. A random level has no memory,
so its bounce rate is what geometry alone gives.

Data: Binance USDT-M futures BTC/ETH/SOL 5m bars with real traded volume (from orderflow.py), and the
lab's broker 15m bars with tick volume for 15 FX pairs, XAU and XAG. Reported on each series' last
40% by time and both halves (nothing is fit).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import spikerisk
from fractal_twins import FAMILIES

RNG = np.random.default_rng(13)
FLOW = Path(os.environ.get("FLOW", ".data/orderflow"))
KINDS = ("POC", "HVN", "LVN", "VAH/VAL", "placebo")


def crypto(sym):
    parts = [np.load(f) for f in sorted(FLOW.glob(f"{sym}.*.npz"))]
    d = pd.DataFrame({k: np.concatenate([p[k] for p in parts]) for k in parts[0].files}).set_index("minute").sort_index()
    d = d[~d.index.duplicated()]
    g = d.groupby(d.index // 5)
    b = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
                      "close": g["close"].last(), "volume": g["buy"].sum() + g["sell"].sum()})
    b.index = pd.to_datetime(b.index * 300, unit="s", utc=True)
    return b, 12  # bars per hour


def broker(sym):
    df = spikerisk.load(None, sym, "SEQLAB", "15m")
    b = df.set_index(pd.to_datetime(df["ts"].to_numpy(), unit="s", utc=True))[["open", "high", "low", "close", "volume"]]
    return b, 4


def profile_levels(tp, vol, width):
    edges = np.arange(tp.min(), tp.max() + width, width)
    if len(edges) < 6:
        return {}
    h, _ = np.histogram(tp, bins=edges, weights=vol)
    c = 0.5 * (edges[1:] + edges[:-1])
    med = np.median(h[h > 0]) if (h > 0).any() else 0
    inner = np.arange(1, len(h) - 1)
    peak = inner[(h[inner] > h[inner - 1]) & (h[inner] >= h[inner + 1]) & (h[inner] > 1.5 * med)]
    trough = inner[(h[inner] < h[inner - 1]) & (h[inner] <= h[inner + 1]) & (h[inner] < 0.5 * med)]
    poc = int(np.argmax(h))
    # value area: grow from the POC toward the heavier side until 70% of volume
    lo = hi = poc
    tot, want = h[poc], 0.7 * h.sum()
    while tot < want and (lo > 0 or hi < len(h) - 1):
        left = h[lo - 1] if lo > 0 else -1
        right = h[hi + 1] if hi < len(h) - 1 else -1
        if right >= left:
            hi += 1
            tot += h[hi]
        else:
            lo -= 1
            tot += h[lo]
    out = {"POC": [c[poc]], "HVN": [c[i] for i in peak if i != poc], "LVN": [c[i] for i in trough],
           "VAH/VAL": [c[hi], c[lo]]}
    real = np.concatenate([np.array(v) for v in out.values()])
    lo_p, hi_p = tp.min(), tp.max()
    placebo = []
    for _ in range(200):
        x = RNG.uniform(lo_p, hi_p)
        if np.min(np.abs(real - x)) > width:
            placebo.append(x)
        if len(placebo) >= 6:
            break
    out["placebo"] = placebo
    return out


def touches(b, per_hour, test_from):
    lh, ll, lc = (np.log(b[k].to_numpy()) for k in ("high", "low", "close"))
    tp = (lh + ll + lc) / 3
    vol = b["volume"].to_numpy().astype(float)
    r = np.diff(lc, prepend=np.nan)
    sig = pd.Series(np.abs(r)).shift(1).rolling(20 * 24 * per_hour // 4, min_periods=200).mean().to_numpy()
    day = b.index.floor("1D")
    starts = np.flatnonzero(np.r_[True, day[1:] != day[:-1]])
    rows = []
    look = 3 * 24 * per_hour
    H = per_hour  # one hour
    for si, s in enumerate(starts):
        e = starts[si + 1] if si + 1 < len(starts) else len(b)
        if s < look or not np.isfinite(sig[s]) or b.index[s] < test_from:
            continue
        w = slice(s - look, s)
        width = 0.5 * sig[s]
        lv = profile_levels(tp[w], vol[w], width)
        for kind, prices in lv.items():
            for L in prices:
                prev = lc[s - 1]
                if abs(prev - L) < sig[s]:
                    continue  # already on the level at the open: no approach to follow
                side = 1.0 if prev > L else -1.0  # from above: a support test, a bounce goes up
                for i in range(s, min(e, len(b) - H - 1)):
                    if ll[i] <= L <= lh[i]:
                        up, dn = L + sig[s], L - sig[s]
                        res = 0.0
                        for j in range(i + 1, i + 1 + H):
                            hit_up, hit_dn = lh[j] >= up, ll[j] <= dn
                            if hit_up or hit_dn:
                                if hit_up and hit_dn:
                                    res = -1.0  # both in one bar: a break, conservatively
                                else:
                                    res = side * (1.0 if hit_up else -1.0)
                                break
                        stay = np.mean(np.abs(lc[i + 1:i + 1 + H] - L) <= 0.5 * sig[s])
                        rows.append(dict(kind=kind, t=b.index[i], res=res, stay=stay))
                        break
    return pd.DataFrame(rows)


def main():
    groups = {"crypto (real volume, 5m)": [(s, crypto) for s in ("BTCUSDT", "ETHUSDT", "SOLUSDT")],
              "fx (tick volume, 15m)": [(s, broker) for s in FAMILIES["fx"]],
              "metals (tick volume, 15m)": [(s, broker) for s in FAMILIES["metal"]],
              "random walks (tick volume, 15m)": [(s, broker) for s in FAMILIES["control"]]}
    print(f"\n{'=' * 110}\nVOLUME PROFILE - first touch of each level the next day; race +-1 baseline move within 1h "
          "(bounce = back the way it came); test block (last 40% by time)")
    for name, items in groups.items():
        T = []
        for sym, loader in items:
            try:
                b, ph = loader(sym)
            except (ValueError, FileNotFoundError) as exc:
                print(f"  skip {sym}: {str(exc)[:60]}")
                continue
            test_from = b.index[int(0.6 * len(b))]
            d = touches(b, ph, test_from)
            if len(d):
                d["half"] = d["t"] >= b.index[int(0.8 * len(b))]
                T.append(d)
        T = pd.concat(T)
        print(f"\n  {name}: {len(T):,} touches")
        base = T[T["kind"] == "placebo"]
        for kind in KINDS:
            k = T[T["kind"] == kind]
            if not len(k):
                continue
            decided = k[k["res"] != 0]
            bounce = np.mean(decided["res"] > 0)
            se = np.sqrt(bounce * (1 - bounce) / max(len(decided), 1))
            halves = [np.mean(decided[decided["half"] == h]["res"] > 0) for h in (False, True)]
            print(f"    {kind:<8} n={len(k):>6} bounce {bounce:.1%} +- {se:.1%} (halves {halves[0]:.1%} / {halves[1]:.1%}), "
                  f"undecided in 1h {np.mean(k['res'] == 0):.1%}, time within half a move {k['stay'].mean():.1%}")
        print(f"    (a bounce rate is only an edge relative to the placebo row; a symmetric +-1 race from a level pays "
              f"its drift and nothing else - barrier-geometry-is-irrelevant.md)")


if __name__ == "__main__":
    main()
