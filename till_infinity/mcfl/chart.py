"""A chart for each card: the last closed candles, with the pattern drawn on them.

matplotlib is an optional extra (`pip install till-infinity[chart]`), imported
lazily on the first render. Without it - or if a render fails for any reason -
the card goes out without its picture and the reason is logged once, because
an alert must never be lost for its image.

Rendering is synchronous and CPU-bound, so the service calls it through
`asyncio.to_thread`; a 1200x675 frame of 80 candles takes a few tens of
milliseconds with the Agg backend.

## What is drawn

* the last `CANDLES` closed bars of the instrument and timeframe;
* the signal candle highlighted (`Spec.highlight`), and nothing else of the
  method - no lookback, no swing, no window: a card shows what to watch, never
  how it was found (see `cards.py`);
* the reference entry and stop as dashed lines, labelled with their prices,
  against a right-hand price scale; a broken level as a plain, unlabelled line;
* the title: symbol · timeframe · signal label · side.

Dark, high-contrast and large-type, for a phone held at arm's length.
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime

import numpy as np

from ..logging import get_logger
from .tokens import Bars

log = get_logger(__name__)

#: Candles shown, and the most shown when the pattern reaches further back.
CANDLES = 80
MAX_CANDLES = 200
#: Pixels, at DPI 100.
WIDTH, HEIGHT, DPI = 12.0, 6.75, 100

BG = "#0f1419"
PANEL = "#151b23"
GRID = "#253040"
TEXT = "#e6edf3"
MUTED = "#8b949e"
UP = "#26a69a"
DOWN = "#ef5350"
MARK = "#f2cc60"
ENTRY = "#58a6ff"
STOP = "#ff7b72"
LEVEL = "#d2a8ff"

_said: set[str] = set()


@dataclass(slots=True)
class Line:
    """A horizontal level from bar `start` (window index) to the right edge."""

    price: float
    label: str
    colour: str = LEVEL
    dashed: bool = False
    start: int | None = None


@dataclass(slots=True)
class Spec:
    """What to draw. Indices are into `bars`, the full detection window."""

    bars: Bars
    title: str
    highlight: tuple[int, ...] = ()
    levels: list[Line] = field(default_factory=list)


def _once(key: str, message: str, *args) -> None:
    if key not in _said:
        _said.add(key)
        log.warning(message, *args)


def available() -> bool:
    """Whether matplotlib can be imported here."""
    try:
        import matplotlib  # noqa: F401
    except Exception:
        return False
    return True


def render(spec: Spec) -> bytes | None:
    """The chart as PNG bytes, or None (logged once) when it cannot be drawn."""
    try:
        import matplotlib

        matplotlib.use("Agg", force=False)
        from matplotlib.figure import Figure
    except Exception as exc:
        _once("import", "mcfl: charts off - matplotlib is not installed (%s)", exc)
        return None
    try:
        return _draw(Figure, spec)
    except Exception as exc:  # a picture must never cost the alert
        _once(f"draw:{type(exc).__name__}", "mcfl: chart render failed: %r", exc)
        return None


def _draw(figure_cls, spec: Spec) -> bytes:
    bars = spec.bars
    n = len(bars)
    # The last CANDLES bars, reaching further back (up to MAX_CANDLES) when the
    # pattern began earlier - a major swing can be a hundred 15m bars old, and
    # a chart that cuts off the swing it is about has not drawn the pattern.
    marks = list(spec.highlight)
    marks += [line.start for line in spec.levels if line.start is not None]
    first = max(0, min(n - CANDLES, *(i - 3 for i in marks if i >= 0)) if marks else n - CANDLES)
    first = max(first, n - MAX_CANDLES, 0)
    x = np.arange(first, n)
    o, h, lo, c = (a[first:] for a in (bars.open, bars.high, bars.low, bars.close))

    fig = figure_cls(figsize=(WIDTH, HEIGHT), dpi=DPI, facecolor=BG)
    ax = fig.add_axes((0.04, 0.09, 0.84, 0.80), facecolor=PANEL)
    up = c >= o
    colours = np.where(up, UP, DOWN)
    ax.vlines(x, lo, h, colors=colours, linewidth=1.2, zorder=2)
    body_lo, body_hi = np.minimum(o, c), np.maximum(o, c)
    tick = (h.max() - lo.min()) * 0.002
    # Bodies as thick vertical lines: one collection, an order of magnitude
    # faster to draw than eighty bar patches, and identical at this scale.
    width = max(1.5, 7.0 * CANDLES / len(x))
    ax.vlines(x, body_lo - tick, body_hi + tick, colors=colours, linewidth=width, zorder=3)

    for i in spec.highlight:
        if first <= i < n:
            ax.axvspan(i - 0.5, i + 0.5, color=MARK, alpha=0.22, zorder=1)
            ax.plot(
                [i - 0.45, i + 0.45, i + 0.45, i - 0.45, i - 0.45],
                [bars.low[i], bars.low[i], bars.high[i], bars.high[i], bars.low[i]],
                color=MARK,
                linewidth=1.6,
                zorder=4,
            )

    # Room on the right, inside the plot, for the level labels - outside it is
    # where the price scale is.
    room = max(14.0, 0.25 * len(x))
    decimals = _decimals(float(h.max() - lo.min()))
    for line in spec.levels:
        start = max(first, line.start) if line.start is not None else first
        ax.hlines(
            line.price,
            start - 0.5,
            n - 1 + room,
            colors=line.colour,
            linestyles="--" if line.dashed else "-",
            linewidth=1.6,
            zorder=5,
        )
        if not line.label:
            continue  # a plain line: where, nothing more
        ax.text(
            n + 0.5,
            line.price,
            f" {line.label} {line.price:,.{decimals}f} ",
            color=line.colour,
            fontsize=12,
            va="center",
            ha="left",
            zorder=6,
            bbox={"facecolor": PANEL, "edgecolor": "none", "pad": 1.5},
        )

    prices = [lo.min(), h.max(), *(line.price for line in spec.levels)]
    pad = (max(prices) - min(prices)) * 0.06 or abs(max(prices)) * 0.01 or 1.0
    ax.set_ylim(min(prices) - pad, max(prices) + pad)
    ax.set_xlim(first - 1, n - 1 + room)
    ax.grid(color=GRID, linewidth=0.6)
    ax.tick_params(colors=MUTED, labelsize=11)
    for side in ax.spines.values():
        side.set_color(GRID)
    ticks = x[:: max(1, len(x) // 6)]
    ax.set_xticks(ticks)
    ax.set_xticklabels([_when(int(bars.ts[i])) for i in ticks])
    ax.yaxis.tick_right()
    ax.yaxis.set_label_position("right")
    # The price scale, at the instrument's own precision: enough decimals to
    # tell the ticks apart, so entry and stop read against it.
    ax.yaxis.set_major_formatter(lambda value, _pos: f"{value:,.{decimals}f}")
    fig.text(0.04, 0.93, spec.title, color=TEXT, fontsize=19, fontweight="bold", ha="left")
    fig.text(
        0.04,
        0.025,
        "paper alert, not a trade instruction",
        color=MUTED,
        fontsize=11,
        ha="left",
    )
    out = io.BytesIO()
    # Light compression: the zlib pass was a third of the render, for a file a
    # few kilobytes smaller.
    fig.savefig(out, format="png", facecolor=BG, dpi=DPI, pil_kwargs={"compress_level": 2})
    return out.getvalue()


def _decimals(span: float) -> int:
    """Decimals that separate price ticks across `span` - about a tenth of it."""
    if not span > 0:
        return 2
    return int(min(8, max(0, -math.floor(math.log10(span / 10)) + 1)))


def _when(ts: int) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime("%m-%d %H:%M")
