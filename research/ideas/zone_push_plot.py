"""Draw the zones the two-candle push selects, with the level inside each.

Written so the desk can check the code is finding what it means before anything
is concluded from the numbers: the origin bar, the two candles leaving it, the
zone band, and the level where the origin closed.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

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
    fig, axes = plt.subplots(rows, 2, figsize=(13, 3.2 * rows), squeeze=False)
    for ax, z in zip(axes.ravel(), found):
        i0, i1 = max(0, z.p - BEFORE), min(len(df), z.p + AFTER)
        x = candles(ax, df, i0, i1)
        p = z.p - i0
        lo, hi = (z.lo, z.hi) if z.side > 0 else (z.hi, z.lo)
        ax.axhspan(min(lo, hi), max(lo, hi), color="#4f86c6", alpha=0.17, zorder=1)
        ax.axhline(z.line, color="#1b4f8a", lw=1.5, ls="-", zorder=4)
        # the origin and the two candles that left it
        for k, colour in ((p, "#000"), (p + 1, "#b8860b"), (p + 2, "#b8860b")):
            if 0 <= k < len(x):
                ax.axvline(k, color=colour, lw=0.9, ls=":" if colour != "#000" else "-", alpha=0.8)
        if 0 <= z.ret - i0 < len(x):
            ax.axvline(z.ret - i0, color="#6a1b9a", lw=1.2, ls="--", alpha=0.9)
        side = "demand" if z.side > 0 else "supply"
        ax.set_title(f"{sym} {iv}  {side}  line {z.line:.5g}  "
                     f"{'ob' if z.ob else 'no ob'}", fontsize=9)
        ax.tick_params(labelsize=7)
        ax.set_xticks([])
    for ax in axes.ravel()[len(found):]:
        ax.axis("off")
    fig.suptitle(f"{sym} {iv} - zones with a two-candle push ({want}); "
                 "band = zone, dark line = the origin's close, dotted = the push bars, "
                 "dashed purple = first return", fontsize=10)
    fig.tight_layout()
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"push_{sym}_{iv}_{want}.png"
    fig.savefig(path, dpi=118)
    plt.close(fig)
    return path


def main() -> None:
    R.DB = os.environ.get("MT5BT_DB")
    want = os.environ.get("WANT", "push_hi")
    syms = (os.environ.get("SYMBOLS") or "EURUSD,XAUUSD,BTCUSD").split(",")
    for sym in syms:
        got = draw(sym.strip(), os.environ.get("IV", "4h"), want)
        print(f"  {sym}: {got}")
    print("plots done", flush=True)


if __name__ == "__main__":
    main()
