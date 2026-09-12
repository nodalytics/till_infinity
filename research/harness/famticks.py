"""Pull the tick history the families arm needs, once, and put it on disk.

**Ticks and not bars, because the object is a tick-level event.** Boom, Crash,
DEX and Jump are compound processes whose rate is quoted per tick; Step is a
lattice whose increment is one tick wide. A three-minute bar has already summed
a hundred and eighty of those increments and there is no undoing it. The bar
cache `seqcache.py` is warming is the right layer for the volatility and
direction arms of this study and the wrong layer for every characterisation in
`seqfamilies.py`, so this is a second warm and not a duplicate of the first.

**Sample sizes are set by the spike count, not by the hour count.** That is the
correction this file exists to make. `research/generators.md` measured the
Boom/Crash waiting time on twenty-four hours of ticks, which is 94 spikes on
Boom 1000 and 306 on Boom 300, and reported a coefficient of variation of 0.844
to 1.103 against a Poisson's 1.000. The standard error of a CV on 94 draws is
about 0.073. **The entire measured spread is two standard errors wide**, so the
published conclusion that the family is memoryless is a failure to reject at a
power that could not have rejected much. Three hundred thousand ticks is 330
spikes on Boom 1000 and six thousand on Boom 50, and that is a sample at which
the five tests in `seqlab.hazard` can say something.

Four workers, not eight. `seqcache.py` is already running eight against the same
terminal for five sibling arms, and `research/starving.md`'s lesson is that
research which degrades the feed everyone shares is not research that got a
result faster.

    ./.secrets/lab.sh run research/harness/famticks.py
"""

from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np

from research.harness import seqlab

#: Half of `seqcache.py`'s, for the reason in the docstring.
WORKERS = 4

#: How many ticks each family needs, and why that many.
#:
#: * **boom / crash / dex / jump** - 300,000. The binding constraint is the
#:   slowest member: Boom 1000 spikes once per thousand ticks, so this is ~300
#:   spikes, three times `generators.md`'s sample on that feed and enough that
#:   a KS statistic has a usable null band.
#: * **step** - 200,000. The object is a per-tick increment, so every tick is a
#:   draw; 200,000 pins `p(up)` to +-0.0011, which separates a 0.20 skew from a
#:   0.50 coin by two hundred standard errors and a 0.499 from a 0.500 by
#:   nothing at all. The second of those is the honest limit and is stated.
#: * **drift_switch** - 200,000. The regime is a bar-scale object and the ticks
#:   are here for the increment law and the dwell time in tick units.
#: * **range_break** - 120,000, and it is a replication and not a study.
#:   `research/deriving.md` already has the break rate at 86.6 and 178.9 minutes
#:   with CV 1.003 and 1.075 over sixty days, and `research/quantising.md` has
#:   the relaxation ladder. Re-running either on three days of ticks would be a
#:   worse measurement of a settled number.
WANT = {"boom": 300_000, "crash": 300_000, "dex": 300_000, "jump": 300_000,
        "step": 200_000, "drift_switch": 200_000, "range_break": 120_000}


def plan() -> list[tuple[str, int]]:
    """Every (symbol, target) pair, slowest family first.

    Ordered by descending target so the long pulls start while the pool is full
    rather than trailing behind the short ones - the usual scheduling point, and
    it matters here because one family's 300,000 is three of another's.
    """
    out = [(s, WANT[fam]) for fam, syms in sorted(seqlab.SYNTHETIC.items()) for s in syms]
    out.sort(key=lambda r: -r[1])
    return out


def one(job: tuple[str, int]) -> tuple[str, str, int, float]:
    symbol, want = job
    began = time.time()
    path = seqlab.TICK_CACHE / f"{seqlab._slug(symbol, 'tick')}.npz"
    if path.exists():
        got = np.load(path)
        if len(got["time"]) >= int(0.85 * want):
            return symbol, "cached", len(got["time"]), 0.0
    try:
        got = seqlab.tick_cache(symbol, want)
    except Exception as exc:  # noqa: BLE001 - one bad symbol must not stop the warm
        return symbol, f"failed: {str(exc)[:70]}", 0, time.time() - began
    n = len(got["time"])
    if n < 2:
        return symbol, "empty", 0, time.time() - began
    span = (got["time"][-1] - got["time"][0]) / 3600.0
    return symbol, f"{span:.0f}h", n, time.time() - began


def main() -> int:
    jobs = plan()
    total_want = sum(w for _, w in jobs)
    print(f"{len(jobs)} symbols, {total_want:,} ticks wanted")
    print(f"cache: {seqlab.TICK_CACHE}\n", flush=True)

    began = time.time()
    ok = bad = 0
    ticks = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(one, j): j for j in jobs}
        for i, future in enumerate(as_completed(futures), 1):
            symbol, how, n, secs = future.result()
            if n:
                ok += 1
                ticks += n
            else:
                bad += 1
            mark = "  " if n else " !"
            print(f"{mark} {i:3d}/{len(jobs)}  {symbol:26s} {n:8,} ticks  {how:>14s} "
                  f"{secs:5.0f}s  [{ticks:,} total, {(time.time()-began)/60:.1f}m]",
                  flush=True)

    print(f"\ndone in {(time.time() - began) / 60:.1f}m: {ok} symbols, "
          f"{bad} failed, {ticks:,} ticks on disk")
    return 1 if bad > len(jobs) // 4 else 0


if __name__ == "__main__":
    sys.exit(main())
