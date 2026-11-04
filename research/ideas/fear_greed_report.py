"""The tables in `research/docs/fear-greed.md`, read back out of the JSONL.

    uv run python -m research.ideas.fear_greed_report <dir>

Reads whatever sections are present, so a partial run still prints. Every
table it prints is one a reader of the write-up can check against the raw
rows, which is the point of keeping the report separate from the run: a number
in the document and a number in the harness have to be the same number, and
the only way to keep them so is for one to be computed from the other.

Three rules the tables obey, all from `finding-edges`:

* **per instrument, never only pooled** - `pooled-medians-invert-subgroups`
  records a pooled median here agreeing with a claim every subgroup refuted;
* **a real value is scored against the hardest null arm's range over its
  draws**, not against a p value four draws cannot support;
* **Benjamini-Hochberg over every cell**, because the grid is 13 instruments
  x 2 swing scales x 3 statistics for the asymmetry alone and picking the best
  of those gives a winner every time.
"""

from __future__ import annotations

import collections
import json
import math
import pathlib
import sys

import research.ideas.fear_greed as F


def read(path: pathlib.Path) -> list[dict]:
    """Every parseable row, with a count of the ones that were not.

    Tolerant of a torn final line, because the run writes one JSON object per
    line as it goes so a partial run is readable - and a run stopped partway
    leaves exactly that. Skipped lines are **counted and printed**, never
    silently dropped: a report quietly missing half its cells is worse than one
    that refuses.
    """
    if not path.exists():
        return []
    out: list[dict] = []
    skipped = 0
    with path.open() as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                skipped += 1
    if skipped:
        print(f"  [{path.name}: skipped {skipped} unparseable line(s) - partial run?]")
    return out


def phi(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def benjamini_hochberg(ps: list[float], alpha: float = 0.05) -> list[bool]:
    """Which of `ps` survive BH at `alpha`. `nan` never survives."""
    order = sorted(
        (p, i) for i, p in enumerate(ps) if isinstance(p, float) and math.isfinite(p)
    )
    out = [False] * len(ps)
    total = len(order)
    cut = 0
    for rank, (p, _) in enumerate(order, start=1):
        if p <= alpha * rank / total:
            cut = rank
    for rank, (_, i) in enumerate(order, start=1):
        if rank <= cut:
            out[i] = True
    return out


def control(rows: list[dict]) -> None:
    coverage = [r for r in rows if r.get("section") == "coverage"]
    for row in coverage:
        print(
            f"coverage  {row['venue']} {row['interval']}  {row['bars']} bars  "
            f"{row['years']:.2f} years  {len(row['feeds'])} series"
        )
    print()
    print("THE TRIANGLE (alignment test; the identity is exact in logs)")
    print(f"{'shift':>5} {'cross':8} {'weights':24} {'r2':>10} {'log dev':>10}")
    for row in sorted(rows, key=lambda r: (r.get("shift", -1), r.get("cross", ""))):
        if row.get("section") != "triangle":
            continue
        weights = ", ".join(f"{w:+.4f}" for w in row["weights"])
        print(
            f"{row['shift']:>5} {row['cross']:8} {weights:24} "
            f"{row['r2']:>10.6f} {row['log_price_dev']:>10.2e}"
        )
    print()
    for row in rows:
        if row.get("section") != "crash":
            continue
        if row.get("skipped"):
            # Not a null: the window is outside this interval's data. Printed
            # rather than omitted, because a reader of a 15m panel has to be
            # able to tell "the control came back empty" from "there was no
            # control to run".
            print(f"THE 2008 CONTROL  {row['from']} .. {row['to']}  NOT RUN: {row['skipped']}")
            print()
            continue
        print(f"THE 2008 CONTROL  {row['from']} .. {row['to']}  {row['bars_in_window']} bars")
        print(f"  breadth at the index peak: {row['breadth_at_peak']} of {row['breadth_legs']} legs")
        print(
            f"  {'reading':16} {'win mean':>9} {'rank':>8} {'win max':>9} "
            f"{'q99':>9} {'pct':>7}  argmax"
        )
        for name, got in row["halves"].items():
            print(
                f"  {name:16} {got['window_mean']:>+9.4f} "
                f"{got['window_rank']:>4}/{got['window_tiles']:<3} "
                f"{got['window_max']:>+9.4f} {got['sample_q99']:>+9.4f} "
                f"{got['peak_pct']:>7.4f}  {got['argmax_date']} "
                f"{'IN' if got['argmax_in_window'] else 'out'}"
                f"  (window peak {got['window_peak_date']})"
            )
        print(f"  {'cross':8} {'kind':12} {'peak':>10} {'trough':>10} {'drawdown':>9}  bars")
        for name, got in row["crosses"].items():
            print(
                f"  {name:8} {got['kind']:12} {got['peak']:>10.2f} {got['trough']:>10.2f} "
                f"{100 * got['drawdown']:>8.1f}% {got['bars_peak_to_trough']:>5}"
                f"   {got['peak_date']} -> {got['trough_date']}"
            )
        print("  the six most risk-off non-overlapping windows:")
        for got in row["episodes"]:
            print(f"    {got['from']} .. {got['to']}  {got['mean']:+.4f}")
        print()
    boundaries = [r for r in rows if r.get("section") == "boundary"]
    if boundaries:
        print("THE MEASURED BOUNDARY (Mood's conventional +-0.5 is not one)")
        keys = [k for k in boundaries[0] if k.startswith("q")]
        print(f"  {'reading':16} " + " ".join(f"{k:>8}" for k in keys))
        for row in boundaries:
            print(f"  {row['reading']:16} " + " ".join(f"{row[k]:>+8.4f}" for k in keys))
        print()
    power = collections.defaultdict(list)
    for row in rows:
        if row.get("section") == "crash-power":
            power[row["depth"]].append(row)
    if power:
        print("POWER FOR THE CONTROL: a crash of known depth planted in surrogate legs")
        print(f"  {'depth':>6} {'found':>7} {'vol':>7} {'dir':>7}   chance")
        for depth in sorted(power):
            got = power[depth]
            found = sum(1 for r in got if r["argmax_in_window"])
            vol = sum(1 for r in got if r["volatile_in_window"])
            direction = sum(1 for r in got if r["directional_in_window"])
            print(
                f"  {depth:>6.2f} {found:>4}/{len(got):<2} {vol:>4}/{len(got):<2} "
                f"{direction:>4}/{len(got):<2}   {got[0]['chance']:.4f}"
            )
        print()


def asym(rows: list[dict]) -> None:
    """Per instrument, per swing scale: real against the hardest null arm."""
    by: dict[tuple, dict[str, list[dict]]] = collections.defaultdict(
        lambda: collections.defaultdict(list)
    )
    for row in rows:
        if not row.get("on_closes"):
            continue
        by[(row["interval"], row["reach"], row["feed"])][row["arm"]].append(row)

    for interval, reach in sorted({(k[0], k[1]) for k in by}):
        print(f"ASYMMETRY  {interval}  reach {reach}  (close pivots)")
        print(
            f"  {'feed':8} {'kind':12} {'n':>5} "
            f"{'bars':>17} {'size':>17} {'speed':>17}  hardest-null excess"
        )
        cells: list[tuple[str, float]] = []
        for (iv, rc, feed), arms in sorted(by.items()):
            if (iv, rc) != (interval, reach):
                continue
            real = arms.get("real", [{}])[0]
            if not real or not real.get("pooled"):
                continue
            pooled, se = real["pooled"], real.get("se", {})
            line = f"  {feed:8} {real['kind']:12} {real['swings']:>5} "
            excess: dict[str, float] = {}
            for name in ("bars", "size", "speed"):
                value = pooled.get(name, float("nan"))
                spread = se.get(name, float("nan"))
                z = value / spread if spread and math.isfinite(spread) and spread > 0 else float("nan")
                line += f"{value:>+8.3f}({z:>+6.2f}) "
                # The hardest null arm is the one the real value beats by
                # least, in the pre-stated direction. For `bars` the claim is
                # positive and for `size` and `speed` negative.
                want = 1.0 if name == "bars" else -1.0
                worst = None
                for arm in F.NULL_ARMS:
                    for got in arms.get(arm, []):
                        got_value = got.get("pooled", {}).get(name, float("nan"))
                        if not math.isfinite(got_value):
                            continue
                        if worst is None or want * got_value > want * worst:
                            worst = got_value
                if worst is not None and math.isfinite(value):
                    excess[name] = want * (value - worst)
            line += "  " + " ".join(f"{k} {v:+.3f}" for k, v in excess.items())
            print(line)
            if math.isfinite(pooled.get("speed", float("nan"))):
                spread = se.get("speed", float("nan"))
                if spread and math.isfinite(spread) and spread > 0:
                    cells.append((feed, 2.0 * (1.0 - phi(abs(pooled["speed"] / spread)))))
        if cells:
            survives = benjamini_hochberg([p for _, p in cells])
            kept = [f for (f, _), ok in zip(cells, survives, strict=True) if ok]
            print(
                f"  BH over {len(cells)} speed cells at 0.05: "
                f"{len(kept)} survive{': ' + ', '.join(kept) if kept else ''}"
            )
        print()


def levels(rows: list[dict]) -> None:
    print("LEVEL FORMATION LABELS  (real legs only; a cross's range is a bound)")
    print(
        f"  {'feed':8} {'book':8} {'arm':14} {'lv':>5} {'tch':>5} "
        f"{'crash':>14} {'spike':>14} {'f-g':>8} {'strata':>8} {'thin':>8}"
    )
    for row in sorted(rows, key=lambda r: (r["book"], r["feed"], r["arm"], r.get("draw", 0))):
        hold = row.get("hold", {})
        if not hold:
            continue
        gaps = row.get("gaps", {})

        def cell(name: str) -> str:
            got = hold.get(name, {})
            n = got.get("n", 0)
            rate = got.get("rate", float("nan"))
            return f"{rate:.3f}(n{n:>4})" if n else f"{'  -  ':>5}(n{n:>4})"

        print(
            f"  {row['feed']:8} {row['book']:8} {row['arm']:14} "
            f"{row['levels']:>5} {row['touched']:>5} {cell('crash'):>14} {cell('spike'):>14} "
            f"{gaps.get('fear_minus_greed_pooled', float('nan')):>+8.3f} "
            f"{gaps.get('fear_minus_greed_strata', float('nan')):>+8.3f} "
            f"{gaps.get('fear_minus_greed_thin', float('nan')):>+8.3f}"
        )
    print()
    print("THE TWO HALVES' AUC FOR THE HOLD  (0.5 is nothing)")
    print(f"  {'feed':8} {'book':8} {'arm':14} {'volatile':>18} {'directional':>18}")
    for row in sorted(rows, key=lambda r: (r["book"], r["feed"], r["arm"])):
        got = row.get("auc", {})
        if not got or row["arm"] != "real":
            continue
        vol, direction = got.get("volatile_off", {}), got.get("directional_off", {})
        print(
            f"  {row['feed']:8} {row['book']:8} {row['arm']:14} "
            f"{vol.get('pooled', float('nan')):>8.3f}/"
            f"{vol.get('within_strata', float('nan')):<9.3f} "
            f"{direction.get('pooled', float('nan')):>8.3f}/"
            f"{direction.get('within_strata', float('nan')):<9.3f}"
        )
    print()


def trade(rows: list[dict]) -> None:
    print("THE TRADE, IN R, GROSS  (no cost is charged; a cross's spread is not in the store)")
    print(
        f"  {'feed':8} {'gate':16} {'side':>4} {'t:s':>7} {'arm':14} {'n':>5} "
        f"{'duty':>5} {'meanR':>8} {'sd':>5} {'ci':>18} {'PF':>6} {'win':>5} {'n95':>9}"
    )
    for row in sorted(
        rows,
        key=lambda r: (
            # Interval first, because 1d and 15m are two rules and must never
            # be read as one table: without it a two-interval run interleaves
            # them feed by feed and every line looks like a cell of one study.
            r.get("interval", ""),
            r["feed"],
            r["gate"],
            -r["side"],
            -r["target"],
            r["arm"],
            r.get("draw", 0),
        ),
    ):
        if row.get("n", 0) < 8:
            continue
        ci = f"[{row['ci_low']:+.3f},{row['ci_high']:+.3f}]" if "ci_low" in row else ""
        need = row.get("trades_for_95", float("nan"))
        need_text = "inf" if not math.isfinite(need) else f"{need:.0f}"
        print(
            f"  {row['feed']:8} {row['gate']:16} {row['side']:>+4} "
            f"{row['target']:.0f}:{row['stop']:.0f}".ljust(0)
            + f" {row['arm']:14} {row['n']:>5} {row['duty']:>5.2f} "
            f"{row['mean_r']:>+8.4f} {row['sd_r']:>5.2f} {ci:>18} "
            f"{(row.get('profit_factor') or float('nan')):>6.3f} "
            f"{(row.get('win_rate') or float('nan')):>5.3f} {need_text:>9}"
        )
    print()
    trade_summary(rows)


def trade_summary(rows: list[dict]) -> None:
    """The counts the trade verdict rests on, one block per interval.

    The table above is one line per arm per cell, and the verdict is a count
    over cells, so before this function the two numbers that decided the 1d
    panel - **6 of 420 cells above their hardest null arm** and **206 of 420
    above their own duty-cycle twin** - were not reproducible from this file.

    * **above the hardest null arm**: the real mean R over the *largest* mean R
      of every draw of every arm in `F.NULL_ARMS`. The chance baseline is
      `cells / (1 + draws)` on exchangeable arms and is printed rather than
      assumed: at four draws an arm it is 20 of 420 and at sixteen it is 5.2,
      so the same count of six is a null against one baseline and a finding
      against the other.
    * **above its own duty-cycle twin**: against `random-twin`, placed at
      random at the real arm's own realised duty. Every pause rule on this desk
      beat its baseline and none beat its twin.
    * **BH** over the real cells' day-block `t`, which asks whether the arm
      makes money at all and not whether it beats a surrogate.
    """
    by: dict[tuple, dict[str, list[dict]]] = collections.defaultdict(
        lambda: collections.defaultdict(list)
    )
    for row in rows:
        key = (
            row.get("interval", ""),
            row["feed"],
            row["gate"],
            row["target"],
            row["stop"],
            row["side"],
        )
        by[key][row["arm"]].append(row)

    for interval in sorted({k[0] for k in by}):
        total = beaten = pairs = won = draws = 0
        ps: list[float] = []
        labels: list[str] = []
        for key in sorted(k for k in by if k[0] == interval):
            arms = by[key]
            real = next((r for r in arms.get("real", []) if "mean_r" in r), None)
            if real is None:
                continue
            total += 1
            nulls = [
                r["mean_r"]
                for arm in F.NULL_ARMS
                for r in arms.get(arm, [])
                if "mean_r" in r
            ]
            draws = max(draws, len(nulls))
            if nulls and real["mean_r"] > max(nulls):
                beaten += 1
            twin = next((r for r in arms.get("random-twin", []) if "mean_r" in r), None)
            if twin is not None:
                pairs += 1
                won += int(real["mean_r"] > twin["mean_r"])
            t = real.get("t", float("nan"))
            if isinstance(t, float) and math.isfinite(t):
                ps.append(2.0 * (1.0 - phi(abs(t))))
                labels.append(
                    f"{key[1]} {key[2]} {key[5]:+d} {key[3]:.0f}:{key[4]:.0f}"
                )
        if not total:
            continue
        print(f"THE VERDICT AS A COUNT OVER CELLS  {interval or '(no interval)'}")
        print(f"  {total} cells, {draws} surrogate draws a cell")
        chance = total / (1.0 + draws) if draws else float("nan")
        print(
            f"  above the hardest null arm:       {beaten:>4} / {total}"
            f"   chance about {chance:.1f}"
        )
        if pairs:
            print(
                f"  above its own duty-cycle twin:   {won:>4} / {pairs}"
                f" = {100.0 * won / pairs:.1f}%   (50% is chance)"
            )
        if ps:
            survives = benjamini_hochberg(ps)
            kept = [name for name, ok in zip(labels, survives, strict=True) if ok]
            print(f"  BH over {len(ps)} cells' day-block t at 0.05: {len(kept)} survive")
            for name in kept[:12]:
                print(f"    {name}")
        print()


def power(rows: list[dict]) -> None:
    by = collections.defaultdict(list)
    for row in rows:
        by[(row["feed"], row["section"], row.get("reach"), row.get("book"))].append(row)
    for key in sorted(by, key=lambda k: tuple(str(x) for x in k)):
        feed, section, reach, book = key
        head = f"POWER  {feed}  {section}" + (f"  reach {reach}" if reach else "")
        print(head + (f"  book {book}" if book else ""))
        for row in by[key]:
            if "speed_excess" in row:
                print(
                    f"  strength {row['strength']:>5.2f}  swings {row['swings']:>5}  "
                    f"speed {row['speed']:>+7.3f}  shuffle {row['speed_shuffle']:>+7.3f}  "
                    f"excess {row['speed_excess']:>+7.3f}  z {row['speed_z']:>+6.2f}  |  "
                    f"bars {row['bars']:>+7.3f} shuffle {row['bars_shuffle']:>+7.3f} "
                    f"z {row['bars_z']:>+6.2f}"
                )
            elif "drift" in row:
                print(
                    f"  drift {row['drift']:>5.2f} units/horizon  mean R "
                    f"{row['mean_r']:>+8.4f}  sd {row['sd']:>7.4f}  draws {row['draws']}"
                )
            elif "gap" in row:
                print(
                    f"  strength {row['strength']:>5.2f}  gap {row['gap']:>+7.3f}  "
                    f"sd {row['sd']:>7.3f}  crash levels {row['crash_n']:>6.1f}  "
                    f"draws {row['draws']}"
                )
        print()


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print(__doc__)
        return 2
    out = pathlib.Path(args[0])
    for name, table in (
        ("control", control),
        ("asym", asym),
        ("levels", levels),
        ("trade", trade),
        ("power", power),
    ):
        rows = read(out / f"{name}.jsonl")
        if not rows:
            continue
        print("=" * 100)
        print(name.upper())
        print("=" * 100)
        table(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
