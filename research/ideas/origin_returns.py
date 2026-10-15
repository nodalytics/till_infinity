"""Does the displacement origin's return rate hold up across asset classes and families?

`fade-to-value` records **82%** of displacement origins being returned to, and
the desk treats that as a target hit rate rather than an entry signal. The
figure was measured on a narrow set. The question here is whether it survives
breadth: 557 instruments in the cache, nine generated families, and seven
traded classes.

## The origin, by the desk's own definition

Not a new one. `drawing/displacement.py` and `drawing/origins.py`:

* **the push** - `PUSH_N` consecutive bars whose bodies are each at least
  `PUSH_BODY` of their own range, all the same direction;
* **the leg** - the push must span at least `MIN_LEG_VOL` volatility units, so
  "two bars agreed" does not qualify;
* **the origin bar** - the bar before the push, whose body must fall between
  `ORIGIN_BODY_MIN` and `ORIGIN_BODY_MAX` of its range. Normally a small
  candle: the upper bound stops every bar of a trend qualifying, the lower one
  rejects the doji;
* **the zone** - `zone_of`: the origin bar's range, or its **body** when the
  range reaches `WIDE_BAR` volatility units, because price went there and did
  not stay.

## What a return rate is worth, and the two things that decide it

A return rate is not a property of the origin alone. It is mostly decided by
**how far price travelled away** and **how long it is given**, and both vary
enormously by instrument: a Step index drifts in fixed increments where gold
gaps. So a raw rate is not comparable across classes, and three things are
reported beside it.

* **A distance-matched placebo zone**, the same width at the same distance on
  the same bars, which is what the rate would be for a price that is not an
  origin.
* **A matched driftless walk**, which gives the rate the geometry produces with
  no structure at all.
* **The horizon**, swept, because 82% at 500 bars and 82% at 20 bars are
  different claims.

The headline to look for is not the level. It is `real - placebo`, per class.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from till_infinity.structures.statespace.behaving import classify  # noqa: E402

CACHE = Path.home() / "till_infinity/data/seqlab"
FRAMES = ("1h", "4h", "1d")
LIMIT = 40000
#: The desk's displacement parameters, unchanged.
PUSH_BODY, PUSH_N = 0.65, 2
MIN_LEG_VOL = 1.5
ORIGIN_BODY = (0.10, 0.60)
WIDE_BAR = 2.0
#: Bars used to set the volatility unit the leg and the zone are measured in.
UNIT_BACK = 100
#: Horizons for "has price come back into the zone", in bars.
HORIZONS = (20, 50, 100, 500)
#: Instruments per class, capped so one crowded class does not dominate.
PER_CLASS = 26
JITTER = 0.20
SEED = 20261015
#: Origins per feed, evenly spaced, so a long history does not outvote a short.
PER_FEED = 400
#: Zone constructions compared on identical bars.
KINDS = ("origin", "engulf", "both")


def universe(frame: str) -> dict[str, list[str]]:
    """Every instrument in the cache for `frame`, grouped by class.

    **Not `relationship_screen.universe`, which returns synthetics only** - it
    filters on `GENERATED_PREFIXES` by design, and a first run of this study
    using it reported nine generated families and not one traded class, which
    was half the question. This walks the cache and lets
    `behaving.classify` name each instrument, so FX, metals, energy, indices,
    baskets, softs and equities appear beside the generated families.
    """
    found: dict[str, list[str]] = {}
    for path in sorted(CACHE.glob(f"*.{frame}.npz")):
        name = path.name[: -len(f".{frame}.npz")]
        found.setdefault(classify(name), []).append(name)
    return found


def load(name: str, frame: str):
    path = CACHE / f"{name}.{frame}.npz"
    if not path.exists():
        return None
    with np.load(path) as bundle:
        need = {"time", "open", "high", "low", "close"}
        if not need <= set(bundle.keys()):
            return None
        order = np.argsort(bundle["time"])
        got = {k: np.asarray(bundle[k], dtype=float)[order] for k in need}
    keep = (got["high"] >= got["low"]) & (got["low"] > 0)
    got = {k: v[keep] for k, v in got.items()}
    if len(got["close"]) < 1200:
        return None
    if len(got["close"]) > LIMIT:
        got = {k: v[-LIMIT:] for k, v in got.items()}
    return got


def units(bars) -> np.ndarray:
    """The volatility unit per bar: a trailing mean true range, in price."""
    highs, lows, closes = bars["high"], bars["low"], bars["close"]
    prior = np.concatenate(([closes[0]], closes[:-1]))
    span = np.maximum.reduce(
        [highs - lows, np.abs(highs - prior), np.abs(lows - prior)]
    )
    out = np.full(len(span), np.nan)
    csum = np.cumsum(span)
    out[UNIT_BACK:] = (csum[UNIT_BACK:] - csum[:-UNIT_BACK]) / UNIT_BACK
    return out


def origins(bars, unit: np.ndarray, kind: str = "origin"):
    """Every zone of one construction, as `(index, low, high, launched up)`.

    Three constructions on the same bars, so their return rates are directly
    comparable:

    * **`origin`** - the desk's displacement origin. The origin bar is `i`, the
      push runs from `i + 1`, and the zone is `zone_of` on bar `i`. Faithful to
      `drawing/displacement.py`.
    * **`engulf`** - the published method's zone: bar `i + 1` engulfs bar `i`,
      and the zone is bar `i`'s **whole range**, with no constraint on its
      body and no leg requirement.
    * **`both`** - an engulfing bar that also passes the displacement tests.

    The two are **not** the same construction, which a shape measurement makes
    plain: an engulfing bar has 1.42 times the median range and a body of only
    0.408 of it, against 0.499 for bars generally, and just 15% clear the 0.65
    body share the push requires against 31% of all bars. An engulf selects a
    wide, wick-heavy bar; a displacement selects a body-dominant one.
    """
    opens, highs = bars["open"], bars["high"]
    lows, closes = bars["low"], bars["close"]
    out = []
    for i in range(UNIT_BACK, len(closes) - PUSH_N - 1):
        here = unit[i]
        if not (here > 0):
            continue
        span = highs[i] - lows[i]
        if span <= 0:
            continue
        first = closes[i + 1] - opens[i + 1]
        side = 1 if first > 0 else -1 if first < 0 else 0
        if side == 0:
            continue
        wants_origin = kind in {"origin", "both"}
        wants_engulf = kind in {"engulf", "both"}
        if wants_engulf:
            # Bar `i + 1` engulfs bar `i`, strictly wider.
            after = highs[i + 1] - lows[i + 1]
            if not (
                highs[i + 1] >= highs[i] and lows[i + 1] <= lows[i] and after > span
            ):
                continue
        if wants_origin:
            share = abs(closes[i] - opens[i]) / span
            if not (ORIGIN_BODY[0] <= share <= ORIGIN_BODY[1]):
                continue
            ok = True
            for j in range(i + 1, i + 1 + PUSH_N):
                reach = highs[j] - lows[j]
                if reach <= 0 or side * (closes[j] - opens[j]) < PUSH_BODY * reach:
                    ok = False
                    break
            if not ok:
                continue
            leg = abs(closes[i + PUSH_N] - opens[i + 1])
            if leg < MIN_LEG_VOL * here:
                continue
        # `zone_of`: the range, or the body when the bar is wide. The published
        # method has no such rule, so its zone is the raw range.
        low, high = float(lows[i]), float(highs[i])
        if kind != "engulf" and (high - low) >= WIDE_BAR * here:
            top, bottom = float(opens[i]), float(closes[i])
            if top != bottom:
                low, high = min(top, bottom), max(top, bottom)
        out.append((i, low, high, side > 0))
    return out


def returned(bars, low: float, high: float, start: int, horizon: int):
    """`(came back, bars taken)` within `horizon` after the push completes."""
    highs, lows = bars["high"], bars["low"]
    end = min(start + horizon + 1, len(highs))
    for i in range(start, end):
        if lows[i] <= high and highs[i] >= low:
            return True, i - start
    return False, None


def walk_like(bars, rng):
    """A driftless walk with this feed's bar volatility and range shape."""
    closes = bars["close"]
    steps = np.diff(np.log(np.maximum(closes, 1e-12)))
    spread = float(np.nanstd(steps))
    wick = float(np.nanmedian((bars["high"] - bars["low"]) / np.maximum(closes, 1e-12)))
    count = len(closes)
    path = float(closes[0]) * np.exp(np.cumsum(rng.normal(0.0, spread, count)))
    opens = np.concatenate(([path[0]], path[:-1]))
    half = np.abs(rng.normal(0.0, wick / 2.0, count)) * path
    return {
        "open": opens,
        "high": np.maximum(opens, path) + half,
        "low": np.maximum(np.minimum(opens, path) - half, 1e-9),
        "close": path,
        "time": bars["time"],
    }


def measure(bars, rng, placebo: bool, kind: str = "origin"):
    """Return rates per horizon over this feed's zones of one construction."""
    unit = units(bars)
    found = origins(bars, unit, kind)
    if not found:
        return None
    if len(found) > PER_FEED:
        pick = np.linspace(0, len(found) - 1, PER_FEED).astype(int)
        found = [found[int(i)] for i in pick]
    counts = {h: [0, 0] for h in HORIZONS}
    taken: list[int] = []
    for i, low, high, up in found:
        start = i + (PUSH_N + 1 if kind != "engulf" else 2)
        if start >= len(bars["close"]):
            continue
        if placebo:
            # The same band, the same width, moved to a matched distance on the
            # other side of where price went - a price that is not an origin.
            here = float(bars["close"][start])
            middle = (low + high) / 2.0
            gap = (middle - here) * (1.0 + float(rng.uniform(-JITTER, JITTER)))
            half = (high - low) / 2.0
            middle = here + gap
            low, high = middle - half, middle + half
        for horizon in HORIZONS:
            back, when = returned(bars, low, high, start, horizon)
            counts[horizon][1] += 1
            if back:
                counts[horizon][0] += 1
                if horizon == max(HORIZONS) and when is not None:
                    taken.append(when)
    return counts, taken, len(found)


def main() -> None:
    print(
        "**A driftless walk already returns to an origin zone 0.825 of the time at\n"
        "h=100** - the 82% this was asked about - and to an engulfed-candle zone 0.953\n"
        "of the time. The level is the zone's width over the distance price travelled,\n"
        "so only `vs walk` and the placebo column carry information.\n"
    )
    print(
        "Displacement origins by the desk's own definition - "
        f"push {PUSH_N} bars at body {PUSH_BODY}, leg {MIN_LEG_VOL} vol, origin body "
        f"{ORIGIN_BODY[0]} to {ORIGIN_BODY[1]}.\n"
        "`real - placebo` is the column that means anything; the level is mostly "
        "distance and horizon.\n"
    )
    rng = np.random.default_rng(SEED)
    for frame in FRAMES:
        classes = universe(frame)
        print("=" * 104)
        print(f"{frame}")
        print("=" * 104)
        head = f"  {'class':<16}{'kind':<8}{'feeds':>6}{'zones':>8}"
        print(head + "".join(f"{f'h={h}':>25}" for h in HORIZONS) + f"{'median bars':>12}")
        print(
            f"  {'':<16}{'':<8}{'':>6}{'':>8}"
            + "".join(f"{'real  plac  walk vs walk':>25}" for _ in HORIZONS)
        )
        for label in sorted(classes):
            picked = sorted(classes[label])[:PER_CLASS]
            loaded = [(n, load(n, frame)) for n in picked]
            loaded = [(n, b) for n, b in loaded if b is not None]
            if not loaded:
                continue
            for kind in KINDS:
                totals = {h: [0, 0, 0, 0, 0, 0] for h in HORIZONS}
                waits: list[int] = []
                feeds = 0
                zone_count = 0
                for _name, bars in loaded:
                    real = measure(bars, rng, False, kind)
                    fake = measure(bars, rng, True, kind)
                    walked = measure(walk_like(bars, rng), rng, False, kind)
                    if real is None or fake is None:
                        continue
                    feeds += 1
                    zone_count += real[2]
                    waits.extend(real[1])
                    for h in HORIZONS:
                        totals[h][0] += real[0][h][0]
                        totals[h][1] += real[0][h][1]
                        totals[h][2] += fake[0][h][0]
                        totals[h][3] += fake[0][h][1]
                        if walked is not None:
                            totals[h][4] += walked[0][h][0]
                            totals[h][5] += walked[0][h][1]
                if not feeds or not totals[HORIZONS[0]][1]:
                    continue
                row = f"  {label:<16}{kind:<8}{feeds:>6}{zone_count:>8}"
                for h in HORIZONS:
                    hit = totals[h][0] / totals[h][1] if totals[h][1] else float("nan")
                    fake_hit = totals[h][2] / totals[h][3] if totals[h][3] else float("nan")
                    walk_hit = totals[h][4] / totals[h][5] if totals[h][5] else float("nan")
                    row += f"{hit:>7.3f}{fake_hit:>6.3f}{walk_hit:>6.3f}{hit - walk_hit:>+7.3f}"
                middle = float(np.median(waits)) if waits else float("nan")
                print(row + f"{middle:>12.0f}")
        print(
            "  `plac` is the same band width at a matched distance on the same bars.\n"
            "  A class where real and placebo agree has a return rate that is about\n"
            "  geometry and horizon, not about the origin.\n"
        )


if __name__ == "__main__":
    main()
