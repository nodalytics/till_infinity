"""Draw a parsed chart with every token on it: candles, EXTREMEs, VOID boxes, each BREAK's reference
line, ORIGIN bands of zones carried through their lifecycle and coloured by final state, and the
lifecycle events labelled where they happened. Under the price, v1's L1 strip: each bar's CANDLE word
(coloured by direction; size and body classes), its strength (body force, close quartile), its
BAR_RELATION, and the candle productions completed at that bar. PNGs go to research/mcfl/out/ (not
committed).

  python research/mcfl/plot.py [--source garch|walk|trend] [--seed 3] [--bars 1500] [--window 160]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.patches import Rectangle

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcfl import synth
from mcfl.core import Chart, Dir
from mcfl.parse import parse
from mcfl.candles import CODE, GCODE, REL_CODE
from mcfl.serialise import sentence, token

OUT = Path(__file__).resolve().parent / "out"
INK, MUTED, GRID = "#1f2328", "#6e7781", "#d0d7de"
UPC, DNC = "#2f6fb0", "#c2571a"  # direction: blue up, orange down (identity, not good/bad)
STATE = {"QUALIFIED": "#8c959f", "REVISITED": "#8c959f", "REJECTED": "#2f6fb0", "ACCEPTED": "#7d4cdb",
         "FAILED": "#cf222e", "EXPIRED": "#d0d7de"}


def _col(d: Dir) -> str:
    return UPC if d is Dir.UP else DNC


def draw(df: pd.DataFrame, chart: Chart, lo: int, hi: int, path: Path, title: str = "") -> Path:
    df = df.reset_index(drop=True)
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    ids = chart.by_id()
    states = dict(chart.states)
    fig, (ax, sx) = plt.subplots(2, 1, figsize=(20, 14), dpi=110, sharex=True,
                                 gridspec_kw={"height_ratios": [3.2, 1.25], "hspace": 0.03})
    ax.set_facecolor("white")
    for i in range(lo, hi):
        col = "#57606a" if c[i] >= o[i] else "#afb8c1"
        ax.plot([i, i], [l[i], h[i]], color="#57606a", lw=0.8, zorder=2)
        ax.add_patch(Rectangle((i - 0.35, min(o[i], c[i])), 0.7, max(abs(c[i] - o[i]), 1e-9),
                               facecolor=col, edgecolor="#57606a", lw=0.5, zorder=3))
    span = h[lo:hi].max() - l[lo:hi].min()
    inside = lambda e: lo <= e.at < hi  # noqa: E731

    # zones: the origin band from the origin to its terminal event (or the window's end)
    for z in chart.of("ZONE"):
        life = [e for e in chart.entities if e.get("zone") == z.id]
        end = max([e.at for e in life if e.type in ("FAIL", "ACCEPT", "EXPIRE")], default=hi)
        if not lo <= z.at < hi:  # only zones born in the window
            continue
        a, b = z.get("band")
        st = states.get(z.id, "")
        ax.add_patch(Rectangle((z.at - 0.5, a), min(end, hi) - z.at + 0.5, b - a, facecolor=STATE.get(st, GRID),
                               alpha=0.28, edgecolor=_col(z.dir), lw=1.0, zorder=1))
        ax.text(z.at, b if z.dir is Dir.UP else a, f" ORIGIN{z.dir.arrow} ZONE {st}", fontsize=7, color=INK,
                va="bottom" if z.dir is Dir.UP else "top", zorder=6)
        brk = ids[z.parts[-1]]
        ref = ids[brk.get("ref")]
        ax.plot([ref.at, brk.at], [brk.get("level")] * 2, color=_col(z.dir), lw=1.4, ls="--", zorder=4)
        for e in life:
            y = l[e.at] - 0.03 * span if z.dir is Dir.UP else h[e.at] + 0.03 * span
            if lo <= e.at < hi:
                lab = token(e, bins=True)
                ax.annotate(lab, (e.at, y), fontsize=7, color=STATE.get({"REJECT_PATH": "REJECTED", "FAIL": "FAILED",
                            "ACCEPT": "ACCEPTED", "EXPIRE": "EXPIRED"}.get(e.type, "QUALIFIED")),
                            rotation=90, ha="center", va="top" if z.dir is Dir.UP else "bottom", zorder=7)

    for e in chart.entities:
        if not inside(e):
            continue
        if e.type == "VOID":
            a, b = e.get("band")
            ax.add_patch(Rectangle((e.at - 2, a), 2.5, b - a, facecolor=_col(e.dir), alpha=0.18, lw=0, zorder=1))
        elif e.type == "EXTREME":
            y = e.get("price")
            ax.plot(e.at, y, marker="v" if e.dir is Dir.UP else "^", ms=6, color=_col(e.dir), zorder=5)
        elif e.type == "BREACH_REVERT":
            ax.plot(e.at, e.get("level"), marker="x", ms=7, color=_col(e.dir), zorder=5)

    # the sentence itself, one token per bar where it became known, stacked along the top
    stack: dict[int, int] = {}
    top = h[lo:hi].max()
    for e in sentence(chart):
        if not lo <= e.known_at < hi or e.type in ("REVISIT", "REJECT_PATH", "ACCEPT", "FAIL", "EXPIRE"):
            continue
        k = stack.get(e.known_at, 0)
        stack[e.known_at] = k + 1
        ax.text(e.known_at, top + span * (0.03 + 0.11 * k), token(e, bins=True), fontsize=6, rotation=90,
                color=_col(e.dir), ha="center", va="bottom", zorder=6)
    ax.set_xlim(lo - 1, hi)
    ax.set_ylim(l[lo:hi].min() - 0.15 * span, top + span * 0.75)
    ax.grid(color=GRID, lw=0.5)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.set_title(title or f"MCFL v1, bars {lo}-{hi}: L2/L3 events by known_at along the top; zones from origin "
                 "to terminal state; the L1 words and candle productions in the strip below",
                 color=INK, fontsize=11, loc="left")
    strip(sx, chart, lo, hi)
    handles = [Rectangle((0, 0), 1, 1, facecolor=STATE[s], alpha=0.5, label=f"zone {s.lower()}")
               for s in ("REJECTED", "ACCEPTED", "FAILED", "EXPIRED", "QUALIFIED")]
    handles += [plt.Line2D([], [], color=UPC, lw=6, alpha=0.3, label="VOID up"),
                plt.Line2D([], [], color=DNC, lw=6, alpha=0.3, label="VOID down"),
                plt.Line2D([], [], color=INK, ls="--", label="BREAK reference level"),
                plt.Line2D([], [], color=INK, marker="v", ls="", label="EXTREME high / low"),
                plt.Line2D([], [], color=INK, marker="x", ls="", label="BREACH_REVERT")]
    ax.legend(handles=handles, loc="lower left", fontsize=7, ncol=5, frameon=False)
    fig.subplots_adjust(left=0.05, right=0.99, top=0.96, bottom=0.05)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path)
    plt.close(fig)
    return path


PROD = {"PIN": "PIN", "ENGULF": "ENG", "INSIDE_BREAK": "IB", "STAR": "STAR", "DISPLACE_C": "DC",
        "DELIVERY_SHIFT": "DS", "REJECT": "REJ"}
"""Candle productions as drawn in the strip's top rows."""


def strip(sx, chart: Chart, lo: int, hi: int) -> None:
    """The L1 strip. Rows, bottom up: the relation to the previous bar (IN OUT HH LL, + for an
    engulfing body); the strength (b = body force grade, q = close quartile); the CANDLE word, a
    tile coloured by direction whose height is the size class and whose label is size/body; then
    the candle productions completed at each bar, stacked."""
    c = {e.at: e for e in chart.entities if e.type == "CANDLE"}
    r = {e.at: e for e in chart.entities if e.type == "BAR_RELATION"}
    sizes = ["NONE", "VERY_SMALL", "SMALL", "MEDIUM", "LARGE", "VERY_LARGE", "EXTREMELY_LARGE"]
    for t in range(lo, hi):
        e = c.get(t)
        if e is None:
            continue
        col = UPC if e.dir is Dir.UP else DNC if e.dir is Dir.DOWN else MUTED
        sz = e.get("size")
        frac = 0.15 + 0.85 * (sizes.index(sz) / 6 if sz in sizes else 0.0)
        sx.add_patch(Rectangle((t - 0.4, 2.05), 0.8, 0.9 * frac, facecolor=col, alpha=0.55, lw=0))
        lab = "W" if sz == "WARMUP" else f"{CODE[sz]}/{CODE[e.get('body')]}"
        sx.text(t, 3.0, lab, fontsize=5.5, rotation=90, ha="center", va="bottom", color=INK)
        sx.text(t, 1.05, f"{GCODE[e.get('force_g')]}{e.get('close_q')[1]}", fontsize=6, rotation=90,
                ha="center", va="bottom", color=col)
        if t in r:
            rel = REL_CODE[r[t].get("rel")] + ("+" if r[t].get("engulf") != "NONE" else "")
            sx.text(t, 0.05, rel, fontsize=6, rotation=90, ha="center", va="bottom", color=INK)
    stack: dict[int, int] = {}
    for e in sorted(chart.of(*PROD), key=lambda e: (e.known_at, e.type)):
        if not lo <= e.known_at < hi:
            continue
        k = stack.get(e.known_at, 0)
        stack[e.known_at] = k + 1
        sx.text(e.known_at, 3.75 + 0.62 * k, PROD[e.type] + e.dir.arrow, fontsize=6, rotation=90, ha="center",
                va="bottom", color=_col(e.dir), fontweight="bold" if e.type in ("REJECT", "DISPLACE_C") else None)
    sx.set_ylim(0, 3.75 + 0.62 * (max(stack.values(), default=1) + 0.4))
    sx.set_yticks([0.5, 1.5, 2.5, 3.9])
    sx.set_yticklabels(["relation", "force,q", "CANDLE", "productions"], fontsize=7, color=MUTED)
    for y in (1.0, 2.0, 3.7):
        sx.axhline(y, color=GRID, lw=0.6)
    sx.set_xlabel("bar", color=MUTED)
    for s_ in ("top", "right"):
        sx.spines[s_].set_visible(False)


def busiest_window(chart: Chart, width: int) -> int:
    """The window start with the most zone lifecycle events, so the picture shows the machine run."""
    ats = sorted(e.at for e in chart.entities if e.type in ("ZONE", "REVISIT", "REJECT", "REJECT_PATH", "ACCEPT",
                                                             "FAIL"))
    best, start = -1, 0
    for a in ats:
        n = sum(a <= x < a + width for x in ats)
        if n > best:
            best, start = n, max(0, a - 10)
    return start


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="garch", choices=("walk", "garch", "trend"))
    ap.add_argument("--seed", type=int, default=3)
    ap.add_argument("--bars", type=int, default=1500)
    ap.add_argument("--window", type=int, default=90)
    a = ap.parse_args()
    df = getattr(synth, a.source)(a.bars, seed=a.seed)
    ch = parse(df)
    lo = busiest_window(ch, a.window)
    p = draw(df, ch, lo, min(len(df), lo + a.window), OUT / f"chart_{a.source}_{a.seed}.png")
    print(f"written {p}")


if __name__ == "__main__":
    main()
