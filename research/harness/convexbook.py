"""Is this book's money in the tail, and is the live desk cutting that tail off?

`research/convexity.md`, the live half. `convexity.py` is the replay half; this
is the part that cannot be simulated, and the folder's standing rule after two
look-aheads in one morning is that **the live record is small and honest and
the replay is large and was twice wrong** (`specs/2026-09-11-live-crosscheck-design.md`).

The premise being tested is the desk owner's: that this book's money is in a
thin right tail, that every gate tuned for the body is destroying it, and that
the answer is convexity rather than accuracy. Three pieces of the folder point
that way already - `exiting.md`'s +0.046R that is worse on 64% of trades,
`giveback.md`'s 27% of the high-water mark kept, and `instruments.md`'s whole
instrument ranking that turned out to be **one trade of +622.63**.

## The question that decides it, and the trap inside it

"What share of total profit comes from the top 5% of trades?" cannot be asked
of this book as written, because **total profit is negative** and a share of a
negative total is not a quantity. It is asked here as a share of **gross
profit** - the winners' sum - with the mirror statistic beside it: the share of
gross loss carried by the worst 5%. A book is convex if the first is large and
the second is not. One number without the other is not a shape.

The trap is the unit. Ranked by **money**, this book is spectacularly
tail-driven and the tail is a *sizing* artefact: the largest close is +622.63
at **+0.703R**, which is a trade that went nowhere in an enormous position. The
same book ranked by **R** - the multiple of its own risk, which is what the
shape of a trade actually is - is a different book. Both are reported, and so
is the concentration of `risk_money` itself, because that is the quantity that
separates them.

## The two populations, and why both are read

A close reaches the journal as `kind='outcome'` if the position still had its
`_refs` link to the decision that opened it, and as an `unattributed`
observation if it did not - which happens when a position outlives a restart.

**The loss is not random and it runs directly at this question.** Unattributed
closes are held far longer, because surviving a deploy is what makes a close
unattributed. This study is *about* long-held tail trades, so reading the
attributed half alone reads the short ones. Both are counted, every money
figure is computed twice, and every R figure states which half it is on -
`eef4912` adds R to a parentless close and whether the running image carries it
is reported at the top of the output rather than assumed.

## What would count as failure, declared before the run

The convexity premise fails if:

* the top 5% share of gross **R** is no larger than the worst 5% share of gross
  loss - a symmetric book, where the tail story is decoration;
* the money concentration disappears once trades are sized equally, which would
  say the tail is the position sizer and not the trade;
* the top decile by `best_r` is indistinguishable from the rest on every
  decision-time feature against its own control - i.e. **the tail cannot be
  selected for**, which is the result that would make "trade for the tail" a
  statement about exits only;
* the biggest winners do **not** end on the hold timeout, which would say the
  clock is not what cuts them.

A null on all four is a real result and is the expected one on 500-odd closes.

Usage:
    JOURNAL=~/till_infinity/data/journal.db python3 -m research.harness.convexbook
"""

from __future__ import annotations

import collections
import math
import os
import random
import statistics as st
import time

from research.harness.winning import load, r_multiple, side_sign
from till_infinity.shared.strata import compare

DB = os.path.expanduser(os.environ.get("JOURNAL", "~/till_infinity/data/journal.db"))
SPLIT = float(os.environ.get("SPLIT", "0.6"))
CONTROLS = int(os.environ.get("CONTROLS", "2000"))
SEED = int(os.environ.get("SEED", "20260911"))
#: A bucket below this is printed with its count and not used to claim anything.
#: `strata.py` argues at length for reporting rather than hiding thin cells.
MIN_CELL = int(os.environ.get("MIN_CELL", "10"))

#: Decision-time features the tail is cut by. Prices and ids are excluded: a
#: tercile of `entry` is a tercile of the instrument's decimal point.
FEATURES = (
    "base_rate_up", "edge", "expected_hold_s", "forecast_ratio", "liquidity_beyond_vol",
    "neighbours", "origin_distance_vol", "origin_size_vol", "own_touches", "probability",
    "range_bps", "reward_to_risk", "risk_vol", "strength", "sweep_n", "sweep_rate",
    "vol_bps", "vol_stretch", "wick_n",
)


# ------------------------------------------------------------------ shape


def shares(values: list[float]) -> dict:
    """Where the gross profit and the gross loss sit, and how asymmetric that is."""
    ranked = sorted(values, reverse=True)
    wins = [v for v in ranked if v > 0]
    losses = [v for v in ranked if v < 0]
    if not wins or not losses:
        return {}
    gross, bled = math.fsum(wins), math.fsum(losses)
    n = len(ranked)
    got = {"n": n, "net": math.fsum(ranked), "gross": gross, "bled": bled,
           "win_rate": len(wins) / n, "best": ranked[0], "worst": ranked[-1]}
    for q in (0.01, 0.05, 0.10, 0.20):
        k = max(1, int(round(n * q)))
        got[f"top{q}"] = math.fsum(ranked[:k]) / gross
        got[f"bot{q}"] = math.fsum(ranked[-k:]) / bled
    got["no_best"] = math.fsum(ranked[1:])
    return got


def render(label: str, got: dict) -> None:
    if not got:
        print(f"  {label}: nothing to rank")
        return
    print(
        f"  {label:<26s} n={got['n']:4d}  net {got['net']:+10.2f}  "
        f"gross+ {got['gross']:+9.2f}  gross- {got['bled']:+10.2f}  "
        f"win {got['win_rate']:5.1%}"
    )
    print(
        f"    {'':24s} {'top 1%':>9s} {'top 5%':>9s} {'top 10%':>9s} {'top 20%':>9s}"
        f"   (share of gross profit)"
    )
    print(
        f"    {'winners carry':24s} {got['top0.01']:9.1%} {got['top0.05']:9.1%} "
        f"{got['top0.1']:9.1%} {got['top0.2']:9.1%}"
    )
    print(
        f"    {'losers carry':24s} {got['bot0.01']:9.1%} {got['bot0.05']:9.1%} "
        f"{got['bot0.1']:9.1%} {got['bot0.2']:9.1%}   (share of gross loss)"
    )
    print(
        f"    asymmetry at 5%: winners {got['top0.05']:.1%} against losers "
        f"{got['bot0.05']:.1%}  ->  {got['top0.05'] / got['bot0.05']:.2f}x"
    )
    print(
        f"    single best {got['best']:+.2f}  = {got['best'] / got['gross']:.1%} of gross "
        f"profit; net without it {got['no_best']:+.2f}   worst {got['worst']:+.2f}"
    )


def gaussian_null(values: list[float], rng: random.Random) -> tuple[float, float]:
    """What the top-5% share looks like with the tail taken out.

    The same n, the same mean, the same standard deviation, drawn from a normal
    - the thinnest-tailed distribution with those moments. It is not a claim
    that returns are normal; it is the reference point for "is 35% a lot", which
    is otherwise a number nobody can size.
    """
    mean, sd = st.fmean(values), st.pstdev(values)
    got = []
    for _ in range(CONTROLS):
        draw = [rng.gauss(mean, sd) for _ in values]
        wins = [v for v in draw if v > 0]
        if not wins:
            continue
        k = max(1, int(round(len(draw) * 0.05)))
        got.append(math.fsum(sorted(draw, reverse=True)[:k]) / math.fsum(wins))
    got.sort()
    return st.median(got), got[int(0.95 * len(got))]


# --------------------------------------------------------------- tail cut


def tail_features(rows: list[dict], key: str, label: str) -> None:
    """Top decile by `key` against the rest, on every decision-time feature.

    Reported as a standardised gap - the difference in means over the pooled
    standard deviation - so features on different scales can be ranked against
    each other and against one control. The control is a **random decile of the
    same rows**, and what it reports is the largest gap over all features,
    because that is what a reader's eye picks out of the table.
    """
    scored = [r for r in rows if isinstance(r.get(key), int | float)]
    if len(scored) < 40:
        print(f"  {label}: only {len(scored)} rows carry {key}")
        return
    ranked = sorted(scored, key=lambda r: -r[key])
    k = max(MIN_CELL, len(ranked) // 10)
    threshold = ranked[k - 1][key]
    for r in scored:
        r["_tail"] = "tail" if r[key] >= threshold else "rest"
    tail_n = sum(1 for r in scored if r["_tail"] == "tail")
    print(f"\n  {label}: top decile by {key} is {tail_n} of {len(scored)}, {key} >= {threshold:.3f}")

    rng = random.Random(SEED)
    gaps = []
    columns = {}
    for feat in FEATURES:
        seen = [r for r in scored if isinstance((r.get("_decision") or {}).get(feat), int | float)]
        if len(seen) < 40:
            continue
        values = [float(r["_decision"][feat]) for r in seen]
        pooled = st.pstdev(values)
        if pooled <= 0:
            continue
        tail = [float(r["_decision"][feat]) for r in seen if r["_tail"] == "tail"]
        rest = [float(r["_decision"][feat]) for r in seen if r["_tail"] == "rest"]
        if len(tail) < MIN_CELL or len(rest) < MIN_CELL:
            continue
        gaps.append(((st.fmean(tail) - st.fmean(rest)) / pooled, feat, len(tail), len(rest)))
        columns[feat] = (values, math.fsum(values), pooled, max(MIN_CELL, len(values) // 10))

    nulls = []
    for _ in range(CONTROLS):
        biggest = 0.0
        for values, total, pooled, size in columns.values():
            picked = math.fsum(rng.sample(values, size))
            rest_mean = (total - picked) / (len(values) - size)
            biggest = max(biggest, abs(picked / size - rest_mean) / pooled)
        nulls.append(biggest)
    nulls.sort()
    floor = nulls[int(0.95 * len(nulls))] if nulls else float("nan")
    print(
        f"    control: largest standardised gap a random decile produces over "
        f"{len(columns)} features - median {st.median(nulls):.3f}, 95th {floor:.3f}"
    )
    print(f"    {'feature':>22s} {'tail-rest sd':>13s} {'n tail':>7s} {'n rest':>7s}  over control")
    for gap, feat, nt, nr in sorted(gaps, key=lambda z: -abs(z[0]))[:8]:
        print(f"    {feat:>22s} {gap:+13.3f} {nt:7d} {nr:7d}  {'YES' if abs(gap) > floor else 'no'}")

    biggest = sorted(gaps, key=lambda z: -abs(z[0]))[:2]
    for gap, feat, _, _ in biggest:
        usable = [
            {
                feat: float(r["_decision"][feat]),
                "tail": r["_tail"],
                "strategy": str(r.get("strategy") or "?"),
                "interval": str((r.get("_decision") or {}).get("interval") or r.get("interval") or "?"),
            }
            for r in scored
            if isinstance((r.get("_decision") or {}).get(feat), int | float)
        ]
        try:
            got = compare(usable, value=feat, bucket="tail", min_n=MIN_CELL * 3)
        except ValueError as exc:
            print(f"\n    {feat}: {exc}")
            continue
        print(f"\n    {feat}, within strategy and interval:")
        print(got.render())


# --------------------------------------------------------------------- run


def main() -> None:
    rng = random.Random(SEED)
    attributed, unattributed = load(DB)
    for r in attributed:
        r["R"] = r_multiple(r)
    both = attributed + unattributed
    both.sort(key=lambda r: r["_t"])
    enriched = sum(1 for r in unattributed if r.get("r_multiple") is not None)

    def when(rows):
        if not rows:
            return "-"
        fmt = "%Y-%m-%d %H:%M"
        return (
            f"{time.strftime(fmt, time.gmtime(rows[0]['_t']))} -> "
            f"{time.strftime(fmt, time.gmtime(rows[-1]['_t']))}"
        )

    print("=" * 78)
    print("THE TWO POPULATIONS")
    print("=" * 78)
    print(f"  kind='outcome'              {len(attributed):5d}   {when(attributed)}")
    print(f"  unattributed observations   {len(unattributed):5d}   {when(unattributed)}")
    print(f"  of those, carrying R:       {enriched:5d}")
    if unattributed and not enriched:
        print("  ** eef4912 is not in the running image, so the missing half is")
        print("     profit-and-seconds only and every R figure below is the short half.")
    for name, rows in (("attributed", attributed), ("unattributed", unattributed)):
        secs = [r["seconds"] for r in rows if isinstance(r.get("seconds"), int | float)]
        kinds = collections.Counter(r.get("exit_kind") for r in rows)
        if secs:
            print(
                f"  {name:<14s} median hold {st.median(secs):6.0f}s   "
                f"over 1800s {sum(1 for s in secs if s > 1800) / len(secs):5.1%}   "
                f"exits {dict(kinds.most_common(4))}"
            )

    print("\n" + "=" * 78)
    print("1. WHERE THE MONEY COMES FROM")
    print("=" * 78)
    print("  Total profit is negative, so 'share of total' is not a quantity. Every")
    print("  share below is of GROSS profit, with the gross-loss mirror beside it.\n")
    money_att = [r["profit"] for r in attributed if isinstance(r.get("profit"), int | float)]
    money_all = [r["profit"] for r in both if isinstance(r.get("profit"), int | float)]
    r_att = [r["R"] for r in attributed if r.get("R") is not None]
    render("attributed, money", shares(money_att))
    print()
    render("both halves, money", shares(money_all))
    print()
    render("attributed, R", shares(r_att))

    print("\n  is the money tail a TRADE tail or a SIZE tail?")
    sized = [
        r for r in attributed
        if r.get("R") is not None and isinstance(r.get("risk_money"), int | float) and r["risk_money"] > 0
    ]
    if len(sized) >= 40:
        risk = [r["risk_money"] for r in sized]
        typical = st.median(risk)
        flat = [r["R"] * typical for r in sized]
        actual = [r["profit"] for r in sized]
        print(
            f"    {len(sized)} of {len(attributed)} closes carry risk_money; both columns below "
            f"are that subset, so the comparison is within one population"
        )
        print(
            f"    risk per trade: median {typical:.2f}, p95 {sorted(risk)[int(0.95 * len(risk))]:.2f}, "
            f"max {max(risk):.2f}  -  a {max(risk) / typical:.1f}x spread in size alone"
        )
        got_actual, got_flat = shares(actual), shares(flat)
        print(
            f"    as traded, top 5% carry {got_actual['top0.05']:.1%} of gross profit; "
            f"at one flat size, {got_flat['top0.05']:.1%}"
        )
        print(
            f"    largest as traded {got_actual['best']:+.2f}; at one flat size the same "
            f"book's largest is {got_flat['best']:+.2f}"
        )

    print("\n  does the concentration hold in both halves of the window?")
    edge = int(len(attributed) * SPLIT)
    for half, part in (("discovery", attributed[:edge]), ("verify", attributed[edge:])):
        cash = shares([r["profit"] for r in part if isinstance(r.get("profit"), int | float)])
        multiple = shares([r["R"] for r in part if r.get("R") is not None])
        if cash and multiple:
            print(
                f"    {half:<10s} n={cash['n']:4d}  money: top 5% {cash['top0.05']:6.1%} "
                f"(worst 5% {cash['bot0.05']:6.1%})   R: top 5% {multiple['top0.05']:6.1%} "
                f"(worst 5% {multiple['bot0.05']:6.1%})"
            )

    print("\n  is 35% a lot? the thin-tailed reference:")
    for label, values in (("money, attributed", money_att), ("R, attributed", r_att)):
        got = shares(values)
        if not got:
            continue
        median, ninety_five = gaussian_null(values, rng)
        print(
            f"    {label:<20s} observed {got['top0.05']:6.1%}   "
            f"a normal with the same mean and sd gives {median:6.1%} "
            f"(95th percentile {ninety_five:6.1%})   "
            f"{'ABOVE' if got['top0.05'] > ninety_five else 'inside'} the null"
        )

    print("\n  by strategy, in R (attributed only):")
    print(f"    {'strategy':>18s} {'n':>5s} {'mean R':>9s} {'median':>9s} {'win':>7s} "
          f"{'top5% of gross':>15s} {'$':>10s}")
    by = collections.defaultdict(list)
    for r in attributed:
        if r.get("R") is not None:
            by[str(r.get("strategy") or "(none)")].append(r)
    for name, part in sorted(by.items(), key=lambda kv: -len(kv[1])):
        rs = [r["R"] for r in part]
        got = shares(rs)
        cash = math.fsum(r["profit"] for r in part if isinstance(r.get("profit"), int | float))
        top = f"{got['top0.05']:.1%}" if got else "-"
        print(
            f"    {name:>18s} {len(part):5d} {st.fmean(rs):+9.3f} {st.median(rs):+9.3f} "
            f"{sum(1 for x in rs if x > 0) / len(rs):6.1%} {top:>15s} {cash:+10.2f}"
        )

    print("\n" + "=" * 78)
    print("2. IS THE TAIL BEING CUT OFF")
    print("=" * 78)
    peaked = [r for r in attributed if isinstance(r.get("best_r"), int | float) and r["best_r"] > 0]
    print(f"  {len(peaked)} closes carry a non-zero high-water mark "
          f"(`best_r` was a constant until 2026-09-02; see giveback.md)")
    if peaked:
        peaked.sort(key=lambda r: -r["best_r"])
        print(f"\n    {'peak fifth':>14s} {'n':>5s} {'mean peak':>10s} {'mean kept':>10s} "
              f"{'keeps':>8s} {'ends on clock':>14s} {'stopped':>8s} {'target':>7s}")
        size = max(MIN_CELL, len(peaked) // 5)
        for i in range(0, len(peaked), size):
            part = peaked[i : i + size]
            if len(part) < MIN_CELL:
                continue
            peak = st.fmean(r["best_r"] for r in part)
            kept = st.fmean(r["R"] for r in part if r["R"] is not None)
            kinds = collections.Counter(r.get("exit_kind") for r in part)
            label = "top" if i == 0 else f"{i // size + 1}"
            print(
                f"    {label:>14s} {len(part):5d} {peak:+10.3f} {kept:+10.3f} "
                f"{kept / peak:7.1%} {kinds['hold'] / len(part):13.1%} "
                f"{kinds['stop'] / len(part):7.1%} {kinds['target'] / len(part):6.1%}"
            )
        print("\n  the ten largest high-water marks and what ended them:")
        print(f"    {'when':<17s} {'symbol':<24s} {'strategy':<17s} {'peak':>7s} {'kept':>7s} "
              f"{'exit':<7s} {'secs':>7s}")
        for r in peaked[:10]:
            print(
                f"    {time.strftime('%m-%d %H:%M', time.gmtime(r['_t'])):<17s} "
                f"{str(r.get('symbol'))[:24]:<24s} {str(r.get('strategy'))[:17]:<17s} "
                f"{r['best_r']:+7.3f} {(r['R'] if r['R'] is not None else float('nan')):+7.3f} "
                f"{str(r.get('exit_kind')):<7s} {r.get('seconds', 0):7.0f}"
            )

    print("\n  what ends the biggest realised winners (top decile by R):")
    scored = [r for r in attributed if r.get("R") is not None]
    scored.sort(key=lambda r: -r["R"])
    for label, part in (
        ("top decile by R", scored[: max(MIN_CELL, len(scored) // 10)]),
        ("the rest", scored[max(MIN_CELL, len(scored) // 10) :]),
    ):
        kinds = collections.Counter(r.get("exit_kind") for r in part)
        secs = [r["seconds"] for r in part if isinstance(r.get("seconds"), int | float)]
        print(
            f"    {label:<18s} n={len(part):4d}  hold {kinds['hold'] / len(part):5.1%}  "
            f"target {kinds['target'] / len(part):5.1%}  stop {kinds['stop'] / len(part):5.1%}  "
            f"stale {kinds['stale'] / len(part):5.1%}  median hold {st.median(secs) if secs else 0:.0f}s"
        )

    print("\n" + "=" * 78)
    print("3. WHAT THE TAIL WINNERS HAVE IN COMMON")
    print("=" * 78)
    print(f"  {len(FEATURES)} features, two tail definitions, one control apiece =")
    print(f"  {len(FEATURES) * 2} comparisons, plus the shares above.")
    for r in attributed:
        if isinstance(r.get("best_r"), int | float):
            r["_best_r"] = r["best_r"]
    tail_features([r for r in attributed if r.get("best_r")], "best_r", "by high-water mark")
    tail_features(scored, "R", "by realised R")

    print("\n" + "=" * 78)
    print("Declared failure conditions: a symmetric 5% share; a money tail that")
    print("vanishes at one flat size; a tail decile indistinguishable from the rest")
    print("against its own control; biggest winners not ending on the clock.")


if __name__ == "__main__":
    main()
