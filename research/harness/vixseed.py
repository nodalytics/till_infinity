"""Seed the ensemble's scores from history, so VIX arrives with a weight.

`SCORE_WARMUP` is 60. At daily bars that is about three months before any
member earns a vote, and over a year at weekly. A design that does nothing until
December is not a design, so the scores are computed off history and seeded.

## What it replays

Both sides come from yfinance, which is already a dependency and free. The index
bars were going to come from `prices.db` - it holds 9,144 daily and 8,621 weekly
across the four - but the research machine's copy reads `database disk image is
malformed`, the known result of rsyncing a live SQLite file.

Taking the indices from Yahoo as well turns out to be the better answer rather
than a workaround: it is **exactly what `implied.md` measured on**, so the seed
and the finding it implements are computed over the same bars.

For each `(feed, interval)` it walks the bars forward, folding each into a fresh
`Volatility` exactly as the live path does, and records what every member said
against what the next bar then did - which is precisely `Ensemble.settle`. The
result is each member's decayed relative error and the count behind it, ready
for `Ensemble.seed`.

## The honest limits

**The seed is a claim about history, not a measurement of this code.** It is a
prior rather than a floor: `Score.record` decays toward what it is currently
seeing, so a seed the live bars contradict loses. That is why the live standings
are worth logging beside it for the first months.

**And it inherits `implied.md`'s assumption** that `spx500` tracks `^GSPC`
closely enough for a VIX quote to describe it. The CFD does track the index;
nothing here tests that it does.

Usage:
    PRICES=~/till_infinity/data/prices.db python3 -m research.harness.vixseed
"""

from __future__ import annotations

import json
import math
import os
import sys

from till_infinity.structures.vol.consensus_vol import Ensemble
from till_infinity.structures.vol.garch import Garch
from till_infinity.structures.vol.har import Har
from till_infinity.structures.vol.implied import IMPLIED_FEEDS, IMPLIED_INTERVALS, bps_for
from till_infinity.structures.vol.ranges import Ranges
from till_infinity.structures.vol.volatility import Volatility

OUT = os.path.expanduser(os.environ.get("OUT", "~/till_infinity/data/vixseed.json"))
YEARS = os.environ.get("YEARS", "20y")


def vix_by_day() -> dict[str, float]:
    import yfinance as yf

    got = yf.Ticker("^VIX").history(period=YEARS, interval="1d", auto_adjust=False)
    out = {}
    for when, row in got.iterrows():
        close = row.get("Close")
        if close is not None and not math.isnan(close) and close > 0:
            out[str(when.date())] = float(close)
    return out


#: This book's feed names, and the index each one tracks. The mapping is the
#: assumption `implied.md` already carries: a VIX quote describes `^GSPC`, and
#: `spx500` is a CFD on it. The CFD does track the index; nothing here tests it.
TICKERS = {"spx500": "^GSPC", "us100": "^NDX", "us30": "^DJI", "us2000": "^RUT"}

#: Yahoo's interval codes for the two this member votes at.
CODES = {"1d": "1d", "1w": "1wk"}


def bars_for(ticker: str, interval: str):
    """`(ts, open, high, low, close)` for one index, oldest first."""
    import yfinance as yf

    got = yf.Ticker(ticker).history(period=YEARS, interval=CODES[interval], auto_adjust=False)
    rows = []
    for when, row in got.iterrows():
        values = [row.get(k) for k in ("Open", "High", "Low", "Close")]
        if any(v is None or math.isnan(v) or v <= 0 for v in values):
            continue
        rows.append((when.timestamp(), *(float(v) for v in values)))
    return rows


def run() -> None:
    import datetime as dt

    vix = vix_by_day()
    print(f"^VIX: {len(vix)} daily closes\n")
    if len(vix) < 500:
        print("not enough VIX history to seed anything")
        sys.exit(1)

    seeds: dict[str, dict[str, dict[str, float]]] = {}

    for feed in sorted(IMPLIED_FEEDS):
        for interval in IMPLIED_INTERVALS:
            rows = bars_for(TICKERS[feed], interval)
            if len(rows) < 100:
                print(f"  {feed:>8s} {interval:>3s}  only {len(rows)} bars, skipped")
                continue

            vol = Volatility(_garch=Garch(), _ranges=Ranges(), _har=Har(), _ensemble=Ensemble())
            matched = 0
            for ts, opened, high, low, close in rows:
                if None in (opened, high, low, close):
                    continue
                day = dt.datetime.fromtimestamp(ts, dt.UTC).date().isoformat()
                quote = vix.get(day)
                implied = bps_for(quote, interval) if quote else None
                matched += implied is not None
                vol.update(float(close))
                vol.observe_bar(
                    float(opened), float(high), float(low), float(close), implied_bps=implied
                )

            scores = {
                name: {"error": score.error, "seen": score.seen}
                for name, score in vol._ensemble._scores.items()
                if score.seen > 0
            }
            seeds.setdefault(feed, {})[interval] = scores
            ranked = sorted(scores.items(), key=lambda kv: kv[1]["error"])
            best = ", ".join(f"{n} {1 - s['error']:.3f}" for n, s in ranked)
            print(f"  {feed:>8s} {interval:>3s}  {len(rows):5d} bars, "
                  f"{matched:5d} with VIX  |  {best}")
    with open(OUT, "w") as handle:
        json.dump(seeds, handle, indent=2, sort_keys=True)
    print(f"\nwritten to {OUT}")
    print("\nAccuracy is 1 - decayed relative error, larger is better. If `vix`")
    print("is not at or near the top here, `implied.md` has not transferred to")
    print("this book's own bars and the member should not be seeded at all.")


if __name__ == "__main__":
    run()
