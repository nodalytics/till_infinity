"""The catalogue this study runs on: three arms over the lab's 15-minute cache.

`node/corpus.py` fills a `ParquetDataCatalog` from `.data/prices/prices.db`,
which holds about 76 days of 15-minute bars for six feeds. Its own docstring
says what that is worth: **"A catalogue this size answers mechanics, not
edge."** A per-trade standard deviation near 1R needs a few hundred trades per
cell before a mean means anything, and 76 days of 15-minute bars gives a rule
firing weekly about eleven.

So this builds a second catalogue from the lab's `data/seqlab` cache, which
holds the same instruments at the same interval over **seven to twelve years**,
and writes three arms into it.

| arm | what it is | what it controls for |
| --- | --- | --- |
| `real` | EURUSD, GBPUSD, XAUUSD, BTCUSD as recorded | nothing; this is the claim |
| `synth` | Deriv's Volatility 25/75, Jump 75 and Step indices | a real market with a *published* generator |
| `walk` | each real feed's log returns resampled i.i.d., with its bar shapes | everything but the bar geometry |

## The spread is modelled, and that is the number to argue about

Exactly as `node/corpus.py` does it: one quote per bar at the bar's own close,
straddled by half the **measured median spread for that feed on DERIV**, taken
from the same `quotes` table. The per-bar `spread` column in the cache is
**not** used and must not be: measured against the recorded quotes it is 3.3 to
8.3x too narrow on FX and 6.5x too wide on `Volatility 75 Index`, and a study
of another shape had 421 of 4,830 cells change sign on the cost line alone.

Measured, 2026-11-05, from the recorded DERIV quotes:

| feed | quotes | median spread | median ATR(1) | cost of a round trip at a 2-ATR stop |
| --- | ---: | ---: | ---: | ---: |
| eurusd | 871 | 1.041 bps | 5.08 bps | **0.102R** |
| gbpusd | 1,133 | 0.890 bps | 5.88 bps | **0.076R** |
| gold | 2,678 | 0.408 bps | 9.62 bps | **0.021R** |
| btc | 2,693 | 2.902 bps | 29.46 bps | **0.049R** |

**No Deriv synthetic has a recorded quote anywhere in the store**, so there is
no measured spread to charge and inventing one is the error this module exists
not to make. The `synth` arm is therefore costed at whatever basis-point figure
gives it a round trip of **0.063R** at the same 2-ATR stop - the median of the
four real legs above - and that is a decision about the *control*, not a claim
that a synthetic is tradable at that price. It makes the null arm pay what the
traded arm pays in the unit the result is reported in, which is the only
property a cost needs to have for a control to be fair.

The `walk` arm keeps its own feed's instrument, venue conventions aside, and
its own measured spread, so it pays exactly what the real leg pays.

## Why the walk is built in log space

`node/surrogates.walk_with_bar_geometry` is the desk's own matched null and is
the right design - resample the step distribution, resample each bar's shape as
proportions of its own range. It is **additive**, which is correct at the
lengths it was written for and wrong here: BTCUSD's 259,486 close-to-close
steps have a standard deviation near 60 dollars, so a random walk of them
wanders about `60 * sqrt(259486) = 30,500` dollars from a start near 8,000 and
spends part of the run at a negative price. Nautilus refuses a negative
`Price`, so the run would abort rather than mislead - but a shorter feed would
merely be distorted.

So the resampling is of **log** returns and of each bar's range as a
*fraction* of its close. Same two resampled quantities, same removal of path
structure, and the price cannot go negative. Reported here because the helper
is fine at its own scale and this is a limit of it, not a defect.
"""

from __future__ import annotations

import argparse
import math
import random
import sqlite3
import sys
from pathlib import Path

import numpy as np

from till_infinity.node import corpus

#: The lab's 15-minute cache, one `.npz` per instrument.
CACHE = Path.home() / "till_infinity" / "data" / "seqlab"

#: The price store the spreads are measured from. `node/corpus.STORE` is
#: relative to the repository and the lab keeps the database outside it.
STORE = Path.home() / "till_infinity" / ".data" / "prices" / "prices.db"

#: The traded arm: the cache file, and the feed name `node/corpus` knows it by.
#: Only feeds with a **recorded** DERIV spread are here - `audusd`, `usdcad`,
#: `usdjpy` and `XAGUSD` are in the cache and have two or fewer quotes at any
#: venue, so they would have to be costed from an invented number.
REAL: dict[str, str] = {
    "EURUSD": "eurusd",
    "GBPUSD": "gbpusd",
    "XAUUSD": "gold",
    "BTCUSD": "btc",
}

#: The synthetic arm: Deriv's published-generator indices, and the symbol each
#: is written under. Spaces are dropped because a Nautilus `Symbol` is an
#: identifier and `Volatility 75 Index` is a label.
SYNTH: dict[str, str] = {
    "Volatility 25 Index": "vol25",
    "Volatility 75 Index": "vol75",
    "Jump 75 Index": "jump75",
    "Step Index": "step",
}

#: What the synthetic arm's round trip costs at a 2-ATR stop, in R. The median
#: of the four real legs, so the control pays what the claim pays.
SYNTH_COST_R = 0.063

#: The venue each arm is written under. The walk keeps its feed's instrument
#: class and precision and changes only the venue, so a pair stays a
#: `CurrencyPair` and gold stays a `Cfd` - an arm that silently swapped the
#: instrument class would change the lot grid and the quantity precision
#: alongside the thing it meant to remove.
VENUE_REAL = "DERIV"
VENUE_WALK = "WALK"


def measured_bps(feed: str, venue: str = VENUE_REAL) -> float:
    """The median recorded spread for this feed on this venue, in bps.

    `node/corpus.spread_bps` with this module's own store path.
    """
    con = sqlite3.connect(f"file:{STORE}?mode=ro", uri=True)
    try:
        return corpus.spread_bps(con, feed, venue)
    finally:
        con.close()


def load(name: str) -> dict[str, np.ndarray]:
    """One cache file as its columns, oldest first and without duplicates."""
    path = CACHE / f"{name}.15m.npz"
    with np.load(path) as data:
        cols = {k: np.asarray(data[k]) for k in ("time", "open", "high", "low", "close", "volume")}
    order = np.argsort(cols["time"], kind="stable")
    cols = {k: v[order] for k, v in cols.items()}
    keep = np.concatenate(([True], np.diff(cols["time"]) > 0))
    return {k: v[keep] for k, v in cols.items()}


def atr_bps(cols: dict[str, np.ndarray]) -> float:
    """The median one-bar true range as a fraction of price, in bps.

    One bar rather than a 14-bar average, because this is only used to turn a
    cost in R into a spread in bps and the two differ by a constant.
    """
    high, low, close = cols["high"], cols["low"], cols["close"]
    prev = close[:-1]
    true = np.maximum(
        high[1:] - low[1:], np.maximum(np.abs(high[1:] - prev), np.abs(low[1:] - prev))
    )
    return float(np.median(true) / np.median(close) * 1e4)


def walk_of(cols: dict[str, np.ndarray], seed: int) -> dict[str, np.ndarray]:
    """The same bars with the path structure resampled out of them.

    Log returns drawn i.i.d. with replacement from this feed's own, and each
    bar's range and wick proportions drawn from this feed's own - so the
    synthetic series has this market's wickiness, its return distribution and
    its calendar, and none of its ordering. See the module docstring on why
    this is in log space where `node/surrogates.walk_with_bar_geometry` is not.
    """
    rng = random.Random(seed)
    close = cols["close"]
    steps = np.diff(np.log(close))
    span = (cols["high"] - cols["low"]) / close
    # Where each bar opened and closed inside its own range, as fractions.
    width = np.where(cols["high"] > cols["low"], cols["high"] - cols["low"], 1.0)
    open_frac = (cols["open"] - cols["low"]) / width
    close_frac = (cols["close"] - cols["low"]) / width
    flat = cols["high"] <= cols["low"]
    open_frac[flat] = 0.5
    close_frac[flat] = 0.5

    n = len(close)
    pick = rng.randrange
    price = float(close[0])
    out_o = np.empty(n)
    out_h = np.empty(n)
    out_l = np.empty(n)
    out_c = np.empty(n)
    for i in range(n):
        price *= math.exp(float(steps[pick(len(steps))]))
        j = pick(n)
        width_i = price * float(span[j])
        low = price - float(close_frac[j]) * width_i
        out_l[i] = low
        out_h[i] = low + width_i
        out_o[i] = low + float(open_frac[j]) * width_i
        out_c[i] = price
    return {
        "time": cols["time"],
        "open": out_o,
        "high": out_h,
        "low": out_l,
        "close": out_c,
        "volume": cols["volume"],
    }


def write_feed(book, feed: str, venue: str, cols: dict[str, np.ndarray], bps: float) -> str:
    """One feed into the catalogue: the instrument, its bars and its quotes."""
    instrument = corpus.instrument_for(feed, venue)
    bar_type = corpus.BarType.from_str(f"{instrument.id}-15-MINUTE-LAST-EXTERNAL")
    rows = list(
        zip(
            cols["time"].tolist(),
            cols["open"].tolist(),
            cols["high"].tolist(),
            cols["low"].tolist(),
            cols["close"].tolist(),
            cols["volume"].tolist(),
            strict=True,
        )
    )
    bars = [corpus._bar(bar_type, instrument, row) for row in rows]
    quotes = [
        corpus._quote(instrument, row[4], int(row[0]) * corpus.NANOS, row[4] * bps / 1e4 / 2.0)
        for row in rows
    ]
    book.write_data([instrument])
    # In chunks: one `write_data` of 294,499 quotes builds the whole Arrow
    # table in memory before it writes a byte, and twelve feeds of those is
    # what takes a 64-core box with 125GB to its knees.
    for start in range(0, len(bars), 50_000):
        book.write_data(bars[start : start + 50_000])
        book.write_data(quotes[start : start + 50_000])
    return (
        f"{instrument.id}: {len(bars)} bars, {bps:.4f} bps, "
        f"{(cols['time'][-1] - cols['time'][0]) / 86_400 / 365.25:.1f} years"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the three-arm catalogue.")
    parser.add_argument("--out", default=str(Path.home() / "till-data" / "grid-catalog"))
    parser.add_argument("--seed", type=int, default=20261105)
    parser.add_argument("--arms", default="real,synth,walk")
    args = parser.parse_args()

    from nautilus_trader.persistence.catalog import ParquetDataCatalog

    where = Path(args.out)
    if where.exists() and any(where.iterdir()):
        raise SystemExit(
            f"{where} already holds data. `write_data` appends, so a second run "
            f"would double every bar and report a different answer rather than "
            f"failing. Remove it and start again."
        )
    where.mkdir(parents=True, exist_ok=True)
    book = ParquetDataCatalog(str(where))
    arms = tuple(a for a in args.arms.split(",") if a)

    for name, feed in REAL.items():
        cols = load(name)
        bps = measured_bps(feed)
        if bps <= 0:
            raise SystemExit(f"{feed} has no recorded DERIV quote to measure a spread from")
        if "real" in arms:
            print(write_feed(book, feed, VENUE_REAL, cols, bps), flush=True)
        if "walk" in arms:
            # One seed per feed, derived, so a rebuild reproduces exactly the
            # same null and two feeds do not share a draw.
            seed = args.seed + sum(ord(c) for c in feed)
            print(write_feed(book, feed, VENUE_WALK, walk_of(cols, seed), bps), flush=True)

    if "synth" in arms:
        for name, feed in SYNTH.items():
            cols = load(name)
            # The bps that makes this arm's round trip cost `SYNTH_COST_R` at a
            # 2-ATR stop: cost_R = bps / (2 * atr_bps).
            bps = SYNTH_COST_R * 2.0 * atr_bps(cols)
            print(write_feed(book, feed, VENUE_REAL, cols, bps), flush=True)

    print(f"\nwrote {where}", file=sys.stderr)
    print(
        "bars are the lab cache as recorded; quotes are one per bar at a measured "
        "median spread, so cost is understated in the hours a spread widens",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
