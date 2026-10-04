"""Does market structure persist? Swing labels (MCFL v2) as sentences, on real markets against walks.

Pre-registered 2026-10-03, before any run. MCFL v2 labels every confirmed 3/3 swing against the
previous one of its kind - HH / LH / EH for highs, LL / HL / EL for lows - known 3 bars after the
swing. The sequence of labels is a market's structure sentence.

  context   the last three swing labels at each swing's known_at (e.g. HL HH HL)
  next      the next high's label and the next low's label after it (persistence: an up context
            followed by HH / HL, a down context by LL / LH)
  price     from the close at the context's known_at: the move 1 and 5 days on, in ATR, and whether
            price goes 2 ATR up before 2 ATR down (within 5 days)
  compare   each context's numbers on real markets against iid walks matched to each series (256
            sub-steps a bar); on a walk swing labels are close to independent, so a real excess is
            structure that persists. Both halves of time (split 2024-01-01) and both venues
  primary   UP context (the last high HH and the last low HL) and DOWN context (LH and LL), pooled
            in the structure's terms: P(the next swing of each kind continues the structure) and
            P(2 ATR the structure's way first), real minus walk, on MT5 and on Binance
  data      MT5 (10 markets) and Binance (12 perpetuals), 1h, 4h, 1d

  OUT=... MT5BT_DB=... MODE=run|plot python research/ideas/structure_seq.py
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

OUT = Path(os.environ.get("OUT", ".data/structure_seq"))
TFS = ("1h", "4h", "1d")
SEC = {"1h": 3600, "4h": 14400, "1d": 86400}
SPLIT = pd.Timestamp("2024-01-01", tz="UTC").timestamp()
WALK_STEPS = 256


def swings(df):
    from mcfl.parse import parse
    ch = parse(df)
    s = [e for e in ch.entities if e.type == "SWING"]
    s.sort(key=lambda e: (e.known_at, e.at))
    return [(e.known_at, e.at, dict(e.attrs)["label"], getattr(e.dir, "name", str(e.dir))) for e in s]


def atr(df, n=14):
    h, l, c = (df[k].to_numpy(float) for k in ("high", "low", "close"))
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h, pc) - np.minimum(l, pc)
    return pd.Series(tr).ewm(alpha=1 / n, adjust=False).mean().to_numpy()


def rows_for(df, tf):
    h, l, c = (df[k].to_numpy(float) for k in ("high", "low", "close"))
    ts = df["ts"].to_numpy()
    a = atr(df)
    n = len(df)
    sw = swings(df)
    labels = [x[2] for x in sw]
    day = max(1, int(86400 / SEC[tf]))
    out = []
    for i in range(2, len(sw)):
        k = sw[i][0]
        if k >= n - 1 or not a[k] > 0:
            continue
        ctx = " ".join(labels[i - 2:i + 1])
        last_high = next((x[2] for x in reversed(sw[:i + 1]) if x[3] == "UP"), None)
        last_low = next((x[2] for x in reversed(sw[:i + 1]) if x[3] == "DOWN"), None)
        state = "UP" if (last_high == "HH" and last_low == "HL") else ("DOWN" if (last_high == "LH" and last_low == "LL") else "MIXED")
        nxt_high = next((x[2] for x in sw[i + 1:] if x[3] == "UP"), None)
        nxt_low = next((x[2] for x in sw[i + 1:] if x[3] == "DOWN"), None)
        m1 = (c[min(n - 1, k + day)] - c[k]) / a[k]
        m5 = (c[min(n - 1, k + 5 * day)] - c[k]) / a[k]
        up_first = np.nan
        for j in range(k + 1, min(n, k + 5 * day)):
            hit_u, hit_d = h[j] >= c[k] + 2 * a[k], l[j] <= c[k] - 2 * a[k]
            if hit_u or hit_d:
                up_first = np.nan if (hit_u and hit_d) else float(hit_u)
                break
        out.append(dict(ts=int(ts[k]), ctx=ctx, state=state, last=labels[i], next_high=nxt_high, next_low=nxt_low,
                        m1=m1, m5=m5, up_first=up_first))
    return out


def one(job):
    from mcfl import synth
    import violence as V
    venue, sym, tf, source = job
    try:
        df = V.load(venue, sym, tf)
    except OSError:
        return None
    if df is None or len(df) < 300:
        return None
    if source == "walk":
        ts = df["ts"].to_numpy()
        df = synth.matched_walk(df, seed=zlib.crc32(f"s{venue}{sym}{tf}".encode()) % 100000, steps=WALK_STEPS)
        df = df.reset_index(drop=True)
        df["ts"] = ts[:len(df)]
    r = pd.DataFrame(rows_for(df, tf))
    print(f"  {venue} {source} {sym} {tf}: {len(r)} swings", flush=True)
    return r.assign(venue=venue, sym=sym, tf=tf, source=source)


def persistence(g):
    """In the structure's own terms: an UP state continues with HH / HL, a DOWN state with LL / LH."""
    up, dn = g[g["state"] == "UP"], g[g["state"] == "DOWN"]
    cont_high = pd.concat([(up["next_high"] == "HH"), (dn["next_low"] == "LL")]).mean()
    cont_low = pd.concat([(up["next_low"] == "HL"), (dn["next_high"] == "LH")]).mean()
    way = pd.concat([up["up_first"], 1 - dn["up_first"]]).mean()
    move = pd.concat([up["m5"], -dn["m5"]]).mean()
    return pd.Series(dict(n=len(up) + len(dn), continue_extreme=cont_high, continue_pullback=cont_low,
                          two_atr_structure_way=way, move5d_atr=move))


def run():
    import violence as V
    OUT.mkdir(parents=True, exist_ok=True)
    jobs = [("mt5", s, tf, src) for src in ("real", "walk") for tf in TFS for s in V.MT5] + \
           [("binance", s, tf, src) for src in ("real", "walk") for tf in TFS for s in V.COINS]
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", 24))) as pool:
        got = [g for g in pool.map(one, jobs) if g is not None and len(g)]
    d = pd.concat(got, ignore_index=True)
    d.to_pickle(OUT / "structure.pkl.gz")  # this study's own output
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 200)
    d["half"] = np.where(d["ts"] < SPLIT, "before 2024", "2024 on")
    prim = d.groupby(["venue", "tf", "source"]).apply(persistence).round(3)
    print("primary - structure continuation (UP and DOWN states pooled in their own terms):")
    print(prim.to_string())
    halves = d.groupby(["venue", "half", "source"]).apply(persistence).round(3)
    print("\nby half:")
    print(halves.to_string())
    prim.to_csv(OUT / "persistence.csv")
    # every context: P(next high HH), P(next low HL), P(2 ATR up first), real vs walk, pooled venues and tfs
    ctx = d.groupby(["ctx", "source"]).agg(n=("ctx", "size"), p_next_HH=("next_high", lambda x: (x == "HH").mean()),
                                           p_next_HL=("next_low", lambda x: (x == "HL").mean()),
                                           p_up_first=("up_first", "mean"), m5=("m5", "mean")).unstack("source")
    ctx = ctx[ctx[("n", "real")] >= 300]
    ctx[("excess", "up_first")] = ctx[("p_up_first", "real")] - ctx[("p_up_first", "walk")]
    ctx.round(3).to_csv(OUT / "contexts.csv")
    print("\ncontexts (pooled), sorted by real-minus-walk P(2 ATR up first):")
    print(ctx.sort_values(("excess", "up_first"), ascending=False).round(3).to_string())


def plot():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import violence as V
    d = pd.read_pickle(OUT / "structure.pkl.gz")
    # 1 persistence bars
    rows = []
    for (venue, tf, source), g in d.groupby(["venue", "tf", "source"]):
        p = persistence(g)
        rows.append(dict(venue=venue, tf=tf, source=source, **p))
    p = pd.DataFrame(rows)
    fig, axes = plt.subplots(1, 3, figsize=(18, 5))
    for ax, col, title in zip(axes, ("continue_extreme", "continue_pullback", "two_atr_structure_way"),
                              ("next extreme continues (HH in up / LL in down)", "next pullback holds (HL / LH)",
                               "2 ATR the structure's way first"), strict=True):
        lab, real, walk = [], [], []
        for (venue, tf), g in p.groupby(["venue", "tf"]):
            lab.append(f"{venue}\n{tf}")
            real.append(g.loc[g["source"] == "real", col].mean())
            walk.append(g.loc[g["source"] == "walk", col].mean())
        x = np.arange(len(lab))
        ax.bar(x - 0.2, real, 0.4, label="real", color="#1d3557")
        ax.bar(x + 0.2, walk, 0.4, label="walk", color="#a8dadc")
        ax.set_xticks(x)
        ax.set_xticklabels(lab, fontsize=8)
        ax.axhline(0.5, color="#999", lw=0.8, ls=":")
        ax.set_title(title, fontsize=10)
        ax.set_ylim(0.3, 0.75)
    axes[0].legend()
    fig.suptitle("does structure persist? in an UP state (last high HH, last low HL) or DOWN state, real markets vs matched walks",
                 fontsize=11)
    fig.tight_layout()
    fig.savefig(OUT / "structure_persistence.png", dpi=80)
    plt.close(fig)
    # 2 structure sentences on charts
    from mcfl.parse import parse
    fig, axes = plt.subplots(3, 1, figsize=(20, 15))
    for ax, (venue, sym, tf) in zip(axes, (("mt5", "XAUUSD", "4h"), ("mt5", "EURUSD", "1h"), ("binance", "BTC", "4h")),
                                    strict=True):
        df = V.load(venue, sym, tf).iloc[-260:].reset_index(drop=True)
        ch = parse(df)
        st = [e for e in ch.entities if e.type == "SWING"]
        sh = sorted([e for e in ch.entities if e.type == "STRUCTURE_SHIFT"], key=lambda e: e.known_at)
        x = np.arange(len(df))
        up = (df["close"] >= df["open"]).to_numpy()
        ax.vlines(x, df["low"], df["high"], color="#555", lw=0.6)
        ax.bar(x[up], (df["close"] - df["open"])[up], bottom=df["open"][up], color="#2a9d8f", width=0.7)
        ax.bar(x[~up], (df["close"] - df["open"])[~up], bottom=df["open"][~up], color="#e76f51", width=0.7)
        colour = {"UP": "#2a9d8f", "DOWN": "#e76f51", "MIXED": "#bbbbbb"}
        prev, state = 0, "MIXED"
        for e in sh:
            ax.axvspan(prev, e.known_at, color=colour[state], alpha=0.08)
            prev, state = e.known_at, dict(e.attrs)["to"]
        ax.axvspan(prev, len(df) - 1, color=colour[state], alpha=0.08)
        for e in st:
            a_ = dict(e.attrs)
            is_up = getattr(e.dir, "name", str(e.dir)) == "UP"
            y = df["high"].iat[e.at] if is_up else df["low"].iat[e.at]
            ax.annotate(a_["label"], (e.at, y), xytext=(0, 8 if is_up else -14), textcoords="offset points", ha="center",
                        fontsize=8, color="#1d3557" if a_["label"] in ("HH", "HL") else "#9d0208")
        sentence = " ".join(dict(e.attrs)["label"] for e in sorted(st, key=lambda e: e.at))
        ax.set_title(f"{sym} {tf} - structure sentence: {sentence[-160:]}", fontsize=9)
    fig.suptitle("MCFL v2 swing labels and the STRUCTURE state (shading: green UP, red DOWN, grey MIXED)", fontsize=12)
    fig.tight_layout()
    fig.savefig(OUT / "structure_sentences.png", dpi=75)
    plt.close(fig)
    print("plots written", flush=True)


def main():
    {"run": run, "plot": plot}[os.environ.get("MODE", "run")]()


if __name__ == "__main__":
    main()
