r"""Read the price-action panel: the cost screen, the arm table, the verdict.

    uv run python research/ideas/price_action_report.py .secrets/pa-out

    # or on the research box, where the panel is written:
    ./.secrets/lab.sh exec "cd ~/till_infinity && \
        PYTHONPATH=\$HOME/till_infinity/repo ./.venv/bin/python \
        repo/research/ideas/price_action_report.py pa-out > pa-out/report.txt"

Every number in `research/docs/price-action.md` comes out of this file from the
JSONL `price_action_run.py` and `price_action_power.py` wrote. It computes and
prints; it decides nothing that was not pre-registered in
`research/docs/price-action-rules.md`.

## What the columns mean, and which one carries the claim

**`excess`**, not `mean`. A bar-level barrier race does not pay `1/(1+N)`:
`level-shield.md` measured it departing by -0.25 to +0.12R, monotone in the
stop-minus-target distance, growing with the interval, **and the surrogates do
it harder** - at 1d a 4:1 reward:risk read -0.2529R where the closed form says
zero and a GARCH twin read -0.7274R. So a raw mean R is not comparable between
a market and its own surrogate, and every arm is quoted as its mean minus the
**same geometry entered at a random bar on the same series**.

**The hardest null arm**, not the average of them.
`let-the-shuffled-twin-names-the-mechanical-observables` is why: the arm to
beat is the highest-reading one, because that is the one naming how much of the
observable is mechanical.

**Benjamini-Hochberg over every cell printed**, and the count travels with the
answer. Picking the best of 43 instruments gives a winner every time.
"""

from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from pathlib import Path

#: The arms that are nulls, in the order the tables print them. `matched` is
#: not here: it is the subtrahend inside `excess`, not a column.
NULLS = ("garch-bars", "walk-geometry", "bar-shuffle", "calendar-shuffle")

#: The desk's cost ceiling, `domain/costs.py`: a round trip may not exceed this
#: share of the **risk**. The denominator is the measured one - 49 trades
#: passed a reward test while expensive against the risk, at -0.471R for
#: -502.70.
CEILING = 0.16

#: The headline target. Two, as in `level-bounce.md`, so the two studies' races
#: are read at the same reward-to-risk.
TARGET = "2.0"


def load(path: Path, name: str) -> list[dict]:
    f = path / name
    if not f.exists():
        return []
    return [json.loads(line) for line in f.open() if line.strip()]


def _excess(row: dict, target: str = TARGET) -> dict | None:
    got = (row.get("r") or {}).get(target)
    return (got or {}).get("excess") if got else None


def pooled(rows: list[dict], target: str = TARGET) -> dict:
    """One `(cell, arm)` pooled across feeds, weighting a feed by its trades.

    Pooled **and** per instrument, never pooled alone: a pooled median here
    once agreed with a claim every subgroup refuted
    (`pooled-medians-invert-subgroups`). The per-feed table is `per_feed`.
    """
    out: dict = defaultdict(
        lambda: {
            "n": 0,
            "num": 0.0,
            "var": 0.0,
            "feeds": 0,
            "signals": 0,
            "trades": 0,
            "placebo": 0,
            "tie": 0.0,
            "decided": 0.0,
            "pdecided": 0.0,
            "agree": 0,
        }
    )
    for row in rows:
        got = (row.get("r") or {}).get(target)
        key = (row["cell"], row["arm"], row.get("level_arm", "none"))
        slot = out[key]
        slot["signals"] += (row.get("census") or {}).get("signals", 0)
        slot["trades"] += (row.get("census") or {}).get("trades", 0)
        slot["placebo"] += row.get("placebo_trades", 0)
        if not got or not got.get("n"):
            continue
        gap = (got.get("excess") or {}).get("value")
        se = (got.get("excess") or {}).get("se") or 0.0
        if gap is None:
            continue
        n = got["n"]
        slot["n"] += n
        slot["num"] += gap * n
        slot["var"] += (se * n) ** 2
        slot["feeds"] += 1
        slot["agree"] += 1 if gap > 0 else 0
        slot["tie"] += got.get("tie", 0.0) * n
        slot["decided"] += got.get("decided", 0.0) * n
        slot["pdecided"] += got.get("placebo_decided", 0.0) * n
    made: dict = {}
    for key, slot in out.items():
        if not slot["n"]:
            made[key] = {"n": 0, "signals": slot["signals"], "trades": slot["trades"]}
            continue
        mean = slot["num"] / slot["n"]
        se = math.sqrt(slot["var"]) / slot["n"]
        made[key] = {
            "n": slot["n"],
            "mean": mean,
            "se": se,
            "z": mean / se if se > 0 else 0.0,
            "feeds": slot["feeds"],
            "agree": slot["agree"],
            "tie": slot["tie"] / slot["n"],
            "decided": slot["decided"] / slot["n"],
            "placebo_decided": slot["pdecided"] / slot["n"],
            "signals": slot["signals"],
            "trades": slot["trades"],
            "placebo_trades": slot["placebo"],
        }
    return made


def hardest(made: dict, cell: str, level_arm: str = "none") -> tuple[str, float]:
    """The null arm reading highest on this cell, and its excess.

    The arm to beat. An average over arms would let a weak arm carry a cell
    that the strongest one refutes, and the strongest one is the measurement of
    how much of the observable is definitional.
    """
    best, value = "", -9.9
    for arm in NULLS:
        got = made.get((cell, arm, level_arm))
        if got and got.get("n") and got["mean"] > value:
            best, value = arm, got["mean"]
    return best, value


def bh(rows: list[tuple[str, float]], alpha: float = 0.05) -> set[str]:
    """Benjamini-Hochberg survivors from `(name, two-sided p)` pairs."""
    ordered = sorted(rows, key=lambda kv: kv[1])
    out: set[str] = set()
    m = len(ordered)
    for i, (name, p) in enumerate(ordered, start=1):
        if p <= alpha * i / m:
            out = {n for n, _ in ordered[:i]}
    return out


def _p(z: float) -> float:
    return math.erfc(abs(z) / math.sqrt(2.0))


def cost_screen(rows: list[dict]) -> list[dict]:
    """Round trip over risk, per feed, interval and pattern. Cost comes first.

    A feed with no recorded quotes gets **no costed number**, which is how it
    ends up geometry-only rather than priced off a guess - the one result that
    looks like a measurement and is not.
    """
    seen: dict[tuple, dict] = {}
    for row in rows:
        if row["arm"] != "real" or row.get("cost_r") is None:
            continue
        key = (row["feed"], row["interval"], row["pattern"], row["stop"])
        if key in seen:
            continue
        seen[key] = {
            "feed": row["feed"],
            "interval": row["interval"],
            "pattern": row["pattern"],
            "stop": row["stop"],
            "spread_bps": row["spread_bps"],
            "risk_vol": row.get("risk_vol"),
            "cost_r": row["cost_r"],
            "affordable": row["cost_r"] <= CEILING,
        }
    return sorted(seen.values(), key=lambda r: (r["interval"], r["cost_r"]))


def per_feed(rows: list[dict], cell: str, target: str = TARGET) -> list[dict]:
    out = []
    for row in rows:
        if row["cell"] != cell or row["arm"] != "real":
            continue
        got = (row.get("r") or {}).get(target)
        if not got or not got.get("n"):
            continue
        e = got.get("excess") or {}
        out.append(
            {
                "feed": row["feed"],
                "interval": row["interval"],
                "n": got["n"],
                "mean": got["mean"],
                "se": got["se"],
                "excess": e.get("value"),
                "excess_se": e.get("se"),
                "win": got.get("win"),
            }
        )
    return sorted(out, key=lambda r: (r["interval"], r["feed"]))


def table(made: dict, rows: list[dict], interval: str | None = None) -> list[dict]:
    """One line per cell: real's excess, the hardest null's, and the gap."""
    cells = sorted({(r["cell"], r.get("level_arm", "none")) for r in rows})
    out = []
    for cell, level_arm in cells:
        real = made.get((cell, "real", level_arm)) or {}
        arm, null = hardest(made, cell, level_arm)
        line = {
            "interval": interval,
            "cell": cell,
            "level_arm": level_arm,
            "signals": real.get("signals", 0),
            "placebo_trades": real.get("placebo_trades", 0),
            "n": real.get("n", 0),
            "feeds": real.get("feeds", 0),
            "agree": real.get("agree", 0),
            "tie": real.get("tie"),
            "decided": real.get("decided"),
            "placebo_decided": real.get("placebo_decided"),
            "excess": real.get("mean"),
            "se": real.get("se"),
            "z": real.get("z"),
            "hardest": arm,
            "null": None if arm == "" else null,
        }
        if line["excess"] is not None and line["null"] is not None:
            line["over_null"] = line["excess"] - line["null"]
        out.append(line)
    return out


#: The cells the sources actually prescribe, at their own stated parameters.
#: Everything else in the panel is a sweep over something no source states, and
#: the verdict is read off these.
HEADLINE = (
    "inside/stop_mother/mother_far/straddle",
    "inside/stop_mother/mother_far/with_trend",
    "inside/stop_mother/mother_50/straddle",
    "pin/market/tail/own/tail0.667",
    "pin/stop_nose/tail/own/tail0.667",
    "fakey/stop_back/break_extreme/own/inside-mother-1",
    "combo/stop_mother/mother_far/own/tail0.667",
)


def per_instrument(rows: list[dict], cell: str, interval: str) -> None:
    """Per feed, never only pooled. `pooled-medians-invert-subgroups`.

    A pooled median on this desk once agreed with a claim every subgroup
    refuted, so the per-feed column is not an appendix - it is where a cell
    with fourteen feeds and one outlier is told apart from one with fourteen
    feeds agreeing.
    """
    got = [r for r in per_feed(rows, cell) if r["interval"] == interval]
    if not got:
        return
    print(f"  -- {cell} at {interval}")
    up = 0
    for row in got:
        up += 1 if (row["excess"] or 0) > 0 else 0
        print(
            f"     {row['feed']:8s} n={row['n']:5d} mean={row['mean']:+.4f} "
            f"excess={row['excess']:+.4f} +- {row['excess_se']:.4f} win={row['win']:.3f}"
        )
    print(f"     {up} of {len(got)} feeds positive")


def clocks(rows: list[dict], screen: list[dict]) -> None:
    """The source's clock claim: "the lower the timeframe the less effective".

    Gross and net side by side, because `a-shorter-clock-multiplies-cost-in-r`
    records the same spread being **19x dearer at 15m than at 1d** - so a
    signal that looks weaker on a fast clock may be entirely a cost effect, and
    "signals work better on higher timeframes" and "costs eat signals on lower
    timeframes" are different claims with one symptom.

    `net` subtracts the median round trip in R over the feeds that **have
    recorded quotes at that clock**, and is blank where none does. A feed with
    no quotes carries no costed number rather than a guessed one.
    """
    cost = {}
    for row in screen:
        cost.setdefault((row["interval"], row["pattern"]), []).append(row["cost_r"])
    print("\n== the clock claim: the same rule at four clocks, gross and net ==")
    for cell in HEADLINE:
        print(f"  -- {cell}")
        for interval in ("1d", "4h", "1h", "15m"):
            at = [r for r in rows if r["interval"] == interval]
            if not at:
                continue
            made = pooled(at)
            for suffix in ("at-trigger", "at-close"):
                real = made.get((f"{cell}/{suffix}", "real", "none"))
                if not real or not real.get("n"):
                    continue
                arm, null = hardest(made, f"{cell}/{suffix}")
                pattern = cell.split("/")[0]
                seen = cost.get((interval, pattern)) or []
                charge = sorted(seen)[len(seen) // 2] if seen else None
                net = (
                    ""
                    if charge is None
                    else f" net={real['mean'] - charge:+.4f} (cost {charge:.4f})"
                )
                print(
                    f"     {interval:>4s} {suffix:11s} n={real['n']:6d} feeds={real['feeds']:2d} "
                    f"up={real['agree']:2d} excess={real['mean']:+.4f} se={real['se']:.4f} "
                    f"z={real['z']:+5.2f} | {arm:16s} {null:+.4f}{net}"
                )


def firing(rows: list[dict], interval: str) -> None:
    """Signals per 1,000 bars, real against every surrogate arm.

    **The confound this study would otherwise inherit.**
    `how-markets-differ-from-every-simple-process` measured real bars as
    *wickier* than every simple process - a body share of 0.43-0.50 against
    0.55 for the best-fitting families, and an inside-bar rate of 0.16-0.21
    against 0.11 - so a pattern stated as a fraction of a bar's range fires
    more often on real data than on a walk for **mechanical** reasons. A rule
    built on one inherits that, and a rate difference is not evidence of
    anything but bar shape.

    `inside-bars.md` is the measured form for the two-bar case: the ordering
    *suppresses* the inside-bar rate by 0.046-0.072 and between a third and a
    half of that is the hour-of-day cycle, which a generated null has none of.
    So `calendar-shuffle` is the row to read the inside bar against, not
    `walk-geometry`.
    """
    print(f"\n== firing rate per 1,000 bars at {interval}: the wickiness confound ==")
    seen: dict[tuple[str, str], tuple[float, float]] = {}
    for row in rows:
        if row["interval"] != interval or row.get("level_arm", "none") != "none":
            continue
        cell = row["cell"].replace("/at-close", "").replace("/at-trigger", "")
        key = (cell, row["arm"])
        got = seen.get(key, (0.0, 0.0))
        seen[key] = (
            got[0] + (row.get("census") or {}).get("signals", 0),
            got[1] + row.get("bars", 0),
        )
    cells = sorted({c for c, _ in seen})
    for cell in cells:
        if "/own" not in cell and "/straddle" not in cell:
            continue
        line = f"  {cell:50s}"
        for arm in ("real", *NULLS):
            signals, bars = seen.get((cell, arm), (0.0, 0.0))
            rate = 1000.0 * signals / bars if bars else float("nan")
            line += f" {arm}={rate:7.2f}"
        print(line)


def main(argv: list[str]) -> int:
    path = Path(argv[1] if len(argv) > 1 else "pa-out")
    panel = load(path, "panel.jsonl")
    sweep = load(path, "sweep.jsonl")
    conf = load(path, "confluence.jsonl")
    power = load(path, "power.jsonl")
    print(
        f"panel {len(panel)} rows, sweep {len(sweep)}, confluence {len(conf)}, power {len(power)}"
    )

    print("\n== cost: round trip over risk, and the 0.16 ceiling ==")
    screen = cost_screen(panel)
    for row in screen:
        if row["stop"] not in ("mother_far", "tail", "break_extreme"):
            continue
        mark = "" if row["affordable"] else "  REFUSED"
        print(
            f"{row['interval']:>4s} {row['feed']:8s} {row['pattern']:7s} "
            f"{row['spread_bps']:6.3f}bps risk={row['risk_vol']:.2f}u "
            f"cost={row['cost_r']:.4f}R{mark}"
        )
    worst = [r for r in screen if not r["affordable"]]
    print(f"{len(worst)} of {len(screen)} (feed, interval, pattern, stop) cells above {CEILING}R")

    for label, rows in (("panel", panel), ("sweep", sweep), ("confluence", conf)):
        if not rows:
            continue
        for interval in sorted({r["interval"] for r in rows}):
            at = [r for r in rows if r["interval"] == interval]
            made = pooled(at)
            lines = table(made, at, interval)
            print(f"\n== {label} {interval}: excess over a matched random entry, at {TARGET}R ==")
            tests = [
                (f"{line['cell']}|{line['level_arm']}", _p(line["z"]))
                for line in lines
                if line.get("z") is not None and line.get("n")
            ]
            kept = bh(tests)
            for line in sorted(lines, key=lambda x: -(x.get("over_null") or -9)):
                if not line["n"]:
                    print(
                        f"  {line['cell']:52s} {line['level_arm']:8s} "
                        f"signals={line['signals']:6d} NO TRADES"
                    )
                    continue
                name = f"{line['cell']}|{line['level_arm']}"
                print(
                    f"  {line['cell']:52s} {line['level_arm']:8s} n={line['n']:6d} "
                    f"feeds={line['feeds']:2d} agree={line['agree']:2d} "
                    f"excess={line['excess']:+.4f} se={line['se']:.4f} z={line['z']:+5.2f} plac={line['placebo_trades']:6d} "
                    f"tie={line['tie']:.3f} dec={line['decided']:.3f}/{line['placebo_decided']:.3f} "
                    f"| {line['hardest']:16s} {line['null']:+.4f} "
                    f"over={line['over_null']:+.4f} {'BH' if name in kept else ''}"
                )
            print(f"  {len(kept)} of {len(tests)} cells survive Benjamini-Hochberg at 0.05")

    if panel:
        for interval in ("1d", "15m"):
            firing(panel, interval)
        clocks(panel, screen)
        print("\n== per instrument, the cells the sources prescribe ==")
        for interval in ("1d", "15m"):
            for cell in HEADLINE:
                for suffix in ("at-trigger", "at-close"):
                    per_instrument(panel, f"{cell}/{suffix}", interval)

    if conf:
        print("\n== confluence: factor count, per pattern, pooled at 1d ==")
        print("   real against placebo levels. `the-placebo-arm-selects-the-null`:")
        print("   a null whose placebo arm finds MORE than the real arm is rejected.")
        for pattern in sorted({r["pattern"] for r in conf}):
            for level_arm in ("real", "placebo"):
                at = [
                    r
                    for r in conf
                    if r["arm"] == "real"
                    and r.get("level_arm") == level_arm
                    and r["pattern"] == pattern
                ]
                for count in ("0", "1", "2", "3"):
                    num = den = var = 0.0
                    feeds: set[str] = set()
                    agree = cells_seen = 0
                    for row in at:
                        got = (row.get("factors") or {}).get(count) or {}
                        gap = (got.get("excess") or {}).get("value")
                        se = (got.get("excess") or {}).get("se") or 0.0
                        if gap is None or not got.get("n"):
                            continue
                        n = got["n"]
                        num += gap * n
                        den += n
                        var += (se * n) ** 2
                        feeds.add(row["feed"])
                        cells_seen += 1
                        agree += 1 if gap > 0 else 0
                    if not den:
                        print(f"  {pattern:7s} {level_arm:8s} >={count}: no scored trades")
                        continue
                    mean = num / den
                    se = math.sqrt(var) / den
                    print(
                        f"  {pattern:7s} {level_arm:8s} >={count}: n={int(den):7d} "
                        f"feeds={len(feeds):2d} rows={cells_seen:4d} up={agree:4d} "
                        f"excess={mean:+.4f} se={se:.4f} z={mean / se if se else 0:+5.2f}"
                    )

    if power:
        print("\n== power: a planted drift, in R, and where the test goes blind ==")
        by = defaultdict(
            lambda: defaultdict(lambda: {"num": 0.0, "den": 0.0, "var": 0.0, "pos": 0, "f": 0})
        )
        for row in power:
            e = row.get("excess") or {}
            if not row.get("n") or e.get("value") is None:
                continue
            slot = by[(row["interval"], row["cell"])][row["strength"]]
            n = row["n"]
            slot["num"] += e["value"] * n
            slot["den"] += n
            slot["var"] += ((e.get("se") or 0.0) * n) ** 2
            slot["pos"] += 1 if e["value"] > 0 else 0
            slot["f"] += 1
        for (interval, cell), rowset in sorted(by.items()):
            print(f"  {interval} {cell}")
            base = None
            for strength in sorted(rowset):
                slot = rowset[strength]
                mean = slot["num"] / slot["den"]
                se = math.sqrt(slot["var"]) / slot["den"]
                if base is None:
                    base = mean
                print(
                    f"    plant={strength:.2f} n={int(slot['den']):6d} feeds={slot['f']:2d} "
                    f"positive={slot['pos']:2d} excess={mean:+.4f} se={se:.4f} "
                    f"z={mean / se if se else 0:+5.2f} lift={mean - base:+.4f}"
                )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
