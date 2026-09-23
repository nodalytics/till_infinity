"""Trade the break instead of the hold: probability x magnitude x hold time.

Run from the repository root:  python research/harness/break_trade.py

The operator's construction, and it is the missing half of `learning/breaking.py`. That model
already publishes `break_probability` at AUC 0.658 and its own docstring says why it decides
nothing:

> *A break rate is not money: what it is worth depends on the size of what follows and the cost
> of being wrong, which is the arithmetic research/paying.md holds direction to and which
> nothing has yet held this to.*

So this holds it to that arithmetic. Three factors, all three measurable from the same journal
rows, and the operator named each one in turn:

1. **probability** - `P(break)`, which `Breaks` already scores;
2. **magnitude** - how far the break runs, because a coin flip on a big move beats a sure thing
   on a small one;
3. **hold time** - `E[tau]`, which `overshoot_theory.py` proved is not a detail but a *factor*:
   `E[P&L] = m = mu E[tau]`. Expectancy is drift multiplied by time in the position.

## Why trading the break is not the same trade inverted

A level call bets the level holds. Breaking bets it does not. Those are the same bet with
opposite signs, so the *directional* halves cancel and only two things distinguish them: the
cost, paid either way, and **the path**. That second one is not symmetric, and it is the whole
subtlety here.

`trap` is the reason. A trap is a failed break - price pushes through, traps whoever followed
it, and comes back - so it settles as a **hold** while spending part of its life on the break
side. A hold-direction trade is stopped out by exactly the excursion that a break-direction
trade needs. 43,102 of these rows are traps against 31,721 clean breaks, so the path is not a
correction to this study, it is larger than the effect.

## What makes the 1m case different, and it is the whole reason this is worth running

`breaking.py` records `interval_log` as the largest single separator in the book - break rate by
the timeframe the level was drawn on, over 126,296 resolutions:

    1m 57.9%   3m 26.8%   5m 20.4%   15m 12.8%   30m 2.8%   1h 1.4%   2h 0.0%   4h 4.3%

Monotone and fortyfold. **On a 1m level the break is the majority outcome.** A desk that trades
1m levels in the hold direction is taking the wrong side of a 58/42 split, and the live record
says exactly that: `trading-scaling.md` has 1m at **-7.75 per close over 47 closes**, t = -2.29,
with 3m and 5m also individually negative and the ordering monotone in the timeframe.

Those two facts have never been put next to each other. If they are the same fact, then the fix
for the desk's 1m losses is not to stop trading 1m - it is to **stop trading 1m levels as
holds**. That is the hypothesis this file exists to kill or confirm.

## The causality problem this fixes, and the one it cannot

`force.md` measured its AUC 0.658 on touches that resolved **between 300 and 1,800 seconds**,
because outside that band the question is definitional - a touch resolving inside a minute
resolves the way its side implies 100.0% of the time. That band is a condition on the future.
At order time nobody knows how long a touch will take, so an AUC measured inside it is not an
AUC a desk can earn.

**Predicting the hold time is what removes that condition**, which is why the operator's third
factor is not a refinement. So this file measures over **every** resolved touch, uses the band
only as a labelled cut for comparison against the published number, and asks directly whether
`seconds` is forecastable from what is known when the touch opens.

What it cannot fix: these are *level resolutions*, not trades. Nothing here has a stop, and
`barrier-geometry-is-irrelevant.md` derived that expectancy is drift over the holding period
regardless of geometry - which is the licence to score a signed move rather than a barrier race.
The gap that remains is that a real stop would truncate the losers, and `adverse_vol` is the
only handle on that.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import statistics as st
from collections import defaultdict
from pathlib import Path

#: Outcomes that mean the level held. `trap` belongs here and was grouped with breaks in every
#: number `force.md` first published - it is a *failed* break, and the correction moved the
#: base rate from 55.6% to 32.3%.
HELD = ("reject", "backcheck", "trap")
BROKE = ("break",)

#: Round trip in volatility units. `spread_cost.py` measured 0.020 TR a leg on FX and metals;
#: a true range and one volatility unit are the same order, so this is the honest charge and
#: the number that has ended every other candidate in this repository.
COST = 0.040

#: The band `force.md` conditioned on, kept only so its published figure can be reproduced and
#: compared against the unconditional one.
BAND = (300.0, 1800.0)

#: Timeframes in order, so tables read fast to slow rather than alphabetically.
ORDER = ("1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "daily", "1d", "weekly", "1w")

#: Features known when the touch opens. `push_vol` is **not** here: it is signed by the outcome,
#: which is the trap `trend.py` names - "a quantity signed by the outcome was scored against the
#: outcome". It is the target of the magnitude question, never an input to it.
CAUSAL = ("approach_vol", "depth_vol", "slowing", "slope", "prior_slope", "strength", "experience")


def load(where: Path) -> list[dict]:
    out = []
    with gzip.open(where, "rt") as handle:
        for line in handle:
            row = json.loads(line)
            if row.get("outcome") in HELD + BROKE:
                out.append(row)
    return out


def num(row: dict, name: str) -> float | None:
    got = row.get(name)
    return float(got) if isinstance(got, (int, float)) else None


def auc(pairs: list[tuple[float, bool]]) -> float:
    """Rank AUC with ties averaged. 0.5 is no separation."""
    scored = sorted(pairs, key=lambda kv: kv[0])
    pos = sum(1 for _s, b in scored if b)
    neg = len(scored) - pos
    if not pos or not neg:
        return 0.5
    total = 0.0
    i = 0
    rank = 1
    while i < len(scored):
        j = i
        while j + 1 < len(scored) and scored[j + 1][0] == scored[i][0]:
            j += 1
        mean_rank = rank + (j - i) / 2.0
        for k in range(i, j + 1):
            if scored[k][1]:
                total += mean_rank
        rank += j - i + 1
        i = j + 1
    return (total - pos * (pos + 1) / 2.0) / (pos * neg)


def err(values: list[float]) -> float:
    """Two standard errors of a mean. Plain, and the limitation is stated where it is used."""
    if len(values) < 2:
        return float("nan")
    return 2.0 * st.stdev(values) / math.sqrt(len(values))


def signed(row: dict) -> float | None:
    """The move in the **break** direction, in volatility units.

    `side` is where price sits relative to the level, so `above` is support and `below` is
    resistance. A reject off support pushes up and a break of support pushes down, which is
    what `force.md`'s outcome-by-side table says and what the sign of `push_vol` is checked
    against below rather than assumed.
    """
    push = num(row, "push_vol")
    if push is None:
        return None
    side = str(row.get("side") or "")
    if side == "above":
        # Support: the break direction is down, so a downward push is a gain for the break.
        return -push
    if side == "below":
        return push
    return None


def table(rows: list[dict], label: str, cost: float) -> None:
    by = defaultdict(list)
    for row in rows:
        by[str(row.get("interval") or "?")].append(row)

    print(f"\n{label}")
    print(
        f"  {'tf':>6}{'n':>8}{'break':>8}{'m break':>9}{'m hold':>8}"
        f"{'p*m brk':>9}{'p*m hold':>10}{'break net':>11}{'+/-':>7}"
        f"{'hold net':>10}{'tau brk':>9}{'tau hold':>9}"
    )
    for name in ORDER:
        seen = by.get(name)
        if not seen or len(seen) < 200:
            continue
        broke = [r for r in seen if r["outcome"] in BROKE]
        held = [r for r in seen if r["outcome"] in HELD]
        if len(broke) < 30 or len(held) < 30:
            continue
        p = len(broke) / len(seen)
        m_b = [abs(v) for r in broke if (v := signed(r)) is not None]
        m_h = [abs(v) for r in held if (v := signed(r)) is not None]
        if len(m_b) < 30 or len(m_h) < 30:
            continue
        mb, mh = st.mean(m_b), st.mean(m_h)
        # The break trade earns the break's move when it breaks and pays the hold's move when
        # it does not - and the hold trade is the exact mirror. Both are charged the round trip.
        moves = [v for r in seen if (v := signed(r)) is not None]
        brk_net = st.mean(moves) - cost
        hold_net = -st.mean(moves) - cost
        tau_b = st.median([s for r in broke if (s := num(r, "seconds")) is not None] or [0.0])
        tau_h = st.median([s for r in held if (s := num(r, "seconds")) is not None] or [0.0])
        mark = ""
        band = err(moves)
        if brk_net > band:
            mark = "  <- break pays"
        elif hold_net > band:
            mark = "  <- hold pays"
        print(
            f"  {name:>6}{len(seen):>8,}{p:>8.1%}{mb:>9.2f}{mh:>8.2f}"
            f"{p * mb:>9.2f}{(1 - p) * mh:>10.2f}"
            f"{brk_net:>+11.3f}{band:>7.3f}{hold_net:>+10.3f}"
            f"{tau_b:>9.0f}{tau_h:>9.0f}{mark}"
        )


#: Elapsed-time cuts for the hazard, in seconds.
CUTS = (0, 30, 60, 120, 300, 600, 1200, 1800, 3600, 7200)


def hazard(rows: list[dict]) -> None:
    """P(break | the touch is *still open* at t) - and this one is reachable at order time.

    **This is the finding this file exists for, and it is not the one it set out to test.**

    Every other number here conditions on the realised resolution, which no desk knows when it
    places an order. Elapsed time does not: at 300 seconds into an unresolved touch you know
    you are 300 seconds in. And "resolution took at least t" and "still open at t" are the same
    event, so the forward probability below is one a live clock can act on.

    The mechanism is not mysterious and does not need to be. A break has to travel through the
    zone before it travels past it, so it is the slower outcome by construction - `tau` medians
    run 4x to 12x longer for breaks than for holds. That explains the effect rather than
    explaining it away: the forward probability is still the forward probability.

    What to read: the cut where each row crosses 50% lands at roughly **five to seven bars of
    the level's own timeframe** - 300s on 1m, ~1,200s on 5m, ~3,600s on 15m, ~7,200s on 30m.
    A level that has not resolved in five of its own bars is more likely to break than to hold,
    on every timeframe measured, and that single rule is scale-free.
    """
    print("\n5. P(break | still open at t) - the one conditional a live clock can act on")
    print(f"   {'tf':>5}" + "".join(f"{c:>8}" for c in CUTS) + f"{'n':>10}{'50% at':>9}")
    for name in ORDER:
        have = [
            r
            for r in rows
            if r.get("interval") == name and (s := num(r, "seconds")) is not None and s >= 0
        ]
        if len(have) < 500:
            continue
        print(f"   {name:>5}", end="")
        crossed = ""
        for cut in CUTS:
            sub = [r for r in have if num(r, "seconds") >= cut]
            # A cut with too few left says nothing; an empty tail would otherwise print a
            # confident number off a dozen rows, which is how this repository has been fooled.
            if len(sub) < 200:
                print(f"{'-':>8}", end="")
                continue
            p = sum(1 for r in sub if r["outcome"] in BROKE) / len(sub)
            if p >= 0.5 and not crossed:
                crossed = f"{cut}s"
            print(f"{p:>8.1%}", end="")
        print(f"{len(have):>10,}{crossed:>9}")
    print(
        "   Rows thin out to the right, so a `-` is "
        '"fewer than 200 touches left" and not zero.\n'
        "   The 50% column is the actionable number: past it, the level's own directional call\n"
        "   is the minority outcome and `Breaks` should be overruling it rather than reporting."
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--where", default=".secrets/journal/touches.jsonl.gz")
    ap.add_argument("--cost", type=float, default=COST)
    args = ap.parse_args()

    rows = load(Path(args.where).expanduser())
    print(f"{len(rows):,} resolved touches\n")

    # 0. The sign convention, checked rather than assumed - this is the error that has been
    #    made twice in this repository and it invalidates everything downstream of it.
    print("0. sign convention check: share of pushes that are positive in the break direction")
    for side in ("above", "below"):
        for group, name in ((BROKE, "break"), (HELD, "held")):
            got = [
                v
                for r in rows
                if r.get("side") == side and r["outcome"] in group and (v := signed(r)) is not None
            ]
            if got:
                share = sum(1 for v in got if v > 0) / len(got)
                print(f"   side={side:<6} {name:<6} n={len(got):>7,}  positive {share:>6.1%}")
    print(
        "   a break should be almost all positive and a hold almost all negative; anything\n"
        "   near 50% means `side` does not mean what `signed()` assumes it means\n"
    )

    # 1. The headline: is the break the side to take, per timeframe?
    table(
        rows,
        "1. every resolved touch, unconditional - the population a desk actually faces",
        args.cost,
    )

    banded = [r for r in rows if (s := num(r, "seconds")) is not None and BAND[0] <= s < BAND[1]]
    table(
        banded,
        f"2. the {BAND[0]:.0f}-{BAND[1]:.0f}s band force.md conditioned on - NOT reachable at "
        "order time, shown for comparison",
        args.cost,
    )

    # 3. Period split, run before anything is believed.
    mid = sorted(r["time"] for r in rows)[len(rows) // 2]
    table([r for r in rows if r["time"] < mid], "3a. first half", args.cost)
    table([r for r in rows if r["time"] >= mid], "3b. second half", args.cost)

    # 4. Is the magnitude forecastable, and is the hold time?
    print("\n4. are the other two factors forecastable from what is known when the touch opens?")
    print(f"   {'feature':<14}{'n':>9}{'AUC break':>11}{'r with |move|':>15}{'r with tau':>12}")
    for name in CAUSAL:
        have = [r for r in rows if num(r, name) is not None]
        pairs = [(num(r, name), r["outcome"] in BROKE) for r in have]
        if len(pairs) < 1000:
            continue
        got = auc(pairs)

        # `have` and `name` bound as defaults: a closure over a loop variable reads
        # whatever the last iteration left, which is a bug class rather than a style note.
        def corr(target, have=have, name=name) -> float:
            xs, ys = [], []
            for r in have:
                t = target(r)
                if t is not None:
                    xs.append(num(r, name))
                    ys.append(t)
            if len(xs) < 1000 or st.stdev(xs) == 0 or st.stdev(ys) == 0:
                return float("nan")
            mx, my = st.mean(xs), st.mean(ys)
            cov = sum((a - mx) * (b - my) for a, b in zip(xs, ys, strict=True)) / len(xs)
            return cov / (st.pstdev(xs) * st.pstdev(ys))

        mag = corr(lambda r: abs(v) if (v := signed(r)) is not None else None)

        def held_for(row: dict) -> float | None:
            # Log seconds, because resolution times span four orders of magnitude and a
            # correlation on the raw scale would be a statement about the slowest few.
            secs = num(row, "seconds")
            return math.log1p(secs) if secs is not None and secs >= 0 else None

        tau = corr(held_for)
        print(f"   {name:<14}{len(pairs):>9,}{got:>11.4f}{mag:>15.3f}{tau:>12.3f}")
    print(
        "   AUC is the probability factor, already known. The two columns after it are the\n"
        "   **new** question: a feature that predicts how far and how long is worth more than\n"
        "   one that only predicts which way, because expectancy is the product of all three."
    )

    hazard(rows)

    print(
        f"\n  Every `net` column is charged {args.cost:.3f} volatility units for the round trip.\n"
        "  `+/-` is two plain standard errors and is **too narrow**: touches on one feed and\n"
        "  interval overlap in time, so the honest interval is a block bootstrap and these\n"
        "  rows are not independent. Treat a result inside two of these as nothing.\n"
        "\n  Read 3a against 3b before the headline. An effect in one half only is decayed,\n"
        "  which is what killed the directional-efficiency candidate."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
