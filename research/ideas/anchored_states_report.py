"""The tables for the anchored-states study, in the order the prereg fixes.

    uv run python -m research.ideas.anchored_states_report <dir>

Coverage first, before any result, because a reader cannot judge a null
without knowing what was measurable: at 15m and 1h a de-overlapped
non-overlapping block of 48 bars leaves about 70 rows an instrument, which is
below the ~100 at which this desk's own standing note says the prior is noise.

Every pass count is quoted against **its own** chance expectation and that
expectation's Poisson spread. `stop-anchor.md` is the reason: a hardcoded "12
draws give about 10.8" printed whatever `--draws` was set to, understated the
bar fourfold, and made 3 of 140 cells read as "far below chance".
"""

from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import research.ideas.anchored_states as A
import research.ideas.anchored_states_agg as G
from till_infinity.domain.costs import MAX_SPREAD_RISK_FRACTION

#: The stop distance a dispersion reading would have to move to be worth
#: acting on. `risk-vol-is-not-the-stop-distance`: the stop is
#: `Intent.stop_vol`, whose measured median is 3.0 volatility units, and
#: `MAX_SPREAD_RISK_FRACTION` is 0.16 **of the risk**. So an effect smaller
#: than `0.16 x 3.0` volatility units cannot reach the stop it would move.
STOP_VOL = 3.0
REACHABLE = MAX_SPREAD_RISK_FRACTION * STOP_VOL


def load(path: Path, name: str) -> list[dict]:
    file = path / name
    if not file.exists():
        return []
    return [json.loads(line) for line in file.read_text().splitlines() if line.strip()]


def _fmt(value: float | None, width: int = 8, places: int = 4) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return " " * (width - 1) + "-"
    return f"{value:>+{width}.{places}f}"


def failures(rows: list[dict]) -> None:
    """Every job that raised, **before any result**.

    A job that died is a missing cell, and a missing cell is not a null. The
    runner turns an exception into one of these rather than taking the whole
    panel down with it.
    """
    if not rows:
        return
    print(f"\n=== {len(rows)} JOBS FAILED - these cells are missing, not null ===\n")
    for row in rows:
        print(f"  {' '.join(row['job'])}: {row['error']}")
        for line in row.get("where") or []:
            print(f"      {line.strip()}")


def coverage(rows: list[dict]) -> None:
    print("\n=== coverage actually run, before any result ===\n")
    print(
        f"{'feed':10s} {'venue':12s} {'int':4s} {'bars':>6s} {'years':>6s} {'rows':>5s} "
        f"{'stride':>7s} {'blk':>4s} {'refused':>8s} {'dead':>5s}  levels seen per anchor"
    )
    for row in sorted(rows, key=lambda r: (r["interval"], r["feed"])):
        seen = ",".join(f"{k[:4]}:{v}" for k, v in row["levels_seen"].items())
        tag = " (placebo)" if row["placebo"] else ""
        print(
            f"{row['feed']:10s} {row['venue']:12s} {row['interval']:4s} {row['bars']:>6d} "
            f"{row['days'] / 365.25:>6.2f} {row['anchors']:>5d} {row['stride']:>7.1f} "
            f"{row['block_rows']:>4d} {row['refused']:>8d} {row.get('dead', 0):>5d}  "
            f"{seen}{tag}"
        )


def _verdicts(cells: list[dict], outcome: str, part: str) -> list[tuple[dict, G.Verdict]]:
    out: list[tuple[dict, G.Verdict]] = []
    for cell in cells:
        if cell["outcome"] != outcome or cell.get(part) is None:
            continue
        arms = {
            name: got
            for name, got in cell[f"arms_{part}"].items()
            if name in A.DECIDING_ARMS
        }
        got = G.judge(cell[part]["effect"], cell[part]["effect_sd"], arms)
        if got is not None:
            out.append((cell, got))
    return out


def claim(cells: list[dict], outcome: str, label: str) -> list[tuple[dict, G.Verdict]]:
    found = _verdicts(cells, outcome, "all")
    if not found:
        print(f"\n=== {label}: no measurable cell ===")
        return []
    draws = max(v.draws for _c, v in found)
    beats = [(c, v) for c, v in found if v.beats_hardest]
    mean, sd = G.expected_passes(len(found), draws)
    ps = [v.p for _c, v in found]
    survivors = G.benjamini_hochberg(ps)
    print(f"\n=== {label} ===\n")
    print(
        f"{len(found)} measurable cells of {len(cells) // 2} attempted, {draws} null draws each.\n"
        f"beating the hardest null draw: {len(beats)} against {mean:.1f} +- {sd:.1f} by chance.\n"
        f"surviving Benjamini-Hochberg at q=0.10: {sum(survivors)}.\n"
        f"real below its hardest arm's mean: {sum(1 for _c, v in found if v.excess < 0)} "
        f"of {len(found)}."
    )
    live = [c["feed"] for c, v in beats if not c["placebo"]]
    print(
        f"non-placebo instruments with a beating cell: {len(set(live))} "
        f"({', '.join(sorted(set(live))) or 'none'}); pass rule 1 needs 3.\n"
        f"placebo cells beating their hardest null: "
        f"{sum(1 for c, v in beats if c['placebo'])} (pass rule 3 fails if any does and survives BH)."
    )

    print(f"\n{'anchor':12s} {'int':4s} {'cells':>5s} {'real':>9s} {'hardest':>9s} "
          f"{'excess':>9s} {'z':>6s} {'beat':>5s} {'v_comp':>7s} {'auc_s':>6s} {'auc_p':>6s}")
    groups: dict[tuple[str, str], list[tuple[dict, G.Verdict]]] = defaultdict(list)
    for cell, got in found:
        groups[(cell["anchor"], cell["interval"])].append((cell, got))
    for key in sorted(groups, key=lambda k: (k[0], k[1])):
        here = groups[key]
        n = len(here)
        aucs = [c["auc_strata"] for c, _v in here if c["auc_strata"] is not None]
        aucp = [c["auc_pooled"] for c, _v in here if c["auc_pooled"] is not None]
        print(
            f"{key[0]:12s} {key[1]:4s} {n:>5d} "
            f"{sum(v.real for _c, v in here) / n:>9.4f} "
            f"{sum(v.hardest_mean for _c, v in here) / n:>9.4f} "
            f"{sum(v.excess for _c, v in here) / n:>+9.4f} "
            f"{sum(v.z for _c, v in here) / n:>+6.2f} "
            f"{sum(1 for _c, v in here if v.beats_hardest):>5d} "
            f"{sum(c['v_comp'] for c, _v in here) / n:>7.3f} "
            f"{(sum(aucs) / len(aucs)) if aucs else float('nan'):>6.3f} "
            f"{(sum(aucp) / len(aucp)) if aucp else float('nan'):>6.3f}"
        )

    #: The rank statistic beside the mean one. `size` has kurtosis 47-74 on
    #: traded feeds, so a cell where the two disagree is tail-driven and the
    #: mean-based reading is the weaker of the two.
    rank_beats, agree, pairs = 0, 0, 0
    for cell, got in found:
        kws = {k: v for k, v in (cell.get("kw_arms_all") or {}).items() if k in A.DECIDING_ARMS}
        every = [x for v in kws.values() for x in v]
        if not every or cell["all"].get("kw") is None:
            continue
        pairs += 1
        over = cell["all"]["kw"] > max(every)
        rank_beats += over
        agree += over == got.beats_hardest
    if pairs:
        print(
            f"\non the within-strata rank statistic instead of the mean: {rank_beats} of "
            f"{pairs} cells beat their hardest null, and the two statistics agree on "
            f"{agree} of {pairs}. A cell where they disagree is tail-driven."
        )
    return found


def instruments(found: list[tuple[dict, G.Verdict]], *, top: int = 3) -> None:
    """The per-feed table for the widest groups. **Never only pooled.**

    A pooled median on this desk once agreed with a claim that every subgroup
    refuted (`pooled-medians-invert-subgroups`), and `level-shield.md`'s own
    answer was only visible per instrument: gold read +0.2533 at z +3.18 where
    spx500 read -0.2595 at z -2.81, same interval, same distance.
    """
    groups: dict[tuple[str, str], list[tuple[dict, G.Verdict]]] = defaultdict(list)
    for cell, got in found:
        groups[(cell["anchor"], cell["interval"])].append((cell, got))
    ranked = sorted(
        groups,
        key=lambda k: -sum(v.excess for _c, v in groups[k]) / len(groups[k]),
    )[:top]
    print("\n=== per instrument, for the widest groups ===")
    for key in ranked:
        print(f"\n{key[0]} at {key[1]}:")
        print(
            f"  {'feed':10s} {'real':>9s} {'hardest':>9s} {'excess':>9s} {'z':>6s} "
            f"{'p':>8s} {'arm':>14s} {'rows':>5s} {'kept':>5s}"
        )
        for cell, got in sorted(groups[key], key=lambda pair: -pair[1].excess):
            tag = " placebo" if cell["placebo"] else ""
            print(
                f"  {cell['feed']:10s} {got.real:>9.4f} {got.hardest:>9.4f} "
                f"{got.excess:>+9.4f} {got.z:>+6.2f} {got.p:>8.4f} "
                f"{got.hardest_arm:>14s} {cell['all']['mass']:>5d} "
                f"{cell['all']['kept']:>5.2f}{tag}"
            )


def pass_rule(cells: list[dict], found: list[tuple[dict, G.Verdict]]) -> None:
    """The five criteria, each with the number that decides it."""
    print("\n=== the pass rule, criterion by criterion ===\n")
    if not found:
        print("no measurable cell, so no criterion is reached.")
        return
    draws = max(v.draws for _c, v in found)
    beats = [(c, v) for c, v in found if v.beats_hardest]
    mean, sd = G.expected_passes(len(found), draws)
    live = {c["feed"] for c, _v in beats if not c["placebo"]}
    a = {(c["feed"], c["interval"], c["anchor"]): v for c, v in _verdicts(cells, "size", "a")}
    b = {(c["feed"], c["interval"], c["anchor"]): v for c, v in _verdicts(cells, "size", "b")}
    both = [
        k
        for k in set(a) & set(b)
        if a[k].beats_hardest and b[k].beats_hardest and k[0] not in A.PLACEBO
    ]
    survivors = G.benjamini_hochberg([v.p for _c, v in found])
    placebo_pass = [c["feed"] for c, _v in beats if c["placebo"]]
    duty_hardest = sum(1 for _c, v in found if v.hardest_arm == "duty-twin")
    rows = [
        (
            "1. beats the hardest null within strata, 3+ instruments, both halves",
            f"{len(beats)} cells beat theirs against {mean:.1f} +- {sd:.1f} by chance; "
            f"{len(live)} non-placebo instruments (needs 3); "
            f"{len(both)} cells beat in both halves",
            len(live) >= 3 and len(both) > 0,
        ),
        (
            "2. survives Benjamini-Hochberg over every cell",
            f"{sum(survivors)} of {len(found)} survive at q=0.10",
            sum(survivors) > 0,
        ),
        (
            "3. the placebo pair does not pass",
            f"{len(placebo_pass)} placebo cells beat their hardest null "
            f"({', '.join(sorted(set(placebo_pass))) or 'none'})",
            len(placebo_pass) == 0,
        ),
        (
            "4. the duty-cycle twin does not pass",
            f"subsumed by criterion 1 - the twin is one of the four deciding arms, so a "
            f"cell beating its hardest null draw has already beaten all of its duty "
            f"draws. The diagnostic is which arm is hardest: the twin is in "
            f"{duty_hardest} of {len(found)} cells, and where it is, the firing rate is "
            f"the binding constraint rather than the series structure",
            True,
        ),
        (
            "5. the power sweep shows the test could have seen this size",
            "read the power section above",
            None,
        ),
    ]
    for name, detail, ok in rows:
        mark = "-" if ok is None else ("MET" if ok else "NOT MET")
        print(f"  [{mark:>7s}] {name}\n            {detail}")
    verdict = all(ok for _n, _d, ok in rows if ok is not None)
    print(
        f"\nprimary claim: {'PASSES every testable criterion' if verdict else 'FAILS'}. "
        "Passing all five is 'worth a fresh-data test', not an edge: DSR >= 0.95 over the "
        "true trial count is still required before that word is used."
    )


def halves(cells: list[dict], outcome: str) -> None:
    """Pass rule 1's both-halves requirement, cell by cell."""
    print("\n=== both halves of the history (pass rule 1) ===\n")
    a = {(c["feed"], c["interval"], c["anchor"]): v for c, v in _verdicts(cells, outcome, "a")}
    b = {(c["feed"], c["interval"], c["anchor"]): v for c, v in _verdicts(cells, outcome, "b")}
    shared = sorted(set(a) & set(b))
    both = [k for k in shared if a[k].beats_hardest and b[k].beats_hardest]
    print(
        f"{len(shared)} cells measurable in both halves. Beating the hardest null in both: "
        f"{len(both)}.\n"
        f"Half A alone: {sum(1 for k in shared if a[k].beats_hardest)}; "
        f"half B alone: {sum(1 for k in shared if b[k].beats_hardest)}."
    )
    if both:
        print(f"\n{'feed':10s} {'int':4s} {'anchor':12s} {'A real':>9s} {'A hard':>9s} "
              f"{'B real':>9s} {'B hard':>9s}")
        for key in both:
            print(
                f"{key[0]:10s} {key[1]:4s} {key[2]:12s} {a[key].real:>9.4f} "
                f"{a[key].hardest:>9.4f} {b[key].real:>9.4f} {b[key].hardest:>9.4f}"
            )


def duty(cells: list[dict], outcome: str) -> None:
    """Pass rule 4: the firing rate must not be the finding."""
    print("\n=== the duty-cycle twin against the series arms (pass rule 4) ===\n")
    rows: list[tuple[str, float, float, float]] = []
    for cell in cells:
        if cell["outcome"] != outcome:
            continue
        arms = cell["arms_all"]
        twin = arms.get("duty-twin") or []
        series = [x for name, got in arms.items() if name in A.SERIES_ARMS for x in got]
        if not twin or not series:
            continue
        rows.append(
            (
                f"{cell['anchor']}/{cell['interval']}",
                sum(twin) / len(twin),
                sum(series) / len(series),
                max(twin) - max(series),
            )
        )
    if not rows:
        print("no cell carries both a duty twin and a series arm.")
        return
    grouped: dict[str, list[tuple[float, float, float]]] = defaultdict(list)
    for key, a, b, gap in rows:
        grouped[key].append((a, b, gap))
    print(f"{'anchor/int':20s} {'duty mean':>10s} {'series mean':>12s} {'hardest gap':>12s}")
    for key in sorted(grouped):
        here = grouped[key]
        print(
            f"{key:20s} {sum(x[0] for x in here) / len(here):>10.4f} "
            f"{sum(x[1] for x in here) / len(here):>12.4f} "
            f"{sum(x[2] for x in here) / len(here):>+12.4f}"
        )
    harder = sum(1 for _k, a, b, _g in rows if a > b)
    print(
        f"\nthe duty twin's mean exceeds the series arms' in {harder} of {len(rows)} cells. "
        f"A twin that is the harder arm means the statistic reads the state's firing rate."
    )


def magnitude(cells: list[dict], outcome: str) -> None:
    """Is the effect larger than the stop it would have to move?"""
    print("\n=== is any effect reachable? (the second 'uninteresting' clause) ===\n")
    print(
        f"A dispersion reading has to move a stop of {STOP_VOL} volatility units by more than "
        f"{MAX_SPREAD_RISK_FRACTION} of the risk, so the bar is {REACHABLE:.2f} units.\n"
    )
    best: list[tuple[float, dict]] = []
    for cell in cells:
        if cell["outcome"] != outcome or cell.get("all") is None:
            continue
        means = [x for x in cell["all"]["level_mean"] if x is not None]
        if len(means) >= 2:
            best.append((max(means) - min(means), cell))
    best.sort(key=lambda pair: -pair[0])
    reachable = sum(1 for gap, _c in best if gap >= REACHABLE)
    print(f"{reachable} of {len(best)} cells have a level-to-level gap of at least "
          f"{REACHABLE:.2f} units. The ten widest:\n")
    print(f"{'feed':10s} {'int':4s} {'anchor':12s} {'gap':>8s} {'rows':>5s} {'row sd':>8s} "
          f"{'n_eff':>7s} {'n for 2s':>9s}")
    for gap, cell in best[:10]:
        got = cell["all"]
        need = (2.0 * got["row_sd"] / gap) ** 2 if gap > 0 else float("inf")
        print(
            f"{cell['feed']:10s} {cell['interval']:4s} {cell['anchor']:12s} {gap:>8.4f} "
            f"{got['mass']:>5d} {got['row_sd']:>8.3f} {got['n_eff']:>7.1f} {need:>9.0f}"
        )


def marginals(rows: list[dict]) -> None:
    """Does each arm match the real series on the outcome's own scale?

    An arm that does not is not matched on the property it is **not**
    removing, and `a-control-is-only-for-a-named-property` is the rule. This
    is the table that justifies deciding on `effect` rather than `spread`.
    """
    print("\n=== each arm's marginal scale of `size`, against the real series' ===\n")
    got: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for row in rows:
        for arm, (mean, sd) in (row.get("arm_size") or {}).items():
            got[arm].append((mean, sd))
    if not got:
        print("not recorded in this run.")
        return
    base = got.get("real") or []
    ref = sum(m for m, _s in base) / len(base) if base else float("nan")
    print(f"{'arm':20s} {'cells':>5s} {'mean size':>10s} {'sd':>8s} {'vs real':>8s}")
    for arm in sorted(got):
        here = got[arm]
        mean = sum(m for m, _s in here) / len(here)
        sd = sum(s for _m, s in here) / len(here)
        print(f"{arm:20s} {len(here):>5d} {mean:>10.4f} {sd:>8.4f} {mean / ref:>8.3f}")


def arms_diagnostic(cells: list[dict]) -> None:
    """How far the absolute-step arms sit from their log twins, at 1d."""
    print("\n=== absolute-step arms against their log twins, 1d only ===\n")
    pairs = (("walk-geometry", "walk-geometry-abs"), ("bar-shuffle", "bar-shuffle-abs"))
    print(f"{'arm pair':34s} {'cells':>5s} {'log mean':>9s} {'abs mean':>9s} {'abs harder':>11s}")
    for log, abs_ in pairs:
        rows = []
        for cell in cells:
            arms = cell.get("arms_all", {})
            if log in arms and abs_ in arms:
                rows.append((sum(arms[log]) / len(arms[log]), sum(arms[abs_]) / len(arms[abs_])))
        if not rows:
            print(f"{log + ' vs ' + abs_:34s} {'-':>5s}")
            continue
        harder = sum(1 for a, b in rows if b > a)
        print(
            f"{log + ' vs ' + abs_:34s} {len(rows):>5d} "
            f"{sum(a for a, _b in rows) / len(rows):>9.4f} "
            f"{sum(b for _a, b in rows) / len(rows):>9.4f} {harder:>11d}"
        )


def power(rows: list[dict]) -> None:
    print("\n=== power: the planted magnitude effect, and where the test goes blind ===\n")
    print(
        "`delivered` is the picked level's mean absolute log move against the other levels',\n"
        "with no volatility unit in it. It separates the plant arriving from the statistic\n"
        "seeing it, which is what the outcome's **trailing** denominator decides: when two\n"
        "consecutive de-overlapped windows are both planted, the span-20 EWMA at the second\n"
        "anchor has already absorbed the first window's lift and the ratio cancels.\n"
    )
    groups: dict[tuple[str, str, str, str], list[dict]] = defaultdict(list)
    for row in rows:
        groups[(row["feed"], row["interval"], row["anchor"], row.get("plant", "all"))].append(row)
    for key in sorted(groups):
        here = sorted(groups[key], key=lambda r: r["strength"])
        plant = "clock" if here[0]["clock_plant"] else "price-derived"
        print(
            f"{key[0]} {key[1]} {key[2]} [{key[3]}] ({plant} plant on "
            f"{here[0]['picked_share']:.0%} of anchors)"
        )
        print(
            f"  {'strength':>9s} {'delivered':>10s} {'effect':>9s} {'hardest':>9s} "
            f"{'excess':>9s} {'z':>7s} {'beats':>6s} {'level gap':>10s}"
        )
        for row in here:
            got = row["real"]
            means = [x for x in (row["level_mean"] or []) if x is not None]
            gap = max(means) - min(means) if len(means) >= 2 else float("nan")
            hardest = max(
                (max(v) for name, v in row["arms"].items() if name in A.DECIDING_ARMS),
                default=float("nan"),
            )
            print(
                f"  {row['strength']:>9.2f} "
                f"{row.get('delivered') if row.get('delivered') is not None else float('nan'):>10.3f} "
                f"{(got or {}).get('effect', float('nan')):>9.4f} "
                f"{hardest:>9.4f} {_fmt(row['excess'], 9)} {_fmt(row['z'], 7, 2)} "
                f"{str(row['beats_hardest']):>6s} {gap:>10.4f}"
            )
        zero = here[0]
        if zero["strength"] == 0.0:
            verdict = "passes" if (zero["z"] or 0) < 2.0 else "FAILS"
            print(
                f"  zero control {verdict}: z {_fmt(zero['z'], 6, 2).strip()} with nothing "
                f"planted. A plant whose zero cell reads outside its arms is a broken arm, "
                f"not a weak effect."
            )
        print()


def main(argv: list[str] | None = None) -> None:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        raise SystemExit("usage: anchored_states_report <dir>")
    path = Path(args[0])
    panel = load(path, "panel.jsonl")
    series = [r for r in panel if r["kind"] == "series"]
    cells = [r for r in panel if r["kind"] == "cell"]
    meta = json.loads((path / "meta.json").read_text()) if (path / "meta.json").exists() else {}
    print(f"anchored-states: {path}")
    if meta:
        print(
            f"draws {meta.get('draws')} an arm, deciding arms "
            f"{', '.join(meta.get('deciding_arms', []))}, placebo "
            f"{', '.join(meta.get('placebo', []))}"
        )
    failures([r for r in panel if r["kind"] == "error"])
    coverage(series)
    marginals(series)
    power(load(path, "power.jsonl"))
    primary = [c for c in cells if c["outcome"] == "size"]
    found = claim(cells, "size", "primary claim: the next move's magnitude")
    instruments(found)
    halves(cells, "size")
    duty(cells, "size")
    magnitude(cells, "size")
    arms_diagnostic(primary)
    pass_rule(cells, found)
    secondary = claim(cells, "signed", "secondary claim: direction, as an interaction")
    if secondary:
        print(
            "\nthe secondary claim's extra requirement: the state's own direction effect must "
            "also exceed the same state's effect with the sign randomised. The `sign-flip` arm "
            "carries that and is excluded from the deciding set above; its column is below.\n"
        )
        rows = []
        for cell in cells:
            if cell["outcome"] != "signed" or cell.get("all") is None:
                continue
            flips = cell["arms_all"].get("sign-flip") or []
            if flips:
                rows.append((cell["all"]["spread"], max(flips)))
        if rows:
            over = sum(1 for real, flip in rows if real > flip)
            print(
                f"  real exceeds the hardest sign-flip draw in {over} of {len(rows)} cells, "
                f"against {len(rows) / (len(flips) + 1):.1f} by chance."
            )
    print(
        "\ntrial count: "
        f"{len([c for c in cells if c.get('all') is not None])} measurable cells over "
        f"{len(cells)} attempted, counting both outcomes; "
        f"{len([c for c in cells if c.get('a') is not None or c.get('b') is not None])} "
        "more in the two halves. Deflation carries this plus the desk's prior searching."
    )


if __name__ == "__main__":
    main()
