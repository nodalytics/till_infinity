"""What was inside that bar: a parent bar decomposed on a finer feed.

Asked for on 2026-10-11, once windows were being measured in time rather than
in bars. A 1h bar is four numbers. The 5m bars inside it are the **path** that
produced those four numbers, and the path carries things OHLC cannot say:

* **which extreme came first.** `open, high, low, close` is famously ambiguous
  about this - "up then down" and "down then up" give the same four numbers -
  and it is the single piece of information a finer feed adds for free.
* **how much travelling the net move cost.** Path length against net
  displacement is an efficiency, and a bar that went a long way to get nowhere
  is a different object from one that went straight there.
* **when and how far it went against itself** before closing where it did.

That is not a new indicator, it is the same bar read at two resolutions, and the
reason it is worth measuring now is that the machinery to line up two feeds by
**timestamp** rather than by position exists and is tested. Lining them up by
position is the cross-resolution lookahead this project has already paid for
once, at `t = +20.8` on five symbols.

## The question, and the null that makes it a question

Not "does intra-bar structure predict" - a path contains the bar, so anything
the bar predicts the path predicts too, and a correlation would prove nothing.
The question is whether the path adds anything **to what the parent bar already
says**, so every reading is also reported net of the parent's own OHLC features:
where the close sat in the range, and how wide the range was. That is a partial
rank correlation with the parent's reading taken out of both sides.

Three nulls, as everywhere here: a rotated control for the marginal, the
parent's own features for the increment, and a trailing standard deviation for
magnitude, which has beaten every volatility model tried on this desk.

## No lookahead, by construction

A parent bar opening at `t` contains the children stamped in `[t, t_next)`, and
it closes at `t_next`. Its features are therefore known at `t_next`, and the
target is measured from the parent's own close **forward**, so the earliest
thing predicted is the next parent bar.

**And the rows are stepped by the horizon, which the first run did not do.**
Parent bars do not overlap, but their *outcomes* do: at twenty-four parents
ahead, consecutive rows share twenty-three twenty-fourths of their outcome
window, and the first run's strongest cells were all at that horizon with
`high_first` taking **opposite signs on two resolutions of the same
instrument** - which is what overlap-inflated noise looks like, not an effect.

Runs on the lab.
"""

from __future__ import annotations

import bisect
import math
import os
import statistics
from pathlib import Path

HOUR = 3600.0

SYMBOLS = (
    ("eurusd", "EURUSD"),
    ("xauusd", "XAUUSD"),
    ("gbpusd", "GBPUSD"),
    ("usdjpy", "USDJPY"),
    ("v75", "Volatility_75_Index"),
)

#: `(parent, child)` feeds. Each pair is one instrument at two resolutions.
PAIRS = (("15m", "3m"), ("1h", "15m"), ("4h", "1h"))

#: Horizons in **parent bars**, which is the natural unit once the parent is
#: the object being described. One parent bar is the shortest honest horizon:
#: the features are known at its close.
AHEAD = (1, 4, 24)

#: Fewest children before a parent is decomposable. Three, because the order of
#: the extremes needs at least that to mean anything.
LEAST = 3

SHIFTS = (0.25, 0.5, 0.75)

LIMIT = int(os.environ.get("LIMIT", "40000"))


def load(stem: str, frame: str):
    import numpy as np

    path = Path(f"data/seqlab/{stem}.{frame}.npz")
    if not path.exists():
        return None
    with np.load(path) as bundle:
        keys = set(bundle.keys())
        if not {"time", "open", "high", "low", "close"} <= keys:
            return None
        order = np.argsort(bundle["time"])
        got = {k: bundle[k][order].tolist() for k in ("time", "open", "high", "low", "close")}
    if len(got["close"]) > LIMIT:
        got = {k: v[-LIMIT:] for k, v in got.items()}
    return got


def ranked(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = [0.0] * len(values)
    for rank, i in enumerate(order):
        out[i] = float(rank)
    return out


def spearman(xs: list[float], ys: list[float], shift: int = 0) -> float:
    n = len(xs)
    if n < 30:
        return float("nan")
    rotated = [xs[(i + shift) % n] for i in range(n)]
    rx, ry = ranked(rotated), ranked(ys)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den > 0 else float("nan")


def null_rho(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    got = [spearman(xs, ys, shift=max(int(n * f), 1)) for f in SHIFTS]
    usable = [v for v in got if not math.isnan(v)]
    return statistics.fmean(usable) if usable else float("nan")


def residualise(values: list[float], givens: list[list[float]]) -> list[float]:
    """Ranks of `values` with each given's ranks regressed out, one at a time.

    Sequential rather than a joint least squares, because the givens here are
    two and nearly uncorrelated and this needs no matrix inverse to be honest
    about. It removes the linear-in-ranks part of each, which is what a partial
    Spearman is.
    """
    out = ranked(values)
    for given in givens:
        rg = ranked(given)
        mg = statistics.fmean(rg)
        sgg = sum((g - mg) ** 2 for g in rg)
        if sgg <= 0:
            continue
        mo = statistics.fmean(out)
        beta = sum((o - mo) * (g - mg) for o, g in zip(out, rg, strict=True)) / sgg
        out = [o - beta * (g - mg) for o, g in zip(out, rg, strict=True)]
    return out


def partial(feature: list[float], target: list[float], givens: list[list[float]]) -> float:
    """Spearman of `feature` on `target` with `givens` taken out of the feature."""
    if len(feature) < 30:
        return float("nan")
    resid = residualise(feature, givens)
    return spearman(resid, target)


def trailing(closes: list[float], span: int) -> list[float]:
    """Standard deviation of the last `span` log returns, per parent bar."""
    steps = [0.0] + [
        math.log(closes[i] / closes[i - 1]) if closes[i] > 0 and closes[i - 1] > 0 else 0.0
        for i in range(1, len(closes))
    ]
    out = [0.0] * len(closes)
    for i in range(1, len(closes)):
        window = steps[max(i - span + 1, 1) : i + 1]
        if len(window) >= 2:
            out[i] = statistics.pstdev(window)
    return out


def inside(child: dict, start: int, stop: int, parent: dict, i: int):
    """Every reading the path adds, from the children of one parent bar.

    All of them are **scale-free** - ratios, fractions of the range, fractions
    of the bar's duration - so they are comparable across instruments without a
    volatility unit, which is the one advantage a path feature has over a level
    one.
    """
    closes = child["close"][start:stop]
    highs = child["high"][start:stop]
    lows = child["low"][start:stop]
    times = child["time"][start:stop]
    count = len(closes)
    if count < LEAST:
        return None

    span = max(parent["high"][i] - parent["low"][i], 1e-12)
    opened = parent["open"][i]
    net = parent["close"][i] - opened

    steps = [closes[k] - closes[k - 1] for k in range(1, count)]
    path = sum(abs(s) for s in steps)
    # Where the extremes were made, as a fraction through the bar. The one
    # thing OHLC cannot express.
    top = max(range(count), key=lambda k: highs[k])
    bottom = min(range(count), key=lambda k: lows[k])
    duration = max(times[-1] - times[0], 1e-9)
    high_at = (times[top] - times[0]) / duration
    low_at = (times[bottom] - times[0]) / duration

    # The worst the bar went against its own eventual direction, before it
    # closed. In units of the bar's range, so "it had to survive half its own
    # range going the wrong way" is comparable everywhere.
    adverse = (opened - min(lows)) / span if net >= 0 else (max(highs) - opened) / span

    turns = sum(
        1
        for k in range(1, len(steps))
        if steps[k] != 0.0 and steps[k - 1] != 0.0 and (steps[k] > 0) != (steps[k - 1] > 0)
    )
    realised = math.sqrt(sum(s * s for s in steps))
    middle = statistics.fmean(closes)

    return {
        # Net displacement over distance travelled: 1 is a straight line.
        "efficiency": abs(net) / path if path > 0 else 0.0,
        # +1 when the high came first: "up then down" rather than "down then up".
        "high_first": 1.0 if high_at < low_at else -1.0,
        "high_at": high_at,
        "low_at": low_at,
        "adverse": adverse,
        "turns": turns / max(len(steps) - 1, 1),
        # Realised variance inside the bar against the range it produced. Low
        # means the range was made in few large moves.
        "rv_over_range": realised / span,
        # Where the close sat relative to the path's own mean, rather than
        # relative to the range. A VWAP without volume.
        "close_vs_path": (parent["close"][i] - middle) / span,
        "children": float(count),
    }


def resolution(label: str, stem: str) -> None:
    """Is a path feature a property of the market, or of the child feed?

    **The question the portability work forces on this harness.** Path length
    grows without bound as the sampling gets finer - that is what it means for
    a price path to have a fractal dimension above one - so `efficiency` and
    `turns` cannot be invariant to the child feed in the way a range or a close
    is. If they are not, they describe the *pair* of resolutions rather than the
    market, and the (tiny) magnitude signal they carry is a statement about
    where the data came from.

    So: the same 1h parents, decomposed on 15m children and on 3m children, and
    the two readings correlated. A high rank correlation means the feature
    orders bars the same way whatever the child feed, which is the only sense in
    which it is a feature *of the bar*.
    """
    parent = load(stem, "1h")
    coarse, fine = load(stem, "15m"), load(stem, "3m")
    if parent is None or coarse is None or fine is None:
        return
    left: dict[str, list[float]] = {}
    right: dict[str, list[float]] = {}
    for i in range(len(parent["close"]) - 1):
        begin, end = parent["time"][i], parent["time"][i + 1]
        a = inside(
            coarse,
            bisect.bisect_left(coarse["time"], begin),
            bisect.bisect_left(coarse["time"], end),
            parent,
            i,
        )
        b = inside(
            fine,
            bisect.bisect_left(fine["time"], begin),
            bisect.bisect_left(fine["time"], end),
            parent,
            i,
        )
        if a is None or b is None:
            continue
        for name in a:
            left.setdefault(name, []).append(a[name])
            right.setdefault(name, []).append(b[name])
    if not left or len(next(iter(left.values()))) < 300:
        return
    count = len(next(iter(left.values())))
    print(f"  {label}: 1h parents on 15m children vs on 3m children ({count})")
    for name, values in left.items():
        rho = spearman(values, right[name])
        shift = statistics.fmean(right[name]) - statistics.fmean(values)
        print(f"    {name:<15}rho{rho:>+7.3f}   mean shift{shift:>+9.3f}")
    print()


def main() -> None:
    print("Inside the bar: a parent decomposed on a finer feed.")
    print("Features are scale-free readings of the PATH, scored three ways:")
    print("  rho      - against the next parent bars, raw")
    print("  control  - the same feature rotated, for its marginal")
    print("  net      - with the parent's OWN OHLC features and a trailing sd")
    print("             taken out. The only version that answers the question,")
    print("             since a path contains its bar.")
    print("Rows are stepped by the horizon, so no two share an outcome.\n")

    for label, stem in SYMBOLS:
        for coarse, fine in PAIRS:
            scored(label, stem, coarse, fine)

    print("## Is a path feature a property of the market or of the child feed?")
    print("Path length diverges as sampling gets finer, so `efficiency` and")
    print("`turns` cannot be invariant the way a close is. Same parents, two")
    print("child feeds, both readings correlated.\n")
    for label, stem in SYMBOLS:
        resolution(label, stem)


def scored(label: str, stem: str, coarse: str, fine: str) -> None:
    """One parent/child pair: every feature against every horizon."""
    parent, child = load(stem, coarse), load(stem, fine)
    if parent is None or child is None:
        return
    if len(parent["close"]) < 500 or len(child["close"]) < 2000:
        return

    rows: list[tuple[dict, float, float, float]] = []
    names: tuple[str, ...] = ()
    for i in range(len(parent["close"]) - 1):
        begin = parent["time"][i]
        end = parent["time"][i + 1]
        start = bisect.bisect_left(child["time"], begin)
        stop = bisect.bisect_left(child["time"], end)
        got = inside(child, start, stop, parent, i)
        if got is None:
            continue
        if not names:
            names = tuple(got)
        span = max(parent["high"][i] - parent["low"][i], 1e-12)
        # The parent's own reading, which is what the path has to beat:
        # where the close sat in the range, and how wide the range was.
        where = (parent["close"][i] - parent["low"][i]) / span
        width = span / max(parent["close"][i], 1e-12)
        rows.append((got, where, width, float(i)))
    if len(rows) < 300:
        return

    print(f"=== {label}: {coarse} bars read on {fine}, {len(rows)} parents ===")
    closes = parent["close"]
    trail = trailing(closes, 20)
    for ahead in AHEAD:
        # Step by the horizon so no two rows share an outcome window.
        usable = [
            r for k, r in enumerate(rows) if k % ahead == 0 and int(r[3]) + ahead < len(closes)
        ]
        if len(usable) < 300:
            continue
        here = [closes[int(r[3])] for r in usable]
        later = [closes[int(r[3]) + ahead] for r in usable]
        signed = [
            math.log(b / a) if a > 0 and b > 0 else 0.0 for a, b in zip(here, later, strict=True)
        ]
        size = [abs(v) for v in signed]
        # What the path has to beat: the parent's own close-in-range
        # and range, plus a trailing standard deviation over twenty
        # parents - because every magnitude reading on this desk has to
        # clear a trailing sd, and a single bar's range is a weaker
        # volatility proxy than one.
        givens = [
            [r[1] for r in usable],
            [r[2] for r in usable],
            [trail[int(r[3])] for r in usable],
        ]
        print(f"  -- {ahead} parent bar(s) ahead, n={len(usable)}")
        print(
            f"     {'feature':<14}{'dir rho':>9}{'ctrl':>8}{'net':>8}"
            f"   {'|move| rho':>11}{'ctrl':>8}{'net':>8}"
        )
        for name in names:
            if name == "children":
                continue
            feature = [r[0][name] for r in usable]
            print(
                f"     {name:<14}{spearman(feature, signed):>+9.3f}"
                f"{null_rho(feature, signed):>+8.3f}"
                f"{partial(feature, signed, givens):>+8.3f}"
                f"   {spearman(feature, size):>+11.3f}"
                f"{null_rho(feature, size):>+8.3f}"
                f"{partial(feature, size, givens):>+8.3f}"
            )
    print()


if __name__ == "__main__":
    main()
