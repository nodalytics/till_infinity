"""Pull every bar the sequence study needs, once, and put it on disk.

Six arms run in parallel on this data. If each pulls its own, one terminal
serves six concurrent floods of fifty-thousand-bar transfers, the 404 that
`seqlab.fetch` retries around becomes common rather than rare, and six arms
disagree about what the data was because they fetched it at different minutes.

Resumable by design: a symbol already on disk is skipped, so this can be
re-run after a drop without re-pulling what it already has, and a later arm
that wants one more timeframe costs only that timeframe.

Bounded concurrency rather than none. Eight workers is enough to turn hours
into half an hour and few enough that the terminal is never the thing that
breaks - it is the same terminal the live desk trades through, and the lesson
of `research/starving.md` is that research which degrades production is not
research that got a result faster.

    ./.secrets/lab.sh run research/harness/seqcache.py
"""

from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from research.harness import seqlab

#: Eight, for the reason in the docstring.
WORKERS = 8


def plan() -> list[tuple[str, str]]:
    """Every (symbol, timeframe) this study needs, priced arm by arm.

    Ordered so the arms that are already written get their data first: the
    Volatility family and the real controls, then the rest of the book. A drop
    part way through therefore leaves the commissioned work runnable.
    """
    groups = [
        seqlab.VOLATILITY,
        seqlab.SPOT_UP,
        seqlab.REAL,
        *[v for _, v in sorted(seqlab.SYNTHETIC.items())],
    ]
    out: list[tuple[str, str]] = []
    for group in groups:
        for symbol in group:
            for interval in seqlab.GRID:
                out.append((symbol, interval))
    return out


def one(job: tuple[str, str]) -> tuple[str, str, str, int]:
    symbol, interval = job
    path = seqlab.CACHE / f"{seqlab._slug(symbol, interval)}.npz"
    if path.exists():
        return symbol, interval, "cached", 0
    try:
        got = seqlab.cache(symbol, interval)
        return symbol, interval, "pulled", len(got["close"])
    except Exception as exc:  # noqa: BLE001 - one bad symbol must not stop the warm
        return symbol, interval, f"failed: {str(exc)[:70]}", 0


def main() -> None:
    jobs = plan()
    print(f"{len(jobs):,} (symbol, timeframe) pairs across {len(seqlab.GRID)} timeframes")
    print(f"cache: {seqlab.CACHE}\n", flush=True)

    began = time.time()
    pulled = cached = failed = 0
    bars = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(one, j): j for j in jobs}
        for i, future in enumerate(as_completed(futures), 1):
            symbol, interval, how, n = future.result()
            if how == "pulled":
                pulled += 1
                bars += n
            elif how == "cached":
                cached += 1
            else:
                failed += 1
                print(f"  ! {symbol} {interval} {how}", flush=True)
            if i % 50 == 0 or i == len(jobs):
                rate = i / max(time.time() - began, 1e-9)
                left = (len(jobs) - i) / max(rate, 1e-9) / 60.0
                print(
                    f"  {i:,}/{len(jobs):,}  pulled {pulled:,}  cached {cached:,} "
                    f"failed {failed:,}  {bars:,} bars  ~{left:.1f}m left",
                    flush=True,
                )

    print(
        f"\ndone in {(time.time() - began) / 60:.1f}m: "
        f"{pulled:,} pulled, {cached:,} already there, {failed:,} failed, {bars:,} bars"
    )
    return 0 if failed < len(jobs) // 4 else 1


if __name__ == "__main__":
    sys.exit(main() or 0)
