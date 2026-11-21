"""Can the six cash equity indices reach the surprise trigger at all?

`SurpriseProfile.feeds` admits a feed on **two** measurements and the
`bnbusd` entry exists to enforce the distinction: it was admitted on the
trigger alone and removed when the cost gate was measured at 20% of bars
inside. The six indices here are the mirror image of that mistake - their cost
gate is already measured and their trigger rate is not:

    US Tech 100     0.6% of a 2R target, 100% of bars inside the 10% gate
    Wall Street 30  1.1%, 100% inside
    Japan 225       1.6%, 100% inside
    US SP 500       1.7%, 100% inside
    Germany 40      1.0%,  92% inside
    UK 100          3.5%,  72% inside

So this file measures the other gate, and nothing else. No cost is re-measured
here and `Feed.spread_points` is deliberately unusable (`point` is NaN), so a
cost figure accidentally computed off these feeds reads NaN rather than being
quietly out by a factor of a hundred - `spread-column-is-in-points` is the
error that costs that factor.

## It is `surprise_reach.py` with a different reader, and the reference arm is why

[`surprise_reach.py`](surprise_reach.py) already runs the production fold
(`statespace.facade.Desk.read`) bar by bar and reports the same three numbers.
Its limitation is its data source: the lab's `.npz` cache holds no index
series. The indices arrive as gzipped broker CSV instead, read through
[`index_pullback.py`](index_pullback.py)'s `read`.

**The admitted feeds are re-measured in the same process**, because a rate is
only comparable to the band it is being judged against if the same code
produced both. The band on record in `strategies/surprise.py` is **1.08% to
1.32%** for the admitted seven and **0.81% / 0.76%** for Volatility 75 / 25,
at a noise of `2.0 * (bar log-range / 4)`; a run whose reference arm does not
reproduce those has measured something else and its index column means nothing.
`reproduce-the-baseline-before-an-increment` is the standing version of this -
a HAR increment read +0.036 against a shelf's +0.110 and the cause was the data
window, not the model.

## Four things that make an index cell untrustworthy, each given a column

* **The window.** The deep CSV holds about 2.5 years of M15 for four indices;
  Germany 40 and UK 100 come from the wide CSV at 6,000 bars, about three
  months. A rate over three months is not a rate over 2.5 years, so
  `rate 6k` repeats every feed's rate over its **last 6,000 readouts** and that
  is the column the six are comparable on.
* **The filter's own warm-up.** `rate ex200` drops the first 200 readouts. On a
  6,000-bar feed the warm-up is 3% of the sample and on a 60,000-bar feed it is
  0.3%, so an index that only clears the trigger while the member is cold would
  show up as a gap between these two columns.
* **The overnight session gap.** A cash index stops quoting overnight and the
  fold charges the elapsed **time**, not the bar count - `linear.predict`
  divides by `HOUR`. A 15-hour step accumulates `Q` for fifteen hours and then
  scores the gap return against it. `gap hit` is the share of trigger-clearing
  readouts that are the first bar after a break of more than an hour, against
  `gap base`, the share of all readouts that are. A feed whose triggers are the
  opening bar is a desk that fires once a day at a price that has already gone.
* **Missing bars.** `bars` is readouts, counted, not a window length assumed.

Run as:

    uv run python research/ideas/index_surprise_reach.py
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from index_pullback import read as read_index  # noqa: E402
from signal_layer import load as load_cached  # noqa: E402

from till_infinity.statespace.facade import Desk  # noqa: E402
from till_infinity.statespace.proposing import TRIGGER  # noqa: E402

#: The noise the band on record was measured at, as a multiple of a quarter of
#: each bar's log range. Not swept: `surprise_reach.py` swept 0.5, 1.0 and 2.0
#: and the admitted band quoted in `strategies/surprise.py` is this one.
NOISE = 2.0

#: Cap, matching `surprise_reach.BARS` so the reference arm is the same sample
#: the band on record came from.
BARS = 40_000

#: The tail every feed is additionally reported over, so a 2.5-year index and a
#: three-month index are compared on the same amount of recent history.
RECENT = 6_000

#: Readouts dropped for the `ex200` column. `facade.LEAST` is 200 residuals
#: before an interval is published at all, which is the same order.
WARM = 200

#: A step longer than this is a session break rather than a 15-minute bar.
BREAK = 3_600.0

CSV_FRAME = "M15"
FOLD_FRAME = "15m"

#: Deep CSV: about 2.5 years of M15 for the four cheap indices.
DEEP = Path(".secrets/indices/deepidx.csv.gz")

#: Wide CSV: 15 indices at M15 with a shorter history. The only source here for
#: Germany 40 and UK 100.
WIDE = Path(".secrets/indices/allidx.csv.gz")

#: `(symbol, csv)`. Separate sources, so a feed missing from the deep file looks
#: missing rather than quiet - the same reason `index_pullback` keeps the two
#: files apart.
INDICES = (
    ("US Tech 100", DEEP),
    ("Wall Street 30", DEEP),
    ("Japan 225", DEEP),
    ("US SP 500", DEEP),
    ("Germany 40", WIDE),
    ("UK 100", WIDE),
)

#: The admitted real feeds whose 1.08%-1.32% band the indices are judged
#: against. `ethusd` has no cached series on the lab, as `surprise_reach` notes.
ADMITTED = ("EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "XAUUSD", "BTCUSD")

#: Admitted on the cost gate while firing at two thirds of a real market's
#: rate - the 0.76%-0.81% floor an index can be compared against instead.
SLOWER = ("Volatility 75 Index", "Volatility 25 Index")


def fold(
    when: np.ndarray,
    close: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    volume: np.ndarray,
    feed: str,
) -> tuple[np.ndarray, np.ndarray]:
    """`|surprise|` per bar through the production fold, and each bar's time.

    Verbatim from `surprise_reach.reach` apart from returning the timestamps,
    which the session-gap column needs. `when` is **epoch seconds**: the fold
    divides by `HOUR`, so handing it nanoseconds would make every step 3.6e12
    hours and every predictive infinitely wide.

    `volume` is the venue's quote count and it is passed because production
    passes it - `drives_q` returns `True` for an unclassified feed and all six
    index names are unclassified (`behaving.TRADED_CLASSES` holds the cache's
    `US_Tech_100`, not the broker's `US Tech 100`). Dropping it here would
    measure a mechanism the live desk does not run.
    """
    price = np.log(np.maximum(close, 1e-12))
    span = np.maximum(
        np.log(np.maximum(high, 1e-12)) - np.log(np.maximum(low, 1e-12)),
        1e-9,
    )
    desk = Desk()
    out = np.full(price.size, np.nan)
    for i in range(price.size):
        got = desk.read(
            feed,
            FOLD_FRAME,
            float(when[i]),
            float(price[i]),
            float((NOISE * span[i] / 4.0) ** 2),
            volume=float(volume[i]),
        )
        value = getattr(got, "surprise", None)
        if value is not None and np.isfinite(value):
            out[i] = abs(float(value))
    keep = np.isfinite(out)
    return out[keep], when[keep]


def opening(when: np.ndarray) -> np.ndarray:
    """Which readouts are the first bar after a break longer than `BREAK`."""
    out = np.zeros(when.size, dtype=bool)
    if when.size > 1:
        out[1:] = np.diff(when) > BREAK
    return out


def row(group: str, feed: str, values: np.ndarray, when: np.ndarray) -> str:
    hit = values >= TRIGGER
    gap = opening(when)
    gap_hit = float(np.mean(gap[hit])) if hit.any() else float("nan")
    first = datetime.fromtimestamp(float(when[0]), UTC).strftime("%Y-%m-%d")
    last = datetime.fromtimestamp(float(when[-1]), UTC).strftime("%Y-%m-%d")
    tail = values[-RECENT:]
    rest = values[WARM:] if values.size > WARM else values
    return (
        f"  {group:<10}{feed:<22}{values.size:>8,}  {first} {last}"
        f"{100 * float(np.mean(hit)):>8.2f}%"
        f"{100 * float(np.mean(rest >= TRIGGER)):>8.2f}%"
        f"{100 * float(np.mean(tail >= TRIGGER)):>8.2f}%"
        f"{float(np.quantile(values, 0.99)):>7.2f}{float(values.max()):>7.2f}"
        f"{100 * gap_hit:>8.1f}%{100 * float(np.mean(gap)):>8.1f}%"
    )


def main() -> None:
    print(
        f"Trigger reach for six cash indices. {CSV_FRAME} bars through\n"
        f"statespace.facade.Desk - the production fold - at noise {NOISE} x range/4.\n"
        f"TRIGGER = {TRIGGER}. On record in strategies/surprise.py at this noise:\n"
        "the admitted seven span 1.08% to 1.32%, Volatility 75 reads 0.81% and\n"
        "Volatility 25 0.76%. The reference rows below must reproduce those or\n"
        "the index rows are not comparable to them.\n"
    )
    print(
        f"  {'group':<10}{'feed':<22}{'bars':>8}  {'from':<10} {'to':<10}"
        f"{'rate':>9}{'ex200':>9}{'rate 6k':>9}{'q99':>7}{'max':>7}"
        f"{'gap hit':>9}{'gap base':>9}"
    )
    missing: list[str] = []
    rates: dict[str, list[tuple[str, float, float]]] = {}

    for group, names in (("admitted", ADMITTED), ("slower", SLOWER)):
        for name in names:
            got = load_cached(name, FOLD_FRAME)
            if got is None:
                missing.append(f"{name}: no cached {FOLD_FRAME} series")
                continue
            cut = {k: np.asarray(v, dtype=float)[-BARS:] for k, v in got.items()}
            values, when = fold(
                cut["time"], cut["close"], cut["high"], cut["low"], cut["volume"], name
            )
            if values.size < 500:
                missing.append(f"{name}: {values.size} readouts, under 500")
                continue
            print(row(group, name, values, when))
            rates.setdefault(group, []).append(
                (
                    name,
                    float(np.mean(values >= TRIGGER)),
                    float(np.mean(values[-RECENT:] >= TRIGGER)),
                )
            )

    for name, where in INDICES:
        feed = read_index(name, CSV_FRAME, float("nan"), where=where)
        if feed is None:
            missing.append(f"{name}: not in {where.name} at {CSV_FRAME}")
            continue
        bars = feed.bars
        seconds = bars.ts.astype(np.float64) / 1e9
        order = np.argsort(seconds, kind="stable")
        seconds = seconds[order][-BARS:]
        values, when = fold(
            seconds,
            np.asarray(bars.close, dtype=float)[order][-BARS:],
            np.asarray(bars.high, dtype=float)[order][-BARS:],
            np.asarray(bars.low, dtype=float)[order][-BARS:],
            np.asarray(feed.quotes, dtype=float)[order][-BARS:],
            name,
        )
        if values.size < 500:
            missing.append(f"{name}: {values.size} readouts, under 500")
            continue
        print(row("index", name, values, when))
        rates.setdefault("index", []).append(
            (
                name,
                float(np.mean(values >= TRIGGER)),
                float(np.mean(values[-RECENT:] >= TRIGGER)),
            )
        )

    print()
    for group in ("admitted", "slower", "index"):
        got = rates.get(group) or []
        if not got:
            continue
        full = [r for _, r, _ in got]
        tail = [t for _, _, t in got]
        print(
            f"  {group:<10}band {100 * min(full):.2f}% to {100 * max(full):.2f}% full, "
            f"{100 * min(tail):.2f}% to {100 * max(tail):.2f}% over the last {RECENT:,}"
        )
    if missing:
        print("\n  not measured:")
        for line in missing:
            print(f"    {line}")


if __name__ == "__main__":
    main()
