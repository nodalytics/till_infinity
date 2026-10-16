"""Every level price might be drawn to, how often it gets there, and how long.

Asked across 2026-10-16: "are there other magnets like these displacement
origins that can pull price back and do so with linear time", then "as many
magnets as you can test", "the min, median, and max time it takes", and
"candle patterns, support/resistance, fibonacci", "those 200 emas, 50 ema".

This is the desk's way of thinking about **liquidity**: a magnet is a price
where resting orders accumulate, because it is a price many participants can
all see and agree on without talking to each other. Institutions do not find
liquidity by prediction, they find it by going where it is resting - so a level
worth anything is one that is *obvious to everybody else*. That is the thread
tying an EMA to a round number to a prior day's high: none of them is special
geometry, each is a **shared reference**. See `research/docs/magnets.md`.

## A correction this file exists because of

The first version of this harness placed its placebo at the same distance, on
the same side, measured from the same bar - which reconstructs the level price
exactly. Every arm read `+0.00` against its null, and the random-walk check
that was supposed to validate the method could not have failed. A null that is
algebraically the thing it nulls is worse than no null, because it reports
success.

## The nulls, and the honest limit of them

The desk's own objection is on the record and it is right: a walk and a
placebo may behave like the real thing, so they may not be the correct nulls -
or there may be no correct null. Three arms, because no single one is
sufficient:

* **random-time** - the same distance in volatility units, from a *different*
  bar. This asks the only question a magnet claim actually makes: does the
  **identity** of this price matter beyond how far away it is? If a rule's
  levels are reached no sooner than an arbitrary price the same distance out,
  the rule is naming distances rather than prices.
* **time-shifted** - a price *this same rule* drew at a different window,
  tested here. It holds "a price this rule likes" fixed and breaks "a price
  this rule likes **now**", which the random-time arm cannot separate.
* **each other** - every rule in one table on the same bars. A ranking needs
  no synthetic null at all, and it is the arm that survives the objection: if
  the 200 EMA and a displacement origin and a coin-flip price all read alike,
  none of them is a magnet, whatever the absolute numbers say.

The known confound, stated rather than controlled: a drawn level is usually a
price **the path has already visited**, and returning to a visited price needs
no participant. The time-shifted arm is the one that bites on this, because
those are visited prices too.

## What is measured

Return rate, and the full time distribution - min, p25, median, p75, max -
because "how long until price comes back" is the question and a median alone
hides whether the answer is reliable or merely typical. Plus the scaling
exponent `b` in `log t = a + b log d`: a driftless walk covers `d` in time
growing like `d**2`, and anything *pulling* arrives in time proportional to
`d`, so **b near 2 is diffusion and b near 1 is a pull**.

  python research/ideas/magnet_levels.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
for q in (HERE, HERE.parent, HERE.parents[1]):
    sys.path.insert(0, str(q))

from pattern_fingerprint import CACHE, classify, load  # noqa: E402

from till_infinity.structures.drawing import (  # noqa: E402
    displacement,
    equals,
    gaps,
    origin_points,
    pips,
    profile,
    rounds,
    runs,
    vwap,
)
from till_infinity.structures.vol.volatility import Volatility  # noqa: E402

FRAME = "1h"
SEED = 20261016
PER_CLASS = 40
WINDOW = 600
#: Bars between calls. Tightened from 400 after the first pass left the
#: slow-moving references - EMA 100/200, SMA 200, VWAP - with too few
#: resolved buckets to fit a slope, which reports as `nan` and must not
#: be read as a null.
STRIDE = 120
HORIZON = 1000
#: Distance buckets in volatility units. The floor is 0.1 and not 0.5
#: because a moving average usually sits *close* to price - at a 0.5 floor
#: every EMA row was being filtered away before it could be measured,
#: which would have reported the most-watched lines on any chart as
#: having no data rather than no effect.
EDGES = (0.1, 0.5, 1.0, 2.0, 3.0, 5.0, 8.0)
RESOLVED = 0.90
LEAST = 60
#: Moving averages, the most-watched shared references there are.
EMAS = (20, 50, 100, 200)
SMAS = (50, 200)
#: Retracements of the last completed swing leg.
FIBS = (0.382, 0.5, 0.618, 0.786)
#: How close two swing highs must be, in volatility units, to count as a
#: double top - the M - and the same for a W.
TWIN_VOL = 1.0
#: The levels this pass is for. The first panel answered the common ones at
#: 40,000-plus samples and starved the rare ones, and the rare ones are the
#: **most-watched** references - which is exactly where a thesis about shared
#: agreement makes its strongest prediction, so "unmeasured" was the weakest
#: row in that table. Dropping the heavy emitters that are already settled
#: buys the windows and instruments these need. `ema20` and `last_bar` stay as
#: calibration: they were measured at +0.17 and -0.05 before, so if they move
#: far from that here, the change of sampling moved them and not the market.
FOCUS = frozenset(
    {
        "vwap", "equal", "ema200", "sma200", "ema100",
        "double_top", "double_bottom", "double_top_neck", "double_bottom_neck",
        "apex", "apex_body", "engulf_edge", "pin_tip",
        "ema20", "last_bar",
    }
)

TRADED = ("fx_major", "fx_cross", "metal")
GENERATED = ("jump",)


def swings(window: dict[str, np.ndarray], wing: int = 5):
    """Pivot highs and lows inside the window, as (index, price)."""
    highs, lows = window["high"], window["low"]
    n = len(highs)
    ph, pl = [], []
    for p in range(wing, n - wing):
        if highs[p] > highs[p - wing : p].max() and highs[p] >= highs[p + 1 : p + wing + 1].max():
            ph.append((p, float(highs[p])))
        if lows[p] < lows[p - wing : p].min() and lows[p] <= lows[p + 1 : p + wing + 1].min():
            pl.append((p, float(lows[p])))
    return ph, pl


def local(window: dict[str, np.ndarray], unit: float) -> dict[str, list[float]]:
    """The levels this harness draws itself, beside the package's own.

    Each is a **shared reference** rather than a piece of geometry: a price
    that many participants compute the same way and can therefore rest orders
    at without coordinating. That is the whole thesis being tested.
    """
    closes, highs, lows = window["close"], window["high"], window["low"]
    spot = float(closes[-1])
    out: dict[str, list[float]] = {}

    # Moving averages. The most-watched numbers on any chart, and the reason
    # they could work is purely reflexive: enough screens draw the same line
    # that orders collect on it.
    for span in EMAS:
        weight = 2.0 / (span + 1.0)
        run = float(closes[0])
        for price in closes:
            run += weight * (float(price) - run)
        out[f"ema{span}"] = [run]
    for span in SMAS:
        if len(closes) >= span:
            out[f"sma{span}"] = [float(np.mean(closes[-span:]))]

    ph, pl = swings(window)
    # Fibonacci retracements of the last completed leg. No mechanism beyond
    # the reflexive one, which is exactly why it is a clean test of it.
    if ph and pl:
        a, b = ph[-1], pl[-1]
        top, bottom = max(a[1], b[1]), min(a[1], b[1])
        if top > bottom:
            out["fib"] = [bottom + f * (top - bottom) for f in FIBS]

    # Prior day's high, low and close, on a 1h series. Session boundaries are
    # a shared reference everybody has without agreeing to it.
    stamps = window["time"]
    days = (stamps // 86400).astype(int)
    if len(set(days.tolist())) > 1:
        today = days[-1]
        past = days < today
        if past.any():
            last = days[past].max()
            inside = days == last
            out["prior_day"] = [
                float(highs[inside].max()),
                float(lows[inside].min()),
                float(closes[inside][-1]),
            ]

    # M and W: two swings at the same price. The neckline between them is
    # where the stops of everyone who traded the pattern are resting.
    fresh = len(closes) - STRIDE
    for name, turns, pick in (("double_top", ph, max), ("double_bottom", pl, min)):
        for (i_one, one), (i_two, two) in zip(turns, turns[1:], strict=False):
            if i_two < fresh:
                continue
            if abs(one - two) / spot * 10_000.0 / unit > TWIN_VOL:
                continue
            out.setdefault(name, []).append(float(pick(one, two)))
            between = window["low"] if name == "double_top" else window["high"]
            lo, hi = sorted((i_one, i_two))
            if hi > lo:
                chunk = between[lo:hi]
                if len(chunk):
                    out.setdefault(f"{name}_neck", []).append(
                        float(chunk.min() if name == "double_top" else chunk.max())
                    )

    # A and V: a single-bar apex, price in and straight back out. The claim is
    # that a rejection that sharp left business unfinished at the extreme.
    span = highs - lows
    typical = float(np.median(span[span > 0])) if (span > 0).any() else 0.0
    if typical > 0:
        sharp = span > 3.0 * typical
        for i in np.flatnonzero(sharp):
            i = int(i)
            if i < fresh:
                continue
            out.setdefault("apex", []).extend([float(highs[i]), float(lows[i])])
            out.setdefault("apex_body", []).extend(
                [
                    max(float(window["open"][i]), float(closes[i])),
                    min(float(window["open"][i]), float(closes[i])),
                ]
            )

    # Support and resistance by agreement: prices the window's bars touched
    # most often. The purest statement of "a level is a price people keep
    # dealing at" that can be made without any pattern at all.
    grid = unit * spot / 10_000.0
    if grid > 0:
        rungs = np.round(np.concatenate([highs, lows]) / grid).astype(int)
        seen, counts = np.unique(rungs, return_counts=True)
        if len(seen):
            busiest = seen[np.argsort(-counts)[:3]]
            out["touched"] = [float(r * grid) for r in busiest]

    # Candle-pattern levels: the body edge of the last engulfing, and the tip
    # of the last pin. Both are "where the rejection happened".
    opens = window["open"]
    top = np.maximum(opens, closes)
    bottom = np.minimum(opens, closes)
    up = closes > opens
    for i in range(max(1, fresh), len(closes)):
        if bottom[i] < bottom[i - 1] and top[i] > top[i - 1] and up[i] != up[i - 1]:
            out.setdefault("engulf_edge", []).append(float(bottom[i] if up[i] else top[i]))
    for i in range(max(0, fresh), len(closes)):
        rng_ = highs[i] - lows[i]
        if rng_ <= 0:
            continue
        if highs[i] - top[i] > 0.66 * rng_:
            out.setdefault("pin_tip", []).append(float(highs[i]))
        elif bottom[i] - lows[i] > 0.66 * rng_:
            out.setdefault("pin_tip", []).append(float(lows[i]))

    # The trivial control: last bar's extremes. No story at all, so whatever
    # this reads is the floor every other row has to clear.
    out["last_bar"] = [float(highs[-1]), float(lows[-1])]
    return out


def shipped() -> dict:
    """The drawing package's own emitters, behind one calling convention."""
    return {
        "displacement": lambda w, v: displacement.points(
            w["time"], w["open"], w["high"], w["low"], w["close"], v
        ),
        "origin": lambda w, v: origin_points.points(w["time"], w["close"], v),
        "gap": lambda w, v: gaps.points(
            w["time"], w["high"], w["low"], w["close"], v, opens=w["open"]
        ),
        "equal": lambda w, v: equals.points(w["time"], w["close"], v),
        "profile": lambda w, v: profile.points(w["time"], w["close"], v),
        "round": lambda w, v: rounds.points(w["time"], w["close"], v),
        "run": lambda w, v: runs.points(w["time"].astype(int), w["close"], v),
        "swing": lambda w, v: pips.points(w["time"].astype(int), w["close"], 12),
        "vwap": lambda w, v: vwap.points(
            w["time"], w["high"], w["low"], w["close"], w["volume"], v
        ),
    }


def reached(highs: np.ndarray, lows: np.ndarray, at: int, level: float, spot: float) -> float:
    """Bars from `at` until price touches `level`, or `nan` within the horizon."""
    a, b = at, min(at + HORIZON, len(highs))
    if a >= b:
        return float("nan")
    hit = highs[a:b] >= level if level > spot else lows[a:b] <= level
    where = np.flatnonzero(hit)
    return float(where[0] + 1) if len(where) else float("nan")


def collect(bars: dict[str, np.ndarray], rng) -> dict[str, list[tuple[float, float, float]]]:
    """Every level every rule drew, with its distance and its return time."""
    highs, lows, closes = bars["high"], bars["low"], bars["close"]
    n = len(closes)
    live = Volatility()
    made = shipped()
    out: dict[str, list[tuple[float, float, float]]] = {}
    history: dict[str, list[float]] = {}
    spots: list[tuple[int, float, float]] = []
    nxt = WINDOW
    for i in range(n):
        live.update(float(closes[i]))
        if i + 1 != nxt:
            continue
        nxt += STRIDE
        at = i + 1
        window = {k: v[at - WINDOW : at] for k, v in bars.items()}
        spot = float(closes[i])
        unit = live.bps
        if unit <= 0:
            continue
        spots.append((at, spot, unit))
        drawn: dict[str, list[float]] = {}
        for name, call in made.items():
            if name not in FOCUS:
                continue
            try:
                drawn[name] = [float(p.price) for p in call(window, live)]
            except Exception:
                drawn[name] = []
        try:
            drawn.update({k: v for k, v in local(window, unit).items() if k in FOCUS})
        except Exception:
            pass
        for name, levels in drawn.items():
            for price in levels:
                if price <= 0 or price == spot:
                    continue
                away = abs(price - spot) / spot * 10_000.0 / unit
                if not EDGES[0] <= away <= EDGES[-1]:
                    continue
                out.setdefault(name, []).append(
                    (away, reached(highs, lows, at, price, spot), 1.0 if price > spot else -1.0)
                )
                # Kept so the time-shifted arm can test this rule's own prices
                # at a window that is not the one that drew them.
                history.setdefault(name, []).append(price)

    # **Random-time**: the same distance, from a different bar. This is the
    # arm the first version got algebraically wrong.
    for name, rows in list(out.items()):
        if not rows or len(spots) < 4:
            continue
        picks = rng.integers(0, len(spots), size=len(rows))
        fake = []
        for (away, _t, side), k in zip(rows, picks, strict=True):
            at, spot, unit = spots[int(k)]
            level = spot * (1.0 + side * away * unit / 10_000.0)
            fake.append((away, reached(highs, lows, at, level, spot), side))
        out[f"{name}~when"] = fake

    # **Time-shifted**: this rule's own prices, tried from a different window.
    for name, prices in history.items():
        if len(prices) < 8 or len(spots) < 4:
            continue
        rows = out.get(name, [])
        picks = rng.integers(0, len(spots), size=len(rows))
        other = rng.integers(0, len(prices), size=len(rows))
        shifted = []
        for k, j in zip(picks, other, strict=True):
            at, spot, unit = spots[int(k)]
            price = prices[int(j)]
            if price <= 0 or price == spot:
                continue
            away = abs(price - spot) / spot * 10_000.0 / unit
            if not EDGES[0] <= away <= EDGES[-1]:
                continue
            shifted.append(
                (away, reached(highs, lows, at, price, spot), 1.0 if price > spot else -1.0)
            )
        if shifted:
            out[f"{name}~where"] = shifted
    return out


def described(rows: list[tuple[float, float, float]]) -> dict:
    """Return rate, the whole time distribution, and the scaling exponent."""
    if not rows:
        return {}
    away = np.array([r[0] for r in rows])
    took = np.array([r[1] for r in rows])
    back = took[~np.isnan(took)]
    mids, times = [], []
    for lo, hi in zip(EDGES[:-1], EDGES[1:], strict=True):
        inside = (away >= lo) & (away < hi)
        if inside.sum() < LEAST:
            continue
        got = took[inside]
        rate = float(np.mean(~np.isnan(got)))
        if rate < RESOLVED:
            continue
        median = float(np.nanmedian(got))
        if median > 0:
            mids.append(float(np.sqrt(lo * hi)))
            times.append(median)
    slope = float("nan")
    if len(mids) >= 3:
        slope = float(np.polyfit(np.log(mids), np.log(times), 1)[0])
    if not len(back):
        return {}
    return {
        "n": int(len(rows)),
        "rate": float(np.mean(~np.isnan(took))),
        "min": float(np.min(back)),
        "p25": float(np.percentile(back, 25)),
        "median": float(np.median(back)),
        "p75": float(np.percentile(back, 75)),
        "max": float(np.max(back)),
        "slope": slope,
        "away": float(np.median(away)),
    }


def main() -> None:
    rng = np.random.default_rng(SEED)
    print(
        f"Magnets: where price returns, how often, and how long it takes.\n"
        f"{FRAME} bars, {WINDOW}-bar windows every {STRIDE}, {HORIZON} bars to return.\n"
        "`~when` is the same distance from a different bar; `~where` is this\n"
        "rule's own level price tried at a different time. slope b: 2 is\n"
        "diffusion, 1 is a pull. Times are in bars.\n"
    )
    groups: dict[str, list[str]] = {}
    for path in sorted(CACHE.glob(f"*.{FRAME}.npz")):
        name = path.name[: -len(f".{FRAME}.npz")]
        groups.setdefault(classify(name), []).append(name)
    wanted = [c for c in (*TRADED, *GENERATED) if c in groups]

    for label in wanted:
        pooled: dict[str, list] = {}
        for name in sorted(groups[label])[:PER_CLASS]:
            bars = load(name, FRAME)
            if bars is None:
                continue
            if "volume" not in bars:
                bars["volume"] = np.ones(len(bars["close"]))
            for key, rows in collect(bars, rng).items():
                pooled.setdefault(key, []).extend(rows)
        if not pooled:
            continue
        print(f"\n=== {label}")
        # **The null's own slope is the point, not just its median.** Real
        # markets travel superdiffusively - trends, volatility clustering and
        # fat tails all carry price further per unit time than a walk - so
        # every rule reads well under 2 on real bars and that says nothing by
        # itself. `b-when` is what the same distance does from an arbitrary
        # bar, and `vs b` is the only column that can mean a pull.
        print(f"  {'level':<16}{'n':>7}{'rate':>6}{'away':>6}{'min':>5}{'p25':>6}"
              f"{'med':>6}{'p75':>7}{'max':>7}{'slope':>7}{'b-when':>8}{'vs b':>7}"
              f"{'vs~when':>9}{'vs~where':>10}")
        names = sorted({k.split("~")[0] for k in pooled})
        for key in names:
            line = described(pooled.get(key, []))
            if not line or line["n"] < LEAST:
                continue
            when = described(pooled.get(f"{key}~when", []))
            where = described(pooled.get(f"{key}~where", []))
            vs_when = line["median"] - when["median"] if when else float("nan")
            vs_where = line["median"] - where["median"] if where else float("nan")
            b_when = when.get("slope", float("nan")) if when else float("nan")
            print(
                f"  {key:<16}{line['n']:>7}{line['rate']:>6.2f}{line['away']:>6.1f}"
                f"{line['min']:>5.0f}{line['p25']:>6.0f}{line['median']:>6.0f}"
                f"{line['p75']:>7.0f}{line['max']:>7.0f}{line['slope']:>7.2f}"
                f"{b_when:>8.2f}{line['slope'] - b_when:>+7.2f}"
                f"{vs_when:>+9.1f}{vs_where:>+10.1f}"
            )


if __name__ == "__main__":
    main()
