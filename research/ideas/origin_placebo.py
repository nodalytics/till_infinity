"""The desk's own displacement, with the placebo column its 82% never had.

`order-block-zones.md` measured an **82% return rate** - the first bar back in
the band, up to 300 bars later - and immediately flagged the objection itself:
*levels are not magnets, and 50 days is long enough to wander back to most
places.* `fade-to-origin.md` put it at **77-81%** and found no tradable edge in
three configurations, with 89-91% of fades stopped out.

What neither has is the number that turns a return rate into a claim about the
**level**: the rate at which a **matched price the same distance away** is
reached over the same window. That is the column here.

## Production's definition, not a big candle

This is `drawing/displacement.py` as written, and it is a different object from
`origins`:

- **the push** - `PUSH_N` = 2 consecutive bars, each with a body at least
  `PUSH_BODY` = 0.65 of its own range, all one colour. Violent because it is
  **one-sided**, not because it is large.
- **the origin** - the bar immediately before them, any colour, body between
  `ORIGIN_BODY_MIN` = 0.10 and `ORIGIN_BODY_MAX` = 0.60 of its range: normally a
  small candle, the ceiling stopping a level being drawn at every step of a
  trend and the floor rejecting the doji, which is undecided rather than small.
- **the leg** - at least `MIN_LEG_VOL` = 1.5 volatility units from the origin's
  body edge to the end of the run.
- **the line** - the origin's **body** edge on the side price returns to: the
  bottom of the body for a demand zone, the top for a supply one.
- **the band** - the origin bar's whole range.

A single large bar with a mark at its midpoint - which is what
`displacement_origin.py` tested, and what the MT5 idea describes - is **not**
this. That test stands as a test of the fair-value-gap construction and not of
this one.

## What the placebo has to be

The return is the first bar back in the band within `HORIZON` bars, counted
**once per zone**. So the placebo is a band the same width, the same distance
from the end of the push, on the **opposite** side, reached within the same
window and counted the same way.

And because this desk has now measured that a return rate is largely a function
of **distance** - a random bar's midpoint is reached 95% of the time and a
displacement's 86% - both are also reported inside buckets of distance. At
matched distance, the origin either beats its placebo or it does not.
"""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
ROOT = HERE.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from level_signatures import JITTER, SEED  # noqa: E402
from screen import load  # noqa: E402

#: Production's own constants, restated so this file can be read alone - and
#: checked against the source in `main`.
PUSH_BODY, PUSH_N = 0.65, 2
ORIGIN_BODY_MIN, ORIGIN_BODY_MAX = 0.10, 0.60
MIN_LEG_VOL = 1.5
#: The window the 82% was measured over, and the sweep around it.
#:
#: **The horizon is the hypothesis.** If 300 bars is long enough to wander back
#: to most places - which `magnet.md` says and the placebo column confirms -
#: then an origin that is respected should beat its placebo **early** and the
#: gap should close as the window grows, because a long enough window reaches
#: everything. A flat gap across horizons would mean the opposite: a constant
#: small advantage with no timing in it.
HORIZONS = tuple(int(k) for k in os.environ.get("HORIZONS", "50,100,250,300,500").split(","))
HORIZON = max(HORIZONS)
LOOK = int(os.environ.get("LOOK", "100"))
FRAMES = tuple(os.environ.get("FRAMES", "1h,4h,1d").split(","))
BUCKETS = ((0.0, 1.0), (1.0, 2.0), (2.0, 4.0), (4.0, 99.0))


def zones(bars, rng) -> list[dict]:
    """Every displacement zone, its first return, and its placebo's."""
    o, h, l_, c = bars["open"], bars["high"], bars["low"], bars["close"]
    out: list[dict] = []
    at = LOOK + 2
    end = len(c) - HORIZON - 2
    while at < end:
        window = slice(at - LOOK, at)
        typical = float(np.median(h[window] - l_[window]))
        if not (typical > 0):
            at += 1
            continue
        # The push: PUSH_N one-sided bars of one colour.
        bodies = []
        ok = True
        for k in range(PUSH_N):
            i = at + k
            span = float(h[i] - l_[i])
            if span <= 0:
                ok = False
                break
            bodies.append((float(c[i]) - float(o[i])) / span)
        if not ok or len(bodies) < PUSH_N:
            at += 1
            continue
        if not all(abs(b) >= PUSH_BODY for b in bodies):
            at += 1
            continue
        if len({b > 0 for b in bodies}) != 1:
            at += 1
            continue
        up = bodies[0] > 0
        # The origin: the bar before, a normally-small candle.
        oi = at - 1
        span = float(h[oi] - l_[oi])
        if span <= 0:
            at += 1
            continue
        share = abs(float(c[oi]) - float(o[oi])) / span
        if not (ORIGIN_BODY_MIN <= share <= ORIGIN_BODY_MAX):
            at += 1
            continue
        # The line: the body edge price returns to.
        body_low = min(float(o[oi]), float(c[oi]))
        body_high = max(float(o[oi]), float(c[oi]))
        line = body_low if up else body_high
        band_low, band_high = float(l_[oi]), float(h[oi])
        # The leg: MIN_LEG_VOL from the body edge to the end of the run.
        run_end = at + PUSH_N - 1
        reach = float(h[run_end]) if up else float(l_[run_end])
        if abs(reach - line) < MIN_LEG_VOL * typical:
            at += 1
            continue
        if run_end + 1 + HORIZON >= len(c):
            break
        here = float(c[run_end])
        distance = abs(here - line) / typical
        width = band_high - band_low
        # The placebo: the same band, the same distance, the other side.
        offset = (here - line) * -(1.0 + float(rng.uniform(-JITTER, JITTER)))
        mirror = here + offset
        mirror_near = mirror - width / 2.0
        mirror_far = mirror + width / 2.0

        def first_bar(target: float, downward: bool) -> int:
            """Bars until price first reaches `target`, or -1 inside the window."""
            for step in range(1, HORIZON + 1):
                i = run_end + step
                if i >= len(c):
                    return -1
                if (float(l_[i]) <= target) if downward else (float(h[i]) >= target):
                    return step
            return -1

        # **Time is the other half of the edge.** If both the origin and its
        # placebo are eventually reached, the probability gap closes as the
        # window grows - which is what 300 against 500 bars showed, both rising
        # and the gap flat at +0.011. What a flat gap leaves open is *speed*:
        # an origin reached sooner than a matched price is an edge in time even
        # when the probability is the same.
        band_at = first_bar(band_high if up else band_low, up)
        line_at = first_bar(line, up)
        placebo_at = first_bar(mirror_near if offset > 0 else mirror_far, offset <= 0)
        margin = RESOLVE * typical
        row: dict = {
            "distance": distance,
            "band_at": band_at,
            "placebo_at": placebo_at,
            "line_at": line_at,
        }
        for horizon in HORIZONS:
            row[f"band_{horizon}"] = 1.0 if 0 < band_at <= horizon else 0.0
            row[f"line_{horizon}"] = 1.0 if 0 < line_at <= horizon else 0.0
            row[f"placebo_{horizon}"] = 1.0 if 0 < placebo_at <= horizon else 0.0
        # What the band did on arrival, for the origin and for its placebo. The
        # placebo's band is mirrored, so price arrives at it from the other
        # side and `up` inverts.
        if band_at > 0:
            row["origin_outcome"] = classify(
                h, l_, c, run_end + band_at, band_low, band_high, up, margin
            )
        if placebo_at > 0:
            row["placebo_outcome"] = classify(
                h, l_, c, run_end + placebo_at, mirror_near, mirror_far, not up, margin
            )
        out.append(row)
        at = run_end + 1
    return out


def show(label: str, rows: list[dict], horizon: int) -> None:
    if len(rows) < 50:
        print(f"  {label:<14}{len(rows):>7}  too few")
        return
    band = float(np.mean([r[f"band_{horizon}"] for r in rows]))
    line_hit = float(np.mean([r[f"line_{horizon}"] for r in rows]))
    placebo = float(np.mean([r[f"placebo_{horizon}"] for r in rows]))
    print(
        f"  {label:<14}{len(rows):>7,}{band:>9.3f}{line_hit:>8.3f}{placebo:>10.3f}"
        f"{band - placebo:>+9.3f}{float(np.median([r['distance'] for r in rows])):>10.2f}"
    )


def timing(rows: list[dict]) -> None:
    """Which is reached first, and how much sooner - the edge in time."""
    both = [r for r in rows if r["band_at"] > 0 and r["placebo_at"] > 0]
    if len(both) < 50:
        print("    too few reached both")
        return
    sooner = float(np.mean([1.0 if r["band_at"] < r["placebo_at"] else 0.0 for r in both]))
    ties = float(np.mean([1.0 if r["band_at"] == r["placebo_at"] else 0.0 for r in both]))
    print(f"    both reached {len(both):>6,}   origin first {sooner:.3f}   ties {ties:.3f}")
    print(
        f"    median bars to origin {float(np.median([r['band_at'] for r in both])):>6.0f}"
        f"   to placebo {float(np.median([r['placebo_at'] for r in both])):>6.0f}"
    )
    # Only the origin reached, or only the placebo - the asymmetry at the edge.
    only_band = sum(1 for r in rows if r["band_at"] > 0 and r["placebo_at"] < 0)
    only_placebo = sum(1 for r in rows if r["band_at"] < 0 and r["placebo_at"] > 0)
    print(f"    only origin {only_band:>5,}   only placebo {only_placebo:>5,}")


#: Ages a zone is asked about, in **days**, converted to bars per frame. The
#: module that draws these says in its own docstring that freshness is
#: deliberately not applied and that "how fast they wear out is a measurement
#: nobody here has made". This is that measurement.
AGES = tuple(float(k) for k in os.environ.get("AGES", "0,3,14,28").split(","))
#: Bars a day holds, per frame - FX trades about 24 hours, five days a week.
PER_DAY = {"15m": 96, "1h": 24, "4h": 6, "1d": 1}
#: The window the conditional rate is measured over, in days.
WINDOW_DAYS = float(os.environ.get("WINDOW_DAYS", "5"))


def wear(rows: list[dict], frame: str) -> None:
    """Given a zone is still unvisited at age A, is it reached in the next window?

    This is a **hazard**, and the placebo column is what makes it a statement
    about the zone rather than about how long price has had to wander. A zone
    that wears out shows a falling hazard; one that does not shows a flat one.
    """
    per_day = PER_DAY.get(frame, 24)
    window = max(int(WINDOW_DAYS * per_day), 2)
    print(f"    wear-out: does it still get hit in the next {WINDOW_DAYS:g} days?")
    print(f"      {'age':<10}{'alive':>7}{'origin':>9}{'placebo':>10}{'diff':>9}")
    for days in AGES:
        age = int(days * per_day)
        # Alive means not yet reached at `age` bars after the push.
        alive = [r for r in rows if r["band_at"] < 0 or r["band_at"] > age]
        if len(alive) < 50:
            print(f"      {f'{days:g}d':<10}{len(alive):>7}  too few")
            continue
        hit = float(np.mean([1.0 if 0 < r["band_at"] <= age + window else 0.0 for r in alive]))
        # The placebo, on the same surviving zones and the same window.
        other = [r for r in rows if r["placebo_at"] < 0 or r["placebo_at"] > age]
        base = (
            float(np.mean([1.0 if 0 < r["placebo_at"] <= age + window else 0.0 for r in other]))
            if len(other) >= 50
            else float("nan")
        )
        print(
            f"      {f'{days:g}d':<10}{len(alive):>7,}{hit:>9.3f}{base:>10.3f}{hit - base:>+9.3f}"
        )


#: Bars an arrival is followed for, and the margin a resolution needs.
PATIENCE = int(os.environ.get("PATIENCE", "30"))
RESOLVE = float(os.environ.get("RESOLVE", "0.5"))
OUTCOMES = ("reject", "break", "trap", "chop")


def classify(h, l_, c, start: int, low: float, high: float, up: bool, margin: float) -> str:
    """What the band did when price arrived - the desk's own taxonomy.

    `drawing/displacement.py` says the open question is whether the **level is
    respected**, which is different from whether an entry paid, and that none of
    the fade work asked it. A return rate cannot answer it: price arriving says
    nothing about what happened next.

    For a demand zone - price returning down into the band - `reject` is a move
    back up by `margin` without closing below the band, `break` is a close
    below it, `trap` is a break that closes back inside, and `chop` is neither
    resolving inside `PATIENCE` bars.
    """
    through = (low - margin) if up else (high + margin)
    away = (high + margin) if up else (low - margin)
    broke = False
    # **From the bar after arrival.** Price reaches the band by coming into it,
    # so the arrival bar's own far extreme is usually already past `away` - a
    # bar that dips into a demand zone normally has its high above the zone.
    # Counting it fired `reject` on arrival and read 0.927 against a placebo's
    # 0.375, which is the asymmetry and not the level.
    for step in range(start + 1, min(start + 1 + PATIENCE, len(c))):
        if not broke:
            if (float(c[step]) <= through) if up else (float(c[step]) >= through):
                broke = True
                continue
            if (float(h[step]) >= away) if up else (float(l_[step]) <= away):
                return "reject"
        elif low <= float(c[step]) <= high:
            return "trap"
    return "break" if broke else "chop"


def respected(rows: list[dict]) -> None:
    """Outcome distribution at the origin against its placebo."""
    if sum(1 for r in rows if r.get("origin_outcome")) < 100:
        print("      too few arrivals to classify")
        return
    print(f"      {'arm':<10}{'n':>7}" + "".join(f"{name:>10}" for name in OUTCOMES))
    for arm in ("origin", "placebo"):
        have = [r[f"{arm}_outcome"] for r in rows if r.get(f"{arm}_outcome")]
        if len(have) < 100:
            continue
        cells = "".join(
            f"{sum(1 for x in have if x == name) / len(have):>10.3f}" for name in OUTCOMES
        )
        print(f"      {arm:<10}{len(have):>7,}" + cells)
    # The number that answers the module's question: of the arrivals that
    # resolved either way, how often did the level hold?
    for arm in ("origin", "placebo"):
        have = [r[f"{arm}_outcome"] for r in rows if r.get(f"{arm}_outcome")]
        decided = [x for x in have if x != "chop"]
        if len(decided) < 100:
            continue
        held = sum(1 for x in decided if x in ("reject", "trap")) / len(decided)
        print(f"      {arm} held {held:.3f} of {len(decided):,} resolved")


def main() -> None:
    rng = np.random.default_rng(SEED)
    # The constants must match production or this tests nothing.
    from till_infinity.structures.drawing import displacement as prod
    from till_infinity.structures.learning.touches import PUSH_BODY as P_BODY
    from till_infinity.structures.learning.touches import PUSH_N as P_N

    assert (P_BODY, P_N) == (PUSH_BODY, PUSH_N), (P_BODY, P_N)
    assert prod.ORIGIN_BODY_MIN == ORIGIN_BODY_MIN
    assert prod.ORIGIN_BODY_MAX == ORIGIN_BODY_MAX
    assert prod.MIN_LEG_VOL == MIN_LEG_VOL
    print(
        f"production's displacement: {PUSH_N} bars at {PUSH_BODY:.0%} body, origin body "
        f"{ORIGIN_BODY_MIN:.0%}-{ORIGIN_BODY_MAX:.0%},\nleg {MIN_LEG_VOL} vol, first return "
        f"within {HORIZON} bars, one per zone - constants checked against the source\n"
    )
    names = tuple(
        os.environ.get(
            "PAIRS",
            "EURUSD,GBPUSD,USDJPY,XAUUSD,AUDUSD,USDCAD,EURJPY,GBPJPY,EURGBP,USDCHF,XAGUSD,NZDUSD",
        ).split(",")
    )
    for frame in FRAMES:
        rows: list[dict] = []
        for name in names:
            bars = load(name, frame)
            if bars is None:
                continue
            rows += zones(bars, rng)
        if len(rows) < 50:
            print(f"{frame}: {len(rows)} zones, too few\n")
            continue
        print(f"{frame}: {len(rows):,} zones")
        print(
            f"  {'horizon':<14}{'n':>7}{'band':>9}{'line':>8}{'placebo':>10}"
            f"{'diff':>9}{'distance':>10}"
        )
        for horizon in HORIZONS:
            show(f"{horizon} bars", rows, horizon)
        print("    time to return:")
        timing(rows)
        wear(rows, frame)
        print("    what the band did on arrival:")
        respected(rows)
        print()
    print(
        "  `band` is the first bar back in the origin bar's range, `line` its body\n"
        "  edge, `placebo` a band the same width the same distance the other side.\n"
        "  The 82% and the 77-81% on record are the `band` column without the\n"
        "  `placebo` one. At matched distance the origin either beats it or not."
    )
    _ = math


if __name__ == "__main__":
    main()
