"""Would a lower break-even trigger raise the payoff ratio, or just scratch the winners?

    python research/harness/breakeven.py --closes .secrets/journal/closes.jsonl.gz

## Why this question

The desk's problem is not its win rate. Over the closed trades it records, it wins
more often than it loses and still barely clears zero, because **mean win is smaller
than mean loss**. Break-even, trailing and scale-out exist to fix exactly that, and
all three arm at `break_even_at`/`scale_out_at` = **1.0R** - while only about a fifth
of closes ever reach 1.0R. So four trades in five get no protection at all, by
design, and the losers run to the full stop.

Observed on the live desk over 24 hours: zero stop moves, with the skip reasons
naming excursions of +0.36R, -0.18R and -0.66R against a 1.00R trigger.

## What can and cannot be measured from this record

Each closed trade journals `best_r` (its maximum favourable excursion), `adverse_r`
(its maximum adverse one) and `r_multiple` (where it finished). That is enough to say
**which trades a trigger would arm**, which is the headline and is not in doubt.

It is **not** enough to settle what arming would have done, and the reason is
ordering. Break-even moves the stop to entry once the trade reaches `T`; the trade
is then scratched only if price comes back to entry **after** that. `best_r` and
`adverse_r` are scalars over the whole life, so a trade that went +1.2R, fell to
-0.3R, and recovered to +1.7R is indistinguishable here from one that went -0.3R
first and then straight to +1.7R. The first would have been scratched at 0; the
second untouched.

So this reports **bounds and a break-even fraction** rather than a point estimate:

* **the gain** is exact - every armed trade that finished negative would have exited
  at 0 instead, and a loser cannot be scratched into something worse;
* **the cost** is bounded above by the whole of every armed winner, which assumes all
  of them retraced to entry and is deliberately absurd;
* **the decision number** is between them: what fraction of armed winners would have
  to be scratched for the change to break even. If that fraction is high, the change
  is safe; if it is low, it is a coin flip dressed as an improvement.

And one hard tightening, which `adverse_r` makes possible. A trade that **never went
below entry** cannot have been scratched by a stop sitting at entry, whatever the
ordering was. So armed winners split in two:

* `adverse_r <= 0` - untouchable. Break-even cannot have cost these anything.
* `adverse_r > 0` - the only candidates, and only some of those, since the dip may
  have come before the trigger armed.

That turns the absurd upper bound into a real one, and it is the number to read.

Getting a point estimate still needs the price path per trade, which the journal does
not carry. That is a separate piece of work and this page does not pretend otherwise.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import statistics as st
from collections.abc import Iterator
from pathlib import Path

#: Triggers to test, in R. 1.0 is what production runs today.
TRIGGERS = (0.25, 0.5, 0.75, 1.0, 1.5)

#: Fewest trades before a cell is reported. A payoff ratio on a handful of trades is
#: an anecdote, and this folder has retracted enough of those.
MIN_TRADES = 100


def load(path: Path) -> Iterator[dict]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt") as handle:
        for raw in handle:
            line = raw.strip()
            if line and not line.startswith("#"):
                yield json.loads(line)


def usable(row: dict) -> bool:
    """A trade with the three numbers this study needs, all finite."""
    for key in ("best_r", "r_multiple"):
        value = row.get(key)
        if not isinstance(value, int | float) or not math.isfinite(value):
            return False
    return True


def payoff(rs: list[float]) -> tuple[float, float, float, float]:
    """`(win_rate, mean_win, mean_loss, payoff_ratio)` over final R multiples."""
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r < 0]
    if not wins or not losses:
        return (float("nan"),) * 4
    rate = len(wins) / len(rs)
    mean_win, mean_loss = st.fmean(wins), abs(st.fmean(losses))
    return (rate, mean_win, mean_loss, mean_win / mean_loss)


def applied(rows: list[dict], trigger: float) -> dict[str, float]:
    """What a break-even at `trigger` would have done, with the cost bounded.

    Armed losers exit at 0 - exact, since a loser cannot be scratched into something
    worse. Armed winners are split by whether they ever traded below entry, because
    only those can have been scratched by a stop sitting there.
    """
    after: list[float] = []
    losers = winners = exposed = 0
    saved = exposed_cost = safe_win = 0.0
    for row in rows:
        best, final = float(row["best_r"]), float(row["r_multiple"])
        adverse = float(row.get("adverse_r") or 0.0)
        if best < trigger:
            after.append(final)
            continue
        if final < 0:
            losers += 1
            saved += -final
            after.append(0.0)
            continue
        winners += 1
        if adverse > 0.0:
            exposed += 1
            exposed_cost += final
        else:
            safe_win += final
        after.append(final)
    return {
        "after": after,
        "losers": losers,
        "winners": winners,
        "exposed": exposed,
        "saved": saved,
        "exposed_cost": exposed_cost,
        "safe_win": safe_win,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--closes", default=".secrets/journal/closes.jsonl.gz")
    args = parser.parse_args()

    rows = [r for r in load(Path(args.closes)) if usable(r)]
    print(f"{len(rows):,} closed trades with an excursion recorded")
    if len(rows) < MIN_TRADES:
        print(f"  under {MIN_TRADES}; not reporting a payoff ratio on this")
        return 1

    base = [float(r["r_multiple"]) for r in rows]
    rate, mw, ml, ratio = payoff(base)
    need = (1 - rate) / rate if rate else float("nan")
    print("\n=== as it trades today")
    print(f"  win rate {100 * rate:.1f}%   mean win {mw:+.3f}R   mean loss {-ml:+.3f}R")
    print(f"  payoff ratio {ratio:.3f}   break-even needs {need:.3f}")
    print(f"  total {sum(base):+.1f}R   expectancy {st.fmean(base):+.4f}R per trade")

    print("\n=== how far trades actually get (the headline, and not in doubt)")
    bests = sorted(float(r["best_r"]) for r in rows)
    for t in TRIGGERS:
        n = sum(1 for b in bests if b >= t)
        print(f"  reached {t:4.2f}R : {n:5d} of {len(rows):,}  = {100 * n / len(rows):5.1f}%")
    p90 = bests[int(0.9 * len(bests))]
    print(f"  median best_r {st.median(bests):+.3f}R,  90th percentile {p90:+.3f}R")

    print("\n=== a break-even at each trigger")
    print(
        f"{'trig':>5} {'losers':>7} {'wins':>6} {'exposed':>8} {'gain':>8} "
        f"{'at risk':>8} {'worst':>8} {'scratch%':>9}"
    )
    print("-" * 66)
    for t in TRIGGERS:
        got = applied(rows, t)
        # The worst the change can do: the gain, less every exposed winner.
        worst = sum(got["after"]) - got["exposed_cost"]
        frac = (
            (got["saved"] / got["exposed_cost"] * 100.0)
            if got["exposed_cost"] > 0
            else float("inf")
        )
        print(
            f"{t:5.2f} {got['losers']:7d} {got['winners']:6d} {got['exposed']:8d} "
            f"{got['saved']:+8.1f} {-got['exposed_cost']:+8.1f} {worst:+8.1f} {frac:8.0f}%"
        )
    print(
        "\n  gain is exact: an armed loser exits at 0 and cannot do worse."
        "\n  exposed counts armed winners that traded below entry at some point - the only"
        "\n  ones a stop at entry could have scratched. 'at risk' is all of their R and"
        "\n  'worst' is the total if every one of them was scratched, which is still"
        "\n  pessimistic because a dip before the trigger armed costs nothing."
        "\n  scratch% is the share of exposed R that would have to be lost to give the"
        "\n  gain back; above 100% the change cannot lose."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
