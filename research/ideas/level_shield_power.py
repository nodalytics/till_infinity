"""Power for the level-shield test: plant the barrier, sweep its strength.

A null is only worth reporting with the strength at which the test stops
seeing one. This generates series in which levels **are** barriers by
construction, at a known leak rate, and runs the same dose test over them.

The plant is the alternative hypothesis itself, not a proxy. Price walks; the
same `Levels` book is maintained causally; whenever a step would carry price
across a level in the book, the path is reflected about that level with
probability `strength`. `strength` 0 is a plain walk with this market's bar
geometry and `strength` 1 is a book of hard walls.

Reported per strength: the dose slope the test recovers, its day-block sd, and
the share of cells whose slope is negative. The blind point is the strength at
which |z| first falls below 2.
"""

import os
import random
import sqlite3
import sys

import numpy as np

import research.ideas.level_shield as L
import research.ideas.level_shield_agg as A
from till_infinity.indicators.levels import FORGET_BARS, KEEP, MERGE_VOL, TOUCH_NOISE_VOL, Levels
from till_infinity.indicators.trend import REACH

STRENGTHS = (0.0, 0.05, 0.1, 0.25, 0.5, 0.75, 1.0)

#: Feeds and intervals the sweep covers. One series at a time, single process:
#: the panel is the parallel job, this is the calibration beside it.
FEEDS = tuple((os.environ.get("POWER_FEEDS") or "eurusd gold").replace(",", " ").split())
INTERVALS = tuple((os.environ.get("POWER_INTERVALS") or "15m 1d").replace(",", " ").split())
DRAWS = int(os.environ.get("POWER_DRAWS") or 3)


def plant_book(series: L.Series, strength: float, rng: random.Random, *, unit_span: int) -> L.Series:
    """A walk whose own level book reflects it, with probability `strength`.

    Steps are resampled from the real series, so bar geometry and the step
    distribution are this market's. The book is the production `Levels` with
    production settings, fed the planted bars as they are made - so the
    barriers the test later looks for are the ones that were planted.
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
    out_o, out_h, out_l, out_c = (np.empty(n) for _ in range(4))
    price = float(series.close[0])
    for i in range(n):
        if i:
            step = float(steps[rng.randrange(len(steps))])
            want = price + step
            if strength > 0.0:
                for level, _ in sorted(
                    ((lv.at(book.when), lv.touches) for lv in book.levels),
                    key=lambda x: abs(x[0] - price),
                ):
                    if (price - level) * (want - level) < 0 and rng.random() < strength:
                        want = 2.0 * level - want
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


def sweep(feed: str = "eurusd", interval: str = "15m", draws: int = 3) -> None:
    """Recovered dose slope against planted barrier strength, one series."""
    con = sqlite3.connect(L.STORE, uri=True)
    try:
        series = L.load(con, feed, interval)
    finally:
        con.close()
    settings = L.SETTINGS[interval]
    print(f"{series.name}: {len(series.close)} bars, {series.days:.1f} days")
    print(f"{'strength':>9} {'slope':>9} {'sd':>8} {'z':>7} {'negative':>9} {'monotone':>9}")
    for strength in STRENGTHS:
        slopes: list[float] = []
        sds: list[float] = []
        negative = 0
        monotone = 0
        cells = 0
        for draw in range(draws):
            rng = random.Random(10_007 * draw + int(strength * 1000))
            made = plant_book(series, strength, rng, unit_span=settings["unit_span"])
            rows = L.measure(made, settings).rows
            for di in range(len(L.DISTANCES)):
                for side in (1, -1):
                    got = A.dose_for(rows, (rows.dist == di) & (rows.side == side), draws=120)
                    if got is None:
                        continue
                    cells += 1
                    slopes.append(got.slope)
                    sds.append(got.sd)
                    negative += got.slope < 0
                    monotone += bool(got.monotone)
        if not cells:
            continue
        slope = float(np.mean(slopes))
        sd = float(np.mean(sds)) / max(1.0, np.sqrt(cells / (len(L.DISTANCES) * 2)))
        print(
            f"{strength:>9.2f} {slope:>+9.4f} {sd:>8.4f} {slope / sd if sd else 0:>+7.2f} "
            f"{negative / cells:>9.2f} {monotone / cells:>9.2f}"
        )


def main() -> None:
    if len(sys.argv) > 2:
        sweep(sys.argv[1], sys.argv[2], draws=DRAWS)
        return
    for interval in INTERVALS:
        for feed in FEEDS:
            sweep(feed, interval, draws=DRAWS)
            print()


if __name__ == "__main__":
    main()
