"""Should every level strategy wear `sweep-aware`'s liquidity stop gate?

Asked on 2026-10-10: add the gate to `cycle-*`, `thesis-only`, `fade-to-value`
"and all the other guys as well". Three strategies wear it today - `cycle-scalp`
(`stop_multiple` 1.25), `confluence-scalp` (1.5) and `sweep-aware` (1.0) - and
the function was written to be worn, documented as "`sweep-aware`'s entry gate,
as something any level strategy can wear".

So the question is not whether it *can* be spread. It is what spreading it
would refuse, and whether those refusals are the ones you want.

## The bug this found before it measured anything

`sweep_gate` computes the stop it judges as

    risk_vol = abs(_number(features, "risk_vol")) * strategy.stop_multiple

but the stop a trade actually gets, from `LevelStrategy.distances`, is

    wide = max(risk_vol * self.stop_multiple, self.stop_floor_vol(interval))

a **`max`**. The gate reads one arm of it. Whenever `risk_vol * stop_multiple`
falls below the floor the gate judges a stop narrower than the one that will be
placed, so it refuses too little - and it fails *open*, which is the direction
that costs money.

For the 1.0-multiple strategies the floor is `min_stop_vol` = 1.0 and the
understatement is small. For **`thesis-only` it is not**: that strategy keeps
`stop_multiple = 1.0` and gets its width from `Settings.thesis_stop_vol` = 4.0
reaching it through an overridden `stop_floor_vol`, so a 0.8v reading describes
a trade that is really risking 4.0v - five times the exposure the gate thinks
it is clearing. Pasted in unchanged, the gate would be close to inert on
exactly the strategy whose stops are widest.

That is not a guess about the code; `opportunity.py` already carries the note
that this strategy's "wide stop comes from `Settings.thesis_stop_vol` reaching
it through `stop_floor_vol`", and the comment there records that discovering it
cost a failing test.

## What this measures

Both gates, over every decision the live desk actually took:

* **as-written** - `risk_vol * stop_multiple / beyond`, what ships today
* **realised** - `max(risk_vol * stop_multiple, stop_floor_vol(interval)) / beyond`,
  the stop the trade is really given

One of the two arms is checked against the real `sweep_gate` imported from the
strategy module rather than reproduced here, so a disagreement between this
harness and production is a test failure rather than a silent difference. Until
2026-10-10 that was the as-written arm; the `max` has since been fixed in
`sweep_gate`, so it is now the realised arm, and re-running this checks the
shipped behaviour against the measurement that asked for it. The realised arm
changes the stop and nothing else: same two conditions, same thresholds, same
order.

**`as written` in the tables below is therefore the pre-fix behaviour**, kept so
the two can still be compared, and the harness's own cross-check is what
establishes which one the desk is running.

Then, for the closed subset, what the refused trades actually made. A gate is
worth wearing where the calls it declines lose money; `sweep-aware`'s own
justification is that "the calls it declines are worth +0.189R each", and the
same arithmetic has to hold for each new wearer on its own record or it is
being given someone else's evidence.

## What it cannot settle

A refused entry is not a counterfactual. These trades were taken, so their
outcomes are known, but the gate changes which trades exist and therefore what
the risk budget and the one-position-per-level rules do with the rest. The
honest reading is a screen: a strategy whose refused trades lose money is a
candidate, and one whose refused trades make money is a refusal to spread.

**Attribution is the trap.** `DEFAULT_MAGIC` is 777701; reading a magic against
777700 shifts every strategy to its neighbour in `MAGIC_ORDER` and every
neighbour is a plausible name, so the mistake reads as a finding. This reads the
`strategy` field the decision recorded.

Runs on the lab. Production has two cores and a 2.6GB container limit, and
research on it OOM-killed the live desk three times - see `research/starving.md`.
"""

from __future__ import annotations

import gzip
import json
import math
import os
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from till_infinity.trading.config import Settings
from till_infinity.trading.strategies import scalper, swing  # noqa: F401  (registers)
from till_infinity.trading.strategies.scalper import sweep_gate
from till_infinity.trading.strategies.strategy import STRATEGIES

#: The extracted decision and outcome entries, one JSON object a line, gzip or
#: plain. Produced from the journal on the instance rather than read here:
#: `journal.db` is 2.5GB and `actor='trading'` is 5,091 rows of its 2.3M.
SOURCE = Path(os.environ.get("TRADES", ".secrets/journal/trades.jsonl.gz"))

#: Closed trades below which a rate is not quoted. `report.ENOUGH`'s reasoning:
#: not significance, just the point where a percentage misleads more than the
#: count informs.
ENOUGH = 30

#: The three that wear the gate today, so the table can separate "this would be
#: new" from "this is already happening".
WEARING = ("cycle-scalp", "confluence-scalp", "sweep-aware")


def rows(path: Path) -> list[dict]:
    """Every entry, with its context parsed."""
    opener = gzip.open if path.suffix == ".gz" else open
    out: list[dict] = []
    with opener(path, "rt") as fh:  # type: ignore[operator]
        for line in fh:
            row = json.loads(line)
            try:
                row["ctx"] = json.loads(row["context"]) if row["context"] else {}
            except (TypeError, ValueError):
                row["ctx"] = {}
            out.append(row)
    return out


def paired(entries: list[dict]) -> tuple[list[dict], dict[str, float]]:
    """Decisions, and the R each one ended at where it has closed.

    Risk falls back to the decision's own sizing: 56% of the record was
    invisible to every report until that fallback existed, because the close
    spread a zero over it. Measured 2026-10-04.
    """
    decisions = [e for e in entries if e["kind"] == "decision"]
    by_id = {e["id"]: e for e in decisions}
    result: dict[str, float] = {}
    for outcome in (e for e in entries if e["kind"] == "outcome"):
        parent = by_id.get(outcome.get("parent") or "")
        if parent is None:
            continue
        ctx = {**parent["ctx"], **outcome["ctx"]}
        risk = float(ctx.get("risk_money") or 0.0)
        if risk <= 0:
            risk = float(parent["ctx"].get("risk_money") or 0.0)
        if risk <= 0:
            continue
        result[parent["id"]] = float(ctx.get("profit") or 0.0) / risk
    return decisions, result


def features_of(ctx: dict[str, Any]) -> dict[str, float]:
    """The numeric part of the context, which is where the features live.

    They are flattened into the context rather than nested under a `features`
    key - checking for the nested shape reports every feature missing, which is
    how this harness first read a journal full of them as empty.
    """
    return {
        k: float(v)
        for k, v in ctx.items()
        if isinstance(v, int | float) and not isinstance(v, bool)
    }


def verdicts(
    strategy: Any, payload: dict[str, Any], features: dict[str, float], settings: Settings
) -> tuple[str, str, float, float]:
    """`(as_written, realised, exposure_as_written, exposure_realised)`.

    The two conditions and their order are `sweep_gate`'s. Only the stop in the
    second one differs, so any difference in the table is that `max`.
    """
    swept = features.get("sweep_rate", 0.0)
    swept_n = features.get("sweep_n", 0.0)
    if swept_n >= settings.sweep_min_history and swept >= settings.sweep_max_rate:
        return "swept_often", "swept_often", 0.0, 0.0

    beyond = features.get("liquidity_beyond_vol", 0.0)
    if beyond <= 0:
        return "", "", 0.0, 0.0  # nothing within reach to be run toward

    interval = str(payload.get("interval") or "")
    narrow = abs(features.get("risk_vol", 0.0)) * strategy.stop_multiple
    wide = max(narrow, strategy.stop_floor_vol(interval))
    limit = settings.sweep_max_exposure
    return (
        "in_front" if narrow / beyond >= limit else "",
        "in_front" if wide / beyond >= limit else "",
        narrow / beyond,
        wide / beyond,
    )


def summarise(label: str, values: list[float]) -> str:
    """One band, with the standard error on its mean.

    The error is the whole point. A refused set of 26 trades at +0.084 R and one
    of 29 at -0.254 R are both well inside a single-trade spread of about 1 R,
    so without `+/-` next to the mean every one of these bands reads as a finding
    and most of them are noise.
    """
    if not values:
        return f"  {label:<30} n=   0"
    n = len(values)
    wins = sum(1 for r in values if r > 0)
    rate = f"{wins / n:>4.0%}" if n >= ENOUGH else f"{wins}/{n}"
    mean = statistics.fmean(values)
    sigma = statistics.stdev(values) if n > 1 else 0.0
    err = sigma / math.sqrt(n) if n else 0.0
    t = mean / err if err else 0.0
    return (
        f"  {label:<30} n={n:>4}  win {rate:>6}  "
        f"mean R {mean:+.3f} +/-{err:.3f} (t {t:+.1f})  total R {sum(values):+8.2f}"
    )


def main() -> None:
    settings = Settings()
    print(
        f"gate thresholds: rate>={settings.sweep_max_rate:.2f} over "
        f">={settings.sweep_min_history:.0f}, exposure>={settings.sweep_max_exposure:.2f}; "
        f"floor min_stop_vol={settings.min_stop_vol:.2f} "
        f"hold_scaling={settings.stop_hold_scaling:.2f}\n"
    )

    entries = rows(SOURCE)
    decisions, closed = paired(entries)
    print(f"{len(decisions)} decisions taken, {len(closed)} of them closed\n")

    instances: dict[str, Any] = {}
    for name, cls in STRATEGIES.items():
        try:
            instances[name] = cls(settings=settings)
        except Exception as exc:  # a strategy this record never used
            print(f"  (cannot instantiate {name}: {type(exc).__name__}: {exc})")

    # Per strategy: counts under each gate, and the R of what each would refuse.
    counts: dict[str, Counter] = defaultdict(Counter)
    refused_r: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: {"as_written": [], "realised": [], "kept": [], "all": []}
    )
    disagreements = 0
    checked = 0
    unknown: Counter = Counter()
    stops: dict[str, list[tuple[float, float]]] = defaultdict(list)

    for entry in decisions:
        ctx = entry["ctx"]
        name = str(ctx.get("strategy") or "?")
        strategy = instances.get(name)
        if strategy is None:
            unknown[name] += 1
            continue
        features = features_of(ctx)
        payload = {"feed": ctx.get("feed"), "interval": ctx.get("interval")}

        written, realised, exposure_a, exposure_b = verdicts(strategy, payload, features, settings)

        # The as-written arm must agree with the function that ships, or this
        # harness is measuring its own reimplementation.
        # `Refusal`'s field is `gate`, not `name`. Reading `name` makes every
        # real refusal register as a pass, which reported 328 disagreements
        # against production that were entirely this attribute.
        #
        # **The arm this is checked against changed on 2026-10-10.** Until then
        # the shipped gate read `risk_vol * stop_multiple` and the check was
        # against `written`; the `max` is now in `sweep_gate`, so production
        # implements `realised` and that is what has to agree. Re-running this
        # is therefore an end-to-end check of the fix rather than only of the
        # replay: the same 3,266 decisions, the same two arms, and the one the
        # desk now computes is the one whose refusals were measured here.
        live = sweep_gate(strategy, payload, features)
        live_name = getattr(live, "gate", "") if live is not None else ""
        checked += 1
        if live_name != realised:
            disagreements += 1
            if disagreements <= 5:
                print(f"  !! {name}: production says {live_name!r}, replay says {realised!r}")

        counts[name]["decisions"] += 1
        if written:
            counts[name][f"as_written:{written}"] += 1
        if realised:
            counts[name][f"realised:{realised}"] += 1
        if realised and not written:
            counts[name]["only_realised"] += 1

        narrow = abs(features.get("risk_vol", 0.0)) * strategy.stop_multiple
        wide = max(narrow, strategy.stop_floor_vol(str(ctx.get("interval") or "")))
        stops[name].append((narrow, wide))

        r = closed.get(entry["id"])
        if r is None:
            continue
        counts[name]["closed"] += 1
        refused_r[name]["all"].append(r)
        if written:
            refused_r[name]["as_written"].append(r)
        if realised:
            refused_r[name]["realised"].append(r)
        else:
            refused_r[name]["kept"].append(r)

    print(
        f"\nrealised-stop replay checked against the shipped `sweep_gate` on "
        f"{checked} decisions: {disagreements} disagreements"
    )
    if unknown:
        print("  decisions from strategies not in the registry:", dict(unknown))

    print("\n=== 1. how much stop the gate cannot see ===")
    print(
        f"  {'strategy':<18} {'wears':>5} {'n':>5} {'gate sees':>10} {'realised':>9} {'ratio':>6}"
    )
    for name in sorted(stops, key=lambda k: -len(stops[k])):
        pairs = stops[name]
        a = statistics.fmean(p[0] for p in pairs)
        b = statistics.fmean(p[1] for p in pairs)
        wears = "yes" if name in WEARING else "-"
        print(
            f"  {name:<18} {wears:>5} {len(pairs):>5} {a:>10.2f} {b:>9.2f} {b / a if a else 0:>6.2f}x"
        )

    print("\n=== 2. what each gate would refuse ===")
    print(f"  {'strategy':<18} {'wears':>5} {'n':>5} {'as-written':>10} {'realised':>9} {'new':>5}")
    for name in sorted(counts, key=lambda k: -counts[k]["decisions"]):
        c = counts[name]
        n = c["decisions"]
        a = c["as_written:in_front"] + c["as_written:swept_often"]
        b = c["realised:in_front"] + c["realised:swept_often"]
        wears = "yes" if name in WEARING else "-"
        print(
            f"  {name:<18} {wears:>5} {n:>5} "
            f"{a:>5} {a / n:>4.0%} {b:>4} {b / n:>4.0%} {c['only_realised']:>5}"
        )

    print("\n  by cause:")
    for name in sorted(counts, key=lambda k: -counts[k]["decisions"]):
        c = counts[name]
        print(
            f"  {name:<18} swept_often {c['realised:swept_often']:>4}  "
            f"in_front {c['realised:in_front']:>4}  (as-written in_front "
            f"{c['as_written:in_front']:>4})"
        )

    print("\n=== 3. what the refused trades actually made, on the closed subset ===")
    print("  a gate is worth wearing where the calls it declines lose money")
    for name in sorted(refused_r, key=lambda k: -len(refused_r[k]["all"])):
        band = refused_r[name]
        if not band["all"]:
            continue
        print(f"\n  {name}{'  (wears it today)' if name in WEARING else ''}")
        print(summarise("all closed", band["all"]))
        print(summarise("would refuse (realised stop)", band["realised"]))
        print(summarise("would keep (realised stop)", band["kept"]))
        print(summarise("would refuse (as written)", band["as_written"]))
        if band["realised"]:
            refused = band["realised"]
            gain = -sum(refused)
            per = gain / len(refused)
            err = statistics.stdev(refused) / math.sqrt(len(refused)) if len(refused) > 1 else 0.0
            verdict = (
                "worth wearing"
                if per > 2 * err and err > 0
                else "costs money"
                if per < -2 * err and err > 0
                else "inside the noise"
            )
            print(
                f"    refusing them is worth {gain:+.2f} R in total, "
                f"{per:+.3f} +/-{err:.3f} R a trade -> {verdict}"
            )


if __name__ == "__main__":
    main()
