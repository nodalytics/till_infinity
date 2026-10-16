"""The one-candle push: is the displacement origin worth anything at run=1?

Asked on 2026-10-16 - "test 1 candle push and different params for 1 candle
push", and then "it is similar but not the same" about engulfings, which is
exactly right and is measured here rather than argued.

## Why this is not the sweep `fade-to-origin.md` says not to do

That file closed the structure at the shipped parameters - `PUSH_N, PUSH_BODY
= 2, 0.65` - from all three directions: traded from the zone (-0.147R over
721), traded toward it (0 of 60 cells positive), and used as a filter on the
origins `fade-to-value` already trades (the gap reverses sign on the largest
sample). Its verdict is that this is "a property of the market rather than a
parameter that was missed".

The one-candle push is a **different population**, not a finer grid on that
one. The same file measured that only **5.3%** of production origins were left
by a two-candle 70%-body displacement, so the shipped definition barely
overlaps the thing the desk actually trades. Dropping `run` to 1 loosens it by
construction, and whether that trades the same way is not implied by the N=2
result either way.

## The null is not optional, because the headline number is geometry

`origin-return-rates.md` has the origin returning 77-82% of the time, and a
**distance-matched placebo matches it on every class** - a random level the
same distance away in volatility units returns about as often, and a plain walk
reads 0.825. So a return rate is reported here only beside its placebo, and the
only number worth reading is the difference. Every arm runs on the same bars
through the same detector, which is the discipline `null-structure-claims` asks
for.

The generated classes carry the real weight. Deriv's volatility and jump
indices are real markets with a known generator and no auction, so a shape that
reads the same on them as on FX is a shape with no structure behind it.

## What is reused and what is reimplemented

`pushed` is imported from `structures/drawing/displacement.py` - the shipped
predicate, not a copy - and `engulfing` from `trading/candles.py`. The filter
around `pushed` (the origin's body band, the leg in volatility units) is
reimplemented here only because `displacements` takes one `Volatility` for the
whole series, which would scale a 40,000-bar history by its last bar's
volatility. `agrees` asserts the reimplementation matches `displacements`
row-for-row on a window where a single volatility is the right one, because a
harness that quietly reimplements its subject is measuring itself.

  python research/ideas/one_push.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
for q in (HERE, HERE.parent, HERE.parents[1]):
    sys.path.insert(0, str(q))

from pattern_fingerprint import (  # noqa: E402
    CACHE,
    classify,
    load,
)

from till_infinity.structures.drawing.displacement import (  # noqa: E402
    ORIGIN_BODY_MAX,
    ORIGIN_BODY_MIN,
    displacements,
    pushed,
)
from till_infinity.structures.vol.volatility import (  # noqa: E402
    HALF_LIFE,
    MIN_VOL_BPS,
    Volatility,
)
from till_infinity.trading.candles import Bar, engulfing  # noqa: E402

FRAME = "1h"
#: The horizon `origin-return-rates.md` measured the return rate over.
HORIZON = 100
SEED = 20261016
#: Instruments per class. Twelve rather than twenty because the grid is 24
#: cells wide and every cell reads every instrument.
PER_CLASS = 12
#: Placebo levels drawn per real origin. The placebo is the whole measurement,
#: so it gets more samples than the thing it is nulling.
PLACEBOS = 4
#: Fewest origins a cell needs before its edge is printed at all.
LEAST = 200

TRADED = ("fx_major", "fx_cross", "metal", "index", "energy", "soft", "basket")
GENERATED = ("volatility", "step", "boom", "jump")

#: The grid. `run=2` at `body=0.65` and `leg=1.5` is the shipped definition and
#: is carried through every table as the row the new ones have to beat.
RUNS = (1, 2)
BODIES = (0.50, 0.65, 0.80)
LEGS = (0.5, 1.0, 1.5, 2.5)
#: Swept separately, at the best body and leg, so the grid stays 24 cells.
BANDS = ((ORIGIN_BODY_MIN, ORIGIN_BODY_MAX), (0.0, 1.0), (0.10, 0.35), (0.35, 0.60))
#: Planted-magnet strengths for the power section, in volatility units a bar.
PLANTED = (0.0, 0.01, 0.025, 0.05, 0.10)


def vol_bps(bars: dict[str, np.ndarray]) -> np.ndarray:
    """Per-bar volatility in basis points, the mean-absolute convention.

    `Volatility` tracks an exponentially weighted mean *absolute* return rather
    than a standard deviation, floored at `MIN_VOL_BPS`, and this is that with
    the same half-life. It is the harness's own and not the live estimator -
    fidelity is not what matters, because the real and placebo arms are scaled
    by the identical array, so any error in it cancels in the difference.
    """
    closes = bars["close"]
    moves = np.zeros(len(closes))
    moves[1:] = np.abs(np.diff(closes)) / closes[:-1] * 10_000.0
    alpha = 1.0 - 2.0 ** (-1.0 / HALF_LIFE)
    out = np.empty(len(closes))
    running = 0.0
    for i, move in enumerate(moves):
        running = running + alpha * (move - running) if i else move
        out[i] = running
    return np.maximum(out, MIN_VOL_BPS)


def found(
    bars: dict[str, np.ndarray],
    vols: np.ndarray,
    *,
    run: int,
    body: float,
    leg: float,
    band: tuple[float, float],
) -> dict[str, np.ndarray]:
    """Every one-sided push origin, with the leg scaled by its own bar's vol."""
    opens, highs = bars["open"], bars["high"]
    lows, closes = bars["low"], bars["close"]
    n = len(closes)
    index, line, up, legs = [], [], [], []
    for i in range(n - run):
        side = pushed(opens, highs, lows, closes, i + 1, run, body)
        if side == 0:
            continue
        span = highs[i] - lows[i]
        if span <= 0:
            continue
        bottom = min(opens[i], closes[i])
        top = max(opens[i], closes[i])
        share = (top - bottom) / span
        if not band[0] <= share <= band[1]:
            continue
        edge = bottom if side > 0 else top
        if edge <= 0:
            continue
        end = i + run
        reach = highs[end] if side > 0 else lows[end]
        # The leg at the origin's own bar, which is the whole reason this is
        # not a call into `displacements`.
        carried = abs(reach - edge) / edge * 10_000.0 / vols[i]
        if carried < leg:
            continue
        index.append(i)
        line.append(edge)
        up.append(side > 0)
        legs.append(carried)
    return {
        "index": np.array(index, dtype=int),
        "line": np.array(line, dtype=float),
        "up": np.array(up, dtype=bool),
        "leg": np.array(legs, dtype=float),
        "confirmed": np.array(index, dtype=int) + run,
    }


def agrees(bars: dict[str, np.ndarray]) -> None:
    """Assert this filter is the shipped one where a single volatility is right.

    `displacements` scales every leg by one `Volatility`, so the two agree only
    on a window short enough for that to be true. A 600-bar tail is that
    window, and the vol array is pinned to its last value across it.
    """
    tail = {k: v[-600:].copy() for k, v in bars.items()}
    live = Volatility()
    for price in tail["close"]:
        live.update(float(price))
    pinned = np.full(len(tail["close"]), live.bps)
    for run in RUNS:
        mine = found(tail, pinned, run=run, body=0.65, leg=1.5,
                     band=(ORIGIN_BODY_MIN, ORIGIN_BODY_MAX))
        theirs = displacements(
            tail["open"], tail["high"], tail["low"], tail["close"], live,
            body=0.65, run=run, minimum_vol=1.5,
            origin_body=(ORIGIN_BODY_MIN, ORIGIN_BODY_MAX), keep=10**9,
        )
        got = np.array([d.index for d in theirs], dtype=int)
        assert np.array_equal(mine["index"], got), (
            f"run={run}: {len(mine['index'])} here against {len(got)} in "
            f"`displacements`, first difference at "
            f"{np.flatnonzero(mine['index'][: len(got)] != got[: len(mine['index'])])[:3]}"
        )
        lines = np.array([d.line for d in theirs], dtype=float)
        assert np.allclose(mine["line"], lines), f"run={run}: the lines differ"


def came_back(
    bars: dict[str, np.ndarray],
    starts: np.ndarray,
    lines: np.ndarray,
    ups: np.ndarray,
    horizon: int = HORIZON,
) -> np.ndarray:
    """Did price trade back to each line within `horizon` bars of the start?

    A demand origin sits below price, so the return is a low reaching down to
    it; a supply origin is the mirror. Measured from the bar *after* the one
    the push finished on, because nothing about the formation is knowable
    before that.
    """
    lows, highs = bars["low"], bars["high"]
    n = len(lows)
    out = np.zeros(len(starts), dtype=bool)
    for k, (start, line, up) in enumerate(zip(starts, lines, ups, strict=True)):
        a, b = int(start) + 1, min(int(start) + 1 + horizon, n)
        if a >= b:
            continue
        out[k] = lows[a:b].min() <= line if up else highs[a:b].max() >= line
    return out


def waited(
    bars: dict[str, np.ndarray],
    starts: np.ndarray,
    lines: np.ndarray,
    ups: np.ndarray,
    horizon: int = HORIZON,
) -> np.ndarray:
    """Bars until the line is reached, `nan` where it never is.

    **The rate cannot report an effect and this can.** At a 100-bar horizon the
    return rate is 0.85 on the real arm and 0.85 on the placebo, which is its
    own ceiling - the power section plants a magnet of 0.1 volatility units a
    bar and the rate does not move, because there is nowhere for it to go. A
    pull that cannot raise an 85% rate still brings price back **sooner**, so
    the time has the dynamic range the rate has spent.
    """
    lows, highs = bars["low"], bars["high"]
    n = len(lows)
    out = np.full(len(starts), np.nan)
    for k, (start, line, up) in enumerate(zip(starts, lines, ups, strict=True)):
        a, b = int(start) + 1, min(int(start) + 1 + horizon, n)
        if a >= b:
            continue
        reached = lows[a:b] <= line if up else highs[a:b] >= line
        where = np.flatnonzero(reached)
        if len(where):
            out[k] = float(where[0] + 1)
    return out


def placebos(
    bars: dict[str, np.ndarray],
    vols: np.ndarray,
    hit: dict[str, np.ndarray],
    rng,
    horizon: int = HORIZON,
) -> tuple[float, float]:
    """The same question at the same distance, from random bars.

    The distance is held in volatility units at the drawn bar, not in price, so
    a placebo in a quiet stretch is the same *statistical* distance rather than
    the same number of points. That is the comparison
    `origin-return-rates.md` found matches the origin on every class.
    """
    closes = bars["close"]
    n = len(closes)
    usable = n - horizon - 2
    if usable <= 10 or not len(hit["index"]):
        return float("nan"), float("nan")
    want = np.abs(closes[hit["confirmed"]] - hit["line"])
    want = want / closes[hit["confirmed"]] * 10_000.0 / vols[hit["confirmed"]]
    rate, took = [], []
    for _ in range(PLACEBOS):
        where = rng.integers(1, usable, size=len(want))
        sign = np.where(hit["up"], -1.0, 1.0)
        level = closes[where] * (1.0 + sign * want * vols[where] / 10_000.0)
        rate.append(came_back(bars, where, level, hit["up"], horizon).mean())
        took.append(np.nanmedian(waited(bars, where, level, hit["up"], horizon)))
    return float(np.mean(rate)), float(np.nanmean(took))


def engulfed(bars: dict[str, np.ndarray], hit: dict[str, np.ndarray]) -> float:
    """Share of these origins whose push bar engulfs the origin's body.

    The shipped predicate, so "similar but not the same" gets a number. An
    engulfing needs the two bars to be **opposite colours** and the second
    body to **contain** the first; a push needs the second body to be
    one-sided in its own range and to travel. Only the first bar of a run is
    asked, which is the only bar an engulfing could involve.
    """
    if not len(hit["index"]):
        return float("nan")
    opens, highs = bars["open"], bars["high"]
    lows, closes = bars["low"], bars["close"]
    both = 0
    for i in hit["index"]:
        before = Bar(opens[i], highs[i], lows[i], closes[i])
        after = Bar(opens[i + 1], highs[i + 1], lows[i + 1], closes[i + 1])
        if engulfing(before, after):
            both += 1
    return both / len(hit["index"])


def magnet(bars: dict[str, np.ndarray], vols: np.ndarray, strength: float) -> dict:
    """The same bars with a real pull toward each push origin planted in them.

    Power, before any null is reported. Each origin's line gets to drag the
    next `HORIZON` bars toward itself by `strength` volatility units a bar, so
    the return rate *should* rise with it. A test that cannot see this cannot
    report its absence.
    """
    if strength <= 0:
        return bars
    hit = found(bars, vols, run=1, body=0.65, leg=1.5,
                band=(ORIGIN_BODY_MIN, ORIGIN_BODY_MAX))
    moved = {k: v.copy() for k, v in bars.items()}
    n = len(moved["close"])
    pull = np.zeros(n)
    for start, line in zip(hit["confirmed"], hit["line"], strict=True):
        a, b = int(start) + 1, min(int(start) + 1 + HORIZON, n)
        if a >= b:
            continue
        toward = np.sign(line - moved["close"][a:b])
        pull[a:b] += toward * strength * vols[a:b] / 10_000.0 * moved["close"][a:b]
    for key in ("open", "high", "low", "close"):
        moved[key] = moved[key] + pull
    # The pull must not invert a bar; a nudge that crosses its own extremes
    # would be a different bar rather than a magnetised one.
    moved["high"] = np.maximum.reduce([moved["high"], moved["open"], moved["close"]])
    moved["low"] = np.minimum.reduce([moved["low"], moved["open"], moved["close"]])
    return moved


def cell(bars, vols, rng, *, run, body, leg, band) -> dict | None:
    """One parameter point on one instrument."""
    hit = found(bars, vols, run=run, body=body, leg=leg, band=band)
    if not len(hit["index"]):
        return None
    real = came_back(bars, hit["confirmed"], hit["line"], hit["up"]).mean()
    mine = float(np.nanmedian(waited(bars, hit["confirmed"], hit["line"], hit["up"])))
    fake, theirs = placebos(bars, vols, hit, rng)
    return {
        "n": float(len(hit["index"])),
        "per1k": float(len(hit["index"]) / len(bars["close"]) * 1000.0),
        "real": float(real),
        "placebo": fake,
        "edge": float(real - fake),
        "bars": mine,
        "bars_placebo": theirs,
        # Negative means the real level is reached **sooner** than a placebo
        # the same distance away, which is what a magnet looks like once the
        # rate has saturated.
        "sooner": mine - theirs,
        "engulf": engulfed(bars, hit),
        "leg": float(np.median(hit["leg"])),
    }


def pooled(rows: list[dict]) -> dict:
    """Instrument rows into one line, weighting each instrument equally.

    Equally rather than by origin count, because one deep history would
    otherwise own the cell - the mistake `pooled-medians-invert-subgroups`
    records.
    """
    if not rows:
        return {}
    keys = ("per1k", "real", "placebo", "edge", "bars", "bars_placebo", "sooner", "engulf", "leg")
    out = {k: float(np.nanmean([r[k] for r in rows])) for k in keys}
    out["n"] = float(np.sum([r["n"] for r in rows]))
    out["instruments"] = float(len(rows))
    return out


def main() -> None:
    rng = np.random.default_rng(SEED)
    print(
        f"The one-candle push. {FRAME} bars, return within {HORIZON} bars,\n"
        f"against a distance-matched placebo drawn {PLACEBOS}x per origin on the\n"
        "same series. run=2 body=0.65 leg=1.5 is the shipped definition.\n"
    )

    groups: dict[str, list[str]] = {}
    for path in sorted(CACHE.glob(f"*.{FRAME}.npz")):
        name = path.name[: -len(f".{FRAME}.npz")]
        groups.setdefault(classify(name), []).append(name)
    wanted = [c for c in (*TRADED, *GENERATED) if c in groups]
    if not wanted:
        print(f"no bars under {CACHE}")
        return

    series: dict[str, list[tuple[str, dict, np.ndarray]]] = {}
    checked = False
    for label in wanted:
        for name in sorted(groups[label])[:PER_CLASS]:
            bars = load(name, FRAME)
            if bars is None:
                continue
            vols = vol_bps(bars)
            if not checked:
                agrees(bars)
                print("the filter agrees with `displacements` on a pinned window\n")
                checked = True
            series.setdefault(label, []).append((name, bars, vols))

    print(f"{'class':<16}{'run':>4}{'body':>6}{'leg':>6}{'n':>8}{'per1k':>8}"
          f"{'real':>7}{'placebo':>9}{'edge':>8}{'bars':>7}{'vs':>7}{'sooner':>8}"
          f"{'engulf':>8}")
    best: tuple[float, tuple] = (-9.0, ())
    for label in wanted:
        got = series.get(label, [])
        if not got:
            continue
        for run in RUNS:
            for body in BODIES:
                for leg in LEGS:
                    rows = [
                        row
                        for _n, bars, vols in got
                        if (
                            row := cell(
                                bars, vols, rng, run=run, body=body, leg=leg,
                                band=(ORIGIN_BODY_MIN, ORIGIN_BODY_MAX),
                            )
                        )
                        is not None
                    ]
                    line = pooled(rows)
                    if not line or line["n"] < LEAST:
                        continue
                    mark = "  <- shipped" if (run, body, leg) == (2, 0.65, 1.5) else ""
                    print(
                        f"{label:<16}{run:>4}{body:>6.2f}{leg:>6.1f}{line['n']:>8.0f}"
                        f"{line['per1k']:>8.2f}{line['real']:>7.3f}{line['placebo']:>9.3f}"
                        f"{line['edge']:>+8.4f}{line['bars']:>7.1f}{line['bars_placebo']:>7.1f}"
                        f"{line['sooner']:>+8.2f}{line['engulf']:>8.2f}{mark}"
                    )
                    if label in TRADED and line["edge"] > best[0]:
                        best = (line["edge"], (label, run, body, leg))

    print("\nthe origin's body band, at the best traded cell so far")
    if best[1]:
        label, run, body, leg = best[1]
        print(f"  {label} run={run} body={body:.2f} leg={leg:.1f}")
        print(f"  {'band':<14}{'n':>8}{'per1k':>8}{'real':>7}{'placebo':>9}{'edge':>8}"
              f"{'sooner':>8}{'engulf':>8}")
        for band in BANDS:
            rows = [
                row
                for _n, bars, vols in series[label]
                if (row := cell(bars, vols, rng, run=run, body=body, leg=leg, band=band))
                is not None
            ]
            line = pooled(rows)
            if not line:
                continue
            print(f"  {str(band):<14}{line['n']:>8.0f}{line['per1k']:>8.2f}"
                  f"{line['real']:>7.3f}{line['placebo']:>9.3f}{line['edge']:>+8.4f}"
                  f"{line['sooner']:>+8.2f}{line['engulf']:>8.2f}")

    print("\npower: a real pull toward the origin, planted, at run=1")
    print("  the edge must rise with the strength or nothing above is readable")
    print(f"  {'strength':<10}{'n':>8}{'real':>7}{'placebo':>9}{'edge':>8}"
          f"{'bars':>7}{'vs':>7}{'sooner':>8}")
    control = next((series[c] for c in GENERATED if c in series), None)
    if control is None:
        control = series[wanted[0]]
    for strength in PLANTED:
        rows = []
        for _n, bars, vols in control[:6]:
            moved = magnet(bars, vols, strength)
            row = cell(moved, vols, rng, run=1, body=0.65, leg=1.5,
                       band=(ORIGIN_BODY_MIN, ORIGIN_BODY_MAX))
            if row is not None:
                rows.append(row)
        line = pooled(rows)
        if not line:
            continue
        print(f"  {strength:<10.3f}{line['n']:>8.0f}{line['real']:>7.3f}"
              f"{line['placebo']:>9.3f}{line['edge']:>+8.4f}{line['bars']:>7.1f}"
              f"{line['bars_placebo']:>7.1f}{line['sooner']:>+8.2f}")


if __name__ == "__main__":
    main()
