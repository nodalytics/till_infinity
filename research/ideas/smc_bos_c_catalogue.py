"""`smc_bos_c_L50|M15|N20|time` over the recorded catalogue, correction by correction.

**What this answers and what it cannot.** The catalogue is 76-86 days of 15m
bars for six feeds with one modelled quote per bar, so at this rule's measured
4-8 breaks per instrument-month it produces about 90 trades. At a per-trade sd
near 2.4R the standard error on the mean is about 0.25R. **It cannot settle an
edge.** It settles whether the implementation matches its specification, what
each divergence is worth, and what the rule's own cost is.

So every row below is one of three things and is labelled as such: a
**mechanic** (trade counts, exit mix, which stop leg binds), a **cost** (the
round trip in R, which the stop sets and no exit rule can change), or a
**reading** whose standard error is wider than any effect being argued about.

## The corrections, each measured alone and then stacked

The rule as frozen, against what this port did:

| correction | what the port did | what the rule says |
|---|---|---|
| `fees` | the FX test instrument charged 0.00002 maker and taker | no commission |
| `contract` | gold sized against 100 ounces and priced at 1 | one convention |
| `bars` | 86,400 seconds of clock | 1,440 M1 bars, so 96 M15 ones |
| `anchor` | both stop legs from the fill | ATR from the signal close |
| `cut` | no entry cut-off | no fill in 19:00-23:59 UTC |
| `tie` | a swing must be strictly beyond | a tie is a swing |
| `overshoot` | a stop fills at the stop | a stop fills at the first tick through |

`fees` and `contract` are in `node/corpus.py` and are not switchable, so they
are measured by running the same code against a catalogue written before the
fix - pass `--before` with that path. The rest are profile knobs.

`overshoot` is a **charge, not a simulation**: there are no ticks in this store,
so each stop exit is debited a flat figure. The reference method's own fallback
for an instrument with no ticks is 0.035R, and that is what `--overshoot` means.

## The nulls

Two arms, both run on the same bars through the same detector:

* **`flip`** - the same rule with the side of every break reversed. Identical
  geometry: same swings, same stop distance, same clock, same spread paid, only
  the side differs. Anything both arms earn is not direction.
* **`late`** - the same entries taken `--late` bars after the break. Keeps the
  rule's selection of *when* and destroys its selection of *what*, which is the
  arm that separates a break from a bar that happened to follow one.

A day-block bootstrap gives the interval, because trades cluster in days: a
stationary resample over whole UTC days, geometric block length of mean 5 days.
An ordinary standard error over 90 overlapping-regime trades is too narrow.

## Running it

One invocation does everything: `--all` runs the correction stack, the nulls and
the per-side reach sweep and writes every table to `--out`, which defaults to
`.data/out/smc_bos_c` relative to the repository.

    uv run python research/ideas/smc_bos_c_catalogue.py --all

**Single process throughout** - one `BacktestEngine` at a time, no pool - so it
is safe to run beside other work, and it needs one core. The full `--all` pass
is 174 engine runs over about 32,000 bars each.
"""

from __future__ import annotations

import argparse
import contextlib
import math
import os
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

import numpy as np
from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, LoggingConfig, RiskEngineConfig
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import BarType
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.model.objects import Money
from nautilus_trader.persistence.catalog import ParquetDataCatalog

from till_infinity.node.backtest import catalogue
from till_infinity.strategies.entries import EdgeEntryConfig
from till_infinity.strategies.structure import Structure, StructureProfile
from till_infinity.strategies.exits import ManagedExit
from till_infinity.strategies.entries import EdgeEntry

#: The reference method's fallback debit for a stop filled off a bar path
#: rather than off ticks, in R. Charged per stop exit, not per trade.
OVERSHOOT_R = 0.035

#: Where the tables are written, relative to the repository unless `SMC_OUT`
#: says otherwise. Relative, so nothing here names a machine, and under
#: `.data/` because that is already gitignored - a report is output, not source.
OUT = os.environ.get("SMC_OUT", ".data/out/smc_bos_c")


class Tee:
    """Write to stdout and to a file at once, so one run leaves a report."""

    def __init__(self, handle: Any) -> None:
        self._handle = handle

    def write(self, text: str) -> int:
        self._handle.write(text)
        return sys.__stdout__.write(text)

    def flush(self) -> None:
        self._handle.flush()
        sys.__stdout__.flush()


#: Equity the account starts with. R is scale-free, so this only has to be
#: large enough that no trade is refused for not covering a minimum lot.
EQUITY = 1_000_000.0


@dataclass(frozen=True, slots=True)
class Arm:
    """One cell: a set of corrections and a null arm, named."""

    name: str
    #: Profile overrides, by `StructureProfile` attribute.
    knobs: dict[str, Any] = field(default_factory=dict)
    #: "" for the rule, "flip" for the reversed twin, "late" for the delayed
    #: entry.
    null: str = ""
    #: Bars of delay for the `late` arm.
    late: int = 8
    #: Charge `OVERSHOOT_R` on every stop exit.
    overshoot: bool = False


def leaf_for(arm: Arm) -> type:
    """A strategy class carrying this arm's profile.

    Built with `type()` rather than written out, which `leaves.py` refuses to
    do for production desks because a `strategy_id` derives from the class
    name. Here each name is stable within one run and no order outlives it.
    """
    profile = type(f"{arm.name}Profile", (StructureProfile,), dict(arm.knobs))
    body: dict[str, Any] = {"profile": profile.__new__(profile)}
    if arm.null == "flip":

        def _payload(self, event, bar, _super=Structure._payload):  # type: ignore[no-untyped-def]
            found = _super(self, event, bar)
            return found | {"direction": -int(found["direction"])}

        body["_payload"] = _payload
    if arm.null == "late":
        body["_late"] = arm.late
        body["_queue"] = None
    built = type(f"{arm.name}Edge", (Structure, ManagedExit, EdgeEntry), body)
    return built


class Late(Structure):
    """The rule with every entry held back `_late` signal bars.

    Keeps *when* the rule fires and drops *what* it fired on: by the time the
    order goes in, the break is eight bars old. A rule whose edge is the break
    itself should lose this; one whose reading is only "a bar after a trending
    stretch" should not.
    """

    _late: ClassVar[int] = 8

    def on_start(self) -> None:
        super().on_start()
        self._pending_late: list[tuple[int, dict[str, Any]]] = []

    def on_bar(self, bar: Any) -> None:
        due = [p for at, p in self._pending_late if self.structure["bars"] >= at]
        self._pending_late = [
            (at, p) for at, p in self._pending_late if self.structure["bars"] < at
        ]
        super().on_bar(bar)
        for payload in due:
            self.on_data(payload)

    def _payload(self, event: Any, bar: Any) -> dict[str, Any]:
        found = super()._payload(event, bar)
        self._pending_late.append((self.structure["bars"] + self._late, found))
        # Returned with a shape no desk wants, so `consider` drops it now and
        # the queued copy is what reaches the gates `_late` bars later.
        return found | {"shape": "deferred"}


def late_leaf(arm: Arm) -> type:
    profile = type(f"{arm.name}Profile", (StructureProfile,), dict(arm.knobs))
    return type(
        f"{arm.name}Edge",
        (Late, ManagedExit, EdgeEntry),
        {"profile": profile.__new__(profile), "_late": arm.late},
    )


def run_one(instrument: Any, data: list[Any], arm: Arm) -> list[Any]:
    """One instrument, one arm. The finished trades, in closing order."""
    engine = BacktestEngine(
        config=BacktestEngineConfig(
            trader_id="BACKTEST-001",
            logging=LoggingConfig(bypass_logging=True),
            risk_engine=RiskEngineConfig(bypass=False),
        )
    )
    engine.add_venue(
        venue=instrument.id.venue,
        oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN,
        base_currency=USD,
        starting_balances=[Money(EQUITY, USD)],
    )
    engine.add_instrument(instrument)
    engine.add_data(data)
    built = late_leaf(arm) if arm.null == "late" else leaf_for(arm)
    strategy = built(
        EdgeEntryConfig(
            instrument_id=instrument.id,
            bar_type=BarType.from_str(f"{instrument.id}-15-MINUTE-LAST-EXTERNAL"),
            order_id_tag="0001",
        )
    )
    engine.add_strategy(strategy)
    engine.run()
    closed = list(strategy.closed)
    counted = dict(strategy.structure)
    gates = dict(sorted(strategy.passed_over.items()))
    engine.dispose()
    return closed, counted, gates


def rewards(closed: list[Any], *, overshoot: bool) -> list[float]:
    """Per-trade R, with the stop-fill debit applied where asked."""
    return [
        trade.reward - (OVERSHOOT_R if overshoot and trade.how == "stop" else 0.0)
        for trade in closed
    ]


def day_block(values: list[float], days: list[str], *, draws: int = 2_000, mean_block: float = 5.0):
    """A stationary bootstrap over whole days. Returns (lo, hi) at 95%.

    Days and not trades: a regime persists for hours and this rule holds for a
    day, so consecutive trades are not independent and an ordinary standard
    error is far too narrow. The block length is geometric with mean 5 days,
    which is one trading week.
    """
    if not values:
        return (0.0, 0.0)
    by_day: dict[str, list[float]] = defaultdict(list)
    for value, day in zip(values, days, strict=True):
        by_day[day].append(value)
    keys = sorted(by_day)
    if len(keys) < 2:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(20_261_103)
    means = []
    for _ in range(draws):
        picked: list[float] = []
        while len(picked) < len(values):
            index = rng.integers(len(keys))
            while True:
                picked.extend(by_day[keys[index % len(keys)]])
                if rng.random() < 1.0 / mean_block:
                    break
                index += 1
        means.append(sum(picked[: len(values)]) / len(picked[: len(values)]))
    return (float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975)))


def describe(closed: list[Any], *, overshoot: bool) -> dict[str, Any]:
    """Everything one cell is reported as."""
    found = rewards(closed, overshoot=overshoot)
    days = [datetime.fromtimestamp(t.opened, UTC).strftime("%Y-%m-%d") for t in closed]
    n = len(found)
    mean = sum(found) / n if n else 0.0
    sd = statistics.stdev(found) if n > 1 else 0.0
    lo, hi = day_block(found, days)
    stops = [t for t in closed if t.how == "stop"]
    costs = [t.spread_px / t.risk_px for t in closed if t.risk_px > 0.0]
    return {
        "n": n,
        "mean": mean,
        "se": sd / math.sqrt(n) if n else 0.0,
        "lo": lo,
        "hi": hi,
        "total": sum(found),
        "stopped": len(stops),
        "clocked": sum(1 for t in closed if t.how == "clock"),
        "win": sum(1 for r in found if r > 0) / n if n else 0.0,
        "cost_r": statistics.median(costs) if costs else 0.0,
        "risk_px": statistics.median([t.risk_px for t in closed]) if closed else 0.0,
        "best": max(found) if found else 0.0,
        "worst": min(found) if found else 0.0,
        # The mean with the single best trade removed. A *share* of total R is
        # unreadable when the total is negative - it comes out at -103% - and
        # the question concentration asks is what the mean is without the tail.
        "ex_best": (sum(found) - max(found)) / (n - 1) if n > 1 else float("nan"),
        "gross_up": sum(r for r in found if r > 0),
        "gross_down": sum(r for r in found if r < 0),
        # Overshoot past the stop, in R, read off the realised R rather than
        # off a separate fill record: a stop filled at the stop is -1R, so
        # anything past that is the gap. **This catalogue's only quotes are one
        # per 15m bar**, so a stop cannot fill at the stop when price jumps
        # over it between closes - the fills here are pessimistic, not the
        # optimistic bar-path fills a tick correction is usually for.
        "slip_r": statistics.median([-t.reward - 1.0 for t in stops]) if stops else 0.0,
        "r": found,
        "days": days,
    }


#: The corrections, cumulative. Each row adds one knob to the row above, so the
#: difference between two consecutive readings is that correction's worth.
STACK: tuple[tuple[str, dict[str, Any]], ...] = (
    (
        "as-committed",
        {
            "hold_signal_bars": 0,
            "stop_from_close": False,
            "no_fill_hours": (),
            "tie_is_a_swing": False,
        },
    ),
    ("+bars", {"stop_from_close": False, "no_fill_hours": (), "tie_is_a_swing": False}),
    ("+anchor", {"no_fill_hours": (), "tie_is_a_swing": False}),
    ("+cut", {"tie_is_a_swing": False}),
    ("+tie", {"tie_is_a_swing": True}),
)


def load(where: str) -> list[tuple[Any, list[Any]]]:
    """Every instrument in a catalogue, with its bars and quotes interleaved."""
    book = ParquetDataCatalog(where)
    out = []
    for instrument in book.instruments():
        iid = str(instrument.id)
        bars = book.bars(bar_types=[f"{iid}-15-MINUTE-LAST-EXTERNAL"])
        quotes = book.quote_ticks(instrument_ids=[iid])
        if not bars or not quotes:
            print(f"  {iid}: {len(bars)} bars and {len(quotes)} quotes - skipped")
            continue
        out.append((instrument, sorted([*bars, *quotes], key=lambda d: d.ts_init)))
    return sorted(out, key=lambda row: str(row[0].id))


def line(label: str, found: dict[str, Any]) -> str:
    return (
        f"  {label:<22} n {found['n']:>3}  R/trade {found['mean']:>+7.3f} "
        f"+/-{found['se']:>5.3f}  day-block [{found['lo']:>+6.3f},{found['hi']:>+6.3f}]  "
        f"stop {found['stopped']:>3} clk {found['clocked']:>3}  win {found['win']:>4.0%}  "
        f"cost {found['cost_r']:>5.3f}R"
    )


#: The per-side reach grid. Three symmetric cells and six asymmetric ones, so
#: "best asymmetric minus best symmetric" is a max over 6 against a max over 3.
REACHES: tuple[int, ...] = (25, 50, 100)


def sweep(loaded: list[tuple[Any, list[Any]]], *, overshoot: bool) -> None:
    """Does a swing reach per side beat the symmetric one?

    **The null written before the run.** A per-side reach is two free
    parameters where there was one, so the best of six asymmetric cells beats
    the best of three symmetric ones *by construction*: at 75 trades split by
    side each cell's standard error is about 0.25R, and the max of six draws
    sits about 1.5 standard errors above their median. **This test is blind to
    any per-side effect smaller than roughly 0.4R a trade**, which is larger
    than the whole standing claim for this rule. A positive reading here is
    therefore uninformative and only a *negative* one says anything.

    The null arm is the **mirror**: the same grid with the side of every break
    reversed. If up legs and down legs genuinely want different windows, the
    real grid's asymmetric gain exceeds the mirror's. If the gain is just the
    max of six noisy cells, both arms show the same gain.
    """
    print(f"\n=== per-side swing reach, {len(REACHES)}x{len(REACHES)} cells ===")
    print("  the null: best asymmetric - best symmetric, against the same on the mirror")
    for null in ("", "flip"):
        label = "rule" if not null else "mirror"
        print(f"\n{label}")
        cells: dict[tuple[int, int], dict[str, dict[str, Any]]] = {}
        for up in REACHES:
            for down in REACHES:
                cells[(up, down)] = {}
                pooled: list[Any] = []
                for instrument, data in loaded:
                    arm = Arm(
                        "Sweep",
                        dict(STACK[-1][1]) | {"reach_up": up, "reach_down": down},
                        null=null,
                    )
                    closed, _, _ = run_one(instrument, data, arm)
                    cells[(up, down)][str(instrument.id)] = describe(closed, overshoot=overshoot)
                    pooled.extend(closed)
                cells[(up, down)]["POOLED"] = describe(pooled, overshoot=overshoot)
        keys = ["POOLED", *sorted(k for k in cells[REACHES[0], REACHES[0]] if k != "POOLED")]
        print(f"  {'up/down':<10} " + "  ".join(f"{k.split('.')[0][:7]:>14}" for k in keys))
        for (up, down), found in cells.items():
            row = "  ".join(f"{found[k]['mean']:>+8.3f}/{found[k]['n']:<5}" for k in keys)
            print(f"  {up:>4}/{down:<5} {row}")
        for key in keys:
            sym = {r: cells[(r, r)][key]["mean"] for r in REACHES}
            asym = {k: v[key]["mean"] for k, v in cells.items() if k[0] != k[1]}
            best_sym = max(sym.values())
            best_asym = max(asym.values())
            won = max(asym, key=lambda k: asym[k])
            print(
                f"  {key.split('.')[0]:<22} best symmetric {best_sym:>+7.3f} at "
                f"{max(sym, key=lambda r: sym[r])}  best asymmetric {best_asym:>+7.3f} at "
                f"{won[0]}/{won[1]}  gain {best_asym - best_sym:>+7.3f}R"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalogue", default=str(catalogue()))
    parser.add_argument(
        "--before",
        default="",
        help="a catalogue written before the corpus fix, for `fees`/`contract`",
    )
    parser.add_argument("--overshoot", action="store_true", help="debit 0.035R on every stop exit")
    parser.add_argument("--nulls", action="store_true", help="also run the flip and late arms")
    parser.add_argument("--late", type=int, default=8)
    parser.add_argument("--sweep", action="store_true", help="the per-side reach grid")
    parser.add_argument("--all", action="store_true", help="the stack, the nulls and the sweep")
    parser.add_argument("--out", default=OUT, help="directory for the written report")
    args = parser.parse_args()

    os.environ.setdefault("LOG_LEVEL", "ERROR")
    print(f"catalogue: {args.catalogue}")
    loaded = load(args.catalogue)
    if not loaded:
        print("nothing to run: the catalogue holds no instrument with both bars and quotes")
        return

    if args.before:
        print(f"\n=== the corpus corrections, same code on {args.before} ===")
        print("  `fees` is the FX test instrument's 2 bp; `contract` is gold's 100 ounces")
        for where, tag in ((args.before, "before"), (args.catalogue, "after")):
            pooled: list[Any] = []
            for instrument, data in load(where):
                closed, _, _ = run_one(instrument, data, Arm("Committed", dict(STACK[0][1])))
                found = describe(closed, overshoot=False)
                print(line(f"{tag} {instrument.id.symbol}", found))
                pooled.extend(closed)
            print(line(f"{tag} POOLED", describe(pooled, overshoot=False)))

    if args.sweep and not args.all:
        sweep(loaded, overshoot=args.overshoot)
        return

    print("\n=== the corrections, each one's own row, per instrument ===")
    rows: dict[str, dict[str, dict[str, Any]]] = {}
    for name, knobs in STACK:
        rows[name] = {}
        pooled = []
        print(f"\n{name}")
        for instrument, data in loaded:
            closed, counted, gates = run_one(instrument, data, Arm("Stacked", dict(knobs)))
            found = describe(closed, overshoot=args.overshoot)
            found["structure"] = counted
            found["gates"] = gates
            rows[name][str(instrument.id)] = found
            print(line(str(instrument.id.symbol), found))
            pooled.extend(closed)
        rows[name]["POOLED"] = describe(pooled, overshoot=args.overshoot)
        print(line("POOLED", rows[name]["POOLED"]))

    print("\n=== what each correction moved, in R a trade ===")
    print(f"  {'correction':<14} {'pooled':>9}  per instrument")
    previous = None
    for name, _ in STACK:
        found = rows[name]
        if previous is not None:
            moved = found["POOLED"]["mean"] - rows[previous]["POOLED"]["mean"]
            each = "  ".join(
                f"{key.split('.')[0]} {found[key]['mean'] - rows[previous][key]['mean']:+.3f}"
                for key in found
                if key != "POOLED"
            )
            print(f"  {name:<14} {moved:>+9.3f}  {each}")
        previous = name

    print("\n=== concentration and the stop fill, on the corrected reading ===")
    final = rows[STACK[-1][0]]
    for key, found in final.items():
        if not found["n"]:
            continue
        print(
            f"  {key.split('.')[0]:<22} best {found['best']:>+7.2f}R worst "
            f"{found['worst']:>+6.2f}R  mean without the best {found['ex_best']:>+7.3f}R  "
            f"gross {found['gross_up']:>+7.2f}/{found['gross_down']:>+7.2f}  "
            f"median overshoot past the stop {found['slip_r']:>+6.3f}R"
        )

    if not (args.nulls or args.all):
        return
    print("\n=== the nulls, on the corrected reading ===")
    for null in ("", "flip", "late"):
        pooled = []
        label = null or "rule"
        print(f"\n{label}")
        for instrument, data in loaded:
            arm = Arm("Null", dict(STACK[-1][1]), null=null, late=args.late)
            closed, _, _ = run_one(instrument, data, arm)
            print(line(str(instrument.id.symbol), describe(closed, overshoot=args.overshoot)))
            pooled.extend(closed)
        print(line("POOLED", describe(pooled, overshoot=args.overshoot)))

    if args.all:
        sweep(loaded, overshoot=args.overshoot)


def report() -> None:
    """`main`, with everything it printed also written to `--out/report.txt`."""
    where = Path(
        next(
            (value for flag, value in zip(sys.argv, sys.argv[1:], strict=False) if flag == "--out"),
            OUT,
        )
    )
    where.mkdir(parents=True, exist_ok=True)
    with (where / "report.txt").open("w") as handle, contextlib.redirect_stdout(Tee(handle)):
        main()
    print(f"\nwritten to {where / 'report.txt'}")


if __name__ == "__main__":
    report()
