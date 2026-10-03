"""Draw a parsed chart with every token on it: candles, EXTREMEs, VOID boxes, each BREAK's reference
line, ORIGIN bands of zones carried through their lifecycle and coloured by final state, and the
lifecycle events labelled where they happened. PNGs go to research/mcfl/out/ (not committed).

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
    fig, ax = plt.subplots(figsize=(20, 11), dpi=110)
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
                ax.annotate(lab, (e.at, y), fontsize=7, color=STATE.get({"REJECT": "REJECTED", "FAIL": "FAILED",
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
        if not lo <= e.known_at < hi or e.type in ("REVISIT", "REJECT", "ACCEPT", "FAIL", "EXPIRE"):
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
    ax.set_xlabel("bar", color=MUTED)
    ax.set_title(title or f"MCFL v0, bars {lo}-{hi}: tokens by known_at along the top; "
                 "zones from origin to terminal state", color=INK, fontsize=11, loc="left")
    handles = [Rectangle((0, 0), 1, 1, facecolor=STATE[s], alpha=0.5, label=f"zone {s.lower()}")
               for s in ("REJECTED", "ACCEPTED", "FAILED", "EXPIRED", "QUALIFIED")]
    handles += [plt.Line2D([], [], color=UPC, lw=6, alpha=0.3, label="VOID up"),
                plt.Line2D([], [], color=DNC, lw=6, alpha=0.3, label="VOID down"),
                plt.Line2D([], [], color=INK, ls="--", label="BREAK reference level"),
                plt.Line2D([], [], color=INK, marker="v", ls="", label="EXTREME high / low"),
                plt.Line2D([], [], color=INK, marker="x", ls="", label="BREACH_REVERT")]
    ax.legend(handles=handles, loc="lower left", fontsize=7, ncol=5, frameon=False)
    fig.subplots_adjust(left=0.05, right=0.99, top=0.95, bottom=0.06)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path)
    plt.close(fig)
    return path


def busiest_window(chart: Chart, width: int) -> int:
    """The window start with the most zone lifecycle events, so the picture shows the machine run."""
    ats = sorted(e.at for e in chart.entities if e.type in ("ZONE", "REVISIT", "REJECT", "ACCEPT", "FAIL"))
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
