"""On Boom and Crash the stop is on the side price cannot walk to, so it gaps.

The tick shape measured by `genspike.py` is stark enough to change what a stop
means. On `boom_500_index`, 84,506 of 84,702 ticks are **down** and 162 are up -
and 160 of those up ticks are spikes. Boom's price is monotone decreasing except
where it jumps.

So for a short on Boom, a stop placed above entry can only ever be reached by a
spike, and a spike is a single tick of 3-12 price units against a grind step of
0.009. The stop is therefore never *walked* to and always *jumped* over. Its
distance stops being the risk: the risk is wherever the spike lands.

That matters for more than Boom. Every position on this book is sized off its
stop distance - `research/stops.md` reads stops as the whole loss and
`research/giveback.md` prices the trail against the stop - and a risk model that
takes the stop distance as the loss is understating the loss on this family by
whatever the gap is worth. This measures the gap.

## What is measured

Entries every `STRIDE` ticks on 24 hours of tick data, both directions, a stop
at `D` and a target at a multiple of it, walked forward tick by tick with the
quoted spread charged on entry and exit. Recorded per trade:

* **intended R** - the trade's own risk, what the sizing assumed;
* **realised R** - what actually came back, at the price the stop was crossed at;
* **slippage** - realised minus intended on the losers, which is the whole point.

## What would count as failure, written before running

* **The gap claim fails** if the mean slippage on stopped trades is near zero -
  that is, if stops fill near where they are placed.
* **The claim is trivial rather than interesting** if it holds on the control
  too. `volatility_75_index` has no spike mechanism, so its stops should fill
  close to their level, and if they do not, the fill rule is wrong rather than
  the instrument.
* **Any expectancy found is not a finding** unless it survives both halves of
  the day and clears the spread.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import statistics as st

DATA = os.environ.get("DATA", os.path.expanduser("~/till_infinity/data"))
DB = os.environ.get("DB", os.path.join(DATA, "research.db"))
OUT = os.environ.get("OUT", os.path.expanduser("~/till_infinity/logs/genstop.json"))

FEEDS = ["boom_300_index", "boom_500_index", "boom_1000_index",
         "crash_300_index", "crash_500_index", "crash_1000_index",
         "volatility_75_index", "step_index"]

STRIDE = int(os.environ.get("STRIDE", "10"))  # kept for reference; entries are sequential
MAX_TICKS = int(os.environ.get("MAX_TICKS", "7200"))
#: Stop distances, in multiples of the quoted spread. Expressing them in spreads
#: rather than in points keeps the comparison across instruments honest -
#: `research/catalogue.md` makes the same argument about volatility units.
STOPS = (5.0, 10.0, 25.0, 50.0)
TARGETS = (1.0, 2.0, 3.0)


def ticks(conn, feed: str):
    rows = conn.execute(
        "SELECT ts, bid, ask FROM ticks WHERE feed=? ORDER BY ts ASC", (feed,)
    ).fetchall()
    return [
        ((float(b) + float(a)) / 2.0, float(a) - float(b))
        for _, b, a in rows
        if b is not None and a is not None and b > 0
    ]


def run(mids: list[float], spread: float, side: int, stop_d: float, target_mult: float) -> dict:
    """Walk every `STRIDE`-th entry forward to its stop, target or timeout.

    `side` is +1 for long, -1 for short. The spread is charged once, as the cost
    of round-tripping: entry is at the far side of the quote and the exit price
    is the mid, so one full spread is deducted from every trade's result. That
    is the `research/exiting.md` rule - an edge smaller than the cost of taking
    it is not an edge - applied before anything is read.
    """
    n = len(mids)
    tgt_d = stop_d * target_mult
    rows = []
    # Sequential entries: the next trade starts where the last one ended, so no
    # two trades share a tick. Overlapping entries every STRIDE ticks resolve on
    # the *same* spikes - on boom_500 there are 160 spikes in the day and 8,470
    # entries - and a standard error computed across them is meaningless. This
    # is the honest sample and it is the one the expectancy is read from.
    i = 0
    while i < n - 2:
        entry = mids[i]
        stop = entry - side * stop_d
        target = entry + side * tgt_d
        out = None
        for j in range(i + 1, min(i + 1 + MAX_TICKS, n)):
            p = mids[j]
            if side * (p - stop) <= 0:
                out = ("stop", p, j - i)
                break
            if side * (p - target) >= 0:
                out = ("target", p, j - i)
                break
        if out is None:
            out = ("timeout", mids[min(i + MAX_TICKS, n - 1)], MAX_TICKS)
        why, exit_p, held = out
        i += max(held, 1)
        gross = side * (exit_p - entry)
        net = gross - spread
        rows.append({
            "why": why,
            "gross_r": gross / stop_d,
            "net_r": net / stop_d,
            "held": held,
            # Slippage is signed the way a loss is: positive means the fill was
            # worse than the stop level by that many R.
            "slip_r": (-(gross + stop_d) / stop_d) if why == "stop" else 0.0,
        })
    if not rows:
        return {}
    stopped = [r for r in rows if r["why"] == "stop"]
    slips = [r["slip_r"] for r in stopped]
    nets = [r["net_r"] for r in rows]
    half = len(rows) // 2
    return {
        "n": len(rows),
        "stop_d": stop_d,
        "target_mult": target_mult,
        "side": side,
        "hit_target": sum(1 for r in rows if r["why"] == "target") / len(rows),
        "hit_stop": len(stopped) / len(rows),
        "timeout": sum(1 for r in rows if r["why"] == "timeout") / len(rows),
        "mean_net_r": st.fmean(nets),
        "se_net_r": st.pstdev(nets) / math.sqrt(len(nets)),
        "first_half_net_r": st.fmean([r["net_r"] for r in rows[:half]]) if half else float("nan"),
        "second_half_net_r": st.fmean([r["net_r"] for r in rows[half:]]) if half else float("nan"),
        "mean_slip_r": st.fmean(slips) if slips else float("nan"),
        "median_slip_r": st.median(slips) if slips else float("nan"),
        "max_slip_r": max(slips) if slips else float("nan"),
        "p90_slip_r": sorted(slips)[int(0.9 * len(slips))] if slips else float("nan"),
        "frac_slip_over_half_r": (sum(1 for s in slips if s > 0.5) / len(slips)) if slips else float("nan"),
        "mean_loss_r": st.fmean([r["gross_r"] for r in stopped]) if stopped else float("nan"),
        "median_held": st.median([r["held"] for r in rows]),
    }


def main() -> None:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    results = []
    for feed in FEEDS:
        rows = ticks(conn, feed)
        if len(rows) < 20_000:
            print(f"{feed}: {len(rows)} ticks, skipped", flush=True)
            continue
        mids = [m for m, _ in rows]
        spread = st.median([s for _, s in rows])
        for mult in STOPS:
            stop_d = mult * spread
            for tgt in TARGETS:
                for side in (+1, -1):
                    got = run(mids, spread, side, stop_d, tgt)
                    if got:
                        got.update({"feed": feed, "spread": spread, "stop_spreads": mult})
                        results.append(got)
        print(f"processed {feed} (spread {spread:g})", flush=True)

    with open(OUT, "w") as fh:
        json.dump(results, fh, indent=1, default=str)
    print(f"wrote {OUT}\n")

    print("=== stop slippage: how far past the stop the fill actually lands ===")
    print(f"{'feed':22s} {'side':5s} {'stop':>6s} {'tgt':>4s} {'n':>6s} {'stop%':>7s} "
          f"{'mean slip R':>12s} {'p90':>7s} {'max':>8s} {'>0.5R':>7s} {'mean loss R':>12s}")
    for r in results:
        if r["target_mult"] != 1.0:
            continue
        side = "long" if r["side"] > 0 else "short"
        print(f"{r['feed']:22s} {side:5s} {r['stop_spreads']:6.0f} {r['target_mult']:4.0f} "
              f"{r['n']:6d} {r['hit_stop']:7.4f} {r['mean_slip_r']:+12.4f} "
              f"{r['p90_slip_r']:+7.3f} {r['max_slip_r']:+8.3f} "
              f"{r['frac_slip_over_half_r']:7.4f} {r['mean_loss_r']:+12.4f}")

    print("\n=== expectancy, spread charged, split by half-day ===")
    print(f"{'feed':22s} {'side':5s} {'stop':>6s} {'tgt':>4s} {'n':>6s} {'tgt%':>7s} {'stop%':>7s} "
          f"{'net R':>9s} {'se':>8s} {'z':>7s} {'first':>8s} {'second':>8s}")
    for r in results:
        side = "long" if r["side"] > 0 else "short"
        z = r["mean_net_r"] / r["se_net_r"] if r["se_net_r"] else float("nan")
        print(f"{r['feed']:22s} {side:5s} {r['stop_spreads']:6.0f} {r['target_mult']:4.0f} "
              f"{r['n']:6d} {r['hit_target']:7.4f} {r['hit_stop']:7.4f} "
              f"{r['mean_net_r']:+9.4f} {r['se_net_r']:8.4f} {z:+7.2f} "
              f"{r['first_half_net_r']:+8.4f} {r['second_half_net_r']:+8.4f}")


if __name__ == "__main__":
    main()
