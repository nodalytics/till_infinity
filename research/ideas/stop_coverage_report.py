"""Render the stop-coverage panel: the tables the write-up is made of.

`uv run python -m research.ideas.stop_coverage_report <dir>/stop_coverage.jsonl`

Nothing is selected here. Every table is the whole grid - per feed, per side,
per arm - because `pooled-medians-invert-subgroups` is the recorded failure: a
pooled median once agreed with a claim that every subgroup refuted. Where a
pooled line appears it is a median over per-feed readings and is labelled as
one.

The null test is **hardest-of-N**: a cell passes when the real statistic falls
outside every draw of the arm whose draws come closest to it. That bar rises
with the draw count, so the pass count at 16 draws is not comparable with one
at 4 without saying so - and 16 is the minimum, because `fear-greed.md`
measured four draws to be anti-conservative on an arm whose own sd is 0.09 to
0.12, turning +0.093 into -0.037 on the same data.
"""

import json
import statistics as st
import sys
from collections import defaultdict

import research.ideas.stop_coverage as S

ARMS = ("vol-3", "vol-3-N20", "t-fixed", "t-sqrt-h", "quantile", "quantile-seated")
NULLS = ("garch-bars", "walk-geometry", "bar-shuffle")
TARGET = 1.0 - S.TAU


def load(path: str) -> list[dict]:
    with open(path) as fh:
        return [json.loads(line) for line in fh if line.strip()]


def pick(rows: list[dict], **where) -> list[dict]:
    return [r for r in rows if all(r.get(k) == v for k, v in where.items())]


def cell(row: dict) -> str:
    return f"{row['feed']}.{row['interval']}"


def _fmt(value, spec: str = "6.3f") -> str:
    return "-" if value is None else f"{value:{spec}}"


# ───────────────────────────── the headline ─────────────────────────────


def headline(rows: list[dict], horizon: int, unit: str = "close") -> None:
    """Realised coverage of every arm, per feed, per side, at one horizon."""
    got = pick(rows, kind="cover", arm="real", unit=unit, step="nonoverlap", horizon=horizon)
    print(f"\n## Coverage at H = {horizon}, unit `{unit}`, non-overlapping, target {TARGET:.3f}\n")
    print("| feed | interval | venue | side | n | " + " | ".join(ARMS) + " |")
    print("|---|---|---|---:|---:|" + "---:|" * len(ARMS))
    for key in sorted({(r["feed"], r["interval"], r["venue"]) for r in got}):
        for side in (1, -1):
            here = [
                r
                for r in got
                if (r["feed"], r["interval"], r["venue"]) == key and r["side"] == side
            ]
            if not here:
                continue
            by_arm = {r["arm_stop"]: r for r in here}
            n = max(r["n"] for r in here)
            marks = []
            for arm in ARMS:
                found = by_arm.get(arm)
                if found is None:
                    marks.append("-")
                    continue
                flag = "**" if found["calibrated"] else ""
                marks.append(f"{flag}{found['rate']:.3f}{flag}")
            print(
                f"| {key[0]} | {key[1]} | {key[2]} | {side:+d} | {n} | " + " | ".join(marks) + " |"
            )
    print(
        "\n`**` marks a cell whose 95% interval holds 0.100, where the interval is the "
        "wider of the binomial and 1.96 block-bootstrap sds."
    )


def widths(rows: list[dict], horizon: int, unit: str = "close") -> None:
    """The stop distance each arm actually placed, and what it cost."""
    got = pick(rows, kind="cover", arm="real", unit=unit, step="nonoverlap", horizon=horizon)
    print(f"\n## Stop distance in volatility units, H = {horizon}\n")
    print("| feed | interval | side | " + " | ".join(ARMS) + " | unaffordable arms |")
    print("|---|---|---:|" + "---:|" * len(ARMS) + "---|")
    for key in sorted({(r["feed"], r["interval"]) for r in got}):
        for side in (1, -1):
            here = [r for r in got if (r["feed"], r["interval"]) == key and r["side"] == side]
            if not here:
                continue
            by_arm = {r["arm_stop"]: r for r in here}
            dear = sorted({r["arm_stop"] for r in here if r.get("afford")})
            # **Absent is not zero.** A feed with no recorded quotes has an
            # unmeasurable cost, which `affordable` returns as an empty string
            # for its own good reason - a trade attributed to the wrong gate is
            # a per-gate count that cannot be read. Printing that as "none"
            # would read as "every arm clears the limit", which is a different
            # claim and one this data cannot make.
            priced_here = any(r.get("spread_bps", 0.0) > 0.0 for r in here)
            verdict = (
                (", ".join(dear) or "none") if priced_here else "*no spread measured*"
            )
            cells = [
                _fmt(by_arm[arm]["stop_median"], "6.2f") if arm in by_arm else "-" for arm in ARMS
            ]
            print(
                f"| {key[0]} | {key[1]} | {side:+d} | " + " | ".join(cells) + f" | {verdict} |"
            )


def ranking(rows: list[dict], horizon: int, unit: str = "close") -> None:
    """The pre-registered pass rules, counted.

    Rule 3 is the incumbent comparison and rule 4 is the one that decides
    whether the extra state is earned: beating `t-fixed` at `H` > 1 is a
    missing square root, so the baseline is `t-sqrt-h`.
    """
    got = pick(rows, kind="cover", arm="real", unit=unit, step="nonoverlap", horizon=horizon)
    by_cell: dict[tuple, dict[str, dict]] = defaultdict(dict)
    for r in got:
        by_cell[(r["feed"], r["interval"], r["side"])][r["arm_stop"]] = r
    print(f"\n## Arm ranking at H = {horizon}: mean |excess| and calibrated cells\n")
    print("| arm | cells | mean \\|excess\\| | median \\|excess\\| | calibrated | median stop |")
    print("|---|---:|---:|---:|---:|---:|")
    for arm in ARMS:
        here = [c[arm] for c in by_cell.values() if arm in c]
        if not here:
            continue
        excess = [abs(r["excess"]) for r in here]
        print(
            f"| {arm} | {len(here)} | {st.fmean(excess):.4f} | {st.median(excess):.4f} | "
            f"{sum(1 for r in here if r['calibrated'])}/{len(here)} | "
            f"{st.median([r['stop_median'] for r in here]):.2f} |"
        )
    print("\n### Pass rules\n")
    for challenger, baseline in (
        ("quantile", "vol-3"),
        ("quantile-seated", "vol-3"),
        ("quantile", "t-sqrt-h"),
        ("quantile-seated", "t-sqrt-h"),
        ("t-sqrt-h", "vol-3"),
    ):
        wins = sides = 0
        by_feed: dict[tuple, list[bool]] = defaultdict(list)
        for key, arms in by_cell.items():
            if challenger not in arms or baseline not in arms:
                continue
            better = abs(arms[challenger]["excess"]) < abs(arms[baseline]["excess"])
            wins += better
            sides += 1
            by_feed[(key[0], key[1])].append(better)
        both = sum(1 for v in by_feed.values() if len(v) == 2 and all(v))
        share = wins / sides if sides else 0.0
        verdict = "pass" if share >= 2 / 3 and both >= 2 / 3 * len(by_feed) else "fail"
        print(
            f"- `{challenger}` better calibrated than `{baseline}` on **{wins}/{sides}** cells "
            f"({share:.0%}) and on both sides of **{both}/{len(by_feed)}** feeds - "
            f"**{verdict}** against the two-thirds rule."
        )


# ───────────────────────────── the sweeps ─────────────────────────────


def horizons(rows: list[dict], unit: str = "close") -> None:
    """Does the verdict depend on the horizon? The whole point of declaring it."""
    got = pick(rows, kind="cover", arm="real", unit=unit, step="nonoverlap")
    print(f"\n## Horizon sweep, unit `{unit}`: median realised rate over feeds and sides\n")
    hs = sorted({r["horizon"] for r in got})
    print("| arm | " + " | ".join(f"H={h}" for h in hs) + " | median n |")
    print("|---|" + "---:|" * (len(hs) + 1))
    for arm in ARMS:
        line = []
        counts = []
        for h in hs:
            here = [r for r in got if r["horizon"] == h and r["arm_stop"] == arm]
            line.append(f"{st.median([r['rate'] for r in here]):.3f}" if here else "-")
            counts.extend(r["n"] for r in here)
        if not counts:
            continue
        print(f"| {arm} | " + " | ".join(line) + f" | {int(st.median(counts))} |")


def unit_check(rows: list[dict], horizon: int) -> None:
    """A coverage reading that depends on the sigma estimator is not one.

    The two differ by 1.015x on eurusd and **0.755x on gold** on real bars, so
    this is a check with teeth rather than a formality.
    """
    print(f"\n## Unit sensitivity at H = {horizon}: close-EWMA against Parkinson range\n")
    print("| feed | interval | arm | close | range | delta |")
    print("|---|---|---|---:|---:|---:|")
    for arm in ARMS:
        close = pick(
            rows, kind="cover", arm="real", unit="close", step="nonoverlap", horizon=horizon
        )
        ranged = pick(
            rows, kind="cover", arm="real", unit="range", step="nonoverlap", horizon=horizon
        )
        index = {(r["feed"], r["interval"], r["side"], r["arm_stop"]): r for r in ranged}
        for r in close:
            if r["arm_stop"] != arm or r["side"] != 1:
                continue
            other = index.get((r["feed"], r["interval"], 1, arm))
            if other is None:
                continue
            print(
                f"| {r['feed']} | {r['interval']} | {arm} | {r['rate']:.3f} | "
                f"{other['rate']:.3f} | {other['rate'] - r['rate']:+.3f} |"
            )


def overlap(rows: list[dict], horizon: int, unit: str = "close") -> None:
    """Dense against non-overlapping, fixed arms only.

    The point estimates must agree; what differs is the sample the standard
    error is read off, and `overlapping-windows-inflate-permutation-nulls` is
    why the headline is the non-overlapping one.
    """
    print(f"\n## Overlap check at H = {horizon}, fixed arms: dense against non-overlapping\n")
    spaced = pick(rows, kind="cover", arm="real", unit=unit, step="nonoverlap", horizon=horizon)
    dense = pick(rows, kind="cover", arm="real", unit=unit, step="dense", horizon=horizon)
    index = {(r["feed"], r["interval"], r["side"], r["arm_stop"]): r for r in dense}
    print(
        "| feed | interval | side | arm | n spaced | rate spaced | block sd | n dense "
        "| rate dense | block sd | binomial sd |"
    )
    print("|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|")
    for r in sorted(spaced, key=lambda x: (x["feed"], x["interval"], -x["side"], x["arm_stop"])):
        other = index.get((r["feed"], r["interval"], r["side"], r["arm_stop"]))
        if other is None:
            continue
        binomial = (TARGET * (1.0 - TARGET) / other["n"]) ** 0.5
        print(
            f"| {r['feed']} | {r['interval']} | {r['side']:+d} | {r['arm_stop']} | "
            f"{r['n']} | {r['rate']:.3f} | {r.get('sd_block', 0.0):.4f} | {other['n']} | "
            f"{other['rate']:.3f} | {other.get('sd_block', 0.0):.4f} | {binomial:.4f} |"
        )
    print(
        "\nThe dense stream's **block sd against its binomial sd** is the reading that "
        "matters: a binomial interval over windows that share H-1 of H bars describes a "
        "sample this study does not have, and the block is the overlap length in anchors "
        "rather than a calendar day - on daily bars a day holds one anchor, so a day block "
        "reads 1.35x the binomial where the overlap block reads several times it."
    )


def gains(rows: list[dict], horizon: int) -> None:
    """The gain sweep: is the online arm miscalibrated or merely unconverged?

    Reported as a grid on the mean. `sweep-thresholds-on-the-mean-not-z` is the
    recorded failure - a z grid faked a ridge at the chosen threshold where the
    mean grid was monotone.
    """
    got = pick(rows, kind="gain", arm="real", horizon=horizon)
    if not got:
        return
    print(f"\n## Gain sweep at H = {horizon}: `GAIN` 0.02 ships\n")
    print("| arm | gain | median rate | median rate (2nd half) | median final stop |")
    print("|---|---:|---:|---:|---:|")
    for arm in ("quantile", "quantile-seated"):
        for gain in sorted({r["gain"] for r in got}):
            here = [r for r in got if r["arm_stop"] == arm and r["gain"] == gain]
            if not here:
                continue
            print(
                f"| {arm} | {gain:.2f} | {st.median([r['rate'] for r in here]):.3f} | "
                f"{st.median([r['rate_late'] for r in here]):.3f} | "
                f"{st.median([r['stop_last'] for r in here]):.2f} |"
            )


# ───────────────────────────── the nulls ─────────────────────────────


def _hardest(real: float, draws: dict[str, list[float]]) -> tuple[str, float, float, float]:
    """`(arm, lo, hi, p)` for the arm whose draws come closest to `real`.

    The deciding arm is the one the real reading beats by least, which is
    `let-the-shuffled-twin-name-the-mechanical-observables`: use the
    highest-powered arm rather than each arm's own, because a definitional
    effect shows up in the twin.
    """
    best = ("", -1e18, 1e18, 0.0)
    for arm, values in draws.items():
        if not values:
            continue
        beyond = sum(1 for v in values if abs(v) >= abs(real))
        p = (1.0 + beyond) / (1.0 + len(values))
        if p > best[3]:
            best = (arm, min(values), max(values), p)
    return best


def nulls(rows: list[dict], horizon: int, unit: str = "close") -> None:
    """Real coverage error against the null arms', per cell.

    **This is a diagnostic and not a significance test, and the direction has
    to be named or the table is unreadable.** Predicted before the run:
    `vol-3` and `t-fixed` should be about as miscalibrated on a walk as on the
    market, because their error is a horizon-and-scale mistake rather than a
    market fact - so a null that *reproduces* the error is the informative
    outcome, and `inside` is the expected verdict rather than a failure.

    An extremeness `p` would be the wrong statistic here. For a coverage error
    the interesting direction is real being **less** miscalibrated than every
    surrogate of itself, which is the opposite tail from the one a
    two-sided permutation p measures, so each cell is reported as `below`,
    `inside` or `above` the whole null span across all three arms.
    """
    got = pick(rows, kind="cover", unit=unit, step="nonoverlap", horizon=horizon)
    print(f"\n## Null arms at H = {horizon}: real coverage error against the draws\n")
    print(
        "| feed | interval | side | arm | real \\|excess\\| | null \\|excess\\| span "
        "| draws | where |"
    )
    print("|---|---|---:|---|---:|---|---:|---|")
    tally: dict[str, int] = defaultdict(int)
    for key in sorted({(r["feed"], r["interval"], r["side"], r["arm_stop"]) for r in got}):
        here = [
            r
            for r in got
            if (r["feed"], r["interval"], r["side"], r["arm_stop"]) == key
        ]
        real = next((r for r in here if r["arm"] == "real"), None)
        spread = [abs(r["excess"]) for r in here if r["arm"] in NULLS]
        if real is None or not spread:
            continue
        mine = abs(real["excess"])
        where = "below" if mine < min(spread) else "above" if mine > max(spread) else "inside"
        tally[where] += 1
        print(
            f"| {key[0]} | {key[1]} | {key[2]:+d} | {key[3]} | {mine:.3f} | "
            f"[{min(spread):.3f}, {max(spread):.3f}] | {len(spread)} | **{where}** |"
        )
    total = sum(tally.values())
    print(
        f"\n**{tally['below']} below / {tally['inside']} inside / {tally['above']} above** "
        f"of {total} cells, against every draw of all three arms. `inside` is the "
        f"pre-registered expectation for the two fixed arms; `below` says the market is "
        f"better calibrated by that stop than any surrogate of itself, which is a "
        f"statement about the surrogate's range-to-sigma geometry and not about an edge."
    )


def ratios(rows: list[dict], horizon: int, unit: str = "close") -> None:
    """The per-side asymmetry: `stop(-1) / stop(+1)`, real against the nulls.

    **The statistic that decides whether anything adaptive is needed.** The
    module's own tests show the fixed t loses only where a side's scale
    differs, at 1.3x. Compared against the arms rather than against 1.0,
    because a one-sided drift produces a ratio with no volatility asymmetry at
    all - and `walk-geometry` resamples steps i.i.d. so it keeps the mean
    step, while `garch-bars` draws zero-mean innovations and does not.
    """
    got = pick(rows, kind="ratio", unit=unit, horizon=horizon)
    print(f"\n## Per-side stop ratio at H = {horizon}: stop(-1) / stop(+1)\n")
    print("| feed | interval | arm | real | garch-bars | walk-geometry | bar-shuffle | hardest | p |")
    print("|---|---|---|---:|---|---|---|---|---:|")
    for key in sorted({(r["feed"], r["interval"], r["arm_stop"]) for r in got}):
        here = [r for r in got if (r["feed"], r["interval"], r["arm_stop"]) == key]
        real = next((r for r in here if r["arm"] == "real"), None)
        if real is None:
            continue
        spans = {}
        for arm in NULLS:
            values = [r["ratio"] for r in here if r["arm"] == arm]
            spans[arm] = values
        arm, lo, hi, p = _hardest(real["ratio"] - 1.0, {k: [v - 1.0 for v in s] for k, s in spans.items()})
        shown = [
            f"[{min(spans[a]):.2f}, {max(spans[a]):.2f}]" if spans[a] else "-" for a in NULLS
        ]
        print(
            f"| {key[0]} | {key[1]} | {key[2]} | {real['ratio']:.3f} | "
            + " | ".join(shown)
            + f" | {arm or '-'} | {p:.3f} |"
        )


def plants(rows: list[dict], horizon: int) -> None:
    """Power: what each plant moves, and where the test goes blind.

    Each sweep starts at its own zero control. **A plant whose zero cell reads
    an effect is rejected** and its question is left untested rather than null;
    `level-bounce.md` discarded a pure-order plant that read -0.180 at z -4.76
    with nothing planted.
    """
    got = pick(rows, kind="plant", horizon=horizon)
    if not got:
        return
    print(f"\n## Power at H = {horizon}: planted effects and their zero controls\n")
    for plant in sorted({r["plant"] for r in got}):
        print(f"\n### `{plant}`\n")
        here = [r for r in got if r["plant"] == plant]
        strengths = sorted({r["strength"] for r in here})
        print(
            "| feed | strength | side ratio | "
            + " | ".join(f"{a} rate" for a in ("vol-3", "t-sqrt-h", "quantile-seated"))
            + " |"
        )
        print("|---|---:|---:|---:|---:|---:|")
        for feed in sorted({r["feed"] for r in here}):
            for strength in strengths:
                sub = [r for r in here if r["feed"] == feed and r["strength"] == strength]
                if not sub:
                    continue
                ratio = next((r["ratio"] for r in sub if r.get("ratio") is not None), None)
                cells = []
                for arm in ("vol-3", "t-sqrt-h", "quantile-seated"):
                    rates = [r["rate"] for r in sub if r["arm_stop"] == arm]
                    cells.append(f"{st.fmean(rates):.3f}" if rates else "-")
                mark = " *(control)*" if strength in (0.0, 1.0) else ""
                print(
                    f"| {feed} | {strength:g}{mark} | {_fmt(ratio, '5.3f')} | "
                    + " | ".join(cells)
                    + " |"
                )


def priced(rows: list[dict], horizon: int) -> None:
    """The secondary. Mean R is a ranking of 1/width; `per_sigma` is not.

    `widestop.md` measured mean R at `m` times the stop to be the 1x mean over
    `m` in every row, with price P&L in units of the base risk not moving.
    """
    got = pick(rows, kind="priced", arm="real", horizon=horizon)
    if not got:
        return
    print(f"\n## Secondary: mean R at H = {horizon}, costed feeds, 15m, spread charged\n")
    print(
        "| feed | venue | live | side | arm | n | stop | stopped | mean R | sd | "
        "P&L per sigma | sd | cost share |"
    )
    print("|---|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    width = {
        (r["feed"], r["interval"], r["side"], r["arm_stop"]): r["stop_median"]
        for r in pick(rows, kind="cover", arm="real", unit="close", step="nonoverlap", horizon=horizon)
    }
    for r in sorted(got, key=lambda x: (x["feed"], -x["side"], x["arm_stop"])):
        key = (r["feed"], r["interval"], r["side"], r["arm_stop"])
        print(
            f"| {r['feed']} | {r['venue']} | {'yes' if r['live_venue'] else '**no**'} | "
            f"{r['side']:+d} | {r['arm_stop']} | {r['n']} | {_fmt(width.get(key), '5.2f')} | "
            f"{r['stopped']:.3f} | {r['mean_r']:+.3f} | {r['sd_r']:.3f} | "
            f"{r['per_sigma']:+.4f} | {r['sd_per_sigma']:.4f} | {r['cost_share']:.3f} |"
        )
    print(
        "\n`live` **no** marks `us100` and `spx500`, which are not the venue the live desk "
        "trades. Mean R is not comparable across arms - the arms span a factor of five in "
        "width and `widestop.md` measured mean R at m times the stop to be the 1x mean over "
        "m - so `P&L per sigma` is the comparable column."
    )


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: stop_coverage_report <stop_coverage.jsonl>")
    rows = load(sys.argv[1])
    horizon = int(sys.argv[2]) if len(sys.argv) > 2 else S.HORIZON
    feeds = sorted({(r["feed"], r["interval"], r["venue"], r["bars"], r["days"]) for r in rows})
    print("# Stop coverage: the panel\n")
    print("| feed | interval | venue | bars | days |")
    print("|---|---|---|---:|---:|")
    for feed, interval, venue, bars, days in feeds:
        print(f"| {feed} | {interval} | {venue} | {bars} | {days} |")
    headline(rows, horizon)
    widths(rows, horizon)
    ranking(rows, horizon)
    horizons(rows)
    unit_check(rows, horizon)
    overlap(rows, horizon)
    gains(rows, horizon)
    # Power before any null, which is the order the rule is written in: a null
    # without the strength at which the test goes blind is not a reading.
    plants(rows, horizon)
    nulls(rows, horizon)
    ratios(rows, horizon)
    priced(rows, horizon)


if __name__ == "__main__":
    main()
