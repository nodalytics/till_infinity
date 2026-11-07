"""Is `statespace-surprise` at 5m the same rule as at 15m, or a different one?

    ./.secrets/lab.sh run research/harness/fivevsfifteen.py

The desk's intervals are now configurable down to 3m, and enabling 5m would put
the rule in a cell it was never measured in. This measures that cell before any
flag changes.

## It drives production, not a copy of it

`statespace.engine.Engine.observe_bar` folds the bar and
`statespace.proposing.proposal_for` decides, both imported. The rule this repo
runs on is that the thing that measured it and the thing that trades it are the
same thing, and a reimplemented surprise would be a measurement of my
arithmetic rather than of the desk's.

## Two things that would make the comparison a lie

**The horizon is a duration, not a bar count.** Holding "96 bars" means 24
hours at 15m and 8 at 5m, which compares two different trades and flatters the
shorter clock - it gets a tighter stop over a shorter window. Both clocks here
hold for `HOLD_HOURS`.

**The span must be identical.** 50,000 bars is 174 days at 5m and 521 at 15m,
so the raw files cover different markets. Both are cut to their overlap.

## The gates are reported, not assumed

A 5m cell can fail two ways: the rule stops working, or it works and cannot be
afforded. `cost_share` (0.10 of the target) and the 0.16-of-risk spread limit
are the production numbers, and the pass rate under each is printed per clock -
because `a-shorter-clock-multiplies-cost-in-r` says the second failure is the
likely one.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from till_infinity.statespace.config import Settings  # noqa: E402
from till_infinity.statespace.engine import Engine  # noqa: E402
from till_infinity.statespace.proposing import proposal_for  # noqa: E402
from till_infinity.strategies.surprise import SurpriseProfile  # noqa: E402

DATA = Path.home() / "till_infinity" / "data" / "btc"
SYMBOL = "BTCUSD"
FEED = "btcusd"
CLOCKS = {"5m": 300.0, "15m": 900.0}
HOLD_HOURS = 24.0
#: The terminal's quoted round trip, from `btccost.py` 2026-11-07. The per-bar
#: spread column is the one this repository measured as unusable as a level.
COST_PX = 18.86
#: The share of the risk a round trip may cost. `Settings`' own default; read
#: here as a literal because this runs without a node to ask.
SPREAD_LIMIT = 0.16
SEED = 20261107
DRAWS = 2000


def load(label: str) -> dict[str, np.ndarray]:
    with np.load(DATA / f"{SYMBOL}.{label}.npz") as data:
        return {k: data[k] for k in ("time", "open", "high", "low", "close")}


def common_window(frames: dict[str, dict[str, np.ndarray]]) -> tuple[float, float]:
    start = max(float(f["time"][0]) for f in frames.values())
    end = min(float(f["time"][-1]) for f in frames.values())
    return start, end


def race(
    bars: dict[str, np.ndarray], entry_i: int, side: int, risk: float, target: float, bars_held: int
) -> float:
    """R of a 1:2 race from `entry_i`, on the wicks, stop checked first.

    One bar can span both barriers; assuming the favourable one is how a
    backtest invents an edge, so the stop wins a tie.
    """
    close, high, low = bars["close"], bars["high"], bars["low"]
    entry = close[entry_i]
    up = entry + side * target
    down = entry - side * risk
    last = min(entry_i + bars_held, len(close) - 1)
    for k in range(entry_i + 1, last + 1):
        if side > 0:
            if low[k] <= down:
                return -1.0
            if high[k] >= up:
                return target / risk
        else:
            if high[k] >= down:
                return -1.0
            if low[k] <= up:
                return target / risk
    return side * (close[last] - entry) / risk


def run(label: str, seconds: float, bars: dict[str, np.ndarray], rng) -> dict:
    # **The scope has to be set, and the first run of this proved it.**
    # `config.DEFAULT_INTERVALS` is `("1m", "5m")`, so a default `Engine()`
    # folded every 5m bar and rejected all 16,731 fifteen-minute ones as
    # `out_of_scope` - which read as "the rule does not fire at 15m" and was
    # really "nothing was offered in a shape it accepts". The live actor takes
    # its scope from the desks' own bar types, which is why 15m works there.
    engine = Engine(settings=Settings(intervals=tuple(CLOCKS)))
    held = int(round(HOLD_HOURS * 3600.0 / seconds))
    rows: list[dict] = []
    folded = 0
    for i in range(len(bars["close"])):
        payload = {
            "feed": FEED,
            "interval": label,
            "closed": True,
            "time": float(bars["time"][i]),
            "open": float(bars["open"][i]),
            "high": float(bars["high"][i]),
            "low": float(bars["low"][i]),
            "close": float(bars["close"][i]),
            "volume": 0.0,
        }
        readout = engine.observe_bar(payload)
        if readout is None:
            continue
        folded += 1
        proposal = proposal_for(readout, payload)
        if proposal is None:
            continue
        features = proposal.get("features") or {}
        vol_bps = float(features.get("vol_bps") or 0.0)
        stop_vol = float(features.get("stop_vol") or 0.0)
        target_r = float(features.get("target_r") or 0.0)
        side = int(proposal.get("direction") or 0)
        if vol_bps <= 0.0 or stop_vol <= 0.0 or target_r <= 0.0 or side == 0:
            continue
        unit = vol_bps / 1e4 * float(bars["close"][i])
        risk = stop_vol * unit
        target = target_r * risk
        if risk <= 0.0:
            continue
        rows.append(
            {
                "i": i,
                "side": side,
                "risk": risk,
                "target": target,
                "cost_of_target": COST_PX / target,
                "cost_of_risk": COST_PX / risk,
                "surprise": float(features.get("surprise") or 0.0),
            }
        )

    # One position at a time, as the desk holds them.
    taken: list[dict] = []
    free = -1
    for row in rows:
        if row["i"] <= free:
            continue
        taken.append(row)
        free = row["i"] + held
    for row in taken:
        row["r"] = race(bars, row["i"], row["side"], row["risk"], row["target"], held)
        row["net"] = row["r"] - row["cost_of_risk"]
        row["coin"] = race(
            bars, row["i"], int(rng.choice([-1, 1])), row["risk"], row["target"], held
        ) - row["cost_of_risk"]

    return {
        "label": label,
        "bars": len(bars["close"]),
        "folded": folded,
        "proposals": len(rows),
        "taken": taken,
        "held": held,
        # `observe_bar` returns None for six different reasons and the engine
        # counts each, which is the only way to tell "nothing fired" from
        # "nothing was offered in a shape it accepts".
        "tally": dict(engine.tally),
    }


def report(name: str, values: list[float], rng) -> None:
    if len(values) < 8:
        print(f"    {name:26s} n {len(values):5d}   too few")
        return
    arr = np.asarray(values)
    boots = [float(arr[rng.integers(0, len(arr), len(arr))].mean()) for _ in range(DRAWS)]
    print(
        f"    {name:26s} n {len(arr):5d}  meanR {arr.mean():+7.3f} "
        f"[{np.percentile(boots, 2.5):+7.3f},{np.percentile(boots, 97.5):+7.3f}]  "
        f"hit {np.mean(arr > 0):.3f}"
    )


def main() -> int:
    rng = np.random.default_rng(SEED)
    frames = {label: load(label) for label in CLOCKS}
    start, end = common_window(frames)
    print(f"common window {(end - start) / 86400.0:.1f} days\n")
    cut = {}
    for label, frame in frames.items():
        keep = (frame["time"] >= start) & (frame["time"] <= end)
        cut[label] = {k: v[keep] for k, v in frame.items()}

    share = SurpriseProfile.cost_share
    print(f"cost gate {share:.0%} of target, spread limit {SPREAD_LIMIT:.0%} of risk, "
          f"round trip {COST_PX:g} px, hold {HOLD_HOURS:g}h\n")

    for label, seconds in CLOCKS.items():
        got = run(label, seconds, cut[label], rng)
        taken = got["taken"]
        print(
            f"=== {label} ===  {got['bars']} bars, {got['folded']} readouts, "
            f"{got['proposals']} proposals, {len(taken)} non-overlapping, hold {got['held']} bars"
        )
        print(f"    engine tally: {got['tally']}")
        if not taken:
            print("    nothing fired\n")
            continue
        of_target = np.asarray([r["cost_of_target"] for r in taken])
        of_risk = np.asarray([r["cost_of_risk"] for r in taken])
        print(
            f"    cost: median {np.median(of_target):.1%} of target "
            f"({np.mean(of_target <= share):.1%} inside {share:.0%}), "
            f"{np.median(of_risk):.1%} of risk "
            f"({np.mean(of_risk <= SPREAD_LIMIT):.1%} inside {SPREAD_LIMIT:.0%})"
        )
        affordable = [r for r in taken if r["cost_of_target"] <= share and r["cost_of_risk"] <= SPREAD_LIMIT]
        report("gross, all proposals", [r["r"] for r in taken], rng)
        report("net, all proposals", [r["net"] for r in taken], rng)
        report("net, gates passed", [r["net"] for r in affordable], rng)
        report("coin twin, net", [r["coin"] for r in taken], rng)
        print()

    print(
        "Break-even on a 1:2 race is 1/3 before cost. The comparison that matters is\n"
        "`net, gates passed` between the clocks: a 5m cell that fires more often and\n"
        "nets less is a different rule, not a faster one."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
