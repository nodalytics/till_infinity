"""Is bar-to-bar overlap a dispersion feature, or is it the range again?

The candlestick order-flow reading says one-sided pressure shows as
**consecutive bars with little overlap and closes near their extremes**. Every
per-bar version of that is already closed here - engulfing is the opposite
shape to a displacement origin (best vs-walk z +1.95 over 516 rows), wick
absorption at a level does no better than fading any spike, and the published
sign-entropy version turned out to be a **folded up-rate**, provably
order-blind at zero spread across 200 within-window permutations.

The *sequence* version is a different object and has not been measured. It is
tested here as a **dispersion** feature, because direction is closed and the
range is where this desk's information has repeatedly turned out to live.

## The trap this harness exists to avoid

Overlap is **mechanically tied to the range**, which is the target. A wide bar
overlaps more of a narrow neighbour whatever the order of either, so an overlap
statistic normalised by range is partly a restatement of recent ranges - and
recent log variance is exactly what the 48-lag baseline already holds.

So the question is never "does overlap predict forward log variance". It is
whether overlap adds anything **beyond 48 lags of log variance**, and whether
whatever it adds **survives a bar shuffle**. `_rebuilt` moves whole bars, so
each bar keeps its own geometry and only the ordering dies: a feature whose
increment is the same there was measuring the bar's shape, not the sequence.

## Four statistics, all order-sensitive and all sign-free

* `overlap` - the share of this bar's range that intersects the previous
  bar's, and its mean over the lag window. Low means displacement;
* `displaced` - how many bars in the window overlapped less than `THIN`, which
  is the run-structure version rather than an average;
* `run` - the current unbroken run of thin-overlap bars, logged. This is the
  "little overlap, several bars in a row" reading stated literally;
* `edges` - the share of the window where **consecutive** closes both landed
  in the same outer third of their bars. Sign-free by construction: both at
  the top and both at the bottom count, so it cannot smuggle direction in.

Scored exactly as `changepoint-increment.md` scored BOCPD's readings - the
out-of-sample R2 each adds to `lin48` on forward log variance at h=1 and h=20,
median across instruments - so the numbers are directly comparable to the
+0.2253 that the inferred predictive sd earned and the -0.0119 to -0.0374 that
the entropies did.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
for q in (HERE, HERE.parent, HERE.parents[1]):
    sys.path.insert(0, str(q))

from cusum_regime import _blocks, _fit, _rebuilt  # noqa: E402
from dispersion_changepoint import _lags  # noqa: E402
from dispersion_ml import LIMIT, SIZE, _design, parkinson  # noqa: E402
from pattern_fingerprint import CACHE, classify, load  # noqa: E402

FRAMES = ("1h",)
TRADED = ("fx_major", "fx_cross", "metal")
CONTROLS = ("volatility",)
PER_CLASS = 3
HORIZONS = (1, 20)
SEED = 20261026

#: Overlap below which a bar counts as displaced from its predecessor.
THIN = 0.25
#: Window for every windowed statistic, matched to the lag count so no arm
#: sees more history than the baseline it is added to.
WINDOW = SIZE
#: Share of the range at each end that counts as "closed at the extreme".
EDGE = 1.0 / 3.0

#: Published cells the baseline must reproduce before any arm is read.
#: `changepoint-increment.md`, 1h, median across instruments.
KNOWN = {("fx_cross", 20): 0.15, ("fx_major", 1): 0.05}


def _overlap(bars: dict) -> np.ndarray:
    """Share of each bar's range that intersects the previous bar's."""
    high, low = bars["high"], bars["low"]
    out = np.full(len(high), np.nan)
    span = high - low
    shared = np.minimum(high[1:], high[:-1]) - np.maximum(low[1:], low[:-1])
    out[1:] = np.maximum(shared, 0.0) / np.maximum(span[1:], 1e-300)
    return np.clip(out, 0.0, 1.0)


def _columns(bars: dict) -> dict[str, np.ndarray]:
    """The four statistics, each known at its own bar's close."""
    overlap = _overlap(bars)
    high, low, close = bars["high"], bars["low"], bars["close"]
    span = np.maximum(high - low, 1e-300)
    where = (close - low) / span

    rows = len(overlap)
    mean_overlap = np.full(rows, np.nan)
    displaced = np.full(rows, np.nan)
    run = np.full(rows, np.nan)
    edges = np.full(rows, np.nan)

    thin = overlap < THIN
    top, bottom = where > 1.0 - EDGE, where < EDGE
    # Consecutive closes in the *same* outer third. Sign-free: a pair at the
    # top and a pair at the bottom both count, so direction cannot enter.
    paired = np.zeros(rows, dtype=bool)
    paired[1:] = (top[1:] & top[:-1]) | (bottom[1:] & bottom[:-1])

    streak = 0.0
    for i in range(rows):
        streak = streak + 1.0 if (i > 0 and thin[i]) else 0.0
        run[i] = np.log1p(streak)
        if i >= WINDOW:
            block = slice(i - WINDOW + 1, i + 1)
            mean_overlap[i] = float(np.nanmean(overlap[block]))
            displaced[i] = float(np.nansum(thin[block]))
            edges[i] = float(np.mean(paired[block]))
    return {"overlap": mean_overlap, "displaced": displaced, "run": run, "edges": edges}


def score(bars: dict) -> dict[tuple[int, str], float]:
    """Every arm at every horizon for one instrument, on identical rows."""
    bars = {k: v[-LIMIT:] for k, v in bars.items()}
    logvar = parkinson(bars["high"], bars["low"])
    if len(logvar) < 600 + SIZE:
        return {}
    made = _columns(bars)

    out: dict[tuple[int, str], float] = {}
    for horizon in HORIZONS:
        _, y, start = _design(logvar, horizon)
        if len(y) < 600:
            continue
        skip = max(0, SIZE - 1 - start)
        y = y[skip:]
        first = start + skip
        cut = len(y) // 2
        base = float(y[:cut].mean())
        rows = slice(first, first + len(y))
        design = _lags(logvar, first, len(y))
        out[(horizon, "lin48")] = _fit(design, y, cut, base)
        for name, series in made.items():
            column = np.asarray(series[rows], dtype=float).reshape(-1, 1)
            if not np.isfinite(column).all():
                column = np.nan_to_num(column, nan=float(np.nanmedian(column)))
            out[(horizon, name)] = _fit(np.hstack([design, column]), y, cut, base)
        # All four together, because the reading is a conjunction - "little
        # overlap AND closes at the extremes" - not any one of them.
        wide = np.hstack(
            [design]
            + [
                np.nan_to_num(
                    np.asarray(made[n][rows], dtype=float).reshape(-1, 1),
                    nan=float(np.nanmedian(made[n][rows])),
                )
                for n in ("overlap", "displaced", "run", "edges")
            ]
        )
        out[(horizon, "all four")] = _fit(wide, y, cut, base)
    return out


def main() -> None:
    rng = np.random.default_rng(SEED)
    print(
        "Is bar-to-bar overlap a dispersion feature, or the range again?\n"
        "Increments to a 48-lag ridge on forward log variance, median across\n"
        "instruments, fitted on each series' first half. Directly comparable to\n"
        "the +0.2253 the inferred predictive sd earned and the -0.0119 to -0.0374\n"
        "the entropies did. The shuffled arm moves whole bars, so each keeps its\n"
        "own geometry and only the ordering dies - an increment that survives\n"
        "there was measuring the bar's shape rather than the sequence.\n",
        flush=True,
    )
    groups: dict[str, list[str]] = {}
    for path in sorted(CACHE.glob("*.1h.npz")):
        name = path.name[: -len(".1h.npz")]
        groups.setdefault(classify(name), []).append(name)
    wanted = {k: v[:PER_CLASS] for k, v in groups.items() if k in TRADED + CONTROLS}
    print("classes:", ", ".join(f"{k} ({len(v)})" for k, v in sorted(wanted.items())), flush=True)

    for frame in FRAMES:
        per_class: dict[str, list[dict]] = {}
        for klass, names in sorted(wanted.items()):
            for name in names:
                bars = load(name, frame)
                if bars is None:
                    continue
                got = score(bars)
                if got:
                    per_class.setdefault(klass, []).append(got)
                order = _blocks(len(bars["close"]), rng)
                shuffled = score(_rebuilt(bars, order))
                if shuffled:
                    per_class.setdefault(f"{klass}.shuffled", []).append(shuffled)

        for horizon in HORIZONS:
            print(f"\n=== {frame}, h={horizon}: R2 of lin48, then each arm's increment")
            classes = sorted(per_class)
            print(f"{'arm':>12}" + "".join(f"{k:>20}" for k in classes))
            floors = {}
            for klass in classes:
                values = [
                    g[(horizon, "lin48")] for g in per_class[klass] if (horizon, "lin48") in g
                ]
                floors[klass] = float(np.median(values)) if values else float("nan")
            print(f"{'lin48':>12}" + "".join(f"{floors[k]:>20.4f}" for k in classes))
            for name in ("overlap", "displaced", "run", "edges", "all four"):
                row = f"{name:>12}"
                for klass in classes:
                    values = [
                        g[(horizon, name)] - g[(horizon, "lin48")]
                        for g in per_class[klass]
                        if (horizon, name) in g
                    ]
                    row += f"{float(np.median(values)):>+20.4f}" if values else f"{'-':>20}"
                print(row, flush=True)
            for (klass, want), floor in ((k, v) for (k, h), v in KNOWN.items() if h == horizon):
                got = floors.get(klass, float("nan"))
                if got < floor:
                    print(f"  WARN {klass} h={horizon} lin48 {got:.4f} below the published {floor}")
    print(
        "\n\nRead each traded column against its `.shuffled` neighbour. An increment\n"
        "that appears in both was the bar's own shape, which the baseline already\n"
        "holds as recent log variance; one that appears only in the real column is\n"
        "the ordering, which is the thing the candlestick reading actually claims.\n"
        "The constant-sigma family is the arm where there is no clustering to find.",
        flush=True,
    )


if __name__ == "__main__":
    main()
