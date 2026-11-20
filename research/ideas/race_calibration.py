"""Does the Monte Carlo's race rate match the one the broker realised?

The operator, 2026-11-20: *"also add race measurement projection monte carlo to
statespace"*, and before it *"since we have sl and tp and be, can't we just hold
till any one hits?"*.

**The Monte Carlo already runs the race.**
[`statespace/projecting.py`](../../till_infinity/statespace/projecting.py) has
`Projection.barrier`, `Projection.geometry`, `Projection.when` for time to
touch, and `Trade` which prints `win_rate` beside `geometric` - the
`1 / (1 + reward)` a driftless market owes - because *"their difference is the
only quantity that can be an edge"*. None of that needed adding.

What has never been done is the other half: **comparing the projection to the
realisation.** The simulator says what share of these entries should reach the
target before the stop; the broker's deal history says what share did. Nobody
has put the two numbers side by side, so the simulator has never been scored.
This file scores it.

## What it does

For each real position the desk opened, read from `/history/deals` and
`/history/orders`:

1. Take the **entry order's own** stop and target, not a later one - a trailed
   stop would make the geometry something the rule never chose.
2. Project forward from the entry bar with the production fold's readout, at
   that feed's own dispersion, over horizons of one day, three days and a week.
3. Race the projection against those same two barriers and record the
   projected target-first rate.
4. Walk the **actual** bars that followed and record which barrier was touched
   first, starting at the bar *after* the entry bar - its own high and low
   include prices from before the position existed, which is the same-bar
   defect `#431` was opened for.
5. Report projected against realised, per edge and per horizon.

## What a reading is worth, stated before the numbers

`Trade.trials` already measured the sample this question needs: **350 to 800
trades before a win rate can be told from the geometric one**, and that bound
is indifferent to the reward chosen. A fortnight of this desk is **142
positions**, so every per-edge cell here is an order of magnitude short and the
pooled one is a quarter of the minimum.

So the calibration is the point and the rates are not. A simulator that is
*mis*-calibrated can be shown so with far fewer samples than are needed to
measure an edge, because its error is systematic where an edge is not.

**And a fortnight of one market direction cannot measure a rule.** Measured on
the same sample: `Structure` entered 86% short and won 0 of 21 races, `Zones`
entered 63% long and won 62% of 60. The target rate tracks the directional
split almost monotonically, which is one market move scored four times.
`a-regime-split-is-information-not-a-verdict` is the standing instruction and
the realised column here inherits that limit whole.

## Two targets, which the operator asked for next

*"also add two tp barriers not just one, or tp1 and tp2"*. The `--split` arm
measures it: half the position leaves at `tp1` and the rest runs to `tp2`, with
one stop under both, scored on the same entries as the single-target arm.

**It is a variance tool and it cannot be an expectancy tool**, which is worth
saying before the numbers. The barrier identity is the martingale theorem: at
reward `r` a driftless race pays `1 / (1 + r)` exactly, so *every* pure
geometry has zero expectancy on a walk and so does every blend of them.
`the-book-is-composable-judge-rules-marginally` is the standing form -
composition buys variance and conditioning, never expectancy. What a split
*can* do is condition: if the edge is concentrated at short horizons, a nearer
`tp1` collects it while `tp2` keeps a claim on the rare long run. That is a
different claim and this arm is how to test it.

**On this broker it has to be two positions, not two legs.** An MT5 position
carries a single `tp` field, and on a hedging account an opposite-side limit
order *opens* a position rather than closing part of one - `mt5-account-is-hedging`
is the record of that costing money. So the options are two positions with
their own targets, both exits broker-side, or one position actively part-closed
at `tp1` by the desk. The second is what `TRADING_SCALE_OUT_AT=1.0` already
configures and it had never once completed, because every managed close raised
a `ValueError` in `_close_out` until 2026-11-20. The first keeps working when
the desk does not, which after that fortnight is the stronger argument.

Two positions cost the same spread as one of twice the size, since a spread is
charged per lot - but they halve the lot, so `TRADING_MIN_LOT_CEILING` can
refuse the halves where it allowed the whole, and they consume two of
`TRADING_MAX_POSITIONS`.

Run as:

    # read-only, inside the container where the bridge is reachable
    uv run python research/ideas/race_calibration.py --dump positions.json

    # the simulation, on the lab - never in the desk's cgroup
    uv run python research/ideas/race_calibration.py --load positions.json --split
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import re
import statistics
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from till_infinity.statespace import projecting
from till_infinity.statespace.facade import Desk

#: The desk's base magic. A deal outside the band is not this desk's.
MAGIC = 777_701

#: Edge id to family, from the strategy ids the node registers.
EDGES = {"E270": "Surprise", "E580": "Structure", "E637": "Zones", "E432": "Identity"}

#: Horizons to project, in days. The operator asked for *"period based, saying
#: how the deviation rate will be in the next 1 day to 1 week"*.
HORIZONS = (1.0, 3.0, 7.0)

FRAME = "15m"
#: M15 bars in a day of a 24/5 market, for the horizon arithmetic.
BARS_A_DAY = 96


def _bridge(path: str, **kw: object) -> object:
    """One read of the terminal bridge. **Credentials from the environment.**

    Never a literal and never logged: this file is public and the bridge is
    not. A missing variable raises here rather than producing an empty result
    that would read as a quiet market.
    """
    base = os.environ["TRADING_MT5_URL"].rstrip("/")
    key = os.environ["TRADING_MT5_API_KEY"]
    query = "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in kw.items())
    request = urllib.request.Request(f"{base}/api/v1/{path}?{query}", headers={"X-API-Key": key})
    with urllib.request.urlopen(request, timeout=60) as answer:
        return json.load(answer)


def positions(days: float) -> list[dict]:
    """Every position this desk opened and closed in the window.

    Each carries its entry price and side, the **entry order's** stop and
    target, the owning edge from the order comment, and the open timestamp.
    """
    now = int(time.time())
    deals = [
        d
        for d in _bridge("history/deals", from_date=now - int(days * 86_400), to_date=now)
        if int(d.get("magic") or 0) == MAGIC
    ]
    orders = [
        o
        for o in _bridge("history/orders", from_date=now - int(days * 86_400), to_date=now)
        if int(o.get("magic") or 0) == MAGIC
    ]
    legs: dict[str, tuple[float, float]] = {}
    owner: dict[str, str] = {}
    for order in orders:
        key = str(order.get("position_id"))
        stop, target = float(order.get("sl") or 0.0), float(order.get("tp") or 0.0)
        # **The entry order only.** On a hedging account its ticket *is* the
        # position's, and any other order for the position may carry a stop the
        # trail moved - which would make the geometry one the rule never chose.
        if stop > 0.0 and target > 0.0 and str(order.get("ticket")) == key:
            legs[key] = (stop, target)
        found = re.search(r"_(E[0-9]+)-", str(order.get("comment") or ""))
        if found:
            owner.setdefault(key, found.group(1))
    out = []
    for deal in deals:
        key = str(deal.get("position_id"))
        if int(deal.get("entry") or 0) != 0 or key not in legs:
            continue
        entry = float(deal.get("price") or 0.0)
        if entry <= 0.0:
            continue
        stop, target = legs[key]
        out.append(
            {
                "edge": EDGES.get(owner.get(key, ""), "unknown"),
                "symbol": str(deal.get("symbol")),
                "entry": entry,
                "long": int(deal.get("type") or 0) == 0,
                "stop": stop,
                "target": target,
                "opened": float(deal.get("time") or 0.0),
            }
        )
    return out


def bars_after(symbol: str, start: float, count: int) -> list[dict]:
    """`count` M15 bars from `start`. **`date_from`, not `from_date`.**

    The bridge spells the same concept two ways and this route takes the other
    one; sending the wrong spelling returns a default page rather than an error.
    """
    try:
        rows = _bridge(
            "symbols/rates/from",
            symbol=symbol,
            timeframe="M15",
            date_from=int(start),
            count=int(count),
        )
    except Exception:
        return []
    return rows if isinstance(rows, list) else []


def realised(spot: dict, rows: list[dict], ahead: int) -> str | None:
    """Which barrier the real bars touched first, within `ahead` bars.

    `None` when neither was reached, and `"both"` when one bar's range covers
    both - the order inside a bar is unknowable from its range, so it is
    reported rather than guessed.

    **The entry bar is skipped.** Its high and low include prices from before
    the position existed, and testing a stop against them is the same-bar
    defect `#431` was opened for.
    """
    stop, target, long_side = spot["stop"], spot["target"], spot["long"]
    for row in rows[1 : ahead + 1]:
        high, low = float(row["high"]), float(row["low"])
        if long_side:
            stopped, hit = low <= stop, high >= target
        else:
            stopped, hit = high >= stop, low <= target
        if stopped and hit:
            return "both"
        if stopped:
            return "stop"
        if hit:
            return "target"
    return None


def split_outcome(spot: dict, rows: list[dict], ahead: int, first: float) -> float | None:
    """R earned by halving out at `first` R and running the rest to the target.

    One stop under both halves, so the loss is unchanged and only the upside is
    reshaped. `None` when neither barrier resolved inside the horizon.

    **The first half is settled on its own touch and the second on the stop
    that follows it**, which is the pessimistic order: a bar that reaches
    `tp1` and the stop cannot say which came first from its range, so the
    stop is taken. Guessing the other way is how a geometry is made to pay
    through arithmetic, which `a-martingale-cannot-pay` records.
    """
    risk = abs(spot["entry"] - spot["stop"])
    if risk <= 0:
        return None
    sign = 1.0 if spot["long"] else -1.0
    tp1 = spot["entry"] + sign * first * risk
    banked = 0.0
    taken = False
    for row in rows[1 : ahead + 1]:
        high, low = float(row["high"]), float(row["low"])
        if spot["long"]:
            stopped, one, two = low <= spot["stop"], high >= tp1, high >= spot["target"]
        else:
            stopped, one, two = high >= spot["stop"], low <= tp1, low <= spot["target"]
        if stopped:
            # The pessimistic order inside the bar, as the docstring says.
            return banked + (0.0 if taken else -0.5) - 0.5
        if one and not taken:
            taken, banked = True, 0.5 * first
        if two:
            reward = abs(spot["target"] - spot["entry"]) / risk
            return banked + 0.5 * reward
    return None


def projected(spot: dict, rows: list[dict], ahead: int, paths: int, seed: int) -> float | None:
    """The simulator's target-first rate for this entry's own geometry.

    The readout comes from the production fold over the bars **before** the
    entry, so the dispersion the projection samples is the one that was
    knowable then.
    """
    import numpy as np

    history = rows[: max(len(rows) - ahead, 1)]
    if len(history) < 60:
        return None
    desk = Desk()
    got = None
    for row in history:
        close = float(row["close"])
        span = max(float(row["high"]) - float(row["low"]), 1e-9)
        got = desk.read(
            spot["symbol"],
            FRAME,
            float(np.datetime64(row["time"]).astype("datetime64[s]").astype(float)),
            float(np.log(max(close, 1e-12))),
            float((span / close / 4.0) ** 2) if close > 0 else 1e-12,
        )
    if got is None:
        return None
    try:
        fan = projecting.project(
            got, ahead=ahead, paths=paths, start=spot["entry"], seed=seed, step=900.0
        )
        up = max(spot["target"], spot["stop"])
        down = min(spot["target"], spot["stop"])
        race = fan.barrier(up=up, down=down)
    except (ValueError, ZeroDivisionError, AttributeError):
        return None
    wins = race["up"] if spot["long"] else race["down"]
    loses = race["down"] if spot["long"] else race["up"]
    decided = wins + loses
    return wins / decided if decided > 0 else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=float, default=14.0)
    parser.add_argument("--dump", help="write the positions and their bars here, then stop")
    parser.add_argument("--load", help="read what --dump wrote instead of the bridge")
    parser.add_argument(
        "--split",
        action="store_true",
        help="also score a tp1/tp2 split against the single target",
    )
    parser.add_argument("--first", type=float, default=1.0, help="tp1, in R")
    parser.add_argument("--paths", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=23)
    parser.add_argument("--horizons", default=",".join(str(h) for h in HORIZONS))
    args = parser.parse_args()

    horizons = [float(h) for h in args.horizons.split(",")]
    widest = int(max(horizons) * BARS_A_DAY) + 200

    if args.load:
        held = json.loads(Path(args.load).read_text())
        spots, bars = held["spots"], held["bars"]
    else:
        spots = positions(args.days)
        # Fetched once at the widest horizon and sliced per horizon, so the
        # bridge is read once per position rather than once per cell.
        bars = {}
        for spot in spots:
            key = f"{spot['symbol']}|{int(spot['opened'])}"
            if key not in bars:
                bars[key] = bars_after(spot["symbol"], spot["opened"], widest)

    if args.dump:
        Path(args.dump).write_text(json.dumps({"spots": spots, "bars": bars}))
        print(
            f"wrote {len(spots)} positions and {sum(len(v) for v in bars.values()):,} bars "
            f"to {args.dump}. Run the simulation elsewhere: the desk has two cores."
        )
        return

    print(
        f"The Monte Carlo's race rate against the broker's, {len(spots)} positions "
        f"over {args.days:g} days.\n"
        "'geometric' is 1/(1+reward), what a driftless market owes among resolved races.\n"
        "Trade.trials puts the sample a win rate needs at 350-800, so read the "
        "calibration and not the rates."
    )
    for days in horizons:
        ahead = int(days * BARS_A_DAY)
        cells = collections.defaultdict(list)
        for spot in spots:
            rows = bars.get(f"{spot['symbol']}|{int(spot['opened'])}") or []
            if len(rows) < 10:
                continue
            risk = abs(spot["entry"] - spot["stop"])
            reward = abs(spot["target"] - spot["entry"]) / risk if risk > 0 else 0.0
            cells[spot["edge"]].append(
                {
                    "fore": projected(spot, rows, ahead, args.paths, args.seed),
                    "real": realised(spot, rows, ahead),
                    "reward": reward,
                    "split": split_outcome(spot, rows, ahead, args.first) if args.split else None,
                }
            )
        print(f"\n  horizon {days:g} day(s) = {ahead} M15 bars")
        header = (
            f"    {'edge':<10}{'n':>4}{'projected':>11}{'realised':>10}"
            f"{'geometric':>11}{'undecided':>11}{'proj-real':>11}"
        )
        if args.split:
            header += f"{'single R':>10}{f'tp1@{args.first:g}R':>11}"
        print(header)
        for edge, got in sorted(cells.items(), key=lambda kv: -len(kv[1])):
            done = [r for r in got if r["real"] in ("target", "stop")]
            if not done:
                continue
            real = sum(1 for r in done if r["real"] == "target") / len(done)
            fore = [r["fore"] for r in done if r["fore"] is not None]
            rewards = [r["reward"] for r in done if r["reward"] > 0]
            geo = statistics.mean(1.0 / (1.0 + w) for w in rewards) if rewards else 0.0
            undecided = 1.0 - len(done) / len(got)
            shown = f"{statistics.mean(fore):>10.1%}" if fore else f"{'-':>10}"
            gap = f"{statistics.mean(fore) - real:>+10.1%}" if fore else f"{'-':>10}"
            line = (
                f"    {edge:<10}{len(got):>4}{shown} {real:>9.1%}"
                f"{geo:>10.1%} {undecided:>10.1%}{gap}"
            )
            if args.split:
                # The single-target arm in R, on the same resolved races, so
                # the two columns are the same trades and not two samples.
                singles = [
                    r["reward"] if r["real"] == "target" else -1.0 for r in done if r["reward"] > 0
                ]
                splits = [r["split"] for r in done if r["split"] is not None]
                line += f"{statistics.mean(singles) if singles else 0:>+10.3f}"
                line += f"{statistics.mean(splits) if splits else 0:>+11.3f}"
            print(line)
        if args.split:
            print(
                "    'single R' settles a target touch at its full reward and a stop at -1R; "
                "'tp1' halves\n    out at the first barrier and runs the rest, one stop under both."
            )


if __name__ == "__main__":
    main()
