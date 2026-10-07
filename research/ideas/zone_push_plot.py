"""Draw what the scan marked: the impulsive candles, and the candle before them.

Written so the desk can check the code is finding what it means before anything
is concluded from the numbers. Asked for in those terms on 2026-10-07 - "can you
give me a chart of what you marked as an impulsive candles", "that is your
supply/demand zone" - so the impulse is boxed in gold, the bar before it in
black, and the band is that bar's whole range carried to its first return.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

HERE = Path(__file__).resolve().parent
for q in (HERE, HERE.parent, HERE.parents[1]):
    sys.path.insert(0, str(q))

import run as R  # noqa: E402
import zones as Z  # noqa: E402

OUT = Path(os.environ.get("OUT", ".data/zonepush"))
BEFORE, AFTER = 22, 34


def candles(ax, df, i0, i1):
    o, h, l, c = (df[k].to_numpy()[i0:i1] for k in ("open", "high", "low", "close"))
    x = np.arange(len(o))
    up = c >= o
    ax.vlines(x, l, h, color="#555", lw=0.7, zorder=2)
    ax.bar(x[up], (c - o)[up], bottom=o[up], width=0.62, color="#17a07e", zorder=3)
    ax.bar(x[~up], (o - c)[~up], bottom=c[~up], width=0.62, color="#d2544e", zorder=3)
    return x


def impulse(df, z):
    """Which bars are the impulse, re-derived rather than stored.

    `ob_zones` takes the first gap `d` in `range(OB_BACK + 1)` for which the push
    holds, so the same search here returns the same bars. Nothing is cached on
    `Zone`: a field added between two existing ones is how the 84% long skew
    happened, and this is only wanted for a picture.
    """
    frame = df if z.side > 0 else Z.flip(df)
    o, h, l, c = (frame[k].to_numpy() for k in ("open", "high", "low", "close"))
    for d in range(Z.OB_BACK + 1):
        if Z.sequential_push(o, h, l, c, z.p, 1, strong=Z.PUSH_STRONG, offset=d):
            return list(range(z.p + 1 + d, z.p + 1 + d + Z.PUSH_N))
    return []


def mirrored(z):
    """The zone as `setups` reads it on a flipped frame - by keyword, always."""
    return z if z.side > 0 else Z.Zone(
        side=1, p=z.p, lo=-z.lo, hi=-z.hi, bos=z.bos, bos_level=-z.bos_level,
        fvg=z.fvg, live=z.live, leg_extreme=-z.leg_extreme, clean=z.clean,
        push=z.push, push_hi=z.push_hi, ob=z.ob, line=-z.line, ret=z.ret, rank=z.rank)


def confirmation(df, a, z):
    """The first bar in the return window carrying the desk's confirmation: a
    pinbar, or a medium-to-long wick rejecting the zone's own side."""
    frame = df if z.side > 0 else Z.flip(df)
    hits = [t["i"] for t in Z.triggers(frame, a, mirrored(z))
            if t["trigger"] in ("pin", "wick")]
    return min(hits, default=None)


def draw(sym: str, iv: str, want: str, limit: int = 6) -> Path | None:
    df = R.load(sym, iv)
    if df is None:
        return None
    df = df.reset_index(drop=True)
    a = R.atr(df) if hasattr(R, "atr") else Z.prod_unit(df)
    found = [z for z in Z.zones(df, a) if getattr(z, want) and z.ret > 0]
    if not found:
        return None
    found = found[-limit:]
    rows = (len(found) + 1) // 2
    fig, axes = plt.subplots(rows, 2, figsize=(13, 3.4 * rows), squeeze=False)
    o_, h_, l_, c_ = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    for ax, z in zip(axes.ravel(), found):
        imp = impulse(df, z)
        i0 = max(0, z.p - BEFORE)
        i1 = min(len(df), max([z.p, z.ret] + imp) + AFTER)
        candles(ax, df, i0, i1)
        lo, hi = min(z.lo, z.hi), max(z.lo, z.hi)
        # the zone: the candle the impulse left from, carried forward to its return
        ax.add_patch(Rectangle((z.p - i0 - 0.5, lo), (z.ret - z.p) + 1.0, hi - lo,
                               facecolor="#4f86c6", alpha=0.18, edgecolor="#2a5f96",
                               lw=1.0, zorder=1))
        ax.axhline(z.line, color="#1b4f8a", lw=1.4, zorder=4)
        # **the impulsive candles**, boxed - what the scan looked for first
        for k in imp:
            if i0 <= k < i1:
                ax.add_patch(Rectangle((k - i0 - 0.46, l_[k]), 0.92, max(h_[k] - l_[k], 1e-9),
                                       facecolor="none", edgecolor="#b8860b", lw=1.5, zorder=5))
        # and the bar before them, which is the zone
        if i0 <= z.p < i1:
            ax.add_patch(Rectangle((z.p - i0 - 0.46, l_[z.p]), 0.92, max(h_[z.p] - l_[z.p], 1e-9),
                                   facecolor="none", edgecolor="#111", lw=1.6, zorder=5))
        if i0 <= z.bos < i1:
            ax.axhline(z.bos_level, color="#888", lw=0.9, ls="--", zorder=3)
        if i0 <= z.ret < i1:
            ax.axvline(z.ret - i0, color="#6a1b9a", lw=1.1, ls="--", alpha=0.9, zorder=4)
        conf = confirmation(df, a, z)
        if conf is not None and i0 <= conf < i1:
            y = l_[conf] if z.side > 0 else h_[conf]
            ax.plot([conf - i0], [y], marker="^" if z.side > 0 else "v", ms=9,
                    color="#6a1b9a", zorder=6)
        side = "demand" if z.side > 0 else "supply"
        body = abs(c_[z.p] - o_[z.p]) / max(h_[z.p] - l_[z.p], 1e-12)
        rel = (h_[z.p] - l_[z.p]) / max(h_[imp[0]] - l_[imp[0]], 1e-12) if imp else float("nan")
        ax.set_title(f"{sym} {iv}  {side}  zone bar "
                     f"{'green' if c_[z.p] >= o_[z.p] else 'red'}, body {body:.0%} of its range, "
                     f"{rel:.2f}x the impulse candle  |  line {z.line:.6g}", fontsize=8.5)
        ax.tick_params(labelsize=7)
        ax.set_xticks([])
    for ax in axes.ravel()[len(found):]:
        ax.axis("off")
    fig.suptitle(f"{sym} {iv} ({want}) - gold: the impulsive candles. Black: the candle before "
                 "them, which is the zone. Band: that candle high to low, carried to its first "
                 "return (purple dash). Dark line: the near edge of its body. Triangle: the "
                 "confirming pinbar or wick. Grey dash: the break of structure.", fontsize=9.5)
    fig.tight_layout()
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"push_{sym.replace(' ', '')}_{iv}_{want}.png"
    fig.savefig(path, dpi=118)
    plt.close(fig)
    return path


def main() -> None:
    R.DB = os.environ.get("MT5BT_DB")
    want = os.environ.get("WANT", "push_hi")
    syms = (os.environ.get("SYMBOLS") or "EURUSD,XAUUSD,BTCUSD").split(",")
    for iv in (os.environ.get("INTERVALS") or "4h").split(","):
        for sym in syms:
            got = draw(sym.strip(), iv.strip(), want)
            print(f"  {sym} {iv}: {got}", flush=True)
    print("plots done", flush=True)


if __name__ == "__main__":
    main()
