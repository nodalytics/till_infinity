"""Pull the commodities, indices and currency baskets the cache lacks, once.

The sequence cache holds FX, equities and Deriv synthetics. It holds **no
energy, no softs and no indices**, which left the headline commodity-currency
claim - CAD against crude - untestable. The terminal offers all of them: 731
symbols, including `US Oil`, `UK Brent Oil`, `NGAS`, five softs, platinum and
palladium, fourteen indices, and - the one that matters most - `USD Basket`.

**`USD Basket` is why this is worth the fetch.** The first pass at the
commodity-currency claim found `AUDUSD` against gold at `+0.4011` and
`GBPUSD` against gold at `+0.3598`. Sterling is not a commodity currency, so
most of that correlation is the **dollar**: gold is priced in dollars, so gold
up is dollar down. A dollar index lets the dollar be regressed out and the
question becomes whether AUD keeps a commodity link once it is.

Eight workers and one timeframe, for the reason `seqcache.py` gives: this is the
same terminal the live desk trades through, and `research/starving.md`'s rule is
that research which degrades production is not research that got a result
faster. Resumable - a symbol already on disk is skipped - so a drop costs only
what it had not already pulled.

    ./.secrets/lab.sh run research/harness/commodity_fetch.py
"""

from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from research.harness import seqlab

WORKERS = 8
FRAMES = ("1h",)

#: Grouped so a partial pull is still a usable study rather than a random
#: subset: the energy and the dollar basket are what the open claims need.
WANTED = {
    "energy": ("US Oil", "UK Brent Oil", "NGAS"),
    "basket": ("USD Basket", "EUR Basket", "GBP Basket"),
    "metal": ("XPTUSD", "XPDUSD"),
    "soft": ("Sugar", "Cocoa", "Cotton", "CoffeeArab", "CoffeeRobu"),
    # **The currencies that give the group test any power.** With only AUD,
    # CAD and NZD named against GBP and EUR, a permutation over currency
    # labels has `C(5, 3) = 10` arrangements and cannot return a p below 0.1
    # whatever the effect is. These six take it to `C(10, 6) = 210`.
    #
    # `USDNOK` against `USDSEK` is the cleanest natural experiment available:
    # two neighbouring Nordic economies of similar size and institutions, one
    # of which exports oil. Sweden is the control Norway deserves, in a way
    # sterling is not.
    #
    # `CLP` and `RUB` are not offered, so copper and the Russian claims stay
    # untestable; `HKD` and `CNH` are pegged or managed, which would give the
    # control group a near-zero correlation for a reason that has nothing to
    # do with commodities, so they are left out rather than used as flattery.
    "currency": ("USDNOK", "USDSEK", "USDMXN", "USDZAR", "USDPLN"),
    "index": (
        "Germany 40",
        "France 40",
        "UK 100",
        "Japan 225",
        "Hong Kong 50",
        "Europe 50",
        "Swiss 20",
        "Spain 35",
        "Netherlands 25",
        "US SP 500",
        "US Tech 100",
        "Wall Street 30",
        "US Mid Cap 400",
        "US Small Cap 2000",
    ),
}


def one(symbol: str, interval: str) -> tuple[str, str, int, str]:
    try:
        bars = seqlab.cache(symbol, interval)
    except seqlab.Gone as exc:
        return symbol, interval, 0, f"gone: {exc}"
    except Exception as exc:  # noqa: BLE001 - reported per symbol, never fatal
        return symbol, interval, 0, f"failed: {exc}"
    return symbol, interval, len(bars.get("time", ())), "ok"


def main() -> None:
    jobs = [
        (symbol, interval)
        for group in WANTED.values()
        for symbol in group
        for interval in FRAMES
    ]
    print(f"{len(jobs)} pulls over {WORKERS} workers, frames {FRAMES}\n")
    started = time.time()
    got = {}
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = [pool.submit(one, s, i) for s, i in jobs]
        for future in as_completed(futures):
            symbol, interval, count, note = future.result()
            got[(symbol, interval)] = (count, note)
            print(f"  {symbol:<22}{interval:>5}{count:>9,}  {note}")
    print(f"\n{time.time() - started:.0f}s")
    print(f"{'group':<10}{'wanted':>8}{'landed':>8}{'bars, median':>14}")
    for label, group in WANTED.items():
        counts = [
            got.get((s, i), (0, ""))[0] for s in group for i in FRAMES
        ]
        landed = [c for c in counts if c > 0]
        middle = sorted(landed)[len(landed) // 2] if landed else 0
        print(f"{label:<10}{len(counts):>8}{len(landed):>8}{middle:>14,}")
    missing = [f"{s} {i}" for (s, i), (c, _) in got.items() if c == 0]
    if missing:
        print(f"\nnot served: {missing}")


if __name__ == "__main__":
    sys.exit(main())
