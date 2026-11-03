"""Power for the bounce study: plant the bounce, then plant the *grading*, and sweep both.

A null is only worth reporting with the strength at which the test stops
seeing one, so the alternative hypothesis is generated rather than
approximated. Two sweeps, because the study asks two questions and one plant
cannot answer both.

**Sweep 1, part 1's power.** `level_shield_power.plant_book`'s construction:
price walks with this market's bar geometry, the production `Levels` book is
maintained causally over the planted bars, and every step that would carry
price across a level in that book is reflected about it with probability
`strength`. 0 is a plain walk, 1 is a book of hard walls. The question is the
strength at which the hold rate stops separating from the placebo.

**Sweep 2, part 2's power, and this is the one the study needs.** A uniform
barrier makes every level the same, so a grade over a level's own past cannot
possibly predict its future - at uniform strength the right answer is *zero
grade gap however hard the barriers are*, which makes a uniform plant a
**control that must read nothing** rather than a power test. The graded plant
gives each level its **own** reflectivity, drawn once when the level is first
seen, from `base - spread/2` or `base + spread/2` by a fair coin. Now levels
genuinely differ, a level's past departures reveal which kind it is, and the
grade has something real to find. `spread` 0 is the uniform control and
`spread` 2*base is half hard walls and half nothing.

Reported per strength and per spread: the statistic recovered, its block
bootstrap sd, and the share of cells with the predicted sign. The blind point
is where |z| first falls below 2.
"""

from __future__ import annotations

import json
import os
import random
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np

import research.ideas.level_bounce as B
import research.ideas.level_bounce_agg as A
import research.ideas.level_shield as L
from till_infinity.indicators.levels import FORGET_BARS, KEEP, MERGE_VOL, TOUCH_NOISE_VOL, Levels
from till_infinity.indicators.trend import REACH

#: Uniform barrier strengths for sweep 1. `level-shield.md`'s own grid, so the
#: two studies' blind points are read on the same axis.
STRENGTHS = (0.0, 0.1, 0.25, 0.5, 0.75, 1.0)

#: Spreads for sweep 2, at `BASE`. 0 is the control that must read nothing.
SPREADS = (0.0, 0.2, 0.4, 0.6, 0.8)
BASE = 0.5

FEEDS = tuple((os.environ.get("POWER_FEEDS") or "eurusd gold").replace(",", " ").split())
INTERVALS = tuple((os.environ.get("POWER_INTERVALS") or "1d").replace(",", " ").split())
DRAWS = int(os.environ.get("POWER_DRAWS") or 3)
OUT = Path(os.environ.get("BOUNCE_OUT") or "bounce-out")


def plant(
    series: L.Series,
    rng: random.Random,
    *,
    unit_span: int,
    strength: float = 0.0,
    spread: float = 0.0,
) -> L.Series:
    """A walk whose own level book reflects it, per level, at a known rate.

    Steps are resampled from the real series, so the bar geometry and the step
    distribution are this market's and only the path structure is planted. The
    book is the production `Levels` at production settings, fed the planted
    bars as they are made, so the barriers the test later looks for are exactly
    the ones that were planted.

    With `spread` 0 every level reflects at `strength`. With `spread > 0` each
    level is assigned `strength -/+ spread/2` once, by a fair coin on first
    sight, and keeps it - which is what makes a level's past informative about
    its future and is the only form in which part 2 has an alternative
    hypothesis at all.

    The reflection is what produces the *shape* too, and that is deliberate
    rather than incidental: a step turned back about the level is a move away
    from it as large as the move that would have gone through, so a strongly
    reflecting level emits larger and straighter departures. The grade reads
    the departures, so the plant generates the signal through the same channel
    the measurement claims to read it from.
    """
    n = len(series.close)
    steps = np.diff(series.close)
    span = series.high - series.low
    safe = np.maximum(span, 1e-12)
    frac_o = np.where(span > 0, (series.open - series.low) / safe, 0.5)
    frac_c = np.where(span > 0, (series.close - series.low) / safe, 0.5)

    book = Levels(
        reach=REACH,
        keep=KEEP,
        merge_vol=MERGE_VOL,
        touch_noise_vol=TOUCH_NOISE_VOL,
        forget=FORGET_BARS,
        span=240,
        unit_span=unit_span,
    )
    rates: dict[int, float] = {}
    held: list[object] = []
    out_o, out_h, out_l, out_c = (np.empty(n) for _ in range(4))
    price = float(series.close[0])
    for i in range(n):
        if i:
            step = float(steps[rng.randrange(len(steps))])
            want = price + step
            if strength > 0.0 or spread > 0.0:
                for level in sorted(book.levels, key=lambda lv: abs(lv.at(book.when) - price)):
                    at = level.at(book.when)
                    if (price - at) * (want - at) >= 0:
                        continue
                    key = id(level)
                    rate = rates.get(key)
                    if rate is None:
                        # A strong reference is kept so a dropped level's
                        # address cannot be handed to a new one, which would
                        # silently give the new level the old one's reflectivity
                        # and plant a grade the measurement did not earn.
                        held.append(level)
                        sign = 1.0 if rng.random() < 0.5 else -1.0
                        rate = min(1.0, max(0.0, strength + sign * spread / 2.0))
                        rates[key] = rate
                    if rng.random() < rate:
                        want = 2.0 * at - want
                    break
            price = want
        k = rng.randrange(n)
        width = float(span[k])
        bottom = price - frac_c[k] * width
        out_c[i], out_l[i], out_h[i] = price, bottom, bottom + width
        out_o[i] = bottom + frac_o[k] * width
        book.handle_bar(L._Bar(out_o[i], out_h[i], out_l[i], out_c[i], float(series.ts[i])))
    return L.Series(
        feed=series.feed,
        venue=series.venue,
        interval=series.interval,
        ts=series.ts,
        open=out_o,
        high=out_h,
        low=out_l,
        close=out_c,
    )


def _measure(made: L.Series, interval: str, settings: dict) -> dict:
    """Every statistic the panel reports, on one planted series, same code path.

    **The R difference is the one that has to be here.** Mean R decides the
    study, so a power sweep calibrated on the hold-rate gap would report the
    blind point of a statistic nothing is judged on - and the one feed measured
    so far has a grade that sorts the hit rate at AUC 0.5335 while moving R by
    a fortieth of its standard error, so the two blind points are demonstrably
    not the same number.
    """
    span = int(settings["unit_span"])
    unit = B.units(made, span)
    rows = B.episodes(
        made,
        B.book_path(made, "levels", unit_span=span, interval=interval),
        unit,
        B.strata_of(unit, span),
        interval=interval,
        horizon=int(settings["horizon"]),
    )
    mask = np.ones(len(rows), dtype=bool)
    hold = A.hold_for(rows, mask)
    out: dict = {
        "episodes": len(rows),
        "skipped": rows.skipped,
        "undecided": rows.undecided,
        "hold": None if hold is None else {"value": hold.value, "sd": hold.sd},
        "shares": A.shares(rows, mask),
        "r": {},
        "grades": {},
    }
    for target in B.TARGETS:
        got = A.r_for(rows, mask, target)
        out["r"][str(target)] = (
            None
            if got is None
            else {"mean": got.mean, "se": got.se, "sd": got.sd, "t": got.t, "n": got.n}
        )
    for grade in B.GRADES:
        gap = A.grade_gap_for(rows, mask, grade)
        auc = A.grade_auc_for(rows, mask, grade)
        entry: dict = {
            "gap": None if gap is None else {"value": gap.value, "sd": gap.sd, "n": gap.n},
            "auc": None if auc is None else {"value": auc.value, "sd": auc.sd, "n": auc.n},
            "r": {},
        }
        for target in B.TARGETS:
            split = A.grade_r_for(rows, mask, grade, target)
            entry["r"][str(target)] = (
                None
                if split is None
                else {
                    "diff": {
                        "mean": split[2].mean,
                        "se": split[2].se,
                        "sd": split[2].sd,
                        "n": split[2].n,
                    },
                    "high": {"mean": split[0].mean, "sd": split[0].sd, "n": split[0].n},
                    "low": {"mean": split[1].mean, "sd": split[1].sd, "n": split[1].n},
                }
            )
        out["grades"][grade] = entry
    return out


def sweep(feed: str, interval: str, draws: int) -> list[dict]:
    """Both sweeps on one series: uniform strength, then graded spread."""
    con = sqlite3.connect(B.BOUNCE_STORE, uri=True)
    try:
        series = B.load(con, feed, interval)
    finally:
        con.close()
    if series is None:
        return []
    settings = B.SETTINGS[interval]
    span = int(settings["unit_span"])
    out: list[dict] = []
    for which, grid in (("uniform", STRENGTHS), ("graded", SPREADS)):
        for value in grid:
            for draw in range(draws):
                rng = random.Random(30_000 + int(value * 1000) + draw)
                made = plant(
                    series,
                    rng,
                    unit_span=span,
                    strength=value if which == "uniform" else BASE,
                    spread=0.0 if which == "uniform" else value,
                )
                row = _measure(made, interval, settings)
                row |= {
                    "feed": feed,
                    "interval": interval,
                    "sweep": which,
                    "level": value,
                    "draw": draw,
                }
                out.append(row)
                print(
                    f"{feed} {interval} {which} {value:.2f} draw {draw}: "
                    f"{row['episodes']} episodes",
                    file=sys.stderr,
                    flush=True,
                )
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    started = time.time()
    with (OUT / "power.jsonl").open("w") as fh:
        for interval in INTERVALS:
            for feed in FEEDS:
                for row in sweep(feed, interval, DRAWS):
                    fh.write(json.dumps(row) + "\n")
                fh.flush()
    print(f"wrote {OUT / 'power.jsonl'} in {time.time() - started:.0f}s", file=sys.stderr)


if __name__ == "__main__":
    main()
