"""Read `level_graph.py`'s cells against the pre-registered pass rule.

Prints coverage first, then the power section, then the verdict - the order
`research/docs/level-graph-prereg.md` fixes, and for the reason it gives: a
reader cannot judge a null without knowing which cells were measurable, and a
cell a guard refused is not a cell that read nothing.

Every error row is printed **before** any result, so a missing cell cannot be
mistaken for a null.
"""

from __future__ import annotations

import collections
import contextlib
import json
import math
import statistics
import sys
from pathlib import Path

#: The arms whose hardest draw the real reading has to beat.
#: `shuffled-twin-names-the-mechanical-observables` says to use the
#: highest-powered shuffled arm rather than each arm's own, so the bar is the
#: hardest draw over **all** arms pooled.
ARMS = ("bar-shuffle", "walk-geometry", "garch-bars")

PLACEBO = ("nzdusd", "usdcad")
CONTROLS = ("Range_Break", "Drift_Switch")

#: A dispersion reading has to move a stop of 3.0 volatility units by more than
#: 0.16 of the risk, so a gap below this cannot be traded whatever its z.
REACHABLE = 0.48


def load(path: Path) -> list[dict]:
    rows = []
    with path.open() as fh:
        for raw in fh:
            text = raw.strip()
            if not text:
                continue
            with contextlib.suppress(json.JSONDecodeError):
                rows.append(json.loads(text))
    return rows


#: Every feed the study asks for at 1d, so the report can say which are
#: **absent from the output** rather than only which raised.
REQUESTED = (
    "eurusd",
    "gbpusd",
    "audusd",
    "usdcad",
    "usdchf",
    "usdjpy",
    "usdcnh",
    "nzdusd",
    "gold",
    "btc",
    "eth",
    "spx500",
    "us100",
    "sol",
)


def failures(rows: list[dict], cells: list[dict]) -> None:
    """What did not run, **including what left no trace at all.**

    The first version of this function looked for `kind == "error"` rows only,
    and printed "nothing: every job returned cells" on a run where **10 of 16
    requested feeds were absent from the output** - the lab had rebooted and
    killed the panel at 6 feeds. A job that dies takes its error row with it,
    so the absence has to be computed from the request rather than read from
    the file. That is the same silent-zero class as every other defect found
    on this desk today.
    """
    bad = [r for r in rows if r.get("kind") == "error"]
    notes = [r for r in rows if r.get("kind") == "note"]
    present = {c["feed"] for c in cells}
    missing = [f for f in REQUESTED if f not in present]

    print("\n=== what did not run, before any result ===\n")
    if missing:
        print(f"  **{len(missing)} of {len(REQUESTED)} requested feeds are ABSENT from the")
        print(f"  output and left no error row**: {', '.join(missing)}")
        print("  A job killed outright takes its error row with it, so this is")
        print("  computed from the request. Coverage below is partial.\n")
    if not bad and not notes and not missing:
        print("  nothing: every requested feed returned cells.")
        return
    for r in bad:
        print(f"  ERROR {r.get('feed')} {r.get('interval')}: {r.get('error')}")
        for line in r.get("where") or []:
            print(f"         {line}")
    for r in notes:
        print(f"  NOTE  {r.get('feed')} {r.get('interval')}: {r.get('note')}")


def coverage(cells: list[dict]) -> None:
    print("\n=== coverage actually run ===\n")
    real = [c for c in cells if c["arm"] == "real"]
    if not real:
        print("  no real cells.")
        return
    by = collections.defaultdict(list)
    for c in real:
        by[(c["feed"], c["venue"], c["interval"])].append(c)
    head = f"{'feed':12s} {'venue':12s} {'int':4s} {'nodes':>6s} {'edges':>6s}"
    print(f"{head} {'cells':>6s} {'pairs':>7s}  note")
    for key in sorted(by):
        rows = by[key]
        tag = ""
        if key[0] in PLACEBO:
            tag = "(placebo)"
        elif key[0] in CONTROLS:
            tag = "(control)"
        print(
            f"{key[0]:12s} {key[1]:12s} {key[2]:4s} "
            f"{max(r['nodes'] for r in rows):6d} {max(r['edges'] for r in rows):6d} "
            f"{len(rows):6d} {sum(r['n_high'] for r in rows):7d}  {tag}"
        )

    # The dwell check the pre-registration demands in advance: a centrality
    # that tracks dwell at r > 0.9 is dwell renamed.
    print("\n  centrality against dwell, rank correlation (>0.9 means it is dwell):")
    for name in sorted({c["centrality"] for c in real}):
        rs = [
            c["dwell_r"]
            for c in real
            if c["centrality"] == name and not math.isnan(c["dwell_r"])
        ]
        if rs:
            print(f"    {name:12s} median {statistics.median(rs):+.3f}  max {max(rs):+.3f}")


def positive_control(cells: list[dict]) -> None:
    """`Range_Break` is a range by construction, so its graph must show two
    dominant nodes with a heavy edge between them. A harness that misses that
    is broken rather than reporting a null."""
    print("\n=== the positive control ===\n")
    for feed in CONTROLS:
        rows = [c for c in cells if c["feed"] == feed and c["arm"] == "real"]
        if not rows:
            print(
                f"  {feed}: **not in this store at any interval or venue**, so the"
                f"\n    positive control cannot be run from `prices.db`. The"
                f"\n    pre-registration named a control that lives in the lab's"
                f"\n    seqlab cache, which is a different source."
            )
            continue
        nodes = max(r["nodes"] for r in rows)
        edges = max(r["edges"] for r in rows)
        per = edges / max(1, nodes)
        print(f"  {feed:14s} nodes {nodes:4d}  edges {edges:5d}  edges/node {per:.2f}")
    print(
        "\n  `Range_Break` must be the denser of the two. If it is not, the\n"
        "  harness cannot see a range it was given by construction and no null\n"
        "  below is reportable - `range-break-is-the-level-positive-control`."
    )


def _rows_for(cells: list[dict]) -> list[dict]:
    keys = ("feed", "interval", "tol", "reach", "centrality", "stratum")
    grouped: dict[tuple, dict[str, list[dict]]] = collections.defaultdict(
        lambda: collections.defaultdict(list)
    )
    for c in cells:
        grouped[tuple(c[k] for k in keys)][c["arm"]].append(c)

    rows = []
    for key, arms in grouped.items():
        real = arms.get("real")
        if not real:
            continue
        draws = [c["gap"] for name in ARMS for c in arms.get(name, [])]
        if len(draws) < 8:
            continue
        hardest = max(draws)
        mean = statistics.fmean(draws)
        sd = statistics.pstdev(draws) if len(draws) > 1 else 0.0
        gap = real[0]["gap"]
        rows.append(
            {
                "feed": key[0],
                "centrality": key[4],
                "stratum": key[5],
                "tol": key[2],
                "reach": key[3],
                "gap": gap,
                "hardest": hardest,
                "excess": gap - hardest,
                "z": (gap - mean) / sd if sd > 0 else 0.0,
                "beats": gap > hardest,
                "n": real[0]["n_high"],
                "draws": len(draws),
            }
        )

    return rows


def verdict(cells: list[dict]) -> None:
    print("\n=== the claim: does centrality beat a distance-matched placebo ===\n")
    rows = _rows_for(cells)
    if not rows:
        print("  no cell carries both a real reading and enough null draws.")
        return

    traded = [r for r in rows if r["feed"] not in PLACEBO and r["feed"] not in CONTROLS]
    placebo = [r for r in rows if r["feed"] in PLACEBO]
    beating = [r for r in traded if r["beats"]]
    chance = len(traded) / (1 + statistics.fmean([r["draws"] for r in rows]))

    draws = statistics.fmean([r["draws"] for r in rows])
    names = sorted({r["feed"] for r in beating})
    print(f"{len(rows)} cells, {len(traded)} on traded instruments, {draws:.0f} null draws each.")
    print(f"beating the hardest null draw: {len(beating)} against {chance:.1f} by chance.")
    print(f"instruments with a beating cell: {len(names)} ({', '.join(names) or 'none'});")
    print("pass rule 1 needs 3.")
    print(f"placebo cells beating their hardest null: {sum(1 for r in placebo if r['beats'])}")
    print("(pass rule 3 fails if any does).")
    below = sum(1 for r in traded if r["gap"] < r["hardest"])
    print(f"real below its hardest arm in {below} of {len(traded)}.")

    print("\nper centrality, traded instruments only:\n")
    cols = f"{'centrality':12s} {'cells':>6s} {'mean gap':>9s}"
    print(f"{cols} {'mean hardest':>13s} {'beats':>6s} {'reachable':>10s}")
    for name in sorted({r["centrality"] for r in traded}):
        rs = [r for r in traded if r["centrality"] == name]
        print(
            f"{name:12s} {len(rs):6d} {statistics.fmean([r['gap'] for r in rs]):+9.4f} "
            f"{statistics.fmean([r['hardest'] for r in rs]):+13.4f} "
            f"{sum(1 for r in rs if r['beats']):6d} "
            f"{sum(1 for r in rs if abs(r['gap']) >= REACHABLE):10d}"
        )

    print("\nper stratum, pooled over centralities - `topology-restates-volatility`")
    print("is the most likely explanation of anything positive, so a pooled")
    print("effect that is not present within strata is volatility:\n")
    print(f"{'stratum':>8s} {'cells':>6s} {'mean gap':>9s} {'beats':>6s}")
    for stratum in sorted({r["stratum"] for r in traded}):
        rs = [r for r in traded if r["stratum"] == stratum]
        print(f"{stratum:8d} {len(rs):6d} {statistics.fmean([r['gap'] for r in rs]):+9.4f} "
              f"{sum(1 for r in rs if r['beats']):6d}")

    reach_n = sum(1 for r in traded if abs(r["gap"]) >= REACHABLE)
    print(f"\nreachability: {reach_n} of {len(traded)} cells have a gap of at least")
    print(f"{REACHABLE} volatility units, which is")
    print("the bar for moving a 3.0-unit stop by more than 0.16 of the risk.")

    print("\nthe ten widest gaps (NOT a result - this is the best of the grid):\n")
    for r in sorted(traded, key=lambda r: -abs(r["gap"]))[:10]:
        print(
            f"  {r['feed']:12s} {r['centrality']:12s} s{r['stratum']} "
            f"tol{r['tol']:<5} reach{r['reach']:<5} n {r['n']:5d} "
            f"gap {r['gap']:+.4f} hardest {r['hardest']:+.4f} z {r['z']:+.2f} "
            f"{'BEATS' if r['beats'] else ''}"
        )

    print("\n=== pass rule, criterion by criterion ===\n")
    met1 = len({r["feed"] for r in beating}) >= 3
    met3 = not any(r["beats"] for r in placebo)
    print(f"  [{'MET' if met1 else 'NOT MET'}] 1. beats the hardest null, 3+ instruments")
    print("  [      -] 2. Benjamini-Hochberg over every cell - needs per-cell p")
    print(f"  [{'MET' if met3 else 'NOT MET'}] 3. no placebo instrument passes")
    print("  [      -] 4. the duty-cycle twin - not in this run's arms")
    print("  [      -] 5. power - the plant sweep is a separate section")
    print(
        f"\nthe claim {'is not refuted by this run' if met1 and met3 else 'FAILS'}. "
        "Passing every criterion would be\n'worth a fresh-data test', not an edge."
    )


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: level_graph_report <cells.jsonl>")
    rows = load(Path(sys.argv[1]))
    cells = [r for r in rows if r.get("kind") == "cell"]
    print(f"level-graph: {sys.argv[1]}")
    print(f"{len(rows)} rows, {len(cells)} cells")
    failures(rows, cells)
    if not cells:
        print("\nno cells: nothing to report, which is not a null.")
        return
    coverage(cells)
    positive_control(cells)
    verdict(cells)


if __name__ == "__main__":
    main()
