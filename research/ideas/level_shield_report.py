"""Read the panel and report it: per instrument, against the hardest null arm.

The claim is directional and was fixed before the run: a barrier means a
**positive** mirror gap (the blocked side reached less often than the clear
side, within the same anchor) and a **negative** dose slope (more levels in
the path, lower reach rate). So the hardest null arm for this claim is the one
with the *highest* mirror gap and the *most negative* dose slope - the arm that
most nearly produces the result mechanically. `hardest` in
`node/surrogates.py` makes the same choice and for the same reason: a result
is only as established as its strongest control.

Nothing is pooled across instruments in the headline. A pooled median on this
desk once agreed with a claim every subgroup refuted.
"""

import json
import math
import statistics as st
import sys
from collections import defaultdict

from research.ideas.level_shield_agg import benjamini_hochberg, two_sided_p

NULLS = ("garch-bars", "walk-geometry", "bar-shuffle")


def load(path: str) -> list[dict]:
    with open(path) as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _excess(real: float, draws: list[float], sd: float, *, want: int) -> tuple[float, float]:
    """`(excess, z)` of `real` over the hardest null arm's mean.

    `want` +1 when the claim predicts a larger value, -1 when smaller. The
    null's own spread across draws is added to the real cell's day-block sd,
    because a null arm estimated from four draws carries error of its own and
    treating it as exact is how a null becomes a rubber stamp.
    """
    if not draws:
        return float("nan"), float("nan")
    worst = max(draws) if want > 0 else min(draws)
    spread = st.pstdev(draws) if len(draws) > 1 else 0.0
    total = math.sqrt(sd**2 + spread**2)
    excess = (real - worst) * want
    return excess, (excess / total if total > 0 else 0.0)


def mirror_table(rows: list[dict]) -> None:
    by: dict[tuple, dict] = defaultdict(dict)
    for r in rows:
        if r["kind"] != "mirror" or r["gap"] is None:
            continue
        key = (r["interval"], r["feed"], r["distance"])
        if r["arm"] == "real":
            by[key]["real"] = r
        else:
            by[key].setdefault(r["arm"], []).append(r["gap"])

    print("\n" + "=" * 104)
    print("MIRROR: blocked side vs clear side, same anchor, skew-corrected.")
    print("Positive gap = the level suppressed the move (good for a stop, bad for a target).")
    print("=" * 104)
    cells: list[tuple] = []
    for interval in ("15m", "1h", "1d"):
        got = sorted(k for k in by if k[0] == interval and "real" in by[k])
        if not got:
            continue
        print(f"\n--- {interval} ---")
        print(
            f"{'feed':9s} {'d':>4s} {'n':>6s} {'p_blk':>7s} {'p_clr':>7s} "
            f"{'gap':>8s} {'sd':>7s} {'z':>6s} | {'hardest null':>13s} {'excess':>8s} {'z':>6s}"
        )
        for key in got:
            real = by[key]["real"]
            draws = [v for arm in NULLS for v in by[key].get(arm, [])]
            names = {arm: by[key].get(arm, []) for arm in NULLS}
            worst_arm = max(
                (a for a in names if names[a]), key=lambda a: max(names[a]), default="-"
            )
            sd = real["sd"] or 0.0
            z = real["gap"] / sd if sd else 0.0
            excess, ez = _excess(real["gap"], draws, sd, want=+1)
            cells.append((key, excess, ez))
            print(
                f"{key[1]:9s} {key[2]:>4.1f} {real['n']:>6d} {real['p_blocked']:>7.4f} "
                f"{real['p_clear']:>7.4f} {real['gap']:>+8.4f} {sd:>7.4f} {z:>+6.2f} | "
                f"{worst_arm:>13s} {excess:>+8.4f} {ez:>+6.2f}"
            )
    _bh(cells, "mirror")


def dose_table(rows: list[dict]) -> None:
    by: dict[tuple, dict] = defaultdict(dict)
    for r in rows:
        if r["kind"] != "cell" or r.get("dose_slope") is None:
            continue
        key = (r["interval"], r["feed"], r["distance"], r["side"])
        if r["arm"] == "real":
            by[key]["real"] = r
        else:
            by[key].setdefault(r["arm"], []).append(r["dose_slope"])

    print("\n" + "=" * 104)
    print("DOSE: reach rate per extra level in the path, within volatility quintiles.")
    print("A barrier predicts a NEGATIVE slope on both sides.")
    print("=" * 104)
    cells: list[tuple] = []
    for interval in ("15m", "1h", "1d"):
        got = sorted(k for k in by if k[0] == interval and "real" in by[k])
        if not got:
            continue
        print(f"\n--- {interval} ---")
        print(
            f"{'feed':9s} {'d':>4s} {'side':>5s} {'slope':>8s} {'sd':>7s} {'z':>6s} "
            f"{'mono':>5s} | {'nulls: garch':>13s} {'walk':>8s} {'shuf':>8s} {'excess':>8s}"
        )
        for key in got:
            real = by[key]["real"]
            means = {
                a: (st.fmean(by[key][a]) if by[key].get(a) else float("nan")) for a in NULLS
            }
            draws = [v for a in NULLS for v in by[key].get(a, [])]
            sd = real["dose_sd"] or 0.0
            excess, ez = _excess(real["dose_slope"], draws, sd, want=-1)
            cells.append((key, excess, ez))
            print(
                f"{key[1]:9s} {key[2]:>4.1f} {key[3]:>+5d} {real['dose_slope']:>+8.4f} "
                f"{sd:>7.4f} {real['dose_slope'] / sd if sd else 0:>+6.2f} "
                f"{'y' if real['dose_monotone'] else 'n':>5s} | "
                f"{means['garch-bars']:>+13.4f} {means['walk-geometry']:>+8.4f} "
                f"{means['bar-shuffle']:>+8.4f} {excess:>+8.4f}"
            )
    _bh(cells, "dose")


def asymmetry(rows: list[dict]) -> None:
    """Is the effect the same size above and below, on the real arm?

    The user's question. Reported as the per-feed difference between the up
    and down dose slope, against the same difference on the null arms - a
    series with a drift produces one by itself, so the nulls are what say
    whether an asymmetry is about levels or about the sample's direction.
    """
    got: dict[tuple, dict] = defaultdict(dict)
    for r in rows:
        if r["kind"] != "cell" or r.get("dose_slope") is None:
            continue
        got[(r["arm"], r["interval"], r["feed"], r["distance"])][r["side"]] = r["dose_slope"]

    print("\n" + "=" * 104)
    print("ASYMMETRY: up-side dose slope minus down-side, per feed, real against the nulls.")
    print("=" * 104)
    per: dict[tuple, list[float]] = defaultdict(list)
    for (arm, interval, feed, _d), sides in got.items():
        if 1 in sides and -1 in sides:
            per[(arm, interval, feed)].append(sides[1] - sides[-1])
    print(f"{'interval':9s} {'feed':9s} {'real':>8s} {'garch':>8s} {'walk':>8s} {'shuf':>8s}")
    for interval in ("15m", "1h", "1d"):
        for feed in sorted({k[2] for k in per if k[1] == interval}):
            vals = []
            for arm in ("real", *NULLS):
                v = per.get((arm, interval, feed), [])
                vals.append(st.fmean(v) if v else float("nan"))
            print(
                f"{interval:9s} {feed:9s} {vals[0]:>+8.4f} {vals[1]:>+8.4f} "
                f"{vals[2]:>+8.4f} {vals[3]:>+8.4f}"
            )


def race_table(rows: list[dict]) -> None:
    print("\n" + "=" * 104)
    print("RACES on the real arm: target vs stop, against 1/(1+N). Entry-agnostic anchors.")
    print("=" * 104)
    by: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        if r["kind"] == "race" and r["arm"] == "real":
            by[(r["interval"], r["target"], r["stop"])].append(r)
    print(
        f"{'interval':9s} {'T':>4s} {'S':>4s} {'feeds':>6s} {'n':>7s} {'won':>7s} "
        f"{'1/(1+N)':>8s} {'edge R':>8s} {'sd':>7s} {'z':>6s} {'ties':>6s}"
    )
    for key in sorted(by, key=lambda k: (("15m", "1h", "1d").index(k[0]), k[1], k[2])):
        got = by[key]
        n = sum(g["n"] for g in got)
        won = sum(g["won"] * g["n"] for g in got) / n
        edge = sum(g["edge_r"] * g["n"] for g in got) / n
        sd = math.sqrt(sum((g["n"] / n) ** 2 * g["sd"] ** 2 for g in got))
        ties = sum(g["ties"] * g["n"] for g in got) / n
        print(
            f"{key[0]:9s} {key[1]:>4.1f} {key[2]:>4.1f} {len(got):>6d} {n:>7d} {won:>7.4f} "
            f"{got[0]['expected']:>8.4f} {edge:>+8.4f} {sd:>7.4f} "
            f"{edge / sd if sd else 0:>+6.2f} {ties:>6.3f}"
        )


def _bh(cells: list[tuple], label: str) -> None:
    usable = [(k, e, z) for k, e, z in cells if not math.isnan(z)]
    if not usable:
        return
    ps = [two_sided_p(z) for _, _, z in usable]
    keep = benjamini_hochberg(ps, 0.10)
    survivors = [(k, e, z, p) for (k, e, z), p, ok in zip(usable, ps, keep, strict=True) if ok]
    print(
        f"\n{label}: {len(usable)} cells against the hardest null, "
        f"{sum(1 for _, _, z in usable if z > 2)} with z > +2 nominally, "
        f"{len(survivors)} surviving Benjamini-Hochberg at q=0.10."
    )
    for key, excess, z, p in sorted(survivors, key=lambda x: -x[2])[:12]:
        print(f"    {key} excess {excess:+.4f} z {z:+.2f} p {p:.4g}")


def main(path: str) -> None:
    rows = load(path)
    arms = {r["arm"] for r in rows}
    feeds = sorted({r["feed"] for r in rows})
    print(f"{len(rows)} rows, arms {sorted(arms)}")
    print(f"{len(feeds)} feeds: {', '.join(feeds)}")
    for r in rows:
        if r["kind"] == "cell" and r["arm"] == "real" and r["distance"] == 1.0 and r["side"] == 1:
            print(f"  {r['feed']:9s} {r['interval']:4s} {r['venue']:12s} "
                  f"{r['bars']:>6d} bars {r['days']:>7.1f} days")
    mirror_table(rows)
    dose_table(rows)
    asymmetry(rows)
    race_table(rows)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "/tmp/shield.jsonl")
