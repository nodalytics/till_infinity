"""What separates a winning trade from a losing one on the live record.

`research/winning.md`. The desk owner's question: *what patterns make our trades
win, and how do we make winning consistent?*

This is a study of the live journal, not a replay. The reason is
`research/specs/2026-09-11-live-crosscheck-design.md`: the only harness that
could answer this by simulation exits 98% by stop where the desk exits 13%, and
two look-aheads in the exit replays moved an answer by an order of magnitude in
one morning. The live record is small and honest; the replay is large and was
twice wrong.

## The two populations, and why both are read

A close reaches the journal one of two ways:

* `kind='outcome'` - the position still had its `_refs` link to the decision
  that opened it, so the entry, stop, target and every level feature the trade
  was born from are on the row.
* an `observation` whose context carries `unattributed` - the position outlived
  that link (it spanned a restart), so `Trader._unattributed_context` writes
  what it can: profit, seconds, exit kind, strategy, feed.

**The loss is not random.** Unattributed closes are held far longer, because
surviving a deploy is what makes a close unattributed. Reading only the
attributed half is reading the short trades. So both are loaded, both are
counted, and every conclusion that can be computed on the union is computed
twice.

What the unattributed half cannot supply is R, because it carries no entry and
no risk. `eef4912` adds that; whether the running image has it is reported at
the top of the output rather than assumed.

## R is reconstructed, not read

`r_multiple` is absent on 118 of the 397 outcomes. It is exactly
`(exit - entry) * side / risk_price` on all 279 that carry it - checked here to
1e-5 - so it is recomputed for every row rather than dropping a quarter of the
book. `profit / risk_money` is **not** the same thing (it carries slippage,
commission and swap) and is not used for R.

## What would count as failure, declared before the run

A decision-time feature is reported as separating winners from losers only if
all four hold:

1. its tercile gap in the **discovery** half exceeds what the permutation
   control produces for the best of the same features on shuffled outcomes;
2. the discovery ordering survives into the **verify** half;
3. `shared.strata.compare` does not flag a reversal within strategy or interval;
4. it survives removal of the single best trade.

**A null is the expected result.** 397 closes against 45 features, split in
half, is a thin study, and the control exists to say so out loud. "Nothing in
the feature set separates winners from losers" is the answer this is built to
be able to give.

## The controls

* **Permutation over the whole scan.** The outcome column is shuffled and the
  entire scan re-run, 200 times. What matters is not one feature's gap but the
  **largest gap over all features**, because that is what a reader's eye picks
  out. `research/generated.md` is the precedent: the biggest correlation in a
  325-pair study was between two unrelated instruments.
* **A per-contrast permutation** for the one hypothesis that was written down
  before this run (`exiting.md`: *"refuse a setup whose spread is too large a
  share of what it is reaching for"*). A pre-registered contrast is not judged
  against the max-of-45 null, which would be the wrong test for it.
* **Shuffling within feed**, so an effect that is really an instrument cannot
  survive as an effect about trades.

## The trap this harness walks into on purpose

Holding time looks like the strongest cohort separator on the book, and it gets
*more* significant when the unattributed half is added. Section 6 conditions it
on exit kind and it disappears entirely. Short trades lose because short trades
are stops. That is the fifth time a pooled figure has reversed on this project
and it is kept in the output, because the reader needs to see the reversal
rather than be told it happened.
"""

from __future__ import annotations

import collections
import json
import math
import os
import random
import sqlite3
import statistics as st
import sys
import time
from typing import Any

sys.path.insert(0, os.environ.get("REPO", os.path.expanduser("~/till_infinity/repo")))

from till_infinity.shared.strata import compare  # noqa: E402

DB = os.environ.get("JOURNAL", "/app/.data/journal/journal.db")
#: Fraction of closes, in time order, used to propose. The rest disposes.
SPLIT = float(os.environ.get("SPLIT", "0.6"))
PERMUTATIONS = int(os.environ.get("PERMUTATIONS", "200"))
#: Permutations for a single pre-registered contrast, which is cheap enough to
#: run properly.
CONTRAST_PERMUTATIONS = int(os.environ.get("CONTRAST_PERMUTATIONS", "2000"))
SEED = int(os.environ.get("SEED", "11"))
#: A tercile below this many rows is not scored. Small enough to keep thin
#: strata visible - `strata.py` argues at length for reporting rather than
#: hiding them - and large enough that a bucket mean is not one trade.
MIN_BUCKET = 25

#: Decision-time numeric features. Prices, ids and sizes are excluded: `entry`,
#: `level` and `zone_low` are the instrument's decimal point, not a property of
#: the trade, and a tercile of them is a tercile of the symbol.
FEATURES = (
    "activity", "after_pullback", "base_rate_up", "break_probability", "edge",
    "efficiency", "ensemble_bps", "expected_hold_s", "forecast_bps",
    "forecast_ratio", "garch_bps", "hold_seconds", "hour_hold", "hour_n",
    "hour_vol_share", "in_origin", "liquidity_beyond_n", "liquidity_beyond_vol",
    "momentum_agree", "momentum_vol", "neighbours", "origin_below_vol",
    "origin_distance_vol", "origin_revisits", "origin_size_vol", "own_touches",
    "pressure_vol", "probability", "range_bps", "record_hold", "record_n",
    "reward_to_risk", "risk_vol", "stop_scale", "stop_vol", "strength",
    "sweep_n", "sweep_rate", "vol_bps", "vol_stretch", "wick_above_sd",
    "wick_below_sd", "wick_n",
)

SYNTHETIC = ("boom_", "crash_", "jump_", "volatility_", "step_", "range_break_")
#: Where the spread stops being a rounding error, from the deciles in §5. Fixed
#: here so that §5's out-of-sample leg can set its own from the discovery half
#: and the two can be compared.
EXPENSIVE = 0.16


def side_sign(row: dict[str, Any]) -> float:
    return 1.0 if str(row.get("side", "")).lower() == "buy" else -1.0


def r_multiple(row: dict[str, Any]) -> float | None:
    """R from prices, which is what `r_multiple` is when it is present."""
    entry, exit_, risk = row.get("entry"), row.get("exit"), row.get("risk_price")
    if entry is None or exit_ is None or not risk:
        return None
    return (exit_ - entry) * side_sign(row) / risk


def hold_bucket(row: dict[str, Any]) -> str:
    seconds = row.get("seconds") or 0
    if seconds < 120:
        return "0-2m"
    if seconds < 600:
        return "2-10m"
    if seconds < 1800:
        return "10-30m"
    return "30m+"


def day_of(row: dict[str, Any]) -> str:
    return time.strftime("%m-%d", time.gmtime(row["_t"]))


def load(path: str) -> tuple[list[dict], list[dict]]:
    """Attributed closes joined to their decisions, and unattributed closes."""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    decisions: dict[str, dict] = {}
    for ident, ctx in conn.execute(
        "SELECT id, context FROM entries WHERE actor='trading' AND kind='decision'"
    ):
        decisions[ident] = json.loads(ctx or "{}")

    attributed: list[dict] = []
    for ident, when, parent, ctx in conn.execute(
        "SELECT id, time, parent, context FROM entries "
        "WHERE actor='trading' AND kind='outcome' ORDER BY time"
    ):
        row = json.loads(ctx or "{}")
        row["_id"], row["_t"] = ident, when
        row["_decision"] = decisions.get(parent) or {}
        row["R"] = r_multiple(row)
        attributed.append(row)

    unattributed: list[dict] = []
    for ident, when, ctx in conn.execute(
        "SELECT id, time, context FROM entries "
        "WHERE actor='trading' AND kind='observation' ORDER BY time"
    ):
        row = json.loads(ctx or "{}")
        if not isinstance(row, dict) or not row.get("unattributed"):
            continue
        row["_id"], row["_t"] = ident, when
        row["R"] = r_multiple(row)
        unattributed.append(row)
    return attributed, unattributed


def features_of(row: dict[str, Any]) -> dict[str, float]:
    """Everything knowable at the moment the order went in.

    Three quantities are re-expressed relative to the trade rather than to the
    chart, because `edge`, `expected_push_vol` and `probability_up` are all
    up-positive: their median is +0.32 on a buy and -0.28 on a sell, so a
    tercile of the raw field is a tercile of `side`.
    """
    decision = row.get("_decision") or {}
    sign = side_sign(row)
    got: dict[str, float] = {
        key: float(decision[key])
        for key in FEATURES
        if isinstance(decision.get(key), int | float) and not isinstance(decision.get(key), bool)
    }
    for key, name in (("edge", "edge_with"), ("expected_push_vol", "push_with")):
        if isinstance(decision.get(key), int | float):
            got[name] = float(decision[key]) * sign
    if isinstance(decision.get("probability_up"), int | float):
        up = float(decision["probability_up"])
        got["prob_with"] = up if sign > 0 else 1.0 - up
    below, above = decision.get("wick_below_vol"), decision.get("wick_above_vol")
    if isinstance(below, int | float) and isinstance(above, int | float):
        got["wick_ahead"] = float(above if sign > 0 else below)
        got["wick_behind"] = float(below if sign > 0 else above)
    spread, risk = decision.get("spread_at_entry"), decision.get("risk_price")
    if isinstance(spread, int | float) and risk:
        # The pre-registered one. `exiting.md` derived it from a replay
        # decomposition: the cost in R is spread / (risk_vol * vol_bps), which
        # grows without bound as the risk shrinks.
        got["spread_over_risk"] = float(spread) / float(risk)
    if row.get("confluence"):
        got["confluence_n"] = float(len(str(row["confluence"]).split("+")))
    return got


def terciles(values: list[float]) -> tuple[float, float]:
    ordered = sorted(values)
    return ordered[len(ordered) // 3], ordered[2 * len(ordered) // 3]


def bucket_of(value: float, low: float, high: float) -> str:
    return "low" if value <= low else ("mid" if value <= high else "high")


def scan(rows: list[dict], target: str, split: int, feats: list[str]) -> list[dict]:
    """Tercile every feature on the discovery half; carry the cut into verify."""
    discovery, verify = rows[:split], rows[split:]
    found: list[dict] = []
    for feat in feats:
        seen = [r for r in discovery if feat in r["f"]]
        if len(seen) < 3 * MIN_BUCKET:
            continue
        low, high = terciles([r["f"][feat] for r in seen])
        if low == high:
            continue
        cut_d: dict[str, list[float]] = collections.defaultdict(list)
        cut_v: dict[str, list[float]] = collections.defaultdict(list)
        for r in seen:
            cut_d[bucket_of(r["f"][feat], low, high)].append(r[target])
        for r in verify:
            if feat in r["f"]:
                cut_v[bucket_of(r["f"][feat], low, high)].append(r[target])
        if len(cut_d) < 2 or any(len(x) < MIN_BUCKET for x in cut_d.values()):
            continue
        means = {k: st.fmean(x) for k, x in cut_d.items()}
        best, worst = max(means, key=means.get), min(means, key=means.get)
        verified = None
        if len(cut_v.get(best, [])) >= 10 and len(cut_v.get(worst, [])) >= 10:
            verified = st.fmean(cut_v[best]) - st.fmean(cut_v[worst])
        found.append(
            {
                "feat": feat, "gap": means[best] - means[worst], "verify_gap": verified,
                "best": best, "worst": worst, "low": low, "high": high,
                "n_d": len(seen), "means": means,
                "counts": {k: len(x) for k, x in cut_d.items()},
            }
        )
    return sorted(found, key=lambda z: -z["gap"])


def control(rows: list[dict], target: str, split: int, feats: list[str]) -> tuple[list, list]:
    """The same scan on shuffled outcomes. Max gap, and how many survive."""
    rng = random.Random(SEED)
    base = [r[target] for r in rows]
    gaps: list[float] = []
    survivors: list[int] = []
    for _ in range(PERMUTATIONS):
        shuffled = base[:]
        rng.shuffle(shuffled)
        for row, value in zip(rows, shuffled, strict=True):
            row["_perm"] = value
        got = scan(rows, "_perm", split, feats)
        if not got:
            continue
        gaps.append(max(z["gap"] for z in got))
        survivors.append(sum(1 for z in got if z["verify_gap"] is not None and z["verify_gap"] > 0))
    for row, value in zip(rows, base, strict=True):
        row[target] = value
    return sorted(gaps), sorted(survivors)


def quantile(ordered: list[float], q: float) -> float:
    if not ordered:
        return float("nan")
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def klass(feed: str) -> str:
    feed = str(feed or "")
    if feed.startswith(SYNTHETIC):
        return "synthetic"
    return "real"


def main() -> None:
    attributed, unattributed = load(DB)
    scored = [r for r in attributed if r["R"] is not None]
    scored.sort(key=lambda r: r["_t"])

    print("=" * 74)
    print("THE TWO POPULATIONS")
    print("=" * 74)
    enriched = sum(1 for r in unattributed if r.get("r_multiple") is not None)
    print(f"  kind='outcome'                {len(attributed):5d}   R recomputed on {len(scored)}")
    print(f"  observations, unattributed    {len(unattributed):5d}   carrying r_multiple: {enriched}")
    if not enriched and unattributed:
        print("  ** no unattributed close carries R. eef4912 is not in the running image,")
        print("     so the missing half is still profit-and-seconds only.")
    recorded = [r["r_multiple"] for r in attributed if r.get("r_multiple") is not None]
    if recorded:
        drift = max(
            abs(r["r_multiple"] - r["R"])
            for r in attributed
            if r.get("r_multiple") is not None and r["R"] is not None
        )
        print(f"  recomputed R vs recorded r_multiple: n={len(recorded)}, max |diff| {drift:.6f}")

    if unattributed:
        since = min(r["_t"] for r in unattributed)
        same_era = [r for r in attributed if r["_t"] >= since]
        holds_a = sorted(r.get("seconds") or 0 for r in same_era)
        holds_u = sorted(r.get("seconds") or 0 for r in unattributed)
        share = len(unattributed) / (len(unattributed) + len(same_era))
        print(f"  over the window both exist: {share:.0%} of closes are unattributed")
        print(
            f"  median hold  attributed {st.median(holds_a):6.0f}s   "
            f"unattributed {st.median(holds_u):6.0f}s   "
            f"over 1800s {sum(1 for x in holds_a if x > 1800) / len(holds_a):.0%} vs "
            f"{sum(1 for x in holds_u if x > 1800) / len(holds_u):.0%}"
        )
        for name, rows in (("attributed", same_era), ("unattributed", unattributed)):
            mix = collections.Counter(str(r.get("exit_kind") or "?") for r in rows)
            print(
                f"    {name:<14s} exit mix "
                + "  ".join(f"{k} {n / len(rows):.0%}" for k, n in mix.most_common())
            )

    print()
    print("=" * 74)
    print("THE BOOK IS ARITHMETIC, NOT SELECTION")
    print("=" * 74)
    by_kind: dict[str, list[float]] = collections.defaultdict(list)
    for row in scored:
        by_kind[str(row.get("exit_kind") or "?")].append(row["R"])
    total = 0.0
    for kind, values in sorted(by_kind.items(), key=lambda t: -len(t[1])):
        share = len(values) / len(scored)
        total += share * st.fmean(values)
        print(
            f"  {kind:<8s} share {share:6.1%}  mean {st.fmean(values):+7.3f}R  "
            f"median {st.median(values):+7.3f}R  contributes {share * st.fmean(values):+7.4f}R"
        )
    print(f"  {'total':<8s}                                            {total:+7.4f}R")
    stops, targets, holds = by_kind.get("stop", []), by_kind.get("target", []), by_kind.get("hold", [])
    if stops and targets and holds and total < 0:
        to_hold = st.fmean(holds) - st.fmean(stops)
        to_target = st.fmean(targets) - st.fmean(holds)
        print(
            f"  to flatten it: {math.ceil(-total * len(scored) / to_hold)} of {len(stops)} stops "
            f"become timeouts, or {math.ceil(-total * len(scored) / to_target)} of {len(holds)} "
            f"timeouts become targets"
        )

    rows = [
        {
            "R": r["R"],
            "won": 1.0 if r["R"] > 0 else 0.0,
            "stopped": 1.0 if str(r.get("exit_kind")) == "stop" else 0.0,
            "profit": float(r.get("profit") or 0.0),
            "seconds": r.get("seconds") or 0,
            "strategy": str(r.get("strategy") or "?"),
            "interval": str(r.get("interval") or "?"),
            "exit_kind": str(r.get("exit_kind") or "?"),
            "feed": str(r.get("feed") or "?"),
            "_t": r["_t"],
            "f": features_of(r),
        }
        for r in scored
    ]
    split = int(len(rows) * SPLIT)
    coverage: collections.Counter = collections.Counter()
    for row in rows:
        coverage.update(row["f"].keys())
    feats = sorted(k for k, c in coverage.items() if c >= 3 * MIN_BUCKET)

    print()
    print("=" * 74)
    print("THE SCAN, AGAINST ITS OWN NULL")
    print("=" * 74)
    print(f"  {len(rows)} closes, {len(feats)} features, discovery {split} / verify {len(rows) - split}")
    survivors_by_target: dict[str, list[dict]] = {}
    for target, label in (("R", "R"), ("stopped", "P(stop)"), ("won", "P(R>0)")):
        found = scan(rows, target, split, feats)
        held = [z for z in found if z["verify_gap"] is not None and z["verify_gap"] > 0]
        gaps, survivors = control(rows, target, split, feats)
        ceiling = quantile(gaps, 0.95)
        print()
        print(f"  -- target {label}")
        for z in found[:6]:
            verified = f"{z['verify_gap']:+.3f}" if z["verify_gap"] is not None else "  n/a"
            print(
                f"     {z['feat']:<22s} gap {z['gap']:+.3f}  verify {verified}  "
                f"{z['best']}>{z['worst']}"
            )
        print(
            f"     control: largest gap on shuffled outcomes  median {st.median(gaps):.3f}  "
            f"p95 {ceiling:.3f}  max {gaps[-1]:.3f}"
        )
        print(
            f"     control: features holding their sign in verify  median "
            f"{st.median(survivors):.0f}  p95 {quantile(survivors, 0.95):.0f}   "
            f"(observed {len(held)} of {len(found)})"
        )
        clear = [z for z in found if z["gap"] > ceiling and (z["verify_gap"] or 0) > 0]
        if clear:
            print("     above the control and holding in verify: " + ", ".join(z["feat"] for z in clear))
        else:
            print("     above the control and holding in verify: none")
        survivors_by_target[target] = clear

    print()
    print("=" * 74)
    print("CONDITIONING THE BEST OF THEM")
    print("=" * 74)
    # The four largest by R, plus anything that cleared a control on any
    # target. A feature that wins the eye and a feature that clears the null
    # both have to face the strata.
    wanted = [z["feat"] for z in scan(rows, "R", split, feats)[:4]]
    for clear in survivors_by_target.values():
        wanted += [z["feat"] for z in clear if z["feat"] not in wanted]
    by_feature = {z["feat"]: z for z in scan(rows, "R", split, feats)}
    top = [by_feature[name] for name in wanted if name in by_feature]
    for z in top:
        def cut(row: dict, z: dict = z) -> str:
            return bucket_of(row["f"][z["feat"]], z["low"], z["high"])

        have = [r for r in rows if z["feat"] in r["f"]]
        print(f"  {z['feat']}  n={len(have)}  terciles from discovery: <={z['low']:.4f}, <={z['high']:.4f}")
        print(compare(have, value="R", bucket=cut, within=("strategy", "interval"), min_n=40).render())
        print()

    print("=" * 74)
    print("THE ONE HYPOTHESIS THAT WAS WRITTEN DOWN FIRST")
    print("=" * 74)
    print("  exiting.md: 'refuse a setup whose spread is too large a share of what it")
    print("  is reaching for'. Contrast declared before the run: spread/risk, cheap - expensive.")
    priced = [r for r in rows if "spread_over_risk" in r["f"]]
    priced.sort(key=lambda r: r["_t"])

    def contrast(rs: list[dict], threshold: float = EXPENSIVE, key: str = "R") -> float | None:
        dear = [r[key] for r in rs if r["f"]["spread_over_risk"] > threshold]
        cheap = [r[key] for r in rs if r["f"]["spread_over_risk"] <= threshold]
        return st.fmean(cheap) - st.fmean(dear) if dear and cheap else None

    print()
    print("  deciles of spread/risk:")
    ordered = sorted(priced, key=lambda r: r["f"]["spread_over_risk"])
    step = len(ordered) // 10
    for i in range(10):
        part = ordered[i * step : (i + 1) * step] if i < 9 else ordered[9 * step :]
        print(
            f"    d{i + 1:<2d} <= {part[-1]['f']['spread_over_risk']:.3f}  n={len(part):<3d} "
            f"mean {st.fmean([r['R'] for r in part]):+.3f}R  "
            f"median {st.median([r['R'] for r in part]):+.3f}R  "
            f"stopped {sum(r['stopped'] for r in part) / len(part):.0%}"
        )

    rng = random.Random(SEED + 1)
    observed = contrast(priced)
    null: list[float] = []
    base = [r["R"] for r in priced]
    for _ in range(CONTRAST_PERMUTATIONS):
        # Shuffled *within feed*, so an effect that is really an instrument
        # cannot survive as an effect about trades.
        pools: dict[str, list[float]] = collections.defaultdict(list)
        for row in priced:
            pools[row["feed"]].append(row["R"])
        for pool in pools.values():
            rng.shuffle(pool)
        taken: collections.Counter = collections.Counter()
        drawn = []
        for row in priced:
            drawn.append({"f": row["f"], "R": pools[row["feed"]][taken[row["feed"]]]})
            taken[row["feed"]] += 1
        null.append(contrast(drawn) or 0.0)
    for row, value in zip(priced, base, strict=True):
        row["R"] = value
    null.sort()
    beat = sum(1 for x in null if x >= (observed or 0.0)) / len(null)
    print()
    print(
        f"  cheap - expensive at spread/risk {EXPENSIVE}: {observed:+.3f}R   "
        f"within-feed null p95 {quantile(null, 0.95):+.3f}  p99 {quantile(null, 0.99):+.3f}  p={beat:.4f}"
    )

    real_only = [r for r in priced if klass(r["feed"]) == "real"]
    if real_only:
        print(f"  on the non-synthetic book alone (n={len(real_only)}): {contrast(real_only):+.3f}R")
    print()
    print("  paired within day (days with >=5 on each side):")
    agree = 0
    days = 0
    for day in sorted({day_of(r) for r in priced}):
        part = [r for r in priced if day_of(r) == day]
        dear = [r for r in part if r["f"]["spread_over_risk"] > EXPENSIVE]
        cheap = [r for r in part if r["f"]["spread_over_risk"] <= EXPENSIVE]
        if len(dear) >= 5 and len(cheap) >= 5:
            gap = st.fmean([r["R"] for r in cheap]) - st.fmean([r["R"] for r in dear])
            days += 1
            agree += gap > 0
            print(
                f"    {day}  expensive n={len(dear):<3d} {st.fmean([r['R'] for r in dear]):+.3f}   "
                f"cheap n={len(cheap):<3d} {st.fmean([r['R'] for r in cheap]):+.3f}   gap {gap:+.3f}"
            )
    print(f"    days where cheap wins: {agree} of {days}")

    print()
    print("  the binary claim inside each stratum (the three-bucket ordering does not")
    print("  survive `strata.compare`; this is the cut that was actually proposed):")
    held = counted = 0
    for key in ("strategy", "interval"):
        groups: dict[str, list[dict]] = collections.defaultdict(list)
        for row in priced:
            groups[row[key]].append(row)
        for name, part in sorted(groups.items()):
            dear = [r["R"] for r in part if r["f"]["spread_over_risk"] > EXPENSIVE]
            cheap = [r["R"] for r in part if r["f"]["spread_over_risk"] <= EXPENSIVE]
            thin = len(dear) < 5 or len(cheap) < 5
            gap = st.fmean(cheap) - st.fmean(dear) if dear and cheap else float("nan")
            if not thin:
                counted += 1
                held += gap > 0
            print(
                f"    {key:<9s} {name:<18s} expensive n={len(dear):<3d} "
                f"{(st.fmean(dear) if dear else float('nan')):+.3f}   "
                f"cheap n={len(cheap):<3d} {(st.fmean(cheap) if cheap else float('nan')):+.3f}   "
                f"gap {gap:+.3f}" + ("   (thin, not counted)" if thin else "")
            )
    print(f"    cheap wins in {held} of {counted} strata with 5 on each side")

    print()
    print("  what it survives:")
    best_money = max(priced, key=lambda r: r["profit"])
    best_r = max(priced, key=lambda r: r["R"])
    worst_r = min(priced, key=lambda r: r["R"])
    dearest_feed = collections.Counter(
        r["feed"] for r in priced if r["f"]["spread_over_risk"] > EXPENSIVE
    ).most_common(1)[0][0]
    for label, kept in (
        ("as measured", priced),
        (f"minus the best trade ({best_money['profit']:+.2f})", [r for r in priced if r is not best_money]),
        (f"minus the best R ({best_r['R']:+.2f})", [r for r in priced if r is not best_r]),
        (f"minus the worst R ({worst_r['R']:+.2f})", [r for r in priced if r is not worst_r]),
        (f"minus every {dearest_feed}", [r for r in priced if r["feed"] != dearest_feed]),
    ):
        print(f"    {label:<34s} {contrast(kept):+.3f}R")

    print()
    print("  out of sample - threshold set on the discovery half only:")
    cut = int(len(priced) * SPLIT)
    edge = quantile(sorted(r["f"]["spread_over_risk"] for r in priced[:cut]), 0.8)
    for name, part in (("discovery", priced[:cut]), ("verify", priced[cut:])):
        dear = [r for r in part if r["f"]["spread_over_risk"] > edge]
        cheap = [r for r in part if r["f"]["spread_over_risk"] <= edge]
        got = contrast(part, edge)
        print(
            f"    {name:<10s} over n={len(dear):<3d} "
            f"{(st.fmean([r['R'] for r in dear]) if dear else float('nan')):+.3f}R   "
            f"under n={len(cheap):<3d} {st.fmean([r['R'] for r in cheap]):+.3f}R   "
            f"gap {(got if got is not None else float('nan')):+.3f}R"
        )
    print(f"    threshold from discovery p80 = {edge:.4f}")

    print()
    print("  the gate that ships measures spread against the REWARD, not the risk:")
    gated = []
    for row, close in zip(rows, scored, strict=True):
        decision = close.get("_decision") or {}
        spread, target_, entry = decision.get("spread_at_entry"), decision.get("target"), decision.get("entry")
        if not isinstance(spread, int | float) or target_ is None or entry is None:
            continue
        reward = abs(target_ - entry)
        if reward <= 0 or "spread_over_risk" not in row["f"]:
            continue
        gated.append((spread / reward, row))
    for passes, label_a in ((True, "passes the 25% gate"), (False, "over the gate")):
        for dear, label_b in ((False, "cheap against risk"), (True, "expensive against risk")):
            part = [
                row
                for share, row in gated
                if (share <= 0.25) == passes and (row["f"]["spread_over_risk"] > EXPENSIVE) == dear
            ]
            if not part:
                continue
            print(
                f"    {label_a:<20s} {label_b:<22s} n={len(part):<4d} "
                f"mean {st.fmean([r['R'] for r in part]):+.3f}R  "
                f"stopped {sum(r['stopped'] for r in part) / len(part):.0%}  "
                f"money {sum(r['profit'] for r in part):+9.2f}"
            )

    print()
    print("=" * 74)
    print("THE TRAP: HOLDING TIME, AND WHAT IT REALLY IS")
    print("=" * 74)
    union = rows + [
        {
            "profit": float(r.get("profit") or 0.0),
            "seconds": r.get("seconds") or 0,
            "strategy": str(r.get("strategy") or "?"),
            "exit_kind": str(r.get("exit_kind") or "?"),
            "feed": str(r.get("feed") or "?"),
            "_t": r["_t"],
        }
        for r in unattributed
    ]
    since = min((r["_t"] for r in unattributed), default=0.0)
    union = [r for r in union if r["_t"] >= since]
    same_era = [r for r in rows if r["_t"] >= since]

    for name, part, field, unit in (
        ("attributed, R", rows, "R", "R"),
        ("attributed, money", same_era, "profit", "$"),
        ("union, money", union, "profit", "$"),
    ):
        cuts: dict[str, list[float]] = collections.defaultdict(list)
        for row in part:
            cuts[hold_bucket(row)].append(row[field])
        line = "  ".join(
            f"{k} n={len(cuts[k])} {st.fmean(cuts[k]):+.3f}"
            for k in ("0-2m", "2-10m", "10-30m", "30m+")
            if k in cuts
        )
        print(f"  {name:<20s} ({unit})  {line}")

    def long_gap(part: list[dict], field: str) -> float:
        long_ = [r[field] for r in part if hold_bucket(r) == "30m+"]
        rest = [r[field] for r in part if hold_bucket(r) != "30m+"]
        return st.fmean(long_) - st.fmean(rest) if long_ and rest else 0.0

    rng = random.Random(SEED + 2)
    for name, part, field in (("attributed, R", rows, "R"), ("union, money", union, "profit")):
        observed = long_gap(part, field)
        null = []
        for _ in range(CONTRAST_PERMUTATIONS):
            pools = collections.defaultdict(list)
            for row in part:
                pools[row["strategy"]].append(row[field])
            for pool in pools.values():
                rng.shuffle(pool)
            taken = collections.Counter()
            drawn = []
            for row in part:
                drawn.append({"seconds": row["seconds"], field: pools[row["strategy"]][taken[row["strategy"]]]})
                taken[row["strategy"]] += 1
            null.append(long_gap(drawn, field))
        null.sort()
        print(
            f"  30m+ minus the rest, {name:<18s} {observed:+7.3f}  "
            f"within-strategy null p95 {quantile(null, 0.95):+.3f}  "
            f"p={sum(1 for x in null if x >= observed) / len(null):.4f}"
        )

    print()
    print("  the same cut, conditioned on how the trade ended:")
    for kind in ("stop", "target", "hold", "stale"):
        part = [r for r in rows if r["exit_kind"] == kind]
        if not part:
            continue
        cuts = collections.defaultdict(list)
        for row in part:
            cuts[hold_bucket(row)].append(row["R"])
        print(
            f"    {kind:<7s} n={len(part):<4d} "
            + "  ".join(
                f"{k} n={len(cuts[k])} {st.fmean(cuts[k]):+.3f}"
                for k in ("0-2m", "2-10m", "10-30m", "30m+")
                if k in cuts
            )
        )
    unstopped = [r for r in rows if r["exit_kind"] != "stop"]
    rng = random.Random(SEED + 3)
    observed = long_gap(unstopped, "R")
    null = []
    base = [r["R"] for r in unstopped]
    for _ in range(CONTRAST_PERMUTATIONS):
        shuffled = base[:]
        rng.shuffle(shuffled)
        null.append(long_gap([{"seconds": r["seconds"], "R": v} for r, v in zip(unstopped, shuffled, strict=True)], "R"))
    null.sort()
    print(
        f"    stops removed: 30m+ minus the rest {observed:+.3f}R  "
        f"null p95 {quantile(null, 0.95):+.3f}  "
        f"p={sum(1 for x in null if x >= observed) / len(null):.4f}"
    )

    print()
    print("=" * 74)
    print("WHAT THE MISSING HALF CHANGES")
    print("=" * 74)
    for name, part in (("attributed", same_era), ("union", union)):
        cuts = collections.defaultdict(list)
        for row in part:
            cuts[row["strategy"]].append(row["profit"])
        print(f"  -- {name}, money per close, n={len(part)}")
        for strategy in sorted(cuts, key=lambda k: -st.fmean(cuts[k])):
            values = cuts[strategy]
            print(
                f"     {strategy:<18s} n={len(values):<4d} mean {st.fmean(values):+7.2f}  "
                f"median {st.median(values):+7.2f}  total {sum(values):+9.2f}"
            )


if __name__ == "__main__":
    main()
