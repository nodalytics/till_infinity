"""The structurally convex bet, with no strategy in the way.

`research/convexity.md`, section on the synthetics. Boom and Crash are the same
generator with the sign reversed: **Boom grinds down and spikes up, Crash grinds
up and spikes down.** A position held in the spike direction therefore has a
bounded cost - the grind, which arrives in small regular pieces - and an
unbounded gain - the spike, which `spiking.md` measured as arriving once every
11.9 minutes on Boom 1000 with a waiting time whose coefficient of variation is
0.99 against a memoryless process's 1.00, meaning **nothing can call it**.

That is the cleanest convex bet available on this book, and it does not need a
model of anything. It needs only the side.

## Why this does not use the strategy's entries

`convexity.py` asks the same question through `sweep-aware`'s published calls,
and `spikeside.py` before it. Both inherit the strategy's level selection, its
timing and its refusals, and `instruments.md` records what that costs: the
buy-minus-sell gap came out with the **same sign on both families**, which the
hypothesis forbids - it needs opposite signs - and the finding was withdrawn as
a general long bias in the replay.

So this removes the strategy. Entries are placed on a **fixed clock**, at every
`hold`-th bar so that no two overlap, long and short alike, with a stop one
average-true-range wide and no target. There is nothing to select and nothing to
be biased by: if one side of Boom pays and the mirror side of Crash pays, that
is the generator, and if both families prefer the same side it is the replay.

## The controls, and they are the point

* **The mirror.** Boom and Crash are measured together and the answer is the
  *pair* of buy-minus-sell gaps. Opposite signs support a spike effect; the same
  sign on both is a direction bias in the harness and refutes it, exactly as it
  did in `instruments.md`.
* **The symmetric synthetics.** `volatility_*` and `step_index` come off the
  same broker and the same generator family with **no** one-sided jump. They
  should show no side preference at all. A gap there is a measurement artefact
  and invalidates the Boom and Crash gaps by the same amount.
* **Non-overlapping entries.** Each entry is a whole `hold` after the last, so
  the sample is not one long position counted many times.
* **A no-stop row.** The same entry held to the horizon with no stop and no
  target, which is the generator's own drift over that window and nothing else.
  **This is the row that decides whether any of the rest is real.** A stop
  truncates the spike: short Boom with a stop is short a jump whose loss is
  capped, and a replay that fills that stop *at the stop price* is paying a
  price a one-tick spike never offered. So if the no-stop row is flat and the
  stopped rows are not, the entire asymmetry was manufactured by an unfillable
  stop, and this harness has found a defect in itself rather than an edge.

## What would count as failure

* Boom and Crash prefer the **same** side - not a spike effect, and the second
  time this project would have found that.
* The symmetric synthetics also show a side preference - the harness is biased.
* The convex policy and the flat one give the same answer - the asymmetry is in
  the drift and not in the tail, which is a fact about the instrument and not an
  argument for convexity.
* No effect at any horizon - the generator's asymmetry is not reachable by a
  position, which is possible: a grind that pays for its own spike is a fair
  game by construction and this broker has no reason to publish an unfair one.

**That last is the honest prior.** A synthetic index is a random process the
house designed; the spike is compensated by the grind on purpose. This measures
whether the compensation is exact after costs, and the expected answer is that
it is, or that it is worse than exact by the spread.

Usage:
    JOURNAL=~/till_infinity/data/journal.db BARS=~/till_infinity/data/research.db \\
    python3 -m research.harness.convexspike
"""

from __future__ import annotations

import math
import os
import sqlite3
import statistics as st
from collections import defaultdict

from research.harness.sweepregimes import BARS, JOURNAL, bars_for, spreads
from till_infinity.shared.replay import walk

#: Bars of history the stop is sized from, all of it strictly before the entry.
LOOKBACK = int(os.environ.get("LOOKBACK", "240"))
#: The stop is `sqrt(hold)` average 1-minute ranges wide, which is the scale a
#: random walk covers in `hold` minutes. A fixed one-minute range against a
#: 1,440-bar hold is a stop that is hit with certainty and an R whose
#: denominator is a thousand times smaller than its numerator - the first
#: version of this harness did that and reported mean R above +10.
STOP_ATRS = float(os.environ.get("STOP_ATRS", "1.0"))
MIN_N = int(os.environ.get("MIN_N", "60"))
SPLIT = float(os.environ.get("SPLIT", "0.6"))
#: Horizons, in 1m bars. Entries are spaced one horizon apart, so the trades at
#: a given horizon never overlap.
HOLDS = (30, 120, 480, 1440)

FAMILIES = {
    "boom_300_index": "boom",
    "boom_500_index": "boom",
    "boom_1000_index": "boom",
    "crash_300_index": "crash",
    "crash_500_index": "crash",
    "crash_1000_index": "crash",
    # The symmetric control: the same broker, the same synthetic family, no
    # one-sided jump in the generator.
    "volatility_10_index": "symmetric",
    "volatility_25_index": "symmetric",
    "volatility_50_index": "symmetric",
    "volatility_75_index": "symmetric",
    "volatility_100_index": "symmetric",
    "step_index": "symmetric",
}

#: Tiny stop, no target, wide trail - the same shape `convexity.py` tests, so
#: the two can be read against each other.
CONVEX = {"stop_mult": 0.5, "target_mult": 1000.0, "trail_risk": 3.0, "protect_r": 0.0}
#: One ATR stop, no target, nothing trailing: the flat bet, for separating an
#: asymmetry in the *drift* from one in the *tail*.
FLAT = {"target_mult": 1000.0, "trail_vol": 0.0, "protect_r": 0.0}
POLICIES = {"flat": FLAT, "convex": CONVEX}
#: `no_stop` is not a `walk` policy - it is computed from the bars directly, so
#: no stop rule of any kind can touch it - but it is reported in the same table.
ROWS = ("no_stop", "flat", "convex")


def quantile(values, q: float) -> float:
    got = sorted(values)
    return got[min(len(got) - 1, int(q * len(got)))] if got else float("nan")


def atr(rows, index: int) -> float:
    """Mean bar range over the `LOOKBACK` bars ending before `index`.

    Strictly before. A range that includes the entry bar is a look-ahead, and
    this project has two of those on record from one morning.
    """
    lo = max(0, index - LOOKBACK)
    if index - lo < LOOKBACK // 2:
        return 0.0
    spans = [r[2] - r[3] for r in rows[lo:index] if r[2] is not None and r[3] is not None]
    return math.fsum(spans) / len(spans) if spans else 0.0


def run() -> None:
    jn = sqlite3.connect(f"file:{JOURNAL}?mode=ro", uri=True, timeout=300.0)
    spread = spreads(jn)
    jn.close()
    conn = sqlite3.connect(f"file:{BARS}?mode=ro", uri=True, timeout=300.0)

    print("=" * 78)
    print("THE CONVEX SIDE OF A ONE-SIDED GENERATOR, WITH NO STRATEGY IN THE WAY")
    print("=" * 78)
    print(f"  stop: one {LOOKBACK}-bar average range, from bars strictly before entry")
    print(f"  entries: every `hold` bars, so trades at one horizon never overlap")
    print(f"  stop width: {STOP_ATRS} x sqrt(hold) average ranges, so it scales with the horizon")
    print(f"  {len(HOLDS)} horizons x {len(ROWS)} rows x 2 sides x 3 families")
    print(f"  = {len(HOLDS) * len(ROWS) * 6} comparisons\n")

    loaded = {}
    for feed in FAMILIES:
        rows, _stamps = bars_for(conn, feed)
        if len(rows) >= 5000:
            loaded[feed] = rows
        else:
            print(f"  {feed}: only {len(rows)} bars, skipped")
    conn.close()
    print(f"  {len(loaded)} feeds with bars\n")

    for hold in HOLDS:
        got: dict[tuple[str, str, str], list[float]] = defaultdict(list)
        per_feed: dict[tuple[str, str, str], list[float]] = defaultdict(list)
        for feed, rows in loaded.items():
            family = FAMILIES[feed]
            bps = spread.get(feed, 0.0)
            width = STOP_ATRS * math.sqrt(hold)
            start = LOOKBACK
            while start + hold < len(rows):
                unit = atr(rows, start)
                level = rows[start][1]
                if unit > 0 and level and level > 0:
                    cost = level * bps / 10_000.0
                    risk = width * unit
                    close = rows[start + hold - 1][4]
                    for up in (True, False):
                        side = "buy" if up else "sell"
                        trade = {
                            "up": up,
                            "unit": unit,
                            "level": level,
                            "risk_vol": width,
                            "push_vol": width,
                            "context": {},
                        }
                        for name, policy in POLICIES.items():
                            answer = walk(rows, start, trade, cost=cost, hold=hold, policy=policy)
                            if answer is not None:
                                got[(family, side, name)].append(answer[0])
                                per_feed[(feed, side, name)].append(answer[0])
                        # The no-stop row, computed straight from the bars: in
                        # at the open plus half the spread, out at the horizon's
                        # close minus it, in the same risk units as the rest.
                        if close is not None and risk > 0:
                            half = cost / 2 if up else -cost / 2
                            entry = level + half
                            left = close - half
                            move = (left - entry) if up else (entry - left)
                            got[(family, side, "no_stop")].append(move / risk)
                            per_feed[(feed, side, "no_stop")].append(move / risk)
                start += hold

        print("=" * 78)
        print(f"HOLD {hold} BARS  (entries every {hold} bars, non-overlapping)")
        print("=" * 78)
        for name in ROWS:
            print(f"\n  under {name}:")
            print(
                f"    {'family':<10s} {'side':<5s} {'n':>6s} {'mean R':>9s} {'median':>9s} "
                f"{'win':>7s} {'p95':>9s} {'max':>9s}"
            )
            for family in ("boom", "crash", "symmetric"):
                for side in ("buy", "sell"):
                    rs = got.get((family, side, name), [])
                    if len(rs) < MIN_N:
                        continue
                    # The spike runs *with* a boom buy and *with* a crash sell.
                    convexly = (family == "boom" and side == "buy") or (
                        family == "crash" and side == "sell"
                    )
                    mark = "  <- spike with" if convexly else ""
                    print(
                        f"    {family:<10s} {side:<5s} {len(rs):6d} {st.fmean(rs):+9.3f} "
                        f"{st.median(rs):+9.3f} {sum(1 for r in rs if r > 0) / len(rs):6.1%} "
                        f"{quantile(rs, 0.95):+9.3f} {max(rs):+9.2f}{mark}"
                    )
            gaps = {}
            for family in ("boom", "crash", "symmetric"):
                buys = got.get((family, "buy", name), [])
                sells = got.get((family, "sell", name), [])
                if len(buys) >= MIN_N and len(sells) >= MIN_N:
                    gaps[family] = st.fmean(buys) - st.fmean(sells)
                    print(f"    {family}: buy - sell = {gaps[family]:+.3f}R")
            if name != "no_stop" and "boom" in gaps and "crash" in gaps:
                drift = gaps.get("symmetric", 0.0)
                boom, crash = gaps["boom"] - drift, gaps["crash"] - drift
                verdict = (
                    "OPPOSITE signs - consistent with the spike"
                    if boom * crash < 0
                    else "SAME sign - a direction bias, not the spike"
                )
                print(
                    f"    net of the symmetric control ({drift:+.3f}R): "
                    f"boom {boom:+.3f}  crash {crash:+.3f}   {verdict}"
                )
                print(
                    f"    the hypothesis needs boom positive and crash negative: "
                    f"{'it does' if boom > 0 > crash else 'it does not'}"
                )

        if hold == HOLDS[0]:
            print("\n  per feed, convex, so a family is not one instrument:")
            print(f"    {'feed':<22s} {'side':<5s} {'n':>6s} {'mean R':>9s} {'p95':>9s}")
            for (feed, side, name), rs in sorted(per_feed.items()):
                if name == "convex" and len(rs) >= MIN_N:
                    print(
                        f"    {feed:<22s} {side:<5s} {len(rs):6d} {st.fmean(rs):+9.3f} "
                        f"{quantile(rs, 0.95):+9.3f}"
                    )

    print("\n" + "=" * 78)
    print("The row that decides it is `no_stop`: the generator's own drift over")
    print("the horizon with nothing truncating it. A flat no-stop row beside a")
    print("large stopped one says the asymmetry is the stop truncating a jump")
    print("that a real fill would not have truncated, not an edge.")
    print("")
    print("Failure conditions: both families preferring the same side; the")
    print("symmetric synthetics showing a side preference; convex and flat")
    print("agreeing, which would put the asymmetry in the drift; or nothing at")
    print("any horizon, which is what a fairly-priced generator looks like.")


if __name__ == "__main__":
    run()
